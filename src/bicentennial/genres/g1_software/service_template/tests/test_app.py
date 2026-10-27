"""Decision document structure checks."""

import re
import unittest

from service.config import ROOT


class AppTests(unittest.TestCase):
    def test_decisions(self):
        lines = (ROOT / "docs/decisions.md").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "# Decisions")
        for line in lines[1:]:
            self.assertIsNotNone(re.fullmatch(r"- .+: .+", line))
