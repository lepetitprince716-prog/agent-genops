"""The internal ``--as-trusted-checker`` mode judges only with the files of the commit it names.

``./check release`` exports the checker, the scanners, the rules, the wrapper, the template and
the policy checker of the judging commit and runs the exported checker with the internal flag.
Run by hand from a working tree, that checker would use the working tree's files beside it, so
it compares each of them with the judging commit before it judges. Every repository here is a
temporary clone with a local bare remote and synthetic private rules.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_release_check import SYNTH_MARKER, SyntheticRepo, combined  # noqa: E402
from test_release_trusted import STUB_CLEAN_SCANNER, manifests, need_betterleaks, release  # noqa: E402

# The release checker lists these as the files it exports; they are named here again on purpose,
# so a file dropped from that list fails these tests.
JUDGE_FILES = (
    "tools/release_check.py",
    "tools/privacy_scan.py",
    "tools/privacy_rules.json",
    "tools/secret_scan.sh",
    "tools/secret_scan.tmpl",
    "tools/workflow_policy.py",
)


def internal(repo: SyntheticRepo, cand: str, trusted: str, *more: str):
    return release(repo, cand, "--json", "--as-trusted-checker", "--trusted-sha", trusted,
                   "--checker-sha", trusted, *more)


class InternalCheckerFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        need_betterleaks(self)
        self.repo = SyntheticRepo(self, maintainer=True)
        self.trusted = self.repo.head()
        self.repo.write("docs/notes.md", f"# Notes\n{SYNTH_MARKER}\n")
        self.repo.git("add", "docs/notes.md")
        self.cand = self.repo.commit_unchecked("a marker")

    def test_a_stub_scanner_in_the_working_tree_is_refused(self) -> None:
        """The case the checker review found: only the scanner beside the checker is a stub."""
        repo = self.repo
        repo.write("tools/privacy_scan.py", STUB_CLEAN_SCANNER)
        res = internal(repo, self.cand, self.trusted)
        self.assertEqual(res.returncode, 2, combined(res))
        self.assertIn("tools/privacy_scan.py", combined(res))
        self.assertNotIn(SYNTH_MARKER, combined(res))
        self.assertEqual(manifests(repo), [])

    def test_each_file_beside_the_checker_must_be_the_judging_commits(self) -> None:
        """Each file is edited in turn; one the judging commit lacks is added instead."""
        repo = self.repo
        for rel in JUDGE_FILES:
            with self.subTest(rel=rel):
                path = repo.work / rel
                original = path.read_bytes() if path.exists() else None
                edit = b"\n" if rel.endswith(".json") else b"\n# edited beside the checker\n"
                path.write_bytes((original or b"# not in the judging commit\n") + edit)
                try:
                    res = internal(repo, self.cand, self.trusted)
                    self.assertEqual(res.returncode, 2, combined(res))
                    self.assertIn(rel, combined(res))
                    self.assertEqual(manifests(repo), [])
                finally:
                    if original is None:
                        path.rename(repo.base / f"aside-{path.name}")
                    else:
                        path.write_bytes(original)

    def test_control_unchanged_files_beside_the_checker_judge_and_block_the_marker(self) -> None:
        res = internal(self.repo, self.cand, self.trusted)
        self.assertEqual(res.returncode, 1, combined(res))
        self.assertIn("privacy", combined(res))
        self.assertEqual(manifests(self.repo), [])


if __name__ == "__main__":
    unittest.main()
