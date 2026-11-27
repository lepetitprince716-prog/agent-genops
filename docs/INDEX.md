# Repository index

English · [中文](INDEX.zh-CN.md)

Agent runs, ComfyUI generates, you enjoy.

| Area | What it is | Where | Start with |
|---|---|---|---|
| Docs | The whole method: 24 rules, architecture, dispatch, render discipline, debugging, performance, inventory, memory | `docs/en/`, `docs/zh/` | [Philosophy](en/00-philosophy.md) |
| Skill | The same method in a form an agent loads on demand; installs as a Claude Code plugin | `skills/agent-genops/`, `.claude-plugin/` | [SKILL.md](../skills/agent-genops/SKILL.md) |
| Templates and workflows | Task packet, handoff, model card and other forms; tiered subagents; three standard SDXL workflows | `templates/`, `workflows/` | [templates/README.md](../templates/README.md) |
| Three tools | `cwc` compiles ComfyUI canvases, `rdbg` runs PowerShell on remote Windows, `artfetch` builds training sets | `cwc/`, `rdbg/`, `artfetch/` | Each folder's README |
| Companion nodes | Standalone ComfyUI custom node repos that clone directly into `ComfyUI/custom_nodes/` | External repos | [Companion ComfyUI nodes](#companion-comfyui-nodes) |
| Guard | Privacy scan, secret scan, workflow allowlist, release check, git hooks, CI | `tools/`, `.githooks/`, `check`, `tests/`, `.github/workflows/` | [PRIVACY.md](../PRIVACY.md), [AGENTS.md](../AGENTS.md) |

## Docs

Fourteen pages in English and fourteen in Chinese, matched page for page; the Chinese pages are written natively. Read Philosophy first, then pick by setup.

| Page | What it answers |
|---|---|
| [Philosophy](en/00-philosophy.md) | The 24 working rules in six groups, each with its reason |
| [Architecture](en/01-architecture.md) | How the control plane and the execution plane connect |
| [Environment](en/02-environment.md) | The reference machines and what runs where |
| [Dispatch](en/03-dispatch.md) | Which model tier gets which job; task packets; acceptance |
| [Model bring-up](en/04-model-bringup.md) | A new model or runtime, from download to verdict |
| [Debugging](en/05-debugging.md) | Symptom, likely cause, first check; remote Windows traps |
| [Render discipline](en/06-render-discipline.md) | Smoke tests, output isolation, queues, GPU etiquette, cleanup |
| [Performance](en/07-performance.md) | A/B method, variance, quantization and distillation verdicts |
| [Inventory](en/08-inventory.md) | Models, LoRAs, recipes, outputs, archives, ledgers |
| [Providers](en/09-providers.md) | Local boxes, NovelAI, Midjourney, Civitai, GPT Image |
| [Prompting and review](en/10-prompting-and-review.md) | Per-model prompt rules, delegated prompt writing, the taste method |
| [Safety and privacy](en/11-safety-and-privacy.md) | Managed egress, gates, secrets, the public and private split |
| [Continuity](en/12-continuity.md) | Memory files, state snapshots, handoffs, the task tracker |
| [Lessons](en/13-lessons.md) | Dated incidents and the rules they produced |

Every job runs the same loop: intake, inventory, plan, probe, smoke, run, verify, record, clean. The diagram is in the [README](../README.md#the-loop); the stop condition for each step is in the loop table of SKILL.md.

## Skill

[SKILL.md](../skills/agent-genops/SKILL.md) is the entry point: the roles table, the loop, the hard rules, dispatch tiers and when to stop and ask. Details live in `references/`, opened only when needed. Install steps are in the [README](../README.md#use-the-skill).

On start the skill reads `~/.config/agent-genops/LOCAL.md` on your machine; its template is [LOCAL.example.md](../templates/LOCAL.example.md). The router, model index and ledgers named in the docs come from the author's own setup and do not ship here. The roles table in SKILL.md says what each one must do and what a plain ComfyUI can stand in with.

Docs and skill references cover the same ground. When one side changes, check the other.

| Docs page | Skill reference |
|---|---|
| Philosophy | Hard rules in SKILL.md |
| Architecture | `architecture.md` |
| Dispatch | `dispatch.md` |
| Model bring-up | `model-bringup.md` |
| Debugging | `debug.md`, `windows-gpu-box.md` |
| Render discipline | `render-discipline.md` |
| Performance | `perf-ab.md` |
| Inventory | `inventory.md` |
| Providers | `providers.md` |
| Prompting and review | `prompt-rules.md`, `review-loop.md` |
| Safety and privacy | `safety.md` |
| Continuity | `continuity.md` |
| Environment, Lessons | No direct counterpart; the glossary `glossary.md` exists only in the skill |

## Templates and workflows

[templates/](../templates/README.md) holds forms to copy and fill in: task packet, handoff, memory entry, run order, smoke check, model card, A/B write-up, prompt rulebook, incident rule, `LOCAL.example.md` and `fleet.example.yaml`.

`templates/agents/` holds the seven worker roles behind the dispatch tiers, from `haiku-worker` to `fact-checker`. Each file is Claude Code front matter over plain instructions that any agent can use. In Claude Code, copy them to `~/.claude/agents/`; the plugin does not install them. For other agents, [its README](../templates/agents/README.md) gives each role a model size, an effort and an access level.

[workflows/](../workflows/README.md) holds three minimal SDXL workflows: text to image, hires fix, and two optional LoRAs. Each folder has the hand-written input graph, the canvas `*.ui.json` and API prompt `*.api.json` that `cwc compile` produced, and a README with the model source, licence and what was tested. Every file passes the `tools/workflow_policy.py` allowlist.

## Three tools

Since 2026-11-18 the three tools live here as folders of their own, each with its own README, licence, tests and CI. They do not call each other. The guard covers their folders.

| Tool | What it does | Language | Commands | Read |
|---|---|---|---|---|
| `cwc` | Compiles a ComfyUI API graph into a grouped, laid-out canvas with native reroutes, and checks that it exports the same prompt | Python, standard library only | `compile`, `render`, `guide`, `presets`, `node`, `learn` | [README](../cwc/README.md), [ARCHITECTURE](../cwc/docs/ARCHITECTURE.md) |
| `rdbg` | Runs PowerShell on a Windows host over the system `ssh`, free of local quoting and command-line length limits | Rust | `ps`, `doctor`, `comfy` | [README](../rdbg/README.md) |
| `artfetch` | Searches illustrations across sources, filters by completion, deduplicates across platforms, stages 1536 px JPEG sets | Rust | `status`, `resolve`, `probe`, `fetch`, `stage` | [README](../artfetch/README.md) |

The `cwc` pipeline takes authoring JSON through normalize and instantiate, or an existing canvas/PNG through ingest, then runs annotate, layout, route, notes, verify and emit — one folder each under `cwc/src/cwc/`. `cwc/tools/oracle/` measures node sizes and exports in a real ComfyUI frontend as the reference for the tests; `cwc/showcase/` has three worked examples; `cwc/skills/` teaches an agent to write API graphs.

## Companion ComfyUI nodes

ComfyUI custom node packs stay in standalone repositories rather than subfolders here so their repository root maps directly to `ComfyUI/custom_nodes/<pack>/` and keeps PyTorch/ComfyUI dependencies out of this repository's CI.

| Repository | What it does | Agent / CLI hook |
|---|---|---|
| [comfyui-blindbox-draft](https://github.com/lepetitprince716-prog/comfyui-blindbox-draft) | Local Midjourney-style Blind-Box Draft Mode for Anima (28-block): multi-prompt `micro_batch=4`, single `0–100` chaos knob, 4-role LoRA co-grouping, decoupled 32-tile fullscreen preview wall, Strict/Creative HD Enhance | `scripts/draft_cli.py` (`deal`, `draft`, `enhance`) |
| [comfyui-moss-accel](https://github.com/lepetitprince716-prog/comfyui-moss-accel) | Cuts MOSS-Image DiT forwards via guidance reuse and linear sigma extrapolation (`fast`, phased 50-step `fast_50` 2.05×, and `refine` presets) plus zero-commit Slim Qwen3.5-9B text encoder loaders (`Row-W8A16` 7.94 GB / `W4A8` 4.93 GB) | Drop-in MODEL & CLIP loader nodes + API/UI two-pass workflows |

## Guard

| Part | Job |
|---|---|
| [privacy_scan.py](../tools/privacy_scan.py) | Scans for LAN addresses, home paths, emails, token shapes and image-generation metadata; private rules stay outside the repo |
| `tools/secret_scan.sh` | Second scan for secrets, a wrapper around Betterleaks |
| [workflow_policy.py](../tools/workflow_policy.py) | Allowlist for `workflows/`: registered files, node types and model names only |
| `check` | `./check changed` while working, scans changes and runs the tests the paths select; `./check release` before publishing, read-only, maintainers only |
| `.githooks/` | pre-commit, commit-msg, pre-push; turn on with `git config core.hooksPath .githooks` after cloning |
| `tests/` | Tests for the guard itself |
| `.github/workflows/` | `privacy.yml` on every push and pull request; each tool's CI on pushes to `main` and pull requests when its folder changes; `cwc-sweeps.yml` on demand |

`kernel_classes.py` and `gemm_probe.py` in `tools/` are probes from the [Performance](en/07-performance.md) page, unrelated to the guard.

## How it fits together

The docs are for people and the skill is for agents; both carry the same rules. The skill learns the machine from `LOCAL.md`, dispatches with the task packets and subagents in `templates/`, and renders with the graphs in `workflows/`.

Each tool serves one step. `cwc` turns agent-written API graphs into canvases people can read, and `workflows/` is its output. `rdbg` handles the remote Windows render boxes in [Debugging](en/05-debugging.md). `artfetch` prepares training datasets for LoRA and style runs.

The guard covers every folder and runs on every commit and push.

## Where to start

| Goal | Start here |
|---|---|
| Understand the method | [Philosophy](en/00-philosophy.md), then the [setup table in the README](../README.md#what-is-inside) |
| Give your agent the method | [README · Use the skill](../README.md#use-the-skill), then fill in `LOCAL.md` |
| Set up tiered workers | [templates/agents/](../templates/agents/README.md), with [Dispatch](en/03-dispatch.md) |
| Drag a workflow into ComfyUI | `*.ui.json` in `workflows/` |
| Turn an API graph into a clean canvas | [cwc tutorial](../cwc/showcase/README.md) |
| Debug a remote Windows box | [rdbg](../rdbg/README.md), with [Debugging](en/05-debugging.md) |
| Build a training set | [artfetch](../artfetch/README.md) |
| Run 32-card Anima blind-box drafts in ComfyUI | [comfyui-blindbox-draft](https://github.com/lepetitprince716-prog/comfyui-blindbox-draft) |
| Speed up MOSS-Image sampling in ComfyUI | [comfyui-moss-accel](https://github.com/lepetitprince716-prog/comfyui-moss-accel) |
| Commit a change | Turn on the hooks and run `./check changed`; see [CONTRIBUTING](../CONTRIBUTING.md) |
| Check before publishing | `./check release` in [AGENTS.md](../AGENTS.md) |
| See what changed | [CHANGELOG](../CHANGELOG.md) |

The starter pack at the top of the README (`comfy_sweep.py`, two moss workflows, the `comfyui-zero-node-pilot` skill) is a download on the [v0.1.0 release page](https://github.com/lepetitprince716-prog/agent-genops/releases/tag/v0.1.0); it is not in the source tree.
