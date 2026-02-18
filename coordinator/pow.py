# coordinator/pow.py
import hashlib
import struct

def header_bytes(height: int, prev_hash: str, nonce: int) -> bytes:
    """
    Header binario fisso (40 bytes):
      - height uint32 LE (4)
      - prev_hash 32 bytes (da hex)
      - nonce uint32 LE (4)
    """
    prev = bytes.fromhex(prev_hash)
    if len(prev) != 32:
        raise ValueError("prev_hash must be 64 hex chars (32 bytes)")
    return struct.pack("<I", height) + prev + struct.pack("<I", nonce)

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def has_leading_zero_bits(hex_hash: str, difficulty_bits: int) -> bool:
    h = int(hex_hash, 16)
    target = 1 << (256 - difficulty_bits)
    return h < target
