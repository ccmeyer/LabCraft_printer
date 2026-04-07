import argparse
from collections import Counter
import json
import os
import sys
from pathlib import Path

import cv2


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_DIR = REPO_ROOT / "FreeRTOS-interface"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))

from CalibrationClasses.Model import NozzlePositionCalibrationProcess  # noqa: E402


def _load_jsonl(path: Path):
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _load_image_rgb(path: Path):
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.ndim == 2:
        return img
    if img.ndim == 3 and img.shape[2] == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    if img.ndim == 3 and img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
    return img


def _make_nozzle_detector():
    proc = NozzlePositionCalibrationProcess.__new__(NozzlePositionCalibrationProcess)
    proc.fixed_thresh_value = 30
    proc.no_signal_min_fg_px = 120
    proc.min_stream_bbox_h_px = 10
    proc.search_top_band_frac = 0.60
    proc._last_detection_details = {}
    return proc


def replay_nozzle_pair(background_rgb, droplet_rgb):
    proc = _make_nozzle_detector()
    status, nozzle_px, n_contours, _ = NozzlePositionCalibrationProcess._detect_nozzle_point(
        proc,
        background_rgb,
        droplet_rgb,
    )
    return {
        "status": status,
        "nozzle_px": nozzle_px,
        "n_contours": int(n_contours),
        "detection": dict(getattr(proc, "_last_detection_details", {}) or {}),
    }


def _as_float_or_none(value):
    try:
        return float(value)
    except Exception:
        return None


def _collect_pressure_rows_from_analyses(analyses):
    direct_rows = []
    legacy_rows = []
    for a in analyses:
        kind = str(a.get("kind", ""))
        if kind == "pressure_sweep_pressure_result":
            rec = a.get("result")
            if isinstance(rec, dict):
                direct_rows.append(dict(rec))
            continue
        if kind != "calibration_data_updated":
            continue
        payload = a.get("payload") or {}
        result = payload.get("result") or {}
        rows = result.get("pressures") or []
        for row in rows:
            if isinstance(row, dict):
                legacy_rows.append(dict(row))
    return direct_rows if direct_rows else legacy_rows


def replay_pressure_sweep_run(run_dir: Path, analyses, events):
    rows = _collect_pressure_rows_from_analyses(analyses)
    decision_events = [
        e for e in events
        if str(e.get("event_type", "")).lower() == "decision"
    ]

    pressure_results = []
    invalid_reason_counts = Counter()
    valid_pressures = 0
    for i, row in enumerate(rows):
        valid = bool(row.get("valid", False))
        reason = str(row.get("invalid_reason", "") or "")
        if valid:
            valid_pressures += 1
        else:
            invalid_reason_counts[str(reason or "unspecified")] += 1
        pressure_results.append(
            {
                "index": int(i),
                "pressure": _as_float_or_none(row.get("pressure")),
                "delay_us": row.get("delay_us"),
                "valid": bool(valid),
                "invalid_reason": (None if valid else str(reason or "unspecified")),
                "accepted_replicates": row.get("accepted_replicates"),
                "captured_replicates": row.get("captured_replicates"),
                "multiple_detections": row.get("multiple_detections"),
                "stream_like_detections": row.get("stream_like_detections"),
                "invalid_frame_hits": row.get("invalid_frame_hits"),
            }
        )

    decision_counts = Counter()
    for evt in decision_events:
        payload = evt.get("payload") or {}
        decision = str(payload.get("decision", "")).strip()
        if decision:
            decision_counts[decision] += 1

    search_analyses = [a for a in analyses if str(a.get("kind", "")) == "pressure_sweep_search"]
    search_status_counts = Counter(str(a.get("status", "")) for a in search_analyses)
    search_reason_counts = Counter(str(a.get("reason", "")) for a in search_analyses)

    char_frames = [a for a in analyses if str(a.get("kind", "")) == "pressure_sweep_characterization_frame"]
    char_status_counts = Counter(str(a.get("status", "")) for a in char_frames)
    char_reason_counts = Counter(str(a.get("reason", "")) for a in char_frames)

    capture_saved = [e for e in events if str(e.get("event_type", "")) == "capture_saved"]
    background_captures = 0
    droplet_captures = 0
    for evt in capture_saved:
        payload = evt.get("payload") or {}
        role = str(payload.get("capture_role", "")).strip().lower()
        if role == "background":
            background_captures += 1
        elif role == "droplet":
            droplet_captures += 1

    background_refreshes = sum(1 for e in events if str(e.get("event_type", "")) == "background_refreshed")
    background_marked_stale = sum(1 for e in events if str(e.get("event_type", "")) == "background_marked_stale")

    total_pressures = int(len(pressure_results))
    invalid_pressures = int(total_pressures - valid_pressures)

    return {
        "run_dir": str(run_dir),
        "process_name": "PressureSweepCharacterizationProcess",
        "supported": True,
        "mode": "pressure_sweep_summary",
        "pressure_results": pressure_results,
        "invalid_reason_counts": dict(sorted(invalid_reason_counts.items())),
        "decision_counts": dict(sorted(decision_counts.items())),
        "search_summary": {
            "count": int(len(search_analyses)),
            "status_counts": dict(sorted(search_status_counts.items())),
            "reason_counts": dict(sorted(search_reason_counts.items())),
        },
        "characterization_summary": {
            "count": int(len(char_frames)),
            "status_counts": dict(sorted(char_status_counts.items())),
            "reason_counts": dict(sorted(char_reason_counts.items())),
        },
        "summary": {
            # Preserve existing top-level aggregator keys for replay_root.
            "total": int(total_pressures),
            "matched": int(valid_pressures),
            "mismatched": int(invalid_pressures),
            "skipped": 0,
            "valid_pressures": int(valid_pressures),
            "invalid_pressures": int(invalid_pressures),
            "background_captures": int(background_captures),
            "droplet_captures": int(droplet_captures),
            "background_refreshes": int(background_refreshes),
            "background_marked_stale": int(background_marked_stale),
        },
    }


def replay_run(run_dir: str | Path):
    run_dir = Path(run_dir)
    run_meta_path = run_dir / "run_meta.json"
    events_path = run_dir / "events.jsonl"
    analysis_path = run_dir / "analysis.jsonl"

    if not run_meta_path.exists():
        raise FileNotFoundError(f"run_meta.json not found in {run_dir}")

    run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
    process_name = str(run_meta.get("process_name", ""))

    analyses = _load_jsonl(analysis_path)
    events = _load_jsonl(events_path)
    decision_events = [
        e for e in events
        if str(e.get("event_type", "")).lower() == "decision"
    ]

    if process_name == "PressureSweepCharacterizationProcess":
        return replay_pressure_sweep_run(run_dir, analyses, events)

    if process_name != "NozzlePositionCalibrationProcess":
        return {
            "run_dir": str(run_dir),
            "process_name": process_name,
            "supported": False,
            "reason": (
                "Replay currently supports NozzlePositionCalibrationProcess and "
                "PressureSweepCharacterizationProcess."
            ),
            "results": [],
            "summary": {"total": 0, "matched": 0, "mismatched": 0, "skipped": 0},
        }

    nozzle_analyses = [a for a in analyses if str(a.get("kind", "")) == "nozzle_detection"]
    rows = []
    matched = 0
    mismatched = 0
    skipped = 0

    for i, a in enumerate(nozzle_analyses):
        pair = a.get("pair", {}) or {}
        bg_rel = str(pair.get("background_image_relpath", "")).strip()
        dr_rel = str(pair.get("droplet_image_relpath", "")).strip()
        recorded_status = str(a.get("status", ""))

        rec_decision = ""
        if i < len(decision_events):
            rec_decision = str((decision_events[i].get("payload") or {}).get("decision", ""))

        if not bg_rel or not dr_rel:
            rows.append(
                {
                    "index": i,
                    "recorded_status": recorded_status,
                    "recorded_decision": rec_decision,
                    "replayed_status": "",
                    "match": False,
                    "skipped": True,
                    "reason": "missing_pair_paths",
                }
            )
            skipped += 1
            continue

        bg_path = run_dir / bg_rel
        dr_path = run_dir / dr_rel
        bg = _load_image_rgb(bg_path)
        dr = _load_image_rgb(dr_path)

        if bg is None or dr is None:
            rows.append(
                {
                    "index": i,
                    "recorded_status": recorded_status,
                    "recorded_decision": rec_decision,
                    "replayed_status": "",
                    "match": False,
                    "skipped": True,
                    "reason": "image_load_failed",
                    "background_path": str(bg_path),
                    "droplet_path": str(dr_path),
                }
            )
            skipped += 1
            continue

        out = replay_nozzle_pair(bg, dr)
        replay_status = str(out.get("status", ""))
        is_match = replay_status == recorded_status
        if is_match:
            matched += 1
        else:
            mismatched += 1

        rows.append(
            {
                "index": i,
                "recorded_status": recorded_status,
                "recorded_decision": rec_decision,
                "replayed_status": replay_status,
                "match": bool(is_match),
                "skipped": False,
                "background_image_relpath": bg_rel,
                "droplet_image_relpath": dr_rel,
                "replayed_nozzle_px": out.get("nozzle_px"),
                "replayed_n_contours": out.get("n_contours"),
            }
        )

    report = {
        "run_dir": str(run_dir),
        "process_name": process_name,
        "supported": True,
        "results": rows,
        "summary": {
            "total": int(len(rows)),
            "matched": int(matched),
            "mismatched": int(mismatched),
            "skipped": int(skipped),
        },
    }
    return report


def replay_root(root_dir: str | Path):
    root_dir = Path(root_dir)
    run_dirs = [p.parent for p in root_dir.rglob("run_meta.json")]
    reports = []
    for run_dir in sorted(set(run_dirs)):
        try:
            reports.append(replay_run(run_dir))
        except Exception as e:
            reports.append(
                {
                    "run_dir": str(run_dir),
                    "supported": False,
                    "reason": f"replay_failed: {e}",
                    "results": [],
                    "summary": {"total": 0, "matched": 0, "mismatched": 0, "skipped": 0},
                }
            )

    total = sum(int(r.get("summary", {}).get("total", 0)) for r in reports)
    matched = sum(int(r.get("summary", {}).get("matched", 0)) for r in reports)
    mismatched = sum(int(r.get("summary", {}).get("mismatched", 0)) for r in reports)
    skipped = sum(int(r.get("summary", {}).get("skipped", 0)) for r in reports)

    return {
        "root_dir": str(root_dir),
        "runs": reports,
        "summary": {
            "run_count": int(len(reports)),
            "total": int(total),
            "matched": int(matched),
            "mismatched": int(mismatched),
            "skipped": int(skipped),
        },
    }


def _write_report(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Replay recorded calibration runs with current analysis logic.")
    ap.add_argument("--run-dir", type=str, default="", help="Path to a single recorded run directory.")
    ap.add_argument("--root", type=str, default="", help="Root directory containing many run directories.")
    ap.add_argument("--output", type=str, default="", help="Optional output JSON path.")
    args = ap.parse_args(argv)

    if not args.run_dir and not args.root:
        ap.error("Provide either --run-dir or --root")

    if args.run_dir:
        report = replay_run(args.run_dir)
        out_path = Path(args.output) if args.output else Path(args.run_dir) / "replay_report.json"
    else:
        report = replay_root(args.root)
        out_path = Path(args.output) if args.output else Path(args.root) / "replay_report.json"

    _write_report(out_path, report)
    print(f"Replay report written to: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
