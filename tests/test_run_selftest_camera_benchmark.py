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

    def time(self) -> float:
        return 1700000000.0


def _frame_payload(mod, payload: bytes) -> bytes:
    return mod.frame_payload(payload)


def _hello_ack(mod) -> bytes:
    return _frame_payload(mod, bytes([mod.CMD_HELLO_ACK, 1]))


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


def test_summarize_cycles_basic():
    mod = _load_module(BENCH_PATH, "camera_flash_benchmark_mod_summary")
    cycles = [
        {
            "completed": True,
            "success_bool": True,
            "ack_seen_bool": True,
            "frame_selected_bool": True,
            "reason": "threshold",
            "trigger_to_ack_ms": 1.0,
            "ack_to_arm_ms": 0.1,
            "arm_to_frame_ms": 2.0,
            "trigger_to_frame_ms": 3.1,
            "cycle_total_ms": 3.4,
        },
        {
            "completed": True,
            "success_bool": True,
            "ack_seen_bool": True,
            "frame_selected_bool": True,
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
    assert summary["success_cycles"] == 2
    assert summary["success_rate"] == 1.0
    assert summary["ack_seen_cycles"] == 2
    assert summary["frame_selected_cycles"] == 2
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

    def fake_bench_run(_ser, _build_control, *, run_id, config):
        assert isinstance(config, FakeCfg)
        assert config.kwargs.get("mode") == "flash_only"
        assert config.kwargs.get("run_order") == "pre_selftest"
        assert config.kwargs.get("num_droplets") == 0
        return {
            "status": "ok",
            "summary": {"effective_fps": 9.5, "completed_cycles": 10},
            "cycles": [],
            "run_id": run_id,
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
