"""Unit tests for ComfyUI-Canvas-Turbo companion backend nodes."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

NODES_PATH = Path(__file__).resolve().parents[1] / "nodes.py"
SPEC = importlib.util.spec_from_file_location("canvas_turbo_nodes", NODES_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules["canvas_turbo_nodes"] = MOD
SPEC.loader.exec_module(MOD)


class TestCanvasTurboNodes(unittest.TestCase):
    def test_vram_gate_is_changed_returns_nan_and_passthrough_works(self) -> None:
        import math

        gate = MOD.CanvasTurboVRAMGate()
        self.assertTrue(math.isnan(MOD.CanvasTurboVRAMGate.IS_CHANGED("x", "unload_models_and_cache")))
        payload = {"tensor": "fake_image_batch", "shape": [1, 1024, 1024, 3]}
        for mode in ("soft_cache_clear", "unload_models_and_cache", "passthrough_only"):
            out = gate.execute(payload, flush_mode=mode)
            self.assertEqual(out, (payload,))

    def test_lazy_branch_switch_requests_only_selected_branch(self) -> None:
        sw = MOD.CanvasTurboLazyBranchSwitch()
        inp_types = sw.INPUT_TYPES()
        for i in range(sw.MAX_BRANCHES):
            self.assertTrue(inp_types["optional"][f"branch_{i}"][1]["lazy"])

        # Only branch_3 requested when index == 3 and branch_3 is not yet evaluated
        needed = sw.check_lazy_status(index=3, branch_0="already_here", branch_3=None)
        self.assertEqual(needed, ["branch_3"])

        # Once branch_3 is provided, nothing more is needed
        self.assertEqual(sw.check_lazy_status(index=3, branch_3="ready"), [])
        self.assertEqual(sw.execute(index=3, branch_0="wrong", branch_3="right"), ("right",))

    def test_lazy_branch_switch_clamps_out_of_range_index(self) -> None:
        sw = MOD.CanvasTurboLazyBranchSwitch()
        self.assertEqual(sw.check_lazy_status(index=-5), ["branch_0"])
        self.assertEqual(sw.check_lazy_status(index=99), [f"branch_{sw.MAX_BRANCHES - 1}"])
        self.assertEqual(sw.execute(index=99, branch_7="last"), ("last",))

    def test_wildcard_type_matches_any_comfy_type_and_is_hashable(self) -> None:
        self.assertEqual(MOD.ANY, "IMAGE")
        self.assertEqual(MOD.ANY, "BASIC_PIPE")
        self.assertFalse(MOD.ANY != "LATENT")
        self.assertIn(MOD.ANY, {MOD.ANY})
        self.assertEqual(hash(MOD.ANY), hash("*"))

    def test_js_core_suite_passes_under_node(self) -> None:
        import shutil
        import subprocess

        node = shutil.which("node")
        if node is None:
            self.fail("node binary required to verify canvas_turbo_core.mjs tests")
        test_file = Path(__file__).with_name("test_canvas_turbo_core.mjs")
        proc = subprocess.run([node, "--test", str(test_file)], capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, f"JS core tests failed:\n{proc.stdout}\n{proc.stderr}")


if __name__ == "__main__":
    unittest.main()
