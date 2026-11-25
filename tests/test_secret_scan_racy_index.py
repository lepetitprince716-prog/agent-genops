"""The unstaged secret scan also scans every changed file as the files mode does, so a change git's
stat check hides from Betterleaks is still scanned.

Betterleaks 1.10.1 runs its pre-commit diff against a copy of .git/index in a private git
directory, and the copy's mtime is the moment it was copied. git compares stat data in whole
seconds (Apple Git, and Linux builds without USE_NSEC) and re-reads a file whose stat data looks
unchanged only while the index file is no newer than the entry ("racy git"). When a file is
staged and then rewritten at the same size within one second, and Betterleaks copies the index in
a later second, its diff is empty and it passes the file without reading it. The repository's own
index is still racy, so git there lists the file, and the files mode scans it with its own path.

The racy tests build that state on purpose: write, git add and the rewrite fall into one second
(checked against the index entry and the index file, retried otherwise) and the scan starts in the
next second. Where git compares nanoseconds the state cannot be built this way and those tests
pass with or without the second pass.

Betterleaks must be installed (brew install betterleaks); missing, these tests fail.
"""

from __future__ import annotations

import base64
import os
import re
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_guard_objects import Repo, combined, registry_token  # noqa: E402

FINDING = re.compile(r"^\s*(\S+) (\S+):(\d+) ", re.MULTILINE)
KUBERNETES_SECRET = (
    b"apiVersion: v1\nkind: Secret\nmetadata:\n  name: db\ndata:\n  pass: c3VwZXJzZWNyZXQxMjM=\n"
)
_DASHES = "-" * 5
_KEY_WORDS = "PRI" + "VATE " + "KE" + "Y"
KEY_BEGIN = f"{_DASHES}BEG" + f"IN {_KEY_WORDS}{_DASHES}"
KEY_END = f"{_DASHES}EN" + f"D {_KEY_WORDS}{_DASHES}"


def private_key() -> bytes:
    body = base64.encodebytes(os.urandom(600)).decode()
    return f"{KEY_BEGIN}\n{body}{KEY_END}\n".encode()


class RacyIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Repo(self)
        self.index = Path(self.repo.git("rev-parse", "--absolute-git-dir")) / "index"

    def index_entry(self, name: str) -> dict[str, int]:
        debug = self.repo.git("ls-files", "--debug", "--", name)
        entry = {key: int(sec) for key, sec in re.findall(r"(ctime|mtime): (\d+):\d+", debug)}
        entry["ino"] = int(re.search(r"ino: (\d+)", debug).group(1))
        entry["size"] = int(re.search(r"size: (\d+)", debug).group(1))
        return entry

    def racy_rewrite(self, name: str, staged: bytes, rewritten: bytes) -> None:
        self.assertEqual(len(staged), len(rewritten))
        path = self.repo.path / name
        for _attempt in range(10):
            # A little past the start of a second: file times can trail the wall clock.
            time.sleep(1 - time.time() % 1 + 0.02)
            path.write_bytes(staged)
            self.repo.git("add", "--", name)
            path.write_bytes(rewritten)
            entry = self.index_entry(name)
            st = path.stat()
            second = entry["mtime"]
            if (
                entry["ctime"] == second
                and st.st_mtime_ns // 10**9 == second
                and st.st_ctime_ns // 10**9 == second
                and self.index.stat().st_mtime_ns // 10**9 == second
                and entry["size"] == st.st_size
                and entry["ino"] == st.st_ino & 0xFFFFFFFF
            ):
                while time.time() < second + 1.05:
                    time.sleep(0.01)
                return
        self.fail("could not stage and rewrite the file within one second in 10 tries")

    def assert_refused_for(self, result, name: str, token: str) -> None:
        output = combined(result)
        self.assertNotIn(result.returncode, (0, 2), output)
        self.assertNotIn(token, output)
        self.assertIn(f" {name}:", output)

    def test_a_text_file_rewritten_in_the_second_it_was_staged_is_scanned(self) -> None:
        token = registry_token()
        rewritten = f"key = {token}\n".encode()
        self.racy_rewrite("app.txt", b"x" * len(rewritten), rewritten)
        self.assert_refused_for(self.repo.secret("unstaged"), "app.txt", token)

    def test_an_image_without_a_nul_byte_rewritten_in_the_second_it_was_staged_is_scanned(self) -> None:
        # The case the guard test suite hit on CI: a GIF head, no NUL byte, valid UTF-8.
        token = registry_token()
        rewritten = b"GIF89a\nkey = " + token.encode() + b"\n"
        staged = b"GIF89a\nkey = " + registry_token().encode() + b"\n"
        self.racy_rewrite("pic.gif", staged, rewritten)
        self.assert_refused_for(self.repo.secret("unstaged"), "pic.gif", token)

    def test_an_inline_allow_comment_in_a_file_only_the_second_pass_reads(self) -> None:
        token = registry_token()
        rewritten = f"key = {token} # betterleaks:allow\n".encode()
        self.racy_rewrite("app.txt", b"x" * len(rewritten), rewritten)
        allowed = self.repo.secret("unstaged")
        self.assertEqual(allowed.returncode, 0, combined(allowed))
        refused = self.repo.secret("unstaged", extra_env={"SECRET_SCAN_IGNORE_ALLOW": "1"})
        self.assert_refused_for(refused, "app.txt", token)

    def test_a_rule_that_needs_the_file_name_fires_on_a_racy_rewrite(self) -> None:
        # kubernetes-secret-yaml applies to *.yaml paths only; a pass over stdin has no path.
        rewritten = KUBERNETES_SECRET
        self.racy_rewrite("db.yaml", b"x" * (len(rewritten) - 1) + b"\n", rewritten)
        scanned = self.repo.secret("unstaged")
        self.assertNotIn(scanned.returncode, (0, 2), combined(scanned))
        self.assertIn("kubernetes-secret-yaml db.yaml:", combined(scanned))

    def test_an_allow_comment_in_one_file_does_not_cover_a_key_in_another(self) -> None:
        # Scanned as one stream, a key match starting at the begin marker in fixture.txt would end
        # in key.pem and fall under the allow comment on the first line.
        key = private_key()
        self.repo.add_file("fixture.txt", "old\n")
        self.repo.unchecked_commit("fixture")
        (self.repo.path / "fixture.txt").write_text(f"fixture: {KEY_BEGIN} # betterleaks:allow\n")
        self.racy_rewrite("key.pem", b"x" * (len(key) - 1) + b"\n", key)
        scanned = self.repo.secret("unstaged")
        self.assertNotIn(scanned.returncode, (0, 2), combined(scanned))
        self.assertIn("private-key key.pem:", combined(scanned))

    def test_relative_git_variables_from_a_subdirectory_still_work(self) -> None:
        (self.repo.path / "docs").mkdir()
        self.repo.add_file("docs/guide.txt", "guide\n")
        self.repo.unchecked_commit("docs")
        env = dict(self.repo.env, GIT_DIR="../.git", GIT_WORK_TREE="..")
        script = str(self.repo.path / "tools" / "secret_scan.sh")
        (self.repo.path / "docs" / "guide.txt").write_text("guide, longer now\n")
        clean = self.repo.run("sh", script, "unstaged", env=env, cwd=self.repo.path / "docs")
        self.assertEqual(clean.returncode, 0, combined(clean))
        token = registry_token()
        (self.repo.path / "docs" / "guide.txt").write_text(f"key = {token}\n")
        refused = self.repo.run("sh", script, "unstaged", env=env, cwd=self.repo.path / "docs")
        self.assert_refused_for(refused, "docs/guide.txt", token)

    def test_a_finding_in_the_last_file_of_a_full_batch_is_reported(self) -> None:
        # 201 changed files make two batches; the token sits in the 200th, the last of the
        # first batch, so a dropped file at a batch edge or a later clean batch would hide it.
        # Its rewrite is racy, so the diff layer does not report it first.
        token = registry_token()
        for number in range(201):
            self.repo.add_file(f"f{number:03}.txt", "old\n")
        self.repo.unchecked_commit("many files")
        for number in range(201):
            if number != 199:
                (self.repo.path / f"f{number:03}.txt").write_text(f"new {number}\n")
        rewritten = f"key = {token}\n".encode()
        self.racy_rewrite("f199.txt", b"x" * len(rewritten), rewritten)
        self.assert_refused_for(self.repo.secret("unstaged"), "f199.txt", token)

    def test_the_unstaged_mode_removes_its_scratch_directories(self) -> None:
        scratch = self.repo.base / "scratch"
        scratch.mkdir()
        (self.repo.path / "README.md").write_text("# Synthetic, changed\n")
        scanned = self.repo.secret("unstaged", extra_env={"TMPDIR": str(scratch)})
        self.assertEqual(scanned.returncode, 0, combined(scanned))
        self.assertEqual(sorted(entry.name for entry in scratch.iterdir()), [])

    def test_the_staged_mode_still_scans_only_what_the_commit_changes(self) -> None:
        token = registry_token()
        self.repo.add_file("app.txt", f"key = {token}\nnote = one\n")
        self.repo.unchecked_commit("app")
        self.repo.add_file("app.txt", f"key = {token}\nnote = two\n")
        scanned = self.repo.secret("staged")
        self.assertEqual(scanned.returncode, 0, combined(scanned))

    def test_a_committed_token_in_a_file_changed_elsewhere_is_reported(self) -> None:
        # Reading the whole file also reads lines the change did not touch; a fingerprint for
        # the file's path, rule and line accepts such a finding.
        token = registry_token()
        self.repo.add_file("app.txt", f"key = {token}\nnote = one\n")
        self.repo.unchecked_commit("app")
        (self.repo.path / "app.txt").write_text(f"key = {token}\nnote = two, now longer\n")
        refused = self.repo.secret("unstaged")
        self.assert_refused_for(refused, "app.txt", token)
        rule, path, line = FINDING.search(combined(refused)).groups()
        self.assertEqual((path, line), ("app.txt", "1"))
        (self.repo.path / ".betterleaksignore").write_text(f"{path}:{rule}:{line}\n")
        accepted = self.repo.secret("unstaged")
        self.assertEqual(accepted.returncode, 0, combined(accepted))


if __name__ == "__main__":
    unittest.main()
