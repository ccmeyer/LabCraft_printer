from types import SimpleNamespace

import numpy as np
import pytest

from tests.calibration_test_utils import Recorder, SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

import CalibrationClasses.Model as calibration_model  # noqa: E402
from CalibrationClasses.Model import BaseCalibrationProcess, PressureBandCalibrationProcess  # noqa: E402
from CaptureTypes import CaptureStatus  # noqa: E402


class _BusyThenSuccessCaptureSignal:
    def __init__(self):
        self.emit_count = 0

    def emit(self, callback):
        self.emit_count += 1
        if self.emit_count == 1:
            callback._capture_rejection_reason = "controller_pending"
            callback._capture_rejection_state = {"worker_active": True}
            callback(None)
            return
        callback(np.zeros((8, 8, 3), dtype=np.uint8))


class _LegacyReasonThenSuccessCaptureSignal:
    def __init__(self, reason, *, rejection_state=None):
        self.emit_count = 0
        self.reason = str(reason)
        self.rejection_state = dict(rejection_state or {})

    def emit(self, callback):
        self.emit_count += 1
        if self.emit_count == 1:
            callback._capture_rejection_reason = self.reason
            callback._capture_rejection_state = dict(self.rejection_state)
            callback(None)
            return
        callback(np.zeros((8, 8, 3), dtype=np.uint8))


class _CancelledCaptureSignal:
    def __init__(self):
        self.emit_count = 0

    def emit(self, callback):
        self.emit_count += 1
        callback._capture_rejection_reason = "capture_cancelled"
        callback._capture_cancel_reason = "unit_test_cancel"
        callback._capture_rejection_state = {"worker_active": True}
        callback(None)


class _TypedStatusThenSuccessCaptureSignal:
    def __init__(self, status, *, reason="", metadata=None):
        self.emit_count = 0
        self.status = status
        self.reason = str(reason or status)
        self.metadata = dict(metadata or {})

    def emit(self, callback):
        self.emit_count += 1
        if self.emit_count == 1 and self.status == CaptureStatus.SUCCESS:
            callback._capture_request_id = "typed-success-request"
            callback._capture_result_status = CaptureStatus.SUCCESS.value
            callback._capture_result_metadata = dict(self.metadata)
            callback(np.zeros((8, 8, 3), dtype=np.uint8))
            return
        if self.emit_count == 1:
            callback._capture_result_status = (
                self.status.value if isinstance(self.status, CaptureStatus) else str(self.status)
            )
            callback._capture_rejection_reason = self.reason
            callback._capture_result_metadata = dict(self.metadata)
            callback(None)
            return
        callback._capture_request_id = "typed-success-request"
        callback._capture_result_status = CaptureStatus.SUCCESS.value
        callback._capture_result_metadata = {"cap_id": "typed-success"}
        callback(np.zeros((8, 8, 3), dtype=np.uint8))


class _TerminalTypedCaptureSignal:
    def __init__(self, status, *, reason=""):
        self.emit_count = 0
        self.status = status
        self.reason = str(reason or status)

    def emit(self, callback):
        self.emit_count += 1
        callback._capture_result_status = (
            self.status.value if isinstance(self.status, CaptureStatus) else str(self.status)
        )
        callback._capture_rejection_reason = self.reason
        callback._capture_result_metadata = {"source": "unit"}
        callback(None)


class _TimeoutThenSuccessCaptureSignal:
    def __init__(self):
        self.emit_count = 0

    def emit(self, callback):
        self.emit_count += 1
        if self.emit_count == 1:
            return
        callback(np.zeros((8, 8, 3), dtype=np.uint8))


class _RecordingSuccessCaptureSignal:
    def __init__(self):
        self.callback_attrs = {}

    def emit(self, callback):
        self.callback_attrs = {
            "capture_diag_id": getattr(callback, "_capture_diag_id", None),
            "calibration_run_id": getattr(callback, "_capture_calibration_run_id", None),
            "calibration_run_index": getattr(callback, "_capture_calibration_run_index", None),
            "calibration_process": getattr(callback, "_capture_calibration_process", None),
            "calibration_phase": getattr(callback, "_capture_calibration_phase", None),
            "stage_text": getattr(callback, "_capture_stage_text", None),
            "set_attr": getattr(callback, "_capture_set_attr", None),
            "capture_role": getattr(callback, "_capture_role", None),
            "attempt": getattr(callback, "_capture_attempt", None),
            "attempts_total": getattr(callback, "_capture_attempts_total", None),
        }
        callback._capture_request_id = "request-unit"
        callback._capture_result_status = CaptureStatus.SUCCESS.value
        callback(np.zeros((8, 8, 3), dtype=np.uint8))


def _make_capture_policy_fixture(monkeypatch, capture_signal):
    proc = BaseCalibrationProcess.__new__(BaseCalibrationProcess)
    events = []
    errors = []
    saved = []
    completed = []
    scheduled = []
    timeouts = []
    capture_perf_events = []
    proc.phase_name = "unit_phase"
    proc._record_event = lambda event_type, payload=None, **kwargs: events.append(
        (str(event_type), dict(payload or {}), dict(kwargs or {}))
    )
    proc._record_error = lambda *args, **kwargs: errors.append((args, kwargs))
    proc._start_timeout = lambda *_args, **kwargs: timeouts.append(kwargs.get("on_timeout")) or object()
    proc._cancel_timeout = lambda *_args, **_kwargs: None
    proc._last_capture_refs = {}
    proc._active_capture_pair_id = None
    proc._record_capture = lambda frame, role="capture", metadata=None: saved.append(
        {"frame": frame, "role": role, "metadata": dict(metadata or {})}
    ) or {"capture_id": "cap-test", "image_relpath": "captures/cap-test.jpg"}
    proc.calibrationError = SimpleNamespace(emit=lambda msg: errors.append((("emit", msg), {})))
    proc.calibration_manager = SimpleNamespace(
        captureImageRequested=capture_signal,
        emitCaptureCompleted=lambda: completed.append(True),
        _run_id="run-unit",
        _run_idx=2,
        record_capture_performance_marker=lambda event_kind, payload=None, **kwargs: capture_perf_events.append(
            (str(event_kind), dict(payload or {}), dict(kwargs or {}))
        )
        or dict(payload or {}),
    )
    monkeypatch.setattr(
        calibration_model.QTimer,
        "singleShot",
        lambda delay_ms, callback: scheduled.append((int(delay_ms), callback)),
    )
    return SimpleNamespace(
        proc=proc,
        events=events,
        errors=errors,
        saved=saved,
        completed=completed,
        scheduled=scheduled,
        timeouts=timeouts,
        capture_perf_events=capture_perf_events,
    )


def test_capture_policy_records_performance_markers_and_callback_context(monkeypatch):
    capture_signal = _RecordingSuccessCaptureSignal()
    fixture = _make_capture_policy_fixture(monkeypatch, capture_signal)

    BaseCalibrationProcess._capture_with_policy(
        fixture.proc,
        set_attr="background_image",
        stage_text="Capturing background image",
        attempts_total=3,
        guard_timeout_ms=5_000,
    )

    attrs = capture_signal.callback_attrs
    assert attrs["capture_diag_id"]
    assert attrs["calibration_run_id"] == "run-unit"
    assert attrs["calibration_run_index"] == 2
    assert attrs["calibration_process"] == "BaseCalibrationProcess"
    assert attrs["calibration_phase"] == "unit_phase"
    assert attrs["stage_text"] == "Capturing background image"
    assert attrs["set_attr"] == "background_image"
    assert attrs["capture_role"] == "background"
    assert attrs["attempt"] == 1
    assert attrs["attempts_total"] == 3

    event_kinds = [event[0] for event in fixture.capture_perf_events]
    assert "calibration_capture_attempt_started" in event_kinds
    assert "calibration_capture_callback_received" in event_kinds
    assert "calibration_capture_frame_recorded" in event_kinds
    assert "calibration_capture_result" in event_kinds
    assert "calibration_capture_completed_emitted" in event_kinds
    result_payload = next(
        payload for kind, payload, _kwargs in fixture.capture_perf_events
        if kind == "calibration_capture_result"
    )
    assert result_payload["request_id"] == "request-unit"
    assert result_payload["status"] == "success"
    assert result_payload["capture_status"] == CaptureStatus.SUCCESS.value


def test_request_settings_with_recording_records_performance_markers(monkeypatch):
    proc = BaseCalibrationProcess.__new__(BaseCalibrationProcess)
    proc.phase_name = "unit_phase"
    events = []
    capture_perf_events = []

    class _SettingsSignal:
        def emit(self, settings, callback):
            bind = getattr(callback, "_settings_bind_callback")
            bind(
                {
                    "request_id": getattr(callback, "_settings_request_id"),
                    "context": getattr(callback, "_settings_context"),
                    "settings": dict(settings),
                    "commands": [
                        {
                            "command_number": 123,
                            "command_type": "SET_DELAY_F",
                            "setting_key": "flash_delay",
                            "requested_value": settings["flash_delay"],
                        }
                    ],
                    "completion_command_number": 123,
                }
            )
            callback()

    proc.calibration_manager = SimpleNamespace(
        changeSettingsRequested=_SettingsSignal(),
        _run_id="run-unit",
        _run_idx=2,
        record_capture_performance_marker=lambda event_kind, payload=None, **kwargs: capture_perf_events.append(
            (str(event_kind), dict(payload or {}), dict(kwargs or {}))
        )
        or dict(payload or {}),
    )
    proc._record_event = lambda event_type, payload=None, **kwargs: events.append(
        (str(event_type), dict(payload or {}), dict(kwargs or {}))
    )
    proc._start_timeout = lambda *_args, **_kwargs: object()
    proc._cancel_timeout = lambda *_args, **_kwargs: None

    completed = []
    BaseCalibrationProcess._request_settings_with_recording(
        proc,
        {"flash_delay": 6100},
        lambda: completed.append(True),
        context="background",
        guard_timeout_ms=1000,
    )

    assert completed == [True]
    event_kinds = [event[0] for event in capture_perf_events]
    assert event_kinds == [
        "calibration_settings_requested",
        "calibration_settings_bound",
        "calibration_settings_completed",
    ]
    bound_payload = capture_perf_events[1][1]
    assert bound_payload["settings_request_id"]
    assert bound_payload["commands"][0]["command_number"] == 123
    assert bound_payload["completion_command_number"] == 123


def test_capture_policy_busy_rejection_backs_off_without_consuming_attempt(monkeypatch):
    proc = BaseCalibrationProcess.__new__(BaseCalibrationProcess)
    events = []
    saved = []
    completed = []
    scheduled = []
    proc._record_event = lambda event_type, payload=None, **kwargs: events.append(
        (str(event_type), dict(payload or {}), dict(kwargs or {}))
    )
    proc._record_error = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("busy rejection should not fail the capture")
    )
    proc._start_timeout = lambda *_args, **_kwargs: object()
    proc._cancel_timeout = lambda *_args, **_kwargs: None
    proc._last_capture_refs = {}
    proc._active_capture_pair_id = None
    proc._record_capture = lambda frame, role="capture", metadata=None: saved.append(
        {"role": role, "metadata": dict(metadata or {})}
    ) or {"capture_id": "cap-test", "image_relpath": "captures/cap-test.jpg"}
    proc.calibration_manager = SimpleNamespace(
        captureImageRequested=_BusyThenSuccessCaptureSignal(),
        emitCaptureCompleted=lambda: completed.append(True),
    )
    monkeypatch.setattr(
        calibration_model.QTimer,
        "singleShot",
        lambda delay_ms, callback: scheduled.append((int(delay_ms), callback)),
    )

    BaseCalibrationProcess._capture_with_policy(
        proc,
        set_attr="droplet_image",
        stage_text="unit capture",
        attempts_total=2,
        guard_timeout_ms=5_000,
        busy_retry_delay_ms=1_000,
    )

    assert scheduled and scheduled[0][0] == 1_000
    busy_events = [payload for event_type, payload, _kwargs in events if event_type == "capture_busy_retry"]
    assert busy_events
    assert busy_events[0]["attempt"] == 1

    scheduled.pop(0)[1]()

    success_events = [payload for event_type, payload, _kwargs in events if event_type == "capture_result"]
    assert success_events[-1]["status"] == "success"
    assert success_events[-1]["attempt"] == 1
    assert saved and saved[-1]["metadata"]["attempt"] == 1
    assert completed == [True]


def test_capture_policy_camera_capture_active_uses_busy_backoff(monkeypatch):
    capture_signal = _LegacyReasonThenSuccessCaptureSignal(
        "camera_capture_active",
        rejection_state={"cap_active": True},
    )
    fixture = _make_capture_policy_fixture(monkeypatch, capture_signal)

    BaseCalibrationProcess._capture_with_policy(
        fixture.proc,
        set_attr="droplet_image",
        stage_text="unit capture",
        attempts_total=2,
        guard_timeout_ms=5_000,
        busy_retry_delay_ms=1_250,
    )

    busy_events = [payload for event_type, payload, _kwargs in fixture.events if event_type == "capture_busy_retry"]
    assert busy_events
    assert busy_events[-1]["capture_status"] == CaptureStatus.BUSY.value
    assert fixture.scheduled and fixture.scheduled[0][0] == 1_250

    fixture.scheduled.pop(0)[1]()

    assert capture_signal.emit_count == 2
    assert fixture.saved[-1]["metadata"]["attempt"] == 1
    assert fixture.completed == [True]


def test_capture_policy_camera_backend_rejections_retry_as_backend_unavailable(monkeypatch):
    cases = [
        ("camera_backend_unsupported", {"backend_error": "gpio_edge_fd_unavailable"}),
        ("camera_not_started", {"camera_started": False}),
    ]
    for reason, rejection_state in cases:
        capture_signal = _LegacyReasonThenSuccessCaptureSignal(
            reason,
            rejection_state=rejection_state,
        )
        fixture = _make_capture_policy_fixture(monkeypatch, capture_signal)

        BaseCalibrationProcess._capture_with_policy(
            fixture.proc,
            set_attr="droplet_image",
            stage_text="unit capture",
            attempts_total=2,
            retry_delay_ms=85,
            guard_timeout_ms=5_000,
        )

        failure_events = [payload for event_type, payload, _kwargs in fixture.events if event_type == "capture_result"]
        assert failure_events[-1]["capture_status"] == CaptureStatus.BACKEND_UNAVAILABLE.value
        assert failure_events[-1]["rejection_reason"] == reason
        assert fixture.scheduled and fixture.scheduled[0][0] == 85

        fixture.scheduled.pop(0)[1]()

        assert capture_signal.emit_count == 2
        assert fixture.completed == [True]


def test_capture_policy_cancelled_capture_is_terminal(monkeypatch):
    proc = BaseCalibrationProcess.__new__(BaseCalibrationProcess)
    events = []
    errors = []
    scheduled = []
    capture_signal = _CancelledCaptureSignal()
    proc._record_event = lambda event_type, payload=None, **kwargs: events.append(
        (str(event_type), dict(payload or {}), dict(kwargs or {}))
    )
    proc._record_error = lambda *args, **kwargs: errors.append((args, kwargs))
    proc._start_timeout = lambda *_args, **_kwargs: object()
    proc._cancel_timeout = lambda *_args, **_kwargs: None
    proc._last_capture_refs = {}
    proc._active_capture_pair_id = None
    proc._record_capture = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("cancelled capture should not be recorded")
    )
    proc.calibration_manager = SimpleNamespace(
        captureImageRequested=capture_signal,
        emitCaptureCompleted=lambda: (_ for _ in ()).throw(
            AssertionError("cancelled capture should not complete")
        ),
    )
    monkeypatch.setattr(
        calibration_model.QTimer,
        "singleShot",
        lambda delay_ms, callback: scheduled.append((int(delay_ms), callback)),
    )

    BaseCalibrationProcess._capture_with_policy(
        proc,
        set_attr="droplet_image",
        stage_text="unit capture",
        attempts_total=3,
        guard_timeout_ms=5_000,
    )

    assert capture_signal.emit_count == 1
    assert scheduled == []
    assert errors == []
    cancelled_events = [payload for event_type, payload, _kwargs in events if event_type == "capture_cancelled"]
    assert cancelled_events
    assert cancelled_events[0]["cancel_reason"] == "unit_test_cancel"


def test_capture_policy_success_uses_typed_result_and_emits_completed(monkeypatch):
    capture_signal = _TypedStatusThenSuccessCaptureSignal(CaptureStatus.SUCCESS)
    fixture = _make_capture_policy_fixture(monkeypatch, capture_signal)

    BaseCalibrationProcess._capture_with_policy(
        fixture.proc,
        set_attr="droplet_image",
        stage_text="unit capture",
        attempts_total=1,
        guard_timeout_ms=5_000,
    )

    assert capture_signal.emit_count == 1
    assert hasattr(fixture.proc, "droplet_image")
    assert fixture.saved and fixture.saved[-1]["metadata"]["attempt"] == 1
    assert fixture.completed == [True]
    success_events = [payload for event_type, payload, _kwargs in fixture.events if event_type == "capture_result"]
    assert success_events[-1]["status"] == "success"
    assert fixture.errors == []


def test_capture_policy_guard_timeout_consumes_attempt_and_retries(monkeypatch):
    capture_signal = _TimeoutThenSuccessCaptureSignal()
    fixture = _make_capture_policy_fixture(monkeypatch, capture_signal)

    BaseCalibrationProcess._capture_with_policy(
        fixture.proc,
        set_attr="droplet_image",
        stage_text="unit capture",
        attempts_total=2,
        retry_delay_ms=75,
        guard_timeout_ms=5_000,
    )

    assert capture_signal.emit_count == 1
    assert fixture.timeouts and callable(fixture.timeouts[0])
    fixture.timeouts[0]()

    failure_events = [payload for event_type, payload, _kwargs in fixture.events if event_type == "capture_result"]
    assert failure_events[-1]["status"] == "failed"
    assert failure_events[-1]["capture_status"] == CaptureStatus.TIMEOUT.value
    assert fixture.scheduled and fixture.scheduled[0][0] == 75

    fixture.scheduled.pop(0)[1]()

    assert capture_signal.emit_count == 2
    assert fixture.completed == [True]
    assert fixture.saved[-1]["metadata"]["attempt"] == 2


def test_capture_policy_queue_rejection_retries_using_typed_status(monkeypatch):
    capture_signal = _TypedStatusThenSuccessCaptureSignal(
        CaptureStatus.QUEUE_REJECTED,
        reason="machine_rejected",
        metadata={"request_id": "queue-reject"},
    )
    fixture = _make_capture_policy_fixture(monkeypatch, capture_signal)

    BaseCalibrationProcess._capture_with_policy(
        fixture.proc,
        set_attr="droplet_image",
        stage_text="unit capture",
        attempts_total=2,
        retry_delay_ms=80,
        guard_timeout_ms=5_000,
    )

    failure_events = [payload for event_type, payload, _kwargs in fixture.events if event_type == "capture_result"]
    assert failure_events[-1]["capture_status"] == CaptureStatus.QUEUE_REJECTED.value
    assert failure_events[-1]["rejection_reason"] == "machine_rejected"
    assert fixture.scheduled and fixture.scheduled[0][0] == 80

    fixture.scheduled.pop(0)[1]()

    assert capture_signal.emit_count == 2
    assert fixture.completed == [True]


def test_capture_policy_backend_unavailable_retries_using_typed_status(monkeypatch):
    capture_signal = _TypedStatusThenSuccessCaptureSignal(
        CaptureStatus.BACKEND_UNAVAILABLE,
        reason="camera_backend_unavailable",
    )
    fixture = _make_capture_policy_fixture(monkeypatch, capture_signal)

    BaseCalibrationProcess._capture_with_policy(
        fixture.proc,
        set_attr="droplet_image",
        stage_text="unit capture",
        attempts_total=2,
        retry_delay_ms=90,
        guard_timeout_ms=5_000,
    )

    failure_events = [payload for event_type, payload, _kwargs in fixture.events if event_type == "capture_result"]
    assert failure_events[-1]["capture_status"] == CaptureStatus.BACKEND_UNAVAILABLE.value
    assert fixture.scheduled and fixture.scheduled[0][0] == 90

    fixture.scheduled.pop(0)[1]()

    assert capture_signal.emit_count == 2
    assert fixture.completed == [True]


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (CaptureStatus.FLASH_DISARMED, "flash_disarmed"),
        (CaptureStatus.FIRMWARE_FLASH_FAULT, "firmware_flash_fault"),
        (CaptureStatus.FIRMWARE_FLASH_LATCHED, "firmware_flash_latched"),
    ],
)
def test_capture_policy_flash_safety_statuses_are_terminal(monkeypatch, status, reason):
    capture_signal = _TerminalTypedCaptureSignal(status, reason=reason)
    fixture = _make_capture_policy_fixture(monkeypatch, capture_signal)
    final_failures = []

    BaseCalibrationProcess._capture_with_policy(
        fixture.proc,
        set_attr="droplet_image",
        stage_text="unit capture",
        attempts_total=3,
        retry_delay_ms=75,
        guard_timeout_ms=5_000,
        on_final_failure=lambda: final_failures.append(True),
    )

    assert capture_signal.emit_count == 1
    assert fixture.scheduled == []
    assert final_failures == [True]
    assert fixture.errors
    failure_events = [payload for event_type, payload, _kwargs in fixture.events if event_type == "capture_result"]
    assert failure_events[-1]["capture_status"] == status.value
    assert failure_events[-1]["rejection_reason"] == reason


def test_pressure_band_replicate_capture_uses_extended_guard_for_recovery_retry():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._current_pressure = 0.65
    proc.reps = []
    proc.replicates_target = 3
    captured = {}
    proc._capture_with_policy = lambda **kwargs: captured.update(kwargs)

    proc.onCaptureReplicate()

    assert captured["attempts_total"] == 5
    assert captured["guard_timeout_ms"] == 15_000


def _rep(cls_name: str, *, dy: int | None = None, cy: int | None = None, h: int = 1536):
    center = None if cy is None else (550, int(cy))
    return {
        "cls": str(cls_name),
        "center_px": center,
        "dy_min_px": dy,
        "nozzle_attached_area": 0,
        "nozzle_wet": False,
        "frame_height_px": int(h),
        "stream_like_count": 0,
        "max_aspect_h_over_w": None,
        "min_circularity": None,
    }


def test_pressure_band_single_exit_risk_overrides_single_when_upper_multiple_exists():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc.min_reps = 5
    proc.escalate_to = 9
    proc.replicates_target = 5
    proc.single_confidence_min = 0.70
    proc.none_confidence_min = 0.70
    proc.multiple_confidence_min = 0.40
    proc.multiple_min_count = 2
    proc.fast_single_bottom_margin_px = 220
    proc.fast_single_risk_fraction = 0.60
    proc.fast_single_risk_min_count = 3
    proc.fast_single_dy_threshold_px = 1000
    proc._current_pressure = 0.92
    proc._prev_verdict = None
    proc._prev_pressure = None
    proc.stageChanged = Recorder()
    proc.continueReplicate = Recorder()
    proc.samples = [
        {"pressure": 0.95, "verdict": "multiple"},
    ]
    proc.reps = [
        _rep("single", dy=1100, cy=1310),
        _rep("single", dy=1090, cy=1300),
        _rep("single", dy=1080, cy=1290),
        _rep("single", dy=1070, cy=1285),
        _rep("single", dy=1060, cy=1280),
    ]

    store_calls = []
    choose_calls = []
    advance_calls = []
    decision_calls = []

    proc._store_pressure_summary = lambda verdict, escalated, decision=None: store_calls.append(
        {"verdict": str(verdict), "escalated": bool(escalated), "decision": dict(decision or {})}
    )
    proc._record_decision = lambda *args, **kwargs: decision_calls.append((args, kwargs))
    proc._maybe_start_or_update_brackets = lambda _verdict: False
    proc._choose_next_pressure = lambda verdict: choose_calls.append(str(verdict))
    proc._advance_or_finish = lambda: advance_calls.append(True)

    proc.onDecide()

    assert proc.continueReplicate.calls == []
    assert store_calls and store_calls[0]["verdict"] == "multiple"
    assert store_calls[0]["decision"].get("reason") == "single_exit_risk_override"
    assert choose_calls == ["multiple"]
    assert len(advance_calls) == 1
    assert decision_calls


def test_pressure_band_completion_errors_when_no_single_band_found():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc.samples = [
        {"pressure": 0.95, "verdict": "multiple"},
        {"pressure": 0.90, "verdict": "multiple"},
        {"pressure": 0.85, "verdict": "none"},
    ]
    proc.start_pressure = 0.95
    proc.P_MIN = 0.3
    proc.P_MAX = 5.0
    proc.stageChanged = Recorder()
    proc.calibrationError = Recorder()
    proc.calibrationDataUpdated = Recorder()
    proc.calibrationCompleted = Recorder()
    proc._record_error = lambda *args, **kwargs: None
    proc.calibration_manager = SimpleNamespace(
        set_primary_pressure_band=lambda _payload: (_ for _ in ()).throw(AssertionError("should not set band"))
    )
    proc._compute_single_bands = lambda: []

    proc.onCalibrationCompleted()

    assert proc.calibrationError.calls
    assert "no valid single-droplet pressure band" in proc.calibrationError.calls[0][0][0].lower()
    assert proc.calibrationDataUpdated.calls == []
    assert proc.calibrationCompleted.calls == []


def _build_choose_proc(*, verdict: str, min_single_pressure):
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._phase = "scan"
    proc._pulse_width_us = 1500
    proc._upper_bracket = None
    proc._lower_bracket = None
    proc._straddle_bracket = None
    proc.dp_min = 0.01
    proc.dp = 0.05
    proc.multiple_big_step = 0.10
    proc.none_jump_up = 0.10
    proc.small_move_px = 8
    proc.large_move_px = 40
    proc.near_nozzle_px = 560
    proc.far_nozzle_px = 1050
    proc._prev_dy = None
    proc._prev_pressure = None
    proc._current_pressure = 0.90
    proc.P_MIN = 0.3
    proc.P_MAX = 5.0
    proc.auto_stop_on_nozzle_wet = True
    proc._early_stop = False
    proc._stop_reason = None
    proc._terminate_at_pressure = None
    proc._min_single_pressure = min_single_pressure
    proc.reps = [
        _rep(verdict, dy=120, cy=320),
        _rep(verdict, dy=118, cy=318),
        _rep(verdict, dy=121, cy=322),
    ]
    for r in proc.reps:
        r["nozzle_wet"] = True
    proc.finalize = Recorder()
    proc._record_decision = lambda *args, **kwargs: None
    return proc


def _build_apply_proc():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc.start_pressure = 1.00
    proc.P_MIN = 0.3
    proc.P_MAX = 5.0
    proc.dp = 0.05
    proc.dp_min = 0.01
    proc.min_reps = 5
    proc.initial_reps_target = 3
    proc.reps = []
    proc._current_pressure = None
    proc._next_pressure = 1.00
    proc._base_classify_delay_us = 5850
    proc._active_classify_delay_us = 5850
    proc._carry_forward_classify_delay_us = None
    proc._carry_forward_delay_anchor_pressure = None
    proc._delay_retest_done_for_pressure = False
    proc._delay_retest_steps_done_for_pressure = 0
    proc._delay_retest_earlier_steps_done_for_pressure = 0
    proc._delay_retest_later_steps_done_for_pressure = 0
    proc._delay_retest_in_progress = False
    proc._delay_retest_context = None
    proc._retest_mode_active = False
    proc._invalid_skip_count = 0
    proc._initial_reps_target = lambda: 3
    proc._should_discard_settling_shot = lambda *_args, **_kwargs: False
    proc.stageChanged = Recorder()
    proc.pressureApplied = SignalStub()
    proc.calibration_manager = SimpleNamespace(changeSettingsRequested=Recorder())
    return proc


def test_pressure_band_nozzle_wet_is_deferred_while_high_multiple_and_no_single_seen():
    proc = _build_choose_proc(verdict="multiple", min_single_pressure=None)

    proc._choose_next_pressure("multiple")

    assert proc._early_stop is False
    assert proc.finalize.calls == []
    assert proc._next_pressure < 0.90


def test_pressure_band_nozzle_wet_still_stops_after_single_region_seen():
    proc = _build_choose_proc(verdict="multiple", min_single_pressure=0.82)

    proc._choose_next_pressure("multiple")

    assert proc._early_stop is True
    assert proc._stop_reason == "Nozzle wet detected during scan"
    assert proc.finalize.calls


def test_pressure_band_nozzle_wet_requires_confirmation_before_stop():
    proc = _build_choose_proc(verdict="multiple", min_single_pressure=0.82)
    proc.nozzle_wet_confirm_reps = 2
    proc.reps[0]["nozzle_wet"] = True
    proc.reps[1]["nozzle_wet"] = False
    proc.reps[2]["nozzle_wet"] = False

    proc._choose_next_pressure("multiple")

    assert proc._early_stop is False
    assert proc.finalize.calls == []
    assert proc._next_pressure < 0.90


def test_pressure_band_wet_none_is_reclassified_to_multiple_direction_pre_single():
    proc = _build_choose_proc(verdict="none", min_single_pressure=None)
    proc.nozzle_wet_confirm_reps = 1

    proc._choose_next_pressure("none")

    assert proc._early_stop is False
    assert proc.finalize.calls == []
    assert proc._next_pressure < 0.90


def test_pressure_band_reacquire_too_close_is_reclassified_none_not_stop():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._discard_next = False
    proc._phase = "reacquire_up"
    proc._prev_verdict = "none"
    proc._current_pressure = 1.10
    proc.safety_clearance_px = 350
    proc.nozzle_center_px = (100, 100)
    proc.nozzle_area_threshold = 8000
    proc.background_image = np.zeros((220, 220), dtype=np.uint8)
    proc.droplet_image = np.zeros((220, 220), dtype=np.uint8)
    proc.reps = []
    proc._invalid_skip_count = 0
    proc._invalid_skip_cap = 6
    proc._active_classify_delay_us = 5850
    proc.classify_delay_us = 5850
    proc.stageChanged = Recorder()
    proc.replicateReady = Recorder()
    proc.finalize = Recorder()
    proc.calibrationError = Recorder()
    proc.presentImageSignal = Recorder()
    decision_calls = []
    proc._record_decision = lambda *args, **kwargs: decision_calls.append((args, kwargs))
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplets=lambda *args, **kwargs: ([(100, 120)], 0, np.zeros((220, 220), dtype=np.uint8))
        )
    )

    proc.onAnalyzeReplicate()

    assert proc.finalize.calls == []
    assert proc.replicateReady.calls
    assert len(proc.reps) == 1
    assert proc.reps[0]["cls"] == "none"
    assert proc.reps[0]["dy_min_px"] is None
    assert decision_calls


def test_pressure_band_scan_too_close_pre_single_is_reclassified_none_not_stop():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._discard_next = False
    proc._phase = "scan"
    proc._prev_verdict = "multiple"
    proc._current_pressure = 1.05
    proc.safety_clearance_px = 350
    proc.nozzle_center_px = (100, 100)
    proc.nozzle_area_threshold = 8000
    proc.background_image = np.zeros((220, 220), dtype=np.uint8)
    proc.droplet_image = np.zeros((220, 220), dtype=np.uint8)
    proc.reps = []
    proc._invalid_skip_count = 0
    proc._invalid_skip_cap = 6
    proc._active_classify_delay_us = 5850
    proc.classify_delay_us = 5850
    proc._min_single_pressure = None
    proc.stageChanged = Recorder()
    proc.replicateReady = Recorder()
    proc.finalize = Recorder()
    proc.calibrationError = Recorder()
    proc.presentImageSignal = Recorder()
    decision_calls = []
    proc._record_decision = lambda *args, **kwargs: decision_calls.append((args, kwargs))
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplets=lambda *args, **kwargs: ([(100, 120)], 0, np.zeros((220, 220), dtype=np.uint8))
        )
    )

    proc.onAnalyzeReplicate()

    assert proc.finalize.calls == []
    assert proc.replicateReady.calls
    assert len(proc.reps) == 1
    assert proc.reps[0]["cls"] == "none"
    assert proc.reps[0]["dy_min_px"] is None
    assert decision_calls
    assert any(
        args and args[0] == "pre_single_near_nozzle_reclassified_none"
        for args, _kwargs in decision_calls
    )


def test_pressure_band_reacquire_guard_resumes_scan_after_max_steps():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._phase = "reacquire_up"
    proc._current_pressure = 1.20
    proc._prev_pressure = None
    proc._prev_verdict = None
    proc.P_MIN = 0.3
    proc.P_MAX = 5.0
    proc.dp_min = 0.01
    proc._reacquire_step = 0.10
    proc._reacquire_growth = 1.7
    proc._reacquire_step_max = 0.30
    proc._reacquire_steps_taken = 17
    proc._reacquire_max_steps = 18
    proc.stageChanged = Recorder()
    decision_calls = []
    proc._record_decision = lambda *args, **kwargs: decision_calls.append((args, kwargs))

    transitioned = proc._maybe_start_or_update_brackets("none")

    assert transitioned is True
    assert proc._phase == "scan"
    assert proc._next_pressure < 1.20
    assert decision_calls
    assert decision_calls[0][0][0] == "reacquire_guard_resume_scan"


def test_pressure_band_apply_pressure_uses_and_then_clears_carried_delay():
    proc = _build_apply_proc()
    proc._current_pressure = 1.00
    proc._next_pressure = 1.05
    proc._carry_forward_classify_delay_us = 5350
    proc._carry_forward_delay_anchor_pressure = 1.00

    proc.onApplyPressure()

    assert proc._active_classify_delay_us == 5350
    first_settings = proc.calibration_manager.changeSettingsRequested.calls[0][0][0]
    assert first_settings["flash_delay"] == 5350

    proc._next_pressure = 0.95
    proc.onApplyPressure()

    assert proc._active_classify_delay_us == 5850
    assert proc._carry_forward_classify_delay_us is None
    assert proc._carry_forward_delay_anchor_pressure is None
    second_settings = proc.calibration_manager.changeSettingsRequested.calls[1][0][0]
    assert second_settings["flash_delay"] == 5850


def test_pressure_band_seek_upper_guard_resumes_scan_after_span_or_steps():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._phase = "seek_upper"
    proc._current_pressure = 2.05
    proc._prev_pressure = None
    proc._prev_verdict = "single"
    proc.P_MIN = 0.3
    proc.P_MAX = 5.0
    proc.dp_min = 0.01
    proc._seek_step = 0.08
    proc._seek_growth = 1.7
    proc._seek_step_max = 0.20
    proc._seek_upper_steps = 9
    proc._seek_upper_max_steps = 10
    proc._seek_upper_max_span_psi = 0.80
    proc._first_single_pressure = 1.10
    proc.stageChanged = Recorder()
    decision_calls = []
    proc._record_decision = lambda *args, **kwargs: decision_calls.append((args, kwargs))

    transitioned = proc._maybe_start_or_update_brackets("single")

    assert transitioned is True
    assert proc._phase == "scan"
    assert proc._next_pressure <= 1.10
    assert decision_calls
    assert decision_calls[0][0][0] == "seek_upper_guard_resume_scan"


def test_pressure_band_retest_does_not_request_second_earlier_step_after_cap():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._base_classify_delay_us = 5850
    proc._active_classify_delay_us = 5350
    proc.delay_retest_step_us = 500
    proc.delay_retest_min_us = 2000
    proc.delay_retest_max_earlier_steps = 1
    proc._delay_retest_earlier_steps_done_for_pressure = 1
    proc._delay_retest_context = {
        "prior_verdict": "multiple",
        "prior_counts": {"none": 0, "single": 3, "multiple": 2},
        "prior_decision": {"has_upper_multiple_evidence": True},
        "trigger_reason": "mixed_single_multiple",
    }

    reason = proc._should_run_delay_retest(
        "single",
        {"none": 0, "single": 5, "multiple": 0},
        {"has_upper_multiple_evidence": True},
    )

    assert reason is None


def test_pressure_band_retest_merge_keeps_multiple_when_prior_multiple_evidence_exists():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc.multiple_confidence_min = 0.40
    proc._delay_retest_context = {
        "trigger_reason": "mixed_single_multiple",
        "prior_verdict": "multiple",
        "prior_counts": {"none": 0, "single": 2, "multiple": 3},
        "prior_decision": {"has_upper_multiple_evidence": True},
        "prior_confidence": 0.75,
        "prior_reason": "multiple_confident",
    }
    decision = {"reason": "single_confident"}

    verdict, confidence, merged = proc._merge_delay_retest_decision(
        "single",
        0.70,
        {"none": 0, "single": 5, "multiple": 0},
        decision,
    )

    assert verdict == "multiple"
    assert confidence >= 0.75
    assert merged["reason"] == "retest_conflict_keep_multiple"


def test_pressure_band_position_regression_triggers_delay_retest():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._base_classify_delay_us = 5850
    proc._active_classify_delay_us = 5850
    proc.delay_retest_step_us = 500
    proc.delay_retest_min_us = 2000
    proc.delay_retest_max_earlier_steps = 1
    proc._delay_retest_earlier_steps_done_for_pressure = 0
    proc.fast_single_bottom_margin_px = 220
    proc.fast_single_risk_fraction = 0.60
    proc.fast_single_risk_min_count = 3
    proc.fast_single_dy_threshold_px = 1000
    proc.large_move_px = 40
    proc._current_pressure = 0.55
    proc.samples = [
        {
            "pressure": 0.50,
            "verdict": "single",
            "dy_min_px_med": 1080,
            "replicates": [
                _rep("single", dy=1100, cy=1310),
                _rep("single", dy=1090, cy=1300),
                _rep("single", dy=1080, cy=1290),
                _rep("single", dy=1070, cy=1285),
                _rep("single", dy=1060, cy=1280),
            ],
        }
    ]
    proc.reps = [
        _rep("single", dy=760, cy=860),
        _rep("single", dy=750, cy=850),
        _rep("single", dy=740, cy=840),
        _rep("single", dy=730, cy=830),
        _rep("single", dy=720, cy=820),
    ]

    reason = proc._should_run_delay_retest(
        "single",
        {"none": 0, "single": 5, "multiple": 0},
        {"has_upper_multiple_evidence": False},
    )

    assert reason == "pressure_upward_position_regression"


def test_pressure_band_later_delay_candidate_moves_back_toward_base():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc.classify_delay_us = 5850
    proc._base_classify_delay_us = 5850
    proc._active_classify_delay_us = 5350
    proc.delay_retest_step_us = 500
    proc.delay_retest_max_later_offset_us = 1000
    proc.delay_retest_abs_max_us = 20000

    assert proc._later_delay_candidate_us() == 5850


def test_pressure_band_edge_retest_only_allowed_in_scan_phase():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._base_classify_delay_us = 5850
    proc._active_classify_delay_us = 5850
    proc.delay_retest_step_us = 500
    proc.delay_retest_min_us = 2000
    proc.delay_retest_max_earlier_steps = 1
    proc._delay_retest_earlier_steps_done_for_pressure = 0
    proc._current_pressure = 1.50
    proc._edge_retest_pressures = []
    proc._edge_retest_count = 0
    proc.edge_retest_scan_only = True
    proc.edge_retest_cooldown_psi = 0.03
    proc.edge_retest_max_per_run = 3
    proc.edge_retest_proximity_window_psi = 0.03
    proc.samples = [{"pressure": 1.52, "verdict": "multiple"}]

    proc._phase = "refine_upper"
    r1 = proc._should_run_delay_retest(
        "single",
        {"none": 0, "single": 5, "multiple": 0},
        {"has_upper_multiple_evidence": True},
    )
    assert r1 is None

    proc._phase = "scan"
    r2 = proc._should_run_delay_retest(
        "single",
        {"none": 0, "single": 5, "multiple": 0},
        {"has_upper_multiple_evidence": True},
    )
    assert r2 == "edge_single_with_upper_multiple"


def test_pressure_band_edge_retest_cooldown_skips_nearby_pressure():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._base_classify_delay_us = 5850
    proc._active_classify_delay_us = 5850
    proc.delay_retest_step_us = 500
    proc.delay_retest_min_us = 2000
    proc.delay_retest_max_earlier_steps = 1
    proc._delay_retest_earlier_steps_done_for_pressure = 0
    proc._phase = "scan"
    proc.edge_retest_scan_only = True
    proc.edge_retest_cooldown_psi = 0.03
    proc.edge_retest_max_per_run = 3
    proc.edge_retest_proximity_window_psi = 0.03
    proc._edge_retest_count = 1
    proc._edge_retest_pressures = [1.50]
    proc.samples = [{"pressure": 1.56, "verdict": "multiple"}]
    proc._current_pressure = 1.515

    near = proc._should_run_delay_retest(
        "single",
        {"none": 0, "single": 5, "multiple": 0},
        {"has_upper_multiple_evidence": True},
    )
    assert near is None

    proc._current_pressure = 1.55
    far = proc._should_run_delay_retest(
        "single",
        {"none": 0, "single": 5, "multiple": 0},
        {"has_upper_multiple_evidence": True},
    )
    assert far == "edge_single_with_upper_multiple"

    proc.samples = [{"pressure": 1.575, "verdict": "multiple"}]
    near_edge = proc._should_run_delay_retest(
        "single",
        {"none": 0, "single": 5, "multiple": 0},
        {"has_upper_multiple_evidence": True},
    )
    assert near_edge == "edge_single_with_upper_multiple"


def test_pressure_band_edge_retest_respects_per_side_cap():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._base_classify_delay_us = 5850
    proc._active_classify_delay_us = 5850
    proc.delay_retest_step_us = 500
    proc.delay_retest_min_us = 2000
    proc.delay_retest_max_earlier_steps = 1
    proc._delay_retest_earlier_steps_done_for_pressure = 0
    proc._phase = "scan"
    proc.edge_retest_scan_only = True
    proc.edge_retest_cooldown_psi = 0.03
    proc.edge_retest_max_per_run = 3
    proc.edge_retest_proximity_window_psi = 0.03
    proc.edge_retest_max_per_side = 1
    proc._edge_retest_count = 1
    proc._edge_retest_pressures = [1.50]
    proc._edge_retest_side_counts = {"upper": 1, "lower": 0}
    proc.samples = [{"pressure": 1.56, "verdict": "multiple"}]
    proc._current_pressure = 1.55
    proc._upper_refine_points_done = 0
    proc._lower_refine_points_done = 0
    proc.max_upper_refine_points = 2
    proc.max_lower_refine_points = 1

    reason = proc._should_run_delay_retest(
        "single",
        {"none": 0, "single": 5, "multiple": 0},
        {"has_upper_multiple_evidence": True},
    )

    assert reason is None


def test_pressure_band_start_delay_retest_later_increments_later_counter():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc.classify_delay_us = 5850
    proc._base_classify_delay_us = 5850
    proc._active_classify_delay_us = 5350
    proc.delay_retest_step_us = 500
    proc.delay_retest_min_us = 2000
    proc.delay_retest_max_earlier_steps = 1
    proc.delay_retest_max_later_steps = 2
    proc.delay_retest_max_later_offset_us = 1000
    proc.delay_retest_abs_max_us = 20000
    proc.delay_retest_timeout_ms = 15000
    proc._delay_retest_done_for_pressure = False
    proc._delay_retest_steps_done_for_pressure = 0
    proc._delay_retest_earlier_steps_done_for_pressure = 0
    proc._delay_retest_later_steps_done_for_pressure = 0
    proc._delay_retest_in_progress = False
    proc._delay_retest_context = None
    proc._retest_mode_active = False
    proc._current_pressure = 1.20
    proc._carry_forward_classify_delay_us = 5350
    proc._carry_forward_delay_anchor_pressure = 1.20
    proc.min_reps = 5
    proc.retest_min_reps = 3
    proc.reps = []
    proc._invalid_skip_count = 0
    proc._discard_next = False
    proc.stageChanged = Recorder()
    proc.continueReplicate = Recorder()
    proc.calibrationError = Recorder()
    proc.finalize = Recorder()
    proc._record_decision = lambda *args, **kwargs: None
    proc._record_error = lambda *args, **kwargs: None
    proc._cancel_timeout = lambda *_args, **_kwargs: None
    proc._start_timeout = lambda *_args, **_kwargs: "timer-token"
    proc._request_settings_with_recording = lambda _settings, cb, context=None: cb()

    ok = proc._start_delay_retest(
        "attached_stream_requires_later_delay",
        "single",
        {"single": 5, "none": 0, "multiple": 0},
        {"reason": "single_confident"},
        1.0,
        direction="later",
    )

    assert ok is True
    assert proc._active_classify_delay_us == 5850
    assert proc._delay_retest_later_steps_done_for_pressure == 1
    assert proc._delay_retest_earlier_steps_done_for_pressure == 0
    assert proc.replicates_target == 3
    assert proc._discard_next is False
    assert proc._retest_mode_active is True
    assert proc._carry_forward_classify_delay_us is None
    assert proc._carry_forward_delay_anchor_pressure is None


def test_pressure_band_regression_retest_preserves_multiple_and_stores_carry_forward_delay():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc.multiple_confidence_min = 0.40
    proc.classify_delay_us = 5850
    proc._base_classify_delay_us = 5850
    proc._active_classify_delay_us = 5850
    proc.delay_retest_step_us = 500
    proc.delay_retest_min_us = 2000
    proc.delay_retest_max_earlier_steps = 1
    proc.delay_retest_timeout_ms = 15000
    proc._delay_retest_done_for_pressure = False
    proc._delay_retest_steps_done_for_pressure = 0
    proc._delay_retest_earlier_steps_done_for_pressure = 0
    proc._delay_retest_later_steps_done_for_pressure = 0
    proc._delay_retest_in_progress = False
    proc._delay_retest_context = None
    proc._retest_mode_active = False
    proc._carry_forward_classify_delay_us = None
    proc._carry_forward_delay_anchor_pressure = None
    proc.fast_single_bottom_margin_px = 220
    proc.fast_single_risk_fraction = 0.60
    proc.fast_single_risk_min_count = 3
    proc.fast_single_dy_threshold_px = 1000
    proc.large_move_px = 40
    proc._current_pressure = 0.55
    proc.min_reps = 5
    proc.retest_min_reps = 3
    proc.reps = [
        _rep("single", dy=760, cy=860),
        _rep("single", dy=750, cy=850),
        _rep("single", dy=740, cy=840),
        _rep("single", dy=730, cy=830),
        _rep("single", dy=720, cy=820),
    ]
    proc.samples = [
        {
            "pressure": 0.50,
            "verdict": "single",
            "dy_min_px_med": 1080,
            "replicates": [
                _rep("single", dy=1100, cy=1310),
                _rep("single", dy=1090, cy=1300),
                _rep("single", dy=1080, cy=1290),
                _rep("single", dy=1070, cy=1285),
                _rep("single", dy=1060, cy=1280),
            ],
        }
    ]
    proc.stageChanged = Recorder()
    proc.continueReplicate = Recorder()
    proc.calibrationError = Recorder()
    proc.finalize = Recorder()
    proc._record_decision = lambda *args, **kwargs: None
    proc._record_error = lambda *args, **kwargs: None
    proc._cancel_timeout = lambda *_args, **_kwargs: None
    proc._start_timeout = lambda *_args, **_kwargs: "timer-token"
    proc._request_settings_with_recording = lambda _settings, cb, context=None: cb()

    reason = proc._should_run_delay_retest(
        "single",
        {"none": 0, "single": 5, "multiple": 0},
        {"reason": "single_confident", "has_upper_multiple_evidence": False},
    )
    assert reason == "pressure_upward_position_regression"

    ok = proc._start_delay_retest(
        reason,
        "single",
        {"single": 5, "none": 0, "multiple": 0},
        {"reason": "single_confident"},
        1.0,
    )

    assert ok is True
    assert proc._carry_forward_classify_delay_us == 5350
    assert proc._carry_forward_delay_anchor_pressure == 0.55

    verdict, confidence, merged = proc._merge_delay_retest_decision(
        "multiple",
        0.80,
        {"none": 0, "single": 0, "multiple": 3},
        {"reason": "multiple_confident"},
    )

    assert verdict == "multiple"
    assert confidence >= 0.80
    assert merged["reason"] == "retest_conflict_multiple_wins"
    assert merged["retest_trigger_reason"] == "pressure_upward_position_regression"


def test_pressure_band_settling_discard_only_for_major_pressure_change():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc.discard_first_after_major_pressure_change = True
    proc.settle_discard_pressure_delta_psi = 0.03

    assert proc._should_discard_settling_shot(None, 1.20) is True
    assert proc._should_discard_settling_shot(1.20, 1.22) is False
    assert proc._should_discard_settling_shot(1.20, 1.24) is True


def test_pressure_band_conservative_finalize_triggers_when_band_is_bracketed():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc.samples = [
        {"pressure": 0.70, "verdict": "none"},
        {"pressure": 0.80, "verdict": "single"},
        {"pressure": 0.88, "verdict": "single"},
        {"pressure": 0.95, "verdict": "multiple"},
    ]
    proc._current_pressure = 0.88
    proc._phase = "scan"
    proc.conservative_finalize_narrow_width_psi = 0.05
    proc.max_upper_refine_points = 2
    proc.max_lower_refine_points = 1
    proc._upper_refine_points_done = 0
    proc._lower_refine_points_done = 0
    proc.stageChanged = Recorder()
    proc.finalize = Recorder()
    decision_calls = []
    proc._record_decision = lambda *args, **kwargs: decision_calls.append((args, kwargs))

    ok = proc._maybe_finalize_conservative_band()

    assert ok is True
    assert proc.finalize.calls
    assert decision_calls


def test_pressure_band_refine_upper_respects_probe_cap():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._phase = "refine_upper"
    proc._current_pressure = 1.05
    proc._prev_pressure = 1.10
    proc._prev_verdict = "multiple"
    proc._upper_bracket = [1.00, 1.10]
    proc._first_single_pressure = 1.00
    proc._upper_edge_locked = False
    proc._min_single_pressure = 0.96
    proc._upper_refine_points_done = 2
    proc.max_upper_refine_points = 2
    proc.dp_min = 0.01
    proc.P_MIN = 0.3
    proc.P_MAX = 5.0
    proc.stageChanged = Recorder()

    transitioned = proc._maybe_start_or_update_brackets("single")

    assert transitioned is True
    assert proc._phase == "scan"
    assert proc._upper_edge_locked is True
    assert proc._upper_bracket is None
    assert proc._next_pressure < 0.96


def test_pressure_band_analyze_reclassifies_stream_like_single_as_multiple():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._discard_next = False
    proc._phase = "scan"
    proc._prev_verdict = "single"
    proc._current_pressure = 1.55
    proc.safety_clearance_px = 350
    proc.nozzle_center_px = (100, 100)
    proc.nozzle_area_threshold = 8000
    proc.background_image = np.zeros((220, 220), dtype=np.uint8)
    proc.droplet_image = np.zeros((220, 220), dtype=np.uint8)
    proc.reps = []
    proc._invalid_skip_count = 0
    proc._invalid_skip_cap = 6
    proc._active_classify_delay_us = 5850
    proc.classify_delay_us = 5850
    proc.stream_aspect_hard = 2.0
    proc.stream_aspect_soft = 1.6
    proc.stream_circularity_max = 0.55
    proc.stream_min_area_px = 1200
    proc.stageChanged = Recorder()
    proc.replicateReady = Recorder()
    proc.finalize = Recorder()
    proc.calibrationError = Recorder()
    proc.presentImageSignal = Recorder()
    decision_calls = []
    proc._record_decision = lambda *args, **kwargs: decision_calls.append((args, kwargs))
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplets=lambda *args, **kwargs: (
                [(110, 540)],
                0,
                np.zeros((220, 220), dtype=np.uint8),
                {
                    "free_droplets": [
                        {
                            "area_px": 2600,
                            "aspect_h_over_w": 2.4,
                            "circularity": 0.31,
                            "is_stream_like": True,
                        }
                    ]
                },
            )
        )
    )

    proc.onAnalyzeReplicate()

    assert proc.finalize.calls == []
    assert proc.replicateReady.calls
    assert len(proc.reps) == 1
    rep = proc.reps[0]
    assert rep["cls"] == "multiple"
    assert rep["stream_like_count"] == 1
    assert rep["max_aspect_h_over_w"] >= 2.4
    assert rep["min_circularity"] <= 0.31
    assert decision_calls
    assert any(
        args and args[0] == "stream_like_single_reclassified_multiple"
        for args, _kwargs in decision_calls
    )


def test_pressure_band_analyze_residue_near_nozzle_does_not_mark_nozzle_wet():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc._discard_next = False
    proc._phase = "scan"
    proc._prev_verdict = "single"
    proc._current_pressure = 1.55
    proc.safety_clearance_px = 350
    proc.nozzle_center_px = (100, 100)
    proc.nozzle_area_threshold = 8000
    proc.background_image = np.zeros((900, 220), dtype=np.uint8)
    proc.droplet_image = np.zeros((900, 220), dtype=np.uint8)
    proc.reps = []
    proc._invalid_skip_count = 0
    proc._invalid_skip_cap = 6
    proc._active_classify_delay_us = 5850
    proc.classify_delay_us = 5850
    proc.stageChanged = Recorder()
    proc.replicateReady = Recorder()
    proc.finalize = Recorder()
    proc.calibrationError = Recorder()
    proc.presentImageSignal = Recorder()
    proc._record_decision = lambda *args, **kwargs: None
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplets=lambda *args, **kwargs: (
                [(110, 620)],
                12000,
                np.zeros((900, 220), dtype=np.uint8),
                {
                    "free_droplets": [
                        {
                            "area_px": 1800,
                            "aspect_h_over_w": 1.2,
                            "circularity": 0.9,
                            "is_stream_like": False,
                        }
                    ],
                    "nozzle_contact_detected": False,
                    "near_nozzle_residue_detected": True,
                    "near_nozzle_residue_area": 12000,
                    "near_nozzle_residue_components": 1,
                },
            )
        )
    )

    proc.onAnalyzeReplicate()

    assert proc.finalize.calls == []
    assert proc.replicateReady.calls
    assert len(proc.reps) == 1
    rep = proc.reps[0]
    assert rep["cls"] == "single"
    assert rep["nozzle_contact"] is False
    assert rep["near_nozzle_residue"] is True
    assert rep["nozzle_wet"] is False


def test_pressure_band_completion_reports_conservative_primary_band_for_wide_band():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc.samples = [
        {"pressure": 1.30, "verdict": "single"},
        {"pressure": 1.20, "verdict": "single"},
        {"pressure": 1.10, "verdict": "single"},
    ]
    proc.start_pressure = 1.30
    proc.P_MIN = 0.3
    proc.P_MAX = 5.0
    proc.classify_delay_us = 5850
    proc._pulse_width_us = 1600
    proc._early_stop = False
    proc._stop_reason = None
    proc._terminate_at_pressure = None
    proc.stageChanged = Recorder()
    proc.calibrationError = Recorder()
    proc.calibrationDataUpdated = Recorder()
    proc.calibrationCompleted = Recorder()
    proc.conservative_band_width_threshold_psi = 0.10
    proc.conservative_band_inset_psi = 0.02
    proc._record_error = lambda *args, **kwargs: None
    proc.calibration_manager = SimpleNamespace(
        set_primary_pressure_band=lambda _payload: None
    )
    proc._compute_single_bands = lambda: [[1.10, 1.30]]

    proc.onCalibrationCompleted()

    assert proc.calibrationError.calls == []
    assert proc.calibrationDataUpdated.calls
    result = proc.calibrationDataUpdated.calls[0][0][0]["result"]
    assert result["single_bands"] == [[1.1, 1.3]]
    assert result["raw_primary_band"] == [1.1, 1.3]
    assert result["primary_band"] == [1.12, 1.28]
    assert result["conservative_primary_band_applied"] is True


def test_pressure_band_completion_rejects_single_point_band_by_default():
    proc = PressureBandCalibrationProcess.__new__(PressureBandCalibrationProcess)
    proc.samples = [
        {"pressure": 0.95, "verdict": "multiple"},
        {"pressure": 0.88, "verdict": "single"},
        {"pressure": 0.72, "verdict": "none"},
    ]
    proc.start_pressure = 0.95
    proc.P_MIN = 0.3
    proc.P_MAX = 5.0
    proc.classify_delay_us = 5850
    proc._pulse_width_us = 1600
    proc._early_stop = False
    proc._stop_reason = None
    proc._terminate_at_pressure = None
    proc.stageChanged = Recorder()
    proc.calibrationError = Recorder()
    proc.calibrationDataUpdated = Recorder()
    proc.calibrationCompleted = Recorder()
    proc.min_single_points_per_band = 2
    proc.allow_single_point_band_if_bracketed = False
    proc._record_error = lambda *args, **kwargs: None
    proc._record_decision = lambda *args, **kwargs: None
    proc.calibration_manager = SimpleNamespace(
        set_primary_pressure_band=lambda _payload: (_ for _ in ()).throw(AssertionError("should not set band"))
    )
    proc._compute_single_bands = lambda: [[0.88, 0.88]]

    proc.onCalibrationCompleted()

    assert proc.calibrationError.calls
    assert proc.calibrationDataUpdated.calls == []
    assert proc.calibrationCompleted.calls == []
