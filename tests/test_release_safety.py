"""Offline regression tests for release boundaries; all payloads are fictitious."""

import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
from config import ConfigError, validate_finite_values, validate_costs
from excel_input import ExcelInputError, number, positive
from transform import build_rows, money, write_db
from publish import script_json
from project_meta import version
from shopify import Client, ShopifyError, mint_token
from check_public_release import inspect_file, inspect_worktree_path


class FiniteInputs(unittest.TestCase):
    def test_excel_numeric_fields_reject_non_finite(self):
        for value in ("NaN", "Infinity", "-Infinity", "1e9999", math.nan, math.inf, -math.inf):
            for field in ("VAT rate (%)", "Target units", "Unit cost", "Quantity", "Price", "Discount"):
                with self.subTest(value=value, field=field):
                    with self.assertRaises(ExcelInputError):
                        number(value, "Settings", 2, field)
                    with self.assertRaises(ExcelInputError):
                        positive(value, "Orders", 2, field)

    def test_optional_nested_model_numbers_rejected(self):
        for value in (math.nan, math.inf, -math.inf, 10 ** 1000):
            with self.assertRaises(ConfigError):
                validate_costs({"optional": [{"nested": value}]})
        for field in ("stock", "stock_on_hand", "precio", "quantity", "amount"):
            with self.assertRaises(ConfigError):
                validate_finite_values({field: "Infinity"})

    def test_labels_dates_zero_and_optional_blanks_remain_valid(self):
        validate_finite_values({"name": "NaN", "sku": "Infinity", "order": "1e9999",
                                "date": "2026-09-05", "zero": 0, "none": None})
        self.assertEqual(number(0, "Orders", 2, "Discount"), 0)
        self.assertIsNone(number("", "Catalogue", 2, "Stock", allow_blank=True))

    def test_snapshot_and_money_reject_non_finite(self):
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.assertRaises(ConfigError):
                build_rows({"pedidos": [{"quantity": value}]}, {})
            with self.assertRaises(ConfigError):
                money({"price": {"shopMoney": {"amount": value}}}, "price")

    def test_overflow_cannot_replace_database_or_enter_html(self):
        with patch("transform.os.remove") as remove:
            with self.assertRaises(ConfigError):
                write_db([{"margin": math.inf}])
            remove.assert_not_called()
        with self.assertRaises(ValueError):
            script_json({"margin": math.inf})


class ProviderErrorPrivacy(unittest.TestCase):
    marker = "fictional-sensitive-value"

    def assert_private(self, action):
        with self.assertRaises(ShopifyError) as result:
            action()
        self.assertNotIn(self.marker, str(result.exception))
        self.assertIsNone(result.exception.__cause__)

    def response(self, body):
        result = unittest.mock.MagicMock()
        result.__enter__.return_value.read.return_value = json.dumps(body).encode()
        result.__enter__.return_value.headers = {}
        return result

    def test_http_bodies_withheld_for_token_and_query(self):
        for status in (400, 401, 403, 500):
            for action in (lambda: mint_token("demo.myshopify.com", "fake", "fake"),
                           lambda: Client("demo.myshopify.com", "fake").query("{}")):
                error = urllib.error.HTTPError("https://example.com", status, self.marker, {}, io.BytesIO(self.marker.encode()))
                with patch("shopify.urllib.request.urlopen", side_effect=error):
                    self.assert_private(action)

    def test_missing_token_and_graphql_errors_withheld(self):
        with patch("shopify.urllib.request.urlopen", return_value=self.response({"private": self.marker})):
            self.assert_private(lambda: mint_token("demo.myshopify.com", "fake", "fake"))
        for errors in ([{"message": self.marker}], self.marker, 12):
            with patch("shopify.urllib.request.urlopen", return_value=self.response({"errors": errors})):
                self.assert_private(lambda: Client("demo.myshopify.com", "fake").query("{}"))

    def test_network_reason_withheld(self):
        with patch("shopify.urllib.request.urlopen", side_effect=urllib.error.URLError(self.marker)):
            self.assert_private(lambda: mint_token("demo.myshopify.com", "fake", "fake"))
            self.assert_private(lambda: Client("demo.myshopify.com", "fake").query("{}"))


class ReleaseGuard(unittest.TestCase):
    def test_public_version_is_semantic_and_documented(self):
        self.assertRegex(version(), r"^\d+\.\d+\.\d+$")
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "CHANGELOG.md"),
                  encoding="utf-8") as handle:
            self.assertIn("## %s " % version(), handle.read())

    def test_private_paths_rejected(self):
        for name in (".env.local", "nested/.ENV.production", "costs.private.json",
                     "Data/raw/orders.json", "Tuara/README.md", "cache.SQLITE3"):
            self.assertIn("private path", inspect_file(name, b""))
        self.assertEqual(inspect_file(".env.example", b"KEY=replace-me"), [])

    def test_office_variants_are_scanned_and_macros_are_blocked(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("xl/workbook.xml", ("shpat" + "_" + "x" * 32).encode())
        self.assertIn("provider credential", inspect_file("sample.XLSX", payload.getvalue()))
        self.assertIn("macro-enabled workbook", inspect_file("sample.xlsm", payload.getvalue()))

    def test_broken_symbolic_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "missing-link").symlink_to(root / "does-not-exist")
            self.assertEqual(inspect_worktree_path(root, "missing-link"),
                             ["symlink not allowed in public package"])

    def test_credentials_detected_without_returning_values(self):
        payload = ("shpat" + "_" + "x" * 32).encode()
        result = inspect_file("README.md", payload)
        self.assertIn("provider credential", result)
        self.assertNotIn(payload.decode(), repr(result))

    def test_non_example_email_blocked(self):
        self.assertIn("non-example email address", inspect_file("README.md", b"person" + b"@" + b"private.invalid"))
        self.assertEqual(inspect_file("README.md", b"person@example.com"), [])


if __name__ == "__main__":
    unittest.main()
