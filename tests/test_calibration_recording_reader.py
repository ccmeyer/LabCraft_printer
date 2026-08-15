import json
from pathlib import Path

from CalibrationRecordingReader import CalibrationRecordingReader
from CalibrationRecordingStore import CalibrationRecordingStore
from CalibrationStorageContracts import build_terminal_summary, process_storage_contract


class _Process:
    __name__ = "PressureSweepCharacterizationProcess"


def _write_case(tmp_path, *, legacy=True, authority=True):
    store = CalibrationRecordingStore(tmp_path, clock=lambda: "2026-08-15T10:00:00Z")
    run = store.start_run(
        calibration_session_id="session-1",
        process_run_id="run_reader_0001",
        process_name="PressureSweepCharacterizationProcess",
        phase_name="pressure_sweep_characterization",
        result_kind="calibration",
        identity={"printer_head_id": "head-1", "stock_id": "stock-1", "stock_solution": "Water"},
    )
    payload = {
        "timestamp": "2026-08-15T10:00:00Z",
        "phase": "pressure_sweep_characterization",
        "settings": {"print_width": 1400},
        "result": {"pressures": [{"pressure": 1.2, "mean_volume": 9.5, "valid": True}]},
    }
    update = store.append_update(
        run,
        payload,
        legacy_source={
            "source_run_id": "session-1",
            "source_phase_key": "pressure_sweep_characterization",
            "source_step_index": 0,
        },
        include_legacy_reference=True,
    )
    legacy_payload = dict(update.document["payload"])
    store.record_parity(run, update_id=update.update_id, legacy_payload=legacy_payload)
    summary = build_terminal_summary(
        _Process(), process_storage_contract("PressureSweepCharacterizationProcess"), run, "completed"
    )
    commit = store.finalize_run(run, outcome="completed", summary_projection=summary)
    if legacy:
        legacy_run = {
            "run_id": "session-1",
            "printer_head_id": "head-1",
            "stock_id": "stock-1",
            "stock_solution": "Water",
            "steps": {"pressure_sweep_characterization": [legacy_payload]},
        }
        if authority:
            legacy_run["canonical_storage"] = {"structured_persistence_required": True}
        (tmp_path / "calibration.json").write_text(
            json.dumps({"schema_version": 1, "runs": [legacy_run]}), encoding="utf-8"
        )
    return store, run, update, commit


def test_reader_history_uses_index_projection_and_resolves_exact_bundle(tmp_path):
    _store, _run, update, commit = _write_case(tmp_path)
    reader = CalibrationRecordingReader(tmp_path)
    snapshot = reader.history_snapshot()

    assert snapshot.diagnostics["routine_result_bundle_reads"] == 0
    assert snapshot.diagnostics["routine_recursive_scans"] == 0
    assert len(snapshot.rows) == 1
    row = dict(snapshot.rows[0])
    assert row["reader_state"] == "matching_dual"
    assert row["result_id"] == commit.result.result_id
    assert row["update_id"] == update.update_id
    assert row["pressure_psi"] == 1.2

    resolved = reader.resolve_selection(row, expected_identity={"printer_head_id": "head-1", "stock_id": "stock-1"})
    assert resolved["ok"] is True
    assert resolved["bundle"]["update"]["update_id"] == update.update_id


def test_reader_detects_mutation_and_dual_write_conflict(tmp_path):
    _store, run, _update, _commit = _write_case(tmp_path)
    reader = CalibrationRecordingReader(tmp_path)
    original = dict(reader.history_snapshot().rows[0])
    result = json.loads(run.result_path.read_text(encoding="utf-8"))
    result["outcome"] = "error"
    run.result_path.write_text(json.dumps(result), encoding="utf-8")
    assert reader.resolve_selection(original)["ok"] is False

    tmp_conflict = tmp_path / "conflict"
    _write_case(tmp_conflict)
    legacy_path = tmp_conflict / "calibration.json"
    legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
    legacy["runs"][0]["steps"]["pressure_sweep_characterization"][0]["result"]["pressures"][0]["mean_volume"] = 99
    legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
    conflict = CalibrationRecordingReader(tmp_conflict).history_snapshot()
    assert dict(conflict.rows[0])["reader_state"] == "parity_conflict"
    assert dict(conflict.rows[0])["blocked"] is True


def test_reader_legacy_fallback_and_authority_missing_index(tmp_path):
    legacy_dir = tmp_path / "legacy"
    _store, _run, _update, _commit = _write_case(legacy_dir, authority=False)
    (legacy_dir / "calibration_index.jsonl").unlink()
    snapshot = CalibrationRecordingReader(legacy_dir).history_snapshot()
    assert dict(snapshot.rows[0])["reader_state"] == "canonical_invalid_legacy_fallback"
    assert dict(snapshot.rows[0])["blocked"] is False

    authority_dir = tmp_path / "authority"
    _write_case(authority_dir, authority=True)
    (authority_dir / "calibration_index.jsonl").unlink()
    snapshot = CalibrationRecordingReader(authority_dir).history_snapshot()
    assert dict(snapshot.rows[0])["reader_state"] == "unavailable"
    assert dict(snapshot.rows[0])["blocked"] is True


def test_reader_canonical_only_and_legacy_preference(tmp_path):
    _write_case(tmp_path, legacy=False)
    canonical = CalibrationRecordingReader(tmp_path).history_snapshot()
    assert dict(canonical.rows[0])["reader_state"] == "canonical_only"
    legacy = CalibrationRecordingReader(tmp_path, primary="legacy").history_snapshot()
    assert legacy.rows == ()

