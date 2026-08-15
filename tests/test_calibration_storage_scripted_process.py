from __future__ import annotations

from pathlib import Path

import pytest

from tools.sil.calibration_storage_contract import load_catalog
from tools.sil.calibration_storage_process import (
    ScriptedCalibrationProcess,
    StorageContractRunner,
    StorageContractRuntimeError,
)
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

