import hashlib

from CalibrationRecordingReader import repair_calibration_index
from CalibrationRecordingStore import CalibrationRecordingStore


def _completed_run(root):
    store = CalibrationRecordingStore(root, clock=lambda: "2026-08-15T11:00:00Z")
    run = store.start_run(
        calibration_session_id="session-repair",
        process_run_id="run_repair_0001",
        process_name="PressureCalibrationProcess",
        phase_name="pressure_calibration",
        result_kind="calibration",
        identity={"printer_head_id": "head-1", "stock_id": "stock-1"},
    )
    store.append_update(run, {"phase": "pressure_calibration", "result": {"pressure_psi": 1.2}})
    store.finalize_run(run, outcome="completed")
    return store, run


def test_index_repair_is_dry_run_by_default_and_apply_backs_up(tmp_path):
    store, run = _completed_run(tmp_path)
    original = store.index_path.read_bytes()
    store.index_path.write_bytes(b"broken\n")
    before_result = hashlib.sha256(run.result_path.read_bytes()).hexdigest()

    preview = repair_calibration_index(tmp_path)
    assert preview["apply"] is False
    assert store.index_path.read_bytes() == b"broken\n"
    assert preview["changed"] is True

    applied = repair_calibration_index(tmp_path, apply=True)
    assert applied["apply"] is True
    assert store.index_path.read_bytes() == original
    assert applied["backup_path"]
    assert hashlib.sha256(run.result_path.read_bytes()).hexdigest() == before_result

