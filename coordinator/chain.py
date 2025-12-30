from dataclasses import dataclass
from typing import List, Optional, Tuple
import time
from .pow import header_bytes, sha256_hex, has_leading_zero_bits


@dataclass(frozen=True)
class Block:
    """
    Minimal block structure for the MVP chain.

    Note: this is not a full blockchain block format; it is enough to:
    - link blocks together via prev_hash
    - attribute blocks to miners
    - measure timing metrics
    """
    height: int
    prev_hash: str
    nonce: int
    miner_id: str
    mined_timestamp_ms: int
    accepted_timestamp_ms: int
    block_hash: str


class Chain:
    """
    In-memory chain manager (MVP).

    This implementation keeps a single canonical chain (no fork support yet).
    The chain is updated only by the coordinator.
    """

    def __init__(self, difficulty_bits: int = 20):
        self.difficulty_bits = difficulty_bits
        self.blocks: List[Block] = []
        self._genesis()
        # Metrics / counters
        self.accepted_by_miner = {}
        self.rejected_total = 0
        self.rejected_by_reason = {}
        self.start_time_ms = int(time.time() * 1000)


    def _genesis(self) -> None:
        """
        Create a genesis block (height=0) to bootstrap the chain.
        """
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
        """
        Return the last block of the current chain.
        """
        return self.blocks[-1]

    def height(self) -> int:
        """
        Current chain height (tip height).
        """
        return self.tip().height

    def avg_block_time_ms(self) -> float:
        """
        Average time between consecutive accepted blocks (excluding genesis).
        """
        if len(self.blocks) <= 2:
            return 0.0
        times = []
        for i in range(2, len(self.blocks)):
            dt = self.blocks[i].accepted_timestamp_ms - self.blocks[i - 1].accepted_timestamp_ms
            times.append(dt)
        return float(sum(times)) / float(len(times)) if times else 0.0

    def last_block_time_ms(self) -> Optional[int]:
        """
        Time between the last two accepted blocks.
        """
        if len(self.blocks) < 2:
            return None
        return self.blocks[-1].accepted_timestamp_ms - self.blocks[-2].accepted_timestamp_ms

    def validate_and_add(
        self,
        height: int,
        prev_hash: str,
        nonce: int,
        miner_id: str,
        mined_ts: int
    ) -> Tuple[bool, str, Optional[Block]]:

        tip = self.tip()

        if height != tip.height + 1:
            reason = f"wrong height: expected {tip.height + 1}, got {height}"
            self._count_reject(reason)
            return False, reason, None

        if prev_hash != tip.block_hash:
            reason = "prev_hash does not match current tip"
            self._count_reject(reason)
            return False, reason, None

        bh = sha256_hex(header_bytes(height, prev_hash, nonce))
        if not has_leading_zero_bits(bh, self.difficulty_bits):
            reason = "invalid PoW for current difficulty"
            self._count_reject(reason)
            return False, reason, None

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

        # Count accepted block
        self.accepted_by_miner[miner_id] = self.accepted_by_miner.get(miner_id, 0) + 1

        return True, "accepted", block


    def get_last_blocks(self, limit: int = 20) -> List[Block]:
        """
        Return the last `limit` blocks from the chain (including genesis if in range).
        Useful for debugging, dashboards, and demos.
        """
        if limit <= 0:
            return []
        return self.blocks[-limit:]

    def _count_reject(self, reason: str) -> None:
        """
        Update reject counters for observability.
        """
        self.rejected_total += 1
        self.rejected_by_reason[reason] = self.rejected_by_reason.get(reason, 0) + 1

    def uptime_ms(self) -> int:
        """
        Coordinator uptime in milliseconds.
        """
        return int(time.time() * 1000) - self.start_time_ms
