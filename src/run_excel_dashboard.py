"""Generate a local dashboard from the editable Excel input workbook."""

import argparse
import os
import subprocess
import sys

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


def main():
    parser = argparse.ArgumentParser(description="Build the dashboard from an editable Excel workbook.")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="path to the editable .xlsx workbook")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="path for the generated HTML dashboard")
    args = parser.parse_args()

    workbook_path = os.path.abspath(args.input)
    output_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(GENERATED_SNAPSHOT), exist_ok=True)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    try:
        write_inputs(workbook_path, GENERATED_COSTS, GENERATED_SNAPSHOT)
    except ExcelInputError as exc:
        print("EXCEL INPUT ERROR: %s" % exc)
        return 1

    environment = os.environ.copy()
    environment.update({"COSTS_FILE": GENERATED_COSTS, "SNAPSHOT": GENERATED_SNAPSHOT,
                        "PANEL_OUT": output_path})
    print("Excel input accepted. Calculating margins...")
    run("transform.py", environment)
    print("Running integrity checks...")
    run("checks.py", environment)
    print("Generating dashboard...")
    run("publish.py", environment)
    pdf_path = os.path.join(os.path.dirname(output_path), "executive-summary.pdf")
    print("Generating executive PDF...")
    run("export_executive_pdf.py", environment, ("--output", pdf_path))
    print("DONE: %s" % output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
