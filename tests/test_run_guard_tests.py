"""Tests for tools/run_guard_tests.py (sharding completeness and fail-closed exits)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import run_guard_tests  # noqa: E402


class GuardTestRunnerTests(unittest.TestCase):
    def test_round_robin_shards_cover_every_discovered_test_exactly_once(self) -> None:
        all_ids = run_guard_tests.discover_test_ids(ROOT / "tests")
        self.assertGreater(len(all_ids), 200)
        self.assertEqual(len(all_ids), len(set(all_ids)))

        for total in (1, 4, 6):
            collected: list[str] = []
            for idx in range(1, total + 1):
                shard = run_guard_tests.select_shard(all_ids, idx, total)
                self.assertTrue(shard)
                collected.extend(shard)
            self.assertEqual(sorted(collected), all_ids)
            self.assertEqual(len(collected), len(all_ids))

    def test_invalid_shard_and_worker_arguments_are_refused(self) -> None:
        for bad in ("0/6", "7/6", "1/0", "abc", "1/2/3"):
            with self.subTest(shard=bad):
                with self.assertRaises(ValueError):
                    run_guard_tests.parse_shard(bad)
        rc = run_guard_tests.main(["--shard", "0/6"])
        self.assertEqual(rc, 2)
        rc_workers = run_guard_tests.main(["--workers", "0"])
        self.assertEqual(rc_workers, 2)

    def test_runner_executes_passing_and_fails_closed_on_failing_synthetic_suite(self) -> None:
        with tempfile.TemporaryDirectory(prefix="guard-runner-") as tmp:
            td = Path(tmp)
            tests_dir = td / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_alpha.py").write_text(
                "import unittest\n"
                "class A(unittest.TestCase):\n"
                "    def test_one(self): self.assertEqual(1 + 1, 2)\n"
                "    def test_two(self): self.assertTrue(True)\n",
                encoding="utf-8",
            )
            (tests_dir / "test_beta.py").write_text(
                "import unittest\n"
                "class B(unittest.TestCase):\n"
                "    def test_three(self): self.assertEqual(2 * 2, 4)\n"
                "    def test_four(self): self.assertFalse(False)\n",
                encoding="utf-8",
            )
            ok = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "tools" / "run_guard_tests.py"),
                    "--top-level-dir",
                    str(td),
                    "--start-dir",
                    "tests",
                    "--shard",
                    "1/2",
                    "--workers",
                    "2",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            self.assertIn("2/4 tests", ok.stdout)

            (tests_dir / "test_fail.py").write_text(
                "import unittest\n"
                "class F(unittest.TestCase):\n"
                "    def test_boom(self): self.fail('intentional')\n",
                encoding="utf-8",
            )
            bad = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "tools" / "run_guard_tests.py"),
                    "--top-level-dir",
                    str(td),
                    "--start-dir",
                    "tests",
                    "--shard",
                    "1/1",
                    "--workers",
                    "2",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bad.returncode, 1, bad.stdout + bad.stderr)
            self.assertIn("intentional", bad.stderr)


if __name__ == "__main__":
    unittest.main()
