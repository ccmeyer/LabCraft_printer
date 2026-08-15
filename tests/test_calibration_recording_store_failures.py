import json

import pytest

from CalibrationRecordingStore import (
    CalibrationRecordingStore,
    CalibrationStoreConflictError,
    CalibrationStoreDurabilityError,
    CalibrationStoreCorruptionError,
)


def _make_store(tmp_path, failed_stage):
    def _fault(stage):
        if stage == failed_stage:
            raise OSError(f"injected {stage}")

    return CalibrationRecordingStore(tmp_path, fault_hook=_fault)


@pytest.mark.parametrize(
    "stage",
    (
        "start_run.mkdir",
        "start_run.updates_create",
        "run_meta_start.write",
        "update_append.write",
        "update_append.flush",
        "update_append.fsync",
        "result_commit.write",
        "result_commit.flush",
        "result_commit.fsync",
        "result_commit.replace",
        "index_append.write",
        "index_append.flush",
        "index_append.fsync",
        "run_meta_finalize.write",
    ),
)
def test_file_operation_failures_are_typed(tmp_path, stage):
    store = _make_store(tmp_path, stage)
    if stage.startswith("start_run") or stage.startswith("run_meta_start"):
        with pytest.raises(CalibrationStoreDurabilityError):
            store.start_run(
                calibration_session_id="session-failure",
                process_run_id="run_failure",
                process_name="FailureProcess",
                phase_name="failure",
            )
        return
    run = store.start_run(
        calibration_session_id="session-failure",
        process_run_id="run_failure",
        process_name="FailureProcess",
        phase_name="failure",
        result_kind="none",
    )
    if stage.startswith("update_append"):
        with pytest.raises(CalibrationStoreDurabilityError):
            store.append_update(run, {"value": 1})
        assert run.updates == []
        return
    store.append_update(run, {"value": 1})
    with pytest.raises(CalibrationStoreDurabilityError):
        store.finalize_run(run, outcome="completed")
    if stage.startswith("index_append") or stage.startswith("run_meta_finalize"):
        assert run.result_path.is_file()


def test_corrupt_update_payload_is_rejected_by_validation(tmp_path):
    store = CalibrationRecordingStore(tmp_path)
    run = store.start_run(
        calibration_session_id="session-corrupt",
        process_run_id="run_corrupt",
        process_name="CorruptProcess",
        phase_name="corrupt",
        result_kind="none",
    )
    store.append_update(run, {"value": 1})
    store.finalize_run(run, outcome="completed")
    row = json.loads(run.updates_path.read_text(encoding="utf-8"))
    row["payload"]["value"] = 2
    run.updates_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(CalibrationStoreCorruptionError, match="payload hash"):
        store.validate_run(run.run_dir)


@pytest.mark.parametrize("failed_stage", ("index_append.write", "run_meta_finalize.write"))
def test_terminal_commit_retry_is_idempotent(tmp_path, failed_stage):
    failures_remaining = 1

    def _fault(stage):
        nonlocal failures_remaining
        if stage == failed_stage and failures_remaining:
            failures_remaining -= 1
            raise OSError(f"injected {stage}")

    store = CalibrationRecordingStore(tmp_path, fault_hook=_fault)
    run = store.start_run(
        calibration_session_id="session-retry",
        process_run_id="run_retry",
        process_name="RetryProcess",
        phase_name="retry",
        result_kind="none",
    )
    store.append_update(run, {"value": 1})
    with pytest.raises(CalibrationStoreDurabilityError):
        store.finalize_run(run, outcome="completed")

    first_result = run.result_path.read_bytes()
    commit = store.finalize_run(run, outcome="completed")
    rows, ignored = store.read_jsonl(store.index_path)

    assert ignored is False
    assert run.finalized is True
    assert run.result_path.read_bytes() == first_result
    assert len(rows) == 1
    assert rows[0]["result_id"] == commit.result.result_id


def test_terminal_retry_rejects_conflicting_existing_result(tmp_path):
    failures_remaining = 1

    def _fault(stage):
        nonlocal failures_remaining
        if stage == "index_append.write" and failures_remaining:
            failures_remaining -= 1
            raise OSError("injected index failure")

    store = CalibrationRecordingStore(tmp_path, fault_hook=_fault)
    run = store.start_run(
        calibration_session_id="session-conflict",
        process_run_id="run_conflict",
        process_name="ConflictProcess",
        phase_name="conflict",
        result_kind="none",
    )
    with pytest.raises(CalibrationStoreDurabilityError):
        store.finalize_run(run, outcome="completed")
    document = json.loads(run.result_path.read_text(encoding="utf-8"))
    document["summary_projection"] = {"changed": True}
    run.result_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(CalibrationStoreConflictError, match="conflicts"):
        store.finalize_run(run, outcome="completed")
