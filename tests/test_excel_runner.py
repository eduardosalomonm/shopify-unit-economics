"""Exercise publication failures and isolation in the one-click workflow."""

import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import run_excel_dashboard as runner
from excel_input import ExcelInputError


class ExcelRunner(unittest.TestCase):
    def test_failed_generation_preserves_previous_deliverables(self):
        for failed_step in ("transform.py", "checks.py", "publish.py", "export_executive_pdf.py"):
            with self.subTest(step=failed_step), tempfile.TemporaryDirectory() as directory:
                html = Path(directory) / "dashboard.html"
                pdf = Path(directory) / "executive-summary.pdf"
                html.write_text("previous dashboard")
                pdf.write_bytes(b"previous PDF")

                def run(script, environment, arguments=()):
                    if script == failed_step:
                        raise SystemExit(1)
                    if script == "publish.py":
                        Path(environment["PANEL_OUT"]).write_text("new dashboard")

                with patch.object(runner, "run", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        runner.build_dashboard(runner.DEFAULT_INPUT, str(html))
                self.assertEqual(html.read_text(), "previous dashboard")
                self.assertEqual(pdf.read_bytes(), b"previous PDF")
                self.assertEqual(sorted(p.name for p in Path(directory).iterdir()),
                                 ["dashboard.html", "executive-summary.pdf"])

    def test_build_is_isolated_and_matches_published_demo(self):
        root = Path(runner.BASE)
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / "private-data"
            sentinel.mkdir()
            database = sentinel / "pipeline.db"
            database.write_bytes(b"existing private database")
            output = Path(directory) / "output" / "dashboard.html"
            with patch.dict(os.environ, {"PIPELINE_DATA_DIR": str(sentinel)}):
                with contextlib.redirect_stdout(io.StringIO()):
                    html, pdf = runner.build_dashboard(runner.DEFAULT_INPUT, str(output))
            self.assertEqual(database.read_bytes(), b"existing private database")
            self.assertEqual(Path(html).read_bytes(), (root / "docs/index.html").read_bytes())
            self.assertEqual(Path(pdf).read_bytes(), (root / "docs/executive-summary.pdf").read_bytes())
            self.assertEqual(sorted(p.name for p in output.parent.iterdir()),
                             ["dashboard.html", "executive-summary.pdf"])

    def test_output_cannot_replace_workbook_or_collide_with_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            workbook = Path(directory) / "input.xlsx"
            workbook.write_bytes(b"original workbook")
            for output in (workbook, Path(directory) / "executive-summary.pdf"):
                with self.assertRaises(ExcelInputError):
                    runner.build_dashboard(str(workbook), str(output))
            self.assertEqual(workbook.read_bytes(), b"original workbook")

    def test_file_errors_explain_recovery_without_traceback(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["run_excel_dashboard.py"]):
            with patch.object(runner, "build_dashboard", side_effect=PermissionError("Access denied")):
                with contextlib.redirect_stdout(output):
                    self.assertEqual(runner.main(), 1)
        self.assertIn("FILE ERROR", output.getvalue())
        self.assertIn("writable", output.getvalue())


if __name__ == "__main__":
    unittest.main()
