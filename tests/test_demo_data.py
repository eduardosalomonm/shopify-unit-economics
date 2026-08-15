"""The public growth story must stay internally consistent."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from make_demo_data import MONTHLY_GROSS_SALES, build, gross_sales  # noqa: E402


class TestSuccessfulDemo(unittest.TestCase):
    def test_twelve_month_sales_total_is_exact(self):
        self.assertEqual(round(sum(value for _, value in MONTHLY_GROSS_SALES), 2), 83755.43)
        self.assertEqual(gross_sales(build()), 83755.43)

    def test_success_fixture_spans_twelve_months(self):
        months = {order["createdAt"][:7] for order in build()}
        self.assertEqual(len(months), 12)
        self.assertEqual(min(months), "2025-08")
        self.assertEqual(max(months), "2026-07")


if __name__ == "__main__":
    unittest.main()


class TestFixtureRealism(unittest.TestCase):
    """The JSON fixture shipped one line and one unit per order, which made average
    order value equal average selling price and basket size meaningless."""

    @classmethod
    def setUpClass(cls):
        import make_demo_data
        cls.orders = make_demo_data.build()

    def test_baskets_are_not_all_single_line(self):
        sizes = [len(order["lineItems"]["edges"]) for order in self.orders]
        self.assertGreater(sum(sizes) / len(sizes), 1.2)
        self.assertGreater(max(sizes), 1)

    def test_a_discount_code_never_lands_on_a_full_price_line(self):
        for order in self.orders:
            if not order["discountCodes"]:
                continue
            for edge in order["lineItems"]["edges"]:
                self.assertTrue(edge["node"]["discountAllocations"],
                                "%s carries a code but has an undiscounted line"
                                % order["name"])

    def test_grouping_preserves_the_exact_annual_total(self):
        import make_demo_data
        self.assertEqual(make_demo_data.gross_sales(self.orders), 83755.43)
