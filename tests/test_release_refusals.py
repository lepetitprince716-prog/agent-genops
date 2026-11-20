"""Refusals of ``./check release`` that no other test reaches by its command line.

Each case is one way a release check could wave a bad request through: a candidate the remote
already holds, a scanner that says "clean" without having loaded the private rules, a bootstrap
option aimed at the wrong commit. Every repository is a temporary clone with a local bare remote
and synthetic private rules.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_release_check import ROOT, SyntheticRepo, combined  # noqa: E402
from test_release_trusted import (  # noqa: E402
    clean_candidate, manifests, need_betterleaks, push_baseline, release, verify,
)

# Answers "clean" and never says it loaded the private rules (it names the flags a scanner is
# expected to accept, so the baseline counts as able to judge).
SILENT_CLEAN_SCANNER = (
    "# accepts --rev and --json\n"
    "import json\n"
    'print(json.dumps({"status": "clean", "findings": []}))\n'
)


class RefusedRequestTests(unittest.TestCase):
    def test_a_candidate_the_remote_already_holds_is_refused(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        cand = clean_candidate(repo)
        repo.git("-c", f"core.hooksPath={os.devnull}", "push", "-q", "origin", f"{cand}:refs/heads/main")
        res = release(repo, cand)
        self.assertEqual(res.returncode, 2, combined(res))
        self.assertIn("nothing to publish", combined(res))
        self.assertEqual(manifests(repo), [])

    def test_a_scanner_that_never_loaded_the_private_rules_cannot_say_clean(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        repo.write("tools/privacy_scan.py", SILENT_CLEAN_SCANNER)
        push_baseline(repo, "a scanner that does not report its rules on the remote", "tools/privacy_scan.py")
        shutil.copy2(ROOT / "tools" / "privacy_scan.py", repo.work / "tools" / "privacy_scan.py")
        repo.write("docs/guide.md", "# Guide\n\nA clean change.\n")
        repo.git("add", "tools/privacy_scan.py", "docs/guide.md")
        cand = repo.commit_unchecked("bring the current scanner")
        res = release(repo, cand)
        self.assertEqual(res.returncode, 2, combined(res))
        self.assertIn("did not confirm non-empty private rules", combined(res))
        self.assertEqual(manifests(repo), [])

    def test_the_internal_bootstrap_option_names_the_candidate_as_the_checker(self) -> None:
        """Run past the launcher with the baseline as the checker: refused for that reason, not
        only because the baseline could judge."""
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        trusted = repo.head()
        cand = clean_candidate(repo)
        res = release(
            repo, cand, "--as-trusted-checker", "--bootstrap-self-judge", "--trusted-sha", trusted, "--checker-sha", trusted
        )
        self.assertEqual(res.returncode, 2, combined(res))
        self.assertIn("must come from the candidate", combined(res))
        self.assertEqual(manifests(repo), [])


class RehearsalRemoteTests(unittest.TestCase):
    """--allowed-url (or genops.allowedPushUrl) points the check at any remote the caller names,
    so whatever that remote's main holds is the baseline. Such a manifest says so."""

    def test_a_manifest_for_a_named_remote_is_marked_a_rehearsal(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        cand = clean_candidate(repo)
        res = release(repo, cand, "--json")
        self.assertEqual(res.returncode, 0, combined(res))
        manifest = json.loads(res.stdout)["manifest"]
        self.assertIs(manifest["rehearsal_remote"], True)
        self.assertTrue(any("rehearsal" in note for note in manifest["unverified_items"]), manifest)

        text = release(repo, clean_candidate(repo, "Another clean change."))
        self.assertEqual(text.returncode, 0, combined(text))
        self.assertIn("REHEARSAL", text.stdout)
        self.assertIn("does not clear a release", text.stdout)

    def test_verifying_a_rehearsal_manifest_needs_the_remote_named_again(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        cand = clean_candidate(repo)
        res = release(repo, cand, "--json")
        self.assertEqual(res.returncode, 0, combined(res))
        path = Path(json.loads(res.stdout)["manifest_path"])
        repo.git("config", "--unset", "genops.allowedPushUrl")

        bare = repo.check("release", "--verify-manifest", str(path))
        self.assertEqual(bare.returncode, 2, combined(bare))
        self.assertIn("not approved", combined(bare))
        self.assertNotIn("VALID", combined(bare).replace("INVALID", ""))

        named = verify(repo, path)
        self.assertEqual(named.returncode, 0, combined(named))
        self.assertIn("VALID", named.stdout)

    def test_a_manifest_that_drops_the_mark_is_invalid(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        cand = clean_candidate(repo)
        res = release(repo, cand, "--json")
        manifest = json.loads(res.stdout)["manifest"]
        edited = repo.base / "edited.json"
        edited.write_text(json.dumps({**manifest, "rehearsal_remote": False}, indent=2) + "\n", encoding="utf-8")
        ver = verify(repo, edited)
        self.assertEqual(ver.returncode, 1, combined(ver))
        self.assertIn("rehearsal_remote", combined(ver))


if __name__ == "__main__":
    unittest.main()
