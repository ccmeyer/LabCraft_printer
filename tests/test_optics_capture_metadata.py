from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from Controller import Controller
from CalibrationClasses.View import DropletImagingDialog


class _Signal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args, **kwargs):
        for callback in list(self._callbacks):
            callback(*args, **kwargs)


class _CaptureGuardTimer:
    def __init__(self):
        self.timeout = _Signal()
        self.interval_ms = None
        self.active = False
        self.single_shot = False

    def setSingleShot(self, single_shot):
        self.single_shot = bool(single_shot)

    def setInterval(self, interval_ms):
        self.interval_ms = int(interval_ms)

    def start(self, interval_ms=None):
        if interval_ms is not None:
            self.interval_ms = int(interval_ms)
        self.active = True

    def stop(self):
        self.active = False

    def fire(self):
        if self.single_shot:
            self.active = False
        self.timeout.emit()


class _DropletCamera:
    def __init__(self):
        self.frame = np.full((8, 10, 3), 77, dtype=np.uint8)

    def get_latest_frame(self):
        return self.frame

    def get_last_capture_result(self):
        return {"cap_id": 123, "reason": "threshold"}


class _Machine:
    def __init__(self):
        self.droplet_camera = _DropletCamera()
        self.capture_calls = []
        self.recover_calls = []
        self.commands_idle = True
        self.capture_return = True
        self.recover_return = {"ok": True, "ready_for_retry": True}
        self.capture_state = {
            "cap_active": False,
            "worker_active": False,
            "camera_started": True,
        }

    def capture_droplet_image(self, *, throughput_mode=False, capture_request_id=None):
        self.capture_calls.append(
            {
                "throughput_mode": bool(throughput_mode),
                "capture_request_id": capture_request_id,
            }
        )
        return self.capture_return

    def recover_droplet_capture(self, reason=""):
        self.recover_calls.append(str(reason))
        self.capture_state.update(
            {
                "cap_active": False,
                "worker_active": False,
            }
        )
        return dict(self.recover_return)

    def get_droplet_capture_state(self):
        return dict(self.capture_state)

    def check_if_all_completed(self):
        return self.commands_idle


class _MachineModel:
    def get_current_position_dict(self):
        return {"X": 101, "Y": 202, "Z": 303}


class _CameraModel:
    def __init__(self):
        self.update_calls = []

    def update_image(self, frame, *, capture_info=None, save_metadata=None):
        self.update_calls.append(
            {
                "frame": frame,
                "capture_info": capture_info,
                "save_metadata": save_metadata,
            }
        )


def _make_controller():
    controller = Controller.__new__(Controller)
    machine = _Machine()
    camera_model = _CameraModel()
    clock = {"value": 100.0}
    controller.machine = machine
    controller.model = SimpleNamespace(
        machine_model=_MachineModel(),
        droplet_camera_model=camera_model,
        calibration_manager=SimpleNamespace(captureFailed=Mock(), activeCalibration=None),
    )
    controller.expected_position = {"X": 111, "Y": 222, "Z": 333}
    controller.pending_capture_callback = None
    controller.pending_capture_context = None
    controller.pending_capture_active = False
    controller.pending_capture_started_monotonic = None
    controller.pending_capture_timeout_ms = 8_000
    controller.pending_capture_throughput_timeout_ms = 1_500
    controller.pending_capture_guard_timer = None
    controller.pending_capture_request_id = None
    controller.pending_capture_recovery_attempted = False
    controller.pending_capture_throughput_mode = False
    controller.last_capture_queue_rejection_reason = None
    controller.last_capture_queue_rejection_state = None
    controller._timer_factory = lambda _parent: _CaptureGuardTimer()
    controller._monotonic_fn = lambda: clock["value"]
    controller._test_clock = clock
    return controller, machine, camera_model


def test_controller_capture_context_is_written_to_next_frame_metadata():
    controller, machine, camera_model = _make_controller()

    assert controller.capture_droplet_image(capture_context="optics_scale_bar") is True
    assert machine.capture_calls[0]["throughput_mode"] is False
    assert machine.capture_calls[0]["capture_request_id"]
    assert controller.pending_capture_context == "optics_scale_bar"
    assert controller.pending_capture_active is True

    controller._on_image_captured()

    assert controller.pending_capture_context is None
    assert controller.pending_capture_active is False
    assert len(camera_model.update_calls) == 1
    call = camera_model.update_calls[0]
    assert call["capture_info"] == {"cap_id": 123, "reason": "threshold"}
    assert call["save_metadata"]["capture_context"] == "optics_scale_bar"
    assert call["save_metadata"]["X_position"] == 111
    assert call["save_metadata"]["Y_position"] == 222
    assert call["save_metadata"]["Z_position"] == 333
    assert call["save_metadata"]["controller_expected_position"] == {"X": 111, "Y": 222, "Z": 333}
    assert call["save_metadata"]["machine_position"] == {"X": 101, "Y": 202, "Z": 303}
    assert call["save_metadata"]["position_source"] == "controller_expected_position"
    assert call["save_metadata"]["commands_idle_at_frame"] is True
    assert isinstance(call["save_metadata"]["position_recorded_at"], str)


def test_controller_capture_context_is_one_shot():
    controller, _machine, camera_model = _make_controller()

    assert controller.capture_droplet_image(capture_context="optics_scale_bar") is True
    controller._on_image_captured()
    controller._on_image_captured()

    assert camera_model.update_calls[0]["save_metadata"]["capture_context"] == "optics_scale_bar"
    assert "capture_context" not in camera_model.update_calls[1]["save_metadata"]


def test_controller_clears_pending_callback_when_camera_rejects_capture():
    controller, machine, _camera_model = _make_controller()
    callback = Mock()
    machine.capture_return = False

    assert controller.capture_droplet_image(callback=callback, capture_context="optics_scale_bar") is False

    assert controller.pending_capture_callback is None
    assert controller.pending_capture_context is None
    assert controller.pending_capture_active is False
    callback.assert_called_once_with(None)
    assert getattr(callback, "_capture_rejection_reason") == "machine_rejected"


def test_controller_blocks_overlapping_capture_until_frame_finishes():
    controller, machine, _camera_model = _make_controller()

    assert controller.capture_droplet_image() is True
    assert controller.capture_droplet_image() is False
    assert len(machine.capture_calls) == 1

    controller._on_image_captured()

    assert controller.capture_droplet_image() is True
    assert len(machine.capture_calls) == 2


def test_controller_overlapping_capture_resolves_waiting_callback():
    controller, machine, _camera_model = _make_controller()
    callback = Mock()

    assert controller.capture_droplet_image() is True
    assert controller.capture_droplet_image(callback=callback) is False

    assert len(machine.capture_calls) == 1
    assert controller.pending_capture_active is True
    callback.assert_called_once_with(None)


def test_controller_capture_guard_recovers_once_and_requeues_original_callback():
    controller, machine, _camera_model = _make_controller()
    callback = Mock()

    assert controller.capture_droplet_image(callback=callback) is True
    timer = controller.pending_capture_guard_timer
    assert timer is not None
    assert timer.active is True
    assert timer.interval_ms == 8_000
    first_request_id = controller.pending_capture_request_id

    controller._test_clock["value"] = 108.25
    timer.fire()

    assert machine.recover_calls
    assert len(machine.capture_calls) == 2
    assert controller.pending_capture_active is True
    assert controller.pending_capture_recovery_attempted is True
    assert controller.pending_capture_request_id != first_request_id
    callback.assert_not_called()
    controller.model.calibration_manager.captureFailed.emit.assert_not_called()

    frame = np.full((4, 5, 3), 99, dtype=np.uint8)
    retry_request_id = controller.pending_capture_request_id
    controller._on_capture_completed_payload(
        {
            "status": "success",
            "request_id": retry_request_id,
            "cap_id": 456,
            "frame": frame,
            "capture_info": {"cap_id": 456, "reason": "threshold"},
        }
    )

    callback.assert_called_once()
    assert callback.call_args.args[0] is frame
    assert controller.pending_capture_callback is None
    assert controller.pending_capture_context is None
    assert controller.pending_capture_active is False
    assert controller.pending_capture_started_monotonic is None

    assert controller.capture_droplet_image() is True
    assert len(machine.capture_calls) == 3


def test_controller_second_capture_timeout_fails_cleanly_and_allows_manual_capture():
    controller, machine, _camera_model = _make_controller()
    callback = Mock()

    assert controller.capture_droplet_image(callback=callback) is True
    controller._test_clock["value"] = 108.25
    controller.pending_capture_guard_timer.fire()

    assert controller.pending_capture_active is True
    assert controller.pending_capture_recovery_attempted is True
    callback.assert_not_called()

    controller._test_clock["value"] = 116.50
    controller.pending_capture_guard_timer.fire()

    assert len(machine.recover_calls) == 2
    callback.assert_called_once_with(None)
    controller.model.calibration_manager.captureFailed.emit.assert_called_once()
    assert controller.pending_capture_callback is None
    assert controller.pending_capture_active is False

    assert controller.capture_droplet_image() is True
    assert len(machine.capture_calls) == 3


def test_controller_timeout_without_retry_ready_fails_and_allows_manual_capture():
    controller, machine, _camera_model = _make_controller()
    callback = Mock()
    machine.recover_return = {"ok": True, "ready_for_retry": False}

    assert controller.capture_droplet_image(callback=callback) is True
    controller._test_clock["value"] = 108.25
    controller.pending_capture_guard_timer.fire()

    assert len(machine.recover_calls) == 1
    assert len(machine.capture_calls) == 1
    callback.assert_called_once_with(None)
    controller.model.calibration_manager.captureFailed.emit.assert_called_once()
    assert controller.pending_capture_callback is None
    assert controller.pending_capture_active is False

    assert controller.capture_droplet_image() is True
    assert len(machine.capture_calls) == 2


def test_controller_late_stale_completion_cannot_satisfy_requeued_capture():
    controller, machine, camera_model = _make_controller()
    callback = Mock()

    assert controller.capture_droplet_image(callback=callback) is True
    old_request_id = controller.pending_capture_request_id
    controller._test_clock["value"] = 108.25
    controller.pending_capture_guard_timer.fire()
    new_request_id = controller.pending_capture_request_id

    old_frame = np.full((4, 5, 3), 10, dtype=np.uint8)
    controller._on_capture_completed_payload(
        {
            "status": "success",
            "request_id": old_request_id,
            "cap_id": 111,
            "frame": old_frame,
            "capture_info": {"cap_id": 111},
        }
    )

    callback.assert_not_called()
    assert camera_model.update_calls == []
    assert controller.pending_capture_request_id == new_request_id

    new_frame = np.full((4, 5, 3), 20, dtype=np.uint8)
    controller._on_capture_completed_payload(
        {
            "status": "success",
            "request_id": new_request_id,
            "cap_id": 222,
            "frame": new_frame,
            "capture_info": {"cap_id": 222},
        }
    )

    callback.assert_called_once()
    assert callback.call_args.args[0] is new_frame
    assert camera_model.update_calls[-1]["capture_info"]["cap_id"] == 222


def _make_optics_dialog(*, commands_idle=True, active=True):
    dialog = DropletImagingDialog.__new__(DropletImagingDialog)
    dialog._optics_session_active = active
    dialog._capture_request_pending = False
    dialog.statuses = []
    dialog._set_optics_status = lambda message, color=None: dialog.statuses.append((message, color))
    dialog._set_capture_request_pending = lambda pending: setattr(dialog, "_capture_request_pending", bool(pending))
    dialog.controller = SimpleNamespace(
        check_if_all_completed=Mock(return_value=commands_idle),
        capture_droplet_image=Mock(return_value=True),
    )
    return dialog


def test_optics_capture_blocks_when_commands_are_active():
    dialog = _make_optics_dialog(commands_idle=False)

    DropletImagingDialog.capture_optics_frame(dialog)

    dialog.controller.capture_droplet_image.assert_not_called()
    assert dialog.statuses == [
        ("Wait for all machine commands to finish before capturing an optics frame.", "red")
    ]


def test_optics_capture_passes_scale_bar_context_when_idle():
    dialog = _make_optics_dialog(commands_idle=True)

    DropletImagingDialog.capture_optics_frame(dialog)

    dialog.controller.capture_droplet_image.assert_called_once_with(capture_context="optics_scale_bar")
    assert dialog._capture_request_pending is True
    assert dialog.statuses == [("Capture requested.", "green")]


def test_optics_capture_previews_without_session_and_without_save_context():
    dialog = _make_optics_dialog(commands_idle=True, active=False)

    DropletImagingDialog.capture_optics_frame(dialog)

    dialog.controller.capture_droplet_image.assert_called_once_with()
    assert dialog._capture_request_pending is True
    assert dialog.statuses == [
        ("Preview capture requested. Start a session when ready to save frames.", "green")
    ]


def test_optics_end_analyze_runs_scale_then_motion_and_writes_combined_payload(tmp_path, monkeypatch):
    import tools.scale_bar_conversion as scale_mod
    import tools.scale_bar_motion_conversion as motion_mod

    scale_analysis = {
        "schema_version": 1,
        "status": "ok",
        "summary": {
            "status": "ok",
            "median_um_per_pixel": 1.5,
            "mean_um_per_pixel": 1.51,
            "std_um_per_pixel": 0.01,
            "cv_pct": 0.5,
            "division_um": 10.0,
            "accepted_count": 30,
            "rejected_count": 1,
            "failed_count": 0,
            "run_directory": str(tmp_path),
        },
    }
    motion_analysis = {
        "schema_version": 1,
        "status": "ok",
        "summary": {
            "status": "ok",
            "run_directory": str(tmp_path),
            "accepted_count": 30,
            "rejected_count": 1,
            "error_count": 0,
            "repeat_position_group_count": 4,
        },
        "motion_fit": {
            "status": "ok",
            "fit_count": 29,
            "intercept": [10.0, 20.0],
            "matrix": [[2.0, 0.0], [0.0, 4.0]],
            "inverse_matrix": [[0.5, 0.0], [0.0, 0.25]],
            "determinant": 8.0,
            "rmse_2d_px": 5.0,
            "p95_2d_residual_px": 9.0,
            "max_2d_residual_px": 10.0,
        },
    }
    quality = {"apply_ready": True, "failed_criteria": [], "fit_count": 29}
    scale_call = Mock(return_value=scale_analysis)
    motion_call = Mock(return_value=motion_analysis)
    quality_call = Mock(return_value=quality)

    def fake_debug(payload, output_dir, **kwargs):
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        (output / "index.html").write_text("debug", encoding="utf-8")
        return {"output_dir": str(output), "summary_only": kwargs.get("summary_only")}

    monkeypatch.setattr(scale_mod, "analyze_scale_bar_directory", scale_call)
    monkeypatch.setattr(motion_mod, "analyze_scale_bar_motion_directory", motion_call)
    monkeypatch.setattr(motion_mod, "summarize_motion_fit_quality", quality_call)
    monkeypatch.setattr(motion_mod, "write_debug_outputs", fake_debug)

    dialog = DropletImagingDialog.__new__(DropletImagingDialog)
    dialog._optics_session_active = True
    dialog._optics_session_dir = str(tmp_path)
    dialog._optics_rejected_filenames = ["scale_bar_000004.png"]
    dialog._optics_last_analysis = None
    dialog.optics_division_um_spin = SimpleNamespace(value=Mock(return_value=10.0))
    dialog.optics_results_text = SimpleNamespace(setPlainText=Mock())
    dialog.statuses = []
    dialog._set_optics_status = lambda message, color=None: dialog.statuses.append((message, color))
    dialog._refresh_optics_controls = Mock()
    dialog._optics_camera_model = Mock(return_value=SimpleNamespace(stop_saving=Mock()))

    DropletImagingDialog.end_and_analyze_optics_session(dialog)

    scale_call.assert_called_once_with(
        str(tmp_path),
        division_um=10.0,
        rejected_filenames={"scale_bar_000004.png"},
    )
    motion_call.assert_called_once_with(
        str(tmp_path),
        rejected_filenames={"scale_bar_000004.png"},
    )
    assert dialog._optics_last_analysis["summary"]["apply_ready"] is True
    assert "scale_bar_analysis" in dialog._optics_last_analysis
    assert "motion_analysis" in dialog._optics_last_analysis
    assert (tmp_path / "scale_bar_analysis.json").exists()
    assert (tmp_path / "scale_bar_motion_analysis.json").exists()
    combined = json.loads((tmp_path / "optics_calibration_analysis.json").read_text(encoding="utf-8"))
    assert combined["summary"]["motion_debug_index_path"].endswith("motion_fit_summary\\index.html") or combined["summary"]["motion_debug_index_path"].endswith("motion_fit_summary/index.html")


class _FakeButton:
    def __init__(self):
        self.enabled = None
        self.tooltip = ""

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)

    def setToolTip(self, text):
        self.tooltip = str(text)


class _FakeLabel:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = str(text)


def test_optics_apply_button_requires_combined_quality_gate():
    dialog = DropletImagingDialog.__new__(DropletImagingDialog)
    dialog._optics_session_active = False
    dialog._capture_request_pending = False
    dialog._optics_last_analysis = {
        "summary": {
            "status": "ok",
            "apply_ready": False,
            "failed_criteria": ["rmse_2d>15"],
        }
    }
    dialog._is_flash_fault_latched = Mock(return_value=False)
    dialog._optics_current_factor = Mock(return_value=1.5)
    dialog._optics_current_source = Mock(return_value="unit")
    dialog._optics_step_conversion_source = Mock(return_value="preset")
    dialog.optics_current_factor_label = _FakeLabel()
    dialog.optics_session_dir_label = _FakeLabel()
    dialog.optics_start_session_button = _FakeButton()
    dialog.optics_capture_frame_button = _FakeButton()
    dialog.optics_reject_last_button = _FakeButton()
    dialog.optics_analyze_button = _FakeButton()
    dialog.optics_apply_button = _FakeButton()
    dialog.optics_manual_override_button = _FakeButton()

    DropletImagingDialog._refresh_optics_controls(dialog)

    assert dialog.optics_apply_button.enabled is False
    assert "rmse_2d>15" in dialog.optics_apply_button.tooltip
