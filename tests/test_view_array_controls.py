from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
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


def _make_widget(
    *,
    array_state="idle",
    has_head=True,
    preflight=None,
    refuel_preflight=None,
    choice="Cancel",
    dock_context=None,
    yes_no_responses=None,
    bypass_result=None,
    completed_view=False,
    loaded_array_state=None,
):
    if preflight is None:
        preflight = {"ok": True, "code": "ok", "message": "", "record": None}
    if refuel_preflight is None:
        refuel_preflight = {"ok": True, "code": "passed_refuel_check", "message": "", "record": {"status": "passed"}}
    if dock_context is None:
        dock_context = {"required": False, "reasons": [], "title": "", "message": ""}
    if bypass_result is None:
        bypass_result = {"status": "bypassed", "source": "print_array_preflight"}
    if loaded_array_state is None:
        loaded_array_state = (
            "no_head"
            if not has_head
            else "in_progress"
            if array_state == "resume_ready"
            else "not_started"
        )
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
        get_loaded_array_control_state=lambda: {"state": loaded_array_state},
        get_print_array_imaging_calibration_preflight=Mock(return_value=preflight),
        get_print_array_refuel_check_preflight=Mock(return_value=refuel_preflight),
        record_manual_refuel_check_bypass=Mock(return_value=bypass_result),
        get_evap_plate_dock_check_context=Mock(return_value=dock_context),
        apply_applied_imaging_calibration_print_settings=Mock(
            return_value={"ok": True, "message": "Set print pulse width to 1450 us and print pressure to 1.350 psi."}
        ),
    )
    widget.model = SimpleNamespace(
        is_completed_execution_view_active=lambda: bool(completed_view),
        rack_model=SimpleNamespace(
            gripper_printer_head=object() if has_head else None,
        )
    )
    popup_yes_no = (
        Mock(side_effect=yes_no_responses)
        if yes_no_responses is not None
        else Mock(return_value=QMessageBox.StandardButton.Yes)
    )
    widget.main_window = SimpleNamespace(
        popup_yes_no=popup_yes_no,
        popup_choice=Mock(return_value=choice),
        popup_message=Mock(),
        _is_yes_response=lambda response: MainWindow._is_yes_response(response),
        pressure_box=SimpleNamespace(manual_refuel_check_after_stream_apply=Mock()),
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
    assert widget.start_print_array_button.text == "Start Array"
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
    widget.controller.get_loaded_array_control_state = lambda: {
        "state": "in_progress"
    }
    WellPlateWidget.update_start_print_array_button(widget)
    assert widget.start_print_array_button.text == "Resume Print"
    assert widget.start_print_array_button.enabled is True


@pytest.mark.parametrize(
    ("loaded_array_state", "expected_text", "expected_enabled"),
    [
        ("complete", "Array Complete", False),
        ("no_array", "No Array", False),
        ("unavailable", "Array Unavailable", False),
        ("no_head", "Start Array", False),
    ],
)
def test_well_plate_widget_projects_non_actionable_loaded_array_states(
    loaded_array_state,
    expected_text,
    expected_enabled,
):
    widget = _make_widget(loaded_array_state=loaded_array_state)

    WellPlateWidget.update_start_print_array_button(widget)
    WellPlateWidget.start_print_array(widget)

    assert widget.start_print_array_button.text == expected_text
    assert widget.start_print_array_button.enabled is expected_enabled
    widget.main_window.popup_yes_no.assert_not_called()
    widget.controller.print_array.assert_not_called()


def test_loaded_reagent_progress_controls_start_and_resume_independent_of_global_state():
    partial = _make_widget(array_state="idle", loaded_array_state="in_progress")
    untouched = _make_widget(
        array_state="resume_ready",
        loaded_array_state="not_started",
    )

    WellPlateWidget.update_start_print_array_button(partial)
    WellPlateWidget.start_print_array(partial)
    WellPlateWidget.update_start_print_array_button(untouched)
    WellPlateWidget.start_print_array(untouched)

    assert partial.start_print_array_button.text == "Resume Print"
    partial.main_window.popup_yes_no.assert_called_once_with(
        "Resume Print Array",
        "Are you sure you want to resume the print array?",
    )
    assert untouched.start_print_array_button.text == "Start Array"
    untouched.main_window.popup_yes_no.assert_any_call(
        "Start Print Array",
        "Are you sure you want to start the print array?",
    )


def test_completed_execution_view_disables_start_and_never_dispatches():
    widget = _make_widget(
        array_state="idle",
        has_head=True,
        completed_view=True,
    )

    WellPlateWidget.update_start_print_array_button(widget)
    WellPlateWidget.start_print_array(widget)

    assert widget.start_print_array_button.text == "Experiment Complete"
    assert widget.start_print_array_button.enabled is False
    widget.controller.print_array.assert_not_called()
    widget.main_window.popup_yes_no.assert_not_called()


def test_completed_execution_view_blocks_plate_calibration_dispatch():
    widget = _make_widget(completed_view=True)
    widget.model.machine_model = SimpleNamespace(
        motors_are_enabled=Mock(return_value=True),
        motors_are_homed=Mock(return_value=True),
    )
    widget.controller.move_to_location = Mock()

    WellPlateWidget.open_calibration_dialog(widget)

    widget.controller.move_to_location.assert_not_called()


def test_well_plate_widget_resume_prompt_uses_resume_copy():
    widget = _make_widget(array_state="resume_ready", has_head=True)

    WellPlateWidget.start_print_array(widget)

    widget.main_window.popup_yes_no.assert_called_once_with(
        "Resume Print Array",
        "Are you sure you want to resume the print array?",
    )
    widget.controller.print_array.assert_called_once_with()


def test_well_plate_widget_first_print_dock_prompt_confirms_before_printing():
    widget = _make_widget(
        dock_context={
            "required": True,
            "reasons": ["first_experiment_print"],
            "title": "Evaporation Plate Dock Check",
            "message": "Confirm the evaporation plate is docked.",
        }
    )

    WellPlateWidget.start_print_array(widget)

    assert widget.main_window.popup_yes_no.call_args_list == [
        call("Start Print Array", "Are you sure you want to start the print array?"),
        call("Evaporation Plate Dock Check", "Confirm the evaporation plate is docked."),
    ]
    widget.controller.print_array.assert_called_once_with(evap_plate_dock_confirmed=True)


def test_well_plate_widget_dock_prompt_cancel_blocks_printing():
    widget = _make_widget(
        dock_context={
            "required": True,
            "reasons": ["first_experiment_print"],
            "title": "Evaporation Plate Dock Check",
            "message": "Confirm the evaporation plate is docked.",
        },
        yes_no_responses=[
            QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.No,
        ],
    )

    WellPlateWidget.start_print_array(widget)

    assert widget.main_window.popup_yes_no.call_count == 2
    widget.controller.print_array.assert_not_called()


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


def test_well_plate_widget_preflight_cancel_does_not_show_dock_prompt():
    widget = _make_widget(
        preflight={
            "ok": False,
            "code": "missing_record",
            "message": "No applied imaging calibration was found.",
            "record": None,
        },
        choice="Cancel",
        dock_context={
            "required": True,
            "reasons": ["first_experiment_print"],
            "title": "Evaporation Plate Dock Check",
            "message": "Confirm the evaporation plate is docked.",
        },
    )

    WellPlateWidget.start_print_array(widget)

    widget.controller.get_evap_plate_dock_check_context.assert_not_called()
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


def test_well_plate_widget_refuel_check_not_required_allows_printing():
    widget = _make_widget(
        refuel_preflight={"ok": True, "code": "not_required", "message": "", "record": None},
    )

    WellPlateWidget.start_print_array(widget)

    widget.controller.get_print_array_refuel_check_preflight.assert_called_once_with()
    widget.controller.print_array.assert_called_once_with()


@pytest.mark.parametrize(
    "code",
    [
        "required_refuel_check",
        "missing_refuel_check",
        "deferred_refuel_check",
        "failed_refuel_check",
        "unclear_refuel_check",
        "stale_refuel_check",
    ],
)
def test_well_plate_widget_refuel_check_cancel_blocks_printing(code):
    widget = _make_widget(
        refuel_preflight={
            "ok": False,
            "code": code,
            "message": "Manual refuel check is required.",
            "record": {"status": "required"},
        },
        choice="Cancel",
    )

    WellPlateWidget.start_print_array(widget)

    widget.main_window.popup_choice.assert_called_once()
    widget.controller.record_manual_refuel_check_bypass.assert_not_called()
    widget.main_window.pressure_box.manual_refuel_check_after_stream_apply.assert_not_called()
    widget.controller.print_array.assert_not_called()


def test_well_plate_widget_refuel_check_run_now_launches_manual_check_without_printing():
    widget = _make_widget(
        refuel_preflight={
            "ok": False,
            "code": "deferred_refuel_check",
            "message": "Manual refuel check was deferred.",
            "record": {"status": "deferred"},
        },
        choice="Run manual refuel check now",
    )

    WellPlateWidget.start_print_array(widget)

    widget.main_window.pressure_box.manual_refuel_check_after_stream_apply.assert_called_once_with()
    widget.controller.record_manual_refuel_check_bypass.assert_not_called()
    widget.controller.print_array.assert_not_called()


def test_well_plate_widget_refuel_check_bypass_records_and_prints():
    widget = _make_widget(
        refuel_preflight={
            "ok": False,
            "code": "missing_refuel_check",
            "message": "No manual refuel check has been recorded.",
            "record": None,
        },
        choice="Proceed without refuel check",
    )

    WellPlateWidget.start_print_array(widget)

    widget.controller.record_manual_refuel_check_bypass.assert_called_once_with(
        source="print_array_preflight",
        reason="operator_bypass",
    )
    widget.controller.print_array.assert_called_once_with(manual_refuel_check_bypass=True)


def test_well_plate_widget_refuel_bypass_failure_blocks_printing():
    widget = _make_widget(
        refuel_preflight={
            "ok": False,
            "code": "stale_refuel_check",
            "message": "Manual refuel check is stale.",
            "record": {"status": "passed"},
        },
        choice="Proceed without refuel check",
        bypass_result={"ok": False, "message": "recording failed"},
    )

    WellPlateWidget.start_print_array(widget)

    widget.controller.record_manual_refuel_check_bypass.assert_called_once()
    widget.main_window.popup_message.assert_called_once_with(
        "Manual Refuel Check Bypass Not Recorded",
        "recording failed",
    )
    widget.controller.print_array.assert_not_called()


def test_well_plate_widget_refuel_context_unavailable_blocks_without_bypass_prompt():
    widget = _make_widget(
        refuel_preflight={
            "ok": False,
            "code": "context_unavailable",
            "message": "No printer head is loaded.",
            "record": None,
        },
    )

    WellPlateWidget.start_print_array(widget)

    widget.main_window.popup_message.assert_called_once_with(
        "Cannot Start Print Array",
        "No printer head is loaded.",
    )
    widget.main_window.popup_choice.assert_not_called()
    widget.controller.record_manual_refuel_check_bypass.assert_not_called()
    widget.controller.print_array.assert_not_called()


def test_well_plate_widget_imaging_cancel_prevents_refuel_prompt():
    widget = _make_widget(
        preflight={
            "ok": False,
            "code": "missing_record",
            "message": "No applied imaging calibration was found.",
            "record": None,
        },
        refuel_preflight={
            "ok": False,
            "code": "required_refuel_check",
            "message": "Manual refuel check is required.",
            "record": {"status": "required"},
        },
        choice="Cancel",
    )

    WellPlateWidget.start_print_array(widget)

    widget.controller.get_print_array_refuel_check_preflight.assert_not_called()
    widget.controller.record_manual_refuel_check_bypass.assert_not_called()
    widget.controller.print_array.assert_not_called()


def test_well_plate_widget_refuel_bypass_and_dock_confirmation_pass_both_flags():
    widget = _make_widget(
        refuel_preflight={
            "ok": False,
            "code": "unclear_refuel_check",
            "message": "Manual refuel check was unclear.",
            "record": {"status": "unclear"},
        },
        choice="Proceed without refuel check",
        dock_context={
            "required": True,
            "reasons": ["first_experiment_print"],
            "title": "Evaporation Plate Dock Check",
            "message": "Confirm the evaporation plate is docked.",
        },
    )

    WellPlateWidget.start_print_array(widget)

    widget.controller.print_array.assert_called_once_with(
        manual_refuel_check_bypass=True,
        evap_plate_dock_confirmed=True,
    )


def test_well_plate_widget_reset_resume_passes_dock_confirmation_with_overrides():
    widget = _make_widget(
        array_state="resume_ready",
        preflight={
            "ok": False,
            "code": "pressure_mismatch",
            "message": "Current print pressure does not match the applied imaging calibration.",
            "record": {"run_id": "run-2", "pw_us": 1450, "pressure_psi": 1.35},
        },
        choice="Proceed with current settings",
        dock_context={
            "required": True,
            "reasons": ["after_board_reset"],
            "title": "Evaporation Plate Dock Check",
            "message": "Confirm the evaporation plate is docked after reset.",
        },
    )

    WellPlateWidget.start_print_array(widget)

    widget.controller.get_evap_plate_dock_check_context.assert_called_once_with(
        request_kind="resume"
    )
    widget.controller.print_array.assert_called_once_with(
        settings_mismatch_override=True,
        evap_plate_dock_confirmed=True,
    )


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
