from types import SimpleNamespace

import numpy as np

from tests.calibration_test_utils import Recorder, contour_from_rect, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import DropletSearchCalibrationProcess


def test_droplet_search_on_analyze_saved_path_records_center_without_runtime_error():
    proc = DropletSearchCalibrationProcess.__new__(DropletSearchCalibrationProcess)
    proc._is_dead = lambda: False
    proc.stageChanged = Recorder()
    proc.presentImageSignal = Recorder()
    proc.continueSearch = Recorder()
    proc.dropletFound = Recorder()
    proc.readyToCharacterize = Recorder()
    proc.measurements = []
    proc._lost_count = 3
    proc.current_delay_us = 1234
    proc.droplet_image = np.zeros((120, 160, 3), dtype=np.uint8)
    proc.background_image = np.zeros((120, 160, 3), dtype=np.uint8)
    proc.manual_start = False
    proc._discard_post_move_pending = False
    proc._discard_post_move_reason = ""
    proc._discard_post_move_target_xyz = None
    proc._search_last_center = None
    proc._search_last_delay_us = None
    proc._search_stable_hits = 0
    proc._search_confirm_same_settings_pending = False
    proc.search_center_jump_max_px = 280.0
    proc.search_cross_delay_jump_scale = 1.8
    proc.search_min_signal_p95 = 10.0
    proc.search_stable_hits_required = 2
    proc._centered = False

    analysis_rows = []
    proc._save_capture = lambda *_args, **_kwargs: {"index": 7}
    proc._save_overlay = lambda *_args, **_kwargs: None
    proc._append_analysis = lambda row: analysis_rows.append(row)
    proc.emitContinueSearch = lambda: None
    proc.emitDropletFound = lambda: analysis_rows.append({"kind": "found"})
    proc.emitReadyToCharacterize = lambda: analysis_rows.append({"kind": "ready"})
    proc._handle_no_droplet_retry = lambda *_args, **_kwargs: analysis_rows.append({"kind": "retry"})

    contour = contour_from_rect(50, 40, 40, 40)
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplet_contour=lambda image, bg, return_details=False: (
                (contour, image.copy(), {"center": (70, 60), "p95": 15.0, "reason": "ok"})
                if return_details
                else (contour, image.copy())
            )
        )
    )

    proc.onAnalyze()

    search_rows = [r for r in analysis_rows if r.get("kind") == "search_result"]
    assert len(search_rows) == 1
    assert search_rows[0]["center_px"] == (70, 60)
    assert proc.measurements and proc.measurements[0]["center"] == (70, 60)


def test_droplet_search_on_analyze_centered_reacquire_emits_ready_to_characterize():
    proc = DropletSearchCalibrationProcess.__new__(DropletSearchCalibrationProcess)
    proc._is_dead = lambda: False
    proc.stageChanged = Recorder()
    proc.presentImageSignal = Recorder()
    proc.continueSearch = Recorder()
    proc.dropletFound = Recorder()
    proc.readyToCharacterize = Recorder()
    proc.measurements = []
    proc._lost_count = 0
    proc.current_delay_us = 1234
    proc.droplet_image = np.zeros((120, 160, 3), dtype=np.uint8)
    proc.background_image = np.zeros((120, 160, 3), dtype=np.uint8)
    proc.manual_start = True
    proc._discard_post_move_pending = False
    proc._discard_post_move_reason = ""
    proc._discard_post_move_target_xyz = None
    proc._search_last_center = (70, 60)
    proc._search_last_delay_us = 1234
    proc._search_stable_hits = 1
    proc._search_confirm_same_settings_pending = False
    proc.search_center_jump_max_px = 280.0
    proc.search_cross_delay_jump_scale = 1.8
    proc.search_min_signal_p95 = 10.0
    proc.search_stable_hits_required = 2
    proc._centered = True
    proc._manual_search_miss_count = 0

    analysis_rows = []
    proc._save_capture = lambda *_args, **_kwargs: {"index": 8}
    proc._save_overlay = lambda *_args, **_kwargs: None
    proc._append_analysis = lambda row: analysis_rows.append(row)
    proc.emitContinueSearch = lambda: analysis_rows.append({"kind": "retry"})
    proc.emitDropletFound = lambda: analysis_rows.append({"kind": "found"})
    proc.emitReadyToCharacterize = lambda: analysis_rows.append({"kind": "ready"})
    proc._handle_no_droplet_retry = lambda *_args, **_kwargs: analysis_rows.append({"kind": "no_droplet"})

    contour = contour_from_rect(50, 40, 40, 40)
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            identify_droplet_contour=lambda image, bg, return_details=False: (
                (contour, image.copy(), {"center": (70, 60), "p95": 18.0, "reason": "ok"})
                if return_details
                else (contour, image.copy())
            )
        )
    )

    proc.onAnalyze()

    assert any(row.get("kind") == "ready" for row in analysis_rows)
    assert not any(row.get("kind") == "found" for row in analysis_rows)
    assert proc.measurements and proc.measurements[0]["center"] == (70, 60)
