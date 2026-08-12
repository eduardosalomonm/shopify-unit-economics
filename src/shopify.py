"""Cliente minimo de la Shopify Admin GraphQL API. Solo libreria estandar.

Respeta el throttleStatus desde el principio: paginar el historico completo agota
el coste de consulta de la API y la respuesta deja de traer datos sin avisar claro.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

API_VERSION = "2025-07"
DEFAULT_TIMEOUT = 30


class ShopifyError(Exception):
    pass


def load_env(path=".env"):
    """Lee un .env sencillo (CLAVE=valor). Sin dependencias."""
    env = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip('"').strip("'")
    for key in ("SHOPIFY_STORE", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET"):
        env.setdefault(key, os.environ.get(key, ""))
    faltan = [k for k in ("SHOPIFY_STORE", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET")
              if not env.get(k)]
    if faltan:
        raise ShopifyError(
            "Faltan en .env: %s. Copia .env.example a .env y rellenalo." % ", ".join(faltan)
        )
    return env


def mint_token(store, client_id, client_secret):
    """Client credentials grant: cambia ID+secreto por un access token de 24 h.

    Desde 2026 no existen los tokens shpat_ permanentes para apps nuevas. El token
    se pide en cada ejecucion y no se guarda en disco, que es justo lo que queremos:
    lo unico que vive en .env es la credencial que puedes rotar desde el dashboard.

    Requisito: la app y la tienda deben pertenecer a la misma organizacion de Shopify.
    """
    url = "https://%s/admin/oauth/access_token" % store
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode("utf-8")
    request = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        if exc.code in (400, 401):
            raise ShopifyError(
                "No se pudo obtener el token (HTTP %s).\n"
                "Causas habituales, por orden de frecuencia:\n"
                "  · la app no esta instalada en la tienda (instalala desde el dev dashboard)\n"
                "  · el Client ID o el Secret estan mal copiados\n"
                "  · la app y la tienda no estan en la misma organizacion de Shopify\n"
                "Respuesta: %s" % (exc.code, detail)
            )
        raise ShopifyError("HTTP %s al pedir el token: %s" % (exc.code, detail))

    if "access_token" not in body:
        raise ShopifyError("Respuesta inesperada del endpoint de token: %s" % body)
    return body


class Client:
    def __init__(self, store, token):
        self.store = store
        self.token = token
        self.url = "https://%s/admin/api/%s/graphql.json" % (store, API_VERSION)
        self.last_throttle = None
        self.granted_scopes = []

    @classmethod
    def from_env(cls, path=".env"):
        """Camino normal: lee .env, pide un token fresco y devuelve el cliente listo."""
        env = load_env(path)
        grant = mint_token(env["SHOPIFY_STORE"], env["SHOPIFY_CLIENT_ID"],
                           env["SHOPIFY_CLIENT_SECRET"])
        client = cls(env["SHOPIFY_STORE"], grant["access_token"])
        client.granted_scopes = (grant.get("scope") or "").split(",")
        client.granted_scopes = [s.strip() for s in client.granted_scopes if s.strip()]
        return client

    def query(self, query, variables=None, retries=5):
        payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Access-Token": self.token,
            },
        )

        for attempt in range(retries):
            try:
                with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT) as response:
                    body = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                detail = exc.read().decode("utf-8", "replace")[:500]
                raise ShopifyError("HTTP %s: %s" % (exc.code, detail))

            errors = body.get("errors")
            if errors:
                # THROTTLED se reintenta; el resto es error real (scope, sintaxis, campo).
                codes = {
                    (e.get("extensions") or {}).get("code") for e in errors if isinstance(e, dict)
                }
                if "THROTTLED" in codes and attempt < retries - 1:
                    time.sleep(2 + 2 * attempt)
                    continue
                raise ShopifyError(json.dumps(errors, indent=2, ensure_ascii=False))

            self._respect_throttle(body)
            return body["data"]

        raise ShopifyError("Agotados los reintentos por throttling")

    def _respect_throttle(self, body):
        cost = (body.get("extensions") or {}).get("cost") or {}
        throttle = cost.get("throttleStatus")
        if not throttle:
            return
        self.last_throttle = throttle
        available = throttle.get("currentlyAvailable", 1000)
        restore = throttle.get("restoreRate", 50) or 50
        # Por debajo del 25% del cupo, esperar a recuperar en vez de chocar contra el limite.
        if available < throttle.get("maximumAvailable", 1000) * 0.25:
            time.sleep(min(10.0, (restore * 4) / restore))
