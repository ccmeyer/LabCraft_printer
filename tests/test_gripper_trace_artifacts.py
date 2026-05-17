import json

from tools.qualification.artifacts import create_run_artifacts
from tools.qualification.gripper_trace_artifacts import analyze_gripper_trace, generate_gripper_trace_artifacts


def _trace(name: str, test_id: int = 2510):
    return {
        "run_id": 123,
        "test_id": test_id,
        "name": name,
        "summary": {},
        "samples": [
            {"dt_ms": 0, "raw_pressure": 4259},
            {"dt_ms": 50, "raw_pressure": 4258},
            {"dt_ms": 100, "raw_pressure": 4259},
            {"dt_ms": 250, "raw_pressure": 4258},
            {"dt_ms": 500, "raw_pressure": 4259},
            {"dt_ms": 1750, "raw_pressure": 4218},
            {"dt_ms": 1900, "raw_pressure": 4217},
            {"dt_ms": 2000, "raw_pressure": 4216},
            {"dt_ms": 2100, "raw_pressure": 4220},
            {"dt_ms": 2200, "raw_pressure": 4221},
        ],
        "events": [
            {"dt_ms": 0, "event_type": 0, "event_name": "trace_start", "value0": 0, "value1": 0},
            {"dt_ms": 500, "event_type": 2, "event_name": "pulse_start", "value0": 2000, "value1": 4259},
            {"dt_ms": 2000, "event_type": 3, "event_name": "pulse_end", "value0": 2000, "value1": 4216},
            {"dt_ms": 2250, "event_type": 1, "event_name": "trace_stop", "value0": 0, "value1": 0},
        ],
    }


def test_analyze_gripper_trace_computes_drop_and_snr():
    row = analyze_gripper_trace(_trace("grip_static_chp_psi3000_rep01"))

    assert row["valid"] is True
    assert row["trace_family"] == "static"
    assert row["channel"] == "p"
    assert row["psi_milli"] == 3000
    assert row["replicate"] == 1
    assert row["baseline_mean_raw"] == 4259
    assert row["end_pressure_raw"] == 4217
    assert row["drop_raw"] == 42
    assert row["post_drop_raw"] == 39
    assert row["slope_raw_min"] > 0
    assert row["snr"] > 0


def test_generate_gripper_trace_artifacts_writes_plots_csv_and_analysis(tmp_path):
    artifacts = create_run_artifacts("LC-TEST", output_root=tmp_path, timestamp="20260517T000000Z")
    sources = [
        ("raw_selftest_trace_2510_grip_static_chp_psi3000_rep01.json", _trace("grip_static_chp_psi3000_rep01", 2510)),
        ("raw_selftest_trace_2510_grip_static_chr_psi3000_rep01.json", _trace("grip_static_chr_psi3000_rep01", 2510)),
        ("raw_selftest_trace_2511_grip_refresh_chp_psi3000_seq01.json", _trace("grip_refresh_chp_psi3000_seq01", 2511)),
        ("raw_selftest_trace_2512_grip_motion_chp_psi3000_seq01_x43000_y13000.json", _trace("grip_motion_chp_psi3000_seq01_x43000_y13000", 2512)),
        ("raw_selftest_trace_2513_grip_compare_chp_pre_psi3000.json", _trace("grip_compare_chp_pre_psi3000", 2513)),
        ("raw_selftest_trace_2513_grip_compare_chp_post_psi3000.json", _trace("grip_compare_chp_post_psi3000", 2513)),
    ]
    for filename, payload in sources:
        (artifacts.run_dir / filename).write_text(json.dumps(payload), encoding="utf-8")

    result = generate_gripper_trace_artifacts(artifacts)

    assert result is not None
    assert result.replicate_count == len(sources)
    assert result.analysis_json.exists()
    assert result.replicate_csv.exists()
    assert (result.plot_dir / "gripper_static_pressure_matrix.png").exists()
    assert (result.plot_dir / "gripper_refresh_hold_timeline.png").exists()
    assert (result.plot_dir / "gripper_motion_raster_drop_timeline.png").exists()
    assert (result.plot_dir / "gripper_motion_raster_drop_map.png").exists()
    analysis = json.loads(result.analysis_json.read_text(encoding="utf-8"))
    assert analysis["schema_version"] == "gripper_trace_analysis_v1"
    assert analysis["valid_replicate_count"] == len(sources)
    assert result.report_metrics[2510]["d3"] == 42
    assert result.report_metrics[2512]["drop_mean"] == 42
    assert result.report_metrics[2513]["p_delta"] == 0
