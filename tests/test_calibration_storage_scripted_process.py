from __future__ import annotations

import json
from dataclasses import replace
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

        assert evidence[0].legacy_update_hashes == ()
        assert evidence[0].recorder_update_hashes == selected[0].expected_update_hashes
        assert evidence[1].capture_count == 2
        assert evidence[1].capture_bytes > 0
        assert evidence[2].recording_dir is not None
        assert evidence[2].recorder_update_hashes == selected[2].expected_update_hashes
        assert runner.metrics.snapshot()["calibration_rewrite_count"] == 0
        assert not calibration_path.exists()
        runner.restore()
    finally:
        assert session.close()


def test_characterization_rows_are_live_then_promoted_after_terminal_commit(
    qapp, tmp_path
):
    session = _session(qapp, tmp_path / "live-results-session")
    try:
        _catalog, cases = load_catalog()
        selected = next(
            case for case in cases if case.process_id == "legacy-parity-two-update"
        )
        experiment_dir = tmp_path / "live-results-experiment"
        experiment_dir.mkdir()
        calibration_path = experiment_dir / "calibration.json"
        em = session.components.model.experiment_model
        em.experiment_dir_path = str(experiment_dir)
        em.calibration_file_path = str(calibration_path)
        runner = StorageContractRunner(
            model=session.components.model,
            controller=session.components.controller,
            machine=session.components.machine,
            app=qapp,
            calibration_file_path=calibration_path,
        )
        manager = runner.manager
        notifications = []

        def observe_summary():
            notifications.append(
                {
                    "summary": manager.get_characterization_summary_rows(),
                    "history": manager.get_characterization_history_snapshot()["rows"],
                    "index_exists": (experiment_dir / "calibration_index.jsonl").exists(),
                }
            )

        manager.characterizationSummaryUpdated.connect(observe_summary)
        runner.run_case(selected)

        live = [
            snapshot
            for snapshot in notifications
            if snapshot["summary"]
            and all(
                row.get("row_state") == "in_progress"
                for row in snapshot["summary"]
            )
        ]
        assert [len(snapshot["summary"]) for snapshot in live] == [1, 3]
        assert all(snapshot["history"] == [] for snapshot in live)
        assert all(snapshot["index_exists"] is False for snapshot in live)
        assert all(
            row["application_eligible"] is False
            and row["result_id"] is None
            and row["update_id"]
            and row["update_payload_sha256"]
            for snapshot in live
            for row in snapshot["summary"]
        )
        assert len(
            {
                row["display_row_id"]
                for row in live[-1]["summary"]
            }
        ) == 3
        blocked = manager.resolve_characterization_selection(live[-1]["summary"][0])
        assert blocked["ok"] is False
        assert blocked["code"] == "calibration_result_in_progress"

        terminal = notifications[-1]
        assert terminal["index_exists"] is True
        assert len(terminal["summary"]) == 3
        assert len(terminal["history"]) == 3
        assert all(row.get("row_state") != "in_progress" for row in terminal["summary"])
        assert all(row.get("result_id") for row in terminal["summary"])
        assert manager._in_progress_characterization_rows == {}
        runner.restore()
    finally:
        assert session.close()


@pytest.mark.parametrize(
    ("terminal_outcome", "error_message"),
    (
        ("error", "injected terminal failure"),
        ("stopped", "Calibration terminated by user"),
    ),
)
def test_noncompleted_characterization_removes_live_rows_without_promoting_them(
    qapp, tmp_path, terminal_outcome, error_message
):
    session = _session(qapp, tmp_path / "live-results-error-session")
    try:
        _catalog, cases = load_catalog()
        completed = next(
            case for case in cases if case.process_id == "legacy-parity-two-update"
        )
        selected = replace(
            completed,
            process_id=f"live-results-{terminal_outcome}-after-updates",
            terminal_outcome=terminal_outcome,
            error_message=error_message,
            expected_summary_rows=(),
        )
        experiment_dir = tmp_path / "live-results-error-experiment"
        experiment_dir.mkdir()
        calibration_path = experiment_dir / "calibration.json"
        em = session.components.model.experiment_model
        em.experiment_dir_path = str(experiment_dir)
        em.calibration_file_path = str(calibration_path)
        runner = StorageContractRunner(
            model=session.components.model,
            controller=session.components.controller,
            machine=session.components.machine,
            app=qapp,
            calibration_file_path=calibration_path,
        )
        manager = runner.manager
        snapshots = []
        manager.characterizationSummaryUpdated.connect(
            lambda: snapshots.append(manager.get_characterization_summary_rows())
        )

        evidence = runner.run_case(selected)

        assert any(
            rows and all(row.get("row_state") == "in_progress" for row in rows)
            for rows in snapshots
        )
        assert snapshots[-1] == []
        assert manager.get_characterization_history_snapshot()["rows"] == []
        assert manager._in_progress_characterization_rows == {}
        assert evidence.canonical_result_outcome == terminal_outcome
        runner.restore()
    finally:
        assert session.close()


def test_scripted_process_keeps_structured_diagnostics_when_pixels_are_disabled(
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
        assert evidence.diagnostic_recording_enabled is True
        assert evidence.recorder_update_hashes == selected.expected_update_hashes
        assert evidence.canonical_update_hashes == selected.expected_update_hashes
        assert evidence.canonical_result_kind == "none"
        assert evidence.canonical_result_outcome == "completed"
        assert evidence.canonical_index_event_count == 1
        assert evidence.canonical_valid is True
        runner.restore()
    finally:
        assert session.close()


def test_authoritative_canonical_only_process_never_creates_legacy_file(
    qapp, tmp_path
):
    session = _session(qapp, tmp_path / "canonical-only-session")
    try:
        _catalog, cases = load_catalog()
        selected = next(
            case for case in cases if case.process_id == "legacy-parity-two-update"
        )
        calibration_path = tmp_path / "canonical-only" / "calibration.json"
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
            authoritative_mode=True,
            legacy_writer_mode="canonical_only",
        )

        evidence = runner.run_case(selected)

        assert evidence.legacy_update_hashes == ()
        assert evidence.canonical_update_hashes == selected.expected_update_hashes
        assert evidence.canonical_result_outcome == "completed"
        assert evidence.canonical_index_event_count == 1
        assert evidence.canonical_valid is True
        assert not calibration_path.exists()
        assert not list(calibration_path.parent.glob("calibration.json.*"))
        diagnostics = runner.manager.get_legacy_calibration_writer_diagnostics()
        assert diagnostics["write_count"] == 0
        assert diagnostics["suppressed_write_count"] == 0
        assert diagnostics["legacy_writer_available"] is False
        runner.restore()
    finally:
        assert session.close()


def test_canonical_append_failure_is_fail_closed(qapp, tmp_path, monkeypatch):
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

        with pytest.raises(CalibrationStorageContractError, match="payload mismatch"):
            runner.run_case(selected)

        assert not calibration_path.exists()
        assert completions == []
        assert runner.manager.activeCalibration is None
        diagnostics = runner.manager.get_shadow_storage_diagnostics()
        assert [row["kind"] for row in diagnostics].count("update_append_failed") == 1
        result_path = next(
            calibration_path.parent.glob("calibration_recordings/*/*/result.json")
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert result["outcome"] == "storage_error"
        assert result["update_count"] == 0
        runner.restore()
    finally:
        assert session.close()


def test_authoritative_append_failure_blocks_legacy_write_and_completion(
    qapp, tmp_path, monkeypatch
):
    session = _session(qapp, tmp_path / "authoritative-failure-session")
    try:
        _catalog, cases = load_catalog()
        selected = next(
            case for case in cases if case.process_id == "legacy-parity-two-update"
        )
        calibration_path = (
            tmp_path / "authoritative-failure-experiment" / "calibration.json"
        )
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
            authoritative_mode=True,
        )
        completions = []
        errors = []
        runner.manager.calibrationCompleted.connect(lambda: completions.append(True))
        runner.manager.calibrationError.connect(errors.append)

        def fail_append(self, *args, **kwargs):
            raise OSError("injected authoritative append failure")

        monkeypatch.setattr(CalibrationRecordingStore, "append_update", fail_append)
        with pytest.raises(CalibrationStorageContractError, match="payload mismatch"):
            runner.run_case(selected)

        assert not calibration_path.exists()
        assert completions == []
        assert len(errors) == 1
        assert "update_append_failed" in errors[0].lower()
        assert runner.manager.activeCalibration is None
        result_path = next(
            calibration_path.parent.glob("calibration_recordings/*/*/result.json")
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert result["outcome"] == "storage_error"
        runner.restore()
    finally:
        assert session.close()


def test_authoritative_run_creation_failure_prevents_process_start(
    qapp, tmp_path, monkeypatch
):
    session = _session(qapp, tmp_path / "authoritative-start-failure-session")
    try:
        _catalog, cases = load_catalog()
        selected = next(
            case for case in cases if case.process_id == "legacy-parity-two-update"
        )
        calibration_path = tmp_path / "start-failure" / "calibration.json"
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
            authoritative_mode=True,
        )
        starts = []
        errors = []
        monkeypatch.setattr(
            ScriptedCalibrationProcess,
            "start",
            lambda self: starts.append(self.case.process_id),
        )

        def fail_start(self, *args, **kwargs):
            raise OSError("injected authoritative run creation failure")

        monkeypatch.setattr(CalibrationRecordingStore, "start_run", fail_start)
        runner.manager.calibrationError.connect(errors.append)
        with pytest.raises(CalibrationStorageContractError, match="payload mismatch"):
            runner.run_case(selected)

        assert not calibration_path.exists()
        assert starts == []
        assert len(errors) == 1
        assert "storage could not be opened" in errors[0].lower()
        assert runner.manager.activeCalibration is None
        runner.restore()
    finally:
        assert session.close()


def test_authority_marked_row_is_blocked_when_index_commit_is_missing(
    qapp, tmp_path
):
    session = _session(qapp, tmp_path / "authoritative-application-guard")
    try:
        _catalog, cases = load_catalog()
        selected = next(
            case for case in cases if case.process_id == "legacy-parity-two-update"
        )
        calibration_path = tmp_path / "application-guard" / "calibration.json"
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
            authoritative_mode=True,
        )
        evidence = runner.run_case(selected)
        rows = runner.characterization_rows(selected.identity)
        target = next(
            row
            for row in rows
            if row.get("source_run_id") == evidence.run_id
            and row.get("source_step_index") == 1
        )
        assert runner.manager.validate_characterization_candidate_for_application(
            target
        )["ok"] is True

        (calibration_path.parent / "calibration_index.jsonl").write_text(
            "", encoding="utf-8"
        )
        blocked = runner.manager.validate_characterization_candidate_for_application(
            target
        )
        assert blocked["ok"] is False
        assert blocked["code"] == "canonical_storage_unavailable"
        runner.restore()
    finally:
        assert session.close()
