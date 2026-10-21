# Philosophy

English | [中文](../zh/00-philosophy.md)

These are the working principles behind every other page in this repo. Each one came from a
measurement, an incident or a standing decision, and the reason sits next to the rule. When a
later page seems to disagree with this one, the later page is wrong and should be fixed.

> **TL;DR**
> - Agents plan, dispatch, verify and record. ComfyUI and the cloud services only render.
> - The live machine and the artifact on disk are the truth. Documents, exit codes and
>   self-reports are claims.
> - GPU time, paid credits and the owner's attention are the scarce resources.
> - Machines eliminate candidates. Taste is decided by a person.
> - Write down what was measured, what was assumed and what is still unverified. Keep the
>   lesson, delete the test images.

## 1. Where the work lives

1. **The agent platform is the control plane; backends only render.**
   Why: every caller (web app, chat, MCP tools, CLI) goes through one execution chain, so
   recipes and resource rules are never forked per front end. Tools that read the ComfyUI
   canvas may inspect and patch the graph the owner has open, but they never queue a job.
   Designing work inside the canvas would put the method where no agent can test, diff or
   review it.

2. **One authority per fact, and thin entry points.**
   Why: duplicated documents drift. The repo-level agent file only declares read order and
   boundaries. Each domain has one authority file. Recipes are registered once and consumers
   pass only the name. A script registry tells agents what already exists, and CI rejects a
   new script that is not registered.

3. **Plan by default, run on purpose.**
   Why: routers print the command or plan and need an explicit `--run`. A read-only HOLD
   check (service reachable, nodes and model files visible, queue idle) runs before any GPU
   work, and "unknown" counts as busy. Planning, previews and packet preparation are not
   permission to generate.

4. **Different backends stay separate adapters.**
   Why: prompt dialect, runtime, cost and media semantics differ between a local Anima line,
   NovelAI, Midjourney and a video model. Folding them into one generic planner was rejected,
   and abstractions wait for the second real use.

## 2. Truth and evidence

5. **The live machine beats any document.**
   Why: a box is checked through its queue endpoint, never by ping (ICMP is firewalled, and
   the system-stats endpoint once returned 500 while the queue was healthy). Checkpoint names
   come from the live server, not from a local index that lags by a generation. Several
   "findings" about a washed-out VAE turned out to be a denoise bug; the fix was to read the
   graph that was actually submitted instead of the source defaults.

6. **An artifact is evidence; an exit code is not.**
   Why: a plan, a queued job, a generated file, a QC pass, a reviewed keeper and a released
   image are different states. A successful spawn receipt once hid that the upstream never got
   the request (2026-08-23). Acceptance checks open the file.

7. **Say what was measured, what was assumed and what is unverified.**
   Why: measurements do not travel. An attention kernel worth 1.30x on one model was worth 5-7%
   on another. Community prompt rules were rejected by our own rounds. Prompt effects are
   reported as counts out of N seeds, and untested ideas are labelled as hypotheses.

8. **Machines eliminate; a person judges taste.**
   Why: a collapsed face shape passed every automatic gate (10/10 identity score, zero QC
   flags) and only the owner's eye caught it. Scalar aesthetic scores ranked the bland
   baseline above the artistic candidates. An agent once called 8 sampling steps usable when
   the owner's floor was 16, which doubled every payback estimate. Agents judge objective
   defects; review agents rank, they never crown.

## 3. Scarce resources

9. **One smoke image before any batch of three or more.**
   Why: on 2026-09-16 three avoidable mistakes in one probe round wasted about 40 minutes of
   GPU time and pushed the schedule back by about an hour. The smoke image checks time per
   image, where files land, and whether names collide.

10. **Pick the engine by what the step has to prove.**
    Why: style and composition probes need a single-pass base image (tens of seconds). The
    upscale and detailer stack takes minutes per image and is for finals only.

11. **The render box is someone's computer.**
    Why: the main render box is also the owner's gaming PC. The router probes it first and
    falls back to the second box when it is busy or a game is running. No 4x model upscales
    while the owner may be playing, because the shared GPU runs out of memory.

12. **Budgets are gates that fail closed, and a cap is not a target.**
    Why: paid Civitai renders take a free quote first, stop above 30 Buzz per call or 150 per
    day, and write a ledger row per image. A pasted paid command that ran twice cost 257 Buzz
    (2026-09-05). A proposed 2000 Buzz ceiling was cut to 500. Cloud rounds are sized by how
    many images a verdict needs.

13. **Measure before tuning, and change the biggest lever first.**
    Why: the same recipe varied 24% in render time across seeds, so a single-sample A/B
    cannot resolve differences under about 20%. Every toggle gets an explicit "off" arm. The
    same attention kernel was worth 5-7% before a quantization change and 14-21% after it.

## 4. Agents and dispatch

14. **Delegate to fan out or to protect the root's context, never by reflex.**
    Why: on single-chain work, running the same model at lower effort beat adding a worker.
    Each job goes to the lowest model tier whose failure the root can still catch. Three of four Haiku
    research lanes drifted off task (2026-10-08), so research lanes go to Sonnet.

15. **A worker's self-report is not acceptance.**
    Why: the root re-runs the numbers and reads the result file. It also checks what the
    worker actually wrote: three corrections queued to a busy worker never arrived, and about
    4 GB were downloaded for nothing (2026-09-20).

16. **Research before building; two failures mean re-inventory.**
    Why: repeated failure usually comes from a missing tool or an unread document, not from a
    coding mistake. Hand-written code is the last resort, after the existing CLIs, libraries
    and open-source projects have been checked.

17. **Never route around a gate. When blocked, hand over one runnable command.**
    Why: a denied call never ran. The agent fixes the command shape once; if that fails, it
    gives the owner a single idempotent command that backs up what it overwrites, was tried on
    a copy first, and says which parts stayed unverified.

## 5. Memory and honesty

18. **Memory is a dated snapshot, not a fact.**
    Why: notes go stale. Findings recorded on ComfyUI 0.33 were not re-checked on 0.42. Every
    state note carries a date and is compared with git or the live machine before use. Memory
    files hold one fact each and are audited for duplicates and dead links.

19. **Keep the lesson, delete the test images.**
    Why: throwaway renders filled the disks on both sides. Test renders are deleted by
    default, and keeping one needs an explicit reason. On Windows, the recycle-bin API called
    over SSH turned out to delete permanently (2026-10-13), so files move to a dated trash
    folder on the same disk and the owner empties it.

20. **Quality first; "all" means all.**
    Why: standing rule. A visual acceptance pass covers every unit, not a sample.

21. **Conclusion first, and bad news is never trimmed.**
    Why: long reports do not get read, so length is a hard limit. When a report must shrink,
    explanations go first; failures, numbers and exact commands stay.

## 6. Creative work

22. **Concept before prompt.**
    Why: if what the picture should do to the viewer cannot be said in one sentence, there is
    nothing to generate yet.

23. **Do not tailor the aesthetic to the model.**
    Why: what a model cannot do is recorded as a discount on that model, and the scene is not
    rewritten to fit its strengths.

24. **Never trust text from an image model.**
    Why: generated lettering is a standing failure. Images are generated without text, and
    text is added afterwards by code or a dedicated model.

## How the rules changed

The rules above are the current state. These are the larger revisions and what forced them.

| Before | Now | What forced it |
|---|---|---|
| Confirm every paid render | Standing budget: quote, cap, ledger, resume flag | Owner decision (2026-09-30); the provider has no server-side cap for API keys, so the client enforces one |
| `POST /free` after every render | The router leases VRAM and an idle reaper frees it | Each free cost a 1.9 s round trip and evicted the loaded weights |
| Three MCP servers registered per agent | One MCP server every agent can use | Per-agent registration never got done, so the tools sat unused (2026-09-16) |
| Per-image verdict sessions | One triage batch per round; decisions go to an inbox | One evening judged the same scene 58 times (2026-09-05) |
| Bare-model comparison grids | One image per new model, with the usual LoRA stack | A 24-cell bare grid told the owner nothing (2026-09-15) |
| One default worker model | A tier ladder from Haiku to Opus high, plus Sonnet max for settled designs | Haiku drifted on research lanes; the rule became "the lowest tier whose failure the root can still catch" |
| A pull request per small change | Commit locally, push and review per stage | Each small PR cost five or six network calls plus a review round (2026-09-01) |

## Guardrails and what enforces them

| Guardrail | Enforced by |
|---|---|
| HOLD before GPU work | Router probe, non-zero exit when the box is busy or unknown |
| Smoke before a batch of three or more | Runbook step; the batch is released only after the smoke checks pass |
| Paid renders stay inside the budget | Client-side gate that fails closed, plus a ledger reconciled after each run |
| Workers cannot delegate further or call the advisor | Shared footer in every subagent definition |
| No secrets in job environments | The job runner passes an allow-list of variables |
| No private data in this repo | `tools/privacy_scan.py` in git hooks and CI |
| One authority per fact | Script registry and CI ratchet in the private studio repo |

## See also

- [01-architecture.md](01-architecture.md): how the two planes are wired
- [03-dispatch.md](03-dispatch.md): the tier ladder and task packets
- [13-lessons.md](13-lessons.md): the incidents behind these rules
