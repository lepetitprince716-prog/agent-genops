# Standard ComfyUI workflows

Each folder holds one workflow: the input graph written by hand, the canvas (`*.ui.json`) and
the API prompt (`*.api.json`) that `cwc compile` produces from it, and a README with the
model source, licence, settings and what was tested.

| Folder | What it does |
|---|---|
| `sdxl-txt2img/` | SDXL base 1.0 text to image, the smallest graph |
| `sdxl-hires-fix/` | The same, with a latent upscale and a second low-denoise pass |
| `sdxl-lora/` | The same, with two optional LoRA loaders (placeholder file names) |

Every file here is checked by `tools/workflow_policy.py` against the registry
`tools/workflow_policy.json`: registered files only, registered node types and model names,
and no paths, private addresses, credential-carrying URLs, embedded media or opaque data in
any string. Run it from the repository root:

```
python3 tools/workflow_policy.py
```

No generated images live here: they carry the whole workflow in their metadata.
