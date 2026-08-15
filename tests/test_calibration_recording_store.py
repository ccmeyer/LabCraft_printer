import json
from pathlib import Path

import numpy as np
import pytest

from CalibrationRecordingStore import (
    CalibrationRecordingStore,
    CalibrationStoreConflictError,
    CalibrationStoreCorruptionError,
    CalibrationStoreValidationError,
    canonical_json_bytes,
    semantic_sha256,
)


class _Clock:
    def __init__(self):
        self.index = 0

    def __call__(self):
        self.index += 1
        return f"2026-08-15T00:00:{self.index:02d}Z"


def _store(tmp_path, **kwargs):
    return CalibrationRecordingStore(tmp_path, clock=_Clock(), **kwargs)


def _run(store, *, run_id="run_unit_0001", kind="calibration"):
    return store.start_run(
        calibration_session_id="session-unit-1",
        process_run_id=run_id,
        process_name="UnitCalibrationProcess",
        phase_name="pressure_sweep_characterization",
        result_kind=kind,
        identity={
            "printer_head_id": "head-unit-1",
            "stock_id": "stock-unit-1",
            "reagent_name": "Unit Reagent",
        },
        capture_policy_requested="structured_only",
    )


def test_canonical_json_golden_vector_and_finite_validation():
    value = {"z": np.int64(3), "a": [np.float64(1.25), True, None]}
    assert canonical_json_bytes(value) == b'{"a":[1.25,true,null],"z":3}'
    assert semantic_sha256(value) == "2d613f4b4465c46cb3534789f69e841cddb5043e71e3d98d4df33d7bdb04a4bc"
    with pytest.raises(CalibrationStoreValidationError, match="non-finite"):
        canonical_json_bytes({"bad": float("nan")})


def test_store_writes_valid_update_result_meta_and_index(tmp_path):
    store = _store(tmp_path)
    run = _run(store)
    payload = {
        "timestamp": "2026-08-15T00:00:10Z",
        "phase": "pressure_sweep_characterization",
        "settings": {"print_pressure": 1.2},
        "meta": {"run_id": "session-unit-1"},
        "result": {"mean_volume": 10.0},
    }
    update = store.append_update(
        run,
        payload,
        legacy_source={
            "source_run_id": "session-unit-1",
            "source_phase_key": "pressure_sweep_characterization",
            "source_step_index": 0,
        },
    )
    assert store.record_parity(
        run, update_id=update.update_id, legacy_payload=payload
    )
    commit = store.finalize_run(
        run,
        outcome="completed",
        summary_projection={"application_eligible": True, "rows": []},
    )

    validated = store.validate_run(run.run_dir)
    assert validated["result"] == commit.result.document
    assert validated["result"]["update_ids"] == [update.update_id]
    assert validated["result"]["result_sha256"] == semantic_sha256(
        {
            key: value
            for key, value in validated["result"].items()
            if key != "result_sha256"
        }
    )
    index_rows, ignored_tail = store.read_jsonl(store.index_path)
    assert ignored_tail is False
    assert [row["result_id"] for row in index_rows] == [commit.result.result_id]
    meta = json.loads(run.meta_path.read_text(encoding="utf-8"))
    assert meta["schema_version"] == 2
    assert meta["canonical_update_count"] == 1
    assert meta["parity_matched_count"] == 1
    assert meta["result_sha256"] == validated["result"]["result_sha256"]


def test_completed_calibration_without_update_is_storage_error(tmp_path):
    store = _store(tmp_path)
    run = _run(store)
    commit = store.finalize_run(run, outcome="completed")
    assert commit.result.document["outcome"] == "storage_error"
    assert commit.result.document["warnings"][-1]["kind"] == (
        "completed_calibration_missing_update"
    )


def test_run_identity_collision_is_rejected_without_overwrite(tmp_path):
    store = _store(tmp_path)
    _run(store)
    with pytest.raises(CalibrationStoreConflictError, match="already exists"):
        _run(store)


def test_trailing_jsonl_recovery_and_interior_corruption(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_bytes(b'{"a":1}\n{"partial"')
    rows, ignored = CalibrationRecordingStore.read_jsonl(
        path, allow_incomplete_trailing_line=True
    )
    assert rows == [{"a": 1}]
    assert ignored is True

    path.write_bytes(b'{"a":1}\nnot-json\n{"b":2}\n')
    with pytest.raises(CalibrationStoreCorruptionError, match="invalid JSONL"):
        CalibrationRecordingStore.read_jsonl(
            path, allow_incomplete_trailing_line=True
        )


def test_rebuild_index_is_deterministic_and_leaves_runs_unchanged(tmp_path):
    store = _store(tmp_path)
    for ordinal in (1, 2):
        run = _run(store, run_id=f"run_unit_{ordinal:04d}")
        store.append_update(run, {"phase": run.phase_name, "value": ordinal})
        store.finalize_run(run, outcome="completed")
    result_hashes = {
        path: semantic_sha256(json.loads(path.read_text(encoding="utf-8")))
        for path in Path(store.recordings_root).glob("*/*/result.json")
    }
    rebuilt_a = tmp_path / "rebuilt-a.jsonl"
    rebuilt_b = tmp_path / "rebuilt-b.jsonl"
    report_a = store.rebuild_index(output_path=rebuilt_a)
    report_b = store.rebuild_index(output_path=rebuilt_b)
    assert report_a["valid_result_count"] == 2
    assert report_a["semantic_sha256"] == report_b["semantic_sha256"]
    assert rebuilt_a.read_bytes() == rebuilt_b.read_bytes()
    assert result_hashes == {
        path: semantic_sha256(json.loads(path.read_text(encoding="utf-8")))
        for path in Path(store.recordings_root).glob("*/*/result.json")
    }
