"""Render a decision-ready, static unit-economics dashboard from SQLite."""

import argparse
import datetime
import html
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import checks  # noqa: E402
from config import ConfigError, costs_path, load_costs  # noqa: E402
from project_meta import version  # noqa: E402
from transform import catalogo, latest_snapshot  # noqa: E402


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.abspath(os.environ.get("PIPELINE_DATA_DIR", os.path.join(BASE, "data")))
DB_PATH = os.path.join(DATA_DIR, "pipeline.db")
COSTS_PATH = costs_path()
TEMPLATE = os.path.join(BASE, "src", "panel_template.html")

# Kept separate from the compact template so the revenue-flow drawing remains
# readable. It redraws whenever the dashboard's existing period/SKU/promotion
# filters call render(), rather than being a decorative all-time graphic.
SANKEY_SCRIPT = r'''<script>
window.drawSankey=function(data){
  const svg=document.getElementById("sankey"); if(!svg)return;
  const list=Math.max(0,data.listed||0),afterDiscount=Math.max(0,data.gross||0),net=Math.max(0,data.net||0);
  const discount=Math.max(0,data.discount||0),vat=Math.max(0,afterDiscount-net),cost=Math.max(0,net-data.margin),contribution=Math.max(0,data.margin||0);
  if(!list){svg.innerHTML='<text x="380" y="135" text-anchor="middle" fill="#77809e" font-size="13">No sales in this selection</text>';return;}
  const share=value=>(100*value/list).toFixed(1)+"% of list price";
  const h=value=>Math.max(3,120*value/list),listH=h(list),afterH=h(afterDiscount),discountH=h(discount),netH=h(net),vatH=h(vat),costH=h(cost),contributionH=h(contribution);
  const sourceY=62,mainY=62,lossY=194;
  const flow=(x1,y1,height1,x2,y2,height2,color)=>{const mid=(x1+x2)/2;return '<path d="M'+x1+','+y1+' C'+mid+','+y1+' '+mid+','+y2+' '+x2+','+y2+' L'+x2+','+(y2+height2)+' C'+mid+','+(y2+height2)+' '+mid+','+(y1+height1)+' '+x1+','+(y1+height1)+' Z" fill="'+color+'" opacity=".82"/>';};
  const node=(x,y,height,color)=>'<rect x="'+x+'" y="'+y+'" width="13" height="'+height+'" rx="4" fill="'+color+'"/>';
  const label=(x,y,name,value,align)=>'<text x="'+x+'" y="'+y+'" text-anchor="'+(align||'start')+'" fill="#252a4a" font-size="11" font-weight="700">'+name+'</text><text x="'+x+'" y="'+(y+14)+'" text-anchor="'+(align||'start')+'" fill="#77809e" font-size="10">'+euro(value)+' · '+share(value)+'</text>';
  svg.setAttribute("aria-label","Revenue flow: list price, discounts, VAT, cost and contribution margin.");
  svg.innerHTML=flow(33,sourceY,afterH,195,mainY,afterH,"#5a4fe8")+flow(33,sourceY+afterH,discountH,195,lossY,discountH,"#dd655f")+flow(208,mainY,netH,375,mainY,netH,"#5a4fe8")+flow(208,mainY+netH,vatH,375,lossY,vatH,"#aeb7ca")+flow(388,mainY,contributionH,555,mainY,contributionH,"#3e9f9a")+flow(388,mainY+contributionH,costH,555,lossY,costH,"#dd655f")+node(20,sourceY,listH,"#5a4fe8")+node(195,mainY,afterH,"#5a4fe8")+node(195,lossY,discountH,"#dd655f")+node(375,mainY,netH,"#5a4fe8")+node(375,lossY,vatH,"#aeb7ca")+node(555,mainY,contributionH,"#3e9f9a")+node(555,lossY,costH,"#dd655f")+label(20,24,"List price",list)+label(195,24,"After discounts",afterDiscount)+label(375,24,"Net revenue ex VAT",net)+label(555,24,"Contribution",contribution)+label(195,270,"Discounts",discount)+label(375,270,"VAT",vat)+label(555,270,"Product cost",cost);
};
document.getElementById("period").dispatchEvent(new Event("change"));
</script>'''
OUTPUT = os.environ.get("PANEL_OUT") or os.path.join(BASE, "panel.html")
if not os.path.isabs(OUTPUT):
    OUTPUT = os.path.join(BASE, OUTPUT)


SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "MXN": "$", "COP": "$", "CHF": "CHF", "SEK": "kr"}

# Set once from the cost model's declared currency. The template's client-side
# formatter already reads {{CURRENCY_SYMBOL}}; hardcoding € here made a non-euro
# store render two different currencies on the same page.
SYMBOL = SYMBOLS["EUR"]


def currency(value, decimals=0):
    return "%s%s" % (SYMBOL, "{:,.{precision}f}".format(value or 0, precision=decimals))


def script_json(value):
    """JSON safe to embed inside a <script> block.

    SKUs, product names and discount codes come from store data, so they can carry
    the characters that would close the tag early and turn data into markup.
    """
    return (json.dumps(value, allow_nan=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def percent(value):
    return "{:.1f}%".format(value or 0)


def iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def month_sequence(first, last):
    year, month = [int(part) for part in first.split("-")]
    final_year, final_month = [int(part) for part in last.split("-")]
    result = []
    while (year, month) <= (final_year, final_month):
        result.append("%04d-%02d" % (year, month))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return result


def monthly_metrics(conn):
    rows = conn.execute("""
        SELECT substr(fecha, 1, 7), ROUND(SUM(ingreso_con_iva), 2),
               ROUND(SUM(ingreso_neto), 2), ROUND(SUM(margen_contribucion), 2),
               SUM(unidades), COUNT(DISTINCT pedido)
        FROM lineas GROUP BY 1 ORDER BY 1
    """).fetchall()
    if not rows:
        return []
    by_month = {row[0]: row[1:] for row in rows}
    metrics = []
    for month in month_sequence(rows[0][0], rows[-1][0]):
        gross, net, margin, units, orders = by_month.get(month, (0, 0, 0, 0, 0))
        metrics.append({"month": month, "label": datetime.datetime.strptime(month, "%Y-%m").strftime("%b"),
                        "gross": gross or 0, "net": net or 0, "margin": margin or 0,
                        "units": units or 0, "orders": orders or 0})
    return metrics


def daily_metrics(conn):
    rows = conn.execute("""
        SELECT fecha, pedido, sku, unidades, ingreso_con_iva, ingreso_neto,
               margen_contribucion, descuento_linea, codigos_descuento
        FROM lineas ORDER BY fecha, pedido, sku
    """).fetchall()
    return [{"date": row[0], "order": row[1], "sku": row[2], "units": row[3] or 0,
             "gross": row[4] or 0, "net": row[5] or 0,
             "margin": row[6] or 0, "discount": row[7] or 0,
             "code": row[8] or ""}
            for row in rows]


def trading_metrics(conn):
    """The commercial reading of the same rows: what was given away, and what a
    basket looks like. Both are invisible in a revenue total."""
    row = conn.execute("""
        SELECT ROUND(SUM(ingreso_con_iva), 2), ROUND(SUM(descuento_linea), 2),
               ROUND(SUM(iva_implicito), 2), ROUND(SUM(coste_total), 2),
               ROUND(SUM(margen_contribucion), 2), SUM(unidades),
               COUNT(DISTINCT pedido), COUNT(*),
               COUNT(DISTINCT CASE WHEN codigos_descuento <> '' THEN pedido END)
        FROM lineas
    """).fetchone()
    gross, discount, vat, cost, margin, units, orders, lines, discounted = [x or 0 for x in row]
    listed = gross + discount          # what the basket was worth before any code
    return {"listed": listed, "gross": gross, "discount": discount, "vat": vat,
            "cost": cost, "margin": margin, "units": units, "orders": orders,
            "lines": lines, "discounted_orders": discounted,
            "discount_rate": 100 * discount / listed if listed else 0,
            "discounted_share": 100 * discounted / orders if orders else 0,
            "units_per_order": units / orders if orders else 0,
            "lines_per_order": lines / orders if orders else 0,
            "margin_per_order": margin / orders if orders else 0}


def inventory_metrics(conn, costs, window_days=90):
    """Sell-through and weeks of cover, only for SKUs with a declared stock figure.

    Stock is never inferred from sales: a store that does not track it gets no
    inventory view rather than a fabricated one.
    """
    last = conn.execute("SELECT MAX(fecha) FROM lineas").fetchone()[0]
    if not last:
        return []
    cutoff = (datetime.date(*[int(part) for part in last.split("-")])
              - datetime.timedelta(days=window_days)).isoformat()
    recent = dict(conn.execute(
        "SELECT sku, SUM(unidades) FROM lineas WHERE fecha > ? GROUP BY sku", (cutoff,)).fetchall())
    sold = dict(conn.execute("SELECT sku, SUM(unidades) FROM lineas GROUP BY sku").fetchall())

    rows = []
    for sku, product in costs.get("productos", {}).items():
        if "stock" not in product:
            continue
        stock = float(product["stock"])
        batch = float(product.get("tirada") or 0)
        weekly = (recent.get(sku, 0) or 0) / (window_days / 7.0)
        # Bundles consume component stock, so component demand includes bundle sales.
        for bundle in (costs.get("bundles") or {}).values():
            for component in bundle.get("contiene") or []:
                if component.get("sku") == sku:
                    bundle_units = recent.get(bundle.get("sku"), 0) or 0
                    weekly += bundle_units * component.get("uds", 1) / (window_days / 7.0)
        cover = stock / weekly if weekly else None
        rows.append({
            "sku": sku, "name": product.get("nombre", sku), "stock": int(stock),
            "batch": int(batch), "sold": int(sold.get(sku, 0) or 0),
            "sell_through": 100 * (batch - stock) / batch if batch else None,
            "weekly": weekly, "cover_weeks": cover,
            "status": "critical" if cover is not None and cover < 8
                      else ("watch" if cover is not None and cover < 16 else "healthy"),
        })
    return sorted(rows, key=lambda item: (item["cover_weeks"] is None, item["cover_weeks"]))


def units_in_window(conn, costs):
    """Only what was sold inside the target window counts towards the target."""
    objective = costs.get("objetivo") or {}
    try:
        start, end = iso(objective["desde"]), iso(objective["hasta"])
    except KeyError:
        return 0
    return conn.execute(
        "SELECT COALESCE(SUM(unidades), 0) FROM lineas WHERE fecha BETWEEN ? AND ?",
        (start, end)).fetchone()[0] or 0


def pace(costs, units_sold, today=None):
    """Where the target lands if nothing changes. A target without a run rate is a wish."""
    objective = costs.get("objetivo") or {}
    try:
        start = datetime.date(*[int(p) for p in iso(objective["desde"]).split("-")])
        end = datetime.date(*[int(p) for p in iso(objective["hasta"]).split("-")])
    except (KeyError, ValueError, TypeError):
        return None
    today = today or datetime.date.today()
    total = max((end - start).days, 1)
    remaining = max((end - today).days, 0)
    target_units = float(objective.get("unidades") or 0)

    # A window that has not opened yet has no run rate to extrapolate. Clamping the
    # elapsed days to 1 would divide a whole period's sales by a single day and
    # project an absurd number, so say plainly that it has not started.
    if today < start:
        return {"start": start.isoformat(), "end": end.isoformat(),
                "remaining_days": remaining, "elapsed_days": 0, "total_days": total,
                "target_units": target_units, "units_sold": units_sold,
                "projected_units": None, "gap": None,
                "required_weekly": target_units / (total / 7.0) if total else None,
                "current_weekly": None, "on_track": None, "not_started": True}

    elapsed = max((min(today, end) - start).days, 1)
    projected = units_sold / elapsed * total
    return {"start": start.isoformat(), "end": end.isoformat(), "remaining_days": remaining,
            "elapsed_days": elapsed, "total_days": total,
            "target_units": target_units, "units_sold": units_sold,
            "projected_units": projected,
            "gap": projected - target_units,
            "required_weekly": (target_units - units_sold) / (remaining / 7.0)
                               if remaining else None,
            "current_weekly": units_sold / (elapsed / 7.0),
            "on_track": projected >= target_units, "not_started": False}


def product_metrics(conn, costs):
    rows = conn.execute("""
        SELECT sku, SUM(unidades), ROUND(SUM(ingreso_con_iva),2), ROUND(SUM(ingreso_neto),2),
               ROUND(SUM(coste_total),2), ROUND(SUM(margen_contribucion),2)
        FROM lineas GROUP BY sku ORDER BY SUM(ingreso_con_iva) DESC
    """).fetchall()
    catalogue = catalogo(costs)
    products = []
    for sku, units, gross, net, cost, margin in rows:
        products.append({"sku": sku, "name": (catalogue.get(sku) or {}).get("nombre", "Unknown SKU"),
                         "units": units or 0, "gross": gross or 0, "net": net or 0,
                         "cost": cost, "margin": margin,
                         "margin_pct": 100 * margin / net if margin is not None and net else None})
    return products


def product_rows(products):
    output = []
    for product in products:
        if product["cost"] is None or product["margin"] is None:
            output.append("<tr><td><strong>%s</strong><span>%s</span></td><td>%s</td><td>%s</td>"
                          "<td colspan='2' class='negative'>No declared cost</td></tr>" %
                          (html.escape(product["name"]), html.escape(product["sku"]), product["units"],
                           currency(product["gross"])))
            continue
        output.append("<tr><td><strong>%s</strong><span>%s</span></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" %
                      (html.escape(product["name"]), html.escape(product["sku"]), product["units"],
                       currency(product["gross"]), currency(product["margin"]), percent(product["margin_pct"])))
    return "\n".join(output)


def pace_verdict(projection):
    """One sentence a manager can act on, instead of a percentage to interpret."""
    if not projection:
        return "No target window declared."
    if projection.get("not_started"):
        return ("The target window opens on %s. It needs %.0f units a week over %d days "
                "to reach %s units."
                % (projection["start"], projection["required_weekly"] or 0,
                   projection["total_days"], "{:,.0f}".format(projection["target_units"])))
    if projection["remaining_days"] == 0:
        return ("Target window closed on %s: %s of %s units."
                % (projection["end"], "{:,.0f}".format(projection["units_sold"]),
                   "{:,.0f}".format(projection["target_units"])))
    verb = "above" if projection["on_track"] else "below"
    return ("At the current pace of %.0f units a week, the window closes near %s units: %s %s "
            "the %s target, with %d days left."
            % (projection["current_weekly"], "{:,.0f}".format(projection["projected_units"]),
               "{:,.0f}".format(abs(projection["gap"])), verb,
               "{:,.0f}".format(projection["target_units"]), projection["remaining_days"]))


def inventory_note(rows):
    if not rows:
        return ("Stock is never inferred from sales. Declare stock on hand per SKU to turn "
                "this view on.")
    tight = [row for row in rows if row["status"] == "critical"]
    if tight:
        first = tight[0]
        return ("%s runs out in about %.0f weeks at the current pace. Bundles are counted "
                "against component stock, so a bundle push shortens that further."
                % (first["name"], first["cover_weeks"]))
    return ("No SKU is inside eight weeks of cover. Bundle sales are counted against "
            "component stock, so pushing a bundle shortens cover on its parts.")


def bridge_block(trading):
    """List price -> discounts -> VAT -> cost -> contribution, to scale."""
    steps = [("List price", trading["listed"], ""),
             ("Discounts", -trading["discount"], "loss"),
             ("VAT", -trading["vat"], "tax"),
             ("Product cost", -trading["cost"], "loss"),
             ("Contribution", trading["margin"], "result")]
    scale = max([abs(value) for _, value, _ in steps] or [1])
    output = []
    for label, value, kind in steps:
        height = max(4, 100 * abs(value) / scale)
        output.append('<div class="bridge-step %s"><div class="bridge-meta"><b>%s%s</b>%s</div>'
                      '<div class="bridge-bar" style="height:%.1f%%"></div></div>'
                      % (kind, "-" if value < 0 else "", currency(abs(value)),
                         html.escape(label), height))
    return "".join(output)


def inventory_block(rows):
    if not rows:
        return ("<tr><td colspan='6'>No stock-on-hand declared. Add a "
                "<strong>Stock on hand</strong> column to the Products sheet to enable "
                "this view; stock is never inferred from sales.</td></tr>")
    output = []
    for row in rows:
        cover = ("%.1f weeks" % row["cover_weeks"]) if row["cover_weeks"] is not None else "no demand"
        width = min(100, (row["cover_weeks"] or 0) / 26 * 100)
        output.append(
            "<tr><td><strong>%s</strong><span>%s</span></td><td>%s</td><td>%s</td>"
            "<td>%.1f/week</td><td><div class='cover-bar'><i class='%s' style='width:%.0f%%'></i>"
            "</div><span>%s</span></td><td><span class='pill %s'>%s</span></td></tr>"
            % (html.escape(row["name"]), html.escape(row["sku"]), "{:,}".format(row["stock"]),
               percent(row["sell_through"]) if row["sell_through"] is not None else "n/a",
               row["weekly"], row["status"], width, cover, row["status"], row["status"]))
    return "\n".join(output)


def controls_block(result):
    counts = {}
    for control, _ in result.errores:
        counts.setdefault(control, [0, 0])[0] += 1
    for control, _ in result.avisos:
        counts.setdefault(control, [0, 0])[1] += 1
    rows = []
    for name in checks.CONTROL_NAMES:
        errors, warnings = counts.get(name, (0, 0))
        if errors:
            state = "<b class='status bad'>%d errors</b>" % errors
        elif warnings:
            state = "<b class='status warning'>%d warnings</b>" % warnings
        else:
            state = "<b class='status good'>Pass</b>"
        rows.append("<tr><td>%s</td><td>%s</td></tr>" % (name, state))
    return "\n".join(rows)


def alerts_block(result):
    if not result.errores:
        note = "%d advisory warnings" % len(result.avisos) if result.avisos else "All checks pass"
        return "<div class='integrity okay'><div><b>Data integrity</b><p>%s</p></div><span>Ready to use</span></div>" % note
    items = "".join("<li>%s</li>" % html.escape(message) for _, message in result.errores)
    return "<div class='integrity issue'><div><b>Dashboard publication blocked</b><p>Resolve these data issues before using the figures.</p><ul>%s</ul></div><span>Action needed</span></div>" % items


def main():
    parser = argparse.ArgumentParser(description="Render the static unit-economics dashboard.")
    parser.add_argument("--allow-errors", action="store_true", help="render even when integrity checks fail")
    args = parser.parse_args()
    if not os.path.exists(DB_PATH):
        raise SystemExit("data/pipeline.db does not exist. Run src/transform.py first.")
    try:
        costs = load_costs(COSTS_PATH)
    except ConfigError as exc:
        raise SystemExit("COST MODEL ERROR: %s" % exc)

    conn = sqlite3.connect(DB_PATH)
    monthly = monthly_metrics(conn)
    daily = daily_metrics(conn)
    as_of_date = (datetime.datetime.strptime(daily[-1]["date"], "%Y-%m-%d").date()
                  if daily else None)
    data_through = as_of_date.strftime("%d %b %Y") if as_of_date else "No sales data"
    products = product_metrics(conn, costs)
    gross_sales = sum(row["gross"] for row in monthly)
    net_sales = sum(row["net"] for row in monthly)
    contribution_margin = sum(row["margin"] for row in monthly)
    units = sum(row["units"] for row in monthly)
    orders = sum(row["orders"] for row in monthly)
    annual_target = float(costs.get("meta", {}).get("objetivo_ventas_brutas", gross_sales))
    target_progress = min(100, 100 * gross_sales / annual_target) if annual_target else 0
    latest = monthly[-1] if monthly else {"gross": 0}
    previous = monthly[-2] if len(monthly) > 1 else {"gross": 0}
    monthly_growth = ((latest["gross"] / previous["gross"] - 1) * 100) if previous["gross"] else 0
    bundle_skus = {bundle.get("sku") for bundle in costs.get("bundles", {}).values()}
    bundle_sales = sum(product["gross"] for product in products if product["sku"] in bundle_skus)
    trading = trading_metrics(conn)
    inventory = inventory_metrics(conn, costs)
    # A snapshot must keep the same target outlook when rebuilt later. Use the
    # latest order date as its commercial "today", not the computer clock.
    projection = pace(costs, units_in_window(conn, costs),
                      today=as_of_date or datetime.date(1970, 1, 1))
    currency_code = (costs.get("meta", {}) or {}).get("moneda", "EUR")
    global SYMBOL
    SYMBOL = SYMBOLS.get(currency_code, currency_code)
    result = checks.run_all(conn, costs)
    if result.errores and not args.allow_errors:
        conn.close()
        print("PUBLICATION BLOCKED: %d integrity errors." % len(result.errores))
        return 1
    with open(TEMPLATE, "r", encoding="utf-8") as handle:
        page = handle.read()
    replacements = {
        "{{APP_VERSION}}": html.escape(version()),
        "{{BRAND}}": html.escape(costs.get("meta", {}).get("marca", "Store")),
        "{{BRAND_UPPER}}": html.escape(costs.get("meta", {}).get("marca", "Store").upper()),
        "{{SIDEBAR_NOTE}}": ("<b>Public demo</b><br>All figures are synthetic and refresh from "
                             "the editable Excel workbook."
                             if costs.get("meta", {}).get("demo", True)
                             else "<b>Private data</b><br>Generated from this store's own orders."),
        "{{CURRENCY_CODE}}": html.escape(currency_code),
        "{{CURRENCY_SYMBOL}}": SYMBOLS.get(currency_code, currency_code),
        "{{ANNUAL_TARGET_VALUE}}": "%.2f" % annual_target,
        "{{BUNDLE_SKUS_JSON}}": script_json(sorted(sku for sku in bundle_skus if sku)),
        "{{DISCOUNT_RATE}}": percent(trading["discount_rate"]),
        "{{DISCOUNT_TOTAL}}": currency(trading["discount"]),
        "{{DISCOUNTED_SHARE}}": percent(trading["discounted_share"]),
        "{{UNITS_PER_ORDER}}": "%.2f" % trading["units_per_order"],
        "{{LINES_PER_ORDER}}": "%.2f" % trading["lines_per_order"],
        "{{MARGIN_PER_ORDER}}": currency(trading["margin_per_order"]),
        "{{CURRENT_WEEKLY}}": (("%.0f" % projection["current_weekly"])
                               if projection and projection["current_weekly"] is not None
                               else "n/a"),
        "{{REQUIRED_WEEKLY}}": (("%.0f" % projection["required_weekly"])
                                if projection and projection["required_weekly"] is not None
                                else "n/a"),
        "{{PACE_VERDICT}}": html.escape(pace_verdict(projection)),
        "{{BRIDGE}}": bridge_block(trading),
        "{{INVENTORY_ROWS}}": inventory_block(inventory),
        "{{INVENTORY_NOTE}}": html.escape(inventory_note(inventory)),
        "{{DOMAIN}}": html.escape(costs.get("meta", {}).get("dominio", "example.com")),
        # The label comes from the input rather than the computer clock. That is
        # more useful to a reviewer and makes published artefacts reproducible.
        "{{GENERATED}}": data_through,
        "{{GROSS_SALES}}": currency(gross_sales), "{{NET_SALES}}": currency(net_sales),
        "{{CONTRIBUTION_MARGIN}}": currency(contribution_margin),
        "{{MARGIN_PCT}}": percent(100 * contribution_margin / net_sales if net_sales else 0),
        "{{ORDERS}}": "{:,.0f}".format(orders), "{{AOV}}": currency(gross_sales / orders if orders else 0),
        "{{UNITS}}": "{:,.0f}".format(units), "{{TARGET}}": currency(annual_target),
        "{{TARGET_PROGRESS}}": percent(target_progress), "{{TARGET_PROGRESS_WIDTH}}": "%.1f" % target_progress,
        "{{TARGET_GAP}}": currency(max(annual_target - gross_sales, 0), 2), "{{LATEST_MONTH}}": currency(latest["gross"], 2),
        "{{LATEST_MONTH_LABEL}}": latest.get("label", ""), "{{MONTHLY_GROWTH}}": "%+.1f%%" % monthly_growth,
        "{{BUNDLE_SALES}}": currency(bundle_sales), "{{BUNDLE_SHARE}}": percent(100 * bundle_sales / gross_sales if gross_sales else 0),
        "{{PRODUCT_ROWS}}": product_rows(products), "{{CONTROLS}}": controls_block(result),
        "{{ALERTS}}": alerts_block(result), "{{SNAPSHOT}}": html.escape(os.path.basename(latest_snapshot())),
        "{{EXECUTIVE_PDF}}": "executive-summary.pdf",
        "{{MONTHLY_JSON}}": script_json(monthly),
        "{{DAILY_JSON}}": script_json(daily),
        "{{PRODUCT_JSON}}": script_json([{key: value for key, value in product.items()
                                          if key in ("sku", "name", "units", "gross", "net", "margin", "margin_pct")}
                                         for product in products]),
    }
    for key, value in replacements.items():
        page = page.replace(key, value)
    page = page.replace("</body>", SANKEY_SCRIPT + "</body>")
    output_dir = os.path.dirname(OUTPUT)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as handle:
        handle.write(page)
    conn.close()
    print("Dashboard generated: %s" % os.path.relpath(OUTPUT, BASE))
    print("  %s gross sales · %s contribution margin · %s orders" %
          (currency(gross_sales), currency(contribution_margin), "{:,.0f}".format(orders)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
