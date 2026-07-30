import json
from pathlib import Path
import random

import pytest
from PySide6 import QtCore, QtWidgets

import ApplicationComposition as composition
from tools.sil.session import (
    ArtifactRetentionPolicy,
    SESSION_FILENAME,
    SESSION_SCHEMA_ID,
    SessionRootPolicy,
    SimulationSession,
    SimulationSessionConfigV1,
)


def _retained_config(root: Path, **overrides):
    values = {
        "visible": False,
        "qt_ownership": "borrowed",
        "root_policy": SessionRootPolicy.RETAINED,
        "session_root": root.resolve(),
        "artifact_retention": ArtifactRetentionPolicy.RETAIN,
        "speed_multiplier": 1000.0,
        "source_identity": "pytest",
    }
    values.update(overrides)
    return SimulationSessionConfigV1(**values)


def _wait_until(qapp, predicate, timeout_ms=5000):
    deadline = QtCore.QDeadlineTimer(timeout_ms)
    while not deadline.hasExpired():
        qapp.processEvents(QtCore.QEventLoop.AllEvents, 5)
        if predicate():
            return
        QtCore.QThread.msleep(1)
    qapp.processEvents(QtCore.QEventLoop.AllEvents, 5)
    assert predicate(), "condition did not become true before timeout"


@pytest.mark.parametrize("speed", [0, -1, float("inf"), float("nan")])
def test_config_rejects_invalid_timing(speed):
    with pytest.raises(ValueError, match="speed_multiplier"):
        SimulationSessionConfigV1(speed_multiplier=speed)


def test_config_rejects_ambiguous_root_policies(tmp_path):
    with pytest.raises(ValueError, match="allocate their own"):
        SimulationSessionConfigV1(
            root_policy="fresh",
            session_root=tmp_path.resolve(),
        )
    with pytest.raises(ValueError, match="require session_root"):
        SimulationSessionConfigV1(root_policy="retained")
    with pytest.raises(ValueError, match="must use artifact_retention"):
        SimulationSessionConfigV1(
            root_policy="retained",
            session_root=tmp_path.resolve(),
        )


def test_session_rejects_repository_and_unmarked_nonempty_roots(qapp, tmp_path):
    with pytest.raises(Exception, match="overlaps repository"):
        SimulationSession.create(_retained_config(Path.cwd()))

    nonempty = tmp_path / "not-a-session"
    nonempty.mkdir()
    (nonempty / "unrelated.txt").write_text("not a marker", encoding="utf-8")
    with pytest.raises(Exception, match="missing a valid session.json"):
        SimulationSession.create(_retained_config(nonempty))


def test_session_constructs_real_app_with_contained_application_writers(
    qapp,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        composition,
        "_production_machine_factory",
        lambda *_args, **_kwargs: pytest.fail("production machine factory invoked"),
    )
    root = tmp_path / "retained"
    session = SimulationSession.create(_retained_config(root))
    try:
        assert type(session.components.model).__name__ == "Model"
        assert type(session.components.controller).__name__ == "Controller"
        assert type(session.components.machine).__name__ == "SimulatedMachine"
        assert session.components.controller.runtime_context.is_simulation

        metadata = json.loads((root / SESSION_FILENAME).read_text(encoding="utf-8"))
        assert metadata["schema_id"] == SESSION_SCHEMA_ID
        assert metadata["schema_version"] == 1
        assert metadata["runtime_mode"] == "simulation"
        assert metadata["safety"]["hardware_access_allowed"] is False
        assert metadata["simulator"]["port"] == "SIMULATED"
        assert metadata["application_roots"] == {
            "config": "config",
            "experiments": "experiments",
            "calibration_memory": "calibration-memory",
        }

        for relative in ("config", "experiments", "calibration-memory"):
            assert (root / relative).is_dir()
        assert (root / "logs" / "launcher.log").is_file()
        assert (root / "artifacts").is_dir()

        model = session.components.model
        for application_file in (
            model.locations_path,
            model.plates_path,
            model.settings_path,
            model.obstacles_path,
            model.regulator_profiles_path,
        ):
            resolved = Path(application_file).resolve()
            assert (root / "config").resolve() in resolved.parents
            assert resolved.is_file()

        model.experiment_model.metadata["name"] = "milestone-one"
        model.experiment_model.initialize_experiment()
        experiment_root = Path(model.experiment_model.experiment_dir_path).resolve()
        assert (root / "experiments").resolve() in experiment_root.parents
        assert not (experiment_root / SESSION_FILENAME).exists()
    finally:
        assert session.close()
        assert session.close()


def test_session_uses_private_seeded_rng_without_mutating_global_random(qapp, tmp_path):
    random.seed(9401)
    global_state = random.getstate()
    first = SimulationSession.create(
        _retained_config(tmp_path / "first", seed=17)
    )
    second = SimulationSession.create(
        _retained_config(tmp_path / "second", seed=17)
    )
    try:
        assert random.getstate() == global_state
        assert [first.rng.random() for _ in range(3)] == [
            second.rng.random() for _ in range(3)
        ]
    finally:
        assert first.close()
        assert second.close()


def test_session_controller_path_operates_simulator_and_closes_connected_window(
    qapp,
    tmp_path,
    monkeypatch,
):
    session = SimulationSession.create(_retained_config(tmp_path / "operation"))
    view = session.launch()
    controller = session.components.controller
    machine = session.components.machine
    model = session.components.model
    try:
        assert session.connect_simulator()
        _wait_until(qapp, model.machine_model.is_connected)

        controller.toggle_motors()
        controller.home_machine()
        _wait_until(qapp, machine.check_if_all_completed)
        assert model.machine_model.motors_are_enabled()
        assert model.machine_model.motors_are_homed()

        assert controller.toggle_regulation()
        assert controller.set_absolute_XY(1200, 3400, override=True)
        assert controller.open_gripper()
        _wait_until(qapp, machine.check_if_all_completed)
        assert machine.state.x == 1200
        assert machine.state.y == 3400
        assert machine.state.gripper_open
        assert machine.state.regulating_print_pressure
        assert machine.state.regulating_refuel_pressure

        monkeypatch.setattr(
            view,
            "popup_yes_no",
            lambda *_args, **_kwargs: QtWidgets.QMessageBox.Yes,
        )
        view.show()
        view.close()
        _wait_until(qapp, lambda: not model.machine_model.is_connected())
        assert not getattr(view, "_close_disconnect_pending", False)
        assert not machine._command_timer.isActive()
        assert not machine._connection_timer.isActive()
    finally:
        assert session.close()


def test_retained_session_reopens_with_stable_identity_and_new_app_record(
    qapp,
    tmp_path,
):
    root = tmp_path / "reopen"
    first = SimulationSession.create(_retained_config(root))
    first_session_id = first.session_id
    assert first.close()

    second = SimulationSession.create(_retained_config(root))
    try:
        assert second.session_id == first_session_id
        metadata = json.loads((root / SESSION_FILENAME).read_text(encoding="utf-8"))
        assert len(metadata["application_sessions"]) == 2
        assert (
            metadata["application_sessions"][0]["application_session_id"]
            != metadata["application_sessions"][1]["application_session_id"]
        )
    finally:
        assert second.close()


def test_locked_retained_session_fails_closed(qapp, tmp_path):
    root = tmp_path / "locked"
    first = SimulationSession.create(_retained_config(root))
    try:
        with pytest.raises(Exception, match="already locked"):
            SimulationSession.create(_retained_config(root))
    finally:
        assert first.close()


def test_clean_fresh_root_is_removed_and_failure_is_retained(
    qapp,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    clean = SimulationSession.create(
        SimulationSessionConfigV1(
            visible=False,
            qt_ownership="borrowed",
            source_identity="pytest",
            speed_multiplier=1000.0,
        )
    )
    clean_root = clean.session_root
    assert clean.close()
    assert clean.root_removed
    assert not clean_root.exists()

    failed = SimulationSession.create(
        SimulationSessionConfigV1(
            visible=False,
            qt_ownership="borrowed",
            source_identity="pytest",
            speed_multiplier=1000.0,
        )
    )
    failed_root = failed.session_root
    assert not failed.close("forced test failure")
    assert failed_root.is_dir()
    metadata = json.loads((failed_root / SESSION_FILENAME).read_text(encoding="utf-8"))
    assert metadata["terminal_status"] == "failed"
    assert metadata["cleanup"]["root_retained"] is True

