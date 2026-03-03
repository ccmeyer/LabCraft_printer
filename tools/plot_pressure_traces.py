#!/usr/bin/env python3
"""Render pressure-trace JSON artifacts into reviewable plots."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


FLAG_PRESSURE_OK = 0x01
FLAG_STEPPING = 0x02
FLAG_DIR = 0x04
FLAG_QUIET = 0x08
FLAG_RECOVERY = 0x10
FLAG_REJECTED = 0x20


EVENT_STYLE = {
    "pulse_start": ("tab:orange", "--"),
    "pulse_end": ("tab:red", "--"),
    "quiet_start": ("tab:purple", ":"),
    "quiet_end": ("tab:purple", "-."),
    "recovery_start": ("tab:green", "--"),
    "recovery_end": ("tab:green", "-."),
    "ready_enter": ("tab:blue", "--"),
    "ready_exit": ("tab:blue", "-."),
}


def _safe_list(obj: dict, key: str) -> list[dict]:
    value = obj.get(key, [])
    return value if isinstance(value, list) else []


def _ms(values: Iterable[int]) -> list[float]:
    return [float(v) for v in values]


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    idx = (len(values) - 1) * p
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return values[lo]
    frac = idx - lo
    return values[lo] * (1.0 - frac) + values[hi] * frac


def _series_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "median": 0.0, "p95": 0.0}
    s = sorted(values)
    return {
        "min": float(s[0]),
        "max": float(s[-1]),
        "mean": float(sum(values) / len(values)),
        "median": float(statistics.median(s)),
        "p95": float(_percentile(s, 0.95)),
    }


def _first_index_at_or_after(times_ms: list[float], dt_ms: float) -> int:
    for i, t in enumerate(times_ms):
        if t >= dt_ms:
            return i
    return len(times_ms) - 1


def _analyze_trace(obj: dict) -> dict:
    samples = _safe_list(obj, "samples")
    events = _safe_list(obj, "events")
    if not samples:
        return {"error": "no samples"}

    t_ms = _ms(s.get("dt_ms", 0) for s in samples)
    raw_p = [float(s.get("raw_pressure", 0)) for s in samples]
    tgt_p = [float(s.get("target", 0)) for s in samples]
    err = [float(s.get("error", 0)) for s in samples]
    req_hz = [float(s.get("requested_hz", 0)) for s in samples]
    app_hz = [float(s.get("applied_hz", 0)) for s in samples]
    ff_hz = [float(s.get("ff_boost_hz", 0)) for s in samples]
    flags = [int(s.get("flags", 0)) for s in samples]

    # Sample period and duty ratios
    dt_steps = [t_ms[i + 1] - t_ms[i] for i in range(len(t_ms) - 1)]
    pressure_ok_ratio = sum(1 for f in flags if (f & FLAG_PRESSURE_OK)) / float(len(flags))
    recovery_ratio = sum(1 for f in flags if (f & FLAG_RECOVERY)) / float(len(flags))
    quiet_ratio = sum(1 for f in flags if (f & FLAG_QUIET)) / float(len(flags))
    rejected_ratio = sum(1 for f in flags if (f & FLAG_REJECTED)) / float(len(flags))

    # Event timelines
    pulse_start = sorted(float(e.get("dt_ms", 0)) for e in events if e.get("event_name") == "pulse_start")
    pulse_end = sorted(float(e.get("dt_ms", 0)) for e in events if e.get("event_name") == "pulse_end")
    ready_enter = sorted(float(e.get("dt_ms", 0)) for e in events if e.get("event_name") == "ready_enter")

    pulse_intervals = [pulse_start[i + 1] - pulse_start[i] for i in range(len(pulse_start) - 1)]
    pulse_interval_stats = _series_stats([float(v) for v in pulse_intervals]) if pulse_intervals else _series_stats([])

    per_pulse: list[dict] = []
    for i, pe in enumerate(pulse_end):
        start_idx = _first_index_at_or_after(t_ms, pe)
        if i + 1 < len(pulse_end):
            next_end = pulse_end[i + 1]
            end_idx = _first_index_at_or_after(t_ms, next_end)
        else:
            end_idx = len(t_ms) - 1
        if end_idx < start_idx:
            end_idx = start_idx

        seg_err = err[start_idx : end_idx + 1]
        seg_raw = raw_p[start_idx : end_idx + 1]
        seg_t = t_ms[start_idx : end_idx + 1]

        trough_error = min(seg_err) if seg_err else 0.0
        trough_idx_local = seg_err.index(trough_error) if seg_err else 0
        trough_t = seg_t[trough_idx_local] if seg_t else pe
        trough_pressure = min(seg_raw) if seg_raw else 0.0

        rec_dt = None
        for dt in ready_enter:
            if dt >= pe:
                rec_dt = dt
                break
        recovery_ms = None if rec_dt is None else (rec_dt - pe)

        overshoot_after_recovery = 0.0
        if rec_dt is not None:
            rec_idx = _first_index_at_or_after(t_ms, rec_dt)
            tail = err[rec_idx : end_idx + 1]
            overshoot_after_recovery = max(tail) if tail else 0.0

        per_pulse.append(
            {
                "pulse_index": i + 1,
                "pulse_end_ms": pe,
                "trough_error_raw": trough_error,
                "trough_pressure_raw": trough_pressure,
                "time_to_trough_ms": trough_t - pe,
                "recovery_ms": recovery_ms,
                "overshoot_after_recovery_raw": overshoot_after_recovery,
            }
        )

    recovery_vals = [float(p["recovery_ms"]) for p in per_pulse if p["recovery_ms"] is not None]
    trough_vals = [float(p["trough_error_raw"]) for p in per_pulse]
    overshoot_vals = [float(p["overshoot_after_recovery_raw"]) for p in per_pulse]

    diagnosis = []
    if recovery_vals and pulse_intervals:
        if statistics.median(recovery_vals) > 0.6 * statistics.median(pulse_intervals):
            diagnosis.append("slow_recovery_vs_pulse_interval")
    if trough_vals and abs(min(trough_vals)) > 2.5 * max(1.0, max(overshoot_vals) if overshoot_vals else 1.0):
        diagnosis.append("undershoot_dominant")
    if overshoot_vals and max(overshoot_vals) > 0.4 * max(1.0, abs(min(trough_vals)) if trough_vals else 1.0):
        diagnosis.append("overshoot_notable")
    if pulse_interval_stats["max"] > 0:
        jitter = pulse_interval_stats["max"] - pulse_interval_stats["min"]
        if jitter > 20.0:
            diagnosis.append("pulse_timing_jitter_high")
    if not diagnosis:
        diagnosis.append("balanced_or_inconclusive")

    return {
        "run_id": obj.get("run_id"),
        "test_id": obj.get("test_id"),
        "name": obj.get("name"),
        "summary_metrics": obj.get("summary", {}),
        "global": {
            "sample_count": len(samples),
            "event_count": len(events),
            "duration_ms": t_ms[-1] - t_ms[0] if t_ms else 0.0,
            "sample_period_ms": _series_stats([float(v) for v in dt_steps]),
            "pulse_count": len(pulse_end),
            "pulse_interval_ms": pulse_interval_stats,
            "pressure_raw": _series_stats(raw_p),
            "target_raw": _series_stats(tgt_p),
            "error_raw": _series_stats(err),
            "requested_hz": _series_stats(req_hz),
            "applied_hz": _series_stats(app_hz),
            "ff_boost_hz": _series_stats(ff_hz),
            "duty_ratios": {
                "pressure_ok_ratio": pressure_ok_ratio,
                "recovery_active_ratio": recovery_ratio,
                "quiet_active_ratio": quiet_ratio,
                "sample_rejected_ratio": rejected_ratio,
            },
            "recovery_ms": _series_stats(recovery_vals),
            "trough_error_raw": _series_stats(trough_vals),
            "overshoot_after_recovery_raw": _series_stats(overshoot_vals),
        },
        "per_pulse": per_pulse,
        "diagnosis": diagnosis,
    }


def render_trace_file(path: Path, out_dir: Path, dpi: int = 150) -> tuple[Path, Path, Path, dict]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    samples = _safe_list(obj, "samples")
    events = _safe_list(obj, "events")
    if not samples:
        raise ValueError(f"{path} has no samples")

    # Keep x-axis in milliseconds to align with self-test metrics.
    t_ms = _ms(s.get("dt_ms", 0) for s in samples)

    raw_p = [int(s.get("raw_pressure", 0)) for s in samples]
    ctl_p = [int(s.get("control_pressure", 0)) for s in samples]
    avg_p = [int(s.get("avg_pressure", 0)) for s in samples]
    tgt_p = [int(s.get("target", 0)) for s in samples]
    err = [int(s.get("error", 0)) for s in samples]
    req_hz = [int(s.get("requested_hz", 0)) for s in samples]
    app_hz = [int(s.get("applied_hz", 0)) for s in samples]
    ff_hz = [int(s.get("ff_boost_hz", 0)) for s in samples]
    flags = [int(s.get("flags", 0)) for s in samples]

    f_ok = [1 if (f & FLAG_PRESSURE_OK) else 0 for f in flags]
    f_quiet = [1 if (f & FLAG_QUIET) else 0 for f in flags]
    f_recovery = [1 if (f & FLAG_RECOVERY) else 0 for f in flags]
    f_rejected = [1 if (f & FLAG_REJECTED) else 0 for f in flags]

    fig, axs = plt.subplots(4, 1, figsize=(14, 10), sharex=True)
    ax_p, ax_e, ax_hz, ax_f = axs

    ax_p.plot(t_ms, raw_p, label="raw_pressure", linewidth=1.4)
    ax_p.plot(t_ms, ctl_p, label="control_pressure", linewidth=1.1)
    ax_p.plot(t_ms, avg_p, label="avg_pressure", linewidth=1.0, alpha=0.8)
    ax_p.plot(t_ms, tgt_p, label="target", linestyle="--", linewidth=1.2)
    ax_p.set_ylabel("Pressure (raw)")
    ax_p.grid(True, alpha=0.25)
    ax_p.legend(loc="upper right", ncols=4, fontsize=8)

    ax_e.plot(t_ms, err, label="error", color="tab:red", linewidth=1.3)
    ax_e.axhline(0.0, color="black", linewidth=0.8, alpha=0.6)
    ax_e.set_ylabel("Error (raw)")
    ax_e.grid(True, alpha=0.25)
    ax_e.legend(loc="upper right", fontsize=8)

    ax_hz.plot(t_ms, req_hz, label="requested_hz", linewidth=1.3)
    ax_hz.plot(t_ms, app_hz, label="applied_hz", linewidth=1.2)
    ax_hz.plot(t_ms, ff_hz, label="ff_boost_hz", linewidth=1.1, alpha=0.9)
    ax_hz.set_ylabel("Speed (Hz)")
    ax_hz.grid(True, alpha=0.25)
    ax_hz.legend(loc="upper right", fontsize=8)

    ax_f.step(t_ms, f_ok, where="post", label="pressure_ok", linewidth=1.2)
    ax_f.step(t_ms, f_quiet, where="post", label="quiet", linewidth=1.1)
    ax_f.step(t_ms, f_recovery, where="post", label="recovery", linewidth=1.1)
    ax_f.step(t_ms, f_rejected, where="post", label="sample_rejected", linewidth=1.1)
    ax_f.set_xlabel("Time (ms)")
    ax_f.set_ylabel("Flags")
    ax_f.set_ylim(-0.1, 1.2)
    ax_f.grid(True, alpha=0.25)
    ax_f.legend(loc="upper right", ncols=4, fontsize=8)

    for ev in events:
        name = str(ev.get("event_name", ""))
        dt = float(ev.get("dt_ms", 0))
        style = EVENT_STYLE.get(name)
        if style is None:
            continue
        color, ls = style
        for ax in axs:
            ax.axvline(dt, color=color, linestyle=ls, linewidth=0.9, alpha=0.55)

    run_id = obj.get("run_id", "unknown")
    test_id = obj.get("test_id", "unknown")
    test_name = obj.get("name", path.stem)
    summary = obj.get("summary", {})
    summary_bits = [f"{k}={v}" for k, v in summary.items()]
    summary_line = " | ".join(summary_bits) if summary_bits else "no-summary-metrics"
    fig.suptitle(f"{test_name} (test_id={test_id}, run_id={run_id})\n{summary_line}", fontsize=10)
    fig.tight_layout(rect=[0, 0.02, 1, 0.94])

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{path.stem}.png"
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)

    analysis = _analyze_trace(obj)
    analysis_json = out_dir / f"{path.stem}.analysis.json"
    analysis_json.write_text(json.dumps(analysis, indent=2), encoding="utf-8")

    per_pulse_csv = out_dir / f"{path.stem}.per_pulse.csv"
    with per_pulse_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "pulse_index",
                "pulse_end_ms",
                "trough_error_raw",
                "trough_pressure_raw",
                "time_to_trough_ms",
                "recovery_ms",
                "overshoot_after_recovery_raw",
            ],
        )
        writer.writeheader()
        for row in analysis.get("per_pulse", []):
            writer.writerow(row)

    return out_path, analysis_json, per_pulse_csv, analysis


def _collect_inputs(inputs: list[str], glob_patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in inputs:
        p = Path(raw)
        if p.is_file():
            files.append(p)
    for pat in glob_patterns:
        files.extend(sorted(Path(".").glob(pat)))
    if not files:
        files.extend(sorted(Path("hil_reports").glob("*_trace_*.json")))
    # de-dup while preserving order
    dedup: list[Path] = []
    seen: set[Path] = set()
    for f in files:
        fp = f.resolve()
        if fp in seen:
            continue
        seen.add(fp)
        dedup.append(f)
    return dedup


def render_sweep_summary(path: Path, out_dir: Path, dpi: int = 150) -> list[Path]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    combos = obj.get("combos", [])
    if not isinstance(combos, list) or not combos:
        raise ValueError(f"{path} has no combos")

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = path.stem

    by_param: dict[int, list[float]] = {}
    for c in combos:
        param = int(c.get("param", 0))
        by_param.setdefault(param, []).append(float(c.get("score", 0)))
    params = sorted(by_param)
    mean_scores = [sum(by_param[p]) / max(1, len(by_param[p])) for p in params]

    score_path = out_dir / f"{stem}_score_by_param.png"
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar([str(p) for p in params], mean_scores, color="tab:blue")
    ax.set_xlabel("Parameter Set")
    ax.set_ylabel("Mean Score (lower is better)")
    ax.set_title("Sweep Score by Parameter Set")
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(score_path, dpi=dpi)
    plt.close(fig)

    scenarios = sorted({int(c.get("scenario", 0)) for c in combos})
    p_index = {p: i for i, p in enumerate(params)}
    s_index = {s: i for i, s in enumerate(scenarios)}
    heat = [[0.0 for _ in scenarios] for _ in params]
    for c in combos:
        pi = p_index[int(c.get("param", 0))]
        si = s_index[int(c.get("scenario", 0))]
        heat[pi][si] += float(c.get("ready_miss", 0))

    heat_path = out_dir / f"{stem}_ready_miss_heatmap.png"
    fig, ax = plt.subplots(figsize=(11, 5))
    im = ax.imshow(heat, cmap="Reds", aspect="auto")
    ax.set_yticks(range(len(params)))
    ax.set_yticklabels([str(p) for p in params])
    ax.set_xticks(range(len(scenarios)))
    ax.set_xticklabels([str(s) for s in scenarios])
    ax.set_xlabel("Scenario")
    ax.set_ylabel("Parameter Set")
    ax.set_title("Ready Miss Heatmap")
    fig.colorbar(im, ax=ax, shrink=0.85, label="ready_miss")
    fig.tight_layout()
    fig.savefig(heat_path, dpi=dpi)
    plt.close(fig)

    scatter_path = out_dir / f"{stem}_slip_over_scatter.png"
    fig, ax = plt.subplots(figsize=(10, 6))
    for p in params:
        rows = [c for c in combos if int(c.get("param", 0)) == p]
        x = [float(c.get("slip_w", 0)) for c in rows]
        y = [float(c.get("over", 0)) for c in rows]
        sizes = [30.0 + float(c.get("under", 0)) * 2.0 for c in rows]
        ax.scatter(x, y, s=sizes, alpha=0.7, label=f"p{p}")
    ax.set_xlabel("Worst Deadline Slip (ms)")
    ax.set_ylabel("Max Overshoot (raw)")
    ax.set_title("Slip vs Overshoot (bubble size = undershoot)")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", ncols=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(scatter_path, dpi=dpi)
    plt.close(fig)

    return [score_path, heat_path, scatter_path]


def main() -> int:
    ap = argparse.ArgumentParser(description="Plot pressure trace JSON artifacts.")
    ap.add_argument("inputs", nargs="*", help="Trace JSON files (e.g. hil_reports/*_trace_*.json)")
    ap.add_argument("--glob", action="append", default=[], help="Additional glob pattern(s)")
    ap.add_argument("--sweep-summary", help="Pressure sweep summary JSON artifact")
    ap.add_argument("--out-dir", default="hil_reports/pressure_trace_plots", help="Output directory for PNGs")
    ap.add_argument("--dpi", type=int, default=150, help="PNG DPI")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    if args.sweep_summary:
        try:
            outputs = render_sweep_summary(Path(args.sweep_summary), out_dir=out_dir, dpi=args.dpi)
            for p in outputs:
                print(f"[ok] {p}")
            return 0
        except Exception as exc:
            print(f"[fail] {args.sweep_summary}: {exc}")
            return 2

    files = _collect_inputs(args.inputs, args.glob)
    if not files:
        print("No trace files found.")
        return 1

    failures = 0
    for f in files:
        try:
            png, analysis_json, per_pulse_csv, analysis = render_trace_file(f, out_dir=out_dir, dpi=args.dpi)
            diagnosis = ",".join(analysis.get("diagnosis", []))
            rec = analysis.get("global", {}).get("recovery_ms", {})
            slip_hint = analysis.get("summary_metrics", {}).get("slip_w", "n/a")
            print(f"[ok] {f} -> {png}")
            print(f"     analysis: {analysis_json}")
            print(f"     per_pulse: {per_pulse_csv}")
            print(
                "     diagnosis: "
                f"{diagnosis}; rec_p95_ms={rec.get('p95', 0):.1f}; slip_w={slip_hint}"
            )
        except Exception as exc:  # pragma: no cover - surfaced in CLI output
            failures += 1
            print(f"[fail] {f}: {exc}")

    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
