from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools.virtual_workflows.coverage import (
    COVERAGE_SCHEMA_NAME,
    CoverageError,
    CoverageRunConfig,
    build_coverage_evaluation,
    coverage_summary,
    load_coverage_evaluation,
    write_coverage_evaluation,
)
from tools.virtual_workflows.registry import load_capability_manifest
from tools.virtual_workflows.report import (
    METRIC_GROUPS,
    REPORT_SCHEMA_NAME,
    REPORT_SCHEMA_VERSION,
    collect_source_identity,
)
from tools.virtual_workflows.selection import SelectionRequest, resolve_selection
from tools.virtual_workflows.suite_runner import AggregateRunConfig, execute_host_selection
from tools.virtual_workflows.pi_sil import (
    PI_HARDWARE_PROOF_SCHEMA,
    PI_PREFLIGHT_SCHEMA,
    PI_SIL_SCHEMA_VERSION,
    SANDBOX_METHOD,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _rows(section):
    return {row["id"]: row for row in section}


class _EvidenceProcess:
    next_pid = 31000

    def __init__(self, command, *, source, behavior):
        self.command = list(command)
        self.source = copy.deepcopy(source)
        self.behavior = dict(behavior)
        self.pid = _EvidenceProcess.next_pid
        _EvidenceProcess.next_pid += 1
        self.returncode = None
        self._written = False

    def _write_report(self):
        if self._written or self.behavior.get("missing_report"):
            return
        self._written = True
        output_root = Path(self.command[self.command.index("--output-root") + 1])
        registry_id = self.command[self.command.index("--scenario") + 1]
        seed = int(self.command[self.command.index("--seed") + 1])
        manifest = load_capability_manifest()
        scenario = next(row for row in manifest["scenarios"] if row["registry_id"] == registry_id)
        actions = _rows(manifest["policy"]["action_catalog"])
        action_rows = [
            {
                "action_id": action_id,
                "interaction_surface": actions[action_id]["interaction_surface"],
                "status": "pass",
            }
            for action_id in scenario["action_ids"]
        ]
        assertion_rows = [
            {
                "assertion_id": assertion_id,
                "decision": "pass",
                "observable_sources": ["ui", "model"],
            }
            for assertion_id in scenario["assertion_ids"]
        ]
        if self.behavior.get("wrong_surface"):
            target = next(row for row in action_rows if row["interaction_surface"] == "ui")
            target["interaction_surface"] = "model"
        if self.behavior.get("failed_assertion"):
            assertion_rows[0]["decision"] = "fail"
        if self.behavior.get("missing_action"):
            action_rows.pop()
        source = copy.deepcopy(self.source)
        if self.behavior.get("legacy_source"):
            source.pop("source_tree", None)
        if self.behavior.get("stale_source"):
            source["source_tree"]["sha256"] = "f" * 64
        report_dir = output_root / registry_id / "synthetic-coverage"
        report_dir.mkdir(parents=True, exist_ok=True)
        now = self.behavior.get("ended_at", "2026-08-07T00:00:01Z")
        classification = self.behavior.get("classification", "pass")
        metrics = {
            name: {"status": "not_applicable", "values": {}}
            for name in METRIC_GROUPS
        }
        metrics["workflow"] = {
            "status": "measured",
            "values": {
                "action_results": action_rows,
                "assertion_results": assertion_rows,
            },
        }
        payload = {
            "schema_name": REPORT_SCHEMA_NAME,
            "schema_version": REPORT_SCHEMA_VERSION,
            "run": {
                "run_id": f"coverage-{registry_id}-{self.behavior.get('token', 'a')}",
                "scenario_name": registry_id,
                "scenario_version": "1",
                "run_mode": (
                    "offscreen_pi_sil"
                    if "--target-pi" in self.command
                    else "offscreen_windows_sil"
                ),
                "timing_policy": "simulated_command_durations_x1000",
                "warmup_runs": 0,
                "measured_runs": 1,
                "started_at_utc": "2026-08-07T00:00:00Z",
                "ended_at_utc": now,
                "duration_ms": 1000.0,
                "seed": seed,
                "replay_command": ["python", "runner.py", "--scenario", registry_id],
            },
            "source": source,
            "environment": {"operating_system": "Windows"},
            "safety": {
                "simulation": True,
                "hardware_access_allowed": False,
                "hardware_interfaces": {"serial": False, "GPIO": False, "camera": False},
                "simulated_port": "SIMULATED",
                "scenario_root": str(report_dir / "session"),
                "report_dir": str(report_dir),
                "root_containment_valid": True,
            },
            "workload": {"workload_id": registry_id},
            "metrics": metrics,
            "artifacts": {},
            "classification": {
                "status": classification,
                "threshold_maturity": "informational",
                "reasons": [] if classification != "fail" else ["synthetic failure"],
            },
            "limitations": ["synthetic coverage evidence"],
        }
        if "--target-pi" in self.command:
            preflight_path = Path(
                self.command[self.command.index("--pi-preflight") + 1]
            )
            proof_path = Path(
                self.command[self.command.index("--pi-hardware-proof") + 1]
            )
            preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
            proof = json.loads(proof_path.read_text(encoding="utf-8"))
            payload["source"]["git_commit"] = preflight["source_commit"]
            payload["environment"] = {
                "operating_system": "Linux",
                "target_pi": {
                    "lane": "raspberry_pi_sil",
                    "pi_model": preflight["pi_model"],
                    "filesystem": {},
                },
            }
            payload["safety"]["pi_sil"] = {
                "sandbox_method": SANDBOX_METHOD,
                "private_dev": True,
                "root_read_only": True,
                "network_unshared": True,
                "forbidden_access_attempt_count": 0,
                "proof_sha256": hashlib.sha256(proof_path.read_bytes()).hexdigest(),
                "trace_sha256": proof["trace_sha256"],
            }
        (report_dir / "report.json").write_text(json.dumps(payload), encoding="utf-8")

    def communicate(self, timeout=None):
        self._write_report()
        self.returncode = 2 if self.behavior.get("classification") == "fail" else 0
        return "synthetic child\n", ""

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


def _aggregate(tmp_path, *, plan=None, behavior=None):
    selected_plan = plan or resolve_selection(
        SelectionRequest(
            kind="capability",
            selector_id="execution.mixed_droplet_stream_lifecycle",
        )
    )
    source = collect_source_identity(REPO_ROOT)
    pi_paths = (None, None)
    if selected_plan["platform"] == "pi_sil":
        pi_paths = _pi_evidence(
            tmp_path / "safety",
            source["git_commit"],
            source["source_tree"]["sha256"],
        )

    def factory(command, **kwargs):
        return _EvidenceProcess(command, source=source, behavior=behavior or {})

    result = execute_host_selection(
        AggregateRunConfig(
            plan=selected_plan,
            output_root=tmp_path,
            speed_multiplier=1000,
            replay_command=("python", "runner.py", "--capability", "mixed"),
            pi_preflight_path=pi_paths[0],
            pi_hardware_proof_path=pi_paths[1],
        ),
        popen_factory=factory,
    )
    return result.aggregate_path


def _pi_evidence(root, source_commit, source_tree_sha256):
    root.mkdir(parents=True, exist_ok=True)
    trace = root / "trace.txt"
    audit = root / "audit.json"
    trace.write_text("private trace\n", encoding="utf-8")
    audit.write_text("{}\n", encoding="utf-8")
    preflight_path = root / "preflight.json"
    preflight = {
        "schema_name": PI_PREFLIGHT_SCHEMA,
        "schema_version": PI_SIL_SCHEMA_VERSION,
        "created_at_utc": "2026-08-07T00:00:00Z",
        "status": "pass",
        "sandbox_method": SANDBOX_METHOD,
        "repo_root": str(REPO_ROOT),
        "output_root": str(root.parent),
        "source_commit": source_commit,
        "dirty_worktree": True,
        "source_tree_sha256": source_tree_sha256,
        "operating_system": "Linux",
        "architecture": "aarch64",
        "pi_model": "Raspberry Pi 5 Model B Rev 1.0",
        "python_version": "3.13.0",
        "python_executable": "/repo/venv/bin/python",
        "qt_platform": "offscreen",
        "pyside_version": "6.7.1",
        "qt_version": "6.7.1",
        "filesystem": {
            "filesystem_type": "ext4",
            "storage_class": "nvme",
            "mount_source": "/dev/nvme0n1p2",
            "free_bytes": 10_000_000_000,
            "total_bytes": 20_000_000_000,
        },
        "thermal": {"temperature_c": 45.0, "throttled_flags": None},
        "requirements": {
            "commands": {"bwrap": "/usr/bin/bwrap"},
            "psutil_version": "7.0.0",
            "private_dev_present": True,
            "host_serial_visible": False,
        },
    }
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")
    proof_path = root / "proof.json"
    proof = {
        "schema_name": PI_HARDWARE_PROOF_SCHEMA,
        "schema_version": PI_SIL_SCHEMA_VERSION,
        "created_at_utc": "2026-08-07T00:00:01Z",
        "status": "pass",
        "sandbox_method": SANDBOX_METHOD,
        "preflight_path": str(preflight_path),
        "preflight_sha256": hashlib.sha256(preflight_path.read_bytes()).hexdigest(),
        "trace_path": str(trace),
        "trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
        "audit_report_path": str(audit),
        "audit_report_sha256": hashlib.sha256(audit.read_bytes()).hexdigest(),
        "source_commit": source_commit,
        "source_tree_sha256": source_tree_sha256,
        "qt_platform": "offscreen",
        "pi_model": preflight["pi_model"],
        "private_dev": True,
        "root_read_only": True,
        "network_unshared": True,
        "forbidden_patterns": [],
        "forbidden_matches": [],
    }
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    return preflight_path, proof_path


def _evaluation(tmp_path, paths, *, evaluated_at=None):
    return build_coverage_evaluation(
        CoverageRunConfig(
            aggregate_paths=tuple(paths),
            output_root=tmp_path / "coverage-output",
            replay_command=("python", "runner.py", "--coverage-from", "aggregate.json"),
        ),
        evaluated_at=evaluated_at or datetime(2026, 8, 7, 1, tzinfo=timezone.utc),
    )


def test_current_complete_capability_passes_with_actions_assertions_and_surfaces(tmp_path):
    payload = _evaluation(tmp_path, [_aggregate(tmp_path / "aggregate")])

    assert payload["schema_name"] == COVERAGE_SCHEMA_NAME
    assert payload["classification"]["counts"]["pass"] == 1
    capability = payload["capabilities"][0]
    assert capability["status"] == "pass"
    assert {"ui", "model", "harness"} <= set(capability["interaction_surfaces"])
    assert {"ui", "model"} <= set(capability["observable_sources"])


@pytest.mark.parametrize(
    ("behavior", "expected"),
    [
        ({"wrong_surface": True}, "fail"),
        ({"failed_assertion": True}, "fail"),
        ({"missing_action": True}, "incomplete"),
        ({"legacy_source": True}, "incomplete"),
        ({"stale_source": True}, "stale"),
    ],
)
def test_fail_incomplete_and_stale_states_are_distinct(tmp_path, behavior, expected):
    path = _aggregate(tmp_path / expected, behavior=behavior)
    payload = _evaluation(tmp_path, [path])
    assert payload["capabilities"][0]["status"] == expected
    assert payload["classification"]["counts"][expected] == 1


def test_missing_and_narrow_suite_portfolio_are_not_coverage(tmp_path):
    mixed_plan = resolve_selection(
        SelectionRequest(kind="capability", selector_id="execution.mixed_droplet_stream_lifecycle")
    )
    standard = resolve_selection(SelectionRequest(kind="suite", selector_id="standard"))
    synthetic = copy.deepcopy(mixed_plan)
    synthetic["scenarios"] = copy.deepcopy(standard["scenarios"])
    synthetic["scenario_count"] = 1
    missing = _evaluation(tmp_path, [_aggregate(tmp_path / "missing", plan=synthetic)])
    assert missing["capabilities"][0]["status"] == "missing"

    narrow = _evaluation(tmp_path, [_aggregate(tmp_path / "narrow", plan=standard)])
    host = next(row for row in narrow["capabilities"] if row["capability_id"] == "sil.hardware_isolation.host")
    assert host["status"] == "incomplete"
    assert "print_array_stress_384x10_v1" in host["required_scenario_ids"]


def test_pi_primary_aggregate_is_ingested_without_claiming_stress_coverage(
    tmp_path,
):
    plan = resolve_selection(
        SelectionRequest(
            kind="suite",
            selector_id="pi_primary",
            platform="pi_sil",
            pi_evidence=("preflight", "hardware_proof"),
        )
    )
    payload = _evaluation(
        tmp_path, [_aggregate(tmp_path / "pi-primary", plan=plan)]
    )

    hardware = next(
        row
        for row in payload["capabilities"]
        if row["capability_id"] == "sil.hardware_isolation.pi"
    )
    assert payload["scope"]["platforms"] == ["pi_sil"]
    assert hardware["status"] == "incomplete"
    assert "print_array_stress_384x10_v1" in hardware["required_scenario_ids"]


def test_conflicting_candidates_are_incomplete_and_identical_evidence_deduplicates(tmp_path):
    first = _aggregate(tmp_path / "first", behavior={"token": "first"})
    second = _aggregate(tmp_path / "second", behavior={"token": "second"})
    conflicted = _evaluation(tmp_path, [first, second])
    assert conflicted["capabilities"][0]["status"] == "incomplete"
    assert "conflicting evidence" in conflicted["scenarios"][0]["reasons"][0]

    duplicate = _evaluation(tmp_path, [first, first])
    assert duplicate["capabilities"][0]["status"] == "pass"


def test_age_is_informational_and_writers_hash_inputs_without_overwrite(tmp_path):
    aggregate = _aggregate(tmp_path / "aggregate", behavior={"ended_at": "2026-08-01T00:00:00Z"})
    payload = _evaluation(
        tmp_path,
        [aggregate],
        evaluated_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )
    capability = payload["capabilities"][0]
    assert capability["status"] == "pass"
    assert capability["evidence_age"][0]["threshold_exceeded"] is True
    destination = tmp_path / "written" / "coverage.json"
    write_coverage_evaluation(destination, payload)
    assert load_coverage_evaluation(destination) == payload
    assert "informational age threshold exceeded" in coverage_summary(payload)
    with pytest.raises(CoverageError, match="refusing to overwrite"):
        write_coverage_evaluation(destination, payload)


def test_coverage_module_is_qt_and_application_import_free():
    script = """
import sys
import tools.virtual_workflows.coverage
forbidden = {'App', 'Controller', 'Model', 'View', 'Machine_FreeRTOS', 'PySide6'}
loaded = sorted(forbidden.intersection(sys.modules))
if loaded:
    raise SystemExit(f'unexpected imports: {loaded}')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
