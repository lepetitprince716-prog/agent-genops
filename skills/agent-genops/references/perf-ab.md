# Performance A/B

Purpose: run speed and quality comparisons that can actually resolve a difference, and apply the recorded verdicts.
Read when: proposing or testing a speed-up (quantization, attention backend, launch flag, step count, distillation, resident process), or quoting a timing.

## Hard rules

- Measure where time goes before tuning. Profile device kernels only (exclude framework wrapper ops; they double-count).
- Warm runs only. Discard the first run per arm (model swap, Triton warm-up).
- At least 3 seeds, same seeds in every arm. Report median and spread.
- A-B-A or ABBA, same box, same time window.
- Every toggle gets an explicit off arm, not just on and unset.
- LoRA control arm: strength 0.001, never 0.
- One variable per test.
- Change the biggest cost first, then re-measure smaller levers.
- Borrowed numbers (other model, other box, other version) are hypotheses until re-measured.
- Quantization verdict = quality holds. Same-seed reproduction is not the criterion.
- Quality tier verdicts belong to the owner. Report only technical breakage: garbled text, collapsed structure, under-denoising.
- Every number written down carries date, box, GPU, ComfyUI version, torch version, launch flags.

## Resolution limit

- Measured: one SDXL quality pipeline varied 24% across seeds (detailer crop size varies with seed). Bare Qwen-Image sampling varied about 1%.
- Measure the variance of the pipeline under test first. If the difference is inside it, verdict = "not resolved".
- Single-sample A/B never resolves differences under about 20% on a detailer pipeline.

## Procedure

1. Copy `templates/ab-test.md`. Fill question, variable, fixed settings, arms, seeds.
2. Probe the box: empty queue, enough VRAM, owner not gaming.
3. Warm each arm once; discard.
4. Run A-B-A (or ABBA) with `tools/comfy_ab_harness.py --strict-cache` (`--a2-seed-offset 100000` in `aba` mode so `A_2` cannot hit ComfyUI's `0.07 s` sampler cache and asymmetric encoder caching fails closed). Record sampling time and wall time separately.
5. Compute median, spread, ratio. Compare against measured seed variance.
6. Quality: pixel difference and composition check, then one review page for the owner.
7. Write the verdict: adopted / rejected / not resolved, with the owner's quality call.
8. Delete test images after the verdict; keep the numbers and the write-up.

## Where time goes (reference, Box A RTX 5080, 2026-09-16, ComfyUI 0.33.1)

| Bucket | SDXL UNet | Anima 2.9B DiT |
|---|---|---|
| GEMM | 51.8% | 68.1% |
| Conv | 20.2% | 0% |
| Attention | 14.0% | 21.6% |
| Fusable rest | about 14% | about 10% |

Implications: precision reduction is the GEMM lever; attention backends matter more on DiT; hand-written fusion of the non-GEMM parts caps at about 5% end to end; do not quote "attention 40 to 70%" (video/FLUX class only). GEMM kernel choice is a separate question: on Box B under the power cap, a Triton FP16-accumulate matmul beat cuBLAS 1.11 to 1.20x in isolation (2026-10-29, not in a render).

## Bounding a speed-up that cannot be run

- Split one profiled render's kernels by accumulator with `tools/kernel_classes.py`: A (FP16/BF16 in, FP32 accumulate), B (already full rate), C (no tensor-core math). Unmatched names stop the run.
- Ceiling: T' = T - A x (1 - 1/s). s from the same render with FP16 accumulation off (measured), plus 1.7 and 2.0.
- Time GEMM candidates with `tools/gemm_probe.py`: sustained load, nvidia-smi clock and power, error against FP32 to confirm the accumulator.
- A ceiling is not a measurement; say so in the report.

## Recorded verdicts (do not re-run without a new reason)

| Lever | Result | Verdict |
|---|---|---|
| mxfp8 weights (Anima 3.8B, Box A, 0.33.1 libs) | 1.63x, quality intact | Adopted |
| mxfp8 + INT8 attention | 2.11x total (attention part 1.30x), intact | Adopted |
| nvfp4 W4A4, uncalibrated | 1.65x, quality collapsed | Never again on this line |
| mxfp8 in production server, pre-distilled 2.9B | 22 to 24% faster | Adopted 2026-10-01 |
| int8 convrot instead of GGUF Q8_0 (Qwen-Image 2.1) | 0.657 to 0.210 s/step | Adopted |
| INT8 attention on Qwen-Image | 5 to 7% on GGUF, 14 to 21% on convrot | Adopted |
| `--fast fp16_accumulation` (Box B, 0.42.1, 2026-10-29) | WAI 1.21x, Anima 1.25x to 1.27x (0.27.1: 1.19x, 1.05x) | Default on |
| SageAttention on top (Box B, 0.27.1) | 1.03x to 1.09x | Default on |
| fp8 matmul (Box B) | 4% slower, PSNR 16.3 dB | Dead end |
| Per-pass `/free` removal | 1% to 11% | Not a lever; keep models resident anyway |
| Hand-written fusion of the non-GEMM parts | Ceiling about 5% | Rejected |
| GeForce FP32-accumulate unlock (Box B, needs Linux) | Ceiling 1.00x to 1.14x on lines in use; 1.26x to 1.52x for a BF16-computed DiT | Not pursued (bounded, not run) |
| Triton FP16-accumulate GEMM instead of cuBLAS (Box B) | 1.11x to 1.20x per GEMM in isolation | Open: not tried in a render |
| One layer routed by a custom loader to a slower library GEMM, moved back to cuBLAS (Box B) | 1.10x per image | Open: quality not accepted |
| Video few-step distill LoRA, 8 steps | 1.5x, motion stalls | Rejected 2026-10-21 (single seed) |
| Qwen-Image few-step distill / self-baked mxfp8 | Not built | Rejected on payback |
| Box B LoRA training: GC off, batch 2, compile, full AdamW | Slower or neutral | Rejected |
| Unified single-port hot-swap `--cache-ram 4.0 8.0 --reserve-vram 2.5` (Box A, `0.46.0`, 2026-11-25) | 4 model families (`8-13 GiB` each) stay in pinned DDR5 (`53.54 GiB/s` vs `4.39 GiB/s` pageable, `21.9 GiB` free); switch overhead `0.15-0.61 s` vs `14.13 s` bare `--cache-ram` / `23.2-29.5 s` multi-port `/free` | Adopted |
| Stock `LoraLoaderModelOnly` vs Python BF16 bypass on `MOSS-Image` INT8 (Box A, `0.46.0`, 2026-11-25) | Stock GPU requant switches in `+0.50-0.67 s` (`1.52 s` warm 8-step `1024x1024`, zero leak) vs `2.84 s` (`+165 ms/step`) for BF16 bypass (`1.003-1.117x` sharper) | Stock for speed; bypass for zero-requant fidelity only |
| Calibrated static `nvfp4` (`CentriQ + ConvRot256 + SVD-64`) & step-split `nvfp4 -> INT8` (2026-11-25) | `0.117` single-layer `relL2` vs `0.0125` INT8; early `E2M1` ODE drift persists into late INT8 steps | Rejected; use 12-step OPD LoRA + 7-step refine (`10.22 -> 6.10 s`) |
| `FLUX 3 Klein` `16px` ROI crop (`<45%` area, `<=70%` width guard, Box A, `0.46.0`, 2026-11-25) | `6.49 -> 1.77-2.61 s` (`2.48-3.66x`), `0.00` MAE outside ROI, `1.08x` sharpness; beats `refresh_stride=2` KV reuse (`6.56 -> 5.81 s`, `1.13x`) and unrefreshed KV (`0.924` sharpness) | Adopted opt-in (localized edits) |
| `isnet-anime.onnx` (`1024x1024`, Box A, 2026-11-25) | Ryzen 9800X3D CPU `0.314 s` vs warm CUDA `0.052 s` (`1536 MiB` arena cap; `512 MiB` OOMs at `Conv_83`), `6.27 s` cold cuDNN init | CPU for 1-shot CLI; CUDA for resident daemons |
| `UMA Box` (`GB10 SM 12.1`, `221-237 GB/s` BW, `0.46.0`, 2026-11-25) | `FP8 e4m3fn` (`185 TFLOPS`, `42`-block `relL2 = 0.0128`) over `NVFP4` (`250 TFLOPS`, `1.35x` compute for `9x` noise); `0` native `sm_121` SASS cubins in `comfy-kitchen 0.2.41` (`1,615` `sm_120f` PTX JIT, persist `~/.nv/ComputeCache`); load via `MAP_SHARED \| PROT_READ` (`tools/safetensors_prot_read.py`) | Adopted |

Box B numbers were measured on 0.27.1 and not re-measured on 0.42.1, except fp16 accumulation and the 2026-10-29 rows. Box A 2026-09 numbers were measured on 0.33.1; 2026-11-25 Box A and `UMA Box` re-measurements ran on `ComfyUI 0.46.0` (`torch 2.10.0+cu130`, `comfy-kitchen 0.2.41`, `comfy-aimdo 0.6.0`).

## Quantization checklist

- Bake per-layer quantization metadata into the checkpoint (loader dtype menu covers fp8 only).
- Log must show detected mixed precision and native ops (not emulation).
- Set the attention flag before any model import; print the bound attention function name.
- After quantization, unload models and empty cache before VAE decode (quantized DiT may not partially offload).
- mxfp8 speeds up only on Blackwell cards (vendor docs, unverified in source).
- Attention flags are mutually exclusive: one backend per process.
- Write `--fast fp16_accumulation` explicitly; bare `--fast` enables every experimental optimisation.

## Packaging speed-ups

- Weight format, attention flags, fused kernels and resident processes cannot be shipped as a LoRA.
- Publishable form: a quantized checkpoint plus the measured ladder and launch flags in the description.
- Before publishing: GUI load check on a stock ComfyUI, licence notices, version decision. Ask the owner first; the check occupies a render box.

## Stop and report

- Difference inside measured variance after 3 seeds: report "not resolved", do not add seeds silently beyond the agreed budget.
- Test would occupy Box A while the owner may be gaming.
- Lever changes launch arguments of a shared production server: back up first, GPU idle window, owner's go-ahead.

## Report

- Question, variable, arms, seeds, box, GPU, ComfyUI and torch versions, flags, date.
- Median and spread per arm; ratio.
- Measured seed variance; resolved or not.
- Quality: pixel diff, composition note, owner's verdict or "awaiting owner".
- Verdict and where the write-up lives.
