#!/usr/bin/env python3
"""Bound what lifting GeForce's half-rate cap on FP32-accumulate tensor ops could gain a render.

Reads a Chrome trace written by torch.profiler and splits the device kernels by accumulator:

  A  FP16 or BF16 inputs with FP32 accumulation on tensor cores: cuBLAS and CUTLASS s-kernels,
     cuDNN convolution, exact attention. GeForce runs these at half rate; only these can gain.
  B  tensor-core work already at full rate on GeForce: FP16 accumulation (h-kernels), INT8 with
     INT32 accumulation, SageAttention with its PV product accumulated in FP16.
  C  no tensor-core MMA: elementwise, norms, reductions, layout transforms, SIMT GEMV.

A kernel that no rule matches stops the run, so a new tensor kernel cannot drop into C unseen.
Add a rule to RULES, or pass --lenient: unmatched kernels then form class U and every ceiling
becomes a range, with U counted as C at the low end and as A at the high end.

Ceiling for a speed-up s of the A kernels: T' = T - A * (1 - 1/s). See tools/README.md.

    python3 tools/kernel_classes.py TRACE [--seconds T] [--off TRACE_OFF] [--s S ...] [--lenient] [--json OUT]
"""
import argparse
import json
import re
import sys
from typing import NoReturn

# (rule, class, kind, pattern); the first match wins. Template kernels are matched in the mangled
# form the profiler reported on Windows with CUDA 13.0; other stacks may need rules of their own.
RULES = [(rule, cls, kind, re.compile(pattern)) for rule, cls, kind, pattern in [
    ("cublas_gemm_f32acc", "A", "gemm", r"_(?:fp16|bf16)_s(?:1688|16816)gemm"),
    ("cutlass_gemm_f32acc", "A", "gemm", r"tensorop_(?:f16|bf16)_s(?:1688|16816|161616)gemm"),
    ("xmma_gemm_f32acc", "A", "gemm", r"xmma_gemm_\w*?(?:f16f16_f16f32|bf16bf16_bf16f32)"),
    ("cudnn_conv_f32acc", "A", "conv",
     r"xmma_fprop_\w*?(?:f16f16_f16f32|bf16bf16_bf16f32)|tensorop_(?:f16|bf16)_s(?:1688|16816)fprop"),
    ("attention_f32acc", "A", "attention", r"fmha_cutlass|flash_fwd|flash_bwd|_sdpa_\w*?flash_fprop"),
    ("gemm_f16acc", "B", "gemm", r"_h(?:1688|16816|161616)gemm"),
    # comfy-kitchen INT8 attention: Q, K and V are quantized to INT8 by the kernels below, so both
    # products are INT8 with INT32 accumulation. Inferred from the names; the source was not read.
    ("int8_attention", "B", "attention", r"qk_int_sv_i8_attn_kernel"),
    ("int8_attention_quant", "C", "attention", r"quant_v_int8_kernel|quant_qk_fused|detect_k_anchor"),
    ("sage_quant", "C", "attention",
     r"quant_(?:query|key)_per_thread_int8_kernel|TransposePadPermuteKernel|MeanScaleKernel"),
    ("torch_native", "C", "other", r"^_ZN2at6native|RangeFactories_cu"),
    ("cudnn_layout", "C", "other", r"(?:nchwToNhwc|nhwcToNchw)Kernel|tensorTransformGeneric|computeOffsetsKernel"),
    ("kitchen_pointwise", "C", "other",
     r"^_ZN5comfy\w*?_(?:rms_rope|adaln)_cu|quantize_int8_rowwise_convrot\d*_kernel"),
    # No MMA tile in the name: SIMT math (GEMV, small convolutions), which GeForce runs at full rate.
    ("simt", "C", "other", r"implicit_convolve_sgemm|gemmk1_kernel|gemvx\d*kernel|_scudnn_|splitKreduce_kernel"),
]]
# SageAttention's SM89 FP8 kernel: the fifth bool template argument is use_pv_fp16_accu
# (csrc/qattn/qk_int_sv_f8_cuda_sm89.cuh in thu-ml/SageAttention).
SAGE_F8 = re.compile(r"qk_int_sv_f8_attn_kernel")
# comfy-kitchen's CUTLASS GEMMs: the template argument after the C operand's alignment is the
# accumulator, then the float epilogue type. "f" is float, "i" is int (INT8), and a substitution
# such as "S4_" repeats the half input type. Checked with c++filt on the names seen.
KITCHEN_GEMM = re.compile(r"DefaultGemmWithVisitor\w*?Li\d+E(f|i|S\d*_)fNS_4arch15OpClassTensorOp")
LOOKS_TENSOR = re.compile(r"gemm|mma|attn|attention|fprop|conv", re.IGNORECASE)
DEFAULT_S = (1.7, 2.0)


def fail(message) -> NoReturn:
    print("kernel_classes: " + message, file=sys.stderr)
    sys.exit(2)


def classify(name):
    """(rule, class, kind) for a kernel name, or None when no rule matches."""
    if "DefaultGemmWithVisitor" in name:
        hit = KITCHEN_GEMM.search(name)
        if hit is None:
            return None
        return {"f": ("kitchen_gemm_f32acc", "A", "gemm"),
                "i": ("kitchen_gemm_int8", "B", "gemm")}.get(hit.group(1), ("kitchen_gemm_f16acc", "B", "gemm"))
    if SAGE_F8.search(name):
        flags = re.findall(r"Lb([01])E", name)
        if len(flags) != 5:
            return None
        return ("sage_pv_f16acc", "B", "attention") if flags[4] == "1" else ("sage_pv_f32acc", "A", "attention")
    for rule, cls, kind, pattern in RULES:
        if pattern.search(name):
            return rule, cls, kind
    return None


def load_kernels(path, lenient):
    """One row per kernel name: total seconds, launches and class. Exits on unmatched names."""
    try:
        with open(path, encoding="utf-8") as fp:
            doc = json.load(fp)
    except (OSError, ValueError) as exc:
        fail("%s: %s" % (path, exc))
    events = doc.get("traceEvents", []) if isinstance(doc, dict) else doc
    totals = {}
    for ev in events:
        if isinstance(ev, dict) and ev.get("ph") == "X" and ev.get("cat") == "kernel":
            total = totals.setdefault(ev.get("name", "?"), [0.0, 0])
            total[0] += float(ev.get("dur", 0))
            total[1] += 1
    if not totals:
        fail("%s: no kernel events; profile with ProfilerActivity.CUDA and export_chrome_trace" % path)
    rows, unmatched = [], []
    for name, (us, count) in totals.items():
        hit = classify(name)
        if hit is None:
            unmatched.append(name)
            hit = ("unmatched", "U", "other")
        rows.append({"name": name, "s": us / 1e6, "count": count, "rule": hit[0], "class": hit[1], "kind": hit[2]})
    if unmatched and not lenient:
        fail("%s: %d kernel names match no rule; add rules or pass --lenient:\n  %s"
             % (path, len(unmatched), "\n  ".join(sorted(unmatched))))
    return rows


def seconds(rows, cls, kind=None):
    return sum(r["s"] for r in rows if r["class"] == cls and kind in (None, r["kind"]))


def measured_s(on, off):
    """s from one render traced with FP16 accumulation on and off: the FP16 GEMMs that left class
    B against the A GEMM time they added. None when the toggle moved no GEMM."""
    moved = seconds(on, "B", "gemm") - seconds(off, "B", "gemm")
    if moved <= 0:
        return None
    return (seconds(off, "A", "gemm") - seconds(on, "A", "gemm")) / moved


def ceiling(t, a, s):
    return t / (t - a * (1 - 1 / s))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace", help="Chrome trace of one render (torch.profiler export_chrome_trace)")
    ap.add_argument("--seconds", type=float, help="timed seconds of the render, T (default: the kernel total)")
    ap.add_argument("--off", metavar="TRACE_OFF", help="the same render traced with FP16 accumulation off")
    ap.add_argument("--s", type=float, action="append", help="speed-up of the A kernels (repeatable; default 1.7 and 2.0)")
    ap.add_argument("--lenient", action="store_true", help="report unmatched kernels as class U instead of stopping")
    ap.add_argument("--json", metavar="OUT", help="also write the result as JSON")
    args = ap.parse_args()

    rows = load_kernels(args.trace, args.lenient)
    total = sum(r["s"] for r in rows)
    t = args.seconds or total
    by_class = {c: seconds(rows, c) for c in "ABCU"}
    svals = [(s, "") for s in (args.s or DEFAULT_S)]
    s_meas = None
    if args.off:
        s_meas = measured_s(rows, load_kernels(args.off, args.lenient))
        if s_meas is None:
            print("--off: no GEMM left class B; the toggle did not reach these GEMMs", file=sys.stderr)
        else:
            svals.append((s_meas, " (measured)"))
    a, u = by_class["A"], by_class["U"]
    ceilings = [{"s": round(s, 3), "low": round(ceiling(t, a, s), 4), "high": round(ceiling(t, a + u, s), 4)}
                for s, _ in svals]

    print("kernels %.3f s, %d launches; T = %.3f s%s" % (
        total, sum(r["count"] for r in rows), t, "" if args.seconds else " (kernel total, pass --seconds)"))
    for c in "ABCU":
        if c != "U" or u:
            print("  %s %9.3f s  %5.1f %%" % (c, by_class[c], 100 * by_class[c] / total))
    if s_meas is not None:
        print("s measured with --off: %.3f" % s_meas)
    for (s, note), c in zip(svals, ceilings):
        span = "%.3fx" % c["low"] if not u else "%.3fx to %.3fx" % (c["low"], c["high"])
        print("ceiling at s = %.2f%s: %.3f s, %s" % (s, note, t / c["low"], span))
    print("review: every A, B and U kernel, and C kernels that look like matrix or attention work")
    for r in sorted(rows, key=lambda r: (r["class"], -r["s"])):
        if r["class"] != "C" or LOOKS_TENSOR.search(r["name"]):
            print("  %s %-22s %8.3f s %7d  %s" % (r["class"], r["rule"], r["s"], r["count"], r["name"][:120]))

    if args.json:
        result = {"trace": args.trace, "t": t, "kernel_s": total, "class_s": by_class,
                  "s_measured": s_meas, "ceilings": ceilings, "kernels": rows}
        with open(args.json, "w", encoding="utf-8") as fp:
            json.dump(result, fp, indent=1)
            fp.write("\n")


if __name__ == "__main__":
    main()
