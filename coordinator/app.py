from fastapi import FastAPI, HTTPException
from .models import BlockTemplate, BlockSubmission, BlockAccepted, Metrics
from .chain import Chain

app = FastAPI(title="Distributed Mining Monitor - Coordinator", version="0.1.0")

# Global in-memory chain (MVP)
chain = Chain(difficulty_bits=20)  # tweak later for speed; 18-22 usually OK on CPU


@app.get("/template", response_model=BlockTemplate)
def get_template() -> BlockTemplate:
    tip = chain.tip()
    return BlockTemplate(
        height=tip.height + 1,
        prev_hash=tip.block_hash,
        difficulty_bits=chain.difficulty_bits,
    )


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
        return BlockAccepted(accepted=False, reason=reason)

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
        blocks_accepted=len(chain.blocks) - 1,  # excluding genesis
        avg_block_time_ms=chain.avg_block_time_ms(),
        last_block_time_ms=chain.last_block_time_ms(),
    )
