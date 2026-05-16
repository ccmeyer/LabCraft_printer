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
RING_WINDOW_AFTER_PULSE_END_MS = 60.0
SETTLED_START_AFTER_PULSE_END_MS = 80.0
SETTLED_END_AFTER_PULSE_END_MS = 150.0
LATENCY_MIN_THRESHOLD_RAW = 5.0
LATENCY_BASELINE_STD_MULTIPLIER = 6.0


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


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _first_event(events: list[dict[str, Any]], event_name: str) -> dict[str, Any] | None:
    for event in events:
        if event.get("event_name") == event_name:
            return event
    return None


def _sample_at_dt(samples: list[dict[str, Any]], dt_ms: float) -> dict[str, Any] | None:
    for sample in samples:
        if float(sample.get("dt_ms", 0)) == dt_ms:
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
    if not samples or pulse_start is None or pulse_end is None:
        row["reason"] = "missing_samples_or_pulse_events"
        return row

    start_ms = float(pulse_start.get("dt_ms", 0))
    end_ms = float(pulse_end.get("dt_ms", start_ms))
    baseline_start_ms = max(0.0, start_ms - BASELINE_WINDOW_MS)
    ring_start_ms = start_ms
    ring_end_ms = end_ms + RING_WINDOW_AFTER_PULSE_END_MS
    settled_start_ms = end_ms + SETTLED_START_AFTER_PULSE_END_MS
    settled_end_ms = end_ms + SETTLED_END_AFTER_PULSE_END_MS

    baseline_samples = [
        float(sample.get("raw_pressure", 0))
        for sample in samples
        if baseline_start_ms <= float(sample.get("dt_ms", 0)) <= start_ms
    ]
    ring_samples = [
        sample
        for sample in samples
        if ring_start_ms <= float(sample.get("dt_ms", 0)) <= ring_end_ms
    ]
    settled_samples = [
        sample
        for sample in samples
        if settled_start_ms <= float(sample.get("dt_ms", 0)) <= settled_end_ms
    ]
    if not baseline_samples or not ring_samples or not settled_samples:
        row["reason"] = "missing_baseline_ring_or_settled_samples"
        return row

    baseline_mean = _mean(baseline_samples)
    baseline_std = _std(baseline_samples)
    baseline_min = min(baseline_samples)
    baseline_max = max(baseline_samples)
    latency_threshold = max(LATENCY_MIN_THRESHOLD_RAW, baseline_std * LATENCY_BASELINE_STD_MULTIPLIER)

    ring_pressures = [float(sample.get("raw_pressure", 0)) for sample in ring_samples]
    min_pressure = min(ring_pressures)
    max_pressure = max(ring_pressures)
    trough_dt = float(min(ring_samples, key=lambda sample: float(sample.get("raw_pressure", 0))).get("dt_ms", end_ms))
    peak_dt = float(max(ring_samples, key=lambda sample: float(sample.get("raw_pressure", 0))).get("dt_ms", start_ms))
    trough_drop_raw = max(0.0, baseline_mean - min_pressure)
    spike_raw = max(0.0, max_pressure - baseline_mean)

    ring_sample = max(
        ring_samples,
        key=lambda sample: abs(float(sample.get("raw_pressure", 0)) - baseline_mean),
    )
    ring_dt = float(ring_sample.get("dt_ms", start_ms))
    ring_pressure = float(ring_sample.get("raw_pressure", baseline_mean))
    ring_amp = abs(ring_pressure - baseline_mean)

    latency_sample = next(
        (
            sample
            for sample in ring_samples
            if abs(float(sample.get("raw_pressure", 0)) - baseline_mean) >= latency_threshold
        ),
        None,
    )
    if latency_sample is None:
        row["reason"] = "missing_latency_threshold_crossing"
        return row
    latency_dt = float(latency_sample.get("dt_ms", start_ms))
    latency_pressure = float(latency_sample.get("raw_pressure", baseline_mean))

    settled_pressures = [float(sample.get("raw_pressure", 0)) for sample in settled_samples]
    settled_pressure = _median(settled_pressures)
    settled_mean = _mean(settled_pressures)
    settled_std = _std(settled_pressures)
    settled_span = max(settled_pressures) - min(settled_pressures)
    settled_drop = max(0.0, baseline_mean - settled_pressure)

    row.update(
        {
            "valid": True,
            "sample_count": len(samples),
            "event_count": len(events),
            "pulse_start_ms": start_ms,
            "pulse_end_ms": end_ms,
            "baseline_start_ms": baseline_start_ms,
            "baseline_end_ms": start_ms,
            "baseline_mean_raw": baseline_mean,
            "baseline_std_raw": baseline_std,
            "baseline_span_raw": baseline_max - baseline_min,
            "ring_start_ms": ring_start_ms,
            "ring_end_ms": ring_end_ms,
            "ring_amp_raw": ring_amp,
            "ring_dt_ms": ring_dt,
            "ring_after_start_ms": ring_dt - start_ms,
            "ring_pressure_raw": ring_pressure,
            "latency_threshold_raw": latency_threshold,
            "latency_ms": latency_dt - start_ms,
            "latency_dt_ms": latency_dt,
            "latency_pressure_raw": latency_pressure,
            "settled_start_ms": settled_start_ms,
            "settled_end_ms": settled_end_ms,
            "settled_pressure_raw": settled_pressure,
            "settled_mean_pressure_raw": settled_mean,
            "settled_std_raw": settled_std,
            "settled_span_raw": settled_span,
            "settled_drop_raw": settled_drop,
            "min_pressure_raw": min_pressure,
            "max_pressure_raw": max_pressure,
            "trough_pressure_raw": min_pressure,
            "trough_dt_ms": trough_dt,
            "trough_after_start_ms": trough_dt - start_ms,
            "trough_after_end_ms": trough_dt - end_ms,
            "trough_drop_raw": trough_drop_raw,
            "peak_pressure_raw": max_pressure,
            "peak_dt_ms": peak_dt,
            "peak_after_start_ms": peak_dt - start_ms,
            "peak_after_end_ms": peak_dt - end_ms,
            "spike_raw": spike_raw,
            "rise_raw": spike_raw,
            "drop_raw": settled_drop,
            "response_raw": settled_drop,
            "response_kind": "settled_drop",
            "selected_pressure_raw": settled_pressure,
            "selected_dt_ms": (settled_start_ms + settled_end_ms) / 2.0,
            "selected_after_start_ms": ((settled_start_ms + settled_end_ms) / 2.0) - start_ms,
            "snr_std": None if baseline_std <= 0.0 else settled_drop / baseline_std,
            "snr_span": None if (baseline_max - baseline_min) <= 0.0 else settled_drop / (baseline_max - baseline_min),
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
        settled = [float(row.get("settled_drop_raw") or 0) for row in subset]
        ring = [float(row.get("ring_amp_raw") or 0) for row in subset]
        latency = [float(row.get("latency_ms") or 0) for row in subset]
        baseline_std = [float(row.get("baseline_std_raw") or 0) for row in subset]
        summary.append(
            {
                "channel": channel,
                "channel_name": "print" if channel == "p" else "refuel",
                "width_us": width_us,
                "replicate_count": len(subset),
                "settled_drop_mean_raw": _mean(settled),
                "settled_drop_std_raw": _std(settled),
                "settled_drop_span_raw": (max(settled) - min(settled)) if settled else 0.0,
                "ring_amp_mean_raw": _mean(ring),
                "ring_amp_std_raw": _std(ring),
                "latency_mean_ms": _mean(latency),
                "latency_std_ms": _std(latency),
                "baseline_std_mean_raw": _mean(baseline_std),
                "drop_mean_raw": _mean(settled),
                "drop_std_raw": _std(settled),
                "drop_span_raw": (max(settled) - min(settled)) if settled else 0.0,
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
        "baseline_mean_raw",
        "baseline_std_raw",
        "baseline_span_raw",
        "ring_start_ms",
        "ring_end_ms",
        "ring_amp_raw",
        "ring_dt_ms",
        "ring_after_start_ms",
        "ring_pressure_raw",
        "latency_threshold_raw",
        "latency_ms",
        "latency_dt_ms",
        "latency_pressure_raw",
        "settled_start_ms",
        "settled_end_ms",
        "settled_pressure_raw",
        "settled_mean_pressure_raw",
        "settled_std_raw",
        "settled_span_raw",
        "settled_drop_raw",
        "min_pressure_raw",
        "max_pressure_raw",
        "trough_pressure_raw",
        "trough_dt_ms",
        "trough_after_start_ms",
        "trough_after_end_ms",
        "trough_drop_raw",
        "peak_pressure_raw",
        "peak_dt_ms",
        "peak_after_start_ms",
        "peak_after_end_ms",
        "spike_raw",
        "rise_raw",
        "drop_raw",
        "response_raw",
        "response_kind",
        "selected_pressure_raw",
        "selected_dt_ms",
        "selected_after_start_ms",
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
        end = offset + float(row.get("pulse_end_ms") or 0)
        latency = offset + float(row.get("latency_dt_ms") or 0)
        ring = offset + float(row.get("ring_dt_ms") or 0)
        settled_start = offset + float(row.get("settled_start_ms") or 0)
        settled_end = offset + float(row.get("settled_end_ms") or 0)
        ax.axvline(start, color="tab:orange", linestyle="--", linewidth=0.7, alpha=0.5)
        ax.axvline(end, color="tab:gray", linestyle=":", linewidth=0.7, alpha=0.45)
        ax.scatter([latency], [float(row.get("latency_pressure_raw") or 0)], color="tab:green", s=18, zorder=4)
        ax.scatter([ring], [float(row.get("ring_pressure_raw") or 0)], color="tab:red", s=18, zorder=4)
        ax.hlines(
            float(row.get("baseline_mean_raw") or 0),
            offset + float(row.get("baseline_start_ms") or 0),
            offset + float(row.get("baseline_end_ms") or 0),
            color="black",
            linewidth=1.0,
            alpha=0.7,
        )
        ax.hlines(
            float(row.get("settled_pressure_raw") or 0),
            settled_start,
            settled_end,
            color="tab:purple",
            linewidth=1.0,
            alpha=0.65,
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
    pulse_end_offsets: list[float] = []
    settled_start_offsets: list[float] = []
    settled_end_offsets: list[float] = []
    for _path, trace, row in subset:
        samples = _safe_list(trace, "samples")
        start = float(row.get("pulse_start_ms") or 0)
        pulse_end_offset = float(row.get("pulse_end_ms") or start) - start
        pulse_end_offsets.append(pulse_end_offset)
        settled_start_offsets.append(float(row.get("settled_start_ms") or start) - start)
        settled_end_offsets.append(float(row.get("settled_end_ms") or start) - start)
        baseline = float(row.get("baseline_mean_raw") or 0)
        x = [float(sample.get("dt_ms", 0)) - start for sample in samples]
        y = [baseline - float(sample.get("raw_pressure", 0)) for sample in samples]
        ax.plot(x, y, linewidth=1.1, alpha=0.65)
        ax.axvline(pulse_end_offset, color="tab:gray", linestyle=":", linewidth=0.6, alpha=0.25)
        ax.scatter(
            [float(row.get("latency_dt_ms") or start) - start],
            [baseline - float(row.get("latency_pressure_raw") or baseline)],
            color="tab:green",
            s=16,
            alpha=0.75,
        )
        ax.scatter(
            [float(row.get("ring_dt_ms") or start) - start],
            [baseline - float(row.get("ring_pressure_raw") or baseline)],
            color="tab:red",
            s=16,
            alpha=0.75,
        )
        ax.hlines(
            float(row.get("settled_drop_raw") or 0),
            float(row.get("settled_start_ms") or start) - start,
            float(row.get("settled_end_ms") or start) - start,
            color="tab:purple",
            linewidth=1.2,
            alpha=0.55,
        )
    ax.axvline(0, color="tab:orange", linestyle="--", linewidth=1.0, label="pulse start")
    if pulse_end_offsets:
        ax.axvspan(
            0,
            max(pulse_end_offsets) + RING_WINDOW_AFTER_PULSE_END_MS,
            color="tab:red",
            alpha=0.04,
            label="ring window",
        )
        ax.axvspan(
            min(settled_start_offsets),
            max(settled_end_offsets),
            color="tab:purple",
            alpha=0.08,
            label="settled window",
        )
        ax.plot([], [], color="tab:gray", linestyle=":", linewidth=1.0, label="pulse end")
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
        ys = [float(row.get("settled_drop_raw") or 0) for row in subset]
        ax.scatter(xs, ys, color=color, alpha=0.45, label=f"{label} replicates")
        for width in sorted({int(row.get("width_us") or 0) for row in subset}):
            responses = [float(row.get("settled_drop_raw") or 0) for row in subset if int(row.get("width_us") or 0) == width]
            if responses:
                ax.errorbar([width], [_mean(responses)], yerr=[_std(responses)], fmt="o", color=color, markersize=8)
    ax.set_title("Valve settled pressure drop by pulse width")
    ax.set_xlabel("Pulse width (us)")
    ax.set_ylabel("Settled pressure drop (raw)")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    path = plot_dir / "valve_char_response_by_width.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _plot_ringing_summary(rows: list[dict[str, Any]], plot_dir: Path) -> Path | None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    valid = [row for row in rows if row.get("valid")]
    if not valid:
        return None
    fig, (ax_amp, ax_lat) = plt.subplots(2, 1, figsize=(9, 8), sharex=True)
    for channel, color, label in (("p", "tab:blue", "print"), ("r", "tab:green", "refuel")):
        subset = [row for row in valid if row.get("channel") == channel]
        if not subset:
            continue
        xs = [float(row.get("width_us") or 0) for row in subset]
        amps = [float(row.get("ring_amp_raw") or 0) for row in subset]
        lats = [float(row.get("latency_ms") or 0) for row in subset]
        ax_amp.scatter(xs, amps, color=color, alpha=0.4, label=f"{label} ring")
        ax_lat.scatter(xs, lats, color=color, alpha=0.4, label=f"{label} latency")
        for width in sorted({int(row.get("width_us") or 0) for row in subset}):
            width_rows = [row for row in subset if int(row.get("width_us") or 0) == width]
            amp_values = [float(row.get("ring_amp_raw") or 0) for row in width_rows]
            lat_values = [float(row.get("latency_ms") or 0) for row in width_rows]
            if amp_values:
                ax_amp.errorbar([width], [_mean(amp_values)], yerr=[_std(amp_values)], fmt="o", color=color, markersize=8)
            if lat_values:
                ax_lat.errorbar([width], [_mean(lat_values)], yerr=[_std(lat_values)], fmt="o", color=color, markersize=8)
    ax_amp.set_title("Valve ringing amplitude by pulse width")
    ax_amp.set_ylabel("Ring amplitude (raw)")
    ax_amp.grid(True, alpha=0.25)
    ax_amp.legend(loc="best", fontsize=8)
    ax_lat.set_title("Valve latency by pulse width")
    ax_lat.set_xlabel("Pulse width (us)")
    ax_lat.set_ylabel("Latency from pulse start (ms)")
    ax_lat.grid(True, alpha=0.25)
    ax_lat.legend(loc="best", fontsize=8)
    fig.tight_layout()
    path = plot_dir / "valve_char_ringing_by_width.png"
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
                "schema_version": "valve_trace_analysis_v3",
                "baseline_window_ms": BASELINE_WINDOW_MS,
                "ring_window_after_pulse_end_ms": RING_WINDOW_AFTER_PULSE_END_MS,
                "settled_start_after_pulse_end_ms": SETTLED_START_AFTER_PULSE_END_MS,
                "settled_end_after_pulse_end_ms": SETTLED_END_AFTER_PULSE_END_MS,
                "latency_min_threshold_raw": LATENCY_MIN_THRESHOLD_RAW,
                "latency_baseline_std_multiplier": LATENCY_BASELINE_STD_MULTIPLIER,
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
    ringing_plot = _plot_ringing_summary(rows, plot_dir)
    if ringing_plot is not None:
        plot_paths.append(ringing_plot)

    return ValveTraceArtifacts(
        trace_dir=trace_dir,
        plot_dir=plot_dir,
        analysis_json=analysis_json,
        replicate_csv=replicate_csv,
        plot_paths=tuple(plot_paths),
        replicate_count=len(rows),
    )
