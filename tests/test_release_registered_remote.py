"""A release check against the repository's registered upstream is not a rehearsal.

``--allowed-url`` and ``genops.allowedPushUrl`` may also name a registered upstream address. Then the
remote is the repository's own and the manifest must not call itself a rehearsal. The remote here
is one of the registered ssh addresses, but its ssh transport is a local script that serves the
synthetic bare repository with ``git upload-pack``, so nothing connects anywhere.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import release_check  # noqa: E402
from test_release_check import SyntheticRepo, combined  # noqa: E402
from test_release_trusted import clean_candidate, need_betterleaks  # noqa: E402


def registered_ssh_url() -> str:
    urls = sorted(u for u in release_check.DEFAULT_ALLOWED_URLS if u.startswith("ssh://"))
    assert urls, "no registered ssh:// address"
    return urls[0]


class RegisteredUpstreamTests(unittest.TestCase):
    def repo_behind_registered_url(self) -> tuple[SyntheticRepo, str, dict[str, str]]:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        url = registered_ssh_url()
        transport = repo.base / "local-upstream.sh"
        transport.write_text(
            "#!/bin/sh\n"
            'case " $* " in *" -G "*) exit 0 ;; esac\n'
            f"exec git upload-pack '{repo.remote}'\n"
        )
        transport.chmod(0o755)
        repo.git("remote", "set-url", "origin", url)
        repo.git("config", "--unset", "genops.allowedPushUrl")
        env = dict(repo.env, GIT_SSH_COMMAND=str(transport))
        return repo, url, env

    def release(self, repo: SyntheticRepo, env: dict[str, str], cand: str, *more: str):
        return repo.check(
            "release", "--to", "origin", "--ref", "refs/heads/main", "--commit", cand,
            "--manifest-dir", str(repo.manifest_dir), *more, env=env,
        )

    def assert_not_a_rehearsal(self, repo: SyntheticRepo, env: dict[str, str], *more: str) -> None:
        cand = clean_candidate(repo)
        res = self.release(repo, env, cand, "--json", *more)
        self.assertEqual(res.returncode, 0, combined(res))
        payload = json.loads(res.stdout)
        manifest = payload["manifest"]
        self.assertIs(manifest["rehearsal_remote"], False)
        self.assertFalse(any("rehearsal" in note for note in manifest["unverified_items"]), manifest)
        # The same remote approved again: the fresh check agrees with the manifest field by field.
        ver = repo.check("release", "--verify-manifest", payload["manifest_path"], *more, env=env)
        self.assertEqual(ver.returncode, 0, combined(ver))
        self.assertIn("VALID", ver.stdout)

        text = self.release(repo, env, clean_candidate(repo, "Another clean change."), *more)
        self.assertEqual(text.returncode, 0, combined(text))
        self.assertNotIn("REHEARSAL", text.stdout)
        self.assertNotIn("does not clear a release", text.stdout)

    def test_the_registered_url_named_with_allowed_url_is_not_a_rehearsal(self) -> None:
        repo, url, env = self.repo_behind_registered_url()
        self.assert_not_a_rehearsal(repo, env, "--allowed-url", url)

    def test_the_registered_url_named_in_the_setting_is_not_a_rehearsal(self) -> None:
        repo, url, env = self.repo_behind_registered_url()
        repo.git("config", "genops.allowedPushUrl", url)
        self.assert_not_a_rehearsal(repo, env)

    def test_the_registered_url_without_a_name_is_not_a_rehearsal(self) -> None:
        repo, _url, env = self.repo_behind_registered_url()
        self.assert_not_a_rehearsal(repo, env)


if __name__ == "__main__":
    unittest.main()
