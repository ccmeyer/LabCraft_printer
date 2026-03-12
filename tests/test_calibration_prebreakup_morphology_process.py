from types import SimpleNamespace

import cv2
import numpy as np

from tests.calibration_test_utils import ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import (  # noqa: E402
    CalibrationManager,
    DropletCameraModel,
    PreBreakupMorphologyCalibrationProcess,
)


def _ready_cm():
    return SimpleNamespace(
        get_nozzle_center=lambda: {"X": 1, "Y": 2, "Z": 3},
        get_pressure_scan_nozzle_center_image_position=lambda: (160, 80),
        get_emergence_time=lambda: 3200,
        model=SimpleNamespace(
            droplet_camera_model=SimpleNamespace(get_image_size=lambda: (320, 320)),
        ),
    )


def _camera_stub():
    cam = DropletCameraModel.__new__(DropletCameraModel)
    cam._k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    return cam


def _proc_stub():
    proc = PreBreakupMorphologyCalibrationProcess.__new__(PreBreakupMorphologyCalibrationProcess)
    proc.min_signal_p95 = 10.0
    proc.min_protrusion_length_px = 14
    proc.min_candidate_protrusion_px = 28
    proc.min_candidate_bulb_width_px = 14
    proc.neck_ratio_risk_threshold = 0.42
    proc.nozzle_side_area_ratio_risk_threshold = 0.48
    proc.long_ligament_px = 36
    proc.max_secondary_lobes_for_clean = 0
    return proc


def test_prebreakup_missing_requirements_reports_dependencies():
    cm = _ready_cm()
    cm.get_nozzle_center = lambda: None
    cm.get_pressure_scan_nozzle_center_image_position = lambda: None
    cm.get_emergence_time = lambda: None
    cm.model.droplet_camera_model.get_image_size = lambda: (_ for _ in ()).throw(RuntimeError("no camera"))

    missing = PreBreakupMorphologyCalibrationProcess.missing_requirements(cm)

    joined = " | ".join(missing).lower()
    assert "nozzle center" in joined
    assert "image coords" in joined
    assert "emergence" in joined
    assert "droplet camera" in joined


def test_start_prebreakup_uses_try_start_process_and_kwargs():
    mgr = CalibrationManager.__new__(CalibrationManager)
    called = {"proc_cls": None, "kwargs": None}

    def _stub(proc_cls, *args, **kwargs):
        called["proc_cls"] = proc_cls
        called["kwargs"] = dict(kwargs)
        return True

    mgr._try_start_process = _stub
    CalibrationManager.start_prebreakup_morphology_calibration(
        mgr,
        start_pressure=0.82,
        pressure_step_psi=0.025,
        prebreakup_lead_us=700,
        replicates_per_pressure=4,
    )

    assert called["proc_cls"] is PreBreakupMorphologyCalibrationProcess
    assert called["kwargs"]["start_pressure"] == 0.82
    assert called["kwargs"]["pressure_step_psi"] == 0.025
    assert called["kwargs"]["prebreakup_lead_us"] == 700
    assert called["kwargs"]["replicates_per_pressure"] == 4


def test_analyze_prebreakup_morphology_extracts_attached_bulb_metrics():
    cam = _camera_stub()
    bg = np.full((320, 320, 3), 220, dtype=np.uint8)
    img = bg.copy()

    cv2.rectangle(img, (154, 80), (166, 126), (20, 20, 20), -1)
    cv2.circle(img, (160, 148), 26, (20, 20, 20), -1)

    metrics, _overlay, details = cam.analyze_prebreakup_morphology(
        bg,
        img,
        nozzle_center=(160, 80),
        return_details=True,
    )

    assert details["status"] == "ok"
    assert details["contour_class"] == "attached"
    assert metrics["protrusion_length_px"] >= 50
    assert metrics["max_width_px"] > metrics["neck_width_px"]
    assert metrics["bulb_present"] is True


def test_analyze_prebreakup_morphology_marks_detached_contour():
    cam = _camera_stub()
    bg = np.full((320, 320, 3), 220, dtype=np.uint8)
    img = bg.copy()

    cv2.circle(img, (160, 150), 24, (20, 20, 20), -1)

    metrics, _overlay, details = cam.analyze_prebreakup_morphology(
        bg,
        img,
        nozzle_center=(160, 80),
        return_details=True,
    )

    assert details["status"] == "ok"
    assert details["contour_class"] == "detached"
    assert metrics["protrusion_length_px"] > 0


def test_prebreakup_classify_morphology_distinguishes_candidate_and_risk():
    proc = _proc_stub()

    candidate = proc._classify_morphology(
        {
            "status": "ok",
            "contour_class": "attached",
            "protrusion_length_px": 54,
            "max_width_px": 32,
            "neck_to_bulb_ratio": 0.55,
            "p95": 24.0,
            "nozzle_side_area_ratio": 0.24,
            "distance_nozzle_to_neck_px": 18,
            "secondary_lobe_count": 0,
            "bulb_present": True,
        }
    )
    risk = proc._classify_morphology(
        {
            "status": "ok",
            "contour_class": "attached",
            "protrusion_length_px": 62,
            "max_width_px": 36,
            "neck_to_bulb_ratio": 0.28,
            "p95": 24.0,
            "nozzle_side_area_ratio": 0.62,
            "distance_nozzle_to_neck_px": 42,
            "secondary_lobe_count": 1,
            "bulb_present": True,
        }
    )

    assert candidate == "candidate_clean"
    assert risk == "approaching_risk"


def test_prebreakup_aggregate_replicates_prefers_risk_state_and_medians():
    proc = _proc_stub()
    proc.reps = [
        {"state": "candidate_clean", "details": {"protrusion_length_px": 42, "neck_to_bulb_ratio": 0.58, "bulb_present": True}},
        {"state": "approaching_risk", "details": {"protrusion_length_px": 50, "neck_to_bulb_ratio": 0.32, "bulb_present": True}},
        {"state": "approaching_risk", "details": {"protrusion_length_px": 48, "neck_to_bulb_ratio": 0.30, "bulb_present": True}},
    ]

    verdict, summary = proc._aggregate_replicates()

    assert verdict == "approaching_risk"
    assert summary["class_counts"]["approaching_risk"] == 2
    assert summary["feature_summary"]["protrusion_length_px"] == 48
    assert round(summary["feature_summary"]["neck_to_bulb_ratio"], 2) == 0.32
    assert summary["feature_summary"]["bulb_present"] is True
