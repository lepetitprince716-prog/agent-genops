"""Inputs that used to change what the two scanners read without anyone seeing it: Betterleaks
configuration left in the shell environment, git attributes committed to the repository, extra
headers inside a commit object, commit messages stored in another encoding, and text hidden in
files with an image suffix.

Each test builds a throwaway repository with the real hooks and tools (the Repo helper of
tests/test_guard_objects.py) and drives the real entry points: the scanners' command lines,
git commit and git push through the hooks, against a local bare remote. Fake tokens and private
markers are built at run time.

Betterleaks must be installed (brew install betterleaks); missing, these tests fail, they do not
skip: a skipped guard test reads as green while the guard is not running.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_guard_objects import MARKER, Repo, combined, registry_token  # noqa: E402

CONFIG_VARS = ("BETTERLEAKS_CONFIG", "GITLEAKS_CONFIG")
CONFIG_TOML_VARS = ("BETTERLEAKS_CONFIG_TOML", "GITLEAKS_CONFIG_TOML")


def refused_by_secret_scan(testcase: unittest.TestCase, result, token: str) -> None:
    testcase.assertNotEqual(result.returncode, 0, combined(result))
    testcase.assertNotEqual(result.returncode, 2, combined(result))
    testcase.assertIn("secret_scan:", combined(result))
    testcase.assertNotIn(token, combined(result))


class EnvironmentConfigTests(unittest.TestCase):
    """A Betterleaks config named in the environment does not replace the wrapper's own."""

    def setUp(self) -> None:
        self.repo = Repo(self)
        self.token = registry_token()
        # What another project could leave in the shell: an allowlist that covers the token.
        self.hostile = '[extend]\nuseDefault = true\n[allowlist]\nregexes = ["np.?m_"]\n'
        self.config = self.repo.base / "other-project.toml"
        self.config.write_text(self.hostile)

    def hostile_env(self, name: str) -> dict[str, str]:
        if name in CONFIG_VARS:
            return {name: str(self.config)}
        return {name: self.hostile}

    def test_each_config_variable_is_ignored_by_the_wrapper(self) -> None:
        self.repo.add_file("cfg.txt", f"key = {self.token}\n")
        for name in CONFIG_VARS + CONFIG_TOML_VARS:
            with self.subTest(variable=name):
                scanned = self.repo.secret("staged", extra_env=self.hostile_env(name))
                refused_by_secret_scan(self, scanned, self.token)

    def test_a_config_committed_in_the_repository_is_not_loaded(self) -> None:
        # Betterleaks 1.10.1 reads these only with --unsafe-auto-load-config, which the wrapper
        # never passes. Unlike the variables above, a commit can bring them in.
        for name in (".betterleaks.toml", ".gitleaks.toml"):
            self.repo.add_file(name, self.hostile)
        self.repo.add_file("cfg.txt", f"key = {self.token}\n")
        refused_by_secret_scan(self, self.repo.secret("staged"), self.token)
        self.repo.unchecked_commit("cfg")
        for args in (("rev", "HEAD"), ("range", "HEAD~1..HEAD"), ("history",)):
            with self.subTest(args=args):
                refused_by_secret_scan(self, self.repo.secret(*args), self.token)

    def test_commit_and_push_refuse_with_a_config_in_the_environment(self) -> None:
        env = dict(self.repo.env)
        for name in CONFIG_VARS + CONFIG_TOML_VARS:
            env.update(self.hostile_env(name))
        self.repo.add_file("cfg.txt", f"key = {self.token}\n")
        committed = self.repo.run("git", "commit", "-q", "-m", "cfg", env=env)
        refused_by_secret_scan(self, committed, self.token)
        self.repo.unchecked_commit("cfg")
        pushed = self.repo.run("git", "push", "origin", "main", env=env)
        refused_by_secret_scan(self, pushed, self.token)
        self.assertNotEqual(
            self.repo.git("rev-parse", "HEAD"),
            self.repo.git("--git-dir", str(self.repo.remote), "rev-parse", "main"),
        )


class AttributeTests(unittest.TestCase):
    """A committed .gitattributes that marks files -diff does not hide them from either scan."""

    def setUp(self) -> None:
        self.repo = Repo(self)
        self.repo.add_file(".gitattributes", "*.cfg -diff\n")
        self.repo.unchecked_commit("attributes")
        self.token = registry_token()

    def test_staged_content_marked_binary_is_scanned(self) -> None:
        self.repo.add_file("app.cfg", f"key = {self.token}\n")
        refused_by_secret_scan(self, self.repo.secret("staged"), self.token)
        before = self.repo.git("rev-parse", "HEAD")
        committed = self.repo.run("git", "commit", "-q", "-m", "config")
        refused_by_secret_scan(self, committed, self.token)
        self.assertEqual(self.repo.git("rev-parse", "HEAD"), before)

    def test_unstaged_content_marked_binary_is_scanned(self) -> None:
        self.repo.add_file("app.cfg", "key = placeholder\n")
        self.repo.unchecked_commit("config")
        (self.repo.path / "app.cfg").write_text(f"key = {self.token}\n")
        refused_by_secret_scan(self, self.repo.secret("unstaged"), self.token)

    def test_staged_and_unstaged_content_with_nul_bytes_is_scanned(self) -> None:
        # Git judges these binary by content (a NUL byte). Betterleaks skips or unpacks a file or
        # stream whose head sniffs as an executable (ELF) or a document (PDF), so the content has
        # to reach it as text.
        heads = {
            "elf": b"\x7fELF\x02\x01\x01\x00\x00\n",
            "pdf": b"%PDF-1.4\n%\xe2\xe3\x00\n",
        }
        for label, head in heads.items():
            with self.subTest(head=label):
                name = f"{label}.dat"
                token = registry_token()
                (self.repo.path / name).write_bytes(head + b"placeholder\n")
                self.repo.git("add", name)
                self.repo.unchecked_commit(label)
                (self.repo.path / name).write_bytes(head + f"key = {token}\n".encode())
                refused_by_secret_scan(self, self.repo.secret("unstaged"), token)
                self.repo.git("add", name)
                refused_by_secret_scan(self, self.repo.secret("staged"), token)
                self.repo.unchecked_commit(f"{label} with a token")

    def test_ignore_files_still_apply_to_content_marked_binary(self) -> None:
        self.repo.add_file("app.cfg", f"key = {self.token}\n")
        report = self.repo.base / "stdin.json"
        self.repo.run(
            "betterleaks", "stdin", "--redact", "--no-banner", "--log-level", "error",
            "-f", "json", "-r", str(report), stdin=f"key = {self.token}\n",
        )
        rules = {item["RuleID"] for item in json.loads(report.read_text())}
        self.assertTrue(rules)
        # Read through stdin, a finding's fingerprint is ":<rule>:<line>"; cover any line.
        prints = [f":{rule}:{line}" for rule in rules for line in range(1, 50)]
        self.repo.add_file(".betterleaksignore", "\n".join(prints) + "\n")
        allowed = self.repo.secret("staged")
        self.assertEqual(allowed.returncode, 0, combined(allowed))
        empty = self.repo.base / "empty.ignore"
        empty.write_text("")
        explicit = {"SECRET_SCAN_IGNORE_PATH": str(empty)}
        refused_by_secret_scan(self, self.repo.secret("staged", extra_env=explicit), self.token)
        inline = f"key = {self.token}  # betterleaks:allow\n"
        self.repo.add_file(".betterleaksignore", "")
        self.repo.add_file("app.cfg", inline)
        allowed = self.repo.secret("staged")
        self.assertEqual(allowed.returncode, 0, combined(allowed))
        refused_by_secret_scan(
            self, self.repo.secret("staged", extra_env={"SECRET_SCAN_IGNORE_ALLOW": "1"}), self.token
        )

    def test_unstaged_symlink_marked_binary_is_read_as_its_target_text(self) -> None:
        # Betterleaks' git mode already reads the symlink side of this type change as text; the
        # second pass reads the link text too (not the file it points at), so either one alone
        # keeps this green.
        self.repo.add_file("app.cfg", "key = placeholder\n")
        self.repo.unchecked_commit("config")
        link = self.repo.base / "link"
        link.symlink_to(f"key = {self.token}")
        link.replace(self.repo.path / "app.cfg")
        refused_by_secret_scan(self, self.repo.secret("unstaged"), self.token)

    def test_committed_content_marked_binary_is_scanned_in_every_git_mode(self) -> None:
        self.repo.add_file("app.cfg", f"key = {self.token}\n")
        self.repo.unchecked_commit("config")
        for args in (("rev", "HEAD"), ("range", "HEAD~1..HEAD"), ("history",)):
            with self.subTest(args=args):
                refused_by_secret_scan(self, self.repo.secret(*args), self.token)

    def test_the_privacy_scan_reads_content_marked_binary_in_every_mode(self) -> None:
        self.repo.add_file("app.cfg", f"host {MARKER}\n")
        staged = self.repo.privacy("--staged")
        self.assertEqual(staged.returncode, 1, combined(staged))
        self.repo.unchecked_commit("config")
        for args in (("--rev", "HEAD"), ("--range", "HEAD~1..HEAD"), ("--history",)):
            with self.subTest(args=args):
                scanned = self.repo.privacy(*args)
                self.assertEqual(scanned.returncode, 1, combined(scanned))
                self.assertIn("synthetic_private_marker", combined(scanned))
        (self.repo.path / "app.cfg").write_text(f"host {MARKER} again\n")
        unstaged = self.repo.privacy("--unstaged")
        self.assertEqual(unstaged.returncode, 1, combined(unstaged))

    def test_diff_drivers_in_the_clone_hide_nothing(self) -> None:
        # A textconv that prints nothing, an external diff command and binary = true, set in the
        # clone's config and named by a committed attribute, next to a global external diff.
        quiet = self.repo.base / "quiet.sh"
        quiet.write_text("#!/bin/sh\nexit 0\n")
        quiet.chmod(0o755)
        self.repo.add_file(".gitattributes", "*.cfg -diff\n*.ini diff=quiet\n*.conf diff=opaque\n")
        self.repo.unchecked_commit("drivers")
        for key, value in (
            ("diff.quiet.textconv", str(quiet)),
            ("diff.quiet.command", str(quiet)),
            ("diff.opaque.binary", "true"),
            ("diff.external", str(quiet)),
        ):
            self.repo.git("config", key, value)
        for name in ("app.ini", "app.conf"):
            with self.subTest(name=name):
                self.repo.add_file(name, f"key = {self.token}\nhost {MARKER}\n")
                refused_by_secret_scan(self, self.repo.secret("staged"), self.token)
                staged = self.repo.privacy("--staged")
                self.assertEqual(staged.returncode, 1, combined(staged))
                self.repo.unchecked_commit(name)
                for args in (("rev", "HEAD"), ("range", "HEAD~1..HEAD")):
                    refused_by_secret_scan(self, self.repo.secret(*args), self.token)
                for args in (("--rev", "HEAD"), ("--range", "HEAD~1..HEAD"), ("--history",)):
                    scanned = self.repo.privacy(*args)
                    self.assertEqual(scanned.returncode, 1, combined(scanned))
                (self.repo.path / name).write_text(f"key = {registry_token()}\nhost {MARKER} 2\n")
                refused_by_secret_scan(self, self.repo.secret("unstaged"), self.token)
                unstaged = self.repo.privacy("--unstaged")
                self.assertEqual(unstaged.returncode, 1, combined(unstaged))
                self.repo.git("checkout", "--", name)
                # Out of the index; the untracked copy left behind is read by no mode used here.
                self.repo.git("rm", "-q", "--cached", name)
                self.repo.unchecked_commit(f"drop {name}")


if __name__ == "__main__":
    unittest.main()
