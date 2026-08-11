from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path

import pytest

import BalanceService as balance_service_module
from BalanceProtocol import (
    StabilityPolicy,
    StableMassFailureReason,
    StableMassOutcome,
    StableMassPhase,
    StableMassRequest,
)
from BalanceService import (
    BalanceCommandRejectReason,
    BalanceConnectionState,
    BalanceSerialSettings,
    BalanceService,
    BalanceServiceErrorCode,
    open_hpb_serial_transport,
)


NS = 1_000_000_000
STABLE_10_MG = b"    10.00 mgS"
UNSTABLE_10_MG = b"    10.00 mg "


class IncrementingClock:
    def __init__(self, *, start=0, step=100_000_000):
        self._value = start
        self._step = step
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            value = self._value
            self._value += self._step
            return value


class FakeTransport:
    def __init__(self, *, close_error=None):
        self.items = queue.Queue()
        self.read_thread_ids = []
        self.read_sizes = []
        self.close_count = 0
        self.close_thread_id = None
        self.close_error = close_error

    def read(self, size):
        self.read_thread_ids.append(threading.get_ident())
        self.read_sizes.append(size)
        try:
            item = self.items.get(timeout=0.01)
        except queue.Empty:
            return b""
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self):
        self.close_count += 1
        self.close_thread_id = threading.get_ident()
        if self.close_error is not None:
            raise self.close_error


class FakeFactory:
    def __init__(self, transport=None, *, open_error=None, open_gate=None):
        self.transport = transport or FakeTransport()
        self.open_error = open_error
        self.open_gate = open_gate
        self.calls = []
        self.thread_ids = []

    def __call__(self, settings):
        self.calls.append(settings)
        self.thread_ids.append(threading.get_ident())
        if self.open_gate is not None:
            self.open_gate.wait(timeout=2)
        if self.open_error is not None:
            raise self.open_error
        return self.transport


def _wait(qapp, predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.002)
    qapp.processEvents()
    assert predicate(), "condition was not reached before timeout"


def _request(request_id="request-1", *, started_ns=0, policy=None):
    return StableMassRequest(
        request_id=request_id,
        stream_session_id="stream-1",
        phase=StableMassPhase.STARTING,
        started_monotonic_ns=started_ns,
        policy=policy or StabilityPolicy(),
    )


def _quick_policy(*, timeout_ns=100 * NS):
    return StabilityPolicy(
        ignore_period_ns=0,
        minimum_window_ns=1,
        minimum_samples=2,
        timeout_ns=timeout_ns,
    )


def _connect_streaming(qapp, service, factory, port="/dev/serial/by-id/hpb"):
    assert service.connect_balance(port).accepted
    _wait(qapp, lambda: service.connection_snapshot.state is BalanceConnectionState.STREAMING)
    assert len(factory.calls) == 1


def _disconnect(qapp, service):
    if service.connection_snapshot.state is BalanceConnectionState.ERROR:
        service.disconnect_balance()
        _wait(qapp, lambda: not service.worker_running)
        service.disconnect_balance()
    elif service.connection_snapshot.state not in (
        BalanceConnectionState.DISCONNECTED,
        BalanceConnectionState.CLOSED,
    ):
        service.disconnect_balance()
        _wait(
            qapp,
            lambda: service.connection_snapshot.state
            in (BalanceConnectionState.DISCONNECTED, BalanceConnectionState.ERROR),
        )


def test_construct_and_invalid_port_do_not_open_transport(qapp):
    factory = FakeFactory()
    service = BalanceService(transport_factory=factory)

    assert service.connection_snapshot.state is BalanceConnectionState.DISCONNECTED
    result = service.connect_balance("  ")

    assert result.accepted is False
    assert result.rejection_reason is BalanceCommandRejectReason.INVALID_ARGUMENT
    assert factory.calls == []
    assert service.close().accepted


def test_open_and_reads_run_off_caller_with_exact_receive_only_settings(qapp):
    caller_thread = threading.get_ident()
    factory = FakeFactory()
    service = BalanceService(transport_factory=factory)
    try:
        _connect_streaming(qapp, service, factory)
        _wait(qapp, lambda: bool(factory.transport.read_thread_ids))

        settings = factory.calls[0]
        assert settings == BalanceSerialSettings("/dev/serial/by-id/hpb")
        assert settings.baud_rate == 9600
        assert settings.read_size == 64
        assert settings.read_timeout_seconds == 0.1
        assert (settings.data_bits, settings.parity, settings.stop_bits) == (8, "N", 1)
        assert settings.software_flow_control is False
        assert settings.hardware_flow_control is False
        assert settings.dsr_dtr_flow_control is False
        assert factory.thread_ids[0] != caller_thread
        assert set(factory.transport.read_thread_ids) == {factory.thread_ids[0]}
        assert set(factory.transport.read_sizes) == {64}
        assert not hasattr(factory.transport, "write")
    finally:
        _disconnect(qapp, service)
        assert service.close().accepted
    assert factory.transport.close_count == 1
    assert factory.transport.close_thread_id == factory.thread_ids[0]


def test_connect_returns_while_worker_factory_is_blocked(qapp):
    gate = threading.Event()
    factory = FakeFactory(open_gate=gate)
    service = BalanceService(transport_factory=factory)
    try:
        started = time.monotonic()
        result = service.connect_balance("/dev/serial/by-id/hpb")
        elapsed = time.monotonic() - started

        assert result.accepted
        assert elapsed < 0.1
        assert service.connection_snapshot.state is BalanceConnectionState.CONNECTING
        gate.set()
        _wait(qapp, lambda: service.connection_snapshot.state is BalanceConnectionState.STREAMING)
    finally:
        gate.set()
        _disconnect(qapp, service)
        assert service.close().accepted


def test_fragmented_multiple_and_malformed_records_drive_stable_result(qapp):
    clock = IncrementingClock(step=10_000_000)
    factory = FakeFactory()
    service = BalanceService(transport_factory=factory, monotonic_ns=clock)
    readings = []
    progress = []
    results = []
    service.reading_received.connect(readings.append)
    service.request_progress.connect(progress.append)
    service.request_finished.connect(results.append)
    try:
        _connect_streaming(qapp, service, factory)
        assert service.request_stable_mass(
            _request(policy=_quick_policy())
        ).accepted
        factory.transport.items.put(b"bad\r\n" + STABLE_10_MG + b"\r")
        factory.transport.items.put(b"\n" + STABLE_10_MG + b"\r\n")
        factory.transport.items.put(STABLE_10_MG + b"\r\n")

        _wait(qapp, lambda: bool(results))

        result = results[0]
        assert result.outcome is StableMassOutcome.STABLE
        assert result.stable_mass_mg == 10
        assert len(readings) == 3
        assert len(progress) == 3
        assert all(item.request.request_id == "request-1" for item in progress)
        diagnostics = service.diagnostics_snapshot()
        assert diagnostics.accepted_reading_count == 3
        assert diagnostics.record_rejection_count == 1
    finally:
        _disconnect(qapp, service)
        assert service.close().accepted


def test_physical_stable_loaded_fixture_replays_through_service(qapp):
    fixture_path = (
        Path(__file__).parent
        / "fixtures"
        / "veritas_balance"
        / "hpb625i_serial_samples_v1.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    capture = next(item for item in fixture["captures"] if item["id"] == "stable_loaded")
    factory = FakeFactory()
    clock = IncrementingClock(step=10_000_000)
    service = BalanceService(transport_factory=factory, monotonic_ns=clock)
    results = []
    service.request_finished.connect(results.append)
    try:
        _connect_streaming(qapp, service, factory)
        policy = StabilityPolicy(
            ignore_period_ns=0,
            minimum_window_ns=80_000_000,
            minimum_samples=5,
            timeout_ns=100 * NS,
        )
        assert service.request_stable_mass(_request(policy=policy)).accepted
        for chunk_hex in capture["chunks_hex"]:
            factory.transport.items.put(bytes.fromhex(chunk_hex))

        _wait(qapp, lambda: bool(results))

        assert results[0].outcome is StableMassOutcome.STABLE
        assert str(results[0].stable_mass_mg) == "1540.57"
        assert results[0].evidence.sample_count == 5
    finally:
        _disconnect(qapp, service)
        assert service.close().accepted


def test_empty_reads_poll_request_to_timeout(qapp):
    clock = IncrementingClock(step=NS)
    factory = FakeFactory()
    service = BalanceService(transport_factory=factory, monotonic_ns=clock)
    results = []
    service.request_finished.connect(results.append)
    try:
        _connect_streaming(qapp, service, factory)
        request = _request(
            started_ns=0,
            policy=StabilityPolicy(
                ignore_period_ns=0,
                minimum_window_ns=NS,
                minimum_samples=2,
                timeout_ns=30 * NS,
            ),
        )
        assert service.request_stable_mass(request).accepted

        _wait(qapp, lambda: bool(results))

        assert results[0].outcome is StableMassOutcome.TIMEOUT
        assert results[0].total_readings_seen == 0
        assert service.diagnostics_snapshot().chunk_count == 0
    finally:
        _disconnect(qapp, service)
        assert service.close().accepted


def test_request_identity_duplicate_cancel_and_reuse_contract(qapp):
    factory = FakeFactory()
    service = BalanceService(transport_factory=factory)
    results = []
    service.request_finished.connect(results.append)
    try:
        _connect_streaming(qapp, service, factory)
        request = _request(started_ns=time.monotonic_ns())
        assert service.request_stable_mass(request).accepted
        old_connection_generation = service._connection_generation
        old_request_generation = service._active_request_generation
        assert (
            service.request_stable_mass(_request("request-2")).rejection_reason
            is BalanceCommandRejectReason.REQUEST_ALREADY_ACTIVE
        )
        assert (
            service.cancel_stable_mass("wrong-id").rejection_reason
            is BalanceCommandRejectReason.REQUEST_ID_MISMATCH
        )
        assert service.cancel_stable_mass(request.request_id).accepted
        assert service.cancel_stable_mass(request.request_id).accepted
        _wait(qapp, lambda: bool(results))
        assert results[0].outcome is StableMassOutcome.CANCELLED
        assert service.active_request_id is None
        assert (
            service.request_stable_mass(request).rejection_reason
            is BalanceCommandRejectReason.INVALID_ARGUMENT
        )
        replacement = _request("request-2", started_ns=time.monotonic_ns())
        assert service.request_stable_mass(replacement).accepted
        service._on_worker_result(
            balance_service_module._WorkerResultEvent(
                old_connection_generation,
                old_request_generation,
                results[0],
            )
        )
        assert service.active_request_id == replacement.request_id
        assert len(results) == 1
        assert service.cancel_stable_mass(replacement.request_id).accepted
        _wait(qapp, lambda: len(results) == 2)
        assert results[1].request_id == replacement.request_id
    finally:
        _disconnect(qapp, service)
        assert service.close().accepted


def test_disconnect_cancels_active_request_and_is_idempotent(qapp):
    factory = FakeFactory()
    service = BalanceService(transport_factory=factory)
    results = []
    service.request_finished.connect(results.append)
    _connect_streaming(qapp, service, factory)
    assert service.request_stable_mass(
        _request(started_ns=time.monotonic_ns())
    ).accepted

    assert service.disconnect_balance().accepted
    assert service.disconnect_balance().accepted
    _wait(qapp, lambda: service.connection_snapshot.state is BalanceConnectionState.DISCONNECTED)

    assert len(results) == 1
    assert results[0].outcome is StableMassOutcome.CANCELLED
    assert factory.transport.close_count == 1
    assert service.disconnect_balance().accepted
    assert service.close().accepted
    assert service.close().accepted


def test_open_failure_can_close_without_explicit_error_reset(qapp):
    factory = FakeFactory(open_error=OSError("permission denied"))
    service = BalanceService(transport_factory=factory)
    errors = []
    service.error_occurred.connect(errors.append)
    try:
        assert service.connect_balance("/dev/serial/by-id/hpb").accepted
        _wait(qapp, lambda: service.connection_snapshot.state is BalanceConnectionState.ERROR)
        _wait(qapp, lambda: not service.worker_running)

        assert errors[0].code is BalanceServiceErrorCode.TRANSPORT_OPEN_FAILED
        assert (
            service.connect_balance("/dev/serial/by-id/hpb").rejection_reason
            is BalanceCommandRejectReason.INVALID_STATE
        )
        assert service.close().accepted
        assert service.connection_snapshot.state is BalanceConnectionState.CLOSED
    finally:
        if service.connection_snapshot.state is BalanceConnectionState.ERROR:
            service.close()
        _wait(qapp, lambda: not service.worker_running)
        qapp.processEvents()
        assert service.close().accepted


def test_read_failure_emits_typed_error_and_terminal_transport_result(qapp):
    factory = FakeFactory()
    service = BalanceService(transport_factory=factory)
    errors = []
    results = []
    service.error_occurred.connect(errors.append)
    service.request_finished.connect(results.append)
    try:
        _connect_streaming(qapp, service, factory)
        request = _request(started_ns=time.monotonic_ns())
        assert service.request_stable_mass(request).accepted
        factory.transport.items.put(OSError("USB disconnected"))

        _wait(qapp, lambda: service.connection_snapshot.state is BalanceConnectionState.ERROR)
        _wait(qapp, lambda: bool(results) and bool(errors))

        assert results[0].outcome is StableMassOutcome.ERROR
        assert results[0].failure_reason is StableMassFailureReason.TRANSPORT_ERROR
        assert errors[0].code is BalanceServiceErrorCode.TRANSPORT_READ_FAILED
        assert errors[0].request_id == request.request_id
    finally:
        _wait(qapp, lambda: not service.worker_running)
        qapp.processEvents()
        assert service.close().accepted


def test_invalid_transport_data_terminates_request_as_service_error(qapp):
    factory = FakeFactory()
    service = BalanceService(transport_factory=factory)
    errors = []
    results = []
    service.error_occurred.connect(errors.append)
    service.request_finished.connect(results.append)
    try:
        _connect_streaming(qapp, service, factory)
        request = _request(started_ns=time.monotonic_ns())
        assert service.request_stable_mass(request).accepted
        factory.transport.items.put("not bytes")

        _wait(qapp, lambda: bool(results) and bool(errors))

        assert results[0].outcome is StableMassOutcome.ERROR
        assert results[0].failure_reason is StableMassFailureReason.SERVICE_ERROR
        assert errors[0].code is BalanceServiceErrorCode.WORKER_FAILURE
        assert errors[0].request_id == request.request_id
    finally:
        _wait(qapp, lambda: not service.worker_running)
        service.disconnect_balance()
        qapp.processEvents()
        assert service.close().accepted


def test_transport_close_failure_is_typed_and_service_can_close(qapp):
    transport = FakeTransport(close_error=OSError("close failed"))
    factory = FakeFactory(transport)
    service = BalanceService(transport_factory=factory)
    errors = []
    service.error_occurred.connect(errors.append)
    _connect_streaming(qapp, service, factory)

    assert service.disconnect_balance().accepted
    _wait(qapp, lambda: service.connection_snapshot.state is BalanceConnectionState.ERROR)
    _wait(qapp, lambda: not service.worker_running)

    assert any(error.code is BalanceServiceErrorCode.TRANSPORT_CLOSE_FAILED for error in errors)
    assert transport.close_count == 1
    qapp.processEvents()
    assert service.close().accepted
    assert service.connection_snapshot.state is BalanceConnectionState.CLOSED


def test_diagnostics_are_bounded_and_incomplete_tail_is_flushed(qapp):
    factory = FakeFactory()
    service = BalanceService(transport_factory=factory)
    _connect_streaming(qapp, service, factory)
    for _ in range(40):
        factory.transport.items.put(b"bad\r\n")
    factory.transport.items.put(b"x" * 300 + b"\r\n")
    factory.transport.items.put(b"partial")
    _wait(qapp, lambda: service.diagnostics_snapshot().record_rejection_count >= 40)
    _wait(qapp, lambda: service.diagnostics_snapshot().byte_count >= 300)

    service.disconnect_balance()
    _wait(qapp, lambda: service.connection_snapshot.state is BalanceConnectionState.DISCONNECTED)
    diagnostics = service.diagnostics_snapshot()

    assert diagnostics.frame_rejection_count >= 2
    assert len(diagnostics.recent_rejections) <= 32
    assert all(len(item.raw_payload) <= 256 for item in diagnostics.recent_rejections)
    assert factory.transport.close_count == 1
    assert service.close().accepted


def test_shutdown_timeout_does_not_force_terminate_worker(qapp):
    gate = threading.Event()
    factory = FakeFactory(open_gate=gate)
    service = BalanceService(transport_factory=factory)
    errors = []
    service.error_occurred.connect(errors.append)
    try:
        assert service.connect_balance("/dev/serial/by-id/hpb").accepted
        _wait(qapp, lambda: bool(factory.thread_ids))

        result = service.close(wait_timeout_ms=10)

        assert result.accepted is False
        assert service.connection_snapshot.state is BalanceConnectionState.ERROR
        assert errors[-1].code is BalanceServiceErrorCode.SHUTDOWN_TIMEOUT
        assert "terminate(" not in Path(balance_service_module.__file__).read_text(encoding="utf-8")
    finally:
        gate.set()
        _wait(qapp, lambda: not service.worker_running)
        qapp.processEvents()
        assert service.close().accepted
        assert service.connection_snapshot.state is BalanceConnectionState.CLOSED


def test_repeated_connection_cycles_leave_no_worker_or_open_transport(qapp):
    transports = []

    def factory(_settings):
        transport = FakeTransport()
        transports.append(transport)
        return transport

    service = BalanceService(transport_factory=factory)
    for index in range(3):
        assert service.connect_balance(f"/dev/hpb-{index}").accepted
        _wait(qapp, lambda: service.connection_snapshot.state is BalanceConnectionState.STREAMING)
        assert service.disconnect_balance().accepted
        _wait(qapp, lambda: service.connection_snapshot.state is BalanceConnectionState.DISCONNECTED)
        _wait(qapp, lambda: not service.worker_running)
    assert service.close().accepted

    assert len(transports) == 3
    assert all(transport.close_count == 1 for transport in transports)
    assert service.worker_running is False


def test_production_factory_passes_exact_pyserial_arguments(monkeypatch):
    import serial

    calls = []
    sentinel = object()

    def fake_serial(**kwargs):
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(serial, "Serial", fake_serial)
    settings = BalanceSerialSettings("COM9")

    assert open_hpb_serial_transport(settings) is sentinel
    assert calls == [
        {
            "port": "COM9",
            "baudrate": 9600,
            "bytesize": 8,
            "parity": "N",
            "stopbits": 1,
            "timeout": 0.1,
            "xonxoff": False,
            "rtscts": False,
            "dsrdtr": False,
        }
    ]


def test_service_layer_has_no_application_or_hardware_control_imports():
    source = Path(balance_service_module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "Controller",
        "Model",
        "View",
        "ApplicationComposition",
        "Machine_FreeRTOS",
        "legacy",
        "firmware",
        "simulation",
        ".write(",
    ):
        assert forbidden not in source
