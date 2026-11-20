"""Stable per-file and per-object fingerprints, plus binary-adjacent and PNG text-chunk scans.

Every test drives the real tools/secret_scan.sh wrapper and real git commands in a temporary
repository with runtime-generated fake tokens (no secret-looking literal lives in the repo).
"""

from __future__ import annotations

import os
import struct
import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import release_check  # noqa: E402
from test_guard_inputs import png_with_chunks, refused_by_secret_scan  # noqa: E402
from test_guard_objects import MARKER, Repo, combined, registry_token  # noqa: E402


def finding_lines(output: str) -> list[str]:
    return [line.strip() for line in output.splitlines() if line.startswith("  ")]


class BinaryStableFingerprintTests(unittest.TestCase):
    """Binary content gets stable per-file (and commit-scoped in history) fingerprints."""

    def add_bytes(self, repo: Repo, name: str, data: bytes) -> None:
        target = repo.path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        repo.git("add", name)

    def test_binary_finding_carries_path_local_line_and_commit(self) -> None:
        repo = Repo(self)
        token = registry_token()
        data = b"GIF89a\x00\x00\nfixture " + token.encode() + b"\n"
        self.add_bytes(repo, "fixture.gif", data)
        for args in (("staged",), ("files", "fixture.gif")):
            with self.subTest(args=args):
                res = repo.secret(*args)
                refused_by_secret_scan(self, res, token)
                lines = finding_lines(combined(res))
                self.assertTrue(any("npm-access-token fixture.gif:2" in line for line in lines), lines)
                self.assertFalse(any(" :2" in line for line in lines), lines)
        repo.unchecked_commit("add fixture")
        commit = repo.git("rev-parse", "HEAD")
        for args in (("rev", "HEAD"), ("range", "HEAD~1..HEAD"), ("history",)):
            with self.subTest(args=args):
                res = repo.secret(*args)
                refused_by_secret_scan(self, res, token)
                lines = finding_lines(combined(res))
                self.assertTrue(
                    any(f"npm-access-token fixture.gif:2 {commit}" in line for line in lines), lines
                )
        (repo.path / "fixture.gif").write_bytes(b"GIF89a\x00\x00\nupdated " + registry_token().encode() + b"\n")
        res = repo.secret("unstaged")
        refused_by_secret_scan(self, res, token)
        lines = finding_lines(combined(res))
        self.assertTrue(any("npm-access-token fixture.gif:2" in line for line in lines), lines)

    def test_binary_path_fingerprint_exempts_only_that_file_and_survives_new_files(self) -> None:
        repo = Repo(self)
        fixture_tok = registry_token()
        self.add_bytes(repo, "fixture.gif", b"GIF89a\x00\x00\nfixture " + fixture_tok.encode() + b"\n")
        repo.add_file(".betterleaksignore", "fixture.gif:npm-access-token:2\n")
        self.assertEqual(repo.secret("staged").returncode, 0)
        committed = repo.run("git", "commit", "-q", "-m", "fixture with stable fingerprint")
        self.assertEqual(committed.returncode, 0, combined(committed))
        pushed = repo.push("main")
        self.assertEqual(pushed.returncode, 0, combined(pushed))

        # Adding another clean binary file does not shift fixture.gif's fingerprint.
        self.add_bytes(repo, "logo.gif", b"GIF89a\x00\x00\nclean logo\n")
        committed2 = repo.run("git", "commit", "-q", "-m", "add clean logo")
        self.assertEqual(committed2.returncode, 0, combined(committed2))
        pushed2 = repo.push("main")
        self.assertEqual(pushed2.returncode, 0, combined(pushed2))

        # A real token on the same line of a different binary file is still refused everywhere.
        other_tok = registry_token()
        self.add_bytes(repo, "other.gif", b"GIF89a\x00\x01\nreal " + other_tok.encode() + b"\n")
        for args in (("staged",), ("files", "other.gif")):
            with self.subTest(args=args):
                res = repo.secret(*args)
                refused_by_secret_scan(self, res, other_tok)
                self.assertIn("other.gif:2", combined(res))
        repo.unchecked_commit("add other binary")
        for args in (("range", "HEAD~1..HEAD"), ("rev", "HEAD"), ("history",)):
            with self.subTest(args=args):
                res = repo.secret(*args)
                refused_by_secret_scan(self, res, other_tok)
                self.assertIn("other.gif:2", combined(res))
        pushed3 = repo.push("main")
        refused_by_secret_scan(self, pushed3, other_tok)

    def test_binary_commit_scoped_fingerprint_exempts_only_that_commit(self) -> None:
        repo = Repo(self)
        tok1 = registry_token()
        self.add_bytes(repo, "fixture.gif", b"GIF89a\x00\x00\nfirst " + tok1.encode() + b"\n")
        repo.unchecked_commit("first fixture")
        c1 = repo.git("rev-parse", "HEAD")
        repo.add_file(".betterleaksignore", f"{c1}:fixture.gif:npm-access-token:2\n")
        repo.unchecked_commit("allow c1 only")
        for args in (("rev", "HEAD"), ("history",)):
            with self.subTest(phase="c1-only", args=args):
                res = repo.secret(*args)
                self.assertEqual(res.returncode, 0, combined(res))
        tok2 = registry_token()
        self.add_bytes(repo, "fixture.gif", b"GIF89a\x00\x00\nsecond " + tok2.encode() + b"\n")
        repo.unchecked_commit("second fixture")
        c2 = repo.git("rev-parse", "HEAD")
        for args in (("rev", "HEAD"), ("range", "HEAD~1..HEAD"), ("history",)):
            with self.subTest(phase="c2-refused", args=args):
                res = repo.secret(*args)
                refused_by_secret_scan(self, res, tok2)
                self.assertIn(f"fixture.gif:2 {c2}", combined(res))

    def test_binary_explicit_ignore_path_overrides_working_tree(self) -> None:
        repo = Repo(self)
        tok = registry_token()
        self.add_bytes(repo, "fixture.gif", b"GIF89a\x00\x00\nfixture " + tok.encode() + b"\n")
        repo.add_file(".betterleaksignore", "fixture.gif:npm-access-token:2\n")
        empty = repo.base / "empty.ignore"
        empty.write_text("")
        trusted = repo.base / "trusted.ignore"
        trusted.write_text("fixture.gif:npm-access-token:2\n")
        refused_by_secret_scan(self, repo.secret("staged", extra_env={"SECRET_SCAN_IGNORE_PATH": str(empty)}), tok)
        self.assertEqual(
            repo.secret("staged", extra_env={"SECRET_SCAN_IGNORE_PATH": str(trusted)}).returncode, 0
        )
        repo.unchecked_commit("commit fixture")
        for args in (("rev", "HEAD"), ("history",)):
            refused_by_secret_scan(self, repo.secret(*args, extra_env={"SECRET_SCAN_IGNORE_PATH": str(empty)}), tok)
            self.assertEqual(
                repo.secret(*args, extra_env={"SECRET_SCAN_IGNORE_PATH": str(trusted)}).returncode, 0
            )

    def test_binary_private_path_is_redacted_in_output(self) -> None:
        repo = Repo(self)
        tok = registry_token()
        name = f"asset-{MARKER}.gif"
        self.add_bytes(repo, name, b"GIF89a\x00\x00\nkey = " + tok.encode() + b"\n")
        res = repo.secret("staged")
        refused_by_secret_scan(self, res, tok)
        out = combined(res)
        self.assertNotIn(MARKER, out)
        self.assertIn("<redacted-path#", out)

    def test_files_mode_normalizes_dot_slash_and_subdir_paths(self) -> None:
        repo = Repo(self)
        tok = registry_token()
        self.add_bytes(repo, "sub/fixture.gif", b"GIF89a\x00\x00\nfixture " + tok.encode() + b"\n")
        self.add_bytes(repo, "sub/elf.bin", b"\x7fELF\x02\x01\x01\x00\x00\nkey = " + registry_token().encode() + b"\n")
        repo.add_file(
            ".betterleaksignore",
            "sub/fixture.gif:npm-access-token:2\nsub/elf.bin:npm-access-token:2\n",
        )
        self.assertEqual(repo.secret("files", "./sub/fixture.gif").returncode, 0)
        self.assertEqual(repo.secret("files", "./sub/elf.bin").returncode, 0)
        for name in ("fixture.gif", "elf.bin"):
            from_sub = repo.run(
                "sh", str(repo.path / "tools" / "secret_scan.sh"), "files", name,
                cwd=repo.path / "sub",
            )
            self.assertEqual(from_sub.returncode, 0, combined(from_sub))


class StdinObjectFingerprintTests(unittest.TestCase):
    """Commit objects, tag objects, direct refs, symlink targets, and message mode."""

    def test_commit_object_uses_commit_scoped_fingerprint_only(self) -> None:
        repo = Repo(self)
        tok1 = registry_token()
        repo.add_file("a.txt", "clean\n")
        repo.unchecked_commit(f"note {tok1}")
        c1 = repo.git("rev-parse", "HEAD")

        res = repo.secret("rev", "HEAD")
        refused_by_secret_scan(self, res, tok1)
        lines = finding_lines(combined(res))
        self.assertEqual(len(lines), 1, lines)
        # Format: "npm-access-token .git/commit:<line> <c1>"
        parts = lines[0].split()
        self.assertEqual(parts[0], "npm-access-token", lines)
        self.assertTrue(parts[1].startswith(".git/commit:"), lines)
        self.assertEqual(parts[2], c1, lines)
        line_no = parts[1].split(":")[1]

        # Bare :rule:line and unscoped .git/commit:rule:line must NOT exempt it.
        (repo.path / ".betterleaksignore").write_text(
            f":npm-access-token:{line_no}\n.git/commit:npm-access-token:{line_no}\n"
        )
        for args in (("rev", c1), ("history",), ("range", f"{c1}~1..{c1}")):
            with self.subTest(unscoped=args):
                refused_by_secret_scan(self, repo.secret(*args), tok1)

        # Commit-scoped fingerprint DOES exempt c1.
        (repo.path / ".betterleaksignore").write_text(f"{c1}:.git/commit:npm-access-token:{line_no}\n")
        for args in (("rev", c1), ("history",), ("range", f"{c1}~1..{c1}")):
            with self.subTest(scoped=args):
                self.assertEqual(repo.secret(*args).returncode, 0)

        # Explicit empty ignore overrides working-tree ignore.
        empty = repo.base / "empty.ignore"
        empty.write_text("")
        refused_by_secret_scan(
            self, repo.secret("rev", c1, extra_env={"SECRET_SCAN_IGNORE_PATH": str(empty)}), tok1
        )

        # Does NOT exempt a second commit c2 with a token on the same line.
        tok2 = registry_token()
        repo.add_file("b.txt", "clean\n")
        repo.unchecked_commit(f"note {tok2}")
        c2 = repo.git("rev-parse", "HEAD")
        refused_by_secret_scan(self, repo.secret("rev", c2), tok2)
        self.assertIn(c2, combined(repo.secret("rev", c2)))

    def test_tag_object_uses_tag_scoped_fingerprint_only(self) -> None:
        repo = Repo(self)
        tok1 = registry_token()
        msg1 = repo.base / "tag1.txt"
        msg1.write_text(f"release {tok1}\n")
        repo.git("tag", "-a", "v1", "-F", str(msg1))
        t1 = repo.git("rev-parse", "v1")

        res = repo.secret("rev", "v1")
        refused_by_secret_scan(self, res, tok1)
        lines = finding_lines(combined(res))
        self.assertEqual(len(lines), 1, lines)
        parts = lines[0].split()
        self.assertEqual(parts[0], "npm-access-token", lines)
        self.assertTrue(parts[1].startswith(".git/tag:"), lines)
        self.assertEqual(parts[2], t1, lines)
        line_no = parts[1].split(":")[1]

        # Bare and unscoped entries do NOT exempt it.
        (repo.path / ".betterleaksignore").write_text(
            f":npm-access-token:{line_no}\n.git/tag:npm-access-token:{line_no}\n"
        )
        refused_by_secret_scan(self, repo.secret("rev", "v1"), tok1)
        refused_by_secret_scan(self, repo.secret("history"), tok1)

        # Tag-OID-scoped entry DOES exempt v1, and NOT a second tag v2.
        (repo.path / ".betterleaksignore").write_text(f"{t1}:.git/tag:npm-access-token:{line_no}\n")
        self.assertEqual(repo.secret("rev", "v1").returncode, 0)
        self.assertEqual(repo.secret("history").returncode, 0)

        tok2 = registry_token()
        msg2 = repo.base / "tag2.txt"
        msg2.write_text(f"release {tok2}\n")
        repo.git("tag", "-a", "v2", "-F", str(msg2))
        refused_by_secret_scan(self, repo.secret("rev", "v2"), tok2)

    def test_direct_blob_and_tree_refs_use_stable_fingerprints(self) -> None:
        repo = Repo(self)
        tok_b = registry_token()
        blob = repo.hash_blob(f"key = {tok_b}\n")
        repo.git("tag", "blobtag", blob)
        res_b = repo.secret("rev", blob)
        refused_by_secret_scan(self, res_b, tok_b)
        self.assertIn(f"npm-access-token .git/blob:1 {blob}", combined(res_b))

        (repo.path / ".betterleaksignore").write_text(".git/blob:npm-access-token:1\n:npm-access-token:1\n")
        refused_by_secret_scan(self, repo.secret("rev", blob), tok_b)
        (repo.path / ".betterleaksignore").write_text(f"{blob}:.git/blob:npm-access-token:1\n")
        self.assertEqual(repo.secret("rev", blob).returncode, 0)

        tok_t = registry_token()
        tree = repo.make_tree(repo.hash_blob(f"other = {tok_t}\n"), name="direct.txt")
        repo.git("update-ref", "refs/custom/treeref", tree)
        res_t = repo.secret("rev", tree)
        refused_by_secret_scan(self, res_t, tok_t)
        self.assertIn(f"npm-access-token direct.txt:1 {tree}", combined(res_t))
        (repo.path / ".betterleaksignore").write_text(f"{tree}:direct.txt:npm-access-token:1\n")
        self.assertEqual(repo.secret("rev", tree).returncode, 0)

    def test_symlink_target_in_files_mode_uses_path_fingerprint_not_bare(self) -> None:
        repo = Repo(self)
        tok = registry_token()
        (repo.path / "link.txt").symlink_to(f"key-{tok}")
        res = repo.secret("files", "link.txt")
        refused_by_secret_scan(self, res, tok)
        self.assertIn("npm-access-token link.txt:1", combined(res))

        # Bare fingerprint must NOT exempt link.txt.
        (repo.path / ".betterleaksignore").write_text(":npm-access-token:1\n")
        refused_by_secret_scan(self, repo.secret("files", "link.txt"), tok)

        # Path fingerprint DOES exempt link.txt, and NOT other-link.txt.
        (repo.path / ".betterleaksignore").write_text("link.txt:npm-access-token:1\n")
        self.assertEqual(repo.secret("files", "link.txt").returncode, 0)
        tok2 = registry_token()
        (repo.path / "other-link.txt").symlink_to(f"key-{tok2}")
        refused_by_secret_scan(self, repo.secret("files", "other-link.txt"), tok2)

        # Explicit empty ignore overrides working-tree ignore.
        empty = repo.base / "empty.ignore"
        empty.write_text("")
        refused_by_secret_scan(
            self, repo.secret("files", "link.txt", extra_env={"SECRET_SCAN_IGNORE_PATH": str(empty)}), tok
        )

    def test_uncommitted_message_rejects_ignore_file_and_honors_inline_allow(self) -> None:
        repo = Repo(self)
        tok = registry_token()
        msg = repo.base / "msg.txt"
        msg.write_text(f"subject\n\ntoken {tok}\n")
        (repo.path / ".betterleaksignore").write_text(
            "\n".join(f":npm-access-token:{n}" for n in range(1, 10))
            + "\n.git/commit:npm-access-token:3\n<commit-message>:npm-access-token:3\n"
        )
        refused_by_secret_scan(self, repo.secret("message", str(msg)), tok)

        # Inline betterleaks:allow works unless SECRET_SCAN_IGNORE_ALLOW=1.
        msg_allow = repo.base / "msg-allow.txt"
        msg_allow.write_text(f"subject\n\ntoken {tok}  # betterleaks:allow\n")
        self.assertEqual(repo.secret("message", str(msg_allow)).returncode, 0)
        refused_by_secret_scan(
            self,
            repo.secret("message", str(msg_allow), extra_env={"SECRET_SCAN_IGNORE_ALLOW": "1"}),
            tok,
        )


class PngAndBinaryAdjacentTokenTests(unittest.TestCase):
    """A-F4: compressed PNG text chunks (zTXt/iTXt), tEXt before CRC, and binary-adjacent tokens."""

    def add_bytes(self, repo: Repo, name: str, data: bytes) -> None:
        (repo.path / name).write_bytes(data)
        repo.git("add", name)

    def test_png_ztxt_token_found_in_every_mode_and_stably_exemptable(self) -> None:
        repo = Repo(self)
        tok = registry_token()
        png = png_with_chunks((b"zTXt", b"Author\x00\x00" + zlib.compress(f"publish with {tok}".encode())))
        self.add_bytes(repo, "z.png", png)

        for args in (("staged",), ("files", "z.png")):
            with self.subTest(args=args):
                res = repo.secret(*args)
                refused_by_secret_scan(self, res, tok)
                self.assertIn("z.png#png-text:", combined(res))

        before = repo.git("rev-parse", "HEAD")
        self.assertNotEqual(repo.run("git", "commit", "-q", "-m", "add z.png").returncode, 0)
        self.assertEqual(repo.git("rev-parse", "HEAD"), before)

        repo.unchecked_commit("add z.png")
        c1 = repo.git("rev-parse", "HEAD")
        for args in (("rev", "HEAD"), ("range", "HEAD~1..HEAD"), ("history",)):
            with self.subTest(args=args):
                res = repo.secret(*args)
                refused_by_secret_scan(self, res, tok)
                self.assertIn(f"z.png#png-text:", combined(res))
                self.assertIn(c1, combined(res))

        pushed = repo.push("main")
        refused_by_secret_scan(self, pushed, tok)

        # Unstaged modification also catches zTXt.
        tok_u = registry_token()
        (repo.path / "z.png").write_bytes(
            png_with_chunks((b"zTXt", b"Author\x00\x00" + zlib.compress(f"unstaged {tok_u}".encode())))
        )
        refused_by_secret_scan(self, repo.secret("unstaged"), tok_u)
        repo.git("checkout", "--", "z.png")

        # Exempting z.png#png-text:<rule>:<line> allows z.png and NOT z2.png.
        lines = finding_lines(combined(repo.secret("rev", "HEAD")))
        loc = lines[0].split()[1]  # z.png#png-text:<line>
        rule = lines[0].split()[0]
        path_part, line_no = loc.rsplit(":", 1)
        repo.add_file(".betterleaksignore", f"{path_part}:{rule}:{line_no}\n")
        self.assertEqual(repo.secret("rev", "HEAD").returncode, 0)
        self.assertEqual(repo.secret("files", "z.png").returncode, 0)

        tok2 = registry_token()
        self.add_bytes(
            repo,
            "z2.png",
            png_with_chunks((b"zTXt", b"Author\x00\x00" + zlib.compress(f"publish with {tok2}".encode()))),
        )
        refused_by_secret_scan(self, repo.secret("staged"), tok2)

    def test_png_itxt_compressed_and_uncompressed_token_is_found(self) -> None:
        repo = Repo(self)
        tok_c = registry_token()
        tok_u = registry_token()
        png_c = png_with_chunks(
            (b"iTXt", b"Note\x00\x01\x00\x00\x00" + zlib.compress(f"secret {tok_c}".encode()))
        )
        png_u = png_with_chunks((b"iTXt", b"Note\x00\x00\x00\x00\x00" + tok_u.encode()))
        self.add_bytes(repo, "ic.png", png_c)
        self.add_bytes(repo, "iu.png", png_u)
        for name, tok in (("ic.png", tok_c), ("iu.png", tok_u)):
            with self.subTest(name=name):
                refused_by_secret_scan(self, repo.secret("files", name), tok)
        refused_by_secret_scan(self, repo.secret("staged"), tok_c)

    def test_png_text_token_directly_before_crc_is_found_even_with_ascii_crc(self) -> None:
        repo = Repo(self)
        # Try tokens until we find one whose tEXt chunk CRC begins with an ASCII letter/digit,
        # proving chunk decoding (not only raw byte sanitization) isolates the token from CRC.
        for _ in range(200):
            tok = registry_token()
            payload = b"Author\x00" + tok.encode()
            crc_first = struct.pack(">I", zlib.crc32(b"tEXt" + payload))[0]
            if 48 <= crc_first <= 57 or 65 <= crc_first <= 90 or 97 <= crc_first <= 122:
                break
        else:
            self.fail("could not generate a tEXt chunk with an ASCII-leading CRC")
        png = png_with_chunks((b"tEXt", payload))
        self.add_bytes(repo, "traw.png", png)
        refused_by_secret_scan(self, repo.secret("staged"), tok)
        refused_by_secret_scan(self, repo.secret("files", "traw.png"), tok)
        repo.unchecked_commit("add traw.png")
        refused_by_secret_scan(self, repo.secret("rev", "HEAD"), tok)

    def test_token_adjacent_to_binary_bytes_is_found_and_exemptable(self) -> None:
        repo = Repo(self)
        tok = registry_token()
        data = b"\x00\x01\xfe\xff" + tok.encode() + b"\xde\xad\xbe\xef"
        self.add_bytes(repo, "raw.bin", data)
        for args in (("staged",), ("files", "raw.bin")):
            with self.subTest(args=args):
                res = repo.secret(*args)
                refused_by_secret_scan(self, res, tok)
                self.assertIn("npm-access-token raw.bin:1", combined(res))
        repo.unchecked_commit("add raw.bin")
        for args in (("rev", "HEAD"), ("range", "HEAD~1..HEAD"), ("history",)):
            with self.subTest(args=args):
                res = repo.secret(*args)
                refused_by_secret_scan(self, res, tok)
                self.assertIn("raw.bin:1", combined(res))
        (repo.path / "raw.bin").write_bytes(b"\x00\xff" + registry_token().encode() + b"\xff\x00")
        refused_by_secret_scan(self, repo.secret("unstaged"), tok)
        repo.git("checkout", "--", "raw.bin")

        repo.add_file(".betterleaksignore", "raw.bin:npm-access-token:1\n")
        self.assertEqual(repo.secret("rev", "HEAD").returncode, 0)
        self.assertEqual(repo.secret("files", "raw.bin").returncode, 0)

    def test_corrupted_and_oversized_png_compressed_chunks_fail_closed(self) -> None:
        repo = Repo(self)
        corrupt = png_with_chunks((b"zTXt", b"Author\x00\x00not-valid-zlib"))
        self.add_bytes(repo, "bad.png", corrupt)
        res = repo.secret("staged")
        self.assertEqual(res.returncode, 1, combined(res))
        self.assertIn("secret_scan:", combined(res))
        self.assertEqual(repo.secret("files", "bad.png").returncode, 1)
        repo.git("rm", "-q", "-f", "bad.png")

        # Compression bomb: 65 MiB of zeros compresses to ~65 KiB, exceeds 64 MiB limit.
        bomb_payload = zlib.compress(b"\x00" * (65 * 1024 * 1024))
        bomb = png_with_chunks((b"zTXt", b"Author\x00\x00" + bomb_payload))
        self.add_bytes(repo, "bomb.png", bomb)
        res_b = repo.secret("staged")
        self.assertEqual(res_b.returncode, 1, combined(res_b))
        self.assertIn("secret_scan:", combined(res_b))

    def test_release_approve_exemption_accepts_new_stable_fingerprints(self) -> None:
        sha = "a" * 40
        samples = [
            f"{sha}:fixture.gif:npm-access-token:2",
            f"{sha}:z.png#png-text:npm-access-token:2",
            f"{sha}:.git/commit:npm-access-token:6",
            f"{sha}:.git/tag:npm-access-token:5",
            f"{sha}:.git/blob:npm-access-token:1",
        ]
        self.assertEqual(release_check.parse_approvals(samples), sorted(samples))


if __name__ == "__main__":
    unittest.main()
