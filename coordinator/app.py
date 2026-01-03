from fastapi import FastAPI, HTTPException
from .models import BlockTemplate, BlockSubmission, BlockAccepted, Metrics, ChainView, ChainBlock
from .chain import Chain
import logging
import os


logger = logging.getLogger("coordinator")
logger.setLevel(logging.INFO)

# FastAPI app exposing coordinator endpoints used by miners and the dashboard.
app = FastAPI(title="Distributed Mining Monitor - Coordinator", version="0.1.0")

# Global in-memory chain for the MVP.
# Note: This makes the coordinator the single source of truth for the chain state.
DIFFICULTY_BITS = int(os.getenv("DIFFICULTY_BITS", "18"))
chain = Chain(difficulty_bits=DIFFICULTY_BITS)


@app.get("/template", response_model=BlockTemplate)
def get_template() -> BlockTemplate:
    """
    Return the current block template to miners.

    Miners should try to find a nonce such that:
        hash(height | prev_hash | nonce) < target(difficulty)
    """
    tip = chain.tip()
    return BlockTemplate(
        height=tip.height + 1,
        prev_hash=tip.block_hash,
        difficulty_bits=chain.difficulty_bits,
    )


@app.post("/submit_block", response_model=BlockAccepted)
def submit_block(sub: BlockSubmission) -> BlockAccepted:
    """
    Validate a miner block proposal and append it to the chain if valid.
    Logs both accepted and rejected submissions for observability.
    """
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
    """
    Expose runtime metrics for experiments and monitoring.
    """
    return Metrics(
        height=chain.height(),
        blocks_accepted=len(chain.blocks) - 1,  # exclude genesis
        avg_block_time_ms=chain.avg_block_time_ms(),
        last_block_time_ms=chain.last_block_time_ms(),
        accepted_by_miner=chain.accepted_by_miner,
        rejected_total=chain.rejected_total,
        rejected_by_reason=chain.rejected_by_reason,
        uptime_ms=chain.uptime_ms(),
    )


@app.get("/chain", response_model=ChainView)
def get_chain(limit: int = 20) -> ChainView:
    """
    Return a snapshot of the last N blocks.
    This endpoint is meant for humans (inspection) and for dashboards.
    """
    blocks = chain.get_last_blocks(limit=limit)
    view_blocks = [
        ChainBlock(
            height=b.height,
            prev_hash=b.prev_hash,
            nonce=b.nonce,
            miner_id=b.miner_id,
            mined_timestamp_ms=b.mined_timestamp_ms,
            accepted_timestamp_ms=b.accepted_timestamp_ms,
            block_hash=b.block_hash,
        )
        for b in blocks
    ]

    return ChainView(
        tip_height=chain.height(),
        difficulty_bits=chain.difficulty_bits,
        blocks=view_blocks,
    )
