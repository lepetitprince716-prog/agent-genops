"""``--bootstrap-self-judge`` is refused while the trusted baseline can judge the candidate.

The flag lets a candidate's own checker and scanners judge it. That is only for the release that
brings the checker to a baseline without one; when the baseline can judge, the flag would let any
candidate (one with a scanner that passes everything, say) write itself a manifest. Every
repository here is a temporary clone with a local bare remote and synthetic private rules.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_release_check import SYNTH_MARKER, SyntheticRepo, combined  # noqa: E402
from test_release_trusted import (  # noqa: E402
    STUB_CLEAN_SCANNER, clean_candidate, manifests, need_betterleaks, release, verify,
)

REFUSAL = "can judge this release"


def stub_scanner_candidate(repo: SyntheticRepo) -> str:
    repo.write("tools/privacy_scan.py", STUB_CLEAN_SCANNER)
    repo.write("docs/notes.md", f"# Notes\n{SYNTH_MARKER}\n")
    repo.git("add", "tools/privacy_scan.py", "docs/notes.md")
    return repo.commit_unchecked("a scanner that passes everything, and a marker")


class BootstrapRefusedTests(unittest.TestCase):
    def test_bootstrap_is_refused_when_the_baseline_can_judge(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        cand = stub_scanner_candidate(repo)
        res = release(repo, cand, "--bootstrap-self-judge", "--json")
        self.assertEqual(res.returncode, 2, combined(res))
        self.assertIn(REFUSAL, combined(res))
        self.assertNotIn(SYNTH_MARKER, combined(res))
        self.assertEqual(manifests(repo), [])

    def test_bootstrap_verify_is_refused_when_the_baseline_can_judge(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        cand = clean_candidate(repo)
        res = release(repo, cand, "--json")
        self.assertEqual(res.returncode, 0, combined(res))
        path = Path(json.loads(res.stdout)["manifest_path"])
        ver = verify(repo, path, "--bootstrap-self-judge")
        self.assertEqual(ver.returncode, 2, combined(ver))
        self.assertIn(REFUSAL, combined(ver))
        self.assertNotIn("VALID", ver.stdout.replace("INVALID", ""))

    def test_the_internal_checker_also_refuses_bootstrap_when_the_baseline_can_judge(self) -> None:
        """Run straight from a working tree whose checker is unchanged, past the launcher."""
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        trusted = repo.head()
        repo.write("docs/notes.md", f"# Notes\n{SYNTH_MARKER}\n")
        repo.git("add", "docs/notes.md")
        cand = repo.commit_unchecked("a marker")
        res = release(repo, cand, "--json", "--bootstrap-self-judge", "--as-trusted-checker",
                      "--trusted-sha", trusted, "--checker-sha", cand)
        self.assertEqual(res.returncode, 2, combined(res))
        self.assertIn(REFUSAL, combined(res))
        self.assertEqual(manifests(repo), [])

    def test_a_launcher_from_the_baseline_refuses_bootstrap_for_a_candidate_whose_checker_would_allow_it(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        trusted = repo.head()
        other = repo.base / "trusted-checkout"
        repo.git("worktree", "add", "-q", "--detach", str(other), trusted)
        checker = repo.work / "tools" / "release_check.py"
        source = checker.read_text(encoding="utf-8")
        main_guard = '\nif __name__ == "__main__":'
        self.assertEqual(source.count(main_guard), 1)
        checker.write_text(source.replace(main_guard, ALLOW_ANY_BOOTSTRAP + main_guard), encoding="utf-8")
        repo.git("add", "tools/release_check.py")
        cand = stub_scanner_candidate(repo)
        res = repo.run(
            sys.executable, "-B", str(other / "check"), "release", "--to", "origin", "--ref", "refs/heads/main",
            "--commit", cand, "--allowed-url", str(repo.remote), "--manifest-dir", str(repo.manifest_dir),
            "--bootstrap-self-judge", cwd=other,
        )
        self.assertEqual(res.returncode, 2, combined(res))
        self.assertIn(REFUSAL, combined(res))
        self.assertEqual(manifests(repo), [])


# Put into a candidate's checker before its entry point: its own refusal of a needless bootstrap is gone.
ALLOW_ANY_BOOTSTRAP = "\n\ndef refuse_needless_bootstrap(root, trusted_sha, candidate):\n    return None\n\n"


if __name__ == "__main__":
    unittest.main()
