#!/usr/bin/env python3
"""Deterministic, fail-closed parallel and sharded runner for root guard tests.

Discovers every ``unittest.TestCase`` method under ``tests/`` using the standard
``unittest.TestLoader`` (identical discovery to ``python3 -B -m unittest discover -s tests``),
optionally selects one deterministic round-robin shard (``--shard INDEX/TOTAL``), and runs
that shard's tests concurrently across isolated worker subprocesses (``--workers N``).

Zero third-party dependencies; fails closed if discovery finds zero tests, if a shard is
invalid, or if any worker exits non-zero.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def iter_test_ids(suite: unittest.TestSuite) -> list[str]:
    """Flatten a ``unittest.TestSuite`` into deterministic dotted test IDs."""
    ids: list[str] = []

    def walk(node: unittest.TestSuite | unittest.TestCase) -> None:
        if isinstance(node, unittest.TestSuite):
            for child in node:
                walk(child)
        else:
            ids.append(node.id())

    walk(suite)
    return sorted(ids)


def discover_test_ids(
    start_dir: Path,
    top_level_dir: Path | None = None,
    pattern: str = "test_*.py",
) -> list[str]:
    """Discover all unittest test method IDs under ``start_dir``.

    Matches ``python3 -B -m unittest discover -s tests``: when ``start_dir`` is not a
    Python package (no ``__init__.py``), ``top_level_dir`` defaults to ``start_dir``.
    """
    effective_top = top_level_dir if top_level_dir is not None else (
        start_dir.parent if (start_dir / "__init__.py").is_file() else start_dir
    )
    loader = unittest.TestLoader()
    suite = loader.discover(
        start_dir=str(start_dir),
        pattern=pattern,
        top_level_dir=str(effective_top),
    )
    ids = iter_test_ids(suite)
    # unittest turns import errors into _FailedTest instances; surface them immediately.
    failed_loads = [tid for tid in ids if tid.startswith("unittest.loader._FailedTest.")]
    if failed_loads:
        raise RuntimeError(f"test discovery failed to import: {', '.join(failed_loads)}")
    return ids


def parse_shard(spec: str) -> tuple[int, int]:
    """Parse ``INDEX/TOTAL`` (1-based) or raise ValueError."""
    parts = spec.strip().split("/")
    if len(parts) != 2:
        raise ValueError(f"invalid --shard {spec!r}; expected INDEX/TOTAL (e.g. 1/6)")
    index, total = int(parts[0]), int(parts[1])
    if total < 1 or not (1 <= index <= total):
        raise ValueError(f"invalid --shard {spec!r}; require 1 <= INDEX <= TOTAL")
    return index, total


def select_shard(ids: list[str], index: int, total: int) -> list[str]:
    """Select round-robin shard ``index`` of ``total`` (1-based) to spread slow modules evenly."""
    return ids[index - 1 :: total]


def partition_workers(ids: list[str], workers: int) -> list[list[str]]:
    """Split ``ids`` round-robin into up to ``workers`` non-empty worker batches."""
    if workers < 1:
        raise ValueError(f"--workers must be >= 1, got {workers}")
    buckets = [ids[i::workers] for i in range(workers)]
    return [bucket for bucket in buckets if bucket]


def run_batch(
    batch_index: int,
    test_ids: list[str],
    *,
    cwd: Path,
    import_dir: Path,
    gomaxprocs: str | None = None,
) -> tuple[int, int, float, str]:
    """Execute one batch of test IDs in an isolated Python subprocess."""
    env = dict(os.environ)
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{import_dir}{os.pathsep}{existing_pp}" if existing_pp else str(import_dir)
    if gomaxprocs:
        env.setdefault("GOMAXPROCS", gomaxprocs)
    t0 = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", *test_ids],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = time.monotonic() - t0
    combined = (proc.stdout + "\n" + proc.stderr).strip()
    return batch_index, proc.returncode, elapsed, combined


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run root guard tests in parallel shards.")
    parser.add_argument("--start-dir", default="tests", help="directory to discover tests in (default: tests)")
    parser.add_argument("--top-level-dir", default=".", help="top-level directory for imports (default: .)")
    parser.add_argument("--pattern", default="test_*.py", help="unittest discovery filename pattern")
    parser.add_argument("--shard", default="1/1", help="1-based shard INDEX/TOTAL (default: 1/1)")
    parser.add_argument(
        "--workers",
        type=int,
        default=min(os.cpu_count() or 2, 4),
        help="concurrent worker subprocesses per shard (default: min(cpus, 4))",
    )
    parser.add_argument("--list-only", action="store_true", help="print selected test IDs and exit")
    args = parser.parse_args(argv)

    try:
        shard_index, shard_total = parse_shard(args.shard)
        if args.workers < 1:
            raise ValueError(f"--workers must be >= 1, got {args.workers}")
    except ValueError as exc:
        print(f"run_guard_tests: {exc}", file=sys.stderr)
        return 2

    top_dir = Path(args.top_level_dir).resolve()
    start_dir = (top_dir / args.start_dir).resolve() if not Path(args.start_dir).is_absolute() else Path(args.start_dir)
    if not start_dir.is_dir():
        print(f"run_guard_tests: start directory not found: {start_dir}", file=sys.stderr)
        return 2

    import_dir = top_dir if (start_dir / "__init__.py").is_file() else start_dir
    try:
        all_ids = discover_test_ids(start_dir, import_dir, pattern=args.pattern)
    except Exception as exc:
        print(f"run_guard_tests: discovery error: {exc}", file=sys.stderr)
        return 2

    if not all_ids:
        print(f"run_guard_tests: discovered 0 tests under {start_dir}", file=sys.stderr)
        return 2

    selected = select_shard(all_ids, shard_index, shard_total)
    if args.list_only:
        for tid in selected:
            print(tid)
        return 0

    if not selected:
        print(
            f"run_guard_tests: shard {shard_index}/{shard_total} selected 0 of {len(all_ids)} tests",
            file=sys.stderr,
        )
        return 2

    batches = partition_workers(selected, args.workers)
    gomaxprocs = "2" if len(batches) > 1 else None
    t_start = time.monotonic()
    print(
        f"run_guard_tests: shard {shard_index}/{shard_total} -> "
        f"{len(selected)}/{len(all_ids)} tests across {len(batches)} worker(s)",
        flush=True,
    )

    failures: list[tuple[int, int, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(batches)) as pool:
        futures = [
            pool.submit(run_batch, idx, batch, cwd=top_dir, import_dir=import_dir, gomaxprocs=gomaxprocs)
            for idx, batch in enumerate(batches, 1)
        ]
        for fut in concurrent.futures.as_completed(futures):
            batch_idx, rc, elapsed, output = fut.result()
            status = "PASS" if rc == 0 else f"FAIL (rc={rc})"
            print(f"  worker {batch_idx}/{len(batches)}: {len(batches[batch_idx - 1])} tests -> {status} ({elapsed:.1f}s)", flush=True)
            if rc != 0:
                failures.append((batch_idx, rc, output))

    wall = time.monotonic() - t_start
    if failures:
        for batch_idx, rc, output in sorted(failures):
            print(f"\n=== worker {batch_idx} failed (rc={rc}) ===\n{output}", file=sys.stderr)
        print(
            f"run_guard_tests: FAILED ({len(failures)}/{len(batches)} workers failed in {wall:.1f}s)",
            file=sys.stderr,
        )
        return 1

    print(f"run_guard_tests: PASS ({len(selected)} tests in {wall:.1f}s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
