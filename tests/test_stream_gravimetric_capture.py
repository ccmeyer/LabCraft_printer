import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs(force=True)

from CalibrationClasses.Model import CalibrationManager, DropletTimecourseProcess
from CalibrationClasses.View import DropletImagingDialog


REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_EXPERIMENT_DIR = (
    REPO_ROOT
    / "FreeRTOS-interface"
    / "Experiments"
    / "Stream_characterization-20260327_225650"
)


class _DummyStockSolution:
    reagent_name = "Water"

    def __str__(self):
        return self.reagent_name


class _DummyPrinterHead:
    def __init__(self):
        self.serial = "PH-001"
        self._stock_solution = _DummyStockSolution()

    def get_stock_solution(self):
        return self._stock_solution


class _ManagerDropletCameraModel:
    def __init__(
        self,
        *,
        num_flashes=100,
        flash_duration=1000,
        flash_delay=5600,
        num_droplets=1,
        exposure_time=30000,
    ):
        self.num_flashes = int(num_flashes)
        self.flash_duration = int(flash_duration)
        self.flash_delay = int(flash_delay)
        self.num_droplets = int(num_droplets)
        self.exposure_time = int(exposure_time)

    def get_image_metadata(self):
        return (
            self.num_flashes,
            self.flash_duration,
            self.flash_delay,
            self.num_droplets,
            self.exposure_time,
        )

    def get_num_flashes(self):
        return self.num_flashes


class _ViewDropletCameraModelStub:
    def __init__(self):
        self.flash_duration = 1000
        self.flash_delay = 5600
        self.num_droplets = 1
        self.exposure_time = 30000
        self.num_flashes = 0
        self.ext_counter = 0
        self.flash_session_armed = False
        self.flash_fault_latched = False
        self.flash_fault_reason = ""
        self.droplet_image_updated = SignalStub()
        self.flash_signal = SignalStub()

    def get_flash_duration(self):
        return self.flash_duration

    def get_flash_delay(self):
        return self.flash_delay

    def get_num_droplets(self):
        return self.num_droplets

    def get_exposure_time(self):
        return self.exposure_time

    def get_num_flashes(self):
        return self.num_flashes

    def get_trigger_counter(self):
        return self.ext_counter

    def get_flash_session_armed(self):
        return self.flash_session_armed

    def get_flash_fault_latched(self):
        return self.flash_fault_latched

    def get_flash_fault_reason_display(self):
        return "None"


class _StreamCaptureManagerStub:
    def __init__(self, state):
        self.state = dict(state)
        self.record_mode_enabled = True
        self.pending_clear_reasons = []
        self.analyzedImageUpdated = SignalStub()
        self.calibrationStageChanged = SignalStub()
        self.calibrationCompleted = SignalStub()
        self.calibrationQueueCompleted = SignalStub()
        self.calibrationError = SignalStub()
        self.position_diff_dict_signal = SignalStub()
        self.characterizationSummaryUpdated = SignalStub()
        self.readinessChanged = SignalStub()
        self.streamCaptureStateChanged = SignalStub()

    def clear_calibration_memory_ui_recommendation_state(self):
        return None

    def _emit_readiness(self):
        return None

    def get_record_mode_enabled(self):
        return bool(self.record_mode_enabled)

    def get_calibration_memory_enabled(self):
        return False

    def get_stream_gravimetric_capture_state(self):
        return dict(self.state)

    def is_stream_gravimetric_capture_busy(self):
        return str(self.state.get("status") or "idle") in {"running", "awaiting_mass"}

    def should_suppress_process_verdict(self):
        return str(self.state.get("status") or "idle") in {"running", "awaiting_mass", "error", "stopped"}

    def clear_pending_process_verdict(self, *, reason=""):
        self.pending_clear_reasons.append(str(reason))


def _make_manager_model(tmp_path, *, experiment_dir_name="experiment", num_flashes=100):
    experiment_dir = tmp_path / experiment_dir_name
    experiment_dir.mkdir(parents=True, exist_ok=True)
    calibration_path = experiment_dir / "calibration.json"

    printer_head = _DummyPrinterHead()
    rack_model = SimpleNamespace(get_gripper_printer_head=lambda: printer_head)
    experiment_model = SimpleNamespace(
        experiment_dir_path=str(experiment_dir),
        calibration_file_path=str(calibration_path),
        get_calibration_file_path=lambda: str(calibration_path),
    )
    droplet_camera_model = _ManagerDropletCameraModel(num_flashes=num_flashes)
    machine_model = SimpleNamespace(
        get_current_position_dict=lambda: {"X": 10, "Y": 20, "Z": 30},
        get_print_pulse_width=lambda: 3000,
        get_refuel_pulse_width=lambda: 5000,
        get_current_print_pressure=lambda: 0.65,
        get_current_refuel_pressure=lambda: 0.80,
    )
    model = SimpleNamespace(
        machine_state_updated=SignalStub(),
        rack_model=rack_model,
        experiment_model=experiment_model,
        droplet_camera_model=droplet_camera_model,
        machine_model=machine_model,
    )
    return model


def _make_manager(tmp_path, *, experiment_dir_name="experiment", num_flashes=100):
    model = _make_manager_model(
        tmp_path,
        experiment_dir_name=experiment_dir_name,
        num_flashes=num_flashes,
    )
    manager = CalibrationManager(model)
    manager._emit_readiness = lambda: None
    return model, manager


def _write_jsonl(path: Path, rows):
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _settings_event(event_type: str, num_droplets: int, *, flash_delay=None, context="test"):
    settings = {"num_droplets": int(num_droplets)}
    if flash_delay is not None:
        settings["flash_delay"] = int(flash_delay)
    return {
        "event_type": str(event_type),
        "payload": {"settings": settings, "context": str(context)},
    }


def _capture_result_event(*, stage_text: str, status="success", role="droplet"):
    return {
        "event_type": "capture_result",
        "payload": {
            "stage_text": str(stage_text),
            "status": str(status),
            "capture_ref": {"capture_role": str(role)},
        },
    }


def _write_run_dir(
    root: Path,
    *,
    process_name: str,
    run_id: str,
    phase_name: str,
    settings_num_droplets: int,
    events: list[dict],
):
    run_dir = root / process_name / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run_meta = {
        "schema_version": 1,
        "run_id": run_id,
        "process_name": process_name,
        "phase_name": phase_name,
        "settings_snapshot": {
            "num_flashes": 0,
            "flash_duration": 1000,
            "flash_delay": 5600,
            "num_droplets": int(settings_num_droplets),
            "exposure_time": 30000,
            "current_position": {"X": 10, "Y": 20, "Z": 30},
            "print_width": 3000,
            "refuel_width": 5000,
            "print_pressure": 0.65,
            "refuel_pressure": 0.80,
        },
    }
    (run_dir / "run_meta.json").write_text(json.dumps(run_meta, indent=2), encoding="utf-8")
    _write_jsonl(run_dir / "events.jsonl", events)
    return run_dir


def _make_recorded_process(process_name: str, phase_name: str, run_dir: Path):
    proc_cls = type(process_name, (), {})
    proc = proc_cls()
    proc._recorder_process_name = process_name
    proc._recorder_phase_name = phase_name
    proc._recorder_run_dir = str(run_dir)
    return proc


def _read_csv_rows(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_jsonl_rows(path: Path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _build_view_dialog(monkeypatch, qapp):
    for method_name in (
        "setup_shortcuts",
        "start_droplet_camera",
        "set_exposure_time",
        "set_flash_delay",
        "set_flash_duration",
        "set_imaging_droplets",
        "set_start_pressure",
        "set_num_pressure_tests",
        "populate_summary_table",
        "refresh_calibration_memory_recommendation",
    ):
        monkeypatch.setattr(DropletImagingDialog, method_name, lambda self, *args, **kwargs: None)

    manager = _StreamCaptureManagerStub(
        {
            "status": "idle",
            "status_message": "Ready to begin stream gravimetric capture.",
            "error_message": "",
            "session_id": None,
            "starting_flash": None,
            "ending_flash": None,
            "raw_flash_delta": None,
            "background_capture_count": None,
            "printed_capture_count": None,
            "timecourse_run_id": None,
            "rep": 1,
            "suggested_rep": 1,
            "notes": "",
        }
    )
    model = SimpleNamespace(
        droplet_camera_model=_ViewDropletCameraModelStub(),
        calibration_manager=manager,
        machine_model=SimpleNamespace(
            get_print_pressure_bounds=lambda: (0.10, 5.00),
            get_print_pulse_width=lambda: 1400,
            get_current_print_pressure=lambda: 0.80,
        ),
        experiment_model=SimpleNamespace(experiment_dir_path="C:/tmp/example-experiment"),
    )
    controller = SimpleNamespace(
        start_read_camera=lambda: None,
        capture_droplet_image=lambda throughput_mode=False: None,
        start_stream_gravimetric_capture=lambda *args, **kwargs: (True, ""),
        finalize_stream_gravimetric_capture=lambda *args, **kwargs: (True, ""),
        discard_stream_gravimetric_capture=lambda *args, **kwargs: (True, ""),
    )
    dialog = DropletImagingDialog(SimpleNamespace(color_dict={}), model, controller)
    qapp.processEvents()
    return dialog, manager


def test_stream_capture_count_replay_uses_recorded_run_meta_and_events():
    if not SAMPLE_EXPERIMENT_DIR.exists():
        pytest.skip("Sample stream-characterization experiment is not available in this checkout.")

    model = SimpleNamespace(
        machine_state_updated=SignalStub(),
        rack_model=SimpleNamespace(get_gripper_printer_head=lambda: _DummyPrinterHead()),
        experiment_model=SimpleNamespace(
            experiment_dir_path=str(SAMPLE_EXPERIMENT_DIR),
            calibration_file_path=str(SAMPLE_EXPERIMENT_DIR / "calibration.json"),
            get_calibration_file_path=lambda: str(SAMPLE_EXPERIMENT_DIR / "calibration.json"),
        ),
        droplet_camera_model=_ManagerDropletCameraModel(),
        machine_model=SimpleNamespace(
            get_current_position_dict=lambda: {"X": 0, "Y": 0, "Z": 0},
            get_print_pulse_width=lambda: 3000,
            get_refuel_pulse_width=lambda: 5000,
            get_current_print_pressure=lambda: 0.65,
            get_current_refuel_pressure=lambda: 0.80,
        ),
    )
    manager = CalibrationManager(model)
    manager._emit_readiness = lambda: None

    child_processes = [
        {
            "run_dir": str(
                SAMPLE_EXPERIMENT_DIR
                / "calibration_recordings"
                / "NozzlePositionCalibrationProcess"
                / "run_20260327_230448_f214dd50"
            )
        },
        {
            "run_dir": str(
                SAMPLE_EXPERIMENT_DIR
                / "calibration_recordings"
                / "NozzleFocusCalibrationProcess"
                / "run_20260327_230502_307fd95e"
            )
        },
        {
            "run_dir": str(
                SAMPLE_EXPERIMENT_DIR
                / "calibration_recordings"
                / "DropletEmergenceCalibrationProcess"
                / "run_20260327_230514_5940193e"
            )
        },
        {
            "run_dir": str(
                SAMPLE_EXPERIMENT_DIR
                / "calibration_recordings"
                / "DropletTimecourseProcess"
                / "run_20260327_230520_9567e1ee"
            )
        },
    ]

    counts = manager._derive_stream_capture_counts(child_processes=child_processes)

    assert counts["background_capture_count"] == 3
    assert counts["printed_capture_count"] == 140
    assert counts["printed_capture_event_count"] == 140


def test_stream_capture_queue_can_start_droplet_timecourse(tmp_path, monkeypatch):
    _model, manager = _make_manager(tmp_path)
    started = []

    def _capture_start(proc_cls, *args, **kwargs):
        started.append(proc_cls)
        return True

    monkeypatch.setattr(manager, "_try_start_process", _capture_start)
    manager.calibration_queue = ["droplet_timecourse"]

    manager.start_calibration_queue()

    assert started == [DropletTimecourseProcess]


def test_stream_capture_finalize_appends_metadata_and_sidecar(tmp_path, monkeypatch):
    model, manager = _make_manager(tmp_path, num_flashes=100)
    queued = []
    recordings_root = Path(model.experiment_model.experiment_dir_path) / "calibration_recordings"

    monkeypatch.setattr(
        manager,
        "start_calibration_queue",
        lambda: queued.append(list(manager.calibration_queue)),
    )

    ok, message = manager.start_stream_gravimetric_capture(0.0, rep_override=2, notes="capture start")
    assert (ok, message) == (True, "")
    assert queued == [list(manager.STREAM_CAPTURE_QUEUE)]
    assert manager.calibration_queue == list(manager.STREAM_CAPTURE_QUEUE)

    nozzle_run = _write_run_dir(
        recordings_root,
        process_name="NozzlePositionCalibrationProcess",
        run_id="run_nozzle",
        phase_name="nozzle_position",
        settings_num_droplets=1,
        events=[
            _settings_event("settings_requested", 0, context="background"),
            _settings_event("settings_completed", 0, context="background"),
            _capture_result_event(stage_text="Background", role="background"),
            _settings_event("settings_requested", 1, context="droplet"),
            _settings_event("settings_completed", 1, context="droplet"),
            _capture_result_event(stage_text="Droplet 1"),
            _capture_result_event(stage_text="Droplet 2"),
        ],
    )
    focus_run = _write_run_dir(
        recordings_root,
        process_name="NozzleFocusCalibrationProcess",
        run_id="run_focus",
        phase_name="nozzle_focus",
        settings_num_droplets=1,
        events=[
            _capture_result_event(stage_text="Focus 1"),
            _capture_result_event(stage_text="Focus 2"),
            _capture_result_event(stage_text="Focus 3"),
        ],
    )
    emergence_run = _write_run_dir(
        recordings_root,
        process_name="DropletEmergenceCalibrationProcess",
        run_id="run_emergence",
        phase_name="droplet_emergence",
        settings_num_droplets=1,
        events=[
            _settings_event("settings_requested", 0, context="background"),
            _settings_event("settings_completed", 0, context="background"),
            _capture_result_event(stage_text="Emergence background", role="background"),
            _settings_event("settings_requested", 1, context="scan"),
            _settings_event("settings_completed", 1, context="scan"),
            _capture_result_event(stage_text="Emergence 1"),
            _capture_result_event(stage_text="Emergence 2"),
        ],
    )
    timecourse_run = _write_run_dir(
        recordings_root,
        process_name="DropletTimecourseProcess",
        run_id="run_timecourse",
        phase_name="droplet_timecourse",
        settings_num_droplets=1,
        events=[
            _capture_result_event(stage_text="Frame 1"),
            _capture_result_event(stage_text="Frame 2"),
            _capture_result_event(stage_text="Frame 3"),
            _capture_result_event(stage_text="Frame 4"),
        ],
    )

    for process_name, phase_name, run_dir in (
        ("NozzlePositionCalibrationProcess", "nozzle_position", nozzle_run),
        ("NozzleFocusCalibrationProcess", "nozzle_focus", focus_run),
        ("DropletEmergenceCalibrationProcess", "droplet_emergence", emergence_run),
        ("DropletTimecourseProcess", "droplet_timecourse", timecourse_run),
    ):
        manager._record_stream_capture_process_result(
            _make_recorded_process(process_name, phase_name, run_dir),
            outcome="completed",
        )

    manager.calibration_queue = []
    model.droplet_camera_model.num_flashes = 113
    manager._complete_stream_capture_queue_success()

    save_ok, save_message = manager.finalize_stream_gravimetric_capture(
        5.5,
        rep_override=3,
        notes="saved row",
    )
    assert (save_ok, save_message) == (True, "")

    metadata_path = Path(model.experiment_model.experiment_dir_path) / "stream_metadata.csv"
    rows = _read_csv_rows(metadata_path)
    assert len(rows) == 1
    assert rows[0]["Dataset name"] == "run_timecourse"
    assert rows[0]["Rep"] == "3"
    assert rows[0]["Starting flash"] == "100"
    assert rows[0]["Ending flash"] == "113"
    assert rows[0]["Mass Change"] == "5.5"
    assert rows[0]["Num printed"] == "11"
    assert rows[0]["Mass/print"] == "0.5"
    assert rows[0]["Notes"] == "saved row"

    sidecar_path = Path(model.experiment_model.experiment_dir_path) / "stream_capture_log.jsonl"
    sidecar_rows = _read_jsonl_rows(sidecar_path)
    assert len(sidecar_rows) == 1
    assert sidecar_rows[0]["outcome"] == "saved"
    assert sidecar_rows[0]["raw_flash_delta"] == 13
    assert sidecar_rows[0]["background_capture_count"] == 2
    assert sidecar_rows[0]["printed_capture_count"] == 11
    assert sidecar_rows[0]["timecourse_run_id"] == "run_timecourse"
    assert [child["run_id"] for child in sidecar_rows[0]["child_processes"]] == [
        "run_nozzle",
        "run_focus",
        "run_emergence",
        "run_timecourse",
    ]


def test_stream_capture_discard_before_queue_start_only_writes_sidecar(tmp_path, monkeypatch):
    model, manager = _make_manager(tmp_path, num_flashes=75)
    monkeypatch.setattr(manager, "start_calibration_queue", lambda: None)

    ok, message = manager.start_stream_gravimetric_capture(0.0, rep_override=1, notes="discard me")
    assert (ok, message) == (True, "")
    assert str(manager.get_stream_gravimetric_capture_state()["status"]) == "running"

    discard_ok, discard_message = manager.discard_stream_gravimetric_capture()
    assert (discard_ok, discard_message) == (True, "")

    metadata_path = Path(model.experiment_model.experiment_dir_path) / "stream_metadata.csv"
    sidecar_path = Path(model.experiment_model.experiment_dir_path) / "stream_capture_log.jsonl"
    assert not metadata_path.exists()
    sidecar_rows = _read_jsonl_rows(sidecar_path)
    assert len(sidecar_rows) == 1
    assert sidecar_rows[0]["outcome"] == "discarded"
    assert sidecar_rows[0]["error_message"] == "operator_discarded"
    assert manager.get_stream_gravimetric_capture_state()["status"] == "idle"


@pytest.mark.parametrize(
    ("terminal_status", "error_message"),
    [
        ("error", "camera timeout"),
        ("stopped", "Calibration terminated by user"),
    ],
)
def test_stream_capture_terminal_sessions_write_only_sidecar(
    tmp_path,
    monkeypatch,
    terminal_status,
    error_message,
):
    model, manager = _make_manager(tmp_path, num_flashes=80)
    monkeypatch.setattr(manager, "start_calibration_queue", lambda: None)

    ok, message = manager.start_stream_gravimetric_capture(0.0, rep_override=1, notes="terminal")
    assert (ok, message) == (True, "")

    error_run = _write_run_dir(
        Path(model.experiment_model.experiment_dir_path) / "calibration_recordings",
        process_name="NozzlePositionCalibrationProcess",
        run_id="run_partial",
        phase_name="nozzle_position",
        settings_num_droplets=1,
        events=[
            _settings_event("settings_requested", 1, context="droplet"),
            _settings_event("settings_completed", 1, context="droplet"),
            _capture_result_event(stage_text="Partial droplet"),
        ],
    )
    manager._record_stream_capture_process_result(
        _make_recorded_process("NozzlePositionCalibrationProcess", "nozzle_position", error_run),
        outcome=terminal_status,
        error_message=error_message,
    )

    model.droplet_camera_model.num_flashes = 81
    manager._mark_stream_capture_terminal_state(
        status=terminal_status,
        error_message=error_message,
    )

    save_ok, save_message = manager.finalize_stream_gravimetric_capture(1.0)
    assert save_ok is False
    assert "not ready to save" in save_message.lower()

    metadata_path = Path(model.experiment_model.experiment_dir_path) / "stream_metadata.csv"
    sidecar_path = Path(model.experiment_model.experiment_dir_path) / "stream_capture_log.jsonl"
    assert not metadata_path.exists()
    sidecar_rows = _read_jsonl_rows(sidecar_path)
    assert len(sidecar_rows) == 1
    assert sidecar_rows[0]["outcome"] == terminal_status
    assert sidecar_rows[0]["error_message"] == error_message
    assert sidecar_rows[0]["printed_capture_count"] == 1


def test_stream_capture_panel_state_locks_manual_controls_and_suppresses_verdict(monkeypatch, qapp):
    dialog, manager = _build_view_dialog(monkeypatch, qapp)
    prompted = []

    monkeypatch.setattr(
        dialog,
        "_prompt_calibration_verdict",
        lambda *args, **kwargs: prompted.append({"args": args, "kwargs": kwargs}),
    )

    manager.record_mode_enabled = False
    dialog._sync_stream_capture_panel_state()
    assert dialog.stream_capture_begin_button.isEnabled() is False

    manager.record_mode_enabled = True
    dialog._sync_stream_capture_panel_state()
    assert dialog.stream_capture_begin_button.isEnabled() is True

    manager.state.update(
        {
            "status": "awaiting_mass",
            "status_message": "Imaging complete. Enter ending mass, review counts, and save the row.",
            "session_id": "stream_capture_demo",
            "timecourse_run_id": "run_timecourse_demo",
            "starting_flash": 100,
            "ending_flash": 113,
            "raw_flash_delta": 13,
            "background_capture_count": 2,
            "printed_capture_count": 11,
            "rep": 2,
            "suggested_rep": 2,
        }
    )
    manager.streamCaptureStateChanged.emit(dict(manager.state))
    qapp.processEvents()

    assert dialog.stream_capture_begin_button.isEnabled() is False
    assert dialog.stream_capture_save_button.isEnabled() is True
    assert dialog.stream_capture_discard_button.isEnabled() is True
    assert dialog.flash_duration_spinbox.isEnabled() is False
    assert dialog.calibrate_timecourse_button.isEnabled() is False
    assert dialog.record_calibration_checkbox.isEnabled() is False

    dialog.on_calibration_completed()

    assert manager.pending_clear_reasons == ["stream_capture_verdict_suppressed"]
    assert prompted == []
