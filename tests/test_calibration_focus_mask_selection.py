import cv2
import numpy as np

from tests.calibration_test_utils import ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import NozzleFocusCalibrationProcess


def test_build_focus_mask_prefers_lowest_contour_deterministically():
    proc = NozzleFocusCalibrationProcess.__new__(NozzleFocusCalibrationProcess)
    proc._last_bbox = None
    proc._last_mask = None
    proc._last_contour_mask = None
    proc._last_ring_mask = None

    bg = np.zeros((420, 420, 3), dtype=np.uint8)
    dr = bg.copy()

    # top contour (would be selected by the old keep[0] overwrite bug)
    cv2.rectangle(dr, (60, 30), (150, 90), (255, 255, 255), -1)
    # lower contour should be selected by the ranking rule
    cv2.rectangle(dr, (200, 280), (310, 350), (255, 255, 255), -1)

    mask = proc._build_focus_mask(bg, dr)
    assert mask is not None
    assert proc._last_bbox is not None
    assert proc._last_contour_mask is not None
    assert proc._last_ring_mask is not None

    x0, y0, w, h = proc._last_bbox
    assert y0 > 200
    assert mask[320, 250] == 255
    assert mask[60, 100] == 0
    assert proc._last_contour_mask[320, 250] == 255
    assert proc._last_contour_mask[60, 100] == 0
    assert proc._last_ring_mask[320, 200] == 255
    assert proc._last_ring_mask[320, 250] == 0
    assert proc._last_ring_mask[60, 100] == 0
    assert int(np.count_nonzero(proc._last_ring_mask)) > 0


def test_ring_cv_drops_with_blur_for_same_silhouette():
    proc = NozzleFocusCalibrationProcess.__new__(NozzleFocusCalibrationProcess)

    contour_mask = np.zeros((180, 180), dtype=np.uint8)
    cv2.rectangle(contour_mask, (60, 50), (120, 140), 255, -1)
    ring_mask = proc._build_contour_ring_mask(contour_mask)
    assert ring_mask is not None

    focus_masks = {
        "roi_mask": contour_mask.copy(),
        "contour_mask": contour_mask,
        "ring_mask": ring_mask,
    }

    sharp = np.zeros((180, 180), dtype=np.uint8)
    cv2.rectangle(sharp, (60, 50), (120, 140), 255, -1)
    medium = cv2.GaussianBlur(sharp, (0, 0), sigmaX=2.0, sigmaY=2.0)
    soft = cv2.GaussianBlur(sharp, (0, 0), sigmaX=4.0, sigmaY=4.0)

    sharp_stats, _ = proc._compute_focus_measurements(sharp, focus_masks)
    medium_stats, _ = proc._compute_focus_measurements(medium, focus_masks)
    soft_stats, _ = proc._compute_focus_measurements(soft, focus_masks)

    assert sharp_stats["valid"] is True
    assert medium_stats["valid"] is True
    assert soft_stats["valid"] is True
    assert sharp_stats["ring_pixels"] == medium_stats["ring_pixels"] == soft_stats["ring_pixels"]
    assert sharp_stats["contour_pixels"] == medium_stats["contour_pixels"] == soft_stats["contour_pixels"]
    assert sharp_stats["ring_cv"] > medium_stats["ring_cv"] > soft_stats["ring_cv"]
