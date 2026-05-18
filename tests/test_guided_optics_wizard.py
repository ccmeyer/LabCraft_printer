from types import SimpleNamespace
from unittest.mock import Mock

from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import QMessageBox

import View
from View import OpticsCalibrationApproachWizardDialog, PressurePlotBox
from hardware.profile import CURRENT_PROFILE
from tests.test_pressure_plotbox_buttons import (
    _FakeMachineModel,
    _make_controller,
    _make_main_window,
    _make_model,
)


class _WizardMachineModel(QtCore.QObject):
    home_status_signal = QtCore.Signal()
    step_size_changed = QtCore.Signal(int)

    def __init__(self):
        super().__init__()
        self.step_size = 500
        self.current_z = 500

    def get_current_position_dict(self):
        return {"X": 500, "Y": 500, "Z": self.current_z}

    def increase_step_size(self):
        self.step_size = 1000
        self.step_size_changed.emit(self.step_size)

    def decrease_step_size(self):
        self.step_size = 250
        self.step_size_changed.emit(self.step_size)


class _LocationModel:
    def __init__(self, *, locations=None):
        self.locations = locations or {
            "home": {"X": 500, "Y": 500, "Z": 500},
            "camera": {"X": 11563, "Y": 39550, "Z": 99388},
        }

    def get_location_dict(self, name):
        return self.locations.get(name)


class _WizardMainWindow:
    color_dict = {"darker_gray": "#222", "dark_blue": "#123", "light_blue": "#79f"}
    _is_yes_response = staticmethod(View.MainWindow._is_yes_response)

    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []
        self.popup_yes_no = Mock(side_effect=self._popup_yes_no)

    def _popup_yes_no(self, *_args):
        if self.responses:
            return self.responses.pop(0)
        return QMessageBox.StandardButton.Yes

    def popup_message(self, title, message):
        self.messages.append((title, message))


class _WizardController:
    def __init__(self, machine_model):
        self.machine_model = machine_model
        self.events = []
        self.expected_position = {"X": 500, "Y": 500, "Z": 500}
        self.queue_clear = True
        self.fail_next_z = False

    def check_if_all_completed(self):
        return self.queue_clear

    def home_machine(self):
        self.events.append("home")
        self.machine_model.home_status_signal.emit()
        return True

    def open_gripper(self, handler=None):
        self.events.append("open_gripper")
        if callable(handler):
            handler()
        return True

    def close_gripper(self, handler=None):
        self.events.append("close_gripper")
        if callable(handler):
            handler()
        return True

    def set_absolute_XY(self, x, y, manual=False, handler=None):
        self.events.append(("xy", int(x), int(y), bool(manual)))
        self.expected_position["X"] = int(x)
        self.expected_position["Y"] = int(y)
        if callable(handler):
            handler()
        return True

    def set_absolute_Z(self, z, manual=False, handler=None):
        if self.fail_next_z:
            self.events.append(("z_failed", int(z), bool(manual)))
            return False
        self.events.append(("z", int(z), bool(manual)))
        self.expected_position["Z"] = int(z)
        self.machine_model.current_z = int(z)
        if callable(handler):
            handler()
        return True

    def set_relative_X(self, delta, manual=False):
        self.events.append(("rel_x", int(delta), bool(manual)))
        self.expected_position["X"] += int(delta)
        return True

    def set_relative_Y(self, delta, manual=False):
        self.events.append(("rel_y", int(delta), bool(manual)))
        self.expected_position["Y"] += int(delta)
        return True

    def set_relative_Z(self, delta, manual=False):
        self.events.append(("rel_z", int(delta), bool(manual)))
        self.expected_position["Z"] += int(delta)
        self.machine_model.current_z = self.expected_position["Z"]
        return True

    def pause_machine(self):
        self.events.append("pause")


def _make_wizard(responses):
    machine = _WizardMachineModel()
    model = SimpleNamespace(machine_model=machine, location_model=_LocationModel())
    controller = _WizardController(machine)
    main_window = _WizardMainWindow(responses)
    dialog = OpticsCalibrationApproachWizardDialog(main_window, model, controller)
    return dialog, main_window, controller


def test_guided_wizard_happy_path_queues_guarded_sequence(qapp):
    dialog, main_window, controller = _make_wizard(
        [
            QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Yes,
        ]
    )

    dialog.begin()
    assert controller.events == ["home", "open_gripper"]
    assert dialog.step_name == "waiting_micrometer"

    dialog.advance_step()
    assert controller.events[-1] == "close_gripper"
    assert dialog.step_name == "waiting_waste_holder"

    dialog.advance_step()
    assert controller.events[-1] == ("xy", 11563, 39550, True)
    assert dialog.step_name == "waiting_entry_alignment"

    dialog.advance_step()
    assert controller.events[-1] == ("z", 98388, True)
    assert dialog.result() == QtWidgets.QDialog.Accepted
    assert main_window.popup_yes_no.call_count == 3


def test_guided_wizard_initial_decline_queues_no_motion(qapp):
    dialog, _main_window, controller = _make_wizard([QMessageBox.StandardButton.No])

    dialog.begin()

    assert controller.events == []
    assert dialog.result() == QtWidgets.QDialog.Rejected


def test_guided_wizard_waste_holder_decline_blocks_camera_motion(qapp):
    dialog, _main_window, controller = _make_wizard(
        [
            QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.No,
        ]
    )

    dialog.begin()
    dialog.advance_step()
    dialog.advance_step()

    assert dialog.step_name == "waiting_waste_holder"
    assert not any(isinstance(event, tuple) and event[0] == "xy" for event in controller.events)


def test_guided_wizard_manual_branch_jogs_and_clamps_z(qapp):
    dialog, _main_window, controller = _make_wizard(
        [
            QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.No,
        ]
    )

    dialog.begin()
    dialog.advance_step()
    dialog.advance_step()
    dialog.advance_step()

    assert dialog.step_name == "manual_alignment"
    assert dialog.manual_jog("X", 1) is True
    assert controller.events[-1] == ("rel_x", 500, True)

    controller.expected_position["Z"] = dialog.approach_z
    assert dialog.manual_jog("Z", 1) is False
    assert controller.events[-1] == ("rel_x", 500, True)


def test_guided_wizard_motion_failure_stops_before_launch(qapp):
    dialog, _main_window, controller = _make_wizard(
        [
            QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Yes,
        ]
    )
    controller.fail_next_z = True

    dialog.begin()
    dialog.advance_step()
    dialog.advance_step()
    dialog.advance_step()

    assert dialog.step_name == "failed"
    assert dialog.result() == 0
    assert controller.events[-1] == ("z_failed", 98388, True)


def _pressure_box_with_guided_locations(
    monkeypatch,
    *,
    queue_clear=True,
    machine_connected=True,
    motors_enabled=True,
    locations=None,
):
    events = []
    popups = []
    main_window = _make_main_window(
        CURRENT_PROFILE,
        popups,
        popup_response=QMessageBox.StandardButton.Yes,
    )
    machine = _FakeMachineModel(regulating_print_pressure=False)
    if not machine_connected:
        machine.is_connected = lambda: False
    if not motors_enabled:
        machine.motors_are_enabled = lambda: False
    model = _make_model(machine, events, printer_head=None)
    model.location_model = _LocationModel(locations=locations)
    controller = _make_controller(events, queue_clear=queue_clear)
    box = PressurePlotBox(main_window, model, controller)
    return box, main_window, model, controller, events, popups


def test_guided_start_blocks_when_commands_active(monkeypatch, qapp):
    box, _main_window, _model, _controller, _events, popups = _pressure_box_with_guided_locations(
        monkeypatch,
        queue_clear=False,
    )

    box.start_guided_optics_calibration()

    assert popups == [
        (
            "Commands Still Running",
            "Please wait for the current commands to finish before starting guided optics calibration.",
        )
    ]


def test_guided_start_requires_motors_enabled(monkeypatch, qapp):
    box, _main_window, _model, _controller, _events, popups = _pressure_box_with_guided_locations(
        monkeypatch,
        motors_enabled=False,
    )

    box.start_guided_optics_calibration()

    assert popups == [
        (
            "Motors Not Enabled",
            "Please enable the motors before starting guided optics calibration.",
        )
    ]


def test_guided_start_requires_machine_connected(monkeypatch, qapp):
    box, _main_window, _model, _controller, _events, popups = _pressure_box_with_guided_locations(
        monkeypatch,
        machine_connected=False,
    )

    box.start_guided_optics_calibration()

    assert popups == [
        (
            "Machine Not Connected",
            "Please connect to the machine before starting guided optics calibration.",
        )
    ]


def test_guided_start_requires_valid_home_and_camera_locations(monkeypatch, qapp):
    box, _main_window, _model, _controller, _events, popups = _pressure_box_with_guided_locations(
        monkeypatch,
        locations={"home": {"X": 500, "Y": 500, "Z": 500}},
    )

    box.start_guided_optics_calibration()

    assert popups == [("Invalid Optics Locations", "Location 'camera' is missing.")]


def test_guided_start_does_not_require_head_or_pressure(monkeypatch, qapp):
    box, _main_window, _model, _controller, events, popups = _pressure_box_with_guided_locations(monkeypatch)

    class _FakeWizard:
        @staticmethod
        def validate_locations(_model):
            return (
                {"X": 500, "Y": 500, "Z": 500},
                {"X": 11563, "Y": 39550, "Z": 99388},
            )

        def __init__(self, *_args):
            events.append("wizard_init")

        def exec(self):
            events.append("wizard_exec")
            return QtWidgets.QDialog.Rejected

        def should_prompt_cleanup(self):
            return False

    monkeypatch.setattr(View, "OpticsCalibrationApproachWizardDialog", _FakeWizard)

    box.start_guided_optics_calibration()

    assert "wizard_init" in events
    assert "wizard_exec" in events
    assert popups == []


def test_guided_cleanup_decline_leaves_machine_in_place(monkeypatch, qapp):
    box, main_window, _model, controller, events, popups = _pressure_box_with_guided_locations(monkeypatch)
    main_window.popup_yes_no.return_value = QMessageBox.StandardButton.No
    controller.set_absolute_Z = Mock()
    controller.set_absolute_XY = Mock()
    controller.open_gripper = Mock()

    box._prompt_guided_optics_cleanup()

    controller.set_absolute_Z.assert_not_called()
    controller.set_absolute_XY.assert_not_called()
    controller.open_gripper.assert_not_called()
    assert events == []
    assert popups == [
        (
            "Optics Cleanup Reminder",
            "Leave the machine safe and remove the micrometer and adapter before returning to normal operation.",
        )
    ]


def test_guided_cleanup_prompt_queues_home_z_xy_and_gripper(monkeypatch, qapp):
    box, main_window, _model, controller, events, popups = _pressure_box_with_guided_locations(monkeypatch)

    def _set_absolute_z(z, manual=False, handler=None):
        events.append(("cleanup_z", int(z), bool(manual)))
        if callable(handler):
            handler()
        return True

    def _set_absolute_xy(x, y, manual=False, handler=None):
        events.append(("cleanup_xy", int(x), int(y), bool(manual)))
        if callable(handler):
            handler()
        return True

    def _open_gripper(handler=None):
        events.append("cleanup_open")
        if callable(handler):
            handler()
        return True

    controller.set_absolute_Z = Mock(side_effect=_set_absolute_z)
    controller.set_absolute_XY = Mock(side_effect=_set_absolute_xy)
    controller.open_gripper = Mock(side_effect=_open_gripper)

    box._prompt_guided_optics_cleanup()

    assert main_window.popup_yes_no.call_count == 1
    assert events[-3:] == [
        ("cleanup_z", 500, True),
        ("cleanup_xy", 500, 500, True),
        "cleanup_open",
    ]
    assert popups[-1] == (
        "Remove Micrometer",
        "The gripper is open. Remove the micrometer adapter before normal operation.",
    )
