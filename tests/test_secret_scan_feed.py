"""How tools/secret_scan.sh hands input to the programs it runs.

The secondary pass writes object ids to `git cat-file --batch` and packed content to
`betterleaks stdin`. Written through a pipe while the child writes its answer to another pipe,
the two block on each other once the kernel shrinks new pipes to PIPE_BUF (512 bytes) and poll
still reports a full pipe writable, which macOS does under pipe-memory pressure: the scan never
returns and the pre-push hook times out. Input read from a file cannot block that way.
"""

from __future__ import annotations

import fcntl
import os
import select
import shutil
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_guard_objects import Repo, combined  # noqa: E402

PIPE_BUF = 512
SHIM = """#!/bin/sh
case " $* " in
  {pattern}) ;;
  *) exec {real} "$@" ;;
esac
if [ -p /dev/stdin ]; then how=pipe; else how=file; fi
printf '%s %s\\n' "$how" "{name} $*" >>"$FEED_LOG"
exec {real} "$@"
"""


def new_pipe_state() -> tuple[int, bool]:
    """How many bytes a new pipe takes before it is full, and whether poll then calls it writable."""
    read_end, write_end = os.pipe()
    try:
        fcntl.fcntl(write_end, fcntl.F_SETFL, fcntl.fcntl(write_end, fcntl.F_GETFL) | os.O_NONBLOCK)
        size = 0
        try:
            while size < 1 << 17:
                size += os.write(write_end, b"x")
        except BlockingIOError:
            pass
        poller = select.poll()
        poller.register(write_end, select.POLLOUT)
        return size, bool(poller.poll(0))
    finally:
        os.close(read_end)
        os.close(write_end)


def add_commits(repo: Repo, count: int) -> None:
    for index in range(count):
        repo.add_file(f"notes/n{index}.txt", f"note {index}\n" * 40)
        repo.unchecked_commit(f"note {index}")


class FeedTests(unittest.TestCase):
    def test_children_read_their_input_from_a_file_not_a_pipe(self) -> None:
        repo = Repo(self)
        shims = repo.base / "shims"
        shims.mkdir()
        for name, pattern in (("git", '*" cat-file --batch "*'), ("betterleaks", '" stdin "*')):
            real = shutil.which(name)
            self.assertIsNotNone(real, name)
            shim = shims / name
            shim.write_text(SHIM.format(pattern=pattern, real=real, name=name))
            shim.chmod(0o755)
        log = repo.base / "feed.log"
        add_commits(repo, 3)
        result = repo.secret(
            "range", "HEAD~3..HEAD",
            extra_env={"PATH": f"{shims}{os.pathsep}{repo.env['PATH']}", "FEED_LOG": str(log)},
        )
        self.assertEqual(result.returncode, 0, combined(result))
        lines = log.read_text().splitlines()
        self.assertTrue(any("git " in line and "cat-file --batch" in line for line in lines), lines)
        self.assertTrue(any("betterleaks stdin" in line for line in lines), lines)
        self.assertEqual([line for line in lines if line.startswith("pipe ")], [])

    def test_range_returns_when_new_pipes_are_tiny_and_poll_misreports(self) -> None:
        size, writable_when_full = new_pipe_state()
        if size > PIPE_BUF or not writable_when_full:
            self.skipTest(
                f"new pipes here take {size} bytes and poll "
                f"{'reports' if writable_when_full else 'does not report'} a full pipe writable; "
                f"the deadlock needs a pipe of at most {PIPE_BUF} bytes together with that false "
                "report, which only pipe-memory exhaustion of the whole system produces"
            )
        repo = Repo(self)
        add_commits(repo, 40)
        process = subprocess.Popen(
            ["sh", "tools/secret_scan.sh", "range", "HEAD~40..HEAD"],
            cwd=repo.path,
            env=repo.env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        started = time.monotonic()
        try:
            out, err = process.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            self.fail(f"secret_scan.sh range did not return within {time.monotonic() - started:.0f} s")
        self.assertEqual(process.returncode, 0, (out + err).decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
