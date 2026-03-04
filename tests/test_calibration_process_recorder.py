import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from tests.calibration_test_utils import ensure_calibration_import_stubs


ensure_calibration_import_stubs()

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
    assert (run_dir / cap["image_relpath"]).exists()

    ana = rec.append_analysis({"kind": "test_analysis", "status": "OK"})
    assert ana is not None

    rec.finalize_run("completed")
    verdict = rec.write_verdict("success", notes="looks good", submitted_by="unit-test")
    assert verdict is not None

    meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["outcome"] == "completed"

    verdict_payload = json.loads((run_dir / "verdict.json").read_text(encoding="utf-8"))
    assert verdict_payload["outcome"] == "success"
    assert verdict_payload["notes"] == "looks good"

    event_lines = (run_dir / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(event_lines) == 1

    analysis_lines = (run_dir / "analysis.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(analysis_lines) == 1
