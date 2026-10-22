English | [中文](../zh/06-render-discipline.md)

# Render discipline

How an agent runs a batch of renders on a shared GPU box without wasting GPU time, overwriting its
own results, or leaving junk behind. Covers smoke tests, engine choice, output isolation, queue
control, yielding the box to its owner, VRAM release, cleanup and delivery.

> **TL;DR**
> - Before any batch of 3 or more, render one smoke image with the same command and check time per image, output path and filename collisions. Report batches over 30 minutes before starting them.
> - Pick the engine by what the step verifies: a base pass for probes, the quality stack only for finals.
> - Every render lands in its own place. Stop queues by process group and prove the tree is gone.
> - Probe the box before dispatch and yield to the owner. VRAM is leased and released by an idle reaper, not freed after every image.
> - Test renders are deleted on both sides by default. Windows boxes get a same-disk dated trash folder, never the Recycle Bin. Results go to a gallery page, not into the conversation.

GPU time is the hard constraint on the schedule. A wasted batch pushes the whole line back. Most
rules below come from one bad probe round on 2026-09-16; see "Real cases".

## Rules

### Before the batch

1. **Render one smoke image before any batch of 3 or more, using the exact batch command.**
   Why: on 2026-09-16 a style-probe round skipped the smoke and made three mistakes at once (wrong
   engine, leaf-only queue stop, same-seed overwrite). Box A lost about 40 minutes, the re-run took
   another 15, and the schedule slipped about an hour. The smoke checks three things: time per image,
   where the image and its result JSON land (and whether post-processing writes a second copy), and
   whether two images in the batch can get the same filename.
2. **Multiply the smoke time by the count and write the total into the order; report any batch over 30 minutes before starting it.**
   Why: the 2026-09-16 round would have shown 3.5 minutes per image times dozens of images before
   it started. The 30-minute line came from that incident.
3. **Choose the engine by what the step has to verify.**
   Why: style, composition and pose probes need a single base pass (tens of seconds per image; the
   Anima fast line runs about 2.1 to 2.5 s warm on Box A). The quality stack (upscale plus detailers)
   costs minutes per image: about 100 s median for the SDXL quality line on Box A, 84 to 108 s for
   Anima at maximum on Box B. On 2026-09-16 the quality stack was used to probe style at 3.5 minutes
   per image. The current upscale and detailer recipe state lives in the project state file; do not
   assume it is current.
4. **Clear shared process state before any same-seed comparison on a shared box.**
   Why: on 2026-10-01 an IP-Adapter node patched model blocks in place and survived the normal VRAM
   release; same-seed outputs differed by a mean pixel difference of 16.55 until a full memory free.
   Two wrong verdicts came from this in one day. A run of black images after a long multi-agent
   session the same day was fixed only by restarting the box.
5. **Test renders on Box B need no per-batch approval; Box A, the network and deleting non-test data still do.**
   Why: I handed test rendering to the agents on 2026-09-30 so Box B gets used to its limit. The
   batch cap for that standing permission is 15 images, smoke first, cleanup on both sides.

### Isolation

6. **Move every render to its own destination as soon as it lands, before the next render starts.**
   Why: engines name files by their own rules. Reuse the isolation helpers the repo already has (a
   `--keep-into DIR` flag that moves the PNG and its metadata JSON as a group with a `__vN` no-clobber
   suffix); the command shape is `render && keep`. Do not write a new one.
7. **Assume filenames collide unless the engine proves otherwise.**
   Why: one generator names output by LoRA name plus seed. On 2026-09-16 five prompt-only arms shared
   seeds and overwrote each other: 30 of 48 images were lost. Another engine already appended a
   unique suffix; the probe did not use it.
8. **Each run writes into a new, empty output directory; a non-empty directory is refused.**
   Why: rounds must never mix. App jobs also write a per-run manifest of produced files and never scan
   the whole output tree, which keeps parallel runs from claiming each other's images.
9. **Two queues never point at the same result directory.**
   Why: part of the 2026-09-16 batch-render rule.

### Queues and processes

10. **Stop a queue by its process group (`kill -- -<PGID>`, or a recursive child kill before the runner), then list processes to prove the whole tree is gone.**
    Why: on 2026-09-16 the runner and the engine were killed, but the intermediate shell running the
    command file kept going and rendered five more images from a deleted command file.
11. **Stop the queue before changing the plan; restart only after the new plan is written.**
    Why: same incident. A re-plan under a live queue means two plans run at once.
12. **On a Windows box, start long work through WMI process creation and delete one-shot scheduled task definitions right after launch.**
    Why: processes started inside an SSH session die with it, and Start-Process fails silently with
    no window station. On 2026-07-20 nine one-shot scheduled tasks re-fired together, exhausted VRAM
    and froze a training run at step 3. At wrap-up a query by task-name prefix must come back empty.
13. **When a queued prompt times out, delete it by its exact id and confirm it is gone; leave a running prompt alone.**
    Why: ComfyUI only offers a box-wide interrupt for the running prompt, which would kill someone
    else's job. After such a timeout the defect campaign marks queue ownership unsafe and aborts.

### The box belongs to its owner

14. **Probe before dispatch; a HOLD (exit code 3 from the probe) means do not dispatch.**
    Why: Box A is my gaming PC. In our setup an intent router called `gen.py` takes
    `--box auto --probe`; every `--run` probes again. `--box auto` scans Box A first and routes to
    Box B when Box A is busy (low free VRAM, a non-empty queue, unreachable). That replaced an
    unconditional "Box B first" rule from 2026-07-18.
15. **When I am running my own work on Box A, wait for three consecutive idle probes before starting a queue.**
    Why: owner's decision. A single idle reading between two of my jobs is not a free box.
16. **No model-based 4x upscale while I may be gaming; use a higher native resolution in one pass instead.**
    Why: the intermediate image of an ESRGAN-class 4x upscale runs the shared 16 GB card out of
    memory. Desktop apps squeezing VRAM also caused silent driver crashes on Box A; the reserve was
    raised to 2.5 GB.
17. **Judge a box alive by its queue endpoint, not by ping.**
    Why: ICMP is firewalled on both boxes by design, and SSH stays up when ComfyUI is down. The
    system-stats endpoint once returned 500 while queue, prompt and object-info answered 200.

### VRAM

18. **Lease VRAM after a run and let an idle reaper free it; do not free after every image.**
    Why: freeing after every render reloaded the checkpoint and LoRAs on each image of a burst, and
    each free cost a 1.9 s remote round trip. Since 2026-09-17 a finished run stamps a lease; a
    detached reaper frees only after 300 s idle with a readable, empty queue (maximum wait 3600 s), one
    reaper per box under a lock, and reads the box back afterwards. A flag frees immediately when
    needed. The old rule "POST /free after every run" (standing op since 2026-06-27) is retired; I
    confirmed keeping models resident on 2026-09-22.
19. **Unload fully only when switching models or when I am done with the box, through one command that names the box and the mode.**
    Why: a full memory free wedged Box A on ComfyUI 0.33.1 on 2026-09-01, so the default release
    became "unload models only". Re-measured on Box B on 2026-10-19: that mode leaves 1.43 GB
    resident on 0.42.1 (2.1 to 3.3 GB on 0.27.1); the full mode returns everything within 1 s and
    did not hang on either version. Whether the default changes is still my decision, pending a
    full-mode test on Box A under 0.42.1.
20. **Account for resident models in any idle threshold.**
    Why: with models resident, idle free VRAM on the Qwen sidecar sat near 45%, so a 40% threshold
    misread a free box; that sidecar's fallback threshold was lowered to 35%.

### Cleanup

21. **Test renders are deleted by default; keeping one needs my explicit word.**
    Why: both disks were filling up; one black-image investigation alone left 20+ throwaway images on
    the controller and on Box A. Tightened on 2026-10-06: clear each round after its verdict, not only
    at task end; comparison sheets count as test images; keep the lesson in the order's findings, not
    the images. A single image I name as a reference may stay, and the report says which and where.
22. **Clean both sides, and list what will go and its size before removing anything.**
    Why: renders often exist twice, once on the controller and once in the box's ComfyUI folders.
    On the box that means `output`, `input` (benchmark inputs) and `temp` (preview dumps).
23. **On Windows boxes never use the Recycle Bin; move files to a same-disk dated trash folder with a restore map.**
    Why: on 2026-10-13 the send-to-Recycle-Bin call over a non-interactive SSH session turned out to
    be a permanent delete. The folder keeps the original relative path; a restore map file lists
    every move; I delete the trash folder myself. The controller side uses the system trash.
24. **If remote cleanup cannot happen now, write the leftovers into a CLEANUP file in the order directory.**
    Why: owner's decision. The file is cleared at wrap-up together with the order.
25. **Clean output subfolders only; never datasets, training checkpoints, converted LoRAs or models.**
    Why: standing boundary. Training validation keeps only the few best images (best-epoch A/B pairs)
    in the repo's analysis folder (2026-07-20).
26. **Select remote files by filename range or by age measured on the box, not by controller clock time.**
    Why: Box A's clock ran 12 hours ahead of the controller (2026-10-06).

### Delivery

27. **Deliver images and videos as links to a gallery page, never by loading them into the conversation.**
    Why: media in context is expensive and disappears at compaction, and a video cannot be scrubbed
    in a transcript. A full 2048x3072 PNG costs about 60 times the context of a shrunk WebP. Earlier
    attempts failed: a send-file tool showed a file chip, and base64 in a widget exceeded a 512 KB
    cap (2026-06-24/25). Reading an image to inspect it myself stays fine.
28. **One review round is one registered batch; a batch is immutable once registered.**
    Why: on 2026-09-05 one evening of per-image verdicts judged the same scene 58 times. A changed file
    stops being served; register a new batch instead. Default to a view-only grid; use the
    one-at-a-time verdict mode only when the next step depends on picks.
29. **The gallery server runs only from the main checkout, and batches are registered from the main checkout.**
    Why: on 2026-08-08 the server was restarted from a worktree; its root pointed at a sparse tree
    and the item count fell from hundreds to single digits. The server now refuses worktree paths.

## Procedure: a batch on a shared box

1. Write the order: intent, box, count, seeds, model, LoRAs, output dir, acceptance, cleanup
   (template: [`templates/run-order.json`](../../templates/run-order.json)).
2. Probe the box. HOLD: wait or switch boxes, and say which.
3. Run one smoke with the batch command. Fill in [`templates/smoke-check.md`](../../templates/smoke-check.md).
4. Compute total time. Over 30 minutes: report and wait for a go.
5. Launch the queue as `render && keep` per item, each into a fresh directory.
6. To stop: kill the process group, list processes, confirm nothing is left.
7. Let the lease expire, or free now if I need the card.
8. Register one gallery batch, hand over the link, read verdicts back.
9. Clean both sides per rules 21 to 26, then record the lesson in the order's findings.

## Real cases

- **2026-09-16, style-probe round.** Quality stack used for a style probe (3.5 min per image);
  queue stopped at the leaves only, five extra images rendered; same-seed overwrite lost 30 of 48.
  Cost: about 40 min of Box A, 15 min re-run, about 1 h schedule slip. I rated it serious. Produced
  rules 1 to 11.
- **2026-09-01, full memory free.** Wedged Box A on ComfyUI 0.33.1. Produced the unload-only default
  and the read-back after release.
- **2026-09-17 and 2026-09-22, release per render.** Reloads on every image of a burst plus 1.9 s
  per free. Produced leases and the idle reaper.
- **2026-10-13, Recycle Bin.** A cleanup call that was meant to be recoverable deleted permanently.
  Produced the same-disk trash folder with a restore map.
- **2026-08-08, gallery from a worktree.** Wrong root, totals collapsed, nothing lost. Produced the
  main-checkout guard.
- **2026-07-20, re-fired tasks.** Nine scheduled tasks fired at once and froze training at step 3.
  Produced "delete the definition after launch".

## Tried and dropped

- Unconditional routing to Box B first (2026-07-18): replaced by probing Box A first.
- POST /free after every run (2026-06-27 to 2026-09-22): replaced by leases and the reaper, built on 2026-09-17 and made the rule on 2026-09-22.
- Full free as the default release: dropped after the 2026-09-01 wedge; re-test pending on 0.42.1.
- Recycle Bin on remote boxes: permanent delete in practice.
- Media delivery through a send-file tool or base64 widget: chip only, or over the size cap.

## See also

- [`04-model-bringup.md`](04-model-bringup.md): smoke and eval when adopting a model.
- [`07-performance.md`](07-performance.md): timing method, warm runs, variance.
- [`08-inventory.md`](08-inventory.md): where outputs, archives and ledgers live.
- [`03-dispatch.md`](03-dispatch.md): how a render runner is briefed and accepted.
