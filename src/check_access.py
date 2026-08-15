"""Verify Shopify access before extracting or writing any local data."""

import datetime
import sys

from shopify import Client, ShopifyError

NECESARIOS = ["read_orders", "read_products"]
OPCIONALES = ["read_inventory"]

SHOP_QUERY = """
{
  shop { name myshopifyDomain currencyCode ianaTimezone }
}
"""

OLDEST_ORDER_QUERY = """
{
  orders(first: 1, sortKey: CREATED_AT, reverse: false) {
    edges { node { name createdAt } }
  }
}
"""

RECENT_ORDERS_QUERY = """
{
  orders(first: 5, sortKey: CREATED_AT, reverse: true) {
    edges { node { name createdAt displayFulfillmentStatus } }
  }
}
"""


def main():
    print("1. Obtain token (client credentials grant)")
    try:
        client = Client.from_env()
    except ShopifyError as exc:
        print("   FAILED.")
        print("   %s" % exc)
        return 1
    print("   OK  token obtained, valid for 24 h. It is not stored on disk.")

    print("2. Granted permissions")
    scopes = client.granted_scopes
    if not scopes:
        print("   The response did not include scopes. Check the app configuration.")
    else:
        lectura = sorted(s for s in scopes if s.startswith("read_"))
        escritura = sorted(s for s in scopes if not s.startswith("read_"))
        print("   Read:  %s" % (", ".join(lectura) or "none"))
        print("   Write: %s" % (", ".join(escritura) or "none"))

        faltan = [s for s in NECESARIOS if s not in scopes]
        if faltan:
            print("   MISSING: %s" % ", ".join(faltan))
            print("   Add them in the Shopify Dev Dashboard, then reinstall the app.")
            return 1
        print("   OK  the pipeline's minimum permissions are granted.")

        optional_missing = [s for s in OPCIONALES if s not in scopes]
        if optional_missing:
            print("   Note: %s is only needed for inspect_products.py." % ", ".join(optional_missing))

        if escritura:
            print()
            print("   WARNING: the app has WRITE permissions this project does not use.")
            print("   The pipeline only reads. Remove them when practical.")
        if "read_all_orders" not in scopes:
            print("   Note: without read_all_orders, only the latest 60 days are visible (step 4).")

    print("3. Store connection")
    try:
        shop = client.query(SHOP_QUERY)["shop"]
    except ShopifyError as exc:
        print("   FAILED: %s" % exc)
        return 1
    print("   OK  %s (%s) · %s · %s"
          % (shop["name"], shop["myshopifyDomain"], shop["currencyCode"], shop["ianaTimezone"]))
    if client.actual_api_version:
        print("   API efectiva: %s" % client.actual_api_version)

    try:
        recent = client.query(RECENT_ORDERS_QUERY)["orders"]["edges"]
    except ShopifyError as exc:
        print("   FAILED while reading orders: %s" % exc)
        return 1
    if recent:
        print("   Latest order: %s (%s)"
              % (recent[0]["node"]["name"], recent[0]["node"]["createdAt"][:10]))
    else:
        print("   No orders in the visible window.")

    print("4. Historical access")
    try:
        oldest = client.query(OLDEST_ORDER_QUERY)["orders"]["edges"]
    except ShopifyError as exc:
        print("   FAILED: %s" % exc)
        return 1

    if not oldest:
        print("   No visible orders. Check the read_all_orders scope.")
        return 1

    first_date = oldest[0]["node"]["createdAt"][:10]
    age_days = (datetime.date.today()
                - datetime.date(*[int(p) for p in first_date.split("-")])).days
    print("   Oldest visible order: %s (%s days)" % (first_date, age_days))

    if age_days < 70:
        print()
        print("   WARNING: only the 60-day window is visible.")
        print("   The read_all_orders scope is required.")
        print("   Without it, there is no full historical view.")
        return 2

    print("   OK  full history is accessible.")
    print()
    print("Access check passed. Next: python3 src/extract.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
