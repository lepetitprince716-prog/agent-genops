# Incident → rule

Turn one incident into one rule. Fill every field; write "unknown" rather than guess.
Keep the reason with the rule's owning file. Add one line to `docs/*/13-lessons.md` in the
form `date — what happened (cost) → rule`.

## Date

YYYY-MM-DD (or YYYY-MM when only the month is known)

## What happened

One to three sentences. What was run, on which role (Controller, Box A, Box B, a worker,
a subagent), and what went wrong. Use roles, never hostnames, addresses or account names.

## Cost

Measured, with units. GPU minutes, wall-clock delay, money (currency or credits), images
lost, calls wasted, sessions affected. "None measured" is an allowed answer.

## Root cause

The mechanism, not the symptom. One sentence for the cause, one for why existing checks
missed it. Mark it "suspected" if the cause was not reproduced.

## Rule

One imperative sentence a future agent can follow without context.

> Example: Render one smoke image before any batch of three or more.

## Where the rule now lives

- File: path relative to the repo (skill, rules file, runbook, script).
- Section or line:
- Changelog line added: yes / no

## How it is enforced

Pick the strongest that applies and say which:

- [ ] Code: a guard, a fail-closed check, a test.
- [ ] Gate or hook: blocks the action before it runs.
- [ ] Checklist step in a skill or runbook.
- [ ] Written rule only (state why nothing stronger was possible).

## Verification

How to show the rule works: a command that now fails on the bad input, a test name, or a
re-run that no longer reproduces the incident.

## Related

Links to earlier incidents of the same class, PRs or tracker tasks.
