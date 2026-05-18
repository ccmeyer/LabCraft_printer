import threading

import pytest

from Machine_FreeRTOS import DropletCamera


class _EdgeRaisesOnConsume:
    def __init__(self):
        self.wait_calls = []

    def event_wait(self, timeout):
        self.wait_calls.append(timeout)
        return len(self.wait_calls) > 1

    def event_consume(self):
        raise RuntimeError("consume failed")


def test_capture_non_blocking_drops_trigger_when_edge_consume_raises():
    camera = DropletCamera.__new__(DropletCamera)
    camera.camera = object()
    camera._cv = threading.Condition(threading.Lock())
    camera._cap_done = threading.Event()
    camera._cap_result = None
    camera._cap_active = False
    camera._cap_id = 7
    camera._edge_in = _EdgeRaisesOnConsume()
    trigger_events = []
    camera._trigger_high = lambda: trigger_events.append("high")
    camera._trigger_low = lambda: trigger_events.append("low")

    with pytest.raises(RuntimeError, match="consume failed"):
        DropletCamera.capture_non_blocking(camera, timeout_s=0.01)

    assert trigger_events == ["high", "low"]
