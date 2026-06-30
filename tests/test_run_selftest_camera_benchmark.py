import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_SELFTEST_PATH = REPO_ROOT / "tools" / "run_selftest.py"
BENCH_PATH = REPO_ROOT / "tools" / "camera_flash_benchmark.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
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

    def monotonic_ns(self) -> int:
        return int(self.monotonic() * 1_000_000_000)

    def sleep(self, seconds: float):
        self.now += float(seconds)

    def time(self) -> float:
        return 1700000000.0


def _frame_payload(mod, payload: bytes) -> bytes:
    if hasattr(mod, "frame_payload"):
        return mod.frame_payload(payload)
    crc = mod._crc16(payload)
    return bytes([0xAA, len(payload)]) + payload + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def _hello_ack(mod) -> bytes:
    return _frame_payload(mod, bytes([mod.CMD_HELLO_ACK, 1]))


def _hello_ack_with_caps(mod) -> bytes:
    payload = bytearray([mod.CMD_HELLO_ACK, 1])
    payload += bytes([mod.TAG_CAPABILITIES, 4]) + mod.SELFTEST_TRANSPORT_CAPS.to_bytes(4, "little")
    return _frame_payload(mod, bytes(payload))


def _queue_ack(mod, seq8: int, seq32: int, result: int | None = None, expected: int | None = None) -> bytes:
    if result is None:
        result = mod.ACK_RESULT_ACCEPTED
    payload = bytearray([mod.CMD_QUEUE_ACK, seq8 & 0xFF])
    payload += bytes([mod.TAG_SEQ32, 4]) + int(seq32).to_bytes(4, "little")
    payload += bytes([mod.TAG_ACK_RESULT, 1, int(result)])
    if expected is not None:
        payload += bytes([mod.TAG_EXPECTED_SEQ32, 4]) + int(expected).to_bytes(4, "little")
    return _frame_payload(mod, bytes(payload))


def _selftest_done(mod, run_id: int, failed: int = 0, aborted: int = 0) -> bytes:
    payload = bytearray([mod.CMD_SELFTEST_DONE, 2])
    payload += bytes([mod.TAG_RUN_ID, 4]) + run_id.to_bytes(4, "little")
    payload += bytes([mod.TAG_TOTAL, 2]) + (1).to_bytes(2, "little")
    payload += bytes([mod.TAG_PASSED, 2]) + (1 - failed).to_bytes(2, "little")
    payload += bytes([mod.TAG_FAILED, 2]) + failed.to_bytes(2, "little")
    payload += bytes([mod.TAG_ABORTED, 1, aborted])
    return _frame_payload(mod, bytes(payload))


def _bye_ack(mod, seq8: int) -> bytes:
    return _frame_payload(mod, bytes([mod.CMD_BYE_ACK, seq8]))


def _bye_done(mod, seq8: int, seq32: int) -> bytes:
    payload = bytearray([mod.CMD_BYE_DONE, seq8])
    payload += bytes([mod.TAG_SEQ32, 4]) + seq32.to_bytes(4, "little")
    return _frame_payload(mod, bytes(payload))


def _write_payload(frame: bytes) -> bytes:
    assert frame[0] == 0xAA
    ln = frame[1]
    return frame[2 : 2 + ln]


def _build_control_for(mod):
    def _build_control(cmd: int, seq8: int, seq32: int, tlvs: bytes = b"") -> bytes:
        payload = bytes([cmd, seq8 & 0xFF, mod.TAG_SEQ32, 4])
        payload += int(seq32).to_bytes(4, "little")
        payload += tlvs
        return _frame_payload(mod, payload)

    return _build_control


def _write_seq32(mod, frame: bytes) -> int:
    payload = _write_payload(frame)
    tlv = mod._parse_tlvs(payload[2:])
    return int.from_bytes(tlv[mod.TAG_SEQ32], "little")


def _strict_benchmark_payload(run_id: int, *, cycles: int = 10, next_seq32: int = 5) -> dict:
    return {
        "status": "ok",
        "summary": {
            "requested_cycles": cycles,
            "completed_cycles": cycles,
            "success_cycles": cycles,
            "success_rate": 1.0,
            "ack_seen_cycles": cycles,
            "frame_selected_cycles": cycles,
            "flash_detected_cycles": cycles,
            "effective_fps": 9.5,
        },
        "init_diag": {"config_match": True},
        "cycles": [],
        "run_id": run_id,
        "next_seq32": next_seq32,
    }


def test_summarize_cycles_basic():
    mod = _load_module(BENCH_PATH, "camera_flash_benchmark_mod_summary")
    cycles = [
        {
            "completed": True,
            "success_bool": True,
            "ack_seen_bool": True,
            "frame_selected_bool": True,
            "flash_detected_bool": True,
            "reason": "threshold",
            "trigger_to_ack_ms": 1.0,
            "ack_to_arm_ms": 0.1,
            "arm_to_frame_ms": 2.0,
            "trigger_to_frame_ms": 3.1,
            "cycle_total_ms": 3.4,
        },
        {
            "completed": True,
            "success_bool": False,
            "ack_seen_bool": True,
            "frame_selected_bool": True,
            "flash_detected_bool": False,
            "reason": "fallback",
            "trigger_to_ack_ms": 2.0,
            "ack_to_arm_ms": 0.2,
            "arm_to_frame_ms": 4.0,
            "trigger_to_frame_ms": 6.2,
            "cycle_total_ms": 6.6,
        },
    ]
    summary = mod.summarize_cycles(cycles, requested_cycles=2, started_ns=0, finished_ns=1_000_000_000)
    assert summary["requested_cycles"] == 2
    assert summary["completed_cycles"] == 2
    assert summary["success_cycles"] == 1
    assert summary["success_rate"] == 0.5
    assert summary["ack_seen_cycles"] == 2
    assert summary["frame_selected_cycles"] == 2
    assert summary["flash_detected_cycles"] == 1
    assert summary["threshold_cycles"] == 1
    assert summary["fallback_cycles"] == 1
    assert summary["effective_fps"] == 2.0
    assert summary["reason_distribution"]["threshold"] == 1
    assert summary["reason_distribution"]["fallback"] == 1
    assert summary["durations_ms"]["cycle_total_ms"]["count"] == 2
    assert summary["durations_ms"]["cycle_total_ms"]["p50"] is not None


def test_resolve_camera_benchmark_order_auto():
    run_mod = _load_module(RUN_SELFTEST_PATH, "run_selftest_mod_order_resolve")
    assert run_mod._resolve_camera_benchmark_order("flash_only", "auto") == "pre_selftest"
    assert run_mod._resolve_camera_benchmark_order("print_then_flash", "auto") == "post_selftest"
    assert run_mod._resolve_camera_benchmark_order("print_then_flash", "pre_selftest") == "pre_selftest"


def test_camera_benchmark_payload_pass_requires_flash_detected_cycles():
    run_mod = _load_module(RUN_SELFTEST_PATH, "run_selftest_mod_flash_detect_gate")
    payload = _strict_benchmark_payload(run_id=123, cycles=10, next_seq32=5)
    assert run_mod._camera_benchmark_payload_pass(payload) is True

    payload["summary"]["flash_detected_cycles"] = 9
    assert run_mod._camera_benchmark_payload_pass(payload) is False


def test_status_snapshot_parses_status_tlvs_from_payload_index_1():
    mod = _load_module(BENCH_PATH, "camera_flash_benchmark_mod_status_parse")

    def _frame(payload: bytes) -> bytes:
        crc = mod._crc16(payload)
        return bytes([0xAA, len(payload)]) + payload + bytes([crc & 0xFF, (crc >> 8) & 0xFF])

    payload = bytearray([mod.CMD_STATUS])
    payload += bytes([mod.TAG_PRINT_P, 2]) + (1234).to_bytes(2, "little")
    payload += bytes([mod.TAG_TAR_PRINT_P, 2]) + (1200).to_bytes(2, "little")
    payload += bytes([mod.TAG_ACTIVE_P, 2]) + (1).to_bytes(2, "little")
    inbound = _frame(bytes(payload))

    class _Serial:
        def __init__(self, data: bytes):
            self._buf = bytearray(data)

        def read(self, n: int) -> bytes:
            if not self._buf:
                return b""
            take = min(max(1, n), len(self._buf))
            out = bytes(self._buf[:take])
            del self._buf[:take]
            return out

    snap = mod._status_snapshot_from_serial(_Serial(inbound), sample_ms=30)
    assert snap["status_frames_seen"] >= 1
    assert snap["print_pressure"] == 1234
    assert snap["print_target"] == 1200
    assert snap["print_active"] == 1


def test_benchmark_queue_command_helper_uses_monotonic_seq32(monkeypatch):
    mod = _load_module(BENCH_PATH, "camera_flash_benchmark_mod_queue_helper")
    inbound = b"".join(
        [
            _queue_ack(mod, seq8=1, seq32=1),
            _queue_ack(mod, seq8=2, seq32=2),
        ]
    )
    serial = FakeSerial(inbound)
    clock = FakeClock()
    monkeypatch.setattr(
        mod,
        "time",
        SimpleNamespace(monotonic=clock.monotonic, monotonic_ns=clock.monotonic_ns, sleep=clock.sleep),
    )

    build_control = _build_control_for(mod)
    first = mod._send_queued_command(
        serial,
        build_control,
        name="init_flash",
        cmd=mod.CMD_INIT_FLASH,
        seq32=1,
    )
    second = mod._send_queued_command(
        serial,
        build_control,
        name="flash_duration",
        cmd=mod.CMD_SET_FLASH_DURATION,
        seq32=2,
        p1=1000,
    )

    assert first["ok"] is True
    assert second["ok"] is True
    assert [_write_seq32(mod, frame) for frame in serial.writes] == [1, 2]


def test_benchmark_queue_command_helper_rejects_gap_ack(monkeypatch):
    mod = _load_module(BENCH_PATH, "camera_flash_benchmark_mod_queue_gap")
    serial = FakeSerial(_queue_ack(mod, seq8=5, seq32=5, result=mod.ACK_RESULT_GAP, expected=1))
    clock = FakeClock()
    monkeypatch.setattr(
        mod,
        "time",
        SimpleNamespace(monotonic=clock.monotonic, monotonic_ns=clock.monotonic_ns, sleep=clock.sleep),
    )

    result = mod._send_queued_command(
        serial,
        _build_control_for(mod),
        name="init_flash",
        cmd=mod.CMD_INIT_FLASH,
        seq32=5,
    )

    assert result["ok"] is False
    assert result["reason"] == "gap"
    assert result["attempts"][0]["expected_seq32_from_mcu"] == 1


def test_camera_flash_benchmark_setup_gap_returns_setup_failed_without_cycles(monkeypatch):
    mod = _load_module(BENCH_PATH, "camera_flash_benchmark_mod_setup_gap")
    serial = FakeSerial(_queue_ack(mod, seq8=1, seq32=1, result=mod.ACK_RESULT_GAP, expected=1))
    clock = FakeClock()
    monkeypatch.setattr(
        mod,
        "time",
        SimpleNamespace(monotonic=clock.monotonic, monotonic_ns=clock.monotonic_ns, sleep=clock.sleep),
    )

    payload = mod.run_camera_flash_benchmark(
        serial,
        _build_control_for(mod),
        run_id=1234,
        config=mod.BenchmarkConfig(cycles=3),
        start_seq32=1,
    )

    assert payload["status"] == "setup_failed"
    assert payload["setup_failure_reason"] == "command_ack_failed"
    assert payload["next_seq32"] == 1
    assert payload["summary"]["completed_cycles"] == 0
    assert payload["cycles"] == []


def test_camera_flash_benchmark_config_mismatch_returns_setup_failed_without_cycles(monkeypatch):
    mod = _load_module(BENCH_PATH, "camera_flash_benchmark_mod_config_mismatch")
    status = bytearray([mod.CMD_STATUS])
    status += bytes([mod.TAG_FLASH_WIDTH, 4]) + (1000).to_bytes(4, "little")
    status += bytes([mod.TAG_FLASH_DELAY, 4]) + (9999).to_bytes(4, "little")
    status += bytes([mod.TAG_FLASH_DROPS, 4]) + (0).to_bytes(4, "little")
    inbound = b"".join(
        [
            _queue_ack(mod, seq8=1, seq32=1),
            _queue_ack(mod, seq8=2, seq32=2),
            _queue_ack(mod, seq8=3, seq32=3),
            _queue_ack(mod, seq8=4, seq32=4),
            _frame_payload(mod, bytes(status)),
        ]
    )
    serial = FakeSerial(inbound)
    clock = FakeClock()
    monkeypatch.setattr(
        mod,
        "time",
        SimpleNamespace(monotonic=clock.monotonic, monotonic_ns=clock.monotonic_ns, sleep=clock.sleep),
    )

    payload = mod.run_camera_flash_benchmark(
        serial,
        _build_control_for(mod),
        run_id=1234,
        config=mod.BenchmarkConfig(cycles=3, flash_delay_us=5000),
        start_seq32=1,
    )

    assert payload["status"] == "setup_failed"
    assert payload["setup_failure_reason"] == "config_mismatch"
    assert payload["next_seq32"] == 5
    assert payload["init_diag"]["config_match"] is False
    assert payload["summary"]["completed_cycles"] == 0
    assert payload["cycles"] == []


def test_run_selftest_writes_camera_benchmark_artifact(monkeypatch, tmp_path):
    run_mod = _load_module(RUN_SELFTEST_PATH, "run_selftest_mod_cam_ok")
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    inbound = b"".join(
        [
            _hello_ack(run_mod),
            _selftest_done(run_mod, run_id),
            _bye_ack(run_mod, 3),
            _bye_done(run_mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(run_mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(run_mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    class FakeCfg:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def fake_bench_run(_ser, _build_control, *, run_id, config, start_seq32=1):
        assert isinstance(config, FakeCfg)
        assert config.kwargs.get("mode") == "flash_only"
        assert config.kwargs.get("run_order") == "pre_selftest"
        assert config.kwargs.get("num_droplets") == 0
        assert start_seq32 == 1
        return _strict_benchmark_payload(run_id, cycles=10, next_seq32=5)

    fake_bench = SimpleNamespace(BenchmarkConfig=FakeCfg, run_camera_flash_benchmark=fake_bench_run)
    monkeypatch.setitem(sys.modules, "camera_flash_benchmark", fake_bench)

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="SAFE",
        timeout_ms=2000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        camera_benchmark=True,
        camera_benchmark_cycles=10,
        camera_benchmark_exposure_us=20000,
        camera_benchmark_flash_delay_us=5000,
        camera_benchmark_flash_width_us=1000,
        camera_benchmark_num_droplets=1,
        camera_benchmark_attempt_timeout_ms=250,
        camera_benchmark_max_new_frames=6,
        camera_benchmark_order="pre_selftest",
        camera_benchmark_mode="flash_only",
        camera_benchmark_preflight_pressure_timeout_ms=1000,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        out=str(out_path),
    )

    rc = run_mod.run(args)
    assert rc == 0
    report = run_mod.json.loads(out_path.read_text(encoding="utf-8"))
    checks = {c["name"]: c for c in report["host_checks"]}
    assert "camera_flash_benchmark" in checks
    assert checks["camera_flash_benchmark"]["pass"] is True
    assert checks["camera_flash_benchmark"]["details"]["phase"] == "pre_selftest"
    assert checks["camera_flash_benchmark"]["details"]["mode"] == "flash_only"
    artifact = tmp_path / "selftest_camera_benchmark.json"
    assert artifact.exists()
    payload = run_mod.json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["summary"]["effective_fps"] == 9.5


def test_run_selftest_pre_benchmark_advances_selftest_seq32(monkeypatch, tmp_path):
    run_mod = _load_module(RUN_SELFTEST_PATH, "run_selftest_mod_cam_seq32")
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    inbound = b"".join(
        [
            _hello_ack_with_caps(run_mod),
            _queue_ack(run_mod, seq8=2, seq32=5),
            _selftest_done(run_mod, run_id),
            _bye_ack(run_mod, 3),
            _bye_done(run_mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(run_mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(run_mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    class FakeCfg:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def fake_bench_run(_ser, _build_control, *, run_id, config, start_seq32=1):
        assert isinstance(config, FakeCfg)
        assert start_seq32 == 1
        return _strict_benchmark_payload(run_id, cycles=10, next_seq32=5)

    fake_bench = SimpleNamespace(BenchmarkConfig=FakeCfg, run_camera_flash_benchmark=fake_bench_run)
    monkeypatch.setitem(sys.modules, "camera_flash_benchmark", fake_bench)

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="SAFE",
        timeout_ms=2000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        camera_benchmark=True,
        camera_benchmark_cycles=10,
        camera_benchmark_exposure_us=20000,
        camera_benchmark_flash_delay_us=5000,
        camera_benchmark_flash_width_us=1000,
        camera_benchmark_num_droplets=1,
        camera_benchmark_attempt_timeout_ms=250,
        camera_benchmark_max_new_frames=6,
        camera_benchmark_order="pre_selftest",
        camera_benchmark_mode="flash_only",
        camera_benchmark_preflight_pressure_timeout_ms=1000,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        out=str(out_path),
    )

    rc = run_mod.run(args)
    assert rc == 0
    start_payload = next(_write_payload(w) for w in serial.writes if _write_payload(w)[0] == run_mod.CMD_SELFTEST_START)
    assert start_payload[1] == 2
    start_tlv = run_mod.parse_tlvs(start_payload[2:])
    assert int.from_bytes(start_tlv[run_mod.TAG_SEQ32], "little") == 5
    report = run_mod.json.loads(out_path.read_text(encoding="utf-8"))
    checks = {c["name"]: c for c in report["host_checks"]}
    assert checks["camera_flash_benchmark"]["details"]["next_seq32"] == 5
    assert checks["selftest_start_ack"]["pass"] is True


def test_run_selftest_camera_benchmark_functional_failure_sets_rc2(monkeypatch, tmp_path):
    run_mod = _load_module(RUN_SELFTEST_PATH, "run_selftest_mod_cam_functional_fail")
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    inbound = b"".join(
        [
            _hello_ack(run_mod),
            _selftest_done(run_mod, run_id),
            _bye_ack(run_mod, 3),
            _bye_done(run_mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(run_mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(run_mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    class FakeCfg:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def fake_bench_run(_ser, _build_control, *, run_id, config, start_seq32=1):
        return {
            "status": "ok",
            "summary": {
                "requested_cycles": 10,
                "completed_cycles": 10,
                "ack_seen_cycles": 0,
                "frame_selected_cycles": 0,
                "flash_detected_cycles": 0,
                "success_cycles": 0,
                "success_rate": 0.0,
            },
            "init_diag": {"config_match": True},
            "cycles": [],
            "run_id": run_id,
            "next_seq32": 5,
        }

    fake_bench = SimpleNamespace(BenchmarkConfig=FakeCfg, run_camera_flash_benchmark=fake_bench_run)
    monkeypatch.setitem(sys.modules, "camera_flash_benchmark", fake_bench)

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="SAFE",
        timeout_ms=2000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        camera_benchmark=True,
        camera_benchmark_order="pre_selftest",
        camera_benchmark_mode="flash_only",
        camera_benchmark_preflight_pressure_timeout_ms=1000,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        out=str(out_path),
    )

    rc = run_mod.run(args)
    assert rc == 2
    report = run_mod.json.loads(out_path.read_text(encoding="utf-8"))
    checks = {c["name"]: c for c in report["host_checks"]}
    assert checks["camera_flash_benchmark"]["pass"] is False
    assert checks["camera_flash_benchmark"]["details"]["status"] == "ok"


def test_run_selftest_camera_benchmark_setup_failed_sets_rc2(monkeypatch, tmp_path):
    run_mod = _load_module(RUN_SELFTEST_PATH, "run_selftest_mod_cam_setup_fail")
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    inbound = b"".join(
        [
            _hello_ack(run_mod),
            _selftest_done(run_mod, run_id),
            _bye_ack(run_mod, 3),
            _bye_done(run_mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(run_mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(run_mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    class FakeCfg:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def fake_bench_run(_ser, _build_control, *, run_id, config, start_seq32=1):
        return {
            "status": "setup_failed",
            "setup_failure_reason": "command_ack_failed",
            "summary": {
                "requested_cycles": 10,
                "completed_cycles": 0,
                "ack_seen_cycles": 0,
                "frame_selected_cycles": 0,
                "flash_detected_cycles": 0,
                "success_cycles": 0,
                "success_rate": 0.0,
            },
            "init_diag": {"config_match": False},
            "cycles": [],
            "run_id": run_id,
            "next_seq32": 1,
        }

    fake_bench = SimpleNamespace(BenchmarkConfig=FakeCfg, run_camera_flash_benchmark=fake_bench_run)
    monkeypatch.setitem(sys.modules, "camera_flash_benchmark", fake_bench)

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="SAFE",
        timeout_ms=2000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        camera_benchmark=True,
        camera_benchmark_order="pre_selftest",
        camera_benchmark_mode="flash_only",
        camera_benchmark_preflight_pressure_timeout_ms=1000,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        out=str(out_path),
    )

    rc = run_mod.run(args)
    assert rc == 2
    report = run_mod.json.loads(out_path.read_text(encoding="utf-8"))
    checks = {c["name"]: c for c in report["host_checks"]}
    assert checks["camera_flash_benchmark"]["pass"] is False
    assert checks["camera_flash_benchmark"]["details"]["status"] == "setup_failed"


def test_run_selftest_camera_benchmark_runtime_error_sets_rc3(monkeypatch, tmp_path):
    run_mod = _load_module(RUN_SELFTEST_PATH, "run_selftest_mod_cam_fail")
    run_id = int(1700000000.0 * 1000) & 0xFFFFFFFF
    clock = FakeClock()

    inbound = b"".join(
        [
            _hello_ack(run_mod),
            _selftest_done(run_mod, run_id),
            _bye_ack(run_mod, 3),
            _bye_done(run_mod, 3, run_id),
        ]
    )
    serial = FakeSerial(inbound)
    monkeypatch.setattr(run_mod, "time", SimpleNamespace(monotonic=clock.monotonic, time=clock.time))
    monkeypatch.setattr(run_mod, "serial", SimpleNamespace(Serial=lambda *args, **kwargs: serial))

    class FakeCfg:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def fake_bench_run(*_args, **_kwargs):
        raise RuntimeError("camera unavailable")

    fake_bench = SimpleNamespace(BenchmarkConfig=FakeCfg, run_camera_flash_benchmark=fake_bench_run)
    monkeypatch.setitem(sys.modules, "camera_flash_benchmark", fake_bench)

    out_path = tmp_path / "selftest.json"
    args = SimpleNamespace(
        port="/dev/ttyAMA0",
        baud=115200,
        profile="SAFE",
        timeout_ms=2000,
        hello_timeout_ms=1000,
        hello_retry_ms=50,
        fast_fail_on_missing_hello=False,
        camera_benchmark=True,
        camera_benchmark_order="pre_selftest",
        camera_benchmark_mode="flash_only",
        camera_benchmark_preflight_pressure_timeout_ms=1000,
        pressure_trace=False,
        pressure_trace_test=None,
        pressure_sweep_suite=None,
        out=str(out_path),
    )

    rc = run_mod.run(args)
    assert rc == 3
    report = run_mod.json.loads(out_path.read_text(encoding="utf-8"))
    checks = {c["name"]: c for c in report["host_checks"]}
    assert checks["camera_flash_benchmark"]["pass"] is False
    assert checks["camera_flash_benchmark"]["details"]["status"] == "error"
