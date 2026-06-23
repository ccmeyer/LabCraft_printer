import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from ResetDebugBundle import ResetDebugBundleError, export_reset_debug_bundle


def _write_json(path: Path, payload: dict):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_export_reset_debug_bundle_writes_zip_with_manifest_and_snapshots(tmp_path):
    downloads = tmp_path / "Downloads"
    logs = tmp_path / "logs"
    logs.mkdir()
    board_log = logs / "board_reset_reports.jsonl"
    board_log.write_text('{"report": {"summary": "Board restarted."}}\n', encoding="utf-8")
    serial_snapshot = _write_json(
        logs / "serial_reader_stopped.json",
        {"schema_version": "host_black_box_v1", "reason": "serial_reader_stopped"},
    )
    reset_snapshot = _write_json(
        logs / "reset_report.json",
        {"schema_version": "host_black_box_v1", "reason": "reset_report"},
    )
    created_at = datetime(2026, 6, 23, 12, 34, 56, tzinfo=timezone.utc)
    context = {
        "repo_root": str(tmp_path),
        "reset_report": {
            "summary": "Board restarted after watchdog reset.",
            "reset_cause": 4,
            "reset_cause_name": "iwdg",
            "seq32": 77,
            "pending": True,
            "sticky": True,
        },
        "reset_report_log_path": str(board_log),
        "black_box_session_id": "session-abc",
        "port": "COM9",
        "profile": "labcraft_v2",
        "black_box_snapshots": [
            {
                "path": str(serial_snapshot),
                "reason": "serial_reader_stopped",
                "session_id": "session-abc",
                "host_time_utc": "2026-06-23T12:30:00Z",
            },
            {
                "path": str(reset_snapshot),
                "reason": "reset_report",
                "session_id": "session-abc",
                "host_time_utc": "2026-06-23T12:31:00Z",
            },
        ],
    }

    result = export_reset_debug_bundle(context, output_dir=downloads, created_at=created_at)

    archive = Path(result["archive_path"])
    assert archive.parent == downloads
    assert archive.name == "LabCraft_reset_debug_bundle_20260623_123456_iwdg_77.zip"
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        top = archive.stem
        assert f"{top}/manifest.json" in names
        assert f"{top}/reset_report/current_reset_report.json" in names
        assert f"{top}/reset_report/board_reset_reports.jsonl" in names
        assert f"{top}/black_box/serial_reader_stopped/serial_reader_stopped.json" in names
        assert f"{top}/black_box/reset_report/reset_report.json" in names
        manifest = json.loads(zf.read(f"{top}/manifest.json").decode("utf-8"))

    assert manifest["schema_version"] == "reset_debug_bundle_v1"
    assert manifest["bundle_kind"] == "reset_report"
    assert manifest["session_id"] == "session-abc"
    assert manifest["machine"] == {"port": "COM9", "profile": "labcraft_v2"}
    assert manifest["reset"]["reset_cause_name"] == "iwdg"
    assert manifest["reset"]["seq32"] == 77
    reasons = {entry["reason"] for entry in manifest["black_box_snapshots"]}
    assert reasons == {"serial_reader_stopped", "reset_report"}
    assert all(entry["included"] for entry in manifest["black_box_snapshots"])
    assert manifest["missing_files"] == []

    second = export_reset_debug_bundle(context, output_dir=downloads, created_at=created_at)
    assert Path(second["archive_path"]).name == "LabCraft_reset_debug_bundle_20260623_123456_iwdg_77_2.zip"


def test_export_reset_debug_bundle_records_missing_optional_files(tmp_path):
    context = {
        "repo_root": str(tmp_path),
        "reset_report": {
            "summary": "Board restarted after power/brownout reset.",
            "reset_cause_name": "power",
            "seq32": 5,
        },
        "reset_report_log_path": str(tmp_path / "missing.jsonl"),
        "black_box_snapshots": [
            {
                "path": str(tmp_path / "missing_snapshot.json"),
                "reason": "serial_reader_stopped",
            }
        ],
    }

    result = export_reset_debug_bundle(context, output_dir=tmp_path)

    with zipfile.ZipFile(result["archive_path"]) as zf:
        top = Path(result["archive_path"]).stem
        manifest = json.loads(zf.read(f"{top}/manifest.json").decode("utf-8"))
        names = set(zf.namelist())

    assert f"{top}/reset_report/current_reset_report.json" in names
    assert not any(name.endswith("board_reset_reports.jsonl") for name in names)
    missing = {(entry["kind"], entry.get("reason")) for entry in manifest["missing_files"]}
    assert ("board_reset_reports_jsonl", None) in missing
    assert ("black_box_snapshot", "serial_reader_stopped") in missing
    assert manifest["black_box_snapshots"][0]["included"] is False


def test_export_connection_loss_debug_bundle_without_reset_report(tmp_path):
    downloads = tmp_path / "Downloads"
    logs = tmp_path / "logs"
    logs.mkdir()
    serial_snapshot = _write_json(
        logs / "serial_reader_stopped.json",
        {"schema_version": "host_black_box_v1", "reason": "serial_reader_stopped"},
    )
    created_at = datetime(2026, 6, 23, 12, 34, 56, tzinfo=timezone.utc)
    context = {
        "bundle_kind": "connection_loss",
        "repo_root": str(tmp_path),
        "connection_loss_report": {
            "summary": "Machine serial connection ended unexpectedly (serial closed).",
            "reason": "serial_closed",
            "port": "COM9",
            "black_box_log_path": str(serial_snapshot),
        },
        "black_box_session_id": "session-abc",
        "profile": "labcraft_v2",
        "black_box_snapshots": [
            {
                "path": str(serial_snapshot),
                "reason": "serial_reader_stopped",
                "session_id": "session-abc",
            }
        ],
    }

    result = export_reset_debug_bundle(context, output_dir=downloads, created_at=created_at)

    archive = Path(result["archive_path"])
    assert archive.parent == downloads
    assert archive.name == "LabCraft_connection_lost_debug_bundle_20260623_123456_serial_closed_session-abc.zip"
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        top = archive.stem
        assert f"{top}/manifest.json" in names
        assert f"{top}/connection_loss/current_connection_loss_report.json" in names
        assert f"{top}/black_box/serial_reader_stopped/serial_reader_stopped.json" in names
        assert not any("/reset_report/current_reset_report.json" in name for name in names)
        manifest = json.loads(zf.read(f"{top}/manifest.json").decode("utf-8"))

    assert manifest["bundle_kind"] == "connection_loss"
    assert manifest["connection_loss"]["reason"] == "serial_closed"
    assert manifest["session_id"] == "session-abc"
    assert manifest["machine"] == {"port": "COM9", "profile": "labcraft_v2"}
    assert manifest["black_box_snapshots"][0]["reason"] == "serial_reader_stopped"
    assert manifest["black_box_snapshots"][0]["included"] is True
    assert manifest["missing_files"] == []


def test_export_connection_loss_debug_bundle_records_missing_snapshot(tmp_path):
    context = {
        "bundle_kind": "connection_loss",
        "repo_root": str(tmp_path),
        "connection_loss_report": {
            "summary": "Machine serial connection ended unexpectedly.",
            "reason": "exception",
            "black_box_log_error": "disk unavailable",
        },
        "black_box_snapshots": [
            {
                "path": str(tmp_path / "missing_snapshot.json"),
                "reason": "serial_reader_stopped",
                "error": "disk unavailable",
            }
        ],
    }

    result = export_reset_debug_bundle(context, output_dir=tmp_path)

    with zipfile.ZipFile(result["archive_path"]) as zf:
        top = Path(result["archive_path"]).stem
        manifest = json.loads(zf.read(f"{top}/manifest.json").decode("utf-8"))
        names = set(zf.namelist())

    assert f"{top}/connection_loss/current_connection_loss_report.json" in names
    missing = {(entry["kind"], entry.get("reason")) for entry in manifest["missing_files"]}
    assert ("black_box_snapshot", "serial_reader_stopped") in missing
    assert manifest["black_box_snapshots"][0]["included"] is False


def test_export_connection_loss_debug_bundle_labels_mcu_unresponsive_snapshot(tmp_path):
    downloads = tmp_path / "Downloads"
    snapshot = _write_json(
        tmp_path / "mcu_unresponsive.json",
        {"schema_version": "host_black_box_v1", "reason": "mcu_unresponsive"},
    )
    created_at = datetime(2026, 6, 23, 12, 34, 56, tzinfo=timezone.utc)
    context = {
        "bundle_kind": "connection_loss",
        "repo_root": str(tmp_path),
        "connection_loss_report": {
            "summary": "MCU stopped responding; no valid frames received for 2500 ms.",
            "reason": "mcu_unresponsive",
            "port": "COM9",
            "black_box_log_path": str(snapshot),
        },
        "black_box_session_id": "session-abc",
        "black_box_snapshots": [
            {
                "path": str(snapshot),
                "reason": "mcu_unresponsive",
                "session_id": "session-abc",
            }
        ],
    }

    result = export_reset_debug_bundle(context, output_dir=downloads, created_at=created_at)

    archive = Path(result["archive_path"])
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        top = archive.stem
        assert f"{top}/black_box/mcu_unresponsive/mcu_unresponsive.json" in names
        manifest = json.loads(zf.read(f"{top}/manifest.json").decode("utf-8"))

    assert manifest["connection_loss"]["reason"] == "mcu_unresponsive"
    assert manifest["black_box_snapshots"][0]["reason"] == "mcu_unresponsive"
    assert manifest["black_box_snapshots"][0]["included"] is True


def test_export_reset_debug_bundle_requires_reset_report(tmp_path):
    try:
        export_reset_debug_bundle({}, output_dir=tmp_path)
    except ResetDebugBundleError as exc:
        assert "No reset report" in str(exc)
    else:
        raise AssertionError("expected ResetDebugBundleError")
