from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from tools.sil.calibration_storage_baseline import (
    BASELINE_ID,
    CalibrationStorageBaselineError,
    candidate_upper_limit,
    create_calibration_storage_baseline,
    freeze_calibration_storage_baseline,
)
from tools.virtual_workflows.compare import (
    CALIBRATION_STORAGE_METRIC_PROFILE,
    ComparisonIncompleteError,
    build_report_set,
    create_baseline_summary,
    validate_report_set,
)
from tools.virtual_workflows.report import REPORT_SCHEMA_NAME, REPORT_SCHEMA_VERSION


TRACKED_PI_BASELINE = (
    Path(__file__).resolve().parent
    / "performance"
    / "baselines"
    / "calibration_storage_legacy_pi5_v1.json"
)


def _distribution(value: float, count: int = 3) -> dict:
    return {
        "count": count,
        "minimum": value * 0.8,
        "median": value * 0.9,
        "p95": value,
        "maximum": value * 1.1,
    }


def _report(run_id: str, value: float) -> dict:
    storage_metrics = {
        name: _distribution(value)
        for name in (
            "calibration_rewrite_latency_ms",
            "recorder_append_latency_ms",
            "update_latency_ms",
            "process_finalize_latency_ms",
            "first_quartile_update_latency_ms",
            "last_quartile_update_latency_ms",
            "history_load_latency_ms",
            "fresh_reload_latency_ms",
        )
    }
    storage_metrics.update(
        {
            "result_finalize_latency": {
                "samples": [],
                "status": "not_available_until_m2",
            },
            "index_latency": {
                "samples": [],
                "status": "not_available_until_m2",
            },
        }
    )
    return {
        "schema_name": REPORT_SCHEMA_NAME,
        "schema_version": REPORT_SCHEMA_VERSION,
        "run": {
            "run_id": run_id,
            "scenario_name": "calibration_storage_legacy_baseline",
            "scenario_version": "1",
            "run_mode": "offscreen_pi_sil",
            "timing_policy": "simulated_command_durations_x1000",
            "warmup_runs": 0,
            "measured_runs": 1,
            "started_at_utc": "2026-08-14T00:00:00Z",
            "ended_at_utc": "2026-08-14T00:02:00Z",
            "duration_ms": 120000.0,
        },
        "source": {
            "git_commit": "a" * 40,
            "git_short_commit": "a" * 12,
            "dirty_worktree": False,
            "git_error": None,
        },
        "environment": {
            "operating_system": "Linux",
            "os_release": "6.12",
            "architecture": "aarch64",
            "cpu_identifier": "Cortex-A76",
            "python_version": "3.13.14",
            "python_implementation": "CPython",
            "python_executable": "/repo/env/bin/python",
            "qt": {
                "binding": "real",
                "pyside_version": "6.11.1",
                "qt_version": "6.11.1",
                "module_path": "/repo/env/lib/PySide6/__init__.py",
                "platform": "offscreen",
            },
            "target_pi": {
                "lane": "raspberry_pi_sil",
                "pi_model": "Raspberry Pi 5 Model B Rev 1.0",
                "filesystem": {
                    "filesystem_type": "ext4",
                    "storage_class": "sd",
                    "mount_source": "/dev/mmcblk0p2",
                },
            },
        },
        "safety": {
            "simulation": True,
            "hardware_access_allowed": False,
            "hardware_interfaces": {
                "serial": False,
                "GPIO": False,
                "camera": False,
                "balance": False,
                "MCU": False,
                "firmware_update": False,
            },
            "simulated_port": "SIMULATED",
            "scenario_root": "/tmp/storage-sil",
            "root_containment_valid": True,
            "pi_sil": {
                "sandbox_method": "bubblewrap_private_dev_v1",
                "private_dev": True,
                "root_read_only": True,
                "network_unshared": True,
                "forbidden_access_attempt_count": 0,
                "proof_sha256": "b" * 64,
                "trace_sha256": "c" * 64,
            },
        },
        "workload": {
            "workload_id": "calibration_storage_legacy_baseline_8x25_v1",
            "fixture_schema_version": 1,
            "fixture_sha256": "d" * 64,
            "workload_hash": "e" * 64,
            "completion_count": 200,
            "expected_update_count": 232,
        },
        "metrics": {
            "responsiveness": {
                "status": "measured",
                "values": {
                    "scheduling_lateness_ms": {"p95": 1.0, "p99": 2.0},
                    "event_loop_gap_ms": {"maximum": 3.0},
                    "phase_timings": {"duration_by_name_ms": {}},
                    "injected_stall_assessment": {"requested": False},
                },
            },
            "workflow": {"status": "measured", "values": {}},
            "queue": {"status": "measured", "values": {}},
            "persistence": {
                "status": "measured",
                "values": {
                    "calibration_storage": {
                        "process_run_count": 200,
                        "legacy_run_envelope_count": 201,
                        "update_count": 232,
                        "recording_count": 200,
                        "workload_capture_count": 0,
                        "key_evidence_probe": {"capture_count": 2},
                        "metrics": storage_metrics,
                        "artifact_growth": {
                            "calibration_json_bytes": int(value * 1_000_000),
                            "scenario_total_bytes": int(value * 3_000_000),
                        },
                    }
                },
            },
            "resources": {
                "status": "measured",
                "values": {
                    "peak_rss_bytes": int(value * 10_000_000),
                    "rss_growth_bytes": int(value * 1_000_000),
                },
            },
        },
        "artifacts": {},
        "classification": {
            "status": "pass",
            "threshold_maturity": "informational",
            "reasons": ["synthetic unit evidence"],
        },
        "limitations": [],
    }


def _report_set(reports: list[dict]) -> dict:
    refs = [
        {
            "path": f"report-{index}.json",
            "sha256": str(index) * 64,
            "run_id": report["run"]["run_id"],
        }
        for index, report in enumerate(reports, start=1)
    ]
    return {
        "host_label": "pi5-calibration-storage-legacy-v1",
        "compatibility": {
            "environment": reports[0]["environment"],
            "safety": reports[0]["safety"],
            "workload": reports[0]["workload"],
        },
        "source_summary": {
            "sources": [{"git_commit": "a" * 40, "dirty_worktree": False}],
            "any_dirty_worktree": False,
        },
        "runs": {
            "warmup_count": 1,
            "measured_count": 3,
            "warmups": [
                {"path": "warmup.json", "sha256": "f" * 64, "run_id": "warmup"}
            ],
            "measured": refs,
        },
        "functional": {"status": "pass"},
        "synthetic": {"warmup_injected_count": 0, "measured_injected_count": 0},
    }


def test_candidate_upper_limit_uses_largest_required_margin():
    result = candidate_upper_limit([10.0, 12.0, 20.0], floor=1.0)
    assert result["robust_margin"] == 12.0
    assert result["upper_limit"] == 32.0


def test_tracked_pi_candidate_baseline_has_qualified_identity_and_counts():
    baseline = json.loads(TRACKED_PI_BASELINE.read_text(encoding="utf-8"))

    assert baseline["baseline_id"] == BASELINE_ID
    assert baseline["classification"] == {
        "status": "pass",
        "threshold_maturity": "candidate",
    }
    assert baseline["source"] == {
        "dirty_worktree": False,
        "git_commit": "ddea246c2aa89f492abf9cc8d4755e92af92d9f0",
    }
    target = baseline["compatibility"]["environment"]["target_pi"]
    assert target["pi_model"] == "Raspberry Pi 5 Model B Rev 1.0"
    assert target["filesystem"]["storage_class"] == "nvme"
    assert target["filesystem"]["filesystem_type"] == "ext4"
    assert baseline["exact_counts"] == {
        "key_evidence_probe_capture_count": 2,
        "legacy_run_envelope_count": 201,
        "process_run_count": 200,
        "recording_count": 200,
        "update_count": 232,
        "workload_capture_count": 0,
    }
    assert [row["role"] for row in baseline["runs"]["raw_reports"]] == [
        "warmup",
        "measured",
        "measured",
        "measured",
    ]
    assert baseline["deferred_metrics"] == {
        "index_latency": "not_available_until_m2",
        "result_finalize_latency": "not_available_until_m2",
    }


def test_storage_report_set_is_reference_only_and_skips_print_array_metrics(tmp_path):
    reports = [_report("warmup", 9.0)] + [
        _report(f"measured-{index}", value)
        for index, value in enumerate((10.0, 12.0, 20.0), start=1)
    ]
    paths = []
    for report in reports:
        report["metrics"]["responsiveness"] = {
            "status": "not_applicable",
            "values": {},
        }
        path = tmp_path / f"{report['run']['run_id']}.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        paths.append(path)

    report_set = build_report_set(
        paths[1:], warmup_paths=paths[:1], host_label="pi5-storage-v1"
    )

    assert report_set["metric_profile"] == CALIBRATION_STORAGE_METRIC_PROFILE
    assert report_set["metrics"] == {}
    assert report_set["noise"]["status"] == "not_applicable"
    assert report_set["synthetic"] == {
        "warmup_injected_count": 0,
        "measured_injected_count": 0,
    }
    validate_report_set(report_set)
    with pytest.raises(ComparisonIncompleteError, match="generic baseline builder"):
        create_baseline_summary(report_set, maturity="candidate")


def test_storage_baseline_preserves_identity_counts_distributions_and_deferred_fields():
    reports = [_report("measured-1", 10.0), _report("measured-2", 12.0), _report("measured-3", 20.0)]
    baseline = create_calibration_storage_baseline(
        _report_set(reports), reports, report_set_sha256="9" * 64
    )

    assert baseline["baseline_id"] == BASELINE_ID
    assert baseline["exact_counts"]["process_run_count"] == 200
    assert baseline["compatibility"]["environment"]["target_pi"]["pi_model"].startswith("Raspberry Pi 5")
    rewrite = baseline["metrics"]["timing"]["calibration_rewrite_latency_ms"]
    assert rewrite["p95_distribution"]["count"] == 3
    assert rewrite["candidate_limit"]["upper_limit"] == 32.0
    assert baseline["deferred_metrics"] == {
        "result_finalize_latency": "not_available_until_m2",
        "index_latency": "not_available_until_m2",
    }


def test_storage_baseline_rejects_count_drift():
    reports = [_report("measured-1", 10.0), _report("measured-2", 12.0), _report("measured-3", 20.0)]
    drifted = copy.deepcopy(reports)
    drifted[1]["metrics"]["persistence"]["values"]["calibration_storage"]["update_count"] = 231
    with pytest.raises(CalibrationStorageBaselineError, match="update_count"):
        create_calibration_storage_baseline(
            _report_set(reports), drifted, report_set_sha256="9" * 64
        )


def test_storage_baseline_freeze_checks_raw_hashes_and_refuses_overwrite(
    tmp_path, monkeypatch
):
    reports = [
        _report("measured-1", 10.0),
        _report("measured-2", 12.0),
        _report("measured-3", 20.0),
    ]
    report_set = _report_set(reports)
    for reference, report in zip(report_set["runs"]["measured"], reports):
        path = tmp_path / f"{report['run']['run_id']}.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        reference["path"] = str(path)
        reference["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    report_set_path = tmp_path / "report_set.json"
    report_set_path.write_text("{}", encoding="utf-8")
    from tools.sil import calibration_storage_baseline as baseline_module

    monkeypatch.setattr(baseline_module, "load_report_set", lambda _path: report_set)
    output = tmp_path / "baseline.json"

    assert freeze_calibration_storage_baseline(report_set_path, output) == output.resolve()
    assert json.loads(output.read_text(encoding="utf-8"))["baseline_id"] == BASELINE_ID
    with pytest.raises(CalibrationStorageBaselineError, match="refusing to overwrite"):
        freeze_calibration_storage_baseline(report_set_path, output)
