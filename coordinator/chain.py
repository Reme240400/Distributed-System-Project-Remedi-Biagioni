from dataclasses import dataclass
from typing import List, Optional, Tuple
import time
from .pow import header_bytes, sha256_hex, has_leading_zero_bits



@dataclass(frozen=True)
class Block:
    height: int
    prev_hash: str
    nonce: int
    miner_id: str
    mined_timestamp_ms: int
    accepted_timestamp_ms: int
    block_hash: str


class Chain:
    def __init__(self, difficulty_bits: int = 20):
        self.difficulty_bits = difficulty_bits
        self.blocks: List[Block] = []
        self._genesis()

    def _genesis(self) -> None:
        now = int(time.time() * 1000)
        genesis_hash = "0" * 64
        self.blocks.append(
            Block(
                height=0,
                prev_hash="0" * 64,
                nonce=0,
                miner_id="genesis",
                mined_timestamp_ms=now,
                accepted_timestamp_ms=now,
                block_hash=genesis_hash,
            )
        )

    def tip(self) -> Block:
        return self.blocks[-1]

    def height(self) -> int:
        return self.tip().height

    def avg_block_time_ms(self) -> float:
        if len(self.blocks) <= 2:
            return 0.0
        times = []
        for i in range(2, len(self.blocks)):
            dt = self.blocks[i].accepted_timestamp_ms - self.blocks[i - 1].accepted_timestamp_ms
            times.append(dt)
        return float(sum(times)) / float(len(times)) if times else 0.0

    def last_block_time_ms(self) -> Optional[int]:
        if len(self.blocks) < 2:
            return None
        return self.blocks[-1].accepted_timestamp_ms - self.blocks[-2].accepted_timestamp_ms

    def validate_and_add(self, height: int, prev_hash: str, nonce: int, miner_id: str, mined_ts: int) -> Tuple[bool, str, Optional[Block]]:
        # Enforce “single chain” rule for MVP: must extend current tip.
        tip = self.tip()
        if height != tip.height + 1:
            return False, f"wrong height: expected {tip.height + 1}, got {height}", None
        if prev_hash != tip.block_hash:
            return False, "prev_hash does not match current tip (forks not supported in MVP)", None

        bh = sha256_hex(header_bytes(height, prev_hash, nonce))
        if not has_leading_zero_bits(bh, self.difficulty_bits):
            return False, "invalid PoW for current difficulty", None

        now = int(time.time() * 1000)
        block = Block(
            height=height,
            prev_hash=prev_hash,
            nonce=nonce,
            miner_id=miner_id,
            mined_timestamp_ms=mined_ts,
            accepted_timestamp_ms=now,
            block_hash=bh,
        )
        self.blocks.append(block)
        return True, "accepted", block
