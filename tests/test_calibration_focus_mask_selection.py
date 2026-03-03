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
