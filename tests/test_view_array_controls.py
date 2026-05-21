from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtWidgets import QMessageBox

from View import CommandQueueWidget, MainWindow, WellPlateWidget


class DummyButton:
    def __init__(self):
        self.text = ""
        self.enabled = None
        self.style = ""

    def setText(self, text):
        self.text = text

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)

    def setStyleSheet(self, style):
        self.style = style


def _make_widget(*, array_state="idle", has_head=True, preflight=None, choice="Cancel"):
    if preflight is None:
        preflight = {"ok": True, "code": "ok", "message": "", "record": None}
    widget = WellPlateWidget.__new__(WellPlateWidget)
    widget.color_dict = {
        "dark_blue": "#123456",
        "dark_red": "#654321",
        "darker_gray": "#111111",
    }
    widget.controller = SimpleNamespace(
        check_if_all_completed=lambda: True,
        print_array=Mock(),
        request_array_soft_stop=Mock(),
        get_array_run_state=lambda: array_state,
        get_print_array_imaging_calibration_preflight=Mock(return_value=preflight),
        apply_applied_imaging_calibration_print_settings=Mock(
            return_value={"ok": True, "message": "Set print pulse width to 1450 us and print pressure to 1.350 psi."}
        ),
    )
    widget.model = SimpleNamespace(
        rack_model=SimpleNamespace(
            gripper_printer_head=object() if has_head else None,
        )
    )
    widget.main_window = SimpleNamespace(
        popup_yes_no=Mock(return_value=QMessageBox.StandardButton.Yes),
        popup_choice=Mock(return_value=choice),
        popup_message=Mock(),
        _is_yes_response=lambda response: MainWindow._is_yes_response(response),
    )
    widget.start_print_array_button = DummyButton()
    return widget


class DummySignal:
    def connect(self, _callback):
        return None


class DummyCommand:
    def __init__(self, number, command, status):
        self._number = int(number)
        self._command = str(command)
        self.status = str(status)

    def get_number(self):
        return self._number

    def get_command(self):
        return self._command


def test_well_plate_widget_refreshes_array_runner_buttons():
    widget = _make_widget(array_state="idle", has_head=True)
    WellPlateWidget.update_start_print_array_button(widget)
    assert widget.start_print_array_button.text == "Start Print"
    assert widget.start_print_array_button.enabled is True

    widget.controller.get_array_run_state = lambda: "running"
    WellPlateWidget.update_start_print_array_button(widget)
    assert widget.start_print_array_button.text == "Stop After Well"
    assert widget.start_print_array_button.enabled is True

    widget.controller.get_array_run_state = lambda: "stop_requested"
    WellPlateWidget.update_start_print_array_button(widget)
    assert widget.start_print_array_button.text == "Stop Pending"
    assert widget.start_print_array_button.enabled is False

    widget.controller.get_array_run_state = lambda: "resume_ready"
    WellPlateWidget.update_start_print_array_button(widget)
    assert widget.start_print_array_button.text == "Resume Print"
    assert widget.start_print_array_button.enabled is True


def test_well_plate_widget_resume_prompt_uses_resume_copy():
    widget = _make_widget(array_state="resume_ready", has_head=True)

    WellPlateWidget.start_print_array(widget)

    widget.main_window.popup_yes_no.assert_called_once_with(
        "Resume Print Array",
        "Are you sure you want to resume the print array?",
    )
    widget.controller.print_array.assert_called_once_with()


def test_well_plate_widget_missing_applied_calibration_cancel_does_not_print():
    widget = _make_widget(
        preflight={
            "ok": False,
            "code": "missing_record",
            "message": "No applied imaging calibration was found.",
            "record": None,
        },
        choice="Cancel",
    )

    WellPlateWidget.start_print_array(widget)

    widget.main_window.popup_choice.assert_called_once()
    widget.controller.print_array.assert_not_called()


def test_well_plate_widget_missing_applied_calibration_can_proceed_with_override():
    widget = _make_widget(
        preflight={
            "ok": False,
            "code": "missing_record",
            "message": "No applied imaging calibration was found.",
            "record": None,
        },
        choice="Proceed without applied calibration",
    )

    WellPlateWidget.start_print_array(widget)

    widget.controller.print_array.assert_called_once_with(imaging_calibration_override=True)


def test_well_plate_widget_settings_mismatch_switches_settings_without_printing():
    record = {"run_id": "run-2", "pw_us": 1450, "pressure_psi": 1.35}
    widget = _make_widget(
        preflight={
            "ok": False,
            "code": "pulse_width_mismatch",
            "message": "Print pulse width does not match the applied imaging calibration.",
            "record": record,
        },
        choice="Switch to applied calibration settings",
    )

    WellPlateWidget.start_print_array(widget)

    widget.controller.apply_applied_imaging_calibration_print_settings.assert_called_once_with(record)
    widget.main_window.popup_message.assert_called_once()
    widget.controller.print_array.assert_not_called()


def test_well_plate_widget_settings_mismatch_can_proceed_with_override():
    widget = _make_widget(
        preflight={
            "ok": False,
            "code": "pressure_mismatch",
            "message": "Current print pressure does not match the applied imaging calibration.",
            "record": {"run_id": "run-2", "pw_us": 1450, "pressure_psi": 1.35},
        },
        choice="Proceed with current settings",
    )

    WellPlateWidget.start_print_array(widget)

    widget.controller.print_array.assert_called_once_with(settings_mismatch_override=True)


def test_shift_p_shortcut_uses_well_plate_print_launch_path():
    shortcuts = {}

    class RecorderShortcutManager:
        def add_shortcut(self, key, _name, callback):
            shortcuts[key] = callback

    main_window = MainWindow.__new__(MainWindow)
    main_window.shortcut_manager = RecorderShortcutManager()
    main_window.controller = SimpleNamespace()
    main_window.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            step_size=1,
            increase_step_size=Mock(),
            decrease_step_size=Mock(),
        )
    )
    main_window.well_plate_widget = SimpleNamespace(start_print_array=Mock())

    MainWindow.setup_shortcuts(main_window)
    shortcuts["Shift+p"]()

    main_window.well_plate_widget.start_print_array.assert_called_once_with()


def test_well_plate_widget_running_button_requests_soft_stop():
    widget = _make_widget(array_state="running", has_head=True)

    WellPlateWidget.start_print_array(widget)

    widget.controller.request_array_soft_stop.assert_called_once_with()
    widget.main_window.popup_yes_no.assert_not_called()
    widget.controller.print_array.assert_not_called()


def test_command_queue_widget_accepted_rows_use_darker_gray(qapp):
    command_queue = SimpleNamespace(
        queue=[DummyCommand(12, "MOVE", "Accepted")],
        completed=[],
        queue_updated=DummySignal(),
    )
    machine = SimpleNamespace(command_queue=command_queue)
    main_window = SimpleNamespace(
        color_dict={
            "darker_gray": "#111111",
            "mid_gray": "#777777",
            "dark_gray": "#444444",
            "light_gray": "#dddddd",
            "dark_red": "#880000",
            "mid_red": "#aa4444",
        }
    )

    widget = CommandQueueWidget(main_window, machine)

    assert widget.table.item(0, 0).background().color().name().lower() == "#444444"


def test_command_queue_widget_canceled_rows_fall_back_to_dark_red_when_mid_red_missing(qapp):
    command_queue = SimpleNamespace(
        queue=[DummyCommand(13, "MOVE", "Canceled")],
        completed=[],
        queue_updated=DummySignal(),
    )
    machine = SimpleNamespace(command_queue=command_queue)
    main_window = SimpleNamespace(
        color_dict={
            "darker_gray": "#111111",
            "mid_gray": "#777777",
            "dark_gray": "#444444",
            "light_gray": "#dddddd",
            "dark_red": "#880000",
        }
    )

    widget = CommandQueueWidget(main_window, machine)

    assert widget.table.item(0, 0).background().color().name().lower() == "#880000"
