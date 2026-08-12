"""Fase 1: extraccion. Baja los pedidos y los guarda crudos, sin transformar nada.

Principio: el snapshot crudo no se sobrescribe nunca. Es lo que permite reconstruir
cualquier cifra historica y saber de donde salio. Si una cifra del panel se discute,
se vuelve aqui.

Uso:  python3 src/extract.py
      python3 src/extract.py --since 2025-01-01
"""

import argparse
import datetime
import json
import os
import sys

from shopify import Client, ShopifyError

RAW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw")

ORDERS_QUERY = """
query($cursor: String, $query: String) {
  orders(first: 50, after: $cursor, query: $query, sortKey: CREATED_AT, reverse: false) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        name
        createdAt
        cancelledAt
        displayFinancialStatus
        test
        currentTotalPriceSet { shopMoney { amount currencyCode } }
        currentTotalDiscountsSet { shopMoney { amount } }
        totalShippingPriceSet { shopMoney { amount } }
        currentTotalTaxSet { shopMoney { amount } }
        taxesIncluded
        discountCodes
        # Sin customer: requiere read_customers (dato personal protegido) y el panel
        # no lo necesita. Si algun dia hace falta cohorte de cliente, sera en A5.
        lineItems(first: 50) {
          edges {
            node {
              id
              title
              sku
              quantity
              variant { id title }
              product { id title }
              originalUnitPriceSet { shopMoney { amount } }
              discountedUnitPriceSet { shopMoney { amount } }
              totalDiscountSet { shopMoney { amount } }
              taxable
            }
          }
        }
      }
    }
  }
}
"""


def fetch_orders(client, since=None):
    orders = []
    cursor = None
    query_filter = "created_at:>=%s" % since if since else None
    page = 0

    while True:
        data = client.query(ORDERS_QUERY, {"cursor": cursor, "query": query_filter})
        block = data["orders"]
        for edge in block["edges"]:
            orders.append(edge["node"])
        page += 1
        print("   pagina %d · %d pedidos acumulados" % (page, len(orders)))

        if not block["pageInfo"]["hasNextPage"]:
            break
        cursor = block["pageInfo"]["endCursor"]

    return orders


def summarise(orders):
    """Reconciliacion contra la realidad. Si no cuadra, el problema esta aqui."""
    live = [o for o in orders if not o.get("test") and not o.get("cancelledAt")]
    units = 0
    skus = {}
    for order in live:
        for edge in order["lineItems"]["edges"]:
            item = edge["node"]
            quantity = item.get("quantity") or 0
            units += quantity
            key = item.get("sku") or ("SIN_SKU: %s" % item.get("title"))
            skus[key] = skus.get(key, 0) + quantity
    return live, units, skus


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", help="fecha ISO, p.ej. 2025-01-01")
    args = parser.parse_args()

    try:
        client = Client.from_env()
    except ShopifyError as exc:
        print("ERROR: %s" % exc)
        return 1

    print("Extrayendo pedidos de %s" % client.store)
    try:
        orders = fetch_orders(client, args.since)
    except ShopifyError as exc:
        print("ERROR en la extraccion: %s" % exc)
        return 1

    os.makedirs(RAW_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(RAW_DIR, "orders-%s.json" % stamp)
    if os.path.exists(path):
        # Nunca se pisa un snapshot. Si ya hay uno de hoy, se numera.
        index = 2
        while os.path.exists(path):
            path = os.path.join(RAW_DIR, "orders-%s.%d.json" % (stamp, index))
            index += 1

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            {"extraido": datetime.datetime.now().isoformat(),
             "tienda": client.store,
             "pedidos": orders},
            fh, ensure_ascii=False, indent=1,
        )

    live, units, skus = summarise(orders)

    print()
    print("Snapshot: %s" % path)
    print("Pedidos totales: %d (validos, sin test ni cancelados: %d)" % (len(orders), len(live)))
    print("Unidades vendidas: %d" % units)
    print("Por SKU:")
    for sku in sorted(skus):
        print("   %-12s %d" % (sku, skus[sku]))

    print()
    if units == 27:
        print("RECONCILIACION OK: 27 unidades, coincide con el dato conocido.")
        print("Siguiente fase: modelo de costes (costs.yml) y transform.py")
        return 0

    print("RECONCILIACION NO CUADRA.")
    print("Se esperaban 27 unidades y salen %d." % units)
    print("No sigas a la fase 2 hasta entender la diferencia. Sospechosos habituales:")
    print("  · la ventana de 60 dias (falta el scope read_all_orders)")
    print("  · pedidos manuales o de Miravia que no estan en Shopify")
    print("  · el dato de 27 esta desactualizado (es de agosto 2026)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
