"""What ``./check release`` prints and lists for a person to read.

Every repository is a temporary clone with a local bare remote and synthetic private rules.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_release_check import SyntheticRepo, combined  # noqa: E402
from test_release_trusted import clean_candidate, need_betterleaks, release  # noqa: E402

# CJK symbols and punctuation, and the full-width forms block.
FULL_WIDTH = re.compile("[　-〿＀-￯]")


class TerminalSummaryTests(unittest.TestCase):
    def test_the_summary_names_the_judges_in_ascii_punctuation(self) -> None:
        need_betterleaks(self)
        repo = SyntheticRepo(self, maintainer=True)
        trusted = repo.head()
        cand = clean_candidate(repo)
        res = release(repo, cand)
        self.assertEqual(res.returncode, 0, combined(res))
        self.assertIn(f" (trusted={trusted[:12]}, checker={trusted[:12]})", res.stdout)
        self.assertEqual(FULL_WIDTH.findall(res.stdout), [], res.stdout)


if __name__ == "__main__":
    unittest.main()
