English | [中文](../zh/07-performance.md)

# Performance: measuring and choosing speed-ups

This page answers: how do I tell whether a speed-up is real, where does render time actually
go, and which quantization and distillation choices held up on 16 GB consumer cards and a 128 GB
unified-memory node? Every number carries its date, box and ComfyUI version. Numbers from 0.27.1
or 0.33.1 were not re-measured on 0.42.1 (which both render boxes ran from 2026-10-20) unless a
re-measure is noted; the 2026-11-25 re-measurements ran on `ComfyUI 0.46.0` (`torch 2.10.0+cu130`,
`comfy-kitchen 0.2.41`, `comfy-aimdo 0.6.0`).

> **TL;DR**
> - Measure before tuning. On the quality line every intuitive cause (network, model loading, polling) was wrong; detailer resampling was the cost.
> - A/B as A-B-A, with an explicit off arm, warm runs, at least 3 seeds, median. One SDXL pipeline showed 24% seed variance, so a single-sample A/B cannot resolve differences under about 20%.
> - Change the biggest lever first, then re-measure the rest. Borrowed numbers are hypotheses.
> - Adopted: mxfp8 weights plus INT8 attention (2.11x on Anima 3.8B on an RTX 50 card, quality intact; mxfp8 speeds up Blackwell cards only). Collapsed: uncalibrated nvfp4. Rejected: fp8 matmul on Box B, a few-step video distill.
> - Quality tiers are judged by me, not the agent. Speed from weight format and kernels cannot be packaged as a LoRA.
> - A speed-up you cannot run can still be bounded: split the profiled kernels by accumulator type and apply T' = T - A(1 - 1/s). A GeForce unlock is worth at most 1.00 to 1.14x on the Box B lines in use, so it is not pursued.

## Rules

1. **Measure where the time goes before changing anything.**
   Why: Box A's SDXL quality line (2026-09-01, ComfyUI 0.33.1 era, 1024x1536 upscaled to
   2048x3072) ran at 99% GPU utilisation, 29 to 35% memory-bandwidth utilisation, no throttle
   reasons, 329 to 337 W of a 385 W limit. One render is four samplings: a 32-step main pass,
   a 2x model upscale, a face detailer on a 1833x1814 crop (nearly a full redraw) and two eye
   detailers. Detection took 9.0 ms and 4.4 ms, VAE 0.6 to 0.8 s. The detailer crop size is
   the lever, not the network or model loading.

2. **Profile real device kernels only.**
   Why: counting the framework's wrapper ops as well counts the same work twice and doubles
   the total.

3. **Do not hand-write kernels for these models.**
   Why: GEMM is 52 to 68% of GPU time and only lower precision moves it; the vendor library
   beats hand kernels. The fusable parts (elementwise, norm, rope, other) are about 14% on
   SDXL and 10% on the Anima DiT, worth about 5% end to end. The often-quoted "attention is
   40 to 70%" comes from video and FLUX-class models and is false for both lines here.
   Measured exception (Box B, 2026-10-29): with FP16 accumulation under the card's 165 W power
   cap, a short Triton matmul ran 1.11 to 1.20x faster than cuBLAS on three DiT layer shapes in
   isolation, so "the vendor library beats hand kernels" does not hold there. It has not run in
   a render and is not adopted; see [Kernel choice under a power cap](#kernel-choice-under-a-power-cap).
   The 5% figure is for fusing the non-GEMM parts and is unchanged.

4. **Time warm runs, at least 3 repeats, report the median, drop the cold start.**
   Why: the same SDXL recipe varied 24% across seeds (81.36 to 100.73 s). A claimed -19.4%
   phase gain (109.8 to 88.55 s) was one sample against one sample and sat inside that band.
   A pre-distilled checkpoint first timed at 3.8 s was re-measured on 2026-09-30 at 2.1 s
   and the old figure deleted. One-off calls include Triton warm-up; do not compare them with
   a resident worker.

5. **Measure variance per pipeline; do not borrow it.**
   Why: the 24% came from the detailer crop size changing with the seed. Bare Qwen-Image
   sampling varied about 1%.

6. **Test every toggle with an explicit off arm.**
   Why: "on" and "unset" cannot tell "ineffective" from "already on". A cache node behaved
   the same on and unset; only the off arm showed there was nothing to cache.

7. **Alternate arms in the same time window on the same box: A-B-A or ABBA.**
   Why: standing method. All Box B lever tests (2026-09-30) used A-B-A or ABBA, and the mxfp8
   production swap on Box A alternated arms in one window.

8. **Change the biggest lever first, then re-measure the rest.**
   Why: replacing GGUF Q8_0 dequantisation with a true W8A8 int8 convrot kernel took a
   Qwen-Image 2.1 step from 0.657 s to 0.210 s. The INT8 attention backend was worth 5 to 7% on
   the GGUF base and 14 to 21% after the switch (Box A, 0.37.0 sidecar, 2026-09-21). Measured
   in the wrong order, every later lever looks smaller than it is.

9. **Borrowed measurements carry their boundary; across models they are hypotheses.**
   Why: the mxfp8 plus INT8-attention stack gave 2.11x on Anima 3.8B, with the attention part
   alone 1.30x; the same attention backend gave 5 to 7% on Qwen-Image's GGUF base.

10. **Judge a quantization by whether image quality holds, not by same-seed reproduction.**
    Why: diffusion is chaotic under weight perturbation. mxfp8 against bf16 kept composition
    and poses, with mean pixel differences of 11 to 19 and small items (jewellery, neon glyphs)
    drifting.

11. **Quality tiers are judged by me. The agent reports only technical breakage.**
    Why: on Qwen-Image the agent judged 8 steps usable; I judged 16 steps the floor. That
    doubled every payback calculation built on the agent's call. Technical breakage means
    garbled text, collapsed structure, under-denoising.

12. **Keep models resident; unload on model switch or when done.**
    Why: the old rule "POST /free after every run" is obsolete since 2026-09-22. A free cost a
    1.9 s remote round trip and truly evicted weights. On Box B (0.27.1) dropping the per-pass
    free saved 1.34 s (11%) per WAI cut and 0.35 s (1%) per Anima cut: not a speed lever. The
    intent router now leases VRAM and an idle reaper frees it.

13. **Bake quantization metadata into the checkpoint and verify the native path.**
    Why: the loader's dtype menu only offers fp8 variants; nvfp4 and mxfp8 need per-layer
    metadata in the file. Check the server log for detected mixed precision and native ops
    (not emulation). Set the attention flag before any model import, because the attention
    function is bound at import, and print the bound function's name.

## Where the time goes

Box A, RTX 5080, torch profiler, device kernels only, 2026-09-16, ComfyUI 0.33.1.

| Bucket | SDXL UNet (fp16, batch 2, 1024x1536, 230 ms/step) | Anima 2.9B DiT (bf16, batch 1, 1024x1024, 260 ms/step) |
|---|---|---|
| GEMM | 51.8% | 68.1% |
| Convolution | 20.2% | 0% |
| Attention | 14.0% | 21.6% |
| Elementwise | 8.9% | 5.9% |
| Norm / rope | 3.3% | 3.4% |
| Other | 1.8% | 0.9% |

Anima 3.8B (52 blocks, bf16, CFG batch 2): 659 ms/step at 1024x1024 (7.44 GiB peak),
1099 ms/step at 1024x1536 (7.63 GiB). Attention share grows with resolution, 21.0% to 26.8%.

Isolated GEMM, shape 4096x2048x2048, random data, naive per-tensor scaling (error is an upper
bound, not a quality verdict): bf16 0.312 ms; fp8 0.153 ms (2.04x, relative error 0.038);
nvfp4 0.071 ms (4.38x, relative error 0.134).

## The A/B procedure

1. Write the question and the one variable. Fill in [`templates/ab-test.md`](../../templates/ab-test.md).
2. Fix everything else: box, prompt, resolution, sampler, steps, LoRA set.
3. Arms: control, treatment, and an explicit off arm for any toggle. A LoRA control arm uses
   strength 0.001, never 0.
4. Seeds: at least 3. Same seeds in every arm.
5. Warm up each arm once; discard that run.
6. Run A-B-A (or ABBA) in one time window with [`tools/comfy_ab_harness.py`](../../tools/comfy_ab_harness.py)
   and `--strict-cache` (`--a2-seed-offset 100000` in `aba` mode so `A_2` never hits ComfyUI's
   `0.07 s` sampler cache and asymmetric `CLIPTextEncode` caching fails closed). Record per-image
   sampling time and wall time separately.
7. Report the median and the spread. If the difference is inside the measured seed variance,
   the verdict is "not resolved".
8. Quality: compare pixel difference and composition, then put the images in front of me.
   My verdict sets the tier.
9. Record date, box, ComfyUI version, torch version and launch flags with the numbers.

## Quantization verdicts

Anima 3.8B, Box A, 30 steps, CFG 4.5, 1024x1536, same seed, in-process worker on ComfyUI
0.33.1 libraries, 2026-09-16/17.

| Configuration | Sampling | vs bf16 | Weights | Quality |
|---|---|---|---|---|
| bf16 | 34.006 s | 1.00x | 6.99 GiB | Reference |
| nvfp4 (W4A4) | 20.624 s | 1.65x | 2.61 GiB | Collapsed: lineart lost, stripe noise, character drift |
| mxfp8 (W8A8) | 20.855 s | 1.63x | 4.04 GiB | Intact |
| mxfp8 + INT8 attention | 16.091 s | 2.11x | 4.04 GiB | Intact; adopted |

- nvfp4 collapsed because ComfyUI's nvfp4 also quantizes activations to 4 bits with no
  calibration. 4-bit weights held; uncalibrated 4-bit activations did not.
- nvfp4 was not faster than mxfp8: per-forward activation abs/amax and packing ate the saving.
  The line is bound by that overhead, not by weight bandwidth.
- If more compression is ever needed: an SVD-quant W4A4 path with low-rank compensation, or
  keeping the most sensitive first and last blocks at higher precision. Never uncalibrated
  nvfp4 again on this line.
- mxfp8 gives real speed only on Blackwell (RTX 50) cards; other cards silently dequantise
  (vendor documentation, source not checked).
- A remapped LoRA on the mxfp8 model costs nothing: 16.295 s against 16.271 s without it.

Pre-distilled Anima 2.9B moved into the production server as mxfp8 (Box A, 0.33.1,
2026-09-30, arms alternated in one window): 8 steps 1.6 s against 2.1 s bf16, 30 steps 11.3 s
against 14.5 s, 22 to 24% faster. I approved it on 2026-10-01. In a resident worker with INT8
attention and fused kernels: 30 steps 6.42 s, 8 steps 0.88 s sampling.

Box B levers (RTX 4060 Ti, PyTorch 2.10.0+cu130, ComfyUI 0.27.1, 2026-09-30, A-B-A / ABBA):

| Lever | Result | Status |
|---|---|---|
| `--fast fp16_accumulation` | WAI 1.19x (12.12 to 10.19 s), Anima 1.05x; composition same, detail drift | On by default |
| SageAttention on top | Anima fast line 1.087x (4.83 to 4.45 s), quality line 1.077x, WAI 1.027x | On by default |
| fp8 weights + fp8 matmul | Anima 4% slower (4.58 vs 4.42 s), PSNR 16.3 dB, composition changed | Dead end |
| Drop per-pass `/free` | WAI 1.34 s (11%), Anima 0.35 s (1%) | Not a lever |

Write `--fast fp16_accumulation` explicitly: bare `--fast` enables every experimental
optimisation. Attention flags are mutually exclusive; one process gets one backend.

fp16 accumulation re-measured on 0.42.1 (Box B, 2026-10-29, one process with only
`torch.backends.cuda.matmul.allow_fp16_accumulation` toggled, A-B-A, median of 3): WAI 1.21x
(11.96 to 9.89 s), Anima fast line 1.25x (5.46 to 4.36 s), Anima quality line 1.27x (30.05 to
23.70 s). The 1.05x for Anima in the table is stale: on 0.27.1 its main model ran in BF16, on
0.42.1 it computes in FP16, so every GEMM takes the flag. Qwen-Image 2.1 with INT8 weights is
unaffected (10.58 against 10.57 s). SageAttention was not re-measured.

## Distillation and step-count verdicts

- **Pre-distilled Anima 2.9B, 8 steps, CFG 1:** 2.1 s warm against 14.2 s for 30 steps at CFG 4
  (Box A, 0.33.1, 896x1152, 2026-09-30). Adopted for the fast line; the recommended fast line on
  both boxes has since moved to a 28-block merged base with the turbo LoRA below. At CFG 1 the negative
  prompt is inert; CFG above 1 runs two forwards and costs 40 to 60% more.
- **Turbo LoRA at 0.9 on a base model, 10 steps:** about 2.5 s warm, 7 s cold. Do not stack a
  turbo LoRA on a model that is already distilled.
- **Qwen-Image 2.1 step tiers** (Box A, 0.37.0 sidecar, 2026-09-21; 0.42.1 gives pixel-identical
  output): 1024x1024 at 16 steps 4.04 s, at 30 steps 7.58 s; 2048x2048 at 16 steps 21.45 s;
  768x768 2.53 s. Cost follows pixel count; 2K is superlinear. I set 16 steps as the tier.
  Few-step distillation and a self-baked mxfp8 for this model were not pursued on payback.
- **A few-step distillation LoRA for a video model (8 steps):** 30.9 s against 46.3 s total, only
  about 1.5x, because each step got slower with the LoRA attached (2.62 s against 1.81 s).
  Motion energy fell from 0.47 to 0.30 with stop-and-jump frames; audio -56 against -45 dB. Rejected
  on 2026-10-21. Single seed, single prompt, ComfyUI 0.30.0 runtime.

## Bounding a speed-up you cannot run

GeForce cards run tensor-core math with FP16 or BF16 inputs and FP32 accumulation at half the
rate of the professional parts. Community unlock tools
([gpu-unlock](https://github.com/Zagitta/gpu-unlock),
[gpu-unlock-ada](https://github.com/JustAResearcher/gpu-unlock-ada)) lift that cap. The RTX 4060
Ti (AD106) has only a Linux kernel module and Box B runs Windows, so on 2026-10-29 I bounded the
gain instead of measuring it:

1. Profile one warm render per workload, device kernels only (rule 2).
2. Put every kernel in a class by accumulator type with
   [`tools/kernel_classes.py`](../../tools/kernel_classes.py). A: FP16 or BF16 inputs with FP32
   accumulation (cuBLAS and CUTLASS s-kernels, cuDNN convolution, exact attention); only these
   gain. B: already full rate on GeForce (FP16 accumulation, INT8 with INT32 accumulation,
   SageAttention with its PV product accumulated in FP16). C: no tensor-core math. A kernel no
   rule matches stops the run, so a new tensor kernel cannot fall into C unseen. Some kernels are
   decided by a template argument: SageAttention's `use_pv_fp16_accu`, a CUTLASS GEMM's
   accumulator type.
3. Ceiling: T' = T - A x (1 - 1/s), with T the timed median and A the class-A seconds of the
   profiled render. s = 2.0 is the ideal; 1.7 is a third-party measurement on the same card
   model under its 165 W limit ([gpu-unlock-ada #98](https://github.com/JustAResearcher/gpu-unlock-ada/issues/98));
   the in-situ value comes from the same render with FP16 accumulation switched off, which sends
   the same FP16 GEMMs to the half-rate FP32-accumulate kernels, power limit included.

Box B (RTX 4060 Ti 16 GB, 165 W, ComfyUI 0.42.1, PyTorch 2.10.0+cu130, `--fast fp16_accumulation
--use-sage-attention`, 2026-10-29). The low end uses the in-situ s (1.52 to 1.63; 1.44 for the
MOSS-Image rows, see Real cases; 1.7 for Qwen-Image, which has no FP16 GEMM to toggle), the high
end s = 2.0:

| Workload | Now | Class A | Ceiling |
|---|---|---|---|
| WAI + LoRA, 1216x832, 30 steps | 9.89 s | 26.1%, almost all convolution | 1.09 to 1.14x |
| Anima fast line, 10 steps | 4.36 s | 3.2% | 1.01 to 1.02x |
| Anima quality line, 30 steps | 23.70 s | 0.6% | 1.00x |
| Qwen-Image 2.1, INT8 weights and INT8 attention, 1024x1024, 16 steps | 10.57 s | 4.8%, VAE convolution | 1.02x |
| MOSS-Image, custom FP16 loader, exact attention, 1024x1024, 25 steps | 45.43 s | 22.6%, exact attention | 1.07 to 1.13x |
| MOSS-Image, stock loader (BF16 compute), SageAttention, 1024x1024, 25 steps | 60.67 s | 68.9%, GEMM | 1.26 to 1.52x |

- The lines in use gain little because their expensive work already runs at full rate:
  `--fast fp16_accumulation` puts their GEMMs on FP16-accumulate kernels, and INT8 and
  SageAttention were never half rate. What is left is cuDNN convolution (PyTorch runs FP16
  convolution with FP32 accumulation) and exact attention.
- Only a model computed in BF16 gains much, because BF16 GEMMs can only accumulate in FP32. The
  custom FP16 loader already takes most of that without an unlock: 1.42x faster per step than
  the stock loader on Box B, both with exact attention (measured 2026-10-21).
- Verdict: switching Box B to Linux for an unlock is not worth it for the lines in use.
- Not verified: no render ran on an unlocked card. Convolution and attention are assumed to gain
  the GEMM s (issue #98 measured 1.63 to 1.66x for SDPA attention). The comfy-kitchen INT8
  attention kernel is in class B from its name and the INT8 quantization kernels before it; its
  source was not read.

## Kernel choice under a power cap

Box B, 2026-10-29, PyTorch 2.10.0+cu130, Triton 3.8.0, driver 610.88.
[`tools/gemm_probe.py`](../../tools/gemm_probe.py) times the four linear layers of a 3072-wide DiT
block (MOSS-Image) with random FP16 operands and M = 4352 rows (a 1024x1024 image plus text).
Each variant runs for 2 s while nvidia-smi is sampled every 100 ms; the error against an FP32
product shows which accumulator ran. The table is the run of the tool in this repo; an earlier
run the same day agreed within 2.4%, with the same kernels and errors.

| Layer (K to N) | cuBLAS, FP16 acc | Triton, FP16 acc | cuBLAS, FP32 acc |
|---|---|---|---|
| qkv 3072 to 9216 | 3.26 ms, 2505 MHz | 2.93 ms, 2573 MHz | 4.96 ms, 2925 MHz |
| o 3072 to 3072 | 1.18 ms, 2400 MHz | 0.98 ms, 2595 MHz | 1.67 ms, 2910 MHz |
| ffn_up_gate 3072 to 16384 | 6.19 ms, 2325 MHz | 5.25 ms, 2565 MHz | 8.85 ms, 2910 MHz |
| ffn_down 8192 to 3072 | 2.99 ms, 2310 MHz, split-K | 2.74 ms, 2430 MHz | 4.41 ms, 2850 MHz |

- For FP16 accumulation on SM 8.9, cuBLAS picks its h1688 kernels for every shape here, as it did
  for the SDXL and Anima GEMMs in the profiles. cuBLASLt picks the same kernels, within 1%.
- The FP16-accumulate variants sat on the 165 W software power cap (throttle reason 0x4) in 70
  to 100% of the busy samples, at 2220 to 2600 MHz. With FP32 accumulation the K=3072 layers touched the cap in part of the
  samples at 2895 to 2925 MHz; ffn_down was capped throughout, at 2850 to 2880 MHz.
- The cap does not fix the speed. Under it, on the K=3072 layers, the Triton kernel held a higher
  clock and ran at 0.93 to 0.94 of the FP16-accumulate peak at the sampled clock, against 0.83 to
  0.88 for cuBLAS: 1.11 to 1.20x faster with the same error (2.88e-3), over both runs.
- ffn_down (K=8192): cuBLAS splits K (a memset before each call), and its error (3.33e-3) is lower
  than full-K FP16 accumulation in Triton (4.69e-3); FP32 accumulation gives 2.08e-4. Triton is
  only 1.09x faster there.
- Not tried in a render: the Triton kernel for the three K=3072 layers. Estimated at about 3 s per
  MOSS-Image render on Box B (those layers take 20.4 s); not verified.

## Multi-model resident hot-swapping on one 16 GB card

Box A (`RTX 5080 16 GB`, Ryzen 9800X3D, `48 GB` DDR5 with `47.2 GiB` usable, PCIe Gen5 x16, Windows,
`ComfyUI 0.46.0`, `torch 2.10.0+cu130`, `comfy-aimdo 0.6.0`, `comfy-kitchen 0.2.41`), measured
2026-11-25.

Two distinct causes drove legacy `23.2 to 29.5 s` model-switch stalls on Box A:

1. Separate sidecar ports forced callers to send `POST /free` (`unload_models` plus `free_memory`),
   dropping host RAM caches and re-reading `10 to 13 GiB` from disk on every switch.
2. In `ComfyUI 0.46.0`, passing bare `--cache-ram` with no numeric bounds sets
   `ram_inactive_headroom` to `100%` of physical RAM (`47.2 GiB` on Box A). On the first node of a
   new workflow, `RAMPressureCache` marks inactive `ModelPatcher` objects at `oom_ram_usage = 1e30`
   and evicts the previous model (`14.13 s` reload) even when `27 GiB` of DDR5 sits free.

Consolidating all model roots into one `ComfyUI 0.46.0` instance with
`--reserve-vram 2.5 --cache-ram 4.0 8.0 --use-sage-attention --fast fp16_accumulation` keeps four
`8 to 13 GiB` model families (`MOSS-Image` `12.11 GiB`, `FLUX 3 Klein` `9.75 GiB`,
`Fibo 2.0 Edit Turbo` `7.83 GiB`, `Qwen-Image 2.1` `13.27 GiB`) resident in `comfy-aimdo` pinned
DDR5 RAM (`21.9 GiB` still free) and sheds the oldest inactive model only if free system RAM drops
below `8.0 GiB`.

| Transition or probe (`1152x1680` pipeline) | Bare `--cache-ram` / legacy sidecar | `--cache-ram 4.0 8.0` | Pure switch cost | Peak VRAM | Free DDR5 RAM |
|---|---:|---:|---:|---:|---:|
| PCIe Gen5 x16 `2.0 GiB` H2D copy (pageable vs pinned) | `455.8 ms` (`4.39 GiB/s`) | `37.4 ms` (`53.54 GiB/s`) | n/a | n/a | n/a |
| `MOSS-Image` 2-pass warm (`832x1216 -> 1152x1680`) | `10.06 s` | `10.00 s` | `0.00 s` | `12,632 MiB` | `26.53 GiB` |
| Switch `FLUX 3 Klein -> MOSS-Image` (2-pass, new seed) | `14.13 s` (`cached=0`, evicted) | `10.45 s` (`cached=10`) | `+0.45 s` | `15,126 MiB` | `23.98 GiB` |
| Switch `MOSS-Image -> FLUX 3 Klein` (16-step edit) | `10.62 s` (cold) | `7.17 s` (`7.22 s` warm) | `<0.15 s` | `15,304 MiB` | `23.85 GiB` |
| Switch `MOSS-Image -> FLUX 3 Klein` (8-step edit) | not run | `3.74 s` | `<0.15 s` | `14,958 MiB` | `23.82 GiB` |
| Switch `MOSS-Image -> Fibo 2.0 Edit Turbo` (4-step edit) | `23.20 s` (multi-port `/free`) | `2.87 s` (`2.60 s` warm) | `+0.27 s` | `15,008 MiB` | `23.44 GiB` |
| `Qwen-Image 2.1` (16-step edit, warm) | not run | `9.88 s` | n/a | `15,208 MiB` | `22.36 GiB` |
| Switch `Qwen-Image 2.1 -> MOSS-Image` (all 4 resident) | `29.46 s` (cold) | `10.61 s` (`cached=10`) | `+0.61 s` | `15,057 MiB` | `21.86 GiB` |

## Blackwell rooflines, quantization, and LoRA verdicts (0.46.0)

Measured 2026-11-24/25 across Box A (`RTX 5080`, `SM 12.0`, `396 W` cap, `2842 to 2865 MHz` under
load, `791.5 GB/s` D2D copy) and `UMA Box` (`NVIDIA GB10`, `SM 12.1`, `128 GB` unified LPDDR5x,
`221 to 237 GB/s` measured bandwidth, Linux ARM64), on `ComfyUI 0.46.0` (`torch 2.10.0+cu130`,
`comfy-kitchen 0.2.41`, `comfy-aimdo 0.6.0`).

- **SM 12.0 INT8 roofline (`MOSS-Image` 5B INT8 ConvRot on Box A):** dense INT8 GEMM runs at
  `355 to 358` of `410 TOPS` (`89%`) and INT8 attention runs at `290` of `302 TOPS` (`96%`). Both
  sit against the hardware ceiling, leaving no room for custom GEMM or attention kernels at INT8.
- **Updated INT8 LoRA verdict (supersedes 2026-09-18):** on `0.46.0`, stock `LoraLoaderModelOnly`
  runs GPU INT8 requantization in `+0.50 to 0.67 s` (`1.52 s` warm 8-step `1024x1024` with cached
  text encoding, `2.02 s` when switching between two stacked LoRA pairs, zero VRAM leak). A
  Python-dispatched BF16 low-rank bypass (`relL2 = 0.0015` on `ffn_down` after `situ` and `0.0016`
  on 3-slice fused `qkv`) removes the `+0.50 s` switch cost (`~0.00 s`) and stays `1.003 to 1.117x`
  sharper (`-0.31%` saturation shift), but adds `+165 ms/step` (`2.84 s` total, `1.87x` slower warm
  and `1.41x` slower even on a switch). Use `LoraLoaderModelOnly` for speed; keep the BF16 bypass
  only when avoiding INT8 requantization saturation or sharpness drift.
- **Why static 4-bit (`nvfp4`) and step-split `nvfp4 -> INT8` fail:** even with
  `CentriQ + ConvRot256 + SVD-64` calibration, `nvfp4` gives `0.117` single-layer `relL2` against
  `0.0125` for INT8 because dynamic `E2M1` activation rounding dominates. Running early steps in
  `nvfp4` and swapping to `INT8` for late steps also fails: the flow-matching ODE integrates early
  content and identity error forward, and late `INT8` steps cannot erase it. Only QAT or on-policy
  distillation held quality: a 12-step on-policy distillation (OPD) LoRA plus a 7-step unguided
  refine tail cut `MOSS-Image` (`832x1216 -> 1152x1680`) from `10.22 s` (`IQR 0.022 s`) to `6.10 s`
  (`IQR 0.016 s`, `1.68x`, `13,089 MiB` peak VRAM).
- **Localized image editing (`FLUX 3 Klein`, `1152x1680`, 8 steps, Box A, `n=6` interleaved `A-B-A`):**

| Edit arm | Control median | Candidate median | Speed-up | Sharpness vs control | Verdict |
|---|---:|---:|---:|---:|---|
| `16px`-aligned context-padded ROI crop (`<45%` area, `<=70%` width banner guard) | `6.49 s` | `2.61 s` (`1.77 s` at `768x768`) | `2.48 to 3.66x` | `1.08x` (`0.00` MAE outside ROI) | Adopted opt-in for localized object/sky edits; width guard skips wide bottom text banners |
| Approximate reference KV reuse (`refresh_stride=2`, BF16) | `6.56 s` | `5.81 s` | `1.13x` | `0.976x` | Conditional: visually clean across 6/6 cells, modest gain |
| Unrefreshed reference KV reuse (`w2`, BF16) | `6.46 s` | `4.78 s` | `1.35x` | `0.924x` | Rejected: `flow_map` drift climbs `0.131 -> 0.442 relL2`, softening bokeh and cloth folds |
| Unrefreshed reference KV reuse (`fp8_e4m3fn`) | `6.48 s` | `5.01 s` | `1.29x` | `0.890x` | Rejected: dequant unpack makes it slower and softer than BF16 |
| Combined ROI crop + KV reuse | `6.48 s` | `2.08 s` | `3.12x` | `0.883x` | Rejected: compounds softening and crop edge artifacts |

- **Auxiliary ONNX segmentation (`isnet-anime.onnx`, `1024x1024` FP32, Box A, `n=6` `A-B-A`):**
  Ryzen 9800X3D `CPUExecutionProvider` runs in `0.314 s` warm (`0.514 s` cold). `CUDAExecutionProvider`
  with a `1536 MiB` BFC arena cap runs in `0.052 s` warm (`6.07x`, alpha MAE `0.058 / 255`,
  `+1.76 GiB` VRAM; a `512 MiB` arena cap OOMs at `Conv_83` requesting `134 MiB` cuDNN workspace),
  but pays `6.27 s` of cold cuDNN autotune init. One-shot CLI calls belong on CPU; resident daemons
  belong on GPU.
- **`UMA Box` (`GB10 SM 12.1`, `221 to 237 GB/s` bandwidth, 2026-11-25):** `FP8 e4m3fn` (`185 TFLOPS`
  with dynamic activation quantization, `42`-block `relL2 = 0.0128` without Hadamard rotation) is the
  sweet spot over `NVFP4` (`250 TFLOPS`, only `1.35x` peak compute in exchange for about `9x` single-layer
  rounding noise). Static `cuobjdump` inspection of `comfy-kitchen 0.2.41` (`aarch64`) found `0`
  precompiled `sm_121` SASS cubins (`39` modules each for `sm_75/80/89/90a/100/120`), relying on
  `1,615` forward-compatible `.target sm_120f` PTX 9.0 entry points that JIT-compile onto `SM 12.1`
  at startup with zero silent Python fallbacks; persist `~/.nv/ComputeCache` across container restarts
  and load `.safetensors` through `MAP_SHARED | PROT_READ` ([`tools/safetensors_prot_read.py`](../../tools/safetensors_prot_read.py)).

## Speed-ups that cannot ship as a LoRA

A LoRA carries weight deltas. The 3.8B speed-up came from weight format (mxfp8), an attention
backend flag, fused kernels and a resident process. None of those are weight values. The
publishable form is an mxfp8 checkpoint whose description lists the measured ladder and the
launch flags. The only LoRA-shaped speed-up is a step-reducing turbo LoRA.

## Real cases

- **2026-09-01, quality line "slow".** Network, loading and polling were blamed. Server logs
  showed four samplings and a near-full-frame face detailer. Rule: profile first.
- **2026-09-03, training gradient checkpointing.** "Only 40% VRAM used" suggested turning it
  off. Result: 15899 of 16380 MiB, power fell to 53 W, about 9x slower (Box B). Rule: peak
  memory with checkpointing on does not predict peak with it off.
- **2026-09-17, nvfp4.** Technically valid (520 layers detected as native nvfp4, weights on GPU
  6984 MB to 2671 MB, 1.65x), visually collapsed. A real bug surfaced too: the quantized DiT
  could not be partly offloaded and VAE decode ran out of memory; fixed by explicit unload
  before decode.
- **2026-09-21, 8 steps against 16.** The agent's "8 is fine" was overruled; the payback
  maths doubled.
- **2026-10-29, one layer on a slow kernel.** The in-situ s of the custom FP16 loader for
  MOSS-Image came out at 1.34, against 1.52 to 1.63 for WAI and Anima. The first explanation, the
  h1688 kernel choice, was wrong. Splitting the profile per layer found the cause: the loader's
  fast mode sends the FFN down-projection through a hook in ComfyUI's ops to a comfy-kitchen
  CUTLASS GEMM with FP16 accumulation, 4.83 ms per call, slower than plain cuBLAS with either
  accumulator (2.99 and 4.41 ms in the probe). That layer alone has an s of about 0.92, the other
  three about 1.56. The MOSS-Image rows of the unlock table therefore use the probe's
  cuBLAS-to-cuBLAS s over the four layers: 1.44 in the earlier run, 1.46 in the run shown above.
  Forcing the layer through its own module (cuBLAS, split-K) in a second ComfyUI process, with
  production untouched: 45.41 to 41.31 s per image, 1.10x, 6 renders per arm over two runs.
  Quality is not accepted. Against an all-FP32-accumulate reference the new route won 1 of 3
  seeds, and the more accurate FP32 route also lost to the default on 2 of 3, so whole-image PSNR
  after 25 steps measures trajectory divergence, not accumulator error (rule 10). Acceptance needs
  the loader's original checks, single-forward error against FP32 and 16 prompt pairs. Not
  adopted. Rule: split a low aggregate ratio per layer before naming a cause.
- **2026-10-29, preview files overwrote each other.** ComfyUI's PreviewImage reuses a file name
  within one process once earlier previews have left its temp folder. Test previews moved into a
  holding folder by name kept 16 of 115, and the first A/B run's image comparisons read the same
  file on both sides. Timings were unaffected. Fix: move each preview to a unique path and record
  it. Rule: when a comparison reads files back, check that the two sides are different files.

## Tried and dropped

- Hand-written fused kernels for the non-GEMM parts (measured ceiling about 5% end to end).
- A GeForce FP32-accumulate unlock on Box B: ceiling 1.00 to 1.14x on the lines in use, and it
  needs Linux (bounded, not run).
- Uncalibrated nvfp4 W4A4.
- fp8 matmul on Box B: Anima's MLP feeds 5-D tensors, which the fp8 path silently routes to
  the fallback, and input conversion ate the 13% matmul gain.
- Per-pass `/free` removal as a speed lever.
- Box B LoRA-training levers (2026-09-03): gradient checkpointing off, batch 2 (9.5% slower),
  compile (no effect: LoRA injection by forward monkey-patch breaks the graph), full AdamW
  (same steady state). 2.9 to 3.0 s/it at 1024 px is the card's level.
- Distributed training across the two Windows boxes: no NCCL, 2.5 GbE link.
- A cache node on Qwen-Image text-to-image: no effect.
- Calibrated static `nvfp4` (`CentriQ + ConvRot256 + SVD-64`, `0.117` single-layer `relL2`) and step-split `nvfp4 -> INT8` runtime weight swapping (early `E2M1` trajectory drift integrates forward).
- Python-dispatched BF16 LoRA bypass as a speed lever on `ComfyUI 0.46.0` (`+165 ms/step`, slower than stock `+0.50 s` GPU INT8 requantization; kept only for zero-requant fidelity).
- Unrefreshed `FLUX 3 Klein` reference KV reuse (`0.924` sharpness) and `CUDAExecutionProvider` on `isnet-anime.onnx` for one-shot CLI runs (`6.27 s` cold cuDNN init).

## See also

- [`04-model-bringup.md`](04-model-bringup.md): adopting a quantized model.
- [`05-debugging.md`](05-debugging.md): OOM, driver resets, polluted processes.
- [`06-render-discipline.md`](06-render-discipline.md): smoke timing before a batch.
- [`templates/ab-test.md`](../../templates/ab-test.md): the write-up template.
- [`tools/README.md`](../../tools/README.md): the kernel classifier, GEMM probe, read-only safetensors loader, and ComfyUI A/B harness used above.
