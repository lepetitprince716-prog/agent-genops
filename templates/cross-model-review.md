# Cross-model bounded review templates

Two read-only prompts for an independent reviewer from a second model family. Copy the gate that
fits, fill the angle-bracket paths, and run the reviewer with read-only file tools (`read`, `grep`,
`glob`). Keep open-ended style advice out of scope so the reviewer spends its budget falsifying
real failure paths and checking test integrity. See `docs/en/03-dispatch.md` for when to run each.

## 1. Gate 1: pre-code spec falsification (`Subtract-Before-Add` + statechart invariants)

Run after drafting an architecture, kernel, or multi-file spec and before writing implementation
code. If you run two model families in parallel, keep them blind to each other's output.

```text
BOUNDED_REVIEW: GATE_1_SPEC
role: independent read-only verifier (no file edits, no shell writes, no sub-agents)
target_spec: <absolute or repo-relative path to SPEC.md>
source_paths: <exact upstream/repo files and line ranges the spec touches>
tool_budget: <=15 targeted reads/greps on disk; verify every claim against source lines

Answer ONLY these two questions, citing exact file:line evidence:

1. Statechart and invariant falsification
   - Trace state transitions, cache/memory ownership, failure/timeout paths, and partial-apply
     rollbacks across source_paths.
   - Flag concrete deadlocks, silent slice/key drops, graph/allocator pool conflicts, unguarded
     shared mappings, or states that `/free` or rollback cannot recover.

2. Subtract-Before-Add
   - List every proposed custom kernel, wrapper, cache, or multi-node scheme in target_spec that
     can be deleted before coding because:
     (a) the current runtime already does the work (verify in source_paths),
     (b) numerical error or Amdahl's law caps the gain inside noise, or
     (c) a simpler single-node or existing-node flag reaches the same outcome.

Out of scope (do not emit):
- New product features, extra abstractions, variable renamings, or prose/formatting preferences.

Output format:
- Blockers B1..Bn: file:line, concrete failure trace or ceiling math, impact, Smallest Fix (or CUT).
- Cut list: items to delete from target_spec before coding, one line each.
- Verified on disk: 2-4 bullets naming the exact files inspected.
- Final line: VERDICT: PASS | VERDICT: FAIL
```

## 2. Gate 2: pre-closeout compliance and anti-gaslighting test audit

Run before merging a multi-file change, closing a benchmark task, or writing a user-facing summary.

```text
BOUNDED_REVIEW: GATE_2_CLOSEOUT
role: independent read-only verifier (no file edits, no shell writes, no sub-agents)
approved_spec: <path to SPEC.md or executor brief>
changed_paths: <git diff base..HEAD paths, test files, and benchmark JSONL/manifests>
tool_budget: <=15 targeted reads/greps on disk; read real files, never trust prose summaries

Audit ONLY these three items, citing exact file:line evidence:

1. Spec compliance
   - Check each requirement and non-goal in approved_spec against changed_paths.
   - Flag silent omissions, unimplemented stubs, hardcoded local paths, silent CPU/FP32 fallbacks,
     or numbers reported without matching artifact rows.

2. Anti-Gaslighting test and benchmark audit (automatic VERDICT: FAIL if any fires)
   - Tests deleted, skipped (`skip`, `xfail`, `.only`), or weakened (`>=` where exact count belongs,
     broad `except`, or lowered thresholds) to turn a red check green.
   - Unit under test mocked away, or production code branching on test inputs.
   - Benchmark distortion: warm-up runs kept in medians, A_2 hitting execution cache (`0.07 s`
     cached sampler), or asymmetric cold vs cached text encoding across arms.
   - Per assertion in new tests, ask: "would this test fail if the guarded code broke?"

3. Hard-constraint opportunity (optional, at most 1 item)
   - Name at most one deterministic check (schema invariant, offset/count assertion, or `--strict-cache`
     gate) that mechanically blocks an entire bug class seen in changed_paths.

Out of scope (do not emit):
- Cosmetic refactors, naming nitpicks, or follow-up feature ideas.

Output format:
- Blockers B1..Bn: file:line, exact mismatch or weak assertion, Smallest Fix.
- Integrity check: 2-4 bullets confirming what was verified directly in changed_paths.
- Hard-constraint opportunity: 0 or 1 bullet.
- Final line: VERDICT: PASS | VERDICT: FAIL
```
