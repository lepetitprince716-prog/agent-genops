"""``extra.cwc`` survives a real frontend: load, then ``serialize()``, gives the block back unchanged.

Runs only with an oracle (``tests/oracle_support.py``: ``CWC_ORACLE_URL``, ``CWC_ORACLE_PYTHON``).
"""

from __future__ import annotations

import unittest

from tests import oracle_support
from tests import support  # noqa: F401  (puts src/ on sys.path)
from tests.graphs import txt2img
from tests.test_render_skin import noted

from cwc.nodedefs.registry import NodeDefs
from cwc.pipeline import compile_document


class NotesRoundtripTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        oracle_support.require()
        cls.written = compile_document(noted(txt2img()), NodeDefs.load()).canvas.to_json()
        [cls.result] = oracle_support.roundtrip([cls.written])

    def test_the_canvas_loads(self):
        self.assertIsNone(self.result.load_error)
        self.assertEqual(self.result.console, ())

    def test_serialize_keeps_extra_cwc_as_written(self):
        self.assertIn("cwc", self.written["extra"])
        self.assertEqual(self.result.serialized["extra"]["cwc"], self.written["extra"]["cwc"])


if __name__ == "__main__":
    unittest.main()
