# Agent instructions

This repository is public (or public-bound). Every committed file, path, commit message, branch
name, and test fixture must be safe to publish as written.

## Where content belongs

- **In this repository:** generic methods, templates, tools, project folders (`cwc/`, `rdbg/`,
  `artfetch/`), synthetic fixtures, and placeholder configs.
- **Outside this repository:** real production canvases, generated images or videos, prompt
  histories, hostnames, LAN addresses, home paths, private repo names, account identifiers,
  runtime logs, model weights, and any API key, token, cookie, or password.

Never copy whole files from a private repository without a line-by-line review. Do not bypass
`.githooks/` (`--no-verify` or changing `core.hooksPath`).

## Two commands

1. **While working:** run `./check changed`
   - Scans staged, unstaged, non-ignored untracked files, and unmerged branch commits with both
     `tools/privacy_scan.py` and `tools/secret_scan.sh`, then runs the tests that the changed paths
     select. The output lists the changed guard files under `GUARD CHANGES`. The workflow policy
     step runs when `workflows/` or its policy changes, also with `--no-tests`.
   - There is no mode that runs every suite. All guard tests: `python3 -B -m unittest discover -s tests`.
   - Contributors without private rules run in contributor mode (`not a release check`).
   - Maintainers with `git config genops.mode maintainer` (or `AGENT_GENOPS_REQUIRE_PRIVATE=1`)
     fail closed if private rules are missing, empty, or invalid, if `core.hooksPath` is not
     `.githooks` or a hook is not executable, or if Betterleaks is unavailable.
2. **Before publishing:** run `./check release --to origin --ref refs/heads/<branch> --commit <full-sha>`
   - Read-only. Checks the exact target remote, full branch ref, remote old SHA, fast-forward
     relation, candidate history, all historical paths, and ref name.
   - It needs non-empty private rules, ready hooks, a clone that is not shallow, and one remote with
     one push URL that is the registered upstream.
   - The trusted baseline is the commit that the remote's `main` holds now, read with
     `git ls-remote`. If the local `refs/remotes/<remote>/main` is another commit, the check
     refuses and tells you to run `git fetch <remote>`. A remote that does not answer within 30 s
     is refused too (exit 2). The check then stops git and its transport, waits 2 s more for their
     output, and gives up on any process that left the group and still holds it.
   - The checker, scanners, rules and wrapper are exported from the trusted commit and run from
     there. The working tree supplies only the launcher.
   - The candidate's own exemptions do not count. Betterleaks uses the baseline's ignore file, and
     the commits from the remote's current branch (from the baseline for a new branch) to the
     candidate are scanned again with inline allow comments off. A maintainer who accepts such a
     finding passes `--approve-exemption <commit>:<path>:<rule>:<line>` once for each finding. The
     manifest lists them under `approved_exemptions`.
   - `--bootstrap-self-judge` is only for a baseline that cannot judge: it has no release checker
     that answers `./check protocol` with `{"release_protocol": 1}`, or no `tools/workflow_policy.py`.
     Without the flag the check refuses and says so; with the flag on a baseline that can judge,
     the check refuses the flag (exit 2), for `--verify-manifest` too. With it the candidate's own checker and
     scanners judge the candidate. The manifest then has `self_judged: true` and an entry in
     `unverified_items`, the terminal says that the candidate judged itself, and the result needs an
     independent review.
   - `--allowed-url` (and the `genops.allowedPushUrl` setting) approves a remote other than the
     repository's own, for rehearsals against a local bare repository. That remote's main is then the
     trusted baseline, so the manifest has `rehearsal_remote: true` and an entry in `unverified_items`,
     the terminal says REHEARSAL, and the manifest does not clear a release to the repository.
     `--verify-manifest` is refused unless the same remote is approved again.
   - Prints a redacted release manifest and stores a verification snapshot outside the repository
     (`~/.cache/agent-genops/release-manifests`, or `--manifest-dir`; a directory inside the
     repository is refused). It also lists the changed control files: the launcher, `.gitignore`, the two
     ignore files, `.githooks/`, `.github/workflows/`, `tests/`, and the scanner, rules, wrapper,
     template, release check and workflow policy files under `tools/`.
   - `--verify-manifest <file>` re-runs the whole release check against the live remote and compares
     it with the snapshot, field by field. Pass `--allow-new-ref`, `--bootstrap-self-judge` and each
     `--approve-exemption` again, exactly as for the first run; the snapshot does not carry them over.
   - The launcher is the `check` file of the working tree, which a candidate may have changed. To
     rule that out, run `./check release --commit <candidate>` from a checkout of the trusted
     baseline.
   - **Never pushes.** Passing checks do not grant permission to push, change visibility, change
     GitHub settings, create tags/releases, or archive repositories.

## When to stop and ask

Stop and report privately (never in a public issue, PR, or commit message) if:
- maintainer private rules are missing, empty, or invalid, or a scanner fails;
- a real personal identifier, credential, submodule, Git LFS pointer, or `refs/replace` entry is
  found;
- a false positive needs a new allow rule or ignore entry;
- the target remote, ref, old SHA, candidate SHA, or policy version differs from the reviewed
  manifest;
- any action requires pushing, changing repository visibility, modifying GitHub settings, or
  rewriting history.
