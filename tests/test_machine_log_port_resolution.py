from types import SimpleNamespace

import Machine_FreeRTOS as mfr
from Machine_FreeRTOS import Machine


def test_resolve_log_port_prefers_explicit_configured_port():
    assert mfr.resolve_log_port("COM4", configured_log_port="COM9") == "COM9"


def test_resolve_log_port_rejects_configured_control_port():
    assert mfr.resolve_log_port("COM4", configured_log_port="COM4") is None


def test_resolve_log_port_prefers_ttyusb_for_pi_control_port():
    ports = [
        SimpleNamespace(device="/dev/ttyAMA0", description="PL011", manufacturer="", hwid=""),
        SimpleNamespace(device="/dev/ttyUSB0", description="USB Serial", manufacturer="", hwid=""),
    ]

    assert mfr.resolve_log_port("/dev/ttyAMA0", port_infos=ports) == "/dev/ttyUSB0"


def test_resolve_log_port_prefers_cp210_style_adapter_for_windows_control_port():
    ports = [
        SimpleNamespace(device="COM4", description="STMicroelectronics Virtual COM Port", manufacturer="STMicroelectronics", hwid="USB VID:PID=0483:5740"),
        SimpleNamespace(device="COM9", description="CP210x USB to UART Bridge", manufacturer="Silicon Labs", hwid="USB VID:PID=10C4:EA60"),
        SimpleNamespace(device="COM7", description="Ohaus Balance", manufacturer="Ohaus", hwid="USB VID:PID=0000:0000"),
    ]

    assert mfr.resolve_log_port("COM4", port_infos=ports) == "COM9"


def test_begin_log_thread_uses_resolved_log_port(qapp, monkeypatch):
    profile = SimpleNamespace(
        name="current",
        has_refuel_camera=False,
        has_droplet_camera=False,
        has_log_channel=True,
    )
    machine = Machine(SimpleNamespace(), profile=profile)
    machine.port = "COM4"

    class _SignalTracker:
        def __init__(self):
            self.connected = []

        def connect(self, slot):
            self.connected.append(slot)

    created = []

    class _Reader:
        def __init__(self, baud, parent=None, log_port="/dev/ttyUSB0", history_len=360, serial_factory=None):
            self.baud = baud
            self.log_port = log_port
            self.parent = parent
            self.history_len = history_len
            self.serial_factory = serial_factory
            self.lineReceived = _SignalTracker()
            self.statsUpdated = _SignalTracker()
            self.messageReceived = _SignalTracker()
            self.flashStateChanged = _SignalTracker()
            self.start_calls = 0
            created.append(self)

        def start(self):
            self.start_calls += 1

    monkeypatch.setattr(mfr, "resolve_log_port", lambda control_port, configured_log_port=None: "COM9")
    monkeypatch.setattr(mfr, "LogReader", _Reader)

    machine.begin_log_thread()

    assert len(created) == 1
    assert created[0].log_port == "COM9"
    assert created[0].start_calls == 1


def test_begin_log_thread_skips_start_when_no_log_port(qapp, monkeypatch, capsys):
    profile = SimpleNamespace(
        name="current",
        has_refuel_camera=False,
        has_droplet_camera=False,
        has_log_channel=True,
    )
    machine = Machine(SimpleNamespace(), profile=profile)
    machine.port = "COM4"

    def _boom(*_args, **_kwargs):
        raise AssertionError("LogReader should not be constructed without a resolved port")

    monkeypatch.setattr(mfr, "resolve_log_port", lambda control_port, configured_log_port=None: None)
    monkeypatch.setattr(mfr, "LogReader", _boom)

    machine.begin_log_thread()

    out = capsys.readouterr().out
    assert machine.log_reader is None
    assert "No dedicated log UART could be resolved" in out
