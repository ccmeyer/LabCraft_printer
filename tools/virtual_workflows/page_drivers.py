"""Small Qt page drivers shared by interactive SIL lifecycle tests."""

from __future__ import annotations

import time
from typing import Any, Callable

from PySide6 import QtCore, QtTest, QtWidgets


class CalibrationDialogDriver:
    """Bounded QTest mechanics for the normal simulation calibration dialog."""

    def __init__(self, app, dialog, *, timeout_seconds: float = 10.0):
        self.app = app
        self.dialog = dialog
        self.timeout_seconds = float(timeout_seconds)

    def wait_until(self, predicate: Callable[[], bool], description: str) -> None:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            QtTest.QTest.qWait(10)
        raise RuntimeError(f"timed out waiting for {description}")

    def inspect_presentation(self) -> dict[str, Any]:
        banner = self.dialog.findChild(QtWidgets.QLabel, "syntheticCalibrationBanner")
        mode_label = self.dialog.findChild(
            QtWidgets.QLabel, "syntheticCalibrationModeLabel"
        )
        table = self.dialog.findChild(QtWidgets.QTableView, "characterizationSummaryTable")
        if banner is None or mode_label is None or table is None:
            raise RuntimeError("synthetic calibration presentation controls are missing")
        return {
            "window_title": self.dialog.windowTitle(),
            "banner_text": banner.text(),
            "banner_visible": banner.isVisible(),
            "mode_text": mode_label.text(),
            "mode_visible": mode_label.isVisible(),
            "row_count": table.model().rowCount(),
            "source_filter": self.dialog.summary_source_combo.currentData(),
        }

    def generate_from_tab(self, target_mode: str) -> dict[str, Any]:
        """Use the real tab and Calibrate All control to generate one result."""

        target_mode = str(target_mode or "").strip().lower()
        if target_mode == "droplet":
            tab = self.dialog.droplet_tab
            button = self.dialog.calibrate_all_button
        elif target_mode == "stream":
            tab = self.dialog.stream_tab
            button = self.dialog.calibrate_all_stream_button
        else:
            raise ValueError("target_mode must be droplet or stream")
        self.dialog.calibration_tabs.setCurrentWidget(tab)
        self.app.processEvents()
        if not button.isEnabled():
            raise RuntimeError(
                f"synthetic {target_mode} Calibrate All is unavailable: {button.toolTip()}"
            )
        QtTest.QTest.mouseClick(button, QtCore.Qt.MouseButton.LeftButton)

        generated: dict[str, Any] = {}

        def _generated_result_visible():
            manager = getattr(self.dialog.model, "calibration_manager", None)
            stored = getattr(manager, "_transient_characterization_candidate", None)
            candidate = stored.get("candidate") if isinstance(stored, dict) else None
            expected = str(getattr(candidate, "result_fingerprint", "") or "")
            if not expected:
                return False
            for row in range(self.dialog.summary_table_model.rowCount()):
                raw = self.dialog.summary_table_model.raw_row_at(row) or {}
                fingerprint = str(raw.get("synthetic_result_fingerprint") or "")
                if fingerprint == expected:
                    generated.update(raw)
                    return True
            return False

        self.wait_until(
            _generated_result_visible,
            f"synthetic {target_mode} result generation",
        )
        return dict(generated)

    def select_result(self, result_fingerprint: str) -> dict[str, Any]:
        table = self.dialog.summary_table
        proxy = self.dialog.summary_table_proxy_model
        source = self.dialog.summary_table_model
        match = None
        for proxy_row in range(proxy.rowCount()):
            source_index = proxy.mapToSource(proxy.index(proxy_row, 0))
            raw = source.raw_row_at(source_index.row()) or {}
            if raw.get("synthetic_result_fingerprint") == str(result_fingerprint):
                match = (proxy_row, raw)
                break
        if match is None:
            raise RuntimeError(f"synthetic result is not visible: {result_fingerprint}")
        proxy_row, raw = match
        target = proxy.index(proxy_row, 1)
        rect = table.visualRect(target)
        QtTest.QTest.mouseClick(
            table.viewport(),
            QtCore.Qt.MouseButton.LeftButton,
            pos=rect.center(),
        )
        self.wait_until(
            lambda: bool(self.dialog._selected_summary_row()[1]),
            "synthetic calibration row selection",
        )
        return dict(raw)

    def inspect_preview(self) -> dict[str, Any]:
        payload = dict(getattr(self.dialog, "_bridge_preview_payload", None) or {})
        return {
            "payload": payload,
            "status": self.dialog.bridge_status_label.text(),
            "apply_enabled": self.dialog.bridge_apply_btn.isEnabled(),
            "apply_text": self.dialog.bridge_apply_btn.text(),
            "preview_rows": self.dialog.bridge_table.rowCount(),
        }

    def apply_selected(
        self,
        *,
        expected_title: str | None = "Applied",
        mode_switch_choice: str | None = None,
        manual_refuel_choice: str | None = None,
    ) -> list[str]:
        steps: list[tuple[str, Any]] = []
        if mode_switch_choice is not None:
            choice = str(mode_switch_choice).strip().lower()
            if choice not in {"yes", "no"}:
                raise ValueError("mode_switch_choice must be yes, no, or None")
            steps.append(
                (
                    "Apply calibration as mode switch?",
                    QtWidgets.QMessageBox.Yes
                    if choice == "yes"
                    else QtWidgets.QMessageBox.No,
                )
            )
        if manual_refuel_choice is not None:
            choice = str(manual_refuel_choice).strip().lower()
            if choice not in {"yes", "no"}:
                raise ValueError("manual_refuel_choice must be yes, no, or None")
            steps.append(
                (
                    "Manual Refuel Check Required",
                    QtWidgets.QMessageBox.Yes
                    if choice == "yes"
                    else QtWidgets.QMessageBox.No,
                )
            )
        elif expected_title is not None:
            steps.append((str(expected_title), None))

        state: dict[str, Any] = {"handled": [], "error": None}

        def handle_modal():
            if not steps:
                return
            active = self.app.activeModalWidget()
            if not isinstance(active, QtWidgets.QMessageBox):
                state["error"] = RuntimeError(
                    f"unexpected Apply modal: {type(active).__name__ if active else None}"
                )
                if isinstance(active, QtWidgets.QDialog):
                    active.reject()
                return
            expected_step_title, standard_button = steps.pop(0)
            if active.windowTitle() != expected_step_title:
                state["error"] = RuntimeError(
                    f"unexpected Apply dialog title: {active.windowTitle()!r}"
                )
                active.reject()
                return
            state["handled"].append(active.windowTitle())
            if standard_button is None:
                active.accept()
            else:
                button = active.button(standard_button)
                if button is None:
                    state["error"] = RuntimeError(
                        f"expected button is missing from {active.windowTitle()!r}"
                    )
                    active.reject()
                    return
                QtTest.QTest.mouseClick(
                    button,
                    QtCore.Qt.MouseButton.LeftButton,
                )
            if steps:
                QtCore.QTimer.singleShot(0, handle_modal)

        QtCore.QTimer.singleShot(0, handle_modal)
        QtTest.QTest.mouseClick(
            self.dialog.bridge_apply_btn,
            QtCore.Qt.MouseButton.LeftButton,
        )
        if state["error"] is not None:
            raise state["error"]
        if steps:
            raise RuntimeError("expected calibration Apply dialog sequence did not complete")
        return list(state["handled"])

    def close(self) -> None:
        self.dialog.close()
        self.wait_until(lambda: not self.dialog.isVisible(), "calibration dialog close")


__all__ = ["CalibrationDialogDriver"]
