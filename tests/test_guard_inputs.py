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
import os
import struct
import subprocess
import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_guard_objects import (  # noqa: E402
    IDENTITY,
    MARKER,
    Repo,
    combined,
    random_text,
    registry_token,
)

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


class CommitHeaderTests(unittest.TestCase):
    """Headers of a commit object other than author and committer are read by both scanners.

    git writes a mergetag header itself when it merges a signed annotated tag: the whole tag
    object (tagger and message) indented by one space. Any other extra header is kept as well.
    """

    def setUp(self) -> None:
        self.repo = Repo(self)
        self.token = registry_token()

    def write_commit(self, headers: str) -> str:
        """A commit on main whose object carries ``headers`` after the committer line."""
        tree = self.repo.git("rev-parse", "HEAD^{tree}")
        parent = self.repo.git("rev-parse", "HEAD")
        ident = f"tester <{IDENTITY}> 1700000000 +0000"
        raw = (
            f"tree {tree}\nparent {parent}\nauthor {ident}\ncommitter {ident}\n"
            f"{headers}\nclean subject\n"
        )
        oid = self.repo.git("hash-object", "-t", "commit", "-w", "--stdin", stdin=raw)
        self.repo.git("update-ref", "refs/heads/main", oid)
        return oid

    def mergetag(self, tagger: str, *message: str) -> str:
        parent = self.repo.git("rev-parse", "HEAD")
        lines = ["object " + parent, "type commit", "tag v1", "tagger " + tagger, "", *message]
        return "mergetag " + "\n ".join(lines) + "\n"

    def privacy_refuses(self, rule: str) -> None:
        for args in (("--rev", "HEAD"), ("--range", "HEAD~1..HEAD"), ("--history",)):
            with self.subTest(args=args):
                scanned = self.repo.privacy(*args)
                self.assertEqual(scanned.returncode, 1, combined(scanned))
                self.assertIn(rule, combined(scanned))

    def test_mergetag_message_is_read_by_both_scanners(self) -> None:
        ident = f"tester <{IDENTITY}> 1700000000 +0000"
        self.write_commit(self.mergetag(ident, f"note {MARKER}", f"key = {self.token}"))
        self.privacy_refuses("synthetic_private_marker")
        for args in (("rev", "HEAD"), ("range", "HEAD~1..HEAD"), ("history",)):
            with self.subTest(args=args):
                refused_by_secret_scan(self, self.repo.secret(*args), self.token)
        pushed = self.repo.push("main")
        self.assertNotEqual(pushed.returncode, 0, combined(pushed))
        self.assertNotEqual(
            self.repo.git("rev-parse", "HEAD"),
            self.repo.git("--git-dir", str(self.repo.remote), "rev-parse", "main"),
        )

    def test_mergetag_tagger_is_checked_like_any_identity(self) -> None:
        # example.com passes the text rules; only the identity list refuses it.
        self.write_commit(self.mergetag("someone <someone@example.com> 1700000000 +0000", "ok"))
        self.privacy_refuses("email")

    def test_any_other_extra_header_is_read(self) -> None:
        self.write_commit(f"x-note {MARKER}\n")
        self.privacy_refuses("synthetic_private_marker")
        self.write_commit(f"x-note key = {self.token}\n")
        for args in (("rev", "HEAD"), ("history",)):
            with self.subTest(args=args):
                refused_by_secret_scan(self, self.repo.secret(*args), self.token)

    def test_a_clean_mergetag_passes(self) -> None:
        ident = f"tester <{IDENTITY}> 1700000000 +0000"
        self.write_commit(self.mergetag(ident, "release one"))
        for args in (("--rev", "HEAD"), ("--history",)):
            with self.subTest(args=args):
                scanned = self.repo.privacy(*args)
                self.assertEqual(scanned.returncode, 0, combined(scanned))
        for args in (("rev", "HEAD"), ("history",)):
            with self.subTest(args=args):
                scanned = self.repo.secret(*args)
                self.assertEqual(scanned.returncode, 0, combined(scanned))


class MessageEncodingTests(unittest.TestCase):
    """A commit message is read in the encoding git stores it in, or refused.

    git keeps a message in i18n.commitEncoding and names that encoding in the commit object's
    encoding header; git log and the hosting site show it converted to UTF-8. The commit-msg hook
    runs before there is a commit object, so the scanner reads i18n.commitEncoding itself.
    Content that cannot be decoded cannot be scanned, so it is a finding, never clean.
    """

    def setUp(self) -> None:
        self.repo = Repo(self)
        # A private rule with non-ASCII text, built at run time.
        self.marker = "\u5408\u6210" + "\u6807\u8bb0" + "zq"
        rules = self.repo.home / ".config" / "agent-genops" / "private_rules.json"
        document = json.loads(rules.read_text())
        document["rules"].append(
            {"id": "synthetic_cjk_marker", "pattern": self.marker, "why": "synthetic non-ASCII marker"}
        )
        rules.write_text(json.dumps(document))
        self.gbk = self.write_message("gbk", f"note: {self.marker} here\n")
        with self.assertRaises(UnicodeDecodeError):
            self.gbk.read_bytes().decode("utf-8")

    def write_message(self, encoding: str, text: str) -> Path:
        path = self.repo.base / f"msg-{random_text(6)}.txt"
        path.write_bytes(text.encode(encoding))
        return path

    def unchecked_commit_file(self, message: Path, *config: str) -> None:
        self.repo.add_file(f"f-{random_text(6)}.txt", "data\n")
        options = [item for pair in config for item in ("-c", pair)]
        self.repo.git("-c", f"core.hooksPath={os.devnull}", *options, "commit", "-q", "-F", str(message))

    def write_commit(self, body: bytes, header: bytes = b"") -> None:
        """A commit on main whose object is written byte for byte (no git conversion)."""
        tree = self.repo.git("rev-parse", "HEAD^{tree}")
        parent = self.repo.git("rev-parse", "HEAD")
        ident = f"tester <{IDENTITY}> 1700000000 +0000"
        raw = (f"tree {tree}\nparent {parent}\nauthor {ident}\ncommitter {ident}\n").encode()
        raw += header + b"\n" + body
        obj = self.repo.base / f"obj-{random_text(6)}"
        obj.write_bytes(raw)
        oid = self.repo.git("hash-object", "-t", "commit", "-w", str(obj))
        self.repo.git("update-ref", "refs/heads/main", oid)

    def privacy_refuses(self, rule: str) -> None:
        for args in (("--rev", "HEAD"), ("--range", "HEAD~1..HEAD"), ("--history",)):
            with self.subTest(args=args):
                scanned = self.repo.privacy(*args)
                self.assertEqual(scanned.returncode, 1, combined(scanned))
                self.assertIn(rule, combined(scanned))
        pushed = self.repo.push("main")
        self.assertNotEqual(pushed.returncode, 0, combined(pushed))
        self.assertNotEqual(
            self.repo.git("rev-parse", "HEAD"),
            self.repo.git("--git-dir", str(self.repo.remote), "rev-parse", "main"),
        )

    def test_message_file_is_read_in_the_commit_encoding(self) -> None:
        self.repo.git("config", "i18n.commitEncoding", "GBK")
        scanned = self.repo.privacy("--message", str(self.gbk))
        self.assertEqual(scanned.returncode, 1, combined(scanned))
        self.assertIn("synthetic_cjk_marker", combined(scanned))
        before = self.repo.git("rev-parse", "HEAD")
        self.repo.add_file("x.txt", "x\n")
        committed = self.repo.run("git", "commit", "-q", "-F", str(self.gbk))
        self.assertNotEqual(committed.returncode, 0, combined(committed))
        self.assertIn("synthetic_cjk_marker", combined(committed))
        self.assertEqual(self.repo.git("rev-parse", "HEAD"), before)

    def test_encoding_given_on_the_command_line_reaches_the_hook(self) -> None:
        before = self.repo.git("rev-parse", "HEAD")
        self.repo.add_file("x.txt", "x\n")
        committed = self.repo.run(
            "git", "-c", "i18n.commitEncoding=GBK", "commit", "-q", "-F", str(self.gbk)
        )
        self.assertNotEqual(committed.returncode, 0, combined(committed))
        self.assertIn("synthetic_cjk_marker", combined(committed))
        self.assertEqual(self.repo.git("rev-parse", "HEAD"), before)

    def test_message_file_that_does_not_decode_is_refused(self) -> None:
        clean = self.write_message("gbk", "\u63d0\u4ea4\u8bf4\u660e\n")
        for config in ((), ("UTF-8",), ("no-such-encoding-zq",)):
            with self.subTest(config=config):
                if config:
                    self.repo.git("config", "i18n.commitEncoding", config[0])
                scanned = self.repo.privacy("--message", str(clean))
                self.assertEqual(scanned.returncode, 1, combined(scanned))
                self.assertIn("undecodable", combined(scanned))

    def test_message_file_in_its_encoding_without_a_marker_is_clean(self) -> None:
        self.repo.git("config", "i18n.commitEncoding", "GBK")
        clean = self.write_message("gbk", "\u63d0\u4ea4\u8bf4\u660e\n")
        scanned = self.repo.privacy("--message", str(clean))
        self.assertEqual(scanned.returncode, 0, combined(scanned))
        utf8 = self.write_message("utf-8", "\u63d0\u4ea4\u8bf4\u660e\n")
        self.repo.run("git", "config", "--unset", "i18n.commitEncoding")
        scanned = self.repo.privacy("--message", str(utf8))
        self.assertEqual(scanned.returncode, 0, combined(scanned))

    def test_commit_is_read_in_its_encoding_header(self) -> None:
        self.unchecked_commit_file(self.gbk, "i18n.commitEncoding=GBK")
        self.assertEqual(self.repo.git("log", "-1", "--format=%e"), "GBK")
        self.privacy_refuses("synthetic_cjk_marker")

    def test_commit_that_does_not_decode_is_refused(self) -> None:
        body = "\u63d0\u4ea4\u8bf4\u660e\n".encode("gbk")
        for header in (b"", b"encoding UTF-8\n", b"encoding no-such-encoding-zq\n"):
            with self.subTest(header=header):
                self.write_commit(body, header)
                self.privacy_refuses("undecodable")

    def test_commit_in_its_encoding_without_a_marker_is_clean(self) -> None:
        clean = self.write_message("gbk", "\u63d0\u4ea4\u8bf4\u660e\n")
        self.unchecked_commit_file(clean, "i18n.commitEncoding=GBK")
        for args in (("--rev", "HEAD"), ("--history",)):
            with self.subTest(args=args):
                scanned = self.repo.privacy(*args)
                self.assertEqual(scanned.returncode, 0, combined(scanned))
        pushed = self.repo.push("main")
        self.assertEqual(pushed.returncode, 0, combined(pushed))

    def test_secret_scan_reads_the_raw_bytes_of_a_message_in_another_encoding(self) -> None:
        token = registry_token()
        message = self.write_message("gbk", f"\u63d0\u4ea4 key = {token}\n")
        refused_by_secret_scan(self, self.repo.secret("message", str(message)), token)
        self.unchecked_commit_file(message, "i18n.commitEncoding=GBK")
        self.assertEqual(self.repo.git("log", "-1", "--format=%e"), "GBK")
        for args in (("rev", "HEAD"), ("range", "HEAD~1..HEAD"), ("history",)):
            with self.subTest(args=args):
                refused_by_secret_scan(self, self.repo.secret(*args), token)


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def png_image(pixels: bytes | None = None) -> bytes:
    """A 1x1 grey PNG; ``pixels`` replaces the IDAT payload (it is never inflated by the scan)."""
    idat = pixels if pixels is not None else zlib.compress(b"\x00\x80")
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
        + png_chunk(b"IDAT", idat)
        + png_chunk(b"IEND", b"")
    )


# The head of each allowed image format, written from the format specifications (PNG, JFIF,
# GIF89a, RIFF/WEBP, ICO), followed by a few bytes of body. Built here, not recorded from files.
IMAGE_HEADS = {
    ".png": png_image(),
    ".jpg": b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9",
    ".jpeg": b"\xff\xd8\xff\xdb\x00\x43\x00\xff\xd9",
    ".gif": b"GIF89a\x01\x00\x01\x00\x00\x00\x00;",
    ".webp": b"RIFF\x1a\x00\x00\x00WEBPVP8L\x0d\x00\x00\x00\x2f\x00\x00\x00\x10",
    ".ico": b"\x00\x00\x01\x00\x01\x00\x01\x01\x00\x00\x01\x00\x20\x00",
}


def lines_naming(output: str, name: str, rule: str) -> list[str]:
    return [line for line in output.splitlines() if name in line and rule in line]


class ImageAndBinaryTests(unittest.TestCase):
    """Bytes behind an image suffix or a NUL byte are read by both scanners.

    Betterleaks skips a file git treats as binary (a NUL byte) and, by its default path
    allowlist, any file named like an image, in its git and dir modes alike. The privacy
    scanner admits binary content only under an image suffix and read PNG pixel chunks not at
    all. So an image suffix has to match the format's header, and both scanners read the raw
    bytes of what they cannot parse as text.
    """

    def setUp(self) -> None:
        self.repo = Repo(self)
        public = json.loads((Path(__file__).resolve().parent.parent / "tools" / "privacy_rules.json").read_text())
        self.suffixes = public["allowed_binary_suffixes"]
        self.assertEqual(sorted(self.suffixes), sorted(IMAGE_HEADS))

    def add_bytes(self, name: str, data: bytes) -> None:
        (self.repo.path / name).write_bytes(data)
        self.repo.git("add", name)

    def test_an_image_suffix_needs_the_header_of_its_format(self) -> None:
        for suffix in self.suffixes:
            with self.subTest(suffix=suffix):
                name = f"right{suffix}"
                self.add_bytes(name, IMAGE_HEADS[suffix])
                scanned = self.repo.privacy("--staged")
                self.assertEqual(scanned.returncode, 0, combined(scanned))
                for label, data in (("text", b"plain text\n"), ("other", IMAGE_HEADS[".gif" if suffix != ".gif" else ".png"])):
                    wrong = f"wrong-{label}{suffix}"
                    self.add_bytes(wrong, data)
                    scanned = self.repo.privacy("--staged")
                    self.assertEqual(scanned.returncode, 1, combined(scanned))
                    self.assertTrue(lines_naming(combined(scanned), wrong, "image_header"), combined(scanned))
                    self.repo.git("rm", "-q", "--cached", wrong)
        before = self.repo.git("rev-parse", "HEAD")
        self.add_bytes("fake.jpg", b"not a picture\n")
        committed = self.repo.run("git", "commit", "-q", "-m", "picture")
        self.assertNotEqual(committed.returncode, 0, combined(committed))
        self.assertIn("image_header", combined(committed))
        self.assertEqual(self.repo.git("rev-parse", "HEAD"), before)

    def test_private_rules_read_the_raw_bytes_in_every_mode(self) -> None:
        samples = {
            "data.bin": b"\x00\x01 " + MARKER.encode() + b" \x00",
            "broken.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\x05IDAT " + MARKER.encode(),
            "notes.txt": b"caf\xe9 " + MARKER.encode() + b"\n",
        }
        for name, data in samples.items():
            self.add_bytes(name, data)
        def check(*args: str) -> None:
            scanned = self.repo.privacy(*args)
            self.assertEqual(scanned.returncode, 1, combined(scanned))
            for name in samples:
                self.assertTrue(
                    lines_naming(combined(scanned), name, "synthetic_private_marker"), (name, combined(scanned))
                )
        check("--staged")
        check(*samples)
        self.repo.unchecked_commit("samples")
        for args in (("--rev", "HEAD"), ("--range", "HEAD~1..HEAD"), ("--history",), ("--tracked",)):
            with self.subTest(args=args):
                check(*args)
        for name, data in samples.items():
            (self.repo.path / name).write_bytes(data + b"\x00")
        check("--unstaged")
        pushed = self.repo.push("main")
        self.assertNotEqual(pushed.returncode, 0, combined(pushed))

    def secret_refused_everywhere(self, name: str, data: bytes, token: str) -> None:
        self.add_bytes(name, data)
        refused_by_secret_scan(self, self.repo.secret("staged"), token)
        refused_by_secret_scan(self, self.repo.secret("files", name), token)
        before = self.repo.git("rev-parse", "HEAD")
        committed = self.repo.run("git", "commit", "-q", "-m", "picture")
        self.assertNotEqual(committed.returncode, 0, combined(committed))
        self.assertEqual(self.repo.git("rev-parse", "HEAD"), before)
        self.repo.unchecked_commit("picture")
        for args in (("rev", "HEAD"), ("range", "HEAD~1..HEAD"), ("history",)):
            with self.subTest(args=args):
                refused_by_secret_scan(self, self.repo.secret(*args), token)
        (self.repo.path / name).write_bytes(data.replace(token.encode(), registry_token().encode()))
        refused_by_secret_scan(self, self.repo.secret("unstaged"), token)
        pushed = self.repo.push("main")
        refused_by_secret_scan(self, pushed, token)
        self.assertEqual(
            before, self.repo.git("--git-dir", str(self.repo.remote), "rev-parse", "main")
        )

    def test_a_token_in_an_image_with_a_nul_byte_is_found_in_every_mode(self) -> None:
        token = registry_token()
        data = IMAGE_HEADS[".jpg"][:4] + b"\x00\nkey = " + token.encode() + b"\n"
        self.secret_refused_everywhere("pic.jpg", data, token)

    def test_a_token_in_an_image_without_a_nul_byte_is_found_in_every_mode(self) -> None:
        token = registry_token()
        data = b"GIF89a\nkey = " + token.encode() + b"\n"
        self.secret_refused_everywhere("pic.gif", data, token)

    def test_real_images_stay_clean(self) -> None:
        for suffix in self.suffixes:
            self.add_bytes(f"img{suffix}", IMAGE_HEADS[suffix])
        self.repo.unchecked_commit("images")
        for args in (("--staged",), ("--rev", "HEAD"), ("--history",)):
            with self.subTest(args=args):
                scanned = self.repo.privacy(*args)
                self.assertEqual(scanned.returncode, 0, combined(scanned))
        for args in (("rev", "HEAD"), ("range", "HEAD~1..HEAD"), ("history",)):
            with self.subTest(args=args):
                scanned = self.repo.secret(*args)
                self.assertEqual(scanned.returncode, 0, combined(scanned))
        pushed = self.repo.push("main")
        self.assertEqual(pushed.returncode, 0, combined(pushed))


def png_with_chunks(*chunks: tuple[bytes, bytes], pixels: bytes | None = None) -> bytes:
    """A 1x1 grey PNG with extra chunks (kind, payload) between the header and the pixels."""
    idat = pixels if pixels is not None else zlib.compress(b"\x00\x80")
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
        + b"".join(png_chunk(kind, payload) for kind, payload in chunks)
        + png_chunk(b"IDAT", idat)
        + png_chunk(b"IEND", b"")
    )


class PngChunkTests(unittest.TestCase):
    """The privacy rules read a PNG's text and other metadata chunks, not its pixel chunk."""

    def setUp(self) -> None:
        self.repo = Repo(self)
        self.marker = MARKER.encode()

    def staged_scan(self, name: str, data: bytes) -> "subprocess.CompletedProcess[str]":
        (self.repo.path / name).write_bytes(data)
        self.repo.git("add", name)
        return self.repo.privacy("--staged")

    def test_a_private_marker_in_a_text_chunk_is_found(self) -> None:
        text = {
            "text.png": (b"tEXt", b"Title\x00 " + self.marker),
            "ztxt.png": (b"zTXt", b"Title\x00\x00" + zlib.compress(self.marker)),
            "itxt.png": (b"iTXt", b"Title\x00\x00\x00\x00\x00" + self.marker),
            "other.png": (b"prVt", self.marker),
        }
        for name, chunk in text.items():
            with self.subTest(name=name):
                scanned = self.staged_scan(name, png_with_chunks(chunk))
                self.assertEqual(scanned.returncode, 1, combined(scanned))
                self.assertTrue(
                    lines_naming(combined(scanned), name, "synthetic_private_marker"), combined(scanned)
                )
                self.repo.git("rm", "-q", "--cached", name)

    def test_a_clean_text_chunk_passes(self) -> None:
        scanned = self.staged_scan("clean.png", png_with_chunks((b"tEXt", b"Title\x00 a plain note")))
        self.assertEqual(scanned.returncode, 0, combined(scanned))

    def test_bytes_in_the_pixel_chunk_are_not_matched_against_the_rules(self) -> None:
        # Compressed pixels can match a short rule by chance, so the pixel chunk is left out; a
        # marker there is not found (the documented limit), while the same marker one chunk
        # earlier is.
        scanned = self.staged_scan("pixels.png", png_with_chunks(pixels=b"\x00 " + self.marker + b" \x00"))
        self.assertEqual(scanned.returncode, 0, combined(scanned))


# One path from each family the prefilter of Betterleaks 1.10.1's default config drops by name
# (`betterleaks config show`): image, font, document, lock file, Go checksum, dependency folder.
DEFAULT_PREFILTER_SAMPLES = (
    "logo.svg",
    "fonts/body.woff2",
    "guide.pdf",
    "yarn.lock",
    "go.sum",
    "node_modules/pkg/index.js",
)


class DefaultPathPrefilterTests(unittest.TestCase):
    """Betterleaks' default config drops whole files by path before any rule runs: images and
    fonts, office documents, lock files, dependency and vendor folders. The wrapper replaces that
    prefilter, so a token in such a file is found with its path by Betterleaks' own git and dir
    scans, in every mode and through the hooks."""

    def test_a_token_in_a_file_the_default_prefilter_names_is_found_in_every_mode(self) -> None:
        for name in DEFAULT_PREFILTER_SAMPLES:
            with self.subTest(name=name):
                repo = Repo(self)
                token = registry_token()
                repo.add_file(name, f"key = {token}\n")
                for args in (("staged",), ("files", name)):
                    scanned = repo.secret(*args)
                    refused_by_secret_scan(self, scanned, token)
                    self.assertIn(name, combined(scanned))
                before = repo.git("rev-parse", "HEAD")
                committed = repo.run("git", "commit", "-q", "-m", "add a file")
                refused_by_secret_scan(self, committed, token)
                self.assertEqual(repo.git("rev-parse", "HEAD"), before)
                repo.unchecked_commit("add a file")
                for args in (("rev", "HEAD"), ("range", "HEAD~1..HEAD"), ("history",)):
                    scanned = repo.secret(*args)
                    refused_by_secret_scan(self, scanned, token)
                    self.assertIn(name, combined(scanned))
                pushed = repo.push("main")
                refused_by_secret_scan(self, pushed, token)
                self.assertEqual(repo.git("--git-dir", str(repo.remote), "rev-parse", "main"), before)
                (repo.path / name).write_text(f"key = {registry_token()}\n")
                scanned = repo.secret("unstaged")
                refused_by_secret_scan(self, scanned, token)
                self.assertIn(name, combined(scanned))


# Heads that Betterleaks' dir mode sniffs as an executable, an archive or a document and then
# skips (found with 1.10.1 by trying each one on a file with a token behind it), written here
# from the format specifications. None holds a NUL byte, so git calls the file text.
SNIFFED_HEADS = {
    "pdf": b"%PDF-1.4",
    "elf": b"\x7fELF text",
    "zip": b"PK\x03\x04",
    "gzip": b"\x1f\x8b\x08",
    "exe": b"MZ",
    "7z": b"7z\xbc\xaf\x27\x1c",
}


class SniffedHeadTests(unittest.TestCase):
    """The files mode (what ./check changed runs on unstaged and untracked files) reads a text
    file whose first bytes look like an executable, an archive or a document, which the dir mode
    of Betterleaks skips by that head."""

    def test_a_token_behind_a_sniffed_head_is_found_by_the_files_mode(self) -> None:
        for label, head in SNIFFED_HEADS.items():
            with self.subTest(head=label):
                repo = Repo(self)
                token = registry_token()
                name = f"{label}.txt"
                (repo.path / name).write_bytes(head + b"\nkey = " + token.encode() + b"\n")
                scanned = repo.secret("files", name)
                refused_by_secret_scan(self, scanned, token)
                self.assertIn(name, combined(scanned))

    def test_a_clean_file_with_a_sniffed_head_passes_and_a_finding_is_reported_once(self) -> None:
        repo = Repo(self)
        (repo.path / "clean.txt").write_bytes(SNIFFED_HEADS["pdf"] + b"\nnothing here\n")
        scanned = repo.secret("files", "clean.txt")
        self.assertEqual(scanned.returncode, 0, combined(scanned))
        token = registry_token()
        (repo.path / "plain.txt").write_bytes(b"key = " + token.encode() + b"\n")
        scanned = repo.secret("files", "plain.txt")
        refused_by_secret_scan(self, scanned, token)
        self.assertEqual(combined(scanned).count("npm-access-token"), 1, combined(scanned))

    def test_the_same_head_with_a_nul_byte_is_still_found(self) -> None:
        repo = Repo(self)
        token = registry_token()
        (repo.path / "elf.bin").write_bytes(SNIFFED_HEADS["elf"] + b"\x00\nkey = " + token.encode() + b"\n")
        refused_by_secret_scan(self, repo.secret("files", "elf.bin"), token)


if __name__ == "__main__":
    unittest.main()
