import threading

import numpy as np
import pytest

from Machine_FreeRTOS import DropletCamera


class _Signal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args, **kwargs):
        for callback in list(self._callbacks):
            callback(*args, **kwargs)


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


def _make_async_camera():
    camera = DropletCamera.__new__(DropletCamera)
    camera.camera = object()
    camera._cv = threading.Condition(threading.Lock())
    camera._cap_done = threading.Event()
    camera._cap_result = None
    camera._cap_active = False
    camera._cap_id = 7
    camera._cap_request_id = None
    camera._capture_worker_active = threading.Event()
    camera._capture_worker_thread = None
    camera._capture_generation = 0
    camera.latest_frame = np.full((3, 4, 3), 88, dtype=np.uint8)
    camera.capture_completed_signal = _Signal()
    camera.image_captured_signal = _Signal()
    camera.capture_failed_signal = _Signal()
    camera._trigger_low = lambda: None
    camera.stop_camera = lambda: setattr(camera, "camera", None)
    camera.start_camera = lambda: setattr(camera, "camera", object())
    return camera


def test_capture_worker_clears_active_before_completion_emit():
    camera = _make_async_camera()
    completion_seen = threading.Event()
    active_states = []

    def _fake_sync(**kwargs):
        return {
            "status": "success",
            "request_id": kwargs.get("request_id"),
            "generation": kwargs.get("generation"),
            "cap_id": 9,
            "frame": camera.latest_frame,
            "capture_info": {"cap_id": 9, "reason": "threshold"},
            "reason": "threshold",
        }

    camera.capture_with_retry_sync = _fake_sync
    camera.capture_completed_signal.connect(
        lambda _payload: active_states.append(camera._capture_worker_active.is_set()) or completion_seen.set()
    )

    assert DropletCamera.capture_with_retry_async(camera, request_id="req-1") is True
    assert completion_seen.wait(1.0)
    assert active_states == [False]


def test_capture_worker_emits_exactly_one_failure_result_after_retry_failure():
    camera = _make_async_camera()
    completion_seen = threading.Event()
    payloads = []
    failures = []

    def _fake_sync(**_kwargs):
        with camera._cv:
            camera._cap_result = {"reason": "edge_timeout", "cap_id": 12}
        raise RuntimeError("retry budget exhausted")

    camera.capture_with_retry_sync = _fake_sync
    camera.capture_completed_signal.connect(lambda payload: payloads.append(dict(payload)) or completion_seen.set())
    camera.capture_failed_signal.connect(lambda msg: failures.append(str(msg)))

    assert DropletCamera.capture_with_retry_async(camera, request_id="req-fail") is True
    assert completion_seen.wait(1.0)

    assert len(payloads) == 1
    assert payloads[0]["status"] == "failed"
    assert payloads[0]["request_id"] == "req-fail"
    assert failures == ["retry budget exhausted"]
    assert camera._capture_worker_active.is_set() is False


def test_recover_stale_capture_releases_trigger_done_and_worker_active():
    camera = _make_async_camera()
    camera._capture_worker_active.set()
    camera._cap_active = True
    camera._cap_done.clear()
    trigger_events = []
    camera._trigger_low = lambda: trigger_events.append("low")
    camera.camera = None

    result = DropletCamera.recover_stale_capture(camera, reason="unit timeout")

    assert result["ok"] is True
    assert trigger_events == ["low"]
    assert camera._cap_active is False
    assert camera._cap_done.is_set() is True
    assert camera._capture_worker_active.is_set() is False


def test_stale_worker_generation_cannot_complete_newer_request():
    camera = _make_async_camera()
    sync_entered = threading.Event()
    release_sync = threading.Event()
    completion_seen = threading.Event()
    payloads = []

    def _fake_sync(**kwargs):
        sync_entered.set()
        release_sync.wait(1.0)
        return {
            "status": "success",
            "request_id": kwargs.get("request_id"),
            "generation": kwargs.get("generation"),
            "cap_id": 22,
            "frame": camera.latest_frame,
            "capture_info": {"cap_id": 22, "reason": "threshold"},
            "reason": "threshold",
        }

    camera.capture_with_retry_sync = _fake_sync
    camera.capture_completed_signal.connect(lambda payload: payloads.append(dict(payload)) or completion_seen.set())

    assert DropletCamera.capture_with_retry_async(camera, request_id="old-request") is True
    assert sync_entered.wait(1.0)

    recovery = DropletCamera.recover_stale_capture(camera, reason="controller timeout")
    assert recovery["ok"] is True

    release_sync.set()
    assert completion_seen.wait(1.0)
    assert payloads[0]["status"] == "stale"
    assert payloads[0]["stale"] is True
    assert payloads[0]["request_id"] == "old-request"
