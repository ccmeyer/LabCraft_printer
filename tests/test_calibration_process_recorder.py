import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from tests.calibration_test_utils import ensure_calibration_import_stubs


ensure_calibration_import_stubs()

import CalibrationClasses.Model as calibration_model
from CalibrationClasses.Model import CalibrationProcessRecorder


def _dummy_model(tmp_path):
    exp = SimpleNamespace(
        experiment_dir_path=str(tmp_path),
        calibration_file_path=str(tmp_path / "calibration.json"),
    )
    return SimpleNamespace(experiment_model=exp)


def test_calibration_process_recorder_writes_run_files(tmp_path):
    model = _dummy_model(tmp_path)
    rec = CalibrationProcessRecorder(model)

    run_dir = Path(rec.start_run("NozzlePositionCalibrationProcess", "nozzle_position", extra_meta={"test": True}))
    assert run_dir.exists()
    assert (run_dir / "run_meta.json").exists()
    assert (run_dir / "verdict.json").exists()

    evt = rec.append_event("test_event", {"value": 1})
    assert evt is not None

    frame = np.zeros((24, 36, 3), dtype=np.uint8)
    cap = rec.save_capture_image(frame, role="background", metadata={"pair_id": "pair_1"})
    assert cap is not None

    ana = rec.append_analysis({"kind": "test_analysis", "status": "OK"})
    assert ana is not None

    rec.finalize_run("completed")
    assert (run_dir / cap["image_relpath"]).exists()
    verdict = rec.write_verdict("success", notes="looks good", submitted_by="unit-test")
    assert verdict is not None

    meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["outcome"] == "completed"
    assert meta["capture_write_failure_count"] == 0
    assert meta["recorder_warning_count"] == 0

    verdict_payload = json.loads((run_dir / "verdict.json").read_text(encoding="utf-8"))
    assert verdict_payload["outcome"] == "success"
    assert verdict_payload["notes"] == "looks good"

    event_lines = (run_dir / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    event_types = [json.loads(line)["event_type"] for line in event_lines]
    assert event_types == ["test_event", "capture_saved"]

    analysis_lines = (run_dir / "analysis.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(analysis_lines) == 1


def test_calibration_process_recorder_queues_capture_writes(monkeypatch, tmp_path):
    model = _dummy_model(tmp_path)
    rec = CalibrationProcessRecorder(model)
    run_dir = Path(rec.start_run("OnlineStreamCalibrationProcess", "online_stream_calibration"))
    rec.append_event("test_event", {"value": 1})

    write_started = threading.Event()
    allow_write = threading.Event()

    def _fake_imwrite(path, image):
        write_started.set()
        allow_write.wait(timeout=2.0)
        Path(path).write_bytes(b"queued-frame")
        return True

    monkeypatch.setattr(calibration_model.cv2, "imwrite", _fake_imwrite)

    frame = np.zeros((24, 36, 3), dtype=np.uint8)
    started = time.monotonic()
    cap = rec.save_capture_image(frame, role="flow_frame", metadata={"stage_text": "flow frame"})
    elapsed_s = time.monotonic() - started

    assert cap is not None
    assert elapsed_s < 0.1
    assert write_started.wait(timeout=1.0)
    assert not (run_dir / cap["image_relpath"]).exists()

    event_types_before = [
        json.loads(line)["event_type"]
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    ]
    assert event_types_before == ["test_event"]

    allow_write.set()
    rec.finalize_run("completed")

    assert (run_dir / cap["image_relpath"]).exists()
    event_types_after = [
        json.loads(line)["event_type"]
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    ]
    assert event_types_after == ["test_event", "capture_saved"]


def test_calibration_process_recorder_records_capture_write_failures(monkeypatch, tmp_path):
    model = _dummy_model(tmp_path)
    rec = CalibrationProcessRecorder(model)
    run_dir = Path(rec.start_run("OnlineStreamCalibrationProcess", "online_stream_calibration"))

    monkeypatch.setattr(calibration_model.cv2, "imwrite", lambda path, image: False)

    frame = np.zeros((24, 36, 3), dtype=np.uint8)
    cap = rec.save_capture_image(frame, role="flow_frame", metadata={"stage_text": "flow frame"})
    assert cap is not None

    rec.finalize_run("completed")

    meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["capture_write_failure_count"] == 1
    assert meta["capture_write_failures"][0]["capture_id"] == cap["capture_id"]
    assert not (run_dir / cap["image_relpath"]).exists()

    event_payloads = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    ]
    event_types = [row["event_type"] for row in event_payloads]
    assert "capture_save_failed" in event_types
    assert "capture_saved" not in event_types


def test_calibration_process_recorder_warns_when_capture_drain_times_out(monkeypatch, tmp_path):
    model = _dummy_model(tmp_path)
    rec = CalibrationProcessRecorder(model)
    run_dir = Path(rec.start_run("OnlineStreamCalibrationProcess", "online_stream_calibration"))

    allow_write = threading.Event()

    def _slow_imwrite(path, image):
        allow_write.wait(timeout=2.0)
        Path(path).write_bytes(b"slow-frame")
        return True

    monkeypatch.setattr(calibration_model.cv2, "imwrite", _slow_imwrite)
    monkeypatch.setattr(CalibrationProcessRecorder, "CAPTURE_WRITE_DRAIN_TIMEOUT_S", 0.05)

    frame = np.zeros((24, 36, 3), dtype=np.uint8)
    rec.save_capture_image(frame, role="flow_frame", metadata={"stage_text": "flow frame"})

    releaser = threading.Thread(
        target=lambda: (time.sleep(0.2), allow_write.set()),
        daemon=True,
    )
    releaser.start()

    rec.finalize_run("completed")
    releaser.join(timeout=1.0)

    meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["recorder_warning_count"] == 1
    assert meta["recorder_warnings"][0]["kind"] == "capture_write_drain_timeout"

    event_types = [
        json.loads(line)["event_type"]
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    ]
    assert "capture_write_drain_timeout" in event_types
