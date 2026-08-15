#!/bin/bash

cd "$(dirname "$0")" || exit 1
clear
echo "Luma Vale unit-economics dashboard"
echo "----------------------------------"

if command -v python3 >/dev/null 2>&1; then
  DASHBOARD_PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
  DASHBOARD_PYTHON="python"
else
  echo ""
  echo "Python 3 was not found. Install it from https://www.python.org/downloads/"
  echo "Then double-click this file again."
  echo ""
  read -r -p "Press Return to close..."
  exit 1
fi

echo "Using $DASHBOARD_PYTHON. Building the dashboard..."
if ! "$DASHBOARD_PYTHON" src/run_excel_dashboard.py; then
  echo ""
  echo "Dashboard could not be generated. The error above explains what to fix."
  echo "For the shortest instructions, open TLDR.README/README.md."
  echo ""
  read -r -p "Press Return to close..."
  exit 1
fi

if [ ! -f output/dashboard.html ]; then
  echo "Dashboard could not be generated: output/dashboard.html is missing."
  read -r -p "Press Return to close..."
  exit 1
fi

open output/dashboard.html
echo "Dashboard opened in your browser."
