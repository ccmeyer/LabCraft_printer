import sys
from PySide6.QtWidgets import QApplication
from Machine_MVC import Machine
from Model import Model
from Controller import Controller
from View import View

def main():
    app = QApplication(sys.argv)

    # Initialize components
    machine = Machine()
    model = Model()
    controller = Controller(machine, model)
    view = View(model)

    # Show the main window
    view.show()

    # Simulate sending a command and requesting status updates
    machine.send_command("Move X", {"x_steps": 100})
    machine.request_status_update()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()