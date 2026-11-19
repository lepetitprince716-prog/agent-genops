#!/usr/bin/env python3
"""Unified local verification and release-manifest preparation for agent-genops.

Self-contained stdlib implementation: never imports repo-local scanner modules into its own
process. Invokes ``privacy_scan.py`` in isolated mode (``python3 -I -B``) and validates its
structured JSON contract so a silent stub cannot pass.

Subcommands (invoked via ``./check``):
  - ``changed``: inspect staged, unstaged, untracked, and unmerged branch changes, then run
    path-selected tests. Distinguishes contributor mode (public rules only, never authorizes a
    release) from maintainer mode (fails closed if private rules are missing, empty or invalid).
  - ``release``: read-only pre-release verification and redacted manifest generation for one exact
    ``(remote, ref, commit)`` candidate, using the trusted baseline scanner/rules. Never pushes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXIT_CLEAN, EXIT_FINDINGS, EXIT_ERROR = 0, 1, 2
PRIVATE_RULES_ENV = "AGENT_GENOPS_PRIVATE_RULES"
REQUIRE_PRIVATE_ENV = "AGENT_GENOPS_REQUIRE_PRIVATE"
MAINTAINER_MODE_CONFIG_KEY = "genops.mode"
MAINTAINER_MODE_VALUE = "maintainer"

ZERO_OID = "0" * 40
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
INLINE_ALLOW_RE = re.compile(r"\b(?:betterleaks|gitleaks):allow\b")
MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HTML_LINK_RE = re.compile(r"""(?:href|src|srcset)=["']([^"']+)["']""")

DEFAULT_ALLOWED_URLS = frozenset(
    {
        "https://github.com/lepetitprince716-prog/agent-genops",
        "https://github.com/lepetitprince716-prog/agent-genops.git",
        "git@github.com:lepetitprince716-prog/agent-genops",
        "git@github.com:lepetitprince716-prog/agent-genops.git",
        "ssh://git@github.com/lepetitprince716-prog/agent-genops",
        "ssh://git@github.com/lepetitprince716-prog/agent-genops.git",
    }
)

CONTROL_PLANE_EXACT = frozenset(
    {
        "check",
        ".gitignore",
        ".betterleaksignore",
        ".gitleaksignore",
        "tools/privacy_scan.py",
        "tools/privacy_rules.json",
        "tools/secret_scan.sh",
        "tools/secret_scan.tmpl",
        "tools/release_check.py",
        "tests/test_secret_guard.py",
        "tests/test_release_check.py",
    }
)
CONTROL_PLANE_PREFIXES = (".githooks/", ".github/workflows/")
DOC_SUFFIXES = frozenset({".md", ".svg", ".txt"})
DOC_EXACT = frozenset({"LICENSE", "LICENSE-APACHE", "LICENSE-MIT"})
GUARD_TEST_PREFIXES = (".githooks/", "tools/", "tests/")
GUARD_TEST_EXACT = frozenset(
    {
        "check",
        ".github/workflows/privacy.yml",
        ".betterleaksignore",
        ".gitleaksignore",
        ".gitignore",
    }
)
EXECUTABLE_SUFFIXES = frozenset({".py", ".sh", ".ps1", ".rs", ".toml", ".yml", ".yaml", ".json"})

TRUSTED_FILES = (
    "tools/privacy_scan.py",
    "tools/privacy_rules.json",
    "tools/secret_scan.sh",
    "tools/secret_scan.tmpl",
    ".betterleaksignore",
    ".gitleaksignore",
)


class CheckError(Exception):
    """Configuration or environment failure (exit status 2)."""


@dataclass
class StepResult:
    name: str
    status: str  # PASS, FAIL, NOT RUN, ERROR
    duration_s: float
    detail: str


def split_names(listing: bytes) -> Iterator[str]:
    return (os.fsdecode(raw) for raw in listing.split(b"\0") if raw)


def private_rules_path() -> Path:
    override = os.environ.get(PRIVATE_RULES_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "agent-genops" / "private_rules.json"


def run_git(
    args: list[str], cwd: Path, *, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    try:
        proc = subprocess.run(
            ["git", "--no-replace-objects", *args],
            cwd=cwd,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise CheckError(f"cannot execute git: {exc}") from exc
    if check and proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise CheckError(f"git {args[0]} failed: {err}")
    return proc


def git_text(args: list[str], cwd: Path) -> str:
    return run_git(args, cwd, check=True).stdout.decode("utf-8", "replace").strip()


def git_optional(args: list[str], cwd: Path) -> str | None:
    proc = run_git(args, cwd, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace").strip()


def repo_root(cwd: Path | None = None) -> Path:
    return Path(git_text(["rev-parse", "--show-toplevel"], cwd or Path.cwd()))


def is_maintainer_required(root: Path) -> bool:
    if os.environ.get(REQUIRE_PRIVATE_ENV) == "1":
        return True
    mode = git_optional(["config", "--get", MAINTAINER_MODE_CONFIG_KEY], root)
    return (mode or "").lower() == MAINTAINER_MODE_VALUE


def validate_private_rules_file(require_non_empty: bool) -> tuple[bool, int, str]:
    """Validate private rules file shape without ever printing pattern text."""
    path = private_rules_path()
    if not path.is_file():
        if require_non_empty:
            raise CheckError(
                f"maintainer/private rules required, but no private rules file at {path}"
            )
        return False, 0, "private rules not loaded (0 rules)"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CheckError(f"cannot read private rules file {path}: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("version") != 1 or not isinstance(doc.get("rules", []), list):
        raise CheckError(f"{path}: invalid private rules schema")
    count = len(doc.get("rules", []))
    if require_non_empty and count == 0:
        raise CheckError(
            f"{path}: private rules file defines 0 rules; refusing to proceed in maintainer mode"
        )
    return True, count, f"private rules loaded ({count} rules)"


def ensure_hooks_ready(root: Path) -> list[str]:
    problems: list[str] = []
    hooks_path = git_optional(["config", "--get", "core.hooksPath"], root)
    if hooks_path != ".githooks":
        problems.append(
            f"core.hooksPath is {hooks_path!r}; expected '.githooks' (run: git config core.hooksPath .githooks)"
        )
    for hook in ("pre-commit", "commit-msg", "pre-push"):
        hook_file = root / ".githooks" / hook
        if not hook_file.is_file() or not os.access(hook_file, os.X_OK):
            problems.append(f"hook missing or not executable: .githooks/{hook}")
    return problems


def ensure_betterleaks_available() -> str:
    found = shutil.which("betterleaks")
    if not found:
        raise CheckError(
            "betterleaks is not on PATH (install with 'brew install betterleaks' or from releases)"
        )
    return found


def resolve_branch_base(root: Path, explicit_base: str | None) -> tuple[str | None, str | None]:
    """Return ``(label, merge_base_sha)`` for branch-commit scanning, or ``(None, None)``."""
    head = git_optional(["rev-parse", "--verify", "--quiet", "HEAD^{commit}"], root)
    if not head:
        return None, None
    candidates: list[tuple[str, str]] = []
    if explicit_base:
        candidates.append((explicit_base, explicit_base))
    else:
        candidates.extend(
            [
                ("refs/remotes/origin/main", "refs/remotes/origin/main"),
                ("refs/heads/main", "refs/heads/main"),
            ]
        )
    for label, ref in candidates:
        if ref.startswith("refs/"):
            sha = git_optional(["show-ref", "--verify", "--hash", ref], root)
        else:
            sha = git_optional(
                ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}"],
                root,
            )
        if not sha:
            if explicit_base:
                raise CheckError(f"base ref not found: {explicit_base}")
            continue
        mb = git_optional(["merge-base", sha, head], root)
        if mb:
            return label, mb
    return None, None


def run_privacy_subprocess(
    scanner: Path,
    rules_path: Path,
    scan_args: list[str],
    cwd: Path,
    *,
    require_private: bool,
    no_private: bool,
) -> tuple[int, dict[str, Any], str]:
    cmd = [sys.executable, "-I", "-B", str(scanner), "--rules", str(rules_path), "--json"]
    if require_private:
        cmd.append("--require-private")
    if no_private:
        cmd.append("--no-private")
    cmd.extend(scan_args)
    env = dict(os.environ)
    if require_private:
        env[REQUIRE_PRIVATE_ENV] = "1"
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    try:
        payload = json.loads(proc.stdout) if proc.stdout.strip() else None
    except ValueError:
        payload = None
    if not isinstance(payload, dict) or payload.get("status") not in ("clean", "findings", "error"):
        detail = (proc.stderr or proc.stdout).strip() or f"exit {proc.returncode}"
        return EXIT_ERROR, {"status": "error", "error": f"invalid scanner JSON output: {detail}"}, detail
    if require_private and payload.get("status") == "clean":
        if not payload.get("private_loaded") or int(payload.get("private_rule_count", 0)) <= 0:
            return (
                EXIT_ERROR,
                {"status": "error", "error": "scanner did not confirm non-empty private rules"},
                "",
            )
    return proc.returncode, payload, proc.stderr.strip()


def run_secret_subprocess(
    script: Path,
    scan_args: list[str],
    cwd: Path,
    *,
    redact_scanner: Path,
    rules_path: Path,
    no_private: bool,
    ignore_path: Path | None = None,
    ignore_allow: bool = False,
) -> tuple[int, str]:
    env = dict(os.environ)
    env["SECRET_SCAN_REDACT_SCANNER"] = str(redact_scanner)
    env["SECRET_SCAN_RULES"] = str(rules_path)
    env["SECRET_SCAN_NO_PRIVATE"] = "1" if no_private else "0"
    if ignore_path is not None:
        env["SECRET_SCAN_IGNORE_PATH"] = str(ignore_path)
    if ignore_allow:
        env["SECRET_SCAN_IGNORE_ALLOW"] = "1"
    proc = subprocess.run(
        ["sh", str(script), *scan_args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = "\n".join(part for part in (proc.stdout.strip(), proc.stderr.strip()) if part)
    return proc.returncode, combined


def check_relative_links(root: Path, md_paths: list[str]) -> list[str]:
    """Check relative file links inside changed Markdown files (local only, stdlib)."""
    broken: list[str] = []
    for rel in sorted(set(md_paths)):
        file_path = root / rel
        if not file_path.is_file() or file_path.is_symlink():
            continue
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError:
            continue
        targets: list[str] = []
        for raw_target in MD_LINK_RE.findall(text):
            target = raw_target.strip().split()[0].strip("<>")
            targets.append(target)
        for raw_target in HTML_LINK_RE.findall(text):
            targets.append(raw_target.strip())
        for target in targets:
            if (
                not target
                or target.startswith(("#", "http://", "https://", "mailto:", "data:", "tel:"))
                or "://" in target
            ):
                continue
            clean = target.split("#", 1)[0].split("?", 1)[0]
            if not clean:
                continue
            resolved = (file_path.parent / clean).resolve()
            if not resolved.exists():
                broken.append(f"{rel}: broken relative link -> {clean}")
    return broken


def is_doc_only_path(rel: str) -> bool:
    p = Path(rel)
    if p.name in DOC_EXACT:
        return True
    if p.suffix.lower() in DOC_SUFFIXES and not rel.startswith(("cwc/", "rdbg/", "artfetch/")):
        return True
    if rel.startswith(("docs/", "assets/", "templates/", "skills/")):
        return p.suffix.lower() in DOC_SUFFIXES
    return False


def is_unclassified_executable(root: Path, rel: str) -> bool:
    if rel.startswith(("cwc/", "rdbg/", "artfetch/")):
        return False
    if is_doc_only_path(rel):
        return False
    p = Path(rel)
    if p.suffix.lower() in EXECUTABLE_SUFFIXES:
        return True
    full = root / rel
    if full.is_file() and not full.is_symlink() and os.access(full, os.X_OK):
        return True
    return False


def guard_trigger_paths(root: Path, changed_paths: list[str]) -> list[str]:
    """The changed paths that select the guard tests: guard files, guard tests, root code."""
    return [
        p
        for p in changed_paths
        if p in GUARD_TEST_EXACT
        or p.startswith(GUARD_TEST_PREFIXES)
        or is_unclassified_executable(root, p)
    ]


def select_test_suites(root: Path, changed_paths: list[str]) -> dict[str, tuple[bool, str]]:
    """Map changed paths to test suites, returning ``{suite: (should_run, reason)}``."""
    md_files = [p for p in changed_paths if p.lower().endswith(".md")]
    run_doc_links = bool(md_files)
    run_cwc = any(p.startswith("cwc/") for p in changed_paths)
    run_rdbg = any(p.startswith("rdbg/") for p in changed_paths)
    run_artfetch = any(p.startswith("artfetch/") for p in changed_paths)
    run_guard = bool(guard_trigger_paths(root, changed_paths))

    return {
        "doc-links": (
            run_doc_links,
            f"{len(md_files)} markdown file(s) changed" if run_doc_links else "no markdown changes",
        ),
        "guard-tests": (
            run_guard,
            "shared guard/policy/hook/executable changed" if run_guard else "no guard/root-code changes",
        ),
        "cwc-tests": (run_cwc, "cwc/ changed" if run_cwc else "cwc/ untouched"),
        "rdbg-tests": (run_rdbg, "rdbg/ changed" if run_rdbg else "rdbg/ untouched"),
        "artfetch-tests": (
            run_artfetch,
            "artfetch/ changed" if run_artfetch else "artfetch/ untouched",
        ),
    }


def run_test_suite(root: Path, suite: str, md_files: list[str]) -> StepResult:
    t0 = time.monotonic()
    if suite == "doc-links":
        broken = check_relative_links(root, md_files)
        dt = time.monotonic() - t0
        if broken:
            return StepResult(suite, "FAIL", dt, "\n".join(broken))
        return StepResult(suite, "PASS", dt, f"checked {len(set(md_files))} markdown file(s)")

    cmd_map: dict[str, tuple[list[str], Path]] = {
        "guard-tests": ([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"], root),
        "cwc-tests": ([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"], root / "cwc"),
        "rdbg-tests": (["cargo", "test", "--locked"], root / "rdbg"),
        "artfetch-tests": (["cargo", "test", "--all-targets"], root / "artfetch"),
    }
    cmd, cwd = cmd_map[suite]
    if not cwd.is_dir():
        return StepResult(suite, "NOT RUN", 0.0, f"directory not present: {cwd.name}/")
    if cmd[0] == "cargo" and shutil.which("cargo") is None:
        return StepResult(suite, "ERROR", 0.0, "cargo is not on PATH")
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    dt = time.monotonic() - t0
    if proc.returncode == 0:
        return StepResult(suite, "PASS", dt, f"exit 0 ({' '.join(cmd)})")
    tail = "\n".join((proc.stdout + "\n" + proc.stderr).strip().splitlines()[-15:])
    return StepResult(suite, "FAIL", dt, tail or f"exit {proc.returncode}")


def list_changed_by_state(root: Path, merge_base: str | None) -> dict[str, list[str]]:
    """Changed paths per state. ``staged``/``unstaged`` hold what still has content (added,
    copied, modified, renamed, type-changed); deletions are listed apart, since there is
    nothing to scan in them but they still decide which tests run."""
    staged = list(
        split_names(
            run_git(["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT"], root).stdout
        )
    )
    unstaged = list(
        split_names(run_git(["diff", "--name-only", "-z", "--diff-filter=ACMRT"], root).stdout)
    )
    removed_staged = list(
        split_names(
            run_git(["diff", "--cached", "--name-only", "-z", "--diff-filter=D"], root).stdout
        )
    )
    removed_unstaged = list(
        split_names(run_git(["diff", "--name-only", "-z", "--diff-filter=D"], root).stdout)
    )
    untracked = list(
        split_names(run_git(["ls-files", "--others", "--exclude-standard", "-z"], root).stdout)
    )
    branch_files: list[str] = []
    if merge_base:
        count = int(git_text(["rev-list", "--count", f"{merge_base}..HEAD"], root))
        if count > 0:
            branch_files = list(
                split_names(run_git(["diff", "--name-only", "-z", f"{merge_base}..HEAD"], root).stdout)
            )
    return {
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "branch": branch_files,
        "removed_staged": removed_staged,
        "removed_unstaged": removed_unstaged,
    }


def cmd_changed(args: argparse.Namespace) -> int:
    t_total = time.monotonic()
    root = repo_root()
    scanner = root / "tools" / "privacy_scan.py"
    rules_path = root / "tools" / "privacy_rules.json"
    secret_script = root / "tools" / "secret_scan.sh"

    if args.maintainer and args.contributor:
        raise CheckError("--maintainer and --contributor are mutually exclusive")
    if args.maintainer:
        maintainer = True
    elif args.contributor:
        maintainer = False
    else:
        maintainer = is_maintainer_required(root)

    mode_label = "maintainer" if maintainer else "contributor"
    errors: list[str] = []

    if maintainer:
        errors.extend(ensure_hooks_ready(root))
    ensure_betterleaks_available()

    if maintainer:
        _loaded, _priv_count, rules_note = validate_private_rules_file(require_non_empty=True)
    else:
        rules_note = "private rules skipped (contributor mode)"

    if errors:
        raise CheckError("; ".join(errors))

    base_label, merge_base = resolve_branch_base(root, args.base)
    states = list_changed_by_state(root, merge_base)
    branch_range = f"{merge_base}..HEAD" if (merge_base and states["branch"]) else None

    scan_args: list[str] = ["--source-labels"]
    if states["staged"] or states["removed_staged"]:
        scan_args.extend(["--staged", "--identity"])
    if states["unstaged"]:
        scan_args.append("--unstaged")
    if states["untracked"]:
        scan_args.append("--untracked")
    if branch_range:
        scan_args.extend(["--range", branch_range])

    privacy_findings: list[dict[str, Any]] = []
    privacy_status = "clean"
    if len(scan_args) > 1:
        rc, payload, stderr_txt = run_privacy_subprocess(
            scanner,
            rules_path,
            scan_args,
            root,
            require_private=maintainer,
            no_private=not maintainer,
        )
        if rc == EXIT_ERROR:
            raise CheckError(payload.get("error") or stderr_txt or "privacy_scan failed")
        if rc == EXIT_FINDINGS:
            privacy_status = "findings"
            privacy_findings = payload.get("findings", [])

    secret_failures: list[tuple[str, str]] = []
    secret_checks: list[tuple[str, list[str]]] = []
    if states["staged"] or states["removed_staged"]:
        secret_checks.append(("staged", ["staged"]))
    if states["unstaged"]:
        secret_checks.append(("unstaged", ["files", *states["unstaged"]]))
    if states["untracked"]:
        secret_checks.append(("untracked", ["files", *states["untracked"]]))
    if branch_range:
        secret_checks.append(("branch", ["range", branch_range]))

    for label, s_args in secret_checks:
        rc, out = run_secret_subprocess(
            secret_script,
            s_args,
            root,
            redact_scanner=scanner,
            rules_path=rules_path,
            no_private=not maintainer,
        )
        if rc in (2, 3):
            raise CheckError(out or f"secret_scan ({label}) failed with exit {rc}")
        if rc != 0:
            secret_failures.append((label, out))

    removed = {*states["removed_staged"], *states["removed_unstaged"]}
    all_changed = sorted(
        {*states["staged"], *states["unstaged"], *states["untracked"], *states["branch"], *removed}
    )
    guard_changes = [
        {"path": p, "change": "removed" if p in removed else "changed"}
        for p in guard_trigger_paths(root, all_changed)
    ]
    suite_plan = select_test_suites(root, all_changed)
    md_files = [p for p in all_changed if p.lower().endswith(".md")]
    test_results: list[StepResult] = []
    for suite, (should_run, reason) in suite_plan.items():
        if args.no_tests:
            test_results.append(StepResult(suite, "NOT RUN", 0.0, "skipped by --no-tests"))
        elif should_run:
            test_results.append(run_test_suite(root, suite, md_files))
        else:
            test_results.append(StepResult(suite, "NOT RUN", 0.0, reason))

    elapsed = time.monotonic() - t_total
    failed_tests = [r for r in test_results if r.status in ("FAIL", "ERROR")]
    passed_tests = [r for r in test_results if r.status == "PASS"]
    not_run_tests = [r for r in test_results if r.status == "NOT RUN"]
    overall_ok = not privacy_findings and not secret_failures and not failed_tests

    if args.json_output:
        report = {
            "status": "pass" if overall_ok else "fail",
            "mode": mode_label,
            "release_authorized": False,
            "rules_note": rules_note,
            "base": base_label,
            "states": {k: len(v) for k, v in states.items()},
            "guard_changes": guard_changes,
            "privacy": {"status": privacy_status, "findings": privacy_findings},
            "secrets": {
                "status": "clean" if not secret_failures else "findings",
                "failures": [{"source": src, "detail": det} for src, det in secret_failures],
            },
            "tests": [
                {
                    "name": r.name,
                    "status": r.status,
                    "duration_s": round(r.duration_s, 3),
                    "detail": r.detail,
                }
                for r in test_results
            ],
            "elapsed_s": round(elapsed, 3),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if overall_ok else 1

    qualifier = "" if maintainer else " (contributor check only; NOT a release check)"
    status_word = "PASS" if overall_ok else "FAIL"
    print(
        f"SUMMARY: {status_word}{qualifier} | mode={mode_label} | {rules_note} | "
        f"privacy={privacy_status} | secrets={'clean' if not secret_failures else 'findings'} | "
        f"tests={len(passed_tests)} pass, {len(failed_tests)} fail, {len(not_run_tests)} not run | "
        f"elapsed={elapsed:.2f}s"
    )
    print(
        "STATES: "
        f"staged={len(states['staged'])} unstaged={len(states['unstaged'])} "
        f"untracked={len(states['untracked'])} branch={len(states['branch'])} "
        f"removed={len(removed)}" + (f" (base={base_label})" if base_label else "")
    )
    if guard_changes:
        print("GUARD CHANGES (these select the guard tests):")
        for item in guard_changes:
            print(f"  {item['path']} ({item['change']})")
    if privacy_findings:
        print("PRIVACY FINDINGS:")
        for item in privacy_findings:
            print(f"  {item['where']}:{item['line']}: {item['rule_id']} -- {item['why']}")
    if secret_failures:
        print("SECRET FINDINGS:")
        for source, detail in secret_failures:
            print(f"  [{source}]")
            for line in detail.splitlines():
                print(f"    {line}")
    print("TESTS:")
    for r in test_results:
        print(f"  {r.name}: {r.status} ({r.duration_s:.2f}s) -- {r.detail}")
    return 0 if overall_ok else 1


# --- release manifest --------------------------------------------------------------


def resolve_trusted_commit(root: Path, remote: str, explicit: str | None) -> tuple[str, str]:
    """Resolve trusted baseline ref/commit strictly via full ref or exact 40-hex SHA."""
    if explicit:
        if FULL_SHA_RE.fullmatch(explicit):
            sha = git_optional(
                ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{explicit}^{{commit}}"],
                root,
            )
            if not sha:
                raise CheckError(f"trusted commit not found: {explicit}")
            return explicit, sha
        if not explicit.startswith("refs/"):
            raise CheckError(
                f"--trusted-ref must be a full ref (refs/...) or 40-char SHA, got: {explicit}"
            )
        sha = git_optional(["show-ref", "--verify", "--hash", explicit], root)
        if not sha:
            raise CheckError(f"trusted ref not found: {explicit}")
        commit_sha = git_optional(
            ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{sha}^{{commit}}"], root
        )
        if not commit_sha:
            raise CheckError(f"trusted ref does not point to a commit: {explicit}")
        return explicit, commit_sha

    default_ref = f"refs/remotes/{remote}/main"
    sha = git_optional(["show-ref", "--verify", "--hash", default_ref], root)
    if not sha:
        raise CheckError(
            f"trusted baseline {default_ref} not found; pass --trusted-ref <full-ref-or-sha>"
        )
    commit_sha = git_optional(
        ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{sha}^{{commit}}"], root
    )
    if not commit_sha:
        raise CheckError(f"trusted baseline {default_ref} is not a commit")
    return default_ref, commit_sha


def check_remote_policy(
    root: Path, remote: str, allowed_url: str | None
) -> tuple[str, str, set[str]]:
    """Verify remote list and fetch/push URLs against the single approved repository."""
    remotes = [r for r in git_text(["remote"], root).splitlines() if r.strip()]
    if remote not in remotes:
        raise CheckError(f"remote {remote!r} does not exist (found: {remotes})")
    if len(remotes) != 1:
        raise CheckError(
            f"repository must have exactly one approved remote; found extra remotes: {', '.join(remotes)}"
        )

    fetch_url = git_text(["remote", "get-url", remote], root)
    # git pushes to every push URL of a remote: all of them are read, and there must be one.
    push_urls = git_text(["remote", "get-url", "--push", "--all", remote], root).splitlines()
    if len(push_urls) != 1:
        raise CheckError(
            f"remote '{remote}' must have exactly one push URL; found {len(push_urls)} "
            "(git pushes to every push URL of a remote)"
        )
    push_url = push_urls[0]

    custom_cfg = git_optional(["config", "--get", "genops.allowedPushUrl"], root)
    if allowed_url:
        allowed_set = {allowed_url}
    elif custom_cfg:
        allowed_set = {custom_cfg}
    else:
        allowed_set = set(DEFAULT_ALLOWED_URLS)

    if fetch_url not in allowed_set or push_url not in allowed_set:
        raise CheckError(
            f"remote '{remote}' URLs are not approved (fetch={fetch_url!r}, push={push_url!r})"
        )
    return fetch_url, push_url, allowed_set


def query_remote_ref_sha(root: Path, remote: str, full_ref: str) -> tuple[str, dict[str, str]]:
    """Query the live remote ref SHA via ``git ls-remote``; fail closed if unreachable."""
    proc = run_git(["ls-remote", "--refs", remote], root, check=False)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise CheckError(f"cannot verify remote state via ls-remote ({remote}): {err}")
    refs: dict[str, str] = {}
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) == 2:
            refs[parts[1].strip()] = parts[0].strip()
    return refs.get(full_ref, ZERO_OID), refs


def extract_trusted_bundle(root: Path, trusted_sha: str, dest: Path) -> tuple[dict[str, Path], str]:
    """Extract scanner, rules, wrapper, template and ignore files from ``trusted_sha``."""
    extracted: dict[str, Path] = {}
    hasher = hashlib.sha256()
    hasher.update(f"trusted_sha={trusted_sha}\n".encode("ascii"))

    for rel in TRUSTED_FILES:
        proc = run_git(["cat-file", "-e", f"{trusted_sha}:{rel}"], root, check=False)
        if proc.returncode != 0:
            hasher.update(f"missing:{rel}\n".encode("ascii"))
            continue
        blob = run_git(["show", f"{trusted_sha}:{rel}"], root, check=True).stdout
        out_path = dest / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(blob)
        if rel.endswith(".sh") or rel.endswith(".py"):
            out_path.chmod(0o755)
        extracted[rel] = out_path
        hasher.update(f"file:{rel}:{hashlib.sha256(blob).hexdigest()}\n".encode("ascii"))

    # Include hash of maintainer private rules file without recording any pattern text.
    priv_path = private_rules_path()
    if priv_path.is_file():
        priv_hash = hashlib.sha256(priv_path.read_bytes()).hexdigest()
        hasher.update(f"private_rules:{priv_hash}\n".encode("ascii"))

    # Prepare explicit Betterleaks ignore path from the trusted baseline only.
    ignore_dir = dest / "_trusted_ignore"
    ignore_dir.mkdir(parents=True, exist_ok=True)
    if ".betterleaksignore" in extracted:
        shutil.copy2(extracted[".betterleaksignore"], ignore_dir / ".betterleaksignore")
        ignore_target = ignore_dir / ".betterleaksignore"
    elif ".gitleaksignore" in extracted:
        shutil.copy2(extracted[".gitleaksignore"], ignore_dir / ".gitleaksignore")
        ignore_target = ignore_dir / ".gitleaksignore"
    else:
        ignore_target = ignore_dir / "empty.ignore"
        ignore_target.write_text("", encoding="utf-8")
    extracted["_ignore_path"] = ignore_target
    return extracted, hasher.hexdigest()[:16]


def inspect_control_plane_and_allows(
    root: Path, base_sha: str, candidate_sha: str
) -> tuple[list[str], list[str]]:
    """List control-plane files touched and any newly added inline Betterleaks/Gitleaks allow lines."""
    if base_sha == ZERO_OID or base_sha == candidate_sha:
        raw_names = run_git(["ls-tree", "-r", "--name-only", "-z", candidate_sha], root).stdout
        touched = list(split_names(raw_names))
        diff_text = run_git(
            ["show", "--format=", "--unified=0", candidate_sha], root, check=False
        ).stdout.decode("utf-8", "replace")
    else:
        raw_names = run_git(["diff", "--name-only", "-z", base_sha, candidate_sha], root).stdout
        touched = list(split_names(raw_names))
        diff_text = run_git(
            ["diff", "--unified=0", base_sha, candidate_sha], root, check=False
        ).stdout.decode("utf-8", "replace")

    control_changes = sorted(
        p
        for p in touched
        if p in CONTROL_PLANE_EXACT or p.startswith(CONTROL_PLANE_PREFIXES)
    )

    inline_allows: list[str] = []
    current_file = ""
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            continue
        if line.startswith("+") and not line.startswith("+++"):
            if INLINE_ALLOW_RE.search(line):
                inline_allows.append(current_file or "<unknown>")
    return control_changes, sorted(set(inline_allows))


def collect_release_diff_summary(
    root: Path, remote_old_sha: str, candidate_sha: str
) -> tuple[int, list[dict[str, str]]]:
    if remote_old_sha == ZERO_OID:
        commit_count = int(git_text(["rev-list", "--count", candidate_sha], root))
        names = list(
            split_names(run_git(["ls-tree", "-r", "--name-only", "-z", candidate_sha], root).stdout)
        )
        files = [{"status": "A", "path": n} for n in sorted(names)]
        return commit_count, files

    commit_count = int(git_text(["rev-list", "--count", f"{remote_old_sha}..{candidate_sha}"], root))
    raw = run_git(["diff", "--name-status", "-z", remote_old_sha, candidate_sha], root).stdout
    parts = raw.split(b"\0")
    files: list[dict[str, str]] = []
    idx = 0
    while idx < len(parts):
        status_b = parts[idx]
        idx += 1
        if not status_b:
            continue
        status = status_b.decode("ascii", "replace")
        if idx >= len(parts):
            break
        p1 = os.fsdecode(parts[idx])
        idx += 1
        if status.startswith(("R", "C")):
            if idx >= len(parts):
                break
            p2 = os.fsdecode(parts[idx])
            idx += 1
            files.append({"status": status[0], "path": f"{p1} -> {p2}"})
        else:
            files.append({"status": status[0], "path": p1})
    return commit_count, files


def default_manifest_dir() -> Path:
    return Path.home() / ".cache" / "agent-genops" / "release-manifests"


def ensure_outside_repo(root: Path, target_dir: Path) -> Path:
    resolved_root = root.resolve()
    resolved_dir = target_dir.expanduser().resolve()
    try:
        resolved_dir.relative_to(resolved_root)
    except ValueError:
        return resolved_dir
    raise CheckError(
        f"manifest directory must stay outside the repository (got {resolved_dir} inside {resolved_root})"
    )


def verify_manifest_file(root: Path, manifest_path: Path, args: argparse.Namespace) -> int:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CheckError(f"cannot read manifest {manifest_path}: {exc}") from exc

    remote = data["remote"]
    target_ref = data["target_ref"]
    expected_old = data["remote_old_sha"]
    expected_new = data["candidate_sha"]
    expected_fetch = data["fetch_url"]
    expected_push = data["push_url"]
    expected_policy = data["policy_version"]
    trusted_ref = data["trusted_ref"]

    mismatches: list[str] = []
    try:
        fetch_url, push_url, _ = check_remote_policy(root, remote, args.allowed_url)
    except CheckError as exc:
        mismatches.append(str(exc))
        fetch_url, push_url = "", ""
    else:
        if fetch_url != expected_fetch or push_url != expected_push:
            mismatches.append(
                f"remote URL drifted: expected ({expected_fetch}, {expected_push}), got ({fetch_url}, {push_url})"
            )

    if args.commit and args.commit != expected_new:
        mismatches.append(f"candidate SHA mismatch: manifest={expected_new}, requested={args.commit}")
    if args.ref and args.ref != target_ref:
        mismatches.append(f"target ref mismatch: manifest={target_ref}, requested={args.ref}")

    local_tip = git_optional(["show-ref", "--verify", "--hash", target_ref], root)
    if local_tip and local_tip != expected_new and not args.commit:
        mismatches.append(
            f"local {target_ref} moved since manifest preparation: manifest={expected_new}, current={local_tip}"
        )

    current_old, _ = query_remote_ref_sha(root, remote, target_ref)
    if current_old != expected_old:
        mismatches.append(
            f"remote {target_ref} changed since preparation: manifest={expected_old}, live={current_old}"
        )

    if current_old != ZERO_OID:
        ff = run_git(["merge-base", "--is-ancestor", current_old, expected_new], root, check=False)
        if ff.returncode != 0:
            mismatches.append("candidate is no longer a fast-forward of remote ref")

    try:
        _label, trusted_sha = resolve_trusted_commit(root, remote, trusted_ref)
        with tempfile.TemporaryDirectory(prefix="genops-verify-") as td:
            _, live_policy = extract_trusted_bundle(root, trusted_sha, Path(td))
        if live_policy != expected_policy:
            mismatches.append(
                f"policy version changed: manifest={expected_policy}, live={live_policy}"
            )
    except CheckError as exc:
        mismatches.append(str(exc))

    hook_problems = ensure_hooks_ready(root)
    if hook_problems:
        mismatches.extend(hook_problems)

    if mismatches:
        print("MANIFEST VERIFICATION: INVALID (do NOT push)")
        for item in mismatches:
            print(f"  - {item}")
        return 1

    print(
        f"MANIFEST VERIFICATION: VALID | {remote} {target_ref} "
        f"{expected_old[:12]} -> {expected_new[:12]} | policy={expected_policy}"
    )
    return 0


def validate_target_ref(root: Path, ref: str) -> None:
    """Accept exactly one valid branch ref: ``refs/heads/<name>``, no refspec or pattern syntax."""
    prefix = "refs/heads/"
    problem = None
    if not ref.startswith(prefix) or ref == prefix:
        problem = "it must start with 'refs/heads/' and name a branch"
    elif any(ch in ref for ch in ":*") or any(ch.isspace() for ch in ref):
        problem = "it must not contain ':', '*' or whitespace"
    elif run_git(["check-ref-format", ref], root, check=False).returncode != 0:
        problem = "git check-ref-format rejects it"
    if problem:
        raise CheckError(f"--ref must be one full branch ref (refs/heads/<name>); {problem}, got: {ref!r}")


def cmd_release(args: argparse.Namespace) -> int:
    root = repo_root()
    if args.verify_manifest:
        return verify_manifest_file(root, Path(args.verify_manifest), args)

    if not args.ref or not args.commit:
        raise CheckError("--ref <refs/heads/...> and --commit <40-hex-sha> are required")
    validate_target_ref(root, args.ref)
    if not FULL_SHA_RE.fullmatch(args.commit):
        raise CheckError(f"--commit must be a full 40-char commit SHA, got: {args.commit!r}")
    verified_commit = git_optional(
        ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{args.commit}^{{commit}}"],
        root,
    )
    if verified_commit != args.commit:
        raise CheckError(f"candidate commit not found locally: {args.commit}")

    # Strict maintainer prerequisites (fail closed before touching anything else).
    hook_problems = ensure_hooks_ready(root)
    if hook_problems:
        raise CheckError("; ".join(hook_problems))
    ensure_betterleaks_available()

    if git_text(["rev-parse", "--is-shallow-repository"], root) == "true":
        raise CheckError("shallow clone cannot prepare a release manifest")

    _priv_loaded, private_rule_count, _priv_note = validate_private_rules_file(require_non_empty=True)

    fetch_url, push_url, _ = check_remote_policy(root, args.to, args.allowed_url)
    remote_old_sha, _remote_refs = query_remote_ref_sha(root, args.to, args.ref)

    if remote_old_sha == ZERO_OID:
        if not args.allow_new_ref:
            raise CheckError(
                f"remote ref {args.ref} does not exist; pass --allow-new-ref to explicitly stage a new branch"
            )
    else:
        if remote_old_sha == args.commit:
            raise CheckError(f"remote {args.ref} is already at {args.commit}; nothing to publish")
        ff = run_git(
            ["merge-base", "--is-ancestor", remote_old_sha, args.commit], root, check=False
        )
        if ff.returncode != 0:
            raise CheckError(
                f"non-fast-forward refused: remote {args.ref} ({remote_old_sha[:12]}) is not an ancestor of {args.commit[:12]}"
            )

    trusted_label, trusted_sha = resolve_trusted_commit(root, args.to, args.trusted_ref)
    manifest_dir = ensure_outside_repo(
        root, Path(args.manifest_dir) if args.manifest_dir else default_manifest_dir()
    )

    with tempfile.TemporaryDirectory(prefix="genops-trusted-") as td:
        td_path = Path(td)
        bundle, policy_version = extract_trusted_bundle(root, trusted_sha, td_path)
        if "tools/privacy_scan.py" not in bundle or "tools/privacy_rules.json" not in bundle:
            raise CheckError(
                f"trusted baseline {trusted_sha[:12]} is missing tools/privacy_scan.py or privacy_rules.json"
            )
        if "tools/secret_scan.sh" not in bundle or "tools/secret_scan.tmpl" not in bundle:
            raise CheckError(
                f"trusted baseline {trusted_sha[:12]} is missing tools/secret_scan.sh or secret_scan.tmpl"
            )

        trusted_scanner = bundle["tools/privacy_scan.py"]
        trusted_rules = bundle["tools/privacy_rules.json"]
        trusted_secret = bundle["tools/secret_scan.sh"]
        trusted_ignore = bundle["_ignore_path"]

        scanner_text = trusted_scanner.read_text(encoding="utf-8", errors="replace")
        secret_text = trusted_secret.read_text(encoding="utf-8", errors="replace")
        scanner_has_rev = "--rev" in scanner_text and "--json" in scanner_text
        secret_has_rev = "rev)" in secret_text

        unverified_notes: list[str] = []
        if scanner_has_rev:
            p_rc, p_payload, p_err = run_privacy_subprocess(
                trusted_scanner,
                trusted_rules,
                ["--rev", args.commit, "--ref-name", args.ref],
                root,
                require_private=True,
                no_private=False,
            )
        else:
            unverified_notes.append(
                f"trusted baseline {trusted_sha[:12]} predates --rev; ran baseline + current scanner (review scanner upgrade separately)"
            )
            legacy = subprocess.run(
                [sys.executable, "-I", "-B", str(trusted_scanner), "--rules", str(trusted_rules), "--history"],
                cwd=root,
                env={**os.environ, REQUIRE_PRIVATE_ENV: "1"},
                capture_output=True,
                text=True,
                check=False,
            )
            if legacy.returncode == EXIT_ERROR:
                raise CheckError(legacy.stderr.strip() or "legacy trusted privacy_scan failed")
            if legacy.returncode == EXIT_FINDINGS:
                print("RELEASE BLOCKED: legacy trusted privacy_scan reported findings (no manifest generated).")
                for line in (legacy.stdout + "\n" + legacy.stderr).strip().splitlines():
                    print(f"  {line}")
                return 1
            p_rc, p_payload, p_err = run_privacy_subprocess(
                root / "tools" / "privacy_scan.py",
                trusted_rules,
                ["--rev", args.commit, "--ref-name", args.ref],
                root,
                require_private=True,
                no_private=False,
            )

        if p_rc == EXIT_ERROR:
            raise CheckError(p_payload.get("error") or p_err or "privacy_scan error")
        if p_rc == EXIT_FINDINGS:
            print("RELEASE BLOCKED: candidate failed privacy scan (no approval manifest generated).")
            for item in p_payload.get("findings", []):
                print(f"  {item['where']}:{item['line']}: {item['rule_id']} -- {item['why']}")
            return 1

        redact_helper = (
            trusted_scanner if "--redact-stream" in scanner_text else (root / "tools" / "privacy_scan.py")
        )
        s_mode = ["rev", args.commit] if secret_has_rev else ["history"]
        if not secret_has_rev:
            unverified_notes.append(
                f"trusted baseline {trusted_sha[:12]} predates secret_scan rev mode; ran baseline history mode"
            )
        s_rc, s_out = run_secret_subprocess(
            trusted_secret,
            s_mode,
            root,
            redact_scanner=redact_helper,
            rules_path=trusted_rules,
            no_private=False,
            ignore_path=trusted_ignore,
        )
        if s_rc in (2, 3):
            raise CheckError(s_out or f"trusted secret_scan error (exit {s_rc})")
        if s_rc != 0:
            print("RELEASE BLOCKED: candidate failed Betterleaks scan (no approval manifest generated).")
            for line in s_out.splitlines():
                print(f"  {line}")
            return 1

        other_scanner = trusted_scanner if scanner_has_rev else (root / "tools" / "privacy_scan.py")
        o_rc, o_payload, _o_err = run_privacy_subprocess(
            other_scanner,
            trusted_rules,
            ["--other-refs-except", args.commit],
            root,
            require_private=True,
            no_private=False,
        )
        other_warnings: list[dict[str, Any]] = []
        if o_rc == EXIT_FINDINGS:
            other_warnings = o_payload.get("findings", [])
        elif o_rc == EXIT_ERROR:
            unverified_notes.append("non-candidate local ref scan errored; inspect locally")

    audit_base = remote_old_sha if remote_old_sha != ZERO_OID else trusted_sha
    control_changes, inline_allows = inspect_control_plane_and_allows(root, audit_base, args.commit)
    commit_count, changed_files = collect_release_diff_summary(root, remote_old_sha, args.commit)

    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = {
        "schema_version": 1,
        "created_at": created_at,
        "status": "awaiting_user_approval_not_pushed",
        "action": "push_single_branch_only",
        "remote": args.to,
        "fetch_url": fetch_url,
        "push_url": push_url,
        "target_ref": args.ref,
        "new_ref": remote_old_sha == ZERO_OID,
        "remote_old_sha": remote_old_sha,
        "candidate_sha": args.commit,
        "trusted_ref": trusted_label,
        "trusted_sha": trusted_sha,
        "policy_version": policy_version,
        "commit_count": commit_count,
        "changed_files": changed_files,
        "privacy_scan": {
            "status": "clean",
            "private_rules_loaded": private_rule_count,
        },
        "secret_scan": {"status": "clean", "tool": "betterleaks"},
        "control_plane_changes": control_changes,
        "inline_allow_additions": inline_allows,
        "non_candidate_ref_warnings": other_warnings,
        "unverified_items": unverified_notes,
    }

    manifest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest_file = manifest_dir / f"release-{args.commit[:12]}-{stamp}.json"
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.json_output:
        print(json.dumps({"manifest_path": str(manifest_file), "manifest": manifest}, ensure_ascii=False, indent=2))
        return 0

    old_label = "NEW (000000000000)" if remote_old_sha == ZERO_OID else remote_old_sha
    file_preview = ", ".join(f"{f['status']} {f['path']}" for f in changed_files[:20])
    if len(changed_files) > 20:
        file_preview += f", ... (+{len(changed_files) - 20} more)"
    print("请求：仅推送一个分支；不改可见性，不建 tag，不发 release")
    print(f"目标：{push_url} · {args.ref} · {old_label} -> {args.commit}")
    print(f"改动：{commit_count} 个提交 / {len(changed_files)} 个文件；{file_preview or '(无文件差异)'}")
    print(
        f"隐私：维护者规则已加载（{private_rule_count} 条）；历史、路径和 ref 通过；"
        f"Betterleaks 通过；策略版本 {policy_version}（trusted={trusted_sha[:12]}）"
    )
    print(
        f"需人决定：控制面改动 {len(control_changes)}；新增行内豁免 {len(inline_allows)}；"
        f"非候选本地 ref 告警 {len(other_warnings)}；未验证项 {len(unverified_notes)}"
    )
    if control_changes:
        print(f"  控制面变更（需独立复核）：{', '.join(control_changes)}")
    if inline_allows:
        print(f"  新增行内豁免（需独立复核）：{', '.join(inline_allows)}")
    if other_warnings:
        print(
            f"  本地其他未推 ref 告警（不影响本次候选）：{len(other_warnings)} 条（详见本机扫描）"
        )
    if unverified_notes:
        for note in unverified_notes:
            print(f"  未验证项：{note}")
    print(
        "当前状态：等待用户同意；尚未推送。目标、SHA 或策略版本变化时本清单作废。"
    )
    print(f"仓外核对记录：{manifest_file}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="./check",
        description="Local verification and read-only release manifest tool for agent-genops.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_changed = sub.add_parser(
        "changed",
        help="scan staged, unstaged, untracked and branch changes, then run path-selected tests",
    )
    p_changed.add_argument("--maintainer", action="store_true", help="enforce maintainer private rules")
    p_changed.add_argument(
        "--contributor", action="store_true", help="run contributor mode (public rules only)"
    )
    p_changed.add_argument("--base", help="base ref/commit for scanning unmerged branch commits")
    p_changed.add_argument("--no-tests", action="store_true", help="skip test suites (marked NOT RUN)")
    p_changed.add_argument("--json", dest="json_output", action="store_true", help="emit JSON report")

    p_release = sub.add_parser(
        "release",
        help="verify one exact (remote, ref, commit) candidate and write a redacted manifest (never pushes)",
    )
    p_release.add_argument("--to", default="origin", help="remote name (default: origin)")
    p_release.add_argument("--ref", help="full target branch ref (e.g. refs/heads/main)")
    p_release.add_argument("--commit", help="full 40-char candidate commit SHA")
    p_release.add_argument(
        "--allow-new-ref",
        action="store_true",
        help="explicitly allow staging a manifest for a ref that does not yet exist on the remote",
    )
    p_release.add_argument(
        "--trusted-ref",
        help="full ref (refs/...) or 40-char commit SHA from which trusted scanners/rules are loaded",
    )
    p_release.add_argument(
        "--allowed-url",
        help="override approved remote URL (for local bare-repo rehearsal tests)",
    )
    p_release.add_argument(
        "--manifest-dir",
        help="out-of-repo directory for manifest snapshots (default: ~/.cache/agent-genops/release-manifests)",
    )
    p_release.add_argument(
        "--verify-manifest",
        help="re-verify an existing manifest snapshot against live remote/local state before pushing",
    )
    p_release.add_argument("--json", dest="json_output", action="store_true", help="emit JSON output")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "changed":
            return cmd_changed(args)
        if args.command == "release":
            return cmd_release(args)
        parser.error(f"unknown command: {args.command}")
    except CheckError as exc:
        if getattr(args, "json_output", False):
            print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"check: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
