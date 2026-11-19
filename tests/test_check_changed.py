"""``./check changed`` against synthetic repositories, run through its command line.

Covers what the change lists see (staged and unstaged deletions, type changes), which paths
select the guard tests and how the selection is reported. Every repository is a temporary
clone with a local bare remote, synthetic private rules and a synthetic marker; nothing here
touches a real remote or the real private rules.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_release_check import SYNTH_MARKER, SyntheticRepo, combined  # noqa: E402

PASSING_TEST = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertTrue(True)\n"


def need_betterleaks(testcase: unittest.TestCase) -> None:
    if shutil.which("betterleaks") is None:
        testcase.fail("betterleaks is not installed: brew install betterleaks")


def repo_with_guard_tests(testcase: unittest.TestCase) -> SyntheticRepo:
    """A synthetic repository whose pushed baseline holds two small passing guard tests."""
    repo = SyntheticRepo(testcase, maintainer=True)
    repo.write("tests/test_guard_dummy.py", PASSING_TEST)
    repo.write("tests/test_other.py", PASSING_TEST)
    repo.git("add", "tests")
    repo.commit_unchecked("add guard tests")
    repo.git("push", "-q", "origin", "main")
    return repo


def changed_json(repo: SyntheticRepo, *flags: str) -> tuple[int, dict]:
    res = repo.check("changed", "--json", *flags)
    try:
        return res.returncode, json.loads(res.stdout)
    except ValueError:
        raise AssertionError(f"no JSON from ./check changed: {combined(res)}") from None


class RemovalsAndTypeChangesTests(unittest.TestCase):
    def test_staged_deletion_of_a_guard_test_selects_and_lists_the_guard_tests(self) -> None:
        need_betterleaks(self)
        repo = repo_with_guard_tests(self)
        repo.git("rm", "-q", "tests/test_guard_dummy.py")
        rc, data = changed_json(repo)
        self.assertEqual(rc, 0, json.dumps(data))
        statuses = {t["name"]: t["status"] for t in data["tests"]}
        self.assertEqual(statuses["guard-tests"], "PASS", json.dumps(data["tests"]))
        self.assertEqual(
            data["guard_changes"], [{"path": "tests/test_guard_dummy.py", "change": "removed"}]
        )
        self.assertEqual(data["states"]["removed_staged"], 1)

    def test_unstaged_deletion_of_a_guard_file_selects_and_lists_the_guard_tests(self) -> None:
        need_betterleaks(self)
        repo = repo_with_guard_tests(self)
        (repo.work / "tests" / "test_guard_dummy.py").rename(repo.base / "moved_aside.py")
        rc, data = changed_json(repo)
        self.assertEqual(rc, 0, json.dumps(data))
        statuses = {t["name"]: t["status"] for t in data["tests"]}
        self.assertEqual(statuses["guard-tests"], "PASS", json.dumps(data["tests"]))
        self.assertEqual(
            data["guard_changes"], [{"path": "tests/test_guard_dummy.py", "change": "removed"}]
        )
        self.assertEqual(data["states"]["removed_unstaged"], 1)

    def test_changed_guard_file_is_listed_as_changed_in_text_output(self) -> None:
        need_betterleaks(self)
        repo = repo_with_guard_tests(self)
        repo.write("tests/test_other.py", PASSING_TEST + "\n# touched\n")
        repo.git("rm", "-q", "tests/test_guard_dummy.py")
        res = repo.check("changed")
        self.assertEqual(res.returncode, 0, combined(res))
        self.assertIn("GUARD CHANGES (these select the guard tests):", res.stdout)
        self.assertIn("tests/test_guard_dummy.py (removed)", res.stdout)
        self.assertIn("tests/test_other.py (changed)", res.stdout)

    def test_staged_type_change_to_a_symlink_is_scanned(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        repo.write("docs/link", "plain\n")
        repo.git("add", "docs/link")
        repo.commit_unchecked("plain file")
        repo.git("push", "-q", "origin", "main")
        (repo.work / "docs" / "link").rename(repo.base / "moved_aside.txt")
        os.symlink(f"/{SYNTH_MARKER}/x", repo.work / "docs" / "link")
        repo.git("add", "docs/link")
        self.assertIn("T\tdocs/link", repo.git("diff", "--cached", "--name-status").stdout)
        res = repo.check("changed", "--no-tests")
        self.assertEqual(res.returncode, 1, combined(res))
        self.assertIn("synthetic_private_marker", combined(res))
        self.assertNotIn(SYNTH_MARKER, combined(res))
        self.assertIn("staged=1", res.stdout)


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_README = "workflows/sdxl-txt2img/README.md"


def repo_with_workflows(testcase: unittest.TestCase) -> SyntheticRepo:
    """A synthetic repository holding the real standard workflows, their registry and the
    policy tool, plus a passing stand-in for tests/test_workflow_policy.py."""
    repo = SyntheticRepo(testcase, maintainer=True)
    for name in ("workflow_policy.py", "workflow_policy.json"):
        shutil.copy2(ROOT / "tools" / name, repo.work / "tools" / name)
    shutil.copytree(ROOT / "workflows", repo.work / "workflows")
    repo.write("tests/test_workflow_policy.py", PASSING_TEST)
    repo.git("add", "tools", "workflows", "tests")
    repo.commit_unchecked("add workflows and the policy tool")
    repo.git("push", "-q", "origin", "main")
    return repo


def step(data: dict, name: str) -> dict:
    return next(t for t in data["tests"] if t["name"] == name)


class WorkflowPolicyStepTests(unittest.TestCase):
    def test_a_policy_violation_in_workflows_fails_check_changed(self) -> None:
        need_betterleaks(self)
        repo = repo_with_workflows(self)
        repo.write("workflows/sdxl-txt2img/stray.json", "{}\n")
        repo.git("add", "workflows")
        rc, data = changed_json(repo, "--no-tests")
        self.assertEqual(rc, 1, json.dumps(data))
        self.assertEqual(data["status"], "fail")
        self.assertEqual(step(data, "workflow-policy")["status"], "FAIL", json.dumps(data["tests"]))
        self.assertIn("finding(s)", step(data, "workflow-policy")["detail"])

    def test_a_clean_change_to_workflows_runs_the_policy_and_the_guard_tests(self) -> None:
        need_betterleaks(self)
        repo = repo_with_workflows(self)
        readme = repo.work / WORKFLOW_README
        readme.write_text(readme.read_text(encoding="utf-8") + "\nOne more sentence.\n", encoding="utf-8")
        rc, data = changed_json(repo)
        self.assertEqual(rc, 0, json.dumps(data))
        self.assertEqual(step(data, "workflow-policy")["status"], "PASS", json.dumps(data["tests"]))
        self.assertEqual(step(data, "guard-tests")["status"], "PASS", json.dumps(data["tests"]))
        self.assertIn(WORKFLOW_README, [c["path"] for c in data["guard_changes"]])

    def test_an_unreadable_registry_fails_check_changed(self) -> None:
        need_betterleaks(self)
        repo = repo_with_workflows(self)
        repo.write("tools/workflow_policy.json", "{not json")
        rc, data = changed_json(repo, "--no-tests")
        self.assertEqual(rc, 1, json.dumps(data))
        self.assertEqual(step(data, "workflow-policy")["status"], "ERROR", json.dumps(data["tests"]))

    def test_the_policy_is_not_run_for_unrelated_changes(self) -> None:
        need_betterleaks(self)
        repo = repo_with_workflows(self)
        repo.write("docs/guide.md", "# Guide\n\nA clean edit.\n")
        rc, data = changed_json(repo)
        self.assertEqual(rc, 0, json.dumps(data))
        self.assertEqual(step(data, "workflow-policy")["status"], "NOT RUN")



def stub_scanner(repo: SyntheticRepo, body: str) -> None:
    """Replace the repository's scanner by a committed, pushed stub so the tree stays clean."""
    repo.write("tools/privacy_scan.py", body)
    repo.git("add", "tools/privacy_scan.py")
    repo.commit_unchecked("stub scanner")
    # The stub would answer the pre-push hook too: record the commit as already published.
    repo.git("update-ref", "refs/remotes/origin/main", "HEAD")


def clone_mode_stub(answer: str, status: int = 0) -> str:
    return (
        "import sys\n"
        "if sys.argv[1:] == ['--clone-mode']:\n"
        f"    print({answer!r})\n"
        f"    sys.exit({status})\n"
        "sys.exit(2)\n"
    )


class CloneModeSourceTests(unittest.TestCase):
    """./check reads the clone mode from the scanner's --clone-mode, the one implementation."""

    def test_the_scanner_answer_decides_the_mode_not_a_second_reading_of_the_config(self) -> None:
        need_betterleaks(self)
        # The scanner says maintainer; the clone config is unset and no private rules exist.
        repo = SyntheticRepo(self, maintainer=False)
        stub_scanner(repo, clone_mode_stub("maintainer"))
        os.unlink(repo.private_rules_file)
        res = repo.check("changed", "--no-tests")
        self.assertEqual(res.returncode, 2, combined(res))
        self.assertIn("private rules", combined(res))

        # The scanner says contributor; the clone config says maintainer.
        repo = SyntheticRepo(self, maintainer=True)
        stub_scanner(repo, clone_mode_stub("contributor"))
        res = repo.check("changed", "--no-tests")
        self.assertEqual(res.returncode, 0, combined(res))
        self.assertIn("NOT a release check", res.stdout)

    def test_a_scanner_that_cannot_answer_stops_the_check(self) -> None:
        need_betterleaks(self)
        for name, body in (
            ("garbage", clone_mode_stub("banana")),
            ("failure", clone_mode_stub("maintainer", status=2)),
        ):
            with self.subTest(stub=name):
                repo = SyntheticRepo(self, maintainer=True)
                stub_scanner(repo, body)
                res = repo.check("changed", "--no-tests")
                self.assertEqual(res.returncode, 2, combined(res))
                self.assertIn("clone mode", combined(res))


class CloneModeReadErrorTests(unittest.TestCase):
    """An unset genops.mode is the contributor mode; a failed read is not an answer."""

    GIT_SHIM = (
        "#!/bin/sh\n"
        'for a in "$@"; do\n'
        '  if [ "$a" = genops.mode ]; then\n'
        '    echo "fatal: simulated failure while reading the configuration" >&2\n'
        "    exit 128\n"
        "  fi\n"
        "done\n"
        'exec "$REAL_GIT" "$@"\n'
    )

    def failing_env(self, repo: SyntheticRepo) -> dict[str, str]:
        # A stand-in for a git that cannot read its configuration: only the read of
        # genops.mode fails (exit 128, what git prints for an unreadable config); every
        # other git call goes to the real git.
        shim = repo.base / "git_shim"
        shim.mkdir()
        (shim / "git").write_text(self.GIT_SHIM)
        (shim / "git").chmod(0o755)
        real = shutil.which("git")
        assert real is not None
        return dict(repo.env, PATH=f"{shim}{os.pathsep}{repo.env.get('PATH', '')}", REAL_GIT=real)

    def test_a_failed_read_is_refused_by_the_scanner_and_by_check(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        env = self.failing_env(repo)
        asked = repo.run(sys.executable, "-B", "tools/privacy_scan.py", "--clone-mode", env=env)
        self.assertEqual(asked.returncode, 2, combined(asked))
        self.assertNotIn("contributor", asked.stdout)
        res = repo.check("changed", "--no-tests", env=env)
        self.assertEqual(res.returncode, 2, combined(res))
        self.assertNotIn("PASS", combined(res))

    def test_an_unset_mode_is_the_contributor_mode(self) -> None:
        repo = SyntheticRepo(self, maintainer=False)
        asked = repo.run(sys.executable, "-B", "tools/privacy_scan.py", "--clone-mode")
        self.assertEqual((asked.returncode, asked.stdout.strip()), (0, "contributor"), combined(asked))



GLPAT_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


class SecretScanRedactionTests(unittest.TestCase):
    """Findings are printed with sensitive paths redacted, or not at all."""

    def staged_secret_scan(self, repo: SyntheticRepo, scanner: str | None) -> "subprocess.CompletedProcess[str]":
        env = dict(repo.env)
        if scanner is not None:
            env["SECRET_SCAN_REDACT_SCANNER"] = scanner
        return repo.run("sh", "tools/secret_scan.sh", "staged", env=env)

    def repo_with_a_secret_in_a_sensitive_path(self) -> tuple[SyntheticRepo, str]:
        import secrets as secrets_module

        repo = SyntheticRepo(self, maintainer=True)
        # A GitLab-style token shape only Betterleaks knows, built at run time.
        token = "glpat-" + "".join(secrets_module.choice(GLPAT_ALPHABET) for _ in range(20))
        repo.write(f"docs/{SYNTH_MARKER}-notes.txt", f"token = {token}\n")
        repo.git("add", "docs")
        return repo, token

    def test_the_real_scanner_redacts_the_path_of_a_finding(self) -> None:
        need_betterleaks(self)
        repo, token = self.repo_with_a_secret_in_a_sensitive_path()
        res = self.staged_secret_scan(repo, None)
        self.assertEqual(res.returncode, 1, combined(res))
        self.assertNotIn(SYNTH_MARKER, combined(res))
        self.assertNotIn(token, combined(res))
        self.assertIn("<redacted-path#", combined(res))

    def test_a_scanner_that_cannot_redact_never_lets_the_path_through(self) -> None:
        need_betterleaks(self)
        repo, token = self.repo_with_a_secret_in_a_sensitive_path()
        # A scanner with no --redact-stream (an older checkout): its source has no such word.
        old = repo.base / "old_scanner.py"
        old.write_text("import sys\nsys.exit(2)\n")
        res = self.staged_secret_scan(repo, str(old))
        self.assertEqual(res.returncode, 1, combined(res))
        self.assertNotIn(SYNTH_MARKER, combined(res))
        self.assertNotIn(token, combined(res))
        self.assertIn("path redaction failed", combined(res))
        missing = self.staged_secret_scan(repo, str(repo.base / "no_such_scanner.py"))
        self.assertEqual(missing.returncode, 1, combined(missing))
        self.assertNotIn(SYNTH_MARKER, combined(missing))
        self.assertIn("path redaction failed", combined(missing))


if __name__ == "__main__":
    unittest.main()
