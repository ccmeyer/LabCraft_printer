from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtWidgets import QMessageBox

from View import MainWindow, WellPlateWidget


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


def _make_widget(*, array_state="idle", has_head=True):
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
    )
    widget.model = SimpleNamespace(
        rack_model=SimpleNamespace(
            gripper_printer_head=object() if has_head else None,
        )
    )
    widget.main_window = SimpleNamespace(
        popup_yes_no=Mock(return_value=QMessageBox.StandardButton.Yes),
        _is_yes_response=lambda response: MainWindow._is_yes_response(response),
    )
    widget.start_print_array_button = DummyButton()
    widget.soft_stop_print_array_button = DummyButton()
    return widget


def test_well_plate_widget_refreshes_array_runner_buttons():
    widget = _make_widget(array_state="idle", has_head=True)
    WellPlateWidget.update_start_print_array_button(widget)
    assert widget.start_print_array_button.text == "Start Print"
    assert widget.start_print_array_button.enabled is True
    assert widget.soft_stop_print_array_button.text == "Stop After Well"
    assert widget.soft_stop_print_array_button.enabled is False

    widget.controller.get_array_run_state = lambda: "running"
    WellPlateWidget.update_start_print_array_button(widget)
    assert widget.start_print_array_button.enabled is False
    assert widget.soft_stop_print_array_button.enabled is True

    widget.controller.get_array_run_state = lambda: "stop_requested"
    WellPlateWidget.update_start_print_array_button(widget)
    assert widget.start_print_array_button.enabled is False
    assert widget.soft_stop_print_array_button.text == "Stop Pending"
    assert widget.soft_stop_print_array_button.enabled is False

    widget.controller.get_array_run_state = lambda: "resume_ready"
    WellPlateWidget.update_start_print_array_button(widget)
    assert widget.start_print_array_button.text == "Resume Print"
    assert widget.start_print_array_button.enabled is True
    assert widget.soft_stop_print_array_button.enabled is False


def test_well_plate_widget_resume_prompt_uses_resume_copy():
    widget = _make_widget(array_state="resume_ready", has_head=True)

    WellPlateWidget.start_print_array(widget)

    widget.main_window.popup_yes_no.assert_called_once_with(
        "Resume Print Array",
        "Are you sure you want to resume the print array?",
    )
    widget.controller.print_array.assert_called_once_with()


def test_well_plate_widget_soft_stop_calls_controller():
    widget = _make_widget(array_state="running", has_head=True)

    WellPlateWidget.request_array_soft_stop(widget)

    widget.controller.request_array_soft_stop.assert_called_once_with()
