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


if __name__ == "__main__":
    unittest.main()
