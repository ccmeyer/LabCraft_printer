"""Standalone hardware-free Qt bootstrap dialog and worker adapter."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from MachineDataBootstrap import (
    AuthorizedMachineContext,
    BootstrapError,
    BootstrapState,
    BootstrapSubmission,
    MachineDataBootstrap,
    PublishedActivationSubmission,
)
from MachineDataMigration import (
    CandidateEvidence,
    CandidateSelection,
    CandidateSourceKind,
    classify_candidates,
    load_candidate_evidence,
)


class BootstrapWorker(QtCore.QObject):
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str, str)

    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    @QtCore.Slot()
    def run(self):
        try:
            self.finished.emit(self.operation())
        except Exception as exc:
            self.failed.emit(str(getattr(exc, "code", "bootstrap_failed")), str(exc))


class MachineDataBootstrapDialog(QtWidgets.QDialog):
    """Explicit source, identity, Camera, and activation review UI."""

    def __init__(
        self,
        bootstrap: MachineDataBootstrap,
        *,
        current_checkout_local: str | Path | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.bootstrap = bootstrap
        self.current_checkout_local = (
            Path(current_checkout_local).resolve(strict=False)
            if current_checkout_local is not None
            else None
        )
        self.inspection = bootstrap.inspect()
        self.candidate: CandidateEvidence | None = None
        self._candidate_history: dict[str, CandidateEvidence] = {}
        self.context: AuthorizedMachineContext | None = None
        self._thread = None
        self._worker = None
        self._worker_mode: str | None = None
        self._busy = False
        self.failure_code: str | None = None
        self.failure_message: str | None = None
        self.setWindowTitle("LabCraft Machine Data Verification")
        self.setModal(True)
        self.resize(860, 680)
        self._build_ui()
        self._initialize_state()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        self.state_label = QtWidgets.QLabel()
        self.state_label.setWordWrap(True)
        layout.addWidget(self.state_label)
        self.pages = QtWidgets.QStackedWidget()
        layout.addWidget(self.pages, 1)

        source_page = QtWidgets.QWidget()
        source_layout = QtWidgets.QVBoxLayout(source_page)
        source_layout.addWidget(QtWidgets.QLabel("Choose the preserved machine-data source."))
        row = QtWidgets.QHBoxLayout()
        self.source_path = QtWidgets.QLineEdit()
        self.source_path.setReadOnly(True)
        row.addWidget(self.source_path, 1)
        self.browse_folder_button = QtWidgets.QPushButton("Browse folder")
        self.browse_zip_button = QtWidgets.QPushButton("Browse ZIP")
        row.addWidget(self.browse_folder_button)
        row.addWidget(self.browse_zip_button)
        source_layout.addLayout(row)
        self.source_summary = QtWidgets.QPlainTextEdit()
        self.source_summary.setReadOnly(True)
        source_layout.addWidget(self.source_summary, 1)
        self.inspect_button = QtWidgets.QPushButton("Inspect selected source")
        self.inspect_button.setEnabled(False)
        source_layout.addWidget(self.inspect_button)
        self.pages.addWidget(source_page)

        verify_page = QtWidgets.QWidget()
        verify_layout = QtWidgets.QVBoxLayout(verify_page)
        self.review_summary = QtWidgets.QPlainTextEdit()
        self.review_summary.setReadOnly(True)
        verify_layout.addWidget(self.review_summary, 1)
        form = QtWidgets.QFormLayout()
        self.machine_id = QtWidgets.QLineEdit()
        self.operator = QtWidgets.QLineEdit()
        self.source_reason = QtWidgets.QLineEdit()
        self.camera_x = QtWidgets.QLineEdit()
        self.camera_y = QtWidgets.QLineEdit()
        self.camera_z = QtWidgets.QLineEdit()
        self.service_record = QtWidgets.QLineEdit()
        form.addRow("Machine display ID (type exactly)", self.machine_id)
        form.addRow("Operator", self.operator)
        form.addRow("Source-selection reason", self.source_reason)
        form.addRow("Confirm Camera X", self.camera_x)
        form.addRow("Confirm Camera Y", self.camera_y)
        form.addRow("Confirm Camera Z", self.camera_z)
        form.addRow("Independent service record (when required)", self.service_record)
        verify_layout.addLayout(form)
        self.attest = QtWidgets.QCheckBox(
            "I reviewed every displayed location/plate and confirm this source belongs to this physical printer."
        )
        self.attest.setWordWrap(True) if hasattr(self.attest, "setWordWrap") else None
        verify_layout.addWidget(self.attest)
        verify_buttons = QtWidgets.QHBoxLayout()
        self.back_button = QtWidgets.QPushButton("Back")
        self.activate_button = QtWidgets.QPushButton("Create verified backup and activate")
        verify_buttons.addWidget(self.back_button)
        verify_buttons.addStretch(1)
        verify_buttons.addWidget(self.activate_button)
        verify_layout.addLayout(verify_buttons)
        self.pages.addWidget(verify_page)

        progress_page = QtWidgets.QWidget()
        progress_layout = QtWidgets.QVBoxLayout(progress_page)
        self.progress_label = QtWidgets.QLabel(
            "Writing and reopening verification evidence. No hardware is being constructed."
        )
        self.progress_label.setWordWrap(True)
        progress_layout.addWidget(self.progress_label)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 0)
        progress_layout.addWidget(self.progress)
        progress_layout.addStretch(1)
        self.cancel_work_button = QtWidgets.QPushButton("Cancel at next safe checkpoint")
        progress_layout.addWidget(self.cancel_work_button)
        self.pages.addWidget(progress_page)

        self.browse_folder_button.clicked.connect(self._browse_folder)
        self.browse_zip_button.clicked.connect(self._browse_zip)
        self.inspect_button.clicked.connect(self._inspect_selected)
        self.back_button.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        self.activate_button.clicked.connect(self._activate)
        self.cancel_work_button.clicked.connect(self._request_cancel)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        self.dialog_buttons = buttons
        layout.addWidget(buttons)

    def _initialize_state(self):
        state = self.inspection.state
        self.state_label.setText(f"External machine-data state: {state.value}")
        if state is BootstrapState.READY:
            self.state_label.setText("Verified external machine data is ready.")
            self.activate_button.setText("Open verified machine")
            self.pages.setCurrentIndex(2)
            self.progress_label.setText("Revalidating the active machine-data store.")
            self._start_worker(self.bootstrap.open_ready, mode="open_ready")
            return
        if state in {
            BootstrapState.MIGRATION_RESUME_REQUIRED,
            BootstrapState.ACTIVATION_RESUME_REQUIRED,
        }:
            paths = self.inspection.machine_paths
            if paths is None:
                self._fatal("Resume state has no canonical machine path.")
                return
            try:
                self.candidate = load_candidate_evidence(paths.candidate_evidence_path)
                identity = json.loads(paths.identity_path.read_text(encoding="utf-8"))
                self.machine_id.setText(str(identity.get("machine_id") or ""))
                self.machine_id.setReadOnly(True)
                self._show_candidate(self.candidate, resume=True)
                self.pages.setCurrentIndex(1)
                self.back_button.setEnabled(False)
                self.activate_button.setText("Verify and activate published copy")
            except Exception as exc:
                self._fatal(str(exc))
            return
        if state is BootstrapState.RECOVERY_REQUIRED:
            detail = "\n".join(issue.message for issue in self.inspection.issues)
            self._fatal(
                detail or "External machine data requires support review.",
                code="recovery_required",
            )
            return
        if self.current_checkout_local and self.current_checkout_local.exists():
            self.source_path.setText(str(self.current_checkout_local))
            self.inspect_button.setEnabled(True)

    def _browse_folder(self):
        selected = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select preserved local folder or its parent"
        )
        if selected:
            self.source_path.setText(selected)
            self.inspect_button.setEnabled(True)

    def _browse_zip(self):
        selected, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select preserved machine-data ZIP", filter="ZIP archives (*.zip)"
        )
        if selected:
            self.source_path.setText(selected)
            self.inspect_button.setEnabled(True)

    def _selection(self) -> CandidateSelection:
        path = Path(self.source_path.text()).resolve(strict=False)
        if path.suffix.casefold() == ".zip":
            kind = CandidateSourceKind.OPERATOR_SELECTED_ZIP
        elif (path / "local").is_dir():
            kind = CandidateSourceKind.OPERATOR_SELECTED_WRAPPER
        elif self.current_checkout_local is not None and path == self.current_checkout_local:
            kind = CandidateSourceKind.CURRENT_CHECKOUT_LOCAL
        else:
            kind = CandidateSourceKind.OPERATOR_SELECTED_LOCAL
        return CandidateSelection(kind, path, "operator-confirmed bootstrap source")

    def _inspect_selected(self):
        selection = self._selection()
        self.pages.setCurrentIndex(2)
        self.progress_label.setText(
            "Inspecting and hashing the selected source. No hardware is being constructed."
        )
        self._start_worker(
            lambda: self.bootstrap.inspect_candidate(selection),
            mode="inspect_candidate",
        )

    def _candidate_inspected(self, candidate: CandidateEvidence):
        self._candidate_history[candidate.candidate_id] = candidate
        candidate_text = self._candidate_review_text(candidate)
        self.source_summary.setPlainText(candidate_text)
        if not candidate.is_importable:
            self.pages.setCurrentIndex(0)
            QtWidgets.QMessageBox.critical(
                self, "Source cannot be used", candidate_text
            )
            return
        self.candidate = candidate
        self._show_candidate(candidate, resume=False)
        self.pages.setCurrentIndex(1)

    def _show_candidate(self, candidate: CandidateEvidence, *, resume: bool):
        self._candidate_history[candidate.candidate_id] = candidate
        self.review_summary.setPlainText(self._candidate_review_text(candidate))
        camera = candidate.safety_snapshot.get("locations", {}).get("camera", {})
        self.camera_x.setPlaceholderText(f"Expected: {camera.get('X')}")
        self.camera_y.setPlaceholderText(f"Expected: {camera.get('Y')}")
        self.camera_z.setPlaceholderText(f"Expected: {camera.get('Z')}")
        if candidate.legacy_identity and candidate.identity_status == "assigned":
            self.machine_id.setText(candidate.legacy_identity.machine_id)
            self.machine_id.setReadOnly(True)
        if candidate.preset_like or candidate.camera_preset_match:
            self.service_record.setPlaceholderText("Required: independent service record")
        if resume:
            self.source_path.setText(str(candidate.normalized_source))

    @staticmethod
    def _candidate_text(candidate: CandidateEvidence) -> str:
        lines = [
            f"Source: {candidate.normalized_source}",
            f"Source type: {candidate.source_kind.value}",
            f"Declared VERSION: {candidate.version_text or 'not recorded'}",
            f"Identity status: {candidate.identity_status}",
            f"CalibrationMemory: {candidate.calibration_memory_status}",
            f"Preset cohorts: {', '.join(candidate.preset_matches) or 'none'}",
            f"Camera preset match: {candidate.camera_preset_match}",
            "",
            "Saved locations:",
        ]
        for name, value in sorted(candidate.safety_snapshot.get("locations", {}).items()):
            lines.append(f"  {name}: X={value.get('X')} Y={value.get('Y')} Z={value.get('Z')}")
        lines.extend(("", "Plate calibrations:"))
        plates = candidate.safety_snapshot.get("plates", [])
        if isinstance(plates, dict):
            plate_items = sorted(plates.items())
        else:
            plate_items = sorted(
                (
                    str(plate.get("name") or "unnamed"),
                    plate.get("calibrations") or {},
                )
                for plate in plates
                if isinstance(plate, dict)
            )
        for name, corners in plate_items:
            lines.append(f"  {name}: {json.dumps(corners, sort_keys=True)}")
        if candidate.unclassified_source_paths:
            lines.extend(("", "Unclassified paths:"))
            lines.extend(f"  {path}" for path in candidate.unclassified_source_paths)
        if candidate.issues:
            lines.extend(("", "Inspection findings:"))
            lines.extend(
                f"  [{issue.severity.value}] {issue.code}: {issue.message}"
                for issue in candidate.issues
            )
        return "\n".join(lines)

    def _candidate_review_text(self, candidate: CandidateEvidence) -> str:
        text = self._candidate_text(candidate)
        candidates = tuple(self._candidate_history.values())
        if len(candidates) < 2:
            return text
        comparison = classify_candidates(candidates)
        by_id = {item.candidate_id: item for item in candidates}
        lines = [text, "", "Comparison with other inspected candidates:"]
        for relation in comparison.relations:
            if candidate.candidate_id not in {
                relation.first_candidate_id,
                relation.second_candidate_id,
            }:
                continue
            other_id = (
                relation.second_candidate_id
                if relation.first_candidate_id == candidate.candidate_id
                else relation.first_candidate_id
            )
            other = by_id[other_id]
            lines.append(
                f"  {other.normalized_source}: {relation.classification}"
            )
        return "\n".join(lines)

    def _camera_confirmation(self):
        try:
            return {
                "X": int(self.camera_x.text().strip()),
                "Y": int(self.camera_y.text().strip()),
                "Z": int(self.camera_z.text().strip()),
            }
        except ValueError as exc:
            raise ValueError("Type the displayed Camera X, Y, and Z values exactly.") from exc

    def _activate(self):
        if self.candidate is None:
            self._fatal("No candidate evidence is loaded.")
            return
        try:
            camera = self._camera_confirmation()
            if not self.attest.isChecked():
                raise ValueError("The source/target attestation checkbox is required.")
            operator = self.operator.text().strip()
            reason = self.source_reason.text().strip()
            machine_id = self.machine_id.text().strip()
            if not operator or not reason or not machine_id:
                raise ValueError("Machine ID, operator, and source reason are required.")
            service_record = self.service_record.text().strip() or None
            if self.inspection.machine_paths is not None:
                operation = lambda: self.bootstrap.activate_published(
                    PublishedActivationSubmission(
                        machine_uuid=self.inspection.machine_paths.machine_uuid,
                        operator=operator,
                        source_reason=reason,
                        camera_confirmation=camera,
                        service_record_reference=service_record,
                    )
                )
            else:
                operation = lambda: self.bootstrap.bootstrap_from_candidate(
                    BootstrapSubmission(
                        selection=self._selection(),
                        machine_id=machine_id,
                        operator=operator,
                        source_reason=reason,
                        camera_confirmation=camera,
                        service_record_reference=service_record,
                    )
                )
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Verification incomplete", str(exc))
            return
        self.pages.setCurrentIndex(2)
        self._start_worker(operation, mode="activate")

    def _start_worker(self, operation, *, mode):
        if self._busy:
            return
        self.failure_code = None
        self.failure_message = None
        self._busy = True
        self._worker_mode = str(mode)
        self.dialog_buttons.setEnabled(False)
        thread = QtCore.QThread(self)
        worker = BootstrapWorker(operation)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._worker_finished)
        worker.failed.connect(self._worker_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    @QtCore.Slot(object)
    def _worker_finished(self, context):
        self._busy = False
        mode = self._worker_mode
        self._worker_mode = None
        self.dialog_buttons.setEnabled(True)
        if mode == "inspect_candidate":
            self._candidate_inspected(context)
            return
        self.context = context
        self.accept()

    @QtCore.Slot(str, str)
    def _worker_failed(self, code, message):
        self._busy = False
        mode = self._worker_mode
        self._worker_mode = None
        self.failure_code = str(code)
        self.failure_message = str(message)
        self.dialog_buttons.setEnabled(True)
        if code == "bootstrap_cancelled":
            self.failure_code = None
            self.failure_message = None
            super().reject()
            return
        self.pages.setCurrentIndex(
            0 if mode == "inspect_candidate" else (1 if self.candidate is not None else 0)
        )
        QtWidgets.QMessageBox.critical(
            self, "Machine data bootstrap stopped", f"{code}: {message}"
        )

    def _request_cancel(self):
        if self._busy:
            self.bootstrap.request_cancel()
            self.cancel_work_button.setEnabled(False)
            self.progress_label.setText(
                "Cancellation requested. Waiting for the next durable checkpoint; evidence will be preserved."
            )

    def _fatal(self, message, *, code="recovery_required"):
        self.failure_code = str(code)
        self.failure_message = str(message)
        self.pages.setCurrentIndex(0)
        self.source_summary.setPlainText(str(message))
        self.inspect_button.setEnabled(False)
        self.browse_folder_button.setEnabled(False)
        self.browse_zip_button.setEnabled(False)
        self.state_label.setText("Recovery is required before hardware-capable startup.")

    def reject(self):
        if self._busy:
            self._request_cancel()
            return
        super().reject()

    def closeEvent(self, event):
        if self._busy:
            self._request_cancel()
            event.ignore()
            return
        super().closeEvent(event)


def run_bootstrap_dialog(
    bootstrap: MachineDataBootstrap,
    *,
    current_checkout_local: str | Path | None = None,
    parent=None,
) -> AuthorizedMachineContext | None:
    dialog = MachineDataBootstrapDialog(
        bootstrap,
        current_checkout_local=current_checkout_local,
        parent=parent,
    )
    if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        if dialog.failure_code:
            raise BootstrapError(
                dialog.failure_code,
                dialog.failure_message or "Machine data bootstrap stopped.",
            )
        return None
    return dialog.context


__all__ = [
    "BootstrapWorker",
    "MachineDataBootstrapDialog",
    "run_bootstrap_dialog",
]
