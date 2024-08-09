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
    controller.connect_to_machine()
    view = View(model,controller)

    # Show the main window
    view.show()

    sys.exit(app.exec())
    controller.disconnect_from_machine()

if __name__ == "__main__":
    main()