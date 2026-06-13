from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPORT_SCHEMA_VERSION = "plate_reader_analysis_export_v1"
MANIFEST_SCHEMA_VERSION = "plate_reader_analysis_manifest_v1"


@dataclass(frozen=True)
class PlateReaderAnalysisExportConfig:
    analysis_payload: dict[str, Any]
    destination: str | Path
    created_by: str | None = None


def export_plate_reader_analysis_package(config: PlateReaderAnalysisExportConfig | dict[str, Any]) -> dict[str, Any]:
    """Create a portable ZIP package for a completed plate-reader analysis run."""
    if isinstance(config, PlateReaderAnalysisExportConfig):
        payload = dict(config.analysis_payload or {})
        destination = Path(config.destination).expanduser()
        created_by = config.created_by
    else:
        raw = dict(config)
        payload = dict(raw.get("analysis_payload") or {})
        destination = Path(raw.get("destination", "")).expanduser()
        created_by = raw.get("created_by")

    if not destination.name:
        raise ValueError("Export destination must be a ZIP file path.")
    if destination.suffix.lower() != ".zip":
        destination = destination.with_suffix(".zip")

    output_dir = Path(str(payload.get("output_dir") or "")).expanduser()
    if not output_dir.exists() or not output_dir.is_dir():
        raise ValueError(f"Analysis output directory does not exist: {output_dir}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(payload.get("manifest_json"))
    included_files: list[str] = []
    missing_files: list[str] = []
    source_payload = _source_payload(payload)
    used_members: set[str] = set()
    destination_resolved = _resolve_for_compare(destination)

    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        _write_directory(
            archive,
            output_dir,
            "analysis",
            included_files,
            missing_files,
            used_members,
            skip_path=destination_resolved,
        )
        for payload_key in ("copied_plate_reader_file", "key_file", "merged_csv"):
            _write_payload_file(
                archive,
                payload,
                payload_key,
                included_files,
                missing_files,
                used_members,
                skip_path=destination_resolved,
            )

        provenance = {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "created_by": str(created_by or ""),
            "source_payload": source_payload,
            "analysis_manifest_schema_version": manifest.get("schema_version", ""),
            "analysis_manifest_created_at": manifest.get("created_at", ""),
            "included_files": list(included_files) + ["plate_reader_export_provenance.json"],
            "missing_files": list(missing_files),
            "command_returncodes": dict(payload.get("command_returncodes") or {}),
        }
        archive.writestr(
            "plate_reader_export_provenance.json",
            json.dumps(provenance, indent=2, sort_keys=True),
        )

    return {
        "ok": True,
        "destination": str(destination),
        "included_files": list(included_files) + ["plate_reader_export_provenance.json"],
        "missing_files": list(missing_files),
        "provenance": provenance,
    }


def _source_payload(payload: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "experiment_dir",
        "plate_reader_file",
        "copied_plate_reader_file",
        "key_file",
        "merged_csv",
        "output_dir",
        "manifest_json",
        "report_html",
    )
    return {key: payload.get(key, "") for key in keys}


def _load_manifest(path_value: object) -> dict[str, Any]:
    if not path_value:
        return {}
    path = Path(str(path_value)).expanduser()
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_directory(
    archive: zipfile.ZipFile,
    source_dir: Path,
    target_root: str,
    included_files: list[str],
    missing_files: list[str],
    used_members: set[str],
    *,
    skip_path: Path | None = None,
) -> None:
    if not source_dir.exists() or not source_dir.is_dir():
        missing_files.append(str(source_dir))
        return
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        if skip_path is not None and _resolve_for_compare(path) == skip_path:
            continue
        member = Path(target_root) / path.relative_to(source_dir)
        _write_file(archive, path, _zip_name(member), included_files, missing_files, used_members)


def _write_payload_file(
    archive: zipfile.ZipFile,
    payload: dict[str, Any],
    payload_key: str,
    included_files: list[str],
    missing_files: list[str],
    used_members: set[str],
    *,
    skip_path: Path | None = None,
) -> None:
    path_value = payload.get(payload_key)
    if not path_value:
        missing_files.append(payload_key)
        return
    source = Path(str(path_value)).expanduser()
    if not source.exists() or not source.is_file():
        missing_files.append(str(source))
        return
    if skip_path is not None and _resolve_for_compare(source) == skip_path:
        return
    member = _unique_member_name(f"inputs/{source.name}", used_members)
    _write_file(archive, source, member, included_files, missing_files, used_members)


def _write_file(
    archive: zipfile.ZipFile,
    source: Path,
    member: str,
    included_files: list[str],
    missing_files: list[str],
    used_members: set[str],
) -> None:
    try:
        archive.write(source, member)
    except FileNotFoundError:
        missing_files.append(str(source))
        return
    used_members.add(member)
    included_files.append(member)


def _unique_member_name(member: str, used_members: set[str]) -> str:
    if member not in used_members:
        return member
    path = Path(member)
    for suffix in range(2, 1000):
        candidate = _zip_name(path.with_name(f"{path.stem}_{suffix}{path.suffix}"))
        if candidate not in used_members:
            return candidate
    raise RuntimeError(f"Could not choose a unique export member path for {member}")


def _zip_name(path: Path | str) -> str:
    return Path(path).as_posix()


def _resolve_for_compare(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()
