from pydantic import BaseModel, Field
from typing import Optional, List, Dict


class BlockTemplate(BaseModel):
    height: int
    prev_hash: str
    difficulty_bits: int = Field(..., ge=1, le=64)


class BlockSubmission(BaseModel):
    height: int
    prev_hash: str
    nonce: int
    miner_id: str = Field(..., min_length=1, max_length=64)
    timestamp_ms: int


class BlockAccepted(BaseModel):
    accepted: bool
    reason: Optional[str] = None
    block_hash: Optional[str] = None
    height: Optional[int] = None
    next_difficulty_bits: Optional[int] = None


class Metrics(BaseModel):
    height: int
    blocks_accepted: int
    avg_block_time_ms: float
    last_block_time_ms: Optional[int] = None

    current_difficulty_bits: int
    blocks_to_next_adjustment: int

    accepted_by_miner: Dict[str, int]
    rejected_total: int
    rejected_by_reason: Dict[str, int]
    uptime_ms: int

    forks_detected: int
    reorg_count: int
    orphan_count: int


class ChainBlock(BaseModel):
    height: int
    prev_hash: str
    nonce: int
    miner_id: str
    mined_timestamp_ms: int
    accepted_timestamp_ms: int
    block_hash: str
    on_main_chain: bool = False


class ChainView(BaseModel):
    tip_height: int
    difficulty_bits: int
    blocks: List[ChainBlock]