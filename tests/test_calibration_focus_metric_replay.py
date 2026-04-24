import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from tests.calibration_test_utils import ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import NozzleFocusCalibrationProcess


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = (
    REPO_ROOT
    / "FreeRTOS-interface"
    / "Experiments"
    / "Ribo_rep1-20260423_204338"
)

RUN_SPECS = {
    "run_20260423_204534_8502f998": {
        "background": (
            EXPERIMENT_ROOT
            / "calibration_recordings"
            / "NozzlePositionCalibrationProcess"
            / "run_20260423_204532_57c91a44"
            / "captures"
            / "cap_000007_background.jpg"
        ),
        "sharp_eval": 5,
        "soft_eval": 7,
    },
    "run_20260423_204600_ffebacf9": {
        "background": (
            EXPERIMENT_ROOT
            / "calibration_recordings"
            / "NozzlePositionCalibrationProcess"
            / "run_20260423_204558_1b965cd9"
            / "captures"
            / "cap_000007_background.jpg"
        ),
        "sharp_eval": 5,
        "soft_eval": 7,
    },
}


def _new_focus_proc():
    proc = NozzleFocusCalibrationProcess.__new__(NozzleFocusCalibrationProcess)
    proc._last_bbox = None
    proc._last_mask = None
    proc._last_contour_mask = None
    proc._last_ring_mask = None
    return proc


def _load_analysis_rows(run_dir: Path) -> list[dict]:
    rows = []
    for line in (run_dir / "analysis.jsonl").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("kind") == "calibration_data_updated":
            continue
        if row.get("process_name") != "NozzleFocusCalibrationProcess":
            continue
        rows.append(row)
    return rows


def _compute_bg_g2(bg_bgr: np.ndarray) -> np.ndarray:
    bg_gray = cv2.cvtColor(bg_bgr, cv2.COLOR_BGR2GRAY)
    gx = cv2.Sobel(bg_gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(bg_gray, cv2.CV_64F, 0, 1, ksize=3)
    return gx * gx + gy * gy


def _score_run(run_id: str) -> list[dict]:
    run_dir = EXPERIMENT_ROOT / "calibration_recordings" / "NozzleFocusCalibrationProcess" / run_id
    spec = RUN_SPECS[run_id]
    if not run_dir.exists():
        pytest.skip(f"Archived nozzle-focus replay run is not available: {run_id}")
    if not spec["background"].exists():
        pytest.skip(f"Archived nozzle-position background is not available for {run_id}")

    proc = _new_focus_proc()
    bg = cv2.imread(str(spec["background"]), cv2.IMREAD_COLOR)
    assert bg is not None
    bg_g2 = _compute_bg_g2(bg)

    analysis_rows = _load_analysis_rows(run_dir)
    capture_paths = sorted((run_dir / "captures").glob("cap_*_droplet.jpg"))
    assert len(analysis_rows) == len(capture_paths) >= 2

    rescored = []
    for analysis_row, capture_path in zip(analysis_rows, capture_paths):
        frame = cv2.imread(str(capture_path), cv2.IMREAD_COLOR)
        assert frame is not None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        masks = proc._build_focus_masks(bg, frame)
        focus_stats, bg_stats = proc._compute_focus_measurements(gray, masks, bg_g2=bg_g2)
        rescored.append(
            {
                "eval_count": int(analysis_row["eval_count"]),
                "mode": str(analysis_row["mode"]),
                "Y": int(analysis_row["position"]["Y"]),
                "capture_path": capture_path,
                "focus_stats": focus_stats,
                "background_stats": bg_stats,
            }
        )
    return rescored


@pytest.mark.parametrize("run_id", sorted(RUN_SPECS))
def test_replay_ring_metric_prefers_sharper_repeat_and_keeps_best_y(run_id: str):
    rescored = _score_run(run_id)
    spec = RUN_SPECS[run_id]

    for row in rescored:
        focus_stats = row["focus_stats"]
        assert focus_stats["valid"] is True
        assert int(focus_stats["ring_pixels"]) > 0
        assert int(focus_stats["contour_pixels"]) > 0

    by_eval = {row["eval_count"]: row for row in rescored}
    sharp_row = by_eval[spec["sharp_eval"]]
    soft_row = by_eval[spec["soft_eval"]]

    assert sharp_row["Y"] == soft_row["Y"] == 39187
    assert sharp_row["focus_stats"]["ring_cv"] > soft_row["focus_stats"]["ring_cv"]
    assert sharp_row["focus_stats"]["ring_cv"] >= NozzleFocusCalibrationProcess.MIN_BEST_RING_CV
    assert soft_row["focus_stats"]["ring_cv"] < NozzleFocusCalibrationProcess.MIN_BEST_RING_CV
    assert (
        sharp_row["focus_stats"]["legacy_p90_ratio_to_background"]
        < soft_row["focus_stats"]["legacy_p90_ratio_to_background"]
    )

    selector = _new_focus_proc()
    selector.best_focus = None
    selector.best_pos = None
    selector.best_focus_stats = None
    selector._best_focus_mode = None
    for row in rescored:
        selector.mode = row["mode"]
        score = float(row["focus_stats"]["ring_cv"] or 0.0)
        if selector._should_replace_best_focus(score):
            selector.best_focus = score
            selector.best_pos = {"Y": int(row["Y"])}
            selector.best_focus_stats = dict(row["focus_stats"])
            selector._best_focus_mode = row["mode"]

    assert selector.best_pos is not None
    assert selector.best_pos["Y"] == 39187
