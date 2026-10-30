"""Rebuild a dated demo without silently moving the public trading window."""
import datetime
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from make_demo_workbook import build_workbook
from excel_input import build_inputs, sheet_paths, shared_strings, read_sheet
from transform import build_rows


class WorkbookGeneration(unittest.TestCase):
    def test_fixed_date_rebuild_and_per_order_fee_reconciliation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "demo.xlsx")
            build_workbook(path, as_of=datetime.date(2026, 10, 22))
            costs, snapshot = build_inputs(path)
            self.assertEqual(max(order["createdAt"][:10] for order in snapshot["pedidos"]), "2026-10-22")
            rows = build_rows(snapshot, costs)
            with zipfile.ZipFile(path) as archive:
                paths = sheet_paths(archive)
                dashboard = read_sheet(archive, paths["Dashboard"], shared_strings(archive))
                orders_xml = archive.read(paths["Orders"]).decode()
            self.assertAlmostEqual(float(dashboard[14][4]), sum(row["resultado_variable"] for row in rows), places=2)
            self.assertIn("SUMIFS($M$3:", orders_xml)
            self.assertIn("K3=TRUE", orders_xml)
            self.assertIn("First line of order", orders_xml)

if __name__ == "__main__":
    unittest.main()
