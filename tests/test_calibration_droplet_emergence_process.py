from types import SimpleNamespace

import cv2
import numpy as np

from tests.calibration_test_utils import Recorder, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import (  # noqa: E402
    CalibrationManager,
    DropletCameraModel,
    DropletEmergenceCalibrationProcess,
)


def _ready_cm():
    return SimpleNamespace(
        get_nozzle_center=lambda: {"X": 1, "Y": 2, "Z": 3},
        get_nozzle_center_image_position=lambda: (120, 80),
        model=SimpleNamespace(
            machine_model=SimpleNamespace(get_current_position_dict=lambda: {"X": 0, "Y": 0, "Z": 0}),
            droplet_camera_model=SimpleNamespace(get_image_size=lambda: (1280, 1024)),
        ),
    )


def _camera_stub():
    cam = DropletCameraModel.__new__(DropletCameraModel)
    cam._k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    return cam


def test_droplet_emergence_missing_requirements_reports_dependencies():
    cm = _ready_cm()
    cm.get_nozzle_center = lambda: None
    cm.get_nozzle_center_image_position = lambda: None
    cm.model.machine_model.get_current_position_dict = lambda: (_ for _ in ()).throw(RuntimeError("no pos"))
    cm.model.droplet_camera_model.get_image_size = lambda: (_ for _ in ()).throw(RuntimeError("no camera"))

    missing = DropletEmergenceCalibrationProcess.missing_requirements(cm)

    joined = " | ".join(missing).lower()
    assert "nozzle center" in joined
    assert "image position" in joined
    assert "machine position" in joined
    assert "droplet camera" in joined


def test_droplet_emergence_missing_requirements_ready_case_is_empty():
    missing = DropletEmergenceCalibrationProcess.missing_requirements(_ready_cm())
    assert missing == []


def test_start_droplet_emergence_uses_try_start_process():
    mgr = CalibrationManager.__new__(CalibrationManager)
    called = {"proc_cls": None}

    def _stub(proc_cls, *args, **kwargs):
        called["proc_cls"] = proc_cls
        return True

    mgr._try_start_process = _stub
    CalibrationManager.start_droplet_emergence_calibration(mgr)

    assert called["proc_cls"] is DropletEmergenceCalibrationProcess


def test_calc_emergence_area_prefers_attached_candidate_when_multiple_exist():
    cam = _camera_stub()
    bg = np.full((320, 320, 3), 220, dtype=np.uint8)
    img = bg.copy()

    # Attached stream crossing nozzle y.
    cv2.rectangle(img, (146, 74), (174, 118), (20, 20, 20), -1)
    # Detached blob below nozzle; larger area should still be down-ranked.
    cv2.rectangle(img, (120, 150), (210, 245), (20, 20, 20), -1)

    area, center, _overlay, details = cam.calc_emergence_area(
        bg,
        img,
        nozzle_center=(160, 80),
        return_details=True,
    )

    assert area is not None and area > 0
    assert center is not None
    assert details["status"] == "ok"
    assert details["contour_class"] == "attached"
    assert abs(int(center[0]) - 160) <= 20
    assert int(center[1]) < 130


def test_emergence_finish_success_does_not_overwrite_nozzle_image_position():
    proc = DropletEmergenceCalibrationProcess.__new__(DropletEmergenceCalibrationProcess)
    proc.stageChanged = Recorder()
    proc.dropletDetected = Recorder()
    proc.selected_area = None
    proc.selected_center_px = None
    proc.selected_quality = {}
    proc.candidate_delay = 3200

    calls = {"machine_center": [], "image_center": [], "emergence_center": []}
    proc.calibration_manager = SimpleNamespace(
        set_nozzle_center=lambda p: calls["machine_center"].append(dict(p)),
        set_nozzle_center_image_position=lambda p: calls["image_center"].append(tuple(p)),
        set_emergence_nozzle_center_image_position=lambda p: calls["emergence_center"].append(tuple(p)),
    )
    proc.model = SimpleNamespace(
        machine_model=SimpleNamespace(get_current_position_dict=lambda: {"X": 10, "Y": 20, "Z": 30})
    )
    proc._record_decision = lambda *args, **kwargs: None

    proc._finish_success(
        4100,
        {
            "center": (159, 92),
            "contour_class": "attached",
            "replicate_count": 3,
        },
    )

    assert len(calls["machine_center"]) == 1
    assert calls["machine_center"][0] == {"X": 10, "Y": 20, "Z": 30}
    assert calls["image_center"] == []
    assert calls["emergence_center"] == [(159, 92)]
    assert proc.selected_area == 4100
    assert proc.selected_center_px == (159, 92)
    assert proc.selected_quality["contour_class"] == "attached"
    assert proc.dropletDetected.calls


def test_on_analyze_accepts_target_area_even_when_classified_detached():
    proc = DropletEmergenceCalibrationProcess.__new__(DropletEmergenceCalibrationProcess)
    proc.stageChanged = Recorder()
    proc.presentImageSignal = Recorder()
    proc.continueSearch = Recorder()
    proc.replicateContinue = Recorder()
    proc.background_image = np.zeros((24, 24, 3), dtype=np.uint8)
    proc.droplet_image = np.zeros((24, 24, 3), dtype=np.uint8)
    proc.nozzle_center_px = (12, 6)
    proc._eval_count = 0
    proc._phase = "fine_adjust"
    proc._prev_area = None
    proc._rep_areas = []
    proc._replicate_details = []
    proc._last_agg_details = {}
    proc._trend_noise_events = 0
    proc.measurements = []
    proc.candidate_delay = 3200
    proc.phase_name = "droplet_emergence"
    proc.MIN_AREA = 3000
    proc.MAX_AREA = 8000
    seen = {"kwargs": None}

    def _calc_emergence_area(*args, **kwargs):
        seen["kwargs"] = dict(kwargs)
        return (
            4200,
            (13, 11),
            np.zeros((24, 24, 3), dtype=np.uint8),
            {"contour_class": "detached"},
        )

    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(calc_emergence_area=_calc_emergence_area)
    )
    proc._required_replicates_for_phase = lambda: 1
    proc._can_accept_replicates_early = lambda: True
    proc._aggregate_replicates = lambda: (
        4200,
        {
            "contour_class": "detached",
            "center": (13, 11),
            "replicate_count": 1,
            "replicate_cv": 0.0,
            "replicate_range": 0.0,
        },
    )
    proc._record_analysis = lambda payload: None
    proc._set_next_delay = lambda *_args, **_kwargs: None
    proc._fail = lambda msg: (_ for _ in ()).throw(AssertionError(f"unexpected fail: {msg}"))

    accepted = {"called": False, "area": None, "cls": None}

    def _finish(area, agg):
        accepted["called"] = True
        accepted["area"] = int(area)
        accepted["cls"] = str(agg.get("contour_class"))

    proc._finish_success = _finish

    proc.onAnalyze()

    assert accepted["called"] is True
    assert accepted["area"] == 4200
    assert accepted["cls"] == "detached"
    assert proc.continueSearch.calls == []
    assert seen["kwargs"] is not None
    assert seen["kwargs"].get("nozzle_center", None) is None


def test_set_next_delay_does_not_apply_extra_nudge():
    proc = DropletEmergenceCalibrationProcess.__new__(DropletEmergenceCalibrationProcess)
    proc.stageChanged = Recorder()
    proc.DELAY_MIN = 1500
    proc.DELAY_MAX = 8000
    proc.FINE_STEP = 100
    proc.candidate_delay = 3100
    proc._last_delay = 3000

    proc._set_next_delay(3000)

    assert proc.candidate_delay == 3000


def test_emergence_scan_down_overshoot_uses_bracket_midpoint():
    proc = DropletEmergenceCalibrationProcess.__new__(DropletEmergenceCalibrationProcess)
    proc.stageChanged = Recorder()
    proc.presentImageSignal = Recorder()
    proc.continueSearch = Recorder()
    proc.replicateContinue = Recorder()
    proc.background_image = np.zeros((24, 24, 3), dtype=np.uint8)
    proc.droplet_image = np.zeros((24, 24, 3), dtype=np.uint8)
    proc.nozzle_center_px = (12, 6)
    proc._eval_count = 1
    proc._phase = "scan_down"
    proc._prev_area = 9100
    proc._rep_areas = []
    proc._replicate_details = []
    proc._last_agg_details = {}
    proc._trend_noise_events = 0
    proc.measurements = []
    proc.candidate_delay = 3000
    proc.phase_name = "droplet_emergence"
    proc.MIN_AREA = 3000
    proc.MAX_AREA = 8000
    proc.FINE_STEP = 100
    proc.COARSE_STEP = 500
    proc.MONO_TOL_FRAC = 0.10
    proc.MAX_EVALS = 50
    proc._above_band_candidate = {"delay": 3500, "area": 9100, "agg": {"replicate_cv": 0.02}}
    proc._below_band_candidate = None
    proc._best_candidate = {"delay": 3500, "area": 9100, "agg": {"replicate_cv": 0.02}}
    proc._recent_delay_history = [3500]
    proc._last_delay = 3500

    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            calc_emergence_area=lambda *args, **kwargs: (
                2500,
                (13, 11),
                np.zeros((24, 24, 3), dtype=np.uint8),
                {"contour_class": "detached"},
            )
        )
    )
    proc._required_replicates_for_phase = lambda: 1
    proc._can_accept_replicates_early = lambda: True
    proc._aggregate_replicates = lambda: (
        2500,
        {
            "contour_class": "detached",
            "center": (13, 11),
            "replicate_count": 1,
            "replicate_cv": 0.03,
            "replicate_range": 0.0,
        },
    )
    proc._record_analysis = lambda payload: None
    proc._record_decision = lambda *args, **kwargs: None
    proc._fail = lambda msg: (_ for _ in ()).throw(AssertionError(f"unexpected fail: {msg}"))
    chosen = {"delay": None}
    proc._set_next_delay = lambda d: chosen.__setitem__("delay", int(d))
    proc._finish_success = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected finish"))

    proc.onAnalyze()

    assert proc._phase == "fine_adjust"
    assert chosen["delay"] == 3300
    assert proc.continueSearch.calls


def test_emergence_fine_adjust_bracket_collapse_selects_best_candidate():
    proc = DropletEmergenceCalibrationProcess.__new__(DropletEmergenceCalibrationProcess)
    proc.stageChanged = Recorder()
    proc.presentImageSignal = Recorder()
    proc.continueSearch = Recorder()
    proc.replicateContinue = Recorder()
    proc.background_image = np.zeros((24, 24, 3), dtype=np.uint8)
    proc.droplet_image = np.zeros((24, 24, 3), dtype=np.uint8)
    proc.nozzle_center_px = (12, 6)
    proc._eval_count = 3
    proc._phase = "fine_adjust"
    proc._prev_area = None
    proc._rep_areas = []
    proc._replicate_details = []
    proc._last_agg_details = {}
    proc._trend_noise_events = 0
    proc.measurements = []
    proc.candidate_delay = 3200
    proc.phase_name = "droplet_emergence"
    proc.MIN_AREA = 3000
    proc.MAX_AREA = 8000
    proc.FINE_STEP = 100
    proc.MONO_TOL_FRAC = 0.10
    proc.MAX_EVALS = 50
    proc._above_band_candidate = None
    proc._below_band_candidate = {"delay": 3100, "area": 2975, "agg": {"replicate_cv": 0.02}}
    proc._best_candidate = {"delay": 3100, "area": 2975, "agg": {"replicate_cv": 0.02}}
    proc._recent_delay_history = [3500, 3000, 3100, 3200]
    proc._last_delay = 3100

    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            calc_emergence_area=lambda *args, **kwargs: (
                8100,
                (13, 11),
                np.zeros((24, 24, 3), dtype=np.uint8),
                {"contour_class": "attached"},
            )
        )
    )
    proc._required_replicates_for_phase = lambda: 1
    proc._can_accept_replicates_early = lambda: True
    proc._aggregate_replicates = lambda: (
        8100,
        {
            "contour_class": "attached",
            "center": (13, 11),
            "replicate_count": 1,
            "replicate_cv": 0.04,
            "replicate_range": 0.0,
        },
    )
    proc._record_analysis = lambda payload: None
    proc._record_decision = lambda *args, **kwargs: None
    proc._set_next_delay = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected next delay"))
    proc._fail = lambda msg: (_ for _ in ()).throw(AssertionError(f"unexpected fail: {msg}"))

    finished = {"area": None, "delay": None, "decision_type": None, "stage_message": None}

    def _finish(area, agg, *, decision_type="emergence_target_reached", stage_message="Target area window reached"):
        finished["area"] = int(area)
        finished["delay"] = int(proc.candidate_delay)
        finished["decision_type"] = str(decision_type)
        finished["stage_message"] = str(stage_message)

    proc._finish_success = _finish

    proc.onAnalyze()

    assert finished["area"] == 2975
    assert finished["delay"] == 3100
    assert finished["decision_type"] == "emergence_best_candidate_selected"
    assert "best measured emergence candidate" in finished["stage_message"].lower()
    assert proc.continueSearch.calls == []


def test_emergence_bracket_midpoint_equal_current_uses_best_candidate():
    proc = DropletEmergenceCalibrationProcess.__new__(DropletEmergenceCalibrationProcess)
    proc.stageChanged = Recorder()
    proc.presentImageSignal = Recorder()
    proc.continueSearch = Recorder()
    proc.replicateContinue = Recorder()
    proc.background_image = np.zeros((24, 24, 3), dtype=np.uint8)
    proc.droplet_image = np.zeros((24, 24, 3), dtype=np.uint8)
    proc.nozzle_center_px = (12, 6)
    proc._eval_count = 4
    proc._phase = "fine_adjust"
    proc._prev_area = None
    proc._rep_areas = []
    proc._replicate_details = []
    proc._last_agg_details = {}
    proc._trend_noise_events = 0
    proc.measurements = []
    proc.candidate_delay = 3200
    proc.phase_name = "droplet_emergence"
    proc.MIN_AREA = 3000
    proc.MAX_AREA = 8000
    proc.FINE_STEP = 100
    proc.MONO_TOL_FRAC = 0.10
    proc.MAX_EVALS = 50
    proc._above_band_candidate = {"delay": 3400, "area": 8400, "agg": {"replicate_cv": 0.03}}
    proc._below_band_candidate = {"delay": 3000, "area": 2950, "agg": {"replicate_cv": 0.02}}
    proc._best_candidate = {"delay": 3000, "area": 2950, "agg": {"replicate_cv": 0.02}}
    proc._recent_delay_history = [3400, 3000, 3200]
    proc._last_delay = 3000

    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            calc_emergence_area=lambda *args, **kwargs: (
                8450,
                (13, 11),
                np.zeros((24, 24, 3), dtype=np.uint8),
                {"contour_class": "attached"},
            )
        )
    )
    proc._required_replicates_for_phase = lambda: 1
    proc._can_accept_replicates_early = lambda: True
    proc._aggregate_replicates = lambda: (
        8450,
        {
            "contour_class": "attached",
            "center": (13, 11),
            "replicate_count": 1,
            "replicate_cv": 0.05,
            "replicate_range": 0.0,
        },
    )
    proc._record_analysis = lambda payload: None
    proc._record_decision = lambda *args, **kwargs: None
    proc._set_next_delay = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected next delay"))
    proc._fail = lambda msg: (_ for _ in ()).throw(AssertionError(f"unexpected fail: {msg}"))

    finished = {"area": None, "delay": None, "decision_type": None}

    def _finish(area, agg, *, decision_type="emergence_target_reached", stage_message="Target area window reached"):
        finished["area"] = int(area)
        finished["delay"] = int(proc.candidate_delay)
        finished["decision_type"] = str(decision_type)

    proc._finish_success = _finish

    proc.onAnalyze()

    assert finished["area"] == 2950
    assert finished["delay"] == 3000
    assert finished["decision_type"] == "emergence_best_candidate_selected"
    assert proc.continueSearch.calls == []
