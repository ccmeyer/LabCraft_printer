from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from .report import write_json_atomic

try:
    from tools import run_selftest
except ModuleNotFoundError:
    import run_selftest  # type: ignore[no-redef]


PRODUCTION_PATH_SCHEMA = "gripper_refresh_production_hil_v1"
HOST_CHECK_NAME = "gripper_refresh_production_path"

CMD_STATUS = 0x02
CMD_GRIPPER_CLOSE = 0x11
CMD_DISPENSE_PRINT = 0x23
CMD_ENABLE_PRINT_PROFILE = 0x60
CMD_DISABLE_PRINT_PROFILE = 0x61
CMD_ABSOLUTE_PRESSURE_P = 0xE0
CMD_REGULATE_PRESSURE_P = 0xE8
CMD_DEREGULATE_PRESSURE_P = 0xE9
CMD_CLEAR = 0xF2
CMD_CLEAR_ACK = 0xF7

TAG_PRINT_PRESSURE = 0x12
TAG_TARGET_PRINT_PRESSURE = 0x14
TAG_ACTIVE_PRINT_PRESSURE = 0x40
TAG_LAST_RETIRED = 0x54
TAG_GRIP_REFRESH = 0x81

REFRESH_INTERVAL_MS = 30_000
CLOSE_COOLDOWN_WAIT_MS = 3_500
EXPIRY_WAIT_MS = 31_000
FAST_DISPENSE_MAX_MS = 1_500
DEFERRED_GAP_MIN_MS = 3_000
DEFERRED_GAP_MAX_MS = 7_000
COMMAND_RETIRE_TIMEOUT_MS = 12_000
PRINT_PRESSURE_TARGET_RAW = 2_512
PRINT_PRESSURE_TOLERANCE_RAW = 3
PRINT_PRESSURE_READY_TIMEOUT_MS = 15_000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _tlv_u32(tlvs: dict[int, bytes], tag: int) -> int | None:
    raw = tlvs.get(tag)
    if raw is None or len(raw) != 4:
        return None
    return int.from_bytes(raw, "little", signed=False)


def _tlv_u16(tlvs: dict[int, bytes], tag: int) -> int | None:
    raw = tlvs.get(tag)
    if raw is None or len(raw) != 2:
        return None
    return int.from_bytes(raw, "little", signed=False)


def _command_tlvs(p1: int, p2: int, p3: int) -> bytes:
    payload = bytearray()
    for tag, value in (
        (run_selftest.TAG_P1, p1),
        (run_selftest.TAG_P2, p2),
        (run_selftest.TAG_P3, p3),
    ):
        payload.extend((tag, 4))
        payload.extend(int(value).to_bytes(4, "little", signed=False))
    return bytes(payload)


class ProductionPathError(RuntimeError):
    pass


@dataclass
class CommandObservation:
    name: str
    command: int
    p1: int
    p2: int
    p3: int
    seq32: int
    ack_result: str
    sent_ms: int
    retired_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "p1": self.p1,
            "p2": self.p2,
            "p3": self.p3,
            "seq32": self.seq32,
            "ack_result": self.ack_result,
            "sent_ms": self.sent_ms,
            "retired_ms": self.retired_ms,
        }


class ProductionTransport(Protocol):
    latest_refresh_period_ms: int | None
    latest_print_pressure_raw: int | None
    latest_target_print_pressure_raw: int | None
    latest_print_pressure_active: int | None

    def __enter__(self) -> "ProductionTransport": ...
    def __exit__(self, exc_type, exc, tb) -> None: ...
    def hello(self) -> None: ...
    def queue(self, name: str, command: int, p1: int = 0, p2: int = 0, p3: int = 0) -> CommandObservation: ...
    def wait_retired(self, observation: CommandObservation, timeout_ms: int = COMMAND_RETIRE_TIMEOUT_MS) -> int: ...
    def reset_refresh_period_observation(self) -> None: ...
    def wait_refresh_period(self, timeout_ms: int = 1_000) -> int | None: ...
    def reset_print_pressure_observation(self) -> None: ...
    def wait_print_pressure_ready(
        self,
        target_raw: int,
        tolerance_raw: int,
        timeout_ms: int = PRINT_PRESSURE_READY_TIMEOUT_MS,
    ) -> dict[str, int] | None: ...
    def clear(self) -> bool: ...


class SerialProductionTransport:
    """Minimal production-wire client for the operator-gated gripper HIL."""

    def __init__(
        self,
        port: str,
        baud: int,
        *,
        serial_factory: Callable[..., Any] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        serial_mod = getattr(run_selftest, "serial", None)
        if serial_factory is None:
            if serial_mod is None:
                raise ProductionPathError("Missing dependency: pyserial")
            serial_factory = serial_mod.Serial
        self._serial_factory = serial_factory
        self._port = str(port)
        self._baud = int(baud)
        self._monotonic = monotonic
        self._serial = None
        self._reader = run_selftest.FrameReader()
        self._start = monotonic()
        self._next_seq32 = 1
        self._last_retired = 0
        self.latest_refresh_period_ms: int | None = None
        self.latest_print_pressure_raw: int | None = None
        self.latest_target_print_pressure_raw: int | None = None
        self.latest_print_pressure_active: int | None = None

    def __enter__(self) -> "SerialProductionTransport":
        self._serial = self._serial_factory(self._port, self._baud, timeout=0.05)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        serial_obj = self._serial
        self._serial = None
        if serial_obj is not None:
            serial_obj.close()

    def _elapsed_ms(self) -> int:
        return int(round((self._monotonic() - self._start) * 1000.0))

    def _read_frames_until(self, deadline: float, predicate: Callable[[bytes], bool]) -> bytes | None:
        if self._serial is None:
            raise ProductionPathError("Serial session is not open")
        while self._monotonic() < deadline:
            chunk = self._serial.read(128)
            for byte in chunk:
                frame = self._reader.feed(byte)
                if frame is None:
                    continue
                self._capture_status(frame)
                if predicate(frame):
                    return frame
        return None

    def _capture_status(self, frame: bytes) -> None:
        if len(frame) < 2 or frame[0] != CMD_STATUS:
            return
        # Status frames contain CMD_STATUS followed immediately by TLVs; unlike
        # command/ACK frames, they do not include a seq8 byte.
        tlvs = run_selftest.parse_tlvs(frame[1:])
        last_retired = _tlv_u32(tlvs, TAG_LAST_RETIRED)
        if last_retired is not None:
            self._last_retired = max(self._last_retired, last_retired)
        refresh_period = _tlv_u32(tlvs, TAG_GRIP_REFRESH)
        if refresh_period is not None:
            self.latest_refresh_period_ms = refresh_period
        print_pressure = _tlv_u16(tlvs, TAG_PRINT_PRESSURE)
        if print_pressure is not None:
            self.latest_print_pressure_raw = print_pressure
        target_print_pressure = _tlv_u16(
            tlvs, TAG_TARGET_PRINT_PRESSURE
        )
        if target_print_pressure is not None:
            self.latest_target_print_pressure_raw = target_print_pressure
        print_pressure_active = _tlv_u16(
            tlvs, TAG_ACTIVE_PRINT_PRESSURE
        )
        if print_pressure_active is not None:
            self.latest_print_pressure_active = print_pressure_active

    def hello(self) -> None:
        if self._serial is None:
            raise ProductionPathError("Serial session is not open")
        run_id = int(time.time() * 1000) & 0xFFFFFFFF
        seq8 = 0x70
        self._serial.write(run_selftest.build_control(run_selftest.CMD_HELLO, seq8, run_id))
        deadline = self._monotonic() + 2.0
        frame = self._read_frames_until(
            deadline,
            lambda item: len(item) >= 2
            and item[0] == run_selftest.CMD_HELLO_ACK
            and item[1] == seq8,
        )
        if frame is None:
            raise ProductionPathError("HELLO_ACK timeout")
        # HELLO establishes a new command session with expected seq32=1. Status
        # frames buffered before the ACK must not seed its retirement frontier.
        self._last_retired = 0

    def queue(
        self,
        name: str,
        command: int,
        p1: int = 0,
        p2: int = 0,
        p3: int = 0,
    ) -> CommandObservation:
        if self._serial is None:
            raise ProductionPathError("Serial session is not open")
        seq32 = self._next_seq32
        self._next_seq32 += 1
        seq8 = seq32 & 0xFF
        sent_ms = self._elapsed_ms()
        frame = run_selftest.build_control(
            command,
            seq8,
            seq32,
            _command_tlvs(p1, p2, p3),
        )
        self._serial.write(frame)
        deadline = self._monotonic() + 3.0
        observed = self._read_frames_until(
            deadline,
            lambda item: len(item) >= 2
            and item[0] == run_selftest.CMD_QUEUE_ACK
            and item[1] == seq8,
        )
        if observed is None:
            raise ProductionPathError(f"{name}: queue ACK timeout")
        tlvs = run_selftest.parse_tlvs(observed[2:])
        ack_seq32 = _tlv_u32(tlvs, run_selftest.TAG_SEQ32)
        ack_code = run_selftest._tlv_u8(tlvs, run_selftest.TAG_ACK_RESULT)
        if ack_seq32 != seq32:
            raise ProductionPathError(f"{name}: ACK sequence mismatch")
        if ack_code not in (run_selftest.ACK_RESULT_ACCEPTED, run_selftest.ACK_RESULT_DUPLICATE):
            raise ProductionPathError(
                f"{name}: queue rejected ({run_selftest.decode_ack_result(ack_code)})"
            )
        return CommandObservation(
            name=name,
            command=command,
            p1=p1,
            p2=p2,
            p3=p3,
            seq32=seq32,
            ack_result=run_selftest.decode_ack_result(ack_code),
            sent_ms=sent_ms,
        )

    def wait_retired(
        self,
        observation: CommandObservation,
        timeout_ms: int = COMMAND_RETIRE_TIMEOUT_MS,
    ) -> int:
        if self._last_retired > observation.seq32:
            raise ProductionPathError(
                f"{observation.name}: retirement sequence advanced from the expected "
                f"{observation.seq32} to {self._last_retired}"
            )
        deadline = self._monotonic() + (int(timeout_ms) / 1000.0)
        if self._last_retired < observation.seq32:
            self._read_frames_until(
                deadline,
                lambda _item: self._last_retired >= observation.seq32,
            )
        if self._last_retired > observation.seq32:
            raise ProductionPathError(
                f"{observation.name}: retirement sequence advanced from the expected "
                f"{observation.seq32} to {self._last_retired}"
            )
        if self._last_retired != observation.seq32:
            raise ProductionPathError(f"{observation.name}: retirement timeout")
        observation.retired_ms = self._elapsed_ms()
        return observation.retired_ms

    def wait_refresh_period(self, timeout_ms: int = 1_000) -> int | None:
        deadline = self._monotonic() + (int(timeout_ms) / 1000.0)
        if self.latest_refresh_period_ms is None:
            self._read_frames_until(
                deadline,
                lambda _item: self.latest_refresh_period_ms is not None,
            )
        return self.latest_refresh_period_ms

    def reset_refresh_period_observation(self) -> None:
        self.latest_refresh_period_ms = None

    def reset_print_pressure_observation(self) -> None:
        self.latest_print_pressure_raw = None
        self.latest_target_print_pressure_raw = None
        self.latest_print_pressure_active = None

    def wait_print_pressure_ready(
        self,
        target_raw: int,
        tolerance_raw: int,
        timeout_ms: int = PRINT_PRESSURE_READY_TIMEOUT_MS,
    ) -> dict[str, int] | None:
        def snapshot_if_ready() -> dict[str, int] | None:
            pressure = self.latest_print_pressure_raw
            target = self.latest_target_print_pressure_raw
            active = self.latest_print_pressure_active
            if (
                pressure is None
                or target is None
                or active != 1
                or target != int(target_raw)
                or abs(pressure - target) > int(tolerance_raw)
            ):
                return None
            return {"pressure_raw": pressure, "target_raw": target, "active": active}

        ready = snapshot_if_ready()
        if ready is not None:
            return ready
        deadline = self._monotonic() + (int(timeout_ms) / 1000.0)
        self._read_frames_until(deadline, lambda _item: snapshot_if_ready() is not None)
        return snapshot_if_ready()

    def clear(self) -> bool:
        if self._serial is None:
            return False
        seq8 = 0x71
        seq32 = self._next_seq32
        self._next_seq32 += 1
        self._serial.write(run_selftest.build_control(CMD_CLEAR, seq8, seq32))
        deadline = self._monotonic() + 3.0
        return self._read_frames_until(
            deadline,
            lambda item: len(item) >= 2 and item[0] == CMD_CLEAR_ACK and item[1] == seq8,
        ) is not None


def _wait_until_ms(
    target_ms: int,
    *,
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    start: float,
) -> None:
    while True:
        remaining = (target_ms / 1000.0) - (monotonic() - start)
        if remaining <= 0:
            return
        sleep(min(remaining, 0.25))


def _retire(
    transport: ProductionTransport,
    commands: list[CommandObservation],
    name: str,
    command: int,
    p1: int = 0,
    p2: int = 0,
    p3: int = 0,
) -> CommandObservation:
    observation = transport.queue(name, command, p1, p2, p3)
    commands.append(observation)
    transport.wait_retired(observation)
    return observation


def _fast_latency(observation: CommandObservation) -> int:
    if observation.retired_ms is None:
        raise ProductionPathError(f"{observation.name}: missing retirement timestamp")
    latency = observation.retired_ms - observation.sent_ms
    if latency > FAST_DISPENSE_MAX_MS:
        raise ProductionPathError(
            f"{observation.name}: {latency} ms exceeded {FAST_DISPENSE_MAX_MS} ms"
        )
    return latency


def _attempt_cleanup(transport: ProductionTransport, commands: list[CommandObservation]) -> dict[str, Any]:
    details: dict[str, Any] = {
        "disable_queued": False,
        "disable_retired": False,
        "deregulate_queued": False,
        "deregulate_retired": False,
        "clear_fallback": False,
    }
    try:
        disable = transport.queue("cleanup_disable_profile", CMD_DISABLE_PRINT_PROFILE)
        commands.append(disable)
        details["disable_queued"] = True
        transport.wait_retired(disable)
        details["disable_retired"] = True
    except Exception as exc:
        details["disable_error"] = str(exc)
    if details["disable_retired"]:
        try:
            deregulate = transport.queue(
                "cleanup_deregulate_print_pressure", CMD_DEREGULATE_PRESSURE_P
            )
            commands.append(deregulate)
            details["deregulate_queued"] = True
            transport.wait_retired(deregulate)
            details["deregulate_retired"] = True
            return details
        except Exception as exc:
            details["deregulate_error"] = str(exc)
    try:
        details["clear_fallback"] = bool(transport.clear())
    except Exception as exc:
        details["clear_error"] = str(exc)
    return details


def run_gripper_refresh_production_path(
    *,
    port: str,
    baud: int,
    artifact_path: str | Path,
    transport_factory: Callable[[], ProductionTransport] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Run the production command lifecycle and return its qualification host check."""

    if transport_factory is None:
        transport_factory = lambda: SerialProductionTransport(port, baud, monotonic=monotonic)

    started_at = _now_iso()
    start = monotonic()
    commands: list[CommandObservation] = []
    metrics: dict[str, Any] = {}
    cleanup: dict[str, Any] = {}
    error: dict[str, Any] | None = None
    active_transport: ProductionTransport | None = None
    normal_disable_completed = False

    try:
        with transport_factory() as transport:
            active_transport = transport
            transport.hello()

            _retire(
                transport,
                commands,
                "set_print_pressure_1psi",
                CMD_ABSOLUTE_PRESSURE_P,
                PRINT_PRESSURE_TARGET_RAW,
            )
            _retire(
                transport,
                commands,
                "regulate_print_pressure",
                CMD_REGULATE_PRESSURE_P,
            )
            transport.reset_print_pressure_observation()
            pressure_ready_started_ms = int(round((monotonic() - start) * 1000.0))
            pressure_ready = transport.wait_print_pressure_ready(
                PRINT_PRESSURE_TARGET_RAW,
                PRINT_PRESSURE_TOLERANCE_RAW,
            )
            if pressure_ready is None:
                raise ProductionPathError(
                    "Print pressure did not become active and ready at the safe 1 psi target"
                )
            metrics["print_pressure_ready"] = pressure_ready
            metrics["print_pressure_ready_latency_ms"] = (
                int(round((monotonic() - start) * 1000.0)) - pressure_ready_started_ms
            )

            close = _retire(transport, commands, "close_gripper", CMD_GRIPPER_CLOSE)
            enable = _retire(
                transport,
                commands,
                "enable_deferred_profile",
                CMD_ENABLE_PRINT_PROFILE,
                1,
            )
            # Retirement proves the enable command executed. Discard any status
            # value observed while it was queued so the period assertion uses a
            # status frame emitted strictly after that production command.
            transport.reset_refresh_period_observation()
            reported_refresh_period_ms = transport.wait_refresh_period()
            metrics["reported_refresh_period_ms"] = reported_refresh_period_ms
            if reported_refresh_period_ms != REFRESH_INTERVAL_MS:
                raise ProductionPathError(
                    "ENABLE_PRINT_PROFILE(p1=1) did not report a 30000 ms refresh period"
                )

            _wait_until_ms(
                max(close.retired_ms or 0, enable.retired_ms or 0) + CLOSE_COOLDOWN_WAIT_MS,
                monotonic=monotonic,
                sleep=sleep,
                start=start,
            )
            startup = _retire(
                transport,
                commands,
                "startup_dispense",
                CMD_DISPENSE_PRINT,
                1,
                20,
            )
            metrics["startup_dispense_latency_ms"] = _fast_latency(startup)

            _wait_until_ms(
                (enable.retired_ms or 0) + EXPIRY_WAIT_MS,
                monotonic=monotonic,
                sleep=sleep,
                start=start,
            )
            first = transport.queue("deferred_boundary_dispense", CMD_DISPENSE_PRINT, 1, 20, 0)
            commands.append(first)
            second = transport.queue("post_refresh_dispense", CMD_DISPENSE_PRINT, 1, 20, 0)
            commands.append(second)
            transport.wait_retired(first)
            transport.wait_retired(second)
            metrics["deferred_first_latency_ms"] = _fast_latency(first)
            if first.retired_ms is None or second.retired_ms is None:
                raise ProductionPathError("Deferred dispense timestamps were not captured")
            deferred_gap_ms = second.retired_ms - first.retired_ms
            metrics["deferred_retirement_gap_ms"] = deferred_gap_ms
            if not (DEFERRED_GAP_MIN_MS <= deferred_gap_ms <= DEFERRED_GAP_MAX_MS):
                raise ProductionPathError(
                    f"Deferred dispense gap {deferred_gap_ms} ms was outside "
                    f"{DEFERRED_GAP_MIN_MS}..{DEFERRED_GAP_MAX_MS} ms"
                )

            _retire(transport, commands, "disable_deferred_profile", CMD_DISABLE_PRINT_PROFILE)
            enable_zero = _retire(
                transport,
                commands,
                "enable_calibration_profile",
                CMD_ENABLE_PRINT_PROFILE,
                0,
            )
            _wait_until_ms(
                (enable_zero.retired_ms or 0) + EXPIRY_WAIT_MS,
                monotonic=monotonic,
                sleep=sleep,
                start=start,
            )
            p1_zero_first = _retire(
                transport,
                commands,
                "p1_zero_dispense_1",
                CMD_DISPENSE_PRINT,
                1,
                20,
            )
            p1_zero_second = _retire(
                transport,
                commands,
                "p1_zero_dispense_2",
                CMD_DISPENSE_PRINT,
                1,
                20,
            )
            metrics["p1_zero_dispense_1_latency_ms"] = _fast_latency(p1_zero_first)
            metrics["p1_zero_dispense_2_latency_ms"] = _fast_latency(p1_zero_second)

            _retire(transport, commands, "final_disable_profile", CMD_DISABLE_PRINT_PROFILE)
            _retire(
                transport,
                commands,
                "deregulate_print_pressure",
                CMD_DEREGULATE_PRESSURE_P,
            )
            normal_disable_completed = True
            cleanup = {
                "disable_queued": True,
                "disable_retired": True,
                "deregulate_queued": True,
                "deregulate_retired": True,
                "clear_fallback": False,
            }
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        if not normal_disable_completed:
            if active_transport is not None:
                cleanup = _attempt_cleanup(active_transport, commands)
            if not cleanup.get("disable_retired") and not cleanup.get("clear_fallback"):
                try:
                    with transport_factory() as recovery:
                        recovery.hello()
                        reconnect_cleanup = _attempt_cleanup(recovery, commands)
                    cleanup["reconnect"] = reconnect_cleanup
                except BaseException as exc:
                    cleanup["reconnect_error"] = str(exc)

    cleanup_ok = bool(
        (cleanup.get("disable_retired") and cleanup.get("deregulate_retired"))
        or cleanup.get("clear_fallback")
        or (
            (cleanup.get("reconnect") or {}).get("disable_retired")
            and (cleanup.get("reconnect") or {}).get("deregulate_retired")
        )
        or (cleanup.get("reconnect") or {}).get("clear_fallback")
    )
    passed = error is None and cleanup_ok
    artifact = {
        "schema_version": PRODUCTION_PATH_SCHEMA,
        "started_at": started_at,
        "finished_at": _now_iso(),
        "port": str(port),
        "baud": int(baud),
        "pass": passed,
        "commands": [item.to_dict() for item in commands],
        "metrics": metrics,
        "cleanup": cleanup,
        "error": error,
    }
    write_json_atomic(artifact_path, artifact)
    return {
        "name": HOST_CHECK_NAME,
        "pass": passed,
        "details": {
            "schema_version": PRODUCTION_PATH_SCHEMA,
            "artifact_path": str(artifact_path),
            "metrics": metrics,
            "cleanup": cleanup,
            "error": error,
        },
        "timestamp": _now_iso(),
    }
