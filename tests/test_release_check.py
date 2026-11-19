"""End-to-end synthetic tests for ./check changed, ./check release, privacy_scan extensions,
secret_scan extensions, and the updated git hooks (T1-T6 local A+B acceptance).

All tests run inside isolated temporary directories with synthetic markers, fake tokens generated
at runtime, and local bare repositories. No real GitHub network calls or real private rules are
touched.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import stat
import string
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IDENTITY = "1+tester@users.noreply.github.com"
SYNTH_MARKER = "synmarker9942alpha"


def random_text(length: int) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def fake_gh_token() -> str:
    return "ghp_" + random_text(36)


def combined(proc: subprocess.CompletedProcess[str]) -> str:
    return proc.stdout + "\n" + proc.stderr


class SyntheticRepo:
    """Isolated clone + local bare remote with real scripts, hooks, and synthetic private rules."""

    def __init__(self, testcase: unittest.TestCase, *, maintainer: bool = True) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="genops-ab-"))
        testcase.addCleanup(shutil.rmtree, self.base, True)
        self.home = self.base / "home"
        self.home.mkdir()
        self.work = self.base / "work"
        self.remote = self.base / "origin.git"
        self.manifest_dir = self.base / "manifests"
        self.manifest_dir.mkdir()
        self.private_rules_file = self.home / ".config" / "agent-genops" / "private_rules.json"

        self.env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("AGENT_GENOPS_") and not k.startswith("SECRET_SCAN_")
        }
        self.env["HOME"] = str(self.home)
        self.env["GIT_CONFIG_GLOBAL"] = os.devnull
        self.env["GIT_CONFIG_NOSYSTEM"] = "1"

        self.git("init", "-q", "-b", "main", str(self.work), cwd=self.base)
        self.git("init", "-q", "--bare", str(self.remote), cwd=self.base)
        for key, value in (
            ("user.email", IDENTITY),
            ("user.name", "tester"),
            ("core.hooksPath", ".githooks"),
            ("genops.allowedPushUrl", str(self.remote)),
        ):
            self.git("config", key, value)
        if maintainer:
            self.git("config", "genops.mode", "maintainer")
        self.git("remote", "add", "origin", str(self.remote))

        self.write_private_rules(
            {
                "version": 1,
                "rules": [
                    {
                        "id": "synthetic_private_marker",
                        "pattern": SYNTH_MARKER,
                        "flags": "i",
                        "why": "synthetic private test marker",
                    }
                ],
            }
        )

        # Copy real guard machinery into the synthetic repo.
        shutil.copytree(ROOT / ".githooks", self.work / ".githooks")
        tools = self.work / "tools"
        tools.mkdir()
        for name in (
            "privacy_scan.py",
            "privacy_rules.json",
            "secret_scan.sh",
            "secret_scan.tmpl",
            "release_check.py",
        ):
            shutil.copy2(ROOT / "tools" / name, tools / name)
        shutil.copy2(ROOT / "check", self.work / "check")
        (self.work / "check").chmod(0o755)
        (self.work / "README.md").write_text("# Synthetic\n\nSee [docs](docs/guide.md).\n")
        (self.work / "docs").mkdir()
        (self.work / "docs" / "guide.md").write_text("# Guide\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "initial clean baseline")
        self.git("push", "-q", "-u", "origin", "main")

    def write_private_rules(self, data: dict | str) -> None:
        self.private_rules_file.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            self.private_rules_file.write_text(data, encoding="utf-8")
        else:
            self.private_rules_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def run(
        self, *args: str, env: dict[str, str] | None = None, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            cwd=cwd or self.work,
            env=env or self.env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    def git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        res = self.run("git", *args, cwd=cwd)
        if res.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed ({res.returncode}): {combined(res)}")
        return res

    def check(
        self, *args: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return self.run(sys.executable, "-B", str(self.work / "check"), *args, env=env)

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").stdout.strip()

    def write(self, rel: str, text: str) -> Path:
        p = self.work / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def commit_unchecked(self, message: str) -> str:
        self.git("-c", f"core.hooksPath={os.devnull}", "commit", "-q", "-m", message)
        return self.head()


class ReleaseAndCheckTests(unittest.TestCase):
    def need_betterleaks(self) -> None:
        if shutil.which("betterleaks") is None:
            self.fail("betterleaks is not installed: brew install betterleaks")

    # --- T1: contributor vs maintainer modes & fail-closed degradation prevention ---

    def test_t1_contributor_passes_without_private_rules_but_cannot_release(self) -> None:
        self.need_betterleaks()
        repo = SyntheticRepo(self, maintainer=False)
        os.unlink(repo.private_rules_file)
        repo.write("docs/guide.md", "# Guide\n\nClean contributor update.\n")
        res = repo.check("changed")
        self.assertEqual(res.returncode, 0, combined(res))
        self.assertIn("NOT a release check", combined(res))

        repo.git("add", "docs/guide.md")
        repo.git("commit", "-q", "-m", "clean doc update")
        rel = repo.check(
            "release",
            "--to",
            "origin",
            "--ref",
            "refs/heads/main",
            "--commit",
            repo.head(),
            "--allowed-url",
            str(repo.remote),
            "--manifest-dir",
            str(repo.manifest_dir),
        )
        self.assertNotEqual(rel.returncode, 0, combined(rel))
        self.assertEqual(list(repo.manifest_dir.iterdir()), [])

    def test_t1_maintainer_fails_closed_without_env_var(self) -> None:
        self.need_betterleaks()
        repo = SyntheticRepo(self, maintainer=True)
        # No AGENT_GENOPS_REQUIRE_PRIVATE in env; clone config genops.mode=maintainer governs.
        self.assertNotIn("AGENT_GENOPS_REQUIRE_PRIVATE", repo.env)

        # (a) Missing private rules file must NOT silently downgrade to contributor mode.
        os.unlink(repo.private_rules_file)
        missing = repo.check("changed")
        self.assertEqual(missing.returncode, 2, combined(missing))
        self.assertNotIn("PASS", combined(missing))

        # (b) Empty rules list (0 rules) must fail closed.
        repo.write_private_rules({"version": 1, "rules": []})
        empty = repo.check("changed")
        self.assertEqual(empty.returncode, 2, combined(empty))
        self.assertIn("0 rules", combined(empty))

        # (c) Corrupt JSON must fail closed.
        repo.write_private_rules("{not valid json")
        corrupt = repo.check("changed")
        self.assertEqual(corrupt.returncode, 2, combined(corrupt))

        # (d) Missing betterleaks on PATH must fail closed.
        repo.write_private_rules(
            {
                "version": 1,
                "rules": [{"id": "m", "pattern": SYNTH_MARKER, "why": "test"}],
            }
        )
        shim = repo.base / "shim_no_bl"
        shim.mkdir()
        for name, target in (
            ("git", shutil.which("git")),
            ("python3", sys.executable),
            ("dirname", shutil.which("dirname")),
            ("sh", "/bin/sh"),
        ):
            assert target is not None
            (shim / name).symlink_to(target)
        env_no_bl = dict(repo.env, PATH=str(shim))
        no_bl = repo.check("changed", env=env_no_bl)
        self.assertEqual(no_bl.returncode, 2, combined(no_bl))
        self.assertIn("betterleaks", combined(no_bl).lower())

    # --- T2: staged vs unstaged vs untracked vs clean branch + doc-only routing ---

    def test_t2_staged_unstaged_untracked_and_clean_branch_coverage(self) -> None:
        self.need_betterleaks()
        repo = SyntheticRepo(self, maintainer=True)

        # (a) Staged has synthetic marker, working tree already fixed -> MUST refuse and flag [staged].
        repo.write("docs/guide.md", f"# Guide\n{SYNTH_MARKER}\n")
        repo.git("add", "docs/guide.md")
        repo.write("docs/guide.md", "# Guide\nclean now in worktree\n")
        r_staged = repo.check("changed")
        self.assertEqual(r_staged.returncode, 1, combined(r_staged))
        self.assertIn("[staged]", combined(r_staged))
        self.assertNotIn(SYNTH_MARKER, combined(r_staged))

        # (b) Staged clean, working tree has synthetic marker -> MUST refuse and flag [unstaged].
        repo.git("add", "docs/guide.md")
        repo.write("docs/guide.md", f"# Guide\n{SYNTH_MARKER}\n")
        r_unstaged = repo.check("changed")
        self.assertEqual(r_unstaged.returncode, 1, combined(r_unstaged))
        self.assertIn("[unstaged]", combined(r_unstaged))
        self.assertNotIn(SYNTH_MARKER, combined(r_unstaged))

        # Reset guide.md, add untracked file with fake secret -> MUST refuse and flag [untracked].
        repo.write("docs/guide.md", "# Guide\n")
        repo.git("add", "docs/guide.md")
        tok = fake_gh_token()
        repo.write("scratch.txt", f"key = {tok}\n")
        r_untracked = repo.check("changed")
        self.assertEqual(r_untracked.returncode, 1, combined(r_untracked))
        self.assertIn("[untracked]", combined(r_untracked))
        self.assertNotIn(tok, combined(r_untracked))
        os.unlink(repo.work / "scratch.txt")

        # (c) Clean working tree on a branch that has an unmerged bad commit -> MUST flag [branch].
        repo.git("checkout", "-q", "-b", "feature-bad")
        repo.write("docs/guide.md", f"# Guide\n{SYNTH_MARKER}\n")
        repo.git("add", "docs/guide.md")
        repo.commit_unchecked("commit with synthetic marker")
        self.assertEqual(repo.git("status", "--porcelain").stdout.strip(), "")
        r_branch = repo.check("changed")
        self.assertEqual(r_branch.returncode, 1, combined(r_branch))
        self.assertIn("[branch]", combined(r_branch))
        self.assertNotIn(SYNTH_MARKER, combined(r_branch))

        # (d) Clean doc-only change -> PASS, doc-links PASS, Rust/cwc/guard tests NOT RUN.
        repo.git("checkout", "-q", "main")
        repo.write("docs/guide.md", "# Guide\n\nSee [README](../README.md).\n")
        r_doc = repo.check("changed", "--json")
        self.assertEqual(r_doc.returncode, 0, combined(r_doc))
        data = json.loads(r_doc.stdout)
        statuses = {t["name"]: t["status"] for t in data["tests"]}
        self.assertEqual(statuses["doc-links"], "PASS")
        self.assertEqual(statuses["cwc-tests"], "NOT RUN")
        self.assertEqual(statuses["rdbg-tests"], "NOT RUN")
        self.assertEqual(statuses["artfetch-tests"], "NOT RUN")
        self.assertEqual(statuses["guard-tests"], "NOT RUN")

    # --- T3: sensitive path & ref redaction, duplicate-blob/deleted paths, symlink/LFS/submodule/replace ---

    def test_t3_path_ref_redaction_and_historical_paths(self) -> None:
        self.need_betterleaks()
        repo = SyntheticRepo(self, maintainer=True)

        # (a) Sensitive filename with clean content, then deleted in next commit -> release MUST refuse & redact.
        bad_rel = f"notes/{SYNTH_MARKER}_notes.md"
        repo.write(bad_rel, "completely benign text\n")
        repo.git("add", bad_rel)
        repo.commit_unchecked("add benign file at sensitive path")
        # Copy same blob to clean path (duplicate blob across two paths) and remove old path.
        repo.write("notes/clean_notes.md", "completely benign text\n")
        repo.git("rm", "-q", bad_rel)
        repo.git("add", "notes/clean_notes.md")
        cand = repo.commit_unchecked("rename/delete old sensitive path")

        rel = repo.check(
            "release",
            "--to",
            "origin",
            "--ref",
            "refs/heads/main",
            "--commit",
            cand,
            "--allowed-url",
            str(repo.remote),
            "--manifest-dir",
            str(repo.manifest_dir),
        )
        out = combined(rel)
        self.assertEqual(rel.returncode, 1, out)
        self.assertIn("<redacted-path#", out)
        self.assertNotIn(SYNTH_MARKER, out)
        self.assertEqual(list(repo.manifest_dir.iterdir()), [])

        # (b) Clean repo, sensitive target ref name -> MUST refuse & redact ref name.
        repo2 = SyntheticRepo(self, maintainer=True)
        repo2.write("docs/guide.md", "# Guide\nClean change.\n")
        repo2.git("add", "docs/guide.md")
        repo2.git("commit", "-q", "-m", "clean change")
        bad_ref = f"refs/heads/{SYNTH_MARKER}-branch"
        rel_ref = repo2.check(
            "release",
            "--to",
            "origin",
            "--ref",
            bad_ref,
            "--commit",
            repo2.head(),
            "--allow-new-ref",
            "--allowed-url",
            str(repo2.remote),
            "--manifest-dir",
            str(repo2.manifest_dir),
        )
        out2 = combined(rel_ref)
        self.assertEqual(rel_ref.returncode, 1, out2)
        self.assertIn("<redacted-ref#", out2)
        self.assertNotIn(SYNTH_MARKER, out2)

        # (c) Dual-review anti-leak: BOTH content secret/privacy hit AND sensitive filename -> neither leaks!
        tok = fake_gh_token()
        fake_email = "leaked" + "@" + "private-domain.test"
        sens_file = f"docs/{SYNTH_MARKER}_leak.txt"
        repo2.write(sens_file, f"token = {tok}\nemail = {fake_email}\n")
        r_both = repo2.check("changed")
        out_both = combined(r_both)
        self.assertEqual(r_both.returncode, 1, out_both)
        self.assertNotIn(SYNTH_MARKER, out_both)
        self.assertNotIn(tok, out_both)
        self.assertIn("<redacted-path#", out_both)

    def test_t3_symlink_lfs_submodule_and_replace_refs_fail_closed(self) -> None:
        self.need_betterleaks()
        # (a) Symlink target containing synthetic marker (dangling symlink: not followed).
        repo = SyntheticRepo(self, maintainer=True)
        link = repo.work / "docs" / "link_ref"
        link.symlink_to(f"/nonexistent/{SYNTH_MARKER}/target")
        repo.git("add", "docs/link_ref")
        cand = repo.commit_unchecked("add symlink")
        r_sym = repo.check(
            "release",
            "--to",
            "origin",
            "--ref",
            "refs/heads/main",
            "--commit",
            cand,
            "--allowed-url",
            str(repo.remote),
            "--manifest-dir",
            str(repo.manifest_dir),
        )
        self.assertEqual(r_sym.returncode, 1, combined(r_sym))
        self.assertNotIn(SYNTH_MARKER, combined(r_sym))

        # (b) Git LFS pointer fails closed.
        repo_lfs = SyntheticRepo(self, maintainer=True)
        lfs_text = (
            "version https://git-lfs.github.com/spec/v1\n"
            "oid sha256:" + "a" * 64 + "\n"
            "size 12345\n"
        )
        repo_lfs.write("assets/sample.bin", lfs_text)
        repo_lfs.git("add", "assets/sample.bin")
        cand_lfs = repo_lfs.commit_unchecked("add lfs pointer")
        r_lfs = repo_lfs.check(
            "release",
            "--to",
            "origin",
            "--ref",
            "refs/heads/main",
            "--commit",
            cand_lfs,
            "--allowed-url",
            str(repo_lfs.remote),
            "--manifest-dir",
            str(repo_lfs.manifest_dir),
        )
        self.assertEqual(r_lfs.returncode, 1, combined(r_lfs))
        self.assertIn("unsupported_lfs_pointer", combined(r_lfs))

        # (c) Git submodule (160000 gitlink) fails closed.
        repo_sub = SyntheticRepo(self, maintainer=True)
        fake_sub_oid = repo_sub.head()
        repo_sub.git("update-index", "--add", "--cacheinfo", f"160000,{fake_sub_oid},ext/submod")
        cand_sub = repo_sub.commit_unchecked("add gitlink")
        r_sub = repo_sub.check(
            "release",
            "--to",
            "origin",
            "--ref",
            "refs/heads/main",
            "--commit",
            cand_sub,
            "--allowed-url",
            str(repo_sub.remote),
            "--manifest-dir",
            str(repo_sub.manifest_dir),
        )
        self.assertEqual(r_sub.returncode, 1, combined(r_sub))
        self.assertIn("unsupported_submodule", combined(r_sub))

        # (d) Active refs/replace/* fails closed.
        repo_rep = SyntheticRepo(self, maintainer=True)
        first = repo_rep.head()
        repo_rep.write("docs/guide.md", "# Guide\nUpdated.\n")
        repo_rep.git("add", "docs/guide.md")
        second = repo_rep.commit_unchecked("second")
        repo_rep.git("replace", second, first)
        r_rep = repo_rep.check(
            "release",
            "--to",
            "origin",
            "--ref",
            "refs/heads/main",
            "--commit",
            second,
            "--allowed-url",
            str(repo_rep.remote),
            "--manifest-dir",
            str(repo_rep.manifest_dir),
        )
        self.assertEqual(r_rep.returncode, 1, combined(r_rep))
        self.assertIn("replace_ref", combined(r_rep))

    # --- T4: bare-repo rehearsal, drift invalidation, non-candidate warnings, contributor fork ---

    def test_t4_bare_repo_rehearsal_drift_and_non_candidate_warning(self) -> None:
        self.need_betterleaks()
        repo = SyntheticRepo(self, maintainer=True)

        # Create a dirty local side branch that must NOT block a clean main push (only warn).
        repo.git("checkout", "-q", "-b", "old-dirty-local")
        repo.write("docs/guide.md", f"# Dirty local\n{SYNTH_MARKER}\n")
        repo.git("add", "docs/guide.md")
        repo.commit_unchecked("dirty local side branch")

        # Return to main and make a clean release candidate.
        repo.git("checkout", "-q", "main")
        repo.write("docs/guide.md", "# Guide\n\nClean release update.\n")
        repo.git("add", "docs/guide.md")
        repo.git("commit", "-q", "-m", "clean release update")
        cand = repo.head()

        rel = repo.check(
            "release",
            "--to",
            "origin",
            "--ref",
            "refs/heads/main",
            "--commit",
            cand,
            "--allowed-url",
            str(repo.remote),
            "--manifest-dir",
            str(repo.manifest_dir),
            "--json",
        )
        self.assertEqual(rel.returncode, 0, combined(rel))
        payload = json.loads(rel.stdout)
        manifest_path = Path(payload["manifest_path"])
        manifest = payload["manifest"]
        self.assertEqual(manifest["candidate_sha"], cand)
        self.assertGreaterEqual(len(manifest["non_candidate_ref_warnings"]), 1)
        self.assertNotIn(SYNTH_MARKER, rel.stdout)

        # Manifest verifies cleanly before push.
        v_ok = repo.check(
            "release",
            "--verify-manifest",
            str(manifest_path),
            "--allowed-url",
            str(repo.remote),
        )
        self.assertEqual(v_ok.returncode, 0, combined(v_ok))

        # Execute the approved single-ref push -> pre-push warns on dirty side branch but allows clean main.
        push_res = repo.run("git", "push", "origin", f"{cand}:refs/heads/main")
        self.assertEqual(push_res.returncode, 0, combined(push_res))
        self.assertIn("warning: non-candidate local ref(s)", combined(push_res))
        self.assertNotIn(SYNTH_MARKER, combined(push_res))

        # Bare remote must ONLY have main at cand (old-dirty-local was never pushed).
        remote_refs = repo.git("for-each-ref", "--format=%(refname) %(objectname)", cwd=repo.remote).stdout.strip()
        self.assertEqual(remote_refs, f"refs/heads/main {cand}")

        # Now remote moved -> old manifest MUST fail verification!
        v_stale = repo.check(
            "release",
            "--verify-manifest",
            str(manifest_path),
            "--allowed-url",
            str(repo.remote),
        )
        self.assertNotEqual(v_stale.returncode, 0, combined(v_stale))
        self.assertIn("changed since preparation", combined(v_stale))

        # Prepare a new manifest, then move local main -> verification MUST fail!
        repo.write("docs/guide.md", "# Guide\n\nSecond clean update.\n")
        repo.git("add", "docs/guide.md")
        repo.git("commit", "-q", "-m", "second clean update")
        cand2 = repo.head()
        rel2 = repo.check(
            "release",
            "--to",
            "origin",
            "--ref",
            "refs/heads/main",
            "--commit",
            cand2,
            "--allowed-url",
            str(repo.remote),
            "--manifest-dir",
            str(repo.manifest_dir),
            "--json",
        )
        self.assertEqual(rel2.returncode, 0, combined(rel2))
        m2 = json.loads(rel2.stdout)["manifest_path"]
        repo.write("docs/guide.md", "# Guide\n\nUnreviewed extra commit.\n")
        repo.git("add", "docs/guide.md")
        repo.git("commit", "-q", "-m", "extra commit after manifest")
        v_moved = repo.check(
            "release",
            "--verify-manifest",
            m2,
            "--allowed-url",
            str(repo.remote),
        )
        self.assertNotEqual(v_moved.returncode, 0, combined(v_moved))
        self.assertIn("moved since manifest preparation", combined(v_moved))

        # Extra remote or unapproved URL or missing --allow-new-ref must all be rejected.
        unapproved_new = repo.check(
            "release",
            "--to",
            "origin",
            "--ref",
            "refs/heads/unapproved-new",
            "--commit",
            repo.head(),
            "--allowed-url",
            str(repo.remote),
            "--manifest-dir",
            str(repo.manifest_dir),
        )
        self.assertEqual(unapproved_new.returncode, 2, combined(unapproved_new))

        extra_remote = repo.base / "extra.git"
        repo.git("init", "-q", "--bare", str(extra_remote), cwd=repo.base)
        repo.git("remote", "add", "rogue", str(extra_remote))
        r_extra = repo.check(
            "release",
            "--to",
            "origin",
            "--ref",
            "refs/heads/main",
            "--commit",
            repo.head(),
            "--allowed-url",
            str(repo.remote),
            "--manifest-dir",
            str(repo.manifest_dir),
        )
        self.assertEqual(r_extra.returncode, 2, combined(r_extra))
        # Maintainer pre-push must refuse pushing to rogue URL.
        p_rogue = repo.run("git", "push", "rogue", "main")
        self.assertNotEqual(p_rogue.returncode, 0, combined(p_rogue))
        self.assertEqual(
            repo.git("for-each-ref", cwd=extra_remote).stdout.strip(), ""
        )

    def test_t4_contributor_can_push_to_own_fork(self) -> None:
        self.need_betterleaks()
        repo = SyntheticRepo(self, maintainer=False)
        fork_remote = repo.base / "contributor-fork.git"
        repo.git("init", "-q", "--bare", str(fork_remote), cwd=repo.base)
        repo.git("remote", "add", "myfork", str(fork_remote))
        # Unset custom allowedPushUrl so default upstream policy applies only to maintainer mode.
        repo.git("config", "--unset", "genops.allowedPushUrl")
        res = repo.run("git", "push", "myfork", "main")
        self.assertEqual(res.returncode, 0, combined(res))

    # --- T5: trusted baseline blocks self-weakening, .betterleaksignore/.gitleaksignore, lists inline allow ---

    def test_t5_trusted_baseline_blocks_self_weakening_and_ignore_bypass(self) -> None:
        self.need_betterleaks()
        # (a) Candidate weakens tools/privacy_scan.py to always exit 0 while slipping in a marker.
        repo = SyntheticRepo(self, maintainer=True)
        repo.write("tools/privacy_scan.py", "import sys\nsys.exit(0)\n")
        repo.write("docs/guide.md", f"# Guide\n{SYNTH_MARKER}\n")
        repo.git("add", "tools/privacy_scan.py", "docs/guide.md")
        cand = repo.commit_unchecked("attempt to disable privacy_scan")
        rel = repo.check(
            "release",
            "--to",
            "origin",
            "--ref",
            "refs/heads/main",
            "--commit",
            cand,
            "--allowed-url",
            str(repo.remote),
            "--manifest-dir",
            str(repo.manifest_dir),
        )
        self.assertEqual(rel.returncode, 1, combined(rel))
        self.assertEqual(list(repo.manifest_dir.iterdir()), [])

        # (b) Candidate adds .gitleaksignore (legacy name) to hide a newly added secret -> MUST block!
        repo2 = SyntheticRepo(self, maintainer=True)
        tok = fake_gh_token()
        repo2.write("docs/sample.txt", f"token = {tok}\n")
        repo2.git("add", "docs/sample.txt")
        c1 = repo2.commit_unchecked("slip token")
        repo2.write(".gitleaksignore", f"{c1}:docs/sample.txt:github-pat:1\n")
        repo2.git("add", ".gitleaksignore")
        c2 = repo2.commit_unchecked("try hiding via .gitleaksignore")
        rel2 = repo2.check(
            "release",
            "--to",
            "origin",
            "--ref",
            "refs/heads/main",
            "--commit",
            c2,
            "--allowed-url",
            str(repo2.remote),
            "--manifest-dir",
            str(repo2.manifest_dir),
        )
        self.assertEqual(rel2.returncode, 1, combined(rel2))
        self.assertNotIn(tok, combined(rel2))
        self.assertEqual(list(repo2.manifest_dir.iterdir()), [])

        # (c) Candidate adds an inline betterleaks:allow -> manifest explicitly flags it for review.
        repo3 = SyntheticRepo(self, maintainer=True)
        repo3.write("docs/guide.md", "# Guide\nexample = placeholder  # betterleaks:allow\n")
        repo3.git("add", "docs/guide.md")
        repo3.git("commit", "-q", "-m", "add inline allow")
        rel3 = repo3.check(
            "release",
            "--to",
            "origin",
            "--ref",
            "refs/heads/main",
            "--commit",
            repo3.head(),
            "--allowed-url",
            str(repo3.remote),
            "--manifest-dir",
            str(repo3.manifest_dir),
            "--json",
        )
        self.assertEqual(rel3.returncode, 0, combined(rel3))
        m3 = json.loads(rel3.stdout)["manifest"]
        self.assertEqual(m3["inline_allow_additions"], ["docs/guide.md"])

        # (d) Ordinary clean code change -> 0 control-plane changes and 0 inline allows.
        repo4 = SyntheticRepo(self, maintainer=True)
        repo4.write("docs/guide.md", "# Guide\nOrdinary clean edit.\n")
        repo4.git("add", "docs/guide.md")
        repo4.git("commit", "-q", "-m", "ordinary edit")
        rel4 = repo4.check(
            "release",
            "--to",
            "origin",
            "--ref",
            "refs/heads/main",
            "--commit",
            repo4.head(),
            "--allowed-url",
            str(repo4.remote),
            "--manifest-dir",
            str(repo4.manifest_dir),
            "--json",
        )
        self.assertEqual(rel4.returncode, 0, combined(rel4))
        m4 = json.loads(rel4.stdout)["manifest"]
        self.assertEqual(m4["control_plane_changes"], [])
        self.assertEqual(m4["inline_allow_additions"], [])

    # --- Regression: secret_scan.sh must not swallow git for-each-ref failure ---

    def test_secret_scan_for_each_ref_failure_not_swallowed(self) -> None:
        self.need_betterleaks()
        repo = SyntheticRepo(self, maintainer=True)
        real_git = shutil.which("git")
        assert real_git is not None
        shim = repo.base / "shim_fail_ref"
        shim.mkdir()
        git_wrapper = shim / "git"
        git_wrapper.write_text(
            "#!/bin/sh\n"
            'for arg in "$@"; do\n'
            '  if [ "$arg" = "for-each-ref" ]; then\n'
            "    exit 128\n"
            "  fi\n"
            "done\n"
            f'exec "{real_git}" "$@"\n',
            encoding="utf-8",
        )
        git_wrapper.chmod(git_wrapper.stat().st_mode | stat.S_IXUSR)
        env = dict(repo.env, PATH=f"{shim}:{repo.env.get('PATH', '')}")
        res = repo.run("sh", "tools/secret_scan.sh", "history", env=env)
        self.assertNotEqual(res.returncode, 0, combined(res))

    # --- Stage C: privacy.yml trusted-base contract & tag-shadow resistance ---

    def test_stage_c_privacy_workflow_contract_and_tag_shadow_resistance(self) -> None:
        workflow_path = ROOT / ".github" / "workflows" / "privacy.yml"
        self.assertTrue(workflow_path.is_file(), "privacy.yml must exist")
        wf_text = workflow_path.read_text(encoding="utf-8")
        # Trigger covers all pushes and pull requests; isolated Python and no persisted creds.
        self.assertIn("persist-credentials: false", wf_text)
        self.assertIn("python3 -I -B", wf_text)
        self.assertIn("show-ref --verify --hash", wf_text)
        self.assertIn("SECRET_SCAN_IGNORE_PATH=", wf_text)
        self.assertIn("guard-tests:", wf_text)
        self.assertNotIn("branches: [main]", wf_text)

        # Simulate a malicious PR that adds a tag named `origin/main` pointing at a weakened
        # commit; exact `show-ref --verify --hash refs/remotes/origin/main` must still resolve
        # the real base commit rather than the shadowing tag.
        repo = SyntheticRepo(self, maintainer=True)
        real_base = repo.head()
        repo.git("checkout", "-q", "-b", "pr-evil")
        repo.write("tools/privacy_scan.py", "import sys\nsys.exit(0)\n")
        repo.write("docs/guide.md", "email = " + "leaked" + "@" + "private-domain.test\n")
        repo.git("add", "tools/privacy_scan.py", "docs/guide.md")
        evil_head = repo.commit_unchecked("evil PR trying to shadow origin/main with a tag")
        repo.git("tag", "origin/main", evil_head)

        resolved = repo.git(
            "--no-replace-objects", "show-ref", "--verify", "--hash", "refs/remotes/origin/main"
        ).stdout.strip()
        self.assertEqual(resolved, real_base)
        self.assertNotEqual(resolved, evil_head)

        # Running the base-extracted privacy_scan.py in isolated mode (-I -B) must catch the leak.
        with tempfile.TemporaryDirectory(prefix="genops-pr-base-") as td:
            td_path = Path(td)
            (td_path / "privacy_scan.py").write_bytes(
                subprocess.run(
                    ["git", "--no-replace-objects", "show", f"{resolved}:tools/privacy_scan.py"],
                    cwd=repo.work,
                    capture_output=True,
                    check=True,
                ).stdout
            )
            (td_path / "privacy_rules.json").write_bytes(
                subprocess.run(
                    ["git", "--no-replace-objects", "show", f"{resolved}:tools/privacy_rules.json"],
                    cwd=repo.work,
                    capture_output=True,
                    check=True,
                ).stdout
            )
            scan = repo.run(
                sys.executable,
                "-I",
                "-B",
                str(td_path / "privacy_scan.py"),
                "--rules",
                str(td_path / "privacy_rules.json"),
                "--no-private",
                "--tracked",
                "--history",
            )
            self.assertEqual(scan.returncode, 1, combined(scan))
            self.assertIn("email", combined(scan))


if __name__ == "__main__":
    unittest.main()
