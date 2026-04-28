from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from tests.calibration_test_utils import Recorder, SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

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
            droplet_camera_model=SimpleNamespace(
                get_image_size=lambda: (320, 320),
                get_flash_fault_latched=lambda: False,
                flash_fault_latched=False,
            ),
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
    proc._settings_wait_cancel = None
    proc._pending_terminal_status = None
    proc._pending_terminal_error_message = ""
    proc._restore_in_progress = False
    proc._restore_settings_confirmed = None
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
    proc._prior_resolution = {
        "lookup_performed": False,
        "candidate_found": False,
        "source": "default",
        "aggregation_level": None,
        "pulse_match_type": None,
        "condition_match": "none",
        "source_run_ids": [],
        "applied_flow_start_offset_us": 650,
        "applied_flow_step_us": 57,
        "applied_flow_delay_count": 15,
        "applied_tail_start_offset_us": 3800,
        "applied_tail_coarse_step_us": 100,
        "fallback_reason": "no_prior",
        "warnings": [],
    }
    proc._prior_resolution_artifact = calibration_model.online_cal_mod.build_online_stream_prior_resolution_artifact(
        condition={
            "print_pressure_psi": 0.42,
            "print_pulse_width_us": 1350,
            "emergence_time_us": 3200,
            "stock_solution": "water",
            "printer_head_id": "head_A",
        },
        lookup={
            "target_pulse_width_us": 1350,
            "target_print_pressure_psi": 0.42,
            "looked_up": False,
            "lookup_skipped_reason": "no_prior",
            "candidate_found": False,
            "candidate_prior": {},
        },
        candidate_prior={},
        applied_prior={"source": "default", "flow_start_offset_us": 650, "tail_start_offset_us": 3800},
        fallback_reason="no_prior",
        warnings=[],
    )
    proc.flow_plan = calibration_model.online_cal_mod.build_online_stream_flow_plan(
        emergence_time_us=3200,
        prior={"source": "default"},
    )
    proc.tail_plan = {"coarse_start_delay_us": 7000, "coarse_step_us": 100}
    proc.analysis_config = dict(calibration_model.online_cal_mod.DEFAULT_ONLINE_STREAM_ANALYSIS_CONFIG)
    proc.capture_budget = calibration_model.online_cal_mod.new_online_stream_budget()
    proc._measurement_rows = []
    proc._flow_delay_summaries = []
    proc._flow_mode = "scout"
    proc._flow_delay_sequence = list(proc.flow_plan.get("delays_us") or [])
    proc._flow_target_delay_offsets_from_emergence_us = list(
        proc.flow_plan.get("delay_offsets_from_emergence_us") or []
    )
    proc._flow_captured_delay_offsets_from_emergence_us = []
    proc._flow_scout_boundary_reason = None
    proc._flow_search_boundary_deferred_reason = None
    proc._flow_right_boundary_delay_from_emergence_us = None
    proc._flow_right_boundary_fixed = False
    proc._flow_hard_boundary_delay_from_emergence_us = None
    proc._flow_ci_refinement_count = 0
    proc._flow_fit_stop_reason = None
    proc._flow_preview_fit_result = {}
    proc._current_delay_frame_rows = []
    proc._flow_delay_index = 0
    proc._flow_replicate_index = 0
    proc._current_delay_us = int(proc.flow_plan.get("start_delay_us") or 3850)
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
    proc.tailPlanReady = Recorder()
    proc.tailFrameAnalyzed = Recorder()
    proc.repeatTailReplicate = Recorder()
    proc.nextTailDelay = Recorder()
    proc.tailPhaseFinished = Recorder()
    proc.finalize = Recorder()
    proc.onlineStreamDebugUpdated = Recorder()
    proc._restored_settings = False
    proc._flow_fit_result = {}
    proc._flow_fit_warnings = []
    proc._tail_plan = {}
    proc._tail_mode = "scout"
    proc._tail_delay_sequence = []
    proc._tail_current_delay_us = None
    proc._tail_delay_index = 0
    proc._tail_replicate_index = 0
    proc._tail_current_delay_frame_rows = []
    proc._tail_scout_delay_summaries = []
    proc._tail_backtrack_delay_summaries = []
    proc._tail_landmark_delay_us = None
    proc._tail_landmark_reason = None
    proc._tail_backtrack_left_delay_us = None
    proc._tail_left_bracket_confirmed = False
    proc._tail_left_bracket_extended = False
    proc._tail_backup_landmark_confirmed = False
    proc._tail_backup_landmark_confirmation_reason = None
    proc._tail_coarse_delay_summaries = []
    proc._tail_refine_delay_summaries = []
    proc._tail_last_nontrigger_delay_us = None
    proc._tail_trigger_delay_us = None
    proc._tail_trigger_reason = None
    proc._tail_synthetic_left_bracket_used = False
    proc._tail_phase_status = "not_run"
    proc._tail_termination_reason = None
    proc._tail_start_delay_from_emergence_us = None
    proc._predicted_stream_duration_us = None
    proc._predicted_volume_nl = None
    proc._tail_fit_result = {}
    proc._tail_fit_warnings = []
    proc._tail_segmented_analysis_running = False
    proc._tail_consecutive_failed_delays = 0
    proc._tail_attempted_capture_count = 0
    proc._tail_width_window_state = {}
    proc._current_tail_analysis_summary = {}
    proc._current_tail_capture_ref = {}
    proc._current_tail_capture_failure = None
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
    proc._prior_resolution_path = None
    proc._flow_fit_path = None
    proc._tail_fit_path = None
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


def _set_flow_sequence(proc, offsets_from_emergence_us):
    offsets = [int(value) for value in list(offsets_from_emergence_us or [])]
    start_offset_us = int(offsets[0]) if offsets else int(
        (proc.flow_plan or {}).get("start_offset_from_emergence_us") or 650
    )
    proc.flow_plan = {
        **dict(proc.flow_plan or {}),
        "delay_offsets_from_emergence_us": [start_offset_us],
        "delays_us": [int(proc.emergence_time_us) + int(start_offset_us)],
        "start_offset_from_emergence_us": int(start_offset_us),
        "start_delay_us": int(proc.emergence_time_us) + int(start_offset_us),
        "target_delay_count": max(len(offsets), int((proc.flow_plan or {}).get("target_delay_count") or 20)),
        "point_count": max(len(offsets), int((proc.flow_plan or {}).get("target_delay_count") or 20)),
        "min_accepted_delays": int((proc.flow_plan or {}).get("min_accepted_delays") or 12),
        "max_capture_count": int((proc.flow_plan or {}).get("max_capture_count") or 30),
        "soft_bottom_clearance_px": int((proc.flow_plan or {}).get("soft_bottom_clearance_px") or 150),
        "ci95_relative_width_target": float((proc.flow_plan or {}).get("ci95_relative_width_target") or 0.12),
        "late_coverage_min_delay_us": int((proc.flow_plan or {}).get("late_coverage_min_delay_us") or 2250),
        "late_coverage_min_visible_fluid_clearance_px": int((proc.flow_plan or {}).get("late_coverage_min_visible_fluid_clearance_px") or 300),
        "late_coverage_confidence_min": float((proc.flow_plan or {}).get("late_coverage_confidence_min") or 0.70),
        "extension_confidence_floor": float((proc.flow_plan or {}).get("extension_confidence_floor") or 0.55),
        "safe_densify_window_us": int((proc.flow_plan or {}).get("safe_densify_window_us") or 600),
        "safe_densify_step_us": int((proc.flow_plan or {}).get("safe_densify_step_us") or 50),
        "late_slope_window_points": int((proc.flow_plan or {}).get("late_slope_window_points") or 4),
        "late_slope_max_relative_gap": float((proc.flow_plan or {}).get("late_slope_max_relative_gap") or 0.07),
        "late_slope_residual_trend_max_nl_per_us": float((proc.flow_plan or {}).get("late_slope_residual_trend_max_nl_per_us") or 0.00015),
        "reserved_tail_capture_count": int((proc.flow_plan or {}).get("reserved_tail_capture_count") or 25),
        "ci_extension_step_us": int((proc.flow_plan or {}).get("ci_extension_step_us") or 50),
    }
    proc._flow_delay_sequence = [int(proc.emergence_time_us) + int(offset_us) for offset_us in offsets]
    proc._flow_target_delay_offsets_from_emergence_us = list(offsets)
    proc._flow_delay_index = 0


def _seed_tail_flow_context(proc, *, fit_status: str = "ok", steady_width_baseline_px: float = 74.0):
    proc._flow_fit_result = {
        "fit_status": str(fit_status),
        "steady_width_baseline_px": float(steady_width_baseline_px),
        "flow_rate_nl_per_us": 0.0187,
        "flow_intercept_nl": -1.2,
    }
    proc._flow_delay_summaries = [
        {
            "delay_us": 3850,
            "delay_from_emergence_us": 650,
            "attempted_replicates": 1,
            "accepted_replicates": 1,
            "rejected_replicates": 0,
            "median_width_px": float(steady_width_baseline_px),
            "delay_accepted": True,
            "warnings": [],
        },
        {
            "delay_us": 4050,
            "delay_from_emergence_us": 850,
            "attempted_replicates": 1,
            "accepted_replicates": 1,
            "rejected_replicates": 0,
            "median_width_px": float(steady_width_baseline_px),
            "delay_accepted": True,
            "warnings": [],
        },
        {
            "delay_us": 4250,
            "delay_from_emergence_us": 1050,
            "attempted_replicates": 1,
            "accepted_replicates": 1,
            "rejected_replicates": 0,
            "median_width_px": float(steady_width_baseline_px),
            "delay_accepted": True,
            "warnings": [],
        },
    ]


def _accepted_flow_frame_row(proc, offset_us: int, *, visible_volume_nl: float, width_px: float = 74.0):
    delay_us = int(proc.emergence_time_us) + int(offset_us)
    return calibration_model.online_cal_mod.build_online_stream_frame_row(
        phase="flow_rate",
        status="accepted",
        delay_us=delay_us,
        delay_from_emergence_us=int(offset_us),
        replicate_index=1,
        qc={
            "measurement_qc_pass": True,
            "nozzle_qc_pass": True,
            "silhouette_qc_pass": True,
        },
        warnings=[],
        silhouette_status="ok",
        failure_reason=None,
        attached_width_px=float(width_px),
        visible_volume_nl=float(visible_volume_nl),
        attached_bottom_clearance_px=180.0,
        min_accepted_fluid_distance_from_bottom_px=180.0,
        accepted_component_count=1,
        accepted_detached_component_count=0,
        detached_near_bottom_warning=False,
        near_nozzle_detached_warning=False,
        late_frame_warning=False,
        attached_bottom_guard_hit=False,
    )


def _accepted_tail_frame_row(
    proc,
    offset_us: int,
    *,
    phase: str,
    width_px: float,
    visible_volume_nl: float = 14.0,
    landmark: bool = False,
    **extra,
):
    delay_us = int(proc.emergence_time_us) + int(offset_us)
    return calibration_model.online_cal_mod.build_online_stream_frame_row(
        phase=str(phase),
        status="accepted",
        delay_us=delay_us,
        delay_from_emergence_us=int(offset_us),
        replicate_index=1,
        qc={
            "measurement_qc_pass": True,
            "nozzle_qc_pass": True,
            "silhouette_qc_pass": True,
            "tail_qc_pass": True,
            "tail_width_usable": True,
            "tail_landmark_usable": bool(landmark),
        },
        warnings=[],
        silhouette_status="ok",
        failure_reason=None,
        attached_width_px=float(width_px),
        visible_volume_nl=float(visible_volume_nl),
        attached_bottom_clearance_px=180.0,
        min_accepted_fluid_distance_from_bottom_px=180.0,
        accepted_component_count=1,
        accepted_detached_component_count=0,
        tail_width_usable=True,
        separated_from_nozzle_landmark=bool(landmark),
        tail_landmark_usable=bool(landmark),
        landmark_reason="separated_from_nozzle" if landmark else None,
        detached_near_bottom_warning=False,
        near_nozzle_detached_warning=False,
        late_frame_warning=False,
        attached_bottom_guard_hit=False,
        **dict(extra or {}),
    )


def test_online_stream_missing_requirements_reports_all_dependencies():
    cm = _ready_cm()
    cm.get_record_mode_enabled = lambda: False
    cm.get_pressure_scan_nozzle_center_image_position = lambda: None
    cm.get_emergence_time = lambda: None
    cm._safe_get_stock_solution = lambda: ""
    cm._safe_get_printer_head_id = lambda: ""
    cm.model.droplet_camera_model.get_image_size = lambda: (_ for _ in ()).throw(RuntimeError("no camera"))

    missing = OnlineStreamCalibrationProcess.missing_requirements(cm)

    joined = " | ".join(missing).lower()
    assert "record calibration runs enabled" in joined
    assert "image coords" in joined
    assert "emergence time" in joined
    assert "droplet camera" in joined
    assert "stock solution" in joined
    assert "printer head" in joined


def test_online_stream_missing_requirements_ready_case_is_empty():
    assert OnlineStreamCalibrationProcess.missing_requirements(_ready_cm()) == []


def test_online_stream_missing_requirements_do_not_require_machine_coords():
    cm = _ready_cm()
    cm.get_nozzle_center = lambda: None

    assert OnlineStreamCalibrationProcess.missing_requirements(cm) == []


def test_online_stream_missing_requirements_reports_flash_fault_latched():
    cm = _ready_cm()
    cm.model.droplet_camera_model.get_flash_fault_latched = lambda: True

    missing = OnlineStreamCalibrationProcess.missing_requirements(cm)

    assert "Flash safety fault latched" in missing


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


def test_calibration_manager_rebroadcasts_online_stream_debug_payload():
    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr.onlineStreamDebugUpdated = Recorder()

    CalibrationManager.onOnlineStreamDebugUpdated(
        mgr,
        {"phase_name": "online_stream_calibration", "subphase": "prepare"},
    )

    payload = mgr.onlineStreamDebugUpdated.calls[-1][0][0]
    assert payload["phase_name"] == "online_stream_calibration"
    assert payload["subphase"] == "prepare"


def test_emit_readiness_includes_online_stream_calibration():
    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr.readinessChanged = SignalStub()
    mgr._process_missing = lambda proc_cls, *args, **kwargs: [] if proc_cls is OnlineStreamCalibrationProcess else ["blocked"]

    CalibrationManager._emit_readiness(mgr)

    readiness = mgr.readinessChanged.calls[-1][0][0]
    assert "online_stream_calibration" in readiness
    assert readiness["online_stream_calibration"] == {"ready": True, "missing": []}


def test_try_start_process_blocks_when_stream_capture_session_is_open():
    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr._stream_capture_state = {"status": "running"}
    mgr.calibrationStageChanged = SignalStub()
    mgr.calibrationError = SignalStub()
    mgr._prepare_calibration_memory_prior_application = lambda proc_cls, kwargs: dict(kwargs or {})
    mgr._process_missing = lambda proc_cls, *args, **kwargs: []

    started = CalibrationManager._try_start_process(mgr, OnlineStreamCalibrationProcess)

    assert started is False
    assert "stream gravimetric capture session" in mgr.calibrationError.calls[-1][0][0].lower()

    mgr._stream_capture_state = {"status": "awaiting_mass_entry"}
    started = CalibrationManager._try_start_process(mgr, OnlineStreamCalibrationProcess)

    assert started is False
    assert "stream gravimetric capture session" in mgr.calibrationError.calls[-1][0][0].lower()


def test_try_start_process_allows_stream_capture_internal_queue_step():
    class _StreamCaptureQueueProcess:
        owns_calibration_memory_session = False

        def __init__(self, manager, model, *args, **kwargs):
            self.manager = manager
            self.model = model
            self.args = args
            self.kwargs = dict(kwargs)
            self.stageChanged = SignalStub()
            self.calibrationCompleted = SignalStub()
            self.calibrationError = SignalStub()
            self.calibrationDataUpdated = SignalStub()
            self.presentImageSignal = SignalStub()

    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr._stream_capture_state = {"status": "running"}
    mgr._run_id = None
    mgr._run_idx = None
    mgr.model = SimpleNamespace()
    mgr.calibrationStageChanged = SignalStub()
    mgr.calibrationError = SignalStub()
    mgr._prepare_calibration_memory_prior_application = lambda proc_cls, kwargs: dict(kwargs or {})
    mgr._process_missing = lambda proc_cls, *args, **kwargs: []
    started = []
    mgr.start_active_calibration = lambda: started.append(mgr.activeCalibration)

    started_ok = CalibrationManager._try_start_process(
        mgr,
        _StreamCaptureQueueProcess,
        _allow_stream_capture_session=True,
        _stream_capture_queue_phase="nozzle_position",
    )

    assert started_ok is True
    assert len(started) == 1
    assert isinstance(mgr.activeCalibration, _StreamCaptureQueueProcess)
    assert mgr.activeCalibration.kwargs.get("parent") is mgr
    assert mgr.calibrationError.calls == []


def test_try_start_process_bypass_still_blocks_non_queue_or_non_running_states():
    class _OnlineStreamQueueProcess:
        owns_calibration_memory_session = False
        supports_operator_verdict = False

        def __init__(self, calibration_manager, model, *args, **kwargs):
            self.calibration_manager = calibration_manager
            self.model = model
            self.kwargs = dict(kwargs)
            self.stageChanged = SignalStub()
            self.calibrationCompleted = SignalStub()
            self.calibrationError = SignalStub()
            self.calibrationDataUpdated = SignalStub()
            self.presentImageSignal = SignalStub()

    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr._stream_capture_state = {"status": "running"}
    mgr._run_id = None
    mgr._run_idx = None
    mgr.model = SimpleNamespace()
    mgr.calibrationStageChanged = SignalStub()
    mgr.calibrationError = SignalStub()
    mgr._prepare_calibration_memory_prior_application = lambda proc_cls, kwargs: dict(kwargs or {})
    mgr._process_missing = lambda proc_cls, *args, **kwargs: []
    started_processes = []
    mgr.start_active_calibration = lambda: started_processes.append(mgr.activeCalibration)

    started = CalibrationManager._try_start_process(
        mgr,
        _OnlineStreamQueueProcess,
        _allow_stream_capture_session=True,
        _stream_capture_queue_phase="online_stream_calibration",
    )
    assert started is True
    assert len(started_processes) == 1
    assert isinstance(mgr.activeCalibration, _OnlineStreamQueueProcess)
    assert mgr.calibrationError.calls == []

    class _StreamCaptureQueueProcess:
        pass

    mgr._stream_capture_state = {"status": "awaiting_mass_entry"}
    started = CalibrationManager._try_start_process(
        mgr,
        _StreamCaptureQueueProcess,
        _allow_stream_capture_session=True,
        _stream_capture_queue_phase="nozzle_position",
    )

    assert started is False
    assert "stream gravimetric capture session" in mgr.calibrationError.calls[-1][0][0].lower()


def test_try_start_process_blocks_when_stream_calibration_sequence_is_open():
    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr._stream_capture_state = {"status": "idle"}
    mgr._stream_calibration_sequence_state = {"status": "running"}
    mgr.calibrationStageChanged = SignalStub()
    mgr.calibrationError = SignalStub()
    mgr._prepare_calibration_memory_prior_application = lambda proc_cls, kwargs: dict(kwargs or {})
    mgr._process_missing = lambda proc_cls, *args, **kwargs: []

    started = CalibrationManager._try_start_process(mgr, OnlineStreamCalibrationProcess)

    assert started is False
    assert "stream calibration sequence" in mgr.calibrationError.calls[-1][0][0].lower()


def test_try_start_process_allows_stream_calibration_sequence_internal_queue_step():
    class _SequenceQueueProcess:
        owns_calibration_memory_session = False

        def __init__(self, manager, model, *args, **kwargs):
            self.manager = manager
            self.model = model
            self.kwargs = dict(kwargs)
            self.stageChanged = SignalStub()
            self.calibrationCompleted = SignalStub()
            self.calibrationError = SignalStub()
            self.calibrationDataUpdated = SignalStub()
            self.presentImageSignal = SignalStub()

    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr._stream_capture_state = {"status": "idle"}
    mgr._stream_calibration_sequence_state = {"status": "running"}
    mgr._run_id = None
    mgr._run_idx = None
    mgr.model = SimpleNamespace()
    mgr.calibrationStageChanged = SignalStub()
    mgr.calibrationError = SignalStub()
    mgr._prepare_calibration_memory_prior_application = lambda proc_cls, kwargs: dict(kwargs or {})
    mgr._process_missing = lambda proc_cls, *args, **kwargs: []
    started = []
    mgr.start_active_calibration = lambda: started.append(mgr.activeCalibration)

    started_ok = CalibrationManager._try_start_process(
        mgr,
        _SequenceQueueProcess,
        _allow_stream_calibration_sequence=True,
        _stream_calibration_sequence_phase="online_stream_calibration",
    )

    assert started_ok is True
    assert len(started) == 1
    assert isinstance(mgr.activeCalibration, _SequenceQueueProcess)
    assert mgr.activeCalibration.kwargs.get("parent") is mgr
    assert mgr.calibrationError.calls == []


def test_try_start_process_blocks_when_droplet_calibration_sequence_is_open():
    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr._stream_capture_state = {"status": "idle"}
    mgr._stream_calibration_sequence_state = {"status": "idle"}
    mgr._droplet_calibration_sequence_state = {"status": "running"}
    mgr.calibrationStageChanged = SignalStub()
    mgr.calibrationError = SignalStub()
    mgr._prepare_calibration_memory_prior_application = lambda proc_cls, kwargs: dict(kwargs or {})
    mgr._process_missing = lambda proc_cls, *args, **kwargs: []

    started = CalibrationManager._try_start_process(mgr, OnlineStreamCalibrationProcess)

    assert started is False
    assert "droplet calibration sequence" in mgr.calibrationError.calls[-1][0][0].lower()


def test_try_start_process_allows_droplet_calibration_sequence_internal_queue_step():
    class _SequenceQueueProcess:
        owns_calibration_memory_session = False

        def __init__(self, manager, model, *args, **kwargs):
            self.manager = manager
            self.model = model
            self.kwargs = dict(kwargs)
            self.stageChanged = SignalStub()
            self.calibrationCompleted = SignalStub()
            self.calibrationError = SignalStub()
            self.calibrationDataUpdated = SignalStub()
            self.presentImageSignal = SignalStub()

    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr._stream_capture_state = {"status": "idle"}
    mgr._stream_calibration_sequence_state = {"status": "idle"}
    mgr._droplet_calibration_sequence_state = {"status": "running"}
    mgr._run_id = None
    mgr._run_idx = None
    mgr.model = SimpleNamespace()
    mgr.calibrationStageChanged = SignalStub()
    mgr.calibrationError = SignalStub()
    mgr._prepare_calibration_memory_prior_application = lambda proc_cls, kwargs: dict(kwargs or {})
    mgr._process_missing = lambda proc_cls, *args, **kwargs: []
    started = []
    mgr.start_active_calibration = lambda: started.append(mgr.activeCalibration)

    started_ok = CalibrationManager._try_start_process(
        mgr,
        _SequenceQueueProcess,
        _allow_droplet_calibration_sequence=True,
        _droplet_calibration_sequence_phase="pressure_sweep_characterization",
    )

    assert started_ok is True
    assert len(started) == 1
    assert isinstance(mgr.activeCalibration, _SequenceQueueProcess)
    assert mgr.activeCalibration.kwargs.get("parent") is mgr
    assert mgr.calibrationError.calls == []


def test_should_suppress_process_verdict_includes_droplet_calibration_sequence():
    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr._stream_capture_state = {"status": "idle"}
    mgr._stream_calibration_sequence_state = {"status": "idle"}
    mgr._droplet_calibration_sequence_state = {"status": "running"}

    assert CalibrationManager.should_suppress_process_verdict(mgr) is True


def test_try_start_process_opens_session_before_online_stream_init(monkeypatch):
    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr._stream_capture_state = {}
    mgr._run_id = None
    mgr._run_idx = None
    mgr.model = SimpleNamespace(
        experiment_model=SimpleNamespace(get_calibration_file_path=lambda: "C:/tmp/calibration.json")
    )
    mgr.calibrationStageChanged = SignalStub()
    mgr.calibrationError = SignalStub()
    mgr._prepare_calibration_memory_prior_application = lambda proc_cls, kwargs: dict(kwargs or {})
    mgr._process_missing = lambda proc_cls, *args, **kwargs: []
    mgr.start_active_calibration = lambda: None
    started_session = {}

    def _begin_session(path, notes=None):
        started_session["path"] = path
        started_session["notes"] = notes
        mgr._run_id = "run_auto"
        mgr._run_idx = 0

    def _fake_init(self, calibration_manager, model, *args, **kwargs):
        assert calibration_manager._run_id == "run_auto"
        self.calibration_manager = calibration_manager
        self.model = model
        self.phase_name = "online_stream_calibration"

    mgr.begin_session = _begin_session
    monkeypatch.setattr(OnlineStreamCalibrationProcess, "__init__", _fake_init)

    started = CalibrationManager._try_start_process(mgr, OnlineStreamCalibrationProcess)

    assert started is True
    assert started_session["path"] == "C:/tmp/calibration.json"
    assert "online_stream_calibration" in started_session["notes"]
    assert mgr.activeCalibration._calibration_memory_session_started_by_manager is True
    assert mgr.activeCalibration._calibration_memory_session_run_id == "run_auto"


def test_try_start_process_closes_auto_started_session_when_online_stream_init_fails(monkeypatch):
    mgr = CalibrationManager.__new__(CalibrationManager)
    mgr._stream_capture_state = {}
    mgr._run_id = None
    mgr._run_idx = None
    mgr.model = SimpleNamespace(
        experiment_model=SimpleNamespace(get_calibration_file_path=lambda: "C:/tmp/calibration.json")
    )
    mgr.calibrationStageChanged = SignalStub()
    mgr.calibrationError = SignalStub()
    mgr._prepare_calibration_memory_prior_application = lambda proc_cls, kwargs: dict(kwargs or {})
    mgr._process_missing = lambda proc_cls, *args, **kwargs: []
    mgr.start_active_calibration = lambda: None
    end_calls = []

    def _begin_session(path, notes=None):
        mgr._run_id = "run_auto"
        mgr._run_idx = 0

    def _end_session(*, outcome="completed", error_message="", emit_stage=True):
        end_calls.append(
            {
                "outcome": outcome,
                "error_message": error_message,
                "emit_stage": emit_stage,
            }
        )
        mgr._run_id = None
        mgr._run_idx = None

    def _boom(self, calibration_manager, model, *args, **kwargs):
        raise RuntimeError("constructor failed")

    mgr.begin_session = _begin_session
    mgr.end_session = _end_session
    mgr._warn_calibration_memory = lambda *args, **kwargs: None
    monkeypatch.setattr(OnlineStreamCalibrationProcess, "__init__", _boom)

    started = CalibrationManager._try_start_process(mgr, OnlineStreamCalibrationProcess)

    assert started is False
    assert end_calls[-1]["outcome"] == "error"
    assert end_calls[-1]["emit_stage"] is False
    assert "failed to start" in mgr.calibrationError.calls[-1][0][0].lower()
    assert mgr._run_id is None


def test_online_stream_on_prepare_requests_only_num_droplets_zero():
    proc = OnlineStreamCalibrationProcess.__new__(OnlineStreamCalibrationProcess)
    proc._stop_requested = False
    proc._settings_wait_cancel = None
    proc.stageChanged = Recorder()
    proc.finalize = Recorder()
    proc.calibration_manager = SimpleNamespace(emitSettingsChangeCompleted=lambda *args, **kwargs: None)
    captured = {"settings": None, "context": None, "callback": None, "guard_timeout_ms": None}

    def _stub(settings, callback, *, context="", guard_timeout_ms=None, on_timeout=None):
        captured["settings"] = dict(settings)
        captured["context"] = str(context)
        captured["callback"] = callback
        captured["guard_timeout_ms"] = guard_timeout_ms
        return lambda: None

    proc._request_settings_with_recording = _stub

    proc.onPrepare()

    assert captured["settings"] == {"num_droplets": 0}
    assert captured["context"] == "online_stream_prepare_background"
    assert captured["guard_timeout_ms"] == 10_000


def test_online_stream_prepare_timeout_restores_before_terminal_error():
    proc = OnlineStreamCalibrationProcess.__new__(OnlineStreamCalibrationProcess)
    proc._stop_requested = False
    proc._stop_reason = None
    proc._settings_wait_cancel = None
    proc._pending_terminal_status = None
    proc._pending_terminal_error_message = ""
    proc._restore_in_progress = False
    proc._restore_settings_confirmed = None
    proc._restored_settings = False
    proc._background_capture_completed = False
    proc._orig_settings = {
        "num_droplets": 1,
        "flash_delay": 4300,
        "print_pressure": 0.42,
        "print_width": 1350,
    }
    proc.stageChanged = Recorder()
    proc.finalize = Recorder()
    proc.calibrationDataUpdated = Recorder()
    proc.calibrationCompleted = Recorder()
    proc.calibrationError = Recorder()
    proc.calibration_manager = SimpleNamespace(emitSettingsChangeCompleted=lambda *args, **kwargs: None)
    phase = {"name": "prepare"}
    captured = {}

    def _stub(settings, callback, *, context="", guard_timeout_ms=None, on_timeout=None):
        captured[phase["name"]] = {
            "settings": dict(settings),
            "context": str(context),
            "guard_timeout_ms": guard_timeout_ms,
            "on_timeout": on_timeout,
        }
        if phase["name"] == "restore":
            callback()
        return lambda: None

    proc._request_settings_with_recording = _stub

    proc.onPrepare()
    captured["prepare"]["on_timeout"]()

    assert proc.finalize.calls
    assert proc._pending_terminal_status == "error"
    assert proc.calibrationError.calls == []

    phase["name"] = "restore"
    proc.onRestoreSettings()
    proc.onCompleted()

    assert captured["restore"]["settings"] == {
        "num_droplets": 1,
        "flash_delay": 4300,
        "print_pressure": 0.42,
        "print_pulse_width": 1350,
    }
    assert proc.calibrationCompleted.calls == []
    assert proc.calibrationError.calls[-1][0][0] == (
        "Timed out waiting for online stream background-prepare settings."
    )


def test_online_stream_graceful_stop_cancels_pending_prepare_wait():
    proc = OnlineStreamCalibrationProcess.__new__(OnlineStreamCalibrationProcess)
    proc._stop_requested = False
    proc._stop_reason = None
    proc._settings_wait_cancel = None
    proc._pending_terminal_status = None
    proc._pending_terminal_error_message = ""
    proc._restore_in_progress = False
    proc._restore_settings_confirmed = None
    proc.stageChanged = Recorder()
    proc.finalize = Recorder()
    proc.calibration_manager = SimpleNamespace(emitSettingsChangeCompleted=lambda *args, **kwargs: None)
    cancelled = {"value": False}

    def _stub(settings, callback, *, context="", guard_timeout_ms=None, on_timeout=None):
        return lambda: cancelled.__setitem__("value", True)

    proc._request_settings_with_recording = _stub

    proc.onPrepare()
    proc.requestGracefulStop("User requested stop")

    assert cancelled["value"] is True
    assert proc.finalize.calls
    assert proc._pending_terminal_status == "stopped"


def test_online_stream_on_capture_background_uses_background_capture_attr():
    proc = OnlineStreamCalibrationProcess.__new__(OnlineStreamCalibrationProcess)
    proc._stop_requested = False
    proc.stageChanged = Recorder()
    captured = {"kwargs": None}
    proc._capture_with_policy = lambda **kwargs: captured.__setitem__("kwargs", dict(kwargs))

    proc.onCaptureBackground()

    assert captured["kwargs"] is not None
    assert captured["kwargs"]["set_attr"] == "background_image"


def test_online_stream_background_capture_failure_restores_before_terminal_error():
    proc = OnlineStreamCalibrationProcess.__new__(OnlineStreamCalibrationProcess)
    proc._stop_requested = False
    proc._stop_reason = None
    proc._settings_wait_cancel = None
    proc._pending_terminal_status = None
    proc._pending_terminal_error_message = ""
    proc._restore_in_progress = False
    proc._restore_settings_confirmed = None
    proc._restored_settings = False
    proc._background_capture_completed = False
    proc._orig_settings = {
        "num_droplets": 1,
        "flash_delay": 4300,
        "print_pressure": 0.42,
        "print_width": 1350,
    }
    proc.stageChanged = Recorder()
    proc.finalize = Recorder()
    proc.calibrationDataUpdated = Recorder()
    proc.calibrationCompleted = Recorder()
    proc.calibrationError = Recorder()
    proc.calibration_manager = SimpleNamespace(emitSettingsChangeCompleted=lambda *args, **kwargs: None)
    captured = {"settings": None}

    def _stub(settings, callback, *, context="", guard_timeout_ms=None, on_timeout=None):
        captured["settings"] = dict(settings)
        callback()
        return lambda: None

    proc._request_settings_with_recording = _stub

    proc._on_background_capture_final_failure()

    assert proc.finalize.calls
    assert proc.calibrationError.calls == []

    proc.onRestoreSettings()
    proc.onCompleted()

    assert captured["settings"] == {
        "num_droplets": 1,
        "flash_delay": 4300,
        "print_pressure": 0.42,
        "print_pulse_width": 1350,
    }
    assert proc.calibrationError.calls[-1][0][0] == (
        "Failed to capture online stream calibration background image."
    )


def test_online_stream_plan_flow_phase_writes_plan_snapshot(tmp_path):
    proc = _flow_proc(tmp_path)

    proc.onPlanFlowPhase()

    assert proc.flowPlanReady.calls
    prior_resolution = json.loads(Path(proc._prior_resolution_path).read_text(encoding="utf-8"))
    assert prior_resolution["fallback_reason"] == "no_prior"
    snapshot = json.loads(Path(proc._plan_snapshot_path).read_text(encoding="utf-8"))
    assert snapshot["phase"] == "online_stream_calibration"
    assert snapshot["priors"]["lookup"]["candidate_found"] is False
    assert snapshot["flow_plan"]["search_method"] == "adaptive_visible_span_v1"
    assert snapshot["flow_plan"]["delays_us"] == [3850]
    assert snapshot["flow_plan"]["target_delay_count"] == 20
    assert snapshot["analysis_config"]["attached_bottom_guard_px"] == 96


def test_online_stream_plan_flow_phase_failure_restores_before_terminal_error(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._ensure_flow_paths = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    captured = {"settings": None}

    def _stub(settings, callback, *, context="", guard_timeout_ms=None, on_timeout=None):
        captured["settings"] = dict(settings)
        callback()
        return lambda: None

    proc._request_settings_with_recording = _stub

    proc.onPlanFlowPhase()

    assert proc.finalize.calls
    assert proc.calibrationError.calls == []
    assert proc._pending_terminal_status == "error"

    proc.onRestoreSettings()
    proc.onCompleted()

    assert captured["settings"] == {
        "num_droplets": 1,
        "flash_delay": 4300,
        "print_pressure": 0.42,
        "print_pulse_width": 1350,
    }
    assert proc.calibrationError.calls[-1][0][0] == (
        "Failed to initialize online stream flow artifacts: boom"
    )


def test_online_stream_capture_flow_frame_uses_one_printed_attempt_and_consumes_budget_once(tmp_path):
    proc = _flow_proc(tmp_path)
    capture_signal = _capture_signal(None)
    proc.calibration_manager.captureImageRequested = capture_signal

    proc.onCaptureFlowFrame()

    assert capture_signal.count == 1
    assert proc._attempted_capture_count == 1
    assert proc.capture_budget["captures_used"] == 1
    assert proc.capture_budget["captures_remaining_hard"] == 60


def test_online_stream_capture_flow_frame_refreshes_plan_snapshot_after_budget_use(tmp_path):
    proc = _flow_proc(tmp_path)
    capture_signal = _capture_signal(None)
    proc.calibration_manager.captureImageRequested = capture_signal
    proc._ensure_flow_paths()
    proc._write_plan_snapshot()

    proc.onCaptureFlowFrame()

    snapshot = json.loads(Path(proc._plan_snapshot_path).read_text(encoding="utf-8"))
    assert snapshot["capture_budget"]["captures_used"] == 1
    assert snapshot["capture_budget"]["captures_remaining_hard"] == 60


def test_online_stream_apply_flow_delay_routes_to_fit_when_delays_are_exhausted(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._flow_delay_index = len(proc._flow_delay_sequence)

    proc.onApplyFlowDelay()

    assert proc.flowAcquisitionFinished.calls
    assert proc._flow_termination_reason == "candidate_delays_exhausted"


def test_online_stream_stage_text_uses_operator_facing_flow_and_tail_labels(tmp_path):
    proc = _flow_proc(tmp_path)

    def _stub(
        settings,
        callback,
        *,
        context="",
        guard_timeout_ms=None,
        on_timeout=None,
        timeout_message=None,
    ):
        return lambda: None

    proc._request_guarded_settings_update = _stub

    proc.onApplyFlowDelay()
    assert "flow scout delay=" in proc.stageChanged.calls[-1][0][0]

    proc._tail_plan = {
        "scout_first_delay_us": 4750,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
    }
    proc._tail_delay_sequence = [4750]
    proc._tail_delay_index = 0
    proc._tail_replicate_index = 0
    proc._tail_mode = "scout"

    proc.onApplyTailDelay()
    assert "tail scout delay=" in proc.stageChanged.calls[-1][0][0]

    proc._tail_mode = "backtrack"
    proc._tail_delay_sequence = [4300]
    proc._tail_delay_index = 0
    proc._tail_replicate_index = 0

    proc.onApplyTailDelay()
    assert "tail backtrack delay=" in proc.stageChanged.calls[-1][0][0]


def test_online_stream_apply_tail_delay_scout_only_updates_flash_delay(tmp_path):
    proc = _flow_proc(tmp_path)
    captured = {}

    def _stub(
        settings,
        callback,
        *,
        context="",
        guard_timeout_ms=None,
        on_timeout=None,
        timeout_message=None,
    ):
        captured["settings"] = dict(settings)
        captured["context"] = str(context)
        return lambda: None

    proc._request_guarded_settings_update = _stub
    proc._tail_plan = {
        "scout_first_delay_us": 4750,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
    }
    proc._tail_delay_sequence = [4750]
    proc._tail_delay_index = 0
    proc._tail_replicate_index = 0
    proc._tail_mode = "scout"

    proc.onApplyTailDelay()

    assert captured["settings"] == {"flash_delay": 4750}
    assert captured["context"] == "online_stream_apply_tail_scout_4750"


def test_online_stream_apply_tail_delay_backtrack_only_updates_flash_delay(tmp_path):
    proc = _flow_proc(tmp_path)
    captured = {}

    def _stub(
        settings,
        callback,
        *,
        context="",
        guard_timeout_ms=None,
        on_timeout=None,
        timeout_message=None,
    ):
        captured["settings"] = dict(settings)
        captured["context"] = str(context)
        return lambda: None

    proc._request_guarded_settings_update = _stub
    proc._tail_plan = {
        "scout_first_delay_us": 4300,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
    }
    proc._tail_delay_sequence = [4300]
    proc._tail_delay_index = 0
    proc._tail_replicate_index = 0
    proc._tail_mode = "backtrack"

    proc.onApplyTailDelay()

    assert captured["settings"] == {"flash_delay": 4300}
    assert captured["context"] == "online_stream_apply_tail_backtrack_4300"


def test_online_stream_tail_apply_reuses_flow_num_droplets_arm(tmp_path):
    proc = _flow_proc(tmp_path)
    captured_calls = []

    def _stub(
        settings,
        callback,
        *,
        context="",
        guard_timeout_ms=None,
        on_timeout=None,
        timeout_message=None,
    ):
        captured_calls.append(
            {
                "settings": dict(settings),
                "context": str(context),
            }
        )
        if callable(callback):
            callback()
        return lambda: None

    proc._request_guarded_settings_update = _stub
    proc._flow_delay_sequence = [3850]
    proc._flow_delay_index = 0
    proc._flow_replicate_index = 0
    proc._flow_mode = "scout"
    proc._tail_plan = {
        "scout_first_delay_us": 4750,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
    }
    proc._tail_delay_sequence = [4750]
    proc._tail_delay_index = 0
    proc._tail_replicate_index = 0
    proc._tail_mode = "scout"

    proc.onApplyFlowDelay()
    proc.onApplyTailDelay()

    assert captured_calls[0]["settings"] == {"flash_delay": 3850, "num_droplets": 1}
    assert captured_calls[0]["context"] == "online_stream_apply_flow_scout_3850"
    assert proc._flow_num_droplets_armed is True
    assert captured_calls[1]["settings"] == {"flash_delay": 4750}
    assert captured_calls[1]["context"] == "online_stream_apply_tail_scout_4750"


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
                "attached_width_mode": "lower_consistent_window",
                "visible_volume_nl": 12.3,
                "attached_bottom_clearance_px": 150,
                "min_accepted_fluid_distance_from_bottom_px": 150,
                "accepted_component_count": 1,
                "accepted_detached_component_count": 0,
                "detached_near_bottom_warning": False,
                "warnings": [],
                "attached_bottom_guard_hit": False,
                "adaptive_roi_expansion_triggered": True,
                "adaptive_roi_expansion_sides": ["left"],
                "adaptive_roi_expansion_iterations": 2,
                "adaptive_roi_left_expansion_px": 96,
                "adaptive_roi_right_expansion_px": 0,
                "adaptive_roi_stop_reason": "clearance_ok",
                "base_roi_x0": 440,
                "base_roi_x1": 821,
                "base_corridor_x0": 496,
                "base_corridor_x1": 763,
                "selected_component_corridor_left_clearance_px": 21,
                "selected_component_corridor_right_clearance_px": 94,
            },
            "overlay": None,
        },
    )

    proc.onAnalyzeFlowFrame()

    assert proc.flowFrameAnalyzed.calls
    assert len(proc._measurement_rows) == 1
    assert proc._measurement_rows[0]["nozzle_qc_pass"] is True
    assert proc._measurement_rows[0]["silhouette_qc_pass"] is True
    assert proc._measurement_rows[0]["attached_bottom_clearance_px"] == 150.0
    lines = Path(proc._frames_path).read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[0])
    assert payload["status"] == "accepted"
    assert payload["visible_volume_nl"] == 12.3
    assert payload["adaptive_roi_expansion_triggered"] is True
    assert payload["adaptive_roi_expansion_sides"] == ["left"]
    assert payload["adaptive_roi_left_expansion_px"] == 96
    assert payload["base_corridor_x0"] == 496
    assert payload["selected_component_corridor_left_clearance_px"] == 21


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


def test_online_stream_analyze_flow_frame_records_geometry_rejected_frame_without_measurement(
    tmp_path,
    monkeypatch,
):
    proc = _flow_proc(tmp_path)
    proc._frames_path = str(tmp_path / "frames.jsonl")
    proc.flow_frame_image = np.full((320, 220), 230, dtype=np.uint8)
    proc._current_flow_capture_ref = {
        "capture_id": "cap_flow_geom",
        "image_relpath": "captures/flow_geom.png",
    }

    monkeypatch.setattr(
        calibration_model.online_runtime_mod,
        "analyze_online_stream_frame",
        lambda **kwargs: {
            "summary": {
                "status": "accepted",
                "measurement_qc_pass": True,
                "flow_measurement_usable": False,
                "flow_volume_geometry_ok": False,
                "flow_volume_geometry_reasons": ["attached_lower_centerline_span_high"],
                "attached_volume_geometry_ok": False,
                "detached_volume_geometry_ok": True,
                "attached_lower_centerline_span_px": 86.0,
                "attached_lower_centerline_rms_px": 22.0,
                "detached_geometry_details": [],
                "min_detached_axis_symmetry_score": None,
                "max_detached_local_centerline_span_px": None,
                "max_detached_axis_offset_px": None,
                "nozzle_qc_pass": True,
                "silhouette_qc_pass": True,
                "silhouette_status": "ok",
                "failure_reason": None,
                "attached_width_px": 91.5,
                "attached_width_mode": "lower_consistent_window",
                "visible_volume_nl": 12.3,
                "attached_bottom_clearance_px": 150,
                "min_accepted_fluid_distance_from_bottom_px": 150,
                "accepted_component_count": 1,
                "accepted_detached_component_count": 0,
                "detached_near_bottom_warning": False,
                "near_nozzle_detached_warning": False,
                "late_frame_warning": False,
                "warnings": ["flow_volume_geometry_not_ok"],
                "attached_bottom_guard_hit": False,
                "root_band_width_px": 134.0,
                "root_band_width_iqr_px": 28.0,
                "root_band_half_delta_px": 24.0,
                "selected_band_y0_px": 164,
                "selected_band_y1_px": 204,
                "selected_band_valid_row_count": 40,
                "spread_fallback_triggered": True,
                "candidate_window_count": 4,
            },
            "overlay": None,
        },
    )

    proc.onAnalyzeFlowFrame()

    assert proc.flowFrameAnalyzed.calls
    assert proc._measurement_rows == []
    lines = Path(proc._frames_path).read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[0])
    assert payload["status"] == "accepted"
    assert payload["flow_volume_geometry_ok"] is False
    assert payload["flow_measurement_usable"] is False
    assert payload["attached_lower_centerline_span_px"] == 86.0
    assert payload["attached_width_mode"] == "lower_consistent_window"
    assert payload["root_band_width_px"] == 134.0
    assert payload["selected_band_y0_px"] == 164
    assert payload["selected_band_y1_px"] == 204
    assert payload["spread_fallback_triggered"] is True


def test_online_stream_debug_signal_emits_provisional_flow_point_and_fit(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._flow_preview_fit_result = {"sentinel": True}

    for offset_us in range(650, 1200, 50):
        volume_nl = 0.01 * float(offset_us)
        proc._flow_delay_summaries.append(
            calibration_model.online_cal_mod.summarize_online_stream_flow_delay(
                [_accepted_flow_frame_row(proc, offset_us, visible_volume_nl=volume_nl)]
            )
        )
        proc._measurement_rows.append(
            calibration_model.online_cal_mod.build_online_stream_measurement_row(
                phase="flow_rate",
                delay_us=int(proc.emergence_time_us) + int(offset_us),
                delay_from_emergence_us=int(offset_us),
                replicate_index=1,
                width_px=74.0,
                visible_volume_nl=volume_nl,
                qc_pass=True,
                image_ref={},
                nozzle_qc_pass=True,
                silhouette_qc_pass=True,
                attached_bottom_clearance_px=180.0,
            )
        )

    open_offset_us = 1200
    open_volume_nl = 0.01 * float(open_offset_us)
    proc._current_delay_us = int(proc.emergence_time_us) + int(open_offset_us)
    proc._current_delay_frame_rows = [
        _accepted_flow_frame_row(proc, open_offset_us, visible_volume_nl=open_volume_nl)
    ]
    proc._measurement_rows.append(
        calibration_model.online_cal_mod.build_online_stream_measurement_row(
            phase="flow_rate",
            delay_us=int(proc.emergence_time_us) + int(open_offset_us),
            delay_from_emergence_us=int(open_offset_us),
            replicate_index=1,
            width_px=74.0,
            visible_volume_nl=open_volume_nl,
            qc_pass=True,
            image_ref={},
            nozzle_qc_pass=True,
            silhouette_qc_pass=True,
            attached_bottom_clearance_px=180.0,
        )
    )
    proc._current_analysis_summary = {
        "visible_volume_nl": open_volume_nl,
        "measurement_qc_pass": True,
    }

    proc._emit_online_stream_debug_payload("flow_rate")

    payload = proc.onlineStreamDebugUpdated.calls[-1][0][0]
    flow_plot = payload["flow_plot"]
    assert payload["phase_name"] == "online_stream_calibration"
    assert payload["subphase"] == "flow_rate"
    assert len(flow_plot["points"]) == 12
    assert flow_plot["points"][-1]["x_us"] == open_offset_us
    assert flow_plot["points"][-1]["provisional"] is True
    assert flow_plot["current_frame_point"] == {
        "x_us": open_offset_us,
        "y_nl": open_volume_nl,
        "accepted": True,
    }
    assert flow_plot["fit"] is not None
    assert proc._flow_preview_fit_result == {"sentinel": True}


def test_online_stream_advance_flow_phase_uses_bottom_guard_as_right_boundary_signal(tmp_path):
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

    assert proc.flowAcquisitionFinished.calls == []
    assert proc.nextDelay.calls
    assert proc._flow_termination_reason is None
    assert proc._flow_right_boundary_fixed is True
    assert proc._flow_right_boundary_delay_from_emergence_us == 650
    assert proc._flow_delay_sequence == [3850]


def test_online_stream_advance_flow_phase_ignores_attached_geometry_warning_for_boundary(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=4050,
            delay_from_emergence_us=850,
            replicate_index=1,
            qc={"measurement_qc_pass": True},
            image_ref={"capture_id": "cap_flow_geom_warn"},
            warnings=["attached_lower_centerline_span_high"],
            attached_width_px=89.0,
            visible_volume_nl=12.0,
            attached_bottom_clearance_px=420,
            min_accepted_fluid_distance_from_bottom_px=420,
            accepted_component_count=1,
            accepted_detached_component_count=0,
            detached_near_bottom_warning=False,
            attached_bottom_guard_hit=False,
            attached_lower_centerline_span_px=50.1,
            flow_volume_geometry_ok=True,
            flow_volume_geometry_warnings=["attached_lower_centerline_span_high"],
            flow_measurement_usable=True,
        )
    ]
    proc._current_analysis_summary = {
        "status": "accepted",
        "measurement_qc_pass": True,
        "flow_volume_geometry_ok": True,
        "flow_measurement_usable": True,
    }

    proc.onAdvanceFlowPhase()

    assert proc.flowAcquisitionFinished.calls == []
    assert proc.nextDelay.calls
    assert proc._flow_termination_reason is None
    assert proc._flow_right_boundary_fixed is False
    assert proc._flow_scout_boundary_reason is None
    assert proc._flow_delay_sequence == [4150]
    assert proc._flow_delay_summaries[-1]["flow_volume_geometry_warnings"] == [
        "attached_lower_centerline_span_high"
    ]


def test_online_stream_advance_flow_phase_defers_attached_geometry_boundary_before_late_coverage(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=4050,
            delay_from_emergence_us=850,
            replicate_index=1,
            qc={"measurement_qc_pass": True},
            image_ref={"capture_id": "cap_flow_geom"},
            warnings=["flow_volume_geometry_not_ok"],
            attached_width_px=89.0,
            visible_volume_nl=12.0,
            attached_bottom_clearance_px=420,
            min_accepted_fluid_distance_from_bottom_px=420,
            accepted_component_count=1,
            accepted_detached_component_count=0,
            detached_near_bottom_warning=False,
            attached_bottom_guard_hit=False,
            flow_volume_geometry_ok=False,
            flow_volume_geometry_reasons=["attached_lower_centerline_span_high"],
            flow_measurement_usable=False,
        )
    ]
    proc._current_analysis_summary = {
        "status": "accepted",
        "measurement_qc_pass": True,
        "flow_volume_geometry_ok": False,
        "flow_measurement_usable": False,
    }

    proc.onAdvanceFlowPhase()

    assert proc.flowAcquisitionFinished.calls == []
    assert proc.nextDelay.calls
    assert proc._flow_termination_reason is None
    assert proc._flow_right_boundary_fixed is False
    assert proc._flow_scout_boundary_reason is None
    assert proc._flow_search_boundary_deferred_reason == "attached_geometry_precoverage"
    assert proc._flow_delay_sequence == [4150]
    assert "flow_geometry_boundary_triggered" in proc._flow_warnings
    assert "flow_volume_geometry_not_ok" in proc._flow_warnings


def test_online_stream_advance_flow_phase_defers_detached_only_geometry_boundary_before_late_coverage(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=4050,
            delay_from_emergence_us=850,
            replicate_index=1,
            qc={"measurement_qc_pass": True},
            image_ref={"capture_id": "cap_flow_geom_detached"},
            warnings=["flow_volume_geometry_not_ok"],
            attached_width_px=89.0,
            visible_volume_nl=12.0,
            attached_bottom_clearance_px=420,
            min_accepted_fluid_distance_from_bottom_px=420,
            accepted_component_count=2,
            accepted_detached_component_count=1,
            detached_near_bottom_warning=False,
            attached_bottom_guard_hit=False,
            flow_volume_geometry_ok=False,
            flow_volume_geometry_reasons=["detached_01:detached_local_centerline_span_high"],
            flow_measurement_usable=False,
        )
    ]
    proc._current_analysis_summary = {
        "status": "accepted",
        "measurement_qc_pass": True,
        "flow_volume_geometry_ok": False,
        "flow_measurement_usable": False,
    }

    proc.onAdvanceFlowPhase()

    assert proc.flowAcquisitionFinished.calls == []
    assert proc.nextDelay.calls
    assert proc._flow_termination_reason is None
    assert proc._flow_right_boundary_fixed is False
    assert proc._flow_scout_boundary_reason is None
    assert proc._flow_search_boundary_deferred_reason == "detached_geometry_precoverage"
    assert proc._flow_delay_sequence == [4150]
    assert "flow_geometry_boundary_triggered" in proc._flow_warnings
    assert "flow_volume_geometry_not_ok" in proc._flow_warnings
    payload = proc._build_online_stream_flow_phase_payload()
    assert payload["search_boundary_deferred_reason"] == "detached_geometry_precoverage"


def test_online_stream_advance_flow_phase_uses_detached_only_geometry_as_search_boundary_after_late_coverage(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._flow_delay_summaries = [
        {
            "delay_us": 5550,
            "delay_from_emergence_us": 2350,
            "delay_accepted": True,
            "late_coverage_candidate": True,
            "flow_point_confidence": 0.92,
            "flow_optical_confidence_active": True,
            "min_attached_bottom_clearance_px": 260,
            "min_accepted_fluid_distance_from_bottom_px": 260,
            "warnings": [],
        }
    ]
    proc._current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=5650,
            delay_from_emergence_us=2450,
            replicate_index=1,
            qc={"measurement_qc_pass": True},
            image_ref={"capture_id": "cap_flow_geom_detached_late"},
            warnings=["flow_volume_geometry_not_ok"],
            attached_width_px=89.0,
            visible_volume_nl=22.0,
            attached_bottom_clearance_px=240,
            min_accepted_fluid_distance_from_bottom_px=240,
            accepted_component_count=2,
            accepted_detached_component_count=1,
            detached_near_bottom_warning=False,
            attached_bottom_guard_hit=False,
            flow_volume_geometry_ok=False,
            flow_volume_geometry_reasons=["detached_01:detached_local_centerline_span_high"],
            flow_measurement_usable=False,
        )
    ]
    proc._current_analysis_summary = {
        "status": "accepted",
        "measurement_qc_pass": True,
        "flow_volume_geometry_ok": False,
        "flow_measurement_usable": False,
    }

    proc.onAdvanceFlowPhase()

    assert proc._flow_right_boundary_fixed is True
    assert proc._flow_scout_boundary_reason == "geometry_not_axisymmetric"
    assert proc._flow_right_boundary_delay_from_emergence_us == 2350


def test_online_stream_advance_flow_phase_uses_attached_geometry_as_search_boundary_after_late_coverage(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._flow_delay_summaries = [
        {
            "delay_us": 5550,
            "delay_from_emergence_us": 2350,
            "delay_accepted": True,
            "late_coverage_candidate": True,
            "flow_point_confidence": 0.92,
            "flow_optical_confidence_active": True,
            "min_attached_bottom_clearance_px": 260,
            "min_accepted_fluid_distance_from_bottom_px": 260,
            "warnings": [],
        }
    ]
    proc._current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=5650,
            delay_from_emergence_us=2450,
            replicate_index=1,
            qc={"measurement_qc_pass": True},
            image_ref={"capture_id": "cap_flow_geom_attached_late"},
            warnings=["flow_volume_geometry_not_ok"],
            attached_width_px=89.0,
            visible_volume_nl=22.0,
            attached_bottom_clearance_px=240,
            min_accepted_fluid_distance_from_bottom_px=240,
            accepted_component_count=1,
            accepted_detached_component_count=0,
            detached_near_bottom_warning=False,
            attached_bottom_guard_hit=False,
            flow_volume_geometry_ok=False,
            flow_volume_geometry_reasons=["attached_lower_centerline_span_high"],
            flow_measurement_usable=False,
        )
    ]
    proc._current_analysis_summary = {
        "status": "accepted",
        "measurement_qc_pass": True,
        "flow_volume_geometry_ok": False,
        "flow_measurement_usable": False,
    }

    proc.onAdvanceFlowPhase()

    assert proc._flow_right_boundary_fixed is True
    assert proc._flow_scout_boundary_reason == "geometry_not_axisymmetric"
    assert proc._flow_right_boundary_delay_from_emergence_us == 2350


def test_online_stream_advance_flow_phase_advances_after_one_fully_failed_delay_when_enough_points_remain(tmp_path):
    proc = _flow_proc(tmp_path)
    _set_flow_sequence(proc, [650, 850, 1050, 1250])
    proc._ensure_flow_paths()
    proc._write_plan_snapshot()
    proc.capture_budget = calibration_model.online_cal_mod.consume_online_stream_budget(
        proc.capture_budget,
        phase="flow_phase",
        count=1,
    )
    proc._attempted_capture_count = 1
    proc._flow_replicate_index = 0
    proc._current_delay_us = 4050
    proc._current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="rejected_measurement_qc",
            delay_us=4050,
            delay_from_emergence_us=850,
            replicate_index=1,
            qc={"measurement_qc_pass": False},
            image_ref={"capture_id": "cap_flow_01"},
            warnings=["measurement_qc_failed"],
            attached_width_px=None,
            visible_volume_nl=None,
            attached_bottom_clearance_px=None,
            min_accepted_fluid_distance_from_bottom_px=None,
            accepted_component_count=0,
            accepted_detached_component_count=0,
            detached_near_bottom_warning=False,
            attached_bottom_guard_hit=False,
        ),
    ]
    proc._current_analysis_summary = {"status": "rejected_measurement_qc"}

    proc.onAdvanceFlowPhase()

    assert proc.flowAcquisitionFinished.calls == []
    assert proc.nextDelay.calls
    assert proc.repeatReplicate.calls == []
    assert proc._flow_termination_reason is None
    assert proc._flow_delay_sequence == [4150]


def test_online_stream_advance_flow_phase_keeps_sampling_when_twelve_accepted_delays_are_not_yet_available(tmp_path):
    proc = _flow_proc(tmp_path)
    _set_flow_sequence(proc, [650, 850, 1050, 1250])
    proc._flow_replicate_index = 0
    proc._current_delay_us = 4250
    proc._flow_delay_summaries = [
        {
            "delay_us": 3850,
            "delay_from_emergence_us": 650,
            "attempted_replicates": 1,
            "accepted_replicates": 0,
            "rejected_replicates": 1,
            "median_visible_volume_nl": None,
            "median_width_px": None,
            "min_attached_bottom_clearance_px": None,
            "detached_near_bottom_warning": False,
            "delay_accepted": False,
            "attached_bottom_guard_hit": False,
            "warnings": [],
        },
        {
            "delay_us": 4050,
            "delay_from_emergence_us": 850,
            "attempted_replicates": 1,
            "accepted_replicates": 0,
            "rejected_replicates": 1,
            "median_visible_volume_nl": None,
            "median_width_px": None,
            "min_attached_bottom_clearance_px": None,
            "detached_near_bottom_warning": False,
            "delay_accepted": False,
            "attached_bottom_guard_hit": False,
            "warnings": [],
        },
    ]
    proc._current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=4250,
            delay_from_emergence_us=1050,
            replicate_index=1,
            qc={"measurement_qc_pass": True},
            image_ref={"capture_id": "cap_flow_11"},
            warnings=[],
            attached_width_px=91.2,
            visible_volume_nl=12.1,
            attached_bottom_clearance_px=150,
            min_accepted_fluid_distance_from_bottom_px=150,
            accepted_component_count=1,
            accepted_detached_component_count=0,
            detached_near_bottom_warning=False,
            attached_bottom_guard_hit=False,
        ),
    ]
    proc._current_analysis_summary = {"status": "accepted"}

    proc.onAdvanceFlowPhase()

    assert proc.flowAcquisitionFinished.calls == []
    assert proc.nextDelay.calls
    assert proc._flow_termination_reason is None


def test_flow_ci_target_requires_target_count_late_coverage_and_late_slope_stability(tmp_path):
    proc = _flow_proc(tmp_path)

    assert proc._flow_ci_target_met(
        {
            "fit_status": "ok",
            "accepted_delay_point_count": 12,
            "steady_rate_ci95_relative_width": 0.05,
            "late_coverage_reached": True,
            "late_slope_stable": True,
        }
    ) is False
    assert proc._flow_ci_target_met(
        {
            "fit_status": "ok",
            "accepted_delay_point_count": 20,
            "steady_rate_ci95_relative_width": 0.05,
            "late_coverage_reached": False,
            "late_slope_stable": True,
        }
    ) is False
    assert proc._flow_ci_target_met(
        {
            "fit_status": "ok",
            "accepted_delay_point_count": 20,
            "steady_rate_ci95_relative_width": 0.05,
            "late_coverage_reached": True,
            "late_slope_stable": False,
        }
    ) is False
    assert proc._flow_ci_target_met(
        {
            "fit_status": "ok",
            "accepted_delay_point_count": 20,
            "steady_rate_ci95_relative_width": 0.05,
            "late_coverage_reached": True,
            "late_slope_stable": True,
        }
    ) is True


def test_online_stream_advance_flow_phase_warns_on_single_active_low_confidence_delay_without_stopping(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._flow_mode = "scout"
    proc._flow_delay_summaries = [
        {
            "delay_us": 3850,
            "delay_from_emergence_us": 650,
            "delay_accepted": True,
            "flow_point_confidence": 0.92,
            "flow_optical_confidence_active": True,
            "min_attached_bottom_clearance_px": 420,
            "min_accepted_fluid_distance_from_bottom_px": 420,
            "warnings": [],
        },
    ]
    proc._current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=3950,
            delay_from_emergence_us=750,
            replicate_index=1,
            qc={"measurement_qc_pass": True},
            image_ref={"capture_id": "cap_flow_conf"},
            warnings=[],
            attached_width_px=90.0,
            visible_volume_nl=12.8,
            attached_bottom_clearance_px=390,
            min_accepted_fluid_distance_from_bottom_px=390,
            flow_point_confidence=0.40,
            flow_optical_confidence_active=True,
            flow_volume_geometry_ok=True,
            flow_measurement_usable=True,
            attached_bottom_guard_hit=False,
            detached_near_bottom_warning=False,
        )
    ]
    proc._current_analysis_summary = {"status": "accepted"}

    proc.onAdvanceFlowPhase()

    assert proc._flow_scout_boundary_reason is None
    assert proc._flow_right_boundary_fixed is False
    assert getattr(proc, "_flow_confidence_boundary_delay_from_emergence_us", None) is None
    assert "flow_low_confidence_warning" in proc._flow_warnings
    assert proc._flow_delay_sequence == [int(proc.emergence_time_us) + 850]


def test_online_stream_advance_flow_phase_keeps_scouting_after_volume_incomplete_delay(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._flow_mode = "scout"
    proc._current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=3850,
            delay_from_emergence_us=650,
            replicate_index=1,
            qc={"measurement_qc_pass": True},
            image_ref={"capture_id": "cap_flow_incomplete"},
            warnings=["flow_volume_incomplete"],
            attached_width_px=90.0,
            visible_volume_nl=12.8,
            attached_bottom_clearance_px=260,
            min_accepted_fluid_distance_from_bottom_px=260,
            flow_point_confidence=0.90,
            flow_optical_confidence_active=True,
            flow_volume_geometry_ok=True,
            flow_volume_complete_ok=False,
            flow_volume_completeness_reasons=["material_plausible_unaccepted_detached"],
            plausible_unaccepted_component_count=1,
            plausible_unaccepted_visible_volume_nl=1.4,
            flow_measurement_usable=False,
            attached_bottom_guard_hit=False,
            detached_near_bottom_warning=False,
        )
    ]
    proc._current_analysis_summary = {"status": "accepted"}

    proc.onAdvanceFlowPhase()

    assert proc._flow_scout_boundary_reason is None
    assert proc._flow_right_boundary_fixed is False
    assert "flow_volume_incomplete" in proc._flow_warnings
    assert proc._flow_delay_summaries[0]["volume_incomplete_rejected_replicates"] == 1
    assert proc._flow_delay_sequence == [int(proc.emergence_time_us) + 750]


def test_online_stream_advance_flow_phase_uses_confidence_floor_to_stop_extending_after_two_active_low_confidence_delays(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._flow_mode = "scout"
    proc._flow_delay_summaries = [
        {
            "delay_us": 3850,
            "delay_from_emergence_us": 650,
            "delay_accepted": True,
            "flow_point_confidence": 0.92,
            "flow_optical_confidence_active": True,
            "min_attached_bottom_clearance_px": 420,
            "min_accepted_fluid_distance_from_bottom_px": 420,
            "warnings": [],
        },
        {
            "delay_us": 3950,
            "delay_from_emergence_us": 750,
            "delay_accepted": True,
            "flow_point_confidence": 0.90,
            "flow_optical_confidence_active": True,
            "min_attached_bottom_clearance_px": 360,
            "min_accepted_fluid_distance_from_bottom_px": 360,
            "warnings": [],
        },
        {
            "delay_us": 4050,
            "delay_from_emergence_us": 850,
            "delay_accepted": True,
            "flow_point_confidence": 0.88,
            "flow_optical_confidence_active": True,
            "min_attached_bottom_clearance_px": 290,
            "min_accepted_fluid_distance_from_bottom_px": 290,
            "warnings": [],
        },
        {
            "delay_us": 4150,
            "delay_from_emergence_us": 950,
            "delay_accepted": True,
            "flow_point_confidence": 0.40,
            "flow_optical_confidence_active": True,
            "min_attached_bottom_clearance_px": 260,
            "min_accepted_fluid_distance_from_bottom_px": 260,
            "warnings": [],
        },
    ]
    proc._flow_captured_delay_offsets_from_emergence_us = [650, 750, 850, 950]
    proc._current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=4250,
            delay_from_emergence_us=1050,
            replicate_index=1,
            qc={"measurement_qc_pass": True},
            image_ref={"capture_id": "cap_flow_conf"},
            warnings=[],
            attached_width_px=90.0,
            visible_volume_nl=12.8,
            attached_bottom_clearance_px=240,
            min_accepted_fluid_distance_from_bottom_px=240,
            flow_point_confidence=0.35,
            flow_optical_confidence_active=True,
            flow_volume_geometry_ok=True,
            flow_measurement_usable=True,
            attached_bottom_guard_hit=False,
            detached_near_bottom_warning=False,
        )
    ]
    proc._current_analysis_summary = {"status": "accepted"}

    proc.onAdvanceFlowPhase()

    assert proc._flow_scout_boundary_reason == "confidence_low"
    assert proc._flow_right_boundary_fixed is True
    assert proc._flow_right_boundary_delay_from_emergence_us == 850
    assert getattr(proc, "_flow_confidence_boundary_delay_from_emergence_us", None) == 1050
    assert proc._flow_target_delay_offsets_from_emergence_us == [650, 700, 750, 800, 850]
    assert proc._flow_delay_sequence == [int(proc.emergence_time_us) + 800]


def test_online_stream_advance_flow_phase_soft_boundary_span_fill_starts_from_latest_missing_target(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._flow_mode = "scout"
    prior_offsets = list(range(650, 2150, 100))
    proc._flow_delay_summaries = [
        {
            "delay_us": int(proc.emergence_time_us) + int(offset_us),
            "delay_from_emergence_us": int(offset_us),
            "delay_accepted": True,
            "flow_point_confidence": 0.95,
            "flow_optical_confidence_active": False,
            "min_attached_bottom_clearance_px": 420,
            "min_accepted_fluid_distance_from_bottom_px": 420,
            "warnings": [],
        }
        for offset_us in prior_offsets
    ]
    proc._flow_captured_delay_offsets_from_emergence_us = list(prior_offsets)
    proc._current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=int(proc.emergence_time_us) + 2150,
            delay_from_emergence_us=2150,
            replicate_index=1,
            qc={"measurement_qc_pass": True},
            image_ref={"capture_id": "cap_flow_soft_boundary"},
            warnings=[],
            attached_width_px=90.0,
            visible_volume_nl=24.5,
            attached_bottom_clearance_px=120,
            min_accepted_fluid_distance_from_bottom_px=120,
            flow_point_confidence=0.90,
            flow_optical_confidence_active=False,
            flow_volume_geometry_ok=True,
            flow_measurement_usable=True,
            attached_bottom_guard_hit=False,
            detached_near_bottom_warning=False,
        )
    ]
    proc._current_analysis_summary = {"status": "accepted"}

    proc.onAdvanceFlowPhase()

    expected_targets = calibration_model.online_cal_mod.build_online_stream_flow_target_offsets(
        start_offset_us=650,
        end_offset_us=2150,
        target_delay_count=int(proc._flow_target_delay_count()),
    )
    assert proc._flow_mode == "span_fill"
    assert proc._flow_scout_boundary_reason == "soft_bottom_clearance"
    assert proc._flow_right_boundary_delay_from_emergence_us == 2150
    assert proc._flow_target_delay_offsets_from_emergence_us == expected_targets
    assert proc._flow_delay_sequence == [int(proc.emergence_time_us) + 2071]


def test_online_stream_advance_flow_phase_span_fill_walks_back_through_late_targets(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._flow_mode = "scout"
    prior_offsets = list(range(650, 2150, 100))
    proc._flow_delay_summaries = [
        {
            "delay_us": int(proc.emergence_time_us) + int(offset_us),
            "delay_from_emergence_us": int(offset_us),
            "delay_accepted": True,
            "flow_point_confidence": 0.95,
            "flow_optical_confidence_active": False,
            "min_attached_bottom_clearance_px": 420,
            "min_accepted_fluid_distance_from_bottom_px": 420,
            "warnings": [],
        }
        for offset_us in prior_offsets
    ]
    proc._flow_captured_delay_offsets_from_emergence_us = list(prior_offsets)
    proc._current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=int(proc.emergence_time_us) + 2150,
            delay_from_emergence_us=2150,
            replicate_index=1,
            qc={"measurement_qc_pass": True},
            image_ref={"capture_id": "cap_flow_soft_boundary"},
            warnings=[],
            attached_width_px=90.0,
            visible_volume_nl=24.5,
            attached_bottom_clearance_px=120,
            min_accepted_fluid_distance_from_bottom_px=120,
            flow_point_confidence=0.90,
            flow_optical_confidence_active=False,
            flow_volume_geometry_ok=True,
            flow_measurement_usable=True,
            attached_bottom_guard_hit=False,
            detached_near_bottom_warning=False,
        )
    ]
    proc._current_analysis_summary = {"status": "accepted"}

    proc.onAdvanceFlowPhase()

    assert proc._flow_mode == "span_fill"
    assert proc._flow_delay_sequence == [int(proc.emergence_time_us) + 2071]

    proc._current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=int(proc.emergence_time_us) + 2071,
            delay_from_emergence_us=2071,
            replicate_index=1,
            qc={"measurement_qc_pass": True},
            image_ref={"capture_id": "cap_flow_span_fill_late"},
            warnings=[],
            attached_width_px=90.0,
            visible_volume_nl=23.8,
            attached_bottom_clearance_px=170,
            min_accepted_fluid_distance_from_bottom_px=170,
            flow_point_confidence=0.90,
            flow_optical_confidence_active=False,
            flow_volume_geometry_ok=True,
            flow_measurement_usable=True,
            attached_bottom_guard_hit=False,
            detached_near_bottom_warning=False,
        )
    ]
    proc._current_analysis_summary = {"status": "accepted"}

    proc.onAdvanceFlowPhase()

    assert proc._flow_mode == "span_fill"
    assert proc._flow_delay_sequence == [int(proc.emergence_time_us) + 1992]


def test_online_stream_advance_flow_phase_does_not_preserve_tail_budget_before_late_coverage_or_boundary(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._flow_mode = "scout"
    proc.capture_budget["captures_used"] = 34
    proc.capture_budget["captures_remaining_nominal"] = 23
    proc.capture_budget["captures_remaining_hard"] = 29
    proc.capture_budget["exhausted"] = False
    proc._flow_delay_summaries = [
        {
            "delay_us": 3850 + (50 * idx),
            "delay_from_emergence_us": 650 + (50 * idx),
            "delay_accepted": True,
            "flow_point_confidence": 0.92,
            "flow_optical_confidence_active": True,
            "min_attached_bottom_clearance_px": 420,
            "min_accepted_fluid_distance_from_bottom_px": 420,
            "warnings": [],
        }
        for idx in range(11)
    ]
    proc._compute_flow_preview_fit_result = lambda: {
        "fit_status": "ok",
        "accepted_delay_point_count": 12,
        "steady_rate_ci95_relative_width": 0.18,
        "late_coverage_reached": False,
        "late_slope_stable": False,
    }
    proc._current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=4400,
            delay_from_emergence_us=1200,
            replicate_index=1,
            qc={"measurement_qc_pass": True},
            image_ref={"capture_id": "cap_flow_budget"},
            warnings=[],
            attached_width_px=90.0,
            visible_volume_nl=17.8,
            attached_bottom_clearance_px=260,
            min_accepted_fluid_distance_from_bottom_px=260,
            flow_point_confidence=0.88,
            flow_optical_confidence_active=True,
            flow_volume_geometry_ok=True,
            flow_volume_complete_ok=True,
            flow_measurement_usable=True,
            attached_bottom_guard_hit=False,
            detached_near_bottom_warning=False,
        )
    ]
    proc._current_analysis_summary = {"status": "accepted"}
    proc._preview_required_tail_capture_count = lambda fit_result=None: 31

    proc.onAdvanceFlowPhase()

    assert proc._flow_termination_reason is None
    assert "tail_budget_preserved_early_finalize" not in proc._flow_warnings
    assert proc.flowAcquisitionFinished.calls == []
    assert proc.nextDelay.calls


def test_online_stream_advance_flow_phase_preserves_tail_budget_after_late_coverage(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._flow_mode = "scout"
    proc.capture_budget["captures_used"] = 34
    proc.capture_budget["captures_remaining_nominal"] = 23
    proc.capture_budget["captures_remaining_hard"] = 29
    proc.capture_budget["exhausted"] = False
    proc._flow_delay_summaries = [
        {
            "delay_us": 3850 + (50 * idx),
            "delay_from_emergence_us": 650 + (50 * idx),
            "delay_accepted": True,
            "flow_point_confidence": 0.92,
            "flow_optical_confidence_active": True,
            "min_attached_bottom_clearance_px": 280,
            "min_accepted_fluid_distance_from_bottom_px": 280,
            "warnings": [],
        }
        for idx in range(11)
    ]
    proc._compute_flow_preview_fit_result = lambda: {
        "fit_status": "ok",
        "accepted_delay_point_count": 12,
        "steady_rate_ci95_relative_width": 0.18,
        "late_coverage_reached": True,
        "late_slope_stable": False,
    }
    proc._current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=4400,
            delay_from_emergence_us=1200,
            replicate_index=1,
            qc={"measurement_qc_pass": True},
            image_ref={"capture_id": "cap_flow_budget_late"},
            warnings=[],
            attached_width_px=90.0,
            visible_volume_nl=17.8,
            attached_bottom_clearance_px=260,
            min_accepted_fluid_distance_from_bottom_px=260,
            flow_point_confidence=0.88,
            flow_optical_confidence_active=True,
            flow_volume_geometry_ok=True,
            flow_volume_complete_ok=True,
            flow_measurement_usable=True,
            attached_bottom_guard_hit=False,
            detached_near_bottom_warning=False,
        )
    ]
    proc._current_analysis_summary = {"status": "accepted"}
    proc._preview_required_tail_capture_count = lambda fit_result=None: 31

    proc.onAdvanceFlowPhase()

    assert proc._flow_termination_reason == "tail_budget_preserved"
    assert "tail_budget_preserved_early_finalize" in proc._flow_warnings
    assert len(proc.flowAcquisitionFinished.calls) == 1


def test_online_stream_advance_flow_phase_preserves_tail_budget_after_real_boundary_fix(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._flow_mode = "scout"
    proc.capture_budget["captures_used"] = 34
    proc.capture_budget["captures_remaining_nominal"] = 23
    proc.capture_budget["captures_remaining_hard"] = 29
    proc.capture_budget["exhausted"] = False
    proc._flow_right_boundary_fixed = True
    proc._flow_right_boundary_delay_from_emergence_us = 950
    proc._flow_scout_boundary_reason = "soft_bottom_clearance"
    proc._flow_delay_summaries = [
        {
            "delay_us": 3850 + (50 * idx),
            "delay_from_emergence_us": 650 + (50 * idx),
            "delay_accepted": True,
            "flow_point_confidence": 0.92,
            "flow_optical_confidence_active": True,
            "min_attached_bottom_clearance_px": 420,
            "min_accepted_fluid_distance_from_bottom_px": 420,
            "warnings": [],
        }
        for idx in range(11)
    ]
    proc._compute_flow_preview_fit_result = lambda: {
        "fit_status": "ok",
        "accepted_delay_point_count": 12,
        "steady_rate_ci95_relative_width": 0.18,
        "late_coverage_reached": False,
        "late_slope_stable": False,
    }
    proc._current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=4400,
            delay_from_emergence_us=1200,
            replicate_index=1,
            qc={"measurement_qc_pass": True},
            image_ref={"capture_id": "cap_flow_budget_boundary"},
            warnings=[],
            attached_width_px=90.0,
            visible_volume_nl=17.8,
            attached_bottom_clearance_px=260,
            min_accepted_fluid_distance_from_bottom_px=260,
            flow_point_confidence=0.88,
            flow_optical_confidence_active=True,
            flow_volume_geometry_ok=True,
            flow_volume_complete_ok=True,
            flow_measurement_usable=True,
            attached_bottom_guard_hit=False,
            detached_near_bottom_warning=False,
        )
    ]
    proc._current_analysis_summary = {"status": "accepted"}
    proc._preview_required_tail_capture_count = lambda fit_result=None: 31

    proc.onAdvanceFlowPhase()

    assert proc._flow_termination_reason == "tail_budget_preserved"
    assert "tail_budget_preserved_early_finalize" in proc._flow_warnings
    assert len(proc.flowAcquisitionFinished.calls) == 1


def test_online_stream_build_tail_backtrack_sequence_compresses_to_fit_remaining_budget(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._tail_plan = {
        "scout_anchor_delay_us": 4250,
        "backtrack_step_us": 50,
        "backtrack_replicates": 1,
        "fine_prepad_us": 100,
        "fine_postpad_us": 100,
    }
    proc.capture_budget["captures_remaining_hard"] = 12
    proc._tail_backtrack_left_delay_us = 4250
    proc._tail_landmark_delay_us = 5250
    proc._tail_backtrack_delay_summaries = []

    sequence = proc._build_tail_backtrack_delay_sequence()

    assert sequence == [4250, 4850, 4900, 4950, 5000, 5050, 5100, 5150, 5200, 5250, 5300, 5350]
    assert proc._tail_plan["tail_backtrack_compressed"] is True
    assert proc._tail_plan["tail_backtrack_requested_capture_count"] == 23
    assert proc._tail_plan["tail_backtrack_applied_capture_count"] == 12
    assert proc._tail_plan["tail_backtrack_budget_impossible"] is False
    assert "tail_budget_compressed_backtrack" in proc._tail_fit_warnings


def test_online_stream_advance_flow_phase_does_not_boundary_before_any_safe_late_window_point(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._flow_mode = "scout"
    proc._flow_delay_summaries = [
        {
            "delay_us": 3850,
            "delay_from_emergence_us": 650,
            "delay_accepted": True,
            "flow_point_confidence": 0.92,
            "flow_optical_confidence_active": True,
            "min_attached_bottom_clearance_px": 420,
            "min_accepted_fluid_distance_from_bottom_px": 420,
            "warnings": [],
        },
        {
            "delay_us": 3950,
            "delay_from_emergence_us": 750,
            "delay_accepted": True,
            "flow_point_confidence": 0.40,
            "flow_optical_confidence_active": True,
            "min_attached_bottom_clearance_px": 390,
            "min_accepted_fluid_distance_from_bottom_px": 390,
            "warnings": [],
        },
    ]
    proc._current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=4050,
            delay_from_emergence_us=850,
            replicate_index=1,
            qc={"measurement_qc_pass": True},
            image_ref={"capture_id": "cap_flow_conf"},
            warnings=[],
            attached_width_px=90.0,
            visible_volume_nl=12.8,
            attached_bottom_clearance_px=280,
            min_accepted_fluid_distance_from_bottom_px=280,
            flow_point_confidence=0.35,
            flow_optical_confidence_active=True,
            flow_volume_geometry_ok=True,
            flow_measurement_usable=True,
            attached_bottom_guard_hit=False,
            detached_near_bottom_warning=False,
        )
    ]
    proc._current_analysis_summary = {"status": "accepted"}

    proc.onAdvanceFlowPhase()

    assert proc._flow_scout_boundary_reason is None
    assert proc._flow_right_boundary_fixed is False
    assert getattr(proc, "_flow_confidence_boundary_delay_from_emergence_us", None) is None
    assert proc._flow_delay_sequence == [int(proc.emergence_time_us) + 950]


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
    assert proc.calibrationCompleted.calls == []
    artifact = json.loads(Path(proc._flow_fit_path).read_text(encoding="utf-8"))
    assert artifact["fit"]["flow_rate_nl_per_us"] == 0.0187
    assert artifact["warnings"] == ["flow_fit_min_points_only"]
    payload = proc.calibrationDataUpdated.calls[-1][0][0]
    assert payload["result"]["flow_phase"]["fit_status"] == "warning_min_points_only"
    assert payload["result"]["tail_phase"] == {"status": "not_run", "plan": {}}
    assert payload["result"]["predicted_stream_duration_us"] is None
    assert payload["result"]["predicted_volume_nl"] is None
    assert payload["result"]["warnings"] == [
        "insufficient_accepted_delays",
        "flow_fit_min_points_only",
    ]


def test_online_stream_fit_flow_rate_failure_restores_before_terminal_error(tmp_path, monkeypatch):
    proc = _flow_proc(tmp_path)
    proc._flow_fit_path = str(tmp_path / "flow_fit.json")
    captured = {"settings": None}

    monkeypatch.setattr(
        calibration_model.online_fit_mod,
        "fit_online_stream_flow_phase",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    def _stub(settings, callback, *, context="", guard_timeout_ms=None, on_timeout=None):
        captured["settings"] = dict(settings)
        callback()
        return lambda: None

    proc._request_settings_with_recording = _stub

    proc.onFitFlowRate()

    assert proc.finalize.calls
    assert proc.calibrationError.calls == []
    assert not Path(proc._flow_fit_path).exists()

    proc.onRestoreSettings()
    proc.onCompleted()

    assert captured["settings"] == {
        "num_droplets": 1,
        "flash_delay": 4300,
        "print_pressure": 0.42,
        "print_pulse_width": 1350,
    }
    assert proc.calibrationCompleted.calls == []
    assert proc.calibrationError.calls[-1][0][0] == "Failed to fit online stream flow rate: boom"


def test_online_stream_on_fit_flow_rate_surfaces_nominal_budget_warning_without_stopping(tmp_path, monkeypatch):
    proc = _flow_proc(tmp_path)
    proc._flow_fit_path = str(tmp_path / "flow_fit.json")
    proc._attempted_capture_count = int(proc.capture_budget["nominal_limit"])
    proc.capture_budget = calibration_model.online_cal_mod.consume_online_stream_budget(
        proc.capture_budget,
        phase="flow_phase",
        count=proc.capture_budget["nominal_limit"],
    )
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
    assert "capture_budget_nominal_exhausted" in proc._flow_warnings
    artifact = json.loads(Path(proc._flow_fit_path).read_text(encoding="utf-8"))
    assert set(artifact["warnings"]) == {
        "capture_budget_nominal_exhausted",
        "flow_fit_min_points_only",
    }
    payload = proc.calibrationDataUpdated.calls[-1][0][0]
    assert "capture_budget_nominal_exhausted" in payload["result"]["flow_phase"]["warnings"]
    assert payload["result"]["flow_phase"]["fit_warnings"] == ["flow_fit_min_points_only"]
    assert proc.calibrationCompleted.calls == []


def test_online_stream_plan_tail_phase_skips_when_flow_baseline_is_missing(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._tail_fit_path = str(tmp_path / "tail_fit.json")
    proc.onPlanFlowPhase()
    proc._flow_fit_result = {"fit_status": "unresolved_insufficient_delays", "steady_width_baseline_px": None}

    proc.onPlanTailPhase()

    assert proc.tailPhaseFinished.calls
    assert proc._tail_phase_status == "unresolved_missing_flow_baseline"
    snapshot = json.loads(Path(proc._plan_snapshot_path).read_text(encoding="utf-8"))
    assert snapshot["tail_plan"]["run_tail"] is False
    assert snapshot["tail_plan"]["skip_reason"] == "missing_flow_baseline"
    artifact = json.loads(Path(proc._tail_fit_path).read_text(encoding="utf-8"))
    assert artifact["result"]["tail_phase"]["status"] == "unresolved_missing_flow_baseline"


def test_online_stream_plan_tail_phase_runs_for_warning_quality_flow_fit(tmp_path):
    proc = _flow_proc(tmp_path)
    proc.onPlanFlowPhase()
    _seed_tail_flow_context(proc, fit_status="warning_quality_thresholds")

    proc.onPlanTailPhase()

    assert proc.tailPlanReady.calls
    assert proc._tail_plan["run_tail"] is True
    assert proc._tail_delay_sequence
    assert proc._tail_mode == "scout"
    assert proc._tail_plan["scout_anchor_delay_us"] == 4250
    assert proc._tail_delay_sequence[0] == 4750
    snapshot = json.loads(Path(proc._plan_snapshot_path).read_text(encoding="utf-8"))
    assert snapshot["tail_plan"] == proc._tail_plan


def test_online_stream_plan_tail_phase_passes_tail_settling_toggle(tmp_path, monkeypatch):
    proc = _flow_proc(tmp_path)
    proc.onPlanFlowPhase()
    _seed_tail_flow_context(proc)
    proc.analysis_config["tail_settling_rule_enabled"] = False
    captured = {}
    original = calibration_model.online_tail_mod.plan_online_stream_tail_phase

    def _wrapped_plan(**kwargs):
        captured["analysis_config"] = dict(kwargs.get("analysis_config") or {})
        return original(**kwargs)

    monkeypatch.setattr(calibration_model.online_tail_mod, "plan_online_stream_tail_phase", _wrapped_plan)

    proc.onPlanTailPhase()

    assert captured["analysis_config"]["tail_settling_rule_enabled"] is False
    assert proc._tail_plan["analysis_config"]["tail_settling_rule_enabled"] is False


def test_online_stream_preview_tail_resolve_result_passes_tail_settling_toggle(tmp_path, monkeypatch):
    proc = _flow_proc(tmp_path)
    proc.onPlanFlowPhase()
    _seed_tail_flow_context(proc)
    proc.analysis_config["tail_settling_rule_enabled"] = False
    proc.onPlanTailPhase()
    captured = {}

    def _fake_resolve(**kwargs):
        captured["analysis_config"] = dict(kwargs.get("analysis_config") or {})
        captured["run_segmented_tail_shadow"] = kwargs.get("run_segmented_tail_shadow")
        return {
            "phase": "online_stream_calibration",
            "tail_phase": {"status": "captured", "warnings": []},
            "predicted_stream_duration_us": None,
            "predicted_volume_nl": None,
            "warnings": [],
        }

    monkeypatch.setattr(calibration_model.online_tail_mod, "resolve_online_stream_tail_result", _fake_resolve)

    proc._preview_tail_resolve_result()

    assert captured["analysis_config"]["tail_settling_rule_enabled"] is False
    assert captured["run_segmented_tail_shadow"] is False


def test_online_stream_plan_tail_phase_reserves_backtrack_budget_for_tail_search(tmp_path):
    proc = _flow_proc(tmp_path)
    proc.onPlanFlowPhase()
    proc.capture_budget = calibration_model.online_cal_mod.consume_online_stream_budget(
        calibration_model.online_cal_mod.new_online_stream_budget(),
        phase="flow_phase",
        count=15,
    )
    _seed_tail_flow_context(proc)

    proc.onPlanTailPhase()

    assert proc._tail_plan["max_scout_delay_count"] == 10
    assert proc._tail_plan["fine_prepad_us"] == 100
    assert proc._tail_plan["fine_postpad_us"] == 100
    assert proc._tail_plan["reserved_backtrack_capture_count"] == 15
    assert proc._tail_plan["reserved_refine_capture_count"] == 15
    assert proc._tail_plan["reserved_refine_delay_count"] == 15
    assert len(proc._tail_delay_sequence) == 10
    assert (
        len(proc._tail_delay_sequence) * int(proc._tail_plan["scout_replicates"])
        + int(proc._tail_plan["reserved_backtrack_capture_count"])
    ) <= int(proc.capture_budget["captures_remaining_hard"])


def test_online_stream_plan_tail_phase_fails_when_less_than_dense_tail_budget_remains(tmp_path):
    proc = _flow_proc(tmp_path)
    proc.onPlanFlowPhase()
    proc.capture_budget = calibration_model.online_cal_mod.consume_online_stream_budget(
        calibration_model.online_cal_mod.new_online_stream_budget(),
        phase="flow_phase",
        count=40,
    )
    _seed_tail_flow_context(proc)

    proc.onPlanTailPhase()

    assert proc.tailPhaseFinished.calls
    assert proc._tail_phase_status == "unresolved_budget_exhausted"
    assert proc._tail_termination_reason == "capture_budget_exhausted"


def test_online_stream_analyze_tail_frame_accepts_late_width_even_when_flow_qc_would_reject(tmp_path, monkeypatch):
    proc = _flow_proc(tmp_path)
    proc._frames_path = str(tmp_path / "frames.jsonl")
    proc._tail_mode = "scout"
    proc._tail_current_delay_us = 7150
    proc._tail_replicate_index = 0
    proc.flow_frame_image = np.full((320, 220), 230, dtype=np.uint8)
    proc._current_tail_capture_ref = {
        "capture_id": "cap_tail_01",
        "image_relpath": "captures/tail_0001.png",
    }

    monkeypatch.setattr(
        calibration_model.online_runtime_mod,
        "analyze_online_stream_frame",
        lambda **kwargs: {
            "summary": {
                "status": "rejected_bottom_guard",
                "measurement_qc_pass": False,
                "nozzle_qc_pass": True,
                "silhouette_qc_pass": True,
                "silhouette_status": "ok",
                "failure_reason": "attached primary reached bottom guard",
                "attached_width_px": 69.0,
                "visible_volume_nl": 18.0,
                "attached_bottom_clearance_px": 80,
                "min_accepted_fluid_distance_from_bottom_px": 80,
                "accepted_component_count": 1,
                "accepted_detached_component_count": 0,
                "detached_near_bottom_warning": False,
                "warnings": ["attached_bottom_guard_hit"],
                "attached_bottom_guard_hit": True,
                "late_frame_warning": True,
                "tail_width_usable": True,
                "tail_landmark_usable": False,
                "separated_from_nozzle_landmark": False,
                "landmark_reason": None,
                "adaptive_roi_expansion_triggered": True,
                "adaptive_roi_expansion_sides": ["right"],
                "adaptive_roi_expansion_iterations": 1,
                "adaptive_roi_left_expansion_px": 0,
                "adaptive_roi_right_expansion_px": 48,
                "adaptive_roi_stop_reason": "clearance_ok",
                "base_roi_x0": 439,
                "base_roi_x1": 820,
                "base_corridor_x0": 495,
                "base_corridor_x1": 762,
                "selected_component_corridor_left_clearance_px": 73,
                "selected_component_corridor_right_clearance_px": 18,
            },
            "overlay": None,
        },
    )

    proc.onAnalyzeTailFrame()

    assert proc.tailFrameAnalyzed.calls
    assert proc._measurement_rows[-1]["phase"] == "tail_scout"
    assert proc._measurement_rows[-1]["nozzle_qc_pass"] is True
    assert proc._measurement_rows[-1]["silhouette_qc_pass"] is True
    assert proc._measurement_rows[-1]["attached_bottom_clearance_px"] == 80.0
    lines = Path(proc._frames_path).read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[0])
    assert payload["status"] == "accepted"
    assert payload["adaptive_roi_expansion_triggered"] is True
    assert payload["adaptive_roi_expansion_sides"] == ["right"]
    assert payload["adaptive_roi_right_expansion_px"] == 48
    assert payload["base_roi_x1"] == 820
    assert payload["selected_component_corridor_right_clearance_px"] == 18


def test_online_stream_analyze_tail_frame_reuses_and_records_sticky_window_state(tmp_path, monkeypatch):
    proc = _flow_proc(tmp_path)
    proc._frames_path = str(tmp_path / "frames.jsonl")
    proc._tail_mode = "scout"
    proc._tail_current_delay_us = 7150
    proc._tail_replicate_index = 0
    proc._tail_width_window_state = {
        "selected_band_y0_px": 144,
        "selected_band_y1_px": 184,
    }
    proc.flow_frame_image = np.full((320, 220), 230, dtype=np.uint8)
    proc._current_tail_capture_ref = {
        "capture_id": "cap_tail_sticky",
        "image_relpath": "captures/tail_sticky.png",
    }
    captured_calls = []

    def _fake_analyze(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "summary": {
                "status": "accepted",
                "measurement_qc_pass": True,
                "nozzle_qc_pass": True,
                "silhouette_qc_pass": True,
                "silhouette_status": "ok",
                "failure_reason": None,
                "attached_width_px": 89.0,
                "attached_width_mode": "lower_consistent_window",
                "visible_volume_nl": 18.0,
                "attached_bottom_clearance_px": 120,
                "min_accepted_fluid_distance_from_bottom_px": 120,
                "accepted_component_count": 1,
                "accepted_detached_component_count": 0,
                "detached_near_bottom_warning": False,
                "near_nozzle_detached_warning": False,
                "warnings": [],
                "attached_bottom_guard_hit": False,
                "late_frame_warning": False,
                "tail_width_usable": True,
                "tail_landmark_usable": False,
                "separated_from_nozzle_landmark": False,
                "landmark_reason": None,
                "root_band_width_px": 130.0,
                "root_band_width_iqr_px": 40.0,
                "root_band_half_delta_px": 40.0,
                "selected_band_y0_px": 144,
                "selected_band_y1_px": 184,
                "selected_band_step_index": 3,
                "root_band_step_index": 0,
                "selected_band_valid_row_count": 40,
                "spread_fallback_triggered": True,
                "candidate_window_count": 5,
                "sticky_window_active": True,
                "sticky_window_previous_y0_px": 144,
                "sticky_window_instant_y0_px": 124,
                "sticky_window_selected_reason": "sticky_hold_previous",
                "sticky_window_candidate_streak": 1,
                "sticky_window_switch_blocked": True,
                "window_delay_lock_active": False,
                "window_locked_reused": False,
                "window_locked_invalid": False,
                "window_monotonic_upward_move_blocked": False,
                "next_sticky_window_state": {
                    "selected_band_y0_px": 144,
                    "selected_band_y1_px": 184,
                    "selected_band_step_index": 3,
                    "pending_candidate_y0_px": 124,
                    "pending_candidate_y1_px": 164,
                    "candidate_streak": 1,
                },
            },
            "overlay": None,
        }

    monkeypatch.setattr(
        calibration_model.online_runtime_mod,
        "analyze_online_stream_frame",
        _fake_analyze,
    )

    proc.onAnalyzeTailFrame()

    assert captured_calls[0]["sticky_window_state"] == {
        "selected_band_y0_px": 144,
        "selected_band_y1_px": 184,
    }
    assert proc._tail_width_window_state == {
        "selected_band_y0_px": 144,
        "selected_band_y1_px": 184,
        "selected_band_step_index": 3,
        "pending_candidate_y0_px": 124,
        "pending_candidate_y1_px": 164,
        "candidate_streak": 1,
    }
    payload = json.loads(Path(proc._frames_path).read_text(encoding="utf-8").strip())
    assert payload["sticky_window_active"] is True
    assert payload["sticky_window_previous_y0_px"] == 144
    assert payload["sticky_window_instant_y0_px"] == 124
    assert payload["sticky_window_selected_reason"] == "sticky_hold_previous"
    assert payload["sticky_window_candidate_streak"] == 1
    assert payload["sticky_window_switch_blocked"] is True
    assert payload["selected_band_step_index"] == 3
    assert payload["window_locked_reused"] is False


def test_online_stream_analyze_tail_frame_resets_sticky_window_state_on_root_band(tmp_path, monkeypatch):
    proc = _flow_proc(tmp_path)
    proc._frames_path = str(tmp_path / "frames.jsonl")
    proc._tail_mode = "scout"
    proc._tail_current_delay_us = 7150
    proc._tail_replicate_index = 0
    proc._tail_width_window_state = {
        "selected_band_y0_px": 144,
        "selected_band_y1_px": 184,
    }
    proc.flow_frame_image = np.full((320, 220), 230, dtype=np.uint8)
    proc._current_tail_capture_ref = {
        "capture_id": "cap_tail_root",
        "image_relpath": "captures/tail_root.png",
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
                "attached_width_px": 70.0,
                "attached_width_mode": "root_band",
                "visible_volume_nl": 18.0,
                "attached_bottom_clearance_px": 120,
                "min_accepted_fluid_distance_from_bottom_px": 120,
                "accepted_component_count": 1,
                "accepted_detached_component_count": 0,
                "detached_near_bottom_warning": False,
                "near_nozzle_detached_warning": False,
                "warnings": [],
                "attached_bottom_guard_hit": False,
                "late_frame_warning": False,
                "tail_width_usable": True,
                "tail_landmark_usable": False,
                "separated_from_nozzle_landmark": False,
                "landmark_reason": None,
                "selected_band_y0_px": 84,
                "selected_band_y1_px": 124,
                "selected_band_valid_row_count": 40,
                "spread_fallback_triggered": False,
                "candidate_window_count": 0,
                "sticky_window_active": False,
                "sticky_window_previous_y0_px": 144,
                "sticky_window_instant_y0_px": None,
                "sticky_window_selected_reason": "reset_root_band",
                "sticky_window_candidate_streak": 0,
                "sticky_window_switch_blocked": False,
                "next_sticky_window_state": {},
            },
            "overlay": None,
        },
    )

    proc.onAnalyzeTailFrame()

    assert proc._tail_width_window_state == {}
    payload = json.loads(Path(proc._frames_path).read_text(encoding="utf-8").strip())
    assert payload["sticky_window_active"] is False
    assert payload["sticky_window_selected_reason"] == "reset_root_band"


def test_online_stream_debug_signal_emits_provisional_tail_width_points(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
    }
    proc._tail_mode = "scout"
    proc._tail_scout_delay_summaries = [
        calibration_model.online_tail_mod.summarize_online_stream_tail_delay(
            [_accepted_tail_frame_row(proc, 1550, phase="tail_scout", width_px=73.5)],
            74.0,
        )
    ]
    proc._tail_current_delay_us = int(proc.emergence_time_us) + 1750
    proc._tail_current_delay_frame_rows = [
        _accepted_tail_frame_row(proc, 1750, phase="tail_scout", width_px=69.5)
    ]
    proc._current_tail_analysis_summary = {
        "attached_width_px": 69.5,
        "tail_width_usable": True,
    }

    proc._emit_online_stream_debug_payload("tail_scout")

    payload = proc.onlineStreamDebugUpdated.calls[-1][0][0]
    tail_plot = payload["tail_plot"]
    assert payload["subphase"] == "tail_scout"
    assert tail_plot["baseline_width_px"] == 74.0
    assert len(tail_plot["scout_points"]) == 2
    assert tail_plot["scout_points"][-1]["x_us"] == 1750
    assert tail_plot["scout_points"][-1]["provisional"] is True
    assert tail_plot["current_frame_point"] == {
        "x_us": 1750,
        "y_px": 69.5,
        "accepted": True,
        "mode": "scout",
    }
    assert tail_plot["tail_start_x_us"] is None


def test_online_stream_debug_signal_does_not_run_segmented_tail_preview(tmp_path, monkeypatch):
    proc = _flow_proc(tmp_path)
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
    }
    proc._tail_mode = "scout"
    proc._tail_start_delay_from_emergence_us = 1700
    proc._tail_scout_delay_summaries = [
        calibration_model.online_tail_mod.summarize_online_stream_tail_delay(
            [_accepted_tail_frame_row(proc, offset_us, phase="tail_scout", width_px=width_px)],
            74.0,
        )
        for offset_us, width_px in [
            (1500, 74.0),
            (1550, 73.8),
            (1600, 72.0),
            (1650, 70.0),
            (1700, 66.0),
        ]
    ]
    proc._tail_current_delay_us = int(proc.emergence_time_us) + 1750
    proc._tail_current_delay_frame_rows = [
        _accepted_tail_frame_row(proc, 1750, phase="tail_scout", width_px=61.0)
    ]
    proc._current_tail_analysis_summary = {
        "attached_width_px": 61.0,
        "tail_width_usable": True,
    }
    calls = {"count": 0}

    def _fail_if_called(**kwargs):
        calls["count"] += 1
        raise AssertionError("segmented tail should not run during debug emission")

    monkeypatch.setattr(
        calibration_model.online_tail_mod,
        "evaluate_online_stream_segmented_tail_shadow",
        _fail_if_called,
    )

    proc._emit_online_stream_debug_payload("tail_scout")

    payload = proc.onlineStreamDebugUpdated.calls[-1][0][0]
    assert payload["tail_plot"]["segmented_tail"] is None
    assert calls["count"] == 0


def test_online_stream_tail_final_resolution_emits_segmented_busy_signal(tmp_path, monkeypatch):
    proc = _flow_proc(tmp_path)
    proc._tail_plan = {"steady_width_baseline_px": 74.0}
    proc.analysis_config = {"segmented_tail_online_shadow_enabled": True}
    captured = {}

    def _fake_tail_resolve_result(*, run_segmented_tail_shadow):
        captured["run_segmented_tail_shadow"] = bool(run_segmented_tail_shadow)
        captured["running_during_resolve"] = bool(proc._tail_segmented_analysis_running)
        busy_payload = proc.onlineStreamDebugUpdated.calls[-1][0][0]
        captured["busy_segmented_tail"] = dict(busy_payload["tail_plot"]["segmented_tail"])
        return {
            "tail_phase": {
                "status": "captured",
                "tail_start_delay_from_emergence_us": 1200,
                "segmented_tail": {
                    "status": "ok",
                    "tail_start_delay_from_emergence_us": 1175,
                    "predicted_volume_nl": 20.7725,
                    "runtime_predicted_volume_nl": 21.24,
                },
                "segmented_tail_start_delay_from_emergence_us": 1175,
                "segmented_predicted_stream_duration_us": 1175,
                "segmented_predicted_volume_nl": 20.7725,
            },
            "predicted_stream_duration_us": 1200,
            "predicted_volume_nl": 21.24,
            "warnings": [],
        }

    monkeypatch.setattr(proc, "_tail_resolve_result", _fake_tail_resolve_result)

    proc._resolve_tail_phase()

    assert captured["run_segmented_tail_shadow"] is True
    assert captured["running_during_resolve"] is True
    assert captured["busy_segmented_tail"]["status"] == "running"
    assert "fitting segmented tail model" in proc.stageChanged.calls[-1][0][0]
    assert proc._tail_segmented_analysis_running is False
    assert proc._tail_fit_result["tail_phase"]["segmented_predicted_volume_nl"] == 20.7725


def test_online_stream_debug_signal_plots_unavailable_tail_widths_at_zero(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
    }
    proc._tail_mode = "scout"
    proc._tail_scout_delay_summaries = [
        {
            "delay_us": int(proc.emergence_time_us) + 1550,
            "delay_from_emergence_us": 1550,
            "median_width_px": None,
        }
    ]
    proc._build_provisional_tail_delay_summary = lambda: {
        "delay_us": int(proc.emergence_time_us) + 1750,
        "delay_from_emergence_us": 1750,
        "median_width_px": "width unavailable",
    }
    proc._tail_current_delay_us = int(proc.emergence_time_us) + 1750
    proc._current_tail_analysis_summary = {
        "attached_width_px": "width unavailable",
        "tail_width_usable": False,
    }

    proc._emit_online_stream_debug_payload("tail_scout")

    payload = proc.onlineStreamDebugUpdated.calls[-1][0][0]
    tail_plot = payload["tail_plot"]
    assert tail_plot["scout_points"] == [
        {"x_us": 1550, "y_px": 0.0, "provisional": False},
        {"x_us": 1750, "y_px": 0.0, "provisional": True},
    ]
    assert tail_plot["current_frame_point"] == {
        "x_us": 1750,
        "y_px": 0.0,
        "accepted": False,
        "mode": "scout",
    }


def test_online_stream_debug_signal_publishes_final_tail_start_after_resolution(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._tail_mode = "backtrack"
    proc._tail_start_delay_from_emergence_us = 3950
    proc._tail_fit_result = {
        "tail_phase": {
            "segmented_tail": {
                "status": "ok",
                "tail_start_delay_from_emergence_us": 3900,
                "predicted_volume_nl": 71.73,
                "runtime_predicted_volume_nl": 72.665,
                "fit_points": [
                    {"delay_from_emergence_us": 3850, "fitted_width_px": 74.0},
                    {"delay_from_emergence_us": 3900, "fitted_width_px": 70.0},
                ],
            }
        }
    }
    proc._tail_backtrack_delay_summaries = [
        calibration_model.online_tail_mod.summarize_online_stream_tail_delay(
            [_accepted_tail_frame_row(proc, 3550, phase="tail_backtrack", width_px=58.0)],
            74.0,
        )
    ]

    proc._emit_online_stream_debug_payload("completed")

    payload = proc.onlineStreamDebugUpdated.calls[-1][0][0]
    assert payload["subphase"] == "completed"
    assert payload["tail_plot"]["tail_start_x_us"] == 3950
    assert payload["tail_plot"]["segmented_tail"]["tail_start_delay_from_emergence_us"] == 3900
    assert payload["tail_plot"]["segmented_tail"]["predicted_volume_nl"] == 71.73


def test_online_stream_advance_tail_phase_continues_scout_without_landmark(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
        "planned_scout_delay_count": 2,
    }
    proc._tail_mode = "scout"
    proc._tail_delay_sequence = [4750, 5250]
    proc._tail_delay_index = 0
    proc._tail_replicate_index = 0
    proc._tail_current_delay_us = 4750
    proc._tail_current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="tail_scout",
            status="accepted",
            delay_us=4750,
            delay_from_emergence_us=1550,
            replicate_index=1,
            qc={"tail_qc_pass": True, "tail_width_usable": True, "tail_landmark_usable": False},
            image_ref={"capture_id": "cap_tail"},
            warnings=[],
            attached_width_px=74.0,
            tail_width_usable=True,
            tail_landmark_usable=False,
            separated_from_nozzle_landmark=False,
        )
    ]

    proc.onAdvanceTailPhase()

    assert proc.nextTailDelay.calls
    assert proc._tail_mode == "scout"
    assert proc._tail_delay_index == 1


def test_online_stream_advance_tail_phase_keeps_scout_running_on_single_pixel_tail_dip(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
        "planned_scout_delay_count": 2,
    }
    proc._tail_mode = "scout"
    proc._tail_delay_sequence = [4750, 5250]
    proc._tail_delay_index = 0
    proc._tail_replicate_index = 0
    proc._tail_current_delay_us = 4750
    proc._tail_current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="tail_scout",
            status="accepted",
            delay_us=4750,
            delay_from_emergence_us=1550,
            replicate_index=1,
            qc={"tail_qc_pass": True, "tail_width_usable": True, "tail_landmark_usable": False},
            image_ref={"capture_id": "cap_tail"},
            warnings=[],
            attached_width_px=73.0,
            tail_width_usable=True,
            tail_landmark_usable=False,
            separated_from_nozzle_landmark=False,
        )
    ]

    proc.onAdvanceTailPhase()

    assert proc.nextTailDelay.calls
    assert proc._tail_mode == "scout"
    assert proc._tail_delay_index == 1
    assert proc._tail_landmark_delay_us is None
    assert proc._tail_landmark_reason is None
    assert len(proc._tail_scout_delay_summaries) == 1


def test_online_stream_advance_tail_phase_keeps_first_mild_backup_collapse_scouting(tmp_path):
    proc = _flow_proc(tmp_path)
    _seed_tail_flow_context(proc)
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_anchor_delay_us": 4250,
        "backtrack_step_us": 50,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
        "fine_prepad_us": 100,
        "fine_postpad_us": 100,
        "planned_scout_delay_count": 3,
    }
    proc._tail_mode = "scout"
    proc._tail_delay_sequence = [4750, 5250, 5750]
    proc._tail_delay_index = 0
    proc._tail_replicate_index = 0
    proc._tail_current_delay_us = 4750
    proc._tail_current_delay_frame_rows = [
        _accepted_tail_frame_row(proc, 1550, phase="tail_scout", width_px=69.0)
    ]

    proc.onAdvanceTailPhase()

    assert proc.nextTailDelay.calls
    assert proc._tail_mode == "scout"
    assert proc._tail_delay_index == 1
    assert proc._tail_landmark_delay_us is None
    assert "tail_backup_landmark_unconfirmed" not in proc._tail_fit_warnings


def test_online_stream_advance_tail_phase_does_not_end_scout_on_repeated_width_only_drop(tmp_path):
    proc = _flow_proc(tmp_path)
    _seed_tail_flow_context(proc)
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_anchor_delay_us": 4250,
        "backtrack_step_us": 50,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
        "fine_prepad_us": 100,
        "fine_postpad_us": 100,
        "planned_scout_delay_count": 3,
    }
    proc._tail_mode = "scout"
    proc._tail_delay_sequence = [4750, 5250, 5750]
    proc._tail_delay_index = 1
    proc._tail_replicate_index = 0
    proc._tail_scout_delay_summaries = [
        calibration_model.online_tail_mod.summarize_online_stream_tail_delay(
            [_accepted_tail_frame_row(proc, 1550, phase="tail_scout", width_px=69.0)],
            74.0,
        )
    ]
    proc._tail_current_delay_us = 5250
    proc._tail_current_delay_frame_rows = [
        _accepted_tail_frame_row(proc, 2050, phase="tail_scout", width_px=68.5)
    ]

    proc.onAdvanceTailPhase()

    assert proc.nextTailDelay.calls
    assert proc._tail_mode == "scout"
    assert proc._tail_delay_index == 2
    assert proc._tail_landmark_delay_us is None
    assert proc._tail_landmark_reason is None
    assert proc._tail_backup_landmark_confirmed is False
    assert proc._tail_backup_landmark_confirmation_reason is None
    assert proc._tail_backtrack_left_delay_us is None


def test_online_stream_advance_tail_phase_continues_after_root_to_lower_window_drop(tmp_path):
    proc = _flow_proc(tmp_path)
    _seed_tail_flow_context(proc)
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_anchor_delay_us": 4250,
        "backtrack_step_us": 50,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
        "fine_prepad_us": 100,
        "fine_postpad_us": 100,
        "planned_scout_delay_count": 3,
    }
    proc._tail_mode = "scout"
    proc._tail_delay_sequence = [4750, 5250, 5750]
    proc._tail_delay_index = 1
    proc._tail_replicate_index = 0
    proc._tail_scout_delay_summaries = [
        calibration_model.online_tail_mod.summarize_online_stream_tail_delay(
            [
                _accepted_tail_frame_row(
                    proc,
                    1550,
                    phase="tail_scout",
                    width_px=74.0,
                    attached_width_mode="root_band",
                    selected_band_step_index=0,
                )
            ],
            74.0,
        )
    ]
    proc._tail_current_delay_us = 5250
    proc._tail_current_delay_frame_rows = [
        _accepted_tail_frame_row(
            proc,
            2050,
            phase="tail_scout",
            width_px=58.0,
            attached_width_mode="lower_consistent_window",
            selected_band_step_index=3,
            selected_band_y0_px=144,
            selected_band_y1_px=184,
            spread_fallback_triggered=True,
        )
    ]

    proc.onAdvanceTailPhase()

    assert proc.nextTailDelay.calls
    assert proc._tail_mode == "scout"
    assert proc._tail_delay_index == 2
    assert proc._tail_landmark_delay_us is None
    assert proc._tail_scout_delay_summaries[-1]["width_only_collapse_candidate"] is True
    assert (
        proc._tail_scout_delay_summaries[-1]["width_only_collapse_suppressed_as_scout_landmark"]
        is True
    )
    assert proc._tail_scout_delay_summaries[-1]["resolver_collapse_candidate"] is False


def test_online_stream_advance_tail_phase_switches_to_backtrack_on_separation_landmark(tmp_path):
    proc = _flow_proc(tmp_path)
    _seed_tail_flow_context(proc)
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_anchor_delay_us": 4250,
        "backtrack_step_us": 50,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
        "fine_prepad_us": 100,
        "fine_postpad_us": 100,
        "planned_scout_delay_count": 2,
    }
    proc._tail_mode = "scout"
    proc._tail_delay_sequence = [4750, 5250]
    proc._tail_delay_index = 0
    proc._tail_replicate_index = 0
    proc._tail_current_delay_us = 4750
    proc._tail_width_window_state = {
        "delay_window_map": {
            "1550": {
                "delay_from_emergence_us": 1550,
                "selected_band_step_index": 2,
                "selected_band_y0_px": 124,
                "selected_band_y1_px": 164,
                "attached_width_mode": "lower_consistent_window",
            }
        }
    }
    proc._tail_current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="tail_scout",
            status="accepted",
            delay_us=4750,
            delay_from_emergence_us=1550,
            replicate_index=1,
            qc={"tail_qc_pass": False, "tail_width_usable": False, "tail_landmark_usable": True},
            image_ref={"capture_id": "cap_tail"},
            warnings=[],
            attached_width_px=None,
            tail_width_usable=False,
            tail_landmark_usable=True,
            separated_from_nozzle_landmark=True,
            landmark_reason="separated_from_nozzle",
            attached_bottom_guard_hit=False,
        )
    ]

    proc.onAdvanceTailPhase()

    assert proc.nextTailDelay.calls
    assert proc._tail_mode == "backtrack"
    assert proc._tail_landmark_delay_us == 4750
    assert proc._tail_landmark_reason == "separated_from_nozzle"
    assert proc._tail_backtrack_left_delay_us == 4250
    assert proc._tail_delay_sequence == [4250, 4300, 4350, 4400, 4450, 4500, 4550, 4600, 4650, 4700, 4750, 4800, 4850]
    assert "1550" in proc._tail_width_window_state["delay_window_map"]


def test_online_stream_advance_tail_phase_switches_to_dense_full_window_after_later_scout_landmark(tmp_path):
    proc = _flow_proc(tmp_path)
    _seed_tail_flow_context(proc)
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_anchor_delay_us": 4250,
        "backtrack_step_us": 50,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
        "fine_prepad_us": 100,
        "fine_postpad_us": 100,
        "planned_scout_delay_count": 2,
    }
    proc._tail_mode = "scout"
    proc._tail_delay_sequence = [4750, 5250]
    proc._tail_delay_index = 1
    proc._tail_replicate_index = 0
    proc._tail_scout_delay_summaries = [
        calibration_model.online_tail_mod.summarize_online_stream_tail_delay(
            [_accepted_tail_frame_row(proc, 1550, phase="tail_scout", width_px=74.0)],
            74.0,
        )
    ]
    proc._tail_current_delay_us = 5250
    proc._tail_current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="tail_scout",
            status="accepted",
            delay_us=5250,
            delay_from_emergence_us=2050,
            replicate_index=1,
            qc={"tail_qc_pass": False, "tail_width_usable": False, "tail_landmark_usable": True},
            image_ref={"capture_id": "cap_tail"},
            warnings=[],
            attached_width_px=None,
            tail_width_usable=False,
            tail_landmark_usable=True,
            separated_from_nozzle_landmark=True,
            landmark_reason="separated_from_nozzle",
            attached_bottom_guard_hit=False,
        )
    ]

    proc.onAdvanceTailPhase()

    assert proc.nextTailDelay.calls
    assert proc._tail_mode == "backtrack"
    assert proc._tail_landmark_delay_us == 5250
    assert proc._tail_backtrack_left_delay_us == 4750
    assert proc._tail_delay_sequence == [4650, 4700, 4750, 4800, 4850, 4900, 4950, 5000, 5050, 5100, 5150, 5200, 5250, 5300, 5350]


def test_online_stream_advance_tail_phase_switches_to_backtrack_on_attached_width_unavailable_landmark(tmp_path):
    proc = _flow_proc(tmp_path)
    _seed_tail_flow_context(proc)
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_anchor_delay_us": 4250,
        "backtrack_step_us": 50,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
        "fine_prepad_us": 100,
        "fine_postpad_us": 100,
        "planned_scout_delay_count": 2,
    }
    proc._tail_mode = "scout"
    proc._tail_delay_sequence = [4750, 5250]
    proc._tail_delay_index = 0
    proc._tail_replicate_index = 0
    proc._tail_current_delay_us = 4750
    proc._tail_current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="tail_scout",
            status="rejected_width_qc",
            delay_us=4750,
            delay_from_emergence_us=1550,
            replicate_index=1,
            qc={"tail_qc_pass": False, "tail_width_usable": False, "tail_landmark_usable": False},
            image_ref={"capture_id": "cap_tail"},
            warnings=["attached_width_unavailable", "detached_near_bottom_warning"],
            failure_reason="attached near-nozzle width unavailable",
            attached_width_px=None,
            tail_width_usable=False,
            tail_landmark_usable=False,
            separated_from_nozzle_landmark=False,
            attached_bottom_guard_hit=False,
            detached_near_bottom_warning=True,
        )
    ]

    proc.onAdvanceTailPhase()

    assert proc.nextTailDelay.calls
    assert proc._tail_mode == "backtrack"
    assert proc._tail_landmark_delay_us == 4750
    assert proc._tail_landmark_reason == "attached_width_unavailable"
    assert proc._tail_backtrack_left_delay_us == 4250
    assert proc._tail_delay_sequence == [4250, 4300, 4350, 4400, 4450, 4500, 4550, 4600, 4650, 4700, 4750, 4800, 4850]


def test_online_stream_advance_tail_phase_stops_when_no_scout_landmark_occurs(tmp_path):
    proc = _flow_proc(tmp_path)
    _seed_tail_flow_context(proc)
    proc._tail_fit_path = str(tmp_path / "tail_fit.json")
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_anchor_delay_us": 4250,
        "backtrack_step_us": 50,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
        "planned_scout_delay_count": 1,
    }
    proc._tail_mode = "scout"
    proc._tail_delay_sequence = [4750]
    proc._tail_delay_index = 0
    proc._tail_replicate_index = 0
    proc._tail_current_delay_us = 4750
    proc._tail_current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="tail_scout",
            status="accepted",
            delay_us=4750,
            delay_from_emergence_us=1550,
            replicate_index=1,
            qc={"tail_qc_pass": True, "tail_width_usable": True, "tail_landmark_usable": False},
            image_ref={"capture_id": "cap_tail"},
            warnings=[],
            attached_width_px=74.0,
            tail_width_usable=True,
            tail_landmark_usable=False,
            separated_from_nozzle_landmark=False,
        )
    ]

    proc.onAdvanceTailPhase()

    assert proc.tailPhaseFinished.calls
    assert proc._tail_phase_status == "unresolved_no_landmark"
    assert proc._tail_termination_reason == "no_scout_landmark"


def test_online_stream_advance_tail_phase_stops_after_repeated_failed_scout_delays(tmp_path):
    proc = _flow_proc(tmp_path)
    _seed_tail_flow_context(proc)
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
        "planned_scout_delay_count": 2,
    }
    proc._tail_mode = "scout"
    proc._tail_delay_sequence = [4750, 5250]
    proc._tail_delay_index = 0
    proc._tail_replicate_index = 0
    proc._tail_consecutive_failed_delays = 1
    proc._tail_current_delay_us = 4750
    proc._tail_current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="tail_scout",
            status="rejected_silhouette_qc",
            delay_us=4750,
            delay_from_emergence_us=1550,
            replicate_index=1,
            qc={"tail_qc_pass": False, "tail_width_usable": False, "tail_landmark_usable": False},
            image_ref={"capture_id": "cap_tail"},
            warnings=["silhouette_qc_failed"],
            attached_width_px=None,
            tail_width_usable=False,
            tail_landmark_usable=False,
            separated_from_nozzle_landmark=False,
        )
    ]

    proc.onAdvanceTailPhase()

    assert proc.tailPhaseFinished.calls
    assert proc._tail_phase_status == "unresolved_qc_failure"


def test_online_stream_capture_tail_frame_stops_on_budget_exhaustion(tmp_path):
    proc = _flow_proc(tmp_path)
    proc._tail_mode = "scout"
    proc._tail_current_delay_us = 4750
    proc._tail_fit_path = str(tmp_path / "tail_fit.json")
    _seed_tail_flow_context(proc)
    proc._tail_plan = {"steady_width_baseline_px": 74.0}
    proc.capture_budget = calibration_model.online_cal_mod.consume_online_stream_budget(
        calibration_model.online_cal_mod.new_online_stream_budget(),
        phase="flow_phase",
        count=61,
    )

    proc.onCaptureTailFrame()

    assert proc.tailPhaseFinished.calls
    assert proc._tail_phase_status == "unresolved_budget_exhausted"


def test_online_stream_successful_backtrack_writes_tail_fit_artifact(tmp_path, monkeypatch):
    proc = _flow_proc(tmp_path)
    proc._tail_fit_path = str(tmp_path / "tail_fit.json")
    _seed_tail_flow_context(proc)
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_anchor_delay_us": 4250,
        "backtrack_step_us": 50,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
    }
    proc._tail_mode = "backtrack"
    proc._tail_delay_sequence = [4300, 4350, 4400]
    proc._tail_delay_index = 2
    proc._tail_replicate_index = 0
    proc._tail_current_delay_us = 4400
    proc._tail_landmark_delay_us = 4750
    proc._tail_landmark_reason = "separated_from_nozzle"
    proc._tail_backtrack_left_delay_us = 4300
    proc._tail_scout_delay_summaries = [
        {
            "delay_us": 4750,
            "delay_from_emergence_us": 1550,
            "attempted_replicates": 1,
            "accepted_replicates": 1,
            "tail_width_usable_replicates": 0,
            "tail_landmark_usable_replicates": 1,
            "rejected_replicates": 0,
            "median_width_px": None,
            "width_ratio_to_baseline": None,
            "tail_width_usable": False,
            "tail_landmark_usable": True,
            "separated_from_nozzle_landmark": True,
            "backup_width_collapse_landmark": False,
            "landmark_detected": True,
            "landmark_reason": "separated_from_nozzle",
            "warnings": [],
            "delay_accepted": True,
        }
    ]
    proc._tail_backtrack_delay_summaries = [
        {
            "delay_us": 4300,
            "delay_from_emergence_us": 1100,
            "attempted_replicates": 1,
            "accepted_replicates": 1,
            "tail_width_usable_replicates": 1,
            "tail_landmark_usable_replicates": 0,
            "rejected_replicates": 0,
            "median_width_px": 74.1,
            "width_ratio_to_baseline": 74.1 / 74.0,
            "tail_width_usable": True,
            "tail_landmark_usable": False,
            "separated_from_nozzle_landmark": False,
            "backup_width_collapse_landmark": False,
            "landmark_detected": False,
            "landmark_reason": None,
            "warnings": [],
            "delay_accepted": True,
        },
        {
            "delay_us": 4350,
            "delay_from_emergence_us": 1150,
            "attempted_replicates": 1,
            "accepted_replicates": 1,
            "tail_width_usable_replicates": 1,
            "tail_landmark_usable_replicates": 0,
            "rejected_replicates": 0,
            "median_width_px": 73.9,
            "width_ratio_to_baseline": 73.9 / 74.0,
            "tail_width_usable": True,
            "tail_landmark_usable": False,
            "separated_from_nozzle_landmark": False,
            "backup_width_collapse_landmark": False,
            "landmark_detected": False,
            "landmark_reason": None,
            "warnings": [],
            "delay_accepted": True,
        },
    ]
    proc._tail_current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="tail_backtrack",
            status="accepted",
            delay_us=4400,
            delay_from_emergence_us=1200,
            replicate_index=1,
            qc={"tail_qc_pass": True, "tail_width_usable": True, "tail_landmark_usable": False},
            image_ref={"capture_id": "cap_tail"},
            warnings=[],
            attached_width_px=73.0,
            tail_width_usable=True,
            tail_landmark_usable=False,
            separated_from_nozzle_landmark=False,
        )
    ]
    calls = {"count": 0}
    original_segmented = calibration_model.online_tail_mod.evaluate_online_stream_segmented_tail_shadow

    def _count_segmented(**kwargs):
        calls["count"] += 1
        return original_segmented(**kwargs)

    monkeypatch.setattr(
        calibration_model.online_tail_mod,
        "evaluate_online_stream_segmented_tail_shadow",
        _count_segmented,
    )

    proc.onAdvanceTailPhase()

    assert proc.tailPhaseFinished.calls
    assert calls["count"] == 1
    artifact = json.loads(Path(proc._tail_fit_path).read_text(encoding="utf-8"))
    assert artifact["result"]["tail_phase"]["status"] == "captured"
    assert artifact["result"]["tail_phase"]["tail_start_evidence"] == "plateau_right_bracket_midpoint"
    assert artifact["result"]["tail_phase"]["tail_start_selection_method"] == "plateau_confirmed_collapse_midpoint"
    assert artifact["result"]["tail_phase"]["segmented_tail"]["status"] == "insufficient_usable_points"
    assert artifact["result"]["predicted_stream_duration_us"] == 1350


def test_online_stream_backtrack_extends_right_edge_without_segmented_preview(tmp_path, monkeypatch):
    proc = _flow_proc(tmp_path)
    _seed_tail_flow_context(proc)
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_anchor_delay_us": 4250,
        "backtrack_step_us": 50,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
        "tail_right_extension_count": 0,
    }
    proc._tail_mode = "backtrack"
    proc._tail_delay_sequence = [4300, 4350, 4400]
    proc._tail_delay_index = 2
    proc._tail_replicate_index = 0
    proc._tail_current_delay_us = 4400
    proc._tail_landmark_delay_us = 4750
    proc._tail_landmark_reason = "separated_from_nozzle"
    proc._tail_backtrack_left_delay_us = 4300
    proc._tail_scout_delay_summaries = [
        calibration_model.online_tail_mod.summarize_online_stream_tail_delay(
            [_accepted_tail_frame_row(proc, 1550, phase="tail_scout", width_px=70.0, landmark=True)],
            74.0,
        )
    ]
    proc._tail_backtrack_delay_summaries = [
        calibration_model.online_tail_mod.summarize_online_stream_tail_delay(
            [_accepted_tail_frame_row(proc, 1100, phase="tail_backtrack", width_px=74.0)],
            74.0,
        ),
        calibration_model.online_tail_mod.summarize_online_stream_tail_delay(
            [_accepted_tail_frame_row(proc, 1150, phase="tail_backtrack", width_px=70.0)],
            74.0,
        ),
    ]
    proc._tail_current_delay_frame_rows = [
        _accepted_tail_frame_row(proc, 1200, phase="tail_backtrack", width_px=66.0)
    ]
    calls = {"count": 0}

    def _fail_if_called(**kwargs):
        calls["count"] += 1
        raise AssertionError("segmented tail should not run for right-edge preview")

    monkeypatch.setattr(
        calibration_model.online_tail_mod,
        "evaluate_online_stream_segmented_tail_shadow",
        _fail_if_called,
    )

    proc.onAdvanceTailPhase()

    assert proc.nextTailDelay.calls
    assert not proc.tailPhaseFinished.calls
    assert proc._tail_delay_sequence[-1] == 4450
    assert proc._tail_delay_index == proc._tail_delay_sequence.index(4450)
    assert proc._tail_plan["tail_right_extension_count"] == 1
    assert proc._tail_plan["tail_right_extension_reason"] == "right_edge_width_still_falling"
    assert calls["count"] == 0


def test_online_stream_backtrack_extension_max_reached_finalizes_with_warning(tmp_path):
    proc = _flow_proc(tmp_path)
    _seed_tail_flow_context(proc)
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_anchor_delay_us": 4250,
        "backtrack_step_us": 50,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
        "tail_right_extension_count": 6,
    }
    proc._tail_mode = "backtrack"
    proc._tail_delay_sequence = [4300, 4350, 4400]
    proc._tail_delay_index = 2
    proc._tail_replicate_index = 0
    proc._tail_current_delay_us = 4400
    proc._tail_landmark_delay_us = 4750
    proc._tail_landmark_reason = "separated_from_nozzle"
    proc._tail_backtrack_left_delay_us = 4300
    proc._tail_scout_delay_summaries = [
        calibration_model.online_tail_mod.summarize_online_stream_tail_delay(
            [_accepted_tail_frame_row(proc, 1550, phase="tail_scout", width_px=70.0, landmark=True)],
            74.0,
        )
    ]
    proc._tail_backtrack_delay_summaries = [
        calibration_model.online_tail_mod.summarize_online_stream_tail_delay(
            [_accepted_tail_frame_row(proc, 1100, phase="tail_backtrack", width_px=74.0)],
            74.0,
        ),
        calibration_model.online_tail_mod.summarize_online_stream_tail_delay(
            [_accepted_tail_frame_row(proc, 1150, phase="tail_backtrack", width_px=70.0)],
            74.0,
        ),
    ]
    proc._tail_current_delay_frame_rows = [
        _accepted_tail_frame_row(proc, 1200, phase="tail_backtrack", width_px=66.0)
    ]

    proc.onAdvanceTailPhase()

    assert proc.tailPhaseFinished.calls
    assert "tail_right_extension_max_reached" in proc._tail_fit_warnings
    assert proc._tail_delay_sequence == [4300, 4350, 4400]


def test_online_stream_backtrack_extension_budget_exhausted_finalizes_with_warning(tmp_path):
    proc = _flow_proc(tmp_path)
    _seed_tail_flow_context(proc)
    proc.capture_budget["captures_remaining_hard"] = 0
    proc.capture_budget["exhausted"] = False
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_anchor_delay_us": 4250,
        "backtrack_step_us": 50,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
        "tail_right_extension_count": 0,
    }
    proc._tail_mode = "backtrack"
    proc._tail_delay_sequence = [4300, 4350, 4400]
    proc._tail_delay_index = 2
    proc._tail_replicate_index = 0
    proc._tail_current_delay_us = 4400
    proc._tail_landmark_delay_us = 4750
    proc._tail_landmark_reason = "separated_from_nozzle"
    proc._tail_backtrack_left_delay_us = 4300
    proc._tail_scout_delay_summaries = [
        calibration_model.online_tail_mod.summarize_online_stream_tail_delay(
            [_accepted_tail_frame_row(proc, 1550, phase="tail_scout", width_px=70.0, landmark=True)],
            74.0,
        )
    ]
    proc._tail_backtrack_delay_summaries = [
        calibration_model.online_tail_mod.summarize_online_stream_tail_delay(
            [_accepted_tail_frame_row(proc, 1100, phase="tail_backtrack", width_px=74.0)],
            74.0,
        ),
        calibration_model.online_tail_mod.summarize_online_stream_tail_delay(
            [_accepted_tail_frame_row(proc, 1150, phase="tail_backtrack", width_px=70.0)],
            74.0,
        ),
    ]
    proc._tail_current_delay_frame_rows = [
        _accepted_tail_frame_row(proc, 1200, phase="tail_backtrack", width_px=66.0)
    ]

    proc.onAdvanceTailPhase()

    assert proc.tailPhaseFinished.calls
    assert "tail_right_extension_budget_exhausted" in proc._tail_fit_warnings
    assert proc._tail_delay_sequence == [4300, 4350, 4400]


def test_online_stream_backtrack_separation_without_early_departure_resolves_midpoint_tail(tmp_path):
    proc = _flow_proc(tmp_path)
    _seed_tail_flow_context(proc)
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_anchor_delay_us": 4250,
        "backtrack_step_us": 50,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
    }
    proc._tail_mode = "backtrack"
    proc._tail_delay_sequence = [4300]
    proc._tail_delay_index = 0
    proc._tail_replicate_index = 0
    proc._tail_current_delay_us = 4300
    proc._tail_landmark_delay_us = 4750
    proc._tail_landmark_reason = "separated_from_nozzle"
    proc._tail_backtrack_left_delay_us = 4300
    proc._tail_scout_delay_summaries = [
        {
            "delay_us": 4750,
            "delay_from_emergence_us": 1550,
            "attempted_replicates": 1,
            "accepted_replicates": 1,
            "tail_width_usable_replicates": 0,
            "tail_landmark_usable_replicates": 1,
            "rejected_replicates": 0,
            "median_width_px": None,
            "width_ratio_to_baseline": None,
            "tail_width_usable": False,
            "tail_landmark_usable": True,
            "separated_from_nozzle_landmark": True,
            "backup_width_collapse_landmark": False,
            "landmark_detected": True,
            "landmark_reason": "separated_from_nozzle",
            "warnings": [],
            "delay_accepted": True,
        }
    ]
    proc._tail_current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="tail_backtrack",
            status="accepted",
            delay_us=4300,
            delay_from_emergence_us=1100,
            replicate_index=1,
            qc={"tail_qc_pass": True, "tail_width_usable": True, "tail_landmark_usable": False},
            image_ref={"capture_id": "cap_tail"},
            warnings=[],
            attached_width_px=74.0,
            tail_width_usable=True,
            tail_landmark_usable=False,
            separated_from_nozzle_landmark=False,
        )
    ]

    proc.onAdvanceTailPhase()

    assert proc.tailPhaseFinished.calls
    assert proc._tail_phase_status == "captured"
    assert proc._tail_start_delay_from_emergence_us == 1325
    assert "tail_landmark_only" not in proc._tail_fit_warnings


def test_online_stream_backtrack_without_tail_plateau_uses_flow_anchor_fallback(tmp_path):
    proc = _flow_proc(tmp_path)
    _seed_tail_flow_context(proc)
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_anchor_delay_us": 4250,
        "backtrack_step_us": 50,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
    }
    proc._tail_mode = "backtrack"
    proc._tail_delay_sequence = [4300]
    proc._tail_delay_index = 0
    proc._tail_replicate_index = 0
    proc._tail_current_delay_us = 4300
    proc._tail_landmark_delay_us = 4750
    proc._tail_landmark_reason = "separated_from_nozzle"
    proc._tail_backtrack_left_delay_us = 4300
    proc._tail_left_bracket_confirmed = False
    proc._tail_left_bracket_extended = True
    proc._tail_scout_delay_summaries = [
        {
            "delay_us": 4750,
            "delay_from_emergence_us": 1550,
            "attempted_replicates": 1,
            "accepted_replicates": 1,
            "tail_width_usable_replicates": 0,
            "tail_landmark_usable_replicates": 1,
            "rejected_replicates": 0,
            "median_width_px": None,
            "width_ratio_to_baseline": None,
            "tail_width_usable": False,
            "tail_landmark_usable": True,
            "separated_from_nozzle_landmark": True,
            "backup_width_collapse_landmark": False,
            "landmark_detected": True,
            "landmark_reason": "separated_from_nozzle",
            "warnings": [],
            "delay_accepted": True,
        }
    ]
    proc._tail_current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="tail_backtrack",
            status="accepted",
            delay_us=4300,
            delay_from_emergence_us=1100,
            replicate_index=1,
            qc={"tail_qc_pass": True, "tail_width_usable": True, "tail_landmark_usable": False},
            image_ref={"capture_id": "cap_tail"},
            warnings=[],
            attached_width_px=73.0,
            tail_width_usable=True,
            tail_landmark_usable=False,
            separated_from_nozzle_landmark=False,
        )
    ]

    proc.onAdvanceTailPhase()

    assert proc.tailPhaseFinished.calls
    assert proc._tail_phase_status == "captured"
    assert proc._tail_start_delay_from_emergence_us == 1300
    assert proc._tail_synthetic_left_bracket_used is True


def test_online_stream_backtrack_without_tail_plateau_stays_unresolved_when_flow_anchor_is_not_plateau(tmp_path):
    proc = _flow_proc(tmp_path)
    _seed_tail_flow_context(proc)
    proc._flow_delay_summaries[-1]["median_width_px"] = 73.0
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_anchor_delay_us": 4250,
        "backtrack_step_us": 50,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
    }
    proc._tail_mode = "backtrack"
    proc._tail_delay_sequence = [4300]
    proc._tail_delay_index = 0
    proc._tail_replicate_index = 0
    proc._tail_current_delay_us = 4300
    proc._tail_landmark_delay_us = 4750
    proc._tail_landmark_reason = "separated_from_nozzle"
    proc._tail_backtrack_left_delay_us = 4300
    proc._tail_left_bracket_confirmed = False
    proc._tail_left_bracket_extended = True
    proc._tail_scout_delay_summaries = [
        {
            "delay_us": 4750,
            "delay_from_emergence_us": 1550,
            "attempted_replicates": 1,
            "accepted_replicates": 1,
            "tail_width_usable_replicates": 0,
            "tail_landmark_usable_replicates": 1,
            "rejected_replicates": 0,
            "median_width_px": None,
            "width_ratio_to_baseline": None,
            "tail_width_usable": False,
            "tail_landmark_usable": True,
            "separated_from_nozzle_landmark": True,
            "backup_width_collapse_landmark": False,
            "landmark_detected": True,
            "landmark_reason": "separated_from_nozzle",
            "warnings": [],
            "delay_accepted": True,
        }
    ]
    proc._tail_current_delay_frame_rows = [
        calibration_model.online_cal_mod.build_online_stream_frame_row(
            phase="tail_backtrack",
            status="accepted",
            delay_us=4300,
            delay_from_emergence_us=1100,
            replicate_index=1,
            qc={"tail_qc_pass": True, "tail_width_usable": True, "tail_landmark_usable": False},
            image_ref={"capture_id": "cap_tail"},
            warnings=[],
            attached_width_px=73.0,
            tail_width_usable=True,
            tail_landmark_usable=False,
            separated_from_nozzle_landmark=False,
        )
    ]

    proc.onAdvanceTailPhase()

    assert proc.tailPhaseFinished.calls
    assert proc._tail_phase_status == "unresolved_missing_left_bracket"
    assert proc._tail_start_delay_from_emergence_us is None
    assert proc._tail_synthetic_left_bracket_used is False


def test_online_stream_maybe_extend_tail_left_bracket_retargets_to_flow_anchor_once(tmp_path):
    proc = _flow_proc(tmp_path)
    _seed_tail_flow_context(proc)
    proc._tail_plan = {
        "steady_width_baseline_px": 74.0,
        "scout_anchor_delay_us": 4250,
        "backtrack_step_us": 50,
        "fine_prepad_us": 100,
        "fine_postpad_us": 100,
        "scout_replicates": 1,
        "backtrack_replicates": 1,
        "tail_retarget_count": 0,
        "retargeted_coarse_start_delay_us": None,
    }
    proc._tail_landmark_delay_us = 4750
    proc._tail_backtrack_left_delay_us = 4350
    proc._tail_left_bracket_extended = False
    proc._tail_backtrack_delay_summaries = []

    changed = proc._maybe_extend_tail_left_bracket()

    assert changed is True
    assert proc._tail_backtrack_left_delay_us == 4250
    assert proc._tail_left_bracket_extended is True
    assert proc._tail_plan["tail_retarget_count"] == 1
    assert proc._tail_plan["retargeted_coarse_start_delay_us"] == 4250
    assert proc._tail_delay_sequence
    assert proc._maybe_extend_tail_left_bracket() is False


def test_online_stream_on_restore_settings_maps_print_width_to_print_pulse_width():
    proc = OnlineStreamCalibrationProcess.__new__(OnlineStreamCalibrationProcess)
    proc._orig_settings = {
        "num_droplets": 1,
        "flash_delay": 4300,
        "print_pressure": 0.42,
        "print_width": 1350,
    }
    proc._restored_settings = False
    proc._settings_wait_cancel = None
    proc._restore_in_progress = False
    proc._restore_settings_confirmed = None
    proc.stageChanged = Recorder()
    proc.calibration_manager = SimpleNamespace(emitSettingsChangeCompleted=lambda *args, **kwargs: None)
    captured = {"settings": None, "context": None, "guard_timeout_ms": None}

    def _stub(settings, callback, *, context="", guard_timeout_ms=None, on_timeout=None):
        captured["settings"] = dict(settings)
        captured["context"] = str(context)
        captured["guard_timeout_ms"] = guard_timeout_ms
        return lambda: None

    proc._request_settings_with_recording = _stub

    proc.onRestoreSettings()

    assert captured["settings"] == {
        "num_droplets": 1,
        "flash_delay": 4300,
        "print_pressure": 0.42,
        "print_pulse_width": 1350,
    }
    assert captured["context"] == "online_stream_restore_settings"
    assert captured["guard_timeout_ms"] == 10_000


def test_online_stream_snapshot_original_settings_prefers_target_print_pressure():
    proc = OnlineStreamCalibrationProcess.__new__(OnlineStreamCalibrationProcess)
    proc.calibration_manager = SimpleNamespace(
        get_current_settings=lambda: {
            "num_droplets": 1,
            "flash_delay": 4300,
            "print_pressure": 0.79,
            "print_width": 1350,
        }
    )
    proc.model = SimpleNamespace(
        machine_model=SimpleNamespace(
            get_target_print_pressure=lambda: 0.80,
        )
    )

    snapshot = proc._snapshot_original_settings()

    assert snapshot == {
        "num_droplets": 1,
        "flash_delay": 4300,
        "print_pressure": 0.80,
        "print_width": 1350,
    }


def test_online_stream_restore_timeout_advances_final_without_clobbering_pending_stop():
    proc = OnlineStreamCalibrationProcess.__new__(OnlineStreamCalibrationProcess)
    proc._orig_settings = {
        "num_droplets": 1,
        "flash_delay": 4300,
        "print_pressure": 0.42,
        "print_width": 1350,
    }
    proc._restored_settings = False
    proc._stop_requested = True
    proc._stop_reason = "User requested stop"
    proc._settings_wait_cancel = None
    proc._pending_terminal_status = "stopped"
    proc._pending_terminal_error_message = "Calibration terminated by user"
    proc._restore_in_progress = False
    proc._restore_settings_confirmed = None
    proc.stageChanged = Recorder()
    proc.finalize = Recorder()
    proc.calibrationDataUpdated = Recorder()
    proc.calibrationCompleted = Recorder()
    proc.calibrationError = Recorder()
    proc.calibration_manager = SimpleNamespace(emitSettingsChangeCompleted=lambda *args, **kwargs: None)
    captured = {"on_timeout": None}

    def _stub(settings, callback, *, context="", guard_timeout_ms=None, on_timeout=None):
        captured["on_timeout"] = on_timeout
        return lambda: None

    proc._request_settings_with_recording = _stub

    proc.onRestoreSettings()
    captured["on_timeout"]()

    assert proc.finalize.calls
    assert proc._restore_settings_confirmed is False

    proc.onCompleted()

    assert proc.calibrationCompleted.calls == []
    assert proc.calibrationError.calls[-1][0][0] == "Calibration terminated by user"


def test_online_stream_on_completed_emits_stage5_payload_with_tail_result():
    proc = OnlineStreamCalibrationProcess.__new__(OnlineStreamCalibrationProcess)
    proc._stop_requested = False
    proc._background_capture_completed = True
    proc._settings_wait_cancel = None
    proc._pending_terminal_status = None
    proc._pending_terminal_error_message = ""
    proc._restore_in_progress = False
    proc._orig_settings = {
        "print_pressure": 0.42,
        "print_width": 1350,
    }
    proc.stock_solution = "water"
    proc.printer_head_id = "head_A"
    proc.emergence_time_us = 3200
    proc.priors = {"source": "default"}
    proc._prior_resolution = {
        "lookup_performed": True,
        "candidate_found": True,
        "source": "calibration_memory",
        "aggregation_level": "exact_pair",
        "pulse_match_type": "exact",
        "condition_match": "exact",
        "source_run_ids": ["seed_run_01"],
        "applied_flow_start_offset_us": 700,
        "applied_flow_step_us": 57,
        "applied_flow_delay_count": 15,
        "applied_tail_start_offset_us": 3950,
        "applied_tail_coarse_step_us": 100,
        "fallback_reason": None,
        "warnings": [],
    }
    proc.flow_plan = calibration_model.online_cal_mod.build_online_stream_flow_plan(
        emergence_time_us=3200,
        prior={"flow_start_offset_us": 650},
    )
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
            "nozzle_qc_pass": True,
            "silhouette_qc_pass": True,
            "attached_bottom_clearance_px": 150.0,
        }
    ]
    proc._flow_delay_summaries = [
        {
            "delay_us": 3850,
            "delay_from_emergence_us": 650,
            "attempted_replicates": 1,
            "accepted_replicates": 1,
            "rejected_replicates": 0,
            "median_visible_volume_nl": 12.3,
            "median_width_px": 91.5,
            "min_attached_bottom_clearance_px": 150.0,
            "detached_near_bottom_warning": False,
            "delay_accepted": True,
        },
        {
            "delay_us": 4050,
            "delay_from_emergence_us": 850,
            "attempted_replicates": 1,
            "accepted_replicates": 0,
            "rejected_replicates": 1,
            "median_visible_volume_nl": None,
            "median_width_px": None,
            "min_attached_bottom_clearance_px": None,
            "detached_near_bottom_warning": False,
            "delay_accepted": False,
        },
    ]
    proc._flow_mode = "ci_refine"
    proc._flow_delay_sequence = [3850, 4050]
    proc._flow_target_delay_offsets_from_emergence_us = [650, 850]
    proc._flow_captured_delay_offsets_from_emergence_us = [650, 850]
    proc._flow_scout_boundary_reason = "scout_cap_reached"
    proc._flow_right_boundary_delay_from_emergence_us = 850
    proc._flow_right_boundary_fixed = False
    proc._flow_hard_boundary_delay_from_emergence_us = None
    proc._flow_ci_refinement_count = 0
    proc._flow_fit_stop_reason = "candidate_delays_exhausted"
    proc._flow_preview_fit_result = {}
    proc._attempted_capture_count = 2
    proc._flow_termination_reason = "insufficient_accepted_delays"
    proc._flow_warnings = ["insufficient_accepted_delays"]
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
    proc._tail_fit_warnings = ["refine_trigger"]
    proc._tail_fit_result = {
        "tail_phase": {
            "status": "captured",
            "plan": {"coarse_start_delay_us": 7000},
            "attempted_delay_count": 3,
            "attempted_capture_count": 6,
            "accepted_delay_count": 3,
            "accepted_measurement_count": 4,
            "termination_reason": "refine_trigger",
            "coarse_delay_summaries": [{"delay_us": 7000}],
            "refine_delay_summaries": [{"delay_us": 7150}],
            "trigger_delay_from_emergence_us": 4000,
            "trigger_reason": "refine_width_frac_le_0.95",
            "last_nontrigger_delay_from_emergence_us": 3800,
            "tail_start_delay_from_emergence_us": 3950,
            "warnings": ["refine_trigger"],
        },
        "predicted_stream_duration_us": 3950,
        "predicted_volume_nl": 72.665,
        "warnings": ["refine_trigger"],
    }
    proc._predicted_stream_duration_us = 3950
    proc._predicted_volume_nl = 72.665
    proc.stageChanged = Recorder()
    proc.calibrationDataUpdated = Recorder()
    proc.calibrationCompleted = Recorder()
    proc.calibrationError = Recorder()
    proc.capture_budget = calibration_model.online_cal_mod.new_online_stream_budget()

    proc.onCompleted()

    assert proc.calibrationError.calls == []
    assert proc.calibrationCompleted.calls
    payload = proc.calibrationDataUpdated.calls[-1][0][0]
    assert len(payload["measurements"]) == 1
    assert payload["measurements"][0]["nozzle_qc_pass"] is True
    assert payload["measurements"][0]["silhouette_qc_pass"] is True
    assert payload["measurements"][0]["attached_bottom_clearance_px"] == 150.0
    result = payload["result"]
    assert result["priors"]["source"] == "calibration_memory"
    assert result["priors"]["aggregation_level"] == "exact_pair"
    assert result["priors"]["applied_flow_start_offset_us"] == 700
    assert result["flow_phase"]["status"] == "insufficient_data"
    assert result["flow_phase"]["attempted_capture_count"] == 2
    assert result["flow_phase"]["accepted_delay_count"] == 1
    assert result["flow_phase"]["delay_summaries"][0]["delay_us"] == 3850
    assert result["flow_phase"]["termination_reason"] == "insufficient_accepted_delays"
    assert result["flow_phase"]["fit_stop_reason"] == "candidate_delays_exhausted"
    assert result["flow_phase"]["fit_status"] == "warning_min_points_only"
    assert result["flow_phase"]["flow_rate_nl_per_us"] == 0.0187
    assert result["flow_phase"]["fit_warnings"] == ["flow_fit_min_points_only"]
    assert result["tail_phase"]["status"] == "captured"
    assert result["predicted_stream_duration_us"] == 3950
    assert result["predicted_volume_nl"] == 72.665
    assert "insufficient_accepted_delays" in result["warnings"]


def test_online_stream_end_to_end_emits_stage4_partial_then_final_payload(tmp_path, monkeypatch):
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
            "nozzle_qc_pass": True,
            "silhouette_qc_pass": True,
            "attached_bottom_clearance_px": 150.0,
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
    proc._attempted_capture_count = 3
    proc._flow_mode = "ci_refine"
    proc._flow_delay_sequence = [3850, 4050, 4250]
    proc._flow_target_delay_offsets_from_emergence_us = [650, 850, 1050]
    proc._flow_captured_delay_offsets_from_emergence_us = [650, 850, 1050]
    proc._flow_scout_boundary_reason = "scout_cap_reached"
    proc._flow_right_boundary_delay_from_emergence_us = 1050
    proc._flow_right_boundary_fixed = False
    proc._flow_hard_boundary_delay_from_emergence_us = None
    proc._flow_ci_refinement_count = 0
    proc._flow_fit_stop_reason = "candidate_delays_exhausted"
    proc._flow_preview_fit_result = {}

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

    proc._tail_fit_warnings = ["refine_trigger"]
    proc._tail_fit_result = {
        "tail_phase": {
            "status": "captured",
            "plan": {"coarse_start_delay_us": 7000},
            "attempted_delay_count": 3,
            "attempted_capture_count": 6,
            "accepted_delay_count": 3,
            "accepted_measurement_count": 4,
            "termination_reason": "refine_trigger",
            "coarse_delay_summaries": [{"delay_us": 7000}],
            "refine_delay_summaries": [{"delay_us": 7150}],
            "trigger_delay_from_emergence_us": 4000,
            "trigger_reason": "refine_width_frac_le_0.95",
            "last_nontrigger_delay_from_emergence_us": 3800,
            "tail_start_delay_from_emergence_us": 3950,
            "warnings": ["refine_trigger"],
        },
        "predicted_stream_duration_us": 3950,
        "predicted_volume_nl": 72.665,
        "warnings": ["refine_trigger"],
    }
    proc._predicted_stream_duration_us = 3950
    proc._predicted_volume_nl = 72.665

    proc.onCompleted()

    assert len(proc.calibrationDataUpdated.calls) == 2
    stage4_payload = proc.calibrationDataUpdated.calls[0][0][0]
    final_payload = proc.calibrationDataUpdated.calls[1][0][0]
    assert stage4_payload["result"]["tail_phase"] == {"status": "not_run", "plan": {}}
    assert stage4_payload["result"]["predicted_stream_duration_us"] is None
    assert final_payload["result"]["tail_phase"]["status"] == "captured"
    assert final_payload["result"]["predicted_stream_duration_us"] == 3950
    assert proc.calibrationCompleted.calls


def test_online_stream_graceful_stop_does_not_emit_success_payload():
    proc = OnlineStreamCalibrationProcess.__new__(OnlineStreamCalibrationProcess)
    proc._stop_requested = False
    proc._stop_reason = None
    proc._settings_wait_cancel = None
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


def test_online_stream_guarded_settings_timeout_records_bound_snapshot_and_late_completion(tmp_path):
    proc = _flow_proc(tmp_path)
    recorded_events = []
    timeout_state = {}

    class _SettingsSignal:
        def __init__(self):
            self.calls = []

        def emit(self, settings, callback):
            self.calls.append((dict(settings), callback))

    proc.calibration_manager.changeSettingsRequested = _SettingsSignal()
    proc.calibration_manager.record_process_event = (
        lambda event_type, payload, **kwargs: recorded_events.append(
            {"event_type": str(event_type), "payload": dict(payload or {}), "kwargs": dict(kwargs or {})}
        )
    )
    proc._cancel_timeout = lambda timer: timeout_state.setdefault("cancelled", []).append(timer)

    def _start_timeout(timeout_ms, err_msg=None, on_timeout=None):
        timeout_state["timeout_ms"] = timeout_ms
        timeout_state["handler"] = on_timeout
        return "settings-timer"

    proc._start_timeout = _start_timeout

    proc._request_guarded_settings_update(
        {"flash_delay": 6000, "num_droplets": 1},
        lambda: None,
        context="online_stream_apply_flow_delay",
        timeout_message="settings timed out",
    )

    assert proc.calibration_manager.changeSettingsRequested.calls
    settings, wrapped = proc.calibration_manager.changeSettingsRequested.calls[0]
    assert settings == {"flash_delay": 6000, "num_droplets": 1}
    assert wrapped._settings_request_id

    provider_state = {"stall_hint": "state_matches_settings_but_completion_missing", "completion_status": "Sent", "completed_ms": None}
    wrapped._settings_bind_callback(
        {
            "request_id": wrapped._settings_request_id,
            "context": "online_stream_apply_flow_delay",
            "settings": settings,
            "commands": [
                {
                    "command_number": 11,
                    "command_type": "SET_DELAY_F",
                    "setting_key": "flash_delay",
                    "requested_value": 6000,
                },
                {
                    "command_number": 12,
                    "command_type": "SET_IMAGE_DROPLETS",
                    "setting_key": "num_droplets",
                    "requested_value": 1,
                },
            ],
            "completion_command_number": 12,
        }
    )
    wrapped._settings_trace_provider = lambda: {
        "request_id": wrapped._settings_request_id,
        "context": "online_stream_apply_flow_delay",
        "requested_settings": dict(settings),
        "timeout_ms": timeout_state["timeout_ms"],
        "commands": [
            {
                "command_number": 11,
                "command_type": "SET_DELAY_F",
                "setting_key": "flash_delay",
                "requested_value": 6000,
                "status": "Completed",
                "queued_ms": 0.0,
                "sent_ms": 1.0,
                "executing_ms": 5.0,
                "completed_ms": 7.0,
            },
            {
                "command_number": 12,
                "command_type": "SET_IMAGE_DROPLETS",
                "setting_key": "num_droplets",
                "requested_value": 1,
                "status": provider_state["completion_status"],
                "queued_ms": 0.0,
                "sent_ms": 2.0,
                "executing_ms": None,
                "completed_ms": provider_state["completed_ms"],
            },
        ],
        "latest_status": {
            "Current_command": 12,
            "Last_completed": 11,
            "cmd_depth": 1,
            "Flash_delay": 6000,
            "Flash_droplets": 1,
            "rx_to_main_thread_ms": 0.4,
        },
        "recent_status": [
            {
                "Current_command": 12,
                "Last_completed": 11,
                "cmd_depth": 1,
                "Flash_delay": 6000,
                "Flash_droplets": 1,
                "rx_to_main_thread_ms": 0.4,
                "observed_ms": 9.0,
            }
        ],
        "recent_command_events": [
            {
                "event": "sent",
                "command_number": 12,
                "command_type": "SET_IMAGE_DROPLETS",
                "setting_key": "num_droplets",
                "requested_value": 1,
                "status": "Sent",
                "observed_ms": 2.0,
            }
        ],
        "stall_hint": provider_state["stall_hint"],
    }

    timeout_state["handler"]()
    provider_state["stall_hint"] = "late_completion_after_timeout"
    provider_state["completion_status"] = "Completed"
    provider_state["completed_ms"] = 10.0
    wrapped()

    event_types = [event["event_type"] for event in recorded_events]
    assert "settings_requested" in event_types
    assert "settings_bound" in event_types
    assert "settings_timeout" in event_types
    assert "settings_completed_ignored" in event_types

    timeout_event = next(event for event in recorded_events if event["event_type"] == "settings_timeout")
    assert timeout_event["payload"]["request_id"] == wrapped._settings_request_id
    assert timeout_event["payload"]["diagnostic_snapshot"]["stall_hint"] == "state_matches_settings_but_completion_missing"
    assert timeout_event["payload"]["diagnostic_snapshot"]["commands"][-1]["command_number"] == 12

    ignored_event = next(event for event in recorded_events if event["event_type"] == "settings_completed_ignored")
    assert ignored_event["payload"]["request_id"] == wrapped._settings_request_id
    assert ignored_event["payload"]["late_completion_ms"] is not None
    assert ignored_event["payload"]["diagnostic_snapshot"]["stall_hint"] == "late_completion_after_timeout"
