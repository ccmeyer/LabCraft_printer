from __future__ import annotations

import csv
import json
import re
from pathlib import Path


PROCESS_NAME = "DropletTimecourseProcess"
ONLINE_STREAM_PROCESS_NAME = "OnlineStreamCalibrationProcess"
SUPPORTED_PROCESS_NAMES = (PROCESS_NAME, ONLINE_STREAM_PROCESS_NAME)
METADATA_FILENAME = "stream_metadata.csv"
STREAM_CAPTURE_LOG_FILENAME = "stream_capture_log.jsonl"
ANALYSIS_DIRNAME = "stream_characterization"
STAGE_DIRNAME = "stage_00_inventory"
TRACKING_MODE_DYNAMIC = "dynamic"
TRACKING_MODE_FIXED_EARLY = "fixed_early"

RUN_COLUMNS = [
    "run_id",
    "metadata_match_status",
    "metadata_row_index",
    "run_dir",
    "process_name",
    "phase_name",
    "outcome",
    "error_message",
    "started_at_utc",
    "ended_at_utc",
    "capture_file_count",
    "indexed_frame_count",
    "analysis_row_count",
    "event_row_count",
    "image_width",
    "image_height",
    "first_flash_delay_us",
    "last_flash_delay_us",
    "timecourse_emergence_us",
    "timecourse_start_us",
    "timecourse_step_us",
    "timecourse_window_us",
    "timecourse_planned_frame_count",
    "gripper_refresh_suspended",
    "tracking_mode",
    "missing_indexed_files",
    "frame_index_csv_path",
    "frame_index_json_path",
]

FRAME_COLUMNS = [
    "run_id",
    "capture_id",
    "capture_index",
    "capture_role",
    "event_index",
    "image_relpath",
    "image_abs_path",
    "image_exists",
    "width",
    "height",
    "captured_at_utc",
    "flash_delay_us",
    "delay_from_emergence_us",
    "stage_text",
]

UNMATCHED_COLUMNS = [
    "run_id",
    "run_dir",
    "outcome",
    "started_at_utc",
    "ended_at_utc",
    "capture_file_count",
    "indexed_frame_count",
    "analysis_row_count",
    "event_row_count",
]

TIMECOURSE_SUMMARY_RE = re.compile(
    r"Timecourse:\s+emergence=(?P<emergence>\d+)\s+us,\s+start=(?P<start>\d+)\s+us,\s+"
    r"step=(?P<step>\d+)\s+us,\s+window=(?P<window>\d+)\s+us\s+\((?P<frames>\d+)\s+frames\)",
    re.IGNORECASE,
)
FLASH_DELAY_RE = re.compile(r"(?:@|flash_delay\s*=)\s*(?P<delay>\d+)\s*us", re.IGNORECASE)


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


def _bool_or_none(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return bool(value)


def _json_cell(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def _sanitize_field_name(name: str) -> str:
    text = re.sub(r"[^0-9a-zA-Z]+", "_", str(name).strip().lower()).strip("_")
    return text or "field"


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


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _is_supported_process_name(name: str | None) -> bool:
    return str(name or "") in SUPPORTED_PROCESS_NAMES


def _discover_process_roots(calibration_root: Path):
    return [
        calibration_root / process_name
        for process_name in SUPPORTED_PROCESS_NAMES
        if (calibration_root / process_name).is_dir()
    ]


def _experiment_root_from_run_dir(run_dir: Path) -> Path:
    process_root = run_dir.parent
    if not _is_supported_process_name(process_root.name):
        supported = ", ".join(SUPPORTED_PROCESS_NAMES)
        raise ValueError(f"Run directory is not inside a supported process root ({supported}): {run_dir}")
    calibration_root = process_root.parent
    if calibration_root.name != "calibration_recordings":
        raise ValueError(f"Unexpected calibration root for run dir: {run_dir}")
    return calibration_root.parent


def resolve_experiment_root(root: str | Path) -> Path:
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        raise FileNotFoundError(f"Experiment root does not exist: {root_path}")

    if root_path.is_file():
        if root_path.name == METADATA_FILENAME:
            return root_path.parent
        if root_path.name == "run_meta.json":
            return _experiment_root_from_run_dir(root_path.parent)
        raise ValueError(f"Unsupported file input: {root_path}")

    process_roots = _discover_process_roots(root_path / "calibration_recordings")
    if (root_path / METADATA_FILENAME).exists() and process_roots:
        return root_path

    if root_path.name == "calibration_recordings" and _discover_process_roots(root_path):
        return root_path.parent

    if _is_supported_process_name(root_path.name):
        calibration_root = root_path.parent
        if calibration_root.name != "calibration_recordings":
            raise ValueError(f"Unexpected process root: {root_path}")
        return calibration_root.parent

    if (root_path / "run_meta.json").exists():
        return _experiment_root_from_run_dir(root_path)

    raise ValueError(
        "Could not resolve experiment root. Point the tool at the experiment directory, "
        "its stream_metadata.csv, the calibration_recordings directory, the process directory, "
        "or a specific run directory."
    )


def process_root_for_experiment(experiment_root: str | Path) -> Path:
    root = resolve_experiment_root(experiment_root)
    calibration_root = root / "calibration_recordings"
    process_roots = _discover_process_roots(calibration_root)
    if not process_roots:
        raise FileNotFoundError(f"No supported process roots exist under: {calibration_root}")
    return process_roots[0]


def metadata_path_for_experiment(experiment_root: str | Path) -> Path:
    root = resolve_experiment_root(experiment_root)
    metadata_path = root / METADATA_FILENAME
    if not metadata_path.exists():
        raise FileNotFoundError(f"Metadata CSV does not exist: {metadata_path}")
    return metadata_path


def stream_capture_log_path_for_experiment(experiment_root: str | Path) -> Path:
    return resolve_experiment_root(experiment_root) / STREAM_CAPTURE_LOG_FILENAME


def default_output_root(experiment_root: str | Path) -> Path:
    return resolve_experiment_root(experiment_root) / "analysis" / ANALYSIS_DIRNAME


def load_metadata_rows(experiment_root: str | Path):
    metadata_path = metadata_path_for_experiment(experiment_root)
    with metadata_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        raw_rows = list(reader)

    field_map = {
        field: f"metadata_{_sanitize_field_name(field)}" for field in list(reader.fieldnames or [])
    }

    rows = []
    for index, raw in enumerate(raw_rows, start=1):
        row = {
            "metadata_row_index": int(index),
            "metadata_source_path": str(metadata_path),
            "metadata_raw": dict(raw),
        }
        for field, value in raw.items():
            row[field_map[field]] = _clean_text(value)
        rows.append(row)

    return rows, field_map


def load_stream_capture_rows(experiment_root: str | Path):
    log_path = stream_capture_log_path_for_experiment(experiment_root)
    rows_by_run_id = {}
    if not log_path.exists():
        return rows_by_run_id, str(log_path)

    for row in _iter_jsonl(log_path):
        run_id = _clean_text((row or {}).get("dataset_run_id")) or _clean_text((row or {}).get("timecourse_run_id"))
        if not run_id:
            continue
        gripper_refresh_suspended = _bool_or_none((row or {}).get("gripper_refresh_suspended"))
        rows_by_run_id[run_id] = {
            "capture_mode": _clean_text((row or {}).get("capture_mode")),
            "dataset_process_name": _clean_text((row or {}).get("dataset_process_name")),
            "gripper_refresh_suspended": gripper_refresh_suspended,
            "tracking_mode": (
                TRACKING_MODE_FIXED_EARLY
                if bool(gripper_refresh_suspended)
                else TRACKING_MODE_DYNAMIC
            ),
        }
    return rows_by_run_id, str(log_path)


def discover_run_dirs(experiment_root: str | Path):
    run_dirs = []
    for process_root in _discover_process_roots(resolve_experiment_root(experiment_root) / "calibration_recordings"):
        run_dirs.extend(
            path for path in process_root.iterdir() if path.is_dir() and (path / "run_meta.json").exists()
        )
    return sorted(run_dirs)


def _parse_timecourse_summary(events):
    for event in events:
        if str(event.get("event_type", "")) != "stage_changed":
            continue
        message = _clean_text((event.get("payload") or {}).get("message"))
        if not message:
            continue
        match = TIMECOURSE_SUMMARY_RE.search(message)
        if not match:
            continue
        return {
            "timecourse_emergence_us": int(match.group("emergence")),
            "timecourse_start_us": int(match.group("start")),
            "timecourse_step_us": int(match.group("step")),
            "timecourse_window_us": int(match.group("window")),
            "timecourse_planned_frame_count": int(match.group("frames")),
        }
    return {
        "timecourse_emergence_us": None,
        "timecourse_start_us": None,
        "timecourse_step_us": None,
        "timecourse_window_us": None,
        "timecourse_planned_frame_count": None,
    }


def _parse_flash_delay_us(text) -> int | None:
    clean = _clean_text(text)
    if not clean:
        return None
    match = FLASH_DELAY_RE.search(clean)
    if not match:
        return None
    return int(match.group("delay"))


def build_frame_index(run_dir: str | Path, *, run_id: str | None = None):
    run_path = Path(run_dir).expanduser().resolve()
    events = list(_iter_jsonl(run_path / "events.jsonl"))
    timecourse = _parse_timecourse_summary(events)

    current_flash_delay_us = None
    saved_capture_info = {}
    rows = []

    for event in events:
        event_type = str(event.get("event_type", ""))
        payload = event.get("payload") or {}

        if event_type == "stage_changed":
            message = _clean_text(payload.get("message"))
            parsed_delay = _parse_flash_delay_us(message)
            if parsed_delay is not None:
                current_flash_delay_us = parsed_delay
            continue

        if event_type == "capture_saved":
            capture_id = _clean_text(payload.get("capture_id"))
            if not capture_id:
                continue
            stage_text = _clean_text((payload.get("metadata") or {}).get("stage_text"))
            saved_capture_info[capture_id] = {
                "stage_text": stage_text,
                "flash_delay_us": _parse_flash_delay_us(stage_text) or current_flash_delay_us,
            }
            continue

        if event_type != "capture_result" or str(payload.get("status", "")) != "success":
            continue

        capture_ref = payload.get("capture_ref") or {}
        capture_id = _clean_text(capture_ref.get("capture_id"))
        fallback = saved_capture_info.get(capture_id or "", {})
        stage_text = (
            _clean_text(payload.get("stage_text"))
            or _clean_text(capture_ref.get("stage_text"))
            or fallback.get("stage_text")
        )
        flash_delay_us = (
            _parse_flash_delay_us(stage_text)
            or fallback.get("flash_delay_us")
            or current_flash_delay_us
        )

        image_relpath = _clean_text(capture_ref.get("image_relpath"))
        image_abs_path = None
        image_exists = False
        if image_relpath:
            image_path = (run_path / image_relpath).resolve()
            image_abs_path = str(image_path)
            image_exists = bool(image_path.exists())

        row = {
            "run_id": run_id or run_path.name,
            "capture_id": capture_id,
            "capture_index": _int_or_none(capture_ref.get("capture_index")),
            "capture_role": _clean_text(capture_ref.get("capture_role")),
            "event_index": _int_or_none(event.get("event_index")),
            "image_relpath": image_relpath,
            "image_abs_path": image_abs_path,
            "image_exists": bool(image_exists),
            "width": _int_or_none(capture_ref.get("width")),
            "height": _int_or_none(capture_ref.get("height")),
            "captured_at_utc": _clean_text(capture_ref.get("captured_at_utc")),
            "flash_delay_us": flash_delay_us,
            "delay_from_emergence_us": None,
            "stage_text": stage_text,
        }
        emergence_time_us = timecourse.get("timecourse_emergence_us")
        if emergence_time_us is not None and flash_delay_us is not None:
            row["delay_from_emergence_us"] = int(flash_delay_us - emergence_time_us)
        rows.append(row)

    rows.sort(
        key=lambda item: (
            _int_or_none(item.get("capture_index")) or 0,
            _int_or_none(item.get("event_index")) or 0,
        )
    )

    return {
        "run_id": run_id or run_path.name,
        "run_dir": str(run_path),
        **timecourse,
        "frames": rows,
    }


def _count_capture_files(run_dir: Path) -> int:
    captures_dir = run_dir / "captures"
    if not captures_dir.exists():
        return 0
    return sum(1 for path in captures_dir.iterdir() if path.is_file())


def build_stage0_inventory(
    experiment_root: str | Path,
    *,
    include_unmatched: bool = False,
    run_ids: list[str] | None = None,
    limit_runs: int | None = None,
):
    experiment_path = resolve_experiment_root(experiment_root)
    process_root = process_root_for_experiment(experiment_path)
    metadata_rows, field_map = load_metadata_rows(experiment_path)
    stream_capture_rows, stream_capture_log_path = load_stream_capture_rows(experiment_path)
    discovered_run_dirs = discover_run_dirs(experiment_path)
    run_dir_by_id = {path.name: path for path in discovered_run_dirs}

    matched_run_ids = []
    missing_metadata_run_ids = []
    all_rows_by_id = {}
    frames_by_run_id = {}

    for metadata_row in metadata_rows:
        run_id = metadata_row.get("metadata_dataset_name")
        run_dir = run_dir_by_id.get(run_id or "")
        if run_dir is None:
            missing_metadata_run_ids.append(run_id)
            continue

        run_meta = _load_json(run_dir / "run_meta.json")
        events = list(_iter_jsonl(run_dir / "events.jsonl"))
        analyses = list(_iter_jsonl(run_dir / "analysis.jsonl"))
        frame_index = build_frame_index(run_dir, run_id=run_id)
        frame_rows = list(frame_index["frames"])
        frames_by_run_id[run_id] = frame_rows
        matched_run_ids.append(run_id)
        stream_capture_row = stream_capture_rows.get(run_id, {})

        row = {
            "run_id": run_id,
            "metadata_match_status": "matched_csv",
            "metadata_row_index": metadata_row["metadata_row_index"],
            "run_dir": str(run_dir),
            "process_name": _clean_text(run_meta.get("process_name")),
            "phase_name": _clean_text(run_meta.get("phase_name")),
            "capture_mode": stream_capture_row.get("capture_mode"),
            "dataset_process_name": stream_capture_row.get("dataset_process_name"),
            "outcome": _clean_text(run_meta.get("outcome")),
            "error_message": _clean_text(run_meta.get("error_message")),
            "started_at_utc": _clean_text(run_meta.get("started_at_utc")),
            "ended_at_utc": _clean_text(run_meta.get("ended_at_utc")),
            "capture_file_count": _count_capture_files(run_dir),
            "indexed_frame_count": len(frame_rows),
            "analysis_row_count": len(analyses),
            "event_row_count": len(events),
            "image_width": frame_rows[0]["width"] if frame_rows else None,
            "image_height": frame_rows[0]["height"] if frame_rows else None,
            "first_flash_delay_us": frame_rows[0]["flash_delay_us"] if frame_rows else None,
            "last_flash_delay_us": frame_rows[-1]["flash_delay_us"] if frame_rows else None,
            "timecourse_emergence_us": frame_index["timecourse_emergence_us"],
            "timecourse_start_us": frame_index["timecourse_start_us"],
            "timecourse_step_us": frame_index["timecourse_step_us"],
            "timecourse_window_us": frame_index["timecourse_window_us"],
            "timecourse_planned_frame_count": frame_index["timecourse_planned_frame_count"],
            "gripper_refresh_suspended": stream_capture_row.get("gripper_refresh_suspended"),
            "tracking_mode": stream_capture_row.get("tracking_mode") or TRACKING_MODE_DYNAMIC,
            "missing_indexed_files": sum(1 for frame in frame_rows if not frame["image_exists"]),
            "frame_index_csv_path": None,
            "frame_index_json_path": None,
        }
        for key, value in metadata_row.items():
            row[key] = value
        all_rows_by_id[run_id] = row

    unmatched_rows = []
    for run_dir in discovered_run_dirs:
        if run_dir.name in matched_run_ids:
            continue
        run_meta = _load_json(run_dir / "run_meta.json")
        events = list(_iter_jsonl(run_dir / "events.jsonl"))
        analyses = list(_iter_jsonl(run_dir / "analysis.jsonl"))
        frame_index = build_frame_index(run_dir, run_id=run_dir.name)
        frame_rows = list(frame_index["frames"])
        frames_by_run_id[run_dir.name] = frame_rows
        stream_capture_row = stream_capture_rows.get(run_dir.name, {})

        row = {
            "run_id": run_dir.name,
            "metadata_match_status": "unmatched_run_dir",
            "metadata_row_index": None,
            "run_dir": str(run_dir),
            "process_name": _clean_text(run_meta.get("process_name")),
            "phase_name": _clean_text(run_meta.get("phase_name")),
            "capture_mode": stream_capture_row.get("capture_mode"),
            "dataset_process_name": stream_capture_row.get("dataset_process_name"),
            "outcome": _clean_text(run_meta.get("outcome")),
            "error_message": _clean_text(run_meta.get("error_message")),
            "started_at_utc": _clean_text(run_meta.get("started_at_utc")),
            "ended_at_utc": _clean_text(run_meta.get("ended_at_utc")),
            "capture_file_count": _count_capture_files(run_dir),
            "indexed_frame_count": len(frame_rows),
            "analysis_row_count": len(analyses),
            "event_row_count": len(events),
            "image_width": frame_rows[0]["width"] if frame_rows else None,
            "image_height": frame_rows[0]["height"] if frame_rows else None,
            "first_flash_delay_us": frame_rows[0]["flash_delay_us"] if frame_rows else None,
            "last_flash_delay_us": frame_rows[-1]["flash_delay_us"] if frame_rows else None,
            "timecourse_emergence_us": frame_index["timecourse_emergence_us"],
            "timecourse_start_us": frame_index["timecourse_start_us"],
            "timecourse_step_us": frame_index["timecourse_step_us"],
            "timecourse_window_us": frame_index["timecourse_window_us"],
            "timecourse_planned_frame_count": frame_index["timecourse_planned_frame_count"],
            "gripper_refresh_suspended": stream_capture_row.get("gripper_refresh_suspended"),
            "tracking_mode": stream_capture_row.get("tracking_mode") or TRACKING_MODE_DYNAMIC,
            "missing_indexed_files": sum(1 for frame in frame_rows if not frame["image_exists"]),
            "frame_index_csv_path": None,
            "frame_index_json_path": None,
        }
        all_rows_by_id[run_dir.name] = row
        unmatched_rows.append(row)

    unmatched_rows.sort(key=lambda item: item["run_id"])

    if run_ids:
        selected_run_ids = []
        for run_id in run_ids:
            if run_id not in all_rows_by_id:
                raise ValueError(f"Requested run_id was not found: {run_id}")
            selected_run_ids.append(run_id)
    else:
        selected_run_ids = list(matched_run_ids)
        if include_unmatched:
            selected_run_ids.extend(row["run_id"] for row in unmatched_rows)

    if limit_runs is not None and limit_runs > 0:
        selected_run_ids = selected_run_ids[:limit_runs]

    selected_rows = [all_rows_by_id[run_id] for run_id in selected_run_ids]

    return {
        "experiment_root": str(experiment_path),
        "process_root": str(process_root),
        "metadata_path": str(metadata_path_for_experiment(experiment_path)),
        "stream_capture_log_path": stream_capture_log_path,
        "metadata_field_map": field_map,
        "metadata_row_count": int(len(metadata_rows)),
        "discovered_run_dir_count": int(len(discovered_run_dirs)),
        "matched_run_count": int(len(matched_run_ids)),
        "selected_run_count": int(len(selected_rows)),
        "unmatched_run_count": int(len(unmatched_rows)),
        "missing_metadata_run_count": int(len(missing_metadata_run_ids)),
        "missing_metadata_run_ids": missing_metadata_run_ids,
        "selected_runs": selected_rows,
        "unmatched_runs": unmatched_rows,
        "frames_by_run_id": frames_by_run_id,
    }


def export_stage0_inventory(
    experiment_root: str | Path,
    *,
    output_root: str | Path | None = None,
    include_unmatched: bool = False,
    run_ids: list[str] | None = None,
    limit_runs: int | None = None,
):
    inventory = build_stage0_inventory(
        experiment_root,
        include_unmatched=include_unmatched,
        run_ids=run_ids,
        limit_runs=limit_runs,
    )

    output_path = Path(output_root).expanduser().resolve() if output_root else default_output_root(experiment_root)
    output_path.mkdir(parents=True, exist_ok=True)

    selected_rows = []
    for row in inventory["selected_runs"]:
        row_copy = dict(row)
        run_id = row_copy["run_id"]
        stage_dir = output_path / "runs" / run_id / STAGE_DIRNAME
        frame_csv_path = stage_dir / "frame_index.csv"
        frame_json_path = stage_dir / "frame_index.json"
        frame_rows = inventory["frames_by_run_id"][run_id]
        _write_csv(frame_csv_path, _preferred_columns(frame_rows, FRAME_COLUMNS), frame_rows)
        _write_json(
            frame_json_path,
            {
                "schema_version": 1,
                "run_id": run_id,
                "run_dir": row_copy["run_dir"],
                "frame_count": len(frame_rows),
                "frames": frame_rows,
            },
        )
        row_copy["frame_index_csv_path"] = str(frame_csv_path)
        row_copy["frame_index_json_path"] = str(frame_json_path)
        selected_rows.append(row_copy)

    unmatched_rows = [dict(row) for row in inventory["unmatched_runs"]]

    run_inventory_csv = output_path / "run_inventory.csv"
    run_inventory_json = output_path / "run_inventory.json"
    unmatched_csv = output_path / "unmatched_runs.csv"
    manifest_json = output_path / "inventory_manifest.json"

    _write_csv(run_inventory_csv, _preferred_columns(selected_rows, RUN_COLUMNS), selected_rows)
    _write_json(
        run_inventory_json,
        {
            "schema_version": 1,
            "experiment_root": inventory["experiment_root"],
            "process_root": inventory["process_root"],
            "metadata_path": inventory["metadata_path"],
            "stream_capture_log_path": inventory["stream_capture_log_path"],
            "selected_run_count": len(selected_rows),
            "matched_run_count": inventory["matched_run_count"],
            "unmatched_run_count": inventory["unmatched_run_count"],
            "missing_metadata_run_ids": inventory["missing_metadata_run_ids"],
            "runs": selected_rows,
        },
    )
    _write_csv(unmatched_csv, _preferred_columns(unmatched_rows, UNMATCHED_COLUMNS), unmatched_rows)

    manifest = {
        "schema_version": 1,
        "stage": "inventory",
        "experiment_root": inventory["experiment_root"],
        "process_root": inventory["process_root"],
        "metadata_path": inventory["metadata_path"],
        "stream_capture_log_path": inventory["stream_capture_log_path"],
        "output_root": str(output_path),
        "metadata_row_count": inventory["metadata_row_count"],
        "discovered_run_dir_count": inventory["discovered_run_dir_count"],
        "matched_run_count": inventory["matched_run_count"],
        "selected_run_count": len(selected_rows),
        "unmatched_run_count": inventory["unmatched_run_count"],
        "missing_metadata_run_count": inventory["missing_metadata_run_count"],
        "missing_metadata_run_ids": inventory["missing_metadata_run_ids"],
        "include_unmatched": bool(include_unmatched),
        "requested_run_ids": list(run_ids or []),
        "limit_runs": limit_runs,
        "outputs": {
            "run_inventory_csv": str(run_inventory_csv),
            "run_inventory_json": str(run_inventory_json),
            "unmatched_runs_csv": str(unmatched_csv),
        },
    }
    _write_json(manifest_json, manifest)
    manifest["manifest_path"] = str(manifest_json)
    return manifest
