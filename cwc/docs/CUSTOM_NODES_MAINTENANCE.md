# Custom Nodes Maintenance Handbook (`cwc`)

> Standard Operating Procedure for curating, updating, verifying, and deprecating high-frequency
> ComfyUI custom node definitions bundled in `src/cwc/data/custom_nodedefs.json`.

## 1. Philosophy: High-Leverage Curated Packs, Not Endless Chasing

ComfyUI custom nodes ship updates weekly. Trying to vendor every obscure node pack into `cwc` creates
perpetual schema drift. Instead, `cwc` follows a three-tier strategy:

1. **Core 702 nodes (`core_nodedefs.json` + `core_truth.json`)**: Always loaded by default (`NodeDefs.load()`),
   captured from a verified ComfyUI release and pinned by `tests/test_build_core_data.py`.
2. **Curated high-frequency custom packs (`custom_nodedefs.json`)**: Enabled via `NodeDefs.load(include_custom=True)`
   or `--custom-packs` on `cwc compile`, `cwc node`, and `cwc render`. Covers the top community packs
   used by real workflows (`rgthree-comfy`, `ComfyUI-Easy-Use`, `ComfyUI-KJNodes`,
   `ComfyUI-Impact-Pack`, `ComfyUI-Lora-Manager`, `comfyui_controlnet_aux`, `ComfyUI_IPAdapter_plus`,
   `ComfyUI_UltimateSDUpscale`, `ComfyUI-Detail-Daemon`, `ComfyUI-TeaCache`, `ComfyUI_LayerStyle`,
   `ComfyUI-Florence2`, `ComfyUI-GGUF`, `ComfyUI-Crystools`, `ComfyUI-Prompt-Assistant`) plus our
   first-party companion pack (`canvas-turbo/` in this repository).
3. **Live server or learned templates (`--nodedefs <FILE|URL>` + `cwc learn`)**: Always overrides bundled
   custom packs whenever a user points `cwc` at their live ComfyUI `/api/object_info` or records widget
   templates for custom frontend extensions.

## 2. Inclusion & Rejection Criteria

A custom node belongs in `custom_nodedefs.json` ONLY when all 4 criteria hold:

- **High frequency**: Used across standard multi-model, ControlNet, Detailer, Upscale, or layout workflows.
- **Stable socket/widget contract**: Inputs, outputs, and `widgets_values` order are documented or captured
  from real `/api/object_info`.
- **Anti-lag compatible**: **Never** encourage or promote `Use Everywhere` (`Anything Everywhere*`,
  `Seed Everywhere`, `Prompts Everywhere`) nodes—they trigger $O(N^2)$ wildcard graph scanning in large
  workflows. Prefer `cwc`'s native 1-level `--pack-subgraphs` + explicit typed buses (`ToBasicPipe` / `Context Big`).
- **Zero hardcoded node names in Python**: All node metadata MUST live in `src/cwc/data/*.json`, never as
  string literals in `src/cwc/**/*.py` (enforced mechanically by `tools/lint_no_node_names.py`).

## 3. Step-by-Step Update Procedure (Agent & Maintainer Checklist)

### Step A — Export Clean `/object_info`
Capture the node's `/api/object_info/<NodeType>` entry from a running ComfyUI server (or verified card dump):
```bash
curl -s http://127.0.0.1:8188/api/object_info/<NodeType> | python3 -m json.tool
```

### Step B — Scrub Private / Machine-Specific Data (Mandatory Privacy Gate)
Before adding any entry to `src/cwc/data/custom_nodedefs.json`:
1. **Replace local model/LoRA/file dropdown lists** (`ckpt_name`, `unet_name`, `lora_name`, `model_name`)
   with 1–3 generic public placeholder names (e.g., `flux1-dev-Q6_K.gguf`, `bbox/face_yolov9c.pt`).
2. **Strip absolute paths, usernames, LAN IPs, URLs with credentials, and local folder hierarchies**.
3. **Keep `output_node` accurate** (`true` for preview/save/display sinks, `false` otherwise) because
   `cwc`'s `annotate` and `--pack-subgraphs` rely on `output_node` to keep final gallery nodes on the root canvas.

### Step C — Handle Frontend-Only / Dynamic-Widget Custom Nodes
Nodes whose frontend JS injects extra widgets not declared in `/object_info` (e.g., `Power Lora Loader (rgthree)`):
- Record a curated widget template using `cwc learn <sample.ui.json> -o custom_templates.json` (paired with
  `<sample.api.json>` or PNG metadata), then verify `canvas_to_prompt` round-trip fidelity.

### Step D — Mandatory Verification Gates (Run All 4 Before Commit)
```bash
cd cwc
python3 -B tools/lint_no_node_names.py
ruff check src tests tools
python3 -B -m unittest discover -s tests
cd .. && ./check changed
```

## 4. Precedence Rules (Never Break These Invariants)

1. `NodeDefs.load()` (default `include_custom=False`) MUST keep returning only `{Tier.TRUTH, Tier.BUILTIN}`
   so strict core-only callers and unit tests never see unexpected custom definitions.
2. When `include_custom=True`:
   - Bundled `core_nodedefs.json` entries ALWAYS take precedence over `custom_nodedefs.json` (custom packs
     cannot shadow core ComfyUI nodes).
   - User-supplied `--nodedefs` ALWAYS overrides `custom_nodedefs.json`.
3. Every entry in `custom_nodedefs.json` MUST parse cleanly through `cwc.nodedefs.derive.from_object_info`
   without warnings or `NaN`/`Infinity` constants.

## 5. Deprecation & Removal

When an upstream custom node pack renames or drops a node:
1. Keep the legacy entry only if existing community workflows still reference it; mark its `category` clearly
   or move version-specific widget orders into `templates.json` keyed by `ver`.
2. Remove entries only after verifying zero showcase or test workflows depend on them and running the full
   4-gate checklist above.
