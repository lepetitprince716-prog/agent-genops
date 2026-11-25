English | [中文](../zh/03-dispatch.md)

# Dispatch: who does the work, and how the root accepts it

This page answers four questions. When should the root session hand work to another agent at all?
Which agent gets which kind of work? What goes into the packet? And how does the root decide the
result is real?

> **TL;DR**
> - Single-chain work stays in the root. Delegate only to fan out or to keep large reads out of the root's context.
> - Pick the lowest tier whose failure the root can still catch. Haiku for checkable bulk work, Opus medium as the default, Opus high for contracts.
> - Every worker gets a packet: one objective, owned paths, non-goals, allowed commands, acceptance checks, a RESULT file.
> - A worker's report is not acceptance. The root re-reads artifacts and re-runs the numbers.
> - Parallel writers each get their own worktree. Integration into shared files is serial and done by the root.

## When not to delegate

The root plans, dispatches, verifies and records. It does not hand off work it can finish in a few
tool calls.

1. **Work the root can finish in a few tool calls stays in the root.**
   Why: a worker costs a packet, a cold start and an acceptance pass, and it starts without the
   root's context. On single-chain work that cost buys nothing.
2. **Delegate for two reasons only: to fan out independent lanes, or to keep a large read out of the root's context.**
   Why: owner's decision since 2026-07-26 (threshold-style delegation). The root's context is the
   scarcest resource in a long session.
3. **Fact questions are answered by reading, not by agents.**
   Why: in one acceptance round, a second-tool pre-read hung (its session log stopped at 2.5 KB with
   no growth for 10 minutes). The root read the code directly and found the misclassified script.
   When the output you want is a fact ("does this symbol exist"), grep beats restarting a flaky agent.
4. **Two failures of the same shape send you back to inventory, not to a third attempt.**
   Why: the usual cause is a missing tool or an unread doc, not a coding error (owner's decision,
   2026-08-27).

## The tier ladder

Rule: choose the lowest rung whose failure the root can still catch. The root picks the tier without
waiting to be told. When I name a model and effort, dispatch exactly that; if no agent
definition matches, add one (copy a sibling, change name and effort) and wait for it to load.

| Tier | Model / effort | Gets | Never gets |
|---|---|---|---|
| haiku-worker | Haiku 5.5 / medium | bulk reading and summarising, extraction, classification, grep and inventory sweeps, format conversion, log digests, run-and-report, waiting on a multiplexer worker | multi-step coding, design calls, debugging, security-adjacent work, web research |
| sonnet-worker | Sonnet 5.5 / high | research lanes that synthesise sources, messy extraction, run-and-report that must diagnose failures, the retry when a Haiku result fails the check | ordinary implementation (that goes to Opus medium) |
| opus-worker-medium | Opus 5.5 / medium | the default: ordinary implementation, debugging, investigation, parallel lanes | nothing by rule; move up when the lane carries a contract |
| opus-worker-high | Opus 5.5 / high | multi-file implementation, design judgment, lanes with a contract to get right | mechanical work (waste) |
| sonnet-worker-max | Sonnet 5.5 / max | code once Opus or the root has settled the design; long optimisation with a clear goal and given directions | open-ended design, vague goals; it stops and reports when the design proves wrong |
| plan-reviewer | Opus 5.5 / medium, read-only | independent review of a draft plan: gaps, unverified assumptions, hard points, with `file:line` | writing code or editing files |
| fact-checker | Sonnet 5.5, read-only | claims about what code does, what tests passed, what a library supports, before a commit or a summary | making claims of its own |

Ready-made definitions are in [`templates/agents/`](../../templates/agents/). Its
[README](../../templates/agents/README.md) maps each role to a model size for agents other than
Claude Code.

5. **Haiku output is always verified by the root before use, and each Haiku packet stays under about 200K tokens of context.**
   Why: Haiku compacts near 200K, and prompts over 100K cost five times as much on API billing
   (2026-10-09). On 2026-10-19 a Haiku subagent copied only 1,643 of about 20,000 base64 characters,
   three times in a row. The root now pushes such payloads itself in chunks with hash checks.
6. **Haiku never gets security-adjacent work.**
   Why: its safety classifiers refuse with no fallback, and the refusal ends the lane.
7. **Research lanes go to Sonnet, not Haiku.**
   Why: on 2026-10-08, three of four Haiku research lanes went off task.
8. **Workers never call the advisor tool and never delegate further.**
   Why: the advisor inherits the strongest model and reads the worker's whole transcript. Measured
   once: 7.7 minutes and 102k tokens to find redundancy in two text sections. Grandchild agents also
   escape the root's tier choice.
9. **Workflow-style fan-outs name a non-strongest model on every agent call.**
   Why: a literature re-check workflow burned quota on 2026-10-15 because its agents inherited the
   session's strongest model.
10. **Run plan-reviewer before leaving plan mode, and fact-checker before a commit or a user-facing summary.**
    Why: owner's decision (plan review since 2026-09-22). An independent review of one plan found nine
    defects; all nine held up, and I re-checked five of them directly at the source.

## External workers through herdr

herdr is a terminal multiplexer for coding agents. The root drives it to run agents from other
vendors. Claude models never go through it: they run only as subagents of the root.

| Worker | Use | Notes |
|---|---|---|
| Cursor Composer 2.5 | default: coding and edit lanes, judgment, review, research, second opinions | no effort flag; effort is encoded in the model id |
| DeepSeek through pi | bulk and mechanical lanes, scripted edits, data collection | off-peak only; always set effort |
| OpenCode Go through pi | DeepSeek substitute in DeepSeek peak hours or when it fails | separate quota |
| Grok | paused since 2026-10-13 until I say otherwise | do not dispatch |

11. **Always pass `effort` to pi workers: low for run-and-report, medium as the default, high for debugging and design review. Never xhigh or max for DeepSeek.**
    Why: an unset effort means max, the most hallucination-prone level.
12. **Check DeepSeek peak hours before every spawn and switch to OpenCode Go in peak.**
    Why: the vendor's pricing page (read 2026-09-27) lists weekday peaks at 01:00-04:00 and
    06:00-10:00 UTC, with the price doubled.
13. **If the coding session's shell is sandboxed, never start a worker CLI from it.**
    Why: on 2026-08-04 a worker launched that way died with a nested-sandbox exit 71. The multiplexer
    service runs workers outside the session sandbox. With no sandbox this failure does not apply;
    with a sandbox and no multiplexer, run the lane in the root.
14. **After changing a running worker's instructions, check its real file activity a minute later.**
    Why: on 2026-09-20 three corrections sat queued in a pane and never reached the agent. About 4 GB
    were downloaded for nothing. "Submitted" can mean "queued".
15. **Close every workspace the task spawned.**
    Why: owner's decision; no single incident behind it.

## The task packet

Every worker, Claude or not, gets the same packet shape. The full template is
[`templates/task-packet.md`](../../templates/task-packet.md).

```text
TASK_PACKET
objective: one concrete outcome
owned_paths: exact write scope, or read-only
context_paths: files allowed for context
non_goals: my red lines (no git / no install / no network changes ...)
allowed_commands: bounded list
acceptance: exact checks and the evidence to return
return: write RESULT (<=30 lines: status, paths, exit codes, evidence, risks) to RESULT_FILE=<abs path>, then reply DONE
no child delegation; do not revert other work
```

16. **Say "you are the executor" in the packet.**
    Why: local re-verification agents repeatedly idled because they assumed another background agent
    was doing the work.
17. **Start a fresh agent with an explicit model instead of messaging a finished one.**
    Why: continuing a finished subagent by message drops its model override; it inherits the
    session's model.
18. **Large briefs for executors follow a fixed skeleton and get a read-only pre-read by the executor's own tool before delivery.**
    Why: pre-reads caught 3 P1 findings on one refactor brief, 1 P1 plus 5 P2 on the next, and
    3 P1 plus 7 P2 on a tests-only brief. Each would have misled the executor.
19. **Delegated runners execute; the dispatcher keeps every creative and parameter call.**
    Why: owner's decision, written into every runner runbook. Outfit, LoRA weight, adapter strength and the final
    pick stay with the dispatcher. The runbooks also say: print mode first, relay asset errors verbatim and stop, open every
    reported path, report shortfalls honestly.

## Acceptance by the root

20. **A worker's self-report is not acceptance.**
    Why: owner's decision. Numbers are checked against artifacts or a re-run. `done` means settled;
    `unknown` does not mean finished.
21. **Read the RESULT file, not the terminal.**
    Why: terminal output carries startup banners and wastes context. Fallbacks in order: the last
    assistant message from the session log, then a bounded read of the last 40 lines.
22. **A failed Haiku check is retried on Sonnet, not re-asked of Haiku.**
    Why: owner's decision; no single incident behind it.
23. **Test PRs get one reviewer with a mutation viewpoint.**
    Why: see the worked example below. "The assertion is correct" is the pass line. "A broken
    implementation would fail this test" is the value.

Acceptance checklist:

- [ ] RESULT file exists and is under 30 lines.
- [ ] Every path in it exists and was opened by the root.
- [ ] Every number in it was re-run or read from the artifact.
- [ ] Every acceptance check from the packet has real output, not a claim.
- [ ] Unverified items are listed as unverified.
- [ ] Workspaces closed; worktrees kept unless I asked to remove them.

## Parallel lanes without collisions

24. **One worktree per writer lane. Read-only lanes may share a checkout.**
    Why: on 2026-09-16 a dirty main checkout with 55 changed files was taken for orphaned work,
    committed as WIP and switched. It belonged to a live session whose pane said "done".
25. **Cap the multiplexer at three workers and run a two-lane preflight before scheduling writers.**
    Why: owner's decision. The preflight refuses lanes whose worktrees or panes overlap.
26. **When several lanes must change one file, each lane writes a fragment file; the root integrates serially.**
    Why: owner's decision. A fragment holds the full insert text plus a content anchor, never line
    numbers. Contract tests run after each integration.
27. **Before deleting a worktree, scan it for work that never reached a branch.**
    Why: on 2026-08-16 one worktree held a whole 3D line (16 modified files, 10 test files, a toolchain)
    that had never reached any branch, and another held 255 MB of analysis outputs with no copy in the
    main checkout.
28. **Remove a subagent's leftover worktree before creating your own on the same branch, and abort when `cd` fails.**
    Why: in one acceptance run, `worktree add` failed on residue, `cd` failed silently, and the checks
    ran in the main checkout and produced a false result.

## Research before build

29. **Before writing code, inventory what already exists: MCP servers and plugins, local CLIs, project facilities, runtime versions.**
    Why: hand-written implementation is the last resort. The inventory is cached for seven days.
30. **Then search open source at the tier the change needs.**
    Why: owner's decision. Tiers are: skip (a string, a parameter, an already-located bug), light (single
    file, no new dependency: one quick search, a one-line report, then build), full (new module,
    dependency or architecture). When unsure, go heavier.
31. **Full-tier candidates are scored and the comparison is shown before code is written.**
    Why: owner's decision. Score = fit x3 + maintenance x2 + dependency weight x2 + readability x2 +
    maturity x1, out of 50. Fit below 3 eliminates. Stars are not a score. A license problem is a
    veto, and GPL/AGPL source from a vetoed candidate is not read into context.

Install tiers during inventory: project-local and reversible installs go ahead and get reported;
global packages get the exact command and a stop; anything with credentials gets the variable name
and where to obtain it, never a guess.

## Worked example: a tests-only lane, end to end

A planning root wanted direct unit tests for the core decision logic of five modules, with zero
source changes. This is how the lane ran.

1. Fact base. Two read-only Sonnet subagents listed file, line, signature and branch behavior for
   each target, "pure facts, no refactoring advice". Their lists cross-checked each other, and the
   root read the code itself to confirm.
2. Scope ruling. The root decided per item what to pin and what to exclude, with a reason each.
3. Brief. Fixed skeleton: position and prerequisites, background facts with line numbers pinned to
   a named main commit, task list T0 (fact gate) to Tn, acceptance commands, PR requirements.
   Acceptance included "the diff of source directories is empty".
4. Pre-read. The executor's own tool read the brief in read-only mode first and found 3 P1 and
   7 P2 problems. The root fixed them before delivery.
5. Execution. An external coding agent ran headless with a workspace-write sandbox, opened a PR and
   did not merge it.
6. Deterministic checks by the root: CI green, test count delta explainable, PR body carrying all
   required evidence, every review comment dispositioned.
7. Triangulation. Three reviewers in parallel, each with a named model: compliance against the
   brief (Sonnet), a local re-run of tests and lint (Sonnet), and a read-only review by a second
   tool.
8. Result. Both Claude reviewers ran the tests green, compared assertions with the source and said
   CLEAN. The second tool asked a different question, "would this test fail if the code broke?",
   and found six loose assertions: a tail-only argv check, membership instead of adjacency, a
   missed branch, a set-membership check that a constant `[0]` would pass, a missed key, `>=`
   instead of an exact count.
9. Fix and rule. A subagent in an isolated worktree tightened the assertions. The mutation-viewpoint
   review became mandatory for test PRs. On the next tests-only PR it caught three more.

One trap from the same lane: the executor reported the test count as 220 to 265 for `tests/` only,
the root as 291 to 336 for the full suite. Both were right. Write down which counting domain an
acceptance number uses.

## Real cases

- 2026-08-04: a worker started from the session shell hit a nested sandbox, exit 71. Rule 13.
- 2026-09-16: a live session's dirty checkout was taken for orphaned work. Rule 24.
- 2026-09-20: three queued corrections never reached a worker; about 4 GB downloaded for nothing. Rule 14.
- 2026-10-08: three of four Haiku research lanes went off task. Rule 7.
- 2026-10-15: a workflow's agents inherited the strongest model and burned quota. Rule 9.
- 2026-10-19: a Haiku worker truncated a base64 payload three times. Rule 5.
- Tests-only lane (date not recorded): two same-family reviewers passed six weak assertions. Rule 23.

## Tried and dropped

- Devin as a worker or reviewer: retired 2026-09-27.
- Grok as the default external worker (from 2026-09-29): paused 2026-10-13.
- A Sonnet medium tier: removed in the 2026-10-20 audit; Sonnet runs at high or max.
- Haiku for web research: dropped 2026-10-08.
- OpenCode's own CLI for DeepSeek: it has no effort flag and runs DeepSeek at max. Use pi.
- Same-family triangulation for test PRs: it missed what a second tool caught.

## See also

- [12-continuity.md](12-continuity.md): handoffs, memory, the shared task tracker.
- [06-render-discipline.md](06-render-discipline.md): smoke before batch, for runner lanes.
- [11-safety-and-privacy.md](11-safety-and-privacy.md): gates a worker must not route around.
- [`templates/task-packet.md`](../../templates/task-packet.md), [`templates/agents/`](../../templates/agents/).
