# Shopify unit-economics pipeline

A Python pipeline that converts Shopify orders and a declared cost model into
contribution margin by SKU, bundle-price checks and a static dashboard. It was
first built for a Shopify e-commerce store, then adapted into this
credential-free public version so anyone can explore the workflow safely.

The project is designed for two use cases:

| Mode | Best for | Data required |
|---|---|---|
| **Excel workflow** | Users who want to edit inputs and generate a dashboard with one click | Included synthetic `.xlsx` workbook |
| **Private Shopify mode** | A store owner who wants to pull live orders | Local credentials and private cost model |

**[Live demo →](https://eduardosalomonm.github.io/shopify-unit-economics/)** ·
**[60-second setup →](TLDR.README/README.md)** ·
**[User guide →](USER_GUIDE.md)** ·
**[Contributing →](CONTRIBUTING.md)**

## Excel workflow

Open [assets/unit-economics-input.xlsx](assets/unit-economics-input.xlsx), edit the
yellow cells, save, then double-click:

- macOS: `Run dashboard.command`
- Windows: `Run dashboard.bat`

It generates and opens `output/dashboard.html`. The included Luma Vale workbook
holds a rolling 12 months of synthetic DTC trading — multi-line baskets, discount
codes, seasonality, €83,755.43 gross sales and a €100,000 annual target — so anyone can evaluate the project
without credentials or packages. The generated dashboard supports quick periods,
any custom calendar range, and filters for SKU, product/bundle type and promotion
code. Its filter bar also includes a one-click executive PDF download.

The workbook starts on `Dashboard`, a formula-driven Excel companion with native
charts for sales by SKU and progress against the annual target. It shows scenario
sales, target progress, price health and product
economics immediately, and explains that the polished interactive experience is
the [published online dashboard](https://eduardosalomonm.github.io/shopify-unit-economics/).
In the default `Scenario` mode, yellow catalogue prices
and promotion rates update the blue unit-price and discount cells in `Orders`, so
the dashboard reflects price experiments after the workbook is saved. Switch
`Pricing model` to `Actual` when using fixed historical order values. Below-cost
prices publish with a visible warning; zero or negative selling prices stop with
an actionable message.

The workbook is a build artefact, not a mystery binary. Regenerate it, and roll its
trading window forward to today, with:

```bash
python3 src/make_demo_workbook.py
```

The dashboard does not publish when integrity checks fail. It detects unknown SKUs,
invalid bundle claims, discount-code allocations that do not match their declared
rules, and inconsistent VAT treatment. Price-history mismatches are also checked
in `Actual` mode; Scenario mode intentionally uses the current catalogue price.

## Public developer demo

The original JSON fixture remains available for automated verification:

```bash
python3 src/make_demo_data.py
COSTS_FILE=costs.example.json SNAPSHOT=data/raw/orders-demo.json python3 src/transform.py
COSTS_FILE=costs.example.json SNAPSHOT=data/raw/orders-demo.json python3 src/checks.py
# The public dashboard itself is rebuilt from the editable workbook so its
# targets, discount rules and visible data always match one another.
python3 src/make_demo_workbook.py
python3 src/run_excel_dashboard.py --output docs/index.html
python3 -m unittest discover -s tests -v
```

Python 3.8+ and the standard library are enough for the public path. Run
`python3 src/make_demo_data.py --with-errors` to create an explicit invalid fixture;
the checks and normal publication must fail.

## Design principles

- **Immutable raw snapshots.** Every number can be traced back to an extracted
  input file.
- **No invented costs.** An unknown SKU produces an error, not a guessed margin.
- **Historical prices.** Actual mode checks orders against the price active on that date;
  Scenario mode deliberately uses the editable current catalogue price.
- **Final discount allocations.** Shopify’s allocated line discount is used when
  available, rather than reverse-engineering discounts from totals.
- **Private data stays private.** The public workbook and demo data are synthetic.
- **Nothing is inferred that was not measured.** Stock on hand drives the inventory
  view; without it the tab says so instead of estimating stock from sales.

## Private Shopify mode

1. Copy `.env.example` to `.env`. Add the `myshopify.com` domain, client ID and
   client secret for an app owned by the same Shopify organization. Grant only
   `read_orders` and `read_products`; `read_inventory` is only for catalogue
   inspection.
2. Create a private `costs.private.json` from `costs.example.json` or use a local
   `costs.yml`. Neither is committed.
3. Verify the connection:

   ```bash
   python3 src/check_access.py
   ```

4. Extract and reconcile against an independently verified unit count:

   ```bash
   python3 src/extract.py --since 2025-01-01 --expected-units 27
   COSTS_FILE=costs.private.json python3 src/transform.py
   COSTS_FILE=costs.private.json python3 src/checks.py
   COSTS_FILE=costs.private.json python3 src/publish.py
   ```

`27` is an example only. Replace it with the independent total for the selected
window. The extractor paginates orders and line items and writes immutable snapshots.

## Project layout

```text
assets/                           Editable public Excel starter workbook
docs/                             GitHub Pages dashboard and executive-summary PDF
src/                              Python pipeline, Excel workflow, and dashboard source
tests/                            Automated calculation and interface checks
TLDR.README/                      Shortest path for non-technical reviewers
costs.example.json                Synthetic cost model for the JSON demo path
Run dashboard.command / .bat      One-click Excel workflow launchers for macOS / Windows
README.md                         Project overview and quick start
USER_GUIDE.md                     Step-by-step guide for non-technical users
CONTRIBUTING.md                   Development and verification conventions
```

The pipeline creates its working files in ignored `data/` and `output/` folders.
They are deliberately excluded from the GitHub package and are recreated when a
user runs the workflow.

## License

MIT
