import sys
from collections import deque
import threading
import time
import types

import numpy as np
import pytest

import Machine_FreeRTOS as machine_mod
from GravimetricLedger import ImagingEjectionLifecycle
from Machine_FreeRTOS import DropletCamera, StaleCaptureBackend


class _Signal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args, **kwargs):
        for callback in list(self._callbacks):
            callback(*args, **kwargs)


class _FakeCaptureRequest:
    def __init__(self, frame, metadata, *, lores_frame=None):
        self._frame = frame
        self._lores_frame = lores_frame if lores_frame is not None else frame
        self._metadata = metadata
        self.released = False
        self.make_array_calls = []
        self.events = []

    def get_metadata(self):
        return dict(self._metadata)

    def make_array(self, stream_name):
        stream_name = str(stream_name)
        self.make_array_calls.append(stream_name)
        self.events.append(f"make_array:{stream_name}")
        if stream_name == "lores":
            return self._lores_frame
        return self._frame

    def release(self):
        self.released = True
        self.events.append("release")


class _FailingLoresCaptureRequest(_FakeCaptureRequest):
    def make_array(self, stream_name):
        stream_name = str(stream_name)
        self.make_array_calls.append(stream_name)
        self.events.append(f"make_array:{stream_name}")
        if stream_name == "lores":
            raise RuntimeError("lores unavailable")
        return self._frame


class _FakeRequestCamera:
    def __init__(self, owner, requests):
        self._owner = owner
        self._requests = list(requests)

    def capture_request(self):
        if not self._requests:
            self._owner._grab_running = False
            return None
        return self._requests.pop(0)


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


class _EdgeNoStaleThenFiredWithCallback(_EdgeNoStaleThenFired):
    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def event_wait(self, timeout):
        self.wait_calls.append(timeout)
        if len(self.wait_calls) <= 1:
            return False
        self._callback()
        return True


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


class _FakeThread:
    def __init__(self, target=None, daemon=None):
        self.target = target
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True

    def join(self, timeout=None):
        pass

    def is_alive(self):
        return self.started


class _FakePicamera2:
    instances = []
    failure_plan = []

    def __init__(self, index):
        self.index = index
        self.sensor_resolution = (1456, 1088)
        self.config_kwargs = None
        self.configured = False
        self.started = False
        self.closed = False
        self.stopped = False
        _FakePicamera2.instances.append(self)

    def _next_failure(self):
        if _FakePicamera2.failure_plan:
            return _FakePicamera2.failure_plan.pop(0)
        return None

    def create_video_configuration(self, **kwargs):
        self.config_kwargs = dict(kwargs)
        failure = self._next_failure()
        if failure == "create":
            raise RuntimeError("create failed")
        return {"config": kwargs}

    def configure(self, config):
        failure = self._next_failure()
        if failure == "configure":
            raise RuntimeError("configure failed")
        self.configured = True

    def set_controls(self, controls):
        failure = self._next_failure()
        if failure == "set_controls":
            raise RuntimeError("set_controls failed")
        self.controls = dict(controls)

    def start(self):
        failure = self._next_failure()
        if failure == "start":
            raise RuntimeError("start failed")
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


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
    camera.imaging_ejection_event = _Signal()
    ejection_events = []
    camera.imaging_ejection_event.connect(ejection_events.append)
    trigger_events = []
    camera._trigger_high = lambda: trigger_events.append("high")
    camera._trigger_low = lambda: trigger_events.append("low")

    with pytest.raises(RuntimeError, match="consume failed"):
        DropletCamera.capture_non_blocking(
            camera,
            timeout_s=0.01,
            requested_droplet_count=1,
        )

    assert trigger_events == ["high", "low"]
    assert [event.lifecycle for event in ejection_events] == [
        ImagingEjectionLifecycle.TRIGGERED,
        ImagingEjectionLifecycle.UNCERTAIN,
    ]


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
    camera.imaging_ejection_event = _Signal()
    ejection_events = []
    camera.imaging_ejection_event.connect(ejection_events.append)
    phases = []
    trigger_events = []
    camera._log_capture_phase = lambda phase, **_kwargs: phases.append(str(phase))
    camera._trigger_high = lambda: trigger_events.append("high")
    camera._trigger_low = lambda: trigger_events.append("low")

    DropletCamera.capture_non_blocking(
        camera,
        timeout_s=0.01,
        request_id="req-arm",
        generation=5,
        attempt_index=2,
        requested_droplet_count=3,
        transport_epoch=7,
    )

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
    assert "early_arm_mark" not in phases
    assert [event.lifecycle for event in ejection_events] == [
        ImagingEjectionLifecycle.TRIGGERED,
        ImagingEjectionLifecycle.ACKNOWLEDGED,
    ]
    assert all(event.transport_epoch == 7 for event in ejection_events)
    assert all(event.capture_generation == 5 for event in ejection_events)
    assert all(event.attempt_index == 2 for event in ejection_events)
    assert all(event.requested_droplet_count == 3 for event in ejection_events)


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
    camera._emit_on_complete = True
    camera._capture_worker_active = threading.Event()
    camera._capture_worker_thread = None
    camera._capture_generation = 0
    camera.latest_frame = np.full((3, 4, 3), 88, dtype=np.uint8)
    camera.capture_completed_signal = _Signal()
    camera.image_captured_signal = _Signal()
    camera.capture_failed_signal = _Signal()
    camera.capture_phase_signal = _Signal()
    camera.imaging_ejection_event = _Signal()
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


def test_capture_phase_signal_info_is_disabled_by_default():
    camera = DropletCamera.__new__(DropletCamera)
    camera._cap_id = 0
    camera.capture_phase_signal = _Signal()
    payloads = []
    camera.capture_phase_signal.connect(lambda payload: payloads.append(dict(payload)))

    DropletCamera._log_capture_phase(camera, "trigger_high", request_id="req-default")

    assert payloads == []

    DropletCamera._log_capture_phase(
        camera,
        "backend_error",
        request_id="req-warning",
        level="warning",
    )
    assert payloads[0]["phase"] == "backend_error"
    assert payloads[0]["level"] == "warning"


def test_capture_phase_info_is_accumulated_without_qt_emission():
    camera = DropletCamera.__new__(DropletCamera)
    camera._cap_id = 0
    camera.capture_phase_signal = _Signal()
    payloads = []
    camera.capture_phase_signal.connect(lambda payload: payloads.append(dict(payload)))
    DropletCamera.set_capture_performance_diagnostics_enabled(camera, True)

    DropletCamera._log_capture_phase(camera, "trigger_high", request_id="req-diag")

    assert payloads == []
    trace = DropletCamera._pop_capture_performance_trace(camera, "req-diag", 0)
    assert [row["phase"] for row in trace["phases"]] == ["trigger_high"]
    assert trace["phases"][0]["request_id"] == "req-diag"


def test_capture_debug_logging_suppresses_info_prints_by_default(capsys):
    camera = DropletCamera.__new__(DropletCamera)
    camera._cap_id = 0
    camera.capture_phase_signal = _Signal()

    DropletCamera._log_capture_phase(camera, "trigger_high", request_id="req-quiet")
    assert capsys.readouterr().out == ""

    DropletCamera._log_capture_phase(camera, "backend_error", request_id="req-warning", level="warning")
    assert "[CameraPhase] backend_error" in capsys.readouterr().out

    DropletCamera.set_capture_debug_logging_enabled(camera, True)
    DropletCamera._log_capture_phase(camera, "trigger_high", request_id="req-loud")
    assert "[CameraPhase] trigger_high" in capsys.readouterr().out


def test_droplet_camera_default_exposure_is_optimized_frame_duration():
    assert DropletCamera.DEFAULT_EXPOSURE_US == 16500


def test_capture_profile_modes_promote_dual_stream_default_with_single_stream_fallback():
    camera = DropletCamera.__new__(DropletCamera)

    assert DropletCamera.set_capture_profile(camera, "default") == "dual_stream_detection"
    assert camera._signal_stride == 1
    assert camera._signal_channel == 0
    assert camera._cap_emit_rotate is True
    assert DropletCamera.get_capture_profile(camera) == "dual_stream_detection"
    state = DropletCamera.get_capture_profile_state(camera)
    assert state["requested_profile"] == "default"
    assert state["effective_profile"] == "dual_stream_detection"

    assert DropletCamera.set_capture_profile(camera, "single_stream_detection") == "single_stream_detection"
    assert camera._signal_stride == 4
    assert camera._signal_channel == 1
    assert camera._cap_emit_rotate is True
    assert DropletCamera.get_capture_profile(camera) == "single_stream_detection"

    assert DropletCamera.set_capture_profile(camera, "fast_detection") == "single_stream_detection"
    assert camera._signal_stride == 4
    assert camera._signal_channel == 1
    assert camera._cap_emit_rotate is True
    assert DropletCamera.get_capture_profile(camera) == "single_stream_detection"
    assert DropletCamera.get_capture_profile_state(camera)["requested_profile"] == "fast_detection"

    assert DropletCamera.set_capture_profile(camera, "legacy_full_rgb") == "legacy_full_rgb"
    assert camera._signal_stride == 1
    assert camera._signal_channel is None
    assert camera._cap_emit_rotate is True
    assert DropletCamera.get_capture_profile(camera) == "legacy_full_rgb"

    assert DropletCamera.set_capture_profile(camera, "dual_stream_detection") == "dual_stream_detection"
    assert camera._signal_stride == 1
    assert camera._signal_channel == 0
    assert camera._cap_emit_rotate is True
    assert DropletCamera.get_capture_profile(camera) == "dual_stream_detection"

    assert DropletCamera.set_capture_profile(camera, "throughput") == "throughput"
    assert camera._signal_stride == 4
    assert camera._signal_channel == 1
    assert camera._cap_emit_rotate is False
    assert DropletCamera.get_capture_profile(camera) == "throughput"

    assert DropletCamera.set_capture_profile(camera, "unknown") == "dual_stream_detection"
    assert camera._signal_stride == 1
    assert camera._signal_channel == 0
    assert camera._cap_emit_rotate is True
    assert DropletCamera.get_capture_profile(camera) == "dual_stream_detection"
    assert DropletCamera.get_capture_profile_state(camera)["requested_profile"] == "default"


def test_video_configuration_kwargs_include_lores_only_for_dual_stream_profile():
    camera = DropletCamera.__new__(DropletCamera)

    DropletCamera.set_capture_profile(camera, "single_stream_detection")
    single_kwargs = DropletCamera._capture_video_configuration_kwargs(camera, (1456, 1088))

    assert single_kwargs["main"] == {"size": (1456, 1088), "format": "RGB888"}
    assert single_kwargs["buffer_count"] == 3
    assert "lores" not in single_kwargs

    DropletCamera.set_capture_profile(camera, "default")
    dual_kwargs = DropletCamera._capture_video_configuration_kwargs(camera, (1456, 1088))

    assert dual_kwargs["main"] == {"size": (1456, 1088), "format": "RGB888"}
    assert dual_kwargs["lores"] == {"size": (320, 240), "format": "YUV420"}
    assert dual_kwargs["buffer_count"] == 3


def _make_start_camera_profile_test_camera():
    camera = DropletCamera.__new__(DropletCamera)
    camera.camera = None
    camera._grab_running = False
    camera._grab_thread = None
    camera._cap_id = 0
    camera.exposure_time = 20000
    camera.capture_phase_signal = _Signal()
    DropletCamera.set_capture_profile(camera, "dual_stream_detection")
    return camera


def test_dual_stream_config_failure_falls_back_to_single_stream(monkeypatch):
    _FakePicamera2.instances = []
    _FakePicamera2.failure_plan = ["create"]
    monkeypatch.setattr(machine_mod, "Picamera2", _FakePicamera2)
    monkeypatch.setattr(machine_mod.threading, "Thread", _FakeThread)
    camera = _make_start_camera_profile_test_camera()
    payloads = []
    camera.capture_phase_signal.connect(lambda payload: payloads.append(dict(payload)))

    DropletCamera.start_camera(camera)

    assert len(_FakePicamera2.instances) == 2
    assert "lores" in _FakePicamera2.instances[0].config_kwargs
    assert "lores" not in _FakePicamera2.instances[1].config_kwargs
    assert DropletCamera.get_capture_profile(camera) == "single_stream_detection"
    state = DropletCamera.get_capture_profile_state(camera)
    assert state["requested_profile"] == "dual_stream_detection"
    assert state["effective_profile"] == "single_stream_detection"
    assert state["fallback_active"] is True
    assert state["fallback_reason"] == "dual_stream_config_failed"
    assert _FakePicamera2.instances[0].closed is True
    assert _FakePicamera2.instances[1].started is True
    assert payloads[-1]["phase"] == "capture_profile_fallback"
    assert payloads[-1]["reason"] == "dual_stream_config_failed"


def test_dual_stream_config_fallback_reraises_if_single_stream_start_fails(monkeypatch):
    _FakePicamera2.instances = []
    _FakePicamera2.failure_plan = ["create", "create"]
    monkeypatch.setattr(machine_mod, "Picamera2", _FakePicamera2)
    monkeypatch.setattr(machine_mod.threading, "Thread", _FakeThread)
    camera = _make_start_camera_profile_test_camera()

    with pytest.raises(RuntimeError, match="create failed"):
        DropletCamera.start_camera(camera)

    assert len(_FakePicamera2.instances) == 2
    assert DropletCamera.get_capture_profile(camera) == "single_stream_detection"
    assert DropletCamera.get_capture_profile_state(camera)["fallback_reason"] == "dual_stream_config_failed"


def test_grabber_records_frame_index_and_interval_when_diagnostics_enabled():
    camera = DropletCamera.__new__(DropletCamera)
    camera._grab_running = True
    camera._cv = threading.Condition(threading.Lock())
    camera._buf = deque(maxlen=16)
    camera._cap_active = False
    camera._grabber_frame_index = 0
    camera._last_grabber_frame_done_ns = None
    camera._signal_stride = 4
    camera._signal_channel = 1
    DropletCamera.set_capture_performance_diagnostics_enabled(camera, True)
    frame = np.full((4, 4, 3), 10, dtype=np.uint8)
    requests = [
        _FakeCaptureRequest(frame, {"ExposureTime": 20000}),
        _FakeCaptureRequest(frame, {"ExposureTime": 20000}),
    ]
    camera.camera = _FakeRequestCamera(camera, requests)

    DropletCamera._grabber(camera)

    assert camera._grab_running is False
    assert len(camera._buf) == 2
    first = camera._buf[0][4]
    second = camera._buf[1][4]
    assert first["frame_index"] == 1
    assert first["selected_frame_interval_ms"] is None
    assert second["frame_index"] == 2
    assert second["selected_frame_interval_ms"] is not None
    assert second["selected_frame_interval_ms"] >= 0.0


def test_dual_stream_grabber_releases_non_selected_frame_without_main_conversion():
    camera = DropletCamera.__new__(DropletCamera)
    camera._grab_running = True
    camera._cv = threading.Condition(threading.Lock())
    camera._buf = deque(maxlen=16)
    camera._cap_active = False
    camera._grabber_frame_index = 0
    camera._last_grabber_frame_done_ns = None
    camera._stream_lores_size = (320, 240)
    camera._stream_lores_format = "YUV420"
    DropletCamera.set_capture_profile(camera, "dual_stream_detection")
    DropletCamera.set_capture_performance_diagnostics_enabled(camera, True)
    main_frame = np.full((4, 4, 3), 200, dtype=np.uint8)
    lores_frame = np.zeros((360, 384), dtype=np.uint8)
    request = _FakeCaptureRequest(main_frame, {"ExposureTime": 20000}, lores_frame=lores_frame)
    camera.camera = _FakeRequestCamera(camera, [request])

    DropletCamera._grabber(camera)

    assert request.make_array_calls == ["lores"]
    assert request.events == ["make_array:lores", "release"]
    assert request.released is True
    entry = camera._buf[0]
    assert entry["arr"] is None
    assert entry["mean"] == 0.0
    assert entry["frame_timing"]["detection_stream"] == "lores"
    assert entry["frame_timing"]["main_converted_for_selected_frame"] is False
    assert DropletCamera.get_capture_profile_state(camera)["fallback_active"] is False


def _make_active_dual_grabber_camera():
    camera = DropletCamera.__new__(DropletCamera)
    camera._grab_running = True
    camera._cv = threading.Condition(threading.Lock())
    camera._buf = deque(maxlen=16)
    camera._cap_active = True
    camera._cap_arm_ns = 0
    camera._cap_deadline = time.monotonic() + 1.0
    camera._cap_max_new = 10
    camera._cap_seen = 0
    camera._cap_threshold = 29.0
    camera._cap_brightest = None
    camera._cap_emit_rotate = False
    camera._cap_done = threading.Event()
    camera._cap_result = None
    camera._cap_id = 4
    camera._cap_request_id = "dual-runtime-fail"
    camera._capture_generation = 12
    camera._cap_ack_ns = 1_000_000
    camera._cap_ack_frame_index = 0
    camera._emit_on_complete = False
    camera._grabber_frame_index = 0
    camera._last_grabber_frame_done_ns = None
    camera._stream_main_size = (1456, 1088)
    camera._stream_main_format = "RGB888"
    camera._stream_lores_size = (320, 240)
    camera._stream_lores_format = "YUV420"
    camera._stream_buffer_count = 3
    camera.exposure_time = 20000
    camera._configured_frame_duration_us = 20000
    camera._trigger_low = lambda: None
    camera._backend_lock = threading.Lock()
    camera._capture_backend = None
    camera.image_captured_signal = _Signal()
    camera.capture_phase_signal = _Signal()
    DropletCamera.set_capture_profile(camera, "dual_stream_detection")
    DropletCamera.set_capture_performance_diagnostics_enabled(camera, True)
    return camera


def test_dual_stream_runtime_lores_failure_falls_back_without_main_conversion():
    camera = _make_active_dual_grabber_camera()
    payloads = []
    camera.capture_phase_signal.connect(lambda payload: payloads.append(dict(payload)))
    main_frame = np.full((4, 4, 3), 200, dtype=np.uint8)
    request = _FailingLoresCaptureRequest(main_frame, {"ExposureTime": 20000})
    camera.camera = _FakeRequestCamera(camera, [request])

    DropletCamera._grabber(camera)

    assert request.make_array_calls == ["lores"]
    assert request.events == ["make_array:lores", "release"]
    assert request.released is True
    assert camera._cap_done.is_set() is True
    assert camera._cap_result["reason"] == "dual_stream_lores_failed"
    assert camera._cap_result["capture_profile"] == "single_stream_detection"
    state = DropletCamera.get_capture_profile_state(camera)
    assert state["requested_profile"] == "dual_stream_detection"
    assert state["effective_profile"] == "single_stream_detection"
    assert state["fallback_active"] is True
    assert state["fallback_reason"] == "dual_stream_lores_failed"
    assert any(
        payload.get("phase") == "capture_profile_fallback"
        and payload.get("reason") == "dual_stream_lores_failed"
        for payload in payloads
    )


def test_dual_stream_runtime_nonfinite_lores_mean_triggers_fallback():
    camera = _make_active_dual_grabber_camera()
    main_frame = np.full((4, 4, 3), 200, dtype=np.uint8)
    lores_frame = np.array([np.nan], dtype=np.float32)
    request = _FakeCaptureRequest(main_frame, {"ExposureTime": 20000}, lores_frame=lores_frame)
    camera.camera = _FakeRequestCamera(camera, [request])

    DropletCamera._grabber(camera)

    assert request.make_array_calls == ["lores"]
    assert request.released is True
    assert camera._cap_result["reason"] == "dual_stream_lores_failed"
    assert DropletCamera.get_capture_profile_state(camera)["fallback_reason"] == "dual_stream_lores_failed"


def test_dual_stream_lores_failure_restarts_camera_before_retry():
    camera = _make_async_camera()
    DropletCamera.set_capture_profile(camera, "dual_stream_detection")
    DropletCamera.set_capture_performance_diagnostics_enabled(camera, True)
    restart_calls = []

    def _stop_camera():
        restart_calls.append("stop")
        camera._grab_running = False
        camera.camera = None

    def _start_camera():
        restart_calls.append(("start", DropletCamera.get_capture_profile(camera)))
        camera.camera = object()
        camera._grab_running = True

    camera.stop_camera = _stop_camera
    camera.start_camera = _start_camera
    calls = {"count": 0}

    def _capture_non_blocking(**_kwargs):
        calls["count"] += 1
        camera._cap_done.clear()
        if calls["count"] == 1:
            DropletCamera._activate_capture_profile_fallback(
                camera,
                "dual_stream_lores_failed",
                "lores unavailable",
            )
            camera.latest_frame = None
            camera._cap_result = {
                "reason": "dual_stream_lores_failed",
                "capture_profile": "single_stream_detection",
                "threshold": 0.0,
                "mean": 0.0,
            }
        else:
            camera.latest_frame = np.full((3, 4, 3), 88, dtype=np.uint8)
            camera._cap_result = {
                "reason": "threshold",
                "capture_profile": "single_stream_detection",
                "threshold": 29.0,
                "mean": 88.0,
                "cap_id": 9,
            }
        camera._cap_done.set()

    camera.capture_non_blocking = _capture_non_blocking

    result = DropletCamera.capture_with_retry_sync(
        camera,
        attempts=2,
        request_id="retry-after-lores-fail",
        generation=0,
    )

    assert result["status"] == "success"
    assert calls["count"] == 2
    assert restart_calls == ["stop", ("start", "single_stream_detection")]


def test_single_stream_grabber_threshold_completes_with_current_main_frame():
    camera = DropletCamera.__new__(DropletCamera)
    camera._grab_running = True
    camera._cv = threading.Condition(threading.Lock())
    camera._buf = deque(maxlen=16)
    camera._cap_active = True
    camera._cap_arm_ns = 0
    camera._cap_deadline = time.monotonic() + 1.0
    camera._cap_max_new = 10
    camera._cap_seen = 0
    camera._cap_threshold = 29.0
    camera._cap_brightest = None
    camera._cap_emit_rotate = False
    camera._cap_done = threading.Event()
    camera._cap_result = None
    camera._cap_id = 4
    camera._cap_request_id = "default-selected"
    camera._cap_ack_ns = 1_000_000
    camera._cap_ack_frame_index = 0
    camera._emit_on_complete = False
    camera._grabber_frame_index = 0
    camera._last_grabber_frame_done_ns = None
    camera._stream_main_size = (1456, 1088)
    camera._stream_main_format = "RGB888"
    camera._stream_lores_size = (320, 240)
    camera._stream_lores_format = "YUV420"
    camera._stream_buffer_count = 3
    camera.exposure_time = 20000
    camera._configured_frame_duration_us = 20000
    camera._trigger_low = lambda: None
    camera._backend_lock = threading.Lock()
    camera._capture_backend = None
    camera.image_captured_signal = _Signal()
    DropletCamera.set_capture_profile(camera, "single_stream_detection")
    DropletCamera.set_capture_performance_diagnostics_enabled(camera, True)
    main_frame = np.full((4, 4, 3), 200, dtype=np.uint8)
    request = _FakeCaptureRequest(main_frame, {"ExposureTime": 20000})
    camera.camera = _FakeRequestCamera(camera, [request])

    DropletCamera._grabber(camera)

    assert request.make_array_calls == ["main"]
    assert request.events == ["make_array:main", "release"]
    assert camera._cap_done.is_set() is True
    assert camera._cap_active is False
    assert np.array_equal(camera.latest_frame, main_frame)
    assert camera._cap_result["reason"] == "threshold"
    assert camera._cap_result["capture_profile"] == "single_stream_detection"
    assert camera._cap_result["detection_stream"] == "main"


def test_dual_stream_grabber_converts_main_for_selected_threshold_before_release():
    camera = DropletCamera.__new__(DropletCamera)
    camera._grab_running = True
    camera._cv = threading.Condition(threading.Lock())
    camera._buf = deque(maxlen=16)
    camera._cap_active = True
    camera._cap_arm_ns = 0
    camera._cap_deadline = time.monotonic() + 1.0
    camera._cap_max_new = 10
    camera._cap_seen = 0
    camera._cap_threshold = 29.0
    camera._cap_brightest = None
    camera._cap_emit_rotate = False
    camera._cap_done = threading.Event()
    camera._cap_result = None
    camera._cap_id = 4
    camera._cap_request_id = "dual-selected"
    camera._cap_ack_ns = 1_000_000
    camera._cap_ack_frame_index = 0
    camera._emit_on_complete = False
    camera._grabber_frame_index = 0
    camera._last_grabber_frame_done_ns = None
    camera._stream_main_size = (1456, 1088)
    camera._stream_main_format = "RGB888"
    camera._stream_lores_size = (320, 240)
    camera._stream_lores_format = "YUV420"
    camera._stream_buffer_count = 3
    camera.exposure_time = 20000
    camera._configured_frame_duration_us = 20000
    camera._trigger_low = lambda: None
    camera._backend_lock = threading.Lock()
    camera._capture_backend = None
    camera.image_captured_signal = _Signal()
    DropletCamera.set_capture_profile(camera, "dual_stream_detection")
    DropletCamera.set_capture_performance_diagnostics_enabled(camera, True)
    main_frame = np.full((4, 4, 3), 200, dtype=np.uint8)
    lores_frame = np.full((360, 384), 220, dtype=np.uint8)
    request = _FakeCaptureRequest(main_frame, {"ExposureTime": 20000}, lores_frame=lores_frame)
    camera.camera = _FakeRequestCamera(camera, [request])

    DropletCamera._grabber(camera)

    assert request.make_array_calls == ["lores", "main"]
    assert request.events == ["make_array:lores", "make_array:main", "release"]
    assert camera._cap_done.is_set() is True
    assert camera._cap_active is False
    assert np.array_equal(camera.latest_frame, main_frame)
    assert camera._cap_result["reason"] == "threshold"
    assert camera._cap_result["capture_profile"] == "dual_stream_detection"
    assert camera._cap_result["detection_stream"] == "lores"
    assert camera._cap_result["main_converted_for_selected_frame"] is True
    assert camera._cap_result["lores_make_array_ms"] >= 0.0
    assert camera._cap_result["lores_signal_mean_ms"] >= 0.0
    assert camera._cap_result["main_make_array_ms"] >= 0.0
    assert camera._cap_result["make_array_ms"] == camera._cap_result["main_make_array_ms"]


def test_complete_capture_includes_selected_frame_timing_only_when_diagnostics_enabled():
    camera = _make_async_camera()
    frame = np.full((3, 4, 3), 120, dtype=np.uint8)
    camera._cap_threshold = 29.0
    camera._cap_seen = 2
    camera._cap_max_new = 10
    camera._cap_emit_rotate = False

    with camera._cv:
        DropletCamera._complete_capture_locked(
            camera,
            frame,
            {},
            120.0,
            "threshold",
            frame_timing={"make_array_ms": 1.25, "signal_mean_ms": 0.5},
        )

    assert "make_array_ms" not in camera._cap_result
    assert "signal_mean_ms" not in camera._cap_result
    assert "rotate_ms" not in camera._cap_result
    assert "selected_frame_index" not in camera._cap_result
    assert "selected_frame_interval_ms" not in camera._cap_result
    assert "selected_frame_index_after_ack" not in camera._cap_result
    assert "selected_frame_done_after_ack_ms" not in camera._cap_result

    DropletCamera.set_capture_performance_diagnostics_enabled(camera, True)
    DropletCamera.set_capture_profile(camera, "default")
    camera._stream_main_size = (1456, 1088)
    camera._stream_main_format = "RGB888"
    camera._stream_buffer_count = 3
    camera.exposure_time = 12000
    camera._configured_frame_duration_us = 12000
    camera._cap_ack_ns = 1_000_000
    camera._cap_ack_frame_index = 40
    camera._cap_done.clear()
    with camera._cv:
        DropletCamera._complete_capture_locked(
            camera,
            frame,
            {
                "ExposureTime": 11991,
                "FrameDuration": 12000,
                "SensorTimestamp": 555555,
            },
            121.0,
            "threshold",
            frame_timing={
                "make_array_ms": 1.5,
                "signal_mean_ms": 0.75,
                "frame_index": 42,
                "frame_done_ns": 21_000_000,
                "selected_frame_interval_ms": 19.5,
            },
        )

    assert camera._cap_result["make_array_ms"] == 1.5
    assert camera._cap_result["signal_mean_ms"] == 0.75
    assert camera._cap_result["rotate_ms"] >= 0.0
    assert camera._cap_result["frame_select_reason"] == "threshold"
    assert camera._cap_result["cap_seen"] == 2
    assert camera._cap_result["cap_max_new"] == 10
    assert camera._cap_result["capture_profile"] == "dual_stream_detection"
    assert camera._cap_result["requested_profile"] == "default"
    assert camera._cap_result["effective_profile"] == "dual_stream_detection"
    assert camera._cap_result["signal_stride"] == 1
    assert camera._cap_result["signal_channel"] == 0
    assert camera._cap_result["cap_emit_rotate"] is True
    assert camera._cap_result["selected_frame_index"] == 42
    assert camera._cap_result["selected_frame_interval_ms"] == 19.5
    assert camera._cap_result["selected_frame_index_after_ack"] == 2
    assert camera._cap_result["selected_frame_done_after_ack_ms"] == 20.0
    assert camera._cap_result["stream_main_size"] == [1456, 1088]
    assert camera._cap_result["stream_main_format"] == "RGB888"
    assert camera._cap_result["stream_buffer_count"] == 3
    assert camera._cap_result["configured_exposure_time_us"] == 12000
    assert camera._cap_result["configured_frame_duration_us"] == 12000
    assert camera._cap_result["selected_metadata_exposure_time_us"] == 11991
    assert camera._cap_result["selected_metadata_frame_duration_us"] == 12000
    assert camera._cap_result["selected_metadata_sensor_timestamp_ns"] == 555555


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


def test_capture_worker_batches_bounded_info_trace_into_one_completion_summary():
    camera = _make_async_camera()
    DropletCamera.set_capture_performance_diagnostics_enabled(camera, True)
    completion_seen = threading.Event()
    payloads = []
    phase_payloads = []

    def _fake_sync(**kwargs):
        for index in range(40):
            DropletCamera._log_capture_phase(
                camera,
                f"phase_{index}",
                request_id=kwargs.get("request_id"),
                generation=kwargs.get("generation"),
            )
        DropletCamera._log_capture_phase(
            camera,
            "retry_attempt_result",
            request_id=kwargs.get("request_id"),
            generation=kwargs.get("generation"),
            reason="threshold",
            mean=125.0,
            threshold=25.0,
            make_array_ms=3.0,
        )
        return {
            "status": "success",
            "request_id": kwargs.get("request_id"),
            "generation": kwargs.get("generation"),
            "cap_id": 19,
            "frame": camera.latest_frame,
            "capture_info": {"cap_id": 19, "reason": "threshold"},
            "reason": "threshold",
        }

    camera.capture_with_retry_sync = _fake_sync
    camera.capture_phase_signal.connect(lambda payload: phase_payloads.append(dict(payload)))
    camera.capture_completed_signal.connect(
        lambda payload: payloads.append(dict(payload)) or completion_seen.set()
    )

    assert DropletCamera.capture_with_retry_async(camera, request_id="req-summary") is True
    assert completion_seen.wait(1.0)

    assert phase_payloads == []
    assert len(payloads) == 1
    summary = payloads[0]["capture_performance_summary"]
    assert summary["request_id"] == "req-summary"
    assert summary["phase_count"] == 41
    assert summary["retained_phase_count"] == 32
    assert summary["dropped_phase_count"] == 9
    assert len(summary["phase_sequence"]) == 32
    assert summary["phase_sequence"][-1] == "retry_attempt_result"
    assert summary["make_array_ms"] == 3.0
    assert summary["selected_frame_mean"] == 125.0
    assert camera._capture_performance_traces == {}


def test_capture_diagnostics_disable_releases_trace_and_skips_info_collection():
    camera = DropletCamera.__new__(DropletCamera)
    camera._cap_id = 0
    camera.capture_phase_signal = _Signal()
    DropletCamera.set_capture_performance_diagnostics_enabled(camera, True)
    DropletCamera._log_capture_phase(camera, "trigger_high", request_id="req-disable", generation=1)
    assert camera._capture_performance_traces

    DropletCamera.set_capture_performance_diagnostics_enabled(camera, False)
    DropletCamera._log_capture_phase(camera, "trigger_low", request_id="req-disable", generation=1)

    assert camera._capture_performance_traces == {}


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
    machine._confirmed_imaging_droplet_count = 4
    machine._transport_epoch = 9

    assert machine_mod.Machine.capture_droplet_image(
        machine,
        throughput_mode=True,
        capture_request_id="req-machine",
        capture_context="ctx-machine",
    ) is True

    assert camera.calls[0]["request_id"] == "req-machine"
    assert camera.calls[0]["capture_context"] == "ctx-machine"
    assert camera.calls[0]["success_reasons"] == ("threshold", "fallback")
    assert camera.calls[0]["requested_droplet_count"] == 4
    assert camera.calls[0]["transport_epoch"] == 9


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
    DropletCamera.set_capture_performance_diagnostics_enabled(camera, True)
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
    summary = payloads[0]["capture_performance_summary"]
    assert summary["request_id"] == "req-no-edge"
    assert summary["edge_timeout_count"] == 1
    assert summary["trigger_count"] == 1
    assert camera._capture_performance_traces == {}
    assert payloads[0]["reason"] == "edge_timeout"
    assert camera._capture_worker_active.is_set() is False
    assert failures


def test_capture_retry_timeout_drops_trigger_low_after_each_attempt(monkeypatch):
    camera = _make_async_camera()
    DropletCamera.set_capture_performance_diagnostics_enabled(camera, True)
    backend = _install_backend(camera, _FakeBackend("2", edge=_EdgeNeverReady()))
    phases = []
    ejection_events = []
    camera.capture_phase_signal.connect(lambda payload: phases.append((payload.get("phase"), dict(payload))))
    camera.imaging_ejection_event.connect(ejection_events.append)
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
            requested_droplet_count=1,
            transport_epoch=4,
        )

    assert backend.trigger_line.values == [1, 0, 1, 0, 1, 0]
    assert sleep_calls.count(0.005) == 3
    trace = DropletCamera._pop_capture_performance_trace(camera, "req-retry-timeout", 0)
    trace_phases = [(payload.get("phase"), payload) for payload in trace["phases"]]
    phase_names = [phase for phase, _payload in trace_phases]
    assert phase_names.count("retry_attempt_start") == 3
    assert phase_names.count("retry_attempt_result") == 3
    assert phase_names.count("retrying") == 2
    assert [phase for phase, _payload in phases] == ["retry_exhausted"]
    retry_results = [payload for phase, payload in trace_phases if phase == "retry_attempt_result"]
    assert [payload["reason"] for payload in retry_results] == ["edge_timeout"] * 3
    assert [payload["will_retry"] for payload in retry_results] == [True, True, False]
    assert all(payload["waited"] is True for payload in retry_results)
    assert all("elapsed_ms" in payload for payload in retry_results)
    assert all("retry_total_elapsed_ms" in payload for payload in retry_results)
    assert retry_results[-1]["retry_total_elapsed_ms"] >= retry_results[0]["retry_total_elapsed_ms"]
    assert retry_results[-1]["retry_total_elapsed_ms"] >= retry_results[-1]["elapsed_ms"]
    assert [event.lifecycle for event in ejection_events] == [
        ImagingEjectionLifecycle.TRIGGERED,
        ImagingEjectionLifecycle.UNCERTAIN,
        ImagingEjectionLifecycle.TRIGGERED,
        ImagingEjectionLifecycle.UNCERTAIN,
        ImagingEjectionLifecycle.TRIGGERED,
        ImagingEjectionLifecycle.UNCERTAIN,
    ]
    assert [event.attempt_index for event in ejection_events] == [1, 1, 2, 2, 3, 3]


def test_capture_retry_frame_selection_emits_retrying_and_success_markers(monkeypatch):
    camera = _make_async_camera()
    DropletCamera.set_capture_performance_diagnostics_enabled(camera, True)
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
    trace = DropletCamera._pop_capture_performance_trace(camera, "req-frame-retry", 0)
    trace_phases = [(payload.get("phase"), payload) for payload in trace["phases"]]
    phase_names = [phase for phase, _payload in trace_phases]
    assert phase_names.count("retry_attempt_start") == 2
    assert phase_names.count("retry_attempt_result") == 2
    assert phase_names.count("retrying") == 1
    assert phase_names[-1] == "retry_success"
    assert phases == []
    retry_results = [payload for phase, payload in trace_phases if phase == "retry_attempt_result"]
    assert retry_results[0]["reason"] == "below_threshold"
    assert retry_results[0]["success"] is False
    assert retry_results[0]["will_retry"] is True
    assert "retry_total_elapsed_ms" in retry_results[0]
    assert retry_results[1]["reason"] == "threshold"
    assert retry_results[1]["success"] is True
    assert retry_results[1]["will_retry"] is False
    assert "retry_total_elapsed_ms" in retry_results[1]
    retry_success = next(payload for phase, payload in trace_phases if phase == "retry_success")
    assert retry_success["retry_total_elapsed_ms"] >= retry_results[0]["retry_total_elapsed_ms"]


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
