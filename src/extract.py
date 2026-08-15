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

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.abspath(os.environ.get("PIPELINE_DATA_DIR", os.path.join(BASE, "data")))
RAW_DIR = os.path.join(DATA_DIR, "raw")

LINE_ITEM_FIELDS = """
  id
  title
  sku
  quantity
  variant { id title }
  product { id title }
  originalUnitPriceSet { shopMoney { amount currencyCode } }
  discountedUnitPriceSet { shopMoney { amount currencyCode } }
  totalDiscountSet { shopMoney { amount currencyCode } }
  discountAllocations { allocatedAmountSet { shopMoney { amount currencyCode } } }
  taxable
"""

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
          pageInfo { hasNextPage endCursor }
          edges {
            node { %s }
          }
        }
      }
    }
  }
}
""" % LINE_ITEM_FIELDS

LINE_ITEMS_QUERY = """
query($id: ID!, $cursor: String) {
  order(id: $id) {
    lineItems(first: 50, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      edges { node { %s } }
    }
  }
}
""" % LINE_ITEM_FIELDS


def fetch_remaining_line_items(client, order):
    """Complete nested pagination so large orders are never silently truncated."""
    line_items = order["lineItems"]
    page = line_items.get("pageInfo") or {}
    while page.get("hasNextPage"):
        data = client.query(LINE_ITEMS_QUERY, {"id": order["id"], "cursor": page["endCursor"]})
        next_page = data.get("order")
        if not next_page:
            raise ShopifyError("Could not retrieve additional line items for %s." % order["name"])
        block = next_page["lineItems"]
        line_items["edges"].extend(block["edges"])
        page = block.get("pageInfo") or {}
    line_items.pop("pageInfo", None)


def fetch_orders(client, since=None):
    orders = []
    cursor = None
    query_filter = "created_at:>=%s" % since if since else None
    page = 0

    while True:
        data = client.query(ORDERS_QUERY, {"cursor": cursor, "query": query_filter})
        block = data["orders"]
        for edge in block["edges"]:
            order = edge["node"]
            fetch_remaining_line_items(client, order)
            orders.append(order)
        page += 1
        print("   page %d · %d orders collected" % (page, len(orders)))

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
    parser.add_argument("--expected-units", type=int,
                        help="reconciliacion opcional contra un total externo conocido")
    args = parser.parse_args()

    try:
        client = Client.from_env()
    except ShopifyError as exc:
        print("ERROR: %s" % exc)
        return 1

    print("Extracting orders from %s" % client.store)
    try:
        orders = fetch_orders(client, args.since)
    except ShopifyError as exc:
        print("EXTRACTION ERROR: %s" % exc)
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
    print("Total orders: %d (valid, excluding tests and cancellations: %d)" % (len(orders), len(live)))
    print("Units sold: %d" % units)
    print("By SKU:")
    for sku in sorted(skus):
        print("   %-12s %d" % (sku, skus[sku]))

    print()
    if args.expected_units is None:
        print("RECONCILIATION PENDING: no external reference total was supplied.")
        print("Compare these units with Shopify or your source of truth before publishing.")
        print("To fail on a mismatch: --expected-units %d" % units)
        print("Next: cost model and transform.py")
        return 0

    if units == args.expected_units:
        print("RECONCILIATION OK: %d units match the known total." % units)
        print("Next: cost model (costs.yml) and transform.py")
        return 0

    print("RECONCILIATION MISMATCH.")
    print("Expected %d units but extracted %d." % (args.expected_units, units))
    print("Do not continue to phase 2 until the difference is understood. Usual causes:")
    print("  · the 60-day window (missing read_all_orders scope)")
    print("  · manual or marketplace orders not present in Shopify")
    print("  · an outdated external reference total")
    return 2


if __name__ == "__main__":
    sys.exit(main())
