import time
from types import SimpleNamespace

import Machine_FreeRTOS as mfr


def test_command_queue_transitions_and_completion_signal(qapp):
    queue = mfr.CommandQueue()
    completed_events = []
    queue.commands_completed.connect(lambda: completed_events.append("done"))

    queue.add_command("LED_ON", 0, 0, 0)
    queue.add_command("LED_OFF", 0, 0, 0)

    first = queue.get_next_command()
    second = queue.get_next_command()
    assert first.status == "Sent"
    assert second.status == "Sent"

    queue.update_command_status(current_executing_command=2, last_completed_command=1)
    assert len(queue.queue) == 1
    assert queue.queue[0].status == "Executing"
    assert len(queue.completed) == 1

    queue.update_command_status(current_executing_command=2, last_completed_command=2)
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
