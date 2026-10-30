# Margin Map · Public release checklist

## Release scope

Publish the synthetic dashboard, editable workbook and local Python workflow.
This is not a multi-tenant SaaS or an audited real-store accounting service.
The old technical repository and URL names remain stable intentionally.

## Required checks

```bash
python3 src/check_public_release.py --history
python3 -m unittest discover -s tests -v
node --test tests/test_*.js
python3 src/run_excel_dashboard.py --output /tmp/margin-map/index.html
cmp /tmp/margin-map/index.html docs/index.html
cmp /tmp/margin-map/executive-summary.pdf docs/executive-summary.pdf
git diff --check
```

Run rebuilds from an isolated copy of the public repository, not the private
runtime. Always use the committed synthetic workbook for reproducibility; the
workbook generator intentionally rolls dates forward when called separately.

- Inspect the PDF, dashboard and screenshots visually, including mobile.
- Check that the synthetic-data notice and calculation scope remain visible.
- Exercise dates, SKU, promotions, tabs, reset, PDF and CSV downloads.
- Verify public URL without authentication and remote CI after release.
- Preserve MIT `LICENSE`, documentation and tests in source downloads.
- Keep `VERSION`, the release tag and `CHANGELOG.md` aligned.

## Packaging boundary

Package **only tracked files of this public repository** after review and commit:

```bash
git archive --format=zip --prefix=margin-map/ --output=/tmp/margin-map-source.zip HEAD
```

Do not zip the parent folder. Never include `.git`, `.env` variants (except the
placeholder `.env.example`), private cost models, databases, raw snapshots or
locally generated real-store reports. The release guard inspects tracked and
unignored worktree files plus reachable Git history, including workbook XML.
It reports finding categories, not matched values. It cannot prove the absence
of every type of PII or every secret format; review newly added binary media.

The guard blocks non-example email addresses by default. Review an intentional
public contact addition explicitly instead of silently bypassing the guard.

## Before real-store operation

- Reconcile refunds/returns and tax handling against an independent known period.
- Decide which shipping, payment, acquisition and overhead costs to add; present
  the current metric as product margin, not net profit.
- Use least-privilege credentials stored outside this public repository.
- Test connection errors, throttling, incomplete snapshots and recovery with
  a designated pilot store. Never put provider response bodies in support logs.
- Do not upload private dashboard/CSV/PDF exports as examples. Private diagnostic
  commands can print store names, order identifiers and catalogue data; keep their
  terminal output private too.

## Workbook verification

The workbook can be rebuilt for a fixed period using `--as-of YYYY-MM-DD`.
Verify per-order fees against pipeline totals, change a catalogue price and a
line's Taxable flag in a disposable copy, and check the affected outputs.
Open that copy in Excel and confirm both native charts are retained. Never use
cached values alone as proof that a formula recalculates.

## Release evidence

Use the latest test and build output for each release. This checklist describes
the required checks, not their current status. Remote CI and anonymous URL
verification must be checked after publication.
