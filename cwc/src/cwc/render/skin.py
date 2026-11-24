"""The diagram skin: a canvas drawn as an architecture figure.

Groups become flat panels, nodes become modules (title and one value line), output nodes alone in
their group become dark terminal blocks across the panel, links become right-angled lines with an
arrow (a short vertical one between two stacked modules), and the author's ``extra.cwc`` block
(:mod:`cwc.render.notes`) adds the figure title, the panel meta lines and the notes beside modules
(under one when the room beside it is taken). Every position comes from the canvas and the
geometry the checks read; nothing is laid out here. Every colour comes from one :class:`Palette`:
the group and node colours saved in the canvas are not used.

Structure, back to front: ``rect.background``; ``text#title``; ``g#groups`` with one
``g.panel#group-<index>``; ``g#links`` with one ``path.link#link-<id>`` (class ``bypass`` when it
touches a bypassed node) and one ``path.arrow#arrow-<id>`` per drawn link; ``g#nodes`` with one
``g.module#node-<id>`` or ``g.terminal#node-<id>`` per node; ``g#notes`` with one ``g.note`` per
note run. No slot dots, reroute circles or first-screen frame: they belong to the debug skin.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence

from cwc.canvas.envelope import BoxFacts, Point, Renderer, box_facts, classic_box, title_text
from cwc.canvas.geometry import Rect, bounding
from cwc.canvas.model import Canvas, Group, Node, NodeMode, id_order
from cwc.canvas.reroutes import Reroutes, link_paths
from cwc.canvas.textwidth import text_width
from cwc.nodedefs.derive import widget_layout
from cwc.nodedefs.types import NodeDef, WidgetKind
from cwc.prompt.slots import DefLookup
from cwc.render.markup import attr, num, pair, text
from cwc.render.notes import DiagramNotes, read_notes
from cwc.render.svg import Rendering, link_shapes


class Theme(str, Enum):
    LIGHT = "light"
    DARK = "dark"


@dataclass(frozen=True)
class Palette:
    bg: str
    panel: str
    panel_title: str
    panel_meta: str
    module: str
    primary: str
    primary_soft: str
    link: str
    accent: str
    terminal: str
    terminal_text: str


PALETTES: dict[Theme, Palette] = {
    Theme.LIGHT: Palette(
        bg="#F6F8FB",
        panel="#E9EDF2",
        panel_title="#1F2733",
        panel_meta="#7A8594",
        module="#FFFFFF",
        primary="#1F7AD1",
        primary_soft="#5E8FBF",
        link="#26303B",
        accent="#1E9A60",
        terminal="#1F2730",
        terminal_text="#FFFFFF",
    ),
    Theme.DARK: Palette(
        bg="#12161C",
        panel="#1B2129",
        panel_title="#E6E9EE",
        panel_meta="#8A93A0",
        module="#10151B",
        primary="#4FA3F0",
        primary_soft="#8DB3D8",
        link="#C8D0DA",
        accent="#3CC98A",
        terminal="#E6E9EE",
        terminal_text="#12161C",
    ),
}

FONT = "-apple-system, 'Helvetica Neue', Arial, sans-serif"
HEADER_SIZE = 28
PANEL_TITLE_SIZE = 22
TERMINAL_SIZE = 20
MODULE_TITLE_SIZE = 15
META_SIZE = 13  # panel meta lines and notes
SUBTITLE_SIZE = 11
BOLD = 1.08  # the width table is measured at regular weight; bold runs wider

MARGIN = 40
PANEL_PAD = 20  # panel title and meta inset; terminal blocks keep this much of the panel free
PANEL_BASELINE = 34
PANEL_RADIUS = 4
HEADER_GAP = 24  # header baseline above the content
MODULE_STROKE = 2
MODULE_RADIUS = 2
TEXT_INSET = 8  # free room inside a module on each side of its title
SUBTITLE_CHARS = 28

LINK_WIDTH = 1.6
LEG = 20  # how far a backward link runs out of the output and into the input before turning
STACK_OVERLAP = 0.6  # share of the narrower width two stacked boxes must overlap for a vertical arrow
CORNER = 6
ARROW_LENGTH = 9
ARROW_HALF_WIDTH = 4.5
DASH = "6 4"

NOTE_GAP = 16
NOTE_WRAP = 160
NOTE_LINE = 17
NOTE_BASELINE = 12.5  # first baseline below the top of a note's text block
NOTE_BELOW_GAP = 8  # a note under its module starts this far below it
NOTE_CLEARANCE = 4  # free room a note's text keeps from links and boxes
BRACKET_GAP = 12
BRACKET_WIDTH = 8
BRACKET_TEXT_GAP = 10

_NUMBER_PREFIX = re.compile(r"^\d+[a-z]? ")
_EXTENSION = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,15}$")


def render_diagram(canvas: Canvas, defs: DefLookup, theme: Theme = Theme.LIGHT) -> Rendering:
    palette = PALETTES[theme]
    nodes = sorted(canvas.nodes, key=lambda node: id_order(node.key))
    node_map = {node.key: node for node in nodes}
    facts = {node.key: box_facts(node, defs.get(node.type)) for node in nodes}
    own_boxes = {node.key: classic_box(node, facts[node.key]) for node in nodes}
    groups = canvas.groups
    depth = _depths(groups)
    home = {key: _innermost(box, groups, depth) for key, box in own_boxes.items()}
    terminals = _terminals(nodes, defs, home)
    boxes = {key: _terminal_box(key, own_boxes, home, groups) if key in terminals else own_boxes[key] for key in own_boxes}
    notes = read_notes(canvas)

    lines = _link_lines(canvas, node_map, facts, boxes)
    note_runs = _note_runs(notes, node_map, boxes, home, lines)

    extent: list[Rect] = [group.bounding for group in groups]
    extent.extend(boxes.values())
    for line in lines:
        extent.extend(_points_rect(run) for run in line.runs)
    extent.extend(run.extent for run in note_runs)
    content = bounding(extent) if extent else Rect(0, 0, 0, 0)
    header: list[str] = []
    if notes.title is not None:
        baseline = content.y - HEADER_GAP
        header.append(
            f'<text id="title" x="{num(content.x)}" y="{num(baseline)}" font-size="{HEADER_SIZE}" '
            f'font-weight="700" fill="{palette.panel_title}">{text(notes.title)}</text>'
        )
        extent.append(Rect(content.x, baseline - HEADER_SIZE, _width(notes.title, HEADER_SIZE, bold=True), HEADER_SIZE))
    box = (bounding(extent) if extent else Rect(0, 0, 0, 0)).inflate(MARGIN, MARGIN, MARGIN, MARGIN)

    order = sorted(range(len(groups)), key=lambda index: (depth[index], index))
    body = [
        f'<rect class="background" x="{num(box.x)}" y="{num(box.y)}" width="{num(box.w)}" height="{num(box.h)}" fill="{palette.bg}"/>',
        *header,
        '<g id="groups">',
        *(_panel(index, groups[index], depth[index], notes, palette) for index in order),
        "</g>",
        f'<g id="links" fill="none" stroke="{palette.link}" stroke-width="{num(LINK_WIDTH)}" stroke-linejoin="round">',
        *(_link(line, palette) for line in lines),
        "</g>",
        '<g id="nodes">',
        *(
            _terminal(node, boxes[node.key], defs, palette) if node.key in terminals else _module(node, boxes[node.key], defs, palette)
            for node in nodes
        ),
        "</g>",
        '<g id="notes">',
        *(_note(run, palette) for run in note_runs),
        "</g>",
    ]
    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{num(box.x)} {num(box.y)} {num(box.w)} {num(box.h)}" '
        f'width="{num(box.w)}" height="{num(box.h)}" font-family="{attr(FONT)}">'
    )
    return Rendering(
        svg="\n".join([head, *body, "</svg>"]) + "\n",
        view_box=(box.x, box.y, box.w, box.h),
        groups=len(groups),
        nodes=len(nodes),
        links=len(lines),
        links_unresolved=len({link.id for link in canvas.links}) - len(lines),
        reroutes=len(Reroutes.read(canvas).points),
    )


# --- groups ----------------------------------------------------------------------------


def _depths(groups: Sequence[Group]) -> list[int]:
    """How many other groups hold each group; a group equal to another counts the earlier one only."""
    rects = [group.bounding for group in groups]
    out: list[int] = []
    for index, rect in enumerate(rects):
        out.append(
            sum(
                1
                for other, outer in enumerate(rects)
                if other != index and outer.contains_rect(rect) and (outer != rect or other < index)
            )
        )
    return out


def _innermost(box: Rect, groups: Sequence[Group], depth: Sequence[int]) -> int | None:
    """The deepest group holding the box centre, as the frontend decides membership."""
    cx, cy = box.center
    holding = [index for index, group in enumerate(groups) if group.bounding.contains_point(cx, cy)]
    if not holding:
        return None
    return max(holding, key=lambda index: (depth[index], -groups[index].bounding.w * groups[index].bounding.h, -index))


def _panel(index: int, group: Group, depth: int, notes: DiagramNotes, palette: Palette) -> str:
    rect = group.bounding
    fill = palette.panel if depth % 2 == 0 else palette.bg
    title = _NUMBER_PREFIX.sub("", group.title)
    baseline = rect.y + PANEL_BASELINE
    room = rect.w - 2 * PANEL_PAD
    title = _fit(title, PANEL_TITLE_SIZE, room, bold=True)
    parts = [
        f'<g class="panel" id="group-{index}">',
        _rect(rect, f'rx="{PANEL_RADIUS}" fill="{fill}"'),
        f'<text class="panel-title" x="{num(rect.x + PANEL_PAD)}" y="{num(baseline)}" font-size="{PANEL_TITLE_SIZE}" '
        f'font-weight="700" fill="{palette.panel_title}">{text(title)}</text>',
    ]
    meta = notes.groups.get(group.title)
    if meta is not None:
        free = room - _width(title, PANEL_TITLE_SIZE, bold=True) - PANEL_PAD
        meta = _fit(meta, META_SIZE, free)
        if meta:
            parts.append(
                f'<text class="panel-meta" x="{num(rect.right - PANEL_PAD)}" y="{num(baseline)}" font-size="{META_SIZE}" '
                f'text-anchor="end" fill="{palette.panel_meta}">{text(meta)}</text>'
            )
    parts.append("</g>")
    return "".join(parts)


# --- nodes ----------------------------------------------------------------------------


def _terminals(nodes: Sequence[Node], defs: DefLookup, home: dict[str, int | None]) -> set[str]:
    """Output nodes drawn as terminal blocks: not bypassed, and the only kind of node in their
    innermost group (or in no group). An output node that shares its group with other nodes, such
    as a preview in the middle of a sampling stage, stays a module."""
    outputs = {node.key for node in nodes if _is_output(defs.get(node.type))}
    out: set[str] = set()
    for node in nodes:
        if node.key not in outputs or node.mode == NodeMode.BYPASS:
            continue
        group = home[node.key]
        if group is None or all(other in outputs for other, where in home.items() if where == group):
            out.add(node.key)
    return out


def _is_output(nodedef: NodeDef | None) -> bool:
    return nodedef is not None and nodedef.output_node


def _terminal_box(key: str, boxes: dict[str, Rect], home: dict[str, int | None], groups: Sequence[Group]) -> Rect:
    """The panel's inner width at the node's own height, unless that would cover another node."""
    own, group = boxes[key], home[key]
    if group is None:
        return own
    panel = groups[group].bounding
    wide = Rect(panel.x + PANEL_PAD, own.y, panel.w - 2 * PANEL_PAD, own.h)
    if wide.w <= own.w:
        return own
    if any(other != key and home[other] == group and wide.overlaps(box) for other, box in boxes.items()):
        return own
    return wide


def _module(node: Node, rect: Rect, defs: DefLookup, palette: Palette) -> str:
    nodedef = defs.get(node.type)
    bypass = node.mode == NodeMode.BYPASS
    stroke = palette.accent if bypass else palette.primary
    dash = f' stroke-dasharray="{DASH}"' if bypass else ""
    room = rect.w - 2 * TEXT_INSET
    cx, cy = rect.center
    title = _fit(title_text(node, nodedef), MODULE_TITLE_SIZE, room, bold=True)
    subtitle = None if node.collapsed else _subtitle(node, nodedef)
    if subtitle is not None:
        subtitle = _fit(subtitle, SUBTITLE_SIZE, room)
    classes = "module bypass" if bypass else "module"
    parts = [
        f'<g class="{classes}" id="node-{attr(node.key)}">',
        f"<title>{text(f'{node.type} (id {node.key})')}</title>",
        _rect(rect, f'rx="{MODULE_RADIUS}" fill="{palette.module}" stroke="{stroke}" stroke-width="{MODULE_STROKE}"{dash}'),
    ]
    title_y = cy - 2 if subtitle else cy + MODULE_TITLE_SIZE * 0.35
    parts.append(
        f'<text class="title" x="{num(cx)}" y="{num(title_y)}" font-size="{MODULE_TITLE_SIZE}" font-weight="700" '
        f'text-anchor="middle" fill="{stroke}">{text(title)}</text>'
    )
    if subtitle:
        parts.append(
            f'<text class="subtitle" x="{num(cx)}" y="{num(cy + 13)}" font-size="{SUBTITLE_SIZE}" '
            f'text-anchor="middle" fill="{palette.accent if bypass else palette.primary_soft}">{text(subtitle)}</text>'
        )
    parts.append("</g>")
    return "".join(parts)


def _terminal(node: Node, rect: Rect, defs: DefLookup, palette: Palette) -> str:
    cx, cy = rect.center
    title = _fit(title_text(node, defs.get(node.type)), TERMINAL_SIZE, rect.w - 2 * TEXT_INSET, bold=True)
    return (
        f'<g class="terminal" id="node-{attr(node.key)}">'
        f"<title>{text(f'{node.type} (id {node.key})')}</title>"
        + _rect(rect, f'rx="{MODULE_RADIUS}" fill="{palette.terminal}"')
        + f'<text class="title" x="{num(cx)}" y="{num(cy + TERMINAL_SIZE * 0.35)}" font-size="{TERMINAL_SIZE}" '
        f'font-weight="700" text-anchor="middle" fill="{palette.terminal_text}">{text(title)}</text>'
        "</g>"
    )


def _subtitle(node: Node, nodedef: NodeDef | None) -> str | None:
    """The value of the node's first dropdown or file-name widget that no link drives: a model
    name without folder and extension, a preset, a sampler."""
    if nodedef is None:
        return None
    values = node.widgets_values_named or node.widgets_values
    linked = {
        widget.get("name")
        for slot in node.inputs
        if slot.get("link") is not None and isinstance(widget := slot.get("widget"), dict)
    }
    for index, spec in enumerate(widget_layout(nodedef, values)):
        if spec.kind is not WidgetKind.VALUE or spec.name is None or spec.name in linked:
            continue
        declared = nodedef.input(spec.input_name or spec.name)
        if not ((declared is not None and declared.type == "COMBO") or "filename" in spec.name):
            continue
        value = _widget_value(values, index, spec.name)
        if value is None or isinstance(value, (dict, list)) or str(value) == "":
            continue
        return _short_value(str(value))
    return None


def _widget_value(values: Any, index: int, name: str) -> Any:
    if isinstance(values, dict):
        return values.get(name)
    if isinstance(values, list) and index < len(values):
        return values[index]
    return None


def _short_value(value: str) -> str:
    name = re.split(r"[\\/]", value)[-1] or value
    name = _EXTENSION.sub("", name) or name
    return name if len(name) <= SUBTITLE_CHARS else name[: SUBTITLE_CHARS - 1] + "…"


# --- links ----------------------------------------------------------------------------


@dataclass(frozen=True)
class _Line:
    link_id: int
    runs: tuple[tuple[Point, ...], ...]  # the link's own pieces; the last one ends at the arrow tip
    bypass: bool


def _link_lines(canvas: Canvas, nodes: dict[str, Node], facts: dict[str, BoxFacts], boxes: dict[str, Rect]) -> list[_Line]:
    """Each drawable link as right-angled runs through its reroutes. A segment several links share
    is drawn by the first link in table order only, as in the debug skin; the arrow is cut where the
    line last enters the target's box (a terminal's widened box)."""
    paths = link_paths(canvas, facts, Renderer.CLASSIC)
    links = canvas.link_map()
    pairs = Counter(frozenset((str(link.origin_id), str(link.target_id))) for link in links.values())
    segment_users = Counter(key for path in paths.values() for key in set(path.keys))
    out: list[_Line] = []
    for link_id, segments, _ in link_shapes(paths):
        path, link = paths[link_id], links[link_id]
        origin, target = str(link.origin_id), str(link.target_id)
        bypass = any(nodes[key].mode == NodeMode.BYPASS for key in (origin, target))
        alone = pairs[frozenset((origin, target))] == 1 and all(segment_users[key] == 1 for key in path.keys)
        drop = _drop(origin, target, boxes) if alone else None
        if drop is not None:
            out.append(_Line(link_id, (drop,), bypass))
            continue
        first, last = path.segments[0], path.segments[-1]
        runs: list[list[Point]] = []
        end: Point | None = None
        for segment in segments:
            piece = _elbow(segment.p0, segment.p3, leaves_output=segment is first, enters_input=segment is last)
            if runs and segment.p0 == end:
                runs[-1].extend(piece[1:])
            else:
                runs.append(piece)
            end = segment.p3
        if segments[0] is first:
            runs[0] = _leave(_simplify(runs[0]), boxes[origin])
        runs[-1] = _enter(_simplify(runs[-1]), boxes[target])
        out.append(_Line(link_id, tuple(tuple(_simplify(run)) for run in runs), bypass))
    return out


def _drop(origin: str, target: str, boxes: dict[str, Rect]) -> tuple[Point, Point] | None:
    """A short vertical arrow from the bottom of ``origin`` to the top of ``target`` when the two are
    stacked: ``target`` below, the two overlapping across at least ``STACK_OVERLAP`` of the narrower
    width, and no other box in the band between them. It runs down the middle of the narrower box
    (``origin`` when they are as wide), which always lies inside the overlap. The canvas still wires
    such a pair left to right through its slots; the figure shows the stack as the reference
    figures do. The caller checks that the link is the pair's only link and shares no reroute."""
    above, below = boxes[origin], boxes[target]
    if below.y < above.bottom:
        return None
    left, right = max(above.x, below.x), min(above.right, below.right)
    if right - left < STACK_OVERLAP * min(above.w, below.w):
        return None
    band = Rect(left, above.bottom, right - left, below.y - above.bottom)
    if any(band.overlaps(box) for key, box in boxes.items() if key not in (origin, target)):
        return None
    narrow = below if below.w < above.w else above
    x = narrow.x + narrow.w / 2
    return ((x, above.bottom), (x, below.y))


def _elbow(a: Point, b: Point, *, leaves_output: bool, enters_input: bool) -> list[Point]:
    """A right-angled path from ``a`` to ``b`` that leaves an output to the right and enters an
    input from the left. Between two anchors it turns in the middle column, or, going backward,
    runs ``LEG`` out and in and crosses on the middle row. A reroute sits in a routing channel, so a
    segment that ends or starts at one turns at the reroute's column: the small step between an
    anchor's row and the reroute's row then joins the channel's own vertical run."""
    (ax, ay), (bx, by) = a, b
    if ay == by and bx >= ax:
        return [a, b]
    if leaves_output and enters_input:
        if bx - ax >= 2 * LEG:
            mid = (ax + bx) / 2
            return [a, (mid, ay), (mid, by), b]
        mid = (ay + by) / 2
        return [a, (ax + LEG, ay), (ax + LEG, mid), (bx - LEG, mid), (bx - LEG, by), b]
    if leaves_output:
        if bx > ax:
            return [a, (bx, ay), b]
        return [a, (ax + LEG, ay), (ax + LEG, by), b]
    if enters_input:
        if ax < bx:
            return [a, (ax, by), b]
        return [a, (bx - LEG, ay), (bx - LEG, by), b]
    if ax == bx or ay == by:
        return [a, b]
    return [a, (bx, ay), b]


def _simplify(points: Sequence[Point]) -> list[Point]:
    """Without repeated points, and without the middle point of three on one line: a straight run
    keeps its ends, and a run that turns back on itself (a channel overshooting an anchor's row by a
    few pixels) is cut at its last point."""
    out: list[Point] = []
    for point in points:
        if out and point == out[-1]:
            continue
        if len(out) >= 2:
            (x0, y0), (x1, y1) = out[-2], out[-1]
            cross = (x1 - x0) * (point[1] - y1) - (y1 - y0) * (point[0] - x1)
            if abs(cross) < 1e-9:
                out[-1] = point
                continue
        out.append(point)
    return out


def _inside(point: Point, rect: Rect) -> bool:
    return rect.x <= point[0] <= rect.right and rect.y <= point[1] <= rect.bottom


def _boundary(outside: Point, inside: Point, rect: Rect) -> Point:
    """Where the segment from ``outside`` to ``inside`` crosses the edge of ``rect``."""
    (x0, y0), (x1, y1) = outside, inside
    candidates = [
        (edge - start) / delta
        for start, delta, low, high in ((x0, x1 - x0, rect.x, rect.right), (y0, y1 - y0, rect.y, rect.bottom))
        if delta != 0
        for edge in (low, high)
        if 0 <= (edge - start) / delta <= 1
    ]
    for t in sorted(candidates):
        point = (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
        if _inside(point, rect):
            return point
    return inside


def _enter(points: list[Point], rect: Rect) -> list[Point]:
    """The run cut where it last enters ``rect``; unchanged when it never comes from outside."""
    for i in range(len(points) - 1, 0, -1):
        if _inside(points[i], rect) and not _inside(points[i - 1], rect):
            return [*points[:i], _boundary(points[i - 1], points[i], rect)]
    return points


def _leave(points: list[Point], rect: Rect) -> list[Point]:
    """The run started where it first leaves ``rect``; unchanged when it starts outside."""
    for i in range(len(points) - 1):
        if _inside(points[i], rect) and not _inside(points[i + 1], rect):
            return [_boundary(points[i + 1], points[i], rect), *points[i + 1 :]]
    return points


def _link(line: _Line, palette: Palette) -> str:
    runs = [list(run) for run in line.runs]
    tip, before = runs[-1][-1], _before_tip(runs[-1])
    arrow = ""
    if before is not None:
        length = math.dist(before, tip)
        ux, uy = (tip[0] - before[0]) / length, (tip[1] - before[1]) / length
        if length > ARROW_LENGTH / 2:  # the line stops under the arrow, so its end does not show past the tip
            runs[-1][-1] = (tip[0] - ux * ARROW_LENGTH / 2, tip[1] - uy * ARROW_LENGTH / 2)
        base = (tip[0] - ux * ARROW_LENGTH, tip[1] - uy * ARROW_LENGTH)
        left = (base[0] - uy * ARROW_HALF_WIDTH, base[1] + ux * ARROW_HALF_WIDTH)
        right = (base[0] + uy * ARROW_HALF_WIDTH, base[1] - ux * ARROW_HALF_WIDTH)
        color = palette.accent if line.bypass else palette.link
        arrow = (
            f'<path class="arrow" id="arrow-{line.link_id}" d="M {pair(tip)} L {pair(left)} L {pair(right)} Z" '
            f'fill="{color}" stroke="none"/>'
        )
    style = f' stroke="{palette.accent}" stroke-dasharray="{DASH}"' if line.bypass else ""
    cls = "link bypass" if line.bypass else "link"
    d = " ".join(_rounded(run) for run in runs)
    return f'<path class="{cls}" id="link-{line.link_id}" d="{d}"{style}/>{arrow}'


def _before_tip(run: Sequence[Point]) -> Point | None:
    for point in reversed(run[:-1]):
        if point != run[-1]:
            return point
    return None


def _rounded(points: Sequence[Point]) -> str:
    """Path data for a polyline with each corner rounded to ``CORNER`` (less on short legs)."""
    parts = [f"M {pair(points[0])}"]
    for i in range(1, len(points) - 1):
        prev, here, nxt = points[i - 1], points[i], points[i + 1]
        into, out = math.dist(prev, here), math.dist(here, nxt)
        radius = min(CORNER, into / 2, out / 2)
        if radius <= 0:
            parts.append(f"L {pair(here)}")
            continue
        start = (here[0] - (here[0] - prev[0]) / into * radius, here[1] - (here[1] - prev[1]) / into * radius)
        end = (here[0] + (nxt[0] - here[0]) / out * radius, here[1] + (nxt[1] - here[1]) / out * radius)
        parts.append(f"L {pair(start)} Q {pair(here)} {pair(end)}")
    if len(points) > 1:
        parts.append(f"L {pair(points[-1])}")
    return " ".join(parts)


# --- notes ----------------------------------------------------------------------------


@dataclass(frozen=True)
class _NoteRun:
    span: Rect  # the boxes of the modules the note belongs to
    lines: tuple[str, ...]
    bracket: bool  # several modules share the note
    below: bool = False  # under its module, left-aligned, because the room beside it is taken

    @property
    def text_x(self) -> float:
        if self.below:
            return self.span.x
        if self.bracket:
            return self.span.right + BRACKET_GAP + BRACKET_WIDTH + BRACKET_TEXT_GAP
        return self.span.right + NOTE_GAP

    @property
    def text_top(self) -> float:
        if self.below:
            return self.span.bottom + NOTE_BELOW_GAP
        return self.span.center[1] - len(self.lines) * NOTE_LINE / 2

    @property
    def text(self) -> Rect:
        return Rect(self.text_x, self.text_top, max(_width(line, META_SIZE) for line in self.lines), len(self.lines) * NOTE_LINE)

    @property
    def extent(self) -> Rect:
        if self.below:
            return self.text.union(Rect(self.span.x, self.span.bottom, 0, 0))
        return Rect(self.span.right, self.text_top, self.text.right - self.span.right, self.text.h).union(
            Rect(self.span.right, self.span.y, 0, self.span.h)
        )


def _note_runs(
    notes: DiagramNotes, nodes: dict[str, Node], boxes: dict[str, Rect], home: dict[str, int | None], links: Sequence[_Line]
) -> list[_NoteRun]:
    """One run per module with a note, except that modules of one group stacked one under the other
    (overlapping columns, nothing between them) with the same note share one run and a bracket. A
    note of one module whose text beside it would touch a link or another box goes under the module
    when the text is free there."""
    noted = sorted(
        (key for key in notes.notes if key in nodes),
        key=lambda key: (home[key] is None, home[key] or 0, boxes[key].y, boxes[key].x, id_order(key)),
    )
    runs: list[list[str]] = []
    for key in noted:
        current = runs[-1] if runs else None
        if current is not None and _joins(current, key, notes, boxes, home):
            current.append(key)
        else:
            runs.append([key])
    out: list[_NoteRun] = []
    for members in runs:
        span = bounding([boxes[key] for key in members])
        run = _NoteRun(span, tuple(_wrap(notes.notes[members[0]])), len(members) > 1)
        if not run.bracket:
            others = [box for key, box in boxes.items() if key not in members]
            below = _NoteRun(run.span, run.lines, False, below=True)
            if _blocked(run.text, others, links) and not _blocked(below.text, others, links):
                run = below
        out.append(run)
    return out


def _blocked(area: Rect, boxes: Sequence[Rect], links: Sequence[_Line]) -> bool:
    """True when ``area``, with ``NOTE_CLEARANCE`` around it, touches a box or a drawn link."""
    room = area.inflate(NOTE_CLEARANCE, NOTE_CLEARANCE, NOTE_CLEARANCE, NOTE_CLEARANCE)
    if any(room.overlaps(box) for box in boxes):
        return True
    return any(
        min(a[0], b[0]) <= room.right and max(a[0], b[0]) >= room.x and min(a[1], b[1]) <= room.bottom and max(a[1], b[1]) >= room.y
        for line in links
        for run in line.runs
        for a, b in zip(run, run[1:])
    )


def _joins(run: list[str], key: str, notes: DiagramNotes, boxes: dict[str, Rect], home: dict[str, int | None]) -> bool:
    last = run[-1]
    if home[last] != home[key] or notes.notes[last] != notes.notes[key]:
        return False
    span = bounding([boxes[member] for member in run])
    box = boxes[key]
    if box.x > span.right or box.right < span.x or box.y < span.bottom:
        return False
    gap = Rect(max(span.x, box.x), span.bottom, min(span.right, box.right) - max(span.x, box.x), box.y - span.bottom)
    return not any(
        other not in run and other != key and home[other] == home[key] and _between(other_box, gap)
        for other, other_box in boxes.items()
    )


def _between(box: Rect, gap: Rect) -> bool:
    return box.x < gap.right and box.right > gap.x and box.y < gap.bottom and box.bottom > gap.y


def _wrap(note: str) -> list[str]:
    """Lines of at most ``NOTE_WRAP`` px at the note size; a word longer than that is cut by characters."""
    lines: list[str] = []
    for paragraph in note.splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            for piece in _pieces(word):
                trial = f"{line} {piece}" if line else piece
                if line and _width(trial, META_SIZE) > NOTE_WRAP:
                    lines.append(line)
                    line = piece
                else:
                    line = trial
        lines.append(line)
    return [line for line in lines if line] or [note.strip()]


def _pieces(word: str) -> list[str]:
    if _width(word, META_SIZE) <= NOTE_WRAP:
        return [word]
    pieces, piece = [], ""
    for char in word:
        if piece and _width(piece + char, META_SIZE) > NOTE_WRAP:
            pieces.append(piece)
            piece = ""
        piece += char
    return [*pieces, piece] if piece else pieces


def _note(run: _NoteRun, palette: Palette) -> str:
    parts = ['<g class="note">']
    if run.bracket:
        x = run.span.right + BRACKET_GAP
        parts.append(
            f'<path class="bracket" d="M {num(x)} {num(run.span.y)} H {num(x + BRACKET_WIDTH)} V {num(run.span.bottom)} H {num(x)}" '
            f'fill="none" stroke="{palette.accent}" stroke-width="{num(LINK_WIDTH)}"/>'
        )
    x, top = run.text_x, run.text_top
    parts.append(f'<text x="{num(x)}" y="{num(top + NOTE_BASELINE)}" font-size="{META_SIZE}" fill="{palette.accent}">')
    for index, line in enumerate(run.lines):
        parts.append(f'<tspan x="{num(x)}" y="{num(top + NOTE_BASELINE + index * NOTE_LINE)}">{text(line)}</tspan>')
    parts.append("</text></g>")
    return "".join(parts)


# --- text and shapes ------------------------------------------------------------------


def _width(value: str, size: float, *, bold: bool = False) -> float:
    return text_width(value, size) * (BOLD if bold else 1.0)


def _fit(value: str, size: float, room: float, *, bold: bool = False) -> str:
    """``value``, or its longest start that fits ``room`` with an ellipsis; empty when nothing fits."""
    if _width(value, size, bold=bold) <= room:
        return value
    for end in range(len(value) - 1, 0, -1):
        cut = value[:end].rstrip() + "…"
        if _width(cut, size, bold=bold) <= room:
            return cut
    return ""


def _rect(rect: Rect, style: str) -> str:
    return f'<rect x="{num(rect.x)}" y="{num(rect.y)}" width="{num(rect.w)}" height="{num(rect.h)}" {style}/>'


def _points_rect(points: Sequence[Point]) -> Rect:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
