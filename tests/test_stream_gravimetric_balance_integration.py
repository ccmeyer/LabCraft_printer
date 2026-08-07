from decimal import Decimal
from types import SimpleNamespace

from PySide6 import QtCore

from CalibrationClasses.View import ExperimentalBalanceConnectionGroup
from tests.test_stream_gravimetric_capture import (
    SignalStub,
    _build_view_dialog,
)


class _UiController(QtCore.QObject):
    experimental_balance_connection_changed = QtCore.Signal(object)
    experimental_balance_reading_received = QtCore.Signal(object)
    experimental_balance_error_occurred = QtCore.Signal(object)

    def __init__(self, descriptors=(), cached_reading=None, cached_snapshot=None):
        super().__init__()
        self.experimental_balance_enabled = True
        self.descriptors = tuple(descriptors)
        self.cached_reading = cached_reading
        self.cached_snapshot = cached_snapshot
        self.list_calls = 0
        self.connect_calls = []
        self.disconnect_calls = 0

    def list_experimental_balance_ports(self):
        self.list_calls += 1
        return self.descriptors

    def connect_experimental_balance(self, port):
        self.connect_calls.append(port)
        return True

    def disconnect_experimental_balance(self):
        self.disconnect_calls += 1
        return True

    def get_experimental_balance_connection_snapshot(self):
        return self.cached_snapshot

    def get_experimental_balance_last_reading(self):
        return self.cached_reading


def _port(path="/dev/serial/by-id/usb-Prolific_balance"):
    return SimpleNamespace(
        device_path=path,
        display_label=f"HPB balance — {path} [067b:23a3]",
    )


def _snapshot(state, detail=""):
    return SimpleNamespace(state=SimpleNamespace(value=state), detail=detail)


def test_group_discovers_without_connecting_and_requires_button_click(qapp):
    descriptor = _port()
    controller = _UiController((descriptor,))

    group = ExperimentalBalanceConnectionGroup(
        controller,
        preselected_port=descriptor.device_path,
    )
    qapp.processEvents()

    assert controller.list_calls == 1
    assert controller.connect_calls == []
    assert group.port_combo.currentData() == descriptor.device_path
    assert group.connection_button.text() == "Connect"
    assert group.connection_button.isEnabled()

    group.connection_button.click()
    assert controller.connect_calls == [descriptor.device_path]
    assert controller.disconnect_calls == 0


def test_group_follows_typed_states_and_restores_last_reading(qapp):
    reading = SimpleNamespace(mass_mg=Decimal("125.34"), device_stable=True)
    controller = _UiController((_port(),), cached_reading=reading)
    group = ExperimentalBalanceConnectionGroup(controller)

    assert group.last_reading_label.text() == "Last reading: 125.34 mg (stable)"

    controller.experimental_balance_connection_changed.emit(
        _snapshot("connecting")
    )
    assert not group.port_combo.isEnabled()
    assert not group.refresh_button.isEnabled()
    assert group.connection_button.text() == "Connecting…"

    controller.experimental_balance_connection_changed.emit(
        _snapshot("streaming", "receiving data")
    )
    assert group.connection_state_label.text() == "Streaming: receiving data"
    assert group.connection_button.text() == "Disconnect"
    assert group.connection_button.isEnabled()
    group.connection_button.click()
    assert controller.disconnect_calls == 1

    controller.experimental_balance_reading_received.emit(
        SimpleNamespace(mass_mg=Decimal("125.33"), device_stable=False)
    )
    assert group.last_reading_label.text() == "Last reading: 125.33 mg (unstable)"

    controller.experimental_balance_connection_changed.emit(
        _snapshot("disconnecting")
    )
    assert group.connection_button.text() == "Disconnecting…"
    assert not group.connection_button.isEnabled()

    controller.experimental_balance_connection_changed.emit(_snapshot("error"))
    assert group.connection_button.text() == "Disconnect"
    assert group.connection_button.isEnabled()


def test_dialog_group_is_hidden_by_default_and_enabled_group_is_connection_only(
    monkeypatch, qapp
):
    disabled_dialog, manager, controller = _build_view_dialog(monkeypatch, qapp)
    model = disabled_dialog.model
    assert not hasattr(disabled_dialog, "experimental_balance_group")
    disabled_dialog.close()

    descriptor = _port("COM8")
    controller.experimental_balance_enabled = True
    controller.experimental_balance_connection_changed = SignalStub()
    controller.experimental_balance_reading_received = SignalStub()
    controller.experimental_balance_error_occurred = SignalStub()
    controller.list_experimental_balance_ports = lambda: (descriptor,)
    controller.get_experimental_balance_connection_snapshot = lambda: None
    controller.get_experimental_balance_last_reading = lambda: None
    controller.experimental_connect_calls = []
    controller.connect_experimental_balance = (
        lambda port: controller.experimental_connect_calls.append(port) or True
    )
    controller.disconnect_experimental_balance = lambda: True
    model.get_default_balance_port = lambda: "COM8"

    enabled_dialog, _manager, _controller = _build_view_dialog(
        monkeypatch,
        qapp,
        manager=manager,
        model=model,
        controller=controller,
    )

    assert enabled_dialog.experimental_balance_group.title() == "Experimental Balance"
    assert enabled_dialog.stream_capture_group.isAncestorOf(
        enabled_dialog.experimental_balance_group
    )
    assert controller.experimental_connect_calls == []
    assert enabled_dialog.stream_capture_starting_mass_spin.value() == 0.0
    assert controller.stream_capture_start_calls == []

