from types import SimpleNamespace

import numpy as np

from tests.calibration_test_utils import ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import CalibrationProcessRecorder
from tools.replay_calibration_run import replay_run


def _dummy_model(tmp_path):
    exp = SimpleNamespace(
        experiment_dir_path=str(tmp_path),
        calibration_file_path=str(tmp_path / "calibration.json"),
    )
    return SimpleNamespace(experiment_model=exp)


def test_replay_nozzle_position_matches_recorded_status(tmp_path):
    rec = CalibrationProcessRecorder(_dummy_model(tmp_path))
    run_dir = rec.start_run("NozzlePositionCalibrationProcess", "nozzle_position")

    bg = np.zeros((240, 320, 3), dtype=np.uint8)
    dr = bg.copy()
    # Large bright stream-like contour in top band to produce status=OK.
    dr[20:120, 130:170, :] = 255

    bg_cap = rec.save_capture_image(bg, role="background")
    dr_cap = rec.save_capture_image(
        dr,
        role="droplet",
        metadata={
            "subtract_background_capture_id": bg_cap["capture_id"],
            "subtract_background_image_relpath": bg_cap["image_relpath"],
        },
    )

    rec.append_event("decision", {"decision": "recenter_move"})
    rec.append_analysis(
        {
            "kind": "nozzle_detection",
            "status": "OK",
            "pair": {
                "background_capture_id": bg_cap["capture_id"],
                "background_image_relpath": bg_cap["image_relpath"],
                "droplet_capture_id": dr_cap["capture_id"],
                "droplet_image_relpath": dr_cap["image_relpath"],
            },
        }
    )
    rec.finalize_run("completed")

    report = replay_run(run_dir)
    assert report["supported"] is True
    assert report["summary"]["total"] == 1
    assert report["summary"]["matched"] == 1
    assert report["summary"]["mismatched"] == 0
