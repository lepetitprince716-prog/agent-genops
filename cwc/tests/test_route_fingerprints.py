"""The x-axis presets lay out and route the repository's layout cases exactly as before the y
axis (``stack``) was added: same node positions and sizes, same groups, same reroutes, byte for
byte.

``tests/fixtures/layout/route_fingerprints.json`` holds the SHA-256 of each routed canvas
(``Canvas.to_json`` dumped with sorted keys) by ``<preset>/<case>``, recorded from the commit
before the y axis. To record it again from another commit, put this file in that commit's
``tests/`` and run ``PYTHONPATH=src python3 -m tests.test_route_fingerprints <output path>``
there; a change that is meant to move a layout records it again and says why.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from dataclasses import replace
from typing import Any, Callable

from tests import support  # noqa: F401  (puts src/ on sys.path)
from tests.graphs import DEFS, compiled
from tests.layout_cases import OTHERS, SIMPLE, routed, two_stage, with_lora
from tests.layout_generator import random_graph

from cwc.annotate import annotate, apply_notes
from cwc.layout import layout
from cwc.layout.presets import get_preset
from cwc.route import route

FILE = support.FIXTURES / "layout" / "route_fingerprints.json"
PRESETS = ("bento", "swimlanes", "stepped", "cockpit-split", "tower-preview")
SEEDS = tuple(range(10))


def _nested(doc: dict[str, Any], preset: Any, nest: tuple[str, str]) -> Any:
    canvas, authoring = compiled(doc)
    plan = annotate(canvas, DEFS, authoring)
    apply_notes(canvas, plan)
    outer, inner = nest
    groups = [g for g in plan.groups if g.key != inner]
    at = next(i for i, g in enumerate(groups) if g.key == outer)
    groups.insert(at + 1, replace(plan.group(inner), parent=outer))
    route(canvas, layout(canvas, replace(plan, groups=tuple(groups)), preset, DEFS), DEFS)
    return canvas


def cases() -> dict[str, Callable[[Any], Any]]:
    out: dict[str, Callable[[Any], Any]] = {}
    builders = {**SIMPLE, **OTHERS, "required_lora": lambda: with_lora(optional=False)}
    builders.update({f"seed_{seed}": (lambda seed=seed: random_graph(seed)) for seed in SEEDS})
    for name, build in builders.items():
        out[name] = lambda preset, build=build: routed(build(), preset)[0]
    out["nested_two_stage"] = lambda preset: _nested(two_stage(), preset, ("stage:3", "sampling:9"))
    return out


def fingerprints() -> dict[str, str]:
    out = {}
    for preset in PRESETS:
        for name, run in cases().items():
            canvas = run(get_preset(preset))
            text = json.dumps(canvas.to_json(), sort_keys=True, separators=(",", ":"))
            out[f"{preset}/{name}"] = hashlib.sha256(text.encode()).hexdigest()
    return out


class RouteFingerprints(unittest.TestCase):
    def test_every_x_preset_lays_out_and_routes_as_recorded(self) -> None:
        recorded = json.loads(FILE.read_text())
        now = fingerprints()
        self.assertEqual(sorted(now), sorted(recorded))
        changed = sorted(key for key in now if now[key] != recorded[key])
        self.assertEqual(changed, [])


if __name__ == "__main__":
    with open(sys.argv[1], "w") as handle:
        json.dump(fingerprints(), handle, indent=1, sort_keys=True)
        handle.write("\n")
