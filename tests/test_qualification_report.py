import csv
import json

from tools.qualification.artifacts import create_run_artifacts
from tools.qualification.identity import load_or_create_identity
from tools.qualification.manifest import parse_manifest
from tools.qualification.report import normalize_report, write_qualification_artifacts


def _raw_selftest():
    return {
        "run_id": 1234,
        "profile": "FULL",
        "started_at": "2026-05-13T00:00:00Z",
        "finished_at": "2026-05-13T00:00:05Z",
        "aborted": False,
        "summary": {"total": 1, "passed": 1, "failed": 0},
        "results": [
            {
                "test_id": 1001,
                "name": "comm_crc_known_vector",
                "pass": True,
                "metrics": {"crc": 19255},
            }
        ],
        "host_checks": [
            {
                "name": "hello_ack",
                "pass": True,
                "details": {"seq8": 1},
            }
        ],
    }


def _raw_factory_v1_selftest():
    raw = _raw_selftest()
    rows = []
    names = {
        1001: "comm_crc_known_vector",
        1002: "comm_frame_roundtrip",
        1010: "session_hello_ack",
        1011: "session_goodbye_ack",
        1012: "session_goodbye_done",
        1003: "status_frame_shape",
        1013: "clear_queue_ack",
        1020: "status_chunk_alternation_safe",
        1021: "status_cadence_safe",
        1004: "uptime_counter_read",
        1005: "flash_config_readonly",
        1007: "flash_imaging_burst_diag_safe",
        1006: "fw_build_info",
        1030: "uart_recovery_after_noise_safe",
        1040: "rtos_memory_headroom_safe",
        1041: "crash_record_retained_safe",
        1042: "watchdog_supervisor_safe",
        2001: "motion_home_cycle_full",
        2002: "motion_absolute_move_bounds_full",
        2007: "motion_home_repeatability_factory",
        2008: "motion_pattern_return_factory",
        2003: "pressure_regulator_step_response_full",
        2004: "valve_actuation_sequence_full",
        2005: "print_refuel_pulse_integrity_full",
        2006: "emergency_abort_and_safe_stop_full",
    }
    metrics = {
        1021: {"period_ms_avg": 62, "period_ms_max_jitter": 13},
        1040: {"heap_min": 7848, "stk_min": 125},
        2001: {"home_time_ms": 489, "home_success_axes": 4, "limit_hits": 4},
        2002: {"final_error_steps": 0, "bound_violation": 0},
        2007: {"x_span": 4, "y_span": 5, "ret_err": 1, "move_to": 0, "home_to": 0},
        2008: {"ret_err": 2, "x_ret": 2, "y_ret": 1, "move_to": 0, "home_to": 0, "bound": 0},
        2003: {"settle_time_ms": 1050, "overshoot": 0, "steady_state_error": 4},
        2004: {"valve_open_count": 2, "valve_close_count": 2, "sequence_order_ok": 1},
        2005: {"pulse_count": 2, "pulse_width_min_ns": 1300000, "pulse_width_max_ns": 2500000},
        2006: {"abort_latency_ms": 501, "motors_disabled": 1, "regulators_stopped": 1, "valves_safe_state": 1},
    }
    for test_id, name in names.items():
        rows.append({"test_id": test_id, "name": name, "pass": True, "metrics": metrics.get(test_id, {})})
    raw["summary"] = {"total": len(rows), "passed": len(rows), "failed": 0}
    raw["results"] = rows
    return raw


def _identity(tmp_path):
    return load_or_create_identity(
        tmp_path / "local" / "machine_identity.json",
        machine_id="LC-0001",
        now_fn=lambda: "2026-05-13T00:00:00Z",
        uuid_fn=lambda: "uuid-1",
    )


def _manifest(*, enforce=False, rules=None):
    return parse_manifest(
        {
            "schema_version": "qualification_manifest_v0",
            "manifest_id": "unit_manifest",
            "name": "Unit Manifest",
            "profile": "FULL",
            "expected_test_ids": [1001],
            "enforce_expected_test_ids": enforce,
            "analysis_rules": rules or {"1001": {"category": "protocol", "failure_domain": "infrastructure"}},
        }
    )


def test_normalize_report_preserves_raw_summary_and_rows(tmp_path):
    manifest = _manifest()
    artifacts = create_run_artifacts("LC-0001", output_root=tmp_path, timestamp="20260513T120000Z")

    report = normalize_report(_raw_selftest(), manifest, _identity(tmp_path), artifacts)

    assert report["schema_version"] == "qualification_report_v1"
    assert report["overall_status"] == "pass"
    assert report["verdict"]["status"] == "pass"
    assert report["analysis"]["schema_version"] == "qualification_analysis_v1"
    assert report["raw_summary"] == {"total": 1, "passed": 1, "failed": 0}
    assert report["results"][0]["test_id"] == 1001
    assert report["host_checks"][0]["name"] == "hello_ack"
    assert report["manifest_checks"]["enforced"] is False


def test_write_qualification_artifacts_writes_json_and_summary_csv(tmp_path):
    manifest = _manifest(
        rules={
            "1001": {
                "category": "protocol",
                "failure_domain": "infrastructure",
                "metrics": {"crc": {"maturity": "candidate", "equals": 19255}},
            }
        }
    )
    artifacts = create_run_artifacts("LC-0001", output_root=tmp_path, timestamp="20260513T120000Z")

    report = write_qualification_artifacts(_raw_selftest(), manifest, _identity(tmp_path), artifacts)

    assert artifacts.raw_selftest_path.exists()
    assert artifacts.report_path.exists()
    assert artifacts.summary_csv_path.exists()
    assert json.loads(artifacts.report_path.read_text(encoding="utf-8"))["schema_version"] == "qualification_report_v1"
    assert report["machine"]["machine_id"] == "LC-0001"

    rows = list(csv.DictReader(artifacts.summary_csv_path.open(newline="", encoding="utf-8")))
    assert [row["item_kind"] for row in rows] == ["firmware_result", "host_check", "analysis_metric"]
    assert rows[0]["machine_id"] == "LC-0001"
    assert rows[0]["manifest_id"] == "unit_manifest"
    assert rows[0]["item_id"] == "1001"
    assert rows[0]["analysis_status"] == "pass"
    assert json.loads(rows[0]["payload_json"]) == {"crc": 19255}
    assert rows[2]["metric_name"] == "crc"
    assert rows[2]["threshold_maturity"] == "candidate"


def test_enforced_missing_expected_id_fails_report(tmp_path):
    manifest = parse_manifest(
        {
            "schema_version": "qualification_manifest_v0",
            "manifest_id": "strict_manifest",
            "name": "Strict Manifest",
            "profile": "FULL",
            "expected_test_ids": [1001, 2006],
            "enforce_expected_test_ids": True,
        }
    )
    artifacts = create_run_artifacts("LC-0001", output_root=tmp_path, timestamp="20260513T120000Z")

    report = normalize_report(_raw_selftest(), manifest, _identity(tmp_path), artifacts)

    assert report["overall_status"] == "fail"
    assert report["verdict"]["blocking_issue_count"] == 1
    assert 2006 in report["manifest_checks"]["missing_test_ids"]


def test_factory_v1_synthetic_full_report_passes_expected_id_enforcement(tmp_path):
    from tools.qualification.manifest import load_manifest

    manifest = load_manifest("factory_acceptance_v1")
    artifacts = create_run_artifacts("LC-0001", output_root=tmp_path, timestamp="20260513T120000Z")

    report = normalize_report(_raw_factory_v1_selftest(), manifest, _identity(tmp_path), artifacts)

    assert report["overall_status"] == "pass"
    assert report["manifest_checks"]["missing_test_ids"] == []
    assert report["raw_summary"]["total"] == 25
    metric_names = {item["metric_name"] for item in report["analysis"]["metric_evaluations"]}
    assert {"x_span", "y_span", "x_ret", "y_ret"}.issubset(metric_names)
