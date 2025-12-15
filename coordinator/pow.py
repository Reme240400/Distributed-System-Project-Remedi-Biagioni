import hashlib


def header_bytes(height: int, prev_hash: str, nonce: int) -> bytes:
    # Simple deterministic header representation
    s = f"{height}|{prev_hash}|{nonce}"
    return s.encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def has_leading_zero_bits(hex_hash: str, difficulty_bits: int) -> bool:
    # Convert hex to int and check top bits are zero.
    # Equivalent: int(hash) < 2^(256 - difficulty_bits)
    h = int(hex_hash, 16)
    target = 1 << (256 - difficulty_bits)
    return h < target
