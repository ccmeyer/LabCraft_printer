from types import SimpleNamespace

import Controller as controller_mod
from Controller import Controller
import pytest


class Emitter:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


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
