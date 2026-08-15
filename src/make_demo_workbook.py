"""Regenerates the public demo workbook, assets/unit-economics-input.xlsx.

A binary spreadsheet committed with no source is a spreadsheet nobody can audit or
change. This script is that source: the workbook is a build artefact, and the
synthetic business it describes lives here in readable form.

The generated data deliberately looks like a real DTC store rather than a tidy
fixture, because the dashboard's job is to be judged on realistic input:

  · orders carry one to three lines, so basket size and units per order mean something
  · roughly two in five orders use a discount code, so the discount rate is not zero
  · demand has seasonality (Q4 peak, summer dip) and a growth trend
  · the trading window rolls to today, so the annual target is live rather than expired

Only the standard library is used, matching the rest of the public path.

Usage:  python3 src/make_demo_workbook.py
"""

import argparse
import datetime
import os
import random
import sys
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(BASE, "assets", "unit-economics-input.xlsx")

STORE = "Luma Vale"
DOMAIN = "lumavale.example"
CURRENCY = "EUR"
VAT = 21.0
TARGET_UNITS = 1500
TARGET_SALES = 100000
TARGET_GROSS_SALES = 83755.43

# sku, name, unit cost ex VAT, current price incl VAT, batch, stock on hand, note
PRODUCTS = [
    ("SKU-A", "Renewal Serum", 12.80, 69.90, 4000, 1180, "Hero product"),
    ("SKU-B", "Barrier Balm", 3.90, 19, 2200, 940, "Add-on product"),
    ("SKU-C", "Contour Stone", 5.40, 29, 1200, 145, "Accessory, tightest stock line"),
    ("SKU-F", "Cloud Cleanser", 6.70, 34, 1800, 690, "Daily-use cleanser"),
]

PRICE_HISTORY = [
    ("SKU-A", "2025-08-01", 64, "Synthetic launch price"),
    ("SKU-A", "2026-01-01", 69.90, "Synthetic price increase"),
    ("SKU-B", "2025-08-01", 18, "Synthetic launch price"),
    ("SKU-B", "2026-03-01", 19, "Synthetic price increase"),
    ("SKU-C", "2025-08-01", 29, "Synthetic launch price"),
    ("SKU-F", "2025-08-01", 34, "Synthetic launch price"),
]

# sku, name, price incl VAT, contents, declared solo total, declared saving, note
BUNDLES = [
    ("SKU-D", "Daily Duo", 79, "SKU-A:1|SKU-B:1", 88.90, 9.90, "Core bundle"),
    ("SKU-E", "Complete Ritual", 89, "SKU-A:1|SKU-C:1", 98.90, 9.90, "Premium bundle"),
    ("SKU-G", "Daily Reset Set", 69, "SKU-B:1|SKU-C:1|SKU-F:1", 82, 13,
     "Three-product starter bundle"),
]

# Relative demand weight per SKU when a line is generated.
MIX = [("SKU-A", 31), ("SKU-D", 21), ("SKU-E", 16), ("SKU-G", 12),
       ("SKU-B", 10), ("SKU-C", 5), ("SKU-F", 5)]

# Month-of-year demand index. Q4 gifting peak, January hangover, August dip.
SEASONALITY = {1: 0.78, 2: 0.85, 3: 0.95, 4: 1.00, 5: 1.05, 6: 0.95,
               7: 0.88, 8: 0.80, 9: 1.02, 10: 1.15, 11: 1.45, 12: 1.30}

DISCOUNTS = [("WELCOME10", 0.10, 55), ("SUMMER15", 0.15, 30), ("VIP20", 0.20, 15)]
PROMOTION_RULES = [
    ("WELCOME10", 10, "2025-08-01", "2026-12-31", "TRUE"),
    ("SUMMER15", 15, "2025-08-01", "2026-12-31", "TRUE"),
    ("VIP20", 20, "2025-08-01", "2026-12-31", "TRUE"),
]
DISCOUNTED_SHARE = 0.42          # orders that carry a code
BASE_ORDERS_PER_DAY = 2.39
GROWTH_PER_MONTH = 0.018         # gentle upward trend across the window


def price_on(sku, day):
    """Price in force that day, so the generated orders respect the price history."""
    price = None
    for history_sku, start, value, _ in sorted(PRICE_HISTORY, key=lambda row: row[1]):
        if history_sku == sku and day.isoformat() >= start:
            price = value
    if price is not None:
        return price
    for product in PRODUCTS:
        if product[0] == sku:
            return product[3]
    for bundle in BUNDLES:
        if bundle[0] == sku:
            return bundle[2]
    raise KeyError(sku)


def current_price(sku):
    """Current Catalogue price used by the editable scenario model."""
    for product in PRODUCTS:
        if product[0] == sku:
            return product[3]
    for bundle in BUNDLES:
        if bundle[0] == sku:
            return bundle[2]
    raise KeyError(sku)


def promotion_rate(code):
    return dict((name, rate) for name, rate, _weight in DISCOUNTS).get(code or "", 0.0)


def scenario_amount(row):
    """Gross sales a row produces when Orders follows current editable inputs."""
    price = current_price(row[2])
    discount = round(price * row[5] * promotion_rate(row[8]), 2)
    return round(price * row[5] - discount, 2)


def title_of(sku):
    for product in PRODUCTS:
        if product[0] == sku:
            return product[1]
    for bundle in BUNDLES:
        if bundle[0] == sku:
            return bundle[1]
    raise KeyError(sku)


def weighted(rng, options):
    total = sum(weight for _, weight in options)
    threshold = rng.uniform(0, total)
    running = 0
    for value, weight in options:
        running += weight
        if running >= threshold:
            return value
    return options[-1][0]


def build_orders(end_day, months=12, seed=11):
    """One row per order line, the same grain the pipeline consumes."""
    rng = random.Random(seed)
    start_day = end_day - datetime.timedelta(days=365)
    rows = []
    order_number = 1000
    day = start_day

    while day <= end_day:
        age_months = (day - start_day).days / 30.4
        expected = (BASE_ORDERS_PER_DAY
                    * SEASONALITY[day.month]
                    * (1 + GROWTH_PER_MONTH) ** age_months
                    * (1.18 if day.weekday() in (1, 2) else 1.0))
        orders_today = max(0, int(rng.gauss(expected, expected * 0.45)))

        for _ in range(orders_today):
            order_number += 1
            order_id = "#%d" % order_number

            # Basket: most orders are a single line, a healthy minority are not.
            line_count = 1 if rng.random() < 0.68 else (2 if rng.random() < 0.82 else 3)
            skus = []
            while len(skus) < line_count:
                candidate = weighted(rng, MIX)
                if candidate not in skus:
                    skus.append(candidate)

            code, rate = None, 0.0
            if rng.random() < DISCOUNTED_SHARE:
                code = weighted(rng, [(name, weight) for name, _, weight in DISCOUNTS])
                rate = dict((name, value) for name, value, _ in DISCOUNTS)[code]

            for sku in skus:
                quantity = 1 if rng.random() < 0.86 else 2
                # Store the original observed value alongside the live scenario
                # formula written below. This keeps the sample realistic without
                # making the editable workbook feel disconnected.
                unit_price = price_on(sku, day)
                discount = round(unit_price * quantity * rate, 2)
                rows.append([order_id, day.isoformat(), sku, title_of(sku),
                             unit_price, quantity, discount, "TRUE", code or ""])
        day += datetime.timedelta(days=1)

    # Keep the public story reproducible: the natural-looking daily order stream is
    # lightly reconciled to the documented annual gross-sales total.
    return reconcile_to_target(rows, end_day, TARGET_GROSS_SALES)


def reconcile_to_target(rows, end_day, target):
    """Add real, rule-compliant orders until the public total is exact.

    This deliberately uses only recognised promotional prices.  It matters because
    the workbook validates every allocated discount against its declared code: a
    made-up final-cent adjustment would make the sample look exact but fail the
    control it is meant to demonstrate.
    """
    current = round(sum(scenario_amount(row) for row in rows), 2)
    # Keep the reconciliation unobtrusive (a handful of low-ticket orders) and
    # ensure every amount corresponds to a published, active rule.
    candidates = []
    catalogue_prices = [(sku, name, price) for sku, name, _cost, price, *_rest in PRODUCTS]
    catalogue_prices.extend((sku, name, price) for sku, name, price, *_rest in BUNDLES)
    for sku, _name, price in catalogue_prices:
        for code, rate, _weight in [("", 0.0, 0.0)] + DISCOUNTS:
            discount = round(price * rate, 2)
            candidates.append((int(round((price - discount) * 100)), sku, price, discount, code))
    def solve(amount_to_fill):
        previous = {0: None}
        for amount in range(1, amount_to_fill + 1):
            for cents, sku, price, discount, code in candidates:
                if amount >= cents and amount - cents in previous:
                    previous[amount] = (amount - cents, sku, price, discount, code)
                    break
        return previous if amount_to_fill in previous else None

    remaining_cents = int(round((target - current) * 100))
    previous = solve(remaining_cents) if remaining_cents >= 0 else None
    if previous is None and remaining_cents < 0:
        # The rolling date window can naturally land above target. Remove enough
        # genuine lines to cross the excess, then refill the gap with recognised
        # price/code combinations rather than failing the public workbook on a
        # new day.
        excess = -remaining_cents
        removed = 0
        remove_indexes = []
        for index, row in sorted(enumerate(rows),
                                 key=lambda item: scenario_amount(item[1]),
                                 reverse=True):
            removed_cents = int(round(scenario_amount(row) * 100))
            removed += removed_cents
            remove_indexes.append(index)
            candidate = solve(removed - excess) if removed >= excess else None
            if candidate is not None:
                for remove_index in sorted(remove_indexes, reverse=True):
                    rows.pop(remove_index)
                remaining_cents = removed - excess
                previous = candidate
                break
    if previous is None:
        # When the gap is smaller than an ordinary valid order, remove one
        # existing line and replace its value through the same valid catalogue
        # prices. This preserves an exact total without fabricating a discount.
        for index, row in enumerate(rows):
            removed_cents = int(round(scenario_amount(row) * 100))
            candidate = solve(remaining_cents + removed_cents)
            if candidate is not None:
                rows.pop(index)
                remaining_cents += removed_cents
                previous = candidate
                break
    if previous is None:
        raise ValueError("Could not reconcile the demo total with valid promotion prices.")

    next_order = max(int(row[0][1:]) for row in rows) + 1
    additions = []
    amount = remaining_cents
    while amount:
        amount, sku, price, discount, code = previous[amount]
        additions.append((sku, price, discount, code))
    for position, (sku, price, discount, code) in enumerate(additions):
        day = end_day - datetime.timedelta(days=(position * 7) % 90)
        rows.append(["#%d" % next_order, day.isoformat(), sku, title_of(sku),
                     price, 1, discount, "TRUE", code])
        next_order += 1
    return rows


# ---------------------------------------------------------------------------
# Minimal xlsx writer. Inline strings only: no shared-string table to keep in sync.
# ---------------------------------------------------------------------------


class Formula:
    """An Excel formula with a cached value for the dependency-free reader.

    Excel/LibreOffice recalculates the formula when an editor changes a yellow
    input. The cached value lets the Python dashboard also read a newly generated
    starter workbook before a spreadsheet application has opened it once.
    """
    def __init__(self, expression, cached, style=None):
        self.expression = expression
        self.cached = cached
        self.style = style


class Styled:
    """A hard-coded input with an explicit Excel display style."""
    def __init__(self, value, style):
        self.value = value
        self.style = style

def escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def cell(reference, value, style=0):
    if isinstance(value, Styled):
        style, value = value.style, value.value
    if isinstance(value, Formula):
        style = value.style if value.style is not None else style
        # Excel requires text-valued formula caches to declare t="str". Readers
        # such as LibreOffice often recover without it, but Excel may refuse the
        # workbook as repaired/corrupt when formula results include labels.
        result_type = ' t="str"' if isinstance(value.cached, str) else ''
        return '<c r="%s" s="%d"%s><f>%s</f><v>%s</v></c>' % (
            reference, style, result_type, escape(value.expression.lstrip("=")),
            escape(value.cached))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return '<c r="%s" s="%d"><v>%s</v></c>' % (reference, style, value)
    if value == "":
        return '<c r="%s" s="%d"/>' % (reference, style)
    return ('<c r="%s" s="%d" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
            % (reference, style, escape(value)))


def column_letter(index):
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def sheet_xml(rows, styles=None, widths=None, hide_gridlines=False, drawing=False,
              hidden_rows=()):
    """rows: list of lists. styles: per-row style id, or a callable(row_index)."""
    body = []
    for row_index, row in enumerate(rows, start=1):
        if callable(styles):
            style = styles(row_index - 1)
        else:
            style = (styles or {}).get(row_index - 1, 0)
        cells = "".join(
            cell("%s%d" % (column_letter(column_index), row_index), value, style)
            for column_index, value in enumerate(row))
        hidden = ' hidden="1"' if row_index in hidden_rows else ''
        body.append('<row r="%d"%s>%s</row>' % (row_index, hidden, cells))

    columns = ""
    if widths:
        columns = "<cols>%s</cols>" % "".join(
            '<col min="%d" max="%d" width="%s" customWidth="1"/>' % (i + 1, i + 1, w)
            for i, w in enumerate(widths))

    relationship_namespace = (' xmlns:r="http://schemas.openxmlformats.org/'
                              'officeDocument/2006/relationships"' if drawing else '')
    drawing_reference = '<drawing r:id="rId1"/>' if drawing else ''
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"%s>'
            % relationship_namespace +
            '<sheetViews><sheetView workbookViewId="0"%s>' % (' showGridLines="0"' if hide_gridlines else '') +
            '<pane ySplit="2" topLeftCell="A3" activePane="bottomLeft" state="frozen"/>'
            '</sheetView></sheetViews>'
            '%s<sheetData>%s</sheetData>%s</worksheet>'
            % (columns, "".join(body), drawing_reference))


STYLES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="164" formatCode="€#,##0.00"/></numFmts>
<fonts count="4">
<font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="14"/><color rgb="FF1B1B2F"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
<font><i/><sz val="10"/><color rgb="FF666680"/><name val="Calibri"/></font>
</fonts>
<fills count="5">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF5A4FE8"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFFFF6CC"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFEFF5FA"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="12">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="2" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
<xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0" applyFill="1"/>
<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="0" fillId="4" borderId="0" xfId="0" applyFill="1"/>
<xf numFmtId="164" fontId="0" fillId="4" borderId="0" xfId="0" applyNumberFormat="1" applyFill="1"/>
<xf numFmtId="10" fontId="0" fillId="4" borderId="0" xfId="0" applyNumberFormat="1" applyFill="1"/>
<xf numFmtId="164" fontId="0" fillId="3" borderId="0" xfId="0" applyNumberFormat="1" applyFill="1"/>
<xf numFmtId="10" fontId="0" fillId="3" borderId="0" xfId="0" applyNumberFormat="1" applyFill="1"/>
<xf numFmtId="0" fontId="2" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
<xf numFmtId="164" fontId="2" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyNumberFormat="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''

TITLE, HEADER, INPUT, NOTE, CALCULATED, CURRENCY_CALCULATED, PERCENT_CALCULATED, CURRENCY_INPUT, PERCENT_INPUT, PRIMARY, PRIMARY_CURRENCY = range(1, 12)


def chart_title_xml(title):
    return (
        '<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r>'
        '<a:rPr lang="en-US" sz="1400" b="1"><a:solidFill>'
        '<a:srgbClr val="1B1B2F"/></a:solidFill></a:rPr><a:t>%s</a:t>'
        '</a:r></a:p></c:rich></c:tx><c:layout/><c:overlay val="0"/></c:title>'
        % escape(title))


def string_cache(values):
    points = "".join('<c:pt idx="%d"><c:v>%s</c:v></c:pt>' % (index, escape(value))
                     for index, value in enumerate(values))
    return '<c:strCache><c:ptCount val="%d"/>%s</c:strCache>' % (len(values), points)


def number_cache(values, format_code='€#,##0'):
    points = "".join('<c:pt idx="%d"><c:v>%s</c:v></c:pt>' % (index, value)
                     for index, value in enumerate(values))
    return ('<c:numCache><c:formatCode>%s</c:formatCode><c:ptCount val="%d"/>%s'
            '</c:numCache>' % (escape(format_code), len(values), points))


def sales_chart_xml(summary_metrics):
    skus = ("SKU-A", "SKU-B", "SKU-C", "SKU-F", "SKU-D", "SKU-E", "SKU-G")
    names = [summary_metrics[sku]["name"] for sku in skus]
    values = [summary_metrics[sku]["gross"] for sku in skus]
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<c:lang val="en-US"/><c:roundedCorners val="0"/><c:chart>%s'
        '<c:plotArea><c:layout/><c:barChart><c:barDir val="bar"/>'
        '<c:grouping val="clustered"/><c:varyColors val="0"/><c:ser>'
        '<c:idx val="0"/><c:order val="0"/><c:tx><c:v>Gross sales</c:v></c:tx>'
        '<c:spPr><a:solidFill><a:srgbClr val="5A4FE8"/></a:solidFill>'
        '<a:ln><a:noFill/></a:ln></c:spPr>'
        '<c:cat><c:strRef><c:f>Dashboard!$B$27:$B$33</c:f>%s</c:strRef></c:cat>'
        '<c:val><c:numRef><c:f>Dashboard!$C$27:$C$33</c:f>%s</c:numRef></c:val>'
        '</c:ser><c:dLbls><c:showLegendKey val="0"/><c:showVal val="1"/>'
        '<c:showCatName val="0"/><c:showSerName val="0"/><c:showPercent val="0"/>'
        '<c:showBubbleSize val="0"/></c:dLbls><c:gapWidth val="55"/>'
        '<c:axId val="101"/><c:axId val="102"/></c:barChart>'
        '<c:catAx><c:axId val="101"/><c:scaling><c:orientation val="maxMin"/>'
        '</c:scaling><c:delete val="0"/><c:axPos val="l"/><c:tickLblPos val="nextTo"/>'
        '<c:crossAx val="102"/><c:crosses val="autoZero"/><c:auto val="1"/>'
        '<c:lblAlgn val="ctr"/><c:lblOffset val="100"/></c:catAx>'
        '<c:valAx><c:axId val="102"/><c:scaling><c:orientation val="minMax"/>'
        '</c:scaling><c:delete val="0"/><c:axPos val="b"/><c:majorGridlines/>'
        '<c:numFmt formatCode="€#,##0" sourceLinked="0"/><c:tickLblPos val="nextTo"/>'
        '<c:crossAx val="101"/><c:crosses val="autoZero"/><c:crossBetween val="between"/>'
        '</c:valAx></c:plotArea><c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/>'
        '<c:showDLblsOverMax val="0"/></c:chart></c:chartSpace>'
        % (chart_title_xml("Gross sales by product (€)"), string_cache(names), number_cache(values)))


def target_chart_xml(gross, target):
    achieved = min(round(gross, 2), target)
    remaining = max(round(target - gross, 2), 0)
    categories = ["Achieved", "Remaining"]
    values = [achieved, remaining]
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<c:lang val="en-US"/><c:roundedCorners val="0"/><c:chart>%s'
        '<c:plotArea><c:layout/><c:doughnutChart><c:varyColors val="0"/><c:ser>'
        '<c:idx val="0"/><c:order val="0"/><c:tx><c:v>Annual target</c:v></c:tx>'
        '<c:dPt><c:idx val="0"/><c:spPr><a:solidFill><a:srgbClr val="5A4FE8"/>'
        '</a:solidFill><a:ln><a:noFill/></a:ln></c:spPr></c:dPt>'
        '<c:dPt><c:idx val="1"/><c:spPr><a:solidFill><a:srgbClr val="E6E9F2"/>'
        '</a:solidFill><a:ln><a:noFill/></a:ln></c:spPr></c:dPt>'
        '<c:cat><c:strRef><c:f>Dashboard!$A$36:$A$37</c:f>%s</c:strRef></c:cat>'
        '<c:val><c:numRef><c:f>Dashboard!$B$36:$B$37</c:f>%s</c:numRef></c:val>'
        '</c:ser><c:dLbls><c:showLegendKey val="0"/><c:showVal val="0"/>'
        '<c:showCatName val="1"/><c:showSerName val="0"/><c:showPercent val="1"/>'
        '<c:showBubbleSize val="0"/><c:showLeaderLines val="0"/></c:dLbls>'
        '<c:firstSliceAng val="270"/><c:holeSize val="68"/></c:doughnutChart>'
        '</c:plotArea><c:legend><c:legendPos val="b"/><c:layout/><c:overlay val="0"/>'
        '</c:legend><c:plotVisOnly val="0"/><c:dispBlanksAs val="gap"/>'
        '<c:showDLblsOverMax val="0"/></c:chart></c:chartSpace>'
        % (chart_title_xml("Annual gross-sales target"), string_cache(categories),
           number_cache(values)))


DASHBOARD_DRAWING = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
 <xdr:twoCellAnchor>
  <xdr:from><xdr:col>7</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>1</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>
  <xdr:to><xdr:col>14</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>17</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>
  <xdr:graphicFrame macro=""><xdr:nvGraphicFramePr><xdr:cNvPr id="2" name="Gross sales by product"/><xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr><xdr:xfrm/>
   <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rId1"/></a:graphicData></a:graphic>
  </xdr:graphicFrame><xdr:clientData/>
 </xdr:twoCellAnchor>
 <xdr:twoCellAnchor>
  <xdr:from><xdr:col>7</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>18</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>
  <xdr:to><xdr:col>14</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>34</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>
  <xdr:graphicFrame macro=""><xdr:nvGraphicFramePr><xdr:cNvPr id="3" name="Annual gross-sales target"/><xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr><xdr:xfrm/>
   <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rId2"/></a:graphicData></a:graphic>
  </xdr:graphicFrame><xdr:clientData/>
 </xdr:twoCellAnchor>
</xdr:wsDr>'''

DASHBOARD_SHEET_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/>
</Relationships>'''

DASHBOARD_DRAWING_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="../charts/chart1.xml"/>
 <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="../charts/chart2.xml"/>
</Relationships>'''


def build_workbook(path=OUTPUT, seed=11):
    today = datetime.date.today()
    end_day = today - datetime.timedelta(days=1)
    orders = build_orders(end_day, seed=seed)

    gross = sum(scenario_amount(row) for row in orders)
    units = sum(row[5] for row in orders)
    order_count = len({row[0] for row in orders})
    year = today.year

    # Cached values make the starter workbook useful immediately. Each displayed
    # result is also represented by an Excel formula below, so it updates after a
    # user changes a yellow input cell.
    product_costs = {sku: cost for sku, _name, cost, *_rest in PRODUCTS}
    bundle_costs = {
        "SKU-D": product_costs["SKU-A"] + product_costs["SKU-B"],
        "SKU-E": product_costs["SKU-A"] + product_costs["SKU-C"],
        "SKU-G": product_costs["SKU-B"] + product_costs["SKU-C"] + product_costs["SKU-F"],
    }
    sku_costs = dict(product_costs, **bundle_costs)
    summary_metrics = {}
    for sku, name in [(row[0], row[1]) for row in PRODUCTS] + [(row[0], row[1]) for row in BUNDLES]:
        sku_orders = [order for order in orders if order[2] == sku]
        sku_gross = sum(scenario_amount(order) for order in sku_orders)
        sku_units = sum(order[5] for order in sku_orders)
        sku_margin = sum(round(scenario_amount(order) / (1 + VAT / 100), 2)
                         - sku_costs[sku] * order[5] for order in sku_orders)
        summary_metrics[sku] = {
            "name": name, "gross": round(sku_gross, 2), "units": sku_units,
            "margin": round(sku_margin, 2),
            "margin_pct": round(100 * sku_margin / (sku_gross / (1 + VAT / 100)), 4)
            if sku_gross else 0,
        }
    top_sku = max(summary_metrics, key=lambda sku: summary_metrics[sku]["gross"])
    total_margin = round(sum(item["margin"] for item in summary_metrics.values()), 2)
    target_remaining = max(TARGET_SALES - gross, 0)

    readme = [
        ["%s | editable unit economics input" % STORE],
        ["Start with Dashboard. Edit yellow cells only; blue and purple cells calculate automatically."],
        [""],
        ["Sheet", "What it is for"],
        ["Dashboard", "Live, formula-driven Excel companion. The polished interactive dashboard is online."],
        ["Settings", "Store identity, VAT rate, annual targets and Scenario / Actual pricing mode."],
        ["Catalogue", "Products and bundles together. Use Type to distinguish them."],
        ["Pricing & promotions", "Price history and the discount rules that drive calculated order discounts."],
        ["Pricing planner", "Live Excel price, margin and bundle-saving checks. It updates when yellow price inputs change."],
        ["Orders", "Blue price and discount cells follow Catalogue and promotion inputs in Scenario mode."],
        [""],
        ["This copy holds %d order lines across %d orders (%d units, %s %s gross after "
         "discounts) for the 12 months to %s."
         % (len(orders), order_count, units, CURRENCY, "{:,.0f}".format(gross),
            end_day.isoformat())],
        ["Regenerate it any time with: python3 src/make_demo_workbook.py"],
    ]

    settings = [
        ["Settings"],
        ["Setting", "Value"],
        ["Store name", STORE],
        ["Store domain", DOMAIN],
        ["Currency", CURRENCY],
        ["VAT rate (%)", VAT],
        ["Target units", TARGET_UNITS],
        ["Gross sales target", TARGET_SALES],
        ["Target start", "%d-01-01" % year],
        ["Target end", "%d-12-31" % year],
        ["Pricing model", "Scenario"],
    ]

    catalogue = [["Catalogue"],
                 ["Type", "SKU", "Name", "Unit cost ex VAT", "Web price incl VAT",
                  "Batch quantity", "Stock on hand", "Bundle contents", "Declared solo total",
                  "Claimed saving", "Confirmed (TRUE/FALSE)", "Cost source", "Notes", "Bundle discount %"]]
    for sku, name, cost, price, batch, stock, note in PRODUCTS:
        catalogue.append(["Product", sku, name, Styled(cost, CURRENCY_INPUT), Styled(price, CURRENCY_INPUT), batch, stock, "", "", "", "",
                          "Synthetic supplier invoice", note, ""])
    for index, (sku, name, price, contents, solo, saving, note) in enumerate(BUNDLES, start=7):
        discount_pct = round(saving / solo, 6)
        catalogue.append(["Bundle", sku, name, "",
                          Formula("ROUND(I%d*(1-N%d),2)" % (index, index), price, CURRENCY_CALCULATED),
                          "", "", contents,
                          Formula({"SKU-D": "E3+E4", "SKU-E": "E3+E5", "SKU-G": "E4+E5+E6"}[sku], solo, CURRENCY_CALCULATED),
                          Formula("ROUND(I%d-E%d,2)" % (index, index), saving, CURRENCY_CALCULATED),
                          "TRUE", "", note, Styled(discount_pct, PERCENT_INPUT)])

    # Put editable promotion rules first: this is the live control used by the
    # blue Scenario formulas in Orders. Price history remains below as a compact
    # reference section for Actual mode, rather than mixing two concepts together.
    pricing = [
        ["Pricing & promotions"],
        ["Edit yellow promotion rules. Scenario-mode Orders discounts recalculate from these values."],
        [""],
        ["Promotion rules | live scenario inputs"],
        ["Discount code", "Discount %", "Active from", "Active to", "Status"],
    ]
    discount_data_start = len(pricing) + 1
    for row in PROMOTION_RULES:
        pricing.append(list(row))
    discount_data_end = len(pricing)
    pricing.extend([[""], ["Price history | reference for Actual mode"],
                    ["SKU", "Start date", "Price incl VAT", "Source"]])
    for row in PRICE_HISTORY:
        pricing.append(list(row))

    # Editable model: in Scenario mode, calculated order values follow current
    # Catalogue prices and live promotion rates. The adjacent yellow recorded
    # values support an Actual mode for a user importing fixed historical orders.
    promotion_codes = "'Pricing & promotions'!$A$%d:$A$%d" % (discount_data_start, discount_data_end)
    promotion_rates = "'Pricing & promotions'!$B$%d:$B$%d" % (discount_data_start, discount_data_end)
    order_sheet = [["Orders"],
                   ["Order ID", "Order date", "SKU", "Product title", "Unit price incl VAT",
                    "Recorded unit price incl VAT", "Quantity", "Discount allocated incl VAT",
                    "Revenue ex VAT", "Recorded discount incl VAT", "Taxable (TRUE/FALSE)",
                    "Discount code"]]
    for row_index, order in enumerate(orders, start=3):
        order_id, day, sku, title, recorded_price, quantity, recorded_discount, taxable, code = order
        scenario_price = current_price(sku)
        scenario_discount = round(scenario_price * quantity * promotion_rate(code), 2)
        price_formula = ("IF('Settings'!$B$11=\"Scenario\",IFERROR(INDEX('Catalogue'!$E$3:$E$100,"
                         "MATCH(C%d,'Catalogue'!$B$3:$B$100,0)),F%d),F%d)" %
                         (row_index, row_index, row_index))
        discount_formula = ("IF('Settings'!$B$11=\"Scenario\",ROUND(E%d*G%d*"
                            "IFERROR(SUMIF(%s,L%d,%s)/100,0),2),J%d)" %
                            (row_index, row_index, promotion_codes, row_index, promotion_rates, row_index))
        revenue_formula = "ROUND((E%d*G%d-H%d)/(1+'Settings'!$B$6/100),2)" % (row_index, row_index, row_index)
        order_sheet.append([
            order_id, day, sku, title,
            Formula(price_formula, scenario_price, CURRENCY_CALCULATED),
            Styled(recorded_price, CURRENCY_INPUT), quantity,
            Formula(discount_formula, scenario_discount, CURRENCY_CALCULATED),
            Formula(revenue_formula, round((scenario_price * quantity - scenario_discount) / (1 + VAT / 100), 2), CURRENCY_CALCULATED),
            Styled(recorded_discount, CURRENCY_INPUT), taxable, code,
        ])

    order_end = len(orders) + 2
    order_range = "'Orders'!$A$3:$A$%d" % order_end
    sku_range = "'Orders'!$C$3:$C$%d" % order_end
    price_range = "'Orders'!$E$3:$E$%d" % order_end
    quantity_range = "'Orders'!$G$3:$G$%d" % order_end
    discount_range = "'Orders'!$H$3:$H$%d" % order_end
    net_revenue_range = "'Orders'!$I$3:$I$%d" % order_end
    gross_formula = "SUMPRODUCT((%s*%s)-%s)" % (price_range, quantity_range, discount_range)
    lines_formula = "COUNTA(%s)" % order_range
    catalogue_rows = {sku: row for row, (sku, *_rest) in enumerate(PRODUCTS, start=3)}
    catalogue_rows.update({sku: row for row, (sku, *_rest) in enumerate(BUNDLES, start=7)})
    cost_formulas = {
        "SKU-A": "'Catalogue'!D3", "SKU-B": "'Catalogue'!D4",
        "SKU-C": "'Catalogue'!D5", "SKU-F": "'Catalogue'!D6",
        "SKU-D": "'Catalogue'!D3+'Catalogue'!D4",
        "SKU-E": "'Catalogue'!D3+'Catalogue'!D5",
        "SKU-G": "'Catalogue'!D4+'Catalogue'!D5+'Catalogue'!D6",
    }
    dashboard = [
        ["%s | Excel dashboard" % STORE],
        ["Instant workbook view: yellow Catalogue and promotion edits flow through blue calculated Orders values."],
        [""],
        ["About this workbook"],
        ["Built first for a Shopify e-commerce store, then adapted as a credential-free public demo."],
        ["This tab updates immediately in Excel. The polished interactive dashboard is published online."],
        [Styled("Online dashboard", PRIMARY), "https://eduardosalomonm.github.io/shopify-unit-economics/"],
        [""],
        ["Live commercial picture", "Value"],
        ["Gross sales", Formula(gross_formula, round(gross, 2), PRIMARY_CURRENCY)],
        ["Contribution margin", Formula("SUM(E27:E33)", total_margin, CURRENCY_CALCULATED)],
        ["Order lines", Formula(lines_formula, len(orders), PRIMARY)],
        ["Units sold", Formula("SUM(%s)" % quantity_range, units, PRIMARY)],
        [""],
        ["Annual target", "Value"],
        ["Gross sales target", Formula("'Settings'!B8", TARGET_SALES, CURRENCY_CALCULATED)],
        ["Progress", Formula("B10/B16", round(gross / TARGET_SALES, 4), PERCENT_CALCULATED)],
        ["Remaining", Formula("MAX(B16-B10,0)", target_remaining, CURRENCY_CALCULATED)],
        [""],
        ["Data-driven observations"],
        [Formula('INDEX(B27:B33,MATCH(MAX(C27:C33),C27:C33,0))&" leads scenario gross sales at "&TEXT(MAX(C27:C33),"€#,##0")&"."',
                 "%s leads scenario gross sales at €%s." % (summary_metrics[top_sku]["name"], "{:,.0f}".format(summary_metrics[top_sku]["gross"])), CALCULATED)],
        [Formula('IF(COUNTIF(\'Pricing planner\'!G6:G9,"Below cost")+COUNTIF(\'Pricing planner\'!I13:I15,"Below cost")>0,"Price warning: at least one current offer is below cost. Review Pricing planner.","All current product and bundle prices are above cost.")',
                 "All current product and bundle prices are above cost.", CALCULATED)],
        [Formula('IF(B17>=1,"Annual gross-sales target reached.",TEXT(B18,"€#,##0")&" remains to reach the annual target.")',
                 "€%s remains to reach the annual target." % "{:,.0f}".format(target_remaining), CALCULATED)],
        [""],
        ["Sales by SKU"],
        ["SKU", "Product", "Scenario gross sales", "Units", "Contribution margin", "Margin %"],
    ]
    for index, sku in enumerate(("SKU-A", "SKU-B", "SKU-C", "SKU-F", "SKU-D", "SKU-E", "SKU-G"), start=27):
        row = catalogue_rows[sku]
        item = summary_metrics[sku]
        sales_formula = "SUMPRODUCT((%s=A%d)*((%s*%s)-%s))" % (sku_range, index, price_range, quantity_range, discount_range)
        units_formula = "SUMIF(%s,A%d,%s)" % (sku_range, index, quantity_range)
        dashboard.append([
            Formula("'Catalogue'!B%d" % row, sku, CALCULATED),
            Formula("'Catalogue'!C%d" % row, item["name"], CALCULATED),
            Formula(sales_formula, item["gross"], CURRENCY_CALCULATED),
            Formula(units_formula, item["units"], CALCULATED),
            Formula("ROUND(SUMIF(%s,A%d,%s)-(%s)*D%d,2)" % (sku_range, index, net_revenue_range, cost_formulas[sku], index), item["margin"], CURRENCY_CALCULATED),
            Formula("IF(C%d=0,0,E%d/SUMIF(%s,A%d,%s))" % (index, index, sku_range, index, net_revenue_range), item["margin_pct"] / 100, PERCENT_CALCULATED),
        ])
    dashboard.extend([
        [""],
        ["Target chart data", "Value"],
        ["Achieved", Formula("MIN(B10,B16)", min(round(gross, 2), TARGET_SALES), CURRENCY_CALCULATED)],
        ["Remaining", Formula("MAX(B16-B10,0)", target_remaining, CURRENCY_CALCULATED)],
    ])

    planner = [
        ["Pricing planner | live Excel checks"],
        ["Change only yellow cells in Catalogue. This sheet updates immediately in Excel, Numbers or LibreOffice."],
        [""],
        ["Product price health"],
        ["SKU", "Product", "Unit cost ex VAT", "Web price incl VAT", "Gross profit ex VAT", "Gross margin %", "Status"],
    ]
    for row in range(3, 7):
        planner.append([Formula("'Catalogue'!B%d" % row, PRODUCTS[row - 3][0], CALCULATED),
                        Formula("'Catalogue'!C%d" % row, PRODUCTS[row - 3][1], CALCULATED),
                        Formula("'Catalogue'!D%d" % row, PRODUCTS[row - 3][2], CURRENCY_CALCULATED),
                        Formula("'Catalogue'!E%d" % row, PRODUCTS[row - 3][3], CURRENCY_CALCULATED),
                        Formula("ROUND(D%d/(1+'Settings'!B6/100)-C%d,2)" % (row + 3, row + 3),
                                round(PRODUCTS[row - 3][3] / 1.21 - PRODUCTS[row - 3][2], 2), CURRENCY_CALCULATED),
                        Formula("IF(D%d<=0,0,E%d/(D%d/(1+'Settings'!B6/100)) )" % (row + 3, row + 3, row + 3),
                                round((PRODUCTS[row - 3][3] / 1.21 - PRODUCTS[row - 3][2]) / (PRODUCTS[row - 3][3] / 1.21), 4), PERCENT_CALCULATED),
                        Formula('IF(D%d<=0,"FIX: price must be positive",IF(E%d<0,"Below cost",IF(F%d<0.5,"Low margin","Healthy")))' % (row + 3, row + 3, row + 3), "Healthy", CALCULATED)])
    planner.extend([[""], ["Bundle price health"],
                    ["SKU", "Bundle", "Bundle price incl VAT", "Buy separately", "Customer saving", "Discount %", "Product cost ex VAT", "Contribution ex VAT", "Status"]])
    for row, bundle in zip(range(7, 10), BUNDLES):
        sku, name, price, _, solo, saving, _ = bundle
        component_cost = {
            "SKU-D": PRODUCTS[0][2] + PRODUCTS[1][2],
            "SKU-E": PRODUCTS[0][2] + PRODUCTS[2][2],
            "SKU-G": PRODUCTS[1][2] + PRODUCTS[2][2] + PRODUCTS[3][2],
        }[sku]
        component_cost_formula = {
            "SKU-D": "'Catalogue'!D3+'Catalogue'!D4",
            "SKU-E": "'Catalogue'!D3+'Catalogue'!D5",
            "SKU-G": "'Catalogue'!D4+'Catalogue'!D5+'Catalogue'!D6",
        }[sku]
        planner_row = row + 6
        planner.append([Formula("'Catalogue'!B%d" % row, sku, CALCULATED),
                        Formula("'Catalogue'!C%d" % row, name, CALCULATED),
                        Formula("'Catalogue'!E%d" % row, price, CURRENCY_CALCULATED),
                        Formula("'Catalogue'!I%d" % row, solo, CURRENCY_CALCULATED),
                        Formula("'Catalogue'!J%d" % row, saving, CURRENCY_CALCULATED),
                        Formula("'Catalogue'!N%d" % row, round(saving / solo, 4), PERCENT_CALCULATED),
                        Formula(component_cost_formula, component_cost, CURRENCY_CALCULATED),
                        Formula("ROUND(C%d/(1+'Settings'!B6/100)-G%d,2)" % (planner_row, planner_row),
                                round(price / 1.21 - component_cost, 2), CURRENCY_CALCULATED),
                        Formula('IF(C%d<=0,"FIX: price must be positive",IF(H%d<0,"Below cost",IF(C%d>=D%d,"No customer saving","Healthy")))' % (planner_row, planner_row, planner_row, planner_row), "Healthy", CALCULATED)])

    def styling(input_from):
        def chooser(row_index):
            if row_index == 0:
                return TITLE
            if row_index == 1:
                return HEADER
            return INPUT if row_index >= input_from else 0
        return chooser

    def pricing_styling(row_index):
        # Two clearly separated tables: live promotion inputs first, historical
        # reference second. Formula cells keep their blue calculated style.
        if row_index in (0, 3, 9):
            return TITLE
        if row_index in (4, 10):
            return HEADER
        if row_index in (5, 6, 7):
            return INPUT
        if row_index in (11, 12, 13, 14, 15, 16):
            return CALCULATED
        return NOTE

    def readme_styling(row_index):
        if row_index == 0:
            return TITLE
        if row_index == 1:
            return NOTE
        if row_index == 3:
            return HEADER
        return 0

    def planner_styling(row_index):
        if row_index in (0, 3, 10):
            return TITLE
        if row_index in (4, 11):
            return HEADER
        return CALCULATED

    def summary_styling(row_index):
        # Let the online-dashboard address remain readable across the otherwise
        # empty row; the primary fill belongs only to its source cell.
        if row_index == 6:
            return 0
        if row_index in (0, 3, 8, 14, 19, 24):
            return TITLE
        if row_index in (25, 34):
            return HEADER
        if row_index in (1, 4, 5):
            return NOTE
        return CALCULATED

    sheets = [
        ("Dashboard", sheet_xml(dashboard, summary_styling,
                                [20, 48, 22, 14, 24, 16, 4, 14, 14, 14, 14, 14, 14, 14],
                                hide_gridlines=True, drawing=True,
                                hidden_rows=(35, 36, 37)),),
        ("Read me", sheet_xml(readme, readme_styling, [36, 92]),),
        ("Settings", sheet_xml(settings, styling(2), [26, 24]),),
        ("Catalogue", sheet_xml(catalogue, styling(2), [12, 10, 24, 16, 18, 14, 14, 32, 18, 16, 24, 26, 28, 18]),),
        ("Pricing & promotions", sheet_xml(pricing, pricing_styling, [18, 16, 16, 24, 16]),),
        ("Pricing planner", sheet_xml(planner, planner_styling, [12, 24, 20, 18, 20, 16, 20, 20, 28]),),
        ("Orders", sheet_xml(order_sheet, styling(2), [14, 14, 10, 24, 20, 26, 12, 24, 18, 24, 18, 16]),),
    ]

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
        'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
        'officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-'
        'officedocument.spreadsheetml.styles+xml"/>'
        + "".join('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/'
                  'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                  % (index + 1) for index in range(len(sheets)))
        + '<Override PartName="/xl/drawings/drawing1.xml" ContentType="application/'
          'vnd.openxmlformats-officedocument.drawing+xml"/>'
        + '<Override PartName="/xl/charts/chart1.xml" ContentType="application/'
          'vnd.openxmlformats-officedocument.drawingml.chart+xml"/>'
        + '<Override PartName="/xl/charts/chart2.xml" ContentType="application/'
          'vnd.openxmlformats-officedocument.drawingml.chart+xml"/>'
        + "</Types>")

    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')

    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        # In the OOXML schema, calcPr follows sheets. Excel for Mac is strict
        # about that order; putting it first makes the workbook unrecoverable.
        '<sheets>%s</sheets>'
        '<calcPr calcId="191029" fullCalcOnLoad="1" forceFullCalc="1"/>'
        '</workbook>'
        % "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (escape(name), i + 1, i + 1)
                  for i, (name, _) in enumerate(sheets)))

    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/'
                  'officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>'
                  % (i + 1, i + 1) for i in range(len(sheets)))
        + '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/'
          '2006/relationships/styles" Target="styles.xml"/>' % (len(sheets) + 1)
        + "</Relationships>")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/styles.xml", STYLES)
        for index, (_, xml) in enumerate(sheets):
            archive.writestr("xl/worksheets/sheet%d.xml" % (index + 1), xml)
        archive.writestr("xl/worksheets/_rels/sheet1.xml.rels", DASHBOARD_SHEET_RELS)
        archive.writestr("xl/drawings/drawing1.xml", DASHBOARD_DRAWING)
        archive.writestr("xl/drawings/_rels/drawing1.xml.rels", DASHBOARD_DRAWING_RELS)
        archive.writestr("xl/charts/chart1.xml", sales_chart_xml(summary_metrics))
        archive.writestr("xl/charts/chart2.xml", target_chart_xml(gross, TARGET_SALES))

    return {"path": path, "lines": len(orders), "orders": order_count,
            "units": units, "gross": gross, "from": (end_day
                                                     - datetime.timedelta(days=365)).isoformat(),
            "to": end_day.isoformat()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--output", default=OUTPUT)
    args = parser.parse_args()

    summary = build_workbook(args.output, args.seed)
    print("Workbook written: %s" % os.path.relpath(summary["path"], BASE))
    print("  %s to %s" % (summary["from"], summary["to"]))
    print("  %d order lines · %d orders · %d units · %s %s gross after discounts"
          % (summary["lines"], summary["orders"], summary["units"],
             CURRENCY, "{:,.0f}".format(summary["gross"])))
    print("  %.2f lines per order · %.2f units per order"
          % (summary["lines"] / summary["orders"], summary["units"] / summary["orders"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
