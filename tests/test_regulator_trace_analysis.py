import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_TOOL = REPO_ROOT / "tools" / "regulator_trace_analysis.py"


def _load_analysis():
    spec = importlib.util.spec_from_file_location("regulator_trace_analysis_test_mod", ANALYSIS_TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _trace(*, summary=None, run_id=123, test_id=2102, name="pressure_recovery_trace_print_repeated"):
    return {
        "run_id": run_id,
        "test_id": test_id,
        "name": name,
        "summary": dict(summary or {}),
        "samples": [
            {
                "dt_ms": 0,
                "raw_pressure": 2512,
                "control_pressure": 2512,
                "avg_pressure": 2512,
                "target": 2512,
                "error": 0,
                "derror": 0,
                "requested_hz": 1000,
                "applied_hz": 1000,
                "flags": 0x01,
                "ff_boost_hz": 0,
            },
            {
                "dt_ms": 10,
                "raw_pressure": 2492,
                "control_pressure": 2492,
                "avg_pressure": 2502,
                "target": 2512,
                "error": -20,
                "derror": -20,
                "requested_hz": 3500,
                "applied_hz": 3000,
                "flags": 0x10,
                "ff_boost_hz": 128,
            },
            {
                "dt_ms": 45,
                "raw_pressure": 2517,
                "control_pressure": 2517,
                "avg_pressure": 2510,
                "target": 2512,
                "error": 5,
                "derror": 25,
                "requested_hz": 1000,
                "applied_hz": 1000,
                "flags": 0x01,
                "ff_boost_hz": 0,
            },
            {
                "dt_ms": 55,
                "raw_pressure": 2508,
                "control_pressure": 2508,
                "avg_pressure": 2510,
                "target": 2512,
                "error": -4,
                "derror": -9,
                "requested_hz": 1200,
                "applied_hz": 1200,
                "flags": 0x21,
                "ff_boost_hz": 0,
            },
            {
                "dt_ms": 90,
                "raw_pressure": 2520,
                "control_pressure": 2520,
                "avg_pressure": 2514,
                "target": 2512,
                "error": 8,
                "derror": 12,
                "requested_hz": 1000,
                "applied_hz": 1000,
                "flags": 0x11,
                "ff_boost_hz": 0,
            },
        ],
        "events": [
            {"dt_ms": 5, "event_type": 2, "event_name": "pulse_start", "value0": 1300, "value1": 2512},
            {"dt_ms": 7, "event_type": 3, "event_name": "pulse_end", "value0": 1300, "value1": 2492},
            {"dt_ms": 45, "event_type": 8, "event_name": "ready_enter", "value0": 0, "value1": 0},
            {"dt_ms": 55, "event_type": 2, "event_name": "pulse_start", "value0": 1300, "value1": 2517},
            {"dt_ms": 57, "event_type": 3, "event_name": "pulse_end", "value0": 1300, "value1": 2508},
            {"dt_ms": 90, "event_type": 8, "event_name": "ready_enter", "value0": 0, "value1": 0},
        ],
    }


def _write_run(run_dir, *, run_id="run_a", candidate="candidate_a", trace=None):
    run_dir.mkdir(parents=True)
    trace_payload = trace or _trace(
        summary={"ready_miss": 0, "rec_w": 42, "under": 24, "over": 9, "slip_w": 6, "zero": 2}
    )
    trace_path = run_dir / "raw_selftest_trace_2102.json"
    trace_path.write_text(json.dumps(trace_payload), encoding="utf-8")
    run_meta = {
        "schema_version": 1,
        "run_id": run_id,
        "session_id": "session_a",
        "mode": "stream",
        "candidate_profile_id": candidate,
        "conditions": {"frequency_hz": 20},
        "outputs": {
            "trace_files": ["raw_selftest_trace_2102.json"],
            "analysis_json": None,
            "summary_csv": None,
            "plots": [],
        },
        "outcome": {"status": "completed", "restored_previous_profile": True, "error_message": ""},
    }
    (run_dir / "run_meta.json").write_text(json.dumps(run_meta), encoding="utf-8")
    return trace_path


def _fake_plot_renderer(trace_path, out_dir, dpi=150, analysis_dir=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    analysis_base = analysis_dir or out_dir
    analysis_base.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{Path(trace_path).stem}.png"
    analysis_json = analysis_base / f"{Path(trace_path).stem}.analysis.json"
    per_pulse_csv = analysis_base / f"{Path(trace_path).stem}.per_pulse.csv"
    png.write_bytes(b"png")
    analysis_json.write_text("{}", encoding="utf-8")
    per_pulse_csv.write_text("pulse_index\n", encoding="utf-8")
    return png, analysis_json, per_pulse_csv, {}


def test_metric_alias_normalization_and_default_score():
    mod = _load_analysis()
    analysis = mod.analyze_trace(
        _trace(summary={"ready_miss": 0, "rec_w": 42, "under": 24, "over": 9, "slip_w": 6, "zero": 2})
    )

    metrics = analysis["normalized_metrics"]

    assert metrics["ready_miss_count"] == 0
    assert metrics["worst_recovery_ms"] == 42
    assert metrics["median_recovery_ms"] == pytest.approx(35.5)
    assert metrics["max_undershoot_raw"] == 24
    assert metrics["max_overshoot_raw"] == 9
    assert metrics["pressure_ok_duty_ratio"] == pytest.approx(0.8)
    assert metrics["recovery_active_duty_ratio"] == pytest.approx(0.4)
    assert metrics["rejected_sample_ratio"] == pytest.approx(0.2)
    assert metrics["requested_applied_hz_saturation_ratio"] == pytest.approx(0.2)
    assert metrics["max_requested_applied_hz_gap"] == 500
    assert analysis["score_valid"] is True
    assert analysis["score"] == pytest.approx(168.0)


def test_derived_fallback_metrics_when_firmware_aliases_are_absent():
    mod = _load_analysis()
    analysis = mod.analyze_trace(_trace(summary={"ready_miss_count": 0}), conditions={"frequency_hz": 20})
    metrics = analysis["normalized_metrics"]

    assert metrics["worst_recovery_ms"] == pytest.approx(38.0)
    assert metrics["median_recovery_ms"] == pytest.approx(35.5)
    assert metrics["max_undershoot_raw"] == pytest.approx(20.0)
    assert metrics["max_overshoot_raw"] == pytest.approx(8.0)
    assert metrics["worst_deadline_slip_ms"] == pytest.approx(0.0)
    assert metrics["zero_crossing_count"] == 3
    assert analysis["score_valid"] is True


def test_score_config_validation_rejects_unknown_or_invalid_weights():
    mod = _load_analysis()

    weights = mod.validate_score_weights({"ready_miss_count": 2, "max_overshoot_raw": 0})

    assert weights["ready_miss_count"] == 2
    assert weights["max_overshoot_raw"] == 0
    with pytest.raises(mod.RegulatorTraceAnalysisError, match="unknown score metric"):
        mod.validate_score_weights({"not_a_metric": 1})
    with pytest.raises(mod.RegulatorTraceAnalysisError, match="nonnegative"):
        mod.validate_score_weights({"ready_miss_count": -1})


def test_discover_runs_supports_run_session_root_and_direct_trace(tmp_path):
    mod = _load_analysis()
    root = tmp_path / "local" / "regulator_optimization"
    run_a = root / "session_a" / "run_a"
    run_b = root / "session_a" / "run_b"
    trace_a = _write_run(run_a, run_id="run_a", candidate="candidate_a")
    _write_run(run_b, run_id="run_b", candidate="candidate_b")

    assert len(mod.discover_runs([run_a])) == 1
    assert len(mod.discover_runs([root / "session_a"])) == 2
    assert len(mod.discover_runs([root])) == 2
    direct = mod.discover_runs([trace_a])

    assert len(direct) == 1
    assert direct[0].run_dir is None
    assert direct[0].trace_files == (trace_a,)


def test_analyze_inputs_writes_outputs_and_updates_run_meta_without_touching_trace(tmp_path):
    mod = _load_analysis()
    run_dir = tmp_path / "session_a" / "run_a"
    trace_path = _write_run(run_dir)
    original_trace = trace_path.read_text(encoding="utf-8")

    result = mod.analyze_inputs([run_dir], make_plots=True, plot_renderer=_fake_plot_renderer)

    analysis_dir = run_dir / "analysis"
    assert result["output_dir"] == analysis_dir
    assert (analysis_dir / "run_analysis.json").exists()
    assert (analysis_dir / "run_summary.csv").exists()
    assert (analysis_dir / "per_pulse.csv").exists()
    assert (analysis_dir / "candidate_ranking.json").exists()
    assert (analysis_dir / "candidate_ranking.csv").exists()
    assert (analysis_dir / "all_pulses.csv").exists()
    assert (analysis_dir / "plots" / "raw_selftest_trace_2102.png").exists()
    assert (analysis_dir / "raw_selftest_trace_2102.analysis.json").exists()
    assert (analysis_dir / "raw_selftest_trace_2102.per_pulse.csv").exists()
    trace_analysis = json.loads((analysis_dir / "raw_selftest_trace_2102.analysis.json").read_text(encoding="utf-8"))
    assert trace_analysis["normalized_metrics"]["ready_miss_count"] == 0
    assert trace_path.read_text(encoding="utf-8") == original_trace

    run_meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
    assert run_meta["outputs"]["analysis_json"] == "analysis\\run_analysis.json" or run_meta["outputs"][
        "analysis_json"
    ] == "analysis/run_analysis.json"
    assert run_meta["outputs"]["summary_csv"] == "analysis\\run_summary.csv" or run_meta["outputs"][
        "summary_csv"
    ] == "analysis/run_summary.csv"
    assert run_meta["outputs"]["plots"]


def test_ranking_sorts_invalid_scores_last(tmp_path):
    mod = _load_analysis()
    root = tmp_path / "runs"
    run_good = root / "session_a" / "run_good"
    run_bad = root / "session_a" / "run_bad"
    _write_run(run_good, run_id="good", candidate="candidate_good")
    _write_run(
        run_bad,
        run_id="bad",
        candidate="candidate_bad",
        trace={
            "run_id": 123,
            "test_id": 2102,
            "name": "pressure_recovery_trace_print_repeated",
            "summary": {},
            "samples": [],
            "events": [],
        },
    )

    result = mod.analyze_inputs([root], output_dir=tmp_path / "analysis", make_plots=False)
    ranking = result["ranking"]

    assert ranking[0]["run_id"] == "good"
    assert ranking[0]["rank"] == 1
    assert ranking[-1]["run_id"] == "bad"
    assert ranking[-1]["score_valid"] is False
    assert ranking[-1]["rank"] is None
    assert (run_good / "analysis" / "raw_selftest_trace_2102.analysis.json").exists()
    assert (run_good / "analysis" / "raw_selftest_trace_2102.per_pulse.csv").exists()
    assert not (run_good / "analysis" / "plots").exists()
    with (tmp_path / "analysis" / "candidate_ranking.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["run_id"] == "good"
