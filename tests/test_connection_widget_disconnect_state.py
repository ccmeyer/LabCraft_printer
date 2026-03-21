from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import QObject, Signal

import View


class _FakeMachine(QObject):
    disconnect_complete_signal = Signal()


class _FakeMachineModel(QObject):
    machine_state_updated = Signal(bool)
    ports_updated = Signal(list)
    balance_state_updated = Signal(bool)

    def __init__(self, *, machine_connected=True, balance_connected=False):
        super().__init__()
        self.machine_connected = machine_connected
        self.balance_connected = balance_connected


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
        },
        profile=SimpleNamespace(name="current"),
    )

    widget = View.ConnectionWidget(main_window, _make_model(machine_model), controller)

    assert widget.machine_connect_button.text() == "Disconnect"
    assert widget.machine_connect_button.isEnabled()

    widget.request_machine_connect_change()

    controller.disconnect_machine.assert_called_once_with()
    assert widget.machine_connect_button.text() == "Disconnecting..."
    assert not widget.machine_connect_button.isEnabled()
    assert main_window.color_dict["mid_gray"] in widget.machine_connect_button.styleSheet()

    machine.disconnect_complete_signal.emit()

    assert widget.machine_connect_button.text() == "Connect"
    assert widget.machine_connect_button.isEnabled()
    assert not widget.machine_connect_button.isChecked()
