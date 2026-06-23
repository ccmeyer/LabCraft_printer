from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "reset_debug_bundle_v1"
REPO_ROOT = Path(__file__).resolve().parents[1]


class ResetDebugBundleError(Exception):
    """Raised when a reset debug bundle cannot be exported."""


def _sanitize_filename_part(value: Any, *, default: str = "unknown") -> str:
    raw_text = "" if value is None else str(value)
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_text.strip())
    text = text.strip("._-")
    return text or default


def _first_present(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is not None:
            return value
    return default


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


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(k): _json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [_json_safe(v) for v in value]
        return str(value)


def _best_effort_git_sha(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
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


def _resolve_output_dir(output_dir: str | os.PathLike[str] | None) -> Path:
    if output_dir is None:
        return (Path.home() / "Downloads").resolve()
    return Path(output_dir).expanduser().resolve()


def _archive_path(top_dir: str, *parts: str) -> str:
    return Path(top_dir, *parts).as_posix()


def _add_file(
    zf: zipfile.ZipFile,
    src: Path,
    arcname: str,
    *,
    included_files: list[dict[str, Any]],
    kind: str,
    reason: str | None = None,
) -> None:
    arc_path = Path(arcname)
    if arc_path.is_absolute() or ".." in arc_path.parts:
        raise ResetDebugBundleError(f"Unsafe archive path: {arcname}")
    zf.write(src, arcname=arcname)
    item = {
        "kind": kind,
        "source_path": str(src),
        "archive_path": arcname,
    }
    if reason:
        item["reason"] = reason
    included_files.append(item)


def _add_json(
    zf: zipfile.ZipFile,
    arcname: str,
    payload: Any,
    *,
    included_files: list[dict[str, Any]],
    kind: str,
) -> None:
    arc_path = Path(arcname)
    if arc_path.is_absolute() or ".." in arc_path.parts:
        raise ResetDebugBundleError(f"Unsafe archive path: {arcname}")
    zf.writestr(arcname, json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n")
    included_files.append({"kind": kind, "source_path": None, "archive_path": arcname})


def _snapshot_entries(context: dict[str, Any]) -> list[dict[str, Any]]:
    direct = context.get("black_box_snapshots")
    if direct is not None:
        return [dict(item or {}) for item in list(direct or [])]
    machine = dict(context.get("machine") or {})
    return [dict(item or {}) for item in list(machine.get("black_box_snapshots") or [])]


def export_reset_debug_bundle(
    context: dict[str, Any],
    output_dir: str | os.PathLike[str] | None = None,
    *,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    context = dict(context or {})
    reset_report = dict(context.get("reset_report") or {})
    connection_loss_report = dict(
        context.get("connection_loss_report")
        or context.get("serial_connection_lost_report")
        or {}
    )
    bundle_kind = str(context.get("bundle_kind") or "").strip()
    if not bundle_kind:
        if reset_report:
            bundle_kind = "reset_report"
        elif connection_loss_report:
            bundle_kind = "connection_loss"
        else:
            bundle_kind = "reset_report"
    if bundle_kind == "reset_report" and not reset_report:
        raise ResetDebugBundleError("No reset report is available to export.")
    if bundle_kind == "connection_loss" and not connection_loss_report:
        raise ResetDebugBundleError("No connection-loss report is available to export.")
    if bundle_kind not in {"reset_report", "connection_loss"}:
        raise ResetDebugBundleError(f"Unsupported debug bundle kind: {bundle_kind or 'unknown'}")

    out_dir = _resolve_output_dir(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    repo_root = Path(context.get("repo_root") or REPO_ROOT).expanduser().resolve()
    timestamp_for_name, exported_at_utc = _timestamp(created_at)
    machine = dict(context.get("machine") or {})
    session_id = (
        context.get("black_box_session_id")
        or machine.get("black_box_session_id")
        or connection_loss_report.get("session_id")
    )
    reset_seq32 = _first_present(reset_report.get("seq32"), reset_report.get("reset_seq32"))
    if bundle_kind == "reset_report":
        reset_cause = reset_report.get("reset_cause_name") or reset_report.get("reset_cause") or "reset"
        seq32 = _first_present(reset_seq32, default="unknown_seq")
        archive_stem = (
            f"LabCraft_reset_debug_bundle_{timestamp_for_name}_"
            f"{_sanitize_filename_part(reset_cause, default='reset')}_"
            f"{_sanitize_filename_part(seq32, default='unknown_seq')}"
        )
    else:
        reason = connection_loss_report.get("reason") or "connection_loss"
        archive_stem = (
            f"LabCraft_connection_lost_debug_bundle_{timestamp_for_name}_"
            f"{_sanitize_filename_part(reason, default='connection_loss')}_"
            f"{_sanitize_filename_part(session_id, default='unknown_session')}"
        )
    archive_path = _unique_archive_path(out_dir, archive_stem)
    top_dir = archive_path.stem

    included_files: list[dict[str, Any]] = []
    missing_files: list[dict[str, Any]] = []
    black_box_manifest: list[dict[str, Any]] = []

    reset_log_path_raw = context.get("reset_report_log_path")
    reset_log_error = context.get("reset_report_log_error")
    reset_log_path = Path(reset_log_path_raw).expanduser() if reset_log_path_raw else None

    snapshots = _snapshot_entries(context)
    if not snapshots:
        missing_files.append({"kind": "black_box_snapshot", "reason": "none_available", "path": None})
    primary_snapshot_path = ""
    if bundle_kind == "reset_report":
        for entry in reversed(snapshots):
            if str(entry.get("reason") or "") == "reset_report" and entry.get("path"):
                primary_snapshot_path = str(entry.get("path") or "")
                break
    else:
        primary_snapshot_path = str(connection_loss_report.get("black_box_log_path") or "")

    manifest_base = {
        "schema_version": SCHEMA_VERSION,
        "bundle_kind": bundle_kind,
        "exported_at_utc": exported_at_utc,
        "archive_name": archive_path.name,
        "bundle_root": top_dir,
        "reset": {
            "summary": reset_report.get("summary"),
            "reset_cause": reset_report.get("reset_cause"),
            "reset_cause_name": reset_report.get("reset_cause_name"),
            "seq32": reset_seq32,
            "reset_flags_raw": reset_report.get("reset_flags_raw"),
            "reset_flag_names": list(reset_report.get("reset_flag_names") or []),
            "reset_flag_summary": reset_report.get("reset_flag_summary"),
            "pending": reset_report.get("pending"),
            "sticky": reset_report.get("sticky"),
        },
        "connection_loss": {
            "summary": connection_loss_report.get("summary"),
            "reason": connection_loss_report.get("reason"),
            "requested_stop": connection_loss_report.get("requested_stop"),
            "exception_type": connection_loss_report.get("exception_type"),
            "message": connection_loss_report.get("message"),
            "black_box_log_path": connection_loss_report.get("black_box_log_path"),
            "black_box_log_error": connection_loss_report.get("black_box_log_error"),
        },
        "session_id": session_id,
        "machine": {
            "port": context.get("port") or machine.get("port") or connection_loss_report.get("port"),
            "profile": context.get("profile") or machine.get("profile"),
        },
        "app": {
            "repo_root": str(repo_root),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "hostname": platform.node(),
        },
        "git_sha": _best_effort_git_sha(repo_root),
        "reset_report_log_error": reset_log_error,
    }

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if bundle_kind == "reset_report":
            _add_json(
                zf,
                _archive_path(top_dir, "reset_report", "current_reset_report.json"),
                reset_report,
                included_files=included_files,
                kind="current_reset_report",
            )

            if reset_log_path is not None and reset_log_path.is_file():
                _add_file(
                    zf,
                    reset_log_path,
                    _archive_path(top_dir, "reset_report", "board_reset_reports.jsonl"),
                    included_files=included_files,
                    kind="board_reset_reports_jsonl",
                )
            else:
                missing_files.append(
                    {
                        "kind": "board_reset_reports_jsonl",
                        "path": str(reset_log_path) if reset_log_path is not None else None,
                        "error": reset_log_error or "not_available",
                    }
                )
        else:
            _add_json(
                zf,
                _archive_path(top_dir, "connection_loss", "current_connection_loss_report.json"),
                connection_loss_report,
                included_files=included_files,
                kind="current_connection_loss_report",
            )

        used_arcnames: set[str] = set()
        for idx, entry in enumerate(snapshots, start=1):
            reason = _sanitize_filename_part(entry.get("reason") or "unknown", default="unknown")
            src_raw = entry.get("path")
            src = Path(src_raw).expanduser() if src_raw else None
            base_name = _sanitize_filename_part(src.name if src else f"snapshot_{idx}.json", default=f"snapshot_{idx}.json")
            arcname = _archive_path(top_dir, "black_box", reason, base_name)
            while arcname in used_arcnames:
                arcname = _archive_path(top_dir, "black_box", reason, f"{idx}_{base_name}")
            used_arcnames.add(arcname)
            manifest_entry = dict(entry)
            manifest_entry["reason"] = reason
            manifest_entry["archive_path"] = arcname
            manifest_entry["role"] = (
                "primary_trigger"
                if primary_snapshot_path and str(src_raw or "") == primary_snapshot_path
                else "same_session_context"
            )
            if src is not None and src.is_file():
                _add_file(
                    zf,
                    src,
                    arcname,
                    included_files=included_files,
                    kind="black_box_snapshot",
                    reason=reason,
                )
                manifest_entry["included"] = True
            else:
                manifest_entry["included"] = False
                missing_files.append(
                    {
                        "kind": "black_box_snapshot",
                        "reason": reason,
                        "path": str(src) if src is not None else None,
                        "error": "not_available",
                    }
                )
            black_box_manifest.append(manifest_entry)

        manifest = dict(manifest_base)
        manifest_arcname = _archive_path(top_dir, "manifest.json")
        manifest["included_files"] = included_files + [
            {"kind": "manifest", "source_path": None, "archive_path": manifest_arcname}
        ]
        manifest["missing_files"] = missing_files
        manifest["black_box_snapshots"] = black_box_manifest
        zf.writestr(
            manifest_arcname,
            json.dumps(_json_safe(manifest), indent=2, sort_keys=True) + "\n",
        )

    return {
        "archive_path": str(archive_path),
        "archive_name": archive_path.name,
        "archive_size_bytes": int(archive_path.stat().st_size),
        "manifest": _json_safe(manifest),
    }
