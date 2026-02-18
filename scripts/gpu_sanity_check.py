import os
import sys
import time
import json
import shutil
import platform
import argparse
import subprocess

def run_cmd(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as e:
        return 999, "", str(e)

def hr(title):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)

def info(msg):
    print(f"[INFO] {msg}")

def warn(msg):
    print(f"[WARN] {msg}")

def err(msg):
    print(f"[ERR ] {msg}")

def check_nvidia_tools():
    hr("1) NVIDIA driver / tools check")

    if shutil.which("nvidia-smi") is None:
        err("nvidia-smi non trovato nel PATH. Driver NVIDIA installati?")
        return False
    rc, out, e = run_cmd(["nvidia-smi"])
    if rc != 0:
        err(f"nvidia-smi fallito (rc={rc}): {e[:200]}")
        return False
    info("nvidia-smi OK")
    print(out.splitlines()[0])  # riga top

    if shutil.which("nvcc") is None:
        warn("nvcc non trovato nel PATH (ok se usi solo NVRTC via CuPy).")
    else:
        rc, out, e = run_cmd(["nvcc", "--version"])
        if rc == 0:
            info("nvcc OK")
            tail = "\n".join(out.splitlines()[-4:])
            print(tail)
        else:
            warn(f"nvcc presente ma fallisce (rc={rc}): {e[:200]}")

    return True

def check_python_env():
    hr("2) Python environment check")
    info(f"Python: {sys.version.splitlines()[0]}")
    info(f"Platform: {platform.platform()}")
    info(f"Executable: {sys.executable}")
    info(f"CWD: {os.getcwd()}")

def check_cupy_and_kernel():
    hr("3) CuPy + CUDA runtime + kernel compilation test (consigliato)")

    try:
        import cupy as cp
    except Exception as e:
        err("CuPy non importabile.")
        print("Dettagli:", repr(e))
        print("\nInstall consigliato (CUDA 12):")
        print("  pip install -U cupy-cuda12x")
        return False

    info(f"CuPy version: {cp.__version__}")

    # Runtime info
    try:
        dev = cp.cuda.Device()
        props = cp.cuda.runtime.getDeviceProperties(dev.id)
        name = props.get("name", b"").decode("utf-8", "ignore") if isinstance(props.get("name"), (bytes, bytearray)) else str(props.get("name"))
        cc = f"{props.get('major')}.{props.get('minor')}"
        total_mem = props.get("totalGlobalMem", 0) / (1024**3)
        info(f"GPU[{dev.id}] name: {name}")
        info(f"Compute capability: {cc}")
        info(f"Total VRAM: {total_mem:.2f} GiB")
    except Exception as e:
        err(f"Impossibile leggere device properties: {repr(e)}")
        return False

    # Kernel compilation (NVRTC via RawKernel)
    kernel_src = r'''
    extern "C" __global__
    void add1(const float* x, float* y, int n) {
        int i = (int)(blockIdx.x * blockDim.x + threadIdx.x);
        if (i < n) y[i] = x[i] + 1.0f;
    }
    '''
    try:
        add1 = cp.RawKernel(kernel_src, "add1")
        info("RawKernel compile OK (NVRTC)")
    except Exception as e:
        err("Compilazione RawKernel fallita (NVRTC).")
        print("Dettagli:", repr(e))
        print("\nTipico: mismatch driver/runtime o install CuPy errato.")
        return False

    # Run kernel + perf
    n = 50_000_000  # ~200MB float32 input + 200MB output => carico serio (se VRAM lo consente)
    try:
        info(f"Allocazioni su GPU: n={n} float32 (~{(n*4)/(1024**2):.1f} MiB per array)")
        x = cp.random.random(n, dtype=cp.float32)
        y = cp.empty_like(x)
        cp.cuda.Device().synchronize()

        threads = 256
        blocks = (n + threads - 1) // threads

        t0 = time.perf_counter()
        add1((blocks,), (threads,), (x, y, n))
        cp.cuda.Device().synchronize()
        t1 = time.perf_counter()

        dt = t1 - t0
        # Lettura x + scrittura y => ~ 8 bytes/elem
        gb = (n * 8) / (1024**3)
        info(f"Kernel exec time: {dt:.4f}s  | approx throughput: {gb/dt:.2f} GiB/s")

        # quick correctness
        mx = float(cp.max(cp.abs((y - (x + 1.0)).astype(cp.float32))).get())
        info(f"Correctness max abs error: {mx:.6g}")

    except cp.cuda.memory.OutOfMemoryError:
        warn("OOM su GPU: il test era troppo grande per la tua VRAM.")
        warn("Riduci n dentro lo script (es. 10_000_000) e rilancia.")
        return True
    except Exception as e:
        err(f"Errore durante esecuzione kernel/perf: {repr(e)}")
        return False

    # H2D / D2H copy tests (pinned memory helps, ma qui test base)
    hr("4) Transfer test (H2D / D2H)")
    try:
        import numpy as np
        n2 = 100_000_000  # ~381 MiB float32
        host = np.random.random(n2).astype(np.float32)

        t0 = time.perf_counter()
        dev_arr = cp.asarray(host)  # H2D
        cp.cuda.Device().synchronize()
        t1 = time.perf_counter()

        back = dev_arr.get()  # D2H
        t2 = time.perf_counter()

        h2d = t1 - t0
        d2h = t2 - t1
        gb_h = (host.nbytes) / (1024**3)

        info(f"H2D: {h2d:.4f}s  | {gb_h/h2d:.2f} GiB/s")
        info(f"D2H: {d2h:.4f}s  | {gb_h/d2h:.2f} GiB/s")

        # sanity small check
        if back.shape == host.shape:
            info("Transfer correctness: shape OK")
    except cp.cuda.memory.OutOfMemoryError:
        warn("OOM nel transfer test: riduci n2 (es. 30_000_000) e rilancia.")
    except Exception as e:
        err(f"Errore transfer test: {repr(e)}")

    return True

def check_coordinator(coordinator_url):
    hr("5) Coordinator connectivity test (optional)")
    if not coordinator_url:
        info("Coordinator URL non fornito: skip.")
        return True

    try:
        import requests
    except Exception as e:
        warn("requests non importabile, skip coordinator test.")
        return True

    try:
        r = requests.get(f"{coordinator_url}/template", timeout=3)
        info(f"GET /template -> status {r.status_code}")
        if r.status_code == 200:
            tpl = r.json()
            info("Template keys: " + ", ".join(sorted(tpl.keys())))
            info(f"height={tpl.get('height')} difficulty_bits={tpl.get('difficulty_bits')}")
        else:
            warn(r.text[:200])
        return True
    except Exception as e:
        err(f"Coordinator test fallito: {repr(e)}")
        return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coordinator", default="", help="es: http://127.0.0.1:8000")
    args = parser.parse_args()

    check_python_env()

    ok_driver = check_nvidia_tools()
    ok_cupy = check_cupy_and_kernel()
    ok_coord = check_coordinator(args.coordinator)

    hr("RESULT")
    if ok_driver and ok_cupy and ok_coord:
        print("✅ Tutto OK: pronto per miner full-GPU con kernel custom.")
        sys.exit(0)
    else:
        print("❌ Qualcosa non torna. Fixa i punti [ERR] e rilancia.")
        sys.exit(1)

if __name__ == "__main__":
    main()
