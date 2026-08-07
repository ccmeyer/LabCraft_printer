from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PySide6 import QtWidgets

from tools.virtual_workflows.harness import AutomationHarness, AutomationHarnessConfig
from tools.virtual_workflows.journeys import (
    SMOKE_REQUIRED_ASSERTIONS,
    JourneyRunConfig,
    run_virtual_print_array_24_journey,
)
from tools.virtual_workflows.page_drivers import MachineControlsDriver


def _config(tmp_path: Path, **changes):
    values = {
        "scenario_id": "scenario",
        "workload_id": "workload",
        "output_root": tmp_path,
        "seed": 3,
        "speed_multiplier": 1000.0,
        "timeout_seconds": 30.0,
        "run_id": "unit-run",
    }
    values.update(changes)
    return AutomationHarnessConfig(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [("seed", -1), ("speed_multiplier", 0), ("timeout_seconds", 0)],
)
def test_harness_config_fails_closed(field, value, tmp_path):
    with pytest.raises(ValueError):
        AutomationHarness(_config(tmp_path, **{field: value}))


def test_harness_config_validates_optional_regression_controls(tmp_path):
    with pytest.raises(ValueError, match="inject_ui_stall_ms"):
        _config(tmp_path, inject_ui_stall_ms=-1)
    with pytest.raises(ValueError, match="inject_after_completion"):
        _config(tmp_path, inject_after_completion=0)
    with pytest.raises(ValueError, match="provided together"):
        _config(tmp_path, pi_preflight_path=tmp_path / "preflight.json")

    config = _config(
        tmp_path,
        inject_ui_stall_ms=300,
        inject_after_completion=48,
        pi_preflight_path=tmp_path / "preflight.json",
        pi_hardware_proof_path=tmp_path / "proof.json",
    )
    assert config.pi_preflight_path == (tmp_path / "preflight.json").resolve()
    assert config.pi_hardware_proof_path == (tmp_path / "proof.json").resolve()


def test_harness_uses_external_session_root_and_hashes_retained_evidence(tmp_path):
    harness = AutomationHarness(_config(tmp_path))
    assert harness.report_dir.is_relative_to(tmp_path.resolve())
    assert not harness.scenario_root.is_relative_to(Path.cwd().resolve())

    evidence = harness.report_dir / "sample.txt"
    evidence.write_text("retained evidence\n", encoding="utf-8")
    manifest_path = harness.write_evidence_manifest()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    row = next(item for item in manifest["files"] if item["path"] == "sample.txt")
    assert row["sha256"] == hashlib.sha256(evidence.read_bytes()).hexdigest()
    assert manifest["excluded"] == ["evidence_manifest.json"]


def test_unexpected_dialog_check_allows_only_explicit_active_dialog(qapp, tmp_path):
    harness = AutomationHarness(_config(tmp_path))
    harness.context.app = qapp
    allowed = QtWidgets.QDialog()
    allowed.setWindowTitle("Expected editor")
    allowed.show()
    qapp.processEvents()

    harness.assert_no_unexpected_dialog(allowed_dialogs=(allowed,))
    assert harness.context.unexpected_dialogs == []

    with pytest.raises(RuntimeError, match="unexpected dialog"):
        harness.assert_no_unexpected_dialog()
    assert harness.context.unexpected_dialogs == [
        {"type": "QDialog", "title": "Expected editor"}
    ]
    assert allowed.isVisible() is False
    allowed.deleteLater()


def test_harness_reopens_fresh_application_on_same_retained_session(qapp, tmp_path):
    harness = AutomationHarness(_config(tmp_path))
    first_launch = harness.start()["evidence"]
    first_root = Path(first_launch["scenario_root"])
    sentinel = first_root / "experiments" / "rotation-sentinel.txt"
    sentinel.write_text("retained\n", encoding="utf-8")

    first_close = harness.close_application_session()["evidence"]
    assert first_close["close_succeeded"]
    assert first_close["recorder"]["status"] == "closed"
    assert not first_close["session_lock_present"]
    assert harness.context.components is None

    second_launch = harness.reopen_application_session()["evidence"]
    assert second_launch["session_id"] == first_launch["session_id"]
    assert second_launch["application_session_id"] != first_launch[
        "application_session_id"
    ]
    assert second_launch["application_session_index"] == 2
    assert sentinel.read_text(encoding="utf-8") == "retained\n"

    teardown = harness.close()["evidence"]
    assert teardown["close_succeeded"]
    assert not teardown["session_lock_present"]
    assert [row["status"] for row in teardown["application_sessions"]] == [
        "completed",
        "completed",
    ]
    assert len(
        {row["recorder_artifact_dir"] for row in teardown["application_sessions"]}
    ) == 2


def test_harness_fails_closed_on_dirty_first_session_close(qapp, tmp_path, monkeypatch):
    harness = AutomationHarness(_config(tmp_path))
    harness.start()
    session_type = type(harness.session)
    original = session_type.close

    def close_but_report_failure(session, *args, **kwargs):
        original(session, *args, **kwargs)
        return False

    monkeypatch.setattr(session_type, "close", close_but_report_failure)
    with pytest.raises(RuntimeError, match="did not close cleanly"):
        harness.close_application_session()
    assert harness.session is None
    assert harness.application_sessions[0]["status"] == "failed"
    assert not (harness.scenario_root / ".sil-session.lock").exists()
    harness.close()


def test_harness_retains_first_recorder_when_second_launch_fails(
    qapp, tmp_path, monkeypatch
):
    from tools.sil.session import SimulationSession

    harness = AutomationHarness(_config(tmp_path))
    harness.start()
    first = harness.close_application_session()["evidence"]

    def reject_second_create(_cls, _config):
        raise RuntimeError("injected second-session construction failure")

    monkeypatch.setattr(SimulationSession, "create", classmethod(reject_second_create))
    with pytest.raises(RuntimeError, match="second-session construction failure"):
        harness.reopen_application_session()
    assert harness.session is None
    assert harness.application_sessions[0]["recorder"]["status"] == "closed"
    assert Path(first["recorder_artifact_dir"]).is_dir()
    assert not (harness.scenario_root / ".sil-session.lock").exists()
    harness.close()


def test_active_session_unexpected_dialog_fails_action_and_retains_evidence(
    qapp, tmp_path, monkeypatch
):
    retained_dialogs = []

    def expose_unexpected_dialog(self):
        dialog = QtWidgets.QMessageBox(
            QtWidgets.QMessageBox.Icon.Warning,
            "Unexpected harness test dialog",
            "This modal is intentionally outside the action policy.",
            parent=self.view,
        )
        retained_dialogs.append(dialog)
        dialog.show()
        self.app.processEvents()

    monkeypatch.setattr(MachineControlsDriver, "connect", expose_unexpected_dialog)
    report = run_virtual_print_array_24_journey(
        JourneyRunConfig(
            output_root=tmp_path,
            seed=11,
            speed_multiplier=1000.0,
            timeout_seconds=30.0,
            run_id="controlled-failure",
        )
    )

    assert report["classification"]["status"] == "fail"
    workflow = report["metrics"]["workflow"]["values"]
    failed = next(
        row for row in workflow["action_results"]
        if row["action_id"] == "machine.connect_via_ui"
    )
    assert failed["status"] == "fail"
    assert failed["interaction_surface"] == "ui"
    assert failed["failure_stage"] == "operation"
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    }
    assert decisions["sil.host_hardware_disabled"] == "pass"
    assert decisions["artifacts.cleanup_complete"] == "pass"
    assert {
        assertion_id
        for assertion_id in SMOKE_REQUIRED_ASSERTIONS
        if decisions[assertion_id] == "incomplete"
    } == set(SMOKE_REQUIRED_ASSERTIONS[1:-1])

    report_dir = Path(report["safety"]["report_dir"])
    scenario_root = Path(report["safety"]["scenario_root"])
    for relative in (
        "failure_traceback.txt",
        "action_ledger.json",
        "assertion_ledger.json",
        "evidence_manifest.json",
        "screenshots/failure.png",
    ):
        assert (report_dir / relative).is_file()
    assert report["run"]["seed"] == 11
    assert report["run"]["replay_command"]
    assert report["workload"]["fixture_sha256"]
    assert scenario_root.is_dir()
    assert not (scenario_root / ".sil-session.lock").exists()
