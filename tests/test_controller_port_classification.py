from types import SimpleNamespace

import Controller as controller_mod
from ApplicationComposition import ExperimentalFeatures, PRODUCTION_RUNTIME_CONTEXT
from Controller import Controller
import pytest


class Emitter:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _CommandService:
    def __init__(self):
        self.connect_calls = []
        self.disconnect_calls = 0

    def connect_balance(self, port):
        self.connect_calls.append(port)
        return SimpleNamespace(accepted=True, detail="")

    def disconnect_balance(self):
        self.disconnect_calls += 1
        return SimpleNamespace(accepted=True, detail="")


def _experimental_controller(
    service=None,
    machine_port="",
    machine_log_port=None,
    resolved_machine_log_port=None,
):
    controller = Controller.__new__(Controller)
    controller.runtime_context = PRODUCTION_RUNTIME_CONTEXT
    controller.experimental_features = ExperimentalFeatures(True)
    controller._experimental_balance_service = service or _CommandService()
    controller._experimental_balance_ports = ()
    controller._experimental_balance_connection_snapshot = None
    controller._experimental_balance_last_reading = None
    controller.machine = SimpleNamespace(
        get_machine_port=lambda: machine_port,
        get_machine_log_port=lambda: machine_log_port,
        get_resolved_machine_log_port=lambda: resolved_machine_log_port,
    )
    controller.error_occurred_signal = Emitter()
    controller.experimental_balance_connection_changed = Emitter()
    controller.experimental_balance_reading_received = Emitter()
    controller.experimental_balance_error_occurred = Emitter()
    return controller


def test_classify_port_mcu_and_balance():
    c = Controller.__new__(Controller)
    c._port_info = {
        "COM_MCU": SimpleNamespace(device="COM_MCU", vid=0x0483, description="STM", manufacturer="STMicroelectronics"),
        "COM_BAL": SimpleNamespace(device="COM_BAL", vid=None, description="usb serial balance", manufacturer=""),
    }

    assert Controller._classify_port(c, "COM_MCU") == "mcu"
    assert Controller._classify_port(c, "COM_BAL") == "balance"


def test_connect_machine_rejects_balance_port():
    c = Controller.__new__(Controller)
    c.error_occurred_signal = Emitter()
    c.machine = SimpleNamespace(connect_board=lambda port: (_ for _ in ()).throw(AssertionError("should not connect")))
    c._port_info = {
        "COMX": SimpleNamespace(device="COMX", vid=None, description="ohaus scale", manufacturer="")
    }
    Controller.connect_machine(c, "COMX")
    assert "BALANCE/scale" in c.error_occurred_signal.calls[0][1]


def test_connect_balance_rejects_mcu_port():
    c = Controller.__new__(Controller)
    c.error_occurred_signal = Emitter()
    c.balance = SimpleNamespace(connect_balance=lambda port: (_ for _ in ()).throw(AssertionError("should not connect")))
    c._port_info = {
        "COMY": SimpleNamespace(device="COMY", vid=0x0483, description="STM32", manufacturer="stmicro")
    }
    Controller.connect_balance(c, "COMY")
    assert "looks like the MCU" in c.error_occurred_signal.calls[0][1]


def test_classify_port_refreshes_from_comports_when_not_cached(monkeypatch):
    c = Controller.__new__(Controller)
    c._port_info = {}
    monkeypatch.setattr(
        controller_mod,
        "comports",
        lambda: [SimpleNamespace(device="COM9", vid=0x0483, description="stm32", manufacturer="")],
    )
    assert Controller._classify_port(c, "COM9") == "mcu"


@pytest.mark.parametrize(
    "desc,manuf,expected",
    [
        ("prolific usb-to-serial", "", "balance"),
        ("OHAUS scale", "", "balance"),
        ("unknown", "STMICROELECTRONICS", "mcu"),
    ],
)
def test_classify_port_case_insensitive_heuristics(desc, manuf, expected):
    c = Controller.__new__(Controller)
    c._port_info = {
        "COMZ": SimpleNamespace(device="COMZ", vid=None, description=desc, manufacturer=manuf)
    }
    assert Controller._classify_port(c, "COMZ") == expected


def test_experimental_listing_filters_mcu_unknown_and_prefers_by_id(monkeypatch):
    ports = [
        SimpleNamespace(
            device="/dev/ttyUSB0",
            vid=0x10C4,
            pid=0xEA60,
            description="CP2102 USB UART",
            manufacturer="Silicon Labs",
            product="CP2102",
            serial_number="mcu",
        ),
        SimpleNamespace(
            device="/dev/ttyUSB1",
            vid=0x067B,
            pid=0x23A3,
            description="USB-Serial Controller",
            manufacturer="Prolific Technology Inc.",
            product="USB-Serial Controller",
            serial_number="balance",
        ),
        SimpleNamespace(
            device="/dev/ttyUSB2",
            vid=0x1234,
            pid=0x5678,
            description="Sartorius scale adapter",
            manufacturer="",
            product="",
            serial_number=None,
        ),
        SimpleNamespace(
            device="/dev/ttyUSB3",
            vid=0x9999,
            pid=0x0001,
            description="Generic serial adapter",
            manufacturer="Unknown",
            product="UART",
            serial_number=None,
        ),
        SimpleNamespace(
            device="/dev/ttyAMA0",
            vid=None,
            pid=None,
            description="Prolific",
            manufacturer="Prolific",
            product="",
            serial_number=None,
        ),
    ]
    alias = "/dev/serial/by-id/usb-Prolific_balance-if00-port0"
    monkeypatch.setattr(controller_mod, "comports", lambda: ports)
    monkeypatch.setattr(
        controller_mod,
        "_serial_by_id_aliases",
        lambda: {
            controller_mod._resolved_serial_path("/dev/ttyUSB1"): (alias,)
        },
    )
    controller = _experimental_controller()

    listed = controller.list_experimental_balance_ports()

    assert [item.system_device for item in listed] == [
        "/dev/ttyUSB2",
        "/dev/ttyUSB1",
    ]
    prolific = next(item for item in listed if item.vid_pid == "067b:23a3")
    assert prolific.device_path == alias
    assert prolific.by_id_paths == (alias,)


def test_experimental_listing_excludes_active_machine_even_with_balance_metadata(
    monkeypatch,
):
    monkeypatch.setattr(
        controller_mod,
        "comports",
        lambda: [
            SimpleNamespace(
                device="COM7",
                vid=0x067B,
                pid=0x23A3,
                description="Prolific balance",
                manufacturer="Prolific",
                product="USB serial",
                serial_number="same",
            )
        ],
    )
    monkeypatch.setattr(controller_mod, "_serial_by_id_aliases", lambda: {})
    controller = _experimental_controller(machine_port="COM7")

    assert controller.list_experimental_balance_ports() == ()


def test_experimental_listing_reserves_mcu_log_port_even_with_balance_metadata(
    monkeypatch,
):
    alias = "/dev/serial/by-id/usb-Silicon_Labs_CP2102-if00-port0"
    system_device = "/dev/ttyUSB0"
    monkeypatch.setattr(
        controller_mod,
        "comports",
        lambda: [
            SimpleNamespace(
                device=system_device,
                vid=0x067B,
                pid=0x23A3,
                description="Prolific balance",
                manufacturer="Prolific",
                product="USB serial",
                serial_number="misleading",
            )
        ],
    )
    monkeypatch.setattr(controller_mod, "_serial_by_id_aliases", lambda: {})
    monkeypatch.setattr(
        controller_mod,
        "_resolved_serial_path",
        lambda path: system_device if str(path) in {alias, system_device} else str(path),
    )
    controller = _experimental_controller(machine_log_port=alias)

    assert controller.list_experimental_balance_ports() == ()


def test_experimental_connect_requires_fresh_listed_path(monkeypatch):
    service = _CommandService()
    controller = _experimental_controller(service)
    info = SimpleNamespace(
        device="COM8",
        vid=0x067B,
        pid=0x23A3,
        description="Prolific",
        manufacturer="Prolific",
        product="USB serial",
        serial_number="balance",
    )
    monkeypatch.setattr(controller_mod, "comports", lambda: [info])
    monkeypatch.setattr(controller_mod, "_serial_by_id_aliases", lambda: {})

    assert controller.connect_experimental_balance("") is False
    assert controller.connect_experimental_balance("COM-stale") is False
    assert service.connect_calls == []

    assert controller.connect_experimental_balance("COM8") is True
    assert service.connect_calls == ["COM8"]
    assert controller.disconnect_experimental_balance() is True
    assert service.disconnect_calls == 1


def test_experimental_disabled_does_not_enumerate(monkeypatch):
    controller = _experimental_controller()
    controller.experimental_features = ExperimentalFeatures(False)
    controller._experimental_balance_service = None
    monkeypatch.setattr(
        controller_mod,
        "comports",
        lambda: (_ for _ in ()).throw(AssertionError("must not enumerate")),
    )

    assert controller.list_experimental_balance_ports() == ()
    assert controller.connect_experimental_balance("COM8") is False


def test_experimental_events_are_cached_and_reemitted():
    controller = _experimental_controller()
    snapshot = object()
    reading = object()
    error = SimpleNamespace(detail="read failed")

    controller._on_experimental_balance_connection_changed(snapshot)
    controller._on_experimental_balance_reading_received(reading)
    controller._on_experimental_balance_error_occurred(error)

    assert controller.get_experimental_balance_connection_snapshot() is snapshot
    assert controller.get_experimental_balance_last_reading() is reading
    assert controller.experimental_balance_connection_changed.calls == [(snapshot,)]
    assert controller.experimental_balance_reading_received.calls == [(reading,)]
    assert controller.experimental_balance_error_occurred.calls == [(error,)]
    assert controller.error_occurred_signal.calls[-1] == (
        "Experimental Balance Error",
        "read failed",
    )
