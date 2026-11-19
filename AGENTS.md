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
     `tools/privacy_scan.py` and `tools/secret_scan.sh`, then runs path-selected tests.
   - Contributors without private rules run in contributor mode (`not a release check`).
   - Maintainers with `git config genops.mode maintainer` (or `AGENT_GENOPS_REQUIRE_PRIVATE=1`)
     fail closed if private rules are missing, empty, or invalid, or if hooks/Betterleaks are
     unavailable.
2. **Before publishing:** run `./check release --to origin --ref refs/heads/<branch> --commit <full-sha>`
   - Read-only. Uses the trusted baseline scanner and rules to verify the exact target remote,
     full branch ref, remote old SHA, fast-forward relation, candidate history, all historical paths,
     and ref name.
   - Prints a redacted release manifest and stores a verification snapshot outside the repository.
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
