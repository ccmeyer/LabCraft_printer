from PySide6.QtCore import QObject

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

    def connect_to_machine(self):
        """Connect to the machine."""
        self.machine.connect_board()

    def disconnect_from_machine(self):
        """Disconnect from the machine."""
        self.machine.disconnect_board()

    def set_relative_coordinates(self, x, y, z,manual=False):
        """Set the relative coordinates for the machine."""
        print(f"Setting relative coordinates: x={x}, y={y}, z={z}")
        self.machine.set_relative_coordinates(x, y, z,manual=manual)

    def set_relative_pressure(self, pressure):
        """Set the relative pressure for the machine."""
        print(f"Setting relative pressure: {pressure}")
        self.machine.set_relative_pressure(pressure)

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