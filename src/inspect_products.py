"""Radiografia del catalogo: SKU, precio, estado y tratamiento de IVA por variante.

Sirve para dos cosas recurrentes:
  · comprobar que el IVA es coherente entre SKU
  · descubrir SKU nuevos, como los bundles, antes de que rompan checks.py

Solo lectura.

Uso:  python3 src/inspect_products.py
"""

import sys

from shopify import Client, ShopifyError

PRODUCTS_QUERY = """
query($cursor: String) {
  products(first: 50, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        title
        status
        totalInventory
        variants(first: 20) {
          edges {
            node {
              sku
              title
              price
              taxable
              inventoryQuantity
            }
          }
        }
      }
    }
  }
}
"""


def main():
    try:
        client = Client.from_env()
    except ShopifyError as exc:
        print("ERROR: %s" % exc)
        return 1

    cursor = None
    filas = []
    while True:
        block = client.query(PRODUCTS_QUERY, {"cursor": cursor})["products"]
        for edge in block["edges"]:
            producto = edge["node"]
            for vedge in producto["variants"]["edges"]:
                v = vedge["node"]
                filas.append((
                    v.get("sku") or "(sin sku)",
                    producto["title"],
                    v.get("title"),
                    producto["status"],
                    float(v["price"]) if v.get("price") is not None else None,
                    bool(v.get("taxable")),
                    v.get("inventoryQuantity"),
                ))
        if not block["pageInfo"]["hasNextPage"]:
            break
        cursor = block["pageInfo"]["endCursor"]

    print("%-12s %-34s %-10s %9s %-9s %8s"
          % ("SKU", "Producto", "Estado", "Precio", "IVA", "Stock"))
    for sku, titulo, variante, estado, precio, taxable, stock in sorted(filas):
        print("%-12s %-34s %-10s %9s %-9s %8s"
              % (sku, titulo[:34], estado,
                 ("%.2f" % precio) if precio is not None else "-",
                 "grava" if taxable else "NO grava",
                 stock if stock is not None else "-"))

    gravados = {f[0] for f in filas if f[5]}
    exentos = {f[0] for f in filas if not f[5]}
    print()
    if exentos and gravados:
        print("AVISO: conviven SKU gravados y exentos.")
        print("  gravados: %s" % ", ".join(sorted(gravados)))
        print("  exentos:  %s" % ", ".join(sorted(exentos)))
    elif gravados and not exentos:
        print("OK: todas las variantes tributan igual.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
