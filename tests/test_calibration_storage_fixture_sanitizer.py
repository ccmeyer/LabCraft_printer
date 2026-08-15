from __future__ import annotations

import json

import pytest

from tools.sil.calibration_storage_contract import file_sha256, validate_fixture
from tools.sil.calibration_storage_sanitizer import (
    build_sanitized_fixture,
    write_new_fixture,
)


def _source_document():
    return {
        "schema_version": 1,
        "runs": [
            {
                "run_id": "private-run",
                "notes": "operator note",
                "steps": {
                    "pressure_sweep_characterization": [
                        {
                            "timestamp": "2026-01-02T03:04:05Z",
                            "settings": {"print_width": 1400},
                            "meta": {
                                "run_id": "private-run",
                                "printer_head_id": "private-head",
                                "stock_id": "private-stock",
                            },
                            "phase": "pressure_sweep_characterization",
                            "result": {
                                "path": "C:\\private\\capture.jpg",
                                "source_run_id": "private-process-run",
                                "operator_email": "operator@example.invalid",
                                "reagent_name": "Private Reagent",
                                "print_pulse_width_us": 1400,
                                "pressures": [
                                    {
                                        "pressure": 1.2,
                                        "mean_volume": 10.0,
                                        "valid": True,
                                    }
                                ],
                            },
                        }
                    ]
                },
            }
        ],
    }


def test_sanitizer_is_deterministic_redacted_and_source_read_only(tmp_path):
    source = tmp_path / "calibration.json"
    source.write_text(json.dumps(_source_document()), encoding="utf-8")
    before = file_sha256(source)

    first = build_sanitized_fixture(
        source,
        fixture_id="sanitized_case_v1",
        run_index=0,
        phase="pressure_sweep_characterization",
        step_indexes=(0,),
        process_id="sanitized-process",
    )
    second = build_sanitized_fixture(
        source,
        fixture_id="sanitized_case_v1",
        run_index=0,
        phase="pressure_sweep_characterization",
        step_indexes=(0,),
        process_id="sanitized-process",
    )

    assert first == second
    validate_fixture(first)
    assert file_sha256(source) == before
    encoded = json.dumps(first)
    for forbidden in (
        "private-run",
        "private-process-run",
        "private-head",
        "private-stock",
        "operator@example.invalid",
        "Private Reagent",
        "operator note",
        "C:\\\\private",
    ):
        assert forbidden not in encoded


def test_sanitizer_refuses_to_replace_reviewed_fixture(tmp_path):
    source = tmp_path / "calibration.json"
    source.write_text(json.dumps(_source_document()), encoding="utf-8")
    fixture = build_sanitized_fixture(
        source,
        fixture_id="sanitized_case_v1",
        run_index=0,
        phase="pressure_sweep_characterization",
        step_indexes=(0,),
        process_id="sanitized-process",
    )
    output = tmp_path / "fixture.json"
    write_new_fixture(output, fixture)
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_new_fixture(output, fixture)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("api_token", "do-not-copy", "sensitive key"),
        ("measurement", float("nan"), "non-finite"),
    ],
)
def test_sanitizer_rejects_unsafe_residual_fields(tmp_path, field, value, message):
    source_document = _source_document()
    source_document["runs"][0]["steps"]["pressure_sweep_characterization"][0][
        "result"
    ][field] = value
    source = tmp_path / "calibration.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")
    before = file_sha256(source)

    with pytest.raises(ValueError, match=message):
        build_sanitized_fixture(
            source,
            fixture_id="sanitized_case_v1",
            run_index=0,
            phase="pressure_sweep_characterization",
            step_indexes=(0,),
            process_id="sanitized-process",
        )
    assert file_sha256(source) == before
