from __future__ import annotations

import csv
import copy
import json
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import RunArtifacts


VALVE_TRACE_RE = re.compile(r"^valve_char_(?P<channel>[pr])_(?:seq(?P<sequence>\d+)_)?w(?P<width>\d+)_rep(?P<rep>\d+)$")
VALVE_GAP_TRACE_RE = re.compile(r"^valve_gap_(?P<channel>[pr])_w(?P<width>\d+)_g(?P<gap>\d+)_rep(?P<rep>\d+)$")
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
    report_metrics: dict[int, dict[str, Any]]


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


def _metric_round(value: float | int | None) -> int:
    if value is None:
        return 0
    numeric = float(value)
    if not math.isfinite(numeric):
        return 0
    if numeric >= 0:
        return int(numeric + 0.5)
    return int(numeric - 0.5)


def _cv_pct(values: list[float]) -> int:
    mean = _mean(values)
    if mean <= 0.0:
        return 0
    return _metric_round((_std(values) * 100.0) / mean)


def _linearity_metrics(m15: int, m30: int, m45: int) -> dict[str, int]:
    monotonic = 1 if m15 <= m30 <= m45 else 0
    gain = (m45 - m15) if monotonic else abs(m45 - m15)
    if gain <= 0:
        lin = 0 if m30 == m15 else 100
    else:
        lin = _metric_round((abs((2 * m30) - (m15 + m45)) * 100.0) / (2.0 * gain))
    return {"mono": monotonic, "gain": gain, "lin": lin}


def _corr(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    x_mean = _mean(xs)
    y_mean = _mean(ys)
    x_var = sum((x - x_mean) ** 2 for x in xs)
    y_var = sum((y - y_mean) ** 2 for y in ys)
    if x_var <= 0.0 or y_var <= 0.0:
        return None
    cov = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    return cov / math.sqrt(x_var * y_var)


def _first_event(events: list[dict[str, Any]], event_name: str) -> dict[str, Any] | None:
    for event in events:
        if event.get("event_name") == event_name:
            return event
    return None


def _event_i32(event: dict[str, Any] | None) -> int | None:
    if event is None:
        return None
    if "value_i32" in event:
        return int(event["value_i32"])
    raw = int(event.get("value0") or 0) | (int(event.get("value1") or 0) << 16)
    if raw >= 0x80000000:
        raw -= 0x100000000
    return raw


def _parse_trace_name(name: str) -> dict[str, Any] | None:
    match = VALVE_TRACE_RE.match(str(name or ""))
    if match:
        channel = match.group("channel")
        sequence = match.group("sequence")
        sequence_index = int(sequence) if sequence else None
        return {
            "trace_family": "valve_char",
            "channel": channel,
            "channel_name": "print" if channel == "p" else "refuel",
            "sequence_index": sequence_index,
            "sequence_slot": None if sequence_index is None else ((sequence_index - 1) % 6) + 1,
            "width_us": int(match.group("width")),
            "replicate": int(match.group("rep")),
        }
    gap_match = VALVE_GAP_TRACE_RE.match(str(name or ""))
    if gap_match:
        channel = gap_match.group("channel")
        return {
            "trace_family": "valve_gap",
            "channel": channel,
            "channel_name": "print" if channel == "p" else "refuel",
            "width_us": int(gap_match.group("width")),
            "gap_ms": int(gap_match.group("gap")),
            "replicate": int(gap_match.group("rep")),
        }
    return None


def analyze_valve_trace(trace: dict[str, Any], *, source_path: str | Path | None = None) -> dict[str, Any]:
    metadata = _parse_trace_name(str(trace.get("name") or "")) or {}
    samples = _safe_list(trace, "samples")
    events = _safe_list(trace, "events")
    pulse_start = _first_event(events, "pulse_start")
    pulse_end = _first_event(events, "pulse_end")
    valve_sequence = _first_event(events, "valve_sequence")
    valve_gap = _first_event(events, "valve_gap")
    valve_previous_width = _first_event(events, "valve_previous_width")
    valve_interval = _first_event(events, "valve_interval")
    motor_position_event = _first_event(events, "motor_position")
    row: dict[str, Any] = {
        "trace_file": "" if source_path is None else str(source_path),
        "test_id": trace.get("test_id"),
        "name": trace.get("name"),
        **metadata,
        "valid": False,
        "latency_valid": False,
        "ring_valid": False,
        "excluded": metadata.get("trace_family") == "valve_char" and int(metadata.get("replicate") or 0) == 1,
        "exclude_reason": "first_after_width_change"
        if metadata.get("trace_family") == "valve_char" and int(metadata.get("replicate") or 0) == 1
        else "",
    }
    if valve_sequence is not None:
        sequence_index = int(valve_sequence.get("value0") or 0)
        row["sequence_index"] = sequence_index
        row["sequence_slot"] = ((sequence_index - 1) % 6) + 1 if sequence_index > 0 else None
        row["sequence_width_us"] = int(valve_sequence.get("value1") or 0)
    if motor_position_event is not None:
        row["motor_position"] = _event_i32(motor_position_event)
    if valve_gap is not None:
        row["gap_ms"] = int(valve_gap.get("value0") or 0)
    if valve_previous_width is not None:
        row["previous_width_us"] = int(valve_previous_width.get("value0") or 0)
        row["sequence_width_us"] = int(valve_previous_width.get("value1") or row.get("width_us") or 0)
    if valve_interval is not None:
        row["actual_interval_ms"] = int(valve_interval.get("value0") or 0)
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
    if not baseline_samples or not settled_samples:
        row["reason"] = "missing_baseline_or_settled_samples"
        return row

    baseline_mean = _mean(baseline_samples)
    baseline_std = _std(baseline_samples)
    baseline_min = min(baseline_samples)
    baseline_max = max(baseline_samples)
    latency_threshold = max(LATENCY_MIN_THRESHOLD_RAW, baseline_std * LATENCY_BASELINE_STD_MULTIPLIER)

    ring_valid = bool(ring_samples)
    min_pressure = baseline_mean
    max_pressure = baseline_mean
    trough_dt = end_ms
    peak_dt = start_ms
    trough_drop_raw = 0.0
    spike_raw = 0.0
    ring_dt = None
    ring_pressure = None
    ring_amp = None
    latency_dt = None
    latency_pressure = None
    latency_reason = ""
    if ring_samples:
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
        if latency_sample is not None:
            latency_dt = float(latency_sample.get("dt_ms", start_ms))
            latency_pressure = float(latency_sample.get("raw_pressure", baseline_mean))
        else:
            latency_reason = "missing_latency_threshold_crossing"
    else:
        latency_reason = "missing_ring_samples"

    settled_pressures = [float(sample.get("raw_pressure", 0)) for sample in settled_samples]
    settled_pressure = _median(settled_pressures)
    settled_mean = _mean(settled_pressures)
    settled_std = _std(settled_pressures)
    settled_span = max(settled_pressures) - min(settled_pressures)
    settled_drop = max(0.0, baseline_mean - settled_pressure)

    row.update(
        {
            "valid": True,
            "latency_valid": latency_dt is not None,
            "ring_valid": ring_valid,
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
            "ring_after_start_ms": None if ring_dt is None else ring_dt - start_ms,
            "ring_pressure_raw": ring_pressure,
            "latency_threshold_raw": latency_threshold,
            "latency_ms": None if latency_dt is None else latency_dt - start_ms,
            "latency_dt_ms": latency_dt,
            "latency_pressure_raw": latency_pressure,
            "latency_reason": latency_reason,
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
        for path in run_dir.glob("*_trace_247[3-9]_valve_*.json")
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


def _row_sort_key(row: dict[str, Any]) -> tuple[str, int, int, int]:
    sequence = row.get("sequence_index")
    if sequence is None or sequence == "":
        gap = int(row.get("gap_ms") or 0)
        sequence_value = 100000 + (int(row.get("width_us") or 0) * 10000) + gap
    else:
        sequence_value = int(sequence)
    return (
        str(row.get("channel") or ""),
        sequence_value,
        int(row.get("width_us") or 0),
        int(row.get("replicate") or 0),
    )


def _annotate_motor_position_deltas(rows: list[dict[str, Any]]) -> None:
    first_by_channel: dict[str, int] = {}
    for row in sorted(rows, key=_row_sort_key):
        channel = str(row.get("channel") or "")
        position = row.get("motor_position")
        if channel and position not in (None, ""):
            first_by_channel.setdefault(channel, int(position))
    for row in rows:
        channel = str(row.get("channel") or "")
        position = row.get("motor_position")
        if channel in first_by_channel and position not in (None, ""):
            row["motor_position_delta_from_first"] = int(position) - first_by_channel[channel]


def _load_rows(trace_paths: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    traces: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for path in trace_paths:
        trace = json.loads(path.read_text(encoding="utf-8"))
        traces.append({"path": str(path), "payload": trace})
        rows.append(analyze_valve_trace(trace, source_path=path))
    _annotate_motor_position_deltas(rows)
    rows.sort(key=_row_sort_key)
    return traces, rows


def _summary_by_condition(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    keys = sorted({(row.get("channel"), row.get("width_us")) for row in rows if row.get("valid")})
    for channel, width_us in keys:
        all_subset = [
            row for row in rows if row.get("valid") and row.get("channel") == channel and row.get("width_us") == width_us
        ]
        subset = [row for row in all_subset if not row.get("excluded")]
        settled = [float(row.get("settled_drop_raw") or 0) for row in subset]
        ring = [float(row.get("ring_amp_raw") or 0) for row in subset if row.get("ring_valid")]
        latency = [float(row.get("latency_ms") or 0) for row in subset if row.get("latency_valid")]
        baseline_std = [float(row.get("baseline_std_raw") or 0) for row in subset]
        motor_positions = [
            float(row["motor_position"])
            for row in subset
            if row.get("motor_position") not in (None, "")
        ]
        motor_responses = [
            float(row.get("settled_drop_raw") or 0)
            for row in subset
            if row.get("motor_position") not in (None, "")
        ]
        summary.append(
            {
                "channel": channel,
                "channel_name": "print" if channel == "p" else "refuel",
                "width_us": width_us,
                "replicate_count": len(all_subset),
                "steady_replicate_count": len(subset),
                "excluded_count": len(all_subset) - len(subset),
                "settled_drop_mean_raw": _mean(settled),
                "settled_drop_std_raw": _std(settled),
                "settled_drop_span_raw": (max(settled) - min(settled)) if settled else 0.0,
                "ring_amp_mean_raw": _mean(ring),
                "ring_amp_std_raw": _std(ring),
                "latency_mean_ms": _mean(latency),
                "latency_std_ms": _std(latency),
                "baseline_std_mean_raw": _mean(baseline_std),
                "motor_position_min": min(motor_positions) if motor_positions else None,
                "motor_position_max": max(motor_positions) if motor_positions else None,
                "motor_position_span": (max(motor_positions) - min(motor_positions)) if motor_positions else None,
                "settled_drop_motor_position_corr": _corr(motor_positions, motor_responses),
                "drop_mean_raw": _mean(settled),
                "drop_std_raw": _std(settled),
                "drop_span_raw": (max(settled) - min(settled)) if settled else 0.0,
            }
        )
    return summary


def _summary_by_gap_condition(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    valid = _gap_rows(rows)
    keys = sorted({(row.get("channel"), row.get("width_us"), row.get("gap_ms")) for row in valid})
    for channel, width_us, gap_ms in keys:
        subset = [
            row
            for row in valid
            if row.get("channel") == channel and row.get("width_us") == width_us and row.get("gap_ms") == gap_ms
        ]
        settled = [float(row.get("settled_drop_raw") or 0) for row in subset]
        intervals = [
            float(row.get("actual_interval_ms") or 0)
            for row in subset
            if float(row.get("actual_interval_ms") or 0) > 0
        ]
        summary.append(
            {
                "channel": channel,
                "channel_name": "print" if channel == "p" else "refuel",
                "width_us": width_us,
                "gap_ms": gap_ms,
                "replicate_count": len(subset),
                "settled_drop_mean_raw": _mean(settled),
                "settled_drop_std_raw": _std(settled),
                "settled_drop_span_raw": (max(settled) - min(settled)) if settled else 0.0,
                "actual_interval_mean_ms": _mean(intervals),
                "actual_interval_span_ms": (max(intervals) - min(intervals)) if intervals else 0.0,
            }
        )
    return summary


def _rows_for(rows: list[dict[str, Any]], *, family: str, channel: str, width_us: int | None = None, gap_ms: int | None = None) -> list[dict[str, Any]]:
    subset = [
        row
        for row in rows
        if row.get("trace_family") == family and row.get("channel") == channel
    ]
    if width_us is not None:
        subset = [row for row in subset if int(row.get("width_us") or 0) == width_us]
    if gap_ms is not None:
        subset = [row for row in subset if int(row.get("gap_ms") or 0) == gap_ms]
    return subset


def _valid_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("valid")]


def _values(rows: list[dict[str, Any]], key: str) -> list[float]:
    return [float(row.get(key) or 0.0) for row in rows]


def _mean_metric(rows: list[dict[str, Any]], key: str) -> int:
    return _metric_round(_mean(_values(rows, key)))


def _valve_char_channel_metrics(rows: list[dict[str, Any]], channel: str) -> dict[str, Any]:
    expected_replicates_per_width = 10
    expected_total = expected_replicates_per_width * 3
    channel_rows = _rows_for(rows, family="valve_char", channel=channel)
    valid = _valid_rows(channel_rows)
    metrics: dict[str, Any] = {
        "rej": max(0, expected_total - len(valid)),
        "lat_miss": sum(1 for row in valid if not row.get("latency_valid")),
        "ring_miss": sum(1 for row in valid if not row.get("ring_valid")),
        "excl": sum(1 for row in channel_rows if row.get("excluded")),
        "rw": _metric_round(RING_WINDOW_AFTER_PULSE_END_MS),
        "sw": _metric_round(SETTLED_START_AFTER_PULSE_END_MS),
    }
    means: dict[int, int] = {}
    for width, label in ((1500, "15"), (3000, "30"), (4500, "45")):
        width_rows = _rows_for(rows, family="valve_char", channel=channel, width_us=width)
        steady = [row for row in _valid_rows(width_rows) if not row.get("excluded")]
        means[width] = _mean_metric(steady, "settled_drop_raw")
        metrics[f"m{label}"] = means[width]
        metrics[f"cv{label}"] = _cv_pct(_values(steady, "settled_drop_raw"))
        metrics[f"rg{label}"] = _mean_metric([row for row in steady if row.get("ring_valid")], "ring_amp_raw")
        metrics[f"lt{label}"] = _mean_metric([row for row in steady if row.get("latency_valid")], "latency_ms")
    metrics["mono"] = _linearity_metrics(means[1500], means[3000], means[4500])["mono"]
    return metrics


def _valve_balance_metrics(print_metrics: dict[str, Any], refuel_metrics: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "rej": int(print_metrics.get("rej") or 0) + int(refuel_metrics.get("rej") or 0),
        "lat_miss": int(print_metrics.get("lat_miss") or 0) + int(refuel_metrics.get("lat_miss") or 0),
        "ring_miss": int(print_metrics.get("ring_miss") or 0) + int(refuel_metrics.get("ring_miss") or 0),
        "excl": int(print_metrics.get("excl") or 0) + int(refuel_metrics.get("excl") or 0),
    }
    for label in ("15", "30", "45"):
        p_value = int(print_metrics.get(f"m{label}") or 0)
        r_value = int(refuel_metrics.get(f"m{label}") or 0)
        metrics[f"m{label}p"] = p_value
        metrics[f"m{label}r"] = r_value
        metrics[f"r{label}"] = int((p_value * 100) / r_value) if r_value > 0 else 0
        metrics[f"d{label}"] = abs(p_value - r_value)
    return metrics


def _gap_detailed_metrics(rows: list[dict[str, Any]], channel: str) -> dict[str, Any]:
    expected_total = 5 * 8
    channel_rows = [
        row
        for row in _rows_for(rows, family="valve_gap", channel=channel, width_us=1500)
        if row.get("gap_ms") in {250, 500, 1000, 2000, 5000}
    ]
    valid = _valid_rows(channel_rows)
    metrics: dict[str, Any] = {
        "rej": max(0, expected_total - len(valid)),
        "lat_miss": sum(1 for row in valid if not row.get("latency_valid")),
        "ring_miss": sum(1 for row in valid if not row.get("ring_valid")),
    }
    for gap in (250, 500, 1000, 2000, 5000):
        metrics[f"g{gap}"] = _mean_metric(_valid_rows(_rows_for(rows, family="valve_gap", channel=channel, width_us=1500, gap_ms=gap)), "settled_drop_raw")
    return metrics


def _gap_control_metrics(rows: list[dict[str, Any]], channel: str) -> dict[str, Any]:
    expected_total = 4 * 4
    condition_rows = [
        row
        for row in _rows_for(rows, family="valve_gap", channel=channel)
        if int(row.get("width_us") or 0) in {3000, 4500} and int(row.get("gap_ms") or 0) in {500, 2000}
    ]
    valid = _valid_rows(condition_rows)
    metrics: dict[str, Any] = {
        "rej": max(0, expected_total - len(valid)),
        "lat_miss": sum(1 for row in valid if not row.get("latency_valid")),
        "ring_miss": sum(1 for row in valid if not row.get("ring_valid")),
    }
    for width, label in ((3000, "30"), (4500, "45")):
        for gap in (500, 2000):
            metrics[f"m{label}g{gap}"] = _mean_metric(
                _valid_rows(_rows_for(rows, family="valve_gap", channel=channel, width_us=width, gap_ms=gap)),
                "settled_drop_raw",
            )
    return metrics


def _build_report_metrics(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    report_metrics: dict[int, dict[str, Any]] = {}
    if any(row.get("trace_family") == "valve_char" for row in rows):
        print_metrics = _valve_char_channel_metrics(rows, "p")
        refuel_metrics = _valve_char_channel_metrics(rows, "r")
        report_metrics[2473] = print_metrics
        report_metrics[2474] = refuel_metrics
        report_metrics[2475] = _valve_balance_metrics(print_metrics, refuel_metrics)
    if any(row.get("trace_family") == "valve_gap" for row in rows):
        report_metrics[2476] = _gap_detailed_metrics(rows, "p")
        report_metrics[2477] = _gap_detailed_metrics(rows, "r")
        report_metrics[2478] = _gap_control_metrics(rows, "p")
        report_metrics[2479] = _gap_control_metrics(rows, "r")
    return report_metrics


def enrich_raw_selftest_with_valve_metrics(raw_selftest: dict[str, Any], report_metrics: dict[int, dict[str, Any]] | None) -> dict[str, Any]:
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


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "trace_file",
        "test_id",
        "name",
        "channel",
        "channel_name",
        "trace_family",
        "sequence_index",
        "sequence_slot",
        "sequence_width_us",
        "width_us",
        "gap_ms",
        "replicate",
        "previous_width_us",
        "actual_interval_ms",
        "motor_position",
        "motor_position_delta_from_first",
        "valid",
        "latency_valid",
        "ring_valid",
        "excluded",
        "exclude_reason",
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
        "latency_reason",
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
    result.sort(key=lambda item: _row_sort_key(item[2]))
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
        if row.get("sequence_index") not in (None, ""):
            label = f"seq {int(row.get('sequence_index') or 0):02d} / {int(row.get('width_us') or 0)} us"
        else:
            label = f"{int(row.get('width_us') or 0)} us rep {int(row.get('replicate') or 0):02d}"
        ax.plot(t, y, linewidth=1.0, alpha=0.75, label=label)
        start = offset + float(row.get("pulse_start_ms") or 0)
        end = offset + float(row.get("pulse_end_ms") or 0)
        latency = None if not row.get("latency_valid") else offset + float(row.get("latency_dt_ms") or 0)
        ring = None if not row.get("ring_valid") else offset + float(row.get("ring_dt_ms") or 0)
        settled_start = offset + float(row.get("settled_start_ms") or 0)
        settled_end = offset + float(row.get("settled_end_ms") or 0)
        ax.axvline(start, color="tab:orange", linestyle="--", linewidth=0.7, alpha=0.5)
        ax.axvline(end, color="tab:gray", linestyle=":", linewidth=0.7, alpha=0.45)
        if latency is not None:
            ax.scatter([latency], [float(row.get("latency_pressure_raw") or 0)], color="tab:green", s=18, zorder=4)
        if ring is not None:
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
        if row.get("latency_valid"):
            ax.scatter(
                [float(row.get("latency_dt_ms") or start) - start],
                [baseline - float(row.get("latency_pressure_raw") or baseline)],
                color="tab:green",
                s=16,
                alpha=0.75,
            )
        if row.get("ring_valid"):
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
        included = [row for row in subset if not row.get("excluded")]
        excluded = [row for row in subset if row.get("excluded")]
        xs = [float(row.get("width_us") or 0) for row in included]
        ys = [float(row.get("settled_drop_raw") or 0) for row in included]
        if included:
            ax.scatter(xs, ys, color=color, alpha=0.45, label=f"{label} steady reps")
        if excluded:
            ax.scatter(
                [float(row.get("width_us") or 0) for row in excluded],
                [float(row.get("settled_drop_raw") or 0) for row in excluded],
                marker="x",
                color=color,
                alpha=0.8,
                label=f"{label} first after width change",
            )
        for width in sorted({int(row.get("width_us") or 0) for row in subset}):
            responses = [
                float(row.get("settled_drop_raw") or 0)
                for row in included
                if int(row.get("width_us") or 0) == width
            ]
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


def _plot_motor_position_summary(rows: list[dict[str, Any]], plot_dir: Path) -> Path | None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    valid = [
        row
        for row in rows
        if row.get("valid") and row.get("motor_position") not in (None, "")
    ]
    if not valid:
        return None
    fig, (ax_p, ax_r) = plt.subplots(2, 1, figsize=(10, 8), sharex=True, sharey=True)
    axes = {"p": ax_p, "r": ax_r}
    colors = {1500: "tab:blue", 3000: "tab:orange", 4500: "tab:green"}
    for channel, ax in axes.items():
        subset = sorted([row for row in valid if row.get("channel") == channel], key=_row_sort_key)
        if subset:
            ax.plot(
                [float(row.get("motor_position") or 0) for row in subset],
                [float(row.get("settled_drop_raw") or 0) for row in subset],
                color="0.65",
                linewidth=0.9,
                alpha=0.55,
                zorder=1,
                label="chronological path",
            )
        for width in (1500, 3000, 4500):
            width_rows = [row for row in subset if int(row.get("width_us") or 0) == width]
            if not width_rows:
                continue
            included = [row for row in width_rows if not row.get("excluded")]
            excluded = [row for row in width_rows if row.get("excluded")]
            if included:
                ax.scatter(
                    [float(row.get("motor_position") or 0) for row in included],
                    [float(row.get("settled_drop_raw") or 0) for row in included],
                    color=colors[width],
                    alpha=0.7,
                    label=f"{width} us steady",
                    zorder=3,
                )
            if excluded:
                ax.scatter(
                    [float(row.get("motor_position") or 0) for row in excluded],
                    [float(row.get("settled_drop_raw") or 0) for row in excluded],
                    marker="x",
                    color=colors[width],
                    alpha=0.9,
                    label=f"{width} us first",
                    zorder=4,
                )
        ax.set_title(f"{'Print' if channel == 'p' else 'Refuel'} settled drop vs regulator motor position")
        ax.set_ylabel("Settled pressure drop (raw)")
        ax.grid(True, alpha=0.25)
        ax.legend(loc="best", fontsize=8)
    ax_r.set_xlabel("Regulator motor position (steps)")
    fig.tight_layout()
    path = plot_dir / "valve_char_settled_drop_vs_motor_position.png"
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
        ring_rows = [row for row in subset if row.get("ring_valid")]
        amps = [float(row.get("ring_amp_raw") or 0) for row in ring_rows]
        lat_rows = [row for row in subset if row.get("latency_valid")]
        lats = [float(row.get("latency_ms") or 0) for row in lat_rows]
        ax_amp.scatter([float(row.get("width_us") or 0) for row in ring_rows], amps, color=color, alpha=0.4, label=f"{label} ring")
        ax_lat.scatter([float(row.get("width_us") or 0) for row in lat_rows], lats, color=color, alpha=0.4, label=f"{label} latency")
        for width in sorted({int(row.get("width_us") or 0) for row in subset}):
            width_rows = [row for row in subset if int(row.get("width_us") or 0) == width]
            amp_values = [float(row.get("ring_amp_raw") or 0) for row in width_rows if row.get("ring_valid")]
            lat_values = [float(row.get("latency_ms") or 0) for row in width_rows if row.get("latency_valid")]
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


def _gap_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("valid") and row.get("gap_ms") not in (None, "")]


def _plot_gap_response_by_gap(rows: list[dict[str, Any]], plot_dir: Path) -> Path | None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    valid = _gap_rows(rows)
    if not valid:
        return None
    fig, (ax_p, ax_r) = plt.subplots(2, 1, figsize=(10, 8), sharex=True, sharey=True)
    axes = {"p": ax_p, "r": ax_r}
    colors = {1500: "tab:blue", 3000: "tab:orange", 4500: "tab:green"}
    for channel, ax in axes.items():
        subset = [row for row in valid if row.get("channel") == channel]
        for width in (1500, 3000, 4500):
            width_rows = [row for row in subset if int(row.get("width_us") or 0) == width]
            if not width_rows:
                continue
            xs = [float(row.get("gap_ms") or 0) for row in width_rows]
            ys = [float(row.get("settled_drop_raw") or 0) for row in width_rows]
            ax.scatter(xs, ys, color=colors[width], alpha=0.45, label=f"{width} us")
            for gap in sorted({int(row.get("gap_ms") or 0) for row in width_rows}):
                responses = [float(row.get("settled_drop_raw") or 0) for row in width_rows if int(row.get("gap_ms") or 0) == gap]
                if responses:
                    ax.errorbar([gap], [_mean(responses)], yerr=[_std(responses)], fmt="o", color=colors[width], markersize=8)
        ax.set_title(f"{'Print' if channel == 'p' else 'Refuel'} settled drop vs post-ready gap")
        ax.set_ylabel("Settled pressure drop (raw)")
        ax.grid(True, alpha=0.25)
        ax.legend(loc="best", fontsize=8)
    ax_r.set_xlabel("Post-ready settle gap (ms)")
    fig.tight_layout()
    path = plot_dir / "valve_gap_settled_drop_by_gap.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _plot_gap_replicates(rows: list[dict[str, Any]], plot_dir: Path) -> Path | None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    valid_or_gap = [row for row in rows if row.get("gap_ms") not in (None, "")]
    if not valid_or_gap:
        return None
    detailed = [row for row in valid_or_gap if int(row.get("width_us") or 0) == 1500]
    if not detailed:
        return None
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True, sharey=True)
    colors = {250: "tab:blue", 500: "tab:orange", 1000: "tab:green", 2000: "tab:red", 5000: "tab:purple"}
    for ax, channel in zip(axes, ("p", "r")):
        subset = [row for row in detailed if row.get("channel") == channel]
        for gap in (250, 500, 1000, 2000, 5000):
            gap_rows = sorted([row for row in subset if int(row.get("gap_ms") or 0) == gap], key=lambda row: int(row.get("replicate") or 0))
            if not gap_rows:
                continue
            xs = [int(row.get("replicate") or 0) for row in gap_rows]
            ys = [float(row.get("settled_drop_raw") or 0) if row.get("valid") else math.nan for row in gap_rows]
            ax.plot(xs, ys, marker="o", color=colors[gap], linewidth=1.2, label=f"{gap} ms")
        ax.set_title(f"{'Print' if channel == 'p' else 'Refuel'} 1500 us drop by replicate")
        ax.set_ylabel("Settled pressure drop (raw)")
        ax.grid(True, alpha=0.25)
        ax.legend(loc="best", fontsize=8)
    axes[-1].set_xlabel("Replicate within gap")
    fig.tight_layout()
    path = plot_dir / "valve_gap_1500_drop_by_replicate.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _plot_gap_interval_response(rows: list[dict[str, Any]], plot_dir: Path) -> Path | None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    valid = [row for row in _gap_rows(rows) if row.get("actual_interval_ms") not in (None, "")]
    if not valid:
        return None
    fig, ax = plt.subplots(figsize=(10, 6))
    colors = {1500: "tab:blue", 3000: "tab:orange", 4500: "tab:green"}
    for channel, marker in (("p", "o"), ("r", "s")):
        for width in (1500, 3000, 4500):
            subset = [
                row
                for row in valid
                if row.get("channel") == channel and int(row.get("width_us") or 0) == width and float(row.get("actual_interval_ms") or 0) > 0
            ]
            if not subset:
                continue
            xs = [float(row.get("actual_interval_ms") or 0) for row in subset]
            ys = [float(row.get("settled_drop_raw") or 0) for row in subset]
            ax.scatter(xs, ys, marker=marker, color=colors[width], alpha=0.55, label=f"{'print' if channel == 'p' else 'refuel'} {width} us")
    ax.set_title("Valve settled drop vs actual pulse-to-pulse interval")
    ax.set_xlabel("Actual pulse-to-pulse interval (ms)")
    ax.set_ylabel("Settled pressure drop (raw)")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    path = plot_dir / "valve_gap_drop_vs_actual_interval.png"
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
    gap_summary = _summary_by_gap_condition(rows)
    report_metrics = _build_report_metrics(rows)

    analysis_json = plot_dir / "valve_trace_analysis.json"
    analysis_json.write_text(
        json.dumps(
            {
                "schema_version": "valve_trace_analysis_v7",
                "baseline_window_ms": BASELINE_WINDOW_MS,
                "ring_window_after_pulse_end_ms": RING_WINDOW_AFTER_PULSE_END_MS,
                "settled_start_after_pulse_end_ms": SETTLED_START_AFTER_PULSE_END_MS,
                "settled_end_after_pulse_end_ms": SETTLED_END_AFTER_PULSE_END_MS,
                "latency_min_threshold_raw": LATENCY_MIN_THRESHOLD_RAW,
                "latency_baseline_std_multiplier": LATENCY_BASELINE_STD_MULTIPLIER,
                "replicate_count": len(rows),
                "valid_replicate_count": sum(1 for row in rows if row.get("valid")),
                "steady_replicate_count": sum(1 for row in rows if row.get("valid") and not row.get("excluded")),
                "excluded_replicate_count": sum(1 for row in rows if row.get("valid") and row.get("excluded")),
                "conditions": summary,
                "gap_conditions": gap_summary,
                "report_metrics": report_metrics,
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
    motor_plot = _plot_motor_position_summary(rows, plot_dir)
    if motor_plot is not None:
        plot_paths.append(motor_plot)
    ringing_plot = _plot_ringing_summary(rows, plot_dir)
    if ringing_plot is not None:
        plot_paths.append(ringing_plot)
    gap_plot = _plot_gap_response_by_gap(rows, plot_dir)
    if gap_plot is not None:
        plot_paths.append(gap_plot)
    gap_replicates = _plot_gap_replicates(rows, plot_dir)
    if gap_replicates is not None:
        plot_paths.append(gap_replicates)
    gap_interval = _plot_gap_interval_response(rows, plot_dir)
    if gap_interval is not None:
        plot_paths.append(gap_interval)

    return ValveTraceArtifacts(
        trace_dir=trace_dir,
        plot_dir=plot_dir,
        analysis_json=analysis_json,
        replicate_csv=replicate_csv,
        plot_paths=tuple(plot_paths),
        replicate_count=len(rows),
        report_metrics=report_metrics,
    )
