from __future__ import annotations

import copy
import csv
import json
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import RunArtifacts


STATIC_TRACE_RE = re.compile(r"^grip_static_ch(?P<channel>[pr])_psi(?P<psi>\d+)_rep(?P<rep>\d+)$")
REFRESH_TRACE_RE = re.compile(r"^grip_refresh_ch(?P<channel>[pr])_psi(?P<psi>\d+)_seq(?P<seq>\d+)$")
MOTION_TRACE_RE = re.compile(
    r"^grip_motion_ch(?P<channel>[pr])_psi(?P<psi>\d+)_seq(?P<seq>\d+)(?:_x(?P<x>-?\d+)_y(?P<y>-?\d+))?$"
)
COMPARE_TRACE_RE = re.compile(r"^grip_compare_ch(?P<channel>[pr])_(?P<phase>pre|post)_psi(?P<psi>\d+)$")

BASELINE_WINDOW_MS = 250.0
END_WINDOW_MS = 250.0
POST_WINDOW_MS = 250.0
PRESSURE_TARGETS_RAW = {
    1000: 2512,
    2000: 3386,
    3000: 4259,
}


@dataclass(frozen=True)
class GripperTraceArtifacts:
    trace_dir: Path
    plot_dir: Path
    analysis_json: Path
    replicate_csv: Path
    plot_paths: tuple[Path, ...]
    replicate_count: int
    report_metrics: dict[int, dict[str, Any]]


def _safe_list(obj: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = obj.get(key, [])
    return value if isinstance(value, list) else []


def _mean(values: list[float]) -> float:
    return sum(values) / float(len(values)) if values else 0.0


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _std(values: list[float]) -> float:
    if not values:
        return 0.0
    avg = _mean(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / float(len(values)))


def _metric_round(value: float | int | None) -> int:
    if value is None:
        return 0
    numeric = float(value)
    if not math.isfinite(numeric):
        return 0
    if numeric >= 0:
        return int(numeric + 0.5)
    return int(numeric - 0.5)


def _first_event(events: list[dict[str, Any]], event_name: str) -> dict[str, Any] | None:
    for event in events:
        if event.get("event_name") == event_name:
            return event
    return None


def _event_value_u16(event: dict[str, Any] | None, key: str) -> int | None:
    if event is None:
        return None
    try:
        return int(event.get(key))
    except (TypeError, ValueError):
        return None


def _parse_trace_name(name: str) -> dict[str, Any] | None:
    for family, regex in (
        ("static", STATIC_TRACE_RE),
        ("refresh", REFRESH_TRACE_RE),
        ("motion", MOTION_TRACE_RE),
        ("compare", COMPARE_TRACE_RE),
    ):
        match = regex.match(str(name or ""))
        if not match:
            continue
        data: dict[str, Any] = {
            "trace_family": family,
            "channel": match.group("channel"),
            "channel_name": "print" if match.group("channel") == "p" else "refuel",
            "psi_milli": int(match.group("psi")),
        }
        if match.groupdict().get("rep"):
            data["replicate"] = int(match.group("rep"))
        if match.groupdict().get("seq"):
            data["sequence_index"] = int(match.group("seq"))
        if match.groupdict().get("phase"):
            data["phase"] = match.group("phase")
        if match.groupdict().get("x") is not None:
            data["x"] = int(match.group("x"))
        if match.groupdict().get("y") is not None:
            data["y"] = int(match.group("y"))
        return data
    return None


def analyze_gripper_trace(trace: dict[str, Any], *, source_path: str | Path | None = None) -> dict[str, Any]:
    metadata = _parse_trace_name(str(trace.get("name") or "")) or {}
    samples = _safe_list(trace, "samples")
    events = _safe_list(trace, "events")
    pulse_start = _first_event(events, "pulse_start")
    pulse_end = _first_event(events, "pulse_end")
    gripper_timing = _first_event(events, "gripper_timing")
    gripper_refresh = _first_event(events, "gripper_refresh_count")
    since_close_ds = _event_value_u16(gripper_timing, "value0")
    since_refresh_ds = _event_value_u16(gripper_timing, "value1")
    refresh_count = _event_value_u16(gripper_refresh, "value0")
    refresh_period_ds = _event_value_u16(gripper_refresh, "value1")
    row: dict[str, Any] = {
        "trace_file": "" if source_path is None else str(source_path),
        "test_id": trace.get("test_id"),
        "name": trace.get("name"),
        **metadata,
        "valid": False,
        "since_close_ms": None if since_close_ds is None else since_close_ds * 100,
        "since_refresh_ms": None if since_refresh_ds is None else since_refresh_ds * 100,
        "refresh_count": refresh_count,
        "refresh_period_ms": None if refresh_period_ds is None else refresh_period_ds * 100,
        "seal_age_ms": None if since_refresh_ds is None else since_refresh_ds * 100,
    }
    if not samples or pulse_start is None or pulse_end is None:
        row["reason"] = "missing_samples_or_pulse_events"
        return row

    start_ms = float(pulse_start.get("dt_ms", 0))
    end_ms = float(pulse_end.get("dt_ms", start_ms))
    baseline_start_ms = max(0.0, start_ms - BASELINE_WINDOW_MS)
    end_start_ms = max(start_ms, end_ms - END_WINDOW_MS)
    post_end_ms = end_ms + POST_WINDOW_MS

    def sample_values(start: float, end: float) -> list[float]:
        return [
            float(sample.get("raw_pressure", 0))
            for sample in samples
            if start <= float(sample.get("dt_ms", 0)) <= end
        ]

    baseline_samples = sample_values(baseline_start_ms, start_ms)
    end_samples = sample_values(end_start_ms, end_ms)
    post_samples = sample_values(end_ms, post_end_ms)
    if not baseline_samples or not end_samples:
        row["reason"] = "missing_baseline_or_end_samples"
        return row

    baseline = _mean(baseline_samples)
    end_pressure = _median(end_samples)
    post_pressure = _median(post_samples) if post_samples else end_pressure
    drop = max(0.0, baseline - end_pressure)
    post_drop = max(0.0, baseline - post_pressure)
    post_pulse_samples = [
        float(sample.get("raw_pressure", 0))
        for sample in samples
        if start_ms <= float(sample.get("dt_ms", 0)) <= post_end_ms
    ]
    abs_dev = max((abs(value - baseline) for value in post_pulse_samples), default=0.0)
    pulse_ms = max(1.0, end_ms - start_ms)
    slope_raw_min = (drop * 60000.0) / pulse_ms
    baseline_std = _std(baseline_samples)
    baseline_span = max(baseline_samples) - min(baseline_samples) if baseline_samples else 0.0
    noise_floor = baseline_std if baseline_std > 0.0 else max(1.0, baseline_span)
    row.update(
        {
            "valid": True,
            "sample_count": len(samples),
            "event_count": len(events),
            "pulse_start_ms": _metric_round(start_ms),
            "pulse_end_ms": _metric_round(end_ms),
            "pulse_ms": _metric_round(pulse_ms),
            "baseline_mean_raw": _metric_round(baseline),
            "baseline_std_raw": _metric_round(baseline_std),
            "baseline_span_raw": _metric_round(baseline_span),
            "end_pressure_raw": _metric_round(end_pressure),
            "post_pressure_raw": _metric_round(post_pressure),
            "drop_raw": _metric_round(drop),
            "post_drop_raw": _metric_round(post_drop),
            "abs_dev_raw": _metric_round(abs_dev),
            "slope_raw_min": _metric_round(slope_raw_min),
            "snr": _metric_round(drop / noise_floor),
        }
    )
    return row


def _valid_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("valid")]


def _rows_for(
    rows: list[dict[str, Any]],
    *,
    family: str | None = None,
    channel: str | None = None,
    psi_milli: int | None = None,
    test_id: int | None = None,
    phase: str | None = None,
) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        if family is not None and row.get("trace_family") != family:
            continue
        if channel is not None and row.get("channel") != channel:
            continue
        if psi_milli is not None and int(row.get("psi_milli") or 0) != int(psi_milli):
            continue
        if test_id is not None and int(row.get("test_id") or 0) != int(test_id):
            continue
        if phase is not None and row.get("phase") != phase:
            continue
        result.append(row)
    return result


def _mean_metric(rows: list[dict[str, Any]], metric: str) -> int:
    values = [float(row.get(metric, 0)) for row in rows if row.get(metric) is not None]
    return _metric_round(_mean(values))


def _max_metric(rows: list[dict[str, Any]], metric: str) -> int:
    values = [float(row.get(metric, 0)) for row in rows if row.get(metric) is not None]
    return _metric_round(max(values)) if values else 0


def _span_metric(rows: list[dict[str, Any]], metric: str) -> int:
    values = [float(row.get(metric, 0)) for row in rows if row.get(metric) is not None]
    if not values:
        return 0
    return _metric_round(max(values) - min(values))


def _build_static_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "rej_py": len([row for row in _rows_for(rows, family="static") if not row.get("valid")]),
        "traces_py": len(_rows_for(rows, family="static")),
    }
    for psi_milli, label in ((1000, "1"), (2000, "2"), (3000, "3")):
        subset = _valid_rows(_rows_for(rows, family="static", psi_milli=psi_milli))
        metrics[f"d{label}"] = _mean_metric(subset, "drop_raw")
        metrics[f"d{label}_max"] = _max_metric(subset, "drop_raw")
        metrics[f"d{label}_span"] = _span_metric(subset, "drop_raw")
        metrics[f"snr{label}"] = _mean_metric(subset, "snr")
    return metrics


def _build_family_metrics(rows: list[dict[str, Any]], family: str) -> dict[str, Any]:
    subset_all = _rows_for(rows, family=family)
    subset = _valid_rows(subset_all)
    return {
        "rej_py": len([row for row in subset_all if not row.get("valid")]),
        "traces_py": len(subset_all),
        "drop_mean": _mean_metric(subset, "drop_raw"),
        "drop_max": _max_metric(subset, "drop_raw"),
        "drop_span": _span_metric(subset, "drop_raw"),
        "abs_dev": _max_metric(subset, "abs_dev_raw"),
        "slope": _mean_metric(subset, "slope_raw_min"),
        "snr": _mean_metric(subset, "snr"),
    }


def _build_compare_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "rej_py": len([row for row in _rows_for(rows, family="compare") if not row.get("valid")]),
        "traces_py": len(_rows_for(rows, family="compare")),
    }
    for channel in ("p", "r"):
        pre_rows = _valid_rows(_rows_for(rows, family="compare", channel=channel, phase="pre"))
        post_rows = _valid_rows(_rows_for(rows, family="compare", channel=channel, phase="post"))
        pre = _mean_metric(pre_rows, "drop_raw")
        post = _mean_metric(post_rows, "drop_raw")
        metrics[f"{channel}_pre"] = pre
        metrics[f"{channel}_post"] = post
        metrics[f"{channel}_delta"] = post - pre
    return metrics


def _build_report_metrics(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {
        2510: _build_static_metrics(rows),
        2511: _build_family_metrics(rows, "refresh"),
        2512: _build_family_metrics(rows, "motion"),
        2513: _build_compare_metrics(rows),
    }


def enrich_raw_selftest_with_gripper_metrics(
    raw_selftest: dict[str, Any],
    report_metrics: dict[int, dict[str, Any]] | None,
) -> dict[str, Any]:
    if not report_metrics:
        return raw_selftest
    enriched = copy.deepcopy(raw_selftest)
    for result in enriched.get("results") or []:
        try:
            test_id = int(result.get("test_id"))
        except (TypeError, ValueError):
            continue
        derived = report_metrics.get(test_id)
        if not derived:
            continue
        metrics = dict(result.get("metrics") or {})
        metrics.update(derived)
        result["metrics"] = metrics
    return enriched


def _trace_sources(run_dir: Path) -> list[Path]:
    return sorted(run_dir.glob("raw_selftest_trace_251*_grip_*.json"))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "trace_file",
        "test_id",
        "name",
        "trace_family",
        "channel",
        "channel_name",
        "psi_milli",
        "replicate",
        "sequence_index",
        "phase",
        "x",
        "y",
        "valid",
        "reason",
        "sample_count",
        "event_count",
        "pulse_start_ms",
        "pulse_end_ms",
        "pulse_ms",
        "baseline_mean_raw",
        "baseline_std_raw",
        "baseline_span_raw",
        "end_pressure_raw",
        "post_pressure_raw",
        "drop_raw",
        "post_drop_raw",
        "abs_dev_raw",
        "slope_raw_min",
        "snr",
        "since_close_ms",
        "since_refresh_ms",
        "refresh_count",
        "refresh_period_ms",
        "seal_age_ms",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _plot_static_matrix(rows: list[dict[str, Any]], plot_dir: Path) -> Path | None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path = plot_dir / "gripper_static_pressure_matrix.png"
    fig, ax = plt.subplots(figsize=(9, 5.5))
    channels = ("p", "r")
    pressures = (1000, 2000, 3000)
    offsets = {"p": -0.18, "r": 0.18}
    jitter = {-1: -0.05, 0: 0.0, 1: 0.05}
    labels = {"p": "Print", "r": "Refuel"}
    colors = {"p": "tab:blue", "r": "tab:orange"}
    seen_channels: set[str] = set()
    for channel in channels:
        for idx, psi in enumerate(pressures):
            subset = sorted(
                _valid_rows(_rows_for(rows, family="static", channel=channel, psi_milli=psi)),
                key=lambda row: int(row.get("replicate") or 0),
            )
            if not subset:
                continue
            values = [float(row.get("drop_raw") or 0) for row in subset]
            base_x = idx + offsets[channel]
            xs = [
                base_x + jitter.get(int(row.get("replicate") or 0) - 2, 0.0)
                for row in subset
            ]
            ax.scatter(
                xs,
                values,
                color=colors[channel],
                edgecolor="black",
                linewidth=0.4,
                alpha=0.8,
                label=labels[channel] if channel not in seen_channels else None,
                zorder=3,
            )
            seen_channels.add(channel)
            avg = _mean(values)
            std = _std(values)
            ax.errorbar(
                [base_x],
                [avg],
                yerr=[[std], [std]],
                fmt="D",
                color=colors[channel],
                markerfacecolor="white",
                markeredgecolor=colors[channel],
                capsize=4,
                markersize=6,
                zorder=4,
            )
    ax.set_xticks(range(len(pressures)), ["1 psi", "2 psi", "3 psi"])
    ax.set_ylabel("End-of-pulse drop (raw)")
    ax.set_title("Gripper Static Pressure Matrix (Replicates + Mean +/- SD)")
    ax.grid(axis="y", alpha=0.2)
    if seen_channels:
        ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def _plot_static_drop_by_replicate(rows: list[dict[str, Any]], plot_dir: Path) -> Path | None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    subset = _valid_rows(_rows_for(rows, family="static"))
    if not subset:
        return None
    path = plot_dir / "gripper_static_drop_by_replicate.png"
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8), sharey=True)
    colors = {1000: "tab:blue", 2000: "tab:orange", 3000: "tab:green"}
    for ax, channel, title in zip(axes, ("p", "r"), ("Print", "Refuel")):
        for psi, color in colors.items():
            pressure_rows = sorted(
                [row for row in subset if row.get("channel") == channel and int(row.get("psi_milli") or 0) == psi],
                key=lambda row: int(row.get("replicate") or 0),
            )
            if not pressure_rows:
                continue
            ax.plot(
                [int(row.get("replicate") or 0) for row in pressure_rows],
                [float(row.get("drop_raw") or 0) for row in pressure_rows],
                marker="o",
                color=color,
                label=f"{psi // 1000} psi",
            )
        ax.set_title(title)
        ax.set_xlabel("Replicate")
        ax.grid(alpha=0.25)
    axes[0].set_ylabel("End-of-pulse drop (raw)")
    axes[-1].legend(title="Pressure")
    fig.suptitle("Gripper Static Drop by Replicate")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def _plot_static_drop_vs_seal_age(rows: list[dict[str, Any]], plot_dir: Path) -> Path | None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    subset = [
        row
        for row in _valid_rows(_rows_for(rows, family="static"))
        if row.get("seal_age_ms") is not None
    ]
    if not subset:
        return None
    path = plot_dir / "gripper_static_drop_vs_seal_age.png"
    fig, ax = plt.subplots(figsize=(9, 5.2))
    colors = {1000: "tab:blue", 2000: "tab:orange", 3000: "tab:green"}
    markers = {"p": "o", "r": "s"}
    labels_seen: set[tuple[int, str]] = set()
    for row in sorted(subset, key=lambda item: (int(item.get("psi_milli") or 0), str(item.get("channel") or ""))):
        psi = int(row.get("psi_milli") or 0)
        channel = str(row.get("channel") or "")
        key = (psi, channel)
        ax.scatter(
            float(row.get("seal_age_ms") or 0) / 1000.0,
            float(row.get("drop_raw") or 0),
            color=colors.get(psi, "tab:gray"),
            marker=markers.get(channel, "o"),
            edgecolor="black",
            linewidth=0.4,
            alpha=0.85,
            label=f"{psi // 1000} psi {'print' if channel == 'p' else 'refuel'}" if key not in labels_seen else None,
        )
        labels_seen.add(key)
    ax.set_xlabel("Time since last gripper close/refresh (s)")
    ax.set_ylabel("End-of-pulse drop (raw)")
    ax.set_title("Gripper Static Drop vs Seal Age")
    ax.grid(alpha=0.25)
    ax.legend(ncol=2, fontsize="small")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def _plot_drop_timeline(rows: list[dict[str, Any]], plot_dir: Path, family: str, filename: str, title: str) -> Path | None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    subset = _valid_rows(_rows_for(rows, family=family))
    if not subset:
        return None
    path = plot_dir / filename
    fig, ax = plt.subplots(figsize=(10, 5))
    for channel, label in (("p", "Print"), ("r", "Refuel")):
        channel_rows = sorted(
            [row for row in subset if row.get("channel") == channel],
            key=lambda row: int(row.get("sequence_index") or row.get("replicate") or 0),
        )
        if not channel_rows:
            continue
        xs = [int(row.get("sequence_index") or idx + 1) for idx, row in enumerate(channel_rows)]
        ys = [float(row.get("drop_raw") or 0) for row in channel_rows]
        ax.plot(xs, ys, marker="o", label=label)
    ax.set_xlabel("Pulse index")
    ax.set_ylabel("End-of-pulse drop (raw)")
    ax.set_title(title)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def _plot_motion_map(rows: list[dict[str, Any]], plot_dir: Path) -> Path | None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    subset = _valid_rows(_rows_for(rows, family="motion"))
    points = [row for row in subset if row.get("x") is not None and row.get("y") is not None]
    if not points:
        return None
    path = plot_dir / "gripper_motion_raster_drop_map.png"
    fig, ax = plt.subplots(figsize=(8, 6))
    scatter = ax.scatter(
        [float(row.get("x") or 0) for row in points],
        [float(row.get("y") or 0) for row in points],
        c=[float(row.get("drop_raw") or 0) for row in points],
        cmap="viridis",
    )
    ax.set_xlabel("X steps")
    ax.set_ylabel("Y steps")
    ax.set_title("Gripper Raster Pulse Drop Map")
    fig.colorbar(scatter, ax=ax, label="Drop raw")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def _plot_overlay(rows: list[dict[str, Any]], trace_by_name: dict[str, dict[str, Any]], plot_dir: Path) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    paths: list[Path] = []
    static_rep_colors = {1: "tab:blue", 2: "tab:orange", 3: "tab:green"}
    phase_colors = {"pre": "tab:blue", "post": "tab:orange"}
    for family in ("static", "refresh", "motion", "compare"):
        for channel in ("p", "r"):
            subset = _rows_for(rows, family=family, channel=channel)
            if not subset:
                continue
            path = plot_dir / f"gripper_{family}_ch{channel}_overlay.png"
            fig, ax = plt.subplots(figsize=(10, 5))
            legend_handles: list[Any] = []
            legend_labels: list[str] = []
            for row in subset:
                trace = trace_by_name.get(str(row.get("name") or ""))
                if not trace:
                    continue
                samples = _safe_list(trace, "samples")
                if not samples:
                    continue
                color = "tab:blue"
                label = None
                if family == "static":
                    replicate = int(row.get("replicate") or 0)
                    color = static_rep_colors.get(replicate, "tab:gray")
                    label = f"rep {replicate}"
                elif family == "compare":
                    phase = str(row.get("phase") or "")
                    color = phase_colors.get(phase, "tab:gray")
                    label = phase
                else:
                    sequence = int(row.get("sequence_index") or row.get("replicate") or 0)
                    cmap = plt.get_cmap("viridis")
                    denominator = max(1, len(subset) - 1)
                    color = cmap((sequence - 1) / denominator if sequence > 0 else 0.0)
                    label = f"seq {sequence:02d}" if sequence > 0 else "trace"
                ax.plot(
                    [float(sample.get("dt_ms", 0)) for sample in samples],
                    [float(sample.get("raw_pressure", 0)) for sample in samples],
                    alpha=0.55,
                    linewidth=1.0,
                    color=color,
                    label=label,
                )
            if family == "static":
                for psi, raw in PRESSURE_TARGETS_RAW.items():
                    ax.axhline(raw, linestyle="--", linewidth=0.9, alpha=0.7, color="black")
                    ax.text(
                        1.01,
                        raw,
                        f"{psi // 1000} psi",
                        transform=ax.get_yaxis_transform(),
                        va="center",
                        fontsize="small",
                    )
                for replicate, color in static_rep_colors.items():
                    legend_handles.append(Line2D([0], [0], color=color, lw=2))
                    legend_labels.append(f"rep {replicate}")
            else:
                valid_subset = _valid_rows(subset)
                baselines = [float(row.get("baseline_mean_raw") or 0) for row in valid_subset]
                if baselines:
                    reference = _median(baselines)
                    ax.axhline(
                        reference,
                        linestyle="--",
                        linewidth=1.0,
                        color="black",
                        alpha=0.65,
                        label=f"start median {int(reference + 0.5)}",
                    )
            handles, labels = ax.get_legend_handles_labels()
            if legend_handles:
                handles = legend_handles + handles
                labels = legend_labels + labels
            unique: dict[str, Any] = {}
            for handle, label in zip(handles, labels):
                if label and label not in unique:
                    unique[label] = handle
            ax.set_title(f"Gripper {family} channel {channel.upper()} traces")
            ax.set_xlabel("Trace time (ms)")
            ax.set_ylabel("Raw pressure")
            if unique:
                ax.legend(unique.values(), unique.keys(), fontsize="x-small", ncol=2)
            ax.grid(alpha=0.2)
            fig.tight_layout()
            fig.savefig(path, dpi=140)
            plt.close(fig)
            paths.append(path)
    return paths


def _write_plots(rows: list[dict[str, Any]], trace_by_name: dict[str, dict[str, Any]], plot_dir: Path) -> list[Path]:
    plot_dir.mkdir(parents=True, exist_ok=True)
    plot_paths: list[Path] = []
    for maybe_path in (
        _plot_static_matrix(rows, plot_dir),
        _plot_static_drop_by_replicate(rows, plot_dir),
        _plot_static_drop_vs_seal_age(rows, plot_dir),
        _plot_drop_timeline(rows, plot_dir, "refresh", "gripper_refresh_hold_timeline.png", "Gripper Refresh Hold Drop"),
        _plot_drop_timeline(rows, plot_dir, "motion", "gripper_motion_raster_drop_timeline.png", "Gripper Raster Pulse Drop"),
        _plot_motion_map(rows, plot_dir),
    ):
        if maybe_path is not None:
            plot_paths.append(maybe_path)
    plot_paths.extend(_plot_overlay(rows, trace_by_name, plot_dir))
    return plot_paths


def generate_gripper_trace_artifacts(artifacts: RunArtifacts) -> GripperTraceArtifacts | None:
    sources = _trace_sources(artifacts.run_dir)
    if not sources:
        return None

    trace_dir = artifacts.traces_dir / "gripper_seal_stress"
    plot_dir = artifacts.plots_dir / "gripper_seal_stress"
    trace_dir.mkdir(parents=True, exist_ok=True)
    plot_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    trace_by_name: dict[str, dict[str, Any]] = {}
    for source in sources:
        trace = json.loads(source.read_text(encoding="utf-8"))
        destination = trace_dir / source.name
        if source.resolve() != destination.resolve():
            shutil.copyfile(source, destination)
        name = str(trace.get("name") or "")
        trace_by_name[name] = trace
        rows.append(analyze_gripper_trace(trace, source_path=destination))

    rows.sort(
        key=lambda row: (
            str(row.get("trace_family") or ""),
            str(row.get("channel") or ""),
            int(row.get("psi_milli") or 0),
            int(row.get("sequence_index") or row.get("replicate") or 0),
            str(row.get("phase") or ""),
        )
    )
    report_metrics = _build_report_metrics(rows)
    analysis = {
        "schema_version": "gripper_trace_analysis_v1",
        "replicate_count": len(rows),
        "valid_replicate_count": len(_valid_rows(rows)),
        "rejected_replicate_count": len([row for row in rows if not row.get("valid")]),
        "replicates": rows,
        "report_metrics": {str(key): value for key, value in report_metrics.items()},
    }
    analysis_json = plot_dir / "gripper_trace_analysis.json"
    analysis_json.write_text(json.dumps(analysis, indent=2, sort_keys=True), encoding="utf-8")
    replicate_csv = plot_dir / "gripper_trace_replicates.csv"
    _write_csv(replicate_csv, rows)
    plot_paths = _write_plots(rows, trace_by_name, plot_dir)

    return GripperTraceArtifacts(
        trace_dir=trace_dir,
        plot_dir=plot_dir,
        analysis_json=analysis_json,
        replicate_csv=replicate_csv,
        plot_paths=tuple(plot_paths),
        replicate_count=len(rows),
        report_metrics=report_metrics,
    )


__all__ = [
    "GripperTraceArtifacts",
    "analyze_gripper_trace",
    "enrich_raw_selftest_with_gripper_metrics",
    "generate_gripper_trace_artifacts",
]
