from __future__ import annotations

import copy
import csv
import json
import math
import os
import re
import statistics
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


FLAG_PRESSURE_OK = 0x01
FLAG_STEPPING = 0x02
FLAG_DIR = 0x04
FLAG_QUIET = 0x08
FLAG_RECOVERY = 0x10
FLAG_REJECTED = 0x20

TRACE_EXPECTED_INTERVAL_MS = {
    2101: 50.0,
    2102: 50.0,
    2103: 50.0,
    2104: 50.0,
}

DEFAULT_SCORE_WEIGHTS = {
    "ready_miss_count": 1000.0,
    "worst_deadline_slip_ms": 4.0,
    "worst_recovery_ms": 2.0,
    "max_undershoot_raw": 1.0,
    "max_overshoot_raw": 1.0,
    "zero_crossing_count": 1.0,
    "requested_applied_hz_saturation_ratio": 100.0,
    "max_requested_applied_hz_gap": 0.01,
}

SCORE_FIELDS = tuple(DEFAULT_SCORE_WEIGHTS.keys())

RUN_SUMMARY_FIELDS = [
    "rank",
    "score",
    "score_valid",
    "candidate_profile_id",
    "run_id",
    "session_id",
    "mode",
    "status",
    "trace_count",
    "sample_count",
    "event_count",
    "ready_miss_count",
    "worst_deadline_slip_ms",
    "worst_recovery_ms",
    "median_recovery_ms",
    "max_undershoot_raw",
    "max_overshoot_raw",
    "pressure_ok_duty_ratio",
    "recovery_active_duty_ratio",
    "pulse_interval_jitter_ms",
    "requested_applied_hz_saturation_ratio",
    "max_requested_applied_hz_gap",
    "zero_crossing_count",
    "rejected_sample_ratio",
    "score_missing_fields",
    "run_dir",
]

PER_PULSE_FIELDS = [
    "run_id",
    "session_id",
    "candidate_profile_id",
    "mode",
    "trace_file",
    "test_id",
    "name",
    "pulse_index",
    "pulse_end_ms",
    "trough_error_raw",
    "trough_pressure_raw",
    "time_to_trough_ms",
    "recovery_ms",
    "overshoot_after_recovery_raw",
]

TRACE_PER_PULSE_FIELDS = [
    "pulse_index",
    "pulse_end_ms",
    "trough_error_raw",
    "trough_pressure_raw",
    "time_to_trough_ms",
    "recovery_ms",
    "overshoot_after_recovery_raw",
]

TRACE_NAME_RE = re.compile(r".*_trace_.*\.json$", re.IGNORECASE)


class RegulatorTraceAnalysisError(ValueError):
    pass


@dataclass(frozen=True)
class RunInput:
    run_dir: Path | None
    run_meta_path: Path | None
    trace_files: tuple[Path, ...]
    source_input: Path


def _safe_list(obj: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = obj.get(key, [])
    return value if isinstance(value, list) else []


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _as_int(value: Any) -> int | None:
    numeric = _as_float(value)
    if numeric is None:
        return None
    return int(numeric)


def _metric(summary: dict[str, Any], *names: str) -> float | None:
    for name in names:
        if name not in summary:
            continue
        numeric = _as_float(summary.get(name))
        if numeric is not None:
            return numeric
    return None


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    idx = (len(ordered) - 1) * p
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return ordered[lo]
    frac = idx - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def series_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "median": 0.0, "p95": 0.0}
    ordered = sorted(values)
    return {
        "min": float(ordered[0]),
        "max": float(ordered[-1]),
        "mean": float(sum(values) / len(values)),
        "median": float(statistics.median(ordered)),
        "p95": float(_percentile(ordered, 0.95)),
    }


def _first_index_at_or_after(times_ms: list[float], dt_ms: float) -> int:
    for i, t in enumerate(times_ms):
        if t >= dt_ms:
            return i
    return max(0, len(times_ms) - 1)


def _zero_cross_count(values: list[float]) -> int:
    count = 0
    prev_sign = 0
    for value in values:
        sign = 1 if value > 0 else -1 if value < 0 else 0
        if sign == 0:
            continue
        if prev_sign and sign != prev_sign:
            count += 1
        prev_sign = sign
    return count


def _expected_interval_ms(trace: dict[str, Any], conditions: dict[str, Any] | None = None) -> float | None:
    if conditions:
        frequency_hz = _as_float(conditions.get("frequency_hz"))
        if frequency_hz and frequency_hz > 0.0:
            return 1000.0 / frequency_hz
    test_id = _as_int(trace.get("test_id"))
    return TRACE_EXPECTED_INTERVAL_MS.get(test_id)


def analyze_trace(
    trace: dict[str, Any],
    *,
    source_path: str | Path | None = None,
    conditions: dict[str, Any] | None = None,
    score_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    samples = _safe_list(trace, "samples")
    events = _safe_list(trace, "events")
    summary = trace.get("summary", {})
    summary = summary if isinstance(summary, dict) else {}
    if not samples:
        return {
            "source_path": None if source_path is None else str(source_path),
            "run_id": trace.get("run_id"),
            "test_id": trace.get("test_id"),
            "name": trace.get("name"),
            "summary_metrics": summary,
            "error": "no samples",
            "per_pulse": [],
            "normalized_metrics": {},
            "score": None,
            "score_valid": False,
            "score_missing_fields": list(SCORE_FIELDS),
        }

    times_ms = [float(sample.get("dt_ms", 0)) for sample in samples]
    raw_pressure = [float(sample.get("raw_pressure", 0)) for sample in samples]
    target = [float(sample.get("target", 0)) for sample in samples]
    error = [float(sample.get("error", 0)) for sample in samples]
    requested_hz = [float(sample.get("requested_hz", 0)) for sample in samples]
    applied_hz = [float(sample.get("applied_hz", 0)) for sample in samples]
    ff_hz = [float(sample.get("ff_boost_hz", 0)) for sample in samples]
    flags = [int(sample.get("flags", 0)) for sample in samples]

    dt_steps = [times_ms[i + 1] - times_ms[i] for i in range(len(times_ms) - 1)]
    pressure_ok_ratio = sum(1 for flag in flags if flag & FLAG_PRESSURE_OK) / float(len(flags))
    recovery_ratio = sum(1 for flag in flags if flag & FLAG_RECOVERY) / float(len(flags))
    quiet_ratio = sum(1 for flag in flags if flag & FLAG_QUIET) / float(len(flags))
    rejected_ratio = sum(1 for flag in flags if flag & FLAG_REJECTED) / float(len(flags))

    pulse_start = sorted(float(event.get("dt_ms", 0)) for event in events if event.get("event_name") == "pulse_start")
    pulse_end = sorted(float(event.get("dt_ms", 0)) for event in events if event.get("event_name") == "pulse_end")
    ready_enter = sorted(float(event.get("dt_ms", 0)) for event in events if event.get("event_name") == "ready_enter")

    pulse_intervals = [pulse_start[i + 1] - pulse_start[i] for i in range(len(pulse_start) - 1)]
    interval_stats = series_stats([float(value) for value in pulse_intervals])
    expected_interval = _expected_interval_ms(trace, conditions)
    derived_deadline_slip = None
    if expected_interval is not None and pulse_intervals:
        derived_deadline_slip = max(max(0.0, float(interval) - expected_interval) for interval in pulse_intervals)

    per_pulse: list[dict[str, Any]] = []
    for index, pulse_end_ms in enumerate(pulse_end):
        start_idx = _first_index_at_or_after(times_ms, pulse_end_ms)
        if index + 1 < len(pulse_end):
            end_idx = _first_index_at_or_after(times_ms, pulse_end[index + 1])
        else:
            end_idx = len(times_ms) - 1
        if end_idx < start_idx:
            end_idx = start_idx

        seg_error = error[start_idx : end_idx + 1]
        seg_raw = raw_pressure[start_idx : end_idx + 1]
        seg_t = times_ms[start_idx : end_idx + 1]
        trough_error = min(seg_error) if seg_error else 0.0
        trough_idx = seg_error.index(trough_error) if seg_error else 0
        trough_t = seg_t[trough_idx] if seg_t else pulse_end_ms
        trough_pressure = min(seg_raw) if seg_raw else 0.0

        recovery_time = next((dt for dt in ready_enter if dt >= pulse_end_ms), None)
        recovery_ms = None if recovery_time is None else recovery_time - pulse_end_ms

        overshoot_after_recovery = 0.0
        if recovery_time is not None:
            recovery_idx = _first_index_at_or_after(times_ms, recovery_time)
            tail = error[recovery_idx : end_idx + 1]
            overshoot_after_recovery = max(tail) if tail else 0.0

        per_pulse.append(
            {
                "pulse_index": index + 1,
                "pulse_end_ms": pulse_end_ms,
                "trough_error_raw": trough_error,
                "trough_pressure_raw": trough_pressure,
                "time_to_trough_ms": trough_t - pulse_end_ms,
                "recovery_ms": recovery_ms,
                "overshoot_after_recovery_raw": overshoot_after_recovery,
            }
        )

    recovery_values = [float(row["recovery_ms"]) for row in per_pulse if row.get("recovery_ms") is not None]
    trough_values = [float(row["trough_error_raw"]) for row in per_pulse]
    overshoot_values = [float(row["overshoot_after_recovery_raw"]) for row in per_pulse]

    active_hz_samples = [(req, app) for req, app in zip(requested_hz, applied_hz) if req > 0.0]
    saturated_samples = [(req, app) for req, app in active_hz_samples if app < req]
    saturation_ratio = len(saturated_samples) / float(len(active_hz_samples)) if active_hz_samples else 0.0
    max_hz_gap = max((max(0.0, req - app) for req, app in active_hz_samples), default=0.0)

    derived_undershoot = max(0.0, -min(error)) if error else None
    derived_overshoot = max(0.0, max(error)) if error else None
    derived_zero_cross = _zero_cross_count(error)
    pulse_interval_jitter = (interval_stats["max"] - interval_stats["min"]) if pulse_intervals else None

    normalized_metrics = {
        "ready_miss_count": _metric(summary, "ready_miss_count", "ready_miss"),
        "worst_recovery_ms": _metric(summary, "worst_recovery_ms", "rec_w"),
        "median_recovery_ms": float(statistics.median(recovery_values)) if recovery_values else None,
        "max_undershoot_raw": _metric(summary, "max_undershoot_raw", "under"),
        "max_overshoot_raw": _metric(summary, "max_overshoot_raw", "over"),
        "pressure_ok_duty_ratio": pressure_ok_ratio,
        "recovery_active_duty_ratio": recovery_ratio,
        "pulse_interval_jitter_ms": pulse_interval_jitter,
        "worst_deadline_slip_ms": _metric(summary, "max_deadline_slip_ms", "slip_w"),
        "requested_applied_hz_saturation_ratio": saturation_ratio,
        "max_requested_applied_hz_gap": max_hz_gap,
        "zero_crossing_count": _metric(summary, "zero_cross_count", "zero"),
        "rejected_sample_ratio": rejected_ratio,
        "sample_reject_count": _metric(summary, "sample_reject_count", "rejects"),
        "sample_count": len(samples),
        "event_count": len(events),
        "active_hz_sample_count": len(active_hz_samples),
        "saturated_hz_sample_count": len(saturated_samples),
    }
    if normalized_metrics["worst_recovery_ms"] is None and recovery_values:
        normalized_metrics["worst_recovery_ms"] = max(recovery_values)
    if normalized_metrics["max_undershoot_raw"] is None:
        normalized_metrics["max_undershoot_raw"] = derived_undershoot
    if normalized_metrics["max_overshoot_raw"] is None:
        normalized_metrics["max_overshoot_raw"] = derived_overshoot
    if normalized_metrics["worst_deadline_slip_ms"] is None:
        normalized_metrics["worst_deadline_slip_ms"] = derived_deadline_slip
    if normalized_metrics["zero_crossing_count"] is None:
        normalized_metrics["zero_crossing_count"] = float(derived_zero_cross)

    score, score_valid, missing = score_metrics(normalized_metrics, score_weights=score_weights)

    diagnosis = []
    if recovery_values and pulse_intervals and statistics.median(recovery_values) > 0.6 * statistics.median(pulse_intervals):
        diagnosis.append("slow_recovery_vs_pulse_interval")
    if trough_values and abs(min(trough_values)) > 2.5 * max(1.0, max(overshoot_values) if overshoot_values else 1.0):
        diagnosis.append("undershoot_dominant")
    if overshoot_values and max(overshoot_values) > 0.4 * max(1.0, abs(min(trough_values)) if trough_values else 1.0):
        diagnosis.append("overshoot_notable")
    if pulse_interval_jitter is not None and pulse_interval_jitter > 20.0:
        diagnosis.append("pulse_timing_jitter_high")
    if saturation_ratio > 0.0:
        diagnosis.append("speed_saturation_present")
    if not diagnosis:
        diagnosis.append("balanced_or_inconclusive")

    return {
        "source_path": None if source_path is None else str(source_path),
        "run_id": trace.get("run_id"),
        "test_id": trace.get("test_id"),
        "name": trace.get("name"),
        "summary_metrics": summary,
        "global": {
            "sample_count": len(samples),
            "event_count": len(events),
            "duration_ms": times_ms[-1] - times_ms[0] if times_ms else 0.0,
            "sample_period_ms": series_stats([float(value) for value in dt_steps]),
            "pulse_count": len(pulse_end),
            "pulse_interval_ms": interval_stats,
            "pressure_raw": series_stats(raw_pressure),
            "target_raw": series_stats(target),
            "error_raw": series_stats(error),
            "requested_hz": series_stats(requested_hz),
            "applied_hz": series_stats(applied_hz),
            "ff_boost_hz": series_stats(ff_hz),
            "duty_ratios": {
                "pressure_ok_ratio": pressure_ok_ratio,
                "recovery_active_ratio": recovery_ratio,
                "quiet_active_ratio": quiet_ratio,
                "sample_rejected_ratio": rejected_ratio,
            },
            "recovery_ms": series_stats(recovery_values),
            "trough_error_raw": series_stats(trough_values),
            "overshoot_after_recovery_raw": series_stats(overshoot_values),
        },
        "per_pulse": per_pulse,
        "normalized_metrics": normalized_metrics,
        "score": score,
        "score_valid": score_valid,
        "score_missing_fields": missing,
        "diagnosis": diagnosis,
    }


def validate_score_weights(overrides: dict[str, Any] | None = None) -> dict[str, float]:
    weights = dict(DEFAULT_SCORE_WEIGHTS)
    if overrides is None:
        return weights
    if not isinstance(overrides, dict):
        raise RegulatorTraceAnalysisError("score config must be a JSON object")
    unknown = sorted(set(overrides) - set(DEFAULT_SCORE_WEIGHTS))
    if unknown:
        raise RegulatorTraceAnalysisError(f"unknown score metric(s): {', '.join(unknown)}")
    for name, value in overrides.items():
        numeric = _as_float(value)
        if numeric is None or numeric < 0.0:
            raise RegulatorTraceAnalysisError(f"score weight for {name} must be a nonnegative number")
        weights[name] = float(numeric)
    return weights


def load_score_config(path: str | Path | None) -> dict[str, float]:
    if path is None:
        return validate_score_weights()
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_score_weights(payload)


def score_metrics(
    metrics: dict[str, Any],
    *,
    score_weights: dict[str, float] | None = None,
) -> tuple[float | None, bool, list[str]]:
    weights = validate_score_weights(score_weights)
    missing = [field for field in SCORE_FIELDS if _as_float(metrics.get(field)) is None]
    if missing:
        return None, False, missing
    score = sum(float(weights[field]) * float(metrics[field]) for field in SCORE_FIELDS)
    return float(score), True, []


def _is_trace_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".json" and TRACE_NAME_RE.match(path.name) is not None


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(path)
    return out


def _trace_files_for_run_dir(run_dir: Path, run_meta: dict[str, Any] | None = None) -> tuple[Path, ...]:
    traces: list[Path] = []
    outputs = run_meta.get("outputs", {}) if isinstance(run_meta, dict) else {}
    listed = outputs.get("trace_files", []) if isinstance(outputs, dict) else []
    if isinstance(listed, list):
        for item in listed:
            if not isinstance(item, str) or not item:
                continue
            path = run_dir / item
            if path.exists() and _is_trace_file(path):
                traces.append(path)
    if not traces:
        traces.extend(sorted(run_dir.glob("*_trace_*.json")))
    return tuple(_dedupe_paths(traces))


def _load_json_object(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RegulatorTraceAnalysisError(f"{path} must contain a JSON object")
    return obj


def discover_runs(inputs: list[str | Path]) -> list[RunInput]:
    runs: list[RunInput] = []
    seen_runs: set[Path] = set()
    seen_files: set[Path] = set()
    for raw in inputs:
        path = Path(raw)
        if path.is_file():
            if not _is_trace_file(path):
                raise RegulatorTraceAnalysisError(f"{path} is not a pressure trace JSON file")
            resolved = path.resolve()
            if resolved not in seen_files:
                seen_files.add(resolved)
                runs.append(RunInput(run_dir=None, run_meta_path=None, trace_files=(path,), source_input=path))
            continue
        if not path.is_dir():
            raise RegulatorTraceAnalysisError(f"{path} does not exist")

        direct_meta = path / "run_meta.json"
        if direct_meta.exists():
            resolved_run = path.resolve()
            if resolved_run in seen_runs:
                continue
            meta = _load_json_object(direct_meta)
            seen_runs.add(resolved_run)
            runs.append(
                RunInput(
                    run_dir=path,
                    run_meta_path=direct_meta,
                    trace_files=_trace_files_for_run_dir(path, meta),
                    source_input=path,
                )
            )
            continue

        meta_paths = sorted(path.rglob("run_meta.json"))
        if meta_paths:
            for meta_path in meta_paths:
                run_dir = meta_path.parent
                resolved_run = run_dir.resolve()
                if resolved_run in seen_runs:
                    continue
                meta = _load_json_object(meta_path)
                seen_runs.add(resolved_run)
                runs.append(
                    RunInput(
                        run_dir=run_dir,
                        run_meta_path=meta_path,
                        trace_files=_trace_files_for_run_dir(run_dir, meta),
                        source_input=path,
                    )
                )
            continue

        for trace_path in sorted(path.rglob("*_trace_*.json")):
            if not _is_trace_file(trace_path):
                continue
            resolved = trace_path.resolve()
            if resolved in seen_files:
                continue
            seen_files.add(resolved)
            runs.append(RunInput(run_dir=None, run_meta_path=None, trace_files=(trace_path,), source_input=path))

    if not runs:
        raise RegulatorTraceAnalysisError("no regulator pressure trace runs found")
    return runs


def _raw_selftest_metrics(run_dir: Path | None) -> dict[int, dict[str, Any]]:
    if run_dir is None:
        return {}
    raw_path = run_dir / "raw_selftest.json"
    if not raw_path.exists():
        return {}
    try:
        raw = _load_json_object(raw_path)
    except Exception:
        return {}
    metrics_by_test: dict[int, dict[str, Any]] = {}
    for row in raw.get("results", []):
        if not isinstance(row, dict) or "test_id" not in row:
            continue
        test_id = _as_int(row.get("test_id"))
        metrics = row.get("metrics", {})
        if test_id is not None and isinstance(metrics, dict):
            metrics_by_test[test_id] = metrics
    return metrics_by_test


def _relative_to(path: str | Path, root: Path | None) -> str:
    p = Path(path)
    if root is not None:
        try:
            return str(p.relative_to(root))
        except ValueError:
            pass
    return str(p)


def _run_identity(run_input: RunInput, run_meta: dict[str, Any] | None, first_trace: dict[str, Any] | None) -> dict[str, Any]:
    run_meta = run_meta or {}
    first_trace = first_trace or {}
    return {
        "run_id": run_meta.get("run_id") or first_trace.get("run_id") or (run_input.trace_files[0].stem if run_input.trace_files else ""),
        "session_id": run_meta.get("session_id"),
        "candidate_profile_id": run_meta.get("candidate_profile_id") or "",
        "mode": run_meta.get("mode") or "",
        "status": (run_meta.get("outcome") or {}).get("status") if isinstance(run_meta.get("outcome"), dict) else "",
        "conditions": run_meta.get("conditions", {}) if isinstance(run_meta.get("conditions"), dict) else {},
    }


def _aggregate_metric(rows: list[dict[str, Any]], key: str, mode: str) -> float | None:
    values = [_as_float(row.get(key)) for row in rows]
    present = [value for value in values if value is not None]
    if not present:
        return None
    if mode == "sum":
        return float(sum(present))
    if mode == "max":
        return float(max(present))
    if mode == "median":
        return float(statistics.median(present))
    raise ValueError(mode)


def _weighted_ratio(rows: list[dict[str, Any]], ratio_key: str, weight_key: str = "sample_count") -> float | None:
    total_weight = 0.0
    total_value = 0.0
    for row in rows:
        ratio = _as_float(row.get(ratio_key))
        weight = _as_float(row.get(weight_key))
        if ratio is None or weight is None or weight <= 0.0:
            continue
        total_weight += weight
        total_value += ratio * weight
    if total_weight <= 0.0:
        return None
    return total_value / total_weight


def _summarize_run_metrics(trace_metrics: list[dict[str, Any]], all_pulses: list[dict[str, Any]]) -> dict[str, Any]:
    recovery_values = [_as_float(row.get("recovery_ms")) for row in all_pulses]
    recovery_values = [value for value in recovery_values if value is not None]
    active_hz_count = sum(int(_as_float(row.get("active_hz_sample_count")) or 0) for row in trace_metrics)
    saturated_hz_count = sum(int(_as_float(row.get("saturated_hz_sample_count")) or 0) for row in trace_metrics)
    return {
        "ready_miss_count": _aggregate_metric(trace_metrics, "ready_miss_count", "sum"),
        "worst_recovery_ms": _aggregate_metric(trace_metrics, "worst_recovery_ms", "max"),
        "median_recovery_ms": float(statistics.median(recovery_values)) if recovery_values else None,
        "max_undershoot_raw": _aggregate_metric(trace_metrics, "max_undershoot_raw", "max"),
        "max_overshoot_raw": _aggregate_metric(trace_metrics, "max_overshoot_raw", "max"),
        "pressure_ok_duty_ratio": _weighted_ratio(trace_metrics, "pressure_ok_duty_ratio"),
        "recovery_active_duty_ratio": _weighted_ratio(trace_metrics, "recovery_active_duty_ratio"),
        "pulse_interval_jitter_ms": _aggregate_metric(trace_metrics, "pulse_interval_jitter_ms", "max"),
        "worst_deadline_slip_ms": _aggregate_metric(trace_metrics, "worst_deadline_slip_ms", "max"),
        "requested_applied_hz_saturation_ratio": (saturated_hz_count / float(active_hz_count))
        if active_hz_count > 0
        else None,
        "max_requested_applied_hz_gap": _aggregate_metric(trace_metrics, "max_requested_applied_hz_gap", "max"),
        "zero_crossing_count": _aggregate_metric(trace_metrics, "zero_crossing_count", "sum"),
        "rejected_sample_ratio": _weighted_ratio(trace_metrics, "rejected_sample_ratio"),
        "sample_count": _aggregate_metric(trace_metrics, "sample_count", "sum") or 0.0,
        "event_count": _aggregate_metric(trace_metrics, "event_count", "sum") or 0.0,
        "active_hz_sample_count": active_hz_count,
        "saturated_hz_sample_count": saturated_hz_count,
    }


def analyze_run(run_input: RunInput, *, score_weights: dict[str, float] | None = None) -> dict[str, Any]:
    run_meta = _load_json_object(run_input.run_meta_path) if run_input.run_meta_path else None
    raw_metrics = _raw_selftest_metrics(run_input.run_dir)
    trace_analyses: list[dict[str, Any]] = []
    all_pulses: list[dict[str, Any]] = []
    first_trace: dict[str, Any] | None = None
    identity: dict[str, Any] | None = None

    for trace_path in run_input.trace_files:
        try:
            trace = _load_json_object(trace_path)
            if first_trace is None:
                first_trace = trace
            if identity is None:
                identity = _run_identity(run_input, run_meta, trace)
            test_id = _as_int(trace.get("test_id"))
            if test_id is not None and test_id in raw_metrics:
                merged = dict(raw_metrics[test_id])
                merged.update(trace.get("summary", {}) if isinstance(trace.get("summary"), dict) else {})
                trace = copy.deepcopy(trace)
                trace["summary"] = merged
            analysis = analyze_trace(
                trace,
                source_path=trace_path,
                conditions=(identity or {}).get("conditions"),
                score_weights=score_weights,
            )
        except Exception as exc:
            analysis = {
                "source_path": str(trace_path),
                "run_id": None,
                "test_id": None,
                "name": trace_path.stem,
                "summary_metrics": {},
                "error": str(exc),
                "per_pulse": [],
                "normalized_metrics": {},
                "score": None,
                "score_valid": False,
                "score_missing_fields": list(SCORE_FIELDS),
            }
        trace_analyses.append(analysis)

    identity = identity or _run_identity(run_input, run_meta, first_trace)
    for analysis in trace_analyses:
        trace_file = analysis.get("source_path") or ""
        for pulse in analysis.get("per_pulse", []):
            row = {
                "run_id": identity.get("run_id"),
                "session_id": identity.get("session_id"),
                "candidate_profile_id": identity.get("candidate_profile_id"),
                "mode": identity.get("mode"),
                "trace_file": _relative_to(trace_file, run_input.run_dir),
                "test_id": analysis.get("test_id"),
                "name": analysis.get("name"),
                **pulse,
            }
            all_pulses.append(row)

    trace_metrics = [analysis.get("normalized_metrics", {}) for analysis in trace_analyses]
    metrics = _summarize_run_metrics(trace_metrics, all_pulses)
    score, score_valid, missing = score_metrics(metrics, score_weights=score_weights)
    run_dir_str = "" if run_input.run_dir is None else str(run_input.run_dir)
    summary_row = {
        "rank": None,
        "score": score,
        "score_valid": score_valid,
        "candidate_profile_id": identity.get("candidate_profile_id") or "",
        "run_id": identity.get("run_id") or "",
        "session_id": identity.get("session_id") or "",
        "mode": identity.get("mode") or "",
        "status": identity.get("status") or "",
        "trace_count": len(run_input.trace_files),
        "sample_count": int(metrics.get("sample_count") or 0),
        "event_count": int(metrics.get("event_count") or 0),
        "score_missing_fields": ",".join(missing),
        "run_dir": run_dir_str,
        **{field: metrics.get(field) for field in metrics},
    }
    return {
        "schema_version": 1,
        "run": {
            "run_id": identity.get("run_id"),
            "session_id": identity.get("session_id"),
            "candidate_profile_id": identity.get("candidate_profile_id"),
            "mode": identity.get("mode"),
            "status": identity.get("status"),
            "run_dir": run_dir_str,
            "source_input": str(run_input.source_input),
            "trace_files": [_relative_to(path, run_input.run_dir) for path in run_input.trace_files],
        },
        "metrics": metrics,
        "score": score,
        "score_valid": score_valid,
        "score_missing_fields": missing,
        "summary_row": summary_row,
        "traces": trace_analyses,
        "per_pulse": all_pulses,
    }


def ranking_key(row: dict[str, Any]) -> tuple[Any, ...]:
    score_valid = bool(row.get("score_valid"))
    score = _as_float(row.get("score"))
    ready_miss = _as_float(row.get("ready_miss_count"))
    slip = _as_float(row.get("worst_deadline_slip_ms"))
    return (
        0 if score_valid else 1,
        score if score is not None else math.inf,
        ready_miss if ready_miss is not None else math.inf,
        slip if slip is not None else math.inf,
        str(row.get("candidate_profile_id") or ""),
        str(row.get("run_id") or ""),
    )


def write_json_atomic(path: str | Path, payload: dict[str, Any]) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".regulator_trace_", suffix=".json", dir=str(out_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, out_path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def write_csv_atomic(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".regulator_trace_", suffix=".csv", dir=str(out_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, out_path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _safe_id(value: Any, fallback: str) -> str:
    raw = str(value or fallback).strip() or fallback
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw)


def _run_output_dir(run_input: RunInput, aggregate_out_dir: Path) -> Path:
    if run_input.run_dir is not None:
        return run_input.run_dir / "analysis"
    stem = run_input.trace_files[0].stem if run_input.trace_files else "standalone_trace"
    return aggregate_out_dir / _safe_id(stem, "standalone_trace")


def _default_aggregate_output_dir(runs: list[RunInput], output_dir: str | Path | None) -> Path:
    if output_dir is not None:
        return Path(output_dir)
    if len(runs) == 1 and runs[0].run_dir is not None:
        return runs[0].run_dir / "analysis"
    raise RegulatorTraceAnalysisError("--out-dir is required when analyzing multiple inputs or standalone trace files")


def _update_run_meta_outputs(run_input: RunInput, run_out_dir: Path, run_analysis: dict[str, Any], plots: list[Path]) -> None:
    if run_input.run_dir is None or run_input.run_meta_path is None:
        return
    meta = _load_json_object(run_input.run_meta_path)
    outputs = meta.setdefault("outputs", {})
    outputs["analysis_json"] = _relative_to(run_out_dir / "run_analysis.json", run_input.run_dir)
    outputs["summary_csv"] = _relative_to(run_out_dir / "run_summary.csv", run_input.run_dir)
    outputs["plots"] = [_relative_to(path, run_input.run_dir) for path in plots]
    if not outputs.get("trace_files"):
        outputs["trace_files"] = [_relative_to(path, run_input.run_dir) for path in run_input.trace_files]
    write_json_atomic(run_input.run_meta_path, meta)


def _write_trace_outputs(run_analysis: dict[str, Any], run_out_dir: Path) -> None:
    for trace_analysis in run_analysis.get("traces", []):
        source_path = trace_analysis.get("source_path")
        if not source_path:
            continue
        stem = Path(str(source_path)).stem
        write_json_atomic(run_out_dir / f"{stem}.analysis.json", trace_analysis)
        write_csv_atomic(
            run_out_dir / f"{stem}.per_pulse.csv",
            list(trace_analysis.get("per_pulse", [])),
            TRACE_PER_PULSE_FIELDS,
        )


def analyze_inputs(
    inputs: list[str | Path],
    *,
    output_dir: str | Path | None = None,
    score_weights: dict[str, float] | None = None,
    make_plots: bool = False,
    dpi: int = 150,
    update_run_meta: bool = True,
    plot_renderer: Callable[..., tuple[Path, Path, Path, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    weights = validate_score_weights(score_weights)
    runs = discover_runs(inputs)
    aggregate_out_dir = _default_aggregate_output_dir(runs, output_dir)
    aggregate_out_dir.mkdir(parents=True, exist_ok=True)

    run_outputs: list[dict[str, Any]] = []
    ranking_rows: list[dict[str, Any]] = []
    all_pulses: list[dict[str, Any]] = []
    generated_plots_by_run: dict[str, list[Path]] = {}

    for run_input in runs:
        run_analysis = analyze_run(run_input, score_weights=weights)
        run_out_dir = _run_output_dir(run_input, aggregate_out_dir)
        run_out_dir.mkdir(parents=True, exist_ok=True)
        plot_paths: list[Path] = []

        if make_plots and plot_renderer is not None:
            plots_dir = run_out_dir / "plots"
            for trace_path in run_input.trace_files:
                png, _analysis_json, _per_pulse_csv, _analysis = plot_renderer(
                    trace_path,
                    plots_dir,
                    dpi=dpi,
                    analysis_dir=run_out_dir,
                )
                plot_paths.append(png)

        _write_trace_outputs(run_analysis, run_out_dir)
        write_json_atomic(run_out_dir / "run_analysis.json", run_analysis)
        write_csv_atomic(run_out_dir / "run_summary.csv", [run_analysis["summary_row"]], RUN_SUMMARY_FIELDS)
        write_csv_atomic(run_out_dir / "per_pulse.csv", run_analysis["per_pulse"], PER_PULSE_FIELDS)

        if update_run_meta:
            _update_run_meta_outputs(run_input, run_out_dir, run_analysis, plot_paths)

        run_key = str(run_analysis["run"].get("run_id") or run_out_dir)
        generated_plots_by_run[run_key] = plot_paths
        run_outputs.append(
            {
                "run_input": run_input,
                "run_output_dir": run_out_dir,
                "analysis": run_analysis,
                "plots": plot_paths,
            }
        )
        ranking_rows.append(dict(run_analysis["summary_row"]))
        all_pulses.extend(run_analysis["per_pulse"])

    ranking_rows.sort(key=ranking_key)
    for index, row in enumerate(ranking_rows, start=1):
        row["rank"] = index if row.get("score_valid") else None

    aggregate_payload = {
        "schema_version": 1,
        "score_weights": weights,
        "run_count": len(run_outputs),
        "runs": ranking_rows,
    }
    write_json_atomic(aggregate_out_dir / "candidate_ranking.json", aggregate_payload)
    write_csv_atomic(aggregate_out_dir / "candidate_ranking.csv", ranking_rows, RUN_SUMMARY_FIELDS)
    write_csv_atomic(aggregate_out_dir / "all_pulses.csv", all_pulses, PER_PULSE_FIELDS)

    return {
        "output_dir": aggregate_out_dir,
        "score_weights": weights,
        "runs": run_outputs,
        "ranking": ranking_rows,
        "candidate_ranking_json": aggregate_out_dir / "candidate_ranking.json",
        "candidate_ranking_csv": aggregate_out_dir / "candidate_ranking.csv",
        "all_pulses_csv": aggregate_out_dir / "all_pulses.csv",
        "plots": generated_plots_by_run,
    }
