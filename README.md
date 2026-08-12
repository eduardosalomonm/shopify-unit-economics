# Shopify unit-economics pipeline

A daily pipeline that pulls real orders from the Shopify Admin API, joins them to a
declared cost model, and publishes contribution margin per SKU, bundle economics and
progress against a sales target — replacing a spreadsheet that was maintained by hand
and had drifted out of sync three separate times.

Built for a live DTC cosmetics store I co-founded, and running against its real data.
The public repo ships with **synthetic data** so the whole thing runs end to end without
credentials.

**[Live demo panel →](https://eduardosalomonm.github.io/shopify-unit-economics/)**

```bash
python3 src/make_demo_data.py    # synthetic snapshot, same shape as the real API
python3 src/transform.py         # margins   -> data/pipeline.db + data/margins.csv
python3 src/checks.py            # integrity controls, exit code 1 on error
python3 src/publish.py           # renders the HTML panel from the database
```

Python 3.8+, PyYAML the only dependency.

---

## What it caught in its first run

The point of the project is not the dashboard, it is the three things that fell out of
building it. Each one had been sitting in the business's documents for months.

**A 22% overstatement of margin, from two compounding mistakes.** Shopify records discount
codes at *order* level; the line-level `totalDiscountSet` is always `0.00`, so a naive
line-item revenue calculation silently ignores every discount ever applied. And storefront
prices are VAT-inclusive while unit costs are not, so comparing them directly inflates
margin again. Both are invisible by eye: the numbers still look plausible.

**A price history nobody had.** The flagship product was documented as having one price,
then two. Reconstructing it from orders showed **four**, and proved that a figure everyone
had written off as a documentation error was a real price genuinely charged to customers
for a month. Any historical margin analysis using today's price was wrong.

**Bundle copy that promised a discount that no longer existed.** After a price cut on the
flagship product, two bundles advertised savings of €3.50 and €3.95 against a "sum of parts"
figure that predated the cut. Their real saving had gone negative.

---

## Design decisions

**Raw snapshots are immutable.** `extract.py` writes the API response untouched and never
overwrites. Every figure on the panel can be traced back to the exact response that produced
it. When a number gets challenged, that is where the argument ends.

**Nothing is computed on an invented input.** An SKU with no declared cost does not get an
estimate — it gets no margin, and `checks.py` turns it into an error. A margin computed on a
guessed cost is worse than no margin, because it looks the same as a real one.

**Prices are compared against the price in force that day.** Validating a 2025 order against
2026's price generates false alerts, and a control that cries wolf gets ignored — at which
point it is not a control.

**Credentials are short-lived.** Since 2026 Shopify no longer issues permanent tokens for new
apps, so the client exchanges a client ID and secret for a 24-hour token on every run
(*client credentials grant*). Nothing long-lived is stored on disk, and the app is
scoped read-only.

**Everything sensitive is out of the repo.** `costs.yml` holds supplier costs and margins and
is gitignored; `costs.example.yml` is the template. Raw order data, the database and the real
panel are ignored too. The demo runs on invented figures.

## Integrity controls

| Control | Why it exists |
|---|---|
| Unknown SKU | Stops margins being computed on invented costs |
| Catalogue price vs charged price | Uses the price in force on the order date |
| Bundle pricing rules | A bundle must beat its parts, and its advertised saving must be true |
| VAT consistency | Catches SKUs taxed inconsistently across the catalogue |

The demo data has two failures planted in it, so `checks.py` visibly fires on a clean clone
rather than asking you to take the table above on trust.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Twelve tests covering the discount split and the VAT conversion — the two calculations that
were wrong in the first working version, and whose wrongness is not visible by inspection.

## Layout

```
src/shopify.py           Admin API client: auth, pagination, rate-limit handling
src/check_access.py      Verifies credentials, scopes and history depth before anything else
src/extract.py           Orders -> immutable raw snapshot, with a reconciliation gate
src/inspect_products.py  Catalogue x-ray: prices, tax treatment, new SKUs
src/transform.py         Line-level margins -> SQLite + CSV
src/checks.py            Integrity controls
src/publish.py           Renders the panel from the database
src/make_demo_data.py    Synthetic snapshot for running without a store
```

## Licence

MIT.
