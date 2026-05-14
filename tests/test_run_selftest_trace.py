import importlib.util
import struct
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_SELFTEST_PATH = REPO_ROOT / "tools" / "run_selftest.py"


def _load_run_selftest():
    spec = importlib.util.spec_from_file_location("run_selftest_mod_trace", RUN_SELFTEST_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


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


def _hello_ack(mod) -> bytes:
    return _frame_payload(mod, bytes([mod.CMD_HELLO_ACK, 1]))


def _selftest_done(mod, run_id: int) -> bytes:
    payload = bytearray([mod.CMD_SELFTEST_DONE, 2])
    payload += bytes([mod.TAG_RUN_ID, 4]) + run_id.to_bytes(4, "little")
    payload += bytes([mod.TAG_TOTAL, 2]) + (1).to_bytes(2, "little")
    payload += bytes([mod.TAG_PASSED, 2]) + (1).to_bytes(2, "little")
    payload += bytes([mod.TAG_FAILED, 2]) + (0).to_bytes(2, "little")
    payload += bytes([mod.TAG_ABORTED, 1, 0])
    return _frame_payload(mod, bytes(payload))


def _bye_ack(mod, seq8: int) -> bytes:
    return _frame_payload(mod, bytes([mod.CMD_BYE_ACK, seq8]))


def _bye_done(mod, seq8: int, seq32: int) -> bytes:
    payload = bytearray([mod.CMD_BYE_DONE, seq8])
    payload += bytes([mod.TAG_SEQ32, 4]) + seq32.to_bytes(4, "little")
    return _frame_payload(mod, bytes(payload))


def _selftest_result_metrics(mod, test_id: int, name: str, passed: bool, metrics: str) -> bytes:
    payload = bytearray([mod.CMD_SELFTEST_RESULT, 2])
    payload += bytes([mod.TAG_TEST_ID, 2]) + test_id.to_bytes(2, "little")
    payload += bytes([mod.TAG_NAME, len(name)]) + name.encode("utf-8")
    payload += bytes([mod.TAG_PASS, 1, 1 if passed else 0])
    payload += bytes([mod.TAG_METRICS, len(metrics)]) + metrics.encode("utf-8")
    return _frame_payload(mod, bytes(payload))


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


def test_run_sends_gripper_seal_selector_and_skips_goodbye(monkeypatch, tmp_path):
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


def test_run_sweep_selector_and_artifacts(monkeypatch, tmp_path):
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
        out=str(out_path),
    )

    rc = mod.run(args)

    assert rc == 0
    report = mod.json.loads(out_path.read_text(encoding="utf-8"))
    assert report["results"] == []
    checks = {c["name"]: c for c in report["host_checks"]}
    assert checks["selftest_progress_watchdog"]["details"]["progress_count"] == 1
