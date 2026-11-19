"""``./check release`` and ``--verify-manifest`` judge a candidate with the trusted baseline.

The trusted baseline is the commit the remote's ``refs/heads/main`` holds (``git ls-remote``);
the checker, the scanners and the trusted ignore file come from it, never from the working tree
or the candidate. Every "remote" here is a bare repository in a temporary directory.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import string
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_release_check import SYNTH_MARKER, SyntheticRepo, combined  # noqa: E402

# A privacy scanner that answers "clean" to everything (it names the flags the old checker
# looked for in a scanner's source, so that checker takes it for a current one).
STUB_CLEAN_SCANNER = (
    "# accepts --rev and --json\n"
    "import json, sys\n"
    'print(json.dumps({"status": "clean", "findings": [], "private_loaded": True, "private_rule_count": 1}))\n'
)


def random_text(length: int) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def need_betterleaks(testcase: unittest.TestCase) -> None:
    if shutil.which("betterleaks") is None:
        testcase.fail("betterleaks is not installed: brew install betterleaks")


def release(repo: SyntheticRepo, commit: str, *more: str, ref: str = "refs/heads/main") -> subprocess.CompletedProcess[str]:
    return repo.check(
        "release",
        "--to",
        "origin",
        "--ref",
        ref,
        "--commit",
        commit,
        "--allowed-url",
        str(repo.remote),
        "--manifest-dir",
        str(repo.manifest_dir),
        *more,
    )


def manifests(repo: SyntheticRepo) -> list[Path]:
    return sorted(repo.manifest_dir.iterdir())


def marker_candidate(repo: SyntheticRepo) -> str:
    repo.write("docs/notes.md", f"# Notes\n{SYNTH_MARKER}\n")
    repo.git("add", "docs/notes.md")
    return repo.commit_unchecked("slip a private marker")


def clean_candidate(repo: SyntheticRepo, text: str = "A clean change.") -> str:
    repo.write("docs/guide.md", f"# Guide\n\n{text}\n")
    repo.git("add", "docs/guide.md")
    return repo.commit_unchecked("clean change")


class TrustedBaselineSourceTests(unittest.TestCase):
    """R10: the baseline is what the remote's main holds, and the local copy must agree."""

    def weak_commit(self, repo: SyntheticRepo) -> str:
        """A never-pushed commit whose privacy scanner passes everything; main is left as it was."""
        repo.git("checkout", "-q", "-b", "weak")
        repo.write("tools/privacy_scan.py", STUB_CLEAN_SCANNER)
        repo.git("add", "tools/privacy_scan.py")
        weak = repo.commit_unchecked("weakened scanner, never pushed")
        repo.git("checkout", "-q", "main")
        return weak

    def test_a_tracking_ref_that_is_not_the_remote_main_is_refused(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        weak = self.weak_commit(repo)
        cand = marker_candidate(repo)
        repo.git("update-ref", "refs/remotes/origin/main", weak)
        res = release(repo, cand)
        self.assertEqual(res.returncode, 2, combined(res))
        self.assertIn("git fetch", combined(res))
        self.assertEqual(manifests(repo), [])

    def test_a_missing_tracking_ref_is_refused(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        cand = clean_candidate(repo)
        repo.git("update-ref", "-d", "refs/remotes/origin/main")
        res = release(repo, cand)
        self.assertEqual(res.returncode, 2, combined(res))
        self.assertIn("git fetch", combined(res))
        self.assertEqual(manifests(repo), [])

    def test_a_tracking_ref_behind_the_remote_is_refused(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        stale = repo.head()
        first = clean_candidate(repo, "Published by someone else.")
        repo.git("-c", f"core.hooksPath={os.devnull}", "push", "-q", "origin", f"{first}:refs/heads/main")
        repo.git("update-ref", "refs/remotes/origin/main", stale)
        cand = clean_candidate(repo, "The change under review.")
        res = release(repo, cand)
        self.assertEqual(res.returncode, 2, combined(res))
        self.assertIn("git fetch", combined(res))
        self.assertEqual(manifests(repo), [])

    def test_the_caller_cannot_name_another_trusted_commit(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        weak = self.weak_commit(repo)
        cand = marker_candidate(repo)
        for trusted in (weak, "refs/heads/weak"):
            with self.subTest(trusted=trusted):
                res = release(repo, cand, "--trusted-ref", trusted)
                self.assertEqual(res.returncode, 2, combined(res))
                self.assertEqual(manifests(repo), [])

    def test_control_the_remote_main_as_baseline_passes_a_clean_candidate(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        base = repo.head()
        cand = clean_candidate(repo)
        res = release(repo, cand, "--json")
        self.assertEqual(res.returncode, 0, combined(res))
        manifest = json.loads(res.stdout)["manifest"]
        self.assertEqual(manifest["trusted_sha"], base)
        self.assertEqual(len(manifests(repo)), 1)


if __name__ == "__main__":
    unittest.main()
