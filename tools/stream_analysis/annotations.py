from __future__ import annotations

import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from tools.stream_analysis import nozzle as nozzle_mod
from tools.stream_analysis.dataset import (
    _clean_text,
    _int_or_none,
    _preferred_columns,
    _write_csv,
    _write_json,
    build_stage0_inventory,
    default_output_root,
    resolve_experiment_root,
)


ANNOTATIONS_DIRNAME = "annotations"

ANNOTATION_MODES = [
    "attached_black_droplet_center",
    "attached_core_separation",
    "visible_nozzle_line",
    "only_nozzle",
    "manual_other",
]

MODE_HOTKEY_LABELS = [
    ("1", "attached_black_droplet_center"),
    ("2", "attached_core_separation"),
    ("3", "visible_nozzle_line"),
    ("4", "manual_other"),
    ("5", "only_nozzle"),
]

ANNOTATION_COLUMNS = [
    "frame_key",
    "run_id",
    "capture_index",
    "capture_id",
    "image_relpath",
    "image_abs_path",
    "captured_at_utc",
    "flash_delay_us",
    "delay_from_emergence_us",
    "image_width",
    "image_height",
    "annotated_nozzle_x_px",
    "annotated_nozzle_y_px",
    "annotation_mode",
    "seed_source",
    "seed_x_px",
    "seed_y_px",
    "predicted_x_px",
    "predicted_y_px",
    "predicted_mode",
    "predicted_confidence",
    "saved_at_utc",
    "session_id",
]

EVENT_COLUMNS = [
    "event_type",
    "session_id",
    "frame_key",
    "run_id",
    "capture_index",
    "old_x_px",
    "old_y_px",
    "old_mode",
    "new_x_px",
    "new_y_px",
    "new_mode",
    "saved_at_utc",
]

EVALUATION_COLUMNS = [
    "frame_key",
    "run_id",
    "capture_index",
    "image_relpath",
    "image_abs_path",
    "annotation_mode",
    "annotated_nozzle_x_px",
    "annotated_nozzle_y_px",
    "predicted_mode",
    "predicted_confidence",
    "predicted_x_px",
    "predicted_y_px",
    "dx_px",
    "dy_px",
    "distance_px",
    "mode_match",
    "prediction_source",
]

DIAGNOSTIC_BASE_COLUMNS = [
    "frame_key",
    "run_id",
    "capture_index",
    "image_relpath",
    "image_abs_path",
    "annotation_mode",
    "annotated_nozzle_x_px",
    "annotated_nozzle_y_px",
    "predicted_mode",
    "predicted_confidence",
    "predicted_x_px",
    "predicted_y_px",
    "predicted_dx_px",
    "predicted_dy_px",
    "predicted_distance_px",
    "best_candidate_name",
    "best_candidate_dx_px",
    "best_candidate_dy_px",
    "best_candidate_distance_px",
    "compact_droplet_score",
    "neck_y_px",
    "neck_width_px",
    "neck_score",
    "contour_completeness_score",
    "contour_bilateral_row_fraction",
    "contour_width_median_px",
    "contour_width_iqr_px",
    "contour_clipped_warning",
    "stable_visible_line_y_px",
    "pending_visible_line_y_px",
    "provisional_visible_line_y_px",
    "provisional_visible_line_count",
    "visible_line_search_center_y_px",
    "visible_line_search_radius_px",
    "visible_line_acquisition_search_center_y_px",
    "visible_line_acquisition_upper_bound_y_px",
    "line_band_y_px",
    "line_band_score",
    "late_widening_y_px",
    "late_widening_score",
    "late_widening_used",
    "visible_line_band_top_y_px",
    "visible_line_band_bottom_y_px",
    "visible_line_band_height_px",
    "visible_line_span_width_px",
    "visible_line_span_fraction",
    "visible_line_dark_delta",
    "visible_line_vertical_overlap",
    "visible_line_used_hysteresis",
    "visible_line_used_relaxed_fallback",
    "visible_line_used_plateau_only_fallback",
    "visible_line_valid_late_band",
    "visible_line_plateau_mode",
    "plateau_suppressed_on_acquisition",
    "hollow_bulb_guard_active",
    "visible_line_rejected_by_hollow_bulb_guard",
    "visible_line_rejected_by_upper_cue_conflict",
    "visible_line_lower_peak_prior_constrained",
    "visible_line_effective_lower_peak_y_px",
    "visible_line_bridge_x0_px",
    "visible_line_bridge_x1_px",
    "bridge_suppressed_by_clipped_contour",
    "bridge_suppressed_by_plateau",
    "bridge_suppressed_by_prior_conflict",
    "late_bridge_delta_from_prior_px",
    "late_plateau_delta_from_prior_px",
    "late_plateau_band_top_y_px",
    "late_plateau_band_bottom_y_px",
    "late_plateau_picked_y_px",
    "only_nozzle_y_px",
    "only_nozzle_score",
    "only_nozzle_roi_centers_y_px",
    "only_nozzle_selected_roi_center_y_px",
    "only_nozzle_candidate_source",
    "only_nozzle_prior_band_used",
    "only_nozzle_prior_band_candidate_count",
    "only_nozzle_rejected_far_from_prior",
    "only_nozzle_transition_scoring_used",
    "only_nozzle_distance_from_stable_prior_px",
    "only_nozzle_rejected_lower_reflection",
    "only_nozzle_anchor_rejected_as_low_reflection",
    "droplet_suppressed_as_reflection",
    "attached_support_score",
    "transition_fill_used",
    "transition_fill_source",
    "anchor_rejected_as_reflection",
]

DEFAULT_SEARCH_WIDTH_FRAC = 0.22
DEFAULT_SEARCH_TOP_FRAC = 0.08
DEFAULT_SEARCH_BOTTOM_FRAC = 0.30


def _utc_now_text():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _float_or_none(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _frame_key(run_id: str, capture_index: int):
    return f"{run_id}:{int(capture_index):04d}"


def _analysis_output_root(experiment_root: str | Path, output_root: str | Path | None = None):
    return (
        Path(output_root).expanduser().resolve()
        if output_root
        else default_output_root(experiment_root)
    )


def annotation_output_root(experiment_root: str | Path, output_root: str | Path | None = None):
    return _analysis_output_root(experiment_root, output_root=output_root) / ANNOTATIONS_DIRNAME


def annotation_paths(experiment_root: str | Path, output_root: str | Path | None = None):
    root = annotation_output_root(experiment_root, output_root=output_root)
    diagnostics_root = root / "diagnostics"
    candidate_overlays_root = diagnostics_root / "candidate_overlays"
    return {
        "root": root,
        "annotations_csv": root / "nozzle_annotations.csv",
        "events_jsonl": root / "nozzle_annotation_events.jsonl",
        "manifest_json": root / "nozzle_annotation_manifest.json",
        "state_json": root / "nozzle_annotation_state.json",
        "evaluation_csv": root / "nozzle_evaluation.csv",
        "evaluation_json": root / "nozzle_evaluation.json",
        "worst_frames_dir": root / "worst_frames",
        "diagnostics_root": diagnostics_root,
        "diagnostics_csv": diagnostics_root / "nozzle_candidate_diagnostics.csv",
        "diagnostics_json": diagnostics_root / "nozzle_candidate_summary.json",
        "candidate_overlays_root": candidate_overlays_root,
        "candidate_worst_dir": candidate_overlays_root / "worst_final_error",
        "candidate_differs_dir": candidate_overlays_root / "best_candidate_differs",
        "candidate_mode_mismatch_dir": candidate_overlays_root / "mode_mismatch",
    }


def _default_search_bounds(width: int, height: int):
    half_width = int(round(width * DEFAULT_SEARCH_WIDTH_FRAC / 2.0))
    center_x = width // 2
    x0 = max(0, center_x - half_width)
    x1 = min(width, center_x + half_width)
    y0 = max(0, min(height - 1, int(round(height * DEFAULT_SEARCH_TOP_FRAC))))
    y1 = max(y0 + 1, min(height, int(round(height * DEFAULT_SEARCH_BOTTOM_FRAC))))
    return {
        "x0": int(x0),
        "y0": int(y0),
        "x1": int(x1),
        "y1": int(y1),
    }


def _normalize_prediction_mode(mode):
    text = _clean_text(mode) or "manual_other"
    if text in ANNOTATION_MODES:
        return text
    return "manual_other"


def load_nozzle_annotations(experiment_root: str | Path, output_root: str | Path | None = None):
    paths = annotation_paths(experiment_root, output_root=output_root)
    csv_path = paths["annotations_csv"]
    if not csv_path.exists():
        return {}

    rows = {}
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        for raw_row in csv.DictReader(handle):
            frame_key = _clean_text(raw_row.get("frame_key"))
            if not frame_key:
                continue
            row = dict(raw_row)
            row["capture_index"] = _int_or_none(row.get("capture_index"))
            row["flash_delay_us"] = _int_or_none(row.get("flash_delay_us"))
            row["delay_from_emergence_us"] = _int_or_none(row.get("delay_from_emergence_us"))
            row["image_width"] = _int_or_none(row.get("image_width"))
            row["image_height"] = _int_or_none(row.get("image_height"))
            for key in [
                "annotated_nozzle_x_px",
                "annotated_nozzle_y_px",
                "seed_x_px",
                "seed_y_px",
                "predicted_x_px",
                "predicted_y_px",
                "predicted_confidence",
            ]:
                row[key] = _float_or_none(row.get(key))
            rows[frame_key] = row
    return rows


def load_nozzle_annotation_state(experiment_root: str | Path, output_root: str | Path | None = None):
    state_path = annotation_paths(experiment_root, output_root=output_root)["state_json"]
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text(encoding="utf-8"))


def _prediction_csv_candidates(experiment_root: str | Path, analysis_root: Path, run_id: str):
    default_root = default_output_root(experiment_root)
    seen = []
    for root in [analysis_root, default_root]:
        root = Path(root).resolve()
        candidate = root / "runs" / run_id / "stage_02_nozzle" / "nozzle_track.csv"
        candidate_text = str(candidate)
        if candidate_text in seen:
            continue
        seen.append(candidate_text)
        yield candidate


def load_stage2_prediction_lookup(
    experiment_root: str | Path,
    *,
    analysis_root: str | Path | None = None,
    run_ids: list[str] | None = None,
):
    experiment_path = resolve_experiment_root(experiment_root)
    analysis_path = (
        Path(analysis_root).expanduser().resolve()
        if analysis_root
        else default_output_root(experiment_path)
    )

    lookup = {}
    for run_id in run_ids or []:
        csv_path = None
        for candidate in _prediction_csv_candidates(experiment_path, analysis_path, run_id):
            if candidate.exists():
                csv_path = candidate
                break
        if csv_path is None:
            continue

        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                capture_index = _int_or_none(row.get("capture_index"))
                if capture_index is None:
                    continue
                frame_key = _frame_key(run_id, capture_index)
                tracked_x = _float_or_none(row.get("tracked_nozzle_x_px"))
                tracked_y = _float_or_none(row.get("tracked_nozzle_y_px"))
                raw_x = _float_or_none(row.get("raw_nozzle_x_px"))
                raw_y = _float_or_none(row.get("raw_nozzle_y_px"))
                lookup[frame_key] = {
                    "run_id": run_id,
                    "capture_index": capture_index,
                    "tracked_x_px": tracked_x,
                    "tracked_y_px": tracked_y,
                    "tracked_mode": _clean_text(row.get("final_mode")) or _clean_text(row.get("detection_mode")),
                    "tracked_confidence": _float_or_none(row.get("tracked_confidence")),
                    "raw_x_px": raw_x,
                    "raw_y_px": raw_y,
                    "raw_mode": _clean_text(row.get("raw_mode")),
                    "raw_confidence": _float_or_none(row.get("raw_confidence")),
                    "search_x0": _int_or_none(row.get("search_x0")),
                    "search_y0": _int_or_none(row.get("search_y0")),
                    "search_x1": _int_or_none(row.get("search_x1")),
                    "search_y1": _int_or_none(row.get("search_y1")),
                }
    return lookup


def build_annotation_queue(
    experiment_root: str | Path,
    *,
    output_root: str | Path | None = None,
    run_ids: list[str] | None = None,
    limit_runs: int | None = None,
    include_unmatched: bool = False,
):
    inventory = build_stage0_inventory(
        experiment_root,
        include_unmatched=include_unmatched,
        run_ids=run_ids,
        limit_runs=limit_runs,
    )
    analysis_root = _analysis_output_root(experiment_root, output_root=output_root)
    selected_run_ids = [str(row["run_id"]) for row in inventory["selected_runs"]]
    prediction_lookup = load_stage2_prediction_lookup(
        experiment_root,
        analysis_root=analysis_root,
        run_ids=selected_run_ids,
    )

    queue = []
    for run_order, run_row in enumerate(inventory["selected_runs"]):
        run_id = str(run_row["run_id"])
        for frame_row in inventory["frames_by_run_id"][run_id]:
            capture_index = _int_or_none(frame_row.get("capture_index"))
            if capture_index is None:
                continue
            frame_key = _frame_key(run_id, capture_index)
            prediction = prediction_lookup.get(frame_key, {})
            width = _int_or_none(frame_row.get("width")) or 0
            height = _int_or_none(frame_row.get("height")) or 0
            search = {
                "x0": prediction.get("search_x0"),
                "y0": prediction.get("search_y0"),
                "x1": prediction.get("search_x1"),
                "y1": prediction.get("search_y1"),
            }
            if None in search.values():
                search = _default_search_bounds(width, height)

            queue.append(
                {
                    "frame_key": frame_key,
                    "run_order": int(run_order),
                    "run_id": run_id,
                    "capture_index": capture_index,
                    "capture_id": _clean_text(frame_row.get("capture_id")),
                    "image_relpath": _clean_text(frame_row.get("image_relpath")),
                    "image_abs_path": _clean_text(frame_row.get("image_abs_path")),
                    "captured_at_utc": _clean_text(frame_row.get("captured_at_utc")),
                    "flash_delay_us": _int_or_none(frame_row.get("flash_delay_us")),
                    "delay_from_emergence_us": _int_or_none(frame_row.get("delay_from_emergence_us")),
                    "image_width": width,
                    "image_height": height,
                    "search_x0": int(search["x0"]),
                    "search_y0": int(search["y0"]),
                    "search_x1": int(search["x1"]),
                    "search_y1": int(search["y1"]),
                    "tracked_prediction_x_px": prediction.get("tracked_x_px"),
                    "tracked_prediction_y_px": prediction.get("tracked_y_px"),
                    "tracked_prediction_mode": prediction.get("tracked_mode"),
                    "tracked_prediction_confidence": prediction.get("tracked_confidence"),
                    "raw_prediction_x_px": prediction.get("raw_x_px"),
                    "raw_prediction_y_px": prediction.get("raw_y_px"),
                    "raw_prediction_mode": prediction.get("raw_mode"),
                    "raw_prediction_confidence": prediction.get("raw_confidence"),
                    "predicted_x_px": (
                        prediction.get("tracked_x_px")
                        if prediction.get("tracked_x_px") is not None and prediction.get("tracked_y_px") is not None
                        else prediction.get("raw_x_px")
                    ),
                    "predicted_y_px": (
                        prediction.get("tracked_y_px")
                        if prediction.get("tracked_x_px") is not None and prediction.get("tracked_y_px") is not None
                        else prediction.get("raw_y_px")
                    ),
                    "predicted_mode": (
                        prediction.get("tracked_mode")
                        if prediction.get("tracked_x_px") is not None and prediction.get("tracked_y_px") is not None
                        else prediction.get("raw_mode")
                    ),
                    "predicted_confidence": (
                        prediction.get("tracked_confidence")
                        if prediction.get("tracked_x_px") is not None and prediction.get("tracked_y_px") is not None
                        else prediction.get("raw_confidence")
                    ),
                }
            )

    return {
        "experiment_root": inventory["experiment_root"],
        "analysis_root": str(analysis_root),
        "selected_run_ids": selected_run_ids,
        "queue": queue,
    }


def resolve_annotation_start_index(
    queue: list[dict],
    *,
    state: dict | None = None,
    resume: bool = False,
    start_run_id: str | None = None,
    start_frame_index: int | None = None,
):
    if not queue:
        return 0

    frame_key_to_index = {row["frame_key"]: index for index, row in enumerate(queue)}
    if start_run_id or start_frame_index is not None:
        target_run_id = _clean_text(start_run_id) or str(queue[0]["run_id"])
        target_frame_index = int(start_frame_index or 1)
        target_key = _frame_key(target_run_id, target_frame_index)
        return int(frame_key_to_index.get(target_key, 0))

    if resume and state:
        target_key = _clean_text(state.get("current_frame_key"))
        if target_key in frame_key_to_index:
            return int(frame_key_to_index[target_key])

    return 0


def seed_annotation_for_queue_index(queue: list[dict], index: int, annotations_by_key: dict):
    frame = queue[index]
    current_key = frame["frame_key"]
    existing = annotations_by_key.get(current_key)
    if existing:
        return {
            "x_px": float(existing["annotated_nozzle_x_px"]),
            "y_px": float(existing["annotated_nozzle_y_px"]),
            "mode": _clean_text(existing.get("annotation_mode")) or "manual_other",
            "source": "existing_annotation",
        }

    run_id = str(frame["run_id"])
    for previous_index in range(index - 1, -1, -1):
        previous = queue[previous_index]
        if str(previous["run_id"]) != run_id:
            break
        previous_annotation = annotations_by_key.get(previous["frame_key"])
        if previous_annotation:
            return {
                "x_px": float(previous_annotation["annotated_nozzle_x_px"]),
                "y_px": float(previous_annotation["annotated_nozzle_y_px"]),
                "mode": _clean_text(previous_annotation.get("annotation_mode")) or "manual_other",
                "source": "previous_annotation",
            }

    if frame.get("tracked_prediction_x_px") is not None and frame.get("tracked_prediction_y_px") is not None:
        return {
            "x_px": float(frame["tracked_prediction_x_px"]),
            "y_px": float(frame["tracked_prediction_y_px"]),
            "mode": _normalize_prediction_mode(frame.get("tracked_prediction_mode")),
            "source": "tracked_prediction",
        }

    if frame.get("raw_prediction_x_px") is not None and frame.get("raw_prediction_y_px") is not None:
        return {
            "x_px": float(frame["raw_prediction_x_px"]),
            "y_px": float(frame["raw_prediction_y_px"]),
            "mode": _normalize_prediction_mode(frame.get("raw_prediction_mode")),
            "source": "raw_prediction",
        }

    return {
        "x_px": float((int(frame["search_x0"]) + int(frame["search_x1"])) / 2.0),
        "y_px": float((int(frame["search_y0"]) + int(frame["search_y1"])) / 2.0),
        "mode": "manual_other",
        "source": "search_roi_center",
    }


def _annotation_sort_key(row: dict):
    return (
        _clean_text(row.get("run_id")) or "",
        _int_or_none(row.get("capture_index")) or 0,
    )


def _append_event_row(path: Path, row: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def _annotation_progress_summary(queue: list[dict], annotations_by_key: dict):
    queue_keys = {row["frame_key"] for row in queue}
    annotated_count = int(sum(1 for key in queue_keys if key in annotations_by_key))
    total_count = int(len(queue))
    return {
        "queue_frame_count": total_count,
        "annotated_frame_count": annotated_count,
        "remaining_frame_count": int(max(0, total_count - annotated_count)),
        "saved_annotation_count_total": int(len(annotations_by_key)),
    }


def _write_annotation_state(
    paths: dict,
    *,
    experiment_root: str,
    analysis_root: str,
    session_id: str,
    current_frame_key: str,
    current_queue_index: int,
    selected_run_ids: list[str],
    last_saved_frame_key: str | None,
    show_prediction: bool,
    zoom_half_width: int,
):
    state = {
        "schema_version": 1,
        "experiment_root": experiment_root,
        "analysis_root": analysis_root,
        "session_id": session_id,
        "current_frame_key": current_frame_key,
        "current_queue_index": int(current_queue_index),
        "selected_run_ids": list(selected_run_ids),
        "last_saved_frame_key": last_saved_frame_key,
        "show_prediction": bool(show_prediction),
        "zoom_half_width": int(zoom_half_width),
        "updated_at_utc": _utc_now_text(),
    }
    _write_json(paths["state_json"], state)
    return state


def _write_annotation_manifest(
    paths: dict,
    *,
    experiment_root: str,
    analysis_root: str,
    session_id: str,
    selected_run_ids: list[str],
    queue: list[dict],
    annotations_by_key: dict,
    current_frame_key: str | None,
    last_saved_frame_key: str | None,
    show_prediction: bool,
    zoom_half_width: int,
):
    summary = _annotation_progress_summary(queue, annotations_by_key)
    manifest = {
        "schema_version": 1,
        "stage": "nozzle_annotations",
        "experiment_root": experiment_root,
        "analysis_root": analysis_root,
        "annotations_root": str(paths["root"]),
        "session_id": session_id,
        "selected_run_ids": list(selected_run_ids),
        "current_frame_key": current_frame_key,
        "last_saved_frame_key": last_saved_frame_key,
        "show_prediction": bool(show_prediction),
        "zoom_half_width": int(zoom_half_width),
        "summary": summary,
        "outputs": {
            "annotations_csv": str(paths["annotations_csv"]),
            "events_jsonl": str(paths["events_jsonl"]),
            "state_json": str(paths["state_json"]),
        },
    }
    _write_json(paths["manifest_json"], manifest)
    return manifest


def _selected_run_ids_from_queue(queue: list[dict]):
    return list(dict.fromkeys(str(item["run_id"]) for item in queue))


def save_nozzle_annotation(
    *,
    experiment_root: str | Path,
    output_root: str | Path | None,
    queue: list[dict],
    annotations_by_key: dict,
    queue_index: int,
    seed: dict,
    marker_x_px: float,
    marker_y_px: float,
    annotation_mode: str,
    session_id: str,
    show_prediction: bool,
    zoom_half_width: int,
):
    experiment_path = str(resolve_experiment_root(experiment_root))
    analysis_root = str(_analysis_output_root(experiment_root, output_root=output_root))
    paths = annotation_paths(experiment_root, output_root=output_root)
    frame = queue[queue_index]
    frame_key = frame["frame_key"]
    old_row = annotations_by_key.get(frame_key)
    saved_at_utc = _utc_now_text()

    row = {
        "frame_key": frame_key,
        "run_id": frame["run_id"],
        "capture_index": int(frame["capture_index"]),
        "capture_id": frame.get("capture_id"),
        "image_relpath": frame.get("image_relpath"),
        "image_abs_path": frame.get("image_abs_path"),
        "captured_at_utc": frame.get("captured_at_utc"),
        "flash_delay_us": frame.get("flash_delay_us"),
        "delay_from_emergence_us": frame.get("delay_from_emergence_us"),
        "image_width": frame.get("image_width"),
        "image_height": frame.get("image_height"),
        "annotated_nozzle_x_px": float(marker_x_px),
        "annotated_nozzle_y_px": float(marker_y_px),
        "annotation_mode": _clean_text(annotation_mode) or "manual_other",
        "seed_source": _clean_text(seed.get("source")) or "search_roi_center",
        "seed_x_px": float(seed["x_px"]),
        "seed_y_px": float(seed["y_px"]),
        "predicted_x_px": frame.get("predicted_x_px"),
        "predicted_y_px": frame.get("predicted_y_px"),
        "predicted_mode": frame.get("predicted_mode"),
        "predicted_confidence": frame.get("predicted_confidence"),
        "saved_at_utc": saved_at_utc,
        "session_id": session_id,
    }
    annotations_by_key[frame_key] = row

    ordered_rows = sorted(annotations_by_key.values(), key=_annotation_sort_key)
    _write_csv(
        paths["annotations_csv"],
        _preferred_columns(ordered_rows, ANNOTATION_COLUMNS),
        ordered_rows,
    )

    _append_event_row(
        paths["events_jsonl"],
        {
            "event_type": "annotation_saved",
            "session_id": session_id,
            "frame_key": frame_key,
            "run_id": frame["run_id"],
            "capture_index": int(frame["capture_index"]),
            "old_x_px": None if old_row is None else old_row.get("annotated_nozzle_x_px"),
            "old_y_px": None if old_row is None else old_row.get("annotated_nozzle_y_px"),
            "old_mode": None if old_row is None else old_row.get("annotation_mode"),
            "new_x_px": float(marker_x_px),
            "new_y_px": float(marker_y_px),
            "new_mode": row["annotation_mode"],
            "saved_at_utc": saved_at_utc,
        },
    )

    _write_annotation_state(
        paths,
        experiment_root=experiment_path,
        analysis_root=analysis_root,
        session_id=session_id,
        current_frame_key=frame_key,
        current_queue_index=queue_index,
        selected_run_ids=_selected_run_ids_from_queue(queue),
        last_saved_frame_key=frame_key,
        show_prediction=show_prediction,
        zoom_half_width=zoom_half_width,
    )
    _write_annotation_manifest(
        paths,
        experiment_root=experiment_path,
        analysis_root=analysis_root,
        session_id=session_id,
        selected_run_ids=_selected_run_ids_from_queue(queue),
        queue=queue,
        annotations_by_key=annotations_by_key,
        current_frame_key=frame_key,
        last_saved_frame_key=frame_key,
        show_prediction=show_prediction,
        zoom_half_width=zoom_half_width,
    )
    return row


def _prediction_for_evaluation(frame: dict, saved_annotation_row: dict | None):
    if frame.get("predicted_x_px") is not None and frame.get("predicted_y_px") is not None:
        return {
            "x_px": float(frame["predicted_x_px"]),
            "y_px": float(frame["predicted_y_px"]),
            "mode": frame.get("predicted_mode"),
            "confidence": frame.get("predicted_confidence"),
            "source": "live_stage2",
        }
    if saved_annotation_row and saved_annotation_row.get("predicted_x_px") is not None and saved_annotation_row.get("predicted_y_px") is not None:
        return {
            "x_px": float(saved_annotation_row["predicted_x_px"]),
            "y_px": float(saved_annotation_row["predicted_y_px"]),
            "mode": saved_annotation_row.get("predicted_mode"),
            "confidence": saved_annotation_row.get("predicted_confidence"),
            "source": "saved_annotation_prediction",
        }
    return {
        "x_px": None,
        "y_px": None,
        "mode": None,
        "confidence": None,
        "source": "missing_prediction",
    }


def _draw_overlay_marker(image: np.ndarray, point, color):
    if point[0] is None or point[1] is None:
        return image
    cv2.drawMarker(
        image,
        (int(round(float(point[0]))), int(round(float(point[1])))),
        color,
        markerType=cv2.MARKER_CROSS,
        markerSize=18,
        thickness=2,
    )
    return image


def _render_worst_frame_overlay(path: Path, row: dict):
    image_path = Path(str(row["image_abs_path"]))
    gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return None

    overlay = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    overlay = _draw_overlay_marker(
        overlay,
        (row.get("annotated_nozzle_x_px"), row.get("annotated_nozzle_y_px")),
        (0, 0, 255),
    )
    overlay = _draw_overlay_marker(
        overlay,
        (row.get("predicted_x_px"), row.get("predicted_y_px")),
        (0, 255, 0),
    )

    text_lines = [
        f"{row['run_id']} frame {row['capture_index']}",
        f"ann=({row['annotated_nozzle_x_px']:.1f}, {row['annotated_nozzle_y_px']:.1f})  pred=({row['predicted_x_px']:.1f}, {row['predicted_y_px']:.1f})",
        f"dx={row['dx_px']:.1f}  dy={row['dy_px']:.1f}  dist={row['distance_px']:.2f}",
        f"ann_mode={row['annotation_mode']}  pred_mode={row['predicted_mode']}",
    ]
    for line_index, text in enumerate(text_lines, start=1):
        cv2.putText(
            overlay,
            text,
            (14, 26 + (line_index * 26)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.60,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), overlay)
    return path


def _diagnostic_columns():
    columns = list(DIAGNOSTIC_BASE_COLUMNS)
    for mode in nozzle_mod.CANDIDATE_ORDER:
        prefix = mode
        columns.extend(
            [
                f"{prefix}_available",
                f"{prefix}_x_px",
                f"{prefix}_y_px",
                f"{prefix}_confidence",
                f"{prefix}_dx_px",
                f"{prefix}_dy_px",
                f"{prefix}_distance_px",
            ]
        )
    return columns


def _candidate_metric(candidate: dict | None, *, annotation_x: float, annotation_y: float, search: dict):
    if candidate is None:
        return {
            "available": False,
            "x_px": None,
            "y_px": None,
            "confidence": None,
            "dx_px": None,
            "dy_px": None,
            "distance_px": None,
        }

    x_px = float(search["x0"] + candidate["raw_x_local"])
    y_px = float(search["y0"] + candidate["raw_y_local"])
    dx_px = float(x_px - annotation_x)
    dy_px = float(y_px - annotation_y)
    return {
        "available": True,
        "x_px": x_px,
        "y_px": y_px,
        "confidence": float(candidate.get("confidence") or 0.0),
        "dx_px": dx_px,
        "dy_px": dy_px,
        "distance_px": float(np.hypot(dx_px, dy_px)),
    }


def _best_candidate_name(candidate_metrics: dict[str, dict]):
    available = [
        (name, metric)
        for name, metric in candidate_metrics.items()
        if bool(metric.get("available")) and metric.get("distance_px") is not None
    ]
    if not available:
        return None
    available.sort(
        key=lambda item: (
            abs(float(item[1]["dy_px"])),
            float(item[1]["distance_px"]),
            abs(float(item[1]["dx_px"])),
            nozzle_mod.CANDIDATE_ORDER.index(item[0]) if item[0] in nozzle_mod.CANDIDATE_ORDER else 999,
        )
    )
    return str(available[0][0])


def _draw_text_block(image: np.ndarray, lines: list[str]):
    for index, line in enumerate(lines, start=1):
        cv2.putText(
            image,
            line,
            (14, 20 + (index * 22)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.54,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )
    return image


def _fmt_optional(value, *, digits: int = 1):
    if value is None:
        return "n/a"
    return f"{float(value):.{digits}f}"


def _render_candidate_overlay(path: Path, row: dict):
    gray = cv2.imread(str(Path(str(row["image_abs_path"]))), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return None

    overlay = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    overlay = _draw_overlay_marker(
        overlay,
        (row.get("annotated_nozzle_x_px"), row.get("annotated_nozzle_y_px")),
        (0, 0, 255),
    )
    overlay = _draw_overlay_marker(
        overlay,
        (row.get("predicted_x_px"), row.get("predicted_y_px")),
        (0, 255, 0),
    )

    candidate_colors = {
        "attached_black_droplet_center": (255, 0, 255),
        "attached_core_separation": (255, 255, 0),
        "visible_nozzle_line": (0, 255, 255),
        "only_nozzle": (255, 128, 0),
    }
    for mode in nozzle_mod.CANDIDATE_ORDER:
        if not row.get(f"{mode}_available"):
            continue
        overlay = _draw_overlay_marker(
            overlay,
            (row.get(f"{mode}_x_px"), row.get(f"{mode}_y_px")),
            candidate_colors[mode],
        )
    for key, color in [
        ("stable_visible_line_y_px", (255, 0, 255)),
        ("pending_visible_line_y_px", (128, 0, 255)),
        ("neck_y_px", (255, 128, 0)),
        ("line_band_y_px", (0, 255, 255)),
        ("late_widening_y_px", (0, 128, 255)),
        ("visible_line_band_top_y_px", (0, 200, 255)),
        ("visible_line_band_bottom_y_px", (0, 200, 255)),
        ("late_plateau_band_top_y_px", (0, 128, 255)),
        ("late_plateau_band_bottom_y_px", (0, 128, 255)),
        ("only_nozzle_y_px", (255, 128, 0)),
        ("only_nozzle_selected_roi_center_y_px", (255, 0, 255)),
    ]:
        value = row.get(key)
        if value is None:
            continue
        y_px = int(round(float(value)))
        cv2.line(overlay, (0, y_px), (overlay.shape[1] - 1, y_px), color, 1)
    search_center_y = row.get("visible_line_search_center_y_px")
    search_radius = row.get("visible_line_search_radius_px")
    if search_center_y is not None and search_radius is not None:
        center_y = int(round(float(search_center_y)))
        radius = int(round(float(search_radius)))
        cv2.line(overlay, (0, max(0, center_y - radius)), (overlay.shape[1] - 1, max(0, center_y - radius)), (255, 0, 255), 1)
        cv2.line(overlay, (0, min(overlay.shape[0] - 1, center_y + radius)), (overlay.shape[1] - 1, min(overlay.shape[0] - 1, center_y + radius)), (255, 0, 255), 1)
    bridge_x0 = row.get("visible_line_bridge_x0_px")
    bridge_x1 = row.get("visible_line_bridge_x1_px")
    bridge_y = row.get("line_band_y_px")
    if bridge_x0 is not None and bridge_x1 is not None and bridge_y is not None:
        cv2.line(
            overlay,
            (int(round(float(bridge_x0))), int(round(float(bridge_y)))),
            (int(round(float(bridge_x1))), int(round(float(bridge_y)))),
            (0, 255, 0),
            2,
        )

    lines = [
        f"{row['run_id']} frame {row['capture_index']}",
        f"ann_mode={row['annotation_mode']} pred_mode={row.get('predicted_mode')} best={row.get('best_candidate_name')}",
        (
            f"pred dx={_fmt_optional(row.get('predicted_dx_px'))} "
            f"dy={_fmt_optional(row.get('predicted_dy_px'))} "
            f"dist={_fmt_optional(row.get('predicted_distance_px'))}"
        ),
    ]
    lines.append(
        (
            f"drop={_fmt_optional(row.get('compact_droplet_score'), digits=2)} "
            f"neck@{_fmt_optional(row.get('neck_y_px'))}/{_fmt_optional(row.get('neck_score'), digits=2)} "
            f"line@{_fmt_optional(row.get('line_band_y_px'))}/{_fmt_optional(row.get('line_band_score'), digits=2)} "
            f"widen@{_fmt_optional(row.get('late_widening_y_px'))}/{_fmt_optional(row.get('late_widening_score'), digits=2)} "
            f"only@{_fmt_optional(row.get('only_nozzle_y_px'))}/{_fmt_optional(row.get('only_nozzle_score'), digits=2)} "
            f"roi={row.get('only_nozzle_roi_centers_y_px') or 'n/a'} "
            f"sel={_fmt_optional(row.get('only_nozzle_selected_roi_center_y_px'))} "
            f"src={row.get('only_nozzle_candidate_source') or 'n/a'} "
            f"band={bool(row.get('only_nozzle_prior_band_used'))} "
            f"band_n={int(row.get('only_nozzle_prior_band_candidate_count') or 0)} "
            f"tr={bool(row.get('only_nozzle_transition_scoring_used'))} "
            f"only_d={_fmt_optional(row.get('only_nozzle_distance_from_stable_prior_px'))} "
            f"far_reject={bool(row.get('only_nozzle_rejected_far_from_prior'))}"
        )
    )
    lines.append(
        (
            f"contour={_fmt_optional(row.get('contour_completeness_score'), digits=2)} "
            f"bilat={_fmt_optional(row.get('contour_bilateral_row_fraction'), digits=2)} "
            f"wmed={_fmt_optional(row.get('contour_width_median_px'), digits=1)} "
            f"wiqr={_fmt_optional(row.get('contour_width_iqr_px'), digits=1)} "
            f"clip={bool(row.get('contour_clipped_warning'))} "
            f"bridge_suppr={bool(row.get('bridge_suppressed_by_clipped_contour'))} "
            f"plateau_suppr={bool(row.get('bridge_suppressed_by_plateau'))} "
            f"prior_suppr={bool(row.get('bridge_suppressed_by_prior_conflict'))} "
            f"drop_suppr={bool(row.get('droplet_suppressed_as_reflection'))} "
            f"far_reject={bool(row.get('only_nozzle_rejected_far_from_prior'))} "
            f"low_reject={bool(row.get('only_nozzle_rejected_lower_reflection'))} "
            f"anchor_low={bool(row.get('only_nozzle_anchor_rejected_as_low_reflection'))}"
        )
    )
    lines.append(
        (
            f"stable@{_fmt_optional(row.get('stable_visible_line_y_px'))} "
            f"pending@{_fmt_optional(row.get('pending_visible_line_y_px'))} "
            f"prov@{_fmt_optional(row.get('provisional_visible_line_y_px'))}/"
            f"{int(row.get('provisional_visible_line_count') or 0)} "
            f"search@{_fmt_optional(row.get('visible_line_search_center_y_px'))}"
            f"+/-{_fmt_optional(row.get('visible_line_search_radius_px'))} "
            f"acq@{_fmt_optional(row.get('visible_line_acquisition_search_center_y_px'))} "
            f"ub={_fmt_optional(row.get('visible_line_acquisition_upper_bound_y_px'))} "
            f"band={_fmt_optional(row.get('visible_line_band_top_y_px'))}"
            f"-{_fmt_optional(row.get('visible_line_band_bottom_y_px'))} "
            f"span={_fmt_optional(row.get('visible_line_span_fraction'), digits=2)} "
            f"dark={_fmt_optional(row.get('visible_line_dark_delta'), digits=1)} "
            f"overlap={_fmt_optional(row.get('visible_line_vertical_overlap'), digits=2)} "
            f"hyst={bool(row.get('visible_line_used_hysteresis'))} "
            f"relaxed={bool(row.get('visible_line_used_relaxed_fallback'))} "
            f"plateau_only={bool(row.get('visible_line_used_plateau_only_fallback'))} "
            f"late_band={bool(row.get('visible_line_valid_late_band'))} "
            f"plateau_mode={row.get('visible_line_plateau_mode') or 'n/a'} "
            f"plateau_acq={bool(row.get('plateau_suppressed_on_acquisition'))} "
            f"hollow={bool(row.get('hollow_bulb_guard_active'))} "
            f"hollow_reject={bool(row.get('visible_line_rejected_by_hollow_bulb_guard'))} "
            f"upper_reject={bool(row.get('visible_line_rejected_by_upper_cue_conflict'))} "
            f"widen_used={bool(row.get('late_widening_used'))} "
            f"lower_fix={bool(row.get('visible_line_lower_peak_prior_constrained'))} "
            f"bridge_d={_fmt_optional(row.get('late_bridge_delta_from_prior_px'))} "
            f"plateau_d={_fmt_optional(row.get('late_plateau_delta_from_prior_px'))}"
        )
    )
    lines.append(
        (
            f"fill_used={bool(row.get('transition_fill_used'))} "
            f"fill_src={row.get('transition_fill_source') or 'n/a'} "
            f"anchor_reject={bool(row.get('anchor_rejected_as_reflection'))}"
        )
    )
    for mode in nozzle_mod.CANDIDATE_ORDER:
        if not row.get(f"{mode}_available"):
            continue
        lines.append(
            f"{mode}: dy={_fmt_optional(row.get(f'{mode}_dy_px'))} dist={_fmt_optional(row.get(f'{mode}_distance_px'))}"
        )
    overlay = _draw_text_block(overlay, lines)

    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), overlay)
    return path


def diagnose_nozzle_candidates(
    experiment_root: str | Path,
    *,
    output_root: str | Path | None = None,
    run_ids: list[str] | None = None,
    limit_runs: int | None = None,
    include_unmatched: bool = False,
    limit_worst_frames: int = 50,
    search_width_frac: float = 0.22,
    search_top_frac: float = 0.08,
    search_bottom_frac: float = 0.30,
    blur_sigma: float = 12.0,
    residual_scale: float = 2.5,
    residual_threshold: int = 18,
    min_area_px: int = 120,
    top_band_slack_px: int = 14,
):
    queue_payload = build_annotation_queue(
        experiment_root,
        output_root=output_root,
        run_ids=run_ids,
        limit_runs=limit_runs,
        include_unmatched=include_unmatched,
    )
    queue = queue_payload["queue"]
    queue_by_key = {row["frame_key"]: row for row in queue}
    annotations_by_key = load_nozzle_annotations(experiment_root, output_root=output_root)
    if not annotations_by_key:
        raise FileNotFoundError("No nozzle annotations were found for this experiment.")

    paths = annotation_paths(experiment_root, output_root=output_root)
    diagnostics_by_frame_key = {}
    queue_by_run_id = {}
    for frame in queue:
        queue_by_run_id.setdefault(str(frame["run_id"]), []).append(frame)
    for run_id, run_frames in queue_by_run_id.items():
        raw_rows, frame_diagnostics = nozzle_mod._detect_run_raw_rows(
            run_id,
            run_frames,
            search_width_frac=search_width_frac,
            search_top_frac=search_top_frac,
            search_bottom_frac=search_bottom_frac,
            blur_sigma=blur_sigma,
            residual_scale=residual_scale,
            residual_threshold=residual_threshold,
            min_area_px=min_area_px,
            top_band_slack_px=top_band_slack_px,
        )
        for frame, raw_row, diagnostics in zip(run_frames, raw_rows, frame_diagnostics):
            diagnostics_by_frame_key[str(frame["frame_key"])] = {
                "raw_row": raw_row,
                "diagnostics": diagnostics,
            }

    rows = []
    for frame_key, annotation_row in sorted(annotations_by_key.items(), key=lambda item: _annotation_sort_key(item[1])):
        if queue_by_key and frame_key not in queue_by_key:
            continue

        frame = queue_by_key.get(frame_key, {})
        diagnostics_bundle = diagnostics_by_frame_key.get(frame_key)
        if diagnostics_bundle is None:
            continue
        diagnostics = diagnostics_bundle["diagnostics"]
        annotation_x = float(annotation_row["annotated_nozzle_x_px"])
        annotation_y = float(annotation_row["annotated_nozzle_y_px"])
        prediction = _prediction_for_evaluation(frame, annotation_row)
        predicted_x = prediction["x_px"]
        predicted_y = prediction["y_px"]
        predicted_dx = None if predicted_x is None else float(predicted_x - annotation_x)
        predicted_dy = None if predicted_y is None else float(predicted_y - annotation_y)
        predicted_distance = None if predicted_dx is None or predicted_dy is None else float(np.hypot(predicted_dx, predicted_dy))

        candidate_metrics = {}
        for mode in nozzle_mod.CANDIDATE_ORDER:
            candidate_metrics[mode] = _candidate_metric(
                diagnostics.get("candidates", {}).get(mode),
                annotation_x=annotation_x,
                annotation_y=annotation_y,
                search=diagnostics["search"],
            )
        best_candidate_name = _best_candidate_name(candidate_metrics)
        best_metric = candidate_metrics.get(best_candidate_name or "", {})

        row = {
            "frame_key": frame_key,
            "run_id": annotation_row["run_id"],
            "capture_index": int(annotation_row["capture_index"]),
            "image_relpath": annotation_row.get("image_relpath"),
            "image_abs_path": annotation_row.get("image_abs_path"),
            "annotation_mode": annotation_row.get("annotation_mode"),
            "annotated_nozzle_x_px": annotation_x,
            "annotated_nozzle_y_px": annotation_y,
            "predicted_mode": _clean_text(prediction.get("mode")),
            "predicted_confidence": prediction.get("confidence"),
            "predicted_x_px": predicted_x,
            "predicted_y_px": predicted_y,
            "predicted_dx_px": predicted_dx,
            "predicted_dy_px": predicted_dy,
            "predicted_distance_px": predicted_distance,
            "best_candidate_name": best_candidate_name,
            "best_candidate_dx_px": best_metric.get("dx_px"),
            "best_candidate_dy_px": best_metric.get("dy_px"),
            "best_candidate_distance_px": best_metric.get("distance_px"),
            "compact_droplet_score": diagnostics.get("compact_droplet_score"),
            "neck_y_px": None
            if diagnostics.get("neck_y_local") is None
            else float(diagnostics["search"]["y0"] + diagnostics["neck_y_local"]),
            "neck_width_px": diagnostics.get("neck_width_px"),
            "neck_score": diagnostics.get("neck_score"),
            "contour_completeness_score": diagnostics.get("contour_completeness_score"),
            "contour_bilateral_row_fraction": diagnostics.get("contour_bilateral_row_fraction"),
            "contour_width_median_px": diagnostics.get("contour_width_median_px"),
            "contour_width_iqr_px": diagnostics.get("contour_width_iqr_px"),
            "contour_clipped_warning": bool(diagnostics.get("contour_clipped_warning")),
            "stable_visible_line_y_px": None
            if diagnostics.get("stable_visible_line_y_local") is None
            else float(diagnostics["search"]["y0"] + diagnostics["stable_visible_line_y_local"]),
            "pending_visible_line_y_px": diagnostics_bundle["raw_row"].get("pending_visible_line_y_px"),
            "provisional_visible_line_y_px": diagnostics_bundle["raw_row"].get("provisional_visible_line_y_px"),
            "provisional_visible_line_count": diagnostics_bundle["raw_row"].get("provisional_visible_line_count"),
            "visible_line_search_center_y_px": None
            if diagnostics.get("visible_line_search_center_y_local") is None
            else float(diagnostics["search"]["y0"] + diagnostics["visible_line_search_center_y_local"]),
            "visible_line_search_radius_px": diagnostics.get("visible_line_search_radius_px"),
            "visible_line_acquisition_search_center_y_px": None
            if diagnostics.get("visible_line_acquisition_search_center_y_local") is None
            else float(diagnostics["search"]["y0"] + diagnostics["visible_line_acquisition_search_center_y_local"]),
            "visible_line_acquisition_upper_bound_y_px": None
            if diagnostics.get("visible_line_acquisition_upper_bound_y_local") is None
            else float(diagnostics["search"]["y0"] + diagnostics["visible_line_acquisition_upper_bound_y_local"]),
            "line_band_y_px": None
            if diagnostics.get("line_band_y_local") is None
            else float(diagnostics["search"]["y0"] + diagnostics["line_band_y_local"]),
            "line_band_score": diagnostics.get("line_band_score"),
            "late_widening_y_px": None
            if diagnostics.get("late_widening_y_local") is None
            else float(diagnostics["search"]["y0"] + diagnostics["late_widening_y_local"]),
            "late_widening_score": diagnostics.get("late_widening_score"),
            "late_widening_used": bool(diagnostics.get("late_widening_used")),
            "visible_line_band_top_y_px": None
            if diagnostics.get("visible_line_band_top_y_local") is None
            else float(diagnostics["search"]["y0"] + diagnostics["visible_line_band_top_y_local"]),
            "visible_line_band_bottom_y_px": None
            if diagnostics.get("visible_line_band_bottom_y_local") is None
            else float(diagnostics["search"]["y0"] + diagnostics["visible_line_band_bottom_y_local"]),
            "visible_line_band_height_px": diagnostics.get("visible_line_band_height_px"),
            "visible_line_span_width_px": diagnostics.get("visible_line_span_width_px"),
            "visible_line_span_fraction": diagnostics.get("visible_line_span_fraction"),
            "visible_line_dark_delta": diagnostics.get("visible_line_dark_delta"),
            "visible_line_vertical_overlap": diagnostics.get("visible_line_vertical_overlap"),
            "visible_line_used_hysteresis": bool(diagnostics.get("visible_line_used_hysteresis")),
            "visible_line_used_relaxed_fallback": bool(diagnostics.get("visible_line_used_relaxed_fallback")),
            "visible_line_used_plateau_only_fallback": bool(diagnostics.get("visible_line_used_plateau_only_fallback")),
            "visible_line_valid_late_band": bool(diagnostics.get("visible_line_valid_late_band")),
            "visible_line_plateau_mode": diagnostics.get("visible_line_plateau_mode"),
            "plateau_suppressed_on_acquisition": bool(diagnostics.get("plateau_suppressed_on_acquisition")),
            "hollow_bulb_guard_active": bool(diagnostics.get("hollow_bulb_guard_active")),
            "visible_line_rejected_by_hollow_bulb_guard": bool(diagnostics.get("visible_line_rejected_by_hollow_bulb_guard")),
            "visible_line_rejected_by_upper_cue_conflict": bool(diagnostics.get("visible_line_rejected_by_upper_cue_conflict")),
            "visible_line_lower_peak_prior_constrained": bool(diagnostics.get("visible_line_lower_peak_prior_constrained")),
            "visible_line_effective_lower_peak_y_px": None
            if diagnostics.get("visible_line_effective_lower_peak_y_local") is None
            else float(diagnostics["search"]["y0"] + diagnostics["visible_line_effective_lower_peak_y_local"]),
            "visible_line_bridge_x0_px": None
            if diagnostics.get("visible_line_bridge_x0_local") is None
            else float(diagnostics["search"]["x0"] + diagnostics["visible_line_bridge_x0_local"]),
            "visible_line_bridge_x1_px": None
            if diagnostics.get("visible_line_bridge_x1_local") is None
            else float(diagnostics["search"]["x0"] + diagnostics["visible_line_bridge_x1_local"]),
            "bridge_suppressed_by_clipped_contour": bool(diagnostics.get("bridge_suppressed_by_clipped_contour")),
            "bridge_suppressed_by_plateau": bool(diagnostics.get("bridge_suppressed_by_plateau")),
            "bridge_suppressed_by_prior_conflict": bool(diagnostics.get("bridge_suppressed_by_prior_conflict")),
            "late_bridge_delta_from_prior_px": diagnostics.get("late_bridge_delta_from_prior_px"),
            "late_plateau_delta_from_prior_px": diagnostics.get("late_plateau_delta_from_prior_px"),
            "late_plateau_band_top_y_px": None
            if diagnostics.get("late_plateau_band_top_y_local") is None
            else float(diagnostics["search"]["y0"] + diagnostics["late_plateau_band_top_y_local"]),
            "late_plateau_band_bottom_y_px": None
            if diagnostics.get("late_plateau_band_bottom_y_local") is None
            else float(diagnostics["search"]["y0"] + diagnostics["late_plateau_band_bottom_y_local"]),
            "late_plateau_picked_y_px": None
            if diagnostics.get("late_plateau_picked_y_local") is None
            else float(diagnostics["search"]["y0"] + diagnostics["late_plateau_picked_y_local"]),
            "only_nozzle_y_px": None
            if diagnostics.get("only_nozzle_y_local") is None
            else float(diagnostics["search"]["y0"] + diagnostics["only_nozzle_y_local"]),
            "only_nozzle_score": diagnostics.get("only_nozzle_score"),
            "only_nozzle_roi_centers_y_px": nozzle_mod._serialize_float_list(
                None
                if diagnostics.get("only_nozzle_roi_centers_y_local") is None
                else [float(diagnostics["search"]["y0"] + float(value)) for value in diagnostics["only_nozzle_roi_centers_y_local"]]
            ),
            "only_nozzle_selected_roi_center_y_px": None
            if diagnostics.get("only_nozzle_selected_roi_center_y_local") is None
            else float(diagnostics["search"]["y0"] + diagnostics["only_nozzle_selected_roi_center_y_local"]),
            "only_nozzle_candidate_source": diagnostics.get("only_nozzle_candidate_source"),
            "only_nozzle_prior_band_used": bool(diagnostics.get("only_nozzle_prior_band_used")),
            "only_nozzle_prior_band_candidate_count": int(diagnostics.get("only_nozzle_prior_band_candidate_count") or 0),
            "only_nozzle_rejected_far_from_prior": bool(diagnostics.get("only_nozzle_rejected_far_from_prior")),
            "only_nozzle_transition_scoring_used": bool(diagnostics.get("only_nozzle_transition_scoring_used")),
            "only_nozzle_distance_from_stable_prior_px": diagnostics.get("only_nozzle_distance_from_stable_prior_px"),
            "only_nozzle_rejected_lower_reflection": bool(diagnostics.get("only_nozzle_rejected_lower_reflection")),
            "only_nozzle_anchor_rejected_as_low_reflection": bool(diagnostics.get("only_nozzle_anchor_rejected_as_low_reflection")),
            "droplet_suppressed_as_reflection": bool(diagnostics.get("droplet_suppressed_as_reflection")),
            "attached_support_score": diagnostics.get("attached_support_score"),
            "transition_fill_used": bool(diagnostics_bundle["raw_row"].get("transition_fill_used")),
            "transition_fill_source": diagnostics_bundle["raw_row"].get("transition_fill_source"),
            "anchor_rejected_as_reflection": bool(diagnostics_bundle["raw_row"].get("anchor_rejected_as_reflection")),
        }
        for mode, metric in candidate_metrics.items():
            row[f"{mode}_available"] = bool(metric["available"])
            row[f"{mode}_x_px"] = metric["x_px"]
            row[f"{mode}_y_px"] = metric["y_px"]
            row[f"{mode}_confidence"] = metric["confidence"]
            row[f"{mode}_dx_px"] = metric["dx_px"]
            row[f"{mode}_dy_px"] = metric["dy_px"]
            row[f"{mode}_distance_px"] = metric["distance_px"]
        rows.append(row)

    _write_csv(paths["diagnostics_csv"], _preferred_columns(rows, _diagnostic_columns()), rows)

    predicted_distances = [float(row["predicted_distance_px"]) for row in rows if row.get("predicted_distance_px") is not None]
    best_distances = [float(row["best_candidate_distance_px"]) for row in rows if row.get("best_candidate_distance_px") is not None]

    per_mode_summary = {}
    best_name_counts = {}
    candidate_summaries = {}
    for mode in nozzle_mod.CANDIDATE_ORDER:
        candidate_distance_values = [float(row[f"{mode}_distance_px"]) for row in rows if row.get(f"{mode}_distance_px") is not None]
        candidate_summaries[mode] = {
            "available_count": int(sum(1 for row in rows if bool(row.get(f"{mode}_available")))),
            "distance_mean_px": float(np.mean(candidate_distance_values)) if candidate_distance_values else None,
            "distance_median_px": float(np.median(candidate_distance_values)) if candidate_distance_values else None,
            "distance_max_px": float(max(candidate_distance_values)) if candidate_distance_values else None,
        }

    for row in rows:
        annotation_mode = str(row["annotation_mode"])
        bucket = per_mode_summary.setdefault(
            annotation_mode,
            {
                "count": 0,
                "predicted_distances": [],
                "best_candidate_distances": [],
                "best_candidate_name_counts": {},
            },
        )
        bucket["count"] += 1
        if row.get("predicted_distance_px") is not None:
            bucket["predicted_distances"].append(float(row["predicted_distance_px"]))
        if row.get("best_candidate_distance_px") is not None:
            bucket["best_candidate_distances"].append(float(row["best_candidate_distance_px"]))
        best_name = row.get("best_candidate_name")
        if best_name:
            bucket["best_candidate_name_counts"][best_name] = int(bucket["best_candidate_name_counts"].get(best_name, 0) + 1)
            best_name_counts[best_name] = int(best_name_counts.get(best_name, 0) + 1)

    for bucket in per_mode_summary.values():
        predicted_values = bucket.pop("predicted_distances")
        best_values = bucket.pop("best_candidate_distances")
        bucket["predicted_distance_mean_px"] = float(np.mean(predicted_values)) if predicted_values else None
        bucket["predicted_distance_median_px"] = float(np.median(predicted_values)) if predicted_values else None
        bucket["best_candidate_distance_mean_px"] = float(np.mean(best_values)) if best_values else None
        bucket["best_candidate_distance_median_px"] = float(np.median(best_values)) if best_values else None

    worst_rows = sorted(
        [row for row in rows if row.get("predicted_distance_px") is not None],
        key=lambda row: float(row["predicted_distance_px"]),
        reverse=True,
    )[: max(0, int(limit_worst_frames))]
    best_candidate_differs = [
        row for row in rows if row.get("best_candidate_name") and row.get("best_candidate_name") != row.get("predicted_mode")
    ][: max(0, int(limit_worst_frames))]
    mode_mismatch = [
        row for row in rows if row.get("predicted_mode") and row.get("predicted_mode") != row.get("annotation_mode")
    ][: max(0, int(limit_worst_frames))]

    overlay_paths = {
        "worst_final_error": [],
        "best_candidate_differs": [],
        "mode_mismatch": [],
    }
    for key, source_rows, directory in [
        ("worst_final_error", worst_rows, paths["candidate_worst_dir"]),
        ("best_candidate_differs", best_candidate_differs, paths["candidate_differs_dir"]),
        ("mode_mismatch", mode_mismatch, paths["candidate_mode_mismatch_dir"]),
    ]:
        for row in source_rows:
            output_path = directory / f"frame_{row['run_id']}_{int(row['capture_index']):04d}.png"
            rendered = _render_candidate_overlay(output_path, row)
            if rendered is not None:
                overlay_paths[key].append(str(rendered))

    payload = {
        "schema_version": 1,
        "stage": "diagnose_nozzle",
        "experiment_root": str(resolve_experiment_root(experiment_root)),
        "analysis_root": str(_analysis_output_root(experiment_root, output_root=output_root)),
        "annotations_root": str(paths["root"]),
        "selected_run_ids": list(queue_payload["selected_run_ids"]),
        "diagnostic_row_count": int(len(rows)),
        "predicted_distance_mean_px": float(np.mean(predicted_distances)) if predicted_distances else None,
        "predicted_distance_median_px": float(np.median(predicted_distances)) if predicted_distances else None,
        "best_candidate_distance_mean_px": float(np.mean(best_distances)) if best_distances else None,
        "best_candidate_distance_median_px": float(np.median(best_distances)) if best_distances else None,
        "best_candidate_name_counts": best_name_counts,
        "per_annotation_mode_summary": per_mode_summary,
        "candidate_summaries": candidate_summaries,
        "outputs": {
            "diagnostics_csv": str(paths["diagnostics_csv"]),
            "diagnostics_json": str(paths["diagnostics_json"]),
            "candidate_overlays_root": str(paths["candidate_overlays_root"]),
            "worst_final_error_paths": overlay_paths["worst_final_error"],
            "best_candidate_differs_paths": overlay_paths["best_candidate_differs"],
            "mode_mismatch_paths": overlay_paths["mode_mismatch"],
        },
    }
    _write_json(paths["diagnostics_json"], payload)
    return payload


def evaluate_nozzle_annotations(
    experiment_root: str | Path,
    *,
    output_root: str | Path | None = None,
    run_ids: list[str] | None = None,
    limit_runs: int | None = None,
    include_unmatched: bool = False,
    limit_worst_frames: int = 50,
):
    queue_payload = build_annotation_queue(
        experiment_root,
        output_root=output_root,
        run_ids=run_ids,
        limit_runs=limit_runs,
        include_unmatched=include_unmatched,
    )
    queue = queue_payload["queue"]
    queue_by_key = {row["frame_key"]: row for row in queue}
    annotations_by_key = load_nozzle_annotations(experiment_root, output_root=output_root)
    if not annotations_by_key:
        raise FileNotFoundError("No nozzle annotations were found for this experiment.")

    paths = annotation_paths(experiment_root, output_root=output_root)
    rows = []
    for frame_key, annotation_row in sorted(annotations_by_key.items(), key=lambda item: _annotation_sort_key(item[1])):
        if queue_by_key and frame_key not in queue_by_key:
            continue
        frame = queue_by_key.get(frame_key, {})
        prediction = _prediction_for_evaluation(frame, annotation_row)
        annotated_x = float(annotation_row["annotated_nozzle_x_px"])
        annotated_y = float(annotation_row["annotated_nozzle_y_px"])
        predicted_x = prediction["x_px"]
        predicted_y = prediction["y_px"]
        dx_px = None if predicted_x is None else float(predicted_x - annotated_x)
        dy_px = None if predicted_y is None else float(predicted_y - annotated_y)
        distance_px = None if dx_px is None or dy_px is None else float(np.hypot(dx_px, dy_px))
        predicted_mode = _clean_text(prediction.get("mode"))
        rows.append(
            {
                "frame_key": frame_key,
                "run_id": annotation_row["run_id"],
                "capture_index": int(annotation_row["capture_index"]),
                "image_relpath": annotation_row.get("image_relpath"),
                "image_abs_path": annotation_row.get("image_abs_path"),
                "annotation_mode": annotation_row.get("annotation_mode"),
                "annotated_nozzle_x_px": annotated_x,
                "annotated_nozzle_y_px": annotated_y,
                "predicted_mode": predicted_mode,
                "predicted_confidence": prediction.get("confidence"),
                "predicted_x_px": predicted_x,
                "predicted_y_px": predicted_y,
                "dx_px": dx_px,
                "dy_px": dy_px,
                "distance_px": distance_px,
                "mode_match": bool(
                    predicted_mode is not None
                    and _normalize_prediction_mode(predicted_mode) == annotation_row.get("annotation_mode")
                ),
                "prediction_source": prediction["source"],
            }
        )

    _write_csv(paths["evaluation_csv"], _preferred_columns(rows, EVALUATION_COLUMNS), rows)

    distances = [float(row["distance_px"]) for row in rows if row.get("distance_px") is not None]
    matched_prediction_count = int(sum(1 for row in rows if row.get("predicted_x_px") is not None))
    missing_prediction_count = int(len(rows) - matched_prediction_count)

    per_run = {}
    per_mode = {}
    for row in rows:
        run_bucket = per_run.setdefault(
            row["run_id"],
            {"count": 0, "matched_prediction_count": 0, "distance_values": [], "mode_match_count": 0},
        )
        mode_bucket = per_mode.setdefault(
            row["annotation_mode"],
            {"count": 0, "matched_prediction_count": 0, "distance_values": [], "mode_match_count": 0},
        )
        for bucket in [run_bucket, mode_bucket]:
            bucket["count"] += 1
            if row.get("predicted_x_px") is not None:
                bucket["matched_prediction_count"] += 1
            if row.get("distance_px") is not None:
                bucket["distance_values"].append(float(row["distance_px"]))
            if row.get("mode_match"):
                bucket["mode_match_count"] += 1

    def _bucket_summary(source: dict):
        payload = {}
        for key, bucket in source.items():
            distance_values = bucket.pop("distance_values")
            payload[key] = {
                **bucket,
                "distance_mean_px": float(np.mean(distance_values)) if distance_values else None,
                "distance_median_px": float(np.median(distance_values)) if distance_values else None,
                "distance_max_px": float(max(distance_values)) if distance_values else None,
                "mode_match_rate": float(bucket["mode_match_count"] / bucket["count"]) if bucket["count"] else None,
            }
        return payload

    worst_rows = sorted(
        [row for row in rows if row.get("distance_px") is not None],
        key=lambda row: float(row["distance_px"]),
        reverse=True,
    )[: max(0, int(limit_worst_frames))]
    worst_frame_paths = []
    for row in worst_rows:
        output_path = paths["worst_frames_dir"] / f"frame_{row['run_id']}_{int(row['capture_index']):04d}.png"
        rendered = _render_worst_frame_overlay(output_path, row)
        if rendered is not None:
            worst_frame_paths.append(str(rendered))

    payload = {
        "schema_version": 1,
        "stage": "evaluate_nozzle",
        "experiment_root": str(resolve_experiment_root(experiment_root)),
        "analysis_root": str(_analysis_output_root(experiment_root, output_root=output_root)),
        "annotations_root": str(paths["root"]),
        "annotation_row_count": int(len(rows)),
        "matched_prediction_count": matched_prediction_count,
        "missing_prediction_count": missing_prediction_count,
        "distance_mean_px": float(np.mean(distances)) if distances else None,
        "distance_median_px": float(np.median(distances)) if distances else None,
        "distance_max_px": float(max(distances)) if distances else None,
        "per_run_summary": _bucket_summary(per_run),
        "per_mode_summary": _bucket_summary(per_mode),
        "worst_frame_count": int(len(worst_frame_paths)),
        "outputs": {
            "evaluation_csv": str(paths["evaluation_csv"]),
            "evaluation_json": str(paths["evaluation_json"]),
            "worst_frames_dir": str(paths["worst_frames_dir"]),
            "worst_frame_paths": worst_frame_paths,
        },
    }
    _write_json(paths["evaluation_json"], payload)
    return payload


class NozzleAnnotationSession:
    def __init__(
        self,
        *,
        experiment_root: str | Path,
        output_root: str | Path | None,
        queue_payload: dict,
        annotations_by_key: dict,
        session_id: str,
        current_index: int,
        show_prediction: bool,
        zoom_half_width: int,
    ):
        self.experiment_root = str(resolve_experiment_root(experiment_root))
        self.analysis_root = str(_analysis_output_root(experiment_root, output_root=output_root))
        self.output_root = output_root
        self.paths = annotation_paths(experiment_root, output_root=output_root)
        self.queue_payload = queue_payload
        self.queue = list(queue_payload["queue"])
        self.annotations_by_key = annotations_by_key
        self.session_id = str(session_id)
        self.current_index = int(max(0, min(current_index, max(0, len(self.queue) - 1))))
        self.show_prediction = bool(show_prediction)
        self.zoom_half_width = int(max(20, zoom_half_width))
        self.figure = None
        self.axes = None
        self.current_image = None
        self.current_seed = None
        self.marker_x_px = None
        self.marker_y_px = None
        self.annotation_mode = "manual_other"
        self.dirty = False
        self.last_saved_frame_key = _clean_text(load_nozzle_annotation_state(experiment_root, output_root=output_root).get("last_saved_frame_key"))
        self.status_message = ""
        self.zoom_origin_x = 0
        self.zoom_origin_y = 0

    def _clip_point(self, x_px: float, y_px: float):
        frame = self.queue[self.current_index]
        max_x = max(0, int(frame["image_width"]) - 1)
        max_y = max(0, int(frame["image_height"]) - 1)
        return float(min(max(0, round(float(x_px))), max_x)), float(min(max(0, round(float(y_px))), max_y))

    def _load_current_frame(self):
        frame = self.queue[self.current_index]
        gray = cv2.imread(str(frame["image_abs_path"]), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise FileNotFoundError(f"Could not load frame for annotation: {frame['image_abs_path']}")
        self.current_image = gray
        self.current_seed = seed_annotation_for_queue_index(self.queue, self.current_index, self.annotations_by_key)
        self.marker_x_px, self.marker_y_px = self._clip_point(self.current_seed["x_px"], self.current_seed["y_px"])
        self.annotation_mode = _clean_text(self.current_seed.get("mode")) or "manual_other"
        self.dirty = False
        self.status_message = f"seed={self.current_seed['source']}"

    def _set_marker(self, x_px: float, y_px: float):
        self.marker_x_px, self.marker_y_px = self._clip_point(x_px, y_px)
        self.dirty = True

    def _move_marker(self, dx_px: float, dy_px: float):
        self._set_marker((self.marker_x_px or 0.0) + dx_px, (self.marker_y_px or 0.0) + dy_px)

    def _zoom_crop(self):
        x_center = int(round(float(self.marker_x_px or 0.0)))
        y_center = int(round(float(self.marker_y_px or 0.0)))
        half = int(self.zoom_half_width)
        x0 = max(0, x_center - half)
        x1 = min(self.current_image.shape[1], x_center + half)
        y0 = max(0, y_center - half)
        y1 = min(self.current_image.shape[0], y_center + half)
        self.zoom_origin_x = int(x0)
        self.zoom_origin_y = int(y0)
        return self.current_image[y0:y1, x0:x1]

    def _write_session_state(self):
        current_frame_key = self.queue[self.current_index]["frame_key"]
        _write_annotation_state(
            self.paths,
            experiment_root=self.experiment_root,
            analysis_root=self.analysis_root,
            session_id=self.session_id,
            current_frame_key=current_frame_key,
            current_queue_index=self.current_index,
            selected_run_ids=self.queue_payload["selected_run_ids"],
            last_saved_frame_key=self.last_saved_frame_key,
            show_prediction=self.show_prediction,
            zoom_half_width=self.zoom_half_width,
        )
        _write_annotation_manifest(
            self.paths,
            experiment_root=self.experiment_root,
            analysis_root=self.analysis_root,
            session_id=self.session_id,
            selected_run_ids=self.queue_payload["selected_run_ids"],
            queue=self.queue,
            annotations_by_key=self.annotations_by_key,
            current_frame_key=current_frame_key,
            last_saved_frame_key=self.last_saved_frame_key,
            show_prediction=self.show_prediction,
            zoom_half_width=self.zoom_half_width,
        )

    def _save_current_frame(self):
        row = save_nozzle_annotation(
            experiment_root=self.experiment_root,
            output_root=self.output_root,
            queue=self.queue,
            annotations_by_key=self.annotations_by_key,
            queue_index=self.current_index,
            seed=self.current_seed,
            marker_x_px=self.marker_x_px,
            marker_y_px=self.marker_y_px,
            annotation_mode=self.annotation_mode,
            session_id=self.session_id,
            show_prediction=self.show_prediction,
            zoom_half_width=self.zoom_half_width,
        )
        self.last_saved_frame_key = row["frame_key"]
        self.dirty = False
        self.status_message = "saved"
        return row

    def _move_index(self, delta: int):
        if not self.queue:
            return
        next_index = int(min(max(0, self.current_index + delta), len(self.queue) - 1))
        if next_index == self.current_index:
            return
        self.current_index = next_index
        self._load_current_frame()
        self._write_session_state()

    def _prediction_point(self):
        frame = self.queue[self.current_index]
        if not self.show_prediction:
            return None
        if frame.get("predicted_x_px") is None or frame.get("predicted_y_px") is None:
            return None
        return float(frame["predicted_x_px"]), float(frame["predicted_y_px"])

    def _render(self):
        from matplotlib import pyplot as plt
        from matplotlib.patches import Rectangle

        frame = self.queue[self.current_index]
        full_ax, zoom_ax = self.axes
        full_ax.clear()
        zoom_ax.clear()

        full_ax.imshow(self.current_image, cmap="gray", vmin=0, vmax=255)
        full_ax.axis("off")
        full_ax.set_title("Full Frame")
        ghost_point = self._prediction_point()
        if ghost_point is not None:
            full_ax.scatter([ghost_point[0]], [ghost_point[1]], c="#43a047", marker="x", s=70, linewidths=2)
        full_ax.scatter([self.marker_x_px], [self.marker_y_px], c="#d81b60", marker="x", s=85, linewidths=2)
        full_ax.add_patch(
            Rectangle(
                (int(frame["search_x0"]), int(frame["search_y0"])),
                int(frame["search_x1"]) - int(frame["search_x0"]),
                int(frame["search_y1"]) - int(frame["search_y0"]),
                fill=False,
                edgecolor="#fbc02d",
                linewidth=1.5,
            )
        )

        zoom_image = self._zoom_crop()
        zoom_ax.imshow(zoom_image, cmap="gray", vmin=0, vmax=255)
        zoom_ax.axis("off")
        zoom_ax.set_title("Zoomed ROI")
        if ghost_point is not None:
            ghost_local_x = ghost_point[0] - self.zoom_origin_x
            ghost_local_y = ghost_point[1] - self.zoom_origin_y
            zoom_ax.scatter([ghost_local_x], [ghost_local_y], c="#43a047", marker="x", s=80, linewidths=2)
        zoom_ax.scatter(
            [self.marker_x_px - self.zoom_origin_x],
            [self.marker_y_px - self.zoom_origin_y],
            c="#d81b60",
            marker="x",
            s=90,
            linewidths=2,
        )

        dirty_text = "unsaved" if self.dirty else "saved"
        self.figure.suptitle(
            (
                f"{frame['run_id']}  frame {frame['capture_index']}  {Path(str(frame['image_relpath'] or '')).name}\n"
                f"point=({int(round(self.marker_x_px))}, {int(round(self.marker_y_px))})  "
                f"mode={self.annotation_mode}  state={dirty_text}  {self.status_message}\n"
                f"modes: {' | '.join(f'{hotkey}={label}' for hotkey, label in MODE_HOTKEY_LABELS)}"
            ),
            fontsize=11,
        )
        self.figure.tight_layout()
        self.figure.canvas.draw_idle()

    def _click_to_image_point(self, event):
        if event.xdata is None or event.ydata is None:
            return None
        if event.inaxes == self.axes[0]:
            return float(event.xdata), float(event.ydata)
        if event.inaxes == self.axes[1]:
            return float(self.zoom_origin_x + event.xdata), float(self.zoom_origin_y + event.ydata)
        return None

    def _on_click(self, event):
        if event.button != 1:
            return
        point = self._click_to_image_point(event)
        if point is None:
            return
        self._set_marker(point[0], point[1])
        self.status_message = "marker moved"
        self._render()

    def _movement_step(self, key: str):
        text = _clean_text(key) or ""
        if "ctrl+" in text:
            return 10
        if "shift+" in text:
            return 5
        return 1

    def _base_key(self, key: str):
        text = (_clean_text(key) or "").lower()
        if "+" in text:
            return text.split("+")[-1]
        return text

    def _on_key(self, event):
        key = self._base_key(event.key)
        step = self._movement_step(event.key or "")

        if key == "left":
            self._move_marker(-step, 0)
        elif key == "right":
            self._move_marker(step, 0)
        elif key == "up":
            self._move_marker(0, -step)
        elif key == "down":
            self._move_marker(0, step)
        elif key in {"enter", "return"}:
            self._save_current_frame()
            if self.current_index < (len(self.queue) - 1):
                self.current_index += 1
                self._load_current_frame()
                self.status_message = "saved and advanced"
            self._write_session_state()
        elif key == "s":
            self._save_current_frame()
            self._write_session_state()
        elif key == "a":
            self._move_index(-1)
        elif key == "d":
            self._move_index(1)
        elif key == "1":
            self.annotation_mode = "attached_black_droplet_center"
            self.dirty = True
            self.status_message = "mode updated"
        elif key == "2":
            self.annotation_mode = "attached_core_separation"
            self.dirty = True
            self.status_message = "mode updated"
        elif key == "3":
            self.annotation_mode = "visible_nozzle_line"
            self.dirty = True
            self.status_message = "mode updated"
        elif key == "4":
            self.annotation_mode = "manual_other"
            self.dirty = True
            self.status_message = "mode updated"
        elif key == "5":
            self.annotation_mode = "only_nozzle"
            self.dirty = True
            self.status_message = "mode updated"
        elif key == "p":
            self.show_prediction = not self.show_prediction
            self.status_message = "prediction shown" if self.show_prediction else "prediction hidden"
            self._write_session_state()
        elif key == "q":
            self._write_session_state()
            from matplotlib import pyplot as plt

            plt.close(self.figure)
            return
        else:
            return

        self._render()

    def run(self):
        if not self.queue:
            raise ValueError("No frames are available for annotation.")

        from matplotlib import pyplot as plt

        self._load_current_frame()
        self.figure, self.axes = plt.subplots(1, 2, figsize=(14, 8))
        try:
            self.figure.canvas.manager.set_window_title("Nozzle Annotation")
        except Exception:
            pass
        self.figure.canvas.mpl_connect("button_press_event", self._on_click)
        self.figure.canvas.mpl_connect("key_press_event", self._on_key)
        self._write_session_state()
        self._render()
        plt.show()
        self._write_session_state()
        return {
            "schema_version": 1,
            "stage": "annotate_nozzle",
            "experiment_root": self.experiment_root,
            "analysis_root": self.analysis_root,
            "annotations_root": str(self.paths["root"]),
            "session_id": self.session_id,
            "selected_run_ids": list(self.queue_payload["selected_run_ids"]),
            "current_frame_key": self.queue[self.current_index]["frame_key"],
            "last_saved_frame_key": self.last_saved_frame_key,
            "show_prediction": bool(self.show_prediction),
            "zoom_half_width": int(self.zoom_half_width),
            "summary": _annotation_progress_summary(self.queue, self.annotations_by_key),
            "outputs": {
                "annotations_csv": str(self.paths["annotations_csv"]),
                "events_jsonl": str(self.paths["events_jsonl"]),
                "manifest_json": str(self.paths["manifest_json"]),
                "state_json": str(self.paths["state_json"]),
            },
        }


def launch_nozzle_annotation_session(
    experiment_root: str | Path,
    *,
    output_root: str | Path | None = None,
    run_ids: list[str] | None = None,
    limit_runs: int | None = None,
    include_unmatched: bool = False,
    resume: bool = False,
    start_run_id: str | None = None,
    start_frame_index: int | None = None,
    zoom_half_width: int = 90,
    show_prediction: bool = True,
):
    queue_payload = build_annotation_queue(
        experiment_root,
        output_root=output_root,
        run_ids=run_ids,
        limit_runs=limit_runs,
        include_unmatched=include_unmatched,
    )
    annotations_by_key = load_nozzle_annotations(experiment_root, output_root=output_root)
    state = load_nozzle_annotation_state(experiment_root, output_root=output_root)
    current_index = resolve_annotation_start_index(
        queue_payload["queue"],
        state=state,
        resume=resume,
        start_run_id=start_run_id,
        start_frame_index=start_frame_index,
    )
    session = NozzleAnnotationSession(
        experiment_root=experiment_root,
        output_root=output_root,
        queue_payload=queue_payload,
        annotations_by_key=annotations_by_key,
        session_id=str(state.get("session_id")) if resume and state.get("session_id") else uuid.uuid4().hex,
        current_index=current_index,
        show_prediction=bool(state.get("show_prediction", show_prediction)) if resume and state else bool(show_prediction),
        zoom_half_width=int(state.get("zoom_half_width", zoom_half_width)) if resume and state else int(zoom_half_width),
    )
    return session.run()
