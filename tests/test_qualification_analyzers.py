from copy import deepcopy

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


def test_coordinated_xy_performance_manifest_accepts_nominal_and_blocks_pending_regression():
    manifest = load_manifest("coordinated_xy_performance_v1")
    totals = {
        2060: (5000, 10, 106832, 180000, 220000, 440000),
        2061: (10000, 10, 106832, 180000, 220000, 440000),
        2062: (20000, 10, 106832, 180000, 220000, 440000),
        2063: (30000, 10, 106832, 180000, 220000, 440000),
        2064: (40000, 10, 106832, 180000, 220000, 440000),
        2065: (40000, 5, 29416, 50000, 61000, 122000),
        2066: (40000, 390, 90000, 362000, 412000, 824000),
        2067: (40000, 10, 84160, 300000, 300000, 600000),
        2068: (40000, 2, 16832, 60000, 60000, 120000),
        2070: (0, 8, 168000, 0, 168000, 336000),
    }
    results = []
    for test_id, (hz, count, x, y, master, callbacks) in totals.items():
        metrics = {
            "hz": hz, "n": count, "xe": x, "ye": y, "ms": master,
            "i2": callbacks, "i7": 0, "pu": 0, "ps": 0,
            "am": 1400, "cm": 900, "dm": 1500, "tm": 2100,
            "de": 25, "sg": 65, "wd": 70, "sa": 0, "wl": 0,
            "cw": 0, "sf": 0, "xd": 4, "yd": 5, "to": 0,
        }
        if test_id <= 2064:
            metrics.update({"ok": 1, "aa": 800, "ca": 500, "da": 850})
        elif test_id < 2068:
            metrics["ok"] = 1
        elif test_id == 2068:
            metrics.update({
                "pa": 1, "ra": 1, "pm": 1, "rm": 1,
                "p2": 1, "r2": 1, "p1": 1, "r1": 1,
                "rej": 0, "flt": 0, "g": 0,
            })
        else:
            metrics.update({
                "ok": 1, "p30": 2, "n30": 3, "p35": 3, "n35": 4,
                "p4l": 5, "n4l": 4, "p40": 6, "n40": 5,
                "an": 140000, "al": 70000,
            })
        results.append({
            "test_id": test_id,
            "name": f"m6_{test_id}",
            "pass": True,
            "metrics": metrics,
        })
    raw = {
        "run_id": 2069,
        "profile": "FULL",
        "started_at": "2026-08-11T00:00:00Z",
        "finished_at": "2026-08-11T00:10:00Z",
        "aborted": False,
        "summary": {"total": 10, "passed": 10, "failed": 0},
        "results": results,
        "host_checks": [
            {"name": "coordinated_xy_status_cadence", "pass": True, "details": {"status_gap_max_ms": 200}}
        ],
    }

    accepted = _analyze(raw, manifest)
    assert accepted["verdict"]["status"] == "pass"
    results[4]["metrics"]["pu"] = 1
    rejected = _analyze(raw, manifest)
    assert rejected["verdict"]["status"] == "fail"
    assert any(
        item.get("metric_name") == "pu" and item.get("status") == "fail"
        for item in rejected["metric_evaluations"]
    )


def test_camera_transition_manifest_accepts_complete_home_and_blocks_missing_enable():
    manifest = load_manifest("coordinated_xy_camera_transition_v1")
    metrics = {
        "fs": 0, "n": 2, "xe": 16832, "ye": 60000,
        "i2": 120000, "i7": 0, "pu": 0, "am": 1200, "tm": 2200,
        "en": 1, "sl": 1, "ow": 0, "lb": 0,
        "hs": 8916, "he": 100, "hg": 11916, "hc": 11916,
        "ha": 8916, "hp": 7, "ho": 2, "hl": 1, "la": 0,
        "hi": 201, "hpc": 100, "hpu": 0, "hd": 3, "to": 0,
    }
    raw = {
        "run_id": 2071,
        "profile": "FULL",
        "started_at": "2026-08-12T00:00:00Z",
        "finished_at": "2026-08-12T00:00:10Z",
        "aborted": False,
        "summary": {"total": 1, "passed": 1, "failed": 0},
        "results": [{
            "test_id": 2071,
            "name": "coord_xy_camera_home_transition",
            "pass": True,
            "metrics": metrics,
        }],
        "host_checks": [{"name": "hello_ack", "pass": True, "details": {}}],
    }

    assert _analyze(raw, manifest)["verdict"]["status"] == "pass"
    raw["results"][0]["metrics"] = {**metrics, "en": 0}
    assert _analyze(raw, manifest)["verdict"]["status"] == "fail"


def test_standalone_40khz_manifest_accepts_exact_row_and_blocks_home_drift():
    manifest = load_manifest("coordinated_xy_40khz_v1")
    metrics = {
        "hz": 40000, "n": 10, "xe": 106832, "ye": 180000,
        "ms": 220000, "i2": 440000, "i7": 0, "ok": 1,
        "pu": 0, "ps": 0, "am": 1200, "aa": 800,
        "cm": 900, "ca": 600, "dm": 1300, "da": 850,
        "tm": 2150, "de": 20, "sg": 65, "wd": 70,
        "sa": 0, "wl": 0, "cw": 1, "sf": 0,
        "xd": 4, "yd": 5, "to": 0,
    }
    raw = {
        "run_id": 2077,
        "profile": "FULL",
        "started_at": "2026-08-12T00:00:00Z",
        "finished_at": "2026-08-12T00:00:10Z",
        "aborted": False,
        "summary": {"total": 3, "passed": 3, "failed": 0},
        "results": [
            {
                "test_id": 2064,
                "name": "coordinated_xy_performance_40khz",
                "pass": True,
                "metrics": metrics,
            },
            {
                "test_id": 2072,
                "name": "coord_xy_40khz_irq_path",
                "pass": True,
                "metrics": {
                    "i2": 440000, "s": 440000, "mi": 0,
                    "ph": 50, "pa": 20, "fm": 1500, "fa": 900,
                    "ax": 1450, "tf": 2200, "pp": 0, "pf": 0, "pu": 0,
                    "ps": 0, "sf": 0, "to": 0,
                },
            },
            {
                "test_id": 2073,
                "name": "coord_xy_40khz_entry_lateness",
                "pass": True,
                "metrics": {
                    "i2": 440000, "s": 440000, "mi": 0,
                    "cm": 100, "ca": 20, "pm": 0, "lc": 0,
                    "dm": 100, "sm": 0, "sf": 0, "to": 0,
                },
            },
        ],
        "host_checks": [{
            "name": "coordinated_xy_status_cadence",
            "pass": True,
            "details": {"status_gap_max_ms": 100},
        }],
    }

    assert _analyze(raw, manifest)["verdict"]["status"] == "pass"
    raw["results"][0]["metrics"] = {**metrics, "xd": 26}
    assert _analyze(raw, manifest)["verdict"]["status"] == "fail"

    raw["results"][0]["metrics"] = metrics
    raw["results"][2]["metrics"]["mi"] = 1
    assert _analyze(raw, manifest)["verdict"]["status"] == "fail"

    raw["results"][2]["metrics"]["mi"] = 0
    raw["results"][2]["metrics"]["s"] = 439999
    assert _analyze(raw, manifest)["verdict"]["status"] == "fail"


def test_status_sync_manifest_requires_complete_low_lateness_mutex_evidence():
    manifest = load_manifest("coordinated_xy_status_sync_v1")
    motion = {
        "hz": 40000, "n": 10, "xe": 106832, "ye": 180000,
        "ms": 220000, "i2": 440000, "i7": 0, "ok": 1,
        "pu": 0, "ps": 0, "am": 1200, "aa": 800,
        "cm": 900, "ca": 600, "dm": 1300, "da": 850,
        "tm": 2150, "de": 20, "sg": 65, "wd": 70,
        "sa": 0, "wl": 0, "cw": 1, "sf": 0,
        "xd": 4, "yd": 5, "to": 0,
    }
    irq = {
        "i2": 440000, "s": 440000, "mi": 0,
        "ph": 50, "pa": 20, "fm": 1500, "fa": 900,
        "ax": 1450, "tf": 2200, "pp": 0, "pf": 0,
        "pu": 0, "ps": 0, "sf": 0, "to": 0,
    }
    entry = {
        "i2": 440000, "s": 440000, "mi": 0,
        "cm": 127, "ca": 20, "pm": 0, "lc": 0,
        "dm": 255, "sm": 1, "lf": 0, "sf": 0, "to": 0,
        "fv": 0, "tr": 0, "la": 0, "ra": 0,
    }
    valid = {
        "run_id": 2076,
        "profile": "FULL",
        "started_at": "2026-08-12T00:00:00Z",
        "finished_at": "2026-08-12T00:00:10Z",
        "aborted": False,
        "summary": {"total": 3, "passed": 3, "failed": 0},
        "results": [
            {"test_id": 2064, "name": "coordinated_xy_performance_40khz", "pass": True, "metrics": motion},
            {"test_id": 2072, "name": "coord_xy_40khz_irq_path", "pass": True, "metrics": irq},
            {"test_id": 2073, "name": "coord_xy_40khz_entry_lateness", "pass": True, "metrics": entry},
        ],
        "host_checks": [{
            "name": "coordinated_xy_status_cadence",
            "pass": True,
            "details": {"status_gap_max_ms": 100},
        }],
    }

    assert _analyze(valid, manifest)["verdict"]["status"] == "pass"
    mutations = (
        (0, "pu", 1),
        (0, "wl", 1),
        (1, "pu", 1),
        (1, "mi", 1),
        (2, "s", 439999),
        (2, "cm", 128),
        (2, "lc", 1),
        (2, "dm", 256),
        (2, "sm", 0),
        (2, "lf", 1),
        (2, "sf", 1),
        (2, "to", 1),
        (2, "fv", 1),
        (2, "tr", 3),
        (2, "la", 1),
        (2, "ra", 1),
    )
    for result_index, metric, value in mutations:
        rejected = deepcopy(valid)
        rejected["results"][result_index]["metrics"][metric] = value
        assert _analyze(rejected, manifest)["verdict"]["status"] == "fail"


def test_mres3_manifest_rejects_unscaled_or_incomplete_timing_evidence():
    manifest = load_manifest("coordinated_xy_mres3_20khz_v1")
    valid = {
        "run_id": 2085,
        "profile": "FULL",
        "started_at": "2026-08-12T00:00:00Z",
        "finished_at": "2026-08-12T00:00:10Z",
        "aborted": False,
        "summary": {"total": 4, "passed": 4, "failed": 0},
        "results": [
            {"test_id": 2080, "name": "coord_xy_mres3_20khz_motion", "pass": True,
             "metrics": {"hz": 20000, "n": 10, "xe": 53416, "ye": 90000,
                         "ms": 110000, "i2": 220000, "i7": 0, "ok": 1,
                         "pu": 0, "ps": 0, "am": 1100, "aa": 700,
                         "cm": 900, "ca": 600, "dm": 1200, "da": 800,
                         "tm": 2100, "de": 20, "sg": 60, "wd": 70,
                         "sa": 0, "wl": 0, "cw": 1, "sf": 0,
                         "xd": 4, "yd": 5, "to": 0}},
            {"test_id": 2081, "name": "coord_xy_mres3_20khz_irq_path", "pass": True,
             "metrics": {"i2": 220000, "s": 220000, "mi": 0,
                         "ph": 50, "pa": 20, "fm": 1500, "fa": 900,
                         "ax": 1450, "tf": 2200, "pp": 0, "pf": 0,
                         "pu": 0, "ps": 0, "sf": 0, "to": 0}},
            {"test_id": 2082, "name": "coord_xy_mres3_entry_margin", "pass": True,
             "metrics": {"i2": 220000, "s": 220000, "mi": 0,
                         "cm": 40, "ca": 12, "pm": 0, "lc": 0, "dm": 80,
                         "ds": 219990, "di": 0, "md": 0, "sl": 700,
                         "sm": 0, "lf": 0, "sf": 0, "to": 0,
                         "fv": 0, "tr": 0, "la": 0, "ra": 0}},
            {"test_id": 2083, "name": "tmc2208_mres3_configuration", "pass": True,
             "metrics": {"mr": 3, "mf": 0, "dd": 1, "gc": 193,
                         "cc": 855638099, "tx": 4, "tf": 0, "ve": 1,
                         "ae": 1, "ge": 1, "sf": 0, "to": 0}},
        ],
        "host_checks": [{"name": "coordinated_xy_status_cadence", "pass": True,
                         "details": {"status_gap_max_ms": 100}}],
    }

    assert _analyze(valid, manifest)["verdict"]["status"] == "pass"
    mutations = (
        (0, "hz", 40000),
        (0, "xe", 106832),
        (0, "pu", 1),
        (1, "s", 219999),
        (1, "pu", 1),
        (2, "ds", 219989),
        (2, "md", 1),
        (2, "sl", 449),
        (3, "mr", 2),
        (3, "mf", 1),
        (3, "tf", 1),
    )
    for result_index, metric, value in mutations:
        rejected = deepcopy(valid)
        rejected["results"][result_index]["metrics"][metric] = value
        assert _analyze(rejected, manifest)["verdict"]["status"] == "fail"

    cadence_failure = deepcopy(valid)
    cadence_failure["host_checks"][0]["pass"] = False
    assert _analyze(cadence_failure, manifest)["verdict"]["status"] == "fail"


def test_mres3_conditional_manifest_rejects_incomplete_late_rearm_evidence():
    manifest = load_manifest("coordinated_xy_mres3_conditional_rearm_v1")
    results = []
    for test_id in manifest.expected_test_ids:
        metrics = {}
        for metric, rule in manifest.analysis_rules[str(test_id)]["metrics"].items():
            if "equals" in rule:
                metrics[metric] = rule["equals"]
            elif "min" in rule:
                metrics[metric] = rule["min"]
            else:
                metrics[metric] = 0
        results.append({
            "test_id": test_id,
            "name": f"diagnostic_{test_id}",
            "pass": True,
            "metrics": metrics,
        })
    valid = {
        "run_id": 2086,
        "profile": "FULL",
        "started_at": "2026-08-13T00:00:00Z",
        "finished_at": "2026-08-13T00:00:10Z",
        "aborted": False,
        "summary": {"total": 5, "passed": 5, "failed": 0},
        "results": results,
        "host_checks": [
            {"name": "coordinated_xy_status_cadence", "pass": True,
             "details": {"status_gap_max_ms": 100}},
            {"name": "watchdog", "pass": True, "details": {"late": 0}},
        ],
    }
    assert _analyze(valid, manifest)["verdict"]["status"] == "pass"

    conditional_index = manifest.expected_test_ids.index(2086)
    for metric, value in (
        ("rm", 1), ("dc", 219989), ("mi", 1), ("rc", 9),
        ("rp", 1), ("ic", 9), ("ix", 1), ("ir", 9),
        ("im", 1126), ("ns", 1125), ("wm", 4501), ("sf", 1),
        ("to", 1),
    ):
        rejected = deepcopy(valid)
        rejected["results"][conditional_index]["metrics"][metric] = value
        assert _analyze(rejected, manifest)["verdict"]["status"] == "fail"

    cadence_failure = deepcopy(valid)
    cadence_failure["host_checks"][0]["pass"] = False
    assert _analyze(cadence_failure, manifest)["verdict"]["status"] == "fail"


def test_mres3_revised_manifests_reject_strict_masks_and_partial_rows():
    for manifest_id in (
        "coordinated_xy_mres3_20khz_v2",
        "coordinated_xy_mres3_conditional_rearm_v2",
        "coordinated_xy_mres3_conditional_rearm_v3",
    ):
        manifest = load_manifest(manifest_id)
        results = []
        for test_id in manifest.expected_test_ids:
            metrics = {}
            for metric, rule in manifest.analysis_rules[str(test_id)]["metrics"].items():
                if "equals" in rule:
                    metrics[metric] = rule["equals"]
                elif "min" in rule:
                    metrics[metric] = rule["min"]
                else:
                    metrics[metric] = 0
            results.append({
                "test_id": test_id,
                "name": f"diagnostic_{test_id}",
                "pass": True,
                "metrics": metrics,
            })
        valid = {
            "run_id": 2086,
            "profile": "FULL",
            "started_at": "2026-08-13T00:00:00Z",
            "finished_at": "2026-08-13T00:00:10Z",
            "aborted": False,
            "summary": {"total": len(results), "passed": len(results), "failed": 0},
            "results": results,
            "host_checks": [
                {"name": "coordinated_xy_status_cadence", "pass": True,
                 "details": {"status_gap_max_ms": 100}},
                {"name": "watchdog", "pass": True, "details": {"late": 0}},
            ],
        }
        assert _analyze(valid, manifest)["verdict"]["status"] == "pass"

        for result_id, metric, value in (
            (2080, "qf", 1),
            (2080, "qm", 1 << 19),
            (2082, "hm", 1 << 1),
        ):
            rejected = deepcopy(valid)
            index = manifest.expected_test_ids.index(result_id)
            rejected["results"][index]["metrics"][metric] = value
            rejected["results"][index]["pass"] = False
            rejected["summary"] = {
                "total": len(results), "passed": len(results) - 1, "failed": 1,
            }
            assert _analyze(rejected, manifest)["verdict"]["status"] == "fail"

        partial = deepcopy(valid)
        motion_index = manifest.expected_test_ids.index(2080)
        partial["results"][motion_index]["metrics"]["n"] = 9
        assert _analyze(partial, manifest)["verdict"]["status"] == "fail"


def test_production_mres3_manifest_rejects_conversion_or_rearm_regressions():
    manifest = load_manifest("coordinated_xy_production_mres3_v1")
    results = []
    for test_id in manifest.expected_test_ids:
        metrics = {}
        for metric, rule in manifest.analysis_rules[str(test_id)]["metrics"].items():
            if "equals" in rule:
                metrics[metric] = rule["equals"]
            elif "min" in rule:
                metrics[metric] = rule["min"]
            else:
                metrics[metric] = 0
        results.append({
            "test_id": test_id,
            "name": f"production_{test_id}",
            "pass": True,
            "metrics": metrics,
        })
    valid = {
        "run_id": 2097,
        "profile": "FULL",
        "started_at": "2026-08-13T00:00:00Z",
        "finished_at": "2026-08-13T00:00:10Z",
        "aborted": False,
        "summary": {"total": 4, "passed": 4, "failed": 0},
        "results": results,
        "host_checks": [
            {"name": "coordinated_xy_status_cadence", "pass": True,
             "details": {"status_gap_max_ms": 100}},
            {"name": "watchdog", "pass": True, "details": {"late": 0}},
        ],
    }
    assert _analyze(valid, manifest)["verdict"]["status"] == "pass"

    terminal_cleanup_warning = deepcopy(valid)
    motion_index = manifest.expected_test_ids.index(2087)
    terminal_cleanup_warning["results"][motion_index]["metrics"]["tm"] = 5000
    analyzed_warning = _analyze(terminal_cleanup_warning, manifest)
    assert analyzed_warning["verdict"]["status"] == "pass"
    assert analyzed_warning["verdict"]["warning_count"] >= 1

    for result_id, metric, value in (
        (2087, "n", 9),
        (2087, "qf", 1),
        (2087, "pu", 1),
        (2088, "s", 219999),
        (2089, "rm", 0),
        (2089, "dc", 219989),
        (2089, "ci", 1),
        (2089, "ns", 1125),
        (2089, "md", 1),
        (2089, "rp", 1),
        (2089, "sl", 449),
        (2090, "mr", 2),
        (2090, "lu", 1),
        (2090, "ge", 0),
    ):
        rejected = deepcopy(valid)
        index = manifest.expected_test_ids.index(result_id)
        rejected["results"][index]["metrics"][metric] = value
        assert _analyze(rejected, manifest)["verdict"]["status"] == "fail"

    cadence_failure = deepcopy(valid)
    cadence_failure["host_checks"][0]["pass"] = False
    assert _analyze(cadence_failure, manifest)["verdict"]["status"] == "fail"


def test_production_mres3_v2_rejects_reduced_evidence_regressions():
    manifest = load_manifest("coordinated_xy_production_mres3_v2")
    results = []
    for test_id in manifest.expected_test_ids:
        metrics = {}
        for metric, rule in manifest.analysis_rules[str(test_id)]["metrics"].items():
            if "equals" in rule:
                metrics[metric] = rule["equals"]
            elif "min" in rule:
                metrics[metric] = rule["min"]
            else:
                metrics[metric] = 0
        results.append({
            "test_id": test_id,
            "name": f"production_v2_{test_id}",
            "pass": True,
            "metrics": metrics,
        })
    valid = {
        "run_id": 2097,
        "profile": "FULL",
        "started_at": "2026-08-13T00:00:00Z",
        "finished_at": "2026-08-13T00:00:10Z",
        "aborted": False,
        "summary": {"total": 4, "passed": 4, "failed": 0},
        "results": results,
        "host_checks": [
            {"name": "selftest_progress_watchdog", "pass": True,
             "details": {"timeout_reason": None}},
            {"name": "coordinated_xy_status_cadence", "pass": True,
             "details": {"status_gap_max_ms": 100}},
        ],
    }
    assert _analyze(valid, manifest)["verdict"]["status"] == "pass"

    for result_id, metric, value in (
        (2087, "n", 9),
        (2087, "i2", 219999),
        (2087, "ok", 0),
        (2087, "pu", 1),
        (2087, "tm", 2701),
        (2087, "sf", 1),
        (2088, "s", 219999),
        (2088, "mi", 1),
        (2089, "ds", 219989),
        (2089, "di", 1),
        (2089, "md", 1),
        (2089, "sl", 449),
        (2089, "dc", 219989),
        (2089, "ci", 1),
        (2089, "ns", 1125),
        (2089, "rp", 1),
        (2090, "mr", 2),
        (2090, "mf", 1),
        (2090, "dd", 0),
        (2090, "lu", 1),
    ):
        rejected = deepcopy(valid)
        index = manifest.expected_test_ids.index(result_id)
        rejected["results"][index]["metrics"][metric] = value
        assert _analyze(rejected, manifest)["verdict"]["status"] == "fail"

    incomplete = deepcopy(valid)
    incomplete["results"].pop()
    incomplete["summary"] = {"total": 3, "passed": 3, "failed": 0}
    assert _analyze(incomplete, manifest)["verdict"]["status"] == "fail"

    for host_index in range(2):
        host_failure = deepcopy(valid)
        host_failure["host_checks"][host_index]["pass"] = False
        assert _analyze(host_failure, manifest)["verdict"]["status"] == "fail"


def test_production_mres3_v3_rejects_limit_debounce_regressions():
    manifest = load_manifest("coordinated_xy_production_mres3_v3")
    results = []
    for test_id in manifest.expected_test_ids:
        metrics = {}
        for metric, rule in manifest.analysis_rules[str(test_id)]["metrics"].items():
            if "equals" in rule:
                metrics[metric] = rule["equals"]
            elif "min" in rule:
                metrics[metric] = rule["min"]
            else:
                metrics[metric] = 0
        results.append({
            "test_id": test_id,
            "name": f"production_v3_{test_id}",
            "pass": True,
            "metrics": metrics,
        })
    valid = {
        "run_id": 2097,
        "profile": "FULL",
        "started_at": "2026-08-13T00:00:00Z",
        "finished_at": "2026-08-13T00:00:10Z",
        "aborted": False,
        "summary": {"total": 5, "passed": 5, "failed": 0},
        "results": results,
        "host_checks": [
            {"name": "selftest_progress_watchdog", "pass": True,
             "details": {"timeout_reason": None}},
            {"name": "coordinated_xy_status_cadence", "pass": True,
             "details": {"status_gap_max_ms": 100}},
        ],
    }
    assert _analyze(valid, manifest)["verdict"]["status"] == "pass"

    # Candidates and rejected electrical transients are retained evidence,
    # not qualification failures.
    informational = deepcopy(valid)
    debounce_index = manifest.expected_test_ids.index(2098)
    informational["results"][debounce_index]["metrics"]["xc"] = 2
    informational["results"][debounce_index]["metrics"]["xr"] = 2
    assert _analyze(informational, manifest)["verdict"]["status"] == "pass"

    for metric, value in (
        ("n", 9),
        ("xf", 1),
        ("xp", 1),
        ("yf", 1),
        ("yp", 1),
        ("tv", 0),
        ("tf", 1),
        ("tr", 2),
        ("sf", 1),
        ("to", 1),
    ):
        rejected = deepcopy(valid)
        rejected["results"][debounce_index]["metrics"][metric] = value
        assert _analyze(rejected, manifest)["verdict"]["status"] == "fail"

    incomplete = deepcopy(valid)
    incomplete["results"].pop()
    incomplete["summary"] = {"total": 4, "passed": 4, "failed": 0}
    assert _analyze(incomplete, manifest)["verdict"]["status"] == "fail"

    for host_index in range(2):
        host_failure = deepcopy(valid)
        host_failure["host_checks"][host_index]["pass"] = False
        assert _analyze(host_failure, manifest)["verdict"]["status"] == "fail"


def test_camera_transition_v2_rejects_scaled_count_and_home_regressions():
    manifest = load_manifest("coordinated_xy_camera_transition_v2")
    rules = manifest.analysis_rules["2071"]["metrics"]
    metrics = {
        name: rule.get("equals", rule.get("min", 0))
        for name, rule in rules.items()
    }
    valid = {
        "run_id": 2078,
        "profile": "FULL",
        "started_at": "2026-08-13T00:00:00Z",
        "finished_at": "2026-08-13T00:00:10Z",
        "aborted": False,
        "summary": {"total": 1, "passed": 1, "failed": 0},
        "results": [{
            "test_id": 2071,
            "name": "coord_xy_camera_home_transition",
            "pass": True,
            "metrics": metrics,
        }],
        "host_checks": [
            {"name": "selftest_progress_watchdog", "pass": True,
             "details": {"timeout_reason": None}},
            {"name": "coordinated_xy_status_cadence", "pass": True,
             "details": {"status_gap_max_ms": 100}},
        ],
    }
    assert _analyze(valid, manifest)["verdict"]["status"] == "pass"

    for metric, value in (
        ("xe", 8415), ("ye", 29999), ("i2", 59999), ("pu", 1),
        ("en", 0), ("sl", 0), ("ow", 1), ("lb", 1),
        ("hi", 100), ("hpc", 49), ("hpu", 1), ("hd", 26),
        ("sf", 1), ("to", 1),
    ):
        rejected = deepcopy(valid)
        rejected["results"][0]["metrics"][metric] = value
        assert _analyze(rejected, manifest)["verdict"]["status"] == "fail"


def test_direct_xyz_lut_manifest_rejects_profile_timing_or_isolation_regressions():
    manifest = load_manifest("direct_xyz_lut_v1")
    results = []
    for test_id in manifest.expected_test_ids:
        metrics = {}
        for metric, rule in manifest.analysis_rules[str(test_id)]["metrics"].items():
            if "equals" in rule:
                metrics[metric] = rule["equals"]
            elif "min" in rule:
                metrics[metric] = rule["min"]
            else:
                metrics[metric] = 0
        results.append({
            "test_id": test_id,
            "name": f"direct_lut_{test_id}",
            "pass": True,
            "metrics": metrics,
        })
    valid = {
        "run_id": 2096,
        "profile": "FULL",
        "started_at": "2026-08-13T00:00:00Z",
        "finished_at": "2026-08-13T00:00:10Z",
        "aborted": False,
        "summary": {"total": 5, "passed": 5, "failed": 0},
        "results": results,
        "host_checks": [
            {"name": "coordinated_xy_status_cadence", "pass": True,
             "details": {"status_gap_max_ms": 100}},
            {"name": "selftest_progress_watchdog", "pass": True,
             "details": {"timeout_reason": None}},
        ],
    }
    assert _analyze(valid, manifest)["verdict"]["status"] == "pass"

    for result_id, metric, value in (
        (2091, "nm", 0),
        (2091, "rf", 1),
        (2091, "dc", 5714),
        (2091, "po", 1),
        (2091, "mx", 2251),
        (2092, "pc", 6999),
        (2093, "co", 0),
        (2094, "ai", 999),
        (2095, "post", 0),
        (2095, "pd", 2),
        (2095, "mres", 2),
        (2095, "sn", 1),
        (2095, "sg", 126),
        (2095, "wd", 101),
        (2095, "sa", 1),
        (2095, "sv", 0),
    ):
        rejected = deepcopy(valid)
        index = manifest.expected_test_ids.index(result_id)
        rejected["results"][index]["metrics"][metric] = value
        assert _analyze(rejected, manifest)["verdict"]["status"] == "fail"

    incomplete = deepcopy(valid)
    incomplete["results"] = incomplete["results"][:-1]
    incomplete["summary"] = {"total": 4, "passed": 4, "failed": 0}
    assert _analyze(incomplete, manifest)["verdict"]["status"] == "fail"

def test_single_irq_manifest_requires_one_callback_and_complete_pulse_margin():
    manifest = load_manifest("coordinated_xy_single_irq_v1")
    motion = {
        "hz": 40000, "n": 10, "xe": 106832, "ye": 180000,
        "ms": 220000, "i2": 220000, "i7": 0, "ok": 1,
        "pu": 0, "ps": 0, "am": 1300, "aa": 900,
        "cm": 1200, "ca": 850, "dm": 1400, "da": 950,
        "tm": 2200, "de": 20, "sg": 65, "wd": 70,
        "sa": 0, "wl": 0, "cw": 1, "sf": 0,
        "xd": 4, "yd": 5, "to": 0,
    }
    irq = {
        "i2": 220000, "s": 220000, "mi": 0,
        "ph": 50, "pa": 20, "fm": 1600, "fa": 1000,
        "ax": 1550, "tf": 2200, "pp": 0, "pf": 0,
        "pu": 0, "ps": 0, "sf": 0, "to": 0,
    }
    entry = {
        "i2": 220000, "s": 220000, "mi": 0,
        "cm": 180, "ca": 25, "pm": 0, "lc": 2,
        "dm": 300, "sm": 0, "lf": 0, "sf": 0, "to": 0,
        "fv": 0, "tr": 0, "la": 0, "ra": 0,
    }
    pulse = {
        "em": 1, "ip": 1, "i2": 220000, "pc": 220000,
        "pn": 360, "px": 700, "pe": 360, "ds": 220000,
        "mi": 0, "md": 0, "sl": 700, "pu": 0, "ok": 1,
        "sf": 0, "to": 0,
    }
    valid = {
        "run_id": 2075,
        "profile": "FULL",
        "started_at": "2026-08-12T00:00:00Z",
        "finished_at": "2026-08-12T00:00:10Z",
        "aborted": False,
        "summary": {"total": 4, "passed": 4, "failed": 0},
        "results": [
            {"test_id": 2064, "name": "coordinated_xy_performance_40khz", "pass": True, "metrics": motion},
            {"test_id": 2072, "name": "coord_xy_40khz_irq_path", "pass": True, "metrics": irq},
            {"test_id": 2073, "name": "coord_xy_40khz_entry_lateness", "pass": True, "metrics": entry},
            {"test_id": 2074, "name": "coord_xy_single_irq_pulse", "pass": True, "metrics": pulse},
        ],
        "host_checks": [{
            "name": "coordinated_xy_status_cadence",
            "pass": True,
            "details": {"status_gap_max_ms": 100},
        }],
    }

    assert _analyze(valid, manifest)["verdict"]["status"] == "pass"
    mutations = (
        (0, "i2", 440000), (0, "pu", 1),
        (1, "s", 219999), (1, "pu", 1),
        (2, "mi", 1), (2, "sm", 1), (2, "tr", 5), (2, "ra", 1),
        (3, "em", 0), (3, "ip", 2), (3, "pc", 219999),
        (3, "pn", 359), (3, "pe", 359), (3, "ds", 219999),
        (3, "mi", 1), (3, "md", 1), (3, "sl", 499),
        (3, "pu", 1), (3, "sf", 1), (3, "to", 1),
    )
    for result_index, metric, value in mutations:
        rejected = deepcopy(valid)
        rejected["results"][result_index]["metrics"][metric] = value
        assert _analyze(rejected, manifest)["verdict"]["status"] == "fail"

    cadence_failure = deepcopy(valid)
    cadence_failure["host_checks"][0]["pass"] = False
    assert _analyze(cadence_failure, manifest)["verdict"]["status"] == "fail"


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


def test_normal_xy_route_manifest_accepts_nominal_and_blocks_physical_window_regression():
    manifest = load_manifest("normal_xy_route_v1")
    common_round_trip = {
        "hz": 3000, "route": 1, "i7": 0, "edge": 1, "ck": 1,
        "low": 1, "done": 1, "pu": 0, "cy": 1200, "ep": 1,
        "ret": 1, "to": 0,
    }
    results = [
        {"test_id": 2050, "name": "normal_xy_route_x_only_low", "pass": True,
         "metrics": {**common_round_trip, "dx": 1000, "dy": 0, "xe": 2000,
                     "ye": 0, "ms": 1000, "i2": 4000}},
        {"test_id": 2051, "name": "normal_xy_route_y_only_low", "pass": True,
         "metrics": {**common_round_trip, "dx": 0, "dy": 1000, "xe": 0,
                     "ye": 2000, "ms": 1000, "i2": 4000}},
        {"test_id": 2052, "name": "normal_xy_route_equal_low", "pass": True,
         "metrics": {**common_round_trip, "dx": 1000, "dy": 1000, "xe": 2000,
                     "ye": 2000, "ms": 1000, "i2": 4000}},
        {"test_id": 2053, "name": "normal_xy_route_asymmetric_low", "pass": True,
         "metrics": {**common_round_trip, "dx": 500, "dy": 1500, "xe": 1000,
                     "ye": 3000, "ms": 1500, "i2": 6000}},
        {"test_id": 2054, "name": "normal_xy_route_long_status", "pass": True,
         "metrics": {"dx": 6000, "dy": 2000, "hz": 3000, "route": 1,
                     "hold": 1, "acq": 0, "clean": 1, "sf": 20, "sg": 55,
                     "sa": 60, "alt": 0, "i2": 24000, "i7": 0, "low": 1,
                     "pu": 0, "cy": 1400, "ep": 1, "ret": 1, "to": 0}},
        {"test_id": 2055, "name": "normal_xy_route_control_low", "pass": True,
         "metrics": {"dx": 2000, "dy": 1000, "hz": 3000, "route": 1,
                     "pause": 1, "stable": 1, "resume": 1, "cancel": 1,
                     "lat": 1, "rise": 0, "rebase": 1, "low": 1, "i7": 0,
                     "pu": 0, "cy": 1400, "recover": 1, "to": 0}},
        {"test_id": 2056, "name": "normal_xy_route_physical_limit", "pass": True,
         "metrics": {"hz": 3000, "route": 1, "win": 200, "xl": 1, "yl": 1,
                     "xe": 100, "ye": 100, "xlat": 1, "ylat": 1, "xrise": 0,
                     "yrise": 0, "req": 2, "raw": 2, "rebase": 1, "low": 1,
                     "i7": 0, "pu": 0, "cy": 1500, "xd": 5, "yd": 6,
                     "home": 1, "to": 0}},
        {"test_id": 2057, "name": "normal_xy_route_legacy_smoke", "pass": True,
         "metrics": {"hz": 3000, "route": 1, "x": 1, "y": 1, "z": 1,
                     "pr": 1, "own": 0, "low": 1, "xret": 0, "yret": 0,
                     "zret": 0, "xd": 5, "yd": 6, "home": 1, "to": 0}},
    ]
    raw = {
        "run_id": 2059,
        "profile": "FULL",
        "started_at": "2026-08-11T00:00:00Z",
        "finished_at": "2026-08-11T00:00:20Z",
        "aborted": False,
        "summary": {"total": 8, "passed": 8, "failed": 0},
        "results": results,
        "host_checks": [],
    }

    accepted = _analyze(raw, manifest)
    assert accepted["verdict"]["status"] == "pass"

    raw["results"][6]["metrics"] = {**raw["results"][6]["metrics"], "xe": 201}
    regressed = _analyze(raw, manifest)
    assert regressed["verdict"]["status"] == "fail"
    failures = [item for item in regressed["metric_evaluations"] if item["status"] == "fail"]
    assert [(item["test_id"], item["metric_name"]) for item in failures] == [(2056, "xe")]


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
