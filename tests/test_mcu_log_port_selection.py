from types import SimpleNamespace

import pytest

import Machine_FreeRTOS as mfr
from Model import Model
from hardware.profile import CURRENT_PROFILE, LEGACY_PROFILE
from hardware.serial_ports import (
    DEFAULT_CURRENT_MCU_LOG_PORT,
    MCU_LOG_EXPECTED_VID_PID,
    SerialPortIdentity,
    SerialPortValidationError,
    SerialPortValidationReason,
    resolve_explicit_usb_serial_port,
)


def _port(device, vid, pid, *, product="", manufacturer="", serial_number=None):
    return SimpleNamespace(
        device=device,
        vid=vid,
        pid=pid,
        description=product,
        product=product,
        manufacturer=manufacturer,
        serial_number=serial_number,
    )


def _path_resolver(mapping):
    return lambda path: mapping.get(str(path), str(path))


@pytest.mark.parametrize("cp_device", ["/dev/ttyUSB0", "/dev/ttyUSB1"])
def test_explicit_cp2102_alias_is_stable_across_ttyusb_order(cp_device):
    balance_device = "/dev/ttyUSB1" if cp_device.endswith("0") else "/dev/ttyUSB0"
    alias = DEFAULT_CURRENT_MCU_LOG_PORT
    paths = {
        alias: cp_device,
        cp_device: cp_device,
        balance_device: balance_device,
    }
    identity = resolve_explicit_usb_serial_port(
        alias,
        expected_vid_pid=MCU_LOG_EXPECTED_VID_PID,
        port_infos=(
            _port(
                balance_device,
                0x067B,
                0x23A3,
                product="USB-Serial Controller",
                manufacturer="Prolific",
            ),
            _port(
                cp_device,
                0x10C4,
                0xEA60,
                product="CP2102 USB UART",
                manufacturer="Silicon Labs",
                serial_number="0001",
            ),
        ),
        path_resolver=_path_resolver(paths),
        aliases_by_device={cp_device: (alias,)},
    )

    assert identity.requested_path == alias
    assert identity.system_device == cp_device
    assert identity.vid_pid == MCU_LOG_EXPECTED_VID_PID
    assert identity.by_id_paths == (alias,)


@pytest.mark.parametrize(
    "requested,ports,reason",
    [
        (
            "/dev/serial/by-id/missing",
            (_port("/dev/ttyUSB0", 0x10C4, 0xEA60),),
            SerialPortValidationReason.DEVICE_NOT_FOUND,
        ),
        (
            "/dev/ttyUSB0",
            (_port("/dev/ttyUSB0", None, None),),
            SerialPortValidationReason.METADATA_UNAVAILABLE,
        ),
        (
            "/dev/ttyUSB0",
            (_port("/dev/ttyUSB0", 0x067B, 0x23A3),),
            SerialPortValidationReason.IDENTITY_MISMATCH,
        ),
        (
            "/dev/ttyUSB0",
            (
                _port("/dev/ttyUSB0", 0x10C4, 0xEA60),
                _port("/dev/ttyUSB0", 0x10C4, 0xEA60),
            ),
            SerialPortValidationReason.CONFLICTING_IDENTITY,
        ),
    ],
)
def test_explicit_log_identity_failures_are_typed(requested, ports, reason):
    with pytest.raises(SerialPortValidationError) as caught:
        resolve_explicit_usb_serial_port(
            requested,
            expected_vid_pid=MCU_LOG_EXPECTED_VID_PID,
            port_infos=ports,
            aliases_by_device={},
        )

    assert caught.value.reason is reason


def test_resolver_never_falls_back_to_first_cp2102_device():
    with pytest.raises(SerialPortValidationError) as caught:
        resolve_explicit_usb_serial_port(
            "/dev/serial/by-id/not-present",
            expected_vid_pid=MCU_LOG_EXPECTED_VID_PID,
            port_infos=(_port("/dev/ttyUSB0", 0x10C4, 0xEA60),),
            aliases_by_device={},
        )

    assert caught.value.reason is SerialPortValidationReason.DEVICE_NOT_FOUND


def test_model_log_port_default_is_backward_compatible_without_mutation():
    settings = {"MACHINE_PORT": "/dev/ttyAMA0"}
    model = SimpleNamespace(profile=CURRENT_PROFILE, settings=settings)

    assert Model.get_default_machine_log_port(model) == DEFAULT_CURRENT_MCU_LOG_PORT
    assert "MACHINE_LOG_PORT" not in settings

    model.settings["MACHINE_LOG_PORT"] = ""
    assert Model.get_default_machine_log_port(model) == ""

    model.profile = LEGACY_PROFILE
    assert Model.get_default_machine_log_port(model) is None


def test_constructing_machine_does_not_resolve_or_open_log_port(qapp):
    calls = []

    machine = mfr.Machine(
        SimpleNamespace(),
        profile=SimpleNamespace(
            name="current",
            has_refuel_camera=False,
            has_droplet_camera=False,
            has_log_channel=True,
        ),
        serial_factory=lambda *_args, **_kwargs: calls.append("open"),
        machine_log_port=DEFAULT_CURRENT_MCU_LOG_PORT,
        serial_identity_resolver=lambda *_args, **_kwargs: calls.append(
            "resolve"
        ),
    )

    assert machine.get_machine_log_port() == DEFAULT_CURRENT_MCU_LOG_PORT
    assert calls == []


@pytest.mark.parametrize("configured_port", [None, "", 123])
def test_invalid_machine_log_configuration_fails_before_resolution_or_open(
    qapp,
    configured_port,
):
    calls = []
    machine = mfr.Machine(
        SimpleNamespace(),
        profile=SimpleNamespace(
            name="current",
            has_refuel_camera=False,
            has_droplet_camera=False,
            has_log_channel=True,
        ),
        serial_factory=lambda *_args, **_kwargs: calls.append("open"),
        machine_log_port=configured_port,
        serial_identity_resolver=lambda *_args, **_kwargs: calls.append(
            "resolve"
        ),
    )
    errors = []
    machine.error_occurred.connect(errors.append)

    assert machine.begin_log_thread() is False
    assert calls == []
    assert errors and "MACHINE_LOG_PORT" in errors[-1]


class _Signal:
    def __init__(self):
        self.connected = []

    def connect(self, callback):
        self.connected.append(callback)

    def disconnect(self, callback):
        if callback in self.connected:
            self.connected.remove(callback)


class _FakeLogReader:
    def __init__(self, baud, *, log_port, serial_factory):
        self.baud = baud
        self.log_port = log_port
        self.serial_factory = serial_factory
        self.lineReceived = _Signal()
        self.messageReceived = _Signal()
        self.flashStateChanged = _Signal()
        self.start_calls = 0

    def start(self):
        self.start_calls += 1

    def isRunning(self):
        return self.start_calls > 0


def _identity(path=DEFAULT_CURRENT_MCU_LOG_PORT, system_device="/dev/ttyUSB1"):
    return SerialPortIdentity(
        requested_path=path,
        system_device=system_device,
        by_id_paths=(path,),
        vid="10c4",
        pid="ea60",
        vid_pid=MCU_LOG_EXPECTED_VID_PID,
        description="CP2102 USB UART",
        manufacturer="Silicon Labs",
        product="CP2102",
        serial_number="0001",
    )


def test_begin_log_thread_passes_only_validated_explicit_port(qapp):
    opened = []
    resolver_calls = []

    def factory(baud, *, log_port, serial_factory):
        opened.append(log_port)
        return _FakeLogReader(
            baud,
            log_port=log_port,
            serial_factory=serial_factory,
        )

    machine = mfr.Machine(
        SimpleNamespace(),
        profile=SimpleNamespace(
            name="current",
            has_refuel_camera=False,
            has_droplet_camera=False,
            has_log_channel=True,
        ),
        machine_log_port=DEFAULT_CURRENT_MCU_LOG_PORT,
        log_reader_factory=factory,
        serial_identity_resolver=lambda path, **kwargs: (
            resolver_calls.append((path, kwargs["expected_vid_pid"])),
            _identity(),
        )[1],
    )

    assert machine.begin_log_thread() is True
    assert resolver_calls == [
        (DEFAULT_CURRENT_MCU_LOG_PORT, MCU_LOG_EXPECTED_VID_PID)
    ]
    assert opened == [DEFAULT_CURRENT_MCU_LOG_PORT]
    assert machine.log_reader.start_calls == 1
    assert machine.get_resolved_machine_log_port() == "/dev/ttyUSB1"


def test_log_reader_requires_explicit_port_without_opening_serial(qapp):
    opens = []
    with pytest.raises(TypeError):
        mfr.LogReader(serial_factory=lambda *_args, **_kwargs: opens.append(True))
    assert opens == []


class _CommandSerial:
    def __init__(self):
        self.is_open = True
        self.close_calls = 0
        self.name = "/dev/ttyAMA0"

    def close(self):
        self.close_calls += 1
        self.is_open = False


def test_hello_ack_fails_closed_when_log_identity_is_invalid(qapp):
    error = SerialPortValidationError(
        SerialPortValidationReason.IDENTITY_MISMATCH,
        "observed Prolific adapter",
        requested_path=DEFAULT_CURRENT_MCU_LOG_PORT,
        expected_vid_pid=MCU_LOG_EXPECTED_VID_PID,
        observed_vid_pid="067b:23a3",
    )
    machine = mfr.Machine(
        SimpleNamespace(),
        profile=SimpleNamespace(
            name="current",
            has_refuel_camera=False,
            has_droplet_camera=False,
            has_log_channel=True,
        ),
        machine_log_port=DEFAULT_CURRENT_MCU_LOG_PORT,
        serial_identity_resolver=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            error
        ),
    )
    command_serial = _CommandSerial()
    machine.ser = command_serial
    machine.port = "/dev/ttyAMA0"
    connected = []
    errors = []
    flash_states = []
    machine.machine_connected_signal.connect(connected.append)
    machine.error_occurred.connect(errors.append)
    machine.flash_state_updated.connect(flash_states.append)

    machine._on_hello_ack({"capabilities": mfr.REQUIRED_TRANSPORT_CAPS})

    assert connected == [False]
    assert errors and MCU_LOG_EXPECTED_VID_PID in errors[-1]
    assert "067b:23a3" in errors[-1]
    assert machine._transport_ready is False
    assert machine._command_queue_blocked_reason == "mcu_log_unavailable"
    assert machine.execution_timer.isActive() is False
    assert machine.ser is None
    assert machine.port is None
    assert command_serial.close_calls == 1
    assert flash_states[-1]["flash_session_armed"] is False


def test_hello_ack_marks_transport_ready_only_after_valid_log_start(qapp):
    machine = mfr.Machine(
        SimpleNamespace(),
        profile=SimpleNamespace(
            name="current",
            has_refuel_camera=False,
            has_droplet_camera=False,
            has_log_channel=True,
        ),
        machine_log_port=DEFAULT_CURRENT_MCU_LOG_PORT,
        log_reader_factory=_FakeLogReader,
        serial_identity_resolver=lambda *_args, **_kwargs: _identity(),
    )
    command_serial = _CommandSerial()
    machine.ser = command_serial
    machine.port = "/dev/ttyAMA0"
    connected = []
    machine.machine_connected_signal.connect(connected.append)

    machine._on_hello_ack({"capabilities": mfr.REQUIRED_TRANSPORT_CAPS})

    assert connected == [True]
    assert machine._transport_ready is True
    assert machine.execution_timer.isActive() is True
    assert machine.log_reader.start_calls == 1
    assert machine.log_reader.log_port == DEFAULT_CURRENT_MCU_LOG_PORT

    machine.execution_timer.stop()
    machine._stop_mcu_response_watchdog()


def test_log_open_failure_is_reported_without_transport_readiness(qapp):
    machine = mfr.Machine(
        SimpleNamespace(),
        profile=SimpleNamespace(
            name="current",
            has_refuel_camera=False,
            has_droplet_camera=False,
            has_log_channel=True,
        ),
        machine_log_port=DEFAULT_CURRENT_MCU_LOG_PORT,
        log_reader_factory=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("injected open failure")
        ),
        serial_identity_resolver=lambda *_args, **_kwargs: _identity(),
    )
    errors = []
    machine.error_occurred.connect(errors.append)

    assert machine.begin_log_thread() is False
    assert machine.log_reader is None
    assert machine.get_machine_log_port_identity() is None
    assert errors and "injected open failure" in errors[-1]
