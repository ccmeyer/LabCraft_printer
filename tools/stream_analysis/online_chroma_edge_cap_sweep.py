from __future__ import annotations

import argparse
import csv
import json
import time
from collections import defaultdict
from pathlib import Path

from tools.stream_analysis import dataset as dataset_mod
from tools.stream_analysis import online_chroma_edge_offset_cache as cache_mod
from tools.stream_analysis import online_chroma_edge_prototype as proto_mod
from tools.stream_analysis import online_report as report_mod
from tools.stream_analysis import online_runtime as runtime_mod


ANALYSIS_NAME = "online_chroma_edge_cap_sweep"
CORRECTION_MODE = "chroma_edge_cap_sweep"
STAGE_DIRNAME = "online_chroma_edge_cap_sweep"
ROW_CONTINUITY_RADIUS = 2

CAP_SUMMARY_COLUMNS = [
    "cap_px",
    "run_count",
    "condition_count",
    "predicted_volume_nl_mean",
    "gravimetric_per_print_nl_mean",
    "signed_residual_nl_mean",
    "predicted_to_gravimetric_ratio_mean",
    "report_output_root",
    "report_manifest_json",
]
RUN_CAP_SUMMARY_COLUMNS = ["cap_px"] + list(report_mod.RUN_SUMMARY_COLUMNS)
CONDITION_CAP_SUMMARY_COLUMNS = ["cap_px"] + list(report_mod.CONDITION_SUMMARY_COLUMNS)


def _load_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _clean_text(value):
    return report_mod._clean_text(value)


def _float_or_none(value):
    return report_mod._float_or_none(value)


def _int_or_none(value):
    return report_mod._int_or_none(value)


def _bool_or_none(value):
    if isinstance(value, bool):
        return value
    text = _clean_text(value)
    if text is None:
        return None
    lowered = str(text).strip().lower()
    if lowered in {"1", "true", "t", "yes", "y"}:
        return True
    if lowered in {"0", "false", "f", "no", "n"}:
        return False
    return None


def _load_csv_rows(path: str | Path) -> list[dict]:
    rows = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(dict(row))
    return rows


def _split_run_ids(values) -> list[str]:
    selected = []
    for value in list(values or []):
        text = _clean_text(value)
        if text is None:
            continue
        for part in str(text).split(","):
            run_id = _clean_text(part)
            if run_id is not None:
                selected.append(str(run_id))
    return selected


def _default_output_root(cache_manifest_path: Path) -> Path:
    return cache_manifest_path.parent / STAGE_DIRNAME


def _resolved_caps(cache_manifest: dict, caps_arg: str | None) -> list[int]:
    max_offset_px = int(cache_manifest.get("max_offset_px") or 0)
    if caps_arg in (None, ""):
        return list(range(0, int(max_offset_px) + 1))
    caps = []
    for part in str(caps_arg).split(","):
        cap_px = _int_or_none(part)
        if cap_px is None:
            raise ValueError(f"Unable to parse cap value: {part!r}")
        if int(cap_px) < 0 or int(cap_px) > int(max_offset_px):
            raise ValueError(
                f"Requested cap {cap_px} is outside cached range 0..{max_offset_px}."
            )
        caps.append(int(cap_px))
    unique_caps = sorted({int(value) for value in caps})
    if not unique_caps:
        raise ValueError("At least one cap must be requested.")
    return unique_caps


def _resolved_rule(
    cache_manifest: dict,
    *,
    gray_headroom_px=None,
    delta_lab_chroma_max=None,
    edge_bg_gap_min=None,
    continuity_min_support=None,
) -> dict:
    base_rule = dict(cache_manifest.get("selected_rule_reference") or {})
    if not base_rule:
        raise ValueError("Cache manifest is missing selected_rule_reference.")
    rule = {
        "gray_headroom_px": int(
            base_rule["gray_headroom_px"] if gray_headroom_px is None else gray_headroom_px
        ),
        "delta_lab_chroma_max": float(
            base_rule["delta_lab_chroma_max"] if delta_lab_chroma_max is None else delta_lab_chroma_max
        ),
        "edge_bg_gap_min": int(
            base_rule["edge_bg_gap_min"] if edge_bg_gap_min is None else edge_bg_gap_min
        ),
        "continuity_min_support": int(
            base_rule["continuity_min_support"] if continuity_min_support is None else continuity_min_support
        ),
    }
    rule["candidate_id"] = proto_mod._candidate_id(
        gray_headroom_px=int(rule["gray_headroom_px"]),
        delta_lab_chroma_max=float(rule["delta_lab_chroma_max"]),
        edge_bg_gap_min=int(rule["edge_bg_gap_min"]),
        continuity_min_support=int(rule["continuity_min_support"]),
    )
    return rule


def _frame_key(*, run_id, capture_id, capture_index, delay_us):
    return (
        str(run_id or ""),
        str(capture_id or ""),
        -1 if capture_index is None else int(capture_index),
        -1 if delay_us is None else int(delay_us),
    )


def _frame_key_from_row(run_id: str, row: dict) -> tuple[str, str, int, int]:
    image_ref = dict(row.get("image_ref") or {})
    capture_id = _clean_text(row.get("capture_id")) or _clean_text(image_ref.get("capture_id")) or ""
    capture_index = _int_or_none(row.get("capture_index"))
    if capture_index is None:
        capture_index = _int_or_none(image_ref.get("capture_index"))
    delay_us = _int_or_none(row.get("delay_us"))
    if delay_us is None:
        delay_us = _int_or_none(row.get("flash_delay_us"))
    return _frame_key(
        run_id=run_id,
        capture_id=capture_id,
        capture_index=capture_index,
        delay_us=delay_us,
    )


def _frame_key_from_cached_row(run_id: str, row: dict) -> tuple[str, str, int, int]:
    return _frame_key(
        run_id=run_id,
        capture_id=_clean_text(row.get("capture_id")) or "",
        capture_index=_int_or_none(row.get("capture_index")),
        delay_us=_int_or_none(row.get("delay_us")),
    )


def _group_metadata_rows_by_run_id(experiment_root: Path) -> dict[str, dict]:
    rows = {}
    for row in report_mod._metadata_rows(experiment_root):
        process_name = _clean_text(row.get("Capture Process")) or report_mod.PROCESS_NAME
        if process_name != report_mod.PROCESS_NAME:
            continue
        run_id = _clean_text(row.get("Dataset name"))
        if run_id is None:
            continue
        rows[str(run_id)] = dict(row)
    return rows


def _parse_frame_summary_row(run_id: str, row: dict) -> dict:
    parsed = {
        "run_id": str(run_id),
        "capture_id": _clean_text(row.get("capture_id")) or "",
        "capture_index": _int_or_none(row.get("capture_index")),
        "delay_us": _int_or_none(row.get("delay_us")),
        "delay_from_emergence_us": _int_or_none(row.get("delay_from_emergence_us")),
        "threshold_value": _float_or_none(row.get("threshold_value")),
        "attached_edge_row_count": _int_or_none(row.get("attached_edge_row_count")) or 0,
        "feature_row_count": _int_or_none(row.get("feature_row_count")) or 0,
        "current_attached_volume_nl": float(_float_or_none(row.get("current_attached_volume_nl")) or 0.0),
        "current_total_visible_volume_nl": float(_float_or_none(row.get("current_total_visible_volume_nl")) or 0.0),
        "detached_visible_volume_nl": float(_float_or_none(row.get("detached_visible_volume_nl")) or 0.0),
        "roi": {
            "x0": int(_int_or_none(row.get("roi_x0")) or 0),
            "y0": int(_int_or_none(row.get("roi_y0")) or 0),
            "x1": int(_int_or_none(row.get("roi_x1")) or 0),
            "y1": int(_int_or_none(row.get("roi_y1")) or 0),
        },
    }
    parsed["roi"]["width"] = int(parsed["roi"]["x1"] - parsed["roi"]["x0"])
    parsed["roi"]["height"] = int(parsed["roi"]["y1"] - parsed["roi"]["y0"])
    return parsed


def _parse_baseline_edge_row(row: dict) -> dict:
    return {
        "y_px": int(_int_or_none(row.get("y_px")) or 0),
        "x_left_px": int(_int_or_none(row.get("x_left_px")) or 0),
        "x_right_px": int(_int_or_none(row.get("x_right_px")) or 0),
        "width_px": int(_int_or_none(row.get("width_px")) or 0),
        "center_x_px": float(_float_or_none(row.get("center_x_px")) or 0.0),
    }


def _parse_offset_feature_row(row: dict) -> dict:
    return {
        "y_px": int(_int_or_none(row.get("y_px")) or 0),
        "side": str(row.get("side") or ""),
        "current_x_px": int(_int_or_none(row.get("current_x_px")) or 0),
        "sample_offset_px": int(_int_or_none(row.get("sample_offset_px")) or 0),
        "sample_in_bounds": bool(_bool_or_none(row.get("sample_in_bounds"))),
        "contiguous_to_attached_mask": bool(_bool_or_none(row.get("contiguous_to_attached_mask"))),
        "sample_is_excluded": bool(_bool_or_none(row.get("sample_is_excluded"))),
        "intermediate_pixels_all_excluded": bool(_bool_or_none(row.get("intermediate_pixels_all_excluded"))),
        "gray_headroom": _float_or_none(row.get("gray_headroom")),
        "delta_lab_chroma": _float_or_none(row.get("delta_lab_chroma")),
        "edge_bg_gap": _float_or_none(row.get("edge_bg_gap")),
    }


def _base_gate_pass(feature_row: dict, rule: dict) -> bool:
    if not bool(feature_row.get("sample_in_bounds")):
        return False
    if not bool(feature_row.get("sample_is_excluded")):
        return False
    if not bool(feature_row.get("contiguous_to_attached_mask")):
        return False
    if not bool(feature_row.get("intermediate_pixels_all_excluded")):
        return False
    gray_headroom = feature_row.get("gray_headroom")
    if gray_headroom is None:
        return False
    if not (0.0 < float(gray_headroom) <= float(rule["gray_headroom_px"])):
        return False
    delta_lab_chroma = feature_row.get("delta_lab_chroma")
    if delta_lab_chroma is None or float(delta_lab_chroma) > float(rule["delta_lab_chroma_max"]):
        return False
    edge_bg_gap = feature_row.get("edge_bg_gap")
    if edge_bg_gap is None or float(edge_bg_gap) < float(rule["edge_bg_gap_min"]):
        return False
    return True


def _eligible_offsets_by_row_side(feature_rows: list[dict], rule: dict) -> dict[tuple[int, str, int], bool]:
    eligible = {}
    by_offset_side = defaultdict(list)
    for row in list(feature_rows or []):
        key = (int(row["sample_offset_px"]), str(row["side"]))
        by_offset_side[key].append(
            {
                **dict(row),
                "base_gate_pass": bool(_base_gate_pass(row, rule)),
            }
        )

    continuity_min_support = int(rule.get("continuity_min_support", 0))
    for (_offset_px, _side), rows in by_offset_side.items():
        rows.sort(key=lambda item: int(item["y_px"]))
        y_values = [int(item["y_px"]) for item in rows]
        base_flags = [1 if bool(item.get("base_gate_pass")) else 0 for item in rows]
        left = 0
        right = 0
        support_count = 0
        for row in rows:
            y_px = int(row["y_px"])
            while left < len(rows) and int(y_values[left]) < int(y_px - ROW_CONTINUITY_RADIUS):
                support_count -= int(base_flags[left])
                left += 1
            while right < len(rows) and int(y_values[right]) <= int(y_px + ROW_CONTINUITY_RADIUS):
                support_count += int(base_flags[right])
                right += 1
            eligible[(int(row["y_px"]), str(row["side"]), int(row["sample_offset_px"]))] = bool(
                bool(row.get("base_gate_pass")) and int(support_count) >= int(continuity_min_support)
            )
    return eligible


def _max_contiguous_move_map(
    baseline_edge_rows: list[dict],
    feature_rows: list[dict],
    *,
    max_offset_px: int,
    rule: dict,
) -> dict[tuple[int, str], int]:
    eligible_offsets = _eligible_offsets_by_row_side(feature_rows, rule)
    move_map = {}
    for row in list(baseline_edge_rows or []):
        y_px = int(row["y_px"])
        for side in ("left", "right"):
            max_contiguous = 0
            for offset_px in range(1, int(max_offset_px) + 1):
                if not bool(eligible_offsets.get((y_px, side, int(offset_px)))):
                    break
                max_contiguous = int(offset_px)
            move_map[(y_px, side)] = int(max_contiguous)
    return move_map


def _corrected_edge_rows_for_cap(
    baseline_edge_rows: list[dict],
    *,
    move_map: dict[tuple[int, str], int],
    cap_px: int,
    roi: dict,
) -> tuple[list[dict], int, int, int]:
    corrected_rows = []
    moved_row_count = 0
    moved_row_side_count = 0
    max_applied_move_px = 0
    x_min = int(roi["x0"])
    x_max = int(roi["x1"]) - 1
    for row in list(baseline_edge_rows or []):
        y_px = int(row["y_px"])
        left_move_px = min(int(cap_px), int(move_map.get((y_px, "left"), 0)))
        right_move_px = min(int(cap_px), int(move_map.get((y_px, "right"), 0)))
        moved_row_side_count += (1 if left_move_px > 0 else 0) + (1 if right_move_px > 0 else 0)
        if left_move_px > 0 or right_move_px > 0:
            moved_row_count += 1
        max_applied_move_px = max(max_applied_move_px, int(left_move_px), int(right_move_px))
        corrected_left = max(int(x_min), min(int(x_max), int(row["x_left_px"]) - int(left_move_px)))
        corrected_right = max(int(x_min), min(int(x_max), int(row["x_right_px"]) + int(right_move_px)))
        if corrected_right < corrected_left:
            corrected_right = corrected_left
        corrected_rows.append(
            {
                **dict(row),
                "x_left_px": int(corrected_left),
                "x_right_px": int(corrected_right),
                "width_px": int(corrected_right - corrected_left + 1),
                "center_x_px": float(corrected_left + corrected_right) / 2.0,
            }
        )
    return corrected_rows, int(moved_row_count), int(moved_row_side_count), int(max_applied_move_px)


def _corrected_frame_row_from_cache(
    archived_row: dict,
    frame_summary: dict,
    baseline_edge_rows: list[dict],
    *,
    move_map: dict[tuple[int, str], int],
    cap_px: int,
    rule: dict,
    nozzle_center_px,
    analysis_config: dict | None = None,
) -> dict:
    resolved_config = runtime_mod._resolved_analysis_config(analysis_config)
    roi = dict(frame_summary["roi"])
    corrected_edge_rows, moved_row_count, moved_row_side_count, max_applied_move_px = _corrected_edge_rows_for_cap(
        baseline_edge_rows,
        move_map=move_map,
        cap_px=cap_px,
        roi=roi,
    )
    corrected_attached_volume_nl = proto_mod._edge_rows_volume_nl(corrected_edge_rows)
    detached_visible_volume_nl = float(frame_summary.get("detached_visible_volume_nl") or 0.0)
    corrected_total_visible_volume_nl = float(corrected_attached_volume_nl + detached_visible_volume_nl)
    current_attached_volume_nl = float(frame_summary.get("current_attached_volume_nl") or 0.0)
    current_total_visible_volume_nl = float(frame_summary.get("current_total_visible_volume_nl") or 0.0)
    attached_delta_nl = float(corrected_attached_volume_nl - current_attached_volume_nl)
    total_delta_nl = float(corrected_total_visible_volume_nl - current_total_visible_volume_nl)
    attached_delta_pct = None
    if current_attached_volume_nl != 0.0:
        attached_delta_pct = float((attached_delta_nl / current_attached_volume_nl) * 100.0)
    total_delta_pct = None
    if current_total_visible_volume_nl != 0.0:
        total_delta_pct = float((total_delta_nl / current_total_visible_volume_nl) * 100.0)

    width_metrics = runtime_mod._band_width_metrics(
        {"tracked_nozzle_y_px": float(nozzle_center_px[1])},
        corrected_edge_rows,
        near_nozzle_band_top_px=int(resolved_config["near_nozzle_band_top_px"]),
        near_nozzle_band_height_px=int(resolved_config["near_nozzle_band_height_px"]),
        min_band_valid_rows=int(resolved_config["min_band_valid_rows"]),
    )

    corrected_row = dict(archived_row or {})
    corrected_row["delay_us"] = int(frame_summary.get("delay_us") or corrected_row.get("delay_us") or 0)
    corrected_row["delay_from_emergence_us"] = int(
        frame_summary.get("delay_from_emergence_us")
        or corrected_row.get("delay_from_emergence_us")
        or 0
    )
    corrected_row["attached_width_px"] = width_metrics.get("attached_width_px")
    corrected_row["width_valid_row_count"] = width_metrics.get("width_valid_row_count")
    corrected_row["visible_volume_nl"] = float(corrected_total_visible_volume_nl)
    corrected_row["attached_visible_volume_nl"] = float(corrected_attached_volume_nl)
    corrected_row["detached_visible_volume_nl"] = float(detached_visible_volume_nl)
    corrected_row["total_visible_volume_nl"] = float(corrected_total_visible_volume_nl)
    corrected_row["correction_rule_candidate_id"] = str(rule["candidate_id"])
    corrected_row["correction_cap_px"] = int(cap_px)
    corrected_row["correction_mode"] = CORRECTION_MODE
    corrected_row["correction_attached_delta_nl"] = float(attached_delta_nl)
    corrected_row["correction_attached_delta_pct"] = attached_delta_pct
    corrected_row["correction_total_delta_nl"] = float(total_delta_nl)
    corrected_row["correction_total_delta_pct"] = total_delta_pct
    corrected_row["correction_moved_row_count"] = int(moved_row_count)
    corrected_row["correction_moved_row_side_count"] = int(moved_row_side_count)
    corrected_row["correction_max_row_side_move_px"] = int(max_applied_move_px)
    return corrected_row


def _load_cached_run_data(run_entry: dict) -> dict:
    run_manifest_path = Path(run_entry["run_manifest_json"]).expanduser().resolve()
    run_manifest = _load_json(run_manifest_path)
    run_id = str(run_manifest["run_id"])
    run_dir = Path(run_manifest["run_dir"]).expanduser().resolve()
    frame_summary_rows = _load_csv_rows(run_manifest["paths"]["frame_summary_csv"])
    baseline_edge_rows = _load_csv_rows(run_manifest["paths"]["baseline_edge_rows_csv"])
    offset_feature_rows = _load_csv_rows(run_manifest["paths"]["row_side_offset_features_csv"])
    archived_frame_rows = report_mod._iter_jsonl(run_dir / "frames.jsonl")
    plan_snapshot = report_mod._load_json(run_dir / "plan_snapshot.json")
    flow_fit_artifact = report_mod._load_json(run_dir / "flow_fit.json")
    tail_fit_artifact = report_mod._load_json(run_dir / "tail_fit.json")

    frame_summary_by_key = {}
    for row in frame_summary_rows:
        parsed = _parse_frame_summary_row(run_id, row)
        frame_summary_by_key[_frame_key_from_cached_row(run_id, parsed)] = parsed

    edge_rows_by_key = defaultdict(list)
    for row in baseline_edge_rows:
        key = _frame_key_from_cached_row(run_id, row)
        edge_rows_by_key[key].append(_parse_baseline_edge_row(row))
    for rows in edge_rows_by_key.values():
        rows.sort(key=lambda item: int(item["y_px"]))

    feature_rows_by_key = defaultdict(list)
    for row in offset_feature_rows:
        key = _frame_key_from_cached_row(run_id, row)
        feature_rows_by_key[key].append(_parse_offset_feature_row(row))

    archived_rows_in_order = []
    for row in archived_frame_rows:
        archived = dict(row or {})
        archived_rows_in_order.append((_frame_key_from_row(run_id, archived), archived))

    return {
        "run_id": run_id,
        "run_dir": run_dir,
        "run_manifest": run_manifest,
        "plan_snapshot": plan_snapshot,
        "flow_fit_artifact": flow_fit_artifact,
        "tail_fit_artifact": tail_fit_artifact,
        "frame_summary_by_key": frame_summary_by_key,
        "edge_rows_by_key": edge_rows_by_key,
        "feature_rows_by_key": feature_rows_by_key,
        "archived_rows_in_order": archived_rows_in_order,
        "max_offset_px": int(run_manifest.get("max_offset_px") or 0),
    }


def _run_context_for_cap(
    run_cache: dict,
    *,
    metadata_row: dict,
    rule: dict,
    cap_px: int,
    density_g_per_ml: float | int,
) -> dict:
    correction_context = dict(run_cache["run_manifest"].get("correction_context") or {})
    move_map_by_frame = {}
    max_offset_px = int(run_cache["max_offset_px"])
    for frame_key, feature_rows in run_cache["feature_rows_by_key"].items():
        baseline_edge_rows = list(run_cache["edge_rows_by_key"].get(frame_key) or [])
        move_map_by_frame[frame_key] = _max_contiguous_move_map(
            baseline_edge_rows,
            feature_rows,
            max_offset_px=max_offset_px,
            rule=rule,
        )

    corrected_frame_rows = []
    for frame_key, archived_row in run_cache["archived_rows_in_order"]:
        frame_summary = run_cache["frame_summary_by_key"].get(frame_key)
        if frame_summary is None:
            corrected_frame_rows.append(dict(archived_row))
            continue
        baseline_edge_rows = list(run_cache["edge_rows_by_key"].get(frame_key) or [])
        corrected_frame_rows.append(
            _corrected_frame_row_from_cache(
                archived_row,
                frame_summary,
                baseline_edge_rows,
                move_map=move_map_by_frame.get(frame_key, {}),
                cap_px=cap_px,
                rule=rule,
                nozzle_center_px=list(correction_context.get("nozzle_center_px") or [0, 0]),
                analysis_config=(run_cache["plan_snapshot"].get("analysis_config") or None),
            )
        )

    replay = report_mod._replay_online_stream_run_from_frame_rows(
        run_cache["run_dir"],
        plan_snapshot=run_cache["plan_snapshot"],
        flow_fit_artifact=run_cache["flow_fit_artifact"],
        tail_fit_artifact=run_cache["tail_fit_artifact"],
        frame_rows=corrected_frame_rows,
        correction_context=correction_context,
    )
    context = report_mod._context_from_replay(
        metadata_row=metadata_row,
        run_dir=run_cache["run_dir"],
        frame_rows=list(replay.get("frame_rows") or []),
        fit=dict(replay.get("fit") or {}),
        tail_result=dict(replay.get("tail_result") or {}),
        density_g_per_ml=density_g_per_ml,
        correction_mode=CORRECTION_MODE,
        correction_context=correction_context,
        flow_artifact=run_cache["flow_fit_artifact"],
        tail_artifact=run_cache["tail_fit_artifact"],
    )
    context["cap_px"] = int(cap_px)
    context["correction_rule"] = dict(rule)
    return context


def _mean_or_none(values) -> float | None:
    numeric = [float(value) for value in list(values or []) if _float_or_none(value) is not None]
    if not numeric:
        return None
    return float(sum(numeric) / float(len(numeric)))


def _cap_summary_row(cap_px: int, summary_rows: list[dict], condition_rows: list[dict], *, report_payload: dict | None = None) -> dict:
    return {
        "cap_px": int(cap_px),
        "run_count": int(len(summary_rows)),
        "condition_count": int(len(condition_rows)),
        "predicted_volume_nl_mean": _mean_or_none(
            row.get("predicted_volume_nl") for row in summary_rows
        ),
        "gravimetric_per_print_nl_mean": _mean_or_none(
            row.get("gravimetric_per_print_nl") for row in summary_rows
        ),
        "signed_residual_nl_mean": _mean_or_none(
            row.get("signed_residual_nl") for row in summary_rows
        ),
        "predicted_to_gravimetric_ratio_mean": _mean_or_none(
            row.get("predicted_to_gravimetric_ratio") for row in summary_rows
        ),
        "report_output_root": None if report_payload is None else str(report_payload.get("output_root")),
        "report_manifest_json": None if report_payload is None else str(report_payload["paths"]["report_manifest_json"]),
    }


def _plot_predicted_vs_gravimetric_by_cap(run_cap_rows: list[dict], output_path: Path):
    plt = report_mod._import_pyplot()
    fig, ax = plt.subplots(figsize=(7.5, 6.5))
    caps = sorted({int(_int_or_none(row.get("cap_px")) or 0) for row in list(run_cap_rows or [])})
    colors = plt.cm.viridis([index / max(1, len(caps) - 1) for index in range(len(caps))])
    numeric_pairs = []
    for color, cap_px in zip(colors, caps):
        x_values = []
        y_values = []
        for row in list(run_cap_rows or []):
            if int(_int_or_none(row.get("cap_px")) or 0) != int(cap_px):
                continue
            predicted = _float_or_none(row.get("predicted_volume_nl"))
            gravimetric = _float_or_none(row.get("gravimetric_per_print_nl"))
            if predicted is None or gravimetric is None:
                continue
            x_values.append(float(predicted))
            y_values.append(float(gravimetric))
            numeric_pairs.append((float(predicted), float(gravimetric)))
        if x_values and y_values:
            ax.scatter(x_values, y_values, s=32, alpha=0.85, color=color, label=f"cap {cap_px}px")
    if numeric_pairs:
        x_max = max(value[0] for value in numeric_pairs)
        y_max = max(value[1] for value in numeric_pairs)
        diagonal_max = max(float(x_max), float(y_max)) * 1.05
        ax.plot([0.0, diagonal_max], [0.0, diagonal_max], color="black", linestyle="--", linewidth=1.2, alpha=0.7)
        ax.set_xlim(0.0, diagonal_max)
        ax.set_ylim(0.0, diagonal_max)
    ax.set_xlabel("Predicted volume (nL)")
    ax.set_ylabel("Gravimetric volume (nL)")
    ax.set_title("Predicted vs gravimetric volume by cap", fontsize=11)
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def _plot_metric_vs_cap_by_condition(
    rows: list[dict],
    *,
    metric_key: str,
    ylabel: str,
    title: str,
    output_path: Path,
):
    plt = report_mod._import_pyplot()
    fig, ax = plt.subplots(figsize=(9, 5.5))
    grouped = defaultdict(list)
    for row in list(rows or []):
        grouped[str(row.get("condition_key") or "unknown")].append(dict(row))
    for condition_key, condition_rows in sorted(grouped.items()):
        ordered = sorted(condition_rows, key=lambda item: int(_int_or_none(item.get("cap_px")) or 0))
        x_values = []
        y_values = []
        for row in ordered:
            metric_value = _float_or_none(row.get(metric_key))
            if metric_value is None:
                continue
            x_values.append(int(_int_or_none(row.get("cap_px")) or 0))
            y_values.append(float(metric_value))
        if x_values and y_values:
            ax.plot(x_values, y_values, marker="o", linewidth=1.8, label=condition_key)
    ax.set_xlabel("Cap (px)")
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=11)
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def export_online_chroma_edge_cap_sweep(
    cache_manifest_path: str | Path,
    *,
    caps: str | None = None,
    density_g_per_ml: float | int,
    run_ids=None,
    output_root: str | Path | None = None,
    summary_only: bool = False,
    gray_headroom_px=None,
    delta_lab_chroma_max=None,
    edge_bg_gap_min=None,
    continuity_min_support=None,
) -> dict:
    cache_manifest_path = Path(cache_manifest_path).expanduser().resolve()
    cache_manifest = _load_json(cache_manifest_path)
    if str(cache_manifest.get("analysis") or "") != cache_mod.STAGE_DIRNAME_PREFIX:
        raise ValueError(f"Unexpected cache manifest analysis type: {cache_manifest.get('analysis')!r}")
    experiment_root = dataset_mod.resolve_experiment_root(cache_manifest["experiment_root"])
    density_g_per_ml = report_mod._validate_density_g_per_ml(density_g_per_ml)
    cap_values = _resolved_caps(cache_manifest, caps)
    rule = _resolved_rule(
        cache_manifest,
        gray_headroom_px=gray_headroom_px,
        delta_lab_chroma_max=delta_lab_chroma_max,
        edge_bg_gap_min=edge_bg_gap_min,
        continuity_min_support=continuity_min_support,
    )

    selected_run_ids = set(_split_run_ids(run_ids))
    available_run_entries = [dict(item) for item in list(cache_manifest.get("runs") or [])]
    if selected_run_ids:
        available_ids = {str(item.get("run_id") or "") for item in available_run_entries}
        missing = sorted(selected_run_ids - available_ids)
        if missing:
            raise ValueError(f"Requested run_id values are not present in cache manifest: {missing}")
        run_entries = [item for item in available_run_entries if str(item.get("run_id") or "") in selected_run_ids]
    else:
        run_entries = list(available_run_entries)
    if not run_entries:
        raise ValueError("No cached runs selected for the cap sweep.")

    stage_dir = (
        Path(output_root).expanduser().resolve()
        if output_root is not None
        else _default_output_root(cache_manifest_path)
    )
    stage_dir.mkdir(parents=True, exist_ok=True)
    caps_dir = stage_dir / "caps"
    caps_dir.mkdir(parents=True, exist_ok=True)

    metadata_by_run_id = _group_metadata_rows_by_run_id(experiment_root)
    started = time.perf_counter()
    cap_contexts = {int(cap_px): [] for cap_px in cap_values}

    for run_entry in run_entries:
        run_cache = _load_cached_run_data(run_entry)
        metadata_row = metadata_by_run_id.get(run_cache["run_id"])
        if metadata_row is None:
            raise ValueError(f"Metadata row not found for cached run_id={run_cache['run_id']!r}")
        for cap_px in cap_values:
            cap_contexts[int(cap_px)].append(
                _run_context_for_cap(
                    run_cache,
                    metadata_row=metadata_row,
                    rule=rule,
                    cap_px=int(cap_px),
                    density_g_per_ml=density_g_per_ml,
                )
            )

    cap_summary_rows = []
    run_cap_rows = []
    condition_cap_rows = []
    cap_report_paths = {}
    for cap_px in cap_values:
        contexts = list(cap_contexts[int(cap_px)] or [])
        summary_rows, condition_rows, _grouped_contexts = report_mod._summaries_from_contexts(contexts)
        report_payload = None
        if not bool(summary_only):
            cap_output_root = caps_dir / f"cap_{int(cap_px)}"
            report_payload = report_mod._export_report_from_contexts(
                contexts,
                stage_dir=cap_output_root,
                experiment_root=experiment_root,
                run_id_filter=None if not selected_run_ids else ",".join(sorted(selected_run_ids)),
                density_g_per_ml=density_g_per_ml,
                correction_mode=CORRECTION_MODE,
                correction_rule={**dict(rule), "cap_px": int(cap_px)},
            )
            summary_rows = [dict(row) for row in list(report_payload.get("summary_rows") or [])]
            condition_rows = [dict(row) for row in list(report_payload.get("condition_summary_rows") or [])]
            cap_report_paths[int(cap_px)] = {
                "output_root": str(report_payload.get("output_root")),
                "report_manifest_json": str(report_payload["paths"]["report_manifest_json"]),
            }
        cap_summary_rows.append(
            _cap_summary_row(
                int(cap_px),
                summary_rows,
                condition_rows,
                report_payload=report_payload,
            )
        )
        run_cap_rows.extend([{**dict(row), "cap_px": int(cap_px)} for row in summary_rows])
        condition_cap_rows.extend([{**dict(row), "cap_px": int(cap_px)} for row in condition_rows])

    cap_summary_csv = proto_mod._write_csv(stage_dir / "cap_summary.csv", cap_summary_rows, fieldnames=CAP_SUMMARY_COLUMNS)
    cap_summary_json = proto_mod._write_json(stage_dir / "cap_summary.json", cap_summary_rows)
    run_cap_summary_csv = proto_mod._write_csv(stage_dir / "run_cap_summary.csv", run_cap_rows, fieldnames=RUN_CAP_SUMMARY_COLUMNS)
    run_cap_summary_json = proto_mod._write_json(stage_dir / "run_cap_summary.json", run_cap_rows)
    condition_cap_summary_csv = proto_mod._write_csv(stage_dir / "condition_cap_summary.csv", condition_cap_rows, fieldnames=CONDITION_CAP_SUMMARY_COLUMNS)
    condition_cap_summary_json = proto_mod._write_json(stage_dir / "condition_cap_summary.json", condition_cap_rows)

    predicted_vs_gravimetric_by_cap_png = stage_dir / "predicted_vs_gravimetric_by_cap.png"
    signed_residual_vs_cap_by_condition_png = stage_dir / "signed_residual_vs_cap_by_condition.png"
    predicted_to_gravimetric_ratio_vs_cap_by_condition_png = stage_dir / "predicted_to_gravimetric_ratio_vs_cap_by_condition.png"
    _plot_predicted_vs_gravimetric_by_cap(run_cap_rows, predicted_vs_gravimetric_by_cap_png)
    _plot_metric_vs_cap_by_condition(
        condition_cap_rows,
        metric_key="signed_residual_nl_mean",
        ylabel="Mean signed residual (nL)",
        title="Signed residual vs cap by condition",
        output_path=signed_residual_vs_cap_by_condition_png,
    )
    _plot_metric_vs_cap_by_condition(
        condition_cap_rows,
        metric_key="predicted_to_gravimetric_ratio_mean",
        ylabel="Mean predicted/gravimetric ratio",
        title="Predicted/gravimetric ratio vs cap by condition",
        output_path=predicted_to_gravimetric_ratio_vs_cap_by_condition_png,
    )

    elapsed_s = float(time.perf_counter() - started)
    manifest = {
        "analysis": ANALYSIS_NAME,
        "cache_manifest_json": str(cache_manifest_path),
        "experiment_root": str(experiment_root),
        "output_root": str(stage_dir),
        "requested_caps_px": [int(value) for value in cap_values],
        "applied_rule": dict(rule),
        "gravimetric_density_g_per_ml": float(density_g_per_ml),
        "selected_run_ids": sorted(str(item.get("run_id") or "") for item in run_entries),
        "summary_only": bool(summary_only),
        "elapsed_s": float(elapsed_s),
        "paths": {
            "cap_summary_csv": str(cap_summary_csv),
            "cap_summary_json": str(cap_summary_json),
            "run_cap_summary_csv": str(run_cap_summary_csv),
            "run_cap_summary_json": str(run_cap_summary_json),
            "condition_cap_summary_csv": str(condition_cap_summary_csv),
            "condition_cap_summary_json": str(condition_cap_summary_json),
            "predicted_vs_gravimetric_by_cap_png": str(predicted_vs_gravimetric_by_cap_png),
            "signed_residual_vs_cap_by_condition_png": str(signed_residual_vs_cap_by_condition_png),
            "predicted_to_gravimetric_ratio_vs_cap_by_condition_png": str(predicted_to_gravimetric_ratio_vs_cap_by_condition_png),
            "caps_dir": str(caps_dir),
        },
        "cap_report_paths": cap_report_paths,
    }
    manifest_path = proto_mod._write_json(stage_dir / "cap_sweep_manifest.json", manifest)
    return {
        **manifest,
        "paths": {
            **manifest["paths"],
            "cap_sweep_manifest_json": str(manifest_path),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay cached chroma-edge corrections across multiple outward caps."
    )
    parser.add_argument(
        "--cache-manifest",
        required=True,
        help="Path to cache_manifest.json written by online_chroma_edge_offset_cache.",
    )
    parser.add_argument(
        "--caps",
        default="",
        help="Optional comma-separated cap list. Defaults to every cap from 0..cached max offset.",
    )
    parser.add_argument(
        "--density-g-per-ml",
        required=True,
        type=float,
        help="Fluid density in g/mL for gravimetric conversion.",
    )
    parser.add_argument(
        "--run-id",
        action="append",
        default=[],
        help="Optional run_id filter. Can be repeated or passed as a comma-separated list.",
    )
    parser.add_argument(
        "--output-root",
        default="",
        help="Optional output directory. Defaults to <cache-root>/online_chroma_edge_cap_sweep.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Write only cross-cap summaries and comparison plots; skip per-cap report bundles.",
    )
    parser.add_argument("--gray-headroom-px", type=int, default=None)
    parser.add_argument("--delta-lab-chroma-max", type=float, default=None)
    parser.add_argument("--edge-bg-gap-min", type=int, default=None)
    parser.add_argument("--continuity-min-support", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    payload = export_online_chroma_edge_cap_sweep(
        args.cache_manifest,
        caps=args.caps or None,
        density_g_per_ml=args.density_g_per_ml,
        run_ids=args.run_id,
        output_root=args.output_root or None,
        summary_only=bool(args.summary_only),
        gray_headroom_px=args.gray_headroom_px,
        delta_lab_chroma_max=args.delta_lab_chroma_max,
        edge_bg_gap_min=args.edge_bg_gap_min,
        continuity_min_support=args.continuity_min_support,
    )
    print(
        json.dumps(
            {
                "output_root": payload["output_root"],
                "cap_sweep_manifest_json": payload["paths"]["cap_sweep_manifest_json"],
                "requested_caps_px": payload["requested_caps_px"],
                "selected_run_ids": payload["selected_run_ids"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
