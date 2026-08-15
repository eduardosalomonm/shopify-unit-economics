"""Create a credible 12-month DTC sales dataset without Shopify credentials.

The default fixture represents a growing skincare business. Its twelve monthly
gross-sales figures add up to exactly €83,755.43 after discounts, which makes it a
useful public portfolio dataset rather than a toy sample.

This is a different dataset from the Excel workbook, deliberately reconciled to the
same annual total. Expect the two demo paths to agree on total sales and to differ
on order counts and average order value, because they describe different baskets.
"""

import argparse
import calendar
import datetime
import json
import os
import random
import sys


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE, "data", "raw")
VAT = 1.21
DISCOUNT_RATE = 0.10

# Monthly gross sales (including VAT, after discounts). Total: exactly €83,755.43.
MONTHLY_GROSS_SALES = [
    ("2025-08", 5000), ("2025-09", 5200), ("2025-10", 5600),
    ("2025-11", 6400), ("2025-12", 7500), ("2026-01", 6500),
    ("2026-02", 5900), ("2026-03", 6800), ("2026-04", 7400),
    ("2026-05", 8000), ("2026-06", 10300), ("2026-07", 9155.43),
]

TYPES = [
    ("SKU-A", "Renewal Serum", 64.0, 0.36),
    ("SKU-B", "Barrier Balm", 19.0, 0.09),
    ("SKU-C", "Contour Stone", 29.0, 0.05),
    ("SKU-D", "Daily Duo", 79.0, 0.21),
    ("SKU-E", "Complete Ritual", 89.0, 0.16),
    ("SKU-F", "Cloud Cleanser", 34.0, 0.10),
    ("SKU-G", "Daily Reset Set", 69.0, 0.12),
]


def money(amount):
    return {"shopMoney": {"amount": "%.2f" % amount, "currencyCode": "EUR"}}


def month_price(sku, month):
    """Return the catalogue price in force for each historical order month."""
    if sku == "SKU-A" and month >= "2026-01":
        return 69.90
    if sku == "SKU-B" and month < "2026-03":
        return 18.0
    return next(price for candidate, _, price, _ in TYPES if candidate == sku)


def finish_order_lines(remaining, month):
    """Find a small exact combination that closes each monthly sales target."""
    candidates = []
    for sku, title, _, _ in TYPES:
        price = month_price(sku, month)
        candidates.extend([(sku, title, price, 0.0),
                           (sku, title, price, round(price * DISCOUNT_RATE, 2))])
    cents = int(round(remaining * 100))
    # Work in cents so the public fixture can model realistic retail endings
    # while still reconciling every month exactly.
    target = cents
    steps = [int(round((price - discount) * 100)) for _, _, price, discount in candidates]
    previous = {0: None}
    for amount in range(1, target + 1):
        for index, step in enumerate(steps):
            if amount >= step and amount - step in previous:
                previous[amount] = (amount - step, index)
                break
    if target in previous:
        result = []
        amount = target
        while amount:
            amount, index = previous[amount]
            result.append(candidates[index])
        return result
    raise RuntimeError("Could not close monthly target %s with available product prices." % remaining)


def pick_type(rng):
    roll = rng.random()
    cumulative = 0.0
    for item in TYPES:
        cumulative += item[3]
        if roll <= cumulative:
            return item
    return TYPES[-1]


def line_node(index, sku, title, price, discount=0.0):
    return {"node": {
        "id": "gid://shopify/LineItem/%d" % index, "title": title, "sku": sku,
        "quantity": 1, "variant": None, "product": None,
        "originalUnitPriceSet": money(price), "discountedUnitPriceSet": money(price),
        "totalDiscountSet": money(0.0),
        "discountAllocations": ([{"allocatedAmountSet": money(discount)}] if discount else []),
        "taxable": True,
    }}


def order_node(index, date, lines):
    """Wrap one or more lines into a single order.

    Baskets carry more than one line on purpose. A fixture where every order holds
    exactly one line makes average order value equal to average selling price and
    makes basket size and bundle attach meaningless, which is precisely what the
    dashboard is supposed to measure.
    """
    net = round(sum(price - discount for _, _, price, discount in lines), 2)
    discount_total = round(sum(discount for _, _, _, discount in lines), 2)
    tax = round(net - net / VAT, 2)
    return {
        "id": "gid://shopify/Order/%d" % index,
        "name": "#%d" % index,
        "createdAt": "%sT%02d:%02d:00Z" % (date, (index * 7) % 20 + 2, (index * 13) % 60),
        "cancelledAt": None, "displayFinancialStatus": "PAID", "test": False,
        "currentTotalPriceSet": money(net), "currentTotalDiscountsSet": money(discount_total),
        "totalShippingPriceSet": money(0.0), "currentTotalTaxSet": money(tax),
        "taxesIncluded": True, "discountCodes": ["WELCOME10"] if discount_total else [],
        "lineItems": {"edges": [line_node(index * 100 + position, sku, title, price, discount)
                                for position, (sku, title, price, discount)
                                in enumerate(lines)]},
    }


def build(include_failures=False):
    """Generate the lines that reconcile each month exactly, then group them into
    orders. Grouping never changes the totals, so the fixture keeps its exact
    monthly reconciliation while baskets stop being one line each."""
    rng = random.Random(8375543)
    # Grouping draws from its own stream. Sharing the line generator's stream would
    # shift it and break the exact monthly reconciliation further down the year.
    basket_rng = random.Random(20260815)
    orders = []
    index = 1001
    for month, target in MONTHLY_GROSS_SALES:
        remaining = float(target)
        year, month_number = [int(value) for value in month.split("-")]
        last_day = calendar.monthrange(year, month_number)[1]
        lines = []
        # Leave enough room for an exact close with a few ordinary full-price items.
        while remaining > 650:
            sku, title, _, _ = pick_type(rng)
            price = month_price(sku, month)
            discount = round(price * DISCOUNT_RATE, 2) if rng.random() < 0.12 else 0.0
            net = price - discount
            if net > remaining - 500:
                continue
            lines.append((sku, title, price, discount))
            remaining = round(remaining - net, 2)
        lines.extend(finish_order_lines(remaining, month))

        # A discount code applies to the whole order, so a basket must not mix
        # discounted and full-price lines: the code would be attributed to a line
        # that never carried it, and the allocation control would rightly object.
        for group in ([line for line in lines if line[3]],
                      [line for line in lines if not line[3]]):
            position = 0
            while position < len(group):
                size = (1 if basket_rng.random() < 0.66
                        else (2 if basket_rng.random() < 0.8 else 3))
                basket = group[position:position + size]
                position += len(basket)
                day = min(last_day, 1 + (index * 11 + month_number * 3) % last_day)
                orders.append(order_node(index, "%s-%02d" % (month, day), basket))
                index += 1

    if include_failures:
        orders.append(order_node(index, "2026-07-29", [("SKU-A", "Renewal Serum", 64.0, 0.0)]))
        orders.append(order_node(index + 1, "2026-07-30",
                                 [("SKU-Z", "Discontinued Sample", 12.0, 0.0)]))
    return orders


def gross_sales(orders):
    return round(sum(float(order["currentTotalPriceSet"]["shopMoney"]["amount"]) for order in orders), 2)


def main():
    parser = argparse.ArgumentParser(description="Write a successful synthetic Shopify sales snapshot.")
    parser.add_argument("--with-errors", action="store_true",
                        help="include two deliberately invalid orders for control demonstrations")
    args = parser.parse_args()
    os.makedirs(RAW_DIR, exist_ok=True)
    orders = build(args.with_errors)
    name = "orders-demo-with-errors.json" if args.with_errors else "orders-demo.json"
    path = os.path.join(RAW_DIR, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"extracted": datetime.datetime.now().isoformat(),
                   "store": "demo-store.myshopify.com", "pedidos": orders}, handle,
                  ensure_ascii=False, indent=1)
    print("Synthetic snapshot written: %s" % os.path.relpath(path, BASE))
    print("%d orders · €%s gross sales after discounts" % (len(orders), "%.2f" % gross_sales(orders)))
    print("Now run: python3 src/transform.py && python3 src/checks.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
