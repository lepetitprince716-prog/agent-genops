# Model temperament card: <model name and version>

<!--
One card per model file (or per baked variant). Fill every field; write "unknown" rather
than guess. Numbers carry date, box, GPU and ComfyUI version. Update the status line when
the verdict changes; keep the history section append-only.
-->

Status: candidate | adopted (<role>) | experimental_worker_only | no_gain | archived
Registry role: <e.g. quality_default, fast_default, none>
Last reviewed: YYYY-MM-DD by <session or person>

## Identity

| Field | Value |
|---|---|
| Family / architecture | <e.g. Anima DiT, SDXL UNet, Qwen-Image 2.1 single-stream DiT> |
| Parameters | <from header> |
| Blocks / layers | <from header; drives LoRA and control compatibility> |
| Weight dtype | <from header, not from the title> |
| File size | <bytes> |
| sha256 | <matches hub: yes / no / no hub hash> |
| Source | <hub page, version id, release date> |
| Licence | <name; redistribution and commercial terms in one line> |
| Loader and companions | <UNETLoader / checkpoint; text encoder; VAE; required nodes> |
| Runtime | <main server or sidecar; minimum ComfyUI version> |
| Boxes that have it | <Box A / Box B; registered name per box> |

## Recipe

| Setting | Value | Source |
|---|---|---|
| Steps | | <author / measured / owner decision, date> |
| CFG | | <note: at CFG 1 the negative prompt is inert> |
| Sampler / scheduler | | |
| Shift / model sampling | | |
| Resolution tiers | | <must the canvas be a multiple of 8 / 16?> |
| Distillation | <none / pre-distilled / needs turbo LoRA at x> | <never stack a turbo LoRA on a distilled model> |
| Default LoRA stack | <names and strengths, or "none"> | |

## Prompt rules

- Prompt form: <tags / natural-language sentences / mixed>
- Quality or score tags: <allowed / banned, with the measurement or decision behind it>
- Attention weight syntax: <works / banned (why)>
- Must state: <e.g. framing, hair length, composition for two people>
- Must avoid: <phrasings that reliably fail>
- Negative prompt: <live / dead at this CFG>

## Good at

- <shot types, styles, subjects it handles reliably; one line each with evidence>

## Bad at

- <priors it fights; anatomy or lighting limits; things no prompt fixed>
- <state when a limit belongs to the base, not to quantization or a LoRA>

## Measured speed

| Box / GPU | ComfyUI | Resolution | Steps / CFG | Warm median | Cold | Seeds | Date |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

Notes: <launch flags, attention backend, resident or not, what was excluded (cold start, warm-up)>

## Compatibility

- LoRA: <block count expected; remap needed; patch count check result (patches == tensors / 3)>
- Control / IP-Adapter: <which weights work; which misalign silently>
- Quantized variants: <format, speed ratio, quality verdict, link to A/B write-up>
- Known crash: <e.g. LoRA on a partially loaded INT8 file>

## Known traps

- <symptom, cause, workaround, date>

## Evaluation

- First look: <date, one image with the usual LoRA stack, review page or batch id>
- Machine gates: <which gates, pass counts; gates only reject>
- Owner verdict: <quote or summary, date>
- Eval bank: <frozen engine hash, bank id, or "not frozen">

## Verdict

<Adopt / drop / keep as experimental, in one or two sentences, and what would reopen it.>

## History

- YYYY-MM-DD <change, measurement or verdict>
