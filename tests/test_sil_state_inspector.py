import json
from pathlib import Path

from tools.sil.inspector import StateInspectorDock
from tools.sil.session import (
    ArtifactRetentionPolicy,
    SessionRootPolicy,
    SimulationSession,
    SimulationSessionConfigV1,
)


def _session(qapp, root: Path):
    return SimulationSession.create(
        SimulationSessionConfigV1(
            visible=False,
            qt_ownership="borrowed",
            root_policy=SessionRootPolicy.RETAINED,
            session_root=root.resolve(),
            artifact_retention=ArtifactRetentionPolicy.RETAIN,
            speed_multiplier=1000.0,
            source_identity="pytest-inspector",
        )
    )


def test_inspector_is_read_only_recorder_view_and_show_is_idempotent(qapp, tmp_path):
    session = _session(qapp, tmp_path / "inspector")
    view = session.launch()
    inspector = session.inspector
    try:
        assert isinstance(inspector, StateInspectorDock)
        assert inspector.parent() is view
        assert inspector.windowTitle() == StateInspectorDock.TITLE
        assert inspector.objectName() == "silStateInspectorDock"
        assert inspector.snapshot_text.isReadOnly()
        assert inspector._recorder is session.recorder
        assert not hasattr(inspector, "controller")
        assert not hasattr(inspector, "model")
        assert not hasattr(inspector, "machine")

        inspector.hide()
        assert session.show_state_inspector()
        assert session.show_state_inspector()
        assert not inspector.isHidden()
        assert inspector.health_label.text() == "healthy"

        before = session.recorder.health_snapshot()["last_event_sequence"]
        inspector.export_button.click()
        qapp.processEvents()
        after = session.recorder.health_snapshot()["last_event_sequence"]
        assert after >= before + 3
        assert inspector.sequence_label.text() == str(after)
        assert inspector.reconciliation_label.text() == "ok"
        rendered = json.loads(inspector.snapshot_text.toPlainText())
        assert rendered["reason"] == "manual_export"
        assert rendered["reconciliation"]["status"] == "ok"

        rendered["reason"] = "mutated-inspector-copy"
        assert session.recorder.latest_snapshot()["projection"]["reason"] == (
            "manual_export"
        )

        inspector.dispose()
        inspector.dispose()
        sequence = inspector.sequence_label.text()
        session.recorder.record_event("after_dispose", source_layer="test")
        assert inspector.sequence_label.text() == sequence
    finally:
        assert session.close()
