from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from Controller import Controller
from CalibrationClasses.View import DropletImagingDialog


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
        self.commands_idle = True
        self.capture_return = True

    def capture_droplet_image(self, *, throughput_mode=False):
        self.capture_calls.append({"throughput_mode": bool(throughput_mode)})
        return self.capture_return

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
    controller.machine = machine
    controller.model = SimpleNamespace(
        machine_model=_MachineModel(),
        droplet_camera_model=camera_model,
        calibration_manager=SimpleNamespace(captureFailed=Mock(), activeCalibration=None),
    )
    controller.expected_position = {"X": 111, "Y": 222, "Z": 333}
    controller.pending_capture_callback = None
    controller.pending_capture_context = None
    return controller, machine, camera_model


def test_controller_capture_context_is_written_to_next_frame_metadata():
    controller, machine, camera_model = _make_controller()

    assert controller.capture_droplet_image(capture_context="optics_scale_bar") is True
    assert machine.capture_calls == [{"throughput_mode": False}]
    assert controller.pending_capture_context == "optics_scale_bar"

    controller._on_image_captured()

    assert controller.pending_capture_context is None
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
    callback.assert_not_called()


def _make_optics_dialog(*, commands_idle=True, active=True):
    dialog = DropletImagingDialog.__new__(DropletImagingDialog)
    dialog._optics_session_active = active
    dialog.statuses = []
    dialog._set_optics_status = lambda message, color=None: dialog.statuses.append((message, color))
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
    assert dialog.statuses == [("Capture requested.", "green")]


def test_optics_capture_previews_without_session_and_without_save_context():
    dialog = _make_optics_dialog(commands_idle=True, active=False)

    DropletImagingDialog.capture_optics_frame(dialog)

    dialog.controller.capture_droplet_image.assert_called_once_with()
    assert dialog.statuses == [
        ("Preview capture requested. Start a session when ready to save frames.", "green")
    ]
