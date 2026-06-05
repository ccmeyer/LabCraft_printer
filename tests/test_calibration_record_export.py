import csv
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from CalibrationRecordExport import (
    CalibrationRecordExportError,
    export_calibration_records,
)


def _write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _make_run(
    experiment_dir: Path,
    process_name: str = "DropletSearchCalibrationProcess",
    run_id: str = "run_20260604_120000_abcdef12",
) -> Path:
    run_dir = experiment_dir / "calibration_recordings" / process_name / run_id
    run_dir.mkdir(parents=True)
    _write_json(
        run_dir / "run_meta.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "process_name": process_name,
            "phase_name": "droplet_characterization",
            "started_at_utc": "2026-06-04T12:00:00Z",
            "ended_at_utc": "2026-06-04T12:01:00Z",
            "outcome": "completed",
            "error_message": "",
        },
    )
    _write_json(
        run_dir / "verdict.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "process_name": process_name,
            "phase_name": "droplet_characterization",
            "outcome": "success",
            "notes": "usable",
            "submitted_by": "unit-test",
        },
    )
    (run_dir / "events.jsonl").write_text(
        json.dumps(
            {
                "event_type": "process_started",
                "level": "info",
                "payload": {"value": 1},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "analysis.jsonl").write_text(
        json.dumps({"kind": "analysis", "status": "ok"}) + "\n",
        encoding="utf-8",
    )
    captures = run_dir / "captures"
    captures.mkdir()
    (captures / "frame_0001.png").write_bytes(b"fake-image")
    return run_dir


def _make_experiment(tmp_path: Path, name: str = "Test Experiment") -> Path:
    experiment_dir = tmp_path / name
    experiment_dir.mkdir()
    _make_run(experiment_dir)
    _write_json(experiment_dir / "calibration.json", {"runs": []})
    _write_json(experiment_dir / "experiment_design.json", {"name": name})
    _write_json(experiment_dir / "progress.json", {"printed": []})
    (experiment_dir / "experiment_audit.jsonl").write_text(
        json.dumps({"event": "created"}) + "\n",
        encoding="utf-8",
    )
    return experiment_dir


def test_export_calibration_records_writes_zip_with_summary_and_manifest(tmp_path):
    experiment_dir = _make_experiment(tmp_path)
    output_dir = tmp_path / "Downloads"

    result = export_calibration_records(
        experiment_dir,
        output_dir,
        created_at=datetime(2026, 6, 4, 12, 30, 0, tzinfo=timezone.utc),
    )

    archive = Path(result["archive_path"])
    assert archive == output_dir / "LabCraft_calibration_records_Test_Experiment_20260604_123000.zip"
    assert archive.exists()
    assert result["archive_size_bytes"] > 0
    assert result["summary"]["row_count"] == 1

    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        assert "calibration_recordings/DropletSearchCalibrationProcess/run_20260604_120000_abcdef12/run_meta.json" in names
        assert "calibration_recordings/DropletSearchCalibrationProcess/run_20260604_120000_abcdef12/captures/frame_0001.png" in names
        assert "calibration.json" in names
        assert "experiment_design.json" in names
        assert "progress.json" in names
        assert "experiment_audit.jsonl" in names
        assert "calibration_recordings_summary.csv" in names
        assert "manifest.json" in names

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["schema_version"] == 1
        assert manifest["experiment_name"] == "Test Experiment"
        assert manifest["archive_name"] == archive.name
        assert manifest["summary"]["row_count"] == 1
        assert "calibration_recordings" in manifest["included_top_level_items"]

        summary_rows = list(
            csv.DictReader(
                zf.read("calibration_recordings_summary.csv").decode("utf-8").splitlines()
            )
        )
        assert len(summary_rows) == 1
        assert summary_rows[0]["run_id"] == "run_20260604_120000_abcdef12"


def test_export_calibration_records_archive_paths_are_relative(tmp_path):
    experiment_dir = _make_experiment(tmp_path)
    result = export_calibration_records(experiment_dir, tmp_path / "Downloads")

    with zipfile.ZipFile(result["archive_path"]) as zf:
        for name in zf.namelist():
            assert not Path(name).is_absolute()
            assert ".." not in Path(name).parts
            assert str(experiment_dir) not in name


def test_export_calibration_records_missing_recordings_root_raises(tmp_path):
    experiment_dir = tmp_path / "NoRecordings"
    experiment_dir.mkdir()

    with pytest.raises(CalibrationRecordExportError, match="calibration_recordings not found"):
        export_calibration_records(experiment_dir, tmp_path / "Downloads")


def test_export_calibration_records_empty_recordings_root_raises(tmp_path):
    experiment_dir = tmp_path / "EmptyRecordings"
    (experiment_dir / "calibration_recordings").mkdir(parents=True)

    with pytest.raises(CalibrationRecordExportError, match="No calibration recording runs found"):
        export_calibration_records(experiment_dir, tmp_path / "Downloads")


def test_export_calibration_records_uses_unique_filename(tmp_path):
    experiment_dir = _make_experiment(tmp_path)
    output_dir = tmp_path / "Downloads"
    output_dir.mkdir()
    existing = output_dir / "LabCraft_calibration_records_Test_Experiment_20260604_123000.zip"
    existing.write_bytes(b"existing")

    result = export_calibration_records(
        experiment_dir,
        output_dir,
        created_at=datetime(2026, 6, 4, 12, 30, 0, tzinfo=timezone.utc),
    )

    assert Path(result["archive_path"]).name == "LabCraft_calibration_records_Test_Experiment_20260604_123000_2.zip"
    assert existing.read_bytes() == b"existing"


def test_export_calibration_records_skips_missing_optional_files(tmp_path):
    experiment_dir = tmp_path / "Minimal"
    experiment_dir.mkdir()
    _make_run(experiment_dir)

    result = export_calibration_records(experiment_dir, tmp_path / "Downloads")

    with zipfile.ZipFile(result["archive_path"]) as zf:
        names = set(zf.namelist())
        assert "calibration_recordings_summary.csv" in names
        assert "manifest.json" in names
        assert "calibration.json" not in names
        assert "experiment_design.json" not in names
        assert "progress.json" not in names
        assert "experiment_audit.jsonl" not in names


def test_droplet_dialog_export_handler_uses_current_experiment_and_downloads(monkeypatch, tmp_path):
    import CalibrationClasses.View as calibration_view

    experiment_dir = _make_experiment(tmp_path)
    downloads_dir = tmp_path / "Downloads"
    dialog = calibration_view.DropletImagingDialog.__new__(calibration_view.DropletImagingDialog)
    dialog.model = SimpleNamespace(
        experiment_model=SimpleNamespace(experiment_dir_path=str(experiment_dir)),
        calibration_manager=SimpleNamespace(calibration_file_path=""),
    )
    dialog.controller = object()
    dialog._capture_request_pending = False
    dialog._resolve_downloads_dir = lambda: downloads_dir
    dialog.update_stage_and_log = lambda *args, **kwargs: None

    calls = []

    def fake_export(exp_arg, out_arg):
        calls.append((Path(exp_arg), Path(out_arg)))
        return {
            "archive_path": str(downloads_dir / "records.zip"),
            "archive_size_bytes": 2048,
        }

    info_messages = []
    warning_messages = []
    monkeypatch.setattr(calibration_view, "export_calibration_records", fake_export)
    monkeypatch.setattr(
        calibration_view.DropletImagingDialog,
        "_is_calibration_busy",
        lambda self: False,
    )
    monkeypatch.setattr(
        calibration_view.QtWidgets.QMessageBox,
        "information",
        lambda *args, **kwargs: info_messages.append(args),
    )
    monkeypatch.setattr(
        calibration_view.QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: warning_messages.append(args),
    )

    calibration_view.DropletImagingDialog.export_calibration_records_to_downloads(dialog)

    assert calls == [(experiment_dir, downloads_dir)]
    assert info_messages
    assert not warning_messages


def test_droplet_dialog_export_handler_blocks_while_busy(monkeypatch, tmp_path):
    import CalibrationClasses.View as calibration_view

    experiment_dir = _make_experiment(tmp_path)
    dialog = calibration_view.DropletImagingDialog.__new__(calibration_view.DropletImagingDialog)
    dialog.model = SimpleNamespace(
        experiment_model=SimpleNamespace(experiment_dir_path=str(experiment_dir)),
        calibration_manager=SimpleNamespace(calibration_file_path=""),
    )
    dialog._capture_request_pending = False

    monkeypatch.setattr(
        calibration_view.DropletImagingDialog,
        "_is_calibration_busy",
        lambda self: True,
    )
    monkeypatch.setattr(
        calibration_view,
        "export_calibration_records",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("export should not run")),
    )
    warning_messages = []
    monkeypatch.setattr(
        calibration_view.QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: warning_messages.append(args),
    )

    calibration_view.DropletImagingDialog.export_calibration_records_to_downloads(dialog)

    assert warning_messages
