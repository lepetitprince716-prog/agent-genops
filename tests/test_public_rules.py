"""The public privacy rules keep catching what they are for and leave ordinary code alone.

Sample strings are assembled at run time so this file does not trip the rules it tests.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

RULES = Path(__file__).resolve().parents[1] / "tools" / "privacy_rules.json"


def rule(rule_id: str) -> re.Pattern[str]:
    data = json.loads(RULES.read_text(encoding="utf-8"))
    for entry in data["rules"]:
        if entry["id"] == rule_id:
            flags = re.IGNORECASE if "i" in entry.get("flags", "") else 0
            return re.compile(entry["pattern"], flags)
    raise AssertionError(f"rule {rule_id} is missing")


class LanHostname(unittest.TestCase):
    def setUp(self) -> None:
        self.pattern = rule("lan_hostname")

    def test_hostnames_are_still_reported(self) -> None:
        for host, suffix in (("box", "local"), ("nas", "lan"), ("printer", "internal"), ("a.b", "home.arpa")):
            name = f"{host}.{suffix}"
            for text in (f"ssh {name}", f"http://{name}/x", f"{name}.", f"({name})", f"{name}:8080"):
                with self.subTest(text=text):
                    self.assertTrue(self.pattern.search(text))

    def test_identifiers_with_an_underscore_are_not_hostnames(self) -> None:
        dot = "."
        for text in (
            f"let addr = listener{dot}local_addr().unwrap();",
            f"self{dot}local_path",
            f"cfg{dot}lan_mode = True",
            f"obj{dot}internal_state",
        ):
            with self.subTest(text=text):
                self.assertIsNone(self.pattern.search(text))


if __name__ == "__main__":
    unittest.main()
