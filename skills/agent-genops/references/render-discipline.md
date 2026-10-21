# Render discipline

Purpose: run renders on a shared GPU box without wasted GPU time, overwritten results or leftover junk.
Read when: about to render 3 or more images, start or stop a queue, release VRAM, clean up test renders, or show results to the owner.

## Hard rules

- Batch of 3 or more: render 1 smoke with the exact batch command first. No exceptions.
- Smoke time x count > 30 min: report the total and wait for a go before starting.
- One render, one destination. Move each output (image plus sidecar, as a group) before the next render starts.
- Assume engine filenames collide (same seed, same LoRA) unless the engine proves a unique suffix.
- Every run writes to a new, empty directory. Refuse a non-empty one. Two queues never share a result dir.
- Probe the box before dispatch. HOLD (probe exit code 3) = do not dispatch.
- Never free VRAM after every image. Leave the lease to the idle reaper.
- Never use the Windows Recycle Bin from a remote session. It deletes permanently.
- Never paste media into the conversation. Deliver a gallery link.

## Pick the engine by what the step verifies

| The step verifies | Use | Typical cost |
|---|---|---|
| style, composition, pose, prompt hit | base pass, fast tier | seconds to tens of seconds per image |
| a new model, one image per model | the model's own fast or default recipe | one image each, no bare-model matrix |
| a finished deliverable | quality stack (upscale plus detailers) | minutes per image |

Do not assume the quality-stack recipe is current; read the project state file.

## Smoke check (fill templates/smoke-check.md)

1. Run the batch command with count 1.
2. Record wall time per image (warm; drop a cold first run if the model had to load).
3. Record every path written: image, sidecar, result JSON, any post-processing copy.
4. Check the filename rule: would a second image with the same seed or LoRA overwrite this one?
5. Compute total = time per image x count. Write it into the order.
6. Total > 30 min: stop and report.

## Box etiquette

| Situation | Action |
|---|---|
| probe returns HOLD | wait, or switch box; say which |
| owner is running own work on the main box | wait for 3 consecutive idle probes |
| owner may be gaming | no model-based 4x upscale; use higher native resolution in one pass |
| test renders on the worker box | allowed without per-batch approval; cap 15 images; smoke first |
| main box, network change, deleting non-test data | ask first |
| box looks dead | probe the queue endpoint; ping is firewalled; system-stats is not a health check |

## Queues and processes

- Launch each item as `render && keep`.
- Stop with the process group: `kill -- -<PGID>`, or kill children recursively before the runner.
- Then list processes matching the runner, command file and engine names. Nothing may remain.
- Stop the queue before re-planning. Restart only after the new plan is written.
- Windows box: start long work via WMI process creation, not inside the SSH session. Delete one-shot scheduled-task definitions right after launch; at wrap-up a prefix query must be empty.
- Timed-out queued prompt: delete by exact id and confirm it is gone. Never interrupt a running prompt (box-wide).

## VRAM

- After `--run`, a lease is stamped. The reaper frees after 300 s idle with a readable, empty queue.
- Need the card now: use the router's free-now flag.
- Full unload (all models plus caches): only when switching models or the owner is done. Use the one global free command with explicit box and mode.
- Same-seed comparison after IP-Adapter, VACE or dtype-changing nodes: full memory free first, or results differ.
- Black images after a long session: restart the box, do not chase precision.
- Idle thresholds must account for resident models (free VRAM sits lower when models stay loaded).

## Cleanup

- Default: delete test renders. Keep only what the owner explicitly names; say which and where.
- Clear after every verdict round, not only at task end. Comparison sheets are test renders.
- List targets and sizes before deleting.
- Controller side: system trash.
- Windows box: move to `<drive>:\_trash_YYYYMMDD\<original relative path>` on the same disk, write a restore map, let the owner delete the folder.
- Box locations to check: ComfyUI `output`, `input`, `temp`.
- Never touch datasets, training checkpoints, converted LoRAs, model files.
- Cannot clean remote now: write leftovers into a CLEANUP file in the order directory.
- Select remote files by filename range or by age computed on the box. Box clocks can differ from the controller.

## Delivery

1. Register one gallery batch per review round from the main checkout (never start the gallery server from a worktree).
2. Default mode: view grid. Use one-at-a-time verdict mode only when the next step depends on picks.
3. Hand the owner the link.
4. Read verdicts back from the result endpoint: `love`, `yes`, `no`, `comments`, `pending`. Non-empty `pending` = unfinished, not rejected.
5. Batches are immutable. Changed files: register a new batch.

## Stop conditions

- Probe HOLD and no other eligible box: stop, report the reason.
- Smoke shows a filename collision or an unexpected write path: stop, fix isolation, smoke again.
- Total > 30 min: stop, report.
- A process survives the group kill: stop, report the pid and parent chain; do not start a new queue.
- Cleanup would touch anything outside output subfolders: stop, ask.

## Report

- Exact command, exit code, smoke time per image, total time.
- Output directory and count delivered vs requested (short delivery is not success).
- Gallery link.
- What was cleaned on each side, what remains and where (CLEANUP file if any).
- Lease state: open, freed, or freed now.
