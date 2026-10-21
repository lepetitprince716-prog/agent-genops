# Handoff templates

Four pieces, lightest first. See `docs/en/12-continuity.md` for when to use each.

## 1. Pre-compaction checkpoint (same session)

Target under 4 KB, ceiling 10 KB. Delete empty sections; never leave placeholders.

```markdown
# Checkpoint: <task in one line>  (<YYYY-MM-DD HH:MM>)

## Goals and constraints
- <goal>
- <constraint>; vetoed by owner: <approach>

## Completed (with evidence)
- <what> - <file:line | command + result | PR>

## Failed attempts (do not retry)
- <attempt> - <why it failed>

## Decisions
- <decision> - <reason>

## Unverified assumptions
- <assumption> - <how to check>

## Next
1. <first concrete action>
2. <...>

## Quick reference
- <paths, commands, branch, ids>
```

End the reply with an anchor sentence, for example:
`CHECKPOINT SAVED: <path> - after compaction, read this file back before continuing.`

## 2. Successor session prompt (fresh context)

One JSON object, telegraphic English, nothing else in the prompt field. Omit empty fields.
`cwd` and `branch` are mandatory.

```json
{
  "cwd": "/abs/path/to/worktree",
  "branch": "feat/x (not merged into local main)",
  "goal": "one line",
  "next": "first concrete action, not a topic",
  "files": ["path/to/file.py:120"],
  "cmd": "command that verifies progress",
  "avoid": ["gate rejects X", "tool Y times out on Z"],
  "task": "<tracker id, if any>",
  "from": "<predecessor actor, if a tracker task is handed over>"
}
```

Background (separate field, at least 80 characters, English): the goal and the constraints the
successor cannot see otherwise. No predecessor session id.

"Take next" variant, after a task closed with work still queued: only `cwd` and
`next: "<tracker> --actor <your actor> ready --claim --json -l repo:<name>"`. No task id, so two
such sessions never take the same task.

## 3. Full relay handoff (session abandoned)

Ideal under 10 KB, ceiling 30 KB. Link artifacts by path or URL; do not paste them.

```markdown
# Handoff: <one-line title>

**Date:** <YYYY-MM-DD>  **Focus:** <topic>

## What we are building
<1-3 sentences>

## What worked (with evidence)
- <item> - <evidence>

## What did not work (and why)
- <item> - <reason>

## Not tried yet
- <idea>

## Current state of files
| Path | State | Note |
|---|---|---|
| <path> | <modified / new / committed at hash> | <note> |

## Decisions made
- <decision> - <reason> - <rejected alternative>

## Blockers and open questions
- <blocker> - <who decides>

## Exact next step
<one action>

## Environment
- Branch, worktree, PR, runtime versions, services that must be running
```

## 4. Tracker work note (every handover of an in-progress task)

```text
work: <actor> <start>-<end> <N>m | session: <id> | branch: <name> (<worktree path>, pushed: yes/no) | next: <action> | excluded: <paths>
```

Receiver: read the task, then swap the assignee with a compare-and-set
(`update <id> -a <me> --if-assignee <previous>`). Keep the task in progress; do not re-claim.

## 5. Stop-and-hand-off note (executor finds the environment inconsistent)

```markdown
## Problem
## Root cause (known or suspected)
## Location (paths, commits, commands)
## Replay steps
## Acceptance criteria for the fix
```
