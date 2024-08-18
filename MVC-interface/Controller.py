from PySide6.QtCore import QObject
from serial.tools.list_ports import comports
from Model import Model,PrinterHead,Slot
import time


class Controller(QObject):
    def __init__(self, machine, model):
        super().__init__()
        self.machine = machine
        self.model = model
        self.expected_position = self.model.machine_model.get_current_position_dict()

        # Connect the machine's signals to the controller's handlers
        self.machine.status_updated.connect(self.handle_status_update)
        self.machine.error_occurred.connect(self.handle_error)
        self.machine.homing_completed.connect(self.home_complete_handler)
        self.machine.gripper_open.connect(self.model.machine_model.open_gripper)
        self.machine.gripper_closed.connect(self.model.machine_model.close_gripper)

    def handle_status_update(self, status_dict):
        """Handle the status update and update the machine model."""
        self.model.update_state(status_dict)

    def handle_error(self, error_message):
        """Handle errors from the machine."""
        print(f"Error occurred: {error_message}")
        # Here, you could also update the view to display the error message

    def update_available_ports(self):
        # Get a list of all connected COM ports
        ports = comports()
        port_names = [port.device for port in ports]
        self.model.machine_model.update_ports(port_names)

    def connect_machine(self, port):
        """Connect to the machine."""
        if self.machine.connect_board(port):
            # Update the model state
            self.model.machine_model.connect_machine(port)
        else:
            print("Failed to connect to machine.")

    def disconnect_machine(self):
        """Disconnect from the machine."""
        self.machine.disconnect_board()
        self.model.machine_model.disconnect_machine()


    def connect_balance(self, port):
        """Connect to the microbalance."""
        if self.machine.connect_balance(port):
            # Update the model state
            self.model.machine_model.connect_balance(port)
    
    def disconnect_balance(self):
        """Disconnect from the balance."""
        self.machine.disconnect_balance()
        self.model.machine_model.disconnect_balance()

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

    def set_relative_coordinates(self, x, y, z,manual=False):
        """Set the relative coordinates for the machine."""
        print(f"Setting relative coordinates: x={x}, y={y}, z={z}")
        self.machine.set_relative_coordinates(x, y, z,manual=manual)

    def set_absolute_coordinates(self, x, y, z,manual=False):
        """Set the absolute coordinates for the machine."""
        print(f"Setting absolute coordinates: x={x}, y={y}, z={z}")
        self.machine.set_absolute_coordinates(x, y, z,manual=manual)

    def set_relative_pressure(self, pressure,manual=False):
        """Set the relative pressure for the machine."""
        print(f"Setting relative pressure: {pressure}")
        self.machine.set_relative_pressure(pressure,manual=manual)

    def home_machine(self):
        """Home the machine."""
        print("Homing machine...")
        self.machine.home_motors()

    def toggle_motors(self):
        """Slot to toggle the motor state."""
        if self.model.machine_model.motors_enabled:
            self.machine.disable_motors()  # Assuming method exists
        else:
            self.machine.enable_motors()  # Assuming method exists
        self.model.machine_model.toggle_motor_state()  # Update the model state

    def toggle_regulation(self):
        """Slot to toggle the motor state."""
        if self.model.machine_model.regulating_pressure:
            self.machine.deregulate_pressure()  # Assuming method exists
        else:
            self.machine.regulate_pressure()  # Assuming method exists
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

    def update_expected_position(self, x=None, y=None, z=None):
        """Update the expected position after a move."""
        if x is not None:
            self.expected_position['x'] = x
        if y is not None:
            self.expected_position['y'] = y
        if z is not None:
            self.expected_position['z'] = z
    
    def update_location_handler(self,name):
        """Update the current location."""
        self.model.machine_model.update_current_location(name)

    def move_to_location(self, name, direct=True, safe_y=False, x_offset=False):
        """Move to the saved location."""
        original_target = self.model.location_model.get_location_dict(name)
        target = original_target.copy()
        if x_offset:
            print(f'Applying X offset:{target["x"]} -> {target["x"] - 2500}')
            target['x'] += -2500

        # Use expected position instead of current position from the model
        current = self.expected_position

        up_first = False
        if direct and current['z'] < target['z']:
            up_first = True
            self.machine.set_absolute_coordinates(
                current['x'], current['y'], target['z'],
                handler=lambda: self.update_expected_position(z=target['z'])
            )

        x_limit = -5500
        safe_height = -3000
        safe_y_value = 3500
        if (current['x'] > x_limit and target['x'] < x_limit) or (current['x'] < x_limit and target['x'] > x_limit):
            print(f'Crossing x limit: {current["x"]} -> {target["x"]}')
            safe_y = True

        if not direct and not safe_y:
            print('Not direct, not safe-y')
            self.machine.set_absolute_coordinates(
                current['x'], current['y'], safe_height,
                handler=lambda: self.update_expected_position(z=safe_height)
            )
            self.machine.set_absolute_coordinates(
                target['x'], target['y'], safe_height,
                handler=lambda: self.update_expected_position(x=target['x'], y=target['y'])
            )
        elif not direct and safe_y:
            print('Not direct, safe-y')
            self.machine.set_absolute_coordinates(
                current['x'], current['y'], safe_height,
                handler=lambda: self.update_expected_position(z=safe_height)
            )
            self.machine.set_absolute_coordinates(
                current['x'], safe_y_value, safe_height,
                handler=lambda: self.update_expected_position(y=safe_y_value)
            )
            self.machine.set_absolute_coordinates(
                target['x'], safe_y_value, safe_height,
                handler=lambda: self.update_expected_position(x=target['x'])
            )
            self.machine.set_absolute_coordinates(
                target['x'], target['y'], safe_height,
                handler=lambda: self.update_expected_position(y=target['y'])
            )
        elif direct and safe_y:
            if up_first:
                self.machine.set_absolute_coordinates(
                    current['x'], safe_y_value, target['z'],
                    handler=lambda: self.update_expected_position(y=safe_y_value, z=target['z'])
                )
                self.machine.set_absolute_coordinates(
                    target['x'], safe_y_value, target['z'],
                    handler=lambda: self.update_expected_position(x=target['x'])
                )
            else:
                self.machine.set_absolute_coordinates(
                    current['x'], safe_y_value, current['z'],
                    handler=lambda: self.update_expected_position(y=safe_y_value)
                )
                self.machine.set_absolute_coordinates(
                    target['x'], safe_y_value, current['z'],
                    handler=lambda: self.update_expected_position(x=target['x'])
                )
                self.machine.set_absolute_coordinates(
                    target['x'], target['y'], current['z'],
                    handler=lambda: self.update_expected_position(y=target['y'])
                )

        self.machine.set_absolute_coordinates(
            target['x'], target['y'], target['z'],
            handler=lambda: self.update_location_handler(name)
        )
        self.update_expected_position(x=target['x'], y=target['y'], z=target['z'])
    
    def open_gripper(self,handler=None):
        """Open the gripper."""
        self.machine.open_gripper(handler=handler)

    def close_gripper(self,handler=None):
        """Close the gripper."""
        self.machine.close_gripper(handler=handler)

    def wait_command(self):
        """Tells the machine to wait a specified amount of time."""
        self.machine.wait_command()
    
    def pick_up_handler(self,slot):
        """Handle the pick up signal from the rack."""
        self.model.rack_model.transfer_to_gripper(slot)

    def pick_up_printer_head(self,slot):
        """Pick up a printer head from the rack."""
        is_valid, error_msg = self.model.rack_model.verify_transfer_to_gripper(slot)
        if is_valid:
            self.open_gripper()
            self.wait_command()
            print(f'Picking up printer head from slot {slot}')
            location = f'rack_position_{slot+1}_{self.model.rack_model.get_num_slots()}'
            self.move_to_location(location,x_offset=True)
            self.move_to_location(location)
            self.close_gripper(handler=lambda: self.pick_up_handler(slot))
            self.wait_command()
            self.move_to_location(location,x_offset=True)
        else:
            print(f'Error: {error_msg}')

    def drop_off_handler(self,slot):
        """Handle the drop off signal from the rack."""
        self.model.rack_model.transfer_from_gripper(slot)

    def drop_off_printer_head(self,slot):
        """Drop off a printer head to the rack."""
        is_valid, error_msg = self.model.rack_model.verify_transfer_from_gripper(slot)
        if is_valid:
            print(f'Dropping off printer head to slot {slot}')
            location = f'rack_position_{slot+1}_{self.model.rack_model.get_num_slots()}'
            self.move_to_location(location,x_offset=True)
            self.move_to_location(location)
            self.open_gripper(handler=lambda: self.drop_off_handler(slot))
            self.wait_command()
            self.move_to_location(location,x_offset=True)
            self.close_gripper()
            self.wait_command()
        else:
            print(f'Error: {error_msg}')

    def swap_printer_head(self, slot_number, new_printer_head):
        """Handle swapping of printer heads."""
        self.model.printer_head_manager.swap_printer_head(slot_number, new_printer_head, self.model.rack_model)

    def swap_printer_heads_between_slots(self, slot_number_1, slot_number_2):
        """
        Swap printer heads between two slots in the rack.

        Args:
            slot_number_1 (int): The first slot number.
            slot_number_2 (int): The second slot number.
        """
        self.model.rack_model.swap_printer_heads_between_slots(slot_number_1, slot_number_2)

    def print_droplets(self,droplets,handler=None,kwargs=None,manual=False):
        """Print a specified number of droplets."""
        self.machine.print_droplets(droplets,handler=handler,kwargs=kwargs,manual=manual)

    def well_complete_handler(self,well_id=None,stock_id=None,target_droplets=None):
        self.model.well_plate.get_well(well_id).record_stock_print(stock_id,target_droplets)
        print(f'Printing complete for well {well_id}')

    def last_well_complete_handler(self,well_id=None,stock_id=None,target_droplets=None):
        self.model.well_plate.get_well(well_id).record_stock_print(stock_id,target_droplets)
        print('---Printing complete---')

    def print_array(self):
        '''
        Iterates through all wells with an assigned reaction and prints the 
        required number of droplets for the currently loaded printer head.
        '''
        if self.model.rack_model.get_gripper_info() == None:
            print('Cannot print: No printer head is loaded')
            return
        
        current_stock_id = self.model.rack_model.gripper_printer_head.get_stock_id()
        print(f'Current stock:{current_stock_id}')
        starting_coords = self.model.machine_model.get_current_position_dict().copy()
        reaction_wells = self.model.well_plate.get_all_wells_with_reactions()
        
        for i,well in enumerate(reaction_wells):
            target_droplets = well.get_remaining_droplets(current_stock_id)
            if target_droplets == 0:
                print(f'No droplets required for well {well.well_id}')
                continue
            row = well.row_num
            col = well.col
            well_coords = starting_coords.copy()
            well_coords['x'] += col * 300
            well_coords['y'] += row * 300
            self.set_absolute_coordinates(well_coords['x'],well_coords['y'],well_coords['z'])
            print(f'Printing {target_droplets} droplets to well {well.well_id}')
            is_last_iteration = i == len(reaction_wells) - 1
            if not is_last_iteration:
                self.print_droplets(target_droplets, handler=self.well_complete_handler,kwargs={'well_id':well.well_id,'stock_id':current_stock_id,'target_droplets':target_droplets})
            else:
                self.print_droplets(target_droplets, handler=self.last_well_complete_handler,kwargs={'well_id':well.well_id,'stock_id':current_stock_id,'target_droplets':target_droplets})
            
            
        

