# User guide

For the shortest possible route, open [`TLDR.README/README.md`](TLDR.README/README.md).

## Fastest route: edit Excel, double-click, view dashboard

This is the recommended public experience. The starter workbook contains 12
rolling months of synthetic Luma Vale data (€83,755.43 gross sales after
discounts), so it works without Shopify credentials.

1. Install Python 3.8+ and verify it in Terminal, PowerShell or Command Prompt:

   ```bash
   python3 --version
   ```

2. Download or clone the repository. Open `assets/unit-economics-input.xlsx` in
   Microsoft Excel, Numbers or LibreOffice.
3. Start on **Dashboard** for the live Excel overview and native charts, then use **Read me** for the
   input instructions. Edit only the yellow cells in these sheets:

   | Sheet | What it controls |
   |---|---|
   | `Dashboard` | Formula-driven Excel companion. It updates immediately and links to the polished online dashboard. |
   | `Settings` | Store name, VAT, target window and the `Scenario` / `Actual` pricing mode |
   | `Catalogue` | Products and bundles together, with costs, current prices and stock; edit yellow values |
   | `Pricing & promotions` | Live promotion rules first, then price-history reference; edit yellow values |
   | `Pricing planner` | Live Excel price, margin and bundle checks; blue cells calculate automatically |
   | `Orders` | One sold SKU per row. Blue unit-price and discount cells automatically react to the catalogue and promotion inputs in `Scenario` mode. |

4. Save the workbook without changing its sheet names or header row.
5. Double-click the matching launcher in the project root:

   - macOS: `Run dashboard.command`
   - Windows: `Run dashboard.bat`

   The launcher validates the workbook, calculates margins, runs integrity checks,
   creates `output/dashboard.html`, then opens it in the default browser.

If Windows shows a security prompt, choose **More info → Run anyway** only after
confirming the file came from this repository. On macOS, you might need to permit
the first run in **System Settings → Privacy & Security**. The launchers now keep
the window open when something fails and explain whether Python is missing or the
Excel input needs attention; copy that complete message when asking for help.

## Choose a reporting period

Use the period menu in the dashboard for the latest 7 days, latest month or all
time. Select **Custom date range** to reveal two calendar inputs. Choose a start
and end date, then select **Apply**. Every tab, KPI, chart, promotion table and
CSV export refreshes to that selected range. The period-change card compares the
range with the immediately preceding range of the same length.

Use the **Refine the view** bar to filter any selected range by SKU, product versus
bundle, or promotion code. These filters refresh commercial KPIs, charts, product
economics, promotions and the CSV export; Inventory health remains the latest
stock-position view. 
Use **Download executive PDF** for a compact all-time summary generated alongside
the dashboard as `output/executive-summary.pdf`.

## Input rules

### Catalogue

- Use `Type` to mark every row as either `Product` or `Bundle`.
- `SKU` is required and must be unique for products; bundle SKUs are also unique.
- For products, `Unit cost ex VAT` and `Web price incl VAT` must be numbers.
- Do not estimate a cost. A missing cost intentionally blocks the dashboard.
- `Stock on hand` is optional. Fill it in to switch on the Inventory health tab,
  which reports sell-through and weeks of cover. Leave it blank and the tab explains
  what is missing: stock is never inferred from sales.
- For bundles, write components as `SKU:quantity|SKU:quantity` in `Bundle contents`.
  Example: `SKU-A:1|SKU-B:2`. `Declared solo total` and `Claimed saving` are checked
  against the current product prices.
- Change the yellow **Web price incl VAT** cells for products and the yellow
  **Bundle discount %** cells for bundles. The blue bundle price, separate-item
  total and saving cells update by themselves. Do not type over blue cells.
- Open `Pricing planner` after changing a price. It immediately labels products
  and bundles as Healthy, Low margin or Below cost. A below-cost scenario still
  builds the dashboard so its commercial effect is visible; a zero or negative
  selling price is rejected with a clear message because it is not usable data.

### Pricing & promotions

- Start with **Promotion rules | live scenario inputs**. Each yellow percentage
  drives the blue discount calculation in `Orders` immediately in Scenario mode.
- In **Price history | reference for Actual mode**, every SKU must exist as a
  `Product` in `Catalogue`. Use dates in `YYYY-MM-DD` format and add a row when
  the shop price changes.
- In the default `Scenario` mode, blue `Orders` prices follow `Catalogue` and
  blue discounts follow Promotion rules. Switch `Settings → Pricing model` to
  `Actual` to use the yellow recorded price and discount values instead.
- For every promotion rule, declare the code, percentage and active dates.
  In Scenario mode, the blue order discount automatically equals `unit price ×
  quantity × declared percentage`. In Actual mode, the dashboard validates the
  yellow recorded allocation against that rule.

### Orders

- Each row is one SKU in one order. An order containing two products needs two rows
  with the same `Order ID`.
- `Discount allocated incl VAT` is the final discount attributable to that line.
  Enter `0` if the line has no discount.
- `Discount code` is optional. If a line has both a code and an allocated discount,
  it must match the active rule in **Promotion rules**. Enter `0` and leave the code
  blank for an undiscounted line.
- Use `TRUE` or `FALSE` for `Taxable`.

## What the dashboard reports

| Metric | Read it as |
|---|---|
| Gross sales | What customers paid, after discounts, including VAT. |
| Contribution margin | Sales ex VAT minus product cost. What the trading actually leaves. |
| Discount rate | Share of list price given away, plus how many orders used a code. |
| Units and lines per order | Basket size. A store at 1.00 has no attach at all. |
| Margin per order | What one order is worth after cost and VAT. |
| Run rate vs target | Units a week now, against the pace the target needs. |
| From list price to contribution | Where the money goes: discounts, VAT, cost, what is left. |
| Weeks of cover | How long stock lasts at the last 90 days of demand, bundles included. |

## What the safeguards do

The launcher stops before publishing if it finds a blocking error:

| Check | Meaning |
|---|---|
| Unknown SKU | A sold SKU has no declared unit cost. |
| Catalogue price vs charged price | In Actual mode, an order price does not match the price history. Scenario mode follows Catalogue and reports an advisory instead. |
| Bundle pricing rules | A bundle is more expensive than its parts, its advertised saving is wrong, or it breaks the configured price rule. |
| Discount rule vs line allocation | A code is missing, inactive, outside its date range, or its percentage does not match the allocated discount. |
| VAT consistency | The same SKU was recorded both taxable and non-taxable. |

Correct the yellow input cells, save the workbook, and run the launcher again.

## Run from the command line

Use this when you want a different workbook or output file:

```bash
python3 src/run_excel_dashboard.py \
  --input assets/unit-economics-input.xlsx \
  --output output/dashboard.html
```

## Shopify mode

The Excel workflow is separate from the optional live Shopify connection. For a
private store, keep `.env` and the private cost model outside Git, run
`python3 src/check_access.py`, then extract and reconcile orders before publishing.
See [README.md](README.md#private-shopify-mode) for the commands.

## Contributors: verify before pushing

```bash
python3 src/make_demo_data.py
SNAPSHOT=data/raw/orders-demo.json python3 src/transform.py
SNAPSHOT=data/raw/orders-demo.json python3 src/checks.py
python3 src/make_demo_workbook.py
python3 src/run_excel_dashboard.py --output docs/index.html
python3 -m unittest discover -s tests -v
```

Do not commit `.env`, a private Excel workbook, real Shopify snapshots, generated
databases, local output dashboards or supplier costs.
