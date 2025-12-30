import hashlib


def header_bytes(height: int, prev_hash: str, nonce: int) -> bytes:
    """
    Build a deterministic "block header" representation.
    In this MVP, the header is just a string containing (height, prev_hash, nonce).
    """
    s = f"{height}|{prev_hash}|{nonce}"
    return s.encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """
    Compute SHA-256 and return the digest as a hex string.
    """
    return hashlib.sha256(data).hexdigest()


def has_leading_zero_bits(hex_hash: str, difficulty_bits: int) -> bool:
    """
    Proof-of-Work check: interpret the hash as an integer and verify:
        int(hash) < 2^(256 - difficulty_bits)

    A higher difficulty_bits means a smaller target and therefore fewer valid hashes.
    """
    # Convert hex string to integer.
    h = int(hex_hash, 16)

    # Compute the target threshold from the difficulty.
    target = 1 << (256 - difficulty_bits)

    # Valid PoW if the hash number is smaller than the target.
    return h < target
