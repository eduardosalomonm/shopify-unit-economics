"""Regression checks for the portable static dashboard shell."""

import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestDashboardTemplate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "src", "panel_template.html"), encoding="utf-8") as handle:
            cls.template = handle.read()

    def test_product_name_preserves_store_identity(self):
        self.assertIn('<title>Margin Map · {{BRAND}} · Performance dashboard</title>', self.template)
        self.assertIn('MARGIN MAP<small>{{BRAND_UPPER}} · v{{APP_VERSION}}</small>', self.template)

    def test_public_notice_and_scope_are_not_sidebar_only(self):
        footer = self.template.split("<footer>", 1)[1].split("</footer>", 1)[0]
        self.assertIn("{{SIDEBAR_NOTE}}", footer)
        self.assertIn("not net profit", footer)
        self.assertIn("refunds require separate reconciliation", footer)
        self.assertIn("Margin Map v{{APP_VERSION}}", footer)
        self.assertIn("footer{font-size:13px;line-height:1.5}", self.template)

    def test_uses_portable_last_date_selection(self):
        self.assertIn("dates[dates.length-1]", self.template)
        self.assertNotIn(".at(-1)", self.template)

    def test_sankey_has_a_dedicated_accessible_target(self):
        self.assertIn('id="sankey"', self.template)
        self.assertIn("Revenue flow from list price to contribution margin", self.template)

    def test_navigation_remains_available_on_small_screens(self):
        self.assertIn("@media(max-width:1020px)", self.template)
        self.assertIn("display:flex!important", self.template)
        self.assertIn("overflow-x:auto", self.template)

    def test_tabs_expose_keyboard_and_assistive_semantics(self):
        self.assertIn('role="tablist"', self.template)
        self.assertIn('role="tab"', self.template)
        self.assertIn("aria-selected", self.template)
        self.assertIn("ArrowRight", self.template)

    def test_period_labels_are_data_driven_and_truthful(self):
        self.assertIn("Complete imported period", self.template)
        self.assertIn("completePeriodLabel", self.template)
        self.assertNotIn("All time · 12 months", self.template)
        self.assertNotIn("Last 7 trading days", self.template)

    def test_global_benchmark_does_not_mutate_with_filters(self):
        self.assertIn("filters do not change this benchmark", self.template)
        self.assertNotIn("by('target-progress'", self.template)
        self.assertNotIn('data-metric="target-bar"', self.template)

    def test_store_text_is_escaped_before_dynamic_html(self):
        self.assertIn("esc(product.name)", self.template)
        self.assertIn("esc(product.sku)", self.template)
        self.assertIn("esc(promo.code)", self.template)
        self.assertIn("csvCell(row.name)", self.template)

    def test_empty_chart_has_an_explicit_state(self):
        self.assertIn("No sales in this view", self.template)


if __name__ == "__main__":
    unittest.main()
