from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple
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
    """
    In-memory chain manager with fork support.

    Canonical branch policy:
    - first seen wins for same-height competing blocks
    - switch to a competing branch only when it is ahead by at least
      `reorg_threshold` blocks
    """

    def __init__(self, difficulty_bits: int = 20, reorg_threshold: int = 2):
        self.difficulty_bits = difficulty_bits
        self.reorg_threshold = reorg_threshold

        # DAG
        self.blocks_by_hash: Dict[str, Block] = {}
        self.children_by_hash: Dict[str, List[Block]] = {}

        # Branches
        self.tips: Set[str] = set()
        self.best_tip_hash: str = ""

        # Canonical chain view
        self.main_chain_hashes: Set[str] = set()

        # Metrics
        self.accepted_by_miner: Dict[str, int] = {}
        self.rejected_total = 0
        self.rejected_by_reason: Dict[str, int] = {}
        self.forks_detected: int = 0
        self.reorg_count: int = 0
        self.start_time_ms = int(time.time() * 1000)

        self._genesis()

    def _genesis(self) -> None:
        now = int(time.time() * 1000)
        genesis_hash = "0" * 64

        genesis_block = Block(
            height=0,
            prev_hash="0" * 64,
            nonce=0,
            miner_id="genesis",
            mined_timestamp_ms=now,
            accepted_timestamp_ms=now,
            block_hash=genesis_hash,
        )

        self.blocks_by_hash[genesis_hash] = genesis_block
        self.children_by_hash[genesis_hash] = []
        self.tips = {genesis_hash}
        self.best_tip_hash = genesis_hash
        self._recompute_main_chain()

    def best_tip(self) -> Block:
        return self.blocks_by_hash[self.best_tip_hash]

    def height(self) -> int:
        return self.best_tip().height

    def _recompute_main_chain(self) -> None:
        chain_hashes: Set[str] = set()
        cur = self.best_tip_hash

        while True:
            chain_hashes.add(cur)
            blk = self.blocks_by_hash[cur]
            if blk.height == 0:
                break
            cur = blk.prev_hash

        self.main_chain_hashes = chain_hashes

    def orphan_count(self) -> int:
        return len(self.blocks_by_hash) - len(self.main_chain_hashes)

    def get_main_chain_blocks(self, limit: int = 50) -> List[Block]:
        if limit <= 0:
            return []

        out: List[Block] = []
        cur = self.best_tip_hash

        while True:
            out.append(self.blocks_by_hash[cur])
            blk = self.blocks_by_hash[cur]
            if blk.height == 0 or len(out) >= limit:
                break
            cur = blk.prev_hash

        out.reverse()
        return out

    def get_all_blocks(self) -> List[Block]:
        all_b = list(self.blocks_by_hash.values())
        all_b.sort(key=lambda b: (b.height, b.accepted_timestamp_ms))
        return all_b

    def get_recent_blocks(self, limit: int = 50) -> List[Block]:
        if limit <= 0:
            return []

        all_blocks = list(self.blocks_by_hash.values())
        all_blocks.sort(key=lambda b: b.accepted_timestamp_ms, reverse=True)
        return all_blocks[:limit]

    def validate_and_add(
        self,
        height: int,
        prev_hash: str,
        nonce: int,
        miner_id: str,
        mined_ts: int,
    ) -> Tuple[bool, str, Optional[Block]]:
        if prev_hash not in self.blocks_by_hash:
            reason = "prev_hash not found in chain (unknown parent)"
            self._count_reject(reason)
            return False, reason, None

        parent = self.blocks_by_hash[prev_hash]

        if height != parent.height + 1:
            reason = f"wrong height: expected {parent.height + 1}, got {height}"
            self._count_reject(reason)
            return False, reason, None

        bh = sha256_hex(header_bytes(height, prev_hash, nonce))
        if not has_leading_zero_bits(bh, self.difficulty_bits):
            reason = "invalid PoW for current difficulty"
            self._count_reject(reason)
            return False, reason, None

        if bh in self.blocks_by_hash:
            reason = "duplicate block (hash already exists)"
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

        self.blocks_by_hash[bh] = block
        self.children_by_hash.setdefault(bh, [])
        self.children_by_hash.setdefault(prev_hash, []).append(block)

        if len(self.children_by_hash[prev_hash]) == 2:
            self.forks_detected += 1

        self.tips.add(bh)
        if prev_hash in self.tips:
            self.tips.remove(prev_hash)

        self.accepted_by_miner[miner_id] = self.accepted_by_miner.get(miner_id, 0) + 1

        old_best_tip_hash = self.best_tip_hash
        self._update_best_tip(new_block_hash=bh)

        if self.best_tip_hash != old_best_tip_hash:
            if not self._is_ancestor(old_best_tip_hash, self.best_tip_hash):
                self.reorg_count += 1
            self._recompute_main_chain()

        return True, "accepted", block

    def _is_ancestor(self, ancestor_hash: str, descendant_hash: str) -> bool:
        cur = descendant_hash

        while True:
            if cur == ancestor_hash:
                return True

            blk = self.blocks_by_hash[cur]
            if blk.height == 0:
                break

            cur = blk.prev_hash

        return False

    def _update_best_tip(self, new_block_hash: str) -> None:
        current_best_hash = self.best_tip_hash
        current_best = self.blocks_by_hash[current_best_hash]
        new_block = self.blocks_by_hash[new_block_hash]

        # If it extends canonical tip, follow it immediately
        if new_block.prev_hash == current_best_hash:
            self.best_tip_hash = new_block_hash
            return

        # Otherwise switch only if competing branch is ahead by threshold
        if new_block.height >= current_best.height + self.reorg_threshold:
            self.best_tip_hash = new_block_hash
            return

    def avg_block_time_ms(self) -> float:
        chain = self.get_main_chain_blocks(limit=10_000)
        if len(chain) <= 2:
            return 0.0

        times = []
        for i in range(2, len(chain)):
            dt = chain[i].accepted_timestamp_ms - chain[i - 1].accepted_timestamp_ms
            times.append(dt)

        return float(sum(times)) / float(len(times)) if times else 0.0

    def last_block_time_ms(self) -> Optional[int]:
        chain = self.get_main_chain_blocks(limit=10_000)
        if len(chain) < 2:
            return None
        return chain[-1].accepted_timestamp_ms - chain[-2].accepted_timestamp_ms

    def _count_reject(self, reason: str) -> None:
        self.rejected_total += 1
        self.rejected_by_reason[reason] = self.rejected_by_reason.get(reason, 0) + 1

    def uptime_ms(self) -> int:
        return int(time.time() * 1000) - self.start_time_ms