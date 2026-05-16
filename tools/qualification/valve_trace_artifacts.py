from __future__ import annotations

import csv
import json
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import RunArtifacts


VALVE_TRACE_RE = re.compile(r"^valve_char_(?P<channel>[pr])_w(?P<width>\d+)_rep(?P<rep>\d+)$")
BASELINE_WINDOW_MS = 10.0
RESPONSE_WINDOW_MS = 30.0


@dataclass(frozen=True)
class ValveTraceArtifacts:
    trace_dir: Path
    plot_dir: Path
    analysis_json: Path
    replicate_csv: Path
    plot_paths: tuple[Path, ...]
    replicate_count: int


def _safe_list(obj: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = obj.get(key, [])
    return value if isinstance(value, list) else []


def _mean(values: list[float]) -> float:
    return sum(values) / float(len(values)) if values else 0.0


def _std(values: list[float]) -> float:
    if not values:
        return 0.0
    avg = _mean(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / float(len(values)))


def _first_event(events: list[dict[str, Any]], event_name: str) -> dict[str, Any] | None:
    for event in events:
        if event.get("event_name") == event_name:
            return event
    return None


def _point_for_pressure(samples: list[dict[str, Any]], pressure: float, start_ms: float, end_ms: float) -> dict[str, Any] | None:
    for sample in samples:
        dt = float(sample.get("dt_ms", 0))
        if start_ms <= dt <= end_ms and float(sample.get("raw_pressure", 0)) == pressure:
            return sample
    return None


def _parse_trace_name(name: str) -> dict[str, Any] | None:
    match = VALVE_TRACE_RE.match(str(name or ""))
    if not match:
        return None
    channel = match.group("channel")
    return {
        "channel": channel,
        "channel_name": "print" if channel == "p" else "refuel",
        "width_us": int(match.group("width")),
        "replicate": int(match.group("rep")),
    }


def analyze_valve_trace(trace: dict[str, Any], *, source_path: str | Path | None = None) -> dict[str, Any]:
    metadata = _parse_trace_name(str(trace.get("name") or "")) or {}
    samples = _safe_list(trace, "samples")
    events = _safe_list(trace, "events")
    pulse_start = _first_event(events, "pulse_start")
    pulse_end = _first_event(events, "pulse_end")
    row: dict[str, Any] = {
        "trace_file": "" if source_path is None else str(source_path),
        "test_id": trace.get("test_id"),
        "name": trace.get("name"),
        **metadata,
        "valid": False,
    }
    if not samples or pulse_start is None:
        row["reason"] = "missing_samples_or_pulse_start"
        return row

    start_ms = float(pulse_start.get("dt_ms", 0))
    end_ms = float(pulse_end.get("dt_ms", start_ms)) if pulse_end is not None else start_ms
    baseline_start_ms = max(0.0, start_ms - BASELINE_WINDOW_MS)
    response_end_ms = start_ms + RESPONSE_WINDOW_MS

    baseline_samples = [
        float(sample.get("raw_pressure", 0))
        for sample in samples
        if baseline_start_ms <= float(sample.get("dt_ms", 0)) <= start_ms
    ]
    response_samples = [
        sample
        for sample in samples
        if start_ms <= float(sample.get("dt_ms", 0)) <= response_end_ms
    ]
    if not baseline_samples or not response_samples:
        row["reason"] = "missing_baseline_or_response_samples"
        return row

    baseline_mean = _mean(baseline_samples)
    baseline_std = _std(baseline_samples)
    baseline_min = min(baseline_samples)
    baseline_max = max(baseline_samples)

    response_pressures = [float(sample.get("raw_pressure", 0)) for sample in response_samples]
    min_pressure = min(response_pressures)
    max_pressure = max(response_pressures)
    drop_raw = max(0.0, baseline_mean - min_pressure)
    rise_raw = max(0.0, max_pressure - baseline_mean)
    if drop_raw >= rise_raw:
        selected_pressure = min_pressure
        response_kind = "drop"
    else:
        selected_pressure = max_pressure
        response_kind = "rise"
    response_raw = max(drop_raw, rise_raw)
    selected_sample = _point_for_pressure(samples, selected_pressure, start_ms, response_end_ms)
    selected_ms = float(selected_sample.get("dt_ms", start_ms)) if selected_sample is not None else start_ms

    row.update(
        {
            "valid": True,
            "sample_count": len(samples),
            "event_count": len(events),
            "pulse_start_ms": start_ms,
            "pulse_end_ms": end_ms,
            "baseline_start_ms": baseline_start_ms,
            "baseline_end_ms": start_ms,
            "response_end_ms": response_end_ms,
            "baseline_mean_raw": baseline_mean,
            "baseline_std_raw": baseline_std,
            "baseline_span_raw": baseline_max - baseline_min,
            "min_pressure_raw": min_pressure,
            "max_pressure_raw": max_pressure,
            "selected_pressure_raw": selected_pressure,
            "selected_dt_ms": selected_ms,
            "selected_after_start_ms": selected_ms - start_ms,
            "drop_raw": drop_raw,
            "rise_raw": rise_raw,
            "response_raw": response_raw,
            "response_kind": response_kind,
            "snr_std": None if baseline_std <= 0.0 else response_raw / baseline_std,
            "snr_span": None if (baseline_max - baseline_min) <= 0.0 else response_raw / (baseline_max - baseline_min),
        }
    )
    return row


def _trace_sources(run_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in run_dir.glob("*_trace_247[34]_valve_char_*.json")
        if path.is_file()
    )


def _copy_trace_sources(sources: list[Path], trace_dir: Path) -> list[Path]:
    trace_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for source in sources:
        dest = trace_dir / source.name
        if source.resolve() != dest.resolve():
            shutil.copyfile(source, dest)
        copied.append(dest)
    return copied


def _load_rows(trace_paths: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    traces: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for path in trace_paths:
        trace = json.loads(path.read_text(encoding="utf-8"))
        traces.append({"path": str(path), "payload": trace})
        rows.append(analyze_valve_trace(trace, source_path=path))
    rows.sort(key=lambda row: (str(row.get("channel") or ""), int(row.get("width_us") or 0), int(row.get("replicate") or 0)))
    return traces, rows


def _summary_by_condition(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    keys = sorted({(row.get("channel"), row.get("width_us")) for row in rows if row.get("valid")})
    for channel, width_us in keys:
        subset = [row for row in rows if row.get("valid") and row.get("channel") == channel and row.get("width_us") == width_us]
        responses = [float(row.get("response_raw") or 0) for row in subset]
        baseline_std = [float(row.get("baseline_std_raw") or 0) for row in subset]
        summary.append(
            {
                "channel": channel,
                "channel_name": "print" if channel == "p" else "refuel",
                "width_us": width_us,
                "replicate_count": len(subset),
                "response_mean_raw": _mean(responses),
                "response_std_raw": _std(responses),
                "response_span_raw": (max(responses) - min(responses)) if responses else 0.0,
                "baseline_std_mean_raw": _mean(baseline_std),
            }
        )
    return summary


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "trace_file",
        "test_id",
        "name",
        "channel",
        "channel_name",
        "width_us",
        "replicate",
        "valid",
        "sample_count",
        "event_count",
        "pulse_start_ms",
        "pulse_end_ms",
        "baseline_start_ms",
        "baseline_end_ms",
        "response_end_ms",
        "baseline_mean_raw",
        "baseline_std_raw",
        "baseline_span_raw",
        "min_pressure_raw",
        "max_pressure_raw",
        "selected_pressure_raw",
        "selected_dt_ms",
        "selected_after_start_ms",
        "drop_raw",
        "rise_raw",
        "response_raw",
        "response_kind",
        "snr_std",
        "snr_span",
        "reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _plot_inputs(traces: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[tuple[Path, dict[str, Any], dict[str, Any]]]:
    row_by_file = {str(row.get("trace_file")): row for row in rows}
    result: list[tuple[Path, dict[str, Any], dict[str, Any]]] = []
    for item in traces:
        path = Path(str(item["path"]))
        row = row_by_file.get(str(path))
        if row is None or not row.get("valid"):
            continue
        result.append((path, item["payload"], row))
    result.sort(key=lambda item: (str(item[2].get("channel") or ""), int(item[2].get("width_us") or 0), int(item[2].get("replicate") or 0)))
    return result


def _plot_full_timecourse(plot_items: list[tuple[Path, dict[str, Any], dict[str, Any]]], plot_dir: Path, channel: str) -> Path | None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    subset = [item for item in plot_items if item[2].get("channel") == channel]
    if not subset:
        return None
    fig, ax = plt.subplots(figsize=(14, 6))
    offset = 0.0
    y_values: list[float] = []
    for _path, trace, row in subset:
        samples = _safe_list(trace, "samples")
        if not samples:
            continue
        t = [offset + float(sample.get("dt_ms", 0)) for sample in samples]
        y = [float(sample.get("raw_pressure", 0)) for sample in samples]
        y_values.extend(y)
        label = f"{int(row.get('width_us') or 0)} us rep {int(row.get('replicate') or 0):02d}"
        ax.plot(t, y, linewidth=1.0, alpha=0.75, label=label)
        start = offset + float(row.get("pulse_start_ms") or 0)
        selected = offset + float(row.get("selected_dt_ms") or 0)
        ax.axvline(start, color="tab:orange", linestyle="--", linewidth=0.7, alpha=0.5)
        ax.scatter([selected], [float(row.get("selected_pressure_raw") or 0)], color="tab:red", s=18, zorder=4)
        ax.hlines(
            float(row.get("baseline_mean_raw") or 0),
            offset + float(row.get("baseline_start_ms") or 0),
            offset + float(row.get("baseline_end_ms") or 0),
            color="black",
            linewidth=1.0,
            alpha=0.7,
        )
        offset += max(float(sample.get("dt_ms", 0)) for sample in samples) + 45.0
    ax.set_title(f"{'Print' if channel == 'p' else 'Refuel'} valve stitched pulse windows")
    ax.set_xlabel("Stitched time (ms)")
    ax.set_ylabel("Pressure (raw)")
    ax.grid(True, alpha=0.25)
    if y_values:
        pad = max(5.0, (max(y_values) - min(y_values)) * 0.15)
        ax.set_ylim(min(y_values) - pad, max(y_values) + pad)
    ax.legend(loc="best", ncols=3, fontsize=7)
    fig.tight_layout()
    path = plot_dir / f"valve_char_{channel}_full_timecourse.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _plot_overlay(plot_items: list[tuple[Path, dict[str, Any], dict[str, Any]]], plot_dir: Path, channel: str, width_us: int) -> Path | None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    subset = [item for item in plot_items if item[2].get("channel") == channel and item[2].get("width_us") == width_us]
    if not subset:
        return None
    fig, ax = plt.subplots(figsize=(10, 6))
    for _path, trace, row in subset:
        samples = _safe_list(trace, "samples")
        start = float(row.get("pulse_start_ms") or 0)
        baseline = float(row.get("baseline_mean_raw") or 0)
        x = [float(sample.get("dt_ms", 0)) - start for sample in samples]
        y = [baseline - float(sample.get("raw_pressure", 0)) for sample in samples]
        ax.plot(x, y, linewidth=1.1, alpha=0.65)
        ax.scatter(
            [float(row.get("selected_dt_ms") or start) - start],
            [baseline - float(row.get("selected_pressure_raw") or baseline)],
            color="tab:red",
            s=14,
            alpha=0.75,
        )
    ax.axvline(0, color="tab:orange", linestyle="--", linewidth=1.0, label="pulse start")
    ax.axvspan(0, RESPONSE_WINDOW_MS, color="tab:blue", alpha=0.08, label="response window")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_title(f"{'Print' if channel == 'p' else 'Refuel'} valve {width_us} us replicate overlay")
    ax.set_xlabel("Time from pulse start (ms)")
    ax.set_ylabel("Baseline - pressure (raw)")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    path = plot_dir / f"valve_char_{channel}_w{width_us}_overlay.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _plot_response_summary(rows: list[dict[str, Any]], plot_dir: Path) -> Path | None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    valid = [row for row in rows if row.get("valid")]
    if not valid:
        return None
    fig, ax = plt.subplots(figsize=(9, 6))
    for channel, color, label in (("p", "tab:blue", "print"), ("r", "tab:green", "refuel")):
        subset = [row for row in valid if row.get("channel") == channel]
        if not subset:
            continue
        xs = [float(row.get("width_us") or 0) for row in subset]
        ys = [float(row.get("response_raw") or 0) for row in subset]
        ax.scatter(xs, ys, color=color, alpha=0.45, label=f"{label} replicates")
        for width in sorted({int(row.get("width_us") or 0) for row in subset}):
            responses = [float(row.get("response_raw") or 0) for row in subset if int(row.get("width_us") or 0) == width]
            if responses:
                ax.errorbar([width], [_mean(responses)], yerr=[_std(responses)], fmt="o", color=color, markersize=8)
    ax.set_title("Valve response by pulse width")
    ax.set_xlabel("Pulse width (us)")
    ax.set_ylabel("Windowed response (raw)")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    path = plot_dir / "valve_char_response_by_width.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def generate_valve_trace_artifacts(artifacts: RunArtifacts) -> ValveTraceArtifacts | None:
    sources = _trace_sources(artifacts.run_dir)
    if not sources:
        return None
    trace_dir = artifacts.traces_dir / "valve_characterization"
    plot_dir = artifacts.plots_dir / "valve_characterization"
    plot_dir.mkdir(parents=True, exist_ok=True)
    copied = _copy_trace_sources(sources, trace_dir)
    traces, rows = _load_rows(copied)
    summary = _summary_by_condition(rows)

    analysis_json = plot_dir / "valve_trace_analysis.json"
    analysis_json.write_text(
        json.dumps(
            {
                "schema_version": "valve_trace_analysis_v1",
                "baseline_window_ms": BASELINE_WINDOW_MS,
                "response_window_ms": RESPONSE_WINDOW_MS,
                "replicate_count": len(rows),
                "valid_replicate_count": sum(1 for row in rows if row.get("valid")),
                "conditions": summary,
                "replicates": rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    replicate_csv = plot_dir / "valve_trace_replicates.csv"
    _write_csv(replicate_csv, rows)

    plot_items = _plot_inputs(traces, rows)
    plot_paths: list[Path] = []
    for channel in ("p", "r"):
        full = _plot_full_timecourse(plot_items, plot_dir, channel)
        if full is not None:
            plot_paths.append(full)
        for width in (1500, 3000, 4500):
            overlay = _plot_overlay(plot_items, plot_dir, channel, width)
            if overlay is not None:
                plot_paths.append(overlay)
    summary_plot = _plot_response_summary(rows, plot_dir)
    if summary_plot is not None:
        plot_paths.append(summary_plot)

    return ValveTraceArtifacts(
        trace_dir=trace_dir,
        plot_dir=plot_dir,
        analysis_json=analysis_json,
        replicate_csv=replicate_csv,
        plot_paths=tuple(plot_paths),
        replicate_count=len(rows),
    )
