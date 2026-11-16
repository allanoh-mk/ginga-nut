import hashlib
import hmac
import os
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction

from accounts.models import User

MAX_PUBLIC_KEY_LENGTH = 131_072
MAX_SIGNATURE_LENGTH = 32_768
GPG_TIMEOUT_SECONDS = 8


def _gpg_binary() -> str:
    binary = shutil.which("gpg")
    if binary is None:
        raise ImproperlyConfigured(
            "GnuPG is required for OpenPGP authentication; install the gpg package."
        )
    return binary


def _run_gpg(
    binary: str,
    home: str,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "GNUPGHOME": home,
        "LC_ALL": "C",
        "LANG": "C",
    }
    return subprocess.run(
        [
            binary,
            "--batch",
            "--no-tty",
            "--no-options",
            "--no-autostart",
            "--homedir",
            home,
            *arguments,
        ],
        capture_output=True,
        text=True,
        timeout=GPG_TIMEOUT_SECONDS,
        check=False,
        env=environment,
    )


def verify_openpgp_signature(
    public_key: str,
    signature: str,
    message: str,
    expected_fingerprint: str | None = None,
) -> str | None:
    public_key = public_key.strip()
    signature = signature.strip()
    if (
        len(public_key) > MAX_PUBLIC_KEY_LENGTH
        or not public_key.isascii()
        or not public_key.startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----")
        or len(signature) > MAX_SIGNATURE_LENGTH
        or not signature.isascii()
        or not signature.startswith("-----BEGIN PGP SIGNATURE-----")
    ):
        return None

    binary = _gpg_binary()
    with tempfile.TemporaryDirectory(prefix="market-pgp-") as home:
        os.chmod(home, 0o700)
        key_path = Path(home) / "public-key.asc"
        signature_path = Path(home) / "challenge.asc"
        message_path = Path(home) / "challenge.txt"
        key_path.write_text(public_key + "\n", encoding="ascii")
        signature_path.write_text(signature + "\n", encoding="ascii")
        message_path.write_text(message, encoding="utf-8")
        for path in (key_path, signature_path, message_path):
            os.chmod(path, 0o600)

        try:
            imported = _run_gpg(binary, home, "--import", str(key_path))
            if imported.returncode != 0:
                return None
            listed = _run_gpg(
                binary,
                home,
                "--with-colons",
                "--fingerprint",
                "--list-keys",
            )
            fingerprints: list[str] = []
            awaiting_primary_fingerprint = False
            for line in listed.stdout.splitlines():
                fields = line.split(":")
                if fields[0] == "pub":
                    awaiting_primary_fingerprint = True
                elif fields[0] == "fpr" and awaiting_primary_fingerprint:
                    fingerprints.append(fields[9].upper())
                    awaiting_primary_fingerprint = False
            if listed.returncode != 0 or len(fingerprints) != 1:
                return None
            fingerprint = fingerprints[0]
            if expected_fingerprint is not None and not hmac.compare_digest(
                fingerprint,
                expected_fingerprint.upper(),
            ):
                return None

            verified = _run_gpg(
                binary,
                home,
                "--status-fd=1",
                "--verify",
                str(signature_path),
                str(message_path),
            )
        except subprocess.TimeoutExpired:
            return None
        except (OSError, UnicodeError) as error:
            raise ImproperlyConfigured(
                "OpenPGP verification could not run with the configured GnuPG binary."
            ) from error

        status_lines = verified.stdout.splitlines()
        has_valid_signature = any(
            line.startswith("[GNUPG:] VALIDSIG ") for line in status_lines
        )
        has_revoked_or_expired_key = any(
            line.startswith(
                (
                    "[GNUPG:] EXPKEYSIG ",
                    "[GNUPG:] REVKEYSIG ",
                    "[GNUPG:] KEYEXPIRED ",
                    "[GNUPG:] SIGEXPIRED ",
                )
            )
            for line in status_lines
        )
        if (
            verified.returncode != 0
            or not has_valid_signature
            or has_revoked_or_expired_key
        ):
            return None
        return fingerprint


def create_recovery_codes() -> tuple[list[str], list[str]]:
    codes = [secrets.token_hex(16) for _ in range(10)]
    hashes = [hashlib.sha256(code.encode("ascii")).hexdigest() for code in codes]
    return codes, hashes


@transaction.atomic
def consume_recovery_code(user_id: int, code: str) -> User | None:
    user = User.objects.select_for_update().get(pk=user_id)
    candidate = hashlib.sha256(code.strip().encode("utf-8")).hexdigest()
    for index, stored_hash in enumerate(user.pgp_recovery_code_hashes):
        if hmac.compare_digest(candidate, stored_hash):
            remaining = list(user.pgp_recovery_code_hashes)
            remaining.pop(index)
            user.pgp_recovery_code_hashes = remaining
            user.save(update_fields=("pgp_recovery_code_hashes",))
            return user
    return None
