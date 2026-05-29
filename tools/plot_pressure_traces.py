#!/usr/bin/env python3
"""Render pressure-trace JSON artifacts into reviewable plots."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Iterable

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from regulator_trace_analysis import (
    FLAG_PRESSURE_OK,
    FLAG_QUIET,
    FLAG_RECOVERY,
    FLAG_REJECTED,
    analyze_trace as _shared_analyze_trace,
)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


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


def _analyze_trace(obj: dict) -> dict:
    return _shared_analyze_trace(obj)


def render_trace_file(
    path: Path,
    out_dir: Path,
    dpi: int = 150,
    analysis_dir: Path | None = None,
) -> tuple[Path, Path, Path, dict]:
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

    analysis_base = analysis_dir or out_dir
    analysis_base.mkdir(parents=True, exist_ok=True)
    analysis = _analyze_trace(obj)
    analysis_json = analysis_base / f"{path.stem}.analysis.json"
    analysis_json.write_text(json.dumps(analysis, indent=2), encoding="utf-8")

    per_pulse_csv = analysis_base / f"{path.stem}.per_pulse.csv"
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
