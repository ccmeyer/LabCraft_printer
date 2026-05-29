from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtWidgets

from RegulatorCalibrationRunner import TRACE_CASES, trace_case_choices


class RegulatorCalibrationWindow(QtWidgets.QDialog):
    """Minimal regulator optimization workflow for fixed firmware trace cases."""

    def __init__(self, parent=None, model=None, controller=None):
        super().__init__(parent)
        self.model = model if model is not None else getattr(parent, "model", None)
        self.controller = controller
        self._busy = False
        self._profiles: list[dict[str, Any]] = []

        self.setWindowTitle("Regulator Calibration")
        self.resize(860, 620)
        self._build_ui()
        self._connect_controller()
        self.refresh_profiles()
        self._update_trace_summary()
        self._update_start_enabled()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        form_group = QtWidgets.QGroupBox("Run Setup")
        form = QtWidgets.QFormLayout(form_group)
        form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        self.profile_combo = QtWidgets.QComboBox()
        self.profile_combo.currentIndexChanged.connect(self._update_start_enabled)
        self.profile_combo.currentIndexChanged.connect(self._update_profile_summary)
        form.addRow("Candidate Profile", self.profile_combo)

        self.trace_case_combo = QtWidgets.QComboBox()
        for choice in trace_case_choices():
            label = (
                f"{choice['test_id']} - {choice['name']} "
                f"({', '.join(choice['channels'])}, {choice['pulse_count']} pulses @ {choice['frequency_hz']} Hz)"
            )
            self.trace_case_combo.addItem(label, int(choice["test_id"]))
        self.trace_case_combo.currentIndexChanged.connect(self._update_trace_summary)
        form.addRow("Trace Case", self.trace_case_combo)

        self.operator_edit = QtWidgets.QLineEdit()
        form.addRow("Operator", self.operator_edit)

        self.head_id_edit = QtWidgets.QLineEdit()
        form.addRow("Printer Head ID", self.head_id_edit)

        self.head_type_edit = QtWidgets.QLineEdit()
        form.addRow("Printer Head Type", self.head_type_edit)

        self.reagent_edit = QtWidgets.QLineEdit()
        form.addRow("Reagent ID", self.reagent_edit)

        self.calibrated_head_checkbox = QtWidgets.QCheckBox("Calibrated printer head installed")
        self.calibrated_head_checkbox.stateChanged.connect(self._update_start_enabled)
        form.addRow("", self.calibrated_head_checkbox)

        layout.addWidget(form_group)

        summary_group = QtWidgets.QGroupBox("Fixed Trace Recipe")
        summary_layout = QtWidgets.QVBoxLayout(summary_group)
        self.trace_summary = QtWidgets.QLabel("")
        self.trace_summary.setWordWrap(True)
        self.profile_summary = QtWidgets.QLabel("")
        self.profile_summary.setWordWrap(True)
        summary_layout.addWidget(self.trace_summary)
        summary_layout.addWidget(self.profile_summary)
        layout.addWidget(summary_group)

        status_row = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("Idle")
        self.output_path_label = QtWidgets.QLabel("")
        self.output_path_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        status_row.addWidget(self.output_path_label)
        layout.addLayout(status_row)

        self.log_output = QtWidgets.QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(180)
        layout.addWidget(self.log_output, 1)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        self.refresh_button = QtWidgets.QPushButton("Refresh Profiles")
        self.refresh_button.clicked.connect(self.refresh_profiles)
        self.start_button = QtWidgets.QPushButton("Start")
        self.start_button.clicked.connect(self._on_start_clicked)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        self.cancel_button.setEnabled(False)
        self.close_button = QtWidgets.QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_row.addWidget(self.refresh_button)
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

    def _connect_controller(self):
        if self.controller is None:
            return
        for signal_name, slot in (
            ("regulator_calibration_stage", self._on_stage),
            ("regulator_calibration_output", self._on_output),
            ("regulator_calibration_finished", self._on_finished),
        ):
            signal = getattr(self.controller, signal_name, None)
            connect = getattr(signal, "connect", None)
            if callable(connect):
                connect(slot)

    def refresh_profiles(self):
        profiles = []
        getter = getattr(self.controller, "list_regulator_calibration_profiles", None)
        if callable(getter):
            profiles = list(getter())
        else:
            store = getattr(getattr(self.model, "regulator_profile_store", None), "list_profiles", None)
            if callable(store):
                profiles = list(store())

        self._profiles = sorted(
            [profile for profile in profiles if isinstance(profile, dict)],
            key=lambda item: str(item.get("profile_id") or ""),
        )
        current_profile_id = self._current_profile_id()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for profile in self._profiles:
            profile_id = str(profile.get("profile_id") or "")
            mode = str(profile.get("mode") or "")
            self.profile_combo.addItem(f"{profile_id} ({mode})", profile_id)
        self.profile_combo.blockSignals(False)
        if current_profile_id:
            index = self.profile_combo.findData(current_profile_id)
            if index >= 0:
                self.profile_combo.setCurrentIndex(index)
        self._update_profile_summary()
        self._update_start_enabled()

    def _current_profile_id(self) -> str:
        data = self.profile_combo.currentData()
        return str(data or "").strip()

    def _current_profile(self) -> dict[str, Any] | None:
        profile_id = self._current_profile_id()
        for profile in self._profiles:
            if str(profile.get("profile_id") or "") == profile_id:
                return profile
        return None

    def _current_trace_case_id(self) -> int:
        data = self.trace_case_combo.currentData()
        return int(data or 0)

    @QtCore.Slot()
    def _update_start_enabled(self):
        can_start = (
            not self._busy
            and bool(self._current_profile_id())
            and self._current_trace_case_id() in TRACE_CASES
            and self.calibrated_head_checkbox.isChecked()
        )
        self.start_button.setEnabled(can_start)
        self.refresh_button.setEnabled(not self._busy)
        self.cancel_button.setEnabled(self._busy)

    @QtCore.Slot()
    def _update_trace_summary(self):
        case = TRACE_CASES.get(self._current_trace_case_id())
        if case is None:
            self.trace_summary.setText("")
        else:
            parts = [
                f"Case {case.test_id}: {case.name}",
                f"Channels: {', '.join(case.channels)}",
                f"Pulses: {case.pulse_count} @ {case.frequency_hz} Hz",
            ]
            if case.print_pressure_psi is not None:
                parts.append(f"Print: {case.print_pressure_psi:g} psi, {case.print_pulse_width_us} us")
            if case.refuel_pressure_psi is not None:
                parts.append(f"Refuel: {case.refuel_pressure_psi:g} psi, {case.refuel_pulse_width_us} us")
            self.trace_summary.setText(" | ".join(parts))
        self._update_start_enabled()

    @QtCore.Slot()
    def _update_profile_summary(self):
        profile = self._current_profile()
        if not profile:
            self.profile_summary.setText("")
            return
        source = profile.get("source") if isinstance(profile.get("source"), dict) else {}
        description = str(profile.get("description") or "")
        source_kind = str(source.get("kind") or "")
        self.profile_summary.setText(
            f"Profile mode: {profile.get('mode')} | Source: {source_kind} | {description}"
        )

    def _run_config(self) -> dict[str, Any]:
        profile = self._current_profile() or {}
        return {
            "profile_id": self._current_profile_id(),
            "mode": str(profile.get("mode") or ""),
            "trace_case_id": self._current_trace_case_id(),
            "operator": self.operator_edit.text().strip(),
            "printer_head_id": self.head_id_edit.text().strip(),
            "printer_head_type": self.head_type_edit.text().strip(),
            "reagent_id": self.reagent_edit.text().strip(),
            "calibrated_head_confirmed": self.calibrated_head_checkbox.isChecked(),
        }

    @QtCore.Slot()
    def _on_start_clicked(self):
        starter = getattr(self.controller, "start_regulator_calibration_run", None)
        if not callable(starter):
            self._on_output("Regulator calibration is not available from this controller.")
            return
        self.log_output.clear()
        self.output_path_label.setText("")
        self._set_busy(True)
        self._on_stage("Preparing regulator calibration")
        if not starter(self._run_config()):
            self._set_busy(False)
            self._on_stage("Failed")

    @QtCore.Slot()
    def _on_cancel_clicked(self):
        cancel = getattr(self.controller, "cancel_regulator_calibration_run", None)
        if callable(cancel):
            cancel()

    @QtCore.Slot(str)
    def _on_stage(self, message: str):
        self.status_label.setText(str(message or ""))

    @QtCore.Slot(str)
    def _on_output(self, message: str):
        text = str(message or "")
        if text:
            self.log_output.appendPlainText(text)

    @QtCore.Slot(bool, str, object)
    def _on_finished(self, ok: bool, message: str, payload: object):
        self._set_busy(False)
        self._on_stage("Finished" if ok else "Failed")
        self._on_output(str(message or ""))
        if isinstance(payload, dict):
            run_dir = payload.get("run_dir")
            if run_dir:
                self.output_path_label.setText(str(run_dir))

    def _set_busy(self, busy: bool):
        self._busy = bool(busy)
        for widget in (
            self.profile_combo,
            self.trace_case_combo,
            self.operator_edit,
            self.head_id_edit,
            self.head_type_edit,
            self.reagent_edit,
            self.calibrated_head_checkbox,
        ):
            widget.setEnabled(not self._busy)
        self._update_start_enabled()
