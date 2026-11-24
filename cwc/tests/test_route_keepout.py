"""Routing keeps its runs off the rectangles layout declares (``LayoutResult.keepout``).

1. a link whose plain spline crosses a keepout rectangle and has a way around it is routed
   around it, and is drawn clear of it under both renderers; a keepout blocks the grid as a node
   box there does, so the route around it is the route around such a box;
2. a link that has to be routed (it crosses a box) and whose only way is through a keepout
   rectangle is routed through a grid without the keepout, clear of every box at the default and
   at an unlimited reroute spline cap, and is not left unresolved. With no other output in its
   way that is the route it takes with no keepout declared. The grids with and without the
   keepout share one track table, so such a route does not run on a grid line another output
   took to go around a keepout, and its channels are named in the grid it was routed in;
3. a link routed only for a keepout rectangle that has no way around it, or whose every way
   still meets it as drawn, keeps its plain spline, or the dummy chain layout gave it, and is not
   counted unresolved. That holds for a dummy chain clear of every box even when the link's plain
   spline crosses one, and for a link that leaves its output along another link's route through
   the keepout;
4. a dummy chain that crosses a box is routed, and is left unresolved when no route clears it.

Each canvas is three to five nodes, so the routes are easy to read when a case fails.
"""

import math
import unittest

from tests import support  # noqa: F401
from tests.graphs import DEFS
from tests.test_route_anchor_cells import _canvas, _node

from cwc.canvas.envelope import Renderer, box_facts, classic_box, envelope, vue_box
from cwc.canvas.geometry import Rect
from cwc.canvas.links import SEGMENTS, crosses
from cwc.canvas.model import Canvas
from cwc.canvas.reroutes import Reroutes, link_paths
from cwc.layout.types import LayoutResult
from cwc.route import route
from cwc.route.grid import Grid


def _route(canvas, keepout=(), waypoints=None):
    result = LayoutResult("stack", (), (), (), None, {}, {}, {}, waypoints=waypoints or {}, keepout=tuple(keepout))
    return route(canvas, result, DEFS)


def _drawn(canvas, cap=20.0, link=1):
    """Each renderer to ``link`` as drawn through its reroutes at ``cap``."""
    nodes = canvas.node_map()
    facts = {key: box_facts(node, DEFS.get(node.type)) for key, node in nodes.items()}
    return {renderer: link_paths(canvas, facts, renderer, cap)[link].points(SEGMENTS) for renderer in Renderer}


def _chain(canvas, link=1):
    """The reroutes ``link`` passes through, output side first."""
    table = Reroutes.read(canvas)
    return [tuple(table.points[r]) for r in table.chain(link)]


def _common_runs(a, b):
    """The stretches of grid line two reroute chains both run along: a horizontal or vertical
    segment of one overlapping one of the other by more than a point."""
    found = []
    for p, q in zip(a, a[1:]):
        for r, t in zip(b, b[1:]):
            for axis in (0, 1):
                along, across = 1 - axis, axis
                if p[across] == q[across] == r[across] == t[across]:
                    lo = max(min(p[along], q[along]), min(r[along], t[along]))
                    hi = min(max(p[along], q[along]), max(r[along], t[along]))
                    if hi > lo:
                        found.append(((p, q), (r, t)))
    return found


def _two_outputs(ay):
    """Output B (node 2, link 1) has to be routed around an obstacle; output A (node 1, link 2)
    runs a straight line above it at ``ay``, from left of B's source to right of B's target."""
    a_src = _node(1, "SourceA", (-200, ay), (300, 60))
    b_src = _node(2, "SourceB", (0, 100), (300, 60))
    b_dst = _node(3, "TargetB", (1200, 100), (300, 60))
    obstacle = _node(4, "Obstacle", (520, 40), (300, 180))
    a_dst = _node(5, "TargetA", (1600, ay), (300, 60))
    a_src["outputs"] = [{"name": "o", "type": "X", "links": [2]}]
    b_src["outputs"] = [{"name": "o", "type": "X", "links": [1]}]
    b_dst["inputs"] = [{"name": "i", "type": "X", "link": 1}]
    a_dst["inputs"] = [{"name": "i", "type": "X", "link": 2}]
    return Canvas(
        {
            "last_node_id": 5,
            "last_link_id": 2,
            "nodes": [a_src, b_src, b_dst, obstacle, a_dst],
            "links": [[1, 2, 0, 3, 0, "X"], [2, 1, 0, 5, 0, "X"]],
            "groups": [],
            "config": {},
            "extra": {},
            "version": 0.4,
        }
    )


def _one_output_two_inputs(branch=True, branch_y=700):
    """One output feeding a target behind an obstacle (link 1) and, with ``branch``, a target at
    ``branch_y`` (link 2)."""
    source = _node(1, "Source", (0, 100), (300, 60))
    obstacle = _node(2, "Obstacle", (520, 90), (300, 80))
    near = _node(3, "Target1", (1200, 100), (300, 60))
    below = _node(4, "Target2", (1200, branch_y), (300, 60))
    source["outputs"] = [{"name": "o", "type": "X", "links": [1, 2] if branch else [1]}]
    near["inputs"] = [{"name": "i", "type": "X", "link": 1}]
    below["inputs"] = [{"name": "i", "type": "X", "link": 2 if branch else None}]
    return Canvas(
        {
            "last_node_id": 4,
            "last_link_id": 2,
            "nodes": [source, obstacle, near, below],
            "links": [[1, 1, 0, 3, 0, "X"]] + ([[2, 1, 0, 4, 0, "X"]] if branch else []),
            "groups": [],
            "config": {},
            "extra": {},
            "version": 0.4,
        }
    )


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


    def test_a_keepout_blocks_the_grid_as_a_box_there_does(self):
        wall = _node(2, "Wall", (600, 90), (200, 40))
        boxed = _canvas(_node(1, "Source", (0, 100), (300, 60)), wall, _node(3, "Target", (1200, 100), (300, 60)))
        self.assertEqual(_route(boxed).rerouted, (1,))
        rect = envelope(boxed.node_map()["2"], box_facts(boxed.node_map()["2"], DEFS.get("T")))
        canvas = open_line()
        self.assertTrue(all(crosses(path, rect) for path in _drawn(canvas).values()))
        result = _route(canvas, [rect])
        self.assertEqual(result.rerouted, (1,))
        self.assertEqual(canvas.raw["extra"]["reroutes"], boxed.raw["extra"]["reroutes"])

    def test_a_keepout_over_a_node_changes_nothing(self):
        plain = blocked_line()
        before = _route(plain)
        canvas = blocked_line()
        obstacle = canvas.node_map()["2"]
        result = _route(canvas, [envelope(obstacle, box_facts(obstacle, DEFS.get("T")))])
        self.assertEqual(canvas.raw["extra"], plain.raw["extra"])
        self.assertEqual(result, before)

    def test_a_link_whose_every_route_meets_the_keepout_as_drawn_keeps_its_spline(self):
        # the keepout covers the end of the input's approach but none of the grid points a route
        # can reach the input from, so the search finds routes the drawn curve still takes into it
        end = Rect(1160, 95, 40, 20)
        canvas = open_line()
        self.assertTrue(any(crosses(path, end) for path in _drawn(canvas).values()))
        result = _route(canvas, [end])
        self.assertEqual((result.rerouted, result.unresolved), ((), ()))
        self.assertNotIn("reroutes", canvas.raw.get("extra", {}))

    def test_a_dummy_chain_through_a_keepout_is_routed_around_it(self):
        chain = ((600.0, 120.0), (900.0, 120.0))
        canvas = open_line()
        result = _route(canvas, [ACROSS], {1: chain})
        self.assertEqual((result.rerouted, result.dummy, result.unresolved), ((1,), 0, ()))
        for renderer, path in _drawn(canvas).items():
            self.assertFalse(crosses(path, ACROSS), renderer.value)
        self.assertEqual(_boxes_crossed(canvas), [])

    def test_a_dummy_chain_clear_of_the_boxes_is_kept_when_the_plain_spline_crosses_one(self):
        chain = ((400.0, 300.0), (900.0, 300.0))  # under the obstacle
        plain = blocked_line()
        self.assertEqual(_route(plain, (), {1: chain}).dummy, 1)
        canvas = blocked_line()
        result = _route(canvas, [BEFORE_TARGET], {1: chain})
        self.assertEqual((result.rerouted, result.dummy, result.unresolved), ((1,), 1, ()))
        self.assertEqual(canvas.raw["extra"], plain.raw["extra"])

    def test_a_dummy_chain_across_a_box_with_no_route_is_unresolved(self):
        # the target's box leaves no free grid point right of the source: nothing can be routed
        canvas = _canvas(
            _node(1, "Source", (0, 100), (300, 60)),
            _node(2, "Aside", (0, 400), (300, 60)),
            _node(3, "Target", (320, 100), (300, 60)),
        )
        self.assertEqual(_route(canvas).rerouted, ())
        result = _route(canvas, (), {1: ((150.0, 420.0), (250.0, 440.0))})
        self.assertEqual((result.rerouted, result.dummy, result.unresolved), ((), 0, (1,)))

    def test_a_link_that_leaves_along_a_route_through_the_keepout_keeps_its_spline(self):
        start = Rect(305, 60, 60, 140)  # over every grid point right of the output
        plain = _one_output_two_inputs()
        self.assertEqual(_route(plain).rerouted, (1,))
        self.assertTrue(all(crosses(path, start) for path in _drawn(plain, link=2).values()))
        canvas = _one_output_two_inputs()
        result = _route(canvas, [start])
        self.assertEqual((result.rerouted, result.unresolved), ((1,), ()))
        self.assertEqual(_chain(canvas, 2), [])

    def test_a_run_shared_with_a_fallback_route_keeps_the_channel_of_the_grid_that_routed_it(self):
        # link 1 goes around the obstacle in a grid with the keepout. Link 2 leaves along link 1's
        # route, but every way into its input meets the keepout there, so it is routed again in a
        # grid without it. The runs it repeats stay named as link 1 routed them
        entry = Rect(1060, 240, 120, 180)  # over every grid point a route could enter Target2 from
        alone = _one_output_two_inputs(branch=False, branch_y=300)
        trunk = _route(alone, [entry])
        self.assertEqual((trunk.rerouted, trunk.unresolved), ((1,), ()))
        self.assertTrue(any("keepout:" in channel.id for channel in trunk.channels))
        canvas = _one_output_two_inputs(branch_y=300)
        result = _route(canvas, [entry])
        self.assertEqual((result.rerouted, result.unresolved), ((1, 2), ()))
        # link 2 repeats link 1's route and is not clear of the keepout: no grid with it routed it
        self.assertEqual(_chain(canvas, 2)[: len(_chain(canvas, 1))], _chain(canvas, 1))
        self.assertTrue(all(crosses(path, entry) for path in _drawn(canvas, link=2).values()))
        for channel in trunk.channels:
            self.assertEqual(
                [(c.id, c.free) for c in result.channels if c.id == channel.id],
                [(channel.id, channel.free)],
            )

    def test_a_fallback_route_keeps_off_a_track_taken_for_a_keepout(self):
        across_a = Rect(700, -30, 80, 80)  # across output A's straight line
        far = Rect(5000, 5000, 40, 20)  # widens the grids' bounds, so their edge codes change
        for keepout in ([BEFORE_TARGET, across_a], [BEFORE_TARGET, across_a, far]):
            with self.subTest(keepout=len(keepout)):
                plain = _two_outputs(-20)
                self.assertEqual(_route(plain).rerouted, (1,))
                canvas = _two_outputs(-20)
                result = _route(canvas, keepout)
                self.assertEqual((result.rerouted, result.unresolved), ((1, 2), ()))
                a, b = _chain(canvas, 2), _chain(canvas, 1)
                # B with no keepout declared would run along A's route around its keepout
                self.assertNotEqual(_common_runs(_chain(plain, 1), a), [])
                self.assertEqual(_common_runs(b, a), [])
                for renderer, path in _drawn(canvas, link=2).items():
                    self.assertFalse(crosses(path, across_a), renderer.value)

    def test_a_fallback_route_is_named_in_the_grid_without_the_keepout(self):
        # inside the boxes' bounds: a keepout reaching past them widens the bounds both grids
        # share, and with them the strips along the bounds
        goal = Rect(1060, 60, 120, 140)  # over every grid point a route could enter the target from
        plain = blocked_line()
        before = _route(plain)
        self.assertTrue(all(crosses(path, goal) for path in _drawn(plain).values()))
        canvas = blocked_line()
        result = _route(canvas, [goal])
        self.assertEqual(canvas.raw["extra"], plain.raw["extra"])
        self.assertEqual(result.channels, before.channels)


class SharedGridTest(unittest.TestCase):
    def test_grids_with_and_without_the_keepout_share_bounds_and_tracks(self):
        box = ("1", Rect(0, 0, 300, 60))
        far = Rect(5000, 5000, 40, 20)
        holding = Grid.build([box, ("keepout:0", far)], 10.0)
        without = Grid.build([box], 10.0, holding.used, extent=[far])
        self.assertEqual((without.lo, without.hi), (holding.lo, holding.hi))
        path = [(20, 10), (21, 10), (22, 10)]
        holding.claim(path, "a")
        without.claim(path, "b")
        self.assertEqual(holding.shared_edges(), 2)
        self.assertEqual(without.shared_edges(), 2)


if __name__ == "__main__":
    unittest.main()
