import json
from pathlib import Path
from types import SimpleNamespace

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

import CalibrationClasses.View as calibration_view
from CalibrationClasses.Model import CalibrationManager
from CalibrationClasses.View import DropletImagingDialog


class _DummyProcess:
    phase_name = "nozzle_position"


class _NonVerdictProcess:
    phase_name = "head_prime"
    supports_operator_verdict = False


class _CleanupProcess:
    phase_name = "nozzle_position"
    supports_operator_verdict = True

    def __init__(self):
        self.stageChanged = SignalStub()
        self.calibrationCompleted = SignalStub()
        self.calibrationError = SignalStub()
        self.calibrationDataUpdated = SignalStub()
        self.presentImageSignal = SignalStub()
        self.cleaned = False
        self.deleted = False

    def release_runtime_resources(self):
        self.cleaned = True

    def deleteLater(self):
        self.deleted = True



def _dummy_model(tmp_path):
    return SimpleNamespace(
        machine_state_updated=SignalStub(),
        experiment_model=SimpleNamespace(
            experiment_dir_path=str(tmp_path),
            calibration_file_path=str(tmp_path / "calibration.json"),
            get_calibration_file_path=lambda: str(tmp_path / "calibration.json"),
        ),
        rack_model=SimpleNamespace(get_gripper_printer_head=lambda: None),
        droplet_camera_model=SimpleNamespace(get_image_metadata=lambda: (0, 0, 0, 0, 0)),
        machine_model=SimpleNamespace(
            get_current_position_dict=lambda: {"X": 0, "Y": 0, "Z": 0},
            get_print_pulse_width=lambda: 0,
            get_refuel_pulse_width=lambda: 0,
            get_current_print_pressure=lambda: 0.0,
            get_current_refuel_pressure=lambda: 0.0,
        ),
    )


def test_manager_submits_pending_process_verdict(tmp_path):
    model = _dummy_model(tmp_path)
    mgr = CalibrationManager(model)

    proc = _DummyProcess()
    mgr._begin_process_recording(proc)
    mgr._pending_process_verdict = mgr._build_pending_process_verdict_context(
        proc,
        default_outcome="failed",
    )
    latest = mgr.get_latest_recording_directory()
    assert latest

    out = mgr.submit_pending_process_verdict(
        outcome="failed",
        failure_summary="nozzle not centered",
        suspected_cause="weak signal",
        notes="repeat under brighter lighting",
        submitted_by="unit-test",
    )
    assert out is not None

    verdict_path = Path(latest) / "verdict.json"
    assert verdict_path.exists()
    payload = json.loads(verdict_path.read_text(encoding="utf-8"))
    assert payload["outcome"] == "failed"
    assert payload["failure_summary"] == "nozzle not centered"
    assert payload["suspected_cause"] == "weak signal"
    assert mgr.get_pending_process_verdict() is None


def test_non_verdict_process_does_not_create_pending_verdict_context(tmp_path):
    model = _dummy_model(tmp_path)
    mgr = CalibrationManager(model)

    proc = _NonVerdictProcess()
    mgr._begin_process_recording(proc)

    pending = mgr._build_pending_process_verdict_context(proc, default_outcome="success")

    assert pending is None


def test_on_calibration_completed_cleans_up_process_and_sets_pending_verdict(tmp_path, monkeypatch):
    model = _dummy_model(tmp_path)
    mgr = CalibrationManager(model)
    mgr._emit_readiness = lambda: None
    proc = _CleanupProcess()
    mgr.activeCalibration = proc
    mgr._begin_process_recording(proc)

    mgr.onCalibrationCompleted()

    pending = mgr.get_pending_process_verdict()
    assert pending is not None
    assert pending["process_name"] == "_CleanupProcess"
    assert proc.cleaned is True
    assert proc.deleted is True
    assert mgr.activeCalibration is None


def test_prompt_ignores_stale_latest_recording_when_no_pending_context(monkeypatch, qapp):
    manager = SimpleNamespace(
        get_pending_process_verdict=lambda: None,
        get_latest_recording_directory=lambda: (_ for _ in ()).throw(
            AssertionError("prompt should not consult latest recording directory")
        ),
    )
    dialog = SimpleNamespace(model=SimpleNamespace(calibration_manager=manager))
    dialog._prompt_calibration_verdict = (
        DropletImagingDialog._prompt_calibration_verdict.__get__(dialog, DropletImagingDialog)
    )

    def _boom(*args, **kwargs):
        raise AssertionError("verdict dialog should not be constructed without pending context")

    monkeypatch.setattr(calibration_view, "CalibrationVerdictDialog", _boom)

    dialog._prompt_calibration_verdict(default_outcome="success")


def test_prompt_submits_pending_verdict_and_clears_on_skip(monkeypatch, qapp):
    submitted = []
    cleared = []

    class _Manager:
        def __init__(self):
            self.pending = {
                "process_name": "PressureBandCalibrationProcess",
                "phase_name": "pressure_scan",
                "default_outcome": "success",
                "error_message": "",
            }

        def get_pending_process_verdict(self):
            return dict(self.pending) if self.pending else None

        def submit_pending_process_verdict(self, **kwargs):
            submitted.append(dict(kwargs))
            self.pending = None
            return dict(kwargs)

        def clear_pending_process_verdict(self, *, reason=""):
            cleared.append(str(reason))
            self.pending = None

    class _AcceptedDialog:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def exec(self):
            return True

        def get_verdict_payload(self):
            return {
                "outcome": "failed",
                "failure_summary": "bad image",
                "suspected_cause": "lighting",
                "notes": "retry",
            }

    class _RejectedDialog:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def exec(self):
            return False

        def get_verdict_payload(self):
            raise AssertionError("payload should not be read when dialog is rejected")

    manager = _Manager()
    dialog = SimpleNamespace(model=SimpleNamespace(calibration_manager=manager))
    dialog._prompt_calibration_verdict = (
        DropletImagingDialog._prompt_calibration_verdict.__get__(dialog, DropletImagingDialog)
    )

    monkeypatch.setattr(calibration_view, "CalibrationVerdictDialog", _AcceptedDialog)
    dialog._prompt_calibration_verdict(default_outcome="success")
    assert submitted == [
        {
            "outcome": "failed",
            "failure_summary": "bad image",
            "suspected_cause": "lighting",
            "notes": "retry",
            "submitted_by": "ui",
        }
    ]

    manager.pending = {
        "process_name": "PressureBandCalibrationProcess",
        "phase_name": "pressure_scan",
        "default_outcome": "failed",
        "error_message": "camera timeout",
    }
    monkeypatch.setattr(calibration_view, "CalibrationVerdictDialog", _RejectedDialog)
    dialog._prompt_calibration_verdict(default_outcome="failed", error_message="camera timeout")
    assert cleared == ["ui_skipped"]
