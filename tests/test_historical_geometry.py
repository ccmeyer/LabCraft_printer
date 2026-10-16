import csv
import hashlib
from pathlib import Path

import cv2
import numpy as np
import pytest

from tools import historical_geometry as geometry
from tools import historical_fixtures as fixtures


@pytest.fixture
def captures(tmp_path):
    run = "run_synthetic"
    source = tmp_path / "source"
    directory = source / geometry.EXPERIMENT / "calibration_recordings/DropletTimecourseProcess" / run
    (directory / "captures").mkdir(parents=True)
    rows = []
    for index, top in enumerate((103, 160)):
        image = np.full((480, 640), 255, dtype=np.uint8)
        cv2.rectangle(image, (310, top), (330, 400), 0, -1)
        relative = f"captures/cap_{index}_raw_frame.jpg"
        assert cv2.imwrite(str(directory / relative), image)
        rows.append(dict(capture_id=f"cap_{index}", image_relpath=relative, capture_index=index,
                         flash_delay_us=4800 + 100 * index, delay_from_emergence_us=100 * index,
                         tracked_nozzle_x_px=320, tracked_nozzle_y_px=100, tracked_confidence=1.0))
    feature_relative = f"{geometry.EXPERIMENT}/analysis/stream_characterization/runs/{run}/stage_05_fit/phase_features.csv"
    feature = source / feature_relative
    feature.parent.mkdir(parents=True)
    with feature.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    entries = {feature_relative: hashlib.sha256(feature.read_bytes()).hexdigest()}
    return source, run, rows, entries


def test_geometry_measures_original_pixels_without_expected_tail_labels(captures):
    source, run, rows, _ = captures
    measured = geometry.geometry_rows(source, run, rows)
    assert [r["cutoff_y_px"] for r in measured] == [102, 102]
    assert [r["selected_component_top_y_px"] for r in measured] == [103, 160]
    assert [r["geometry_silhouette_status"] for r in measured] == ["ok", "ok"]
    assert [r["flash_delay_us"] - r["delay_from_emergence_us"] for r in measured] == [4800, 4800]


def test_derivation_is_reproducible_and_pins_sources_and_outputs(captures, tmp_path):
    source, _, _, entries = captures
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    contract = geometry.derive(source, first, entries)
    second.mkdir()
    assert geometry.derive(source, second, entries, expected=contract) == contract
    assert (first / geometry.RECEIPT).read_bytes() == (second / geometry.RECEIPT).read_bytes()
    image = next(source.rglob("*.jpg"))
    image.write_bytes(b"corrupt original capture")
    with pytest.raises(ValueError, match="source/implementation differs"):
        geometry.validate_sources(source, entries, contract)


def test_derivation_detects_output_drift(captures, tmp_path):
    source, _, _, entries = captures
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    contract = geometry.derive(source, first, entries)
    next(iter(contract["runs"].values()))["sha256"] = "0" * 64
    second.mkdir()
    with pytest.raises(ValueError, match="output contract"):
        geometry.derive(source, second, entries, expected=contract)


@pytest.mark.parametrize("corrupt", [False, True])
def test_staging_validates_geometry_before_writing_and_preserves_sources(captures, tmp_path, monkeypatch, corrupt):
    source, _, _, entries = captures
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    contract = geometry.derive(source, candidate, entries)
    monkeypatch.setattr(fixtures, "load_manifest", lambda: {"dense_stream": entries})
    monkeypatch.setattr(fixtures, "external_root", lambda p: p)
    monkeypatch.setattr(geometry, "load_contract", lambda: contract)
    if corrupt:
        next(source.rglob("*.jpg")).write_bytes(b"changed")
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*") if p.is_file()}
    target = tmp_path / "staged"
    if corrupt:
        with pytest.raises(ValueError, match="source/implementation differs"):
            fixtures.stage(source, target)
        assert not target.exists()
    else:
        assert fixtures.stage(source, target) == 3  # Feature CSV, geometry CSV, receipt.
        assert geometry.verify(target) == contract
    assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*") if p.is_file()}


@pytest.mark.parametrize("relative", ["../escape.jpg", "/absolute.jpg", "C:/private.jpg", "a\\b.jpg"])
def test_geometry_source_rejects_path_escape(tmp_path, relative):
    with pytest.raises(ValueError, match="Invalid geometry input path"):
        geometry.contained(tmp_path, relative)


@pytest.mark.parametrize("defect", [None, "columns", "missing", "duplicate", "time", "nan", "missing_coordinate"])
def test_geometry_join_requires_exact_schema_and_capture_times(captures, tmp_path, defect):
    source, run, features, _ = captures
    measured = geometry.geometry_rows(source, run, features)
    measured.reverse()  # Order is not identity.
    fields = list(geometry.COLUMNS)
    if defect == "columns":
        fields.remove("cutoff_y_px")
        for row in measured:
            row.pop("cutoff_y_px")
    elif defect == "missing":
        measured.pop()
    elif defect == "duplicate":
        measured.append(measured[0])
    elif defect == "time":
        measured[0]["flash_delay_us"] += 1
    elif defect == "nan":
        measured[0]["cutoff_y_px"] = "nan"
    elif defect == "missing_coordinate":
        measured[0]["cutoff_y_px"] = ""
    path = tmp_path / "geometry.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(measured)
    if defect:
        with pytest.raises(ValueError):
            geometry.merge_geometry(features, path)
    else:
        joined = geometry.merge_geometry(features, path)
        assert [r["capture_id"] for r in joined] == [r["capture_id"] for r in features]
        assert [r["selected_component_top_y_px"] for r in joined] == ["103", "160"]
