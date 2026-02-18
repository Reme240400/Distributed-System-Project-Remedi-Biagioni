import time
import random
import requests
import argparse
import struct

import cupy as cp

# riusa le stesse funzioni PoW del progetto (ora con header binario fisso)
from coordinator.pow import sha256_hex  # solo per stampare hash (da bytes)
TEMPLATE_REFRESH_RATE = 1
template_counter = 0
cached_tpl = None


_SHA256_KERNEL = r'''
extern "C" {

__device__ __forceinline__ unsigned rotr(unsigned x, unsigned n) {
    return (x >> n) | (x << (32 - n));
}
__device__ __forceinline__ unsigned ch(unsigned x, unsigned y, unsigned z) {
    return (x & y) ^ (~x & z);
}
__device__ __forceinline__ unsigned maj(unsigned x, unsigned y, unsigned z) {
    return (x & y) ^ (x & z) ^ (y & z);
}
__device__ __forceinline__ unsigned bsig0(unsigned x) {
    return rotr(x, 2) ^ rotr(x, 13) ^ rotr(x, 22);
}
__device__ __forceinline__ unsigned bsig1(unsigned x) {
    return rotr(x, 6) ^ rotr(x, 11) ^ rotr(x, 25);
}
__device__ __forceinline__ unsigned ssig0(unsigned x) {
    return rotr(x, 7) ^ rotr(x, 18) ^ (x >> 3);
}
__device__ __forceinline__ unsigned ssig1(unsigned x) {
    return rotr(x, 17) ^ rotr(x, 19) ^ (x >> 10);
}

__constant__ unsigned K[64] = {
  0x428a2f98u,0x71374491u,0xb5c0fbcfu,0xe9b5dba5u,0x3956c25bu,0x59f111f1u,0x923f82a4u,0xab1c5ed5u,
  0xd807aa98u,0x12835b01u,0x243185beu,0x550c7dc3u,0x72be5d74u,0x80deb1feu,0x9bdc06a7u,0xc19bf174u,
  0xe49b69c1u,0xefbe4786u,0x0fc19dc6u,0x240ca1ccu,0x2de92c6fu,0x4a7484aau,0x5cb0a9dcu,0x76f988dau,
  0x983e5152u,0xa831c66du,0xb00327c8u,0xbf597fc7u,0xc6e00bf3u,0xd5a79147u,0x06ca6351u,0x14292967u,
  0x27b70a85u,0x2e1b2138u,0x4d2c6dfcu,0x53380d13u,0x650a7354u,0x766a0abbu,0x81c2c92eu,0x92722c85u,
  0xa2bfe8a1u,0xa81a664bu,0xc24b8b70u,0xc76c51a3u,0xd192e819u,0xd6990624u,0xf40e3585u,0x106aa070u,
  0x19a4c116u,0x1e376c08u,0x2748774cu,0x34b0bcb5u,0x391c0cb3u,0x4ed8aa4au,0x5b9cca4fu,0x682e6ff3u,
  0x748f82eeu,0x78a5636fu,0x84c87814u,0x8cc70208u,0x90befffau,0xa4506cebu,0xbef9a3f7u,0xc67178f2u
};

__device__ __forceinline__ bool leading_zero_bits_ok(const unsigned char* d, int bits) {
    int full = bits >> 3;
    int rem  = bits & 7;

    for (int i = 0; i < full; i++) {
        if (d[i] != 0) return false;
    }
    if (rem == 0) return true;
    unsigned char mask = (unsigned char)(0xFFu << (8 - rem));
    return (d[full] & mask) == 0;
}

/*
prefix36 = height(4 LE) + prev_hash(32 bytes)
message = prefix36 + nonce(4 LE) => 40 bytes
padding => single 64-byte block, bitlen=320
*/
__global__ void sha256_search(
    const unsigned char* prefix36,
    unsigned start_nonce,
    unsigned n_nonces,
    int difficulty_bits,
    unsigned* found_nonce,
    unsigned char* found_hash
) {
    unsigned idx = (unsigned)(blockIdx.x * blockDim.x + threadIdx.x);
    if (idx >= n_nonces) return;

    // cheap early exit
    if (atomicAdd(found_nonce, 0) != 0xFFFFFFFFu) return;

    unsigned nonce = start_nonce + idx;

    unsigned char m[64];
    #pragma unroll
    for (int i = 0; i < 36; i++) m[i] = prefix36[i];

    // nonce LE
    m[36] = (unsigned char)(nonce & 0xFFu);
    m[37] = (unsigned char)((nonce >> 8) & 0xFFu);
    m[38] = (unsigned char)((nonce >> 16) & 0xFFu);
    m[39] = (unsigned char)((nonce >> 24) & 0xFFu);

    m[40] = 0x80u;
    #pragma unroll
    for (int i = 41; i < 56; i++) m[i] = 0;

    // bitlen 320 = 0x0000000000000140 (BE)
    m[56]=0; m[57]=0; m[58]=0; m[59]=0;
    m[60]=0; m[61]=0; m[62]=0x01u; m[63]=0x40u;

    unsigned w[64];
    #pragma unroll
    for (int t = 0; t < 16; t++) {
        int j = t * 4;
        w[t] = ((unsigned)m[j] << 24) | ((unsigned)m[j+1] << 16) | ((unsigned)m[j+2] << 8) | (unsigned)m[j+3];
    }
    #pragma unroll
    for (int t = 16; t < 64; t++) {
        w[t] = ssig1(w[t-2]) + w[t-7] + ssig0(w[t-15]) + w[t-16];
    }

    unsigned a=0x6a09e667u, b=0xbb67ae85u, c=0x3c6ef372u, d=0xa54ff53au;
    unsigned e=0x510e527fu, f=0x9b05688cu, g=0x1f83d9abu, h=0x5be0cd19u;

    #pragma unroll
    for (int t = 0; t < 64; t++) {
        unsigned T1 = h + bsig1(e) + ch(e,f,g) + K[t] + w[t];
        unsigned T2 = bsig0(a) + maj(a,b,c);
        h = g; g = f; f = e;
        e = d + T1;
        d = c; c = b; b = a;
        a = T1 + T2;
    }

    unsigned H0=0x6a09e667u + a;
    unsigned H1=0xbb67ae85u + b;
    unsigned H2=0x3c6ef372u + c;
    unsigned H3=0xa54ff53au + d;
    unsigned H4=0x510e527fu + e;
    unsigned H5=0x9b05688cu + f;
    unsigned H6=0x1f83d9abu + g;
    unsigned H7=0x5be0cd19u + h;

    unsigned char dig[32];
    #define STORE32BE(x, off) \
        dig[off+0] = (unsigned char)((x >> 24) & 0xFFu); \
        dig[off+1] = (unsigned char)((x >> 16) & 0xFFu); \
        dig[off+2] = (unsigned char)((x >>  8) & 0xFFu); \
        dig[off+3] = (unsigned char)((x      ) & 0xFFu);

    STORE32BE(H0, 0); STORE32BE(H1, 4); STORE32BE(H2, 8); STORE32BE(H3,12);
    STORE32BE(H4,16); STORE32BE(H5,20); STORE32BE(H6,24); STORE32BE(H7,28);

    if (leading_zero_bits_ok(dig, difficulty_bits)) {
        unsigned expected = 0xFFFFFFFFu;
        if (atomicCAS(found_nonce, expected, nonce) == expected) {
            for (int i = 0; i < 32; i++) found_hash[i] = dig[i];
        }
    }
}

} // extern "C"
'''

_kernel = cp.RawKernel(_SHA256_KERNEL, "sha256_search")


def gpu_search(prefix36: bytes, start_nonce: int, batch: int, difficulty_bits: int):
    if len(prefix36) != 36:
        raise ValueError("prefix36 must be 36 bytes")

    d_prefix = cp.asarray(bytearray(prefix36), dtype=cp.uint8)
    found_nonce = cp.asarray([0xFFFFFFFF], dtype=cp.uint32)
    found_hash = cp.zeros((32,), dtype=cp.uint8)

    threads = 256
    blocks = (batch + threads - 1) // threads

    t0 = time.perf_counter()
    _kernel((blocks,), (threads,), (
        d_prefix,
        cp.uint32(start_nonce),
        cp.uint32(batch),
        cp.int32(difficulty_bits),
        found_nonce,
        found_hash
    ))
    cp.cuda.Device().synchronize()
    t1 = time.perf_counter()

    nonce = int(found_nonce.get()[0])
    if nonce == 0xFFFFFFFF:
        return False, None, None, (t1 - t0)

    hbytes = bytes(found_hash.get().tolist())
    return True, nonce, hbytes, (t1 - t0)


def mine_once(coordinator_url: str, miner_id: str, gpu_batch: int, refresh_rate: int):
    global template_counter, cached_tpl

    if template_counter % refresh_rate == 0 or cached_tpl is None:
        cached_tpl = requests.get(f"{coordinator_url}/template", timeout=5).json()
    template_counter += 1

    height = cached_tpl["height"]
    prev_hash = cached_tpl["prev_hash"]
    difficulty_bits = cached_tpl["difficulty_bits"]

    # prefix36 = height(4 LE) + prev_hash(32 bytes)
    prefix36 = struct.pack("<I", height) + bytes.fromhex(prev_hash)

    start = time.time()
    start_nonce = random.randint(0, 2**32 - 1)

    total_kernel_time = 0.0
    total_tested = 0

    while True:
        found, nonce, hbytes, kdt = gpu_search(prefix36, start_nonce, gpu_batch, difficulty_bits)
        total_kernel_time += kdt
        total_tested += gpu_batch

        if found:
            bh = hbytes.hex()
            mined_ts = int(time.time() * 1000)

            payload = {
                "height": height,
                "prev_hash": prev_hash,
                "nonce": nonce,
                "miner_id": miner_id,
                "timestamp_ms": mined_ts,
            }

            # Simula latenza rete come nel miner CPU
            network_delay = random.uniform(0, 0.6)
            time.sleep(network_delay)

            r = requests.post(f"{coordinator_url}/submit_block", json=payload, timeout=5).json()
            elapsed = time.time() - start

            hashrate = (total_tested / max(total_kernel_time, 1e-9))
            return r, elapsed, nonce, bh, hashrate

        start_nonce = (start_nonce + gpu_batch) & 0xFFFFFFFF


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coordinator", default="http://127.0.0.1:8000")
    parser.add_argument("--miner-id", default="gpu-miner-1")
    parser.add_argument("--gpu-batch", type=int, default=2_000_000)
    parser.add_argument("--template-refresh", type=int, default=1)  # come il tuo
    args = parser.parse_args()

    print(f"[{args.miner_id}] coordinator={args.coordinator} device=gpu batch={args.gpu_batch}")

    while True:
        res, elapsed, nonce, bh, hashrate = mine_once(
            args.coordinator, args.miner_id, args.gpu_batch, args.template_refresh
        )

        if res.get("accepted"):
            print(
                f"[{args.miner_id}] ✅ accepted "
                f"height={res.get('height')} nonce={nonce} hash={bh[:16]}... "
                f"time={elapsed:.2f}s gpu_hashrate≈{hashrate:,.0f} nonces/s"
            )
        else:
            print(f"[{args.miner_id}] ❌ rejected reason={res.get('reason')} (retrying)")
            time.sleep(0.2)


if __name__ == "__main__":
    main()
