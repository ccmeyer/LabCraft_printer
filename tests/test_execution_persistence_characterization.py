from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from tools import characterize_execution_persistence as characterization
from tools.virtual_workflows.report import (
    REPORT_SCHEMA_NAME,
    REPORT_SCHEMA_VERSION,
    ReportValidationError,
    collect_environment_identity,
    validate_report_v1,
    write_report_atomic,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _small_workload() -> characterization.WorkloadSpec:
    return characterization.WorkloadSpec(
        plate_name="shallow-384_well_plate",
        plate_rows=16,
        plate_columns=24,
        well_ids=("A1", "A2"),
        stock_count=1,
        workload_id="execution_persistence_test_v1",
    )


def _valid_report() -> dict:
    metric = {"status": "not_available", "values": {}}
    return {
        "schema_name": REPORT_SCHEMA_NAME,
        "schema_version": REPORT_SCHEMA_VERSION,
        "run": {
            "run_id": "test-run",
            "scenario_name": "test",
            "scenario_version": "1",
            "run_mode": "host_characterization",
            "timing_policy": "unpaced",
            "warmup_runs": 0,
            "measured_runs": 1,
            "started_at_utc": "2026-07-23T12:00:00Z",
            "ended_at_utc": "2026-07-23T12:00:01Z",
            "duration_ms": 1000.0,
        },
        "source": {
            "git_commit": None,
            "git_short_commit": None,
            "dirty_worktree": None,
            "git_error": "not a checkout",
        },
        "environment": {"python_version": "test"},
        "safety": {
            "simulation": True,
            "hardware_access_allowed": False,
            "hardware_interfaces": {
                "serial": False,
                "gpio": False,
                "camera": False,
                "balance": False,
                "mcu": False,
                "firmware_update": False,
            },
        },
        "workload": {"workload_id": "test"},
        "metrics": {
            "responsiveness": dict(metric),
            "workflow": dict(metric),
            "queue": {"status": "not_applicable", "values": {}},
            "persistence": dict(metric),
            "resources": dict(metric),
        },
        "artifacts": {"report_json": "report.json"},
        "classification": {
            "status": "pass",
            "threshold_maturity": "informational",
            "reasons": [],
        },
        "limitations": [],
    }


def test_report_schema_accepts_v1_and_atomic_writer_round_trips(tmp_path):
    report = _valid_report()

    validate_report_v1(report)
    destination = write_report_atomic(tmp_path / "report.json", report)

    assert json.loads(destination.read_text(encoding="utf-8")) == report
    assert not list(tmp_path.glob(".report.json.*.tmp"))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda report: report.pop("safety"), "missing top-level"),
        (lambda report: report.update(extra=True), "unknown top-level"),
        (
            lambda report: report["metrics"].pop("responsiveness"),
            "invalid metric groups",
        ),
        (
            lambda report: report["metrics"]["queue"].update(status="ignored"),
            "metrics.queue.status",
        ),
        (
            lambda report: report["safety"].update(hardware_access_allowed=True),
            "hardware_access_allowed",
        ),
        (
            lambda report: report["classification"].update(
                threshold_maturity="unknown"
            ),
            "threshold_maturity",
        ),
    ],
)
def test_report_schema_rejects_contract_violations(mutation, message):
    report = _valid_report()
    mutation(report)

    with pytest.raises(ReportValidationError, match=message):
        validate_report_v1(report)


def test_environment_identity_records_git_python_and_qt_mode():
    identity = collect_environment_identity(REPO_ROOT)

    assert set(identity) == {"source", "environment"}
    assert identity["source"]["git_commit"]
    assert identity["environment"]["python_version"]
    assert identity["environment"]["qt"]["binding"] in {
        "real",
        "stub",
        "missing",
    }


def test_baseline_workload_is_exact_and_serpentine():
    workload = characterization.BASELINE_WORKLOAD

    assert workload.plate_name == "shallow-384_well_plate"
    assert (workload.plate_rows, workload.plate_columns) == (16, 24)
    assert workload.stock_count == 4
    assert workload.target_dispenses == 1
    assert workload.completion_count == 384
    assert workload.well_ids[:3] == ("A1", "A2", "A3")
    assert workload.well_ids[23:27] == ("A24", "B24", "B23", "B22")
    assert workload.well_ids[-3:] == ("D3", "D2", "D1")


def test_characterization_source_has_no_production_hardware_imports():
    source_path = REPO_ROOT / "tools" / "characterize_execution_persistence.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots.isdisjoint(
        {
            "App",
            "Controller",
            "Machine_FreeRTOS",
            "serial",
            "RPi",
            "CalibrationClasses",
            "dfu_update",
            "update_and_restart",
        }
    )


def test_reduced_workload_uses_real_persistence_without_hardware_construction(
    tmp_path,
    monkeypatch,
):
    import CalibrationClasses
    import serial

    def hardware_called(*args, **kwargs):
        raise AssertionError("physical hardware constructor was called")

    monkeypatch.setattr(characterization.Model, "__init__", hardware_called)
    monkeypatch.setattr(CalibrationClasses, "RefuelCameraModel", hardware_called)
    monkeypatch.setattr(CalibrationClasses, "DropletCameraModel", hardware_called)
    monkeypatch.setattr(serial, "Serial", hardware_called)

    result = characterization._execute_workload(
        _small_workload(),
        tmp_path / "experiment",
    )

    assert result["validation"]["checkpoint_state"] == "clean"
    assert result["validation"]["intent_count"] == 2
    assert result["validation"]["authoritative_bundle_valid"] is True
    assert result["validation"]["targets_match_progress"] is True
    assert len(result["samples_ms"]["well_total"]) == 2


def test_characterization_writes_valid_informational_report(tmp_path):
    exit_code, report_path = characterization.run_characterization(
        output_root=tmp_path / "reports",
        warmup_runs=0,
        measured_runs=1,
        keep_workload_artifacts="never",
        spec=_small_workload(),
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    validate_report_v1(report)
    assert exit_code == 0
    assert report["classification"]["status"] == "pass"
    assert report["classification"]["threshold_maturity"] == "informational"
    assert report["metrics"]["persistence"]["status"] == "measured"
    assert report["metrics"]["responsiveness"]["status"] == "not_available"
    assert report["metrics"]["queue"]["status"] == "not_applicable"
    assert report["artifacts"]["retained_workloads"] == []
    assert report_path.with_name("summary.txt").is_file()


def test_characterization_failure_writes_report_and_retains_workload(
    tmp_path,
    monkeypatch,
):
    def fail(_spec, experiment_dir):
        experiment_dir.mkdir(parents=True)
        (experiment_dir / "diagnostic.txt").write_text("failure", encoding="utf-8")
        raise characterization.WorkloadInvariantError("injected invariant failure")

    monkeypatch.setattr(characterization, "_execute_workload", fail)

    exit_code, report_path = characterization.run_characterization(
        output_root=tmp_path / "reports",
        warmup_runs=0,
        measured_runs=1,
        keep_workload_artifacts="on-failure",
        spec=_small_workload(),
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    validate_report_v1(report)
    assert exit_code == 2
    assert report["classification"]["status"] == "fail"
    assert "injected invariant failure" in report["classification"]["reasons"][0]
    retained = report["artifacts"]["retained_workloads"]
    assert len(retained) == 1
    assert (report_path.parent / retained[0] / "diagnostic.txt").is_file()
    assert (report_path.parent / "failure_traceback.txt").is_file()


def test_cli_returns_runner_exit_code_and_prints_report(tmp_path, monkeypatch, capsys):
    report_path = tmp_path / "report.json"
    monkeypatch.setattr(
        characterization,
        "run_characterization",
        lambda **kwargs: (2, report_path),
    )

    exit_code = characterization.main(
        ["--output-root", str(tmp_path), "--measured-runs", "1"]
    )

    assert exit_code == 2
    assert capsys.readouterr().out.strip() == str(report_path)


def test_cli_setup_error_returns_three(tmp_path, monkeypatch, capsys):
    def fail(**kwargs):
        raise ValueError("bad setup")

    monkeypatch.setattr(characterization, "run_characterization", fail)

    assert characterization.main(["--output-root", str(tmp_path)]) == 3
    assert "bad setup" in capsys.readouterr().err
