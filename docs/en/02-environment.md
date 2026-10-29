English | [中文](../zh/02-environment.md)

# Environment: machines, stack, and what runs where

This page answers: what hardware and software does this method run on, which work goes to
which machine, and how the agents reach the machines. The numbers are mine and dated. Use
them as a reference point, then fill in [`templates/fleet.example.yaml`](../../templates/fleet.example.yaml) for your own setup.

> **TL;DR**
> - Four roles: a Controller that runs the agents and renders nothing, two Windows render boxes, and a Linux node outside the image lines.
> - Box A takes the quality line and training. Box B takes drafts, tests and dataset renders, because it is free and nobody games on it.
> - Sidecar ComfyUI instances listen on Box A's loopback only and are reached by running a script on Box A.
> - Reachability is a route choice: LAN first, then a tunnel, all through managed wrappers. Probe the queue endpoint, never ping.
> - Box A is also the owner's gaming PC. Routing, thresholds and the VRAM lease all assume the owner may be using the GPU.

## Machines

| Public name | Hardware and role |
|---|---|
| Controller | MacBook Air, Apple M5 (10 cores), 24 GB. Runs the agents; renders nothing. |
| Box A | Windows desktop, NVIDIA RTX 5080 16 GB, AMD Ryzen 7 9800X3D, about 48 GB RAM. Main render box for the quality line and LoRA training. It is also the owner's gaming PC, so agents yield to the owner. Since 2026-10-13 it also sleeps when idle. |
| Box B | Windows desktop, NVIDIA RTX 4060 Ti 16 GB, 32 GB RAM. Worker box for drafts, tests and datasets. Sleeps when idle. |
| Linux node | An NVIDIA DGX Spark pair (head plus one worker) used for batch jobs and model services. Not part of the image lines described here. |

## Software stack per machine

Only versions the records state, with the date they were recorded.

**Controller (macOS).**
- Claude Code (root session and subagents), herdr for external workers, bd for tasks, portless for named local HTTPS URLs.
- The web studio app and gallery. The production server starts only from the main checkout, never a worktree (incident 2026-08-08 below).
- The VRAM reaper runs here as a detached process adopted by the OS service manager, so it survives the agent sandbox.

**Box A (Windows).**
- ComfyUI 0.42.1 since 2026-10-20, torch 2.10.0+cu130. Launch flags: DynamicVRAM on, `--use-sage-attention`, `--fast fp16_accumulation`, `--reserve-vram 2.5`.
- Runs as a Windows service, switched to delayed auto-start on 2026-10-20. Auto-start after a real reboot is not yet verified.
- Since 2026-10-13 it also sleeps when idle, like Box B.
- Rollback path kept: the 0.33.1 source and venv. 0.42.1 migrated the ComfyUI database to a schema 0.33.1 cannot open, so rollback means restoring the backed-up database first.
- kohya sd-scripts in its own training venv: torch 2.7.0+cu128, accelerate 1.13.0, xformers 0.0.30, bitsandbytes 0.49.2, transformers 4.44.2, diffusers 0.32.2.
- triton is judged per venv: the ComfyUI venv has triton 3.8.0 (2026-09-16); the training venv does not.
- Sidecar instances, each on its own ComfyUI version, loopback only, normally stopped:
  - Qwen-Image-2.1 on ComfyUI 0.37.0 (approved 2026-09-29). Same-seed text-to-image and edit outputs were pixel-identical against 0.42.1.
  - FLUX 3 Klein on ComfyUI 0.41.0 (built 2026-10-16, about 11.7 GB VRAM).
  - An edit-model sidecar on a ComfyUI master build, set up 2026-10-21. New; one of my own notes still lists it as not deployed.
- Trap: one sidecar's venv is a thin layer over the production venv, so upgrading the production venv in place changes the sidecar too.

**Box B (Windows).**
- ComfyUI 0.42.1 since 2026-10-20, torch 2.10.0+cu130, started at boot by a scheduled task. Ready 80.6 s after a manual task start; the boot trigger itself waits for the next reboot to count as verified. Its front-end package is older than Box A's.
- fp16 accumulation and SageAttention on by default. fp16 accumulation re-measured on 0.42.1 (2026-10-29): 1.21x on an SDXL-class checkpoint and 1.25 to 1.27x on Anima (1.19x and 1.05x on 0.27.1). SageAttention on top added 2.7 to 8.7 percent depending on the line, measured on 0.27.1 (2026-09-30) and not re-measured.
- triton_windows 3.8.0. A second kohya install for training.
- Sleeps when idle. Its idle check samples every 5 minutes, so short jobs do not keep it awake.
- 32 GB RAM plus a 16 GB pagefile. A training run that exceeded the commit limit failed with WinError 1455.
- No route to GitHub, Civitai or Hugging Face; pip goes through a domestic mirror (verified 2026-06-21, not rechecked).
- Rollback path kept: the 0.27.1 launcher plus the database backup.

**Driver drift.** The two boxes run different NVIDIA driver branches (recorded 2026-09-03).

**Linux node.** A job runner with a ledger dispatches batch work there. While its model service runs, it accepts only small CPU jobs and refuses GPU jobs.

## What runs where, and why

| Work | Where | Why |
|---|---|---|
| Quality line (upscale plus detailers), large DiT models | Box A | The bigger GPU. The SDXL quality stack ran about 100 s per image (median of 3, 2026-09-01) at 99 percent GPU utilisation. |
| Sidecar lines (Qwen-Image, edit models) | Box A, loopback | Each needs its own ComfyUI version; loopback keeps them off the LAN. |
| LoRA training | Box A first, Box B possible | SDXL LoRA dim16, about 2100 steps: about 25 min on Box A. Dim32 at 1024 with gradient checkpointing: about 2.0 s/it on Box B (2820 steps, about 95 min). Do not reuse one box's estimate for the other. |
| Drafts, test renders, A/B arms | Box B | Free, and nobody games on it. Since 2026-09-30, test renders go to Box B without asking per batch. |
| Dataset renders | Box B | Free. About 420 Buzz once went to Civitai for a dataset Box B could have made at no cost. |
| Agents, web app, gallery, review pages | Controller | It renders nothing. |
| Batch jobs, model services | Linux node | Outside the image lines. |

Some routes are pinned by resources, not policy: a line whose model or detector exists on only
one box goes to that box. When both boxes qualify, `--box auto` applies the probe described
under GPU sharing.

## Reachability

Reachability is a route choice, made per call, not a fixed hostname.

1. **LAN first.** The fastest path and the default at home.
2. **Then a tunnel.** Used when the Controller is away from home or the LAN is unreachable.
3. **A mesh VPN last.** Fast at home, but slow when it falls back to a relay.

All of it goes through managed wrappers: one wrapper per command, no bare `ssh` or `curl` from
helper scripts. On the Controller, one loopback forward per box is kept alive by the OS service
manager. A route picker behind it chooses LAN, tunnel or VPN, so scripts always see one fixed
local endpoint per box. Sidecars are reached by running a script on Box A that calls its own
loopback, through the remote PowerShell runner.

Measured transport (same 5.94 MB file, 2026-09-01):

| Route | Steady throughput | Note |
|---|---|---|
| LAN | 48.1 MB/s | Loopback rtt p50 17.4 ms over LAN (2026-09-17) |
| Mesh VPN | about 11.2 MB/s | At home only; first pull 10.06 s, repeat 0.53 s (hole punching) |
| Tunnel | about 0.33 MB/s | Single sample, then a timeout |

Away from home (2026-09-22) the order flipped: the mesh VPN went through a relay at 3.7 KB/s
while the tunnel gave 461 KB/s. The route order became LAN, tunnel, VPN.

Health checks: ICMP is firewalled on both boxes, and SSH stays up when ComfyUI is down. Probe
the ComfyUI queue endpoint. Do not rely on the system-stats endpoint alone: it once returned
500 while queue, prompt and object-info answered 200.

## GPU sharing with the owner

Box A is my gaming PC. The rules below exist because of that.

1. **Probe Box A first; fall back to Box B when it is busy.**
   Why: `--box auto` replaced the 2026-07-18 "Box B first, always" policy. Box A counts as busy when free VRAM is low, the queue is not empty, or it does not answer.
2. **No 4x model upscale while the owner may be gaming.**
   Why: the large intermediate image from an ESRGAN-class upscale runs the shared GPU out of memory. Use a higher native resolution in one pass instead.
3. **Keep models resident; let the lease and idle reaper free VRAM.**
   Why: owner decision 2026-09-22. A per-render free cost a 1.9 s round trip and reloaded weights on the next image. The old "POST `/free` after every run" rule is obsolete.
4. **Set busy thresholds against resident models, not an empty GPU.**
   Why: with models resident, a sidecar had only about 45 percent VRAM free while idle, so a 40 percent threshold misjudged it. The sidecar threshold became 35 percent.
5. **Count the owner's foreground apps in the VRAM budget.**
   Why: apps kept open on Box A hold about 2.4 GB of VRAM all the time (2370 to 2493 MiB measured). The job runner's GPU-ready threshold went from 2048 to 4096 MiB with my consent on 2026-10-19; the new threshold is deployed on Box A only, and Box B still runs the 2048 MiB build.
6. **When any ComfyUI instance has queued work, batch GPU jobs wait.**
   Why: owner's decision. A GPU guard freezes the whole GPU job group, and those jobs must not submit prompts to the ComfyUI instances themselves.
7. **Changes to Box A ask first; Box B tuning is pre-authorised.**
   Why: owner decision 2026-09-30. Memory, precision, attention backend, resident models and launch flags on Box B are in scope for agents; Box A, the network plane and deleting non-test data still need a yes.

## Real cases

- **2026-09-22, silent fallback to the tunnel.** The Controller picked up a DHCP lease on a different subnet from the boxes. The route picker fell back to the tunnel without saying so. A Qwen render took 8 s on the GPU and over 230 s of wall clock. Only I could fix the network; afterwards a route refresh restored LAN. Rule: diagnose from the route cache first, then time a loopback request.
- **2026-08-28, a box alias where a URL belonged.** A request helper was given a box alias instead of the resolved URL, built a fake hostname and got a 403 from an access proxy. A network specialist was dispatched for nothing. Rule: the request helper takes the full resolved URL; a 403 there is a calling mistake.
- **2026-09-17, a handoff that read the forward wrong.** A handoff written by a cloud session assumed the loopback forward went through the tunnel and proposed overwriting its definition, which would have removed the route picker. Rule: read the running definition before acting on a claim about routes.
- **Route probes from the sandbox.** Inside the agent sandbox every probe reports DOWN and writes that into the route cache. Rule: do not run route status or refresh from the sandbox; to kick a stuck forward, kill its process and let the supervisor re-probe.
- **2026-08-08, production server from a worktree.** Started from a worktree, the gallery pointed at a sparse tree and its count fell from hundreds to single digits. Nothing was lost. Rule: production server from the main checkout only; the start script now refuses worktree paths.

## Tried and dropped

- **"Box B first, always"** (2026-07-18). Replaced by probe-first routing.
- **The mesh VPN as the away-from-home answer.** Dropped to last place after the 2026-09-22 relay measurement.
- **A forward that always went through the tunnel, even at home.** Replaced by the route picker after I decided on 2026-09-01: "if LAN works, use LAN".
- **Launch-flag reasoning from older ComfyUI versions** (2026-07-02: no `--fast`, no `--reserve-vram`). Superseded; both boxes now run fp16 accumulation and SageAttention, and Box A reserves 2.5 GB.

## Adapting this to your setup

Copy [`templates/fleet.example.yaml`](../../templates/fleet.example.yaml) and fill it in before an agent dispatches anything.

- [ ] Name each machine by role, not by hostname. Mark which one runs agents and renders nothing.
- [ ] Record GPU, VRAM, RAM and OS per box, and the date you recorded them.
- [ ] Record the ComfyUI version per instance, its rollback path, and whether the database was migrated.
- [ ] Mark which box is shared with a human, and what that person keeps open on the GPU.
- [ ] List the lines each box may run, and which ones are pinned to one box by resources.
- [ ] Write the reachability order (LAN, tunnel, VPN) as words. Keep addresses in private config, never in the registry.
- [ ] Write the health probe per box (the queue endpoint) and the busy thresholds with models resident.
- [ ] State which changes are pre-authorised per box and which need a human yes.
- [ ] Record outbound blocks per box (model hosts, package indexes) with the date checked.

## See also

- [`01-architecture.md`](01-architecture.md): the two planes and the layers.
- [`04-model-bringup.md`](04-model-bringup.md): adopting a new model or ComfyUI version.
- [`05-debugging.md`](05-debugging.md): Windows remote traps, restarts that do not restart.
- [`06-render-discipline.md`](06-render-discipline.md): smoke first, queues, cleanup.
- [`07-performance.md`](07-performance.md): A/B method and the numbers behind the launch flags.
- [`11-safety-and-privacy.md`](11-safety-and-privacy.md): managed wrappers and gates.
