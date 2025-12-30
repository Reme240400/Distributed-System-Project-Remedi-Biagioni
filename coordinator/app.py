from fastapi import FastAPI, HTTPException
from .models import BlockTemplate, BlockSubmission, BlockAccepted, Metrics
from .chain import Chain

# FastAPI app exposing coordinator endpoints used by miners and the dashboard.
app = FastAPI(title="Distributed Mining Monitor - Coordinator", version="0.1.0")

# Global in-memory chain for the MVP.
# Note: This makes the coordinator the single source of truth for the chain state.
chain = Chain(difficulty_bits=18)  # tune for demo speed (e.g., 15–20 on CPU)


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
    """
    ok, reason, block = chain.validate_and_add(
        height=sub.height,
        prev_hash=sub.prev_hash,
        nonce=sub.nonce,
        miner_id=sub.miner_id,
        mined_ts=sub.timestamp_ms,
    )

    if not ok:
        # Rejections usually happen because another miner was faster (stale height),
        # or because the PoW does not match the current difficulty.
        return BlockAccepted(accepted=False, reason=reason)

    return BlockAccepted(
        accepted=True,
        reason=reason,
        block_hash=block.block_hash if block else None,
        height=block.height if block else None,
    )


@app.get("/metrics", response_model=Metrics)
def get_metrics() -> Metrics:
    """
    Expose basic metrics for monitoring and experiments.
    """
    return Metrics(
        height=chain.height(),
        blocks_accepted=len(chain.blocks) - 1,  # exclude genesis
        avg_block_time_ms=chain.avg_block_time_ms(),
        last_block_time_ms=chain.last_block_time_ms(),
    )
