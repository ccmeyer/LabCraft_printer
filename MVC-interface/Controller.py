from PySide6.QtCore import QObject
from serial.tools.list_ports import comports
from Model import Model,PrinterHead,Slot


class Controller(QObject):
    def __init__(self, machine, model):
        super().__init__()
        self.machine = machine
        self.model = model

        # Connect the machine's signals to the controller's handlers
        self.machine.status_updated.connect(self.handle_status_update)
        self.machine.error_occurred.connect(self.handle_error)

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

    def set_relative_coordinates(self, x, y, z,manual=False):
        """Set the relative coordinates for the machine."""
        print(f"Setting relative coordinates: x={x}, y={y}, z={z}")
        self.machine.set_relative_coordinates(x, y, z,manual=manual)

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
    
    def transfer_from_gripper(self, slot):
        """Transfer a reagent from the gripper to a slot."""
        self.model.rack_model.transfer_from_gripper(slot)

    def transfer_to_gripper(self, slot):
        """Transfer a reagent from a slot to the gripper."""
        self.model.rack_model.transfer_to_gripper(slot)

    def save_location(self,name):
        """Save the current location information."""
        self.model.location_model.add_location(name,*self.model.machine_model.get_current_position())

    def print_locations(self):
        """Print the saved locations."""
        print(self.model.location_model.get_all_locations())
