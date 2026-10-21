# Task packet templates

Three shapes, smallest first. Copy the one that fits, delete the comments. See
`docs/en/03-dispatch.md` for when to use each.

## 1. TASK_PACKET (any worker: subagent or external)

```text
TASK_PACKET
objective: <one concrete outcome, testable>
you are the executor: do not wait for other agents; do not spawn sub-agents
owned_paths: <exact files or directories you may write; or "read-only">
context_paths: <files you may read for context>
baseline: <commit hash that line numbers refer to, if any>
non_goals: <red lines: no git, no install, no network or system changes, no edits outside owned_paths>
allowed_commands: <bounded list, e.g. "pytest tests/x", "ruff check scripts/">
acceptance:
  - <exact check 1 and the evidence to return>
  - <exact check 2>
budgets: <time, tool calls, money; omit if none>
return: write RESULT (<=30 lines: status, paths, exit codes, evidence, risks, unverified items)
        to RESULT_FILE=<absolute path>, then reply DONE
no child delegation; do not revert other work
on a blocker (permission, gate, missing file, question the packet does not answer):
  stop that item and report what blocked you, what you tried, what you need
```

Research lane addition:

```text
question: <the exact question>
method: parallel search backends; primary sources for every number, date, version or price;
        dated source list; "not found in <sources>" instead of "does not exist" after one miss
```

## 2. Executor brief (a self-contained change delivered as a PR)

Use when an external coding agent will run a whole change with zero context from the planning
session. Have the executor's own tool pre-read this brief in read-only mode before delivery.

~~~markdown
# <ID>: <title>

## Position and prerequisites
- Branch: <name>, from main at <hash>
- Merged prerequisites: <PRs>
- Forbidden files: <e.g. CI workflow files if the executor's token cannot push them>

## Background facts (line numbers at main@<hash>)
- <file:line - signature - behavior that matters>
- Excluded items and why: <item - reason>

## Contract-loosening policy (only if anything may change)
- May converge: <message wording, timeouts ...>
- Must stay byte-identical: <exit codes, output paths, metadata, dry-run output ...>
- Consumer check: <grep proving nobody parses the loosened output>

## Tasks
- T0 fact gate: re-read the cited line ranges; confirm offline import; report any mismatch before coding
- T1 characterization tests pin current behavior (own commit)
- T2 ... Tn: <one change each, exact signatures given as contract>

## Acceptance (run all, paste output in the PR body)
```bash
<lint command>
<test command>   # expected count delta: <n>, counting domain: <full suite | tests/ only>
<golden or dry-run command with full arguments and fixed seed>   # diff must be empty
git diff --stat <source dirs>   # tests-only briefs: must be empty
```

## PR requirements
- Title: <...>
- Commits: <grouping, e.g. tests first, then change>
- Body sections: evidence for each acceptance item, skipped items with reasons, deviations from
  this brief (the repo wins when brief and repo disagree)
~~~

## 3. Runner runbook skeleton (a delegated runner executing a fixed line)

The dispatcher keeps every creative and parameter decision. The runner executes and reports.

```markdown
# <line name> runbook

## What the line does
<one paragraph>

## Command template
1. Print mode first: run without `--run`, compare the printed engine command with the brief.
2. Execute: `<command> --run --json-out <path>`.

## Reading the result
<shape of the JSON result; read results from it, not from stdout>

## Acceptance checklist
- [ ] Exit code <expected>
- [ ] Every reported path opened by the runner
- [ ] Gate statistics reported (kept / dropped and why)
- [ ] Shortfall reported honestly (0 survivors is a valid outcome)
- [ ] Resources released after the run

## Failure modes
| Symptom | Action |
|---|---|
| Asset error with a fix hint | Relay the hint verbatim and stop. Never substitute assets. |
| Box busy | Stop and report. Do not queue behind other work. |
| <symptom> | <one action> |

## Boundaries
- Do not change weights, strengths, outfits or prompts. Report and let the dispatcher decide.
- Do not crown a best result unless this line is defined to auto-pick.
- A line with no safety gate says so in the report; do not improvise a gate.

## Report
Exact command, exit code, gate stats, verified result paths, contact sheet path, runbook
ambiguities found.
```
