import json

from tools.qualification.artifacts import create_run_artifacts
from tools.qualification.valve_trace_artifacts import analyze_valve_trace, generate_valve_trace_artifacts


def _trace(name: str, test_id: int = 2474):
    return {
        "run_id": 123,
        "test_id": test_id,
        "name": name,
        "summary": {"m15": 10},
        "samples": [
            {"dt_ms": 0, "raw_pressure": 3385, "control_pressure": 3385, "avg_pressure": 3385, "target": 3386, "error": -1, "derror": 0, "requested_hz": 0, "applied_hz": 0, "flags": 0x08, "ff_boost_hz": 0},
            {"dt_ms": 5, "raw_pressure": 3386, "control_pressure": 3386, "avg_pressure": 3386, "target": 3386, "error": 0, "derror": 1, "requested_hz": 0, "applied_hz": 0, "flags": 0x08, "ff_boost_hz": 0},
            {"dt_ms": 10, "raw_pressure": 3387, "control_pressure": 3387, "avg_pressure": 3387, "target": 3386, "error": 1, "derror": 1, "requested_hz": 0, "applied_hz": 0, "flags": 0x08, "ff_boost_hz": 0},
            {"dt_ms": 15, "raw_pressure": 3376, "control_pressure": 3376, "avg_pressure": 3376, "target": 3386, "error": -10, "derror": -11, "requested_hz": 0, "applied_hz": 0, "flags": 0x08, "ff_boost_hz": 0},
            {"dt_ms": 25, "raw_pressure": 3380, "control_pressure": 3380, "avg_pressure": 3380, "target": 3386, "error": -6, "derror": 4, "requested_hz": 0, "applied_hz": 0, "flags": 0x08, "ff_boost_hz": 0},
            {"dt_ms": 40, "raw_pressure": 3384, "control_pressure": 3384, "avg_pressure": 3384, "target": 3386, "error": -2, "derror": 4, "requested_hz": 0, "applied_hz": 0, "flags": 0x08, "ff_boost_hz": 0},
        ],
        "events": [
            {"dt_ms": 0, "event_type": 0, "event_name": "trace_start", "value0": 0, "value1": 0},
            {"dt_ms": 10, "event_type": 2, "event_name": "pulse_start", "value0": 1500, "value1": 3387},
            {"dt_ms": 13, "event_type": 3, "event_name": "pulse_end", "value0": 1500, "value1": 3378},
            {"dt_ms": 40, "event_type": 1, "event_name": "trace_stop", "value0": 0, "value1": 0},
        ],
    }


def test_analyze_valve_trace_marks_baseline_response_and_snr():
    row = analyze_valve_trace(_trace("valve_char_r_w1500_rep01"))

    assert row["valid"] is True
    assert row["channel"] == "r"
    assert row["width_us"] == 1500
    assert row["replicate"] == 1
    assert row["baseline_mean_raw"] == 3386
    assert row["baseline_span_raw"] == 2
    assert row["drop_raw"] == 10
    assert row["spike_raw"] == 1
    assert row["response_raw"] == 10
    assert row["response_kind"] == "drop"
    assert row["trough_after_end_ms"] == 2
    assert row["selected_after_start_ms"] == 5
    assert row["snr_span"] == 5


def test_analyze_valve_trace_keeps_spike_separate_from_later_drop():
    trace = _trace("valve_char_p_w3000_rep02", test_id=2473)
    trace["samples"] = [
        {"dt_ms": 0, "raw_pressure": 3386},
        {"dt_ms": 5, "raw_pressure": 3386},
        {"dt_ms": 10, "raw_pressure": 3386},
        {"dt_ms": 14, "raw_pressure": 3456},
        {"dt_ms": 32, "raw_pressure": 3400},
        {"dt_ms": 48, "raw_pressure": 3356},
    ]
    trace["events"] = [
        {"dt_ms": 10, "event_type": 2, "event_name": "pulse_start", "value0": 3000, "value1": 3386},
        {"dt_ms": 13, "event_type": 3, "event_name": "pulse_end", "value0": 3000, "value1": 3386},
    ]

    row = analyze_valve_trace(trace)

    assert row["valid"] is True
    assert row["drop_raw"] == 30
    assert row["spike_raw"] == 70
    assert row["response_raw"] == 30
    assert row["trough_dt_ms"] == 48
    assert row["peak_dt_ms"] == 14


def test_generate_valve_trace_artifacts_writes_plots_csv_and_analysis(tmp_path):
    artifacts = create_run_artifacts("LC-TEST", output_root=tmp_path, timestamp="20260516T000000Z")
    source = artifacts.run_dir / "raw_selftest_trace_2474_valve_char_r_w1500_rep01.json"
    source.write_text(json.dumps(_trace("valve_char_r_w1500_rep01")), encoding="utf-8")
    source_p = artifacts.run_dir / "raw_selftest_trace_2473_valve_char_p_w3000_rep01.json"
    source_p.write_text(json.dumps(_trace("valve_char_p_w3000_rep01", test_id=2473)), encoding="utf-8")

    result = generate_valve_trace_artifacts(artifacts)

    assert result is not None
    assert result.replicate_count == 2
    assert (result.trace_dir / source.name).exists()
    assert result.analysis_json.exists()
    assert result.replicate_csv.exists()
    assert (result.plot_dir / "valve_char_r_w1500_overlay.png").exists()
    assert (result.plot_dir / "valve_char_p_full_timecourse.png").exists()
    assert (result.plot_dir / "valve_char_response_by_width.png").exists()
    analysis = json.loads(result.analysis_json.read_text(encoding="utf-8"))
    assert analysis["schema_version"] == "valve_trace_analysis_v2"
    assert analysis["valid_replicate_count"] == 2
