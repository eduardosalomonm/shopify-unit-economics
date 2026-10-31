"""Tests for the dependency-free Excel input path.

These assert the *shape and coherence* of the workbook rather than exact totals.
Pinning a row count or a revenue figure makes the suite fail every time the demo
data is regenerated, which trains people to update the number instead of reading
the failure.
"""

import os
import sys
import unittest
import zipfile
from xml.etree import ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from excel_input import ExcelInputError, build_inputs, positive  # noqa: E402

WORKBOOK = os.path.join(ROOT, "assets", "unit-economics-input.xlsx")


class TestStarterWorkbook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.costs, cls.snapshot = build_inputs(WORKBOOK)

    def test_settings_populate_the_cost_model(self):
        self.assertEqual(self.costs["meta"]["marca"], "Luma Vale")
        self.assertEqual(self.costs["meta"]["moneda"], "EUR")
        self.assertEqual(self.costs["iva"]["tipo_pct"], 21)

    def test_products_carry_a_cost_and_a_price(self):
        for sku, product in self.costs["productos"].items():
            self.assertGreater(product["coste_unitario"], 0, sku)
            self.assertGreater(product["precio_web"], product["coste_unitario"], sku)

    def test_stock_on_hand_is_optional_but_read_when_present(self):
        stocked = [sku for sku, product in self.costs["productos"].items() if "stock" in product]
        self.assertTrue(stocked, "the demo workbook should exercise the inventory path")
        for sku in stocked:
            product = self.costs["productos"][sku]
            self.assertLessEqual(product["stock"], product["tirada"],
                                 "%s cannot hold more stock than was ever produced" % sku)

    def test_bundle_contents_reference_real_products(self):
        for sku, bundle in self.costs["bundles"].items():
            self.assertTrue(bundle["contiene"], sku)
            for component in bundle["contiene"]:
                self.assertIn(component["sku"], self.costs["productos"])

    def test_orders_look_like_a_shop_rather_than_a_fixture(self):
        orders = self.snapshot["pedidos"]
        self.assertGreater(len(orders), 100)
        names = {order["name"] for order in orders}
        units = sum(edge["node"]["quantity"]
                    for order in orders for edge in order["lineItems"]["edges"])
        # Real baskets are not one unit each: that would make AOV, basket size and
        # bundle attach rate meaningless.
        self.assertGreater(units / len(names), 1.2)

    def test_demo_sales_match_the_documented_public_total(self):
        gross = sum(
            float(item["originalUnitPriceSet"]["shopMoney"]["amount"]) * item["quantity"]
            - sum(float(item["allocatedAmountSet"]["shopMoney"]["amount"])
                  for item in item["discountAllocations"])
            for order in self.snapshot["pedidos"]
            for edge in order["lineItems"]["edges"]
            for item in [edge["node"]]
        )
        self.assertEqual(round(gross, 2), 83755.43)

    def test_every_ordered_sku_exists_in_the_cost_model(self):
        known = set(self.costs["productos"]) | {b["sku"] for b in self.costs["bundles"].values()}
        for order in self.snapshot["pedidos"]:
            for edge in order["lineItems"]["edges"]:
                self.assertIn(edge["node"]["sku"], known)

    def test_discounts_are_present_and_plausible(self):
        listed = discount = 0.0
        for order in self.snapshot["pedidos"]:
            for edge in order["lineItems"]["edges"]:
                item = edge["node"]
                listed += float(item["originalUnitPriceSet"]["shopMoney"]["amount"]) * item["quantity"]
                discount += sum(float(allocation["allocatedAmountSet"]["shopMoney"]["amount"])
                                for allocation in item["discountAllocations"])
        self.assertGreater(discount, 0, "a store with no discounts hides the discount KPI")
        self.assertLess(100 * discount / listed, 30, "discount rate is implausibly high")

    def test_discount_codes_have_declared_rules(self):
        rules = self.costs["descuentos"]
        self.assertEqual(set(rules), {"WELCOME10", "SUMMER15", "VIP20"})
        for code, rule in rules.items():
            self.assertGreater(rule["porcentaje"], 0, code)
            self.assertTrue(rule["activo"], code)

    def test_scenario_order_prices_follow_the_current_catalogue(self):
        """The public workbook starts in Scenario mode, so blue Orders prices
        are recalculated from the yellow Catalogue input rather than dates."""
        self.assertEqual(self.costs["meta"]["pricing_model"], "scenario")
        for order in self.snapshot["pedidos"]:
            for edge in order["lineItems"]["edges"]:
                item = edge["node"]
                product = self.costs["productos"].get(item["sku"])
                if not product:
                    continue
                self.assertEqual(
                    float(item["originalUnitPriceSet"]["shopMoney"]["amount"]),
                    product["precio_web"], item["sku"])

    def test_scenario_discounts_reference_the_visible_promotion_rules(self):
        """Protect the Scenario model from pointing at blank rows after the
        Pricing & promotions sheet is reorganised."""
        namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        with zipfile.ZipFile(WORKBOOK) as archive:
            orders = ET.fromstring(archive.read("xl/worksheets/sheet7.xml"))
        formulas = {
            cell.attrib["r"]: cell.findtext("x:f", namespaces=namespace)
            for cell in orders.findall(".//x:c", namespace)
        }
        self.assertIn("'Pricing & promotions'!$A$6:$A$8", formulas["H3"])
        self.assertIn("'Pricing & promotions'!$B$6:$B$8", formulas["H3"])

    def test_dashboard_is_the_first_sheet_and_links_to_the_online_version(self):
        """Keep the accessible Excel companion and polished public demo connected."""
        namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        with zipfile.ZipFile(WORKBOOK) as archive:
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            dashboard = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        sheets = workbook.findall(".//x:sheets/x:sheet", namespace)
        self.assertEqual(sheets[0].attrib["name"], "Dashboard")
        values = ["".join(cell.itertext()) for cell in dashboard.findall(".//x:c", namespace)]
        self.assertIn("Online dashboard", values)
        self.assertIn("https://marginmap.eilvi.com/", values)

    def test_non_positive_prices_explain_how_to_recover(self):
        with self.assertRaisesRegex(ExcelInputError, "Pricing planner"):
            positive(-1, "Catalogue", 3, "Web price incl VAT")


if __name__ == "__main__":
    unittest.main()
