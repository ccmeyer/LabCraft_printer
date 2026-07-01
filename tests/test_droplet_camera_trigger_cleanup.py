import sys
import threading
import time
import types

import numpy as np
import pytest

import Machine_FreeRTOS as machine_mod
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


class _EdgeNeverReady:
    def __init__(self):
        self.wait_calls = []
        self.consume_count = 0
        self.release_count = 0

    def event_wait(self, timeout):
        self.wait_calls.append(timeout)
        return False

    def event_consume(self):
        self.consume_count += 1

    def release(self):
        self.release_count += 1


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


class _FakeGpiodLine:
    def __init__(self, *, event_fd=None, has_event_fd=True):
        self.event_fd = event_fd
        self.has_event_fd = has_event_fd
        self.request_calls = []
        self.event_read_count = 0
        self.event_wait_count = 0
        self.release_count = 0

    def request(self, **kwargs):
        self.request_calls.append(dict(kwargs))

    def event_get_fd(self):
        if not self.has_event_fd:
            raise AttributeError("event_get_fd unavailable")
        return self.event_fd

    def event_wait(self, _timeout):
        self.event_wait_count += 1
        raise AssertionError("native event_wait must not be called")

    def event_read(self):
        self.event_read_count += 1

    def release(self):
        self.release_count += 1


class _FakeGpiodChip:
    def __init__(self, line):
        self.line = line

    def get_line(self, _offset):
        return self.line


def _install_fake_gpiod(monkeypatch, line):
    fake_gpiod = types.SimpleNamespace(
        Chip=lambda _name: _FakeGpiodChip(line),
        LINE_REQ_EV_RISING_EDGE=17,
        LINE_REQ_FLAG_BIAS_PULL_DOWN=4,
    )
    monkeypatch.setitem(sys.modules, "gpiod", fake_gpiod)
    return fake_gpiod


def test_gpiod_v1_edge_wait_uses_fd_select_and_consumes_one_event(monkeypatch):
    readiness = {"ready": False}
    select_calls = []
    monkeypatch.setattr(
        machine_mod.select,
        "select",
        lambda r, w, x, timeout: select_calls.append((list(r), timeout))
        or ((list(r) if readiness["ready"] else []), [], []),
    )
    line = _FakeGpiodLine(event_fd=123)
    _install_fake_gpiod(monkeypatch, line)
    edge = machine_mod._make_rising_edge_input("gpiochip-test", 22, consumer="unit")

    assert edge.event_wait(0) is False
    readiness["ready"] = True
    assert edge.event_wait(0) is True
    edge.event_consume()
    edge.release()

    assert select_calls == [([123], 0.0), ([123], 0.0)]
    assert line.event_read_count == 1
    assert line.event_wait_count == 0
    assert line.release_count == 1


def test_gpiod_v1_edge_wait_times_out_without_native_wait(monkeypatch):
    select_calls = []
    monkeypatch.setattr(
        machine_mod.select,
        "select",
        lambda r, w, x, timeout: select_calls.append((list(r), timeout)) or ([], [], []),
    )
    line = _FakeGpiodLine(event_fd=456)
    _install_fake_gpiod(monkeypatch, line)
    edge = machine_mod._make_rising_edge_input("gpiochip-test", 22, consumer="unit")

    assert edge.event_wait(0.001) is False
    edge.release()

    assert select_calls == [([456], 0.001)]
    assert line.event_wait_count == 0


def test_gpiod_v1_missing_event_fd_fails_without_unbounded_wait(monkeypatch):
    line = _FakeGpiodLine(has_event_fd=False)
    _install_fake_gpiod(monkeypatch, line)

    with pytest.raises(RuntimeError, match="gpio_edge_fd_unavailable"):
        machine_mod._make_rising_edge_input("gpiochip-test", 22, consumer="unit")

    assert line.release_count == 1
    assert line.event_wait_count == 0


def _make_backend_creation_camera():
    camera = DropletCamera.__new__(DropletCamera)
    camera._capture_backend_seq = 0
    camera._trig_chip_name = "gpiochip-trigger"
    camera._trig_offset = 17
    camera._flash_chip_name = "gpiochip-edge"
    camera._flash_offset = 22
    camera._cap_id = 0
    camera._last_backend_error = None
    camera._last_backend_create_step = None
    camera.capture_phase_signal = _Signal()
    camera._log_capture_phase = lambda *_args, **_kwargs: None
    return camera


def test_capture_backend_creation_opens_edge_before_trigger(monkeypatch):
    camera = _make_backend_creation_camera()
    calls = []
    edge_line = _EdgeNeverReady()
    trigger_line = _TriggerLine()

    def _edge_factory(*_args, **_kwargs):
        calls.append("edge")
        return edge_line

    def _trigger_factory(*_args, **_kwargs):
        calls.append("trigger")
        return trigger_line

    monkeypatch.setattr(machine_mod, "_make_rising_edge_input", _edge_factory)
    monkeypatch.setattr(machine_mod, "_make_output_line", _trigger_factory)

    backend = DropletCamera._make_capture_backend(camera, reason="unit")

    assert calls == ["edge", "trigger"]
    assert backend.edge_line is edge_line
    assert backend.trigger_line is trigger_line
    assert camera._last_backend_error is None
    assert camera._last_backend_create_step is None


def test_capture_backend_creation_releases_edge_if_trigger_open_fails(monkeypatch):
    camera = _make_backend_creation_camera()
    edge_line = _EdgeNeverReady()
    phases = []
    camera._log_capture_phase = lambda phase, **payload: phases.append((phase, dict(payload)))

    monkeypatch.setattr(machine_mod, "_make_rising_edge_input", lambda *_args, **_kwargs: edge_line)

    def _trigger_factory(*_args, **_kwargs):
        raise OSError(16, "Device or resource busy")

    monkeypatch.setattr(machine_mod, "_make_output_line", _trigger_factory)

    with pytest.raises(OSError):
        DropletCamera._make_capture_backend(camera, reason="unit")

    assert edge_line.wait_calls == []
    assert edge_line.release_count == 1
    assert camera._last_backend_create_step == "trigger_output"
    assert "Device or resource busy" in camera._last_backend_error
    assert phases[-1][0] == "backend_create_failed"
    assert phases[-1][1]["step"] == "trigger_output"


def test_capture_backend_creation_does_not_open_trigger_if_edge_open_fails(monkeypatch):
    camera = _make_backend_creation_camera()
    trigger_calls = []

    def _edge_factory(*_args, **_kwargs):
        raise RuntimeError("gpio_edge_fd_unavailable: missing fd")

    def _trigger_factory(*_args, **_kwargs):
        trigger_calls.append("trigger")
        return _TriggerLine()

    monkeypatch.setattr(machine_mod, "_make_rising_edge_input", _edge_factory)
    monkeypatch.setattr(machine_mod, "_make_output_line", _trigger_factory)

    with pytest.raises(RuntimeError, match="gpio_edge_fd_unavailable"):
        DropletCamera._make_capture_backend(camera, reason="unit")

    assert trigger_calls == []
    assert camera._last_backend_create_step == "edge_input"
    assert "gpio_edge_fd_unavailable" in camera._last_backend_error


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
        "trigger_low",
        "trigger_pulse_done",
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


def test_capture_worker_success_payload_includes_identity_context_and_timestamps():
    camera = _make_async_camera()
    completion_seen = threading.Event()
    payloads = []

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
    camera.capture_completed_signal.connect(lambda payload: payloads.append(dict(payload)) or completion_seen.set())

    assert DropletCamera.capture_with_retry_async(
        camera,
        request_id="req-ident",
        capture_context="ctx-ident",
    ) is True
    assert completion_seen.wait(1.0)

    payload = payloads[0]
    assert payload["status"] == "success"
    assert payload["request_id"] == "req-ident"
    assert payload["generation"] == 1
    assert payload["backend_id"] == "1"
    assert payload["capture_context"] == "ctx-ident"
    assert isinstance(payload["queued_monotonic_ns"], int)
    assert isinstance(payload["worker_started_monotonic_ns"], int)
    assert isinstance(payload["worker_completed_monotonic_ns"], int)
    assert payload["queued_monotonic_ns"] <= payload["worker_started_monotonic_ns"]
    assert payload["worker_started_monotonic_ns"] <= payload["worker_completed_monotonic_ns"]


def test_machine_capture_droplet_image_passes_capture_context_to_camera_worker():
    class _Camera:
        def __init__(self):
            self.calls = []

        def capture_with_retry_async(self, **kwargs):
            self.calls.append(dict(kwargs))
            return True

    machine = machine_mod.Machine.__new__(machine_mod.Machine)
    camera = _Camera()
    machine.droplet_camera = camera

    assert machine_mod.Machine.capture_droplet_image(
        machine,
        throughput_mode=True,
        capture_request_id="req-machine",
        capture_context="ctx-machine",
    ) is True

    assert camera.calls[0]["request_id"] == "req-machine"
    assert camera.calls[0]["capture_context"] == "ctx-machine"
    assert camera.calls[0]["success_reasons"] == ("threshold", "fallback")


def test_machine_get_flash_safety_state_returns_normalized_copy():
    machine = machine_mod.Machine.__new__(machine_mod.Machine)
    machine._flash_state = {
        "flash_session_armed": 1,
        "flash_fault_latched": 0,
        "flash_fault_reason": "unit_reason",
        "extra": "ignored",
    }

    state = machine_mod.Machine.get_flash_safety_state(machine)

    assert state == {
        "flash_session_armed": True,
        "flash_fault_latched": False,
        "flash_fault_reason": "unit_reason",
    }


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

    assert DropletCamera.capture_with_retry_async(
        camera,
        request_id="req-fail",
        capture_context="ctx-fail",
    ) is True
    assert completion_seen.wait(1.0)

    assert len(payloads) == 1
    assert payloads[0]["status"] == "failed"
    assert payloads[0]["request_id"] == "req-fail"
    assert payloads[0]["generation"] == 1
    assert payloads[0]["backend_id"] == "1"
    assert payloads[0]["capture_context"] == "ctx-fail"
    assert isinstance(payloads[0]["queued_monotonic_ns"], int)
    assert isinstance(payloads[0]["worker_started_monotonic_ns"], int)
    assert isinstance(payloads[0]["worker_completed_monotonic_ns"], int)
    assert failures == ["retry budget exhausted"]
    assert camera._capture_worker_active.is_set() is False


def test_capture_worker_finishes_on_missing_flash_edge_without_stuck_active():
    camera = _make_async_camera()
    backend = _install_backend(camera, _FakeBackend("2", edge=_EdgeNeverReady()))
    completion_seen = threading.Event()
    payloads = []
    failures = []

    camera.capture_completed_signal.connect(lambda payload: payloads.append(dict(payload)) or completion_seen.set())
    camera.capture_failed_signal.connect(lambda msg: failures.append(str(msg)))

    assert DropletCamera.capture_with_retry_async(
        camera,
        attempts=1,
        attempt_timeout_s=0.001,
        request_id="req-no-edge",
    ) is True
    assert completion_seen.wait(1.0)

    assert backend.edge_line.wait_calls == [0, 0.001]
    assert backend.trigger_line.values == [1, 0]
    assert payloads[0]["status"] == "failed"
    assert payloads[0]["reason"] == "edge_timeout"
    assert camera._capture_worker_active.is_set() is False
    assert failures


def test_capture_retry_timeout_drops_trigger_low_after_each_attempt(monkeypatch):
    camera = _make_async_camera()
    backend = _install_backend(camera, _FakeBackend("2", edge=_EdgeNeverReady()))
    phases = []
    camera.capture_phase_signal.connect(lambda payload: phases.append((payload.get("phase"), dict(payload))))
    sleep_calls = []
    monkeypatch.setattr(machine_mod.time, "sleep", lambda seconds: sleep_calls.append(float(seconds)))

    with pytest.raises(RuntimeError, match="Flash capture failed after 3 attempts"):
        DropletCamera.capture_with_retry_sync(
            camera,
            attempts=3,
            attempt_timeout_s=0.001,
            small_sleep_between=0,
            request_id="req-retry-timeout",
            generation=0,
            backend=backend,
            backend_id="2",
        )

    assert backend.trigger_line.values == [1, 0, 1, 0, 1, 0]
    assert sleep_calls.count(0.005) == 3
    phase_names = [phase for phase, _payload in phases]
    assert phase_names.count("retry_attempt_start") == 3
    assert phase_names.count("retry_attempt_result") == 3
    assert phase_names.count("retrying") == 2
    assert phase_names[-1] == "retry_exhausted"
    retry_results = [payload for phase, payload in phases if phase == "retry_attempt_result"]
    assert [payload["reason"] for payload in retry_results] == ["edge_timeout"] * 3
    assert [payload["will_retry"] for payload in retry_results] == [True, True, False]
    assert all(payload["waited"] is True for payload in retry_results)


def test_capture_retry_frame_selection_emits_retrying_and_success_markers(monkeypatch):
    camera = _make_async_camera()
    backend = _install_backend(camera, _FakeBackend("2"))
    phases = []
    capture_calls = []
    sleep_calls = []
    camera.capture_phase_signal.connect(lambda payload: phases.append((payload.get("phase"), dict(payload))))
    monkeypatch.setattr(machine_mod.time, "sleep", lambda seconds: sleep_calls.append(float(seconds)))

    def _fake_capture_non_blocking(**_kwargs):
        capture_calls.append(1)
        if len(capture_calls) == 1:
            camera.latest_frame = None
            camera._cap_result = {
                "reason": "below_threshold",
                "mean": 5.0,
                "threshold": 29.0,
                "cap_id": 21,
            }
        else:
            camera.latest_frame = np.full((3, 4, 3), 88, dtype=np.uint8)
            camera._cap_result = {
                "reason": "threshold",
                "mean": 180.0,
                "threshold": 29.0,
                "cap_id": 22,
            }
        camera._cap_done.set()

    camera.capture_non_blocking = _fake_capture_non_blocking

    result = DropletCamera.capture_with_retry_sync(
        camera,
        attempts=3,
        attempt_timeout_s=0.001,
        small_sleep_between=0.02,
        request_id="req-frame-retry",
        generation=0,
        backend=backend,
        backend_id="2",
    )

    assert result["status"] == "success"
    assert result["cap_id"] == 22
    assert len(capture_calls) == 2
    assert sleep_calls == [0.02]
    phase_names = [phase for phase, _payload in phases]
    assert phase_names.count("retry_attempt_start") == 2
    assert phase_names.count("retry_attempt_result") == 2
    assert phase_names.count("retrying") == 1
    assert phase_names[-1] == "retry_success"
    retry_results = [payload for phase, payload in phases if phase == "retry_attempt_result"]
    assert retry_results[0]["reason"] == "below_threshold"
    assert retry_results[0]["success"] is False
    assert retry_results[0]["will_retry"] is True
    assert retry_results[1]["reason"] == "threshold"
    assert retry_results[1]["success"] is True
    assert retry_results[1]["will_retry"] is False


def test_capture_trigger_pulse_is_clamped_and_reported(monkeypatch):
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
    camera.droplet_trigger_pulse_s = 0.00001
    phases = []
    sleep_calls = []
    trigger_events = []
    camera._log_capture_phase = lambda phase, **payload: phases.append((str(phase), dict(payload)))
    camera._trigger_high = lambda: trigger_events.append("high")
    camera._trigger_low = lambda: trigger_events.append("low")
    monkeypatch.setattr(machine_mod.time, "sleep", lambda seconds: sleep_calls.append(float(seconds)))

    DropletCamera.capture_non_blocking(camera, timeout_s=0.01, request_id="req-clamp", generation=5)

    assert trigger_events == ["high", "low"]
    assert sleep_calls == [0.001]
    trigger_high = next(payload for phase, payload in phases if phase == "trigger_high")
    trigger_low = next(payload for phase, payload in phases if phase == "trigger_low")
    pulse_done = next(payload for phase, payload in phases if phase == "trigger_pulse_done")
    assert trigger_high["trigger_pulse_ms"] == "1.0"
    assert trigger_low["trigger_pulse_ms"] == "1.0"
    assert pulse_done["trigger_pulse_ms"] == "1.0"
    assert [phase for phase, _payload in phases].index("trigger_low") < [
        phase for phase, _payload in phases
    ].index("edge_wait_start")


def test_capture_trigger_pulse_duration_clamps_bounds_and_invalid_values():
    camera = DropletCamera.__new__(DropletCamera)

    camera.droplet_trigger_pulse_s = 999.0
    assert DropletCamera._trigger_pulse_duration_s(camera) == 0.100

    camera.droplet_trigger_pulse_s = -1.0
    assert DropletCamera._trigger_pulse_duration_s(camera) == 0.001

    camera.droplet_trigger_pulse_s = float("nan")
    assert DropletCamera._trigger_pulse_duration_s(camera) == 0.005


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

    assert DropletCamera.capture_with_retry_async(
        camera,
        request_id="old-request",
        capture_context="ctx-stale-generation",
    ) is True
    assert sync_entered.wait(1.0)

    recovery = DropletCamera.recover_stale_capture(camera, reason="controller timeout")
    assert recovery["ok"] is True

    release_sync.set()
    assert completion_seen.wait(1.0)
    assert payloads[0]["status"] == "stale"
    assert payloads[0]["stale"] is True
    assert payloads[0]["request_id"] == "old-request"
    assert payloads[0]["capture_context"] == "ctx-stale-generation"
    assert isinstance(payloads[0]["queued_monotonic_ns"], int)
    assert isinstance(payloads[0]["worker_started_monotonic_ns"], int)
    assert isinstance(payloads[0]["worker_completed_monotonic_ns"], int)


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

    assert DropletCamera.capture_with_retry_async(
        camera,
        request_id="backend-old",
        capture_context="ctx-stale-backend",
    ) is True
    assert sync_entered.wait(1.0)

    DropletCamera.recover_stale_capture(camera, reason="backend replaced")
    release_sync.set()

    assert completion_seen.wait(1.0)
    assert payloads[0]["status"] == "stale"
    assert payloads[0]["stale"] is True
    assert payloads[0]["stale_reason"] in {"worker_backend_superseded", "worker_generation_superseded"}
    assert payloads[0]["capture_context"] == "ctx-stale-backend"
    assert isinstance(payloads[0]["queued_monotonic_ns"], int)
    assert isinstance(payloads[0]["worker_started_monotonic_ns"], int)
    assert isinstance(payloads[0]["worker_completed_monotonic_ns"], int)


def test_capture_worker_reports_stale_backend_and_clears_active():
    camera = _make_async_camera()
    completion_seen = threading.Event()
    payloads = []

    def _fake_sync(**_kwargs):
        raise StaleCaptureBackend("backend released during event_wait")

    camera.capture_with_retry_sync = _fake_sync
    camera.capture_completed_signal.connect(lambda payload: payloads.append(dict(payload)) or completion_seen.set())

    assert DropletCamera.capture_with_retry_async(
        camera,
        request_id="req-stale",
        capture_context="ctx-stale-backend-exception",
    ) is True
    assert completion_seen.wait(1.0)

    assert payloads[0]["status"] == "stale"
    assert payloads[0]["reason"] == "stale_backend"
    assert payloads[0]["capture_context"] == "ctx-stale-backend-exception"
    assert isinstance(payloads[0]["queued_monotonic_ns"], int)
    assert isinstance(payloads[0]["worker_started_monotonic_ns"], int)
    assert isinstance(payloads[0]["worker_completed_monotonic_ns"], int)
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
