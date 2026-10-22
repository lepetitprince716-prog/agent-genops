# Inventory

Purpose: find models, LoRAs, recipes and scripts by lookup instead of guessing, and keep outputs, archives and spend traceable.
Read when: choosing a model or LoRA, downloading a model, writing a new script, filing outputs, archiving, or spending cloud credits.

## Hard rules

- Model names come from the model index (`canonical_name`) or the live server's object info. Never type a filename from memory.
- Never hand-edit an index. Regenerate it.
- Never write an unreachable box as an empty inventory.
- Read block count and dtype from the safetensors header before pairing a LoRA or control weight with a base.
- Model bytes go straight to the render box. The controller sends commands and polls.
- Read the script registry and its generated catalogue before writing any new script.
- Cold archive: fail closed at 80% of the free tier, no delete flag, private bucket, no plaintext credentials in the agent.
- Every cloud render and every remote job gets a ledger row.

## Model index commands (shape)

| Need | Command | Notes |
|---|---|---|
| is the index fresh | `status` | exit 3 = stale: run `refresh` |
| update after new files | `refresh` | read-only, incremental, prints NEW count; non-zero exit and old index kept if box unreachable |
| find a LoRA by intent | `lookup "<intent>" --kind lora --base <family>` | semantic; returns `canonical_name`, triggers, strengths, rating, why |
| list new LoRAs | `lookup --kind lora --new` | after `refresh` |
| checkpoints, VAE, control, upscale | `lookup "<text>" --kind <kind>` | deterministic name/base/tag filter |

- Run `refresh` with the interpreter that has the embedding stack, or status reads `partial`.
- Embeddings unavailable: use lexical matching over the same index. Do not block on the semantic path.
- `content_rating=unknown` stays unknown and labelled.
- Self-trained LoRAs show base "Unknown" by design. Do not fix.

## Architecture check before pairing

1. Read the header: block count, parameter count, tensor dtype. Ignore vendor labels (an "FP8" file can be INT8).
2. Compare base blocks with LoRA or control blocks (Anima: 28, 40, 52).
3. Mismatch: remap keys to the base's block count.
4. Verify: applied patches = LoRA tensors / 3. Zero patches = wrong key dialect or table. Stop.
5. Control weights with a different block count: do not use. They misalign silently.
6. Record `blocks` on the model card. Resolve defaults from card roles, never from hard-coded names.

## Download a model to a render box

1. Decide the file from the repository file listing, not the model card text.
2. Start the on-box download manager (on demand only).
3. Request the download with model and version ids. Set the target root explicitly; default-path mode ignores the root you pass.
4. Poll progress. aria2 backend: done when the control file disappears.
5. Verify sha256 against the hub's LFS object id.
6. Rebuild the index and embeddings.
7. Stop the manager (also closes its tunnel).
- A box "lacks a feature": check the version of the tool copy on that box first.
- Never echo or copy the hub key; it stays in the box's settings.

## Recipes

- Two layers: store on the box (material), local library (management: provenance, lineage, runs).
- Trace chain: image -> job -> brief -> recipe -> parent recipe -> source.
- `to-brief` has no side effects. Inspect the brief before `generate`.
- Missing LoRAs: warn, never substitute. At most 4 extra LoRAs. Recipe negative is appended, not replaced.
- Deleting from the store: owner confirmation required.

## Scripts

1. Search the registry and generated catalogue for an existing script with the same job.
2. Discovery order: router `--list`, then catalogue, then companion docs.
3. Status (active, probe, legacy, test, reference) comes only from the registry.
4. Borrow by copying. Changing a canonical script: freeze its CLI, paths and output behaviour; update registry, catalogue line and tests in the same commit; run the registry validator.
5. New script: docstring, registry entry, catalogue line, tests, declared default mode (plan or execute).

## Outputs

- File by driving model; metadata JSON with only values really used (engine, base, LoRAs, strengths, prompt, seed).
- PNG embeds the submitted graph. Analyse the submitted graph, not defaults or metadata JSON.
- Worktree tools: set the outputs root to the main checkout. Merge worktree outputs with `rsync --ignore-existing`. Never `rm` in the main outputs tree.

## Cold archive

| Step | Command shape | Stop if |
|---|---|---|
| read usage | `status` | usage unreadable |
| preview | `plan`, or `push` without `--apply` | projected total > 80% of free tier |
| upload | `push --src <tree> --prefix <name> --apply` | credentials missing (exit 2, nothing sent) |

- Free tier is decimal: 10 GB = 10,000,000,000 bytes; ceiling 8,000,000,000.
- Transcode PNG/JPG to WebP q90 before upload; stage locally first.
- Run from the main checkout, never a worktree. Push after each new batch lands.
- Archive set: the curated gallery tree, one prefix per top-level tree.
- Never archive: caches, live working trees as a whole, staging folders.
- Never pass a delete flag. Never loosen the quota. Never make the bucket public unless the owner asks.

## Ledgers

| Ledger | Rule |
|---|---|
| Civitai Buzz (JSONL) | quote first; 30 Buzz per request, 150 per local calendar day; client-side check; fail closed; beyond caps, batch probes, video: ask |
| NovelAI Anlas (daily) | free tier by default; default cap 300/day; HTTP 402 = stop; local manifest is the history |
| remote jobs | entry at packaging (id, sha256); mark `cleaned` after cleanup; pending query lists uncleaned jobs |

Before any paid command:
1. Search the ledger for the batch id. Count files in the output dir.
2. Anything exists: run with resume. Default to resume anyway.
3. After: ledger rows = rendered files = spec entries. Extra rows = double run; report it.
4. A paid command pasted into chat may already have been run by the owner.

Remote jobs: failed or timed-out jobs are never auto-deleted; read the log, then clean. Delete audit suspects by exact path and note it in the ledger.

## Report

- Canonical names used and the index freshness at use time.
- Any remap done and the patch-count result.
- For downloads: file, size, sha256 match, index rebuilt yes/no.
- For archive: bytes transferred, bucket total after, percentage of the ceiling.
- For spend: quoted cost, ledger rows added, reconciliation result.
