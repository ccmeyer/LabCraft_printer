import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_SELFTEST_PATH = REPO_ROOT / "tools" / "run_selftest.py"


def _load_run_selftest():
    spec = importlib.util.spec_from_file_location("run_selftest_mod_metrics", RUN_SELFTEST_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_parse_metrics_keeps_rtos_memory_headroom_keys():
    mod = _load_run_selftest()
    raw = "heap_now=8192;heap_min=6144;stk_min=96;stk_task=Status;task_n=9;core_miss=0;preg_n=2;trunc=0;stk_ovf=0"

    metrics = mod.parse_metrics(raw)

    assert metrics == {
        "heap_now": 8192,
        "heap_min": 6144,
        "stk_min": 96,
        "stk_task": "Status",
        "task_n": 9,
        "core_miss": 0,
        "preg_n": 2,
        "trunc": 0,
        "stk_ovf": 0,
    }


def test_parse_metrics_keeps_crash_record_keys():
    mod = _load_run_selftest()
    raw = "pending=0;sticky=1;fault=none;task=none;reset=pin;boot=42;fault_ct=3;wdg_ct=2;sticky_ct=4;raw_sr=3;boot_stage=hello_ack;wdg_late=status"

    metrics = mod.parse_metrics(raw)

    assert metrics == {
        "pending": 0,
        "sticky": 1,
        "fault": "none",
        "task": "none",
        "reset": "pin",
        "boot": 42,
        "fault_ct": 3,
        "wdg_ct": 2,
        "sticky_ct": 4,
        "raw_sr": 3,
        "boot_stage": "hello_ack",
        "wdg_late": "status",
    }


def test_parse_metrics_keeps_watchdog_supervisor_keys():
    mod = _load_run_selftest()
    raw = "enabled=0;arm_result=sticky_status_skip;timeout_ms=4000;init_timeout_ms=20;req_n=0;live_n=0;late_task=none;raw_sr=3;sticky_ct=2;recovery_boot=1"

    metrics = mod.parse_metrics(raw)

    assert metrics == {
        "enabled": 0,
        "arm_result": "sticky_status_skip",
        "timeout_ms": 4000,
        "init_timeout_ms": 20,
        "req_n": 0,
        "live_n": 0,
        "late_task": "none",
        "raw_sr": 3,
        "sticky_ct": 2,
        "recovery_boot": 1,
    }
