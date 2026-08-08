"""Deterministic, fail-closed dispense-count evidence for SIL journeys."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


def _count(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _identity(value: Any, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{label} must be non-empty")
    return normalized


@dataclass(frozen=True, order=True)
class StockWellCount:
    """One exact droplet count keyed by authoritative stock and well identity."""

    stock_id: str
    well_id: str
    droplets: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_id", _identity(self.stock_id, "stock_id"))
        object.__setattr__(self, "well_id", _identity(self.well_id, "well_id"))
        object.__setattr__(
            self,
            "droplets",
            _count(self.droplets, "droplets"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_id": self.stock_id,
            "well_id": self.well_id,
            "droplets": self.droplets,
        }


def normalize_stock_well_counts(
    rows: Iterable[StockWellCount | Mapping[str, Any]],
    *,
    label: str,
) -> tuple[StockWellCount, ...]:
    normalized: list[StockWellCount] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(rows):
        row = raw if isinstance(raw, StockWellCount) else StockWellCount(
            stock_id=raw.get("stock_id"),
            well_id=raw.get("well_id"),
            droplets=raw.get("droplets"),
        )
        key = (row.stock_id, row.well_id)
        if key in seen:
            raise ValueError(f"{label} contains duplicate stock/well identity {key!r}")
        seen.add(key)
        normalized.append(row)
    return tuple(sorted(normalized))


def count_rows_json(rows: Iterable[StockWellCount]) -> list[dict[str, Any]]:
    return [row.to_dict() for row in normalize_stock_well_counts(rows, label="counts")]


def plan_target_counts(plan: Any) -> tuple[StockWellCount, ...]:
    return normalize_stock_well_counts(
        (
            StockWellCount(
                stock_id=str(dispense.stock_id),
                well_id=str(well.well_id),
                droplets=_count(
                    dispense.target_dispenses,
                    f"plan {well.well_id}/{dispense.stock_id}",
                ),
            )
            for well in plan.wells
            for dispense in well.dispenses
        ),
        label="execution plan",
    )


def decoded_progress_counts(
    plan: Any,
    payload: Mapping[str, Any],
) -> tuple[tuple[StockWellCount, ...], tuple[StockWellCount, ...]]:
    from ExecutionProgressStore import decode_execution_progress

    decoded = decode_execution_progress(plan, payload)
    targets: list[StockWellCount] = []
    added: list[StockWellCount] = []
    for well_id, entry in decoded.progress_wells.items():
        for stock_id, details in entry["reagents"].items():
            targets.append(
                StockWellCount(stock_id, well_id, details["target_droplets"])
            )
            added.append(
                StockWellCount(stock_id, well_id, details["added_droplets"])
            )
    return (
        normalize_stock_well_counts(targets, label="progress targets"),
        normalize_stock_well_counts(added, label="progress added counts"),
    )


def runtime_target_counts(context: Any) -> tuple[StockWellCount, ...]:
    rows: list[StockWellCount] = []
    for well in context.model.well_plate.get_all_wells():
        reaction = well.get_assigned_reaction()
        if reaction is None:
            continue
        for stock_id, reagent in reaction.get_all_reagents().items():
            rows.append(
                StockWellCount(
                    stock_id=str(stock_id),
                    well_id=str(well.well_id),
                    droplets=_count(
                        reagent.get_target_droplets(),
                        f"runtime {well.well_id}/{stock_id}",
                    ),
                )
            )
    return normalize_stock_well_counts(rows, label="runtime targets")


def capture_count_snapshot(
    context: Any,
    *,
    include_runtime: bool = True,
) -> dict[str, Any]:
    experiment = context.experiment_model
    plan = experiment.get_execution_plan_snapshot()
    if plan is None:
        raise RuntimeError("authoritative execution plan is unavailable")
    progress_path = Path(experiment.progress_file_path)
    payload = json.loads(progress_path.read_text(encoding="utf-8"))
    progress_targets, progress_added = decoded_progress_counts(plan, payload)
    plan_targets = plan_target_counts(plan)
    runtime_targets = runtime_target_counts(context) if include_runtime else ()
    return {
        "plan_id": str(plan.plan_id),
        "plan_revision": int(plan.plan_revision),
        "plan_state": str(plan.state.value),
        "plan_targets": count_rows_json(plan_targets),
        "progress_targets": count_rows_json(progress_targets),
        "progress_added": count_rows_json(progress_added),
        "runtime_targets": count_rows_json(runtime_targets),
        "runtime_captured": bool(include_runtime),
    }


def project_single_stock_preview_counts(
    preview: Mapping[str, Any],
    *,
    stock_id: str,
    well_ids_by_row: Sequence[Sequence[str]],
) -> tuple[StockWellCount, ...]:
    table = dict(preview.get("visible_table") or {})
    headers = list(table.get("headers") or [])
    rows = list(table.get("rows") or [])
    if table.get("row_count") != len(rows):
        raise ValueError("preview row count does not match retained rows")
    if table.get("column_count") != len(headers):
        raise ValueError("preview column count does not match retained headers")
    if len(rows) != len(well_ids_by_row):
        raise ValueError("preview row-to-well projection has the wrong cardinality")
    if headers.count("Drops") != 1:
        raise ValueError("preview must contain exactly one Drops column")
    drops_column = headers.index("Drops")
    projected: list[StockWellCount] = []
    for index, (row, well_ids) in enumerate(zip(rows, well_ids_by_row)):
        if not isinstance(row, list) or len(row) != len(headers):
            raise ValueError(f"preview row {index} has the wrong column count")
        text = row[drops_column]
        if not isinstance(text, str) or not text.isascii() or not text.isdecimal():
            raise ValueError(
                f"preview row {index} Drops cell is not a single-stock integer"
            )
        if not well_ids:
            raise ValueError(f"preview row {index} has no projected wells")
        for well_id in well_ids:
            projected.append(StockWellCount(stock_id, well_id, int(text)))
    return normalize_stock_well_counts(projected, label="preview projection")


def intent_and_simulator_counts(
    lifecycle: Mapping[str, Any],
) -> tuple[tuple[StockWellCount, ...], tuple[StockWellCount, ...], dict[str, Any]]:
    begins = list(lifecycle.get("begins") or [])
    attachments = list(lifecycle.get("attachments") or [])
    dispenses = list(lifecycle.get("simulator_dispenses") or [])
    if int(lifecycle.get("simulator_dispense_overflow_count", 0) or 0) != 0:
        raise ValueError("simulator dispense evidence overflowed its retention bound")

    begin_by_id: dict[str, Mapping[str, Any]] = {}
    for row in begins:
        intent_id = _identity(row.get("intent_id"), "intent_id")
        if intent_id in begin_by_id:
            raise ValueError(f"duplicate durable intent ID {intent_id!r}")
        begin_by_id[intent_id] = row

    attachment_by_id: dict[str, int] = {}
    for row in attachments:
        intent_id = _identity(row.get("intent_id"), "attachment intent_id")
        sequence = _count(row.get("command_seq32"), "command_seq32")
        if intent_id in attachment_by_id:
            raise ValueError(f"duplicate command attachment for {intent_id!r}")
        attachment_by_id[intent_id] = sequence
    if set(attachment_by_id) != set(begin_by_id):
        raise ValueError("durable intents and command attachments differ")
    if len(set(attachment_by_id.values())) != len(attachment_by_id):
        raise ValueError("command attachments contain duplicate sequences")

    dispense_by_sequence: dict[int, Mapping[str, Any]] = {}
    for row in dispenses:
        sequence = _count(row.get("command_seq32"), "simulator command_seq32")
        if sequence in dispense_by_sequence:
            raise ValueError(f"duplicate simulator command sequence {sequence}")
        dispense_by_sequence[sequence] = row

    intent_rows: list[StockWellCount] = []
    simulator_rows: list[StockWellCount] = []
    joined_commands: list[dict[str, Any]] = []
    for intent_id, begin in begin_by_id.items():
        intent_count = StockWellCount(
            stock_id=begin.get("stock_id"),
            well_id=begin.get("well_id"),
            droplets=_count(
                begin.get("commanded_droplets"),
                f"intent {intent_id} commanded_droplets",
            ),
        )
        sequence = attachment_by_id[intent_id]
        command = dispense_by_sequence.get(sequence)
        if command is None:
            raise ValueError(f"attached simulator command {sequence} is missing")
        if command.get("command_type") != "DISPENSE":
            raise ValueError(f"attached simulator command {sequence} is not DISPENSE")
        if bool(command.get("manual")):
            raise ValueError(f"attached simulator command {sequence} is manual")
        if command.get("status") != "Completed":
            raise ValueError(f"attached simulator command {sequence} is not completed")
        simulator_count = StockWellCount(
            intent_count.stock_id,
            intent_count.well_id,
            _count(
                command.get("commanded_droplets"),
                f"simulator command {sequence} droplets",
            ),
        )
        intent_rows.append(intent_count)
        simulator_rows.append(simulator_count)
        joined_commands.append(
            {
                "intent_id": intent_id,
                "command_seq32": sequence,
                "stock_id": intent_count.stock_id,
                "well_id": intent_count.well_id,
                "intent_droplets": intent_count.droplets,
                "simulator_droplets": simulator_count.droplets,
                "status": str(command.get("status")),
            }
        )
    manual_or_unattached = [
        dict(command)
        for sequence, command in sorted(dispense_by_sequence.items())
        if sequence not in set(attachment_by_id.values())
    ]
    return (
        normalize_stock_well_counts(intent_rows, label="intent counts"),
        normalize_stock_well_counts(simulator_rows, label="simulator counts"),
        {
            "joined_commands": joined_commands,
            "unattached_dispenses": manual_or_unattached,
            "retained_dispense_count": len(dispenses),
            "retention_limit": int(
                lifecycle.get("simulator_dispense_limit", 0) or 0
            ),
            "overflow_count": int(
                lifecycle.get("simulator_dispense_overflow_count", 0) or 0
            ),
        },
    )


@dataclass(frozen=True)
class CountReconciliation:
    passed: bool
    required_layers: tuple[str, ...]
    checks: Mapping[str, bool]
    expected: Mapping[str, tuple[StockWellCount, ...]]
    observed: Mapping[str, tuple[StockWellCount, ...]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "required_layers": list(self.required_layers),
            "checks": dict(self.checks),
            "expected": {
                name: count_rows_json(rows)
                for name, rows in sorted(self.expected.items())
            },
            "observed": {
                name: count_rows_json(rows)
                for name, rows in sorted(self.observed.items())
            },
        }


def reconcile_stock_well_counts(
    *,
    expected: Mapping[str, Iterable[StockWellCount | Mapping[str, Any]]],
    observed: Mapping[str, Iterable[StockWellCount | Mapping[str, Any]]],
    required_layers: Sequence[str],
) -> CountReconciliation:
    required = tuple(str(name).strip() for name in required_layers)
    if not required or any(not name for name in required):
        raise ValueError("required count layers must be non-empty")
    if len(set(required)) != len(required):
        raise ValueError("required count layers must be unique")
    if set(expected) != set(required) or set(observed) != set(required):
        raise ValueError("expected and observed layers must exactly match required layers")
    normalized_expected = {
        name: normalize_stock_well_counts(expected[name], label=f"expected {name}")
        for name in required
    }
    normalized_observed = {
        name: normalize_stock_well_counts(observed[name], label=f"observed {name}")
        for name in required
    }
    checks = {
        name: normalized_observed[name] == normalized_expected[name]
        for name in required
    }
    return CountReconciliation(
        passed=all(checks.values()),
        required_layers=required,
        checks=checks,
        expected=normalized_expected,
        observed=normalized_observed,
    )


__all__ = [
    "CountReconciliation",
    "StockWellCount",
    "capture_count_snapshot",
    "count_rows_json",
    "decoded_progress_counts",
    "intent_and_simulator_counts",
    "normalize_stock_well_counts",
    "plan_target_counts",
    "project_single_stock_preview_counts",
    "reconcile_stock_well_counts",
    "runtime_target_counts",
]
