from tools.qualification.analyzers import analyze_report
from tools.qualification.manifest import load_manifest, parse_manifest
from tools.qualification.report import _manifest_checks


def _manifest(*, expected=(1001,), enforce=False, metric_rule=None):
    rules = {"1001": {"category": "protocol", "failure_domain": "infrastructure"}}
    if metric_rule is not None:
        rules["1001"]["metrics"] = {"crc": metric_rule}
    return parse_manifest(
        {
            "schema_version": "qualification_manifest_v0",
            "manifest_id": "unit_manifest",
            "name": "Unit Manifest",
            "profile": "FULL",
            "expected_test_ids": list(expected),
            "enforce_expected_test_ids": enforce,
            "analysis_rules": rules,
        }
    )


def _raw(*, passed=True, aborted=False, metrics=None):
    row_metrics = {"crc": 19255} if metrics is None else metrics
    return {
        "run_id": 1234,
        "profile": "FULL",
        "started_at": "2026-05-13T00:00:00Z",
        "finished_at": "2026-05-13T00:00:05Z",
        "aborted": aborted,
        "summary": {"total": 1, "passed": 1 if passed else 0, "failed": 0 if passed else 1},
        "results": [{"test_id": 1001, "name": "comm_crc_known_vector", "pass": passed, "metrics": row_metrics}],
        "host_checks": [{"name": "hello_ack", "pass": True, "details": {"seq8": 1}}],
    }


def _analyze(raw, manifest, *, returncode=0):
    return analyze_report(raw, manifest, _manifest_checks(raw, manifest), selftest_returncode=returncode)


def test_passing_raw_report_produces_pass_verdict():
    analysis = _analyze(_raw(), _manifest())

    assert analysis["verdict"]["status"] == "pass"
    assert analysis["summary"]["blocking_issue_count"] == 0


def test_raw_firmware_failure_is_classified():
    analysis = _analyze(_raw(passed=False), _manifest())

    assert analysis["verdict"]["status"] == "fail"
    failed = [item for item in analysis["items"] if item.get("item_kind") == "firmware_result"][0]
    assert failed["failure_domain"] == "infrastructure"


def test_aborted_or_missing_raw_output_is_infrastructure_failure():
    analysis = _analyze(_raw(aborted=True), _manifest(), returncode=3)

    assert analysis["verdict"]["status"] == "fail"
    domains = {item["failure_domain"] for item in analysis["items"] if item["status"] == "fail"}
    assert domains == {"infrastructure"}


def test_missing_expected_ids_are_reported():
    analysis = _analyze(_raw(), _manifest(expected=(1001, 2006), enforce=True))

    assert analysis["verdict"]["status"] == "fail"
    item = [row for row in analysis["items"] if row["item_kind"] == "manifest_check"][0]
    assert item["missing_test_ids"] == [2006]


def test_candidate_threshold_warning_does_not_fail():
    analysis = _analyze(
        _raw(metrics={"crc": 1}),
        _manifest(metric_rule={"maturity": "candidate", "equals": 19255}),
    )

    assert analysis["verdict"]["status"] == "pass"
    assert analysis["summary"]["warning_count"] == 1
    assert analysis["metric_evaluations"][0]["status"] == "warning"


def test_acceptance_threshold_violation_fails():
    analysis = _analyze(
        _raw(metrics={"crc": 1}),
        _manifest(metric_rule={"maturity": "acceptance", "equals": 19255}),
    )

    assert analysis["verdict"]["status"] == "fail"
    assert analysis["metric_evaluations"][0]["status"] == "fail"


def test_profile_lut_benchmark_manifest_accepts_limits_and_blocks_cycle_regression():
    manifest = load_manifest("profile_lut_benchmark_v1")
    metrics = {
        "clk": 180000000,
        "samples": 25376,
        "lut_max": 225,
        "lut_mean": 100,
        "legacy_max": 1000,
        "legacy_mean": 500,
        "speedup_x100": 500,
        "prep_short": 400,
        "prep_long": 400,
        "err_max": 2,
        "irq_restore": 1,
        "checksum": 1234,
    }
    raw = {
        "run_id": 2030,
        "profile": "SAFE",
        "started_at": "2026-08-11T00:00:00Z",
        "finished_at": "2026-08-11T00:00:01Z",
        "aborted": False,
        "summary": {"total": 1, "passed": 1, "failed": 0},
        "results": [
            {
                "test_id": 2030,
                "name": "profile_lut_cycle_benchmark_safe",
                "pass": True,
                "metrics": metrics,
            }
        ],
        "host_checks": [],
    }

    accepted = _analyze(raw, manifest)
    assert accepted["verdict"]["status"] == "pass"

    raw["results"][0]["metrics"] = {**metrics, "lut_max": 226}
    regressed = _analyze(raw, manifest)
    assert regressed["verdict"]["status"] == "fail"
    failures = [
        item for item in regressed["metric_evaluations"] if item["status"] == "fail"
    ]
    assert [item["metric_name"] for item in failures] == ["lut_max"]


def test_coordinated_xy_executor_manifest_accepts_nominal_and_blocks_isr_regression():
    manifest = load_manifest("coordinated_xy_executor_v1")
    common_round_trip = {
        "hz": 3000, "i7": 0, "edge": 1, "ck": 1, "low": 1,
        "done": 1, "pu": 0, "cy": 1200, "ret": 1, "to": 0,
    }
    results = [
        {"test_id": 2040, "name": "coordinated_xy_x_only_low", "pass": True,
         "metrics": {**common_round_trip, "dx": 1000, "dy": 0, "xe": 2000, "ye": 0, "ms": 1000, "i2": 4000}},
        {"test_id": 2041, "name": "coordinated_xy_y_only_low", "pass": True,
         "metrics": {**common_round_trip, "dx": 0, "dy": 1000, "xe": 0, "ye": 2000, "ms": 1000, "i2": 4000}},
        {"test_id": 2042, "name": "coordinated_xy_equal_low", "pass": True,
         "metrics": {**common_round_trip, "dx": 1000, "dy": 1000, "xe": 2000, "ye": 2000, "ms": 1000, "i2": 4000}},
        {"test_id": 2043, "name": "coordinated_xy_asymmetric_low", "pass": True,
         "metrics": {**common_round_trip, "dx": 500, "dy": 1500, "xe": 1000, "ye": 3000, "ms": 1500, "i2": 6000}},
        {"test_id": 2044, "name": "coordinated_xy_pause_resume", "pass": True,
         "metrics": {"dx": 2000, "dy": 1000, "hz": 3000, "pause": 1, "stable": 1,
                     "resume": 1, "low": 1, "i7": 0, "pu": 0, "cy": 1200, "ret": 1, "to": 0}},
        {"test_id": 2045, "name": "coordinated_xy_cancel", "pass": True,
         "metrics": {"dx": 2000, "dy": 1000, "hz": 3000, "cancel": 1, "lat": 1,
                     "rise": 0, "rebase": 1, "low": 1, "i7": 0, "pu": 0, "cy": 1200,
                     "recover": 1, "to": 0}},
        {"test_id": 2046, "name": "coordinated_xy_limit_abort", "pass": True,
         "metrics": {"dx": 1000, "dy": 2000, "hz": 3000, "xl": 1, "yl": 1,
                     "xlat": 1, "ylat": 1, "xrise": 0, "yrise": 0, "rebase": 1,
                     "low": 1, "i7": 0, "pu": 0, "cy": 1200, "xd": 10, "yd": 12,
                     "home": 1, "to": 0}},
    ]
    raw = {
        "run_id": 2049,
        "profile": "FULL",
        "started_at": "2026-08-11T00:00:00Z",
        "finished_at": "2026-08-11T00:00:05Z",
        "aborted": False,
        "summary": {"total": 7, "passed": 7, "failed": 0},
        "results": results,
        "host_checks": [],
    }

    accepted = _analyze(raw, manifest)
    assert accepted["verdict"]["status"] == "pass"

    raw["results"][2]["metrics"] = {**raw["results"][2]["metrics"], "cy": 2251}
    regressed = _analyze(raw, manifest)
    assert regressed["verdict"]["status"] == "fail"
    failures = [item for item in regressed["metric_evaluations"] if item["status"] == "fail"]
    assert [(item["test_id"], item["metric_name"]) for item in failures] == [(2042, "cy")]


def test_missing_metric_follows_threshold_maturity():
    analysis = _analyze(_raw(metrics={}), _manifest(metric_rule={"maturity": "candidate", "max": 10}))

    assert analysis["verdict"]["status"] == "pass"
    assert analysis["metric_evaluations"][0]["status"] == "warning"


def test_motion_candidate_threshold_warning_does_not_fail():
    manifest = parse_manifest(
        {
            "schema_version": "qualification_manifest_v0",
            "manifest_id": "motion_manifest",
            "name": "Motion Manifest",
            "profile": "FULL",
            "expected_test_ids": [2007],
            "enforce_expected_test_ids": True,
            "analysis_rules": {
                "2007": {
                    "category": "motion",
                    "failure_domain": "machine_performance",
                    "metrics": {"x_span": {"maturity": "candidate", "max": 25}},
                }
            },
        }
    )
    raw = {
        "run_id": 1234,
        "profile": "FULL",
        "started_at": "2026-05-13T00:00:00Z",
        "finished_at": "2026-05-13T00:00:05Z",
        "aborted": False,
        "summary": {"total": 1, "passed": 1, "failed": 0},
        "results": [
            {
                "test_id": 2007,
                "name": "motion_home_repeatability_factory",
                "pass": True,
                "metrics": {"x_span": 50},
            }
        ],
        "host_checks": [],
    }

    analysis = _analyze(raw, manifest)

    assert analysis["verdict"]["status"] == "pass"
    assert analysis["metric_evaluations"][0]["status"] == "warning"
    assert analysis["metric_evaluations"][0]["failure_domain"] == "machine_performance"


def test_pressure_candidate_threshold_warning_does_not_fail():
    manifest = parse_manifest(
        {
            "schema_version": "qualification_manifest_v0",
            "manifest_id": "pressure_manifest",
            "name": "Pressure Manifest",
            "profile": "FULL",
            "expected_test_ids": [2201],
            "enforce_expected_test_ids": True,
            "analysis_rules": {
                "2201": {
                    "category": "pressure",
                    "failure_domain": "machine_performance",
                    "metrics": {"slope_raw_min": {"maturity": "candidate", "min": -1500, "max": 1500}},
                }
            },
        }
    )
    raw = {
        "run_id": 1234,
        "profile": "FULL",
        "started_at": "2026-05-13T00:00:00Z",
        "finished_at": "2026-05-13T00:00:05Z",
        "aborted": False,
        "summary": {"total": 1, "passed": 1, "failed": 0},
        "results": [
            {
                "test_id": 2201,
                "name": "pressure_hold_leak_factory",
                "pass": True,
                "metrics": {"slope_raw_min": 2200},
            }
        ],
        "host_checks": [],
    }

    analysis = _analyze(raw, manifest)

    assert analysis["verdict"]["status"] == "pass"
    assert analysis["metric_evaluations"][0]["status"] == "warning"
    assert analysis["metric_evaluations"][0]["failure_domain"] == "machine_performance"


def test_valve_pulse_candidate_threshold_warning_does_not_fail():
    manifest = parse_manifest(
        {
            "schema_version": "qualification_manifest_v0",
            "manifest_id": "valve_pulse_manifest",
            "name": "Valve Pulse Manifest",
            "profile": "FULL",
            "expected_test_ids": [2401],
            "enforce_expected_test_ids": True,
            "analysis_rules": {
                "2401": {
                    "category": "pulse",
                    "failure_domain": "machine_performance",
                    "metrics": {"cv_pct": {"maturity": "candidate", "max": 100}},
                }
            },
        }
    )
    raw = {
        "run_id": 1234,
        "profile": "FULL",
        "started_at": "2026-05-13T00:00:00Z",
        "finished_at": "2026-05-13T00:00:05Z",
        "aborted": False,
        "summary": {"total": 1, "passed": 1, "failed": 0},
        "results": [
            {
                "test_id": 2401,
                "name": "print_valve_pulse_drop_repeatability_factory",
                "pass": True,
                "metrics": {"cv_pct": 150},
            }
        ],
        "host_checks": [],
    }

    analysis = _analyze(raw, manifest)

    assert analysis["verdict"]["status"] == "pass"
    assert analysis["metric_evaluations"][0]["status"] == "warning"
    assert analysis["metric_evaluations"][0]["failure_domain"] == "machine_performance"
