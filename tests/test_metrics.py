"""Tests for the commercial metrics the dashboard reports.

Revenue and margin are checked in test_transform.py. These cover the reads a
commercial team actually makes decisions on: what was discounted away, what a
basket looks like, whether stock lasts, and where the target lands.
"""

import datetime
import os
import sqlite3
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import publish  # noqa: E402

COSTS = {
    "meta": {"marca": "Test", "moneda": "EUR"},
    "productos": {
        "A": {"nombre": "A", "coste_unitario": 10.0, "precio_web": 50.0,
              "tirada": 1000, "stock": 200},
        "B": {"nombre": "B", "coste_unitario": 2.0, "precio_web": 10.0, "tirada": 500},
    },
    "bundles": {"duo": {"sku": "D", "nombre": "Duo", "precio_web": 55.0, "confirmado": True,
                        "contiene": [{"sku": "A", "uds": 1}, {"sku": "B", "uds": 1}]}},
    "objetivo": {"unidades": 1000, "desde": "2026-01-01", "hasta": "2026-12-31"},
}

COLUMNS = ("pedido", "fecha", "sku", "titulo", "unidades", "precio_bruto", "descuento_linea",
           "precio_catalogo", "coste_unitario", "ingreso_con_iva", "iva_implicito",
           "ingreso_neto", "coste_total", "margen_contribucion", "margen_pct", "taxable",
           "codigos_descuento", "estado_financiero", "iva_pedido_declarado", "envio_pedido")


def line(order, date, sku, units, gross, discount=0.0, cost=0.0, code=""):
    net = round((gross - discount) / 1.21, 2)
    return {"pedido": order, "fecha": date, "sku": sku, "titulo": sku, "unidades": units,
            "precio_bruto": gross / units, "descuento_linea": discount, "precio_catalogo": None,
            "coste_unitario": cost / units if units else 0, "ingreso_con_iva": gross - discount,
            "iva_implicito": round(gross - discount - net, 2), "ingreso_neto": net,
            "coste_total": cost, "margen_contribucion": round(net - cost, 2), "margen_pct": None,
            "taxable": 1, "codigos_descuento": code, "estado_financiero": "PAID",
            "iva_pedido_declarado": 0.0, "envio_pedido": 0.0}


def database(rows):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE lineas (%s)" % ", ".join(COLUMNS))
    conn.executemany("INSERT INTO lineas VALUES (%s)" % ",".join("?" * len(COLUMNS)),
                     [tuple(row[column] for column in COLUMNS) for row in rows])
    conn.commit()
    return conn


class TestTradingMetrics(unittest.TestCase):
    def setUp(self):
        self.conn = database([
            line("#1", "2026-02-01", "A", 1, 50.0, 5.0, 10.0, "WELCOME10"),
            line("#1", "2026-02-01", "B", 2, 20.0, 2.0, 4.0, "WELCOME10"),
            line("#2", "2026-02-02", "A", 1, 50.0, 0.0, 10.0),
        ])

    def test_discount_rate_is_measured_against_list_price(self):
        trading = publish.trading_metrics(self.conn)
        # 120 listed, 7 discounted
        self.assertAlmostEqual(trading["listed"], 120.0, places=2)
        self.assertAlmostEqual(trading["discount_rate"], 100 * 7 / 120, places=2)

    def test_basket_size_counts_orders_not_lines(self):
        trading = publish.trading_metrics(self.conn)
        self.assertEqual(trading["orders"], 2)
        self.assertEqual(trading["lines"], 3)
        self.assertAlmostEqual(trading["units_per_order"], 2.0, places=2)

    def test_discounted_share_counts_orders_with_a_code(self):
        trading = publish.trading_metrics(self.conn)
        self.assertAlmostEqual(trading["discounted_share"], 50.0, places=2)

    def test_margin_per_order_is_margin_over_orders(self):
        trading = publish.trading_metrics(self.conn)
        self.assertAlmostEqual(trading["margin_per_order"],
                               trading["margin"] / 2, places=2)


class TestInventoryMetrics(unittest.TestCase):
    def test_only_skus_with_declared_stock_appear(self):
        conn = database([line("#1", "2026-08-01", "A", 10, 500.0, 0.0, 100.0)])
        rows = publish.inventory_metrics(conn, COSTS)
        self.assertEqual([row["sku"] for row in rows], ["A"])

    def test_bundle_sales_consume_component_stock(self):
        with_bundle = database([line("#1", "2026-08-01", "A", 10, 500.0, 0.0, 100.0),
                                line("#2", "2026-08-01", "D", 10, 550.0, 0.0, 120.0)])
        without = database([line("#1", "2026-08-01", "A", 10, 500.0, 0.0, 100.0)])
        faster = publish.inventory_metrics(with_bundle, COSTS)[0]
        slower = publish.inventory_metrics(without, COSTS)[0]
        self.assertGreater(faster["weekly"], slower["weekly"])
        self.assertLess(faster["cover_weeks"], slower["cover_weeks"])

    def test_sell_through_uses_batch_and_stock_not_sales(self):
        conn = database([line("#1", "2026-08-01", "A", 1, 50.0, 0.0, 10.0)])
        row = publish.inventory_metrics(conn, COSTS)[0]
        self.assertAlmostEqual(row["sell_through"], 80.0, places=2)  # 1000 made, 200 left

    def test_no_stock_declared_gives_no_inventory_view(self):
        costs = {key: value for key, value in COSTS.items()}
        costs["productos"] = {"B": COSTS["productos"]["B"]}
        conn = database([line("#1", "2026-08-01", "B", 1, 10.0, 0.0, 2.0)])
        self.assertEqual(publish.inventory_metrics(conn, costs), [])


class TestPace(unittest.TestCase):
    def test_projection_extrapolates_the_current_run_rate(self):
        # Half the window gone, half the target sold: it lands exactly on target.
        projection = publish.pace(COSTS, 500, today=datetime.date(2026, 7, 2))
        self.assertAlmostEqual(projection["projected_units"], 1000, delta=15)
        self.assertTrue(projection["on_track"])

    def test_a_slow_start_is_reported_as_short(self):
        projection = publish.pace(COSTS, 100, today=datetime.date(2026, 7, 2))
        self.assertFalse(projection["on_track"])
        self.assertLess(projection["gap"], 0)

    def test_required_pace_rises_as_the_window_closes(self):
        early = publish.pace(COSTS, 100, today=datetime.date(2026, 3, 1))
        late = publish.pace(COSTS, 100, today=datetime.date(2026, 11, 1))
        self.assertGreater(late["required_weekly"], early["required_weekly"])

    def test_a_closed_window_reports_no_required_pace(self):
        projection = publish.pace(COSTS, 900, today=datetime.date(2027, 1, 5))
        self.assertEqual(projection["remaining_days"], 0)
        self.assertIsNone(projection["required_weekly"])

    def test_verdict_is_a_sentence_not_a_percentage(self):
        projection = publish.pace(COSTS, 500, today=datetime.date(2026, 7, 2))
        self.assertIn("units a week", publish.pace_verdict(projection))

    def test_verdict_reads_as_english_in_both_directions(self):
        for sold, expected in ((900, "above"), (100, "below")):
            sentence = publish.pace_verdict(
                publish.pace(COSTS, sold, today=datetime.date(2026, 7, 2)))
            self.assertIn(expected, sentence)
            self.assertNotIn("of by", sentence)

    def test_only_units_inside_the_window_count_towards_the_target(self):
        conn = database([line("#1", "2025-06-01", "A", 40, 2000.0, 0.0, 400.0),
                         line("#2", "2026-06-01", "A", 10, 500.0, 0.0, 100.0)])
        self.assertEqual(publish.units_in_window(conn, COSTS), 10)


if __name__ == "__main__":
    unittest.main()


class TestFutureTargetWindow(unittest.TestCase):
    """A window that has not opened has no run rate. Clamping elapsed days to 1
    used to divide a whole period's sales by a single day and project nonsense."""

    FUTURE = {"productos": {}, "objetivo": {"unidades": 100,
                                            "desde": "2027-01-01", "hasta": "2027-12-31"}}

    def test_a_future_window_projects_nothing(self):
        projection = publish.pace(self.FUTURE, 50, today=datetime.date(2026, 8, 15))
        self.assertTrue(projection["not_started"])
        self.assertIsNone(projection["projected_units"])

    def test_a_future_window_never_reports_an_absurd_projection(self):
        projection = publish.pace(self.FUTURE, 50, today=datetime.date(2026, 8, 15))
        sentence = publish.pace_verdict(projection)
        self.assertIn("opens on 2027-01-01", sentence)
        self.assertNotIn("18,200", sentence)

    def test_an_open_window_still_projects(self):
        costs = {"productos": {}, "objetivo": {"unidades": 100,
                                               "desde": "2026-01-01", "hasta": "2026-12-31"}}
        projection = publish.pace(costs, 50, today=datetime.date(2026, 7, 2))
        self.assertFalse(projection["not_started"])
        self.assertIsNotNone(projection["projected_units"])


class TestDiscountRuleScope(unittest.TestCase):
    """The promotion control is a guardrail for declared rules. A code a store
    invented in its admin is untidy paperwork, not corrupt data, and must not
    block a dashboard."""

    def setUp(self):
        import checks
        self.checks = checks
        self.conn = database([line("#1", "2026-02-01", "A", 1, 50.0, 5.0, 10.0, "WELCOME10")])

    def result_for(self, discounts):
        costs = dict(COSTS)
        costs["descuentos"] = discounts
        result = self.checks.Resultado()
        self.checks.check_descuentos(self.conn, costs, result)
        return result

    def test_an_undeclared_code_warns_instead_of_blocking(self):
        result = self.result_for({})
        self.assertEqual(result.errores, [])
        self.assertTrue(result.avisos)

    def test_a_rule_can_be_addressed_by_a_label_plus_code(self):
        result = self.result_for({"welcome": {"codigo": "WELCOME10", "porcentaje": 10}})
        self.assertEqual(result.errores, [])

    def test_a_declared_rule_that_disagrees_is_still_an_error(self):
        result = self.result_for({"WELCOME10": {"porcentaje": 25}})
        self.assertTrue(result.errores)

    def test_a_shipping_rule_expects_no_product_line_discount(self):
        result = self.result_for({"WELCOME10": {"aplica": "envio"}})
        self.assertTrue(result.errores)   # this line does discount the product
        clean = database([line("#2", "2026-02-01", "A", 1, 50.0, 0.0, 10.0, "SHIP")])
        outcome = self.checks.Resultado()
        self.checks.check_descuentos(clean, dict(COSTS, descuentos={
            "SHIP": {"aplica": "envio"}}), outcome)
        self.assertEqual(outcome.errores, [])
