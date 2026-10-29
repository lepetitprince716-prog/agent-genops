#!/usr/bin/env python3
"""Time a model's linear-layer GEMMs under sustained load, per kernel and accumulator type.

For each layer shape (K inputs, N outputs) and row count M, with random FP16 operands:

  cublas_f16acc, cublas_f32acc       F.linear with torch's FP16-accumulation flag on and off
  cublaslt_f16acc, cublaslt_f32acc   the same through preferred_blas_library("cublaslt")
  triton_f16acc                      a Triton matmul with an FP16 accumulator, fastest of CONFIGS
  cublas_f16acc_again                the first variant once more, to catch drift

Each variant runs for --seconds while nvidia-smi is sampled (clock, power, throttle reasons), so
the numbers include the card's power limit. The relative error against an FP32 product shows
which accumulator actually ran; the kernel names come from torch.profiler. One line per variant
goes to stdout and, with --out, a JSON record to a JSONL file.

Needs a CUDA GPU, torch 2.7 or later (allow_fp16_accumulation) and, for the Triton variant,
triton. The default shapes are the linear layers of a 3072-wide DiT block (MOSS-Image), with
M = 4352 rows for a 1024x1024 image.

    python3 tools/gemm_probe.py [--shape NAME=K,N ...] [--m M ...] [--seconds S] [--no-triton] [--out FILE]
"""
import argparse
import json
import math
import statistics
import subprocess
import sys
import threading

try:
    import triton
    import triton.language as tl
except ImportError:
    triton = None

SHAPES = {"qkv": (3072, 9216), "o": (3072, 3072), "ffn_up_gate": (3072, 16384), "ffn_down": (8192, 3072)}
# (BM, BN, BK, warps, stages); a config that fails to compile or fit is recorded and skipped.
CONFIGS = [(128, 128, 32, 4, 4), (128, 128, 64, 4, 3), (128, 256, 32, 8, 3), (256, 128, 32, 8, 3),
           (128, 64, 64, 4, 4), (64, 128, 64, 4, 4), (128, 128, 32, 8, 4)]
TUNE_SECONDS = 0.3
SMI_FIELDS = "clocks.sm,power.draw,utilization.gpu,clocks_throttle_reasons.active"
POWER_CAP_BIT = 0x4  # nvidia-smi throttle reason: software power cap
# Dense tensor FLOPs per SM per clock on GeForce Ada (SM 8.9): FP16 inputs with FP16 accumulation,
# and half of that with FP32 accumulation. Efficiency is reported only for those cards.
ADA_GEFORCE_FLOPS = {True: 1024, False: 512}

if triton is not None:
    # Grouped-ordering matmul after the Triton matmul tutorial, with the accumulator kept in FP16.
    @triton.jit
    def mm_f16acc(a_ptr, b_ptr, c_ptr, M, N, K, s_am, s_ak, s_bk, s_bn, s_cm, s_cn,
                  BM: tl.constexpr, BN: tl.constexpr, BK: tl.constexpr, GROUP_M: tl.constexpr):
        pid = tl.program_id(0)
        blocks_m = tl.cdiv(M, BM)
        blocks_n = tl.cdiv(N, BN)
        group = GROUP_M * blocks_n
        first_m = (pid // group) * GROUP_M
        rows = min(blocks_m - first_m, GROUP_M)
        pid_m = first_m + (pid % group) % rows
        pid_n = (pid % group) // rows
        rm = (pid_m * BM + tl.arange(0, BM)) % M
        rn = (pid_n * BN + tl.arange(0, BN)) % N
        rk = tl.arange(0, BK)
        a = a_ptr + rm[:, None] * s_am + rk[None, :] * s_ak
        b = b_ptr + rk[:, None] * s_bk + rn[None, :] * s_bn
        acc = tl.zeros((BM, BN), dtype=tl.float16)
        for _ in range(0, K // BK):
            acc = tl.dot(tl.load(a), tl.load(b), acc, out_dtype=tl.float16)
            a += BK * s_ak
            b += BK * s_bk
        cm = pid_m * BM + tl.arange(0, BM)
        cn = pid_n * BN + tl.arange(0, BN)
        tl.store(c_ptr + cm[:, None] * s_cm + cn[None, :] * s_cn, acc, mask=(cm[:, None] < M) & (cn[None, :] < N))


def triton_linear(torch, x, w, cfg):
    """A callable computing x @ w.T in FP16 with an FP16 accumulator; K must divide by BK."""
    bm, bn, bk, warps, stages = cfg
    m, k = x.shape
    n = w.shape[0]
    if k % bk:
        raise ValueError("K=%d does not divide by BK=%d" % (k, bk))
    c = torch.empty((m, n), device=x.device, dtype=torch.float16)
    wt = w.t()
    grid = (triton.cdiv(m, bm) * triton.cdiv(n, bn),)

    def run():
        mm_f16acc[grid](x, wt, c, m, n, k, x.stride(0), x.stride(1), wt.stride(0), wt.stride(1),
                        c.stride(0), c.stride(1), BM=bm, BN=bn, BK=bk, GROUP_M=8,
                        num_warps=warps, num_stages=stages)
        return c
    return run


class SmiSampler:
    """nvidia-smi samples of one GPU while a variant runs; the summary keeps samples at >= 90 % load."""

    def __init__(self, index, interval_ms):
        self.cmd = ["nvidia-smi", "-i", str(index), "--query-gpu=" + SMI_FIELDS,
                    "--format=csv,noheader,nounits", "-lms", str(interval_ms)]
        self.rows = []

    def __enter__(self):
        self.proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()
        return self

    def _read(self):
        for line in self.proc.stdout:
            parts = [p.strip() for p in line.split(",")]
            try:
                self.rows.append((float(parts[0]), float(parts[1]), float(parts[2]), int(parts[3], 16)))
            except (IndexError, ValueError):
                continue

    def __exit__(self, *exc):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.thread.join(timeout=5)

    def summary(self):
        busy = [r for r in self.rows if r[2] >= 90]
        out = {"samples": len(self.rows), "busy_samples": len(busy)}
        if busy:
            out.update({"clock_mhz": statistics.median(r[0] for r in busy),
                        "power_w": statistics.median(r[1] for r in busy),
                        "power_capped_share": round(sum(1 for r in busy if r[3] & POWER_CAP_BIT) / len(busy), 3)})
        return out


def parse_shape(text):
    name, _, dims = text.partition("=")
    try:
        k, n = (int(v) for v in dims.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("expected NAME=K,N, got %r" % text) from None
    return name, (k, n)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shape", type=parse_shape, action="append", metavar="NAME=K,N",
                    help="layer shape, repeatable (default: the four layers of a 3072-wide DiT block)")
    ap.add_argument("--m", type=int, action="append", help="row count M, repeatable (default 4352)")
    ap.add_argument("--seconds", type=float, default=2.0, help="sustained run per variant (default 2.0)")
    ap.add_argument("--no-triton", action="store_true", help="skip the Triton variant")
    ap.add_argument("--smi-index", type=int, default=0, help="nvidia-smi index of the GPU torch uses (default 0)")
    ap.add_argument("--smi-interval-ms", type=int, default=100)
    ap.add_argument("--out", metavar="FILE", help="append one JSON record per variant to FILE")
    args = ap.parse_args()
    shapes = dict(args.shape) if args.shape else SHAPES
    use_triton = not args.no_triton
    if use_triton and triton is None:
        sys.exit("triton is not installed; pass --no-triton")

    try:
        import torch
        import torch.nn.functional as F
    except ImportError:
        sys.exit("torch is not installed")
    if not torch.cuda.is_available():
        sys.exit("no CUDA device")
    matmul = torch.backends.cuda.matmul
    if not hasattr(matmul, "allow_fp16_accumulation"):
        sys.exit("torch %s has no allow_fp16_accumulation; needs 2.7 or later" % torch.__version__)
    matmul.allow_tf32 = False
    props = torch.cuda.get_device_properties(0)
    ada_geforce = (props.major, props.minor) == (8, 9) and "GeForce" in props.name
    out = open(args.out, "a", encoding="utf-8") if args.out else None
    env = {"event": "env", "device": props.name, "sm_count": props.multi_processor_count,
           "cc": [props.major, props.minor], "torch": torch.__version__, "cuda": torch.version.cuda,
           "triton": triton.__version__ if triton is not None else None}
    print(json.dumps(env))
    if out:
        out.write(json.dumps(env) + "\n")

    def set_mode(lib, f16acc):
        torch.backends.cuda.preferred_blas_library(lib)
        matmul.allow_fp16_accumulation = f16acc

    def timed(fn, seconds):
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)
        fn()
        torch.cuda.synchronize()
        start.record()
        for _ in range(5):
            fn()
        end.record()
        torch.cuda.synchronize()
        iters = max(10, math.ceil(seconds * 1000 / (start.elapsed_time(end) / 5)))
        start.record()
        for _ in range(iters):
            fn()
        end.record()
        torch.cuda.synchronize()
        return start.elapsed_time(end) / iters, iters

    def kernel_names(fn):
        with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CUDA]) as prof:
            for _ in range(3):
                fn()
            torch.cuda.synchronize()
        return sorted({e.key for e in prof.key_averages() if e.device_type == torch.autograd.DeviceType.CUDA})

    def measure(rec, fn, ref, flops, f16acc):
        y = fn().float()
        rec["rel_err"] = float((y - ref).norm() / ref.norm())
        rec["kernels"] = kernel_names(fn)
        with SmiSampler(args.smi_index, args.smi_interval_ms) as smi:
            ms, iters = timed(fn, args.seconds)
        rec.update({"ms": round(ms, 4), "iters": iters, "tflops": round(flops / ms / 1e9, 2), "smi": smi.summary()})
        clock = rec["smi"].get("clock_mhz")
        if ada_geforce and clock:
            peak = props.multi_processor_count * ADA_GEFORCE_FLOPS[f16acc] * clock * 1e6 / 1e12
            rec["efficiency_at_clock"] = round(rec["tflops"] / peak, 3)
        print("%-12s M=%-5d %-20s %8.3f ms %6.1f TFLOPS %6s MHz %6s W cap %5s eff %5s err %.2e  %s" % (
            rec["shape"], rec["m"], rec["variant"], ms, rec["tflops"], rec["smi"].get("clock_mhz", "-"),
            rec["smi"].get("power_w", "-"), rec["smi"].get("power_capped_share", "-"),
            rec.get("efficiency_at_clock", "-"), rec["rel_err"], " ".join(rec["kernels"])[:90]))
        if out:
            out.write(json.dumps(rec) + "\n")
            out.flush()

    torch.manual_seed(0)
    for name, (k, n) in shapes.items():
        w = (torch.randn(n, k, device="cuda") / math.sqrt(k)).half()
        for m in args.m or [4352]:
            x = torch.randn(m, k, device="cuda").half()
            ref = x.float() @ w.float().t()
            flops = 2.0 * m * n * k
            base = {"event": "gemm", "shape": name, "m": m, "k": k, "n": n}
            linear = lambda x=x, w=w: F.linear(x, w)  # noqa: E731
            for variant, lib, f16acc in (("cublas_f16acc", "cublas", True), ("cublas_f32acc", "cublas", False),
                                         ("cublaslt_f16acc", "cublaslt", True), ("cublaslt_f32acc", "cublaslt", False)):
                set_mode(lib, f16acc)
                measure(dict(base, variant=variant), linear, ref, flops, f16acc)
            set_mode("cublas", True)
            if use_triton:
                tune = []
                for cfg in CONFIGS:
                    try:
                        fn = triton_linear(torch, x, w, cfg)
                        tune.append({"cfg": cfg, "ms": round(timed(fn, TUNE_SECONDS)[0], 4)})
                    except Exception as exc:  # does not compile or fit: record and try the next
                        tune.append({"cfg": cfg, "error": repr(exc)[:200]})
                done = [t for t in tune if "ms" in t]
                if done:
                    best = min(done, key=lambda t: t["ms"])["cfg"]
                    measure(dict(base, variant="triton_f16acc", cfg=best, tune=tune),
                            triton_linear(torch, x, w, best), ref, flops, True)
            measure(dict(base, variant="cublas_f16acc_again"), linear, ref, flops, True)
    if out:
        out.close()


if __name__ == "__main__":
    main()
