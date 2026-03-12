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

from hardware.profile import CURRENT_PROFILE, HardwareProfile
from hardware.null_devices import NullCamera

class Controller(QObject):
    """Controller class for the application."""
    array_complete = Signal()
    update_slots_signal = Signal()
    update_volumes_in_view_signal = Signal()
    error_occurred_signal = Signal(str,str)

    # DFU signals
    dfu_progress = QtCore.Signal(int)
    dfu_stage    = QtCore.Signal(str)
    dfu_finished = QtCore.Signal(bool, str)
    dfu_output   = QtCore.Signal(str)

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

        self._bin_path_current = (self._repo_root / "firmware" / "freeRTOS_LabCraft.bin").resolve()
        self._bin_path_legacy  = (self._repo_root / "firmware" / "freeRTOS_LabCraft_legacy.bin").resolve()

        # This variable will temporarily hold the callback for the next capture.
        self.pending_capture_callback = None

        # Connect the machine's signals to the controller's handlers
        self.machine.status_updated.connect(self.handle_status_update)
        self.machine.error_occurred.connect(self.handle_error)
        self.machine.homing_completed.connect(self.home_complete_handler)
        self.machine.gripper_open.connect(self.model.machine_model.open_gripper)
        self.machine.gripper_closed.connect(self.model.machine_model.close_gripper)
        
        self.machine.machine_connected_signal.connect(self.update_machine_connection_status)
        self.machine.reset_report_received.connect(self.handle_reset_report)
        self.machine.disconnect_complete_signal.connect(self.reset_board)
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
            self.machine.droplet_camera.image_captured_signal.connect(self._on_image_captured)
            self.machine.droplet_camera.capture_failed_signal.connect(self._on_capture_failed)
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
            self.machine.droplet_camera.image_captured_signal.disconnect(self._on_image_captured)
            self.machine.droplet_camera.capture_failed_signal.disconnect(self._on_capture_failed)
        except Exception:
            pass

    def handle_status_update(self, status_dict):
        """Handle the status update and update the machine model."""
        self.model.update_state(status_dict)

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

    def set_axis_accel(self, axis_idx, accel):
        """Set the acceleration for a specific axis."""
        self.machine.set_axis_accel(axis_idx, accel)

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

        bin_path = self._bin_path_legacy if manual else self._bin_path_current

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
        try:
            self.update_expected_with_current()
        except Exception:
            pass

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

    def set_absolute_print_pressure(self, pressure,handler=None, manual=False):
        """Set the absolute pressure for the machine."""
        #print(f"Setting absolute pressure: {pressure}")
        self.machine.set_absolute_print_pressure(pressure,manual=manual,handler=handler)

    def set_absolute_refuel_pressure(self, pressure, handler=None, manual=False):
        """Set the absolute pressure for the machine."""
        #print(f"Setting absolute pressure: {pressure}")
        self.machine.set_absolute_refuel_pressure(pressure,manual=manual,handler=handler)

    def set_print_pulse_width(self, pulse_width,handler=None, manual=False,update_model=False):
        """Set the pulse width for the machine."""
        #print(f"Setting pulse width: {pulse_width}")
        if update_model:
            self.model.machine_model.update_print_pulse_width(pulse_width)
        self.machine.set_print_pulse_width(pulse_width,manual=manual,handler=handler)

    def set_refuel_pulse_width(self, pulse_width, handler=None, manual=False,update_model=False):
        """Set the pulse width for the machine."""
        #print(f"Setting pulse width: {pulse_width}")
        if update_model:
            self.model.machine_model.update_refuel_pulse_width(pulse_width)
        self.machine.set_refuel_pulse_width(pulse_width,manual=manual,handler=handler)

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
        if success and success_2:
            self.model.machine_model.toggle_regulation_state()  # Update the model state

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

    def move_to_location(self, name, direct=True, safe_y=False, x_offset: int = 0,z_offset: int = 0,manual=False,coords=None,override=False,ignore_safe_height=False):
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

        if self.set_absolute_coordinates(
            target['X'], target['Y'], target['Z'],
            manual=manual,
            override=override,
            handler=self.update_location_handler,
            kwargs={'name': name}
        ) is False:
            self.error_occurred_signal.emit('Move Error', 'Failed to move to target coordinates')
            return False

        self.expected_location = name
        return True
        
    def open_gripper(self,handler=None):
        """Open the gripper."""
        self.machine.open_gripper(handler=handler)

    def close_gripper(self,handler=None):
        """Close the gripper."""
        self.machine.close_gripper(handler=handler)

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

    def pick_up_printer_head(self,slot,manual=False):
        """Pick up a printer head from the rack."""
        if manual == True:
            status = self.machine.check_if_all_completed()
            if status == False:
                print('Cannot pick up: Commands are still running')
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
            self.move_to_location(name,x_offset=8000,coords=coords)

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
            status = self.machine.check_if_all_completed()
            if status == False:
                print('Cannot drop off: Commands are still running')
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
            self.move_to_location(name,x_offset=8000,coords=coords,override=True,ignore_safe_height=True)
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
    
    def print_droplets(self,droplets,handler=None,kwargs=None,manual=False,expected_volume=None):
        """Print a specified number of droplets."""
        if not self.model.machine_model.regulating_print_pressure:
            self.error_occurred_signal.emit('Error','Pressure regulation is not enabled')
            print('Cannot print: Pressure regulation is not enabled')
            return
        if self.profile.name != "legacy":
            # fall back to your current implementation
            return self.machine.print_droplets(droplets, handler=handler, kwargs=kwargs, manual=manual)
        
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

        self.machine.print_droplets(droplets,handler=handler,kwargs=kwargs,manual=manual)

    def print_only(self,droplets,manual=False):
        """Activate the print valve a specified number of times without refueling."""
        self.machine.print_only(droplets,manual=manual)
    
    def refuel_only(self,droplets,manual=False):
        """Activate the refuel valve a specified number of times without printing."""
        self.machine.refuel_only(droplets,manual=manual)

    def print_calibration_droplets(self,droplets,manual=False,pressure=None,pulse_width=None):
        """Print a specified number of droplets for calibration."""
        print('Controller: Printing calibration droplets')
        self.machine.print_calibration_droplets(droplets,manual=manual,pressure=pressure,pulse_width=pulse_width)

    def start_mass_stabilization_timer(self):
        """Create a single shot timer that when triggered it will signal the model to check for the final stable mass."""
        print('Starting mass stabilization timer...')
        QtCore.QTimer.singleShot(3000, self.model.calibration_model.check_for_final_mass)


    def well_complete_handler(self,well_id=None,stock_id=None,target_droplets=None,update_volume=False):
        self.model.well_plate.get_well(well_id).record_stock_print(stock_id,target_droplets)
        if update_volume:
            self.model.rack_model.get_gripper_printer_head().record_droplet_volume_lost(target_droplets)
        self.model.experiment_model.create_progress_file()
        #print(f'Printing complete for well {well_id}')

    def last_well_complete_handler(self,well_id=None,stock_id=None,target_droplets=None,update_volume=False):
        # Reset acceleration and move to pause after the queue is processed
        def finalize_printing():
            try:
                if update_volume:
                    self.model.rack_model.get_gripper_printer_head().record_droplet_volume_lost(target_droplets)
                # self.machine.reset_acceleration()
                # self.exit_print_mode()
                self.disable_print_profile()
                self.move_to_location('pause')
                self.move_to_location('pause',z_offset=-5000)
                self.model.well_plate.get_well(well_id).record_stock_print(stock_id, target_droplets)
                self.model.experiment_model.create_progress_file()
                self.array_complete.emit()
                print('---Printing complete---')
            except Exception as exc:
                msg = f'Failed to finalize array printing for well {well_id}: {exc}'
                print(msg)
                self.error_occurred_signal.emit('Print Array Error', msg)
        
        # Ensure that this is done after the command queue has been fully processed
        QtCore.QTimer.singleShot(0, finalize_printing)

    def refill_printer_head_handler(self,well_id=None,stock_id=None,target_droplets=None,update_volume=False):
        # Reset acceleration and move to pause after the queue is processed
        def refill_printer_head():
            if update_volume:
                self.model.rack_model.get_gripper_printer_head().record_droplet_volume_lost(target_droplets)
            self.machine.reset_acceleration()
            self.exit_print_mode()
            self.move_to_location('pause')
            self.model.well_plate.get_well(well_id).record_stock_print(stock_id, target_droplets)
            self.model.experiment_model.create_progress_file()
            print('---Must reload printer head---')
            self.error_occurred_signal.emit('Error','Printer head needs to be reloaded')
        
        # Ensure that this is done after the command queue has been fully processed
        QtCore.QTimer.singleShot(0, refill_printer_head)

    def reset_single_array(self):
        """Resets the droplet count for all wells in the well plate for the currently loaded stock solution."""
        active_printer_head = self.model.rack_model.get_gripper_printer_head()
        self.model.well_plate.reset_all_wells_for_stock(active_printer_head.get_stock_id())
        self.model.experiment_model.create_progress_file()

    def reset_all_arrays(self):
        """Resets the droplet count for all wells in the well plate for all stock solutions."""
        self.model.well_plate.reset_all_wells()
        self.model.experiment_model.create_progress_file()
        self.update_slots_signal.emit()

    def enter_print_mode(self):
        """Enter print mode."""
        self.machine.enter_print_mode()

    def exit_print_mode(self):
        """Exit print mode."""
        self.machine.exit_print_mode()
    
    def print_array(self):
        '''
        Iterates through all wells with an assigned reaction and prints the 
        required number of droplets for the currently loaded printer head.
        '''
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
        
        self.close_gripper()
        # self.wait_command()

        self.move_to_location('pause',z_offset=-5000)
        self.move_to_location('pause', ignore_safe_height=True)
        # self.machine.change_acceleration(16000)
        # self.enter_print_mode()
        self.enable_print_profile()

        current_printer_head = self.model.rack_model.get_gripper_printer_head()
        if current_printer_head is not None:
            if current_printer_head.check_calibration_complete():
                print('\nController: Using calibrations during array printing')
                expected_volume = current_printer_head.get_current_volume()
                droplet_volume = current_printer_head.get_target_droplet_volume()
                if current_printer_head.get_current_volume() == None:
                    update_volume = False
                else:
                    update_volume = True
            else:
                print('\nController: using default pulse width')
                expected_volume = None
                update_volume = False

        current_stock_id = self.model.rack_model.gripper_printer_head.get_stock_id()
        #print(f'Current stock:{current_stock_id}')
        reaction_wells = self.model.well_plate.get_all_wells_with_reactions(fill_by='rows')
        wells_with_droplets = [well for well in reaction_wells if well.get_remaining_droplets(current_stock_id) > 0]
        for i,well in enumerate(wells_with_droplets):
            target_droplets = well.get_remaining_droplets(current_stock_id)
            if target_droplets == 0:
                #print(f'No droplets required for well {well.well_id}')
                continue
            well_coords = well.get_coordinates()
            self.set_absolute_coordinates(well_coords['X'],well_coords['Y'],well_coords['Z'],override=True)
            print(f'Printing {target_droplets} droplets to well {well.well_id}')
            is_last_iteration = i == len(wells_with_droplets) - 1
            if update_volume:
                if expected_volume < 10:
                    self.print_droplets(target_droplets,expected_volume=expected_volume, handler=self.refill_printer_head_handler,kwargs={'well_id':well.well_id,'stock_id':current_stock_id,'target_droplets':target_droplets,'update_volume':update_volume})
                    print('---Printer head needs to be reloaded---')
                    return
            if not is_last_iteration:
                self.print_droplets(target_droplets,expected_volume=expected_volume, handler=self.well_complete_handler,kwargs={'well_id':well.well_id,'stock_id':current_stock_id,'target_droplets':target_droplets,'update_volume':update_volume})
            else:
                self.print_droplets(target_droplets,expected_volume=expected_volume, handler=self.last_well_complete_handler,kwargs={'well_id':well.well_id,'stock_id':current_stock_id,'target_droplets':target_droplets,'update_volume':update_volume})
            if update_volume:
                expected_volume -= target_droplets * droplet_volume / 1000  # convert to uL
            
    def enable_print_profile(self):
        """Enable the print profile."""
        self.machine.enable_print_profile()

    def disable_print_profile(self):
        """Disable the print profile."""
        self.machine.disable_print_profile()
    
    def start_refuel_camera(self):
        self.machine.start_refuel_camera()
        self.machine.refuel_led_on()

    def capture_refuel_image(self):
        frame = self.machine.capture_refuel_image()
        self.model.refuel_camera_model.start_analysis(frame)

    def stop_refuel_camera(self):
        self.machine.stop_refuel_camera()
        self.machine.refuel_led_off()

    def start_droplet_camera(self):
        self.machine.start_droplet_camera()

    def capture_droplet_image(self, callback=None, *, throughput_mode=False):
        """
        Initiates a non-blocking image capture. If a callback is provided,
        it will be invoked with the captured frame once the capture completes.
        """
        if callback is not None:
            if self.pending_capture_callback is not None:
                print("Capture already pending; dropping new capture callback.")
                return False
            self.pending_capture_callback = callback
        self.machine.capture_droplet_image(throughput_mode=throughput_mode)
        return True

    def stop_droplet_camera(self):
        self.machine.stop_droplet_camera()

    def start_read_camera(self):
        self.machine.start_read_camera()

    def stop_read_camera(self):
        self.machine.stop_read_camera()

    def set_flash_duration(self, duration,callback=None):
        self.machine.set_flash_duration(duration, handler=callback)

    def set_flash_delay(self, delay,callback=None):
        self.machine.set_flash_delay(delay, handler=callback)

    def set_imaging_droplets(self, num_droplets, callback=None):
        self.machine.set_imaging_droplets(num_droplets,handler=callback)

    def set_exposure_time(self, exposure_time,callback=None):
        self.machine.set_exposure_time(exposure_time,handler=callback)
        self.model.droplet_camera_model.update_exposure_time(exposure_time)

    def set_droplet_capture_profile(self, profile_name: str):
        self.machine.set_droplet_capture_profile(profile_name)

    def set_command_dispatch_interval(self, interval_ms: int):
        self.machine.set_execution_interval_ms(interval_ms)

    def set_save_directory(self, directory):
        self.model.droplet_camera_model.set_save_directory(directory)      

    def handle_capture_request(self, callback):
            # protect against overlapping requests
        if self.pending_capture_callback is not None:
            print("Capture already pending; dropping new request.")
            return
        self.pending_capture_callback = callback
        # Use your defaults or pipe through parameters as needed
        # Start the non-blocking capture process, then invoke the callback with the captured image.
        # self.capture_droplet_image(callback=callback)
        self.machine.capture_droplet_image()

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
            self.model.calibration_manager.calibrationError.emit(msg)
        except Exception:
            pass

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
        num_settings = len(settings)
        current_call_back = self.intermediate_callback  # Default callback for intermediate settings.
        for i, (key, value) in enumerate(settings.items()):
            if i == num_settings - 1:
                current_call_back = callback
            if key == 'num_droplets':
                self.set_imaging_droplets(value,callback=current_call_back)
            elif key == 'flash_duration':
                self.set_flash_duration(value, callback=current_call_back)
            elif key == 'flash_delay':
                self.set_flash_delay(value, callback=current_call_back)
                print(f'--Setting flash delay: {value}')
            elif key == 'exposure_time':
                self.set_exposure_time(value, callback=current_call_back)
            elif key == 'print_pulse_width':
                self.set_print_pulse_width(value, handler=current_call_back)
            elif key == 'refuel_pulse_width':
                self.set_refuel_pulse_width(value, handler=current_call_back)
            elif key == 'print_pressure':
                print(f'--Setting print pressure: {value}')
                self.set_absolute_print_pressure(value, handler=current_call_back)
            elif key == 'refuel_pressure':
                self.set_absolute_refuel_pressure(value, handler=current_call_back)
            else:
                print(f'Unknown setting: {key}')

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
            
        # Update the model and/or view (assuming your model has such a method)
        self.model.droplet_camera_model.update_image(frame, capture_info=cap_info)
        
        # If a callback was set for the capture, call it.
        if self.pending_capture_callback:
            callback = self.pending_capture_callback
            self.pending_capture_callback = None  # Clear for future captures.
            callback(frame)

    @QtCore.Slot(str)
    def _on_capture_failed(self, msg: str):
        print(f"[Camera] capture failed: {msg}")
        # 1) If a caller is waiting via callback, resolve it with sentinel None
        if self.pending_capture_callback:
            cb = self.pending_capture_callback
            self.pending_capture_callback = None
            try:
                cb(None)                # <- sentinel for failure
            except Exception as e:
                # If some callback signature changed, at least fail loudly
                print(f"Callback raised after capture failure: {e}")
        # 2) Also notify the calibration layer (optional, but handy for QState transitions)
        self.model.calibration_manager.captureFailed.emit(msg)

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
        replicates_per_pressure: int = 3,
    ):
        self.model.calibration_manager.start_prebreakup_morphology_calibration(
            start_pressure=start_pressure,
            pressure_step_psi=pressure_step_psi,
            prebreakup_lead_us=prebreakup_lead_us,
            replicates_per_pressure=replicates_per_pressure,
        )

    def start_pressure_sweep_characterization(self):
        self.model.calibration_manager.start_pressure_sweep_characterization()
    
    def start_droplet_timecourse_process(self):
        self.model.calibration_manager.start_droplet_timecourse_process()

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

