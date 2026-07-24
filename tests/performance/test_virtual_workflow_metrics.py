from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import characterize_execution_persistence as persistence
from tools import run_qt_event_loop_probe as probe_cli
from tools.virtual_workflows.metrics import (
    NamedPhaseRecorder,
    ProcessResourceSampler,
    QtEventLoopProbe,
    linear_slope,
    percentile,
    summarize_samples,
)
from tools.virtual_workflows.report import (
    collect_environment_identity,
    validate_report_v1,
    write_report_atomic,
)
from tools.virtual_workflows.scenarios import _InstanceInstrumentation


pytestmark = pytest.mark.virtual_workflow
REPO_ROOT = Path(__file__).resolve().parents[2]


class ManualClock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        return self.value

    def advance_ms(self, milliseconds):
        self.value += int(milliseconds * 1_000_000)


class FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect(self, callback):
        self.callbacks.remove(callback)

    def emit(self):
        for callback in list(self.callbacks):
            callback()


def test_percentile_handles_empty_singleton_and_interpolation():
    assert percentile([], 0.95) == 0.0
    assert percentile([4], 0.95) == 4.0
    assert percentile([0, 10], 0.50) == 5.0
    assert percentile(range(100), 0.95) == pytest.approx(94.05)


@pytest.mark.parametrize("quantile", [-0.01, 1.01, float("nan"), True, "0.5"])
def test_percentile_rejects_invalid_quantiles(quantile):
    with pytest.raises(ValueError, match="quantile"):
        percentile([1, 2], quantile)


@pytest.mark.parametrize("sample", [float("nan"), float("inf"), True, "1"])
def test_statistics_reject_non_finite_or_non_numeric_samples(sample):
    with pytest.raises(ValueError, match="samples"):
        summarize_samples([1, sample])


def test_summary_uses_strict_threshold_bands_and_stable_slope():
    summary = summarize_samples(
        [25, 50, 51, 1000, 1001],
        bands_ms=(25, 50, 100, 1000),
    )

    assert summary["counts_strictly_above_ms"] == {
        "25": 4,
        "50": 3,
        "100": 2,
        "1000": 1,
    }
    assert linear_slope([1, 3, 5, 7]) == pytest.approx(2.0)
    assert summarize_samples([], bands_ms=())["linear_slope_per_sample"] == 0.0


def test_summary_rejects_invalid_threshold_bands():
    with pytest.raises(ValueError, match="non-negative"):
        summarize_samples([1], bands_ms=(-1,))
    with pytest.raises(ValueError, match="unique"):
        summarize_samples([1], bands_ms=(25, 25))


def test_named_phases_record_nesting_outcome_and_best_overlap():
    clock = ManualClock()
    recorder = NamedPhaseRecorder(clock_ns=clock, max_records=4)

    with recorder.phase("outer", {"kind": "test"}):
        clock.advance_ms(10)
        with recorder.phase("inner"):
            clock.advance_ms(20)
        clock.advance_ms(30)

    snapshot = recorder.snapshot()
    records = {record["name"]: record for record in snapshot["records"]}
    assert records["outer"]["duration_ms"] == 60
    assert records["inner"]["duration_ms"] == 20
    assert records["inner"]["depth"] == 1
    assert records["outer"]["outcome"] == "ok"
    assert recorder.best_overlap(15_000_000, 25_000_000)["name"] == "inner"
    assert recorder.current_phase() is None


def test_named_phase_records_exception_and_bounded_history():
    clock = ManualClock()
    recorder = NamedPhaseRecorder(clock_ns=clock, max_records=2)

    with pytest.raises(RuntimeError, match="injected"):
        with recorder.phase("failed"):
            clock.advance_ms(1)
            raise RuntimeError("injected")
    failed = recorder.snapshot()["records"][0]
    assert failed["outcome"] == "exception"
    assert failed["error_type"] == "RuntimeError"
    for name in ("second", "third"):
        with recorder.phase(name):
            clock.advance_ms(1)

    snapshot = recorder.snapshot()
    assert [record["name"] for record in snapshot["records"]] == [
        "second",
        "third",
    ]
    assert snapshot["dropped_records"] == 1
    assert snapshot["records"][0]["outcome"] == "ok"


def test_connected_slot_instrumentation_measures_and_restores_original():
    clock = ManualClock()
    recorder = NamedPhaseRecorder(clock_ns=clock)
    signal = FakeSignal()

    class Target:
        calls = 0

        def update_pressure(self):
            self.calls += 1
            clock.advance_ms(7)

    target = Target()
    original = target.update_pressure
    signal.connect(original)
    instrumentation = _InstanceInstrumentation(
        recorder,
        inject_ms=0,
        inject_after_completion=1,
        completed_count=lambda: 0,
    )

    instrumentation.wrap_connected_slot(
        target,
        "update_pressure",
        signal,
        "ui.pressure_render",
    )
    signal.emit()

    pressure = recorder.snapshot()["duration_by_name_ms"]["ui.pressure_render"]
    assert target.calls == 1
    assert pressure["count"] == 1
    assert pressure["p95"] == 7

    instrumentation.restore()
    assert target.update_pressure == original
    signal.emit()
    assert target.calls == 2
    assert recorder.snapshot()["duration_by_name_ms"]["ui.pressure_render"][
        "count"
    ] == 1


class FakeProcess:
    def __init__(self):
        self.cpu = (1.0, 2.0)
        self.rss = 100
        self.io = (1000, 2000)
        self.threads = 3

    def cpu_times(self):
        return SimpleNamespace(user=self.cpu[0], system=self.cpu[1])

    def memory_info(self):
        return SimpleNamespace(rss=self.rss)

    def io_counters(self):
        return SimpleNamespace(read_bytes=self.io[0], write_bytes=self.io[1])

    def num_threads(self):
        return self.threads


def test_resource_sampler_reports_cpu_rss_io_and_threads():
    process = FakeProcess()
    sampler = ProcessResourceSampler(process=process)
    sampler.start()
    process.cpu = (1.25, 2.25)
    process.rss = 175
    process.io = (1400, 2600)
    process.threads = 5
    sampler.sample()
    process.cpu = (1.5, 2.5)
    process.rss = 150
    process.io = (1800, 3000)
    sampler.stop()

    snapshot = sampler.snapshot()
    assert snapshot["status"] == "measured"
    assert snapshot["values"]["process_cpu_time_ms_delta"] == 1000
    assert snapshot["values"]["initial_rss_bytes"] == 100
    assert snapshot["values"]["final_rss_bytes"] == 150
    assert snapshot["values"]["rss_growth_bytes"] == 50
    assert snapshot["values"]["rss_growth_ratio"] == 1.5
    assert snapshot["values"]["peak_rss_bytes"] == 175
    assert snapshot["values"]["read_bytes_delta"] == 800
    assert snapshot["values"]["write_bytes_delta"] == 1000
    assert snapshot["values"]["maximum_thread_count"] == 5


def test_resource_sampler_degrades_when_psutil_is_unavailable():
    sampler = ProcessResourceSampler(psutil_module=None)

    sampler.start()
    sampler.stop()

    snapshot = sampler.snapshot()
    assert snapshot["status"] == "not_available"
    assert snapshot["values"]["sample_count"] == 0
    assert "psutil unavailable" in snapshot["values"]["availability_reasons"]


def test_resource_sampler_reports_partial_when_counter_is_unsupported():
    process = FakeProcess()

    def unsupported_io():
        raise NotImplementedError("platform counter missing")

    process.io_counters = unsupported_io
    sampler = ProcessResourceSampler(process=process)
    sampler.start()
    sampler.stop()

    snapshot = sampler.snapshot()
    assert snapshot["status"] == "partial"
    assert snapshot["values"]["read_bytes_delta"] is None
    assert snapshot["values"]["write_bytes_delta"] is None
    assert any(
        "io_counters unavailable" in reason
        for reason in snapshot["values"]["availability_reasons"]
    )


def test_synthetic_heartbeat_has_no_false_stall_and_counts_real_gap():
    clock = ManualClock()
    probe = QtEventLoopProbe(
        heartbeat_interval_ms=10,
        threshold_bands_ms=(25, 50),
        clock_ns=clock,
        max_samples=4,
    )

    probe.record_heartbeat(now_ns=0)
    for _ in range(3):
        clock.advance_ms(10)
        probe.record_heartbeat(now_ns=clock())
    clock.advance_ms(60)
    probe.record_heartbeat(now_ns=clock())

    snapshot = probe.snapshot()
    summary = snapshot["event_loop_gap_ms"]
    assert summary["counts_strictly_above_ms"] == {"25": 1, "50": 1}
    assert len(snapshot["stall_events"]) == 1
    assert snapshot["scheduling_lateness_ms"]["maximum"] == 50
    assert snapshot["retention"]["dropped_gap_samples"] == 0


def test_heartbeat_sample_history_is_bounded():
    clock = ManualClock()
    probe = QtEventLoopProbe(clock_ns=clock, max_samples=2)
    probe.record_heartbeat(now_ns=0)
    for _ in range(4):
        clock.advance_ms(10)
        probe.record_heartbeat(now_ns=clock())

    snapshot = probe.snapshot()
    assert snapshot["raw_event_loop_gap_ms"] == [10, 10]
    assert snapshot["retention"]["dropped_gap_samples"] == 2


def test_slice0_distribution_adapter_preserves_existing_shape():
    assert persistence._distribution([1.0, 2.0, 3.0]) == {
        "count": 3,
        "mean": 2.0,
        "p50": 2.0,
        "p95": 2.9,
        "p99": 2.98,
        "maximum": 3.0,
    }


def test_identical_report_payloads_write_identical_bytes(tmp_path):
    identity = collect_environment_identity(REPO_ROOT)
    payload = probe_cli._base_report(
        identity=identity,
        started_at="2026-07-23T12:00:00Z",
        warmup_runs=0,
        measured_runs=1,
        stalls_ms=(50,),
        heartbeat_interval_ms=10,
        stack_capture_ms=250,
        observer_interval_ms=5,
        resource_interval_ms=100,
    )
    payload["run"]["run_id"] = "deterministic"
    payload["run"]["ended_at_utc"] = "2026-07-23T12:00:01Z"
    payload["run"]["duration_ms"] = 1000.0

    first = write_report_atomic(tmp_path / "first.json", payload)
    second = write_report_atomic(tmp_path / "second.json", payload)

    assert first.read_bytes() == second.read_bytes()
    validate_report_v1(json.loads(first.read_text(encoding="utf-8")))


def test_probe_cli_has_no_production_or_hardware_imports():
    source_path = REPO_ROOT / "tools" / "run_qt_event_loop_probe.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots.isdisjoint(
        {
            "App",
            "Controller",
            "Model",
            "Machine_FreeRTOS",
            "serial",
            "RPi",
            "CalibrationClasses",
            "dfu_update",
            "update_and_restart",
        }
    )


def test_probe_cli_reports_setup_failure_for_non_real_qt(tmp_path, monkeypatch):
    identity = collect_environment_identity(REPO_ROOT)
    identity["environment"]["qt"]["binding"] = "stub"
    monkeypatch.setattr(
        probe_cli,
        "collect_environment_identity",
        lambda _repo_root: identity,
    )

    exit_code, report_path = probe_cli.run_probe(
        output_root=tmp_path,
        warmup_runs=0,
        measured_runs=1,
        stalls_ms=(50,),
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert exit_code == 3
    assert report["classification"]["status"] == "fail"
    assert "real PySide6 is required" in report["classification"]["reasons"][0]


def test_probe_cli_reports_correctness_failure(tmp_path, monkeypatch, qapp):
    def fail_iteration(*_args, **_kwargs):
        raise probe_cli.ProbeCorrectnessError("injected verification failure")

    monkeypatch.setattr(probe_cli, "_run_probe_iteration", fail_iteration)

    exit_code, report_path = probe_cli.run_probe(
        output_root=tmp_path,
        warmup_runs=0,
        measured_runs=1,
        stalls_ms=(50,),
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert report["classification"]["status"] == "fail"
    assert "injected verification failure" in report["classification"]["reasons"][0]


def test_real_qt_probe_surfaces_cleanup_failure(qapp, monkeypatch):
    original_stop = QtEventLoopProbe.stop

    def fail_after_cleanup(self, timeout_s=1.0):
        original_stop(self, timeout_s)
        raise RuntimeError("injected cleanup failure")

    monkeypatch.setattr(QtEventLoopProbe, "stop", fail_after_cleanup)

    with pytest.raises(probe_cli.ProbeCorrectnessError, match="cleanup"):
        probe_cli._run_probe_iteration(
            qapp,
            stalls_ms=(50,),
            heartbeat_interval_ms=10,
            stack_capture_ms=250,
            observer_interval_ms=5,
            resource_interval_ms=100,
        )


def test_real_qt_probe_detects_and_attributes_stalls_and_cleans_up(qapp):
    identity = collect_environment_identity(REPO_ROOT)
    if identity["environment"]["qt"]["binding"] != "real":
        pytest.skip("real PySide6 is required for the event-loop integration test")

    result = probe_cli._run_probe_iteration(
        qapp,
        stalls_ms=(50, 100, 250, 350),
        heartbeat_interval_ms=10,
        stack_capture_ms=250,
        observer_interval_ms=5,
        resource_interval_ms=100,
    )

    assert all(check["detected"] for check in result["injected_stall_checks"])
    captures = result["responsiveness"]["stack_captures"]
    assert any(
        (capture.get("phase") or {}).get("name") == "injected_stall_4_350ms"
        and "time.sleep" in capture["stack"]
        for capture in captures
    )
    assert result["responsiveness"]["shutdown"] == {
        "timer_active": False,
        "observer_thread_alive": False,
    }
    assert result["responsiveness"]["probe_callback_cost_ms"]["count"] > 0
    assert result["resources"]["status"] in {"measured", "partial"}
