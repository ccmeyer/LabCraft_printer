"""Operator-facing LabCraft updater window."""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtWidgets

from tools import update_and_restart as updater


SUCCESS_STATUSES = {updater.STATUS_UPDATED, updater.STATUS_ALREADY_CURRENT}


class UpdaterWorker(QtCore.QObject):
    progress = QtCore.Signal(object)
    finished = QtCore.Signal(object)

    def __init__(
        self,
        config: updater.UpdaterConfig,
        *,
        command_runner=None,
        waiter=None,
    ) -> None:
        super().__init__()
        self.config = config
        self.command_runner = command_runner
        self.waiter = waiter

    @QtCore.Slot()
    def run(self) -> None:
        worker_config = replace(
            self.config,
            no_relaunch=True,
            relaunch_on_failure=False,
            gui=False,
        )
        kwargs: dict[str, Any] = {"progress_callback": self.progress.emit}
        if self.command_runner is not None:
            kwargs["command_runner"] = self.command_runner
        if self.waiter is not None:
            kwargs["waiter"] = self.waiter
        result = updater.run_update(worker_config, **kwargs)
        self.finished.emit(result)


class UpdaterWindow(QtWidgets.QDialog):
    def __init__(
        self,
        config: updater.UpdaterConfig,
        *,
        command_runner=None,
        launcher=None,
        waiter=None,
        auto_start: bool = True,
        auto_close_on_launch: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.command_runner = command_runner
        self.launcher = launcher or updater.default_launcher
        self.waiter = waiter
        self.auto_close_on_launch = bool(auto_close_on_launch)
        self.exit_code = 0
        self._result: updater.UpdateResult | None = None
        self._worker_running = False
        self._thread: QtCore.QThread | None = None
        self._worker: UpdaterWorker | None = None

        self.setWindowTitle("LabCraft Updater")
        self.resize(560, 380)
        self._build_ui()

        if auto_start:
            QtCore.QTimer.singleShot(0, self.start_update)

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        self.status_label = QtWidgets.QLabel("Preparing update...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

        self.log_path_label = QtWidgets.QLabel("")
        self.log_path_label.setWordWrap(True)
        self.log_path_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.log_path_label.hide()
        layout.addWidget(self.log_path_label)

        self.details_button = QtWidgets.QPushButton("Show Details")
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self._set_details_visible)
        layout.addWidget(self.details_button)

        self.details_text = QtWidgets.QPlainTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.details_text.hide()
        layout.addWidget(self.details_text, stretch=1)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)

        self.reopen_button = QtWidgets.QPushButton("Reopen Current Version")
        self.reopen_button.clicked.connect(self._on_reopen_clicked)
        self.reopen_button.hide()
        button_row.addWidget(self.reopen_button)

        self.retry_launch_button = QtWidgets.QPushButton("Retry Launch")
        self.retry_launch_button.clicked.connect(self._on_retry_launch_clicked)
        self.retry_launch_button.hide()
        button_row.addWidget(self.retry_launch_button)

        self.close_button = QtWidgets.QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        self.close_button.hide()
        button_row.addWidget(self.close_button)

        layout.addLayout(button_row)

    def start_update(self) -> None:
        if self._worker_running:
            return
        self._worker_running = True
        self._set_running_state("Starting LabCraft updater...")
        self._thread = QtCore.QThread(self)
        self._worker = UpdaterWorker(
            self.config,
            command_runner=self.command_runner,
            waiter=self.waiter,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.handle_progress_event)
        self._worker.finished.connect(self.handle_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    @QtCore.Slot(object)
    def handle_progress_event(self, event) -> None:
        message = str(getattr(event, "message", "") or "")
        if message and getattr(event, "kind", "") != "command":
            self.status_label.setText(message)

        details = str(getattr(event, "details", "") or "")
        command_result = getattr(event, "command_result", None)
        if command_result is not None and not details:
            details = updater.format_command_result(command_result)
        if details:
            self._append_details(details)

        log_path = getattr(event, "log_path", None)
        if log_path is not None:
            self._show_log_path(log_path)

    @QtCore.Slot(object)
    def handle_finished(self, result: updater.UpdateResult) -> None:
        self._worker_running = False
        self._result = result
        self.exit_code = int(result.returncode)
        if result.log_path is not None:
            self._show_log_path(result.log_path)

        if result.status in SUCCESS_STATUSES:
            if self.config.no_relaunch:
                self._set_done_state(result.message)
                return
            self.status_label.setText("Starting LabCraft...")
            if not self._try_launch_app(close_on_success=True):
                return
            return

        self._show_failure_state(result)

    def _set_running_state(self, message: str) -> None:
        self.status_label.setText(message)
        self.progress_bar.setRange(0, 0)
        self.reopen_button.hide()
        self.retry_launch_button.hide()
        self.close_button.hide()

    def _set_done_state(self, message: str) -> None:
        self.status_label.setText(message)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.reopen_button.hide()
        self.retry_launch_button.hide()
        self.close_button.show()

    def _show_failure_state(self, result: updater.UpdateResult) -> None:
        self.status_label.setText(result.message)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.reopen_button.show()
        self.retry_launch_button.hide()
        self.close_button.show()
        if result.log_path is not None:
            self._show_log_path(result.log_path)

    def _show_relaunch_failure(self, message: str, command: list[str]) -> None:
        self.status_label.setText(f"LabCraft could not be started: {message}")
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        if self._result is not None and self._result.status in SUCCESS_STATUSES:
            self.exit_code = updater.EXIT_CODES[updater.STATUS_RELAUNCH_FAILED]
            self.retry_launch_button.show()
            self.reopen_button.hide()
        else:
            self.reopen_button.show()
            self.retry_launch_button.hide()
        self.close_button.show()
        self._append_details("Launch command:\n$ " + " ".join(command))
        if self._result is not None and self._result.log_path is not None:
            self._show_log_path(self._result.log_path)

    def _try_launch_app(self, *, close_on_success: bool) -> bool:
        result = self._result
        repo_root = result.repo_root if result and result.repo_root is not None else Path(self.config.repo_root).resolve()
        self._set_running_state("Starting LabCraft...")
        deferred = bool(close_on_success and self.auto_close_on_launch)
        if deferred:
            ok, message, helper_command, command = updater.relaunch_app_after_process_exit(
                self.config,
                repo_root,
                wait_pid=os.getpid(),
                launcher=self.launcher,
            )
            self._append_details("Deferred launch command:\n$ " + " ".join(helper_command))
            self._append_details("App launch command:\n$ " + " ".join(command))
        else:
            ok, message, command = updater.relaunch_app(self.config, repo_root, launcher=self.launcher)
            self._append_details("Launch command:\n$ " + " ".join(command))
        if not ok:
            self._show_relaunch_failure(message, command)
            return False

        self.status_label.setText("LabCraft will reopen." if deferred else "LabCraft started.")
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        if result is not None and result.status in SUCCESS_STATUSES:
            self.exit_code = 0
        if close_on_success and self.auto_close_on_launch:
            QtCore.QTimer.singleShot(0, self.accept)
        return True

    def _show_log_path(self, log_path) -> None:
        self.log_path_label.setText(f"Log: {Path(log_path)}")
        self.log_path_label.show()

    def _append_details(self, text: str) -> None:
        text = str(text).rstrip()
        if not text:
            return
        if self.details_text.toPlainText():
            self.details_text.appendPlainText("")
        self.details_text.appendPlainText(text)

    @QtCore.Slot(bool)
    def _set_details_visible(self, visible: bool) -> None:
        self.details_text.setVisible(bool(visible))
        self.details_button.setText("Hide Details" if visible else "Show Details")

    @QtCore.Slot()
    def _on_reopen_clicked(self) -> None:
        self._try_launch_app(close_on_success=True)

    @QtCore.Slot()
    def _on_retry_launch_clicked(self) -> None:
        self._try_launch_app(close_on_success=True)

    def closeEvent(self, event) -> None:
        if self._worker_running:
            event.ignore()
            return
        super().closeEvent(event)


def run_gui(config: updater.UpdaterConfig) -> int:
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv[:1])

    window = UpdaterWindow(config)
    window.finished.connect(app.quit)
    window.show()
    app.exec()
    return int(window.exit_code)
