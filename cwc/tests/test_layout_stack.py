"""The ``stack`` preset: groups read top to bottom, stacked in columns (:mod:`cwc.layout.stack`).

The fixture ``fixtures/layout/stack_two_pass.json`` is a two-pass image workflow with a preview
after each stage, a model chain cut by an optional LoRA group, and an optional A/B module that
reruns both passes without the patch node and compares each stage in an
``ImageCompare``. Its node definitions are a real ``/object_info`` of the fifteen classes it uses,
with the model file lists replaced by the four generic names the workflow uses.

1. the compile has no geometry finding;
2. each box's spine reads down, the spines of a column on one x, and each link between spine
   neighbours is a four-point Z whose upright legs stand ``LEG`` outside the spine;
3. previews and comparers fed by the spine stand in the right lane, level with the spine node
   feeding them, inside the frame and clear of the Z legs;
4. an optional module is one frame however many layers it has, also when a path leaves it
   through a required step and comes back; two optional groups apart from each other are two
   frames; only a layer of more than twelve expanded nodes cuts a group; under every preset no
   node outside an optional module stands in the rectangle of one of its frames, since ComfyUI
   takes a group's members from its rectangle and one bypass switch turns them all off;
5. a column's corridor in front of the spine is ``CORRIDOR_BASE`` plus ``TRACK`` per distinct
   output feeding the column from outside, within ``CORRIDOR_MIN`` and ``CORRIDOR_MAX``;
6. the links between columns, and only they, are ``forced``, and routing routes each of them;
   one that enters a spine node comes down its track in the corridor and turns once, level with
   its input, into a straight run to it; no upright run of any link stands closer than a grid
   step to the left or right side of a frame it runs beside;
7. the output is the same byte for byte on a second run;
8. small cases: an empty group, one node, no spine, a loop, a nested group.
"""

from __future__ import annotations

import copy
import json
import unittest
from types import SimpleNamespace

from tests import support
from tests.graphs import DEFS, compiled, node, txt2img
from tests.layout_cases import routed
from tests.test_layout_frontend import cases, nested

from cwc.annotate import annotate, apply_notes
from cwc.annotate.types import GroupPlan, Zone
from cwc.canvas.envelope import Renderer, box_facts, envelope
from cwc.canvas.geometry import GRID, Rect
from cwc.canvas.links import canvas_splines
from cwc.canvas.reroutes import Reroutes
from cwc.layout import stack
from cwc.layout.inner import MAX_EXPANDED, PAD, TRACK, Graph
from cwc.layout.presets import get_preset, load_presets
from cwc.nodedefs.registry import NodeDefs
from cwc.pipeline import compile_document

FIXTURE = support.FIXTURES / "layout" / "stack_two_pass.json"
OBJECT_INFO = support.FIXTURES / "layout" / "stack_two_pass.object_info.json"
STACK = get_preset("stack")
GEOMETRY = ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "C1", "C2", "C3", "C4", "C6")

BASE_SPINE = ("base_sampler", "base_decode")
UPSCALE_SPINE = ("up_scale", "up_encode", "up_sampler", "up_decode")
AB_SPINE = ("ab_base_sampler", "ab_base_decode", "ab_up_scale", "ab_up_encode", "ab_up_sampler", "ab_up_decode")
AB = AB_SPINE + ("ab_compare_base", "ab_compare_up")


def _grid(value: float) -> float:
    return float(round(value / 20) * 20)


def _compile():
    defs = NodeDefs.load(object_info=json.loads(OBJECT_INFO.read_text()))
    return compile_document(json.loads(FIXTURE.read_text()), defs, preset="stack"), defs


class TwoPass(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out, cls.defs = _compile()
        cls.key = dict(cls.out.authoring.ids)
        nodes = cls.out.canvas.node_map()
        cls.env = {a: envelope(nodes[k], box_facts(nodes[k], cls.defs.get(nodes[k].type))) for a, k in cls.key.items()}
        cls.frames = [g.bounding for g in cls.out.canvas.groups]
        membership = cls.out.layout.membership
        cls.frame = {a: cls.frames[membership[k]] for a, k in cls.key.items()}
        lefts = sorted({frame.x for frame in cls.frames})
        cls.column = {k: lefts.index(cls.frames[membership[k]].x) for k in cls.key.values()}
        cls.links = {link.id: link for link in cls.out.canvas.links}

    def _link(self, origin: str, target: str) -> int:
        o, t = self.key[origin], self.key[target]
        found = [link.id for link in self.links.values() if str(link.origin_id) == o and str(link.target_id) == t]
        self.assertEqual(len(found), 1, (origin, target))
        return found[0]

    def test_compile_has_no_geometry_finding(self):
        codes = sorted({f.code.value for f in self.out.report.findings})
        self.assertTrue(self.out.report.ok, codes)
        self.assertFalse(set(codes) & set(GEOMETRY), codes)
        self.assertEqual(self.out.routes.unresolved, ())

    def test_spines_read_down_on_one_x(self):
        for spine in (BASE_SPINE + UPSCALE_SPINE, AB_SPINE):
            rects = [self.env[a] for a in spine]
            self.assertEqual({r.x for r in rects}, {rects[0].x}, spine)
            for upper, lower in zip(rects, rects[1:]):
                self.assertLess(upper.bottom, lower.y, spine)

    def test_spine_neighbours_are_z_links(self):
        pairs = [
            pair
            for spine in (BASE_SPINE + UPSCALE_SPINE, AB_SPINE)
            for pair in zip(spine, spine[1:])
        ]
        for upper, lower in pairs:
            with self.subTest(link=(upper, lower)):
                points = self.out.layout.waypoints[self._link(upper, lower)]
                right, left = _grid(self.env[upper].right + stack.LEG), _grid(self.env[upper].x - stack.LEG)
                self.assertEqual([p[0] for p in points], [right, right, left, left])
                self.assertEqual(points[1][1], points[2][1])
                self.assertLess(self.env[upper].bottom, points[1][1])
                self.assertLess(points[1][1], self.env[lower].y)
                self.assertTrue(all(v % 20 == 0 for p in points for v in p))
        # every Z is drawn as given: routing kept each one as its reroutes
        self.assertEqual(self.out.routes.dummy, len(self.out.layout.waypoints))

    def test_previews_stand_in_the_right_lane(self):
        for preview, spine, feeder in (
            ("base_preview", "base_sampler", "base_decode"),
            ("ab_compare_base", "ab_base_sampler", "ab_base_decode"),
            ("ab_compare_up", "ab_base_sampler", "ab_up_decode"),
        ):
            with self.subTest(preview=preview):
                at = self.env[preview]
                self.assertEqual(at.x, self.env[spine].right + stack.LANE_GAP)
                self.assertEqual(at.y, self.env[feeder].y)
                frame = self.frame[preview]
                self.assertIs(frame, self.frame[spine])
                self.assertLessEqual(at.right + PAD, frame.right)

    def test_z_right_legs_clear_the_right_lane(self):
        for spine, lane in ((BASE_SPINE, "base_preview"), (AB_SPINE, "ab_compare_base")):
            for upper, lower in zip(spine, spine[1:]):
                points = self.out.layout.waypoints[self._link(upper, lower)]
                self.assertLess(points[0][0], self.env[lane].x)

    def test_optional_module_is_one_frame(self):
        self.assertEqual(len({id(self.frame[a]) for a in AB}), 1)
        labels = sorted(self.out.layout.labels.values())
        self.assertEqual(labels, ["01", "02a", "02b", "03", "04", "05", "06", "07"])

    def test_gap_left_of_a_column_holds_one_track_per_output_coming_in(self):
        feeding: dict[int, set[tuple[str, int]]] = {}
        for link in self.links.values():
            o, t = self.column[str(link.origin_id)], self.column[str(link.target_id)]
            if o != t:
                feeding.setdefault(t, set()).add((str(link.origin_id), link.origin_slot))
        # the base and upscale passes take the prompts, the latent, the model and the VAE; the
        # A/B module those and the two decoded images it compares
        self.assertEqual({c: len(s) for c, s in feeding.items()}, {1: 5, 2: 7})
        tracks = self.out.layout.tracks
        lefts = sorted({frame.x for frame in self.frames})
        # every output feeding a spine node comes down a track; the A/B module's second decoded
        # image feeds only its comparer, in the right lane
        for column, count in ((1, 5), (2, 6)):
            with self.subTest(column=column):
                outputs: dict[tuple[str, int], set[float]] = {}
                for link in self.links.values():
                    if link.id in tracks and self.column[str(link.target_id)] == column:
                        self.assertNotEqual(self.column[str(link.origin_id)], column)
                        outputs.setdefault((str(link.origin_id), link.origin_slot), set()).add(tracks[link.id])
                # one track per output, its links branching off it, no two outputs on one track
                self.assertEqual(len(outputs), count)
                self.assertTrue(all(len(xs) == 1 for xs in outputs.values()), outputs)
                xs = sorted(x for found in outputs.values() for x in found)
                self.assertEqual(len(set(xs)), count)
                # TRACK apart in the gap left of the column, COLUMN_GAP clear of the column before
                # it, so none runs through a frame's top-left corner, where the title is
                left = lefts[column]
                self.assertEqual(xs, [left - TRACK * k for k in range(count, 0, -1)])
                self.assertEqual(xs[0] - max(f.right for f in self.frames if f.right < left), stack.COLUMN_GAP)
        # with no left lane, nothing comes down in front of a spine but a Z's left leg
        for spine in ("base_sampler", "ab_base_sampler"):
            self.assertEqual(self.env[spine].x - self.frame[spine].x, stack.CORRIDOR_MIN)

    def test_forced_are_the_links_between_columns(self):
        between = {
            link.id
            for link in self.links.values()
            if self.column[str(link.origin_id)] != self.column[str(link.target_id)]
        }
        self.assertTrue(between)
        self.assertEqual(set(self.out.layout.forced), between)
        self.assertLessEqual(between, set(self.out.routes.rerouted))

    def test_columns_fit_the_canvas_width(self):
        left = min(f.x for f in self.frames)
        wide = max(f.right for f in self.frames) - left
        high = max(f.bottom for f in self.frames)
        self.assertLessEqual(high, STACK.wrap_ratio * wide)
        self.assertEqual(len({f.x for f in self.frames}), 3)

    def test_second_run_is_byte_identical(self):
        again, _ = _compile()
        first = json.dumps(self.out.canvas.to_json(), sort_keys=True)
        self.assertEqual(json.dumps(again.canvas.to_json(), sort_keys=True), first)

    def test_patch_widgets_follow_its_definition(self):
        patch = self.out.canvas.node_map()[self.key["patch"]]
        self.assertEqual(patch.widgets_values, ["medium", 0.4, "AAB", "first", "left"])


def _lanes(keys) -> stack.Lanes:
    return stack.Lanes(key="g", plan=None, letter="", left=list(keys), spine=[], right=[], y={})


class Corridor(unittest.TestCase):
    """:func:`cwc.layout.stack._corridor` and the spine x it gives."""

    def _width(self, edges, column=("a", "b", "c")) -> float:
        graph = SimpleNamespace(edges=tuple((i, o, t) for i, (o, t, _) in enumerate(edges)))
        sources = {i: (o, slot) for i, (o, _, slot) in enumerate(edges)}
        return stack._corridor(graph, [_lanes(column)], sources)

    def test_no_link_from_outside_keeps_the_minimum(self):
        self.assertEqual(self._width([]), stack.CORRIDOR_MIN)
        self.assertEqual(self._width([("a", "b", 0)]), stack.CORRIDOR_MIN)

    def test_one_track_per_distinct_output(self):
        three = [("x", "a", 0), ("y", "b", 0), ("z", "c", 0)]
        self.assertEqual(self._width(three), stack.CORRIDOR_BASE + 3 * TRACK)
        fan = [("x", "a", 0), ("x", "b", 0), ("x", "c", 0), ("y", "a", 0), ("z", "a", 0)]
        self.assertEqual(self._width(fan), stack.CORRIDOR_BASE + 3 * TRACK)
        slots = [("x", "a", 0), ("x", "b", 1), ("y", "a", 0)]
        self.assertEqual(self._width(slots), stack.CORRIDOR_BASE + 3 * TRACK)

    def test_capped_at_the_maximum(self):
        many = [(f"s{i}", "a", 0) for i in range(40)]
        self.assertEqual(self._width(many), stack.CORRIDOR_MAX)

    def test_spine_x(self):
        self.assertEqual(stack.Widths(0, 280, 0, 0, 140).spine_x, 140)
        self.assertEqual(stack.Widths(400, 280, 0, 0, 80).spine_x, PAD + 400 + stack.LANE_GAP)
        self.assertEqual(stack.Widths(400, 280, 0, 0, 300).spine_x, PAD + 400 + 300)


def _scale(image: str, **meta) -> dict:
    return node("ImageScaleBy", {"image": [image, 0], "upscale_method": "lanczos", "scale_by": 1.0}, **meta)


def long_optional_chain(length: int = 8) -> dict:
    """Text to image with an optional chain of ``length`` image scalers before the save."""
    doc = txt2img()
    prev = "decode"
    for i in range(length):
        doc[f"s{i}"] = _scale(prev, ui_optional=True, ui_group="post")
        prev = f"s{i}"
    doc["save"]["inputs"]["images"] = [prev, 0]
    return doc


def crowded_layer(count: int = MAX_EXPANDED + 1) -> dict:
    """Text to image with ``count`` previews of the decoded image in one group: one layer."""
    doc = txt2img()
    for i in range(count):
        doc[f"p{i}"] = node("PreviewImage", {"images": ["decode", 0]}, ui_group="views")
    return doc


def _frames_of(canvas, result, keys) -> set[int]:
    return {result.membership[k] for k in keys}


def _blend(image1: str, image2: str, **meta) -> dict:
    return node("ImageBlend", {"image1": [image1, 0], "image2": [image2, 0], "blend_factor": 0.5, "blend_mode": "normal"}, **meta)


def optional_split_by_required() -> dict:
    """Two optional scalers in one authored group with a required scaler between them: annotate
    makes them two optional modules."""
    doc = txt2img()
    doc["o1"] = _scale("decode", ui_optional=True, ui_group="opt")
    doc["mid"] = _scale("o1", ui_group="req")
    doc["o2"] = _scale("mid", ui_optional=True, ui_group="opt")
    doc["save"]["inputs"]["images"] = ["o2", 0]
    return doc


def optional_reentered() -> dict:
    """One optional module, a scaler and a blend linked inside it, with a path that leaves it
    through a required scaler and comes back into the blend."""
    doc = txt2img()
    doc["o1"] = _scale("decode", ui_optional=True, ui_group="opt")
    doc["mid"] = _scale("o1", ui_group="req")
    doc["o2"] = _blend("mid", "o1", ui_optional=True, ui_group="opt")
    doc["save"]["inputs"]["images"] = ["o2", 0]
    return doc


def _intrusions(canvas, plan, result) -> list[tuple[str, str]]:
    """(optional module, node) for every node outside a top-level optional module whose envelope
    meets the rectangle of one of the module's frames."""
    parent = {g.key: g.parent for g in plan.groups}

    def top(key: str) -> str:
        while parent[key] is not None:
            key = parent[key]
        return key

    modules = {g.key for g in plan.groups if g.parent is None and g.optional}
    frames: dict[str, set[int]] = {m: set() for m in modules}
    for key, index in result.group_index.items():
        module = top(key.split("/")[0])
        if module in modules:
            frames[module].add(index)
    inside = {m: {k for g in plan.groups if top(g.key) == m for k in g.members} for m in modules}
    nodes = canvas.node_map()
    found = []
    for module, indices in frames.items():
        for key, n in nodes.items():
            if key in inside[module]:
                continue
            env = envelope(n, box_facts(n, DEFS.get(n.type)))
            if any(_overlap(env, canvas.groups[i].bounding) for i in indices):
                found.append((module, key))
    return found


class Cuts(unittest.TestCase):
    """Along y no group is cut by its number of layers or nodes; a crowded layer still is."""

    def test_long_optional_module_is_one_frame(self):
        doc = long_optional_chain()
        canvas, plan, result, report, _, _ = routed(copy.deepcopy(doc), STACK)
        _, authoring = compiled(doc)
        keys = [authoring.ids[f"s{i}"] for i in range(8)]
        self.assertEqual(len(_frames_of(canvas, result, keys)), 1)
        self.assertFalse([f.code.value for f in report.findings if f.severity.value == "error"])
        # the same graph along x is cut by C1, so the case tells the two apart
        canvas, plan, result, _, _, _ = routed(copy.deepcopy(doc), get_preset("bento"))
        self.assertGreater(len(_frames_of(canvas, result, keys)), 1)

    def test_optional_modules_apart_are_two_frames(self):
        doc = optional_split_by_required()
        _, authoring = compiled(doc)
        keys = [authoring.ids["o1"], authoring.ids["o2"]]
        for name in ("stack", "bento"):
            with self.subTest(preset=name):
                canvas, plan, result, _, _, _ = routed(copy.deepcopy(doc), get_preset(name))
                self.assertEqual(len(_frames_of(canvas, result, keys)), 2)

    def test_optional_module_reentered_is_one_frame(self):
        doc = optional_reentered()
        _, authoring = compiled(doc)
        o1, mid, o2 = (authoring.ids[n] for n in ("o1", "mid", "o2"))
        canvas, plan, result, report, _, _ = routed(copy.deepcopy(doc), STACK)
        self.assertEqual(len(_frames_of(canvas, result, [o1, o2])), 1)
        self.assertNotEqual(result.membership[mid], result.membership[o1])
        self.assertEqual(_intrusions(canvas, plan, result), [])
        self.assertFalse([f.code.value for f in report.findings if f.severity.value == "error"])

    def test_crowded_layer_is_cut(self):
        doc = crowded_layer()
        canvas, plan, result, report, _, _ = routed(copy.deepcopy(doc), STACK)
        _, authoring = compiled(doc)
        keys = [authoring.ids[f"p{i}"] for i in range(MAX_EXPANDED + 1)]
        self.assertEqual(len(_frames_of(canvas, result, keys)), 2)
        self.assertFalse([f for f in report.findings if f.code.value == "C1"])

    def test_crowded_split_cuts_only_the_crowded_half(self):
        doc = crowded_layer()
        doc["tail"] = _scale("p0", ui_group="views")
        canvas, authoring = compiled(doc)
        plan = annotate(canvas, DEFS, authoring)
        apply_notes(canvas, plan)
        graph = Graph.of(canvas, plan.nodes, DEFS)
        keys = [authoring.ids[f"p{i}"] for i in range(MAX_EXPANDED + 1)] + [authoring.ids["tail"]]
        pieces = stack.crowded_split(graph, keys)
        self.assertEqual(sorted(len(p) for p in pieces), [1, 1, MAX_EXPANDED])
        self.assertEqual(sorted(k for p in pieces for k in p), sorted(keys))
        self.assertEqual(stack.crowded_split(graph, keys[:MAX_EXPANDED] + keys[-1:]), [keys[:MAX_EXPANDED] + keys[-1:]])


class OptionalFrames(unittest.TestCase):
    """Under every preset, the rectangle of an optional module's frame holds no node from
    outside the module."""

    def test_no_outside_node_in_an_optional_frame(self):
        docs = {name: spec.build for name, spec in cases().items() if spec.nest is None}
        docs.update(
            split_by_required=optional_split_by_required,
            reentered=optional_reentered,
            long_optional_chain=long_optional_chain,
        )
        checked = 0
        for preset in load_presets().values():
            for name, build in docs.items():
                with self.subTest(preset=preset.name, case=name):
                    canvas, plan, result, _, _, _ = routed(build(), preset)
                    self.assertEqual(_intrusions(canvas, plan, result), [])
                    checked += any(g.optional for g in plan.groups)
        self.assertGreater(checked, len(load_presets()) * 5)

    def test_a_frame_stretched_over_a_neighbour_is_found(self):
        canvas, plan, result, _, _, _ = routed(optional_split_by_required(), STACK)
        index = result.group_index[next(g.key for g in plan.groups if g.optional)]
        frame = canvas.groups[index]
        frame.set_bounding(Rect(frame.bounding.x - 4000, frame.bounding.y - 4000, frame.bounding.w + 8000, frame.bounding.h + 8000))
        self.assertTrue(_intrusions(canvas, plan, result))


def _stack_canvases():
    """The fixture and every canvas of ``cases()`` routed under ``stack``: name to the canvas,
    the layout result and the node definitions."""
    out, defs = _compile()
    found = {"two_pass": (out.canvas, out.layout, defs)}
    for name, spec in cases().items():
        if spec.nest is None:
            canvas, _, result, _, _, _ = routed(spec.build(), STACK)
        else:
            canvas, result = nested(spec.build(), STACK, spec.nest, routing=True)
        found[name] = (canvas, result, DEFS)
    return found


def _late_turns(canvas, result, defs) -> list[tuple]:
    """The links with a track whose route, drawn under either renderer, does not end in one turn
    from the track into a straight run along the input's grid row."""
    table = Reroutes.read(canvas)
    nodes = canvas.node_map()
    facts = {key: box_facts(n, defs.get(n.type)) for key, n in nodes.items()}
    found = []
    for renderer in Renderer:
        curves = canvas_splines(canvas, facts, renderer)
        for link, x in sorted(result.tracks.items()):
            points = [table.points[r] for r in table.chain(link)]
            on = [k for k, p in enumerate(points) if p[0] == x]
            k = on[-1] if on else 0
            corner, end = points[k] if on else None, curves[link].p3
            if not (
                on
                and k > 0
                and points[k - 1][0] == x
                and all(p[1] == corner[1] for p in points[k:])
                and abs(end[1] - corner[1]) < GRID / 2
                and end[0] > points[-1][0]
            ):
                found.append((renderer.value, link, x, points[-4:], end))
    return found


def _uprights(canvas) -> list[tuple[int, float, float, float]]:
    """Each upright reroute segment: link id, x, top and bottom."""
    table = Reroutes.read(canvas)
    found = []
    for link in canvas.links:
        points = [table.points[r] for r in table.chain(link.id)]
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            if ax == bx and ay != by:
                found.append((link.id, ax, min(ay, by), max(ay, by)))
    return found


def _crowded_tracks(canvas, result, defs) -> list[tuple]:
    """Each run down a link's track that is not ``TRACK`` clear left of the Z leg line in front of
    the spine node it feeds, that is not right of the left lane of the box that node stands in,
    or that passes through a node."""
    nodes = canvas.node_map()
    env = {key: envelope(n, box_facts(n, defs.get(n.type))) for key, n in nodes.items()}
    frames = [group.bounding for group in canvas.groups]
    home = {key: min((f for f in frames if f.contains_rect(box)), key=lambda f: f.w * f.h, default=None) for key, box in env.items()}
    fed = {link.id: str(link.target_id) for link in canvas.links}
    found = []
    for link, x, top, bottom in _uprights(canvas):
        if result.tracks.get(link) != x:
            continue
        spine = env[fed[link]]
        if x > spine.x - stack.LEG - TRACK:
            found.append((link, x, "at the Z leg", spine.x))
        lane = [box.right for key, box in env.items() if home[key] == home[fed[link]] and box.right <= spine.x - stack.LEG]
        if lane and x <= max(lane):
            found.append((link, x, "in the left lane", max(lane)))
        for key, box in env.items():
            if box.x < x < box.right and top < box.bottom and box.y < bottom:
                found.append((link, x, "through", key))
    return found


def _uprights_on_sides(canvas) -> list[tuple]:
    """Each upright reroute segment closer than ``GRID`` to the left or right side of a frame
    whose height it overlaps."""
    found = []
    for link, x, top, bottom in _uprights(canvas):
        for group in canvas.groups:
            frame = group.bounding
            if bottom <= frame.y or top >= frame.bottom:
                continue
            for side in (frame.x, frame.right):
                if abs(x - side) < GRID:
                    found.append((link, x, (top, bottom), group.title, side))
    return found


class Buses(unittest.TestCase):
    """Under ``stack``: the links into a spine node from another column turn once from their
    track into the input, a track keeps clear of the Z leg line and of every node, and no upright
    run stands on a frame's side."""

    @classmethod
    def setUpClass(cls):
        cls.canvases = _stack_canvases()

    def test_a_tracked_link_turns_once_into_its_input(self):
        tracked = 0
        for name, (canvas, result, defs) in self.canvases.items():
            with self.subTest(case=name):
                self.assertEqual(_late_turns(canvas, result, defs), [])
                tracked += len(result.tracks)
        self.assertGreater(tracked, 100)

    def test_no_upright_run_on_a_frame_side(self):
        uprights = 0
        for name, (canvas, _, _) in self.canvases.items():
            with self.subTest(case=name):
                self.assertEqual(_uprights_on_sides(canvas), [])
                uprights += len(_uprights(canvas))
        self.assertGreater(uprights, 100)

    def test_a_track_keeps_off_the_z_leg_the_left_lane_and_every_node(self):
        # a column with no left lane keeps its tracks in the gap left of it, one with a left lane
        # in the corridor between the lane and the spine, which _corridor widens per track;
        # either way a track stands TRACK clear left of the Z leg line in front of the spine node
        # it feeds, right of that box's left lane, and goes through no node
        runs = 0
        for name, (canvas, result, defs) in self.canvases.items():
            with self.subTest(case=name):
                self.assertEqual(_crowded_tracks(canvas, result, defs), [])
                runs += sum(1 for link, x, _, _ in _uprights(canvas) if result.tracks.get(link) == x)
        self.assertGreater(runs, 100)

    def test_a_node_moved_under_a_track_is_found(self):
        canvas, result, defs = copy.deepcopy(self.canvases["two_pass"])
        link, x, top, bottom = next(u for u in _uprights(canvas) if result.tracks.get(u[0]) == u[1])
        moved = next(n for n in canvas.nodes if str(n.id) != str(next(k.target_id for k in canvas.links if k.id == link)))
        moved.set_pos(x - 40, (top + bottom) / 2)
        self.assertIn((link, x, "through", str(moved.id)), _crowded_tracks(canvas, result, defs))

    def test_a_frame_side_moved_onto_an_upright_is_found(self):
        canvas = copy.deepcopy(self.canvases["two_pass"][0])
        _, x, top, bottom = _uprights(canvas)[0]
        frame = canvas.groups[0]
        frame.set_bounding(Rect(x - GRID / 2, top, frame.bounding.w, bottom - top))
        self.assertTrue(_uprights_on_sides(canvas))


class SmallCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        doc = txt2img()
        cls.canvas, cls.authoring = compiled(doc)
        plan = annotate(cls.canvas, DEFS, cls.authoring)
        apply_notes(cls.canvas, plan)
        cls.graph = Graph.of(cls.canvas, plan.nodes, DEFS)
        cls.k = dict(cls.authoring.ids)

    def _plan(self, members) -> GroupPlan:
        return GroupPlan(key="g", zone=Zone.SAMPLING, name="g", members=tuple(members))

    def _box(self, members, graph=None) -> stack.Lanes:
        (lanes,) = stack.group_lanes(graph or self.graph, self._plan(members), [], frozenset({self.k["save"]}))
        return lanes

    def _no_overlap(self, graph, lanes):
        drawn = stack.draw_alone(graph, lanes, {})
        rects = []
        for key, (x, y) in drawn.nodes.items():
            n = graph.nodes[key]
            n.set_pos(x, y)
            rects.append(envelope(n, graph.facts[key]))
        for i, a in enumerate(rects):
            for b in rects[i + 1 :]:
                self.assertFalse(_overlap(a, b), (a, b))
            self.assertLessEqual(a.bottom, drawn.box.h)

    def test_empty_group(self):
        lanes = self._box([])
        self.assertEqual((lanes.left, lanes.spine, lanes.right), ([], [], []))
        self.assertGreater(lanes.height, 0)

    def test_one_node_is_its_own_spine(self):
        for name in ("sampler", "save"):
            lanes = self._box([self.k[name]])
            self.assertEqual(lanes.spine, [self.k[name]], name)

    def test_unlinked_nodes_have_no_spine(self):
        lanes = self._box([self.k["pos"], self.k["neg"], self.k["latent"]])
        self.assertEqual(lanes.spine, [])
        self.assertEqual(sorted(lanes.left), sorted([self.k["pos"], self.k["neg"], self.k["latent"]]))
        self._no_overlap(self.graph, lanes)

    def test_chain_with_a_preview(self):
        members = [self.k[n] for n in ("sampler", "decode", "save")]
        lanes = self._box(members)
        self.assertEqual(lanes.spine, [self.k["sampler"], self.k["decode"]])
        self.assertEqual(lanes.right, [self.k["save"]])
        self._no_overlap(self.graph, lanes)

    def test_loop_inside_a_group(self):
        a, b = self.k["pos"], self.k["neg"]
        graph = Graph(
            nodes=self.graph.nodes,
            facts=self.graph.facts,
            notes=self.graph.notes,
            edges=((900, a, b), (901, b, a)),
        )
        lanes = self._box([a, b], graph)
        self.assertEqual(sorted(lanes.spine + lanes.left + lanes.right), sorted([a, b]))
        self.assertEqual(len(lanes.spine), 2)
        self._no_overlap(graph, lanes)

    def test_nested_group(self):
        spec = cases()["nested_two_stage"]
        canvas, result = nested(spec.build(), STACK, spec.nest, routing=True)
        frames = [g.bounding for g in canvas.groups]
        inside = [
            (i, j)
            for i, a in enumerate(frames)
            for j, b in enumerate(frames)
            if i != j and a.x <= b.x and a.y <= b.y and b.right <= a.right and b.bottom <= a.bottom
        ]
        self.assertEqual(len(inside), 1)
        nodes = canvas.node_map()
        for key, index in result.membership.items():
            if index is None:
                continue
            n = nodes[key]
            env = envelope(n, box_facts(n, DEFS.get(n.type)))
            frame = frames[index]
            self.assertTrue(frame.x <= env.x and env.right <= frame.right and frame.y <= env.y and env.bottom <= frame.bottom, key)


def _overlap(a: Rect, b: Rect) -> bool:
    return a.x < b.right and b.x < a.right and a.y < b.bottom and b.y < a.bottom


if __name__ == "__main__":
    unittest.main()
