import re

from django.core.exceptions import ValidationError
from tronpy.exceptions import BadAddress, BadSignature
from tronpy.keys import Signature, to_base58check_address

_SIGNATURE_PATTERN = re.compile(r"^(?:0x)?[0-9a-fA-F]{130}$")


def _normalize_tron_address(address: str) -> str:
    value = address.strip()
    if not value:
        raise ValidationError("Enter a valid TRON address.")
    try:
        return to_base58check_address(value)
    except (BadAddress, IndexError, TypeError, ValueError) as error:
        raise ValidationError("Enter a valid TRON address.") from error


def _signature_matches_address(message: str, signature: str, address: str) -> bool:
    value = signature.strip()
    if not _SIGNATURE_PATTERN.fullmatch(value):
        return False
    try:
        parsed_signature = Signature.fromhex(value.removeprefix("0x"))
        public_key = parsed_signature.recover_public_key_from_msg(
            message.encode("utf-8")
        )
    except (BadSignature, IndexError, TypeError, ValueError):
        return False
    return public_key.to_base58check_address() == address
