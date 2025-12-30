from pydantic import BaseModel, Field
from typing import Optional, List, Dict


class BlockTemplate(BaseModel):
    """
    Block template returned by the coordinator to miners.

    Miners must build a block candidate with:
    - the given height
    - the given prev_hash
    - a nonce that satisfies the PoW difficulty
    """
    height: int
    prev_hash: str

    # Difficulty expressed in "leading zero bits" (via a target threshold).
    difficulty_bits: int = Field(..., ge=1, le=32)


class BlockSubmission(BaseModel):
    """
    Block proposal submitted by a miner to the coordinator.

    The coordinator will:
    - check it extends the current tip (MVP: single-chain only)
    - recompute the hash
    - verify the PoW difficulty
    """
    height: int
    prev_hash: str
    nonce: int

    # Used for attribution and per-miner metrics/logging.
    miner_id: str = Field(..., min_length=1, max_length=64)

    # Miner local timestamp (for observability; coordinator also timestamps acceptance).
    timestamp_ms: int


class BlockAccepted(BaseModel):
    """
    Response to a block submission.
    """
    accepted: bool
    reason: Optional[str] = None
    block_hash: Optional[str] = None
    height: Optional[int] = None


class Metrics(BaseModel):
    """
    Runtime metrics exposed by the coordinator.
    """
    height: int
    blocks_accepted: int
    avg_block_time_ms: float
    last_block_time_ms: Optional[int] = None

    accepted_by_miner: Dict[str, int]
    rejected_total: int
    rejected_by_reason: Dict[str, int]
    uptime_ms: int

class ChainBlock(BaseModel):
    """
    Public representation of a block for inspection/monitoring endpoints.
    """
    height: int
    prev_hash: str
    nonce: int
    miner_id: str
    mined_timestamp_ms: int
    accepted_timestamp_ms: int
    block_hash: str
    
class ChainView(BaseModel):
    """
    Chain snapshot returned by the coordinator.
    """
    tip_height: int
    difficulty_bits: int
    blocks: List[ChainBlock]