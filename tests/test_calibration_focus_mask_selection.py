import cv2
import numpy as np

from tests.calibration_test_utils import ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import NozzleFocusCalibrationProcess


def test_build_focus_mask_prefers_lowest_contour_deterministically():
    proc = NozzleFocusCalibrationProcess.__new__(NozzleFocusCalibrationProcess)
    proc._last_bbox = None
    proc._last_mask = None

    bg = np.zeros((420, 420, 3), dtype=np.uint8)
    dr = bg.copy()

    # top contour (would be selected by the old keep[0] overwrite bug)
    cv2.rectangle(dr, (60, 30), (150, 90), (255, 255, 255), -1)
    # lower contour should be selected by the ranking rule
    cv2.rectangle(dr, (200, 280), (310, 350), (255, 255, 255), -1)

    mask = proc._build_focus_mask(bg, dr)
    assert mask is not None
    assert proc._last_bbox is not None

    x0, y0, w, h = proc._last_bbox
    assert y0 > 200
    assert mask[320, 250] == 255
    assert mask[60, 100] == 0


def test_tenengrad_variance_drops_with_blur_for_same_silhouette():
    proc = NozzleFocusCalibrationProcess.__new__(NozzleFocusCalibrationProcess)

    roi_mask = np.zeros((180, 180), dtype=np.uint8)
    cv2.rectangle(roi_mask, (60, 50), (120, 140), 255, -1)

    sharp = np.zeros((180, 180), dtype=np.uint8)
    cv2.rectangle(sharp, (60, 50), (120, 140), 255, -1)
    medium = cv2.GaussianBlur(sharp, (0, 0), sigmaX=2.0, sigmaY=2.0)
    soft = cv2.GaussianBlur(sharp, (0, 0), sigmaX=4.0, sigmaY=4.0)

    sharp_stats = proc._compute_focus_stats(sharp, roi_mask)
    medium_stats = proc._compute_focus_stats(medium, roi_mask)
    soft_stats = proc._compute_focus_stats(soft, roi_mask)

    assert sharp_stats["valid"] is True
    assert medium_stats["valid"] is True
    assert soft_stats["valid"] is True
    assert sharp_stats["mask_pixels"] == medium_stats["mask_pixels"] == soft_stats["mask_pixels"]
    assert sharp_stats["var"] > medium_stats["var"] > soft_stats["var"]
