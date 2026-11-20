"""Object coverage of the two scanners: annotated and nested tags, refs that point straight at a
tree or a blob, content that exists only in a merge commit, and which Betterleaks ignore files
apply when the caller names one.

Every test builds a throwaway repository with the real hooks and the real tools, a home folder of
its own whose private rules hold one synthetic marker, and a local bare remote. Fake tokens are
built at run time from random characters, so no secret-looking literal exists in the repository.
The registry token shape is one that only Betterleaks knows (the privacy scan's public rules do
not), so a refusal of it can only come from tools/secret_scan.sh.

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
MARKER = "zzobjmarker7731"
SUFFIX_MARKER = "zzcfgonly4410"


def random_text(length: int) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def registry_token() -> str:
    """A token shape that only Betterleaks knows; built at run time."""
    return "np" + "m_" + random_text(36)


def combined(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


class Repo:
    """A temporary maintainer clone with the real hooks and tools and a bare remote."""

    def __init__(self, testcase: unittest.TestCase) -> None:
        if shutil.which("betterleaks") is None:
            testcase.fail("betterleaks is not installed: brew install betterleaks")
        self.base = Path(tempfile.mkdtemp(prefix="guard-objects-"))
        testcase.addCleanup(shutil.rmtree, self.base, True)
        self.home = self.base / "home"
        rules = self.home / ".config" / "agent-genops" / "private_rules.json"
        rules.parent.mkdir(parents=True)
        rules.write_text(
            json.dumps(
                {
                    "version": 1,
                    "rules": [
                        {
                            "id": "synthetic_private_marker",
                            "pattern": MARKER,
                            "flags": "i",
                            "why": "synthetic private test marker",
                        },
                        {
                            "id": "synthetic_cfg_marker",
                            "pattern": SUFFIX_MARKER,
                            "suffixes": [".cfg"],
                            "why": "synthetic marker that only counts in .cfg files",
                        },
                    ],
                }
            )
        )
        self.path = self.base / "work"
        self.remote = self.base / "origin.git"
        self.env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("AGENT_GENOPS_", "SECRET_SCAN_", "GIT_"))
        }
        self.env["HOME"] = str(self.home)
        self.env["GIT_CONFIG_GLOBAL"] = os.devnull
        self.env["GIT_CONFIG_NOSYSTEM"] = "1"
        self.git("init", "-q", "-b", "main", str(self.path), cwd=self.base)
        self.git("init", "-q", "--bare", str(self.remote), cwd=self.base)
        for key, value in (
            ("user.email", IDENTITY),
            ("user.name", "tester"),
            ("core.hooksPath", ".githooks"),
            ("genops.mode", "maintainer"),
            ("genops.allowedPushUrl", str(self.remote)),
        ):
            self.git("config", key, value)
        self.git("remote", "add", "origin", str(self.remote))
        shutil.copytree(ROOT / ".githooks", self.path / ".githooks")
        tools = self.path / "tools"
        tools.mkdir()
        for name in ("privacy_scan.py", "privacy_rules.json", "secret_scan.sh", "secret_scan.tmpl"):
            shutil.copy2(ROOT / "tools" / name, tools / name)
        (self.path / "README.md").write_text("# Synthetic\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "initial clean baseline")
        self.git("push", "-q", "-u", "origin", "main")

    # --- running things ---------------------------------------------------------------

    def run(self, *args: str, env: dict[str, str] | None = None, cwd: Path | None = None,
            stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            cwd=cwd or self.path,
            env=env or self.env,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    def git(self, *args: str, cwd: Path | None = None, stdin: str | None = None) -> str:
        result = self.run("git", *args, cwd=cwd, stdin=stdin)
        if result.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed: {combined(result)}")
        return result.stdout.strip()

    def unchecked_commit(self, message: str) -> None:
        """A commit the hooks never see, to put content into history."""
        self.git("-c", f"core.hooksPath={os.devnull}", "commit", "-q", "-m", message)

    def add_file(self, name: str, text: str) -> None:
        target = self.path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        self.git("add", name)

    def privacy(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.run("python3", "-B", "tools/privacy_scan.py", *args)

    def secret(self, *args: str, extra_env: dict[str, str] | None = None
               ) -> subprocess.CompletedProcess[str]:
        env = dict(self.env)
        env.update(extra_env or {})
        return self.run("sh", "tools/secret_scan.sh", *args, env=env)

    def push(self, *refspecs: str) -> subprocess.CompletedProcess[str]:
        return self.run("git", "push", "origin", *refspecs)

    def remote_has(self, ref: str) -> bool:
        result = self.run("git", "--git-dir", str(self.remote), "rev-parse", "--verify", "--quiet", ref)
        return result.returncode == 0

    def hash_blob(self, text: str) -> str:
        return self.git("hash-object", "-w", "--stdin", stdin=text)

    def make_tree(self, blob: str, name: str = "note.txt") -> str:
        return self.git("mktree", stdin=f"100644 blob {blob}\t{name}\n")

    def fingerprints(self, *bl_args: str) -> list[str]:
        """Fingerprints Betterleaks reports for this repository, read from a JSON report."""
        report = self.base / f"report-{random_text(6)}.json"
        self.run(
            "betterleaks", *bl_args, "--redact", "--no-banner", "--no-color", "--log-level",
            "error", "-f", "json", "-r", str(report),
        )
        return [item["Fingerprint"] for item in json.loads(report.read_text() or "[]")]

    def evil_merge(self, token: str | None) -> None:
        """A merge whose tree adds a file that neither parent has (with a token, or clean)."""
        self.git("checkout", "-q", "-b", "side")
        self.add_file("side.txt", "side\n")
        self.unchecked_commit("side")
        self.git("checkout", "-q", "main")
        self.add_file("main.txt", "main\n")
        self.unchecked_commit("main work")
        self.git("merge", "-q", "--no-ff", "--no-commit", "side")
        self.add_file("merged.txt", f"key = {token}\n" if token else "nothing to see\n")
        self.unchecked_commit("merge side")


class AnnotatedTagPushTests(unittest.TestCase):
    """R1 through the real pre-push hook: the tag object itself is what is published."""

    def test_push_refuses_private_marker_in_annotated_tag_message(self) -> None:
        repo = Repo(self)
        repo.git("tag", "-a", "v1", "-m", f"release notes mention {MARKER} here")
        result = repo.push("v1")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("synthetic_private_marker", combined(result))
        self.assertNotIn(MARKER, combined(result))
        self.assertFalse(repo.remote_has("refs/tags/v1"))

    def test_push_refuses_token_in_annotated_tag_message(self) -> None:
        repo = Repo(self)
        token = registry_token()
        message = repo.base / "tagmsg.txt"
        message.write_text(f"token {token}\n")
        repo.git("tag", "-a", "v2", "-F", str(message))
        result = repo.push("v2")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("secret_scan:", combined(result))
        self.assertNotIn(token, combined(result))
        self.assertFalse(repo.remote_has("refs/tags/v2"))

    def test_push_of_a_clean_annotated_tag_passes(self) -> None:
        repo = Repo(self)
        repo.git("tag", "-a", "v3", "-m", "clean release notes")
        result = repo.push("v3")
        self.assertEqual(result.returncode, 0, combined(result))
        self.assertTrue(repo.remote_has("refs/tags/v3"))


class NestedTagTests(unittest.TestCase):
    """An outer clean tag that points at an inner tag whose own ref was deleted."""

    def nested(self, repo: Repo, inner_name: str, inner_message: str) -> str:
        message = repo.base / "inner.txt"
        message.write_text(inner_message)
        repo.git("tag", "-a", inner_name, "-F", str(message), "HEAD")
        repo.git("-c", "advice.nestedTag=false", "tag", "-a", "outer", "-m", "outer clean", inner_name)
        repo.git("tag", "-d", inner_name)
        return repo.git("rev-parse", "outer")

    def test_privacy_scan_reads_every_layer_of_a_nested_tag(self) -> None:
        repo = Repo(self)
        outer = self.nested(repo, "inner", f"inner {MARKER}\n")
        for args in (("--history",), ("--rev", outer)):
            with self.subTest(args=args):
                result = repo.privacy(*args)
                self.assertEqual(result.returncode, 1, combined(result))
                self.assertIn("synthetic_private_marker", result.stdout)

    def test_privacy_scan_reads_the_name_inside_a_tag_object(self) -> None:
        repo = Repo(self)
        outer = self.nested(repo, f"rel-{MARKER}", "inner clean\n")
        for args in (("--history",), ("--rev", outer)):
            with self.subTest(args=args):
                result = repo.privacy(*args)
                self.assertEqual(result.returncode, 1, combined(result))
                self.assertIn("synthetic_private_marker", result.stdout)
                self.assertNotIn(MARKER, combined(result))

    def test_push_refuses_a_nested_tag_with_a_private_inner_layer(self) -> None:
        repo = Repo(self)
        self.nested(repo, "inner", f"inner {MARKER}\n")
        result = repo.push("outer")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertFalse(repo.remote_has("refs/tags/outer"))

    def test_secret_scan_reads_every_layer_of_a_nested_tag(self) -> None:
        repo = Repo(self)
        token = registry_token()
        outer = self.nested(repo, "inner", f"inner {token}\n")
        for args in (("history",), ("rev", outer)):
            with self.subTest(args=args):
                result = repo.secret(*args)
                self.assertNotEqual(result.returncode, 0, combined(result))
                self.assertNotEqual(result.returncode, 2, combined(result))
                self.assertNotIn(token, combined(result))


class DirectObjectRefTests(unittest.TestCase):
    """Refs that point straight at a blob or a tree, with no commit in between."""

    def test_privacy_scan_reports_a_blob_tag(self) -> None:
        repo = Repo(self)
        blob = repo.hash_blob(f"secret note {MARKER}\n")
        repo.git("tag", "blobtag", blob)
        for args in (("--history",), ("--rev", blob), ("--rev", "blobtag")):
            with self.subTest(args=args):
                result = repo.privacy(*args)
                self.assertEqual(result.returncode, 1, combined(result))
                self.assertIn("synthetic_private_marker", result.stdout)

    def test_privacy_scan_reports_a_tree_ref(self) -> None:
        repo = Repo(self)
        tree = repo.make_tree(repo.hash_blob(f"secret note {MARKER}\n"))
        repo.git("update-ref", "refs/custom/treeref", tree)
        for args in (("--history",), ("--rev", tree)):
            with self.subTest(args=args):
                result = repo.privacy(*args)
                self.assertEqual(result.returncode, 1, combined(result))
                self.assertIn("synthetic_private_marker", result.stdout)

    def test_privacy_scan_reports_an_annotated_tag_of_a_blob(self) -> None:
        repo = Repo(self)
        blob = repo.hash_blob(f"secret note {MARKER}\n")
        repo.git("tag", "-a", "blobnote", "-m", "clean message", blob)
        for args in (("--history",), ("--rev", "blobnote")):
            with self.subTest(args=args):
                result = repo.privacy(*args)
                self.assertEqual(result.returncode, 1, combined(result))
                self.assertIn("synthetic_private_marker", result.stdout)

    def test_clean_blob_tag_is_clean_not_an_error(self) -> None:
        repo = Repo(self)
        blob = repo.hash_blob("nothing private here\n")
        repo.git("tag", "blobtag", blob)
        for args in (("--history",), ("--rev", blob)):
            with self.subTest(args=args):
                result = repo.privacy(*args)
                self.assertEqual(result.returncode, 0, combined(result))
        result = repo.secret("rev", blob)
        self.assertEqual(result.returncode, 0, combined(result))

    def test_secret_scan_reads_a_blob_tag_and_a_tree_ref(self) -> None:
        repo = Repo(self)
        token = registry_token()
        blob = repo.hash_blob(f"key = {token}\n")
        tree = repo.make_tree(repo.hash_blob(f"other = {registry_token()}\n"))
        repo.git("tag", "blobtag", blob)
        for args in (("rev", blob), ("rev", tree), ("history",)):
            with self.subTest(args=args):
                result = repo.secret(*args)
                self.assertNotEqual(result.returncode, 0, combined(result))
                self.assertNotEqual(result.returncode, 2, combined(result))
                self.assertNotIn(token, combined(result))
        repo.git("tag", "-d", "blobtag")
        repo.git("update-ref", "refs/custom/treeref", tree)
        result = repo.secret("history")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertNotEqual(result.returncode, 2, combined(result))

    def test_push_of_a_blob_tag_is_refused_by_the_privacy_scan_itself(self) -> None:
        repo = Repo(self)
        blob = repo.hash_blob(f"secret note {MARKER}\n")
        repo.git("tag", "blobtag", blob)
        result = repo.push("blobtag")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("synthetic_private_marker", combined(result))
        self.assertNotIn("invalid commit", combined(result))
        self.assertFalse(repo.remote_has("refs/tags/blobtag"))


class SharedBlobTests(unittest.TestCase):
    """One blob at two paths whose suffixes decide whether a rule applies."""

    def test_every_path_of_a_shared_blob_is_checked(self) -> None:
        repo = Repo(self)
        text = f"setting {SUFFIX_MARKER}\n"
        repo.add_file("a.txt", text)
        repo.add_file("b.cfg", text)
        repo.unchecked_commit("same content twice")
        for args in (("--history",), ("--rev", "HEAD")):
            with self.subTest(args=args):
                result = repo.privacy(*args)
                self.assertEqual(result.returncode, 1, combined(result))
                self.assertIn("synthetic_cfg_marker", result.stdout)


class MergeOnlyContentTests(unittest.TestCase):
    """R3: a token that only the merge commit's tree adds."""

    def test_secret_scan_sees_a_token_added_only_in_a_merge(self) -> None:
        repo = Repo(self)
        token = registry_token()
        repo.evil_merge(token)
        base = repo.git("rev-parse", "HEAD^1")
        for args in (("rev", "HEAD"), ("history",), ("range", f"{base}..HEAD")):
            with self.subTest(args=args):
                result = repo.secret(*args)
                self.assertNotEqual(result.returncode, 0, combined(result))
                self.assertNotEqual(result.returncode, 2, combined(result))
                self.assertNotIn(token, combined(result))
        result = repo.push("main")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertNotEqual(
            repo.git("rev-parse", "HEAD"),
            repo.run("git", "--git-dir", str(repo.remote), "rev-parse", "main").stdout.strip(),
        )

    def test_a_clean_merge_passes(self) -> None:
        repo = Repo(self)
        repo.evil_merge(None)
        base = repo.git("rev-parse", "HEAD^1")
        for args in (("rev", "HEAD"), ("history",), ("range", f"{base}..HEAD")):
            with self.subTest(args=args):
                result = repo.secret(*args)
                self.assertEqual(result.returncode, 0, combined(result))
        result = repo.push("main")
        self.assertEqual(result.returncode, 0, combined(result))


class BinaryLogFormTests(unittest.TestCase):
    """The second pass over binary content walks history from git log -z --raw --numstat."""

    NAMES = (b"with space.bin", b"new\nline.bin", b'quo"te.bin', b"caf\xe9.bin")

    def merge_adding(self, repo: Repo, data: bytes) -> None:
        """A merge whose tree alone adds one blob under four awkward names, one not UTF-8."""
        repo.git("checkout", "-q", "-b", "side")
        repo.add_file("side.txt", "side\n")
        repo.unchecked_commit("side")
        repo.git("checkout", "-q", "main")
        repo.add_file("main.txt", "main\n")
        repo.unchecked_commit("main work")
        env = dict(repo.env, GIT_INDEX_FILE=str(repo.base / "merge.index"))

        def git(*args: bytes | str, stdin: bytes | None = None) -> bytes:
            return subprocess.run(
                ["git", *args], cwd=repo.path, env=env, input=stdin, capture_output=True, check=True
            ).stdout.strip()

        blob = git("hash-object", "-w", "--stdin", stdin=data)
        git("read-tree", "HEAD")
        for name in self.NAMES:
            git("update-index", "--add", "--cacheinfo", b"100644," + blob + b"," + name)
        tree = git("write-tree")
        merge = git("commit-tree", tree, "-p", "main", "-p", "side", "-m", "merge side")
        # The working tree is left as it is: this file system may refuse a name not in UTF-8.
        repo.git("update-ref", "refs/heads/main", merge.decode())

    def test_awkward_names_in_a_merge_are_reported_with_stable_paths(self) -> None:
        repo = Repo(self)
        token = registry_token()
        self.merge_adding(repo, b"\x00\x01\nkey = " + token.encode() + b"\n")
        head = repo.git("rev-parse", "HEAD")
        for args in (("rev", "HEAD"), ("range", "HEAD~1..HEAD"), ("history",)):
            with self.subTest(args=args):
                result = repo.secret(*args)
                self.assertNotEqual(result.returncode, 0, combined(result))
                self.assertNotEqual(result.returncode, 2, combined(result))
                self.assertNotIn(token, combined(result))
                # One blob under four awkward names: four per-path findings carrying the merge
                # commit and local line 2, and no pathless " :line" findings.
                findings = [line for line in combined(result).splitlines() if line.startswith("  ")]
                self.assertEqual(len(findings), len(self.NAMES), combined(result))
                self.assertFalse(any(" :" in line for line in findings), combined(result))
                self.assertTrue(all(f":2 {head}" in line for line in findings), combined(result))

    def test_awkward_names_in_a_clean_merge_pass(self) -> None:
        repo = Repo(self)
        self.merge_adding(repo, b"\x00\x01\nnothing to see\n")
        for args in (("rev", "HEAD"), ("range", "HEAD~1..HEAD"), ("history",)):
            with self.subTest(args=args):
                result = repo.secret(*args)
                self.assertEqual(result.returncode, 0, combined(result))


class ExplicitIgnoreFileTests(unittest.TestCase):
    """R4: with SECRET_SCAN_IGNORE_PATH set, that file is the only ignore list."""

    def setUp(self) -> None:
        self.repo = Repo(self)
        self.token = registry_token()
        self.repo.add_file("config.txt", f"key = {self.token}\n")
        self.repo.unchecked_commit("add config")
        self.empty = self.repo.base / "empty.ignore"
        self.empty.write_text("")
        self.prints = self.repo.fingerprints("git", str(self.repo.path))
        self.assertTrue(self.prints, "betterleaks found nothing to fingerprint")

    def explicit(self, path: Path) -> dict[str, str]:
        return {"SECRET_SCAN_IGNORE_PATH": str(path)}

    def assert_refused(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertNotEqual(result.returncode, 2, combined(result))
        self.assertNotIn(self.token, combined(result))

    def test_committed_ignore_file_does_not_apply(self) -> None:
        self.repo.add_file(".betterleaksignore", "\n".join(self.prints) + "\n")
        self.repo.unchecked_commit("add ignore")
        head = self.repo.git("rev-parse", "HEAD")
        for args in (("rev", head), ("history",), ("range", f"{head}~2..{head}")):
            with self.subTest(args=args):
                self.assert_refused(self.repo.secret(*args, extra_env=self.explicit(self.empty)))

    def test_committed_legacy_ignore_file_does_not_apply(self) -> None:
        self.repo.add_file(".gitleaksignore", "\n".join(self.prints) + "\n")
        self.repo.unchecked_commit("add legacy ignore")
        for args in (("rev", "HEAD"), ("history",)):
            with self.subTest(args=args):
                self.assert_refused(self.repo.secret(*args, extra_env=self.explicit(self.empty)))

    def test_untracked_ignore_file_does_not_apply(self) -> None:
        (self.repo.path / ".betterleaksignore").write_text("\n".join(self.prints) + "\n")
        for args in (("rev", "HEAD"), ("history",)):
            with self.subTest(args=args):
                self.assert_refused(self.repo.secret(*args, extra_env=self.explicit(self.empty)))

    def test_working_tree_ignore_file_does_not_cover_messages(self) -> None:
        message = self.repo.base / "msg.txt"
        message.write_text(f"token {registry_token()}\n")
        self.repo.git("tag", "-a", "v9", "-F", str(message), "HEAD~1")
        tag_oid = self.repo.git("rev-parse", "v9")
        report = self.repo.base / "stdin.json"
        self.repo.run(
            "betterleaks", "stdin", "--redact", "--no-banner", "--log-level", "error",
            "-f", "json", "-r", str(report), stdin=message.read_text(),
        )
        rules = {item["RuleID"] for item in json.loads(report.read_text())}
        self.assertTrue(rules)
        tag_prints = [f"{tag_oid}:.git/tag:{rule}:{line}" for rule in rules for line in range(1, 20)]
        (self.repo.path / ".betterleaksignore").write_text(
            "\n".join(self.prints + tag_prints) + "\n"
        )
        self.repo.git("checkout", "-q", "HEAD~1")  # the token file is gone from disk
        # Sanity check: without SECRET_SCAN_IGNORE_PATH, the tag-scoped entry covers v9.
        self.assertEqual(self.repo.secret("rev", "v9").returncode, 0)
        for args in (("rev", "v9"), ("history",)):
            with self.subTest(args=args):
                self.assert_refused(self.repo.secret(*args, extra_env=self.explicit(self.empty)))

    def test_the_named_ignore_file_still_applies(self) -> None:
        named = self.repo.base / "named.ignore"
        named.write_text("\n".join(self.prints) + "\n")
        for args in (("rev", "HEAD"), ("history",)):
            with self.subTest(args=args):
                result = self.repo.secret(*args, extra_env=self.explicit(named))
                self.assertEqual(result.returncode, 0, combined(result))

    def test_without_a_named_file_the_working_tree_ignore_file_still_applies(self) -> None:
        # The documented way to allow a false positive in a clone (PRIVACY.md) stays as it was.
        (self.repo.path / ".betterleaksignore").write_text("\n".join(self.prints) + "\n")
        result = self.repo.secret("rev", "HEAD")
        self.assertEqual(result.returncode, 0, combined(result))

    def test_working_tree_ignore_file_does_not_apply_to_message_or_files(self) -> None:
        # Symlink target findings use the stable path fingerprint "link.txt:<rule>:1"; bare
        # ":<rule>:<line>" entries never apply, and uncommitted message mode never applies
        # .betterleaksignore at all. With SECRET_SCAN_IGNORE_PATH pointing to an empty file,
        # the working-tree .betterleaksignore does not cover link.txt either.
        token = registry_token()
        rules = {fp.split(":")[-2] for fp in self.prints}
        bare_and_link = [f":{rule}:{line}" for rule in rules for line in range(1, 10)]
        bare_and_link += [f"link.txt:{rule}:1" for rule in rules]
        (self.repo.path / ".betterleaksignore").write_text("\n".join(bare_and_link) + "\n")
        message = self.repo.base / "msg.txt"
        message.write_text(f"subject\n\ntoken {token}\n")
        (self.repo.path / "link.txt").symlink_to(f"key-{token}")

        # Symlink target: exempted by link.txt:<rule>:1 without explicit ignore, refused with empty.
        without_link = self.repo.secret("files", "link.txt")
        self.assertEqual(without_link.returncode, 0, combined(without_link))
        with_empty_link = self.repo.secret("files", "link.txt", extra_env=self.explicit(self.empty))
        self.assert_refused(with_empty_link)
        self.assertNotIn(token, combined(with_empty_link))

        # Uncommitted message: never exempted by .betterleaksignore with or without explicit ignore.
        for extra in ({}, self.explicit(self.empty)):
            with self.subTest(extra=bool(extra)):
                res = self.repo.secret("message", str(message), extra_env=extra)
                self.assert_refused(res)
                self.assertNotIn(token, combined(res))

    def test_unstaged_mode_refuses_a_named_ignore_file(self) -> None:
        result = self.repo.secret("unstaged", extra_env=self.explicit(self.empty))
        self.assertEqual(result.returncode, 2, combined(result))


class InlineAllowSwitchTests(unittest.TestCase):
    """SECRET_SCAN_IGNORE_ALLOW=1 makes Betterleaks ignore inline allow comments."""

    def test_switch_turns_inline_allow_comments_off(self) -> None:
        repo = Repo(self)
        token = registry_token()
        repo.add_file("config.txt", f"key = {token}  # gitleaks:allow\n")
        repo.unchecked_commit("allowed inline")
        empty = repo.base / "empty.ignore"
        empty.write_text("")
        for args in (("rev", "HEAD"), ("history",)):
            for named in (False, True):
                with self.subTest(args=args, named=named):
                    base_env = {"SECRET_SCAN_IGNORE_PATH": str(empty)} if named else {}
                    allowed = repo.secret(*args, extra_env=base_env)
                    self.assertEqual(allowed.returncode, 0, combined(allowed))
                    strict = repo.secret(*args, extra_env={**base_env, "SECRET_SCAN_IGNORE_ALLOW": "1"})
                    self.assertNotEqual(strict.returncode, 0, combined(strict))
                    self.assertNotEqual(strict.returncode, 2, combined(strict))
                    self.assertNotIn(token, combined(strict))


if __name__ == "__main__":
    unittest.main()
