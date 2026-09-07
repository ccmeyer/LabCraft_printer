from __future__ import annotations

from typing import Any, Mapping


STOCK_ID_CONCENTRATION_DECIMALS = 2


def stock_id_for_parts(reagent_name: str, concentration: float, units: str) -> str:
    """Return the legacy runtime stock identity without changing its schema."""
    concentration_text = (
        f"{float(concentration):.{STOCK_ID_CONCENTRATION_DECIMALS}f}"
    )
    return "_".join((str(reagent_name), concentration_text, str(units)))


def stock_id_for_row(row: Mapping[str, Any]) -> str:
    reagent_name = str(
        row.get("option_name") or row.get("factor_name") or ""
    ).strip()
    units = str(row.get("units") or "").strip()
    if not reagent_name or not units:
        raise ValueError("Every stock row requires a reagent name and units.")
    try:
        concentration = float(row.get("stock_concentration"))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Stock {reagent_name!r} has no numeric concentration."
        ) from exc
    return stock_id_for_parts(reagent_name, concentration, units)
