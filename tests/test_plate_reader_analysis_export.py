from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from PlateReaderAnalysisExport import (
    EXPORT_SCHEMA_VERSION,
    PlateReaderAnalysisExportConfig,
    export_plate_reader_analysis_package,
)


def _make_export_sources(tmp_path: Path):
    experiment_dir = tmp_path / "experiment"
    experiment_dir.mkdir()
    raw_file = experiment_dir / "raw_plate_reader" / "reader.txt"
    raw_file.parent.mkdir()
    raw_file.write_text("raw export\n", encoding="utf-8")
    key_file = experiment_dir / "concentration_key.csv"
    key_file.write_text("Well ID,DNA_mM\nA1,1\n", encoding="utf-8")
    merged_csv = experiment_dir / "reader_merged_tidy.csv"
    merged_csv.write_text("well,rfu\nA1,100\n", encoding="utf-8")
    output_dir = experiment_dir / "plate_reader_analysis"
    output_dir.mkdir()
    report = output_dir / "analysis_report.html"
    report.write_text("<html></html>", encoding="utf-8")
    manifest = output_dir / "analysis_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "plate_reader_analysis_manifest_v1",
                "created_at": "2026-06-13T12:00:00",
            }
        ),
        encoding="utf-8",
    )
    nested_plot = output_dir / "heatmaps_absolute_rfu" / "488_509_endpoint_rfu.png"
    nested_plot.parent.mkdir()
    nested_plot.write_bytes(b"png")
    payload = {
        "experiment_dir": str(experiment_dir),
        "plate_reader_file": str(tmp_path / "original_reader.txt"),
        "copied_plate_reader_file": str(raw_file),
        "key_file": str(key_file),
        "merged_csv": str(merged_csv),
        "output_dir": str(output_dir),
        "manifest_json": str(manifest),
        "report_html": str(report),
        "command_returncodes": {"associate": 0, "analyze": 0},
    }
    return payload, output_dir, raw_file


def test_export_plate_reader_analysis_package_writes_zip_and_provenance(tmp_path):
    payload, _output_dir, _raw_file = _make_export_sources(tmp_path)
    destination = tmp_path / "export.zip"

    result = export_plate_reader_analysis_package(
        PlateReaderAnalysisExportConfig(payload, destination, created_by="tests")
    )

    assert result["ok"] is True
    assert Path(result["destination"]) == destination
    assert result["missing_files"] == []
    with zipfile.ZipFile(destination) as archive:
        names = set(archive.namelist())
        assert "analysis/analysis_report.html" in names
        assert "analysis/analysis_manifest.json" in names
        assert "analysis/heatmaps_absolute_rfu/488_509_endpoint_rfu.png" in names
        assert "inputs/reader.txt" in names
        assert "inputs/concentration_key.csv" in names
        assert "inputs/reader_merged_tidy.csv" in names
        assert "plate_reader_export_provenance.json" in names
        provenance = json.loads(archive.read("plate_reader_export_provenance.json").decode("utf-8"))

    assert provenance["schema_version"] == EXPORT_SCHEMA_VERSION
    assert provenance["created_by"] == "tests"
    assert provenance["analysis_manifest_schema_version"] == "plate_reader_analysis_manifest_v1"
    assert provenance["analysis_manifest_created_at"] == "2026-06-13T12:00:00"
    assert provenance["command_returncodes"] == {"associate": 0, "analyze": 0}
    assert provenance["source_payload"]["output_dir"] == payload["output_dir"]
    assert "analysis/analysis_report.html" in provenance["included_files"]
    assert "plate_reader_export_provenance.json" in provenance["included_files"]


def test_export_records_missing_optional_inputs_without_failing(tmp_path):
    payload, _output_dir, raw_file = _make_export_sources(tmp_path)
    raw_file.unlink()
    destination = tmp_path / "export.zip"

    result = export_plate_reader_analysis_package(PlateReaderAnalysisExportConfig(payload, destination))

    assert result["ok"] is True
    assert any(str(raw_file) == missing for missing in result["missing_files"])
    with zipfile.ZipFile(destination) as archive:
        provenance = json.loads(archive.read("plate_reader_export_provenance.json").decode("utf-8"))
    assert any(str(raw_file) == missing for missing in provenance["missing_files"])


def test_export_requires_analysis_output_directory(tmp_path):
    payload, output_dir, _raw_file = _make_export_sources(tmp_path)
    for path in sorted(output_dir.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        else:
            path.rmdir()
    output_dir.rmdir()

    with pytest.raises(ValueError, match="Analysis output directory does not exist"):
        export_plate_reader_analysis_package(PlateReaderAnalysisExportConfig(payload, tmp_path / "export.zip"))
