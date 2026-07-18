from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from ExecutionPlan import (
    ExecutionDispense,
    ExecutionPlan,
    ExecutionPlanState,
    ExecutionPlate,
    ExecutionStock,
    ExecutionVolumeBasis,
    ExecutionWell,
    canonical_sha256,
    new_plan_id,
)


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stock_id_for_row(row: Mapping[str, Any]) -> str:
    reagent_name = str(row.get("option_name") or row.get("factor_name") or "").strip()
    units = str(row.get("units") or "").strip()
    if not reagent_name or not units:
        raise ValueError("Every finalized stock row requires a reagent name and units.")
    try:
        concentration = float(row.get("stock_concentration"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Stock {reagent_name!r} has no numeric concentration.") from exc
    return f"{reagent_name}_{concentration:.2f}_{units}"


def _design_option_lookup(
    design_payload: Mapping[str, Any],
) -> dict[tuple[str, str | None, str], list[Mapping[str, Any]]]:
    lookup: dict[tuple[str, str | None, str], list[Mapping[str, Any]]] = {}
    factors = design_payload.get("factors")
    if not isinstance(factors, list):
        raise ValueError("The finalized design has no valid factors list.")
    for factor in factors:
        if not isinstance(factor, Mapping):
            raise ValueError("Every finalized design factor must be an object.")
        factor_name = str(factor.get("name") or "").strip()
        kind = str(factor.get("kind") or "").strip()
        options = factor.get("options")
        if not factor_name or kind not in {"additive", "choice"} or not isinstance(options, list):
            raise ValueError(f"Design factor {factor_name!r} is invalid.")
        for option in options:
            if not isinstance(option, Mapping):
                raise ValueError(f"Design factor {factor_name!r} has an invalid option.")
            option_name = str(option.get("name") or "").strip()
            units = str(option.get("units") or "").strip()
            if not option_name or not units:
                raise ValueError(f"Design factor {factor_name!r} has an unnamed option or units.")
            key = (factor_name, None if kind == "additive" else option_name, units)
            lookup.setdefault(key, []).append(option)
    return lookup


def _intended_volume_for_row(
    row: Mapping[str, Any],
    *,
    metadata: Mapping[str, Any],
    option_lookup: Mapping[tuple[str, str | None, str], list[Mapping[str, Any]]],
) -> float:
    factor_name = str(row.get("factor_name") or "").strip()
    option_text = str(row.get("option_name") or "").strip()
    units = str(row.get("units") or "").strip()
    effective = float(row.get("droplet_volume_nL"))
    fill_name = str(metadata.get("fill_reagent_name") or "Water").strip()
    if factor_name == fill_name and not option_text and units == "--":
        value = metadata.get(
            "intended_fill_droplet_volume_nL",
            metadata.get("fill_droplet_volume_nL", effective),
        )
        return float(value)

    key = (factor_name, option_text or None, units)
    candidates = list(option_lookup.get(key, []))
    if len(candidates) != 1:
        raise ValueError(
            f"Finalized stock {_stock_id_for_row(row)!r} maps to {len(candidates)} design options; expected exactly one."
        )
    option = candidates[0]
    value = option.get("intended_droplet_nL", option.get("droplet_nL"))
    if value is None:
        raise ValueError(
            f"Finalized stock {_stock_id_for_row(row)!r} has no persisted intended dispense volume."
        )
    return float(value)


def build_initial_execution_plan(
    *,
    design_payload: Mapping[str, Any],
    plate_name: str,
    plate_rows: int,
    plate_columns: int,
    stock_rows: Iterable[Mapping[str, Any]],
    assigned_wells: Iterable[Mapping[str, Any]],
    plan_id: str | None = None,
    timestamp_utc: str | None = None,
) -> ExecutionPlan:
    if not isinstance(design_payload, Mapping):
        raise ValueError("The finalized design payload must be an object.")
    metadata = design_payload.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ValueError("The finalized design has no valid metadata object.")

    rows_by_stock_id: dict[str, Mapping[str, Any]] = {}
    for row in stock_rows:
        if not isinstance(row, Mapping):
            raise ValueError("Every finalized stock row must be an object.")
        stock_id = _stock_id_for_row(row)
        if stock_id in rows_by_stock_id:
            raise ValueError(f"Finalized stock rows contain duplicate stock ID {stock_id!r}.")
        rows_by_stock_id[stock_id] = row

    raw_wells = list(assigned_wells)
    referenced_stock_ids: set[str] = set()
    normalized_wells: list[tuple[str, str, dict[str, int]]] = []
    for raw_well in raw_wells:
        if not isinstance(raw_well, Mapping):
            raise ValueError("Every finalized assigned well must be an object.")
        well_id = str(raw_well.get("well_id") or "").strip().upper()
        reaction_id = str(raw_well.get("reaction_id") or "").strip()
        targets = raw_well.get("target_dispenses")
        if not well_id or not reaction_id or not isinstance(targets, Mapping):
            raise ValueError("Every finalized well requires a well ID, reaction ID, and target map.")
        normalized_targets: dict[str, int] = {}
        for stock_id, count in targets.items():
            stock_id = str(stock_id).strip()
            if isinstance(count, bool):
                raise ValueError(f"Target count for {well_id}/{stock_id} must be an integer.")
            try:
                integer_count = int(count)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Target count for {well_id}/{stock_id} must be an integer.") from exc
            if integer_count != count or integer_count < 0:
                raise ValueError(f"Target count for {well_id}/{stock_id} must be a non-negative integer.")
            normalized_targets[stock_id] = integer_count
            referenced_stock_ids.add(stock_id)
        normalized_wells.append((well_id, reaction_id, normalized_targets))

    missing = sorted(referenced_stock_ids - set(rows_by_stock_id))
    if missing:
        raise ValueError(
            "Finalized runtime wells reference stocks absent from the exact stock plan: "
            + ", ".join(missing)
        )

    option_lookup = _design_option_lookup(design_payload)
    stocks: list[ExecutionStock] = []
    for stock_id in sorted(referenced_stock_ids):
        row = rows_by_stock_id[stock_id]
        factor_name = str(row.get("factor_name") or "").strip()
        option_name = str(row.get("option_name") or "").strip() or None
        reagent_name = option_name or factor_name
        stocks.append(
            ExecutionStock(
                stock_id=stock_id,
                factor_name=factor_name,
                option_name=option_name,
                reagent_name=reagent_name,
                concentration=float(row.get("stock_concentration")),
                units=str(row.get("units") or "").strip(),
                printing_mode=str(row.get("printing_mode") or "").strip().lower(),
                intended_volume_nL=_intended_volume_for_row(
                    row,
                    metadata=metadata,
                    option_lookup=option_lookup,
                ),
                effective_volume_nL=float(row.get("droplet_volume_nL")),
                printer_head_id=None,
                calibration_record_key=None,
            )
        )
    stock_lookup = {stock.stock_id: stock for stock in stocks}

    wells: list[ExecutionWell] = []
    for well_id, reaction_id, targets in normalized_wells:
        dispenses = tuple(
            ExecutionDispense(stock_id=stock_id, target_dispenses=count)
            for stock_id, count in targets.items()
        )
        expected = sum(
            dispense.target_dispenses * stock_lookup[dispense.stock_id].effective_volume_nL
            for dispense in dispenses
        )
        wells.append(
            ExecutionWell(
                well_id=well_id,
                reaction_id=reaction_id,
                dispenses=dispenses,
                expected_printed_volume_nL=expected,
            )
        )

    timestamp = timestamp_utc or _utc_now_text()
    return ExecutionPlan(
        plan_id=plan_id or new_plan_id(),
        plan_revision=1,
        state=ExecutionPlanState.PREPARED,
        design_sha256=canonical_sha256(design_payload),
        created_at_utc=timestamp,
        updated_at_utc=timestamp,
        locked_at_utc=None,
        lock_reason=None,
        plate=ExecutionPlate(str(plate_name), int(plate_rows), int(plate_columns)),
        volume_basis=ExecutionVolumeBasis(
            target_printed_volume_nL=float(metadata.get("target_reaction_volume_nL")),
            final_reaction_volume_nL=float(
                metadata.get("final_reaction_volume_nL", metadata.get("target_reaction_volume_nL"))
            ),
            design_optimization_tolerance_nL=float(
                metadata.get("printed_volume_tolerance_nL", 0.0)
            ),
        ),
        stocks=tuple(stocks),
        wells=tuple(wells),
    )


def initial_execution_content_matches(
    existing: ExecutionPlan,
    candidate: ExecutionPlan,
) -> bool:
    return bool(
        existing.state is ExecutionPlanState.PREPARED
        and existing.plan_revision == 1
        and existing.design_sha256 == candidate.design_sha256
        and existing.plate == candidate.plate
        and existing.volume_basis == candidate.volume_basis
        and existing.stocks == candidate.stocks
        and existing.wells == candidate.wells
    )
