from types import SimpleNamespace

import cv2
import numpy as np

from tests.calibration_test_utils import Recorder, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import DropletSearchCalibrationProcess


def _make_rect_contour():
    img = np.zeros((120, 160), dtype=np.uint8)
    cv2.rectangle(img, (50, 40), (90, 80), 255, -1)
    contours, _ = cv2.findContours(img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return contours[0]


def test_droplet_search_on_analyze_saved_path_records_center_without_runtime_error():
    proc = DropletSearchCalibrationProcess.__new__(DropletSearchCalibrationProcess)
    proc._is_dead = lambda: False
    proc.stageChanged = Recorder()
    proc.presentImageSignal = Recorder()
    proc.measurements = []
    proc._lost_count = 3
    proc.current_delay_us = 1234
    proc.droplet_image = np.zeros((120, 160, 3), dtype=np.uint8)
    proc.background_image = np.zeros((120, 160, 3), dtype=np.uint8)

    analysis_rows = []
    proc._save_capture = lambda *_args, **_kwargs: {"index": 7}
    proc._save_overlay = lambda *_args, **_kwargs: None
    proc._append_analysis = lambda row: analysis_rows.append(row)
    proc.emitContinueSearch = lambda: None
    proc.emitDropletFound = lambda: analysis_rows.append({"kind": "found"})

    contour = _make_rect_contour()
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplet_contour=lambda image, bg: (contour, image.copy())
        )
    )

    proc.onAnalyze()

    search_rows = [r for r in analysis_rows if r.get("kind") == "search_result"]
    assert len(search_rows) == 1
    assert search_rows[0]["center_px"] == (70, 60)
    assert proc.measurements and proc.measurements[0]["center"] == (70, 60)
