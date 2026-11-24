"""The diagram skin (``cwc render --skin diagram``): determinism, the theme as the only source of
colour, terminal blocks, right-angled links with arrows, and what ``extra.cwc`` adds."""

from __future__ import annotations

import copy
import io
import json
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from dataclasses import astuple
from pathlib import Path
from typing import Any

from tests import support  # noqa: F401  (puts src/ on sys.path)
from tests.graphs import txt2img

from cwc.canvas.model import Canvas
from cwc.cli import main
from cwc.nodedefs.registry import NodeDefs
from cwc.pipeline import compile_document
from cwc.render.skin import PALETTES, PANEL_PAD, Theme, render_diagram
from cwc.render.svg import render
from cwc.report import ExitCode

SVG = "{http://www.w3.org/2000/svg}"
DEFS = NodeDefs.load()


def noted(doc: dict[str, Any]) -> dict[str, Any]:
    """``doc`` with a figure title, two notes and a note on the group of the decoder."""
    doc = copy.deepcopy(doc)
    doc["sampler"]["_meta"] = {"ui_note": "the one step that runs long"}
    doc["ckpt"]["_meta"] = {"ui_note": "weights from disk"}
    doc["decode"]["_meta"] = {"ui_group": "finish"}
    doc["_workflow"] = {"format": 1, "title": "Text to image", "groups": {"finish": {"title": "Finish", "note": "decode and save"}}}
    return doc


def tree(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def by_class(root: ET.Element, cls: str) -> list[ET.Element]:
    return [el for el in root.iter() if cls in (el.get("class") or "").split()]


def node(key: int, type: str, x: float, y: float, *, w: float = 300, h: float = 100, mode: int = 0, **extra: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "id": key,
        "type": type,
        "pos": [x, y],
        "size": [w, h],
        "flags": {},
        "order": 0,
        "mode": mode,
        "inputs": [],
        "outputs": [],
        "properties": {},
        "widgets_values": [],
    }
    raw.update(extra)
    return raw


def canvas(nodes: list[dict], groups: list[tuple[str, list[float]]] = (), links: list[list] = (), extra: dict | None = None) -> Canvas:
    return Canvas(
        {
            "last_node_id": len(nodes),
            "last_link_id": len(links),
            "nodes": nodes,
            "links": list(links),
            "groups": [{"id": i + 1, "title": title, "bounding": box, "color": "#ff0000", "flags": {}} for i, (title, box) in enumerate(groups)],
            "config": {},
            "extra": extra or {},
            "version": 0.4,
        }
    )


def rect_of(el: ET.Element) -> tuple[float, float, float, float]:
    rect = el.find(f"{SVG}rect")
    return tuple(float(rect.get(k)) for k in ("x", "y", "width", "height"))


class CompiledFigureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.with_notes = compile_document(noted(txt2img()), DEFS).canvas
        cls.plain = compile_document(txt2img(), DEFS).canvas

    def test_two_renders_are_byte_identical_and_a_reload_changes_nothing(self):
        for theme in Theme:
            with self.subTest(theme=theme):
                first = render_diagram(self.with_notes, DEFS, theme).svg
                again = render_diagram(Canvas(json.loads(json.dumps(self.with_notes.to_json()))), DEFS, theme).svg
                self.assertEqual(first.encode("utf-8"), render_diagram(self.with_notes, DEFS, theme).svg.encode("utf-8"))
                self.assertEqual(first, again)

    def test_every_colour_belongs_to_the_chosen_theme(self):
        for theme in Theme:
            allowed = set(astuple(PALETTES[theme])) | {"none"}
            svg = render_diagram(self.with_notes, DEFS, theme).svg
            used = set(re.findall(r'(?:fill|stroke)="([^"]*)"', svg))
            with self.subTest(theme=theme):
                self.assertLessEqual(used, allowed)
                self.assertIn(PALETTES[theme].bg, used)
                self.assertIn(PALETTES[theme].accent, used)  # the notes

    def test_the_canvas_colours_are_not_used(self):
        saved = {g.color for g in self.with_notes.groups} | {n.raw.get("color") for n in self.with_notes.nodes} | {n.raw.get("bgcolor") for n in self.with_notes.nodes}
        saved.discard(None)
        self.assertTrue(saved)  # compile colours its groups and nodes
        svg = render_diagram(self.with_notes, DEFS).svg
        for colour in saved:
            self.assertNotIn(f'"{colour}"', svg)

    def test_no_slot_dots_reroute_circles_or_first_screen_frame(self):
        root = tree(render_diagram(self.with_notes, DEFS).svg)
        self.assertEqual([el for el in root.iter(f"{SVG}circle")], [])
        self.assertIsNone(root.find(".//*[@id='first-screen']"))
        self.assertEqual(by_class(root, "slot"), [])

    def test_extra_cwc_draws_the_title_the_panel_meta_and_the_notes(self):
        root = tree(render_diagram(self.with_notes, DEFS).svg)
        self.assertEqual(root.find(f".//{SVG}text[@id='title']").text, "Text to image")
        metas = [el.text for el in by_class(root, "panel-meta")]
        self.assertEqual(metas, ["decode and save"])
        notes = sorted(" ".join(t.text for t in el.iter(f"{SVG}tspan")) for el in by_class(root, "note"))
        self.assertEqual(notes, ["the one step that runs long", "weights from disk"])

    def test_without_extra_cwc_there_is_no_title_meta_or_note(self):
        self.assertNotIn("cwc", self.plain.extra)
        root = tree(render_diagram(self.plain, DEFS).svg)
        self.assertIsNone(root.find(f".//{SVG}text[@id='title']"))
        self.assertEqual(by_class(root, "panel-meta"), [])
        self.assertEqual(by_class(root, "note"), [])

    def test_panel_titles_lose_their_number(self):
        root = tree(render_diagram(self.with_notes, DEFS).svg)
        titles = [el.text for el in by_class(root, "panel-title")]
        self.assertTrue(any(re.match(r"^\d+[a-z]? ", g.title) for g in self.with_notes.groups))
        self.assertFalse([t for t in titles if re.match(r"^\d+[a-z]? ", t)], titles)

    def test_every_link_is_right_angled_and_ends_in_an_arrow(self):
        root = tree(render_diagram(self.with_notes, DEFS).svg)
        links = by_class(root, "link")
        self.assertEqual(len(links), len(self.with_notes.links))
        self.assertEqual(len(by_class(root, "arrow")), len(links))
        for link in links:
            for a, b in legs(link.get("d")):
                self.assertTrue(abs(a[0] - b[0]) < 0.01 or abs(a[1] - b[1]) < 0.01, (link.get("id"), a, b))


def legs(d: str) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Every straight piece of a path: ``L`` legs, and the two halves of each rounded corner (from
    its start to its control point, the corner, and on to its end)."""
    tokens = d.split()
    out, here, i = [], None, 0
    while i < len(tokens):
        op = tokens[i]
        if op == "M":
            here, i = (float(tokens[i + 1]), float(tokens[i + 2])), i + 3
        elif op == "L":
            to = (float(tokens[i + 1]), float(tokens[i + 2]))
            out.append((here, to))
            here, i = to, i + 3
        elif op == "Q":
            corner, to = (float(tokens[i + 1]), float(tokens[i + 2])), (float(tokens[i + 3]), float(tokens[i + 4]))
            out.extend([(here, corner), (corner, to)])
            here, i = to, i + 5
        else:
            raise AssertionError(f"unexpected path command {op!r} in {d}")
    return out


class TerminalTest(unittest.TestCase):
    """An output node becomes a terminal block only when its group holds output nodes alone."""

    def figure(self, nodes, groups, links=()):
        return tree(render_diagram(canvas(nodes, groups, links), DEFS).svg)

    def kind(self, root, key):
        return root.find(f".//*[@id='node-{key}']").get("class").split()[0]

    def test_a_save_alone_in_its_group_spans_the_panel(self):
        root = self.figure([node(1, "SaveImage", 100, 140, w=280, h=60)], [("03 Output", [40, 40, 800, 300])])
        self.assertEqual(self.kind(root, 1), "terminal")
        x, _, w, _ = rect_of(root.find(".//*[@id='node-1']"))
        self.assertEqual((x, w), (40 + PANEL_PAD, 800 - 2 * PANEL_PAD))

    def test_a_preview_in_the_middle_of_a_stage_stays_a_module(self):
        root = self.figure(
            [node(1, "VAEDecode", 100, 140), node(2, "PreviewImage", 500, 140), node(3, "SaveImage", 100, 540)],
            [("02 Sampling", [40, 40, 900, 300]), ("03 Output", [40, 440, 900, 300])],
        )
        self.assertEqual(self.kind(root, 2), "module")
        self.assertEqual(self.kind(root, 3), "terminal")

    def test_a_bypassed_output_is_a_dashed_module(self):
        root = self.figure([node(1, "SaveImage", 100, 140, mode=4)], [("Output", [40, 40, 800, 300])])
        el = root.find(".//*[@id='node-1']")
        self.assertEqual(el.get("class"), "module bypass")
        self.assertIsNotNone(el.find(f"{SVG}rect").get("stroke-dasharray"))

    def test_an_output_in_no_group_keeps_its_own_box(self):
        root = self.figure([node(1, "SaveImage", 100, 140, w=280, h=60)], [])
        self.assertEqual(self.kind(root, 1), "terminal")
        self.assertEqual(rect_of(root.find(".//*[@id='node-1']")), (100, 110, 280, 90))

    def test_two_outputs_side_by_side_keep_their_own_boxes(self):
        root = self.figure(
            [node(1, "SaveImage", 100, 140, w=280, h=60), node(2, "PreviewImage", 500, 140, w=280, h=60)],
            [("Output", [40, 40, 900, 300])],
        )
        self.assertEqual([self.kind(root, k) for k in (1, 2)], ["terminal", "terminal"])
        self.assertEqual(rect_of(root.find(".//*[@id='node-1']"))[2], 280)


class LinkAndNoteTest(unittest.TestCase):
    def test_the_arrow_tip_sits_on_the_edge_of_the_target_box(self):
        nodes = [
            node(1, "VAEDecode", 100, 140, outputs=[{"name": "IMAGE", "type": "IMAGE", "links": [1]}]),
            node(2, "SaveImage", 100, 440, w=280, h=60, inputs=[{"name": "images", "type": "IMAGE", "link": 1}]),
        ]
        root = tree(render_diagram(canvas(nodes, [("Output", [40, 360, 800, 300])], [[1, 1, 0, 2, 0, "IMAGE"]]), DEFS).svg)
        arrow = root.find(".//*[@id='arrow-1']").get("d")
        tip = tuple(float(v) for v in re.match(r"M ([-\d.]+) ([-\d.]+)", arrow).groups())
        x, y, w, h = rect_of(root.find(".//*[@id='node-2']"))
        on_edge = (abs(tip[0] - x) < 0.01 or abs(tip[0] - (x + w)) < 0.01 or abs(tip[1] - y) < 0.01 or abs(tip[1] - (y + h)) < 0.01)
        self.assertTrue(on_edge and x <= tip[0] <= x + w and y <= tip[1] <= y + h, (tip, (x, y, w, h)))

    def test_a_link_to_a_bypassed_node_is_a_dashed_accent_line(self):
        nodes = [
            node(1, "VAEDecode", 100, 140, outputs=[{"name": "IMAGE", "type": "IMAGE", "links": [1]}]),
            node(2, "PreviewImage", 600, 140, mode=4, inputs=[{"name": "images", "type": "IMAGE", "link": 1}]),
        ]
        root = tree(render_diagram(canvas(nodes, [], [[1, 1, 0, 2, 0, "IMAGE"]]), DEFS).svg)
        link = root.find(".//*[@id='link-1']")
        self.assertEqual(link.get("class"), "link bypass")
        self.assertEqual(link.get("stroke"), PALETTES[Theme.LIGHT].accent)

    def notes(self, notes, nodes):
        extra = {"cwc": {"format": 1, "title": None, "notes": notes, "groups": {}}}
        return by_class(tree(render_diagram(canvas(nodes, [("Stack", [40, 40, 600, 900])], extra=extra), DEFS).svg), "note")

    def test_stacked_modules_with_one_note_share_a_bracket(self):
        stack = [node(1, "VAEDecode", 100, 140), node(2, "VAEDecode", 100, 300), node(3, "VAEDecode", 100, 460)]
        [run] = self.notes({"1": "same", "2": "same", "3": "same"}, stack)
        self.assertIsNotNone(run.find(f"{SVG}path[@class='bracket']"))
        runs = self.notes({"1": "same", "2": "other", "3": "same"}, stack)
        self.assertEqual(len(runs), 3)
        self.assertEqual([r.find(f"{SVG}path") for r in runs], [None, None, None])

    def test_a_module_between_breaks_the_bracket(self):
        stack = [node(1, "VAEDecode", 100, 140), node(2, "VAEDecode", 100, 300), node(3, "VAEDecode", 100, 460)]
        self.assertEqual(len(self.notes({"1": "same", "3": "same"}, stack)), 2)

    def note_x(self, nodes, links=()):
        extra = {"cwc": {"format": 1, "title": None, "notes": {"1": "note"}, "groups": {}}}
        [run] = by_class(tree(render_diagram(canvas(nodes, [], links, extra=extra), DEFS).svg), "note")
        return float(run.find(f"{SVG}text").get("x"))

    def test_a_note_with_free_room_sits_beside_its_module(self):
        self.assertGreater(self.note_x([node(1, "VAEDecode", 100, 140, h=40)]), 400)

    def test_a_note_on_its_own_outgoing_link_goes_under_the_module(self):
        nodes = [
            node(1, "VAEDecode", 100, 140, h=40, outputs=[{"name": "IMAGE", "type": "IMAGE", "links": [1]}]),
            node(2, "VAEDecode", 600, 140, h=40, inputs=[{"name": "samples", "type": "LATENT", "link": 1}]),
        ]
        self.assertEqual(self.note_x(nodes, [[1, 1, 0, 2, 0, "IMAGE"]]), 100)

    def test_a_note_against_a_neighbour_box_goes_under_the_module(self):
        self.assertEqual(self.note_x([node(1, "VAEDecode", 100, 140, h=40), node(2, "VAEDecode", 410, 140, h=40)]), 100)

    def test_a_note_blocked_beside_and_under_stays_beside(self):
        nodes = [node(1, "VAEDecode", 100, 140, h=40), node(2, "VAEDecode", 410, 140, h=40), node(3, "VAEDecode", 100, 220, h=40)]
        self.assertGreater(self.note_x(nodes), 400)

    def test_a_long_note_wraps(self):
        [run] = self.notes({"1": "a note long enough that it has to wrap onto more than one line here"}, [node(1, "VAEDecode", 100, 140)])
        self.assertGreater(len(list(run.iter(f"{SVG}tspan"))), 1)


class StackedLinkTest(unittest.TestCase):
    """A link between two stacked modules is a short vertical arrow; anything else keeps its elbows."""

    def figure(self, nodes, links):
        return tree(render_diagram(canvas(nodes, [], links), DEFS).svg)

    def pair(self, dx=0.0, *, extra_nodes=(), links=None):
        nodes = [
            node(1, "VAEDecode", 100, 140, outputs=[{"name": "IMAGE", "type": "IMAGE", "links": [1]}]),
            node(2, "VAEDecode", 100 + dx, 440, inputs=[{"name": "samples", "type": "LATENT", "link": 1}]),
            *extra_nodes,
        ]
        return self.figure(nodes, links if links is not None else [[1, 1, 0, 2, 0, "IMAGE"]])

    def drawn(self, root, link_id=1):
        return legs(root.find(f".//*[@id='link-{link_id}']").get("d"))

    def tip(self, root, link_id=1):
        d = root.find(f".//*[@id='arrow-{link_id}']").get("d")
        return tuple(float(v) for v in re.match(r"M ([-\d.]+) ([-\d.]+)", d).groups())

    def assert_vertical(self, root, x):
        [(a, b)] = self.drawn(root)
        above, below = rect_of(root.find(".//*[@id='node-1']")), rect_of(root.find(".//*[@id='node-2']"))
        self.assertEqual((a[0], b[0]), (x, x))
        self.assertAlmostEqual(a[1], above[1] + above[3])
        self.assertEqual(self.tip(root), (x, below[1]))

    def assert_elbows(self, root, link_id=1):
        self.assertGreater(len(self.drawn(root, link_id)), 1)

    def test_stacked_modules_get_a_vertical_arrow_down_the_middle(self):
        self.assert_vertical(self.pair(), 100 + 300 / 2)

    def test_sixty_percent_overlap_is_enough(self):
        self.assert_vertical(self.pair(120), 100 + 300 / 2)

    def test_less_overlap_keeps_the_elbows(self):
        self.assert_elbows(self.pair(150))

    def test_a_target_beside_or_above_keeps_the_elbows(self):
        nodes = [
            node(1, "VAEDecode", 100, 440, outputs=[{"name": "IMAGE", "type": "IMAGE", "links": [1]}]),
            node(2, "VAEDecode", 100, 140, inputs=[{"name": "samples", "type": "LATENT", "link": 1}]),
        ]
        self.assert_elbows(self.figure(nodes, [[1, 1, 0, 2, 0, "IMAGE"]]))

    def test_a_module_in_the_band_between_keeps_the_elbows(self):
        self.assert_elbows(self.pair(extra_nodes=[node(3, "VAEDecode", 300, 290, w=200, h=40)]))

    def test_a_module_beside_the_band_does_not(self):
        self.assert_vertical(self.pair(extra_nodes=[node(3, "VAEDecode", 420, 290, w=200, h=40)]), 100 + 300 / 2)

    def test_two_links_between_the_pair_keep_their_elbows(self):
        nodes = [
            node(1, "VAEDecode", 100, 140, outputs=[{"name": "IMAGE", "type": "IMAGE", "links": [1, 2]}]),
            node(
                2, "VAEDecode", 100, 440,
                inputs=[{"name": "samples", "type": "LATENT", "link": 1}, {"name": "vae", "type": "VAE", "link": 2}],
            ),
        ]
        root = self.figure(nodes, [[1, 1, 0, 2, 0, "IMAGE"], [2, 1, 0, 2, 1, "IMAGE"]])
        self.assert_elbows(root, 1)
        self.assert_elbows(root, 2)

    def rerouted(self, *, shared: bool):
        nodes = [
            node(1, "VAEDecode", 100, 140, outputs=[{"name": "IMAGE", "type": "IMAGE", "links": [1, 2]}]),
            node(2, "VAEDecode", 100, 440, inputs=[{"name": "samples", "type": "LATENT", "link": 1}]),
            node(3, "VAEDecode", 700, 440, inputs=[{"name": "samples", "type": "LATENT", "link": 2}]),
        ]
        links = [[1, 1, 0, 2, 0, "IMAGE"], [2, 1, 0, 3, 0, "IMAGE"]]
        if shared:
            reroutes = [{"id": 1, "pos": [500, 300], "linkIds": [1, 2]}]
            extensions = [{"id": 1, "parentId": 1}, {"id": 2, "parentId": 1}]
        else:
            reroutes = [{"id": 1, "pos": [500, 300], "linkIds": [1]}]
            extensions = [{"id": 1, "parentId": 1}]
        return tree(render_diagram(canvas(nodes, [], links, extra={"reroutes": reroutes, "linkExtensions": extensions}), DEFS).svg)

    def test_a_reroute_of_its_own_does_not_stop_the_vertical_arrow(self):
        self.assert_vertical(self.rerouted(shared=False), 100 + 300 / 2)

    def test_a_reroute_shared_with_another_link_keeps_the_elbows(self):
        self.assert_elbows(self.rerouted(shared=True))


class SubtitleTest(unittest.TestCase):
    def subtitle(self, raw):
        root = tree(render_diagram(canvas([raw]), DEFS).svg)
        el = root.find(".//*[@id='node-1']/*[@class='subtitle']")
        return None if el is None else el.text

    def test_a_model_name_loses_folder_and_extension(self):
        raw = node(1, "UNETLoader", 100, 140, widgets_values=["family/example_model.safetensors", "default"])
        self.assertEqual(self.subtitle(raw), "example_model")

    def test_a_long_value_is_cut_to_28_characters(self):
        raw = node(1, "UNETLoader", 100, 140, w=600, widgets_values=["a" * 40 + ".safetensors", "default"])
        self.assertEqual(self.subtitle(raw), "a" * 27 + "…")

    def test_a_widget_driven_by_a_link_is_skipped(self):
        raw = node(
            1, "UNETLoader", 100, 140,
            inputs=[{"name": "unet_name", "type": "COMBO", "widget": {"name": "unet_name"}, "link": 7}],
            widgets_values=["example_model.safetensors", "fp8_e4m3fn"],
        )
        self.assertEqual(self.subtitle(raw), "fp8_e4m3fn")

    def test_a_sampler_shows_its_sampler(self):
        raw = node(1, "KSampler", 100, 140, h=262, widgets_values=[1, "fixed", 20, 5.0, "euler", "normal", 1.0])
        self.assertEqual(self.subtitle(raw), "euler")


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.graph = self.dir / "g.ui.json"
        self.graph.write_text(json.dumps(compile_document(noted(txt2img()), DEFS).canvas.to_json()), encoding="utf-8")

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = main(["render", str(self.graph), "-o", str(self.dir / "o.svg"), *argv], out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def test_diagram_dark_writes_the_dark_figure(self):
        code, _, err = self.run_cli("--skin", "diagram", "--theme", "dark")
        self.assertEqual(code, ExitCode.OK, err)
        svg = (self.dir / "o.svg").read_text(encoding="utf-8")
        self.assertIn(f'fill="{PALETTES[Theme.DARK].bg}"', svg)
        self.assertEqual(svg, render_diagram(Canvas(json.loads(self.graph.read_text())), DEFS, Theme.DARK).svg)

    def test_diagram_defaults_to_light(self):
        self.assertEqual(self.run_cli("--skin", "diagram")[0], ExitCode.OK)
        self.assertIn(f'fill="{PALETTES[Theme.LIGHT].bg}"', (self.dir / "o.svg").read_text(encoding="utf-8"))

    def test_the_default_skin_is_the_debug_drawing(self):
        self.assertEqual(self.run_cli()[0], ExitCode.OK)
        expected = render(Canvas(json.loads(self.graph.read_text())), DEFS).svg
        self.assertEqual((self.dir / "o.svg").read_text(encoding="utf-8"), expected)

    def test_a_theme_for_the_debug_skin_is_a_usage_error(self):
        code, _, err = self.run_cli("--theme", "dark")
        self.assertEqual(code, ExitCode.USAGE)
        self.assertIn("--theme applies to --skin diagram only", err)
        self.assertFalse((self.dir / "o.svg").exists())


if __name__ == "__main__":
    unittest.main()
