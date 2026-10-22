English | [中文](../zh/08-inventory.md)

# Inventory

How agents know what exists and where: models and LoRAs on the render boxes, recipes, scripts,
outputs, the cold archive, cloud spend and remote jobs. The point is that an agent looks a fact up
in an index or a ledger instead of guessing it, and that every image can be traced back to what
made it.

> **TL;DR**
> - One machine-readable model index, built from Box A, records per entry whether Box B has the file and under which name. Agents pass its canonical names verbatim and regenerate it instead of editing it. LoRA search is semantic, with a lexical fallback.
> - Read block counts and dtypes from the file header before pairing a LoRA or control weight with a base. Mismatches fail silently.
> - Downloads land on the render box directly; the controller sends a command and polls.
> - Before writing a new script, read the script registry and the catalogue generated from it.
> - Cold archive goes to a private bucket behind a fail-closed quota at 80% of the free tier, with no delete flag. Every cloud render and every remote job leaves a ledger row.

## Rules

### Models and LoRAs

1. **Keep one machine-readable model index; regenerate it with `refresh`, never edit it by hand.**
   Why: a dated human judgement table exists next to it and says in its header that it is not a
   second index; machine facts always go back to the index. A second full LoRA index was rejected
   as speculative duplication.
2. **`refresh` is read-only and incremental; when the box is unreachable it exits non-zero and keeps the last valid index. `status` exits 3 when the index is stale.**
   Why: an unreachable machine must never be written down as an empty inventory. The snapshot is
   invalidated by an `(mtime_ns, size)` fingerprint, so a changed file is noticed without a full
   rescan. A stale or missing catalogue blocks generation.
3. **Pass the canonical name from the index, or from the live server's object info, verbatim; never type a filename from memory.**
   Why: each record carries `canonical_name`, the exact string the loader node accepts. On
   2026-07-16 a defect-probe campaign aborted halfway because the local index was a generation
   behind the box. For checkpoints, the live server's object info is the authority.
4. **Search LoRAs semantically; fall back to lexical matching over the same index when embeddings are unavailable.**
   Why: embeddings make "find a LoRA for this intent" work (a small sentence-transformers model,
   384 dimensions; incremental re-embedding by id plus doc hash takes 0.1 s instead of 27 s). On
   2026-08-23 the embedding model on the controller turned out to be half-downloaded and the hub was
   unreachable, so semantic search failed outright; a zero-dependency lexical match over the same
   index kept character lookups working. The index build itself never depends on embeddings.
   `refresh` must run with the interpreter that has the embedding stack, otherwise status reads
   `partial` (2026-09-22).
5. **Show an unknown content rating as unknown; never classify it silently.**
   Why: owner's decision. Self-trained LoRAs have base model "Unknown" and no hub metadata by design;
   a family-matching function falls back to path tokens. Do not "fix" that.
6. **Read the safetensors header (block count, parameter count, tensor dtype) before pairing a LoRA or control weight with a base, and record `blocks` on the model card.**
   Why: Anima comes in 28, 40 and 52 blocks. A 28-block LoRA on the 52-block model draws scribbles
   with no error; a 28-block control weight on a 40-block model misaligns with no error. On
   2026-09-17 none of the 166 Anima LoRAs on Box A were native 52-block. After remapping, check the
   patch count against tensors divided by 3 (280 of 280 in that test; 0 means the wrong key dialect).
   Vendor labels lie too: a hub version labelled FP8 was really INT8.
7. **Resolve defaults from registry roles, not from names hard-coded in scripts.**
   Why: in 2026-09 three independent definitions of the default base model existed. Model cards now
   carry a role (for example `quality_default`), the boxes they run on, per-box loader names and a
   status such as `no_gain`.
8. **Decide what to download from the repository file listing, and verify sha256 against the hub's LFS object id before installing.**
   Why: one model card described a whole family of mixed-precision files, none of which were in the
   repository. Community custom nodes are pinned by commit.

### Downloads

9. **Download models onto the render box directly; the controller only sends "download model X" and polls.**
   Why: the file never transits the controller or its link. In our setup an open-source LoRA manager
   for ComfyUI runs on Box A on demand, on its own port, isolated from the generation ComfyUI (no
   VRAM contention). Verified on 2026-07-12 with a 6.5 GB checkpoint, sha256 included. The hub key
   stays in the box's own settings and is never echoed. Stopping the manager also closes its tunnel.
10. **Pin the target root explicitly.**
    Why: the manager's default-path mode ignores the root passed in and files by base model under its
    own default root. Box A has two LoRA roots; find the right one by locating a known file.
11. **Rebuild the index (and embeddings) after every download.**
    Why: a new file is invisible to selection until the index knows it (verified end to end on
    2026-06-24: 508 to 509 entries, the new LoRA found by search). The aria2 backend signals
    completion when its control file disappears.
12. **When a box seems to lack a feature, check the version of the tool copy on that box first.**
    Why: on 2026-08-25 the recipe-capture extension on a box was two versions behind.

### Recipes

13. **Keep recipes in two layers: the store on the box as material, a local library as management with provenance, lineage and runs.**
    Why: everything saved on the box, by the browser extension or by hand, shows up in one store; the
    local library adds what the store lacks. Provenance is the raw hub view captured at import;
    lineage records parent recipes; runs lists the jobs that used it. The trace chain is image to job
    to brief to recipe to parent recipe to source.
14. **Converting a recipe into a render brief has no side effects; inspect the brief, then run it.**
    Why: conversion clamps steps, CFG and resolution to engine ranges, appends the recipe's negative
    instead of replacing it, keeps at most 4 extra LoRAs, and warns about missing LoRAs instead of
    guessing substitutes. Deleting from the store needs my explicit confirmation.

### Scripts

15. **Before writing anything new, read the script registry and the catalogue generated from it.**
    Why: owner's decision since 2026-06-25. The registry is a JSON file with status, zone, effects,
    targets, default mode, gates, timeout, output roots, cleanup, tests and authority for every
    script. CI rejects an unregistered script or an undeclared risk increase. Status (active, probe,
    legacy, test, reference) comes only from the registry, never from a filename or file age.
    Discovery order for agents: the router's `--list`, then the catalogue, then the companion docs.
16. **Borrow a script by copying it; change a canonical script only together with its registry entry, catalogue line and tests.**
    Why: an active script's CLI, paths and output behaviour are a contract other code relies on.

### Outputs

17. **File outputs by the driving model, with a metadata JSON holding only values really used.**
    Why: my rule from 2026-06-23. The folder says which agent drove the run; the metadata JSON records the
    real engine, base, LoRAs and strengths, prompt and seed, never guessed values. The PNG also
    embeds the full ComfyUI graph.
18. **When analysing a result, read the graph that was actually submitted, not source defaults or metadata JSON.**
    Why: on 2026-06-25 a txt2img run submitted denoise 0.5 by mistake; "baked VAE washes out" and
    "base over-exposes" were both artefacts of that bug and were retracted.
19. **Tools run from a worktree point their outputs root at the main checkout; worktree outputs merge back with `rsync --ignore-existing`.**
    Why: otherwise ledgers split and judged batches are invisible to the review server on the main
    checkout. Never `rm` inside the main outputs tree to "merge".
20. **The archive set is the curated gallery tree. Live working trees are not archived whole, and caches are never an archive source.**
    Why: live trees churn and hold test material; caches rebuild themselves. The staging folder used
    for transcoding is not archived either.

### Cold archive

21. **Enforce the storage quota on the upload side: fail closed at 80% of the free tier, and refuse when usage cannot be read.**
    Why: Cloudflare offers only budget alerts, no hard cut-off, and R2 is billed after the fact, so
    "I never topped up" protects nothing. The free tier is 10 GB in decimal units; the ceiling is
    8,000,000,000 bytes. The transfer size comes from a dry-run sync, so re-pushing an uploaded prefix
    costs nothing and is not refused. Decided 2026-08-13.
22. **No delete flag, a private bucket, and credentials that I create in the dashboard myself.**
    Why: standing constraints. The agent never handles plaintext secrets; the script reads the
    standard environment without logging it. Before credentials exist it stages and exits with code 2
    without touching the network. The prefix is validated against path traversal before any
    filesystem operation.
23. **Transcode to WebP q90 and stage before upload; push from the main checkout after each new batch lands, without waiting for a reminder.**
    Why: measured on 12 real outputs: PNG to WebP shrinks 7.1x at q95, 10.5x at q90, 13.6x at q85.
    All 4479 images at q90 came to about 1.0 GB, 10% of the free tier. One prefix per top-level tree.
    Renders of models judged `no_gain` were archived and their local PNGs deleted. (The memory
    note from 2026-08-13 records the upload as blocked on credentials; the current project rule
    treats pushes as routine. Credential state is not re-checked here.)

### Ledgers

24. **Every cloud render is a ledger row; quote first, compare against the budget on the client side, fail closed.**
    Why: Civitai has no server-side cap for an API key. Since 2026-09-30 a standing budget of
    30 Buzz per request and 150 Buzz per local calendar day replaced per-image confirmation; each render
    appends to a JSONL ledger. Anything over the caps, batch probes and video still need my approval.
25. **Before any paid command, search the ledger and count the files in the output directory; resume by default; afterwards check ledger rows = rendered files = spec entries.**
    Why: a double paid run on 2026-09-05 cost 257 Buzz (the full story is in
    [Providers](09-providers.md#real-cases)). A paid command pasted into chat may already have
    been run.
26. **NovelAI gets a local manifest and a daily Anlas ledger, because the API keeps no history.**
    Why: the default ledger cap is 300 Anlas per day and is not raised casually; the client is locked
    to the free tier unless a render is marked paid; HTTP 402 means stop, not retry. On 2026-09-30 the
    local price estimator was found to under-price paid renders (1536x1024 at 23 steps: 8 Anlas
    estimated, 39 charged). Separately, a ledger total of 638 Anlas "used" (2026-09-01) was mostly
    free images booked as paid.
27. **Every remote job has a ledger entry from packaging until it is marked cleaned.**
    Why: a job runner with a ledger prints a job id and sha256 at packaging; a pending query lists jobs
    packaged but not cleaned. Failed or timed-out jobs are never auto-deleted: read the log, then
    clean explicitly. A before/after filesystem audit flags new paths outside the job root; suspects
    are deleted by exact path with a ledger note. Remote job directories go to a trash folder first.

## Procedure: find a model for a job

1. Check index freshness (`status`). Exit 3: run `refresh`.
2. `lookup "<intent>" --kind lora --base <family>`; read `canonical_name`, triggers, strengths, rating.
3. Check the base's block count against the LoRA's. Mismatch: remap, then verify the patch count.
4. Paste `canonical_name` verbatim into the render brief.

## Procedure: archive a batch

1. `status` to read bucket usage. Unreadable: stop.
2. `plan` or `push` without `--apply` to see the transcode and transfer size.
3. Confirm the projected total stays under the ceiling, then `push --apply`.
4. Never pass a delete flag. Never archive caches or live trees.

## Checklist: before writing a new script

- [ ] Searched the registry and catalogue for an existing script with the same job.
- [ ] Read the companion doc of the closest match.
- [ ] Decided: reuse as is, borrow by copy, or add new.
- [ ] If new: registry entry, catalogue line, tests and default mode (plan or execute) in the same commit.

## Real cases

- **2026-07-16, stale index.** A defect campaign aborted halfway on names the box no longer had.
  Produced "canonical names from the index or live object info".
- **2026-08-23, embeddings broken on the controller.** Semantic search died; lexical matching over
  the same index carried on. Produced the lexical fallback.
- **2026-09-17, 52-block scribbles.** Unremapped 28-block LoRAs on the 52-block base drew noise
  with no error. Produced the header check and the patch-count identity.
- **2026-08-13, archive quota.** No hard cut-off at the provider. Produced the upload-side gate at 80%.

## Tried and dropped

- A second full LoRA index next to the catalogue: rejected as duplication.
- An older Civitai client that put the API token in argv, visible in the process list: replaced by
  one that passes it through a file descriptor.
- Semantic-only LoRA search: kept, but no longer the only path.

## See also

- [`06-render-discipline.md`](06-render-discipline.md): isolation, cleanup and delivery of renders.
- [`04-model-bringup.md`](04-model-bringup.md): adopting a model, model cards.
- [`09-providers.md`](09-providers.md): cloud budgets per provider.
- [`11-safety-and-privacy.md`](11-safety-and-privacy.md): secrets and what stays private.
