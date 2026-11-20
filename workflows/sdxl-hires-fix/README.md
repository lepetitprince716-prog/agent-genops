# SDXL text to image with a hires fix

The same graph as `../sdxl-txt2img/`, plus a second pass: sample a 1024 x 1024 latent, scale
the latent up by 1.5, and sample it again at a low denoise so the larger image gets detail
instead of a new composition. One decode at the end, from the second pass. Every node ships
with ComfyUI.

| File | What it is |
|---|---|
| `sdxl-hires-fix.json` | The input, written by hand: a ComfyUI API graph with `cwc` intents (`_workflow`, `_meta`) |
| `sdxl-hires-fix.ui.json` | The canvas `cwc compile` writes from it, to load in the ComfyUI frontend |
| `sdxl-hires-fix.api.json` | The API prompt the canvas exports, for `POST /prompt` |

## Model

- `sd_xl_base_1.0.safetensors`, Stability AI's SDXL base 1.0 checkpoint, from
  https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0. It goes in ComfyUI's
  `checkpoints` model folder. The canvas carries the download address in its `models` list.
- Licence: CreativeML Open RAIL++-M, https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md.
  Read it yourself before you rely on it; this is not legal advice. Source and licence notes
  are the same as in `../sdxl-txt2img/README.md`.
- The workflow files themselves carry no model weights.

## Settings and where they come from

- First pass: the settings of `../sdxl-txt2img/` (1024 x 1024, `dpmpp_2m`, `karras`, cfg 7,
  25 steps, denoise 1, seed 0 fixed), taken from ComfyUI's base-only SDXL template
  `templates/image_sdxl_simple.json` in https://github.com/Comfy-Org/workflow_templates.
- Second pass: same sampler, scheduler, cfg, steps and seed, with denoise 0.4. The latent
  upscale is `LatentUpscaleBy`, `nearest-exact`, scale 1.5 (1536 x 1536).
- The denoise 0.4 and the scale 1.5 are not official recommendations. ComfyUI's template
  library has no SDXL hires-fix template, and the ComfyUI 2-pass example
  (https://comfyanonymous.github.io/ComfyUI_examples/2_pass_txt2img/) describes the method
  without a denoise value for this model. They are example starting points, and no image has
  been generated on a real install to check them. A lower denoise keeps the first pass more
  closely; a higher one changes more. Expect to tune both.
- The negative prompt is the same as in `../sdxl-txt2img/`; both samplers read the same
  prompts.

## Changing the inputs

Change the input graph and compile again; do not edit the canvas and the API prompt by hand,
or they stop matching the input.

- Second pass strength: `denoise` of the `sampler2` node. Scale: `scale_by` of the `up` node.
- Prompts, size, seed and sampler: as in `../sdxl-txt2img/README.md`; the second pass has its
  own `seed`, `steps`, `cfg`, `sampler_name` and `scheduler`.

Compile from the `cwc/` folder of this repository:

```
python3 -m cwc compile ../workflows/sdxl-hires-fix/sdxl-hires-fix.json -o <scratch folder>
```

(run with `PYTHONPATH=src`, or after `pip install -e .`; the preset is set in the input).
Copy only the `.ui.json` and `.api.json` files back; the `.report.json` stays out of the
repository. Then run `python3 tools/workflow_policy.py` from the repository root.

## Layout

The input asks for the `stepped` layout preset: with `bento` this two-pass graph gets a
canvas wider than cwc's aspect-ratio limit and a G9 warning, and `stepped` compiles without
findings.

## What was tested

- Tested: `cwc compile` succeeds with an `ok` report and no warnings; compiling again in a
  clean folder gives byte-identical files; the canvas exports the committed API prompt
  (cwc's own equivalence check); the files pass `tools/workflow_policy.py`. All of this runs
  in `tests/test_workflow_policy.py`.
- Not tested: no image was generated on a real ComfyUI install, and the canvas was not opened
  in a real ComfyUI frontend for this workflow.
