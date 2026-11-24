"""What instantiate writes is what a real frontend writes (``frontend_serialize.json``).

The fixture is a frontend's ``serialize()`` of a graph built by hand (``tests/oracle_runner.py
capture``). ``pos`` is not compared (instantiate leaves it to layout), ``size`` has its own
tests, and ``order`` is the frontend's creation order there but the load-time order here
(``tests/test_instantiate_order.py``).
"""

import unittest

from tests import support  # noqa: F401  (puts src/ on sys.path)

from cwc.instantiate import instantiate
from tests.fixtures.instantiate import graphs

SKIPPED = {"pos", "size", "order"}
# A node the frontend creates with empty properties, and that it leaves empty on load;
# instantiate always writes the search name (a written value is kept on load).
EMPTY_PROPERTIES = {"SaveImage"}


class FrontendShapeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.canvas = instantiate(graphs.build(graphs.capture()))
        cls.fixture = graphs.serialize_fixture()
        cls.written = {node["id"]: node for node in cls.canvas.raw["nodes"]}
        cls.frontend = {node["id"]: node for node in cls.fixture["nodes"]}

    def test_the_same_nodes(self):
        self.assertEqual(list(self.written), list(self.frontend))
        self.assertEqual({k: n["type"] for k, n in self.written.items()}, {k: n["type"] for k, n in self.frontend.items()})

    def test_node_keys_and_their_order(self):
        for node_id, ours in self.written.items():
            with self.subTest(node=node_id, type=ours["type"]):
                self.assertEqual(list(ours), list(self.frontend[node_id]))

    def test_input_slots(self):
        for node_id, ours in self.written.items():
            theirs = self.frontend[node_id]
            with self.subTest(node=node_id, type=ours["type"]):
                self.assertEqual(ours["inputs"], theirs["inputs"])
                self.assertEqual([list(slot) for slot in ours["inputs"]], [list(slot) for slot in theirs["inputs"]])

    def test_output_slots(self):
        for node_id, ours in self.written.items():
            theirs = self.frontend[node_id]
            with self.subTest(node=node_id, type=ours["type"]):
                self.assertEqual(ours["outputs"], theirs["outputs"])
                self.assertEqual([list(slot) for slot in ours["outputs"]], [list(slot) for slot in theirs["outputs"]])

    def test_everything_else_but_position_size_and_order(self):
        for node_id, ours in self.written.items():
            theirs = self.frontend[node_id]
            for key in ours:
                if key in SKIPPED | {"inputs", "outputs"}:
                    continue
                with self.subTest(node=node_id, type=ours["type"], key=key):
                    if key == "properties" and ours["type"] in EMPTY_PROPERTIES:
                        self.assertEqual(theirs[key], {})
                        self.assertEqual(ours[key], {"Node name for S&R": ours["type"]})
                    else:
                        self.assertEqual(ours[key], theirs[key])

    def test_links_are_numbered_like_the_frontend_numbers_them(self):
        self.assertEqual(self.canvas.raw["links"], self.fixture["links"])
        self.assertEqual(self.canvas.raw["last_link_id"], self.fixture["last_link_id"])
        self.assertEqual(self.canvas.raw["last_node_id"], self.fixture["last_node_id"])

    def test_root_keys(self):
        for key in ("groups", "config", "version"):
            self.assertEqual(self.canvas.raw[key], self.fixture[key])
        self.assertEqual(
            [key for key in self.fixture if key in self.canvas.raw],
            [key for key in self.canvas.raw if key in self.fixture],
        )

    def test_unlinked_outputs_are_null_and_linked_ones_ascending(self):
        for node in self.canvas.raw["nodes"]:
            for slot in node["outputs"]:
                self.assertTrue(slot["links"] is None or slot["links"] == sorted(slot["links"]) and slot["links"])



# Node 3 of a frontend 1.59.1 serialize() (ComfyUI 0.45.0, classic renderer): two LoadImage
# nodes created and linked into a new ImageCompare by tests/oracle_runner.py capture.
FRONTEND_IMAGE_COMPARE = {
    "id": 3,
    "type": "ImageCompare",
    "flags": {},
    "mode": 0,
    "inputs": [
        {"localized_name": "image_a", "name": "image_a", "shape": 7, "type": "IMAGE", "link": 1},
        {"localized_name": "image_b", "name": "image_b", "shape": 7, "type": "IMAGE", "link": 2},
        {"localized_name": "compare_view", "name": "compare_view", "type": "IMAGECOMPARE", "widget": {"name": "compare_view"}, "link": None},
    ],
    "outputs": [],
    "properties": {"Node name for S&R": "ImageCompare"},
    "widgets_values": [],
    "widgets_values_named": {},
}


class UnpersistedWidgetShapeTest(unittest.TestCase):
    """ImageCompare's compare_view: a slot, and a widget serialize() leaves out of the tables."""

    def test_the_node_is_written_as_the_frontend_writes_it(self):
        canvas = instantiate(graphs.build(graphs.compare()))
        ours = next(node for node in canvas.raw["nodes"] if node["id"] == 3)
        self.assertEqual({k: v for k, v in ours.items() if k not in SKIPPED | {"title"}}, FRONTEND_IMAGE_COMPARE)
        self.assertEqual(list(ours)[-2:], ["widgets_values", "widgets_values_named"])


if __name__ == "__main__":
    unittest.main()
