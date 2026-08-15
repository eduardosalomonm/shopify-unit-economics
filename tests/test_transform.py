"""Tests for the two calculations that are easy to get silently wrong.

Both of these were wrong in the first working version of this pipeline, and neither
failure is visible by eye: the numbers still look plausible, just inflated. That is
exactly the kind of bug a test earns its keep on.

Run:  python3 -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from transform import build_rows, catalogo, precio_catalogo  # noqa: E402


COSTS = {
    "iva": {"tipo_pct": 21.0},
    "productos": {
        "A": {"nombre": "A", "coste_unitario": 10.0, "precio_web": 40.0,
              "precios": [{"desde": "2025-01-01", "precio": 50.0},
                          {"desde": "2026-01-01", "precio": 40.0}]},
        "B": {"nombre": "B", "coste_unitario": 2.0, "precio_web": 10.0},
    },
    "bundles": {
        "duo": {"sku": "D", "nombre": "Duo", "precio_web": 45.0, "confirmado": True,
                "contiene": [{"sku": "A", "uds": 1}, {"sku": "B", "uds": 1}]},
    },
}


def money(amount):
    return {"shopMoney": {"amount": "%.2f" % amount}}


def order(lines, descuento=0.0, taxes_included=True):
    return {"pedidos": [{
        "name": "#1", "createdAt": "2026-02-01T10:00:00Z", "cancelledAt": None,
        "test": False, "displayFinancialStatus": "PAID", "taxesIncluded": taxes_included,
        "discountCodes": [], "currentTotalDiscountsSet": money(descuento),
        "currentTotalTaxSet": money(0.0), "totalShippingPriceSet": money(0.0),
        "lineItems": {"edges": [{"node": {
            "title": sku, "sku": sku, "quantity": qty, "taxable": True,
            "originalUnitPriceSet": money(precio),
            "discountedUnitPriceSet": money(precio),
            "totalDiscountSet": money(0.0),   # always zero in the real API
        }} for sku, qty, precio in lines]}},
    ]}


class TestOrderLevelDiscount(unittest.TestCase):
    """Shopify reports discounts on the order, never on the line item."""

    def test_discount_is_split_across_lines_by_value(self):
        rows = build_rows(order([("A", 1, 40.0), ("B", 1, 10.0)], descuento=5.0), COSTS)
        # 50.00 gross, 5.00 off -> A carries 80% of it, B carries 20%.
        by_sku = {r["sku"]: r for r in rows}
        self.assertAlmostEqual(by_sku["A"]["descuento_linea"], 4.0, places=2)
        self.assertAlmostEqual(by_sku["B"]["descuento_linea"], 1.0, places=2)

    def test_ignoring_the_order_discount_would_overstate_revenue(self):
        con = build_rows(order([("A", 1, 40.0)], descuento=4.0), COSTS)[0]
        sin = build_rows(order([("A", 1, 40.0)], descuento=0.0), COSTS)[0]
        self.assertLess(con["ingreso_neto"], sin["ingreso_neto"])

    def test_quantity_is_respected_in_the_split(self):
        rows = build_rows(order([("A", 2, 40.0), ("B", 1, 10.0)], descuento=9.0), COSTS)
        by_sku = {r["sku"]: r for r in rows}
        # 80.00 vs 10.00 -> 8/9 and 1/9 of the discount.
        self.assertAlmostEqual(by_sku["A"]["descuento_linea"], 8.0, places=2)
        self.assertAlmostEqual(by_sku["B"]["descuento_linea"], 1.0, places=2)

    def test_real_line_allocations_override_a_proportional_legacy_fallback(self):
        payload = order([("A", 1, 40.0), ("B", 1, 10.0)], descuento=5.0)
        # Shopify can allocate a discount unevenly; do not reverse-engineer it.
        lines = payload["pedidos"][0]["lineItems"]["edges"]
        lines[0]["node"]["discountAllocations"] = [{"allocatedAmountSet": money(5.0)}]
        lines[1]["node"]["discountAllocations"] = []
        by_sku = {r["sku"]: r for r in build_rows(payload, COSTS)}
        self.assertAlmostEqual(by_sku["A"]["descuento_linea"], 5.0, places=2)
        self.assertAlmostEqual(by_sku["B"]["descuento_linea"], 0.0, places=2)


class TestVatHandling(unittest.TestCase):
    """Storefront prices include VAT; unit costs do not. Margin must be ex VAT."""

    def test_taxable_line_is_converted_to_ex_vat(self):
        row = build_rows(order([("A", 1, 121.0)]), COSTS)[0]
        self.assertAlmostEqual(row["ingreso_neto"], 100.0, places=2)
        self.assertAlmostEqual(row["iva_implicito"], 21.0, places=2)

    def test_margin_is_computed_on_the_ex_vat_figure(self):
        row = build_rows(order([("A", 1, 121.0)]), COSTS)[0]
        self.assertAlmostEqual(row["margen_contribucion"], 90.0, places=2)  # 100 - 10 cost

    def test_prices_excluding_vat_are_left_alone(self):
        row = build_rows(order([("A", 1, 100.0)], taxes_included=False), COSTS)[0]
        self.assertAlmostEqual(row["ingreso_neto"], 100.0, places=2)


class TestPriceHistory(unittest.TestCase):
    """A single current price produces false alerts on historical orders."""

    def test_order_is_matched_against_the_price_in_force_that_day(self):
        self.assertEqual(precio_catalogo(COSTS, "A", "2025-06-01"), 50.0)
        self.assertEqual(precio_catalogo(COSTS, "A", "2026-06-01"), 40.0)

    def test_product_without_history_falls_back_to_current_price(self):
        self.assertEqual(precio_catalogo(COSTS, "B", "2025-06-01"), 10.0)

    def test_unknown_sku_has_no_catalogue_price(self):
        self.assertIsNone(precio_catalogo(COSTS, "NOPE", "2026-01-01"))


class TestBundleCosting(unittest.TestCase):
    """A bundle SKU must resolve to the sum of its parts, not to nothing."""

    def test_bundle_cost_is_the_sum_of_its_components(self):
        self.assertAlmostEqual(catalogo(COSTS)["D"]["coste"], 12.0, places=2)

    def test_bundle_sale_produces_a_margin_instead_of_a_gap(self):
        row = build_rows(order([("D", 1, 45.0)]), COSTS)[0]
        self.assertIsNotNone(row["margen_contribucion"])

    def test_unknown_sku_gets_no_invented_cost(self):
        row = build_rows(order([("ZZZ", 1, 20.0)]), COSTS)[0]
        self.assertIsNone(row["coste_total"])
        self.assertIsNone(row["margen_contribucion"])


if __name__ == "__main__":
    unittest.main()
