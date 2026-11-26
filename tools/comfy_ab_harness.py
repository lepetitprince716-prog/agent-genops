#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Interleaved A-B-A / ABBA benchmark harness for ComfyUI HTTP endpoints (stdlib only).

Runs paired API workflow JSON files against a local or tunnelled ComfyUI server, discards
warm-up runs per arm, samples GPU clock/power/throttle state through ``nvidia-smi`` when
present, summarizes median and IQR execution times, and writes per-run JSONL telemetry.

With ``--strict-cache``, the harness fails closed (exit 1) if ComfyUI's execution messages
show either:
  - a cached sampler node (preventing the 0.07 s full-graph cache hit when ``ctl_2`` repeats
    ``ctl_1`` with the same seed), or
  - an asymmetric text-encoder cache hit across arms (preventing a cold 1.4 s ``CLIPTextEncode``
    on one arm from racing a cached encoder on the other).

    python3 tools/comfy_ab_harness.py --control ctl.json --candidate cand.json \\
        [--off off.json] [--order aba|abba] [--seed 1001 --seed 1002 --seed 1003] \\
        [--a2-seed-offset 100000] [--strict-cache] [--out ab.jsonl]
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import threading
import time
from typing import Any
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8188"
DEFAULT_SEEDS = (1001, 1002, 1003)
SMI_FIELDS = (
    "clocks.sm,power.draw,utilization.gpu,temperature.gpu,clocks_throttle_reasons.active"
)
POWER_CAP_BIT = 0x4  # nvidia-smi software power cap bit


class CacheIntegrityError(RuntimeError):
    """Raised when --strict-cache detects a sampler or asymmetric encoder cache hit."""


def parse_smi_line(line: str) -> tuple[float, float, float, float, int] | None:
    """Parse one CSV line from ``nvidia-smi`` into ``(clock_mhz, power_w, util_pct, temp_c, mask)``."""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 5:
        return None
    try:
        return (
            float(parts[0]),
            float(parts[1]),
            float(parts[2]),
            float(parts[3]),
            int(parts[4], 16),
        )
    except ValueError:
        return None


def summarize_smi_samples(
    rows: list[tuple[float, float, float, float, int]],
    *,
    busy_util_min: float = 90.0,
) -> dict[str, Any]:
    """Summarize ``nvidia-smi`` samples, filtering clock/power/cap stats to busy GPU samples."""
    busy = [r for r in rows if r[2] >= busy_util_min]
    out: dict[str, Any] = {"samples": len(rows), "busy_samples": len(busy)}
    if busy:
        out.update(
            {
                "clock_mhz": round(statistics.median(r[0] for r in busy), 1),
                "power_w": round(statistics.median(r[1] for r in busy), 2),
                "temp_c": round(statistics.median(r[3] for r in busy), 1),
                "power_capped_share": round(
                    sum(1 for r in busy if (r[4] & POWER_CAP_BIT) != 0) / len(busy), 3
                ),
            }
        )
    return out


class SmiSampler:
    """Background ``nvidia-smi`` poller; degrades to an empty no-op if ``nvidia-smi`` is absent."""

    def __init__(self, index: int = 0, interval_ms: int = 100, enabled: bool = True) -> None:
        self.enabled = enabled and (shutil.which("nvidia-smi") is not None)
        self.cmd = [
            "nvidia-smi",
            "-i",
            str(index),
            f"--query-gpu={SMI_FIELDS}",
            "--format=csv,noheader,nounits",
            "-lms",
            str(interval_ms),
        ]
        self.rows: list[tuple[float, float, float, float, int]] = []
        self.proc: subprocess.Popen[str] | None = None
        self.thread: threading.Thread | None = None

    def __enter__(self) -> "SmiSampler":
        if not self.enabled:
            return self
        try:
            self.proc = subprocess.Popen(
                self.cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
            )
        except OSError:
            self.enabled = False
            return self
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()
        return self

    def _read(self) -> None:
        if self.proc is None or self.proc.stdout is None:
            return
        for line in self.proc.stdout:
            parsed = parse_smi_line(line)
            if parsed is not None:
                self.rows.append(parsed)

    def __exit__(self, *exc: object) -> None:
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.thread is not None:
            self.thread.join(timeout=5)

    def summary(self) -> dict[str, Any]:
        return {"available": self.enabled, **summarize_smi_samples(self.rows)}


def classify_workflow_nodes(
    workflow: dict[str, Any],
    *,
    sampler_nodes: list[str] | None = None,
    encoder_nodes: list[str] | None = None,
) -> tuple[set[str], set[str]]:
    """Identify sampler node IDs and text-encoder node IDs in a ComfyUI API workflow."""
    samplers: set[str] = {str(n) for n in (sampler_nodes or [])}
    encoders: set[str] = {str(n) for n in (encoder_nodes or [])}

    for node_id, spec in workflow.items():
        if not isinstance(spec, dict):
            continue
        nid = str(node_id)
        cls_name = str(spec.get("class_type", ""))
        inputs = spec.get("inputs", {})
        if not isinstance(inputs, dict):
            inputs = {}
        if not sampler_nodes:
            if "Sampler" in cls_name or "seed" in inputs or "noise_seed" in inputs:
                samplers.add(nid)
        if not encoder_nodes:
            if "TextEncode" in cls_name or cls_name in ("CLIPLoader", "DualCLIPLoader"):
                encoders.add(nid)
    return samplers, encoders


def inject_seed(
    workflow: dict[str, Any], seed: int, *, seed_nodes: list[str] | None = None
) -> dict[str, Any]:
    """Return a deep copy of ``workflow`` with ``seed`` / ``noise_seed`` updated."""
    patched = copy.deepcopy(workflow)
    targets = {str(n) for n in seed_nodes} if seed_nodes else None
    updated = 0
    for node_id, spec in patched.items():
        if not isinstance(spec, dict):
            continue
        if targets is not None and str(node_id) not in targets:
            continue
        inputs = spec.get("inputs")
        if not isinstance(inputs, dict):
            continue
        if "seed" in inputs:
            inputs["seed"] = int(seed)
            updated += 1
        if "noise_seed" in inputs:
            inputs["noise_seed"] = int(seed)
            updated += 1
    if updated == 0:
        raise ValueError(
            "No 'seed' or 'noise_seed' input found in workflow; pass --seed-node with a sampler ID"
        )
    return patched


def build_interleaved_schedule(
    arms: list[str],
    seeds: list[int],
    *,
    order: str = "aba",
    warmup: int = 1,
    a2_seed_offset: int = 0,
    warmup_seed_base: int = 900000,
) -> list[dict[str, Any]]:
    """Build a warm-up + interleaved ``A-B-A`` or ``ABBA`` run schedule.

    - ``aba``: for each seed ``s``, runs ``A1(s) -> B(s) [-> other arms(s)] -> A2(s + a2_seed_offset)``.
    - ``abba``: alternates forward and reverse arm order across consecutive seeds
      (``s0: A, B; s1: B, A; s2: A, B ...``) so every seed runs once per arm with zero duplicate
      ``(arm, seed)`` submissions.
    """
    if len(arms) < 2:
        raise ValueError("At least two arms are required for an interleaved A/B schedule")
    if not seeds:
        raise ValueError("At least one seed is required")
    if order not in ("aba", "abba"):
        raise ValueError(f"Unsupported schedule order {order!r}; expected 'aba' or 'abba'")

    schedule: list[dict[str, Any]] = []
    for w_round in range(max(0, warmup)):
        for a_idx, arm in enumerate(arms):
            schedule.append(
                {
                    "index": len(schedule),
                    "arm": arm,
                    "slot": f"{arm}_warmup_{w_round + 1}",
                    "seed": warmup_seed_base + w_round * 100 + a_idx,
                    "base_seed": warmup_seed_base + w_round * 100,
                    "warmup": True,
                }
            )

    primary = arms[0]
    others = arms[1:]

    if order == "aba":
        for seed in seeds:
            schedule.append(
                {
                    "index": len(schedule),
                    "arm": primary,
                    "slot": f"{primary}_1",
                    "seed": int(seed),
                    "base_seed": int(seed),
                    "warmup": False,
                }
            )
            for arm in others:
                schedule.append(
                    {
                        "index": len(schedule),
                        "arm": arm,
                        "slot": arm,
                        "seed": int(seed),
                        "base_seed": int(seed),
                        "warmup": False,
                    }
                )
            schedule.append(
                {
                    "index": len(schedule),
                    "arm": primary,
                    "slot": f"{primary}_2",
                    "seed": int(seed) + int(a2_seed_offset),
                    "base_seed": int(seed),
                    "warmup": False,
                }
            )
    else:
        for s_idx, seed in enumerate(seeds):
            seq = arms if (s_idx % 2 == 0) else list(reversed(arms))
            for arm in seq:
                schedule.append(
                    {
                        "index": len(schedule),
                        "arm": arm,
                        "slot": arm,
                        "seed": int(seed),
                        "base_seed": int(seed),
                        "warmup": False,
                    }
                )
    return schedule


def parse_execution_telemetry(
    workflow: dict[str, Any],
    history_entry: dict[str, Any] | None = None,
    ws_events: list[dict[str, Any]] | None = None,
    *,
    sampler_nodes: list[str] | None = None,
    encoder_nodes: list[str] | None = None,
) -> dict[str, Any]:
    """Extract ComfyUI execution span, cached nodes, and sampler/encoder cache flags."""
    samplers, encoders = classify_workflow_nodes(
        workflow, sampler_nodes=sampler_nodes, encoder_nodes=encoder_nodes
    )
    cached_nodes: set[str] = set()
    executed_nodes: set[str] = set()
    saw_executing_events = False
    t_start_ms: float | None = None
    t_end_ms: float | None = None

    if isinstance(history_entry, dict):
        status = history_entry.get("status", {})
        messages = status.get("messages", []) if isinstance(status, dict) else []
        for msg in messages:
            if not isinstance(msg, (list, tuple)) or len(msg) < 2:
                continue
            mtype, payload = msg[0], msg[1]
            if not isinstance(payload, dict):
                continue
            if mtype == "execution_start" and "timestamp" in payload:
                t_start_ms = float(payload["timestamp"])
            elif mtype == "execution_success" and "timestamp" in payload:
                t_end_ms = float(payload["timestamp"])
            elif mtype in ("execution_cached", "cached"):
                for nid in payload.get("nodes", []) or []:
                    cached_nodes.add(str(nid))
            elif mtype == "executing":
                saw_executing_events = True
                if payload.get("node") is not None:
                    executed_nodes.add(str(payload["node"]))

    for ev in ws_events or []:
        if not isinstance(ev, dict):
            continue
        etype = ev.get("type")
        data = ev.get("data", {})
        if not isinstance(data, dict):
            continue
        if etype in ("execution_cached", "cached"):
            for nid in data.get("nodes", []) or []:
                cached_nodes.add(str(nid))
        elif etype == "executing":
            saw_executing_events = True
            if data.get("node") is not None:
                executed_nodes.add(str(data["node"]))

    cached_samplers = sorted(samplers & cached_nodes)
    if saw_executing_events and samplers:
        for s_nid in sorted(samplers - executed_nodes):
            if s_nid not in cached_samplers:
                cached_samplers.append(s_nid)

    # Whole-graph cache hit on older ComfyUI builds returns empty messages or zero span.
    whole_graph_cached = False
    if isinstance(history_entry, dict):
        status = history_entry.get("status", {})
        messages = status.get("messages", []) if isinstance(status, dict) else []
        if status.get("completed") is True and not messages and samplers:
            whole_graph_cached = True
            cached_samplers = sorted(samplers)

    cached_encoders = sorted(encoders & cached_nodes)
    if not encoders:
        encoder_cache_state = "no_encoders"
    elif len(cached_encoders) == len(encoders):
        encoder_cache_state = "all_cached"
    elif len(cached_encoders) == 0:
        encoder_cache_state = "none_cached"
    else:
        encoder_cache_state = "partial_cached"

    exec_s: float | None = None
    if t_start_ms is not None and t_end_ms is not None and t_end_ms >= t_start_ms:
        exec_s = round((t_end_ms - t_start_ms) / 1000.0, 4)

    return {
        "exec_s": exec_s,
        "sampler_nodes": sorted(samplers),
        "encoder_nodes": sorted(encoders),
        "cached_nodes": sorted(cached_nodes),
        "cached_samplers": cached_samplers,
        "sampler_cached": bool(cached_samplers) or whole_graph_cached,
        "cached_encoders": cached_encoders,
        "encoder_cache_state": encoder_cache_state,
    }


def verify_strict_cache(records: list[dict[str, Any]]) -> None:
    """Fail closed if timed runs show sampler cache hits or asymmetric encoder caching."""
    timed = [r for r in records if not r.get("warmup", False)]
    for rec in timed:
        if rec.get("sampler_cached"):
            raise CacheIntegrityError(
                f"Sampler cache hit in timed run slot={rec.get('slot')} arm={rec.get('arm')} "
                f"seed={rec.get('seed')} cached_samplers={rec.get('cached_samplers')} "
                "(pass --a2-seed-offset or change seeds so every timed run executes the sampler)"
            )

    by_base_seed: dict[Any, list[dict[str, Any]]] = {}
    for rec in timed:
        key = rec.get("base_seed", rec.get("seed"))
        by_base_seed.setdefault(key, []).append(rec)

    for base_seed, group in by_base_seed.items():
        with_enc = [r for r in group if r.get("encoder_cache_state") != "no_encoders"]
        states = {r.get("encoder_cache_state") for r in with_enc}
        if len(states) > 1 or "partial_cached" in states:
            detail = ", ".join(
                f"{r.get('slot')}:{r.get('encoder_cache_state')}" for r in with_enc
            )
            raise CacheIntegrityError(
                f"Asymmetric text-encoder cache state across arms on base_seed={base_seed}: "
                f"{detail} (warm up every arm's prompt first or include text encoding symmetrically)"
            )

    all_with_enc = [r for r in timed if r.get("encoder_cache_state") != "no_encoders"]
    arm_states: dict[str, set[str]] = {}
    for rec in all_with_enc:
        arm_states.setdefault(str(rec.get("arm")), set()).add(str(rec.get("encoder_cache_state")))
    distinct_union = set().union(*arm_states.values()) if arm_states else set()
    if len(distinct_union) > 1:
        detail = ", ".join(f"{arm}:{sorted(st)}" for arm, st in sorted(arm_states.items()))
        raise CacheIntegrityError(
            f"Asymmetric or drifting text-encoder cache state across timed runs: {detail}"
        )


def compute_iqr(values: list[float]) -> float:
    """Compute interquartile range (Q3 - Q1) for 1+ numeric samples."""
    n = len(values)
    if n < 2:
        return 0.0
    ordered = sorted(values)
    if n >= 4:
        q1, _, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
        return round(q3 - q1, 4)
    return round(ordered[-1] - ordered[0], 4)


def summarize_timings(
    records: list[dict[str, Any]], *, control_arm: str | None = None
) -> dict[str, Any]:
    """Summarize warm-discarded median, IQR, min/max, speedup vs control, and A1/A2 drift."""
    timed = [r for r in records if not r.get("warmup", False)]
    arms_order: list[str] = []
    for rec in timed:
        arm = str(rec["arm"])
        if arm not in arms_order:
            arms_order.append(arm)

    if control_arm is None and arms_order:
        control_arm = arms_order[0]

    arm_stats: dict[str, dict[str, Any]] = {}
    for arm in arms_order:
        rows = [r for r in timed if str(r["arm"]) == arm]
        exec_vals = [
            float(r["exec_s"] if r.get("exec_s") is not None else r["wall_s"]) for r in rows
        ]
        wall_vals = [float(r["wall_s"]) for r in rows]
        med = statistics.median(exec_vals)
        arm_stats[arm] = {
            "n": len(rows),
            "median_s": round(med, 4),
            "iqr_s": compute_iqr(exec_vals),
            "min_s": round(min(exec_vals), 4),
            "max_s": round(max(exec_vals), 4),
            "spread_pct": round(((max(exec_vals) - min(exec_vals)) / med) * 100.0, 2)
            if med > 0
            else 0.0,
            "wall_median_s": round(statistics.median(wall_vals), 4),
        }

    ctl_med = arm_stats.get(control_arm or "", {}).get("median_s")
    if ctl_med and ctl_med > 0:
        for arm, st in arm_stats.items():
            st["speedup_vs_control"] = (
                round(ctl_med / st["median_s"], 4) if st["median_s"] > 0 else None
            )

    bracket_drift_pct: float | None = None
    if control_arm:
        slot1 = [
            float(r["exec_s"] if r.get("exec_s") is not None else r["wall_s"])
            for r in timed
            if r.get("slot") == f"{control_arm}_1"
        ]
        slot2 = [
            float(r["exec_s"] if r.get("exec_s") is not None else r["wall_s"])
            for r in timed
            if r.get("slot") == f"{control_arm}_2"
        ]
        if slot1 and slot2:
            m1, m2 = statistics.median(slot1), statistics.median(slot2)
            if m1 > 0:
                bracket_drift_pct = round(abs(m2 - m1) / m1 * 100.0, 2)

    return {
        "control_arm": control_arm,
        "timed_runs": len(timed),
        "discarded_warmups": sum(1 for r in records if r.get("warmup", False)),
        "arms": arm_stats,
        "control_bracket_drift_pct": bracket_drift_pct,
    }


def http_json(
    base_url: str, path: str, payload: dict[str, Any] | None = None, *, timeout_s: float = 60.0
) -> Any:
    url = base_url.rstrip("/") + path
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Expect": ""},
        )
    else:
        req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def submit_and_wait(
    base_url: str,
    workflow: dict[str, Any],
    *,
    timeout_s: float = 300.0,
    poll_interval_s: float = 0.2,
    sampler_nodes: list[str] | None = None,
    encoder_nodes: list[str] | None = None,
    smi_index: int = 0,
    smi_interval_ms: int = 100,
    enable_smi: bool = True,
) -> dict[str, Any]:
    """Submit ``workflow`` without ``client_id`` and poll ``/history/<prompt_id>`` to completion."""
    with SmiSampler(index=smi_index, interval_ms=smi_interval_ms, enabled=enable_smi) as smi:
        t0 = time.perf_counter()
        resp = http_json(base_url, "/prompt", {"prompt": workflow}, timeout_s=timeout_s)
        prompt_id = resp.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI /prompt returned no prompt_id: {resp!r}")

        deadline = time.perf_counter() + timeout_s
        history_entry: dict[str, Any] | None = None
        while time.perf_counter() < deadline:
            hist = http_json(base_url, f"/history/{prompt_id}", timeout_s=timeout_s)
            if isinstance(hist, dict) and prompt_id in hist:
                history_entry = hist[prompt_id]
                break
            time.sleep(poll_interval_s)
        wall_s = round(time.perf_counter() - t0, 4)

    if history_entry is None:
        raise TimeoutError(f"Timed out waiting for prompt_id={prompt_id} after {timeout_s}s")
    status = history_entry.get("status", {})
    if isinstance(status, dict) and status.get("status_str") == "error":
        raise RuntimeError(f"ComfyUI execution error for {prompt_id}: {json.dumps(status)[:1000]}")

    telemetry = parse_execution_telemetry(
        workflow,
        history_entry,
        sampler_nodes=sampler_nodes,
        encoder_nodes=encoder_nodes,
    )
    return {
        "prompt_id": prompt_id,
        "wall_s": wall_s,
        **telemetry,
        "smi": smi.summary(),
    }


def _parse_arm_arg(text: str) -> tuple[str, Path]:
    name, sep, raw_path = text.partition("=")
    if not sep or not name.strip() or not raw_path.strip():
        raise argparse.ArgumentTypeError(f"Expected NAME=WORKFLOW.json, got {text!r}")
    return name.strip(), Path(raw_path.strip())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--url", default=DEFAULT_URL, help=f"ComfyUI base URL (default {DEFAULT_URL})")
    ap.add_argument("--control", type=Path, help="Control arm (A) ComfyUI API workflow JSON")
    ap.add_argument("--candidate", type=Path, help="Candidate arm (B) ComfyUI API workflow JSON")
    ap.add_argument("--off", type=Path, help="Optional explicit toggle-off arm workflow JSON")
    ap.add_argument(
        "--arm",
        type=_parse_arm_arg,
        action="append",
        metavar="NAME=FILE",
        help="Named arm workflow JSON (repeatable; alternative to --control/--candidate)",
    )
    ap.add_argument("--order", choices=("aba", "abba"), default="aba", help="Interleaving order")
    ap.add_argument(
        "--seed",
        type=int,
        action="append",
        help="Seed to run in every arm (repeatable; default: 1001, 1002, 1003)",
    )
    ap.add_argument(
        "--allow-fewer-seeds",
        action="store_true",
        help="Allow fewer than 3 seeds for smoke runs",
    )
    ap.add_argument(
        "--a2-seed-offset",
        type=int,
        default=0,
        help="Offset added to A_2 seeds in aba mode to avoid full-graph cache hits",
    )
    ap.add_argument("--warmup", type=int, default=1, help="Warm-up runs per arm to discard (default 1)")
    ap.add_argument("--seed-node", action="append", help="Explicit node ID(s) carrying seed/noise_seed")
    ap.add_argument("--sampler-node", action="append", help="Explicit sampler node ID(s)")
    ap.add_argument("--encoder-node", action="append", help="Explicit text-encoder node ID(s)")
    ap.add_argument(
        "--strict-cache",
        action="store_true",
        help="Fail closed (exit 1) on sampler cache hits or asymmetric encoder caching",
    )
    ap.add_argument("--timeout", type=float, default=300.0, help="Per-prompt timeout in seconds")
    ap.add_argument("--poll-ms", type=int, default=200, help="History poll interval in milliseconds")
    ap.add_argument("--smi-index", type=int, default=0, help="nvidia-smi GPU index (default 0)")
    ap.add_argument("--smi-interval-ms", type=int, default=100, help="nvidia-smi interval in ms")
    ap.add_argument("--no-smi", action="store_true", help="Disable background nvidia-smi sampling")
    ap.add_argument("--dry-run", action="store_true", help="Print interleaved schedule and exit")
    ap.add_argument("--out", type=Path, help="Write per-run and summary JSONL records to FILE")
    args = ap.parse_args(argv)

    arm_files: list[tuple[str, Path]] = []
    if args.control:
        arm_files.append(("A", args.control))
    if args.candidate:
        arm_files.append(("B", args.candidate))
    if args.off:
        arm_files.append(("Off", args.off))
    if args.arm:
        arm_files.extend(args.arm)
    if len(arm_files) < 2:
        print(
            "comfy_ab_harness: provide --control and --candidate (or at least two --arm NAME=FILE)",
            file=sys.stderr,
        )
        return 2

    seeds = args.seed if args.seed else list(DEFAULT_SEEDS)
    if len(seeds) < 3 and not args.allow_fewer_seeds:
        print(
            f"comfy_ab_harness: need at least 3 seeds (got {len(seeds)}); pass --allow-fewer-seeds for smoke",
            file=sys.stderr,
        )
        return 2

    workflows: dict[str, dict[str, Any]] = {}
    for name, path in arm_files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"comfy_ab_harness: cannot load {path}: {exc}", file=sys.stderr)
            return 2
        if not isinstance(doc, dict):
            print(f"comfy_ab_harness: {path} is not a ComfyUI API prompt dict", file=sys.stderr)
            return 2
        workflows[name] = doc

    try:
        schedule = build_interleaved_schedule(
            [name for name, _ in arm_files],
            seeds,
            order=args.order,
            warmup=args.warmup,
            a2_seed_offset=args.a2_seed_offset,
        )
        for item in schedule:
            inject_seed(workflows[item["arm"]], item["seed"], seed_nodes=args.seed_node)
    except ValueError as exc:
        print(f"comfy_ab_harness: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        for item in schedule:
            print(json.dumps({"event": "plan", **item}))
        return 0

    out_fp = open(args.out, "w", encoding="utf-8") if args.out else None
    records: list[dict[str, Any]] = []
    try:
        for item in schedule:
            wf = inject_seed(workflows[item["arm"]], item["seed"], seed_nodes=args.seed_node)
            res = submit_and_wait(
                args.url,
                wf,
                timeout_s=args.timeout,
                poll_interval_s=max(0.01, args.poll_ms / 1000.0),
                sampler_nodes=args.sampler_node,
                encoder_nodes=args.encoder_node,
                smi_index=args.smi_index,
                smi_interval_ms=args.smi_interval_ms,
                enable_smi=not args.no_smi,
            )
            rec = {"event": "run", **item, **res}
            records.append(rec)
            if out_fp is not None:
                out_fp.write(json.dumps(rec) + "\n")
                out_fp.flush()
            tag = "warmup" if item["warmup"] else "timed"
            t_disp = res["exec_s"] if res["exec_s"] is not None else res["wall_s"]
            print(
                f"[{item['index']:02d}] {tag:6s} slot={item['slot']:12s} seed={item['seed']} "
                f"exec={t_disp:.4f}s wall={res['wall_s']:.4f}s "
                f"sampler_cached={res['sampler_cached']} enc={res['encoder_cache_state']}"
            )

        summary = {
            "event": "summary",
            "order": args.order,
            "strict_cache": args.strict_cache,
            **summarize_timings(records, control_arm=arm_files[0][0]),
        }
        if args.strict_cache:
            verify_strict_cache(records)
        if out_fp is not None:
            out_fp.write(json.dumps(summary) + "\n")
            out_fp.flush()
        print(json.dumps(summary))
    except CacheIntegrityError as exc:
        err_rec = {"event": "strict_cache_error", "error": str(exc)}
        if out_fp is not None:
            out_fp.write(json.dumps(err_rec) + "\n")
            out_fp.flush()
        print(f"comfy_ab_harness: STRICT CACHE FAIL: {exc}", file=sys.stderr)
        return 1
    except (OSError, urllib.error.URLError, RuntimeError, TimeoutError) as exc:
        print(f"comfy_ab_harness: {exc}", file=sys.stderr)
        return 2
    finally:
        if out_fp is not None:
            out_fp.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
