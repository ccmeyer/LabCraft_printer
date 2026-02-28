import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_SELFTEST_PATH = REPO_ROOT / "tools" / "run_selftest.py"


def _load_run_selftest():
    spec = importlib.util.spec_from_file_location("run_selftest_mod_fastfail", RUN_SELFTEST_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_parse_metrics_empty_string_is_empty_dict():
    mod = _load_run_selftest()
    assert mod.parse_metrics("") == {}
