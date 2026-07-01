from __future__ import annotations

import json
from types import SimpleNamespace

from Controller import Controller, DropletCapturePerformanceDiagnostics


def test_droplet_capture_perf_disabled_recording_is_noop():
    diagnostics = DropletCapturePerformanceDiagnostics(max_events=3)

    assert diagnostics.record("ui_trigger_received", {"request_id": "a"}) is None
    assert diagnostics.build_snapshot()["event_count"] == 0


def test_droplet_capture_perf_enabled_events_are_bounded_and_json_safe():
    diagnostics = DropletCapturePerformanceDiagnostics(max_events=2)
    diagnostics.set_enabled(True)

    diagnostics.record("ui_trigger_received", {"request_id": "old"})
    diagnostics.record("ui_request_returned", {"request_id": "new", "accepted": True})
    diagnostics.record("controller_completion_received", {"request_id": "new", "status": "success"})
    snapshot = diagnostics.build_snapshot(reason="unit_test")

    assert snapshot["kind"] == "droplet_capture_performance_snapshot"
    assert snapshot["reason"] == "unit_test"
    assert snapshot["event_count"] == 2
    assert snapshot["event_counts"]["controller_completion_received"] == 1
    assert [row["request_id"] for row in snapshot["event_log_tail"]] == ["new", "new"]
    json.dumps(snapshot)


def test_droplet_capture_perf_snapshot_summarizes_timings():
    diagnostics = DropletCapturePerformanceDiagnostics(max_events=10)
    diagnostics.set_enabled(True)

    diagnostics.record("ui_trigger_received", {"ui_sequence": 1})
    diagnostics.record("ui_request_returned", {"ui_sequence": 1, "request_id": "r1", "accepted": True})
    diagnostics.record(
        "controller_completion_received",
        {
            "request_id": "r1",
            "status": "success",
            "cap_id": 12,
            "generation": 44,
            "backend_id": 1,
            "queue_to_worker_start_ms": 1.5,
            "worker_duration_ms": 8.0,
            "worker_complete_to_controller_ms": 0.25,
        },
    )
    diagnostics.record("controller_pending_cleared", {"request_id": "r1"})
    diagnostics.record("ui_pending_cleared", {"request_id": "r1"})

    snapshot = diagnostics.build_snapshot()

    request_summary = snapshot["request_summaries"][0]
    assert request_summary["request_id"] == "r1"
    assert request_summary["status"] == "success"
    assert request_summary["queue_to_worker_start_ms"] == 1.5
    assert request_summary["worker_duration_ms"] == 8.0
    assert request_summary["worker_complete_to_controller_ms"] == 0.25
    assert request_summary["controller_completion_to_pending_clear_ms"] is not None
    assert snapshot["ui_sequence_summaries"][0]["accepted"] is True


def test_controller_writes_droplet_capture_perf_snapshot(tmp_path):
    controller = Controller.__new__(Controller)
    controller.model = SimpleNamespace(experiment_model=SimpleNamespace(experiment_dir_path=str(tmp_path)))
    controller.set_droplet_capture_performance_diagnostics_enabled(True)
    controller.record_droplet_capture_performance_marker("ui_trigger_received", {"ui_sequence": 1})

    path = controller.write_droplet_capture_performance_snapshot(reason="unit_test")

    assert path.parent == tmp_path / "calibration_recordings" / "droplet_capture_performance"
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["reason"] == "unit_test"
    assert payload["event_count"] == 1
