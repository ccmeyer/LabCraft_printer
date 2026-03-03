import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_SELFTEST_PATH = REPO_ROOT / "tools" / "run_selftest.py"


def _load_run_selftest():
    spec = importlib.util.spec_from_file_location("run_selftest_mod_sweep", RUN_SELFTEST_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_write_sweep_artifacts_sorts_by_score_and_writes_csv(tmp_path):
    mod = _load_run_selftest()
    out = tmp_path / "selftest.json"
    results = [
        {
            "test_id": 2311,
            "name": "pressure_sweep_s2301_p2_c1",
            "pass": False,
            "metrics": {
                "suite": 2301,
                "param": 2,
                "scenario": 1,
                "mode": 0,
                "target_raw": 2400,
                "pulse_us": 1300,
                "droplets": 10,
                "hz": 20,
                "base": 2395,
                "min": 2360,
                "max": 2420,
                "under": 40,
                "over": 20,
                "rec_w": 90,
                "rec_m": 40,
                "ready_miss": 1,
                "slip_w": 220,
                "slip_m": 110,
                "zero": 5,
                "rejects": 0,
                "sc": 50,
                "ec": 10,
                "trace": 0,
                "score": 2300,
            },
        },
        {
            "test_id": 2310,
            "name": "pressure_sweep_s2301_p1_c1",
            "pass": True,
            "metrics": {
                "suite": 2301,
                "param": 1,
                "scenario": 1,
                "mode": 0,
                "target_raw": 2400,
                "pulse_us": 1300,
                "droplets": 10,
                "hz": 20,
                "base": 2398,
                "min": 2385,
                "max": 2412,
                "under": 18,
                "over": 12,
                "rec_w": 45,
                "rec_m": 20,
                "ready_miss": 0,
                "slip_w": 80,
                "slip_m": 40,
                "zero": 2,
                "rejects": 0,
                "sc": 48,
                "ec": 10,
                "trace": 0,
                "score": 460,
            },
        },
        {
            "test_id": 2391,
            "name": "pressure_sweep_summary_s2301",
            "pass": False,
            "metrics": {
                "suite": 2301,
                "combos": 2,
                "pass_combo_count": 1,
                "best_param": 1,
                "best_score": 460,
                "worst_score": 2300,
                "trace_exported_count": 0,
            },
        },
    ]

    json_path, csv_path = mod._write_sweep_artifacts(str(out), 1234, results)
    assert json_path is not None
    assert csv_path is not None

    payload = mod.json.loads(Path(json_path).read_text(encoding="utf-8"))
    assert payload["suite_id"] == 2301
    assert payload["summary"]["best_param"] == 1
    assert len(payload["combos"]) == 2
    assert payload["combos"][0]["score"] <= payload["combos"][1]["score"]
    assert payload["combos"][0]["param"] == 1
    assert Path(csv_path).exists()
