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
    ``(remote, ref, commit)`` candidate. The copy in the working tree only launches: the checker,
    the scanners and the rules that judge are exported from the trusted baseline (the remote's
    main) and run from a temporary directory. Never pushes.
  - ``protocol``: the release protocol this checker speaks, as JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
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
MAINTAINER_MODE_VALUE = "maintainer"
CONTRIBUTOR_MODE_VALUE = "contributor"

ZERO_OID = "0" * 40
# How long a git call that talks to the remote may take. The variable can only shorten it (tests
# use it); the release check runs the baseline's copy of this constant, not the candidate's.
REMOTE_TIMEOUT_S = 30.0
REMOTE_TIMEOUT_ENV = "AGENT_GENOPS_REMOTE_TIMEOUT_S"
# After a timeout stops git's process group, how long to wait for its pipes to close before giving up on them.
REMOTE_DRAIN_S = 2.0
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# Betterleaks honours an inline allow wherever the substring appears on a line
# (`# _gitleaks:allow` and `nobetterleaks:allow` included), so it is counted the same way.
INLINE_ALLOW_RE = re.compile(r"(?:betterleaks|gitleaks):allow")
# A Betterleaks fingerprint of a finding in git history: <commit>:<path>:<rule>:<line>.
FINGERPRINT_RE = re.compile(r"[0-9a-f]{40}:[^\r\n]+:[^:\s]+:[0-9]+")
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
        "tools/workflow_policy.py",
        "tools/workflow_policy.json",
    }
)
# Every git diff that builds a change list reads a rename as a removal plus an addition: with rename
# detection on, git names only the new path, and a guard file moved away would drop off the list.
NO_RENAMES = "--no-renames"
# Every test under the root tests/ is a guard test.
CONTROL_PLANE_PREFIXES = (".githooks/", ".github/workflows/", "tests/")
DOC_SUFFIXES = frozenset({".md", ".svg", ".txt"})
DOC_EXACT = frozenset({"LICENSE", "LICENSE-APACHE", "LICENSE-MIT"})
GUARD_TEST_PREFIXES = (".githooks/", "tools/", "tests/", "workflows/")
WORKFLOW_POLICY_PATHS = frozenset({"tools/workflow_policy.py", "tools/workflow_policy.json"})
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

# The release protocol: a checker that answers ``protocol`` with this number can judge a release
# handed to it by ./check release (``--as-trusted-checker``).
RELEASE_PROTOCOL = 1
BOOTSTRAP_FLAG = "--bootstrap-self-judge"
# Exported from the judging commit; the checker uses only the copies beside it.
CHECKER_FILES = (
    "tools/release_check.py",
    "tools/privacy_scan.py",
    "tools/privacy_rules.json",
    "tools/secret_scan.sh",
    "tools/secret_scan.tmpl",
)
OPTIONAL_CHECKER_FILES = ("tools/workflow_policy.py",)
# The one list of what is exported, hashed into the policy version, and checked by the exported
# checker against the judging commit before it judges.
EXPORTED_CHECKER_FILES = CHECKER_FILES + OPTIONAL_CHECKER_FILES
IGNORE_FILES = (".betterleaksignore", ".gitleaksignore")
WORKFLOW_RELEASE_PATHS = ("workflows", "tools/workflow_policy.json")


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


def remote_timeout() -> float:
    raw = os.environ.get(REMOTE_TIMEOUT_ENV)
    if raw is None:
        return REMOTE_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        value = float("nan")
    if not (0 < value < float("inf")):
        raise CheckError(f"{REMOTE_TIMEOUT_ENV} must be a positive number of seconds, got {raw!r}")
    return min(value, REMOTE_TIMEOUT_S)


def run_git_remote(args: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
    """A git call that talks to the remote: refused, never left hanging, past ``remote_timeout()``.

    git and its transport (ssh, a credential helper) run in a session of their own, and the whole
    group is stopped on timeout, so no transport process outlives the check. A process that left
    the group and still holds git's pipes gets ``REMOTE_DRAIN_S`` to let go; then the pipes are
    closed on this side and the call is refused all the same."""
    timeout = remote_timeout()
    cmd = ["git", "--no-replace-objects", *args]
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True
        )
    except OSError as exc:
        raise CheckError(f"cannot execute git: {exc}") from exc
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.communicate(timeout=REMOTE_DRAIN_S)
        except subprocess.TimeoutExpired:
            # A process that left the group (setsid) still holds git's pipes: stop reading them.
            # git itself was in the group, so it is dead and the wait below returns.
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()
            proc.wait()
        raise CheckError(
            f"git {args[0]} did not answer within {timeout:g} s; the remote was not checked, so nothing is approved"
        ) from None
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def git_text(args: list[str], cwd: Path) -> str:
    return run_git(args, cwd, check=True).stdout.decode("utf-8", "replace").strip()


def git_optional(args: list[str], cwd: Path) -> str | None:
    proc = run_git(args, cwd, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace").strip()


def repo_root(cwd: Path | None = None) -> Path:
    return Path(git_text(["rev-parse", "--show-toplevel"], cwd or Path.cwd()))


def clone_mode_is_maintainer(root: Path) -> bool:
    """Ask the scanner for the clone mode: its ``--clone-mode`` is the one reading of
    ``genops.mode`` (the hooks use it too). Anything but its two answers stops the check."""
    scanner = root / "tools" / "privacy_scan.py"
    cmd = [sys.executable, "-I", "-B", str(scanner), "--clone-mode"]
    try:
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise CheckError(f"cannot read the clone mode: cannot run {scanner.name}: {exc}") from exc
    answer = proc.stdout.strip()
    if proc.returncode != 0 or answer not in (MAINTAINER_MODE_VALUE, CONTRIBUTOR_MODE_VALUE):
        detail = proc.stderr.strip() or f"exit {proc.returncode}, answer {answer!r}"
        raise CheckError(f"cannot read the clone mode from tools/privacy_scan.py --clone-mode: {detail}")
    return answer == MAINTAINER_MODE_VALUE


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
    run_policy = any(p.startswith("workflows/") or p in WORKFLOW_POLICY_PATHS for p in changed_paths)
    run_guard = bool(guard_trigger_paths(root, changed_paths))

    return {
        "doc-links": (
            run_doc_links,
            f"{len(md_files)} markdown file(s) changed" if run_doc_links else "no markdown changes",
        ),
        "workflow-policy": (
            run_policy,
            "workflows/ or its policy changed" if run_policy else "workflows/ and its policy untouched",
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


def run_workflow_policy(root: Path) -> StepResult:
    """Run tools/workflow_policy.py: exit 0 is clean, 1 findings, anything else an error."""
    t0 = time.monotonic()
    script = root / "tools" / "workflow_policy.py"
    if not script.is_file():
        return StepResult("workflow-policy", "ERROR", 0.0, "tools/workflow_policy.py is missing")
    proc = subprocess.run(
        [sys.executable, "-I", "-B", str(script)], cwd=root, capture_output=True, text=True, check=False
    )
    dt = time.monotonic() - t0
    tail = "\n".join((proc.stdout + "\n" + proc.stderr).strip().splitlines()[-15:])
    if proc.returncode == 0:
        return StepResult("workflow-policy", "PASS", dt, "workflows/ matches its policy")
    status = "FAIL" if proc.returncode == 1 else "ERROR"
    return StepResult("workflow-policy", status, dt, tail or f"exit {proc.returncode}")


def run_test_suite(root: Path, suite: str, md_files: list[str]) -> StepResult:
    t0 = time.monotonic()
    if suite == "doc-links":
        broken = check_relative_links(root, md_files)
        dt = time.monotonic() - t0
        if broken:
            return StepResult(suite, "FAIL", dt, "\n".join(broken))
        return StepResult(suite, "PASS", dt, f"checked {len(set(md_files))} markdown file(s)")

    if suite == "workflow-policy":
        return run_workflow_policy(root)

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
            run_git(["diff", NO_RENAMES, "--cached", "--name-only", "-z", "--diff-filter=ACMRT"], root).stdout
        )
    )
    unstaged = list(
        split_names(run_git(["diff", NO_RENAMES, "--name-only", "-z", "--diff-filter=ACMRT"], root).stdout)
    )
    removed_staged = list(
        split_names(
            run_git(["diff", NO_RENAMES, "--cached", "--name-only", "-z", "--diff-filter=D"], root).stdout
        )
    )
    removed_unstaged = list(
        split_names(run_git(["diff", NO_RENAMES, "--name-only", "-z", "--diff-filter=D"], root).stdout)
    )
    untracked = list(
        split_names(run_git(["ls-files", "--others", "--exclude-standard", "-z"], root).stdout)
    )
    branch_files: list[str] = []
    if merge_base:
        count = int(git_text(["rev-list", "--count", f"{merge_base}..HEAD"], root))
        if count > 0:
            branch_files = list(
                split_names(run_git(["diff", NO_RENAMES, "--name-only", "-z", f"{merge_base}..HEAD"], root).stdout)
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
        maintainer = clone_mode_is_maintainer(root)

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
        if args.no_tests and suite != "workflow-policy":
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


BASELINE_BRANCH = "refs/heads/main"


def resolve_trusted_baseline(root: Path, remote: str, remote_refs: dict[str, str]) -> tuple[str, str]:
    """The trusted baseline is the commit the remote's main holds now (from ``git ls-remote``).

    The local tracking ref must hold the same commit: a stale or moved local copy is refused, so a
    commit that never reached the remote cannot become the judge. Returns ``(label, sha)``."""
    live = remote_refs.get(BASELINE_BRANCH)
    if not live or live == ZERO_OID:
        raise CheckError(
            f"remote {remote!r} has no {BASELINE_BRANCH}, so there is no trusted baseline to judge with"
        )
    tracking = f"refs/remotes/{remote}/main"
    local = git_optional(["show-ref", "--verify", "--hash", tracking], root)
    if local != live:
        raise CheckError(
            f"local {tracking} ({(local or 'missing')[:12]}) is not the remote's {BASELINE_BRANCH} "
            f"({live[:12]}); run 'git fetch {remote}' and retry"
        )
    commit_sha = git_optional(
        ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{live}^{{commit}}"], root
    )
    if commit_sha != live:
        raise CheckError(
            f"the remote's {BASELINE_BRANCH} ({live[:12]}) is not a commit in this clone; run 'git fetch {remote}' and retry"
        )
    return f"{remote} {BASELINE_BRANCH}", live


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
    proc = run_git_remote(["ls-remote", "--refs", remote], root)
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


def inspect_control_plane_and_allows(
    root: Path, base_sha: str, candidate_sha: str
) -> tuple[list[str], list[str]]:
    """List control-plane files touched and any newly added inline Betterleaks/Gitleaks allow lines."""
    if base_sha == ZERO_OID or base_sha == candidate_sha:
        raw_names = run_git(["ls-tree", "-r", "--name-only", "-z", candidate_sha], root).stdout
        touched = list(split_names(raw_names))
        diff_text = run_git(
            ["show", NO_RENAMES, "--format=", "--unified=0", candidate_sha], root, check=False
        ).stdout.decode("utf-8", "replace")
    else:
        raw_names = run_git(["diff", NO_RENAMES, "--name-only", "-z", base_sha, candidate_sha], root).stdout
        touched = list(split_names(raw_names))
        diff_text = run_git(
            ["diff", NO_RENAMES, "--unified=0", base_sha, candidate_sha], root, check=False
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
    raw = run_git(["diff", NO_RENAMES, "--name-status", "-z", remote_old_sha, candidate_sha], root).stdout
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


@dataclass(frozen=True)
class Judge:
    """Who judges a release: the checker and scanners exported from one commit."""

    tools: Path  # directory holding the exported checker, scanners and rules
    trusted_sha: str  # the remote main the release is judged against (its ignore file applies)
    checker_sha: str  # where the checker and scanners came from
    self_judged: bool  # True only under --bootstrap-self-judge: the candidate's own tools


def export_checker(root: Path, sha: str, dest: Path) -> Path:
    """Write the release checker, its scanners and rules from ``sha`` into ``dest/tools``.

    Raises CheckError naming the first required file ``sha`` lacks."""
    tools = dest / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    for rel in EXPORTED_CHECKER_FILES:
        proc = run_git(["cat-file", "blob", f"{sha}:{rel}"], root, check=False)
        if proc.returncode != 0:
            if rel in CHECKER_FILES:
                raise CheckError(f"commit {sha[:12]} has no {rel}")
            continue
        out_path = dest / rel
        out_path.write_bytes(proc.stdout)
        out_path.chmod(0o755 if rel.endswith((".py", ".sh")) else 0o644)
    return tools


def checker_speaks_protocol(script: Path, root: Path) -> bool:
    """Ask an exported checker for its protocol; anything but the expected answer is a no."""
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-B", str(script), "protocol"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if proc.returncode != 0:
        return False
    try:
        answer = json.loads(proc.stdout)
    except ValueError:
        return False
    return isinstance(answer, dict) and answer.get("release_protocol") == RELEASE_PROTOCOL


def bootstrap_hint(trusted_sha: str, what: str) -> str:
    return (
        f"the trusted baseline {trusted_sha[:12]} {what}, so it cannot judge this release. "
        f"Only with {BOOTSTRAP_FLAG} does the candidate's own checker judge it; the manifest then "
        "says the candidate judged itself and needs an independent review"
    )


def write_trusted_ignore(root: Path, trusted_sha: str, approvals: list[str], dest: Path) -> tuple[Path, bytes]:
    """The one ignore list for Betterleaks: the trusted baseline's ignore file plus approvals."""
    content = b""
    for name in IGNORE_FILES:
        proc = run_git(["cat-file", "blob", f"{trusted_sha}:{name}"], root, check=False)
        if proc.returncode == 0:
            content = proc.stdout
            break
    if approvals:
        if content and not content.endswith(b"\n"):
            content += b"\n"
        content += "".join(f"{fp}\n" for fp in approvals).encode("utf-8")
    ignore_dir = dest / "_ignore"
    ignore_dir.mkdir(parents=True, exist_ok=True)
    target = ignore_dir / ".betterleaksignore"
    target.write_bytes(content)
    return target, content


def compute_policy_version(judge: Judge, ignore_bytes: bytes) -> str:
    hasher = hashlib.sha256()
    hasher.update(f"protocol={RELEASE_PROTOCOL}\nchecker_sha={judge.checker_sha}\n".encode("ascii"))
    hasher.update(f"trusted_sha={judge.trusted_sha}\n".encode("ascii"))
    for rel in EXPORTED_CHECKER_FILES:
        path = judge.tools.parent / rel
        if path.is_file():
            hasher.update(f"file:{rel}:{hashlib.sha256(path.read_bytes()).hexdigest()}\n".encode("ascii"))
        else:
            hasher.update(f"missing:{rel}\n".encode("ascii"))
    hasher.update(f"ignore:{hashlib.sha256(ignore_bytes).hexdigest()}\n".encode("ascii"))
    # The private rules count by hash only; no pattern text is recorded.
    priv_path = private_rules_path()
    if priv_path.is_file():
        hasher.update(f"private_rules:{hashlib.sha256(priv_path.read_bytes()).hexdigest()}\n".encode("ascii"))
    return hasher.hexdigest()[:16]


def export_paths(root: Path, commit: str, paths: list[str], dest: Path) -> None:
    """Write ``paths`` of ``commit``'s tree under ``dest`` as git stores them (links stay links)."""
    listing = run_git(["ls-tree", "-r", "-z", "--full-tree", commit, "--", *paths], root).stdout
    for entry in split_names(listing):
        meta, _, rel = entry.partition("\t")
        mode, kind, oid = meta.split(" ")
        parts = rel.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise CheckError(f"commit {commit[:12]} holds a path git should not store: {rel!r}")
        target = dest.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        if kind == "commit":
            target.mkdir(exist_ok=True)  # a submodule: a folder the policy does not know
        elif mode == "120000":
            os.symlink(run_git(["cat-file", "blob", oid], root).stdout, target)
        else:
            target.write_bytes(run_git(["cat-file", "blob", oid], root).stdout)


def candidate_workflow_paths(root: Path, commit: str) -> list[str]:
    """The workflow-policy inputs ``commit`` holds (workflows/, the registry)."""
    return [
        rel
        for rel in WORKFLOW_RELEASE_PATHS
        if run_git(["cat-file", "-e", f"{commit}:{rel}"], root, check=False).returncode == 0
    ]


def trusted_baseline_gap(root: Path, trusted_sha: str, candidate: str) -> str | None:
    """Why the trusted baseline cannot judge ``candidate``, or None when it can.

    The one reading of "the baseline can judge", used by the launcher (which baseline to export)
    and by the checker itself (whether --bootstrap-self-judge may stand)."""
    with tempfile.TemporaryDirectory(prefix="genops-baseline-") as td:
        try:
            tools = export_checker(root, trusted_sha, Path(td))
        except CheckError as exc:
            return f"cannot supply the checker ({exc})"
        if not checker_speaks_protocol(tools / "release_check.py", root):
            return f"has no release checker that speaks protocol {RELEASE_PROTOCOL}"
        if not (tools / "workflow_policy.py").is_file() and candidate_workflow_paths(root, candidate):
            return "has no tools/workflow_policy.py"
    return None


def refuse_needless_bootstrap(root: Path, trusted_sha: str, candidate: str) -> None:
    if trusted_baseline_gap(root, trusted_sha, candidate) is None:
        raise CheckError(
            f"{BOOTSTRAP_FLAG} refused: the trusted baseline {trusted_sha[:12]} can judge this release, "
            f"so the candidate may not judge itself; run without {BOOTSTRAP_FLAG}"
        )


def run_release_workflow_policy(root: Path, judge: Judge, commit: str, dest: Path) -> tuple[str, str]:
    """Check the candidate's workflows/ with the judge's policy checker and the candidate's registry.

    Returns ``(status, detail)``: ``clean``, ``findings`` or ``not_applicable`` (the candidate has
    neither workflows/ nor the registry, so there is nothing for the policy to cover)."""
    present = candidate_workflow_paths(root, commit)
    if not present:
        return "not_applicable", "the candidate has no workflows/ and no tools/workflow_policy.json"
    checker = judge.tools / "workflow_policy.py"
    if not checker.is_file():
        if judge.self_judged:
            raise CheckError(f"the candidate {commit[:12]} has workflows but no tools/workflow_policy.py")
        raise CheckError(bootstrap_hint(judge.trusted_sha, "has no tools/workflow_policy.py"))
    tree = dest / "candidate"
    tree.mkdir()
    export_paths(root, commit, present, tree)
    proc = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(checker),
            "--root",
            str(tree / "workflows"),
            "--policy",
            str(tree / "tools" / "workflow_policy.json"),
        ],
        cwd=tree,
        capture_output=True,
        text=True,
        check=False,
    )
    detail = (proc.stdout + "\n" + proc.stderr).strip()
    if proc.returncode == 0:
        return "clean", detail
    if proc.returncode == 1:
        return "findings", detail
    raise CheckError(f"workflow policy check failed (exit {proc.returncode}): {detail[-800:]}")


def parse_approvals(values: list[str] | None) -> list[str]:
    """Each --approve-exemption is one Betterleaks fingerprint, nothing wider."""
    out: list[str] = []
    for value in values or []:
        if not FINGERPRINT_RE.fullmatch(value):
            raise CheckError(
                "--approve-exemption takes one Betterleaks fingerprint <40-hex commit>:<path>:<rule>:<line> "
                f"per flag, got: {value!r}"
            )
        out.append(value)
    return sorted(dict.fromkeys(out))


def count_findings(scan_output: str) -> int | None:
    """Findings secret_scan.sh printed (one indented line each); None when redaction failed."""
    lines = [line for line in scan_output.splitlines() if line.startswith("  ")]
    if any("<redacted:" in line for line in lines):
        return None
    return len(lines)


def candidate_ignore_bytes(root: Path, commit: str) -> bytes:
    """The ignore entries the candidate carries itself (any of the ignore file names)."""
    content = b""
    for name in IGNORE_FILES:
        proc = run_git(["cat-file", "blob", f"{commit}:{name}"], root, check=False)
        if proc.returncode == 0:
            content += proc.stdout if proc.stdout.endswith(b"\n") or not proc.stdout else proc.stdout + b"\n"
    return content


def scan_own_commits(
    root: Path,
    judge: Judge,
    secret: Path,
    scanner: Path,
    rules: Path,
    ignore_path: Path,
    ignore_bytes: bytes,
    audit_base: str,
    commit: str,
    dest: Path,
) -> list[str]:
    """Scan ``audit_base..commit`` with the trusted ignore file (plus approvals) and inline allow
    comments off. Returns the report lines when it finds something, else an empty list.

    On findings it scans once more honouring what the candidate adds itself (its inline allow
    comments and its own ignore file) to say how many of them those exemptions would hide."""
    spec = f"{audit_base}..{commit}"
    rc, out = run_secret_subprocess(
        secret, ["range", spec], root, redact_scanner=scanner, rules_path=rules,
        no_private=False, ignore_path=ignore_path, ignore_allow=True,
    )
    if rc in (2, 3):
        raise CheckError(out or f"secret_scan error (exit {rc})")
    if rc == 0:
        return []
    found = count_findings(out)
    own_dir = dest / "_candidate_ignore"
    own_dir.mkdir(parents=True, exist_ok=True)
    own_ignore = own_dir / ".betterleaksignore"
    trusted = ignore_bytes if ignore_bytes.endswith(b"\n") or not ignore_bytes else ignore_bytes + b"\n"
    own_ignore.write_bytes(trusted + candidate_ignore_bytes(root, commit))
    rc_own, out_own = run_secret_subprocess(
        secret, ["range", spec], root, redact_scanner=scanner, rules_path=rules,
        no_private=False, ignore_path=own_ignore,
    )
    if rc_own in (2, 3):
        raise CheckError(out_own or f"secret_scan error (exit {rc_own})")
    left = 0 if rc_own == 0 else count_findings(out_own)
    if found is None or left is None:
        hidden = "an unknown number (path redaction failed)"
        found_text = "an unknown number of"
    else:
        hidden = str(max(found - left, 0))
        found_text = str(found)
    return [
        "RELEASE BLOCKED: candidate failed Betterleaks scan of its own commits "
        f"({audit_base[:12]}..{commit[:12]}, trusted ignore file, inline allow comments off; "
        "no approval manifest generated).",
        f"  {found_text} finding(s); {hidden} of them would be hidden by exemptions the candidate adds itself "
        "(inline allow comments or its own ignore file), which this check does not honour.",
        "  To release anyway the user approves each finding by its fingerprint "
        "(<commit>:<path>:<rule>:<line>), and the check runs again with one "
        "--approve-exemption <fingerprint> per finding; the manifest records them.",
        *(f"  {line}" for line in out.splitlines()),
    ]


@dataclass
class ReleaseResult:
    blocked: list[str]  # report lines when the release is blocked; empty when it passes
    manifest: dict[str, Any] | None


def blocked(*lines: str) -> ReleaseResult:
    return ReleaseResult(list(lines), None)


def prepare_release(
    root: Path,
    judge: Judge,
    *,
    remote: str,
    ref: str,
    commit: str,
    allow_new_ref: bool,
    allowed_url: str | None,
    approvals: list[str],
) -> ReleaseResult:
    """Every release check for one ``(remote, ref, commit)``; writes nothing to the repository."""
    validate_target_ref(root, ref)
    approvals = parse_approvals(approvals)
    if not FULL_SHA_RE.fullmatch(commit):
        raise CheckError(f"--commit must be a full 40-char commit SHA, got: {commit!r}")
    verified_commit = git_optional(
        ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{commit}^{{commit}}"], root
    )
    if verified_commit != commit:
        raise CheckError(f"candidate commit not found locally: {commit}")

    hook_problems = ensure_hooks_ready(root)
    if hook_problems:
        raise CheckError("; ".join(hook_problems))
    ensure_betterleaks_available()
    if git_text(["rev-parse", "--is-shallow-repository"], root) == "true":
        raise CheckError("shallow clone cannot prepare a release manifest")
    _priv_loaded, private_rule_count, _priv_note = validate_private_rules_file(require_non_empty=True)

    fetch_url, push_url, approved_urls = check_remote_policy(root, remote, allowed_url)
    rehearsal_remote = approved_urls != DEFAULT_ALLOWED_URLS
    remote_old_sha, remote_refs = query_remote_ref_sha(root, remote, ref)
    trusted_label, live_trusted = resolve_trusted_baseline(root, remote, remote_refs)
    if live_trusted != judge.trusted_sha:
        raise CheckError(
            f"the remote's {BASELINE_BRANCH} moved during the check ({judge.trusted_sha[:12]} -> {live_trusted[:12]}); retry"
        )

    if remote_old_sha == ZERO_OID:
        if not allow_new_ref:
            raise CheckError(
                f"remote ref {ref} does not exist; pass --allow-new-ref to explicitly stage a new branch"
            )
    else:
        if remote_old_sha == commit:
            raise CheckError(f"remote {ref} is already at {commit}; nothing to publish")
        ff = run_git(["merge-base", "--is-ancestor", remote_old_sha, commit], root, check=False)
        if ff.returncode != 0:
            raise CheckError(
                f"non-fast-forward refused: remote {ref} ({remote_old_sha[:12]}) is not an ancestor of {commit[:12]}"
            )

    scanner = judge.tools / "privacy_scan.py"
    rules = judge.tools / "privacy_rules.json"
    secret = judge.tools / "secret_scan.sh"
    unverified_notes: list[str] = []
    if rehearsal_remote:
        unverified_notes.append(
            f"rehearsal: the remote ({push_url}) is not the repository's own, so its main is the trusted baseline "
            "only because the caller named that remote with --allowed-url or genops.allowedPushUrl; "
            "this manifest does not clear a release to the repository"
        )
    if judge.self_judged:
        unverified_notes.append(
            f"bootstrap: the candidate's own checker and scanners ({judge.checker_sha[:12]}) judged it, "
            f"because the trusted baseline {judge.trusted_sha[:12]} could not; needs an independent review"
        )

    with tempfile.TemporaryDirectory(prefix="genops-release-") as td:
        td_path = Path(td)
        ignore_path, ignore_bytes = write_trusted_ignore(root, judge.trusted_sha, approvals, td_path)
        policy_version = compute_policy_version(judge, ignore_bytes)
        audit_base = remote_old_sha if remote_old_sha != ZERO_OID else judge.trusted_sha

        p_rc, p_payload, p_err = run_privacy_subprocess(
            scanner, rules, ["--rev", commit, "--ref-name", ref], root, require_private=True, no_private=False
        )
        if p_rc == EXIT_ERROR or p_payload.get("status") == "error":
            raise CheckError(p_payload.get("error") or p_err or "privacy_scan error")
        if p_rc == EXIT_FINDINGS:
            return blocked(
                "RELEASE BLOCKED: candidate failed privacy scan (no approval manifest generated).",
                *(
                    f"  {item['where']}:{item['line']}: {item['rule_id']} -- {item['why']}"
                    for item in p_payload.get("findings", [])
                ),
            )
        if p_rc != 0:
            raise CheckError(f"privacy_scan exited {p_rc}")

        # The candidate's own commits first, with inline allow comments off: an exemption the
        # candidate adds cannot clear itself.
        own = scan_own_commits(root, judge, secret, scanner, rules, ignore_path, ignore_bytes, audit_base, commit, td_path)
        if own:
            return blocked(*own)

        s_rc, s_out = run_secret_subprocess(
            secret,
            ["rev", commit],
            root,
            redact_scanner=scanner,
            rules_path=rules,
            no_private=False,
            ignore_path=ignore_path,
        )
        if s_rc in (2, 3):
            raise CheckError(s_out or f"secret_scan error (exit {s_rc})")
        if s_rc != 0:
            return blocked(
                "RELEASE BLOCKED: candidate failed Betterleaks scan (no approval manifest generated).",
                *(f"  {line}" for line in s_out.splitlines()),
            )

        wf_status, wf_detail = run_release_workflow_policy(root, judge, commit, td_path)
        if wf_status == "findings":
            return blocked(
                "RELEASE BLOCKED: candidate's workflows/ failed the workflow policy (no approval manifest generated).",
                *(f"  {line}" for line in wf_detail.splitlines()),
            )

        o_rc, o_payload, _o_err = run_privacy_subprocess(
            scanner, rules, ["--other-refs-except", commit], root, require_private=True, no_private=False
        )
        other_warnings: list[dict[str, Any]] = []
        if o_rc == EXIT_FINDINGS:
            other_warnings = o_payload.get("findings", [])
        elif o_rc != 0:
            unverified_notes.append("non-candidate local ref scan errored; inspect locally")

    control_changes, inline_allows = inspect_control_plane_and_allows(root, audit_base, commit)
    commit_count, changed_files = collect_release_diff_summary(root, remote_old_sha, commit)

    return ReleaseResult(
        [],
        {
            "schema_version": 2,
            "status": "awaiting_user_approval_not_pushed",
            "action": "push_single_branch_only",
            "remote": remote,
            "fetch_url": fetch_url,
            "push_url": push_url,
            "target_ref": ref,
            "new_ref": remote_old_sha == ZERO_OID,
            "remote_old_sha": remote_old_sha,
            "candidate_sha": commit,
            "trusted_ref": trusted_label,
            "trusted_sha": judge.trusted_sha,
            "checker_sha": judge.checker_sha,
            "self_judged": judge.self_judged,
            "rehearsal_remote": rehearsal_remote,
            "policy_version": policy_version,
            "commit_count": commit_count,
            "changed_files": changed_files,
            "privacy_scan": {"status": "clean", "private_rules_loaded": private_rule_count},
            "secret_scan": {"status": "clean", "tool": "betterleaks"},
            "workflow_policy": wf_status,
            "control_plane_changes": control_changes,
            "inline_allow_additions": inline_allows,
            "approved_exemptions": approvals,
            "non_candidate_ref_warnings": other_warnings,
            "unverified_items": unverified_notes,
        },
    )


def read_manifest(manifest_path: Path) -> dict[str, Any]:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CheckError(f"cannot read manifest {manifest_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CheckError(f"manifest {manifest_path} is not a JSON object")
    for key in ("remote", "target_ref", "candidate_sha"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise CheckError(f"manifest {manifest_path} has no {key}")
    return data


def verify_manifest_file(root: Path, judge: Judge, manifest_path: Path, args: argparse.Namespace) -> int:
    data = read_manifest(manifest_path)
    remote = data["remote"]
    target_ref = data["target_ref"]
    expected_old = data.get("remote_old_sha")
    expected_new = data["candidate_sha"]
    expected_fetch = data.get("fetch_url")
    expected_push = data.get("push_url")
    expected_policy = data.get("policy_version")

    mismatches: list[str] = []
    try:
        fetch_url, push_url, _ = check_remote_policy(root, remote, args.allowed_url)
    except CheckError as exc:
        mismatches.append(str(exc))
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

    current_old, live_refs = query_remote_ref_sha(root, remote, target_ref)
    if current_old != expected_old:
        mismatches.append(
            f"remote {target_ref} changed since preparation: manifest={expected_old}, live={current_old}"
        )

    if current_old != ZERO_OID:
        ff = run_git(["merge-base", "--is-ancestor", current_old, expected_new], root, check=False)
        if ff.returncode != 0:
            mismatches.append("candidate is no longer a fast-forward of remote ref")

    try:
        _label, live_trusted = resolve_trusted_baseline(root, remote, live_refs)
        if live_trusted != judge.trusted_sha:
            raise CheckError(f"the remote's {BASELINE_BRANCH} moved during the check; retry")
        with tempfile.TemporaryDirectory(prefix="genops-verify-") as td:
            _path, ignore_bytes = write_trusted_ignore(
                root, judge.trusted_sha, parse_approvals(args.approve_exemption), Path(td)
            )
        live_policy = compute_policy_version(judge, ignore_bytes)
        if live_policy != expected_policy:
            mismatches.append(f"policy version changed: manifest={expected_policy}, live={live_policy}")
    except CheckError as exc:
        mismatches.append(str(exc))

    hook_problems = ensure_hooks_ready(root)
    if hook_problems:
        mismatches.extend(hook_problems)

    mismatches.extend(recheck_manifest(root, judge, data, args))

    if mismatches:
        print("MANIFEST VERIFICATION: INVALID (do NOT push)")
        for item in mismatches:
            print(f"  - {item}")
        return 1

    print(
        f"MANIFEST VERIFICATION: VALID | {remote} {target_ref} "
        f"{str(expected_old)[:12]} -> {expected_new[:12]} | policy={expected_policy}"
    )
    return 0


# Fields a manifest carries that a fresh check does not reproduce.
UNCOMPARED_MANIFEST_FIELDS = frozenset({"created_at"})


def recheck_manifest(root: Path, judge: Judge, data: dict[str, Any], args: argparse.Namespace) -> list[str]:
    """Run the whole release check again for the manifest's candidate and compare every field.

    A manifest is only as good as the check that wrote it: one that was edited, or written by
    hand for a commit no check ever saw, does not match what the check says now. Options that
    widen a release (--allow-new-ref, --bootstrap-self-judge) are taken from this call, never
    from the manifest. Mismatches name the field, not its value."""
    try:
        result = prepare_release(
            root,
            judge,
            remote=data["remote"],
            ref=data["target_ref"],
            commit=data["candidate_sha"],
            allow_new_ref=bool(args.allow_new_ref),
            allowed_url=args.allowed_url,
            approvals=args.approve_exemption or [],
        )
    except CheckError as exc:
        return [f"the release check cannot run again for this manifest: {exc}"]
    if result.blocked or result.manifest is None:
        return ["the candidate does not pass the release check now:", *result.blocked]
    fresh = result.manifest
    problems: list[str] = []
    for key in sorted((fresh.keys() | data.keys()) - UNCOMPARED_MANIFEST_FIELDS):
        if key not in data:
            problems.append(f"manifest field {key!r} is missing (a fresh release check writes it)")
        elif key not in fresh:
            problems.append(f"manifest field {key!r} is not one a release check writes")
        elif fresh[key] != data[key]:
            problems.append(f"manifest field {key!r} does not match a fresh release check")
    return problems


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


def forwarded_release_args(args: argparse.Namespace) -> list[str]:
    """The caller's release options, passed on unchanged to the exported checker."""
    out = ["--to", args.to]
    for flag, value in (
        ("--ref", args.ref),
        ("--commit", args.commit),
        ("--allowed-url", args.allowed_url),
        ("--manifest-dir", args.manifest_dir),
        ("--verify-manifest", args.verify_manifest),
    ):
        if value is not None:
            out += [flag, value]
    if args.allow_new_ref:
        out.append("--allow-new-ref")
    if args.json_output:
        out.append("--json")
    if args.bootstrap_self_judge:
        out.append(BOOTSTRAP_FLAG)
    for fingerprint in args.approve_exemption or []:
        out += ["--approve-exemption", fingerprint]
    return out


def launch_release(args: argparse.Namespace) -> int:
    """Run the release check with the checker exported from the trusted baseline.

    This launcher is the only part that runs from the working tree. It finds the trusted
    baseline (the remote's main), exports the checker and scanners of that commit (or, under
    --bootstrap-self-judge, of the candidate) and hands the whole check to that exported copy."""
    root = repo_root()
    if args.verify_manifest:
        data = read_manifest(Path(args.verify_manifest))
        remote, candidate = data["remote"], data["candidate_sha"]
    else:
        if not args.ref or not args.commit:
            raise CheckError("--ref <refs/heads/...> and --commit <40-hex-sha> are required")
        validate_target_ref(root, args.ref)
        remote, candidate = args.to, args.commit
    if not FULL_SHA_RE.fullmatch(candidate):
        raise CheckError(f"--commit must be a full 40-char commit SHA, got: {candidate!r}")
    if git_optional(["rev-parse", "--verify", "--quiet", "--end-of-options", f"{candidate}^{{commit}}"], root) != candidate:
        raise CheckError(f"candidate commit not found locally: {candidate}")

    # The remote is checked before it is asked anything; the exported checker checks it again.
    check_remote_policy(root, remote, args.allowed_url)
    _old, remote_refs = query_remote_ref_sha(root, remote, BASELINE_BRANCH)
    _label, trusted_sha = resolve_trusted_baseline(root, remote, remote_refs)
    if args.bootstrap_self_judge:
        refuse_needless_bootstrap(root, trusted_sha, candidate)
    else:
        gap = trusted_baseline_gap(root, trusted_sha, candidate)
        if gap:
            raise CheckError(bootstrap_hint(trusted_sha, gap))
    checker_sha = candidate if args.bootstrap_self_judge else trusted_sha
    with tempfile.TemporaryDirectory(prefix="genops-checker-") as td:
        tools = export_checker(root, checker_sha, Path(td))
        script = tools / "release_check.py"
        if not checker_speaks_protocol(script, root):
            if args.bootstrap_self_judge:
                raise CheckError(
                    f"the candidate's own checker ({candidate[:12]}) does not speak release protocol {RELEASE_PROTOCOL}"
                )
            raise CheckError(
                bootstrap_hint(trusted_sha, f"has no release checker that speaks protocol {RELEASE_PROTOCOL}")
            )
        cmd = [
            sys.executable,
            "-I",
            "-B",
            str(script),
            "release",
            *forwarded_release_args(args),
            "--as-trusted-checker",
            "--trusted-sha",
            trusted_sha,
            "--checker-sha",
            checker_sha,
        ]
        sys.stdout.flush()
        sys.stderr.flush()
        return subprocess.run(cmd, cwd=root, check=False).returncode


def judge_for_this_process(root: Path, args: argparse.Namespace) -> Judge:
    """The exported checker checks what the launcher told it before it judges anything."""
    for name in ("trusted_sha", "checker_sha"):
        if not FULL_SHA_RE.fullmatch(getattr(args, name) or ""):
            raise CheckError("--as-trusted-checker is internal to ./check release")
    candidate = args.commit
    if args.verify_manifest:
        candidate = read_manifest(Path(args.verify_manifest))["candidate_sha"]
    if args.bootstrap_self_judge:
        if args.checker_sha != candidate:
            raise CheckError("bootstrap: the checker must come from the candidate")
        refuse_needless_bootstrap(root, args.trusted_sha, candidate)
    elif args.checker_sha != args.trusted_sha:
        raise CheckError("the checker must come from the trusted baseline")
    me = Path(__file__).resolve()
    tools = me.parent
    mismatched = [
        rel
        for rel in EXPORTED_CHECKER_FILES
        if not file_is_blob_of(root, tools.parent / rel, args.checker_sha, rel, required=rel in CHECKER_FILES)
    ]
    if mismatched:
        raise CheckError(
            f"the files beside this checker ({tools}) are not those of {args.checker_sha[:12]}: "
            f"{', '.join(mismatched)}; run ./check release"
        )
    return Judge(tools, args.trusted_sha, args.checker_sha, bool(args.bootstrap_self_judge))


def file_is_blob_of(root: Path, path: Path, sha: str, rel: str, *, required: bool) -> bool:
    """Whether ``path`` holds exactly ``sha``'s ``rel``; a file ``sha`` lacks must be absent too."""
    shipped = run_git(["cat-file", "blob", f"{sha}:{rel}"], root, check=False)
    if shipped.returncode != 0:
        return not required and not path.exists() and not path.is_symlink()
    try:
        return not path.is_symlink() and path.is_file() and path.read_bytes() == shipped.stdout
    except OSError:
        return False


def run_as_trusted_checker(args: argparse.Namespace) -> int:
    root = repo_root()
    judge = judge_for_this_process(root, args)
    if args.verify_manifest:
        return verify_manifest_file(root, judge, Path(args.verify_manifest), args)

    manifest_dir = ensure_outside_repo(
        root, Path(args.manifest_dir) if args.manifest_dir else default_manifest_dir()
    )
    result = prepare_release(
        root,
        judge,
        remote=args.to,
        ref=args.ref,
        commit=args.commit,
        allow_new_ref=args.allow_new_ref,
        allowed_url=args.allowed_url,
        approvals=args.approve_exemption or [],
    )
    if result.blocked or result.manifest is None:
        if judge.self_judged:
            print("Note: the candidate judged itself (bootstrap mode); the result needs an independent review.")
        for line in result.blocked:
            print(line)
        return 1
    manifest = {"created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **result.manifest}
    print_and_store_manifest(manifest, manifest_dir, args.json_output)
    return 0


def print_and_store_manifest(manifest: dict[str, Any], manifest_dir: Path, json_output: bool) -> None:
    commit = manifest["candidate_sha"]
    manifest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest_file = manifest_dir / f"release-{commit[:12]}-{stamp}.json"
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if json_output:
        print(json.dumps({"manifest_path": str(manifest_file), "manifest": manifest}, ensure_ascii=False, indent=2))
        return

    remote_old_sha = manifest["remote_old_sha"]
    changed_files = manifest["changed_files"]
    control_changes = manifest["control_plane_changes"]
    inline_allows = manifest["inline_allow_additions"]
    other_warnings = manifest["non_candidate_ref_warnings"]
    unverified_notes = manifest["unverified_items"]
    old_label = "NEW (000000000000)" if remote_old_sha == ZERO_OID else remote_old_sha
    file_preview = ", ".join(f"{f['status']} {f['path']}" for f in changed_files[:20])
    if len(changed_files) > 20:
        file_preview += f", ... (+{len(changed_files) - 20} more)"
    if manifest["rehearsal_remote"]:
        print(
            f"Note: REHEARSAL. The remote {manifest['push_url']} is not the repository's own; its main is the trusted baseline "
            "(set with --allowed-url or genops.allowedPushUrl). This manifest does not clear a release to the repository."
        )
    if manifest["self_judged"]:
        print(
            f"Note: the candidate judged itself. The trusted baseline {manifest['trusted_sha'][:12]} could not judge, "
            f"so the checker and scanners are the candidate's own ({manifest['checker_sha'][:12]}); get an independent review."
        )
    print("Request: push one branch only; no visibility change, no tag, no release")
    print(f"Target: {manifest['push_url']} · {manifest['target_ref']} · {old_label} -> {commit}")
    print(f"Changes: {manifest['commit_count']} commit(s) / {len(changed_files)} file(s); {file_preview or '(no file differences)'}")
    print(
        f"Privacy: maintainer rules loaded ({manifest['privacy_scan']['private_rules_loaded']}); history, paths and ref passed; "
        f"Betterleaks passed; workflow policy {manifest['workflow_policy']}; policy version {manifest['policy_version']}"
        f"（trusted={manifest['trusted_sha'][:12]}，checker={manifest['checker_sha'][:12]}）"
    )
    print(
        f"For a person to decide: control-plane changes {len(control_changes)}; new inline exemptions {len(inline_allows)}; "
        f"warnings on other local refs {len(other_warnings)}; unverified items {len(unverified_notes)}"
    )
    if control_changes:
        print(f"  Control-plane changes (review independently): {', '.join(control_changes)}")
    if inline_allows:
        print(f"  New inline exemptions (review independently): {', '.join(inline_allows)}")
    if manifest["approved_exemptions"]:
        print(f"  Exemptions the user approved one by one: {len(manifest['approved_exemptions'])} (fingerprints are in the manifest file)")
    if other_warnings:
        print(f"  Warnings on other unpushed local refs (they do not affect this candidate): {len(other_warnings)} (see the local scan)")
    for note in unverified_notes:
        print(f"  Unverified item: {note}")
    print("Status: waiting for the user's approval; nothing has been pushed. This manifest is void if the target, the SHA or the policy version changes.")
    print(f"Record kept outside the repository: {manifest_file}")


def cmd_release(args: argparse.Namespace) -> int:
    if args.as_trusted_checker:
        return run_as_trusted_checker(args)
    return launch_release(args)


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
    p_changed.add_argument("--no-tests", action="store_true", help="skip the test suites (marked NOT RUN); the workflow policy check still runs")
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
    p_release.add_argument(
        BOOTSTRAP_FLAG,
        dest="bootstrap_self_judge",
        action="store_true",
        help=(
            "only when the trusted baseline cannot judge (no release checker that speaks the protocol, "
            "or no workflow policy checker): let the candidate's own checker and scanners judge it; "
            "the manifest says so and needs an independent review"
        ),
    )
    p_release.add_argument(
        "--approve-exemption",
        action="append",
        metavar="FINGERPRINT",
        help=(
            "a secret-scan finding the user approved, as its Betterleaks fingerprint "
            "<commit>:<path>:<rule>:<line>; one flag per finding, recorded in the manifest, "
            "and passed again to --verify-manifest"
        ),
    )
    # Internal: ./check release hands the check to the checker exported from the judging commit.
    p_release.add_argument("--as-trusted-checker", action="store_true", help=argparse.SUPPRESS)
    p_release.add_argument("--trusted-sha", help=argparse.SUPPRESS)
    p_release.add_argument("--checker-sha", help=argparse.SUPPRESS)

    sub.add_parser("protocol", help="print the release protocol this checker speaks (JSON)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "changed":
            return cmd_changed(args)
        if args.command == "release":
            return cmd_release(args)
        if args.command == "protocol":
            print(json.dumps({"release_protocol": RELEASE_PROTOCOL}))
            return 0
        parser.error(f"unknown command: {args.command}")
    except CheckError as exc:
        if getattr(args, "json_output", False):
            print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"check: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
