# Model bring-up

Purpose: take a new checkpoint, quantized file, LoRA family or ComfyUI runtime from discovery to "adopted" or "no_gain".
Read when: a new model, quantization or ComfyUI version is proposed, downloaded, or about to be wired into a recipe.

## Hard rules

- Decide downloads from the repository file listing. Ignore what the README claims exists.
- Read the safetensors header before trusting a title or version label: tensor dtype, tensor count, block count, parameter count.
- Find the real model root by locating a known model file. Never assume the default `models` directory.
- Hash every download (sha256) against the hub before moving it into a model directory.
- After adding weights or nodes: restart the server, then prove the restart (process start time, or the new name in `object_info`).
- New ComfyUI core needed: run a sidecar. Never upgrade production in place as the first step.
- Wire graphs from the official reference workflow. Submit API-format graphs. Never build from memory.
- Check block counts before attaching any LoRA or control weight. Mismatch fails silently.
- LoRA control arm: strength 0.001. Strength 0 is short-circuited and proves nothing.
- First look: ONE image per new model, with the owner's usual LoRA stack. Ask before rendering any bare-model matrix.
- Machine gates may only reject. The owner decides adoption.
- Never reuse a purpose-built eval script as a cross-model bench.
- Defaults resolve from registry roles. Never hard-code a model name in a recipe.

## Steps

1. Research: file listing, licence, release date, author's recommended steps / CFG / sampler. For fast-moving models, verify every number you will rely on against a primary source.
2. Header check: dtype (labels lie: a "FP8" file was INT8), block count, parameters. Record them.
3. Download (see table). Resume on failure. Hash after download.
4. Place under the real root. Restart. Confirm the exact registered name in `object_info`.
5. Build the graph from the official workflow. For a new runtime, run it as a sidecar (below).
6. Architecture check: blocks of base vs LoRA vs control weight. Remap if needed. Verify patches == LoRA tensors / 3.
7. Smoke: one image. Record per-image time, write path, filename rule.
8. First look: one image with the usual LoRA stack, same prompt and seed as the current default.
9. Gates reject broken images. Put survivors on one review page for the owner.
10. Write the model card (`templates/model-card.md`). Fill speed with date, box, ComfyUI version, warm median.
11. Adopted: set registry role, freeze eval engine by hash, register recipes by name.
    Dropped: status `no_gain`, archive weights if kept, delete local test images.

## Download routes

| Situation | Route |
|---|---|
| Hub reachable directly or via working proxy | Plain HTTP Range downloader with resume; disable XET behind a proxy |
| Hub slow or blocked | Check ModelScope for the same repo; download direct; verify against hub sha256 |
| Mirror only | Mirror + aria2 with 8 connections; verify with `Get-FileHash` afterwards (aria2 checksum flag breaks through PowerShell) |
| Civitai LoRA | The box's LoRA manager download API; poll progress; pause/resume on stall |
| Mirror snapshot install | Repo sha from mirror API, files into the snapshot path, write `refs/main`; Python 3.11+ |

- Never send a hub token to a mirror.
- Progress: aria2 counters, or `os.walk` over the target (glob skips hidden cache dirs). Not file length.
- Stopping the local call does not stop the remote download. Kill the remote process by command line.
- Model directories are scanned dynamically: half-finished files appear in lists. Check byte count before running.

## Sidecar runtime

- Own base directory, own custom-node whitelist, loopback-only port.
- Never load production's extra-model-paths file.
- Start through WMI process creation (survives the SSH session). See `windows-gpu-box.md`.
- If its venv inherits the production venv, an in-place production upgrade changes it too. Check before upgrading.
- Free VRAM on the main server before a sidecar run; sidecars share the GPU. Keep sidecars stopped when idle.
- Stop by matching command line (port + private root), never by image name.

## Production upgrade

1. Back up the UI database (newer versions migrate it; old versions then cannot open it).
2. Clone the production venv. Install only the wheels the new version pins.
3. Run a sibling instance on another port.
4. Same-seed A/B per model family. Accept: pixel-identical, or unchanged composition with modest PSNR drop (Anima saw 28 to 37 dB on 0.27.1 to 0.42.1). Record warm and cold timings.
5. Switch the service. Keep the old runtime and the DB backup for rollback. Never move a live production runtime into a trash folder.

## Block-count check (Anima example)

| Base | Blocks | 28-block LoRA | 28-block control weight |
|---|---|---|---|
| 2B | 28 | Native | Native |
| 2.9B | 40 | Remap 28→40 | Remap node only; core node misaligns silently |
| 3.8B | 52 | Remap 28→52 | Refuse (no 52-block control manifest on 2026-09-16; not re-checked since the 28→52 LoRA manifest of 2026-09-17) |

- Patch count 0 = wrong key dialect or table. Fix before rendering.
- Deriving a missing remap: per-block cosine between native and extended checkpoints on two independent probe weights; both probes must agree on every block.

## Stop and report

- Licence forbids the intended use, or accepting terms is the owner's step (gated repo).
- Download route needs a network-plane change.
- Upgrade or node install on the shared main box without the owner's go-ahead.
- Two failed attempts of the same shape (see `debug.md`).

## Report

- Model, source, file, size, sha256 match (yes/no), blocks, params.
- Where it lives (registered name only), runtime and version used.
- Smoke result: per-image warm time, ComfyUI version, box, date.
- First-look image path and review page. Gate results.
- Verdict requested from the owner, or verdict recorded. Card path.
