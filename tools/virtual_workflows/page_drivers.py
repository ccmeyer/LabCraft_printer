"""Small Qt page drivers shared by interactive SIL lifecycle tests."""

from __future__ import annotations

import time
from typing import Any, Callable

from PySide6 import QtCore, QtTest, QtWidgets


class CalibrationDialogDriver:
    """Bounded QTest mechanics for the calibration result presentation dialog."""

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
        table = self.dialog.findChild(QtWidgets.QTableView, "characterizationSummaryTable")
        if banner is None or table is None:
            raise RuntimeError("synthetic calibration presentation controls are missing")
        return {
            "window_title": self.dialog.windowTitle(),
            "banner_text": banner.text(),
            "banner_visible": banner.isVisible(),
            "row_count": table.model().rowCount(),
            "source_filter": self.dialog.summary_source_combo.currentData(),
        }

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

    def apply_selected(self, *, expected_title: str = "Applied") -> None:
        state: dict[str, Any] = {"handled": False, "error": None}

        def handle_modal():
            active = self.app.activeModalWidget()
            if not isinstance(active, QtWidgets.QMessageBox):
                state["error"] = RuntimeError(
                    f"unexpected Apply modal: {type(active).__name__ if active else None}"
                )
                if isinstance(active, QtWidgets.QDialog):
                    active.reject()
                return
            if active.windowTitle() != expected_title:
                state["error"] = RuntimeError(
                    f"unexpected Apply dialog title: {active.windowTitle()!r}"
                )
                active.reject()
                return
            state["handled"] = True
            active.accept()

        QtCore.QTimer.singleShot(0, handle_modal)
        QtTest.QTest.mouseClick(
            self.dialog.bridge_apply_btn,
            QtCore.Qt.MouseButton.LeftButton,
        )
        if state["error"] is not None:
            raise state["error"]
        if not state["handled"]:
            raise RuntimeError("expected calibration Apply completion dialog did not open")

    def close(self) -> None:
        self.dialog.close()
        self.wait_until(lambda: not self.dialog.isVisible(), "calibration dialog close")


__all__ = ["CalibrationDialogDriver"]
