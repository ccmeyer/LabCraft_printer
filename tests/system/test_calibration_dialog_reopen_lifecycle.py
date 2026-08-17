from __future__ import annotations

import json
import threading
import time

import pytest

from CalibrationClasses.View import DropletImagingDialog
from tests.test_droplet_imaging_refuel_panel import _build_droplet_dialog


SCENARIO_ID = "calibration_dialog_reopen_lifecycle_v1"


@pytest.mark.sil_lifecycle
def test_calibration_dialog_reopen_lifecycle(monkeypatch, qapp):
    callback_counts = {"image": 0, "capture_complete": 0}

    def _image_callback(_self):
        callback_counts["image"] += 1

    def _capture_complete_callback(_self):
        callback_counts["capture_complete"] += 1

    monkeypatch.setattr(DropletImagingDialog, "update_image", _image_callback)
    monkeypatch.setattr(
        DropletImagingDialog,
        "_on_droplet_capture_finished",
        _capture_complete_callback,
    )
    dialog, _refuel_model, controller = _build_droplet_dialog(
        monkeypatch,
        qapp,
    )
    manager = dialog.model.calibration_manager
    camera = dialog.model.droplet_camera_model
    identities = {
        "dialog": id(dialog),
        "manager": id(manager),
        "droplet_camera": id(camera),
        "refuel_camera": id(dialog.refuel_camera_model),
    }
    capture_cycles = {1, 4, 8}
    capture_latencies_ms = []
    receiver_counts = []

    for cycle in range(1, 9):
        assert dialog._session_state == "active"
        assert identities == {
            "dialog": id(dialog),
            "manager": id(dialog.model.calibration_manager),
            "droplet_camera": id(dialog.model.droplet_camera_model),
            "refuel_camera": id(dialog.refuel_camera_model),
        }
        if cycle in capture_cycles:
            started = time.perf_counter_ns()
            camera.droplet_image_updated.emit()
            qapp.processEvents()
            capture_latencies_ms.append(
                (time.perf_counter_ns() - started) / 1_000_000.0
            )
        assert dialog.deactivate_session(reason=f"cycle_{cycle}") is True
        hidden_counts = dict(callback_counts)
        camera.droplet_image_updated.emit()
        manager.calibrationStageChanged.emit("hidden", "red")
        qapp.processEvents()
        assert callback_counts == hidden_counts
        receiver_counts.append(len(dialog._session_signal_connections))
        if cycle < 8:
            assert dialog.activate_session(
                mode="optics" if cycle == 4 else "calibration"
            ) is True

    metrics = {
        "scenario_id": SCENARIO_ID,
        "cycles": 8,
        "capture_cycles": sorted(capture_cycles),
        "identities": identities,
        "callback_counts": callback_counts,
        "receiver_counts_while_hidden": receiver_counts,
        "camera_start_count": controller.start_droplet_camera.call_count,
        "camera_stop_count": controller.stop_droplet_camera.call_count,
        "active_timer_count": sum(
            int(timer.isActive())
            for timer in (
                dialog.camera_timer,
                dialog.refuel_monitor_timer,
                dialog.refuel_panel_refresh_timer,
            )
        ),
        "active_thread_count": threading.active_count(),
        "capture_latencies_ms": capture_latencies_ms,
    }
    print("SIL_PROGRESS " + json.dumps(metrics, sort_keys=True), flush=True)

    assert callback_counts == {"image": 3, "capture_complete": 3}
    assert receiver_counts == [0] * 8
    assert controller.start_droplet_camera.call_count == 8
    assert controller.stop_droplet_camera.call_count == 8
    assert metrics["active_timer_count"] == 0
