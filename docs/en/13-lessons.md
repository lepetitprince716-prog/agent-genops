English | [中文](../zh/13-lessons.md)

# Lessons

Which mistakes have already cost GPU hours, money or a day of work, and what rule each one
left behind? This page lists dated incidents from my setup, grouped by area, one line each.
Every other page cites its reasons from here.

> **TL;DR**
> - Each line reads: date — what happened (cost) → rule.
> - Only incidents with a recorded date or cost are kept. Private names are replaced by roles.
> - Most costs come from three habits: batching before a smoke test, trusting a report instead of the artifact, and routing around a gate.
> - New incidents become rules through [templates/incident-rule.md](../../templates/incident-rule.md).

## Rules for keeping this page

1. **An incident enters the list only with a date or a measured cost.**
   Why: undated stories cannot be checked and drift with each retelling.
2. **Each incident names the rule it produced and where that rule now lives.**
   Why: a lesson that lives only in chat is lost when the transcript is cleaned.
3. **A rule's reason stays in the file that owns the rule; the changelog keeps one line.**
   Why: policy files are distilled by dropping reasons and keeping constraints (owner's decision).
4. **Two failures of the same task send the agent back to inventory, not to a third attempt.**
   Why: the usual cause is a missing tool or an unread doc, not a coding error (policy entry 2026-08-27).

Machine names: Controller (the laptop that runs agents), Box A (main render box, also a
gaming PC), Box B (worker box), UMA Box (128 GB unified-memory Linux ARM64 node). See [02-environment.md](02-environment.md).

## Real cases

### Rendering and GPU time

- 2026-06-25 — a txt2img graph was submitted with denoise 0.5 and produced false findings about VAE wash-out (one investigation on a wrong premise) → read the graph that was actually submitted before drawing conclusions.
- 2026-07-18 — one hard-to-render garment concept was tried 72 times → stop fighting a model's prior; drop the concept or change tool.
- 2026-07-20 — scheduled tasks re-fired, nine at once; VRAM ran out and a training run froze at step 3 → delete the task definition right after launch is confirmed; query tasks by prefix at wrap-up.
- 2026-09-01 — a full memory free through ComfyUI's `/free` wedged Box A while tearing down its RAM cache → free unloads models only, from one function, and the box is read back after release.
- 2026-09-03 — gradient checkpointing was turned off because "only 40% VRAM is used"; training hit 15,899 of 16,380 MiB and slowed 9x → peak memory with checkpointing on does not predict peak with it off.
- 2026-09-16 — a style probe ran on the quality stack (3.5 min per image), a queue stop killed only leaf processes so a subshell rendered 5 more, and same-seed overwrites destroyed 30 of 48 images (about 40 min GPU, 15 min re-run, about 1 h schedule slip) → smoke one image first, choose the engine by what the step verifies, isolate each render on landing, stop the whole process group.
- 2026-09-16 — throwaway test renders kept filling both disks (one black-image debug alone left 20+ images on two machines) → clean up test renders when a task ends; tightened on 2026-10-06 to delete by default and keep the lesson, not the images.
- 2026-09-17 — unremapped 28-block LoRAs on a 52-block Anima base produced scribbles with no error; none of 166 Anima LoRAs on the box were native 52-block → remap block indices before attaching.
- 2026-09-18 — a LoRA on a partially loaded INT8 ConvRot checkpoint crashed 6 of 6 runs on ComfyUI 0.33.1 and leaked about 11 GB VRAM that `/free` could not recover → only a service restart freed it on 0.33.1; ComfyUI 0.46.0 fixed INT8 ConvRot LoRA attachment (`+0.50 s` GPU requant, zero leak).
- 2026-09-22 — "release VRAM after every render" reloaded checkpoint and LoRAs on every image of a burst; each free cost a 1.9 s round trip → leases plus an idle reaper replace per-render release.
- 2026-09-30 — reusing a locally cached output path returned another image's pixels with the new metadata → look up history by prompt; drop local cached-path reuse.
- 2026-09-30 — an identical rerun on ComfyUI 0.27.1 polled until the 1,800 s timeout and looked like a hang → look up the same prompt in history and fetch the existing file; fail fast on 404.
- 2026-10-01 — img2img returned black images after a long multi-agent session; a restart fixed it and the cause was not captured → on black images, restart the box before debugging precision.
- 2026-11-05 — more pictures were wanted for a style set whose first version was already in training → a set handed to training is frozen and its build refuses to run; additions go under a new version name.
- 2026-11-25 — bare `--cache-ram` on ComfyUI 0.46.0 defaulted inactive headroom to 100% of RAM (`47.2 GiB` on Box A) and evicted resident models on every workflow switch (`14.13 s` reload vs `0.15 to 0.61 s`) → pass explicit bounds `--cache-ram 4.0 8.0` alongside `--reserve-vram 2.5`.
- 2026-11-25 — a custom KV-reuse wrapper changed per-step tensor shapes inside `comfy-aimdo`'s malloc graph and crashed on step 2 (`aimdo memory compile error`) → call `cleanup_malloc_graph()` on mode or shape transitions.
- 2026-11-25 — ComfyUI 0.46.0's built-in `LoraLoaderBypassModelOnly` silently dropped 126 tuple-keyed fused `qkv` slices on MOSS-Image INT8 and left FP32 adapters uncast → verify applied slice counts and unpack offset tuples in BF16, or use stock `LoraLoaderModelOnly` (`+0.50 s` GPU requant).
- 2026-11-25 — installing CPU `onnxruntime` alongside `onnxruntime-gpu` hid `CUDAExecutionProvider`, and a `512 MiB` arena cap OOMed at `Conv_83` on `isnet-anime.onnx` (`6.27 s` cold cuDNN init vs `0.314 s` CPU) → isolate `onnxruntime-gpu`, set a `1,536 MiB` arena cap with CPU fallback, and keep one-shot CLI calls on CPU.
- 2026-11-25 — `MAP_PRIVATE` checkpoint mmaps on UMA Box added `+4.0 GiB RssAnon` per `4 GiB` CUDA copy while writable `MAP_SHARED` risked silent on-disk `.safetensors` corruption → map checkpoints with `MAP_SHARED | PROT_READ` (`r--s`) and guard tensors against in-place writes.

### Remote Windows boxes

- 2026-06-21 — a crashed training run on Box B left a zombie Python holding 16 GB+ of memory → between retries, list Python processes, confirm the command line is the trainer (not ComfyUI), kill those PIDs.
- 2026-07-02 — a ComfyUI "restart" did not restart anything → kill the process that owns the listening port, then start.
- 2026-07-16 — a failed window discovery over SSH was read as "the desktop is unusable"; SSH sessions cannot see the console desktop → drive desktop apps through a devtools protocol, not screenshots over SSH.
- 2026-08-25 — 13 orphan multiprocessing Pythons holding 33 GB blocked a verified setup with a misleading storage error → kill by listening port or command line, and check listener identity, not just "port alive".
- 2026-09-01 — a PCIe link reading Gen3 with a 256 MiB BAR was diagnosed as a BIOS fault; one reboot restored Gen5 x16 → reboot and re-measure before blaming hardware.
- 2026-10-01 — remote PowerShell payloads of 60 KB and more stalled intermittently on one box (1–46 KB never did) → copy large files first, then send a small runner script.
- 2026-10-13 — a CIM module load hung on one box, left orphans and finally blocked the SSH banner (14 timeouts in three weeks) → only plain cmd commands or one process-create call on that box; do not lengthen timeouts.
- 2026-10-13 — a second SSH hop lost its quotes and broke a docker command template → quote once per hop; past three layers, ship a script file.
- 2026-10-13 — tasks created through SSH only ran while someone was logged on → import task XML as UTF-16 with BOM and S4U logon.
- 2026-10-13 — "send to recycle bin" over a non-interactive SSH session deleted permanently → move files to a same-disk dated quarantine folder with a restore map.
- By 2026-10-19 — the agent's Bash tool rewrites `>nul` into `>/dev/null`, a path that does not exist on Windows → write cmd files with the file tool and CRLF; use `>NUL:` in one-liners.
- 2026-10-19 — Box B's proxy pointed at a local port with no listener, so dependency installs failed → tell the owner; never edit proxy variables in a job environment.
- 2026-11-25 — Box A's service Scheduled Task launched `powershell.exe` without `-WindowStyle Hidden`, exposing the server to `0xC000013A` console-close exits (`29 s` cold reload) → prepend `-WindowStyle Hidden` in place with `Set-ScheduledTask` instead of unregistering.

### Agents and dispatch

- By 2026-06-20 — a headless coding agent asked for an image wrote code that drew polygons → require the native image tool and an explicit escape token when it is missing.
- 2026-07 — two same-family reviewers passed a tests-only PR; a second tool found 6 loose assertions (and 3 more on the next PR) → every test PR gets a mutation-minded review from a different tool.
- 2026-07 — an isolation check only printed the resolved root, while a copied config made a restricted subtree write into the main output tree; two same-family agents missed it → isolation tests assert the path resolves inside its own subtree; use a second tool family for review.
- 2026-07-05 — orphaned worker processes of an agent CLI ran at about 700% CPU for days and overheated the Controller → orphans with parent PID 1 and days-long spin are safe to kill.
- 2026-08-04 — starting a worker CLI from the sandboxed session shell failed with a nested-sandbox exit 71 → start external workers only through the multiplexer service.
- 2026-08-14 — one advisor call by a worker took 7.7 min and 102k tokens to find redundancy in two text sections → workers never call the advisor and never delegate further.
- 2026-09-20 — corrections queued to a running worker never arrived; about 4 GB downloaded for nothing → after changing instructions, check the worker's real file activity.
- 2026-10-08 — three of four Haiku research lanes went off task → research lanes go to Sonnet.
- 2026-10-15 — a literature re-check Workflow ran every agent on the strongest model and burned quota → every Workflow agent call names a cheaper model.
- 2026-10-19 — a Haiku subagent copied 1,643 of about 20,000 base64 characters, three times in a row → the root pushes data in chunks with hash checks.
- 2026-11-25 — bounded cross-model Gate-1 spec review falsified three speculative CUDA items (step-split `nvfp4`-to-`INT8` swap, `CUDA Graphs` on dynamic-VRAM DiTs, sub-4MP two-node sequence parallelism) pre-code → run bounded `Subtract-Before-Add` and statechart falsification before writing kernel or multi-file code.

### Sessions and context

- 2026-07-04 — the sandbox's git view drifted (one commit under two hashes, deletes written through, commits not) → step 0 runs status, worktree list and HEAD twice and compares; on mismatch stop and write a handoff.
- 2026-08-25 — a relapse into long replies was traced to instruction dilution in long sessions, not a model change → a re-injection hook that fires only after 12 assistant turns.
- 2026-09-16 — a 55-file dirty main checkout was taken for orphaned work, WIP-committed and switched; it belonged to a live session → list live sessions and transcript times before touching a shared checkout.
- 2026-09-17 — a cloud-written handoff misdiagnosed the box link and proposed overwriting the launch definition that auto-picks the route → read the real service definition before acting on a handoff's diagnosis.
- 2026-10-13 — a successor session could not find its files because the handoff omitted working directory and branch → both fields are mandatory in handoffs and tracker notes.
- 2026-10-14 — the successor-session trigger never fired: 70% was computed on a 1M window while compaction ran at 500k (it hit at about 467k) → thresholds use the compaction window in force.
- 2026-10-14 — a task left "in progress, waiting for the owner" produced an empty to-do list at wrap-up → a task waiting on a person is set to blocked.

### Network and gates

- 2026-08-06 — tightening to managed hooks silently disabled four user hooks (two rescued 2026-09-15, two still off) → hooks live only in the managed directory.
- 2026-08-20 — heredoc text that merely contained a wrapper's name matched the gate → write files with the file tool; never mention wrapper names in other commands.
- 2026-08-28 — a box alias passed instead of a resolved URL produced a fake hostname and a 403; a network specialist was dispatched for nothing → the HTTP helper takes the resolved full URL.
- 2026-09-10 — a gate-rejected GitHub sub-command was tried 244 times in 63 sessions over 30 days, copied from doc examples → the sub-command is always rejected and the examples were rewritten.
- 2026-09-16 — an agent declared a public API uncallable after seeing the guard and handed a working command to the owner → send one minimal request and read the real error first.
- 2026-09-22 — the LAN link silently fell back to the slow remote path after the laptop got a lease in another subnet → diagnose from the route cache first, not from proxy rules.
- 2026-09-29 — a 1.5 MB upload through the managed proxy hung until timeout → clear `Expect: 100-continue`.
- 2026-10 — about 250 gate rejections in three weeks came from chained, piped or prefixed wrapper calls → one wrapper command per shell call, nothing before or after.
- 2026-10-19 — an SSH session environment holding API keys nearly went into a job queue's state file → job environments come from a variable allow-list.
- 2026-10-19 — a post-tool hook rewrote remote output and the script looked unrun → treat it as a hook output defect; change shape once, then hand the command to the owner.

### Git and CI

- 2026-07 — three review comments left unresolved before merge cost an extra PR → every review comment is dispositioned before merge.
- 2026-08-08 — the production gallery server started from a worktree; its index fell from hundreds of images to single digits → production servers start only from the main checkout, guarded in the script.
- 2026-08-13 — a "pre-existing" gap changed severity under new code and broke 7 of 22 direction cards → judge defects by behaviour at the current tip.
- 2026-08-13 — 8 red CI runs fell into four classes (guard killed an install, unregistered script, state-file size cap, TLS reset) → classify the first error before rerunning; never raise a cap to get green.
- 2026-08-16 — the hosted CI monthly quota ran out → cost-aware lanes: a short job on PRs, heavy lanes weekly and on manual dispatch, a local runner that mirrors the hosted selection.
- 2026-08-16 — one worktree held a whole uncommitted feature (16 tracked files, 10 tests) that no branch had, and another held 255 MB of outputs with no copy in the main checkout → scan and rsync untracked work back before deleting any worktree.
- 2026-08-23 — a reviewer's recursive grep at repo root ran 11+ min and ate its timeout → `git grep` or scoped searches only.
- 2026-09-16 — a review verdict note committed inside the reviewed diff blocked the next review as injection → verdicts live only in PR comments.
- 2026-09-16 — a third review round on one PR wasted time → at most two review rounds; later suggestions go to follow-up PRs.
- 2026-10-06 — a 28-commit branch never had a PR, was believed merged, and an endpoint returned 404 in production → check `git log origin/main` for the file before assuming a merge.
- 2026-10-14 — a large push reported success after a sideband disconnect → verify every push with fetch plus `rev-parse`.

### Web app on the Controller

- 2026-10-29 — new rows in the web studio app's live feed stayed at opacity 0 until a reload on 2 of 3 own submissions; suspected cause, not reproduced: a JS animation library's `initial`/`animate` entrance lost its flag mid-run → run mount-only entrances as a CSS animation keyed on a data attribute, moved with `translate` rather than `transform`.
- 2026-10-29 — a server restart stalled at uvicorn's `Waiting for connections to close` because an open browser tab held an event stream, and the wait has no limit by default → find the client with `lsof`, navigate the tab away or force the exit with a follow-up SIGINT, and let the service manager start the new process.

### Cloud spend

- 2026-08-25 — Civitai's public image endpoint stopped returning generation metadata (10 of 10 empty) → do not assume REST returns metadata; use an import route that parses the page.
- 2026-08-25 — NovelAI's edge returned 403/1010 for the default Python user agent → always send a custom User-Agent.
- 2026-09-05 — two paid probe commands were pasted in a reply and also approved from an inbox; 19 images rendered twice (257 Buzz) → check the ledger and output folder first, default to resume, reconcile counts after.
- 2026-09-30 — the NovelAI cost estimator ran low and the ledger counted free images as paid → use the site's own formula and pixel rule.
- 2026-10-19 — a Midjourney prompt over 1,031 characters was silently rewritten and lost words → keep the prompt body under about 1,000 characters.

### Evaluation and review

- 2026-07-02 — a hand-paraphrased direction intent dropped a slot and the reviewer ranked the wrong winner → build the review intent mechanically from the card.
- 2026-07-03 — structurally melted images passed the QC gate with zero flags → never skip visual pre-screen and final review because a gate passed.
- 2026-07-16 — an external reviewer and the mechanical layer both failed digit-count calibration → their findings stay auxiliary and never enter scores.
- 2026-07-17 — reading thumbnails gave a false "detail difference" conclusion → diff pixels before reading contact sheets.
- 2026-08-04 — stacking two style LoRAs collapsed faces and the automatic gates missed it 10 of 10 times → single-variable ablation, then remove the culprit and add a regression test.
- 2026-08-27 — a crop cut off a toe row and reported a fake success; a human caught it → four-edge enclosure checks plus human final review.
- 2026-08-27 and 2026-09-17 — artist candidates were filtered by a 500-post threshold that excluded every wanted illustrator (164 to 490 posts), twice → judge by commercial record, not post counts.
- 2026-09-05 — one evening of per-image verdicts judged the same scene 58 times → the agent judges objective defects; only taste goes to a person, in small batches.
- 2026-09-15 — a 24-cell bare-model matrix wasted human attention → one image per new model, then ask about the LoRA stack.
- 2026-09-30 — a recorded warm timing of 3.8 s re-measured at 2.1 s → re-measure on the production server, drop cold runs, delete stale numbers.
- 2026-10-01 — artifacts blamed on a new base model came from two strong style LoRAs stacking (found by same-seed dose and leave-one-out tests) → isolate the style stack before judging a model.
- 2026-11-25 — the second control bracket `ctl_2` in an `A-B-A` benchmark repeated `ctl_1`'s graph and seed and returned in `0.07 s` from ComfyUI's sampler cache while `ctl_1` paid `1.4 s` uncached text encoding → fail closed on sampler or asymmetric encoder cache hits (`--strict-cache`) and offset `A_2` seeds.

## Tried and dropped

- **Release VRAM after every render.** Dropped for leases and an idle reaper (2026-09-22).
- **Longer timeouts on a hanging remote box.** Dropped for a narrower command shape (2026-10-13).
- **Same-family review only.** Dropped after two misses in July 2026; a second tool family reviews.
- **Polling scripts that wait for CI.** Dropped: check once, wait, check once (owner's decision).

## See also

- [06-render-discipline.md](06-render-discipline.md)
- [05-debugging.md](05-debugging.md)
- [03-dispatch.md](03-dispatch.md)
- [11-safety-and-privacy.md](11-safety-and-privacy.md)
- [12-continuity.md](12-continuity.md)
- [../../templates/incident-rule.md](../../templates/incident-rule.md)
