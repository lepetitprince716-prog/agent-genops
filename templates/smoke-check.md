# Smoke check

Fill this in after rendering ONE image with the exact batch command, before releasing the batch.
Required for any batch of 3 or more images. Keep it in the order directory next to the run order.

- Order id:
- Date and time:
- Box:
- Batch command (exact, count set to 1):

## 1. Box state

- [ ] Probe returned ready (not HOLD, exit code not 3).
- [ ] Owner is not using the box, or three consecutive idle probes were seen.
- [ ] Engine tier matches what the batch verifies (base pass for probes, quality stack for finals).
- [ ] Shared process state cleared if this batch is a same-seed comparison.

## 2. Time

| Item | Value |
|---|---|
| Seconds per image (warm) | |
| Cold first-run seconds (not counted) | |
| Images in the batch | |
| Projected total minutes | |

- [ ] Projected total is 30 minutes or less, or it was reported and approved before starting.

## 3. Where things landed

| What | Path |
|---|---|
| Image | |
| Sidecar JSON | |
| Result JSON | |
| Post-processing copy (if any) | |
| Copy on the box (if any) | |

- [ ] The output directory was empty before the smoke.
- [ ] No other queue writes to this directory.
- [ ] The keep step moved the image and its sidecar as a group.

## 4. Filename rule

- Engine naming rule (what the filename is built from):
- [ ] Two images in this batch cannot get the same name (different seed, LoRA, or a unique suffix).
- [ ] If unsure, each render is moved to its own destination before the next one starts.

## 5. Stop plan

- Runner pid and process group id:
- Stop command: `kill -- -<PGID>`
- [ ] Process listing pattern ready to confirm nothing survives a stop.

## 6. Decision

- [ ] Release the batch.
- [ ] Fix and smoke again. Reason:
- [ ] Report and wait. Reason:

The smoke image itself is a test render: delete it with the batch's test material unless it is kept on purpose.
