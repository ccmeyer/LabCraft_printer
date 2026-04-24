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
    "ribo": REPO_ROOT / "FreeRTOS-interface" / "Experiments" / "Ribo_rep1-20260423_204338",
    "untitled_old": REPO_ROOT / "FreeRTOS-interface" / "Experiments" / "Untitled-20260424_130613",
    "untitled_new": REPO_ROOT / "FreeRTOS-interface" / "Experiments" / "Untitled-20260424_141733",
}

RUN_SPECS = {
    "run_20260423_204534_8502f998": {
        "experiment_key": "ribo",
        "background": EXPERIMENT_ROOTS["ribo"]
        / "calibration_recordings"
        / "NozzlePositionCalibrationProcess"
        / "run_20260423_204532_57c91a44"
        / "captures"
        / "cap_000007_background.jpg",
        "expected_peak_actual_y": {39161},
    },
    "run_20260423_204600_ffebacf9": {
        "experiment_key": "ribo",
        "background": EXPERIMENT_ROOTS["ribo"]
        / "calibration_recordings"
        / "NozzlePositionCalibrationProcess"
        / "run_20260423_204558_1b965cd9"
        / "captures"
        / "cap_000007_background.jpg",
        "expected_peak_actual_y": {39161},
    },
    "run_20260424_131431_32078ae9": {
        "experiment_key": "untitled_old",
        "background": EXPERIMENT_ROOTS["untitled_old"]
        / "calibration_recordings"
        / "NozzlePositionCalibrationProcess"
        / "run_20260424_131427_b599a03f"
        / "captures"
        / "cap_000007_background.jpg",
        "expected_peak_actual_y": {39145},
        "mislabeled_eval": 3,
        "mislabeled_reported_y": 39145,
        "mislabeled_actual_y": 39161,
    },
    "run_20260424_131437_70432e5c": {
        "experiment_key": "untitled_old",
        "background": EXPERIMENT_ROOTS["untitled_old"]
        / "calibration_recordings"
        / "NozzlePositionCalibrationProcess"
        / "run_20260424_131427_b599a03f"
        / "captures"
        / "cap_000007_background.jpg",
        "expected_peak_actual_y": {39144},
        "mislabeled_eval": 7,
        "mislabeled_reported_y": 39144,
        "mislabeled_actual_y": 39149,
    },
    "run_20260424_142013_c47414a9": {
        "experiment_key": "untitled_new",
        "background": EXPERIMENT_ROOTS["untitled_new"]
        / "calibration_recordings"
        / "NozzlePositionCalibrationProcess"
        / "run_20260424_142011_d7820c95"
        / "captures"
        / "cap_000007_background.jpg",
        "expected_peak_actual_y": {39145},
    },
    "run_20260424_142026_f5e4944e": {
        "experiment_key": "untitled_new",
        "background": EXPERIMENT_ROOTS["untitled_new"]
        / "calibration_recordings"
        / "NozzlePositionCalibrationProcess"
        / "run_20260424_142023_ee95a095"
        / "captures"
        / "cap_000007_background.jpg",
        "expected_peak_actual_y": {39145},
    },
    "run_20260424_142038_70aca440": {
        "experiment_key": "untitled_new",
        "background": EXPERIMENT_ROOTS["untitled_new"]
        / "calibration_recordings"
        / "NozzlePositionCalibrationProcess"
        / "run_20260424_142036_f43cd46b"
        / "captures"
        / "cap_000007_background.jpg",
        "expected_peak_actual_y": {39145},
    },
    "run_20260424_142217_df027cda": {
        "experiment_key": "untitled_new",
        "background": EXPERIMENT_ROOTS["untitled_new"]
        / "calibration_recordings"
        / "NozzlePositionCalibrationProcess"
        / "run_20260424_142036_f43cd46b"
        / "captures"
        / "cap_000007_background.jpg",
        "strong_signal_eval": 1,
        "weak_basin_min_y": 39216,
    },
    "run_20260424_142403_d34e6529": {
        "experiment_key": "untitled_new",
        "background": EXPERIMENT_ROOTS["untitled_new"]
        / "calibration_recordings"
        / "NozzlePositionCalibrationProcess"
        / "run_20260424_142036_f43cd46b"
        / "captures"
        / "cap_000007_background.jpg",
        "strong_signal_eval": 1,
        "weak_basin_min_y": 39211,
    },
    "run_20260424_142454_e4946885": {
        "experiment_key": "untitled_new",
        "background": EXPERIMENT_ROOTS["untitled_new"]
        / "calibration_recordings"
        / "NozzlePositionCalibrationProcess"
        / "run_20260424_142036_f43cd46b"
        / "captures"
        / "cap_000007_background.jpg",
        "positive_eval": 2,
        "negative_branch_eval": 4,
    },
    "run_20260424_142512_d2506065": {
        "experiment_key": "untitled_new",
        "background": EXPERIMENT_ROOTS["untitled_new"]
        / "calibration_recordings"
        / "NozzlePositionCalibrationProcess"
        / "run_20260424_142036_f43cd46b"
        / "captures"
        / "cap_000007_background.jpg",
        "positive_eval": 2,
        "negative_branch_eval": 4,
    },
    "run_20260424_142520_8b4457f7": {
        "experiment_key": "untitled_new",
        "background": EXPERIMENT_ROOTS["untitled_new"]
        / "calibration_recordings"
        / "NozzlePositionCalibrationProcess"
        / "run_20260424_142036_f43cd46b"
        / "captures"
        / "cap_000007_background.jpg",
        "positive_eval": 2,
        "negative_branch_eval": 4,
    },
}

LEGACY_PEAK_RUN_IDS = [
    "run_20260423_204534_8502f998",
    "run_20260423_204600_ffebacf9",
    "run_20260424_131431_32078ae9",
    "run_20260424_131437_70432e5c",
    "run_20260424_142013_c47414a9",
    "run_20260424_142026_f5e4944e",
    "run_20260424_142038_70aca440",
]
TRACKED_Y_RUN_IDS = [
    "run_20260424_131431_32078ae9",
    "run_20260424_131437_70432e5c",
]
WRONG_DIRECTION_RUN_IDS = [
    "run_20260424_142454_e4946885",
    "run_20260424_142512_d2506065",
    "run_20260424_142520_8b4457f7",
]
TINY_SIGNAL_RUN_IDS = [
    "run_20260424_142217_df027cda",
    "run_20260424_142403_d34e6529",
]


def _new_focus_proc():
    proc = NozzleFocusCalibrationProcess.__new__(NozzleFocusCalibrationProcess)
    proc._last_bbox = None
    proc._last_mask = None
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
        if "position" not in row:
            continue
        rows.append(row)
    return rows


def _load_move_completions(run_dir: Path) -> list[dict]:
    moves = []
    for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        event = json.loads(line)
        if event.get("event_type") != "move_completed":
            continue
        move = list((event.get("payload") or {}).get("move_vector") or [])
        if len(move) != 3:
            continue
        moves.append({"ts_utc": str(event.get("ts_utc", "")), "dY": int(move[1])})
    return moves


def _reconstruct_actual_y(analysis_rows: list[dict], move_completions: list[dict]) -> list[int]:
    if not analysis_rows:
        return []

    current_y = int(analysis_rows[0]["position"]["Y"])
    move_idx = 0
    actual_y = []

    for row in analysis_rows:
        row_ts = str(row.get("ts_utc", ""))
        while move_idx < len(move_completions) and str(move_completions[move_idx]["ts_utc"]) <= row_ts:
            current_y += int(move_completions[move_idx]["dY"])
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
    move_completions = _load_move_completions(run_dir)
    actual_y = _reconstruct_actual_y(analysis_rows, move_completions)
    capture_paths = sorted((run_dir / "captures").glob("cap_*_droplet.jpg"))
    assert len(analysis_rows) == len(capture_paths) >= 2
    assert len(actual_y) == len(analysis_rows)

    rescored = []
    for analysis_row, capture_path, reconstructed_y in zip(analysis_rows, capture_paths, actual_y):
        frame = cv2.imread(str(capture_path), cv2.IMREAD_COLOR)
        assert frame is not None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mask = proc._build_focus_mask(bg, frame)
        focus_stats = proc._compute_focus_stats(gray, mask)
        bg_stats = proc._compute_focus_stats(None, mask, g2_precomputed=bg_g2)
        p90_ratio = None
        if focus_stats.get("valid", False) and bg_stats.get("valid", False):
            p90_ratio = float((focus_stats["p90"] + 1.0) / (bg_stats["p90"] + 1.0))
        rescored.append(
            {
                "eval_count": int(analysis_row["eval_count"]),
                "mode": str(analysis_row["mode"]),
                "reported_Y": int(analysis_row["position"]["Y"]),
                "actual_Y": int(reconstructed_y),
                "reported_position": dict(analysis_row.get("reported_position") or analysis_row["position"]),
                "position_source": str(analysis_row.get("position_source") or "reported"),
                "capture_path": capture_path,
                "focus_stats": {
                    "valid": bool(focus_stats.get("valid", False)),
                    "mask_pixels": int(focus_stats.get("mask_pixels", 0)),
                    "var": float(focus_stats.get("var", 0.0)) if focus_stats.get("valid", False) else 0.0,
                    "mean": float(focus_stats.get("mean", 0.0)) if focus_stats.get("valid", False) else 0.0,
                    "p90": float(focus_stats.get("p90", 0.0)) if focus_stats.get("valid", False) else 0.0,
                    "p90_ratio_to_background": p90_ratio,
                },
                "background_stats": bg_stats,
            }
        )
    return rescored


@pytest.mark.parametrize("run_id", LEGACY_PEAK_RUN_IDS)
def test_replay_legacy_metric_keeps_best_actual_y_in_known_focus_basin(run_id: str):
    rescored = _score_run(run_id)
    spec = RUN_SPECS[run_id]

    for row in rescored:
        assert row["focus_stats"]["valid"] is True
        assert int(row["focus_stats"]["mask_pixels"]) > 0

    best_row = max(rescored, key=lambda row: float(row["focus_stats"]["var"] or 0.0))
    assert best_row["actual_Y"] in set(spec["expected_peak_actual_y"])
    assert (
        float(best_row["focus_stats"]["p90_ratio_to_background"] or 0.0)
        > NozzleFocusCalibrationProcess.MIN_BEST_P90_BG_RATIO
    )


@pytest.mark.parametrize("run_id", TRACKED_Y_RUN_IDS)
def test_replay_tracked_y_fields_expose_machine_feedback_mislabels(run_id: str):
    rescored = _score_run(run_id)
    spec = RUN_SPECS[run_id]

    assert any(row["actual_Y"] != row["reported_Y"] for row in rescored)

    by_eval = {row["eval_count"]: row for row in rescored}
    mislabeled = by_eval[spec["mislabeled_eval"]]
    assert mislabeled["reported_Y"] == spec["mislabeled_reported_y"]
    assert mislabeled["actual_Y"] == spec["mislabeled_actual_y"]


@pytest.mark.parametrize("run_id", WRONG_DIRECTION_RUN_IDS)
def test_replay_legacy_metric_prefers_initial_positive_probe_over_negative_branch(run_id: str):
    rescored = _score_run(run_id)
    spec = RUN_SPECS[run_id]
    by_eval = {row["eval_count"]: row for row in rescored}

    positive_row = by_eval[spec["positive_eval"]]
    negative_row = by_eval[spec["negative_branch_eval"]]

    assert positive_row["actual_Y"] > by_eval[1]["actual_Y"]
    assert negative_row["actual_Y"] < by_eval[1]["actual_Y"]
    assert positive_row["focus_stats"]["var"] > negative_row["focus_stats"]["var"]
    assert (
        positive_row["focus_stats"]["p90_ratio_to_background"]
        > negative_row["focus_stats"]["p90_ratio_to_background"]
    )
    assert (
        positive_row["focus_stats"]["p90_ratio_to_background"]
        > NozzleFocusCalibrationProcess.MIN_BEST_P90_BG_RATIO
    )


@pytest.mark.parametrize("run_id", TINY_SIGNAL_RUN_IDS)
def test_replay_legacy_metric_prefers_earlier_stronger_signal_over_tiny_signal_high_y_basin(run_id: str):
    rescored = _score_run(run_id)
    spec = RUN_SPECS[run_id]
    by_eval = {row["eval_count"]: row for row in rescored}

    strong_row = by_eval[spec["strong_signal_eval"]]
    weak_basin_rows = [row for row in rescored if row["actual_Y"] >= int(spec["weak_basin_min_y"])]
    assert weak_basin_rows

    best_row = max(rescored, key=lambda row: float(row["focus_stats"]["var"] or 0.0))
    assert best_row["eval_count"] == spec["strong_signal_eval"]
    assert strong_row["focus_stats"]["var"] > max(row["focus_stats"]["var"] for row in weak_basin_rows)
    assert (
        strong_row["focus_stats"]["p90_ratio_to_background"]
        > NozzleFocusCalibrationProcess.MIN_BEST_P90_BG_RATIO
    )
    assert strong_row["focus_stats"]["p90_ratio_to_background"] > max(
        float(row["focus_stats"]["p90_ratio_to_background"] or 0.0) for row in weak_basin_rows
    )
