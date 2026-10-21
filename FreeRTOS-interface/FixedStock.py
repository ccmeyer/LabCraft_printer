"""Fixed stock input shared by the designer and its model."""
import math

from StockIdentity import stock_id_for_parts


def normalize_fixed_stock_pair(values):
    if values is None:
        return None
    if not isinstance(values, (tuple, list)) or len(values) != 2:
        raise ValueError("Enter exactly two fixed stock concentrations.")
    try:
        pair = tuple(sorted((float(value) for value in values), reverse=True))
    except (TypeError, ValueError):
        raise ValueError("Fixed stock concentrations must be positive finite numbers.") from None
    if any(not math.isfinite(value) or value <= 0 for value in pair):
        raise ValueError("Fixed stock concentrations must be positive finite numbers.")
    if stock_id_for_parts("", pair[0], "") == stock_id_for_parts("", pair[1], ""):
        raise ValueError("Fixed stocks must have distinct concentrations at stock-ID precision (two decimal places).")
    return pair


def parse_fixed_stock_text(text):
    """Return (single, pair); blank means automatic selection."""
    text = (text or "").strip()
    if not text:
        return None, None
    if "," in text:
        return None, normalize_fixed_stock_pair(text.split(","))
    try:
        value = float(text)
    except ValueError:
        raise ValueError("Fixed stock must be a positive number or two comma-separated concentrations.") from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Fixed stock must be a positive number (finite and greater than zero).")
    return value, None


def fixed_stock_concentrations(option):
    pair = normalize_fixed_stock_pair(getattr(option, "forced_stock_concs", None))
    single = getattr(option, "forced_stock_conc", None)
    if pair is not None:
        if single is not None:
            raise ValueError("Specify either one fixed stock or a fixed pair, not both.")
        return pair
    return () if single in (None, 0.0) else (float(single),)


def has_fixed_stock(option):
    return bool(fixed_stock_concentrations(option))


def fixed_stock_matches(option, concentrations, *, abs_tol=1e-12, rel_tol=0.0):
    expected = fixed_stock_concentrations(option)
    if not expected:
        return True
    try:
        actual = tuple(sorted((float(value) for value in concentrations), reverse=True))
    except (TypeError, ValueError):
        return False
    return len(actual) == len(expected) and all(
        math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)
        for a, b in zip(actual, expected)
    )


def format_fixed_stock_text(single=None, pair=None):
    if pair is not None:
        return ", ".join(str(value) for value in reversed(normalize_fixed_stock_pair(pair)))
    return "" if single in (None, 0.0) else str(single)
