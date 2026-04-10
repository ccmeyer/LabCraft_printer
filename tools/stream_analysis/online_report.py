from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

from tools.stream_analysis import dataset as dataset_mod
from tools.stream_analysis import online_calibration as online_cal_mod


PROCESS_NAME = dataset_mod.ONLINE_STREAM_PROCESS_NAME
STAGE_DIRNAME = "online_stream_report"
TAIL_PHASES = {"tail_scout", "tail_backtrack", "tail_coarse", "tail_refine"}

RUN_SUMMARY_COLUMNS = [
    "run_id",
    "condition_key",
    "print_pressure",
    "print_pw_us",
    "replicate_index",
    "num_printed",
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


def _gravimetric_per_print_nl(metadata_row: dict) -> float | None:
    mass_per_print_mg = _float_or_none(metadata_row.get("Mass/print"))
    if mass_per_print_mg is not None:
        return float(mass_per_print_mg) * 1000.0
    mass_change_mg = _float_or_none(metadata_row.get("Mass Change"))
    num_printed = _int_or_none(metadata_row.get("Num printed"))
    if mass_change_mg is None or num_printed in (None, 0):
        return None
    return (float(mass_change_mg) * 1000.0) / float(num_printed)


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


def _run_context(experiment_root: Path, metadata_row: dict) -> dict:
    run_id = _clean_text(metadata_row.get("Dataset name"))
    run_dir = _run_dir_for_row(experiment_root, metadata_row)
    flow_artifact = _load_json(run_dir / "flow_fit.json")
    tail_artifact = _load_json(run_dir / "tail_fit.json")
    frame_rows = _iter_jsonl(run_dir / "frames.jsonl")
    fit = dict(flow_artifact.get("fit") or {})
    tail_result = dict(tail_artifact.get("result") or {})
    tail_phase = dict(tail_result.get("tail_phase") or {})

    print_pressure = _float_or_none(metadata_row.get("Print Pressure"))
    print_pw_us = _int_or_none(metadata_row.get("Print PW"))
    replicate_index = _int_or_none(metadata_row.get("Rep"))
    predicted_volume_nl = (
        _float_or_none(metadata_row.get("Predicted Volume (nL)"))
        if _float_or_none(metadata_row.get("Predicted Volume (nL)")) is not None
        else _float_or_none(tail_result.get("predicted_volume_nl"))
    )
    gravimetric_per_print_nl = _gravimetric_per_print_nl(metadata_row)
    gravimetric_metrics = _gravimetric_equality_metrics(gravimetric_per_print_nl, fit)

    flow_rows = _phase_rows(frame_rows, "flow_rate")
    tail_rows = _phase_rows(frame_rows, *sorted(TAIL_PHASES))
    flow_volume_points = _points_from_rows(flow_rows, y_key="visible_volume_nl", accepted_only=True)
    tail_volume_points = _points_from_rows(tail_rows, y_key="visible_volume_nl", accepted_only=True)
    tail_rejected_volume_points = _points_from_rows(tail_rows, y_key="visible_volume_nl", accepted_only=False)
    width_points = _points_from_rows(flow_rows + tail_rows, y_key="attached_width_px", accepted_only=False)
    clearance_points = _points_from_rows(flow_rows + tail_rows, y_key="attached_bottom_clearance_px", accepted_only=False)

    tail_start_delay = _int_or_none(tail_phase.get("tail_start_delay_from_emergence_us"))
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
        "run_id": run_id,
        "condition_key": _format_condition_key(print_pressure, print_pw_us),
        "print_pressure": print_pressure,
        "print_pw_us": print_pw_us,
        "replicate_index": replicate_index,
        "num_printed": _int_or_none(metadata_row.get("Num printed")),
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
        "analysis_warnings": _clean_text(metadata_row.get("Analysis Warnings")),
        "run_report_png": None,
    }

    return {
        "summary_row": summary_row,
        "run_dir": run_dir,
        "metadata_row": dict(metadata_row),
        "flow_artifact": flow_artifact,
        "tail_artifact": tail_artifact,
        "fit": fit,
        "tail_result": tail_result,
        "tail_phase": tail_phase,
        "frame_rows": frame_rows,
        "flow_rows": flow_rows,
        "tail_rows": tail_rows,
        "flow_volume_points": flow_volume_points,
        "tail_volume_points": tail_volume_points,
        "tail_rejected_volume_points": tail_rejected_volume_points,
        "width_points": width_points,
        "clearance_points": clearance_points,
    }


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
):
    experiment_root = dataset_mod.resolve_experiment_root(experiment_root)
    stage_dir = (
        Path(output_root).expanduser().resolve()
        if output_root is not None
        else experiment_root / "analysis" / STAGE_DIRNAME
    )
    stage_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = stage_dir / "runs"
    conditions_dir = stage_dir / "conditions"
    experiment_dir = stage_dir / "experiment"
    runs_dir.mkdir(parents=True, exist_ok=True)
    conditions_dir.mkdir(parents=True, exist_ok=True)
    experiment_dir.mkdir(parents=True, exist_ok=True)

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

    contexts = [_run_context(experiment_root, row) for row in metadata_rows]
    summary_rows = []
    grouped_contexts = defaultdict(list)
    for context in contexts:
        summary_row = dict(context.get("summary_row") or {})
        run_slug = _safe_slug(summary_row.get("run_id") or "run")
        run_report_path = runs_dir / f"{run_slug}.png"
        _plot_run_report(context, run_report_path)
        summary_row["run_report_png"] = str(run_report_path)
        context["summary_row"] = summary_row
        summary_rows.append(summary_row)
        grouped_contexts[str(summary_row.get("condition_key") or "unknown")].append(context)

    condition_summary_rows = []
    for condition_key, condition_contexts in sorted(grouped_contexts.items()):
        condition_slug = _safe_slug(condition_key)
        overlay_path = conditions_dir / f"{condition_slug}_overlay.png"
        _plot_condition_overlay(condition_key, condition_contexts, overlay_path)
        condition_row = _condition_summary_row(
            condition_key,
            [dict(item.get("summary_row") or {}) for item in condition_contexts],
        )
        condition_row["condition_overlay_png"] = str(overlay_path)
        condition_summary_rows.append(condition_row)

    predicted_vs_gravimetric_path = experiment_dir / "predicted_vs_gravimetric.png"
    delay_gap_path = experiment_dir / "delay_gap_by_condition.png"
    _plot_predicted_vs_gravimetric(contexts, predicted_vs_gravimetric_path)
    _plot_delay_gap_by_condition(contexts, delay_gap_path)

    run_summary_csv = stage_dir / "run_summary.csv"
    run_summary_json = stage_dir / "run_summary.json"
    condition_summary_csv = stage_dir / "condition_summary.csv"
    condition_summary_json = stage_dir / "condition_summary.json"
    manifest_json = stage_dir / "report_manifest.json"

    dataset_mod._write_csv(run_summary_csv, RUN_SUMMARY_COLUMNS, summary_rows)
    dataset_mod._write_json(run_summary_json, summary_rows)
    dataset_mod._write_csv(condition_summary_csv, CONDITION_SUMMARY_COLUMNS, condition_summary_rows)
    dataset_mod._write_json(condition_summary_json, condition_summary_rows)

    manifest = {
        "schema_version": 1,
        "experiment_root": str(experiment_root),
        "output_root": str(stage_dir),
        "run_id_filter": None if run_id is None else str(run_id),
        "run_count": len(summary_rows),
        "condition_count": len(condition_summary_rows),
        "paths": {
            "run_summary_csv": str(run_summary_csv),
            "run_summary_json": str(run_summary_json),
            "condition_summary_csv": str(condition_summary_csv),
            "condition_summary_json": str(condition_summary_json),
            "predicted_vs_gravimetric_png": str(predicted_vs_gravimetric_path),
            "delay_gap_by_condition_png": str(delay_gap_path),
            "runs_dir": str(runs_dir),
            "conditions_dir": str(conditions_dir),
        },
    }
    dataset_mod._write_json(manifest_json, manifest)

    return {
        **manifest,
        "paths": {
            **manifest["paths"],
            "report_manifest_json": str(manifest_json),
        },
    }
