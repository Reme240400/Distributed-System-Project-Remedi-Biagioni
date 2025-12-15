from pydantic import BaseModel, Field
from typing import Optional


class BlockTemplate(BaseModel):
    height: int
    prev_hash: str
    difficulty_bits: int = Field(..., ge=1, le=32)
    # client should search for a nonce such that hash(hex_header) has >= difficulty_bits leading zero bits


class BlockSubmission(BaseModel):
    height: int
    prev_hash: str
    nonce: int
    miner_id: str = Field(..., min_length=1, max_length=64)
    timestamp_ms: int  # miner local time, for observability (coordinator will also timestamp)


class BlockAccepted(BaseModel):
    accepted: bool
    reason: Optional[str] = None
    block_hash: Optional[str] = None
    height: Optional[int] = None


class Metrics(BaseModel):
    height: int
    blocks_accepted: int
    avg_block_time_ms: float
    last_block_time_ms: Optional[int] = None
