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
            {"dt_ms": 15, "raw_pressure": 3436, "control_pressure": 3436, "avg_pressure": 3436, "target": 3386, "error": 50, "derror": 49, "requested_hz": 0, "applied_hz": 0, "flags": 0x08, "ff_boost_hz": 0},
            {"dt_ms": 25, "raw_pressure": 3306, "control_pressure": 3306, "avg_pressure": 3306, "target": 3386, "error": -80, "derror": -130, "requested_hz": 0, "applied_hz": 0, "flags": 0x08, "ff_boost_hz": 0},
            {"dt_ms": 100, "raw_pressure": 3381, "control_pressure": 3381, "avg_pressure": 3381, "target": 3386, "error": -5, "derror": 75, "requested_hz": 0, "applied_hz": 0, "flags": 0x08, "ff_boost_hz": 0},
            {"dt_ms": 105, "raw_pressure": 3380, "control_pressure": 3380, "avg_pressure": 3380, "target": 3386, "error": -6, "derror": -1, "requested_hz": 0, "applied_hz": 0, "flags": 0x08, "ff_boost_hz": 0},
            {"dt_ms": 110, "raw_pressure": 3379, "control_pressure": 3379, "avg_pressure": 3379, "target": 3386, "error": -7, "derror": -1, "requested_hz": 0, "applied_hz": 0, "flags": 0x08, "ff_boost_hz": 0},
            {"dt_ms": 160, "raw_pressure": 3380, "control_pressure": 3380, "avg_pressure": 3380, "target": 3386, "error": -6, "derror": 1, "requested_hz": 0, "applied_hz": 0, "flags": 0x08, "ff_boost_hz": 0},
        ],
        "events": [
            {"dt_ms": 0, "event_type": 0, "event_name": "trace_start", "value0": 0, "value1": 0},
            {"dt_ms": 10, "event_type": 2, "event_name": "pulse_start", "value0": 1500, "value1": 3387},
            {"dt_ms": 13, "event_type": 3, "event_name": "pulse_end", "value0": 1500, "value1": 3378},
            {"dt_ms": 40, "event_type": 1, "event_name": "trace_stop", "value0": 0, "value1": 0},
        ],
    }


def _with_context(trace: dict, sequence_index: int, motor_position: int) -> dict:
    raw_motor = motor_position & 0xFFFFFFFF
    trace["events"].insert(
        1,
        {
            "dt_ms": 2,
            "event_type": 10,
            "event_name": "valve_sequence",
            "value0": sequence_index,
            "value1": int(trace["name"].split("_w")[1].split("_")[0]),
        },
    )
    trace["events"].insert(
        2,
        {
            "dt_ms": 2,
            "event_type": 11,
            "event_name": "motor_position",
            "value0": raw_motor & 0xFFFF,
            "value1": (raw_motor >> 16) & 0xFFFF,
        },
    )
    return trace


def _with_gap_context(trace: dict, gap_ms: int, previous_width: int, interval_ms: int, motor_position: int) -> dict:
    raw_motor = motor_position & 0xFFFFFFFF
    trace["events"].insert(
        1,
        {"dt_ms": 2, "event_type": 12, "event_name": "valve_gap", "value0": gap_ms, "value1": 0},
    )
    trace["events"].insert(
        2,
        {
            "dt_ms": 2,
            "event_type": 13,
            "event_name": "valve_previous_width",
            "value0": previous_width,
            "value1": int(trace["name"].split("_w")[1].split("_")[0]),
        },
    )
    trace["events"].insert(
        3,
        {"dt_ms": 2, "event_type": 14, "event_name": "valve_interval", "value0": interval_ms, "value1": 0},
    )
    trace["events"].insert(
        4,
        {
            "dt_ms": 2,
            "event_type": 11,
            "event_name": "motor_position",
            "value0": raw_motor & 0xFFFF,
            "value1": (raw_motor >> 16) & 0xFFFF,
        },
    )
    return trace


def test_analyze_valve_trace_marks_baseline_response_and_snr():
    row = analyze_valve_trace(_trace("valve_char_r_w1500_rep01"))

    assert row["valid"] is True
    assert row["excluded"] is True
    assert row["exclude_reason"] == "first_after_width_change"
    assert row["latency_valid"] is True
    assert row["ring_valid"] is True
    assert row["channel"] == "r"
    assert row["width_us"] == 1500
    assert row["replicate"] == 1
    assert row["baseline_mean_raw"] == 3386
    assert row["baseline_span_raw"] == 2
    assert row["settled_drop_raw"] == 6
    assert row["drop_raw"] == 6
    assert row["ring_amp_raw"] == 80
    assert row["spike_raw"] == 50
    assert row["latency_ms"] == 5
    assert row["response_raw"] == 6
    assert row["response_kind"] == "settled_drop"
    assert row["settled_pressure_raw"] == 3380
    assert row["snr_span"] == 3


def test_analyze_valve_trace_keeps_settled_drop_valid_when_latency_is_missing():
    trace = _trace("valve_char_p_w1500_rep02", test_id=2473)
    trace["samples"] = [
        {"dt_ms": 0, "raw_pressure": 3386},
        {"dt_ms": 5, "raw_pressure": 3386},
        {"dt_ms": 10, "raw_pressure": 3386},
        {"dt_ms": 15, "raw_pressure": 3388},
        {"dt_ms": 25, "raw_pressure": 3384},
        {"dt_ms": 100, "raw_pressure": 3380},
        {"dt_ms": 105, "raw_pressure": 3380},
        {"dt_ms": 110, "raw_pressure": 3380},
    ]
    trace["events"] = [
        {"dt_ms": 10, "event_type": 2, "event_name": "pulse_start", "value0": 1500, "value1": 3386},
        {"dt_ms": 13, "event_type": 3, "event_name": "pulse_end", "value0": 1500, "value1": 3386},
    ]

    row = analyze_valve_trace(trace)

    assert row["valid"] is True
    assert row["latency_valid"] is False
    assert row["ring_valid"] is True
    assert row["latency_reason"] == "missing_latency_threshold_crossing"
    assert row["settled_drop_raw"] == 6


def test_analyze_valve_trace_parses_sequence_and_motor_position_context():
    trace = _with_context(_trace("valve_char_r_seq06_w1500_rep02"), 6, -12345)

    row = analyze_valve_trace(trace)

    assert row["valid"] is True
    assert row["sequence_index"] == 6
    assert row["sequence_slot"] == 6
    assert row["sequence_width_us"] == 1500
    assert row["width_us"] == 1500
    assert row["replicate"] == 2
    assert row["motor_position"] == -12345


def test_analyze_valve_trace_parses_gap_context():
    trace = _with_gap_context(_trace("valve_gap_p_w1500_g0500_rep03", test_id=2476), 500, 1500, 1840, 24680)

    row = analyze_valve_trace(trace)

    assert row["valid"] is True
    assert row["trace_family"] == "valve_gap"
    assert row["channel"] == "p"
    assert row["width_us"] == 1500
    assert row["gap_ms"] == 500
    assert row["replicate"] == 3
    assert row["previous_width_us"] == 1500
    assert row["sequence_width_us"] == 1500
    assert row["actual_interval_ms"] == 1840
    assert row["motor_position"] == 24680


def test_analyze_valve_trace_keeps_ringing_separate_from_settled_drop():
    trace = _trace("valve_char_p_w3000_rep02", test_id=2473)
    trace["samples"] = [
        {"dt_ms": 0, "raw_pressure": 3386},
        {"dt_ms": 5, "raw_pressure": 3386},
        {"dt_ms": 10, "raw_pressure": 3386},
        {"dt_ms": 14, "raw_pressure": 3456},
        {"dt_ms": 32, "raw_pressure": 3400},
        {"dt_ms": 48, "raw_pressure": 3356},
        {"dt_ms": 100, "raw_pressure": 3381},
        {"dt_ms": 105, "raw_pressure": 3380},
        {"dt_ms": 110, "raw_pressure": 3379},
        {"dt_ms": 115, "raw_pressure": 3380},
    ]
    trace["events"] = [
        {"dt_ms": 10, "event_type": 2, "event_name": "pulse_start", "value0": 3000, "value1": 3386},
        {"dt_ms": 13, "event_type": 3, "event_name": "pulse_end", "value0": 3000, "value1": 3386},
    ]

    row = analyze_valve_trace(trace)

    assert row["valid"] is True
    assert row["settled_drop_raw"] == 6
    assert row["drop_raw"] == 6
    assert row["spike_raw"] == 70
    assert row["trough_drop_raw"] == 30
    assert row["ring_amp_raw"] == 70
    assert row["response_raw"] == 6
    assert row["peak_dt_ms"] == 14


def test_generate_valve_trace_artifacts_writes_plots_csv_and_analysis(tmp_path):
    artifacts = create_run_artifacts("LC-TEST", output_root=tmp_path, timestamp="20260516T000000Z")
    source = artifacts.run_dir / "raw_selftest_trace_2474_valve_char_r_seq01_w1500_rep01.json"
    source.write_text(json.dumps(_with_context(_trace("valve_char_r_seq01_w1500_rep01"), 1, -12000)), encoding="utf-8")
    source_p = artifacts.run_dir / "raw_selftest_trace_2473_valve_char_p_seq02_w3000_rep02.json"
    source_p.write_text(json.dumps(_with_context(_trace("valve_char_p_seq02_w3000_rep02", test_id=2473), 2, 5400)), encoding="utf-8")
    source_p2 = artifacts.run_dir / "raw_selftest_trace_2473_valve_char_p_seq03_w3000_rep03.json"
    source_p2.write_text(json.dumps(_with_context(_trace("valve_char_p_seq03_w3000_rep03", test_id=2473), 3, 5300)), encoding="utf-8")

    result = generate_valve_trace_artifacts(artifacts)

    assert result is not None
    assert result.replicate_count == 3
    assert (result.trace_dir / source.name).exists()
    assert result.analysis_json.exists()
    assert result.replicate_csv.exists()
    assert (result.plot_dir / "valve_char_r_w1500_overlay.png").exists()
    assert (result.plot_dir / "valve_char_p_full_timecourse.png").exists()
    assert (result.plot_dir / "valve_char_response_by_width.png").exists()
    assert (result.plot_dir / "valve_char_settled_drop_vs_motor_position.png").exists()
    assert (result.plot_dir / "valve_char_ringing_by_width.png").exists()
    analysis = json.loads(result.analysis_json.read_text(encoding="utf-8"))
    assert analysis["schema_version"] == "valve_trace_analysis_v7"
    assert analysis["valid_replicate_count"] == 3
    assert analysis["steady_replicate_count"] == 2
    assert analysis["excluded_replicate_count"] == 1
    assert analysis["conditions"][0]["settled_drop_mean_raw"] == 6
    assert analysis["conditions"][0]["motor_position_span"] == 100
    assert analysis["conditions"][0]["steady_replicate_count"] == 2
    assert analysis["replicates"][0]["sequence_index"] == 2
    assert analysis["replicates"][0]["motor_position"] == 5400
    assert analysis["replicates"][0]["motor_position_delta_from_first"] == 0
    assert analysis["replicates"][1]["motor_position_delta_from_first"] == -100
    assert "ring_amp_raw" in analysis["replicates"][0]
    assert result.report_metrics[2473]["m30"] == 6
    assert result.report_metrics[2473]["rej"] == 28
    assert result.report_metrics[2473]["excl"] == 0
    assert result.report_metrics[2474]["excl"] == 1
    assert analysis["report_metrics"]["2473"]["m30"] == 6


def test_generate_valve_gap_trace_artifacts_writes_gap_plots(tmp_path):
    artifacts = create_run_artifacts("LC-TEST", output_root=tmp_path, timestamp="20260516T000001Z")
    source = artifacts.run_dir / "raw_selftest_trace_2476_valve_gap_p_w1500_g0500_rep01.json"
    source.write_text(
        json.dumps(_with_gap_context(_trace("valve_gap_p_w1500_g0500_rep01", test_id=2476), 500, 0, 0, 12000)),
        encoding="utf-8",
    )
    source_r = artifacts.run_dir / "raw_selftest_trace_2477_valve_gap_r_w1500_g2000_rep01.json"
    source_r.write_text(
        json.dumps(_with_gap_context(_trace("valve_gap_r_w1500_g2000_rep01", test_id=2477), 2000, 1500, 2800, 12100)),
        encoding="utf-8",
    )

    result = generate_valve_trace_artifacts(artifacts)

    assert result is not None
    assert result.replicate_count == 2
    assert (result.plot_dir / "valve_gap_settled_drop_by_gap.png").exists()
    assert (result.plot_dir / "valve_gap_1500_drop_by_replicate.png").exists()
    assert (result.plot_dir / "valve_gap_drop_vs_actual_interval.png").exists()
    analysis = json.loads(result.analysis_json.read_text(encoding="utf-8"))
    assert analysis["schema_version"] == "valve_trace_analysis_v7"
    assert analysis["gap_conditions"][0]["gap_ms"] == 500
    assert analysis["replicates"][0]["actual_interval_ms"] == 0
    assert analysis["replicates"][1]["actual_interval_ms"] == 2800
    assert result.report_metrics[2476]["g500"] == 6
    assert result.report_metrics[2476]["rej"] == 39
