"""Launcher-owned diagnostics for an interactive simulator."""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class SimulatorControlDock(QtWidgets.QDockWidget):
    """Persistent simulation identity and evidence surface with no workflow controls."""

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
        show_inspector_callback=None,
        export_snapshot_callback=None,
    ):
        super().__init__(self.TITLE, parent)
        self.setObjectName("simulatorControlDock")
        self.setFeatures(QtWidgets.QDockWidget.NoDockWidgetFeatures)
        self.setAllowedAreas(QtCore.Qt.RightDockWidgetArea)

        self._machine = machine
        self._show_inspector_callback = show_inspector_callback
        self._export_snapshot_callback = export_snapshot_callback
        self._state_signal_connected = False

        panel = QtWidgets.QWidget(self)
        panel.setObjectName("simulatorControlPanel")
        layout = QtWidgets.QVBoxLayout(panel)

        heading = QtWidgets.QLabel(self.TITLE, panel)
        heading.setObjectName("simulatorControlHeading")
        heading.setWordWrap(True)
        heading.setStyleSheet("font-weight: bold; color: #ffcc66;")
        layout.addWidget(heading)

        guidance = QtWidgets.QLabel(
            "Use the application's normal Connect, Calibrate Printer Head, and "
            "Manual Refuel Check controls. This dock contains diagnostics only.",
            panel,
        )
        guidance.setObjectName("simulatorControlGuidance")
        guidance.setWordWrap(True)
        layout.addWidget(guidance)

        form = QtWidgets.QFormLayout()
        self.session_id_label = self._add_value(form, "Session", session_id)
        self.session_root_label = self._add_value(form, "Root", session_root)
        self.session_root_label.setWordWrap(True)
        self.seed_label = self._add_value(form, "Seed", str(seed))
        self.timing_label = self._add_value(form, "Speed", f"{float(speed_multiplier):g}x")
        self.connection_label = self._add_value(form, "Connection", "Disconnected")
        self.motors_label = self._add_value(form, "Motors / home", "Disabled / No")
        self.position_label = self._add_value(form, "Position", "X 0  Y 0  Z 0")
        self.pressure_label = self._add_value(form, "Pressure", "Print 0→0  Refuel 0→0")
        self.regulation_label = self._add_value(form, "Regulation", "Print off / Refuel off")
        self.gripper_label = self._add_value(form, "Gripper", "Closed / inactive")
        self.queue_label = self._add_value(form, "Queue", "0")
        self.time_label = self._add_value(form, "Simulated time", "0 ms")
        layout.addLayout(form)

        calibration_group = QtWidgets.QGroupBox("Synthetic calibration diagnostics", panel)
        calibration_layout = QtWidgets.QVBoxLayout(calibration_group)
        self.calibration_status_label = QtWidgets.QLabel(
            "Simulation calibration binding is initializing.", calibration_group
        )
        self.calibration_status_label.setObjectName("syntheticCalibrationStatusLabel")
        self.calibration_status_label.setWordWrap(True)
        self.calibration_status_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        calibration_layout.addWidget(self.calibration_status_label)
        layout.addWidget(calibration_group)

        refuel_group = QtWidgets.QGroupBox("Manual-refuel diagnostics", panel)
        refuel_layout = QtWidgets.QVBoxLayout(refuel_group)
        self.refuel_status_label = QtWidgets.QLabel(
            "Simulation manual-refuel binding is initializing.", refuel_group
        )
        self.refuel_status_label.setObjectName("simulatedManualRefuelStatusLabel")
        self.refuel_status_label.setWordWrap(True)
        self.refuel_status_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        refuel_layout.addWidget(self.refuel_status_label)
        layout.addWidget(refuel_group)

        evidence_buttons = QtWidgets.QHBoxLayout()
        self.show_inspector_button = QtWidgets.QPushButton("Show State Inspector", panel)
        self.show_inspector_button.setObjectName("showSilStateInspectorButton")
        self.export_snapshot_button = QtWidgets.QPushButton("Export State Snapshot", panel)
        self.export_snapshot_button.setObjectName("exportSilStateSnapshotButton")
        self.show_inspector_button.clicked.connect(self._show_inspector)
        self.export_snapshot_button.clicked.connect(self._export_snapshot)
        self.show_inspector_button.setEnabled(callable(self._show_inspector_callback))
        self.export_snapshot_button.setEnabled(callable(self._export_snapshot_callback))
        evidence_buttons.addWidget(self.show_inspector_button)
        evidence_buttons.addWidget(self.export_snapshot_button)
        layout.addLayout(evidence_buttons)
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
    def _show_inspector(self):
        if callable(self._show_inspector_callback):
            self._show_inspector_callback()

    @QtCore.Slot()
    def _export_snapshot(self):
        if callable(self._export_snapshot_callback):
            self._export_snapshot_callback()

    @QtCore.Slot(str)
    def set_calibration_status(self, status: str):
        self.calibration_status_label.setText(str(status))

    @QtCore.Slot(str)
    def set_refuel_status(self, status: str):
        self.refuel_status_label.setText(str(status))

    @QtCore.Slot(object)
    def _update_state(self, state):
        connected = bool(getattr(state, "connected", False))
        self.connection_label.setText("Connected to SIMULATED" if connected else "Disconnected")
        self.motors_label.setText(
            f"{'Enabled' if getattr(state, 'motors_enabled', False) else 'Disabled'} / "
            f"{'Yes' if getattr(state, 'homed', False) else 'No'}"
        )
        self.position_label.setText(
            f"X {getattr(state, 'x', 0)}  Y {getattr(state, 'y', 0)}  Z {getattr(state, 'z', 0)}"
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

    def dispose(self):
        if self._state_signal_connected:
            try:
                self._machine.state_changed.disconnect(self._update_state)
            except (RuntimeError, TypeError):
                pass
            self._state_signal_connected = False
