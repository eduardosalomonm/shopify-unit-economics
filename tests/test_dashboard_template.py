"""Regression checks for the portable static dashboard shell."""

import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestDashboardTemplate(unittest.TestCase):
    def test_uses_portable_last_date_selection(self):
        with open(os.path.join(ROOT, "src", "panel_template.html"), encoding="utf-8") as handle:
            template = handle.read()
        self.assertIn("dates[dates.length-1]", template)
        self.assertNotIn(".at(-1)", template)

    def test_sankey_has_a_dedicated_accessible_target(self):
        with open(os.path.join(ROOT, "src", "panel_template.html"), encoding="utf-8") as handle:
            template = handle.read()
        self.assertIn('id="sankey"', template)
        self.assertIn("Revenue flow from list price to contribution margin", template)


if __name__ == "__main__":
    unittest.main()
