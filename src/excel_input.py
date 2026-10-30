"""Read the editable Excel workbook without adding a runtime dependency.

The starter workbook is an .xlsx file, which is a ZIP archive of XML files. This
small reader intentionally supports the simple typed cells used by the workbook:
text, numbers and booleans. It keeps the public project runnable with Python's
standard library only.
"""

import json
import math
import re
import xml.etree.ElementTree as ET
import zipfile


MAIN_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
OFFICE_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


class ExcelInputError(Exception):
    """The workbook cannot safely be converted into pipeline input."""


def column_index(reference):
    letters = re.match(r"([A-Z]+)", reference).group(1)
    value = 0
    for letter in letters:
        value = value * 26 + ord(letter) - 64
    return value - 1


def shared_strings(archive):
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(node.itertext()) for node in root.findall(MAIN_NS + "si")]


def sheet_paths(archive):
    root = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        relationship.attrib["Id"]: relationship.attrib["Target"]
        for relationship in relationships.findall(OFFICE_REL_NS + "Relationship")
    }
    result = {}
    for sheet in root.findall(MAIN_NS + "sheets/" + MAIN_NS + "sheet"):
        relation_id = sheet.attrib[REL_NS + "id"]
        target = targets[relation_id].lstrip("/")
        result[sheet.attrib["name"]] = target if target.startswith("xl/") else "xl/" + target
    return result


def read_sheet(archive, path, strings):
    root = ET.fromstring(archive.read(path))
    rows = []
    for row in root.findall(".//" + MAIN_NS + "sheetData/" + MAIN_NS + "row"):
        cells = {}
        for cell in row.findall(MAIN_NS + "c"):
            cell_type = cell.attrib.get("t")
            value = cell.find(MAIN_NS + "v")
            if cell_type == "inlineStr":
                inline = cell.find(MAIN_NS + "is")
                raw = "".join(inline.itertext()) if inline is not None else ""
            elif value is None:
                raw = ""
            else:
                raw = value.text or ""
                if cell_type == "s":
                    raw = strings[int(raw)]
                elif cell_type == "b":
                    raw = "TRUE" if raw == "1" else "FALSE"
            cells[column_index(cell.attrib["r"])] = raw
        if cells:
            rows.append([cells.get(index, "") for index in range(max(cells) + 1)])
    return rows


def table(rows, sheet_name, headers, optional=()):
    """Optional columns are read when present and ignored when absent, so a workbook
    written before a column existed keeps working."""
    actual = next((row for row in rows if all(header in row for header in headers)), None)
    if actual is None:
        raise ExcelInputError("%s is missing columns: %s." % (sheet_name, ", ".join(headers)))
    headers = list(headers) + [name for name in optional if name in actual]
    positions = {header: actual.index(header) for header in headers}
    result = []
    for row in rows[rows.index(actual) + 1:]:
        # A blank row ends a table. This lets one clear input sheet contain small,
        # separate tables without their rows bleeding into one another.
        if not any(str(value).strip() for value in row):
            break
        item = {header: row[positions[header]] if positions[header] < len(row) else ""
                for header in headers}
        if any(str(value).strip() for value in item.values()):
            result.append(item)
    return result


def number(value, sheet_name, row_number, field, allow_blank=False):
    if str(value).strip() == "" and allow_blank:
        return None
    try:
        result = float(value)
        if not math.isfinite(result):
            raise ValueError
        return result
    except (TypeError, ValueError, OverflowError):
        raise ExcelInputError("%s row %d: %s must be a finite number." % (sheet_name, row_number, field)) from None


def positive(value, sheet_name, row_number, field, allow_blank=False):
    """Fail before the calculation pipeline with an actionable Excel edit message."""
    result = number(value, sheet_name, row_number, field, allow_blank)
    if result is not None and result <= 0:
        raise ExcelInputError(
            "%s row %d: %s must be greater than zero. Use a positive selling price, "
            "then check the Pricing planner sheet before rebuilding the dashboard."
            % (sheet_name, row_number, field))
    return result


def truth(value, sheet_name, row_number, field):
    normalized = str(value).strip().upper()
    if normalized in ("TRUE", "YES", "1"):
        return True
    if normalized in ("FALSE", "NO", "0"):
        return False
    raise ExcelInputError("%s row %d: %s must be TRUE or FALSE." %
                          (sheet_name, row_number, field))


def whole_number(value, sheet_name, row_number, field, minimum=0):
    result = number(value, sheet_name, row_number, field)
    if result < minimum or not result.is_integer():
        raise ExcelInputError("%s row %d: %s must be a whole number of at least %d." %
                              (sheet_name, row_number, field, minimum))
    return int(result)


def contents(value, row_number):
    result = []
    for component in str(value).split("|"):
        try:
            sku, quantity = component.strip().split(":", 1)
            quantity = int(quantity)
        except ValueError:
            raise ExcelInputError("Bundles row %d: Contents must use SKU:quantity pairs." % row_number)
        if not sku or quantity <= 0:
            raise ExcelInputError("Bundles row %d: each component needs a SKU and positive quantity." % row_number)
        result.append({"sku": sku.strip(), "uds": quantity})
    return result


def money(amount):
    return {"shopMoney": {"amount": "%.2f" % amount, "currencyCode": "EUR"}}


VARIABLE_SETTINGS = {
    "Fulfilment cost per order ex VAT": "logistica_por_pedido",
    "Payment fee (%)": "comision_pago_pct",
    "Payment fee per order": "comision_pago_fija",
}
SHIPPING_SETTING = "Shipping charged per order incl VAT"
ADVERTISING_HEADERS = ["Month (YYYY-MM)", "Advertising spend ex VAT"]


def variable_cost_inputs(settings, settings_rows):
    """Optional Settings that move the dashboard from product margin towards profit.

    Every value may be left blank. When none is filled in and no advertising is
    listed, the workbook produces exactly the product-margin dashboard it did before.
    """
    model = {}
    for label, field in VARIABLE_SETTINGS.items():
        value = number(settings.get(label, ""), "Settings", 0, label, allow_blank=True)
        if value is not None:
            if value < 0 or (field == "comision_pago_pct" and value >= 100):
                raise ExcelInputError("Settings %s must be zero or more%s." % (
                    label, " and below 100" if field == "comision_pago_pct" else ""))
            model[field] = value
    shipping = number(settings.get(SHIPPING_SETTING, ""), "Settings", 0, SHIPPING_SETTING,
                      allow_blank=True)
    if shipping is not None and shipping < 0:
        raise ExcelInputError("Settings %s must be zero or more." % SHIPPING_SETTING)

    advertising = {}
    if any(all(header in row for header in ADVERTISING_HEADERS) for row in settings_rows):
        for offset, row in enumerate(table(settings_rows, "Settings", ADVERTISING_HEADERS), start=1):
            month = str(row["Month (YYYY-MM)"]).strip()
            if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", month):
                raise ExcelInputError("Settings advertising row %d: Month must use YYYY-MM." % offset)
            if month in advertising:
                raise ExcelInputError("Settings advertising row %d: %s is listed twice." % (offset, month))
            spend = number(row["Advertising spend ex VAT"], "Settings advertising", offset,
                           "Advertising spend ex VAT", allow_blank=True) or 0.0
            if spend < 0:
                raise ExcelInputError("Settings advertising row %d: spend cannot be negative." % offset)
            advertising[month] = spend
    if advertising:
        model["publicidad"] = advertising
    if shipping:
        model.setdefault("logistica_por_pedido", 0.0)
    return (model or None), (shipping or 0.0)


def load_workbook(path):
    try:
        with zipfile.ZipFile(path) as archive:
            strings = shared_strings(archive)
            paths = sheet_paths(archive)
            simplified = ("Settings", "Catalogue", "Pricing & promotions", "Orders")
            legacy = ("Settings", "Products", "Price history", "Bundles", "Orders")
            required = simplified if all(name in paths for name in simplified) else legacy
            missing = [name for name in required if name not in paths]
            if missing:
                raise ExcelInputError("Workbook is missing sheets: %s." % ", ".join(missing))
            return {name: read_sheet(archive, paths[name], strings) for name in required}
    except (OSError, zipfile.BadZipFile) as exc:
        raise ExcelInputError("Could not read workbook %s: %s" % (path, exc))


def build_inputs(path):
    sheets = load_workbook(path)
    setting_rows = table(sheets["Settings"], "Settings", ["Setting", "Value"])
    settings = {row["Setting"].strip(): row["Value"] for row in setting_rows}
    required_settings = ("Store name", "Store domain", "Currency", "VAT rate (%)", "Target units",
                         "Gross sales target", "Target start", "Target end")
    missing = [key for key in required_settings if not str(settings.get(key, "")).strip()]
    if missing:
        raise ExcelInputError("Settings is missing values for: %s." % ", ".join(missing))
    variable_model, shipping_charged = variable_cost_inputs(settings, sheets["Settings"])
    pricing_model = str(settings.get("Pricing model", "Actual")).strip().lower()
    if pricing_model not in ("scenario", "actual"):
        raise ExcelInputError("Settings Pricing model must be either Scenario or Actual.")

    simplified = "Catalogue" in sheets
    if simplified:
        product_rows = table(sheets["Catalogue"], "Catalogue", ["Type", "SKU", "Name", "Unit cost ex VAT",
                             "Web price incl VAT", "Batch quantity", "Cost source", "Notes"],
                             optional=("Stock on hand", "Bundle contents", "Declared solo total",
                                       "Claimed saving", "Confirmed (TRUE/FALSE)"))
        for row in product_rows:
            if str(row["Type"]).strip().lower() not in ("product", "bundle"):
                raise ExcelInputError("Catalogue: Type must be Product or Bundle for SKU %s." % row["SKU"])
        product_rows = [row for row in product_rows if str(row["Type"]).strip().lower() == "product"]
        bundle_rows = table(sheets["Catalogue"], "Catalogue", ["Type", "SKU", "Name", "Web price incl VAT",
                            "Bundle contents", "Declared solo total", "Claimed saving",
                            "Confirmed (TRUE/FALSE)", "Notes"])
        bundle_rows = [row for row in bundle_rows if str(row["Type"]).strip().lower() == "bundle"]
        products_sheet = "Catalogue"
    else:
        product_rows = table(sheets["Products"], "Products", ["SKU", "Product name", "Unit cost ex VAT",
                             "Current web price incl VAT", "Batch quantity", "Cost source",
                              "Cost confirmed date", "Notes"], optional=("Stock on hand",))
        bundle_rows = table(sheets["Bundles"], "Bundles", ["Bundle SKU", "Bundle name", "Bundle price incl VAT",
                            "Confirmed (TRUE/FALSE)", "Contents (SKU:quantity | SKU:quantity)", "Declared solo total",
                            "Declared saving", "Notes"])
        products_sheet = "Products"
    products = {}
    for offset, row in enumerate(product_rows, start=4):
        sku = str(row["SKU"]).strip()
        if not sku:
            raise ExcelInputError("%s row %d: SKU is required." % (products_sheet, offset))
        if sku in products:
            raise ExcelInputError("%s row %d: duplicate SKU %s." % (products_sheet, offset, sku))
        products[sku] = {
            "nombre": str(row["Name"] if simplified else row["Product name"]).strip(),
            "coste_unitario": positive(row["Unit cost ex VAT"], products_sheet, offset, "Unit cost ex VAT"),
            "coste_fuente": str(row["Cost source"]).strip(),
            "precio_web": positive(row["Web price incl VAT"] if simplified else row["Current web price incl VAT"],
                                    products_sheet, offset, "Web price incl VAT"),
            "tirada": whole_number(row["Batch quantity"], products_sheet, offset, "Batch quantity", 1),
        }
        # Stock on hand is optional: a store that does not track it still gets margins,
        # it just does not get the inventory view. Better than inferring stock from sales.
        if "Stock on hand" in row and str(row["Stock on hand"]).strip():
            products[sku]["stock"] = whole_number(row["Stock on hand"], products_sheet, offset,
                                                  "Stock on hand")
        if not products[sku]["nombre"]:
            raise ExcelInputError("%s row %d: Product name is required." % (products_sheet, offset))

    pricing_sheet = "Pricing & promotions" if simplified else "Price history"
    history_rows = table(sheets[pricing_sheet], pricing_sheet, ["SKU", "Start date", "Price incl VAT", "Source"])
    for offset, row in enumerate(history_rows, start=4):
        sku = str(row["SKU"]).strip()
        if sku not in products:
            raise ExcelInputError("Price history row %d: SKU %s does not exist in Catalogue." % (offset, sku))
        products[sku].setdefault("precios", []).append({
            "desde": str(row["Start date"]).strip(),
            "precio": positive(row["Price incl VAT"], pricing_sheet, offset, "Price incl VAT"),
            "fuente": str(row["Source"]).strip(),
        })

    bundles = {}
    for offset, row in enumerate(bundle_rows, start=4):
        sku = str(row["SKU"] if simplified else row["Bundle SKU"]).strip()
        if not sku:
            raise ExcelInputError("Catalogue row %d: Bundle SKU is required." % offset)
        if sku in products or sku in bundles:
            raise ExcelInputError("Catalogue: duplicate SKU %s. Products and bundles need unique SKUs." % sku)
        bundles[sku] = {
            "sku": sku, "nombre": str(row["Name"] if simplified else row["Bundle name"]).strip(),
            "precio_web": positive(row["Web price incl VAT"] if simplified else row["Bundle price incl VAT"],
                                    "Catalogue" if simplified else "Bundles", offset, "Bundle price incl VAT"),
            "confirmado": truth(row["Confirmed (TRUE/FALSE)"], "Catalogue" if simplified else "Bundles", offset, "Confirmed"),
            "contiene": contents(row["Bundle contents"] if simplified else row["Contents (SKU:quantity | SKU:quantity)"], offset),
            "sueltos_declarado": number(row["Declared solo total"], "Catalogue" if simplified else "Bundles", offset, "Declared solo total"),
            "ahorro_declarado": number(row["Claimed saving"] if simplified else row["Declared saving"], "Catalogue" if simplified else "Bundles", offset, "Claimed saving"),
        }

    promotions = {}
    if simplified:
        promotion_rows = table(sheets[pricing_sheet], pricing_sheet,
                               ["Discount code", "Discount %", "Active from", "Active to", "Status"])
        for offset, row in enumerate(promotion_rows, start=4):
            code = str(row["Discount code"]).strip()
            if not code:
                raise ExcelInputError("Promotion rules row %d: Promotion code is required." % offset)
            if code in promotions:
                raise ExcelInputError("Promotion rules: duplicate code %s. Use one rule per code." % code)
            rate = number(row["Discount %"], pricing_sheet, offset, "Discount %")
            if rate < 0 or rate >= 100:
                raise ExcelInputError("Promotion rules row %d: Discount %% must be between 0 and 100." % offset)
            promotions[code] = {"porcentaje": rate, "desde": str(row["Active from"]).strip(),
                                "hasta": str(row["Active to"]).strip(),
                                "activo": truth(row["Status"], pricing_sheet, offset, "Status")}

    order_rows = table(sheets["Orders"], "Orders", ["Order ID", "Order date", "SKU", "Product title",
                       "Unit price incl VAT", "Quantity", "Discount allocated incl VAT",
                       "Taxable (TRUE/FALSE)"], optional=("Discount code",))
    orders = []
    charged_shipping = set()
    for offset, row in enumerate(order_rows, start=4):
        order_id = str(row["Order ID"]).strip()
        sku = str(row["SKU"]).strip()
        if not order_id or not sku:
            raise ExcelInputError("Orders row %d: Order ID and SKU are required." % offset)
        price = positive(row["Unit price incl VAT"], "Orders", offset, "Unit price incl VAT")
        quantity = whole_number(row["Quantity"], "Orders", offset, "Quantity", 1)
        discount = number(row["Discount allocated incl VAT"], "Orders", offset, "Discount allocated incl VAT", True) or 0.0
        if discount < 0 or discount > round(price * quantity, 2):
            raise ExcelInputError("Orders row %d: Discount must be between zero and the line's selling value." % offset)
        # Each Excel row becomes its own order object, so the per-order shipping
        # charge goes on the first row of an order only.
        shipping = 0.0
        if shipping_charged and order_id not in charged_shipping:
            charged_shipping.add(order_id)
            shipping = shipping_charged
        orders.append({
            "id": "excel:%s:%d" % (order_id, offset), "name": order_id,
            "createdAt": "%sT12:00:00Z" % str(row["Order date"]).strip(), "cancelledAt": None,
            "displayFinancialStatus": "PAID", "test": False, "taxesIncluded": True,
            "discountCodes": ([str(row["Discount code"]).strip()]
                              if str(row.get("Discount code", "")).strip() else []),
            "currentTotalDiscountsSet": money(discount),
            "currentTotalTaxSet": money(0.0), "totalShippingPriceSet": money(shipping),
            "lineItems": {"edges": [{"node": {
                "id": "excel-line:%d" % offset, "title": str(row["Product title"]).strip(), "sku": sku,
                "quantity": quantity, "variant": None, "product": None,
                "originalUnitPriceSet": money(price), "discountedUnitPriceSet": money(price),
                "totalDiscountSet": money(0.0),
                "discountAllocations": ([{"allocatedAmountSet": money(discount)}] if discount else []),
                "taxable": truth(row["Taxable (TRUE/FALSE)"], "Orders", offset, "Taxable"),
            }}]},
        })

    costs = {
        "meta": {"marca": settings["Store name"], "dominio": settings["Store domain"],
                 "moneda": settings["Currency"], "actualizado": "from Excel",
                 "pricing_model": pricing_model,
                 "objetivo_ventas_brutas": number(settings["Gross sales target"], "Settings", 0,
                                                    "Gross sales target")},
        "iva": {"tipo_pct": number(settings["VAT rate (%)"], "Settings", 0, "VAT rate (%)"),
                "precios_incluyen_iva": True},
        "productos": products, "bundles": bundles, "descuentos": promotions,
        "objetivo": {"unidades": whole_number(settings["Target units"], "Settings", 0, "Target units", 1),
                     "desde": str(settings["Target start"]), "hasta": str(settings["Target end"])},
    }
    if variable_model is not None:
        costs["costes_variables"] = variable_model
    return costs, {"extraido": "from editable Excel workbook", "tienda": settings["Store domain"], "pedidos": orders}


def write_inputs(workbook_path, costs_path, snapshot_path):
    costs, snapshot = build_inputs(workbook_path)
    with open(costs_path, "w", encoding="utf-8") as handle:
        json.dump(costs, handle, ensure_ascii=False, indent=2, allow_nan=False)
    with open(snapshot_path, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False, indent=2, allow_nan=False)
