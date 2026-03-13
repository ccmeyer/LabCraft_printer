from types import SimpleNamespace

import numpy as np

from tests.calibration_test_utils import Recorder, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import PressureTrajectoryCalibrationProcess  # noqa: E402


def test_pressure_trajectory_missing_requirements_primary_band_optional_with_explicit_pressures():
    cm = SimpleNamespace(
        get_nozzle_center=lambda: {"X": 0, "Y": 0, "Z": 0},
        get_real_nozzle_center_image_position=lambda: (100, 100),
        get_background_image=lambda: np.zeros((64, 64), dtype=np.uint8),
        get_emergence_time=lambda: 4500,
        get_primary_pressure_band=lambda: None,
    )

    req_default = PressureTrajectoryCalibrationProcess.missing_requirements(cm)
    req_explicit = PressureTrajectoryCalibrationProcess.missing_requirements(
        cm,
        require_primary_band=False,
    )

    assert "Primary pressure band" in req_default
    assert req_explicit == []


def test_pressure_trajectory_missing_requirements_accepts_prebreakup_published_band():
    cm = SimpleNamespace(
        get_nozzle_center=lambda: {"X": 0, "Y": 0, "Z": 0},
        get_real_nozzle_center_image_position=lambda: (100, 100),
        get_background_image=lambda: np.zeros((64, 64), dtype=np.uint8),
        get_emergence_time=lambda: 4500,
        get_primary_pressure_band=lambda: (0.41, 0.47),
    )

    req_default = PressureTrajectoryCalibrationProcess.missing_requirements(cm)

    assert req_default == []


def test_pressure_trajectory_settings_timeout_emits_error_and_finalizes():
    proc = PressureTrajectoryCalibrationProcess.__new__(PressureTrajectoryCalibrationProcess)
    proc.settings_timeout_ms = 12000
    proc.calibrationError = Recorder()
    proc.finalize = Recorder()
    proc._record_error = lambda *args, **kwargs: None
    proc._cancel_timeout = lambda *_args, **_kwargs: None
    proc._request_settings_with_recording = lambda _settings, _cb, context=None: None

    def _start_timeout(_ms, *, on_timeout=None, **_kwargs):
        if callable(on_timeout):
            on_timeout()
        return "timer"

    proc._start_timeout = _start_timeout

    proc._request_settings_with_timeout(
        {"num_droplets": 0},
        on_done=lambda: None,
        context="unit_test_timeout",
    )

    assert proc.calibrationError.calls
    assert proc.finalize.calls


def test_pressure_trajectory_multiple_on_single_replicate_disqualifies_and_retests_lower():
    proc = PressureTrajectoryCalibrationProcess.__new__(PressureTrajectoryCalibrationProcess)
    proc._discard_next = False
    proc._current_pressure = 1.20
    proc.d_index = 0
    proc.delays_us = [6000]
    proc.nozzle_center_px = (100, 100)
    proc.background_image = np.zeros((220, 220), dtype=np.uint8)
    proc.droplet_image = np.zeros((220, 220), dtype=np.uint8)
    proc.edge_guard_px = 60
    proc._rep_buffer = []
    proc._rep_count = 0
    proc._failed_caps_this_delay = 0
    proc._miss_streak = 0
    proc._stop_delays_after_this = False
    proc._max_delay_allowed_us = None
    proc._pending_pressure_adjustment = None
    proc._pending_adjust_reason = None
    proc._pending_adjust_payload = {}
    proc._disqualified_pressures = []
    proc.points = []
    proc.samples = []
    proc.stageChanged = Recorder()
    proc.presentImageSignal = Recorder()
    proc.timepointReady = Recorder()
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplets=lambda *args, **kwargs: (
                [(120, 420), (150, 430)],
                0,
                np.zeros((220, 220, 3), dtype=np.uint8),
                {"source": "test"},
            )
        )
    )

    proc.onAnalyzeTimepoint()

    restart_calls = []
    proc._restart_current_pressure_with = lambda new_p, reason: restart_calls.append(
        (float(new_p), str(reason))
    )

    proc.onDecide()

    assert proc.timepointReady.calls
    assert restart_calls
    assert restart_calls[0][1] == "multiple_droplets"
    assert restart_calls[0][0] < 1.20
    assert proc.samples
    assert proc.samples[-1]["disqualified"] is True
    assert proc.samples[-1]["reason"] == "multiple_droplets"


def test_pressure_trajectory_adjustment_limit_skips_slot():
    proc = PressureTrajectoryCalibrationProcess.__new__(PressureTrajectoryCalibrationProcess)
    proc.model = SimpleNamespace(
        machine_model=SimpleNamespace(get_print_pressure_bounds=lambda: (0.3, 5.0))
    )
    proc._adjust_attempts_at_pressure = 1
    proc._adjust_attempts_limit = 1
    proc._current_pressure = 1.00
    proc.points = []
    proc.samples = []
    proc._pending_pressure_adjustment = 0.99
    proc._pending_adjust_reason = "multiple_droplets"
    proc._pending_adjust_payload = {"k": 1}
    proc.stageChanged = Recorder()
    finish_calls = []
    proc._finish_pressure_and_advance = lambda: finish_calls.append(True)

    proc._restart_current_pressure_with(0.99, reason="multiple_droplets")

    assert finish_calls
    assert proc.samples
    assert proc.samples[-1]["fit"] is None
    assert str(proc.samples[-1]["reason"]).startswith("skipped_after_")
    assert proc._pending_adjust_reason is None
    assert proc._pending_adjust_payload == {}


def test_pressure_trajectory_restart_resets_working_delays_to_base():
    proc = PressureTrajectoryCalibrationProcess.__new__(PressureTrajectoryCalibrationProcess)
    proc.model = SimpleNamespace(
        machine_model=SimpleNamespace(get_print_pressure_bounds=lambda: (0.3, 5.0))
    )
    proc._adjust_attempts_at_pressure = 0
    proc._adjust_attempts_limit = 5
    proc.p_index = 0
    proc.pressures = [1.10]
    proc._current_pressure = 1.10
    proc._base_delays_us = [5000, 5700, 6400]
    proc.delays_us = [4500, 5000, 5700, 6400]
    proc.points = [{"t_us": 5000, "center_px": (4.0, 12.0)}]
    proc._completed = [True, False, False, False]
    proc._reset_delay_state = lambda: None
    proc._miss_streak = 1
    proc._stop_delays_after_this = True
    proc._max_delay_allowed_us = 5400
    proc._pending_pressure_adjustment = 1.09
    proc._pending_adjust_reason = "multiple_droplets"
    proc._pending_adjust_payload = {"x": 1}
    proc.discard_first_after_pressure = True
    proc.reapplyPressure = Recorder()

    proc._restart_current_pressure_with(1.09, reason="multiple_droplets")

    assert proc.pressures[0] == 1.09
    assert proc.delays_us == [5000, 5700, 6400]
    assert proc._completed == [False, False, False]
    assert proc.reapplyPressure.calls
    assert proc._adjust_attempts_at_pressure == 1


def test_pressure_trajectory_true_ejection_check_requires_downward_motion():
    proc = PressureTrajectoryCalibrationProcess.__new__(PressureTrajectoryCalibrationProcess)
    proc._min_radial_growth_px = 4.0
    proc._min_downward_growth_px = 6.0
    proc._min_downward_slope_px_per_us = 0.0010
    proc._reverse_step_px = 1.0

    proc.points = [
        {"t_us": 5000, "center_px": (2.0, 10.0)},
        {"t_us": 5700, "center_px": (3.0, 18.0)},
        {"t_us": 6400, "center_px": (4.0, 28.0)},
    ]
    assert proc._should_raise_low_pressure_due_to_retraction() is False

    proc.points = [
        {"t_us": 5000, "center_px": (2.0, 14.0)},
        {"t_us": 5700, "center_px": (3.0, 12.0)},
        {"t_us": 6400, "center_px": (4.0, 9.0)},
    ]
    assert proc._should_raise_low_pressure_due_to_retraction() is True


def test_pressure_trajectory_retraction_check_requires_multi_delay_evidence():
    proc = PressureTrajectoryCalibrationProcess.__new__(PressureTrajectoryCalibrationProcess)
    proc._min_radial_growth_px = 4.0
    proc._min_downward_growth_px = 6.0
    proc._min_downward_slope_px_per_us = 0.0010
    proc._reverse_step_px = 1.0
    proc._min_points_for_retraction_check = 2
    proc._min_delay_span_us_for_retraction = 300

    proc.points = [{"t_us": 5950, "center_px": (2.0, 14.0)}]
    assert proc._trajectory_has_min_retraction_evidence() is False
    assert proc._should_raise_low_pressure_due_to_retraction() is False

    proc.points = [
        {"t_us": 5950, "center_px": (2.0, 14.0)},
        {"t_us": 5950, "center_px": (3.0, 12.0)},
    ]
    assert proc._trajectory_has_min_retraction_evidence() is False
    assert proc._should_raise_low_pressure_due_to_retraction() is False

    proc.points = [
        {"t_us": 5950, "center_px": (2.0, 14.0)},
        {"t_us": 6300, "center_px": (3.0, 12.0)},
    ]
    assert proc._trajectory_has_min_retraction_evidence() is True
    assert proc._should_raise_low_pressure_due_to_retraction() is True


def test_pressure_trajectory_on_decide_does_not_retest_pressure_after_first_point():
    proc = PressureTrajectoryCalibrationProcess.__new__(PressureTrajectoryCalibrationProcess)
    proc._pending_pressure_adjustment = None
    proc._pending_adjust_reason = None
    proc._pending_adjust_payload = {}
    proc._failed_caps_this_delay = 0
    proc.max_failed_captures_per_delay = 4
    proc._rep_count = 3
    proc.replicates_per_delay = 3
    proc._analyze_good = True
    proc._rep_buffer = [(8.0, 14.0), (9.0, 15.0), (8.0, 15.0)]
    proc.delays_us = [5950, 6650, 7350]
    proc.d_index = 0
    proc.points = []
    proc._completed = [False, False, False]
    proc._stop_delays_after_this = False
    proc._max_delay_allowed_us = None
    proc._miss_streak = 0
    proc.miss_streak_limit = 2
    proc.min_points = 3
    proc._current_pressure = 0.91
    proc._low_pressure_adjusted_this_pressure = False
    proc._min_points_for_retraction_check = 2
    proc._min_delay_span_us_for_retraction = 300
    proc._edge_close_now = False
    proc.stageChanged = Recorder()
    proc.setNextDelay = Recorder()
    proc.continueCapture = Recorder()
    proc._record_decision = lambda *args, **kwargs: None
    finish_calls = []
    restart_calls = []
    proc._finish_pressure_and_advance = lambda: finish_calls.append(True)
    proc._restart_current_pressure_with = lambda new_p, reason: restart_calls.append((new_p, reason))

    proc.onDecide()

    assert restart_calls == []
    assert finish_calls == []
    assert len(proc.points) == 1
    assert proc._completed[0] is True
    assert proc.setNextDelay.calls


def test_pressure_trajectory_completion_errors_when_no_valid_fit():
    proc = PressureTrajectoryCalibrationProcess.__new__(PressureTrajectoryCalibrationProcess)
    proc.samples = [
        {"pressure": 1.00, "points": [], "fit": None, "reason": "insufficient_points"},
        {"pressure": 0.95, "points": [], "fit": None, "reason": "multiple_droplets"},
    ]
    proc._base_delays_us = [5000, 5700, 6400]
    proc.nozzle_center_px = (100, 100)
    proc.emergence_time_us = 4500
    proc.calibrationError = Recorder()
    proc.calibrationDataUpdated = Recorder()
    proc.calibrationCompleted = Recorder()
    proc.stageChanged = Recorder()
    proc._record_error = lambda *args, **kwargs: None
    proc.calibration_manager = SimpleNamespace(
        get_primary_pressure_band=lambda: (0.9, 1.1),
        set_pressure_trajectory_result=lambda _payload: (_ for _ in ()).throw(
            AssertionError("should not persist invalid trajectory result")
        ),
    )

    proc.onCalibrationCompleted()

    assert proc.calibrationError.calls
    assert proc.calibrationDataUpdated.calls == []
    assert proc.calibrationCompleted.calls == []


def test_pressure_trajectory_completion_publishes_valid_fit_band_fields():
    proc = PressureTrajectoryCalibrationProcess.__new__(PressureTrajectoryCalibrationProcess)
    proc.samples = [
        {
            "pressure": 1.10,
            "points": [{"t_us": 5000, "center_px": (1.0, 2.0)}],
            "fit": {"vx_px_per_us": 0.01, "vy_px_per_us": 0.02},
        },
        {
            "pressure": 1.00,
            "points": [{"t_us": 5000, "center_px": (1.0, 2.0)}],
            "fit": None,
            "reason": "multiple_droplets",
            "disqualified": True,
        },
        {
            "pressure": 0.95,
            "points": [{"t_us": 5000, "center_px": (1.0, 2.0)}],
            "fit": {"vx_px_per_us": 0.02, "vy_px_per_us": 0.03},
        },
    ]
    proc._base_delays_us = [5000, 5700, 6400]
    proc.nozzle_center_px = (100, 100)
    proc.emergence_time_us = 4500
    proc.calibrationError = Recorder()
    proc.calibrationDataUpdated = Recorder()
    proc.calibrationCompleted = Recorder()
    proc.stageChanged = Recorder()
    proc._record_error = lambda *args, **kwargs: None
    persisted = []
    proc.calibration_manager = SimpleNamespace(
        get_primary_pressure_band=lambda: (0.9, 1.2),
        set_pressure_trajectory_result=lambda payload: persisted.append(dict(payload)),
    )

    proc.onCalibrationCompleted()

    assert not proc.calibrationError.calls
    assert proc.calibrationCompleted.calls
    assert proc.calibrationDataUpdated.calls
    payload = proc.calibrationDataUpdated.calls[-1][0][0]["result"]
    assert payload["valid_fit_count"] == 2
    assert payload["valid_fit_pressures"] == [0.95, 1.1]
    assert payload["trajectory_pressure_band"] == [0.95, 1.1]
    assert payload["disqualified_pressures"] == [1.0]
    assert persisted
