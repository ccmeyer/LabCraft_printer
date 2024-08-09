from PySide6.QtCore import QObject

class Controller(QObject):
    def __init__(self, machine, machine_model):
        super().__init__()
        self.machine = machine
        self.machine_model = machine_model

        # Connect the machine's signals to the controller's handlers
        self.machine.status_updated.connect(self.handle_status_update)
        self.machine.error_occurred.connect(self.handle_error)

    def handle_status_update(self, status_dict):
        """Handle the status update and update the machine model."""
        self.machine_model.update_state(status_dict)

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

    def move_left(self):
        """Move the machine to the left."""
        self.machine.move_left(manual=True)

    def move_right(self):
        """Move the machine to the right."""
        self.machine.move_right(manual=True)