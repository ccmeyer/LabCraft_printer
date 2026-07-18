from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import ExecutionPlan as execution_plan_module
from ExecutionPlan import (
    ExecutionDispense,
    ExecutionPlan,
    ExecutionPlanIOError,
    ExecutionPlanState,
    ExecutionPlanValidationError,
    ExecutionPlate,
    ExecutionStock,
    ExecutionVolumeBasis,
    ExecutionWell,
    ProgressExecutionReference,
    canonical_sha256,
    load_execution_plan,
    new_plan_id,
    save_execution_plan,
)


PLAN_ID = "f33cf5d6-2f38-4ca7-86fd-74f73baac81d"
DESIGN_HASH = "a" * 64
CREATED_AT = "2026-07-17T12:00:00Z"


def _stock(
    stock_id: str = "PURE MM_1.11_x",
    *,
    effective_volume_nL: float = 143.59278258103592,
) -> ExecutionStock:
    return ExecutionStock(
        stock_id=stock_id,
        factor_name="PURE MM",
        option_name=None,
        reagent_name="PURE MM",
        concentration=1.11,
        units="x",
        printing_mode="stream",
        intended_volume_nL=60.0,
        effective_volume_nL=effective_volume_nL,
        printer_head_id=None,
        calibration_record_key=None,
    )


def _valid_plan(*, state: ExecutionPlanState = ExecutionPlanState.PREPARED) -> ExecutionPlan:
    stock = _stock()
    locked = state is not ExecutionPlanState.PREPARED
    return ExecutionPlan(
        plan_id=PLAN_ID,
        plan_revision=1,
        state=state,
        design_sha256=DESIGN_HASH,
        created_at_utc=CREATED_AT,
        updated_at_utc="2026-07-17T12:05:00Z" if locked else CREATED_AT,
        locked_at_utc="2026-07-17T12:01:00Z" if locked else None,
        lock_reason="calibration_started" if locked else None,
        plate=ExecutionPlate(name="shallow-384_well_plate", rows=16, columns=24),
        volume_basis=ExecutionVolumeBasis(
            target_printed_volume_nL=2500.0,
            final_reaction_volume_nL=2500.0,
            design_optimization_tolerance_nL=50.0,
        ),
        stocks=(stock,),
        wells=(
            ExecutionWell(
                well_id="C3",
                reaction_id="R1",
                dispenses=(ExecutionDispense(stock.stock_id, 16),),
                expected_printed_volume_nL=16 * stock.effective_volume_nL,
            ),
        ),
    )


def _valid_payload() -> dict:
    return _valid_plan().to_dict()


def test_round_trip_preserves_exact_effective_volume(tmp_path):
    plan = _valid_plan()
    path = tmp_path / "execution_plan.json"

    save_execution_plan(path, plan)
    loaded = load_execution_plan(path)

    assert loaded == plan
    assert loaded.stocks[0].effective_volume_nL == 143.59278258103592
    assert json.loads(path.read_text(encoding="utf-8")) == plan.to_dict()
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_progress_execution_reference_round_trip_is_strict():
    reference = ProgressExecutionReference(PLAN_ID, 3)

    assert ProgressExecutionReference.from_dict(reference.to_dict()) == reference
    assert reference.to_dict() == {
        "schema_version": 1,
        "plan_id": PLAN_ID,
        "plan_revision": 3,
    }


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda payload: payload.update(extra=True), "unknown field"),
        (lambda payload: payload.update(schema_version=2), "unsupported version"),
        (lambda payload: payload.update(plan_id="not-a-uuid"), "valid UUID"),
        (lambda payload: payload.update(plan_revision=0), "at least 1"),
        (lambda payload: payload.update(plan_revision=True), "must be an integer"),
    ],
)
def test_progress_execution_reference_rejects_invalid_payloads(mutation, message):
    payload = ProgressExecutionReference(PLAN_ID, 1).to_dict()
    mutation(payload)

    with pytest.raises(ExecutionPlanValidationError, match=message):
        ProgressExecutionReference.from_dict(payload)


def test_multi_stock_multi_well_serialization_is_stably_sorted():
    pure = _stock()
    utp = ExecutionStock(
        stock_id="UTP_950.00_nM",
        factor_name="UTP",
        option_name="UTP",
        reagent_name="UTP",
        concentration=950.0,
        units="nM",
        printing_mode="droplet",
        intended_volume_nL=None,
        effective_volume_nL=10.4,
        printer_head_id="head-2",
        calibration_record_key="record-2",
    )
    plan = ExecutionPlan(
        plan_id=PLAN_ID,
        plan_revision=3,
        state=ExecutionPlanState.ACTIVE,
        design_sha256=DESIGN_HASH,
        created_at_utc=CREATED_AT,
        updated_at_utc="2026-07-17T12:10:00Z",
        locked_at_utc="2026-07-17T12:01:00Z",
        lock_reason="calibration_started",
        plate=ExecutionPlate("shallow-384_well_plate", 16, 24),
        volume_basis=ExecutionVolumeBasis(2500.0, 2500.0, 50.0),
        stocks=(utp, pure),
        wells=(
            ExecutionWell(
                "M5",
                "R2",
                (ExecutionDispense(utp.stock_id, 25), ExecutionDispense(pure.stock_id, 16)),
                25 * 10.4 + 16 * pure.effective_volume_nL,
            ),
            ExecutionWell(
                "A1",
                "R1",
                (ExecutionDispense(pure.stock_id, 16),),
                16 * pure.effective_volume_nL,
            ),
        ),
    )

    payload = plan.to_dict()

    assert list(payload["stocks"]) == [pure.stock_id, utp.stock_id]
    assert list(payload["wells"]) == ["A1", "M5"]
    assert list(payload["wells"]["M5"]["reagents"]) == [pure.stock_id, utp.stock_id]
    assert ExecutionPlan.from_dict(payload) == plan


def test_to_dict_returns_independent_nested_data():
    plan = _valid_plan()
    payload = plan.to_dict()

    payload["stocks"][plan.stocks[0].stock_id]["effective_volume_nL"] = 999.0
    payload["wells"]["C3"]["reagents"][plan.stocks[0].stock_id]["target_dispenses"] = 1

    assert plan.stocks[0].effective_volume_nL == 143.59278258103592
    assert plan.wells[0].dispenses[0].target_dispenses == 16


def test_canonical_hash_is_order_independent_and_rejects_nan():
    left = {"metadata": {"b": 2, "a": 1}, "factors": ["x"]}
    right = {"factors": ["x"], "metadata": {"a": 1, "b": 2}}

    assert canonical_sha256(left) == canonical_sha256(right)
    assert len(canonical_sha256(left)) == 64
    with pytest.raises(ExecutionPlanValidationError, match="canonically serialized"):
        canonical_sha256({"bad": float("nan")})


def test_new_plan_id_returns_canonical_unique_uuids():
    first = new_plan_id()
    second = new_plan_id()

    assert first != second
    assert ExecutionPlan.from_dict({**_valid_payload(), "plan_id": first}).plan_id == first


def test_noncanonical_uuid_text_is_rejected():
    payload = _valid_payload()
    payload["plan_id"] = PLAN_ID.upper()

    with pytest.raises(ExecutionPlanValidationError, match="canonical UUID form"):
        ExecutionPlan.from_dict(payload)


def test_unsupported_schema_is_reported_before_newer_unknown_fields():
    payload = _valid_payload()
    payload["schema_version"] = 2
    payload["new_v2_field"] = True

    with pytest.raises(ExecutionPlanValidationError, match="unsupported version 2"):
        ExecutionPlan.from_dict(payload)


@pytest.mark.parametrize(
    "mutate, match",
    [
        (lambda p: p.update(unknown_top=True), "unknown field"),
        (lambda p: p["plate"].update(unknown_plate=True), "unknown field"),
        (lambda p: p["volume_basis"].update(unknown_volume=True), "unknown field"),
        (
            lambda p: next(iter(p["stocks"].values())).update(unknown_stock=True),
            "unknown field",
        ),
        (lambda p: p["wells"]["C3"].update(unknown_well=True), "unknown field"),
        (
            lambda p: next(iter(p["wells"]["C3"]["reagents"].values())).update(
                unknown_dispense=True
            ),
            "unknown field",
        ),
        (lambda p: p.update(schema_name="other"), "schema_name"),
        (lambda p: p.update(schema_version=2), "unsupported version 2"),
        (lambda p: p.pop("plan_id"), "missing required field"),
    ],
)
def test_strict_schema_rejects_unknown_unsupported_and_missing_fields(mutate, match):
    payload = _valid_payload()
    mutate(payload)

    with pytest.raises(ExecutionPlanValidationError, match=match):
        ExecutionPlan.from_dict(payload)


@pytest.mark.parametrize(
    "mutate, match",
    [
        (lambda p: p.update(plan_revision=True), "must be an integer"),
        (lambda p: p.update(plan_revision=0), "at least 1"),
        (lambda p: p.update(plan_id="not-a-uuid"), "valid UUID"),
        (lambda p: p.update(design_sha256="ABC"), "lowercase SHA-256"),
        (lambda p: p.update(state="unknown"), "must be one of"),
        (lambda p: p.update(created_at_utc="2026-07-17"), "ending in 'Z'"),
        (
            lambda p: p.update(updated_at_utc="2026-07-17T11:59:00Z"),
            "must not precede",
        ),
        (
            lambda p: p["volume_basis"].update(target_printed_volume_nL=float("inf")),
            "must be finite",
        ),
        (
            lambda p: p["volume_basis"].update(design_optimization_tolerance_nL=-1),
            "at least 0",
        ),
        (
            lambda p: next(iter(p["stocks"].values())).update(printing_mode="spray"),
            "must be one of",
        ),
        (
            lambda p: next(iter(p["stocks"].values())).update(effective_volume_nL=0),
            "greater than 0",
        ),
        (
            lambda p: next(iter(p["wells"]["C3"]["reagents"].values())).update(
                target_dispenses=-1
            ),
            "at least 0",
        ),
    ],
)
def test_invalid_scalar_values_fail_closed(mutate, match):
    payload = _valid_payload()
    mutate(payload)

    with pytest.raises(ExecutionPlanValidationError, match=match):
        ExecutionPlan.from_dict(payload)


@pytest.mark.parametrize("state", ["active", "completed", "aborted"])
def test_locked_states_require_lock_metadata(state):
    payload = _valid_payload()
    payload["state"] = state

    with pytest.raises(ExecutionPlanValidationError, match="require lock metadata"):
        ExecutionPlan.from_dict(payload)


def test_prepared_state_rejects_lock_metadata():
    payload = _valid_payload()
    payload["locked_at_utc"] = CREATED_AT
    payload["lock_reason"] = "calibration_started"

    with pytest.raises(ExecutionPlanValidationError, match="must not contain lock metadata"):
        ExecutionPlan.from_dict(payload)


@pytest.mark.parametrize("well_id", ["A0", "a1", "Q1", "A25", "not-a-well"])
def test_invalid_or_out_of_bounds_wells_are_rejected(well_id):
    payload = _valid_payload()
    payload["wells"] = {well_id: payload["wells"].pop("C3")}

    with pytest.raises(ExecutionPlanValidationError, match="plate notation|outside"):
        ExecutionPlan.from_dict(payload)


def test_unknown_stock_reference_is_rejected():
    payload = _valid_payload()
    reagent = payload["wells"]["C3"]["reagents"].pop("PURE MM_1.11_x")
    payload["wells"]["C3"]["reagents"]["missing_stock"] = reagent

    with pytest.raises(ExecutionPlanValidationError, match="undeclared stock"):
        ExecutionPlan.from_dict(payload)


def test_incorrect_expected_volume_is_rejected():
    payload = _valid_payload()
    payload["wells"]["C3"]["expected_printed_volume_nL"] += 0.01

    with pytest.raises(ExecutionPlanValidationError, match="must equal the dispense total"):
        ExecutionPlan.from_dict(payload)


def test_duplicate_json_keys_are_rejected(tmp_path):
    path = tmp_path / "execution_plan.json"
    path.write_text('{"schema_name":"first","schema_name":"second"}', encoding="utf-8")

    with pytest.raises(ExecutionPlanValidationError, match="duplicate JSON object key"):
        load_execution_plan(path)


def test_invalid_json_is_a_validation_error(tmp_path):
    path = tmp_path / "execution_plan.json"
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(ExecutionPlanValidationError, match="invalid execution-plan JSON"):
        load_execution_plan(path)


def test_missing_parent_is_an_io_error(tmp_path):
    path = tmp_path / "missing" / "execution_plan.json"

    with pytest.raises(ExecutionPlanIOError, match="parent directory does not exist"):
        save_execution_plan(path, _valid_plan())
    assert not path.exists()


def test_failed_atomic_replace_preserves_existing_file_and_cleans_temp(tmp_path, monkeypatch):
    path = tmp_path / "execution_plan.json"
    original = b"original-data\n"
    path.write_bytes(original)

    def fail_replace(_source, _destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(execution_plan_module.os, "replace", fail_replace)

    with pytest.raises(ExecutionPlanIOError, match="simulated replace failure"):
        save_execution_plan(path, _valid_plan())

    assert path.read_bytes() == original
    assert list(tmp_path.glob("._tmp_*.json")) == []


def test_validation_failure_does_not_touch_existing_file(tmp_path):
    path = tmp_path / "execution_plan.json"
    path.write_text("original\n", encoding="utf-8")

    with pytest.raises(ExecutionPlanValidationError, match="must be an ExecutionPlan"):
        save_execution_plan(path, object())

    assert path.read_text(encoding="utf-8") == "original\n"
    assert list(tmp_path.glob("._tmp_*.json")) == []


def test_module_import_does_not_load_qt_model_or_hardware_modules():
    interface_dir = Path(__file__).resolve().parents[1] / "FreeRTOS-interface"
    script = (
        "import sys; import ExecutionPlan; "
        "assert 'Model' not in sys.modules; "
        "assert 'PySide6' not in sys.modules; "
        "assert 'hardware.profile' not in sys.modules"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=interface_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
