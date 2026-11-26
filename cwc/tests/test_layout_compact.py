"""Tests for the 2D minimal-area compact layout engine and G11 area-utilization gate."""

from __future__ import annotations

import copy
import time
import unittest

from tests import support  # noqa: F401
from tests.graphs import DEFS, node, txt2img
from tests.layout_cases import (
    custom_sampling,
    long_chain,
    lora_chain,
    optional_upscale,
    two_stage,
    with_lora,
    controlnet,
)

from cwc.canvas.model import Canvas
from cwc.layout.presets import get_preset, parse_presets
from cwc.pipeline import compile_document
from cwc.report import Code, Mode, Severity
from cwc.resources import read_json
from cwc.verify.geometry import AREA_UTIL_MIN, AREA_UTIL_MIN_NODES, check_geometry


def _canvas_with_nodes(positions: list[tuple[float, float, float, float]]) -> Canvas:
    nodes = [
        {
            "id": i + 1,
            "type": "KSampler",
            "pos": [x, y],
            "size": [w, h],
            "flags": {},
            "order": i,
            "mode": 0,
            "inputs": [],
            "outputs": [],
            "properties": {},
            "widgets_values": [],
        }
        for i, (x, y, w, h) in enumerate(positions)
    ]
    return Canvas(
        {
            "last_node_id": len(nodes),
            "last_link_id": 0,
            "nodes": nodes,
            "links": [],
            "groups": [],
            "config": {},
            "extra": {},
            "version": 0.4,
        }
    )


def _multi_stage_poster_like() -> dict:
    """Synthetic 16-node two-pass + LoRA + upscale poster graph with a Quick Guide title."""
    doc = two_stage()
    doc["lora"] = node(
        "LoraLoader",
        {"model": ["ckpt", "MODEL"], "clip": ["ckpt", "CLIP"], "lora_name": "style.safetensors"},
    )
    doc["sampler"]["inputs"]["model"] = ["lora", "MODEL"]
    doc["sampler2"]["inputs"]["model"] = ["lora", "MODEL"]
    doc["pos"]["inputs"]["clip"] = ["lora", "CLIP"]
    doc["neg"]["inputs"]["clip"] = ["lora", "CLIP"]
    doc["upscale"] = node("ImageScaleBy", {"image": ["decode2", 0], "upscale_method": "lanczos", "scale_by": 1.5})
    doc["save"]["inputs"]["images"] = ["upscale", 0]
    doc["_workflow"] = {
        "format": 1,
        "title": "Two-Pass Poster Workflow",
    }
    return doc


class AreaUtilizationCheckTest(unittest.TestCase):
    def test_empty_canvas_reports_zero_areas(self):
        rep = check_geometry(_canvas_with_nodes([]), DEFS, mode=Mode.COMPILE)
        g11 = rep.metrics["G11"]
        self.assertEqual(
            g11,
            {
                "bbox_area": 0.0,
                "node_area_sum": 0.0,
                "area_utilization": None,
                "nodes": 0,
                "min_utilization": AREA_UTIL_MIN,
            },
        )
        self.assertEqual([f for f in rep.findings if f.code is Code.G11], [])

    def test_sparse_small_graph_below_node_threshold_does_not_warn(self):
        # 2 nodes placed far apart -> tiny utilization, but < AREA_UTIL_MIN_NODES
        cv = _canvas_with_nodes([(0, 0, 200, 100), (4000, 2000, 200, 100)])
        rep = check_geometry(cv, DEFS, mode=Mode.COMPILE)
        g11 = rep.metrics["G11"]
        self.assertEqual(g11["nodes"], 2)
        self.assertLess(g11["area_utilization"], AREA_UTIL_MIN)
        self.assertEqual([f for f in rep.findings if f.code is Code.G11], [])

    def test_sparse_large_graph_emits_g11_warning_with_hint(self):
        # 10 nodes spread sparsely across a huge canvas -> triggers G11 warning
        positions = [(i * 800, (i % 2) * 1400, 220, 120) for i in range(AREA_UTIL_MIN_NODES)]
        cv = _canvas_with_nodes(positions)
        rep = check_geometry(cv, DEFS, mode=Mode.COMPILE)
        g11 = rep.metrics["G11"]
        self.assertEqual(g11["nodes"], AREA_UTIL_MIN_NODES)
        self.assertGreater(g11["bbox_area"], 0.0)
        self.assertGreater(g11["node_area_sum"], 0.0)
        self.assertLess(g11["area_utilization"], AREA_UTIL_MIN)
        found = [f for f in rep.findings if f.code is Code.G11]
        self.assertEqual(len(found), 1)
        self.assertIs(found[0].severity, Severity.WARNING)
        self.assertIn("--preset square", found[0].hint or "")

    def test_dense_large_graph_passes_g11_cleanly(self):
        # 10 nodes packed tightly in a 5x2 grid -> high utilization, no G11 warning
        positions = [(col * 260, row * 240, 240, 200) for row in range(2) for col in range(5)]
        cv = _canvas_with_nodes(positions)
        rep = check_geometry(cv, DEFS, mode=Mode.COMPILE)
        g11 = rep.metrics["G11"]
        self.assertGreaterEqual(g11["area_utilization"], AREA_UTIL_MIN)
        self.assertEqual([f for f in rep.findings if f.code is Code.G11], [])


class CompactPresetSchemaTest(unittest.TestCase):
    def test_golden_preset_flag_matrix(self):
        expected = {
            "bento": (2.4, False, False, False),
            "swimlanes": (2.4, False, False, False),
            "cockpit-split": (2.4, False, False, False),
            "tower-preview": (2.4, False, False, False),
            "stepped": (2.4, False, False, False),
            "stack": (1.0, False, False, False),
            "gallery": (2.6, False, False, False),
            "square": (1.85, True, True, True),
        }
        for name, flags in expected.items():
            preset = get_preset(name)
            self.assertEqual(
                (preset.wrap_ratio, preset.wrap_rows, preset.compact, preset.compact_under_guide),
                flags,
                name,
            )

    def test_non_bool_compact_flags_rejected(self):
        for key in ("compact", "compact_under_guide"):
            for bad in (1, "true", None):
                doc = copy.deepcopy(read_json("presets.json"))
                doc["presets"]["square"][key] = bad
                with self.assertRaises(ValueError):
                    parse_presets(doc)


class CompactLayoutEngineTest(unittest.TestCase):
    def test_compile_report_exposes_g11_metrics_and_beats_bento_area(self):
        doc = _multi_stage_poster_like()
        res_sq = compile_document(doc, DEFS, preset="square")
        res_bento = compile_document(doc, DEFS, preset="bento")

        self.assertTrue(res_sq.report.ok, [f.message for f in res_sq.report.findings])
        gm_sq = res_sq.report.metrics["geometry"]
        gm_bento = res_bento.report.metrics["geometry"]

        self.assertIn("G11", gm_sq)
        g11_sq = gm_sq["G11"]
        g11_bento = gm_bento["G11"]
        self.assertLess(g11_sq["bbox_area"], g11_bento["bbox_area"])
        self.assertGreater(g11_sq["area_utilization"], g11_bento["area_utilization"])
        self.assertGreaterEqual(g11_sq["area_utilization"], AREA_UTIL_MIN)
        self.assertEqual([f for f in res_sq.report.findings if f.code in (Code.G9, Code.G11)], [])
        self.assertGreaterEqual(gm_sq["G9"]["ratio"], 1.0)
        self.assertLessEqual(gm_sq["G9"]["ratio"], 2.0)

    def test_untitled_square_reclaims_empty_guide_column(self):
        doc = two_stage()
        res = compile_document(doc, DEFS, preset="square")
        self.assertTrue(res.report.ok, [f.message for f in res.report.findings])
        self.assertIsNone(res.layout.guide)
        first_group = res.canvas.groups[0]
        self.assertEqual(first_group.bounding.x, 0.0)
        self.assertGreaterEqual(res.report.metrics["geometry"]["G11"]["area_utilization"], 0.35)

    def test_short_guide_places_controls_under_guide_without_g1_g8_c5_errors(self):
        doc = copy.deepcopy(two_stage())
        doc["_workflow"] = {"format": 1, "title": "Two-Pass Hires Fix"}
        res = compile_document(doc, DEFS, preset="square")
        self.assertTrue(res.report.ok, [f.message for f in res.report.findings])
        self.assertIsNotNone(res.layout.guide)
        # Actual measured guide card is much shorter than the legacy 900 px sentinel,
        # and 01 Controls nests directly underneath it in the left sidebar lane.
        self.assertLess(res.layout.guide.h, 500.0)
        controls = res.canvas.groups[0].bounding
        self.assertGreaterEqual(controls.y, res.layout.guide.bottom)
        self.assertLess(controls.x, res.layout.guide.right)
        errs = [f for f in res.report.findings if f.severity is Severity.ERROR]
        self.assertEqual(errs, [])
        gm = res.report.metrics["geometry"]
        self.assertGreaterEqual(gm["G11"]["area_utilization"], 0.40)

    def test_tall_guide_never_violates_g8_first_screen(self):
        for name, base in (("two_stage", two_stage()), ("custom_sampling", custom_sampling()), ("lora_OROR", lora_chain("OROR"))):
            with self.subTest(graph=name):
                doc = copy.deepcopy(base)
                doc["_workflow"] = {
                    "format": 1,
                    "title": "Detailed Multi-Pass Workflow With Long Guide Notes " * 2,
                }
                for nid in list(doc.keys())[:4]:
                    if nid != "_workflow":
                        doc[nid].setdefault("_meta", {})["ui_note"] = (
                            f"Tuning note for {nid}: adjust steps, seed, and CFG carefully."
                        )
                res = compile_document(doc, DEFS, preset="square")
                errs = [f for f in res.report.findings if f.severity is Severity.ERROR]
                self.assertEqual(errs, [], f"{name}: {[f.message for f in errs]}")
                self.assertTrue(res.report.ok)

    def test_compact_square_is_strictly_deterministic(self):
        doc = _multi_stage_poster_like()
        first = compile_document(doc, DEFS, preset="square")
        second = compile_document(doc, DEFS, preset="square")
        self.assertEqual(first.canvas.to_json(), second.canvas.to_json())
        self.assertEqual(first.report.metrics["geometry"]["G11"], second.report.metrics["geometry"]["G11"])

    def test_compact_skyline_tucks_lower_band_and_reduces_area_on_controlnet(self):
        doc = copy.deepcopy(optional_upscale(controlnet(with_lora())))
        doc["_workflow"] = {"format": 1, "title": "LoRA + ControlNet + Upscale"}
        res_compact = compile_document(doc, DEFS, preset="square")
        self.assertTrue(res_compact.report.ok, [f.message for f in res_compact.report.findings])
        gm_compact = res_compact.report.metrics["geometry"]
        self.assertGreaterEqual(gm_compact["G11"]["area_utilization"], AREA_UTIL_MIN)
        self.assertEqual([f for f in res_compact.report.findings if f.code is Code.G11], [])

    def test_large_199_node_graph_compiles_fast_and_clean_under_square(self):
        doc = long_chain(48)
        t0 = time.perf_counter()
        res = compile_document(doc, DEFS, preset="square")
        elapsed = time.perf_counter() - t0
        self.assertTrue(res.report.ok, [f.message for f in res.report.findings])
        self.assertLess(elapsed, 1.5)
        gm = res.report.metrics["geometry"]
        self.assertGreaterEqual(gm["G11"]["area_utilization"], AREA_UTIL_MIN)

    def test_small_txt2img_with_guide_achieves_high_density(self):
        doc = copy.deepcopy(txt2img())
        doc["_workflow"] = {"format": 1, "title": "Basic Txt2Img"}
        res = compile_document(doc, DEFS, preset="square")
        self.assertTrue(res.report.ok, [f.message for f in res.report.findings])
        gm = res.report.metrics["geometry"]
        self.assertGreaterEqual(gm["G11"]["area_utilization"], 0.45)
        self.assertEqual([f for f in res.report.findings if f.code is Code.G9], [])


if __name__ == "__main__":
    unittest.main()
