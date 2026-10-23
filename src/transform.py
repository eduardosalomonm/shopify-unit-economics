"""Fase 3: transformacion. Del snapshot crudo a una fila por linea de pedido.

Salidas:
  data/pipeline.db     SQLite, para consultar y para conectar Power BI
  data/margins.csv  resumen por SKU, legible sin herramientas

No inventa nada: si un SKU no esta en costs.yml, la fila sale con coste nulo y
checks.py lo convierte en error. Un margen calculado sobre un coste inventado es
peor que no tener margen.

Uso:  python3 src/transform.py
"""

import csv
import datetime
import glob
import json
import os
import sqlite3
import sys

from config import ConfigError, costs_path, load_costs, validate_finite_values, variable_costs

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.abspath(os.environ.get("PIPELINE_DATA_DIR", os.path.join(BASE, "data")))
RAW_DIR = os.path.join(DATA_DIR, "raw")
DB_PATH = os.path.join(DATA_DIR, "pipeline.db")
CSV_PATH = os.path.join(DATA_DIR, "margins.csv")
COSTS_PATH = costs_path()


def latest_snapshot():
    """SNAPSHOT fuerza un archivo concreto; si no, el mas reciente por fecha de
    modificacion (por nombre, orders-demo.json ordena despues de una fecha)."""
    forzado = os.environ.get("SNAPSHOT")
    if forzado:
        return forzado if os.path.isabs(forzado) else os.path.join(BASE, forzado)
    files = glob.glob(os.path.join(RAW_DIR, "orders-*.json"))
    if not files:
        raise SystemExit("No snapshots exist in data/raw. Run src/extract.py first "
                         "(or src/make_demo_data.py for the synthetic demo).")
    return max(files, key=os.path.getmtime)


def money(node, field):
    """Extrae un importe de un *Set de Shopify. Devuelve None si no viene."""
    block = (node or {}).get(field) or {}
    shop_money = block.get("shopMoney") or {}
    amount = shop_money.get("amount")
    validate_finite_values(amount, "amount")
    return float(amount) if amount is not None else None


def allocated_discount(item):
    """Return Shopify's final discount allocation for a line, if supplied.

    The Admin API allocates every applicable discount to the line, including
    code-based and order-level promotions. This is more accurate than dividing an
    order total proportionally, which can incorrectly assign a shipping discount
    to merchandise revenue. Older snapshots and the minimal test fixture have no
    allocation field, so callers can explicitly use the legacy fallback.
    """
    allocations = item.get("discountAllocations")
    if allocations is None:
        return None
    total = 0.0
    for allocation in allocations:
        total += money(allocation, "allocatedAmountSet") or 0.0
    return round(total, 2)


def catalogo(costs):
    """SKU -> nombre y coste, productos y bundles juntos.

    El coste de un bundle es la suma de sus componentes. Sin esto, la primera venta
    de un Ritual Duo entraria como SKU desconocido y se quedaria sin margen.
    """
    tabla = {}
    for sku, producto in costs["productos"].items():
        tabla[sku] = {
            "nombre": producto["nombre"],
            "coste": float(producto["coste_unitario"]),
            "es_bundle": False,
        }
    for bundle in (costs.get("bundles") or {}).values():
        sku = bundle.get("sku")
        if not sku:
            continue
        coste = 0.0
        completo = True
        for comp in bundle.get("contiene") or []:
            producto = costs["productos"].get(comp["sku"])
            if not producto:
                completo = False
                break
            coste += float(producto["coste_unitario"]) * comp.get("uds", 1)
        if completo:
            tabla[sku] = {"nombre": bundle["nombre"], "coste": round(coste, 2),
                          "es_bundle": True}
    return tabla


def precio_catalogo(costs, sku, fecha):
    """Precio vigente ese dia, segun el historico declarado en costs.yml.

    Un precio unico no sirve: un SKU puede haber tenido varios. Comparar un pedido de 2025
    contra el precio de hoy genera errores falsos que acaban ignorandose, y un
    control que se ignora no es un control.
    """
    producto = costs["productos"].get(sku)
    if not producto:
        for bundle in (costs.get("bundles") or {}).values():
            if bundle.get("sku") == sku:
                return float(bundle["precio_web"])
        return None
    historico = producto.get("precios")
    if not historico:
        return float(producto["precio_web"])

    vigente = None
    for tramo in sorted(historico, key=lambda t: str(t["desde"])):
        desde = tramo["desde"]
        desde = desde.isoformat() if hasattr(desde, "isoformat") else str(desde)
        if fecha >= desde:
            vigente = float(tramo["precio"])
    return vigente if vigente is not None else float(producto["precio_web"])


def build_rows(snapshot, costs):
    """Una fila por linea de pedido, con dos correcciones que no son opcionales:

    1. El descuento final se toma de discountAllocations por linea. Es la asignacion
       de Shopify para descuentos de codigo, pedido y producto. Snapshots antiguos
       sin ese campo usan un reparto proporcional como compatibilidad, nunca como
       sustituto de una extraccion actual.
    2. Los precios de la tienda INCLUYEN IVA (taxesIncluded). Comparar un precio con
       IVA contra un coste sin IVA infla el margen. El margen se calcula ex IVA.
    """
    validate_finite_values(snapshot)
    validate_finite_values(costs)
    tipo_iva = float(costs.get("iva", {}).get("tipo_pct", 21.0))
    tabla = catalogo(costs)
    rows = []
    envio_por_pedido = {}
    for order in snapshot["pedidos"]:
        if order.get("test") or order.get("cancelledAt"):
            continue
        fecha = order["createdAt"][:10]
        codigos = ",".join(order.get("discountCodes") or [])
        incluye_iva = bool(order.get("taxesIncluded"))
        descuento_pedido = money(order, "currentTotalDiscountsSet") or 0.0

        # Shipping is charged once per order object. The Excel workflow writes one
        # object per line, so it records the charge on the first line of each order.
        envio = money(order, "totalShippingPriceSet") or 0.0
        envio_neto = envio / (1 + tipo_iva / 100.0) if incluye_iva else envio
        cobrado, neto = envio_por_pedido.get(order["name"], (0.0, 0.0))
        envio_por_pedido[order["name"]] = (cobrado + envio, neto + envio_neto)

        lineas = [e["node"] for e in order["lineItems"]["edges"]]
        base_total = sum((money(i, "originalUnitPriceSet") or 0.0) * (i.get("quantity") or 0)
                         for i in lineas)

        for item in lineas:
            sku = item.get("sku") or ""
            qty = item.get("quantity") or 0
            bruto = money(item, "originalUnitPriceSet")
            base_linea = (bruto or 0.0) * qty

            # 1. Shopify supplies a final allocation per line. Fall back only for
            # legacy raw snapshots that predate that field.
            descuento_linea = allocated_discount(item)
            if descuento_linea is None:
                cuota = (base_linea / base_total) if base_total else 0.0
                descuento_linea = round(descuento_pedido * cuota, 2)
            ingreso_con_iva = round(base_linea - descuento_linea, 2)

            # 2. Paso a ex IVA. Solo las lineas gravadas llevan IVA incluido.
            gravada = bool(item.get("taxable"))
            if incluye_iva and gravada:
                ingreso_ex_iva = round(ingreso_con_iva / (1 + tipo_iva / 100.0), 2)
            else:
                ingreso_ex_iva = ingreso_con_iva
            iva_implicito = round(ingreso_con_iva - ingreso_ex_iva, 2)

            entrada = tabla.get(sku)
            coste_unit = entrada["coste"] if entrada else None
            coste = round(coste_unit * qty, 2) if coste_unit is not None else None
            margen = round(ingreso_ex_iva - coste, 2) if coste is not None else None

            rows.append({
                "pedido": order["name"],
                "fecha": fecha,
                "sku": sku,
                "titulo": item.get("title"),
                "unidades": qty,
                "precio_bruto": bruto,
                "descuento_linea": descuento_linea,
                "precio_catalogo": precio_catalogo(costs, sku, fecha),
                "coste_unitario": coste_unit,
                "ingreso_con_iva": ingreso_con_iva,
                "iva_implicito": iva_implicito,
                "ingreso_neto": ingreso_ex_iva,
                "coste_total": coste,
                "margen_contribucion": margen,
                "margen_pct": round(100.0 * margen / ingreso_ex_iva, 1) if margen is not None
                              and ingreso_ex_iva else None,
                "taxable": 1 if gravada else 0,
                "codigos_descuento": codigos,
                "estado_financiero": order.get("displayFinancialStatus"),
                "iva_pedido_declarado": money(order, "currentTotalTaxSet"),
                "envio_pedido": money(order, "totalShippingPriceSet"),
            })
    aplicar_costes_variables(rows, envio_por_pedido, costs)
    return rows


def repartir(total, pesos):
    """Split an amount into cents by weight, so the parts add up to the total exactly.

    Rounding each share independently leaves a cent or two unexplained on a busy
    order; the largest remainders absorb those cents instead.
    """
    centimos = int(round(total * 100))
    suma = sum(pesos)
    if suma <= 0:
        pesos, suma = [1.0] * len(pesos), float(len(pesos))
    brutos = [centimos * peso / suma for peso in pesos]
    partes = [int(valor) for valor in brutos]
    orden = sorted(range(len(pesos)), key=lambda i: (-(brutos[i] - partes[i]), i))
    for indice in orden[:centimos - sum(partes)]:
        partes[indice] += 1
    return [parte / 100.0 for parte in partes]


def aplicar_costes_variables(rows, envio_por_pedido, costs):
    """Add the optional per-order and monthly costs to each line.

    Order-level amounts (shipping charged, fulfilment, payment fees) follow each
    line's share of what the customer paid. Monthly advertising follows each line's
    share of that month's net revenue. Both are allocations, stated as such, so a
    SKU or promotion filter still adds up to the store total.
    """
    modelo = variable_costs(costs)
    campos = ("ingreso_envio", "coste_logistica", "comision_pago", "coste_publicidad",
              "resultado_variable")
    for row in rows:
        for campo in campos:
            row[campo] = None
    if modelo is None or not rows:
        return

    por_pedido = {}
    for row in rows:
        por_pedido.setdefault(row["pedido"], []).append(row)
    for pedido, lineas in por_pedido.items():
        pesos = [max(linea["ingreso_con_iva"], 0.0) for linea in lineas]
        envio_cobrado, envio_neto = envio_por_pedido.get(pedido, (0.0, 0.0))
        # Payment providers charge on everything the customer paid, VAT and shipping included.
        cobrado = sum(linea["ingreso_con_iva"] for linea in lineas) + envio_cobrado
        comision = cobrado * modelo["comision_pago_pct"] / 100.0 + modelo["comision_pago_fija"]
        for campo, importe in (("ingreso_envio", envio_neto),
                               ("coste_logistica", modelo["logistica_por_pedido"]),
                               ("comision_pago", comision)):
            for linea, parte in zip(lineas, repartir(importe, pesos)):
                linea[campo] = parte

    por_mes = {}
    for row in rows:
        por_mes.setdefault(row["fecha"][:7], []).append(row)
    for row in rows:
        row["coste_publicidad"] = 0.0
    for mes, importe in modelo["publicidad"].items():
        lineas = por_mes.get(mes)
        if not lineas:
            continue  # checks.py reports advertising that has no sales to land on.
        pesos = [max(linea["ingreso_neto"], 0.0) for linea in lineas]
        for linea, parte in zip(lineas, repartir(importe, pesos)):
            linea["coste_publicidad"] = parte

    for row in rows:
        if row["margen_contribucion"] is None:
            continue
        row["resultado_variable"] = round(
            row["margen_contribucion"] + row["ingreso_envio"] - row["coste_logistica"]
            - row["comision_pago"] - row["coste_publicidad"], 2)


def write_db(rows):
    validate_finite_values(rows)  # Also catch arithmetic overflow before replacing data.
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)   # se reconstruye siempre desde el snapshot crudo
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE lineas (
            pedido TEXT, fecha TEXT, sku TEXT, titulo TEXT, unidades INTEGER,
            precio_bruto REAL, descuento_linea REAL, precio_catalogo REAL,
            coste_unitario REAL, ingreso_con_iva REAL, iva_implicito REAL,
            ingreso_neto REAL, coste_total REAL,
            margen_contribucion REAL, margen_pct REAL,
            taxable INTEGER, codigos_descuento TEXT, estado_financiero TEXT,
            iva_pedido_declarado REAL, envio_pedido REAL,
            ingreso_envio REAL, coste_logistica REAL, comision_pago REAL,
            coste_publicidad REAL, resultado_variable REAL
        )
    """)
    columns = ["pedido", "fecha", "sku", "titulo", "unidades", "precio_bruto", "descuento_linea",
               "precio_catalogo", "coste_unitario", "ingreso_con_iva", "iva_implicito",
               "ingreso_neto", "coste_total", "margen_contribucion", "margen_pct", "taxable",
               "codigos_descuento", "estado_financiero", "iva_pedido_declarado", "envio_pedido",
               "ingreso_envio", "coste_logistica", "comision_pago", "coste_publicidad",
               "resultado_variable"]
    conn.executemany(
        "INSERT INTO lineas VALUES (%s)" % ",".join("?" * len(columns)),
        [tuple(row[c] for c in columns) for row in rows],
    )
    conn.commit()
    conn.close()
    return columns


def write_csv(rows, costs):
    os.makedirs(DATA_DIR, exist_ok=True)
    tabla = catalogo(costs)
    resumen = {}
    for row in rows:
        entry = resumen.setdefault(row["sku"], {
            "sku": row["sku"],
            "nombre": (tabla.get(row["sku"]) or {}).get("nombre", "DESCONOCIDO"),
            "unidades": 0, "ingreso_neto": 0.0, "coste_total": 0.0, "margen": 0.0,
            "resultado_variable": None,
        })
        entry["unidades"] += row["unidades"]
        entry["ingreso_neto"] += row["ingreso_neto"]
        entry["coste_total"] += row["coste_total"] or 0.0
        entry["margen"] += row["margen_contribucion"] or 0.0
        if row["resultado_variable"] is not None:
            entry["resultado_variable"] = (entry["resultado_variable"] or 0.0) + row["resultado_variable"]

    filas = sorted(resumen.values(), key=lambda r: -r["unidades"])
    for fila in filas:
        for key in ("ingreso_neto", "coste_total", "margen", "resultado_variable"):
            if fila[key] is not None:
                fila[key] = round(fila[key], 2)
        fila["margen_pct"] = (round(100.0 * fila["margen"] / fila["ingreso_neto"], 1)
                              if fila["ingreso_neto"] else None)

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["sku", "nombre", "unidades", "ingreso_neto",
                                                "coste_total", "margen", "margen_pct",
                                                "resultado_variable"])
        writer.writeheader()
        writer.writerows(filas)
    return filas


def contador_objetivo(rows, costs):
    objetivo = costs["objetivo"]
    desde = objetivo["desde"]
    hasta = objetivo["hasta"]
    desde = desde.isoformat() if hasattr(desde, "isoformat") else str(desde)
    hasta = hasta.isoformat() if hasattr(hasta, "isoformat") else str(hasta)
    vendidas = sum(r["unidades"] for r in rows if desde <= r["fecha"] <= hasta)
    # Target pacing belongs to the snapshot. Rebuilding an old snapshot next week
    # must not silently change its reported outlook.
    as_of = max((r["fecha"] for r in rows), default=desde)
    as_of_date = datetime.date(*[int(p) for p in as_of.split("-")])
    dias = (datetime.date(*[int(p) for p in hasta.split("-")]) - as_of_date).days
    return objetivo["unidades"], vendidas, max(dias, 0), desde, hasta, as_of


def main():
    try:
        costs = load_costs(COSTS_PATH)
    except ConfigError as exc:
        raise SystemExit("COST MODEL ERROR: %s" % exc)

    path = latest_snapshot()
    with open(path, "r", encoding="utf-8") as fh:
        snapshot = json.load(fh)

    print("Snapshot: %s" % os.path.basename(path))
    try:
        rows = build_rows(snapshot, costs)
    except ConfigError as exc:
        raise SystemExit("INPUT ERROR: %s" % exc) from None
    write_db(rows)
    filas = write_csv(rows, costs)

    print("Lines processed: %d" % len(rows))
    print()
    print("%-8s %-28s %6s %10s %10s %10s %8s"
          % ("SKU", "Product", "Units", "Revenue", "Cost", "Margin", "Margin%"))
    total_u = total_i = total_m = 0
    for f in filas:
        print("%-8s %-28s %6d %10.2f %10.2f %10.2f %7s"
              % (f["sku"] or "(sin sku)", f["nombre"][:28], f["unidades"], f["ingreso_neto"],
                 f["coste_total"], f["margen"],
                 ("%.1f" % f["margen_pct"]) if f["margen_pct"] is not None else "-"))
        total_u += f["unidades"]
        total_i += f["ingreso_neto"]
        total_m += f["margen"]
    print("%-8s %-28s %6d %10.2f %10s %10.2f %7s"
          % ("TOTAL", "", total_u, total_i, "", total_m,
             "%.1f" % (100.0 * total_m / total_i) if total_i else "-"))

    if variable_costs(costs) is not None:
        resultado = sum(f["resultado_variable"] or 0.0 for f in filas)
        print("After shipping, fulfilment, payment fees and advertising: %.2f" % resultado)

    meta, vendidas, dias, desde, hasta, as_of = contador_objetivo(rows, costs)
    print()
    print("TARGET %d units (%s to %s; data through %s)" % (meta, desde, hasta, as_of))
    print("   sold in window: %d · remaining: %d · days remaining: %d"
          % (vendidas, meta - vendidas, dias))
    if dias:
        print("   required pace: %.1f units/week" % ((meta - vendidas) / (dias / 7.0)))

    print()
    print("Written: data/pipeline.db · data/margins.csv")
    print("Next: python3 src/checks.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
