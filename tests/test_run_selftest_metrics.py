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
    raw = "heap_now=8192;heap_min=6144;stk_min=96;stk_task=Status;task_n=9;core_miss=0;preg_n=2;trunc=0"

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
    }
