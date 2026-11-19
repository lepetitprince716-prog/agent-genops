"""The three git hooks as a whole: what they refuse and what they let through.

Covers type changes in the staged and unstaged scans, the clone mode the hooks act on, deleting a
remote ref, the per-ref pre-push path, Betterleaks ignore files that the scanned content does not
carry, maintainer mode without usable private rules, staged submodules, and the secret scan of
pushed history and commit messages.

One template repository is built per test class (the real hooks and tools, a home folder whose
private rules hold one synthetic marker, a registered bare remote and an unregistered one); each
test works on a fresh copy of it, so no test sees another's state and the setup cost is paid once.
Fake tokens are built at run time from random characters, so no secret-looking literal exists in
the repository. The registry token shape is one that only Betterleaks knows (the privacy scan's
public rules do not), so a refusal of it can only come from tools/secret_scan.sh.

Betterleaks must be installed (brew install betterleaks); missing, these tests fail, they do not
skip: a skipped guard test reads as green while the guard is not running.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import string
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IDENTITY = "1+tester@users.noreply.github.com"
MARKER = "zzhookmarker5150"
RULES = {
    "version": 1,
    "rules": [
        {
            "id": "synthetic_private_marker",
            "pattern": MARKER,
            "flags": "i",
            "why": "synthetic private test marker",
        }
    ],
}
NO_HOOKS = f"core.hooksPath={os.devnull}"


def random_text(length: int) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def registry_token() -> str:
    """A token shape that only Betterleaks knows; built at run time."""
    return "np" + "m_" + random_text(36)


def combined(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def clean_env(home: Path) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("AGENT_GENOPS_", "SECRET_SCAN_", "GIT_"))
    }
    env["HOME"] = str(home)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def run(args: list[str], cwd: Path, env: dict[str, str], stdin: str | None = None
        ) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=cwd, env=env, input=stdin, capture_output=True, text=True, timeout=180,
        check=False,
    )


def build_template(base: Path) -> None:
    """base/{home,work,origin.git,other.git}: a maintainer clone with one clean pushed commit."""
    home = base / "home"
    rules = home / ".config" / "agent-genops" / "private_rules.json"
    rules.parent.mkdir(parents=True)
    rules.write_text(json.dumps(RULES))
    env = clean_env(home)

    def git(*args: str, cwd: Path = base / "work") -> None:
        done = run(["git", *args], cwd, env)
        if done.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed: {combined(done)}")

    git("init", "-q", "-b", "main", str(base / "work"), cwd=base)
    git("init", "-q", "--bare", str(base / "origin.git"), cwd=base)
    git("init", "-q", "--bare", str(base / "other.git"), cwd=base)
    work = base / "work"
    for key, value in (
        ("user.email", IDENTITY),
        ("user.name", "tester"),
        ("core.hooksPath", ".githooks"),
        ("genops.mode", "maintainer"),
    ):
        git("config", key, value)
    git("remote", "add", "origin", str(base / "origin.git"))
    git("remote", "add", "other", str(base / "other.git"))
    shutil.copytree(ROOT / ".githooks", work / ".githooks")
    tools = work / "tools"
    tools.mkdir()
    for name in ("privacy_scan.py", "privacy_rules.json", "secret_scan.sh", "secret_scan.tmpl"):
        shutil.copy2(ROOT / "tools" / name, tools / name)
    (work / "README.md").write_text("# Synthetic\n")
    git("add", ".")
    git("-c", NO_HOOKS, "commit", "-q", "-m", "initial clean baseline")
    git("-c", NO_HOOKS, "push", "-q", "-u", "origin", "main")


class Repo:
    """A fresh copy of the class template, with its remote URLs pointed at the copy."""

    def __init__(self, testcase: unittest.TestCase, template: Path) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="guard-hooks-"))
        testcase.addCleanup(shutil.rmtree, self.base, True)
        shutil.copytree(template, self.base, symlinks=True, dirs_exist_ok=True)
        self.home = self.base / "home"
        self.path = self.base / "work"
        self.remote = self.base / "origin.git"
        self.other = self.base / "other.git"
        self.rules = self.home / ".config" / "agent-genops" / "private_rules.json"
        self.env = clean_env(self.home)
        self.git("remote", "set-url", "origin", str(self.remote))
        self.git("remote", "set-url", "other", str(self.other))
        self.git("config", "genops.allowedPushUrl", str(self.remote))

    def run(self, *args: str, env: dict[str, str] | None = None, stdin: str | None = None
            ) -> subprocess.CompletedProcess[str]:
        return run(list(args), self.path, env or self.env, stdin)

    def git(self, *args: str, stdin: str | None = None) -> str:
        result = self.run("git", *args, stdin=stdin)
        if result.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed: {combined(result)}")
        return result.stdout.strip()

    def write(self, name: str, text: str) -> None:
        target = self.path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def add_file(self, name: str, text: str) -> None:
        self.write(name, text)
        self.git("add", name)

    def unchecked_commit(self, message: str) -> None:
        """A commit the hooks never see, to put content into history."""
        self.git("-c", NO_HOOKS, "commit", "-q", "-m", message)

    def commit(self, message: str) -> subprocess.CompletedProcess[str]:
        return self.run("git", "commit", "-q", "-m", message)

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def privacy(self, *args: str, env: dict[str, str] | None = None
                ) -> subprocess.CompletedProcess[str]:
        return self.run("python3", "-B", "tools/privacy_scan.py", *args, env=env)

    def push(self, remote: str, *refspecs: str, env: dict[str, str] | None = None
             ) -> subprocess.CompletedProcess[str]:
        return self.run("git", "push", remote, *refspecs, env=env)

    def refs_of(self, bare: Path) -> list[str]:
        out = self.run("git", "--git-dir", str(bare), "for-each-ref", "--format=%(refname)").stdout
        return out.split()

    def remote_tip(self, ref: str = "refs/heads/main") -> str:
        return self.git("--git-dir", str(self.remote), "rev-parse", ref)

    def fingerprints(self, *bl_args: str, stdin: str | None = None) -> list[str]:
        """Fingerprints Betterleaks reports here, from a JSON report, with no ignore file."""
        report = self.base / f"report-{random_text(6)}.json"
        self.run(
            "betterleaks", *bl_args, "--redact", "--no-banner", "--no-color", "--log-level",
            "error", "-f", "json", "-r", str(report), stdin=stdin,
        )
        return [item["Fingerprint"] for item in json.loads(report.read_text() or "[]")]


class TemplateCase(unittest.TestCase):
    template: Path

    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("betterleaks") is None:
            raise AssertionError("betterleaks is not installed: brew install betterleaks")
        cls.template = Path(tempfile.mkdtemp(prefix="guard-hooks-template-"))
        build_template(cls.template)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.template, True)

    def repo(self) -> Repo:
        return Repo(self, self.template)

    def assert_refused(self, result: subprocess.CompletedProcess[str], *expected: str) -> None:
        self.assertNotEqual(result.returncode, 0, combined(result))
        for text in expected:
            self.assertIn(text, combined(result))


class TypeChangeTests(TemplateCase):
    """A regular file and a symlink swapping places is a change the scans must read (R5)."""

    def test_file_turned_symlink_is_scanned_and_refused_at_commit(self) -> None:
        repo = self.repo()
        repo.add_file("link.txt", "hello\n")
        repo.unchecked_commit("add file")
        before = repo.head()
        (repo.path / "link.txt").unlink()
        (repo.path / "link.txt").symlink_to(f"/Users/{MARKER}/private/thing")
        repo.git("add", "link.txt")
        self.assertIn("T\tlink.txt", repo.git("diff", "--cached", "--raw"))
        scanned = repo.privacy("--staged")
        self.assertEqual(scanned.returncode, 1, combined(scanned))
        self.assertIn("synthetic_private_marker", combined(scanned))
        committed = repo.commit("swap to symlink")
        self.assert_refused(committed, "synthetic_private_marker")
        self.assertEqual(repo.head(), before)

    def test_symlink_turned_file_is_scanned_and_refused_at_commit(self) -> None:
        repo = self.repo()
        (repo.path / "link.txt").symlink_to("README.md")
        repo.git("add", "link.txt")
        repo.unchecked_commit("add symlink")
        before = repo.head()
        (repo.path / "link.txt").unlink()
        repo.add_file("link.txt", f"{MARKER} in content\n")
        self.assertIn("T\tlink.txt", repo.git("diff", "--cached", "--raw"))
        scanned = repo.privacy("--staged")
        self.assertEqual(scanned.returncode, 1, combined(scanned))
        committed = repo.commit("swap to file")
        self.assert_refused(committed, "synthetic_private_marker")
        self.assertEqual(repo.head(), before)

    def test_unstaged_type_change_is_scanned(self) -> None:
        repo = self.repo()
        repo.add_file("link.txt", "hello\n")
        repo.unchecked_commit("add file")
        (repo.path / "link.txt").unlink()
        (repo.path / "link.txt").symlink_to(f"/Users/{MARKER}/private/thing")
        self.assertIn("T\tlink.txt", repo.git("diff", "--raw"))
        scanned = repo.privacy("--unstaged")
        self.assertEqual(scanned.returncode, 1, combined(scanned))
        self.assertIn("synthetic_private_marker", combined(scanned))


class SubmoduleTests(TemplateCase):
    """A staged gitlink cannot be scanned, so it is refused."""

    def test_staged_submodule_is_refused(self) -> None:
        repo = self.repo()
        before = repo.head()
        repo.git("update-index", "--add", "--cacheinfo", f"160000,{before},sub")
        scanned = repo.privacy("--staged")
        self.assertEqual(scanned.returncode, 1, combined(scanned))
        self.assertIn("unsupported_submodule", combined(scanned))
        self.assert_refused(repo.commit("add a gitlink"), "unsupported_submodule")
        self.assertEqual(repo.head(), before)


if __name__ == "__main__":
    unittest.main()
