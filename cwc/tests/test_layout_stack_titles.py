"""Under ``stack`` no link is drawn over the text of a group title: neither the uprights
:func:`cwc.layout.stack.finish` places itself nor the runs routing places through the grid.

The frontend draws a group title in 20 px Inter, left-aligned 10 px inside the frame, in a 30 px
title bar, and does not clip it (``LGraphGroup.draw`` in ComfyUI_frontend 1.59.1); the
``font_size`` a canvas writes is not read there. The title text is taken as that bar from 10 px
in, as wide as :func:`cwc.canvas.textwidth.text_width` gives the title at 20 px, 4 px wider on
each side. The rectangle is written out here from that drawing code rather than taken from the
compiler, so a wrong rectangle in the compiler does not pass for a right one.

1. each Z, as its four waypoints and as drawn under either renderer, meets no title text;
2. each link's upright run down the track layout gave it meets no title text;
3. every link, as the polyline of its reroutes and as drawn under either renderer, meets no
   title text;
4. the check finds a title moved under a Z leg, one moved under a track and one moved under a
   routed run.

The widest title in these cases is about 310 px; a longer one can still reach a Z's right leg, or
a track in the corridor beside a left lane, since neither moves for a title.
"""

from __future__ import annotations

import copy
import json
import unittest

from tests import support
from tests.test_layout_stack import _stack_canvases, _uprights

from cwc.canvas.envelope import Renderer
from cwc.canvas.geometry import Rect
from cwc.canvas.links import crosses
from cwc.canvas.reroutes import Reroutes
from cwc.canvas.textwidth import text_width
from cwc.nodedefs.registry import NodeDefs
from cwc.pipeline import compile_document
from cwc.verify.geometry_view import GeometryView

TITLE_FONT = 20
TITLE_INSET = 10
TITLE_BAR = 30
MARGIN = 4
SOURCES = support.ROOT / "docs" / "images" / "src"


def _canvases():
    """Every canvas of :func:`tests.test_layout_stack._stack_canvases` and the README's stack
    pictures: name to the canvas, the layout result and the node definitions."""
    found = dict(_stack_canvases())
    core = NodeDefs.load()
    for name in ("landscape", "hires"):
        out = compile_document(json.loads((SOURCES / f"{name}.json").read_text()), core, preset="stack")
        found[name] = (out.canvas, out.layout, core)
    return found


def title_rects(canvas) -> list[tuple[str, Rect]]:
    """Each group's title text as the frontend draws it, widened by ``MARGIN``."""
    out = []
    for group in canvas.groups:
        frame = group.bounding
        width = text_width(group.title, TITLE_FONT)
        out.append((group.title, Rect(frame.x + TITLE_INSET - MARGIN, frame.y, width + 2 * MARGIN, TITLE_BAR)))
    return out


def z_hits(canvas, result, defs) -> list[tuple]:
    """Each Z (``result.waypoints``) whose waypoints, or whose curve under a renderer, meet a
    title's text."""
    titles = title_rects(canvas)
    samples = GeometryView.build(canvas, defs).samples
    found = []
    for link, points in sorted(result.waypoints.items()):
        drawn = {"waypoints": list(points)}
        for renderer in Renderer:
            drawn[renderer.value] = [p for part in samples[renderer].get(link, ()) for p in part]
        for title, rect in titles:
            for how, path in drawn.items():
                if crosses(path, rect):
                    found.append((link, title, how))
    return found


def track_hits(canvas, result) -> list[tuple]:
    """Each upright run on a link's track (``result.tracks``) that meets a title's text."""
    titles = title_rects(canvas)
    found = []
    for link, x, top, bottom in _uprights(canvas):
        if result.tracks.get(link) != x:
            continue
        for title, rect in titles:
            if crosses([(x, top), (x, bottom)], rect):
                found.append((link, x, (top, bottom), title))
    return found


def link_hits(canvas, defs) -> list[tuple]:
    """Each link whose reroutes, as a polyline, or whose curve under a renderer meets a title's
    text."""
    titles = title_rects(canvas)
    samples = GeometryView.build(canvas, defs).samples
    table = Reroutes.read(canvas)
    found = []
    for link in canvas.links:
        drawn = {"reroutes": [table.points[r] for r in table.chain(link.id)]}
        for renderer in Renderer:
            drawn[renderer.value] = [p for part in samples[renderer].get(link.id, ()) for p in part]
        for title, rect in titles:
            for how, path in drawn.items():
                if len(path) > 1 and crosses(path, rect):
                    found.append((link.id, title, how))
    return found


class Titles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.canvases = _canvases()

    def test_no_z_meets_a_title(self):
        zs = 0
        for name, (canvas, result, defs) in self.canvases.items():
            zs += len(result.waypoints)
            with self.subTest(case=name):
                self.assertEqual(z_hits(canvas, result, defs), [])
        self.assertGreater(zs, 50)

    def test_no_track_run_meets_a_title(self):
        runs = 0
        for name, (canvas, result, _) in self.canvases.items():
            runs += sum(1 for link, x, _, _ in _uprights(canvas) if result.tracks.get(link) == x)
            with self.subTest(case=name):
                self.assertEqual(track_hits(canvas, result), [])
        self.assertGreater(runs, 50)

    def test_no_link_meets_a_title(self):
        routed = 0
        for name, (canvas, _, defs) in self.canvases.items():
            routed += len(canvas.link_extensions)
            with self.subTest(case=name):
                self.assertEqual(link_hits(canvas, defs), [])
        self.assertGreater(routed, 100)

    def test_a_title_under_a_z_leg_is_found(self):
        canvas, result, defs = copy.deepcopy(self.canvases["landscape"])
        link, points = next(iter(sorted(result.waypoints.items())))
        (x, top), (_, bottom) = points[2], points[3]
        group = canvas.groups[0]
        group.set_bounding(Rect(x - TITLE_INSET - 20, (top + bottom) / 2 - TITLE_BAR / 2, group.bounding.w, group.bounding.h))
        self.assertIn(link, {hit[0] for hit in z_hits(canvas, result, defs)})

    def test_a_title_under_a_track_is_found(self):
        canvas, result, _ = copy.deepcopy(self.canvases["landscape"])
        link, x, top, bottom = next(u for u in _uprights(canvas) if result.tracks.get(u[0]) == u[1])
        group = canvas.groups[0]
        group.set_bounding(Rect(x - TITLE_INSET - 20, (top + bottom) / 2 - TITLE_BAR / 2, group.bounding.w, group.bounding.h))
        self.assertIn(link, {hit[0] for hit in track_hits(canvas, result)})


    def test_a_title_under_a_routed_run_is_found(self):
        canvas, _, defs = copy.deepcopy(self.canvases["landscape"])
        table = Reroutes.read(canvas)
        chains = {link.id: [table.points[r] for r in table.chain(link.id)] for link in canvas.links}
        link, a, b = next(
            (link, a, b) for link, chain in chains.items() for a, b in zip(chain, chain[1:]) if a[1] == b[1] and abs(a[0] - b[0]) >= 100
        )
        group = canvas.groups[0]
        x, y = (a[0] + b[0]) / 2, a[1]
        group.set_bounding(Rect(x - TITLE_INSET - 20, y - TITLE_BAR / 2, group.bounding.w, group.bounding.h))
        hits = {(hit[0], hit[2]) for hit in link_hits(canvas, defs)}
        self.assertIn((link, "reroutes"), hits)

if __name__ == "__main__":
    unittest.main()
