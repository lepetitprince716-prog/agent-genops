#!/usr/bin/env python3
"""Strict schema, graph-integrity, prompt-resolvability, and anti-lag validator for OmniStudio Workbench."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BANNED_LAG_TYPES = frozenset(
    {
        "Anything Everywhere",
        "Anything Everywhere?",
        "Anything Everywhere3",
        "Seed Everywhere",
        "Prompts Everywhere",
    }
)

PREVIEW_TYPES = frozenset({"PreviewImage", "Image Comparer (rgthree)", "PreviewAny", "HDRPreviewKJ"})
ANY_SWITCH_TYPES = frozenset({"Any Switch (rgthree)"})
INDEX_SWITCH_TYPES = frozenset({"easy anythingIndexSwitch"})


@dataclass(frozen=True)
class ValidationFinding:
    code: str
    severity: str  # "ERROR" | "WARN"
    message: str


def _boxes_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def _bypass_input_slot(node: dict[str, Any], out_slot: int) -> int | None:
    """Resolve ComfyUI bypass passthrough slot: exact name match first, else first type match."""
    outputs = node.get("outputs") or []
    inputs = node.get("inputs") or []
    if out_slot < 0 or out_slot >= len(outputs):
        return None
    out = outputs[out_slot]
    out_name = out.get("name")
    out_type = out.get("type")
    for idx, inp in enumerate(inputs):
        if out_name and inp.get("name") == out_name and (
            inp.get("type") == out_type or inp.get("type") == "*" or out_type == "*"
        ):
            return idx
    for idx, inp in enumerate(inputs):
        itype = inp.get("type")
        if itype == out_type or itype == "*" or out_type == "*":
            return idx
    return None


def _check_prompt_resolvability(
    doc: dict[str, Any],
    sg_by_id: dict[str, dict[str, Any]],
    findings: list[ValidationFinding],
) -> None:
    """Simulate ComfyUI graphToPrompt resolvability across root and active subgraphs.

    Every active (mode == 0) node on root and inside every active subgraph must have:
    - Any Switch (rgthree): at least one connected input that resolves to a live producer.
    - easy anythingIndexSwitch: its selected index input (value<index>) resolves to a live producer.
    - All other nodes: every linked input resolves to a live (mode == 0) producer (walking
      through mode == 4 bypassed nodes and failing on mode == 2 muted or dead bypasses).
    """
    root_nodes = {n["id"]: n for n in doc.get("nodes") or []}
    root_links = {lk[0]: lk for lk in doc.get("links") or [] if isinstance(lk, list) and len(lk) == 6}

    def resolve_root_output(nid: Any, oslot: int, seen: set[tuple[Any, int]]) -> tuple[Any, int] | None:
        key = (nid, oslot)
        if key in seen or nid not in root_nodes:
            return None
        seen = seen | {key}
        node = root_nodes[nid]
        mode = node.get("mode", 0)
        if mode == 2:
            return None
        if mode == 4:
            in_idx = _bypass_input_slot(node, oslot)
            if in_idx is None:
                return None
            lid = (node.get("inputs") or [])[in_idx].get("link")
            if lid not in root_links:
                return None
            _, src_id, src_slot, _, _, _ = root_links[lid]
            return resolve_root_output(src_id, src_slot, seen)
        # Active node (mode == 0): if it is an Any Switch, ensure at least one input resolves
        if node["type"] in ANY_SWITCH_TYPES:
            for inp in node.get("inputs") or []:
                lid = inp.get("link")
                if lid in root_links:
                    _, src_id, src_slot, _, _, _ = root_links[lid]
                    if resolve_root_output(src_id, src_slot, seen) is not None:
                        return (nid, oslot)
            return None
        return (nid, oslot)

    # 1. Check every active root node's connected inputs
    for node in root_nodes.values():
        if node.get("mode", 0) != 0:
            continue
        ntype = node["type"]
        if ntype in ANY_SWITCH_TYPES:
            # A cascaded Any Switch feeding only another Any Switch may legally return None when its bank is muted;
            # any Any Switch feeding a non-switch active consumer (or with no downstream) MUST resolve to a live source.
            consumers = [
                root_nodes[lk[3]]
                for lk in root_links.values()
                if lk[1] == node["id"] and lk[3] in root_nodes and root_nodes[lk[3]].get("mode", 0) != 2
            ]
            only_feeds_switches = bool(consumers) and all(c["type"] in ANY_SWITCH_TYPES for c in consumers)
            if only_feeds_switches:
                continue
            resolved_any = False
            for inp in node.get("inputs") or []:
                lid = inp.get("link")
                if lid in root_links:
                    _, src_id, src_slot, _, _, _ = root_links[lid]
                    if resolve_root_output(src_id, src_slot, set()) is not None:
                        resolved_any = True
                        break
            if not resolved_any:
                findings.append(
                    ValidationFinding(
                        "PR01",
                        "ERROR",
                        f"Active root Any Switch #{node['id']} ({node.get('title')}) has no live upstream source",
                    )
                )
            continue

        # Subgraph instance: check internal active nodes with root-resolved boundary availability
        if ntype in sg_by_id:
            boundary_ok: dict[int, bool] = {}
            for idx, inp in enumerate(node.get("inputs") or []):
                lid = inp.get("link")
                if lid in root_links:
                    _, src_id, src_slot, _, _, _ = root_links[lid]
                    boundary_ok[idx] = resolve_root_output(src_id, src_slot, set()) is not None
                else:
                    boundary_ok[idx] = False
            _check_subgraph_resolvability(sg_by_id[ntype], node, boundary_ok, findings)
            continue

        # Regular active root node: every linked input must resolve to a live source
        for inp in node.get("inputs") or []:
            lid = inp.get("link")
            if lid is None:
                continue
            if lid not in root_links:
                findings.append(
                    ValidationFinding("PR02", "ERROR", f"Root node #{node['id']} input {inp['name']} has missing link {lid}")
                )
                continue
            _, src_id, src_slot, _, _, _ = root_links[lid]
            if resolve_root_output(src_id, src_slot, set()) is None:
                findings.append(
                    ValidationFinding(
                        "PR02",
                        "ERROR",
                        f"Active root node #{node['id']} ({node.get('title')}) input '{inp['name']}' resolves to null (muted/unresolvable bypass)",
                    )
                )


def _check_subgraph_resolvability(
    sg: dict[str, Any],
    instance: dict[str, Any],
    boundary_ok: dict[int, bool],
    findings: list[ValidationFinding],
) -> None:
    inodes = {n["id"]: n for n in sg.get("nodes") or []}
    ilinks = {lk["id"]: lk for lk in sg.get("links") or [] if isinstance(lk, dict)}

    def resolve_inner(nid: Any, oslot: int, seen: set[tuple[Any, int]]) -> bool:
        if nid == -10:
            return boundary_ok.get(oslot, False)
        key = (nid, oslot)
        if key in seen or nid not in inodes:
            return False
        seen = seen | {key}
        node = inodes[nid]
        mode = node.get("mode", 0)
        if mode == 2:
            return False
        if mode == 4:
            in_idx = _bypass_input_slot(node, oslot)
            if in_idx is None:
                return False
            lid = (node.get("inputs") or [])[in_idx].get("link")
            if lid not in ilinks:
                return False
            lk = ilinks[lid]
            return resolve_inner(lk["origin_id"], lk["origin_slot"], seen)
        if node["type"] in ANY_SWITCH_TYPES:
            for inp in node.get("inputs") or []:
                lid = inp.get("link")
                if lid in ilinks:
                    lk = ilinks[lid]
                    if resolve_inner(lk["origin_id"], lk["origin_slot"], seen):
                        return True
            return False
        if node["type"] in INDEX_SWITCH_TYPES:
            vals = node.get("widgets_values") or [0]
            sel_idx = int(vals[0]) if isinstance(vals, list) and vals else 0
            inps = node.get("inputs") or []
            if 0 <= sel_idx < len(inps):
                lid = inps[sel_idx].get("link")
                if lid in ilinks:
                    lk = ilinks[lid]
                    return resolve_inner(lk["origin_id"], lk["origin_slot"], seen)
            return False
        return True

    for inode in inodes.values():
        if inode.get("mode", 0) != 0:
            continue
        ntype = inode["type"]
        if ntype in ANY_SWITCH_TYPES:
            if not any(
                inp.get("link") in ilinks
                and resolve_inner(ilinks[inp["link"]]["origin_id"], ilinks[inp["link"]]["origin_slot"], set())
                for inp in inode.get("inputs") or []
            ):
                findings.append(
                    ValidationFinding(
                        "PR03",
                        "ERROR",
                        f"Subgraph {sg['name']} (inst #{instance['id']}): Any Switch #{inode['id']} has no resolvable input",
                    )
                )
            continue
        if ntype in INDEX_SWITCH_TYPES:
            vals = inode.get("widgets_values") or [0]
            sel_idx = int(vals[0]) if isinstance(vals, list) and vals else 0
            inps = inode.get("inputs") or []
            ok = False
            if 0 <= sel_idx < len(inps):
                lid = inps[sel_idx].get("link")
                if lid in ilinks:
                    ok = resolve_inner(ilinks[lid]["origin_id"], ilinks[lid]["origin_slot"], set())
            if not ok:
                findings.append(
                    ValidationFinding(
                        "PR03",
                        "ERROR",
                        f"Subgraph {sg['name']} (inst #{instance['id']}): Index Switch #{inode['id']} selected index {sel_idx} unresolved",
                    )
                )
            continue
        for inp in inode.get("inputs") or []:
            lid = inp.get("link")
            if lid is None:
                continue
            if lid not in ilinks:
                findings.append(
                    ValidationFinding("PR04", "ERROR", f"Subgraph {sg['name']}: node #{inode['id']} missing link {lid}")
                )
                continue
            lk = ilinks[lid]
            if not resolve_inner(lk["origin_id"], lk["origin_slot"], set()):
                findings.append(
                    ValidationFinding(
                        "PR04",
                        "ERROR",
                        f"Subgraph {sg['name']} (inst #{instance['id']}): active node #{inode['id']} ({inode.get('title')}) "
                        f"input '{inp['name']}' resolves to null",
                    )
                )


def validate_workbench(doc: dict[str, Any]) -> tuple[list[ValidationFinding], dict[str, Any]]:
    findings: list[ValidationFinding] = []

    if doc.get("version") != 0.4:
        findings.append(ValidationFinding("W01", "ERROR", f"Root version must be 0.4, got {doc.get('version')!r}"))

    nodes = doc.get("nodes") or []
    links = doc.get("links") or []
    groups = doc.get("groups") or []
    subgraphs = (doc.get("definitions") or {}).get("subgraphs") or []
    sg_by_id = {sg["id"]: sg for sg in subgraphs if isinstance(sg, dict) and "id" in sg}

    # 1. Root unique node IDs, overlap check, banned UE check, preview budget check
    root_by_id: dict[Any, dict[str, Any]] = {}
    root_boxes: list[tuple[Any, tuple[float, float, float, float]]] = []
    root_previews = 0
    banned_hits: list[str] = []

    for node in nodes:
        nid = node["id"]
        if nid in root_by_id:
            findings.append(ValidationFinding("W02", "ERROR", f"Duplicate root node id {nid}"))
        root_by_id[nid] = node
        x, y = node["pos"]
        w, h = node["size"]
        root_boxes.append((nid, (x, y - 30, w, h + 30)))
        if node["type"] in BANNED_LAG_TYPES:
            banned_hits.append(f"root:{nid}:{node['type']}")
        if node["type"] in PREVIEW_TYPES:
            root_previews += 1

    for i in range(len(root_boxes)):
        for j in range(i + 1, len(root_boxes)):
            if _boxes_overlap(root_boxes[i][1], root_boxes[j][1]):
                findings.append(
                    ValidationFinding("W03", "ERROR", f"Root nodes {root_boxes[i][0]} and {root_boxes[j][0]} overlap")
                )

    if root_previews > 1:
        findings.append(
            ValidationFinding("AL01", "ERROR", f"Root canvas has {root_previews} preview nodes; anti-lag budget is <= 1")
        )

    # 2. Root link integrity
    link_ids: set[int] = set()
    for link in links:
        if not isinstance(link, list) or len(link) != 6:
            findings.append(ValidationFinding("W04", "ERROR", f"Malformed root link tuple: {link!r}"))
            continue
        lid, orig_id, orig_slot, tgt_id, tgt_slot, _ltype = link
        if lid in link_ids:
            findings.append(ValidationFinding("W04", "ERROR", f"Duplicate root link id {lid}"))
        link_ids.add(lid)
        if orig_id not in root_by_id or tgt_id not in root_by_id:
            findings.append(ValidationFinding("W05", "ERROR", f"Dangling root link {lid}: {orig_id} -> {tgt_id}"))
            continue
        src = root_by_id[orig_id]
        dst = root_by_id[tgt_id]
        if orig_slot < 0 or orig_slot >= len(src.get("outputs") or []):
            findings.append(ValidationFinding("W05", "ERROR", f"Root link {lid}: bad origin_slot {orig_slot} on {orig_id}"))
        elif lid not in (src["outputs"][orig_slot].get("links") or []):
            findings.append(ValidationFinding("W05", "ERROR", f"Root link {lid} missing from source node {orig_id} outputs"))
        if tgt_slot < 0 or tgt_slot >= len(dst.get("inputs") or []):
            findings.append(ValidationFinding("W05", "ERROR", f"Root link {lid}: bad target_slot {tgt_slot} on {tgt_id}"))
        elif dst["inputs"][tgt_slot].get("link") != lid:
            findings.append(ValidationFinding("W05", "ERROR", f"Root link {lid} mismatch on target node {tgt_id} inputs"))

    # 3. Subgraph v1 schema, depth == 1 invariant, internal link integrity, internal overlap
    max_depth = 0
    total_internal_nodes = 0
    for sg in subgraphs:
        sg_id = sg["id"]
        max_depth = max(max_depth, 1)
        if sg.get("version") != 1:
            findings.append(ValidationFinding("SG01", "ERROR", f"Subgraph {sg_id} version != 1"))
        if (sg.get("inputNode") or {}).get("id") != -10 or (sg.get("outputNode") or {}).get("id") != -20:
            findings.append(ValidationFinding("SG02", "ERROR", f"Subgraph {sg_id} missing -10/-20 boundary nodes"))

        in_nodes = sg.get("nodes") or []
        in_links = sg.get("links") or []
        total_internal_nodes += len(in_nodes)
        ib_by_id: dict[Any, dict[str, Any]] = {}
        ib_boxes: list[tuple[Any, tuple[float, float, float, float]]] = []

        for inode in in_nodes:
            inid = inode["id"]
            if inid in ib_by_id:
                findings.append(ValidationFinding("SG03", "ERROR", f"Subgraph {sg_id} duplicate node id {inid}"))
            ib_by_id[inid] = inode
            if inode["type"] in sg_by_id:
                max_depth = max(max_depth, 2)
                findings.append(
                    ValidationFinding("AL02", "ERROR", f"Nested subgraph detected inside {sg_id}: node {inid}")
                )
            if inode["type"] in BANNED_LAG_TYPES:
                banned_hits.append(f"{sg_id}:{inid}:{inode['type']}")
            x, y = inode["pos"]
            w, h = inode["size"]
            ib_boxes.append((inid, (x, y - 30, w, h + 30)))

        for i in range(len(ib_boxes)):
            for j in range(i + 1, len(ib_boxes)):
                if _boxes_overlap(ib_boxes[i][1], ib_boxes[j][1]):
                    findings.append(
                        ValidationFinding(
                            "SG04",
                            "ERROR",
                            f"Subgraph {sg['name']}: internal nodes {ib_boxes[i][0]} and {ib_boxes[j][0]} overlap",
                        )
                    )

        sg_in_defs = sg.get("inputs") or []
        sg_out_defs = sg.get("outputs") or []
        seen_in_lids: set[int] = set()
        for sl in in_links:
            if not isinstance(sl, dict):
                findings.append(ValidationFinding("SG05", "ERROR", f"Subgraph {sg_id}: non-object link {sl!r}"))
                continue
            slid = sl["id"]
            if slid in seen_in_lids:
                findings.append(ValidationFinding("SG05", "ERROR", f"Subgraph {sg_id}: duplicate link id {slid}"))
            seen_in_lids.add(slid)
            oid, oslot, tid, tslot = sl["origin_id"], sl["origin_slot"], sl["target_id"], sl["target_slot"]
            if oid == -10:
                if oslot < 0 or oslot >= len(sg_in_defs) or slid not in sg_in_defs[oslot].get("linkIds", []):
                    findings.append(ValidationFinding("SG06", "ERROR", f"Subgraph {sg_id}: input boundary link {slid} inconsistent"))
            elif oid not in ib_by_id:
                findings.append(ValidationFinding("SG06", "ERROR", f"Subgraph {sg_id}: dangling origin {oid}"))
            if tid == -20:
                if tslot < 0 or tslot >= len(sg_out_defs) or slid not in sg_out_defs[tslot].get("linkIds", []):
                    findings.append(ValidationFinding("SG06", "ERROR", f"Subgraph {sg_id}: output boundary link {slid} inconsistent"))
            elif tid not in ib_by_id:
                findings.append(ValidationFinding("SG06", "ERROR", f"Subgraph {sg_id}: dangling target {tid}"))

        for rnode in nodes:
            if rnode["type"] == sg_id:
                if len(rnode.get("inputs") or []) != len(sg_in_defs):
                    findings.append(ValidationFinding("SG07", "ERROR", f"Instance {rnode['id']} input count mismatch"))
                if len(rnode.get("outputs") or []) != len(sg_out_defs):
                    findings.append(ValidationFinding("SG07", "ERROR", f"Instance {rnode['id']} output count mismatch"))
                pws = (rnode.get("properties") or {}).get("proxyWidgets") or []
                wvals = rnode.get("widgets_values") or []
                if len(wvals) != len(pws):
                    findings.append(
                        ValidationFinding(
                            "SG08",
                            "ERROR",
                            f"Instance {rnode['id']} widgets_values len ({len(wvals)}) != proxyWidgets len ({len(pws)})",
                        )
                    )
                for pw in pws:
                    target_id = int(pw[0])
                    if target_id not in ib_by_id:
                        findings.append(ValidationFinding("SG08", "ERROR", f"Instance {rnode['id']} proxyWidget targets missing node {pw}"))

    if banned_hits:
        findings.append(ValidationFinding("AL03", "ERROR", f"Banned Use-Everywhere lag nodes found: {banned_hits}"))

    # 4. Radio Engine Switch & Bypass Slot Uniqueness Check
    engine_instances = [
        n for n in nodes if n["type"] in sg_by_id and sg_by_id[n["type"]].get("extra", {}).get("omnistudio_capsule", "").startswith("e")
    ]
    active_engines = [n for n in engine_instances if n.get("mode", 0) == 0]
    if len(active_engines) != 1:
        findings.append(
            ValidationFinding("SW01", "ERROR", f"Expected exactly 1 active engine by default, found {len(active_engines)}")
        )

    radio_nodes = [
        n
        for n in nodes
        if n["type"] == "Fast Groups Muter (rgthree)" and (n.get("properties") or {}).get("toggleRestriction") == "max one"
    ]
    if not radio_nodes:
        findings.append(ValidationFinding("SW02", "ERROR", "Missing root Fast Groups Muter (rgthree) with toggleRestriction='max one'"))

    for n in nodes:
        if n["type"] in sg_by_id and n.get("mode", 0) == 4:
            in_types = [inp["type"] for inp in n.get("inputs") or []]
            out_types = [out["type"] for out in n.get("outputs") or []]
            for ot in out_types:
                matches = [t for t in in_types if t == ot]
                if len(matches) > 1:
                    findings.append(
                        ValidationFinding(
                            "BY01",
                            "ERROR",
                            f"Bypassed subgraph {n['title']} has ambiguous bypass type {ot} ({len(matches)} matching inputs)",
                        )
                    )

    # 5. Anti-lag DOM reduction gate
    total_nodes = len(nodes) + total_internal_nodes
    dom_reduction_pct = round((1.0 - len(nodes) / max(1, total_nodes)) * 100, 1)
    if dom_reduction_pct < 85.0:
        findings.append(
            ValidationFinding("AL04", "ERROR", f"Root DOM reduction {dom_reduction_pct}% below 85% anti-lag target")
        )

    # 6. Check all ⚡ engine groups match engine instances cleanly
    engine_groups = [g for g in groups if str(g.get("title", "")).startswith("⚡")]
    if len(engine_groups) != len(engine_instances):
        findings.append(
            ValidationFinding(
                "SW03",
                "ERROR",
                f"Engine radio group count ({len(engine_groups)}) != engine subgraph count ({len(engine_instances)})",
            )
        )

    # 7. Hard-Constraint: Full deterministic graphToPrompt prompt-resolvability simulation
    _check_prompt_resolvability(doc, sg_by_id, findings)

    metrics = {
        "total_real_nodes": total_nodes,
        "root_nodes": len(nodes),
        "internal_nodes": total_internal_nodes,
        "subgraphs": len(subgraphs),
        "max_subgraph_depth": max_depth,
        "root_dom_reduction_pct": dom_reduction_pct,
        "root_preview_nodes": root_previews,
        "banned_ue_nodes": len(banned_hits),
        "engine_capsules": len(engine_instances),
        "default_active_engines": len(active_engines),
        "errors": sum(1 for f in findings if f.severity == "ERROR"),
        "warnings": sum(1 for f in findings if f.severity == "WARN"),
    }
    return findings, metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an OmniStudio Workbench UI JSON.")
    parser.add_argument(
        "workflow",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parent / "dist" / "omni_ubisoft_workbench.ui.json",
    )
    args = parser.parse_args(argv)
    doc = json.loads(args.workflow.read_text(encoding="utf-8"))
    findings, metrics = validate_workbench(doc)
    for f in findings:
        print(f"[{f.severity}] {f.code}: {f.message}", file=sys.stderr)
    print(json.dumps(metrics, indent=2))
    return 1 if metrics["errors"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
