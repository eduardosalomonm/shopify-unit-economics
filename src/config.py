"""Configuration loading and validation.

The public demo deliberately uses JSON so a clean clone needs no runtime
dependencies.  A private ``costs.yml`` remains supported for existing stores when
PyYAML is installed locally.
"""

import json
import math
import os


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_COSTS = os.path.join(BASE, "costs.example.json")


class ConfigError(Exception):
    """The cost model cannot safely be used to calculate a margin."""


NUMERIC_FIELDS = frozenset({
    "ahorro_declarado", "amount", "cost", "coste_total", "coste_unitario",
    "descuento_linea", "discount", "gross", "ingreso_con_iva", "ingreso_neto",
    "iva_implicito", "iva_pedido_declarado", "margin", "margen_contribucion",
    "margen_pct", "net", "objetivo_ventas_brutas", "porcentaje", "precio",
    "precio_bruto", "precio_catalogo", "precio_web", "quantity", "stock",
    "stock_on_hand", "sueltos_declarado", "tipo_pct", "tirada", "uds",
    "unidades", "units",
})


def validate_finite_values(value, field=None):
    """Reject non-finite numbers without treating store labels as numbers.

    Errors intentionally omit input values and object keys, which can contain
    private store data. Numeric strings are checked only for known numeric fields,
    so a legitimate SKU or product name such as ``NaN`` remains valid text.
    """
    if isinstance(value, dict):
        for key, item in value.items():
            validate_finite_values(item, str(key).casefold())
    elif isinstance(value, (list, tuple)):
        for item in value:
            validate_finite_values(item, field)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            numeric = float(value)
        except OverflowError:
            raise ConfigError("Numeric inputs must be finite and within supported range.") from None
        if not math.isfinite(numeric):
            raise ConfigError("Numeric inputs must be finite; NaN and infinity are not supported.")
    elif isinstance(value, str) and field in NUMERIC_FIELDS:
        try:
            numeric = float(value)
        except ValueError:
            return  # The schema-specific validator will report malformed numbers.
        except OverflowError:
            raise ConfigError("Numeric inputs must be finite and within supported range.") from None
        if not math.isfinite(numeric):
            raise ConfigError("Numeric inputs must be finite; NaN and infinity are not supported.")


def costs_path():
    """Return an explicit local model, or the dependency-free public example."""
    path = os.environ.get("COSTS_FILE", DEFAULT_COSTS)
    return path if os.path.isabs(path) else os.path.join(BASE, path)


def load_costs(path=None):
    path = path or costs_path()
    if not os.path.exists(path):
        raise ConfigError("Cost model does not exist: %s" % path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            if path.lower().endswith(".json"):
                costs = json.load(fh)
            else:
                try:
                    import yaml
                except ImportError:
                    raise ConfigError(
                        "The model %s is YAML. Install local support with "
                        "python3 -m pip install PyYAML, or use the JSON example." % path
                    )
                try:
                    costs = yaml.safe_load(fh)
                except yaml.YAMLError as exc:
                    raise ConfigError("Could not read %s: %s" % (path, exc))
    except (OSError, ValueError) as exc:
        raise ConfigError("Could not read %s: %s" % (path, exc))
    validate_costs(costs, path)
    return costs


def validate_costs(costs, path="cost model"):
    """Fail early with a useful message instead of producing plausible nonsense."""
    validate_finite_values(costs)
    if not isinstance(costs, dict):
        raise ConfigError("%s must contain an object." % path)
    required = ("productos", "objetivo")
    missing = [key for key in required if key not in costs]
    if missing:
        raise ConfigError("%s is missing: %s" % (path, ", ".join(missing)))
    if not isinstance(costs["productos"], dict) or not costs["productos"]:
        raise ConfigError("%s needs at least one product." % path)
    for sku, product in costs["productos"].items():
        for field in ("nombre", "coste_unitario", "precio_web"):
            if field not in product:
                raise ConfigError("%s: product %s is missing %s." % (path, sku, field))
        try:
            if float(product["coste_unitario"]) < 0 or float(product["precio_web"]) < 0:
                raise ValueError
        except (TypeError, ValueError):
            raise ConfigError("%s: costs and prices for %s must be non-negative numbers."
                              % (path, sku))
    objective = costs["objetivo"]
    if not isinstance(objective, dict) or not all(k in objective for k in ("unidades", "desde", "hasta")):
        raise ConfigError("%s: target needs units, start and end." % path)
