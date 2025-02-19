from PySide6.QtCore import QObject, Signal
from PySide6 import QtCore
from serial.tools.list_ports import comports
from Model import Model,PrinterHead,Slot
import time
import numpy as np
import os
import serial


class Controller(QObject):
    """Controller class for the application."""
    array_complete = Signal()
    update_slots_signal = Signal()
    update_volumes_in_view_signal = Signal()
    error_occurred_signal = Signal(str,str)
    def __init__(self, machine, model):
        super().__init__()
        self.machine = machine
        self.model = model
        self.expected_position = self.model.machine_model.get_current_position_dict()

        # This variable will temporarily hold the callback for the next capture.
        self.pending_capture_callback = None

        # Connect the machine's signals to the controller's handlers
        self.machine.status_updated.connect(self.handle_status_update)
        self.machine.error_occurred.connect(self.handle_error)
        self.machine.homing_completed.connect(self.home_complete_handler)
        self.machine.gripper_open.connect(self.model.machine_model.open_gripper)
        self.machine.gripper_closed.connect(self.model.machine_model.close_gripper)
        
        self.machine.machine_connected_signal.connect(self.update_machine_connection_status)
        self.machine.disconnect_complete_signal.connect(self.reset_board)
        self.model.machine_model.command_numbers_updated.connect(self.update_command_numbers)
        self.machine.command_queue.commands_completed.connect(self.update_expected_with_current)

        self.machine.balance.balance_mass_updated_signal.connect(self.model.calibration_model.update_mass)
        self.machine.all_calibration_droplets_printed.connect(self.start_mass_stabilization_timer)

        self.model.printer_head_manager.volume_changed_signal.connect(self.update_volumes_in_view)
        
        self.model.calibration_manager.captureImageRequested.connect(self.handle_capture_request)
        self.model.calibration_manager.moveRequested.connect(self.handle_move_request)
        self.model.calibration_manager.moveAbsoluteRequested.connect(self.handle_absolute_move_request)
        # self.model.calibration_manager.dropletChangeRequested.connect(self.handle_droplet_change_request)
        self.model.calibration_manager.changeSettingsRequested.connect(self.handle_settings_change_request)
        self.machine.droplet_camera.image_captured_signal.connect(self._on_image_captured)

    def handle_status_update(self, status_dict):
        """Handle the status update and update the machine model."""
        self.model.update_state(status_dict)

    def handle_error(self, error_message):
        """Handle errors from the machine."""
        pass
        #print(f"Error occurred: {error_message}")
        # self.error_occurred_signal.emit('Error Occurred',error_message)

    def update_command_numbers(self):
        """Pass the current command and last completed command to the command queue"""
        self.machine.update_command_numbers(*self.model.machine_model.get_command_numbers())
    
    def update_volumes_in_view(self):
        """Update the volume in the view."""
        self.update_volumes_in_view_signal.emit()

    def reset_board(self):
        """Reset the machine board."""
        self.machine.reset_board()
        self.model.machine_model.disconnect_machine()
    
    def update_available_ports(self):
        # Get a list of all connected COM ports
        ports = comports()
        active_ports = []
        
        for port in ports:
            port_name = port.device
            if "ttyAMA" in port_name:
                continue
            # Check if the port exists in the /dev directory
            if os.path.exists(port_name):
                try:
                    # Try to open the port to ensure it is active
                    with serial.Serial(port_name) as ser:
                        active_ports.append(port_name)
                except (OSError, serial.SerialException):
                    # Port exists but cannot be opened (not active)
                    continue

        # return active_ports
        self.model.machine_model.update_ports(active_ports)

    def connect_machine(self, port):
        """Connect to the machine."""
        self.machine.connect_board(port)

    def disconnect_machine(self):
        """Disconnect from the machine."""
        self.machine.disconnect_board()

    def update_machine_connection_status(self, status):
        """Update the machine connection status."""
        if status:
            self.model.machine_model.connect_machine()
        else:
            self.model.machine_model.disconnect_machine()

    def get_machine_port(self):
        """Get the currently connected machine port."""
        return self.machine.get_machine_port()

    def connect_balance(self, port):
        """Connect to the microbalance."""
        if self.machine.connect_balance(port):
            # Update the model state
            self.model.machine_model.connect_balance(port)
    
    def disconnect_balance(self):
        """Disconnect from the balance."""
        self.machine.disconnect_balance()
        self.model.machine_model.disconnect_balance()

    def update_balance_prediction_models(self,target_volume=40):
        pred_model = self.model.calibration_model.get_selected_model_path()
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
        
        Parameters:
        - current_pos: tuple of floats (x, y, z) representing the current position.
        - target_pos: tuple of floats (x, y, z) representing the target position.
        - obstacles: list of obstacles, where each obstacle is defined by two tuples representing
                    the opposite corners of a 3D rectangular prism: [(corner1, corner2), ...]
        - boundaries: tuple of two corners defining the machine workspace boundaries.

        Returns:
        - True if a collision or out-of-bounds is detected, False otherwise.
        """
        boundaries = self.model.location_model.get_boundaries()
        obstacles = self.model.location_model.get_obstacles()

        # Boundary check
        for axis in ['X', 'Y', 'Z']:
            if not (boundaries['min'][axis] <= min(current_pos[axis], target_pos[axis]) and 
                    max(current_pos[axis], target_pos[axis]) <= boundaries['max'][axis]):
                #print(f"Path goes out of bounds on axis {axis}.")
                return True

        # Obstacle check
        for obstacle in obstacles:
            min_corner = {axis: min(obstacle['corner1'][axis], obstacle['corner2'][axis]) for axis in ['X', 'Y', 'Z']}
            max_corner = {axis: max(obstacle['corner1'][axis], obstacle['corner2'][axis]) for axis in ['X', 'Y', 'Z']}
            
            for axis in ['X', 'Y', 'Z']:
                min_proj = min(current_pos[axis], target_pos[axis])
                max_proj = max(current_pos[axis], target_pos[axis])
                
                if max_proj < min_corner[axis] or min_proj > max_corner[axis]:
                    break
            else:
                #print(f"Collision with {obstacle['name']} detected.")
                #print(f'Current position: {current_pos}')
                #print(f'Target position: {target_pos}')
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

    def set_absolute_coordinates(self, x, y, z, manual=False, handler=None, override=False):
        """Set the absolute coordinates for the machine."""
        new_position = {'X': x, 'Y': y, 'Z': z}
        # Check for collisions if not overriding.
        if not override:
            if self.check_collision(self.expected_position, new_position):
                print('Collision detected')
                return False

        commands = []
        current = self.expected_position

        # Determine the order of moves based on Z change.
        if current['Z'] != z:
            if z < current['Z']:
                # Moving up: move Z first, then Y, then X.
                if z != current['Z']:
                    commands.append(('Z', z))
                if y != current['Y']:
                    commands.append(('Y', y))
                if x != current['X']:
                    commands.append(('X', x))
            else:
                # Moving down: move Y first, then X, then Z.
                if y != current['Y']:
                    commands.append(('Y', y))
                if x != current['X']:
                    commands.append(('X', x))
                if z != current['Z']:
                    commands.append(('Z', z))
        else:
            # Z is unchanged, so only X and Y need updating.
            if y != current['Y']:
                commands.append(('Y', y))
            if x != current['X']:
                commands.append(('X', x))

        # Execute the commands in order, attaching the callback only to the last one.
        for i, (axis, value) in enumerate(commands):
            is_last = (i == len(commands) - 1)
            current_handler = handler if is_last else None
            if axis == 'X':
                self.machine.set_absolute_X(value, manual=manual, handler=current_handler)
            elif axis == 'Y':
                self.machine.set_absolute_Y(value, manual=manual, handler=current_handler)
            elif axis == 'Z':
                self.machine.set_absolute_Z(value, manual=manual, handler=current_handler)

        # Update the expected position.
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
        if current_p > 22500:
            self.reset_print_syringe()
    
    def check_refuel_syringe_position(self):
        """Checks the syringe position and resets it if nearly at the limit."""
        current_r = self.model.machine_model.get_current_r_motor()
        if current_r > 18000:
            self.reset_refuel_syringe()

    def pause_machine(self):
        """Pause the machine."""
        self.machine.pause_machine()

    def home_machine(self):
        """Home the machine."""
        print("Homing machine...")
        self.machine.home_motors()

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
            success = self.machine.deregulate_pressure()  # Assuming method exists
            success_2 = True
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
    
    def update_location_handler(self,name):
        """Update the current location."""
        self.model.machine_model.update_current_location(name)

    def check_if_all_completed(self):
        """Check if all commands have been completed."""
        return self.machine.check_if_all_completed()

    def move_to_location(self, name, direct=True, safe_y=False, x_offset=False,z_offset=False,manual=False,coords=None,override=False):
        """Move to the saved location."""
        if manual == True:
            status = self.machine.check_if_all_completed()
            if status == False:
                print('Cannot move: Commands are still running')
                return
        if coords != None:
            target = coords.copy()
        else:
            original_target = self.model.location_model.get_location_dict(name)
            target = original_target.copy()
        if x_offset:
            #print(f'Applying X offset:{target['X']} -> {target['X'] + 2500}')
            target['X'] += 2500

        if z_offset:
            target['Z'] -= 18000
        # Use expected position instead of current position from the model
        current = self.expected_position

        up_first = False
        if direct and current['Z'] > target['Z']:
            up_first = True
            self.set_absolute_Z(target['Z'])

        x_limit = 5500
        safe_height = 3000
        safe_y_value = 3500
        if (target['Y'] > 9500) or (current['Y'] > 9500 and current['X'] > x_limit):
            print('Not applying safe Y')
            
        elif (current['X'] > x_limit and target['X'] < x_limit) or (current['X'] < x_limit and target['X'] > x_limit):
            #print(f'Crossing x limit: {current['X']} -> {target['X']}')
            safe_y = True
            # direct = False

        if not direct and not safe_y:
            print('Not direct, not safe-y')
            self.set_absolute_Z(safe_height,override=override)
            self.set_absolute_Y(target['Y'],override=override)
            self.set_absolute_X(target['X'],override=override)
            self.set_absolute_Z(target['Z'],handler=lambda: self.update_location_handler(name),override=override)

        elif not direct and safe_y:
            print('Not direct, safe-y')
            self.set_absolute_Z(safe_height,override=override)
            self.set_absolute_Y(safe_y_value,override=override)
            self.set_absolute_X(target['X'],override=override)
            self.set_absolute_Y(target['Y'],override=override)
            self.set_absolute_Z(target['Z'],handler=lambda: self.update_location_handler(name),override=override)
        elif direct and safe_y:
            if up_first:
                self.set_absolute_Z(target['Z'],override=override)
                self.set_absolute_Y(safe_y_value,override=override)
                self.set_absolute_X(target['X'],override=override)
                self.set_absolute_Y(target['Y'],handler=lambda: self.update_location_handler(name),override=override)
            else:
                self.set_absolute_Y(safe_y_value,override=override)
                self.set_absolute_X(target['X'],override=override)
                self.set_absolute_Y(target['Y'],override=override)
                self.set_absolute_Z(target['Z'],handler=lambda: self.update_location_handler(name),override=override)
        else:
            if up_first:
                self.set_absolute_Z(target['Z'],override=override)
                self.set_absolute_Y(target['Y'],override=override)
                self.set_absolute_X(target['X'],handler=lambda: self.update_location_handler(name),override=override)
            else:
                self.set_absolute_Y(target['Y'],override=override)
                self.set_absolute_X(target['X'],override=override)
                self.set_absolute_Z(target['Z'],handler=lambda: self.update_location_handler(name),override=override)

        # self.update_expected_position(x=target['X'], y=target['Y'], z=target['Z'])
    
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
        self.wait_command()
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
        is_valid, error_msg = self.model.rack_model.verify_transfer_to_gripper(slot)
        if is_valid:
            self.open_gripper()
            self.wait_command()
            #print(f'Picking up printer head from slot {slot}')
            coords = self.model.rack_model.get_slot_coordinates(slot)
            name = 'Slot-'+str(slot+1)
            self.move_to_location(name,x_offset=True,coords=coords)

            self.move_to_location(name,coords=coords,override=True)
            self.close_gripper(handler=lambda: self.pick_up_handler(slot))
            self.wait_command()
            self.move_to_location(name,x_offset=True,coords=coords,override=True)
            # self.model.calibration_model.update_calibration_models(self.model.rack_model.get_gripper_printer_head())
        else:
            #print(f'Error: {error_msg}')
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
        is_valid, error_msg = self.model.rack_model.verify_transfer_from_gripper(slot)
        if is_valid:
            #print(f'Dropping off printer head to slot {slot}')
            coords = self.model.rack_model.get_slot_coordinates(slot)
            name = 'Slot-'+str(slot+1)
            self.move_to_location(name,x_offset=True,coords=coords)
            self.move_to_location(name,coords=coords,override=True)
            self.open_gripper(handler=lambda: self.drop_off_handler(slot))
            self.wait_command()
            self.move_to_location(name,x_offset=True,coords=coords,override=True)
            self.close_gripper()
            self.wait_command()
        else:
            #print(f'Error: {error_msg}')
            pass

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
        printer_head = self.model.rack_model.get_gripper_printer_head()
        if printer_head is not None:
            if printer_head.check_calibration_complete():
                print('Controller: using calibrations to change pulse width')
                vol, res, target, bias, pred_model, resistance_pulse_width = printer_head.get_prediction_data()
                if expected_volume is not None:
                    #print(f'Controller: using expected volume: {expected_volume}')
                    vol = expected_volume
                new_pulse_width = self.model.calibration_model.predict_pulse_width(vol, res, target, bias=bias, prediction_model=pred_model,resistance_pulse_width=resistance_pulse_width)
                if abs(self.model.machine_model.get_print_pulse_width() - new_pulse_width) > 2:
                    self.set_print_pulse_width(new_pulse_width,manual=False)
            
                if handler is None:
                    handler = self.volume_update_handler
                    kwargs = {'droplet_count':droplets}
                else:
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

    def print_calibration_droplets(self,droplets,manual=False,pressure=None):
        """Print a specified number of droplets for calibration."""
        print('Controller: Printing calibration droplets')
        self.machine.print_calibration_droplets(droplets,manual=manual,pressure=pressure)

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
            if update_volume:
                self.model.rack_model.get_gripper_printer_head().record_droplet_volume_lost(target_droplets)
            self.machine.reset_acceleration()
            self.exit_print_mode()
            self.move_to_location('pause')
            self.move_to_location('pause',z_offset=True)
            self.model.well_plate.get_well(well_id).record_stock_print(stock_id, target_droplets)
            self.model.experiment_model.update_progress(well_id)
            self.array_complete.emit()
            print('---Printing complete---')
        
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

    def check_if_all_completed(self):
        """Check if all commands have been completed."""
        return self.machine.check_if_all_completed()
    
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
        self.wait_command()

        self.move_to_location('pause',z_offset=True)
        self.move_to_location('pause')
        self.machine.change_acceleration(16000)
        self.enter_print_mode()

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
            #print(f'Printing {target_droplets} droplets to well {well.well_id}')
            is_last_iteration = i == len(wells_with_droplets) - 1
            if update_volume:
                expected_volume -= target_droplets * droplet_volume / 1000
                if expected_volume < 10:
                    self.print_droplets(target_droplets,expected_volume=expected_volume, handler=self.refill_printer_head_handler,kwargs={'well_id':well.well_id,'stock_id':current_stock_id,'target_droplets':target_droplets,'update_volume':update_volume})
                    print('---Printer head needs to be reloaded---')
                    return
            if not is_last_iteration:
                self.print_droplets(target_droplets,expected_volume=expected_volume, handler=self.well_complete_handler,kwargs={'well_id':well.well_id,'stock_id':current_stock_id,'target_droplets':target_droplets,'update_volume':update_volume})
            else:
                self.print_droplets(target_droplets,expected_volume=expected_volume, handler=self.last_well_complete_handler,kwargs={'well_id':well.well_id,'stock_id':current_stock_id,'target_droplets':target_droplets,'update_volume':update_volume})
            
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

    def capture_droplet_image(self, callback=None):
        """
        Initiates a non-blocking image capture. If a callback is provided,
        it will be invoked with the captured frame once the capture completes.
        """
        self.pending_capture_callback = callback
        self.machine.capture_droplet_image()

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

    def set_save_directory(self, directory):
        self.model.droplet_camera_model.set_save_directory(directory)      

    def handle_capture_request(self, callback):
        # Start the non-blocking capture process, then invoke the callback with the captured image.
        self.capture_droplet_image(callback=callback)

    def handle_move_request(self, move_vector, callback):
        # Perform the move command then call the callback.
        dX, dY, dZ = move_vector
        self.set_relative_coordinates(dX, dY, dZ, manual=False,handler=callback)
        print('Controller: Move request handled')

    def handle_absolute_move_request(self, target_position, callback):
        # Perform the move command then call the callback.
        if type(target_position) == tuple or type(target_position) == list:
            target = {'X': target_position[0], 'Y': target_position[1], 'Z': target_position[2]}
        else:
            target = target_position.copy()
        self.set_absolute_coordinates(target['X'], target['Y'], target['Z'], manual=False,handler=callback)
        print('Controller: Move request handled')

    # def handle_droplet_change_request(self, num_droplets,callback):
    #     self.set_imaging_droplets(num_droplets,callback=callback)

    def handle_settings_change_request(self, settings, callback):
        # Update the settings in the model and machine.
        num_settings = len(settings)
        current_call_back = None
        for i, (key, value) in enumerate(settings.items()):
            if i == num_settings - 1:
                current_call_back = callback
            if key == 'num_droplets':
                self.set_imaging_droplets(value,callback=current_call_back)
            elif key == 'flash_duration':
                self.set_flash_duration(value, callback=current_call_back)
            elif key == 'flash_delay':
                self.set_flash_delay(value, callback=current_call_back)
            elif key == 'exposure_time':
                self.set_exposure_time(value, callback=current_call_back)
            elif key == 'print_pulse_width':
                self.set_print_pulse_width(value, handler=current_call_back)
            elif key == 'refuel_pulse_width':
                self.set_refuel_pulse_width(value, handler=current_call_back)
            elif key == 'print_pressure':
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
        # Update the model and/or view (assuming your model has such a method)
        self.model.droplet_camera_model.update_image(frame)
        
        # If a callback was set for the capture, call it.
        if self.pending_capture_callback:
            callback = self.pending_capture_callback
            self.pending_capture_callback = None  # Clear for future captures.
            callback(frame)

    def start_nozzle_calibration(self):
        # Tell the Model to start the nozzle position calibration.
        self.model.calibration_manager.start_nozzle_calibration()

    def start_nozzle_focus_calibration(self):
        # Tell the Model to start the nozzle focus calibration.
        self.model.calibration_manager.start_nozzle_focus_calibration()

    def start_droplet_emergence_calibration(self):
        # Tell the Model to start the droplet emergence calibration.
        self.model.calibration_manager.start_droplet_emergence_calibration()

    def start_pressure_calibration(self):
        # Tell the Model to start the pressure calibration.
        self.model.calibration_manager.start_pressure_calibration()

    def start_trajectory_calibration(self):
        # Tell the Model to start the trajectory calibration.
        self.model.calibration_manager.start_trajectory_calibration()

    def start_droplet_search_calibration(self):
        # Tell the Model to start the droplet search calibration.
        self.model.calibration_manager.start_droplet_search_calibration()

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
            move_vector = self.model.droplet_camera_model.calculate_move_to_top_center(current,offset=50)
            dX, dY, dZ = move_vector
            target_position['X'] += dX
            target_position['Y'] += dY
            target_position['Z'] += dZ

        self.set_absolute_coordinates(target_position['X'],target_position['Y'],target_position['Z'],handler=callback)

