from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


SCHEMA_NAME = "labcraft.execution_plan"
SCHEMA_VERSION = 1
PRINTING_MODES = frozenset({"droplet", "stream"})

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WELL_ID_RE = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")


class ExecutionPlanValidationError(ValueError):
    """Raised when an execution-plan document violates the v1 contract."""


class ExecutionPlanIOError(OSError):
    """Raised when an execution-plan document cannot be read or written."""


class ExecutionPlanState(str, Enum):
    PREPARED = "prepared"
    ACTIVE = "active"
    COMPLETED = "completed"
    ABORTED = "aborted"


def _error(path: str, message: str) -> ExecutionPlanValidationError:
    return ExecutionPlanValidationError(f"{path}: {message}")


def _require_object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(path, "must be a JSON object")
    return value


def _require_fields(
    value: Any,
    *,
    fields: set[str],
    path: str,
) -> Mapping[str, Any]:
    obj = _require_object(value, path)
    actual = set(obj)
    missing = sorted(fields - actual)
    unknown = sorted(actual - fields)
    if missing:
        raise _error(path, f"missing required field(s): {', '.join(missing)}")
    if unknown:
        raise _error(path, f"unknown field(s): {', '.join(unknown)}")
    return obj


def _require_string(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise _error(path, "must be a string")
    if value != value.strip():
        raise _error(path, "must not contain leading or trailing whitespace")
    if not allow_empty and not value:
        raise _error(path, "must not be empty")
    return value


def _optional_string(value: Any, path: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, path)


def _require_int(value: Any, path: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _error(path, "must be an integer")
    if minimum is not None and value < minimum:
        raise _error(path, f"must be at least {minimum}")
    return value


def _require_number(
    value: Any,
    path: str,
    *,
    minimum: float | None = None,
    exclusive_minimum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _error(path, "must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise _error(path, "must be finite")
    if minimum is not None and number < minimum:
        raise _error(path, f"must be at least {minimum:g}")
    if exclusive_minimum is not None and number <= exclusive_minimum:
        raise _error(path, f"must be greater than {exclusive_minimum:g}")
    return number


def _optional_positive_number(value: Any, path: str) -> float | None:
    if value is None:
        return None
    return _require_number(value, path, exclusive_minimum=0.0)


def _parse_utc_timestamp(value: Any, path: str) -> datetime:
    text = _require_string(value, path)
    if not text.endswith("Z"):
        raise _error(path, "must be an ISO-8601 UTC timestamp ending in 'Z'")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise _error(path, "must be a valid ISO-8601 UTC timestamp") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise _error(path, "must use UTC")
    return parsed


def _row_number(row_text: str) -> int:
    value = 0
    for char in row_text:
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value


def _validate_well_id(well_id: str, plate: "ExecutionPlate", path: str) -> None:
    match = _WELL_ID_RE.fullmatch(well_id)
    if match is None:
        raise _error(path, "must use plate notation such as 'A1' or 'AA12'")
    row = _row_number(match.group(1))
    column = int(match.group(2))
    if row > plate.rows or column > plate.columns:
        raise _error(path, f"is outside the declared {plate.rows}x{plate.columns} plate")


@dataclass(frozen=True)
class ExecutionPlate:
    name: str
    rows: int
    columns: int

    def __post_init__(self) -> None:
        _require_string(self.name, "plate.name")
        _require_int(self.rows, "plate.rows", minimum=1)
        _require_int(self.columns, "plate.columns", minimum=1)


@dataclass(frozen=True)
class ExecutionVolumeBasis:
    target_printed_volume_nL: float
    final_reaction_volume_nL: float
    design_optimization_tolerance_nL: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_printed_volume_nL",
            _require_number(
                self.target_printed_volume_nL,
                "volume_basis.target_printed_volume_nL",
                exclusive_minimum=0.0,
            ),
        )
        object.__setattr__(
            self,
            "final_reaction_volume_nL",
            _require_number(
                self.final_reaction_volume_nL,
                "volume_basis.final_reaction_volume_nL",
                exclusive_minimum=0.0,
            ),
        )
        object.__setattr__(
            self,
            "design_optimization_tolerance_nL",
            _require_number(
                self.design_optimization_tolerance_nL,
                "volume_basis.design_optimization_tolerance_nL",
                minimum=0.0,
            ),
        )


@dataclass(frozen=True)
class ExecutionStock:
    stock_id: str
    factor_name: str
    option_name: str | None
    reagent_name: str
    concentration: float
    units: str
    printing_mode: str
    intended_volume_nL: float | None
    effective_volume_nL: float
    printer_head_id: str | None
    calibration_record_key: str | None

    def __post_init__(self) -> None:
        _require_string(self.stock_id, "stock.stock_id")
        _require_string(self.factor_name, f"stocks.{self.stock_id}.factor_name")
        _optional_string(self.option_name, f"stocks.{self.stock_id}.option_name")
        _require_string(self.reagent_name, f"stocks.{self.stock_id}.reagent_name")
        object.__setattr__(
            self,
            "concentration",
            _require_number(
                self.concentration,
                f"stocks.{self.stock_id}.concentration",
                minimum=0.0,
            ),
        )
        _require_string(self.units, f"stocks.{self.stock_id}.units")
        mode = _require_string(self.printing_mode, f"stocks.{self.stock_id}.printing_mode")
        if mode not in PRINTING_MODES:
            raise _error(
                f"stocks.{self.stock_id}.printing_mode",
                f"must be one of: {', '.join(sorted(PRINTING_MODES))}",
            )
        object.__setattr__(
            self,
            "intended_volume_nL",
            _optional_positive_number(
                self.intended_volume_nL,
                f"stocks.{self.stock_id}.intended_volume_nL",
            ),
        )
        object.__setattr__(
            self,
            "effective_volume_nL",
            _require_number(
                self.effective_volume_nL,
                f"stocks.{self.stock_id}.effective_volume_nL",
                exclusive_minimum=0.0,
            ),
        )
        _optional_string(self.printer_head_id, f"stocks.{self.stock_id}.printer_head_id")
        _optional_string(
            self.calibration_record_key,
            f"stocks.{self.stock_id}.calibration_record_key",
        )


@dataclass(frozen=True)
class ExecutionDispense:
    stock_id: str
    target_dispenses: int

    def __post_init__(self) -> None:
        _require_string(self.stock_id, "dispense.stock_id")
        _require_int(self.target_dispenses, "dispense.target_dispenses", minimum=0)


@dataclass(frozen=True)
class ExecutionWell:
    well_id: str
    reaction_id: str
    dispenses: tuple[ExecutionDispense, ...]
    expected_printed_volume_nL: float

    def __post_init__(self) -> None:
        _require_string(self.well_id, "well.well_id")
        _require_string(self.reaction_id, f"wells.{self.well_id}.reaction_id")
        dispenses = tuple(self.dispenses)
        if any(not isinstance(item, ExecutionDispense) for item in dispenses):
            raise _error(f"wells.{self.well_id}.reagents", "must contain ExecutionDispense values")
        ids = [item.stock_id for item in dispenses]
        if len(ids) != len(set(ids)):
            raise _error(f"wells.{self.well_id}.reagents", "contains duplicate stock IDs")
        object.__setattr__(self, "dispenses", tuple(sorted(dispenses, key=lambda item: item.stock_id)))
        object.__setattr__(
            self,
            "expected_printed_volume_nL",
            _require_number(
                self.expected_printed_volume_nL,
                f"wells.{self.well_id}.expected_printed_volume_nL",
                minimum=0.0,
            ),
        )


@dataclass(frozen=True)
class ExecutionPlan:
    plan_id: str
    plan_revision: int
    state: ExecutionPlanState
    design_sha256: str
    created_at_utc: str
    updated_at_utc: str
    locked_at_utc: str | None
    lock_reason: str | None
    plate: ExecutionPlate
    volume_basis: ExecutionVolumeBasis
    stocks: tuple[ExecutionStock, ...]
    wells: tuple[ExecutionWell, ...]

    def __post_init__(self) -> None:
        plan_id = _require_string(self.plan_id, "plan_id")
        try:
            parsed_id = uuid.UUID(plan_id)
        except ValueError as exc:
            raise _error("plan_id", "must be a valid UUID") from exc
        if str(parsed_id) != plan_id:
            raise _error("plan_id", "must use canonical UUID form")
        _require_int(self.plan_revision, "plan_revision", minimum=1)
        if not isinstance(self.state, ExecutionPlanState):
            raise _error("state", "must be an ExecutionPlanState")
        design_hash = _require_string(self.design_sha256, "design_sha256")
        if _SHA256_RE.fullmatch(design_hash) is None:
            raise _error("design_sha256", "must be a 64-character lowercase SHA-256 digest")

        created = _parse_utc_timestamp(self.created_at_utc, "created_at_utc")
        updated = _parse_utc_timestamp(self.updated_at_utc, "updated_at_utc")
        if updated < created:
            raise _error("updated_at_utc", "must not precede created_at_utc")

        locked = self.locked_at_utc
        reason = self.lock_reason
        if self.state is ExecutionPlanState.PREPARED:
            if locked is not None or reason is not None:
                raise _error("state", "prepared plans must not contain lock metadata")
        else:
            if locked is None or reason is None:
                raise _error("state", f"{self.state.value} plans require lock metadata")
            locked_dt = _parse_utc_timestamp(locked, "locked_at_utc")
            _require_string(reason, "lock_reason")
            if locked_dt < created or locked_dt > updated:
                raise _error("locked_at_utc", "must fall between created_at_utc and updated_at_utc")

        if not isinstance(self.plate, ExecutionPlate):
            raise _error("plate", "must be an ExecutionPlate")
        if not isinstance(self.volume_basis, ExecutionVolumeBasis):
            raise _error("volume_basis", "must be an ExecutionVolumeBasis")

        stocks = tuple(self.stocks)
        wells = tuple(self.wells)
        if not stocks:
            raise _error("stocks", "must contain at least one stock")
        if not wells:
            raise _error("wells", "must contain at least one well")
        if any(not isinstance(item, ExecutionStock) for item in stocks):
            raise _error("stocks", "must contain ExecutionStock values")
        if any(not isinstance(item, ExecutionWell) for item in wells):
            raise _error("wells", "must contain ExecutionWell values")

        stock_ids = [item.stock_id for item in stocks]
        well_ids = [item.well_id for item in wells]
        if len(stock_ids) != len(set(stock_ids)):
            raise _error("stocks", "contains duplicate stock IDs")
        if len(well_ids) != len(set(well_ids)):
            raise _error("wells", "contains duplicate well IDs")

        stock_lookup = {item.stock_id: item for item in stocks}
        for well in wells:
            _validate_well_id(well.well_id, self.plate, f"wells.{well.well_id}")
            expected = 0.0
            for dispense in well.dispenses:
                stock = stock_lookup.get(dispense.stock_id)
                if stock is None:
                    raise _error(
                        f"wells.{well.well_id}.reagents.{dispense.stock_id}",
                        "references an undeclared stock",
                    )
                expected += dispense.target_dispenses * stock.effective_volume_nL
            tolerance = max(1e-6, 1e-9 * max(1.0, expected))
            if not math.isclose(
                well.expected_printed_volume_nL,
                expected,
                rel_tol=0.0,
                abs_tol=tolerance,
            ):
                raise _error(
                    f"wells.{well.well_id}.expected_printed_volume_nL",
                    f"must equal the dispense total {expected:.12g} nL",
                )

        object.__setattr__(self, "stocks", tuple(sorted(stocks, key=lambda item: item.stock_id)))
        object.__setattr__(self, "wells", tuple(sorted(wells, key=lambda item: item.well_id)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_name": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "plan_id": self.plan_id,
            "plan_revision": self.plan_revision,
            "state": self.state.value,
            "design_sha256": self.design_sha256,
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "locked_at_utc": self.locked_at_utc,
            "lock_reason": self.lock_reason,
            "plate": {
                "name": self.plate.name,
                "rows": self.plate.rows,
                "columns": self.plate.columns,
            },
            "volume_basis": {
                "target_printed_volume_nL": self.volume_basis.target_printed_volume_nL,
                "final_reaction_volume_nL": self.volume_basis.final_reaction_volume_nL,
                "design_optimization_tolerance_nL": (
                    self.volume_basis.design_optimization_tolerance_nL
                ),
            },
            "stocks": {
                stock.stock_id: {
                    "factor_name": stock.factor_name,
                    "option_name": stock.option_name,
                    "reagent_name": stock.reagent_name,
                    "concentration": stock.concentration,
                    "units": stock.units,
                    "printing_mode": stock.printing_mode,
                    "intended_volume_nL": stock.intended_volume_nL,
                    "effective_volume_nL": stock.effective_volume_nL,
                    "printer_head_id": stock.printer_head_id,
                    "calibration_record_key": stock.calibration_record_key,
                }
                for stock in self.stocks
            },
            "wells": {
                well.well_id: {
                    "reaction_id": well.reaction_id,
                    "reagents": {
                        dispense.stock_id: {
                            "target_dispenses": dispense.target_dispenses,
                        }
                        for dispense in well.dispenses
                    },
                    "expected_printed_volume_nL": well.expected_printed_volume_nL,
                }
                for well in self.wells
            },
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "ExecutionPlan":
        top_fields = {
            "schema_name",
            "schema_version",
            "plan_id",
            "plan_revision",
            "state",
            "design_sha256",
            "created_at_utc",
            "updated_at_utc",
            "locked_at_utc",
            "lock_reason",
            "plate",
            "volume_basis",
            "stocks",
            "wells",
        }
        raw_obj = _require_object(payload, "execution_plan")
        if "schema_name" not in raw_obj:
            raise _error("execution_plan", "missing required field(s): schema_name")
        if raw_obj["schema_name"] != SCHEMA_NAME:
            raise _error("schema_name", f"must be {SCHEMA_NAME!r}")
        if "schema_version" not in raw_obj:
            raise _error("execution_plan", "missing required field(s): schema_version")
        version = _require_int(raw_obj["schema_version"], "schema_version", minimum=1)
        if version != SCHEMA_VERSION:
            raise _error("schema_version", f"unsupported version {version}")
        obj = _require_fields(raw_obj, fields=top_fields, path="execution_plan")

        plate_obj = _require_fields(
            obj["plate"],
            fields={"name", "rows", "columns"},
            path="plate",
        )
        plate = ExecutionPlate(
            name=plate_obj["name"],
            rows=plate_obj["rows"],
            columns=plate_obj["columns"],
        )

        volume_obj = _require_fields(
            obj["volume_basis"],
            fields={
                "target_printed_volume_nL",
                "final_reaction_volume_nL",
                "design_optimization_tolerance_nL",
            },
            path="volume_basis",
        )
        volume_basis = ExecutionVolumeBasis(
            target_printed_volume_nL=volume_obj["target_printed_volume_nL"],
            final_reaction_volume_nL=volume_obj["final_reaction_volume_nL"],
            design_optimization_tolerance_nL=volume_obj[
                "design_optimization_tolerance_nL"
            ],
        )

        stocks_obj = _require_object(obj["stocks"], "stocks")
        stocks: list[ExecutionStock] = []
        stock_fields = {
            "factor_name",
            "option_name",
            "reagent_name",
            "concentration",
            "units",
            "printing_mode",
            "intended_volume_nL",
            "effective_volume_nL",
            "printer_head_id",
            "calibration_record_key",
        }
        for stock_id, raw_stock in stocks_obj.items():
            stock_id = _require_string(stock_id, "stocks key")
            stock_obj = _require_fields(
                raw_stock,
                fields=stock_fields,
                path=f"stocks.{stock_id}",
            )
            stocks.append(
                ExecutionStock(
                    stock_id=stock_id,
                    factor_name=stock_obj["factor_name"],
                    option_name=stock_obj["option_name"],
                    reagent_name=stock_obj["reagent_name"],
                    concentration=stock_obj["concentration"],
                    units=stock_obj["units"],
                    printing_mode=stock_obj["printing_mode"],
                    intended_volume_nL=stock_obj["intended_volume_nL"],
                    effective_volume_nL=stock_obj["effective_volume_nL"],
                    printer_head_id=stock_obj["printer_head_id"],
                    calibration_record_key=stock_obj["calibration_record_key"],
                )
            )

        wells_obj = _require_object(obj["wells"], "wells")
        wells: list[ExecutionWell] = []
        for well_id, raw_well in wells_obj.items():
            well_id = _require_string(well_id, "wells key")
            well_obj = _require_fields(
                raw_well,
                fields={"reaction_id", "reagents", "expected_printed_volume_nL"},
                path=f"wells.{well_id}",
            )
            reagents_obj = _require_object(well_obj["reagents"], f"wells.{well_id}.reagents")
            dispenses: list[ExecutionDispense] = []
            for stock_id, raw_dispense in reagents_obj.items():
                stock_id = _require_string(stock_id, f"wells.{well_id}.reagents key")
                dispense_obj = _require_fields(
                    raw_dispense,
                    fields={"target_dispenses"},
                    path=f"wells.{well_id}.reagents.{stock_id}",
                )
                dispenses.append(
                    ExecutionDispense(
                        stock_id=stock_id,
                        target_dispenses=dispense_obj["target_dispenses"],
                    )
                )
            wells.append(
                ExecutionWell(
                    well_id=well_id,
                    reaction_id=well_obj["reaction_id"],
                    dispenses=tuple(dispenses),
                    expected_printed_volume_nL=well_obj["expected_printed_volume_nL"],
                )
            )

        state_text = _require_string(obj["state"], "state")
        try:
            state = ExecutionPlanState(state_text)
        except ValueError as exc:
            allowed = ", ".join(state.value for state in ExecutionPlanState)
            raise _error("state", f"must be one of: {allowed}") from exc

        return cls(
            plan_id=obj["plan_id"],
            plan_revision=obj["plan_revision"],
            state=state,
            design_sha256=obj["design_sha256"],
            created_at_utc=obj["created_at_utc"],
            updated_at_utc=obj["updated_at_utc"],
            locked_at_utc=obj["locked_at_utc"],
            lock_reason=obj["lock_reason"],
            plate=plate,
            volume_basis=volume_basis,
            stocks=tuple(stocks),
            wells=tuple(wells),
        )


def new_plan_id() -> str:
    return str(uuid.uuid4())


def canonical_sha256(payload: Any) -> str:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExecutionPlanValidationError(
            f"design payload cannot be canonically serialized: {exc}"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExecutionPlanValidationError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def load_execution_plan(path: str | os.PathLike[str]) -> ExecutionPlan:
    plan_path = Path(path)
    try:
        with plan_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle, object_pairs_hook=_reject_duplicate_keys)
    except ExecutionPlanValidationError:
        raise
    except json.JSONDecodeError as exc:
        raise ExecutionPlanValidationError(
            f"invalid execution-plan JSON in {plan_path}: {exc}"
        ) from exc
    except OSError as exc:
        raise ExecutionPlanIOError(f"could not read execution plan {plan_path}: {exc}") from exc
    return ExecutionPlan.from_dict(payload)


def save_execution_plan(
    path: str | os.PathLike[str],
    plan: ExecutionPlan,
) -> None:
    if not isinstance(plan, ExecutionPlan):
        raise ExecutionPlanValidationError("plan must be an ExecutionPlan")
    payload = plan.to_dict()
    ExecutionPlan.from_dict(payload)

    plan_path = Path(path)
    parent = plan_path.parent
    if not parent.is_dir():
        raise ExecutionPlanIOError(
            f"execution-plan parent directory does not exist: {parent}"
        )

    fd: int | None = None
    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(prefix="._tmp_", suffix=".json", dir=parent)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = None
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, plan_path)
        tmp_path = None
    except OSError as exc:
        raise ExecutionPlanIOError(f"could not write execution plan {plan_path}: {exc}") from exc
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            except OSError:
                pass
