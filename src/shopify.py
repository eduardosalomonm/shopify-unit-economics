"""Minimal Shopify Admin GraphQL API client using only the standard library."""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

# Keep this on a supported stable release; Shopify retires versions after 12 months.
API_VERSION = "2026-07"
DEFAULT_TIMEOUT = 30


class ShopifyError(Exception):
    pass


def load_env(path=".env"):
    """Read a simple KEY=value .env file without dependencies."""
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
            "Missing from .env: %s. Copy .env.example to .env and fill it in." % ", ".join(faltan)
        )
    return env


def mint_token(store, client_id, client_secret):
    """Exchange client credentials for a 24-hour access token."""
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
        if exc.code in (400, 401):
            raise ShopifyError(
                "Could not obtain an access token (HTTP %s).\n"
                "Common causes:\n"
                "  · the app is not installed on the store\n"
                "  · the Client ID or Secret is incorrect\n"
                "  · the app and store are not in the same Shopify organization"
                % exc.code
            ) from None
        raise ShopifyError("HTTP %s while requesting the token; response details withheld." % exc.code) from None
    except (urllib.error.URLError, ValueError, OSError):
        raise ShopifyError("Token request failed or returned invalid JSON; response details withheld.") from None

    if not isinstance(body, dict) or not isinstance(body.get("access_token"), str) or not body["access_token"]:
        raise ShopifyError("Token endpoint did not return a usable access token; response details withheld.")
    return body


class Client:
    def __init__(self, store, token):
        self.store = store
        self.token = token
        self.url = "https://%s/admin/api/%s/graphql.json" % (store, API_VERSION)
        self.last_throttle = None
        self.actual_api_version = None
        self.granted_scopes = []

    @classmethod
    def from_env(cls, path=".env"):
        """Normal path: read .env, request a fresh token and return a ready client."""
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
                    self.actual_api_version = response.headers.get("X-Shopify-API-Version")
                    body = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise ShopifyError("Shopify query failed (HTTP %s); response details withheld." % exc.code) from None
            except (urllib.error.URLError, ValueError, OSError):
                raise ShopifyError("Shopify query failed or returned invalid JSON; response details withheld.") from None

            if not isinstance(body, dict):
                raise ShopifyError("Unexpected Shopify response shape; response details withheld.")
            errors = body.get("errors")
            if errors:
                # Retry throttling; other errors are real scope, syntax or field errors.
                throttled = isinstance(errors, list) and any(
                    isinstance(e, dict) and isinstance(e.get("extensions"), dict)
                    and e["extensions"].get("code") == "THROTTLED" for e in errors)
                if throttled and attempt < retries - 1:
                    time.sleep(2 + 2 * attempt)
                    continue
                raise ShopifyError("Shopify reported query errors; check scopes and query schema. Response details withheld.")

            if "data" not in body:
                raise ShopifyError("Shopify response is missing data; response details withheld.")
            self._respect_throttle(body)
            return body["data"]

        raise ShopifyError("Throttling retries exhausted")

    def _respect_throttle(self, body):
        cost = (body.get("extensions") or {}).get("cost") or {}
        throttle = cost.get("throttleStatus")
        if not throttle:
            return
        self.last_throttle = throttle
        available = throttle.get("currentlyAvailable", 1000)
        maximum = throttle.get("maximumAvailable", 1000)
        restore = throttle.get("restoreRate", 50) or 50
        # Below 25% of capacity, wait for the bucket to refill back to that
        # threshold rather than collide with the limit. restoreRate is points per
        # second, so the deficit divided by it is the wait in seconds.
        threshold = maximum * 0.25
        if available < threshold:
            time.sleep(min(10.0, (threshold - available) / restore))
