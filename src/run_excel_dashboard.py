"""Generate a local dashboard from the editable Excel input workbook."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import webbrowser

from excel_input import ExcelInputError, write_inputs


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_INPUT = os.path.join(BASE, "assets", "unit-economics-input.xlsx")
DEFAULT_OUTPUT = os.path.join(BASE, "output", "dashboard.html")


def run(script, environment, arguments=()):
    result = subprocess.run([sys.executable, os.path.join(BASE, "src", script), *arguments],
                            cwd=BASE, env=environment)
    if result.returncode:
        raise SystemExit(result.returncode)


def build_dashboard(workbook_path, output_path):
    """Validate one workbook and produce the HTML and PDF deliverables.

    This is the public workflow's interface. Launchers and command-line users do
    not need to know which internal pipeline scripts run, in what order, or which
    temporary files they exchange.
    """
    workbook_path = os.path.abspath(workbook_path)
    output_path = os.path.abspath(output_path)
    pdf_path = os.path.join(os.path.dirname(output_path), "executive-summary.pdf")
    if Path(output_path) == Path(pdf_path):
        raise ExcelInputError("Choose an HTML output filename, not executive-summary.pdf.")
    if Path(workbook_path).resolve() in (Path(output_path).resolve(), Path(pdf_path).resolve()):
        raise ExcelInputError("Output must not overwrite the input workbook. Choose a different output path.")
    output_directory = os.path.dirname(output_path)
    os.makedirs(output_directory, exist_ok=True)
    # Stage on the destination filesystem so each final replacement is atomic.
    # Every run gets its own database, regardless of inherited shell settings.
    with tempfile.TemporaryDirectory(prefix=".margin-map-", dir=output_directory) as working:
        generated_costs = os.path.join(working, "costs.json")
        generated_snapshot = os.path.join(working, "orders-from-excel.json")
        staged_html = os.path.join(working, "dashboard.html")
        staged_pdf = os.path.join(working, "executive-summary.pdf")
        write_inputs(workbook_path, generated_costs, generated_snapshot)
        environment = os.environ.copy()
        environment.update({"COSTS_FILE": generated_costs, "SNAPSHOT": generated_snapshot,
                            "PIPELINE_DATA_DIR": working, "PANEL_OUT": staged_html})
        print("1/4  Excel input accepted", flush=True)
        print("2/4  Calculating margins and targets...", flush=True)
        run("transform.py", environment)
        print("3/4  Running integrity checks...", flush=True)
        run("checks.py", environment)
        print("4/4  Generating dashboard and executive PDF...", flush=True)
        run("publish.py", environment)
        run("export_executive_pdf.py", environment, ("--output", staged_pdf))
        # A calculation, validation or rendering failure leaves both old outputs intact.
        os.replace(staged_pdf, pdf_path)
        os.replace(staged_html, output_path)
    return output_path, pdf_path


def main():
    parser = argparse.ArgumentParser(description="Build the dashboard from an editable Excel workbook.")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="path to the editable .xlsx workbook")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="path for the generated HTML dashboard")
    parser.add_argument("--open", action="store_true",
                        help="open the generated dashboard in the default browser")
    args = parser.parse_args()

    try:
        output_path, pdf_path = build_dashboard(args.input, args.output)
    except ExcelInputError as exc:
        print("EXCEL INPUT ERROR: %s" % exc)
        return 1
    except OSError as exc:
        print("FILE ERROR: %s" % exc)
        print("Check that the output folder is writable and close any app locking the output files, then retry.")
        return 1
    print("DONE: %s" % output_path)
    print("PDF:  %s" % pdf_path)
    if args.open:
        if webbrowser.open(Path(output_path).as_uri()):
            print("Dashboard opened in your browser.")
        else:
            print("Open this file manually: %s" % output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
