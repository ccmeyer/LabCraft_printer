from types import SimpleNamespace

from Machine_FreeRTOS import Machine


def test_on_goodbye_done_does_not_block_with_sleep(qapp, test_profile, monkeypatch):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    called = {"disconnect": 0, "reset": 0}

    def _no_sleep(_seconds):
        raise AssertionError("time.sleep should not be called in _on_goodbye_done")

    monkeypatch.setattr("Machine_FreeRTOS.time.sleep", _no_sleep)

    machine.ser = SimpleNamespace(
        reset_input_buffer=lambda: called.__setitem__("reset", called["reset"] + 1)
    )
    machine.disconnect_handler = lambda: called.__setitem__("disconnect", called["disconnect"] + 1)

    machine._on_goodbye_done()

    assert called["reset"] == 1
    assert called["disconnect"] == 1


def test_on_goodbye_done_still_disconnects_when_buffer_reset_fails(qapp, test_profile):
    machine = Machine(SimpleNamespace(), profile=test_profile)
    called = {"disconnect": 0}

    def _boom():
        raise RuntimeError("buffer reset failed")

    machine.ser = SimpleNamespace(reset_input_buffer=_boom)
    machine.disconnect_handler = lambda: called.__setitem__("disconnect", called["disconnect"] + 1)

    machine._on_goodbye_done()

    assert called["disconnect"] == 1
