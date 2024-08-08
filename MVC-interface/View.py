# View.py

from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QTableWidget, QTableWidgetItem

class View(QMainWindow):
    def __init__(self, model):
        super().__init__()
        self.model = model

        self.setWindowTitle("Machine Status")
        self.init_ui()

        # Connect the model's state_updated signal to the update_table method
        self.model.machine_state_updated.connect(self.update_table)

    def init_ui(self):
        """Initialize the user interface."""
        self.layout = QVBoxLayout()

        # Table to display motor positions
        self.position_table = QTableWidget(4, 2)  # 4 motors, 2 columns (actual, target)
        self.position_table.setHorizontalHeaderLabels(['Actual Position', 'Target Position'])
        self.position_table.setVerticalHeaderLabels(['X Motor', 'Y Motor', 'Z Motor', 'P Motor'])
        self.layout.addWidget(self.position_table)

        container = QWidget()
        container.setLayout(self.layout)
        self.setCentralWidget(container)

    def update_table(self):
        """Update the table with the current motor positions."""
        # Update the actual positions
        self.position_table.setItem(0, 0, QTableWidgetItem(str(self.model.machine_model.x_position)))
        self.position_table.setItem(1, 0, QTableWidgetItem(str(self.model.machine_model.y_position)))
        self.position_table.setItem(2, 0, QTableWidgetItem(str(self.model.machine_model.z_position)))
        self.position_table.setItem(3, 0, QTableWidgetItem(str(self.model.machine_model.p_position)))

        # Update the target positions
        self.position_table.setItem(0, 1, QTableWidgetItem(str(self.model.machine_model.x_target_position)))
        self.position_table.setItem(1, 1, QTableWidgetItem(str(self.model.machine_model.y_target_position)))
        self.position_table.setItem(2, 1, QTableWidgetItem(str(self.model.machine_model.z_target_position)))
        self.position_table.setItem(3, 1, QTableWidgetItem(str(self.model.machine_model.z_target_position)))
