# SDXL text to image with optional LoRAs

The smallest SDXL graph with two `LoraLoader` nodes chained between the checkpoint and the
prompts and sampler. Both are one optional module: `cwc` marks them bypassed and groups them
as "Optional LoRAs", so the canvas runs as plain SDXL until you switch them on. Every node
ships with ComfyUI.

| File | What it is |
|---|---|
| `sdxl-lora.json` | The input, written by hand: a ComfyUI API graph with `cwc` intents (`_workflow`, `_meta`) |
| `sdxl-lora.ui.json` | The canvas `cwc compile` writes from it, to load in the ComfyUI frontend |
| `sdxl-lora.api.json` | The API prompt the canvas exports, for `POST /prompt` |

## Model

- `sd_xl_base_1.0.safetensors`, Stability AI's SDXL base 1.0 checkpoint, from
  https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0. It goes in ComfyUI's
  `checkpoints` model folder. The canvas carries the download address in its `models` list.
- Licence: CreativeML Open RAIL++-M, https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md.
  Read it yourself before you rely on it; this is not legal advice. Source and licence notes
  are the same as in `../sdxl-txt2img/README.md`.
- The workflow files themselves carry no model weights.

## The LoRAs

- The two loaders name `your_lora_a.safetensors` and `your_lora_b.safetensors`. They are
  placeholders: no such files exist and this folder points to no LoRA. Put SDXL LoRA files
  in ComfyUI's `loras` model folder and choose them in the two `LoraLoader` nodes. A LoRA
  trained for another base model will not match SDXL; check each file's own page for its
  base model and licence.
- Strengths are 0.8 for both the model and the text encoder, in both loaders. This is an
  example starting point, not an official value, and no image has been generated to check it.
- The module ships bypassed. In the frontend, select the two nodes and take them out of bypass
  (Ctrl+B toggles it, from memory of the frontend, not checked here). For one LoRA, bypass `LoRA 2` alone: the chain then skips it.
- The committed API prompt (`sdxl-lora.api.json`) is the exported state of the shipped
  canvas, so it has no LoRA nodes and wires the checkpoint straight to the prompts and the
  sampler. To get an API prompt with LoRAs, enable the module in the input graph (remove
  `ui_optional` from both loaders' `_meta`), choose real file names, and compile again.

## Settings and where they come from

- Everything else is the same as `../sdxl-txt2img/`: 1024 x 1024, `dpmpp_2m`, `karras`,
  cfg 7, 25 steps, denoise 1, seed 0 fixed, taken from ComfyUI's base-only SDXL template
  `templates/image_sdxl_simple.json` in https://github.com/Comfy-Org/workflow_templates.
  ComfyUI's template library has no SDXL LoRA template; the LoRA nodes and their strengths
  are written here, not copied from a template.

## Changing the inputs

Change the input graph and compile again; do not edit the canvas and the API prompt by hand,
or they stop matching the input.

- LoRA files and strengths: `lora_name`, `strength_model`, `strength_clip` of `lora_a` and
  `lora_b`. Register each new file name in `tools/workflow_policy.json` before you commit it
  to this repository, as a bare file name.
- Everything else: as in `../sdxl-txt2img/README.md`.

Compile from the `cwc/` folder of this repository:

```
python3 -m cwc compile ../workflows/sdxl-lora/sdxl-lora.json -o <scratch folder>
```

(run with `PYTHONPATH=src`, or after `pip install -e .`; the `bento` preset is set in the
input). Copy only the `.ui.json` and `.api.json` files back; the `.report.json` stays out of
the repository. Then run `python3 tools/workflow_policy.py` from the repository root.

## What was tested

- Tested: `cwc compile` succeeds with an `ok` report and no warnings; compiling again in a
  clean folder gives byte-identical files; the canvas exports the committed API prompt
  (cwc's own equivalence check); the files pass `tools/workflow_policy.py`. All of this runs
  in `tests/test_workflow_policy.py`.
- Not tested: no image was generated on a real ComfyUI install, and the canvas was not opened
  in a real ComfyUI frontend for this workflow, so the bypass switch above is cwc's documented
  behaviour, not something seen in the frontend. No real LoRA file was loaded.
