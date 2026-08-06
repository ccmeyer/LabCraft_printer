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
