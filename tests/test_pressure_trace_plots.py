import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLOT_TOOL = REPO_ROOT / "tools" / "plot_pressure_traces.py"


def _load_plot_tool():
    spec = importlib.util.spec_from_file_location("plot_pressure_traces_mod", PLOT_TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_render_trace_file_writes_outputs(tmp_path):
    mod = _load_plot_tool()
    trace_path = tmp_path / "trace.json"
    out_dir = tmp_path / "plots"

    trace = {
        "run_id": 123,
        "test_id": 2104,
        "name": "pressure_recovery_trace_dual_interleaved",
        "summary": {"rec_w": 58, "slip_w": 336},
        "samples": [
            {
                "dt_ms": 0,
                "raw_pressure": 2508,
                "control_pressure": 2508,
                "avg_pressure": 2506,
                "target": 2512,
                "error": -4,
                "derror": 0,
                "requested_hz": 1200,
                "applied_hz": 1200,
                "flags": 0x03,
                "ff_boost_hz": 0,
            },
            {
                "dt_ms": 5,
                "raw_pressure": 2485,
                "control_pressure": 2485,
                "avg_pressure": 2496,
                "target": 2512,
                "error": -27,
                "derror": -23,
                "requested_hz": 3500,
                "applied_hz": 3000,
                "flags": 0x13,
                "ff_boost_hz": 256,
            },
            {
                "dt_ms": 10,
                "raw_pressure": 2501,
                "control_pressure": 2501,
                "avg_pressure": 2498,
                "target": 2512,
                "error": -11,
                "derror": 16,
                "requested_hz": 2200,
                "applied_hz": 2200,
                "flags": 0x11,
                "ff_boost_hz": 128,
            },
        ],
        "events": [
            {"dt_ms": 4, "event_type": 2, "event_name": "pulse_start", "value0": 1300, "value1": 2508},
            {"dt_ms": 6, "event_type": 3, "event_name": "pulse_end", "value0": 1300, "value1": 2485},
            {"dt_ms": 7, "event_type": 6, "event_name": "recovery_start", "value0": 512, "value1": 4},
        ],
    }
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    out_path, analysis_json, per_pulse_csv, analysis = mod.render_trace_file(trace_path, out_dir, dpi=100)

    assert out_path.exists()
    assert out_path.suffix == ".png"
    assert out_path.stat().st_size > 0
    assert analysis_json.exists()
    assert analysis_json.suffix == ".json"
    assert per_pulse_csv.exists()
    assert per_pulse_csv.suffix == ".csv"
    assert isinstance(analysis, dict)
    assert analysis.get("test_id") == 2104
    assert analysis.get("global", {}).get("sample_count") == 3
    assert isinstance(analysis.get("per_pulse"), list)


def test_render_sweep_summary_writes_outputs(tmp_path):
    mod = _load_plot_tool()
    sweep_path = tmp_path / "sweep.json"
    out_dir = tmp_path / "plots"
    sweep_path.write_text(
        json.dumps(
            {
                "run_id": 123,
                "suite_id": 2301,
                "summary": {"best_param": 2},
                "combos": [
                    {"param": 1, "scenario": 1, "score": 950, "ready_miss": 1, "slip_w": 200, "over": 15, "under": 40},
                    {"param": 1, "scenario": 2, "score": 620, "ready_miss": 0, "slip_w": 120, "over": 12, "under": 28},
                    {"param": 2, "scenario": 1, "score": 410, "ready_miss": 0, "slip_w": 80, "over": 10, "under": 20},
                    {"param": 2, "scenario": 2, "score": 360, "ready_miss": 0, "slip_w": 70, "over": 9, "under": 16},
                ],
            }
        ),
        encoding="utf-8",
    )

    outputs = mod.render_sweep_summary(sweep_path, out_dir, dpi=100)

    assert len(outputs) == 3
    for out in outputs:
        assert out.exists()
        assert out.suffix == ".png"
        assert out.stat().st_size > 0
