"""Integrity controls. They fail loudly rather than disappearing into a log.

Exit code 0 means no blocking errors; exit code 1 means the dashboard must not be
trusted. Warnings remain visible without blocking publication.
"""

import os
import sqlite3
import sys

from config import ConfigError, costs_path, load_costs

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.abspath(os.environ.get("PIPELINE_DATA_DIR", os.path.join(BASE, "data")))
DB_PATH = os.path.join(DATA_DIR, "pipeline.db")
COSTS_PATH = costs_path()

TOLERANCIA = 0.01   # euros


class Resultado:
    def __init__(self):
        self.errores = []
        self.avisos = []

    def error(self, control, mensaje):
        self.errores.append((control, mensaje))

    def aviso(self, control, mensaje):
        self.avisos.append((control, mensaje))


def check_sku_desconocido(conn, costs, res):
    filas = conn.execute(
        "SELECT sku, titulo, SUM(unidades) FROM lineas WHERE coste_unitario IS NULL "
        "GROUP BY sku, titulo").fetchall()
    for sku, titulo, unidades in filas:
        res.error("Unknown SKU",
                  "'%s' (%s): %d units have no declared cost. Their contribution margin does not exist."
                  % (sku or "(blank)", titulo, unidades))


def check_precio_catalogo(conn, costs, res):
    if (costs.get("meta") or {}).get("pricing_model") == "scenario":
        res.aviso("Catalogue price vs charged price",
                  "Scenario pricing is active: calculated Orders values follow the current Catalogue "
                  "instead of historical price entries.")
        return
    filas = conn.execute(
        "SELECT pedido, fecha, sku, precio_bruto, precio_catalogo, unidades FROM lineas "
        "WHERE precio_catalogo IS NOT NULL AND precio_bruto IS NOT NULL "
        "AND ABS(precio_bruto - precio_catalogo) > ?", (TOLERANCIA,)).fetchall()
    for pedido, fecha, sku, bruto, catalogo, unidades in filas:
        res.error("Catalogue price vs charged price",
                  "%s (%s) %s: the store charged %.2f but the catalogue says %.2f (%d units)"
                  % (pedido, fecha, sku, bruto, catalogo, unidades))


def check_bundles(conn, costs, res):
    for clave, bundle in (costs.get("bundles") or {}).items():
        if not bundle.get("confirmado"):
            res.aviso("Bundle pricing rules",
                      "%s: composition is unconfirmed, so its margin and pricing rule cannot be "
                      "validated." % bundle["nombre"])
            continue

        componentes = bundle.get("contiene") or []
        if not componentes:
            res.error("Bundle pricing rules",
                      "%s is marked confirmed but has no components." % bundle["nombre"])
            continue

        precios = []
        coste = 0.0
        for comp in componentes:
            producto = costs["productos"].get(comp["sku"])
            if not producto:
                res.error("Bundle pricing rules",
                          "%s contains an unknown SKU: %s" % (bundle["nombre"], comp["sku"]))
                continue
            precios.append(float(producto["precio_web"]))
            coste += float(producto["coste_unitario"]) * comp.get("uds", 1)

        precio = float(bundle["precio_web"])

        if precios and precio <= max(precios):
            res.error("Bundle pricing rules",
                      "%s costs %.2f and its most expensive item costs %.2f. It breaks the rule."
                      % (bundle["nombre"], precio, max(precios)))

        # El bundle tiene que ahorrar algo frente a comprar los articulos sueltos,
        # a los precios VIGENTES. Si no, el cliente paga mas por el pack.
        sueltos = sum(float(costs["productos"][c["sku"]]["precio_web"]) * c.get("uds", 1)
                      for c in componentes if c["sku"] in costs["productos"])
        if precio >= sueltos:
            res.error("Bundle pricing rules",
                      "%s costs %.2f and buying its items separately costs %.2f. "
                      "The bundle is MORE EXPENSIVE than buying separately."
                      % (bundle["nombre"], precio, sueltos))

        # El ahorro anunciado en la ficha tiene que coincidir con el real.
        declarado = bundle.get("sueltos_declarado")
        if declarado is not None and abs(float(declarado) - sueltos) > 0.01:
            res.error("Bundle pricing rules",
                      "%s: the product page says the separate-item total is %.2f but it is now %.2f. "
                      "The copy uses old prices."
                      % (bundle["nombre"], float(declarado), sueltos))

        ahorro_dec = bundle.get("ahorro_declarado")
        if ahorro_dec is not None and abs(float(ahorro_dec) - (sueltos - precio)) > 0.01:
            res.error("Bundle pricing rules",
                      "%s: the product page claims %.2f savings but the actual saving is %.2f."
                      % (bundle["nombre"], float(ahorro_dec), sueltos - precio))

        margen = float(bundle["precio_web"]) - coste
        if margen <= 0:
            # A loss-making price is commercially important, but it is not corrupt
            # data. Keep publishing so the dashboard can quantify the scenario;
            # the Excel Pricing planner and the published warning make it visible.
            res.aviso("Bundle pricing rules",
                      "%s is below cost: price %.2f, component cost %.2f. "
                      "The dashboard remains available so you can assess the loss."
                      % (bundle["nombre"], float(bundle["precio_web"]), coste))


def check_descuentos(conn, costs, res):
    """Verify the workbook's declared promotion terms against final line allocations.

    Shopify may allocate discounts in more complex ways in production, so this
    control is intentionally an Excel-workflow guardrail: it tells a workbook
    editor when a code, date window, or allocated amount no longer matches the
    declared rule.
    """
    declared = costs.get("descuentos") or {}
    # A rule is addressed by its discount code. The Excel workbook keys rules by code;
    # a hand-written cost model may key them by a human label and name the code in a
    # `codigo` field. Support both, and index only the rules that name a code.
    rules = {}
    for key, rule in declared.items():
        if not isinstance(rule, dict):
            continue
        code = str(rule.get("codigo") or key).strip()
        if code:
            rules[code] = rule

    rows = conn.execute("""
        SELECT pedido, fecha, sku, precio_bruto, unidades, descuento_linea, codigos_descuento
        FROM lineas WHERE codigos_descuento <> '' OR descuento_linea > 0
    """).fetchall()

    used = {(codes or "").split(",")[0].strip() for _, _, _, _, _, _, codes in rows}
    used.discard("")
    if used and not (used & set(rules)):
        # Nothing to validate against: the cost model does not describe any code this
        # store actually used. A store creates codes freely in its admin, so failing
        # every discounted line here would block a dashboard over missing paperwork
        # instead of over a real data defect. Say so once, and move on.
        res.aviso("Discount rule vs line allocation",
                  "%d discount code(s) used in orders (%s) are not described in the cost "
                  "model, so their allocations were not validated. Declare them as "
                  "promotion rules to switch this control on."
                  % (len(used), ", ".join(sorted(used))))
        return
    for order, date, sku, price, units, discount, codes in rows:
        code = (codes or "").split(",")[0].strip()
        if not code:
            res.aviso("Discount rule vs line allocation",
                      "%s %s: %.2f discount has no discount code to check." % (order, sku, discount))
            continue
        rule = rules.get(code)
        if not rule:
            # A store can create a code in its admin at any time. That is untidy
            # paperwork, not corrupt data, so it must not block a dashboard. What
            # this control exists to catch is a *declared* rule that no longer
            # matches what was actually allocated, and that is still an error below.
            res.aviso("Discount rule vs line allocation",
                      "%s %s: %s is used in orders but is not declared as a promotion "
                      "rule, so its allocation was not validated." % (order, sku, code))
            continue
        if not rule.get("activo", True):
            res.error("Discount rule vs line allocation",
                      "%s %s: %s is marked inactive but was used on %s."
                      % (order, sku, code, date))
        if rule.get("desde") and date < str(rule["desde"]):
            res.error("Discount rule vs line allocation",
                      "%s %s: %s was used before its active date." % (order, sku, code))
        if rule.get("hasta") and date > str(rule["hasta"]):
            res.error("Discount rule vs line allocation",
                      "%s %s: %s was used after its end date." % (order, sku, code))
        # A shipping code discounts the parcel, not the product line, so the correct
        # line allocation is zero. Validating it as a product discount turns a healthy
        # order into a false error.
        if str(rule.get("aplica", "")).strip().lower() in ("envio", "shipping"):
            if abs(float(discount)) > TOLERANCIA:
                res.error("Discount rule vs line allocation",
                          "%s %s: %s is declared as a shipping discount but takes %.2f "
                          "off the product line." % (order, sku, code, discount))
            continue

        # Percentage rules are the common case; a fixed amount covers codes that take
        # a flat sum off a line.
        if rule.get("importe") is not None:
            expected = round(float(rule["importe"]), 2)
            described = "flat %.2f" % expected
        else:
            expected = round(float(price) * int(units) * float(rule.get("porcentaje", 0)) / 100, 2)
            described = "%.1f%%" % float(rule.get("porcentaje", 0))
        if abs(float(discount) - expected) > TOLERANCIA:
            res.error("Discount rule vs line allocation",
                      "%s %s: %s allocates %.2f; the declared %s rule expects %.2f."
                      % (order, sku, code, discount, described, expected))


def check_iva(conn, costs, res):
    filas = conn.execute(
        "SELECT sku, taxable, COUNT(*), SUM(unidades) FROM lineas GROUP BY sku, taxable"
    ).fetchall()
    por_sku = {}
    for sku, taxable, lineas, unidades in filas:
        por_sku.setdefault(sku, []).append((taxable, lineas, unidades))

    estados = {sku: {t for t, _, _ in valores} for sku, valores in por_sku.items()}
    no_gravados = [sku for sku, ts in estados.items() if ts == {0}]
    gravados = [sku for sku, ts in estados.items() if ts == {1}]

    if no_gravados and gravados:
        ultima = conn.execute(
            "SELECT MAX(fecha) FROM lineas WHERE taxable = 0").fetchone()[0]
        res.aviso("VAT consistency",
                  "The history contains taxable SKUs (%s) and non-taxable SKUs (%s); the last "
                  "affected order is %s. Check the current store configuration with "
                  "inspect_products.py; history reflects how each order was charged."
                  % (", ".join(sorted(gravados)), ", ".join(sorted(no_gravados)), ultima))

    for sku, ts in estados.items():
        if len(ts) > 1:
            res.error("VAT consistency",
                      "%s appears taxable on some orders and non-taxable on others. This is a data error."
                      % sku)


# The single registry of controls. publish.py runs the same set and renders the
# same names, so a new control is added here once instead of in three places.
ALL_CHECKS = (check_sku_desconocido, check_precio_catalogo, check_bundles,
              check_descuentos, check_iva)

CONTROL_NAMES = ("Unknown SKU", "Catalogue price vs charged price", "Bundle pricing rules",
                 "Discount rule vs line allocation", "VAT consistency")


def run_all(conn, costs, res=None):
    """Run every control against an open connection and return the result."""
    res = res if res is not None else Resultado()
    for check in ALL_CHECKS:
        check(conn, costs, res)
    return res


def main():
    if not os.path.exists(DB_PATH):
        raise SystemExit("data/pipeline.db does not exist. Run src/transform.py first.")

    try:
        costs = load_costs(COSTS_PATH)
    except ConfigError as exc:
        raise SystemExit("COST MODEL ERROR: %s" % exc)

    conn = sqlite3.connect(DB_PATH)
    try:
        res = run_all(conn, costs)
    finally:
        conn.close()

    if res.errores:
        print("ERRORS (%d)" % len(res.errores))
        for control, mensaje in res.errores:
            print("  [%s] %s" % (control, mensaje))
        print()
    if res.avisos:
        print("WARNINGS (%d)" % len(res.avisos))
        for control, mensaje in res.avisos:
            print("  [%s] %s" % (control, mensaje))
        print()

    if not res.errores and not res.avisos:
        print("All integrity checks pass.")
    elif not res.errores:
        print("No errors. Warnings do not block the dashboard.")

    return 1 if res.errores else 0


if __name__ == "__main__":
    sys.exit(main())
