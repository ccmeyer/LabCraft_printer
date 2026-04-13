from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np

from tools.stream_analysis import online_runtime as runtime_mod
from tools.stream_analysis import silhouette as silhouette_mod
from tools.stream_analysis import volume as volume_mod


GRAY_HEADROOM_VALUES = (20, 30, 40)
DELTA_LAB_CHROMA_MAX_VALUES = (-4.0, -6.0, -8.0, -10.0)
EDGE_BG_GAP_MIN_VALUES = (45, 50, 55, 60)
CONTINUITY_MIN_SUPPORT_VALUES = (2, 3)

WATER_GUARD_MEAN_ATTACHED_DELTA_PCT = 1.0
WATER_GUARD_MAX_ATTACHED_DELTA_PCT = 2.5
WATER_GUARD_MOVED_ROW_SIDE_FRACTION = 0.05

PROFILE_ROW_FRACTIONS = (0.35, 0.75)
PROFILE_MARGIN_PX = 28
CONTACT_SHEET_TILE_HEIGHT = 300
ROW_CONTINUITY_RADIUS = 2
ROW_CONTINUITY_MIN_SUPPORT = 3

SELECTED_V2_RULE = {
    "candidate_id": "gh40_dlc-4_ebg45_sup2",
    "gray_headroom_px": 40,
    "delta_lab_chroma_max": -4.0,
    "edge_bg_gap_min": 45,
    "continuity_min_support": 2,
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_comparison_manifest_path() -> Path:
    return (
        _repo_root()
        / "FreeRTOS-interface"
        / "Experiments"
        / "Stream_BSA_large1-20260411_113020"
        / "analysis"
        / "silhouette_compare_bsa_vs_water"
        / "online_flow_contour_overlays"
        / "comparison_manifest.json"
    )


def _default_output_root(comparison_manifest_path: Path) -> Path:
    return Path(comparison_manifest_path).resolve().parent.parent / "online_flow_chroma_edge_prototype_v2"


def _load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _json_builtin(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _json_builtin(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_builtin(item) for item in value]
    return value


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_builtin(payload), indent=2), encoding="utf-8")
    return path


def _write_csv(path: Path, rows: list[dict], *, fieldnames: list[str] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    row_list = [dict(row) for row in list(rows or [])]
    if fieldnames is None:
        fieldnames = []
        known = set()
        for row in row_list:
            for key in row.keys():
                if key in known:
                    continue
                known.add(key)
                fieldnames.append(str(key))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in row_list:
            writer.writerow({name: _json_builtin(row.get(name)) for name in fieldnames})
    return path


def _int_or_none(value):
    try:
        if value in (None, ""):
            return None
        return int(value)
    except Exception:
        return None


def _ensure_mask(mask: np.ndarray | None, *, shape=None) -> np.ndarray:
    if mask is None:
        if shape is None:
            raise ValueError("shape is required when mask is None")
        return np.zeros(shape, dtype=np.uint8)
    arr = np.asarray(mask)
    if arr.ndim != 2:
        raise ValueError(f"Expected 2D mask, got {arr.shape}")
    return np.where(arr > 0, 255, 0).astype(np.uint8)


def _resize_to_height(image: np.ndarray, target_height: int) -> np.ndarray:
    return silhouette_mod._resize_to_height(image, int(target_height))


def _lab_descriptor_metrics(bgr_pixel: np.ndarray | list[int] | tuple[int, int, int]) -> dict:
    b_value, g_value, r_value = [int(value) for value in np.asarray(bgr_pixel).reshape(3)]
    lab_pixel = cv2.cvtColor(
        np.asarray([[[b_value, g_value, r_value]]], dtype=np.uint8),
        cv2.COLOR_BGR2LAB,
    )[0, 0].astype(float)
    lab_a = float(lab_pixel[1] - 128.0)
    lab_b = float(lab_pixel[2] - 128.0)
    return {
        "b": int(b_value),
        "g": int(g_value),
        "r": int(r_value),
        "bg_gap": float(b_value - g_value),
        "gr_gap": float(g_value - r_value),
        "br_gap": float(b_value - r_value),
        "rb_chroma": float(abs(int(b_value) - int(r_value))),
        "blue_excess": float(int(b_value) - max(int(g_value), int(r_value))),
        "lab_a": float(lab_a),
        "lab_b": float(lab_b),
        "lab_chroma": float(np.hypot(lab_a, lab_b)),
    }


def _candidate_id(*, gray_headroom_px: int, delta_lab_chroma_max: float, edge_bg_gap_min: int, continuity_min_support: int) -> str:
    delta_text = str(int(delta_lab_chroma_max)) if float(delta_lab_chroma_max).is_integer() else str(delta_lab_chroma_max).replace(".", "p")
    return (
        f"gh{int(gray_headroom_px)}"
        f"_dlc{delta_text}"
        f"_ebg{int(edge_bg_gap_min)}"
        f"_sup{int(continuity_min_support)}"
    )


def _candidate_rule_rows() -> list[dict]:
    rows = []
    for gray_headroom_px in GRAY_HEADROOM_VALUES:
        for delta_lab_chroma_max in DELTA_LAB_CHROMA_MAX_VALUES:
            for edge_bg_gap_min in EDGE_BG_GAP_MIN_VALUES:
                for continuity_min_support in CONTINUITY_MIN_SUPPORT_VALUES:
                    rows.append(
                        {
                            "candidate_id": _candidate_id(
                                gray_headroom_px=int(gray_headroom_px),
                                delta_lab_chroma_max=float(delta_lab_chroma_max),
                                edge_bg_gap_min=int(edge_bg_gap_min),
                                continuity_min_support=int(continuity_min_support),
                            ),
                            "gray_headroom_px": int(gray_headroom_px),
                            "delta_lab_chroma_max": float(delta_lab_chroma_max),
                            "edge_bg_gap_min": int(edge_bg_gap_min),
                            "continuity_min_support": int(continuity_min_support),
                        }
                    )
    return rows


def _base_gate_pass(feature_row: dict, rule: dict) -> bool:
    if not bool(feature_row.get("outside_in_bounds")):
        return False
    if not bool(feature_row.get("is_currently_excluded")):
        return False
    if not bool(feature_row.get("contiguous_to_attached_mask")):
        return False
    gray_headroom = feature_row.get("gray_headroom")
    if gray_headroom is None:
        return False
    if not (0.0 < float(gray_headroom) <= float(rule["gray_headroom_px"])):
        return False
    delta_lab_chroma = feature_row.get("delta_lab_chroma")
    edge_bg_gap = feature_row.get("edge_bg_gap")
    if delta_lab_chroma is None or float(delta_lab_chroma) > float(rule["delta_lab_chroma_max"]):
        return False
    if edge_bg_gap is None or float(edge_bg_gap) < float(rule["edge_bg_gap_min"]):
        return False
    return True


def _evaluate_rule_on_row_side_features(feature_rows: list[dict], rule: dict) -> list[dict]:
    ordered = [dict(row) for row in list(feature_rows or [])]
    by_side = {"left": [], "right": []}
    continuity_min_support = int(rule.get("continuity_min_support", ROW_CONTINUITY_MIN_SUPPORT))
    for row in ordered:
        row["base_gate_pass"] = bool(_base_gate_pass(row, rule))
        row["support_count"] = 0
        row["continuity_gate_pass"] = False
        row["move_outward_px"] = 0
        row["moved"] = False
        row["corrected_x_px"] = row.get("current_x_px")
        by_side.setdefault(str(row.get("side") or ""), []).append(row)

    for side_rows in by_side.values():
        side_rows.sort(key=lambda item: (int(item.get("y_px") or 0), int(item.get("current_x_px") or 0)))
        for row in side_rows:
            y_px = int(row["y_px"])
            support_count = sum(
                1
                for neighbor in side_rows
                if abs(int(neighbor["y_px"]) - y_px) <= int(ROW_CONTINUITY_RADIUS)
                and bool(neighbor.get("base_gate_pass"))
            )
            row["support_count"] = int(support_count)
            row["continuity_gate_pass"] = bool(support_count >= int(continuity_min_support))
            row["moved"] = bool(row["base_gate_pass"] and row["continuity_gate_pass"])
            row["move_outward_px"] = 1 if row["moved"] else 0
            current_x_px = int(row["current_x_px"])
            if str(row.get("side")) == "left":
                row["corrected_x_px"] = int(current_x_px - int(row["move_outward_px"]))
            else:
                row["corrected_x_px"] = int(current_x_px + int(row["move_outward_px"]))
    return ordered


def _apply_edge_correction(attached_edge_rows: list[dict], decisions: list[dict], roi: dict) -> list[dict]:
    decision_map = {}
    for row in list(decisions or []):
        decision_map[(int(row["y_px"]), str(row["side"]))] = dict(row)

    corrected = []
    x_min = int(roi["x0"])
    x_max = int(roi["x1"]) - 1
    for row in list(attached_edge_rows or []):
        y_px = int(row["y_px"])
        left = decision_map.get((y_px, "left"))
        right = decision_map.get((y_px, "right"))
        corrected_left = int(row["x_left_px"]) if left is None else int(left["corrected_x_px"])
        corrected_right = int(row["x_right_px"]) if right is None else int(right["corrected_x_px"])
        corrected_left = max(x_min, min(x_max, corrected_left))
        corrected_right = max(x_min, min(x_max, corrected_right))
        if corrected_right < corrected_left:
            corrected_right = corrected_left
        corrected.append(
            {
                **dict(row),
                "x_left_px": int(corrected_left),
                "x_right_px": int(corrected_right),
                "width_px": int(corrected_right - corrected_left + 1),
                "center_x_px": float(corrected_left + corrected_right) / 2.0,
            }
        )
    return corrected


def _edge_rows_to_mask(edge_rows: list[dict], roi: dict) -> np.ndarray:
    mask = np.zeros((int(roi["height"]), int(roi["width"])), dtype=np.uint8)
    for row in list(edge_rows or []):
        local_y = int(row["y_px"]) - int(roi["y0"])
        if local_y < 0 or local_y >= mask.shape[0]:
            continue
        local_x0 = max(0, min(mask.shape[1] - 1, int(row["x_left_px"]) - int(roi["x0"])))
        local_x1 = max(0, min(mask.shape[1] - 1, int(row["x_right_px"]) - int(roi["x0"])))
        if local_x1 < local_x0:
            local_x1 = local_x0
        mask[local_y, local_x0 : local_x1 + 1] = 255
    return mask


def _edge_rows_volume_nl(edge_rows: list[dict]) -> float:
    return float(sum(volume_mod._row_volume_um3(row) for row in list(edge_rows or []))) / float(volume_mod.UM3_PER_NL)


def _frame_analysis_from_capture(
    *,
    image_path: str | Path,
    nozzle_center_px,
    delay_us: int,
    emergence_time_us: int,
    analysis_config: dict | None = None,
    capture_id=None,
    capture_index=None,
    run_key: str = "",
    run_label: str = "",
    run_dir: str | Path | None = None,
) -> dict:
    image_path = Path(str(image_path))
    frame_color = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if frame_color is None:
        raise RuntimeError(f"Unable to load frame image: {image_path}")

    resolved_config = runtime_mod._resolved_analysis_config(analysis_config)
    gray = silhouette_mod._coerce_gray_image(frame_color)
    frame_row = runtime_mod._frame_row(
        delay_us=int(delay_us),
        emergence_time_us=int(emergence_time_us),
        capture_ref={
            "capture_id": capture_id,
            "image_relpath": str(image_path),
        },
        capture_index=capture_index,
    )
    tracked_row = runtime_mod._tracked_row(nozzle_center_px)
    stage3 = silhouette_mod._analyze_stage3_gray(
        "online_stream_runtime",
        frame_row,
        tracked_row,
        gray,
        roi_width_frac=runtime_mod._ROI_WIDTH_FRAC,
        roi_top_frac=runtime_mod._ROI_TOP_FRAC,
        roi_bottom_frac=runtime_mod._ROI_BOTTOM_FRAC,
        corridor_width_frac=runtime_mod._CORRIDOR_WIDTH_FRAC,
        nozzle_guard_px=int(resolved_config["nozzle_guard_px"]),
        min_component_area_px=int(resolved_config["min_component_area_px"]),
    )
    stage4 = volume_mod._analyze_stage4_frame(
        stage3,
        near_bottom_px=int(resolved_config["detached_near_bottom_warning_px"]),
    )

    accepted_components = [dict(component) for component in list(stage3.get("accepted_components") or [])]
    plausible_components = [dict(component) for component in list(stage3.get("plausible_unaccepted_components") or [])]
    attached_component = next(
        (
            dict(component)
            for component in accepted_components
            if str(component.get("component_role") or "") == "attached_primary"
        ),
        None,
    )
    detached_components = [
        dict(component)
        for component in accepted_components
        if str(component.get("component_role") or "") == "detached_accepted"
    ]

    attached_edge_rows = [] if attached_component is None else [dict(row) for row in list(attached_component.get("edge_rows") or [])]
    attached_mask = _ensure_mask(
        None if attached_component is None else attached_component.get("final_mask"),
        shape=stage3["raw_mask"].shape,
    )
    frame_metric_row = dict(stage4.get("frame_metric_row") or {})

    return {
        "run_key": str(run_key),
        "run_label": str(run_label),
        "run_dir": None if run_dir is None else Path(str(run_dir)),
        "image_path": image_path,
        "capture_id": None if capture_id in (None, "") else str(capture_id),
        "capture_index": None if capture_index is None else int(capture_index),
        "delay_us": int(delay_us),
        "delay_from_emergence_us": int(int(delay_us) - int(emergence_time_us)),
        "nozzle_center_px": list(nozzle_center_px),
        "frame_color": frame_color,
        "gray": gray,
        "tracked_row": tracked_row,
        "analysis_config": resolved_config,
        "roi": dict(stage3["roi"]),
        "corridor": dict(stage3["corridor"]),
        "cutoff_y_px": stage3["metric_row"].get("cutoff_y_px"),
        "threshold_value": stage3["metric_row"].get("threshold_value"),
        "stage3_metric_row": dict(stage3["metric_row"]),
        "stage4_frame_metric_row": frame_metric_row,
        "attached_component": attached_component,
        "attached_edge_rows": attached_edge_rows,
        "attached_mask": attached_mask,
        "detached_components": detached_components,
        "plausible_components": plausible_components,
        "detached_visible_volume_nl": float(frame_metric_row.get("detached_visible_volume_nl") or 0.0),
        "current_attached_volume_nl": float(frame_metric_row.get("attached_visible_volume_nl") or 0.0),
        "current_total_visible_volume_nl": float(frame_metric_row.get("total_visible_volume_nl") or 0.0),
        "profile_specs": _profile_specs(attached_edge_rows),
    }


def _profile_specs(attached_edge_rows: list[dict]) -> list[dict]:
    if not attached_edge_rows:
        return []
    row_count = len(attached_edge_rows)
    specs = []
    used_y = set()
    for fraction in PROFILE_ROW_FRACTIONS:
        index = max(0, min(row_count - 1, int(round((row_count - 1) * float(fraction)))))
        row = dict(attached_edge_rows[index])
        y_px = int(row["y_px"])
        if y_px in used_y:
            continue
        used_y.add(y_px)
        specs.append(
            {
                "profile_id": f"p{len(specs) + 1}",
                "row_index": int(index),
                "y_px": y_px,
                "x_left_px": int(row["x_left_px"]),
                "x_right_px": int(row["x_right_px"]),
                "width_px": int(row["width_px"]),
            }
        )
    return specs


def _baseline_frame_analysis(run_key: str, run_info: dict, pair_row: dict) -> dict:
    image_path = Path(str(pair_row["image_path"]))
    emergence_time_us = int(run_info["emergence_time_us"])
    nozzle_center_px = list(run_info["nozzle_center_px"])
    capture_index = int(pair_row["capture_index"])
    delay_us = int(pair_row["delay_us"])

    baseline = _frame_analysis_from_capture(
        image_path=image_path,
        nozzle_center_px=nozzle_center_px,
        delay_us=delay_us,
        emergence_time_us=emergence_time_us,
        analysis_config=None,
        capture_id=pair_row.get("capture_id"),
        capture_index=capture_index,
        run_key=run_key,
        run_label=str(run_info["label"]),
        run_dir=run_info["run_dir"],
    )
    if baseline["attached_component"] is None:
        raise RuntimeError(
            f"Attached component missing for {run_info['label']} {pair_row.get('capture_id')}"
        )

    current_summary = runtime_mod.analyze_online_stream_frame(
        frame_image=baseline["frame_color"],
        background_image=None,
        nozzle_center_px=nozzle_center_px,
        delay_us=delay_us,
        emergence_time_us=emergence_time_us,
        analysis_config=None,
        capture_ref={
            "capture_id": pair_row.get("capture_id"),
            "image_relpath": str(image_path),
        },
        capture_index=capture_index,
    )["summary"]
    baseline["current_summary"] = current_summary
    baseline["delay_from_emergence_us"] = int(pair_row["delay_from_emergence_us"])
    return baseline


def _extract_row_side_features(frame_analysis: dict) -> list[dict]:
    roi = dict(frame_analysis["roi"])
    attached_mask = _ensure_mask(frame_analysis["attached_mask"], shape=(int(roi["height"]), int(roi["width"])))
    frame_color = np.asarray(frame_analysis["frame_color"])
    gray = np.asarray(frame_analysis["gray"])
    threshold_value = frame_analysis.get("threshold_value")
    features = []
    for edge_row in list(frame_analysis.get("attached_edge_rows") or []):
        y_px = int(edge_row["y_px"])
        local_y = y_px - int(roi["y0"])
        if local_y < 0 or local_y >= attached_mask.shape[0]:
            continue
        for side in ("left", "right"):
            current_x_px = int(edge_row["x_left_px"] if side == "left" else edge_row["x_right_px"])
            outside_x_px = int(current_x_px - 1) if side == "left" else int(current_x_px + 1)
            outside_in_bounds = bool(int(roi["x0"]) <= outside_x_px < int(roi["x1"]))
            current_local_x = current_x_px - int(roi["x0"])
            outside_local_x = outside_x_px - int(roi["x0"])
            contiguous_to_mask = False
            is_currently_excluded = False
            edge_metrics = None
            outside_metrics = None
            gray_edge = None
            b_value = None
            g_value = None
            r_value = None
            gray_outside = None
            rb_chroma = None
            blue_excess = None
            if outside_in_bounds and 0 <= current_local_x < attached_mask.shape[1] and 0 <= outside_local_x < attached_mask.shape[1]:
                contiguous_to_mask = bool(attached_mask[local_y, current_local_x] > 0)
                is_currently_excluded = bool(attached_mask[local_y, outside_local_x] == 0)
                edge_metrics = _lab_descriptor_metrics(frame_color[y_px, current_x_px])
                outside_metrics = _lab_descriptor_metrics(frame_color[y_px, outside_x_px])
                b_value = int(outside_metrics["b"])
                g_value = int(outside_metrics["g"])
                r_value = int(outside_metrics["r"])
                gray_edge = int(gray[y_px, current_x_px])
                gray_outside = int(gray[y_px, outside_x_px])
                rb_chroma = float(outside_metrics["rb_chroma"])
                blue_excess = float(outside_metrics["blue_excess"])
            gray_headroom = None
            if gray_outside is not None and threshold_value is not None:
                gray_headroom = float(gray_outside) - float(threshold_value)
            delta_lab_chroma = None
            if edge_metrics is not None and outside_metrics is not None:
                delta_lab_chroma = float(outside_metrics["lab_chroma"]) - float(edge_metrics["lab_chroma"])
            features.append(
                {
                    "run_label": frame_analysis["run_label"],
                    "capture_id": frame_analysis["capture_id"],
                    "capture_index": frame_analysis["capture_index"],
                    "delay_from_emergence_us": frame_analysis["delay_from_emergence_us"],
                    "y_px": int(y_px),
                    "side": str(side),
                    "current_x_px": int(current_x_px),
                    "outside_x_px": int(outside_x_px),
                    "outside_in_bounds": bool(outside_in_bounds),
                    "contiguous_to_attached_mask": bool(contiguous_to_mask),
                    "is_currently_excluded": bool(is_currently_excluded),
                    "gray_edge": gray_edge,
                    "gray_outside": gray_outside,
                    "gray_headroom": gray_headroom,
                    "b_edge": None if edge_metrics is None else int(edge_metrics["b"]),
                    "g_edge": None if edge_metrics is None else int(edge_metrics["g"]),
                    "r_edge": None if edge_metrics is None else int(edge_metrics["r"]),
                    "b_outside": b_value,
                    "g_outside": g_value,
                    "r_outside": r_value,
                    "rb_chroma": rb_chroma,
                    "blue_excess": blue_excess,
                    "edge_bg_gap": None if edge_metrics is None else float(edge_metrics["bg_gap"]),
                    "out_bg_gap": None if outside_metrics is None else float(outside_metrics["bg_gap"]),
                    "edge_gr_gap": None if edge_metrics is None else float(edge_metrics["gr_gap"]),
                    "out_gr_gap": None if outside_metrics is None else float(outside_metrics["gr_gap"]),
                    "edge_br_gap": None if edge_metrics is None else float(edge_metrics["br_gap"]),
                    "out_br_gap": None if outside_metrics is None else float(outside_metrics["br_gap"]),
                    "edge_lab_a": None if edge_metrics is None else float(edge_metrics["lab_a"]),
                    "edge_lab_b": None if edge_metrics is None else float(edge_metrics["lab_b"]),
                    "edge_lab_chroma": None if edge_metrics is None else float(edge_metrics["lab_chroma"]),
                    "out_lab_a": None if outside_metrics is None else float(outside_metrics["lab_a"]),
                    "out_lab_b": None if outside_metrics is None else float(outside_metrics["lab_b"]),
                    "out_lab_chroma": None if outside_metrics is None else float(outside_metrics["lab_chroma"]),
                    "delta_lab_chroma": delta_lab_chroma,
                }
            )
    return features


def _evaluate_candidate_on_frame(frame_analysis: dict, rule: dict) -> dict:
    decisions = _evaluate_rule_on_row_side_features(frame_analysis["row_side_features"], rule)
    corrected_edge_rows = _apply_edge_correction(
        frame_analysis["attached_edge_rows"],
        decisions,
        frame_analysis["roi"],
    )
    corrected_mask = _edge_rows_to_mask(corrected_edge_rows, frame_analysis["roi"])
    corrected_attached_volume_nl = _edge_rows_volume_nl(corrected_edge_rows)
    corrected_total_volume_nl = float(corrected_attached_volume_nl + float(frame_analysis["detached_visible_volume_nl"]))

    moved_row_sides = [row for row in decisions if bool(row.get("moved"))]
    moved_rows = sorted({int(row["y_px"]) for row in moved_row_sides})
    attached_row_count = max(1, int(len(frame_analysis["attached_edge_rows"])))
    attached_row_side_count = max(1, int(attached_row_count * 2))
    current_attached_volume_nl = float(frame_analysis["current_attached_volume_nl"])
    current_total_visible_volume_nl = float(frame_analysis["current_total_visible_volume_nl"])

    attached_delta_nl = float(corrected_attached_volume_nl - current_attached_volume_nl)
    total_delta_nl = float(corrected_total_volume_nl - current_total_visible_volume_nl)
    attached_delta_pct = (
        None
        if current_attached_volume_nl == 0.0
        else float((attached_delta_nl / current_attached_volume_nl) * 100.0)
    )
    total_delta_pct = (
        None
        if current_total_visible_volume_nl == 0.0
        else float((total_delta_nl / current_total_visible_volume_nl) * 100.0)
    )

    return {
        "rule": dict(rule),
        "decisions": decisions,
        "corrected_edge_rows": corrected_edge_rows,
        "corrected_mask": corrected_mask,
        "current_attached_volume_nl": current_attached_volume_nl,
        "corrected_attached_volume_nl": float(corrected_attached_volume_nl),
        "current_total_visible_volume_nl": current_total_visible_volume_nl,
        "corrected_total_visible_volume_nl": float(corrected_total_volume_nl),
        "attached_delta_nl": float(attached_delta_nl),
        "attached_delta_pct": attached_delta_pct,
        "total_delta_nl": float(total_delta_nl),
        "total_delta_pct": total_delta_pct,
        "moved_row_side_count": int(len(moved_row_sides)),
        "moved_row_count": int(len(moved_rows)),
        "moved_rows": moved_rows,
        "moved_row_fraction": float(len(moved_rows)) / float(attached_row_count),
        "moved_row_side_fraction": float(len(moved_row_sides)) / float(attached_row_side_count),
    }


def apply_selected_v2_correction_to_frame_row(
    frame_row: dict,
    *,
    image_path: str | Path,
    nozzle_center_px,
    emergence_time_us: int,
    analysis_config: dict | None = None,
    rule: dict | None = None,
) -> dict:
    record = dict(frame_row or {})
    delay_us = _int_or_none(record.get("delay_us"))
    if delay_us is None:
        delay_us = _int_or_none(record.get("flash_delay_us"))
    if delay_us is None:
        raise ValueError("Frame row is missing delay_us/flash_delay_us required for correction replay.")

    image_ref = dict(record.get("image_ref") or {})
    capture_index = _int_or_none(record.get("capture_index"))
    if capture_index is None:
        capture_index = _int_or_none(image_ref.get("capture_index"))
    capture_id = record.get("capture_id")
    if capture_id in (None, ""):
        capture_id = image_ref.get("capture_id")

    frame_analysis = _frame_analysis_from_capture(
        image_path=image_path,
        nozzle_center_px=nozzle_center_px,
        delay_us=int(delay_us),
        emergence_time_us=int(emergence_time_us),
        analysis_config=analysis_config,
        capture_id=capture_id,
        capture_index=capture_index,
        run_key=str(record.get("run_id") or ""),
        run_label=str(record.get("phase") or ""),
    )
    frame_analysis["row_side_features"] = _extract_row_side_features(frame_analysis)
    applied_rule = dict(rule or SELECTED_V2_RULE)
    frame_result = _evaluate_candidate_on_frame(frame_analysis, applied_rule)
    corrected_width_metrics = runtime_mod._band_width_metrics(
        frame_analysis["stage3_metric_row"],
        frame_result["corrected_edge_rows"],
        near_nozzle_band_top_px=int(frame_analysis["analysis_config"]["near_nozzle_band_top_px"]),
        near_nozzle_band_height_px=int(frame_analysis["analysis_config"]["near_nozzle_band_height_px"]),
        min_band_valid_rows=int(frame_analysis["analysis_config"]["min_band_valid_rows"]),
    )

    corrected_row = dict(record)
    corrected_row["delay_us"] = int(delay_us)
    corrected_row["delay_from_emergence_us"] = int(frame_analysis["delay_from_emergence_us"])
    corrected_row["attached_width_px"] = corrected_width_metrics.get("attached_width_px")
    corrected_row["width_valid_row_count"] = corrected_width_metrics.get("width_valid_row_count")
    corrected_row["visible_volume_nl"] = float(frame_result["corrected_total_visible_volume_nl"])
    corrected_row["attached_visible_volume_nl"] = float(frame_result["corrected_attached_volume_nl"])
    corrected_row["detached_visible_volume_nl"] = float(frame_analysis["detached_visible_volume_nl"])
    corrected_row["total_visible_volume_nl"] = float(frame_result["corrected_total_visible_volume_nl"])
    corrected_row["correction_rule_candidate_id"] = str(applied_rule["candidate_id"])
    corrected_row["correction_attached_delta_nl"] = float(frame_result["attached_delta_nl"])
    corrected_row["correction_attached_delta_pct"] = frame_result.get("attached_delta_pct")
    corrected_row["correction_total_delta_nl"] = float(frame_result["total_delta_nl"])
    corrected_row["correction_total_delta_pct"] = frame_result.get("total_delta_pct")
    corrected_row["correction_moved_row_count"] = int(frame_result["moved_row_count"])
    corrected_row["correction_moved_row_side_count"] = int(frame_result["moved_row_side_count"])

    if corrected_row.get("attached_bottom_clearance_px") in (None, ""):
        roi_y1 = frame_analysis["stage3_metric_row"].get("roi_y1")
        attached_component = dict(frame_analysis.get("attached_component") or {})
        last_valid_y_px = attached_component.get("last_valid_y_px")
        if roi_y1 is not None and last_valid_y_px is not None:
            corrected_row["attached_bottom_clearance_px"] = int(int(roi_y1) - 1 - int(last_valid_y_px))
    if corrected_row.get("min_accepted_fluid_distance_from_bottom_px") in (None, ""):
        corrected_row["min_accepted_fluid_distance_from_bottom_px"] = frame_analysis["stage4_frame_metric_row"].get(
            "min_accepted_fluid_distance_from_bottom_px"
        )
    if corrected_row.get("plausible_unaccepted_visible_volume_nl") in (None, ""):
        corrected_row["plausible_unaccepted_visible_volume_nl"] = frame_analysis["stage4_frame_metric_row"].get(
            "plausible_unaccepted_visible_volume_nl"
        )
    if corrected_row.get("plausible_unaccepted_component_count") in (None, ""):
        corrected_row["plausible_unaccepted_component_count"] = frame_analysis["stage3_metric_row"].get(
            "plausible_unaccepted_component_count"
        )

    return {
        "rule": applied_rule,
        "frame_analysis": frame_analysis,
        "frame_result": frame_result,
        "corrected_width_metrics": corrected_width_metrics,
        "corrected_frame_row": corrected_row,
    }


def _mean_or_zero(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(float(value) for value in values) / float(len(values)))


def _max_or_zero(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(max(float(value) for value in values))


def _summarize_candidate_results(candidate: dict, per_frame_results: list[dict], frame_analyses: list[dict]) -> dict:
    by_run = {"BSA": [], "Water": []}
    for frame_analysis, frame_result in zip(frame_analyses, per_frame_results):
        by_run.setdefault(str(frame_analysis["run_label"]), []).append((frame_analysis, frame_result))

    def _condition_stats(label: str) -> dict:
        pairs = list(by_run.get(label, []))
        if not pairs:
            return {
                "frame_count": 0,
                "moved_row_side_count": 0,
                "moved_row_count": 0,
                "moved_row_fraction": 0.0,
                "moved_row_side_fraction": 0.0,
                "mean_attached_delta_pct": 0.0,
                "max_attached_delta_pct": 0.0,
            }
        total_rows = sum(len(frame_analysis["attached_edge_rows"]) for frame_analysis, _frame_result in pairs)
        total_row_sides = max(1, int(total_rows * 2))
        moved_row_side_count = sum(frame_result["moved_row_side_count"] for _frame_analysis, frame_result in pairs)
        moved_row_count = sum(frame_result["moved_row_count"] for _frame_analysis, frame_result in pairs)
        attached_delta_pcts = [
            float(frame_result["attached_delta_pct"])
            for _frame_analysis, frame_result in pairs
            if frame_result.get("attached_delta_pct") is not None
        ]
        return {
            "frame_count": int(len(pairs)),
            "moved_row_side_count": int(moved_row_side_count),
            "moved_row_count": int(moved_row_count),
            "moved_row_fraction": 0.0 if total_rows <= 0 else float(moved_row_count) / float(total_rows),
            "moved_row_side_fraction": 0.0 if total_row_sides <= 0 else float(moved_row_side_count) / float(total_row_sides),
            "mean_attached_delta_pct": _mean_or_zero(attached_delta_pcts),
            "max_attached_delta_pct": _max_or_zero(attached_delta_pcts),
        }

    bsa = _condition_stats("BSA")
    water = _condition_stats("Water")
    passes_water_guard = bool(
        float(water["mean_attached_delta_pct"]) <= float(WATER_GUARD_MEAN_ATTACHED_DELTA_PCT)
        and float(water["max_attached_delta_pct"]) <= float(WATER_GUARD_MAX_ATTACHED_DELTA_PCT)
        and float(water["moved_row_side_fraction"]) <= float(WATER_GUARD_MOVED_ROW_SIDE_FRACTION)
    )
    return {
        **dict(candidate),
        "bsa_frame_count": int(bsa["frame_count"]),
        "bsa_moved_row_side_count": int(bsa["moved_row_side_count"]),
        "bsa_moved_row_count": int(bsa["moved_row_count"]),
        "bsa_moved_row_fraction": float(bsa["moved_row_fraction"]),
        "bsa_moved_row_side_fraction": float(bsa["moved_row_side_fraction"]),
        "bsa_mean_attached_delta_pct": float(bsa["mean_attached_delta_pct"]),
        "bsa_max_attached_delta_pct": float(bsa["max_attached_delta_pct"]),
        "water_frame_count": int(water["frame_count"]),
        "water_moved_row_side_count": int(water["moved_row_side_count"]),
        "water_moved_row_count": int(water["moved_row_count"]),
        "water_moved_row_fraction": float(water["moved_row_fraction"]),
        "water_moved_row_side_fraction": float(water["moved_row_side_fraction"]),
        "water_mean_attached_delta_pct": float(water["mean_attached_delta_pct"]),
        "water_max_attached_delta_pct": float(water["max_attached_delta_pct"]),
        "total_moved_row_side_count": int(bsa["moved_row_side_count"] + water["moved_row_side_count"]),
        "passes_water_guard": bool(passes_water_guard),
    }


def _select_rule(parameter_summaries: list[dict]) -> dict:
    summaries = [dict(row) for row in list(parameter_summaries or [])]
    guard_passing = [row for row in summaries if bool(row.get("passes_water_guard"))]
    selected_rule = None
    if guard_passing:
        selected_rule = sorted(
            guard_passing,
            key=lambda row: (
                -float(row["bsa_mean_attached_delta_pct"]),
                float(row["water_mean_attached_delta_pct"]),
                int(row["total_moved_row_side_count"]),
            ),
        )[0]
    fallback_rule = None
    if summaries:
        fallback_rule = sorted(
            summaries,
            key=lambda row: (
                float(row["water_max_attached_delta_pct"]),
                -float(row["bsa_mean_attached_delta_pct"]),
                int(row["total_moved_row_side_count"]),
            ),
        )[0]
    rendered_rule = selected_rule if selected_rule is not None else fallback_rule
    rendered_rule_kind = "selected_guard_passing" if selected_rule is not None else "fallback_exploratory"
    return {
        "selected_rule": None if selected_rule is None else dict(selected_rule),
        "fallback_rule": None if fallback_rule is None else dict(fallback_rule),
        "rendered_rule": None if rendered_rule is None else dict(rendered_rule),
        "rendered_rule_kind": str(rendered_rule_kind),
        "water_guard": {
            "mean_attached_delta_pct_max": float(WATER_GUARD_MEAN_ATTACHED_DELTA_PCT),
            "max_attached_delta_pct_max": float(WATER_GUARD_MAX_ATTACHED_DELTA_PCT),
            "moved_row_side_fraction_max": float(WATER_GUARD_MOVED_ROW_SIDE_FRACTION),
        },
    }


def _get_pyplot():
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    return plt


def _profile_csv_rows(frame_analysis: dict, frame_result: dict, profile_spec: dict) -> list[dict]:
    frame_color = np.asarray(frame_analysis["frame_color"])
    gray = np.asarray(frame_analysis["gray"])
    y_px = int(profile_spec["y_px"])
    corrected_row = next(
        (
            row
            for row in list(frame_result["corrected_edge_rows"] or [])
            if int(row["y_px"]) == y_px
        ),
        None,
    )
    corrected_left_px = int(profile_spec["x_left_px"]) if corrected_row is None else int(corrected_row["x_left_px"])
    corrected_right_px = int(profile_spec["x_right_px"]) if corrected_row is None else int(corrected_row["x_right_px"])
    x_min = min(int(profile_spec["x_left_px"]), int(profile_spec["x_right_px"]), int(corrected_left_px), int(corrected_right_px))
    x_max = max(int(profile_spec["x_left_px"]), int(profile_spec["x_right_px"]), int(corrected_left_px), int(corrected_right_px))
    x0 = max(0, x_min - int(PROFILE_MARGIN_PX))
    x1 = min(frame_color.shape[1] - 1, x_max + int(PROFILE_MARGIN_PX))
    rows = []
    for x_px in range(x0, x1 + 1):
        metrics = _lab_descriptor_metrics(frame_color[y_px, x_px])
        b_value = int(metrics["b"])
        g_value = int(metrics["g"])
        r_value = int(metrics["r"])
        gray_value = int(gray[y_px, x_px])
        rows.append(
            {
                "profile_id": profile_spec["profile_id"],
                "y_px": int(y_px),
                "x_px": int(x_px),
                "b": int(b_value),
                "g": int(g_value),
                "r": int(r_value),
                "gray": int(gray_value),
                "rb_chroma_abs": int(abs(int(b_value) - int(r_value))),
                "blue_excess": int(int(b_value) - max(int(g_value), int(r_value))),
                "bg_gap": float(metrics["bg_gap"]),
                "gr_gap": float(metrics["gr_gap"]),
                "br_gap": float(metrics["br_gap"]),
                "lab_a": float(metrics["lab_a"]),
                "lab_b": float(metrics["lab_b"]),
                "lab_chroma": float(metrics["lab_chroma"]),
                "current_left_marker": bool(int(x_px) == int(profile_spec["x_left_px"])),
                "current_right_marker": bool(int(x_px) == int(profile_spec["x_right_px"])),
                "corrected_left_marker": bool(int(x_px) == int(corrected_left_px)),
                "corrected_right_marker": bool(int(x_px) == int(corrected_right_px)),
            }
        )
    return rows


def _save_profile_plot(frame_analysis: dict, frame_result: dict, profile_spec: dict, frame_dir: Path) -> dict:
    plt = _get_pyplot()
    rows = _profile_csv_rows(frame_analysis, frame_result, profile_spec)
    csv_path = frame_dir / f"{profile_spec['profile_id']}_edge_profile.csv"
    png_path = frame_dir / f"{profile_spec['profile_id']}_edge_profile_before_after.png"
    _write_csv(csv_path, rows)

    y_px = int(profile_spec["y_px"])
    xs = np.asarray([int(row["x_px"]) for row in rows], dtype=int)
    b_vals = np.asarray([int(row["b"]) for row in rows], dtype=float)
    g_vals = np.asarray([int(row["g"]) for row in rows], dtype=float)
    r_vals = np.asarray([int(row["r"]) for row in rows], dtype=float)
    gray_vals = np.asarray([int(row["gray"]) for row in rows], dtype=float)
    current_left_px = int(profile_spec["x_left_px"])
    current_right_px = int(profile_spec["x_right_px"])
    corrected_left_px = next((int(row["x_px"]) for row in rows if row["corrected_left_marker"]), current_left_px)
    corrected_right_px = next((int(row["x_px"]) for row in rows if row["corrected_right_marker"]), current_right_px)

    frame_color = np.asarray(frame_analysis["frame_color"])
    crop_y0 = max(0, y_px - 8)
    crop_y1 = min(frame_color.shape[0], y_px + 9)
    crop = cv2.cvtColor(frame_color[crop_y0:crop_y1, int(xs[0]) : int(xs[-1]) + 1], cv2.COLOR_BGR2RGB)

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(8.0, 4.4), dpi=140)
    ax0.imshow(crop, aspect="auto")
    ax0.axhline(y=float(y_px - crop_y0), color="yellow", linewidth=1.0, label="sampled row")
    ax0.axvline(x=float(current_left_px - int(xs[0])), color="lime", linestyle="--", linewidth=1.0, label="current edge")
    ax0.axvline(x=float(current_right_px - int(xs[0])), color="lime", linestyle="--", linewidth=1.0)
    ax0.axvline(x=float(corrected_left_px - int(xs[0])), color="cyan", linestyle=":", linewidth=1.2, label="corrected edge")
    ax0.axvline(x=float(corrected_right_px - int(xs[0])), color="cyan", linestyle=":", linewidth=1.2)
    ax0.set_title(
        f"{frame_analysis['run_label']} {frame_analysis['capture_id']} {profile_spec['profile_id']} y={y_px}px"
    )
    ax0.set_axis_off()
    ax0.legend(loc="upper right", fontsize=8)

    ax1.plot(xs, b_vals, color="#1f77b4", label="B")
    ax1.plot(xs, g_vals, color="#2ca02c", label="G")
    ax1.plot(xs, r_vals, color="#d62728", label="R")
    ax1.plot(xs, gray_vals, color="#111111", label="Gray", linewidth=1.2)
    ax1.axvline(x=float(current_left_px), color="lime", linestyle="--", linewidth=1.0)
    ax1.axvline(x=float(current_right_px), color="lime", linestyle="--", linewidth=1.0)
    ax1.axvline(x=float(corrected_left_px), color="cyan", linestyle=":", linewidth=1.2)
    ax1.axvline(x=float(corrected_right_px), color="cyan", linestyle=":", linewidth=1.2)
    ax1.set_xlim(int(xs[0]), int(xs[-1]))
    ax1.set_ylim(0, 255)
    ax1.set_xlabel("x (px)")
    ax1.set_ylabel("intensity")
    ax1.grid(alpha=0.25)
    ax1.legend(loc="upper right", ncol=4, fontsize=8)
    fig.tight_layout()
    fig.savefig(png_path, bbox_inches="tight")
    plt.close(fig)
    return {
        "profile_id": str(profile_spec["profile_id"]),
        "y_px": int(profile_spec["y_px"]),
        "current_x_left_px": int(current_left_px),
        "current_x_right_px": int(current_right_px),
        "corrected_x_left_px": int(corrected_left_px),
        "corrected_x_right_px": int(corrected_right_px),
        "csv_path": str(csv_path),
        "plot_path": str(png_path),
    }


def _draw_component_overlay(
    roi_color: np.ndarray,
    *,
    roi: dict,
    tracked_row: dict,
    cutoff_y_px,
    attached_mask: np.ndarray,
    attached_edge_rows: list[dict],
    attached_color: tuple[int, int, int],
    detached_components: list[dict],
    sample_specs: list[dict] | None = None,
    moved_rows: list[int] | None = None,
    label: str,
) -> np.ndarray:
    overlay = roi_color.copy()
    mask = _ensure_mask(attached_mask, shape=roi_color.shape[:2])
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        cv2.drawContours(overlay, contours, -1, attached_color, 2)
    for row in list(attached_edge_rows or []):
        y_local = int(row["y_px"]) - int(roi["y0"])
        xl = int(row["x_left_px"]) - int(roi["x0"])
        xr = int(row["x_right_px"]) - int(roi["x0"])
        if 0 <= y_local < overlay.shape[0]:
            if 0 <= xl < overlay.shape[1]:
                overlay[y_local, xl] = attached_color
            if 0 <= xr < overlay.shape[1]:
                overlay[y_local, xr] = attached_color
    for component in list(detached_components or []):
        detached_mask = _ensure_mask(component.get("final_mask"), shape=roi_color.shape[:2])
        detached_contours, _hierarchy = cv2.findContours(detached_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if detached_contours:
            cv2.drawContours(overlay, detached_contours, -1, (0, 191, 255), 2)
    for spec in list(sample_specs or []):
        y_local = int(spec["y_px"]) - int(roi["y0"])
        if 0 <= y_local < overlay.shape[0]:
            cv2.line(overlay, (0, y_local), (overlay.shape[1] - 1, y_local), (255, 255, 0), 1)
    for y_px in list(moved_rows or []):
        y_local = int(y_px) - int(roi["y0"])
        if 0 <= y_local < overlay.shape[0]:
            cv2.line(overlay, (0, y_local), (overlay.shape[1] - 1, y_local), (0, 255, 255), 1)
    overlay = silhouette_mod._draw_nozzle_context(
        overlay,
        nozzle_x_px=None if tracked_row.get("tracked_nozzle_x_px") is None else float(tracked_row["tracked_nozzle_x_px"]) - float(roi["x0"]),
        nozzle_y_px=None if tracked_row.get("tracked_nozzle_y_px") is None else float(tracked_row["tracked_nozzle_y_px"]) - float(roi["y0"]),
        cutoff_y_px=None if cutoff_y_px is None else int(cutoff_y_px) - int(roi["y0"]),
        x0_px=0,
        x1_px=max(0, overlay.shape[1] - 1),
    )
    return silhouette_mod._draw_label(overlay, label)


def _render_before_after_panel(frame_analysis: dict, frame_result: dict, *, rendered_rule_kind: str) -> np.ndarray:
    roi = dict(frame_analysis["roi"])
    roi_color = frame_analysis["frame_color"][int(roi["y0"]) : int(roi["y1"]), int(roi["x0"]) : int(roi["x1"])].copy()
    raw_panel = roi_color.copy()
    for spec in list(frame_analysis["profile_specs"]):
        y_local = int(spec["y_px"]) - int(roi["y0"])
        if 0 <= y_local < raw_panel.shape[0]:
            cv2.line(raw_panel, (0, y_local), (raw_panel.shape[1] - 1, y_local), (255, 255, 0), 1)
            cv2.putText(raw_panel, str(spec["profile_id"]).upper(), (10, max(18, y_local - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2, cv2.LINE_AA)
    raw_panel = silhouette_mod._draw_nozzle_context(
        raw_panel,
        nozzle_x_px=None if frame_analysis["tracked_row"].get("tracked_nozzle_x_px") is None else float(frame_analysis["tracked_row"]["tracked_nozzle_x_px"]) - float(roi["x0"]),
        nozzle_y_px=None if frame_analysis["tracked_row"].get("tracked_nozzle_y_px") is None else float(frame_analysis["tracked_row"]["tracked_nozzle_y_px"]) - float(roi["y0"]),
        cutoff_y_px=None if frame_analysis.get("cutoff_y_px") is None else int(frame_analysis["cutoff_y_px"]) - int(roi["y0"]),
        x0_px=0,
        x1_px=max(0, raw_panel.shape[1] - 1),
    )
    raw_panel = silhouette_mod._draw_label(raw_panel, "raw ROI + sampled rows")

    current_panel = _draw_component_overlay(
        roi_color,
        roi=roi,
        tracked_row=frame_analysis["tracked_row"],
        cutoff_y_px=frame_analysis.get("cutoff_y_px"),
        attached_mask=frame_analysis["attached_mask"],
        attached_edge_rows=frame_analysis["attached_edge_rows"],
        attached_color=(0, 255, 0),
        detached_components=frame_analysis["detached_components"],
        sample_specs=frame_analysis["profile_specs"],
        label="current contour",
    )
    corrected_panel = _draw_component_overlay(
        roi_color,
        roi=roi,
        tracked_row=frame_analysis["tracked_row"],
        cutoff_y_px=frame_analysis.get("cutoff_y_px"),
        attached_mask=frame_result["corrected_mask"],
        attached_edge_rows=frame_result["corrected_edge_rows"],
        attached_color=(255, 255, 0),
        detached_components=frame_analysis["detached_components"],
        sample_specs=frame_analysis["profile_specs"],
        label="corrected contour",
    )
    combined_panel = _draw_component_overlay(
        roi_color,
        roi=roi,
        tracked_row=frame_analysis["tracked_row"],
        cutoff_y_px=frame_analysis.get("cutoff_y_px"),
        attached_mask=frame_result["corrected_mask"],
        attached_edge_rows=frame_result["corrected_edge_rows"],
        attached_color=(255, 255, 0),
        detached_components=frame_analysis["detached_components"],
        sample_specs=frame_analysis["profile_specs"],
        moved_rows=frame_result["moved_rows"],
        label="current vs corrected + moved rows",
    )
    current_contours, _hierarchy = cv2.findContours(_ensure_mask(frame_analysis["attached_mask"]), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if current_contours:
        cv2.drawContours(combined_panel, current_contours, -1, (0, 255, 0), 1)

    top_row = cv2.hconcat([_resize_to_height(raw_panel, CONTACT_SHEET_TILE_HEIGHT), _resize_to_height(current_panel, CONTACT_SHEET_TILE_HEIGHT)])
    bottom_row = cv2.hconcat([_resize_to_height(corrected_panel, CONTACT_SHEET_TILE_HEIGHT), _resize_to_height(combined_panel, CONTACT_SHEET_TILE_HEIGHT)])
    panel = cv2.vconcat([top_row, bottom_row])
    header = np.zeros((44, panel.shape[1], 3), dtype=np.uint8)
    rule = dict(frame_result["rule"])
    header_text = (
        f"{frame_analysis['run_label']} {frame_analysis['capture_id']}  "
        f"delay={frame_analysis['delay_from_emergence_us']} us  "
        f"rule={rule['candidate_id']} ({rendered_rule_kind})  "
        f"attached {frame_result['current_attached_volume_nl']:.3f}->{frame_result['corrected_attached_volume_nl']:.3f} nL"
    )
    cv2.putText(header, header_text, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 2, cv2.LINE_AA)
    return cv2.vconcat([header, panel])


def _contact_sheet(images: list[np.ndarray], *, columns: int, title: str) -> np.ndarray:
    if not images:
        return np.zeros((10, 10, 3), dtype=np.uint8)
    rows = []
    current = []
    for image in images:
        current.append(_resize_to_height(image, CONTACT_SHEET_TILE_HEIGHT))
        if len(current) == int(columns):
            rows.append(current)
            current = []
    if current:
        filler = np.zeros_like(current[0])
        while len(current) < int(columns):
            current.append(filler.copy())
        rows.append(current)
    rendered_rows = [cv2.hconcat(row) for row in rows]
    max_width = max(image.shape[1] for image in rendered_rows)
    padded_rows = []
    for image in rendered_rows:
        if image.shape[1] == max_width:
            padded_rows.append(image)
            continue
        canvas = np.zeros((image.shape[0], max_width, image.shape[2]), dtype=image.dtype)
        canvas[:, : image.shape[1], :] = image
        padded_rows.append(canvas)
    sheet = cv2.vconcat(padded_rows)
    header = np.zeros((44, sheet.shape[1], 3), dtype=np.uint8)
    cv2.putText(header, title, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.82, (255, 255, 255), 2, cv2.LINE_AA)
    return cv2.vconcat([header, sheet])


def _load_frame_analyses(comparison_manifest_path: Path) -> tuple[dict, list[dict]]:
    manifest = _load_json(comparison_manifest_path)
    runs = {
        "bsa": {
            "label": str(manifest["bsa"]["label"]),
            "run_dir": Path(str(manifest["bsa"]["run_dir"])),
            "nozzle_center_px": list(manifest["bsa"]["nozzle_center_px"]),
            "emergence_time_us": int(manifest["bsa"]["emergence_time_us"]),
        },
        "water": {
            "label": str(manifest["water"]["label"]),
            "run_dir": Path(str(manifest["water"]["run_dir"])),
            "nozzle_center_px": list(manifest["water"]["nozzle_center_px"]),
            "emergence_time_us": int(manifest["water"]["emergence_time_us"]),
        },
    }

    frame_analyses = []
    for pair in list(manifest.get("pairs") or []):
        for run_key in ("bsa", "water"):
            analysis = _baseline_frame_analysis(run_key, runs[run_key], dict(pair[run_key]))
            analysis["target_delay_from_emergence_us"] = int(pair["target_delay_from_emergence_us"])
            analysis["row_side_features"] = _extract_row_side_features(analysis)
            frame_analyses.append(analysis)
    return manifest, frame_analyses


def _sweep_parameter_space(frame_analyses: list[dict]) -> list[dict]:
    summaries = []
    for candidate in _candidate_rule_rows():
        per_frame_results = [
            _evaluate_candidate_on_frame(frame_analysis, candidate)
            for frame_analysis in frame_analyses
        ]
        summaries.append(_summarize_candidate_results(candidate, per_frame_results, frame_analyses))
    return summaries


def export_online_chroma_edge_prototype(
    comparison_manifest: str | Path | None = None,
    *,
    output_root: str | Path | None = None,
) -> dict:
    comparison_manifest_path = (
        _default_comparison_manifest_path()
        if comparison_manifest in (None, "")
        else Path(str(comparison_manifest)).resolve()
    )
    resolved_output_root = (
        _default_output_root(comparison_manifest_path)
        if output_root in (None, "")
        else Path(str(output_root)).resolve()
    )
    resolved_output_root.mkdir(parents=True, exist_ok=True)

    manifest, frame_analyses = _load_frame_analyses(comparison_manifest_path)
    parameter_summaries = _sweep_parameter_space(frame_analyses)
    selection = _select_rule(parameter_summaries)
    rendered_rule = selection.get("rendered_rule")
    if rendered_rule is None:
        raise RuntimeError("No prototype rule candidates were produced.")

    parameter_csv_path = _write_csv(
        resolved_output_root / "parameter_sweep_summary.csv",
        parameter_summaries,
    )
    rule_selection_json_path = _write_json(
        resolved_output_root / "rule_selection_summary.json",
        selection,
    )

    rendered_results = [
        _evaluate_candidate_on_frame(frame_analysis, rendered_rule)
        for frame_analysis in frame_analyses
    ]

    per_frame_entries = {"BSA": [], "Water": []}
    for frame_analysis, frame_result in zip(frame_analyses, rendered_results):
        run_dir = resolved_output_root / str(frame_analysis["run_label"]).lower() / str(frame_analysis["capture_id"])
        run_dir.mkdir(parents=True, exist_ok=True)

        decision_rows = [dict(row) for row in list(frame_result["decisions"] or [])]
        for row in decision_rows:
            if str(row.get("side")) == "left":
                row["corrected_x_left_px"] = row.get("corrected_x_px")
                row["corrected_x_right_px"] = None
            else:
                row["corrected_x_left_px"] = None
                row["corrected_x_right_px"] = row.get("corrected_x_px")

        before_after_panel_path = run_dir / "before_after_panel.png"
        current_edges_path = run_dir / "current_edge_rows.csv"
        corrected_edges_path = run_dir / "corrected_edge_rows.csv"
        row_decisions_path = run_dir / "row_side_decisions.csv"
        volume_comparison_path = run_dir / "volume_comparison.json"

        before_after_panel = _render_before_after_panel(
            frame_analysis,
            frame_result,
            rendered_rule_kind=str(selection["rendered_rule_kind"]),
        )
        cv2.imwrite(str(before_after_panel_path), before_after_panel)
        _write_csv(current_edges_path, frame_analysis["attached_edge_rows"])
        _write_csv(corrected_edges_path, frame_result["corrected_edge_rows"])
        _write_csv(row_decisions_path, decision_rows)

        profile_outputs = [
            _save_profile_plot(frame_analysis, frame_result, profile_spec, run_dir)
            for profile_spec in list(frame_analysis["profile_specs"] or [])
        ]

        volume_comparison = {
            "run_label": frame_analysis["run_label"],
            "capture_id": frame_analysis["capture_id"],
            "delay_from_emergence_us": frame_analysis["delay_from_emergence_us"],
            "rendered_rule_kind": selection["rendered_rule_kind"],
            "rule": rendered_rule,
            "current_attached_volume_nl": frame_result["current_attached_volume_nl"],
            "corrected_attached_volume_nl": frame_result["corrected_attached_volume_nl"],
            "current_total_visible_volume_nl": frame_result["current_total_visible_volume_nl"],
            "corrected_total_visible_volume_nl": frame_result["corrected_total_visible_volume_nl"],
            "attached_delta_nl": frame_result["attached_delta_nl"],
            "attached_delta_pct": frame_result["attached_delta_pct"],
            "total_delta_nl": frame_result["total_delta_nl"],
            "total_delta_pct": frame_result["total_delta_pct"],
            "moved_row_count": frame_result["moved_row_count"],
            "moved_row_side_count": frame_result["moved_row_side_count"],
            "moved_row_fraction": frame_result["moved_row_fraction"],
            "moved_row_side_fraction": frame_result["moved_row_side_fraction"],
            "current_optical_metrics": {
                "attached_width_px": frame_analysis["current_summary"].get("attached_width_px"),
                "lower_edge_jitter_px": frame_analysis["current_summary"].get("lower_edge_jitter_px"),
                "boundary_chroma_aberration_score": frame_analysis["current_summary"].get("boundary_chroma_aberration_score"),
                "flow_optical_confidence": frame_analysis["current_summary"].get("flow_optical_confidence"),
            },
            "paths": {
                "before_after_panel_png": str(before_after_panel_path),
                "current_edge_rows_csv": str(current_edges_path),
                "corrected_edge_rows_csv": str(corrected_edges_path),
                "row_side_decisions_csv": str(row_decisions_path),
            },
            "profiles": profile_outputs,
        }
        _write_json(volume_comparison_path, volume_comparison)

        entry = {
            "run_label": frame_analysis["run_label"],
            "capture_id": frame_analysis["capture_id"],
            "capture_index": frame_analysis["capture_index"],
            "delay_from_emergence_us": frame_analysis["delay_from_emergence_us"],
            "target_delay_from_emergence_us": frame_analysis["target_delay_from_emergence_us"],
            "rendered_rule_kind": selection["rendered_rule_kind"],
            "rule_candidate_id": rendered_rule["candidate_id"],
            "current_attached_volume_nl": frame_result["current_attached_volume_nl"],
            "corrected_attached_volume_nl": frame_result["corrected_attached_volume_nl"],
            "current_total_visible_volume_nl": frame_result["current_total_visible_volume_nl"],
            "corrected_total_visible_volume_nl": frame_result["corrected_total_visible_volume_nl"],
            "attached_delta_pct": frame_result["attached_delta_pct"],
            "total_delta_pct": frame_result["total_delta_pct"],
            "moved_row_count": frame_result["moved_row_count"],
            "moved_row_side_count": frame_result["moved_row_side_count"],
            "before_after_panel_png": str(before_after_panel_path),
            "volume_comparison_json": str(volume_comparison_path),
            "row_side_decisions_csv": str(row_decisions_path),
            "profile_outputs": profile_outputs,
        }
        per_frame_entries[str(frame_analysis["run_label"])].append({**entry, "_panel": before_after_panel})

    bsa_sheet = _contact_sheet(
        [entry["_panel"] for entry in per_frame_entries["BSA"]],
        columns=2,
        title="BSA chroma-gated 1 px edge prototype v2",
    )
    water_sheet = _contact_sheet(
        [entry["_panel"] for entry in per_frame_entries["Water"]],
        columns=2,
        title="Water chroma-gated 1 px edge prototype v2",
    )
    pair_panels = []
    water_by_delay = {
        int(entry["target_delay_from_emergence_us"]): entry
        for entry in per_frame_entries["Water"]
    }
    for bsa_entry in per_frame_entries["BSA"]:
        target_delay = int(bsa_entry["target_delay_from_emergence_us"])
        water_entry = water_by_delay.get(target_delay)
        if water_entry is None:
            continue
        pair_panels.append(
            cv2.hconcat(
                [
                    _resize_to_height(bsa_entry["_panel"], CONTACT_SHEET_TILE_HEIGHT),
                    _resize_to_height(water_entry["_panel"], CONTACT_SHEET_TILE_HEIGHT),
                ]
            )
        )
    matched_pair_sheet = _contact_sheet(
        pair_panels,
        columns=1,
        title="Matched BSA vs water chroma-gated 1 px edge prototype v2",
    )

    bsa_sheet_path = resolved_output_root / "bsa_before_after_contact_sheet.png"
    water_sheet_path = resolved_output_root / "water_before_after_contact_sheet.png"
    pair_sheet_path = resolved_output_root / "matched_pair_before_after_contact_sheet.png"
    cv2.imwrite(str(bsa_sheet_path), bsa_sheet)
    cv2.imwrite(str(water_sheet_path), water_sheet)
    cv2.imwrite(str(pair_sheet_path), matched_pair_sheet)

    manifest_entries = {
        label.lower(): [
            {key: value for key, value in entry.items() if key != "_panel"}
            for entry in per_frame_entries[label]
        ]
        for label in ("BSA", "Water")
    }
    prototype_manifest = {
        "analysis": "online_flow_chroma_edge_prototype_v2",
        "descriptor_family": "delta_lab_chroma_plus_edge_bg_gap",
        "comparison_manifest": str(comparison_manifest_path),
        "output_root": str(resolved_output_root),
        "rendered_rule_kind": selection["rendered_rule_kind"],
        "selected_rule": selection.get("selected_rule"),
        "fallback_rule": selection.get("fallback_rule"),
        "rendered_rule": selection.get("rendered_rule"),
        "paths": {
            "parameter_sweep_summary_csv": str(parameter_csv_path),
            "rule_selection_summary_json": str(rule_selection_json_path),
            "bsa_before_after_contact_sheet_png": str(bsa_sheet_path),
            "water_before_after_contact_sheet_png": str(water_sheet_path),
            "matched_pair_before_after_contact_sheet_png": str(pair_sheet_path),
        },
        "frames": manifest_entries,
    }
    prototype_manifest_path = _write_json(
        resolved_output_root / "prototype_manifest.json",
        prototype_manifest,
    )
    return {
        **prototype_manifest,
        "prototype_manifest_json": str(prototype_manifest_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline chroma-gated 1 px edge correction prototype v2 for online stream captures."
    )
    parser.add_argument(
        "--comparison-manifest",
        default=str(_default_comparison_manifest_path()),
        help="Paired comparison manifest JSON used to select BSA/water frames.",
    )
    parser.add_argument(
        "--output-root",
        default="",
        help="Optional output directory. Defaults to a sibling online_flow_chroma_edge_prototype directory.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    payload = export_online_chroma_edge_prototype(
        comparison_manifest=args.comparison_manifest,
        output_root=args.output_root,
    )
    print(json.dumps({"output_root": payload["output_root"], "prototype_manifest_json": payload["prototype_manifest_json"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
