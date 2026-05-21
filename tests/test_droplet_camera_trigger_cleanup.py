import threading
import time

import numpy as np
import pytest

from Machine_FreeRTOS import DropletCamera, StaleCaptureBackend


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

    def release(self):
        pass


class _EdgeAlwaysReady:
    def __init__(self):
        self.consume_count = 0

    def event_wait(self, _timeout):
        return True

    def event_consume(self):
        self.consume_count += 1

    def release(self):
        pass


class _EdgeNoStaleThenFired:
    def __init__(self):
        self.wait_calls = []
        self.consume_count = 0

    def event_wait(self, timeout):
        self.wait_calls.append(timeout)
        return len(self.wait_calls) > 1

    def event_consume(self):
        self.consume_count += 1

    def release(self):
        pass


class _TriggerLine:
    def __init__(self):
        self.values = []
        self.release_count = 0

    def set_value(self, value):
        self.values.append(int(value))

    def release(self):
        self.release_count += 1


class _FakeBackend:
    def __init__(self, backend_id, edge=None):
        self.backend_id = str(backend_id)
        self.trigger_line = _TriggerLine()
        self.edge_line = edge if edge is not None else _EdgeNoStaleThenFired()
        self.release_count = 0
        self.released = False

    @property
    def is_open(self):
        return not self.released

    def _raise_if_released(self, action):
        if self.released:
            raise StaleCaptureBackend(f"backend {self.backend_id} released during {action}")

    def trigger_high(self):
        self._raise_if_released("trigger_high")
        self.trigger_line.set_value(1)

    def trigger_low(self):
        self._raise_if_released("trigger_low")
        self.trigger_line.set_value(0)

    def event_wait(self, timeout):
        self._raise_if_released("event_wait")
        return self.edge_line.event_wait(timeout)

    def event_consume(self):
        self._raise_if_released("event_consume")
        return self.edge_line.event_consume()

    def release(self):
        if self.released:
            return False
        self.released = True
        self.release_count += 1
        try:
            self.trigger_line.set_value(0)
        except Exception:
            pass
        release = getattr(self.edge_line, "release", None)
        if callable(release):
            release()
        self.trigger_line.release()
        return True


def _install_backend(camera, backend=None):
    backend = backend or _FakeBackend("1")
    camera._backend_lock = threading.Lock()
    camera._capture_backend = backend
    camera._capture_backend_seq = int(backend.backend_id) if str(backend.backend_id).isdigit() else 1
    camera._trig_line = backend.trigger_line
    camera._edge_in = backend.edge_line
    return backend


def _install_fake_backend_factory(camera):
    created = []

    def _make_capture_backend(*, reason=""):
        next_id = int(getattr(camera, "_capture_backend_seq", 0)) + 1
        camera._capture_backend_seq = next_id
        backend = _FakeBackend(str(next_id))
        created.append((backend, reason))
        return backend

    camera._make_capture_backend = _make_capture_backend
    return created


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


def test_capture_non_blocking_bounds_stale_edge_drain_and_releases_latches():
    camera = DropletCamera.__new__(DropletCamera)
    camera.camera = object()
    camera._cv = threading.Condition(threading.Lock())
    camera._cap_done = threading.Event()
    camera._cap_result = None
    camera._cap_active = True
    camera._cap_id = 7
    camera._cap_request_id = None
    camera._edge_in = _EdgeAlwaysReady()
    camera.prearm_drain_max_edges = 3
    camera.prearm_drain_timeout_s = 10.0
    phases = []
    trigger_events = []
    camera._log_capture_phase = lambda phase, **_kwargs: phases.append(str(phase))
    camera._trigger_high = lambda: trigger_events.append("high")
    camera._trigger_low = lambda: trigger_events.append("low")

    DropletCamera.capture_non_blocking(camera, timeout_s=0.01, request_id="req-drain", generation=4)

    assert camera._edge_in.consume_count == 3
    assert trigger_events == ["low"]
    assert camera._cap_active is False
    assert camera._cap_done.is_set() is True
    assert camera._cap_result["reason"] == "edge_drain_stuck"
    assert camera._cap_result["request_id"] == "req-drain"
    assert phases == ["drain_start", "drain_stuck"]


def test_capture_non_blocking_logs_prearm_phases_before_arm():
    camera = DropletCamera.__new__(DropletCamera)
    camera.camera = object()
    camera._cv = threading.Condition(threading.Lock())
    camera._cap_done = threading.Event()
    camera._cap_result = None
    camera._cap_active = False
    camera._cap_id = 7
    camera._cap_request_id = None
    camera._edge_in = _EdgeNoStaleThenFired()
    camera._buf = [(np.zeros((2, 2, 3), dtype=np.uint8), {}, time.monotonic_ns() - 1_000_000, 1.0)]
    camera.k_sigma = 4.0
    camera.min_delta = 25.0
    camera._cap_emit_rotate = False
    phases = []
    trigger_events = []
    camera._log_capture_phase = lambda phase, **_kwargs: phases.append(str(phase))
    camera._trigger_high = lambda: trigger_events.append("high")
    camera._trigger_low = lambda: trigger_events.append("low")

    DropletCamera.capture_non_blocking(camera, timeout_s=0.01, request_id="req-arm", generation=5)

    assert phases == [
        "drain_start",
        "drain_done",
        "trigger_high",
        "edge_wait_start",
        "edge_wait_done",
        "edge_consume_done",
        "arm_start",
    ]
    assert trigger_events == ["high", "low"]
    assert camera._cap_active is True
    assert camera._cap_done.is_set() is False
    assert camera._cap_id == 8


def _make_async_camera():
    camera = DropletCamera.__new__(DropletCamera)
    camera.camera = object()
    camera._grab_running = True
    camera._grab_thread = None
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
    camera.capture_phase_signal = _Signal()
    _install_backend(camera, _FakeBackend("1"))
    _install_fake_backend_factory(camera)
    camera._trigger_low = lambda: None
    def _stop_camera():
        camera._grab_running = False
        camera.camera = None
    def _start_camera():
        camera.camera = object()
        camera._grab_running = True
    camera.stop_camera = _stop_camera
    camera.start_camera = _start_camera
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
    old_backend = camera._capture_backend
    camera.camera = None

    result = DropletCamera.recover_stale_capture(camera, reason="unit timeout")

    assert result["ok"] is True
    assert result["ready_for_retry"] is False
    assert old_backend.release_count == 1
    assert old_backend.trigger_line.values[:1] == [0]
    assert camera._cap_active is False
    assert camera._cap_done.is_set() is True
    assert camera._capture_worker_active.is_set() is False


def test_recover_stale_capture_with_alive_worker_restarts_camera_and_allows_retry():
    camera = _make_async_camera()
    release_worker = threading.Event()
    worker = threading.Thread(target=lambda: release_worker.wait(1.0), daemon=True)
    worker.start()
    camera._capture_worker_thread = worker
    camera._capture_worker_active.set()
    camera._cap_active = True
    camera._cap_done.clear()
    old_backend = camera._capture_backend
    restart_events = []
    camera.stop_camera = lambda: restart_events.append("stop")
    camera.start_camera = lambda: restart_events.append("start")

    result = DropletCamera.recover_stale_capture(camera, reason="unit timeout")
    release_worker.set()
    worker.join(timeout=1.0)

    assert result["ok"] is True
    assert result["ready_for_retry"] is True
    assert result["worker_alive_after_join"] is True
    assert result["camera_restarted"] is True
    assert result["backend_reopened"] is True
    assert restart_events == ["stop", "start"]
    assert old_backend.release_count == 1
    assert camera._capture_backend is not old_backend


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


def test_recover_stale_capture_replaces_backend_and_releases_old_once():
    camera = _make_async_camera()
    old_backend = camera._capture_backend

    result = DropletCamera.recover_stale_capture(camera, reason="unit timeout")

    assert result["ok"] is True
    assert result["backend_reopened"] is True
    assert result["ready_for_retry"] is True
    assert old_backend.release_count == 1
    assert old_backend.released is True
    assert camera._capture_backend is not old_backend
    assert camera._capture_backend.is_open is True

    second = DropletCamera.recover_stale_capture(camera, reason="second timeout")

    assert second["ok"] is True
    assert old_backend.release_count == 1


def test_stale_worker_old_backend_cannot_drive_new_trigger_line_after_recovery():
    camera = _make_async_camera()
    old_backend = camera._capture_backend

    recovery = DropletCamera.recover_stale_capture(camera, reason="controller timeout")
    new_backend = camera._capture_backend

    assert recovery["ready_for_retry"] is True
    assert new_backend is not old_backend
    with pytest.raises(StaleCaptureBackend):
        old_backend.trigger_high()
    assert new_backend.trigger_line.values == []


def test_async_worker_reports_stale_when_backend_was_replaced():
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
            "backend_id": kwargs.get("backend_id"),
            "cap_id": 33,
            "frame": camera.latest_frame,
            "capture_info": {"cap_id": 33, "reason": "threshold"},
            "reason": "threshold",
        }

    camera.capture_with_retry_sync = _fake_sync
    camera.capture_completed_signal.connect(lambda payload: payloads.append(dict(payload)) or completion_seen.set())

    assert DropletCamera.capture_with_retry_async(camera, request_id="backend-old") is True
    assert sync_entered.wait(1.0)

    DropletCamera.recover_stale_capture(camera, reason="backend replaced")
    release_sync.set()

    assert completion_seen.wait(1.0)
    assert payloads[0]["status"] == "stale"
    assert payloads[0]["stale"] is True
    assert payloads[0]["stale_reason"] in {"worker_backend_superseded", "worker_generation_superseded"}


def test_capture_worker_reports_stale_backend_and_clears_active():
    camera = _make_async_camera()
    completion_seen = threading.Event()
    payloads = []

    def _fake_sync(**_kwargs):
        raise StaleCaptureBackend("backend released during event_wait")

    camera.capture_with_retry_sync = _fake_sync
    camera.capture_completed_signal.connect(lambda payload: payloads.append(dict(payload)) or completion_seen.set())

    assert DropletCamera.capture_with_retry_async(camera, request_id="req-stale") is True
    assert completion_seen.wait(1.0)

    assert payloads[0]["status"] == "stale"
    assert payloads[0]["reason"] == "stale_backend"
    assert camera._capture_worker_active.is_set() is False


def test_recover_stale_capture_backend_reopen_failure_is_not_retry_ready():
    camera = _make_async_camera()

    def _fail_backend(*, reason=""):
        raise RuntimeError("gpio reopen failed")

    camera._make_capture_backend = _fail_backend

    result = DropletCamera.recover_stale_capture(camera, reason="unit timeout")

    assert result["ok"] is False
    assert result["ready_for_retry"] is False
    assert result["backend_reopened"] is False
    assert "gpio reopen failed" in result["backend_error"]
