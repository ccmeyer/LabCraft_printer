import importlib.util
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_SELFTEST_PATH = REPO_ROOT / "tools" / "run_selftest.py"


def _load_run_selftest():
    spec = importlib.util.spec_from_file_location("run_selftest_mod_trace", RUN_SELFTEST_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_status_only_timeout_allows_blocking_performance_legs_by_default():
    mod = _load_run_selftest()
    assert mod._effective_status_only_timeout_ms(SimpleNamespace(), True) == 60000
    assert mod._effective_status_only_timeout_ms(SimpleNamespace(), False) == 5000
    assert mod._effective_status_only_timeout_ms(
        SimpleNamespace(status_only_timeout_ms=12000), True
    ) == 12000


class FakeSerial:
    def __init__(self, inbound: bytes):
        self._buf = bytearray(inbound)
        self.writes = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, n: int) -> bytes:
        if not self._buf:
            return b""
        take = 1 if n > 0 else 0
        out = bytes(self._buf[:take])
        del self._buf[:take]
        return out

    def write(self, data: bytes):
        self.writes.append(bytes(data))
        return len(data)


class ChunkedFakeSerial(FakeSerial):
    def __init__(self, chunks: list[bytes]):
        self._chunks = [bytearray(chunk) for chunk in chunks]
        self.writes = []

    def read(self, n: int) -> bytes:
        while self._chunks and not self._chunks[0]:
            self._chunks.pop(0)
        if not self._chunks or n <= 0:
            return b""
        take = min(n, len(self._chunks[0]))
        out = bytes(self._chunks[0][:take])
        del self._chunks[0][:take]
        return out


class FakeClock:
    def __init__(self, step: float = 0.01, t0: float = 1000.0):
        self.now = t0
        self.step = step

    def monotonic(self) -> float:
        self.now += self.step
        return self.now

    def time(self) -> float:
        return 1700000000.0


def _frame_payload(mod, payload: bytes) -> bytes:
    return mod.frame_payload(payload)


def _hello_ack(mod, capabilities: int | None = None) -> bytes:
    payload = bytearray([mod.CMD_HELLO_ACK, 1])
    if capabilities is not None:
        payload += bytes([mod.TAG_CAPABILITIES, 4]) + capabilities.to_bytes(4, "little")
    return _frame_payload(mod, bytes(payload))


def _queue_ack(mod, seq8: int, seq32: int, result: int) -> bytes:
    payload = bytearray([mod.CMD_QUEUE_ACK, seq8])
    payload += bytes([mod.TAG_SEQ32, 4]) + seq32.to_bytes(4, "little")
    payload += bytes([mod.TAG_ACK_RESULT, 1, result])
    return _frame_payload(mod, bytes(payload))


def _selftest_done(
    mod,
    run_id: int,
    total: int = 1,
    passed: int = 1,
    failed: int = 0,
    aborted: bool = False,
) -> bytes:
    payload = bytearray([mod.CMD_SELFTEST_DONE, 2])
    payload += bytes([mod.TAG_RUN_ID, 4]) + run_id.to_bytes(4, "little")
    payload += bytes([mod.TAG_TOTAL, 2]) + total.to_bytes(2, "little")
    payload += bytes([mod.TAG_PASSED, 2]) + passed.to_bytes(2, "little")
    payload += bytes([mod.TAG_FAILED, 2]) + failed.to_bytes(2, "little")
    payload += bytes([mod.TAG_ABORTED, 1, 1 if aborted else 0])
    return _frame_payload(mod, bytes(payload))


def _bye_ack(mod, seq8: int) -> bytes:
    return _frame_payload(mod, bytes([mod.CMD_BYE_ACK, seq8]))


def _bye_done(mod, seq8: int, seq32: int) -> bytes:
    payload = bytearray([mod.CMD_BYE_DONE, seq8])
    payload += bytes([mod.TAG_SEQ32, 4]) + seq32.to_bytes(4, "little")
    return _frame_payload(mod, bytes(payload))


def _regulator_context_payload() -> bytes:
    return struct.pack(
        "<BBHHBBIIBBIII",
        1,
        1,
        0x0089,
        0x0103,
        0,
        1,
        0xFFFFFFFF,
        42,
        3,
        14,
        12,
        0xFFFFFFFF,
        123456,
    )


def _fault_context_payload(version: int = 1) -> bytes:
    header = (version, 0x45, 1, 8, 0x22, 3, 4, 0, 7, 8, 0)
    registers = (
        0xFFFFFFFD, 0x20002200, 0x20010000, 0x20002200, 0x20002000, 0x20002400,
        1, 2, 3, 4, 12, 0x08005679, 0x08001235, 0x21000000, 0x00008200,
        0x40000000, 2, 0, 0x00070000, 0x20000020, 0x20000024, 2, 0, 1, 0,
    )
    return struct.pack("<10BH25I", *header, *registers)


def _fault_context_v2_payload(version: int = 2) -> bytes:
    phases = (3, 4, 0, 7, 8)
    checkpoints = (4, 5, 0, 6, 8)
    registers = (
        0xFFFFFFED, 0x20002200, 0x20010000, 0x20002200, 0x20002000, 0x20002400,
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 0x08005679, 0x08001235,
        0x21000000, 0x00008200, 0x40000000, 0x20000020, 0x202020F8,
        0xC0000001, 0x20002100,
    )
    return struct.pack(
        "<4BH14B28I",
        version, 1, 8, 0x22, 0x0FD7,
        *phases, *checkpoints, 2, 0, 1, 0, *registers,
    )


def _xy_motion_context_payload(version: int = 1, valid: int = 1) -> bytes:
    return struct.pack(
        "<8BII6i5I",
        version, valid, 3, 0, 6, 4, 0x43, 0,
        77, 123456, -10, 20, 1000, 2000, 400, 500,
        1010, 1980, 410, 480, 3,
    )


def _selftest_result_metrics(mod, test_id: int, name: str, passed: bool, metrics: str) -> bytes:
    payload = bytearray([mod.CMD_SELFTEST_RESULT, 2])
    payload += bytes([mod.TAG_TEST_ID, 2]) + test_id.to_bytes(2, "little")
    payload += bytes([mod.TAG_NAME, len(name)]) + name.encode("utf-8")
    payload += bytes([mod.TAG_PASS, 1, 1 if passed else 0])
    payload += bytes([mod.TAG_METRICS, len(metrics)]) + metrics.encode("utf-8")
    return _frame_payload(mod, bytes(payload))


def _reset_report(
    mod,
    seq32: int = 1234,
    seq8: int = 2,
    include_regulator_context: bool = True,
) -> bytes:
    payload = bytearray([mod.CMD_RESET_REPORT, seq8])
    payload += bytes([mod.TAG_RESET_SEQ32, 4]) + seq32.to_bytes(4, "little")
    payload += bytes([mod.TAG_RESET_CAUSE, 1, 4])
    payload += bytes([mod.TAG_RESET_FLAGS, 4]) + (0x20000000).to_bytes(4, "little")
    payload += bytes([mod.TAG_RESET_LAST_FAULT, 1, 2])
    payload += bytes([mod.TAG_RESET_LAST_TASK, 1, 3])
    payload += bytes([mod.TAG_RESET_BOOT_COUNT, 4]) + (19).to_bytes(4, "little")
    payload += bytes([mod.TAG_RESET_FAULT_COUNT, 4]) + (5).to_bytes(4, "little")
    payload += bytes([mod.TAG_RESET_WATCHDOG_COUNT, 4]) + (7).to_bytes(4, "little")
    payload += bytes([mod.TAG_RESET_WATCHDOG_STICKY_CT, 4]) + (3).to_bytes(4, "little")
    payload += bytes([mod.TAG_RESET_WATCHDOG_RAW_SR, 4]) + (0x20000000).to_bytes(4, "little")
    payload += bytes([mod.TAG_RESET_UPTIME_MS, 4]) + (123456).to_bytes(4, "little")
    payload += bytes([mod.TAG_RESET_BOOT_STAGE, 1, 9])
    payload += bytes([mod.TAG_RESET_RECOVERY_BOOT, 1, 1])
    payload += bytes([mod.TAG_RESET_FAULT_STAGE, 1, 10])
    payload += bytes([mod.TAG_RESET_WATCHDOG_LATE_TASK, 1, 1])
    payload += bytes([mod.TAG_RESET_ACTIVE_COMMAND, 1, mod.CMD_SELFTEST_START])
    if include_regulator_context:
        raw_context = _regulator_context_payload()
        payload += bytes([mod.TAG_RESET_REG_CONTEXT, len(raw_context)]) + raw_context
    return _frame_payload(mod, bytes(payload))


def _basic_run_args(out_path: Path, *, progress_jsonl: bool = False):
    return SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="SAFE",
        timeout_ms=2000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        progress_timeout_ms=500,
        progress_jsonl=progress_jsonl,
        out=str(out_path),
    )


def _selftest_result_trace(
    mod,
    test_id: int,
    name: str,
    trace_kind: int,
    trace_format: int,
    chunk_index: int,
    chunk_total: int,
    payload_raw: bytes,
) -> bytes:
    payload = bytearray([mod.CMD_SELFTEST_RESULT, 2])
    payload += bytes([mod.TAG_TEST_ID, 2]) + test_id.to_bytes(2, "little")
    payload += bytes([mod.TAG_NAME, len(name)]) + name.encode("utf-8")
    payload += bytes([mod.TAG_PASS, 1, 1])
    payload += bytes([mod.TAG_TRACE_KIND, 1, trace_kind])
    payload += bytes([mod.TAG_TRACE_FORMAT, 1, trace_format])
    payload += bytes([mod.TAG_TRACE_CHUNK_INDEX, 2]) + chunk_index.to_bytes(2, "little")
    payload += bytes([mod.TAG_TRACE_CHUNK_TOTAL, 2]) + chunk_total.to_bytes(2, "little")
    payload += bytes([mod.TAG_TRACE_PAYLOAD, len(payload_raw)]) + payload_raw
    return _frame_payload(mod, bytes(payload))


def _captured_selftest_events(mod, captured_text: str) -> list[dict]:
    prefix = mod.SELFTEST_EVENT_PREFIX
    return [
        mod.json.loads(line[len(prefix):])
        for line in captured_text.splitlines()
        if line.startswith(prefix)
    ]


def _sent_command_ids(mod, writes: list[bytes]) -> list[int]:
    commands: list[int] = []
    for outbound in writes:
        reader = mod.FrameReader()
        for byte in outbound:
            frame = reader.feed(byte)
            if frame:
                commands.append(frame[0])
    return commands


def test_decode_pressure_trace_payloads():
    mod = _load_run_selftest()

    sample_payload = struct.pack(
        "<HHHHHhhHHBB",
        25,
        2100,
        2096,
        2088,
        2050,
        46,
        -3,
        3200,
        3000,
        0x13,
        8,
    )
    event_payload = struct.pack("<HBBHH", 30, 3, 0, 1300, 2100)

    samples = mod.decode_pressure_trace_samples_v1(sample_payload)
    events = mod.decode_pressure_trace_events_v1(event_payload)

    assert samples == [
        {
            "dt_ms": 25,
            "raw_pressure": 2100,
            "control_pressure": 2096,
            "avg_pressure": 2088,
            "target": 2050,
            "error": 46,
            "derror": -3,
            "requested_hz": 3200,
            "applied_hz": 3000,
            "flags": 0x13,
            "ff_boost_hz": 128,
        }
    ]
    assert events == [
        {
            "dt_ms": 30,
            "event_type": 3,
            "event_name": "pulse_end",
            "value0": 1300,
            "value1": 2100,
        }
    ]


def test_run_writes_pressure_trace_artifact(monkeypatch, tmp_path):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    sample_payload = struct.pack(
        "<HHHHHhhHHBB",
        25,
        2100,
        2096,
        2088,
        2050,
        46,
        -3,
        3200,
        3000,
        0x13,
        8,
    )
    event_payload = struct.pack("<HBBHH", 30, 3, 0, 1300, 2100)
    inbound = b"".join(
        [
            _hello_ack(mod),
            _selftest_result_metrics(
                mod,
                2102,
                "pressure_recovery_trace_print_repeated",
                True,
                "worst_recovery_ms=37;ready_miss_count=0",
            ),
            _selftest_result_trace(
                mod,
                2102,
                "pressure_recovery_trace_print_repeated",
                mod.TRACE_KIND_SAMPLES,
                mod.TRACE_FORMAT_SAMPLE_V1,
                0,
                1,
                sample_payload,
            ),
            _selftest_result_trace(
                mod,
                2102,
                "pressure_recovery_trace_print_repeated",
                mod.TRACE_KIND_EVENTS,
                mod.TRACE_FORMAT_EVENT_V1,
                0,
                1,
                event_payload,
            ),
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="FULL",
        timeout_ms=1000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=True,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 0
    report = mod.json.loads(out_path.read_text(encoding="utf-8"))
    assert report["summary"] == {"total": 1, "passed": 1, "failed": 0}
    trace_path = tmp_path / "selftest_trace_2102.json"
    trace = mod.json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["run_id"] == run_id
    assert trace["test_id"] == 2102
    assert trace["name"] == "pressure_recovery_trace_print_repeated"
    assert trace["summary"] == {"worst_recovery_ms": 37, "ready_miss_count": 0}
    assert len(trace["samples"]) == 1
    assert trace["samples"][0]["ff_boost_hz"] == 128
    assert len(trace["events"]) == 1
    assert trace["events"][0]["event_name"] == "pulse_end"

    sent_p2 = None
    for outbound in serial.writes:
        reader = mod.FrameReader()
        for byte in outbound:
            frame = reader.feed(byte)
            if not frame or frame[0] != mod.CMD_SELFTEST_START:
                continue
            tlv = mod.parse_tlvs(frame[2:])
            sent_p2 = tlv[mod.TAG_P2]
            break
        if sent_p2 is not None:
            break
    assert sent_p2 == b"\x01"


def test_run_writes_named_trace_artifacts_for_same_test_id(monkeypatch, tmp_path):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    sample_payload = struct.pack(
        "<HHHHHhhHHBB",
        25,
        3380,
        3380,
        3380,
        3386,
        -6,
        0,
        0,
        0,
        0x08,
        0,
    )
    event_payload = struct.pack("<HBBHH", 10, 2, 0, 1500, 3386)
    inbound = b"".join(
        [
            _hello_ack(mod),
            _selftest_result_trace(
                mod,
                2474,
                "valve_char_r_w1500_rep01",
                mod.TRACE_KIND_SAMPLES,
                mod.TRACE_FORMAT_SAMPLE_V1,
                0,
                1,
                sample_payload,
            ),
            _selftest_result_trace(
                mod,
                2474,
                "valve_char_r_w1500_rep01",
                mod.TRACE_KIND_EVENTS,
                mod.TRACE_FORMAT_EVENT_V1,
                0,
                1,
                event_payload,
            ),
            _selftest_result_trace(
                mod,
                2474,
                "valve_char_r_w3000_rep01",
                mod.TRACE_KIND_SAMPLES,
                mod.TRACE_FORMAT_SAMPLE_V1,
                0,
                1,
                sample_payload,
            ),
            _selftest_result_trace(
                mod,
                2474,
                "valve_char_r_w3000_rep01",
                mod.TRACE_KIND_EVENTS,
                mod.TRACE_FORMAT_EVENT_V1,
                0,
                1,
                event_payload,
            ),
            _selftest_result_metrics(
                mod,
                2474,
                "valve_char_refuel_2psi_repeat_linearity",
                True,
                "m15=10;m30=12;m45=18",
            ),
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="FULL",
        timeout_ms=1000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=True,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 0
    trace_15 = tmp_path / "selftest_trace_2474_valve_char_r_w1500_rep01.json"
    trace_30 = tmp_path / "selftest_trace_2474_valve_char_r_w3000_rep01.json"
    assert trace_15.exists()
    assert trace_30.exists()
    assert mod.json.loads(trace_15.read_text(encoding="utf-8"))["name"] == "valve_char_r_w1500_rep01"
    assert mod.json.loads(trace_30.read_text(encoding="utf-8"))["name"] == "valve_char_r_w3000_rep01"
    assert not (tmp_path / "selftest_trace_2474.json").exists()


def test_decode_pressure_trace_events_names_valve_and_gripper_metadata():
    mod = _load_run_selftest()
    payload = b"".join(
        [
            struct.pack("<HBBHH", 4, 10, 0, 12, 1500),
            struct.pack("<HBBHH", 4, 11, 0, 0xCFC7, 0xFFFF),
            struct.pack("<HBBHH", 4, 12, 0, 500, 0),
            struct.pack("<HBBHH", 4, 13, 0, 1500, 3000),
            struct.pack("<HBBHH", 4, 14, 0, 1234, 0),
            struct.pack("<HBBHH", 4, 15, 0, 42, 17),
            struct.pack("<HBBHH", 4, 16, 0, 3, 300),
        ]
    )

    rows = mod.decode_pressure_trace_events_v1(payload)

    assert rows[0]["event_name"] == "valve_sequence"
    assert rows[0]["value0"] == 12
    assert rows[0]["value1"] == 1500
    assert rows[1]["event_name"] == "motor_position"
    assert rows[1]["value_i32"] == -12345
    assert rows[2]["event_name"] == "valve_gap"
    assert rows[2]["value0"] == 500
    assert rows[3]["event_name"] == "valve_previous_width"
    assert rows[3]["value0"] == 1500
    assert rows[3]["value1"] == 3000
    assert rows[4]["event_name"] == "valve_interval"
    assert rows[4]["value0"] == 1234
    assert rows[5]["event_name"] == "gripper_timing"
    assert rows[5]["value0"] == 42
    assert rows[5]["value1"] == 17
    assert rows[6]["event_name"] == "gripper_refresh_count"
    assert rows[6]["value0"] == 3
    assert rows[6]["value1"] == 300


def test_run_sends_pressure_trace_test_selector(monkeypatch, tmp_path):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    inbound = b"".join(
        [
            _hello_ack(mod),
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="FULL",
        timeout_ms=1000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=True,
        pressure_trace_test=2103,
        pressure_sweep_suite=None,
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 0
    sent_p3 = None
    for outbound in serial.writes:
        reader = mod.FrameReader()
        for byte in outbound:
            frame = reader.feed(byte)
            if not frame or frame[0] != mod.CMD_SELFTEST_START:
                continue
            tlv = mod.parse_tlvs(frame[2:])
            sent_p3 = tlv.get(mod.TAG_P3)
            break
        if sent_p3 is not None:
            break
    assert sent_p3 == (2103).to_bytes(2, "little")


def test_run_sends_custom_pressure_trace_tlvs(monkeypatch, tmp_path):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    inbound = b"".join(
        [
            _hello_ack(mod),
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="FULL",
        timeout_ms=1000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_trace_custom=True,
        trace_channel="print",
        trace_pressure_psi=1.25,
        trace_pulse_us=1450,
        trace_pulse_count=20,
        trace_frequency_hz=20,
        pressure_sweep_suite=None,
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 0
    sent = None
    for outbound in serial.writes:
        reader = mod.FrameReader()
        for byte in outbound:
            frame = reader.feed(byte)
            if not frame or frame[0] != mod.CMD_SELFTEST_START:
                continue
            sent = mod.parse_tlvs(frame[2:])
            break
        if sent is not None:
            break
    assert sent[mod.TAG_P2] == b"\x01"
    assert sent[mod.TAG_P3] == (2110).to_bytes(2, "little")
    assert sent[mod.TAG_TRACE_CHANNEL] == b"\x00"
    assert sent[mod.TAG_TRACE_PRESSURE_MPSI] == (1250).to_bytes(2, "little")
    assert sent[mod.TAG_TRACE_PULSE_US] == (1450).to_bytes(2, "little")
    assert sent[mod.TAG_TRACE_PULSE_COUNT] == (20).to_bytes(2, "little")
    assert sent[mod.TAG_TRACE_FREQUENCY_HZ] == (20).to_bytes(2, "little")


def test_run_rejects_invalid_custom_pressure_trace_before_serial(monkeypatch, tmp_path):
    mod = _load_run_selftest()

    def fail_serial(*_args, **_kwargs):
        raise AssertionError("serial should not be opened for invalid custom trace args")

    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=fail_serial))
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="FULL",
        timeout_ms=1000,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_trace_custom=True,
        trace_channel="print",
        trace_pressure_psi=3.0,
        trace_pulse_us=1450,
        trace_pulse_count=20,
        trace_frequency_hz=20,
        out=str(tmp_path / "selftest.json"),
    )

    assert mod.run(args) == 3


def test_run_sends_gripper_seal_selector_and_skips_goodbye(monkeypatch, tmp_path):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()
    sample_payload = struct.pack(
        "<HHHHHhhHHBB",
        25,
        2100,
        2096,
        2088,
        2050,
        46,
        -3,
        3200,
        3000,
        0x11,
        2,
    )

    inbound = b"".join(
        [
            _hello_ack(mod),
            _selftest_done(mod, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="FULL",
        timeout_ms=1000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        gripper_seal_suite=True,
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 0
    sent_p3 = None
    sent_goodbye = False
    for outbound in serial.writes:
        reader = mod.FrameReader()
        for byte in outbound:
            frame = reader.feed(byte)
            if not frame:
                continue
            if frame[0] == mod.CMD_GOODBYE:
                sent_goodbye = True
            if frame[0] == mod.CMD_SELFTEST_START:
                tlv = mod.parse_tlvs(frame[2:])
                sent_p3 = tlv.get(mod.TAG_P3)
    assert sent_p3 == (2500).to_bytes(2, "little")
    assert sent_goodbye is False
    report = mod.json.loads(out_path.read_text(encoding="utf-8"))
    checks = {item["name"]: item for item in report["host_checks"]}
    assert checks["goodbye_skipped"]["details"]["reason"] == "operator_gated_gripper_teardown"


def test_run_sends_xy_motion_selector_and_keeps_goodbye(monkeypatch, tmp_path):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    inbound = b"".join(
        [
            _hello_ack(mod),
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="FULL",
        timeout_ms=1000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        gripper_seal_suite=False,
        xy_motion_suite=True,
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 0
    sent_p3 = None
    sent_goodbye = False
    for outbound in serial.writes:
        reader = mod.FrameReader()
        for byte in outbound:
            frame = reader.feed(byte)
            if not frame:
                continue
            if frame[0] == mod.CMD_GOODBYE:
                sent_goodbye = True
            if frame[0] == mod.CMD_SELFTEST_START:
                tlv = mod.parse_tlvs(frame[2:])
                sent_p3 = tlv.get(mod.TAG_P3)
    assert sent_p3 == (2009).to_bytes(2, "little")
    assert sent_goodbye is True


def test_run_sends_motion_envelope_selector_and_keeps_goodbye(monkeypatch, tmp_path):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    inbound = b"".join(
        [
            _hello_ack(mod),
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="FULL",
        timeout_ms=1000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        gripper_seal_suite=False,
        xy_motion_suite=False,
        motion_envelope_suite=True,
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 0
    sent_p3 = None
    sent_goodbye = False
    for outbound in serial.writes:
        reader = mod.FrameReader()
        for byte in outbound:
            frame = reader.feed(byte)
            if not frame:
                continue
            if frame[0] == mod.CMD_GOODBYE:
                sent_goodbye = True
            if frame[0] == mod.CMD_SELFTEST_START:
                tlv = mod.parse_tlvs(frame[2:])
                sent_p3 = tlv.get(mod.TAG_P3)
    assert sent_p3 == (2019).to_bytes(2, "little")
    assert sent_goodbye is True


def test_run_sends_motion_timing_selector_and_keeps_goodbye(monkeypatch, tmp_path):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    inbound = b"".join(
        [
            _hello_ack(mod),
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="FULL",
        timeout_ms=1000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        gripper_seal_suite=False,
        xy_motion_suite=False,
        motion_envelope_suite=False,
        motion_timing_suite=True,
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 0
    sent_p3 = None
    sent_goodbye = False
    for outbound in serial.writes:
        reader = mod.FrameReader()
        for byte in outbound:
            frame = reader.feed(byte)
            if not frame:
                continue
            if frame[0] == mod.CMD_GOODBYE:
                sent_goodbye = True
            if frame[0] == mod.CMD_SELFTEST_START:
                tlv = mod.parse_tlvs(frame[2:])
                sent_p3 = tlv.get(mod.TAG_P3)
    assert sent_p3 == (2029).to_bytes(2, "little")
    assert sent_goodbye is True


def test_run_sends_profile_lut_benchmark_selector_and_keeps_goodbye(monkeypatch, tmp_path):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    inbound = b"".join(
        [
            _hello_ack(mod),
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="SAFE",
        timeout_ms=1000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        gripper_seal_suite=False,
        xy_motion_suite=False,
        motion_envelope_suite=False,
        motion_timing_suite=False,
        profile_lut_benchmark=True,
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 0
    sent_p3 = None
    sent_goodbye = False
    for outbound in serial.writes:
        reader = mod.FrameReader()
        for byte in outbound:
            frame = reader.feed(byte)
            if not frame:
                continue
            if frame[0] == mod.CMD_GOODBYE:
                sent_goodbye = True
            if frame[0] == mod.CMD_SELFTEST_START:
                tlv = mod.parse_tlvs(frame[2:])
                sent_p3 = tlv.get(mod.TAG_P3)
    assert sent_p3 == (2039).to_bytes(2, "little")
    assert sent_goodbye is True


@pytest.mark.parametrize(
    ("flag_name", "expected_selector"),
    (("selftest_scheduler_no_yield_suite", 1039),
     ("selftest_scheduler_cooperative_suite", 1038)),
)
def test_run_sends_selftest_scheduler_selector(monkeypatch, tmp_path, flag_name, expected_selector):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()
    status = _frame_payload(mod, bytes([0x02, 0]))
    inbound = b"".join([
        _hello_ack(mod),
        status,
        status,
        _selftest_done(mod, run_id),
        _bye_ack(mod, 3),
        _bye_done(mod, 3, run_id),
    ])
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))
    args = SimpleNamespace(
        port="/dev/ttyAMA0", baud=115200, profile="SAFE", timeout_ms=1000,
        hello_timeout_ms=1000, hello_retry_ms=50, fast_fail_on_missing_hello=False,
        pressure_trace=False, pressure_trace_test=None, pressure_sweep_suite=None,
        out=str(tmp_path / f"{flag_name}.json"), **{flag_name: True},
    )

    assert mod.run(args) == 0
    sent_selector = None
    for outbound in serial.writes:
        reader = mod.FrameReader()
        for byte in outbound:
            frame = reader.feed(byte)
            if frame and frame[0] == mod.CMD_SELFTEST_START:
                sent_selector = mod.parse_tlvs(frame[2:]).get(mod.TAG_P3)
    assert sent_selector == expected_selector.to_bytes(2, "little")
    report = __import__("json").loads(
        (tmp_path / f"{flag_name}.json").read_text(encoding="utf-8")
    )
    cadence = [
        item for item in report["host_checks"]
        if item["name"] == "selftest_scheduler_status_cadence"
    ]
    assert bool(cadence) is (expected_selector == 1038)
    if cadence:
        assert cadence[0]["pass"] is True


@pytest.mark.parametrize(
    ("flag_name", "expected_selector"),
    (
        ("coordinated_xy_production_mres3_suite", 2097),
        ("coordinated_xy_shallow_edge_suite", 2099),
        ("direct_xyz_lut_suite", 2096),
        ("coordinated_xy_camera_transition_suite", 2078),
    ),
)
def test_run_sends_active_motion_selector_and_checks_status_cadence(
    monkeypatch, tmp_path, flag_name, expected_selector
):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()
    status = _frame_payload(mod, bytes([0x02, 0]))
    inbound = b"".join(
        [
            _hello_ack(mod),
            status,
            status,
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(
        mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time)
    )
    monkeypatch.setattr(
        mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial)
    )
    out_path = tmp_path / f"{flag_name}.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="FULL",
        timeout_ms=1000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        gripper_seal_suite=False,
        xy_motion_suite=False,
        motion_envelope_suite=False,
        motion_timing_suite=False,
        profile_lut_benchmark=False,
        out=str(out_path),
        **{flag_name: True},
    )

    assert mod.run(args) == 0
    sent_p3 = None
    for outbound in serial.writes:
        reader = mod.FrameReader()
        for byte in outbound:
            frame = reader.feed(byte)
            if frame and frame[0] == mod.CMD_SELFTEST_START:
                sent_p3 = mod.parse_tlvs(frame[2:]).get(mod.TAG_P3)
    assert sent_p3 == expected_selector.to_bytes(2, "little")
    report = mod.json.loads(out_path.read_text(encoding="utf-8"))
    cadence = next(
        item
        for item in report["host_checks"]
        if item["name"] == "coordinated_xy_status_cadence"
    )
    assert cadence["pass"] is True


def test_run_sends_pressure_regulator_selector_and_keeps_goodbye(monkeypatch, tmp_path):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    inbound = b"".join(
        [
            _hello_ack(mod),
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="FULL",
        timeout_ms=1000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        pressure_regulator_suite=True,
        gripper_seal_suite=False,
        xy_motion_suite=False,
        motion_envelope_suite=False,
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 0
    sent_p3 = None
    sent_goodbye = False
    for outbound in serial.writes:
        reader = mod.FrameReader()
        for byte in outbound:
            frame = reader.feed(byte)
            if not frame:
                continue
            if frame[0] == mod.CMD_GOODBYE:
                sent_goodbye = True
            if frame[0] == mod.CMD_SELFTEST_START:
                tlv = mod.parse_tlvs(frame[2:])
                sent_p3 = tlv.get(mod.TAG_P3)
    assert sent_p3 == (2299).to_bytes(2, "little")
    assert sent_goodbye is True


def test_run_sends_refuel_vacuum_selector_and_keeps_goodbye(monkeypatch, tmp_path):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    inbound = b"".join(
        [
            _hello_ack(mod),
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="FULL",
        timeout_ms=1000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=True,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        pressure_regulator_suite=False,
        refuel_vacuum_suite=True,
        gripper_seal_suite=False,
        xy_motion_suite=False,
        motion_envelope_suite=False,
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 0
    sent_p3 = None
    sent_goodbye = False
    for outbound in serial.writes:
        reader = mod.FrameReader()
        for byte in outbound:
            frame = reader.feed(byte)
            if not frame:
                continue
            if frame[0] == mod.CMD_GOODBYE:
                sent_goodbye = True
            if frame[0] == mod.CMD_SELFTEST_START:
                tlv = mod.parse_tlvs(frame[2:])
                sent_p3 = tlv.get(mod.TAG_P3)
    assert sent_p3 == (2298).to_bytes(2, "little")
    assert sent_goodbye is True


def test_run_sends_valve_characterization_selector_and_keeps_goodbye(monkeypatch, tmp_path):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    inbound = b"".join(
        [
            _hello_ack(mod),
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="FULL",
        timeout_ms=1000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        pressure_regulator_suite=False,
        valve_characterization_suite=True,
        gripper_seal_suite=False,
        xy_motion_suite=False,
        motion_envelope_suite=False,
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 0
    sent_p3 = None
    sent_goodbye = False
    for outbound in serial.writes:
        reader = mod.FrameReader()
        for byte in outbound:
            frame = reader.feed(byte)
            if not frame:
                continue
            if frame[0] == mod.CMD_GOODBYE:
                sent_goodbye = True
            if frame[0] == mod.CMD_SELFTEST_START:
                tlv = mod.parse_tlvs(frame[2:])
                sent_p3 = tlv.get(mod.TAG_P3)
    assert sent_p3 == (2499).to_bytes(2, "little")
    assert sent_goodbye is True


def test_run_sends_valve_gap_sweep_selector_and_keeps_goodbye(monkeypatch, tmp_path):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    inbound = b"".join(
        [
            _hello_ack(mod),
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="FULL",
        timeout_ms=1000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        pressure_regulator_suite=False,
        valve_characterization_suite=False,
        valve_gap_sweep_suite=True,
        gripper_seal_suite=False,
        xy_motion_suite=False,
        motion_envelope_suite=False,
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 0
    sent_p3 = None
    sent_goodbye = False
    for outbound in serial.writes:
        reader = mod.FrameReader()
        for byte in outbound:
            frame = reader.feed(byte)
            if not frame:
                continue
            if frame[0] == mod.CMD_GOODBYE:
                sent_goodbye = True
            if frame[0] == mod.CMD_SELFTEST_START:
                tlv = mod.parse_tlvs(frame[2:])
                sent_p3 = tlv.get(mod.TAG_P3)
    assert sent_p3 == (2498).to_bytes(2, "little")
    assert sent_goodbye is True


def test_run_sends_gripper_seal_stress_selector_and_skips_goodbye(monkeypatch, tmp_path):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    inbound = b"".join(
        [
            _hello_ack(mod),
            _selftest_done(mod, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="FULL",
        timeout_ms=1000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=True,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        pressure_regulator_suite=False,
        valve_characterization_suite=False,
        valve_gap_sweep_suite=False,
        gripper_seal_suite=False,
        gripper_seal_stress_suite=True,
        xy_motion_suite=False,
        motion_envelope_suite=False,
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 0
    sent_p3 = None
    sent_goodbye = False
    for outbound in serial.writes:
        reader = mod.FrameReader()
        for byte in outbound:
            frame = reader.feed(byte)
            if not frame:
                continue
            if frame[0] == mod.CMD_GOODBYE:
                sent_goodbye = True
            if frame[0] == mod.CMD_SELFTEST_START:
                tlv = mod.parse_tlvs(frame[2:])
                sent_p3 = tlv.get(mod.TAG_P3)
    assert sent_p3 == (2599).to_bytes(2, "little")
    assert sent_goodbye is False


def test_run_sweep_selector_and_artifacts(monkeypatch, tmp_path, capsys):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    sample_payload = struct.pack(
        "<HHHHHhhHHBB",
        10,
        2050,
        2050,
        2049,
        2055,
        -5,
        1,
        1400,
        1300,
        0x11,
        2,
    )
    event_payload = struct.pack("<HBBHH", 12, 3, 0, 1300, 2050)
    inbound = b"".join(
        [
            _hello_ack(mod),
            _selftest_result_metrics(
                mod,
                2310,
                "pressure_sweep_s2301_p1_c2",
                True,
                "suite=2301;param=1;scenario=2;mode=0;target_raw=2512;pulse_us=1300;droplets=10;hz=20;ready_miss=0;slip_w=90;trace=1;score=460",
            ),
            _selftest_result_metrics(
                mod,
                2391,
                "pressure_sweep_summary_s2301",
                False,
                "suite=2301;combos=1;pass_combo_count=1;best_param=1;best_score=460;worst_score=460;trace_exported_count=1",
            ),
            _selftest_result_trace(
                mod,
                2310,
                "pressure_sweep_s2301_p1_c2",
                mod.TRACE_KIND_SAMPLES,
                mod.TRACE_FORMAT_SAMPLE_V1,
                0,
                1,
                sample_payload,
            ),
            _selftest_result_trace(
                mod,
                2310,
                "pressure_sweep_s2301_p1_c2",
                mod.TRACE_KIND_EVENTS,
                mod.TRACE_FORMAT_EVENT_V1,
                0,
                1,
                event_payload,
            ),
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="FULL",
        timeout_ms=1000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=True,
        pressure_trace_test=None,
        pressure_sweep_suite=2301,
        progress_jsonl=True,
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 0
    sent_p3 = None
    for outbound in serial.writes:
        reader = mod.FrameReader()
        for byte in outbound:
            frame = reader.feed(byte)
            if not frame or frame[0] != mod.CMD_SELFTEST_START:
                continue
            tlv = mod.parse_tlvs(frame[2:])
            sent_p3 = tlv.get(mod.TAG_P3)
            break
        if sent_p3 is not None:
            break
    assert sent_p3 == (2301).to_bytes(2, "little")

    sweep_json = tmp_path / "selftest_pressure_sweep_s2301.json"
    sweep_csv = tmp_path / "selftest_pressure_sweep_s2301.csv"
    assert sweep_json.exists()
    assert sweep_csv.exists()

    sweep = mod.json.loads(sweep_json.read_text(encoding="utf-8"))
    assert sweep["suite_id"] == 2301
    assert len(sweep["combos"]) == 1
    assert sweep["combos"][0]["test_id"] == 2310
    assert sweep["combos"][0]["trace_file"] is not None
    events = _captured_selftest_events(mod, capsys.readouterr().out)
    assert [event["event"] for event in events] == [
        "selftest_result",
        "selftest_result",
        "selftest_done",
    ]
    assert [event["test_id"] for event in events if event["event"] == "selftest_result"] == [2310, 2391]


def test_progress_jsonl_emits_progress_result_and_done_events(monkeypatch, tmp_path, capsys):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    inbound = b"".join(
        [
            _hello_ack(mod),
            _selftest_result_metrics(
                mod,
                0,
                "selftest_progress",
                True,
                "kind=progress;stage=sweep_combo;elapsed_ms=1200",
            ),
            _selftest_result_metrics(
                mod,
                2007,
                "motion_home_repeatability_factory",
                True,
                "x_span=6;y_span=5;ret_err=0",
            ),
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="SAFE",
        timeout_ms=2000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        progress_timeout_ms=500,
        progress_jsonl=True,
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 0
    events = _captured_selftest_events(mod, capsys.readouterr().out)
    assert [event["event"] for event in events] == [
        "selftest_progress",
        "selftest_result",
        "selftest_done",
    ]
    assert events[0]["stage"] == "sweep_combo"
    assert events[1]["test_id"] == 2007
    assert events[1]["metrics"]["ret_err"] == 0
    assert events[2]["summary"] == {"total": 1, "passed": 1, "failed": 0}


def test_progress_jsonl_prompts_once_and_sends_resume_for_evap_plate_confirm(monkeypatch, tmp_path, capsys):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()
    progress = _selftest_result_metrics(
        mod,
        0,
        "selftest_progress",
        True,
        "kind=progress;stage=evap_plate_confirm;elapsed_ms=10;stk_hwm_w=100",
    )
    inbound = b"".join(
        [
            _hello_ack(mod),
            progress,
            progress,
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    responses: list[str] = []

    def fake_input(prompt=""):
        responses.append(prompt)
        return "continue"

    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))
    monkeypatch.setattr("builtins.input", fake_input)

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="FULL",
        timeout_ms=1000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        progress_jsonl=True,
        out=str(out_path),
    )

    assert mod.run(args) == 0

    events = _captured_selftest_events(mod, capsys.readouterr().out)
    prompt_events = [event for event in events if event["event"] == "selftest_operator_prompt"]
    response_events = [event for event in events if event["event"] == "selftest_operator_prompt_response"]
    assert len(prompt_events) == 1
    assert prompt_events[0]["stage"] == "evap_plate_confirm"
    assert len(response_events) == 1
    assert response_events[0]["accepted"] is True
    assert responses == [""]
    assert mod.CMD_RESUME in _sent_command_ids(mod, serial.writes)


def test_progress_jsonl_sends_abort_when_evap_plate_prompt_is_rejected(monkeypatch, tmp_path, capsys):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()
    inbound = b"".join(
        [
            _hello_ack(mod),
            _selftest_result_metrics(
                mod,
                0,
                "selftest_progress",
                True,
                "kind=progress;stage=evap_plate_confirm;elapsed_ms=10;stk_hwm_w=100",
            ),
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))
    monkeypatch.setattr("builtins.input", lambda prompt="": "abort")

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="FULL",
        timeout_ms=1000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        progress_jsonl=True,
        out=str(out_path),
    )

    assert mod.run(args) == 0

    events = _captured_selftest_events(mod, capsys.readouterr().out)
    response_events = [event for event in events if event["event"] == "selftest_operator_prompt_response"]
    assert len(response_events) == 1
    assert response_events[0]["accepted"] is False
    assert mod.CMD_SELFTEST_ABORT in _sent_command_ids(mod, serial.writes)


def test_progress_heartbeat_is_not_recorded_as_result(monkeypatch, tmp_path):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    inbound = b"".join(
        [
            _hello_ack(mod),
            _selftest_result_metrics(
                mod,
                0,
                "selftest_progress",
                True,
                "kind=progress;stage=sweep_combo;elapsed_ms=1200",
            ),
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="SAFE",
        timeout_ms=2000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        progress_timeout_ms=500,
        progress_jsonl=False,
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 0
    report = mod.json.loads(out_path.read_text(encoding="utf-8"))
    assert report["results"] == []
    checks = {c["name"]: c for c in report["host_checks"]}
    assert checks["selftest_progress_watchdog"]["details"]["progress_count"] == 1


def test_crash_watchdog_selftest_results_are_recorded_with_metrics(monkeypatch, tmp_path):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock(step=0.001)
    crash_metrics = (
        "pending=0;sticky=0;fault=none;task=none;reset=power;boot=42;"
        "fault_ct=3;wdg_ct=2;sticky_ct=4;raw_sr=3;boot_stage=hello_ack;wdg_late=none"
    )
    watchdog_metrics = (
        "enabled=1;arm_result=armed;timeout_ms=4000;init_timeout_ms=20;"
        "req_n=3;live_n=3;late_task=none;raw_sr=0;sticky_ct=0;recovery_boot=0"
    )

    inbound = b"".join(
        [
            _hello_ack(mod),
            _selftest_result_metrics(mod, 1041, "crash_record_retained_safe", True, crash_metrics),
            _selftest_result_metrics(mod, 1042, "watchdog_supervisor_safe", True, watchdog_metrics),
            _selftest_done(mod, run_id, total=2, passed=2, failed=0),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="SAFE",
        timeout_ms=2000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        progress_timeout_ms=500,
        progress_jsonl=False,
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 0
    report = mod.json.loads(out_path.read_text(encoding="utf-8"))
    results = {entry["name"]: entry for entry in report["results"]}
    assert results["crash_record_retained_safe"]["test_id"] == 1041
    assert results["crash_record_retained_safe"]["metrics"] == {
        "pending": 0,
        "sticky": 0,
        "fault": "none",
        "task": "none",
        "reset": "power",
        "boot": 42,
        "fault_ct": 3,
        "wdg_ct": 2,
        "sticky_ct": 4,
        "raw_sr": 3,
        "boot_stage": "hello_ack",
        "wdg_late": "none",
    }
    assert results["watchdog_supervisor_safe"]["test_id"] == 1042
    assert results["watchdog_supervisor_safe"]["metrics"] == {
        "enabled": 1,
        "arm_result": "armed",
        "timeout_ms": 4000,
        "init_timeout_ms": 20,
        "req_n": 3,
        "live_n": 3,
        "late_task": "none",
        "raw_sr": 0,
        "sticky_ct": 0,
        "recovery_boot": 0,
    }


def test_selftest_reset_decoder_accepts_v1_v2_and_ignores_bad_fault_context():
    mod = _load_run_selftest()

    context = mod.decode_fault_context(_fault_context_payload())

    assert context["task_name"] == "home_y"
    assert context["core_frame_valid"] is True
    assert context["pc"] == 0x08001235
    assert context["cfsr"] == 0x00008200
    assert context["home_phases"]["y"] == {"value": 4, "name": "fine_seek"}
    context_v2 = mod.decode_fault_context(_fault_context_v2_payload())
    assert context_v2["version"] == 2
    assert context_v2["task_name"] == "home_y"
    assert context_v2["r4"] == 5
    assert context_v2["r11"] == 12
    assert context_v2["fpccr"] == 0xC0000001
    assert context_v2["home_checkpoints"]["x"] == {"value": 4, "name": "waiting_for_move"}
    assert mod.decode_fault_context(b"\x01") is None
    assert mod.decode_fault_context(_fault_context_payload(version=3)) is None
    assert mod.decode_fault_context(_fault_context_v2_payload(version=3)) is None


def test_selftest_reset_decoder_decodes_optional_xy_motion_context():
    mod = _load_run_selftest()

    context = mod.decode_xy_motion_context(_xy_motion_context_payload())

    assert context["reason_name"] == "y_limit"
    assert context["executor_state_name"] == "limit_aborted"
    assert context["terminal_reason_name"] == "y_limit"
    assert context["command_seq32"] == 77
    assert context["start_x"] == -10
    assert context["emitted_y_edges"] == 480
    assert context["timer_owned"] is True
    assert mod.decode_xy_motion_context(b"\x01") is None
    assert mod.decode_xy_motion_context(_xy_motion_context_payload(version=2)) is None
    assert mod.decode_xy_motion_context(_xy_motion_context_payload(valid=0)) is None


def test_selftest_reset_decoder_decodes_direct_z_motion_context():
    mod = _load_run_selftest()
    payload = struct.pack(
        "<8BII6i5I",
        1, 1, 7, 0, 6, 6, 0x06, 0x0C,
        88, 654321, 1000, 0, 5000, 0, 2400, 0,
        4000, 0, 1400, 0, 1 << 3,
    )

    context = mod.decode_xy_motion_context(payload)

    assert context["reason_name"] == "z_limit"
    assert context["terminal_reason_name"] == "z_limit"
    assert context["motion_kind"] == "direct_axis"
    assert context["command_type"] == "ABSOLUTE_Z"
    assert context["axis"] == "Z"
    assert context["axis_start"] == 1000
    assert context["axis_target"] == 5000
    assert context["axis_end"] == 2400


def test_startup_reset_report_trailing_hello_ack_in_same_read_is_retained(
    monkeypatch, tmp_path, capsys
):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()
    serial = ChunkedFakeSerial(
        [
            _hello_ack(mod)
            + _reset_report(
                mod,
                seq32=run_id,
                seq8=1,
                include_regulator_context=False,
            ),
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    rc = mod.run(_basic_run_args(out_path, progress_jsonl=True))

    assert rc == 0
    report = mod.json.loads(out_path.read_text(encoding="utf-8"))
    assert report["startup_reset_report"]["reset_seq32"] == run_id
    assert report["startup_reset_report"]["watchdog_late_task"] == 1
    assert report["reset_report"] is None
    checks = {entry["name"]: entry for entry in report["host_checks"]}
    assert checks["selftest_progress_watchdog"]["pass"] is True
    assert checks["selftest_progress_watchdog"]["details"]["timeout_reason"] is None
    events = _captured_selftest_events(mod, capsys.readouterr().out)
    assert "selftest_startup_reset_report" in [event["event"] for event in events]
    assert "selftest_reset_report" not in [event["event"] for event in events]


def test_startup_reset_report_split_after_hello_ack_is_retained(monkeypatch, tmp_path):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()
    serial = ChunkedFakeSerial(
        [
            _hello_ack(mod),
            _reset_report(mod, seq32=run_id, seq8=1),
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    assert mod.run(_basic_run_args(out_path)) == 0

    report = mod.json.loads(out_path.read_text(encoding="utf-8"))
    assert report["startup_reset_report"]["reset_seq32"] == run_id
    assert report["startup_reset_report"]["regulator_context"]["valid"] is True
    assert report["reset_report"] is None


def test_startup_reset_report_interleaved_with_start_ack_is_retained(
    monkeypatch, tmp_path
):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()
    serial = ChunkedFakeSerial(
        [
            _hello_ack(mod, mod.SELFTEST_TRANSPORT_CAPS),
            _reset_report(mod, seq32=run_id, seq8=1)
            + _queue_ack(mod, 2, 1, mod.ACK_RESULT_ACCEPTED),
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    assert mod.run(_basic_run_args(out_path)) == 0

    report = mod.json.loads(out_path.read_text(encoding="utf-8"))
    assert report["startup_reset_report"]["reset_seq32"] == run_id
    assert report["reset_report"] is None
    checks = {entry["name"]: entry for entry in report["host_checks"]}
    assert checks["selftest_start_ack"]["pass"] is True
    assert checks["selftest_start_ack"]["details"]["ack_result"] == "accepted"


def test_report_schema_keeps_nullable_reset_fields_when_no_report_arrives(
    monkeypatch, tmp_path
):
    mod = _load_run_selftest()
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()
    serial = ChunkedFakeSerial(
        [
            _hello_ack(mod),
            _selftest_done(mod, run_id),
            _bye_ack(mod, 3),
            _bye_done(mod, 3, run_id),
        ]
    )
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    assert mod.run(_basic_run_args(out_path)) == 0

    report = mod.json.loads(out_path.read_text(encoding="utf-8"))
    assert report["startup_reset_report"] is None
    assert report["reset_report"] is None


def test_reset_report_during_selftest_is_classified(monkeypatch, tmp_path, capsys):
    mod = _load_run_selftest()
    clock = FakeClock()

    inbound = b"".join(
        [
            _hello_ack(mod),
            _selftest_result_metrics(
                mod,
                0,
                "selftest_progress",
                True,
                "kind=progress;stage=gripper_seal_reg_home;elapsed_ms=1200",
            ),
            _reset_report(mod, seq32=4321),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="FULL",
        timeout_ms=2000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        gripper_seal_suite=True,
        progress_timeout_ms=500,
        progress_jsonl=True,
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 3
    report = mod.json.loads(out_path.read_text(encoding="utf-8"))
    assert report["aborted"] is True
    assert report["startup_reset_report"] is None
    assert report["reset_report"]["reset_seq32"] == 4321
    checks = {c["name"]: c for c in report["host_checks"]}
    details = checks["selftest_progress_watchdog"]["details"]
    expected_regulator_context = {
        "version": 1,
        "valid": True,
        "snapshot_tick_ms": 123456,
        "print": {
            "raw": 0x0089,
            "names": ["active", "motion_hold", "motion_hold_wdg"],
            "active": True,
            "homing": False,
            "resetting": False,
            "motion_hold": True,
            "quiet": False,
            "stepping": False,
            "inactive_hold": False,
            "motion_hold_wdg": True,
            "recovery_hold": False,
            "watchdog_enabled": False,
            "watchdog_age_ms": None,
            "last_event": 3,
            "last_event_name": "motion_hold_enter",
            "last_event_age_ms": 12,
        },
        "refuel": {
            "raw": 0x0103,
            "names": ["active", "homing", "recovery_hold"],
            "active": True,
            "homing": True,
            "resetting": False,
            "motion_hold": False,
            "quiet": False,
            "stepping": False,
            "inactive_hold": False,
            "motion_hold_wdg": False,
            "recovery_hold": True,
            "watchdog_enabled": True,
            "watchdog_age_ms": 42,
            "last_event": 14,
            "last_event_name": "step_limit",
            "last_event_age_ms": None,
        },
    }
    assert details["timeout_reason"] == "mcu_reset_report_seen"
    assert details["reset_report"] == {
        "reset_seq32": 4321,
        "reset_cause": 4,
        "reset_flags": 0x20000000,
        "last_fault": 2,
        "last_task": 3,
        "boot_count": 19,
        "fault_count": 5,
        "watchdog_count": 7,
        "watchdog_sticky_count": 3,
        "watchdog_raw_sr": 0x20000000,
        "uptime_ms": 123456,
        "boot_stage": 9,
        "recovery_boot": 1,
        "fault_stage": 10,
        "watchdog_late_task": 1,
        "active_command": mod.CMD_SELFTEST_START,
        "regulator_context": expected_regulator_context,
        "fault_context": None,
        "xy_motion_context": None,
    }
    reset_frames = [frame for frame in details["recent_frames"] if frame["cmd"] == mod.CMD_RESET_REPORT]
    assert reset_frames
    assert reset_frames[-1]["reset_seq32"] == 4321
    events = _captured_selftest_events(mod, capsys.readouterr().out)
    assert [event["event"] for event in events] == [
        "selftest_progress",
        "selftest_reset_report",
        "selftest_timeout",
    ]
    assert events[1]["reset_report"]["reset_seq32"] == 4321
    assert events[1]["reset_report"]["reset_cause"] == 4
    assert events[1]["reset_report"]["watchdog_raw_sr"] == 0x20000000
    assert events[1]["reset_report"]["regulator_context"] == expected_regulator_context
    assert events[2]["reason"] == "mcu_reset_report_seen"


def test_progress_jsonl_emits_timeout_event_when_done_missing(monkeypatch, tmp_path, capsys):
    mod = _load_run_selftest()
    clock = FakeClock(step=0.05)

    serial = FakeSerial(_hello_ack(mod))
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="SAFE",
        timeout_ms=200,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        progress_timeout_ms=100,
        progress_jsonl=True,
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 3
    events = _captured_selftest_events(mod, capsys.readouterr().out)
    assert events[-1]["event"] == "selftest_timeout"
    assert mod.CMD_SELFTEST_ABORT in _sent_command_ids(mod, serial.writes)
    report = mod.json.loads(out_path.read_text(encoding="utf-8"))
    abort_check = next(
        check for check in report["host_checks"]
        if check["name"] == "selftest_timeout_abort"
    )
    assert abort_check["pass"] is True
    assert abort_check["details"]["sent"] is True


def test_camera_transition_stage_is_one_clear_envelope_prompt_without_pressure():
    mod = _load_run_selftest()
    stage = "coordinated_xy_camera_transition_envelope_clear"

    assert mod._is_operator_prompt_stage(stage)
    message = mod._operator_prompt_message(stage)
    assert "complete XY/Z motion envelope" in message
    assert "one 40 kHz camera-ratio round trip" in message
    assert "pressure_closed_loop_v1" not in message
    assert "press and hold" not in message.lower()


def test_production_mres3_fixture_stage_is_an_operator_prompt():
    mod = _load_run_selftest()
    stage = "coordinated_xy_production_mres3_envelope_clear"

    assert mod._is_operator_prompt_stage(stage)
    message = mod._operator_prompt_message(stage)
    assert "MRES=3" in message
    assert "40 kHz active edges" in message


def test_production_mres3_limit_crossing_stage_is_an_operator_prompt():
    mod = _load_run_selftest()
    stage = "coordinated_xy_production_mres3_limit_crossings_ready"

    assert mod._is_operator_prompt_stage(stage)
    message = mod._operator_prompt_message(stage)
    assert "optical X/Y limits are released" in message
    assert "bounded 200-step X crossing at 3 kHz" in message
    assert "home/release X" in message
    assert "repeat for Y" in message
    assert "Abort immediately" in message


def test_shallow_edge_fixture_stage_is_an_operator_prompt():
    mod = _load_run_selftest()
    stage = "coordinated_xy_shallow_edge_envelope_clear"

    assert mod._is_operator_prompt_stage(stage)
    message = mod._operator_prompt_message(stage)
    assert "non-dispensing test heads" in message
    assert "10/40 kHz shallow-angle" in message


def test_direct_xyz_lut_fixture_stage_is_an_operator_prompt():
    mod = _load_run_selftest()
    stage = "direct_xyz_lut_envelope_clear"

    assert mod._is_operator_prompt_stage(stage)
    message = mod._operator_prompt_message(stage)
    assert "direct X/Y/Z motion envelope" in message
    assert "14,000-unit move" in message
    assert "40 kHz logical rate" in message


def test_active_production_selector_is_mutually_exclusive_with_direct_lut(
    monkeypatch, tmp_path
):
    mod = _load_run_selftest()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_selftest.py",
            "--port", "/dev/null",
            "--profile", "FULL",
            "--coordinated-xy-production-mres3-suite",
            "--direct-xyz-lut-suite",
            "--out", str(tmp_path / "not-written.json"),
        ],
    )

    with pytest.raises(SystemExit) as error:
        mod.main()
    assert error.value.code == 2
