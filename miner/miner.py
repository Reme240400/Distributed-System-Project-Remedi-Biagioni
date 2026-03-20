import time
import random
import requests
import argparse

from coordinator.pow import header_bytes, sha256_hex, has_leading_zero_bits

cached_tpl = None


def fetch_template(coordinator_url: str):
    return requests.get(f"{coordinator_url}/template", timeout=5).json()


def fetch_head(coordinator_url: str):
    return requests.get(f"{coordinator_url}/head", timeout=3).json()


def mine_once(
    coordinator_url: str,
    miner_id: str,
    head_poll_ms: int,
    switch_lag_blocks: int,
    network_delay_min_ms: int,
    network_delay_max_ms: int,
):
    global cached_tpl

    if cached_tpl is None:
        cached_tpl = fetch_template(coordinator_url)

    height = cached_tpl["height"]
    prev_hash = cached_tpl["prev_hash"]
    difficulty_bits = cached_tpl["difficulty_bits"]

    nonce = random.randint(0, 2**32 - 1)
    start = time.time()

    poll_s = (head_poll_ms / 1000.0) if head_poll_ms and head_poll_ms > 0 else 0.0
    next_head_check = time.monotonic() + poll_s if poll_s > 0 else 0.0

    while True:
        bh = sha256_hex(header_bytes(height, prev_hash, nonce))

        if has_leading_zero_bits(bh, difficulty_bits):
            mined_ts = int(time.time() * 1000)

            payload = {
                "height": height,
                "prev_hash": prev_hash,
                "nonce": nonce,
                "miner_id": miner_id,
                "timestamp_ms": mined_ts,
            }

            delay_min_s = max(0, network_delay_min_ms) / 1000.0
            delay_max_s = max(delay_min_s, network_delay_max_ms / 1000.0)
            network_delay = random.uniform(delay_min_s, delay_max_s)
            time.sleep(network_delay)

            r = requests.post(
                f"{coordinator_url}/submit_block",
                json=payload,
                timeout=5
            ).json()

            # If accepted, continue locally on top of THIS block
            if r.get("accepted") and r.get("block_hash") and r.get("height") is not None:
                cached_tpl = {
                    "height": int(r["height"]) + 1,
                    "prev_hash": r["block_hash"],
                    "difficulty_bits": difficulty_bits,
                }
            else:
                # Rejected => resync next time
                cached_tpl = None

            elapsed = time.time() - start
            return r, elapsed, nonce, bh

        nonce = (nonce + 1) & 0xFFFFFFFF

        if poll_s > 0:
            now = time.monotonic()
            if now >= next_head_check:
                next_head_check = now + poll_s
                try:
                    head = fetch_head(coordinator_url)
                    head_height = int(head.get("height", height - 1))

                    # Keep mining locally if behind by 0 or 1 block.
                    # Switch only if behind by >= switch_lag_blocks.
                    if head_height - height >= switch_lag_blocks:
                        latest = fetch_template(coordinator_url)
                        cached_tpl = latest
                        height = latest["height"]
                        prev_hash = latest["prev_hash"]
                        difficulty_bits = latest["difficulty_bits"]
                        nonce = random.randint(0, 2**32 - 1)
                except Exception:
                    pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coordinator", default="http://127.0.0.1:8000")
    parser.add_argument("--miner-id", default="cpu-miner-1")
    parser.add_argument("--head-poll-ms", type=int, default=200)
    parser.add_argument("--switch-lag-blocks", type=int, default=2)
    parser.add_argument("--network-delay-min-ms", type=int, default=0)
    parser.add_argument("--network-delay-max-ms", type=int, default=600)
    args = parser.parse_args()

    print(
        f"[{args.miner_id}] coordinator={args.coordinator} "
        f"device=cpu head_poll_ms={args.head_poll_ms} "
        f"switch_lag={args.switch_lag_blocks}"
    )

    while True:
        res, elapsed, nonce, bh = mine_once(
            args.coordinator,
            args.miner_id,
            args.head_poll_ms,
            args.switch_lag_blocks,
            args.network_delay_min_ms,
            args.network_delay_max_ms,
        )

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