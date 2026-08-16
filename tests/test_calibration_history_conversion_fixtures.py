from __future__ import annotations

import json

import pytest

from CalibrationHistoricalConversion import CalibrationHistoricalConverter, file_sha256
from tools.sil.calibration_history_conversion_fixture import (
    load_fixture,
    materialize_fixture,
)
from tools.sil.calibration_history_conversion_sanitizer import build_fixture
from tools.sil.calibration_storage_sanitizer import write_new_fixture


def test_tracked_fixture_materializes_exact_conversion_contract(tmp_path):
    fixture = load_fixture()
    evidence = materialize_fixture(tmp_path / "experiment", fixture)
    plan = CalibrationHistoricalConverter(evidence["experiment_dir"]).plan()
    expected = dict(fixture["expected_counts"])
    expected.pop("generated_count")
    assert plan.counts == expected
    report = CalibrationHistoricalConverter(evidence["experiment_dir"]).apply()
    assert report["generated_count"] == fixture["expected_counts"]["generated_count"]
    assert report["source_unchanged"] is True


def test_historical_fixture_sanitizer_is_deterministic_and_read_only(tmp_path):
    source_dir = tmp_path / "private-experiment"
    source_dir.mkdir()
    source = source_dir / "calibration.json"
    source.write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "run_id": "private-run-id",
                        "outcome": "completed",
                        "operator": "private operator",
                        "steps": {
                            "pressure_sweep_characterization": [
                                {
                                    "timestamp": "2025-01-01T00:00:00Z",
                                    "result": {
                                        "operator": "private operator",
                                        "path": "C:\\private\\image.jpg",
                                        "pressures": [
                                            {"pressure": 1.2, "mean_volume": 10.0, "valid": True}
                                        ],
                                    },
                                }
                            ]
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    before = file_sha256(source)
    first = build_fixture(
        source,
        fixture_id="reviewed-history-v1",
        selectors=("0:pressure_sweep_characterization:0",),
    )
    second = build_fixture(
        source,
        fixture_id="reviewed-history-v1",
        selectors=("0:pressure_sweep_characterization:0",),
    )
    assert first == second
    assert file_sha256(source) == before
    encoded = json.dumps(first)
    assert "private operator" not in encoded
    assert "C:\\\\private" not in encoded

    output = tmp_path / "reviewed.json"
    write_new_fixture(output, first)
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_new_fixture(output, first)
