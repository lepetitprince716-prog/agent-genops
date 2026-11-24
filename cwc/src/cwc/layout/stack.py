"""Placement along y (a preset with ``"axis": "y"``): every group is a box read top to bottom,
the boxes stack in columns, and a column too high for the canvas's width wraps into the next
column to its right.

Inside a box the members stand in up to three lanes:

- the spine: the longest chain of the group's members, top to bottom, each envelope
  ``SPINE_GAP`` below the one before; a group of one node is that node, a group of several nodes
  and no link between them has no spine;
- the left lane: the members that feed the spine or hang off it, each as high as the first spine
  node it reaches (or just below the last spine node that reaches it), pushed down where it would
  overlap the one above;
- the right lane: the output nodes (previews, savers, comparers) fed inside the group by spine
  nodes only, each as high as the last spine node that feeds it, so the link from the spine runs
  a short way right.

The output nodes take no part in the spine unless the group has nothing else, so a preview
hangs off the stage it shows. A group holding nested groups lays its own members out in lanes
and stacks its children under them, each laid out the same way on its own.

In a column every top-level box has the same left edge and width, and every lane the same x and
width, its expanded nodes widened to it (width up only), so the spines of the column form one
line. The links that come into the spines of a column from other columns each come down an
upright track (one output feeding several nodes needs one track, its links branching off it),
and a track never runs inside a frame's top-left corner, where the frontend writes the group
title over 100 to 300 px:

- a column with no left lane keeps its tracks in the gap to its left, ``TRACK`` apart, the gap
  ``COLUMN_GAP`` plus ``TRACK`` per track (the first column moves right from ``x0`` by
  ``TRACK`` per track), and in front of the spine only ``CORRIDOR_MIN``, a box margin and a
  Z's left leg;
- a column with a left lane keeps them in a corridor between the left lane and the spine, since
  a run from the gap would meet the left lane: ``CORRIDOR_BASE`` plus ``TRACK`` for every
  distinct output feeding the column, at least ``CORRIDOR_MIN`` and at most ``CORRIDOR_MAX``,
  the gap between the left lane and the spine the wider of that and ``LANE_GAP``.

A column takes as many boxes, in reading order, as keeps it at most ``wrap_ratio`` times the
width of the whole canvas high and G5 within its limit (:func:`place_stack`).

A link between two spine nodes next to each other in a column, inside a box or from the last
spine node of one box to the first of the box below, runs out of the right side and into the
left side of nodes stacked along y; it gets four waypoints, a Z: right of the spine, down to its
cross leg, left of the spine, down to the input. Inside a box the cross leg runs in the middle
of the gap between the two nodes; from one box to the next it runs under the lower box's title
band, so the left leg comes down under the title instead of through it. A link between two
columns is listed in ``LayoutResult.forced``, so routing takes it through the grid
(:func:`finish`); one that enters a spine node has a track (``LayoutResult.tracks``), shared by
the links of its output, which it comes down before it turns into its input.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, Collection, Mapping, Sequence

from cwc.annotate.types import CockpitSlot, GroupPlan, Zone
from cwc.canvas.envelope import VUE_MIN_WIDTH, Renderer, envelope, readable_width
from cwc.canvas.geometry import Rect, snap_up
from cwc.canvas.links import canvas_splines
from cwc.canvas.model import Canvas
from cwc.canvas.titles import title_rect
from cwc.layout.inner import (
    NODE_GAP,
    PAD,
    TITLE_BAND,
    Graph,
    Part,
    _dag,
    _id_key,
    _inside,
    _letter,
    _order,
    MAX_EXPANDED,
    TRACK,
    _order_key,
    _rel_envelope,
    layers_of,
    segments,
    split,
    tiers,
)
from cwc.layout.section import Placed
from cwc.layout.types import LayoutResult, Point

__all__ = [
    "COLUMN_GAP",
    "CORRIDOR_BASE",
    "CORRIDOR_MAX",
    "CORRIDOR_MIN",
    "GROUP_GAP",
    "LANE_GAP",
    "LEG",
    "SPINE_GAP",
    "Lanes",
    "crowded_split",
    "finish",
    "group_lanes",
    "place_stack",
]

LANE_GAP = 120  # between a side lane and the spine: room for a Z leg and the links beside it
SPINE_GAP = 80  # between two spine envelopes: room for a Z's cross leg
LEG = 40  # a Z's upright legs stand this far right and left of the spine lane
GROUP_GAP = 80  # between two boxes of a column
COLUMN_GAP = 120  # between two columns
# a corridor between a left lane and the spine: this, plus TRACK per output feeding in; a Z's left
# leg and a TRACK between the outermost track and the left lane
CORRIDOR_BASE = LEG + TRACK
CORRIDOR_MIN = PAD + LEG + PAD  # in front of a spine with no track there: a box margin and a Z's left leg
CORRIDOR_MAX = 400


@dataclass
class Lanes:
    """One box before its x is known. ``left``, ``spine``, ``right``: the members of each lane, top
    to bottom. ``y``: each member's ``pos`` y relative to the box top. ``children``: the nested
    parts, laid out already, each with its y. ``height``: the box height. ``segment``, ``tier``:
    as :class:`cwc.layout.inner.Part`."""

    key: str
    plan: GroupPlan
    letter: str
    left: list[str]
    spine: list[str]
    right: list[str]
    y: dict[str, float]
    children: list[tuple[Part, float]] = field(default_factory=list)
    height: float = 0.0
    segment: int = 0
    tier: int = 0


@dataclass(frozen=True)
class Widths:
    """The lane widths a box is drawn with (0 for an empty lane), the box width and the column's
    corridor in front of the spine (:func:`_corridor` with a left lane, else ``CORRIDOR_MIN``)."""

    left: float
    spine: float
    right: float
    box: float
    corridor: float = CORRIDOR_MIN

    @property
    def spine_x(self) -> float:
        """The spine lane's left edge in the box: past the left lane and the wider of ``LANE_GAP``
        and the corridor, or, with no left lane, the corridor from the box's left edge."""
        if self.left:
            return float(PAD + self.left + max(LANE_GAP, self.corridor))
        return float(self.corridor)

    @property
    def right_x(self) -> float:
        return self.spine_x + self.spine + LANE_GAP

    @property
    def track_base(self) -> float:
        """Where the tracks start, relative to the box's left edge: the k-th track (from 0)
        stands ``TRACK * (k + 1)`` left of it. With a left lane, a Z's left leg in front of the
        spine; without one, the box's left edge, so the tracks stand in the gap to its left."""
        return self.spine_x - LEG if self.left else 0.0


@dataclass(frozen=True)
class Drawn:
    """A part as drawn: its lanes and widths, by part key (nested parts included)."""

    lanes: Lanes
    widths: Widths


def _spine(graph: Graph, keys: list[str], outputs: Collection[str]) -> list[str]:
    """The longest chain through ``keys``, along the links inside them and the order edges of
    :func:`cwc.layout.inner._order` (a chain broken by a group outside keeps its order), output
    nodes left out unless every key is one. The chain ends at the deepest key, ties to the first
    in id order, and steps back through a predecessor one layer up, a real link before an order
    edge, then id order. Empty for several keys with no link between them."""
    base = [key for key in keys if key not in outputs] or list(keys)
    if len(keys) > 1 and not _inside(graph, keys):
        return []
    edges = _order(graph, base, _dag(base, _inside(graph, base)))
    layer = layers_of(base, edges)
    if not layer:
        return []
    preds: dict[str, list[tuple[bool, tuple, str]]] = {key: [] for key in base}
    for link, origin, target in edges:
        preds[target].append((link == -1, _id_key(origin), origin))
    end = min(base, key=lambda key: (-layer[key], _id_key(key)))
    chain = [end]
    while layer[chain[-1]] > 0:
        step = min(p for p in preds[chain[-1]] if layer[p[2]] == layer[chain[-1]] - 1)
        chain.append(step[2])
    return chain[::-1]


def _feeders(graph: Graph, key: str, inside: Collection[str]) -> list[str]:
    return [origin for _, origin, target in graph.edges if target == key and origin in inside]


def lanes_of(
    graph: Graph, plan: GroupPlan, key: str, letter: str, keys: list[str], outputs: Collection[str]
) -> Lanes:
    """Lay ``keys`` out in lanes along y (the module docstring); x is left to :func:`draw`."""
    spine = _spine(graph, keys, outputs)
    index = {node: i for i, node in enumerate(spine)}
    members = set(keys)
    right = [
        node
        for node in keys
        if node not in index
        and node in outputs
        and (fed := _feeders(graph, node, members))
        and all(origin in index for origin in fed)
    ]
    left = [node for node in keys if node not in index and node not in right]
    y: dict[str, float] = {}
    tops: list[float] = []
    bottoms: list[float] = []
    cursor = float(PAD + TITLE_BAND)
    for node in spine:
        rel = _rel_envelope(graph.nodes[node], graph.facts[node])
        y[node] = float(snap_up(cursor - rel.y))
        tops.append(y[node] + rel.y)
        bottoms.append(y[node] + rel.y + rel.h)
        cursor = bottoms[-1] + SPINE_GAP
    low = bottoms[-1] if bottoms else float(PAD + TITLE_BAND)

    def anchor(node: str) -> float:
        reach = graph.reach
        ahead = [index[s] for s in spine if s in reach[node]]
        if ahead:
            return float(min(ahead))
        behind = [index[s] for s in spine if node in reach[s]]
        return max(behind) + 0.5 if behind else float("inf")

    left_edges = _order(graph, left, _dag(left, _inside(graph, left)))
    left_layer = layers_of(left, left_edges)
    ordered_left = sorted(left, key=lambda node: (anchor(node), left_layer[node], _order_key(graph.notes[node], node)))
    right_at = {node: max(index[origin] for origin in _feeders(graph, node, members)) for node in right}
    ordered_right = sorted(right, key=lambda node: (right_at[node], _order_key(graph.notes[node], node)))
    for lane, want in (
        (ordered_left, lambda node: _want(anchor(node), tops, bottoms)),
        (ordered_right, lambda node: tops[right_at[node]]),
    ):
        cursor = float(PAD + TITLE_BAND)
        for node in lane:
            rel = _rel_envelope(graph.nodes[node], graph.facts[node])
            y[node] = float(snap_up(max(want(node), cursor) - rel.y))
            cursor = y[node] + rel.y + rel.h + NODE_GAP
            low = max(low, cursor - NODE_GAP)
    return Lanes(key=key, plan=plan, letter=letter, left=ordered_left, spine=spine, right=ordered_right, y=y, height=low)


def _want(anchor: float, tops: list[float], bottoms: list[float]) -> float:
    """Where a left-lane node's envelope would start: level with the spine node it reaches first,
    or just below the last spine node that reaches it; nowhere in particular (0) otherwise."""
    if anchor == float("inf"):
        return 0.0
    if anchor.is_integer():
        return tops[int(anchor)]
    return bottoms[int(anchor)] + NODE_GAP


def _stack_children(lanes: Lanes, children: list[Part]) -> None:
    """Put the nested parts under the box's own lanes, left-aligned, one below the other, and
    set the box height."""
    own = bool(lanes.spine or lanes.left or lanes.right)
    y = float(snap_up(lanes.height + NODE_GAP)) if own else float(PAD + TITLE_BAND)
    bottom = lanes.height
    for part in children:
        lanes.children.append((part, y))
        bottom = y + part.box.h
        y = float(snap_up(bottom + NODE_GAP))
    lanes.height = float(snap_up(bottom + PAD))


def group_lanes(
    graph: Graph,
    plan: GroupPlan,
    children: list[list[Part]],
    outputs: Collection[str],
    core: Collection[CockpitSlot] | None = None,
) -> list[Lanes]:
    """The boxes of one plan group, keys and letters as :func:`cwc.layout.inner.group_parts` gives
    them: the cockpit cut into tiers, another top-level group into segments unless it is optional
    (an optional module is one box, so one bypass switch turns it off), then each piece by
    :func:`crowded_split`. A group holding nested groups is one box, its children (``children``,
    drawn already) under its own lanes."""
    members = list(plan.members)
    if children:
        lanes = lanes_of(graph, plan, plan.key, "", members, outputs)
        _stack_children(lanes, [part for row in children for part in row])
        return [lanes]
    if not members:
        lanes = lanes_of(graph, plan, plan.key, "", [], outputs)
        lanes.height = float(snap_up(PAD + TITLE_BAND + PAD))
        return [lanes]
    if plan.parent is None and plan.zone is Zone.COCKPIT:
        runs = [(0, t, run) for t, run in enumerate(tiers(graph, members, core))]
    elif plan.parent is None and not plan.optional:
        runs = [(s, 0, run) for s, run in enumerate(segments(graph, members))]
    else:
        runs = [(0, 0, members)]
    pieces = [(s, t, piece) for s, t, run in runs for piece in crowded_split(graph, run)]
    if len(pieces) <= 1:
        return [_closed(lanes_of(graph, plan, plan.key, "", members, outputs))]
    out = []
    for i, (s, t, piece) in enumerate(pieces):
        lanes = _closed(lanes_of(graph, plan, f"{plan.key}/{_letter(i)}", _letter(i), piece, outputs))
        lanes.segment, lanes.tier = s, t
        out.append(lanes)
    return out


def crowded_split(graph: Graph, keys: list[str]) -> list[list[str]]:
    """C1 along y: a box grows down, so neither its number of layers nor of nodes cuts it; only
    a layer holding more than ``MAX_EXPANDED`` expanded nodes does. Such a set is cut as
    :func:`cwc.layout.inner.split` cuts it (at the layer midpoint, a single layer into chunks),
    and only the pieces that still hold such a layer are cut again."""
    layer = layers_of(keys, _order(graph, keys, _dag(keys, _inside(graph, keys))))
    crowd: dict[int, int] = {}
    for key in keys:
        if not graph.nodes[key].collapsed:
            crowd[layer[key]] = crowd.get(layer[key], 0) + 1
    if max(crowd.values(), default=0) <= MAX_EXPANDED:
        return [keys]
    count = max(layer.values()) + 1
    if count < 2:
        return split(graph, keys)
    mid = (count + 1) // 2
    return crowded_split(graph, [k for k in keys if layer[k] < mid]) + crowded_split(graph, [k for k in keys if layer[k] >= mid])


def _closed(lanes: Lanes) -> Lanes:
    lanes.height = float(snap_up(lanes.height + PAD))
    return lanes


def _need(graph: Graph, keys: Sequence[str]) -> int:
    """The width the expanded nodes of a lane are widened to: the widest of their widths, readable
    widths and the Vue minimum, snapped; 0 with no expanded node."""
    need = 0.0
    for key in keys:
        node = graph.nodes[key]
        if not node.collapsed:
            need = max(need, node.size[0], readable_width(graph.facts[key]), VUE_MIN_WIDTH)
    return snap_up(need) if need else 0


def _widen(graph: Graph, keys: Sequence[str], target: int) -> float:
    """Widen the expanded nodes of a lane to ``target`` (width up only); the lane's width."""
    width = float(target)
    for key in keys:
        node = graph.nodes[key]
        if not node.collapsed and target > node.size[0]:
            node.set_size(target, node.size[1])
        width = max(width, _rel_envelope(node, graph.facts[key]).w)
    return float(snap_up(width)) if width else 0.0


def _lane_widths(graph: Graph, boxes: Sequence[Lanes]) -> tuple[float, float, float]:
    """Widen the lanes of ``boxes`` as one column; the left, spine and right lane widths."""
    out = []
    for lane in ("left", "spine", "right"):
        keys = [key for box in boxes for key in getattr(box, lane)]
        out.append(_widen(graph, keys, _need(graph, keys)))
    return out[0], out[1], out[2]


def _widths(boxes: Sequence[Lanes], left: float, spine: float, right: float, corridor: float = CORRIDOR_MIN) -> Widths:
    """The widths every box of a column is drawn with: the lanes' and one box width holding the
    right lane when any box has one, else the spine and a Z's right leg, and every nested part."""
    probe = Widths(left, spine, right, 0.0, corridor)
    edge = float(PAD + left)
    if spine:
        edge = probe.spine_x + spine + LEG
    if right:
        edge = probe.right_x + right
    for box in boxes:
        for part, _ in box.children:
            edge = max(edge, PAD + part.box.w)
    return Widths(left, spine, right, float(snap_up(edge + PAD)), corridor)


def draw(graph: Graph, lanes: Lanes, widths: Widths) -> Part:
    """The part of ``lanes`` drawn with ``widths``: every envelope's left edge on its lane's x."""
    xs = {**dict.fromkeys(lanes.left, float(PAD)), **dict.fromkeys(lanes.spine, widths.spine_x), **dict.fromkeys(lanes.right, widths.right_x)}
    nodes: dict[str, Point] = {}
    for key, x in xs.items():
        rel = _rel_envelope(graph.nodes[key], graph.facts[key])
        nodes[key] = (x - rel.x, lanes.y[key])
    return Part(
        key=lanes.key,
        plan=lanes.plan,
        letter=lanes.letter,
        box=Rect(0, 0, widths.box, lanes.height),
        nodes=nodes,
        children=[(part, (float(PAD), y)) for part, y in lanes.children],
        segment=lanes.segment,
        tier=lanes.tier,
    )


def draw_alone(graph: Graph, lanes: Lanes, drawn: dict[str, Drawn]) -> Part:
    """``lanes`` drawn as a column of its own (a nested part, or a box before the columns are
    known), widening its nodes; recorded in ``drawn``."""
    widths = _widths([lanes], *_lane_widths(graph, [lanes]))
    drawn[lanes.key] = Drawn(lanes, widths)
    return draw(graph, lanes, widths)


@dataclass(frozen=True)
class Stacked:
    """The columns :func:`place_stack` chose: each column's boxes in reading order with their
    top-left corners, and the widths they are drawn with."""

    placed: Placed
    columns: tuple[tuple[tuple[Lanes, float, float], ...], ...]
    widths: tuple[Widths, ...]


def _cuts(heights: Sequence[float], count: int) -> tuple[int, ...]:
    """The cut of ``heights`` into ``count`` runs, in order, whose highest run (boxes and the gaps
    between them) is the lowest; among equals, the one that fills the earlier columns most. The
    indices where the runs after the first start."""
    n = len(heights)

    def high(i: int, j: int) -> float:
        return sum(heights[i:j]) + GROUP_GAP * (j - i - 1)

    best: dict[tuple[int, int], tuple[float, tuple[int, ...]]] = {}
    for start in range(n - 1, -1, -1):
        best[(start, 1)] = (high(start, n), ())
        for runs in range(2, min(count, n - start) + 1):
            options = [
                (max(high(start, end), best[(end, runs - 1)][0]), (end,) + best[(end, runs - 1)][1])
                for end in range(start + 1, n - runs + 2)
            ]
            best[(start, runs)] = min(options, key=lambda option: (option[0], tuple(-c for c in option[1])))
    return best[(0, count)][1]


def place_stack(
    graph: Graph,
    boxes: Sequence[Lanes],
    *,
    x0: float,
    wrap_ratio: float,
    fits_of: Callable[[], Callable[[Placed], bool]],
    drawn: dict[str, Drawn],
    sources: Mapping[int, tuple[str, int]],
) -> Stacked:
    """Stack ``boxes`` (top-level, in reading order) in columns from ``x0``. Takes the fewest
    columns, each cut to keep the highest column lowest, whose highest column is at most
    ``wrap_ratio`` times the width of the canvas (columns and the gaps between them, the guide
    left out) and whose placement ``fits`` (G5 within its limit); ``fits_of`` builds the check
    for the node sizes as they stand, since a column's widening moves the output anchors. With
    no such count, the fewest columns that meet the height alone; with none, one box a column.
    ``sources``: each link's output (origin key, slot), which sizes each column's corridor.
    Writes node sizes (width up only) for the columns chosen; records every part drawn in
    ``drawn``."""
    if not boxes:
        return Stacked(Placed(parts=[], bands=[], items=[], band_of=[]), (), ())
    nodes = graph.nodes
    base = {key: node.size for key, node in nodes.items()}

    def build(count: int) -> tuple[Stacked, float, float]:
        for key, size in base.items():
            if nodes[key].size != size:
                nodes[key].set_size(*size)
        bounds = (0,) + _cuts([box.height for box in boxes], count) + (len(boxes),)
        runs = [list(boxes[a:b]) for a, b in zip(bounds, bounds[1:])]
        parts: list[tuple[Part, float, float]] = []
        rects: list[Rect] = []
        columns = []
        all_widths = []
        x = x0
        gap = 0.0
        high = 0.0
        for run in runs:
            left, spine, right = _lane_widths(graph, run)
            if left:
                widths = _widths(run, left, spine, right, _corridor(graph, run, sources))
            else:
                widths = _widths(run, left, spine, right)
                outside = _spine_feeds(graph, run, sources)
                gap += TRACK * outside
            x += gap
            y = 0.0
            column = []
            for box in run:
                parts.append((draw(graph, box, widths), x, y))
                column.append((box, x, y))
                y += box.height + GROUP_GAP
            rects.append(Rect(x, 0, widths.box, y - GROUP_GAP))
            high = max(high, y - GROUP_GAP)
            columns.append(tuple(column))
            all_widths.append(widths)
            x += widths.box
            gap = COLUMN_GAP
        placed = Placed(parts=parts, bands=rects, items=[], band_of=[])
        return Stacked(placed, tuple(columns), tuple(all_widths)), high, x - x0

    chosen: int | None = None
    tall: int | None = None
    for count in range(1, len(boxes) + 1):
        stacked, high, wide = build(count)
        if high > wrap_ratio * wide:
            continue
        if tall is None:
            tall = count
        if fits_of()(stacked.placed):
            chosen = count
            break
    stacked, _, _ = build(chosen or tall or len(boxes))
    for column, widths in zip(stacked.columns, stacked.widths):
        for box, _, _ in column:
            drawn[box.key] = Drawn(box, widths)
    return stacked


def _members(column: Sequence[Lanes]) -> set[str]:
    inside: set[str] = set()
    for box in column:
        inside.update(box.left, box.spine, box.right)
        for part, _ in box.children:
            inside.update(_all_nodes(part))
    return inside


def _corridor(graph: Graph, column: Sequence[Lanes], sources: Mapping[int, tuple[str, int]]) -> float:
    """The corridor of ``column`` between its left lane and its spine (the module docstring):
    one track per distinct output outside the column that feeds a node in it."""
    inside = _members(column)
    feeding = {sources[link] for link, origin, target in graph.edges if target in inside and origin not in inside}
    return float(min(CORRIDOR_MAX, max(CORRIDOR_MIN, CORRIDOR_BASE + TRACK * len(feeding))))


def _spine_feeds(graph: Graph, column: Sequence[Lanes], sources: Mapping[int, tuple[str, int]]) -> int:
    """How many tracks :func:`_tracks` gives ``column``: the distinct outputs outside it that feed
    a spine node of it."""
    inside = _members(column)
    spine = {key for box in column for key in box.spine}
    return len({sources[link] for link, origin, target in graph.edges if target in spine and origin not in inside})


def finish(canvas: Canvas, graph: Graph, result: LayoutResult, stacked: Stacked, drawn: Mapping[str, Drawn]) -> LayoutResult:
    """``result`` with the Z waypoints of the links between spine nodes next to each other, the
    links between columns as ``forced``, the tracks, and the title text of every group as
    ``keepout``, read from the canvas as ``_write`` left it. A Z from one box to the next crosses
    under the lower box's title band, between it and the first spine node there."""
    nodes = canvas.node_map()
    curves = canvas_splines(canvas, dict(graph.facts), Renderer.CLASSIC)
    env = {key: envelope(node, graph.facts[key]) for key, node in nodes.items()}
    links: dict[tuple[str, str], list[int]] = {}
    for link, origin, target in graph.edges:
        links.setdefault((origin, target), []).append(link)
    waypoints: dict[int, tuple[Point, ...]] = dict(result.waypoints)

    def z(link: int, right: float, left: float, middle: float) -> None:
        curve = curves.get(link)
        if curve is None:
            return
        out_y, in_y = _grid(curve.p0[1]), _grid(curve.p3[1])
        right, left, middle = _grid(right + LEG), _grid(left - LEG), _grid(middle)
        waypoints[link] = ((right, out_y), (right, middle), (left, middle), (left, in_y))

    def inside(part: Part, x: float) -> None:
        lanes, widths = drawn[part.key].lanes, drawn[part.key].widths
        left, right = x + widths.spine_x, x + widths.spine_x + widths.spine
        for upper, lower in zip(lanes.spine, lanes.spine[1:]):
            for link in links.get((upper, lower), ()):
                z(link, right, left, (env[upper].bottom + env[lower].y) / 2)
        for child, (cx, _) in part.children:
            inside(child, x + cx)

    column_of: dict[str, int] = {}
    for c, column in enumerate(stacked.columns):
        for box, x, y in column:
            part = next(p for p, px, py in stacked.placed.parts if p.key == box.key)
            inside(part, x)
            for key in _all_nodes(part):
                column_of[key] = c
        for (upper, ux, uy), (lower, lx, ly) in zip(column, column[1:]):
            if not upper.spine or not lower.spine or upper.children or lower.children:
                continue
            widths = stacked.widths[c]
            left, right = ux + widths.spine_x, ux + widths.spine_x + widths.spine
            under_title = (ly + TITLE_BAND + env[lower.spine[0]].y) / 2
            for link in links.get((upper.spine[-1], lower.spine[0]), ()):
                z(link, right, left, under_title)
    forced = tuple(
        sorted(
            link
            for link, origin, target in graph.edges
            if origin in column_of and target in column_of and column_of[origin] != column_of[target]
        )
    )
    tracks = _tracks(canvas, graph, stacked, column_of, curves)
    keepout = tuple(title_rect(group) for group in canvas.groups)
    return replace(result, waypoints=waypoints, forced=forced, tracks=tracks, fence_frames=True, keepout=keepout)


def _tracks(canvas: Canvas, graph: Graph, stacked: Stacked, column_of: Mapping[str, int], curves: Mapping) -> dict[int, float]:
    """Each link from outside a column into a spine node of it, to the upright track it comes
    down: one track per output, ``TRACK`` apart leftwards from :attr:`Widths.track_base`, the
    output whose first input stands highest nearest the spine, so the routes into a column nest
    without crossing each other's turns."""
    output = {link.id: (str(link.origin_id), link.origin_slot) for link in canvas.links}
    tracks: dict[int, float] = {}
    for c, column in enumerate(stacked.columns):
        if not column:
            continue
        spine = {key for box, _, _ in column for key in box.spine}
        entering: dict[tuple[str, int], list[int]] = {}
        for link, origin, target in graph.edges:
            if target in spine and column_of.get(origin) != c and link in curves:
                entering.setdefault(output[link], []).append(link)
        order = sorted(entering, key=lambda out: (min(curves[link].p3[1] for link in entering[out]), _id_key(out[0]), out[1]))
        base = column[0][1] + stacked.widths[c].track_base
        for k, out in enumerate(order):
            for link in entering[out]:
                tracks[link] = _grid(base - TRACK * (k + 1))
    return tracks


def _all_nodes(part: Part) -> list[str]:
    out = list(part.nodes)
    for child, _ in part.children:
        out.extend(_all_nodes(child))
    return out


def _grid(value: float) -> float:
    return float(round(value / 20) * 20)
