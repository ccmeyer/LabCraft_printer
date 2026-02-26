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
