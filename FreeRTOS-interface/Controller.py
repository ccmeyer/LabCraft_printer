from PySide6.QtCore import QObject, Signal
from PySide6 import QtCore
from serial.tools.list_ports import comports
from Model import Model,PrinterHead,Slot
from dfu_update import reset_board
from dfu_update_worker import DfuUpdateWorker
from pathlib import Path
from datetime import datetime, timezone

import time
import numpy as np
import os
import serial
import math
import json
import uuid
import inspect

from hardware.profile import CURRENT_PROFILE, HardwareProfile
from hardware.null_devices import NullCamera

ARRAY_PAUSE_DEPARTURE_ACCEL = 32000
ARRAY_PAUSE_DEPARTURE_SETTLE_MS = 200
ARRAY_AXIS_ACCEL_DEFAULT = 140000
ARRAY_PRINT_SERPENTINE = True
ARRAY_GENTLE_ACCEL_ENABLED = False
ARRAY_ROW_START_OVERSHOOT_STEPS = 0

class Controller(QObject):
    """Controller class for the application."""
    array_complete = Signal()
    array_state_changed = Signal(str)
    update_slots_signal = Signal()
    update_volumes_in_view_signal = Signal()
    error_occurred_signal = Signal(str,str)

    # DFU signals
    dfu_progress = QtCore.Signal(int)
    dfu_stage    = QtCore.Signal(str)
    dfu_finished = QtCore.Signal(bool, str)
    dfu_output   = QtCore.Signal(str)

    # Qualification run signals
    qualification_stage = QtCore.Signal(str)
    qualification_output = QtCore.Signal(str)
    qualification_prompt = QtCore.Signal(str)
    qualification_selftest_event = QtCore.Signal(object)
    qualification_campaign_event = QtCore.Signal(object)
    qualification_finished = QtCore.Signal(bool, str, object)

    # Preprogrammed sequence signals
    sequence_state_changed = QtCore.Signal(str)         # "idle" | "countdown" | "running"
    sequence_countdown_s   = QtCore.Signal(float)       # seconds remaining
    sequence_started       = QtCore.Signal(str)         # seq_id
    sequence_completed     = QtCore.Signal(str)         # seq_id
    sequence_error         = QtCore.Signal(str)         # message

    def __init__(
        self,
        machine,
        model,
        profile: HardwareProfile = CURRENT_PROFILE,
        monotonic_fn=None,
        timer_factory=None,
    ):
        super().__init__()

        self.machine = machine
        self.model = model
        self.profile = profile
        self._monotonic_fn = monotonic_fn or time.monotonic
        self._timer_factory = timer_factory or (lambda parent: QtCore.QTimer(parent))
        self.balance = None  # to be set for legacy if needed
        self._port_info = {}  # device -> ListPortInfo

        self.expected_position = self.model.machine_model.get_current_position_dict()
        self.expected_location = self.model.machine_model.get_current_location()

        self._dfu_thread: DfuUpdateWorker | None = None
        self._qualification_worker = None

        # Defaults; tweak if you keep them elsewhere
        self._dfu_script = Path(__file__).resolve().parent / "dfu_update.py"
        self._bin_path   = Path("/home/labcraft/LabCraft_printer/firmware/freeRTOS_LabCraft.bin")
        self._boot_chip  = "gpiochip0"; self._boot_off = 24
        self._rst_chip   = "gpiochip0"; self._rst_off  = 23
        self._cwd        = None  # or Path("/home/labcraft/LabCraft_printer")

        self._ui_dir = Path(__file__).resolve().parent              # LabCraft_Printer/FreeRTOS-interface
        self._repo_root = self._ui_dir.parent                       # LabCraft_Printer
        self._reset_report_log_path = self._repo_root / "logs" / "board_reset_reports.jsonl"

        self._dfu_script = (self._ui_dir / "dfu_update.py").resolve()
        self._cwd = self._repo_root                                 # IMPORTANT: run child from repo root

        self._bin_path_current = (self._repo_root / "firmware" / "artifacts"/ "LabCraft_firmware.bin").resolve()
        self._bin_path_legacy  = (self._repo_root / "firmware" / "freeRTOS_LabCraft_legacy.bin").resolve()

        # This variable will temporarily hold the callback for the next capture.
        self.pending_capture_callback = None
        self.pending_capture_context = None
        self.pending_capture_active = False
        self.pending_capture_started_monotonic = None
        self.pending_capture_timeout_ms = 8_000
        self.pending_capture_throughput_timeout_ms = 1_500
        self.pending_capture_guard_timer = None
        self.pending_capture_request_id = None
        self.pending_capture_recovery_attempted = False
        self.pending_capture_throughput_mode = False
        self.last_capture_queue_rejection_reason = None
        self.last_capture_queue_rejection_state = None

        self._array_state = "idle"
        self._array_context = None

        # Connect the machine's signals to the controller's handlers
        self.machine.status_updated.connect(self.handle_status_update)
        self.machine.error_occurred.connect(self.handle_error)
        self.machine.homing_completed.connect(self.home_complete_handler)
        self.machine.gripper_open.connect(self.model.machine_model.open_gripper)
        self.machine.gripper_closed.connect(self.model.machine_model.close_gripper)
        
        self.machine.machine_connected_signal.connect(self.update_machine_connection_status)
        self.machine.reset_report_received.connect(self.handle_reset_report)
        self.machine.disconnect_complete_signal.connect(self.reset_board)
        self.machine.flash_state_updated.connect(self.model.update_flash_session_state)
        self.model.machine_model.command_numbers_updated.connect(self.update_command_numbers)
        self.machine.command_queue.commands_completed.connect(self.update_expected_with_current)

        # self.machine.balance.balance_mass_updated_signal.connect(self.model.calibration_model.update_mass)
        self.machine.all_calibration_droplets_printed.connect(self.start_mass_stabilization_timer)

        self.model.printer_head_manager.volume_changed_signal.connect(self.update_volumes_in_view)
        
        self.connect_droplet_camera_signals()
        # self.model.calibration_manager.captureImageRequested.connect(self.handle_capture_request)
        # self.model.calibration_manager.moveRequested.connect(self.handle_move_request)
        # self.model.calibration_manager.moveAbsoluteRequested.connect(self.handle_absolute_move_request)
        # # self.model.calibration_manager.dropletChangeRequested.connect(self.handle_droplet_change_request)
        # self.model.calibration_manager.changeSettingsRequested.connect(self.handle_settings_change_request)
        # self.machine.droplet_camera.image_captured_signal.connect(self._on_image_captured)

        # --- Preprogrammed sequences runner ---
        self._seq_state   = "idle"
        self._seq_id      = None
        self._seq_params  = {}
        self._seq_deadline_monotonic = 0.0

        self._seq_timer = self._timer_factory(self)
        self._seq_timer.setInterval(100)  # 10 Hz countdown updates
        self._seq_timer.timeout.connect(self._on_seq_tick)

        # Detect end-of-sequence when queue drains
        self.machine.command_queue.commands_completed.connect(self._on_commands_completed_for_sequence)

        # Registry of available sequences
        self._sequence_builders = {
            "pickup_slot_imager_return": self._seq_pickup_slot_imager_return,
            "led_on_wait_off":           self._seq_led_on_wait_off,
            "imager_plate_imager":       self._seq_imager_plate_imager,
            "snake_grid_droplet_print": self._seq_snake_grid_droplet_print,
            "droplet_walk_y": self._seq_droplet_walk_y,
            "bridge_and_pull_y": self._seq_bridge_and_pull_y,
            "bridge_pull_y_3step": self._seq_bridge_pull_y_3step,
        }

    def connect_droplet_camera_signals(self):
        """Connect the droplet camera signals to the controller."""
        self.model.calibration_manager.captureImageRequested.connect(self.handle_capture_request)
        self.model.calibration_manager.moveRequested.connect(self.handle_move_request)
        self.model.calibration_manager.moveAbsoluteRequested.connect(self.handle_absolute_move_request)
        self.model.calibration_manager.changeSettingsRequested.connect(self.handle_settings_change_request)
        try:
            camera = self.machine.droplet_camera
            phase_signal = getattr(camera, "capture_phase_signal", None)
            if phase_signal is not None:
                self._connect_qt_signal(phase_signal, self._on_camera_capture_phase, queued=True)
            completion_signal = getattr(camera, "capture_completed_signal", None)
            if completion_signal is not None:
                self._connect_qt_signal(completion_signal, self._on_capture_completed_payload, queued=True)
            else:
                self._connect_qt_signal(camera.image_captured_signal, self._on_image_captured, queued=True)
                self._connect_qt_signal(camera.capture_failed_signal, self._on_capture_failed, queued=True)
        except AttributeError:
            print("Droplet camera not initialized or image_captured_signal not available.")
    
    def disconnect_droplet_camera_signals(self):
        try:
            self.model.calibration_manager.captureImageRequested.disconnect(self.handle_capture_request)
            self.model.calibration_manager.moveRequested.disconnect(self.handle_move_request)
            self.model.calibration_manager.moveAbsoluteRequested.disconnect(self.handle_absolute_move_request)
            self.model.calibration_manager.changeSettingsRequested.disconnect(self.handle_settings_change_request)
        except Exception:
            pass
        try:
            camera = self.machine.droplet_camera
            phase_signal = getattr(camera, "capture_phase_signal", None)
            if phase_signal is not None:
                phase_signal.disconnect(self._on_camera_capture_phase)
            completion_signal = getattr(camera, "capture_completed_signal", None)
            if completion_signal is not None:
                completion_signal.disconnect(self._on_capture_completed_payload)
            image_signal = getattr(camera, "image_captured_signal", None)
            if image_signal is not None:
                image_signal.disconnect(self._on_image_captured)
            fail_signal = getattr(camera, "capture_failed_signal", None)
            if fail_signal is not None:
                fail_signal.disconnect(self._on_capture_failed)
        except Exception:
            pass

    @staticmethod
    def _queued_connection_type():
        qt = getattr(QtCore, "Qt", None)
        connection = getattr(qt, "QueuedConnection", None)
        if connection is not None:
            return connection
        connection_type = getattr(qt, "ConnectionType", None)
        return getattr(connection_type, "QueuedConnection", None)

    def _connect_qt_signal(self, signal, slot, *, queued=False):
        if queued:
            connection = self._queued_connection_type()
            if connection is not None:
                try:
                    signal.connect(slot, connection)
                    return
                except TypeError:
                    pass
        signal.connect(slot)

    def handle_status_update(self, status_dict):
        """Handle the status update and update the machine model."""
        self.model.update_state(status_dict)
        context = getattr(self, "_array_context", None) or {}
        if (
            self.get_array_run_state() == "stop_requested"
            and context.get("soft_stop_pending")
            and context.get("soft_stop_phase", "waiting_watermark") == "waiting_watermark"
            and self.model.machine_model.pause_watermark_reached
            and self.model.machine_model.transport_paused
        ):
            self._begin_soft_stop_clear_and_park()

    def handle_error(self, error_message):
        """Handle errors from the machine."""
        #print(f"Error occurred: {error_message}")
        self.error_occurred_signal.emit('Error Occurred',error_message)

    def update_command_numbers(self):
        """Pass the current command and last completed command to the command queue"""
        self.machine.update_command_numbers(*self.model.machine_model.get_command_numbers())
    
    def update_volumes_in_view(self):
        """Update the volume in the view."""
        self.update_volumes_in_view_signal.emit()

    def set_axis_maxspeed(self, axis_idx, max_speed):
        """Set the maximum speed for a specific axis."""
        self.machine.set_axis_maxspeed(axis_idx, max_speed)

    def set_axis_accel(self, axis_idx, accel, handler=None, kwargs=None, manual=False):
        """Set the acceleration for a specific axis."""
        if handler is None and kwargs is None and manual is False:
            return self.machine.set_axis_accel(axis_idx, accel)
        if kwargs is None and manual is False:
            return self.machine.set_axis_accel(axis_idx, accel, handler=handler)
        return self.machine.set_axis_accel(axis_idx, accel, handler=handler, kwargs=kwargs, manual=manual)

    def reset_board(self):
        """Reset the machine board."""
        self.machine.reset_board()
        self.model.machine_model.disconnect_machine()
    
    def update_available_ports(self):
        ports = []
        self._port_info = {}

        for p in comports():
            dev = p.device  # e.g. "COM3" on Windows, "/dev/ttyACM0" on Linux
            if not dev:
                continue
            if "ttyAMA" in dev:  # keep your Pi filter
                continue

            ports.append(dev)
            self._port_info[dev] = p

        self.model.machine_model.update_ports(ports)

    def _classify_port(self, port: str) -> str | None:
            """
            Return "mcu", "balance", or None (unknown).
            Uses cached comports metadata if available.
            """
            info = self._port_info.get(port)
            if info is None:
                # refresh metadata if needed
                for p in comports():
                    if p.device == port:
                        info = p
                        break
            print(f"Classifying port {port} with info: {info}")
            if info is None:
                return None

            vid = getattr(info, "vid", None)
            desc = (getattr(info, "description", "") or "").lower()
            manuf = (getattr(info, "manufacturer", "") or "").lower()

            # MCU heuristics
            if vid == 0x0483 or "CP210" in desc or "stm" in desc or "stmicro" in manuf:
                return "mcu"

            # Balance heuristics (best-effort)
            if any(k in desc for k in ("prolific", "balance", "scale", "ohaus", "sartorius", "mettler", "toledo")):
                return "balance"

            return None

    @QtCore.Slot(str)
    def connect_machine(self, port: str):
        kind = self._classify_port(port)
        if kind == "balance":
            self.error_occurred_signal.emit(
                "Connection Error", f"Port {port} looks like the BALANCE/scale, not the MCU. Please choose the MCU port."
            )
            return
        self.machine.connect_board(port)

    def disconnect_machine(self):
        """Disconnect from the machine."""
        self.machine.disconnect_board()
    # @QtCore.Slot()
    # def disconnect_machine(self):
    #     # self.machine.reset_board()
    #     # try:
    #     #     if getattr(self.machine, "ser", None):
    #     #         self.machine.ser.close()
    #     # except Exception:
    #     #     pass
    #     self.model.machine_model.disconnect_machine()

    @QtCore.Slot(str)
    def connect_balance(self, port: str):
        if self.balance is None:
            self.error_occurred_signal.emit("Connection Error","Balance support is not enabled in this build/profile.")
            return

        kind = self._classify_port(port)
        if kind == "mcu":
            self.error_occurred_signal.emit(
               "Connection Error", f"Port {port} looks like the MCU, not the balance. Please choose the balance port."
            )
            return

        self.balance.connect_balance(port)

    @QtCore.Slot()
    def disconnect_balance(self):
        if self.balance:
            self.balance.close_connection()
        self.model.machine_model.disconnect_balance()


    def update_machine_connection_status(self, status):
        """Update the machine connection status."""
        if status:
            print("Controller: Machine connected successfully.")
            self.model.machine_model.connect_machine()
        else:
            print("Controller: Failed to connect to the machine.")
            self.model.machine_model.disconnect_machine()

    def handle_reset_report(self, report: dict):
        self.model.machine_model.recover_after_board_reset()
        self.expected_position = self.model.machine_model.get_current_position_dict()
        self.expected_location = None
        log_path = self._append_reset_report_log(report)
        summary = report.get("summary", "Board reset detected.")
        message = f"{summary}\n\nSaved to: {log_path}"
        self.error_occurred_signal.emit("Board Reset Detected", message)

    def _append_reset_report_log(self, report: dict) -> str:
        path = Path(getattr(self, "_reset_report_log_path", Path("logs") / "board_reset_reports.jsonl"))
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "host_time_utc": datetime.now(timezone.utc).isoformat(),
            "report": dict(report),
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
        return str(path)

    def get_machine_port(self):
        """Get the currently connected machine port."""
        return self.machine.get_machine_port()

    # def connect_balance(self, port):
    #     """Connect to the microbalance."""
    #     if self.machine.connect_balance(port):
    #         # Update the model state
    #         self.model.machine_model.connect_balance(port)
    
    # def disconnect_balance(self):
    #     """Disconnect from the balance."""
    #     self.machine.disconnect_balance()
    #     self.model.machine_model.disconnect_balance()

    # def update_firmware(self, bin_path: str):
    #     self.machine.update_firmware(bin_path)

    def start_firmware_update(self,manual: bool=False):
        print("[Controller] Starting firmware update..., manual mode =", manual)
        if self._dfu_thread and self._dfu_thread.isRunning():
            return  # already running

        # bin_path = self._bin_path_legacy if manual else self._bin_path_current
        bin_path = self._bin_path_current

        self._dfu_thread = DfuUpdateWorker(
            dfu_script=self._dfu_script,
            bin_path=bin_path,
            cwd=self._cwd,
            boot_chip=self._boot_chip, boot_off=self._boot_off,
            rst_chip=self._rst_chip,   rst_off=self._rst_off,
            manual=manual,
            timeout_s=20.0,
            # optionally:
            dfu_vidpid="0483:df11",
            flash_address="0x08000000"
        )
        self._dfu_thread.progress.connect(self.dfu_progress)
        self._dfu_thread.stage.connect(self.dfu_stage)
        self._dfu_thread.finished.connect(self.dfu_finished)
        self._dfu_thread.output.connect(self.dfu_output)
        self._dfu_thread.start()

    def qualification_report_root(self):
        return self._repo_root / "hil_reports"

    def qualification_manifest_root(self):
        return self._repo_root / "tools" / "qualification" / "manifests"

    def qualification_campaign_root(self):
        return self._repo_root / "tools" / "qualification" / "campaigns"

    def qualification_output_root(self):
        return self._repo_root / "hil_reports" / "qualification"

    def qualification_campaign_output_root(self):
        return self._repo_root / "hil_reports" / "qualification_campaigns"

    def qualification_identity_path(self):
        return self._repo_root / "local" / "machine_identity.json"

    def qualification_default_machine_id(self):
        path = self.qualification_identity_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return ""
        return str(payload.get("machine_id") or "")

    def list_qualification_reports(self):
        from QualificationReports import discover_report_entries

        return discover_report_entries(self.qualification_report_root())

    def load_qualification_report(self, report_path):
        from QualificationReports import load_report

        return load_report(report_path)

    def list_qualification_suites(self):
        from QualificationSuites import discover_suite_entries

        return discover_suite_entries(self.qualification_manifest_root())

    def list_qualification_campaigns(self):
        from QualificationCampaigns import discover_campaign_entries

        return discover_campaign_entries(self.qualification_campaign_root())

    def qualification_timing_estimates(self):
        from QualificationTiming import build_timing_model

        return build_timing_model(self.qualification_report_root())

    def is_qualification_running(self):
        worker = getattr(self, "_qualification_worker", None)
        is_running = getattr(worker, "isRunning", None)
        return bool(worker is not None and callable(is_running) and is_running())

    def start_qualification_run(self, config):
        if self.is_qualification_running():
            return False

        from QualificationRunWorker import QualificationRunWorker

        run_config = dict(config)
        run_config.setdefault("identity_path", self.qualification_identity_path())
        run_config.setdefault("output_root", self.qualification_output_root())
        run_config.setdefault("suite_output_root", self.qualification_output_root())
        run_config.setdefault("campaign_output_root", self.qualification_campaign_output_root())
        run_config.setdefault("run_selftest_path", self._repo_root / "tools" / "run_selftest.py")
        self._qualification_worker = QualificationRunWorker(run_config, repo_root=self._repo_root)
        self._qualification_worker.stage.connect(lambda msg: self.qualification_stage.emit(msg))
        self._qualification_worker.output.connect(lambda msg: self.qualification_output.emit(msg))
        self._qualification_worker.prompt.connect(lambda msg: self.qualification_prompt.emit(msg))
        self._qualification_worker.selftest_event.connect(lambda event: self.qualification_selftest_event.emit(event))
        self._qualification_worker.campaign_event.connect(lambda event: self.qualification_campaign_event.emit(event))
        self._qualification_worker.run_finished.connect(self._on_qualification_finished)
        self._qualification_worker.start()
        return True

    def respond_qualification_prompt(self, accepted: bool):
        worker = getattr(self, "_qualification_worker", None)
        if worker is not None:
            worker.resolve_prompt(bool(accepted))

    @QtCore.Slot(bool, str, object)
    def _on_qualification_finished(self, ok, message, payload):
        self.qualification_finished.emit(bool(ok), str(message), payload)
        self._qualification_worker = None

    def reset_mcu_board(self):
        """Reset the MCU board."""
        self.machine.reset_mcu_board()
        self.machine.reset_board()

    # def update_balance_prediction_models(self,target_volume=40):
    #     pred_model = self.model.calibration_model.get_selected_model_path()
        # resistance_model = self.model.calibration_model.get_selected_resistance_model_path()
        # self.machine.balance.update_prediction_models(pred_model,target_volume)

    def pause_commands(self):
        """Pause the machine."""
        self.machine.pause_commands()
        self.model.machine_model.pause_commands()

    def resume_commands(self):
        """Resume the machine commands."""
        self.machine.resume_commands()
        self.model.machine_model.resume_commands()

    def clear_command_queue(self):
        """Clear the command queue."""
        self.machine.clear_command_queue()
        self.model.machine_model.clear_command_queue()
        if self.get_array_run_state() != "idle":
            self._complete_array_finalize("hard_abort")
        try:
            self.update_expected_with_current()
        except Exception:
            pass

    def get_array_run_state(self):
        """Return the current array runner state."""
        return str(getattr(self, "_array_state", "idle") or "idle")

    def _emit_optional(self, signal_name, *args):
        signal = getattr(self, signal_name, None)
        if signal is None:
            return
        try:
            signal.emit(*args)
        except Exception:
            pass

    def _set_array_run_state(self, state):
        state = str(state or "idle")
        if getattr(self, "_array_state", None) == state:
            self._array_state = state
            return
        self._array_state = state
        self._emit_optional("array_state_changed", state)

    def _safe_audit_value(self, obj, name, default=None):
        if obj is None:
            return default
        try:
            value = getattr(obj, name, default)
            if callable(value):
                return value()
            return value
        except Exception:
            return default

    def _build_print_settings_snapshot(self):
        machine_model = getattr(getattr(self, "model", None), "machine_model", None)
        return {
            "print_pressure_psi": self._safe_audit_value(machine_model, "get_current_print_pressure"),
            "target_print_pressure_psi": self._safe_audit_value(machine_model, "get_target_print_pressure"),
            "refuel_pressure_psi": self._safe_audit_value(machine_model, "get_current_refuel_pressure"),
            "target_refuel_pressure_psi": self._safe_audit_value(machine_model, "get_target_refuel_pressure"),
            "print_pulse_width_us": self._safe_audit_value(machine_model, "get_print_pulse_width"),
            "refuel_pulse_width_us": self._safe_audit_value(machine_model, "get_refuel_pulse_width"),
            "regulating_print_pressure": bool(
                getattr(machine_model, "regulating_print_pressure", False)
            ),
            "transport_paused": bool(getattr(machine_model, "transport_paused", False)),
        }

    def _build_loaded_printer_head_snapshot(self):
        rack_model = getattr(getattr(self, "model", None), "rack_model", None)
        printer_head = self._safe_audit_value(rack_model, "get_gripper_printer_head")
        if printer_head is None:
            printer_head = getattr(rack_model, "gripper_printer_head", None)
        if printer_head is None:
            return {"loaded": False}

        return {
            "loaded": True,
            "stock_id": self._safe_audit_value(printer_head, "get_stock_id"),
            "stock_solution": self._safe_audit_value(printer_head, "get_stock_name"),
            "reagent": self._safe_audit_value(printer_head, "get_reagent_name"),
            "concentration": self._safe_audit_value(printer_head, "get_stock_concentration"),
            "printing_mode": self._safe_audit_value(printer_head, "get_printing_mode"),
            "printer_head_id": self._safe_audit_value(printer_head, "printer_head_id"),
            "display_name": self._safe_audit_value(printer_head, "display_name"),
            "head_type_id": self._safe_audit_value(printer_head, "head_type_id"),
            "printer_head_slot": getattr(rack_model, "gripper_slot_number", None),
            "calibration_complete": bool(
                self._safe_audit_value(printer_head, "check_calibration_complete", False)
            ),
            "current_volume_uL": self._safe_audit_value(printer_head, "get_current_volume"),
            "droplet_volume_nL": self._safe_audit_value(printer_head, "get_target_droplet_volume"),
        }

    def _count_audit_assigned_wells(self):
        well_plate = getattr(getattr(self, "model", None), "well_plate", None)
        getter = getattr(well_plate, "get_all_wells_with_reactions", None)
        if callable(getter):
            try:
                return len(getter(fill_by="rows", serpentine=False))
            except TypeError:
                try:
                    return len(getter())
                except Exception:
                    pass
            except Exception:
                pass

        wells = getattr(well_plate, "wells", None)
        if isinstance(wells, dict):
            try:
                assigned = [
                    well for well in wells.values()
                    if getattr(well, "assigned_reaction", None) is not None
                ]
                if assigned:
                    return len(assigned)
                return len(wells)
            except Exception:
                return None
        return None

    def _build_print_array_snapshot(self, context=None):
        if context is None:
            context = getattr(self, "_array_context", None)
        if not isinstance(context, dict):
            context = {}

        stock_id = context.get("stock_id")
        remaining_well_count = None
        if stock_id:
            try:
                remaining_well_count = len(self._get_array_remaining_wells(stock_id))
            except Exception:
                remaining_well_count = None

        queued_wells = list(context.get("queued_wells") or [])
        planned_well_ids = context.get("planned_well_ids") or set()
        try:
            planned_well_count = len(planned_well_ids)
        except Exception:
            planned_well_count = None

        return {
            "array_state": self.get_array_run_state(),
            "stock_id": stock_id,
            "remaining_well_count": remaining_well_count,
            "queued_well_count": len(queued_wells),
            "planned_well_count": planned_well_count,
            "lookahead_wells": context.get("lookahead_wells"),
            "current_barrier_seq32": context.get("current_barrier_seq32"),
            "finalize_reason": context.get("finalize_reason"),
            "soft_stop_pending": bool(context.get("soft_stop_pending", False)),
            "soft_stop_phase": context.get("soft_stop_phase"),
            "soft_stop_clear_uncertain": bool(getattr(self, "_soft_stop_clear_uncertain", False)),
            "serpentine": bool(getattr(self, "_array_print_serpentine", ARRAY_PRINT_SERPENTINE)),
            "expected_volume_uL": context.get("expected_volume"),
            "droplet_volume_nL": context.get("droplet_volume"),
            "update_volume": bool(context.get("update_volume", False)),
            "settings": self._build_print_settings_snapshot(),
            "loaded_printer_head": self._build_loaded_printer_head_snapshot(),
        }

    def _record_print_array_audit_event(self, event_type, summary, details=None, level="info"):
        try:
            event_details = self._build_print_array_snapshot()
            if isinstance(details, dict):
                event_details.update(details)
            elif details is not None:
                event_details["details"] = details

            recorder = getattr(getattr(self, "model", None), "record_experiment_audit_event", None)
            if not callable(recorder):
                return None
            return recorder(event_type, summary, details=event_details, level=level)
        except Exception:
            return None

    def request_array_soft_stop(self):
        """Finish the active well, then park and leave the array resumable."""
        if self.get_array_run_state() != "running":
            return False
        context = getattr(self, "_array_context", None) or {}
        try:
            self._update_current_array_barrier()
        except Exception:
            pass
        current_barrier = context.get("current_barrier_seq32")
        if not current_barrier:
            return False
        self._set_array_run_state("stop_requested")
        context["soft_stop_pending"] = True
        context["soft_stop_phase"] = "waiting_watermark"
        if not self.machine.request_pause_after_seq32(
            current_barrier,
            on_failure=lambda payload, barrier=current_barrier: self._abort_array_after_soft_stop_failure(
                payload.get("reason", "unknown"),
                payload.get("barrier_seq32", barrier),
            ),
        ):
            return False
        self._record_print_array_audit_event(
            "print_array_soft_stop_requested",
            "Print array soft stop requested",
            details={"barrier_seq32": current_barrier},
        )
        return True

    def _abort_array_after_soft_stop_failure(self, reason, barrier_seq32=None):
        context = getattr(self, "_array_context", None)
        if context is not None:
            context["soft_stop_pending"] = False
            context["soft_stop_phase"] = "done"

        detail_map = {
            "write_failed": "the pause-after request could not be sent",
            "ack_rejected": "the MCU rejected the pause-after request",
            "ack_timeout": "the MCU did not acknowledge the pause-after request",
            "not_confirmed": "the pause-after request was not confirmed within the grace window",
            "invalid_barrier": "the pause-after request had an invalid barrier",
        }
        detail = detail_map.get(str(reason or "unknown"), f"the pause-after request failed ({reason})")
        barrier_text = f" for command {int(barrier_seq32)}" if barrier_seq32 else ""

        try:
            self.clear_command_queue()
        except Exception:
            self._complete_array_finalize("hard_abort")

        self.error_occurred_signal.emit(
            "Soft Stop Failed",
            f"Soft stop failed because {detail}{barrier_text}. The print array was aborted and the queued commands were cleared.",
        )

    def _warn_soft_stop_post_watermark(self, message):
        self.error_occurred_signal.emit("Soft Stop Warning", str(message or "Soft stop could not finish parking."))

    def _clear_command_queue_for_soft_stop(self, on_cleared=None):
        self.machine.clear_command_queue(handler=on_cleared)
        self.model.machine_model.clear_command_queue()

    def _begin_soft_stop_clear_and_park(self):
        context = getattr(self, "_array_context", None)
        if not isinstance(context, dict):
            return False
        if context.get("soft_stop_phase", "waiting_watermark") != "waiting_watermark":
            return False

        context["soft_stop_phase"] = "clearing"
        context["finalize_reason"] = "soft_stop"
        context["soft_stop_transport_was_paused"] = bool(
            getattr(self.model.machine_model, "transport_paused", False)
        )
        self._soft_stop_clear_uncertain = False

        try:
            self._clear_command_queue_for_soft_stop(self._on_soft_stop_queue_cleared)
        except Exception:
            context["soft_stop_phase"] = "done"
            context["soft_stop_pending"] = False
            self._warn_soft_stop_post_watermark(
                "Soft stop reached the watermark, but the queued commands could not be cleared. Preserving resume state without parking."
            )
            self._complete_array_finalize("soft_stop")
            return False
        return True

    def _on_soft_stop_queue_cleared(self, clear_result=None):
        context = getattr(self, "_array_context", None)
        if not isinstance(context, dict):
            return

        clear_result = dict(clear_result or {})
        print(f"Soft stop clear completion: {clear_result}")
        context["soft_stop_pending"] = False

        if not bool(clear_result.get("status_confirmed")):
            self._soft_stop_clear_uncertain = True
            context["skip_array_accel_restore"] = True
            context["soft_stop_phase"] = "done"
            ack_received = bool(clear_result.get("ack_received"))
            ack_timed_out = bool(clear_result.get("ack_timed_out"))
            if ack_received:
                warning = (
                    "Soft stop reached the watermark and received CLEAR_ACK, but the queue clear was not confirmed within the grace window. "
                    "Preserving resume state without parking."
                )
            elif ack_timed_out:
                warning = (
                    "Soft stop reached the watermark, but the queue clear was not confirmed within the grace window after CLEAR_ACK timed out. "
                    "Preserving resume state without parking."
                )
            else:
                warning = (
                    "Soft stop reached the watermark, but the queue clear was not confirmed within the grace window. "
                    "Preserving resume state without parking."
                )
            self._warn_soft_stop_post_watermark(
                warning
            )
            self._complete_array_finalize("soft_stop")
            return

        try:
            self.update_expected_with_current()
        except Exception:
            pass

        self._soft_stop_clear_uncertain = False
        if context.get("soft_stop_transport_was_paused"):
            try:
                self.resume_commands()
            except Exception:
                context["soft_stop_phase"] = "done"
                self._warn_soft_stop_post_watermark(
                    "Soft stop reached the watermark and cleared the queue, but transport could not be resumed for parking. Preserving resume state without parking."
                )
                self._complete_array_finalize("soft_stop")
                return

        self.disable_print_profile()
        context["soft_stop_phase"] = "parking"

        def _finish_after_park():
            active_context = getattr(self, "_array_context", None)
            if isinstance(active_context, dict):
                active_context["soft_stop_phase"] = "done"
            self._complete_array_finalize("soft_stop")

        if self._queue_pause_park_sequence(on_complete=_finish_after_park) is False:
            context["soft_stop_phase"] = "done"
            self._warn_soft_stop_post_watermark(
                "Soft stop reached the watermark, but the machine could not be parked. Preserving resume state without parking."
            )
            self._complete_array_finalize("soft_stop")

    def _queue_pause_park_sequence(self, on_complete=None):
        if self.move_to_location('pause') is False:
            return False
        if self.move_to_location('pause', z_offset=-5000, on_complete=on_complete) is False:
            return False
        return True

    def set_relative_X(self, x,manual=False,handler=None,override=False):
        """Set the relative X coordinate for the machine."""
        if not override:
            if self.check_collision(self.expected_position, {'X': self.expected_position['X'] + x, 'Y': self.expected_position['Y'], 'Z': self.expected_position['Z']}):
                print('Collision detected')
                return False
        #print(f"Setting relative X: {x}")
        self.machine.set_relative_X(x,manual=manual,handler=handler)
        self.expected_position['X'] += x
        return True

    def set_relative_Y(self, y,manual=False,handler=None, override=False):
        """Set the relative Y coordinate for the machine."""
        if not override:
            if self.check_collision(self.expected_position, {'X': self.expected_position['X'], 'Y': self.expected_position['Y'] + y, 'Z': self.expected_position['Z']}):
                print('Collision detected')
                return False
        #print(f"Setting relative Y: {y}")
        self.machine.set_relative_Y(y,manual=manual,handler=handler)
        self.expected_position['Y'] += y
        return True

    def set_relative_Z(self, z,manual=False,handler=None, override=False):
        """Set the relative Z coordinate for the machine."""
        if not override:
            if self.check_collision(self.expected_position, {'X': self.expected_position['X'], 'Y': self.expected_position['Y'], 'Z': self.expected_position['Z'] + z}):
                print('Collision detected')
                return False
        #print(f"Setting relative Z: {z}")
        self.machine.set_relative_Z(z,manual=manual,handler=handler)
        self.expected_position['Z'] += z
        return True
    
    def set_absolute_XY(self, x, y, manual=False, handler=None, override=False):
        """Set the absolute X and Y coordinates for the machine."""
        if not override:
            if self.check_collision(self.expected_position, {'X': x, 'Y': y, 'Z': self.expected_position['Z']}):
                print('Collision detected')
                return False
        #print(f"Setting absolute XY: {x}, {y}")
        self.machine.set_absolute_XY(x, y, manual=manual, handler=handler)
        self.update_expected_position(x=x, y=y)
        return True

    def set_absolute_X(self, x,manual=False,handler=None, override=False):
        """Set the absolute X coordinate for the machine."""
        if not override:
            if self.check_collision(self.expected_position, {'X': x, 'Y': self.expected_position['Y'], 'Z': self.expected_position['Z']}):
                print('Collision detected')
                return False
        #print(f"Setting absolute X: {x}")
        self.machine.set_absolute_X(x,manual=manual,handler=handler)
        self.update_expected_position(x=x)
        return True

    def set_absolute_Y(self, y,manual=False,handler=None, override=False):
        """Set the absolute Y coordinate for the machine."""
        if not override:
            if self.check_collision(self.expected_position, {'X': self.expected_position['X'], 'Y': y, 'Z': self.expected_position['Z']}):
                print('Collision detected')
                return False
        #print(f"Setting absolute Y: {y}")
        self.machine.set_absolute_Y(y,manual=manual,handler=handler)
        self.update_expected_position(y=y)
        return True
    
    def set_absolute_Z(self, z,manual=False,handler=None, override=False):
        """Set the absolute Z coordinate for the machine."""
        if not override:
            if self.check_collision(self.expected_position, {'X': self.expected_position['X'], 'Y': self.expected_position['Y'], 'Z': z}):
                print('Collision detected')
                return False
        #print(f"Setting absolute Z: {z}")
        self.machine.set_absolute_Z(z,manual=manual,handler=handler)
        self.update_expected_position(z=z)
        return True

    def check_collision(self,current_pos, target_pos):
        """
        Check if a straight-line path from current_pos to target_pos intersects any 3D obstacles
        or goes out of bounds.

        Returns True on malformed safety config as a fail-safe (block motion).
        """
        boundaries = self.model.location_model.get_boundaries()
        obstacles = self.model.location_model.get_obstacles()

        try:
            for axis in ['X', 'Y', 'Z']:
                if not (boundaries['min'][axis] <= min(current_pos[axis], target_pos[axis]) and
                        max(current_pos[axis], target_pos[axis]) <= boundaries['max'][axis]):
                    return True

            for obstacle in obstacles:
                min_corner = {axis: min(obstacle['corner1'][axis], obstacle['corner2'][axis]) for axis in ['X', 'Y', 'Z']}
                max_corner = {axis: max(obstacle['corner1'][axis], obstacle['corner2'][axis]) for axis in ['X', 'Y', 'Z']}

                for axis in ['X', 'Y', 'Z']:
                    min_proj = min(current_pos[axis], target_pos[axis])
                    max_proj = max(current_pos[axis], target_pos[axis])

                    if max_proj < min_corner[axis] or min_proj > max_corner[axis]:
                        break
                else:
                    return True
        except (TypeError, KeyError):
            print('Collision check misconfigured: invalid boundaries/obstacles payload')
            return True

        return False
    
    def set_relative_coordinates(self, x, y, z, manual=False, handler=None,override=False):
        """Set the relative coordinates for the machine."""
        #print(f"Setting relative coordinates: x={x}, y={y}, z={z}")
        if not override:
            new_position = {
                'X': self.expected_position['X'] + x,
                'Y': self.expected_position['Y'] + y,
                'Z': self.expected_position['Z'] + z
            }
            if self.check_collision(self.expected_position, new_position):
                print('Collision detected')
                return False

        # Build list of commands based on the order dictated by z.
        # Each element is a tuple: (axis, value)
        commands = []
        if z < 0:
            if z != 0:
                commands.append(('Z', z))
            if y != 0:
                commands.append(('Y', y))
            if x != 0:
                commands.append(('X', x))
        else:
            if y != 0:
                commands.append(('Y', y))
            if x != 0:
                commands.append(('X', x))
            if z != 0:
                commands.append(('Z', z))

        # Execute the commands in order, attaching the callback only to the last one.
        for i, (axis, value) in enumerate(commands):
            is_last = (i == len(commands) - 1)
            current_handler = handler if is_last else None
            if axis == 'X':
                self.machine.set_relative_X(value, manual=manual, handler=current_handler)
            elif axis == 'Y':
                self.machine.set_relative_Y(value, manual=manual, handler=current_handler)
            elif axis == 'Z':
                self.machine.set_relative_Z(value, manual=manual, handler=current_handler)

        # Update the expected position
        self.expected_position['X'] += x
        self.expected_position['Y'] += y
        self.expected_position['Z'] += z
        return True
    
    def set_absolute_coordinates(self, x, y, z, manual=False, handler=None, kwargs=None, override=False):
        """Set absolute coordinates; always use XY for any X/Y movement."""
        new_position = {'X': x, 'Y': y, 'Z': z}

        # 1) collision check
        if not override and self.check_collision(self.expected_position, new_position):
            print('Collision detected')
            return False

        cur = dict(self.expected_position)
        needs_xy = (x != cur['X']) or (y != cur['Y'])
        needs_z  = (z != cur['Z'])

        # 2) plan ordering: if moving "up", do Z first; otherwise XY first, then Z
        moves = []
        if needs_z and z < cur['Z']:
            # up first
            moves.append(('Z', z))
            if needs_xy:
                moves.append(('XY', (x, y)))
        else:
            # XY first (if any), then Z (if any)
            if needs_xy:
                moves.append(('XY', (x, y)))
            if needs_z:
                moves.append(('Z', z))

        # 3) nothing to do
        if not moves:
            if handler:
                handler()
            self.update_expected_position(x=x, y=y, z=z)
            return True

        # 4) dispatch (XY is used even if only one axis actually changes)
        for idx, (axis, val) in enumerate(moves):
            is_last = (idx == len(moves) - 1)
            cb = handler if is_last else None

            if axis == 'XY':
                x_val, y_val = val
                self.machine.set_absolute_XY(
                    x_val, y_val,
                    manual=manual,
                    handler=cb,
                    kwargs=kwargs
                )
                cur['X'], cur['Y'] = x_val, y_val
            elif axis == 'Z':
                self.machine.set_absolute_Z(
                    val,
                    manual=manual,
                    handler=cb,
                    kwargs=kwargs
                )
                cur['Z'] = val
            else:
                raise ValueError(f"Unknown axis {axis}")

        # 5) update expected end position
        self.update_expected_position(x=x, y=y, z=z)
        return True

    def set_relative_print_pressure(self, pressure,manual=False):
        """Set the relative pressure for the machine."""
        #print(f"Setting relative pressure: {pressure}")
        self.machine.set_relative_print_pressure(pressure,manual=manual)

    def set_relative_refuel_pressure(self, pressure,manual=False):
        """Set the relative pressure for the machine."""
        #print(f"Setting relative pressure: {pressure}")
        self.machine.set_relative_refuel_pressure(pressure,manual=manual)

    def set_absolute_print_pressure(self, pressure,handler=None, manual=False, trace_metadata=None):
        """Set the absolute pressure for the machine."""
        #print(f"Setting absolute pressure: {pressure}")
        return self.machine.set_absolute_print_pressure(
            pressure,
            manual=manual,
            handler=handler,
            trace_metadata=trace_metadata,
        )

    def set_absolute_refuel_pressure(self, pressure, handler=None, manual=False, trace_metadata=None):
        """Set the absolute pressure for the machine."""
        #print(f"Setting absolute pressure: {pressure}")
        return self.machine.set_absolute_refuel_pressure(
            pressure,
            manual=manual,
            handler=handler,
            trace_metadata=trace_metadata,
        )

    def _validate_refuel_vacuum_pressure(self, pressure):
        try:
            pressure = float(pressure)
        except (TypeError, ValueError):
            self.error_occurred_signal.emit(
                "Refuel Vacuum Error",
                f"Invalid refuel vacuum pressure: {pressure}",
            )
            return None
        if pressure < -1.0 or pressure > 0.0:
            self.error_occurred_signal.emit(
                "Refuel Vacuum Error",
                "Refuel vacuum pressure must be between -1.0 and 0.0 psi.",
            )
            return None
        return pressure

    def enter_refuel_vacuum_mode(
        self,
        target_psi=-1.0,
        prep_position_steps=20000,
        move_hz=5000,
        handler=None,
        manual=False,
    ):
        target_psi = self._validate_refuel_vacuum_pressure(target_psi)
        if target_psi is None:
            return False
        return self.machine.enter_refuel_vacuum_mode(
            target_psi=target_psi,
            prep_position_steps=int(prep_position_steps),
            move_hz=int(move_hz),
            handler=handler,
            manual=manual,
        )

    def set_refuel_vacuum_pressure(self, pressure_psi, handler=None, manual=False):
        pressure_psi = self._validate_refuel_vacuum_pressure(pressure_psi)
        if pressure_psi is None:
            return False
        return self.machine.set_refuel_vacuum_pressure(
            pressure_psi,
            handler=handler,
            manual=manual,
        )

    def exit_refuel_vacuum_mode(self, restore_pressure_psi, handler=None, manual=False):
        try:
            restore_pressure_psi = float(restore_pressure_psi)
        except (TypeError, ValueError):
            self.error_occurred_signal.emit(
                "Refuel Vacuum Error",
                f"Invalid refuel restore pressure: {restore_pressure_psi}",
            )
            return False
        if restore_pressure_psi < 0.0:
            restore_pressure_psi = 0.0
        return self.machine.exit_refuel_vacuum_mode(
            restore_pressure_psi,
            handler=handler,
            manual=manual,
        )

    def set_print_pulse_width(self, pulse_width,handler=None, manual=False,update_model=False, trace_metadata=None):
        """Set the pulse width for the machine."""
        #print(f"Setting pulse width: {pulse_width}")
        if update_model:
            self.model.machine_model.update_print_pulse_width(pulse_width)
        return self.machine.set_print_pulse_width(
            pulse_width,
            manual=manual,
            handler=handler,
            trace_metadata=trace_metadata,
        )

    def set_refuel_pulse_width(self, pulse_width, handler=None, manual=False,update_model=False, trace_metadata=None):
        """Set the pulse width for the machine."""
        #print(f"Setting pulse width: {pulse_width}")
        if update_model:
            self.model.machine_model.update_refuel_pulse_width(pulse_width)
        return self.machine.set_refuel_pulse_width(
            pulse_width,
            manual=manual,
            handler=handler,
            trace_metadata=trace_metadata,
        )

    def apply_print_profile(self, profile, callback=None):
        """Apply a print profile through the existing print/refuel setting commands."""
        profile = dict(profile or {})
        required = (
            "print_pressure",
            "refuel_pressure",
            "print_pulse_width",
            "refuel_pulse_width",
        )
        missing = [key for key in required if key not in profile]
        if missing:
            raise ValueError(f"Print profile missing required settings: {missing}")

        settings = {
            "print_pressure": float(profile["print_pressure"]),
            "refuel_pressure": float(profile["refuel_pressure"]),
            "print_pulse_width": int(profile["print_pulse_width"]),
            "refuel_pulse_width": int(profile["refuel_pulse_width"]),
        }
        self.handle_settings_change_request(settings, callback or self.intermediate_callback)
        return True

    def set_dispense_frequency_hz(self, hz, manual=False):
        """Set the print pacing used for future dispense commands."""
        return self.model.set_dispense_frequency_hz(
            hz,
        )

    def reset_print_syringe(self):
        """Reset the print syringe."""
        self.machine.reset_print_syringe()

    def reset_refuel_syringe(self):
        """Reset the refuel syringe."""
        self.machine.reset_refuel_syringe()

    def check_print_syringe_position(self):
        """Checks the syringe position and resets it if nearly at the limit."""
        current_p = self.model.machine_model.get_current_p_motor()
        if current_p > 95000:
            self.reset_print_syringe()
    
    def check_refuel_syringe_position(self):
        """Checks the syringe position and resets it if nearly at the limit."""
        current_r = self.model.machine_model.get_current_r_motor()
        if current_r > 95000:
            self.reset_refuel_syringe()

    def pause_machine(self):
        """Pause the machine."""
        self.machine.pause_machine()

    def LED_on(self):
        """Turn on the LED."""
        self.machine.LED_on()
        
    def LED_off(self):
        """Turn off the LED."""
        self.machine.LED_off()

    def home_machine(self):
        """Home the machine."""
        print("Homing machine...")
        self.machine.home_motors()

    def home_regulators(self):
        """Home the regulators."""
        print("Homing regulators...")
        self.machine.home_regulators()

    def toggle_motors(self):
        """Slot to toggle the motor state."""
        if self.model.machine_model.motors_enabled:
            success = self.machine.disable_motors()  # Assuming method exists
        else:
            success = self.machine.enable_motors()  # Assuming method exists
        if success:
            self.model.machine_model.toggle_motor_state()  # Update the model state

    def toggle_regulation(self):
        """Slot to toggle the motor state."""
        if self.model.machine_model.regulating_print_pressure:
            success = self.machine.deregulate_print_pressure()  # Assuming method exists
            success_2 = self.machine.deregulate_refuel_pressure()
        else:
            success = self.machine.regulate_print_pressure()  # Assuming method exists
            success_2 = self.machine.regulate_refuel_pressure()
        return success and success_2

    def add_reagent_to_slot(self, slot):
        """Add a reagent to a slot."""
        if slot == 0:
            new_printer_head = PrinterHead('Water',1,'Blue')
        elif slot == 1:
            new_printer_head = PrinterHead('Ethanol',2,'Green')
        elif slot == 2:
            new_printer_head = PrinterHead('Acetone',3,'Red')
        elif slot == 3:
            new_printer_head = PrinterHead('Methanol',4,'Yellow')
        self.model.rack_model.update_slot_with_printer_head(slot, new_printer_head)

    def confirm_slot(self, slot):
        """Confirm that a reagent is present in a slot."""
        self.model.rack_model.confirm_slot(slot)

    def add_new_location(self,name):
        """Save the current location information."""
        self.model.location_model.add_location(name,*self.model.machine_model.get_current_position())

    def modify_location(self,name):
        """Modify the location information."""
        self.model.location_model.update_location(name,*self.model.machine_model.get_current_position())

    # def update_current_location(self, name):
    #     """Update the current location to the specified name."""
    #     self.model.machine_model.update_current_location(name)
    
    def print_locations(self):
        """Print the saved locations."""
        print(self.model.location_model.get_all_locations())

    def save_locations(self):
        """Save the locations to a file."""
        self.model.location_model.save_locations()

    def home_complete_handler(self):
        """Handle the home complete signal."""
        self.model.machine_model.handle_home_complete()
        self.update_expected_position(x=500, y=500, z=500)
        try:
            self.expected_location = self.model.machine_model.get_current_location()
        except Exception:
            self.expected_location = "Home"

    def update_expected_position(self, x=None, y=None, z=None):
        """Update the expected position after a move."""
        if x is not None:
            self.expected_position['X'] = x
        if y is not None:
            self.expected_position['Y'] = y
        if z is not None:
            self.expected_position['Z'] = z

    def update_expected_with_current(self):
        """Update the expected position with the current position."""
        self.expected_position = self.model.machine_model.get_current_position_dict()
        try:
            self.expected_location = self.model.machine_model.get_current_location()
        except Exception:
            self.expected_location = None

        # resync rack expected state when queue drains
        try:
            self.model.rack_model.sync_expected_to_actual()
        except Exception:
            pass
    
    def update_location_handler(self,name=None):
        """Update the current location."""
        # self.model.machine_model.update_current_location(name)
        self.model.location_model.update_current_location(name)

    def check_if_all_completed(self):
        """Check if all commands have been completed."""
        return self.machine.check_if_all_completed()

    def move_to_location(self, name, direct=True, safe_y=False, x_offset: int = 0,z_offset: int = 0,manual=False,coords=None,override=False,ignore_safe_height=False,on_complete=None):
        """Move to the saved location."""
        if self.profile.name != "legacy":
            safe_z = 35000
        else:
            safe_z = 5000
        current_location = str(getattr(self, "expected_location", None) or "")
        current_location_norm = current_location.strip().lower()
        target_name_norm = str(name or "").strip().lower()
        current_z = self.expected_position['Z']

        if coords is not None:
            original_target = coords
        elif target_name_norm == "plate":
            # Treat "plate" as the active plate anchor first, with the legacy
            # persisted waypoint preserved as a fallback for uncalibrated plates.
            original_target = None
            well_plate = getattr(self.model, "well_plate", None)
            if well_plate is not None:
                get_plate_reference_coords = getattr(well_plate, "get_plate_reference_coords", None)
                if callable(get_plate_reference_coords):
                    original_target = get_plate_reference_coords()
            if original_target is None:
                original_target = self.model.location_model.get_location_dict(name)
        else:
            original_target = self.model.location_model.get_location_dict(name)

        if original_target is None:
            self.error_occurred_signal.emit("Move Error", f"Location '{name}' not found")
            print(f"Move aborted: location '{name}' not found")
            return False

        if not isinstance(original_target, dict) or not all(axis in original_target for axis in ("X", "Y", "Z")):
            self.error_occurred_signal.emit("Move Error", f"Location '{name}' has invalid coordinates")
            print(f"Move aborted: location '{name}' has invalid coordinates: {original_target}")
            return False

        target = original_target.copy()
        try:
            target['X'] = int(target['X'])
            target['Y'] = int(target['Y'])
            target['Z'] = int(target['Z'])
        except (TypeError, ValueError, KeyError):
            self.error_occurred_signal.emit("Move Error", f"Location '{name}' has non-numeric coordinates")
            print(f"Move aborted: location '{name}' has non-numeric coordinates: {original_target}")
            return False

        current_is_camera = current_location_norm == 'camera'
        target_is_camera = target_name_norm == 'camera'
        current_is_balance = current_location_norm == 'balance'
        target_is_balance = target_name_norm == 'balance'
        current_is_slot = current_location_norm.startswith('slot-')
        target_is_slot = target_name_norm.startswith('slot-')

        # Inverted-Z convention: smaller numerical Z means physically higher.
        # If we are already above the safe height plane, don't insert a redundant safe-Z move.
        if current_z < safe_z:
            print("Already above safe height")
            ignore_safe_height = True

        needs_route_safe_z = (
            (current_is_camera or target_is_camera) or
            (current_is_slot and not target_is_slot) or
            (not current_is_slot and target_is_slot)
        )

        print(f'Moving to location: {name} from {current_location}')
        # Only insert an intermediate safe-Z move when both endpoints are at/below
        # the safe plane (in inverted-Z coordinates: numerically >= safe_z).
        needs_intermediate_safe_z = current_z > safe_z and target['Z'] > safe_z

        if needs_route_safe_z and not ignore_safe_height and needs_intermediate_safe_z:
            print(f'Must move up to safe height before moving to {name} from {current_location}')
            if self.set_absolute_Z(safe_z, manual=manual, override=override) is False:
                self.error_occurred_signal.emit('Move Error', 'Failed to move to safe Z height')
                return False

        if current_is_balance or target_is_balance:
            if not ignore_safe_height:
                print(f'Must move up to safe height before moving to {name} from {current_location}')
                if self.set_absolute_Z(safe_z, manual=manual, override=override) is False:
                    self.error_occurred_signal.emit('Move Error', 'Failed to move to safe Z height')
                    return False
            print(f'Must move up to safe height before moving to {name} from {current_location}')
            print("Must move to safe Y before moving to or from balance")
            if self.set_absolute_Y(15000, manual=manual, override=override) is False:
                self.error_occurred_signal.emit('Move Error', 'Failed to move to safe Y height')
                return False
            if self.set_absolute_X(target['X'], manual=manual, override=override) is False:
                self.error_occurred_signal.emit('Move Error', 'Failed to move to target X for balance route')
                return False

        if x_offset != 0:
            target['X'] += x_offset
        if z_offset != 0:
            target['Z'] += z_offset

        def final_location_handler(name=name):
            self.update_location_handler(name=name)
            if on_complete is not None:
                on_complete()

        if self.set_absolute_coordinates(
            target['X'], target['Y'], target['Z'],
            manual=manual,
            override=override,
            handler=final_location_handler,
            kwargs={'name': name}
        ) is False:
            self.error_occurred_signal.emit('Move Error', 'Failed to move to target coordinates')
            return False

        self.expected_location = name
        return True
        
    def open_gripper(self,handler=None):
        """Open the gripper."""
        return self.machine.open_gripper(handler=handler)

    def close_gripper(self,handler=None):
        """Close the gripper."""
        return self.machine.close_gripper(handler=handler)

    def set_gripper_params(self, refresh_period_ms, pulse_duration_ms, handler=None, manual=False):
        """Update the firmware gripper refresh timing."""
        return self.machine.set_gripper_params(
            int(refresh_period_ms),
            int(pulse_duration_ms),
            handler=handler,
            manual=manual,
        )

    def wait_command(self):
        """Tells the machine to wait a specified amount of time in milliseconds."""
        self.machine.wait_command()

    def test_print_wait(self):
        """Test the print wait command."""
        self.print_droplets(10)
        # self.wait_command()
        self.print_droplets(10)
    
    def pick_up_handler(self,slot):
        """Handle the pick up signal from the rack."""
        self.model.rack_model.transfer_to_gripper(slot)

    def _prepare_manual_head_transfer(self):
        array_state = self.get_array_run_state()
        if array_state in {"running", "stop_requested"}:
            self.error_occurred_signal.emit(
                'Head Transfer Blocked',
                'Cannot load or unload a printer head while the print array is still stopping.',
            )
            return False

        if getattr(self, "_soft_stop_clear_uncertain", False):
            self.error_occurred_signal.emit(
                'Head Transfer Blocked',
                'The last soft stop did not confirm that the firmware queue was cleared. Clear the queue or reconnect before loading another printer head.',
            )
            return False

        if self.machine.check_if_all_completed() == False:
            print('Cannot transfer printer head: Commands are still running')
            return False

        machine_model = getattr(self.model, "machine_model", None)
        if bool(getattr(machine_model, "transport_paused", False)) or bool(getattr(machine_model, "paused", False)):
            try:
                self.resume_commands()
            except Exception:
                self.error_occurred_signal.emit(
                    'Head Transfer Blocked',
                    'Cannot resume machine transport before loading or unloading a printer head.',
                )
                return False
        return True

    def pick_up_printer_head(self,slot,manual=False):
        """Pick up a printer head from the rack."""
        if manual == True:
            if not self._prepare_manual_head_transfer():
                return
        # is_valid, error_msg = self.model.rack_model.verify_transfer_to_gripper(slot)
        is_valid, error_msg = self.model.rack_model.verify_transfer_to_gripper(slot, use_expected=True)
        if is_valid:
            # update expected rack state NOW (so subsequent queued ops see it)
            ok, msg = self.model.rack_model.plan_transfer_to_gripper(slot)
            if not ok:
                print(f"Plan pickup failed: {msg}")
                return

            self.open_gripper()
            coords = self.model.rack_model.get_slot_coordinates(slot)
            name = 'Slot-'+str(slot+1)
            self.move_to_location(name,x_offset=9000,coords=coords)

            self.move_to_location(name,coords=coords,override=True,ignore_safe_height=True)
            self.close_gripper(handler=lambda: self.pick_up_handler(slot))
            self.move_to_location(name,x_offset=3000,coords=coords,override=True,ignore_safe_height=True)
        else:
            print(f'Error: {error_msg}')
            pass

    def drop_off_handler(self,slot):
        """Handle the drop off signal from the rack."""
        self.model.rack_model.transfer_from_gripper(slot)

    def drop_off_printer_head(self,slot,manual=False):
        """Drop off a printer head to the rack."""
        if manual == True:
            if not self._prepare_manual_head_transfer():
                return
        is_valid, error_msg = self.model.rack_model.verify_transfer_from_gripper(slot, use_expected=True)
        if is_valid:
            # update expected rack state NOW (so subsequent queued ops see it)
            ok, msg = self.model.rack_model.plan_transfer_from_gripper(slot)
            if not ok:
                print(f"Plan dropoff failed: {msg}")
                return
            
            coords = self.model.rack_model.get_slot_coordinates(slot)
            name = 'Slot-'+str(slot+1)
            self.move_to_location(name,x_offset=3000,coords=coords)
            self.move_to_location(name,coords=coords,override=True,ignore_safe_height=True)
            self.open_gripper(handler=lambda: self.drop_off_handler(slot))
            self.move_to_location(name,x_offset=9000,coords=coords,override=True,ignore_safe_height=True)
            self.close_gripper()
        else:
            print(f'Error: {error_msg}')
            return

    def swap_printer_head(self, slot_number, new_printer_head):
        """Handle swapping of printer heads."""
        self.model.printer_head_manager.swap_printer_head(slot_number, new_printer_head)

    def swap_printer_heads_between_slots(self, slot_number_1, slot_number_2):
        """
        Swap printer heads between two slots in the rack.

        Args:
            slot_number_1 (int): The first slot number.
            slot_number_2 (int): The second slot number.
        """
        self.model.rack_model.swap_printer_heads_between_slots(slot_number_1, slot_number_2)

    def volume_update_handler(self,droplet_count=None):
        """Handle the volume update signal."""
        self.model.rack_model.get_gripper_printer_head().record_droplet_volume_lost(droplet_count)

    def _record_refuel_ejection_event(self, count, *, source, event_kind, count_kind="observed", payload=None):
        try:
            refuel_model = getattr(self.model, "refuel_camera_model", None)
            recorder = getattr(refuel_model, "record_refuel_ejection_event", None)
            if callable(recorder):
                return recorder(
                    count,
                    source=source,
                    event_kind=event_kind,
                    count_kind=count_kind,
                    payload=payload or {},
                )
        except Exception as exc:
            print(f"[RefuelEjections] failed to record ejection event: {exc}")
        return None

    def _current_imaging_droplet_count(self):
        try:
            camera_model = getattr(self.model, "droplet_camera_model", None)
            getter = getattr(camera_model, "get_num_droplets", None)
            value = getter() if callable(getter) else getattr(camera_model, "num_droplets", None)
            return max(0, int(value))
        except Exception:
            return 0
    
    def print_droplets(self,droplets,handler=None,kwargs=None,manual=False,expected_volume=None):
        """Print a specified number of droplets."""
        if not self.model.machine_model.regulating_print_pressure:
            self.error_occurred_signal.emit('Error','Pressure regulation is not enabled')
            print('Cannot print: Pressure regulation is not enabled')
            return
        if self.profile.name != "legacy":
            # fall back to your current implementation
            result = self.machine.print_droplets(droplets, handler=handler, kwargs=kwargs, manual=manual)
            if result is not False:
                self._record_refuel_ejection_event(
                    droplets,
                    source="Controller.print_droplets",
                    event_kind="print_droplets_queued",
                    count_kind="commanded",
                    payload={"manual": bool(manual)},
                )
            return result
        
        # --- legacy behavior ---
        printer_head = self.model.rack_model.get_gripper_printer_head()
        if printer_head is not None:
            if printer_head.check_calibration_complete():
                # print('Controller: using calibrations to change pulse width')
                # vol, res, target, bias, pred_model, resistance_pulse_width = printer_head.get_prediction_data()
                # if expected_volume is not None:
                #     #print(f'Controller: using expected volume: {expected_volume}')
                #     vol = expected_volume
                # new_pulse_width = self.model.calibration_model.predict_pulse_width(vol, res, target, bias=bias, prediction_model=pred_model,resistance_pulse_width=resistance_pulse_width)
                # if abs(self.model.machine_model.get_print_pulse_width() - new_pulse_width) > 2:
                #     self.set_print_pulse_width(new_pulse_width,manual=False)
            
                if handler is None:
                    handler = self.volume_update_handler
                    kwargs = {'droplet_count':droplets}
                else:
                    if kwargs is None:
                        kwargs = {}
                    kwargs['update_volume'] = True
            else:
                print('Controller: using default pulse width')

        result = self.machine.print_droplets(droplets,handler=handler,kwargs=kwargs,manual=manual)
        if result is not False:
            self._record_refuel_ejection_event(
                droplets,
                source="Controller.print_droplets",
                event_kind="print_droplets_queued",
                count_kind="commanded",
                payload={"manual": bool(manual), "profile": "legacy"},
            )
        return result

    def print_only(self,droplets,manual=False):
        """Activate the print valve a specified number of times without refueling."""
        result = self.machine.print_only(droplets,manual=manual)
        if result is not False:
            self._record_refuel_ejection_event(
                droplets,
                source="Controller.print_only",
                event_kind="print_only_queued",
                count_kind="commanded",
                payload={"manual": bool(manual)},
            )
        return result
    
    def refuel_only(self,droplets,manual=False):
        """Activate the refuel valve a specified number of times without printing."""
        self.machine.refuel_only(droplets,manual=manual)

    def print_calibration_droplets(self,droplets,manual=False,pressure=None,pulse_width=None):
        """Print a specified number of droplets for calibration."""
        print('Controller: Printing calibration droplets')
        result = self.machine.print_calibration_droplets(droplets,manual=manual,pressure=pressure,pulse_width=pulse_width)
        if result is not False:
            self._record_refuel_ejection_event(
                droplets,
                source="Controller.print_calibration_droplets",
                event_kind="print_calibration_droplets_queued",
                count_kind="commanded",
                payload={
                    "manual": bool(manual),
                    "pressure": pressure,
                    "pulse_width": pulse_width,
                },
            )
        return result

    def start_mass_stabilization_timer(self):
        """Create a single shot timer that when triggered it will signal the model to check for the final stable mass."""
        print('Starting mass stabilization timer...')
        QtCore.QTimer.singleShot(3000, self.model.calibration_model.check_for_final_mass)

    def _record_array_progress(self, well_id=None, stock_id=None, target_droplets=None, update_volume=False):
        target_droplets = int(target_droplets or 0)
        well = self.model.well_plate.get_well(well_id)
        if well is not None:
            well.record_stock_print(stock_id, target_droplets)
        if update_volume:
            printer_head = self.model.rack_model.get_gripper_printer_head()
            if printer_head is not None:
                printer_head.record_droplet_volume_lost(target_droplets)
        self.model.experiment_model.create_progress_file()

    def _get_array_remaining_wells(self, stock_id):
        if not stock_id:
            return []
        serpentine = bool(getattr(self, "_array_print_serpentine", ARRAY_PRINT_SERPENTINE))
        reaction_wells = self.model.well_plate.get_all_wells_with_reactions(fill_by='rows', serpentine=serpentine)
        return [well for well in reaction_wells if well.get_remaining_droplets(stock_id) > 0]

    def _start_array_run_context(self):
        current_printer_head = self.model.rack_model.get_gripper_printer_head()
        if current_printer_head is None:
            return False

        if current_printer_head.check_calibration_complete():
            print('\nController: Using calibrations during array printing')
            expected_volume = current_printer_head.get_current_volume()
            droplet_volume = current_printer_head.get_target_droplet_volume()
            update_volume = expected_volume is not None
        else:
            print('\nController: using default pulse width')
            expected_volume = None
            droplet_volume = None
            update_volume = False

        current_stock_id = current_printer_head.get_stock_id()
        wells_with_droplets = self._get_array_remaining_wells(current_stock_id)
        if not wells_with_droplets:
            self._array_context = None
            self._set_array_run_state("idle")
            return False

        self._array_context = {
            "stock_id": current_stock_id,
            "expected_volume": expected_volume,
            "update_volume": update_volume,
            "droplet_volume": droplet_volume,
            "finalize_reason": None,
            "lookahead_wells": 2,
            "queued_wells": [],
            "planned_well_ids": set(),
            "current_barrier_seq32": None,
            "soft_stop_pending": False,
            "soft_stop_phase": None,
            "pause_departure_pending": True,
            "pause_departure_accel": int(
                getattr(self, "_array_pause_departure_accel", ARRAY_PAUSE_DEPARTURE_ACCEL)
            ),
            "pause_departure_settle_ms": int(
                getattr(self, "_array_pause_departure_settle_ms", ARRAY_PAUSE_DEPARTURE_SETTLE_MS)
            ),
            "pause_departure_restore_accels": self._get_array_pause_departure_restore_accels(),
            "gentle_accel_enabled": bool(
                getattr(self, "_array_gentle_accel_enabled", ARRAY_GENTLE_ACCEL_ENABLED)
            ),
            "array_accels_lowered": False,
            "array_accels_restored": False,
            "row_start_overshoot_steps": int(
                getattr(self, "_array_row_start_overshoot_steps", ARRAY_ROW_START_OVERSHOOT_STEPS)
            ),
            "last_planned_row_num": None,
            "last_planned_col": None,
        }
        return True

    def _get_array_pause_departure_restore_accels(self):
        defaults = (ARRAY_AXIS_ACCEL_DEFAULT,) * 3
        machine_model = getattr(self.model, "machine_model", None)
        getter = getattr(machine_model, "get_current_accelerations", None)
        if not callable(getter):
            return defaults

        try:
            values = getter()
        except Exception:
            return defaults

        if not isinstance(values, (tuple, list)) or len(values) < 3:
            return defaults

        restore = []
        for idx, default in enumerate(defaults):
            try:
                value = int(values[idx])
            except Exception:
                value = default
            restore.append(value if value > 0 else default)
        return tuple(restore)

    def _apply_array_run_acceleration(self):
        context = getattr(self, "_array_context", None)
        if not isinstance(context, dict):
            return False
        if context.get("array_accels_lowered"):
            return True

        if not context.get("gentle_accel_enabled", ARRAY_GENTLE_ACCEL_ENABLED):
            context["array_accels_lowered"] = False
            context["array_accels_restored"] = True
            return True

        accel = max(0, int(context.get("pause_departure_accel") or 0))
        if accel <= 0:
            context["array_accels_lowered"] = True
            context["array_accels_restored"] = True
            return True

        queued_any = False
        for axis_idx in range(3):
            if self.set_axis_accel(axis_idx, accel) is False:
                if queued_any:
                    context["array_accels_lowered"] = True
                    self._restore_array_run_acceleration()
                self.error_occurred_signal.emit(
                    'Print Array Error',
                    'Failed to lower acceleration before starting the print array',
                )
                return False
            queued_any = True

        context["array_accels_lowered"] = True
        context["array_accels_restored"] = False
        return True

    def _restore_array_run_acceleration(self, on_restored=None):
        context = getattr(self, "_array_context", None)
        if not isinstance(context, dict):
            if callable(on_restored):
                on_restored()
            return True

        if not context.get("array_accels_lowered") or context.get("array_accels_restored"):
            if callable(on_restored):
                on_restored()
            return True

        restore_accels = tuple(
            context.get("pause_departure_restore_accels")
            or (ARRAY_AXIS_ACCEL_DEFAULT, ARRAY_AXIS_ACCEL_DEFAULT, ARRAY_AXIS_ACCEL_DEFAULT)
        )
        if len(restore_accels) < 3:
            restore_accels = (ARRAY_AXIS_ACCEL_DEFAULT, ARRAY_AXIS_ACCEL_DEFAULT, ARRAY_AXIS_ACCEL_DEFAULT)

        context["array_accels_restored"] = True
        for axis_idx, accel_value in enumerate(restore_accels[:3]):
            handler = on_restored if axis_idx == 2 else None
            if self.set_axis_accel(axis_idx, int(accel_value), handler=handler) is False:
                self.error_occurred_signal.emit(
                    'Print Array Warning',
                    'Failed to restore acceleration after the print array; check the Speed Profiles tab before the next run.',
                )
                if callable(on_restored):
                    on_restored()
                return False
        return True

    def _array_post_well_expected_volume(self, target_droplets):
        context = getattr(self, "_array_context", None) or {}
        expected_volume = context.get("expected_volume")
        droplet_volume = context.get("droplet_volume")
        if expected_volume is None or droplet_volume is None:
            return None
        return float(expected_volume) - int(target_droplets or 0) * float(droplet_volume) / 1000.0

    def _get_next_unplanned_array_well(self, context):
        stock_id = context.get("stock_id")
        planned = context.get("planned_well_ids", set())
        for well in self._get_array_remaining_wells(stock_id):
            if well.well_id not in planned:
                return well
        return None

    def _get_array_well_row_col(self, well):
        try:
            return int(well.row_num), int(well.col)
        except Exception:
            return None, None

    def _get_well_xy_direction(self, target_coords, neighbor_coords, *, invert=False):
        try:
            target_x = float(target_coords['X'])
            target_y = float(target_coords['Y'])
            neighbor_x = float(neighbor_coords['X'])
            neighbor_y = float(neighbor_coords['Y'])
        except Exception:
            return None

        dx = neighbor_x - target_x
        dy = neighbor_y - target_y
        if invert:
            dx = -dx
            dy = -dy

        length = math.hypot(dx, dy)
        if length <= 0:
            return None
        return dx / length, dy / length

    def _get_array_row_start_overshoot_coords(self, context, well, target_coords):
        try:
            overshoot_steps = int(context.get("row_start_overshoot_steps") or 0)
        except Exception:
            overshoot_steps = 0
        if overshoot_steps <= 0:
            return None

        row_num, col = self._get_array_well_row_col(well)
        last_row_num = context.get("last_planned_row_num")
        if row_num is None or col is None or last_row_num is None:
            return None
        try:
            if row_num <= int(last_row_num):
                return None
        except Exception:
            return None

        row_label = getattr(well, "row", None)
        if not row_label:
            return None

        well_plate = getattr(self.model, "well_plate", None)
        get_well = getattr(well_plate, "get_well", None)
        if not callable(get_well):
            return None

        direction = None
        right_neighbor = get_well(f"{row_label}{col + 1}")
        if right_neighbor is not None:
            right_coords = right_neighbor.get_coordinates()
            if isinstance(right_coords, dict):
                direction = self._get_well_xy_direction(target_coords, right_coords)

        if direction is None and col > 1:
            left_neighbor = get_well(f"{row_label}{col - 1}")
            if left_neighbor is not None:
                left_coords = left_neighbor.get_coordinates()
                if isinstance(left_coords, dict):
                    direction = self._get_well_xy_direction(target_coords, left_coords, invert=True)

        if direction is None:
            return None

        unit_x, unit_y = direction
        try:
            target_x = float(target_coords['X'])
            target_y = float(target_coords['Y'])
            target_z = target_coords['Z']
        except Exception:
            return None

        return {
            'X': int(round(target_x - unit_x * overshoot_steps, 0)),
            'Y': int(round(target_y - unit_y * overshoot_steps, 0)),
            'Z': target_z,
        }

    def _record_last_planned_array_well(self, context, well):
        row_num, col = self._get_array_well_row_col(well)
        context["last_planned_row_num"] = row_num
        context["last_planned_col"] = col

    def _update_current_array_barrier(self):
        context = getattr(self, "_array_context", None) or {}
        queued_wells = list(context.get("queued_wells") or [])
        context["current_barrier_seq32"] = queued_wells[0]["dispense_seq32"] if queued_wells else None

    def _queue_next_array_well(self):
        context = getattr(self, "_array_context", None) or {}
        stock_id = context.get("stock_id")
        well = self._get_next_unplanned_array_well(context)
        if well is None:
            return False

        target_droplets = int(well.get_remaining_droplets(stock_id) or 0)
        if target_droplets <= 0:
            return False

        well_coords = well.get_coordinates()
        if not isinstance(well_coords, dict):
            self.error_occurred_signal.emit('Print Array Error', f'Well {well.well_id} has no coordinates')
            self._complete_array_finalize("hard_abort")
            return False

        apply_pause_departure_safeguards = bool(context.get("pause_departure_pending"))
        pause_departure_settle_ms = max(0, int(context.get("pause_departure_settle_ms") or 0))

        overshoot_coords = self._get_array_row_start_overshoot_coords(context, well, well_coords)
        if overshoot_coords is not None:
            if self.set_absolute_coordinates(overshoot_coords['X'], overshoot_coords['Y'], overshoot_coords['Z'], override=True) is False:
                self.error_occurred_signal.emit('Print Array Error', f'Failed to queue row-entry approach for well {well.well_id}')
                self._complete_array_finalize("hard_abort")
                return False

        if self.set_absolute_coordinates(well_coords['X'], well_coords['Y'], well_coords['Z'], override=True) is False:
            self.error_occurred_signal.emit('Print Array Error', f'Failed to move to well {well.well_id}')
            self._complete_array_finalize("hard_abort")
            return False

        if apply_pause_departure_safeguards and pause_departure_settle_ms > 0:
            if self.machine.wait_ms(pause_departure_settle_ms) is False:
                self.error_occurred_signal.emit('Print Array Error', f'Failed to queue settle delay before printing well {well.well_id}')
                self._complete_array_finalize("hard_abort")
                return False

        context["pause_departure_pending"] = False

        print(f'Printing {target_droplets} droplets to well {well.well_id}')
        dispense_command = self.print_droplets(
            target_droplets,
            expected_volume=context.get("expected_volume"),
            handler=self._handle_array_well_complete,
            kwargs={
                'well_id': well.well_id,
                'stock_id': stock_id,
                'target_droplets': target_droplets,
                'update_volume': context.get("update_volume", False),
            },
        )
        if dispense_command is None:
            self.error_occurred_signal.emit('Print Array Error', f'Failed to queue dispense for well {well.well_id}')
            self._complete_array_finalize("hard_abort")
            return False

        context.setdefault("planned_well_ids", set()).add(well.well_id)
        context.setdefault("queued_wells", []).append(
            {
                "well_id": well.well_id,
                "target_droplets": target_droplets,
                "dispense_seq32": int(getattr(dispense_command, "command_number", 0) or 0),
            }
        )
        self._record_last_planned_array_well(context, well)
        self._update_current_array_barrier()
        return True

    def _fill_array_lookahead(self):
        context = getattr(self, "_array_context", None) or {}
        if context.get("finalize_reason") is not None:
            return False

        queued_wells = context.setdefault("queued_wells", [])
        lookahead_wells = int(context.get("lookahead_wells", 1) or 1)
        added_any = False
        while len(queued_wells) < lookahead_wells:
            if self.get_array_run_state() == "stop_requested":
                break

            if queued_wells and context.get("update_volume"):
                post_well_expected = self._array_post_well_expected_volume(queued_wells[-1]["target_droplets"])
                if post_well_expected is not None and post_well_expected < 10:
                    break

            if not self._queue_next_array_well():
                break
            queued_wells = context.setdefault("queued_wells", [])
            added_any = True

        self._update_current_array_barrier()
        return added_any

    def _pop_completed_array_well(self, well_id):
        context = getattr(self, "_array_context", None) or {}
        queued_wells = list(context.get("queued_wells") or [])
        removed = None
        remaining = []
        for info in queued_wells:
            if removed is None and info.get("well_id") == well_id:
                removed = info
            else:
                remaining.append(info)
        context["queued_wells"] = remaining
        if removed is not None:
            context.setdefault("planned_well_ids", set()).discard(well_id)
        self._update_current_array_barrier()
        return removed

    def _handle_array_well_complete(self, well_id=None, stock_id=None, target_droplets=None, update_volume=False):
        context = getattr(self, "_array_context", None) or {}
        self._pop_completed_array_well(well_id)
        self._record_array_progress(
            well_id=well_id,
            stock_id=stock_id,
            target_droplets=target_droplets,
            update_volume=update_volume,
        )

        if context.get("update_volume") and context.get("expected_volume") is not None and context.get("droplet_volume") is not None:
            context["expected_volume"] -= int(target_droplets or 0) * float(context["droplet_volume"]) / 1000.0

        stock_id = context.get("stock_id", stock_id)
        remaining_wells = self._get_array_remaining_wells(stock_id)
        if not remaining_wells and not context.get("queued_wells"):
            self._enqueue_array_finalize("completed")
        elif self.get_array_run_state() == "stop_requested":
            context["soft_stop_pending"] = True
        elif context.get("update_volume") and context.get("expected_volume") is not None and context.get("expected_volume") < 10:
            self._enqueue_array_finalize("refill_required")
        else:
            self._fill_array_lookahead()

    def _enqueue_array_finalize(self, reason):
        reason = str(reason or "completed")
        context = getattr(self, "_array_context", None)
        if context is not None:
            if context.get("finalize_reason") is not None:
                return False
            context["finalize_reason"] = reason

        if reason == "hard_abort":
            self._complete_array_finalize(reason)
            return False

        self.disable_print_profile()

        def _finish_after_park():
            self._complete_array_finalize(reason)

        if self._queue_pause_park_sequence(on_complete=_finish_after_park) is False:
            self._complete_array_finalize(reason)
            return False
        return True

    def _complete_array_finalize(self, reason):
        reason = str(reason or "completed")
        context = getattr(self, "_array_context", None)
        if isinstance(context, dict) and context.get("array_finalize_after_accel_restore"):
            return
        if isinstance(context, dict) and context.get("skip_array_accel_restore"):
            self._finish_array_finalize(reason)
            return
        if isinstance(context, dict):
            context["array_finalize_after_accel_restore"] = reason

        def _finish_finalize():
            self._finish_array_finalize(reason)

        self._restore_array_run_acceleration(on_restored=_finish_finalize)

    def _finish_array_finalize(self, reason):
        reason = str(reason or "completed")
        try:
            audit_details = self._build_print_array_snapshot(getattr(self, "_array_context", None))
        except Exception:
            audit_details = {}
        audit_details["finalize_reason"] = reason
        self._array_context = None

        if reason in {"soft_stop", "refill_required"}:
            self._set_array_run_state("resume_ready")
        else:
            self._set_array_run_state("idle")
        audit_details["array_state"] = self.get_array_run_state()

        if reason == "completed":
            self._record_print_array_audit_event(
                "print_array_completed",
                "Print array completed",
                details=audit_details,
            )
        elif reason == "soft_stop":
            self._record_print_array_audit_event(
                "print_array_paused",
                "Print array paused",
                details=audit_details,
            )
        elif reason == "refill_required":
            self._record_print_array_audit_event(
                "print_array_refill_required",
                "Print array paused for printer head refill",
                details=audit_details,
                level="warning",
            )
        else:
            self._record_print_array_audit_event(
                "print_array_aborted",
                "Print array aborted",
                details=audit_details,
                level="error",
            )

        if reason == "completed":
            print('---Printing complete---')
            self._emit_optional("array_complete")
        elif reason == "soft_stop":
            print('---Array soft stop complete---')
            self._emit_optional("update_slots_signal")
        elif reason == "refill_required":
            print('---Must reload printer head---')
            self._emit_optional("update_slots_signal")
            self.error_occurred_signal.emit('Error', 'Printer head needs to be reloaded')
        elif reason == "hard_abort":
            print('---Array run aborted---')


    def well_complete_handler(self,well_id=None,stock_id=None,target_droplets=None,update_volume=False):
        self._record_array_progress(
            well_id=well_id,
            stock_id=stock_id,
            target_droplets=target_droplets,
            update_volume=update_volume,
        )

    def last_well_complete_handler(self,well_id=None,stock_id=None,target_droplets=None,update_volume=False):
        self._record_array_progress(
            well_id=well_id,
            stock_id=stock_id,
            target_droplets=target_droplets,
            update_volume=update_volume,
        )
        self._enqueue_array_finalize("completed")

    def refill_printer_head_handler(self,well_id=None,stock_id=None,target_droplets=None,update_volume=False):
        self._record_array_progress(
            well_id=well_id,
            stock_id=stock_id,
            target_droplets=target_droplets,
            update_volume=update_volume,
        )
        self._enqueue_array_finalize("refill_required")

    def reset_single_array(self):
        """Resets the droplet count for all wells in the well plate for the currently loaded stock solution."""
        active_printer_head = self.model.rack_model.get_gripper_printer_head()
        stock_id = active_printer_head.get_stock_id()
        try:
            remaining_before = len(self._get_array_remaining_wells(stock_id))
        except Exception:
            remaining_before = None
        self.model.well_plate.reset_all_wells_for_stock(stock_id)
        self.model.experiment_model.create_progress_file()
        progress_path = getattr(self.model.experiment_model, "progress_file_path", None)
        self._record_print_array_audit_event(
            "print_array_reset",
            f"Print array reset for {stock_id}",
            details={
                "reset_scope": "single_stock",
                "stock_id": stock_id,
                "affected_well_count": self._count_audit_assigned_wells(),
                "remaining_well_count_before_reset": remaining_before,
                "progress_file_path": progress_path,
            },
            level="warning",
        )

    def reset_all_arrays(self):
        """Resets the droplet count for all wells in the well plate for all stock solutions."""
        self.model.well_plate.reset_all_wells()
        self.model.experiment_model.create_progress_file()
        self.update_slots_signal.emit()
        progress_path = getattr(self.model.experiment_model, "progress_file_path", None)
        self._record_print_array_audit_event(
            "print_arrays_reset_all",
            "All print arrays reset",
            details={
                "reset_scope": "all_stocks",
                "affected_well_count": self._count_audit_assigned_wells(),
                "progress_file_path": progress_path,
            },
            level="warning",
        )

    def enter_print_mode(self):
        """Enter print mode."""
        self.machine.enter_print_mode()

    def exit_print_mode(self):
        """Exit print mode."""
        self.machine.exit_print_mode()

    def get_print_array_imaging_calibration_preflight(self):
        """Return imaging-calibration readiness for the loaded printer head."""
        profile_name = str(getattr(getattr(self, "profile", None), "name", "") or "").lower()
        if profile_name == "legacy":
            return {"ok": True, "code": "ok", "message": "", "record": None}

        try:
            printer_head = self.model.rack_model.get_gripper_printer_head()
        except Exception:
            printer_head = None
        if printer_head is None:
            return {
                "ok": False,
                "code": "context_unavailable",
                "message": "No printer head is loaded.",
                "record": None,
            }

        validator = getattr(
            getattr(self.model, "experiment_model", None),
            "validate_applied_imaging_calibration_for_print",
            None,
        )
        if not callable(validator):
            return {
                "ok": False,
                "code": "validation_unavailable",
                "message": "Experiment model cannot confirm the applied imaging calibration.",
                "record": None,
            }

        validation = validator(
            printer_head=printer_head,
            machine_model=self.model.machine_model,
        )
        if not isinstance(validation, dict):
            return {
                "ok": False,
                "code": "validation_unavailable",
                "message": "Experiment model returned an invalid imaging calibration result.",
                "record": None,
            }
        validation.setdefault("code", "ok" if validation.get("ok") else "validation_failed")
        validation.setdefault("message", "")
        validation.setdefault("record", None)
        return validation

    def apply_applied_imaging_calibration_print_settings(self, record):
        """Apply PW and pressure from an applied imaging calibration record."""
        record = dict(record or {})
        try:
            pw_us = int(round(float(record.get("pw_us"))))
            pressure_psi = float(record.get("pressure_psi"))
        except Exception:
            return {
                "ok": False,
                "message": "Applied imaging calibration is missing usable PW or pressure settings.",
            }

        try:
            self.set_print_pulse_width(pw_us, manual=True)
            self.set_absolute_print_pressure(pressure_psi, manual=True)
        except Exception as exc:
            return {"ok": False, "message": f"Could not apply calibration settings: {exc}"}

        return {
            "ok": True,
            "message": (
                f"Set print pulse width to {pw_us} us and print pressure to "
                f"{pressure_psi:.3f} psi."
            ),
            "pw_us": pw_us,
            "pressure_psi": pressure_psi,
        }
    
    def print_array(self, *, imaging_calibration_override=False, settings_mismatch_override=False):
        '''
        Iterates through all wells with an assigned reaction and prints the 
        required number of droplets for the currently loaded printer head.
        '''
        starting_state = self.get_array_run_state()
        if starting_state in {"running", "stop_requested"}:
            print('Cannot print: Array runner is already active')
            return

        if not self.check_if_all_completed():
            print('Cannot print: command queue is not empty')
            return

        if not self.model.well_plate.check_calibration_applied():
            self.error_occurred_signal.emit('Error','Calibration has not been applied to this plate')
            print('Cannot print: Calibration has not been applied')
            return
        
        if self.model.rack_model.get_gripper_info() == None:
            self.error_occurred_signal.emit('Error','No printer head is loaded')
            print('Cannot print: No printer head is loaded')
            return
        
        if not self.model.machine_model.regulating_print_pressure:
            self.error_occurred_signal.emit('Error','Pressure regulation is not enabled')
            print('Cannot print: Pressure regulation is not enabled')
            return

        validation = self.get_print_array_imaging_calibration_preflight()
        if not bool(validation.get("ok")):
            code = str(validation.get("code") or "")
            imaging_override_ok = (
                bool(imaging_calibration_override)
                and code in {"missing_record", "stale_design_volume"}
            )
            settings_override_ok = (
                bool(settings_mismatch_override)
                and code in {"pulse_width_mismatch", "pressure_mismatch"}
            )
            if not (imaging_override_ok or settings_override_ok):
                message = str(
                    validation.get("message")
                    or "No applied imaging calibration was found for the loaded printer head."
                )
                self.error_occurred_signal.emit('Error', message)
                print(f'Cannot print: {message}')
                return
            print(f"Print array imaging calibration override accepted: {code}")

        transport_resumed = False
        if starting_state == "resume_ready" and self.model.machine_model.transport_paused:
            self.resume_commands()
            transport_resumed = True

        if not self._start_array_run_context():
            print('Cannot print: No remaining droplets for the loaded stock')
            return
        self._record_print_array_audit_event(
            "print_array_requested",
            "Print array request accepted",
            details={
                "request_kind": "resume" if starting_state == "resume_ready" else "start",
                "imaging_calibration_override": bool(imaging_calibration_override),
                "settings_mismatch_override": bool(settings_mismatch_override),
            },
        )
        if starting_state == "resume_ready":
            self._record_print_array_audit_event(
                "print_array_resumed",
                "Print array resumed",
                details={"transport_resumed": transport_resumed},
            )
        
        self.close_gripper()
        # self.wait_command()

        self.move_to_location('pause',z_offset=-5000)
        self.move_to_location('pause', ignore_safe_height=True)
        if not self._apply_array_run_acceleration():
            self._complete_array_finalize("hard_abort")
            return
        # self.machine.change_acceleration(16000)
        # self.enter_print_mode()
        self.enable_print_profile()

        self._set_array_run_state("running")
        lookahead_added = self._fill_array_lookahead()
        if self.get_array_run_state() == "running":
            self._record_print_array_audit_event(
                "print_array_started",
                "Print array started",
                details={"lookahead_added": bool(lookahead_added)},
            )
            
    def enable_print_profile(self):
        """Enable the print profile."""
        self.machine.enable_print_profile()

    def disable_print_profile(self):
        """Disable the print profile."""
        self.machine.disable_print_profile()
    
    def start_refuel_camera(self):
        self.machine.start_refuel_camera()
        try:
            self.machine.refuel_led_on()
        except Exception:
            try:
                self.machine.refuel_led_off()
            except Exception:
                pass
            try:
                self.machine.stop_refuel_camera()
            except Exception:
                pass
            raise

    def _build_refuel_capture_context(self):
        machine_model = getattr(self.model, "machine_model", None)
        context = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "monotonic_s": time.monotonic(),
            "print_pressure": None,
            "refuel_pressure": None,
            "print_pulse_width": None,
            "refuel_pulse_width": None,
            "location": "",
        }
        if machine_model is None:
            return context

        getters = (
            ("print_pressure", "get_current_print_pressure"),
            ("refuel_pressure", "get_current_refuel_pressure"),
            ("print_pulse_width", "get_print_pulse_width"),
            ("refuel_pulse_width", "get_refuel_pulse_width"),
            ("location", "get_current_location"),
        )
        for key, getter_name in getters:
            getter = getattr(machine_model, getter_name, None)
            if callable(getter):
                try:
                    context[key] = getter()
                except Exception:
                    pass
        return context

    def capture_refuel_image(self):
        frame, _context = self.capture_refuel_image_with_context(analyze=True)
        return frame

    def capture_refuel_image_with_context(self, *, analyze=True, context_overrides=None):
        capture_start = time.perf_counter()
        frame = self.machine.capture_refuel_image()
        capture_duration_ms = float((time.perf_counter() - capture_start) * 1000.0)
        context = self._build_refuel_capture_context()
        context["refuel_monitor_capture_duration_ms"] = capture_duration_ms
        if context_overrides:
            context.update(dict(context_overrides))
        if frame is None:
            context["analysis_started"] = False
            return None, context
        if analyze:
            context["analysis_started"] = bool(self.model.refuel_camera_model.start_analysis(frame, context=context))
        else:
            context["analysis_started"] = False
        return frame, context

    def get_refuel_capture_context(self):
        return self._build_refuel_capture_context()

    def run_refuel_balance_burst(self, droplet_count, settle_ms, on_complete=None, on_error=None):
        if not self.machine.check_if_all_completed():
            msg = "Cannot start refuel burst: command queue is not empty."
            if callable(on_error):
                on_error(msg)
            return False
        if not self.model.machine_model.regulating_print_pressure:
            msg = "Cannot start refuel burst: print pressure regulation is not enabled."
            if callable(on_error):
                on_error(msg)
            return False

        droplet_count = max(1, int(droplet_count))
        settle_ms = max(1, int(settle_ms))

        def _burst_complete_handler():
            if callable(on_complete):
                on_complete(self._build_refuel_capture_context())

        ok_print = self.machine.print_droplets(droplet_count, manual=True)
        if ok_print is False:
            msg = "Failed to enqueue refuel balance print burst."
            if callable(on_error):
                on_error(msg)
            return False
        self._record_refuel_ejection_event(
            droplet_count,
            source="Controller.run_refuel_balance_burst",
            event_kind="refuel_balance_burst_queued",
            count_kind="commanded",
            payload={"manual": True, "settle_ms": settle_ms},
        )

        ok_wait = self.machine.wait_ms(settle_ms, handler=_burst_complete_handler, manual=True)
        if ok_wait is False:
            msg = "Failed to enqueue refuel balance settle delay."
            if callable(on_error):
                on_error(msg)
            return False

        return True

    def stop_refuel_camera(self):
        stop_error = None
        try:
            self.machine.stop_refuel_camera()
        except Exception as exc:
            stop_error = exc

        try:
            self.machine.refuel_led_off()
        except Exception:
            raise

        if stop_error is not None:
            raise stop_error

    def start_droplet_camera(self):
        self.machine.start_droplet_camera()

    def capture_droplet_image(self, callback=None, *, throughput_mode=False, capture_context=None):
        """
        Initiates a non-blocking image capture. If a callback is provided,
        it will be invoked with the captured frame once the capture completes.
        """
        self.last_capture_queue_rejection_reason = None
        self.last_capture_queue_rejection_state = None
        if self._is_flash_fault_latched():
            self.last_capture_queue_rejection_reason = "flash_fault"
            self.last_capture_queue_rejection_state = self._get_droplet_capture_state()
            self._record_active_calibration_event(
                "capture_queue_rejected",
                {"reason": "flash_fault", "capture_context": capture_context},
                level="warning",
            )
            self._handle_blocked_capture(callback)
            return False
        if bool(getattr(self, "pending_capture_active", False)):
            state = self._get_droplet_capture_state()
            self.last_capture_queue_rejection_reason = "controller_pending"
            self.last_capture_queue_rejection_state = state
            print(
                "[Camera] capture rejected: reason=controller_pending "
                f"pending_request_id={getattr(self, 'pending_capture_request_id', None)} state={state}"
            )
            self._record_active_calibration_event(
                "capture_queue_rejected",
                {
                    "reason": "controller_pending",
                    "pending_request_id": getattr(self, "pending_capture_request_id", None),
                    "state": state,
                },
                level="warning",
            )
            self._notify_capture_callback_failed(callback)
            return False
        if capture_context is not None and getattr(self, "pending_capture_context", None) is not None:
            state = self._get_droplet_capture_state()
            self.last_capture_queue_rejection_reason = "context_pending"
            self.last_capture_queue_rejection_state = state
            print(f"[Camera] capture rejected: reason=context_pending state={state}")
            self._record_active_calibration_event(
                "capture_queue_rejected",
                {"reason": "context_pending", "capture_context": capture_context, "state": state},
                level="warning",
            )
            self._notify_capture_callback_failed(callback)
            return False
        if callback is not None:
            if self.pending_capture_callback is not None:
                state = self._get_droplet_capture_state()
                self.last_capture_queue_rejection_reason = "callback_pending"
                self.last_capture_queue_rejection_state = state
                print(f"[Camera] capture rejected: reason=callback_pending state={state}")
                self._record_active_calibration_event(
                    "capture_queue_rejected",
                    {"reason": "callback_pending", "state": state},
                    level="warning",
                )
                self._notify_capture_callback_failed(callback)
                return False
        return self._queue_capture_request(
            callback=callback,
            throughput_mode=throughput_mode,
            capture_context=capture_context,
            recovery_attempted=False,
        )

    def _queue_capture_request(
        self,
        *,
        callback=None,
        throughput_mode=False,
        capture_context=None,
        recovery_attempted=False,
    ):
        capture_request_id = uuid.uuid4().hex
        self.last_capture_queue_rejection_reason = None
        self.last_capture_queue_rejection_state = None
        if callback is not None:
            self.pending_capture_callback = callback
        self.pending_capture_context = None if capture_context is None else str(capture_context)
        self.pending_capture_active = True
        self.pending_capture_request_id = capture_request_id
        self.pending_capture_recovery_attempted = bool(recovery_attempted)
        self.pending_capture_throughput_mode = bool(throughput_mode)
        monotonic_fn = getattr(self, "_monotonic_fn", time.monotonic)
        self.pending_capture_started_monotonic = monotonic_fn()
        try:
            capture_method = self.machine.capture_droplet_image
            accepts_request_id = True
            try:
                signature = inspect.signature(capture_method)
                accepts_request_id = (
                    "capture_request_id" in signature.parameters
                    or any(
                        param.kind == inspect.Parameter.VAR_KEYWORD
                        for param in signature.parameters.values()
                    )
                )
            except (TypeError, ValueError):
                accepts_request_id = True
            if accepts_request_id:
                queued = capture_method(
                    throughput_mode=throughput_mode,
                    capture_request_id=capture_request_id,
                )
            else:
                queued = capture_method(throughput_mode=throughput_mode)
        except Exception:
            self._clear_pending_capture(callback=callback, capture_context=capture_context)
            raise
        if queued is False:
            state = self._get_droplet_capture_state()
            reason = self._classify_capture_queue_rejection(state)
            self.last_capture_queue_rejection_reason = reason
            self.last_capture_queue_rejection_state = state
            print(
                f"[Camera] capture rejected by machine request_id={capture_request_id} "
                f"reason={reason} state={state}"
            )
            self._record_active_calibration_event(
                "capture_queue_rejected",
                {
                    "request_id": capture_request_id,
                    "reason": reason,
                    "state": state,
                    "capture_context": capture_context,
                    "recovery_attempted": bool(recovery_attempted),
                },
                level="warning",
            )
            self._clear_pending_capture(callback=callback, capture_context=capture_context)
            self._notify_capture_callback_failed(callback)
            return False
        self._start_pending_capture_guard(throughput_mode=throughput_mode)
        print(
            f"[Camera] capture request queued request_id={capture_request_id} "
            f"throughput_mode={bool(throughput_mode)} recovery_attempted={bool(recovery_attempted)}"
        )
        self._record_active_calibration_event(
            "capture_request_queued",
            {
                "request_id": capture_request_id,
                "capture_context": capture_context,
                "throughput_mode": bool(throughput_mode),
                "recovery_attempted": bool(recovery_attempted),
            },
        )
        return True

    def stop_droplet_camera(self):
        self.machine.stop_droplet_camera()

    def start_read_camera(self):
        self.machine.start_read_camera()

    def stop_read_camera(self):
        self.machine.stop_read_camera()

    def set_flash_duration(self, duration,callback=None, trace_metadata=None):
        return self.machine.set_flash_duration(duration, handler=callback, trace_metadata=trace_metadata)

    def set_flash_delay(self, delay,callback=None, trace_metadata=None):
        return self.machine.set_flash_delay(delay, handler=callback, trace_metadata=trace_metadata)

    def set_imaging_droplets(self, num_droplets, callback=None, trace_metadata=None):
        return self.machine.set_imaging_droplets(num_droplets,handler=callback, trace_metadata=trace_metadata)

    def set_exposure_time(self, exposure_time,callback=None, trace_metadata=None):
        result = self.machine.set_exposure_time(exposure_time,handler=callback, trace_metadata=trace_metadata)
        self.model.droplet_camera_model.update_exposure_time(exposure_time)
        return result

    def set_droplet_capture_profile(self, profile_name: str):
        self.machine.set_droplet_capture_profile(profile_name)

    def set_command_dispatch_interval(self, interval_ms: int):
        self.machine.set_execution_interval_ms(interval_ms)

    def set_save_directory(self, directory):
        self.model.droplet_camera_model.set_save_directory(directory)      

    def handle_capture_request(self, callback):
        # protect against overlapping requests
        self.capture_droplet_image(callback=callback)

    def _notify_capture_callback_failed(self, callback):
        if callback is None:
            return
        try:
            setattr(callback, "_capture_rejection_reason", self.last_capture_queue_rejection_reason)
            setattr(callback, "_capture_rejection_state", self.last_capture_queue_rejection_state)
        except Exception:
            pass
        try:
            callback(None)
        except Exception as e:
            print(f"Callback raised after capture request failure: {e}")

    def _ensure_pending_capture_guard_timer(self):
        timer = getattr(self, "pending_capture_guard_timer", None)
        if timer is not None:
            return timer
        timer_factory = getattr(self, "_timer_factory", None)
        if not callable(timer_factory):
            return None
        try:
            timer = timer_factory(self)
            if hasattr(timer, "setSingleShot"):
                timer.setSingleShot(True)
            timer.timeout.connect(self._on_pending_capture_timeout)
        except Exception as e:
            print(f"[Camera] could not create pending capture guard timer: {e}")
            return None
        self.pending_capture_guard_timer = timer
        return timer

    def _start_pending_capture_guard(self, *, throughput_mode=False):
        timer = self._ensure_pending_capture_guard_timer()
        if timer is None:
            return
        timeout_ms = (
            int(getattr(self, "pending_capture_throughput_timeout_ms", 1_500))
            if throughput_mode else
            int(getattr(self, "pending_capture_timeout_ms", 8_000))
        )
        timeout_ms = max(1, timeout_ms)
        try:
            timer.stop()
        except Exception:
            pass
        try:
            timer.setInterval(timeout_ms)
            timer.start()
        except TypeError:
            timer.start(timeout_ms)

    def _stop_pending_capture_guard(self):
        timer = getattr(self, "pending_capture_guard_timer", None)
        if timer is None:
            return
        try:
            timer.stop()
        except Exception:
            pass

    def _clear_pending_capture(self, *, callback=None, capture_context=None):
        self._stop_pending_capture_guard()
        if callback is None or self.pending_capture_callback is callback:
            self.pending_capture_callback = None
        if capture_context is None or self.pending_capture_context == str(capture_context):
            self.pending_capture_context = None
        self.pending_capture_active = False
        self.pending_capture_started_monotonic = None
        self.pending_capture_request_id = None
        self.pending_capture_recovery_attempted = False
        self.pending_capture_throughput_mode = False

    def _fail_pending_capture(self, msg: str, *, emit_capture_failed: bool = True):
        cb = self.pending_capture_callback
        request_id = getattr(self, "pending_capture_request_id", None)
        self._record_active_calibration_event(
            "capture_failed",
            {"request_id": request_id, "message": str(msg), "state": self._get_droplet_capture_state()},
            level="warning",
        )
        self._clear_pending_capture()
        if cb:
            try:
                cb(None)
            except Exception as e:
                print(f"Callback raised after capture failure: {e}")
        if emit_capture_failed:
            try:
                self.model.calibration_manager.captureFailed.emit(msg)
            except Exception:
                pass

    def _on_pending_capture_timeout(self):
        if not bool(getattr(self, "pending_capture_active", False)):
            return
        request_id = getattr(self, "pending_capture_request_id", None)
        recovery_attempted = bool(getattr(self, "pending_capture_recovery_attempted", False))
        started = getattr(self, "pending_capture_started_monotonic", None)
        elapsed_s = None
        if started is not None:
            try:
                monotonic_fn = getattr(self, "_monotonic_fn", time.monotonic)
                elapsed_s = max(0.0, float(monotonic_fn()) - float(started))
            except Exception:
                elapsed_s = None
        suffix = "" if elapsed_s is None else f" after {elapsed_s:.1f}s"
        msg = f"Droplet capture timed out in controller{suffix}; releasing pending request."
        print(f"[Camera] {msg}")
        self._record_active_calibration_event(
            "capture_controller_timeout",
            {
                "request_id": request_id,
                "elapsed_s": elapsed_s,
                "recovery_attempted": recovery_attempted,
                "state": self._get_droplet_capture_state(),
            },
            level="warning",
        )
        if not recovery_attempted:
            callback = self.pending_capture_callback
            capture_context = self.pending_capture_context
            throughput_mode = bool(getattr(self, "pending_capture_throughput_mode", False))
            recovery_result = self._recover_current_droplet_capture(
                request_id,
                reason=f"controller_timeout request_id={request_id}",
            )
            recovery_ok = bool(recovery_result.get("ok"))
            ready_for_retry = bool(recovery_result.get("ready_for_retry", recovery_ok))
            if recovery_ok and ready_for_retry:
                self._clear_pending_capture()
                requeued = self._queue_capture_request(
                    callback=callback,
                    throughput_mode=throughput_mode,
                    capture_context=capture_context,
                    recovery_attempted=True,
                )
                if requeued:
                    return
                msg = "Droplet capture recovery completed, but retry capture could not be queued."
                try:
                    self.model.calibration_manager.captureFailed.emit(msg)
                except Exception:
                    pass
                return
            self._record_active_calibration_event(
                "capture_retry_suppressed_after_recovery",
                {
                    "request_id": request_id,
                    "result": dict(recovery_result or {}),
                    "message": msg,
                },
                level="warning",
            )
            self._fail_pending_capture(msg)
            return
        self._recover_current_droplet_capture(
            request_id,
            reason=f"second_controller_timeout request_id={request_id}",
        )
        self._fail_pending_capture(msg)

    def _recover_current_droplet_capture(self, request_id, *, reason):
        self._record_active_calibration_event(
            "camera_recovery_started",
            {"request_id": request_id, "reason": str(reason)},
            level="warning",
        )
        recovery_result = {"ok": False, "ready_for_retry": False, "reason": "recovery_not_available"}
        try:
            recover = getattr(self.machine, "recover_droplet_capture", None)
            if callable(recover):
                recovery_result = recover(reason=str(reason))
        except Exception as exc:
            recovery_result = {"ok": False, "ready_for_retry": False, "reason": str(exc)}
        if not isinstance(recovery_result, dict):
            recovery_result = {
                "ok": False,
                "ready_for_retry": False,
                "reason": f"invalid_recovery_result:{type(recovery_result).__name__}",
            }
        recovery_ok = bool(recovery_result.get("ok"))
        self._record_active_calibration_event(
            "camera_recovery_completed" if recovery_ok else "camera_recovery_failed",
            {
                "request_id": request_id,
                "result": dict(recovery_result or {}),
                "state": self._get_droplet_capture_state(),
            },
            level="info" if recovery_ok else "warning",
        )
        return dict(recovery_result or {})

    def _get_droplet_capture_state(self):
        try:
            getter = getattr(self.machine, "get_droplet_capture_state", None)
            if callable(getter):
                return dict(getter() or {})
            camera = getattr(self.machine, "droplet_camera", None)
            getter = getattr(camera, "get_capture_state", None)
            if callable(getter):
                return dict(getter() or {})
        except Exception as exc:
            return {"state_error": str(exc)}
        return {}

    @staticmethod
    def _classify_capture_queue_rejection(state):
        state = dict(state or {})
        if state.get("worker_active"):
            return "camera_worker_active"
        if state.get("cap_active"):
            return "camera_capture_active"
        if state.get("camera_started") is False:
            return "camera_not_started"
        backend_error = str(state.get("backend_error") or "")
        if "gpio_edge_fd_unavailable" in backend_error:
            return "camera_backend_unsupported"
        if backend_error or state.get("backend_available") is False:
            return "camera_backend_unavailable"
        if state.get("flash_fault"):
            return "flash_fault"
        return "machine_rejected"

    def _record_active_calibration_event(self, event_type, payload=None, *, level="info"):
        try:
            active = getattr(self.model.calibration_manager, "activeCalibration", None)
            recorder = getattr(active, "_record_event", None)
            if callable(recorder):
                recorder(str(event_type), payload or {}, level=level)
                return
            manager = getattr(self.model, "calibration_manager", None)
            record_process_event = getattr(manager, "record_process_event", None)
            if callable(record_process_event):
                record_process_event(str(event_type), payload or {}, level=level)
        except Exception:
            pass

    def _on_camera_capture_phase(self, payload):
        data = dict(payload or {}) if isinstance(payload, dict) else {"payload": payload}
        level = str(data.get("level") or "info")
        self._record_active_calibration_event("camera_capture_phase", data, level=level)

    def _emit_active_calibration_error(self, message: str):
        """
        Route runtime errors through the active calibration process when available.
        This ensures CalibrationManager receives the error via its normal process wiring.
        """
        msg = str(message)
        try:
            active = getattr(self.model.calibration_manager, "activeCalibration", None)
            if active is not None and hasattr(active, "calibrationError"):
                active.calibrationError.emit(msg)
                return
        except Exception:
            pass
        try:
            manager_error = getattr(self.model.calibration_manager, "calibrationError", None)
            if manager_error is not None and hasattr(manager_error, "emit"):
                manager_error.emit(msg)
        except Exception:
            pass

    def _is_flash_fault_latched(self) -> bool:
        cam = getattr(self.model, "droplet_camera_model", None)
        getter = getattr(cam, "get_flash_fault_latched", None)
        if callable(getter):
            try:
                return bool(getter())
            except Exception:
                return False
        return bool(getattr(cam, "flash_fault_latched", False))

    def _flash_fault_reason_text(self) -> str:
        cam = getattr(self.model, "droplet_camera_model", None)
        getter = getattr(cam, "get_flash_fault_reason_display", None)
        if callable(getter):
            try:
                reason = str(getter() or "").strip()
                if reason:
                    return reason
            except Exception:
                pass
        raw = str(getattr(cam, "flash_fault_reason", "") or "").strip().replace("_", " ")
        return raw or "Flash safety fault latched."

    def _handle_blocked_capture(self, callback=None):
        message = (
            "Droplet capture blocked because the flash safety latch is active. "
            f"{self._flash_fault_reason_text()}. Close and reopen the imager after PE8 is low."
        )
        print(f"[Camera] capture blocked: {message}")
        if callback is not None:
            try:
                callback(None)
            except Exception as exc:
                print(f"Callback raised after blocked capture: {exc}")
        self._emit_active_calibration_error(message)

    @staticmethod
    def _coerce_xyz_position_dict(position):
        if not isinstance(position, dict):
            return None
        out = {}
        for axis in ("X", "Y", "Z"):
            try:
                out[axis] = int(position[axis])
            except (KeyError, TypeError, ValueError):
                return None
        return out

    def _build_droplet_capture_save_metadata(self, capture_context=None):
        metadata = {
            "position_source": "controller_expected_position",
            "position_recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if capture_context is not None:
            metadata["capture_context"] = str(capture_context)

        expected = self._coerce_xyz_position_dict(getattr(self, "expected_position", None))
        if expected is not None:
            metadata["controller_expected_position"] = expected
            metadata["X_position"] = expected["X"]
            metadata["Y_position"] = expected["Y"]
            metadata["Z_position"] = expected["Z"]

        machine_position = None
        try:
            getter = getattr(getattr(self.model, "machine_model", None), "get_current_position_dict", None)
            if callable(getter):
                machine_position = self._coerce_xyz_position_dict(getter())
        except Exception:
            machine_position = None
        if machine_position is not None:
            metadata["machine_position"] = machine_position

        try:
            metadata["commands_idle_at_frame"] = bool(self.check_if_all_completed())
        except Exception:
            metadata["commands_idle_at_frame"] = None

        return metadata

    def handle_move_request(self, move_vector, callback):
        # Perform the move command then call the callback.
        try:
            dX, dY, dZ = move_vector
            ok = self.set_relative_coordinates(dX, dY, dZ, manual=False, handler=callback)
            if ok is False:
                self._emit_active_calibration_error(
                    f"Relative move rejected by safety guard: ({dX}, {dY}, {dZ})"
                )
                return
            print('Controller: Move request handled')
        except Exception as e:
            self._emit_active_calibration_error(f"Relative move failed: {e}")

    def handle_absolute_move_request(self, target_position, callback):
        # Perform the move command then call the callback.
        try:
            if type(target_position) == tuple or type(target_position) == list:
                target = {'X': target_position[0], 'Y': target_position[1], 'Z': target_position[2]}
            else:
                target = target_position.copy()
            ok = self.set_absolute_coordinates(
                target['X'],
                target['Y'],
                target['Z'],
                manual=False,
                handler=callback
            )
            if ok is False:
                self._emit_active_calibration_error(
                    f"Absolute move rejected by safety guard: ({target['X']}, {target['Y']}, {target['Z']})"
                )
                return
            print('Controller: Move request handled')
        except Exception as e:
            self._emit_active_calibration_error(f"Absolute move failed: {e}")

    # def handle_droplet_change_request(self, num_droplets,callback):
    #     self.set_imaging_droplets(num_droplets,callback=callback)
    def intermediate_callback(self):
        """
        A simple callback function that can be used to handle intermediate results.
        This is just a placeholder and can be customized as needed.
        """
        print(f'Intermediate result')

    def handle_settings_change_request(self, settings, callback):
        # Update the settings in the model and machine.
        settings = dict(settings or {})
        num_settings = len(settings)
        request_id = getattr(callback, "_settings_request_id", None)
        request_context = getattr(callback, "_settings_context", "")
        requested_settings = dict(getattr(callback, "_settings_requested_settings", settings) or {})
        request_created_monotonic_ns = getattr(callback, "_settings_created_monotonic_ns", None)
        timeout_ms = getattr(callback, "_settings_guard_timeout_ms", None)
        bind_callback = getattr(callback, "_settings_bind_callback", None)
        bound_commands = []
        completion_command_number = None

        if request_id and hasattr(self.machine, "get_settings_trace_snapshot"):
            def _trace_provider():
                timed_out_monotonic_ns = getattr(callback, "_settings_timed_out_monotonic_ns", None)
                return self.machine.get_settings_trace_snapshot(
                    str(request_id),
                    timed_out_monotonic_ns=timed_out_monotonic_ns,
                )

            try:
                setattr(callback, "_settings_trace_provider", _trace_provider)
            except Exception:
                pass

        current_call_back = self.intermediate_callback  # Default callback for intermediate settings.
        for i, (key, value) in enumerate(settings.items()):
            if i == num_settings - 1:
                current_call_back = callback
            trace_metadata = None
            if request_id:
                trace_metadata = {
                    "request_id": str(request_id),
                    "settings_context": str(request_context or ""),
                    "setting_key": str(key),
                    "requested_value": value,
                    "setting_index": int(i),
                    "settings_count": int(num_settings),
                    "request_created_monotonic_ns": request_created_monotonic_ns,
                }
            queued_command = None
            command_type = None
            if key == 'num_droplets':
                command_type = "SET_IMAGE_DROPLETS"
                queued_command = self.set_imaging_droplets(value,callback=current_call_back, trace_metadata=trace_metadata)
            elif key == 'flash_duration':
                command_type = "SET_WIDTH_F"
                queued_command = self.set_flash_duration(value, callback=current_call_back, trace_metadata=trace_metadata)
            elif key == 'flash_delay':
                command_type = "SET_DELAY_F"
                queued_command = self.set_flash_delay(value, callback=current_call_back, trace_metadata=trace_metadata)
                print(f'--Setting flash delay: {value}')
            elif key == 'exposure_time':
                command_type = "SET_EXPOSURE_TIME"
                queued_command = self.set_exposure_time(value, callback=current_call_back, trace_metadata=trace_metadata)
            elif key == 'print_pulse_width':
                command_type = "SET_WIDTH_P"
                queued_command = self.set_print_pulse_width(value, handler=current_call_back, trace_metadata=trace_metadata)
            elif key == 'refuel_pulse_width':
                command_type = "SET_WIDTH_R"
                queued_command = self.set_refuel_pulse_width(value, handler=current_call_back, trace_metadata=trace_metadata)
            elif key == 'print_pressure':
                print(f'--Setting print pressure: {value}')
                command_type = "ABSOLUTE_PRESSURE_P"
                queued_command = self.set_absolute_print_pressure(value, handler=current_call_back, trace_metadata=trace_metadata)
            elif key == 'refuel_pressure':
                command_type = "ABSOLUTE_PRESSURE_R"
                queued_command = self.set_absolute_refuel_pressure(value, handler=current_call_back, trace_metadata=trace_metadata)
            else:
                print(f'Unknown setting: {key}')
            if request_id:
                command_number = getattr(queued_command, "command_number", None)
                command_type = str(getattr(queued_command, "command_type", command_type or "") or "")
                bound_commands.append(
                    {
                        "command_number": None if command_number is None else int(command_number),
                        "command_type": command_type,
                        "setting_key": str(key),
                        "requested_value": value,
                    }
                )
                if i == num_settings - 1:
                    completion_command_number = None if command_number is None else int(command_number)

        if request_id:
            binding_payload = {
                "request_id": str(request_id),
                "context": str(request_context or ""),
                "settings": dict(requested_settings),
                "timeout_ms": timeout_ms,
                "request_created_monotonic_ns": request_created_monotonic_ns,
                "commands": bound_commands,
                "completion_command_number": completion_command_number,
            }
            register = getattr(self.machine, "register_settings_trace_binding", None)
            if callable(register):
                register(binding_payload)
            if callable(bind_callback):
                bind_callback(binding_payload)

    @QtCore.Slot()
    def _on_image_captured(self):
        """
        This slot is called when the droplet camera emits its image_captured_signal.
        It retrieves the latest frame, updates the model (and view), and if a
        callback is waiting, calls it.
        """
        frame = self.machine.droplet_camera.get_latest_frame()

        cap_info = None
        try:
            cap_info = self.machine.droplet_camera.get_last_capture_result()
        except Exception:
            cap_info = None

        self._complete_pending_capture_success(frame, cap_info=cap_info)

    @QtCore.Slot(object)
    def _on_capture_completed_payload(self, payload):
        payload = dict(payload or {}) if isinstance(payload, dict) else {"status": "failed", "error": str(payload)}
        request_id = payload.get("request_id")
        expected_request_id = getattr(self, "pending_capture_request_id", None)
        if not bool(getattr(self, "pending_capture_active", False)) or str(request_id) != str(expected_request_id):
            print(
                "[Camera] stale capture completion ignored "
                f"request_id={request_id} expected={expected_request_id} status={payload.get('status')}"
            )
            self._record_active_calibration_event(
                "capture_stale_completion_ignored",
                {
                    "request_id": request_id,
                    "expected_request_id": expected_request_id,
                    "status": payload.get("status"),
                    "generation": payload.get("generation"),
                    "cap_id": payload.get("cap_id"),
                    "state": self._get_droplet_capture_state(),
                },
                level="warning",
            )
            return

        status = str(payload.get("status") or "").lower()
        if status == "success" and payload.get("frame") is not None:
            capture_info = dict(payload.get("capture_info") or {})
            capture_info.setdefault("request_id", request_id)
            capture_info.setdefault("cap_id", payload.get("cap_id"))
            self._complete_pending_capture_success(payload.get("frame"), cap_info=capture_info)
            return

        msg = str(
            payload.get("error")
            or payload.get("reason")
            or payload.get("stale_reason")
            or "Droplet capture failed."
        )
        print(
            f"[Camera] capture failed request_id={request_id} status={status} "
            f"cap_id={payload.get('cap_id')} reason={msg}"
        )
        self._fail_pending_capture(msg)

    def _complete_pending_capture_success(self, frame, *, cap_info=None):
        request_id = getattr(self, "pending_capture_request_id", None)
        capture_context = getattr(self, "pending_capture_context", None)
        save_metadata = self._build_droplet_capture_save_metadata(capture_context=capture_context)

        callback = self.pending_capture_callback

        # Update the model and/or view (assuming your model has such a method)
        try:
            self.model.droplet_camera_model.update_image(frame, capture_info=cap_info, save_metadata=save_metadata)
            droplet_count = self._current_imaging_droplet_count()
            if droplet_count > 0:
                self._record_refuel_ejection_event(
                    droplet_count,
                    source="Controller.droplet_capture_completed",
                    event_kind="capture_completed",
                    count_kind="observed",
                    payload={
                        "request_id": request_id,
                        "capture_context": capture_context,
                        "cap_id": (cap_info or {}).get("cap_id") if isinstance(cap_info, dict) else None,
                    },
                )
        finally:
            self._record_active_calibration_event(
                "capture_completed",
                {
                    "request_id": request_id,
                    "cap_id": (cap_info or {}).get("cap_id") if isinstance(cap_info, dict) else None,
                    "capture_context": capture_context,
                    "state": self._get_droplet_capture_state(),
                },
            )
            self._clear_pending_capture()
        
        # If a callback was set for the capture, call it.
        if callback:
            callback(frame)

    @QtCore.Slot(str)
    def _on_capture_failed(self, msg: str):
        print(f"[Camera] capture failed: {msg}")
        self._fail_pending_capture(str(msg))

    def set_start_pressure(self, pressure):
        self.model.calibration_manager.set_start_pressure(pressure)

    def set_num_pressure_tests(self, num_tests):
        self.model.calibration_manager.set_num_pressure_tests(num_tests)

    def start_head_prime_calibration(self):
        # Tell the Model to start the head priming calibration.
        self.model.calibration_manager.start_head_prime_calibration()

    def start_nozzle_calibration(self):
        # Tell the Model to start the nozzle position calibration.
        self.model.calibration_manager.start_nozzle_calibration()

    def start_nozzle_focus_calibration(self):
        # Tell the Model to start the nozzle focus calibration.
        self.model.calibration_manager.start_nozzle_focus_calibration()

    def start_droplet_emergence_calibration(self):
        # Tell the Model to start the droplet emergence calibration.
        self.model.calibration_manager.start_droplet_emergence_calibration()

    # def start_pressure_calibration(self):
    #     # Tell the Model to start the pressure calibration.
    #     self.model.calibration_manager.start_pressure_calibration()

    # def start_trajectory_calibration(self):
    #     # Tell the Model to start the trajectory calibration.
    #     self.model.calibration_manager.start_trajectory_calibration()

    def start_pressure_scan_calibration(self):
        self.model.calibration_manager.start_pressure_scan_calibration()

    def start_prebreakup_morphology_calibration(
        self,
        *,
        start_pressure: float | None = None,
        pressure_step_psi: float = 0.03,
        prebreakup_lead_us: int = 600,
        fixed_prebreakup_delay_us: int | None = None,
        auto_scout_delay: bool = True,
        replicates_per_pressure: int = 3,
    ):
        self.model.calibration_manager.start_prebreakup_morphology_calibration(
            start_pressure=start_pressure,
            pressure_step_psi=pressure_step_psi,
            prebreakup_lead_us=prebreakup_lead_us,
            fixed_prebreakup_delay_us=fixed_prebreakup_delay_us,
            auto_scout_delay=auto_scout_delay,
            replicates_per_pressure=replicates_per_pressure,
        )

    def start_prebreakup_dataset_acquisition(
        self,
        *,
        plan_path: str | None = None,
        pressure_psi: float | None = None,
        pulse_width_us: int | None = None,
        delay_start_offset_us: int = 100,
        delay_stop_offset_us: int = 2200,
        delay_step_us: int = 50,
        replicates_per_delay: int = 2,
        analyze_frames: bool = False,
        save_overlays: bool = False,
    ):
        self.model.calibration_manager.start_prebreakup_dataset_acquisition(
            plan_path=plan_path,
            pressure_psi=pressure_psi,
            pulse_width_us=pulse_width_us,
            delay_start_offset_us=delay_start_offset_us,
            delay_stop_offset_us=delay_stop_offset_us,
            delay_step_us=delay_step_us,
            replicates_per_delay=replicates_per_delay,
            analyze_frames=analyze_frames,
            save_overlays=save_overlays,
        )

    def start_pressure_sweep_characterization(self):
        self.model.calibration_manager.start_pressure_sweep_characterization()
    
    def start_droplet_timecourse_process(self):
        self.model.calibration_manager.start_droplet_timecourse_process()

    def start_online_stream_calibration(self):
        self.model.calibration_manager.start_online_stream_calibration()

    def start_droplet_calibration_sequence(self):
        return self.model.calibration_manager.start_droplet_calibration_sequence()

    def start_stream_calibration_sequence(self):
        return self.model.calibration_manager.start_stream_calibration_sequence()

    def start_stream_gravimetric_capture(self, starting_mass_mg, rep_override=None, notes="", capture_mode="timecourse"):
        return self.model.calibration_manager.start_stream_gravimetric_capture(
            starting_mass_mg,
            rep_override=rep_override,
            notes=notes,
            capture_mode=capture_mode,
        )

    def _begin_gripper_refresh_suspend_sequence(
        self,
        *,
        manager,
        state_getter,
        begin_refresh,
        begin_suspend,
        mark_suspended,
        report_failure,
    ):
        result = begin_refresh()
        if isinstance(result, tuple) and result and (result[0] is False):
            return result

        state = state_getter()
        pulse_duration_ms = int(state.get("gripper_pulse_duration_snapshot_ms") or 0)
        gripper_was_open = bool(state.get("gripper_was_open"))
        if pulse_duration_ms <= 0:
            report_failure(
                "Current gripper pulse duration is unavailable; cannot pause auto-refresh.",
            )
            return False, "Current gripper pulse duration is unavailable; cannot pause auto-refresh."

        def _after_gripper_suspend():
            finish_result = mark_suspended()
            if isinstance(finish_result, tuple) and finish_result and (finish_result[0] is False):
                report_failure(
                    str(finish_result[1] or "Failed to finalize gripper refresh suspension."),
                )

        def _after_gripper_refresh():
            suspend_result = begin_suspend()
            if isinstance(suspend_result, tuple) and suspend_result and (suspend_result[0] is False):
                report_failure(
                    str(suspend_result[1] or "Failed to pause gripper auto-refresh."),
                )
                return
            parked_ok = self.set_gripper_params(
                manager.STREAM_CAPTURE_PARKED_GRIPPER_REFRESH_MS,
                pulse_duration_ms,
                handler=_after_gripper_suspend,
                manual=False,
            )
            if parked_ok is False:
                report_failure(
                    "Failed to send gripper auto-refresh pause command.",
                )

        refresh_ok = (
            self.open_gripper(handler=_after_gripper_refresh)
            if gripper_was_open
            else self.close_gripper(handler=_after_gripper_refresh)
        )
        if refresh_ok is False:
            report_failure(
                "Failed to enqueue the initial gripper refresh pulse.",
            )
            return False, "Failed to enqueue the initial gripper refresh pulse."
        return True, ""

    def _begin_gripper_restore_sequence(
        self,
        *,
        state_getter,
        begin_restore,
        mark_restored,
        report_failure,
    ):
        result = begin_restore()
        if isinstance(result, tuple) and result and (result[0] is False):
            return result

        state = state_getter()
        refresh_period_ms = int(state.get("gripper_refresh_period_snapshot_ms") or 0)
        pulse_duration_ms = int(state.get("gripper_pulse_duration_snapshot_ms") or 0)
        if refresh_period_ms <= 0 or pulse_duration_ms <= 0:
            report_failure(
                "Original gripper refresh settings are unavailable; cannot restore auto-refresh.",
            )
            return False, "Original gripper refresh settings are unavailable; cannot restore auto-refresh."

        def _after_gripper_restore():
            finish_result = mark_restored()
            if isinstance(finish_result, tuple) and finish_result and (finish_result[0] is False):
                report_failure(
                    str(finish_result[1] or "Failed to finalize gripper refresh restore."),
                )

        restore_ok = self.set_gripper_params(
            refresh_period_ms,
            pulse_duration_ms,
            handler=_after_gripper_restore,
            manual=False,
        )
        if restore_ok is False:
            report_failure(
                "Failed to send gripper auto-refresh restore command.",
            )
            return False, "Failed to send gripper auto-refresh restore command."
        return True, ""

    def begin_stream_gravimetric_capture_gripper_preamble(self):
        manager = self.model.calibration_manager
        return self._begin_gripper_refresh_suspend_sequence(
            manager=manager,
            state_getter=manager.get_stream_gravimetric_capture_state,
            begin_refresh=manager.begin_stream_gravimetric_capture_gripper_refresh,
            begin_suspend=manager.begin_stream_gravimetric_capture_gripper_suspend,
            mark_suspended=manager.mark_stream_gravimetric_capture_gripper_suspended,
            report_failure=manager.report_stream_gravimetric_capture_gripper_preamble_failure,
        )

    def begin_stream_gravimetric_capture_gripper_restore(self):
        manager = self.model.calibration_manager
        return self._begin_gripper_restore_sequence(
            state_getter=manager.get_stream_gravimetric_capture_state,
            begin_restore=manager.begin_stream_gravimetric_capture_gripper_restore,
            mark_restored=manager.mark_stream_gravimetric_capture_gripper_restored,
            report_failure=manager.report_stream_gravimetric_capture_gripper_restore_failure,
        )

    def begin_stream_calibration_sequence_gripper_preamble(self):
        manager = self.model.calibration_manager
        return self._begin_gripper_refresh_suspend_sequence(
            manager=manager,
            state_getter=manager.get_stream_calibration_sequence_state,
            begin_refresh=manager.begin_stream_calibration_sequence_gripper_refresh,
            begin_suspend=manager.begin_stream_calibration_sequence_gripper_suspend,
            mark_suspended=manager.mark_stream_calibration_sequence_gripper_suspended,
            report_failure=manager.report_stream_calibration_sequence_gripper_preamble_failure,
        )

    def begin_stream_calibration_sequence_gripper_restore(self):
        manager = self.model.calibration_manager
        return self._begin_gripper_restore_sequence(
            state_getter=manager.get_stream_calibration_sequence_state,
            begin_restore=manager.begin_stream_calibration_sequence_gripper_restore,
            mark_restored=manager.mark_stream_calibration_sequence_gripper_restored,
            report_failure=manager.report_stream_calibration_sequence_gripper_restore_failure,
        )

    def begin_droplet_calibration_sequence_gripper_preamble(self):
        manager = self.model.calibration_manager
        return self._begin_gripper_refresh_suspend_sequence(
            manager=manager,
            state_getter=manager.get_droplet_calibration_sequence_state,
            begin_refresh=manager.begin_droplet_calibration_sequence_gripper_refresh,
            begin_suspend=manager.begin_droplet_calibration_sequence_gripper_suspend,
            mark_suspended=manager.mark_droplet_calibration_sequence_gripper_suspended,
            report_failure=manager.report_droplet_calibration_sequence_gripper_preamble_failure,
        )

    def begin_droplet_calibration_sequence_gripper_restore(self):
        manager = self.model.calibration_manager
        return self._begin_gripper_restore_sequence(
            state_getter=manager.get_droplet_calibration_sequence_state,
            begin_restore=manager.begin_droplet_calibration_sequence_gripper_restore,
            mark_restored=manager.mark_droplet_calibration_sequence_gripper_restored,
            report_failure=manager.report_droplet_calibration_sequence_gripper_restore_failure,
        )

    def finalize_stream_gravimetric_capture(self, ending_mass_mg, rep_override=None, notes=""):
        return self.model.calibration_manager.finalize_stream_gravimetric_capture(
            ending_mass_mg,
            rep_override=rep_override,
            notes=notes,
        )

    def discard_stream_gravimetric_capture(self, reason="operator_discarded"):
        return self.model.calibration_manager.discard_stream_gravimetric_capture(
            reason=reason,
        )

    def begin_stream_gravimetric_capture_loading_move(self):
        return self.model.calibration_manager.begin_stream_gravimetric_capture_loading_move()

    def on_stream_gravimetric_capture_loading_reached(self):
        return self.model.calibration_manager.mark_stream_gravimetric_capture_loading_reached()

    def begin_stream_gravimetric_capture_camera_return(self):
        return self.model.calibration_manager.begin_stream_gravimetric_capture_camera_return()

    def on_stream_gravimetric_capture_camera_reached(self):
        return self.model.calibration_manager.mark_stream_gravimetric_capture_camera_reached()

    def report_stream_gravimetric_capture_move_failure(self, target, error_message=""):
        return self.model.calibration_manager.report_stream_gravimetric_capture_move_failure(
            target=target,
            error_message=error_message,
        )

    # def start_pressure_scan_calibration(self):
    #     # Tell the Model to start the pressure scan calibration.
    #     self.model.calibration_manager.start_pressure_scan_calibration()

    def start_trajectory_calibration(self):
        # Tell the Model to start the trajectory calibration.
        self.model.calibration_manager.start_trajectory_calibration()

    def start_pressure_trajectory_calibration(self):
        # Tell the Model to start the pressure trajectory calibration.
        self.model.calibration_manager.start_pressure_trajectory_calibration()

    def start_droplet_search_calibration(self):
        # Tell the Model to start the droplet search calibration.
        self.model.calibration_manager.start_droplet_search_calibration()

    def start_droplet_characterization_calibration(self):
        # Tell the Model to start the droplet characterization calibration.
        self.model.calibration_manager.start_manual_droplet_characterization()

    def start_all_calibrations(self):
        # Tell the Model to start all calibrations.
        self.model.calibration_manager.add_all_calibrations_to_queue()

    def stop_calibration(self):
        # Tell the Model to stop the calibration.
        self.model.calibration_manager.stop()

    def start_flash(self):
        self.machine.start_flash()

    def stop_flash(self):
        self.machine.stop_flash()

    def center_nozzle_in_camera(self,position=None,callback=None):
        centered_nozzle_position = self.model.calibration_manager.get_nozzle_center()
        # Create a copy of the centered nozzle position
        target_position = centered_nozzle_position.copy()
        if target_position is None:
            print('Nozzle center not found')
            return
        if position == 'top':
            current = self.model.droplet_camera_model.get_center_in_pixels()
            print(f'-Current center in pixels: {current}')
            move_vector = self.model.droplet_camera_model.calculate_move_to_top_center(current,offset=150)
            print(f'-Move vector to top center: {move_vector}')
            dX, dY, dZ = move_vector
            target_position['X'] += dX
            target_position['Y'] += dY
            target_position['Z'] += dZ
        print(f'-Centering nozzle at position: {target_position}')
        self.set_absolute_coordinates(target_position['X'],target_position['Y'],target_position['Z'],handler=callback)

    # --------------------------
    # Legacy commands
    # --------------------------
    def update_balance_prediction_models(self, target_volume: float):
        """Called by MassCalibrationDialog.handle_model_change(...)"""
        if not self.balance or self.profile.name != "legacy":
            return
        pred_path = self.model.calibration_model.get_selected_model_path()
        res_path  = self.model.calibration_model.get_selected_resistance_model_path()
        if pred_path and res_path:
            self.balance.update_prediction_models(pred_path, res_path, target_volume)
    
    # def start_mass_stabilization_timer(self):
    #     from PySide6 import QtCore
    #     QtCore.QTimer.singleShot(2000, self.model.calibration_model.check_for_final_mass)

    # def print_calibration_droplets(self, droplets, manual=False, pulse_width=None):
    #     """Used by MassCalibrationDialog when initial mass is captured."""
    #     if pulse_width is None:
    #         pulse_width = int(getattr(self.model.machine_model, "pulse_width", 0) or 0)

    #     # ensure controller/machine uses that pulse width
    #     if pulse_width:
    #         self.set_print_pulse_width(pulse_width, manual=False)

    #     # if virtual balance is running, enqueue a simulated droplet event
    #     if self.balance and getattr(self.balance, "simulate", False):
    #         self.machine.balance_droplets.append([int(droplets), int(pulse_width)])

    #     # print droplets; when finished, wait then allow final mass capture
    #     self.machine.print_droplets(int(droplets), handler=self.start_mass_stabilization_timer, kwargs={}, manual=manual)


    # -------------------------
    # Preprogrammed sequences
    # -------------------------
    def start_preprogrammed_sequence(self, seq_id: str, delay_s: float = 0.0, **params):
        """
        Start a named sequence after a delay with countdown shown in UI.
        During countdown, TX is hard-paused (Machine.set_sequence_pause(True)).
        """
        if seq_id not in getattr(self, "_sequence_builders", {}):
            self.sequence_error.emit(f"Unknown sequence: {seq_id}")
            return

        if self._seq_state in ("countdown", "running"):
            self.sequence_error.emit("A sequence is already in progress.")
            return

        # Basic safety checks
        try:
            if not self.model.machine_model.is_connected():
                self.sequence_error.emit("Machine is not connected.")
                return
        except Exception:
            # If your model API differs, you can remove this check
            pass

        if not self.machine.check_if_all_completed():
            self.sequence_error.emit("Cannot start: command queue is not empty.")
            return

        delay_s = max(0.0, float(delay_s))
        self._seq_id = seq_id
        self._seq_params = dict(params)

        # Hard-pause TX during countdown so nothing can move early
        self.machine.set_sequence_pause(True)

        if delay_s <= 0.0:
            self.sequence_countdown_s.emit(0.0)
            self._begin_sequence()
            return

        self._seq_deadline_monotonic = self._monotonic_fn() + delay_s
        self._seq_state = "countdown"
        self.sequence_state_changed.emit(self._seq_state)
        self.sequence_countdown_s.emit(delay_s)
        self._seq_timer.start()

    def cancel_preprogrammed_sequence(self):
        """Cancels only the countdown stage (does not try to stop an already-running queue)."""
        if self._seq_state != "countdown":
            return
        self._seq_timer.stop()
        self._seq_state = "idle"
        self.sequence_state_changed.emit(self._seq_state)
        self.sequence_countdown_s.emit(0.0)
        self._seq_id = None
        self._seq_params = {}
        self.machine.set_sequence_pause(False)

    def _on_seq_tick(self):
        remaining = self._seq_deadline_monotonic - self._monotonic_fn()
        if remaining <= 0:
            self._seq_timer.stop()
            self.sequence_countdown_s.emit(0.0)
            self._begin_sequence()
            return
        self.sequence_countdown_s.emit(remaining)

    def _begin_sequence(self):
        # Re-check queue: if anything got queued during countdown, abort
        if not self.machine.check_if_all_completed():
            self._abort_sequence("Queue became non-empty during countdown; aborting.")
            return
        
        self.update_expected_with_current()

        seq_id = self._seq_id
        builder = self._sequence_builders.get(seq_id)
        if builder is None:
            self._abort_sequence(f"Unknown sequence: {seq_id}")
            return

        self._seq_state = "running"
        self.sequence_state_changed.emit(self._seq_state)
        self.sequence_started.emit(seq_id)

        # Keep TX paused while we enqueue the whole block
        self.machine.set_sequence_pause(True)

        try:
            builder()  # enqueue commands using controller/machine methods
        except Exception as e:
            self._abort_sequence(f"Sequence build failed: {e}")
            return
        finally:
            # Ensure TX is resumed even if builder raises (abort handles state too)
            pass

        # Resume TX and nudge sender
        self.machine.set_sequence_pause(False)
        try:
            self.machine.send_next_command()
        except Exception:
            pass

        # If a sequence enqueued nothing (edge case), complete immediately
        if self.machine.check_if_all_completed():
            self._finish_sequence()

    def _abort_sequence(self, msg: str):
        self._seq_timer.stop()
        self.machine.set_sequence_pause(False)
        self._seq_state = "idle"
        self.sequence_state_changed.emit(self._seq_state)
        self.sequence_error.emit(msg)
        self._seq_id = None
        self._seq_params = {}
        self.sequence_countdown_s.emit(0.0)

    def _finish_sequence(self):
        seq_id = self._seq_id
        self._seq_state = "idle"
        self.sequence_state_changed.emit(self._seq_state)
        if seq_id:
            self.sequence_completed.emit(seq_id)
        self._seq_id = None
        self._seq_params = {}
        self.sequence_countdown_s.emit(0.0)

    def _on_commands_completed_for_sequence(self):
        """Called whenever the queue drains; if we’re running a sequence, mark it done."""
        if self._seq_state == "running":
            self._finish_sequence()

    # -------------------------
    # Example sequence builders
    # -------------------------

    def _seq_pickup_slot_imager_return(self):
        """
        Pick up a head from a slot, move to imager, return to same slot.
        NOTE: Adjust location names if yours differ.
        """
        slot_1based = int(self._seq_params.get("slot", 1))
        slot = max(1, min(slot_1based, 4)) - 1

        # These calls enqueue many commands:
        self.pick_up_printer_head(slot)
        self.move_to_location("camera")      # <-- change if your imager location is named differently
        self.drop_off_printer_head(slot)

    def _seq_led_on_wait_off(self):
        """
        Turn LEDs on, wait N seconds (firmware WAIT), then off.
        """
        on_s = float(self._seq_params.get("on_s", 5.0))
        on_ms = max(1, int(on_s * 1000))

        self.machine.LED_on()
        self.machine.wait_ms(on_ms)
        self.machine.LED_off()

    def _seq_imager_plate_imager(self):
        """
        Move from imager to plate and back.
        NOTE: Adjust location names if yours differ.
        """
        self.move_to_location("camera")   # imager
        self.move_to_location("plate")    # plate
        self.move_to_location("camera")   # back

    def _seq_snake_grid_droplet_print(self):
        """
        Prints a snake-pattern grid of droplets starting at the current position.

        Pattern:
        - For each row:
            - print droplets at current position
            - move in Y between columns (direction alternates each row)
            - at end of row, move +X to next row (no Y reset; snake continues)

        Params expected in self._seq_params:
        rows (int)      : number of rows (X direction)
        cols (int)      : number of columns (Y direction)
        step (int)      : relative move in "steps" between spots (applied to both X and Y)
        droplets (int)  : number of droplets to print at each spot
        """
        rows = int(self._seq_params.get("rows", 1))
        cols = int(self._seq_params.get("cols", 1))
        step = int(self._seq_params.get("step", 0))
        droplets = int(self._seq_params.get("droplets", 1))

        # basic sanitation
        rows = max(1, rows)
        cols = max(1, cols)
        droplets = max(1, droplets)
        # allow step = 0 (prints all on same spot), but clamp negatives
        step = max(0, step)

        for r in range(rows):
            direction = +1 if (r % 2 == 0) else -1  # snake direction along Y

            for c in range(cols):
                # Print droplets at this grid point
                self.print_droplets(droplets)

                # Move to next column (Y) unless we're at end of the row
                if c < (cols - 1):
                    dy = direction * step
                    if dy != 0:
                        self.set_relative_Y(dy)

            # Move to next row (X) unless we're at last row
            if r < (rows - 1):
                if step != 0:
                    self.set_relative_X(step)

    def _seq_droplet_walk_y(self):
        """
        Demo sequence: Print increasing droplet counts while stepping +Y.

        Default behavior:
        spot 1: 1 droplet
        move +Y (step)
        spot 2: 2 droplets
        move +Y (step)
        spot 3: 3 droplets
        ...

        Params in self._seq_params:
        n_spots (int)        : number of spots along the line (>=1)
        step_y (int)         : relative Y move between spots, in steps (>=0)
        start_droplets (int) : droplets at first spot (>=1), default 1
        inc_droplets (int)   : increment each spot (>=0), default 1
        """
        n_spots = int(self._seq_params.get("n_spots", 5))
        step_y = int(self._seq_params.get("step_y", 50))
        start = int(self._seq_params.get("start_droplets", 1))
        inc = int(self._seq_params.get("inc_droplets", 1))

        n_spots = max(1, n_spots)
        step_y = max(0, step_y)
        start = max(1, start)
        inc = max(0, inc)

        droplets = start

        for i in range(n_spots):
            self.print_droplets(droplets)

            if i < (n_spots - 1) and step_y != 0:
                self.set_relative_Y(step_y)

            droplets += inc

    def _seq_bridge_and_pull_y(self):
        """
        Bridge & Pull demo in Y.

        Steps:
        1) Print payload droplets at current position.
        2) Move +Y by separation_steps.
        3) Print target droplets.
        4) Print 1-droplet bridge spots from target toward payload:
                (move -Y by bridge_spacing_steps, print 1 droplet) repeated.

        Params in self._seq_params:
        payload_droplets (int)       : droplets at payload position
        target_droplets (int)        : droplets at target position
        separation_steps (int)       : +Y distance between payload and target
        bridge_spacing_steps (int)   : spacing between bridge droplets (printed from target toward payload)
        """
        payload = int(self._seq_params.get("payload_droplets", 5))
        target = int(self._seq_params.get("target_droplets", 10))
        separation = int(self._seq_params.get("separation_steps", 200))
        bridge_spacing = int(self._seq_params.get("bridge_spacing_steps", 50))

        payload = max(1, payload)
        target = max(1, target)
        separation = max(0, separation)
        bridge_spacing = max(1, bridge_spacing)  # must be >=1 to avoid infinite loops

        # 1) Payload at start position
        self.print_droplets(payload)

        # 2) Move to target position (+Y)
        if separation != 0:
            self.set_relative_Y(separation)

        # 3) Target droplet
        self.print_droplets(target)

        # 4) Bridge droplets from target toward payload.
        #    Compute how many bridge points to place so that the last bridge point is within
        #    one bridge_spacing of the payload (or closer), without necessarily printing on top of payload.
        if separation == 0:
            return

        n_bridge = max(0, int(math.ceil(separation / bridge_spacing)) - 1)

        for _ in range(n_bridge):
            self.set_relative_Y(-bridge_spacing)
            self.print_droplets(1)

    def _seq_bridge_pull_y_3step(self):
        """
        3-step Bridge & Pull demo in +Y.

        Workflow:
        - Print initial payload once at the current position.
        - For i in {1..3}:
            - Move +Y by separation_i
            - Print target_i droplets
            - Print bridge droplets from target toward payload (move -Y in steps of bridge_spacing_i, print 1 droplet each)
            - Return to the target position (so the next step starts from "where the droplet likely moved")

        Params in self._seq_params:
        payload_droplets (int)

        step1_target_droplets (int)
        step1_separation_steps (int)
        step1_bridge_spacing_steps (int)

        step2_target_droplets (int)
        step2_separation_steps (int)
        step2_bridge_spacing_steps (int)

        step3_target_droplets (int)
        step3_separation_steps (int)
        step3_bridge_spacing_steps (int)
        """

        def _bridge_pull_one_step(separation: int, target_droplets: int, bridge_spacing: int):
            """
            Executes one bridge & pull step starting from the current payload position.
            After this returns, the head is positioned back at the target location (payload advanced).
            """
            separation = max(0, int(separation))
            target_droplets = max(1, int(target_droplets))
            bridge_spacing = max(1, int(bridge_spacing))  # avoid infinite loop

            # Move to target position (+Y)
            if separation != 0:
                self.set_relative_Y(separation)

            # Print target droplet cluster
            self.print_droplets(target_droplets)

            # If no separation, nothing to bridge
            if separation == 0:
                return

            # Number of bridge points so the last bridge is within <= bridge_spacing of payload
            n_bridge = max(0, int(math.ceil(separation / bridge_spacing)) - 1)

            # Print bridging droplets from target back toward payload
            for _ in range(n_bridge):
                self.set_relative_Y(-bridge_spacing)
                self.print_droplets(1)

            # Return to target position (so next step starts from expected "moved" droplet location)
            if n_bridge > 0:
                self.set_relative_Y(n_bridge * bridge_spacing)

        payload = max(1, int(self._seq_params.get("payload_droplets", 5)))
        self.print_droplets(payload)

        # Step 1
        _bridge_pull_one_step(
            separation=self._seq_params.get("step1_separation_steps", 200),
            target_droplets=self._seq_params.get("step1_target_droplets", 10),
            bridge_spacing=self._seq_params.get("step1_bridge_spacing_steps", 50),
        )

        # Step 2
        _bridge_pull_one_step(
            separation=self._seq_params.get("step2_separation_steps", 200),
            target_droplets=self._seq_params.get("step2_target_droplets", 10),
            bridge_spacing=self._seq_params.get("step2_bridge_spacing_steps", 50),
        )

        # Step 3
        _bridge_pull_one_step(
            separation=self._seq_params.get("step3_separation_steps", 200),
            target_droplets=self._seq_params.get("step3_target_droplets", 10),
            bridge_spacing=self._seq_params.get("step3_bridge_spacing_steps", 50),
        )

