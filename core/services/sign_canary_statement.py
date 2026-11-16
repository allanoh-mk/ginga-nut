import base64
import binascii
import hashlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def sign_canary_statement() -> dict | None:
    statement = settings.CANARY_STATEMENT
    encoded_key = settings.CANARY_SIGNING_KEY
    if not statement or not encoded_key:
        return None
    try:
        private_bytes = base64.b64decode(encoded_key, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImproperlyConfigured(
            "CANARY_SIGNING_KEY must be a base64-encoded Ed25519 private seed."
        ) from exc
    if len(private_bytes) != 32:
        raise ImproperlyConfigured(
            "CANARY_SIGNING_KEY must encode exactly 32 private-key bytes."
        )
    private_key = Ed25519PrivateKey.from_private_bytes(private_bytes)
    public_key = private_key.public_key()
    signature = private_key.sign(statement.encode("utf-8"))
    public_bytes = public_key.public_bytes_raw()
    return {
        "statement": statement,
        "signature": base64.b64encode(signature).decode("ascii"),
        "public_key": base64.b64encode(public_bytes).decode("ascii"),
        "fingerprint": hashlib.sha256(public_bytes).hexdigest().upper(),
    }
