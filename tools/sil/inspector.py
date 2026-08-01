"""Read-only visible projection of StateRecorder evidence."""

from __future__ import annotations

import json
from typing import Any, Callable

from PySide6 import QtCore, QtWidgets


class StateInspectorDock(QtWidgets.QDockWidget):
    """Display recorder-owned copies without access to application objects."""

    TITLE = "SIL STATE INSPECTOR - READ ONLY"

    def __init__(
        self,
        *,
        parent,
        recorder,
        export_snapshot_callback: Callable[[], Any],
    ) -> None:
        super().__init__(self.TITLE, parent)
        self.setObjectName("silStateInspectorDock")
        self.setAllowedAreas(
            QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea
        )
        self._recorder = recorder
        self._export_snapshot_callback = export_snapshot_callback
        self._subscribed = False

        panel = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(panel)

        heading = QtWidgets.QLabel(self.TITLE, panel)
        heading.setObjectName("silStateInspectorHeading")
        heading.setStyleSheet("font-weight: bold; color: #ffcc66;")
        layout.addWidget(heading)

        form = QtWidgets.QFormLayout()
        self.health_label = self._add_value(form, "Recorder", "Starting")
        self.schema_label = self._add_value(form, "Schema", "v1")
        self.sequence_label = self._add_value(form, "Sequence", "0")
        self.event_label = self._add_value(form, "Last event", "None")
        self.correlation_label = self._add_value(form, "Correlation", "None")
        self.retention_label = self._add_value(form, "Memory", "0 / 0")
        self.reconciliation_label = self._add_value(
            form, "Reconciliation", "Unavailable"
        )
        layout.addLayout(form)

        self.snapshot_text = QtWidgets.QPlainTextEdit(panel)
        self.snapshot_text.setObjectName("silStateSnapshotText")
        self.snapshot_text.setReadOnly(True)
        self.snapshot_text.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        layout.addWidget(self.snapshot_text, 1)

        self.export_button = QtWidgets.QPushButton("Export State Snapshot", panel)
        self.export_button.setObjectName("exportSilStateSnapshotButton")
        self.export_button.clicked.connect(self._export_snapshot)
        layout.addWidget(self.export_button)

        self.setWidget(panel)
        self._recorder.subscribe(self._on_event)
        self._subscribed = True
        self.refresh()

    @staticmethod
    def _add_value(form, name: str, value: str):
        label = QtWidgets.QLabel(str(value))
        label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        label.setWordWrap(True)
        form.addRow(f"{name}:", label)
        return label

    @QtCore.Slot()
    def _export_snapshot(self) -> None:
        try:
            self._export_snapshot_callback()
        finally:
            self.refresh()

    def _on_event(self, event: dict[str, Any]) -> None:
        self.sequence_label.setText(str(event.get("event_sequence", 0)))
        self.event_label.setText(
            f"{event.get('source_layer', '?')} / {event.get('event_kind', '?')}"
        )
        correlation = event.get("correlation") or {}
        rendered = ", ".join(
            f"{key}={value}" for key, value in sorted(correlation.items()) if value
        )
        self.correlation_label.setText(rendered or "None")
        projection = ((event.get("payload") or {}).get("projection"))
        if isinstance(projection, dict):
            self._render_projection(projection)
        self._render_health()

    def _render_projection(self, projection: dict[str, Any]) -> None:
        reconciliation = projection.get("reconciliation") or {}
        status = str(reconciliation.get("status") or "unavailable")
        mismatches = len(reconciliation.get("mismatches") or [])
        self.reconciliation_label.setText(
            status if not mismatches else f"{status} ({mismatches} mismatches)"
        )
        self.snapshot_text.setPlainText(
            json.dumps(projection, indent=2, sort_keys=True)
        )

    def _render_health(self) -> None:
        health = self._recorder.health_snapshot()
        self.health_label.setText(str(health.get("status") or "unknown"))
        self.schema_label.setText(f"v{health.get('schema_version', '?')}")
        self.sequence_label.setText(str(health.get("last_event_sequence", 0)))
        self.retention_label.setText(
            f"{health.get('retained_memory_count', 0)} / "
            f"{health.get('memory_limit', 0)}; "
            f"evicted {health.get('evicted_memory_count', 0)}"
        )
        self.export_button.setEnabled(health.get("status") == "healthy")

    def refresh(self) -> None:
        self._render_health()
        snapshot = self._recorder.latest_snapshot()
        if snapshot is not None:
            projection = snapshot.get("projection") or {}
            if isinstance(projection, dict):
                self._render_projection(projection)

    def dispose(self) -> None:
        if self._subscribed:
            self._recorder.unsubscribe(self._on_event)
            self._subscribed = False
