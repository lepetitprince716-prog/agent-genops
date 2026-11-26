#!/usr/bin/env python3
"""Tactical dark-HUD SVG preview renderer for OmniStudio Ubisoft Workbench.

Renders two clean, deterministic vector diagrams without needing a live ComfyUI server:
1. ``omni_ubisoft_workbench_root.svg``: Full Ubisoft Root HUD (Command Cockpit, 18 Engine
   Capsules across 4 color-coded banks, Lazy Pixel/Pipe Bridge, VRAM Flush Gate, 4 Post-FX
   Stations, Centralized Gallery Tower, and Anti-Lag Telemetry Banner).
2. ``omni_ubisoft_workbench_capsules.svg``: Zoomed internal architecture of 4 flagship
   capsules (E01 SDXL/Illustrious, E06 Flux.1 Dev, E11 MOSS-Image, S03 Anatomy SEGS).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

BG = "#0f141c"
GRID = "#17202b"
TEXT = "#e6edf3"
MUTED = "#8b949e"
LINK_ACTIVE = "#4cc9f0"
LINK_MUTED = "#3a4654"
LINK_PIPE = "#c77dff"


def _esc(text: Any) -> str:
    return escape(str(text), {'"': "&quot;", "'": "&apos;"})


def render_root_svg(doc: dict[str, Any]) -> str:
    nodes = doc.get("nodes") or []
    groups = doc.get("groups") or []
    links = doc.get("links") or []
    subgraphs = {s["id"]: s for s in (doc.get("definitions") or {}).get("subgraphs") or []}
    node_map = {n["id"]: n for n in nodes}

    internal_nodes = sum(len(s["nodes"]) for s in subgraphs.values())
    total_nodes = len(nodes) + internal_nodes
    reduction = round((1.0 - len(nodes) / max(1, total_nodes)) * 100, 1)

    min_x = min([g["bounding"][0] for g in groups] + [n["pos"][0] for n in nodes], default=0) - 60
    min_y = min([g["bounding"][1] for g in groups] + [n["pos"][1] - 30 for n in nodes], default=0) - 130
    max_x = max(
        [g["bounding"][0] + g["bounding"][2] for g in groups]
        + [n["pos"][0] + n["size"][0] for n in nodes],
        default=5700,
    ) + 60
    max_y = max(
        [g["bounding"][1] + g["bounding"][3] for g in groups]
        + [n["pos"][1] + n["size"][1] for n in nodes],
        default=1800,
    ) + 80
    vw, vh = max_x - min_x, max_y - min_y

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{min_x} {min_y} {vw} {vh}" '
        f'width="{int(vw * 0.35)}" height="{int(vh * 0.35)}" font-family="Inter, system-ui, -apple-system, sans-serif">',
        "<defs>",
        f'<pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">'
        f'<path d="M 40 0 L 0 0 0 40" fill="none" stroke="{GRID}" stroke-width="1"/></pattern>',
        "</defs>",
        f'<rect x="{min_x}" y="{min_y}" width="{vw}" height="{vh}" fill="{BG}"/>',
        f'<rect x="{min_x}" y="{min_y}" width="{vw}" height="{vh}" fill="url(#grid)"/>',
        # Header HUD banner
        f'<rect x="{min_x + 20}" y="{min_y + 18}" width="{vw - 40}" height="82" rx="10" '
        f'fill="#161f2c" stroke="#2d4a6b" stroke-width="2"/>',
        f'<text x="{min_x + 48}" y="{min_y + 58}" fill="#ffffff" font-size="30" font-weight="700">'
        f'OMNISTUDIO UBISOFT ALL-IN-ONE SUPER WORKBENCH (v1.0 · ComfyUI 0.4 Native Flat Subgraphs)</text>',
        f'<text x="{min_x + 48}" y="{min_y + 86}" fill="#7ee787" font-size="18" font-weight="600">'
        f'Total Real Nodes: {total_nodes}  |  Root Canvas Nodes: {len(nodes)} ({reduction}% DOM Reduction)  |  '
        f'18 Model Engines (1-Click Radio)  |  6 Post-FX Stations  |  0 Use-Everywhere  |  1 Centralized Comparer</text>',
    ]

    # Groups
    parts.append('<g id="groups">')
    for g in groups:
        gx, gy, gw, gh = g["bounding"]
        col = g.get("color") or "#2b4257"
        parts.append(
            f'<rect x="{gx}" y="{gy}" width="{gw}" height="{gh}" rx="10" '
            f'fill="{col}" fill-opacity="0.22" stroke="{col}" stroke-width="2.5"/>'
        )
        parts.append(
            f'<text x="{gx + 14}" y="{gy + 28}" fill="{TEXT}" font-size="{min(22, g.get("font_size", 20))}" '
            f'font-weight="700">{_esc(g.get("title", ""))}</text>'
        )
    parts.append("</g>")

    # Links (reroute waypoints aware)
    rr_map = {r["id"]: r for r in (doc.get("extra") or {}).get("reroutes") or []}
    le_map = {e["id"]: e["parentId"] for e in (doc.get("extra") or {}).get("linkExtensions") or []}

    parts.append('<g id="links" fill="none" stroke-linecap="round" stroke-linejoin="round">')
    for lid, oid, oslot, tid, tslot, ltype in links:
        src = node_map.get(oid)
        dst = node_map.get(tid)
        if not src or not dst:
            continue
        sx = src["pos"][0] + src["size"][0]
        sy = src["pos"][1] + 24 + oslot * 22
        tx = dst["pos"][0]
        ty = dst["pos"][1] + 24 + tslot * 22

        is_muted = src.get("mode", 0) == 2 or dst.get("mode", 0) == 2
        stroke = LINK_MUTED if is_muted else (LINK_PIPE if ltype == "BASIC_PIPE" else LINK_ACTIVE)
        opacity = "0.28" if is_muted else "0.82"
        width = "1.6" if is_muted else "2.6"

        pts: list[tuple[float, float]] = [(sx, sy)]
        if lid in le_map:
            chain: list[tuple[float, float]] = []
            cur = le_map[lid]
            seen: set[int] = set()
            while cur is not None and cur in rr_map and cur not in seen:
                seen.add(cur)
                r = rr_map[cur]
                chain.append((r["pos"][0], r["pos"][1]))
                cur = r.get("parentId")
            pts.extend(reversed(chain))
        pts.append((tx, ty))
        d = "M " + " L ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        parts.append(f'<path d="{d}" stroke="{stroke}" stroke-opacity="{opacity}" stroke-width="{width}"/>')
    parts.append("</g>")

    # Nodes
    parts.append('<g id="nodes">')
    for n in nodes:
        nx, ny = n["pos"]
        nw, nh = n["size"]
        mode = n.get("mode", 0)
        is_sg = n["type"] in subgraphs
        hdr = n.get("color") or "#2a3b4c"
        bg = n.get("bgcolor") or "#20262f"
        op = "0.46" if mode == 2 else ("0.68" if mode == 4 else "1.0")
        stroke = "#58a6ff" if (is_sg and mode == 0) else ("#7d8590" if mode != 0 else "#4c6278")
        dash = ' stroke-dasharray="7 4"' if mode == 4 else ""

        parts.append(f'<g opacity="{op}">')
        parts.append(
            f'<rect x="{nx}" y="{ny - 30}" width="{nw}" height="{nh + 30}" rx="8" '
            f'fill="{bg}" stroke="{stroke}" stroke-width="2"{dash}/>'
        )
        parts.append(
            f'<path d="M {nx + 8},{ny - 30} H {nx + nw - 8} Q {nx + nw},{ny - 30} {nx + nw},{ny - 22} '
            f'V {ny} H {nx} V {ny - 22} Q {nx},{ny - 30} {nx + 8},{ny - 30} Z" fill="{hdr}"/>'
        )
        title = n.get("title") or n["type"]
        if len(title) > 38:
            title = title[:36] + "..."
        parts.append(
            f'<text x="{nx + 12}" y="{ny - 10}" fill="#ffffff" font-size="13" font-weight="700">{_esc(title)}</text>'
        )

        # Subgraph folder pill & status badge
        if is_sg:
            sg_nodes = len(subgraphs[n["type"]]["nodes"])
            badge = "ACTIVE" if mode == 0 else ("MUTED (0 cost)" if mode == 2 else "BYPASSED")
            b_fill = "#238636" if mode == 0 else ("#30363d" if mode == 2 else "#9e6a03")
            parts.append(
                f'<rect x="{nx + 14}" y="{ny + 18}" width="{nw - 28}" height="32" rx="6" fill="#161b22" stroke="#30363d"/>'
            )
            parts.append(
                f'<text x="{nx + 24}" y="{ny + 39}" fill="#79c0ff" font-size="13" font-weight="600">'
                f'SUBGRAPH CAPSULE · {sg_nodes} nodes</text>'
            )
            parts.append(
                f'<rect x="{nx + 14}" y="{ny + 62}" width="138" height="24" rx="12" fill="{b_fill}"/>'
            )
            parts.append(
                f'<text x="{nx + 26}" y="{ny + 78}" fill="#ffffff" font-size="11" font-weight="700">{badge}</text>'
            )
            pw = (n.get("properties") or {}).get("proxyWidgets") or []
            if pw:
                exposed = ", ".join(p[1] for p in pw[:3])
                parts.append(
                    f'<text x="{nx + 14}" y="{ny + 112}" fill="{MUTED}" font-size="12">App Controls: {_esc(exposed)}</text>'
                )
        else:
            parts.append(
                f'<text x="{nx + 14}" y="{ny + 24}" fill="{MUTED}" font-size="12">{_esc(n["type"])}</text>'
            )
        parts.append("</g>")
    parts.append("</g>")
    parts.append("</svg>\n")
    return "\n".join(parts)


def render_capsules_svg(doc: dict[str, Any]) -> str:
    """2x2 zoomed architectural diagram of 4 flagship Subgraph capsules."""
    subgraphs = {s["extra"]["omnistudio_capsule"]: s for s in (doc.get("definitions") or {}).get("subgraphs") or []}
    picks = ["e01_sdxl_illustrious", "e06_flux1_dev", "e11_moss_image", "s03_anatomy_segs"]
    panel_w, panel_h = 1120, 420
    pad = 36
    total_w = panel_w * 2 + pad * 3
    total_h = panel_h * 2 + pad * 3 + 70

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w} {total_h}" '
        f'width="{int(total_w * 0.65)}" height="{int(total_h * 0.65)}" font-family="Inter, system-ui, sans-serif">',
        f'<rect x="0" y="0" width="{total_w}" height="{total_h}" fill="{BG}"/>',
        f'<text x="{pad}" y="48" fill="#ffffff" font-size="26" font-weight="700">'
        f'INSIDE THE 1-LEVEL FLAT SUBGRAPH CAPSULES (Zero Nested Subgraphs · Self-Contained Engines)</text>',
    ]

    for idx, key in enumerate(picks):
        sg = subgraphs.get(key)
        if not sg:
            continue
        col = idx % 2
        row = idx // 2
        ox = pad + col * (panel_w + pad)
        oy = 76 + row * (panel_h + pad)
        parts.append(
            f'<rect x="{ox}" y="{oy}" width="{panel_w}" height="{panel_h}" rx="12" '
            f'fill="#151b24" stroke="#2d4a6b" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{ox + 20}" y="{oy + 32}" fill="#79c0ff" font-size="18" font-weight="700">'
            f'{_esc(sg["name"])} ({len(sg["nodes"])} nodes · {len(sg["links"])} links)</text>'
        )

        # Normalize node positions inside panel
        inodes = sg["nodes"]
        min_x = min(n["pos"][0] for n in inodes)
        max_x = max(n["pos"][0] + n["size"][0] for n in inodes)
        min_y = min(n["pos"][1] for n in inodes)
        max_y = max(n["pos"][1] + n["size"][1] for n in inodes)
        sx = (panel_w - 60) / max(1, (max_x - min_x))
        sy = (panel_h - 80) / max(1, (max_y - min_y))
        scale = min(sx, sy, 0.42)

        pos_map: dict[int, tuple[float, float, float, float]] = {}
        for n in inodes:
            x = ox + 30 + (n["pos"][0] - min_x) * scale
            y = oy + 54 + (n["pos"][1] - min_y) * scale
            w = max(84, n["size"][0] * scale)
            h = max(36, n["size"][1] * scale)
            pos_map[n["id"]] = (x, y, w, h)

        # Internal links
        for lk in sg["links"]:
            oid, tid = lk["origin_id"], lk["target_id"]
            if oid in pos_map and tid in pos_map:
                ax, ay, aw, ah = pos_map[oid]
                bx, by, _bw, bh = pos_map[tid]
                parts.append(
                    f'<line x1="{ax + aw:.1f}" y1="{ay + ah * 0.5:.1f}" '
                    f'x2="{bx:.1f}" y2="{by + bh * 0.5:.1f}" stroke="#4cc9f0" stroke-opacity="0.6" stroke-width="1.5"/>'
                )

        # Internal nodes
        for n in inodes:
            x, y, w, h = pos_map[n["id"]]
            bypassed = n.get("mode", 0) == 4
            fill = "#202733" if not bypassed else "#1c1f24"
            stroke = "#58a6ff" if not bypassed else "#6e7681"
            dash = ' stroke-dasharray="4 3"' if bypassed else ""
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="5" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="1.3"{dash}/>'
            )
            lbl = n.get("title") or n["type"]
            if len(lbl) > 20:
                lbl = lbl[:18] + ".."
            parts.append(
                f'<text x="{x + 6:.1f}" y="{y + 18:.1f}" fill="{TEXT}" font-size="10" font-weight="600">{_esc(lbl)}</text>'
            )
            parts.append(
                f'<text x="{x + 6:.1f}" y="{y + 32:.1f}" fill="{MUTED}" font-size="9">{_esc(n["type"][:22])}</text>'
            )

    parts.append("</svg>\n")
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render SVG previews of OmniStudio Ubisoft Workbench.")
    parser.add_argument(
        "workflow",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parent / "dist" / "omni_ubisoft_workbench.ui.json",
    )
    parser.add_argument(
        "-o",
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "dist",
    )
    args = parser.parse_args(argv)
    doc = json.loads(args.workflow.read_text(encoding="utf-8"))
    args.out_dir.mkdir(parents=True, exist_ok=True)

    root_svg = args.out_dir / "omni_ubisoft_workbench_root.svg"
    caps_svg = args.out_dir / "omni_ubisoft_workbench_capsules.svg"
    root_svg.write_text(render_root_svg(doc), encoding="utf-8")
    caps_svg.write_text(render_capsules_svg(doc), encoding="utf-8")
    print(f"Rendered {root_svg.name} ({root_svg.stat().st_size} B) and {caps_svg.name} ({caps_svg.stat().st_size} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
