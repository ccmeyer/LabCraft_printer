from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, call

from Controller import Controller


class SignalRecorder:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class ResetWell:
    def __init__(self, remaining):
        self.remaining = int(remaining)

    def get_remaining_droplets(self, _stock_id):
        return self.remaining


class ResetWellPlate:
    def __init__(self, remaining):
        self.remaining = int(remaining)

    def get_all_wells_with_reactions(self, fill_by="rows", serpentine=True):
        return [ResetWell(self.remaining)]


def _make_reset_controller(tmp_path, *, array_state="idle", has_progress=False, remaining=5):
    events = []
    popups = []

    controller = Controller.__new__(Controller)
    controller._repo_root = tmp_path
    controller._reset_report_log_path = tmp_path / "board_reset_reports.jsonl"
    controller.machine = SimpleNamespace(get_reset_debug_bundle_context=lambda: {})
    controller.array_state_changed = SignalRecorder()
    controller.error_occurred_signal = SimpleNamespace(
        emit=lambda title, message: popups.append((title, message))
    )
    controller.expected_position = {"X": 9, "Y": 9, "Z": 9}
    controller.expected_location = "Home"
    controller._array_state = array_state
    controller._array_context = {
        "stock_id": "stock-a",
        "queued_wells": [{"well_id": "A1", "target_droplets": 5}],
        "planned_well_ids": {"A1"},
        "current_barrier_seq32": 123,
    }
    controller._soft_stop_clear_uncertain = True
    controller.model = SimpleNamespace(
        record_experiment_audit_event=Mock(),
        machine_model=SimpleNamespace(
            recover_after_board_reset=lambda: events.append(("recover", None)),
            update_last_reset_report=lambda report: events.append(("update", dict(report))),
            get_current_position_dict=lambda: {"X": 1, "Y": 2, "Z": 3},
            get_current_print_pressure=lambda: 1.11,
            get_target_print_pressure=lambda: 1.23,
            get_current_refuel_pressure=lambda: 0.44,
            get_target_refuel_pressure=lambda: 0.56,
            get_print_pulse_width=lambda: 1450,
            get_refuel_pulse_width=lambda: 3200,
        ),
        rack_model=SimpleNamespace(
            get_gripper_printer_head=lambda: SimpleNamespace(get_stock_id=lambda: "stock-a"),
            gripper_printer_head=SimpleNamespace(get_stock_id=lambda: "stock-a"),
        ),
        well_plate=ResetWellPlate(remaining),
        experiment_model=SimpleNamespace(
            get_progress_status=lambda: {"has_printed_progress": bool(has_progress)}
        ),
    )
    return controller, events, popups


def test_handle_reset_report_logs_and_emits_popup(tmp_path):
    events = []
    popups = []

    controller = Controller.__new__(Controller)
    controller._repo_root = tmp_path
    controller._reset_report_log_path = tmp_path / "board_reset_reports.jsonl"
    controller.machine = SimpleNamespace(
        get_reset_debug_bundle_context=lambda: {
            "port": "COM9",
            "profile": "test_profile",
            "black_box_session_id": "session-abc",
            "black_box_snapshots": [
                {"path": str(tmp_path / "reset_report.json"), "reason": "reset_report"}
            ],
        }
    )
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            recover_after_board_reset=lambda: events.append(("recover", None)),
            update_last_reset_report=lambda report: events.append(("update", dict(report))),
            get_current_position_dict=lambda: {"X": 1, "Y": 2, "Z": 3},
        )
    )
    controller.error_occurred_signal = SimpleNamespace(
        emit=lambda title, message: popups.append((title, message))
    )
    controller.expected_position = {"X": 9, "Y": 9, "Z": 9}
    controller.expected_location = "Home"

    report = {"summary": "Board restarted after watchdog reset."}

    Controller.handle_reset_report(controller, report)

    assert events == [("recover", None), ("update", report)]
    assert controller.expected_position == {"X": 1, "Y": 2, "Z": 3}
    assert controller.expected_location is None
    assert len(popups) == 1
    assert popups[0][0] == "Board Reset Detected"
    assert "Board restarted after watchdog reset." in popups[0][1]
    assert "Homing state was cleared. Home the motors before resuming motion." in popups[0][1]
    assert "confirm the evaporation plate is in the dock position" in popups[0][1]
    assert "Saved to:" in popups[0][1]
    assert str(controller._reset_report_log_path) in popups[0][1]
    assert controller._reset_report_log_path.exists()
    text = controller._reset_report_log_path.read_text(encoding="utf-8")
    assert '"summary": "Board restarted after watchdog reset."' in text
    context = controller._last_reset_debug_bundle_context
    assert context["reset_report"] == report
    assert context["reset_report_log_path"] == str(controller._reset_report_log_path)
    assert context["reset_report_log_error"] is None
    assert context["port"] == "COM9"
    assert context["black_box_session_id"] == "session-abc"
    assert context["black_box_snapshots"][0]["reason"] == "reset_report"


def test_handle_reset_report_marks_active_array_resume_ready_when_progress_exists(tmp_path):
    controller, events, popups = _make_reset_controller(
        tmp_path,
        array_state="running",
        has_progress=True,
        remaining=4,
    )

    Controller.handle_reset_report(controller, {"summary": "Board restarted."})

    assert controller.get_array_run_state() == "resume_ready"
    assert controller._array_context is None
    assert controller._soft_stop_clear_uncertain is False
    assert controller.array_state_changed.calls == [("resume_ready",)]
    assert events == [("recover", None), ("update", {"summary": "Board restarted."})]
    assert popups[0][0] == "Board Reset Detected"
    controller.model.record_experiment_audit_event.assert_called_once()
    assert controller.model.record_experiment_audit_event.call_args.args[:2] == (
        "print_array_interrupted_by_board_reset",
        "Print array interrupted by board reset",
    )
    assert controller.model.record_experiment_audit_event.call_args.kwargs["level"] == "warning"


def test_handle_reset_report_marks_active_array_idle_without_progress(tmp_path):
    controller, _events, _popups = _make_reset_controller(
        tmp_path,
        array_state="running",
        has_progress=False,
        remaining=4,
    )

    Controller.handle_reset_report(controller, {"summary": "Board restarted."})

    assert controller.get_array_run_state() == "idle"
    assert controller._array_context is None
    assert controller.array_state_changed.calls == [("idle",)]


def test_update_machine_connection_status_restores_reset_print_settings_once():
    controller = Controller.__new__(Controller)
    controller._pending_reset_print_settings_restore = {
        "target_print_pressure_psi": 1.23,
        "target_refuel_pressure_psi": 0.56,
        "print_pulse_width_us": 1450,
        "refuel_pulse_width_us": 3200,
    }
    controller.model = SimpleNamespace(machine_model=SimpleNamespace(connect_machine=Mock()))
    controller.set_print_pulse_width = Mock(return_value=True)
    controller.set_refuel_pulse_width = Mock(return_value=True)
    controller.set_absolute_print_pressure = Mock(return_value=True)
    controller.set_absolute_refuel_pressure = Mock(return_value=True)

    Controller.update_machine_connection_status(controller, True)
    Controller.update_machine_connection_status(controller, True)

    controller.model.machine_model.connect_machine.assert_has_calls([call(), call()])
    controller.set_print_pulse_width.assert_called_once_with(
        1450,
        manual=True,
        trace_metadata={
            "source": "board_reset_reconnect_restore",
            "setting_key": "print_pulse_width_us",
        },
    )
    controller.set_refuel_pulse_width.assert_called_once_with(
        3200,
        manual=True,
        trace_metadata={
            "source": "board_reset_reconnect_restore",
            "setting_key": "refuel_pulse_width_us",
        },
    )
    controller.set_absolute_print_pressure.assert_called_once_with(
        1.23,
        manual=True,
        trace_metadata={
            "source": "board_reset_reconnect_restore",
            "setting_key": "target_print_pressure_psi",
        },
    )
    controller.set_absolute_refuel_pressure.assert_called_once_with(
        0.56,
        manual=True,
        trace_metadata={
            "source": "board_reset_reconnect_restore",
            "setting_key": "target_refuel_pressure_psi",
        },
    )
    assert controller._pending_reset_print_settings_restore is None


def test_handle_reset_report_emits_popup_when_log_write_fails():
    events = []
    popups = []

    controller = Controller.__new__(Controller)
    controller._repo_root = Path.cwd()
    controller.machine = SimpleNamespace(get_reset_debug_bundle_context=lambda: {})
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            recover_after_board_reset=lambda: events.append(("recover", None)),
            update_last_reset_report=lambda report: events.append(("update", dict(report))),
            get_current_position_dict=lambda: {"X": 1, "Y": 2, "Z": 3},
        )
    )
    controller.error_occurred_signal = SimpleNamespace(
        emit=lambda title, message: popups.append((title, message))
    )
    controller.expected_position = {"X": 9, "Y": 9, "Z": 9}
    controller.expected_location = "Home"

    def _raise_log_error(_report):
        raise OSError("disk unavailable")

    controller._append_reset_report_log = _raise_log_error
    report = {"summary": "Board restarted after power/brownout reset."}

    Controller.handle_reset_report(controller, report)

    assert events == [("recover", None), ("update", report)]
    assert controller.expected_position == {"X": 1, "Y": 2, "Z": 3}
    assert controller.expected_location is None
    assert len(popups) == 1
    assert popups[0][0] == "Board Reset Detected"
    assert "Board restarted after power/brownout reset." in popups[0][1]
    assert "Homing state was cleared. Home the motors before resuming motion." in popups[0][1]
    assert "confirm the evaporation plate is in the dock position" in popups[0][1]
    assert "Log save failed: disk unavailable" in popups[0][1]
    assert controller._last_reset_debug_bundle_context["reset_report"] == report
    assert controller._last_reset_debug_bundle_context["reset_report_log_error"] == "disk unavailable"


def test_export_last_reset_debug_bundle_packages_current_context(tmp_path):
    controller = Controller.__new__(Controller)
    controller._last_reset_debug_bundle_context = {
        "repo_root": str(tmp_path),
        "reset_report": {
            "summary": "Board restarted after watchdog reset.",
            "reset_cause_name": "iwdg",
            "seq32": 77,
        },
        "black_box_snapshots": [],
    }

    result = Controller.export_last_reset_debug_bundle(controller, output_dir=tmp_path)

    archive_path = Path(result["archive_path"])
    assert archive_path.exists()
    assert archive_path.parent == tmp_path
    assert result["archive_size_bytes"] > 0
    assert result["manifest"]["reset"]["reset_cause_name"] == "iwdg"


def test_export_last_reset_debug_bundle_requires_context(tmp_path):
    controller = Controller.__new__(Controller)
    controller._last_reset_debug_bundle_context = None

    try:
        Controller.export_last_reset_debug_bundle(controller, output_dir=tmp_path)
    except RuntimeError as exc:
        assert "No board reset debug context" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_handle_serial_connection_lost_emits_guidance_popup():
    popups = []

    controller = Controller.__new__(Controller)
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            get_current_position_dict=lambda: {"X": 1, "Y": 2, "Z": 3},
        )
    )
    controller.error_occurred_signal = SimpleNamespace(
        emit=lambda title, message: popups.append((title, message))
    )
    controller.expected_position = {"X": 9, "Y": 9, "Z": 9}
    controller.expected_location = "Home"

    Controller.handle_serial_connection_lost(
        controller,
        {
            "summary": "Machine serial connection ended unexpectedly (serial closed).",
            "black_box_log_path": "logs/machine_black_box/session.json",
            "black_box_log_error": None,
        },
    )

    assert controller.expected_position == {"X": 1, "Y": 2, "Z": 3}
    assert controller.expected_location is None
    assert popups[0][0] == "Machine Connection Lost"
    assert "Machine serial connection ended unexpectedly" in popups[0][1]
    assert "Machine state is no longer trusted." in popups[0][1]
    assert "Reconnect to the MCU and home the motors" in popups[0][1]
    assert "Black-box log: logs/machine_black_box/session.json" in popups[0][1]
    context = controller._last_connection_loss_debug_bundle_context
    assert context["bundle_kind"] == "connection_loss"
    assert context["connection_loss_report"]["black_box_log_path"] == "logs/machine_black_box/session.json"
    assert context["black_box_snapshots"][0]["reason"] == "serial_reader_stopped"
    assert context["black_box_snapshots"][0]["path"] == "logs/machine_black_box/session.json"


def test_handle_serial_connection_lost_popup_survives_black_box_write_failure():
    popups = []

    controller = Controller.__new__(Controller)
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            get_current_position_dict=lambda: {"X": 1, "Y": 2, "Z": 3},
        )
    )
    controller.error_occurred_signal = SimpleNamespace(
        emit=lambda title, message: popups.append((title, message))
    )
    controller.expected_position = {"X": 9, "Y": 9, "Z": 9}
    controller.expected_location = "Home"

    Controller.handle_serial_connection_lost(
        controller,
        {
            "summary": "Machine serial connection ended unexpectedly (OSError: device disconnected).",
            "black_box_log_path": None,
            "black_box_log_error": "disk unavailable",
        },
    )

    assert popups[0][0] == "Machine Connection Lost"
    assert "OSError: device disconnected" in popups[0][1]
    assert "Black-box log save failed: disk unavailable" in popups[0][1]
    context = controller._last_connection_loss_debug_bundle_context
    assert context["bundle_kind"] == "connection_loss"
    assert context["connection_loss_report"]["black_box_log_error"] == "disk unavailable"


def test_handle_serial_connection_lost_preserves_mcu_unresponsive_snapshot_reason():
    popups = []

    controller = Controller.__new__(Controller)
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            get_current_position_dict=lambda: {"X": 1, "Y": 2, "Z": 3},
        )
    )
    controller.error_occurred_signal = SimpleNamespace(
        emit=lambda title, message: popups.append((title, message))
    )
    controller.expected_position = {"X": 9, "Y": 9, "Z": 9}
    controller.expected_location = "Home"

    Controller.handle_serial_connection_lost(
        controller,
        {
            "reason": "mcu_unresponsive",
            "summary": "MCU stopped responding; no valid frames received for 2500 ms.",
            "black_box_reason": "mcu_unresponsive",
            "black_box_log_path": "logs/machine_black_box/mcu_unresponsive.json",
            "black_box_log_error": None,
        },
    )

    assert popups[0][0] == "Machine Connection Lost"
    assert "MCU stopped responding" in popups[0][1]
    assert "Black-box log: logs/machine_black_box/mcu_unresponsive.json" in popups[0][1]
    context = controller._last_connection_loss_debug_bundle_context
    assert context["connection_loss_report"]["reason"] == "mcu_unresponsive"
    assert context["black_box_snapshots"][0]["reason"] == "mcu_unresponsive"
    assert context["black_box_snapshots"][0]["path"] == "logs/machine_black_box/mcu_unresponsive.json"


def test_export_last_connection_loss_debug_bundle_packages_current_context(tmp_path):
    snapshot = tmp_path / "serial_reader_stopped.json"
    snapshot.write_text('{"reason": "serial_reader_stopped"}', encoding="utf-8")
    controller = Controller.__new__(Controller)
    controller._last_connection_loss_debug_bundle_context = {
        "bundle_kind": "connection_loss",
        "repo_root": str(tmp_path),
        "connection_loss_report": {
            "summary": "Machine serial connection ended unexpectedly (serial closed).",
            "reason": "serial_closed",
            "port": "COM9",
            "black_box_log_path": str(snapshot),
        },
        "black_box_session_id": "session-abc",
        "black_box_snapshots": [
            {"path": str(snapshot), "reason": "serial_reader_stopped", "session_id": "session-abc"}
        ],
    }

    result = Controller.export_last_connection_loss_debug_bundle(controller, output_dir=tmp_path)

    archive_path = Path(result["archive_path"])
    assert archive_path.exists()
    assert archive_path.parent == tmp_path
    assert result["archive_size_bytes"] > 0
    assert result["manifest"]["bundle_kind"] == "connection_loss"
    assert result["manifest"]["connection_loss"]["reason"] == "serial_closed"


def test_export_last_connection_loss_debug_bundle_requires_context(tmp_path):
    controller = Controller.__new__(Controller)
    controller._last_connection_loss_debug_bundle_context = None

    try:
        Controller.export_last_connection_loss_debug_bundle(controller, output_dir=tmp_path)
    except RuntimeError as exc:
        assert "No machine connection-loss debug context" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
