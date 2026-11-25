# Dispatch: choosing a worker, writing the packet, accepting the result

Read when: about to hand work to a subagent or an external worker, running parallel lanes, or
accepting a delegated result.

## 1. Delegate or not

| Situation | Action |
|---|---|
| Finishable in a few tool calls | Do it in the root |
| Answer is a fact (path, symbol, value) | Read or grep it yourself |
| Independent lanes that can run at once | Fan out |
| A large read would flood the root's context | Delegate the read, take back a digest |
| Same task failed twice with the same shape | Stop; re-inventory tools and docs before any third attempt |

## 2. Pick the tier

Rule: the lowest rung whose failure you can still catch. Pick it yourself. If the owner names a
model and effort, use exactly that; if no definition exists, copy a sibling definition, change
`name` and `effort`, wait for it to load. Never substitute.

| Work | Tier |
|---|---|
| Bulk read, extract, classify, grep sweep, convert, log digest, run-and-report | haiku-worker |
| Research with synthesis, messy extraction, diagnose a failing run, retry of a failed Haiku result | sonnet-worker |
| Ordinary implementation, debugging, investigation, default when unsure | opus-worker-medium |
| Multi-file implementation, design judgment, contract-bound lane | opus-worker-high |
| Code against a settled design; long optimisation with clear goal and directions | sonnet-worker-max |
| Review a draft plan before leaving plan mode | plan-reviewer |
| Verify claims before a commit or a user-facing summary | fact-checker |

The tier names are the agent files in the repo's `templates/agents/`. With another agent, its
README gives each role a small, mid or large model, an effort and an access level.

Never:
- Haiku: coding chains, design, debugging, security-adjacent work, web research.
- Any worker: calling the advisor tool, delegating further.
- Workflow fan-outs: an agent call without an explicit non-strongest model.
- Haiku packet over about 200K tokens of context. Split instead.

## 3. External workers (herdr)

| Worker | Settings | Use |
|---|---|---|
| Cursor Composer 2.5 | no effort flag | default for coding, review, research, second opinions |
| DeepSeek through pi | effort always set; skills disabled | bulk and mechanical lanes, off-peak only |
| OpenCode Go through pi | effort always set | DeepSeek substitute in peak hours or on failure |
| Grok | paused | do not dispatch |
| Claude models | n/a | never through the multiplexer; use subagents |

- pi effort: `low` run-and-report, extract, reformat; `medium` default; `high` debugging, multi-file
  reasoning, design review. Never `xhigh` or `max` for DeepSeek. Unset means max.
- DeepSeek peak (as of 2026-09-27): weekdays 01:00-04:00 and 06:00-10:00 UTC. Check before each spawn.
- If the session's shell is sandboxed, never launch a worker CLI from it: the worker dies in a
  nested sandbox (exit 71 in the reference setup). Use a multiplexer that runs workers outside the
  sandbox; with none, run the lane in the root.
- Long job: spawn without wait, then `wait`; a `timeout` status is normal, call `wait` again unchanged.
- After changing a running worker's instructions, read the pane and check its real file activity a
  minute later. "Submitted" may mean "queued".
- Never call a pane read without a line limit.
- Close every workspace the task spawned.

## 4. Write the packet

```text
TASK_PACKET
objective: one concrete outcome
owned_paths: exact write scope, or read-only
context_paths: files allowed for context
non_goals: owner's red lines (no git / no install / no network changes ...)
allowed_commands: bounded list
acceptance: exact checks and evidence to return
return: write RESULT (<=30 lines: status, paths, exits, evidence, risks) to RESULT_FILE=<abs path>, then reply DONE
no child delegation; do not revert other work
```

Also:
- State "you are the executor; do not wait for other agents".
- For research lanes: state the question, require parallel backends, primary sources, a dated
  source list, and no "does not exist" from a single miss.
- For runner lanes: print mode first; relay asset errors verbatim and stop; open every reported
  path; report shortfalls; no creative or parameter decisions.
- For large executor briefs: use the skeleton in `templates/task-packet.md`, pin line numbers to a
  named commit, and have the executor's tool pre-read the brief read-only before delivery.
- To continue work, start a fresh agent with an explicit model. Do not message a finished subagent.

## 5. Accept the result

1. Read `RESULT_FILE`. Fallbacks: last assistant message in the session log, then the last 40 lines
   of the pane.
2. Open every path the result names.
3. Re-run or re-read every number. Note the counting domain of each count.
4. Check every acceptance item has real output.
5. Haiku result failed the check: re-dispatch to sonnet-worker.
6. Test PRs: one reviewer must ask, per assertion, "would this fail if the code broke?"
7. Before commit or summary: run fact-checker over claims.
8. List unverified items as unverified in your own report.

Status words: `done` is settled. `unknown` is not finished.

## 6. Parallel lanes

- One worktree per writer lane. Read-only lanes may share a checkout.
- At most three multiplexer workers at once. Run the two-lane preflight before scheduling writers.
- Same-file edits: each lane writes a fragment (full insert text plus a content anchor, no line
  numbers). Integrate serially in the root. Run contract tests after each integration.
- Before touching the main checkout: list live sessions and check transcript activity. A pane
  marked done may still belong to a live session.
- Before deleting a worktree: porcelain status, ref search for key files, scan untracked files
  against the main checkout, copy missing ones back, verify, then remove.
- Remove a leftover subagent worktree before creating one on the same branch. Abort on `cd` failure.
- Two queues never write to the same result directory.

## 7. Research before build

1. Inventory: MCP servers and plugins, local CLIs, project facilities, runtime versions. Cache 7 days.
2. Install tiers: project-local and reversible, install and report; global, give the command and
   stop; credentials, name the variable and its source, never guess.
3. Remix tier: skip (string, parameter, located bug); light (single file, no new dependency, one
   quick search, one-line report); full (new module, dependency or architecture). Unsure: heavier.
4. Full tier scoring: fit x3 + maintenance x2 + dependency weight x2 + readability x2 + maturity x1
   (max 50). Fit < 3 eliminates. Stars are not a score. License problems veto; do not read GPL/AGPL
   source from vetoed candidates.
5. Full tier: stop and show the comparison table, recommendation and architecture sketch before
   writing code.
6. Register vendored or rewritten code: URL, commit, license, scope, modifications.

## 8. Stop conditions

- A gate, permission or policy denies a call: stop that item, report it, hand the owner one
  runnable command. Do not route around it.
- A worker hangs (session log not growing for about 10 minutes): kill its process group; if the
  wanted output is a fact, get it by reading instead of restarting.
- The executor's environment looks inconsistent (same commit under two hashes, partial writes):
  stop, no commit, leave a handoff.

## 9. Report to the owner

Worker (kind, model, effort), status, RESULT summary, evidence paths, unverified items. At most
20 lines.
