English | [中文](../zh/07-performance.md)

# Performance: measuring and choosing speed-ups

This page answers: how do I tell whether a speed-up is real, where does render time actually
go, and which quantization and distillation choices held up on 16 GB consumer cards? Every
number carries its date, box and ComfyUI version. Numbers from 0.27.1 or 0.33.1 were not
re-measured on 0.42.1, which both render boxes run since 2026-10-20.

> **TL;DR**
> - Measure before tuning. On the quality line every intuitive cause (network, model loading, polling) was wrong; detailer resampling was the cost.
> - A/B as A-B-A, with an explicit off arm, warm runs, at least 3 seeds, median. One SDXL pipeline showed 24% seed variance, so a single-sample A/B cannot resolve differences under about 20%.
> - Change the biggest lever first, then re-measure the rest. Borrowed numbers are hypotheses.
> - Adopted: mxfp8 weights plus INT8 attention (2.11x on Anima 3.8B on an RTX 50 card, quality intact; mxfp8 speeds up Blackwell cards only). Collapsed: uncalibrated nvfp4. Rejected: fp8 matmul on Box B, a few-step video distill.
> - Quality tiers are judged by me, not the agent. Speed from weight format and kernels cannot be packaged as a LoRA.

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
6. Run A-B-A (or ABBA) in one time window. Record per-image sampling time and wall time
   separately.
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

## Tried and dropped

- Hand-written kernels (measured ceiling about 5% end to end).
- Uncalibrated nvfp4 W4A4.
- fp8 matmul on Box B: Anima's MLP feeds 5-D tensors, which the fp8 path silently routes to
  the fallback, and input conversion ate the 13% matmul gain.
- Per-pass `/free` removal as a speed lever.
- Box B LoRA-training levers (2026-09-03): gradient checkpointing off, batch 2 (9.5% slower),
  compile (no effect: LoRA injection by forward monkey-patch breaks the graph), full AdamW
  (same steady state). 2.9 to 3.0 s/it at 1024 px is the card's level.
- Distributed training across the two Windows boxes: no NCCL, 2.5 GbE link.
- A cache node on Qwen-Image text-to-image: no effect.

## See also

- [`04-model-bringup.md`](04-model-bringup.md): adopting a quantized model.
- [`05-debugging.md`](05-debugging.md): OOM, driver resets, polluted processes.
- [`06-render-discipline.md`](06-render-discipline.md): smoke timing before a batch.
- [`templates/ab-test.md`](../../templates/ab-test.md): the write-up template.
