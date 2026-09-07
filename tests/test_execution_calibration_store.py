import json

import pytest

from ExperimentAuditLog import build_calibration_volume_warning_audit_intent
from ExecutionCalibrationStore import (
    ExecutionCalibrationDocument,
    ExecutionCalibrationRecord,
    deterministic_calibration_record_id,
    load_execution_calibrations,
    save_execution_calibrations,
)


PLAN_ID = "f33cf5d6-2f38-4ca7-86fd-74f73baac81d"


def _values():
    return {
        "stock_id": "PURE MM_1.00_x",
        "printer_head_id": "head-1",
        "factor_name": "PURE MM",
        "option_name": None,
        "is_fill": False,
        "measured_volume_nL": 143.59278258103592,
        "effective_volume_nL": 143.59278258103592,
        "pw_us": 1400,
        "pressure_psi": 1.2,
        "run_id": "run-1",
        "phase": "pressure_sweep_characterization",
        "timestamp": "2026-07-17T12:00:00Z",
        "source_row_fingerprint": ("run-1", 1400, 1.2),
        "original_printing_mode": "stream",
        "applied_printing_mode": "stream",
        "printing_mode": "stream",
        "applied_design_volume_nL": 143.59278258103592,
        "recorded_at": "2026-07-17T12:01:00Z",
        "recorded_at_utc": "2026-07-17T12:01:00Z",
    }


def _record():
    values = _values()
    return ExecutionCalibrationRecord(
        record_id=deterministic_calibration_record_id(PLAN_ID, values),
        **values,
    )


def test_record_identity_is_deterministic_and_recording_time_independent():
    first = _values()
    second = {
        **first,
        "recorded_at": "2026-07-17T12:05:00Z",
        "recorded_at_utc": "2026-07-17T12:05:00Z",
    }
    assert deterministic_calibration_record_id(PLAN_ID, first) == deterministic_calibration_record_id(PLAN_ID, second)


def test_sidecar_round_trip_and_unknown_fields_fail_closed(tmp_path):
    record = _record()
    document = ExecutionCalibrationDocument(plan_id=PLAN_ID, records={record.record_id: record})
    path = tmp_path / "execution_calibrations.json"
    save_execution_calibrations(path, document)
    assert load_execution_calibrations(path) == document

    payload = document.to_dict()
    payload["unexpected"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown field"):
        load_execution_calibrations(path)


def test_sidecar_rejects_duplicate_json_keys(tmp_path):
    path = tmp_path / "execution_calibrations.json"
    path.write_text(
        '{"schema_name":"labcraft.execution_calibrations","schema_name":"duplicate"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        load_execution_calibrations(path)


def test_compatibility_volume_and_mode_must_match_exact_execution_values():
    values = _values()
    record_id = deterministic_calibration_record_id(PLAN_ID, values)
    with pytest.raises(ValueError, match="applied_design_volume_nL must equal"):
        ExecutionCalibrationRecord(
            record_id=record_id,
            **{**values, "applied_design_volume_nL": 100.0},
        )


def test_schema_v1_loads_with_null_canonical_references_and_upgrades_on_write(tmp_path):
    record = _record()
    payload = ExecutionCalibrationDocument(
        plan_id=PLAN_ID, records={record.record_id: record}
    ).to_dict()
    payload["schema_version"] = 1
    payload.pop("volume_warning_audits")
    for name in ("result_id", "result_sha256", "process_run_id", "update_id"):
        payload["records"][record.record_id].pop(name)
    path = tmp_path / "execution_calibrations.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_execution_calibrations(path)
    assert loaded.records[record.record_id].result_id is None
    save_execution_calibrations(path, loaded)
    upgraded = json.loads(path.read_text(encoding="utf-8"))
    assert upgraded["schema_version"] == 3
    assert upgraded["records"][record.record_id]["result_id"] is None
    assert upgraded["volume_warning_audits"] == {}

def test_schema_v2_loads_with_empty_warning_outbox(tmp_path):
    record = _record()
    payload = ExecutionCalibrationDocument(
        plan_id=PLAN_ID, records={record.record_id: record}
    ).to_dict()
    payload["schema_version"] = 2
    payload.pop("volume_warning_audits")
    path = tmp_path / "execution_calibrations.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_execution_calibrations(path)

    assert loaded.volume_warning_audits == {}


def test_volume_warning_outbox_round_trips_and_requires_matching_key(tmp_path):
    intent = build_calibration_volume_warning_audit_intent(
        identity={"plan_id": PLAN_ID, "plan_revision": 3},
        timestamp_utc="2026-08-30T12:00:00Z",
        details={
            "plan_id": PLAN_ID,
            "plan_revision": 3,
            "volume_warning": {
                "code": "calibration_volume_tolerance_exceeded",
                "affected_row_count": 1,
            },
        },
    )
    document = ExecutionCalibrationDocument(
        plan_id=PLAN_ID,
        volume_warning_audits={intent["event_id"]: intent},
    )
    path = tmp_path / "execution_calibrations.json"
    save_execution_calibrations(path, document)

    assert load_execution_calibrations(path) == document

    with pytest.raises(ValueError, match="key must equal event_id"):
        ExecutionCalibrationDocument(
            plan_id=PLAN_ID,
            volume_warning_audits={"wrong": intent},
        )
