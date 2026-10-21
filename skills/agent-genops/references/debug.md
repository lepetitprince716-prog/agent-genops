# Debug

Purpose: triage failed, hung or wrong renders on ComfyUI boxes, decide the first check, and know when to stop.
Read when: a graph is rejected, a job hangs, output looks wrong, VRAM misbehaves, or a remote box seems down.

## First moves

1. Probe the queue endpoint. Do not ping (ICMP is blocked). Do not use system-stats as health (it has returned 500 while queue, prompt and object-info were 200).
2. Read the server log tail and the graph that was actually submitted (embedded in the output PNG), not script defaults.
3. Note box, ComfyUI version, what changed since the last good run.
4. Use the table. Run the first check before forming a theory.

## Symptom table

| Symptom | First check | Action |
|---|---|---|
| "value not in list" | Name in live `object_info`; byte count on disk | Use the live name; finish the download |
| New node missing | Process start time | Kill the listener process, start, verify |
| Pixels changed after upgrade | Same-seed A/B on sibling instance | Composition same = drift; else regression |
| Old runtime fails after rollback | DB revision | Restore the DB backup |
| OOM only at VAE decode, quantized model | Load mode in log | Unload models + empty cache before decode |
| Silent server death, driver reset in event log | `--reserve-vram` value | Set 2.5 |
| VRAM stuck after `/free`, "Cannot set version_counter for inference tensor" | Was an INT8 ConvRot model partially loaded with a LoRA | Service stop and start |
| VRAM held, no job; WinError 1455 | Processes by command line | Kill orphans by listening port or command line |
| Free VRAM looks fine, OOM anyway | Vendor tool total minus server's own | Account for foreground apps |
| Success with empty outputs, or poll to timeout on rerun | History for the same prompt | Reuse history output or change seed; never add client id |
| Rerun returns another image's pixels | Local cached-path reuse | Fetch by prompt id from box history |
| Queue wedged | Log: node waiting on network | Cancel; pre-place the model |
| Training frozen early, VRAM exhausted | Scheduled tasks by prefix | Delete re-fired one-shot definitions |
| Same seed differs on shared box | Which nodes ran before | `/free` with `free_memory`; then compare |
| Black images after long shared use | None reliable | Restart the server |
| Scribbles / control ignored | Base `blocks` vs weight blocks; patch count | Remap or refuse |
| LoRA has no effect | Strength (0 short-circuits); patch count | 0.001 control arm; fix key dialect |
| Wrong output size (Qwen-Image) | Canvas multiple of 16 | Fix latent size |
| Box "dead" | Queue endpoint; SSH | ComfyUI down != box down |
| PCIe Gen3 / small BAR | Uptime since sleep or driver update | Reboot, re-measure |
| SSH exit 255 | Transport only | Other non-zero = ran remotely; do not switch route |

Version note: cache/history and object-patch findings are from 0.27.1 / 0.33.1; not re-checked on 0.42.1.

## Silent-failure rules

- Before comparing two renders on a shared server: `POST /free` with `unload_models` and `free_memory`. Model unload alone does not clear node patches.
- Custom nodes that replace a module forward: injections only. Verify with a plain no-LoRA sampler right after.
- Never conclude "compatible" from a LoRA run without a 0.001 control arm and a nonzero patch count.
- Never report a finding without re-reading the submitted graph.

## Shared-box etiquette while debugging

- Box A is the owner's gaming PC. Probe VRAM and an empty queue before any test submission.
- Restarting a shared main server needs an empty queue. If the owner said "don't run", stop.
- Test images are deleted after the verdict. Remote cleanup goes to a quarantine folder (see `windows-gpu-box.md`).

## Two failures rule

After two failures of the same task:
1. Stop. No third attempt of the same shape.
2. Write both attempts and exact errors.
3. Re-inventory: tools and MCP, project scripts and docs, runtime versions per venv per box, what changed.
4. Re-test the assumption under the plan (examples that were wrong: "no triton" machine-wide; "box lacks feature" when the installed copy was outdated; "network forbids it" without one minimal request).
5. Change approach, or report the blocker.

## Blocked handoff

When a gate, missing permission, root-owned file or GUI-only step blocks you, hand over ONE command:
- Shortest copy-pasteable form.
- Idempotent.
- Backs up what it overwrites.
- Aborts if its anchor is missing.
- Verified on a copy.
- Lists unverified parts.

Never route around the gate. Never describe steps in prose instead.

## Network vs not-network

- Hook deny, wrapper failure, ACL/TLS block, remote unreachable after starting the service: network issue; follow the project's network handoff.
- 403 from the egress proxy for an alias instead of a resolved URL: calling mistake.
- Gate rejection of a command shape, or a hook that rewrote output shape: tool defect. Fix shape once, then hand over.
- ComfyUI returns 503: start ComfyUI first (pre-authorised), probe about a minute later.

## Report

- Symptom, box, ComfyUI version, time.
- First check run and its literal result.
- Cause (verified) or hypothesis (marked unverified).
- Fix applied, and the check that proved it.
- Anything restarted, killed or moved, with identities checked.
- Blocker and the handed-over command, if any.
