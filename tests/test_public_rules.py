"""The public privacy rules keep catching what they are for and leave ordinary code alone.

Sample strings are assembled at run time so this file does not trip the rules it tests.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "tools" / "privacy_rules.json"
SCANNER = ROOT / "tools" / "privacy_scan.py"


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

    def test_a_hostname_closed_by_an_underscore_is_still_reported(self) -> None:
        # Markdown italics put an underscore right after the name; only an underscore that goes
        # on into a letter or digit makes an identifier such as local_addr.
        for host, suffix in (("nas", "local"), ("box", "lan"), ("db", "internal")):
            name = f"{host}.{suffix}"
            for text in (f"_ssh {name}_ first", f"see {name}_.", f"{name}_", f"{name}_, then",
                         f"{name}__"):
                with self.subTest(text=text):
                    self.assertTrue(self.pattern.search(text))

    def test_the_command_line_scanner_reports_an_italic_hostname_and_not_an_identifier(self) -> None:
        dot = "."
        cases = (
            (f"Connect with _ssh nas{dot}local_ first.\n", 1),
            (f"let addr = listener{dot}local_addr().unwrap();\n", 0),
        )
        for text, expected in cases:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "note.md"
                target.write_text(text)
                done = subprocess.run(
                    [sys.executable, "-I", "-B", str(SCANNER), "--no-private", str(target)],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(done.returncode, expected, done.stdout + done.stderr)
                if expected:
                    self.assertIn("lan_hostname", done.stdout)


if __name__ == "__main__":
    unittest.main()
