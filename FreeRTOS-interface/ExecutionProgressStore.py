from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

from ExecutionPlan import ExecutionPlan, ProgressExecutionReference


SCHEMA_NAME = "labcraft.execution_progress"
SCHEMA_VERSION = 2


class ExecutionProgressValidationError(ValueError):
    """Raised when an execution-progress document violates its schema."""


@dataclass(frozen=True)
class DecodedExecutionProgress:
    schema_version: int
    payload: dict[str, Any]
    progress_wells: dict[str, Any]
    reference: ProgressExecutionReference


def _error(path: str, message: str) -> ExecutionProgressValidationError:
    return ExecutionProgressValidationError(f"{path}: {message}")


def _object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(path, "must be a JSON object")
    return value


def _exact_fields(
    value: Any,
    *,
    fields: set[str],
    path: str,
) -> Mapping[str, Any]:
    obj = _object(value, path)
    actual = set(obj)
    missing = sorted(fields - actual)
    unknown = sorted(actual - fields)
    if missing:
        raise _error(path, f"missing required field(s): {', '.join(missing)}")
    if unknown:
        raise _error(path, f"unknown field(s): {', '.join(unknown)}")
    return obj


def _count(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _error(path, "must be a nonnegative integer")
    return value


def _legacy_count(value: Any, path: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not float(value).is_integer()
        or int(value) < 0
    ):
        raise _error(path, "must be a nonnegative integer")
    return int(value)


def detect_execution_progress_schema(payload: Any) -> int:
    obj = _object(payload, "progress")
    has_schema_name = "schema_name" in obj
    has_schema_version = "schema_version" in obj
    if not has_schema_name and not has_schema_version:
        return 1
    if not has_schema_name or not has_schema_version:
        raise _error("progress", "schema_name and schema_version must appear together")
    if obj["schema_name"] != SCHEMA_NAME:
        raise _error("progress.schema_name", f"must equal {SCHEMA_NAME!r}")
    version = obj["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise _error("progress.schema_version", "must be an integer")
    if version != SCHEMA_VERSION:
        raise _error("progress.schema_version", f"unsupported version {version}")
    return version


def _plan_reference(plan: ExecutionPlan) -> ProgressExecutionReference:
    return ProgressExecutionReference(
        plan_id=plan.plan_id,
        plan_revision=plan.plan_revision,
    )


def progress_reference_from_payload(payload: Any) -> ProgressExecutionReference:
    obj = _object(payload, "progress")
    version = detect_execution_progress_schema(obj)
    if version == 1:
        return ProgressExecutionReference.from_dict(obj.get("__execution__"))
    return ProgressExecutionReference(
        plan_id=obj.get("plan_id"),
        plan_revision=obj.get("plan_revision"),
    )


def _validate_reference(
    plan: ExecutionPlan,
    reference: ProgressExecutionReference,
) -> None:
    if (
        reference.plan_id != plan.plan_id
        or reference.plan_revision != plan.plan_revision
    ):
        raise _error("progress", "does not reference the latest execution plan")


def _validate_canonical_progress_wells(
    plan: ExecutionPlan,
    wells: Any,
    *,
    legacy_numeric_values: bool = False,
) -> dict[str, Any]:
    wells_obj = _object(wells, "progress.wells")
    expected_well_ids = {well.well_id for well in plan.wells}
    if set(wells_obj) != expected_well_ids:
        raise _error(
            "progress.wells", "well identities differ from the execution plan"
        )
    reaction_ids = [well.reaction_id for well in plan.wells]
    if len(reaction_ids) != len(set(reaction_ids)):
        raise _error(
            "progress.wells",
            "authoritative runtime loading requires unique reaction IDs",
        )

    validated: dict[str, Any] = {}
    allowed_reagent_fields = {
        "target_droplets",
        "added_droplets",
        "name",
        "concentration",
        "units",
    }
    for well in plan.wells:
        path = f"progress.wells.{well.well_id}"
        entry = _exact_fields(
            wells_obj[well.well_id],
            fields={"reaction_id", "reagents", "completed"},
            path=path,
        )
        if entry["reaction_id"] != well.reaction_id:
            raise _error(path + ".reaction_id", "differs from the execution plan")
        reagent_obj = _object(entry["reagents"], path + ".reagents")
        targets = {
            dispense.stock_id: dispense.target_dispenses
            for dispense in well.dispenses
        }
        if set(reagent_obj) != set(targets):
            raise _error(path + ".reagents", "stock identities differ from the plan")

        normalized_reagents: dict[str, Any] = {}
        for stock_id, target in targets.items():
            reagent_path = path + f".reagents.{stock_id}"
            details = _object(reagent_obj[stock_id], reagent_path)
            if (
                not {"target_droplets", "added_droplets"}.issubset(details)
                or set(details) - allowed_reagent_fields
            ):
                raise _error(reagent_path, "contains invalid fields")
            count_parser = _legacy_count if legacy_numeric_values else _count
            if count_parser(
                details["target_droplets"], reagent_path + ".target_droplets"
            ) != target:
                raise _error(
                    reagent_path + ".target_droplets",
                    "differs from the execution plan",
                )
            added = count_parser(
                details["added_droplets"], reagent_path + ".added_droplets"
            )
            if added > target:
                raise _error(
                    reagent_path + ".added_droplets", "exceeds the frozen target"
                )
            normalized_reagents[stock_id] = dict(details)

        completed = entry["completed"]
        expected_completed = all(
            normalized_reagents[stock_id]["added_droplets"] >= target
            for stock_id, target in targets.items()
        )
        if not isinstance(completed, bool) or completed != expected_completed:
            raise _error(path + ".completed", "differs from the reagent counts")
        validated[well.well_id] = {
            "reaction_id": well.reaction_id,
            "reagents": normalized_reagents,
            "completed": completed,
        }
    return validated


def _decode_v1(plan: ExecutionPlan, payload: Mapping[str, Any]) -> DecodedExecutionProgress:
    reference = ProgressExecutionReference.from_dict(payload.get("__execution__"))
    _validate_reference(plan, reference)
    plate = _object(payload.get("__plate__"), "progress.__plate__")
    if (
        plate.get("name") != plan.plate.name
        or _legacy_count(plate.get("rows"), "progress.__plate__.rows")
        != plan.plate.rows
        or _legacy_count(plate.get("columns"), "progress.__plate__.columns")
        != plan.plate.columns
    ):
        raise _error("progress.__plate__", "differs from the execution plan")
    wells = {
        str(key): value
        for key, value in payload.items()
        if not str(key).startswith("__")
    }
    return DecodedExecutionProgress(
        schema_version=1,
        payload=dict(payload),
        progress_wells=_validate_canonical_progress_wells(
            plan, wells, legacy_numeric_values=True
        ),
        reference=reference,
    )


def _decode_v2(plan: ExecutionPlan, payload: Mapping[str, Any]) -> DecodedExecutionProgress:
    obj = _exact_fields(
        payload,
        fields={
            "schema_name",
            "schema_version",
            "plan_id",
            "plan_revision",
            "well_order",
            "added_droplets",
        },
        path="progress",
    )
    reference = ProgressExecutionReference(
        plan_id=obj["plan_id"],
        plan_revision=obj["plan_revision"],
    )
    _validate_reference(plan, reference)

    well_order = obj["well_order"]
    if not isinstance(well_order, list) or any(
        not isinstance(well_id, str) for well_id in well_order
    ):
        raise _error("progress.well_order", "must be an array of strings")
    expected_well_order = [well.well_id for well in plan.wells]
    if well_order != expected_well_order:
        raise _error(
            "progress.well_order", "must equal the execution plan's canonical order"
        )

    added_by_stock = _object(obj["added_droplets"], "progress.added_droplets")
    expected_stock_ids = [stock.stock_id for stock in plan.stocks]
    if set(added_by_stock) != set(expected_stock_ids):
        raise _error(
            "progress.added_droplets",
            "stock identities differ from the execution plan",
        )

    targets_by_well = {
        well.well_id: {
            dispense.stock_id: dispense.target_dispenses
            for dispense in well.dispenses
        }
        for well in plan.wells
    }
    arrays: dict[str, list[Any]] = {}
    for stock_id in expected_stock_ids:
        values = added_by_stock[stock_id]
        stock_path = f"progress.added_droplets.{stock_id}"
        if not isinstance(values, list):
            raise _error(stock_path, "must be an array")
        if len(values) != len(expected_well_order):
            raise _error(stock_path, "length differs from well_order")
        checked: list[Any] = []
        for index, well_id in enumerate(expected_well_order):
            value = values[index]
            target = targets_by_well[well_id].get(stock_id)
            item_path = f"{stock_path}[{index}]"
            if target is None:
                if value is not None:
                    raise _error(item_path, "must be null where the stock is absent")
                checked.append(None)
                continue
            added = _count(value, item_path)
            if added > target:
                raise _error(item_path, "exceeds the frozen target")
            checked.append(added)
        arrays[stock_id] = checked

    wells: dict[str, Any] = {}
    for index, well in enumerate(plan.wells):
        reagents = {
            dispense.stock_id: {
                "target_droplets": dispense.target_dispenses,
                "added_droplets": arrays[dispense.stock_id][index],
            }
            for dispense in well.dispenses
        }
        wells[well.well_id] = {
            "reaction_id": well.reaction_id,
            "reagents": reagents,
            "completed": all(
                details["added_droplets"] >= details["target_droplets"]
                for details in reagents.values()
            ),
        }
    return DecodedExecutionProgress(
        schema_version=SCHEMA_VERSION,
        payload=dict(payload),
        progress_wells=wells,
        reference=reference,
    )


def decode_execution_progress(
    plan: ExecutionPlan,
    payload: Any,
) -> DecodedExecutionProgress:
    obj = _object(payload, "progress")
    if detect_execution_progress_schema(obj) == 1:
        return _decode_v1(plan, obj)
    return _decode_v2(plan, obj)


def encode_execution_progress_v2(
    plan: ExecutionPlan,
    progress_wells: Any,
) -> dict[str, Any]:
    wells = _validate_canonical_progress_wells(plan, progress_wells)
    well_order = [well.well_id for well in plan.wells]
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan.plan_id,
        "plan_revision": plan.plan_revision,
        "well_order": well_order,
        "added_droplets": {
            stock.stock_id: [
                (
                    wells[well_id]["reagents"][stock.stock_id]["added_droplets"]
                    if stock.stock_id in wells[well_id]["reagents"]
                    else None
                )
                for well_id in well_order
            ]
            for stock in plan.stocks
        },
    }


def encode_execution_progress_v1(
    plan: ExecutionPlan,
    progress_wells: Any,
) -> dict[str, Any]:
    wells = _validate_canonical_progress_wells(plan, progress_wells)
    payload = {
        well.well_id: {
            "reaction_id": well.reaction_id,
            "reagents": {
                dispense.stock_id: {
                    "target_droplets": dispense.target_dispenses,
                    "added_droplets": wells[well.well_id]["reagents"][
                        dispense.stock_id
                    ]["added_droplets"],
                }
                for dispense in well.dispenses
            },
            "completed": wells[well.well_id]["completed"],
        }
        for well in plan.wells
    }
    payload["__plate__"] = {
        "name": plan.plate.name,
        "rows": plan.plate.rows,
        "columns": plan.plate.columns,
    }
    payload["__execution__"] = _plan_reference(plan).to_dict()
    return payload


def serialize_execution_progress(
    payload: Any,
    *,
    default: Any = None,
) -> str:
    version = detect_execution_progress_schema(payload)
    if version == SCHEMA_VERSION:
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    kwargs: dict[str, Any] = {"indent": 4}
    if default is not None:
        kwargs["default"] = default
    return json.dumps(payload, **kwargs)


def update_execution_progress_payload(
    plan: ExecutionPlan,
    payload: Any,
    *,
    well_id: str,
    stock_id: str,
    added_droplets: int,
) -> DecodedExecutionProgress:
    decoded = decode_execution_progress(plan, payload)
    candidate = copy_execution_progress_payload(
        plan,
        decoded.payload,
        well_id=well_id,
        stock_id=stock_id,
        added_droplets=added_droplets,
    )
    return decode_execution_progress(plan, candidate)


def copy_execution_progress_payload(
    plan: ExecutionPlan,
    payload: Any,
    *,
    well_id: str,
    stock_id: str,
    added_droplets: int,
) -> dict[str, Any]:
    """Copy only the raw containers affected by one validated completion."""
    added = _count(added_droplets, "added_droplets")
    well_lookup = {well.well_id: well for well in plan.wells}
    well = well_lookup.get(well_id)
    targets = (
        {
            dispense.stock_id: dispense.target_dispenses
            for dispense in well.dispenses
        }
        if well is not None
        else {}
    )
    if well is None or stock_id not in targets:
        raise _error("progress", "completion does not identify a planned well/stock")
    target = targets[stock_id]
    if added > target:
        raise _error("added_droplets", "exceeds the frozen target")

    obj = _object(payload, "progress")
    if detect_execution_progress_schema(obj) == SCHEMA_VERSION:
        candidate = dict(obj)
        candidate_by_stock = dict(obj["added_droplets"])
        candidate_values = list(candidate_by_stock[stock_id])
        index = obj["well_order"].index(well_id)
        if candidate_values[index] is None:
            raise _error(
                "progress", "completion identifies a null stock/well position"
            )
        candidate_values[index] = added
        candidate_by_stock[stock_id] = candidate_values
        candidate["added_droplets"] = candidate_by_stock
    else:
        candidate = dict(obj)
        well_entry = dict(candidate[well_id])
        reagents = dict(well_entry["reagents"])
        reagent = dict(reagents[stock_id])
        reagent["added_droplets"] = added
        reagents[stock_id] = reagent
        well_entry["reagents"] = reagents
        well_entry["completed"] = all(
            int(details.get("added_droplets", 0) or 0)
            >= int(details.get("target_droplets", 0) or 0)
            for details in reagents.values()
        )
        candidate[well_id] = well_entry
    return candidate


def execution_progress_added_value(
    payload: Any,
    *,
    well_id: str,
    stock_id: str,
) -> int:
    obj = _object(payload, "progress")
    if detect_execution_progress_schema(obj) == SCHEMA_VERSION:
        well_order = obj.get("well_order")
        added_by_stock = obj.get("added_droplets")
        if not isinstance(well_order, list) or well_id not in well_order:
            raise _error("progress", "well is missing from compact progress")
        if not isinstance(added_by_stock, Mapping) or stock_id not in added_by_stock:
            raise _error("progress", "stock is missing from compact progress")
        values = added_by_stock[stock_id]
        index = well_order.index(well_id)
        if not isinstance(values, list) or index >= len(values):
            raise _error("progress", "stock array is malformed")
        return _count(
            values[index],
            f"progress.added_droplets.{stock_id}[{index}]",
        )
    well = obj.get(well_id)
    reagent = (
        (well.get("reagents") or {}).get(stock_id)
        if isinstance(well, Mapping)
        else None
    )
    if not isinstance(reagent, Mapping):
        raise _error("progress", "well/stock is missing from schema-v1 progress")
    return _legacy_count(
        reagent.get("added_droplets"),
        f"progress.wells.{well_id}.reagents.{stock_id}.added_droplets",
    )


def copy_progress_wells_update(
    progress_wells: Mapping[str, Any],
    *,
    well_id: str,
    stock_id: str,
    added_droplets: int,
) -> dict[str, Any]:
    """Copy one well/reagent branch in an already validated expanded snapshot."""
    well = progress_wells.get(well_id)
    if not isinstance(well, Mapping):
        raise _error("progress.wells", "completion well is unavailable")
    reagents = well.get("reagents")
    if not isinstance(reagents, Mapping):
        raise _error("progress.wells", "completion reagent mapping is unavailable")
    details = reagents.get(stock_id)
    if not isinstance(details, Mapping):
        raise _error("progress.wells", "completion stock is unavailable")
    added = _count(added_droplets, "added_droplets")
    target = _count(details.get("target_droplets"), "target_droplets")
    if added > target:
        raise _error("added_droplets", "exceeds the frozen target")
    candidate_details = dict(details)
    candidate_details["added_droplets"] = added
    candidate_reagents = dict(reagents)
    candidate_reagents[stock_id] = candidate_details
    candidate_well = dict(well)
    candidate_well["reagents"] = candidate_reagents
    candidate_well["completed"] = all(
        _count(item.get("added_droplets"), "added_droplets")
        >= _count(item.get("target_droplets"), "target_droplets")
        for item in candidate_reagents.values()
    )
    candidate_wells = dict(progress_wells)
    candidate_wells[well_id] = candidate_well
    return candidate_wells


def has_positive_execution_progress(payload: Any) -> bool:
    obj = _object(payload, "progress")
    if detect_execution_progress_schema(obj) == SCHEMA_VERSION:
        added_by_stock = _object(
            obj.get("added_droplets"), "progress.added_droplets"
        )
        return any(
            isinstance(value, int) and not isinstance(value, bool) and value > 0
            for values in added_by_stock.values()
            if isinstance(values, list)
            for value in values
        )
    return any(
        isinstance(details, Mapping)
        and isinstance(details.get("added_droplets"), (int, float))
        and not isinstance(details.get("added_droplets"), bool)
        and details.get("added_droplets", 0) > 0
        for well_id, well in obj.items()
        if not str(well_id).startswith("__") and isinstance(well, Mapping)
        for details in (well.get("reagents") or {}).values()
    )


def execution_progress_storage_evidence(
    plan: ExecutionPlan,
    payload: Any,
) -> dict[str, Any]:
    decoded = decode_execution_progress(plan, payload)
    encoded_size = len(
        serialize_execution_progress(decoded.payload).encode("utf-8")
    )
    v1_size = len(
        serialize_execution_progress(
            encode_execution_progress_v1(plan, decoded.progress_wells)
        ).encode("utf-8")
    )
    return {
        "schema_name": (
            SCHEMA_NAME if decoded.schema_version == SCHEMA_VERSION else None
        ),
        "schema_version": decoded.schema_version,
        "encoded_size_bytes": encoded_size,
        "schema_v1_equivalent_size_bytes": v1_size,
        "encoded_to_v1_ratio": encoded_size / v1_size if v1_size else 1.0,
        "size_reduction_fraction": (
            1.0 - (encoded_size / v1_size) if v1_size else 0.0
        ),
    }
