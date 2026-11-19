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



ROOT = Path(__file__).resolve().parent.parent

# Synthetic stand-in for a release checker written before the trusted-checker protocol: it knows
# only "changed" and "release", and would wave any release through.
OLD_CHECKER = (
    '"""Synthetic stand-in for a release checker that predates the trusted-checker protocol."""\n'
    "import argparse, sys\n"
    'parser = argparse.ArgumentParser(prog="./check")\n'
    'sub = parser.add_subparsers(dest="command", required=True)\n'
    'sub.add_parser("changed")\n'
    'sub.add_parser("release")\n'
    "parser.parse_known_args()\n"
    'print("old checker: release OK")\n'
    "sys.exit(0)\n"
)

# Appended to a candidate's tools/release_check.py: every privacy scan answers "clean", and the
# control-plane list is emptied. Both only matter if the candidate's checker is what judges.
CHECKER_OVERRIDE_SCAN = (
    "\n\ndef run_privacy_subprocess(*_args, **_kwargs):\n"
    '    return 0, {"status": "clean", "findings": [], "private_loaded": True, "private_rule_count": 1}, ""\n'
)
CHECKER_OVERRIDE_CONTROL = '\n\nCONTROL_PLANE_EXACT = frozenset()\nCONTROL_PLANE_PREFIXES = ("\\0",)\n'


def push_baseline(repo: SyntheticRepo, message: str, *paths: str) -> str:
    """Commit ``paths`` on main and publish them as the remote's main (hooks off: synthetic setup)."""
    repo.git("add", *paths)
    sha = repo.commit_unchecked(message)
    repo.git("-c", f"core.hooksPath={os.devnull}", "push", "-q", "origin", "main")
    return sha


def add_workflows(repo: SyntheticRepo, *, checker: bool = True) -> list[str]:
    paths = ["tools/workflow_policy.json", "workflows"]
    shutil.copy2(ROOT / "tools" / "workflow_policy.json", repo.work / "tools" / "workflow_policy.json")
    shutil.copytree(ROOT / "workflows", repo.work / "workflows")
    if checker:
        shutil.copy2(ROOT / "tools" / "workflow_policy.py", repo.work / "tools" / "workflow_policy.py")
        paths.append("tools/workflow_policy.py")
    return paths


class TrustedCheckerTests(unittest.TestCase):
    """R9: the checker and the scanners that judge come from the trusted baseline."""

    def test_a_candidate_that_rewrites_the_checker_is_still_judged_by_the_baseline(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        checker = repo.work / "tools" / "release_check.py"
        checker.write_text(checker.read_text(encoding="utf-8") + CHECKER_OVERRIDE_SCAN, encoding="utf-8")
        repo.write("docs/notes.md", f"# Notes\n{SYNTH_MARKER}\n")
        repo.git("add", "tools/release_check.py", "docs/notes.md")
        cand = repo.commit_unchecked("weaken the checker and slip a marker")
        res = release(repo, cand)
        self.assertEqual(res.returncode, 1, combined(res))
        self.assertIn("privacy", combined(res))
        self.assertNotIn(SYNTH_MARKER, combined(res))
        self.assertEqual(manifests(repo), [])

    def test_the_control_plane_list_is_computed_by_the_baseline(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        checker = repo.work / "tools" / "release_check.py"
        checker.write_text(checker.read_text(encoding="utf-8") + CHECKER_OVERRIDE_CONTROL, encoding="utf-8")
        repo.write("tests/test_guard_extra.py", "import unittest\n")
        repo.git("add", "tools/release_check.py", "tests/test_guard_extra.py")
        cand = repo.commit_unchecked("empty the control-plane list")
        res = release(repo, cand, "--json")
        self.assertEqual(res.returncode, 0, combined(res))
        manifest = json.loads(res.stdout)["manifest"]
        self.assertEqual(manifest["control_plane_changes"], ["tests/test_guard_extra.py", "tools/release_check.py"])

    def test_a_baseline_without_the_trusted_checker_is_refused_unless_bootstrapped(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        repo.write("tools/release_check.py", OLD_CHECKER)
        push_baseline(repo, "an old checker on the remote", "tools/release_check.py")
        shutil.copy2(ROOT / "tools" / "release_check.py", repo.work / "tools" / "release_check.py")
        repo.write("docs/guide.md", "# Guide\n\nA clean change.\n")
        repo.git("add", "tools/release_check.py", "docs/guide.md")
        cand = repo.commit_unchecked("bring the current checker")

        refused = release(repo, cand)
        self.assertEqual(refused.returncode, 2, combined(refused))
        self.assertIn("--bootstrap-self-judge", combined(refused))
        self.assertNotIn("old checker: release OK", combined(refused))
        self.assertEqual(manifests(repo), [])

        boot = release(repo, cand, "--bootstrap-self-judge", "--json")
        self.assertEqual(boot.returncode, 0, combined(boot))
        manifest = json.loads(boot.stdout)["manifest"]
        self.assertIs(manifest["self_judged"], True)
        self.assertEqual(manifest["checker_sha"], cand)
        self.assertIn("tools/release_check.py", manifest["control_plane_changes"])
        self.assertTrue(any("independent" in note for note in manifest["unverified_items"]), manifest)

        text = release(repo, cand, "--bootstrap-self-judge")
        self.assertEqual(text.returncode, 0, combined(text))
        self.assertIn("候选自己判自己", text.stdout)

    def test_a_bootstrapped_candidate_is_still_scanned_by_its_own_scanners(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        repo.write("tools/release_check.py", OLD_CHECKER)
        push_baseline(repo, "an old checker on the remote", "tools/release_check.py")
        shutil.copy2(ROOT / "tools" / "release_check.py", repo.work / "tools" / "release_check.py")
        repo.write("docs/notes.md", f"# Notes\n{SYNTH_MARKER}\n")
        repo.git("add", "tools/release_check.py", "docs/notes.md")
        cand = repo.commit_unchecked("current checker and a marker")
        res = release(repo, cand, "--bootstrap-self-judge")
        self.assertEqual(res.returncode, 1, combined(res))
        self.assertEqual(manifests(repo), [])

    def test_a_baseline_scanner_without_rev_is_refused_not_replaced(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        repo.write("tools/privacy_scan.py", "import sys\nsys.exit(0)\n")
        push_baseline(repo, "an old privacy scanner on the remote", "tools/privacy_scan.py")
        shutil.copy2(ROOT / "tools" / "privacy_scan.py", repo.work / "tools" / "privacy_scan.py")
        repo.write("docs/guide.md", "# Guide\n\nA clean change.\n")
        repo.git("add", "tools/privacy_scan.py", "docs/guide.md")
        cand = repo.commit_unchecked("bring the current scanner")
        res = release(repo, cand)
        self.assertEqual(res.returncode, 2, combined(res))
        self.assertEqual(manifests(repo), [])

    def test_a_check_run_from_a_checkout_of_the_baseline_judges_a_candidate_that_replaced_the_launcher(self) -> None:
        """The way to rule out a candidate that swaps the launcher itself: run ./check from a
        checkout of the trusted baseline and name the candidate by its commit."""
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        trusted = repo.head()
        other = repo.base / "trusted-checkout"
        repo.git("worktree", "add", "-q", "--detach", str(other), trusted)

        def from_other(commit: str, *more: str) -> subprocess.CompletedProcess[str]:
            return repo.run(
                sys.executable, "-B", str(other / "check"), "release", "--to", "origin",
                "--ref", "refs/heads/main", "--commit", commit, "--allowed-url", str(repo.remote),
                "--manifest-dir", str(repo.manifest_dir), *more, cwd=other,
            )

        repo.write("tools/release_check.py", OLD_CHECKER)
        repo.write("docs/notes.md", f"# Notes\n{SYNTH_MARKER}\n")
        repo.git("add", "tools/release_check.py", "docs/notes.md")
        dirty = repo.commit_unchecked("replace the launcher and slip a marker")
        res = from_other(dirty)
        self.assertEqual(res.returncode, 1, combined(res))
        self.assertIn("privacy", combined(res))
        self.assertNotIn("old checker: release OK", combined(res))
        self.assertEqual(manifests(repo), [])

        repo.git("reset", "-q", "--hard", trusted)
        repo.write("tools/release_check.py", OLD_CHECKER)
        repo.git("add", "tools/release_check.py")
        clean = repo.commit_unchecked("replace the launcher only")
        ok = from_other(clean, "--json")
        self.assertEqual(ok.returncode, 0, combined(ok))
        manifest = json.loads(ok.stdout)["manifest"]
        self.assertEqual((manifest["candidate_sha"], manifest["checker_sha"]), (clean, trusted))
        self.assertIn("tools/release_check.py", manifest["control_plane_changes"])


class ReleaseWorkflowPolicyTests(unittest.TestCase):
    """The baseline's policy checker, the candidate's registry and workflows/."""

    def repo(self, *, checker: bool = True) -> SyntheticRepo:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        push_baseline(repo, "standard workflows", *add_workflows(repo, checker=checker))
        return repo

    def test_an_unregistered_workflow_file_blocks_the_release(self) -> None:
        repo = self.repo()
        repo.write("workflows/sdxl-lora/NOTES.md", "# Notes\n\nPlain text.\n")
        repo.git("add", "workflows/sdxl-lora/NOTES.md")
        cand = repo.commit_unchecked("an unregistered file")
        res = release(repo, cand)
        self.assertEqual(res.returncode, 1, combined(res))
        self.assertIn("workflow", combined(res))
        self.assertEqual(manifests(repo), [])

    def test_a_file_the_candidate_registers_passes_and_the_registry_is_listed(self) -> None:
        repo = self.repo()
        repo.write("workflows/sdxl-lora/NOTES.md", "# Notes\n\nPlain text.\n")
        registry = json.loads((repo.work / "tools" / "workflow_policy.json").read_text(encoding="utf-8"))
        registry["workflows"]["sdxl-lora"]["files"].append("NOTES.md")
        repo.write("tools/workflow_policy.json", json.dumps(registry, indent=2) + "\n")
        repo.git("add", "workflows/sdxl-lora/NOTES.md", "tools/workflow_policy.json")
        cand = repo.commit_unchecked("a registered file")
        res = release(repo, cand, "--json")
        self.assertEqual(res.returncode, 0, combined(res))
        manifest = json.loads(res.stdout)["manifest"]
        self.assertEqual(manifest["control_plane_changes"], ["tools/workflow_policy.json"])
        self.assertEqual(manifest["workflow_policy"], "clean")

    def test_a_candidate_that_weakens_the_policy_checker_is_judged_by_the_baseline(self) -> None:
        repo = self.repo()
        repo.write("tools/workflow_policy.py", "import sys\nsys.exit(0)\n")
        repo.write("workflows/sdxl-lora/NOTES.md", "# Notes\n\nPlain text.\n")
        repo.git("add", "tools/workflow_policy.py", "workflows/sdxl-lora/NOTES.md")
        cand = repo.commit_unchecked("weaken the policy checker")
        res = release(repo, cand)
        self.assertEqual(res.returncode, 1, combined(res))
        self.assertEqual(manifests(repo), [])

    def test_a_baseline_without_the_policy_checker_is_refused_unless_bootstrapped(self) -> None:
        repo = self.repo(checker=False)
        shutil.copy2(ROOT / "tools" / "workflow_policy.py", repo.work / "tools" / "workflow_policy.py")
        repo.write("docs/guide.md", "# Guide\n\nA clean change.\n")
        repo.git("add", "tools/workflow_policy.py", "docs/guide.md")
        cand = repo.commit_unchecked("bring the policy checker")
        refused = release(repo, cand)
        self.assertEqual(refused.returncode, 2, combined(refused))
        self.assertIn("--bootstrap-self-judge", combined(refused))
        self.assertEqual(manifests(repo), [])
        boot = release(repo, cand, "--bootstrap-self-judge", "--json")
        self.assertEqual(boot.returncode, 0, combined(boot))
        manifest = json.loads(boot.stdout)["manifest"]
        self.assertIs(manifest["self_judged"], True)
        self.assertEqual(manifest["workflow_policy"], "clean")


def verify(repo: SyntheticRepo, manifest_path: Path, *more: str) -> subprocess.CompletedProcess[str]:
    return repo.check("release", "--verify-manifest", str(manifest_path), "--allowed-url", str(repo.remote), *more)


class ManifestReverifyTests(unittest.TestCase):
    """R12: --verify-manifest runs the release check again and compares every field."""

    def genuine(self, repo: SyntheticRepo, commit: str) -> tuple[Path, dict]:
        res = release(repo, commit, "--json")
        self.assertEqual(res.returncode, 0, combined(res))
        payload = json.loads(res.stdout)
        return Path(payload["manifest_path"]), payload["manifest"]

    def test_a_hand_written_manifest_for_a_never_scanned_candidate_is_invalid(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        base = repo.head()
        scanned = clean_candidate(repo)
        _path, real = self.genuine(repo, scanned)
        never_scanned = marker_candidate(repo)
        # Every field a real manifest has, written by hand for a commit no check ever saw; the
        # policy version is the real one (it does not depend on the candidate).
        forged = {
            **real,
            "candidate_sha": never_scanned,
            "remote_old_sha": base,
            "commit_count": 2,
            "changed_files": [{"status": "M", "path": "docs/guide.md"}, {"status": "A", "path": "docs/notes.md"}],
            "control_plane_changes": [],
            "inline_allow_additions": [],
            "non_candidate_ref_warnings": [],
            "unverified_items": [],
        }
        forged_path = repo.base / "forged.json"
        forged_path.write_text(json.dumps(forged, indent=2) + "\n", encoding="utf-8")
        res = verify(repo, forged_path)
        self.assertEqual(res.returncode, 1, combined(res))
        self.assertIn("INVALID", combined(res))
        self.assertNotIn(SYNTH_MARKER, combined(res))

    def test_an_edited_field_of_a_real_manifest_is_invalid(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        repo.write("tests/test_guard_extra.py", "import unittest\n")
        repo.git("add", "tests/test_guard_extra.py")
        cand = repo.commit_unchecked("a guard test")
        path, real = self.genuine(repo, cand)
        self.assertEqual(verify(repo, path).returncode, 0)
        self.assertEqual(real["control_plane_changes"], ["tests/test_guard_extra.py"])
        edited = repo.base / "edited.json"
        edited.write_text(json.dumps({**real, "control_plane_changes": []}, indent=2) + "\n", encoding="utf-8")
        res = verify(repo, edited)
        self.assertEqual(res.returncode, 1, combined(res))
        self.assertIn("control_plane_changes", combined(res))


if __name__ == "__main__":
    unittest.main()
