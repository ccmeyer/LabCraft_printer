import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import CalibrationManager


class AuditSink:
    def __init__(self, *, fail=False):
        self.fail = bool(fail)
        self.events = []

    def record(self, event_type, summary, details=None, level="info", context=None):
        if self.fail:
            raise RuntimeError("audit unavailable")
        event = {
            "event_type": event_type,
            "summary": summary,
            "details": dict(details or {}),
            "level": level,
            "context": context,
        }
        self.events.append(event)
        return event


class _FakeCalibrationProcess:
    phase_name = "nozzle_focus"

    def __init__(self):
        self.stageChanged = SignalStub()
        self.calibrationCompleted = SignalStub()
        self.calibrationError = SignalStub()
        self.calibrationDataUpdated = SignalStub()
        self.presentImageSignal = SignalStub()
        self.onlineStreamDebugUpdated = SignalStub()
        self.started = False
        self.stopped = False
        self._recorder_process_name = self.__class__.__name__
        self._recorder_phase_name = self.phase_name
        self._recorder_run_dir = "calibration_recordings/run-1"
        self._process_recording_finalized = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def _make_model(audit_sink):
    stock = SimpleNamespace(reagent_name="stock-a")
    printer_head = SimpleNamespace(
        serial="head-1",
        get_stock_solution=lambda: stock,
    )
    return SimpleNamespace(
        record_experiment_audit_event=audit_sink.record,
        experiment_model=SimpleNamespace(get_calibration_file_path=lambda: "calibration.json"),
        rack_model=SimpleNamespace(get_gripper_printer_head=lambda: printer_head),
        droplet_camera_model=SimpleNamespace(get_image_metadata=lambda: (1, 2, 3, 4, 5)),
        machine_model=SimpleNamespace(
            get_current_position_dict=lambda: {"X": 10, "Y": 20, "Z": 30},
            get_print_pulse_width=lambda: 1400,
            get_refuel_pulse_width=lambda: 900,
            get_current_print_pressure=lambda: 1.2,
            get_current_refuel_pressure=lambda: 0.8,
        ),
        calibration_memory_store=None,
    )


def _make_manager(tmp_path, *, audit_fail=False):
    sink = AuditSink(fail=audit_fail)
    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr.model = _make_model(sink)
    mgr.audit_sink = sink
    mgr.data = {"schema_version": 1, "runs": []}
    mgr.calibration_file_path = None
    mgr._run_id = None
    mgr._run_idx = None
    mgr._lock = threading.Lock()
    mgr.calibration_queue = []
    mgr.record_mode_enabled = True
    mgr._process_recorder = None
    mgr.activeCalibration = None
    mgr.calibrationStageChanged = SignalStub()
    mgr.calibrationCompleted = SignalStub()
    mgr.calibrationError = SignalStub()
    mgr.calibrationQueueCompleted = SignalStub()
    mgr.characterizationSummaryUpdated = SignalStub()
    mgr.onlineStreamDebugUpdated = SignalStub()
    mgr.analyzedImageUpdated = SignalStub()
    mgr._reset_calibration_memory_prior_runtime = lambda *a, **k: None
    mgr._reset_online_stream_prior_runtime = lambda *a, **k: None
    mgr._reset_calibration_memory_ui_recommendation_state = lambda *a, **k: None
    mgr._start_calibration_memory_run = lambda *a, **k: None
    mgr._write_calibration_memory_summary = lambda *a, **k: None
    mgr._emit_readiness = lambda *a, **k: None
    mgr._finalized_process_recording_run_dir = None
    mgr.calibration_file_path = str(tmp_path / "calibration.json")
    return mgr


def _seed_open_session(mgr):
    mgr._run_id = "run-1"
    mgr._run_idx = 0
    mgr.data = {
        "schema_version": 1,
        "runs": [
            {
                "run_id": "run-1",
                "steps": {
                    "nozzle_focus": [
                        {
                            "timestamp": "2026-05-24T00:00:00Z",
                            "result": {
                                "status": "ok",
                                "mean_nL": 42.5,
                                "droplet_volumes": [41.0, 42.5, 44.0],
                                "large_nested": {"a": 1, "b": 2},
                            },
                        }
                    ]
                },
                "flat_measurements": [{"id": 1}, {"id": 2}],
            }
        ],
    }


def _install_terminal_stubs(mgr):
    mgr._finalize_process_recording = Mock()
    mgr._build_pending_process_verdict_context = Mock(return_value={"pending": True})
    mgr._record_stream_capture_process_result = Mock()
    mgr._close_process_owned_calibration_memory_session = Mock(return_value=False)
    mgr._cleanup_finished_process = Mock()
    mgr._emit_readiness = Mock()
    mgr._complete_droplet_calibration_sequence_queue_success = Mock()
    mgr._complete_stream_capture_queue_success = Mock()
    mgr._complete_stream_calibration_sequence_queue_success = Mock()
    mgr.has_open_stream_gravimetric_capture = Mock(return_value=False)
    mgr.has_open_droplet_calibration_sequence = Mock(return_value=False)
    mgr.has_open_stream_calibration_sequence = Mock(return_value=False)
    mgr._mark_stream_capture_terminal_state = Mock()
    mgr._mark_droplet_calibration_sequence_terminal_state = Mock()
    mgr._mark_stream_calibration_sequence_terminal_state = Mock()
    mgr.clear_calibration_queue = Mock(side_effect=lambda: mgr.calibration_queue.clear())


def _event_types(mgr):
    return [event["event_type"] for event in mgr.audit_sink.events]


def test_begin_session_records_calibration_session_started(tmp_path):
    mgr = _make_manager(tmp_path)

    mgr.begin_session(str(tmp_path / "calibration.json"), notes="initial pass")

    assert _event_types(mgr) == ["calibration_session_started"]
    event = mgr.audit_sink.events[0]
    assert event["level"] == "info"
    assert event["details"]["calibration_file_path"] == str(tmp_path / "calibration.json")
    assert event["details"]["calibration_run_id"] == mgr._run_id
    assert event["details"]["calibration_run_index"] == 0
    assert event["details"]["printer_head_id"] == "head-1"
    assert event["details"]["stock_solution"] == "stock-a"
    assert event["details"]["settings"]["print_width"] == 1400
    assert event["details"]["artifact_refs"]["calibration_file_path"] == str(tmp_path / "calibration.json")


@pytest.mark.parametrize(
    ("outcome", "level"),
    [
        ("completed", "info"),
        ("stopped", "warning"),
        ("error", "error"),
    ],
)
def test_end_session_records_calibration_session_ended_with_level(tmp_path, outcome, level):
    mgr = _make_manager(tmp_path)
    mgr.begin_session(str(tmp_path / "calibration.json"), notes="session")
    mgr.audit_sink.events.clear()

    mgr.end_session(outcome=outcome, error_message="boom" if outcome == "error" else "")

    assert _event_types(mgr) == ["calibration_session_ended"]
    event = mgr.audit_sink.events[0]
    assert event["level"] == level
    assert event["details"]["outcome"] == outcome
    assert event["details"]["calibration_run_id"] is not None
    assert mgr._run_id is None
    assert mgr._run_idx is None


def test_start_active_calibration_records_process_started(tmp_path):
    mgr = _make_manager(tmp_path)
    _seed_open_session(mgr)
    proc = _FakeCalibrationProcess()
    mgr.activeCalibration = proc
    mgr.clear_pending_process_verdict = Mock()
    mgr._begin_process_recording = Mock(
        side_effect=lambda process_obj: setattr(
            process_obj, "_recorder_run_dir", "calibration_recordings/start-run"
        )
    )

    mgr.start_active_calibration()

    assert proc.started is True
    assert _event_types(mgr) == ["calibration_process_started"]
    event = mgr.audit_sink.events[0]
    assert event["details"]["process_name"] == "_FakeCalibrationProcess"
    assert event["details"]["calibration_phase"] == "nozzle_focus"
    assert event["details"]["artifact_refs"]["process_recording_run_dir"] == "calibration_recordings/start-run"


def test_on_calibration_completed_records_compact_process_completed(tmp_path):
    mgr = _make_manager(tmp_path)
    _seed_open_session(mgr)
    _install_terminal_stubs(mgr)
    proc = _FakeCalibrationProcess()
    mgr.activeCalibration = proc

    mgr.onCalibrationCompleted()

    assert mgr.activeCalibration is None
    assert _event_types(mgr) == ["calibration_process_completed"]
    event = mgr.audit_sink.events[0]
    summary = event["details"]["result_summary"]
    assert event["level"] == "info"
    assert event["details"]["outcome"] == "completed"
    assert summary["step_count"] == 1
    assert summary["flat_measurement_count"] == 2
    assert summary["latest_compact"]["droplet_volumes_count"] == 3
    assert "droplet_volumes" not in summary["latest_compact"]
    assert event["details"]["artifact_refs"]["process_recording_run_dir"] == "calibration_recordings/run-1"
    assert mgr.calibrationCompleted.calls


@pytest.mark.parametrize(
    ("message", "event_type", "level", "outcome"),
    [
        ("boom", "calibration_process_failed", "error", "error"),
        ("Calibration terminated by user", "calibration_process_stopped", "warning", "stopped"),
    ],
)
def test_on_calibration_error_records_failed_or_stopped(tmp_path, message, event_type, level, outcome):
    mgr = _make_manager(tmp_path)
    _seed_open_session(mgr)
    _install_terminal_stubs(mgr)
    mgr.activeCalibration = _FakeCalibrationProcess()

    mgr.onCalibrationError(message)

    assert mgr.activeCalibration is None
    assert _event_types(mgr) == [event_type]
    event = mgr.audit_sink.events[0]
    assert event["level"] == level
    assert event["details"]["outcome"] == outcome
    assert event["details"]["error_message"] == message
    assert mgr.calibrationError.calls[-1][0] == (message,)


def test_stop_records_process_stopped_and_preserves_stop_behavior(tmp_path):
    mgr = _make_manager(tmp_path)
    _seed_open_session(mgr)
    _install_terminal_stubs(mgr)
    proc = _FakeCalibrationProcess()
    mgr.activeCalibration = proc
    mgr._pw_sweep_active = False
    mgr._pw_values = []
    mgr._pw_index = -1
    mgr._cancel_pw_apply_wait = Mock()
    mgr.clear_pending_process_verdict = Mock()

    mgr.stop()

    assert proc.stopped is True
    assert mgr.activeCalibration is None
    assert _event_types(mgr) == ["calibration_process_stopped"]
    event = mgr.audit_sink.events[0]
    assert event["level"] == "warning"
    assert event["details"]["outcome"] == "stopped"
    assert mgr.calibrationStageChanged.calls[-1][0] == ("Calibration stopped", "orange")
    assert mgr.calibrationError.calls[-1][0] == ("Calibration terminated by user",)


def test_audit_failure_does_not_block_calibration_lifecycle(tmp_path):
    mgr = _make_manager(tmp_path, audit_fail=True)

    mgr.begin_session(str(tmp_path / "calibration.json"), notes="audit failure")
    mgr.end_session(outcome="completed")

    _seed_open_session(mgr)
    proc = _FakeCalibrationProcess()
    mgr.activeCalibration = proc
    mgr.clear_pending_process_verdict = Mock()
    mgr._begin_process_recording = Mock()
    mgr.start_active_calibration()
    assert proc.started is True

    _seed_open_session(mgr)
    _install_terminal_stubs(mgr)
    mgr.activeCalibration = _FakeCalibrationProcess()
    mgr.onCalibrationCompleted()
    assert mgr.calibrationCompleted.calls

    _seed_open_session(mgr)
    _install_terminal_stubs(mgr)
    mgr.activeCalibration = _FakeCalibrationProcess()
    mgr.onCalibrationError("boom")
    assert mgr.calibrationError.calls[-1][0] == ("boom",)

    _seed_open_session(mgr)
    _install_terminal_stubs(mgr)
    proc = _FakeCalibrationProcess()
    mgr.activeCalibration = proc
    mgr._pw_sweep_active = False
    mgr._pw_values = []
    mgr._pw_index = -1
    mgr._cancel_pw_apply_wait = Mock()
    mgr.clear_pending_process_verdict = Mock()
    mgr.stop()
    assert proc.stopped is True
