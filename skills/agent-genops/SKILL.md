---
name: agent-genops
description: Agent-first method for running, debugging, deploying and benchmarking local generative image and video models (ComfyUI boxes, sidecar instances) and routing work to cloud services (NovelAI, Midjourney, Civitai, GPT Image). Use when bringing up a new model or ComfyUI runtime, fixing a broken graph or a remote GPU box, planning or running a batch render, A/B-testing speed or quality, managing model/LoRA/recipe inventory, choosing a provider, delegating any of this to subagents or worker agents, or recording what was learned. Triggers include 部署模型, 上新模型, 接入新模型, 调试工作流, 出图慢, 批量出图, 测速, A/B, 盘点 LoRA, 选哪个服务出图, 派工, bring up a model, debug ComfyUI, batch render, benchmark. Not for writing a single creative prompt (use the provider's own skill) or for UI work.
license: MIT
---

# agent-genops

The agent platform is the control plane. You plan, dispatch, verify and record. ComfyUI boxes
and cloud services only render. Never design work inside the ComfyUI canvas, and never queue a
job from a canvas tool.

## Start here

1. If `~/.config/agent-genops/LOCAL.md` exists, read it first. It maps the roles in this skill
   (intent router, MCP server, boxes, ledgers, gallery, task tracker, worker launcher) to this
   machine's real commands. Its facts beat the defaults below.
2. If it does not exist, find the project's own entry points (an intent router CLI, an MCP
   server, a script catalogue, runbooks) before writing anything. Do not invent commands.
3. Treat every state note you read (memory, STATE files, handoffs) as a dated snapshot. Check
   it against git or the live machine before you rely on it.

## The loop (every job)

| Step | Do | Stop if |
|---|---|---|
| Intake | Write down what this step must prove and what counts as done. | You cannot say it in one sentence. |
| Inventory | Look up existing scripts, recipes, models, earlier results and runbooks. | You are about to hand-write something that exists. |
| Plan | Produce the command or plan in print mode. Size the run: time per image x count. | The run exceeds 30 minutes of GPU and nobody approved it. |
| Probe | Check the box: reachable through its queue endpoint, models and nodes present, queue idle, owner not using it. | Busy or unknown: HOLD, report, offer the other box. |
| Smoke | Render one image with the exact batch command. Check time, output path, file names. | Names collide, path is wrong, time is off. |
| Run | Release the batch with outputs isolated per job. Keep the queue stoppable as a process tree. | A failure: stop, keep the evidence, no auto-retry with new seeds. |
| Verify | Open the artifacts. Compare against the intake. Machines may only reject. | A taste question: send it to the owner. |
| Record | Ledger rows, model card, memory note with a date, incident rule if something broke. | Ledger rows do not match files. |
| Clean | Delete test renders on both sides. On Windows move to a dated trash folder on the same disk. | You are about to delete datasets, checkpoints or models. |

## Hard rules

- One smoke image before any batch of three or more.
- Pick the engine by what the step must prove: base pass for probes, quality stack for finals.
- An exit code, a receipt or a worker's report is a claim. The file on disk is the evidence.
- Paid renders: quote first, stay inside the standing caps, write a ledger row per image, pass
  the resume flag, reconcile afterwards. A cap is a ceiling, not a target.
- Scalar aesthetic scores filter, they never rank. Review agents rank, they never crown.
- Measure before tuning. A/B uses an explicit off arm, at least three seeds and warm runs.
  Change the biggest lever first. Quality tiers are judged by the owner.
- Never route around a gate, a hook or a permission. A denied call did not run. Fix the command
  shape once; then hand the owner one runnable, idempotent command.
- Secrets never go into argv, logs, job environments or this repo.
- Say which facts are measured, which are assumed and which are unverified.
- Keep the lesson, delete the test images.

## Where to read next

| Situation | Read |
|---|---|
| How the planes and entry points fit together | `references/architecture.md` |
| Deciding whether and to whom to delegate; writing a task packet; accepting results | `references/dispatch.md` |
| Adopting a new model, LoRA family or ComfyUI runtime | `references/model-bringup.md` |
| Something fails, hangs, OOMs or renders wrong | `references/debug.md` |
| Remote Windows GPU box: PowerShell, cmd.exe, services, cleanup | `references/windows-gpu-box.md` |
| Planning or running renders | `references/render-discipline.md` |
| Speed or quality comparison | `references/perf-ab.md` |
| Models, LoRAs, recipes, outputs, archives, ledgers | `references/inventory.md` |
| Choosing between local boxes, NovelAI, Midjourney, Civitai, GPT Image | `references/providers.md` |
| Writing or delegating prompts per model family | `references/prompt-rules.md` |
| Showing results and collecting verdicts | `references/review-loop.md` |
| Network, gates, secrets, public versus private material | `references/safety.md` |
| Memory, handoffs, successor sessions, task tracker | `references/continuity.md` |

## Delegation at a glance

Keep single-chain work in the root session. Delegate only to fan out or to keep large reads out
of the root's context. Give each job to the lowest tier whose failure you can still catch.

| Job | Tier |
|---|---|
| Bulk reading, extraction, classification, log digests, run-and-report | Haiku worker |
| Research that combines sources; messy extraction; retry after a Haiku miss | Sonnet worker |
| Ordinary implementation, debugging, investigation | Opus worker, medium |
| Multi-file work, design judgment, contracts | Opus worker, high |
| Code for a settled design; long tuning with a clear goal | Sonnet worker, max |
| Plan review before execution | Plan reviewer |
| Claims about code, tests, libraries before commit or report | Fact checker |
| Parallel lanes on other vendors' models | Terminal-multiplexer workers |

Every packet states: objective, owned paths, context paths, non-goals, allowed commands,
acceptance checks, and where to write a short result. Workers never delegate further.

## Stop and ask the owner

- Anything irreversible or visible outside this machine: deleting originals, publishing,
  posting, pushing to a protected branch, spending beyond the standing budget.
- Taste verdicts, quality tiers, and direction forks.
- GPU work on the owner's personal machine while they are using it.
- Accepting a gated model licence or logging in to a service.

## Report

Conclusion first. Then numbers as numbers, exact paths and commands, what failed, what is still
unverified. Bad news is never trimmed to save space.
