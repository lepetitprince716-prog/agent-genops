"""2D minimal-area compact packing solver for presets with ``compact=True``.

Searches a deterministic set of candidate row partitions (with optional within-row
column bin-packing and under-guide sidebar tower) using 2D skyline nesting and
skyline lower-band tucking, choosing the valid layout with minimal canvas bounding
box area while respecting G1, G4, G5, G8, C3, zero-hole, and bridge-gap invariants.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Callable, Mapping

from cwc.canvas.geometry import Rect, snap_down, snap_up
from cwc.layout.inner import Part
from cwc.layout.items import GAP, Item
from cwc.layout.section import (
    BAND_GAP,
    COMPACT_ROW_GAP,
    SCREEN_W,
    TITLE_REACH,
    Links,
    Placed,
    _at_spine,
    _docks,
    _Done,
    _finish,
    _first_width,
    _hull,
    _pack,
    _split,
    _starts,
    _union,
    _wiring,
)
from cwc.layout.types import CorridorKind, Preset

_TARGET_RATIOS = (1.15, 1.30, 1.45, 1.60, 1.75, 1.90, 2.10, 2.35)
_MAX_WIDTH_CANDS = 14
_MAX_WIDTH_CANDS_LARGE = 8
_LARGE_MAIN_LEN = 18
_MAX_COL_STACK = 3
_HOLE_LIMIT = 80.0
_G9_MIN = 1.0
_G9_MAX = 2.8

AssignFn = Callable[[list[list[Item]], list[Item], Links], dict[Item, int]]
G8Check = Callable[[Part, float, float], bool]


@dataclass(frozen=True)
class _Snap:
    placed: Placed
    sections: list[list[Item]]
    coords: dict[int, tuple[float, float]]


def _build_reach(items: list[Item], links: Links, exempt: frozenset[str]) -> dict[Item, set[Item]]:
    owner = {key: item for item in items for key in item.groups}
    adj: dict[Item, set[Item]] = {item: set() for item in items}
    for a, b in links:
        if b in exempt:
            continue
        ia, ib = owner.get(a), owner.get(b)
        if ia is not None and ib is not None and ia is not ib:
            adj[ia].add(ib)
    reach: dict[Item, set[Item]] = {}
    for start in items:
        seen = {start}
        todo = [start]
        while todo:
            for nxt in adj[todo.pop()]:
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        seen.discard(start)
        reach[start] = seen
    return reach


def _has_lower_bridge(a: Item, b: Item, flat: list[Item], links: Links, exempt: frozenset[str]) -> bool:
    if not flat:
        return False
    a_keys, b_keys = set(a.groups), set(b.groups)
    low_owner = {key: item for item in flat for key in item.groups}
    fed_by_a = {low_owner[t] for s, t in links if s in a_keys and t in low_owner}
    if not fed_by_a:
        return False
    adj: dict[Item, set[Item]] = {item: set() for item in flat}
    feeds_b: set[Item] = set()
    for s, t in links:
        if t in exempt:
            continue
        if s in low_owner and t in b_keys:
            feeds_b.add(low_owner[s])
        elif s in low_owner and t in low_owner and low_owner[s] is not low_owner[t]:
            adj[low_owner[s]].add(low_owner[t])
    seen = set(fed_by_a)
    todo = list(fed_by_a)
    while todo:
        cur = todo.pop()
        if cur in feeds_b:
            return True
        for nxt in adj[cur]:
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return False


def _stack_row_into_columns(
    row: list[Item],
    flat: list[Item],
    links: Links,
    exempt: frozenset[str],
    reach: Mapping[Item, set[Item]],
    spine: int | None,
    height_cap: float,
    wrap_rows: bool,
) -> list[list[Item]]:
    """Group consecutive short main-row items into vertical columns within ``height_cap``."""
    cols: list[list[Item]] = []
    for item in row:
        is_cockpit = any(g in exempt for g in item.groups)
        if not cols or is_cockpit:
            cols.append([item])
            continue
        prev_col = cols[-1]
        prev = prev_col[-1]
        prev_cockpit = any(g in exempt for g in prev.groups)
        if (
            prev_cockpit
            or len(prev_col) >= _MAX_COL_STACK
            or _at_spine(prev, item, spine)
            or _has_lower_bridge(prev, item, flat, links, exempt)
        ):
            cols.append([item])
            continue
        if any(p in reach.get(item, ()) for p in prev_col):
            cols.append([item])
            continue
        if not wrap_rows and any(item in reach.get(p, ()) for p in prev_col):
            cols.append([item])
            continue
        stacked_h = sum(x.h for x in prev_col) + COMPACT_ROW_GAP * len(prev_col) + item.h
        if stacked_h <= height_cap:
            prev_col.append(item)
        else:
            cols.append([item])
    return cols


def _col_size(col: list[Item]) -> tuple[float, float]:
    w = max(i.w for i in col)
    h = sum(i.h for i in col) + COMPACT_ROW_GAP * (len(col) - 1)
    return w, h


def _partition_cols(
    cols: list[list[Item]],
    spine: int | None,
    first_start: float,
    later_start: float,
    width_cap: float,
) -> list[list[list[Item]]]:
    """Greedy balanced partition of column units into rows within ``width_cap``."""
    rows: list[list[list[Item]]] = []
    cur: list[list[Item]] = []
    cur_x = first_start
    for idx, col in enumerate(cols):
        cw, _ = _col_size(col)
        if not cur:
            cur.append(col)
            cur_x = (first_start if not rows else later_start) + cw
            continue
        gap = BAND_GAP if _at_spine(cur[-1][-1], col[0], spine) else GAP
        nxt_right = snap_up(cur_x + gap + cw)
        can_break = not _at_spine(cur[-1][-1], col[0], spine)
        if can_break and nxt_right > width_cap:
            rows.append(cur)
            cur = [col]
            cur_x = later_start + cw
        else:
            cur.append(col)
            cur_x = float(nxt_right)
    if cur:
        rows.append(cur)
    return rows


def _width_candidates(
    items: list[Item],
    flat: list[Item],
    guide_w: float,
    guide_h: float,
    x0: float,
    spine: int | None,
    large: bool,
) -> list[float]:
    total_area = sum(i.w * i.h for i in items) + sum(i.w * i.h for i in flat) + (guide_w * guide_h if guide_h > 0 else 0.0)
    max_w = max((i.w for i in items), default=0.0)
    full_w = x0
    for i, item in enumerate(items):
        if i:
            full_w += BAND_GAP if _at_spine(items[i - 1], item, spine) else GAP
        full_w += item.w
    cands: set[float] = {float(snap_up(full_w))}
    for r in _TARGET_RATIOS:
        w = float(snap_up(math.sqrt(max(1.0, total_area * r))))
        cands.add(max(w, float(snap_up(x0 + max_w))))
    if not large and len(items) >= 2:
        acc = x0
        for i, item in enumerate(items[:-1]):
            if i:
                acc += BAND_GAP if _at_spine(items[i - 1], item, spine) else GAP
            acc = float(snap_up(acc + item.w))
            cands.add(acc)
        if len(items) >= 3:
            cands.add(float(snap_up(full_w * 0.55)))
            cands.add(float(snap_up(full_w * 0.65)))
            cands.add(float(snap_up(full_w * 0.75)))
    ordered = sorted(w for w in cands if w >= max_w)
    limit = _MAX_WIDTH_CANDS_LARGE if large else _MAX_WIDTH_CANDS
    if len(ordered) <= limit:
        return ordered
    step = (len(ordered) - 1) / (limit - 1)
    return [ordered[round(i * step)] for i in range(limit)]


def _skyline_y(occupied: list[Rect], x: float, w: float, row_gap: float, min_y: float = 0.0) -> float:
    y = min_y
    left, right = x - GAP, x + w + GAP
    for rect in occupied:
        if rect.x < right and left < rect.right:
            y = max(y, float(snap_up(rect.bottom + row_gap)))
    return y


def _collides(occupied: list[Rect], x: float, y: float, w: float, h: float, row_gap: float) -> bool:
    for r in occupied:
        if x < r.right + GAP and r.x < x + w + GAP and y < r.bottom + row_gap and r.y < y + h + row_gap:
            return True
    return False


def _skyline_spot(
    occupied: list[Rect],
    x: float,
    w: float,
    h: float,
    min_y: float,
    row_gap: float,
) -> float:
    """Lowest ``y >= min_y`` at column ``x`` free of ``occupied`` with horizontal GAP and vertical ``row_gap``."""
    cand_ys = sorted({min_y} | {float(snap_up(r.bottom + row_gap)) for r in occupied if r.bottom + row_gap > min_y})
    for y in cand_ys:
        if not _collides(occupied, x, y, w, h, row_gap):
            return y
    return _skyline_y(occupied, x, w, row_gap, min_y)


def _pack_lower_skyline(
    bands: list[list[Item]],
    row: list[Item],
    wiring,
    want: Mapping[Item, float],
    occupied: list[Rect],
    group_box: Mapping[str, Rect],
    links: Links,
    exempt: frozenset[str],
    row_gap: float,
    width_cap: float,
    wrap_rows: bool,
    min_band_y: float,
) -> list[list[Item]]:
    """Place lower-band items into minimal-area 2D skyline pockets while respecting bridges and C3/G5."""
    bridges: set[Item] = set()
    feeds_main: dict[Item, bool] = {}
    for item in reversed(wiring.order):
        feeds_main[item] = bool(wiring.feeds[item]) or any(feeds_main[s] for s in wiring.succs[item])
    fed_main: dict[Item, bool] = {}
    for item in wiring.order:
        fed_main[item] = bool(wiring.fed[item]) or any(fed_main[p] for p in wiring.preds[item])
    for item in wiring.order:
        if feeds_main[item] and fed_main[item]:
            bridges.add(item)

    row_left = min(i.x for i in row)
    row_right = max(i.x + i.w for i in row)
    base_right = max(row_right, width_cap)
    cur_occ = list(occupied)
    cur_box = dict(group_box)
    out: list[list[Item]] = []

    for band in bands:
        placed_band: list[Item] = []
        ordered = [i for i in wiring.order if i in band]
        for item in ordered:
            item_keys = set(item.groups)
            preds_boxes = [cur_box[a] for a, b in links if b in item_keys and b not in exempt and a in cur_box]
            same_row_consumers = [row[j] for j in wiring.feeds[item]]

            cand_xs: set[float] = {float(snap_up(want[item]))}
            if item not in bridges and wrap_rows and not same_row_consumers:
                cand_xs.add(row_left)
                for r_item in row:
                    cand_xs.add(r_item.x)
                    cand_xs.add(float(snap_up(r_item.x + r_item.w + GAP)))
                for pb in preds_boxes:
                    cand_xs.add(pb.x)
                    cand_xs.add(float(snap_up(pb.right + GAP)))
                for p in placed_band:
                    cand_xs.add(float(snap_up(p.x + p.w + GAP)))
                if min_band_y == 0.0:
                    cand_xs.add(0.0)
            else:
                # Bridge or consumer-constrained lower item: anchor at dock, also consider row column starts inside bounds
                if same_row_consumers:
                    hi_x = min(c.x - item.w - GAP for c in same_row_consumers)
                    lo_x = max((row[j].x + row[j].w + GAP for j in wiring.fed[item]), default=row_left)
                    if lo_x <= hi_x:
                        cand_xs.add(float(snap_up(lo_x)))
                        cand_xs.add(float(snap_down(hi_x)))

            cur_w = max((r.right for r in cur_occ), default=row_right)
            cur_h = max((r.bottom for r in cur_occ), default=0.0)
            best_choice: tuple[tuple[float, ...], float, float] | None = None

            for raw_x in sorted(cand_xs):
                x = float(snap_up(raw_x))
                if x < 0.0:
                    continue
                if (item in bridges or same_row_consumers) and any(x + item.w > c.x for c in same_row_consumers):
                    continue
                # Avoid creating a >80px horizontal hole relative to current section boxes
                sec_spans = [(i.x, i.x + i.w) for i in row] + [(p.x, p.x + p.w) for p in placed_band]
                min_span_dist = min(
                    0.0 if (a <= x + item.w and x <= b) else min(abs(x - b), abs(a - (x + item.w))) for a, b in sec_spans
                )
                if min_span_dist > _HOLE_LIMIT:
                    continue

                min_y = min_band_y
                if x >= row_right:
                    # Lower-band items extending right of the main row stay below the shortest
                    # main-row item rather than floating up into the main row's top edge.
                    min_y = max(min_y, float(snap_up(min(i.y + i.h for i in row) + row_gap)))
                if item in bridges or same_row_consumers:
                    # Bridges belong below their main-row producers, never inline at the main row's top edge
                    for j in wiring.fed[item]:
                        min_y = max(min_y, float(snap_up(row[j].y + row[j].h + row_gap)))
                for pb in preds_boxes:
                    if x < pb.right + GAP:
                        min_y = max(min_y, float(snap_up(pb.bottom + row_gap)))

                y = _skyline_spot(cur_occ, x, item.w, item.h, min_y, row_gap)
                if x + item.w > max(base_right + 160.0, cur_w, cur_h * 1.8) and best_choice is not None:
                    continue
                new_w = max(cur_w, x + item.w)
                new_h = max(cur_h, y + item.h)
                wire_d = sum(abs(x - pb.right) + abs(y - pb.y) for pb in preds_boxes)
                score = (new_w * new_h, new_h, new_w, wire_d, y, x)
                if best_choice is None or score < best_choice[0]:
                    best_choice = (score, x, y)

            if best_choice is None:
                # Safe fallback: dock below everything
                x = float(snap_up(max(0.0, want[item])))
                y = _skyline_spot(cur_occ, x, item.w, item.h, max(min_band_y, cur_h + row_gap), row_gap)
            else:
                _, x, y = best_choice
            item.x, item.y = x, y
            rect = Rect(x, y, item.w, item.h)
            cur_occ.append(rect)
            for k in item.groups:
                cur_box[k] = rect
            placed_band.append(item)
        out.append(sorted(placed_band, key=lambda i: (i.y, i.x)))
    return out


def _lay_compact_section(
    done: _Done,
    cols: list[list[Item]],
    mine: list[list[Item]],
    links: Links,
    exempt: frozenset[str],
    x0: float,
    guide: float,
    guide_w: float,
    occupied: list[Rect],
    group_box: dict[str, Rect],
    width_cap: float,
    row_gap: float,
    sec_gap: float,
    under_guide_tower: Item | None = None,
    allow_lower_wrap: bool = True,
) -> tuple[_Done, list[Rect], dict[str, Rect]]:
    """Lay out one compact section (stacked columns + 2D skyline lower band) on top of ``occupied``."""
    mine_flat = [item for band in mine for item in band]
    # Split any bridged sub-column items before placing
    split_cols: list[list[Item]] = []
    for col in cols:
        if len(col) == 1:
            pieces = _split(col, mine_flat, links, exempt)
            for p in pieces:
                split_cols.append([p])
        else:
            split_cols.append(col)

    flat_row = ([under_guide_tower] if under_guide_tower is not None else []) + [i for col in split_cols for i in col]
    wiring = _wiring(flat_row, mine_flat, links, exempt)
    occ = list(occupied)
    gbox = dict(group_box)
    sky = BAND_GAP if done.skybridge else 0
    is_first = not done.bands
    prev_main_top = done.bands[-1].y if done.bands else -row_gap

    # Compute x positions for the main row columns
    right_of_item: dict[int, float] = {}
    idx_map = {item: j for j, item in enumerate(flat_row)}
    if under_guide_tower is not None:
        tower_gap = BAND_GAP if (split_cols and _at_spine(under_guide_tower, split_cols[0][0], done.spine)) else GAP
        first_col_x = float(snap_up(max(guide_w + GAP, under_guide_tower.w + tower_gap)))
        tower_x = float(snap_down(max(0.0, first_col_x - tower_gap - under_guide_tower.w)))
        tower_y = float(snap_up(guide + row_gap))
        under_guide_tower.x = tower_x
        under_guide_tower.y = tower_y
        right_of_item[0] = tower_x + under_guide_tower.w
        tower_rect = Rect(tower_x, tower_y, under_guide_tower.w, under_guide_tower.h)
        occ.append(tower_rect)
        for k in under_guide_tower.groups:
            gbox[k] = tower_rect
    else:
        first_col_x = x0

    # Pack columns left-to-right, widening only for spine or lower bridges
    cur_x = first_col_x
    col_xs: list[float] = []
    col_ws: list[float] = []
    for c_idx, col in enumerate(split_cols):
        cw, _ = _col_size(col)
        if c_idx == 0:
            x = cur_x
        else:
            prev_last = split_cols[c_idx - 1][-1]
            gap = BAND_GAP if _at_spine(prev_last, col[0], done.spine) else GAP
            x = float(snap_up(cur_x + gap))
        # Respect lower-band bridges feeding items in this column
        start = _starts(wiring, right_of_item)
        need = [
            s + b.w + GAP
            for item in col
            for b in mine_flat
            if idx_map[item] in wiring.feeds[b] and (s := start[b]) is not None
        ]
        if need:
            x = max(x, float(snap_up(max(need))))
        col_xs.append(x)
        col_ws.append(cw)
        for item in col:
            if len(col) > 1 and item is not col[0] and col[0].w > item.w:
                item.x = float(snap_up(x + (cw - item.w)))
            else:
                item.x = x
            right_of_item[idx_map[item]] = x + cw
        cur_x = x + cw

    # Handle sourceless lower items needing room left of the main row (same guard as section._lay)
    prev_bottom = max((b.bottom for b in done.bands), default=0.0)
    floor = 0.0 if (not is_first and prev_bottom + row_gap >= guide) else x0
    if under_guide_tower is None and mine_flat and not done.wrap_rows:
        reach = min(_docks(flat_row, wiring, x0, floor, clamp=False, wrap_rows=done.wrap_rows).values(), default=x0)
        if reach < floor:
            shift = float(snap_up(floor - reach))
            if is_first:
                cap = float(snap_down(SCREEN_W - min(_first_width(flat_row[0]), TITLE_REACH)))
                shift = max(0.0, min(shift, cap - x0))
            for c_idx, col in enumerate(split_cols):
                col_xs[c_idx] += shift
                for item in col:
                    item.x += shift

    # Compute y positions for each column via 2D skyline + upstream bottom constraints
    sec_top_floor = float(sky) if is_first else float(snap_up(prev_main_top + sec_gap))
    if not is_first and not done.wrap_rows:
        sec_top_floor = max(sec_top_floor, float(snap_up(prev_bottom + BAND_GAP)) + sky)

    same_row_col_top: dict[str, float] = {}
    prev_col_top = sec_top_floor
    for col, cx, cw in zip(split_cols, col_xs, col_ws):
        _, ch = _col_size(col)
        if is_first:
            cy = float(sky)
        else:
            min_y = max(sec_top_floor, prev_col_top)
            col_keys = {k for item in col for k in item.groups}
            for a, b in links:
                if b in col_keys and b not in exempt:
                    if a in same_row_col_top:
                        min_y = max(min_y, same_row_col_top[a])
                    elif a in gbox:
                        pb = gbox[a]
                        if cx < pb.right + GAP:
                            min_y = max(min_y, float(snap_up(pb.bottom + sec_gap)))
            cy = _skyline_spot(occ, cx, cw, ch, min_y, sec_gap)
        prev_col_top = cy
        cursor_y = cy
        for item in col:
            item.y = cursor_y
            rect = Rect(item.x, item.y, item.w, item.h)
            occ.append(rect)
            for k in item.groups:
                gbox[k] = rect
                same_row_col_top[k] = cy
            cursor_y = float(snap_up(cursor_y + item.h + row_gap))

    # Order main-row items by (x, y) keeping stacked columns in top-to-bottom order
    ordered_main = ([under_guide_tower] if under_guide_tower is not None else []) + [i for col in split_cols for i in col]
    bands = list(done.bands)
    rows = list(done.band_rows)
    first = len(bands)
    bands.append(_hull(ordered_main))
    rows.append(ordered_main)

    # Place lower bands via 2D skyline
    lower_nonempty = [band for band in mine if band]
    if lower_nonempty:
        want = _docks(flat_row, wiring, x0, floor, wrap_rows=done.wrap_rows)
        if done.wrap_rows and allow_lower_wrap:
            packed_lower = _pack_lower_skyline(
                lower_nonempty,
                ordered_main,
                wiring,
                want,
                occ,
                gbox,
                links,
                exempt,
                row_gap,
                width_cap,
                done.wrap_rows,
                min_band_y=bands[-1].y,
            )
            for members in packed_lower:
                bands.append(_hull(members))
                rows.append(members)
                for m in members:
                    rect = Rect(m.x, m.y, m.w, m.h)
                    occ.append(rect)
                    for k in m.groups:
                        gbox[k] = rect
        else:
            packed_lower = _pack(lower_nonempty, flat_row, wiring, want, wrap_rows=False)
            for members in packed_lower:
                band_left = min(m.x for m in members)
                band_right = max(m.x + m.w for m in members)
                overlap = [r for r in occ if r.x < band_right + GAP and band_left < r.right + GAP]
                top = float(snap_up(max((r.bottom for r in overlap), default=bands[-1].bottom) + BAND_GAP))
                for m in members:
                    m.y = top + m.y
                    rect = Rect(m.x, m.y, m.w, m.h)
                    occ.append(rect)
                    for k in m.groups:
                        gbox[k] = rect
                bands.append(_hull(members))
                rows.append(members)

    at = done.at + [(item, item.x, item.y) for members in rows[len(done.band_rows) :] for item in members]
    section = _union(bands[first:])
    skybridges = done.skybridges + ([Rect(section.x, section.y - sky, section.w, sky)] if sky else [])
    spines = list(done.spines)
    for a, b in zip(ordered_main, ordered_main[1:]):
        if _at_spine(a, b, done.spine):
            spines.append((len(done.sections), Rect(a.x + a.w, section.y, b.x - (a.x + a.w), section.h)))
    new_done = replace(done, bands=bands, band_rows=rows, sections=done.sections + [section], at=at, skybridges=skybridges, spines=spines)
    return new_done, occ, gbox


def _is_valid_candidate(
    placed: Placed,
    links: Links,
    exempt: frozenset[str],
    guide_rect: Rect | None,
    fits: Callable[[Placed], bool],
    g8_ok: G8Check | None,
    spine: int | None,
) -> bool:
    """Hard validity gate: no overlaps, G5 fits, C3 partial order, G8 first screen, zero-hole, bridge-gap."""
    part_rects = [Rect(x, y, part.box.w, part.box.h) for part, x, y in placed.parts]
    all_rects = part_rects + ([guide_rect] if guide_rect is not None else [])
    for i, a in enumerate(all_rects):
        for b in all_rects[i + 1 :]:
            if a.overlaps(b):
                return False

    # G8 first-screen check on the first interactive group (first part in reading order)
    if g8_ok is not None and placed.parts:
        fpart, fx, fy = placed.parts[0]
        if not g8_ok(fpart, fx, fy):
            return False

    # C3 reading-order partial order across all top-level groups
    by_group: dict[str, list[Rect]] = {}
    for item in placed.items:
        r = Rect(item.x, item.y, item.w, item.h)
        for key in item.groups:
            by_group.setdefault(key, []).append(r)
    for (a, b) in links:
        if b in exempt or a == b or a not in by_group or b not in by_group:
            continue
        if (b, a) in links:
            continue  # direct cycle edge is feedback-exempt
        for ra in by_group[a]:
            for rb in by_group[b]:
                if rb.x < ra.x - 1e-6 and rb.y < ra.bottom - 1e-6:
                    return False

    # Section-level zero-hole and bridge-gap checks matching tests/layout_cases.py
    main_bands = sorted({placed.band_of[i] for i, item in enumerate(placed.items) if item.band == 0})
    spine_spans = {(s.x, s.right) for _, s in placed.spines}
    for idx, first in enumerate(main_bands):
        last = main_bands[idx + 1] - 1 if idx + 1 < len(main_bands) else len(placed.bands) - 1
        sec_items = [item for i, item in enumerate(placed.items) if first <= placed.band_of[i] <= last]
        main_items = sorted((item for i, item in enumerate(placed.items) if placed.band_of[i] == first), key=lambda it: it.x)
        lower_items = [item for i, item in enumerate(placed.items) if first < placed.band_of[i] <= last]

        # Zero-hole on x projection (same predicate as layout_cases.column_holes)
        top_y, bot_y = placed.bands[first].y, placed.bands[last].bottom
        boxes = [r for r in part_rects if top_y <= r.y < bot_y]
        if boxes:
            spans = sorted((r.x, r.right) for r in boxes)
            reach_x = spans[0][1]
            for lx, rx in spans[1:]:
                if lx - reach_x > _HOLE_LIMIT + 1e-6:
                    return False
                reach_x = max(reach_x, rx)

        # Bridge-gap check on main row (same predicate as layout_cases.gap_faults)
        main_keys = {k for it in main_items for k in it.groups}

        def _feeds(col_item: Item, keys: set[str] | list[str]) -> bool:
            return any((a, b) in links for a in col_item.groups for b in keys if b not in exempt)

        def _closure(seed_fn, step_fn) -> list[Item]:
            found = [c for c in lower_items if seed_fn(c)]
            while True:
                more = [c for c in lower_items if c not in found and any(step_fn(c, d) for d in found)]
                if not more:
                    return found
                found += more

        fed = _closure(lambda c: any((a, b) in links for a in main_keys for b in c.groups), lambda c, d: _feeds(d, c.groups))
        feeding = _closure(lambda c: _feeds(c, main_keys), lambda c, d: _feeds(c, d.groups))
        bridges = [c for c in fed if c in feeding]
        for prev, nxt in zip(main_items, main_items[1:]):
            gap = (prev.x + prev.w, nxt.x)
            if gap[1] - gap[0] <= GAP + 1e-6:
                continue
            if gap in spine_spans:
                continue
            under = [b for b in bridges if b.x < gap[1] and gap[0] < b.x + b.w]
            if not under:
                return False
            allowed = max([prev.x + prev.w + GAP] + [c.x + c.w + GAP for c in lower_items if _feeds(c, nxt.groups)])
            if nxt.x > float(snap_up(allowed)) + 1e-6:
                return False
        _ = sec_items  # keep readable structure

    return fits(placed)


def _score_placed(
    placed: Placed,
    links: Links,
    exempt: frozenset[str],
    guide_rect: Rect | None,
    preset: Preset,
    index: int,
) -> tuple[int, float, float, float, float, int]:
    part_rects = [Rect(x, y, part.box.w, part.box.h) for part, x, y in placed.parts]
    if not part_rects:
        return (0, 0.0, 0.0, 0.0, 0.0, index)
    parts_bbox = _union(part_rects)
    # Include the guide in total area only when it is a real measured card (h < 900);
    # the 900px sentinel reserve has no guide node on untitled graphs, so ratio must
    # stay G9-healthy on the placed groups themselves too.
    has_real_guide = guide_rect is not None and guide_rect.h < 900.0
    bbox = _union(part_rects + ([guide_rect] if has_real_guide else []))
    area = bbox.w * bbox.h
    ratio = bbox.w / bbox.h if bbox.h > 0 else 99.0
    parts_ratio = parts_bbox.w / parts_bbox.h if parts_bbox.h > 0 else 99.0
    wrap_hi = max(preset.wrap_ratio, 1.0)
    if _G9_MIN <= ratio <= wrap_hi and _G9_MIN <= parts_ratio <= _G9_MAX:
        aspect_tier = 0
    elif _G9_MIN <= ratio <= _G9_MAX and _G9_MIN <= parts_ratio <= _G9_MAX:
        aspect_tier = 1
    else:
        aspect_tier = 2

    ideal_hi = min(2.0, wrap_hi) if preset.wrap_rows else wrap_hi
    if 1.15 <= ratio <= ideal_hi:
        aspect_mult = 1.0
    else:
        dist = (1.15 - ratio) if ratio < 1.15 else (ratio - ideal_hi)
        aspect_mult = 1.0 + 0.12 * dist
        if ratio < _G9_MIN:
            aspect_mult += 1.0 * (_G9_MIN - ratio)

    # Lightweight wire cost & cross-row count to keep data flow readable
    box_of: dict[str, Rect] = {}
    for item in placed.items:
        r = Rect(item.x, item.y, item.w, item.h)
        for key in item.groups:
            box_of[key] = r
    total_links = 0
    cross_links = 0
    wire_sum = 0.0
    for (a, b), count in links.items():
        if b in exempt or a not in box_of or b not in box_of:
            continue
        ra, rb = box_of[a], box_of[b]
        total_links += count
        if rb.y >= ra.bottom:
            cross_links += count
        wire_sum += count * (abs(rb.x - ra.right) + abs((rb.y + rb.h / 2) - (ra.y + ra.h / 2)))
    mean_wire = wire_sum / total_links if total_links else 0.0
    wire_mult = 1.0 + 0.03 * (cross_links / max(1, total_links)) + 0.02 * (mean_wire / 1000.0)
    weighted = round(area * aspect_mult * wire_mult, 2)
    return (aspect_tier, weighted, area, bbox.w, bbox.h, index)


def _snapshot(placed: Placed, sections: list[list[Item]]) -> _Snap:
    coords = {id(item): (item.x, item.y) for item in placed.items}
    return _Snap(placed=placed, sections=sections, coords=coords)


def _restore_coords(placed: Placed, coords: Mapping[int, tuple[float, float]]) -> None:
    for item in placed.items:
        x, y = coords[id(item)]
        item.x, item.y = x, y


def place_compact(
    preset: Preset,
    main: list[Item],
    lower: list[list[Item]],
    links: Links,
    *,
    x0: float,
    exempt: frozenset[str],
    fits: Callable[[Placed], bool],
    guide: float,
    guide_w: float,
    g8_ok: G8Check | None,
    assign_fn: AssignFn,
    baseline_fn: Callable[[], tuple[Placed, list[list[Item]]]],
) -> Placed:
    """Solve 2D minimal-area compact placement; monotonically never worse than ``baseline_fn``."""
    flat = [item for band in lower for item in band]
    all_items = main + flat
    spine = next((rule.after_slot for rule in preset.corridors if rule.kind is CorridorKind.SPINE), None)
    skybridge = any(rule.kind is CorridorKind.SKYBRIDGE for rule in preset.corridors)
    row_gap = float(BAND_GAP if skybridge else COMPACT_ROW_GAP)
    # Wrapped sections get 60 px (two routing tracks) so cross-row bus wires clear group title bars
    sec_gap = float(BAND_GAP if skybridge else 60)
    guide_rect = Rect(0.0, 0.0, guide_w, guide) if guide > 0 else None
    # The default 900px reserve already includes its bottom margin (matching section.py);
    # keep full vertical sec_gap below a real measured guide card.
    guide_occ = (
        Rect(0.0, 0.0, guide_w, max(0.0, guide - sec_gap))
        if (guide_rect is not None and guide >= 900.0)
        else guide_rect
    )

    base_placed, base_sections = baseline_fn()
    best_snap = _snapshot(base_placed, base_sections)
    best_score = _score_placed(base_placed, links, exempt, guide_rect, preset, 0)
    base_area = best_score[2]
    base_ratio = best_score[3] / best_score[4] if best_score[4] > 0 else 99.0
    wrap_hi = max(preset.wrap_ratio, 1.0)

    if len(main) <= 1 and not flat:
        return base_placed

    # Preserve clean single-row layouts when preset does not opt into aggressive under-guide folding
    # and the baseline already satisfies wrap_ratio without a G9 warning.
    base_bbox = _union([Rect(x, y, p.box.w, p.box.h) for p, x, y in base_placed.parts] + ([guide_rect] if guide_rect else []))
    if (
        not preset.compact_under_guide
        and len(base_sections) == 1
        and base_bbox.w <= preset.wrap_ratio * base_bbox.h
    ):
        return base_placed

    reach = _build_reach(all_items, links, exempt)
    large = len(main) > _LARGE_MAIN_LEN
    seen_partitions: set[tuple] = set()
    cand_idx = 0

    modes: list[tuple[bool, bool]] = [(False, False)]
    if (
        preset.compact_under_guide
        and guide > 0
        and len(main) >= 2
        and any(g in exempt for g in main[0].groups)
    ):
        tower_cand = main[0]
        tower_gap = BAND_GAP if _at_spine(tower_cand, main[1], spine) else GAP
        first_col_x = float(snap_up(max(guide_w + GAP, tower_cand.w + tower_gap)))
        tower_x = float(snap_down(max(0.0, first_col_x - tower_gap - tower_cand.w)))
        tower_parts: list[tuple[Part, float, float]] = []
        tower_cand.content.place(tower_x, float(snap_up(guide + row_gap)), tower_parts)
        if g8_ok is None or not tower_parts or g8_ok(*tower_parts[0]):
            # Try both tucking wrapped rows beside a tall sidebar and using full width below a short sidebar
            modes.append((True, True))
            modes.append((True, False))

    for under_guide, tuck_beside_tower in modes:
        tower = main[0] if under_guide else None
        flow = main[1:] if under_guide else main
        if under_guide:
            tower_gap = BAND_GAP if _at_spine(tower, flow[0], spine) else GAP  # type: ignore[arg-type]
            first_x0 = float(snap_up(max(guide_w + GAP, tower.w + tower_gap)))  # type: ignore[union-attr]
            later_x0 = first_x0 if tuck_beside_tower else 0.0
        else:
            first_x0 = x0
            later_x0 = 0.0 if preset.wrap_rows else x0

        w_caps = _width_candidates(
            flow,
            flat,
            guide_w if not under_guide else 0.0,
            guide if not under_guide else 0.0,
            first_x0,
            spine,
            large,
        )
        stack_heights: list[float] = [0.0]
        if preset.wrap_rows:
            tallest = max((i.h for i in flow if not any(g in exempt for g in i.groups)), default=0.0)
            if tallest > 0.0:
                stack_heights.append(tallest)

        for h_cap in stack_heights:
            if h_cap > 0.0:
                col_units = _stack_row_into_columns(flow, flat, links, exempt, reach, spine, h_cap, preset.wrap_rows)
            else:
                col_units = [[i] for i in flow]

            part_candidates: list[tuple[float, list[list[list[Item]]]]] = [
                (w_cap, _partition_cols(col_units, spine, first_x0, later_x0, w_cap)) for w_cap in w_caps
            ]
            if not large and len(col_units) >= 2:
                for k in range(1, len(col_units)):
                    if _at_spine(col_units[k - 1][-1], col_units[k][0], spine):
                        continue
                    two_rows = [col_units[:k], col_units[k:]]
                    r0_w = first_x0 + sum(_col_size(c)[0] for c in two_rows[0]) + GAP * max(0, len(two_rows[0]) - 1)
                    r1_w = later_x0 + sum(_col_size(c)[0] for c in two_rows[1]) + GAP * max(0, len(two_rows[1]) - 1)
                    part_candidates.append((float(snap_up(max(r0_w, r1_w))), two_rows))

            for w_cap, row_cols_list in part_candidates:
                sig = (
                    under_guide,
                    tuck_beside_tower,
                    tuple(tuple(tuple(id(x) for x in col) for col in row) for row in row_cols_list),
                )
                if sig in seen_partitions:
                    continue
                seen_partitions.add(sig)
                cand_idx += 1

                sec_rows = [
                    ([tower] if (under_guide and s == 0 and tower is not None) else []) + [i for col in rcols for i in col]
                    for s, rcols in enumerate(row_cols_list)
                ]
                assign = assign_fn(sec_rows, flat, links)
                done = _Done(skybridge=skybridge, spine=spine, wrap_rows=preset.wrap_rows)
                occ: list[Rect] = [guide_occ] if guide_occ is not None else []
                gbox: dict[str, Rect] = {}
                for s, rcols in enumerate(row_cols_list):
                    mine = [[item for item in band if assign[item] == s] for band in lower]
                    if s == 0:
                        sx0 = first_x0
                    elif under_guide:
                        if tuck_beside_tower and tower is not None:
                            right_bottom = max((r.bottom for r in occ if r.right > first_x0 - GAP), default=0.0)
                            sx0 = first_x0 if right_bottom + row_gap < tower.y + tower.h else 0.0
                        else:
                            sx0 = 0.0
                    else:
                        prev_bottom = max((b.bottom for b in done.bands), default=0.0)
                        if preset.wrap_rows and (guide <= 0 or (done.bands and prev_bottom + BAND_GAP >= guide)):
                            sx0 = 0.0
                        else:
                            sx0 = x0
                    done, occ, gbox = _lay_compact_section(
                        done,
                        rcols,
                        mine,
                        links,
                        exempt,
                        sx0,
                        guide,
                        guide_w,
                        occ,
                        gbox,
                        w_cap,
                        row_gap,
                        sec_gap,
                        under_guide_tower=tower if (under_guide and s == 0) else None,
                        allow_lower_wrap=preset.compact_under_guide,
                    )
                placed = _finish(done)
                if not _is_valid_candidate(placed, links, exempt, guide_rect, fits, g8_ok, spine):
                    continue
                score = _score_placed(placed, links, exempt, guide_rect, preset, cand_idx)
                cand_area = score[2]
                cand_ratio = score[3] / score[4] if score[4] > 0 else 99.0
                # Monotonic area & aspect guard: never bloat area above a G9-non-wide baseline,
                # never unwrap past wrap_ratio once baseline fits, and never worsen tall ratio < 1.0.
                if base_ratio <= _G9_MAX and cand_area > base_area + 1e-6:
                    continue
                if base_ratio <= wrap_hi and cand_ratio > wrap_hi + 1e-6:
                    continue
                if cand_ratio < min(_G9_MIN, base_ratio) - 1e-6:
                    continue
                if score < best_score:
                    best_score = score
                    best_snap = _snapshot(placed, sec_rows)

    # Replay _assign once for the winning partition so observers/tests reading the final _assign call see the winner
    _restore_coords(best_snap.placed, best_snap.coords)
    assign_fn(best_snap.sections, flat, links)
    return best_snap.placed
