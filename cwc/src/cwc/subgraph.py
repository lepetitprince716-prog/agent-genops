"""ComfyUI v0.4 1-level flat Subgraph packing and flattening.

ComfyUI's native Subgraph format (root ``version: 0.4``, ``definitions.subgraphs`` with
entry ``version: 1``, ``inputNode.id = -10``, ``outputNode.id = -20``, and object links)
reduces frontend DOM bloat by encapsulating multi-node stages into single top-level cards.

This module enforces **strict 1-level flat Subgraphs (depth == 1)** to avoid the ComfyUI
frontend's double-configuration cold-load and O(nodes * subgraphs) traversal bottlenecks:

* :func:`flatten_subgraphs` expands active 1-level Subgraph instances back into a flat
  :class:`Canvas` so :func:`cwc.prompt.from_canvas.canvas_to_prompt` can export exact API
  prompts and verify 100% round-trip equivalence.
* :func:`pack_subgraphs` packs eligible non-cockpit / non-output groups of a laid-out
  :class:`Canvas` into deterministic 1-level Subgraphs, promoting key widgets via
  ``proxyWidgets`` and computing anti-lag DOM reduction metrics.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from typing import Any

from cwc.canvas.geometry import GRID, TITLE_HEIGHT, Rect, snap_up
from cwc.canvas.model import Canvas, Node, NodeMode
from cwc.nodedefs.types import WidgetKind
from cwc.prompt.slots import DefLookup

SUBGRAPH_INPUT_ID = -10
SUBGRAPH_OUTPUT_ID = -20
SUBGRAPH_NAMESPACE = uuid.UUID("c1c05b62-3f9a-4c87-a10d-5a0c12345678")
SUBGRAPH_CARD_MIN_W = 300
SUBGRAPH_CARD_MIN_H = 140
SUBGRAPH_PADDING = 40
GROUP_HEADER_PAD = 60


@dataclass(frozen=True)
class PackResult:
    """Result of packing eligible canvas groups into 1-level native v0.4 Subgraphs."""

    canvas: Canvas
    packed_groups: tuple[str, ...]
    subgraph_count: int
    root_nodes_before: int
    root_nodes_after: int
    internal_nodes: int
    root_links_before: int
    root_links_after: int
    max_depth: int
    root_dom_reduction_pct: float
    id_map: dict[str, str]  # flattened node key -> original flat node key (for equivalence checks)

    def metrics(self) -> dict[str, Any]:
        return {
            "packed_groups": list(self.packed_groups),
            "subgraph_count": self.subgraph_count,
            "max_depth": self.max_depth,
            "root_nodes_before": self.root_nodes_before,
            "root_nodes_after": self.root_nodes_after,
            "internal_nodes": self.internal_nodes,
            "root_links_before": self.root_links_before,
            "root_links_after": self.root_links_after,
            "root_dom_reduction_pct": self.root_dom_reduction_pct,
        }


def subgraph_definitions(canvas: Canvas) -> dict[str, dict[str, Any]]:
    """Map subgraph UUID -> raw definition dict from ``definitions.subgraphs``."""
    definitions = canvas.raw.get("definitions") or {}
    raw_list = definitions.get("subgraphs") or []
    out: dict[str, dict[str, Any]] = {}
    for entry in raw_list:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"]:
            out[entry["id"]] = entry
    return out


def _stable_uuid(seed: str) -> str:
    return str(uuid.uuid5(SUBGRAPH_NAMESPACE, seed))


def _node_in_group(node: Node, rect: Rect) -> bool:
    cx = node.pos[0] + node.size[0] * 0.5
    cy = node.pos[1] + node.size[1] * 0.5
    return rect.x <= cx <= rect.x + rect.w and rect.y <= cy <= rect.y + rect.h


def _allocate_int_id(used: set[int], start: int = 1) -> int:
    candidate = start
    while candidate in used:
        candidate += 1
    used.add(candidate)
    return candidate


def _extract_proxy_widgets(
    inner_nodes: list[dict[str, Any]],
    defs: DefLookup,
    max_proxies: int = 4,
) -> tuple[list[list[str]], list[Any]]:
    """Promote up to ``max_proxies`` representative value widgets from inner nodes to the parent card."""
    proxies: list[list[str]] = []
    values: list[Any] = []
    for raw in inner_nodes:
        if len(proxies) >= max_proxies:
            break
        nodedef = defs.get(raw["type"])
        if nodedef is None:
            continue
        wvals = raw.get("widgets_values")
        if not isinstance(wvals, list):
            continue
        for idx, widget in enumerate(nodedef.widgets):
            if widget.kind is not WidgetKind.VALUE or not widget.name:
                continue
            if idx >= len(wvals):
                continue
            proxies.append([str(raw["id"]), widget.name])
            values.append(wvals[idx])
            break
    return proxies, values


def pack_subgraphs(
    canvas: Canvas,
    defs: DefLookup,
    *,
    min_group_nodes: int = 2,
    skip_group_indices: tuple[int, ...] = (),
    skip_output_groups: bool = True,
) -> PackResult:
    """Pack eligible multi-node groups of ``canvas`` into strict 1-level native v0.4 Subgraphs.

    Groups skipped:
    - Any group index in ``skip_group_indices`` (typically the Cockpit / Controls frame).
    - Any group containing an output node when ``skip_output_groups`` is True (keeps Gallery on root).
    - Any group with fewer than ``min_group_nodes`` member nodes, or already containing a subgraph instance.
    - Any group whose member nodes overlap another already-selected group (no ambiguous ownership).
    """
    existing_sgs = subgraph_definitions(canvas)
    root_nodes_before = len(canvas.nodes)
    root_links_before = len(canvas.links)
    raw_doc = canvas.to_json()

    groups = canvas.groups
    all_nodes = canvas.nodes
    skip_set = set(skip_group_indices)

    # Identify eligible disjoint groups
    claimed_keys: set[str] = set()
    pack_plan: list[tuple[int, str, Rect, Any, list[Node]]] = []

    for g_idx, group in enumerate(groups):
        if g_idx in skip_set:
            continue
        members = [n for n in all_nodes if _node_in_group(n, group.bounding)]
        if len(members) < min_group_nodes:
            continue
        if any(n.key in claimed_keys for n in members):
            continue
        if any(n.type in existing_sgs for n in members):
            continue
        if skip_output_groups and any((nd := defs.get(n.type)) is not None and nd.output_node for n in members):
            continue
        # Ensure bypass safety when all members are bypassed: no ambiguous duplicate input/output types
        all_bypassed = all(n.mode == NodeMode.BYPASS for n in members)
        member_keys = {n.key for n in members}
        if all_bypassed:
            # Verify external outputs map unambiguously to external inputs by type
            in_types = [
                lk.type for lk in canvas.links if str(lk.target_id) in member_keys and str(lk.origin_id) not in member_keys
            ]
            out_types = [
                lk.type for lk in canvas.links if str(lk.origin_id) in member_keys and str(lk.target_id) not in member_keys
            ]
            if any(in_types.count(ot) != 1 for ot in set(out_types)):
                continue

        claimed_keys.update(member_keys)
        pack_plan.append((g_idx, group.title, group.bounding, group.raw.get("color"), members))

    if not pack_plan:
        return PackResult(
            canvas=Canvas(raw_doc),
            packed_groups=(),
            subgraph_count=len(existing_sgs),
            root_nodes_before=root_nodes_before,
            root_nodes_after=root_nodes_before,
            internal_nodes=sum(len(s.get("nodes") or []) for s in existing_sgs.values()),
            root_links_before=root_links_before,
            root_links_after=root_links_before,
            max_depth=1 if existing_sgs else 0,
            root_dom_reduction_pct=0.0,
            id_map={},
        )

    # Track numeric IDs used on root so newly created subgraph instance nodes never collide
    used_root_ids: set[int] = {int(n.id) for n in all_nodes if isinstance(n.id, int)}
    next_root_id_hint = max(used_root_ids, default=0) + 1
    used_root_link_ids: set[int] = {lk.id for lk in canvas.links}
    next_root_link_hint = max(used_root_link_ids, default=0) + 1

    old_nodes_by_key = {n.key: copy.deepcopy(n.raw) for n in all_nodes}
    new_root_nodes: list[dict[str, Any]] = [
        copy.deepcopy(n.raw) for n in all_nodes if n.key not in claimed_keys
    ]
    # Clear link bindings on kept root nodes; we rebuild all root links cleanly below
    for rn in new_root_nodes:
        for inp in rn.get("inputs") or []:
            inp["link"] = None
        for out in rn.get("outputs") or []:
            out["links"] = []

    kept_links = [
        lk for lk in canvas.links if str(lk.origin_id) not in claimed_keys and str(lk.target_id) not in claimed_keys
    ]
    new_root_links: list[list[Any]] = []
    node_lookup: dict[str, dict[str, Any]] = {str(n["id"]): n for n in new_root_nodes}

    def add_root_link(oid: Any, oslot: int, tid: Any, tslot: int, ltype: str, pref_id: int | None = None) -> int:
        nonlocal next_root_link_hint
        if pref_id is not None and pref_id not in used_root_link_ids:
            lid = pref_id
            used_root_link_ids.add(lid)
        else:
            lid = _allocate_int_id(used_root_link_ids, next_root_link_hint)
            next_root_link_hint = lid + 1
        new_root_links.append([lid, oid, oslot, tid, tslot, ltype])
        src = node_lookup[str(oid)]
        dst = node_lookup[str(tid)]
        src["outputs"][oslot].setdefault("links", []).append(lid)
        dst["inputs"][tslot]["link"] = lid
        return lid

    # Re-attach links strictly between unpacked root nodes (preserving IDs)
    used_root_link_ids.clear()
    for lk in kept_links:
        add_root_link(lk.origin_id, lk.origin_slot, lk.target_id, lk.target_slot, lk.type, pref_id=lk.id)

    # Build one 1-level Subgraph per planned group
    new_subgraphs: list[dict[str, Any]] = list(copy.deepcopy((raw_doc.get("definitions") or {}).get("subgraphs") or []))
    packed_group_names: list[str] = []
    id_map: dict[str, str] = {}
    # Map (original_node_key, slot) -> (subgraph_inst_id, boundary_slot) for cross-group rewiring
    out_redirect: dict[tuple[str, int], tuple[int, int, str]] = {}
    in_redirect: dict[tuple[str, int], tuple[int, int, str]] = {}
    group_rects_updated: dict[int, list[float]] = {}

    # Track external links crossing each packed group
    for g_idx, g_title, g_rect, _g_color, members in pack_plan:
        member_keys = {m.key for m in members}
        sg_id = _stable_uuid(f"cwc-sg:{g_idx}:{g_title}:{','.join(sorted(member_keys))}")
        inst_id = _allocate_int_id(used_root_ids, next_root_id_hint)
        next_root_id_hint = inst_id + 1

        all_bypassed = all(m.mode == NodeMode.BYPASS for m in members)
        all_muted = all(m.mode == NodeMode.NEVER for m in members)
        inst_mode = int(NodeMode.BYPASS) if all_bypassed else (int(NodeMode.NEVER) if all_muted else int(NodeMode.ALWAYS))

        # Clone internal nodes and normalize their coordinates to start near (200, 100)
        min_x = min(m.pos[0] for m in members)
        min_y = min(m.pos[1] for m in members)
        inner_nodes: list[dict[str, Any]] = []
        inner_by_key: dict[str, dict[str, Any]] = {}
        for m in members:
            clone = copy.deepcopy(old_nodes_by_key[m.key])
            clone["pos"] = [
                snap_up(clone["pos"][0] - min_x + 200),
                snap_up(clone["pos"][1] - min_y + 100),
            ]
            if all_bypassed or all_muted:
                clone["mode"] = int(NodeMode.ALWAYS)
            for inp in clone.get("inputs") or []:
                inp["link"] = None
            for out in clone.get("outputs") or []:
                out["links"] = []
            inner_nodes.append(clone)
            inner_by_key[str(clone["id"])] = clone
            id_map[f"{inst_id}:{clone['id']}"] = m.key

        # Partition links touching this group: internal, incoming, outgoing
        inner_links: list[dict[str, Any]] = []
        next_inner_lid = 1
        sg_inputs: list[dict[str, Any]] = []
        sg_outputs: list[dict[str, Any]] = []
        inst_inputs: list[dict[str, Any]] = []
        inst_outputs: list[dict[str, Any]] = []

        # Deduplicate incoming boundary ports by (origin_key, origin_slot)
        in_port_by_origin: dict[tuple[str, int], int] = {}
        # Deduplicate outgoing boundary ports by (origin_key, origin_slot)
        out_port_by_origin: dict[tuple[str, int], int] = {}

        for lk in canvas.links:
            okey, tkey = str(lk.origin_id), str(lk.target_id)
            o_in = okey in member_keys
            t_in = tkey in member_keys
            if o_in and t_in:
                lid = next_inner_lid
                next_inner_lid += 1
                inner_links.append(
                    {
                        "id": lid,
                        "origin_id": lk.origin_id,
                        "origin_slot": lk.origin_slot,
                        "target_id": lk.target_id,
                        "target_slot": lk.target_slot,
                        "type": lk.type,
                    }
                )
                inner_by_key[okey]["outputs"][lk.origin_slot].setdefault("links", []).append(lid)
                inner_by_key[tkey]["inputs"][lk.target_slot]["link"] = lid
            elif not o_in and t_in:
                origin_pair = (okey, lk.origin_slot)
                if origin_pair not in in_port_by_origin:
                    p_idx = len(sg_inputs)
                    in_port_by_origin[origin_pair] = p_idx
                    t_inp = inner_by_key[tkey]["inputs"][lk.target_slot]
                    pname = t_inp.get("name") or f"in_{p_idx}"
                    sg_inputs.append(
                        {
                            "id": _stable_uuid(f"{sg_id}:in:{p_idx}:{pname}"),
                            "name": pname,
                            "type": lk.type,
                            "linkIds": [],
                            "label": pname,
                            "pos": [40, 120 + p_idx * 28],
                        }
                    )
                    inst_inputs.append({"name": pname, "type": lk.type, "link": None})
                p_idx = in_port_by_origin[origin_pair]
                lid = next_inner_lid
                next_inner_lid += 1
                inner_links.append(
                    {
                        "id": lid,
                        "origin_id": SUBGRAPH_INPUT_ID,
                        "origin_slot": p_idx,
                        "target_id": lk.target_id,
                        "target_slot": lk.target_slot,
                        "type": lk.type,
                    }
                )
                sg_inputs[p_idx]["linkIds"].append(lid)
                inner_by_key[tkey]["inputs"][lk.target_slot]["link"] = lid
                in_redirect[(tkey, lk.target_slot)] = (inst_id, p_idx, lk.type)
            elif o_in and not t_in:
                origin_pair = (okey, lk.origin_slot)
                if origin_pair not in out_port_by_origin:
                    p_idx = len(sg_outputs)
                    out_port_by_origin[origin_pair] = p_idx
                    o_out = inner_by_key[okey]["outputs"][lk.origin_slot]
                    pname = o_out.get("name") or f"out_{p_idx}"
                    sg_outputs.append(
                        {
                            "id": _stable_uuid(f"{sg_id}:out:{p_idx}:{pname}"),
                            "name": pname,
                            "type": lk.type,
                            "linkIds": [],
                            "label": pname,
                            "pos": [0, 120 + p_idx * 28],
                        }
                    )
                    inst_outputs.append({"name": pname, "type": lk.type, "links": []})
                    lid = next_inner_lid
                    next_inner_lid += 1
                    inner_links.append(
                        {
                            "id": lid,
                            "origin_id": lk.origin_id,
                            "origin_slot": lk.origin_slot,
                            "target_id": SUBGRAPH_OUTPUT_ID,
                            "target_slot": p_idx,
                            "type": lk.type,
                        }
                    )
                    sg_outputs[p_idx]["linkIds"].append(lid)
                    inner_by_key[okey]["outputs"][lk.origin_slot].setdefault("links", []).append(lid)
                p_idx = out_port_by_origin[origin_pair]
                out_redirect[(okey, lk.origin_slot)] = (inst_id, p_idx, lk.type)

        max_inner_x = max((n["pos"][0] + n["size"][0] for n in inner_nodes), default=500)
        for odef in sg_outputs:
            odef["pos"][0] = max_inner_x + 120

        proxies, proxy_vals = _extract_proxy_widgets(inner_nodes, defs)
        card_w = max(SUBGRAPH_CARD_MIN_W, snap_up(min(g_rect.w - SUBGRAPH_PADDING, 360)))
        slots_rows = max(len(inst_inputs), len(inst_outputs), 2)
        card_h = max(SUBGRAPH_CARD_MIN_H, snap_up(60 + slots_rows * 24 + len(proxies) * 26))
        card_x = snap_up(g_rect.x + GRID)
        card_y = snap_up(g_rect.y + GROUP_HEADER_PAD)

        sg_def = {
            "id": sg_id,
            "version": 1,
            "name": g_title,
            "state": {
                "lastGroupId": 0,
                "lastNodeId": max((int(n["id"]) for n in inner_nodes if isinstance(n["id"], int)), default=0),
                "lastLinkId": next_inner_lid - 1,
                "lastRerouteId": 0,
            },
            "revision": 0,
            "config": {},
            "extra": {"cwc_packed_group": g_title},
            "inputNode": {"id": SUBGRAPH_INPUT_ID, "bounding": [-60, 100, 140, max(80, 34 + len(sg_inputs) * 28)]},
            "outputNode": {"id": SUBGRAPH_OUTPUT_ID, "bounding": [max_inner_x + 100, 100, 140, max(80, 34 + len(sg_outputs) * 28)]},
            "inputs": sg_inputs,
            "outputs": sg_outputs,
            "nodes": inner_nodes,
            "links": inner_links,
            "groups": [],
            "widgets": [],
        }
        new_subgraphs.append(sg_def)

        inst_node: dict[str, Any] = {
            "id": inst_id,
            "type": sg_id,
            "pos": [card_x, card_y],
            "size": [card_w, card_h],
            "flags": {},
            "order": inst_id,
            "mode": inst_mode,
            "title": f"{g_title} [{len(inner_nodes)} nodes]",
            "inputs": inst_inputs,
            "outputs": inst_outputs,
            "properties": {
                "proxyWidgets": proxies,
                "cwc_internal_nodes": len(inner_nodes),
            },
            "widgets_values": proxy_vals,
        }
        new_root_nodes.append(inst_node)
        node_lookup[str(inst_id)] = inst_node
        packed_group_names.append(g_title)
        group_rects_updated[g_idx] = [
            g_rect.x,
            g_rect.y,
            max(card_w + SUBGRAPH_PADDING, snap_up(card_w + 40)),
            max(card_h + GROUP_HEADER_PAD + TITLE_HEIGHT, snap_up(card_h + 90)),
        ]

    # Rewire all cross-boundary root links (deduplicated per (new_origin, new_target))
    wired_edges: set[tuple[Any, int, Any, int]] = set()
    for lk in canvas.links:
        okey, tkey = str(lk.origin_id), str(lk.target_id)
        if okey not in claimed_keys and tkey not in claimed_keys:
            continue
        if okey in claimed_keys and tkey in claimed_keys:
            # Skip strictly intra-group links; connect inter-subgraph links
            src_redir = out_redirect.get((okey, lk.origin_slot))
            dst_redir = in_redirect.get((tkey, lk.target_slot))
            if src_redir is None or dst_redir is None or src_redir[0] == dst_redir[0]:
                continue
            new_o, new_oslot = src_redir[0], src_redir[1]
            new_t, new_tslot = dst_redir[0], dst_redir[1]
        elif okey in claimed_keys:
            src_redir = out_redirect[(okey, lk.origin_slot)]
            new_o, new_oslot = src_redir[0], src_redir[1]
            new_t, new_tslot = lk.target_id, lk.target_slot
        else:
            dst_redir = in_redirect[(tkey, lk.target_slot)]
            new_o, new_oslot = lk.origin_id, lk.origin_slot
            new_t, new_tslot = dst_redir[0], dst_redir[1]

        edge = (new_o, new_oslot, new_t, new_tslot)
        if edge in wired_edges:
            continue
        wired_edges.add(edge)
        add_root_link(new_o, new_oslot, new_t, new_tslot, lk.type)

    # Update groups & clean stale reroutes whose links changed
    new_groups = copy.deepcopy(raw_doc.get("groups") or [])
    for g_idx, rect_list in group_rects_updated.items():
        if 0 <= g_idx < len(new_groups):
            new_groups[g_idx]["bounding"] = rect_list

    extra = copy.deepcopy(raw_doc.get("extra") or {})
    extra.pop("reroutes", None)
    extra.pop("linkExtensions", None)

    packed_doc = {
        **raw_doc,
        "last_node_id": max((int(n["id"]) for n in new_root_nodes if isinstance(n["id"], int)), default=0),
        "last_link_id": max((lk[0] for lk in new_root_links), default=0),
        "nodes": new_root_nodes,
        "links": new_root_links,
        "groups": new_groups,
        "extra": extra,
        "definitions": {"subgraphs": new_subgraphs},
    }
    packed_canvas = Canvas(packed_doc)
    internal_total = sum(len(s.get("nodes") or []) for s in new_subgraphs)
    total_after = len(new_root_nodes) + internal_total
    reduction = round((1.0 - len(new_root_nodes) / max(1, total_after)) * 100.0, 1)

    return PackResult(
        canvas=packed_canvas,
        packed_groups=tuple(packed_group_names),
        subgraph_count=len(new_subgraphs),
        root_nodes_before=root_nodes_before,
        root_nodes_after=len(new_root_nodes),
        internal_nodes=internal_total,
        root_links_before=root_links_before,
        root_links_after=len(new_root_links),
        max_depth=1,
        root_dom_reduction_pct=reduction,
        id_map=id_map,
    )


def flatten_subgraphs(canvas: Canvas, *, max_depth: int = 1) -> Canvas:
    """Expand active 1-level Subgraph instances into a flat :class:`Canvas` matching frontend graphToPrompt.

    * Muted subgraph instances (mode 2) are dropped.
    * Bypassed subgraph instances (mode 4) remain as bypassed passthrough nodes so downstream
      bypass resolution walks straight through their matching input/output slots.
    * Active subgraph instances (mode 0) are expanded with scoped string IDs ``"<inst>:<inner>"``.
    * Nested subgraphs deeper than ``max_depth`` raise ``ValueError``.
    """
    sg_defs = subgraph_definitions(canvas)
    if not sg_defs:
        return Canvas(canvas.to_json())

    raw = canvas.to_json()
    root_nodes = raw.get("nodes") or []
    root_links = raw.get("links") or []

    active_instances = [n for n in root_nodes if n.get("type") in sg_defs and int(n.get("mode", 0)) == NodeMode.ALWAYS]
    if not active_instances:
        # Only muted/bypassed or unused subgraph definitions: strip definitions and return flat canvas
        cleaned = copy.deepcopy(raw)
        cleaned.pop("definitions", None)
        return Canvas(cleaned)

    # Check depth constraint: fail closed on nested subgraphs > max_depth
    for inst in active_instances:
        sg = sg_defs[inst["type"]]
        for inode in sg.get("nodes") or []:
            if inode.get("type") in sg_defs and max_depth <= 1:
                raise ValueError(
                    f"nested subgraph detected inside '{sg.get('name', sg['id'])}': "
                    f"depth > {max_depth} is refused by 1-level anti-lag policy"
                )

    flat_nodes: list[dict[str, Any]] = []
    node_map: dict[str, dict[str, Any]] = {}
    flat_links: list[list[Any]] = []
    next_link_id = max((lk[0] for lk in root_links if isinstance(lk, list) and lk), default=0) + 1

    # Track external link tables for rewiring
    root_links_by_id = {lk[0]: lk for lk in root_links if isinstance(lk, list) and len(lk) == 6}

    # Copy non-active-subgraph root nodes (dropping muted subgraph instances)
    active_inst_keys = {str(n["id"]) for n in active_instances}
    muted_inst_keys = {
        str(n["id"]) for n in root_nodes if n.get("type") in sg_defs and int(n.get("mode", 0)) == NodeMode.NEVER
    }
    for rn in root_nodes:
        rkey = str(rn["id"])
        if rkey in active_inst_keys or rkey in muted_inst_keys:
            continue
        clone = copy.deepcopy(rn)
        for inp in clone.get("inputs") or []:
            inp["link"] = None
        for out in clone.get("outputs") or []:
            out["links"] = []
        flat_nodes.append(clone)
        node_map[rkey] = clone

    # Per active subgraph instance, record where each boundary output port comes from inside the flattened graph
    # and which internal (node_key, target_slot, type) consume each boundary input port.
    inst_out_source: dict[tuple[str, int], tuple[str, int, str]] = {}
    inst_in_targets: dict[tuple[str, int], list[tuple[str, int, str]]] = {}

    def add_flat_link(oid: Any, oslot: int, tid: Any, tslot: int, ltype: str) -> int:
        nonlocal next_link_id
        lid = next_link_id
        next_link_id += 1
        flat_links.append([lid, oid, oslot, tid, tslot, ltype])
        src = node_map[str(oid)]
        dst = node_map[str(tid)]
        src["outputs"][oslot].setdefault("links", []).append(lid)
        dst["inputs"][tslot]["link"] = lid
        return lid

    # Expand every active subgraph instance
    for inst in active_instances:
        ikey = str(inst["id"])
        sg = sg_defs[inst["type"]]
        inner_nodes = sg.get("nodes") or []
        inner_links = sg.get("links") or []

        for inode in inner_nodes:
            scoped_id = f"{ikey}:{inode['id']}"
            clone = copy.deepcopy(inode)
            clone["id"] = scoped_id
            for inp in clone.get("inputs") or []:
                inp["link"] = None
            for out in clone.get("outputs") or []:
                out["links"] = []
            flat_nodes.append(clone)
            node_map[scoped_id] = clone

        for ilk in inner_links:
            if not isinstance(ilk, dict):
                continue
            oid, oslot = ilk["origin_id"], ilk["origin_slot"]
            tid, tslot = ilk["target_id"], ilk["target_slot"]
            ltype = ilk.get("type", "*")
            if oid == SUBGRAPH_INPUT_ID and tid == SUBGRAPH_OUTPUT_ID:
                # Direct passthrough wire inside subgraph
                inst_out_source[(ikey, tslot)] = (f"__INPUT__:{ikey}", oslot, ltype)
            elif oid == SUBGRAPH_INPUT_ID:
                inst_in_targets.setdefault((ikey, oslot), []).append((f"{ikey}:{tid}", tslot, ltype))
            elif tid == SUBGRAPH_OUTPUT_ID:
                inst_out_source[(ikey, tslot)] = (f"{ikey}:{oid}", oslot, ltype)
            else:
                add_flat_link(f"{ikey}:{oid}", oslot, f"{ikey}:{tid}", tslot, ltype)

    # Resolve any direct input->output passthrough inside a subgraph
    def resolve_source(okey: str, oslot: int, seen: set[tuple[str, int]] | None = None) -> tuple[Any, int] | None:
        seen = seen or set()
        if (okey, oslot) in seen:
            raise ValueError(f"cyclic subgraph boundary link at {okey}:{oslot}")
        seen = seen | {(okey, oslot)}
        if okey in muted_inst_keys:
            return None
        if okey not in active_inst_keys:
            orig_node = node_map.get(okey)
            return (orig_node["id"], oslot) if orig_node is not None else None
        mapped = inst_out_source.get((okey, oslot))
        if mapped is None:
            return None
        src_key, src_slot, _ = mapped
        if src_key.startswith("__INPUT__:"):
            inst_node = next(n for n in active_instances if str(n["id"]) == okey)
            inps = inst_node.get("inputs") or []
            if 0 <= src_slot < len(inps):
                ext_lid = inps[src_slot].get("link")
                if ext_lid in root_links_by_id:
                    _, ext_oid, ext_oslot, _, _, _ = root_links_by_id[ext_lid]
                    return resolve_source(str(ext_oid), ext_oslot, seen)
            return None
        return (src_key, src_slot)

    # Rewire every root link using expanded producers and consumers
    for lk in root_links:
        if not isinstance(lk, list) or len(lk) != 6:
            continue
        _lid, oid, oslot, tid, tslot, ltype = lk
        okey, tkey = str(oid), str(tid)
        if okey in muted_inst_keys or tkey in muted_inst_keys:
            continue
        resolved_src = resolve_source(okey, oslot)
        if resolved_src is None:
            continue
        real_oid, real_oslot = resolved_src
        if tkey in active_inst_keys:
            for inner_tid, inner_tslot, inner_type in inst_in_targets.get((tkey, tslot), []):
                add_flat_link(real_oid, real_oslot, inner_tid, inner_tslot, inner_type or ltype)
        elif tkey in node_map:
            add_flat_link(real_oid, real_oslot, node_map[tkey]["id"], tslot, ltype)

    out_doc = {
        **raw,
        "last_link_id": next_link_id - 1,
        "nodes": flat_nodes,
        "links": flat_links,
    }
    out_doc.pop("definitions", None)
    return Canvas(out_doc)
