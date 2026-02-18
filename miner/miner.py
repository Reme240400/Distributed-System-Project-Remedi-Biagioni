import time
import random
import requests
import argparse

# Proof-of-Work helper functions
from coordinator.pow import header_bytes, sha256_hex, has_leading_zero_bits

TEMPLATE_REFRESH_RATE = 1
template_counter = 0
cached_tpl = None


def mine_once(coordinator_url: str, miner_id: str, template_refresh_ms: int):
    """
    Performs a single mining attempt:
    - fetches a block template from the coordinator (cached)
    - searches for a nonce satisfying the Proof-of-Work
    - (optional) refreshes template every template_refresh_ms while mining
    - submits the block to the coordinator

    Returns:
    - coordinator response
    - mining time
    - nonce found
    - block hash
    """
    global template_counter, cached_tpl

    # Refresh cached template every TEMPLATE_REFRESH_RATE calls (or first time)
    if template_counter % TEMPLATE_REFRESH_RATE == 0 or cached_tpl is None:
        cached_tpl = requests.get(f"{coordinator_url}/template", timeout=5).json()

    template_counter += 1

    # Load current template fields
    height = cached_tpl["height"]
    prev_hash = cached_tpl["prev_hash"]
    difficulty_bits = cached_tpl["difficulty_bits"]

    # The nonce is the only value the miner can freely change.
    nonce = random.randint(0, 2**32 - 1)

    # Start time used to measure mining duration.
    start = time.time()

    # Optional in-loop polling interval
    refresh_s = (template_refresh_ms / 1000.0) if template_refresh_ms and template_refresh_ms > 0 else 0.0
    next_check = time.monotonic() + refresh_s if refresh_s > 0 else 0.0

    while True:
        # Compute the hash for the current block candidate.
        bh = sha256_hex(header_bytes(height, prev_hash, nonce))

        # Check if the hash satisfies the difficulty constraint.
        if has_leading_zero_bits(bh, difficulty_bits):
            mined_ts = int(time.time() * 1000)

            payload = {
                "height": height,
                "prev_hash": prev_hash,
                "nonce": nonce,
                "miner_id": miner_id,
                "timestamp_ms": mined_ts,
            }

            # Simulate network latency
            network_delay = random.uniform(0, 0.6)
            time.sleep(network_delay)

            # Submit the block to the coordinator for validation.
            r = requests.post(
                f"{coordinator_url}/submit_block",
                json=payload,
                timeout=5
            ).json()

            elapsed = time.time() - start
            return r, elapsed, nonce, bh

        # Try next nonce
        nonce = (nonce + 1) & 0xFFFFFFFF

        # Periodic template check (optional)
        if refresh_s > 0:
            now = time.monotonic()
            if now >= next_check:
                next_check = now + refresh_s
                try:
                    latest = requests.get(f"{coordinator_url}/template", timeout=2).json()

                    new_height = latest.get("height")
                    new_prev = latest.get("prev_hash")
                    new_diff = latest.get("difficulty_bits")

                    # If tip or difficulty changed, restart mining immediately
                    if (new_height != height) or (new_prev != prev_hash) or (new_diff != difficulty_bits):
                        cached_tpl = latest  # update global cache

                        height = new_height
                        prev_hash = new_prev
                        difficulty_bits = new_diff

                        # restart nonce search on the new tip
                        nonce = random.randint(0, 2**32 - 1)

                except Exception:
                    # If coordinator temporarily unreachable, keep mining current template
                    pass


def main():
    """
    Miner entry point.
    Parses command-line arguments and continuously mines blocks.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--coordinator", default="http://127.0.0.1:8000")
    parser.add_argument("--miner-id", default="cpu-miner-1")
    parser.add_argument(
        "--template-refresh-ms",
        type=int,
        default=0,
        help="Polling template every N ms while mining (0=disable)"
    )
    args = parser.parse_args()

    print(
        f"[{args.miner_id}] coordinator={args.coordinator} "
        f"device=cpu refresh_ms={args.template_refresh_ms}"
    )

    while True:
        res, elapsed, nonce, bh = mine_once(args.coordinator, args.miner_id, args.template_refresh_ms)

        if res.get("accepted"):
            print(
                f"[{args.miner_id}] ✅ accepted "
                f"height={res.get('height')} "
                f"nonce={nonce} "
                f"hash={bh[:16]}... "
                f"time={elapsed:.2f}s"
            )
        else:
            print(
                f"[{args.miner_id}] ❌ rejected "
                f"reason={res.get('reason')} (retrying)"
            )
            time.sleep(0.2)


if __name__ == "__main__":
    main()
