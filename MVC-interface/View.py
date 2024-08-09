from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QTableWidget, QTableWidgetItem
from PySide6.QtGui import QShortcut, QKeySequence

class ShortcutManager:
    """Manage application shortcuts and their descriptions."""
    def __init__(self, parent):
        self.parent = parent
        self.shortcuts = []

    def add_shortcut(self, key_sequence, description, callback):
        """Add a shortcut to the application and store its description."""
        shortcut = QShortcut(QKeySequence(key_sequence), self.parent, activated=callback)
        self.shortcuts.append((key_sequence, description))
        return shortcut

    def get_shortcuts(self):
        """Return a list of shortcuts and their descriptions."""
        return self.shortcuts

class View(QMainWindow):
    def __init__(self, model,controller):
        super().__init__()
        self.model = model
        self.controller = controller
        self.shortcut_manager = ShortcutManager(self)

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
        self.setup_shortcuts()

    def setup_shortcuts(self):
        """Set up keyboard shortcuts using the shortcut manager."""
        self.shortcut_manager.add_shortcut('Left', 'Move left', self.controller.move_left)
        self.shortcut_manager.add_shortcut('Right', 'Move right', self.controller.move_right)


    def update_table(self):
        """Update the table with the current motor positions."""
        # Update the actual positions
        self.position_table.setItem(0, 0, QTableWidgetItem(str(self.model.machine_model.current_x)))
        self.position_table.setItem(1, 0, QTableWidgetItem(str(self.model.machine_model.current_y)))
        self.position_table.setItem(2, 0, QTableWidgetItem(str(self.model.machine_model.current_z)))
        self.position_table.setItem(3, 0, QTableWidgetItem(str(self.model.machine_model.current_p)))

        # Update the target positions
        self.position_table.setItem(0, 1, QTableWidgetItem(str(self.model.machine_model.target_x)))
        self.position_table.setItem(1, 1, QTableWidgetItem(str(self.model.machine_model.target_y)))
        self.position_table.setItem(2, 1, QTableWidgetItem(str(self.model.machine_model.target_z)))
        self.position_table.setItem(3, 1, QTableWidgetItem(str(self.model.machine_model.target_z)))
