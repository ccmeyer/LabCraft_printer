from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import cv2

from tools.stream_analysis import dataset as dataset_mod
from tools.stream_analysis import online_calibration as online_cal_mod
from tools.stream_analysis import online_chroma_edge_prototype as chroma_proto_mod
from tools.stream_analysis import online_fit as online_fit_mod
from tools.stream_analysis import online_replay as online_replay_mod
from tools.stream_analysis import online_runtime as runtime_mod
from tools.stream_analysis import online_tail as online_tail_mod
from tools.stream_analysis import segmented_tail as segmented_tail_mod


PROCESS_NAME = dataset_mod.ONLINE_STREAM_PROCESS_NAME
STAGE_DIRNAME = "online_stream_report"
CHROMA_EDGE_V2_STAGE_DIRNAME = "online_stream_report_chroma_edge_v2"
RUNTIME_RGB_FIX_STAGE_DIRNAME = "online_stream_report_runtime_rgb_fix"
TAIL_PHASES = {"tail_scout", "tail_backtrack", "tail_coarse", "tail_refine"}
CORRECTION_MODE_CHROMA_EDGE_V2 = "chroma_edge_v2"
CORRECTION_MODE_RUNTIME_RGB_FIX = "runtime_rgb_fix"

RUN_SUMMARY_COLUMNS = [
    "run_id",
    "condition_key",
    "print_pressure",
    "print_pw_us",
    "replicate_index",
    "num_printed",
    "gravimetric_density_g_per_ml",
    "gravimetric_per_print_nl",
    "predicted_volume_nl",
    "signed_residual_nl",
    "predicted_to_gravimetric_ratio",
    "flow_rate_nl_per_us",
    "flow_intercept_nl",
    "steady_rate_ci95_low_nl_per_us",
    "steady_rate_ci95_high_nl_per_us",
    "steady_rate_ci95_relative_width",
    "tail_start_delay_from_emergence_us",
    "initial_confirmed_collapse_delay_from_emergence_us",
    "confirmed_collapse_delay_from_emergence_us",
    "last_plateau_delay_from_emergence_us",
    "first_tail_bottom_guard_delay_from_emergence_us",
    "first_tail_detachment_delay_from_emergence_us",
    "first_tail_width_unavailable_delay_from_emergence_us",
    "max_tail_observed_delay_from_emergence_us",
    "gravimetric_equality_delay_us",
    "gravimetric_equality_delay_low_us",
    "gravimetric_equality_delay_high_us",
    "gravimetric_equality_band_width_us",
    "gravimetric_minus_tail_start_us",
    "gravimetric_minus_confirmed_collapse_us",
    "gravimetric_minus_first_detachment_us",
    "gravimetric_vs_detachment_status",
    "gravimetric_vs_observed_tail_status",
    "fit_status",
    "tail_phase_status",
    "tail_start_selection_method",
    "landmark_reason",
    "tail_settling_rule_applied",
    "tail_settling_rule_reason",
    "tail_settling_candidate_delay_from_emergence_us",
    "tail_settling_trace_window_end_delay_from_emergence_us",
    "tail_settling_progress_threshold",
    "analysis_warnings",
    "run_report_png",
]

CONDITION_SUMMARY_COLUMNS = [
    "condition_key",
    "print_pressure",
    "print_pw_us",
    "run_count",
    "gravimetric_per_print_nl_mean",
    "gravimetric_per_print_nl_cv",
    "predicted_volume_nl_mean",
    "predicted_volume_nl_cv",
    "signed_residual_nl_mean",
    "predicted_to_gravimetric_ratio_mean",
    "gravimetric_minus_tail_start_us_mean",
    "gravimetric_after_detachment_count",
    "gravimetric_after_last_observed_tail_count",
    "condition_overlay_png",
]

SEGMENTED_TAIL_REVIEW_COLUMNS = [
    "run_id",
    "condition_key",
    "print_pressure",
    "print_pw_us",
    "replicate_index",
    "current_tail_start_delay_from_emergence_us",
    "segmented_tail_start_delay_from_emergence_us",
    "segmented_knee_delay_from_emergence_us",
    "segmented_second_knee_delay_from_emergence_us",
    "segmented_breakpoint_delays_from_emergence_us",
    "segmented_breakpoint_refinement_step_us",
    "segmented_tail_start_observed_delay",
    "segmented_breakpoint_observed_delays",
    "segmented_tail_start_source",
    "segmented_three_break_tail_start_delay_from_emergence_us",
    "segmented_two_break_tail_start_delay_from_emergence_us",
    "segmented_midpoint_tail_start_delay_from_emergence_us",
    "segmented_model_name",
    "segmented_fit_status",
    "segmented_usable_point_count",
    "segmented_noise_estimate_px",
    "segmented_bic_plateau",
    "segmented_bic_plateau_decline",
    "segmented_bic_plateau_shoulder_collapse",
    "segmented_bic_plateau_gradual_shoulder_steep_shoulder_collapse",
    "segmented_three_break_gate_passed",
    "segmented_three_break_gate_reason",
    "segmented_three_break_tail_start_advance_us",
    "segmented_three_break_early_shoulder_slope_px_per_ms",
    "segmented_local_confirmation_passed",
    "segmented_local_confirmation_reason",
    "segmented_local_confirmation_baseline_width_px",
    "segmented_local_confirmation_final_drop_px",
    "segmented_local_confirmation_rebound_px",
    "segmented_minus_current_tail_start_us",
    "gravimetric_equality_delay_us",
    "gravimetric_minus_segmented_tail_start_us",
    "run_report_png",
]


def _clean_text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float_or_none(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _int_or_none(value):
    try:
        if value in (None, ""):
            return None
        return int(round(float(value)))
    except Exception:
        return None


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _format_condition_key(print_pressure: float | None, print_pw_us: int | None) -> str:
    pressure_text = "unknown" if print_pressure is None else f"{float(print_pressure):0.3f}".rstrip("0").rstrip(".")
    pw_text = "unknown" if print_pw_us is None else str(int(print_pw_us))
    return f"p{pressure_text}_pw{pw_text}"


def _safe_slug(text: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in str(text)).strip("_")


def _metadata_rows(experiment_root: Path) -> list[dict]:
    metadata_path = experiment_root / dataset_mod.METADATA_FILENAME
    with metadata_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _run_dir_for_row(experiment_root: Path, metadata_row: dict) -> Path:
    process_name = _clean_text(metadata_row.get("Capture Process")) or PROCESS_NAME
    run_id = _clean_text(metadata_row.get("Dataset name"))
    if not run_id:
        raise ValueError("Metadata row is missing Dataset name.")
    return experiment_root / "calibration_recordings" / process_name / run_id


def _normalized_correction_mode(correction_mode: str | None) -> str | None:
    text = _clean_text(correction_mode)
    if text is None:
        return None
    lowered = str(text).strip().lower()
    if lowered in {"none", "off", "false", "0"}:
        return None
    if lowered == CORRECTION_MODE_CHROMA_EDGE_V2:
        return CORRECTION_MODE_CHROMA_EDGE_V2
    if lowered in {CORRECTION_MODE_RUNTIME_RGB_FIX, "rgb_order_fix"}:
        return CORRECTION_MODE_RUNTIME_RGB_FIX
    raise ValueError(
        f"Unsupported correction_mode={correction_mode!r}. "
        f"Expected {CORRECTION_MODE_CHROMA_EDGE_V2!r}, "
        f"{CORRECTION_MODE_RUNTIME_RGB_FIX!r}, or None."
    )


def _default_stage_dirname(correction_mode: str | None) -> str:
    if correction_mode == CORRECTION_MODE_CHROMA_EDGE_V2:
        return CHROMA_EDGE_V2_STAGE_DIRNAME
    if correction_mode == CORRECTION_MODE_RUNTIME_RGB_FIX:
        return RUNTIME_RGB_FIX_STAGE_DIRNAME
    return STAGE_DIRNAME


def _stream_capture_log_index(experiment_root: Path) -> dict[str, dict]:
    index = {}
    for row in _iter_jsonl(experiment_root / dataset_mod.STREAM_CAPTURE_LOG_FILENAME):
        run_id = _clean_text(row.get("dataset_run_id"))
        if run_id is None:
            continue
        index[str(run_id)] = dict(row)
    return index


def _latest_emergence_result(emergence_run_dir: Path) -> dict:
    latest = {}
    for row in _iter_jsonl(emergence_run_dir / "analysis.jsonl"):
        if str(row.get("kind") or "") != "calibration_data_updated":
            continue
        payload = dict(row.get("payload") or {})
        result = dict(payload.get("result") or {})
        if not result:
            continue
        latest = {
            "analysis_row": dict(row),
            "payload": payload,
            "result": result,
        }
    return latest


def _fallback_emergence_run_dir(experiment_root: Path, online_run_dir: Path) -> Path | None:
    emergence_root = experiment_root / "calibration_recordings" / "DropletEmergenceCalibrationProcess"
    if not emergence_root.exists():
        return None
    candidates = [path for path in emergence_root.iterdir() if path.is_dir()]
    candidates.sort(key=lambda path: path.name)
    earlier = [path for path in candidates if path.name < online_run_dir.name]
    if earlier:
        return earlier[-1]
    return candidates[-1] if candidates else None


def _resolve_online_stream_correction_context(
    experiment_root: Path,
    run_dir: Path,
    *,
    plan_snapshot: dict,
    correction_cache: dict | None = None,
) -> dict:
    cache = correction_cache if isinstance(correction_cache, dict) else {}
    context_cache = cache.setdefault("run_contexts", {})
    run_key = str(Path(run_dir).resolve())
    if run_key in context_cache:
        return dict(context_cache[run_key])

    stream_log_index = cache.setdefault(
        "stream_capture_log_index",
        _stream_capture_log_index(experiment_root),
    )
    run_id = str(Path(run_dir).name)
    log_entry = dict(stream_log_index.get(run_id) or {})
    emergence_run_id = None
    for child in list(log_entry.get("child_processes") or []):
        child_row = dict(child or {})
        if str(child_row.get("process_name") or "") != "DropletEmergenceCalibrationProcess":
            continue
        emergence_run_id = _clean_text(child_row.get("run_id"))
        if emergence_run_id is not None:
            break

    emergence_run_dir = None
    if emergence_run_id is not None:
        emergence_run_dir = (
            experiment_root
            / "calibration_recordings"
            / "DropletEmergenceCalibrationProcess"
            / str(emergence_run_id)
        )
        if not emergence_run_dir.exists():
            emergence_run_dir = None
    if emergence_run_dir is None:
        emergence_run_dir = _fallback_emergence_run_dir(experiment_root, run_dir)
    if emergence_run_dir is None:
        raise FileNotFoundError(f"Unable to resolve emergence run for online stream run: {run_dir}")

    emergence_result_cache = cache.setdefault("emergence_results", {})
    emergence_key = str(emergence_run_dir.resolve())
    emergence_payload = emergence_result_cache.get(emergence_key)
    if emergence_payload is None:
        emergence_payload = _latest_emergence_result(emergence_run_dir)
        emergence_result_cache[emergence_key] = dict(emergence_payload)
    emergence_result = dict(emergence_payload.get("result") or {})
    nozzle_center = emergence_result.get("selected_center_px") or emergence_result.get(
        "pressure_band_nozzle_center_px"
    )
    if not isinstance(nozzle_center, (list, tuple)) or len(nozzle_center) < 2:
        raise ValueError(
            f"Emergence run {emergence_run_dir.name} does not expose selected_center_px/pressure_band_nozzle_center_px."
        )

    emergence_time_us = _int_or_none(((plan_snapshot.get("condition") or {}).get("emergence_time_us")))
    if emergence_time_us is None:
        emergence_time_us = _int_or_none(emergence_result.get("flash_delay"))
    if emergence_time_us is None:
        raise ValueError(f"Unable to resolve emergence_time_us for online stream run: {run_dir}")

    context = {
        "run_id": run_id,
        "online_run_dir": str(run_dir),
        "emergence_run_dir": str(emergence_run_dir),
        "emergence_run_id": str(emergence_run_dir.name),
        "emergence_time_us": int(emergence_time_us),
        "nozzle_center_px": [int(nozzle_center[0]), int(nozzle_center[1])],
        "resolved_from_stream_capture_log": bool(log_entry),
        "selected_rule": dict(chroma_proto_mod.SELECTED_V2_RULE),
    }
    context_cache[run_key] = dict(context)
    return context


def _corrected_frame_rows_for_run(
    run_dir: Path,
    frame_rows: list[dict],
    *,
    correction_context: dict,
    plan_snapshot: dict,
) -> list[dict]:
    corrected_rows = []
    analysis_config = (plan_snapshot.get("analysis_config") or None)
    for row in list(frame_rows or []):
        record = dict(row or {})
        image_ref = dict(record.get("image_ref") or {})
        image_relpath = _clean_text(image_ref.get("image_relpath")) or _clean_text(record.get("image_relpath"))
        if image_relpath is None:
            corrected_rows.append(record)
            continue
        if _int_or_none(record.get("delay_us")) is None and _int_or_none(record.get("flash_delay_us")) is None:
            corrected_rows.append(record)
            continue
        corrected = chroma_proto_mod.apply_selected_v2_correction_to_frame_row(
            record,
            image_path=run_dir / str(image_relpath),
            nozzle_center_px=list(correction_context["nozzle_center_px"]),
            emergence_time_us=int(correction_context["emergence_time_us"]),
            analysis_config=analysis_config,
            rule=chroma_proto_mod.SELECTED_V2_RULE,
        )
        corrected_rows.append(dict(corrected["corrected_frame_row"]))
    return corrected_rows


def _flow_frame_row_from_runtime_summary(
    *,
    delay_us: int,
    delay_from_emergence_us: int,
    replicate_index: int,
    image_ref: dict,
    summary: dict,
) -> dict:
    flow_volume_geometry_ok = (
        summary.get("flow_volume_geometry_ok")
        if "flow_volume_geometry_ok" in summary
        else (True if bool(summary.get("measurement_qc_pass")) else None)
    )
    flow_measurement_usable = summary.get("flow_measurement_usable")
    if flow_measurement_usable is None:
        flow_measurement_usable = bool(
            bool(summary.get("measurement_qc_pass"))
            and flow_volume_geometry_ok is not False
        )
    return online_cal_mod.build_online_stream_frame_row(
        phase="flow_rate",
        status=str(summary.get("status") or "rejected_measurement_qc"),
        delay_us=delay_us,
        delay_from_emergence_us=delay_from_emergence_us,
        replicate_index=replicate_index,
        qc={
            "measurement_qc_pass": bool(summary.get("measurement_qc_pass")),
            "nozzle_qc_pass": bool(summary.get("nozzle_qc_pass")),
            "silhouette_qc_pass": bool(summary.get("silhouette_qc_pass")),
        },
        image_ref=image_ref,
        warnings=list(summary.get("warnings") or []),
        silhouette_status=summary.get("silhouette_status"),
        failure_reason=summary.get("failure_reason"),
        attached_width_px=summary.get("attached_width_px"),
        visible_volume_nl=summary.get("visible_volume_nl"),
        attached_bottom_clearance_px=summary.get("attached_bottom_clearance_px"),
        min_accepted_fluid_distance_from_bottom_px=summary.get(
            "min_accepted_fluid_distance_from_bottom_px"
        ),
        accepted_component_count=summary.get("accepted_component_count"),
        accepted_detached_component_count=summary.get("accepted_detached_component_count"),
        plausible_unaccepted_component_count=summary.get("plausible_unaccepted_component_count"),
        plausible_unaccepted_visible_volume_nl=summary.get(
            "plausible_unaccepted_visible_volume_nl"
        ),
        detached_near_bottom_warning=bool(summary.get("detached_near_bottom_warning")),
        near_nozzle_detached_warning=bool(summary.get("near_nozzle_detached_warning")),
        late_frame_warning=bool(summary.get("late_frame_warning")),
        attached_bottom_guard_hit=bool(summary.get("attached_bottom_guard_hit")),
        attached_lower_centerline_span_px=summary.get("attached_lower_centerline_span_px"),
        attached_lower_centerline_rms_px=summary.get("attached_lower_centerline_rms_px"),
        attached_volume_geometry_ok=summary.get("attached_volume_geometry_ok"),
        detached_volume_geometry_ok=summary.get("detached_volume_geometry_ok"),
        flow_volume_geometry_ok=flow_volume_geometry_ok,
        flow_volume_geometry_reasons=list(summary.get("flow_volume_geometry_reasons") or []),
        flow_volume_geometry_warnings=list(summary.get("flow_volume_geometry_warnings") or []),
        detached_geometry_details=list(summary.get("detached_geometry_details") or []),
        min_detached_axis_symmetry_score=summary.get("min_detached_axis_symmetry_score"),
        max_detached_local_centerline_span_px=summary.get("max_detached_local_centerline_span_px"),
        max_detached_axis_offset_px=summary.get("max_detached_axis_offset_px"),
        flow_geometry_confidence=summary.get("flow_geometry_confidence"),
        flow_optical_confidence=summary.get("flow_optical_confidence"),
        flow_point_confidence=summary.get("flow_point_confidence"),
        flow_optical_confidence_active=summary.get("flow_optical_confidence_active"),
        optical_activation_clearance_px=summary.get("optical_activation_clearance_px"),
        lower_edge_jitter_px=summary.get("lower_edge_jitter_px"),
        boundary_chroma_aberration_score=summary.get("boundary_chroma_aberration_score"),
        pixel_size_um=summary.get("pixel_size_um"),
        late_coverage_candidate=summary.get("late_coverage_candidate"),
        late_coverage_metric=summary.get("late_coverage_metric"),
        flow_volume_complete_ok=summary.get("flow_volume_complete_ok"),
        flow_volume_completeness_reasons=list(
            summary.get("flow_volume_completeness_reasons") or []
        ),
        flow_measurement_usable=bool(flow_measurement_usable),
    )


def _tail_frame_row_from_runtime_summary(
    *,
    phase: str,
    delay_us: int,
    delay_from_emergence_us: int,
    replicate_index: int,
    image_ref: dict,
    summary: dict,
) -> dict:
    tail_qc_pass = bool(summary.get("tail_width_usable"))
    status = "accepted" if tail_qc_pass else str(summary.get("status") or "rejected_tail_qc")
    return online_cal_mod.build_online_stream_frame_row(
        phase=phase,
        status=status,
        delay_us=delay_us,
        delay_from_emergence_us=delay_from_emergence_us,
        replicate_index=replicate_index,
        qc={
            "measurement_qc_pass": bool(summary.get("measurement_qc_pass")),
            "nozzle_qc_pass": bool(summary.get("nozzle_qc_pass")),
            "silhouette_qc_pass": bool(summary.get("silhouette_qc_pass")),
            "tail_qc_pass": bool(tail_qc_pass),
            "tail_width_usable": bool(summary.get("tail_width_usable")),
            "tail_landmark_usable": bool(summary.get("tail_landmark_usable")),
        },
        image_ref=image_ref,
        warnings=list(summary.get("warnings") or []),
        silhouette_status=summary.get("silhouette_status"),
        failure_reason=summary.get("failure_reason"),
        attached_width_px=summary.get("attached_width_px"),
        visible_volume_nl=summary.get("visible_volume_nl"),
        attached_bottom_clearance_px=summary.get("attached_bottom_clearance_px"),
        min_accepted_fluid_distance_from_bottom_px=summary.get(
            "min_accepted_fluid_distance_from_bottom_px"
        ),
        accepted_component_count=summary.get("accepted_component_count"),
        accepted_detached_component_count=summary.get("accepted_detached_component_count"),
        tail_width_usable=bool(summary.get("tail_width_usable")),
        separated_from_nozzle_landmark=bool(summary.get("separated_from_nozzle_landmark")),
        tail_landmark_usable=bool(summary.get("tail_landmark_usable")),
        landmark_reason=summary.get("landmark_reason"),
        detached_near_bottom_warning=bool(summary.get("detached_near_bottom_warning")),
        near_nozzle_detached_warning=bool(summary.get("near_nozzle_detached_warning")),
        late_frame_warning=bool(summary.get("late_frame_warning")),
        attached_bottom_guard_hit=bool(summary.get("attached_bottom_guard_hit")),
        pixel_size_um=summary.get("pixel_size_um"),
    )


def _runtime_rgb_fix_frame_rows_for_run(
    run_dir: Path,
    frame_rows: list[dict],
    *,
    correction_context: dict,
    plan_snapshot: dict,
    pixel_size_um: float | None = None,
) -> list[dict]:
    corrected_rows = []
    analysis_config = (plan_snapshot.get("analysis_config") or None)
    tail_phase_labels = set(TAIL_PHASES)
    for row in list(frame_rows or []):
        record = dict(row or {})
        phase = str(record.get("phase") or "")
        if phase not in {"flow_rate", *tail_phase_labels}:
            corrected_rows.append(record)
            continue

        image_ref = dict(record.get("image_ref") or {})
        image_relpath = _clean_text(image_ref.get("image_relpath")) or _clean_text(record.get("image_relpath"))
        delay_us = _int_or_none(record.get("delay_us"))
        delay_from_emergence_us = _int_or_none(record.get("delay_from_emergence_us"))
        replicate_index = _int_or_none(record.get("replicate_index"))
        if (
            image_relpath is None
            or delay_us is None
            or delay_from_emergence_us is None
            or replicate_index is None
        ):
            corrected_rows.append(record)
            continue

        image_path = run_dir / str(image_relpath)
        frame_bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if frame_bgr is None:
            corrected_rows.append(record)
            continue

        capture_index = _int_or_none(record.get("capture_index"))
        if capture_index is None:
            capture_index = _int_or_none(image_ref.get("capture_index"))
        analysis = runtime_mod.analyze_online_stream_frame(
            frame_image=frame_bgr,
            background_image=None,
            nozzle_center_px=list(correction_context["nozzle_center_px"]),
            delay_us=int(delay_us),
            emergence_time_us=int(correction_context["emergence_time_us"]),
            analysis_config=analysis_config,
            capture_ref=image_ref,
            capture_index=capture_index,
            frame_color_order="bgr",
            pixel_size_um=pixel_size_um,
        )
        summary = dict(analysis.get("summary") or {})
        if phase == "flow_rate":
            corrected_rows.append(
                _flow_frame_row_from_runtime_summary(
                    delay_us=int(delay_us),
                    delay_from_emergence_us=int(delay_from_emergence_us),
                    replicate_index=int(replicate_index),
                    image_ref=image_ref,
                    summary=summary,
                )
            )
            continue
        corrected_rows.append(
            _tail_frame_row_from_runtime_summary(
                phase=phase,
                delay_us=int(delay_us),
                delay_from_emergence_us=int(delay_from_emergence_us),
                replicate_index=int(replicate_index),
                image_ref=image_ref,
                summary=summary,
            )
        )
    return corrected_rows


def _replay_online_stream_run_from_frame_rows(
    run_dir: Path,
    *,
    plan_snapshot: dict,
    flow_fit_artifact: dict,
    tail_fit_artifact: dict,
    frame_rows: list[dict],
    correction_context: dict | None = None,
    flow_fit_policy_override: dict | None = None,
) -> dict:
    stored_tail_plan = dict(tail_fit_artifact.get("tail_plan") or {})
    quality_policy = dict(plan_snapshot.get("analysis_config") or {})
    if isinstance(flow_fit_policy_override, dict):
        quality_policy.update(dict(flow_fit_policy_override))
    flow_measurements = online_replay_mod._accepted_measurements(
        frame_rows,
        phases=("flow_rate",),
    )
    flow_delay_summaries = online_replay_mod._group_delay_summaries(
        frame_rows,
        phase="flow_rate",
    )
    replay_flow_fit = online_fit_mod.fit_online_stream_flow_phase(
        measurements=flow_measurements,
        delay_summaries=flow_delay_summaries,
        quality_policy=quality_policy,
    )

    baseline_width_px = _float_or_none(replay_flow_fit.get("steady_width_baseline_px"))
    if baseline_width_px is None:
        baseline_width_px = _float_or_none((flow_fit_artifact.get("fit") or {}).get("steady_width_baseline_px"))
    scout_summaries = online_replay_mod._group_delay_summaries(
        frame_rows,
        phase=("tail_scout", "tail_coarse"),
        baseline_width_px=baseline_width_px,
    )
    backtrack_summaries = online_replay_mod._group_delay_summaries(
        frame_rows,
        phase=("tail_backtrack", "tail_refine"),
        baseline_width_px=baseline_width_px,
    )
    trigger_bracket = online_replay_mod._replay_tail_trigger_bracket(
        scout_summaries,
        backtrack_summaries,
        tail_plan=stored_tail_plan,
        flow_delay_summaries=flow_delay_summaries,
    )
    replay_tail_result = online_tail_mod.resolve_online_stream_tail_result(
        flow_fit_result=dict(replay_flow_fit or {}),
        tail_plan=stored_tail_plan,
        scout_summaries=scout_summaries,
        backtrack_summaries=backtrack_summaries,
        trigger_bracket=trigger_bracket,
        flow_delay_summaries=flow_delay_summaries,
        analysis_config=quality_policy,
    )
    return {
        "plan_snapshot": plan_snapshot,
        "correction_context": None if correction_context is None else dict(correction_context),
        "frame_rows": list(frame_rows or []),
        "fit": dict(replay_flow_fit or {}),
        "tail_result": dict(replay_tail_result or {}),
        "run_dir": run_dir,
        "flow_artifact": dict(flow_fit_artifact or {}),
        "tail_artifact": dict(tail_fit_artifact or {}),
    }


def _replay_corrected_online_stream_run(
    experiment_root: Path,
    run_dir: Path,
    *,
    correction_cache: dict | None = None,
    flow_fit_policy_override: dict | None = None,
) -> dict:
    plan_snapshot = _load_json(run_dir / "plan_snapshot.json")
    flow_fit_artifact = _load_json(run_dir / "flow_fit.json")
    tail_fit_artifact = _load_json(run_dir / "tail_fit.json")
    stored_tail_plan = dict(tail_fit_artifact.get("tail_plan") or {})
    frame_rows = _iter_jsonl(run_dir / "frames.jsonl")
    correction_context = _resolve_online_stream_correction_context(
        experiment_root,
        run_dir,
        plan_snapshot=plan_snapshot,
        correction_cache=correction_cache,
    )
    corrected_frame_rows = _corrected_frame_rows_for_run(
        run_dir,
        frame_rows,
        correction_context=correction_context,
        plan_snapshot=plan_snapshot,
    )
    return _replay_online_stream_run_from_frame_rows(
        run_dir,
        plan_snapshot=plan_snapshot,
        flow_fit_artifact=flow_fit_artifact,
        tail_fit_artifact=tail_fit_artifact,
        frame_rows=corrected_frame_rows,
        correction_context=correction_context,
        flow_fit_policy_override=flow_fit_policy_override,
    )


def _replay_runtime_rgb_fix_online_stream_run(
    experiment_root: Path,
    run_dir: Path,
    *,
    correction_cache: dict | None = None,
    flow_fit_policy_override: dict | None = None,
    pixel_size_um: float | None = None,
) -> dict:
    plan_snapshot = _load_json(run_dir / "plan_snapshot.json")
    flow_fit_artifact = _load_json(run_dir / "flow_fit.json")
    tail_fit_artifact = _load_json(run_dir / "tail_fit.json")
    frame_rows = _iter_jsonl(run_dir / "frames.jsonl")
    correction_context = _resolve_online_stream_correction_context(
        experiment_root,
        run_dir,
        plan_snapshot=plan_snapshot,
        correction_cache=correction_cache,
    )
    if pixel_size_um is not None:
        correction_context = {
            **correction_context,
            "um_per_pixel": float(pixel_size_um),
        }
    corrected_frame_rows = _runtime_rgb_fix_frame_rows_for_run(
        run_dir,
        frame_rows,
        correction_context=correction_context,
        plan_snapshot=plan_snapshot,
        pixel_size_um=pixel_size_um,
    )
    return _replay_online_stream_run_from_frame_rows(
        run_dir,
        plan_snapshot=plan_snapshot,
        flow_fit_artifact=flow_fit_artifact,
        tail_fit_artifact=tail_fit_artifact,
        frame_rows=corrected_frame_rows,
        correction_context=correction_context,
        flow_fit_policy_override=flow_fit_policy_override,
    )


def _validate_density_g_per_ml(density_g_per_ml: float | int | None) -> float:
    density = _float_or_none(density_g_per_ml)
    if density is None or float(density) <= 0.0:
        raise ValueError("gravimetric density must be a positive number in g/mL.")
    return float(density)


def _validate_um_per_pixel(um_per_pixel: float | int | None) -> float | None:
    if um_per_pixel is None:
        return None
    value = _float_or_none(um_per_pixel)
    if value is None or float(value) <= 0.0:
        raise ValueError("um_per_pixel must be a positive number.")
    return float(value)


def _gravimetric_per_print_nl(
    metadata_row: dict,
    *,
    density_g_per_ml: float | int = 1.0,
) -> float | None:
    density = _validate_density_g_per_ml(density_g_per_ml)
    mass_per_print_mg = _float_or_none(metadata_row.get("Mass/print"))
    if mass_per_print_mg is not None:
        return (float(mass_per_print_mg) * 1000.0) / float(density)
    mass_change_mg = _float_or_none(metadata_row.get("Mass Change"))
    num_printed = _int_or_none(metadata_row.get("Num printed"))
    if mass_change_mg is None or num_printed in (None, 0):
        return None
    return (float(mass_change_mg) * 1000.0) / (float(num_printed) * float(density))


def _flow_fit_lines(
    fit: dict,
    *,
    x_min: float,
    x_max: float,
):
    slope = _float_or_none(fit.get("flow_rate_nl_per_us"))
    intercept = _float_or_none(fit.get("flow_intercept_nl"))
    if slope is None or intercept is None:
        return None
    x_values = [float(x_min), float(x_max)]
    y_values = [float(intercept) + (float(slope) * x_value) for x_value in x_values]
    slope_low = _float_or_none(fit.get("steady_rate_ci95_low_nl_per_us"))
    slope_high = _float_or_none(fit.get("steady_rate_ci95_high_nl_per_us"))
    band = None
    if slope_low is not None and slope_high is not None:
        band = {
            "lower": [float(intercept) + (float(slope_low) * x_value) for x_value in x_values],
            "upper": [float(intercept) + (float(slope_high) * x_value) for x_value in x_values],
        }
    return {
        "x": x_values,
        "y": y_values,
        "band": band,
    }


def _gravimetric_equality_metrics(gravimetric_per_print_nl: float | None, fit: dict) -> dict:
    metrics = {
        "gravimetric_equality_delay_us": None,
        "gravimetric_equality_delay_low_us": None,
        "gravimetric_equality_delay_high_us": None,
        "gravimetric_equality_band_width_us": None,
    }
    gravimetric_per_print_nl = _float_or_none(gravimetric_per_print_nl)
    slope = _float_or_none(fit.get("flow_rate_nl_per_us"))
    intercept = _float_or_none(fit.get("flow_intercept_nl"))
    if gravimetric_per_print_nl is None or slope in (None, 0.0) or intercept is None:
        return metrics

    central_delay = (float(gravimetric_per_print_nl) - float(intercept)) / float(slope)
    metrics["gravimetric_equality_delay_us"] = float(central_delay)

    slope_low = _float_or_none(fit.get("steady_rate_ci95_low_nl_per_us"))
    slope_high = _float_or_none(fit.get("steady_rate_ci95_high_nl_per_us"))
    if slope_low is None or slope_high is None or float(slope_low) <= 0.0 or float(slope_high) <= 0.0:
        return metrics

    delay_candidates = [
        (float(gravimetric_per_print_nl) - float(intercept)) / float(slope_low),
        (float(gravimetric_per_print_nl) - float(intercept)) / float(slope_high),
    ]
    delay_low = float(min(delay_candidates))
    delay_high = float(max(delay_candidates))
    metrics["gravimetric_equality_delay_low_us"] = delay_low
    metrics["gravimetric_equality_delay_high_us"] = delay_high
    metrics["gravimetric_equality_band_width_us"] = float(delay_high - delay_low)
    return metrics


def _delay_sort_key(row: dict):
    return (
        _int_or_none(row.get("delay_from_emergence_us")) or 10**9,
        _int_or_none(((row.get("image_ref") or {}).get("capture_index"))) or 10**9,
    )


def _phase_rows(frame_rows: list[dict], *phases: str) -> list[dict]:
    phase_set = {str(phase) for phase in phases}
    return sorted(
        [dict(row or {}) for row in list(frame_rows or []) if str((row or {}).get("phase") or "") in phase_set],
        key=_delay_sort_key,
    )


def _points_from_rows(rows: list[dict], *, y_key: str, accepted_only: bool = False) -> list[tuple[float, float]]:
    points = []
    for row in list(rows or []):
        if accepted_only and str(row.get("status") or "") != "accepted":
            continue
        x_value = _float_or_none(row.get("delay_from_emergence_us"))
        y_value = _float_or_none(row.get(y_key))
        if x_value is None or y_value is None:
            continue
        points.append((float(x_value), float(y_value)))
    points.sort()
    return points


def _interp(points: list[tuple[float, float]], x_value: float | None) -> float | None:
    if x_value is None or not points:
        return None
    ordered = sorted(points)
    if float(x_value) <= float(ordered[0][0]):
        return float(ordered[0][1])
    if float(x_value) >= float(ordered[-1][0]):
        return float(ordered[-1][1])
    for (x0, y0), (x1, y1) in zip(ordered, ordered[1:]):
        if float(x0) <= float(x_value) <= float(x1):
            if float(x1) == float(x0):
                return float(y0)
            frac = (float(x_value) - float(x0)) / (float(x1) - float(x0))
            return float(y0) + frac * (float(y1) - float(y0))
    return None


def _first_delay(rows: list[dict], predicate) -> int | None:
    candidates = []
    for row in list(rows or []):
        if not predicate(row):
            continue
        delay = _int_or_none(row.get("delay_from_emergence_us"))
        if delay is not None:
            candidates.append(int(delay))
    return None if not candidates else int(min(candidates))


def _max_delay(rows: list[dict]) -> int | None:
    candidates = [
        _int_or_none(row.get("delay_from_emergence_us"))
        for row in list(rows or [])
        if _int_or_none(row.get("delay_from_emergence_us")) is not None
    ]
    return None if not candidates else int(max(candidates))


def _tail_detachment_predicate(row: dict) -> bool:
    warnings = {str(item) for item in list(row.get("warnings") or [])}
    if bool(row.get("separated_from_nozzle_landmark")):
        return True
    if bool(row.get("tail_landmark_usable")):
        return True
    if str(row.get("landmark_reason") or "") == "separated_from_nozzle":
        return True
    if "attached_width_unavailable" in warnings:
        return True
    return False


def _width_unavailable_predicate(row: dict) -> bool:
    warnings = {str(item) for item in list(row.get("warnings") or [])}
    return _float_or_none(row.get("attached_width_px")) is None or "attached_width_unavailable" in warnings


def _run_relationship_status(
    gravimetric_equality_delay_us: float | None,
    *,
    first_tail_detachment_delay_us: int | None,
    max_tail_observed_delay_us: int | None,
) -> tuple[str, str]:
    if gravimetric_equality_delay_us is None:
        return ("unresolved_missing_fit", "unresolved_missing_fit")

    detachment_status = "before_first_detachment_landmark"
    if (
        first_tail_detachment_delay_us is not None
        and float(gravimetric_equality_delay_us) > float(first_tail_detachment_delay_us)
    ):
        detachment_status = "after_first_detachment_landmark"

    observed_status = "within_observed_tail_window"
    if (
        max_tail_observed_delay_us is not None
        and float(gravimetric_equality_delay_us) > float(max_tail_observed_delay_us)
    ):
        observed_status = "after_last_observed_tail_frame"

    return detachment_status, observed_status


def _context_from_replay(
    *,
    metadata_row: dict,
    run_dir: Path,
    frame_rows: list[dict],
    fit: dict,
    tail_result: dict,
    density_g_per_ml: float | int = 1.0,
    correction_mode: str | None = None,
    correction_context: dict | None = None,
    flow_artifact: dict | None = None,
    tail_artifact: dict | None = None,
) -> dict:
    tail_phase = dict(tail_result.get("tail_phase") or {})

    print_pressure = _float_or_none(metadata_row.get("Print Pressure"))
    print_pw_us = _int_or_none(metadata_row.get("Print PW"))
    replicate_index = _int_or_none(metadata_row.get("Rep"))
    predicted_volume_nl = _float_or_none(tail_result.get("predicted_volume_nl"))
    if predicted_volume_nl is None and correction_mode is None:
        predicted_volume_nl = _float_or_none(metadata_row.get("Predicted Volume (nL)"))
    gravimetric_density_g_per_ml = _validate_density_g_per_ml(density_g_per_ml)
    gravimetric_per_print_nl = _gravimetric_per_print_nl(
        metadata_row,
        density_g_per_ml=gravimetric_density_g_per_ml,
    )
    gravimetric_metrics = _gravimetric_equality_metrics(gravimetric_per_print_nl, fit)

    flow_rows = _phase_rows(frame_rows, "flow_rate")
    tail_rows = _phase_rows(frame_rows, *sorted(TAIL_PHASES))
    flow_volume_points = _points_from_rows(flow_rows, y_key="visible_volume_nl", accepted_only=True)
    tail_volume_points = _points_from_rows(tail_rows, y_key="visible_volume_nl", accepted_only=True)
    tail_rejected_volume_points = _points_from_rows(tail_rows, y_key="visible_volume_nl", accepted_only=False)
    width_points = _points_from_rows(flow_rows + tail_rows, y_key="attached_width_px", accepted_only=False)
    clearance_points = _points_from_rows(flow_rows + tail_rows, y_key="attached_bottom_clearance_px", accepted_only=False)

    tail_start_delay = _int_or_none(tail_phase.get("tail_start_delay_from_emergence_us"))
    initial_confirmed_collapse_delay = _int_or_none(
        tail_phase.get("initial_confirmed_collapse_delay_from_emergence_us")
    )
    confirmed_collapse_delay = _int_or_none(tail_phase.get("confirmed_collapse_delay_from_emergence_us"))
    last_plateau_delay = _int_or_none(tail_phase.get("last_plateau_delay_from_emergence_us"))
    first_tail_bottom_guard_delay = _first_delay(
        tail_rows,
        lambda row: bool(row.get("attached_bottom_guard_hit")),
    )
    first_tail_detachment_delay = _first_delay(tail_rows, _tail_detachment_predicate)
    first_tail_width_unavailable_delay = _first_delay(tail_rows, _width_unavailable_predicate)
    max_tail_observed_delay = _max_delay(tail_rows)

    grav_vs_detachment, grav_vs_observed = _run_relationship_status(
        gravimetric_metrics.get("gravimetric_equality_delay_us"),
        first_tail_detachment_delay_us=first_tail_detachment_delay,
        max_tail_observed_delay_us=max_tail_observed_delay,
    )

    signed_residual_nl = None
    predicted_to_grav_ratio = None
    if gravimetric_per_print_nl is not None and predicted_volume_nl is not None:
        signed_residual_nl = float(gravimetric_per_print_nl) - float(predicted_volume_nl)
        if float(gravimetric_per_print_nl) != 0.0:
            predicted_to_grav_ratio = float(predicted_volume_nl) / float(gravimetric_per_print_nl)

    summary_row = {
        "run_id": _clean_text(metadata_row.get("Dataset name")),
        "condition_key": _format_condition_key(print_pressure, print_pw_us),
        "print_pressure": print_pressure,
        "print_pw_us": print_pw_us,
        "replicate_index": replicate_index,
        "num_printed": _int_or_none(metadata_row.get("Num printed")),
        "gravimetric_density_g_per_ml": gravimetric_density_g_per_ml,
        "gravimetric_per_print_nl": gravimetric_per_print_nl,
        "predicted_volume_nl": predicted_volume_nl,
        "signed_residual_nl": signed_residual_nl,
        "predicted_to_gravimetric_ratio": predicted_to_grav_ratio,
        "flow_rate_nl_per_us": _float_or_none(fit.get("flow_rate_nl_per_us")),
        "flow_intercept_nl": _float_or_none(fit.get("flow_intercept_nl")),
        "steady_rate_ci95_low_nl_per_us": _float_or_none(fit.get("steady_rate_ci95_low_nl_per_us")),
        "steady_rate_ci95_high_nl_per_us": _float_or_none(fit.get("steady_rate_ci95_high_nl_per_us")),
        "steady_rate_ci95_relative_width": _float_or_none(fit.get("steady_rate_ci95_relative_width")),
        "tail_start_delay_from_emergence_us": tail_start_delay,
        "initial_confirmed_collapse_delay_from_emergence_us": initial_confirmed_collapse_delay,
        "confirmed_collapse_delay_from_emergence_us": confirmed_collapse_delay,
        "last_plateau_delay_from_emergence_us": last_plateau_delay,
        "first_tail_bottom_guard_delay_from_emergence_us": first_tail_bottom_guard_delay,
        "first_tail_detachment_delay_from_emergence_us": first_tail_detachment_delay,
        "first_tail_width_unavailable_delay_from_emergence_us": first_tail_width_unavailable_delay,
        "max_tail_observed_delay_from_emergence_us": max_tail_observed_delay,
        "gravimetric_equality_delay_us": gravimetric_metrics.get("gravimetric_equality_delay_us"),
        "gravimetric_equality_delay_low_us": gravimetric_metrics.get("gravimetric_equality_delay_low_us"),
        "gravimetric_equality_delay_high_us": gravimetric_metrics.get("gravimetric_equality_delay_high_us"),
        "gravimetric_equality_band_width_us": gravimetric_metrics.get("gravimetric_equality_band_width_us"),
        "gravimetric_minus_tail_start_us": None
        if gravimetric_metrics.get("gravimetric_equality_delay_us") is None or tail_start_delay is None
        else float(gravimetric_metrics["gravimetric_equality_delay_us"]) - float(tail_start_delay),
        "gravimetric_minus_confirmed_collapse_us": None
        if gravimetric_metrics.get("gravimetric_equality_delay_us") is None or confirmed_collapse_delay is None
        else float(gravimetric_metrics["gravimetric_equality_delay_us"]) - float(confirmed_collapse_delay),
        "gravimetric_minus_first_detachment_us": None
        if gravimetric_metrics.get("gravimetric_equality_delay_us") is None or first_tail_detachment_delay is None
        else float(gravimetric_metrics["gravimetric_equality_delay_us"]) - float(first_tail_detachment_delay),
        "gravimetric_vs_detachment_status": grav_vs_detachment,
        "gravimetric_vs_observed_tail_status": grav_vs_observed,
        "fit_status": _clean_text(fit.get("fit_status")),
        "tail_phase_status": _clean_text(tail_phase.get("status")),
        "tail_start_selection_method": _clean_text(tail_phase.get("tail_start_selection_method")),
        "landmark_reason": _clean_text(tail_phase.get("landmark_reason")),
        "tail_settling_rule_applied": bool(tail_phase.get("tail_settling_rule_applied")),
        "tail_settling_rule_reason": _clean_text(tail_phase.get("tail_settling_rule_reason")),
        "tail_settling_candidate_delay_from_emergence_us": _int_or_none(
            tail_phase.get("tail_settling_candidate_delay_from_emergence_us")
        ),
        "tail_settling_trace_window_end_delay_from_emergence_us": _int_or_none(
            tail_phase.get("tail_settling_trace_window_end_delay_from_emergence_us")
        ),
        "tail_settling_progress_threshold": _float_or_none(
            tail_phase.get("tail_settling_progress_threshold")
        ),
        "analysis_warnings": _clean_text(metadata_row.get("Analysis Warnings")),
        "run_report_png": None,
    }

    return {
        "summary_row": summary_row,
        "run_dir": run_dir,
        "metadata_row": dict(metadata_row),
        "flow_artifact": dict(flow_artifact or {}),
        "tail_artifact": dict(tail_artifact or {}),
        "fit": dict(fit or {}),
        "tail_result": dict(tail_result or {}),
        "tail_phase": tail_phase,
        "correction_mode": correction_mode,
        "correction_context": None if correction_context is None else dict(correction_context),
        "frame_rows": list(frame_rows or []),
        "flow_rows": flow_rows,
        "tail_rows": tail_rows,
        "flow_volume_points": flow_volume_points,
        "tail_volume_points": tail_volume_points,
        "tail_rejected_volume_points": tail_rejected_volume_points,
        "width_points": width_points,
        "clearance_points": clearance_points,
    }


def _run_context(
    experiment_root: Path,
    metadata_row: dict,
    *,
    density_g_per_ml: float | int = 1.0,
    correction_mode: str | None = None,
    correction_cache: dict | None = None,
    flow_fit_policy_override: dict | None = None,
    um_per_pixel: float | None = None,
) -> dict:
    correction_mode = _normalized_correction_mode(correction_mode)
    run_id = _clean_text(metadata_row.get("Dataset name"))
    run_dir = _run_dir_for_row(experiment_root, metadata_row)
    flow_artifact = _load_json(run_dir / "flow_fit.json")
    tail_artifact = _load_json(run_dir / "tail_fit.json")
    correction_context = None
    if correction_mode == CORRECTION_MODE_CHROMA_EDGE_V2:
        corrected_replay = _replay_corrected_online_stream_run(
            experiment_root,
            run_dir,
            correction_cache=correction_cache,
            flow_fit_policy_override=flow_fit_policy_override,
        )
        frame_rows = list(corrected_replay.get("frame_rows") or [])
        fit = dict(corrected_replay.get("fit") or {})
        tail_result = dict(corrected_replay.get("tail_result") or {})
        correction_context = dict(corrected_replay.get("correction_context") or {})
    elif correction_mode == CORRECTION_MODE_RUNTIME_RGB_FIX:
        corrected_replay = _replay_runtime_rgb_fix_online_stream_run(
            experiment_root,
            run_dir,
            correction_cache=correction_cache,
            flow_fit_policy_override=flow_fit_policy_override,
            pixel_size_um=um_per_pixel,
        )
        frame_rows = list(corrected_replay.get("frame_rows") or [])
        fit = dict(corrected_replay.get("fit") or {})
        tail_result = dict(corrected_replay.get("tail_result") or {})
        correction_context = dict(corrected_replay.get("correction_context") or {})
    else:
        frame_rows = _iter_jsonl(run_dir / "frames.jsonl")
        fit = dict(flow_artifact.get("fit") or {})
        tail_result = dict(tail_artifact.get("result") or {})
    return _context_from_replay(
        metadata_row=metadata_row,
        run_dir=run_dir,
        frame_rows=frame_rows,
        fit=fit,
        tail_result=tail_result,
        density_g_per_ml=density_g_per_ml,
        correction_mode=correction_mode,
        correction_context=correction_context,
        flow_artifact=flow_artifact,
        tail_artifact=tail_artifact,
    )


def _metadata_row_from_online_run_dir(run_dir: Path, tail_artifact: dict) -> dict:
    run_id = run_dir.name
    run_meta = _load_json(run_dir / "run_meta.json")
    if _clean_text(run_meta.get("run_id")):
        run_id = str(run_meta.get("run_id"))
    condition = dict(tail_artifact.get("condition") or {})
    tail_result = dict(tail_artifact.get("result") or {})
    warnings = list(tail_result.get("warnings") or tail_artifact.get("warnings") or [])
    return {
        "Dataset name": run_id,
        "Print PW": condition.get("print_pulse_width_us"),
        "Print Pressure": condition.get("print_pressure_psi"),
        "Rep": "",
        "Mass/print": "",
        "Num printed": "",
        "Capture Process": PROCESS_NAME,
        "Predicted Volume (nL)": tail_result.get("predicted_volume_nl"),
        "Analysis Warnings": "; ".join(str(item) for item in warnings if str(item or "").strip()),
    }


def _context_from_online_run_dir(
    experiment_root: Path,
    run_dir: Path,
    *,
    density_g_per_ml: float | int,
) -> dict:
    flow_artifact = _load_json(run_dir / "flow_fit.json")
    tail_artifact = _load_json(run_dir / "tail_fit.json")
    frame_rows = _iter_jsonl(run_dir / "frames.jsonl")
    return _context_from_replay(
        metadata_row=_metadata_row_from_online_run_dir(run_dir, tail_artifact),
        run_dir=run_dir,
        frame_rows=frame_rows,
        fit=dict(flow_artifact.get("fit") or {}),
        tail_result=dict(tail_artifact.get("result") or {}),
        density_g_per_ml=density_g_per_ml,
        correction_mode=None,
        correction_context=None,
        flow_artifact=flow_artifact,
        tail_artifact=tail_artifact,
    )


def _segmented_tail_contexts_with_unlisted_runs(
    experiment_root: Path,
    contexts: list[dict],
    *,
    density_g_per_ml: float | int,
) -> list[dict]:
    combined = list(contexts or [])
    seen_run_ids = {
        str(dict(context.get("summary_row") or {}).get("run_id") or "")
        for context in combined
    }
    process_root = Path(experiment_root) / "calibration_recordings" / PROCESS_NAME
    if not process_root.is_dir():
        return combined
    for run_dir in sorted(path for path in process_root.iterdir() if path.is_dir()):
        run_id = run_dir.name
        if run_id in seen_run_ids:
            continue
        if not (run_dir / "frames.jsonl").exists() or not (run_dir / "tail_fit.json").exists():
            continue
        context = _context_from_online_run_dir(
            Path(experiment_root),
            run_dir,
            density_g_per_ml=density_g_per_ml,
        )
        resolved_run_id = str(dict(context.get("summary_row") or {}).get("run_id") or run_id)
        if resolved_run_id in seen_run_ids:
            continue
        combined.append(context)
        seen_run_ids.add(resolved_run_id)
    return combined


def _cv(values: list[float]) -> float | None:
    numeric = [float(value) for value in list(values or []) if _float_or_none(value) is not None]
    if not numeric:
        return None
    mean_value = statistics.mean(numeric)
    if mean_value == 0.0:
        return None
    if len(numeric) == 1:
        return 0.0
    return float(statistics.stdev(numeric) / mean_value)


def _condition_summary_row(condition_key: str, run_rows: list[dict]) -> dict:
    first = run_rows[0] if run_rows else {}
    return {
        "condition_key": condition_key,
        "print_pressure": _float_or_none(first.get("print_pressure")),
        "print_pw_us": _int_or_none(first.get("print_pw_us")),
        "run_count": len(run_rows),
        "gravimetric_per_print_nl_mean": (
            statistics.mean(
                float(row["gravimetric_per_print_nl"])
                for row in run_rows
                if _float_or_none(row.get("gravimetric_per_print_nl")) is not None
            )
            if any(_float_or_none(row.get("gravimetric_per_print_nl")) is not None for row in run_rows)
            else None
        ),
        "gravimetric_per_print_nl_cv": _cv(
            [
                float(row["gravimetric_per_print_nl"])
                for row in run_rows
                if _float_or_none(row.get("gravimetric_per_print_nl")) is not None
            ]
        ),
        "predicted_volume_nl_mean": (
            statistics.mean(
                float(row["predicted_volume_nl"])
                for row in run_rows
                if _float_or_none(row.get("predicted_volume_nl")) is not None
            )
            if any(_float_or_none(row.get("predicted_volume_nl")) is not None for row in run_rows)
            else None
        ),
        "predicted_volume_nl_cv": _cv(
            [
                float(row["predicted_volume_nl"])
                for row in run_rows
                if _float_or_none(row.get("predicted_volume_nl")) is not None
            ]
        ),
        "signed_residual_nl_mean": (
            statistics.mean(
                float(row["signed_residual_nl"])
                for row in run_rows
                if _float_or_none(row.get("signed_residual_nl")) is not None
            )
            if any(_float_or_none(row.get("signed_residual_nl")) is not None for row in run_rows)
            else None
        ),
        "predicted_to_gravimetric_ratio_mean": (
            statistics.mean(
                float(row["predicted_to_gravimetric_ratio"])
                for row in run_rows
                if _float_or_none(row.get("predicted_to_gravimetric_ratio")) is not None
            )
            if any(_float_or_none(row.get("predicted_to_gravimetric_ratio")) is not None for row in run_rows)
            else None
        ),
        "gravimetric_minus_tail_start_us_mean": (
            statistics.mean(
                float(row["gravimetric_minus_tail_start_us"])
                for row in run_rows
                if _float_or_none(row.get("gravimetric_minus_tail_start_us")) is not None
            )
            if any(_float_or_none(row.get("gravimetric_minus_tail_start_us")) is not None for row in run_rows)
            else None
        ),
        "gravimetric_after_detachment_count": sum(
            1
            for row in run_rows
            if str(row.get("gravimetric_vs_detachment_status") or "") == "after_first_detachment_landmark"
        ),
        "gravimetric_after_last_observed_tail_count": sum(
            1
            for row in run_rows
            if str(row.get("gravimetric_vs_observed_tail_status") or "") == "after_last_observed_tail_frame"
        ),
        "condition_overlay_png": None,
    }


def _summaries_from_contexts(contexts: list[dict]) -> tuple[list[dict], list[dict], dict[str, list[dict]]]:
    summary_rows = [dict(context.get("summary_row") or {}) for context in list(contexts or [])]
    grouped_contexts = defaultdict(list)
    for context in list(contexts or []):
        summary_row = dict(context.get("summary_row") or {})
        grouped_contexts[str(summary_row.get("condition_key") or "unknown")].append(context)
    condition_summary_rows = [
        _condition_summary_row(
            condition_key,
            [dict(item.get("summary_row") or {}) for item in condition_contexts],
        )
        for condition_key, condition_contexts in sorted(grouped_contexts.items())
    ]
    return summary_rows, condition_summary_rows, grouped_contexts


def _delta_or_none(left, right):
    left_value = _float_or_none(left)
    right_value = _float_or_none(right)
    if left_value is None or right_value is None:
        return None
    return float(left_value - right_value)


def _bic_score(result: dict, model_name: str):
    scores = dict(result.get("bic_scores") or {})
    return _float_or_none(scores.get(model_name))


def _segmented_tail_review_row(context: dict, result: dict, *, plot_path: Path) -> dict:
    summary = dict(context.get("summary_row") or {})
    segmented_tail_start = _int_or_none(result.get("tail_start_delay_from_emergence_us"))
    current_tail_start = _int_or_none(summary.get("tail_start_delay_from_emergence_us"))
    grav_delay = _float_or_none(summary.get("gravimetric_equality_delay_us"))
    three_break_gate = dict(result.get("three_break_selection_gate") or {})
    local_confirmation = dict(result.get("local_confirmation") or {})
    return {
        "run_id": summary.get("run_id"),
        "condition_key": summary.get("condition_key"),
        "print_pressure": _float_or_none(summary.get("print_pressure")),
        "print_pw_us": _int_or_none(summary.get("print_pw_us")),
        "replicate_index": _int_or_none(summary.get("replicate_index")),
        "current_tail_start_delay_from_emergence_us": current_tail_start,
        "segmented_tail_start_delay_from_emergence_us": segmented_tail_start,
        "segmented_knee_delay_from_emergence_us": _int_or_none(result.get("knee_delay_from_emergence_us")),
        "segmented_second_knee_delay_from_emergence_us": _int_or_none(
            result.get("second_knee_delay_from_emergence_us")
        ),
        "segmented_breakpoint_delays_from_emergence_us": [
            int(value)
            for value in list(result.get("breakpoint_delays_from_emergence_us") or [])
            if _int_or_none(value) is not None
        ],
        "segmented_breakpoint_refinement_step_us": _int_or_none(
            result.get("breakpoint_refinement_step_us")
        ),
        "segmented_tail_start_observed_delay": result.get("tail_start_observed_delay"),
        "segmented_breakpoint_observed_delays": [
            bool(value)
            for value in list(result.get("breakpoint_observed_delays") or [])
        ],
        "segmented_tail_start_source": _clean_text(result.get("tail_start_source")),
        "segmented_three_break_tail_start_delay_from_emergence_us": _int_or_none(
            result.get("three_break_tail_start_delay_from_emergence_us")
        ),
        "segmented_two_break_tail_start_delay_from_emergence_us": _int_or_none(
            result.get("two_break_tail_start_delay_from_emergence_us")
        ),
        "segmented_midpoint_tail_start_delay_from_emergence_us": _int_or_none(
            result.get("midpoint_tail_start_delay_from_emergence_us")
        ),
        "segmented_model_name": _clean_text(result.get("model_name")),
        "segmented_fit_status": _clean_text(result.get("fit_status")),
        "segmented_usable_point_count": _int_or_none(result.get("usable_point_count")),
        "segmented_noise_estimate_px": _float_or_none(result.get("noise_estimate_px")),
        "segmented_bic_plateau": _bic_score(result, segmented_tail_mod.MODEL_PLATEAU),
        "segmented_bic_plateau_decline": _bic_score(result, segmented_tail_mod.MODEL_PLATEAU_DECLINE),
        "segmented_bic_plateau_shoulder_collapse": _bic_score(
            result,
            segmented_tail_mod.MODEL_PLATEAU_SHOULDER_COLLAPSE,
        ),
        "segmented_bic_plateau_gradual_shoulder_steep_shoulder_collapse": _bic_score(
            result,
            segmented_tail_mod.MODEL_PLATEAU_GRADUAL_SHOULDER_STEEP_SHOULDER_COLLAPSE,
        ),
        "segmented_three_break_gate_passed": bool(three_break_gate.get("passed")),
        "segmented_three_break_gate_reason": _clean_text(three_break_gate.get("reason")),
        "segmented_three_break_tail_start_advance_us": _float_or_none(
            three_break_gate.get("tail_start_advance_us")
        ),
        "segmented_three_break_early_shoulder_slope_px_per_ms": _float_or_none(
            three_break_gate.get("early_shoulder_slope_px_per_ms")
        ),
        "segmented_local_confirmation_passed": bool(local_confirmation.get("passed")),
        "segmented_local_confirmation_reason": _clean_text(local_confirmation.get("reason")),
        "segmented_local_confirmation_baseline_width_px": _float_or_none(
            local_confirmation.get("baseline_width_px")
        ),
        "segmented_local_confirmation_final_drop_px": _float_or_none(
            local_confirmation.get("final_drop_px")
        ),
        "segmented_local_confirmation_rebound_px": _float_or_none(
            local_confirmation.get("rebound_px")
        ),
        "segmented_minus_current_tail_start_us": _delta_or_none(segmented_tail_start, current_tail_start),
        "gravimetric_equality_delay_us": grav_delay,
        "gravimetric_minus_segmented_tail_start_us": _delta_or_none(grav_delay, segmented_tail_start),
        "run_report_png": str(plot_path),
    }


def _segmented_tail_baseline_width(context: dict):
    fit = dict(context.get("fit") or {})
    baseline = _float_or_none(fit.get("steady_width_baseline_px"))
    if baseline is not None:
        return baseline
    flow_artifact_fit = dict(dict(context.get("flow_artifact") or {}).get("fit") or {})
    return _float_or_none(flow_artifact_fit.get("steady_width_baseline_px"))


def _write_segmented_tail_review(contexts: list[dict], *, stage_dir: Path) -> dict:
    review_dir = Path(stage_dir) / "segmented_tail_review"
    runs_dir = review_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    review_items = []
    review_rows = []
    for context in list(contexts or []):
        summary = dict(context.get("summary_row") or {})
        run_id = str(summary.get("run_id") or "run")
        result = segmented_tail_mod.evaluate_segmented_tail_trace(
            list(context.get("tail_rows") or []),
            baseline_width_px=_segmented_tail_baseline_width(context),
        )
        plot_path = runs_dir / f"{_safe_slug(run_id)}.png"
        row = _segmented_tail_review_row(context, result, plot_path=plot_path)
        _plot_segmented_tail_run(context, result, row, plot_path)
        context["segmented_tail_review"] = result
        review_rows.append(row)
        review_items.append({"context": context, "result": result, "row": row})

    run_summary_csv = review_dir / "run_summary.csv"
    run_summary_json = review_dir / "run_summary.json"
    contact_sheet_png = review_dir / "contact_sheet.png"
    dataset_mod._write_csv(run_summary_csv, SEGMENTED_TAIL_REVIEW_COLUMNS, review_rows)
    dataset_mod._write_json(run_summary_json, review_rows)
    _plot_segmented_tail_contact_sheet(review_items, contact_sheet_png)
    return {
        "segmented_tail_review_dir": str(review_dir),
        "segmented_tail_review_run_summary_csv": str(run_summary_csv),
        "segmented_tail_review_run_summary_json": str(run_summary_json),
        "segmented_tail_review_contact_sheet_png": str(contact_sheet_png),
    }


def _export_report_from_contexts(
    contexts: list[dict],
    *,
    stage_dir: Path,
    experiment_root: Path | None,
    run_id_filter: str | None = None,
    density_g_per_ml: float | int = 1.0,
    correction_mode: str | None = None,
    correction_rule: dict | None = None,
    flow_fit_policy_override: dict | None = None,
    um_per_pixel: float | None = None,
    segmented_tail_review: bool = False,
    segmented_tail_contexts: list[dict] | None = None,
) -> dict:
    stage_dir = Path(stage_dir).expanduser().resolve()
    stage_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = stage_dir / "runs"
    conditions_dir = stage_dir / "conditions"
    experiment_dir = stage_dir / "experiment"
    runs_dir.mkdir(parents=True, exist_ok=True)
    conditions_dir.mkdir(parents=True, exist_ok=True)
    experiment_dir.mkdir(parents=True, exist_ok=True)

    summary_rows, condition_summary_rows, grouped_contexts = _summaries_from_contexts(contexts)
    context_by_run_id = {
        str(dict(context.get("summary_row") or {}).get("run_id") or ""): context
        for context in list(contexts or [])
    }

    rendered_summary_rows = []
    for summary_row in summary_rows:
        rendered_row = dict(summary_row)
        run_slug = _safe_slug(rendered_row.get("run_id") or "run")
        run_report_path = runs_dir / f"{run_slug}.png"
        context = context_by_run_id.get(str(rendered_row.get("run_id") or ""))
        if context is not None:
            _plot_run_report(context, run_report_path)
            rendered_row["run_report_png"] = str(run_report_path)
            context["summary_row"] = rendered_row
        rendered_summary_rows.append(rendered_row)

    rendered_condition_rows = []
    for condition_row in condition_summary_rows:
        rendered_row = dict(condition_row)
        condition_key = str(rendered_row.get("condition_key") or "unknown")
        condition_slug = _safe_slug(condition_key)
        overlay_path = conditions_dir / f"{condition_slug}_overlay.png"
        condition_contexts = list(grouped_contexts.get(condition_key) or [])
        _plot_condition_overlay(condition_key, condition_contexts, overlay_path)
        rendered_row["condition_overlay_png"] = str(overlay_path)
        rendered_condition_rows.append(rendered_row)

    predicted_vs_gravimetric_path = experiment_dir / "predicted_vs_gravimetric.png"
    delay_gap_path = experiment_dir / "delay_gap_by_condition.png"
    _plot_predicted_vs_gravimetric(contexts, predicted_vs_gravimetric_path)
    _plot_delay_gap_by_condition(contexts, delay_gap_path)
    segmented_tail_paths = (
        _write_segmented_tail_review(
            segmented_tail_contexts if segmented_tail_contexts is not None else contexts,
            stage_dir=stage_dir,
        )
        if bool(segmented_tail_review)
        else {}
    )

    run_summary_csv = stage_dir / "run_summary.csv"
    run_summary_json = stage_dir / "run_summary.json"
    condition_summary_csv = stage_dir / "condition_summary.csv"
    condition_summary_json = stage_dir / "condition_summary.json"
    manifest_json = stage_dir / "report_manifest.json"

    dataset_mod._write_csv(run_summary_csv, RUN_SUMMARY_COLUMNS, rendered_summary_rows)
    dataset_mod._write_json(run_summary_json, rendered_summary_rows)
    dataset_mod._write_csv(condition_summary_csv, CONDITION_SUMMARY_COLUMNS, rendered_condition_rows)
    dataset_mod._write_json(condition_summary_json, rendered_condition_rows)

    manifest = {
        "schema_version": 1,
        "experiment_root": None if experiment_root is None else str(Path(experiment_root).resolve()),
        "output_root": str(stage_dir),
        "run_id_filter": None if run_id_filter is None else str(run_id_filter),
        "gravimetric_density_g_per_ml": float(_validate_density_g_per_ml(density_g_per_ml)),
        "um_per_pixel": _validate_um_per_pixel(um_per_pixel),
        "correction_mode": correction_mode,
        "correction_rule": None if correction_rule is None else dict(correction_rule),
        "flow_fit_policy_override": (
            None if flow_fit_policy_override is None else dict(flow_fit_policy_override)
        ),
        "run_count": len(rendered_summary_rows),
        "condition_count": len(rendered_condition_rows),
        "segmented_tail_review": bool(segmented_tail_review),
        "segmented_tail_review_run_count": (
            len(segmented_tail_contexts if segmented_tail_contexts is not None else contexts)
            if bool(segmented_tail_review)
            else 0
        ),
        "paths": {
            "run_summary_csv": str(run_summary_csv),
            "run_summary_json": str(run_summary_json),
            "condition_summary_csv": str(condition_summary_csv),
            "condition_summary_json": str(condition_summary_json),
            "predicted_vs_gravimetric_png": str(predicted_vs_gravimetric_path),
            "delay_gap_by_condition_png": str(delay_gap_path),
            "runs_dir": str(runs_dir),
            "conditions_dir": str(conditions_dir),
            **segmented_tail_paths,
        },
    }
    dataset_mod._write_json(manifest_json, manifest)
    return {
        **manifest,
        "summary_rows": rendered_summary_rows,
        "condition_summary_rows": rendered_condition_rows,
        "paths": {
            **manifest["paths"],
            "report_manifest_json": str(manifest_json),
        },
    }


def _import_pyplot():
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    return plt


def _add_vertical_guides(ax, guides: list[tuple[float | None, str, str, str, float]]):
    used_labels = set()
    for x_value, label, color, linestyle, linewidth in guides:
        x_value = _float_or_none(x_value)
        if x_value is None:
            continue
        label_arg = label if label not in used_labels else "_nolegend_"
        used_labels.add(label)
        ax.axvline(
            float(x_value),
            color=str(color),
            linestyle=str(linestyle),
            linewidth=float(linewidth),
            alpha=0.95,
            label=label_arg,
        )


def _segmented_tail_common_guides(summary_row: dict, review_row: dict):
    guides = [
        (
            review_row.get("segmented_tail_start_delay_from_emergence_us"),
            "segmented tail start",
            "#059669",
            "--",
            1.8,
        ),
        (
            review_row.get("segmented_knee_delay_from_emergence_us"),
            "segmented knee",
            "#0891b2",
            "-.",
            1.4,
        ),
        (
            review_row.get("segmented_second_knee_delay_from_emergence_us"),
            "segmented second knee",
            "#be123c",
            "-.",
            1.2,
        ),
        (
            summary_row.get("tail_start_delay_from_emergence_us"),
            "current tail start",
            "#7c3aed",
            "--",
            1.5,
        ),
        (
            summary_row.get("last_plateau_delay_from_emergence_us"),
            "current last plateau",
            "#0f766e",
            ":",
            1.1,
        ),
        (
            summary_row.get("confirmed_collapse_delay_from_emergence_us"),
            "current confirmed collapse",
            "#dc2626",
            "-.",
            1.2,
        ),
        (
            summary_row.get("gravimetric_equality_delay_us"),
            "grav eq timing",
            "#111827",
            ":",
            1.4,
        ),
    ]
    if (
        _clean_text(review_row.get("segmented_tail_start_source"))
        == segmented_tail_mod.TAIL_START_SOURCE_THREE_TWO_MIDPOINT
    ):
        guides.extend(
            [
                (
                    review_row.get("segmented_three_break_tail_start_delay_from_emergence_us"),
                    "three-break tau1",
                    "#86efac",
                    ":",
                    1.0,
                ),
                (
                    review_row.get("segmented_two_break_tail_start_delay_from_emergence_us"),
                    "two-break tau1",
                    "#94a3b8",
                    ":",
                    1.0,
                ),
            ]
        )
    return guides


def _raw_tail_width_points(tail_rows: list[dict]) -> list[tuple[float, float]]:
    points = []
    for row in list(tail_rows or []):
        delay = _float_or_none(dict(row or {}).get("delay_from_emergence_us"))
        width = _float_or_none(dict(row or {}).get("attached_width_px"))
        if delay is None or width is None:
            continue
        points.append((float(delay), float(width)))
    return sorted(points)


def _plot_segmented_tail_run(context: dict, result: dict, review_row: dict, output_path: Path):
    plt = _import_pyplot()

    summary_row = dict(context.get("summary_row") or {})
    tail_rows = list(context.get("tail_rows") or [])
    raw_points = _raw_tail_width_points(tail_rows)
    median_trace = list(result.get("trace") or [])
    fit_points = list(result.get("fit_points") or [])
    guides = _segmented_tail_common_guides(summary_row, review_row)

    fig, ax = plt.subplots(1, 1, figsize=(11, 6))
    if raw_points:
        ax.scatter(
            [x for x, _y in raw_points],
            [y for _x, y in raw_points],
            color="#d1d5db",
            edgecolors="#6b7280",
            s=26,
            linewidths=0.5,
            label="recorded width frames",
            zorder=2,
        )
    if median_trace:
        ax.plot(
            [float(row["delay_from_emergence_us"]) for row in median_trace],
            [float(row["median_width_px"]) for row in median_trace],
            color="#d97706",
            marker="o",
            markersize=4,
            linewidth=1.5,
            label="median fit trace",
            zorder=4,
        )
    if fit_points:
        ax.plot(
            [float(row["delay_from_emergence_us"]) for row in fit_points],
            [float(row["fitted_width_px"]) for row in fit_points],
            color="#059669",
            linewidth=2.2,
            label="segmented regression",
            zorder=5,
        )

    bottom_guard_points = [
        (
            _float_or_none(row.get("delay_from_emergence_us")),
            _float_or_none(row.get("attached_width_px")),
        )
        for row in tail_rows
        if bool(row.get("attached_bottom_guard_hit"))
    ]
    bottom_guard_points = [
        (float(x), float(y)) for x, y in bottom_guard_points if x is not None and y is not None
    ]
    if bottom_guard_points:
        ax.scatter(
            [x for x, _y in bottom_guard_points],
            [y for _x, y in bottom_guard_points],
            facecolors="none",
            edgecolors="#dc2626",
            s=54,
            linewidths=1.0,
            label="bottom-guard hit",
            zorder=6,
        )

    detachment_points = [
        (
            _float_or_none(row.get("delay_from_emergence_us")),
            _float_or_none(row.get("attached_width_px")),
        )
        for row in tail_rows
        if _tail_detachment_predicate(row)
    ]
    detachment_points = [
        (float(x), float(y)) for x, y in detachment_points if x is not None and y is not None
    ]
    if detachment_points:
        ax.scatter(
            [x for x, _y in detachment_points],
            [y for _x, y in detachment_points],
            color="#111827",
            marker="x",
            s=48,
            label="detachment-like frame",
            zorder=7,
        )

    grav_low = _float_or_none(summary_row.get("gravimetric_equality_delay_low_us"))
    grav_high = _float_or_none(summary_row.get("gravimetric_equality_delay_high_us"))
    if grav_low is not None and grav_high is not None and grav_high > grav_low:
        ax.axvspan(float(grav_low), float(grav_high), color="#111827", alpha=0.09, label="grav eq 95% band")
    _add_vertical_guides(ax, guides)

    fit_status = review_row.get("segmented_fit_status") or "n/a"
    model_name = review_row.get("segmented_model_name") or "n/a"
    segmented_tail = review_row.get("segmented_tail_start_delay_from_emergence_us")
    current_tail = review_row.get("current_tail_start_delay_from_emergence_us")
    ax.set_title(
        f"{summary_row.get('run_id')} | {summary_row.get('condition_key')} | "
        f"{model_name} ({fit_status}) | segmented {segmented_tail} us vs current {current_tail} us",
        fontsize=11,
    )
    ax.set_xlabel("Delay from emergence (us)")
    ax.set_ylabel("Attached width (px)")
    ax.grid(alpha=0.22)
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(handles, labels, fontsize=8, loc="best")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def _plot_segmented_tail_contact_sheet(review_items: list[dict], output_path: Path):
    plt = _import_pyplot()

    items = list(review_items or [])
    if not items:
        fig, ax = plt.subplots(1, 1, figsize=(8, 3))
        ax.text(0.5, 0.5, "No segmented tail review rows", ha="center", va="center")
        ax.axis("off")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=160)
        plt.close(fig)
        return

    column_count = min(3, max(1, len(items)))
    row_count = int(math.ceil(len(items) / float(column_count)))
    fig, axes = plt.subplots(row_count, column_count, figsize=(5.2 * column_count, 3.4 * row_count), squeeze=False)
    for ax in axes.flatten():
        ax.axis("off")

    for index, item in enumerate(items):
        ax = axes[index // column_count][index % column_count]
        ax.axis("on")
        context = dict(item.get("context") or {})
        result = dict(item.get("result") or {})
        row = dict(item.get("row") or {})
        summary = dict(context.get("summary_row") or {})
        trace = list(result.get("trace") or [])
        fit_points = list(result.get("fit_points") or [])
        if trace:
            ax.plot(
                [float(point["delay_from_emergence_us"]) for point in trace],
                [float(point["median_width_px"]) for point in trace],
                color="#d97706",
                marker="o",
                markersize=2.8,
                linewidth=1.1,
            )
        if fit_points:
            ax.plot(
                [float(point["delay_from_emergence_us"]) for point in fit_points],
                [float(point["fitted_width_px"]) for point in fit_points],
                color="#059669",
                linewidth=1.6,
            )
        for x_value, _label, color, linestyle, linewidth in _segmented_tail_common_guides(summary, row):
            if _float_or_none(x_value) is not None:
                ax.axvline(float(x_value), color=color, linestyle=linestyle, linewidth=linewidth, alpha=0.85)
        ax.set_title(
            f"{summary.get('run_id')}\n{row.get('segmented_model_name') or 'n/a'} | "
            f"seg {row.get('segmented_tail_start_delay_from_emergence_us')}",
            fontsize=8,
        )
        ax.grid(alpha=0.18)
        ax.tick_params(labelsize=7)

    fig.suptitle("Segmented Tail Start Review", fontsize=13)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.97))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def _plot_run_report(context: dict, output_path: Path):
    plt = _import_pyplot()

    summary_row = dict(context.get("summary_row") or {})
    fit = dict(context.get("fit") or {})
    flow_volume_points = list(context.get("flow_volume_points") or [])
    tail_volume_points = list(context.get("tail_volume_points") or [])
    tail_rejected_volume_points = list(context.get("tail_rejected_volume_points") or [])
    width_points = list(context.get("width_points") or [])
    clearance_points = list(context.get("clearance_points") or [])
    tail_rows = list(context.get("tail_rows") or [])

    x_candidates = [x for x, _y in flow_volume_points + tail_rejected_volume_points + width_points + clearance_points]
    x_candidates.extend(
        [
            _float_or_none(summary_row.get("tail_start_delay_from_emergence_us")),
            _float_or_none(summary_row.get("initial_confirmed_collapse_delay_from_emergence_us")),
            _float_or_none(summary_row.get("confirmed_collapse_delay_from_emergence_us")),
            _float_or_none(summary_row.get("last_plateau_delay_from_emergence_us")),
            _float_or_none(summary_row.get("gravimetric_equality_delay_us")),
            _float_or_none(summary_row.get("gravimetric_equality_delay_low_us")),
            _float_or_none(summary_row.get("gravimetric_equality_delay_high_us")),
            _float_or_none(summary_row.get("first_tail_detachment_delay_from_emergence_us")),
        ]
    )
    x_numeric = [float(value) for value in x_candidates if _float_or_none(value) is not None]
    x_min = min(x_numeric) if x_numeric else 0.0
    x_max = max(x_numeric) if x_numeric else 1.0

    fig, (ax_volume, ax_width, ax_clearance) = plt.subplots(
        3,
        1,
        figsize=(12, 10),
        sharex=True,
        gridspec_kw={"height_ratios": [2.1, 1.5, 1.2]},
    )

    fit_line = _flow_fit_lines(fit, x_min=x_min, x_max=x_max)
    if fit_line and fit_line.get("band"):
        ax_volume.fill_between(
            fit_line["x"],
            fit_line["band"]["lower"],
            fit_line["band"]["upper"],
            color="#bfdbfe",
            alpha=0.4,
            label="flow fit 95% CI",
        )
    if fit_line:
        ax_volume.plot(
            fit_line["x"],
            fit_line["y"],
            color="#1d4ed8",
            linewidth=2.0,
            label="flow fit",
        )

    if flow_volume_points:
        ax_volume.scatter(
            [x for x, _y in flow_volume_points],
            [y for _x, y in flow_volume_points],
            color="#2563eb",
            s=28,
            label="accepted flow points",
            zorder=3,
        )
    if tail_rejected_volume_points:
        ax_volume.plot(
            [x for x, _y in tail_rejected_volume_points],
            [y for _x, y in tail_rejected_volume_points],
            color="#9ca3af",
            linewidth=1.1,
            alpha=0.7,
            label="all tail points",
        )
        rejected_only = [
            (x, y)
            for x, y in tail_rejected_volume_points
            if (x, y) not in set(tail_volume_points)
        ]
        if rejected_only:
            ax_volume.scatter(
                [x for x, _y in rejected_only],
                [y for _x, y in rejected_only],
                color="#6b7280",
                marker="x",
                s=28,
                label="rejected tail points",
                zorder=3,
            )
    if tail_volume_points:
        ax_volume.scatter(
            [x for x, _y in tail_volume_points],
            [y for _x, y in tail_volume_points],
            color="#ea580c",
            s=30,
            label="accepted tail points",
            zorder=4,
        )

    gravimetric_volume = _float_or_none(summary_row.get("gravimetric_per_print_nl"))
    predicted_volume = _float_or_none(summary_row.get("predicted_volume_nl"))
    grav_delay = _float_or_none(summary_row.get("gravimetric_equality_delay_us"))
    grav_low = _float_or_none(summary_row.get("gravimetric_equality_delay_low_us"))
    grav_high = _float_or_none(summary_row.get("gravimetric_equality_delay_high_us"))
    tail_start_delay = _float_or_none(summary_row.get("tail_start_delay_from_emergence_us"))
    initial_confirmed_collapse_delay = _float_or_none(
        summary_row.get("initial_confirmed_collapse_delay_from_emergence_us")
    )
    confirmed_collapse_delay = _float_or_none(summary_row.get("confirmed_collapse_delay_from_emergence_us"))
    last_plateau_delay = _float_or_none(summary_row.get("last_plateau_delay_from_emergence_us"))
    first_detachment_delay = _float_or_none(summary_row.get("first_tail_detachment_delay_from_emergence_us"))

    if grav_low is not None and grav_high is not None and grav_high > grav_low:
        ax_volume.axvspan(
            float(grav_low),
            float(grav_high),
            color="#111827",
            alpha=0.09,
            label="grav eq 95% band",
        )
    if gravimetric_volume is not None:
        ax_volume.axhline(
            float(gravimetric_volume),
            color="#111827",
            linestyle=":",
            linewidth=1.2,
            label="gravimetric volume",
        )
    if predicted_volume is not None:
        ax_volume.axhline(
            float(predicted_volume),
            color="#7c3aed",
            linestyle="--",
            linewidth=1.0,
            label="predicted volume",
        )

    predicted_point_y = _interp(tail_rejected_volume_points or flow_volume_points, tail_start_delay)
    if predicted_point_y is None and fit_line and tail_start_delay is not None:
        slope = _float_or_none(fit.get("flow_rate_nl_per_us"))
        intercept = _float_or_none(fit.get("flow_intercept_nl"))
        if slope is not None and intercept is not None:
            predicted_point_y = float(intercept) + float(slope) * float(tail_start_delay)
    if tail_start_delay is not None and predicted_point_y is not None:
        ax_volume.scatter(
            [float(tail_start_delay)],
            [float(predicted_point_y)],
            color="#7c3aed",
            s=90,
            marker="o",
            edgecolors="white",
            linewidths=0.8,
            label="predicted tail start",
            zorder=5,
        )

    grav_eq_point_y = None
    if grav_delay is not None and gravimetric_volume is not None:
        grav_eq_point_y = float(gravimetric_volume)
    elif grav_delay is not None and fit_line:
        slope = _float_or_none(fit.get("flow_rate_nl_per_us"))
        intercept = _float_or_none(fit.get("flow_intercept_nl"))
        if slope is not None and intercept is not None:
            grav_eq_point_y = float(intercept) + float(slope) * float(grav_delay)
    if grav_delay is not None and grav_eq_point_y is not None:
        ax_volume.scatter(
            [float(grav_delay)],
            [float(grav_eq_point_y)],
            color="#111827",
            s=110,
            marker="*",
            label="grav eq timing",
            zorder=6,
        )

    common_guides = [
        (tail_start_delay, "tail start", "#7c3aed", "--", 1.5),
        (
            initial_confirmed_collapse_delay
            if initial_confirmed_collapse_delay != confirmed_collapse_delay
            else None,
            "initial confirmed collapse",
            "#f97316",
            ":",
            1.0,
        ),
        (confirmed_collapse_delay, "confirmed collapse", "#dc2626", "-.", 1.2),
        (last_plateau_delay, "last plateau", "#0f766e", ":", 1.2),
        (first_detachment_delay, "first detachment-like landmark", "#b91c1c", "--", 1.2),
        (grav_delay, "grav eq timing", "#111827", ":", 1.5),
    ]
    _add_vertical_guides(ax_volume, common_guides)

    if width_points:
        ax_width.plot(
            [x for x, _y in width_points],
            [y for _x, y in width_points],
            color="#d97706",
            linewidth=1.6,
            marker="o",
            markersize=3.0,
            label="attached width",
        )
    bg_width_points = [
        (float(delay), float(width))
        for delay, width in width_points
        if any(
            _float_or_none(row.get("delay_from_emergence_us")) == float(delay)
            and bool(row.get("attached_bottom_guard_hit"))
            and _float_or_none(row.get("attached_width_px")) == float(width)
            for row in tail_rows
        )
    ]
    if bg_width_points:
        ax_width.scatter(
            [x for x, _y in bg_width_points],
            [y for _x, y in bg_width_points],
            facecolors="none",
            edgecolors="#dc2626",
            s=48,
            linewidths=1.0,
            label="bottom-guard hit",
            zorder=5,
        )
    detachment_width_points = [
        (
            _float_or_none(row.get("delay_from_emergence_us")),
            _float_or_none(row.get("attached_width_px")),
        )
        for row in tail_rows
        if _tail_detachment_predicate(row)
    ]
    detachment_width_points = [
        (float(x), float(y))
        for x, y in detachment_width_points
        if x is not None and y is not None
    ]
    if detachment_width_points:
        ax_width.scatter(
            [x for x, _y in detachment_width_points],
            [y for _x, y in detachment_width_points],
            color="#111827",
            marker="x",
            s=46,
            label="detachment-like frames",
            zorder=5,
        )
    _add_vertical_guides(ax_width, common_guides)
    if grav_low is not None and grav_high is not None and grav_high > grav_low:
        ax_width.axvspan(float(grav_low), float(grav_high), color="#111827", alpha=0.09, label="grav eq 95% band")

    if clearance_points:
        ax_clearance.plot(
            [x for x, _y in clearance_points],
            [y for _x, y in clearance_points],
            color="#0f766e",
            linewidth=1.5,
            marker="o",
            markersize=3.0,
            label="bottom clearance",
        )
    bottom_guard_px = _float_or_none(
        online_cal_mod.DEFAULT_ONLINE_STREAM_ANALYSIS_CONFIG.get("attached_bottom_guard_px")
    )
    if bottom_guard_px is not None:
        ax_clearance.axhline(
            float(bottom_guard_px),
            color="#dc2626",
            linestyle="--",
            linewidth=1.1,
            label="bottom-guard threshold",
        )
    _add_vertical_guides(ax_clearance, common_guides)
    if grav_low is not None and grav_high is not None and grav_high > grav_low:
        ax_clearance.axvspan(
            float(grav_low),
            float(grav_high),
            color="#111827",
            alpha=0.09,
            label="grav eq 95% band",
        )

    condition_text = (
        f"{summary_row.get('print_pressure'):0.3f} psi, {int(summary_row.get('print_pw_us'))} us"
        if _float_or_none(summary_row.get("print_pressure")) is not None
        and _int_or_none(summary_row.get("print_pw_us")) is not None
        else str(summary_row.get("condition_key") or "unknown condition")
    )
    residual_text = (
        f"residual {float(summary_row['signed_residual_nl']):0.2f} nL"
        if _float_or_none(summary_row.get("signed_residual_nl")) is not None
        else "residual n/a"
    )
    status_text = str(summary_row.get("gravimetric_vs_detachment_status") or "status n/a")
    fig.suptitle(f"{summary_row.get('run_id')} | {condition_text} | {residual_text} | {status_text}", fontsize=12)

    ax_volume.set_ylabel("Visible volume (nL)")
    ax_width.set_ylabel("Attached width (px)")
    ax_clearance.set_ylabel("Bottom clearance (px)")
    ax_clearance.set_xlabel("Delay from emergence (us)")

    for axis, title in [
        (ax_volume, "V(t) flow fit and tail timing"),
        (ax_width, "Width trace with predicted vs gravimetric timing"),
        (ax_clearance, "Late-frame bottom clearance"),
    ]:
        axis.set_title(title, fontsize=10)
        axis.grid(alpha=0.22)
        handles, labels = axis.get_legend_handles_labels()
        if handles:
            axis.legend(handles, labels, fontsize=8, loc="best")

    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.97))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def _plot_condition_overlay(condition_key: str, contexts: list[dict], output_path: Path):
    plt = _import_pyplot()

    palette = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed", "#0891b2", "#be123c", "#4f46e5"]
    fig, (ax_volume, ax_width, ax_shift) = plt.subplots(
        3,
        1,
        figsize=(12, 10),
        sharex=False,
        gridspec_kw={"height_ratios": [2.0, 1.7, 1.2]},
    )

    shift_labels = []
    shift_values = []
    for index, context in enumerate(sorted(contexts, key=lambda item: _int_or_none(item["summary_row"].get("replicate_index")) or 10**9)):
        summary_row = dict(context.get("summary_row") or {})
        color = palette[index % len(palette)]
        run_label = f"rep {summary_row.get('replicate_index')}" if summary_row.get("replicate_index") is not None else str(summary_row.get("run_id"))

        flow_volume_points = list(context.get("flow_volume_points") or [])
        tail_volume_points = list(context.get("tail_volume_points") or [])
        width_points = list(context.get("width_points") or [])

        if flow_volume_points:
            ax_volume.plot(
                [x for x, _y in flow_volume_points],
                [y for _x, y in flow_volume_points],
                color=color,
                linewidth=1.4,
                alpha=0.9,
                label=f"{run_label} flow",
            )
        if tail_volume_points:
            ax_volume.plot(
                [x for x, _y in tail_volume_points],
                [y for _x, y in tail_volume_points],
                color=color,
                linewidth=1.2,
                linestyle="--",
                alpha=0.9,
                label=f"{run_label} tail",
            )
        if width_points:
            ax_width.plot(
                [x for x, _y in width_points],
                [y for _x, y in width_points],
                color=color,
                linewidth=1.4,
                alpha=0.95,
                label=run_label,
            )

        tail_start_delay = _float_or_none(summary_row.get("tail_start_delay_from_emergence_us"))
        grav_delay = _float_or_none(summary_row.get("gravimetric_equality_delay_us"))
        grav_low = _float_or_none(summary_row.get("gravimetric_equality_delay_low_us"))
        grav_high = _float_or_none(summary_row.get("gravimetric_equality_delay_high_us"))

        if tail_start_delay is not None:
            ax_width.axvline(float(tail_start_delay), color=color, linestyle="--", linewidth=1.0, alpha=0.7)
            ax_volume.axvline(float(tail_start_delay), color=color, linestyle="--", linewidth=0.9, alpha=0.45)
        if grav_delay is not None:
            ax_width.axvline(float(grav_delay), color=color, linestyle=":", linewidth=1.1, alpha=0.9)
            ax_volume.axvline(float(grav_delay), color=color, linestyle=":", linewidth=0.9, alpha=0.5)
        if grav_low is not None and grav_high is not None and grav_high > grav_low:
            ax_width.axvspan(float(grav_low), float(grav_high), color=color, alpha=0.05)
            ax_volume.axvspan(float(grav_low), float(grav_high), color=color, alpha=0.04)

        shift_labels.append(run_label)
        shift_values.append(_float_or_none(summary_row.get("gravimetric_minus_tail_start_us")))

    valid_shifts = [(label, value) for label, value in zip(shift_labels, shift_values) if value is not None]
    if valid_shifts:
        ax_shift.bar(
            [label for label, _value in valid_shifts],
            [float(value) for _label, value in valid_shifts],
            color="#475569",
            alpha=0.85,
        )
        ax_shift.axhline(0.0, color="#111827", linestyle=":", linewidth=1.0)
        ax_shift.set_ylabel("Grav eq - tail start (us)")
    else:
        ax_shift.text(0.5, 0.5, "No shift values available", transform=ax_shift.transAxes, ha="center", va="center")

    ax_volume.set_title(f"{condition_key}: replicate overlay V(t)", fontsize=10)
    ax_width.set_title(f"{condition_key}: replicate overlay width traces", fontsize=10)
    ax_shift.set_title(f"{condition_key}: required tail-start shift by replicate", fontsize=10)
    ax_volume.set_ylabel("Visible volume (nL)")
    ax_width.set_ylabel("Attached width (px)")
    ax_width.set_xlabel("Delay from emergence (us)")
    ax_shift.set_xlabel("Replicate")

    for axis in (ax_volume, ax_width, ax_shift):
        axis.grid(alpha=0.22)
        handles, labels = axis.get_legend_handles_labels()
        if handles:
            axis.legend(handles, labels, fontsize=8, loc="best")

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def _plot_predicted_vs_gravimetric(contexts: list[dict], output_path: Path):
    plt = _import_pyplot()

    palette = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed", "#0891b2"]
    grouped = defaultdict(list)
    for context in contexts:
        grouped[str(context["summary_row"].get("condition_key") or "unknown")].append(context)

    fig, ax = plt.subplots(figsize=(7.5, 6.5))
    numeric_pairs = []
    for index, (condition_key, rows) in enumerate(sorted(grouped.items())):
        color = palette[index % len(palette)]
        x_values = []
        y_values = []
        for context in rows:
            summary_row = dict(context.get("summary_row") or {})
            predicted = _float_or_none(summary_row.get("predicted_volume_nl"))
            gravimetric = _float_or_none(summary_row.get("gravimetric_per_print_nl"))
            if predicted is None or gravimetric is None:
                continue
            x_values.append(float(predicted))
            y_values.append(float(gravimetric))
            numeric_pairs.append((float(predicted), float(gravimetric)))
        if x_values:
            ax.scatter(x_values, y_values, s=42, color=color, alpha=0.9, label=condition_key)

    if numeric_pairs:
        axis_min = min(min(x, y) for x, y in numeric_pairs)
        axis_max = max(max(x, y) for x, y in numeric_pairs)
        ax.plot([axis_min, axis_max], [axis_min, axis_max], color="#111827", linestyle=":", linewidth=1.2, label="parity")

    ax.set_title("Predicted vs gravimetric volume", fontsize=11)
    ax.set_xlabel("Predicted volume (nL)")
    ax.set_ylabel("Gravimetric volume (nL)")
    ax.grid(alpha=0.22)
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(handles, labels, fontsize=8, loc="best")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def _plot_delay_gap_by_condition(contexts: list[dict], output_path: Path):
    plt = _import_pyplot()

    grouped = defaultdict(list)
    for context in contexts:
        summary_row = dict(context.get("summary_row") or {})
        grouped[str(summary_row.get("condition_key") or "unknown")].append(summary_row)

    condition_keys = sorted(grouped)
    fig, ax = plt.subplots(figsize=(10, 5.5))
    x_positions = list(range(len(condition_keys)))

    for x_position, condition_key in zip(x_positions, condition_keys):
        rows = grouped[condition_key]
        shifts = [
            float(row["gravimetric_minus_tail_start_us"])
            for row in rows
            if _float_or_none(row.get("gravimetric_minus_tail_start_us")) is not None
        ]
        if shifts:
            ax.scatter(
                [x_position] * len(shifts),
                shifts,
                color="#1d4ed8",
                s=42,
                alpha=0.9,
            )
            mean_shift = statistics.mean(shifts)
            ax.plot([x_position - 0.18, x_position + 0.18], [mean_shift, mean_shift], color="#111827", linewidth=2.0)

        detachment_gaps = [
            float(row["gravimetric_minus_first_detachment_us"])
            for row in rows
            if _float_or_none(row.get("gravimetric_minus_first_detachment_us")) is not None
        ]
        if detachment_gaps:
            ax.scatter(
                [x_position + 0.12] * len(detachment_gaps),
                detachment_gaps,
                color="#dc2626",
                marker="x",
                s=44,
                alpha=0.85,
            )

    ax.axhline(0.0, color="#111827", linestyle=":", linewidth=1.1)
    ax.set_xticks(x_positions)
    ax.set_xticklabels(condition_keys, rotation=20, ha="right")
    ax.set_ylabel("Delay difference (us)")
    ax.set_title("Required shift beyond selected tail start and detachment landmarks", fontsize=11)
    ax.grid(alpha=0.22, axis="y")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def export_online_stream_experiment_report(
    experiment_root: str | Path,
    *,
    output_root: str | Path | None = None,
    run_id: str | None = None,
    density_g_per_ml: float | int = 1.0,
    correction_mode: str | None = None,
    um_per_pixel: float | int | None = None,
    settling_aware_fit_enabled: bool | None = None,
    tail_settling_rule_enabled: bool | None = None,
    segmented_tail_review: bool = False,
):
    experiment_root = dataset_mod.resolve_experiment_root(experiment_root)
    density_g_per_ml = _validate_density_g_per_ml(density_g_per_ml)
    um_per_pixel = _validate_um_per_pixel(um_per_pixel)
    correction_mode = _normalized_correction_mode(correction_mode)
    analysis_config_override = {}
    if settling_aware_fit_enabled is not None:
        analysis_config_override["settling_aware_fit_enabled"] = bool(settling_aware_fit_enabled)
    if tail_settling_rule_enabled is not None:
        analysis_config_override["tail_settling_rule_enabled"] = bool(tail_settling_rule_enabled)
    flow_fit_policy_override = analysis_config_override or None
    stage_dir = (
        Path(output_root).expanduser().resolve()
        if output_root is not None
        else experiment_root / "analysis" / _default_stage_dirname(correction_mode)
    )

    metadata_rows = []
    for row in _metadata_rows(experiment_root):
        process_name = _clean_text(row.get("Capture Process")) or PROCESS_NAME
        if process_name != PROCESS_NAME:
            continue
        if run_id is not None and _clean_text(row.get("Dataset name")) != str(run_id):
            continue
        metadata_rows.append(row)

    if not metadata_rows:
        raise ValueError(
            f"No {PROCESS_NAME} metadata rows found under {experiment_root}"
            + (f" for run_id={run_id!r}" if run_id is not None else "")
        )

    correction_cache = None
    if correction_mode in {CORRECTION_MODE_CHROMA_EDGE_V2, CORRECTION_MODE_RUNTIME_RGB_FIX}:
        correction_cache = {}
    contexts = [
        _run_context(
            experiment_root,
            row,
            density_g_per_ml=density_g_per_ml,
            correction_mode=correction_mode,
            correction_cache=correction_cache,
            flow_fit_policy_override=flow_fit_policy_override,
            um_per_pixel=um_per_pixel,
        )
        for row in metadata_rows
    ]
    segmented_tail_contexts = (
        _segmented_tail_contexts_with_unlisted_runs(
            experiment_root,
            contexts,
            density_g_per_ml=density_g_per_ml,
        )
        if bool(segmented_tail_review)
        else None
    )
    return _export_report_from_contexts(
        contexts,
        stage_dir=stage_dir,
        experiment_root=experiment_root,
        run_id_filter=run_id,
        density_g_per_ml=density_g_per_ml,
        correction_mode=correction_mode,
        flow_fit_policy_override=flow_fit_policy_override,
        um_per_pixel=um_per_pixel,
        segmented_tail_review=segmented_tail_review,
        segmented_tail_contexts=segmented_tail_contexts,
        correction_rule=(
            dict(chroma_proto_mod.SELECTED_V2_RULE)
            if correction_mode == CORRECTION_MODE_CHROMA_EDGE_V2
            else (
                {
                    "replay_source": "saved_images",
                    "frame_color_order": "bgr",
                    "live_runtime_frame_color_order": "rgb",
                }
                if correction_mode == CORRECTION_MODE_RUNTIME_RGB_FIX
                else None
            )
        ),
    )
