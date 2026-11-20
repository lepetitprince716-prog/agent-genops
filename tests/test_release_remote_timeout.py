"""A remote that never answers stops ``./check release`` within the remote timeout.

``git ls-remote`` is the release check's one call to the remote. Its ssh transport here is a local
script, so nothing connects anywhere; the remote timeout is shortened for the test through its
environment variable, which can shorten the timeout but never lengthen it.

git first runs an unknown ssh command once with ``-G`` to learn which ssh it is, with every stdio
stream on /dev/null, and only then connects. Each transport here answers that probe and hangs on
the connection, so the test reaches the stage where git's pipes are open.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
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

# Shell lines that answer git's ``ssh -G`` variant probe, so the script below them is the connection.
ANSWER_PROBE = 'case " $* " in *" -G "*) exit 0 ;; esac\n'


def run_against_silent_remote(testcase: unittest.TestCase, transport: str) -> tuple[SyntheticRepo, subprocess.Popen[str], str, str]:
    """``./check release`` for a clean candidate, with ``transport`` as the remote's ssh command.

    Returns once the check has ended (or failed the test after 30 s)."""
    need_betterleaks(testcase)
    repo = SyntheticRepo(testcase, maintainer=True)
    cand = clean_candidate(repo)
    fake = repo.base / "silent-ssh.sh"
    fake.write_text(transport)
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
        testcase.fail("./check release was still waiting on the remote after 30 s")
    testcase.assertLess(time.monotonic() - started, 20)
    return repo, proc, out, err


def is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class SilentRemoteTests(unittest.TestCase):
    def test_a_remote_that_never_answers_is_refused_within_the_timeout(self) -> None:
        repo, proc, out, err = run_against_silent_remote(self, "#!/bin/sh\n" + ANSWER_PROBE + "exec sleep 600\n")
        self.assertEqual(proc.returncode, 2, out + err)
        self.assertIn("did not answer", out + err)
        self.assertEqual(manifests(repo), [])

    def test_the_transport_and_what_it_started_do_not_outlive_the_check(self) -> None:
        """The ssh command git starts, and a process that one starts in turn, are gone once the
        check has given up: stopping git alone would leave both running."""
        probe = Path(tempfile.mkdtemp(prefix="genops-transport-"))
        self.addCleanup(shutil.rmtree, probe, True)
        script = (
            "#!/bin/sh\n"
            + ANSWER_PROBE
            + f"echo $$ > {probe}/transport.pid\n"
            + "sleep 600 > /dev/null 2>&1 &\n"
            + f"echo $! > {probe}/grandchild.pid\n"
            + "wait\n"
        )
        repo, proc, out, err = run_against_silent_remote(self, script)
        pids = []
        for name in ("transport.pid", "grandchild.pid"):
            pids.append(int((probe / name).read_text().strip()))
        for pid in pids:
            self.addCleanup(self.kill_quietly, pid)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and any(is_running(pid) for pid in pids):
            time.sleep(0.1)
        self.assertEqual([pid for pid in pids if is_running(pid)], [], out + err)
        self.assertEqual(proc.returncode, 2, out + err)

    @staticmethod
    def kill_quietly(pid: int) -> None:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


# A transport that answers the probe, then starts a helper that leaves git's process group (setsid)
# while it keeps the stderr pipe it inherited from git, and never answers. Stopping the group does
# not reach the helper, so the pipe stays open until the helper ends.
ESCAPING_TRANSPORT = """#!{python} -I
import os, sys, time
if "-G" in sys.argv[1:]:
    sys.exit(0)
if os.fork() == 0:
    os.setsid()
    with open({pidfile!r}, "w") as fh:
        fh.write(str(os.getpid()))
    time.sleep(60)
    os._exit(0)
time.sleep(600)
"""


class EscapedTransportChildTests(unittest.TestCase):
    """A process that left the group and still holds git's pipes does not keep the check waiting."""

    def escaping_transport(self) -> Path:
        probe = Path(tempfile.mkdtemp(prefix="genops-escape-"))
        self.addCleanup(shutil.rmtree, probe, True)
        pidfile = probe / "helper.pid"
        self.addCleanup(self.stop_helper, pidfile)
        fake = probe / "escaping-ssh.py"
        fake.write_text(ESCAPING_TRANSPORT.format(python=sys.executable, pidfile=str(pidfile)))
        fake.chmod(0o755)
        return fake

    @staticmethod
    def stop_helper(pidfile: Path) -> None:
        try:
            pid = int(pidfile.read_text().strip())
        except (OSError, ValueError):
            return
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def test_the_remote_call_is_refused_soon_after_the_timeout(self) -> None:
        home = Path(tempfile.mkdtemp(prefix="genops-escape-home-"))
        self.addCleanup(shutil.rmtree, home, True)
        work = home / "work"
        env = {
            "HOME": str(home),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_SSH_COMMAND": str(self.escaping_transport()),
            release_check.REMOTE_TIMEOUT_ENV: "1",
        }
        with mock.patch.dict(os.environ, env):
            subprocess.run(["git", "init", "-q", str(work)], check=True)
            subprocess.run(
                ["git", "-C", str(work), "remote", "add", "origin", "ssh://git.example.invalid/x.git"], check=True
            )
            started = time.monotonic()
            with self.assertRaises(release_check.CheckError) as caught:
                release_check.run_git_remote(["ls-remote", "--refs", "origin"], work)
            elapsed = time.monotonic() - started
        self.assertIn("did not answer", str(caught.exception))
        self.assertLess(elapsed, 1 + release_check.REMOTE_DRAIN_S + 2)

    def test_the_release_check_is_refused_and_writes_no_manifest(self) -> None:
        fake = self.escaping_transport()
        repo, proc, out, err = run_against_silent_remote(self, f'#!/bin/sh\nexec {fake} "$@"\n')
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
