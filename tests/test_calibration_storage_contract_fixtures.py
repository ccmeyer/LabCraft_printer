from __future__ import annotations

import json

from tools.sil.calibration_storage_contract import (
    CATALOG_PATH,
    canonical_json_bytes,
    load_catalog,
    semantic_sha256,
)


def test_storage_contract_catalog_freezes_required_fixture_and_process_counts():
    catalog, cases = load_catalog()

    assert catalog["fixture_id"] == "calibration_storage_contract_v1"
    assert [row["fixture_id"] for row in catalog["fixtures"]] == [
        "droplet_sequence_nominal_v1",
        "online_stream_large_multi_update_v1",
        "multi_head_isolation_v1",
        "non_calibration_terminal_v1",
        "stopped_and_error_v1",
        "capture_policy_v1",
        "legacy_parity_v1",
    ]
    assert len(cases) == 16
    assert sum(case.terminal_outcome == "completed" for case in cases) == 14
    assert sum(case.terminal_outcome == "stopped" for case in cases) == 1
    assert sum(case.terminal_outcome == "error" for case in cases) == 1
    assert sum(len(case.updates) for case in cases) == 17
    assert sum(len(case.expected_summary_rows) for case in cases) == 7
    assert all(isinstance(case.expected_summary_rows, tuple) for case in cases)
    large = next(
        case for case in cases if case.fixture_id == "online_stream_large_multi_update_v1"
    )
    assert len(large.updates) == 5
    assert 340 * 1024 <= sum(len(canonical_json_bytes(row)) for row in large.updates) <= 360 * 1024


def test_storage_contract_catalog_contains_no_source_paths_or_raw_images():
    catalog, cases = load_catalog()
    raw = CATALOG_PATH.read_text(encoding="utf-8")
    assert "FreeRTOS-interface/Experiments" not in raw
    assert "C:\\" not in raw
    assert all("image" not in json.dumps(case.updates).lower() for case in cases)
    assert len(catalog["catalog_semantic_sha256"]) == 64


def test_storage_contract_update_hashes_are_stable_canonical_oracles():
    _catalog, cases = load_catalog()
    for case in cases:
        observed = tuple(
            semantic_sha256({"phase": case.phase_name, "data": update})
            for update in case.updates
        )
        assert observed == case.expected_update_hashes


def test_capture_policy_fixture_freezes_current_scaffold_counts():
    _catalog, cases = load_catalog()
    capture_cases = {
        case.capture_mode: case
        for case in cases
        if case.fixture_id == "capture_policy_v1" and case.record_mode_enabled
    }
    assert set(capture_cases) == {
        "structured_only_proxy",
        "key_evidence_proxy",
        "full_proxy",
    }
    assert len(capture_cases["structured_only_proxy"].captures) == 4
    assert sum(row["key_evidence"] for row in capture_cases["key_evidence_proxy"].captures) == 2
