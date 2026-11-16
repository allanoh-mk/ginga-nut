import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.urls import reverse
from tronpy.keys import PrivateKey

from accounts.models import User
from core.services.create_vendor_profile import create_vendor_profile
from core.services.pgp_auth import create_recovery_codes, verify_openpgp_signature
from core.services.register_user import register_user
from core.services.update_session_expiry import update_session_expiry
from payments.models import WalletLink


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.lock = Lock()

    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> int:
        assert numkeys == 1
        key, limit, window = keys_and_args
        with self.lock:
            attempts = self.values.get(str(key), 0)
            if attempts >= int(limit):
                return 0
            attempts += 1
            self.values[str(key)] = attempts
            if attempts == 1:
                self.ttls[str(key)] = int(window)
            return 1

    def delete(self, name: str) -> int:
        return int(self.values.pop(name, None) is not None)

    def expire_key(self, name: str) -> None:
        self.values.pop(name, None)
        self.ttls.pop(name, None)


@dataclass(frozen=True)
class _PGPIdentity:
    home: str
    public_key: str

    def sign(self, message: str) -> str:
        with tempfile.TemporaryDirectory(prefix="market-pgp-test-") as work:
            message_path = Path(work) / "challenge.txt"
            signature_path = Path(work) / "challenge.asc"
            message_path.write_text(message, encoding="utf-8")
            subprocess.run(
                [
                    shutil.which("gpg") or "gpg",
                    "--batch",
                    "--no-tty",
                    "--no-options",
                    "--homedir",
                    self.home,
                    "--pinentry-mode",
                    "loopback",
                    "--passphrase",
                    "",
                    "--armor",
                    "--detach-sign",
                    "--output",
                    str(signature_path),
                    str(message_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            return signature_path.read_text(encoding="ascii")


@pytest.fixture(scope="session")
def pgp_identity():
    gpg = shutil.which("gpg")
    if gpg is None:
        pytest.fail("GnuPG is required for OpenPGP authentication tests.")
    with tempfile.TemporaryDirectory(prefix="market-pgp-identity-") as home:
        os.chmod(home, 0o700)
        subprocess.run(
            [
                gpg,
                "--batch",
                "--no-tty",
                "--no-options",
                "--homedir",
                home,
                "--pinentry-mode",
                "loopback",
                "--passphrase",
                "",
                "--quick-generate-key",
                "Kola Market Test",
                "ed25519",
                "sign",
                "0",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        exported = subprocess.run(
            [
                gpg,
                "--batch",
                "--no-tty",
                "--no-options",
                "--homedir",
                home,
                "--armor",
                "--export",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        yield _PGPIdentity(home, exported.stdout)
        gpgconf = shutil.which("gpgconf")
        if gpgconf is not None:
            subprocess.run(
                [gpgconf, "--homedir", home, "--kill", "gpg-agent"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )


def _enroll_user(user: User, identity: _PGPIdentity) -> None:
    challenge = "Kola Market OpenPGP authentication\ntest-enrollment-challenge\n"
    fingerprint = verify_openpgp_signature(
        identity.public_key,
        identity.sign(challenge),
        challenge,
    )
    assert fingerprint is not None
    _, recovery_hashes = create_recovery_codes()
    user.pgp_public_key = identity.public_key
    user.pgp_fingerprint = fingerprint
    user.pgp_recovery_code_hashes = recovery_hashes
    user.save(
        update_fields=(
            "pgp_public_key",
            "pgp_fingerprint",
            "pgp_recovery_code_hashes",
        )
    )


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    from core.services import authenticate_user

    client = _FakeRedis()
    monkeypatch.setattr(authenticate_user, "_get_redis_client", lambda: client)
    return client


@pytest.mark.django_db
def test_registration_requires_openpgp_enrollment_before_login(
    client,
    fake_redis: _FakeRedis,
    pgp_identity: _PGPIdentity,
) -> None:
    response = client.post(
        reverse("accounts:register"),
        {
            "username": "buyer_one",
            "password1": "a-very-long-unique-password-8492",
            "password2": "a-very-long-unique-password-8492",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("accounts:pgp_auth")
    assert "_auth_user_id" not in client.session
    response = client.get(response.url)
    response = client.post(
        reverse("accounts:pgp_auth"),
        {
            "public_key": pgp_identity.public_key,
            "signature": pgp_identity.sign(response.context["challenge"]),
        },
    )
    assert response.status_code == 200
    assert len(response.context["recovery_codes"]) == 10
    user = User.objects.get(username="buyer_one")
    assert not hasattr(user, "email")
    assert user.pgp_public_key == pgp_identity.public_key.strip()
    assert len(user.pgp_recovery_code_hashes) == 10
    assert user.session_expiry_seconds == 30 * 60
    assert client.session.get_expiry_age() == 30 * 60


@pytest.mark.django_db
def test_admin_password_login_redirects_to_openpgp_login(client) -> None:
    User.objects.create_superuser(
        username="admin_without_pgp",
        password="a-very-long-unique-password-8492",
    )

    response = client.post(
        "/admin/login/",
        {
            "username": "admin_without_pgp",
            "password": "a-very-long-unique-password-8492",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("accounts:login")
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_admin_requires_a_pgp_verified_session(client) -> None:
    User.objects.create_superuser(
        username="admin_without_marker",
        password="a-very-long-unique-password-8492",
    )
    client.force_login(User.objects.get(username="admin_without_marker"))

    response = client.get("/admin/", follow=True)

    assert response.status_code == 200
    assert response.redirect_chain[0][0].startswith("/admin/login/")
    assert response.request["PATH_INFO"] != "/admin/"


@pytest.mark.django_db
def test_pgp_verified_staff_can_access_admin(
    client,
    fake_redis: _FakeRedis,
    pgp_identity: _PGPIdentity,
) -> None:
    user = User.objects.create_superuser(
        username="admin_with_pgp",
        password="a-very-long-unique-password-8492",
    )
    _enroll_user(user, pgp_identity)
    response = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": "a-very-long-unique-password-8492"},
    )
    challenge_response = client.get(response.url)
    client.post(
        reverse("accounts:pgp_auth"),
        {
            "signature": pgp_identity.sign(challenge_response.context["challenge"]),
        },
    )

    response = client.get("/admin/")

    assert response.status_code == 200
    assert client.session["pgp_verified_user_id"] == user.pk


@pytest.mark.django_db
def test_existing_password_only_session_is_invalidated_in_production(client) -> None:
    from django.test import override_settings

    onion_host = f"{'b' * 56}.onion"
    user = User.objects.create_user(
        username="legacy_session",
        password="a-very-long-unique-password-8492",
    )
    client.force_login(user)

    with override_settings(
        ONION_ONLY=True,
        ONION_HOSTS=[onion_host],
        ALLOWED_HOSTS=[onion_host],
    ):
        response = client.get(
            reverse("accounts:profile"),
            HTTP_HOST=onion_host,
        )

    assert response.status_code == 302
    assert response.url == reverse("accounts:login")
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_registration_rejects_duplicate_username() -> None:
    User.objects.create_user(username="ExistingBuyer", password="unused")

    with pytest.raises(ValidationError, match="username is already taken"):
        register_user("existingbuyer", "a-very-long-unique-password-8492")


@pytest.mark.django_db
def test_login_is_rate_limited_after_configured_failures(
    client,
    fake_redis: _FakeRedis,
) -> None:
    User.objects.create_user(
        username="buyer_two",
        password="a-very-long-unique-password-8492",
    )
    login_url = reverse("accounts:login")
    payload = {"username": "buyer_two", "password": "wrong-password"}

    for _ in range(settings.LOGIN_RATE_LIMIT_ATTEMPTS):
        response = client.post(login_url, payload)
        assert response.status_code == 200
        assert b"Invalid username or password" in response.content

    response = client.post(login_url, payload)
    assert response.status_code == 429
    assert b"Too many attempts" in response.content
    assert fake_redis.values
    assert set(fake_redis.ttls.values()) == {settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS}


@pytest.mark.django_db
def test_login_lockout_expires_with_redis_window(
    client,
    fake_redis: _FakeRedis,
) -> None:
    user = User.objects.create_user(
        username="buyer_three",
        password="a-very-long-unique-password-8492",
    )
    login_url = reverse("accounts:login")
    payload = {"username": user.username, "password": "wrong-password"}

    for _ in range(settings.LOGIN_RATE_LIMIT_ATTEMPTS):
        client.post(login_url, payload)
    blocked = client.post(login_url, payload)
    assert blocked.status_code == 429
    assert b"Too many attempts" in blocked.content

    for key in list(fake_redis.values):
        fake_redis.expire_key(key)

    unblocked = client.post(login_url, payload)
    assert unblocked.status_code == 200
    assert b"Invalid username or password" in unblocked.content
    assert b"Too many attempts" not in unblocked.content


@pytest.mark.django_db
def test_successful_login_clears_failed_attempts(
    client,
    fake_redis: _FakeRedis,
    pgp_identity: _PGPIdentity,
) -> None:
    user = User.objects.create_user(
        username="buyer_four",
        password="a-very-long-unique-password-8492",
    )
    _enroll_user(user, pgp_identity)
    login_url = reverse("accounts:login")
    client.post(login_url, {"username": user.username, "password": "wrong"})
    assert fake_redis.values

    response = client.post(
        login_url,
        {"username": user.username, "password": "a-very-long-unique-password-8492"},
    )

    assert response.status_code == 302
    assert response.url == reverse("accounts:pgp_auth")
    challenge_response = client.get(response.url)
    response = client.post(
        reverse("accounts:pgp_auth"),
        {
            "signature": pgp_identity.sign(challenge_response.context["challenge"]),
        },
    )
    assert response.status_code == 302
    assert response.url == reverse("accounts:profile")
    assert client.session["pgp_verified_user_id"] == user.pk
    assert fake_redis.values == {}


@pytest.mark.django_db
def test_login_requires_openpgp_signature(
    client,
    fake_redis: _FakeRedis,
    pgp_identity: _PGPIdentity,
) -> None:
    user = User.objects.create_user(
        username="pgp_login",
        password="a-very-long-unique-password-8492",
    )
    _enroll_user(user, pgp_identity)

    response = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": "a-very-long-unique-password-8492"},
    )
    assert response.status_code == 302
    assert response.url == reverse("accounts:pgp_auth")
    assert "_auth_user_id" not in client.session

    challenge_response = client.get(response.url)
    response = client.post(
        reverse("accounts:pgp_auth"),
        {"signature": pgp_identity.sign("not the challenge")},
    )
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session

    response = client.post(
        reverse("accounts:pgp_auth"),
        {
            "signature": pgp_identity.sign(challenge_response.context["challenge"]),
        },
    )
    assert response.status_code == 302
    assert response.url == reverse("accounts:profile")
    assert client.session["pgp_verified_user_id"] == user.pk


@pytest.mark.django_db
def test_recovery_code_is_consumed_once(
    client,
    fake_redis: _FakeRedis,
    pgp_identity: _PGPIdentity,
) -> None:
    user = User.objects.create_user(
        username="pgp_recovery",
        password="a-very-long-unique-password-8492",
    )
    _enroll_user(user, pgp_identity)
    codes, hashes = create_recovery_codes()
    user.pgp_recovery_code_hashes = hashes
    user.save(update_fields=("pgp_recovery_code_hashes",))

    response = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": "a-very-long-unique-password-8492"},
    )
    client.get(response.url)
    first_challenge = client.session["pending_pgp_auth"]["challenge"]
    response = client.post(
        reverse("accounts:pgp_auth"),
        {"recovery_code": codes[0]},
    )
    assert response.status_code == 302
    assert response.url == reverse("accounts:profile")
    user.refresh_from_db()
    assert len(user.pgp_recovery_code_hashes) == 9

    client.post(reverse("accounts:logout"))
    response = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": "a-very-long-unique-password-8492"},
    )
    client.get(response.url)
    response = client.post(
        reverse("accounts:pgp_auth"),
        {"recovery_code": codes[0]},
    )
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session
    assert client.session["pending_pgp_auth"]["challenge"] != first_challenge


@pytest.mark.django_db
def test_recovery_code_regeneration_requires_openpgp_challenge(
    client,
    pgp_identity: _PGPIdentity,
) -> None:
    user = User.objects.create_user(
        username="pgp_regenerate",
        password="a-very-long-unique-password-8492",
    )
    _enroll_user(user, pgp_identity)
    previous_hashes = list(user.pgp_recovery_code_hashes)
    client.force_login(user)

    response = client.post(reverse("accounts:regenerate_recovery_codes"))
    assert response.status_code == 302
    challenge_response = client.get(response.url)
    response = client.post(
        reverse("accounts:pgp_auth"),
        {
            "signature": pgp_identity.sign(challenge_response.context["challenge"]),
        },
    )

    assert response.status_code == 200
    assert len(response.context["recovery_codes"]) == 10
    user.refresh_from_db()
    assert len(user.pgp_recovery_code_hashes) == 10
    assert user.pgp_recovery_code_hashes != previous_hashes


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("expiry_seconds", "label"),
    [
        (User.SessionExpiry.THIRTY_MINUTES, "30 minutes"),
        (User.SessionExpiry.ONE_HOUR, "1 hour"),
        (User.SessionExpiry.TWO_HOURS, "2 hours"),
    ],
)
def test_profile_updates_session_expiry(
    client,
    expiry_seconds: int,
    label: str,
) -> None:
    user = User.objects.create_user(
        username=f"profile_{expiry_seconds}",
        password="a-very-long-unique-password-8492",
    )
    client.force_login(user)

    response = client.post(
        reverse("accounts:profile"),
        {"session_expiry_seconds": str(expiry_seconds)},
    )

    assert response.status_code == 302
    user.refresh_from_db()
    assert user.session_expiry_seconds == expiry_seconds
    assert client.session.get_expiry_age() == expiry_seconds
    assert label.encode() in client.get(reverse("accounts:profile")).content


@pytest.mark.django_db
def test_profile_service_rejects_unsupported_session_expiry() -> None:
    user = User.objects.create_user(
        username="profile_invalid",
        password="a-very-long-unique-password-8492",
    )

    with pytest.raises(ValidationError, match="supported session duration"):
        update_session_expiry(user, 4_000)

    user.refresh_from_db()
    assert user.session_expiry_seconds == User.SessionExpiry.THIRTY_MINUTES


@pytest.mark.django_db
def test_logout_requires_post_and_clears_session(client) -> None:
    user = User.objects.create_user(
        username="logout_user",
        password="a-very-long-unique-password-8492",
    )
    client.force_login(user)

    assert client.get(reverse("accounts:logout")).status_code == 405
    response = client.post(reverse("accounts:logout"))

    assert response.status_code == 302
    assert response.url == reverse("accounts:login")
    assert client.get(reverse("accounts:profile")).url.startswith(
        reverse("accounts:login")
    )


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["customer", "vendor", "delivery", "admin"])
def test_profile_displays_role_colored_initials_without_photo(
    client, role: str
) -> None:
    user = User.objects.create_user(
        username="Abacus",
        password="TestOnly-Role-Password-12345",
    )
    if role == "vendor":
        create_vendor_profile(user)
    elif role == "delivery":
        delivery_group, _ = Group.objects.get_or_create(name="delivery")
        user.groups.add(delivery_group)
    elif role == "admin":
        user.is_staff = True
        user.save(update_fields=("is_staff",))
    client.force_login(user)

    response = client.get(reverse("accounts:profile"))

    assert response.status_code == 200
    assert f'role-avatar--{role}"'.encode() in response.content
    assert b">Ab</span>" in response.content
    assert b"<img" not in response.content


@pytest.mark.django_db
def test_single_character_username_has_two_initials(client) -> None:
    user = User.objects.create_user(
        username="a",
        password="TestOnly-Initial-Password-12345",
    )
    client.force_login(user)

    response = client.get(reverse("accounts:profile"))

    assert b'role-avatar--customer"' in response.content
    assert b">Aa</span>" in response.content


@pytest.mark.django_db
def test_wallet_link_pages_verify_signatures_and_retain_unlink_history(client) -> None:
    user = User.objects.create_user(username="wallet-link-user")
    key = PrivateKey(bytes.fromhex("33" * 32))
    address = key.public_key.to_base58check_address()
    client.force_login(user)

    start = client.post(
        reverse("accounts:wallet_challenge_start"),
        {"address": address},
    )
    assert start.status_code == 302
    challenge = user.wallet_link_challenges.get()
    challenge_page = client.get(start.url)
    assert challenge_page.status_code == 200
    assert challenge.message_to_sign.encode() in challenge_page.content
    assert b"private keys" not in challenge_page.content.lower()

    response = client.post(
        start.url,
        {
            "signature": key.sign_msg(challenge.message_to_sign.encode()).hex(),
        },
    )
    assert response.status_code == 302
    assert response.url == reverse("accounts:wallets")
    wallet = WalletLink.objects.get(user=user, address=address)
    assert wallet.unlinked_at is None

    unlink_response = client.post(
        reverse("accounts:unlink_wallet", args=(wallet.pk,)),
    )
    assert unlink_response.status_code == 302
    wallet.refresh_from_db()
    assert wallet.unlinked_at is not None
    assert WalletLink.objects.filter(user=user).count() == 1
