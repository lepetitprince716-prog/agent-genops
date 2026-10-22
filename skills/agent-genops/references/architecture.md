# Architecture reference

Purpose: decide which plane and which layer a piece of work belongs to, and which entry point to use.
Read when: you are about to render, add a tool or script, touch a box, or route work to a machine.

## Planes

| Plane | Contains | Renders? |
|---|---|---|
| Control | root session, subagents, external workers, skills, MCP servers, task tracker, memory files, hooks and gates | Never |
| Execution | render boxes (ComfyUI, API-format graphs), loopback sidecars, cloud APIs, browser-pane operators, batch node | Yes |

- Plan, dispatch, verify and record in the control plane.
- Treat every execution backend as swappable. Put backend specifics in its engine or runbook, not in the root's reasoning.
- Never render on the Controller. Controller and render box are roles: on a single machine that
  holds both, probe before every render and keep agent work from competing with a running job.

## Layers (top to bottom)

1. Callers: web app, browser chat, MCP server, CLI. Hold no recipes.
2. Job brief + persistent queue: one validation layer shared by all queued callers; idempotency key per submit.
3. Intent router: maps intent + uniform flags to an engine. Prints by default; `--run` executes.
4. Engines: one per model family or line. Own graph, recipe, per-box quirks.
5. Transport: the only code that talks to a box (HTTP to ComfyUI; remote PowerShell runner on Windows).
6. Boxes: run what they are given. Probe live every time.
7. Evidence: result manifest per run, metadata JSON per image, jobs DB, review ledgers.

Specialist adapters (cloud APIs, instruction edits, video, exact-recipe replay) sit beside the router and call engines or transport directly. Do not fold them into the router.

## Which entry point

| Need | Use | Not |
|---|---|---|
| A render someone will keep | MCP generate group or a JSON job brief into the queue | raw `comfy_run`, canvas |
| One-off render from a shell | router without `--run`, read the command, then add `--run` | calling an engine directly |
| Analysis graph, node or model lookup | MCP raw group (`comfy_status`, `comfy_models`, `comfy_nodes`, `comfy_run`) | the product queue |
| Inspect or patch what the human has open in ComfyUI | MCP canvas group | queuing from the canvas |
| Agent host without MCP | the server's CLI twin: `<launcher> call <tool> '{json}'` | a second server |
| Cloud provider render | that provider's adapter, under its budget and ledger | the local router |
| Site with no API | browser-pane operator subagent, exact prompt, one submit | improvised clicking by the root |

## Rules

- Run the router in print mode first. Compare the printed command with the brief. Then `--run`.
- Read results from the result JSON, not stdout. Open every output path you report.
- Probe the box before every run: queue empty, enough free VRAM. A valid plan is not proof of availability.
- Never queue from the canvas. The human presses Queue.
- Validate model names against the box's live object info before submitting a graph taken from a saved workflow.
- Add a new agent-facing ComfyUI capability to the existing server's raw group. Do not start a new MCP server.
- Keep a separate standalone server only when the surface must be usable without this repo's data.
- When stdout is the MCP wire, run anything that prints or calls `SystemExit` in a subprocess.
- If the queue fails, report the failure. Do not fall back to direct execution unless the explicit bypass is set.
- Count tools from the server's own listing, never from a document.

## Script catalogue

Before writing any script:

1. Run the router's `--list`.
2. Search the script index (one line per script, default mode, exit codes, refusals, tests, companion doc).
3. Read the companion doc of the closest match.
4. If a script fits, borrow by copying it to scratch and editing the copy.

When maintaining an `active` script in place:

- Freeze its path, CLI and output contract unless the task contract says otherwise.
- Update tests, the machine registry and the index in the same commit.
- Take status (`active`, `probe`, `legacy`, `test`, `reference`) from the registry only.
- Expect CI to reject an unregistered script or an undeclared risk increase.

When adding a stable script: docstring, one index line, one registry entry.

## Box routing

| Condition | Route |
|---|---|
| Model or detector exists on one box only | that box |
| Both eligible, Box A idle | Box A |
| Both eligible, Box A busy (low free VRAM, queue not empty, unreachable, owner gaming) | Box B |
| Test render, smoke, A/B arm, dataset | Box B, no per-batch ask (if your owner has authorised it) |
| Sidecar line | run a script on the sidecar's host that calls its loopback |
| Anything on a Controller that is not also a render box | refuse |

- Busy thresholds assume resident models. Do not use empty-GPU numbers.
- Do not free VRAM after each render. Let the lease and idle reaper release it.
- Do not run 4x model upscale on a box the owner may be gaming on.

## Reachability

- Route order: LAN, then tunnel, then mesh VPN. Use the route picker's choice; do not hard-code a host.
- Where managed wrappers exist, go through them only, one wrapper per command (see `safety.md`).
- Pass the resolved full URL to request helpers, never a box alias.
- Health: probe the ComfyUI queue endpoint. Do not use ping. Do not rely on system-stats alone.
- Do not run route status or refresh from the sandbox; it writes DOWN into the cache.
- Read the running forward definition before acting on any claim about routes.

## Stop conditions

Stop and report to the root session when:

- the box probe returns HOLD or busy and no other eligible box exists;
- the router's printed command does not match the brief;
- a needed capability has no entry point and would require a new server or a new script with no catalogue match;
- a change would touch Box A configuration, the network plane, or non-test data without a recorded authorisation;
- a wrapper or gate denies a call (a denied call did not run; do not retry in another shape twice).

## What to report

- Plane and layer used, entry point, exact command or tool call.
- Box chosen and the probe result that chose it.
- Result JSON path, output paths you opened, return code.
- Any catalogue gap or doc ambiguity you hit.
