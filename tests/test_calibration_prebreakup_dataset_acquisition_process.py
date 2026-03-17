from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tests.calibration_test_utils import Recorder, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import (  # noqa: E402
    CalibrationManager,
    PreBreakupDatasetAcquisitionProcess,
)


def _ready_cm():
    return SimpleNamespace(
        get_record_mode_enabled=lambda: True,
        get_pressure_scan_nozzle_center_image_position=lambda: (160, 80),
        get_emergence_time=lambda: 3200,
        model=SimpleNamespace(
            droplet_camera_model=SimpleNamespace(get_image_size=lambda: (320, 320)),
        ),
    )


def _proc_stub(tmp_path: Path):
    proc = PreBreakupDatasetAcquisitionProcess.__new__(PreBreakupDatasetAcquisitionProcess)
    proc._recorder_run_dir = str(tmp_path / "run_001")
    proc._recorder_run_id = "run_001"
    proc._last_capture_refs = {
        "background_image": {
            "capture_id": "cap_bg",
            "image_relpath": "captures/background.png",
            "capture_role": "background",
        },
        "frame_image": {
            "capture_id": "cap_frame",
            "capture_index": 7,
            "image_relpath": "captures/frame_0007.png",
            "capture_role": "capture",
        },
    }
    proc.calibration_manager = SimpleNamespace(
        _safe_get_stock_solution=lambda: "water",
        _safe_get_printer_head_id=lambda: "head_A",
    )
    proc.P_MIN = 0.30
    proc.P_MAX = 5.0
    proc._condition_id = "cond_0001"
    proc._current_condition_index = 0
    proc._pulse_width_us = 1300
    proc._pressure_psi = 0.42
    proc._default_pressure_psi = 0.42
    proc._default_pulse_width_us = 1300
    proc.delay_mode = "emergence_relative"
    proc.delay_start_offset_us = 100
    proc.delay_stop_offset_us = 220
    proc.delay_step_us = 50
    proc.replicates_per_delay = 2
    proc._default_delay_start_offset_us = 100
    proc._default_delay_stop_offset_us = 220
    proc._default_delay_step_us = 50
    proc._default_replicates_per_delay = 2
    proc._default_stock_solution = "water"
    proc._default_printer_head_id = "head_A"
    proc.emergence_time_us = 3200
    proc.nozzle_center_px = (160, 80)
    proc.delays = [3300, 3350, 3400, 3420]
    proc._conditions = [
        {
            "condition_id": "cond_0001",
            "condition_index": 1,
            "pulse_width_us": 1300,
            "pressure_psi": 0.42,
            "delay_mode": "emergence_relative",
            "delay_start_offset_us": 100,
            "delay_stop_offset_us": 220,
            "delay_step_us": 50,
            "replicates_per_delay": 2,
            "background_policy": "per_condition",
            "stock_solution": "water",
            "printer_head_id": "head_A",
            "nozzle_id": "n1",
            "label_key": "pw1300",
            "notes": "",
        }
    ]
    proc._active_condition = dict(proc._conditions[0])
    proc._condition_record = {}
    proc._condition_written = False
    proc._condition_summaries = [
        {
            "condition_id": "cond_0001",
            "condition_index": 1,
            "pulse_width_us": 1300,
            "pressure_psi": 0.42,
            "delay_start_us": 3300,
            "delay_stop_us": 3420,
            "delay_step_us": 50,
            "replicates_per_delay": 2,
            "label_key": "pw1300",
        }
    ]
    proc._current_delay_us = 3350
    proc._replicate_index = 0
    proc._frame_count = 1
    proc._background_count = 1
    proc._analysis_count = 0
    proc._overlay_count = 0
    proc._run_dir = str(Path(proc._recorder_run_dir))
    proc._conditions_path = str(Path(proc._recorder_run_dir) / "conditions.jsonl")
    proc._frames_path = str(Path(proc._recorder_run_dir) / "frames.jsonl")
    proc._plan_snapshot_path = str(Path(proc._recorder_run_dir) / "plan_snapshot.json")
    proc._plan_snapshot_written = False
    proc._requested_plan_path = None
    proc._plan_definition = {"schema_version": 1, "conditions": list(proc._conditions)}
    proc.analyze_frames = False
    proc.save_overlays = False
    proc._measurements = [("cond_0001", 3350, 1, 0.42)]
    proc.background_image = None
    proc.frame_image = None
    proc.phase_name = "pre_breakup_dataset_acquisition"
    return proc


def test_prebreakup_dataset_missing_requirements_reports_dependencies():
    cm = _ready_cm()
    cm.get_record_mode_enabled = lambda: False
    cm.get_pressure_scan_nozzle_center_image_position = lambda: None
    cm.get_emergence_time = lambda: None
    cm.model.droplet_camera_model.get_image_size = lambda: (_ for _ in ()).throw(RuntimeError("no camera"))

    missing = PreBreakupDatasetAcquisitionProcess.missing_requirements(cm)

    joined = " | ".join(missing).lower()
    assert "record calibration runs enabled" in joined
    assert "image coords" in joined
    assert "emergence" in joined
    assert "droplet camera" in joined


def test_prebreakup_dataset_missing_requirements_ready_case_is_empty():
    assert PreBreakupDatasetAcquisitionProcess.missing_requirements(_ready_cm()) == []


def test_start_prebreakup_dataset_uses_try_start_process_and_kwargs():
    mgr = CalibrationManager.__new__(CalibrationManager)
    called = {"proc_cls": None, "kwargs": None}

    def _stub(proc_cls, *args, **kwargs):
        called["proc_cls"] = proc_cls
        called["kwargs"] = dict(kwargs)
        return True

    mgr._try_start_process = _stub
    CalibrationManager.start_prebreakup_dataset_acquisition(
        mgr,
        plan_path="tmp\\dataset_plan.json",
        pressure_psi=0.58,
        pulse_width_us=1450,
        delay_start_offset_us=150,
        delay_stop_offset_us=2450,
        delay_step_us=75,
        replicates_per_delay=3,
        analyze_frames=True,
        save_overlays=True,
    )

    assert called["proc_cls"] is PreBreakupDatasetAcquisitionProcess
    assert called["kwargs"] == {
        "plan_path": "tmp\\dataset_plan.json",
        "pressure_psi": 0.58,
        "pulse_width_us": 1450,
        "delay_start_offset_us": 150,
        "delay_stop_offset_us": 2450,
        "delay_step_us": 75,
        "replicates_per_delay": 3,
        "analyze_frames": True,
        "save_overlays": True,
    }


def test_prebreakup_dataset_build_delay_schedule_appends_terminal_stop():
    proc = PreBreakupDatasetAcquisitionProcess.__new__(PreBreakupDatasetAcquisitionProcess)
    proc.emergence_time_us = 3200
    proc.delay_mode = "emergence_relative"
    proc.delay_start_offset_us = 100
    proc.delay_stop_offset_us = 220
    proc.delay_step_us = 50

    delays = proc._build_delay_schedule()

    assert delays == [3300, 3350, 3400, 3420]


def test_prebreakup_dataset_normalize_plan_expands_pw_and_pressure_ranges():
    proc = PreBreakupDatasetAcquisitionProcess.__new__(PreBreakupDatasetAcquisitionProcess)
    proc.P_MIN = 0.30
    proc.P_MAX = 5.0
    proc.emergence_time_us = 3200
    proc._default_delay_start_offset_us = 100
    proc._default_delay_stop_offset_us = 2200
    proc._default_delay_step_us = 50
    proc._default_replicates_per_delay = 2
    proc._default_stock_solution = "water"
    proc._default_printer_head_id = "head_A"
    proc._default_pulse_width_us = 1300
    proc._default_pressure_psi = 0.40

    plan = {
        "schema_version": 1,
        "defaults": {
            "delay_start_offset_us": 150,
            "delay_stop_offset_us": 350,
            "delay_step_us": 100,
            "replicates_per_delay": 3,
        },
        "conditions": [
            {
                "condition_id": "grid",
                "pulse_widths_us": [1300, 1400],
                "pressure_start_psi": 0.40,
                "pressure_stop_psi": 0.46,
                "pressure_step_psi": 0.03,
                "label_key": "grid_label",
            }
        ],
    }

    normalized = proc._normalize_plan_conditions(plan)

    assert len(normalized) == 6
    assert normalized[0]["condition_id"] == "grid_001"
    assert normalized[-1]["condition_id"] == "grid_006"
    assert {row["pulse_width_us"] for row in normalized} == {1300, 1400}
    assert {row["pressure_psi"] for row in normalized} == {0.40, 0.43, 0.46}
    assert all(row["delay_start_us"] == 3350 for row in normalized)
    assert all(row["delay_stop_us"] == 3550 for row in normalized)
    assert all(row["replicates_per_delay"] == 3 for row in normalized)
    assert all(row["label_key"] == "grid_label" for row in normalized)


def test_prebreakup_dataset_advance_to_next_condition_resets_condition_state(tmp_path):
    proc = _proc_stub(tmp_path)
    proc._conditions = [
        dict(proc._active_condition),
        {
            "condition_id": "cond_0002",
            "condition_index": 2,
            "pulse_width_us": 1500,
            "pressure_psi": 0.55,
            "delay_mode": "emergence_relative",
            "delay_start_offset_us": 200,
            "delay_stop_offset_us": 400,
            "delay_step_us": 100,
            "replicates_per_delay": 4,
            "background_policy": "per_condition",
            "stock_solution": "reagent_b",
            "printer_head_id": "head_B",
            "nozzle_id": "n2",
            "label_key": "pw1500",
            "notes": "second block",
        },
    ]
    proc._delay_index = 3
    proc._replicate_index = 1
    proc.background_image = object()
    proc.frame_image = object()

    advanced = proc._advance_to_next_condition()

    assert advanced is True
    assert proc._current_condition_index == 1
    assert proc._condition_id == "cond_0002"
    assert proc._pulse_width_us == 1500
    assert proc._pressure_psi == pytest.approx(0.55)
    assert proc.delays == [3400, 3500, 3600]
    assert proc.replicates_per_delay == 4
    assert proc._delay_index == 0
    assert proc._replicate_index == 0
    assert proc.background_image is None
    assert proc.frame_image is None


def test_prebreakup_dataset_writes_condition_and_frame_rows(tmp_path):
    proc = _proc_stub(tmp_path)

    proc._ensure_dataset_paths()
    proc._write_condition_record()
    frame_record = proc._build_frame_record(proc._get_capture_ref("frame_image"))
    proc._append_dataset_jsonl(proc._frames_path, frame_record)

    condition_lines = Path(proc._conditions_path).read_text(encoding="utf-8").strip().splitlines()
    frame_lines = Path(proc._frames_path).read_text(encoding="utf-8").strip().splitlines()

    condition_payload = json.loads(condition_lines[0])
    frame_payload = json.loads(frame_lines[0])

    assert condition_payload["condition_id"] == "cond_0001"
    assert condition_payload["condition_index"] == 1
    assert condition_payload["pulse_width_us"] == 1300
    assert condition_payload["pressure_psi"] == pytest.approx(0.42)
    assert condition_payload["background_image_relpath"] == "captures/background.png"
    assert condition_payload["delay_start_us"] == 3300
    assert condition_payload["delay_stop_us"] == 3420
    assert condition_payload["label_key"] == "pw1300"

    assert frame_payload["condition_id"] == "cond_0001"
    assert frame_payload["condition_index"] == 1
    assert frame_payload["image_relpath"] == "captures/frame_0007.png"
    assert frame_payload["background_image_relpath"] == "captures/background.png"
    assert frame_payload["flash_delay_us"] == 3350
    assert frame_payload["delay_from_emergence_us"] == 150
    assert frame_payload["pulse_width_us"] == 1300
    assert frame_payload["pressure_psi"] == pytest.approx(0.42)
    assert frame_payload["stock_solution"] == "water"
    assert frame_payload["printer_head_id"] == "head_A"
    assert frame_payload["label_key"] == "pw1300"


def test_prebreakup_dataset_on_record_frame_writes_analysis_and_overlay(tmp_path):
    proc = _proc_stub(tmp_path)
    proc.analyze_frames = True
    proc.save_overlays = True
    proc.background_image = np.zeros((12, 12, 3), dtype=np.uint8)
    proc.frame_image = np.ones((12, 12, 3), dtype=np.uint8)
    proc._analysis_count = 0
    proc._overlay_count = 0
    proc._frame_count = 0
    proc._measurements = []
    proc._delay_index = 0
    proc.frameStored = Recorder()
    proc.presentImageSignal = Recorder()
    proc.model = SimpleNamespace(
        droplet_camera_model=SimpleNamespace(
            analyze_prebreakup_morphology=lambda *args, **kwargs: (
                {"protrusion_length_px": 42, "distance_nozzle_to_neck_px": 18},
                np.full((12, 12, 3), 9, dtype=np.uint8),
                {"status": "ok", "contour_class": "attached"},
            )
        )
    )

    appended = []
    analyses = []

    proc._append_dataset_jsonl = lambda path, payload: appended.append((path, payload))
    proc._record_analysis = lambda payload: analyses.append(payload)
    proc._record_capture = lambda _image, *, role, metadata=None: {
        "capture_id": "cap_overlay",
        "image_relpath": "captures/overlay_0001.png",
        "capture_role": role,
        "metadata": dict(metadata or {}),
    }

    proc.onRecordFrame()

    assert len(analyses) == 1
    analysis_payload = analyses[0]
    assert analysis_payload["stage"] == "dataset_frame_analysis"
    assert analysis_payload["capture_id"] == "cap_frame"
    assert analysis_payload["background_capture_id"] == "cap_bg"
    assert analysis_payload["overlay_capture_id"] == "cap_overlay"
    assert analysis_payload["overlay_image_relpath"] == "captures/overlay_0001.png"
    assert analysis_payload["metrics"]["protrusion_length_px"] == 42
    assert analysis_payload["details"]["status"] == "ok"

    assert len(appended) == 1
    frame_payload = appended[0][1]
    assert frame_payload["analysis"]["overlay_capture_id"] == "cap_overlay"
    assert frame_payload["overlay_image_relpath"] == "captures/overlay_0001.png"
    assert frame_payload["overlay_capture_id"] == "cap_overlay"
    assert proc._analysis_count == 1
    assert proc._overlay_count == 1
    assert proc.presentImageSignal.calls
    assert proc.frameStored.calls


def test_prebreakup_dataset_completed_emits_summary(tmp_path):
    proc = _proc_stub(tmp_path)
    proc.stageChanged = Recorder()
    proc.calibrationDataUpdated = Recorder()
    proc.calibrationCompleted = Recorder()

    proc.onCompleted()

    assert proc.calibrationDataUpdated.calls
    payload = proc.calibrationDataUpdated.calls[0][0][0]
    assert payload["measurements"] == [("cond_0001", 3350, 1, 0.42)]
    assert payload["result"]["condition_count"] == 1
    assert payload["result"]["planned_condition_count"] == 1
    assert payload["result"]["frame_count"] == 1
    assert payload["result"]["background_count"] == 1
    assert payload["result"]["analysis_enabled"] is False
    assert payload["result"]["overlay_saving_enabled"] is False
    assert payload["result"]["overlay_count"] == 0
    assert payload["result"]["plan_snapshot_path"].endswith("plan_snapshot.json")
    assert payload["result"]["conditions"][0]["condition_id"] == "cond_0001"
    assert proc.calibrationCompleted.calls
