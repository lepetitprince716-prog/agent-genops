"""Unit tests for the OmniStudio Ubisoft All-in-One Super Workbench."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any

WORKBENCH_DIR = Path(__file__).resolve().parents[1]
if str(WORKBENCH_DIR) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_DIR))

from build_workbench import (  # noqa: E402
    CUSTOM_NODE_MANIFEST,
    NODE_MODE_ALWAYS,
    NODE_MODE_BYPASS,
    NODE_MODE_NEVER,
    build_workbench,
)
from render_preview import render_capsules_svg, render_root_svg  # noqa: E402
from validate_workbench import validate_workbench  # noqa: E402


def _node_in_group(node: dict[str, Any], group: dict[str, Any]) -> bool:
    gx, gy, gw, gh = group["bounding"]
    nx, ny = node["pos"]
    nw, nh = node["size"]
    cx, cy = nx + nw * 0.5, ny + nh * 0.5
    return gx <= cx <= gx + gw and gy <= cy <= gy + gh


def _simulate_radio_switch(doc: dict[str, Any], target_capsule_key: str) -> dict[str, Any]:
    """Simulate rgthree Fast Groups Muter (toggleRestriction='max one') switching to one engine."""
    cloned = copy.deepcopy(doc)
    sg_by_id = {s["id"]: s for s in cloned["definitions"]["subgraphs"]}
    matched = 0
    for node in cloned["nodes"]:
        sg = sg_by_id.get(node["type"])
        if sg and sg["extra"]["omnistudio_capsule"].startswith("e"):
            if sg["extra"]["omnistudio_capsule"] == target_capsule_key:
                node["mode"] = NODE_MODE_ALWAYS
                matched += 1
            else:
                node["mode"] = NODE_MODE_NEVER
    assert matched == 1, f"Expected to match 1 engine for {target_capsule_key}, got {matched}"
    return cloned


def _simulate_station_group_toggle(doc: dict[str, Any], group_prefix: str, enable: bool) -> dict[str, Any]:
    """Simulate rgthree Fast Groups Bypasser toggling every root node inside a matching 🛠 group."""
    cloned = copy.deepcopy(doc)
    targets = [g for g in cloned["groups"] if str(g.get("title", "")).startswith(group_prefix)]
    assert len(targets) == 1, f"Expected 1 group starting with {group_prefix}, got {len(targets)}"
    group = targets[0]
    touched = 0
    for node in cloned["nodes"]:
        if _node_in_group(node, group):
            node["mode"] = NODE_MODE_ALWAYS if enable else NODE_MODE_BYPASS
            touched += 1
    assert touched >= 1, f"Group {group_prefix} contains no nodes"
    return cloned


def _active_upstream_engines(doc: dict[str, Any]) -> list[str]:
    """Trace which non-muted engine capsules feed the Master Pixel Bridge & Gallery."""
    nodes = {n["id"]: n for n in doc["nodes"]}
    links_by_id = {lk[0]: lk for lk in doc["links"]}
    sg_by_id = {s["id"]: s for s in doc["definitions"]["subgraphs"]}

    save_node = next(n for n in doc["nodes"] if n["type"] == "Save Image (LoraManager)")
    active_engines: list[str] = []
    visited: set[int] = set()

    def walk(nid: int) -> None:
        if nid in visited:
            return
        visited.add(nid)
        node = nodes[nid]
        if node.get("mode", 0) == NODE_MODE_NEVER:
            return
        sg = sg_by_id.get(node["type"])
        if sg and sg["extra"]["omnistudio_capsule"].startswith("e"):
            active_engines.append(sg["extra"]["omnistudio_capsule"])
            return
        for inp in node.get("inputs") or []:
            lid = inp.get("link")
            if lid in links_by_id:
                walk(links_by_id[lid][1])

    walk(save_node["id"])
    return active_engines


class TestUbisoftWorkbench(unittest.TestCase):
    def test_deterministic_build(self) -> None:
        doc1, stats1 = build_workbench()
        doc2, stats2 = build_workbench()
        self.assertEqual(json.dumps(doc1, sort_keys=True), json.dumps(doc2, sort_keys=True))
        self.assertEqual(stats1, stats2)

    def test_dist_artifacts_match_builder_byte_for_byte(self) -> None:
        doc, stats = build_workbench()
        dist_wf = WORKBENCH_DIR / "dist" / "omni_ubisoft_workbench.ui.json"
        dist_stats = WORKBENCH_DIR / "dist" / "workbench_stats.json"
        self.assertTrue(dist_wf.is_file(), "dist/omni_ubisoft_workbench.ui.json must exist")
        self.assertEqual(json.loads(dist_wf.read_text(encoding="utf-8")), doc)
        self.assertEqual(json.loads(dist_stats.read_text(encoding="utf-8")), stats)

    def test_schema_and_anti_lag_invariants(self) -> None:
        doc, stats = build_workbench()
        findings, metrics = validate_workbench(doc)
        self.assertEqual(metrics["errors"], 0, f"Unexpected validation errors: {findings}")
        self.assertEqual(metrics["max_subgraph_depth"], 1)
        self.assertEqual(metrics["banned_ue_nodes"], 0)
        self.assertLessEqual(metrics["root_preview_nodes"], 1)
        self.assertGreaterEqual(metrics["root_dom_reduction_pct"], 85.0)
        self.assertGreaterEqual(metrics["total_real_nodes"], 250)
        self.assertEqual(metrics["engine_capsules"], 18)
        self.assertEqual(stats["production_stations"], 6)
        self.assertGreaterEqual(len(CUSTOM_NODE_MANIFEST), 14)

    def test_all_18_engines_switch_cleanly_without_conflicts(self) -> None:
        doc, stats = build_workbench()
        for eng in stats["engines"]:
            switched = _simulate_radio_switch(doc, eng["id"])
            findings, metrics = validate_workbench(switched)
            self.assertEqual(metrics["errors"], 0, f"Engine {eng['id']} failed validation: {findings}")
            active = _active_upstream_engines(switched)
            self.assertEqual(active, [eng["id"]], f"Expected active engine {[eng['id']]}, got {active}")

    def test_all_7_station_toggles_resolve_cleanly(self) -> None:
        doc, _ = build_workbench()
        stations = ["🛠 S01", "🛠 S02", "🛠 S03", "🛠 S04", "🛠 S05", "🛠 S06", "🛠 S07"]
        # Toggle each station ON and OFF individually
        for prefix in stations:
            for state in (True, False):
                toggled = _simulate_station_group_toggle(doc, prefix, enable=state)
                findings, metrics = validate_workbench(toggled)
                self.assertEqual(
                    metrics["errors"],
                    0,
                    f"Station {prefix} enable={state} failed prompt resolvability: {findings}",
                )
        # Toggle ALL 7 stations ON simultaneously
        all_on = doc
        for prefix in stations:
            all_on = _simulate_station_group_toggle(all_on, prefix, enable=True)
        findings, metrics = validate_workbench(all_on)
        self.assertEqual(metrics["errors"], 0, f"All 7 stations ON failed validation: {findings}")

    def test_svg_renderers_produce_valid_svg(self) -> None:
        doc, _ = build_workbench()
        root_svg = render_root_svg(doc)
        caps_svg = render_capsules_svg(doc)
        self.assertTrue(root_svg.startswith("<svg "))
        self.assertIn("OMNISTUDIO UBISOFT ALL-IN-ONE SUPER WORKBENCH", root_svg)
        self.assertIn("SUBGRAPH CAPSULE", root_svg)
        self.assertTrue(caps_svg.startswith("<svg "))
        self.assertIn("INSIDE THE 1-LEVEL FLAT SUBGRAPH CAPSULES", caps_svg)


if __name__ == "__main__":
    unittest.main()
