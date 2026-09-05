"""Create a compact, dependency-free executive PDF from the current pipeline data.

The public project intentionally has no install step. Rather than requiring a PDF
library for a single export, this writer produces a small standards-compliant PDF
using the built-in Helvetica font available in every PDF reader.
"""

import argparse
import os
import sqlite3
import sys
import textwrap

from config import costs_path, load_costs
from project_meta import version


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.abspath(os.environ.get("PIPELINE_DATA_DIR", os.path.join(BASE, "data")))
DB_PATH = os.path.join(DATA_DIR, "pipeline.db")
DEFAULT_OUTPUT = os.path.join(BASE, "output", "executive-summary.pdf")


def safe(text):
    """Keep content compatible with the built-in WinAnsi PDF font."""
    return str(text).encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def ellipsize(value, width):
    """Keep store-controlled labels inside the fixed one-page layout."""
    value = str(value)
    return value if len(value) <= width else value[:width - 3].rstrip() + "..."


def currency(value):
    return "EUR {:,.0f}".format(value or 0)


def pct(value):
    return "{:.1f}%".format(value or 0)


def text(x, y, value, size=10, colour="252A4A", bold=False):
    font = "F2" if bold else "F1"
    r, g, b = (int(colour[index:index + 2], 16) / 255 for index in (0, 2, 4))
    return "BT /%s %s Tf %.3f %.3f %.3f rg 1 0 0 1 %s %s Tm (%s) Tj ET" % (
        font, size, r, g, b, x, y, safe(value))


def rect(x, y, width, height, colour):
    r, g, b = (int(colour[index:index + 2], 16) / 255 for index in (0, 2, 4))
    return "%.3f %.3f %.3f rg %s %s %s %s re f" % (r, g, b, x, y, width, height)


def pdf_bytes(stream):
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>",
        "<< /Length %d >>\nstream\n%s\nendstream" % (len(stream.encode("latin-1")), stream),
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]
    output = ["%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"]
    offsets = [0]
    position = len(output[0].encode("latin-1"))
    for index, obj in enumerate(objects, start=1):
        body = "%d 0 obj\n%s\nendobj\n" % (index, obj)
        offsets.append(position)
        output.append(body)
        position += len(body.encode("latin-1"))
    startxref = position
    output.append("xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    output.extend("%010d 00000 n \n" % offset for offset in offsets[1:])
    output.append("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%EOF\n" % (len(objects) + 1, startxref))
    return "".join(output).encode("latin-1")


def main():
    parser = argparse.ArgumentParser(description="Export a one-page executive PDF summary.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="target PDF path")
    args = parser.parse_args()
    if not os.path.exists(DB_PATH):
        raise SystemExit("data/pipeline.db does not exist. Run the dashboard pipeline first.")

    costs = load_costs(costs_path())
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("""
        SELECT COALESCE(SUM(ingreso_con_iva), 0), COALESCE(SUM(ingreso_neto), 0),
               COALESCE(SUM(margen_contribucion), 0), COALESCE(SUM(descuento_linea), 0),
               COALESCE(SUM(unidades), 0), COUNT(DISTINCT pedido)
        FROM lineas
    """).fetchone()
    products = conn.execute("""
        SELECT sku, titulo, SUM(unidades), SUM(ingreso_con_iva), SUM(margen_contribucion), SUM(ingreso_neto)
        FROM lineas GROUP BY sku, titulo ORDER BY SUM(ingreso_con_iva) DESC LIMIT 5
    """).fetchall()
    promotions = conn.execute("""
        SELECT codigos_descuento, COUNT(DISTINCT pedido), SUM(descuento_linea), SUM(ingreso_con_iva)
        FROM lineas WHERE codigos_descuento <> '' GROUP BY codigos_descuento
        ORDER BY SUM(descuento_linea) DESC LIMIT 4
    """).fetchall()
    window = conn.execute("SELECT MIN(fecha), MAX(fecha) FROM lineas").fetchone()
    conn.close()

    gross, net, margin, discount, units, orders = total
    brand = costs.get("meta", {}).get("marca", "Store")
    target = float(costs.get("meta", {}).get("objetivo_ventas_brutas", gross))
    margin_pct = 100 * margin / net if net else 0
    discount_rate = 100 * discount / (gross + discount) if gross + discount else 0
    progress = min(100, 100 * gross / target) if target else 0
    if margin < 0:
        decision = "Trading is loss-making: review price, product cost and bundle composition before scaling demand."
    elif margin_pct < 30:
        decision = "Contribution is positive but thin at %s; protect margin before increasing promotion pressure." % pct(margin_pct)
    elif progress >= 100:
        decision = "The imported period has passed its %s gross-sales benchmark with a %s contribution margin." % (currency(target), pct(margin_pct))
    else:
        decision = "%s contribution margin on %s gross sales; %s remains to the period benchmark." % (pct(margin_pct), currency(gross), currency(max(target - gross, 0)))

    stream = []
    stream.extend([rect(0, 770, 595, 72, "5A4FE8"), text(42, 805, "Margin Map | Executive summary", 19, "FFFFFF", True),
                   text(42, 785, "%s synthetic demo - %s to %s - data through %s" %
                        (ellipsize(brand, 24), window[0], window[1], window[1]), 9, "E8E7FF")])
    stream.append(text(42, 740, "Commercial performance", 14, "252A4A", True))
    cards = [("Gross sales", currency(gross)), ("Contribution margin", currency(margin)),
             ("Orders", "{:,.0f}".format(orders)), ("Margin rate", pct(margin_pct))]
    for index, (label, value) in enumerate(cards):
        x = 42 + index * 132
        stream.extend([rect(x, 668, 120, 55, "F7F7FC"), text(x + 10, 704, label, 8, "77809E"),
                       text(x + 10, 682, value, 14, "252A4A", True)])
    stream.extend([text(42, 638, "Gross sales benchmark", 11, "252A4A", True), text(405, 638, "%s of %s" % (pct(progress), currency(target)), 9, "77809E"),
                   rect(42, 619, 510, 8, "E8EAF4"), rect(42, 619, 510 * progress / 100, 8, "5A4FE8"),
                   text(42, 594, "%s units sold | %s discount investment (%s of list price)" % ("{:,.0f}".format(units), currency(discount), pct(discount_rate)), 9, "77809E")])
    stream.extend([text(42, 552, "Top product economics", 14, "252A4A", True), text(42, 532, "PRODUCT", 8, "77809E", True), text(295, 532, "GROSS SALES", 8, "77809E", True), text(415, 532, "CONTRIBUTION", 8, "77809E", True), text(515, 532, "MARGIN", 8, "77809E", True)])
    y = 512
    for sku, name, product_units, product_gross, product_margin, product_net in products:
        rate = 100 * product_margin / product_net if product_net else 0
        stream.extend([rect(42, y - 8, 510, 1, "E6E9F3"), text(42, y, ellipsize("%s - %s" % (sku, name), 44), 9, "252A4A", True),
                       text(295, y, currency(product_gross), 9), text(415, y, currency(product_margin), 9), text(515, y, pct(rate), 9)])
        y -= 27
    stream.extend([text(42, 350, "Promotion effectiveness", 14, "252A4A", True), text(42, 330, "CODE", 8, "77809E", True), text(240, 330, "ORDERS", 8, "77809E", True), text(330, 330, "DISCOUNT", 8, "77809E", True), text(450, 330, "PROMOTION SALES", 8, "77809E", True)])
    y = 310
    for code, promo_orders, promo_discount, promo_sales in promotions:
        stream.extend([rect(42, y - 8, 510, 1, "E6E9F3"), text(42, y, ellipsize(code, 30), 9, "252A4A", True), text(240, y, "{:,.0f}".format(promo_orders), 9), text(330, y, currency(promo_discount), 9), text(450, y, currency(promo_sales), 9)])
        y -= 27
    decision_lines = textwrap.wrap(decision, width=88, break_long_words=False)[:2]
    stream.extend([rect(42, 137, 510, 90, "F0F9FA"), text(58, 202, "Data-driven decision note", 11, "197A82", True)])
    stream.extend(text(58, 183 - index * 13, line, 9) for index, line in enumerate(decision_lines))
    stream.extend([text(58, 150, "Use the interactive dashboard to filter by date, SKU, bundle and promotion code.", 9),
                   text(42, 92, "Scope: product margin after discounts and VAT, minus declared product costs; not net profit.", 8, "77809E"),
                   text(42, 78, "Excludes shipping, payment fees, acquisition and overhead; refunds require separate reconciliation.", 8, "77809E"),
                   text(42, 64, "Source: validated Excel input or Shopify snapshot. Public demo figures are synthetic, not business results.", 8, "77809E"),
                   text(42, 48, "Margin Map v%s is local decision support, not an accounting or tax reporting system." % version(), 8, "77809E")])

    output = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "wb") as handle:
        handle.write(pdf_bytes("\n".join(stream)))
    print("Executive PDF generated: %s" % os.path.relpath(output, BASE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
