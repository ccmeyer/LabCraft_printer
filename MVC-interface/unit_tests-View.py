import pytest
import numpy as np

from PySide6.QtWidgets import QApplication
from View import ShortcutManager, MainWindow, MotorPositionWidget, PressurePlotBox
from Model import MachineModel, Model
from Machine_MVC import Machine
from Controller import Controller  

@pytest.fixture
def app(qtbot):
    """Create a Qt application instance for testing."""
    app = QApplication([])
    qtbot.addWidget(app)
    return app

@pytest.fixture
def model():
    """Create a machine model for testing."""
    return Model()

@pytest.fixture
def machine():
    """Create a machine instance for testing."""
    return Machine()

@pytest.fixture
def controller(machine, model):
    """Create a controller instance using the machine and model."""
    return Controller(machine, model)

@pytest.fixture
def main_window(model, controller, qtbot):
    """Create the main window for testing."""
    window = MainWindow(model, controller)
    qtbot.addWidget(window)
    return window

def test_shortcut_manager(qtbot):
    """Test the ShortcutManager functionality."""
    app = QApplication.instance() or QApplication([])
    manager = ShortcutManager(app)

    def dummy_callback():
        pass

    manager.add_shortcut('Ctrl+S', 'Save', dummy_callback)
    assert len(manager.get_shortcuts()) == 1
    assert manager.get_shortcuts()[0] == ('Ctrl+S', 'Save')

def test_motor_position_widget_signal_emission(qtbot, model, controller):
    """Test MotorPositionWidget signal emissions."""
    widget = MotorPositionWidget(model, controller)
    qtbot.addWidget(widget)

    with qtbot.waitSignal(widget.home_requested, timeout=1000):
        widget.request_homing()

    with qtbot.waitSignal(widget.toggle_motor_requested, timeout=1000):
        widget.request_toggle_motors()

def test_motor_position_widget_update_labels(qtbot, model, controller):
    """Test MotorPositionWidget label updates."""
    widget = MotorPositionWidget(model, controller)
    qtbot.addWidget(widget)

    model.machine_model.update_current_position(10, 20, 30)
    model.machine_model.update_target_position(40, 50, 60)
    model.machine_state_updated.emit()

    assert widget.labels['X']['current'].text() == '10'
    assert widget.labels['Y']['current'].text() == '20'
    assert widget.labels['Z']['current'].text() == '30'

    assert widget.labels['X']['target'].text() == '40'
    assert widget.labels['Y']['target'].text() == '50'
    assert widget.labels['Z']['target'].text() == '60'

def test_pressure_plot_box_update_pressure(qtbot, model, controller):
    """Test PressurePlotBox updates pressure."""
    widget = PressurePlotBox(model, controller)
    qtbot.addWidget(widget)

    # Simulate pressure update
    pressure_values = np.random.rand(100) * 10  # Random pressure values
    model.machine_model.pressure_updated.emit(pressure_values)

    # Check if the labels and plot updated correctly
    assert widget.current_pressure_value.text() == f"{pressure_values[-1]:.3f}"
    assert widget.target_pressure_value.text() == f"{model.machine_model.target_pressure:.3f}"

def test_pressure_plot_box_regulation_button(qtbot, model, controller):
    """Test PressurePlotBox regulation button state."""
    widget = PressurePlotBox(model, controller)
    qtbot.addWidget(widget)

    model.machine_model.regulating_pressure = True
    model.machine_model.regulation_state_changed.emit(True)
    assert widget.pressure_regulation_button.text() == "Deregulate Pressure"

    model.machine_model.regulating_pressure = False
    model.machine_model.regulation_state_changed.emit(False)
    assert widget.pressure_regulation_button.text() == "Regulate Pressure"