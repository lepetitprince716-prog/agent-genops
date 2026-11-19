# SDXL text to image

The smallest SDXL graph: load the checkpoint, encode a positive and a negative prompt, sample
an empty 1024 x 1024 latent, decode, save. Every node ships with ComfyUI.

| File | What it is |
|---|---|
| `sdxl-txt2img.json` | The input, written by hand: a ComfyUI API graph with `cwc` intents (`_workflow`, `_meta`) |
| `sdxl-txt2img.ui.json` | The canvas `cwc compile` writes from it, to load in the ComfyUI frontend |
| `sdxl-txt2img.api.json` | The API prompt the canvas exports, for `POST /prompt` |

## Model

- `sd_xl_base_1.0.safetensors`, Stability AI's SDXL base 1.0 checkpoint, from
  https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0 (file listing read 2026-11-19).
  It goes in ComfyUI's `checkpoints` model folder. The canvas carries the download address in
  its `models` list, the same field ComfyUI's own templates use for their model downloads.
- Licence: CreativeML Open RAIL++-M, dated 2023-07-26,
  https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md (read
  2026-11-19). Redistribution and hosted use are allowed under its conditions, which include
  passing its use restrictions (Attachment A) on to your users. Read the licence yourself
  before you rely on this summary; this is not legal advice.
- The workflow files themselves carry no model weights.

## Settings and where they come from

- Size: 1024 x 1024. The ComfyUI SDXL examples page asks for 1024 x 1024 or another size with
  the same number of pixels, such as 896 x 1152 or 1536 x 640
  (https://comfyanonymous.github.io/ComfyUI_examples/sdxl/, read 2026-11-19).
- Sampler: `dpmpp_2m`, scheduler `karras`, cfg 7, 25 steps, denoise 1. These are the values in
  ComfyUI's own base-only SDXL template, `templates/image_sdxl_simple.json` in
  https://github.com/Comfy-Org/workflow_templates (last changed 2026-09-28, read 2026-11-19).
  Neither the model card nor the ComfyUI examples page names a sampler, so these values rest on
  that template alone; whether they are the best choice is not verified.
- Seed 0, fixed, so the seed stays the same from one run to the next.
- Negative prompt `lowres, blurry, watermark, text, logo, signature`, a subset of the same
  template's negative prompt.

## Changing the inputs

Change the input graph and compile again; do not edit the canvas and the API prompt by hand,
or they stop matching the input.

- Prompts: the `text` of the `pos` and `neg` nodes.
- Size: `width` and `height` of the `latent` node, keeping about one megapixel.
- Another SDXL checkpoint: `ckpt_name` of the `ckpt` node, and the `models` entry in
  `_workflow` (or drop that entry if the file has no public download address).
- Sampling: `seed`, `steps`, `cfg`, `sampler_name`, `scheduler` of the `sampler` node.

Compile from the `cwc/` folder of this repository:

```
python3 -m cwc compile ../workflows/sdxl-txt2img/sdxl-txt2img.json -o <scratch folder> --preset bento
```

(run with `PYTHONPATH=src`, or after `pip install -e .`). Copy only `sdxl-txt2img.ui.json` and
`sdxl-txt2img.api.json` back; the `.report.json` stays out of the repository. Then run
`python3 tools/workflow_policy.py` from the repository root, and register any new node type or
model name in `tools/workflow_policy.json`.

## What was tested

- Tested: `cwc compile` succeeds with an `ok` report; compiling again in a clean folder gives
  byte-identical files; the canvas exports the committed API prompt (cwc's own equivalence
  check); the files pass `tools/workflow_policy.py`. All of this runs in
  `tests/test_workflow_policy.py`.
- Not tested: no image was generated on a real ComfyUI install, and the canvas was not opened
  in a real ComfyUI frontend for this workflow.
