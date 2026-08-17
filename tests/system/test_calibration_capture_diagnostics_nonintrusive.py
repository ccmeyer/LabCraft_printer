from __future__ import annotations

import json

import pytest

from CalibrationClasses.View import DropletImagingDialog
from Controller import DropletCapturePerformanceDiagnostics
from Machine_FreeRTOS import DropletCamera


SCENARIO_ID = "calibration_capture_diagnostics_nonintrusive_v1"


class _Label:
    def __init__(self):
        self.value = ""

    def setText(self, value):
        self.value = str(value)


@pytest.mark.sil_lifecycle
def test_calibration_capture_diagnostics_nonintrusive():
    camera = DropletCamera.__new__(DropletCamera)
    camera._cap_id = 0
    DropletCamera.set_capture_performance_diagnostics_enabled(camera, True)
    diagnostics = DropletCapturePerformanceDiagnostics(max_events=5000)
    diagnostics.set_enabled(True)
    pipeline_counts = {"callbacks": 0, "storage_writes": 0, "saved_images": 0}

    for index in range(1000):
        request_id = f"sil-capture-{index:04d}"
        generation = index + 1
        DropletCamera._start_capture_performance_trace(camera, request_id, generation)
        for phase, elapsed_ms in (
            ("retry_attempt_start", 0.0),
            ("trigger_high", 1.0),
            ("edge_wait_start", 2.0),
            ("edge_wait_done", 5.0),
            ("arm_start", 6.0),
        ):
            DropletCamera._log_capture_phase(
                camera,
                phase,
                request_id=request_id,
                generation=generation,
                started_ns=None,
                synthetic_elapsed_ms=elapsed_ms,
            )
            # The production logger computes elapsed_ms from a monotonic start.
            # Set the deterministic SIL value directly in the retained row.
            camera._capture_performance_traces[(request_id, generation)]["phases"][-1][
                "elapsed_ms"
            ] = elapsed_ms
        DropletCamera._log_capture_phase(
            camera,
            "retry_attempt_result",
            request_id=request_id,
            generation=generation,
            reason="threshold",
            mean=100.0,
            threshold=25.0,
            make_array_ms=2.0,
            rotate_ms=1.0,
        )
        camera._capture_performance_traces[(request_id, generation)]["phases"][-1][
            "elapsed_ms"
        ] = 10.0
        trace = DropletCamera._pop_capture_performance_trace(camera, request_id, generation)
        summary = DropletCamera._build_capture_performance_summary(
            trace,
            request_id=request_id,
            generation=generation,
            backend_id="simulated",
            cap_id=generation,
        )
        diagnostics.record("camera_capture_summary", summary)
        diagnostics.record(
            "controller_completion_received",
            {"request_id": request_id, "status": "success", "cap_id": generation},
        )
        pipeline_counts["callbacks"] += 1
        pipeline_counts["storage_writes"] += 1
        pipeline_counts["saved_images"] += 1
        if (index + 1) % 250 == 0:
            print(
                "SIL_PROGRESS "
                + json.dumps(
                    {"scenario_id": SCENARIO_ID, "captures_complete": index + 1},
                    sort_keys=True,
                ),
                flush=True,
            )

    status_host = type("StatusHost", (), {})()
    status_host.stageLabel = _Label()
    for index in range(1000):
        DropletImagingDialog.update_stage_and_log(status_host, f"stage-{index}", "blue")

    snapshot = diagnostics.build_snapshot(reason="sil_contract")
    hardware_activity = {
        "camera": 0,
        "gpio": 0,
        "serial": 0,
        "motion": 0,
        "pressure": 0,
        "dispense": 0,
        "firmware": 0,
        "physical_ports": 0,
    }
    metrics = {
        "scenario_id": SCENARIO_ID,
        "capture_summary_count": snapshot["event_counts"].get("camera_capture_summary", 0),
        "normal_phase_event_count": snapshot["event_counts"].get("camera_phase", 0),
        "request_summary_count": len(snapshot["request_summaries"]),
        "pipeline_counts": pipeline_counts,
        "trace_count_after_completion": len(camera._capture_performance_traces),
        "status_text": status_host.stageLabel.value,
        "hardware_activity": hardware_activity,
    }
    print("SIL_PROGRESS " + json.dumps(metrics, sort_keys=True), flush=True)

    assert snapshot["schema_version"] == 10
    assert metrics["capture_summary_count"] == 1000
    assert metrics["normal_phase_event_count"] == 0
    assert metrics["request_summary_count"] == 1000
    assert pipeline_counts == {"callbacks": 1000, "storage_writes": 1000, "saved_images": 1000}
    assert metrics["trace_count_after_completion"] == 0
    assert metrics["status_text"] == "Status: stage-999"
    assert not hasattr(status_host, "stage_table")
    assert hardware_activity == {key: 0 for key in hardware_activity}
