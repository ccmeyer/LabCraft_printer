import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import Machine_FreeRTOS as mfr
from Controller import Controller


def _terminal_fault_status(*, paused=True, watermark=False, depth=0, command_type="ABSOLUTE_XY"):
    return {
        "Transport_paused": paused,
        "Pause_watermark_reached": watermark,
        "cmd_depth": depth,
        "Current_command": 42,
        "Last_completed": 40,
        "Last_accepted": 42,
        "Last_retired": 42,
        "_command_type": command_type,
    }


def _machine_with_xy_window(test_profile, tmp_path, *, first_type="ABSOLUTE_XY"):
    machine = mfr.Machine(
        SimpleNamespace(),
        profile=test_profile,
        black_box_log_dir=tmp_path,
    )
    machine._transport_ready = True
    machine._tx_paused = False
    machine._write_frame = Mock()
    machine.command_queue.command_number = 40
    callbacks = []

    first = machine.command_queue.add_command(
        first_type, 100, 200, 300, handler=lambda: callbacks.append("first")
    )
    accepted_tail = machine.command_queue.add_command(
        "WAIT", 10, 0, 0, handler=lambda: callbacks.append("accepted_tail")
    )
    unsent_tail = machine.command_queue.add_command(
        "LED_ON", 0, 0, 0, handler=lambda: callbacks.append("unsent_tail")
    )
    first.mark_as_accepted()
    first.mark_as_executing()
    accepted_tail.mark_as_accepted()
    return machine, (first, accepted_tail, unsent_tail), callbacks


def _connect_status_reconciliation(machine, events):
    def reconcile(data):
        events.append("status")
        machine.update_command_numbers(
            data.get("Current_command"),
            data.get("Last_completed"),
            data.get("Last_accepted"),
            data.get("Last_retired"),
        )

    machine.status_updated.connect(reconcile)


def test_xy_fault_terminalizes_accepted_and_unsent_work_before_one_drain(
    qapp, test_profile, tmp_path
):
    machine, commands, callbacks = _machine_with_xy_window(test_profile, tmp_path)
    events = []
    reports = []
    machine.xy_motion_faulted.connect(
        lambda report: (events.append("fault"), reports.append(dict(report)))
    )
    _connect_status_reconciliation(machine, events)
    machine.command_queue.commands_completed.connect(lambda: events.append("drained"))

    status = _terminal_fault_status()
    machine.update_status(status)
    machine.update_status(status)

    assert events == ["fault", "status", "drained", "status"]
    assert len(reports) == 1
    assert reports[0]["failed_command_number"] == 41
    assert reports[0]["requires_reset"] is False
    assert machine.get_xy_motion_recovery_state() == "clear_required"
    assert machine._tx_paused is True
    assert len(machine.command_queue.queue) == 0
    assert [command.status for command in commands] == ["Canceled", "Canceled", "Canceled"]
    assert callbacks == []


@pytest.mark.parametrize(
    "overrides,first_type",
    [
        ({"Transport_paused": False}, "ABSOLUTE_XY"),
        ({"Pause_watermark_reached": True}, "ABSOLUTE_XY"),
        ({"cmd_depth": 1}, "ABSOLUTE_XY"),
        ({"Last_retired": 40, "Last_accepted": 40, "Current_command": 40}, "ABSOLUTE_XY"),
        ({}, "WAIT"),
    ],
)
def test_xy_fault_detector_excludes_nonterminal_and_control_pause_shapes(
    qapp, test_profile, tmp_path, overrides, first_type
):
    machine, _commands, _callbacks = _machine_with_xy_window(
        test_profile, tmp_path, first_type=first_type
    )
    reports = []
    machine.xy_motion_faulted.connect(reports.append)
    status = _terminal_fault_status()
    status.update(overrides)

    machine.update_status(status)

    assert reports == []
    assert machine.get_xy_motion_recovery_state() == "idle"


def test_first_status_after_hello_detects_retained_xy_latch(qapp, test_profile, tmp_path):
    machine = mfr.Machine(
        SimpleNamespace(), profile=test_profile, black_box_log_dir=tmp_path
    )
    reports = []
    machine.xy_motion_faulted.connect(reports.append)
    machine._transport_ready = True
    machine._tx_paused = True
    machine._awaiting_first_status_after_hello = True

    machine.update_status(
        {
            "Transport_paused": True,
            "Pause_watermark_reached": False,
            "cmd_depth": 0,
            "Current_command": 0,
            "Last_completed": 0,
            "Last_accepted": 0,
            "Last_retired": 0,
        }
    )

    assert len(reports) == 1
    assert reports[0]["source"] == "post_hello_latched_status"
    assert reports[0]["failed_command_number"] is None
    assert machine.get_xy_motion_recovery_state() == "clear_required"
    assert machine._tx_paused is True


def test_xy_clear_requires_unpaused_status_and_timeout_stays_blocked(
    qapp, test_profile, fake_serial_main, tmp_path
):
    machine, _commands, _callbacks = _machine_with_xy_window(test_profile, tmp_path)
    machine.ser = fake_serial_main
    machine.update_status(_terminal_fault_status())
    results = []

    assert machine.clear_command_queue(handler=results.append) is True
    machine._on_clear_ack(timed_out=False)
    assert machine.get_xy_motion_recovery_state() == "clear_pending"

    machine.update_status(_terminal_fault_status())
    assert machine.get_xy_motion_recovery_state() == "clear_pending"
    assert results == []

    machine._wait_for_clear_status_deadline = time.time() - 1
    machine.update_status(_terminal_fault_status())

    assert machine.get_xy_motion_recovery_state() == "clear_required"
    assert machine._tx_paused is True
    assert results == [
        {
            "ack_received": True,
            "ack_timed_out": False,
            "status_confirmed": False,
            "status_timed_out": True,
        }
    ]
    machine._cancel_pending_acks()
    machine.stop_execution_timer()


def test_confirmed_clear_allows_only_atomic_full_home_then_restores_commands(
    qapp, test_profile, fake_serial_main, tmp_path
):
    machine, _commands, _callbacks = _machine_with_xy_window(test_profile, tmp_path)
    machine.ser = fake_serial_main
    machine.update_status(_terminal_fault_status())
    machine.clear_command_queue()
    machine._on_clear_ack(timed_out=False)
    machine.update_status(
        {
            "Transport_paused": False,
            "Pause_watermark_reached": False,
            "cmd_depth": 0,
            "Current_command": 42,
            "Last_completed": 40,
            "Last_accepted": 42,
            "Last_retired": 42,
        }
    )

    assert machine.get_xy_motion_recovery_state() == "home_required"
    assert machine.wait_ms(10) is False
    assert machine.home_regulators() is False

    assert machine.home_motors() is True
    commands = list(machine.command_queue.queue)
    assert [command.command_type for command in commands] == [
        "HOME_Z",
        "HOME_XY",
        "HOME_PR_BOTH",
    ]
    assert machine.get_xy_motion_recovery_state() == "home_in_progress"
    assert all(command.command_number in machine._xy_rehome_command_numbers for command in commands)

    final_seq32 = commands[-1].command_number
    machine.update_command_numbers(
        final_seq32,
        final_seq32,
        final_seq32,
        final_seq32,
    )

    assert machine.get_xy_motion_recovery_state() == "idle"
    assert machine.homed is True
    assert machine._command_queue_blocked_reason is None
    machine._transport_ready = False
    assert machine.wait_ms(10) is not False
    machine._cancel_pending_acks()
    machine.stop_execution_timer()


def test_controller_xy_fault_invalidates_home_and_aborts_before_workflow_notice():
    events = []
    popups = []
    machine_model = SimpleNamespace(
        reset_home_status=Mock(side_effect=lambda: events.append("home_reset")),
        home_status_signal=SimpleNamespace(emit=lambda: events.append("home_signal")),
        get_current_position_dict=lambda: {"X": 12, "Y": 34, "Z": 56},
    )
    controller = Controller.__new__(Controller)
    controller._seq_state = "running"
    controller._abort_sequence = Mock(side_effect=lambda _msg: events.append("sequence_aborted"))
    controller._stream_capture_manager = Mock(return_value=None)
    controller._interrupt_array_after_transport_fault = Mock(
        side_effect=lambda *_args, **_kwargs: events.append("array_interrupted")
    )
    controller._emit_machine_workflow_interrupted = Mock(
        side_effect=lambda *_args, **_kwargs: events.append("workflow_interrupted")
    )
    controller.model = SimpleNamespace(machine_model=machine_model)
    controller.expected_position = {"X": 0, "Y": 0, "Z": 0}
    controller.expected_location = "camera"
    controller.error_occurred_signal = SimpleNamespace(
        emit=lambda title, message: popups.append((title, message))
    )

    Controller.handle_xy_motion_fault(
        controller,
        {
            "summary": "XY stopped.",
            "failed_command_number": 77,
            "black_box_log_path": "logs/machine_black_box/xy.json",
        },
    )

    assert events == [
        "sequence_aborted",
        "home_reset",
        "home_signal",
        "array_interrupted",
        "workflow_interrupted",
    ]
    assert controller.expected_position == {"X": 12, "Y": 34, "Z": 56}
    assert controller.expected_location is None
    assert popups[0][0] == "XY Motion Stopped"
    assert "did not reset" in popups[0][1]
    assert "Clear Queue" in popups[0][1]
