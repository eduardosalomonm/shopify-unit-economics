"""Regression checks for the non-technical entry points."""

import os
import stat
import unittest
import zipfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKBOOK = os.path.join(ROOT, "assets", "unit-economics-input.xlsx")


class TestExcelDashboard(unittest.TestCase):
    def test_dashboard_contains_native_excel_charts(self):
        """A worksheet called Dashboard is not enough: it needs visible charts."""
        with zipfile.ZipFile(WORKBOOK) as archive:
            names = set(archive.namelist())
        self.assertIn("xl/drawings/drawing1.xml", names)
        self.assertIn("xl/charts/chart1.xml", names)
        self.assertIn("xl/charts/chart2.xml", names)
        self.assertIn("xl/worksheets/_rels/sheet1.xml.rels", names)


class TestLaunchers(unittest.TestCase):
    def test_tldr_entry_point_exists(self):
        guide = os.path.join(ROOT, "TLDR.README", "README.md")
        online = os.path.join(ROOT, "TLDR.README", "OPEN ONLINE DASHBOARD.html")
        self.assertTrue(os.path.isfile(guide))
        self.assertTrue(os.path.isfile(online))
        with open(guide, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("I only want to see the finished dashboard", text)
        self.assertIn("Run dashboard.command", text)
        self.assertIn("Run dashboard.bat", text)

    def test_mac_launcher_has_fallback_and_visible_failure_message(self):
        path = os.path.join(ROOT, "Run dashboard.command")
        with open(path, encoding="utf-8") as handle:
            script = handle.read()
        self.assertTrue(os.stat(path).st_mode & stat.S_IXUSR)
        self.assertIn("command -v python3", script)
        self.assertIn("command -v python", script)
        self.assertIn("--open", script)
        self.assertIn("Dashboard could not be generated", script)
        self.assertIn("Press Return", script)

    def test_windows_launcher_tries_py_and_python_and_pauses_on_failure(self):
        path = os.path.join(ROOT, "Run dashboard.bat")
        with open(path, encoding="utf-8") as handle:
            script = handle.read()
        self.assertIn("where py", script)
        self.assertIn("where python", script)
        self.assertIn("--open", script)
        self.assertIn("Dashboard could not be generated", script)
        self.assertIn("pause", script.lower())


if __name__ == "__main__":
    unittest.main()
