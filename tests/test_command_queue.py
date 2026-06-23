import time
from unittest.mock import Mock

from types import SimpleNamespace

import Machine_FreeRTOS as mfr


def test_command_queue_transitions_and_completion_signal(qapp):
    queue = mfr.CommandQueue()
    completed_events = []
    queue.commands_completed.connect(lambda: completed_events.append("done"))

    queue.add_command("LED_ON", 0, 0, 0)
    queue.add_command("LED_OFF", 0, 0, 0)

    first = queue.get_next_command()
    assert first.status == "Added"
    assert first.mark_as_sent() is True
    second = queue.get_next_command()
    assert second.status == "Added"
    assert second.mark_as_sent() is True

    queue.update_command_status(
        current_executing_command=2,
        last_completed_command=1,
        last_accepted_command=2,
        last_retired_command=1,
    )
    assert len(queue.queue) == 1
    assert queue.queue[0].status == "Executing"
    assert len(queue.completed) == 1

    queue.update_command_status(
        current_executing_command=2,
        last_completed_command=2,
        last_accepted_command=2,
        last_retired_command=2,
    )
    assert len(queue.queue) == 0
    assert len(queue.completed) == 2
    assert completed_events == ["done"]


def test_command_queue_clear_resets_state(qapp):
    queue = mfr.CommandQueue()
    queue.add_command("LED_ON", 0, 0, 0)
    queue.add_command("LED_OFF", 0, 0, 0)
    _ = queue.get_next_command()
    assert queue.command_number == 2
    assert len(queue.queue) == 2

    queue.clear_queue()
    assert queue.command_number == 0
    assert len(queue.queue) == 0
    assert len(queue.completed) == 0


def test_command_queue_clear_can_preserve_monotonic_counter(qapp):
    queue = mfr.CommandQueue()
    queue.add_command("LED_ON", 0, 0, 0)
    queue.add_command("LED_OFF", 0, 0, 0)

    queue.clear_queue(reset_counter=False)
    assert queue.command_number == 2
    next_command = queue.add_command("WAIT", 1, 0, 0)
    assert next_command.command_number == 3


def test_command_queue_marks_canceled_commands_from_retired_frontier(qapp):
    queue = mfr.CommandQueue()
    first = queue.add_command("LED_ON", 0, 0, 0)
    second = queue.add_command("LED_OFF", 0, 0, 0)
    first.mark_as_sent()
    second.mark_as_sent()

    queue.update_command_status(
        current_executing_command=2,
        last_completed_command=1,
        last_accepted_command=2,
        last_retired_command=2,
    )

    assert len(queue.queue) == 0
    assert [cmd.status for cmd in queue.completed] == ["Completed", "Canceled"]


def test_machine_dispense_commands_use_configured_frequency(qapp, test_profile):
    model = SimpleNamespace(
        machine_model=SimpleNamespace(get_dispense_frequency_hz=lambda: 10)
    )
    machine = mfr.Machine(model, profile=test_profile)

    dispense = machine.print_droplets(7)
    print_only = machine.print_only(5)
    refuel_only = machine.refuel_only(3)

    assert dispense.command_type == "DISPENSE"
    assert dispense.param1 == 7
    assert dispense.param2 == 10
    assert print_only.command_type == "DISPENSE_PRINT"
    assert print_only.param2 == 10
    assert refuel_only.command_type == "DISPENSE_REFUEL"
    assert refuel_only.param2 == 10


def _register_settings_trace(machine, *, request_id="req-1", settings=None):
    settings = dict(settings or {"flash_delay": 6000, "num_droplets": 1})
    created_ns = time.monotonic_ns()
    command_specs = [
        ("flash_delay", "SET_DELAY_F", int(settings["flash_delay"])),
        ("num_droplets", "SET_IMAGE_DROPLETS", int(settings["num_droplets"])),
    ]
    commands = []
    for index, (setting_key, command_type, param1) in enumerate(command_specs):
        command = machine.command_queue.add_command(
            command_type,
            param1,
            0,
            0,
            trace_metadata={
                "request_id": request_id,
                "settings_context": "online_stream_apply_flow_delay",
                "setting_key": setting_key,
                "requested_value": settings[setting_key],
                "setting_index": index,
                "settings_count": len(command_specs),
                "request_created_monotonic_ns": created_ns,
            },
        )
        commands.append(command)
    machine.register_settings_trace_binding(
        {
            "request_id": request_id,
            "context": "online_stream_apply_flow_delay",
            "settings": settings,
            "timeout_ms": 10000,
            "request_created_monotonic_ns": created_ns,
            "commands": [
                {
                    "command_number": command.command_number,
                    "command_type": command.command_type,
                    "setting_key": spec[0],
                    "requested_value": settings[spec[0]],
                }
                for command, spec in zip(commands, command_specs)
            ],
            "completion_command_number": commands[-1].command_number,
        }
    )
    return commands


def test_machine_snapshot_classifies_completion_command_not_sent(qapp, test_profile):
    machine = mfr.Machine(SimpleNamespace(), profile=test_profile)
    commands = _register_settings_trace(machine)

    snapshot = machine.get_settings_trace_snapshot("req-1")

    assert snapshot["stall_hint"] == "completion_command_not_sent"
    assert snapshot["commands"][-1]["command_number"] == commands[-1].command_number
    assert snapshot["commands"][-1]["queued_ms"] is not None
    assert snapshot["commands"][-1]["sent_ms"] is None


def test_machine_records_untraced_command_events(qapp, test_profile):
    machine = mfr.Machine(SimpleNamespace(), profile=test_profile)

    command = machine.command_queue.add_command("LED_ON", 0, 0, 0)

    assert machine.command_event_history[-1]["request_id"] is None
    assert machine.command_event_history[-1]["event"] == "queued"
    assert machine.command_event_history[-1]["command_number"] == command.command_number
    assert any(
        event["kind"] == "command_lifecycle"
        and event["payload"]["command_number"] == command.command_number
        for event in machine.black_box_recorder.recent_events()
    )


def test_settings_trace_snapshot_filters_untraced_command_events(qapp, test_profile):
    machine = mfr.Machine(SimpleNamespace(), profile=test_profile)
    untraced = machine.command_queue.add_command("LED_ON", 0, 0, 0)
    commands = _register_settings_trace(machine)

    snapshot = machine.get_settings_trace_snapshot("req-1")

    assert snapshot["commands"][-1]["command_number"] == commands[-1].command_number
    assert all(
        event["command_number"] != untraced.command_number
        for event in snapshot["recent_command_events"]
    )


def test_machine_snapshot_classifies_completion_command_sent_not_retired(qapp, test_profile):
    machine = mfr.Machine(SimpleNamespace(), profile=test_profile)
    commands = _register_settings_trace(machine)

    for _ in commands:
        command = machine.command_queue.get_next_command()
        assert command is not None
        assert command.mark_as_sent() is True
        machine._record_command_event(command, "sent")

    snapshot = machine.get_settings_trace_snapshot("req-1")

    assert snapshot["stall_hint"] == "completion_command_sent_not_retired"
    assert snapshot["commands"][-1]["sent_ms"] is not None
    assert snapshot["commands"][-1]["completed_ms"] is None


def test_machine_snapshot_classifies_state_matches_settings_but_completion_missing(qapp, test_profile):
    machine = mfr.Machine(SimpleNamespace(), profile=test_profile)
    commands = _register_settings_trace(machine)

    for _ in commands:
        command = machine.command_queue.get_next_command()
        assert command is not None
        assert command.mark_as_sent() is True
        machine._record_command_event(command, "sent")

    host_rx_ns = time.monotonic_ns()
    machine.update_status(
        {
            "__host_rx_monotonic_ns": host_rx_ns,
            "Current_command": commands[-1].command_number,
            "Last_completed": commands[0].command_number,
            "cmd_depth": 1,
            "Flash_delay": 6000,
            "Flash_droplets": 1,
        }
    )

    snapshot = machine.get_settings_trace_snapshot("req-1")

    assert snapshot["stall_hint"] == "state_matches_settings_but_completion_missing"
    assert snapshot["latest_status"]["Flash_delay"] == 6000
    assert snapshot["latest_status"]["Flash_droplets"] == 1
    assert snapshot["latest_status"]["rx_to_main_thread_ms"] is not None
    assert snapshot["recent_status"]


def test_machine_snapshot_classifies_late_completion_after_timeout(qapp, test_profile):
    machine = mfr.Machine(SimpleNamespace(), profile=test_profile)
    commands = _register_settings_trace(machine)

    for _ in commands:
        command = machine.command_queue.get_next_command()
        assert command is not None
        assert command.mark_as_sent() is True
        machine._record_command_event(command, "sent")

    timed_out_ns = time.monotonic_ns() - 1_000_000
    machine.command_queue.update_command_status(
        current_executing_command=commands[-1].command_number,
        last_completed_command=commands[-1].command_number,
    )

    snapshot = machine.get_settings_trace_snapshot("req-1", timed_out_monotonic_ns=timed_out_ns)

    assert snapshot["stall_hint"] == "late_completion_after_timeout"
    assert snapshot["commands"][-1]["completed_ms"] is not None
    assert any(event["event"] == "completed" for event in snapshot["recent_command_events"])


def test_request_pause_after_seq32_write_failure_invokes_failure_callback(qapp, test_profile):
    machine = mfr.Machine(SimpleNamespace(), profile=test_profile)
    machine._write_frame = Mock(side_effect=IOError("port closed"))
    failures = []
    errors = []
    machine.error_occurred.connect(errors.append)

    ok = machine.request_pause_after_seq32(42, on_failure=failures.append)

    assert ok is False
    assert failures == [
        {
            "reason": "write_failed",
            "barrier_seq32": 42,
            "ack_result": None,
            "error": "port closed",
        }
    ]
    assert errors == []


def test_request_pause_after_seq32_ack_rejection_invokes_failure_callback(qapp, test_profile):
    machine = mfr.Machine(SimpleNamespace(), profile=test_profile)
    machine._write_frame = Mock()
    failures = []
    errors = []
    machine.error_occurred.connect(errors.append)

    ok = machine.request_pause_after_seq32(42, on_failure=failures.append)
    seq32 = next(iter(machine._pending_pause_after_requests))
    machine._on_any_ack({"ack_cmd": mfr.CMD_QUEUE_ACK, "seq32": seq32, "seq8": 0, "ack_result": "watermark_rejected"})

    assert ok is True
    assert failures == [
        {
            "reason": "ack_rejected",
            "barrier_seq32": 42,
            "ack_result": "watermark_rejected",
            "error": None,
        }
    ]
    assert errors == []


def test_request_pause_after_seq32_status_confirmation_survives_initial_ack_timeout(qapp, test_profile):
    machine = mfr.Machine(SimpleNamespace(), profile=test_profile)
    machine._write_frame = Mock()
    successes = []
    failures = []
    ok = machine.request_pause_after_seq32(42, on_success=successes.append, on_failure=failures.append)
    seq32 = next(iter(machine._pending_pause_after_requests))
    request = machine._pending_pause_after_requests[seq32]

    machine._on_pause_after_ack_timeout(seq32)
    machine._update_pause_after_requests_from_status(
        {
            "monotonic_ns": int(request["created_monotonic_ns"]) + 1,
            "Pause_after_seq32": 42,
            "Pause_watermark_reached": False,
            "Transport_paused": False,
        }
    )
    machine._on_pause_after_confirm_timeout(seq32)

    assert ok is True
    assert failures == []
    assert successes
    assert successes[0]["ack_result"] == "status_confirmed"
    assert seq32 not in machine._pending_pause_after_requests


def test_request_pause_after_seq32_not_confirmed_within_grace_window_invokes_failure_callback(qapp, test_profile):
    machine = mfr.Machine(SimpleNamespace(), profile=test_profile)
    machine._write_frame = Mock()
    failures = []

    ok = machine.request_pause_after_seq32(42, on_failure=failures.append)
    seq32 = next(iter(machine._pending_pause_after_requests))

    machine._on_pause_after_ack_timeout(seq32)
    machine._on_pause_after_confirm_timeout(seq32)

    assert ok is True
    assert failures == [
        {
            "reason": "not_confirmed",
            "barrier_seq32": 42,
            "ack_result": None,
            "error": None,
        }
    ]


def test_request_pause_after_seq32_success_still_invokes_success_callback(qapp, test_profile):
    machine = mfr.Machine(SimpleNamespace(), profile=test_profile)
    machine._write_frame = Mock()
    successes = []
    failures = []

    ok = machine.request_pause_after_seq32(42, on_success=successes.append, on_failure=failures.append)
    seq32 = next(iter(machine._pending_pause_after_requests))
    machine._on_any_ack({"ack_cmd": mfr.CMD_QUEUE_ACK, "seq32": seq32, "seq8": 0, "ack_result": "watermark_set"})

    assert ok is True
    assert successes
    assert successes[0]["ack_result"] == "watermark_set"
    assert failures == []


def test_queue_gap_below_local_queue_faults_instead_of_resending(qapp, test_profile):
    machine = mfr.Machine(SimpleNamespace(), profile=test_profile)
    errors = []
    machine.error_occurred.connect(errors.append)
    machine._transport_ready = True
    machine._write_frame = Mock()
    machine.command_queue.command_number = 9
    command = machine.wait_ms(10)
    sent_before_gap = machine._write_frame.call_count
    command.send_attempts = 1
    command.mark_as_sent()

    machine._on_queue_ack(
        command.command_number,
        {
            "ack_result": "gap",
            "expected_seq32": 5,
        },
    )

    assert machine._tx_paused is True
    assert errors
    assert "earliest local queued command is 10" in errors[-1]
    assert machine._write_frame.call_count == sent_before_gap


def test_queue_busy_resends_are_bounded(qapp, test_profile):
    machine = mfr.Machine(SimpleNamespace(), profile=test_profile)
    errors = []
    machine.error_occurred.connect(errors.append)
    command = machine.wait_ms(10)
    command.send_attempts = machine._queue_ack_max_retries
    command.mark_as_sent()

    machine._on_queue_ack(command.command_number, {"ack_result": "busy"})

    assert machine._tx_paused is True
    assert errors
    assert "remained busy" in errors[-1]


class _OpenSerial:
    is_open = True


def test_queue_ack_timeout_retries_before_transport_loss(qapp, test_profile):
    machine = mfr.Machine(SimpleNamespace(), profile=test_profile)
    lost_reports = []
    machine.serial_connection_lost.connect(lost_reports.append)
    machine.pump_send_queue = Mock()
    command = machine.wait_ms(10)
    command.send_attempts = machine._queue_ack_max_retries - 1
    command.mark_as_sent()

    machine._on_queue_ack_timeout(command.command_number)

    assert lost_reports == []
    assert command.status == "Added"
    machine.pump_send_queue.assert_called_once()


def test_queue_ack_timeout_at_retry_limit_marks_mcu_unresponsive(qapp, test_profile, tmp_path):
    machine = mfr.Machine(SimpleNamespace(), profile=test_profile, black_box_log_dir=tmp_path)
    lost_reports = []
    connected_states = []
    machine.serial_connection_lost.connect(lost_reports.append)
    machine.machine_connected_signal.connect(connected_states.append)
    machine.ser = _OpenSerial()
    machine.port = "COM9"
    command = machine.wait_ms(10)
    machine._transport_ready = True
    machine._tx_paused = False
    command.send_attempts = machine._queue_ack_max_retries
    command.mark_as_sent()

    machine._on_queue_ack_timeout(command.command_number)

    assert connected_states == [False]
    assert len(lost_reports) == 1
    assert lost_reports[0]["reason"] == "mcu_unresponsive"
    assert lost_reports[0]["trigger_reason"] == "ack_timeout"
    assert "command ACK" in lost_reports[0]["summary"]
    assert machine._transport_ready is False
    assert machine._tx_paused is True
    assert len(machine.command_queue.queue) == 0


def test_command_queue_rejects_commands_after_untrusted_transport(qapp, test_profile):
    machine = mfr.Machine(SimpleNamespace(), profile=test_profile)
    errors = []
    machine.error_occurred.connect(errors.append)
    machine._transport_ready = False
    machine._command_queue_blocked_reason = "mcu_unresponsive"

    result = machine.add_command_to_queue("DISABLE_MOTORS", 0, 0, 0)

    assert result is False
    assert len(machine.command_queue.queue) == 0
    assert errors
    assert "machine connection is not trusted" in errors[-1]
