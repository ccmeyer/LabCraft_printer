from types import SimpleNamespace

from PySide6 import QtWidgets

import View


class _Button:
    def __init__(self):
        self.enabled = None

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)


class _Controller:
    def __init__(self):
        self.calls = []

    def capture_and_advance_rack_calibration(self, token, point_name):
        self.calls.append(("capture", token, point_name))
        return True

    def move_rack_calibration_to_point(self, token, point_name):
        self.calls.append(("back", token, point_name))
        return True

    def jog_rack_calibration(self, token, **deltas):
        self.calls.append(("jog", token, deltas))
        return True


def _dialog(*, current_step=0):
    dialog = View.RackCalibrationDialog.__new__(View.RackCalibrationDialog)
    dialog.session_token = "rack-session"
    dialog._automatic_motion_pending = False
    dialog._workflow_interrupted = False
    dialog.current_step = current_step
    dialog.steps = ["Left", "Right"]
    dialog.name_dict = {
        "Left": "rack_position_Left",
        "Right": "rack_position_Right",
    }
    dialog.controller = _Controller()
    dialog.model = SimpleNamespace(
        machine_model=SimpleNamespace(is_busy=lambda: False),
    )
    dialog.main_window = SimpleNamespace(popup_message=lambda *_args: None)
    dialog.next_button = _Button()
    dialog.back_button = _Button()
    dialog.submit_button = _Button()
    dialog.set_automatic_motion_pending = lambda pending: setattr(
        dialog, "_automatic_motion_pending", bool(pending)
    )
    dialog.update_step_labels = lambda: None
    dialog.update_visual_aid = lambda: None
    return dialog


def test_rack_dialog_initial_move_is_side_effect_free():
    dialog = _dialog()

    result = View.RackCalibrationDialog.move_to_initial_position(dialog)

    assert result is True
    assert dialog.controller.calls == []


def test_rack_dialog_constructor_is_motion_free(qapp, monkeypatch):
    monkeypatch.setattr(
        View,
        "SimplePositionWidget",
        lambda *_args, **_kwargs: QtWidgets.QWidget(),
    )
    monkeypatch.setattr(
        View,
        "ShortcutTableWidget",
        lambda *_args, **_kwargs: QtWidgets.QWidget(),
    )
    motion_calls = []
    machine_model = SimpleNamespace(
        step_size=500,
        increase_step_size=lambda: None,
        decrease_step_size=lambda: None,
    )
    rack_model = SimpleNamespace(
        get_all_current_rack_calibrations=lambda: {
            "rack_position_Left": {"X": 104, "Y": 2000, "Z": 65500},
            "rack_position_Right": {"X": 204, "Y": 41350, "Z": 66600},
        }
    )
    model = SimpleNamespace(machine_model=machine_model, rack_model=rack_model)
    main_window = SimpleNamespace(
        color_dict={
            "dark_blue": "#000088",
            "dark_red": "#880000",
            "dark_gray": "#444444",
            "darker_gray": "#222222",
        }
    )
    controller = SimpleNamespace(
        set_absolute_coordinates=lambda *args, **kwargs: motion_calls.append(
            (args, kwargs)
        ),
        jog_rack_calibration=lambda *args, **kwargs: motion_calls.append(
            (args, kwargs)
        ),
    )

    dialog = View.RackCalibrationDialog(
        main_window,
        model,
        controller,
        session_token="rack-session",
        manual_first=True,
    )

    assert motion_calls == []
    assert "safe Z=500" in dialog.instructions_label.text()
    dialog.deleteLater()


def test_rack_dialog_capture_delegates_to_session_controller():
    dialog = _dialog(current_step=0)

    result = View.RackCalibrationDialog.next_step(dialog)

    assert result is True
    assert dialog.current_step == 1
    assert dialog._automatic_motion_pending is True
    assert dialog.controller.calls == [
        ("capture", "rack-session", "rack_position_Left")
    ]


def test_rack_dialog_back_delegates_to_session_controller():
    dialog = _dialog(current_step=1)

    result = View.RackCalibrationDialog.previous_step(dialog)

    assert result is True
    assert dialog.current_step == 0
    assert dialog._automatic_motion_pending is True
    assert dialog.controller.calls == [
        ("back", "rack-session", "rack_position_Left")
    ]


def test_rack_dialog_manual_jog_is_session_bound():
    dialog = _dialog()

    result = View.RackCalibrationDialog.request_relative_jog(
        dialog, 0, 0, -500
    )

    assert result is True
    assert dialog.controller.calls == [
        ("jog", "rack-session", {"x": 0, "y": 0, "z": -500})
    ]


def test_rack_dialog_rejects_actions_during_automatic_motion():
    dialog = _dialog(current_step=1)
    dialog._automatic_motion_pending = True

    assert View.RackCalibrationDialog.next_step(dialog) is False
    assert View.RackCalibrationDialog.previous_step(dialog) is False
    assert View.RackCalibrationDialog.request_relative_jog(dialog, 500, 0, 0) is False
    assert dialog.controller.calls == []
