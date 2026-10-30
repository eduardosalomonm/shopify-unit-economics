# Contributing to Margin Map

Thanks for improving the project. The public repository must stay safe to clone,
run and show in a portfolio: never add Shopify credentials, supplier costs, real
customer data or private dashboards.

## Before opening a pull request

1. Keep the public path dependency-free on Python 3.8+.
2. Rebuild the Excel demo and dashboard:

   ```bash
   python3 src/make_demo_workbook.py
   python3 src/run_excel_dashboard.py --output docs/index.html
   ```

3. Run the verification suite:

   ```bash
   python3 src/check_public_release.py --history
   python3 -m unittest discover -s tests -v
   node --test tests/test_*.js
   ```

4. If you change an input column, update `USER_GUIDE.md`, its workbook generator,
   parser and tests together.

Node.js 22+ is used only for browser calculation tests. Running the dashboard and
Excel workflow still requires only Python and its standard library.

## Project conventions

- Keep user-facing text and documentation in English.
- Treat raw order snapshots as immutable input; do not edit transformed output to
  force a KPI.
- Prefer a documented source for every cost, price, stock figure and discount rule.
- Keep the static dashboard self-contained so GitHub Pages can serve it without a
  build step.
- Keep publication reproducible: the same workbook must produce byte-identical
  `docs/index.html` and `docs/executive-summary.pdf`.
- Escape imported store text before inserting it into HTML and neutralise
  formula-like text before writing spreadsheet-compatible exports.

For private Shopify usage, use local `.env` and `costs.private.json` files. They
are excluded from Git by design.
