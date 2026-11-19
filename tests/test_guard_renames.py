"""A guard file moved away by a rename is still a guard change.

git reports a rename as one entry under the new name, so a list built from new names alone loses
the guard test or control file that left its place. ``./check changed`` and ``./check release``
both read their change lists with rename detection off: a rename is a removal plus an addition.
Every repository here is a temporary clone with a local bare remote and synthetic private rules.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_release_check import SyntheticRepo, combined  # noqa: E402
from test_release_trusted import manifests, need_betterleaks, push_baseline, release  # noqa: E402

PASSING_TEST = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertTrue(True)\n"
GUARD_TEST = "tests/test_guard_dummy.py"
CONTROL_FILE = ".gitleaksignore"


def repo_with_guard_files(testcase: unittest.TestCase) -> SyntheticRepo:
    """The pushed baseline holds a guard test and a control file (an ignore list with no entries)."""
    need_betterleaks(testcase)
    repo = SyntheticRepo(testcase, maintainer=True)
    repo.write(GUARD_TEST, PASSING_TEST)
    repo.write("tests/test_other.py", PASSING_TEST)
    repo.write(CONTROL_FILE, "# no exemptions\n")
    push_baseline(repo, "a guard test and a control file", "tests", CONTROL_FILE)
    return repo


def changed_json(repo: SyntheticRepo) -> dict:
    res = repo.check("changed", "--json")
    try:
        data = json.loads(res.stdout)
    except ValueError:
        raise AssertionError(f"no JSON from ./check changed: {combined(res)}") from None
    data["_rc"] = res.returncode
    return data


class CheckChangedRenameTests(unittest.TestCase):
    def test_a_staged_rename_of_a_guard_test_is_a_guard_change(self) -> None:
        repo = repo_with_guard_files(self)
        repo.git("mv", GUARD_TEST, "docs/old-guard.md")
        data = changed_json(repo)
        self.assertEqual(data["_rc"], 0, json.dumps(data))
        self.assertIn({"path": GUARD_TEST, "change": "removed"}, data["guard_changes"])
        statuses = {t["name"]: t["status"] for t in data["tests"]}
        self.assertEqual(statuses["guard-tests"], "PASS", json.dumps(data["tests"]))

    def test_a_staged_rename_of_a_control_file_is_a_guard_change(self) -> None:
        repo = repo_with_guard_files(self)
        repo.git("mv", CONTROL_FILE, "docs/old-ignore.md")
        data = changed_json(repo)
        self.assertEqual(data["_rc"], 0, json.dumps(data))
        self.assertIn({"path": CONTROL_FILE, "change": "removed"}, data["guard_changes"])
        statuses = {t["name"]: t["status"] for t in data["tests"]}
        self.assertEqual(statuses["guard-tests"], "PASS", json.dumps(data["tests"]))

    def test_a_committed_rename_on_the_branch_lists_the_old_path(self) -> None:
        repo = repo_with_guard_files(self)
        repo.git("checkout", "-q", "-b", "topic")
        repo.git("mv", GUARD_TEST, "docs/old-guard.md")
        repo.commit_unchecked("move the guard test away")
        res = repo.check("changed", "--json", "--base", "origin/main", "--no-tests")
        data = json.loads(res.stdout)
        self.assertIn(GUARD_TEST, [g["path"] for g in data["guard_changes"]], combined(res))
        # The old path no longer exists on the branch: it is shown as removed, as a staged rename is.
        self.assertIn({"path": GUARD_TEST, "change": "removed"}, data["guard_changes"], combined(res))
        self.assertEqual(data["states"]["removed_branch"], 1, combined(res))
        text = repo.check("changed", "--base", "origin/main", "--no-tests")
        self.assertIn(f"{GUARD_TEST} (removed)", text.stdout, combined(text))


class ReleaseRenameTests(unittest.TestCase):
    def test_a_renamed_guard_test_is_in_the_control_plane_list(self) -> None:
        repo = repo_with_guard_files(self)
        repo.git("mv", GUARD_TEST, "docs/old-guard.md")
        cand = repo.commit_unchecked("move the guard test out of tests/")
        res = release(repo, cand, "--json")
        self.assertEqual(res.returncode, 0, combined(res))
        manifest = json.loads(res.stdout)["manifest"]
        self.assertIn(GUARD_TEST, manifest["control_plane_changes"])
        self.assertIn({"status": "D", "path": GUARD_TEST}, manifest["changed_files"])

    def test_a_renamed_control_file_is_in_the_control_plane_list(self) -> None:
        repo = repo_with_guard_files(self)
        repo.git("mv", CONTROL_FILE, "docs/old-ignore.md")
        cand = repo.commit_unchecked("move the ignore list away")
        res = release(repo, cand, "--json")
        self.assertEqual(res.returncode, 0, combined(res))
        manifest = json.loads(res.stdout)["manifest"]
        self.assertIn(CONTROL_FILE, manifest["control_plane_changes"])
        self.assertEqual(len(manifests(repo)), 1)


if __name__ == "__main__":
    unittest.main()
