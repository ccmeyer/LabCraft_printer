from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping
import uuid

from ExecutionPlan import (
    ExecutionDispense,
    ExecutionPlan,
    ExecutionPlanState,
    ExecutionStock,
    ExecutionWell,
    load_execution_plan,
    save_execution_plan,
)


REVISION_DIRECTORY_NAME = "execution_plan_revisions"


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def revision_file_name(revision: int) -> str:
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("Execution-plan revisions must be positive integers.")
    return f"revision_{revision:06d}.json"


def revision_file_path(revision_dir: str | Path, revision: int) -> Path:
    return Path(revision_dir) / revision_file_name(revision)


def persist_immutable_revision(
    revision_dir: str | Path,
    plan: ExecutionPlan,
) -> str:
    directory = Path(revision_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = revision_file_path(directory, plan.plan_revision)
    if path.exists():
        existing = load_execution_plan(path)
        if existing != plan:
            raise RuntimeError(
                f"Immutable execution-plan revision {plan.plan_revision} already exists with different content."
            )
        return "reused"
    save_execution_plan(path, plan)
    return "created"


def validate_revision_history(
    revision_dir: str | Path,
    *,
    latest_plan: ExecutionPlan | None = None,
) -> tuple[ExecutionPlan, ...]:
    directory = Path(revision_dir)
    if not directory.exists():
        return ()
    paths = sorted(directory.glob("revision_*.json"))
    plans = tuple(load_execution_plan(path) for path in paths)
    if not plans:
        return ()
    plan_id = plans[0].plan_id
    design_hash = plans[0].design_sha256
    created_at = plans[0].created_at_utc
    plate = plans[0].plate
    volume_basis = plans[0].volume_basis
    for expected, (path, plan) in enumerate(zip(paths, plans), start=1):
        if path.name != revision_file_name(expected):
            raise RuntimeError(
                "Execution-plan revision history contains a malformed or noncontiguous filename."
            )
        if plan.plan_revision != expected:
            raise RuntimeError("Execution-plan revision history is not contiguous from revision 1.")
        if plan.plan_id != plan_id:
            raise RuntimeError("Execution-plan revision history contains multiple plan IDs.")
        if plan.design_sha256 != design_hash:
            raise RuntimeError("Execution-plan revision history changes the frozen design hash.")
        if plan.created_at_utc != created_at:
            raise RuntimeError("Execution-plan revision history changes the creation timestamp.")
        if plan.plate != plate or plan.volume_basis != volume_basis:
            raise RuntimeError("Execution-plan revision history changes frozen plate or volume-basis facts.")
        if expected > 1:
            previous = plans[expected - 2]
            if previous.state is ExecutionPlanState.PREPARED:
                if plan.state is not ExecutionPlanState.ACTIVE:
                    raise RuntimeError("Prepared execution plans may transition only to active.")
                if previous.stocks != plan.stocks or previous.wells != plan.wells:
                    raise RuntimeError("The prepared-to-active lock transition changed execution facts.")
            elif plan.state is not previous.state:
                raise RuntimeError("Slice 4 revision history contains an unsupported lifecycle transition.")
            if previous.locked_at_utc is not None and (
                plan.locked_at_utc != previous.locked_at_utc
                or plan.lock_reason != previous.lock_reason
            ):
                raise RuntimeError("Execution-plan lock metadata changed after the first lock.")
    if latest_plan is not None and plans[-1] != latest_plan:
        raise RuntimeError("execution_plan.json does not exactly match the latest immutable revision.")
    return plans


def build_locked_revision(
    plan: ExecutionPlan,
    *,
    reason: str,
    timestamp_utc: str | None = None,
) -> ExecutionPlan:
    if plan.state is ExecutionPlanState.ACTIVE:
        return plan
    if plan.state is not ExecutionPlanState.PREPARED:
        raise ValueError(f"Cannot lock an execution plan in state {plan.state.value!r}.")
    if reason not in {"calibration_started", "printing_started"}:
        raise ValueError("Execution-plan lock reason must be calibration_started or printing_started.")
    timestamp = timestamp_utc or utc_now_text()
    return replace(
        plan,
        plan_revision=plan.plan_revision + 1,
        state=ExecutionPlanState.ACTIVE,
        updated_at_utc=timestamp,
        locked_at_utc=timestamp,
        lock_reason=reason,
    )


def build_calibrated_revision(
    plan: ExecutionPlan,
    *,
    stock_id: str,
    effective_volume_nL: float,
    printing_mode: str,
    printer_head_id: str,
    calibration_record_key: str,
    target_counts_by_well: Mapping[str, Mapping[str, int]],
    timestamp_utc: str | None = None,
) -> ExecutionPlan:
    if plan.state is not ExecutionPlanState.ACTIVE:
        raise ValueError("Calibration revisions require an active execution plan.")
    stock_lookup = {stock.stock_id: stock for stock in plan.stocks}
    if stock_id not in stock_lookup:
        raise ValueError(f"Execution plan contains no stock {stock_id!r}.")
    try:
        parsed_record_id = uuid.UUID(calibration_record_key)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Calibration record key must be a canonical UUID.") from exc
    if str(parsed_record_id) != calibration_record_key:
        raise ValueError("Calibration record key must be a canonical UUID.")
    timestamp = timestamp_utc or utc_now_text()
    stocks = tuple(
        replace(
            stock,
            effective_volume_nL=float(effective_volume_nL),
            printing_mode=str(printing_mode),
            printer_head_id=str(printer_head_id),
            calibration_record_key=str(calibration_record_key),
        )
        if stock.stock_id == stock_id
        else stock
        for stock in plan.stocks
    )
    revised_stock_lookup: dict[str, ExecutionStock] = {
        stock.stock_id: stock for stock in stocks
    }
    expected_wells = {well.well_id for well in plan.wells}
    if set(target_counts_by_well) != expected_wells:
        raise ValueError("Calibration target map must contain exactly the execution-plan wells.")

    wells = []
    for old_well in plan.wells:
        counts = target_counts_by_well[old_well.well_id]
        if set(counts) - set(revised_stock_lookup):
            raise ValueError(f"Calibration targets for {old_well.well_id} reference unknown stocks.")
        dispenses = tuple(
            ExecutionDispense(stock_id=str(target_stock_id), target_dispenses=count)
            for target_stock_id, count in counts.items()
        )
        expected = sum(
            dispense.target_dispenses
            * revised_stock_lookup[dispense.stock_id].effective_volume_nL
            for dispense in dispenses
        )
        wells.append(
            ExecutionWell(
                well_id=old_well.well_id,
                reaction_id=old_well.reaction_id,
                dispenses=dispenses,
                expected_printed_volume_nL=expected,
            )
        )

    return replace(
        plan,
        plan_revision=plan.plan_revision + 1,
        updated_at_utc=timestamp,
        stocks=stocks,
        wells=tuple(wells),
    )
