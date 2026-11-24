"""Hidden links: the ``stack`` preset marks its resource links between columns hidden in
``extra.linkPresentation`` (:mod:`cwc.route.presentation`).

1. under ``stack`` the hidden links are exactly the links of ``LayoutResult.forced`` whose type is
   MODEL, CLIP, VAE or CONDITIONING; a LATENT or IMAGE link between columns and a resource link
   inside a column stay drawn;
2. hiding changes nothing else: the canvas without ``extra.linkPresentation`` is the canvas
   compiled with hiding off, byte for byte, reroutes included;
3. the key has the frontend's shape: link ids as decimal strings in ascending order, each to
   ``{"hidden": true}`` or ``{"hidden": true, "label": <text>}``;
4. labels: a type whose hidden links leave two or more outputs labels each of its links with the
   source node's title, else the definition's display name, else the output's name; a type with
   one output writes no label, so the frontend stacks its links into one badge;
5. the ``x`` presets write no ``extra.linkPresentation``, also when hiding is asked for;
6. the preset decides the default (``stack``: resources, the rest: none) and ``compile_document``
   and ``cwc compile --hide-links`` override it.
"""

from __future__ import annotations

import copy
import json
import unittest

from tests import support
from tests.graphs import DEFS
from tests.layout_cases import OTHERS, SIMPLE, with_lora
from tests.layout_generator import random_graph
from tests.test_cli_compile import TXT2IMG, Folder, run

from cwc.canvas.model import Canvas
from cwc.emit.canonical import json_bytes
from cwc.layout.presets import get_preset, load_presets, parse_presets
from cwc.layout.types import HideLinks
from cwc.nodedefs.registry import NodeDefs
from cwc.pipeline import compile_document
from cwc.report import ExitCode
from cwc.resources import read_json
from cwc.route.presentation import KEY, mark_hidden

RESOURCES = {"MODEL", "CLIP", "VAE", "CONDITIONING"}  # what the packet of this feature names
X_PRESETS = ("bento", "swimlanes", "cockpit-split", "tower-preview", "stepped")
STACK_FIXTURE = support.FIXTURES / "layout" / "stack_two_pass.json"
STACK_OBJECT_INFO = support.FIXTURES / "layout" / "stack_two_pass.object_info.json"


def builders():
    out = {**SIMPLE, **OTHERS, "required_lora": lambda: with_lora(optional=False)}
    out.update({f"seed_{seed}": (lambda seed=seed: random_graph(seed)) for seed in (0, 3, 4, 11, 14)})
    return out


def stripped(canvas: Canvas) -> bytes:
    raw = canvas.to_json()
    raw["extra"].pop(KEY, None)
    return json_bytes(raw)


def two_pass(**kwargs):
    defs = NodeDefs.load(object_info=json.loads(STACK_OBJECT_INFO.read_text()))
    return compile_document(json.loads(STACK_FIXTURE.read_text()), defs, preset="stack", **kwargs)


class StackHidesResourceLinksBetweenColumns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiled = {name: compile_document(build(), DEFS, preset="stack") for name, build in builders().items()}
        cls.compiled["stack_two_pass"] = two_pass()

    def test_the_hidden_links_are_the_resource_links_between_columns(self):
        for name, out in self.compiled.items():
            with self.subTest(case=name):
                links = out.canvas.link_map()
                want = sorted(lid for lid in out.layout.forced if links[lid].type in RESOURCES)
                self.assertTrue(want, "every case has a resource link between columns")
                got = sorted(int(key) for key in out.canvas.extra.get(KEY, {}))
                self.assertEqual(got, want)

    def test_main_flow_and_links_inside_a_column_stay_drawn(self):
        seen_flow = seen_inside = False
        for name, out in self.compiled.items():
            hidden = {int(key) for key in out.canvas.extra.get(KEY, {})}
            forced = set(out.layout.forced)
            for link in out.canvas.links:
                if link.id in forced and link.type not in RESOURCES:
                    seen_flow = True
                    self.assertNotIn(link.id, hidden, (name, link))
                if link.id not in forced and link.type in RESOURCES:
                    seen_inside = True
                    self.assertNotIn(link.id, hidden, (name, link))
        self.assertTrue(seen_flow and seen_inside)

    def test_hiding_changes_nothing_else(self):
        for name, build in builders().items():
            with self.subTest(case=name):
                off = compile_document(build(), DEFS, preset="stack", hide_links=HideLinks.NONE)
                self.assertNotIn(KEY, off.canvas.extra)
                self.assertEqual(stripped(self.compiled[name].canvas), json_bytes(off.canvas.to_json()))
        off = two_pass(hide_links=HideLinks.NONE)
        self.assertEqual(stripped(self.compiled["stack_two_pass"].canvas), json_bytes(off.canvas.to_json()))

    def test_the_key_has_the_frontend_shape(self):
        for name, out in self.compiled.items():
            with self.subTest(case=name):
                block = out.canvas.extra[KEY]
                keys = list(block)
                self.assertEqual(keys, [str(k) for k in sorted(int(k) for k in keys)])
                for value in block.values():
                    self.assertIn(list(value), (["hidden"], ["hidden", "label"]))
                    self.assertIs(value["hidden"], True)
                    if "label" in value:
                        self.assertIsInstance(value["label"], str)
                        self.assertTrue(value["label"])
                # the canvas written to disk carries it as plain JSON
                self.assertEqual(json.loads(json_bytes(out.canvas.to_json()))["extra"][KEY], block)

    def test_labels_on_a_compiled_canvas(self):
        out = self.compiled["optional_lora"]
        links, nodes = out.canvas.link_map(), out.canvas.node_map()
        labels = {}
        for key, value in out.canvas.extra[KEY].items():
            link = links[int(key)]
            labels.setdefault(link.type, set()).add(value.get("label"))
        # one checkpoint output each: no label; CLIP from the checkpoint and the LoRA, the two
        # prompts' CONDITIONING: each labelled with its source
        self.assertEqual(labels["MODEL"], {None})
        self.assertEqual(labels["VAE"], {None})
        self.assertEqual(labels["CLIP"], {"Load Checkpoint", "Load LoRA (Model and CLIP)"})
        self.assertEqual(labels["CONDITIONING"], {"Positive prompt", "Negative prompt"})
        self.assertTrue(all(nodes[str(links[int(k)].origin_id)].title is None for k, v in out.canvas.extra[KEY].items() if links[int(k)].type == "CLIP"))


def _canvas(nodes, links):
    return Canvas(
        {
            "nodes": [
                {"id": nid, "type": kind, **({"title": title} if title is not None else {}), "outputs": [{"name": n, "type": t} for n, t in outs]}
                for nid, kind, title, outs in nodes
            ],
            "links": [list(link) for link in links],
            "groups": [],
            "extra": {},
            "version": 0.4,
        }
    )


CKPT = (1, "CheckpointLoaderSimple", None, [("MODEL", "MODEL"), ("CLIP", "CLIP"), ("VAE", "VAE")])


class LabelRule(unittest.TestCase):
    def test_one_output_writes_no_label(self):
        canvas = _canvas([CKPT, (2, "VAEDecode", None, [("IMAGE", "IMAGE")]), (3, "VAEDecode", None, [("IMAGE", "IMAGE")])],
                         [(1, 1, 2, 2, 1, "VAE"), (2, 1, 2, 3, 1, "VAE")])
        mark_hidden(canvas, (1, 2), HideLinks.RESOURCES, DEFS)
        self.assertEqual(canvas.extra[KEY], {"1": {"hidden": True}, "2": {"hidden": True}})

    def test_two_outputs_label_every_link_of_the_type_with_the_title(self):
        lora = (2, "LoraLoader", "Style LoRA", [("MODEL", "MODEL"), ("CLIP", "CLIP")])
        canvas = _canvas([CKPT, lora, (3, "CLIPTextEncode", None, []), (4, "CLIPTextEncode", None, []), (5, "VAEDecode", None, [])],
                         [(1, 1, 1, 3, 0, "CLIP"), (2, 2, 1, 4, 0, "CLIP"), (3, 1, 2, 5, 1, "VAE"), (4, 2, 1, 3, 0, "CLIP")])
        mark_hidden(canvas, (1, 2, 3, 4), HideLinks.RESOURCES, DEFS)
        self.assertEqual(
            canvas.extra[KEY],
            {
                "1": {"hidden": True, "label": "Load Checkpoint"},  # no title: the display name
                "2": {"hidden": True, "label": "Style LoRA"},
                "3": {"hidden": True},  # VAE has one output
                "4": {"hidden": True, "label": "Style LoRA"},
            },
        )

    def test_two_outputs_of_one_node_are_two_sources(self):
        apply = (2, "ControlNetApplyAdvanced", "Pose", [("positive", "CONDITIONING"), ("negative", "CONDITIONING")])
        canvas = _canvas([apply, (3, "KSampler", None, [])], [(1, 2, 0, 3, 1, "CONDITIONING"), (2, 2, 1, 3, 2, "CONDITIONING")])
        mark_hidden(canvas, (1, 2), HideLinks.RESOURCES, DEFS)
        # the title alone would label both links the same: the output's name tells them apart
        self.assertEqual(
            canvas.extra[KEY], {"1": {"hidden": True, "label": "Pose: positive"}, "2": {"hidden": True, "label": "Pose: negative"}}
        )

    def test_two_outputs_of_one_node_without_a_title_use_the_display_name_then_the_output_name(self):
        apply = (2, "ControlNetApplyAdvanced", None, [("positive", "CONDITIONING"), ("negative", "CONDITIONING")])
        canvas = _canvas([apply, (3, "KSampler", None, [])], [(1, 2, 0, 3, 1, "CONDITIONING"), (2, 2, 1, 3, 2, "CONDITIONING")])
        mark_hidden(canvas, (1, 2), HideLinks.RESOURCES, DEFS)
        self.assertEqual(
            canvas.extra[KEY],
            {"1": {"hidden": True, "label": "Apply ControlNet: positive"}, "2": {"hidden": True, "label": "Apply ControlNet: negative"}},
        )
        # a node that fell back to its output names says them once, with no prefix
        bare = (4, "UnknownPackLoader", None, [("base", "MODEL"), ("tuned", "MODEL")])
        canvas = _canvas([bare, (3, "KSampler", None, [])], [(1, 4, 0, 3, 0, "MODEL"), (2, 4, 1, 3, 1, "MODEL")])
        mark_hidden(canvas, (1, 2), HideLinks.RESOURCES, DEFS)
        self.assertEqual(canvas.extra[KEY], {"1": {"hidden": True, "label": "base"}, "2": {"hidden": True, "label": "tuned"}})

    def test_a_type_labels_independently_of_the_others(self):
        # CLIP has two sources, VAE one: only CLIP is labelled, though both come from the same nodes
        lora = (2, "LoraLoader", "Style LoRA", [("MODEL", "MODEL"), ("CLIP", "CLIP")])
        canvas = _canvas([CKPT, lora, (3, "VAEDecode", None, [])], [(1, 1, 1, 2, 1, "CLIP"), (2, 2, 1, 3, 0, "CLIP"), (3, 1, 2, 3, 1, "VAE")])
        mark_hidden(canvas, (1, 2, 3), HideLinks.RESOURCES, DEFS)
        self.assertEqual(
            canvas.extra[KEY],
            {"1": {"hidden": True, "label": "Load Checkpoint"}, "2": {"hidden": True, "label": "Style LoRA"}, "3": {"hidden": True}},
        )

    def test_no_title_and_no_definition_takes_the_output_name_never_the_class(self):
        a = (1, "UnknownPackLoader", None, [("base model", "MODEL")])
        b = (2, "OtherPackLoader", "", [("tuned", "MODEL")])  # an empty title counts as none
        canvas = _canvas([a, b, (3, "KSampler", None, []), (4, "KSampler", None, [])], [(1, 1, 0, 3, 0, "MODEL"), (2, 2, 0, 4, 0, "MODEL")])
        mark_hidden(canvas, (1, 2), HideLinks.RESOURCES, DEFS)
        self.assertEqual(canvas.extra[KEY], {"1": {"hidden": True, "label": "base model"}, "2": {"hidden": True, "label": "tuned"}})

    def test_only_listed_resource_links_are_hidden_and_none_hides_nothing(self):
        canvas = _canvas([CKPT, (2, "EmptyLatentImage", None, [("LATENT", "LATENT")]), (3, "KSampler", None, [])],
                         [(1, 1, 0, 3, 0, "MODEL"), (2, 2, 0, 3, 3, "LATENT"), (3, 1, 2, 3, 1, "VAE")])
        mark_hidden(canvas, (1, 2), HideLinks.RESOURCES, DEFS)  # link 3 is not between columns
        self.assertEqual(canvas.extra[KEY], {"1": {"hidden": True}})
        mark_hidden(canvas, (1, 2), HideLinks.NONE, DEFS)
        self.assertNotIn(KEY, canvas.extra)


class XPresetsWriteNoHiddenLinks(unittest.TestCase):
    def test_no_key_by_default_nor_when_asked(self):
        for preset in X_PRESETS:
            for name in ("txt2img", "optional_lora", "two_stage", "lora_controlnet_upscale"):
                with self.subTest(preset=preset, case=name):
                    build = builders()[name]
                    default = compile_document(build(), DEFS, preset=preset)
                    asked = compile_document(build(), DEFS, preset=preset, hide_links=HideLinks.RESOURCES)
                    self.assertNotIn(KEY, default.canvas.extra)
                    self.assertNotIn(KEY, asked.canvas.extra)
                    self.assertEqual(json_bytes(default.canvas.to_json()), json_bytes(asked.canvas.to_json()))


class PresetDefault(unittest.TestCase):
    def test_stack_hides_resources_and_the_rest_hide_nothing(self):
        want = {name: HideLinks.NONE for name in X_PRESETS} | {"stack": HideLinks.RESOURCES}
        self.assertEqual({name: preset.hide_links for name, preset in load_presets().items()}, want)

    def test_the_presets_document_must_say_it(self):
        doc = copy.deepcopy(read_json("presets.json"))
        doc["presets"]["stack"]["hide_links"] = "everything"
        with self.assertRaisesRegex(ValueError, "hide_links"):
            parse_presets(doc)
        doc = copy.deepcopy(read_json("presets.json"))
        del doc["presets"]["stack"]["hide_links"]
        with self.assertRaisesRegex(ValueError, r"missing keys \['hide_links'\]"):
            parse_presets(doc)

    def test_compile_document_overrides_the_preset(self):
        doc = with_lora()
        self.assertIn(KEY, compile_document(copy.deepcopy(doc), DEFS, preset="stack").canvas.extra)
        self.assertNotIn(KEY, compile_document(copy.deepcopy(doc), DEFS, preset="stack", hide_links=HideLinks.NONE).canvas.extra)
        self.assertIs(get_preset("stack").hide_links, HideLinks.RESOURCES)


class CommandLine(Folder):
    def test_stack_hides_by_default_and_the_flag_turns_it_off(self):
        graph = self.graph(TXT2IMG)
        self.assertEqual(run("compile", graph, "-o", self.out, "--preset", "stack")[0], ExitCode.OK)
        hidden = self.read(".ui.json")
        self.assertTrue(hidden["extra"][KEY])
        self.assertEqual(run("compile", graph, "-o", self.out, "--preset", "stack", "--hide-links", "none")[0], ExitCode.OK)
        shown = self.read(".ui.json")
        self.assertNotIn(KEY, shown["extra"])
        del hidden["extra"][KEY]
        self.assertEqual(json_bytes(hidden), json_bytes(shown))

    def test_the_flag_asks_an_x_preset_for_nothing_it_can_hide(self):
        graph = self.graph(TXT2IMG)
        self.assertEqual(run("compile", graph, "-o", self.out, "--preset", "bento", "--hide-links", "resources")[0], ExitCode.OK)
        self.assertNotIn(KEY, self.read(".ui.json")["extra"])

    def test_an_unknown_value_is_a_usage_error(self):
        code, _, err = run("compile", self.graph(TXT2IMG), "-o", self.out, "--hide-links", "all")
        self.assertEqual(code, ExitCode.USAGE)
        self.assertIn("--hide-links", err)


if __name__ == "__main__":
    unittest.main()
