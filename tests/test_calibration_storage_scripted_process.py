from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.sil.calibration_storage_contract import load_catalog
from tools.sil.calibration_storage_process import (
    CalibrationStorageContractError,
    ScriptedCalibrationProcess,
    StorageContractRunner,
    StorageContractRuntimeError,
)
from CalibrationRecordingStore import CalibrationRecordingStore
from tools.sil.session import (
    ArtifactRetentionPolicy,
    QtOwnership,
    SessionRootPolicy,
    SimulationSession,
    SimulationSessionConfigV1,
)


def _session(qapp, root: Path):
    session = SimulationSession.create(
        SimulationSessionConfigV1(
            visible=False,
            qt_ownership=QtOwnership.BORROWED,
            root_policy=SessionRootPolicy.RETAINED,
            session_root=root,
            artifact_retention=ArtifactRetentionPolicy.RETAIN,
            source_identity="calibration-storage-component-test",
        )
    )
    session.launch()
    return session


def test_scripted_process_rejects_non_simulation_before_application_access():
    _catalog, cases = load_catalog()
    with pytest.raises(StorageContractRuntimeError, match="canonical simulation"):
        ScriptedCalibrationProcess(
            object(),
            object(),
            case=cases[0],
            runtime_context=object(),
            machine=object(),
        )


def test_scripted_process_uses_real_manager_writers_and_capture_drain(qapp, tmp_path):
    session = _session(qapp, tmp_path / "session")
    try:
        _catalog, cases = load_catalog()
        selected = [
            next(case for case in cases if case.process_id == "legacy-parity-two-update"),
            next(case for case in cases if case.process_id == "key-evidence-proxy"),
            next(case for case in cases if case.process_id == "recorder-disabled-control"),
        ]
        calibration_path = tmp_path / "experiment" / "calibration.json"
        calibration_path.parent.mkdir()
        em = session.components.model.experiment_model
        em.experiment_dir_path = str(calibration_path.parent)
        em.calibration_file_path = str(calibration_path)
        runner = StorageContractRunner(
            model=session.components.model,
            controller=session.components.controller,
            machine=session.components.machine,
            app=qapp,
            calibration_file_path=calibration_path,
        )

        evidence = [runner.run_case(case) for case in selected]

        assert evidence[0].legacy_update_hashes == selected[0].expected_update_hashes
        assert evidence[0].recorder_update_hashes == selected[0].expected_update_hashes
        assert evidence[1].capture_count == 2
        assert evidence[1].capture_bytes > 0
        assert evidence[2].recording_dir is None
        assert evidence[2].recorder_update_hashes == ()
        assert runner.metrics.snapshot()["calibration_rewrite_count"] >= 7
        runner.restore()
    finally:
        assert session.close()


def test_scripted_process_writes_canonical_shadow_when_recorder_is_disabled(
    qapp, tmp_path
):
    session = _session(qapp, tmp_path / "shadow-session")
    try:
        _catalog, cases = load_catalog()
        selected = next(
            case for case in cases if case.process_id == "recorder-disabled-control"
        )
        calibration_path = tmp_path / "shadow-experiment" / "calibration.json"
        calibration_path.parent.mkdir()
        em = session.components.model.experiment_model
        em.experiment_dir_path = str(calibration_path.parent)
        em.calibration_file_path = str(calibration_path)
        runner = StorageContractRunner(
            model=session.components.model,
            controller=session.components.controller,
            machine=session.components.machine,
            app=qapp,
            calibration_file_path=calibration_path,
            shadow_store_enabled=True,
        )

        evidence = runner.run_case(selected)

        assert evidence.recording_dir is not None
        assert evidence.diagnostic_recording_enabled is False
        assert evidence.recorder_update_hashes == ()
        assert evidence.canonical_update_hashes == selected.expected_update_hashes
        assert evidence.canonical_result_kind == "none"
        assert evidence.canonical_result_outcome == "completed"
        assert evidence.canonical_index_event_count == 1
        assert evidence.canonical_valid is True
        runner.restore()
    finally:
        assert session.close()


def test_shadow_append_failure_preserves_legacy_completion(qapp, tmp_path, monkeypatch):
    session = _session(qapp, tmp_path / "shadow-failure-session")
    try:
        _catalog, cases = load_catalog()
        selected = next(
            case for case in cases if case.process_id == "legacy-parity-two-update"
        )
        calibration_path = tmp_path / "shadow-failure-experiment" / "calibration.json"
        calibration_path.parent.mkdir()
        em = session.components.model.experiment_model
        em.experiment_dir_path = str(calibration_path.parent)
        em.calibration_file_path = str(calibration_path)
        runner = StorageContractRunner(
            model=session.components.model,
            controller=session.components.controller,
            machine=session.components.machine,
            app=qapp,
            calibration_file_path=calibration_path,
            shadow_store_enabled=True,
        )
        completions = []
        runner.manager.calibrationCompleted.connect(lambda: completions.append(True))

        def fail_append(self, *args, **kwargs):
            raise OSError("injected canonical append failure")

        monkeypatch.setattr(CalibrationRecordingStore, "append_update", fail_append)

        with pytest.raises(CalibrationStorageContractError, match="canonical payload"):
            runner.run_case(selected)

        legacy = json.loads(calibration_path.read_text(encoding="utf-8"))
        assert len(legacy["runs"][0]["steps"][selected.phase_name]) == 2
        assert completions == [True]
        assert runner.manager.activeCalibration is None
        diagnostics = runner.manager.get_shadow_storage_diagnostics()
        assert [row["kind"] for row in diagnostics].count("update_append_failed") == 2
        result_path = next(
            calibration_path.parent.glob("calibration_recordings/*/*/result.json")
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert result["outcome"] == "storage_error"
        assert result["update_count"] == 0
        runner.restore()
    finally:
        assert session.close()
