import hashlib

from django.core.exceptions import ValidationError
from tronpy.exceptions import BadAddress
from tronpy.keys import to_base58check_address

_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BECH32_ALPHABET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_GENERATORS = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
_XMR_BLOCK_ENCODED_LENGTHS = (0, 2, 3, 5, 6, 7, 9, 10, 11)
_XMR_BLOCK_DECODED_LENGTHS = {
    length: size for size, length in enumerate(_XMR_BLOCK_ENCODED_LENGTHS)
}


def _decode_base58(value: str) -> bytes:
    number = 0
    for character in value:
        digit = _BASE58_ALPHABET.find(character)
        if digit < 0:
            raise ValueError("Invalid base58 character.")
        number = number * 58 + digit
    decoded = number.to_bytes((number.bit_length() + 7) // 8, "big")
    return b"\x00" * (len(value) - len(value.lstrip("1"))) + decoded


def _validate_base58check(value: str, versions: set[int]) -> str:
    decoded = _decode_base58(value)
    if len(decoded) != 25 or decoded[0] not in versions:
        raise ValueError("Address prefix or length is invalid.")
    checksum = hashlib.sha256(hashlib.sha256(decoded[:-4]).digest()).digest()[:4]
    if checksum != decoded[-4:]:
        raise ValueError("Address checksum is invalid.")
    return value


def _bech32_polymod(values: list[int]) -> int:
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ value
        for bit, generator in enumerate(_BECH32_GENERATORS):
            if (top >> bit) & 1:
                checksum ^= generator
    return checksum


def _convert_witness_program(values: list[int]) -> bytes:
    accumulator = 0
    bits = 0
    decoded = bytearray()
    for value in values:
        accumulator = (accumulator << 5) | value
        bits += 5
        if bits >= 8:
            bits -= 8
            decoded.append((accumulator >> bits) & 0xFF)
    if bits >= 5 or ((accumulator << (8 - bits)) & 0xFF):
        raise ValueError("Invalid witness-program padding.")
    return bytes(decoded)


def _validate_segwit_address(value: str, expected_hrp: str) -> str:
    if value.lower() != value and value.upper() != value:
        raise ValueError("Mixed-case bech32 address.")
    normalized = value.lower()
    if len(normalized) < 8 or len(normalized) > 90:
        raise ValueError("Invalid bech32 length.")
    separator = normalized.rfind("1")
    if separator < 1 or separator + 7 > len(normalized):
        raise ValueError("Invalid bech32 separator.")
    hrp = normalized[:separator]
    if hrp != expected_hrp:
        raise ValueError("Address network prefix is invalid.")
    try:
        data = [_BECH32_ALPHABET.index(char) for char in normalized[separator + 1 :]]
    except ValueError as error:
        raise ValueError("Invalid bech32 character.") from error
    expanded_hrp = [ord(char) >> 5 for char in hrp] + [0]
    expanded_hrp += [ord(char) & 31 for char in hrp]
    checksum = _bech32_polymod(expanded_hrp + data)
    payload = data[:-6]
    if not payload:
        raise ValueError("Missing witness version.")
    version = payload[0]
    if version > 16:
        raise ValueError("Invalid witness version.")
    expected_checksum = 1 if version == 0 else 0x2BC830A3
    if checksum != expected_checksum:
        raise ValueError("Address checksum is invalid.")
    witness_program = _convert_witness_program(payload[1:])
    if not 2 <= len(witness_program) <= 40:
        raise ValueError("Invalid witness program length.")
    if version == 0 and len(witness_program) not in {20, 32}:
        raise ValueError("Invalid version 0 witness program.")
    return normalized


def _decode_xmr_block(encoded: str) -> bytes:
    decoded_length = _XMR_BLOCK_DECODED_LENGTHS.get(len(encoded))
    if decoded_length is None:
        raise ValueError("Invalid Monero block length.")
    number = 0
    for character in encoded:
        digit = _BASE58_ALPHABET.find(character)
        if digit < 0:
            raise ValueError("Invalid Monero base58 character.")
        number = number * 58 + digit
    if number >= 1 << (decoded_length * 8):
        raise ValueError("Invalid Monero block value.")
    return number.to_bytes(decoded_length, "big")


def _validate_monero_address(value: str) -> str:
    if len(value) not in {95, 106}:
        raise ValueError("Invalid Monero address length.")
    full_blocks, remainder = divmod(len(value), 11)
    encoded_blocks = [
        value[index * 11 : (index + 1) * 11] for index in range(full_blocks)
    ]
    if remainder:
        encoded_blocks.append(value[full_blocks * 11 :])
    decoded = b"".join(_decode_xmr_block(block) for block in encoded_blocks)
    if len(decoded) not in {69, 77}:
        raise ValueError("Invalid Monero address payload.")
    prefix = decoded[0]
    if prefix not in {18, 19, 42}:
        raise ValueError("Address prefix is not a Monero mainnet address.")
    if len(decoded) == 77 and prefix != 19:
        raise ValueError("Invalid integrated Monero address.")
    if len(decoded) == 69 and prefix == 19:
        raise ValueError("Invalid integrated Monero address.")
    from tronpy.keys import keccak256

    if keccak256(decoded[:-4])[:4] != decoded[-4:]:
        raise ValueError("Address checksum is invalid.")
    return value


def normalize_payout_address(chain: str, address: str) -> str:
    value = address.strip()
    try:
        if chain == "BTC":
            if value.lower().startswith("bc1"):
                return _validate_segwit_address(value, "bc")
            return _validate_base58check(value, {0, 5})
        if chain == "LTC":
            if value.lower().startswith("ltc1"):
                return _validate_segwit_address(value, "ltc")
            return _validate_base58check(value, {5, 48, 50})
        if chain == "TRC20":
            return to_base58check_address(value)
        if chain == "XMR":
            return _validate_monero_address(value)
    except (BadAddress, IndexError, TypeError, ValueError) as error:
        raise ValidationError(f"Invalid {chain} payout address.") from error
    raise ValidationError(f"Unsupported payout-address chain: {chain}.")
