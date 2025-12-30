import time
import requests
import argparse

# Proof-of-Work helper functions:
# - header_bytes: builds the block header used as hash input
# - sha256_hex: computes the SHA-256 hash
# - has_leading_zero_bits: checks if the hash satisfies the difficulty (hash < target)
from coordinator.pow import header_bytes, sha256_hex, has_leading_zero_bits


def mine_once(coordinator_url: str, miner_id: str):
    """
    Performs a single mining attempt:
    - fetches a block template from the coordinator
    - searches for a nonce satisfying the Proof-of-Work
    - submits the block to the coordinator

    Returns:
    - coordinator response
    - mining time
    - nonce found
    - block hash
    """

    # Request the current block template from the coordinator.
    # The template defines the current blockchain state.
    tpl = requests.get(f"{coordinator_url}/template", timeout=5).json()
    height = tpl["height"]
    prev_hash = tpl["prev_hash"]
    difficulty_bits = tpl["difficulty_bits"]

    # The nonce is the only value the miner can freely change.
    nonce = 0

    # Start time used to measure mining duration.
    start = time.time()

    # Proof-of-Work loop: try different nonce values until a valid hash is found.
    while True:
        # Compute the hash for the current block candidate.
        bh = sha256_hex(header_bytes(height, prev_hash, nonce))

        # Check if the hash satisfies the difficulty constraint.
        if has_leading_zero_bits(bh, difficulty_bits):
            # A valid Proof-of-Work has been found.
            mined_ts = int(time.time() * 1000)

            # Block proposal sent to the coordinator.
            payload = {
                "height": height,
                "prev_hash": prev_hash,
                "nonce": nonce,
                "miner_id": miner_id,
                "timestamp_ms": mined_ts,
            }

            # Submit the block to the coordinator for validation.
            r = requests.post(
                f"{coordinator_url}/submit_block",
                json=payload,
                timeout=5
            ).json()

            # Total time spent mining this block.
            elapsed = time.time() - start

            return r, elapsed, nonce, bh

        # Try the next nonce value.
        nonce += 1


def main():
    """
    Miner entry point.
    Parses command-line arguments and continuously mines blocks.
    """

    # Parse command-line arguments.
    parser = argparse.ArgumentParser()
    parser.add_argument("--coordinator", default="http://127.0.0.1:8000")
    parser.add_argument("--miner-id", default="cpu-miner-1")
    args = parser.parse_args()

    print(f"[{args.miner_id}] coordinator={args.coordinator}")

    # Continuous mining loop.
    while True:
        res, elapsed, nonce, bh = mine_once(args.coordinator, args.miner_id)

        # The block is accepted if this miner won the PoW competition.
        if res.get("accepted"):
            print(
                f"[{args.miner_id}] ✅ accepted "
                f"height={res.get('height')} "
                f"nonce={nonce} "
                f"hash={bh[:16]}... "
                f"time={elapsed:.2f}s"
            )
        else:
            # Rejection usually means another miner was faster.
            # The miner waits briefly and then retries.
            print(
                f"[{args.miner_id}] ❌ rejected "
                f"reason={res.get('reason')} (retrying)"
            )
            time.sleep(0.2)


if __name__ == "__main__":
    main()
