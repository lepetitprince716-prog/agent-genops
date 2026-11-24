"""``extra.cwc``: compile writes the author's title and notes into the canvas, and the one reader
takes what is well formed and drops the rest."""

from __future__ import annotations

import copy
import unittest

from tests import support  # noqa: F401  (puts src/ on sys.path)
from tests.graphs import txt2img
from tests.test_render_skin import noted

from cwc.canvas.model import Canvas
from cwc.nodedefs.registry import NodeDefs
from cwc.pipeline import compile_document
from cwc.render.notes import DiagramNotes, read_notes, write_notes

DEFS = NodeDefs.load()


def with_block(block) -> Canvas:
    return Canvas({"nodes": [], "links": [], "groups": [], "extra": {"cwc": block}, "version": 0.4})


class WriteTest(unittest.TestCase):
    def test_compile_writes_title_notes_and_group_notes_keyed_as_the_canvas_names_them(self):
        compiled = compile_document(noted(txt2img()), DEFS)
        block = compiled.canvas.extra["cwc"]
        ids = dict(compiled.authoring.ids)
        [finish] = [g.title for g in compiled.canvas.groups if g.title.endswith("Finish")]
        self.assertEqual(
            block,
            {
                "format": 1,
                "title": "Text to image",
                "notes": dict(sorted({ids["ckpt"]: "weights from disk", ids["sampler"]: "the one step that runs long"}.items(), key=lambda kv: int(kv[0]))),
                "groups": {finish: {"note": "decode and save"}},
            },
        )
        self.assertEqual(read_notes(compiled.canvas).groups, {finish: "decode and save"})

    def test_a_document_with_nothing_to_say_gets_no_block(self):
        self.assertNotIn("cwc", compile_document(txt2img(), DEFS).canvas.extra)
        doc = copy.deepcopy(txt2img())
        doc["_workflow"] = {"format": 1, "groups": {"finish": {"title": "Finish"}}}
        doc["decode"]["_meta"] = {"ui_group": "finish"}
        self.assertNotIn("cwc", compile_document(doc, DEFS).canvas.extra)

    def test_the_keys_now_have_an_effect_and_get_no_e8(self):
        report = compile_document(noted(txt2img()), DEFS).report
        self.assertEqual([f for f in report.findings if f.code.value == "E8"], [])

    def test_an_empty_note_set_removes_an_old_block(self):
        canvas = with_block({"format": 1, "title": "old", "notes": {}, "groups": {}})
        write_notes(canvas, DiagramNotes())
        self.assertNotIn("cwc", canvas.extra)

    def test_written_block_reads_back(self):
        canvas = Canvas({"nodes": [], "links": [], "groups": [], "version": 0.4})
        notes = DiagramNotes(title="T", notes={"3": "n"}, groups={"01 Models": "m"})
        write_notes(canvas, notes)
        self.assertEqual(read_notes(canvas), notes)


class ReadTest(unittest.TestCase):
    def test_absent_or_of_another_format_reads_empty(self):
        self.assertEqual(read_notes(Canvas({"nodes": [], "links": [], "groups": []})), DiagramNotes())
        for block in (None, [], "x", {"format": 2, "title": "t"}, {"format": True, "title": "t"}, {"title": "t"}):
            with self.subTest(block=block):
                self.assertEqual(read_notes(with_block(block)), DiagramNotes())

    def test_malformed_entries_are_dropped_and_the_rest_kept(self):
        block = {
            "format": 1,
            "title": 7,
            "notes": {"1": "keep", "2": 3, "3": "", "4": None},
            "groups": {"A": {"note": "keep"}, "B": "flat", "C": {"note": 1}, "D": {}},
        }
        self.assertEqual(read_notes(with_block(block)), DiagramNotes(title=None, notes={"1": "keep"}, groups={"A": "keep"}))

    def test_tables_of_the_wrong_kind_read_empty(self):
        block = {"format": 1, "title": "t", "notes": ["a"], "groups": "g"}
        self.assertEqual(read_notes(with_block(block)), DiagramNotes(title="t"))


if __name__ == "__main__":
    unittest.main()
