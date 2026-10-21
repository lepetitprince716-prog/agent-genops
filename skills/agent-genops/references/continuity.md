# Continuity: memory, state, handoffs, task tracker, reports

Read when: writing or using memory, updating STATE or logs, approaching compaction, handing a task
to another session, claiming or closing tracker tasks, or writing a wrap-up report.

## 1. Memory files

- One fact or one tight topic per file. Template: `templates/memory-entry.md`.
- Index: one line per file. The line states the fact and its incident.
- Treat every state in memory as a dated snapshot. Before acting on a PR, branch, machine or service
  claim, check git or probe the live machine.
- Live probe beats document. A doc saying "online" is history.
- Never create a second source of truth. If a rule file holds it, memory points to the rule file.
- Write descriptions in the language queries will use.
- Do not compress by deleting facts. Terser style is not a saving.
- Routing changes and worker retirements go to global rules, not project memory.
- Retired knowledge folders: do not read, cite or build on them.
- Audit round: merge duplicates, rewrite stale entries, fix dangling links, shrink the index, back
  up removed files to a dated folder. Report counts before and after.

## 2. STATE and logs

| File | Write mode | Holds |
|---|---|---|
| STATE | overwrite in place, keep short | where we are; in-flight pointers (branch, PR, HEAD, handoff folder) |
| PROGRESS | append-only, date + author | what was accepted, when |
| DECISIONS | append-only, date + author | decisions with rejected alternatives |
| MEMORY log | append-only, date + author | durable lessons |
| ROADMAP | edit with dated lines | where next, which gate blocks it; no progress numbers |
| Open decisions | remove item once decided | decisions still pending |

- Correct wrong history by appending a correction. Never edit silently.
- Never write unfinished work as done.
- Write pointers, not expiring state. Never commit a review verdict into the tree under review.
- Planning session start: read STATE, roadmap status table, runbook. After each accepted
  checkpoint: append PROGRESS, update the STATE bullet.
- Authority read order: state, roadmap, vocabulary, decisions, topology, route map, script index.
  Domain authority wins a conflict.

## 3. Handoff level

| Trigger | Level |
|---|---|
| Compaction coming, same session continues | Checkpoint |
| Context at 70% of the compaction window actually in force | Successor session |
| Tracker task closed, queue still has work | Successor session with a "take next" prompt |
| Session abandoned or stage done | Full relay |

Compute 70% on the configured compaction window, not the nominal model window.

### Checkpoint

1. Sections: goals and constraints (with vetoes), completed with evidence, failed attempts,
   decisions, unverified assumptions, next 1-3 steps, quick reference. Drop empty sections.
2. Size: under 4 KB, ceiling 10 KB.
3. End the reply with an anchor sentence naming the checkpoint path.
4. After compaction: read the checkpoint back before any other action.

### Successor session

1. If a tracker task is in flight: append the work note first (section 4).
2. Start with fresh context, never a fork.
3. Prompt is one JSON object, telegraphic English. Mandatory: `cwd` (the worktree holding the
   work), `branch` (and whether it is merged into local main). Optional: `goal`, `next` (an action),
   `files` (`path:line`), `cmd`, `avoid` (dead ends phrased as state), `task`, `from`. Omit empty
   fields.
4. Background paragraph: at least 80 characters, goal and constraints.
5. No predecessor session id. The successor reads only the JSON, background and tracker notes.
6. One successor per main thread. Withdraw a superseded card first.
7. After sending: end the turn, stop touching files. Do not archive the predecessor while they
   share a worktree.
8. Do not send for finished work (unless the queue has more), work blocked on the owner, or work
   too vague to start.

### Full relay

1. Git: only if the tree has changes. Topic branch if on default. Stage only this task's paths.
   Never commit failing or half-finished work. PR body from a file.
2. Handoff sections: building what; worked (evidence); did not work (why); not tried;
   current files; decisions; blockers; exact next step; environment. Under 10 KB, ceiling 30 KB.
3. Follow-ups as proposal cards, at most 3 per turn, each with a tracker task first.
4. Withdraw pending successor cards, then start the successor.

## 4. Task tracker (bd)

1. Actor on every command: `<agent>-<model>/<effort>#<short session id>`. Unknown parts: `unknown`.
2. Claim: `ready --claim` for next, or `update <id> --claim`. Record `started_at`. Do not run
   reclaim casually; 24 hours for dead sessions.
3. Handoff note: session, branch, worktree, pushed or not, next step, excluded paths. Receiver:
   read the task, then compare-and-set the assignee. A distinct exit code means someone else
   changed it; check who.
4. Waiting on the owner: status blocked plus a one-line blocker. Never leave it in progress. On
   decision: back to open, assignee cleared.
5. Close: metadata `{agent, model, effort, minutes, sessions}`, then a close reason whose first
   sentence (60 characters or fewer) is the result.
6. Discovered work: link `discovered-from`, set `chain` = source chain + 1. At chain 3, create it
   blocked with a note asking the owner whether to continue.
7. Titles: verb first, 24 characters or fewer, no repo name.
8. Archive a session only when it holds no in-progress tasks.

## 5. Session trees

- Detach a successor or handoff session right after it starts.
- Before starting sessions of your own from a side session, detach yourself.
- If detach is refused, detach each session you start instead. A session that may start others
  gets its own worktree.
- Only the task owner reads side-session reports. No relays.

## 6. Wrap-up report

1. First sentence: works or not, and why.
2. Numbers as numbers: "1952 pass / 26 fail".
3. Keep all bad news: unverified, undone, impossible, failed (and whether you caused it).
4. Copy commands, paths, branches, links verbatim.
5. Blocked by a gate: one runnable command (idempotent, backs up, aborts on missing anchor),
   unverified parts named.
6. At most two options per decision, with a recommendation.
7. End with the blocked task list and the stale in-progress list (2 days). Report only.
8. Trim order: explanations, then details, then merge items. Never cut bad news or commands.
