English | [中文](../zh/12-continuity.md)

# Continuity: memory, state, handoffs and the task tracker

Agent sessions end, compact and get replaced. This page answers how work survives that: where
facts live between sessions, how one session hands over to the next, how parallel sessions share a
task list, and how results are reported to me.

> **TL;DR**
> - Memory is a folder of small files plus a one-line-per-file index. Every state in it is a dated snapshot; check it against git or the live machine before acting on it.
> - STATE is overwritten and kept short. Progress, decisions and memory logs are append-only with date and author.
> - Three handoff levels: a checkpoint before compaction, a successor session at 70% of the real compaction window, a full relay with a written handoff.
> - Session trees stay one level deep. Task status lives in one place, the shared tracker.
> - Reports lead with the conclusion and never drop bad news.

On this page: [Memory files](#memory-files) · [STATE snapshot versus append-only logs](#state-snapshot-versus-append-only-logs) · [Three handoff levels](#three-handoff-levels) · [Session trees one level deep](#session-trees-one-level-deep) · [The shared task tracker](#the-shared-task-tracker) · [Report style](#report-style) · [Real cases](#real-cases) · [Tried and dropped](#tried-and-dropped)

## Memory files

1. **One fact or one tight topic per file; the index carries one line per file.**
   Why: the index is loaded into every session, the files only on demand. On 2026-07-22 the index
   was cut from 21.5 KB to 7.4 KB, part of a saving of about 12,500 tokens per conversation.
2. **The description line carries the fact and its incident, so the index alone is often enough.**
   Why: an agent scanning the index decides from that line whether to open the file. A line like
   "smoke one image before any batch (09-16 probe round wasted about 40 minutes)" does that.
3. **Every state in memory is a snapshot from the day it was written. Check PRs, branches and machine state against git or the live machine before use.**
   Why: on 2026-09-17 a handoff written by a cloud session said a loopback link ran over a tunnel
   and proposed overwriting the launch definition with a fixed alias. The real definition picked the
   route automatically (it was plain LAN). Following the note would have destroyed the auto-picker.
4. **Live probes beat any snapshot.**
   Why: a doc that says a backend is online is history, not current state. The project's authority
   order puts the live machine, process and log above every document.
5. **Do not keep a second source of truth.**
   Why: on 2026-08-10 a new rating scale was deliberately not written to memory because the rule
   file already held it. Two copies drift.
6. **Audit memory in rounds: merge duplicates, rewrite stale entries, fix dangling links, shrink the index.**
   Why: memory grows by accretion. 2026-09-18: 63 to 59 files, three duplicate groups merged, two
   stale entries rewritten, zero dangling links. 2026-10-20, seven projects: the main project 217 to
   160 entries (index 26.3 KB to 17.5 KB), a second 68 to 45, the small ones 46 to 25. Deleted or
   distilled files go to a dated backup folder.
7. **Write descriptions in the language the queries will use.**
   Why: the 2026-09-18 audit kept Chinese descriptions instead of translating everything to
   English, because recall runs on Chinese phrasing.
8. **Shorter wording is not cheaper if it deletes facts.**
   Why: a blind test on 2026-09-18 rewrote one memory three ways. Plain modern Chinese scored 5/5.
   A terse classical style also scored 5/5 but used 48 more characters. An aggressive classical
   style scored 4.5/5, and the lost half point came from deleted facts.
9. **Record routing changes and worker retirements in global rules, not in one project's memory.**
   Why: owner's decision. Project memory is invisible to other projects.
10. **Mark retired knowledge bases as retired and do not build on them.**
    Why: owner's decision. The project keeps one retired folder with the note "do not read, cite or
    build logic on it".

Template: [`templates/memory-entry.md`](../../templates/memory-entry.md).

## STATE snapshot versus append-only logs

11. **STATE is overwritten in place and kept to a short "where are we" snapshot.**
    Why: owner's decision. In-flight work in STATE is a pointer (branch, PR, HEAD, handoff folder),
    not a narrative; the narrative lives in the dated handoff folder.
12. **PROGRESS, DECISIONS and MEMORY are append-only, each entry with date and author tag. Wrong history gets a correction appended, never a silent edit.**
    Why: owner's decision. An edited history cannot be audited.
13. **The roadmap says "where next and which gate blocks it"; it carries no progress numbers.**
    Why: owner's decision. STATE owns progress; the roadmap defers to it.
14. **A decision, once made, is written back into its authority file and removed from the open list.**
    Why: owner's decision; no single incident behind it.
15. **Never write unfinished work as done.**
    Why: owner's decision. STATE and the roadmap both carry this warning for UI items.
16. **Write pointers, not state that expires, and never put a verdict inside the tree under review.**
    Why: on 2026-09-16 a handoff note saying "all four packages PASS" sat inside a PR diff. The
    next docs package was then blocked under the injection rule. Verdicts live in the PR comment.
17. **A planning session opens with three reads: STATE, the roadmap status table, the runbook.**
    Why: owner's decision. After each accepted checkpoint it closes with a PROGRESS append and a STATE
    bullet update.

The governing files follow an authority read order: current state, then roadmap, vocabulary,
decisions, topology, route map, script index. When two disagree, the domain authority wins.

## Three handoff levels

Use the lightest level that fits.

| Level | When | What survives |
|---|---|---|
| Checkpoint | same session, before a compaction | a file on disk, re-injected once after compaction |
| Successor session | context at 70% of the real compaction window, or a task closed with work still queued | a small JSON prompt plus tracker notes |
| Relay | the session is abandoned | a git wrap-up, a written handoff, a started successor |

Templates for all three: [`templates/handoff.md`](../../templates/handoff.md).

### Checkpoint before compaction

1. Write the checkpoint file: goals and constraints with my vetoes, completed work with
   evidence, failed attempts, decisions, unverified assumptions, next one to three steps, quick
   reference coordinates. Delete empty sections.
2. Keep it under 4 KB; 10 KB is the ceiling. Over that, you are writing narrative.
3. End the reply with a fixed anchor sentence naming the file path, so the post-compaction session
   knows to read it back.
4. Optional: a SessionStart hook on `compact` injects the checkpoint once (consume-once, two-hour
   TTL, 50 KB cap) and archives it.

18. **Compaction summaries keep the story and drop the details, so the details go to disk first.**
    Why: what gets lost is exact `file:line`, command text, why an attempt failed, my
    vetoes, and the first next action. Without them the next turn re-argues settled decisions.

### Successor session at 70%

19. **Compute the threshold on the compaction window actually in force, not the model's nominal window.**
    Why: on 2026-10-14 the Opus window had been set to 500k (compaction fired near 467k), but the 70%
    trigger was still computed on 1M. It never fired, and every Opus session fell into automatic
    compaction. 70% of 500k is about 350k.
20. **The successor starts with fresh context, not a fork.**
    Why: a fork copies the 70%-full context, which defeats the handoff.
21. **The successor prompt is one JSON object. `cwd` and `branch` are mandatory.**
    Why: on 2026-10-13 a successor could not find the files because the prompt omitted them, and
    searched git three times. Other fields: `goal`, `next` (an action, not a topic), `files` as
    `path:line`, `cmd`, `avoid`, plus a background paragraph of 80 characters or more.
22. **`avoid` is the most valuable field. Phrase dead ends as state: "gate rejects X", not "tried X and it was rejected".**
    Why: it saves the next session from walking the same dead end.
23. **The successor works only from the JSON, the background and the tracker notes. It does not read or contact the predecessor.**
    Why: decided 2026-10-15. Everything the successor needs goes into the JSON or the notes. The
    older relay flow passed the predecessor's session id so the transcript could be read; for
    successor prompts the newer rule wins.
24. **After sending the successor, the predecessor ends its turn and stops touching files. Do not archive it while they share a worktree.**
    Why: archiving a session also archives sessions that share its worktree.

In this setup a Stop hook measures occupancy from the transcript tail, fires once per session above
the threshold, returns the handoff instructions, never loops and always exits 0. It has to be
registered as a managed hook, because user-level hooks are blocked by policy here and fail silently.

### Full relay

1. Git wrap-up only if the tree has changes: topic branch if on the default branch, stage only this
   task's paths, conventional commit, PR with the body from a file. Never commit half-finished or
   failing work.
2. Write the handoff with these sections: what we are building, what worked (with evidence), what did
   not work and why, not tried yet, current state of files, decisions, blockers and open questions,
   exact next step, environment. Ideal under 10 KB, ceiling 30 KB. Link artifacts by path.
3. Turn real follow-ups into proposal cards, at most three per turn.
4. Withdraw any pending successor card for this thread, then start the successor.

25. **An executor whose environment looks wrong stops and leaves a handoff instead of committing.**
    Why: on 2026-07-04 an executor saw the same commit under two hashes and branch deletes writing
    through while file commits did not. It stopped without committing and left a handoff with
    problem, root cause, location, replay steps and acceptance criteria. Partial write-through is
    more dangerous than full isolation.

## Session trees one level deep

26. **A successor or handoff session is detached right after it starts.**
    Why: decided 2026-10-17. The app wakes the starter every time a side session ends a turn, and each
    woken session wakes its own starter, so a deep chain re-reads every ancestor's context.
27. **A side session that will start sessions of its own detaches itself first.**
    Why: same reason; its children then report to it, not to the root.
28. **When the app refuses to detach (shared worktree, or a session I placed by hand), detach each session you start instead.**
    Why: those children have their own worktrees. A session that may later start others gets its
    own worktree from the start.
29. **Only the session that owns a task reads side-session reports.**
    Why: a report that unblocks none of your steps earns no relay and at most one line to me.

## The shared task tracker

Task state lives in one place, the shared tracker (bd, also known as beads). Chat cards, step lists
and wrap-up boxes are views onto it. Cards expire after a week and transcripts get cleaned; the
tracker does not, and non-Claude workers see only the tracker.

30. **One actor per session, on every command: `<agent>-<model>/<effort>#<short session id>`. Unknown parts are written `unknown`.**
    Why: claim and close protection only works when actors differ. Shell state does not survive
    between calls, so the actor goes on each command.
31. **Claim with `ready --claim` for "next task", or claim a named id. Do not reclaim casually.**
    Why: two parallel "take next" sessions get different tasks; a card with a hard-coded id gets
    taken by two sessions at once. Leases expire after five minutes but are reclaimed only when
    someone runs reclaim; use a 24-hour threshold for dead sessions.
32. **On handoff, append a work note with session, branch, worktree, pushed or not, next step, excluded paths. The receiver swaps the assignee with a compare-and-set.**
    Why: the branch is the only way to find files not yet on main (the 2026-10-13 case). The
    compare-and-set fails with a distinct exit code when someone else changed the assignee.
33. **A task waiting on me is set to blocked with a one-line blocker, never left in progress.**
    Why: on 2026-10-14 a task sat in progress with "not closing, waiting for user", and the wrap-up
    to-do list came out empty. When I decide, the task goes back to open with the assignee cleared.
34. **Close with metadata (agent, model, effort, minutes, sessions) and a close reason that starts with the result.**
    Why: owner's decision. Metadata makes "which tier did this work" a query. The reason's first
    sentence (60 characters or fewer) is what shows in the sidebar.
35. **Discovered work links to its source and carries a chain counter. The third derived task is created blocked.**
    Why: decided 2026-10-07. The same kind of small fix cannot roll on by itself; direction stays
    with me.
36. **Every wrap-up ends with the blocked list and the stale in-progress list (no update in two days). Report only; do not act on them.**
    Why: owner's decision. These are the two lists I need and would otherwise not see.

Titles: verb first, 24 characters or fewer, no repo name (the label carries it).

## Report style

37. **Conclusion first. The first sentence says whether it works and why.**
    Why: the reader needs to know "can I use it, what next" within three seconds.
38. **Numbers go in directly: "1952 pass / 26 fail", not "tests mostly pass".**
    Why: owner's decision; no single incident behind it.
39. **Bad news is never trimmed. Unverified, undone, impossible and failed items stay, with whether the failure is yours.**
    Why: owner's decision. Trim order is explanations first, then details, then merged items. Bad news
    and commands are never cut.
40. **Commands, paths, branches and links are copied verbatim. When a gate blocks you, hand over one runnable command, not prose.**
    Why: owner's decision since 2026-09-19. The command is idempotent, backs up what it overwrites,
    aborts on a missing anchor, and says which parts stayed unverified.
41. **At most two options per decision, with a recommendation. Progress notes only when the plan changes, something fails, or before a long wait.**
    Why: length is a hard constraint for me; progress notes count toward it (2026-10-17).

## Real cases

- 2026-07-04: executor saw a drifting git view, stopped, left a handoff. Rule 25.
- 2026-09-16: a verdict inside a reviewed diff blocked the next package. Rule 16.
- 2026-09-17: a cloud-written handoff misread the route and proposed a destructive fix. Rule 3.
- 2026-10-13: a successor prompt without `cwd` and `branch`; three passes through git. Rule 21.
- 2026-10-14: a task left in progress emptied the wrap-up to-do list. Rule 33.
- 2026-10-14: the 70% trigger never fired after the window shrank. Rule 19.

## Tried and dropped

- Classical-Chinese and operator-style compression of rules and memory: dropped 2026-09-18 (rule 8).
- Forking the context into the successor: dropped (rule 20).
- Computing occupancy on the nominal 1M window: dropped 2026-10-14 (rule 19).
- Successors reading the predecessor's transcript: replaced by self-contained prompts 2026-10-15.
- "In progress, waiting for user": replaced by blocked 2026-10-14.
- One-time session-start context for long sessions: it decays like any early message. A hook now
  re-injects it, silent for the first 12 turns (2026-08-25).

## See also

- [03-dispatch.md](03-dispatch.md): packets, tiers, acceptance.
- [13-lessons.md](13-lessons.md): dated incidents by area.
- [`templates/handoff.md`](../../templates/handoff.md), [`templates/memory-entry.md`](../../templates/memory-entry.md).
