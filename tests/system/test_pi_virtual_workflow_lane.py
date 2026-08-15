from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from tools.virtual_workflows.compare import build_report_set, write_report_set
from tools.virtual_workflows.pi_sil import (
    PI_ARTIFACT_MANIFEST_SCHEMA,
    PI_HARDWARE_PROOF_SCHEMA,
    PI_PREFLIGHT_SCHEMA,
    PI_SIL_SCHEMA_VERSION,
    SANDBOX_METHOD,
    PiSilError,
    build_pi_artifact_bundle,
    cleanup_manifest_paths,
    extract_and_validate_pi_artifact_bundle,
    load_and_validate_pi_evidence,
    validate_pi_hardware_proof,
    validate_pi_hardware_trace,
    validate_pi_preflight,
    write_pi_hardware_proof,
)
from tools.virtual_workflows.report import (
    REPORT_SCHEMA_NAME,
    REPORT_SCHEMA_VERSION,
    validate_report_v1,
)
from tools.virtual_workflows.harness import AutomationHarness, AutomationHarnessConfig

pytestmark = pytest.mark.sil_pi_contract


REPO_ROOT = Path(__file__).resolve().parents[2]
PI_SHELL = REPO_ROOT / "scripts" / "pi" / "run_virtual_workflow_sil.sh"
REMOTE_TOOL = REPO_ROOT / "tools" / "run_pi_virtual_workflow.ps1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _preflight(root: Path, *, dirty: bool = False) -> dict:
    return {
        "schema_name": PI_PREFLIGHT_SCHEMA,
        "schema_version": PI_SIL_SCHEMA_VERSION,
        "created_at_utc": "2026-07-23T00:00:00Z",
        "status": "pass",
        "sandbox_method": SANDBOX_METHOD,
        "repo_root": str(root),
        "output_root": str(root / "verification_reports" / "virtual_workflows"),
        "source_commit": "a" * 40,
        "dirty_worktree": dirty,
        "source_tree_sha256": "d" * 64,
        "operating_system": "Linux",
        "architecture": "aarch64",
        "pi_model": "Raspberry Pi 5 Model B Rev 1.0",
        "python_version": "3.13.14",
        "python_executable": "/home/labcraft/LabCraft_printer/venv/bin/python",
        "qt_platform": "offscreen",
        "pyside_version": "6.11.1",
        "qt_version": "6.11.1",
        "filesystem": {
            "filesystem_type": "ext4",
            "storage_class": "sd",
            "mount_source": "/dev/mmcblk0p2",
            "free_bytes": 10_000_000_000,
            "total_bytes": 20_000_000_000,
        },
        "thermal": {"temperature_c": 45.0, "throttled_flags": "throttled=0x0"},
        "requirements": {
            "commands": {"bwrap": "/usr/bin/bwrap"},
            "psutil_version": "7.0.0",
            "private_dev_present": True,
            "host_serial_visible": False,
        },
    }


def _report(run_id: str, scenario_root: Path) -> dict:
    report = {
        "schema_name": REPORT_SCHEMA_NAME,
        "schema_version": REPORT_SCHEMA_VERSION,
        "run": {
            "run_id": run_id,
            "scenario_name": "virtual_print_array",
            "scenario_version": "1",
            "run_mode": "offscreen_pi_sil",
            "timing_policy": "simulated_command_durations_x1",
            "warmup_runs": 0,
            "measured_runs": 1,
            "started_at_utc": "2026-07-23T00:00:00Z",
            "ended_at_utc": "2026-07-23T00:00:10Z",
            "duration_ms": 10_000.0,
        },
        "source": {
            "git_commit": "a" * 40,
            "git_short_commit": "a" * 12,
            "dirty_worktree": False,
            "git_error": None,
            "source_tree": {"sha256": "d" * 64},
        },
        "environment": {
            "operating_system": "Linux",
            "os_release": "6.12",
            "architecture": "aarch64",
            "cpu_identifier": "Cortex-A76",
            "python_version": "3.13.14",
            "python_implementation": "CPython",
            "python_executable": "venv/bin/python",
            "qt": {
                "binding": "real",
                "pyside_version": "6.11.1",
                "qt_version": "6.11.1",
                "module_path": "/repo/venv/lib/PySide6/__init__.py",
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
            "scenario_root": str(scenario_root),
            "root_containment_valid": True,
            "pi_sil": {
                "sandbox_method": SANDBOX_METHOD,
                "private_dev": True,
                "root_read_only": True,
                "network_unshared": True,
                "forbidden_access_attempt_count": 0,
                "proof_sha256": "b" * 64,
                "trace_sha256": "c" * 64,
            },
        },
        "workload": {
            "workload_id": "virtual_print_array_96_v1",
            "fixture_schema_version": 1,
            "plate_name": "shallow-384_well_plate",
            "plate_rows": 16,
            "plate_columns": 24,
            "well_ids": ["A1", "A2"],
            "stock_id": "Virtual Stock_1.00_x",
            "target_dispenses_per_well": 1,
            "expected_completion_count": 96,
            "speed_multiplier": 1.0,
            "timeout_seconds": 600.0,
        },
        "metrics": {
            "responsiveness": {
                "status": "measured",
                "values": {
                    "scheduling_lateness_ms": {"p95": 10, "p99": 20},
                    "event_loop_gap_ms": {"maximum": 50},
                    "phase_timings": {
                        "duration_by_name_ms": {
                            "controller.well_completion": {"p95": 2},
                            "ui.well_plate_update": {"p95": 2},
                            "persistence.write_progress": {"p95": 2},
                            "persistence.complete_intent": {"p95": 2},
                        }
                    },
                    "injected_stall_assessment": {"requested": False},
                },
            },
            "workflow": {"status": "measured", "values": {}},
            "queue": {"status": "measured", "values": {}},
            "persistence": {"status": "measured", "values": {}},
            "resources": {"status": "measured", "values": {}},
        },
        "artifacts": {},
        "classification": {
            "status": "pass",
            "threshold_maturity": "informational",
            "reasons": ["synthetic Pi report"],
        },
        "limitations": [],
    }
    validate_report_v1(report)
    return report


def _write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _proof(preflight_path: Path, trace_path: Path, report_path: Path) -> dict:
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    return {
        "schema_name": PI_HARDWARE_PROOF_SCHEMA,
        "schema_version": PI_SIL_SCHEMA_VERSION,
        "created_at_utc": "2026-07-23T00:00:00Z",
        "status": "pass",
        "sandbox_method": SANDBOX_METHOD,
        "preflight_path": str(preflight_path),
        "preflight_sha256": _sha256(preflight_path),
        "trace_path": str(trace_path),
        "trace_sha256": _sha256(trace_path),
        "audit_report_path": str(report_path),
        "audit_report_sha256": _sha256(report_path),
        "source_commit": preflight["source_commit"],
        "source_tree_sha256": preflight["source_tree_sha256"],
        "qt_platform": preflight["qt_platform"],
        "pi_model": preflight["pi_model"],
        "private_dev": True,
        "root_read_only": True,
        "network_unshared": True,
        "forbidden_patterns": [],
        "forbidden_matches": [],
    }


def test_pi_preflight_and_proof_validation_are_fail_closed(tmp_path):
    preflight = _preflight(tmp_path)
    validate_pi_preflight(preflight)
    proof = {
        "schema_name": PI_HARDWARE_PROOF_SCHEMA,
        "schema_version": PI_SIL_SCHEMA_VERSION,
        "status": "pass",
        "sandbox_method": SANDBOX_METHOD,
        "private_dev": True,
        "root_read_only": True,
        "network_unshared": True,
        "forbidden_matches": [],
    }
    validate_pi_hardware_proof(proof)

    unsafe = copy.deepcopy(proof)
    unsafe["private_dev"] = False
    with pytest.raises(PiSilError, match="sandbox protections"):
        validate_pi_hardware_proof(unsafe)

    wrong_platform = copy.deepcopy(preflight)
    wrong_platform["architecture"] = "x86_64"
    with pytest.raises(PiSilError, match="architecture"):
        validate_pi_preflight(wrong_platform)


def test_hardware_trace_accepts_private_dev_and_rejects_physical_devices(tmp_path):
    preflight_path = _write_json(tmp_path / "preflight.json", _preflight(tmp_path))
    scenario_root = tmp_path / "audit" / "scenario-root"
    scenario_root.mkdir(parents=True)
    report_path = _write_json(
        tmp_path / "audit" / "report.json",
        _report("audit", scenario_root),
    )
    trace_path = tmp_path / "trace.txt"
    trace_path.write_text(
        'openat(AT_FDCWD, "/dev/null", O_RDWR) = 3</dev/null>\n',
        encoding="utf-8",
    )

    proof = validate_pi_hardware_trace(
        preflight_path, trace_path, report_path
    )
    assert proof.status == "pass"
    assert proof.forbidden_matches == []

    mislabeled_report = _report("audit-mislabeled", scenario_root)
    mislabeled_report["run"]["run_mode"] = "offscreen_windows_sil"
    mislabeled_path = _write_json(
        tmp_path / "audit" / "mislabeled-report.json", mislabeled_report
    )
    with pytest.raises(PiSilError, match="not a Pi SIL run"):
        validate_pi_hardware_trace(
            preflight_path, trace_path, mislabeled_path
        )

    trace_path.write_text(
        'openat(AT_FDCWD, "/dev/ttyAMA0", O_RDWR) = 7</dev/ttyAMA0>\n',
        encoding="utf-8",
    )
    with pytest.raises(PiSilError, match="serial_uart"):
        validate_pi_hardware_trace(preflight_path, trace_path, report_path)


def test_pi_evidence_requires_exact_preflight_hash_and_qt_platform(tmp_path):
    preflight_path = _write_json(tmp_path / "preflight.json", _preflight(tmp_path))
    trace_path = tmp_path / "trace.txt"
    trace_path.write_text("clean\n", encoding="utf-8")
    report_path = _write_json(
        tmp_path / "report.json",
        _report("audit", tmp_path / "scenario-root"),
    )
    proof_path = _write_json(
        tmp_path / "proof.json",
        _proof(preflight_path, trace_path, report_path),
    )

    preflight, proof = load_and_validate_pi_evidence(
        preflight_path, proof_path, expected_qt_platform="offscreen"
    )
    assert preflight["pi_model"].startswith("Raspberry Pi 5")
    assert proof["sandbox_method"] == SANDBOX_METHOD

    preflight_path.write_text(
        preflight_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    with pytest.raises(PiSilError, match="does not match"):
        load_and_validate_pi_evidence(
            preflight_path, proof_path, expected_qt_platform="offscreen"
        )


def test_composed_harness_binds_validated_pi_identity_before_launch(
    tmp_path, monkeypatch
):
    preflight_payload = _preflight(tmp_path)
    preflight_path = _write_json(tmp_path / "preflight.json", preflight_payload)
    trace_path = tmp_path / "trace.txt"
    trace_path.write_text("clean\n", encoding="utf-8")
    audit_path = _write_json(
        tmp_path / "audit-report.json",
        _report("audit", tmp_path / "scenario-root"),
    )
    proof_path = _write_json(
        tmp_path / "proof.json",
        _proof(preflight_path, trace_path, audit_path),
    )
    from tools.virtual_workflows import report as report_module

    monkeypatch.setattr(
        report_module,
        "collect_environment_identity",
        lambda _repo_root: {
            "source": {"git_commit": preflight_payload["source_commit"]},
            "environment": {
                "operating_system": preflight_payload["operating_system"],
                "architecture": preflight_payload["architecture"],
                "python_version": preflight_payload["python_version"],
                "python_executable": preflight_payload["python_executable"],
                "qt": {"platform": preflight_payload["qt_platform"]},
            },
        },
    )
    harness = AutomationHarness(
        AutomationHarnessConfig(
            scenario_id="calibration_storage_legacy_baseline_8x25_v1",
            workload_id="calibration_storage_legacy_baseline_8x25_v1",
            output_root=tmp_path / "reports",
            pi_preflight_path=preflight_path,
            pi_hardware_proof_path=proof_path,
        )
    )

    harness._bind_pi_report_identity()

    assert harness.report_identity["target_pi"]["pi_model"].startswith(
        "Raspberry Pi 5"
    )
    assert harness.report_identity["target_pi"]["filesystem"]["storage_class"] == "sd"
    assert harness.report_identity["pi_sil"]["private_dev"] is True


def test_artifact_bundle_round_trip_preserves_relative_reports_and_hashes(
    tmp_path, monkeypatch
):
    source_repo = tmp_path / "source"
    destination_repo = tmp_path / "destination"
    output = source_repo / "verification_reports" / "virtual_workflows"
    safety = output / "pi-safety-test"
    raw = output / "virtual_print_array_96_v1" / "raw"
    set_dir = output / "virtual_print_array_96_v1" / "set"
    scenario_root = raw / "scenario-root"
    scenario_root.mkdir(parents=True)
    (scenario_root / "progress.json").write_text("{}", encoding="utf-8")
    (raw / "summary.txt").write_text("passed\n", encoding="utf-8")
    (raw / "events.jsonl").write_text("{}\n", encoding="utf-8")
    (raw / "screenshots").mkdir()
    (raw / "screenshots" / "completed.png").write_bytes(b"png")

    monkeypatch.chdir(source_repo)
    report_path = _write_json(raw / "report.json", _report("measured", scenario_root))
    report_set = build_report_set(
        [report_path], host_label="pi5-sil-primary-v1"
    )
    report_set_path = write_report_set(set_dir / "report_set.json", report_set)
    preflight_path = _write_json(safety / "preflight.json", _preflight(source_repo))
    trace_path = safety / "hardware_access_trace.txt"
    trace_path.write_text("clean\n", encoding="utf-8")
    proof_path = _write_json(
        safety / "hardware_proof.json",
        _proof(preflight_path, trace_path, report_path),
    )
    archive = output / "bundles" / "pi.zip"
    bundle_path, sidecar = build_pi_artifact_bundle(
        source_repo,
        report_set_path,
        proof_path,
        trace_path,
        archive,
    )
    assert bundle_path.is_file()
    assert json.loads(sidecar.read_text(encoding="utf-8"))["schema_name"] == (
        PI_ARTIFACT_MANIFEST_SCHEMA
    )

    copied_archive = tmp_path / "retrieved.zip"
    shutil.copy2(bundle_path, copied_archive)
    destination_repo.mkdir()
    monkeypatch.chdir(destination_repo)
    manifest = extract_and_validate_pi_artifact_bundle(
        copied_archive, destination_repo
    )
    assert (destination_repo / manifest["report_set_path"]).is_file()
    assert (
        destination_repo
        / "verification_reports"
        / "virtual_workflows"
        / "virtual_print_array_96_v1"
        / "raw"
        / "screenshots"
        / "completed.png"
    ).read_bytes() == b"png"

    with pytest.raises(PiSilError, match="overwrite"):
        extract_and_validate_pi_artifact_bundle(copied_archive, destination_repo)


def test_artifact_extraction_rejects_traversal(tmp_path):
    archive_path = tmp_path / "unsafe.zip"
    manifest = {
        "schema_name": PI_ARTIFACT_MANIFEST_SCHEMA,
        "schema_version": PI_SIL_SCHEMA_VERSION,
        "report_set_path": "../report_set.json",
        "proof_path": "../proof.json",
        "trace_path": "../trace.txt",
        "files": [
            {
                "path": "../outside.txt",
                "size_bytes": 1,
                "sha256": hashlib.sha256(b"x").hexdigest(),
            }
        ],
        "cleanup_roots": [],
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.txt", b"x")
        archive.writestr("pi_sil_artifact_manifest.json", json.dumps(manifest))

    with pytest.raises(PiSilError, match="unsafe"):
        extract_and_validate_pi_artifact_bundle(
            archive_path, tmp_path / "destination"
        )


def test_cleanup_removes_only_manifest_roots_beneath_output(tmp_path):
    repo = tmp_path / "repo"
    output = repo / "verification_reports" / "virtual_workflows"
    target = output / "virtual_print_array_96_v1" / "run"
    target.mkdir(parents=True)
    (target / "report.json").write_text("{}", encoding="utf-8")
    manifest_path = _write_json(
        output / "manifest.json",
        {
            "schema_name": PI_ARTIFACT_MANIFEST_SCHEMA,
            "schema_version": PI_SIL_SCHEMA_VERSION,
            "cleanup_roots": [
                target.relative_to(repo).as_posix(),
            ],
        },
    )

    assert cleanup_manifest_paths(manifest_path, repo, output) == [target]
    assert not target.exists()

    unsafe_manifest = _write_json(
        output / "unsafe.json",
        {
            "schema_name": PI_ARTIFACT_MANIFEST_SCHEMA,
            "schema_version": PI_SIL_SCHEMA_VERSION,
            "cleanup_roots": ["../outside"],
        },
    )
    with pytest.raises(PiSilError, match="escaped"):
        cleanup_manifest_paths(unsafe_manifest, repo, output)


def test_pi_shell_is_private_device_only_and_never_launches_production_app():
    source = PI_SHELL.read_text(encoding="utf-8")
    python_source = (
        REPO_ROOT / "tools" / "virtual_workflows" / "pi_sil.py"
    ).read_text(encoding="utf-8")

    for required in (
        "--unshare-all",
        "--ro-bind / /",
        "--dev /dev",
        "--tmpfs /tmp",
        "tools/run_virtual_workflow.py",
        "--target-pi",
        "validate-trace",
        "replay-suite",
        "--aggregate",
    ):
        assert required in source
    assert "FreeRTOS-interface/App.py" not in source
    assert "--unsafe" not in source
    for forbidden in (
        "Machine_FreeRTOS",
        "serial.Serial",
        "RefuelCamera(",
        "DropletCamera(",
        "GPIO.",
        "dfu-util",
    ):
        assert forbidden not in python_source


def test_remote_wrapper_dry_run_builds_preflight_proof_and_collection_commands():
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    result = subprocess.run(
        [
            powershell,
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REMOTE_TOOL),
            "-PiHost",
            "pi-test",
            "-Scenario",
            "virtual_print_array_384x10_v1",
            "-WarmupRuns",
            "0",
            "-MeasuredRuns",
            "1",
            "-DryRun",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "run_virtual_workflow_sil.sh" in result.stdout
    assert "'preflight'" in result.stdout
    assert "'prove'" in result.stdout
    assert "'collect'" in result.stdout
    assert "'virtual_print_array_384x10_v1'" in result.stdout
    assert "'--emit-report-set'" in result.stdout
    assert "Dry run complete" in result.stdout


def test_remote_wrapper_uses_native_exit_code_when_ssh_writes_stderr(
    tmp_path,
):
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    (fake_bin / "ssh.cmd").write_text(
        "@echo off\r\necho benign-native-stderr 1>&2\r\nexit /b 0\r\n",
        encoding="utf-8",
    )
    (fake_bin / "scp.cmd").write_text("@exit /b 0\r\n", encoding="utf-8")
    environment = dict(os.environ)
    environment["PATH"] = str(fake_bin) + os.pathsep + environment.get("PATH", "")
    result = subprocess.run(
        [
            powershell,
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REMOTE_TOOL),
            "-PiHost",
            "pi-test",
            "-PreflightOnly",
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "benign-native-stderr" in result.stdout
    assert "Pi SIL preflight completed" in result.stdout


def test_remote_wrapper_allows_calibration_storage_pi_qualification_contract():
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    result = subprocess.run(
        [
            powershell,
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REMOTE_TOOL),
            "-PiHost",
            "pi-test",
            "-Scenario",
            "calibration_storage_legacy_baseline_8x25_v1",
            "-HostLabel",
            "pi5-calibration-storage-legacy-v1",
            "-WarmupRuns",
            "1",
            "-MeasuredRuns",
            "3",
            "-SpeedMultiplier",
            "1000",
            "-TimeoutSeconds",
            "1800",
            "-DryRun",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "'calibration_storage_legacy_baseline_8x25_v1'" in result.stdout
    assert "--warmup-runs" in result.stdout
    assert "--measured-runs" in result.stdout
    assert "--speed-multiplier" in result.stdout
    assert "--timeout-seconds" in result.stdout
    assert "'--emit-report-set'" in result.stdout
    assert "Dry run complete" in result.stdout


def test_remote_wrapper_allows_calibration_storage_shadow_pi_qualification_contract(
    tmp_path,
):
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    identity = tmp_path / "pi-sil-test-identity"
    identity.write_text("test-only-placeholder", encoding="utf-8")
    result = subprocess.run(
        [
            powershell,
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REMOTE_TOOL),
            "-PiHost",
            "pi-test",
            "-SshIdentityFile",
            str(identity),
            "-Scenario",
            "calibration_storage_shadow_8x25_v1",
            "-HostLabel",
            "pi5-calibration-storage-shadow-v1",
            "-WarmupRuns",
            "1",
            "-MeasuredRuns",
            "3",
            "-SpeedMultiplier",
            "1000",
            "-TimeoutSeconds",
            "1800",
            "-DryRun",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "'calibration_storage_shadow_8x25_v1'" in result.stdout
    assert "'--emit-report-set'" in result.stdout
    assert str(identity) in result.stdout
    assert "BatchMode=yes" in result.stdout
    assert "Dry run complete" in result.stdout


def test_remote_wrapper_allows_calibration_storage_authoritative_pi_qualification_contract(
    tmp_path,
):
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    identity = tmp_path / "pi-sil-test-identity"
    identity.write_text("test-only-placeholder", encoding="utf-8")
    result = subprocess.run(
        [
            powershell,
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REMOTE_TOOL),
            "-PiHost",
            "pi-test",
            "-SshIdentityFile",
            str(identity),
            "-Scenario",
            "calibration_storage_authoritative_8x25_v1",
            "-HostLabel",
            "pi5-calibration-storage-authoritative-v1",
            "-WarmupRuns",
            "1",
            "-MeasuredRuns",
            "3",
            "-SpeedMultiplier",
            "1000",
            "-TimeoutSeconds",
            "1800",
            "-DryRun",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "'calibration_storage_authoritative_8x25_v1'" in result.stdout
    assert "'--emit-report-set'" in result.stdout
    assert str(identity) in result.stdout
    assert "BatchMode=yes" in result.stdout
    assert "Dry run complete" in result.stdout


def test_remote_wrapper_allows_calibration_storage_primary_reader_pi_qualification_contract(
    tmp_path,
):
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    identity = tmp_path / "pi-sil-test-identity"
    identity.write_text("test-only-placeholder", encoding="utf-8")
    result = subprocess.run(
        [
            powershell, "-ExecutionPolicy", "Bypass", "-File", str(REMOTE_TOOL),
            "-PiHost", "pi-test", "-SshIdentityFile", str(identity),
            "-Scenario", "calibration_storage_primary_reader_8x25_v1",
            "-HostLabel", "pi5-calibration-storage-primary-reader-v1",
            "-WarmupRuns", "1", "-MeasuredRuns", "3",
            "-SpeedMultiplier", "1000", "-TimeoutSeconds", "1800", "-DryRun",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "'calibration_storage_primary_reader_8x25_v1'" in result.stdout
    assert "'--emit-report-set'" in result.stdout
    assert str(identity) in result.stdout
    assert "BatchMode=yes" in result.stdout
    assert "Dry run complete" in result.stdout


def test_remote_wrapper_allows_calibration_storage_secondary_reader_pi_qualification_contract(
    tmp_path,
):
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    identity = tmp_path / "pi-sil-test-identity"
    identity.write_text("test-only-placeholder", encoding="utf-8")
    result = subprocess.run(
        [
            powershell, "-ExecutionPolicy", "Bypass", "-File", str(REMOTE_TOOL),
            "-PiHost", "pi-test", "-SshIdentityFile", str(identity),
            "-Scenario", "calibration_storage_secondary_reader_8x25_v1",
            "-HostLabel", "pi5-calibration-storage-secondary-reader-v1",
            "-WarmupRuns", "0", "-MeasuredRuns", "1",
            "-SpeedMultiplier", "1000", "-TimeoutSeconds", "3600", "-DryRun",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "'calibration_storage_secondary_reader_8x25_v1'" in result.stdout
    assert "'--emit-report-set'" in result.stdout
    assert "--timeout-seconds" in result.stdout
    assert "3600" in result.stdout
    assert str(identity) in result.stdout
    assert "BatchMode=yes" in result.stdout
    assert "Dry run complete" in result.stdout


@pytest.mark.parametrize(
    ("suite_id", "replay_expected"),
    [("pi_primary", True), ("pi_stress", False)],
)
def test_remote_wrapper_suite_dry_run_is_explicit_and_retains_evidence(
    suite_id, replay_expected
):
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    command = [
        powershell,
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(REMOTE_TOOL),
        "-PiHost",
        "pi-test",
        "-Suite",
        suite_id,
        "-Seed",
        "1",
        "-SpeedMultiplier",
        "100",
        "-DryRun",
    ]
    if replay_expected:
        command.append("-ReplaySuite")
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert f"Suite: {suite_id}" in result.stdout
    assert "'--suite'" in result.stdout
    assert f"'{suite_id}'" in result.stdout
    assert "'--aggregate'" in result.stdout
    assert "pi-suite-" in result.stdout
    assert "'--timeout-seconds'" not in result.stdout
    assert "'cleanup'" not in result.stdout
    assert ("'replay'" in result.stdout) is replay_expected
    assert "no remote operation, artifact, or cleanup occurred" in result.stdout


@pytest.mark.parametrize(
    "conflict",
    [
        ["-Scenario", "virtual_print_array_96_v1"],
        ["-WarmupRuns", "1"],
        ["-HostLabel", "pi-test-label"],
    ],
)
def test_remote_wrapper_suite_mode_rejects_legacy_scenario_controls(conflict):
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    result = subprocess.run(
        [
            powershell,
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REMOTE_TOOL),
            "-PiHost",
            "pi-test",
            "-Suite",
            "pi_primary",
            "-DryRun",
            *conflict,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
