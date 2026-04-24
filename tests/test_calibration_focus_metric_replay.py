import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from tests.calibration_test_utils import ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import NozzleFocusCalibrationProcess


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOTS = {
    "ribo": (
        REPO_ROOT
        / "FreeRTOS-interface"
        / "Experiments"
        / "Ribo_rep1-20260423_204338"
    ),
    "untitled": (
        REPO_ROOT
        / "FreeRTOS-interface"
        / "Experiments"
        / "Untitled-20260424_130613"
    ),
}

RUN_SPECS = {
    "run_20260423_204534_8502f998": {
        "experiment_key": "ribo",
        "background": (
            EXPERIMENT_ROOTS["ribo"]
            / "calibration_recordings"
            / "NozzlePositionCalibrationProcess"
            / "run_20260423_204532_57c91a44"
            / "captures"
            / "cap_000007_background.jpg"
        ),
        "sharp_eval": 5,
        "soft_eval": 7,
        "expected_peak_actual_y": {39166},
    },
    "run_20260423_204600_ffebacf9": {
        "experiment_key": "ribo",
        "background": (
            EXPERIMENT_ROOTS["ribo"]
            / "calibration_recordings"
            / "NozzlePositionCalibrationProcess"
            / "run_20260423_204558_1b965cd9"
            / "captures"
            / "cap_000007_background.jpg"
        ),
        "sharp_eval": 5,
        "soft_eval": 7,
        "expected_peak_actual_y": {39166},
    },
    "run_20260424_131431_32078ae9": {
        "experiment_key": "untitled",
        "background": (
            EXPERIMENT_ROOTS["untitled"]
            / "calibration_recordings"
            / "NozzlePositionCalibrationProcess"
            / "run_20260424_131427_b599a03f"
            / "captures"
            / "cap_000007_background.jpg"
        ),
        "expected_peak_actual_y": {39145},
        "consistent_actual_y": 39145,
        "mislabeled_eval": 3,
        "mislabeled_reported_y": 39145,
        "mislabeled_actual_y": 39161,
    },
    "run_20260424_131437_70432e5c": {
        "experiment_key": "untitled",
        "background": (
            EXPERIMENT_ROOTS["untitled"]
            / "calibration_recordings"
            / "NozzlePositionCalibrationProcess"
            / "run_20260424_131427_b599a03f"
            / "captures"
            / "cap_000007_background.jpg"
        ),
        "expected_peak_actual_y": {39144, 39145},
        "consistent_actual_y": 39144,
        "mislabeled_eval": 7,
        "mislabeled_reported_y": 39144,
        "mislabeled_actual_y": 39149,
    },
}

RIBO_RUN_IDS = [
    run_id for run_id, spec in RUN_SPECS.items() if spec["experiment_key"] == "ribo"
]
UNTITLED_RUN_IDS = [
    run_id for run_id, spec in RUN_SPECS.items() if spec["experiment_key"] == "untitled"
]


def _new_focus_proc():
    proc = NozzleFocusCalibrationProcess.__new__(NozzleFocusCalibrationProcess)
    proc._last_bbox = None
    proc._last_mask = None
    proc._last_contour_mask = None
    proc._last_ring_mask = None
    proc._tracked_pos = None
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


def _load_move_requests(run_dir: Path) -> list[dict]:
    requests = []
    for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        event = json.loads(line)
        if event.get("event_type") != "move_requested":
            continue
        move = list((event.get("payload") or {}).get("move_vector") or [])
        if len(move) != 3:
            continue
        requests.append({"ts_utc": str(event.get("ts_utc", "")), "dY": int(move[1])})
    return requests


def _reconstruct_actual_y(analysis_rows: list[dict], move_requests: list[dict]) -> list[int]:
    if not analysis_rows:
        return []

    current_y = int(analysis_rows[0]["position"]["Y"])
    move_idx = 0
    actual_y = []

    for row in analysis_rows:
        row_ts = str(row.get("ts_utc", ""))
        while move_idx < len(move_requests) and str(move_requests[move_idx]["ts_utc"]) <= row_ts:
            current_y += int(move_requests[move_idx]["dY"])
            move_idx += 1
        actual_y.append(current_y)

    return actual_y


def _compute_bg_g2(bg_bgr: np.ndarray) -> np.ndarray:
    bg_gray = cv2.cvtColor(bg_bgr, cv2.COLOR_BGR2GRAY)
    gx = cv2.Sobel(bg_gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(bg_gray, cv2.CV_64F, 0, 1, ksize=3)
    return gx * gx + gy * gy


def _score_run(run_id: str) -> list[dict]:
    spec = RUN_SPECS[run_id]
    experiment_root = EXPERIMENT_ROOTS[spec["experiment_key"]]
    run_dir = experiment_root / "calibration_recordings" / "NozzleFocusCalibrationProcess" / run_id
    if not run_dir.exists():
        pytest.skip(f"Archived nozzle-focus replay run is not available: {run_id}")
    if not spec["background"].exists():
        pytest.skip(f"Archived nozzle-position background is not available for {run_id}")

    proc = _new_focus_proc()
    bg = cv2.imread(str(spec["background"]), cv2.IMREAD_COLOR)
    assert bg is not None
    bg_g2 = _compute_bg_g2(bg)

    analysis_rows = _load_analysis_rows(run_dir)
    move_requests = _load_move_requests(run_dir)
    actual_y = _reconstruct_actual_y(analysis_rows, move_requests)
    capture_paths = sorted((run_dir / "captures").glob("cap_*_droplet.jpg"))
    assert len(analysis_rows) == len(capture_paths) >= 2
    assert len(actual_y) == len(analysis_rows)

    rescored = []
    for analysis_row, capture_path, reconstructed_y in zip(analysis_rows, capture_paths, actual_y):
        frame = cv2.imread(str(capture_path), cv2.IMREAD_COLOR)
        assert frame is not None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        masks = proc._build_focus_masks(bg, frame)
        focus_stats, bg_stats = proc._compute_focus_measurements(gray, masks, bg_g2=bg_g2)
        reported_position = dict(analysis_row.get("reported_position") or analysis_row["position"])
        rescored.append(
            {
                "eval_count": int(analysis_row["eval_count"]),
                "mode": str(analysis_row["mode"]),
                "reported_Y": int(analysis_row["position"]["Y"]),
                "actual_Y": int(reconstructed_y),
                "reported_position": {
                    "X": int(reported_position["X"]),
                    "Y": int(reported_position["Y"]),
                    "Z": int(reported_position["Z"]),
                },
                "position_source": str(analysis_row.get("position_source") or "reported"),
                "capture_path": capture_path,
                "focus_stats": focus_stats,
                "background_stats": bg_stats,
            }
        )
    return rescored


@pytest.mark.parametrize("run_id", RIBO_RUN_IDS)
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

    assert sharp_row["reported_Y"] == soft_row["reported_Y"] == 39187
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
            selector.best_pos = {"Y": int(row["actual_Y"])}
            selector.best_focus_stats = dict(row["focus_stats"])
            selector._best_focus_mode = row["mode"]

    assert selector.best_pos is not None
    assert selector.best_pos["Y"] in set(spec["expected_peak_actual_y"])


@pytest.mark.parametrize("run_id", UNTITLED_RUN_IDS)
def test_replay_untitled_runs_require_corrected_y_labels_and_clear_new_threshold(run_id: str):
    rescored = _score_run(run_id)
    spec = RUN_SPECS[run_id]

    for row in rescored:
        focus_stats = row["focus_stats"]
        assert focus_stats["valid"] is True
        assert int(focus_stats["ring_pixels"]) > 0
        assert int(focus_stats["contour_pixels"]) > 0

    assert any(row["actual_Y"] != row["reported_Y"] for row in rescored)

    by_eval = {row["eval_count"]: row for row in rescored}
    mislabeled = by_eval[spec["mislabeled_eval"]]
    assert mislabeled["reported_Y"] == spec["mislabeled_reported_y"]
    assert mislabeled["actual_Y"] == spec["mislabeled_actual_y"]

    consistent_scores = [
        float(row["focus_stats"]["ring_cv"] or 0.0)
        for row in rescored
        if row["actual_Y"] == spec["consistent_actual_y"]
    ]
    assert len(consistent_scores) >= 2
    assert max(consistent_scores) - min(consistent_scores) < 0.02

    best_row = max(rescored, key=lambda row: float(row["focus_stats"]["ring_cv"] or 0.0))
    assert best_row["actual_Y"] in set(spec["expected_peak_actual_y"])
    assert float(best_row["focus_stats"]["ring_cv"] or 0.0) >= NozzleFocusCalibrationProcess.MIN_BEST_RING_CV
