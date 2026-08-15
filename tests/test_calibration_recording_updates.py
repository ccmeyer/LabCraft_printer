from __future__ import annotations

import json

import pytest

from tools.calibration_recording_updates import (
    CalibrationUpdateConflictError,
    load_calibration_updates,
)


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _canonical(payload):
    import hashlib

    digest = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    return {
        "update_id": "update-1",
        "update_index": 1,
        "payload_sha256": digest,
        "payload": payload,
    }


def test_update_loader_prefers_matching_canonical_projection(tmp_path):
    payload = {"phase": "droplet_emergence", "result": {"delay_us": 400}}
    _write_jsonl(tmp_path / "updates.jsonl", [_canonical(payload)])
    _write_jsonl(
        tmp_path / "analysis.jsonl",
        [{"kind": "calibration_data_updated", "payload": payload}],
    )

    loaded = load_calibration_updates(tmp_path)

    assert loaded.source == "canonical"
    assert loaded.reader_state == "matching_dual"
    assert loaded.rows[0]["update_id"] == "update-1"


def test_update_loader_retains_legacy_fallback_and_blocks_conflict(tmp_path):
    payload = {"result": {"pressure": 1.2}}
    _write_jsonl(
        tmp_path / "analysis.jsonl",
        [{"kind": "calibration_data_updated", "payload": payload}],
    )
    assert load_calibration_updates(tmp_path).reader_state == "legacy_only"

    _write_jsonl(tmp_path / "updates.jsonl", [_canonical({"result": {"pressure": 2.0}})])
    with pytest.raises(CalibrationUpdateConflictError, match="conflict"):
        load_calibration_updates(tmp_path)
