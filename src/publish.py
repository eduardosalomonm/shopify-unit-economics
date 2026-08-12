"""Fase 4: publicacion. Genera panel.html desde la base de datos.

Cierra el bucle: hasta ahora el panel tenia las cifras escritas a mano, asi que
el pipeline estaba automatizado y el entregable no. Aqui todo sale de la base de datos.

Uso:  python3 src/publish.py
"""

import datetime
import os
import sqlite3
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import checks  # noqa: E402
from transform import catalogo, latest_snapshot  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "data", "pipeline.db")
_REAL = os.path.join(BASE, "costs.yml")
# El repo publico no lleva costs.yml (costes de proveedor). Con el ejemplo, quien
# clone puede ejecutar el pipeline entero sin tener datos reales ni credenciales.
# COSTS_FILE fuerza un modelo concreto (la demo usa el de ejemplo aunque exista el real).
COSTS_PATH = os.environ.get("COSTS_FILE") or (
    _REAL if os.path.exists(_REAL) else os.path.join(BASE, "costs.example.yml"))
if not os.path.isabs(COSTS_PATH):
    COSTS_PATH = os.path.join(BASE, COSTS_PATH)
TEMPLATE = os.path.join(BASE, "src", "panel_template.html")
# PANEL_OUT permite generar la demo publica (docs/index.html) sin pisar el panel real.
OUTPUT = os.environ.get("PANEL_OUT") or os.path.join(BASE, "panel.html")
if not os.path.isabs(OUTPUT):
    OUTPUT = os.path.join(BASE, OUTPUT)

MESES = ["ene", "feb", "mar", "abr", "may", "jun",
         "jul", "ago", "sep", "oct", "nov", "dic"]


def euro(valor):
    return ("%.2f" % valor).replace(".", ",")


def iso(valor):
    return valor.isoformat() if hasattr(valor, "isoformat") else str(valor)


def serie_mensual(conn):
    """Todos los meses entre el primero y el ultimo, incluidos los de cero ventas.

    Los meses vacios son la mitad de la historia: omitirlos dibuja un negocio
    que no existe.
    """
    filas = dict(conn.execute(
        "SELECT substr(fecha,1,7), SUM(unidades) FROM lineas GROUP BY 1").fetchall())
    if not filas:
        return []
    primero = min(filas)
    hoy = datetime.date.today()
    anio, mes = int(primero[:4]), int(primero[5:7])
    serie = []
    while (anio, mes) <= (hoy.year, hoy.month):
        clave = "%04d-%02d" % (anio, mes)
        etiqueta = MESES[mes - 1] + (" %02d" % (anio % 100) if mes == 1 or not serie else "")
        serie.append((etiqueta, filas.get(clave, 0)))
        mes += 1
        if mes > 12:
            mes, anio = 1, anio + 1
    return serie


def tabla_skus(conn, costs):
    filas = conn.execute("""
        SELECT sku, SUM(unidades), ROUND(SUM(ingreso_neto),2), ROUND(SUM(coste_total),2),
               ROUND(SUM(margen_contribucion),2)
        FROM lineas GROUP BY sku ORDER BY SUM(unidades) DESC""").fetchall()
    html = []
    tu = ti = tc = tm = 0
    tabla = catalogo(costs)
    for sku, uds, ingreso, coste, margen in filas:
        ingreso = ingreso or 0.0
        # Un SKU sin coste declarado no recibe un margen inventado: se marca y se
        # queda fuera de los totales de coste y margen.
        if coste is None or margen is None:
            html.append('<tr><td>%s</td><td>%s</td><td>%d</td><td>%s</td>'
                        '<td colspan="3" class="neg">sin coste declarado</td></tr>'
                        % (sku, "SKU desconocido", uds, euro(ingreso)))
            tu += uds; ti += ingreso
            continue
        nombre = (tabla.get(sku) or {}).get("nombre", sku)
        pct = (100.0 * margen / ingreso) if ingreso else 0
        html.append("<tr><td>%s</td><td>%s</td><td>%d</td><td>%s</td><td>%s</td>"
                    "<td>%s</td><td>%.1f %%</td></tr>"
                    % (sku, nombre, uds, euro(ingreso), euro(coste), euro(margen), pct))
        tu += uds; ti += ingreso; tc += coste; tm += margen
    html.append('<tr class="total"><td>Total</td><td></td><td>%d</td><td>%s</td><td>%s</td>'
                '<td>%s</td><td>%.1f %%</td></tr>'
                % (tu, euro(ti), euro(tc), euro(tm), (100.0 * tm / ti) if ti else 0))
    return "\n".join(html), tu, ti, tm


def tabla_bundles(costs):
    P = costs["productos"]
    html = []
    for bundle in costs["bundles"].values():
        comps = bundle["contiene"]
        sueltos = sum(P[c["sku"]]["precio_web"] * c["uds"] for c in comps)
        coste = sum(P[c["sku"]]["coste_unitario"] * c["uds"] for c in comps)
        precio = float(bundle["precio_web"])
        ahorro = sueltos - precio
        grav = sum(P[c["sku"]]["precio_web"] * c["uds"] for c in comps)
        ex = precio / 1.21 if grav else precio
        margen = ex - coste
        estado = ('<span class="pill ok">Correcto</span>' if ahorro > 0
                  else '<span class="pill bad">Corregir</span>')
        clase = "pos" if ahorro > 0 else "neg"
        html.append("<tr><td>%s · %s</td><td>%s</td><td>%s</td>"
                    '<td class="%s">%s%s</td><td>%s (%.0f %%)</td><td>%s</td></tr>'
                    % (bundle.get("sku", ""), bundle["nombre"], euro(precio), euro(sueltos),
                       clase, "+" if ahorro > 0 else "−", euro(abs(ahorro)),
                       euro(margen), 100.0 * margen / ex if ex else 0, estado))
    return "\n".join(html)


def historico_precios(costs):
    """Historico de precios del SKU que lo tenga. No se asume ninguno concreto:
    el repo publico corre sobre un catalogo distinto al real."""
    tramos = []
    for producto in costs["productos"].values():
        if producto.get("precios"):
            tramos = producto["precios"]
            break
    html = []
    for i, tramo in enumerate(sorted(tramos, key=lambda t: iso(t["desde"]))):
        actual = " current" if i == len(tramos) - 1 else ""
        html.append('<div class="price%s"><div class="amount">%s €</div>'
                    '<div class="when">desde %s</div><div class="units">%s</div></div>'
                    % (actual, euro(float(tramo["precio"])), iso(tramo["desde"]),
                       tramo.get("fuente", "")))
    return "\n".join(html)


def bloque_alertas(res):
    """La alerta del panel sale de los controles, no de un texto escrito a mano."""
    if not res.errores:
        return ('<section><div class="tiles"><div class="tile"><div class="label">Controles</div>'
                '<div class="value">OK</div><div class="meta">%d avisos, ningun error</div>'
                "</div></div></section>" % len(res.avisos))
    filas = "".join("<li>%s</li>" % mensaje for _, mensaje in res.errores)
    return ('<section class="alert"><h2>%d %s que resolver</h2>'
            '<p>Detectados por los controles en esta ejecucion. El detalle completo, con el '
            'control que lo encontro, esta en la salida de <code>checks.py</code>.</p>'
            '<ul style="margin:0;padding-left:1.2rem;font-size:.9rem">%s</ul></section>'
            % (len(res.errores), "error" if len(res.errores) == 1 else "errores", filas))


def tabla_controles(res):
    total = {}
    for control, _ in res.errores:
        total.setdefault(control, [0, 0])[0] += 1
    for control, _ in res.avisos:
        total.setdefault(control, [0, 0])[1] += 1
    for control in ("SKU desconocido", "Precio catalogo vs tienda",
                    "Regla de bundle", "Coherencia de IVA"):
        total.setdefault(control, [0, 0])
    filas = []
    for control, (errores, avisos) in total.items():
        if errores:
            estado = '<span class="pill bad">%d errores</span>' % errores
        elif avisos:
            estado = '<span class="pill">%d avisos</span>' % avisos
        else:
            estado = '<span class="pill ok">Pasa</span>'
        filas.append("<tr><td>%s</td><td>%s</td></tr>" % (control, estado))
    return "\n".join(filas)


def main():
    if not os.path.exists(DB_PATH):
        raise SystemExit("Falta data/pipeline.db. Ejecuta antes src/transform.py")

    with open(COSTS_PATH, "r", encoding="utf-8") as fh:
        costs = yaml.safe_load(fh)
    conn = sqlite3.connect(DB_PATH)

    skus_html, unidades, ingreso, margen = tabla_skus(conn, costs)
    serie = serie_mensual(conn)

    objetivo = costs["objetivo"]
    desde, hasta = iso(objetivo["desde"]), iso(objetivo["hasta"])
    vendidas = conn.execute(
        "SELECT COALESCE(SUM(unidades),0) FROM lineas WHERE fecha BETWEEN ? AND ?",
        (desde, hasta)).fetchone()[0]
    dias = max((datetime.date(*[int(p) for p in hasta.split("-")])
                - datetime.date.today()).days, 0)
    ritmo = ((objetivo["unidades"] - vendidas) / (dias / 7.0)) if dias else 0

    ultima = conn.execute("SELECT MAX(fecha) FROM lineas").fetchone()[0]
    sin_ventas = (datetime.date.today()
                  - datetime.date(*[int(p) for p in ultima.split("-")])).days
    pedidos = conn.execute("SELECT COUNT(DISTINCT pedido) FROM lineas").fetchone()[0]

    res = checks.Resultado()
    for check in (checks.check_sku_desconocido, checks.check_precio_catalogo,
                  checks.check_bundles, checks.check_iva):
        check(conn, costs, res)

    with open(TEMPLATE, "r", encoding="utf-8") as fh:
        html = fh.read()

    sustituciones = {
        "{{MARCA}}": costs.get("meta", {}).get("marca", "Demo store"),
        "{{DOMINIO}}": costs.get("meta", {}).get("dominio", "example.com"),
        "{{GENERADO}}": datetime.date.today().strftime("%d/%m/%Y"),
        "{{UNIDADES}}": str(unidades),
        "{{PEDIDOS}}": str(pedidos),
        "{{INGRESO}}": euro(ingreso),
        "{{MARGEN}}": euro(margen),
        "{{MARGEN_PCT}}": ("%.1f" % ((100.0 * margen / ingreso) if ingreso else 0)).replace(".", ","),
        "{{OBJETIVO}}": str(objetivo["unidades"]),
        "{{VENDIDAS_VENTANA}}": str(vendidas),
        "{{DIAS}}": str(dias),
        "{{RITMO}}": ("%.1f" % ritmo).replace(".", ","),
        "{{SIN_VENTAS}}": str(sin_ventas),
        "{{ULTIMA_VENTA}}": "%s/%s/%s" % (ultima[8:10], ultima[5:7], ultima[:4]),
        "{{ALERTAS}}": bloque_alertas(res),
        "{{CONTROLES}}": tabla_controles(res),
        "{{SNAPSHOT}}": os.path.basename(latest_snapshot()),
        "{{FILAS_SKU}}": skus_html,
        "{{FILAS_BUNDLE}}": tabla_bundles(costs),
        "{{PRECIOS}}": historico_precios(costs),
        "{{SERIE}}": repr([[e, u] for e, u in serie]).replace("'", '"'),
        "{{N_MESES}}": str(len(serie)),
        "{{MAX_MES}}": str(max([u for _, u in serie] or [1])),
    }
    for clave, valor in sustituciones.items():
        html = html.replace(clave, valor)

    with open(OUTPUT, "w", encoding="utf-8") as fh:
        fh.write(html)

    conn.close()
    print("Panel generado: %s" % os.path.relpath(OUTPUT, BASE))
    print("  %d unidades · %s € ingreso · %s € margen" % (unidades, euro(ingreso), euro(margen)))
    print("  objetivo: %d de %d · %d dias · %s uds/semana"
          % (vendidas, objetivo["unidades"], dias, sustituciones["{{RITMO}}"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
