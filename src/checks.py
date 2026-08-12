"""Fase 3: controles. Fallan ruidosamente, no en un log que nadie lee.

Cada control existe porque el error correspondiente ya ocurrio de verdad:
  1. SKU desconocido            -> margen calculado sobre coste inventado
  2. Precio catalogo vs tienda  -> dos precios casi iguales convivieron meses en documentos
  3. Regla de bundle            -> un bundle nunca puede costar menos que su articulo mas caro
  4. Coherencia de IVA          -> un SKU como taxable:false mientras los demas tributan

Salida: codigo 0 si todo pasa, 1 si hay algun ERROR. Los AVISOS no bloquean.

Uso:  python3 src/checks.py
"""

import os
import sqlite3
import sys

import yaml

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
        res.error("SKU desconocido",
                  "'%s' (%s): %d uds sin coste en costs.yml. El margen de esas lineas no existe."
                  % (sku or "(vacio)", titulo, unidades))


def check_precio_catalogo(conn, costs, res):
    filas = conn.execute(
        "SELECT pedido, fecha, sku, precio_bruto, precio_catalogo, unidades FROM lineas "
        "WHERE precio_catalogo IS NOT NULL AND precio_bruto IS NOT NULL "
        "AND ABS(precio_bruto - precio_catalogo) > ?", (TOLERANCIA,)).fetchall()
    for pedido, fecha, sku, bruto, catalogo, unidades in filas:
        res.error("Precio catalogo vs tienda",
                  "%s (%s) %s: la tienda cobro %.2f y el catalogo dice %.2f (%d uds)"
                  % (pedido, fecha, sku, bruto, catalogo, unidades))


def check_bundles(conn, costs, res):
    for clave, bundle in (costs.get("bundles") or {}).items():
        if not bundle.get("confirmado"):
            res.aviso("Regla de bundle",
                      "%s: composicion sin confirmar, no se puede validar su margen ni la regla "
                      "de precio." % bundle["nombre"])
            continue

        componentes = bundle.get("contiene") or []
        if not componentes:
            res.error("Regla de bundle",
                      "%s marcado como confirmado pero sin componentes." % bundle["nombre"])
            continue

        precios = []
        coste = 0.0
        for comp in componentes:
            producto = costs["productos"].get(comp["sku"])
            if not producto:
                res.error("Regla de bundle",
                          "%s contiene un SKU inexistente: %s" % (bundle["nombre"], comp["sku"]))
                continue
            precios.append(float(producto["precio_web"]))
            coste += float(producto["coste_unitario"]) * comp.get("uds", 1)

        precio = float(bundle["precio_web"])

        if precios and precio <= max(precios):
            res.error("Regla de bundle",
                      "%s cuesta %.2f y su articulo mas caro vale %.2f. Rompe la regla."
                      % (bundle["nombre"], precio, max(precios)))

        # El bundle tiene que ahorrar algo frente a comprar los articulos sueltos,
        # a los precios VIGENTES. Si no, el cliente paga mas por el pack.
        sueltos = sum(float(costs["productos"][c["sku"]]["precio_web"]) * c.get("uds", 1)
                      for c in componentes if c["sku"] in costs["productos"])
        if precio >= sueltos:
            res.error("Regla de bundle",
                      "%s cuesta %.2f y comprar sus articulos sueltos cuesta %.2f. "
                      "El pack sale MAS CARO que comprarlo por separado."
                      % (bundle["nombre"], precio, sueltos))

        # El ahorro anunciado en la ficha tiene que coincidir con el real.
        declarado = bundle.get("sueltos_declarado")
        if declarado is not None and abs(float(declarado) - sueltos) > 0.01:
            res.error("Regla de bundle",
                      "%s: la ficha dice %.2f de precio suelto y hoy son %.2f. "
                      "El texto se escribio con precios antiguos."
                      % (bundle["nombre"], float(declarado), sueltos))

        ahorro_dec = bundle.get("ahorro_declarado")
        if ahorro_dec is not None and abs(float(ahorro_dec) - (sueltos - precio)) > 0.01:
            res.error("Regla de bundle",
                      "%s: la ficha anuncia %.2f de ahorro y el real es %.2f."
                      % (bundle["nombre"], float(ahorro_dec), sueltos - precio))

        margen = float(bundle["precio_web"]) - coste
        if margen <= 0:
            res.error("Regla de bundle",
                      "%s tiene margen negativo: precio %.2f, coste %.2f"
                      % (bundle["nombre"], float(bundle["precio_web"]), coste))


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
        res.aviso("Coherencia de IVA",
                  "En el historico conviven SKU gravados (%s) y no gravados (%s); el ultimo "
                  "pedido afectado es del %s. El tratamiento en la tienda ya se corrigio: "
                  "verifica con inspect_products.py, no con este historico, que refleja como "
                  "estaban las cosas cuando se cobro cada pedido."
                  % (", ".join(sorted(gravados)), ", ".join(sorted(no_gravados)), ultima))

    for sku, ts in estados.items():
        if len(ts) > 1:
            res.error("Coherencia de IVA",
                      "%s aparece unas veces gravado y otras no. Eso si es un error de datos."
                      % sku)


def main():
    if not os.path.exists(DB_PATH):
        raise SystemExit("No existe data/pipeline.db. Ejecuta antes src/transform.py")

    with open(COSTS_PATH, "r", encoding="utf-8") as fh:
        costs = yaml.safe_load(fh)

    conn = sqlite3.connect(DB_PATH)
    res = Resultado()

    for check in (check_sku_desconocido, check_precio_catalogo, check_bundles, check_iva):
        check(conn, costs, res)

    conn.close()

    if res.errores:
        print("ERRORES (%d)" % len(res.errores))
        for control, mensaje in res.errores:
            print("  [%s] %s" % (control, mensaje))
        print()
    if res.avisos:
        print("AVISOS (%d)" % len(res.avisos))
        for control, mensaje in res.avisos:
            print("  [%s] %s" % (control, mensaje))
        print()

    if not res.errores and not res.avisos:
        print("Todos los controles pasan.")
    elif not res.errores:
        print("Sin errores. Los avisos no bloquean el panel.")

    return 1 if res.errores else 0


if __name__ == "__main__":
    sys.exit(main())
