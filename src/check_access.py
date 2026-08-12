"""Fase 0, paso 3: verificar el acceso antes de escribir nada mas.

Comprueba, en este orden:
  1. Que el client credentials grant funciona y devuelve un token.
  2. Que los permisos concedidos incluyen los que necesita el pipeline.
  3. Que la tienda responde y es la correcta.
  4. Si el historico completo es accesible o solo la ventana de 60 dias.

El punto 4 es el que decide si A1 tiene sentido: sin los 14 meses de historico,
el panel no puede reconstruir las 27 unidades ni el contador de 100.

Uso:  python3 src/check_access.py
"""

import datetime
import sys

from shopify import Client, ShopifyError

NECESARIOS = ["read_orders", "read_products", "read_inventory"]

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
    print("1. Obtener token (client credentials grant)")
    try:
        client = Client.from_env()
    except ShopifyError as exc:
        print("   FALLO.")
        print("   %s" % exc)
        return 1
    print("   OK  token obtenido, valido 24 h. No se guarda en disco.")

    print("2. Permisos concedidos")
    scopes = client.granted_scopes
    if not scopes:
        print("   La respuesta no trajo scopes. Revisa la configuracion de la app.")
    else:
        lectura = sorted(s for s in scopes if s.startswith("read_"))
        escritura = sorted(s for s in scopes if not s.startswith("read_"))
        print("   Lectura:   %s" % (", ".join(lectura) or "ninguno"))
        print("   Escritura: %s" % (", ".join(escritura) or "ninguno"))

        faltan = [s for s in NECESARIOS if s not in scopes]
        if faltan:
            print("   FALTAN: %s" % ", ".join(faltan))
            print("   Anadelos en el dev dashboard, en los scopes de la app, y reinstala.")
            return 1
        print("   OK  estan los tres que necesita el pipeline.")

        if escritura:
            print()
            print("   AVISO: la app tiene permisos de ESCRITURA que este proyecto no usa.")
            print("   El pipeline solo lee. Quitalos cuando puedas.")
        if "read_all_orders" not in scopes:
            print("   Nota: sin read_all_orders solo se ven los ultimos 60 dias (paso 4).")

    print("3. Conexion con la tienda")
    try:
        shop = client.query(SHOP_QUERY)["shop"]
    except ShopifyError as exc:
        print("   FALLO: %s" % exc)
        return 1
    print("   OK  %s (%s) · %s · %s"
          % (shop["name"], shop["myshopifyDomain"], shop["currencyCode"], shop["ianaTimezone"]))

    try:
        recent = client.query(RECENT_ORDERS_QUERY)["orders"]["edges"]
    except ShopifyError as exc:
        print("   FALLO al leer pedidos: %s" % exc)
        return 1
    if recent:
        print("   Ultimo pedido: %s (%s)"
              % (recent[0]["node"]["name"], recent[0]["node"]["createdAt"][:10]))
    else:
        print("   Sin pedidos en la ventana visible.")

    print("4. Alcance del historico")
    try:
        oldest = client.query(OLDEST_ORDER_QUERY)["orders"]["edges"]
    except ShopifyError as exc:
        print("   FALLO: %s" % exc)
        return 1

    if not oldest:
        print("   Sin pedidos visibles. Revisa el scope read_all_orders.")
        return 1

    first_date = oldest[0]["node"]["createdAt"][:10]
    age_days = (datetime.date.today()
                - datetime.date(*[int(p) for p in first_date.split("-")])).days
    print("   Pedido mas antiguo visible: %s (%s dias)" % (first_date, age_days))

    if age_days < 70:
        print()
        print("   AVISO: solo se ve la ventana de 60 dias.")
        print("   Hace falta el scope read_all_orders.")
        print("   Sin el no hay historico de 14 meses y el panel pierde su sentido.")
        return 2

    print("   OK  el historico completo es accesible.")
    print()
    print("Fase 0 superada. Siguiente: python3 src/extract.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
