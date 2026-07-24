import json
from pathlib import Path

import pytest

from ExecutionPlan import (
    ExecutionDispense,
    ExecutionPlan,
    ExecutionPlanState,
    ExecutionPlate,
    ExecutionStock,
    ExecutionVolumeBasis,
    ExecutionWell,
    canonical_sha256,
    save_execution_plan,
)
from ExecutionPlanRevision import persist_immutable_revision
from ExecutionProgressStore import (
    ExecutionProgressValidationError,
    decode_execution_progress,
    encode_execution_progress_v1,
    encode_execution_progress_v2,
    serialize_execution_progress,
    update_execution_progress_payload,
)
from ExecutionResumeStore import progress_fingerprint
from tools.convert_execution_progress import convert_execution_progress_to_v1


def _stock(stock_id):
    return ExecutionStock(
        stock_id=stock_id,
        factor_name=stock_id,
        option_name=None,
        reagent_name=stock_id,
        concentration=1.0,
        units="x",
        printing_mode="droplet",
        intended_volume_nL=1.0,
        effective_volume_nL=1.0,
        printer_head_id=None,
        calibration_record_key=None,
    )


def _plan():
    stocks = (_stock("stock-a"), _stock("stock-b"))
    return ExecutionPlan(
        plan_id="91e375b4-ea3d-4472-8ac3-10c3338893e2",
        plan_revision=1,
        state=ExecutionPlanState.PREPARED,
        design_sha256=canonical_sha256({"design": 1}),
        created_at_utc="2026-07-24T12:00:00Z",
        updated_at_utc="2026-07-24T12:00:00Z",
        locked_at_utc=None,
        lock_reason=None,
        plate=ExecutionPlate("test", 2, 2),
        volume_basis=ExecutionVolumeBasis(10.0, 10.0, 0.0),
        stocks=stocks,
        wells=(
            ExecutionWell(
                "A1",
                "reaction-a1",
                (ExecutionDispense("stock-a", 2),),
                2.0,
            ),
            ExecutionWell(
                "A2",
                "reaction-a2",
                (
                    ExecutionDispense("stock-a", 1),
                    ExecutionDispense("stock-b", 3),
                ),
                4.0,
            ),
        ),
    )


def _wells():
    return {
        "A1": {
            "reaction_id": "reaction-a1",
            "reagents": {
                "stock-a": {
                    "target_droplets": 2,
                    "added_droplets": 1,
                    "name": "optional v1 metadata",
                }
            },
            "completed": False,
        },
        "A2": {
            "reaction_id": "reaction-a2",
            "reagents": {
                "stock-a": {"target_droplets": 1, "added_droplets": 1},
                "stock-b": {"target_droplets": 3, "added_droplets": 3},
            },
            "completed": True,
        },
    }


def test_v2_serialization_is_deterministic_compact_and_round_trips():
    plan = _plan()
    payload = encode_execution_progress_v2(plan, _wells())

    encoded = serialize_execution_progress(payload)
    decoded = decode_execution_progress(plan, json.loads(encoded))

    assert encoded == serialize_execution_progress(payload)
    assert "\n" not in encoded
    assert ": " not in encoded
    assert decoded.schema_version == 2
    assert decoded.progress_wells["A1"]["reagents"]["stock-a"] == {
        "target_droplets": 2,
        "added_droplets": 1,
    }
    assert payload["well_order"] == ["A1", "A2"]
    assert payload["added_droplets"] == {
        "stock-a": [1, 1],
        "stock-b": [None, 3],
    }


def test_v1_and_v2_decode_to_semantically_equal_progress():
    plan = _plan()
    v1 = encode_execution_progress_v1(plan, _wells())
    v2 = encode_execution_progress_v2(plan, _wells())

    assert (
        decode_execution_progress(plan, v1).progress_wells
        == decode_execution_progress(plan, v2).progress_wells
    )
    assert serialize_execution_progress(v1) == json.dumps(v1, indent=4)


def test_v1_reader_preserves_allowed_optional_metadata_and_plate_metadata():
    plan = _plan()
    payload = encode_execution_progress_v1(plan, _wells())
    payload["__plate__"]["schema_version"] = 1
    payload["A1"]["reagents"]["stock-a"]["name"] = "optional v1 metadata"
    payload["A1"]["reagents"]["stock-a"]["concentration"] = 1.0

    decoded = decode_execution_progress(plan, payload)

    assert decoded.progress_wells["A1"]["reagents"]["stock-a"]["name"] == (
        "optional v1 metadata"
    )
    assert decoded.progress_wells["A1"]["reagents"]["stock-a"]["concentration"] == 1.0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(schema_version=3),
        lambda payload: payload["well_order"].reverse(),
        lambda payload: payload["added_droplets"].pop("stock-b"),
        lambda payload: payload["added_droplets"]["stock-a"].append(0),
        lambda payload: payload["added_droplets"]["stock-b"].__setitem__(0, 0),
        lambda payload: payload["added_droplets"]["stock-a"].__setitem__(0, True),
        lambda payload: payload["added_droplets"]["stock-a"].__setitem__(0, 3),
    ],
)
def test_v2_rejects_malformed_or_plan_inconsistent_arrays(mutate):
    plan = _plan()
    payload = encode_execution_progress_v2(plan, _wells())
    mutate(payload)

    with pytest.raises(ExecutionProgressValidationError):
        decode_execution_progress(plan, payload)


def test_copy_on_write_changes_only_selected_v2_stock_array():
    plan = _plan()
    payload = encode_execution_progress_v2(plan, _wells())

    updated = update_execution_progress_payload(
        plan,
        payload,
        well_id="A1",
        stock_id="stock-a",
        added_droplets=2,
    )

    assert updated.payload is not payload
    assert updated.payload["added_droplets"] is not payload["added_droplets"]
    assert (
        updated.payload["added_droplets"]["stock-a"]
        is not payload["added_droplets"]["stock-a"]
    )
    assert (
        updated.payload["added_droplets"]["stock-b"]
        is payload["added_droplets"]["stock-b"]
    )
    assert payload["added_droplets"]["stock-a"] == [1, 1]
    assert updated.payload["added_droplets"]["stock-a"] == [2, 1]
    assert updated.progress_wells["A1"]["completed"]


def test_offline_downgrade_preserves_semantics_and_progress_fingerprint(tmp_path):
    plan = _plan()
    design = {"design": 1}
    (tmp_path / "experiment_design.json").write_text(
        json.dumps(design),
        encoding="utf-8",
    )
    save_execution_plan(tmp_path / "execution_plan.json", plan)
    persist_immutable_revision(tmp_path / "execution_plan_revisions", plan)
    v2 = encode_execution_progress_v2(plan, _wells())
    (tmp_path / "progress.json").write_text(
        serialize_execution_progress(v2),
        encoding="utf-8",
    )
    before = decode_execution_progress(plan, v2)

    result = convert_execution_progress_to_v1(tmp_path)

    converted = json.loads(
        Path(result["progress_path"]).read_text(encoding="utf-8")
    )
    after = decode_execution_progress(plan, converted)
    assert result["to_schema_version"] == 1
    assert "__execution__" in converted
    assert progress_fingerprint(after.progress_wells) == progress_fingerprint(
        before.progress_wells
    )
