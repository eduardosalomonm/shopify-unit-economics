import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from export_executive_pdf import ellipsize, pdf_bytes  # noqa: E402


class TestExecutivePdf(unittest.TestCase):
    def test_store_labels_are_kept_inside_fixed_columns(self):
        label = ellipsize("SKU-WITH-A-LONG-NAME - A very long product name", 24)
        self.assertLessEqual(len(label), 24)
        self.assertTrue(label.endswith("..."))

    def test_pdf_writer_is_deterministic(self):
        stream = "BT /F1 10 Tf (Hello) Tj ET"
        self.assertEqual(pdf_bytes(stream), pdf_bytes(stream))
        self.assertTrue(pdf_bytes(stream).startswith(b"%PDF-1.4"))


if __name__ == "__main__":
    unittest.main()
