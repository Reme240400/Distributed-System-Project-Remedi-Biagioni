import time
import requests
import argparse
from coordinator.pow import header_bytes, sha256_hex, has_leading_zero_bits


def mine_once(coordinator_url: str, miner_id: str, refresh_every_s: float = 2.0):
    tpl = requests.get(f"{coordinator_url}/template", timeout=5).json()
    height = tpl["height"]
    prev_hash = tpl["prev_hash"]
    difficulty_bits = tpl["difficulty_bits"]

    nonce = 0
    start = time.time()
    last_refresh = start

    while True:
        # Refresh template periodically to avoid mining stale heights forever
        now = time.time()
        if now - last_refresh >= refresh_every_s:
            tpl2 = requests.get(f"{coordinator_url}/template", timeout=5).json()
            height2 = tpl2["height"]
            prev_hash2 = tpl2["prev_hash"]
            if height2 != height or prev_hash2 != prev_hash:
                height, prev_hash, difficulty_bits = height2, prev_hash2, tpl2["difficulty_bits"]
                nonce = 0
            last_refresh = now

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
            r = requests.post(f"{coordinator_url}/submit_block", json=payload, timeout=5).json()
            elapsed = time.time() - start
            return r, elapsed, nonce, bh

        nonce += 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coordinator", default="http://127.0.0.1:8000")
    parser.add_argument("--miner-id", default="cpu-miner-1")
    args = parser.parse_args()

    print(f"[{args.miner_id}] coordinator={args.coordinator}")
    while True:
        res, elapsed, nonce, bh = mine_once(args.coordinator, args.miner_id)
        if res.get("accepted"):
            print(f"[{args.miner_id}] ✅ accepted height={res.get('height')} nonce={nonce} hash={bh[:16]}... time={elapsed:.2f}s")
        else:
            print(f"[{args.miner_id}] ❌ rejected reason={res.get('reason')} (retrying)")
            time.sleep(0.2)


if __name__ == "__main__":
    main()
