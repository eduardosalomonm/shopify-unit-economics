"""Generate a local dashboard from the editable Excel input workbook."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import webbrowser

from excel_input import ExcelInputError, write_inputs


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_INPUT = os.path.join(BASE, "assets", "unit-economics-input.xlsx")
GENERATED_COSTS = os.path.join(BASE, "data", "costs-from-excel.json")
GENERATED_SNAPSHOT = os.path.join(BASE, "data", "raw", "orders-from-excel.json")
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
    os.makedirs(os.path.dirname(GENERATED_SNAPSHOT), exist_ok=True)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    write_inputs(workbook_path, GENERATED_COSTS, GENERATED_SNAPSHOT)

    environment = os.environ.copy()
    environment.update({"COSTS_FILE": GENERATED_COSTS, "SNAPSHOT": GENERATED_SNAPSHOT,
                        "PANEL_OUT": output_path})
    print("1/4  Excel input accepted", flush=True)
    print("2/4  Calculating margins and targets...", flush=True)
    run("transform.py", environment)
    print("3/4  Running integrity checks...", flush=True)
    run("checks.py", environment)
    print("4/4  Generating dashboard and executive PDF...", flush=True)
    run("publish.py", environment)
    pdf_path = os.path.join(os.path.dirname(output_path), "executive-summary.pdf")
    run("export_executive_pdf.py", environment, ("--output", pdf_path))
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
