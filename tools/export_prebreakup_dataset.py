#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


PROCESS_NAME = "PreBreakupDatasetAcquisitionProcess"


RUN_COLUMNS = [
    "run_id",
    "process_name",
    "phase_name",
    "run_dir",
    "started_at_utc",
    "ended_at_utc",
    "outcome",
    "error_message",
    "condition_count",
    "frame_count",
    "analysis_count",
    "overlay_count",
    "plan_snapshot_path",
    "source_plan_path",
]

CONDITION_COLUMNS = [
    "run_id",
    "condition_id",
    "condition_index",
    "pulse_width_us",
    "pressure_psi",
    "delay_mode",
    "delay_start_us",
    "delay_stop_us",
    "delay_step_us",
    "replicates_per_delay",
    "stock_solution",
    "printer_head_id",
    "nozzle_id",
    "label_key",
    "pressure_band_label",
    "label_match_mode",
    "background_image_relpath",
    "background_image_abs_path",
    "background_image_exists",
    "notes",
]

FRAME_COLUMNS = [
    "run_id",
    "condition_id",
    "condition_index",
    "frame_id",
    "capture_id",
    "capture_index",
    "capture_role",
    "image_relpath",
    "image_abs_path",
    "image_exists",
    "background_image_relpath",
    "background_image_abs_path",
    "background_image_exists",
    "overlay_image_relpath",
    "overlay_image_abs_path",
    "overlay_image_exists",
    "flash_delay_us",
    "delay_from_emergence_us",
    "replicate_index",
    "pulse_width_us",
    "pressure_psi",
    "stock_solution",
    "printer_head_id",
    "nozzle_id",
    "label_key",
    "pressure_band_label",
    "label_match_mode",
]


def _print_json(payload: dict):
    print(json.dumps(payload, indent=2, sort_keys=True))


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            yield json.loads(text)


def _clean_text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value):
    try:
        if value in (None, ""):
            return None
        return int(round(float(value)))
    except Exception:
        return None


def _float_or_none(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _json_cell(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def _flatten_value(prefix: str, value, out: dict):
    key = prefix.rstrip("_")
    if isinstance(value, dict):
        for child_key, child_value in sorted(value.items()):
            _flatten_value(f"{prefix}{child_key}_", child_value, out)
        return
    if isinstance(value, list):
        out[key] = json.dumps(value, sort_keys=True, separators=(",", ":"))
        return
    out[key] = value


def _preferred_columns(rows, base_columns):
    seen = list(base_columns)
    seen_set = set(seen)
    extras = sorted({key for row in rows for key in row.keys() if key not in seen_set})
    return seen + extras


def _write_csv(path: Path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _json_cell(row.get(column)) for column in columns})
    return path


def _resolve_dataset_root(root: str | Path):
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        raise FileNotFoundError(f"Dataset root does not exist: {root_path}")

    if root_path.is_file():
        if root_path.name == "run_meta.json":
            run_dir = root_path.parent
            return run_dir.parent, [run_dir]
        raise ValueError(f"Unsupported file root: {root_path}")

    if (root_path / "run_meta.json").exists():
        return root_path.parent, [root_path]

    if root_path.name == PROCESS_NAME:
        process_root = root_path
        base_root = root_path.parent
    elif root_path.name == "calibration_recordings" and (root_path / PROCESS_NAME).is_dir():
        process_root = root_path / PROCESS_NAME
        base_root = root_path.parent
    elif (root_path / "calibration_recordings" / PROCESS_NAME).is_dir():
        process_root = root_path / "calibration_recordings" / PROCESS_NAME
        base_root = root_path
    elif (root_path / PROCESS_NAME).is_dir():
        process_root = root_path / PROCESS_NAME
        base_root = root_path
    else:
        run_dirs = sorted(path for path in root_path.iterdir() if path.is_dir() and (path / "run_meta.json").exists())
        if run_dirs:
            return root_path, run_dirs
        raise ValueError(
            "Could not resolve PreBreakupDatasetAcquisitionProcess runs from "
            f"{root_path}. Point the tool at an experiment dir, calibration_recordings dir, "
            "process dir, or a specific run dir."
        )

    run_dirs = sorted(path for path in process_root.iterdir() if path.is_dir() and (path / "run_meta.json").exists())
    return base_root, run_dirs


def default_export_dir(root: str | Path):
    base_root, _ = _resolve_dataset_root(root)
    return Path(base_root) / "analysis" / "prebreakup_dataset_exports"


def _load_label_rows(path: str | Path | None):
    if not path:
        return []
    label_path = Path(path).expanduser().resolve()
    if not label_path.exists():
        raise FileNotFoundError(f"Label table does not exist: {label_path}")

    if label_path.suffix.lower() == ".csv":
        with label_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    elif label_path.suffix.lower() == ".jsonl":
        rows = list(_iter_jsonl(label_path))
    else:
        payload = _load_json(label_path)
        if isinstance(payload, dict):
            rows = list(payload.get("labels") or payload.get("rows") or [])
        elif isinstance(payload, list):
            rows = list(payload)
        else:
            raise ValueError(f"Unsupported label payload in {label_path}")

    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        lo = _float_or_none(row.get("band_low_psi"))
        hi = _float_or_none(row.get("band_high_psi"))
        if lo is not None and hi is not None and lo > hi:
            lo, hi = hi, lo
        normalized.append(
            {
                "label_key": _clean_text(row.get("label_key")),
                "stock_solution": _clean_text(row.get("stock_solution")),
                "printer_head_id": _clean_text(row.get("printer_head_id")),
                "nozzle_id": _clean_text(row.get("nozzle_id")),
                "pulse_width_us": _int_or_none(row.get("pulse_width_us")),
                "band_low_psi": lo,
                "band_high_psi": hi,
                "recommended_pressure_psi": _float_or_none(row.get("recommended_pressure_psi")),
                "label_source_process": _clean_text(row.get("label_source_process")),
                "label_source_run_id": _clean_text(row.get("label_source_run_id")),
                "label_confidence": _float_or_none(row.get("label_confidence")),
                "notes": _clean_text(row.get("notes")),
            }
        )
    return normalized


def _build_label_indices(labels):
    by_key = {}
    by_exact = {}
    by_partial = {}
    for row in labels:
        label_key = row.get("label_key")
        if label_key and label_key not in by_key:
            by_key[label_key] = row
        exact = (
            row.get("stock_solution"),
            row.get("printer_head_id"),
            row.get("nozzle_id"),
            row.get("pulse_width_us"),
        )
        if exact not in by_exact:
            by_exact[exact] = row
        partial = (
            row.get("stock_solution"),
            row.get("printer_head_id"),
            row.get("pulse_width_us"),
        )
        if partial not in by_partial:
            by_partial[partial] = row
    return by_key, by_exact, by_partial


def _match_label(row: dict, label_indices):
    by_key, by_exact, by_partial = label_indices
    label_key = _clean_text(row.get("label_key"))
    if label_key and label_key in by_key:
        return by_key[label_key], "label_key"

    exact = (
        _clean_text(row.get("stock_solution")),
        _clean_text(row.get("printer_head_id")),
        _clean_text(row.get("nozzle_id")),
        _int_or_none(row.get("pulse_width_us")),
    )
    if exact in by_exact:
        return by_exact[exact], "exact_context"

    partial = (
        _clean_text(row.get("stock_solution")),
        _clean_text(row.get("printer_head_id")),
        _int_or_none(row.get("pulse_width_us")),
    )
    if partial in by_partial:
        return by_partial[partial], "context_without_nozzle"
    return None, None


def _derive_pressure_band_label(pressure_psi, band_low_psi, band_high_psi):
    pressure = _float_or_none(pressure_psi)
    low = _float_or_none(band_low_psi)
    high = _float_or_none(band_high_psi)
    if pressure is None or low is None or high is None:
        return None
    if pressure < low:
        return "too_low"
    if pressure > high:
        return "too_high"
    return "good"


def _apply_label_join(row: dict, matched_label: dict | None, match_mode: str | None):
    out = dict(row)
    out["label_match_mode"] = match_mode
    if not matched_label:
        out["pressure_band_label"] = None
        return out

    for key, value in matched_label.items():
        out[f"label_{key}"] = value
    out["matched_label_key"] = matched_label.get("label_key")
    out["pressure_band_label"] = _derive_pressure_band_label(
        row.get("pressure_psi"),
        matched_label.get("band_low_psi"),
        matched_label.get("band_high_psi"),
    )
    return out


def _abs_path(run_dir: Path, relpath):
    rel = _clean_text(relpath)
    if not rel:
        return None, False
    abs_path = (run_dir / rel).resolve()
    return str(abs_path), bool(abs_path.exists())


def _build_analysis_index(run_dir: Path, analysis_rows, frame_rows):
    by_frame_id = {}
    by_capture_id = {}
    frame_by_frame_id = {row.get("frame_id"): row for row in frame_rows if row.get("frame_id")}
    for row in analysis_rows:
        if not isinstance(row, dict):
            continue
        merged = dict(row)
        frame_id = _clean_text(row.get("frame_id"))
        capture_id = _clean_text(row.get("capture_id"))
        if frame_id and frame_id in frame_by_frame_id:
            frame_row = frame_by_frame_id[frame_id]
            merged.setdefault("image_relpath", frame_row.get("image_relpath"))
            merged.setdefault("background_image_relpath", frame_row.get("background_image_relpath"))
        if frame_id:
            by_frame_id[frame_id] = merged
        if capture_id:
            by_capture_id[capture_id] = merged
    return by_frame_id, by_capture_id


def _build_run_tables(run_dir: Path, labels_index):
    errors = []
    run_meta_path = run_dir / "run_meta.json"
    conditions_path = run_dir / "conditions.jsonl"
    frames_path = run_dir / "frames.jsonl"
    analysis_path = run_dir / "analysis.jsonl"
    plan_snapshot_path = run_dir / "plan_snapshot.json"

    run_meta = _load_json(run_meta_path)
    conditions = list(_iter_jsonl(conditions_path))
    frames = list(_iter_jsonl(frames_path))
    analyses = list(_iter_jsonl(analysis_path))
    plan_snapshot = _load_json(plan_snapshot_path) if plan_snapshot_path.exists() else {}

    analysis_by_frame_id, analysis_by_capture_id = _build_analysis_index(run_dir, analyses, frames)

    run_row = {
        "run_id": run_meta.get("run_id"),
        "process_name": run_meta.get("process_name"),
        "phase_name": run_meta.get("phase_name"),
        "run_dir": str(run_dir),
        "started_at_utc": run_meta.get("started_at_utc"),
        "ended_at_utc": run_meta.get("ended_at_utc"),
        "outcome": run_meta.get("outcome"),
        "error_message": run_meta.get("error_message"),
        "condition_count": len(conditions),
        "frame_count": len(frames),
        "analysis_count": len(analyses),
        "overlay_count": sum(1 for row in analyses if _clean_text(row.get("overlay_image_relpath"))),
        "plan_snapshot_path": str(plan_snapshot_path) if plan_snapshot_path.exists() else None,
        "source_plan_path": plan_snapshot.get("source_plan_path"),
    }

    condition_rows = []
    for condition in conditions:
        row = {
            "run_id": run_meta.get("run_id"),
            **dict(condition or {}),
        }
        bg_abs_path, bg_exists = _abs_path(run_dir, row.get("background_image_relpath"))
        row["background_image_abs_path"] = bg_abs_path
        row["background_image_exists"] = bg_exists
        matched_label, match_mode = _match_label(row, labels_index)
        row = _apply_label_join(row, matched_label, match_mode)
        condition_rows.append(row)

    frame_rows = []
    for frame in frames:
        row = {
            "run_id": run_meta.get("run_id"),
            "process_name": run_meta.get("process_name"),
            "phase_name": run_meta.get("phase_name"),
            **dict(frame or {}),
        }
        image_abs_path, image_exists = _abs_path(run_dir, row.get("image_relpath"))
        bg_abs_path, bg_exists = _abs_path(run_dir, row.get("background_image_relpath"))
        overlay_abs_path, overlay_exists = _abs_path(run_dir, row.get("overlay_image_relpath"))
        row["image_abs_path"] = image_abs_path
        row["image_exists"] = image_exists
        row["background_image_abs_path"] = bg_abs_path
        row["background_image_exists"] = bg_exists
        row["overlay_image_abs_path"] = overlay_abs_path
        row["overlay_image_exists"] = overlay_exists

        analysis = None
        frame_id = _clean_text(row.get("frame_id"))
        capture_id = _clean_text(row.get("capture_id"))
        if frame_id and frame_id in analysis_by_frame_id:
            analysis = analysis_by_frame_id[frame_id]
        elif capture_id and capture_id in analysis_by_capture_id:
            analysis = analysis_by_capture_id[capture_id]
        elif isinstance(frame.get("analysis"), dict):
            analysis = dict(frame.get("analysis"))

        if isinstance(analysis, dict):
            top_level = {
                key: value
                for key, value in analysis.items()
                if key not in {"metrics", "details"}
            }
            for key, value in sorted(top_level.items()):
                row[f"analysis_{key}"] = value
            _flatten_value("analysis_metric_", analysis.get("metrics") or {}, row)
            _flatten_value("analysis_detail_", analysis.get("details") or {}, row)

            if not row.get("overlay_image_relpath") and analysis.get("overlay_image_relpath"):
                row["overlay_image_relpath"] = analysis.get("overlay_image_relpath")
                overlay_abs_path, overlay_exists = _abs_path(run_dir, row.get("overlay_image_relpath"))
                row["overlay_image_abs_path"] = overlay_abs_path
                row["overlay_image_exists"] = overlay_exists
            if not row.get("overlay_capture_id") and analysis.get("overlay_capture_id"):
                row["overlay_capture_id"] = analysis.get("overlay_capture_id")

        matched_label, match_mode = _match_label(row, labels_index)
        row = _apply_label_join(row, matched_label, match_mode)
        frame_rows.append(row)

    return run_row, condition_rows, frame_rows, errors


def build_prebreakup_dataset_tables(root: str | Path, *, labels_path: str | Path | None = None):
    base_root, run_dirs = _resolve_dataset_root(root)
    labels = _load_label_rows(labels_path)
    labels_index = _build_label_indices(labels)

    run_rows = []
    condition_rows = []
    frame_rows = []
    errors = []
    for run_dir in run_dirs:
        try:
            run_row, cond_rows, frm_rows, run_errors = _build_run_tables(run_dir, labels_index)
            run_rows.append(run_row)
            condition_rows.extend(cond_rows)
            frame_rows.extend(frm_rows)
            errors.extend(run_errors)
        except Exception as exc:
            errors.append({"run_dir": str(run_dir), "error": str(exc)})

    run_rows = sorted(run_rows, key=lambda row: str(row.get("run_id") or ""))
    condition_rows = sorted(
        condition_rows,
        key=lambda row: (str(row.get("run_id") or ""), int(_int_or_none(row.get("condition_index")) or 0)),
    )
    frame_rows = sorted(
        frame_rows,
        key=lambda row: (
            str(row.get("run_id") or ""),
            int(_int_or_none(row.get("condition_index")) or 0),
            int(_int_or_none(row.get("flash_delay_us")) or 0),
            int(_int_or_none(row.get("replicate_index")) or 0),
        ),
    )

    return {
        "base_root": str(base_root),
        "run_count": len(run_rows),
        "condition_count": len(condition_rows),
        "frame_count": len(frame_rows),
        "label_count": len(labels),
        "errors": errors,
        "runs": run_rows,
        "conditions": condition_rows,
        "frames": frame_rows,
    }


def export_prebreakup_dataset_tables(
    root: str | Path,
    *,
    out_dir: str | Path | None = None,
    labels_path: str | Path | None = None,
):
    tables = build_prebreakup_dataset_tables(root, labels_path=labels_path)
    output_dir = Path(out_dir).expanduser().resolve() if out_dir else default_export_dir(root).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    run_path = output_dir / "prebreakup_dataset_runs.csv"
    condition_path = output_dir / "prebreakup_dataset_conditions.csv"
    frame_path = output_dir / "prebreakup_dataset_frames.csv"
    manifest_path = output_dir / "prebreakup_dataset_export_manifest.json"

    run_columns = _preferred_columns(tables["runs"], RUN_COLUMNS)
    condition_columns = _preferred_columns(tables["conditions"], CONDITION_COLUMNS)
    frame_columns = _preferred_columns(tables["frames"], FRAME_COLUMNS)

    _write_csv(run_path, run_columns, tables["runs"])
    _write_csv(condition_path, condition_columns, tables["conditions"])
    _write_csv(frame_path, frame_columns, tables["frames"])

    manifest = {
        "schema_version": 1,
        "process_name": PROCESS_NAME,
        "source_root": str(Path(root).expanduser().resolve()),
        "base_root": tables["base_root"],
        "labels_path": None if not labels_path else str(Path(labels_path).expanduser().resolve()),
        "run_count": int(tables["run_count"]),
        "condition_count": int(tables["condition_count"]),
        "frame_count": int(tables["frame_count"]),
        "label_count": int(tables["label_count"]),
        "error_count": int(len(tables["errors"])),
        "errors": list(tables["errors"]),
        "outputs": {
            "runs_csv": str(run_path),
            "conditions_csv": str(condition_path),
            "frames_csv": str(frame_path),
        },
        "parquet_ready": True,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    return {
        **manifest,
        "manifest_path": str(manifest_path),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Export PreBreakupDatasetAcquisitionProcess recorder runs into flat analysis-ready CSV tables."
    )
    parser.add_argument("--root", required=True, help="Experiment dir, calibration_recordings dir, process dir, or run dir.")
    parser.add_argument("--out-dir", default="", help="Output directory for exported CSV tables.")
    parser.add_argument("--labels", default="", help="Optional CSV/JSON/JSONL label table to join onto exported rows.")
    args = parser.parse_args()

    payload = export_prebreakup_dataset_tables(
        args.root,
        out_dir=args.out_dir or None,
        labels_path=args.labels or None,
    )
    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
