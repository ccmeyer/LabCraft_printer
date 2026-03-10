import cv2
import numpy as np

from tests.calibration_test_utils import ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import DropletCameraModel, PressureCalibrationProcess  # noqa: E402


def _build_detector():
    detector = DropletCameraModel.__new__(DropletCameraModel)
    detector._k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    detector.stream_aspect_hard = 2.0
    detector.stream_aspect_soft = 1.6
    detector.stream_circularity_max = 0.55
    detector.stream_min_area_px = 1200
    return detector


def test_identify_droplets_treats_near_nozzle_residue_as_non_contact():
    detector = _build_detector()
    background = np.zeros((240, 240, 3), dtype=np.uint8)
    image = background.copy()

    cv2.rectangle(image, (92, 108), (108, 122), (255, 255, 255), -1)
    cv2.circle(image, (100, 160), 14, (255, 255, 255), -1)

    droplets, nozzle_area, _overlay, details = detector.identify_droplets(
        image,
        background,
        (100, 100),
        min_area=120,
        return_details=True,
    )

    assert droplets is not None
    assert len(droplets) == 1
    assert droplets[0][1] >= 130
    assert nozzle_area is None
    assert details["nozzle_contact_detected"] is False
    assert details["near_nozzle_residue_detected"] is True
    assert details["near_nozzle_residue_components"] >= 1


def test_identify_droplets_marks_true_nozzle_contact_as_attached():
    detector = _build_detector()
    background = np.zeros((240, 240, 3), dtype=np.uint8)
    image = background.copy()

    cv2.rectangle(image, (95, 98), (105, 136), (255, 255, 255), -1)

    droplets, nozzle_area, _overlay, details = detector.identify_droplets(
        image,
        background,
        (100, 100),
        min_area=120,
        return_details=True,
    )

    assert droplets is None
    assert nozzle_area is not None
    assert int(nozzle_area) > 0
    assert details["nozzle_contact_detected"] is True
    assert details["attached_components"] >= 1
    assert details["near_nozzle_residue_detected"] is False


def test_pressure_calibration_accepts_single_droplet_without_attached_area_signal():
    proc = PressureCalibrationProcess.__new__(PressureCalibrationProcess)
    proc.hysteresis_frac = 0.10

    outcome = proc.evaluate_condition(1, None, 8000)

    assert outcome == "ACCEPTABLE"
