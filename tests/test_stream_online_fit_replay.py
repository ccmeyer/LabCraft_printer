import csv
import importlib
import sys
from pathlib import Path

import pytest

from tools.stream_analysis import online_calibration as online_cal_mod
from tools.stream_analysis import online_fit as online_fit_mod


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = (
    REPO_ROOT
    / "FreeRTOS-interface"
    / "Experiments"
    / "Stream_characterization-20260327_225650"
)
SUMMARY_CSV = EXPERIMENT_ROOT / "analysis" / "stream_characterization" / "experiment_summary.csv"
SCHEDULE_OFFSETS_US = online_cal_mod.build_online_stream_flow_plan(
    emergence_time_us=0
)["delay_offsets_from_emergence_us"]


def _read_csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _to_int(value):
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except Exception:
        return None


def _to_float(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _feature_row_is_stage3_accepted(row: dict) -> bool:
    return bool(
        str(row.get("silhouette_status") or "") == "ok"
        and _to_float(row.get("attached_near_nozzle_width_median_px")) is not None
        and _to_float(row.get("total_visible_volume_nl")) is not None
        and (_to_float(row.get("min_accepted_fluid_distance_from_bottom_px")) or 0.0) > 96.0
    )


def _build_sparse_replay_inputs(run_id: str):
    phase_features_path = (
        EXPERIMENT_ROOT
        / "analysis"
        / "stream_characterization"
        / "runs"
        / run_id
        / "stage_05_fit"
        / "phase_features.csv"
    )
    if not phase_features_path.exists():
        return None

    rows_by_delay = {}
    for row in _read_csv_rows(phase_features_path):
        delay_from_emergence_us = _to_int(row.get("delay_from_emergence_us"))
        if delay_from_emergence_us is not None and delay_from_emergence_us not in rows_by_delay:
            rows_by_delay[delay_from_emergence_us] = row

    available_offsets = sorted(int(offset) for offset in rows_by_delay.keys())

    def _select_feature_row(target_offset_us: int, *, minimum_offset_us: int | None) -> tuple[int | None, dict | None]:
        exact_row = rows_by_delay.get(int(target_offset_us))
        if exact_row is not None:
            exact_offset_us = int(target_offset_us)
            if minimum_offset_us is None or exact_offset_us > int(minimum_offset_us):
                return exact_offset_us, exact_row

        candidate_offsets = []
        for offset_us in available_offsets:
            if minimum_offset_us is not None and int(offset_us) <= int(minimum_offset_us):
                continue
            if abs(int(offset_us) - int(target_offset_us)) <= 35:
                candidate_offsets.append(int(offset_us))
        if not candidate_offsets:
            return None, None
        best_offset_us = min(
            candidate_offsets,
            key=lambda offset_us: (abs(int(offset_us) - int(target_offset_us)), int(offset_us)),
        )
        return int(best_offset_us), rows_by_delay.get(int(best_offset_us))

    measurements = []
    delay_summaries = []
    previous_selected_offset_us = None
    for offset_us in list(SCHEDULE_OFFSETS_US):
        selected_offset_us, feature_row = _select_feature_row(
            int(offset_us),
            minimum_offset_us=previous_selected_offset_us,
        )
        if feature_row is None or selected_offset_us is None:
            continue
        previous_selected_offset_us = int(selected_offset_us)
        delay_us = _to_int(feature_row.get("flash_delay_us"))
        if delay_us is None:
            continue
        capture_id = str(feature_row.get("capture_id") or f"{run_id}_{selected_offset_us}")
        if _feature_row_is_stage3_accepted(feature_row):
            frame_rows = [
                online_cal_mod.build_online_stream_frame_row(
                    phase="flow_rate",
                    status="accepted",
                    delay_us=delay_us,
                    delay_from_emergence_us=int(selected_offset_us),
                    replicate_index=1,
                    qc={"measurement_qc_pass": True},
                    image_ref={"capture_id": capture_id},
                    warnings=[],
                    attached_width_px=_to_float(feature_row.get("attached_near_nozzle_width_median_px")),
                    visible_volume_nl=_to_float(feature_row.get("total_visible_volume_nl")),
                    attached_bottom_clearance_px=_to_float(
                        feature_row.get("min_accepted_fluid_distance_from_bottom_px")
                    ),
                    min_accepted_fluid_distance_from_bottom_px=_to_float(
                        feature_row.get("min_accepted_fluid_distance_from_bottom_px")
                    ),
                    accepted_component_count=_to_int(feature_row.get("accepted_component_count")) or 0,
                    accepted_detached_component_count=_to_int(
                        feature_row.get("accepted_detached_component_count")
                    )
                    or 0,
                    detached_near_bottom_warning=False,
                    attached_bottom_guard_hit=False,
                )
            ]
            measurements.append(
                online_cal_mod.build_online_stream_measurement_row(
                    phase="flow_rate",
                    delay_us=delay_us,
                    delay_from_emergence_us=int(selected_offset_us),
                    replicate_index=1,
                    width_px=_to_float(feature_row.get("attached_near_nozzle_width_median_px")),
                    visible_volume_nl=_to_float(feature_row.get("total_visible_volume_nl")),
                    qc_pass=True,
                    image_ref={"capture_id": capture_id},
                )
            )
        else:
            frame_rows = [
                online_cal_mod.build_online_stream_frame_row(
                    phase="flow_rate",
                    status="rejected_replay_qc",
                    delay_us=delay_us,
                    delay_from_emergence_us=int(selected_offset_us),
                    replicate_index=1,
                    qc={"measurement_qc_pass": False},
                    image_ref={"capture_id": capture_id},
                    warnings=["replay_qc_failed"],
                    attached_width_px=_to_float(feature_row.get("attached_near_nozzle_width_median_px")),
                    visible_volume_nl=_to_float(feature_row.get("total_visible_volume_nl")),
                    attached_bottom_clearance_px=_to_float(
                        feature_row.get("min_accepted_fluid_distance_from_bottom_px")
                    ),
                    min_accepted_fluid_distance_from_bottom_px=_to_float(
                        feature_row.get("min_accepted_fluid_distance_from_bottom_px")
                    ),
                    accepted_component_count=_to_int(feature_row.get("accepted_component_count")) or 0,
                    accepted_detached_component_count=_to_int(
                        feature_row.get("accepted_detached_component_count")
                    )
                    or 0,
                    detached_near_bottom_warning=False,
                    attached_bottom_guard_hit=False,
                )
            ]
        delay_summaries.append(online_cal_mod.summarize_online_stream_flow_delay(frame_rows))

    return measurements, delay_summaries


def test_sparse_online_flow_fit_replay_matches_dense_offline_rates():
    if not SUMMARY_CSV.exists():
        pytest.skip("Archived stream-analysis experiment summary is not available.")

    for module_name in ("scipy", "scipy.optimize", "scipy.signal", "scipy.stats", "scipy.ndimage"):
        sys.modules.pop(module_name, None)
    pytest.importorskip("scipy.stats")
    fit_module = importlib.reload(online_fit_mod)
    errors = []
    for row in _read_csv_rows(SUMMARY_CSV):
        if str(row.get("analysis_source_mode") or "") != "raw":
            continue
        if str(row.get("steady_fit_status") or "") != "ok":
            continue
        gold_rate = _to_float(row.get("steady_rate_nl_per_us"))
        run_id = str(row.get("run_id") or "").strip()
        if not run_id or gold_rate in (None, 0.0):
            continue
        replay_inputs = _build_sparse_replay_inputs(run_id)
        if replay_inputs is None:
            continue
        measurements, delay_summaries = replay_inputs
        result = fit_module.fit_online_stream_flow_phase(
            measurements=measurements,
            delay_summaries=delay_summaries,
        )
        fitted_rate = _to_float(result.get("flow_rate_nl_per_us"))
        if fitted_rate is None:
            continue
        errors.append(abs(float(fitted_rate) - float(gold_rate)) / abs(float(gold_rate)))

    assert len(errors) >= 10
    sorted_errors = sorted(float(value) for value in errors)
    median_error = sorted_errors[len(sorted_errors) // 2]
    worst_error = max(sorted_errors)

    assert median_error <= 0.02
    assert worst_error <= 0.05
