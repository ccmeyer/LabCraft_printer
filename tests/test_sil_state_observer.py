import json
from pathlib import Path

from PySide6 import QtCore

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
            source_identity="pytest-observer",
        )
    )


def _wait_until(qapp, predicate, timeout_ms=5000):
    deadline = QtCore.QDeadlineTimer(timeout_ms)
    while not deadline.hasExpired():
        qapp.processEvents(QtCore.QEventLoop.AllEvents, 5)
        if predicate():
            return
        QtCore.QThread.msleep(1)
    qapp.processEvents(QtCore.QEventLoop.AllEvents, 5)
    assert predicate(), "condition did not become true before timeout"


def _events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_observer_records_normal_controller_transitions_and_reconciles(qapp, tmp_path):
    session = _session(qapp, tmp_path / "observer")
    session.launch()
    observer = session.observer
    recorder = session.recorder
    controller = session.components.controller
    machine = session.components.machine
    model_machine = session.components.model.machine_model
    try:
        assert observer.installed
        connection_count = observer.connection_count
        assert connection_count > 0
        assert observer.install() is False
        assert observer.connection_count == connection_count

        assert session.connect_simulator()
        _wait_until(qapp, model_machine.is_connected)
        controller.toggle_motors()
        controller.home_machine()
        _wait_until(qapp, machine.check_if_all_completed)
        assert controller.toggle_regulation()
        assert controller.set_absolute_XY(1200, 3400, override=True)
        assert controller.open_gripper()
        assert controller.close_gripper()
        _wait_until(qapp, machine.check_if_all_completed)
        _wait_until(
            qapp,
            lambda: (
                recorder.latest_snapshot() is not None
                and recorder.latest_snapshot()["projection"]["reconciliation"]["status"]
                == "ok"
            ),
        )
        session.disconnect_simulator()
        _wait_until(qapp, lambda: not model_machine.is_connected())
        qapp.processEvents()

        events = _events(recorder.events_path)
        assert [event["event_sequence"] for event in events] == list(
            range(1, len(events) + 1)
        )
        kinds = [event["event_kind"] for event in events]
        for expected in (
            "action_started",
            "simulator_connection_changed",
            "simulator_command_lifecycle",
            "simulator_state_changed",
            "model_machine_state_changed",
            "projection_reconciled",
            "action_completed",
        ):
            assert expected in kinds

        lifecycle = [
            event
            for event in events
            if event["event_kind"] == "simulator_command_lifecycle"
        ]
        lifecycle_states = {event["payload"].get("event") for event in lifecycle}
        assert {"queued", "sent", "accepted", "completed"} <= lifecycle_states
        command_ids = {
            event["correlation"].get("command_id") for event in lifecycle
        }
        assert None not in command_ids
        assert len(command_ids) >= 6

        connect_start = next(
            event
            for event in events
            if event["event_kind"] == "action_started"
            and event["payload"]["action_kind"] == "connect_simulator"
        )
        connect_id = connect_start["correlation"]["action_id"]
        connect_events = [
            event
            for event in events
            if event["correlation"].get("action_id") == connect_id
        ]
        connect_kinds = [event["event_kind"] for event in connect_events]
        assert connect_kinds[0] == "action_started"
        assert connect_kinds.index("action_started") < connect_kinds.index(
            "action_completed"
        ) < connect_kinds.index("snapshot_exported")
        assert recorder.healthy
    finally:
        assert session.close()

    final_events = _events(recorder.events_path)
    assert final_events[-2]["event_kind"] == "cleanup_completed"
    assert final_events[-1]["event_kind"] == "recorder_stopped"
    assert observer.installed is False
    assert observer.connection_count == 0
    assert observer.dispose() is False


def test_observer_coalesces_reconciliation_within_one_event_loop_turn(qapp, tmp_path):
    session = _session(qapp, tmp_path / "coalescing")
    try:
        observer = session.observer
        recorder = session.recorder
        qapp.processEvents()
        before = recorder.health_snapshot()["event_counts"].get(
            "projection_reconciled", 0
        )
        observer.schedule_reconciliation("first")
        observer.schedule_reconciliation("second")
        observer.schedule_reconciliation("first")
        qapp.processEvents()
        after = recorder.health_snapshot()["event_counts"].get(
            "projection_reconciled", 0
        )
        assert after == before + 1
        latest = recorder.latest_snapshot()
        assert latest["reason"] == "first+second"
    finally:
        assert session.close()


def test_experiment_loaded_signal_captures_persistence_projection(qapp, tmp_path):
    session = _session(qapp, tmp_path / "experiment-load")
    try:
        experiment = session.components.model.experiment_model
        experiment.metadata["name"] = "observer-load"
        experiment.initialize_experiment()
        progress = Path(experiment.experiment_dir_path) / "progress.json"
        progress.write_text(
            json.dumps(
                {
                    "schema_id": "labcraft.execution_progress",
                    "schema_version": 1,
                    "plan_id": "plan-observer",
                    "plan_revision": 1,
                    "wells": {},
                    "intents": [],
                }
            ),
            encoding="utf-8",
        )
        before = progress.read_bytes()

        qapp.processEvents()
        session.components.model.experiment_loaded.emit()
        qapp.processEvents()
        latest = session.recorder.latest_snapshot()
        assert latest["reason"] == "experiment_loaded"
        persistence = latest["projection"]["layers"]["persistence"]
        assert persistence["available"] is True
        assert persistence["state"]["documents"]["progress.json"]["exists"]
        assert latest["projection"]["reconciliation"]["status"] == "ok"
        assert progress.read_bytes() == before

        events = _events(session.recorder.events_path)
        load_event = next(
            event
            for event in events
            if event["event_kind"] == "model_experiment_loaded"
        )
        snapshot_event = next(
            event
            for event in events
            if event["event_kind"] == "snapshot_exported"
            and event["payload"]["reason"] == "experiment_loaded"
        )
        assert load_event["event_sequence"] < snapshot_event["event_sequence"]
    finally:
        assert session.close()
