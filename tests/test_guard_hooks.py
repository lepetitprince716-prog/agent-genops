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


class CloneModeTests(TemplateCase):
    """The hooks act on the scanner's one reading of genops.mode (R6)."""

    def test_mode_is_read_case_insensitively_and_the_hook_follows_it(self) -> None:
        for value in ("Maintainer", "MAINTAINER", " maintainer "):
            with self.subTest(mode=value):
                repo = self.repo()
                repo.git("config", "genops.mode", value)
                asked = repo.privacy("--clone-mode")
                self.assertEqual((asked.returncode, asked.stdout.strip()), (0, "maintainer"),
                                 combined(asked))
                pushed = repo.push("other", "main")
                self.assert_refused(pushed, "refused in maintainer mode")
                self.assertEqual(repo.refs_of(repo.other), [])

    def test_contributor_clone_may_push_anywhere(self) -> None:
        repo = self.repo()
        repo.git("config", "--unset", "genops.mode")
        asked = repo.privacy("--clone-mode")
        self.assertEqual((asked.returncode, asked.stdout.strip()), (0, "contributor"),
                         combined(asked))
        pushed = repo.push("other", "main")
        self.assertEqual(pushed.returncode, 0, combined(pushed))
        self.assertEqual(repo.refs_of(repo.other), ["refs/heads/main"])

    def test_the_environment_switch_also_makes_the_hook_a_maintainer(self) -> None:
        repo = self.repo()
        repo.git("config", "--unset", "genops.mode")
        env = dict(repo.env, AGENT_GENOPS_REQUIRE_PRIVATE="1")
        asked = repo.privacy("--clone-mode", env=env)
        self.assertEqual(asked.stdout.strip(), "maintainer", combined(asked))
        pushed = repo.push("other", "main", env=env)
        self.assert_refused(pushed, "refused in maintainer mode")
        self.assertEqual(repo.refs_of(repo.other), [])

    def test_the_hook_refuses_when_the_mode_cannot_be_read(self) -> None:
        for name, stub in (
            ("garbage", "import sys\nprint('banana')\nsys.exit(0)\n"),
            ("failure", "import sys\nsys.exit(2)\n"),
        ):
            with self.subTest(stub=name):
                repo = self.repo()
                repo.git("config", "--unset", "genops.mode")
                (repo.path / "tools" / "privacy_scan.py").write_text(stub)
                pushed = repo.push("other", "main")
                self.assert_refused(pushed, "pre-push:")
                self.assertEqual(repo.refs_of(repo.other), [])

    def test_an_unknown_mode_value_is_refused_not_read_as_contributor(self) -> None:
        for value in ("maintainers", "maintainer,", "maintaner", "true", "1", ""):
            with self.subTest(mode=value):
                repo = self.repo()
                repo.git("config", "genops.mode", value)
                asked = repo.privacy("--clone-mode")
                self.assertEqual(asked.returncode, 2, combined(asked))
                self.assertEqual(asked.stdout.strip(), "", combined(asked))
                self.assertIn("maintainer", asked.stderr)
                self.assertIn("contributor", asked.stderr)
                scanned = repo.privacy("--staged")
                self.assertEqual(scanned.returncode, 2, combined(scanned))
                pushed = repo.push("other", "main")
                self.assert_refused(pushed, "pre-push:")
                self.assertEqual(repo.refs_of(repo.other), [])

    def test_contributor_may_be_set_explicitly_in_any_case(self) -> None:
        repo = self.repo()
        repo.git("config", "genops.mode", "Contributor")
        asked = repo.privacy("--clone-mode")
        self.assertEqual((asked.returncode, asked.stdout.strip()), (0, "contributor"),
                         combined(asked))
        pushed = repo.push("other", "main")
        self.assertEqual(pushed.returncode, 0, combined(pushed))
        self.assertEqual(repo.refs_of(repo.other), ["refs/heads/main"])

    def test_clone_mode_is_a_mode_of_its_own(self) -> None:
        repo = self.repo()
        result = repo.privacy("--clone-mode", "--staged")
        self.assertEqual(result.returncode, 2, combined(result))


class RefNameTests(TemplateCase):
    """Names a push publishes are checked; a deletion publishes none (R7)."""

    def test_deleting_a_remote_ref_with_a_private_name_is_allowed(self) -> None:
        repo = self.repo()
        name = f"refs/heads/{MARKER}"
        repo.git("--git-dir", str(repo.remote), "update-ref", name, repo.head())
        deleted = repo.push("origin", "--delete", MARKER)
        self.assertEqual(deleted.returncode, 0, combined(deleted))
        self.assertIn("pre-push: deleting", deleted.stderr)
        self.assertEqual(repo.refs_of(repo.remote), ["refs/heads/main"])

    def test_pushing_to_a_private_ref_name_is_refused(self) -> None:
        repo = self.repo()
        pushed = repo.push("origin", f"main:refs/heads/{MARKER}")
        self.assert_refused(pushed, "synthetic_private_marker")
        self.assertEqual(repo.refs_of(repo.remote), ["refs/heads/main"])


class PerRefPathTests(TemplateCase):
    """pre-push scans each pushed ref, whatever the scanner's source looks like (R8)."""

    def test_pre_push_takes_the_per_ref_path_with_any_first_scan(self) -> None:
        repo = self.repo()
        log = repo.base / "first-scan.log"
        (repo.path / "tools" / "privacy_scan.py").write_text(
            "import sys\n"
            f"with open({str(log)!r}, 'a') as fh:\n"
            "    fh.write(' '.join(sys.argv[1:]) + '\\n')\n"
            "if sys.argv[1:] == ['--clone-mode']:\n"
            "    print('contributor')\n"
            "sys.exit(0)\n"
        )
        repo.add_file("more.txt", "clean\n")
        repo.unchecked_commit("more")
        pushed = repo.push("origin", "main")
        self.assertEqual(pushed.returncode, 0, combined(pushed))
        calls = log.read_text().splitlines()
        self.assertIn(f"--rev {repo.head()} --ref-name refs/heads/main", calls)
        self.assertNotIn("--history", calls)

    def test_push_refuses_a_token_in_history_with_the_real_scanners(self) -> None:
        repo = self.repo()
        token = registry_token()
        repo.add_file("deploy.txt", f"value: {token}\n")
        repo.unchecked_commit("slip")
        repo.add_file("deploy.txt", "value: removed\n")
        repo.unchecked_commit("remove it again")
        before = repo.remote_tip()
        pushed = repo.push("origin", "main")
        self.assert_refused(pushed, "secret_scan:", "npm-access-token")
        self.assertNotIn(token, combined(pushed))
        self.assertEqual(repo.remote_tip(), before)

    def test_secret_scan_rev_reads_commit_messages(self) -> None:
        repo = self.repo()
        token = registry_token()
        repo.add_file("ok.txt", "clean\n")
        repo.unchecked_commit(f"note the token {token}")
        scanned = repo.run("sh", "tools/secret_scan.sh", "rev", "HEAD")
        self.assert_refused(scanned, "secret_scan:", "npm-access-token")
        self.assertNotIn(token, combined(scanned))
        before = repo.remote_tip()
        pushed = repo.push("origin", "main")
        self.assert_refused(pushed, "secret_scan:")
        self.assertEqual(repo.remote_tip(), before)


class IgnoreFileTests(TemplateCase):
    """A Betterleaks ignore file only the working tree has is an exemption nobody sees (R8b)."""

    def staged_token(self) -> tuple[Repo, str]:
        """A copy with a registry token staged, and the one fingerprint Betterleaks gives it."""
        repo = self.repo()
        repo.add_file("deploy.txt", f"value: {registry_token()}\n")
        prints = repo.fingerprints("git", "--pre-commit", "--staged", ".")
        self.assertEqual(len(prints), 1, prints)
        self.assert_refused(repo.commit("no exemption yet"), "secret_scan:")
        return repo, prints[0] + "\n"

    def test_pre_commit_refuses_an_ignore_file_the_index_does_not_have(self) -> None:
        for name in (".betterleaksignore", ".gitleaksignore"):
            with self.subTest(untracked=name):
                repo, listing = self.staged_token()
                before = repo.head()
                repo.write(name, listing)
                self.assert_refused(repo.commit("untracked exemption"), name)
                self.assertEqual(repo.head(), before)

    def test_pre_commit_accepts_a_staged_ignore_file_but_not_an_unstaged_edit(self) -> None:
        repo, listing = self.staged_token()
        repo.add_file(".betterleaksignore", listing)
        committed = repo.commit("exemption in the commit itself")
        self.assertEqual(committed.returncode, 0, combined(committed))
        before = repo.head()
        repo.write(".betterleaksignore", listing + "other.txt:npm-access-token:1\n")
        repo.add_file("note.txt", "clean\n")
        self.assert_refused(repo.commit("modified, not staged"), ".betterleaksignore")
        self.assertEqual(repo.head(), before)

    def test_pre_commit_hook_alone_refuses_an_ignore_file_the_index_does_not_have(self) -> None:
        """Run directly: a real commit also runs commit-msg, which would mask a missing check."""
        repo, listing = self.staged_token()
        hook = str(repo.path / ".githooks" / "pre-commit")
        repo.write(".betterleaksignore", listing)
        self.assert_refused(repo.run(hook), ".betterleaksignore")
        repo.git("add", ".betterleaksignore")
        allowed = repo.run(hook)
        self.assertEqual(allowed.returncode, 0, combined(allowed))

    def test_commit_msg_refuses_an_ignore_file_the_index_does_not_have(self) -> None:
        repo = self.repo()
        token = registry_token()
        message = repo.base / "msg.txt"
        message.write_text(f"note the token {token}\n")
        prints = repo.fingerprints("stdin", stdin=message.read_text())
        self.assertEqual(len(prints), 1, prints)
        hook = str(repo.path / ".githooks" / "commit-msg")
        self.assert_refused(repo.run(hook, str(message)), "secret_scan:")
        repo.write(".betterleaksignore", prints[0] + "\n")
        self.assert_refused(repo.run(hook, str(message)), ".betterleaksignore")
        repo.git("add", ".betterleaksignore")
        allowed = repo.run(hook, str(message))
        self.assertEqual(allowed.returncode, 0, combined(allowed))

    def test_pre_push_refuses_an_ignore_file_the_candidate_does_not_have(self) -> None:
        repo = self.repo()
        token = registry_token()
        repo.add_file("deploy.txt", f"value: {token}\n")
        repo.unchecked_commit("slip")
        prints = repo.fingerprints("git", "--log-opts=-1", ".")
        self.assertEqual(len(prints), 1, prints)
        before = repo.remote_tip()
        self.assert_refused(repo.push("origin", "main"), "secret_scan:")
        repo.write(".betterleaksignore", prints[0] + "\n")
        self.assert_refused(repo.push("origin", "main"), ".betterleaksignore")
        self.assertEqual(repo.remote_tip(), before)
        repo.git("add", ".betterleaksignore")
        repo.unchecked_commit("exemption in the pushed commit")
        pushed = repo.push("origin", "main")
        self.assertEqual(pushed.returncode, 0, combined(pushed))
        self.assertEqual(repo.remote_tip(), repo.head())

    def test_pre_push_compares_with_the_pushed_commit_not_with_head(self) -> None:
        repo = self.repo()
        base = repo.head()
        repo.add_file("deploy.txt", f"value: {registry_token()}\n")
        repo.unchecked_commit("slip")
        prints = repo.fingerprints("git", "--log-opts=-1", ".")
        self.assertEqual(len(prints), 1, prints)
        repo.add_file(".betterleaksignore", prints[0] + "\n")
        repo.unchecked_commit("exemption in the pushed commit")
        pushed_tip = repo.head()
        repo.git("checkout", "-q", "-b", "side", base)
        self.assertFalse((repo.path / ".betterleaksignore").exists())
        repo.write(".betterleaksignore", prints[0] + "\n")
        pushed = repo.push("origin", "main:main")
        self.assertEqual(pushed.returncode, 0, combined(pushed))
        self.assertEqual(repo.remote_tip(), pushed_tip)

    def test_direct_pre_push_refuses_an_ignore_file_head_does_not_have(self) -> None:
        for name in ("no arguments", "no ref lines"):
            with self.subTest(invocation=name):
                repo = self.repo()
                args = () if name == "no arguments" else ("origin", str(repo.remote))
                repo.add_file("deploy.txt", f"value: {registry_token()}\n")
                repo.unchecked_commit("slip")
                prints = repo.fingerprints("git", "--log-opts=-1", ".")
                self.assertEqual(len(prints), 1, prints)
                hook = str(repo.path / ".githooks" / "pre-push")
                self.assert_refused(repo.run(hook, *args, stdin=""), "secret_scan:")
                repo.write(".betterleaksignore", prints[0] + "\n")
                self.assert_refused(repo.run(hook, *args, stdin=""), ".betterleaksignore")


class MaintainerRulesTests(TemplateCase):
    """In maintainer mode a missing or empty private rules file stops every hook."""

    def test_commit_and_push_are_refused_without_usable_private_rules(self) -> None:
        for state in ("empty", "missing"):
            with self.subTest(rules=state):
                repo = self.repo()
                repo.add_file("more.txt", "clean\n")
                repo.unchecked_commit("unpushed")
                before = repo.head()
                remote_before = repo.remote_tip()
                if state == "empty":
                    repo.rules.write_text(json.dumps({"version": 1, "rules": []}))
                else:
                    repo.rules.unlink()
                repo.add_file("note.txt", "clean\n")
                committed = repo.commit("clean change")
                self.assert_refused(committed, "maintainer")
                self.assertEqual(repo.head(), before)
                pushed = repo.push("origin", "main")
                self.assert_refused(pushed, "maintainer")
                self.assertEqual(repo.remote_tip(), remote_before)


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
