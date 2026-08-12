"""Generates a synthetic order snapshot so the pipeline runs without a real store.

The output mirrors the exact shape the Shopify Admin API returns, including the two
quirks the pipeline exists to handle:

  · discounts land at ORDER level (currentTotalDiscountsSet); the line-level
    totalDiscountSet is always "0.0"
  · prices are VAT-inclusive (taxesIncluded: true)

It also plants the failures the checks are meant to catch, so a reader can run the
demo and see the controls fire instead of taking the README's word for it:

  · an order priced off the historical price, not today's
  · a line with an SKU that is not in the cost model

Usage:  python3 src/make_demo_data.py
"""

import datetime
import json
import os
import random
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE, "data", "raw")

VAT = 1.21
WELCOME = 0.10

# (date, sku, title, unit price incl VAT, qty, discount code)
ORDERS = [
    ("2025-02-14", "SKU-A", "Example Serum", 48.00, 1, "WELCOME10"),
    ("2025-03-02", "SKU-A", "Example Serum", 48.00, 1, None),
    ("2025-04-19", "SKU-A", "Example Serum", 48.00, 2, "WELCOME10"),
    ("2025-06-08", "SKU-B", "Example Balm", 6.50, 3, None),
    ("2025-09-21", "SKU-A", "Example Serum", 48.00, 1, "WELCOME10"),
    ("2025-11-11", "SKU-A", "Example Serum", 43.00, 1, None),
    ("2025-12-03", "SKU-A", "Example Serum", 43.00, 2, "WELCOME10"),
    ("2026-01-16", "SKU-A", "Example Serum", 39.00, 1, None),
    ("2026-01-28", "SKU-C", "Example Tool", 8.00, 1, "WELCOME10"),
    ("2026-02-09", "SKU-D", "Example Duo", 41.00, 1, None),
    ("2026-02-22", "SKU-A", "Example Serum", 39.00, 3, "WELCOME10"),
    ("2026-03-05", "SKU-B", "Example Balm", 6.50, 2, None),
    # Planted failure 1: sold at the old price after the price change.
    ("2026-03-11", "SKU-A", "Example Serum", 43.00, 1, None),
    # Planted failure 2: an SKU that does not exist in the cost model.
    ("2026-03-18", "SKU-Z", "Discontinued Sample", 12.00, 1, None),
]


def money(amount):
    return {"shopMoney": {"amount": "%.2f" % amount, "currencyCode": "EUR"}}


def build():
    random.seed(7)
    pedidos = []
    for index, (fecha, sku, titulo, precio, qty, codigo) in enumerate(ORDERS, start=1001):
        bruto = precio * qty
        descuento = round(bruto * WELCOME, 2) if codigo else 0.0
        envio = 5.00 if bruto < 40 else 0.0
        total = round(bruto - descuento + envio, 2)
        iva = round(total - total / VAT, 2)

        pedidos.append({
            "id": "gid://shopify/Order/%d" % index,
            "name": "#%d" % index,
            "createdAt": "%sT10:%02d:00Z" % (fecha, random.randint(0, 59)),
            "cancelledAt": None,
            "displayFinancialStatus": "PAID",
            "test": False,
            "currentTotalPriceSet": money(total),
            "currentTotalDiscountsSet": money(descuento),
            "totalShippingPriceSet": money(envio),
            "currentTotalTaxSet": money(iva),
            "taxesIncluded": True,
            "discountCodes": [codigo] if codigo else [],
            "lineItems": {"edges": [{"node": {
                "id": "gid://shopify/LineItem/%d" % index,
                "title": titulo,
                "sku": sku,
                "quantity": qty,
                "variant": {"id": "gid://shopify/ProductVariant/%d" % index, "title": "Default"},
                "product": {"id": "gid://shopify/Product/%d" % index, "title": titulo},
                "originalUnitPriceSet": money(precio),
                "discountedUnitPriceSet": money(precio),
                # Always zero in the real API. This is the trap the pipeline avoids.
                "totalDiscountSet": money(0.0),
                "taxable": True,
            }}]},
        })
    return pedidos


def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    path = os.path.join(RAW_DIR, "orders-demo.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({
            "extraido": datetime.datetime.now().isoformat(),
            "tienda": "demo-store.myshopify.com",
            "pedidos": build(),
        }, fh, ensure_ascii=False, indent=1)

    print("Synthetic snapshot written: %s" % os.path.relpath(path, BASE))
    print("%d orders. Now run: python3 src/transform.py && python3 src/checks.py" % len(ORDERS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
