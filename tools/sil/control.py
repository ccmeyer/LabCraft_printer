"""Launcher-owned controls and observability for an interactive simulator."""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class SimulatorControlDock(QtWidgets.QDockWidget):
    """A persistent, simulation-only control surface attached to MainWindow."""

    TITLE = "SIMULATOR CONTROL — NO HARDWARE"

    def __init__(
        self,
        *,
        parent,
        machine,
        session_id: str,
        session_root: str,
        seed: int,
        speed_multiplier: float,
        connect_callback,
        disconnect_callback,
    ):
        super().__init__(self.TITLE, parent)
        self.setObjectName("simulatorControlDock")
        self.setFeatures(QtWidgets.QDockWidget.NoDockWidgetFeatures)
        self.setAllowedAreas(QtCore.Qt.RightDockWidgetArea)

        self._machine = machine
        self._connect_callback = connect_callback
        self._disconnect_callback = disconnect_callback
        self._connection_pending = False
        self._state_signal_connected = False

        panel = QtWidgets.QWidget(self)
        panel.setObjectName("simulatorControlPanel")
        layout = QtWidgets.QVBoxLayout(panel)

        heading = QtWidgets.QLabel(self.TITLE, panel)
        heading.setObjectName("simulatorControlHeading")
        heading.setWordWrap(True)
        heading.setStyleSheet("font-weight: bold; color: #ffcc66;")
        layout.addWidget(heading)

        form = QtWidgets.QFormLayout()
        self.session_id_label = self._add_value(form, "Session", session_id)
        self.session_root_label = self._add_value(form, "Root", session_root)
        self.session_root_label.setWordWrap(True)
        self.seed_label = self._add_value(form, "Seed", str(seed))
        self.timing_label = self._add_value(
            form,
            "Speed",
            f"{float(speed_multiplier):g}x",
        )
        self.connection_label = self._add_value(form, "Connection", "Disconnected")
        self.motors_label = self._add_value(form, "Motors / home", "Disabled / No")
        self.position_label = self._add_value(form, "Position", "X 0  Y 0  Z 0")
        self.pressure_label = self._add_value(
            form,
            "Pressure",
            "Print 0→0  Refuel 0→0",
        )
        self.regulation_label = self._add_value(
            form,
            "Regulation",
            "Print off / Refuel off",
        )
        self.gripper_label = self._add_value(form, "Gripper", "Closed / inactive")
        self.queue_label = self._add_value(form, "Queue", "0")
        self.time_label = self._add_value(form, "Simulated time", "0 ms")
        layout.addLayout(form)

        buttons = QtWidgets.QHBoxLayout()
        self.connect_button = QtWidgets.QPushButton("Connect Simulator", panel)
        self.connect_button.setObjectName("connectSimulatorButton")
        self.disconnect_button = QtWidgets.QPushButton("Disconnect Simulator", panel)
        self.disconnect_button.setObjectName("disconnectSimulatorButton")
        self.connect_button.clicked.connect(self._connect)
        self.disconnect_button.clicked.connect(self._disconnect)
        buttons.addWidget(self.connect_button)
        buttons.addWidget(self.disconnect_button)
        layout.addLayout(buttons)
        layout.addStretch(1)

        self.setWidget(panel)
        self._machine.state_changed.connect(self._update_state)
        self._state_signal_connected = True
        self._update_state(self._machine.state)

    @staticmethod
    def _add_value(form, name: str, value: str):
        label = QtWidgets.QLabel(str(value))
        label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        form.addRow(f"{name}:", label)
        return label

    @QtCore.Slot()
    def _connect(self):
        self._connection_pending = True
        self._update_buttons(bool(self._machine.state.connected))
        result = self._connect_callback()
        if result is False:
            self._connection_pending = False
            self._update_buttons(bool(self._machine.state.connected))

    @QtCore.Slot()
    def _disconnect(self):
        self._connection_pending = False
        self._disconnect_callback()
        self._update_buttons(bool(self._machine.state.connected))

    @QtCore.Slot(object)
    def _update_state(self, state):
        connected = bool(getattr(state, "connected", False))
        self._connection_pending = False
        self.connection_label.setText("Connected to SIMULATED" if connected else "Disconnected")
        self.motors_label.setText(
            f"{'Enabled' if getattr(state, 'motors_enabled', False) else 'Disabled'} / "
            f"{'Yes' if getattr(state, 'homed', False) else 'No'}"
        )
        self.position_label.setText(
            f"X {getattr(state, 'x', 0)}  "
            f"Y {getattr(state, 'y', 0)}  "
            f"Z {getattr(state, 'z', 0)}"
        )
        self.pressure_label.setText(
            f"Print {getattr(state, 'current_print_pressure_raw', 0)}"
            f"→{getattr(state, 'target_print_pressure_raw', 0)}  "
            f"Refuel {getattr(state, 'current_refuel_pressure_raw', 0)}"
            f"→{getattr(state, 'target_refuel_pressure_raw', 0)}"
        )
        self.regulation_label.setText(
            f"Print {'on' if getattr(state, 'regulating_print_pressure', False) else 'off'} / "
            f"Refuel {'on' if getattr(state, 'regulating_refuel_pressure', False) else 'off'}"
        )
        self.gripper_label.setText(
            f"{'Open' if getattr(state, 'gripper_open', False) else 'Closed'} / "
            f"{'active' if getattr(state, 'gripper_active', False) else 'inactive'}"
        )
        self.queue_label.setText(str(getattr(state, "command_depth", 0)))
        self.time_label.setText(f"{getattr(state, 'simulated_elapsed_ms', 0)} ms")
        self._update_buttons(connected)

    def _update_buttons(self, connected: bool):
        self.connect_button.setEnabled(not connected and not self._connection_pending)
        self.disconnect_button.setEnabled(connected)

    def dispose(self):
        if self._state_signal_connected:
            try:
                self._machine.state_changed.disconnect(self._update_state)
            except (RuntimeError, TypeError):
                pass
            self._state_signal_connected = False

