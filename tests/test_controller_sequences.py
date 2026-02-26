from types import SimpleNamespace

from Controller import Controller


class Emitter:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class FakeTimer:
    def __init__(self):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class QueueStateMachine:
    def __init__(self, values):
        self.values = list(values)
        self.idx = 0

    def __call__(self):
        if self.idx >= len(self.values):
            return self.values[-1]
        value = self.values[self.idx]
        self.idx += 1
        return value


def _make_sequence_controller(now=100.0):
    c = Controller.__new__(Controller)
    c._monotonic_fn = lambda: now
    c._seq_timer = FakeTimer()
    c._seq_state = "idle"
    c._seq_id = None
    c._seq_params = {}
    c._seq_deadline_monotonic = 0.0

    c.sequence_error = Emitter()
    c.sequence_state_changed = Emitter()
    c.sequence_countdown_s = Emitter()
    c.sequence_started = Emitter()
    c.sequence_completed = Emitter()

    c.model = SimpleNamespace(machine_model=SimpleNamespace(is_connected=lambda: True))
    c.update_expected_with_current = lambda: None

    pause_calls = []
    send_calls = []
    c.machine = SimpleNamespace(
        check_if_all_completed=lambda: True,
        set_sequence_pause=lambda paused: pause_calls.append(paused),
        send_next_command=lambda: send_calls.append("send"),
    )
    c._pause_calls = pause_calls
    c._send_calls = send_calls

    return c


def test_sequence_immediate_start_and_complete():
    c = _make_sequence_controller()
    built = []
    c._sequence_builders = {"led_on_wait_off": lambda: built.append("built")}

    Controller.start_preprogrammed_sequence(c, "led_on_wait_off", delay_s=0)

    assert built == ["built"]
    assert c._pause_calls[:2] == [True, True]
    assert c._pause_calls[-1] is False
    assert c._send_calls == ["send"]
    assert c._seq_state == "idle"
    assert c.sequence_started.calls[0][0] == "led_on_wait_off"
    assert c.sequence_completed.calls[0][0] == "led_on_wait_off"


def test_sequence_countdown_tick_transitions_to_begin():
    c = _make_sequence_controller(now=10.0)
    c._sequence_builders = {"x": lambda: None}
    c.machine.check_if_all_completed = QueueStateMachine([True, True])

    Controller.start_preprogrammed_sequence(c, "x", delay_s=5.0)
    assert c._seq_state == "countdown"
    assert c._seq_timer.started is True

    c._monotonic_fn = lambda: 20.0
    Controller._on_seq_tick(c)
    assert c._seq_timer.stopped is True
    assert c._seq_state == "idle"


def test_cancel_countdown_unpauses_and_resets():
    c = _make_sequence_controller()
    c._sequence_builders = {"x": lambda: None}
    Controller.start_preprogrammed_sequence(c, "x", delay_s=3.0)
    assert c._seq_state == "countdown"

    Controller.cancel_preprogrammed_sequence(c)
    assert c._seq_state == "idle"
    assert c._pause_calls[-1] is False
