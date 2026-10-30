"""Invalid edits must fail before they silently change sales or the catalogue."""
import copy
import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from excel_input import ExcelInputError, build_inputs, load_workbook, whole_number


class ExcelValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sheets = load_workbook(os.path.join(ROOT, "assets", "unit-economics-input.xlsx"))

    def changed(self, sheet, header, field, value, row_offset=1):
        sheets = copy.deepcopy(self.sheets)
        rows = sheets[sheet]
        index = next(i for i, row in enumerate(rows) if header in row and field in row)
        rows[index + row_offset][rows[index].index(field)] = value
        return sheets

    def rejects(self, sheets, message):
        with patch("excel_input.load_workbook", return_value=sheets):
            with self.assertRaisesRegex(ExcelInputError, message):
                build_inputs("unused.xlsx")

    def test_discrete_counts_never_truncate_or_accept_negative_stock(self):
        for value in (1.5, -1, "NaN", "Infinity"):
            with self.subTest(value=value), self.assertRaises(ExcelInputError):
                whole_number(value, "Orders", 3, "Quantity")
        self.assertEqual(whole_number("0", "Catalogue", 3, "Stock"), 0)
        self.assertEqual(whole_number("2.0", "Orders", 3, "Quantity", 1), 2)
        self.rejects(self.changed("Orders", "Order ID", "Quantity", 1.5), "whole number")
        self.rejects(self.changed("Catalogue", "Type", "Stock on hand", -1), "whole number")

    def test_invalid_catalogue_type_cannot_disappear(self):
        self.rejects(self.changed("Catalogue", "Type", "Type", "Prodcut"), "Type must")

    def test_bundle_cannot_replace_an_existing_sku(self):
        self.rejects(self.changed("Catalogue", "Type", "SKU", "SKU-A", 5), "duplicate SKU")
        self.rejects(self.changed("Catalogue", "Type", "SKU", "SKU-D", 6), "duplicate SKU")

    def test_promotion_codes_cannot_overwrite_an_existing_rule(self):
        rows = self.sheets["Pricing & promotions"]
        index = next(i for i, row in enumerate(rows) if "Discount code" in row)
        code = rows[index+1][rows[index].index("Discount code")]
        self.rejects(self.changed("Pricing & promotions", "Discount code", "Discount code", code, 2), "duplicate code")

    def test_impossible_discount_fails_at_import(self):
        for discount in (-1, 1000000):
            self.rejects(self.changed("Orders", "Order ID", "Discount allocated incl VAT", discount), "Discount must")

if __name__ == "__main__":
    unittest.main()
