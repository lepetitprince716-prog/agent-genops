"""Routing keeps its runs off the rectangles layout declares (``LayoutResult.keepout``).

1. a link whose plain spline crosses a keepout rectangle and has a way around it is routed
   around it, and is drawn clear of it under both renderers;
2. a link that has to be routed (it crosses a box) and whose only way is through a keepout
   rectangle takes the route it takes with no keepout declared, clear of every box at the
   default and at an unlimited reroute spline cap, and is not left unresolved;
3. a link routed only for a keepout rectangle that has no way around it keeps its plain spline,
   or the dummy chain layout gave it, and is not counted unresolved.

Each canvas is three nodes and one link, so the routes are easy to read when a case fails.
"""

import math
import unittest

from tests import support  # noqa: F401
from tests.graphs import DEFS
from tests.test_route_anchor_cells import _canvas, _node

from cwc.canvas.envelope import Renderer, box_facts, classic_box, vue_box
from cwc.canvas.geometry import Rect
from cwc.canvas.links import SEGMENTS, crosses
from cwc.canvas.reroutes import link_paths
from cwc.layout.types import LayoutResult
from cwc.route import route


def _route(canvas, keepout=(), waypoints=None):
    result = LayoutResult("stack", (), (), (), None, {}, {}, {}, waypoints=waypoints or {}, keepout=tuple(keepout))
    return route(canvas, result, DEFS)


def _drawn(canvas, cap=20.0):
    """Each renderer to link 1 as drawn through its reroutes at ``cap``."""
    nodes = canvas.node_map()
    facts = {key: box_facts(node, DEFS.get(node.type)) for key, node in nodes.items()}
    return {renderer: link_paths(canvas, facts, renderer, cap)[1].points(SEGMENTS) for renderer in Renderer}


def _boxes_crossed(canvas):
    nodes = canvas.node_map()
    facts = {key: box_facts(node, DEFS.get(node.type)) for key, node in nodes.items()}
    found = []
    for renderer, box in ((Renderer.CLASSIC, classic_box), (Renderer.VUE, vue_box)):
        boxes = {key: box(node, facts[key]).inflate(-1e-6, -1e-6, -1e-6, -1e-6) for key, node in nodes.items()}
        for cap in (20.0, math.inf):
            path = link_paths(canvas, facts, renderer, cap)[1].points(SEGMENTS)
            found += [(renderer.value, cap, key) for key, rect in boxes.items() if key not in ("1", "3") and crosses(path, rect)]
    return found


def open_line():
    """Source and target on one line with nothing between them: the plain spline is straight."""
    return _canvas(
        _node(1, "Source", (0, 100), (300, 60)),
        _node(2, "Aside", (0, 600), (300, 60)),
        _node(3, "Target", (1200, 100), (300, 60)),
    )


def blocked_line():
    """Source and target on one line with a box between them, so the link has to be routed."""
    return _canvas(
        _node(1, "Source", (0, 100), (300, 60)),
        _node(2, "Obstacle", (520, 40), (300, 180)),
        _node(3, "Target", (1200, 100), (300, 60)),
    )


ACROSS = Rect(600, 80, 200, 60)  # across the straight line between source and target
BEFORE_TARGET = Rect(1060, -60, 120, 360)  # over every grid point a route could enter the target from


class KeepoutTest(unittest.TestCase):
    def test_routed_around_a_keepout(self):
        plain = open_line()
        self.assertEqual(_route(plain).rerouted, ())
        self.assertTrue(all(crosses(path, ACROSS) for path in _drawn(plain).values()))
        canvas = open_line()
        result = _route(canvas, [ACROSS])
        self.assertEqual(result.rerouted, (1,))
        self.assertEqual(result.unresolved, ())
        for renderer, path in _drawn(canvas).items():
            self.assertFalse(crosses(path, ACROSS), renderer.value)
        self.assertEqual(_boxes_crossed(canvas), [])

    def test_falls_back_to_the_route_without_the_keepout(self):
        plain = blocked_line()
        self.assertEqual(_route(plain).rerouted, (1,))
        self.assertTrue(all(crosses(path, BEFORE_TARGET) for path in _drawn(plain).values()))
        canvas = blocked_line()
        result = _route(canvas, [BEFORE_TARGET])
        self.assertEqual(result.rerouted, (1,))
        self.assertEqual(result.unresolved, ())
        self.assertEqual(canvas.raw["extra"], plain.raw["extra"])
        self.assertEqual(_boxes_crossed(canvas), [])

    def test_a_link_routed_only_for_a_keepout_keeps_its_spline(self):
        canvas = open_line()
        result = _route(canvas, [BEFORE_TARGET])
        self.assertEqual(result.rerouted, ())
        self.assertEqual(result.unresolved, ())
        self.assertNotIn("reroutes", canvas.raw.get("extra", {}))

    def test_a_dummy_chain_through_a_keepout_is_kept_when_nothing_clears_it(self):
        chain = ((600.0, 120.0), (900.0, 120.0))
        canvas = open_line()
        result = _route(canvas, [BEFORE_TARGET], {1: chain})
        self.assertEqual((result.rerouted, result.dummy, result.unresolved), ((1,), 1, ()))
        self.assertEqual([tuple(r["pos"]) for r in canvas.raw["extra"]["reroutes"]], [(600, 120), (900, 120)])


if __name__ == "__main__":
    unittest.main()
