# Changelog

All notable public changes to Margin Map are recorded here.

## 1.2.0 - 2026-10-31

- Reconciled Excel payment fees with per-order rounding in the pipeline, made
  line revenue respect Taxable, and improved summary column widths.
- Added `--as-of YYYY-MM-DD` for reproducible workbook generation.

- Reject fractional counts, negative stock, unknown catalogue types, duplicate
  bundle/product SKUs and promotion codes, and impossible line discounts before
  they can silently change imported results.

- Added a browser-only Scenario lab for price, volume and supplier-cost experiments,
  including the volume needed to preserve product margin and explicit assumptions.
- Fixed sales charts hiding negative results after variable costs. Losses now sit
  below a visible zero line; individual points expose their values.
- Included empty calendar buckets between recorded sales and year labels on monthly charts.
- Added executable JavaScript checks alongside Python verification in CI.

## 1.1.0 - 2026-10-23

- Added optional variable costs (fulfilment, shipping charged, payment fees and monthly
  advertising) and a result after variable costs across the overview, products,
  promotions, trend chart, CSV export, insights and executive PDF.
- Added the same breakdown to the workbook's live `Dashboard` sheet.
- Added a break-even discount per product and catalogue bundle.
- Added a variable-cost allocation control that reports advertising with no sales to land on.
- Excel builds now run in an isolated temporary folder and keep the previous report on failure.

## 1.0.0 - 2026-09-05

- Introduced the Margin Map product name while keeping Luma Vale as the synthetic demo store.
- Added an editable Excel workflow, formula-driven workbook dashboard and one-click launchers.
- Added interactive date, SKU, product-type and promotion filters across six dashboard views.
- Added data-driven insights, a revenue-flow Sankey diagram and an executive PDF export.
- Added finite-number validation, provider-error redaction and a public-release privacy guard.
- Clarified that contribution means product margin and excludes shipping, payment fees, acquisition and overhead.
