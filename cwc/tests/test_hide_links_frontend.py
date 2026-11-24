"""A real frontend loads the hidden links the ``stack`` preset writes and queues the same prompt.

Needs the oracle (``CWC_ORACLE_URL``, ``CWC_ORACLE_PYTHON``, see ``tests/oracle_support.py``);
without them every test here is skipped. Each stack canvas is loaded twice, with
``extra.linkPresentation`` and with the key removed, and the two are compared after the
frontend's own ``graphToPrompt`` and ``serialize()``.
"""

import json
import unittest

from tests import support
from tests.graphs import DEFS
from tests.layout_cases import OTHERS, SIMPLE, with_lora
from tests.layout_generator import random_graph
from tests import oracle_support

from cwc.nodedefs.registry import NodeDefs
from cwc.pipeline import compile_document
from cwc.route.presentation import KEY

STACK_FIXTURE = support.FIXTURES / "layout" / "stack_two_pass.json"
STACK_OBJECT_INFO = support.FIXTURES / "layout" / "stack_two_pass.object_info.json"


def graphs():
    out = {**SIMPLE, **OTHERS, "required_lora": lambda: with_lora(optional=False)}
    out.update({f"seed_{seed}": (lambda seed=seed: random_graph(seed)) for seed in (0, 3, 4, 11, 14)})
    return out


def canvases():
    """Name to the stack canvas written with hidden links, and the same canvas without the key."""
    written = {name: compile_document(build(), DEFS, preset="stack").canvas.to_json() for name, build in graphs().items()}
    defs = NodeDefs.load(object_info=json.loads(STACK_OBJECT_INFO.read_text()))
    written["stack_two_pass"] = compile_document(json.loads(STACK_FIXTURE.read_text()), defs, preset="stack").canvas.to_json()
    return written


def without_key(canvas):
    plain = json.loads(json.dumps(canvas))
    del plain["extra"][KEY]
    return plain


class HiddenLinksInARealFrontend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        oracle_support.require()
        cls.written = canvases()
        names = list(cls.written)
        results = oracle_support.roundtrip([cls.written[name] for name in names] + [without_key(cls.written[name]) for name in names])
        cls.hidden = dict(zip(names, results[: len(names)]))
        cls.plain = dict(zip(names, results[len(names) :]))

    def test_every_canvas_has_hidden_links(self):
        for name, canvas in self.written.items():
            with self.subTest(name):
                self.assertTrue(canvas["extra"][KEY])

    def test_the_frontend_loads_them_without_a_message(self):
        for name, result in self.hidden.items():
            with self.subTest(name):
                self.assertIsNone(result.load_error)
                self.assertIsNone(result.prompt_error)
                self.assertEqual(result.console, ())

    def test_the_key_survives_the_frontend(self):
        for name, result in self.hidden.items():
            with self.subTest(name):
                self.assertEqual(result.serialized["extra"][KEY], self.written[name]["extra"][KEY])
                self.assertNotIn(KEY, self.plain[name].serialized["extra"])

    def test_the_prompt_is_the_one_of_the_canvas_without_the_key(self):
        for name, result in self.hidden.items():
            with self.subTest(name):
                self.assertIsNotNone(result.prompt)
                self.assertEqual(json.dumps(result.prompt), json.dumps(self.plain[name].prompt))


if __name__ == "__main__":
    unittest.main()
