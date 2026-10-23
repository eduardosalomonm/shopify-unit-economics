"""Tests for the optional costs between product margin and profit.

Allocations are where a plausible-looking number goes quietly wrong: a cost counted
once per line instead of once per order, or a monthly budget that vanishes because
nothing sold that month. These tests pin those rules down.

Run:  python3 -m unittest discover -s tests -v
"""

import copy
import os
import sqlite3
import sys
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import checks  # noqa: E402
import publish  # noqa: E402
from config import ConfigError, validate_costs, variable_costs  # noqa: E402
from excel_input import (ExcelInputError, build_inputs, read_sheet, sheet_paths,  # noqa: E402
                         shared_strings, variable_cost_inputs)
from transform import build_rows, repartir  # noqa: E402

WORKBOOK = os.path.join(ROOT, "assets", "unit-economics-input.xlsx")

COSTS = {
    "iva": {"tipo_pct": 21.0},
    "productos": {
        "A": {"nombre": "A", "coste_unitario": 10.0, "precio_web": 60.5},
        "B": {"nombre": "B", "coste_unitario": 2.0, "precio_web": 12.1},
    },
    "objetivo": {"unidades": 10, "desde": "2026-01-01", "hasta": "2026-12-31"},
}
MODEL = {"logistica_por_pedido": 5.0, "comision_pago_pct": 2.0, "comision_pago_fija": 0.30,
         "publicidad": {"2026-02": 30.0}}


def money(amount):
    return {"shopMoney": {"amount": "%.2f" % amount}}


def order(name, date, lines, shipping=0.0):
    return {
        "name": name, "createdAt": "%sT10:00:00Z" % date, "cancelledAt": None,
        "test": False, "displayFinancialStatus": "PAID", "taxesIncluded": True,
        "discountCodes": [], "currentTotalDiscountsSet": money(0.0),
        "currentTotalTaxSet": money(0.0), "totalShippingPriceSet": money(shipping),
        "lineItems": {"edges": [{"node": {
            "title": sku, "sku": sku, "quantity": qty, "taxable": True,
            "originalUnitPriceSet": money(price), "discountAllocations": [],
        }} for sku, qty, price in lines]},
    }


def with_model(model=MODEL):
    costs = copy.deepcopy(COSTS)
    costs["costes_variables"] = copy.deepcopy(model)
    return costs


class TestAllocation(unittest.TestCase):
    def test_parts_add_up_to_the_total_to_the_cent(self):
        parts = repartir(10.0, [1, 1, 1])
        self.assertAlmostEqual(sum(parts), 10.0, places=2)
        self.assertEqual(sorted(parts), [3.33, 3.33, 3.34])

    def test_parts_follow_their_weights(self):
        self.assertEqual(repartir(5.0, [80.0, 20.0]), [4.0, 1.0])

    def test_zero_weights_split_evenly_instead_of_dropping_the_cost(self):
        self.assertEqual(repartir(1.0, [0.0, 0.0]), [0.5, 0.5])


class TestVariableCosts(unittest.TestCase):
    def test_without_a_model_product_margin_is_unchanged_and_nothing_is_invented(self):
        rows = build_rows({"pedidos": [order("#1", "2026-02-01", [("A", 1, 60.5)], 4.84)]}, COSTS)
        self.assertAlmostEqual(rows[0]["margen_contribucion"], 40.0, places=2)
        for field in ("ingreso_envio", "coste_logistica", "comision_pago",
                      "coste_publicidad", "resultado_variable"):
            self.assertIsNone(rows[0][field], field)

    def test_per_order_costs_are_charged_once_and_split_by_line_value(self):
        snapshot = {"pedidos": [order("#1", "2026-02-01", [("A", 1, 60.5), ("B", 1, 12.1)], 4.84)]}
        rows = {row["sku"]: row for row in build_rows(snapshot, with_model({
            "logistica_por_pedido": 5.0, "comision_pago_pct": 2.0, "comision_pago_fija": 0.30}))}
        # Shipping 4.84 incl VAT is 4.00 ex VAT; A carries 60.5 / 72.6 of each order cost.
        self.assertAlmostEqual(rows["A"]["ingreso_envio"] + rows["B"]["ingreso_envio"], 4.0, places=2)
        self.assertAlmostEqual(rows["A"]["coste_logistica"] + rows["B"]["coste_logistica"], 5.0, places=2)
        self.assertAlmostEqual(rows["A"]["coste_logistica"], 4.17, places=2)
        # The fee is charged on everything paid, shipping and VAT included: 2% of 77.44 + 0.30.
        fees = rows["A"]["comision_pago"] + rows["B"]["comision_pago"]
        self.assertAlmostEqual(fees, round(0.02 * 77.44 + 0.30, 2), places=2)

    def test_result_after_variable_costs_adds_and_deducts_each_component(self):
        rows = build_rows({"pedidos": [order("#1", "2026-02-01", [("A", 1, 60.5)], 4.84)]},
                          with_model())
        row = rows[0]
        expected = (row["margen_contribucion"] + row["ingreso_envio"] - row["coste_logistica"]
                    - row["comision_pago"] - row["coste_publicidad"])
        self.assertAlmostEqual(row["resultado_variable"], expected, places=2)
        self.assertAlmostEqual(row["coste_publicidad"], 30.0, places=2)

    def test_advertising_follows_net_revenue_within_its_month_only(self):
        snapshot = {"pedidos": [order("#1", "2026-02-01", [("A", 3, 60.5)]),
                                order("#2", "2026-02-20", [("B", 5, 12.1)]),
                                order("#3", "2026-03-02", [("A", 1, 60.5)])]}
        rows = {row["pedido"]: row for row in build_rows(snapshot, with_model())}
        self.assertAlmostEqual(rows["#1"]["coste_publicidad"], 22.5, places=2)
        self.assertAlmostEqual(rows["#2"]["coste_publicidad"], 7.5, places=2)
        self.assertEqual(rows["#3"]["coste_publicidad"], 0.0)

    def test_an_order_split_across_excel_rows_pays_its_order_costs_once(self):
        # The Excel workflow writes one order object per line, sharing the order name.
        snapshot = {"pedidos": [order("#1", "2026-02-01", [("A", 1, 60.5)], 4.84),
                                order("#1", "2026-02-01", [("B", 1, 12.1)])]}
        rows = build_rows(snapshot, with_model({"logistica_por_pedido": 5.0}))
        self.assertAlmostEqual(sum(row["coste_logistica"] for row in rows), 5.0, places=2)
        self.assertAlmostEqual(sum(row["ingreso_envio"] for row in rows), 4.0, places=2)

    def test_unknown_sku_has_no_result_rather_than_a_guessed_one(self):
        rows = build_rows({"pedidos": [order("#1", "2026-02-01", [("Z", 1, 10.0)])]}, with_model())
        self.assertIsNone(rows[0]["resultado_variable"])


class TestValidation(unittest.TestCase):
    def test_a_valid_model_is_accepted_and_normalised(self):
        validate_costs(with_model())
        self.assertEqual(variable_costs(with_model())["publicidad"], {"2026-02": 30.0})
        self.assertIsNone(variable_costs(COSTS))

    def test_impossible_values_fail_before_any_calculation(self):
        for model in ({"logistica_por_pedido": -1}, {"comision_pago_pct": 100},
                      {"publicidad": {"Feb 2026": 10}}, {"publicidad": {"2026-02": -5}},
                      {"comision_pago_fija": "free"}):
            with self.subTest(model=model), self.assertRaises(ConfigError):
                validate_costs(with_model(model))


class TestWorkbook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.costs, cls.snapshot = build_inputs(WORKBOOK)

    def test_demo_workbook_declares_variable_costs(self):
        model = variable_costs(self.costs)
        self.assertIsNotNone(model)
        self.assertGreater(model["logistica_por_pedido"], 0)
        self.assertTrue(model["publicidad"])

    def test_shipping_is_recorded_once_per_order(self):
        charged = {}
        for item in self.snapshot["pedidos"]:
            amount = float(item["totalShippingPriceSet"]["shopMoney"]["amount"])
            charged[item["name"]] = charged.get(item["name"], 0) + amount
        self.assertEqual(len(set(charged.values())), 1)
        self.assertGreater(next(iter(charged.values())), 0)

    def test_excel_dashboard_sheet_follows_the_settings_costs(self):
        with zipfile.ZipFile(WORKBOOK) as archive:
            path = sheet_paths(archive)["Dashboard"]
            xml = archive.read(path).decode("utf-8")
            rows = read_sheet(archive, path, shared_strings(archive))
        self.assertEqual(rows[14][3], "After variable costs")
        self.assertIn("<f>E10+E11-E12-E13-E14</f>", xml)
        for setting in ("'Settings'!B12", "'Settings'!B13", "'Settings'!B14", "'Settings'!B15"):
            self.assertIn(setting, xml)
        # The cached result shown before Excel recalculates matches its own parts.
        parts = [float(rows[index][4]) for index in range(9, 15)]
        self.assertAlmostEqual(parts[0] + parts[1] - parts[2] - parts[3] - parts[4], parts[5], places=2)

    def test_blank_settings_keep_the_product_margin_dashboard(self):
        self.assertEqual(variable_cost_inputs({}, [["Setting", "Value"]]), (None, 0.0))

    def test_settings_errors_name_the_field_to_fix(self):
        with self.assertRaises(ExcelInputError) as error:
            variable_cost_inputs({"Payment fee (%)": "120"}, [])
        self.assertIn("Payment fee (%)", str(error.exception))
        rows = [["Month (YYYY-MM)", "Advertising spend ex VAT"], ["March", "100"]]
        with self.assertRaises(ExcelInputError) as error:
            variable_cost_inputs({}, rows)
        self.assertIn("YYYY-MM", str(error.exception))


class TestReporting(unittest.TestCase):
    def test_advertising_without_sales_is_reported_not_dropped_silently(self):
        costs = with_model(dict(MODEL, publicidad={"2026-02": 30.0, "2026-05": 80.0}))
        rows = build_rows({"pedidos": [order("#1", "2026-02-01", [("A", 1, 60.5)])]}, costs)
        conn = sqlite3.connect(":memory:")
        columns = list(rows[0])
        conn.execute("CREATE TABLE lineas (%s)" % ", ".join(columns))
        conn.executemany("INSERT INTO lineas VALUES (%s)" % ",".join("?" * len(columns)),
                         [tuple(row[column] for column in columns) for row in rows])
        result = checks.run_all(conn, costs)
        warnings = [message for control, message in result.avisos
                    if control == "Variable cost allocation"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("2026-05", warnings[0])
        self.assertFalse(result.errores)

    def test_breakeven_discount_counts_cost_vat_and_payment_fee(self):
        # 60.50 incl VAT is 50.00 ex VAT; a 10.00 unit cost leaves 80% before fees.
        self.assertAlmostEqual(publish.breakeven_discount(COSTS, "A"), 80.0, places=1)
        rate = publish.breakeven_discount(COSTS, "A", {"comision_pago_pct": 2.0})
        self.assertAlmostEqual(rate, 100 * (1 - 10.0 / (60.5 * (1 / 1.21 - 0.02))), places=1)
        below_cost = copy.deepcopy(COSTS)
        below_cost["productos"]["A"]["coste_unitario"] = 70.0
        self.assertIsNone(publish.breakeven_discount(below_cost, "A"))

    def test_scope_note_never_calls_the_result_net_profit(self):
        self.assertIn("declare them as variable costs", publish.scope_note(None))
        self.assertIn("overhead are still excluded", publish.scope_note(variable_costs(with_model())))

    def test_dashboard_hides_the_variable_view_when_it_is_not_declared(self):
        with open(os.path.join(ROOT, "src", "panel_template.html"), encoding="utf-8") as handle:
            template = handle.read()
        self.assertIn("hasVariable={{VARIABLE_COSTS}}", template)
        self.assertIn(".no-variable .var-col", template)
        self.assertIn("no-var-only", template)


if __name__ == "__main__":
    unittest.main()
