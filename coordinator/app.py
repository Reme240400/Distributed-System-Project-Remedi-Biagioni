from fastapi import FastAPI
from typing import List
from .models import BlockTemplate, BlockSubmission, BlockAccepted, Metrics, ChainView, ChainBlock
from .chain import Chain
import logging
import os


logger = logging.getLogger("coordinator")
logger.setLevel(logging.INFO)

app = FastAPI(title="Distributed Mining Monitor - Coordinator", version="0.1.0")

DIFFICULTY_BITS = int(os.getenv("DIFFICULTY_BITS", "18"))
REORG_THRESHOLD = int(os.getenv("REORG_THRESHOLD", "2"))

chain = Chain(difficulty_bits=DIFFICULTY_BITS, reorg_threshold=REORG_THRESHOLD)


@app.get("/template", response_model=BlockTemplate)
def get_template() -> BlockTemplate:
    tip = chain.best_tip()
    return BlockTemplate(
        height=tip.height + 1,
        prev_hash=tip.block_hash,
        difficulty_bits=chain.difficulty_bits,
    )


@app.get("/head")
def get_head():
    tip = chain.best_tip()
    return {
        "height": tip.height,
        "block_hash": tip.block_hash,
        "difficulty_bits": chain.difficulty_bits,
    }


@app.post("/submit_block", response_model=BlockAccepted)
def submit_block(sub: BlockSubmission) -> BlockAccepted:
    ok, reason, block = chain.validate_and_add(
        height=sub.height,
        prev_hash=sub.prev_hash,
        nonce=sub.nonce,
        miner_id=sub.miner_id,
        mined_ts=sub.timestamp_ms,
    )

    if not ok:
        logger.info(
            "REJECT miner=%s height=%s reason=%s",
            sub.miner_id, sub.height, reason
        )
        return BlockAccepted(accepted=False, reason=reason)

    logger.info(
        "ACCEPT miner=%s height=%s hash=%s",
        sub.miner_id, block.height, block.block_hash[:16]
    )

    return BlockAccepted(
        accepted=True,
        reason=reason,
        block_hash=block.block_hash if block else None,
        height=block.height if block else None,
    )


@app.get("/metrics", response_model=Metrics)
def get_metrics() -> Metrics:
    return Metrics(
        height=chain.height(),
        blocks_accepted=len(chain.blocks_by_hash) - 1,
        avg_block_time_ms=chain.avg_block_time_ms(),
        last_block_time_ms=chain.last_block_time_ms(),
        accepted_by_miner=chain.accepted_by_miner,
        rejected_total=chain.rejected_total,
        rejected_by_reason=chain.rejected_by_reason,
        uptime_ms=chain.uptime_ms(),
        forks_detected=chain.forks_detected,
        reorg_count=chain.reorg_count,
        orphan_count=chain.orphan_count(),
    )


@app.get("/chain", response_model=ChainView)
def get_chain(limit: int = 20) -> ChainView:
    blocks = chain.get_main_chain_blocks(limit=limit)
    view_blocks = [ChainBlock(**b.__dict__) for b in blocks]

    return ChainView(
        tip_height=chain.height(),
        difficulty_bits=chain.difficulty_bits,
        blocks=view_blocks,
    )


@app.get("/all-blocks", response_model=List[ChainBlock])
def get_all_blocks() -> List[ChainBlock]:
    blocks = chain.get_all_blocks()
    out = []
    for b in blocks:
        cb = ChainBlock(**b.__dict__)
        cb.on_main_chain = (b.block_hash in chain.main_chain_hashes)
        out.append(cb)
    return out


@app.get("/blocks", response_model=ChainView)
def get_blocks(limit: int = 20) -> ChainView:
    blocks = chain.get_recent_blocks(limit=limit)
    view_blocks = [ChainBlock(**b.__dict__) for b in blocks]

    return ChainView(
        tip_height=chain.height(),
        difficulty_bits=chain.difficulty_bits,
        blocks=view_blocks,
    )