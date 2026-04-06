from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from tests.calibration_test_utils import Recorder, SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs(force=True)

if "Model" not in sys.modules:
    fake_model = types.ModuleType("Model")
    fake_model.Model = object
    fake_model.PrinterHead = object
    fake_model.Slot = object
    sys.modules["Model"] = fake_model

import CalibrationClasses.Model as calibration_model  # noqa: E402
from CalibrationClasses.Model import (  # noqa: E402
    CalibrationManager,
    OnlineStreamCalibrationProcess,
)
from Controller import Controller  # noqa: E402


def _ready_cm():
    return SimpleNamespace(
        get_record_mode_enabled=lambda: True,
        get_nozzle_center=lambda: {"X": 1, "Y": 2, "Z": 3},
        get_pressure_scan_nozzle_center_image_position=lambda: (160, 80),
        get_emergence_time=lambda: 3200,
        _safe_get_stock_solution=lambda: "water",
        _safe_get_printer_head_id=lambda: "head_A",
        model=SimpleNamespace(
            droplet_camera_model=SimpleNamespace(get_image_size=lambda: (320, 320)),
        ),
    )


def _capture_signal(frame):
    class _Signal:
        def __init__(self, payload):
            self.payload = payload
            self.count = 0

        def emit(self, callback):
            self.count += 1
            callback(self.payload)

    return _Signal(frame)


def _flow_proc(tmp_path: Path):
    proc = OnlineStreamCalibrationProcess.__new__(OnlineStreamCalibrationProcess)
    proc._stop_requested = False
    proc._stop_reason = None
    proc._background_capture_completed = True
    proc._orig_settings = {
        "num_droplets": 1,
        "flash_delay": 4300,
        "print_pressure": 0.42,
        "print_width": 1350,
    }
    proc.stock_solution = "water"
    proc.printer_head_id = "head_A"
    proc.emergence_time_us = 3200
    proc.priors = {"source": "default"}
    proc.flow_plan = {
        "delays_us": [3850, 4050],
        "replicates_per_delay": 3,
        "point_count": 2,
    }
    proc.tail_plan = {"coarse_start_delay_us": 7000, "coarse_step_us": 100}
    proc.analysis_config = dict(calibration_model.online_cal_mod.DEFAULT_ONLINE_STREAM_ANALYSIS_CONFIG)
    proc.capture_budget = calibration_model.online_cal_mod.new_online_stream_budget()
    proc._measurement_rows = []
    proc._flow_delay_summaries = []
    proc._current_delay_frame_rows = []
    proc._flow_delay_index = 0
    proc._flow_replicate_index = 0
    proc._current_delay_us = 4050
    proc._attempted_capture_count = 0
    proc._consecutive_failed_delays = 0
    proc._flow_termination_reason = None
    proc._flow_warnings = []
    proc._current_analysis_summary = {}
    proc._current_flow_capture_ref = {}
    proc._current_flow_capture_failure = None
    proc.background_image = np.full((320, 220), 230, dtype=np.uint8)
    proc.flow_frame_image = None
    proc.stageChanged = Recorder()
    proc.calibrationDataUpdated = Recorder()
    proc.calibrationCompleted = Recorder()
    proc.calibrationError = Recorder()
    proc.presentImageSignal = Recorder()
    proc.flowPlanReady = Recorder()
    proc.flowFrameAnalyzed = Recorder()
    proc.repeatReplicate = Recorder()
    proc.nextDelay = Recorder()
    proc.flowAcquisitionFinished = Recorder()
    proc.flowFitReady = Recorder()
    proc.finalize = Recorder()
    proc._restored_settings = False
    proc._flow_fit_result = {}
    proc._flow_fit_warnings = []
    proc._last_capture_refs = {
        "background_image": {
            "capture_id": "cap_bg",
            "image_relpath": "captures/background.png",
            "pair_id": "pair_bg",
        }
    }
    proc._recorder_run_dir = str(tmp_path)
    proc._run_dir = None
    proc._frames_path = None
    proc._plan_snapshot_path = None
    proc._flow_fit_path = None
    proc._plan_snapshot_written = False
    proc._cancel_timeout = lambda timer: None
    proc._start_timeout = lambda *args, **kwargs: None
    proc._record_capture = lambda image, *, role, metadata=None: {
        "capture_id": "cap_flow",
        "capture_index": proc._attempted_capture_count,
        "image_relpath": f"captures/flow_{proc._attempted_capture_count:04d}.png",
        "capture_role": role,
        "metadata": dict(metadata or {}),
    }
    proc.calibration_manager = SimpleNamespace(
        emitSettingsChangeCompleted=lambda *args, **kwargs: None,
        emitCaptureCompleted=lambda *args, **kwargs: None,
        get_pressure_scan_nozzle_center_image_position=lambda: (110, 60),
        captureImageRequested=_capture_signal(np.full((320, 220), 230, dtype=np.uint8)),
    )
    return proc


def test_online_stream_missing_requirements_reports_all_dependencies():
    cm = _ready_cm()
    cm.get_record_mode_enabled = lambda: False
    cm.get_nozzle_center = lambda: None
    cm.get_pressure_scan_nozzle_center_image_position = lambda: None
    cm.get_emergence_time = lambda: None
    cm._safe_get_stock_solution = lambda: ""
    cm._safe_get_printer_head_id = lambda: ""
    cm.model.droplet_camera_model.get_image_size = lambda: (_ for _ in ()).throw(RuntimeError("no camera"))

    missing = OnlineStreamCalibrationProcess.missing_requirements(cm)

    joined = " | ".join(missing).lower()
    assert "record calibration runs enabled" in joined
    assert "machine coords" in joined
    assert "image coords" in joined
    assert "emergence time" in joined
    assert "droplet camera" in joined
    assert "stock solution" in joined
    assert "printer head" in joined


def test_online_stream_missing_requirements_ready_case_is_empty():
    assert OnlineStreamCalibrationProcess.missing_requirements(_ready_cm()) == []


def test_start_online_stream_calibration_uses_try_start_process():
    mgr = CalibrationManager.__new__(CalibrationManager)
    called = {"proc_cls": None}

    def _stub(proc_cls, *args, **kwargs):
        called["proc_cls"] = proc_cls
        return True

    mgr._try_start_process = _stub

    started = CalibrationManager.start_online_stream_calibration(mgr)

    assert called["proc_cls"] is OnlineStreamCalibrationProcess
    assert started is True


def test_controller_start_online_stream_calibration_forwards_to_manager():
    controller = Controller.__new__(Controller)
    called = {"count": 0}
    controller.model = SimpleNamespace(
        calibration_manager=SimpleNamespace(
            start_online_stream_calibration=lambda: called.__setitem__("count", called["count"] + 1)
        )
    )

    Controller.start_online_stream_calibration(controller)

    assert called["count"] == 1


def test_emit_readiness_includes_online_stream_calibration():
    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr.readinessChanged = SignalStub()
    mgr._process_missing = lambda proc_cls, *args, **kwargs: [] if proc_cls is OnlineStreamCalibrationProcess else ["blocked"]

    CalibrationManager._emit_readiness(mgr)

    readiness = mgr.readinessChanged.calls[-1][0][0]
    assert "online_stream_calibration" in readiness
    assert readiness["online_stream_calibration"] == {"ready": True, "missing": []}


def test_online_stream_on_prepare_requests_only_num_droplets_zero():
    proc = OnlineStreamCalibrationProcess.__new__(OnlineStreamCalibrationProcess)
    proc._stop_requested = False
    proc.stageChanged = Recorder()
    proc.finalize = Recorder()
    proc.calibration_manager = SimpleNamespace(emitSettingsChangeCompleted=lambda *args, **kwargs: None)
    captured = {"settings": None, "context": None, "callback": None}

    def _stub(settings, callback, *, context=""):
        captured["settings"] = dict(settings)
        captured["context"] = str(context)
        captured["callback"] = callback

    proc._request_settings_with_recording = _stub

    proc.onPrepare()

    assert captured["settings"] == {"num_droplets": 0}
    assert captured["context"] == "online_stream_prepare_background"


def test_online_stream_on_capture_background_uses_background_capture_attr():
    proc = OnlineStreamCalibrationProcess.__new__(OnlineStreamCalibrationProcess)
    proc._stop_requested = False
    proc.stageChanged = Recorder()
    captured = {"kwargs": None}
    proc._capture_with_policy = lambda **kwargs: captured.__setitem__("kwargs", dict(kwargs))

    proc.onCaptureBackground()

    assert captured["kwargs"] is not None
    assert captured["kwargs"]["set_attr"] == "background_image"


def test_online_stream_plan_flow_phase_writes_plan_snapshot(tmp_path):
    proc = _flow_proc(tmp_path)

    proc.onPlanFlowPhase()

    assert proc.flowPlanReady.calls
    snapshot = json.loads(Path(proc._plan_snapshot_path).read_text(encoding="utf-8"))
    assert snapshot["phase"] == "online_stream_calibration"
    assert snapshot["flow_plan"]["delays_us"] == [3850, 4050]
    assert snapshot["analysis_config"]["attached_bottom_guard_px"] == 96


def test_online_stream_capture_flow_frame_uses_one_printed_attempt_and_consumes_budget_once(tmp_path):
    proc = _flow_proc(tmp_path)
    capture_signal = _capture_signal(None)
    proc.calibration_manager.captureImageRequested = capture_signal

    proc.onCaptureFlowFrame()

    assert capture_signal.count == 1
    assert proc._attempted_capture_count == 1
    assert proc.capture_budget["captures_used"] == 1
    assert proc.capture_budget["captures_remaining_hard"] == 35


def test_online_stream_apply_flow_delay_routes_to_fit_when_delays_are_exhausted(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._flow_delay_index = len(proc.flow_plan["delays_us"])

    proc.onApplyFlowDelay()

    assert proc.flowAcquisitionFinished.calls
    assert proc._flow_termination_reason == "planned_delays_exhausted"


def test_online_stream_analyze_flow_frame_appends_measurement_for_accepted_frame(tmp_path, monkeypatch):
    proc = _flow_proc(tmp_path)
    proc._frames_path = str(tmp_path / "frames.jsonl")
    proc.flow_frame_image = np.full((320, 220), 230, dtype=np.uint8)
    proc._current_flow_capture_ref = {
        "capture_id": "cap_flow_01",
        "image_relpath": "captures/flow_0001.png",
    }

    monkeypatch.setattr(
        calibration_model.online_runtime_mod,
        "analyze_online_stream_frame",
        lambda **kwargs: {
            "summary": {
                "status": "accepted",
                "measurement_qc_pass": True,
                "nozzle_qc_pass": True,
                "silhouette_qc_pass": True,
                "silhouette_status": "ok",
                "failure_reason": None,
                "attached_width_px": 91.5,
                "visible_volume_nl": 12.3,
                "attached_bottom_clearance_px": 150,
                "min_accepted_fluid_distance_from_bottom_px": 150,
                "accepted_component_count": 1,
                "accepted_detached_component_count": 0,
                "detached_near_bottom_warning": False,
                "warnings": [],
                "attached_bottom_guard_hit": False,
            },
            "overlay": None,
        },
    )

    proc.onAnalyzeFlowFrame()

    assert proc.flowFrameAnalyzed.calls
    assert len(proc._measurement_rows) == 1
    lines = Path(proc._frames_path).read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[0])
    assert payload["status"] == "accepted"
    assert payload["visible_volume_nl"] == 12.3


def test_online_stream_analyze_flow_frame_records_rejected_frame_without_measurement(tmp_path, monkeypatch):
    proc = _flow_proc(tmp_path)
    proc._frames_path = str(tmp_path / "frames.jsonl")
    proc.flow_frame_image = np.full((320, 220), 230, dtype=np.uint8)
    proc._current_flow_capture_ref = {
        "capture_id": "cap_flow_02",
        "image_relpath": "captures/flow_0002.png",
    }

    monkeypatch.setattr(
        calibration_model.online_runtime_mod,
        "analyze_online_stream_frame",
        lambda **kwargs: {
            "summary": {
                "status": "rejected_silhouette_qc",
                "measurement_qc_pass": False,
                "nozzle_qc_pass": False,
                "silhouette_qc_pass": False,
                "silhouette_status": "empty_mask",
                "failure_reason": "no pixels remain",
                "attached_width_px": None,
                "visible_volume_nl": None,
                "attached_bottom_clearance_px": None,
                "min_accepted_fluid_distance_from_bottom_px": None,
                "accepted_component_count": 0,
                "accepted_detached_component_count": 0,
                "detached_near_bottom_warning": False,
                "warnings": ["silhouette_qc_failed"],
                "attached_bottom_guard_hit": False,
            },
            "overlay": None,
        },
    )

    proc.onAnalyzeFlowFrame()

    assert proc.flowFrameAnalyzed.calls
    assert proc._measurement_rows == []
    lines = Path(proc._frames_path).read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[0])
    assert payload["status"] == "rejected_silhouette_qc"
    assert payload["warnings"] == ["silhouette_qc_failed"]


def test_online_stream_advance_flow_phase_stops_on_bottom_guard_and_routes_to_fit(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="rejected_bottom_guard",
            delay_us=4050,
            delay_from_emergence_us=850,
            replicate_index=1,
            qc={"measurement_qc_pass": False},
            image_ref={"capture_id": "cap_flow"},
            warnings=["attached_bottom_guard_hit"],
            attached_width_px=89.0,
            visible_volume_nl=12.0,
            attached_bottom_clearance_px=96,
            min_accepted_fluid_distance_from_bottom_px=96,
            accepted_component_count=1,
            accepted_detached_component_count=0,
            detached_near_bottom_warning=False,
            attached_bottom_guard_hit=True,
        )
    ]
    proc._current_analysis_summary = {"status": "rejected_bottom_guard"}

    proc.onAdvanceFlowPhase()

    assert proc.flowAcquisitionFinished.calls
    assert proc._flow_termination_reason == "attached_bottom_guard_hit"


def test_online_stream_on_fit_flow_rate_writes_flow_fit_artifact(tmp_path, monkeypatch):
    proc = _flow_proc(tmp_path)
    proc._flow_fit_path = str(tmp_path / "flow_fit.json")
    proc._measurement_rows = [
        {
            "phase": "flow_rate",
            "delay_us": 3850,
            "delay_from_emergence_us": 650,
            "replicate_index": 1,
            "width_px": 91.5,
            "visible_volume_nl": 12.3,
            "qc_pass": True,
            "image_ref": {"capture_id": "cap_flow_01"},
        }
    ]
    proc._flow_delay_summaries = [
        {
            "delay_us": 3850,
            "delay_from_emergence_us": 650,
            "attempted_replicates": 3,
            "accepted_replicates": 1,
            "rejected_replicates": 2,
            "median_visible_volume_nl": 12.3,
            "median_width_px": 91.5,
            "min_attached_bottom_clearance_px": 150.0,
            "detached_near_bottom_warning": False,
            "delay_accepted": True,
        },
        {
            "delay_us": 4050,
            "delay_from_emergence_us": 850,
            "attempted_replicates": 3,
            "accepted_replicates": 1,
            "rejected_replicates": 2,
            "median_visible_volume_nl": 16.1,
            "median_width_px": 91.0,
            "min_attached_bottom_clearance_px": 145.0,
            "detached_near_bottom_warning": False,
            "delay_accepted": True,
        },
        {
            "delay_us": 4250,
            "delay_from_emergence_us": 1050,
            "attempted_replicates": 3,
            "accepted_replicates": 1,
            "rejected_replicates": 2,
            "median_visible_volume_nl": 20.0,
            "median_width_px": 90.5,
            "min_attached_bottom_clearance_px": 140.0,
            "detached_near_bottom_warning": False,
            "delay_accepted": True,
        },
    ]

    monkeypatch.setattr(
        calibration_model.online_fit_mod,
        "fit_online_stream_flow_phase",
        lambda **kwargs: {
            "fit_status": "warning_min_points_only",
            "accepted_delay_points": [
                {"delay_us": 3850, "delay_from_emergence_us": 650, "median_visible_volume_nl": 12.3}
            ],
            "flow_fit_point_count": 3,
            "flow_rate_nl_per_us": 0.0187,
            "flow_intercept_nl": -1.2,
            "flow_fit_delay_start_from_emergence_us": 650,
            "flow_fit_delay_end_from_emergence_us": 1050,
            "steady_width_baseline_px": 91.0,
            "steady_r2": 0.999,
            "steady_nrmse": 0.01,
            "steady_rate_ci95_low_nl_per_us": 0.0185,
            "steady_rate_ci95_high_nl_per_us": 0.0189,
            "steady_rate_ci95_relative_width": 0.02,
            "flow_fit_outlier_prune_status": "not_needed_too_few_points",
            "flow_fit_dropped_outlier_delay_from_emergence_us": None,
            "warnings": ["flow_fit_min_points_only"],
        },
    )

    proc.onFitFlowRate()

    assert proc.flowFitReady.calls
    artifact = json.loads(Path(proc._flow_fit_path).read_text(encoding="utf-8"))
    assert artifact["fit"]["flow_rate_nl_per_us"] == 0.0187
    assert artifact["warnings"] == ["flow_fit_min_points_only"]


def test_online_stream_on_restore_settings_maps_print_width_to_print_pulse_width():
    proc = OnlineStreamCalibrationProcess.__new__(OnlineStreamCalibrationProcess)
    proc._orig_settings = {
        "num_droplets": 1,
        "flash_delay": 4300,
        "print_pressure": 0.42,
        "print_width": 1350,
    }
    proc._restored_settings = False
    proc.stageChanged = Recorder()
    proc.calibration_manager = SimpleNamespace(emitSettingsChangeCompleted=lambda *args, **kwargs: None)
    captured = {"settings": None, "context": None}

    def _stub(settings, callback, *, context=""):
        captured["settings"] = dict(settings)
        captured["context"] = str(context)

    proc._request_settings_with_recording = _stub

    proc.onRestoreSettings()

    assert captured["settings"] == {
        "num_droplets": 1,
        "flash_delay": 4300,
        "print_pressure": 0.42,
        "print_pulse_width": 1350,
    }
    assert captured["context"] == "online_stream_restore_settings"


def test_online_stream_on_completed_emits_stage4_flow_phase_payload():
    proc = OnlineStreamCalibrationProcess.__new__(OnlineStreamCalibrationProcess)
    proc._stop_requested = False
    proc._background_capture_completed = True
    proc._orig_settings = {
        "print_pressure": 0.42,
        "print_width": 1350,
    }
    proc.stock_solution = "water"
    proc.printer_head_id = "head_A"
    proc.emergence_time_us = 3200
    proc.priors = {"source": "default"}
    proc.flow_plan = {"delays_us": [3850, 4050], "replicates_per_delay": 3}
    proc.tail_plan = {"coarse_start_delay_us": 7000, "coarse_step_us": 100}
    proc._measurement_rows = [
        {
            "phase": "flow_rate",
            "delay_us": 3850,
            "delay_from_emergence_us": 650,
            "replicate_index": 1,
            "width_px": 91.5,
            "visible_volume_nl": 12.3,
            "qc_pass": True,
            "image_ref": {"capture_id": "cap_flow_01"},
        }
    ]
    proc._flow_delay_summaries = [
        {
            "delay_us": 3850,
            "delay_from_emergence_us": 650,
            "attempted_replicates": 3,
            "accepted_replicates": 1,
            "rejected_replicates": 2,
            "median_visible_volume_nl": 12.3,
            "median_width_px": 91.5,
            "min_attached_bottom_clearance_px": 150.0,
            "detached_near_bottom_warning": False,
            "delay_accepted": True,
        },
        {
            "delay_us": 4050,
            "delay_from_emergence_us": 850,
            "attempted_replicates": 3,
            "accepted_replicates": 0,
            "rejected_replicates": 3,
            "median_visible_volume_nl": None,
            "median_width_px": None,
            "min_attached_bottom_clearance_px": None,
            "detached_near_bottom_warning": False,
            "delay_accepted": False,
        },
    ]
    proc._attempted_capture_count = 6
    proc._flow_termination_reason = "repeated_qc_failure"
    proc._flow_warnings = ["repeated_qc_failure"]
    proc._flow_fit_warnings = ["flow_fit_min_points_only"]
    proc._flow_fit_result = {
        "fit_status": "warning_min_points_only",
        "flow_fit_point_count": 3,
        "flow_rate_nl_per_us": 0.0187,
        "flow_intercept_nl": -1.2,
        "flow_fit_delay_start_from_emergence_us": 650,
        "flow_fit_delay_end_from_emergence_us": 1050,
        "steady_width_baseline_px": 91.0,
        "steady_r2": 0.999,
        "steady_nrmse": 0.01,
        "steady_rate_ci95_low_nl_per_us": 0.0185,
        "steady_rate_ci95_high_nl_per_us": 0.0189,
        "steady_rate_ci95_relative_width": 0.02,
        "flow_fit_outlier_prune_status": "not_needed_too_few_points",
        "flow_fit_dropped_outlier_delay_from_emergence_us": None,
        "warnings": ["flow_fit_min_points_only"],
    }
    proc.stageChanged = Recorder()
    proc.calibrationDataUpdated = Recorder()
    proc.calibrationCompleted = Recorder()
    proc.calibrationError = Recorder()

    proc.onCompleted()

    assert proc.calibrationError.calls == []
    assert proc.calibrationCompleted.calls
    payload = proc.calibrationDataUpdated.calls[-1][0][0]
    assert len(payload["measurements"]) == 1
    result = payload["result"]
    assert result["flow_phase"]["status"] == "insufficient_data"
    assert result["flow_phase"]["attempted_capture_count"] == 6
    assert result["flow_phase"]["accepted_delay_count"] == 1
    assert result["flow_phase"]["delay_summaries"][0]["delay_us"] == 3850
    assert result["flow_phase"]["termination_reason"] == "repeated_qc_failure"
    assert result["flow_phase"]["fit_status"] == "warning_min_points_only"
    assert result["flow_phase"]["flow_rate_nl_per_us"] == 0.0187
    assert result["flow_phase"]["fit_warnings"] == ["flow_fit_min_points_only"]
    assert "stage4_flow_fit_partial_result" in result["warnings"]
    assert "insufficient_accepted_delays" in result["warnings"]


def test_online_stream_graceful_stop_does_not_emit_success_payload():
    proc = OnlineStreamCalibrationProcess.__new__(OnlineStreamCalibrationProcess)
    proc._stop_requested = False
    proc._stop_reason = None
    proc.stageChanged = Recorder()
    proc.finalize = Recorder()
    proc.calibrationDataUpdated = Recorder()
    proc.calibrationCompleted = Recorder()
    proc.calibrationError = Recorder()
    proc._background_capture_completed = False
    capture_started = {"value": False}
    proc._capture_with_policy = lambda **kwargs: capture_started.__setitem__("value", True)

    proc.requestGracefulStop("User requested stop")
    proc.onCaptureBackground()
    proc.onCompleted()

    assert proc._stop_requested is True
    assert proc._stop_reason == "User requested stop"
    assert proc.finalize.calls
    assert capture_started["value"] is False
    assert proc.calibrationDataUpdated.calls == []
    assert proc.calibrationCompleted.calls == []
    assert proc.calibrationError.calls[-1][0][0] == "Calibration terminated by user"
