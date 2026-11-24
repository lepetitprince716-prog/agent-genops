import unittest
from pathlib import Path

from tests import support  # noqa: F401  (puts src/ on sys.path)

from cwc.report import Code, Mode, Severity
from cwc.verify import verify_canvas, verify_compile
from tests.fixtures.prompt.build import CanvasBuilder, load_defs
from tests.fixtures.verify.canvases import BYPASS, MUTED, add_group, authoring, place

DEFS = load_defs(Path(__file__).parent / "fixtures" / "verify" / "stage_defs.json")


def found(canvas, mode=Mode.BEAUTIFY):
    report = verify_canvas(canvas, DEFS, mode=mode)
    return [f for f in report.findings if f.code is Code.N7]


def pairs(findings):
    return [f.nodes for f in findings]


class Stages:
    """Builder for the graphs below. Ids are fixed per role so each test reads as a diagram."""

    def __init__(self):
        self.b = CanvasBuilder(DEFS)
        self.b.add(1, "StageLoader", widgets=["m.safetensors"])
        self.b.add(2, "StageLatent")

    def add(self, node_id, type, *, mode=0, **kwargs):
        self.b.add(node_id, type, mode=mode, **kwargs)
        return node_id

    def sampler(self, node_id, latent_from, *, mode=0, type="StageSampler"):
        self.b.add(node_id, type, mode=mode)
        if type == "StageGuidedSampler":
            self.b.add(node_id + 100, "StageGuider", mode=mode)
            self.b.link(1, 0, node_id + 100, "model")
            self.b.link(node_id + 100, 0, node_id, "guider")
        else:
            self.b.link(1, 0, node_id, "model")
        self.b.link(latent_from, 0, node_id, "latent_image")
        return node_id

    def decode(self, node_id, latent_from, *, mode=0):
        self.b.add(node_id, "StageDecode", mode=mode)
        self.b.link(latent_from, 0, node_id, "samples")
        self.b.link(1, 1, node_id, "vae")
        return node_id

    def encode(self, node_id, image_from, *, mode=0):
        self.b.add(node_id, "StageEncode", mode=mode)
        self.b.link(image_from, 0, node_id, "pixels")
        self.b.link(1, 1, node_id, "vae")
        return node_id

    def after(self, node_id, type, source, target_input, *, mode=0):
        self.b.add(node_id, type, mode=mode)
        self.b.link(source, 0, node_id, target_input)
        return node_id

    def canvas(self):
        return self.b.canvas()


def image_upscale(preview=None, **sampler_kwargs):
    """1 loader, 2 latent, 10 sampler, 11 decode, 12 scale, 13 encode, 14 sampler, 15 decode, 16 save;
    ``preview`` is (id, type) added on the first decode."""
    s = Stages()
    s.sampler(10, 2, **sampler_kwargs)
    s.decode(11, 10)
    s.after(12, "StageImageScale", 11, "image")
    s.encode(13, 12)
    s.sampler(14, 13)
    s.decode(15, 14)
    s.after(16, "StageSave", 15, "images")
    if preview:
        s.after(preview[0], preview[1], 11, "image_a" if preview[1] == "StageCompare" else "images")
    return s


class HandoffTest(unittest.TestCase):
    def test_single_stage_has_no_handoff(self):
        s = Stages()
        s.sampler(10, 2)
        s.decode(11, 10)
        s.after(12, "StageSave", 11, "images")
        self.assertEqual(found(s.canvas()), [])

    def test_image_domain_upscale_without_preview_is_one_finding(self):
        [finding] = found(image_upscale().canvas())
        self.assertEqual((finding.nodes, finding.severity), (("10", "14"), Severity.INFO))
        self.assertEqual(finding.data, {"from": "10", "to": "14"})
        self.assertIn("node 11 (StageDecode)", finding.message)
        self.assertIn("PreviewImage", finding.hint)
        self.assertIn("ImageCompare", finding.hint)

    def test_a_preview_on_the_decode_covers_the_handoff(self):
        for kind in ("StagePreview", "StageSave", "StageCompare"):
            with self.subTest(kind):
                self.assertEqual(found(image_upscale((20, kind)).canvas()), [])

    def test_a_preview_further_along_the_image_path_covers_it(self):
        s = image_upscale()
        s.after(20, "StagePreview", 12, "images")  # on the scaled image
        self.assertEqual(found(s.canvas()), [])

    def test_a_link_through_a_legacy_reroute_counts(self):
        s = image_upscale()
        s.b.add(20, "StageReroute", ins=[("", "*")], outs=["*"])
        s.b.add(21, "StagePreview", mode=0)
        s.b.link(11, 0, 20, 0)
        s.b.link(20, 0, 21, "images")
        self.assertEqual(found(s.canvas()), [])


class LatentHandoffTest(unittest.TestCase):
    def latent_upscale(self):
        s = Stages()
        s.sampler(10, 2)
        s.after(11, "StageLatentScale", 10, "samples")
        s.sampler(12, 11)
        s.decode(13, 12)
        s.after(14, "StageSave", 13, "images")
        return s

    def test_pure_latent_handoff_without_a_decode_preview_is_reported(self):
        [finding] = found(self.latent_upscale().canvas())
        self.assertEqual(finding.nodes, ("10", "12"))
        self.assertIn("decode the output of node 10", finding.message)

    def test_a_decode_beside_the_handoff_without_preview_is_still_reported(self):
        s = self.latent_upscale()
        s.decode(20, 10)
        self.assertEqual(pairs(found(s.canvas())), [("10", "12")])

    def test_a_decode_beside_the_handoff_with_preview_covers_it(self):
        s = self.latent_upscale()
        s.decode(20, 10)
        s.after(21, "StagePreview", 20, "images")
        self.assertEqual(found(s.canvas()), [])

    def test_the_second_stage_picture_is_not_the_first_stage_preview(self):
        s = self.latent_upscale()
        s.after(20, "StagePreview", 13, "images")
        self.assertEqual(pairs(found(s.canvas())), [("10", "12")])

    def test_an_image_made_from_both_stages_is_not_a_first_stage_preview(self):
        s = self.latent_upscale()
        s.decode(20, 10)
        s.b.add(21, "StageImageMix")
        s.b.link(20, 0, 21, "image_a")
        s.b.link(13, 0, 21, "image_b")
        s.after(22, "StagePreview", 21, "images")
        self.assertEqual(pairs(found(s.canvas())), [("10", "12")])


class ChainTest(unittest.TestCase):
    def chain(self, previews):
        s = Stages()
        s.sampler(10, 2)
        s.decode(11, 10)
        s.after(12, "StageLatentScale", 10, "samples")
        s.sampler(13, 12)
        s.decode(14, 13)
        s.after(15, "StageLatentScale", 13, "samples")
        s.sampler(16, 15)
        s.decode(17, 16)
        s.after(18, "StageSave", 17, "images")
        for decode in previews:
            s.after(decode + 50, "StagePreview", decode, "images")
        return s.canvas()

    def test_each_boundary_is_judged_alone(self):
        self.assertEqual(pairs(found(self.chain([11, 14]))), [])
        self.assertEqual(pairs(found(self.chain([11]))), [("13", "16")])
        self.assertEqual(pairs(found(self.chain([14]))), [("10", "13")])
        self.assertEqual(pairs(found(self.chain([]))), [("10", "13"), ("13", "16")])

    def test_a_sampler_further_down_the_chain_is_not_a_handoff_of_the_first(self):
        # 10 reaches 16 only through sampler 13
        self.assertNotIn(("10", "16"), pairs(found(self.chain([]))))


class SamplerKindTest(unittest.TestCase):
    def test_a_guided_sampler_is_a_stage(self):
        s = Stages()
        s.sampler(10, 2, type="StageGuidedSampler")
        s.decode(11, 10)
        s.sampler(12, 10, type="StageGuidedSampler")
        s.decode(13, 12)
        s.after(14, "StageSave", 13, "images")
        self.assertEqual(pairs(found(s.canvas())), [("10", "12")])

    def test_a_muted_sampler_is_not_a_stage(self):
        s = image_upscale(mode=int(MUTED))
        self.assertEqual(found(s.canvas()), [])
        s = Stages()
        s.sampler(10, 2)
        s.decode(11, 10)
        s.after(12, "StageImageScale", 11, "image")
        s.encode(13, 12)
        s.sampler(14, 13, mode=int(MUTED))
        self.assertEqual(found(s.canvas()), [])

    def test_a_node_that_is_not_a_sampler_is_not_a_stage(self):
        s = Stages()
        s.after(10, "StageLatentScale", 2, "samples")
        s.after(11, "StageLatentScale", 10, "samples")
        s.decode(12, 11)
        s.after(13, "StageSave", 12, "images")
        self.assertEqual(found(s.canvas()), [])

    def test_a_sampler_reached_by_a_non_latent_input_is_not_a_handoff(self):
        s = Stages()
        s.sampler(10, 2)
        s.b.add(11, "StageGuider")
        s.b.link(1, 0, 11, "model")
        s.sampler(12, 2)
        s.decode(13, 12)
        s.after(14, "StageSave", 13, "images")
        self.assertEqual(found(s.canvas()), [])


class ModeTest(unittest.TestCase):
    """The main branch runs (mode 0) and an A/B module (mode 4) sits in groups beside it."""

    def workflow(self, *, compare_in_module=True, preview_on_main=True, main_preview_mode=0, compare_mode=int(BYPASS), split=False, titles=("01a A/B", "01b A/B")):
        s = Stages()
        s.sampler(10, 2)
        s.decode(11, 10)
        s.after(12, "StageImageScale", 11, "image")
        s.encode(13, 12)
        s.sampler(14, 13)
        s.decode(15, 14)
        s.after(16, "StageSave", 15, "images")
        if preview_on_main:
            s.after(17, "StagePreview", 11, "images", mode=main_preview_mode)
        s.sampler(30, 2, mode=int(BYPASS))
        s.decode(31, 30, mode=int(BYPASS))
        s.after(32, "StageImageScale", 31, "image", mode=int(BYPASS))
        s.encode(33, 32, mode=int(BYPASS))
        s.sampler(34, 33, mode=int(BYPASS))
        s.b.add(35, "StageCompare", mode=compare_mode)
        s.b.link(11, 0, 35, "image_a")
        s.b.link(31, 0, 35, "image_b")
        canvas = s.canvas()
        positions = {1: (0, 0), 2: (0, 200), 10: (400, 0), 11: (800, 0), 12: (1200, 0), 13: (1600, 0), 14: (2000, 0), 15: (2400, 0), 16: (2800, 0), 17: (800, 200)}
        positions.update({30: (4100, 100), 31: (4400, 100), 32: (4700, 100), 33: (5000, 100), 34: (5300, 100)})
        positions[35] = (4400, 300) if compare_in_module else (800, 400)
        place(canvas, positions)
        if split:
            add_group(canvas, titles[0], [4080, 20, 740, 420])
            add_group(canvas, titles[1], [4880, 20, 740, 420])
        else:
            add_group(canvas, "A/B", [4080, 20, 1500, 440])
        return canvas

    def test_a_preview_in_the_one_bypassed_box_with_both_samplers_counts(self):
        self.assertEqual(pairs(found(self.workflow())), [])

    def test_a_module_split_over_two_boxes_is_two_modules(self):
        # the compare node and the next sampler sit in different boxes: one toggle leaves a part bypassed
        self.assertEqual(pairs(found(self.workflow(split=True))), [("30", "34")])

    def test_boxes_with_the_same_title_are_not_merged(self):
        self.assertEqual(pairs(found(self.workflow(split=True, titles=("A/B", "A/B")))), [("30", "34")])

    def test_main_branch_without_its_own_preview_is_reported(self):
        self.assertEqual(pairs(found(self.workflow(preview_on_main=False))), [("10", "14")])

    def test_a_compare_node_outside_the_module_does_not_cover_the_module_stage(self):
        self.assertEqual(pairs(found(self.workflow(compare_in_module=False))), [("30", "34")])

    def test_a_muted_preview_does_not_count(self):
        self.assertEqual(pairs(found(self.workflow(main_preview_mode=int(MUTED)))), [("10", "14")])
        self.assertEqual(pairs(found(self.workflow(compare_mode=int(MUTED)))), [("30", "34")])

    def test_a_bypassed_preview_on_a_running_branch_does_not_count(self):
        self.assertEqual(pairs(found(self.workflow(main_preview_mode=int(BYPASS)))), [("10", "14")])

    def test_a_compare_node_that_runs_alone_covers_the_module_stage(self):
        # mode 0 outside the module: it runs whether or not the module is on
        self.assertEqual(pairs(found(self.workflow(compare_in_module=False, compare_mode=0))), [])


class CompileModeTest(unittest.TestCase):
    def test_compile_verification_reports_it_too_and_never_blocks(self):
        canvas = image_upscale().canvas()
        report = verify_compile(canvas, authoring(), DEFS)
        [finding] = [f for f in report.findings if f.code is Code.N7]
        self.assertIs(finding.severity, Severity.INFO)
        for mode in (Mode.COMPILE, Mode.BEAUTIFY):
            [only] = found(canvas, mode)
            self.assertIs(only.severity, Severity.INFO)


if __name__ == "__main__":
    unittest.main()
