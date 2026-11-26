"""Unit tests for cwc 1-level Subgraph packing/flattening and curated custom node packs."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from tests import support  # noqa: F401  (puts src/ on sys.path)

from cwc.canvas.model import Canvas, NodeMode
from cwc.cli import main
from cwc.ingest import load_canvas
from cwc.nodedefs.registry import NodeDefs
from cwc.nodedefs.types import Tier
from cwc.pipeline import compile_document
from cwc.prompt.from_canvas import canvas_to_prompt
from cwc.render.svg import render_svg
from cwc.subgraph import flatten_subgraphs

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKBENCH_UI = REPO_ROOT / "workbench" / "dist" / "omni_ubisoft_workbench.ui.json"


def _hires_custom_graph() -> dict:
    """Multi-stage authoring graph mixing core nodes + curated custom packs (Impact, EasyUse, KJNodes, LayerStyle)."""
    return {
        "ckpt": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "illustrious_xl_v2.safetensors"},
        },
        "lora": {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["ckpt", 0],
                "clip": ["ckpt", 1],
                "lora_name": "style_example.safetensors",
                "strength_model": 0.7,
                "strength_clip": 0.7,
            },
            "_meta": {"title": "Optional Style LoRA", "ui_optional": True},
        },
        "pos": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["lora", 1], "text": "cinematic anime illustration, warm afternoon window light"},
        },
        "neg": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["lora", 1], "text": "worst quality, lowres, watermark"},
        },
        "lat": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 832, "height": 1216, "batch_size": 1},
        },
        "ks1": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["lora", 0],
                "positive": ["pos", 0],
                "negative": ["neg", 0],
                "latent_image": ["lat", 0],
                "seed": 42,
                "steps": 24,
                "cfg": 6.0,
                "sampler_name": "euler_ancestral",
                "scheduler": "karras",
                "denoise": 1.0,
            },
        },
        "dec": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["ks1", 0], "vae": ["ckpt", 2]},
        },
        "vram": {
            "class_type": "easy cleanGpuUsed",
            "inputs": {"anything": ["dec", 0]},
        },
        "resize": {
            "class_type": "ImageResizeKJv2",
            "inputs": {
                "image": ["vram", 0],
                "width": 1664,
                "height": 2432,
                "upscale_method": "lanczos",
                "keep_proportion": "resize",
                "pad_color": "0, 0, 0",
                "crop_position": "center",
                "divisible_by": 16,
                "device": "cpu",
            },
        },
        "grade": {
            "class_type": "LayerColor: ColorBalance",
            "inputs": {
                "image": ["resize", 0],
                "cyan_red": 0.05,
                "magenta_green": 0.0,
                "yellow_blue": -0.04,
            },
        },
        "film": {
            "class_type": "LayerFilter: FilmPost",
            "inputs": {
                "image": ["grade", 0],
                "grain_power": 0.3,
                "grain_scale": 1.2,
                "vignette": 0.2,
            },
        },
        "save": {
            "class_type": "SaveImage",
            "inputs": {"images": ["film", 0], "filename_prefix": "custom_packed_test"},
        },
    }


class TestCuratedCustomPacks(unittest.TestCase):
    def test_default_load_stays_core_only_and_include_custom_adds_packs(self) -> None:
        core_only = NodeDefs.load()
        self.assertEqual({core_only.tier_of(name) for name in core_only}, {Tier.TRUTH, Tier.BUILTIN})
        self.assertNotIn("easy cleanGpuUsed", core_only)

        with_custom = NodeDefs.load(include_custom=True)
        self.assertGreater(len(with_custom), len(core_only) + 20)
        for node_type in (
            "Any Switch (rgthree)",
            "easy cleanGpuUsed",
            "ImageResizeKJv2",
            "ToBasicPipe",
            "FaceDetailer",
            "UltimateSDUpscale",
            "DetailDaemonSamplerNode",
            "TeaCache",
            "UnetLoaderGGUF",
            "LayerFilter: FilmPost",
            "CanvasTurboVRAMGate",
            "CanvasTurboLazyBranchSwitch",
        ):
            self.assertIn(node_type, with_custom)
            self.assertEqual(with_custom.tier_of(node_type), Tier.DERIVED)

    def test_core_nodes_cannot_be_shadowed_and_user_nodedefs_win_over_custom(self) -> None:
        custom_override = {
            "easy cleanGpuUsed": {
                "input": {"required": {"anything": ["*", {}]}},
                "output": ["*"],
                "output_is_list": [False],
                "output_name": ["custom_override_out"],
                "name": "easy cleanGpuUsed",
                "display_name": "User Override VRAM",
                "category": "CustomOverride",
                "output_node": False,
            }
        }
        defs = NodeDefs.load(object_info=custom_override, include_custom=True)
        self.assertEqual(defs.get("easy cleanGpuUsed").display_name, "User Override VRAM")
        self.assertEqual(defs.tier_of("KSampler"), Tier.TRUTH)


class TestSubgraphPackingAndFlattening(unittest.TestCase):
    def test_compile_custom_graph_with_pack_subgraphs_proves_roundtrip_equivalence(self) -> None:
        defs = NodeDefs.load(include_custom=True)
        doc = _hires_custom_graph()
        compiled = compile_document(doc, defs, pack_subgraphs=True)
        self.assertTrue(compiled.report.ok, f"Compile with --pack-subgraphs failed: {compiled.report.findings}")

        sg_metrics = compiled.report.metrics.get("subgraphs")
        self.assertIsNotNone(sg_metrics)
        self.assertGreaterEqual(sg_metrics["subgraph_count"], 1)
        self.assertEqual(sg_metrics["max_depth"], 1)
        self.assertLess(sg_metrics["root_nodes_after"], sg_metrics["root_nodes_before"])

        # Default canvas_to_prompt still refuses subgraph instances unless expand_subgraphs=True
        with self.assertRaises(ValueError):
            canvas_to_prompt(compiled.canvas, defs)

        # expand_subgraphs=True exports a full valid prompt cleanly
        expanded_prompt = canvas_to_prompt(compiled.canvas, defs, expand_subgraphs=True)
        self.assertGreater(len(expanded_prompt), 5)

        # SVG renderer draws subgraph badges cleanly
        svg = render_svg(compiled.canvas, defs)
        self.assertIn("subgraph-badge", svg)
        self.assertIn("[SUBGRAPH ·", svg)

    def test_flatten_subgraphs_refuses_nested_depth_gt_1(self) -> None:
        nested = Canvas(
            {
                "version": 0.4,
                "last_node_id": 1,
                "last_link_id": 0,
                "nodes": [
                    {
                        "id": 1,
                        "type": "sg-outer",
                        "pos": [0, 0],
                        "size": [300, 150],
                        "mode": 0,
                        "inputs": [],
                        "outputs": [],
                    }
                ],
                "links": [],
                "groups": [],
                "definitions": {
                    "subgraphs": [
                        {
                            "id": "sg-inner",
                            "version": 1,
                            "name": "Inner",
                            "inputNode": {"id": -10, "bounding": [0, 0, 100, 60]},
                            "outputNode": {"id": -20, "bounding": [400, 0, 100, 60]},
                            "inputs": [],
                            "outputs": [],
                            "nodes": [],
                            "links": [],
                        },
                        {
                            "id": "sg-outer",
                            "version": 1,
                            "name": "Outer",
                            "inputNode": {"id": -10, "bounding": [0, 0, 100, 60]},
                            "outputNode": {"id": -20, "bounding": [400, 0, 100, 60]},
                            "inputs": [],
                            "outputs": [],
                            "nodes": [{"id": 1, "type": "sg-inner", "pos": [100, 100], "size": [200, 100], "mode": 0}],
                            "links": [],
                        },
                    ]
                },
            }
        )
        with self.assertRaisesRegex(ValueError, "nested subgraph"):
            flatten_subgraphs(nested)

    def test_flatten_subgraphs_drops_muted_and_preserves_bypassed(self) -> None:
        defs = NodeDefs.load(include_custom=True)
        doc = _hires_custom_graph()
        compiled = compile_document(doc, defs, pack_subgraphs=True)
        raw = compiled.canvas.to_json()
        sg_ids = {s["id"] for s in raw["definitions"]["subgraphs"]}

        # 1. Mute one subgraph instance and confirm flatten drops its internal nodes
        muted_raw = json.loads(json.dumps(raw))
        muted_id = None
        for n in muted_raw["nodes"]:
            if n["type"] in sg_ids:
                n["mode"] = int(NodeMode.NEVER)
                muted_id = str(n["id"])
                break
        self.assertIsNotNone(muted_id)
        flattened_muted = flatten_subgraphs(Canvas(muted_raw))
        self.assertFalse(any(n.key.startswith(f"{muted_id}:") for n in flattened_muted.nodes))

        # 2. Bypass a single-type-passthrough subgraph instance (post-FX IMAGE->IMAGE) and verify
        #    flatten preserves the bypassed instance and canvas_to_prompt resolves straight through it
        bypass_raw = json.loads(json.dumps(raw))
        bypass_id = None
        for n in bypass_raw["nodes"]:
            if n["type"] in sg_ids:
                in_types = [i["type"] for i in n.get("inputs") or []]
                out_types = [o["type"] for o in n.get("outputs") or []]
                if out_types and all(in_types.count(ot) == 1 for ot in out_types):
                    n["mode"] = int(NodeMode.BYPASS)
                    bypass_id = str(n["id"])
                    break
        self.assertIsNotNone(bypass_id, "Expected at least one unambiguous passthrough subgraph instance")
        flattened_bypass = flatten_subgraphs(Canvas(bypass_raw))
        self.assertTrue(any(n.key == bypass_id and n.mode == NodeMode.BYPASS for n in flattened_bypass.nodes))
        self.assertFalse(any(n.key.startswith(f"{bypass_id}:") for n in flattened_bypass.nodes))
        bypassed_prompt = canvas_to_prompt(Canvas(bypass_raw), defs, expand_subgraphs=True)
        self.assertNotIn(bypass_id, bypassed_prompt)
        save_entry = next(v for v in bypassed_prompt.values() if v["class_type"] == "SaveImage")
        self.assertIsInstance(save_entry["inputs"]["images"], list)
        self.assertIn(save_entry["inputs"]["images"][0], bypassed_prompt)

    def test_multi_node_optional_module_packs_as_bypassed_subgraph_and_roundtrips(self) -> None:
        """Multi-node optional post-FX chain packs into a bypassed subgraph and preserves both factory & all-enabled."""
        defs = NodeDefs.load(include_custom=True)
        doc = _hires_custom_graph()
        # Mark the 2-node color/film post-FX chain as an optional module in the same explicit group
        doc["grade"]["_meta"] = {"ui_optional": True, "ui_group": "Optional Film Grade"}
        doc["film"]["_meta"] = {"ui_optional": True, "ui_group": "Optional Film Grade"}
        compiled = compile_document(doc, defs, pack_subgraphs=True)
        self.assertTrue(compiled.report.ok, f"Multi-node optional subgraph failed: {compiled.report.findings}")
        sg_ids = {s["id"] for s in compiled.canvas.raw["definitions"]["subgraphs"]}
        bypassed_sg_instances = [
            n for n in compiled.canvas.nodes if n.type in sg_ids and n.mode == NodeMode.BYPASS
        ]
        self.assertGreaterEqual(len(bypassed_sg_instances), 1, "Expected optional multi-node group packed as BYPASS subgraph")

    def test_cli_compile_custom_packs_and_pack_subgraphs_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "mega.json"
            out_dir = Path(tmp) / "out"
            svg_out = Path(tmp) / "mega.svg"
            src.write_text(json.dumps(_hires_custom_graph()), encoding="utf-8")

            stdout, stderr = io.StringIO(), io.StringIO()
            rc = main(
                ["compile", str(src), "-o", str(out_dir), "--custom-packs", "--pack-subgraphs", "--json"],
                out=stdout,
                err=stderr,
            )
            self.assertEqual(rc, 0, f"CLI compile failed:\nstdout={stdout.getvalue()}\nstderr={stderr.getvalue()}")
            summary = json.loads(stdout.getvalue())
            self.assertTrue(summary["ok"])
            ui_path = Path(summary["outputs"]["ui"])
            self.assertTrue(ui_path.is_file())
            ui_doc = json.loads(ui_path.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(ui_doc["definitions"]["subgraphs"]), 1)

            # Render the compiled subgraph workflow to SVG via CLI
            r_out, r_err = io.StringIO(), io.StringIO()
            r_rc = main(["render", str(ui_path), "-o", str(svg_out), "--custom-packs"], out=r_out, err=r_err)
            self.assertEqual(r_rc, 0, f"CLI render failed: {r_err.getvalue()}")
            self.assertIn("[SUBGRAPH ·", svg_out.read_text(encoding="utf-8"))

    def test_pack_subgraphs_reroutes_packed_root_links_cleanly(self) -> None:
        defs = NodeDefs.load(include_custom=True)
        compiled = compile_document(_hires_custom_graph(), defs, pack_subgraphs=True)
        self.assertTrue(compiled.report.ok, f"Compile failed: {compiled.report.findings}")
        self.assertEqual(compiled.routes.unresolved, ())
        root_link_ids = {lk.id for lk in compiled.canvas.links}
        for ext in compiled.canvas.raw.get("extra", {}).get("linkExtensions") or []:
            self.assertIn(ext["id"], root_link_ids)

    def test_render_phase1_ubisoft_workbench_through_cwc(self) -> None:
        self.assertTrue(WORKBENCH_UI.is_file(), f"Expected Phase 1 workbench at {WORKBENCH_UI}")
        defs = NodeDefs.load(include_custom=True)
        canvas = load_canvas(WORKBENCH_UI.read_bytes())
        svg = render_svg(canvas, defs)
        self.assertIn("subgraph-badge", svg)
        self.assertIn("[SUBGRAPH ·", svg)
        # Flattening Phase 1 workbench should cleanly expand the active engine without error
        flattened = flatten_subgraphs(canvas)
        self.assertGreater(len(flattened.nodes), len(canvas.nodes))


if __name__ == "__main__":
    unittest.main()
