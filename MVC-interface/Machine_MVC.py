import threading
import time
from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QThread
from PySide6.QtWidgets import QApplication

from collections import deque

import serial
import re
import json
import cv2
import numpy as np
import pandas as pd
import os
import joblib
from picamera2 import Picamera2
import gpiod

class DropletCamera(QObject):
    image_captured_signal = Signal()
    def __init__(self):
        super().__init__()
        self.signal_pin = 27
        self.camera = None
        self.chip = gpiod.Chip("gpiochip4")
        self.line = self.chip.get_line(self.signal_pin)
        self.line.request(consumer="GPIOConsumer", type=gpiod.LINE_REQ_DIR_OUT)
        self.line.set_value(0)

        self.exposure_time = 200000
        self.latest_frame = None

        # We’ll store the “job” IDs returned by PiCamera2’s non-blocking calls
        self.current_job = None

        # Timers for half-exposure steps
        self.timer_half = QtCore.QTimer()
        self.timer_half.setSingleShot(True)
        self.timer_half.timeout.connect(self._on_half_exposure_timeout)

        self.timer_second_half = QtCore.QTimer()
        self.timer_second_half.setSingleShot(True)
        self.timer_second_half.timeout.connect(self._on_second_half_timeout)

    def get_latest_frame(self):
        return self.latest_frame
    
    def start_flash(self):
        self.line.set_value(1)

    def stop_flash(self):
        self.line.set_value(0)

    def start_camera(self):
        self.camera = Picamera2(1)
        print(f'--- Modes:{self.camera.sensor_modes}')
        print(f'--- Resolution:{self.camera.sensor_resolution}')
        self.configure_camera()
        self.camera.start()

    def configure_camera(self):
        # Create a "video" configuration to stream frames continuously
        video_config = self.camera.create_still_configuration(
            main={
                "size": self.camera.sensor_resolution,
                "format": "RGB888",
            }
        )
        self.camera.configure(video_config)

        # Force a fixed 200 ms exposure
        self.camera.set_controls({
            "FrameDurationLimits": (200_000, 200_000),  # 200 ms frame time
            "ExposureTime": 200_000,
            "AeEnable": False,
            "AwbEnable": False,
            "AnalogueGain": 1.0,
        })
    
    def change_exposure_time(self, exposure_time, handler=None):
        """
        Adjusts the fixed exposure time on the fly.
        """
        if not self.camera:
            return
        self.camera.stop()
        self.camera.set_controls({
            "FrameDurationLimits": (exposure_time, exposure_time),
            "ExposureTime": exposure_time,
            "AeEnable": False,
            "AwbEnable": False
        })
        self.camera.start()
        print(f"--Camera changed: Exp {exposure_time} us")
        if handler is not None:
            handler()

    def stop_camera(self):
        if self.camera:
            self.camera.stop()
            self.camera.close()
            self.camera = None

    @QtCore.Slot(int)
    def _schedule_half_timer(self, half_ms):
        """
        This slot is guaranteed to run in the main thread (our droplet camera's thread).
        We start the QTimer here.
        """
        self.timer_half.start(half_ms)

    def _skip_frame(self):
        """
        Request 1 frame from the pipeline in a non-blocking manner,
        so we know exactly when the next frame starts.
        """
        # We supply a non-blocking "signal_function":
        self.current_job = self.camera.capture_request(signal_function=self._on_skip_frame_done)

    def _on_skip_frame_done(self, job):
        """
        Called when the skip-frame request completes, meaning a new 200ms exposure
        is just starting in the pipeline.
        """
        request = self.camera.wait(job)
        if request:
            request.release()  # discard the skip frame

        # Now we wait half the exposure time (100 ms) before setting the GPIO high
        half_ms = int(self.exposure_time / 2 / 1000)  # 200_000 us => 100 ms
        
        # Queue a call to _schedule_half_timer(...) in the main thread
        QtCore.QMetaObject.invokeMethod(
            self, 
            "_schedule_half_timer",           # method name
            QtCore.Qt.QueuedConnection,       # ensures it runs in self's thread
            QtCore.Q_ARG(int, half_ms)        # pass the half_ms parameter
        )
    

    def _on_half_exposure_timeout(self):
        """
        Called ~halfway (100 ms) into the current 200 ms frame.
        Set the GPIO line high so the flash board knows to flash (once).
        """
        self.start_flash()

        # Schedule the second half
        half_ms = int(self.exposure_time / 4 / 1000) 
        self.timer_second_half.start(half_ms)

    def _on_second_half_timeout(self):
        """
        Called after the second 100 ms, meaning the frame that had the flash
        should now be finishing. We can capture that frame in a non-blocking manner.
        """
        # Next request should contain the lit frame
        self.current_job = self.camera.capture_request(signal_function=self._on_flash_frame_captured)

    def _on_flash_frame_captured(self, job):
        """
        Called when the flash frame request completes. We retrieve the frame,
        set the GPIO line low so the board can re-arm for future flashes, and emit.
        """
        request = self.camera.wait(job)
        if request:
            self.latest_frame = request.make_array("main")
            md = request.get_metadata()  # or req.metadata
            # print("Actual exposure used:", md["ExposureTime"])
            # print("Actual frame duration:", md["FrameDuration"])
            request.release()
        else:
            frame = None

        # Now we can set GPIO low to re-arm the board
        self.stop_flash()

        # Emit the signal with the new frame
        self.image_captured_signal.emit()

    def capture_non_blocking(self):
        """
        Public method to start the “mid-exposure flash capture” process.
        1) skip a frame
        2) half exposure => set GPIO high
        3) second half => capture request => set GPIO low => emit
        """
        if not self.camera:
            print("Camera not started.")
            return
        self._skip_frame()


class RefuelCamera(QObject):
    def __init__(self):
        super().__init__()
        self.led_pin = 17
        self.chip = gpiod.Chip("gpiochip4")
        self.line = self.chip.get_line(self.led_pin)
        self.line.request(consumer="GPIOConsumer", type=gpiod.LINE_REQ_DIR_OUT)
        self.line.set_value(0)

    def start_camera(self):
        # Initialize Picamera2
        self.camera = Picamera2(0)
        self.camera.configure(self.camera.create_still_configuration(
            main={"size": self.camera.sensor_resolution, "format": "RGB888"}
        ))
        self.camera.start()

    def capture_image(self):
        return self.camera.capture_array()

    def stop_camera(self):
        if self.camera:
            self.camera.stop()
            self.camera.close()

    def led_on(self):
        print("---LED ON")
        self.line.set_value(1)

    def led_off(self):
        print("---LED OFF")
        self.line.set_value(0)

    def __del__(self):
        self.line.set_value(0)
        self.line.release()


class Balance(QObject):
    balance_mass_updated_signal = Signal(float)
    def __init__(self,machine,model):
        super().__init__()
        self.machine = machine
        self.model = model
        self.connected = False
        self.port = None
        self.simulate = True
        self.error_count = 0
        self.current_mass = 0
        self.target_mass = 0
        self.mass_update_timer = None
        self.mass_log = []

    def is_connected(self):
        return self.connected

    def connect_balance(self,port):
        if port == 'Virtual':
            print('Connecting to virtual balance')
            self.script_dir = os.path.dirname(os.path.abspath(__file__))
            # self.prediction_model_path = os.path.join(self.script_dir, 'Presets','large_lr_pipeline.pkl')
            # self.resistance_model_path = os.path.join(self.script_dir, 'Presets','large_resistance_pipeline.pkl')
            self.prediction_model = None
            self.resistance_model = None
            # self.load_prediction_models()
            self.current_resistance = None
            self.current_printer_head_id = None
            self.current_pulse_width = None
            self.resistance_dict = {}

            self.connected = True
            self.simulate = True
            self.mass_simulate_timer = QtCore.QTimer()
            self.mass_simulate_timer.timeout.connect(self.update_simulated_mass)
            self.mass_simulate_timer.start(10)
            self.show_connection()
            self.begin_reading()
            return True
        try:
            self.port = serial.Serial(port, baudrate=9600, bytesize=8, timeout=2, stopbits=serial.STOPBITS_ONE)
            if not self.port.is_open:  # Add this line
                raise serial.SerialException('Could not open port')  # Add this line
            self.connected = True
            self.simulate = False
            self.show_connection()
            self.begin_reading()
            return True
        except:
            self.main_window.popup_message('Connection error',f'Could not connect to balance at port {port}')
            self.connected = False
            return False
        
    def update_prediction_models(self,prediction_model_path,resistance_model_path,target_volume):
        self.prediction_model = joblib.load(prediction_model_path)
        self.resistance_model = joblib.load(resistance_model_path)
        self.target_volume = target_volume

    # def load_prediction_models(self):
    #     """Load the prediction model from the specified file path."""
    #     self.prediction_model = joblib.load(self.prediction_model_path)
    #     self.resistance_model = joblib.load(self.resistance_model_path)
        
    def close_connection(self):
        if not self.simulate:
            self.port.close()
        else:
            self.mass_simulate_timer.stop()
        if self.mass_update_timer is not None:
            self.mass_update_timer.stop()
        self.connected = False
        return

    def show_connection(self):
        print('Balance connected')

    def get_mass(self):
        if not self.simulate:
            if self.port.in_waiting > 0:
                data = self.port.readline()
                try:
                    data = data.decode("ASCII")
                    # print('Data:',data)
                    [sign,mass] = re.findall(r'(-?) *([0-9]+\.[0-9]+) [a-zA-Z]*',data)[0]
                    mass = float(''.join([sign,mass]))
                    self.current_mass = mass
                    self.add_to_log(self.current_mass)
                    self.balance_mass_updated_signal.emit(self.current_mass)
                except Exception as e:
                    #print(f'--Error {e} reading from balance')
                    self.error_count += 1
                    if self.error_count > 100:
                        self.close_connection()
                        self.main_window.popup_message('Connection error','Lost connection to balance')
                    
        else:
            self.add_to_log(self.current_mass)
            self.balance_mass_updated_signal.emit(self.current_mass)

        
        
    def begin_reading(self):
        print('\n---Begin reading balance---\n')
        self.mass_update_timer = QtCore.QTimer()
        self.mass_update_timer.timeout.connect(self.get_mass)
        self.mass_update_timer.start(20)

    def add_to_log(self,mass):
        # print('Adding to log:',mass)
        self.mass_log.append(mass)
        if len(self.mass_log) > 100:
            self.mass_log.pop(0)

    def get_recent_mass(self):
        if self.mass_log != []:
            return self.mass_log[-1]
        else:
            return 0
    
    def simulate_mass(self, num_droplets,pulse_width):
        printer_head = self.model.rack_model.get_gripper_printer_head()
        current_id = printer_head.get_stock_id()
        
        if printer_head is not None:
            if current_id not in self.resistance_dict.keys():
                if self.target_volume > 50:
                    resistance = np.random.randint(self.target_volume-10,self.target_volume+30)
                else:
                    resistance = np.random.randint(self.target_volume-15,self.target_volume+10)
                self.resistance_dict.update({current_id:resistance})
                #print(f'Adding simulated resistance: {current_id}-{self.current_resistance}')
            effective_resistance = self.resistance_dict[current_id]
            current_volume, _, _, _, _, _, _ = printer_head.get_prediction_data()
            input_features = pd.DataFrame({
                'pulse_width': [pulse_width],
                'starting_volume': [current_volume],
                'effective_resistance': [effective_resistance]
            })
            if self.prediction_model is None:
                print('Prediction model not loaded')
                return 0
            predicted_volume = self.prediction_model.predict(input_features)[0]
            mass = predicted_volume * num_droplets / 1000
            error = np.random.normal(0, 0.005)
            #print(f'\nError: {error}\n')
            mass += error
            
            #print(f'\nDrop: {predicted_volume} Mass: {mass} Pulse: {pulse_width} Vol: {current_volume} Res: {effective_resistance}')

        else:
            mass = 0
        return mass

    
    def update_simulated_mass(self):
        # print('Updating simulated mass')
        # self.pulse_width = self.model.machine_model.get_pulse_width()
        if self.machine.balance_droplets != []:
            time.sleep(0.5)
            # print('Balance droplets:',self.machine.balance_droplets)
            [num_droplets,pulse_width] = self.machine.balance_droplets.pop(0)
            # print('Found balance droplets',num_droplets,psi)
            mass = self.simulate_mass(num_droplets,pulse_width)
            # print('Simulated mass:',mass,self.current_mass,self.target_mass)
            self.target_mass += mass
        
        if self.current_mass < self.target_mass:
            self.current_mass += 0.01

class BoardCommand():
    """
    Represents a command to be executed on the board.

    Attributes:
        command_number (int): The number of the command.
        command_type (str): The type of the command.
        param1 (any): The first parameter of the command.
        param2 (any): The second parameter of the command.
        param3 (any): The third parameter of the command.
        executed (bool): Indicates whether the command has been executed.
    """

    def __init__(self, command_number, command_type, param1, param2, param3):
        self.command_number = command_number
        self.command_type = command_type
        self.param1 = param1
        self.param2 = param2
        self.param3 = param3
        self.executed = False

class VirtualMachine():
    def __init__(self,machine):
        """
        Initializes a ControlBoard object.

        Attributes:
            command_number: Current command number.
            command_queue: List containing the command queue.
            past_commands: List containing the executed commands.
            state: Current state of the machine (Free or Busy).
        """
        self.machine = machine
        self.command_queue = []
        self.current_command_number = 0
        self.last_completed_command_number = 0
        self.last_added_command_number = 0
        self.wait_flag = False
        self.wait_time = 0
        self.pause = False
        self.initial_time = 0
        self.state = "Free"
        self.com_open = True
        self.max_cycle = 300
        self.cycle_count = 10000

        self.board_check_timer = QTimer()
        self.board_check_timer.timeout.connect(self.check_for_command)
        self.board_check_timer.start(20)  # Update every 20 ms
        
        self.board_update_timer = QTimer()
        self.board_update_timer.timeout.connect(self.update_states)
        self.board_update_timer.start(2)  # Update every 20 ms

        self.motors_active = False
        self.x_pos = 0
        self.y_pos = 0
        self.z_pos = 0
        self.p_pos = 0
        self.x_correct = False
        self.y_correct = False
        self.z_correct = False

        self.correct_pos = True
        self.xy_speed = 50
        self.z_speed = 50

        self.target_x = 0
        self.target_y = 0
        self.target_z = 0
        self.target_p = 0

        self.pressure = 1638
        self.target_pressure = 1638
        self.regulate_pressure = False
        self.correct_pressure = True

        self.pulse_width = 4200
        self.current_micros = 0

        self.current_droplets = 0
        self.target_droplets = 0
        self.correct_droplets = True

        self.gripper_active = False
        self.gripper_open = False
        self.target_gripper_open = False
        self.correct_gripper = True

        self.status_step = 'Cycle_count'
    
    def pause_commands(self):
        self.state = "Paused"
        self.pause = True
        
    def resume_commands(self):
        self.state = "Free"
        self.pause = False

    def clear_command_queue(self):
        # new_command_queue = [command for command in self.command_queue if command.executed]
        self.command_queue = []
        self.current_command_number = 0
        self.last_completed_command_number = 0
        self.last_added_command_number = 0
        self.state = "Free"
        self.pause = False

        self.target_x = self.x_pos
        self.target_y = self.y_pos
        self.target_z = self.z_pos
        self.target_pressure = self.pressure
        self.target_gripper_open = self.gripper_open
        self.target_droplets = self.current_droplets

    
    def get_complete_state(self):
        # if self.simulate:
        full_string = (
            f'State:{self.state},'
            f'Com_open:{self.com_open},'
            f'Last_added:{self.last_added_command_number},'
            f'Current_command:{self.current_command_number},'
            f'Last_completed:{self.last_completed_command_number},'
            f'X:{self.x_pos},'
            f'Y:{self.y_pos},'
            f'Z:{self.z_pos},'
            f'P:{self.p_pos},'
            f'Tar_X:{self.target_x},'
            f'Tar_Y:{self.target_y},'
            f'Tar_Z:{self.target_z},'
            f'Tar_P:{self.target_p},'
            f'Pressure:{self.pressure},'
            f'Tar_pressure:{self.target_pressure},'
            f'Gripper:{self.gripper_open},'
            f'Droplets:{self.current_droplets},'
            f'Max_cycle:{self.max_cycle},'
            f'Cycle_count:{self.cycle_count}'
        )
        return full_string
    
    def get_current_state(self):
        if self.status_step == 'Cycle_count':
            self.status_step = 'Last_completed'
            return f'Cycle_count:{self.cycle_count}'
        elif self.status_step == 'Last_completed':
            self.status_step = 'Last_added'
            return f'Last_completed:{self.last_completed_command_number}'
        elif self.status_step == 'Last_added':
            self.status_step = 'Current_command'
            return f'Last_added:{self.last_added_command_number}'
        elif self.status_step == 'Current_command':
            self.status_step = 'X'
            return f'Current_command:{self.current_command_number}'
        elif self.status_step == 'X':
            self.status_step = 'Y'
            return f'X:{self.x_pos}'
        elif self.status_step == 'Y':
            self.status_step = 'Z'
            return f'Y:{self.y_pos}'
        elif self.status_step == 'Z':
            self.status_step = 'P'
            return f'Z:{self.z_pos}'
        elif self.status_step == 'P':
            self.status_step = 'Tar_X'
            return f'P:{self.p_pos}'
        elif self.status_step == 'Tar_X':
            self.status_step = 'Tar_Y'
            return f'Tar_X:{self.target_x}'
        elif self.status_step == 'Tar_Y':
            self.status_step = 'Tar_Z'
            return f'Tar_Y:{self.target_y}'
        elif self.status_step == 'Tar_Z':
            self.status_step = 'Tar_P'
            return f'Tar_Z:{self.target_z}'
        elif self.status_step == 'Tar_P':
            self.status_step = 'Gripper'
            return f'Tar_P:{self.target_p}'
        elif self.status_step == 'Gripper':
            self.status_step = 'Pressure'
            return f'Gripper:{self.gripper_open}'
        elif self.status_step == 'Pressure':
            self.status_step = 'Tar_pressure'
            return f'Pressure:{self.pressure}'
        elif self.status_step == 'Tar_pressure':
            self.status_step = 'Pulse_width'
            return f'Tar_pressure:{self.target_pressure}'
        elif self.status_step == 'Pulse_width':
            self.status_step = 'Micros'
            return f'Pulse_width:{self.pulse_width}'
        elif self.status_step == 'Micros':
            self.status_step = 'Cycle_count'
            self.current_micros += 10000
            if self.current_micros > 46000000:
                self.current_micros = 0
            return f'Micros:{self.current_micros}'

        

    def check_for_command(self):
        if self.machine.sent_command is not None:
            self.add_command_to_queue(self.machine.sent_command.get_command())
            self.machine.sent_command = None
    
    def update_states(self):
        if self.pause:
            return
        if self.wait_flag:
            if time.time() - self.initial_time > self.wait_time:
                self.wait_flag = False
            else:
                return
        if self.motors_active:
            self.x_correct = False
            self.y_correct = False
            self.z_correct = False

            if abs(self.y_pos - self.target_y) < self.xy_speed:
                self.y_pos = self.target_y
                self.y_correct = True
            elif self.y_pos < self.target_y:
                self.y_pos += self.xy_speed
            elif self.y_pos > self.target_y:
                self.y_pos -= self.xy_speed

            # Only move the X axis if the Y axis has reached its target position
            if self.y_correct:
                if abs(self.x_pos - self.target_x) < self.xy_speed:
                    self.x_pos = self.target_x
                    self.x_correct = True
                elif self.x_pos < self.target_x:
                    self.x_pos += self.xy_speed
                elif self.x_pos > self.target_x:
                    self.x_pos -= self.xy_speed

            # Only move the Z axis if the X and Y axes have reached their target positions
            if self.x_correct and self.y_correct:
                if abs(self.z_pos - self.target_z) < self.z_speed:
                    self.z_pos = self.target_z
                    self.z_correct = True
                elif self.z_pos < self.target_z:
                    self.z_pos += self.z_speed
                elif self.z_pos > self.target_z:
                    self.z_pos -= self.z_speed

            if self.x_correct and self.y_correct and self.z_correct:
                self.correct_pos = True
        else:
            self.correct_pos = True

        if self.regulate_pressure:
            if abs(self.pressure - self.target_pressure) < 5:
                self.pressure = self.target_pressure
                self.correct_pressure = True
            elif self.pressure < self.target_pressure:
                self.pressure += 5
            elif self.pressure > self.target_pressure:
                self.pressure -= 5
        else:
            self.correct_pressure = True

        if self.correct_pos and self.correct_pressure:
            if self.gripper_open != self.target_gripper_open:
                self.gripper_open = self.target_gripper_open
            else:
                self.correct_gripper = True

        if self.correct_pos and self.correct_pressure and self.correct_gripper:
            if self.current_droplets < self.target_droplets:
                self.current_droplets += 1
            else:
                self.correct_droplets = True

        self.max_cycle += np.random.randint(-10,10)
        self.cycle_count = np.random.randint(6100,6300)

        if self.correct_pos and self.correct_pressure and self.correct_gripper and self.correct_droplets:
            self.state = "Free"
            self.last_completed_command_number = self.current_command_number
            self.execute_command_from_queue()
        
    def add_command_to_queue(self, command):            
        new_command = self.convert_command(command)
        if new_command.command_type == 'PAUSE':
            self.pause_commands()
            print('Received pause command')
        elif new_command.command_type == 'RESUME':
            self.resume_commands()
            print('Received resume command')
        elif new_command.command_type == 'CLEAR_QUEUE':
            self.clear_command_queue()
            print('Received clear command')
        else:
            self.command_queue.append(new_command)

    def convert_command(self, command):
        [command_number,command_type,p1,p2,p3] = command[1:-1].split(',')
        self.last_added_command_number = int(command_number)
        return BoardCommand(command_number,command_type,p1,p2,p3)
    
    def execute_command_from_queue(self):
        if self.state == "Free":
            for i,command in enumerate(self.command_queue):
                if not command.executed:
                    self.current_command_number = int(command.command_number)
                    self.execute_command(i)
                    self.command_queue[i].executed = True
                    self.command_queue.pop(i)
                    self.state = "Busy"
                    break            

    def execute_command(self,command_index):
        command = self.command_queue[command_index]
        print('Board Executing command:',command.command_number,command.command_type,command.param1,command.param2,command.param3,command.executed)
        if command.command_type == 'RELATIVE_XYZ':
            self.correct_pos = False
            self.correct_x = False
            self.correct_y = False
            self.correct_z = False

            self.target_x += int(command.param1)
            self.target_y += int(command.param2)
            self.target_z += int(command.param3)
        elif command.command_type == 'RELATIVE_X':
            self.correct_pos = False
            self.correct_x = False
            self.target_x += int(command.param1)
        elif command.command_type == 'RELATIVE_Y':
            self.correct_pos = False
            self.correct_y = False
            self.target_y += int(command.param1)
        elif command.command_type == 'RELATIVE_Z':
            self.correct_pos = False
            self.correct_z = False
            self.target_z += int(command.param1)
        elif command.command_type == 'ABSOLUTE_XYZ':
            self.correct_pos = False
            self.correct_x = False
            self.correct_y = False
            self.correct_z = False

            self.target_x = int(command.param1)
            self.target_y = int(command.param2)
            self.target_z = int(command.param3)
        elif command.command_type == 'ABSOLUTE_X':
            self.correct_pos = False
            self.correct_x = False
            self.target_x = int(command.param1)
        elif command.command_type == 'ABSOLUTE_Y':
            self.correct_pos = False
            self.correct_y = False
            self.target_y = int(command.param1)
        elif command.command_type == 'ABSOLUTE_Z':
            self.correct_pos = False
            self.correct_z = False
            self.target_z = int(command.param1)
        
        elif command.command_type == 'RELATIVE_PRESSURE':
            self.correct_pressure = False
            self.target_pressure += int(command.param1)
        elif command.command_type == 'ABSOLUTE_PRESSURE':
            self.correct_pressure = False
            self.target_pressure = int(command.param1)
        elif command.command_type == 'REGULATE_PRESSURE':
            self.correct_pressure = False
            self.regulate_pressure = True
        elif command.command_type == 'DEREGULATE_PRESSURE':
            self.correct_pressure = True
            self.regulate_pressure = False
        elif command.command_type == 'OPEN_GRIPPER':
            if not self.gripper_active:
                self.gripper_active = True
            self.target_gripper_open = True
        elif command.command_type == 'CLOSE_GRIPPER':
            if not self.gripper_active:
                self.gripper_active = True
            self.target_gripper_open = False
        elif command.command_type == 'GRIPPER_OFF':
            self.gripper_active = False
        elif command.command_type == 'ENABLE_MOTORS':
            self.motors_active = True
        elif command.command_type == 'DISABLE_MOTORS':
            self.motors_active = False
        elif command.command_type == 'WAIT':
            self.wait_time = int(command.param1) / 1000
            self.initial_time = time.time()
            self.wait_flag = True
        elif command.command_type == 'PRINT':
            self.correct_droplets = False
            self.target_droplets = int(command.param1)
        elif command.command_type == 'RESET_P':
            self.p_pos = 0
        elif command.command_type == 'HOME_ALL':
            self.x_pos = 0
            self.y_pos = 0
            self.z_pos = 0
            self.p_pos = 0
            self.target_x = 0
            self.target_y = 0
            self.target_z = 0
            self.target_p = 0
        elif command.command_type == 'HOME_X':
            self.x_pos = 0
            self.target_x = 500
        elif command.command_type == 'HOME_Y':
            self.y_pos = 0
            self.target_y = 500
        elif command.command_type == 'HOME_Z':
            self.z_pos = 0
            self.target_z = 500
        elif command.command_type == 'HOME_P':
            self.p_pos = 0
            self.target_p = 500
        elif command.command_type == 'SET_WIDTH':
            self.pulse_width = int(command.param1)
        elif command.command_type == 'PRINT_MODE':
            print('--Entered print mode--')
        elif command.command_type == 'NORMAL_MODE':
            print('--Entered normal mode--')
            
        elif command.command_type == 'CHANGE_ACCEL':
            print('Changing acceleration')
        elif command.command_type == 'RESET_ACCEL':
            print('Resetting acceleration')
        else:
            print('Unknown command:',command.command_type)
        self.correct_pos = False
        self.correct_pressure = False
        self.correct_gripper = False
        # self.command_queue[command_index].executed = True
        self.state = "Busy"

class Command:
    """
    Represents a command to be sent to the machine.
    
    Attributes:
    command_number (int): The number of the command.
    command_type (str): The type of the command.
    param1: The first parameter of the command.
    param2: The second parameter of the command.
    param3: The third parameter of the command.
    handler (function, optional): The handler function for the command.
    kwargs (dict, optional): Additional keyword arguments for the handler function.
    """
    def __init__(self, command_number, command_type, param1, param2, param3, handler=None, kwargs=None):
        self.command_number = command_number
        self.command_type = command_type
        self.param1 = param1
        self.param2 = param2
        self.param3 = param3
        self.signal = f'<{self.command_number},{command_type},{param1},{param2},{param3}>'
        self.status = "Added"
        self.timestamp = time.time()
        self.handler = handler
        self.kwargs = kwargs if kwargs is not None else {}

    def mark_as_sent(self):
        self.status = "Sent"

    def mark_as_executing(self):
        self.status = "Executing"

    def mark_as_completed(self):
        self.status = "Completed"
        self.execute_handler()

    def get_number(self):
        return self.command_number

    def get_command(self):
        return self.signal

    def get_timestamp(self):
        return self.timestamp

    def execute_handler(self):
        if self.handler is not None:
            self.handler(**self.kwargs)


class CommandQueue(QObject):
    """
    Represents a queue of commands to be sent to the machine.
    Uses deque to store the commands.
    Completed commands are transferred to the completed queue.
    """
    queue_updated = Signal()  # Signal to emit when the queue is updated
    commands_completed = Signal()  # Signal to emit when all commands are completed

    def __init__(self):
        super().__init__()  # Initialize the QObject
        self.queue = deque()
        self.completed = deque()
        self.command_number = 0
        self.max_sent_commands = 8  # Maximum number of commands that can be sent to the machine at once

    def add_command(self, command_type, param1, param2, param3, handler=None, kwargs=None):
        """Add a command to the queue."""
        
        
        self.command_number += 1
        # print(f'type params: {self.command_number}-{command_type} {type(param1)} {type(param2)} {type(param3)}')
        #print(f'Adding command: {command_type} {param1} {param2} {param3}')
        command = Command(self.command_number, command_type, param1, param2, param3, handler, kwargs)
        self.queue.append(command)
        return command

    def get_number_of_sent_commands(self):
        """Returns the number of commands that have been sent to the machine."""
        return len([command for command in self.queue if command.status == "Sent"])

    def get_next_command(self):
        """Send the next command to the machine if the buffer allows."""
        if self.queue and self.get_number_of_sent_commands() < self.max_sent_commands:
            for command in self.queue:
                if command.status == "Added":
                    command.mark_as_sent()
                    return command
        return None

    def update_command_status(self, current_executing_command, last_completed_command):
        if current_executing_command is None or last_completed_command is None:
            print('No commands to update')
            return
        # Iterate over a copy of the queue.
        for command in list(self.queue):
            if command.status == "Sent" and command.command_number == int(current_executing_command):
                command.mark_as_executing()
            if command.command_number <= int(last_completed_command):
                command.mark_as_completed()

        # Now remove completed commands.
        while self.queue and self.queue[0].status == "Completed":
            completed_command = self.queue.popleft()
            self.completed.append(completed_command)
            if len(self.completed) > 100:
                self.completed.popleft()

        if len(self.queue) == 0:
            self.commands_completed.emit()

        self.queue_updated.emit()

    def clear_queue(self):
        """Clear the command queue."""
        self.queue.clear()
        self.completed.clear()
        self.command_number = 0
        self.queue_updated.emit()

class DisconnectWorker(QThread):
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent

    def run(self):
        self.parent.gripper_off()
        self.parent.disable_motors()
        self.parent.deregulate_pressure()

        # Continuously check until all tasks are completed
        timeout_counter = 0
        while not self.parent.check_if_all_completed():
            timeout_counter += 1
            time.sleep(0.1)
            if timeout_counter > 100:
                print('Timeout disconnecting from machine')
                break

        self.parent.clear_command_queue()
        time.sleep(1)
        self.finished.emit()
    
class ResetWorker(QThread):
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent

    def run(self):
        self.parent.gripper_off()
        self.parent.disable_motors()
        self.parent.deregulate_pressure()
        self.parent.exit_print_mode()

        # Continuously check until all tasks are completed
        timeout_counter = 0
        while not self.parent.check_if_all_completed():
            timeout_counter += 1
            time.sleep(0.1)
            if timeout_counter > 10:
                print('Timeout disconnecting from machine')
                break

        self.parent.clear_command_queue()
        time.sleep(1)
        self.finished.emit()

class Machine(QObject):
    """
    Class for the machine object. This class is responsible for 
    sending and receiving data from the machine and organizing
    the command queue.
    """
    status_updated = Signal(dict)  # Signal to emit status updates
    command_sent = Signal(dict)    # Signal to emit when a command is sent
    error_occurred = Signal(str)   # Signal to emit errors
    homing_completed = Signal()    # Signal to emit when homing is completed
    gripper_open = Signal()      # Signal to emit when the gripper is opened
    gripper_closed = Signal()    # Signal to emit when the gripper is closed
    gripper_on_signal = Signal()        # Signal to emit when the gripper is turned on
    gripper_off_signal = Signal()       # Signal to emit when the gripper is turned off
    disconnect_complete_signal = Signal()  # Signal to stop timers
    machine_connected_signal = Signal(bool)  # Signal to emit when the machine is connected
    all_calibration_droplets_printed = Signal()  # Signal to emit when all calibration droplets are printed

    def __init__(self,model):
        super().__init__()
        self.command_queue = CommandQueue()
        self.model = model
        self.board = None
        self.port = 'Virtual'
        self.simulate = True
        self.communication_timer = None
        self.execution_timer = None
        self.sent_command = None
        self.error_count = 0

        self.fss = 6553
        self.psi_offset = 8192
        self.psi_max = 15

        self.simulate_balance = True
        self.balance = Balance(self,self.model)
        self.balance_connected = False
        self.balance_droplets = []

        self.refuel_camera = RefuelCamera()
        self.droplet_camera = DropletCamera()

    def begin_communication_timer(self):
        print('Starting communication timer')
        self.communication_timer = QTimer()
        self.communication_timer.timeout.connect(self.request_status_update)
        self.communication_timer.start(5)  # Update every 100 ms

    def begin_execution_timer(self):
        print('Starting execution timer')
        self.execution_timer = QTimer()
        self.execution_timer.timeout.connect(self.send_next_command)
        self.execution_timer.start(90)  # Update every 100 ms

    def stop_communication_timer(self):
        print('Stopping communication timer')
        self.communication_timer.stop()

    def stop_execution_timer(self):
        print('Stopping execution timer')
        self.execution_timer.stop()

    def reset_board(self):
        print('Resetting board')
        self.board = None
        self.port = None
        self.command_queue.clear_queue()
        self.stop_communication_timer()
        self.stop_execution_timer()

    def connect_board(self,port):
        if port == 'Virtual':
            self.board = VirtualMachine(self)
            self.machine_connected_signal.emit(True)
            self.simulate = True
            self.port = port
        else:
            print('Connecting to machine at port:',port)
            try:
                self.board = serial.Serial(port, baudrate=115200,timeout=2)
                if not self.board.is_open:  # Add this line
                    self.error_occurred.emit('Could not open port')
                    raise serial.SerialException('Could not open port')  # Add this line
                
                time.sleep(0.2)  # Give some time for the device to respond
                # Read the response
                response = self.board.read_all().decode('ascii').strip()
                if 'Cycle_count' not in response:  # Check if the response matches the expected handshake
                    raise serial.SerialException(f'Unexpected response from machine: {response}')

                self.initial_reset_board()
                self.machine_connected_signal.emit(True)
                self.simulate = False
                self.port = port
            except Exception as e:
                if self.board.is_open:
                    self.board.close()
                self.error_occurred.emit(f'Could not connect to machine at port {port}\nError: {e}')
                self.machine_connected_signal.emit(False)
                self.port = None
                return False
        self.request_status_update()
        self.begin_communication_timer()
        self.begin_execution_timer()
        return True
    
    def reset_handler(self):
        print('Reset Complete')
    
    def initial_reset_board(self):
        self.reset_worker = ResetWorker(self)
        self.reset_worker.finished.connect(self.reset_handler)
        self.reset_worker.start()
    
    def disconnect_handler(self):
        if not self.simulate and self.board is not None:
            self.board.close()
        self.reset_board()
        self.disconnect_complete_signal.emit()

    def disconnect_board(self, error=False):
        print('--------Disconnecting from machine---------')
        if not error:
            self.worker = DisconnectWorker(self)
            self.worker.finished.connect(self.disconnect_handler)
            self.worker.start()
        else:
            self.disconnect_handler()
    
    def get_machine_port(self):
        return self.port
    
    def connect_balance(self,port):
        if self.balance.connect_balance(port):
            self.balance_connected = True
            return True
        else:
            self.balance_connected = False
            return False
    
    def disconnect_balance(self):
        self.balance.close_connection()
        self.balance_connected = False
        return
    
    def is_balance_connected(self):
        return self.balance_connected

    def start_refuel_camera(self):
        self.refuel_camera.start_camera()
        return

    def capture_refuel_image(self):
        return self.refuel_camera.capture_image()

    def stop_refuel_camera(self):
        self.refuel_camera.stop_camera()
        return

    def refuel_led_on(self):
        self.refuel_camera.led_on()
        return

    def refuel_led_off(self):
        self.refuel_camera.led_off()
        return
    
    def start_droplet_camera(self):
        self.droplet_camera.start_camera()
        return
    
    def capture_droplet_image(self):
        return self.droplet_camera.capture_non_blocking()
    
    def stop_droplet_camera(self):
        self.droplet_camera.stop_camera()
        return
    
    def start_read_camera(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('START_READ_CAMERA',0,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def stop_read_camera(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('STOP_READ_CAMERA',0,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def set_flash_duration(self,duration,handler=None,kwargs=None,manual=False):
        duration = round(duration,-2) # Only allow durations in increments of 100 nsec
        if duration >= 100:
            return self.add_command_to_queue('SET_WIDTH_F',duration,0,0,handler=handler,kwargs=kwargs,manual=manual)
        else:
            print('Duration too low')

    def set_flash_delay(self,delay,handler=None,kwargs=None,manual=False):
        delay = round(delay,-2)
        if delay >= 100:
            return self.add_command_to_queue('SET_DELAY_F',delay,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def set_imaging_droplets(self,droplets,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('SET_IMAGE_DROPLETS',droplets,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def set_exposure_time(self, exposure_time, handler=None):
        return self.droplet_camera.change_exposure_time(exposure_time,handler=handler)

    def trigger_flash(self):
        self.droplet_camera.trigger_flash()
        return
    
    def stop_flash(self):
        self.droplet_camera.stop_flash()
        return
    
    def update_command_numbers(self,current_command,last_completed):
        self.command_queue.update_command_status(current_command,last_completed)

    def request_status_update(self):
        """Send a request to the control board for a status update."""
        if self.board is not None:
            if self.simulate:
                status_string = self.board.get_current_state()
            else:
                try:
                    if self.board.in_waiting > 0:
                        status_string = self.board.readline().decode('utf-8').strip()
                        # print('Status string:',status_string)
                    else:
                        status_string = ''
                except Exception as e:
                    status_string = ''
                    self.error_occurred.emit(f'Error reading from machine\n Error: {e}')
                    self.error_count += 1
                    if self.error_count > 100:
                        print('------- Automatic disconnect -------')
                        self.disconnect_board(error=True)
            try:
                if status_string == '':
                    # print('No status string received')
                    return
                status_dict = self.parse_status_string(status_string)
                if status_dict == {}:
                    return
                self.status_updated.emit(status_dict)  # Emit the status update signal
                self.error_count = 0
            except ValueError as e:
                self.error_occurred.emit(f"Error parsing status string: {str(e)}-{status_string}")
            except Exception as e:
                self.error_occurred.emit(f"Unexpected error: {str(e)}-{status_string}")
                self.error_count += 1
                if self.error_count > 100:
                    print('------- Automatic disconnect -------')
                    self.disconnect_board(error=True)

    def parse_status_string(self, status_string):
        """Convert status string into a dictionary."""
        if not status_string:
            raise ValueError("Status string is empty")
        
        if "DEBUG" in status_string:
            # print('Status string:',status_string)
            return {}

        status_dict = {}
        # for item in status_string.split(','):
        try:
            key, value = status_string.split(':')
            status_dict[key] = value
        except ValueError:
            raise ValueError(f"Malformed item in status string: {status_string}")

        return status_dict

    def check_if_all_completed(self):
        """Check if all commands have been completed."""
        if len(self.command_queue.queue) == 0:
            return True
        return False
    
    def get_remaining_commands(self):
        return len(self.command_queue.queue)
    
    def add_command_to_queue(self, command_type, param1, param2, param3, handler=None, kwargs=None, manual=False):
        """Add a command to the queue."""
        if self.board is None:
            print('No board connected')
            return False
        if manual:
            completed = self.check_if_all_completed()
            if not completed:
                print('Cannot add manual command while commands are in queue')
                return False
        return self.command_queue.add_command(command_type, param1, param2, param3, handler, kwargs)

    def send_command_to_board(self, command):
        """Send a command to the board."""
        if self.board is not None:
            if self.simulate:
                #print(f'Sending command: {command.get_command()}')
                self.sent_command = command
                self.command_sent.emit({"command": command.get_command()})
                return True
            else:
                self.board.write(command.get_command().encode('utf-8'))
                self.board.flush()
                self.command_sent.emit({"command": command.get_command()})
                return True
        else:
            print('No board connected')
        return False

    def send_next_command(self):
        """Send the next command to the machine."""
        command = self.command_queue.get_next_command()
        if command is not None:
            self.send_command_to_board(command)
        return False
    
    def pause_commands(self):
        print('Pausing commands')
        new_command = Command(0, 'PAUSE', 0, 0, 0)
        if self.sent_command is not None:
            print('Overriding command:',self.sent_command.get_command())
        print('Sending pause command')
        self.send_command_to_board(new_command)

    def resume_commands(self):
        print('Resuming commands')
        new_command = Command(0, 'RESUME', 0, 0, 0)
        if self.sent_command is not None:
            print('Overriding command:',self.sent_command.get_command())
        print('Sending resume command')
        self.send_command_to_board(new_command)

    def clear_command_queue(self,handler=None):
        print('Clearing command queue')
        new_command = Command(0, 'CLEAR_QUEUE', 0, 0, 0, handler=handler)
        if self.sent_command is not None:
            print('Overriding command:',self.sent_command.get_command())
        print('Sending clear command')
        self.send_command_to_board(new_command)
        self.command_queue.clear_queue()

    def check_param_limits(self,param,min_val,max_val):
        if param >= min_val and param <= max_val:
            return True
        else:
            self.error_occurred.emit(f'Parameter out of range: {param} not in ({min_val},{max_val})')
            return False

    def update_state(self, state):
        """Update the machine state."""
        self.status_updated.emit(state)

    def enable_motors(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('ENABLE_MOTORS',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def disable_motors(self,handler=None,kwargs=None,manual=False):
        outcome = self.add_command_to_queue('DISABLE_MOTORS',0,0,0,handler=handler,kwargs=kwargs, manual=manual)
        self.add_command_to_queue('GRIPPER_OFF',0,0,0)
        return outcome
    
    def change_acceleration(self,acceleration,handler=None,kwargs=None,manual=False):
        if self.check_param_limits(acceleration,1,50000):
            return self.add_command_to_queue('CHANGE_ACCEL',acceleration,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def reset_acceleration(self,handler=None,kwargs=None,manual=False):
        self.add_command_to_queue('RESET_ACCEL',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def regulate_print_pressure(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('REGULATE_PRESSURE_P',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def regulate_refuel_pressure(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('REGULATE_PRESSURE_R',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
        
    def deregulate_pressure(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('DEREGULATE_PRESSURE',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def reset_print_syringe(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('RESET_P',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def reset_refuel_syringe(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('RESET_R',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
        
    def set_relative_X(self, x, handler=None, kwargs=None, manual=False):
        if self.check_param_limits(x,-50000,50000):
            return self.add_command_to_queue('RELATIVE_X', x, 0, 0, handler=handler, kwargs=kwargs, manual=manual)
    
    def set_absolute_X(self, x, handler=None, kwargs=None, manual=False):
        if self.check_param_limits(x,-50000,50000):
            return self.add_command_to_queue('ABSOLUTE_X', x, 0, 0, handler=handler, kwargs=kwargs, manual=manual)
    
    def set_relative_Y(self, y, handler=None, kwargs=None, manual=False):
        if self.check_param_limits(y,-50000,50000):
            return self.add_command_to_queue('RELATIVE_Y', y, 0, 0, handler=handler, kwargs=kwargs, manual=manual)
    
    def set_absolute_Y(self, y, handler=None, kwargs=None, manual=False):
        if self.check_param_limits(y,-50000,50000):
            return self.add_command_to_queue('ABSOLUTE_Y', y, 0, 0, handler=handler, kwargs=kwargs, manual=manual)
    
    def set_relative_Z(self, z, handler=None, kwargs=None, manual=False):
        if self.check_param_limits(z,-50000,50000):
            return self.add_command_to_queue('RELATIVE_Z', z, 0, 0, handler=handler, kwargs=kwargs, manual=manual)
    
    def set_absolute_Z(self, z, handler=None, kwargs=None, manual=False):
        if self.check_param_limits(z,-50000,50000):
            return self.add_command_to_queue('ABSOLUTE_Z', z, 0, 0, handler=handler, kwargs=kwargs, manual=manual)
    
    def set_relative_coordinates(self, x, y, z, handler=None, kwargs=None, manual=False):
        if self.check_param_limits(x,-50000,50000) and self.check_param_limits(y,-50000,50000) and self.check_param_limits(z,-50000,50000):
            return self.add_command_to_queue('RELATIVE_XYZ', x, y, z, handler=handler, kwargs=kwargs, manual=manual)
        
    def set_absolute_coordinates(self, x, y, z, handler=None, kwargs=None, manual=False):
        if self.check_param_limits(x,-50000,50000) and self.check_param_limits(y,-50000,50000) and self.check_param_limits(z,-50000,50000):
            return self.add_command_to_queue('ABSOLUTE_XYZ', x, y, z, handler=handler, kwargs=kwargs, manual=manual)
        
    def convert_to_psi(self,pressure):
        return round(((pressure - self.psi_offset) / self.fss) * self.psi_max,4)
    
    def convert_to_raw_pressure(self,psi):
        return int((psi / self.psi_max) * self.fss + self.psi_offset)

    def set_relative_print_pressure(self,psi,handler=None,kwargs=None,manual=False):
        pressure = self.convert_to_raw_pressure(psi)
        pressure -= self.psi_offset
        print('Setting relative print pressure:',pressure)
        if self.check_param_limits(pressure,-2185,2185):
            return self.add_command_to_queue('RELATIVE_PRESSURE_P',pressure,0,0,handler=handler,kwargs=kwargs,manual=manual)
        
    def set_relative_refuel_pressure(self,psi,handler=None,kwargs=None,manual=False):
        pressure = self.convert_to_raw_pressure(psi)
        pressure -= self.psi_offset
        print('Setting relative refuel pressure:',pressure)
        if self.check_param_limits(pressure,-2185,2185):
            return self.add_command_to_queue('RELATIVE_PRESSURE_R',pressure,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def set_absolute_print_pressure(self,psi,handler=None,kwargs=None,manual=False):
        pressure = self.convert_to_raw_pressure(psi)
        print('Setting absolute print pressure:',pressure)
        if self.check_param_limits(pressure,7755,10376):
            return self.add_command_to_queue('ABSOLUTE_PRESSURE_P',pressure,0,0,handler=handler,kwargs=kwargs,manual=manual)
        
    def set_absolute_refuel_pressure(self,psi,handler=None,kwargs=None,manual=False):
        pressure = self.convert_to_raw_pressure(psi)
        print('Setting absolute refuel pressure:',pressure)
        if self.check_param_limits(pressure,7755,10376):
            return self.add_command_to_queue('ABSOLUTE_PRESSURE_R',pressure,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def set_print_pulse_width(self,pulse_width,handler=None,kwargs=None,manual=False):
        if self.check_param_limits(pulse_width,100,10000):
            return self.add_command_to_queue('SET_WIDTH_P',int(pulse_width),0,0,handler=handler,kwargs=kwargs,manual=manual)
        
    def set_refuel_pulse_width(self,pulse_width,handler=None,kwargs=None,manual=False):
        if self.check_param_limits(pulse_width,100,10000):
            return self.add_command_to_queue('SET_WIDTH_R',int(pulse_width),0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def enter_print_mode(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('PRINT_MODE',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def exit_print_mode(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('NORMAL_MODE',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def home_motor_handler(self):
        self.homed = True
        self.location = 'Home'
        self.homing_completed.emit()

    def home_motors(self,handler=None,kwargs=None,manual=False):
        if handler == None:
            handler = self.home_motor_handler
        self.add_command_to_queue('HOME_Z',0,0,0,handler=None,kwargs=kwargs,manual=manual)
        self.add_command_to_queue('HOME_X',0,0,0,handler=None,kwargs=kwargs,manual=manual)
        self.add_command_to_queue('HOME_Y',0,0,0,handler=None,kwargs=kwargs,manual=manual)
        self.add_command_to_queue('HOME_P',0,0,0,handler=None,kwargs=kwargs,manual=manual)
        self.add_command_to_queue('HOME_R',0,0,0,handler=handler,kwargs=kwargs, manual=manual)
        return True
    
    def open_gripper_handler(self,additional_handler=None):
        if additional_handler is not None:
            additional_handler()
        self.gripper_open.emit()

    def open_gripper(self,handler=None,kwargs=None,manual=False):
        if handler == None:
            new_handler = self.open_gripper_handler
        else:
            new_handler = lambda: self.open_gripper_handler(handler)
        return self.add_command_to_queue('OPEN_GRIPPER',0,0,0,handler=new_handler,kwargs=kwargs,manual=manual)
    
    def close_gripper_handler(self,additional_handler=None):
        if additional_handler is not None:
            additional_handler()
        self.gripper_closed.emit()

    def close_gripper(self,handler=None,kwargs=None,manual=False):
        if handler == None:
            new_handler = self.close_gripper_handler
        else:
            new_handler = lambda: self.close_gripper_handler(handler)
        return self.add_command_to_queue('CLOSE_GRIPPER',0,0,0,handler=new_handler,kwargs=kwargs,manual=manual)
        
    def gripper_off_handler(self):
        self.gripper_off_signal.emit()

    def gripper_off(self,handler=None,kwargs=None,manual=False):
        if handler == None:
            handler = self.gripper_off_handler
        return self.add_command_to_queue('GRIPPER_OFF',0,0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def wait_command(self,handler=None,kwargs=None,manual=False):
        return self.add_command_to_queue('WAIT',200,0,0,handler=handler,kwargs=kwargs,manual=manual)

    def print_droplets(self,droplet_count,handler=None,kwargs=None,manual=False):
        self.check_param_limits(droplet_count,1,1000)
        return self.add_command_to_queue('PRINT',int(droplet_count),0,0,handler=handler,kwargs=kwargs,manual=manual)

    def print_only(self,droplet_count,handler=None,kwargs=None,manual=False):
        self.check_param_limits(droplet_count,1,1000)
        return self.add_command_to_queue('PRINT_ONLY',int(droplet_count),0,0,handler=handler,kwargs=kwargs,manual=manual)
    
    def refuel_only(self,droplet_count,handler=None,kwargs=None,manual=False):
        self.check_param_limits(droplet_count,1,1000)
        return self.add_command_to_queue('REFUEL_ONLY',int(droplet_count),0,0,handler=handler,kwargs=kwargs,manual=manual)

    def calibrate_pressure_handler(self):
        self.all_calibration_droplets_printed.emit()

    def get_print_pulse_width(self):
        return self.model.machine_model.get_print_pulse_width()

    def get_refuel_pulse_width(self):
        return self.model.machine_model.get_refuel_pulse_width()
    
    def get_print_pressure(self):
        return self.model.machine_model.get_print_pressure()
    
    def get_refuel_pressure(self):
        return self.model.machine_model.get_refuel_pressure()

    def print_calibration_droplets(self,num_droplets,manual=False,pressure=None):
        print('Machine: Printing calibration droplets')
        if self.balance.simulate:
            if pressure is None:
                pressure = self.get_print_pressure()
            self.balance_droplets.append([num_droplets,pressure])
        self.check_param_limits(num_droplets,1,1000)
        self.print_droplets(num_droplets,handler=self.calibrate_pressure_handler,manual=manual)
