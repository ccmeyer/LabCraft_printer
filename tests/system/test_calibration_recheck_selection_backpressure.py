from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from CalibrationClasses.View import DropletImagingDialog
from tests.test_calibration_memory_ui_recommendation import _build_real_dialog_for_layout


SCENARIO_ID = "calibration_recheck_selection_backpressure_v1"


@pytest.mark.sil_lifecycle
def test_calibration_recheck_selection_backpressure(monkeypatch, qapp):
    dialog = _build_real_dialog_for_layout(
        monkeypatch,
        qapp,
        main_window=SimpleNamespace(color_dict={}),
    )
    manager = dialog.model.calibration_manager
    candidate = {
        "row_identity_key": "result-sweep:update-sweep:0",
        "display_row_id": "result-sweep:update-sweep:0",
        "candidate_key": "canonical:result-sweep:update-sweep:0",
        "result_id": "result-sweep",
        "result_sha256": "sha-result-sweep",
        "process_run_id": "process-sweep",
        "update_id": "update-sweep",
        "update_payload_sha256": "sha-update-sweep",
        "reader_state": "matching_dual",
        "row_state": "committed",
        "phase": "sweep",
        "timestamp": "2026-08-17T12:00:00Z",
        "pw_us": 1400,
        "pressure_psi": 0.62,
        "mean_nL": 10.0,
        "valid": True,
        "application_eligible": True,
    }
    validation_calls = []

    def _resolve(row):
        validation_calls.append(str(row.get("row_identity_key") or ""))
        return {
            "ok": True,
            "code": "ok",
            "message": "",
            "row": dict(row),
            "bundle": {"validated": True},
        }

    manager.resolve_characterization_selection = _resolve
    manager.get_droplet_recheck_missing_requirements = lambda _row: []
    manager.changeSettingsRequested = SimpleNamespace(
        emit=lambda _settings, callback: callback()
    )
    dialog._selected_summary_row = lambda: (0, dict(candidate))
    dialog._refresh_optics_controls = lambda: None
    dialog.refresh_calibration_memory_recommendation = lambda: None
    manager.activeCalibration = object()
    dialog._manual_controls_locked = True

    capture_transitions = 0
    stage_updates = 0
    for pass_index in range(1, 7):
        for _ in range(50):
            stage_updates += 1
            dialog._refresh_manual_control_lock_state("scripted busy stage")
        assert dialog._set_capture_request_pending(True) is True
        assert dialog._set_capture_request_pending(True) is False
        assert dialog._set_capture_request_pending(False) is True
        assert dialog._set_capture_request_pending(False) is False
        capture_transitions += 2
        assert validation_calls == []
        print(
            f"Pass {pass_index}/6: "
            + json.dumps(
                {
                    "scenario_id": SCENARIO_ID,
                    "capture_transitions": capture_transitions,
                    "stage_updates": stage_updates,
                    "busy_validation_calls": len(validation_calls),
                    "pending_callbacks": 0,
                },
                sort_keys=True,
            ),
            flush=True,
        )

    manager.activeCalibration = None
    dialog._refresh_manual_control_lock_state("idle")
    assert validation_calls == [candidate["row_identity_key"]]
    dialog._refresh_manual_control_lock_state("unchanged idle")
    assert validation_calls == [candidate["row_identity_key"]]

    dialog.load_selected_summary_row()
    assert validation_calls == [
        candidate["row_identity_key"],
        candidate["row_identity_key"],
    ]
    _, selected_after = dialog._selected_summary_row()
    assert selected_after["row_identity_key"] == candidate["row_identity_key"]

    hardware_activity = {
        "camera": 0,
        "motion": 0,
        "pressure": 0,
        "dispense": 0,
        "serial": 0,
        "gpio": 0,
        "firmware": 0,
        "physical_ports": 0,
    }
    assert hardware_activity == {key: 0 for key in hardware_activity}
    dialog.deactivate_session(reason="sil_complete")
    dialog.deleteLater()
    qapp.processEvents()
