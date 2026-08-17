from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from CalibrationClasses.View import DropletImagingDialog
from tests.test_calibration_memory_ui_recommendation import _build_real_dialog_for_layout


SCENARIO_ID = "calibration_status_ui_backpressure_v1"


@pytest.mark.sil_lifecycle
def test_calibration_status_ui_backpressure(monkeypatch, qapp):
    captures = {"completed": 0}

    monkeypatch.setattr(DropletImagingDialog, "update_image", lambda _self: None)
    monkeypatch.setattr(
        DropletImagingDialog,
        "_on_droplet_capture_finished",
        lambda _self: captures.__setitem__("completed", captures["completed"] + 1),
    )
    dialog = _build_real_dialog_for_layout(
        monkeypatch,
        qapp,
        main_window=SimpleNamespace(color_dict={}),
    )
    camera = dialog.model.droplet_camera_model
    camera.num_flashes = 0
    camera.ext_counter = 0
    camera.get_num_flashes = lambda: int(camera.num_flashes)
    camera.get_trigger_counter = lambda: 0
    camera.get_flash_duration = lambda: int(camera.flash_duration)
    camera.get_flash_delay = lambda: int(camera.flash_delay)
    camera.get_num_droplets = lambda: int(camera.num_droplets)
    camera.get_exposure_time = lambda: int(camera.exposure_time)
    dialog._reset_status_ui_runtime_diagnostics()

    prior_batches = 0
    for pass_index in range(1, 7):
        started_ns = time.perf_counter_ns()
        for _ in range(250):
            dialog.model.machine_model.pressure_updated.emit()
            dialog.model.machine_model.printing_parameters_updated.emit()
            camera.flash_signal.emit()
            dialog.model.machine_model.machine_state_updated.emit()
        camera.droplet_image_updated.emit()
        assert dialog.status_ui_refresh_timer.isActive()
        qapp.processEvents()
        latency_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
        diagnostics = dialog.get_status_ui_refresh_diagnostics()
        assert diagnostics["pending_count"] == 0
        assert diagnostics["max_pending_count"] == 1
        assert diagnostics["batch_count"] == prior_batches + 1
        assert diagnostics["manual_focus"]["request_count"] == 0
        assert captures["completed"] == pass_index
        prior_batches = diagnostics["batch_count"]
        print(
            f"Pass {pass_index}/6: "
            + json.dumps(
                {
                    "scenario_id": SCENARIO_ID,
                    "status_frames": pass_index * 250,
                    "ui_batches": prior_batches,
                    "pending_callbacks": diagnostics["pending_count"],
                    "capture_latency_ms": round(latency_ms, 3),
                },
                sort_keys=True,
            ),
            flush=True,
        )

    final = dialog.get_status_ui_refresh_diagnostics()
    assert final["request_count"] == (6 * 250 * 3) + 1
    assert final["coalesced_request_count"] == final["request_count"] - 6
    assert final["batch_count"] == 6
    dialog.deactivate_session(reason="sil_complete")
    dialog.deleteLater()
    qapp.processEvents()
