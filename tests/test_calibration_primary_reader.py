from types import SimpleNamespace

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import CalibrationManager


def _manager(monkeypatch, *, authoritative="1", primary=None, fallback=None):
    monkeypatch.setenv("LABCRAFT_CALIBRATION_STORE_AUTHORITATIVE", authoritative)
    if primary is None:
        monkeypatch.delenv("LABCRAFT_CALIBRATION_PRIMARY_READER", raising=False)
    else:
        monkeypatch.setenv("LABCRAFT_CALIBRATION_PRIMARY_READER", primary)
    if fallback is not None:
        monkeypatch.setenv("LABCRAFT_CALIBRATION_LEGACY_FALLBACK", fallback)
    model = SimpleNamespace(
        machine_state_updated=SignalStub(),
        experiment_model=SimpleNamespace(),
        rack_model=SimpleNamespace(get_gripper_printer_head=lambda: None),
    )
    return CalibrationManager(model)


def test_primary_reader_flags_and_authority_rollback(monkeypatch):
    assert _manager(monkeypatch).get_calibration_reader_preference() == "canonical"
    assert _manager(monkeypatch, primary="legacy").get_calibration_reader_preference() == "legacy"
    assert _manager(monkeypatch, authoritative="0", primary="canonical").get_calibration_reader_preference() == "legacy"
    assert _manager(monkeypatch, primary="invalid").get_calibration_reader_preference() == "canonical"


def test_completed_cache_excludes_uncommitted_and_wrong_session(monkeypatch, tmp_path):
    manager = _manager(monkeypatch)
    manager.calibration_file_path = str(tmp_path / "calibration.json")
    manager.update_calibration_storage_paths(experiment_dir=tmp_path)
    manager._run_id = "session-1"
    run = SimpleNamespace(
        calibration_session_id="session-1",
        phase_name="droplet_emergence",
        updates=[{"payload": {"result": {"flash_delay": 4200}}}],
    )
    assert manager.get_emergence_time() is None
    assert manager._register_completed_canonical_run(run) is True
    assert manager.get_emergence_time() == 4200
    wrong = SimpleNamespace(calibration_session_id="other", phase_name="droplet_emergence", updates=[])
    assert manager._register_completed_canonical_run(wrong) is False
