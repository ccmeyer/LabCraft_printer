from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.virtual_workflows.report import (
    METRIC_GROUPS,
    REPORT_SCHEMA_NAME,
    REPORT_SCHEMA_VERSION,
)
from tools.virtual_workflows.pi_sil import (
    PI_HARDWARE_PROOF_SCHEMA,
    PI_PREFLIGHT_SCHEMA,
    PI_SIL_SCHEMA_VERSION,
    SANDBOX_METHOD,
    PI_SUITE_ARTIFACT_MANIFEST_VERSION,
    PiSilError,
    build_pi_suite_artifact_bundle,
    extract_and_validate_pi_artifact_bundle,
    validate_pi_suite_replay_command,
)
from tools.run_virtual_workflow import main
from tools.virtual_workflows.selection import SelectionRequest, resolve_selection
from tools.virtual_workflows.suite_runner import (
    AGGREGATE_SCHEMA_NAME,
    AggregateError,
    AggregateExecutionResult,
    AggregateRunConfig,
    aggregate_summary,
    execute_host_selection,
    execute_selection,
    load_aggregate,
    validate_aggregate,
    write_aggregate_atomic,
)


def _plan(selector_id="standard", *, count=None):
    payload = resolve_selection(
        SelectionRequest(kind="suite", selector_id=selector_id)
    )
    if count is not None:
        payload = copy.deepcopy(payload)
        payload["scenarios"] = payload["scenarios"][:count]
        payload["scenario_count"] = len(payload["scenarios"])
    return payload


def _report_payload(
    report_dir: Path,
    registry_id: str,
    seed: int,
    *,
    classification="pass",
    workload_id=None,
    pi_evidence=None,
):
    preflight, proof, proof_path = pi_evidence or (None, None, None)
    is_pi = preflight is not None
    return {
        "schema_name": REPORT_SCHEMA_NAME,
        "schema_version": REPORT_SCHEMA_VERSION,
        "run": {
            "run_id": f"run-{registry_id}",
            "scenario_name": registry_id,
            "scenario_version": "1",
            "run_mode": "offscreen_pi_sil" if is_pi else "offscreen_windows_sil",
            "timing_policy": "simulated_command_durations_x1000",
            "warmup_runs": 0,
            "measured_runs": 1,
            "started_at_utc": "2026-08-07T00:00:00Z",
            "ended_at_utc": "2026-08-07T00:00:01Z",
            "duration_ms": 1000.0,
            "seed": seed,
            "replay_command": ["python", "runner.py", "--scenario", registry_id],
        },
        "source": {
            "git_commit": preflight["source_commit"] if is_pi else "a" * 40,
            "dirty_worktree": True,
            **(
                {
                    "source_tree": {
                        "sha256": preflight["source_tree_sha256"]
                    }
                }
                if is_pi
                else {}
            ),
        },
        "environment": (
            {
                "operating_system": "Linux",
                "target_pi": {
                    "lane": "raspberry_pi_sil",
                    "pi_model": preflight["pi_model"],
                    "filesystem": {},
                },
            }
            if is_pi
            else {"operating_system": "Windows"}
        ),
        "safety": {
            "simulation": True,
            "hardware_access_allowed": False,
            "hardware_interfaces": {
                "serial": False,
                "GPIO": False,
                "camera": False,
            },
            "simulated_port": "SIMULATED",
            "scenario_root": str(report_dir / "session"),
            "report_dir": str(report_dir),
            "root_containment_valid": True,
            **(
                {
                    "pi_sil": {
                        "sandbox_method": SANDBOX_METHOD,
                        "private_dev": True,
                        "root_read_only": True,
                        "network_unshared": True,
                        "forbidden_access_attempt_count": 0,
                        "proof_sha256": hashlib.sha256(
                            proof_path.read_bytes()
                        ).hexdigest(),
                        "trace_sha256": proof["trace_sha256"],
                    }
                }
                if is_pi
                else {}
            ),
        },
        "workload": {"workload_id": workload_id or registry_id},
        "metrics": {
            name: {"status": "not_applicable", "values": {}}
            for name in METRIC_GROUPS
        },
        "artifacts": {},
        "classification": {
            "status": classification,
            "threshold_maturity": "informational",
            "reasons": [] if classification != "fail" else ["synthetic failure"],
        },
        "limitations": ["synthetic aggregate test report"],
    }


class _FakeProcess:
    next_pid = 5000

    def __init__(self, command, behavior):
        self.command = list(command)
        self.behavior = dict(behavior)
        self.pid = _FakeProcess.next_pid
        _FakeProcess.next_pid += 1
        self.returncode = None
        self.terminated = False
        self.killed = False
        self._wrote = False

    def _write_evidence(self):
        if self._wrote:
            return
        self._wrote = True
        if self.behavior.get("report") == "missing":
            return
        output_root = Path(self.command[self.command.index("--output-root") + 1])
        registry_id = self.command[self.command.index("--scenario") + 1]
        seed = int(self.command[self.command.index("--seed") + 1])
        report_dir = output_root / registry_id / "synthetic-run"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "report.json"
        if self.behavior.get("report") == "invalid":
            report_path.write_text("not-json", encoding="utf-8")
            return
        payload = _report_payload(
            report_dir,
            registry_id,
            seed,
            classification=self.behavior.get("classification", "pass"),
            workload_id=(
                "wrong-workload"
                if self.behavior.get("report") == "mismatch"
                else None
            ),
            pi_evidence=(
                (
                    json.loads(
                        Path(
                            self.command[
                                self.command.index("--pi-preflight") + 1
                            ]
                        ).read_text(encoding="utf-8")
                    ),
                    json.loads(
                        Path(
                            self.command[
                                self.command.index("--pi-hardware-proof") + 1
                            ]
                        ).read_text(encoding="utf-8")
                    ),
                    Path(
                        self.command[
                            self.command.index("--pi-hardware-proof") + 1
                        ]
                    ),
                )
                if "--target-pi" in self.command
                else None
            ),
        )
        if self.behavior.get("pi_mismatch"):
            payload["safety"]["pi_sil"]["trace_sha256"] = "f" * 64
        report_path.write_text(json.dumps(payload), encoding="utf-8")
        if self.behavior.get("report") == "ambiguous":
            duplicate = output_root / "duplicate" / "report.json"
            duplicate.parent.mkdir(parents=True)
            duplicate.write_text(json.dumps(payload), encoding="utf-8")

    def communicate(self, timeout=None):
        if self.behavior.get("timeout") and not self.terminated:
            raise subprocess.TimeoutExpired(self.command, timeout)
        if (
            self.behavior.get("kill_after_terminate")
            and self.terminated
            and not self.killed
        ):
            raise subprocess.TimeoutExpired(self.command, timeout)
        if not self.behavior.get("timeout"):
            self._write_evidence()
        default_code = (
            2 if self.behavior.get("classification") == "fail" else 0
        )
        self.returncode = self.behavior.get(
            "return_code", -9 if self.killed else default_code
        )
        return self.behavior.get("stdout", "child stdout\n"), self.behavior.get(
            "stderr", ""
        )

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def _factory(behaviors):
    remaining = list(behaviors)
    calls = []
    processes = []

    def create(command, **kwargs):
        behavior = remaining.pop(0)
        calls.append((list(command), kwargs))
        if behavior.get("launch_error"):
            raise OSError("synthetic launch error")
        process = _FakeProcess(command, behavior)
        processes.append(process)
        return process

    return create, calls, processes


def _config(tmp_path, plan=None):
    return AggregateRunConfig(
        plan=plan or _plan(),
        output_root=tmp_path,
        speed_multiplier=1000,
        replay_command=("python", "runner.py", "--suite", "standard"),
    )


def _pi_plan():
    return resolve_selection(
        SelectionRequest(
            kind="suite",
            selector_id="pi_primary",
            platform="pi_sil",
            pi_evidence=("preflight", "hardware_proof"),
        )
    )


def _pi_evidence(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    trace = tmp_path / "hardware_access_trace.txt"
    trace.write_text("private device trace\n", encoding="utf-8")
    audit = tmp_path / "audit_report.json"
    audit.write_text("{}\n", encoding="utf-8")
    preflight_path = tmp_path / "preflight.json"
    preflight = {
        "schema_name": PI_PREFLIGHT_SCHEMA,
        "schema_version": PI_SIL_SCHEMA_VERSION,
        "created_at_utc": "2026-08-07T00:00:00Z",
        "status": "pass",
        "sandbox_method": SANDBOX_METHOD,
        "repo_root": str(tmp_path),
        "output_root": str(tmp_path),
        "source_commit": "a" * 40,
        "dirty_worktree": True,
        "source_tree_sha256": "d" * 64,
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
    proof_path = tmp_path / "hardware_proof.json"
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
        "source_commit": preflight["source_commit"],
        "source_tree_sha256": preflight["source_tree_sha256"],
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


def test_aggregate_config_preserves_virtualenv_executable_path(
    tmp_path, monkeypatch
):
    executable = tmp_path / "env" / "bin" / "python"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"python")
    resolved_target = tmp_path / "usr" / "bin" / "python3"
    original_resolve = Path.resolve

    def fake_resolve(path, *args, **kwargs):
        if path == executable:
            return resolved_target
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fake_resolve)
    config = AggregateRunConfig(
        plan=_plan(),
        output_root=tmp_path / "aggregates",
        python_executable=executable,
    )

    assert config.python_executable == Path(os.path.abspath(executable))
    assert config.python_executable != resolved_target


def test_successful_aggregate_retains_fresh_child_evidence_and_hashes(tmp_path):
    factory, calls, processes = _factory([{}])
    result = execute_host_selection(_config(tmp_path), popen_factory=factory)

    assert result.exit_code == 0
    assert result.aggregate["schema_name"] == AGGREGATE_SCHEMA_NAME
    assert result.aggregate["classification"] == {
        "status": "pass",
        "total_count": 1,
        "completed_count": 1,
        "pass_count": 1,
        "warning_count": 0,
        "fail_count": 0,
        "reasons": [],
    }
    child = result.aggregate["children"][0]
    assert child["outcome"] == "pass"
    assert child["process"]["pid"] == processes[0].pid
    assert child["process"]["pid"] != child["process"]["parent_pid"]
    assert child["report"]["classification"] == "pass"
    assert "--scenario" in calls[0][0]
    assert calls[0][1]["cwd"] == Path(__file__).resolve().parents[1]
    loaded = load_aggregate(result.aggregate_path)
    assert loaded == result.aggregate
    assert json.loads(
        (result.aggregate_path.parent / "selection_plan.json").read_text(
            encoding="utf-8"
        )
    )["execution_authorized"] is False
    assert "Replay: python runner.py --suite standard" in result.summary_path.read_text(
        encoding="utf-8"
    )


def test_pi_suite_aggregate_forwards_and_validates_safety_evidence(tmp_path):
    preflight, proof = _pi_evidence(tmp_path / "safety")
    factory, calls, processes = _factory([{}])
    config = AggregateRunConfig(
        plan=_pi_plan(),
        output_root=tmp_path / "aggregates",
        speed_multiplier=100,
        replay_command=("python", "runner.py", "--suite", "pi_primary"),
        pi_preflight_path=preflight,
        pi_hardware_proof_path=proof,
    )

    result = execute_selection(config, popen_factory=factory)

    assert result.exit_code == 0
    assert result.aggregate["run"]["platform"] == "pi_sil"
    assert result.aggregate["run"]["pi_safety"]["private_dev"] is True
    assert result.aggregate["children"][0]["process"]["pid"] == processes[0].pid
    command = calls[0][0]
    assert "--target-pi" in command
    assert command[command.index("--pi-preflight") + 1] == str(preflight)
    assert command[command.index("--pi-hardware-proof") + 1] == str(proof)
    assert load_aggregate(result.aggregate_path) == result.aggregate


def test_pi_suite_aggregate_fails_closed_on_report_safety_mismatch(tmp_path):
    preflight, proof = _pi_evidence(tmp_path / "safety")
    factory, _, _ = _factory([{"pi_mismatch": True}])
    result = execute_selection(
        AggregateRunConfig(
            plan=_pi_plan(),
            output_root=tmp_path / "aggregates",
            pi_preflight_path=preflight,
            pi_hardware_proof_path=proof,
            replay_command=("python", "runner.py", "--suite", "pi_primary"),
        ),
        popen_factory=factory,
    )
    assert result.exit_code == 2
    assert result.aggregate["children"][0]["outcome"] == "identity_mismatch"
    assert "trace_sha256" in result.aggregate["children"][0]["reasons"][0]


def test_pi_suite_aggregate_requires_both_evidence_files(tmp_path):
    with pytest.raises(AggregateError, match="requires preflight and proof"):
        AggregateRunConfig(plan=_pi_plan(), output_root=tmp_path)


def test_pi_suite_bundle_v2_round_trip_and_replay_allowlist(tmp_path):
    repo = tmp_path / "repo"
    output = repo / "verification_reports" / "virtual_workflows" / "pi-sil"
    preflight, proof = _pi_evidence(output / "safety")
    replay = (
        str(Path(sys.executable).resolve()),
        "tools/run_virtual_workflow.py",
        "--suite",
        "pi_primary",
        "--output-root",
        str(output),
        "--seed",
        "1",
        "--speed-multiplier",
        "100",
        "--qt-platform",
        "offscreen",
        "--target-pi",
        "--pi-preflight",
        str(preflight),
        "--pi-hardware-proof",
        str(proof),
    )
    factory, _, _ = _factory([{}])
    result = execute_selection(
        AggregateRunConfig(
            plan=_pi_plan(),
            output_root=output,
            speed_multiplier=100,
            replay_command=replay,
            pi_preflight_path=preflight,
            pi_hardware_proof_path=proof,
        ),
        popen_factory=factory,
    )
    replay_factory, _, _ = _factory([{}])
    replay_result = execute_selection(
        AggregateRunConfig(
            plan=_pi_plan(),
            output_root=output,
            speed_multiplier=100,
            replay_command=replay,
            pi_preflight_path=preflight,
            pi_hardware_proof_path=proof,
        ),
        popen_factory=replay_factory,
    )
    assert validate_pi_suite_replay_command(
        result.aggregate_path, repo, output
    ) == replay

    archive, sidecar = build_pi_suite_artifact_bundle(
        repo,
        [result.aggregate_path, replay_result.aggregate_path],
        proof,
        output / "safety" / "hardware_access_trace.txt",
        output / "bundles" / "suite.zip",
    )
    extracted = extract_and_validate_pi_artifact_bundle(
        archive, tmp_path / "extracted", sidecar
    )

    assert extracted["schema_version"] == PI_SUITE_ARTIFACT_MANIFEST_VERSION
    assert extracted["aggregate_paths"] == [
        result.aggregate_path.relative_to(repo).as_posix(),
        replay_result.aggregate_path.relative_to(repo).as_posix(),
    ]

    wrong_proof = output / "safety" / "wrong_proof.json"
    wrong_payload = json.loads(proof.read_text(encoding="utf-8"))
    wrong_payload["source_tree_sha256"] = "f" * 64
    wrong_proof.write_text(json.dumps(wrong_payload), encoding="utf-8")
    with pytest.raises(PiSilError, match="does not match bundle proof"):
        build_pi_suite_artifact_bundle(
            repo,
            [result.aggregate_path],
            wrong_proof,
            output / "safety" / "hardware_access_trace.txt",
            output / "bundles" / "wrong.zip",
        )

    tampered = copy.deepcopy(result.aggregate)
    tampered["run"]["replay_command"][0] = "sh"
    tampered_path = result.aggregate_path.parent / "tampered.json"
    tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises((PiSilError, AggregateError)):
        validate_pi_suite_replay_command(tampered_path, repo, output)


def test_multi_child_selection_continues_after_failure_and_fails_closed(tmp_path):
    factory, calls, _ = _factory(
        [{}, {"classification": "fail"}, {}]
    )
    result = execute_host_selection(
        _config(tmp_path, _plan("lifecycle", count=3)),
        popen_factory=factory,
    )

    assert len(calls) == 3
    assert [row["outcome"] for row in result.aggregate["children"]] == [
        "pass",
        "fail",
        "pass",
    ]
    assert result.aggregate["classification"]["status"] == "fail"
    assert result.aggregate["classification"]["fail_count"] == 1
    failed = result.aggregate["children"][1]
    assert failed["report"]["classification_reasons"] == [
        "synthetic failure"
    ]
    assert failed["reasons"] == ["report: synthetic failure"]
    assert "report: synthetic failure" in result.aggregate["classification"][
        "reasons"
    ][0]
    assert result.exit_code == 2


def test_warning_child_produces_warning_aggregate_and_zero_exit(tmp_path):
    factory, _, _ = _factory([{"classification": "warning"}])
    result = execute_host_selection(_config(tmp_path), popen_factory=factory)

    assert result.aggregate["classification"]["status"] == "warning"
    assert result.aggregate["classification"]["warning_count"] == 1
    assert result.exit_code == 0


@pytest.mark.parametrize(
    ("behavior", "outcome"),
    [
        ({"report": "missing"}, "missing_report"),
        ({"report": "ambiguous"}, "ambiguous_report"),
        ({"report": "invalid"}, "invalid_report"),
        ({"report": "mismatch"}, "identity_mismatch"),
        ({"classification": "pass", "return_code": 2}, "process_error"),
        ({"return_code": 3, "report": "missing"}, "process_error"),
        ({"launch_error": True}, "process_error"),
    ],
)
def test_child_evidence_and_process_failures_are_classified(
    tmp_path, behavior, outcome
):
    factory, _, _ = _factory([behavior])
    result = execute_host_selection(_config(tmp_path), popen_factory=factory)

    assert result.aggregate["children"][0]["outcome"] == outcome
    assert result.aggregate["classification"]["status"] == "fail"
    assert result.exit_code == 2


def test_timeout_terminates_then_kills_and_retains_logs(tmp_path):
    factory, _, processes = _factory(
        [{"timeout": True, "kill_after_terminate": True}]
    )
    config = AggregateRunConfig(
        plan=_plan(),
        output_root=tmp_path,
        speed_multiplier=1000,
        replay_command=("python", "runner.py", "--suite", "standard"),
        child_timeout_grace_seconds=1,
        termination_grace_seconds=1,
    )
    result = execute_host_selection(config, popen_factory=factory)

    child = result.aggregate["children"][0]
    assert child["outcome"] == "timeout"
    assert child["watchdog_seconds"] == 61.0
    assert child["process"]["timed_out"] is True
    assert child["process"]["terminated"] is True
    assert child["process"]["killed"] is True
    assert processes[0].terminated is True
    assert processes[0].killed is True


def test_hash_tampering_path_escape_and_overwrite_fail_closed(tmp_path):
    factory, _, _ = _factory([{}])
    result = execute_host_selection(_config(tmp_path), popen_factory=factory)

    with pytest.raises(AggregateError, match="refusing to overwrite"):
        write_aggregate_atomic(result.aggregate_path, result.aggregate)

    stdout_ref = result.aggregate["children"][0]["process"]["stdout"]
    stdout_path = result.aggregate_path.parent / stdout_ref["path"]
    stdout_path.write_text("tampered", encoding="utf-8")

    with pytest.raises(AggregateError, match="SHA-256 mismatch"):
        load_aggregate(result.aggregate_path)

    escaped = copy.deepcopy(result.aggregate)
    escaped["children"][0]["process"]["stdout"]["path"] = "../outside.txt"
    with pytest.raises(AggregateError, match="escaped aggregate root"):
        validate_aggregate(
            escaped,
            aggregate_root=result.aggregate_path.parent,
            verify_hashes=False,
        )


def test_summary_is_deterministic_for_same_aggregate(tmp_path):
    factory, _, _ = _factory([{}])
    result = execute_host_selection(_config(tmp_path), popen_factory=factory)

    assert aggregate_summary(result.aggregate) == aggregate_summary(result.aggregate)


def test_suite_runner_module_is_qt_and_application_import_free():
    script = """
import sys
import tools.virtual_workflows.suite_runner
forbidden = {'App', 'Controller', 'Model', 'View', 'Machine_FreeRTOS', 'PySide6'}
loaded = sorted(forbidden.intersection(sys.modules))
if loaded:
    raise SystemExit(f'unexpected imports: {loaded}')
"""
    result = subprocess.run(
        [str(Path(__file__).resolve().parents[1] / "env" / "Scripts" / "python.exe"), "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_cli_executes_suite_with_default_root_and_resolved_plan(
    tmp_path, monkeypatch, capsys
):
    aggregate_path = tmp_path / "aggregate.json"
    aggregate_path.write_text("{}\n", encoding="utf-8")
    summary_path = tmp_path / "summary.txt"
    summary_path.write_text("aggregate summary\n", encoding="utf-8")
    captured = {}

    def fake_execute(config):
        captured["config"] = config
        return AggregateExecutionResult(
            aggregate_path=aggregate_path,
            summary_path=summary_path,
            aggregate={"classification": {"status": "pass"}},
        )

    monkeypatch.setattr(
        "tools.virtual_workflows.suite_runner.execute_selection",
        fake_execute,
    )

    assert main(["--suite", "standard", "--speed-multiplier", "1000"]) == 0

    config = captured["config"]
    assert config.plan["selector"]["kind"] == "suite"
    assert config.plan["selector"]["id"] == "standard"
    assert config.plan["scenarios"][0]["registry_id"] == (
        "virtual_print_array_24_v1"
    )
    assert config.output_root == (
        Path(__file__).resolve().parents[1]
        / "verification_reports"
        / "suites"
    )
    assert config.speed_multiplier == 1000
    assert config.replay_command[:4] == (
        r".\env\Scripts\python.exe",
        r"tools\run_virtual_workflow.py",
        "--suite",
        "standard",
    )
    output = capsys.readouterr().out
    assert "aggregate summary" in output
    assert f"Aggregate: {aggregate_path}" in output
    assert "Aggregate SHA-256:" in output


def test_cli_executes_only_named_pi_suite_with_exact_linux_replay(
    tmp_path, monkeypatch
):
    preflight, proof = _pi_evidence(tmp_path / "safety")
    aggregate_path = tmp_path / "aggregate.json"
    aggregate_path.write_text("{}\n", encoding="utf-8")
    summary_path = tmp_path / "summary.txt"
    summary_path.write_text("pi aggregate\n", encoding="utf-8")
    captured = {}

    def fake_execute(config):
        captured["config"] = config
        return AggregateExecutionResult(
            aggregate_path=aggregate_path,
            summary_path=summary_path,
            aggregate={"classification": {"status": "pass"}},
        )

    monkeypatch.setattr(
        "tools.virtual_workflows.suite_runner.execute_selection", fake_execute
    )
    venv_python = tmp_path / "env" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_bytes(b"python")
    monkeypatch.setattr(sys, "executable", str(venv_python))
    assert main(
        [
            "--suite",
            "pi_primary",
            "--target-pi",
            "--pi-preflight",
            str(preflight),
            "--pi-hardware-proof",
            str(proof),
            "--speed-multiplier",
            "100",
        ]
    ) == 0

    config = captured["config"]
    assert config.plan["platform"] == "pi_sil"
    assert config.pi_preflight_path == preflight
    assert config.pi_hardware_proof_path == proof
    assert config.replay_command[0] == os.path.abspath(str(venv_python))
    assert "--target-pi" in config.replay_command

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--capability",
                "sil.hardware_isolation.pi",
                "--target-pi",
                "--pi-preflight",
                str(preflight),
                "--pi-hardware-proof",
                str(proof),
            ]
        )
    assert exc_info.value.code == 2


@pytest.mark.parametrize(
    "arguments",
    [
        ["--suite", "standard", "--target-pi"],
        ["--suite", "standard", "--warmup-runs", "1"],
        ["--suite", "standard", "--inject-ui-stall-ms", "1"],
        ["--suite", "standard", "--host-label", "host"],
        ["--suite", "standard", "--emit-report-set"],
        ["--suite", "standard", "--accept-baseline", "baseline.json"],
        ["--suite", "standard", "--threshold-maturity", "diagnostic"],
        ["--suite", "standard", "--compare", "a.json", "b.json"],
        ["--suite", "standard", "--speed-multiplier", "0"],
    ],
)
def test_cli_rejects_deferred_or_unsupported_aggregate_controls(arguments):
    with pytest.raises(SystemExit) as exc_info:
        main(arguments)
    assert exc_info.value.code == 2
