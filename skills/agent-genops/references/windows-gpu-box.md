# Windows GPU box

Purpose: run commands, scripts and services on remote Windows render boxes over SSH without the known traps.
Read when: writing PowerShell or cmd for a Windows box, starting or restarting a service there, deleting remote files, or reading its console output.

## Transport

- If the setup has managed SSH and copy wrappers and a remote PowerShell runner, use them, and never bare ssh from a managed session. Without them, plain ssh and scp do; the rules below still apply.
- Short non-PowerShell command (`ver`, `sc query`, `taskkill`): one cmd one-liner over ssh.
- Any PowerShell, however short: write a `.ps1` file and send it through the runner (without one, copy it over and run it with `powershell -File`). Never `ssh ... powershell -Command "..."`.
  - cmd.exe is the default remote shell and parses first.
  - UTF-8 into PowerShell 5.1 stdin is lossy.
  - cmd command line limit: 8191 characters.
- Runner payloads stay small. Scripts of 60 KB and more stalled intermittently. Copy big files first, then send a small runner.
- After a runner timeout, find leftover encoded-command PowerShell processes by command line prefix and kill them by pid.
- The runner consumes stdin. Remote scripts get data through parameters, not `[Console]::In`.
- SSH exit 255 = transport failure, retry another route. Any other non-zero code = the command ran; do not switch route.
- Upload or POST large bodies through the managed HTTP proxy with the `Expect:` header cleared (a 1.5 MB upload hung without it, 0.2 s with it).

## PowerShell 5.1 rules

- Start every script with `$ProgressPreference = 'SilentlyContinue'` and a terminating `$ErrorActionPreference`.
- Invoke another script and format in two statements:
  `$raw = & $scriptPath -Action Status` then `$text = ($raw | Out-String).Trim()`.
- Temporary scripts end in `.ps1` (`x.preflight-20261021.ps1`, not `x.ps1.tmp`).
- Use `-LiteralPath` for any file operation; brackets are wildcards with `-Path`. Verify with `Test-Path -LiteralPath`.
- Do not log with `Write-Host` (becomes CLIXML on stderr) or `Write-Output` inside functions (joins the return value). Collect log lines in a list; write once at top level.
- Receiver side: strip CLIXML noise by taking first `{` to last `}` before JSON parsing, as a last resort only.
- `ft` is `Format-Table`. Call CLIs with that name as `ft.cmd`.
- No `true` binary on Windows; use `exit` for a no-op probe.

## cmd.exe rules

- cmd mangles `;`, `$?`, `&&`, `<`. Beyond a trivial one-liner, write a `.cmd` file with CRLF line endings via the file tool.
- `if not exist DIR mkdir DIR & move ...` skips the move silently. Separate calls; verify by target size.
- Use `>NUL:` in one-liners; a gate has rewritten `>nul` into a path that does not exist on Windows.
- Reading a safetensors header length from cmd: `int.from_bytes(f.read(8),'little')`; `'<Q'` collides with redirection.

## Output decoding

- Console output is GBK (code page 936). Decode bytes as GBK, or UTF-8 with `errors="replace"`.
- Parse `sc query` by numeric state (`: 4` = RUNNING), not by the English word.
- Some services signal READY on stderr. Watch both streams.
- Some services log 127.0.0.1 even when bound to all interfaces. Trust the listening-socket query.

## Processes and services

| Need | Do | Never |
|---|---|---|
| Long-lived process that survives SSH | WMI `Win32_Process.Create` running `powershell -NoProfile -ExecutionPolicy Bypass -File <script.ps1>` | `Start-Process` (killed with the session job object, or fails silently without a window station) |
| Path with spaces in the command | Put it inside the `.ps1` the WMI call runs | Inline quotes in the WMI command line |
| Kill a process | By listening port (`Get-NetTCPConnection` owner) or command-line match | `taskkill /im` (hits same-name processes, leaves children) |
| Restart a service-hosted ComfyUI | Empty queue, kill the listener's process tree, start, verify start time or new node | Trust a service "restart" that returns in under a second |
| Wait for a build | `-PassThru`, then `WaitForExit()` on the main process | `Start-Process -Wait` (waits for resident helper processes) |
| Edit config, stop, start | Three small scripts | One combined script (hangs) |

Box with CIM-hang history (Box B): plain cmd or one `Win32_Process.Create` call only. Do not lengthen timeouts.

## Scheduled tasks

- Tasks created over SSH run only during an interactive logon. Use XML with `LogonType S4U`, encoded UTF-16LE with BOM.
- One-shot tasks: delete the definition right after the launch is confirmed. At wrap-up, a query by your task prefix must be empty.
- Server tasks: deleting the definition kills the running instance. Keep it; set the start time in the past.
- Interactive (`/IT`) windows get closed by a person, killing the server with Last Run Result `3221225786` (`0xC000013A`, `STATUS_CONTROL_C_EXIT`). Always pass `-WindowStyle Hidden` to `powershell.exe`, and update an existing server task in place via `New-ScheduledTaskAction` + `Set-ScheduledTask -TaskName ... -Action $newAct` instead of unregistering it.

## VRAM, RAM cache and GPU

- `--reserve-vram 2.5` on boxes with desktop apps; 1.0 caused silent driver crashes.
- On `ComfyUI 0.46.0`, pass explicit bounds `--cache-ram 4.0 8.0` alongside `--reserve-vram 2.5` when hosting multiple model families on one port; bare `--cache-ram` defaults inactive headroom to `100%` of system RAM (`47.2 GiB` on Box A) and evicts resident models on every workflow switch (`14.13 s` reload vs `0.15-0.61 s`).
- In GPU venvs on Windows, never install CPU `onnxruntime` alongside `onnxruntime-gpu`: the CPU wheel overwrites `onnxruntime/capi` and hides `CUDAExecutionProvider`. Cap `isnet-anime.onnx` CUDA BFC arena at `1536 MiB` (`512 MiB` OOMs at `Conv_83`), and keep 1-shot CLI calls on CPU (`0.314 s` on Ryzen 9800X3D vs `6.27 s` cold cuDNN init).
- Judge free VRAM as vendor tool total minus the server's own use; foreground apps on Box A hold about 2.4 GB.
- Orphan Python processes from crashed runs hold VRAM and commit memory (WinError 1455). Confirm the command line is not the live server before killing.
- Do not start GPU work when a neighbour is rendering or the owner said not to.

## Deletion

- Never use the recycle bin remotely: in a non-interactive SSH session it deletes permanently (measured 2026-10-13).
- Move to `<drive>:\_trash_YYYYMMDD\<original relative path>` on the same drive and write `RESTORE_MAP.tsv`. The owner deletes the folder.
- Only clear output, input and temp subfolders of ComfyUI. Never datasets, training checkpoints, converted LoRAs, models.
- List targets and sizes before moving anything.
- Box clocks can be hours off the controller. Select cleanup targets by filename range or "last N minutes" on the box, not by controller clock time.

## Network on the box

- Do not change system or default web proxy settings from remote scripts; on a box with a dead proxy this hangs the session.
- Dependency install fails on a dead proxy: report it; do not edit proxy variables in the job.
- Secrets never enter payloads, argv or logs. Scripts read keys from local files on the box without printing them.

## Stop and report

- The runner or SSH wrapper fails, is rejected, or the box is unreachable after starting ComfyUI: follow the project's network handoff. Do not split or reshape commands to get around a gate.
- A hook rewrote the output shape: change shape once; then hand the command to the owner.
- Away from the LAN with no working PowerShell route: finish everything that does not need it, then report.
