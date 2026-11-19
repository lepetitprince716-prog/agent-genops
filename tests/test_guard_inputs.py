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


if __name__ == "__main__":
    unittest.main()
