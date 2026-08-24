from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import QObject, Signal

import View


class _FakeMachine(QObject):
    disconnect_complete_signal = Signal()


class _FakeMachineModel(QObject):
    machine_state_updated = Signal(bool)
    machine_paused = Signal()
    ports_updated = Signal(list)
    balance_state_updated = Signal(bool)

    def __init__(self, *, machine_connected=True, balance_connected=False, paused=False):
        super().__init__()
        self.machine_connected = machine_connected
        self.balance_connected = balance_connected
        self.paused = paused


def _make_model(machine_model):
    return SimpleNamespace(
        machine_model=machine_model,
        get_default_machine_port=lambda: "COM7",
        get_default_balance_port=lambda: "",
    )


def test_connection_widget_shows_disconnect_pending_until_complete(qapp):
    machine = _FakeMachine()
    machine_model = _FakeMachineModel(machine_connected=True)

    def _complete_disconnect():
        machine_model.machine_connected = False
        machine_model.machine_state_updated.emit(False)

    machine.disconnect_complete_signal.connect(_complete_disconnect)

    controller = SimpleNamespace(
        machine=machine,
        connect_machine=Mock(),
        connect_balance=Mock(),
        disconnect_machine=Mock(),
        update_available_ports=Mock(),
    )
    main_window = SimpleNamespace(
        color_dict={
            "dark_blue": "#1d4ed8",
            "light_blue": "#60a5fa",
            "mid_gray": "#6e6e6e",
            "dark_red": "#8a0303",
            "orange": "#f4743b",
        },
        profile=SimpleNamespace(name="current"),
        pause_machine=Mock(),
    )

    widget = View.ConnectionWidget(main_window, _make_model(machine_model), controller)

    assert widget.machine_connect_button.text() == "Disconnect"
    assert widget.machine_connect_button.isEnabled()
    assert widget.pause_machine_button.text() == "Pause"
    assert widget.pause_machine_button.isEnabled()

    widget.request_machine_connect_change()

    controller.disconnect_machine.assert_called_once_with()
    assert widget.machine_connect_button.text() == "Disconnecting..."
    assert not widget.machine_connect_button.isEnabled()
    assert main_window.color_dict["mid_gray"] in widget.machine_connect_button.styleSheet()
    assert not widget.pause_machine_button.isEnabled()

    machine.disconnect_complete_signal.emit()

    assert widget.machine_connect_button.text() == "Connect"
    assert widget.machine_connect_button.isEnabled()
    assert not widget.machine_connect_button.isChecked()
    assert not widget.pause_machine_button.isEnabled()


def _make_connection_widget(qapp, *, profile="current", connected=True, paused=False):
    machine = _FakeMachine()
    machine_model = _FakeMachineModel(machine_connected=connected, paused=paused)
    controller = SimpleNamespace(
        machine=machine,
        connect_machine=Mock(),
        connect_balance=Mock(),
        disconnect_machine=Mock(),
        update_available_ports=Mock(),
    )
    main_window = SimpleNamespace(
        color_dict={
            "dark_blue": "#1d4ed8",
            "light_blue": "#60a5fa",
            "mid_gray": "#6e6e6e",
            "dark_red": "#8a0303",
            "orange": "#f4743b",
        },
        profile=SimpleNamespace(name=profile),
        pause_machine=Mock(),
    )
    widget = View.ConnectionWidget(main_window, _make_model(machine_model), controller)
    return widget, main_window, machine_model


def test_connection_pause_button_tracks_pause_state_and_dispatches(qapp):
    widget, main_window, machine_model = _make_connection_widget(qapp)

    assert widget.pause_machine_button.objectName() == "pauseMachineButton"
    assert widget.pause_machine_button.text() == "Pause"
    assert widget.pause_machine_button.isEnabled()
    assert main_window.color_dict["dark_red"] in widget.pause_machine_button.styleSheet()

    widget.pause_machine_button.click()
    main_window.pause_machine.assert_called_once_with()

    machine_model.paused = True
    machine_model.machine_paused.emit()

    assert widget.pause_machine_button.text() == "Paused\nActions…"
    assert widget.pause_machine_button.isEnabled()
    assert main_window.color_dict["orange"] in widget.pause_machine_button.styleSheet()


def test_legacy_connection_group_includes_enabled_safety_control(qapp):
    widget, _main_window, _machine_model = _make_connection_widget(
        qapp,
        profile="legacy",
    )

    assert widget.pause_machine_button.text() == "Pause"
    assert widget.pause_machine_button.isEnabled()


def test_pause_button_spans_every_connection_row_without_safety_header(qapp):
    for profile, expected_row_span in (("current", 2), ("legacy", 3)):
        widget, _main_window, _machine_model = _make_connection_widget(
            qapp,
            profile=profile,
        )
        layout = widget.layout()
        button_index = layout.indexOf(widget.pause_machine_button)

        assert layout.getItemPosition(button_index) == (0, 3, expected_row_span, 1)
        assert "Safety" not in {
            label.text() for label in widget.findChildren(View.QLabel)
        }


def test_simulation_pause_control_waits_for_binding(qapp):
    widget, main_window, machine_model = _make_connection_widget(qapp)
    main_window.runtime_context = View.SIMULATION_RUNTIME_CONTEXT
    widget.simulation_mode = True
    widget.update_machine_connect_button(machine_model.machine_connected)

    assert not widget.pause_machine_button.isEnabled()

    widget.bind_simulation_connection(
        "SIMULATED",
        connect_callback=Mock(return_value=True),
        disconnect_callback=Mock(return_value=True),
    )

    assert widget.pause_machine_button.isEnabled()
