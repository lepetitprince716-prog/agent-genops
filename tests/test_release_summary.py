"""What ``./check release`` prints and lists for a person to read.

Every repository is a temporary clone with a local bare remote and synthetic private rules.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_release_check import SyntheticRepo, combined  # noqa: E402
from test_release_trusted import clean_candidate, need_betterleaks, push_baseline, release, verify  # noqa: E402

# CJK symbols and punctuation, and the full-width forms block.
FULL_WIDTH = re.compile(r"[\u3000-\u303f\uff00-\uffef]")


class TerminalSummaryTests(unittest.TestCase):
    def test_the_summary_names_the_judges_in_ascii_punctuation(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        trusted = repo.head()
        cand = clean_candidate(repo)
        res = release(repo, cand)
        self.assertEqual(res.returncode, 0, combined(res))
        self.assertIn(f" (trusted={trusted[:12]}, checker={trusted[:12]})", res.stdout)
        self.assertEqual(FULL_WIDTH.findall(res.stdout), [], res.stdout)
        self.assertIn(f"Changes since {trusted[:12]} (the remote's refs/heads/main): 1 commit(s) / 1 file(s)", res.stdout)


class NewRefChangeListTests(unittest.TestCase):
    """For a new branch the listed commits and files are counted from where the candidate meets
    the trusted baseline, not from the start of history. The scans themselves are unchanged."""

    REF = "refs/heads/topic"

    def release_new_ref(self, repo: SyntheticRepo, cand: str) -> tuple[Path, dict]:
        res = release(repo, cand, "--json", "--allow-new-ref", ref=self.REF)
        self.assertEqual(res.returncode, 0, combined(res))
        payload = json.loads(res.stdout)
        return Path(payload["manifest_path"]), payload["manifest"]

    def assert_verifies(self, repo: SyntheticRepo, path: Path) -> None:
        ver = verify(repo, path, "--allow-new-ref")
        self.assertEqual(ver.returncode, 0, combined(ver))
        self.assertIn("VALID", ver.stdout)

    def test_a_branch_on_top_of_the_baseline_lists_only_its_own_commits(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        trusted = repo.head()
        clean_candidate(repo)
        repo.write("docs/extra.md", "# Extra\n")
        repo.git("add", "docs/extra.md")
        cand = repo.commit_unchecked("add a page")
        path, manifest = self.release_new_ref(repo, cand)
        self.assertEqual(manifest["commit_count"], 2)
        self.assertEqual(
            manifest["changed_files"],
            [{"status": "A", "path": "docs/extra.md"}, {"status": "M", "path": "docs/guide.md"}],
        )
        self.assertEqual(manifest["change_base"], trusted)
        self.assert_verifies(repo, path)

        text = release(repo, cand, "--allow-new-ref", ref=self.REF)
        self.assertEqual(text.returncode, 0, combined(text))
        self.assertIn(f"Changes since {trusted[:12]} (the trusted baseline): 2 commit(s) / 2 file(s)", text.stdout)

    def test_a_branch_the_baseline_moved_past_lists_from_where_they_meet(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        fork = repo.head()
        repo.git("checkout", "-q", "-b", "topic")
        cand = clean_candidate(repo)
        repo.git("checkout", "-q", "main")
        repo.write("docs/later.md", "# Later\n")
        moved = push_baseline(repo, "main moves on", "docs/later.md")
        path, manifest = self.release_new_ref(repo, cand)
        self.assertEqual(manifest["trusted_sha"], moved)
        self.assertEqual(manifest["commit_count"], 1)
        self.assertEqual(manifest["changed_files"], [{"status": "M", "path": "docs/guide.md"}])
        self.assertEqual(manifest["change_base"], fork)
        self.assert_verifies(repo, path)

    def test_an_orphan_branch_lists_its_whole_tree(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        repo.git("checkout", "-q", "--orphan", "lonely")
        orphan = repo.commit_unchecked("orphan root")
        tree = sorted(repo.git("ls-tree", "-r", "--name-only", orphan).stdout.split())
        path, manifest = self.release_new_ref(repo, orphan)
        self.assertEqual(manifest["commit_count"], 1)
        self.assertEqual(manifest["changed_files"], [{"status": "A", "path": name} for name in tree])
        self.assertEqual(manifest["change_base"], "")
        self.assert_verifies(repo, path)

        text = release(repo, orphan, "--allow-new-ref", ref=self.REF)
        self.assertEqual(text.returncode, 0, combined(text))
        self.assertIn("Changes in the whole tree (no commit in common with the trusted baseline): 1 commit(s)", text.stdout)


if __name__ == "__main__":
    unittest.main()
