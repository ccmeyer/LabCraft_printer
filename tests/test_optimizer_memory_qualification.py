import gc
import json
import os
from types import SimpleNamespace

import pytest

from tools import optimizer_memory_qualification as memory


def test_os_memory_sample_reports_headroom_and_high_water():
    sample = memory.memory_sample(os.getpid())
    assert 0 < sample["rss_bytes"] <= sample["peak_rss_bytes"]
    assert 0 < sample["available_bytes"] <= sample["total_bytes"]


@pytest.mark.parametrize("values,status", [
    ([100, 100, 100, 140, 140, 140], "inconclusive"),
    ([180, 181, 179, 182, 180, 181], "stable_within_bound"),
    ([100, 115, 130, 145, 160, 175], "growth_requires_review"),
    ([100, 100, 100, 100, 100], "inconclusive"),
])
def test_growth_screen_distinguishes_plateau_growth_and_insufficient_samples(values, status):
    # The first sequence still exceeds the retained-growth allowance: do not
    # declare an early allocator expansion stable without more settled rounds.
    actual = memory.trend([v*memory.MIB for v in values], absolute_tolerance=32*memory.MIB,
                          slope_tolerance=12*memory.MIB)
    assert actual["status"] == status


def test_assessment_excludes_warmup_and_tolerates_allocator_plateau():
    points = [dict(warmup=True, rss_bytes=10, python_allocated_blocks=10)] + [
        dict(warmup=False, rss_bytes=(400+i%2)*memory.MIB, python_allocated_blocks=200000+i)
        for i in range(6)]
    result = memory.assess(points)
    assert all(v["status"] == "stable_within_bound" for v in result.values())
    assert result["rss"]["samples"] == 6


def test_python_growth_is_reported_even_if_resident_memory_is_flat():
    points = [dict(warmup=False, rss_bytes=400*memory.MIB, python_allocated_blocks=20000+i*6000)
              for i in range(6)]
    result = memory.assess(points)
    assert result["rss"]["status"] == "stable_within_bound"
    assert result["python_blocks"]["status"] == "growth_requires_review"


def fake_sample(available=900*memory.MIB):
    return dict(rss_bytes=100*memory.MIB, peak_rss_bytes=120*memory.MIB,
                total_bytes=1024*memory.MIB, available_bytes=available, swap_bytes=0)


@pytest.mark.parametrize("failure", ["low_memory", "timeout", "sample_failure"])
def test_supervisor_cooperatively_stops_only_owned_child(tmp_path, monkeypatch, failure):
    output = tmp_path/"memory.json"
    args = SimpleNamespace(output=str(output), max_seconds=-1 if failure == "timeout" else 60)
    calls = []
    class Child:
        pid = 987654
        returncode = None
        def __init__(self, *a, **kw): pass
        def poll(self): return self.returncode
        def wait(self, timeout):
            assert output.with_suffix(".cancel").exists()
            self.returncode = 0
        def terminate(self): pytest.fail("Cooperative child must not be terminated")
    def sample(pid):
        calls.append(pid)
        if len(calls) == 1: return fake_sample()
        if failure == "sample_failure": raise OSError("injected sampler failure")
        return fake_sample(100*memory.MIB if failure == "low_memory" else 900*memory.MIB)
    monkeypatch.setattr(memory, "memory_sample", sample)
    monkeypatch.setattr(memory.subprocess, "Popen", Child)
    assert memory.supervise(args, ["unused"]) == 1
    evidence = json.loads(output.read_text())
    record = evidence["supervisor"]
    assert evidence["status"] == "failed"
    assert record["cleanup"] == ["cooperative cancellation requested"]
    assert record["owned_process_exited"]
    assert calls == [os.getpid(), Child.pid]


def test_refuses_to_overwrite_evidence_or_launch_under_memory_pressure(tmp_path, monkeypatch):
    output = tmp_path/"existing.json"; output.write_text("preserved")
    args = SimpleNamespace(output=str(output), max_seconds=60)
    with pytest.raises(ValueError, match="existing evidence"):
        memory.supervise(args, [])
    assert output.read_text() == "preserved"
    args.output = str(tmp_path/"low.json")
    monkeypatch.setattr(memory, "memory_sample", lambda pid: fake_sample(100*memory.MIB))
    monkeypatch.setattr(memory.subprocess, "Popen", lambda *a, **kw: pytest.fail("Must refuse before launch"))
    with pytest.raises(RuntimeError, match="Insufficient"):
        memory.supervise(args, [])
    assert json.loads((tmp_path/"low.json").read_text())["status"] == "failed"


def test_supervisor_retains_growth_review_verdict_and_records_clean_exit(tmp_path, monkeypatch):
    output = tmp_path/"growth.json"
    args = SimpleNamespace(output=str(output), max_seconds=60)
    class Child:
        pid = 987654
        returncode = 1
        def __init__(self, *a, **kw):
            memory.write_json(output, dict(status="review_required", complete=True))
        def poll(self): return self.returncode
    monkeypatch.setattr(memory, "memory_sample", lambda pid: fake_sample())
    monkeypatch.setattr(memory.subprocess, "Popen", Child)
    assert memory.supervise(args, ["unused"]) == 1
    evidence = json.loads(output.read_text())
    assert evidence["status"] == "review_required"
    assert evidence["supervisor"]["cleanup"] == []
    assert evidence["supervisor"]["owned_process_exited"]


@pytest.mark.parametrize("inject_failure", [False, True])
def test_persistent_session_real_qt_repeats_cancels_closes_and_preserves_gc(qapp, tmp_path, monkeypatch, inject_failure):
    from OptimizationJobs import optimization_job_manager
    from PySide6.QtCore import QCoreApplication, QEvent
    args = SimpleNamespace(output=str(tmp_path/"session.json"), fixture_root=None,
                           warmups=1, rounds=2, settle_seconds=.01)
    policy = gc.isenabled(), gc.get_threshold()
    if inject_failure:
        monkeypatch.setattr(memory, "state_digest", lambda model: (_ for _ in ()).throw(RuntimeError("injected digest failure")))
    try:
        if inject_failure:
            with pytest.raises(RuntimeError, match="injected digest failure"):
                memory.run_session(qapp, args, [("groups_import", True)])
            result = json.loads((tmp_path/"session.json").read_text())
            assert not result["complete"] and result["status"] == "failed"
        else:
            result = memory.run_session(qapp, args, [("groups_import", True)])
            assert result["complete"] and result["status"] == "inconclusive"
            assert len(result["interactions"]) == 3 and len(result["endpoints"]) == 3
            assert len({r["state_sha256"] for r in result["interactions"]}) == 1
            assert all(r["live_closed_editors"] == 0 for r in result["endpoints"])
            assert all(r["cancellation"]["cancel_ms"] is not None and r["close_active"]["cancel_ms"] is not None
                       for r in result["interactions"])
        assert result["worker_stopped"]
        assert (gc.isenabled(), gc.get_threshold()) == policy
    finally:
        service = optimization_job_manager()
        qapp.removeEventFilter(service)
        qapp._optimization_job_manager = None
        service.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
