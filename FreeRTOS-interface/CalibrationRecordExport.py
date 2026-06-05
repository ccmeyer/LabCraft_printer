from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.export_calibration_recording_summary import (
    build_calibration_recording_summary_rows,
    export_calibration_recording_summary,
)


class CalibrationRecordExportError(Exception):
    """Raised when calibration records cannot be exported."""


OPTIONAL_EXPERIMENT_FILES = (
    "calibration.json",
    "experiment_design.json",
    "progress.json",
    "experiment_audit.jsonl",
)


def _sanitize_filename_part(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    text = text.strip("._-")
    return text or "experiment"


def _timestamp(created_at: datetime | None) -> tuple[str, str]:
    dt = created_at or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y%m%d_%H%M%S"), dt_utc.isoformat().replace("+00:00", "Z")


def _unique_archive_path(output_dir: Path, stem: str) -> Path:
    candidate = output_dir / f"{stem}.zip"
    if not candidate.exists():
        return candidate
    idx = 2
    while True:
        candidate = output_dir / f"{stem}_{idx}.zip"
        if not candidate.exists():
            return candidate
        idx += 1


def _repo_root() -> Path:
    return REPO_ROOT


def _best_effort_git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(_repo_root()),
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return str(result.stdout or "").strip()


def _iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path


def _has_recording_run(recordings_root: Path) -> bool:
    if not recordings_root.exists() or not recordings_root.is_dir():
        return False
    for process_dir in recordings_root.iterdir():
        if not process_dir.is_dir():
            continue
        for run_dir in process_dir.iterdir():
            if not run_dir.is_dir():
                continue
            if (
                run_dir.name.startswith("run_")
                or (run_dir / "run_meta.json").exists()
                or (run_dir / "verdict.json").exists()
                or (run_dir / "events.jsonl").exists()
                or (run_dir / "analysis.jsonl").exists()
            ):
                return True
    return False


def _add_file(zf: zipfile.ZipFile, src: Path, arcname: str, included: set[str]) -> None:
    arc_path = Path(arcname)
    if arc_path.is_absolute() or ".." in arc_path.parts:
        raise CalibrationRecordExportError(f"Unsafe archive path: {arcname}")
    zf.write(src, arcname=arcname)
    if arc_path.parts:
        included.add(arc_path.parts[0])


def _build_manifest(
    *,
    experiment_dir: Path,
    archive_path: Path,
    exported_at_utc: str,
    included_top_level_items: set[str],
    summary_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "exported_at_utc": exported_at_utc,
        "experiment_name": experiment_dir.name,
        "experiment_path": str(experiment_dir),
        "archive_name": archive_path.name,
        "included_top_level_items": sorted(included_top_level_items | {"manifest.json"}),
        "summary": {
            "row_count": int(summary_result.get("row_count") or 0),
            "needs_review_count": int(summary_result.get("needs_review_count") or 0),
            "parse_error_count": int(summary_result.get("parse_error_count") or 0),
            "tool_error_count": int(summary_result.get("tool_error_count") or 0),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "hostname": platform.node(),
        },
        "git_sha": _best_effort_git_sha(),
    }


def export_calibration_records(
    experiment_dir: str | os.PathLike[str],
    output_dir: str | os.PathLike[str] | None = None,
    *,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    experiment_path = Path(experiment_dir).resolve()
    if not experiment_path.exists():
        raise CalibrationRecordExportError(f"Experiment directory not found: {experiment_path}")
    if not experiment_path.is_dir():
        raise CalibrationRecordExportError(f"Experiment path is not a directory: {experiment_path}")

    recordings_root = experiment_path / "calibration_recordings"
    if not recordings_root.exists():
        raise CalibrationRecordExportError(f"calibration_recordings not found: {recordings_root}")
    if not recordings_root.is_dir():
        raise CalibrationRecordExportError(f"calibration_recordings is not a directory: {recordings_root}")
    if not _has_recording_run(recordings_root):
        raise CalibrationRecordExportError(f"No calibration recording runs found in: {recordings_root}")

    out_dir = Path(output_dir).expanduser().resolve() if output_dir else (Path.home() / "Downloads").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp_for_name, exported_at_utc = _timestamp(created_at)
    experiment_name = _sanitize_filename_part(experiment_path.name)
    archive_stem = f"LabCraft_calibration_records_{experiment_name}_{timestamp_for_name}"
    archive_path = _unique_archive_path(out_dir, archive_stem)

    included: set[str] = set()
    with tempfile.TemporaryDirectory() as tmp:
        summary_path = Path(tmp) / "calibration_recordings_summary.csv"
        summary_result = export_calibration_recording_summary(
            experiment_path,
            out_path=summary_path,
        )
        # Build rows too so tests and callers can rely on row_count even if the
        # summary exporter changes its return payload in the future.
        _rows, summary_stats = build_calibration_recording_summary_rows(experiment_path)
        summary_result.update(summary_stats)

        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for src in _iter_files(recordings_root):
                rel = src.relative_to(experiment_path).as_posix()
                _add_file(zf, src, rel, included)

            for filename in OPTIONAL_EXPERIMENT_FILES:
                src = experiment_path / filename
                if src.is_file():
                    _add_file(zf, src, filename, included)

            _add_file(zf, summary_path, "calibration_recordings_summary.csv", included)

            manifest = _build_manifest(
                experiment_dir=experiment_path,
                archive_path=archive_path,
                exported_at_utc=exported_at_utc,
                included_top_level_items=included,
                summary_result=summary_result,
            )
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))

    return {
        "archive_path": str(archive_path),
        "archive_name": archive_path.name,
        "archive_size_bytes": int(archive_path.stat().st_size),
        "experiment_dir": str(experiment_path),
        "recordings_root": str(recordings_root),
        "included_top_level_items": sorted(included | {"manifest.json"}),
        "summary": {
            "row_count": int(summary_result.get("row_count") or 0),
            "needs_review_count": int(summary_result.get("needs_review_count") or 0),
            "parse_error_count": int(summary_result.get("parse_error_count") or 0),
            "tool_error_count": int(summary_result.get("tool_error_count") or 0),
        },
    }
