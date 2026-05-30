import json
from pathlib import Path

from QualificationReports import (
    artifact_paths,
    discover_report_entries,
    normalize_result_rows,
    subsystem_for,
)


def _report(*, started_at="2026-05-15T00:00:00Z"):
    return {
        "schema_version": "qualification_report_v1",
        "manifest": {
            "manifest_id": "factory_acceptance_v3",
            "name": "Factory Acceptance v3",
            "profile": "FULL",
        },
        "machine": {
            "machine_id": "LC-TEST",
            "machine_uuid": "uuid",
            "assigned_at": "2026-05-15T00:00:00Z",
        },
        "run": {
            "run_dir": "hil_reports/qualification/LC-TEST/20260515T000000Z",
            "raw_selftest_path": "hil_reports/qualification/LC-TEST/20260515T000000Z/raw_selftest.json",
            "report_path": "hil_reports/qualification/LC-TEST/20260515T000000Z/report.json",
            "summary_csv_path": "hil_reports/qualification/LC-TEST/20260515T000000Z/summary.csv",
            "fixture_id": "",
        },
        "overall_status": "pass",
        "run_id": 123,
        "profile": "FULL",
        "started_at": started_at,
        "finished_at": "2026-05-15T00:00:10Z",
        "results": [
            {
                "test_id": 2007,
                "name": "motion_home_repeatability_factory",
                "pass": True,
                "metrics": {"x_span": 6, "y_span": 5, "ret_err": 0},
            },
            {
                "test_id": 2201,
                "name": "pressure_hold_leak_factory",
                "pass": True,
                "metrics": {"slope_raw_min": 0, "corr_steps": 2500, "ready_miss": 0, "timeout": 0},
            },
        ],
        "host_checks": [
            {"name": "hello_ack", "pass": True, "details": {"seq8": 1}},
        ],
        "analysis": {
            "items": [
                {
                    "item_kind": "firmware_result",
                    "test_id": 2007,
                    "name": "motion_home_repeatability_factory",
                    "category": "motion",
                    "status": "pass",
                    "failure_domain": "none",
                    "message": "Raw firmware result passed.",
                },
                {
                    "item_kind": "firmware_result",
                    "test_id": 2201,
                    "name": "pressure_hold_leak_factory",
                    "category": "pressure",
                    "status": "pass",
                    "failure_domain": "none",
                    "message": "Raw firmware result passed.",
                },
                {
                    "item_kind": "host_check",
                    "name": "hello_ack",
                    "status": "pass",
                    "failure_domain": "none",
                    "message": "Host check passed.",
                },
            ],
            "metric_evaluations": [
                {
                    "item_kind": "metric",
                    "test_id": 2201,
                    "name": "pressure_hold_leak_factory",
                    "metric_name": "corr_steps",
                    "status": "warning",
                    "failure_domain": "machine_performance",
                    "message": "Candidate metric outside threshold: corr_steps=2500, max=2000.",
                }
            ],
            "warnings": [
                {
                    "item_kind": "metric",
                    "test_id": 2201,
                    "name": "pressure_hold_leak_factory",
                    "message": "Candidate metric outside threshold: corr_steps=2500, max=2000.",
                }
            ],
        },
        "warnings": [
            {
                "item_kind": "metric",
                "test_id": 2201,
                "name": "pressure_hold_leak_factory",
                "message": "Candidate metric outside threshold: corr_steps=2500, max=2000.",
            }
        ],
    }


def _write_report(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_discover_report_entries_filters_schema_and_sorts_newest_first(tmp_path):
    old_path = tmp_path / "qualification" / "LC-TEST" / "old" / "report.json"
    new_path = tmp_path / "qualification" / "LC-TEST" / "new" / "report.json"
    bad_path = tmp_path / "qualification" / "LC-TEST" / "bad" / "report.json"
    _write_report(old_path, _report(started_at="2026-05-14T00:00:00Z"))
    _write_report(new_path, _report(started_at="2026-05-15T00:00:00Z"))
    _write_report(bad_path, {"schema_version": "old"})

    entries = discover_report_entries(tmp_path)

    assert [entry.report_path for entry in entries] == [new_path, old_path]
    assert entries[0].machine_id == "LC-TEST"
    assert entries[0].manifest_id == "factory_acceptance_v3"
    assert entries[0].run_dir == new_path.parent
    assert entries[0].warning_count == 1


def test_normalize_result_rows_groups_subsystems_and_promotes_metric_warnings():
    rows = normalize_result_rows(_report())
    by_id = {row.item_id or row.name: row for row in rows}

    assert by_id["2007"].subsystem == "Motion"
    assert by_id["2007"].analysis_status == "pass"
    assert by_id["2201"].subsystem == "Pressure"
    assert by_id["2201"].analysis_status == "warning"
    assert by_id["2201"].failure_domain == "machine_performance"
    assert "corr_steps=2500" in by_id["2201"].message
    assert by_id["hello_ack"].subsystem == "Host Checks"


def test_fallback_subsystem_mapping_uses_category_and_kind():
    assert subsystem_for("pressure") == "Pressure"
    assert subsystem_for("pulse") == "Valves/Pulses"
    assert subsystem_for("gripper") == "Gripper"
    assert subsystem_for("anything", "host_check") == "Host Checks"


def test_artifact_paths_exposes_canonical_report_files():
    paths = artifact_paths(_report(), report_path="fallback_report.json")

    labels = [label for label, _path in paths]
    assert labels[:4] == ["Run folder", "Report JSON", "Raw self-test JSON", "Summary CSV"]


def test_artifact_paths_exposes_valve_trace_outputs(tmp_path):
    run_dir = tmp_path / "qualification" / "LC-TEST" / "20260516T000000Z"
    plot_dir = run_dir / "plots" / "valve_characterization"
    trace_dir = run_dir / "traces" / "valve_characterization"
    plot_dir.mkdir(parents=True)
    trace_dir.mkdir(parents=True)
    (plot_dir / "valve_trace_analysis.json").write_text("{}", encoding="utf-8")
    (plot_dir / "valve_trace_replicates.csv").write_text("header\n", encoding="utf-8")
    (plot_dir / "valve_char_response_by_width.png").write_bytes(b"png")
    (plot_dir / "valve_char_settled_drop_vs_motor_position.png").write_bytes(b"png")
    (plot_dir / "valve_char_ringing_by_width.png").write_bytes(b"png")
    (plot_dir / "valve_char_r_w1500_overlay.png").write_bytes(b"png")

    report = _report()
    report["run"]["run_dir"] = str(run_dir)
    paths = artifact_paths(report, report_path=run_dir / "report.json")

    labels = [label for label, _path in paths]
    assert "Valve trace folder" in labels
    assert "Valve plot folder" in labels
    assert "Valve trace analysis JSON" in labels
    assert "Valve trace replicate CSV" in labels
    assert "Valve response summary plot" in labels
    assert "Valve motor-position plot" in labels
    assert "Valve ringing summary plot" in labels
    assert "Valve overlay plot valve_char_r_w1500_overlay" in labels


def test_artifact_paths_exposes_gripper_trace_outputs(tmp_path):
    run_dir = tmp_path / "qualification" / "LC-TEST" / "20260517T000000Z"
    plot_dir = run_dir / "plots" / "gripper_seal_stress"
    trace_dir = run_dir / "traces" / "gripper_seal_stress"
    plot_dir.mkdir(parents=True)
    trace_dir.mkdir(parents=True)
    (plot_dir / "gripper_trace_analysis.json").write_text("{}", encoding="utf-8")
    (plot_dir / "gripper_trace_replicates.csv").write_text("header\n", encoding="utf-8")
    (plot_dir / "gripper_static_pressure_matrix.png").write_bytes(b"png")
    (plot_dir / "gripper_static_drop_by_replicate.png").write_bytes(b"png")
    (plot_dir / "gripper_static_drop_vs_seal_age.png").write_bytes(b"png")
    (plot_dir / "gripper_refresh_hold_timeline.png").write_bytes(b"png")
    (plot_dir / "gripper_motion_raster_drop_timeline.png").write_bytes(b"png")
    (plot_dir / "gripper_motion_raster_drop_map.png").write_bytes(b"png")
    (plot_dir / "gripper_static_chp_overlay.png").write_bytes(b"png")

    report = _report()
    report["run"]["run_dir"] = str(run_dir)
    paths = artifact_paths(report, report_path=run_dir / "report.json")

    labels = [label for label, _path in paths]
    assert "Gripper trace folder" in labels
    assert "Gripper plot folder" in labels
    assert "Gripper trace analysis JSON" in labels
    assert "Gripper trace replicate CSV" in labels
    assert "Gripper static pressure matrix plot" in labels
    assert "Gripper static drop by replicate plot" in labels
    assert "Gripper static drop vs seal age plot" in labels
    assert "Gripper refresh hold timeline plot" in labels
    assert "Gripper raster drop timeline plot" in labels
    assert "Gripper raster drop map plot" in labels
    assert "Gripper overlay plot gripper_static_chp_overlay" in labels
