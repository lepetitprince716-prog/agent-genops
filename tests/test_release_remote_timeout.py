"""A remote that never answers stops ``./check release`` within the remote timeout.

``git ls-remote`` is the release check's one call to the remote. Its ssh transport here is a local
script that only sleeps, so nothing connects anywhere; the remote timeout is shortened for the
test through its environment variable, which can shorten the timeout but never lengthen it.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import release_check  # noqa: E402
from test_release_check import SyntheticRepo  # noqa: E402
from test_release_trusted import clean_candidate, manifests, need_betterleaks  # noqa: E402

SHORT = "2"


class SilentRemoteTests(unittest.TestCase):
    def test_a_remote_that_never_answers_is_refused_within_the_timeout(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        cand = clean_candidate(repo)
        fake = repo.base / "silent-ssh.sh"
        fake.write_text("#!/bin/sh\nexec sleep 600\n")
        fake.chmod(0o755)
        url = "ssh://git.example.invalid/x.git"
        repo.git("remote", "set-url", "origin", url)
        repo.git("config", "genops.allowedPushUrl", url)
        env = dict(repo.env, GIT_SSH_COMMAND=str(fake))
        env[release_check.REMOTE_TIMEOUT_ENV] = SHORT
        cmd = [sys.executable, "-B", str(repo.work / "check"), "release", "--to", "origin", "--ref",
               "refs/heads/main", "--commit", cand, "--manifest-dir", str(repo.manifest_dir)]
        proc = subprocess.Popen(cmd, cwd=repo.work, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
        started = time.monotonic()
        try:
            out, err = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            self.fail("./check release was still waiting on the remote after 30 s")
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(proc.returncode, 2, out + err)
        self.assertIn("did not answer", out + err)
        self.assertEqual(manifests(repo), [])


class RemoteTimeoutValueTests(unittest.TestCase):
    def timeout_with(self, value: str | None) -> float:
        with mock.patch.dict(os.environ, {release_check.REMOTE_TIMEOUT_ENV: value or ""}):
            if value is None:
                del os.environ[release_check.REMOTE_TIMEOUT_ENV]
            return release_check.remote_timeout()

    def test_the_default_is_the_constant(self) -> None:
        self.assertEqual(self.timeout_with(None), release_check.REMOTE_TIMEOUT_S)
        self.assertEqual(release_check.REMOTE_TIMEOUT_S, 30)

    def test_the_variable_shortens_but_never_lengthens(self) -> None:
        self.assertEqual(self.timeout_with("2.5"), 2.5)
        self.assertEqual(self.timeout_with("999"), release_check.REMOTE_TIMEOUT_S)

    def test_a_value_that_is_not_a_positive_number_is_refused(self) -> None:
        for value in ("", "0", "-1", "nan", "inf", "soon"):
            with self.subTest(value=value):
                with self.assertRaises(release_check.CheckError):
                    self.timeout_with(value)


if __name__ == "__main__":
    unittest.main()
