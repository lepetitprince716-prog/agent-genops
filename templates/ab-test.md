# A/B: <one-line question>

<!--
One variable per write-up. Fill before running, then fill results. A difference inside the
measured seed variance is "not resolved", not a win. Quality tiers are the owner's call; the
agent records technical breakage only. Delete test images after the verdict; keep this file.
-->

Date: YYYY-MM-DD
Author: <session / worker, model, effort>
Status: planned | running | done

## Question

<What decision does this answer? e.g. "Does mxfp8 keep quality on model X at 1.5x speed?">

## Variable

- Changed: <exactly one thing>
- Hypothesis: <expected effect and size; cite any borrowed number with its model, box and version>

## Fixed settings

| Setting | Value |
|---|---|
| Box / GPU | |
| ComfyUI version | |
| torch / CUDA | |
| Launch flags | |
| Model file (sha256 prefix) | |
| Prompt | |
| Resolution | |
| Sampler / scheduler / steps / CFG | |
| LoRA set and strengths | |
| Resident model or per-call load | |

## Arms

| Arm | Setting | Purpose |
|---|---|---|
| A | <baseline> | Control |
| B | <treatment> | Effect |
| Off | <toggle explicitly off> | Separates "ineffective" from "already on" |
| LoRA control | <strength 0.001, never 0> | Only for LoRA tests |

Order: A-B-A | ABBA, all arms in one time window on one box.

## Seeds

- Seeds: <at least 3, same in every arm>
- Warm-up: <first run per arm discarded: yes>

## Variance note

- Measured seed variance of this pipeline: <percent, how measured>
- Smallest difference this test can resolve: <percent>
- Reference: one SDXL detailer pipeline showed 24% across seeds; bare Qwen-Image sampling about 1%. Measure, do not borrow.

## Results: timing

| Arm | Seed | Sampling time (s) | Wall time (s) | Notes |
|---|---|---|---|---|
| | | | | |

| Arm | Median sampling | Spread | Ratio vs A |
|---|---|---|---|
| | | | |

Resolved: yes | no (inside variance)

## Results: quality

- Pixel difference vs A (mean, per seed): <values>
- Composition: <same / drifted; what moved>
- Technical breakage found: <garbled text, collapsed structure, under-denoising, none>
- Review page / batch id: <where the owner looked>
- Owner verdict: <quote or summary, date> | awaiting owner

## Verdict

Adopted | rejected | not resolved — <one sentence, with the main number and its conditions>

Follow-ups: <re-measure on new version, more seeds, next lever after this one>

## Cleanup

- [ ] Test images deleted on the controller
- [ ] Test images moved to quarantine on the box (or listed in a cleanup note)
- [ ] Numbers copied into the model card
