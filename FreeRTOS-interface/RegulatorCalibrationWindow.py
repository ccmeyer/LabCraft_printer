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
        self._batch_active = False
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

        batch_group = QtWidgets.QGroupBox("Batch Session")
        batch_layout = QtWidgets.QVBoxLayout(batch_group)
        batch_form = QtWidgets.QFormLayout()
        batch_form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        self.batch_mode_combo = QtWidgets.QComboBox()
        self.batch_mode_combo.addItems(["stream", "droplet"])
        self.batch_mode_combo.currentIndexChanged.connect(self._refresh_batch_candidates)
        self.batch_mode_combo.currentIndexChanged.connect(self._update_batch_enabled)
        batch_form.addRow("Mode", self.batch_mode_combo)

        self.batch_trace_case_combo = QtWidgets.QComboBox()
        for choice in trace_case_choices():
            label = (
                f"{choice['test_id']} - {choice['name']} "
                f"({', '.join(choice['channels'])}, {choice['pulse_count']} pulses @ {choice['frequency_hz']} Hz)"
            )
            self.batch_trace_case_combo.addItem(label, int(choice["test_id"]))
        self.batch_trace_case_combo.currentIndexChanged.connect(self._update_batch_enabled)
        batch_form.addRow("Trace Case", self.batch_trace_case_combo)

        self.batch_repeat_spin = QtWidgets.QSpinBox()
        self.batch_repeat_spin.setRange(1, 5)
        self.batch_repeat_spin.setValue(1)
        self.batch_repeat_spin.valueChanged.connect(self._update_batch_enabled)
        batch_form.addRow("Repeats", self.batch_repeat_spin)

        self.batch_order_combo = QtWidgets.QComboBox()
        self.batch_order_combo.addItems(["alternating", "grouped", "randomized"])
        batch_form.addRow("Order", self.batch_order_combo)

        self.batch_baseline_before_checkbox = QtWidgets.QCheckBox("Baseline before")
        self.batch_baseline_before_checkbox.setChecked(True)
        self.batch_baseline_after_checkbox = QtWidgets.QCheckBox("Baseline after")
        self.batch_baseline_after_checkbox.setChecked(True)
        baseline_row = QtWidgets.QHBoxLayout()
        baseline_row.addWidget(self.batch_baseline_before_checkbox)
        baseline_row.addWidget(self.batch_baseline_after_checkbox)
        baseline_row.addStretch(1)
        baseline_widget = QtWidgets.QWidget()
        baseline_widget.setLayout(baseline_row)
        batch_form.addRow("Baselines", baseline_widget)

        self.batch_baseline_label = QtWidgets.QLabel("")
        self.batch_baseline_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        batch_form.addRow("Active Baseline", self.batch_baseline_label)

        self.batch_calibrated_head_checkbox = QtWidgets.QCheckBox("Calibrated printer head installed")
        self.batch_calibrated_head_checkbox.stateChanged.connect(self._update_batch_enabled)
        batch_form.addRow("", self.batch_calibrated_head_checkbox)
        batch_layout.addLayout(batch_form)

        self.batch_candidate_list = QtWidgets.QListWidget()
        self.batch_candidate_list.setMinimumHeight(100)
        self.batch_candidate_list.itemChanged.connect(self._update_batch_enabled)
        batch_layout.addWidget(self.batch_candidate_list)

        batch_status_row = QtWidgets.QHBoxLayout()
        self.batch_status_label = QtWidgets.QLabel("Batch idle")
        self.batch_path_label = QtWidgets.QLabel("")
        self.batch_path_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        batch_status_row.addWidget(self.batch_status_label)
        batch_status_row.addStretch(1)
        batch_status_row.addWidget(self.batch_path_label)
        batch_layout.addLayout(batch_status_row)

        batch_button_row = QtWidgets.QHBoxLayout()
        batch_button_row.addStretch(1)
        self.batch_start_button = QtWidgets.QPushButton("Start Batch")
        self.batch_start_button.clicked.connect(self._on_batch_start_clicked)
        self.batch_cancel_button = QtWidgets.QPushButton("Cancel Batch")
        self.batch_cancel_button.clicked.connect(self._on_batch_cancel_clicked)
        self.batch_cancel_button.setEnabled(False)
        batch_button_row.addWidget(self.batch_start_button)
        batch_button_row.addWidget(self.batch_cancel_button)
        batch_layout.addLayout(batch_button_row)
        layout.addWidget(batch_group)

    def _connect_controller(self):
        if self.controller is None:
            return
        for signal_name, slot in (
            ("regulator_calibration_stage", self._on_stage),
            ("regulator_calibration_output", self._on_output),
            ("regulator_calibration_finished", self._on_finished),
            ("regulator_calibration_batch_stage", self._on_batch_stage),
            ("regulator_calibration_batch_output", self._on_output),
            ("regulator_calibration_batch_progress", self._on_batch_progress),
            ("regulator_calibration_batch_finished", self._on_batch_finished),
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
        self._refresh_batch_candidates()
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
        self._update_batch_enabled()

    def _batch_mode(self) -> str:
        return str(self.batch_mode_combo.currentText() or "").strip().lower()

    def _batch_trace_case_id(self) -> int:
        data = self.batch_trace_case_combo.currentData()
        return int(data or 0)

    def _batch_candidate_profile_ids(self) -> list[str]:
        ids = []
        for index in range(self.batch_candidate_list.count()):
            item = self.batch_candidate_list.item(index)
            if item.checkState() == QtCore.Qt.Checked:
                ids.append(str(item.data(QtCore.Qt.UserRole) or ""))
        return [item for item in ids if item]

    def _refresh_batch_candidates(self):
        if not hasattr(self, "batch_candidate_list"):
            return
        checked = set(self._batch_candidate_profile_ids())
        mode = self._batch_mode()
        self.batch_candidate_list.blockSignals(True)
        self.batch_candidate_list.clear()
        for profile in self._profiles:
            if str(profile.get("mode") or "") != mode:
                continue
            profile_id = str(profile.get("profile_id") or "")
            item = QtWidgets.QListWidgetItem(profile_id)
            item.setData(QtCore.Qt.UserRole, profile_id)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if profile_id in checked else QtCore.Qt.Unchecked)
            self.batch_candidate_list.addItem(item)
        self.batch_candidate_list.blockSignals(False)
        baseline_id = None
        getter = getattr(self.controller, "get_regulator_calibration_active_profile_id", None)
        if callable(getter):
            baseline_id = getter(mode)
        self.batch_baseline_label.setText(str(baseline_id or f"Active {mode} profile"))
        self._update_batch_enabled()

    @QtCore.Slot()
    def _update_batch_enabled(self):
        if not hasattr(self, "batch_start_button"):
            return
        can_start = (
            not self._busy
            and self._batch_trace_case_id() in TRACE_CASES
            and bool(self._batch_candidate_profile_ids())
            and self.batch_calibrated_head_checkbox.isChecked()
        )
        self.batch_start_button.setEnabled(can_start)
        self.batch_cancel_button.setEnabled(self._busy and self._batch_active)

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

    def _batch_config(self) -> dict[str, Any]:
        return {
            "mode": self._batch_mode(),
            "trace_case_id": self._batch_trace_case_id(),
            "candidate_profile_ids": self._batch_candidate_profile_ids(),
            "repeat_count": self.batch_repeat_spin.value(),
            "order_strategy": str(self.batch_order_combo.currentText() or "alternating"),
            "baseline_before": self.batch_baseline_before_checkbox.isChecked(),
            "baseline_after": self.batch_baseline_after_checkbox.isChecked(),
            "operator": self.operator_edit.text().strip(),
            "printer_head_id": self.head_id_edit.text().strip(),
            "printer_head_type": self.head_type_edit.text().strip(),
            "reagent_id": self.reagent_edit.text().strip(),
            "calibrated_head_confirmed": self.batch_calibrated_head_checkbox.isChecked(),
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
    def _on_batch_start_clicked(self):
        starter = getattr(self.controller, "start_regulator_calibration_batch", None)
        if not callable(starter):
            self._on_output("Regulator calibration batch is not available from this controller.")
            return
        self.log_output.clear()
        self.batch_path_label.setText("")
        self._batch_active = True
        self._set_busy(True)
        self._on_batch_stage("Preparing regulator calibration batch")
        if not starter(self._batch_config()):
            self._batch_active = False
            self._set_busy(False)
            self._on_batch_stage("Failed")

    @QtCore.Slot()
    def _on_cancel_clicked(self):
        cancel = getattr(self.controller, "cancel_regulator_calibration_run", None)
        if callable(cancel):
            cancel()

    @QtCore.Slot()
    def _on_batch_cancel_clicked(self):
        cancel = getattr(self.controller, "cancel_regulator_calibration_batch", None)
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
        if self._batch_active:
            return
        self._set_busy(False)
        self._on_stage("Finished" if ok else "Failed")
        self._on_output(str(message or ""))
        if isinstance(payload, dict):
            run_dir = payload.get("run_dir")
            if run_dir:
                self.output_path_label.setText(str(run_dir))

    @QtCore.Slot(str)
    def _on_batch_stage(self, message: str):
        self.batch_status_label.setText(str(message or ""))

    @QtCore.Slot(int, int, object)
    def _on_batch_progress(self, current: int, total: int, run: object):
        if isinstance(run, dict):
            self.batch_status_label.setText(
                f"Batch run {current}/{total}: {run.get('role')} {run.get('profile_id')}"
            )

    @QtCore.Slot(bool, str, object)
    def _on_batch_finished(self, ok: bool, message: str, payload: object):
        self._batch_active = False
        self._set_busy(False)
        self._on_batch_stage("Finished" if ok else "Failed")
        self._on_output(str(message or ""))
        if isinstance(payload, dict):
            session_dir = payload.get("session_dir")
            if session_dir:
                self.batch_path_label.setText(str(session_dir))
            manifest = payload.get("manifest")
            if isinstance(manifest, dict):
                analysis = manifest.get("analysis") if isinstance(manifest.get("analysis"), dict) else {}
                ranking = analysis.get("candidate_ranking_csv")
                if ranking:
                    self.batch_path_label.setText(str(ranking))

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
            self.batch_mode_combo,
            self.batch_trace_case_combo,
            self.batch_repeat_spin,
            self.batch_order_combo,
            self.batch_baseline_before_checkbox,
            self.batch_baseline_after_checkbox,
            self.batch_calibrated_head_checkbox,
            self.batch_candidate_list,
        ):
            widget.setEnabled(not self._busy)
        self._update_start_enabled()
        self._update_batch_enabled()
