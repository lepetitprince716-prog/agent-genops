English | [中文](../zh/05-debugging.md)

# Debugging: graphs, runtimes and remote boxes

This page answers: when a render fails, hangs or returns the wrong image, where does the agent
look first? It gives a symptom table, the traps of driving Windows GPU boxes over SSH, the
two-failures rule, and the shape of the command an agent hands me when it is blocked.

> **TL;DR**
> - Probe the queue endpoint, not ping. ComfyUI being down does not mean the box is down.
> - The expensive class is silent wrong output: read the graph that was actually submitted, check block counts, clear shared state before comparing.
> - On a shared server, a polluted process gets restarted, not reasoned about.
> - Remote PowerShell goes through script files sent by a runner, never inline strings.
> - Two failures of the same shape: stop and re-inventory. Blocked: hand over one runnable command.

## Symptom table

Versions matter: findings marked 0.27.1 or 0.33.1 were not re-checked on 0.42.1, which both
render boxes run since 2026-10-20.

| Symptom | Likely cause | First check |
|---|---|---|
| Graph rejected: value not in list | Local model index a generation stale; file half-downloaded | Name in the live server's `object_info`; byte count on disk |
| New node type missing after install | Server never really restarted, or survived sleep with old code | Process start time; node present in `object_info` |
| Node pack registers nothing after an upgrade | Pack built for a different core version | Server start log; node list |
| Same seed, different pixels after a ComfyUI upgrade | Expected drift (Anima PSNR 28 to 37 dB, 0.27.1 to 0.42.1) or a real regression | Same-seed A/B on a sibling instance; composition unchanged means drift |
| Old runtime will not start after rollback | 0.42.1 migrated the UI database | Restore the database backup taken before the upgrade |
| OOM at VAE decode only on a quantized model | Quantized DiT not partially offloadable | Explicit unload and cache empty before decode |
| Server dies, no traceback, event log shows a driver reset | Desktop apps ate through `--reserve-vram 1.0` | Raise `--reserve-vram`: 2.5 on Box A, whose desktop apps hold about 2.4 GB; size yours from your own apps |
| VRAM stays high after `/free`; "Cannot set version_counter for inference tensor" | LoRA on a partially loaded INT8 ConvRot checkpoint (about 11 GB leaked) | Service stop and start; `/free` cannot recover it |
| VRAM or commit memory held with no job; WinError 1455 | Orphan or zombie Python from a crashed run | Processes by command line; kill by listening port or command line |
| Server reports free VRAM, jobs still OOM | Server's number ignores other processes; Box A's foreground apps hold about 2.4 GB | Vendor tool total minus the server's own use |
| Job "succeeds" with empty outputs, or polls until timeout on a rerun | Whole graph hit the execution cache (0.27.1 lists no outputs without a client id) | Look up history by prompt; change the seed |
| Rerun returns another image's pixels | Local reuse of a cached file path | Fetch from the box's history by prompt id |
| Queue wedged | A node waiting on a model download the box cannot reach | Server log; queue endpoint |
| Training frozen at step 3, VRAM exhausted | One-shot scheduled tasks re-fired together | Task list by prefix |
| Same seed differs between runs on a shared box | A node patched the model in place (IP-Adapter: mean pixel diff 16.55) or an object patch leaked across clones | Free with `free_memory`; run a plain no-LoRA sampler after the special node |
| Black images after several agents shared one server | Process-level pollution, cause not captured | Restart the server |
| Scribbles, or control silently ignored | Block-count mismatch | Card's `blocks`; patches = tensors / 3 |
| LoRA "compatible" but changes nothing | Strength 0 short-circuit, or zero patches from a wrong key dialect | Patch count in the log; control arm at 0.001 |
| Output has the wrong size | Qwen-Image canvas not a multiple of 16 | Latent width and height |
| A "finding" contradicts known behaviour | Graph differs from what you think (denoise 0.5 on txt2img) | Read the graph embedded in the PNG |
| Ping 100% loss, box "dead" | ICMP blocked by design | Queue endpoint, or SSH on port 22 |
| system-stats returns 500 | That endpoint failed while queue, prompt and object-info returned 200 | Use the queue endpoint as the health check |
| PCIe reads Gen3, BAR 256 MiB | Link negotiation stuck after sleep or a driver update | Reboot and re-measure before suspecting BIOS |
| SSH exit 255 | Transport failure; any other non-zero code means the command ran remotely | Retry another route only on 255 |

## Rules for silent failures

1. **Read the graph that was actually submitted, not the script defaults or the metadata JSON.**
   Why: on 2026-06-25 a txt2img graph carried denoise 0.5 and produced three false findings,
   among them the VAE and exposure ones. All three were retracted.

2. **Before comparing two renders on a shared server, clear node state with `free_memory`.**
   Why: on 2026-10-01 an IP-Adapter node patched DiT blocks in place; the next plain render with
   the same seed differed by a mean of 16.55. Unloading models did not clear it; freeing node
   memory restored pixel identity. Two wrong verdicts that day came from this.

3. **Custom nodes that replace a module's forward must use injections, not object patches.**
   Why: on 0.33.1, object patches are not restored when the server switches between clones of
   the same base, so the wrapper leaks into the next unrelated job. Test by running a plain
   no-LoRA sampler right after the special node.

4. **Black images on a long-running shared server: restart it.**
   Why: on 2026-10-01 img2img went black again about an hour after a morning restart, while several
   agents shared the box. A clean process fixed
   it; precision was a red herring and the bf16 "fix" was reverted. The source was not captured.

5. **Do not add a client id to get cached outputs back.**
   Why: it turns progress broadcast into unicast and silences the progress bar. On 0.27.1 an
   identical rerun polled until the 1800 s timeout and looked like a hang; the fix looks up the
   last 200 history entries for the same prompt and fails fast with "change seed" otherwise.

## Rules for remote Windows boxes

1. **Send PowerShell as a script file through a runner, never as an inline string.**
   Why: Windows OpenSSH's default shell is cmd.exe, which parses the command before
   PowerShell sees it; UTF-8 piped into PowerShell 5.1's stdin is lossy; cmd's command line
   stops at 8191 characters. The runner sends the script as UTF-16LE base64 over stdin.

2. **Keep runner payloads small; copy large files first.**
   Why: scripts of 60 KB and more stalled intermittently on Box A (1 to 46 KB never did),
   2026-10-01, leaving remote PowerShell processes waiting for EOF. Kill those by pid after a
   timeout.

3. **Write PowerShell 5.1-safe code.**
   Why: each item below failed once. Invoke a second script and format its output in two
   statements, not inside a parenthesised pipeline. Temporary scripts end in `.ps1`.
   Use `-LiteralPath` (brackets in names are wildcards; `Move-Item` reports success and moves
   nothing). Set `$ProgressPreference = 'SilentlyContinue'`. `Write-Host` over SSH becomes a
   CLIXML blob on stderr (2026-09-23), so collect log lines and write them once at top level.
   `Write-Output` inside a function joins the return value.

4. **Decode console output as GBK and parse numeric status codes.**
   Why: Box A's console code page is 936 (2026-08-27). Three weeks of logs held 40+ garbled
   "file not found" lines. In `sc query`, the number survives mojibake; the English word does not.

5. **Keep cmd.exe one-liners trivial; write anything longer as a .cmd file with CRLF.**
   Why: cmd mangles `;`, `$?`, `&&` and `<`. `if not exist DIR mkdir DIR & move ...` silently
   skips the move. The agent's Bash tool rewrites `>nul` into `>/dev/null`, a path that does not
   exist on Windows.

6. **Start long-lived processes with WMI process creation.**
   Why: the SSH session is a job object that kills the whole tree on disconnect, and
   `Start-Process` without a window station fails without an error, not even creating its log
   directory. Split "edit, stop, start" into small separate scripts; combined ones hang.

7. **Handle scheduled tasks deliberately.**
   Why: tasks created over SSH run only during an interactive logon; the XML route needs S4U
   logon and UTF-16 with BOM (2026-10-13). One-shot definitions must be deleted right after a
   confirmed launch: on 2026-07-20 nine re-fired at once and froze training at step 3. For a
   server task the opposite holds: deleting the definition kills the running instance, so keep
   it with a start time in the past. Interactive task windows get closed by a person.

8. **On a box where CIM-loading PowerShell hangs, use plain cmd or one WMI call; do not raise the timeout.**
   Why: 14 timeouts in three weeks on Box B; the stuck processes eventually blocked even the
   SSH banner (2026-10-13).

9. **Never delete through the recycle bin remotely.**
   Why: measured on 2026-10-13, the recycle-bin API in a non-interactive SSH session deletes
   permanently. Move files to a dated quarantine folder on the same drive with a restore map,
   and let me delete the folder.

10. **Do not touch proxy settings from remote scripts.**
    Why: Box B's configured proxy is dead; changing the default web proxy hung the session and
    left orphans. When a job's dependency install fails on that proxy, report it instead of
    editing proxy variables (2026-10-19).

11. **Trust the listening-socket query over service logs, and kill by port or command line.**
    Why: some services print 127.0.0.1 while bound to all interfaces. `taskkill /im` kills
    same-name processes that belong to someone else and leaves multiprocessing children alive.

12. **A hook that rewrites the tool output shape is a tool defect, not a network problem.**
    Why: on 2026-10-19 a managed post-tool hook reported "expected object, received string"
    and hid the output of a script that never ran. Change the call shape once; if it still
    fails, hand the command to me.

## Two failures, then re-inventory

1. **After two failures of the same task, stop. Do not make a third attempt of the same shape.**
   Why: the usual cause is a missing tool or an unread document, not a coding error. Standing
   rule since 2026-08-27.

Procedure after the second failure:

1. Write down both attempts and their exact error text.
2. Re-inventory: tools and MCP servers available, project scripts and docs on the topic, the
   runtime versions actually in play (per venv, per box), what changed since it last worked.
3. Check the claim behind the plan. Examples that were wrong: "this box has no triton" (true
   for the training venv, false for the ComfyUI venv); "the box lacks this feature" (the
   installed browser extension was two versions behind, 2026-08-25); "network policy forbids
   this call" (one minimal request worked, 2026-09-16).
4. Pick a different approach, or stop and report the blocker.

## Handing over a runnable command

1. **Blocked means a runnable command, not prose.**
   Why: owner's decision since 2026-09-19. A gate, a missing permission, a root-owned file or a
   GUI-only step stops the agent; describing the steps leaves me to assemble them.

Typical blockers: loading or restarting a launch agent, process or network probes the managed
session cannot run, a GUI load check on a busy render box, anything on the network plane.

- [ ] One command, shortest form, copy-pasteable.
- [ ] Idempotent: a second run changes nothing.
- [ ] Backs up every file it overwrites.
- [ ] Aborts when the anchor it edits is missing.
- [ ] Verified on a copy first.
- [ ] States which parts stayed unverified.

Shape of such a command (illustration):

```bash
set -euo pipefail
f="$HOME/example/service.yaml"
grep -q '^args:' "$f" || { echo "anchor 'args:' missing, abort"; exit 1; }
grep -q -- '--reserve-vram 2.5' "$f" && { echo "already applied"; exit 0; }
cp -p "$f" "$f.bak.$(date +%Y%m%d%H%M%S)"
# macOS sed; with GNU sed, drop the ''
sed -i '' 's/^args:\(.*\)$/args:\1 --reserve-vram 2.5/' "$f"
grep -- '--reserve-vram 2.5' "$f"
```

## Real cases

- **2026-07-02, fake restart.** The service restart returned in 0.5 s; the Python process
  survived and a newly installed node pack never loaded. Rule: kill the listener, then start,
  then verify start time.
- **2026-07-20, re-fired tasks.** Nine one-shot scheduled tasks fired together, VRAM ran out,
  training froze at step 3. Rule: delete one-shot definitions after launch; an empty task list
  by prefix is part of wrap-up.
- **2026-08-25, orphans.** 13 orphaned multiprocessing Pythons held 33 GB and blocked a
  verified configuration with the misleading error "invalid python storage". Rule: verify the
  listener's identity, not just "port alive and version right".
- **2026-08-28, alias instead of URL.** A request helper got a box alias instead of the resolved
  URL, built a fake hostname and got a 403 from the egress proxy. A network specialist was
  dispatched for nothing. Rule: a 403 there is a calling mistake.
- **2026-09-01, PCIe misread.** The link read Gen3 with a 256 MiB BAR, and the agent inferred a
  BIOS or cable fault. BIOS was fine; one reboot restored Gen5 x16 and a 16 GiB BAR.
- **2026-09-30, wrong pixels.** A, then B, then a rerun of B stored A's pixels with B's metadata
  (Box B, 0.27.1). Rule: fetch outputs from the box's history by prompt id; local cached-path
  reuse removed.
- **2026-10-01, two wrong verdicts.** Comparisons on Box A ran after IP-Adapter and dtype nodes
  had touched the shared process. Rule: free node memory before any comparison.
- **2026-10-13, permanent recycle bin.** Remote cleanup through the recycle-bin API freed disk
  space immediately; nothing reached the bin. Rule: quarantine folder with a restore map.

## Tried and dropped

- Adding a client id so cached outputs show up in history.
- Raising timeouts for the CIM hang.
- Changing precision to fix black images.
- Remote recycle-bin deletion.
- Inline `powershell -Command` strings over SSH.

## See also

- [`04-model-bringup.md`](04-model-bringup.md): architecture checks before a model goes live.
- [`06-render-discipline.md`](06-render-discipline.md): process-group queue stops, cleanup.
- [`07-performance.md`](07-performance.md): when the problem is speed, not correctness.
- [`11-safety-and-privacy.md`](11-safety-and-privacy.md): managed egress and gates.
