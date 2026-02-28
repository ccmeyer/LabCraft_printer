import importlib.util
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_SELFTEST_PATH = REPO_ROOT / "tools" / "run_selftest.py"


def _load_run_selftest():
    spec = importlib.util.spec_from_file_location("run_selftest_mod", RUN_SELFTEST_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class FakeSerial:
    def __init__(self, inbound: bytes, empty_reads_before_data: int = 0):
        self._buf = bytearray(inbound)
        self.writes = []
        self._empty_reads_before_data = empty_reads_before_data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, n: int) -> bytes:
        if self._empty_reads_before_data > 0:
            self._empty_reads_before_data -= 1
            return b""
        if not self._buf:
            return b""
        # Emulate streaming UART bytes so handshake loops don't consume
        # subsequent frames in a single read call.
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


def _selftest_done(mod, run_id: int, failed: int = 0, aborted: int = 0) -> bytes:
    payload = bytearray([mod.CMD_SELFTEST_DONE, 2])
    payload += bytes([mod.TAG_RUN_ID, 4]) + run_id.to_bytes(4, "little")
    payload += bytes([mod.TAG_TOTAL, 2]) + (6).to_bytes(2, "little")
    payload += bytes([mod.TAG_PASSED, 2]) + (6 - failed).to_bytes(2, "little")
    payload += bytes([mod.TAG_FAILED, 2]) + failed.to_bytes(2, "little")
    payload += bytes([mod.TAG_ABORTED, 1, aborted])
    return _frame_payload(mod, bytes(payload))


def _bye_ack(mod, seq8: int) -> bytes:
    return _frame_payload(mod, bytes([mod.CMD_BYE_ACK, seq8]))


def _bye_done(mod, seq8: int, seq32: int | None = None) -> bytes:
    payload = bytearray([mod.CMD_BYE_DONE, seq8])
    if seq32 is not None:
        payload += bytes([mod.TAG_SEQ32, 4]) + seq32.to_bytes(4, "little")
    return _frame_payload(mod, bytes(payload))


def _run_with_stream(
    monkeypatch,
    tmp_path,
    inbound: bytes,
    timeout_ms: int = 5000,
    empty_reads_before_data: int = 0,
    profile: str = "SAFE",
    hello_timeout_ms: int = 8000,
    hello_retry_ms: int = 250,
    fast_fail_on_missing_hello: bool = False,
):
    mod = _load_run_selftest()
    clock = FakeClock()
    ser = FakeSerial(inbound, empty_reads_before_data=empty_reads_before_data)
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: ser))
    out_path = tmp_path / "report.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile=profile,
        timeout_ms=timeout_ms,
        hello_timeout_ms=hello_timeout_ms,
        hello_retry_ms=hello_retry_ms,
        fast_fail_on_missing_hello=fast_fail_on_missing_hello,
        out=str(out_path),
    )
    rc = mod.run(args)
    report = mod.json.loads(out_path.read_text(encoding="utf-8"))
    return mod, rc, report, ser


def test_goodbye_ack_and_done_success(monkeypatch, tmp_path):
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    inbound = b"".join(
        [
            _hello_ack(_load_run_selftest()),
            _selftest_done(_load_run_selftest(), run_id, failed=0),
            _bye_ack(_load_run_selftest(), 3),
            _bye_done(_load_run_selftest(), 3, seq32=run_id),
        ]
    )
    mod, rc, report, ser = _run_with_stream(monkeypatch, tmp_path, inbound)
    assert rc == 0
    checks = {c["name"]: c for c in report["host_checks"]}
    assert checks["goodbye_ack"]["pass"] is True
    assert checks["goodbye_done"]["pass"] is True
    assert len(ser.writes) == 3
    sent_goodbye = mod.FrameReader()
    got_cmd = None
    for b in ser.writes[2]:
        frame = sent_goodbye.feed(b)
        if frame:
            got_cmd = frame[0]
            break
    assert got_cmd == mod.CMD_GOODBYE


def test_hello_retries_until_target_is_ready(monkeypatch, tmp_path):
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    inbound = b"".join(
        [
            _hello_ack(_load_run_selftest()),
            _selftest_done(_load_run_selftest(), run_id, failed=0),
            _bye_ack(_load_run_selftest(), 3),
            _bye_done(_load_run_selftest(), 3, seq32=run_id),
        ]
    )
    mod, rc, report, ser = _run_with_stream(
        monkeypatch,
        tmp_path,
        inbound,
        empty_reads_before_data=30,
    )
    assert rc == 0
    assert len(ser.writes) >= 4
    hello_frames = 0
    for data in ser.writes:
        reader = mod.FrameReader()
        for b in data:
            frame = reader.feed(b)
            if frame:
                if frame[0] == mod.CMD_HELLO:
                    hello_frames += 1
                break
    assert hello_frames >= 2
    assert report["summary"]["failed"] == 0
    checks = {c["name"]: c for c in report["host_checks"]}
    assert checks["hello_ack"]["pass"] is True
    assert checks["hello_ack"]["details"]["retries_sent"] >= 2


def test_fast_fail_on_missing_hello_writes_report_and_skips_selftest(monkeypatch, tmp_path):
    mod, rc, report, ser = _run_with_stream(
        monkeypatch,
        tmp_path,
        inbound=b"",
        timeout_ms=12000,
        hello_timeout_ms=800,
        hello_retry_ms=100,
        fast_fail_on_missing_hello=True,
    )
    assert rc == 3
    assert report["aborted"] is True
    checks = {c["name"]: c for c in report["host_checks"]}
    assert checks["hello_ack"]["pass"] is False
    assert checks["hello_ack"]["details"]["timeout_ms"] == 800
    assert checks["hello_ack"]["details"]["retry_ms"] == 100
    assert checks["hello_ack"]["details"]["retries_sent"] >= 1
    assert len(ser.writes) >= 1
    for data in ser.writes:
        reader = mod.FrameReader()
        for b in data:
            frame = reader.feed(b)
            if frame:
                assert frame[0] != mod.CMD_SELFTEST_START
                break


def test_full_profile_preserves_long_timeout_floor(monkeypatch, tmp_path):
    _, rc, report, _ = _run_with_stream(
        monkeypatch,
        tmp_path,
        inbound=b"",
        profile="FULL",
        timeout_ms=1000,
        hello_timeout_ms=500,
        hello_retry_ms=100,
        fast_fail_on_missing_hello=True,
    )
    assert rc == 3
    assert report["profile"] == "FULL"
    checks = {c["name"]: c for c in report["host_checks"]}
    assert checks["hello_ack"]["details"]["timeout_ms"] == 500


def test_goodbye_ack_missing_sets_rc3(monkeypatch, tmp_path):
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    mod, rc, report, _ = _run_with_stream(
        monkeypatch,
        tmp_path,
        _hello_ack(_load_run_selftest()) + _selftest_done(_load_run_selftest(), run_id),
    )
    assert rc == 3
    checks = {c["name"]: c for c in report["host_checks"]}
    assert checks["goodbye_ack"]["pass"] is False
    assert checks["goodbye_done"]["pass"] is False
    assert checks["goodbye_done"]["details"]["skipped"] == "BYE_ACK not received"
    assert mod is not None


def test_goodbye_done_missing_after_ack_sets_rc3(monkeypatch, tmp_path):
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    inbound = _hello_ack(_load_run_selftest()) + _selftest_done(_load_run_selftest(), run_id) + _bye_ack(_load_run_selftest(), 3)
    _, rc, report, _ = _run_with_stream(monkeypatch, tmp_path, inbound)
    assert rc == 3
    checks = {c["name"]: c for c in report["host_checks"]}
    assert checks["goodbye_ack"]["pass"] is True
    assert checks["goodbye_done"]["pass"] is False


def test_wrong_seq8_is_rejected(monkeypatch, tmp_path):
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    inbound = b"".join(
        [
            _hello_ack(_load_run_selftest()),
            _selftest_done(_load_run_selftest(), run_id),
            _bye_ack(_load_run_selftest(), 9),
        ]
    )
    _, rc, report, _ = _run_with_stream(monkeypatch, tmp_path, inbound)
    assert rc == 3
    checks = {c["name"]: c for c in report["host_checks"]}
    assert checks["goodbye_ack"]["pass"] is False
    assert checks["goodbye_ack"]["details"]["observed_seq8"] == 9


def test_selftest_failed_but_closeout_success_stays_rc2(monkeypatch, tmp_path):
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    inbound = b"".join(
        [
            _hello_ack(_load_run_selftest()),
            _selftest_done(_load_run_selftest(), run_id, failed=2),
            _bye_ack(_load_run_selftest(), 3),
            _bye_done(_load_run_selftest(), 3, seq32=run_id),
        ]
    )
    _, rc, report, _ = _run_with_stream(monkeypatch, tmp_path, inbound)
    assert rc == 2
    checks = {c["name"]: c for c in report["host_checks"]}
    assert checks["goodbye_ack"]["pass"] is True
    assert checks["goodbye_done"]["pass"] is True


def test_selftest_pass_but_bad_bye_done_seq32_sets_rc3(monkeypatch, tmp_path):
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    inbound = b"".join(
        [
            _hello_ack(_load_run_selftest()),
            _selftest_done(_load_run_selftest(), run_id, failed=0),
            _bye_ack(_load_run_selftest(), 3),
            _bye_done(_load_run_selftest(), 3, seq32=(run_id + 1) & 0xFFFFFFFF),
        ]
    )
    _, rc, report, _ = _run_with_stream(monkeypatch, tmp_path, inbound)
    assert rc == 3
    checks = {c["name"]: c for c in report["host_checks"]}
    assert checks["goodbye_ack"]["pass"] is True
    assert checks["goodbye_done"]["pass"] is False
