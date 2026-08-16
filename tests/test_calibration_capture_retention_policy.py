from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from CalibrationClasses.Model import CalibrationManager, CalibrationProcessRecorder
from CalibrationRecordingStore import CaptureRetentionPolicy
from tests.calibration_test_utils import SignalStub


def _model(tmp_path):
    return SimpleNamespace(
        experiment_model=SimpleNamespace(
            experiment_dir_path=str(tmp_path),
            calibration_file_path=str(tmp_path / "calibration.json"),
        )
    )


@pytest.mark.parametrize(
    ("policy", "expected_saved", "expected_omitted"),
    [
        ("structured_only", 0, 4),
        ("key_evidence", 2, 2),
        ("full", 4, 0),
    ],
)
def test_capture_retention_records_every_request_and_writes_only_selected_pixels(
    tmp_path, policy, expected_saved, expected_omitted
):
    recorder = CalibrationProcessRecorder(_model(tmp_path))
    run_dir = Path(
        recorder.start_run(
            "PolicyProcess",
            "policy_phase",
            capture_policy=policy,
        )
    )
    refs = []
    for index in range(4):
        refs.append(
            recorder.save_capture_image(
                np.full((12, 16), index, dtype=np.uint8),
                role=f"frame_{index}",
                retention_class="key" if index in {0, 3} else "routine",
            )
        )
    summary = recorder.finalize_run("completed")

    assert len({ref["capture_id"] for ref in refs}) == 4
    assert sum(ref["retention_outcome"] == "omitted" for ref in refs) == expected_omitted
    assert len(list((run_dir / "captures").glob("*"))) == expected_saved
    assert summary["capture_requested_count"] == 4
    assert summary["capture_saved_count"] == expected_saved
    assert summary["capture_omitted_count"] == expected_omitted
    meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["capture_requested_count"] == 4
    assert meta["capture_saved_count"] == expected_saved
    assert meta["capture_omitted_count"] == expected_omitted
    capture_events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {row["payload"]["capture_id"] for row in capture_events} == {
        ref["capture_id"] for ref in refs
    }
    assert all(row["payload"]["width"] == 16 for row in capture_events)
    assert all(row["payload"]["height"] == 12 for row in capture_events)
    assert all(row["payload"]["requested_policy"] == policy for row in capture_events)
    assert all(row["payload"]["effective_policy"] == policy for row in capture_events)
    assert {
        row["payload"]["retention_outcome"] for row in capture_events
    } <= {"saved", "omitted", "failed"}


def test_full_minimum_policy_is_never_silently_elevated(tmp_path):
    recorder = CalibrationProcessRecorder(_model(tmp_path))
    with pytest.raises(ValueError, match="full capture retention is required"):
        recorder.start_run(
            "DatasetProcess",
            "dataset",
            capture_policy="key_evidence",
            minimum_capture_policy="full",
        )
    assert recorder.get_active_run_dir() is None


def test_policy_order_and_compatibility_names_are_stable():
    assert CaptureRetentionPolicy.STRUCTURED_ONLY < CaptureRetentionPolicy.KEY_EVIDENCE
    assert CaptureRetentionPolicy.KEY_EVIDENCE < CaptureRetentionPolicy.FULL
    assert CaptureRetentionPolicy.parse("key_evidence") is CaptureRetentionPolicy.KEY_EVIDENCE


def test_manager_policy_is_session_scoped_busy_guarded_and_compatibility_safe():
    manager = CalibrationManager.__new__(CalibrationManager)
    manager._canonical_store_authoritative = True
    manager._capture_retention_policy = CaptureRetentionPolicy.KEY_EVIDENCE
    manager.activeCalibration = None
    manager.calibration_queue = []
    manager.has_open_stream_gravimetric_capture = lambda: False
    manager.calibrationStageChanged = SignalStub()

    assert manager.get_capture_retention_policy() == "key_evidence"
    assert manager.set_capture_retention_policy("structured_only") is True
    assert manager.get_record_mode_enabled() is False
    assert manager.set_record_mode_enabled(True) is True
    assert manager.get_capture_retention_policy() == "full"
    manager.activeCalibration = object()
    assert manager.set_capture_retention_policy("key_evidence") is False
    assert manager.get_capture_retention_policy() == "full"


def test_obsolete_authority_rollback_does_not_disable_structured_persistence(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LABCRAFT_CALIBRATION_STORE_AUTHORITATIVE", "0")
    model = _model(tmp_path)
    model.machine_state_updated = SignalStub()
    manager = CalibrationManager(model)

    assert manager.is_calibration_store_authoritative() is True
    assert manager.get_calibration_storage_start_block_message()
    manager.set_record_mode_enabled(False)
    assert manager.get_record_mode_enabled() is False
    assert manager.get_shadow_store_enabled() is True
