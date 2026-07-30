from pathlib import Path

from PySide6 import QtCore, QtWidgets

from tools.sil.control import SimulatorControlDock
from tools.sil.session import (
    ArtifactRetentionPolicy,
    SessionRootPolicy,
    SimulationSession,
    SimulationSessionConfigV1,
)


def _config(root: Path):
    return SimulationSessionConfigV1(
        visible=False,
        qt_ownership="borrowed",
        root_policy=SessionRootPolicy.RETAINED,
        session_root=root.resolve(),
        artifact_retention=ArtifactRetentionPolicy.RETAIN,
        seed=23,
        speed_multiplier=1000.0,
        source_identity="pytest",
    )


def _wait_until(qapp, predicate, timeout_ms=5000):
    deadline = QtCore.QDeadlineTimer(timeout_ms)
    while not deadline.hasExpired():
        qapp.processEvents(QtCore.QEventLoop.AllEvents, 5)
        if predicate():
            return
        QtCore.QThread.msleep(1)
    assert predicate(), "condition did not become true before timeout"


def test_simulator_control_is_persistent_and_uses_only_session_callbacks(
    qapp,
    tmp_path,
):
    session = SimulationSession.create(_config(tmp_path / "control"))
    try:
        view = session.launch()
        control = session.control
        assert isinstance(control, SimulatorControlDock)
        assert control.windowTitle() == "SIMULATOR CONTROL — NO HARDWARE"
        assert control.objectName() == "simulatorControlDock"
        assert (
            control.features()
            == QtWidgets.QDockWidget.DockWidgetFeature.NoDockWidgetFeatures
        )
        assert control.parent() is view
        assert control.seed_label.text() == "23"
        assert control.timing_label.text() == "1000x"
        assert control.connect_button.isEnabled()
        assert not control.disconnect_button.isEnabled()
        assert not view.connection_widget.machine_connect_button.isEnabled()

        control.connect_button.click()
        _wait_until(qapp, lambda: session.components.machine.state.connected)
        assert "SIMULATED" in control.connection_label.text()
        assert not control.connect_button.isEnabled()
        assert control.disconnect_button.isEnabled()

        session.components.controller.toggle_motors()
        session.components.controller.home_machine()
        _wait_until(qapp, session.components.machine.check_if_all_completed)
        assert "Enabled" in control.motors_label.text()
        assert "Yes" in control.motors_label.text()

        control.disconnect_button.click()
        _wait_until(qapp, lambda: not session.components.machine.state.connected)
        assert control.connection_label.text() == "Disconnected"
        assert control.connect_button.isEnabled()
        assert not control.disconnect_button.isEnabled()
    finally:
        assert session.close()


def test_controller_rejects_nonliteral_simulation_ports(qapp, tmp_path):
    session = SimulationSession.create(_config(tmp_path / "sentinel"))
    messages = []
    controller = session.components.controller
    machine = session.components.machine
    controller.error_occurred_signal.disconnect()
    controller.error_occurred_signal.connect(
        lambda title, message: messages.append((title, message))
    )
    try:
        assert controller.connect_machine("simulated") is False
        assert controller.connect_machine("COM4") is False
        assert controller.connect_machine("SIMULATED ") is False
        assert machine.port is None
        assert machine.state.connected is False
        assert messages
        assert all(title == "Simulation Mode" for title, _message in messages)
        assert all("only 'SIMULATED' is allowed" in message for _title, message in messages)
    finally:
        assert session.close()

