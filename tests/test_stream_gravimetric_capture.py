import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.Model import (
    BaseCalibrationProcess,
    CalibrationManager,
    DropletTimecourseProcess,
    OnlineStreamCalibrationProcess,
)
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
        self.save_root_dir = None
        self.start_saving_calls = []
        self.stop_saving_calls = 0

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

    def get_save_root_directory(self):
        return self.save_root_dir

    def start_saving(self, **kwargs):
        self.start_saving_calls.append(dict(kwargs))
        root_dir = kwargs.get("root_dir") or self.save_root_dir or "."
        return str(Path(root_dir) / "droplet_timecourse_stub")

    def stop_saving(self):
        self.stop_saving_calls += 1


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
        return str(self.state.get("status") or "idle") in {
            "pending_gripper_refresh",
            "refreshing_gripper",
            "suspending_gripper_refresh",
            "running",
            "pending_loading_move",
            "moving_to_loading",
            "awaiting_mass_entry",
            "pending_gripper_restore",
            "restoring_gripper_refresh",
            "pending_camera_return",
            "returning_to_camera",
        }

    def should_suppress_process_verdict(self):
        return str(self.state.get("status") or "idle") in {
            "pending_gripper_refresh",
            "refreshing_gripper",
            "suspending_gripper_refresh",
            "running",
            "pending_loading_move",
            "moving_to_loading",
            "awaiting_mass_entry",
            "pending_gripper_restore",
            "restoring_gripper_refresh",
            "pending_camera_return",
            "returning_to_camera",
            "error",
            "stopped",
        }

    def clear_pending_process_verdict(self, *, reason=""):
        self.pending_clear_reasons.append(str(reason))


class _ViewControllerStub:
    def __init__(self, manager, model):
        self.manager = manager
        self.model = model
        self.moves = []
        self.stream_capture_start_calls = []
        self.refuel_pressure_steps = []
        self.refuel_only_calls = []
        self.print_only_calls = []
        self.print_droplet_calls = []
        self.refuel_pulse_width_updates = []
        self.gripper_refresh_calls = []
        self.gripper_param_updates = []
        self.auto_complete_moves = False

    def start_read_camera(self):
        return None

    def capture_droplet_image(self, throughput_mode=False):
        return None

    def stop_droplet_camera(self):
        return None

    def set_droplet_capture_profile(self, *args, **kwargs):
        return None

    def set_command_dispatch_interval(self, *args, **kwargs):
        return None

    def stop_read_camera(self):
        return None

    def disable_print_profile(self):
        return None

    def start_stream_gravimetric_capture(self, *args, **kwargs):
        self.stream_capture_start_calls.append({"args": args, "kwargs": dict(kwargs)})
        capture_mode = str(kwargs.get("capture_mode") or "timecourse")
        capture_process = (
            "OnlineStreamCalibrationProcess"
            if capture_mode == "online_stream"
            else "DropletTimecourseProcess"
        )
        self.manager.state["status"] = "pending_gripper_refresh"
        self.manager.state["status_message"] = "Refreshing gripper vacuum before stream gravimetric capture."
        self.manager.state["capture_mode"] = capture_mode
        self.manager.state["capture_process_name"] = capture_process
        self.manager.streamCaptureStateChanged.emit(dict(self.manager.state))
        return True, ""

    def begin_stream_gravimetric_capture_gripper_preamble(self):
        self.gripper_refresh_calls.append(bool(self.manager.state.get("gripper_was_open")))
        self.manager.state["status"] = "running"
        self.manager.state["status_message"] = "Running nozzle, focus, emergence, and stream capture sequence."
        self.manager.state["gripper_refresh_suspended"] = True
        self.manager.streamCaptureStateChanged.emit(dict(self.manager.state))
        return True, ""

    def finalize_stream_gravimetric_capture(self, ending_mass_mg, rep_override=None, notes=""):
        self.manager.state["status"] = "pending_gripper_restore"
        self.manager.state["ending_mass_mg"] = float(ending_mass_mg)
        self.manager.state["rep"] = int(rep_override or self.manager.state.get("rep") or 1)
        self.manager.state["notes"] = str(notes or "")
        self.manager.state["saved_dataset_name"] = str(
            self.manager.state.get("dataset_run_id")
            or self.manager.state.get("timecourse_run_id")
            or "run_timecourse_demo"
        )
        self.manager.state["session_outcome"] = "saved"
        self.manager.state["post_restore_action"] = "saved_camera_return"
        self.manager.state["gripper_refresh_suspended"] = True
        self.manager.state["status_message"] = "Restoring gripper auto-refresh settings before returning to camera."
        self.manager.streamCaptureStateChanged.emit(dict(self.manager.state))
        return True, ""

    def discard_stream_gravimetric_capture(self, reason="operator_discarded"):
        if str(self.manager.state.get("status") or "") == "awaiting_mass_entry":
            self.manager.state["status"] = "pending_gripper_restore"
            self.manager.state["status_message"] = "Discarding this run and restoring gripper auto-refresh settings."
            self.manager.state["session_outcome"] = "discarded"
            self.manager.state["post_restore_action"] = "discard_camera_return"
            self.manager.state["gripper_refresh_suspended"] = True
        else:
            self.manager.state["status"] = "idle"
            self.manager.state["status_message"] = "Discarded stream gravimetric capture."
        self.manager.streamCaptureStateChanged.emit(dict(self.manager.state))
        return True, ""

    def begin_stream_gravimetric_capture_gripper_restore(self):
        self.gripper_param_updates.append(
            (
                int(self.manager.state.get("gripper_refresh_period_snapshot_ms") or 25000),
                int(self.manager.state.get("gripper_pulse_duration_snapshot_ms") or 1500),
            )
        )
        action = str(self.manager.state.get("post_restore_action") or "")
        if action in {"saved_camera_return", "discard_camera_return"}:
            self.manager.state["status"] = "pending_camera_return"
        elif action == "terminal":
            self.manager.state["status"] = str(self.manager.state.get("session_outcome") or "error")
        else:
            self.manager.state["status"] = "idle"
        self.manager.state["gripper_refresh_suspended"] = False
        self.manager.streamCaptureStateChanged.emit(dict(self.manager.state))
        return True, ""

    def begin_stream_gravimetric_capture_loading_move(self):
        self.manager.state["status"] = "moving_to_loading"
        self.manager.state["status_message"] = "Moving printer head to loading position for mass measurement."
        self.manager.streamCaptureStateChanged.emit(dict(self.manager.state))
        return True, ""

    def on_stream_gravimetric_capture_loading_reached(self):
        self.manager.state["status"] = "awaiting_mass_entry"
        self.manager.state["status_message"] = "Loading position reached. Enter ending mass and inspect the printer head."
        self.manager.streamCaptureStateChanged.emit(dict(self.manager.state))
        return True, ""

    def begin_stream_gravimetric_capture_camera_return(self):
        self.manager.state["status"] = "returning_to_camera"
        self.manager.state["status_message"] = "Returning printer head to camera."
        self.manager.streamCaptureStateChanged.emit(dict(self.manager.state))
        return True, ""

    def on_stream_gravimetric_capture_camera_reached(self):
        self.manager.state.update(
            {
                "status": "idle",
                "status_message": "Saved stream metadata row for run_timecourse_demo. Ready to begin stream gravimetric capture.",
                "error_message": "",
                "session_id": None,
                "starting_mass_mg": 0.0,
                "ending_mass_mg": None,
                "starting_flash": None,
                "ending_flash": None,
                "raw_flash_delta": None,
                "background_capture_count": None,
                "printed_capture_count": None,
                "capture_mode": "timecourse",
                "capture_process_name": "DropletTimecourseProcess",
                "timecourse_run_id": None,
                "dataset_run_id": None,
                "dataset_process_name": None,
                "flow_fit_status": "",
                "tail_phase_status": "",
                "flow_rate_nl_per_us": None,
                "tail_start_delay_from_emergence_us": None,
                "predicted_stream_duration_us": None,
                "predicted_volume_nl": None,
                "analysis_warnings": [],
                "rep": 2,
                "suggested_rep": 2,
                "notes": "",
            }
        )
        self.manager.streamCaptureStateChanged.emit(dict(self.manager.state))
        return True, ""

    def report_stream_gravimetric_capture_move_failure(self, target, error_message=""):
        target = str(target or "")
        if target == "loading":
            self.manager.state["status"] = "pending_loading_move"
        elif target == "camera":
            self.manager.state["status"] = "pending_camera_return"
        self.manager.state["error_message"] = str(error_message or "")
        self.manager.streamCaptureStateChanged.emit(dict(self.manager.state))
        return True, ""

    def move_to_location(self, name, **kwargs):
        self.moves.append(str(name))
        on_complete = kwargs.get("on_complete")
        if self.auto_complete_moves and callable(on_complete):
            on_complete()
        return True

    def set_relative_refuel_pressure(self, pressure, manual=False):
        self.refuel_pressure_steps.append(float(pressure))

    def refuel_only(self, droplets):
        self.refuel_only_calls.append(int(droplets))

    def print_only(self, droplets):
        self.print_only_calls.append(int(droplets))

    def print_droplets(self, droplets):
        self.print_droplet_calls.append(int(droplets))

    def set_refuel_pulse_width(self, pulse_width, manual=False):
        self.refuel_pulse_width_updates.append(int(pulse_width))


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
        get_gripper_settings=lambda: (25000, 1500),
        gripper_refresh_period=25000,
        gripper_pulse_duration=1500,
        gripper_open=False,
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


def _make_timecourse_process(
    tmp_path,
    monkeypatch,
    *,
    save_camera_archive=False,
    print_pulse_width=3000,
):
    model, manager = _make_manager(tmp_path)
    model.machine_model.get_print_pulse_width = lambda: print_pulse_width
    manager.get_emergence_time = lambda quiet=True: 750
    manager.get_background_image = lambda: object()
    started = []
    monkeypatch.setattr(
        BaseCalibrationProcess,
        "start",
        lambda self: started.append(self),
    )
    proc = DropletTimecourseProcess(
        manager,
        model,
        save_camera_archive=save_camera_archive,
    )
    return model, manager, proc, started


def _start_stream_capture_with_gripper_suspend(manager):
    ok, message = manager.begin_stream_gravimetric_capture_gripper_refresh()
    assert (ok, message) == (True, "")
    ok, message = manager.begin_stream_gravimetric_capture_gripper_suspend()
    assert (ok, message) == (True, "")
    ok, message = manager.mark_stream_gravimetric_capture_gripper_suspended()
    assert (ok, message) == (True, "")


def _restore_stream_capture_gripper(manager):
    ok, message = manager.begin_stream_gravimetric_capture_gripper_restore()
    assert (ok, message) == (True, "")
    ok, message = manager.mark_stream_gravimetric_capture_gripper_restored()
    assert (ok, message) == (True, "")


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


def _online_stream_result_payload():
    return {
        "result": {
            "flow_phase": {
                "fit_status": "warning",
                "flow_rate_nl_per_us": 0.123456,
            },
            "tail_phase": {
                "status": "resolved",
                "tail_start_delay_from_emergence_us": 5200,
            },
            "predicted_stream_duration_us": 6400,
            "predicted_volume_nl": 0.7901,
            "warnings": ["tail advisory", "budget low"],
        }
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


def _build_view_dialog(monkeypatch, qapp, *, manager=None, model=None, controller=None):
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

    if manager is None:
        manager = _StreamCaptureManagerStub(
            {
                "status": "idle",
                "status_message": "Ready to begin stream gravimetric capture.",
                "error_message": "",
                "session_id": None,
                "starting_mass_mg": 0.0,
                "starting_flash": None,
                "ending_flash": None,
                "raw_flash_delta": None,
                "background_capture_count": None,
                "printed_capture_count": None,
                "capture_mode": "timecourse",
                "capture_process_name": "DropletTimecourseProcess",
                "timecourse_run_id": None,
                "dataset_run_id": None,
                "dataset_process_name": None,
                "flow_fit_status": "",
                "tail_phase_status": "",
                "flow_rate_nl_per_us": None,
                "tail_start_delay_from_emergence_us": None,
                "predicted_stream_duration_us": None,
                "predicted_volume_nl": None,
                "analysis_warnings": [],
                "rep": 1,
                "suggested_rep": 1,
                "notes": "",
            }
        )
    if model is None:
        model = SimpleNamespace(
            droplet_camera_model=_ViewDropletCameraModelStub(),
            calibration_manager=manager,
            machine_model=SimpleNamespace(
                get_print_pressure_bounds=lambda: (0.10, 5.00),
                get_print_pulse_width=lambda: 1400,
                get_refuel_pulse_width=lambda: 3000,
                get_current_print_pressure=lambda: 0.80,
                get_gripper_settings=lambda: (25000, 1500),
                gripper_refresh_period=25000,
                gripper_pulse_duration=1500,
                gripper_open=False,
            ),
            experiment_model=SimpleNamespace(experiment_dir_path="C:/tmp/example-experiment"),
        )
    if controller is None:
        controller = _ViewControllerStub(manager, model)
    dialog = DropletImagingDialog(SimpleNamespace(color_dict={}), model, controller)
    qapp.processEvents()
    return dialog, manager, controller


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
        started.append((proc_cls, dict(kwargs)))
        return True

    monkeypatch.setattr(manager, "_try_start_process", _capture_start)
    manager.calibration_queue = ["droplet_timecourse"]
    manager._stream_capture_state = {"status": "running"}

    manager.start_calibration_queue()

    assert started == [
        (
            DropletTimecourseProcess,
            {
                "_allow_stream_capture_session": True,
                "_stream_capture_queue_phase": "droplet_timecourse",
            },
        ),
    ]


def test_stream_capture_queue_can_start_online_stream_calibration(tmp_path, monkeypatch):
    _model, manager = _make_manager(tmp_path)
    started = []

    def _capture_start(proc_cls, *args, **kwargs):
        started.append((proc_cls, dict(kwargs)))
        return True

    monkeypatch.setattr(manager, "_try_start_process", _capture_start)
    manager.calibration_queue = ["online_stream_calibration"]
    manager._stream_capture_state = {"status": "running"}

    manager.start_calibration_queue()

    assert started == [
        (
            OnlineStreamCalibrationProcess,
            {
                "_allow_stream_capture_session": True,
                "_stream_capture_queue_phase": "online_stream_calibration",
            },
        ),
    ]


def test_stream_capture_gripper_suspend_can_launch_first_internal_queue_step(tmp_path, monkeypatch):
    _model, manager = _make_manager(tmp_path)

    class _QueueStartStubProcess:
        owns_calibration_memory_session = False
        supports_operator_verdict = False

        def __init__(self, calibration_manager, model, *args, **kwargs):
            self.calibration_manager = calibration_manager
            self.model = model
            self.args = args
            self.kwargs = dict(kwargs)
            self.stageChanged = SignalStub()
            self.calibrationCompleted = SignalStub()
            self.calibrationError = SignalStub()
            self.calibrationDataUpdated = SignalStub()
            self.presentImageSignal = SignalStub()
            self.started = False

        def start(self):
            self.started = True

        def stop(self):
            return None

    monkeypatch.setattr("CalibrationClasses.Model.NozzlePositionCalibrationProcess", _QueueStartStubProcess)

    ok, message = manager.start_stream_gravimetric_capture(0.0, rep_override=1, notes="queue launch")
    assert (ok, message) == (True, "")

    ok, message = manager.begin_stream_gravimetric_capture_gripper_refresh()
    assert (ok, message) == (True, "")
    ok, message = manager.begin_stream_gravimetric_capture_gripper_suspend()
    assert (ok, message) == (True, "")
    ok, message = manager.mark_stream_gravimetric_capture_gripper_suspended()
    assert (ok, message) == (True, "")

    assert isinstance(manager.activeCalibration, _QueueStartStubProcess)
    assert manager.activeCalibration.started is True
    assert manager.calibration_queue == list(manager._build_stream_capture_queue_for_mode("timecourse")[1:])
    assert manager.get_stream_gravimetric_capture_state()["status"] == "running"


def test_stream_capture_gripper_suspend_queues_online_stream_mode(tmp_path, monkeypatch):
    _model, manager = _make_manager(tmp_path)

    class _QueueStartStubProcess:
        owns_calibration_memory_session = False
        supports_operator_verdict = False

        def __init__(self, calibration_manager, model, *args, **kwargs):
            self.calibration_manager = calibration_manager
            self.model = model
            self.args = args
            self.kwargs = dict(kwargs)
            self.stageChanged = SignalStub()
            self.calibrationCompleted = SignalStub()
            self.calibrationError = SignalStub()
            self.calibrationDataUpdated = SignalStub()
            self.presentImageSignal = SignalStub()
            self.started = False

        def start(self):
            self.started = True

        def stop(self):
            return None

    monkeypatch.setattr("CalibrationClasses.Model.NozzlePositionCalibrationProcess", _QueueStartStubProcess)

    ok, message = manager.start_stream_gravimetric_capture(
        0.0,
        rep_override=1,
        notes="queue launch",
        capture_mode="online_stream",
    )
    assert (ok, message) == (True, "")

    ok, message = manager.begin_stream_gravimetric_capture_gripper_refresh()
    assert (ok, message) == (True, "")
    ok, message = manager.begin_stream_gravimetric_capture_gripper_suspend()
    assert (ok, message) == (True, "")
    ok, message = manager.mark_stream_gravimetric_capture_gripper_suspended()
    assert (ok, message) == (True, "")

    assert isinstance(manager.activeCalibration, _QueueStartStubProcess)
    assert manager.activeCalibration.started is True
    assert manager.calibration_queue == list(manager._build_stream_capture_queue_for_mode("online_stream")[1:])
    assert manager.get_stream_gravimetric_capture_state()["capture_mode"] == "online_stream"
    assert manager.get_stream_gravimetric_capture_state()["status"] == "running"


def test_start_droplet_timecourse_process_passes_camera_archive_flag(tmp_path, monkeypatch):
    _model, manager = _make_manager(tmp_path)
    started = []

    def _capture_start(proc_cls, *args, **kwargs):
        started.append((proc_cls, dict(kwargs)))
        return True

    monkeypatch.setattr(manager, "_try_start_process", _capture_start)

    manager.start_droplet_timecourse_process(save_camera_archive=True)

    assert started == [
        (DropletTimecourseProcess, {"save_camera_archive": True}),
    ]


def test_droplet_timecourse_skips_camera_archive_by_default(tmp_path, monkeypatch):
    model, _manager, proc, started = _make_timecourse_process(tmp_path, monkeypatch)

    proc.start()

    assert started == [proc]
    assert model.droplet_camera_model.start_saving_calls == []
    assert model.droplet_camera_model.stop_saving_calls == 0
    assert proc._camera_archive_enabled is False
    assert proc._save_dir is None

    proc.calibrationCompleted.emit()
    assert model.droplet_camera_model.stop_saving_calls == 0


@pytest.mark.parametrize("signal_name", ["calibrationCompleted", "calibrationError"])
def test_droplet_timecourse_camera_archive_can_be_opted_in(tmp_path, monkeypatch, signal_name):
    model, _manager, proc, started = _make_timecourse_process(
        tmp_path,
        monkeypatch,
        save_camera_archive=True,
    )
    model.droplet_camera_model.save_root_dir = str(tmp_path / "droplet_imager_captures")

    proc.start()

    assert started == [proc]
    assert len(model.droplet_camera_model.start_saving_calls) == 1
    assert model.droplet_camera_model.start_saving_calls[0]["root_dir"] == str(
        tmp_path / "droplet_imager_captures"
    )
    assert model.droplet_camera_model.start_saving_calls[0]["prefix"] == "droplet_timecourse"
    assert proc._camera_archive_enabled is True
    assert proc._save_dir is not None

    signal = getattr(proc, signal_name)
    if signal_name == "calibrationError":
        signal.emit("boom")
    else:
        signal.emit()

    assert model.droplet_camera_model.stop_saving_calls == 1
    assert proc._camera_archive_enabled is False
    assert proc._save_dir is None


@pytest.mark.parametrize(
    ("print_pulse_width", "expected_window_us"),
    [
        (1400, 6000),
        (3000, 6000),
        (3500, 6500),
        ("invalid", 6000),
        (None, 6000),
    ],
)
def test_droplet_timecourse_window_scales_with_print_pulse_width(
    tmp_path,
    monkeypatch,
    print_pulse_width,
    expected_window_us,
):
    _model, _manager, proc, _started = _make_timecourse_process(
        tmp_path,
        monkeypatch,
        print_pulse_width=print_pulse_width,
    )

    assert proc.window_us == expected_window_us
    assert proc.delays[0] == 700
    assert proc.delays[-1] == 700 + expected_window_us


def test_droplet_timecourse_prepare_stage_reports_derived_window(tmp_path, monkeypatch):
    _model, _manager, proc, _started = _make_timecourse_process(
        tmp_path,
        monkeypatch,
        print_pulse_width=3500,
    )
    messages = []
    proc.stageChanged.connect(messages.append)

    proc.onPrepare()

    assert any("window=6500 us" in message for message in messages)


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
    assert manager.get_stream_gravimetric_capture_state()["status"] == "pending_gripper_refresh"
    assert queued == []

    _start_stream_capture_with_gripper_suspend(manager)
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
    assert manager.get_stream_gravimetric_capture_state()["status"] == "pending_loading_move"

    move_ok, move_message = manager.begin_stream_gravimetric_capture_loading_move()
    assert (move_ok, move_message) == (True, "")
    reached_ok, reached_message = manager.mark_stream_gravimetric_capture_loading_reached()
    assert (reached_ok, reached_message) == (True, "")

    save_ok, save_message = manager.finalize_stream_gravimetric_capture(
        5.5,
        rep_override=3,
        notes="saved row",
    )
    assert (save_ok, save_message) == (True, "")
    save_state = manager.get_stream_gravimetric_capture_state()
    assert save_state["status"] == "pending_gripper_restore"
    assert save_state["session_outcome"] == "saved"

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
    assert rows[0]["Capture Mode"] == "timecourse"
    assert rows[0]["Capture Process"] == "DropletTimecourseProcess"
    assert rows[0]["Flow Fit Status"] == ""
    assert rows[0]["Tail Phase Status"] == ""
    assert rows[0]["Flow Rate (nL/us)"] == ""
    assert rows[0]["Tail Start From Emergence (us)"] == ""
    assert rows[0]["Predicted Stream Duration (us)"] == ""
    assert rows[0]["Predicted Volume (nL)"] == ""
    assert rows[0]["Analysis Warnings"] == ""

    sidecar_path = Path(model.experiment_model.experiment_dir_path) / "stream_capture_log.jsonl"
    sidecar_rows = _read_jsonl_rows(sidecar_path)
    assert len(sidecar_rows) == 1
    assert sidecar_rows[0]["outcome"] == "saved"
    assert sidecar_rows[0]["raw_flash_delta"] == 13
    assert sidecar_rows[0]["background_capture_count"] == 2
    assert sidecar_rows[0]["printed_capture_count"] == 11
    assert sidecar_rows[0]["dataset_run_id"] == "run_timecourse"
    assert sidecar_rows[0]["dataset_process_name"] == "DropletTimecourseProcess"
    assert sidecar_rows[0]["capture_mode"] == "timecourse"
    assert sidecar_rows[0]["timecourse_run_id"] == "run_timecourse"
    assert [child["run_id"] for child in sidecar_rows[0]["child_processes"]] == [
        "run_nozzle",
        "run_focus",
        "run_emergence",
        "run_timecourse",
    ]

    _restore_stream_capture_gripper(manager)
    assert manager.get_stream_gravimetric_capture_state()["status"] == "pending_camera_return"

    return_ok, return_message = manager.begin_stream_gravimetric_capture_camera_return()
    assert (return_ok, return_message) == (True, "")
    camera_ok, camera_message = manager.mark_stream_gravimetric_capture_camera_reached()
    assert (camera_ok, camera_message) == (True, "")
    final_state = manager.get_stream_gravimetric_capture_state()
    assert final_state["status"] == "idle"
    assert final_state["starting_mass_mg"] == 0.0


def test_stream_capture_finalize_online_mode_appends_metadata_and_sidecar(tmp_path, monkeypatch):
    model, manager = _make_manager(tmp_path, num_flashes=200)
    queued = []
    recordings_root = Path(model.experiment_model.experiment_dir_path) / "calibration_recordings"

    monkeypatch.setattr(
        manager,
        "start_calibration_queue",
        lambda: queued.append(list(manager.calibration_queue)),
    )

    ok, message = manager.start_stream_gravimetric_capture(
        1.0,
        rep_override=4,
        notes="online capture start",
        capture_mode="online_stream",
    )
    assert (ok, message) == (True, "")
    start_state = manager.get_stream_gravimetric_capture_state()
    assert start_state["capture_mode"] == "online_stream"
    assert start_state["capture_process_name"] == "OnlineStreamCalibrationProcess"

    _start_stream_capture_with_gripper_suspend(manager)
    expected_queue = list(manager._build_stream_capture_queue_for_mode("online_stream"))
    assert queued == [expected_queue]
    assert manager.calibration_queue == expected_queue

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
    online_run = _write_run_dir(
        recordings_root,
        process_name="OnlineStreamCalibrationProcess",
        run_id="run_online_stream",
        phase_name="online_stream_calibration",
        settings_num_droplets=1,
        events=[
            _settings_event("settings_requested", 0, context="online_stream_prepare_background"),
            _settings_event("settings_completed", 0, context="online_stream_prepare_background"),
            _capture_result_event(stage_text="Online stream background @ 4700 us", role="background"),
            _settings_event("settings_requested", 1, context="online_stream_apply_flow_delay_4800"),
            _settings_event("settings_completed", 1, context="online_stream_apply_flow_delay_4800"),
            _capture_result_event(stage_text="Online stream flow @ 4800 us"),
            _settings_event("settings_requested", 1, context="online_stream_apply_tail_delay_5200"),
            _settings_event("settings_completed", 1, context="online_stream_apply_tail_delay_5200"),
            _capture_result_event(stage_text="Online stream tail @ 5200 us"),
        ],
    )

    manager.activeCalibration = SimpleNamespace(phase_name="online_stream_calibration")
    manager.onCalibrationDataUpdated(_online_stream_result_payload())
    manager.activeCalibration = None

    for process_name, phase_name, run_dir in (
        ("NozzlePositionCalibrationProcess", "nozzle_position", nozzle_run),
        ("NozzleFocusCalibrationProcess", "nozzle_focus", focus_run),
        ("DropletEmergenceCalibrationProcess", "droplet_emergence", emergence_run),
        ("OnlineStreamCalibrationProcess", "online_stream_calibration", online_run),
    ):
        manager._record_stream_capture_process_result(
            _make_recorded_process(process_name, phase_name, run_dir),
            outcome="completed",
        )

    manager.calibration_queue = []
    model.droplet_camera_model.num_flashes = 214
    manager._complete_stream_capture_queue_success()
    assert manager.get_stream_gravimetric_capture_state()["status"] == "pending_loading_move"

    move_ok, move_message = manager.begin_stream_gravimetric_capture_loading_move()
    assert (move_ok, move_message) == (True, "")
    reached_ok, reached_message = manager.mark_stream_gravimetric_capture_loading_reached()
    assert (reached_ok, reached_message) == (True, "")

    save_ok, save_message = manager.finalize_stream_gravimetric_capture(
        4.5,
        rep_override=5,
        notes="saved online row",
    )
    assert (save_ok, save_message) == (True, "")
    save_state = manager.get_stream_gravimetric_capture_state()
    assert save_state["status"] == "pending_gripper_restore"
    assert save_state["session_outcome"] == "saved"
    assert save_state["dataset_run_id"] == "run_online_stream"
    assert save_state["dataset_process_name"] == "OnlineStreamCalibrationProcess"

    metadata_path = Path(model.experiment_model.experiment_dir_path) / "stream_metadata.csv"
    rows = _read_csv_rows(metadata_path)
    assert len(rows) == 1
    assert rows[0]["Dataset name"] == "run_online_stream"
    assert rows[0]["Rep"] == "5"
    assert rows[0]["Starting flash"] == "200"
    assert rows[0]["Ending flash"] == "214"
    assert rows[0]["Mass Change"] == "3.5"
    assert rows[0]["Num printed"] == "7"
    assert rows[0]["Mass/print"] == "0.5"
    assert rows[0]["Notes"] == "saved online row"
    assert rows[0]["Capture Mode"] == "online_stream"
    assert rows[0]["Capture Process"] == "OnlineStreamCalibrationProcess"
    assert rows[0]["Flow Fit Status"] == "warning"
    assert rows[0]["Tail Phase Status"] == "resolved"
    assert rows[0]["Flow Rate (nL/us)"] == "0.123456"
    assert rows[0]["Tail Start From Emergence (us)"] == "5200"
    assert rows[0]["Predicted Stream Duration (us)"] == "6400"
    assert rows[0]["Predicted Volume (nL)"] == "0.7901"
    assert rows[0]["Analysis Warnings"] == "tail advisory; budget low"

    sidecar_path = Path(model.experiment_model.experiment_dir_path) / "stream_capture_log.jsonl"
    sidecar_rows = _read_jsonl_rows(sidecar_path)
    assert len(sidecar_rows) == 1
    assert sidecar_rows[0]["outcome"] == "saved"
    assert sidecar_rows[0]["raw_flash_delta"] == 14
    assert sidecar_rows[0]["background_capture_count"] == 3
    assert sidecar_rows[0]["printed_capture_count"] == 7
    assert sidecar_rows[0]["dataset_run_id"] == "run_online_stream"
    assert sidecar_rows[0]["dataset_process_name"] == "OnlineStreamCalibrationProcess"
    assert sidecar_rows[0]["capture_mode"] == "online_stream"
    assert sidecar_rows[0]["timecourse_run_id"] is None
    assert sidecar_rows[0]["flow_fit_status"] == "warning"
    assert sidecar_rows[0]["tail_phase_status"] == "resolved"
    assert sidecar_rows[0]["flow_rate_nl_per_us"] == pytest.approx(0.123456)
    assert sidecar_rows[0]["tail_start_delay_from_emergence_us"] == 5200
    assert sidecar_rows[0]["predicted_stream_duration_us"] == 6400
    assert sidecar_rows[0]["predicted_volume_nl"] == pytest.approx(0.7901)
    assert sidecar_rows[0]["analysis_warnings"] == ["tail advisory", "budget low"]
    assert [child["run_id"] for child in sidecar_rows[0]["child_processes"]] == [
        "run_nozzle",
        "run_focus",
        "run_emergence",
        "run_online_stream",
    ]

    _restore_stream_capture_gripper(manager)
    assert manager.get_stream_gravimetric_capture_state()["status"] == "pending_camera_return"


def test_stream_capture_discard_before_queue_start_only_writes_sidecar(tmp_path, monkeypatch):
    model, manager = _make_manager(tmp_path, num_flashes=75)
    monkeypatch.setattr(manager, "start_calibration_queue", lambda: None)

    ok, message = manager.start_stream_gravimetric_capture(0.0, rep_override=1, notes="discard me")
    assert (ok, message) == (True, "")
    assert str(manager.get_stream_gravimetric_capture_state()["status"]) == "pending_gripper_refresh"

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


def test_stream_capture_gripper_preamble_failure_blocks_queue_start(tmp_path, monkeypatch):
    _model, manager = _make_manager(tmp_path, num_flashes=75)
    queued = []
    monkeypatch.setattr(manager, "start_calibration_queue", lambda: queued.append(list(manager.calibration_queue)))

    ok, message = manager.start_stream_gravimetric_capture(0.0, rep_override=1, notes="preamble fail")
    assert (ok, message) == (True, "")
    assert manager.get_stream_gravimetric_capture_state()["status"] == "pending_gripper_refresh"

    ok, message = manager.begin_stream_gravimetric_capture_gripper_refresh()
    assert (ok, message) == (True, "")
    fail_ok, fail_message = manager.report_stream_gravimetric_capture_gripper_preamble_failure(
        "Failed to send gripper auto-refresh pause command.",
    )
    assert (fail_ok, fail_message) == (True, "")
    assert queued == []
    assert manager.get_stream_gravimetric_capture_state()["status"] == "error"


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
    _start_stream_capture_with_gripper_suspend(manager)

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
    assert manager.get_stream_gravimetric_capture_state()["status"] == "pending_gripper_restore"

    _restore_stream_capture_gripper(manager)
    assert manager.get_stream_gravimetric_capture_state()["status"] == terminal_status

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


def test_stream_capture_online_run_count_replay_uses_background_and_printed_events(tmp_path):
    _model, manager = _make_manager(tmp_path)
    recordings_root = Path(manager.model.experiment_model.experiment_dir_path) / "calibration_recordings"
    online_run = _write_run_dir(
        recordings_root,
        process_name="OnlineStreamCalibrationProcess",
        run_id="run_online_stream_counts",
        phase_name="online_stream_calibration",
        settings_num_droplets=1,
        events=[
            _settings_event("settings_requested", 0, context="online_stream_prepare_background"),
            _settings_event("settings_completed", 0, context="online_stream_prepare_background"),
            _capture_result_event(stage_text="Online stream background @ 4700 us", role="background"),
            _settings_event("settings_requested", 1, context="online_stream_apply_flow_delay_4800"),
            _settings_event("settings_completed", 1, context="online_stream_apply_flow_delay_4800"),
            _capture_result_event(stage_text="Online stream flow @ 4800 us"),
            _settings_event("settings_requested", 1, context="online_stream_apply_tail_delay_5200"),
            _settings_event("settings_completed", 1, context="online_stream_apply_tail_delay_5200"),
            _capture_result_event(stage_text="Online stream tail @ 5200 us"),
        ],
    )

    counts = manager._derive_stream_capture_counts_for_run(str(online_run))

    assert counts["background_capture_count"] == 1
    assert counts["printed_capture_count"] == 2
    assert counts["printed_capture_event_count"] == 2


@pytest.mark.parametrize(
    ("checked", "expected_mode", "expected_process"),
    [
        (False, "timecourse", "DropletTimecourseProcess"),
        (True, "online_stream", "OnlineStreamCalibrationProcess"),
    ],
)
def test_stream_capture_begin_uses_selected_capture_mode(
    monkeypatch,
    qapp,
    checked,
    expected_mode,
    expected_process,
):
    dialog, manager, controller = _build_view_dialog(monkeypatch, qapp)

    dialog.stream_capture_online_mode_checkbox.setChecked(checked)
    dialog.stream_capture_starting_mass_spin.setValue(1.25)
    dialog.stream_capture_rep_spin.setValue(3)
    dialog.stream_capture_notes_edit.setPlainText("mode select")

    dialog.begin_stream_gravimetric_capture()
    qapp.processEvents()

    assert controller.stream_capture_start_calls[-1]["kwargs"]["capture_mode"] == expected_mode
    assert manager.state["capture_mode"] == expected_mode
    assert manager.state["capture_process_name"] == expected_process


def test_stream_capture_popup_discard_returns_to_camera_without_saving(monkeypatch, qapp):
    dialog, manager, controller = _build_view_dialog(monkeypatch, qapp)

    manager.state.update(
        {
            "status": "awaiting_mass_entry",
            "status_message": "Loading position reached. Enter ending mass and inspect the printer head.",
            "session_id": "stream_capture_discard_popup",
            "timecourse_run_id": "run_discard_demo",
            "starting_flash": 100,
            "ending_flash": 111,
            "raw_flash_delta": 11,
            "background_capture_count": 1,
            "printed_capture_count": 10,
            "rep": 3,
            "suggested_rep": 3,
            "notes": "discard me",
            "gripper_refresh_period_snapshot_ms": 25000,
            "gripper_pulse_duration_snapshot_ms": 1500,
            "gripper_refresh_suspended": True,
        }
    )
    manager.streamCaptureStateChanged.emit(dict(manager.state))
    qapp.processEvents()

    assert dialog._stream_capture_mass_dialog is not None
    dialog._stream_capture_mass_dialog.discard_button.click()
    qapp.processEvents()

    assert controller.moves[-1] == "camera"
    assert manager.state["status"] == "returning_to_camera"

    controller.on_stream_gravimetric_capture_camera_reached()
    qapp.processEvents()

    assert manager.state["status"] == "idle"
    assert dialog.stream_capture_starting_mass_spin.value() == pytest.approx(0.0)


def test_stream_capture_popup_click_away_restores_shortcuts(monkeypatch, qapp):
    dialog, manager, controller = _build_view_dialog(monkeypatch, qapp)

    manager.state.update(
        {
            "status": "awaiting_mass_entry",
            "status_message": "Loading position reached. Enter ending mass and inspect the printer head.",
            "session_id": "stream_capture_focus_demo",
            "timecourse_run_id": "run_focus_demo",
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

    popup = dialog._stream_capture_mass_dialog
    assert popup is not None
    assert popup.isVisible() is True
    assert popup.ending_mass_spin.hasFocus() is False

    popup.ending_mass_spin.setFocus()
    qapp.processEvents()
    assert popup.ending_mass_spin.hasFocus() is True

    popup.ending_mass_spin.lineEdit().setText("5.5")
    QTest.mouseClick(popup.summary_label, Qt.LeftButton)
    qapp.processEvents()
    assert popup.ending_mass_spin.hasFocus() is False
    assert popup.ending_mass_spin.value() == pytest.approx(5.5)

    QTest.keyClick(popup, Qt.Key_Equal)
    QTest.keyClick(popup, Qt.Key_1)
    qapp.processEvents()
    assert controller.refuel_pulse_width_updates[-1] == 3500
    assert controller.refuel_pressure_steps[-1] == -1.0


def test_stream_capture_online_summary_uses_generic_dataset_labels(monkeypatch, qapp):
    dialog, manager, _controller = _build_view_dialog(monkeypatch, qapp)

    manager.state.update(
        {
            "status": "awaiting_mass_entry",
            "status_message": "Loading position reached. Enter ending mass and inspect the printer head.",
            "session_id": "stream_capture_online_demo",
            "capture_mode": "online_stream",
            "capture_process_name": "OnlineStreamCalibrationProcess",
            "dataset_run_id": "run_online_demo",
            "dataset_process_name": "OnlineStreamCalibrationProcess",
            "starting_flash": 200,
            "ending_flash": 214,
            "raw_flash_delta": 14,
            "background_capture_count": 3,
            "printed_capture_count": 7,
            "rep": 5,
            "suggested_rep": 5,
            "notes": "online summary",
            "flow_fit_status": "warning",
            "tail_phase_status": "resolved",
            "flow_rate_nl_per_us": 0.123456,
            "tail_start_delay_from_emergence_us": 5200,
            "predicted_stream_duration_us": 6400,
            "predicted_volume_nl": 0.7901,
            "analysis_warnings": ["tail advisory"],
        }
    )
    manager.streamCaptureStateChanged.emit(dict(manager.state))
    qapp.processEvents()

    panel_text = dialog.stream_capture_summary_label.text()
    assert "Capture Run: run_online_demo | Mode: online_stream | Process: OnlineStreamCalibrationProcess" in panel_text
    assert "Timecourse:" not in panel_text
    assert "Flow fit: warning | Tail: resolved" in panel_text
    assert "Warnings: tail advisory" in panel_text

    popup = dialog._stream_capture_mass_dialog
    assert popup is not None
    popup_text = popup.summary_label.text()
    assert "Capture Run: run_online_demo" in popup_text
    assert "Mode: online_stream | Process: OnlineStreamCalibrationProcess" in popup_text
    assert "Flow rate: 0.123456 nL/us" in popup_text
    assert "Tail start: 5200 us" in popup_text
    assert "Duration: 6400 us" in popup_text
    assert "Volume: 0.7901 nL" in popup_text
    assert "Timecourse:" not in popup_text


def test_stream_capture_panel_state_locks_manual_controls_and_suppresses_verdict(monkeypatch, qapp):
    dialog, manager, controller = _build_view_dialog(monkeypatch, qapp)
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
    assert dialog.stream_capture_online_mode_checkbox.isEnabled() is True
    assert dialog.control_panel_scroll.widget() is dialog.control_panel

    dialog.on_readiness_changed(
        {
            "online_stream_calibration": {
                "ready": False,
                "missing": ["Emergence time"],
            }
        }
    )

    manager.state.update(
        {
            "status": "awaiting_mass_entry",
            "status_message": "Loading position reached. Enter ending mass and inspect the printer head.",
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
    assert dialog.stream_capture_discard_button.isEnabled() is True
    assert dialog.flash_duration_spinbox.isEnabled() is False
    assert dialog.calibrate_timecourse_button.isEnabled() is False
    assert dialog.calibrate_online_stream_button.isEnabled() is False
    assert dialog.record_calibration_checkbox.isEnabled() is False
    assert dialog.stream_capture_online_mode_checkbox.isEnabled() is False
    assert dialog._stream_capture_mass_dialog is not None
    assert dialog._stream_capture_mass_dialog.isVisible() is True

    dialog.on_calibration_completed()

    assert manager.pending_clear_reasons == ["stream_capture_verdict_suppressed"]
    assert prompted == []

    dialog._stream_capture_mass_dialog.ending_mass_spin.setValue(5.5)
    QTest.keyClick(dialog._stream_capture_mass_dialog, Qt.Key_Equal)
    QTest.keyClick(dialog._stream_capture_mass_dialog, Qt.Key_1)
    qapp.processEvents()
    assert controller.refuel_pulse_width_updates[-1] == 3500
    assert controller.refuel_pressure_steps[-1] == -1.0

    dialog._stream_capture_mass_dialog.complete_button.click()
    qapp.processEvents()
    assert "camera" in controller.moves

    controller.on_stream_gravimetric_capture_camera_reached()
    qapp.processEvents()

    manager.state.update(
        {
            "status": "idle",
            "status_message": "Ready to begin stream gravimetric capture.",
            "error_message": "",
        }
    )
    manager.streamCaptureStateChanged.emit(dict(manager.state))
    qapp.processEvents()

    assert dialog.calibrate_online_stream_button.isEnabled() is False
    assert "Emergence time" in dialog.calibrate_online_stream_button.toolTip()
    assert dialog.stream_capture_begin_button.isEnabled() is True
    assert dialog.stream_capture_online_mode_checkbox.isEnabled() is True
    assert dialog.stream_capture_starting_mass_spin.value() == pytest.approx(0.0)


def test_stream_capture_pending_mass_entry_restores_after_dialog_reopen(monkeypatch, qapp):
    dialog, manager, controller = _build_view_dialog(monkeypatch, qapp)

    manager.state.update(
        {
            "status": "awaiting_mass_entry",
            "status_message": "Loading position reached. Enter ending mass and inspect the printer head.",
            "session_id": "stream_capture_restore",
            "timecourse_run_id": "run_restore_demo",
            "starting_flash": 100,
            "ending_flash": 111,
            "raw_flash_delta": 11,
            "background_capture_count": 1,
            "printed_capture_count": 10,
            "rep": 4,
            "suggested_rep": 4,
            "notes": "restore me",
        }
    )
    manager.streamCaptureStateChanged.emit(dict(manager.state))
    qapp.processEvents()

    assert dialog._stream_capture_mass_dialog is not None
    dialog.close()
    qapp.processEvents()
    assert manager.get_stream_gravimetric_capture_state()["status"] == "awaiting_mass_entry"

    reopened, _, _ = _build_view_dialog(
        monkeypatch,
        qapp,
        manager=manager,
        model=controller.model,
        controller=controller,
    )
    qapp.processEvents()

    assert reopened._stream_capture_mass_dialog is not None
    assert reopened._stream_capture_mass_dialog.isVisible() is True
