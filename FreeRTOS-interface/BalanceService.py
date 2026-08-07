"""Nonblocking, receive-only service for the Veritas HPB balance.

This module is intentionally not composed into the application yet.  It owns
only the balance serial stream and delegates framing, parsing, and stability
decisions to :mod:`BalanceProtocol`.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from PySide6 import QtCore

from BalanceProtocol import (
    BalanceReading,
    CrlfFramer,
    FrameEventKind,
    StabilityDetector,
    StabilityEvidence,
    StableMassFailureReason,
    StableMassRequest,
    StableMassResult,
    parse_hpb_record,
)


HPB_BAUD_RATE = 9600
HPB_READ_SIZE = 64
HPB_READ_TIMEOUT_SECONDS = 0.1
HPB_FRAME_BUFFER_BYTES = 256
MAX_RECENT_REJECTIONS = 32
MAX_RECENT_REQUEST_IDS = 64
WORKER_COMMAND_QUEUE_SIZE = 8


class BalanceConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    STREAMING = "streaming"
    DISCONNECTING = "disconnecting"
    ERROR = "error"
    CLOSED = "closed"


class BalanceCommandRejectReason(str, Enum):
    NONE = "none"
    INVALID_ARGUMENT = "invalid_argument"
    INVALID_STATE = "invalid_state"
    REQUEST_ALREADY_ACTIVE = "request_already_active"
    NO_ACTIVE_REQUEST = "no_active_request"
    REQUEST_ID_MISMATCH = "request_id_mismatch"
    SERVICE_CLOSED = "service_closed"


class BalanceServiceErrorCode(str, Enum):
    TRANSPORT_OPEN_FAILED = "transport_open_failed"
    TRANSPORT_READ_FAILED = "transport_read_failed"
    TRANSPORT_CLOSE_FAILED = "transport_close_failed"
    WORKER_FAILURE = "worker_failure"
    SHUTDOWN_TIMEOUT = "shutdown_timeout"


@dataclass(frozen=True)
class BalanceCommandResult:
    accepted: bool
    rejection_reason: BalanceCommandRejectReason = BalanceCommandRejectReason.NONE
    detail: str = ""

    def __post_init__(self) -> None:
        if self.accepted and self.rejection_reason is not BalanceCommandRejectReason.NONE:
            raise ValueError("accepted command cannot carry a rejection reason")
        if not self.accepted and self.rejection_reason is BalanceCommandRejectReason.NONE:
            raise ValueError("rejected command requires a rejection reason")
        object.__setattr__(self, "detail", str(self.detail))


@dataclass(frozen=True)
class BalanceSerialSettings:
    port: str
    baud_rate: int = HPB_BAUD_RATE
    read_size: int = HPB_READ_SIZE
    read_timeout_seconds: float = HPB_READ_TIMEOUT_SECONDS
    data_bits: int = 8
    parity: str = "N"
    stop_bits: int = 1
    software_flow_control: bool = False
    hardware_flow_control: bool = False
    dsr_dtr_flow_control: bool = False

    def __post_init__(self) -> None:
        port = str(self.port).strip()
        if not port:
            raise ValueError("balance serial port must be explicit")
        if self.baud_rate != HPB_BAUD_RATE:
            raise ValueError("HPB balance baud rate must be 9600")
        if self.read_size != HPB_READ_SIZE:
            raise ValueError("HPB balance read size must be 64 bytes")
        if self.read_timeout_seconds != HPB_READ_TIMEOUT_SECONDS:
            raise ValueError("HPB balance read timeout must be 0.1 seconds")
        if (self.data_bits, self.parity, self.stop_bits) != (8, "N", 1):
            raise ValueError("HPB balance framing must be 8-N-1")
        if any(
            (
                self.software_flow_control,
                self.hardware_flow_control,
                self.dsr_dtr_flow_control,
            )
        ):
            raise ValueError("HPB balance flow control must be disabled")
        object.__setattr__(self, "port", port)


@dataclass(frozen=True)
class BalanceConnectionSnapshot:
    state: BalanceConnectionState
    port: str | None
    connection_generation: int
    timestamp_ns: int
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.state, BalanceConnectionState):
            raise TypeError("connection state must be BalanceConnectionState")
        if self.connection_generation < 0 or self.timestamp_ns < 0:
            raise ValueError("connection generation and timestamp must be nonnegative")


@dataclass(frozen=True)
class BalanceServiceError:
    code: BalanceServiceErrorCode
    timestamp_ns: int
    connection_generation: int
    port: str | None
    request_id: str | None
    exception_type: str
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, BalanceServiceErrorCode):
            raise TypeError("service error code must be BalanceServiceErrorCode")
        if self.timestamp_ns < 0 or self.connection_generation < 0:
            raise ValueError("error timestamp and generation must be nonnegative")
        if not str(self.exception_type).strip():
            raise ValueError("service error requires an exception type")


@dataclass(frozen=True)
class BalanceRequestProgress:
    connection_generation: int
    request_generation: int
    request: StableMassRequest
    latest_reading: BalanceReading
    evidence: StabilityEvidence | None
    elapsed_ns: int
    retained_sample_count: int

    def __post_init__(self) -> None:
        if self.connection_generation < 0 or self.request_generation < 0:
            raise ValueError("progress generations must be nonnegative")
        if not isinstance(self.request, StableMassRequest):
            raise TypeError("progress request must be StableMassRequest")
        if not isinstance(self.latest_reading, BalanceReading):
            raise TypeError("progress latest_reading must be BalanceReading")
        if self.evidence is not None and not isinstance(
            self.evidence, StabilityEvidence
        ):
            raise TypeError("progress evidence must be StabilityEvidence or None")
        if self.elapsed_ns < 0 or self.retained_sample_count < 0:
            raise ValueError("progress elapsed time and sample count must be nonnegative")


@dataclass(frozen=True)
class BalanceDiagnosticRecord:
    timestamp_ns: int
    category: str
    reason: str
    raw_payload: bytes

    def __post_init__(self) -> None:
        if self.timestamp_ns < 0:
            raise ValueError("diagnostic timestamp must be nonnegative")
        if len(self.raw_payload) > HPB_FRAME_BUFFER_BYTES:
            raise ValueError("diagnostic payload exceeds the framing bound")
        if self.category not in ("frame", "record"):
            raise ValueError("diagnostic category must be frame or record")
        if not isinstance(self.raw_payload, bytes):
            raise TypeError("diagnostic payload must be bytes")


@dataclass(frozen=True)
class BalanceDiagnosticsSnapshot:
    byte_count: int = 0
    chunk_count: int = 0
    frame_count: int = 0
    accepted_reading_count: int = 0
    frame_rejection_count: int = 0
    record_rejection_count: int = 0
    recent_rejections: tuple[BalanceDiagnosticRecord, ...] = ()

    def __post_init__(self) -> None:
        counts = (
            self.byte_count,
            self.chunk_count,
            self.frame_count,
            self.accepted_reading_count,
            self.frame_rejection_count,
            self.record_rejection_count,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counts
        ):
            raise ValueError("diagnostic counts must be nonnegative integers")
        if not isinstance(self.recent_rejections, tuple):
            raise TypeError("recent rejections must be a tuple")
        if len(self.recent_rejections) > MAX_RECENT_REJECTIONS:
            raise ValueError("recent rejection history exceeds its bound")


class BalanceTransport(Protocol):
    def read(self, size: int) -> bytes: ...

    def close(self) -> None: ...


BalanceTransportFactory = Callable[[BalanceSerialSettings], BalanceTransport]
MonotonicClock = Callable[[], int]


def open_hpb_serial_transport(settings: BalanceSerialSettings) -> BalanceTransport:
    """Open the verified HPB receive-only serial configuration."""
    import serial

    return serial.Serial(
        port=settings.port,
        baudrate=settings.baud_rate,
        bytesize=settings.data_bits,
        parity=settings.parity,
        stopbits=settings.stop_bits,
        timeout=settings.read_timeout_seconds,
        xonxoff=settings.software_flow_control,
        rtscts=settings.hardware_flow_control,
        dsrdtr=settings.dsr_dtr_flow_control,
    )


def _accepted(detail: str = "") -> BalanceCommandResult:
    return BalanceCommandResult(True, detail=detail)


def _rejected(
    reason: BalanceCommandRejectReason, detail: str
) -> BalanceCommandResult:
    return BalanceCommandResult(False, rejection_reason=reason, detail=detail)


def _safe_exception_detail(exc: BaseException) -> str:
    return " ".join(str(exc).split())[:512] or exc.__class__.__name__


def _thread_is_running(thread: QtCore.QThread | None) -> bool:
    if thread is None:
        return False
    try:
        return thread.isRunning()
    except RuntimeError:
        return False


class _WorkerCommandKind(str, Enum):
    START = "start"
    CANCEL = "cancel"


@dataclass(frozen=True)
class _WorkerCommand:
    kind: _WorkerCommandKind
    request_generation: int
    request: StableMassRequest | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class _WorkerReadingEvent:
    connection_generation: int
    reading: BalanceReading


@dataclass(frozen=True)
class _WorkerResultEvent:
    connection_generation: int
    request_generation: int
    result: StableMassResult


@dataclass(frozen=True)
class _WorkerFinishedEvent:
    connection_generation: int
    requested_stop: bool
    had_error: bool
    diagnostics: BalanceDiagnosticsSnapshot


class _MutableDiagnostics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.byte_count = 0
        self.chunk_count = 0
        self.frame_count = 0
        self.accepted_reading_count = 0
        self.frame_rejection_count = 0
        self.record_rejection_count = 0
        self.recent_rejections: deque[BalanceDiagnosticRecord] = deque(
            maxlen=MAX_RECENT_REJECTIONS
        )

    def add_chunk(self, chunk: bytes) -> None:
        with self._lock:
            self.byte_count += len(chunk)
            self.chunk_count += 1

    def add_frame(self) -> None:
        with self._lock:
            self.frame_count += 1

    def add_reading(self) -> None:
        with self._lock:
            self.accepted_reading_count += 1

    def add_rejection(
        self, *, timestamp_ns: int, category: str, reason: str, payload: bytes
    ) -> None:
        record = BalanceDiagnosticRecord(
            timestamp_ns=timestamp_ns,
            category=category,
            reason=reason,
            raw_payload=bytes(payload[:HPB_FRAME_BUFFER_BYTES]),
        )
        with self._lock:
            if category == "frame":
                self.frame_rejection_count += 1
            else:
                self.record_rejection_count += 1
            self.recent_rejections.append(record)

    def snapshot(self) -> BalanceDiagnosticsSnapshot:
        with self._lock:
            return BalanceDiagnosticsSnapshot(
                byte_count=self.byte_count,
                chunk_count=self.chunk_count,
                frame_count=self.frame_count,
                accepted_reading_count=self.accepted_reading_count,
                frame_rejection_count=self.frame_rejection_count,
                record_rejection_count=self.record_rejection_count,
                recent_rejections=tuple(self.recent_rejections),
            )


class _BalanceSerialWorker(QtCore.QObject):
    opened = QtCore.Signal(object)
    reading = QtCore.Signal(object)
    progress = QtCore.Signal(object)
    result = QtCore.Signal(object)
    fault = QtCore.Signal(object)
    finished = QtCore.Signal(object)
    thread_done = QtCore.Signal()

    def __init__(
        self,
        *,
        settings: BalanceSerialSettings,
        connection_generation: int,
        transport_factory: BalanceTransportFactory,
        monotonic_ns: MonotonicClock,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.connection_generation = connection_generation
        self._transport_factory = transport_factory
        self._monotonic_ns = monotonic_ns
        self._commands: queue.Queue[_WorkerCommand] = queue.Queue(
            maxsize=WORKER_COMMAND_QUEUE_SIZE
        )
        self._stop_requested = threading.Event()
        self._diagnostics = _MutableDiagnostics()
        self._framer = CrlfFramer(max_buffer_bytes=HPB_FRAME_BUFFER_BYTES)
        self._detector: StabilityDetector | None = None
        self._request_generation: int | None = None

    def enqueue_request(
        self, request: StableMassRequest, request_generation: int
    ) -> bool:
        try:
            self._commands.put_nowait(
                _WorkerCommand(
                    _WorkerCommandKind.START,
                    request_generation,
                    request=request,
                )
            )
        except queue.Full:
            return False
        return True

    def enqueue_cancel(self, request_id: str, request_generation: int) -> bool:
        try:
            self._commands.put_nowait(
                _WorkerCommand(
                    _WorkerCommandKind.CANCEL,
                    request_generation,
                    request_id=request_id,
                )
            )
        except queue.Full:
            return False
        return True

    def request_stop(self) -> None:
        self._stop_requested.set()

    def diagnostics_snapshot(self) -> BalanceDiagnosticsSnapshot:
        return self._diagnostics.snapshot()

    def _now(self) -> int:
        value = self._monotonic_ns()
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("monotonic clock must return a nonnegative integer")
        return value

    def _error(
        self, code: BalanceServiceErrorCode, exc: BaseException, now_ns: int
    ) -> BalanceServiceError:
        request_id = self._detector.request.request_id if self._detector else None
        return BalanceServiceError(
            code=code,
            timestamp_ns=now_ns,
            connection_generation=self.connection_generation,
            port=self.settings.port,
            request_id=request_id,
            exception_type=exc.__class__.__name__,
            detail=_safe_exception_detail(exc),
        )

    def _emit_result(self, result: StableMassResult) -> None:
        if self._request_generation is None:
            return
        self.result.emit(
            _WorkerResultEvent(
                self.connection_generation,
                self._request_generation,
                result,
            )
        )
        self._detector = None
        self._request_generation = None

    def _fail_active(
        self, now_ns: int, reason: StableMassFailureReason, detail: str
    ) -> None:
        if self._detector is None:
            return
        failure_time = max(now_ns, self._detector.request.started_monotonic_ns)
        self._emit_result(self._detector.fail(failure_time, reason, detail))

    def _drain_commands(self, now_ns: int) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return
            if command.kind is _WorkerCommandKind.START and command.request is not None:
                if self._detector is None:
                    self._detector = StabilityDetector(command.request)
                    self._request_generation = command.request_generation
            elif (
                command.kind is _WorkerCommandKind.CANCEL
                and self._detector is not None
                and self._request_generation == command.request_generation
                and self._detector.request.request_id == command.request_id
            ):
                cancel_time = max(
                    now_ns, self._detector.request.started_monotonic_ns
                )
                self._emit_result(self._detector.cancel(cancel_time))

    def _poll_active(self, now_ns: int) -> None:
        if self._detector is None:
            return
        if now_ns < self._detector.request.started_monotonic_ns:
            return
        result = self._detector.poll(now_ns)
        if result is not None:
            self._emit_result(result)

    def _handle_reading(self, reading: BalanceReading) -> None:
        self.reading.emit(_WorkerReadingEvent(self.connection_generation, reading))
        if self._detector is None:
            return
        if reading.timestamp_ns < self._detector.request.started_monotonic_ns:
            return
        detector = self._detector
        request_generation = self._request_generation
        result = detector.add_reading(reading)
        self.progress.emit(
            BalanceRequestProgress(
                connection_generation=self.connection_generation,
                request_generation=request_generation,
                request=detector.request,
                latest_reading=reading,
                evidence=detector.latest_evidence,
                elapsed_ns=reading.timestamp_ns - detector.request.started_monotonic_ns,
                retained_sample_count=detector.retained_sample_count,
            )
        )
        if result is not None:
            self._emit_result(result)

    @QtCore.Slot()
    def run(self) -> None:
        transport: BalanceTransport | None = None
        had_error = False
        try:
            try:
                transport = self._transport_factory(self.settings)
                if not callable(getattr(transport, "read", None)) or not callable(
                    getattr(transport, "close", None)
                ):
                    raise TypeError("transport must provide read() and close()")
            except Exception as exc:
                had_error = True
                self.fault.emit(
                    self._error(
                        BalanceServiceErrorCode.TRANSPORT_OPEN_FAILED,
                        exc,
                        self._now(),
                    )
                )
                return

            if not self._stop_requested.is_set():
                self.opened.emit(self.connection_generation)

            while not self._stop_requested.is_set():
                now_ns = self._now()
                self._drain_commands(now_ns)
                if self._stop_requested.is_set():
                    break
                try:
                    chunk_value = transport.read(self.settings.read_size)
                except Exception as exc:
                    had_error = True
                    now_ns = self._now()
                    self._drain_commands(now_ns)
                    detail = _safe_exception_detail(exc)
                    error = self._error(
                        BalanceServiceErrorCode.TRANSPORT_READ_FAILED,
                        exc,
                        now_ns,
                    )
                    self._fail_active(
                        now_ns,
                        StableMassFailureReason.TRANSPORT_ERROR,
                        detail,
                    )
                    self.fault.emit(error)
                    break

                now_ns = self._now()
                self._drain_commands(now_ns)
                if not isinstance(chunk_value, (bytes, bytearray, memoryview)):
                    raise TypeError("transport read() must return bytes-like data")
                chunk = bytes(chunk_value)
                if chunk:
                    self._diagnostics.add_chunk(chunk)
                    for event in self._framer.feed(chunk):
                        if event.kind is FrameEventKind.REJECTED:
                            self._diagnostics.add_rejection(
                                timestamp_ns=now_ns,
                                category="frame",
                                reason=event.rejection_reason.value,
                                payload=event.payload,
                            )
                            continue
                        self._diagnostics.add_frame()
                        parsed = parse_hpb_record(event.payload, now_ns)
                        if parsed.reading is not None:
                            self._diagnostics.add_reading()
                            self._handle_reading(parsed.reading)
                        else:
                            rejection = parsed.rejection
                            self._diagnostics.add_rejection(
                                timestamp_ns=now_ns,
                                category="record",
                                reason=rejection.reason.value,
                                payload=rejection.raw_frame,
                            )
                self._poll_active(now_ns)
        except Exception as exc:
            had_error = True
            now_ns = time.monotonic_ns()
            try:
                now_ns = self._now()
            except Exception:
                pass
            detail = _safe_exception_detail(exc)
            error = self._error(
                BalanceServiceErrorCode.WORKER_FAILURE, exc, now_ns
            )
            self._fail_active(
                now_ns, StableMassFailureReason.SERVICE_ERROR, detail
            )
            self.fault.emit(error)
        finally:
            now_ns = time.monotonic_ns()
            try:
                now_ns = self._now()
                self._drain_commands(now_ns)
            except Exception:
                pass
            if self._stop_requested.is_set() and self._detector is not None:
                cancel_time = max(
                    now_ns, self._detector.request.started_monotonic_ns
                )
                self._emit_result(self._detector.cancel(cancel_time))
            incomplete = self._framer.flush_incomplete()
            if incomplete is not None:
                self._diagnostics.add_rejection(
                    timestamp_ns=now_ns,
                    category="frame",
                    reason=incomplete.rejection_reason.value,
                    payload=incomplete.payload,
                )
            if transport is not None:
                try:
                    transport.close()
                except Exception as exc:
                    had_error = True
                    self.fault.emit(
                        self._error(
                            BalanceServiceErrorCode.TRANSPORT_CLOSE_FAILED,
                            exc,
                            now_ns,
                        )
                    )
            self.finished.emit(
                _WorkerFinishedEvent(
                    connection_generation=self.connection_generation,
                    requested_stop=self._stop_requested.is_set(),
                    had_error=had_error,
                    diagnostics=self._diagnostics.snapshot(),
                )
            )
            self.deleteLater()
            self.thread_done.emit()


class BalanceService(QtCore.QObject):
    connection_changed = QtCore.Signal(object)
    reading_received = QtCore.Signal(object)
    request_progress = QtCore.Signal(object)
    request_finished = QtCore.Signal(object)
    error_occurred = QtCore.Signal(object)

    def __init__(
        self,
        *,
        transport_factory: BalanceTransportFactory = open_hpb_serial_transport,
        monotonic_ns: MonotonicClock = time.monotonic_ns,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if not callable(transport_factory):
            raise TypeError("transport_factory must be callable")
        if not callable(monotonic_ns):
            raise TypeError("monotonic_ns must be callable")
        self._transport_factory = transport_factory
        self._monotonic_ns = monotonic_ns
        self._state = BalanceConnectionState.DISCONNECTED
        self._port: str | None = None
        self._connection_generation = 0
        self._request_generation = 0
        self._active_request: StableMassRequest | None = None
        self._active_request_generation: int | None = None
        self._cancel_pending = False
        self._used_request_ids: deque[str] = deque()
        self._used_request_id_set: set[str] = set()
        self._thread: QtCore.QThread | None = None
        self._worker: _BalanceSerialWorker | None = None
        self._last_diagnostics = BalanceDiagnosticsSnapshot()
        self._last_detail = ""

    def _now(self) -> int:
        value = self._monotonic_ns()
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("monotonic clock must return a nonnegative integer")
        return value

    @property
    def connection_snapshot(self) -> BalanceConnectionSnapshot:
        return BalanceConnectionSnapshot(
            state=self._state,
            port=self._port,
            connection_generation=self._connection_generation,
            timestamp_ns=self._now(),
            detail=self._last_detail,
        )

    @property
    def active_request_id(self) -> str | None:
        return self._active_request.request_id if self._active_request else None

    @property
    def worker_running(self) -> bool:
        return _thread_is_running(self._thread)

    def _set_state(self, state: BalanceConnectionState, detail: str = "") -> None:
        self._state = state
        self._last_detail = str(detail)
        self.connection_changed.emit(self.connection_snapshot)

    def _remember_request_id(self, request_id: str) -> None:
        if len(self._used_request_ids) >= MAX_RECENT_REQUEST_IDS:
            expired = self._used_request_ids.popleft()
            self._used_request_id_set.discard(expired)
        self._used_request_ids.append(request_id)
        self._used_request_id_set.add(request_id)

    def _forget_latest_request_id(self, request_id: str) -> None:
        if self._used_request_ids and self._used_request_ids[-1] == request_id:
            self._used_request_ids.pop()
            self._used_request_id_set.discard(request_id)

    def connect_balance(self, port: str) -> BalanceCommandResult:
        if self._state is BalanceConnectionState.CLOSED:
            return _rejected(
                BalanceCommandRejectReason.SERVICE_CLOSED,
                "balance service is closed",
            )
        explicit_port = str(port).strip() if port is not None else ""
        if not explicit_port:
            return _rejected(
                BalanceCommandRejectReason.INVALID_ARGUMENT,
                "an explicit balance serial port is required",
            )
        if self._state is not BalanceConnectionState.DISCONNECTED:
            return _rejected(
                BalanceCommandRejectReason.INVALID_STATE,
                f"cannot connect while balance service is {self._state.value}",
            )
        if self._thread is not None:
            return _rejected(
                BalanceCommandRejectReason.INVALID_STATE,
                "previous balance worker cleanup has not completed",
            )

        settings = BalanceSerialSettings(port=explicit_port)
        self._connection_generation += 1
        worker = _BalanceSerialWorker(
            settings=settings,
            connection_generation=self._connection_generation,
            transport_factory=self._transport_factory,
            monotonic_ns=self._monotonic_ns,
        )
        thread = QtCore.QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.opened.connect(self._on_worker_opened)
        worker.reading.connect(self._on_worker_reading)
        worker.progress.connect(self._on_worker_progress)
        worker.result.connect(self._on_worker_result)
        worker.fault.connect(self._on_worker_fault)
        worker.finished.connect(self._on_worker_finished)
        worker.thread_done.connect(
            thread.quit, QtCore.Qt.ConnectionType.DirectConnection
        )
        thread.finished.connect(self._on_thread_finished)
        self._worker = worker
        self._thread = thread
        self._port = explicit_port
        self._last_diagnostics = BalanceDiagnosticsSnapshot()
        self._set_state(BalanceConnectionState.CONNECTING, "opening balance port")
        thread.start()
        return _accepted("balance connection started")

    def disconnect_balance(self) -> BalanceCommandResult:
        if self._state is BalanceConnectionState.CLOSED:
            return _rejected(
                BalanceCommandRejectReason.SERVICE_CLOSED,
                "balance service is closed",
            )
        if self._state is BalanceConnectionState.DISCONNECTED:
            return _accepted("balance is already disconnected")
        if self._state is BalanceConnectionState.DISCONNECTING:
            return _accepted("balance disconnection is already in progress")
        if self._state is BalanceConnectionState.ERROR and not self.worker_running:
            self._active_request = None
            self._active_request_generation = None
            self._cancel_pending = False
            self._port = None
            self._set_state(BalanceConnectionState.DISCONNECTED, "error state reset")
            return _accepted("balance error state reset")
        self._set_state(BalanceConnectionState.DISCONNECTING, "disconnecting balance")
        if self._worker is not None:
            self._worker.request_stop()
        return _accepted("balance disconnection started")

    def request_stable_mass(
        self, request: StableMassRequest
    ) -> BalanceCommandResult:
        if self._state is BalanceConnectionState.CLOSED:
            return _rejected(
                BalanceCommandRejectReason.SERVICE_CLOSED,
                "balance service is closed",
            )
        if not isinstance(request, StableMassRequest):
            return _rejected(
                BalanceCommandRejectReason.INVALID_ARGUMENT,
                "request must be StableMassRequest",
            )
        if self._state is not BalanceConnectionState.STREAMING or self._worker is None:
            return _rejected(
                BalanceCommandRejectReason.INVALID_STATE,
                "stable mass can only be requested while streaming",
            )
        if self._active_request is not None:
            return _rejected(
                BalanceCommandRejectReason.REQUEST_ALREADY_ACTIVE,
                "a stable-mass request is already active",
            )
        if request.request_id in self._used_request_id_set:
            return _rejected(
                BalanceCommandRejectReason.INVALID_ARGUMENT,
                "stable-mass request id was recently used",
            )
        self._request_generation += 1
        self._active_request = request
        self._active_request_generation = self._request_generation
        self._cancel_pending = False
        self._remember_request_id(request.request_id)
        if not self._worker.enqueue_request(request, self._request_generation):
            self._active_request = None
            self._active_request_generation = None
            self._forget_latest_request_id(request.request_id)
            return _rejected(
                BalanceCommandRejectReason.INVALID_STATE,
                "balance worker command queue is full",
            )
        return _accepted("stable-mass request started")

    def cancel_stable_mass(self, request_id: str) -> BalanceCommandResult:
        if self._state is BalanceConnectionState.CLOSED:
            return _rejected(
                BalanceCommandRejectReason.SERVICE_CLOSED,
                "balance service is closed",
            )
        if self._active_request is None or self._worker is None:
            return _rejected(
                BalanceCommandRejectReason.NO_ACTIVE_REQUEST,
                "there is no active stable-mass request",
            )
        explicit_id = str(request_id).strip() if request_id is not None else ""
        if explicit_id != self._active_request.request_id:
            return _rejected(
                BalanceCommandRejectReason.REQUEST_ID_MISMATCH,
                "request id does not match the active stable-mass request",
            )
        if self._cancel_pending:
            return _accepted("stable-mass cancellation is already pending")
        if not self._worker.enqueue_cancel(
            explicit_id, self._active_request_generation
        ):
            return _rejected(
                BalanceCommandRejectReason.INVALID_STATE,
                "balance worker command queue is full",
            )
        self._cancel_pending = True
        return _accepted("stable-mass cancellation requested")

    def diagnostics_snapshot(self) -> BalanceDiagnosticsSnapshot:
        if self._worker is not None:
            try:
                return self._worker.diagnostics_snapshot()
            except RuntimeError:
                pass
        return self._last_diagnostics

    def close(self, wait_timeout_ms: int = 2000) -> BalanceCommandResult:
        if self._state is BalanceConnectionState.CLOSED:
            return _accepted("balance service is already closed")
        if (
            isinstance(wait_timeout_ms, bool)
            or not isinstance(wait_timeout_ms, int)
            or wait_timeout_ms < 0
        ):
            return _rejected(
                BalanceCommandRejectReason.INVALID_ARGUMENT,
                "wait_timeout_ms must be a nonnegative integer",
            )
        thread = self._thread
        worker = self._worker
        if _thread_is_running(thread):
            self._set_state(BalanceConnectionState.DISCONNECTING, "closing balance service")
            if worker is not None:
                worker.request_stop()
            deadline = time.monotonic() + wait_timeout_ms / 1000.0
            app = QtCore.QCoreApplication.instance()
            while _thread_is_running(thread):
                remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
                if remaining_ms <= 0:
                    break
                thread.wait(min(remaining_ms, 25))
                if app is not None:
                    app.processEvents()
            if app is not None:
                app.processEvents()
            if _thread_is_running(thread):
                error = BalanceServiceError(
                    code=BalanceServiceErrorCode.SHUTDOWN_TIMEOUT,
                    timestamp_ns=self._now(),
                    connection_generation=self._connection_generation,
                    port=self._port,
                    request_id=self.active_request_id,
                    exception_type="TimeoutError",
                    detail="balance worker did not stop before the shutdown deadline",
                )
                self.error_occurred.emit(error)
                self._set_state(BalanceConnectionState.ERROR, error.detail)
                return _rejected(
                    BalanceCommandRejectReason.INVALID_STATE,
                    error.detail,
                )
        if self._state is BalanceConnectionState.ERROR:
            return _rejected(
                BalanceCommandRejectReason.INVALID_STATE,
                "balance service stopped with an error",
            )
        self._thread = None
        self._worker = None
        self._active_request = None
        self._active_request_generation = None
        self._cancel_pending = False
        self._port = None
        self._set_state(BalanceConnectionState.CLOSED, "balance service closed")
        return _accepted("balance service closed")

    @QtCore.Slot(object)
    def _on_worker_opened(self, connection_generation: int) -> None:
        if connection_generation != self._connection_generation:
            return
        if self._state is BalanceConnectionState.CONNECTING:
            self._set_state(BalanceConnectionState.STREAMING, "balance stream active")

    @QtCore.Slot(object)
    def _on_worker_reading(self, event: _WorkerReadingEvent) -> None:
        if event.connection_generation != self._connection_generation:
            return
        if self._state in (
            BalanceConnectionState.STREAMING,
            BalanceConnectionState.DISCONNECTING,
        ):
            self.reading_received.emit(event.reading)

    @QtCore.Slot(object)
    def _on_worker_progress(self, progress: BalanceRequestProgress) -> None:
        if progress.connection_generation != self._connection_generation:
            return
        if progress.request_generation != self._active_request_generation:
            return
        if self._active_request is None:
            return
        if progress.request.request_id != self._active_request.request_id:
            return
        self.request_progress.emit(progress)

    @QtCore.Slot(object)
    def _on_worker_result(self, event: _WorkerResultEvent) -> None:
        if event.connection_generation != self._connection_generation:
            return
        if event.request_generation != self._active_request_generation:
            return
        if self._active_request is None:
            return
        if event.result.request_id != self._active_request.request_id:
            return
        self._active_request = None
        self._active_request_generation = None
        self._cancel_pending = False
        self.request_finished.emit(event.result)

    @QtCore.Slot(object)
    def _on_worker_fault(self, error: BalanceServiceError) -> None:
        if error.connection_generation != self._connection_generation:
            return
        self.error_occurred.emit(error)
        if self._state is not BalanceConnectionState.CLOSED:
            self._set_state(BalanceConnectionState.ERROR, error.detail)

    @QtCore.Slot(object)
    def _on_worker_finished(self, event: _WorkerFinishedEvent) -> None:
        if event.connection_generation != self._connection_generation:
            return
        self._last_diagnostics = event.diagnostics
        if self._state is BalanceConnectionState.CLOSED:
            return
        if event.had_error:
            if self._state is not BalanceConnectionState.ERROR:
                self._set_state(BalanceConnectionState.ERROR, "balance worker failed")
            return
        if event.requested_stop or self._state is BalanceConnectionState.DISCONNECTING:
            self._port = None
            self._set_state(BalanceConnectionState.DISCONNECTED, "balance disconnected")
            return
        error = BalanceServiceError(
            code=BalanceServiceErrorCode.WORKER_FAILURE,
            timestamp_ns=self._now(),
            connection_generation=self._connection_generation,
            port=self._port,
            request_id=self.active_request_id,
            exception_type="RuntimeError",
            detail="balance worker stopped unexpectedly",
        )
        self.error_occurred.emit(error)
        self._set_state(BalanceConnectionState.ERROR, error.detail)

    @QtCore.Slot()
    def _on_thread_finished(self) -> None:
        thread = self._thread
        self._thread = None
        self._worker = None
        if thread is not None:
            thread.deleteLater()


__all__ = [
    "BalanceCommandRejectReason",
    "BalanceCommandResult",
    "BalanceConnectionSnapshot",
    "BalanceConnectionState",
    "BalanceDiagnosticRecord",
    "BalanceDiagnosticsSnapshot",
    "BalanceRequestProgress",
    "BalanceSerialSettings",
    "BalanceService",
    "BalanceServiceError",
    "BalanceServiceErrorCode",
    "BalanceTransport",
    "BalanceTransportFactory",
    "open_hpb_serial_transport",
]
