from __future__ import annotations

import base64
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "pi_development_workflow.py"
WRAPPER_PATH = REPO_ROOT / "tools" / "run_pi_development.ps1"

SPEC = importlib.util.spec_from_file_location("pi_development_workflow", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)


def _local(**updates):
    payload = {
        "repo_root": "C:/repo",
        "head": "a" * 40,
        "short_head": "a" * 12,
        "branch": "feature/test",
        "detached": False,
        "clean": True,
        "status": [],
        "upstream": "origin/feature/test",
        "upstream_remote": "origin",
        "upstream_merge_ref": "refs/heads/feature/test",
        "ahead": 0,
        "behind": 0,
        "head_reachable_from_upstream": True,
        "origin_url": "https://example.invalid/repo.git",
    }
    payload.update(updates)
    return payload


def _remote(**updates):
    payload = {
        "ssh_target": "labcraft@pi-test",
        "ssh_identity_supplied": True,
        "hostname": "pi-test",
        "production_worktree": {
            "valid": True,
            "registered": True,
            "path": "/home/labcraft/LabCraft_printer",
            "head": "b" * 40,
            "branch": "protected-update-rc5",
            "detached": False,
            "clean": True,
            "status": [],
        },
        "development_worktree": {
            "path": "/home/labcraft/LabCraft_printer-dev",
            "state": "absent",
            "registered": False,
            "error": None,
        },
        "other_worktrees": [],
        "shared_python": {
            "path": "/home/labcraft/LabCraft_printer/env/bin/python",
            "exists": True,
            "executable": True,
            "version": "Python 3.11.2",
        },
        "processes": [],
        "development_machine_data": {
            "selection_source": "single_candidate",
            "candidate_paths": ["/machine-data/dev"],
            "selected": {
                "path": "/machine-data/dev",
                "valid": True,
                "marker_valid": True,
                "active_pointer_valid": True,
                "machine_identity_valid": True,
                "store_id": "00000000-0000-0000-0000-000000000001",
                "machine_id": "LC-001",
                "source_tree_evidence": {
                    "valid": True,
                    "file_count": 66,
                    "total_size": 4_300_000,
                    "tree_sha256": "1" * 64,
                },
                "development_tree_evidence": {
                    "valid": True,
                    "file_count": 58,
                    "total_size": 3_200_000,
                    "tree_sha256": "2" * 64,
                },
                "errors": [],
            },
        },
        "workflow_config": {
            "path": workflow.DEFAULT_WORKFLOW_CONFIG,
            "exists": False,
            "valid": False,
            "errors": [],
        },
    }
    payload.update(updates)
    return payload


def _runtime_ready_remote(*, configured: bool, selection_source: str = "explicit"):
    payload = _remote()
    payload["development_worktree"] = {
        "path": workflow.DEFAULT_DEVELOPMENT_REPO,
        "state": "registered_clean",
        "registered": True,
        "valid": True,
        "clean": True,
        "status": [],
        "head": "a" * 40,
        "branch": None,
        "detached": True,
    }
    payload["development_machine_data"]["selection_source"] = selection_source
    if configured:
        payload["workflow_config"] = {
            "path": workflow.DEFAULT_WORKFLOW_CONFIG,
            "exists": True,
            "valid": True,
            "errors": [],
            "payload": {
                "schema_name": "labcraft.pi_development_workflow_config",
                "schema_version": 1,
                "production_repo": workflow.DEFAULT_PRODUCTION_REPO,
                "development_repo": workflow.DEFAULT_DEVELOPMENT_REPO,
                "shared_python": workflow.DEFAULT_SHARED_PYTHON,
                "development_machine_data_root": "/machine-data/dev",
                "development_store_id": "00000000-0000-0000-0000-000000000001",
                "machine_id": "LC-001",
                "dependency_manifest_sha256": "d" * 64,
                "configured_at_utc": "2026-08-21T12:00:00Z",
                "configured_by": "Conary-Codex",
                "creation_commit": "a" * 40,
            },
        }
    return payload


def _codes(values):
    return {value["code"] for value in values}


def test_embedded_pi_programs_compile():
    compile(workflow.REMOTE_COLLECTOR, "REMOTE_COLLECTOR", "exec")
    compile(workflow.REMOTE_SYNC, "REMOTE_SYNC", "exec")
    compile(workflow.REMOTE_RUNTIME_CONFIG, "REMOTE_RUNTIME_CONFIG", "exec")
    compile(workflow.REMOTE_LAUNCH, "REMOTE_LAUNCH", "exec")


def test_absent_development_worktree_is_ready_with_warning():
    blockers, warnings = workflow.classify_status(_local(), _remote())
    assert blockers == []
    assert _codes(warnings) == {"development_worktree_absent"}


@pytest.mark.parametrize(
    "updates",
    [
        {"production_repo": "relative/production"},
        {"development_repo": "/home/labcraft/LabCraft_printer/child"},
        {"development_repo": "/home/labcraft"},
        {"shared_python": "relative/python"},
        {"shared_python": "/usr/bin/python3"},
        {"development_machine_data_root": "/home/labcraft/LabCraft_printer-dev/data"},
        {"workflow_config": "/home/labcraft/LabCraft_printer-dev/workflow.json"},
        {"workflow_config": "/home/labcraft"},
    ],
)
def test_remote_path_contract_rejects_relative_broad_nested_and_overlapping_paths(updates):
    arguments = {
        "pi_user": "labcraft",
        "production_repo": workflow.DEFAULT_PRODUCTION_REPO,
        "development_repo": workflow.DEFAULT_DEVELOPMENT_REPO,
        "shared_python": workflow.DEFAULT_SHARED_PYTHON,
        "development_machine_data_root": "/machine-data/development",
    }
    arguments.update(updates)
    with pytest.raises(workflow.WorkflowError):
        workflow.validate_remote_paths(**arguments)


def test_remote_path_contract_accepts_expected_disjoint_paths():
    workflow.validate_remote_paths(
        pi_user="labcraft",
        production_repo=workflow.DEFAULT_PRODUCTION_REPO,
        development_repo=workflow.DEFAULT_DEVELOPMENT_REPO,
        shared_python=workflow.DEFAULT_SHARED_PYTHON,
        development_machine_data_root=(
            "/home/labcraft/.local/share/LabCraft/LabCraft Printer/development/store"
        ),
    )


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"clean": False}, "local_dirty"),
        ({"detached": True, "branch": None}, "local_detached"),
        ({"upstream": None}, "local_upstream_missing"),
        ({"head_reachable_from_upstream": False}, "local_head_unpublished"),
    ],
)
def test_local_blocking_states(updates, code):
    blockers, _warnings = workflow.classify_status(_local(**updates), _remote())
    assert code in _codes(blockers)


def test_behind_but_pushed_is_warning_only():
    blockers, warnings = workflow.classify_status(
        _local(behind=2, head_reachable_from_upstream=True), _remote()
    )
    assert blockers == []
    assert "local_behind" in _codes(warnings)


@pytest.mark.parametrize("state", ["registered_dirty", "unregistered_path", "invalid"])
def test_development_worktree_unsafe_states_block(state):
    remote = _remote()
    remote["development_worktree"] = {
        "path": "/home/labcraft/LabCraft_printer-dev",
        "state": state,
        "registered": state.startswith("registered"),
    }
    blockers, _warnings = workflow.classify_status(_local(), remote)
    assert "development_worktree_unsafe" in _codes(blockers)


def test_clean_registered_development_worktree_is_ready():
    remote = _remote()
    remote["development_worktree"] = {
        "path": "/home/labcraft/LabCraft_printer-dev",
        "state": "registered_clean",
        "registered": True,
        "valid": True,
        "clean": True,
    }
    blockers, warnings = workflow.classify_status(_local(), remote)
    assert blockers == []
    assert warnings == []


def test_production_interpreter_process_and_store_failures_block():
    remote = _remote()
    remote["production_worktree"]["clean"] = False
    remote["shared_python"]["executable"] = False
    remote["processes"] = [{"pid": 42, "command": "FreeRTOS-interface/App.py"}]
    remote["development_machine_data"] = {
        "selection_source": "ambiguous",
        "candidate_paths": ["/one", "/two"],
        "selected": None,
    }
    blockers, _warnings = workflow.classify_status(_local(), remote)
    assert {
        "production_dirty",
        "shared_python_invalid",
        "labcraft_process_running",
        "development_store_unresolved",
    } <= _codes(blockers)


def test_additional_worktrees_are_warning_only():
    remote = _remote()
    remote["other_worktrees"] = [{"path": "/retained", "head": "c" * 40}]
    blockers, warnings = workflow.classify_status(_local(), remote)
    assert blockers == []
    assert "additional_worktrees" in _codes(warnings)


def test_existing_invalid_workflow_configuration_blocks():
    remote = _remote()
    remote["workflow_config"] = {
        "path": workflow.DEFAULT_WORKFLOW_CONFIG,
        "exists": True,
        "valid": False,
        "errors": ["configured development store identity differs"],
    }
    blockers, _warnings = workflow.classify_status(_local(), remote)
    assert "workflow_config_invalid" in _codes(blockers)


def test_report_schema_and_atomic_write_exclude_identity_path(tmp_path):
    report = workflow.build_report(
        action="status",
        local=_local(),
        remote=_remote(),
        clock=datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc),
        collection_id="00000000-0000-0000-0000-000000000009",
    )
    path = workflow.write_report(report, tmp_path)
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["schema_name"] == "labcraft.pi_development_status"
    assert persisted["schema_version"] == 1
    assert persisted["overall_state"] == "warning"
    assert "identity_file" not in json.dumps(persisted)
    assert not list(path.parent.glob(".*.tmp"))


def test_remote_collector_rejects_nonzero_and_malformed_ssh(monkeypatch, tmp_path):
    identity = tmp_path / "identity"
    identity.write_text("placeholder", encoding="utf-8")

    def failed(*_args, **_kwargs):
        raise workflow.WorkflowError("ssh failed")

    monkeypatch.setattr(workflow, "_run", failed)
    with pytest.raises(workflow.WorkflowError, match="ssh failed"):
        workflow.collect_remote_state(
            pi_host="pi-test",
            pi_user="labcraft",
            identity_file=identity,
            production_repo=workflow.DEFAULT_PRODUCTION_REPO,
            development_repo=workflow.DEFAULT_DEVELOPMENT_REPO,
            shared_python=workflow.DEFAULT_SHARED_PYTHON,
            development_machine_data_root=None,
        )

    def malformed(*_args, **_kwargs):
        return subprocess.CompletedProcess([], 0, stdout="not-json", stderr="benign")

    monkeypatch.setattr(workflow, "_run", malformed)
    with pytest.raises(workflow.WorkflowError, match="malformed"):
        workflow.collect_remote_state(
            pi_host="user@pi-test",
            pi_user="ignored",
            identity_file=identity,
            production_repo=workflow.DEFAULT_PRODUCTION_REPO,
            development_repo=workflow.DEFAULT_DEVELOPMENT_REPO,
            shared_python=workflow.DEFAULT_SHARED_PYTHON,
            development_machine_data_root=None,
        )


def test_remote_collector_accepts_json_and_uses_batch_mode(monkeypatch):
    captured = {}

    def fake_run(arguments, **kwargs):
        captured["arguments"] = list(arguments)
        captured["input"] = kwargs["input_text"]
        return subprocess.CompletedProcess([], 0, stdout=json.dumps(_remote()), stderr="benign")

    monkeypatch.setattr(workflow, "_run", fake_run)
    result = workflow.collect_remote_state(
        pi_host="pi-test",
        pi_user="operator",
        identity_file=None,
        production_repo=workflow.DEFAULT_PRODUCTION_REPO,
        development_repo=workflow.DEFAULT_DEVELOPMENT_REPO,
        shared_python=workflow.DEFAULT_SHARED_PYTHON,
        development_machine_data_root=None,
    )
    assert result["ssh_target"] == "operator@pi-test"
    assert "BatchMode=yes" in captured["arguments"]
    assert "development_store.json" in captured["input"]
    assert "machine_identity.json" in captured["input"]
    assert "regular_tree_evidence" in captured["input"]
    assert "tree_sha256" in captured["input"]
    encoded = captured["arguments"][-1]
    request = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
    assert request["workflow_config"] == workflow.DEFAULT_WORKFLOW_CONFIG


def test_sync_remote_worktree_uses_exact_commit_and_safe_remote_ref(monkeypatch):
    captured = {}

    def fake_run(arguments, **kwargs):
        captured["arguments"] = list(arguments)
        captured["input"] = kwargs["input_text"]
        return subprocess.CompletedProcess(
            [],
            0,
            stdout=json.dumps(
                {
                    "action": "created",
                    "commit": "a" * 40,
                    "development_repo": workflow.DEFAULT_DEVELOPMENT_REPO,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(workflow, "_run", fake_run)
    result = workflow.sync_remote_worktree(
        pi_host="pi-test",
        pi_user="labcraft",
        identity_file=None,
        production_repo=workflow.DEFAULT_PRODUCTION_REPO,
        development_repo=workflow.DEFAULT_DEVELOPMENT_REPO,
        expected_commit="a" * 40,
        expected_production_head="b" * 40,
        expected_production_branch="protected-update-rc5",
        remote_name="origin",
        remote_ref="refs/heads/feature/test",
        expected_remote_url="https://example.invalid/repo.git",
    )
    assert result["action"] == "created"
    assert "BatchMode=yes" in captured["arguments"]
    assert "worktree\", \"add\"" in captured["input"]
    assert "switch\", \"--detach\"" in captured["input"]
    assert "reset --hard" not in captured["input"]
    assert "git clean" not in captured["input"]


@pytest.mark.parametrize(
    ("remote_name", "remote_ref"),
    [("", "refs/heads/feature/test"), (".", "refs/heads/feature/test"), ("origin", "tag")],
)
def test_sync_remote_worktree_rejects_unsafe_upstream_contract(remote_name, remote_ref):
    with pytest.raises(workflow.WorkflowError):
        workflow.sync_remote_worktree(
            pi_host="pi-test",
            pi_user="labcraft",
            identity_file=None,
            production_repo=workflow.DEFAULT_PRODUCTION_REPO,
            development_repo=workflow.DEFAULT_DEVELOPMENT_REPO,
            expected_commit="a" * 40,
            expected_production_head="b" * 40,
            expected_production_branch="protected-update-rc5",
            remote_name=remote_name,
            remote_ref=remote_ref,
            expected_remote_url="https://example.invalid/repo.git",
        )


def test_configure_remote_runtime_uses_explicit_read_only_contract(monkeypatch):
    captured = {}

    def fake_run(arguments, **kwargs):
        captured["arguments"] = list(arguments)
        captured["input"] = kwargs["input_text"]
        return subprocess.CompletedProcess(
            [],
            0,
            stdout=json.dumps(
                {
                    "action": "created",
                    "config_path": workflow.DEFAULT_WORKFLOW_CONFIG,
                    "dependency_manifest_sha256": "d" * 64,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(workflow, "_run", fake_run)
    result = workflow.configure_remote_runtime(
        mode="configure",
        pi_host="pi-test",
        pi_user="labcraft",
        identity_file=None,
        production_repo=workflow.DEFAULT_PRODUCTION_REPO,
        development_repo=workflow.DEFAULT_DEVELOPMENT_REPO,
        shared_python=workflow.DEFAULT_SHARED_PYTHON,
        development_machine_data_root="/machine-data/dev",
        workflow_config=workflow.DEFAULT_WORKFLOW_CONFIG,
        operator="Conary-Codex",
        expected_commit="a" * 40,
        expected_production_head="b" * 40,
        expected_production_branch="protected-update-rc5",
    )
    request = json.loads(
        base64.urlsafe_b64decode(captured["arguments"][-1]).decode("utf-8")
    )
    assert result["action"] == "created"
    assert request["mode"] == "configure"
    assert request["operator"] == "Conary-Codex"
    assert request["development_machine_data_root"] == "/machine-data/dev"
    assert '"pip", "check"' in captured["input"]
    assert '"pip", "install"' not in captured["input"]
    assert "environment_before" in captured["input"]
    assert "machine_identity.json" in captured["input"]
    assert "os.replace" in captured["input"]
    assert 'shared_python = lexical_absolute(config["shared_python"])' in captured["input"]
    assert 'shared_python = resolved(config["shared_python"])' not in captured["input"]


@pytest.mark.parametrize(
    ("mode", "operator"),
    [("launch", "Conary-Codex"), ("configure", ""), ("validate", "   ")],
)
def test_configure_remote_runtime_rejects_invalid_mode_or_operator(mode, operator):
    with pytest.raises(workflow.WorkflowError):
        workflow.configure_remote_runtime(
            mode=mode,
            pi_host="pi-test",
            pi_user="labcraft",
            identity_file=None,
            production_repo=workflow.DEFAULT_PRODUCTION_REPO,
            development_repo=workflow.DEFAULT_DEVELOPMENT_REPO,
            shared_python=workflow.DEFAULT_SHARED_PYTHON,
            development_machine_data_root="/machine-data/dev",
            workflow_config=workflow.DEFAULT_WORKFLOW_CONFIG,
            operator=operator,
            expected_commit="a" * 40,
            expected_production_head="b" * 40,
            expected_production_branch="protected-update-rc5",
        )


def test_pi_invariant_hash_excludes_only_managed_development_state():
    before = _remote()
    after = _remote()
    after["development_worktree"] = {
        "path": workflow.DEFAULT_DEVELOPMENT_REPO,
        "state": "registered_clean",
        "registered": True,
        "valid": True,
        "clean": True,
        "head": "a" * 40,
        "detached": True,
    }
    assert workflow.canonical_sha256(workflow.pi_invariant_payload(before)) == (
        workflow.canonical_sha256(workflow.pi_invariant_payload(after))
    )
    after["workflow_config"] = {
        "path": workflow.DEFAULT_WORKFLOW_CONFIG,
        "exists": True,
        "valid": True,
        "errors": [],
    }
    assert workflow.canonical_sha256(workflow.pi_invariant_payload(before)) == (
        workflow.canonical_sha256(workflow.pi_invariant_payload(after))
    )
    after["production_worktree"]["head"] = "c" * 40
    assert workflow.canonical_sha256(workflow.pi_invariant_payload(before)) != (
        workflow.canonical_sha256(workflow.pi_invariant_payload(after))
    )


def test_powershell_wrapper_dry_run_and_identity_validation(tmp_path):
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    result = subprocess.run(
        [
            powershell,
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(WRAPPER_PATH),
            "-PiHost",
            "developer@pi-test",
            "-DryRun",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "DRY RUN action=status" in result.stdout
    assert "SSH target: developer@pi-test" in result.stdout
    assert "No SSH call or report write was performed" in result.stdout

    configure = subprocess.run(
        [
            powershell,
            "-ExecutionPolicy", "Bypass",
            "-File", str(WRAPPER_PATH),
            "-Action", "Configure",
            "-PiHost", "pi-test",
            "-DevelopmentMachineDataRoot", "/machine-data/dev",
            "-Operator", "Conary-Codex",
            "-DryRun",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert configure.returncode == 0, configure.stderr
    assert "DRY RUN action=configure" in configure.stdout
    assert "Development machine data: /machine-data/dev" in configure.stdout
    assert f"Workflow configuration: {workflow.DEFAULT_WORKFLOW_CONFIG}" in configure.stdout
    assert "Operator: Conary-Codex" in configure.stdout

    missing = tmp_path / "missing-identity"
    rejected = subprocess.run(
        [
            powershell,
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(WRAPPER_PATH),
            "-PiHost",
            "pi-test",
            "-SshIdentityFile",
            str(missing),
            "-DryRun",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert rejected.returncode == 1
    assert "identity file does not exist" in rejected.stderr


def test_cli_preflight_returns_two_for_policy_block(monkeypatch, tmp_path):
    monkeypatch.setattr(workflow, "collect_local_state", lambda *_: _local(clean=False))
    monkeypatch.setattr(workflow, "collect_remote_state", lambda **_: _remote())
    result = workflow.main(
        [
            "--action", "preflight",
            "--pi-host", "pi-test",
            "--output-root", str(tmp_path),
        ]
    )
    assert result == 2
    assert list(tmp_path.rglob("status.json"))


def test_cli_rejects_missing_openssh_before_collection(monkeypatch, capsys):
    monkeypatch.setattr(workflow.shutil, "which", lambda _name: None)
    result = workflow.main(["--action", "status", "--pi-host", "pi-test"])
    assert result == 1
    assert "OpenSSH client" in capsys.readouterr().err


def test_cli_sync_blocks_before_mutation(monkeypatch, tmp_path):
    monkeypatch.setattr(workflow, "collect_local_state", lambda *_: _local(clean=False))
    monkeypatch.setattr(workflow, "collect_remote_state", lambda **_: _remote())
    called = False

    def unexpected_sync(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("sync must not run")

    monkeypatch.setattr(workflow, "sync_remote_worktree", unexpected_sync)
    result = workflow.main(
        ["--action", "sync", "--pi-host", "pi-test", "--output-root", str(tmp_path)]
    )
    assert result == 2
    assert called is False
    report = json.loads(next(tmp_path.rglob("status.json")).read_text(encoding="utf-8"))
    assert "local_dirty" in _codes(report["blockers"])


def test_cli_sync_creates_exact_clean_detached_worktree_and_proves_invariants(
    monkeypatch, tmp_path
):
    pre = _remote()
    post = _remote()
    post["development_worktree"] = {
        "path": workflow.DEFAULT_DEVELOPMENT_REPO,
        "state": "registered_clean",
        "registered": True,
        "valid": True,
        "clean": True,
        "status": [],
        "head": "a" * 40,
        "branch": None,
        "detached": True,
    }
    states = iter([pre, post])
    monkeypatch.setattr(workflow, "collect_local_state", lambda *_: _local())
    monkeypatch.setattr(workflow, "collect_remote_state", lambda **_: next(states))
    monkeypatch.setattr(
        workflow,
        "sync_remote_worktree",
        lambda **_: {
            "action": "created",
            "commit": "a" * 40,
            "development_repo": workflow.DEFAULT_DEVELOPMENT_REPO,
        },
    )
    result = workflow.main(
        ["--action", "sync", "--pi-host", "pi-test", "--output-root", str(tmp_path)]
    )
    assert result == 0
    report = json.loads(next(tmp_path.rglob("status.json")).read_text(encoding="utf-8"))
    assert report["sync"]["status"] == "passed"
    assert report["sync"]["action"] == "created"
    assert report["sync"]["pre_invariant_sha256"] == report["sync"]["post_invariant_sha256"]
    assert report["pi"]["development_worktree"]["head"] == "a" * 40


def test_cli_sync_failure_writes_evidence_and_returns_one(monkeypatch, tmp_path):
    monkeypatch.setattr(workflow, "collect_local_state", lambda *_: _local())
    monkeypatch.setattr(workflow, "collect_remote_state", lambda **_: _remote())
    monkeypatch.setattr(
        workflow,
        "sync_remote_worktree",
        lambda **_: (_ for _ in ()).throw(workflow.WorkflowError("fetch rejected")),
    )
    result = workflow.main(
        ["--action", "sync", "--pi-host", "pi-test", "--output-root", str(tmp_path)]
    )
    assert result == 1
    report = json.loads(next(tmp_path.rglob("status.json")).read_text(encoding="utf-8"))
    assert report["sync"] == {"status": "failed", "error": "fetch rejected"}


def test_cli_configure_creates_binding_and_proves_invariants(monkeypatch, tmp_path):
    pre = _runtime_ready_remote(configured=False, selection_source="explicit")
    post = _runtime_ready_remote(configured=True, selection_source="explicit")
    states = iter([pre, post])
    captured = {}
    monkeypatch.setattr(workflow, "collect_local_state", lambda *_: _local())
    monkeypatch.setattr(workflow, "collect_remote_state", lambda **_: next(states))

    def configured(**kwargs):
        captured.update(kwargs)
        return {
            "action": "created",
            "config_path": workflow.DEFAULT_WORKFLOW_CONFIG,
            "dependency_manifest_sha256": "d" * 64,
            "environment_before": {"sha256": "e" * 64},
            "environment_after": {"sha256": "e" * 64},
        }

    monkeypatch.setattr(workflow, "configure_remote_runtime", configured)
    result = workflow.main(
        [
            "--action", "configure",
            "--pi-host", "pi-test",
            "--development-machine-data-root", "/machine-data/dev",
            "--operator", "Conary-Codex",
            "--output-root", str(tmp_path),
        ]
    )
    assert result == 0
    assert captured["development_machine_data_root"] == "/machine-data/dev"
    assert captured["operator"] == "Conary-Codex"
    report = json.loads(next(tmp_path.rglob("status.json")).read_text(encoding="utf-8"))
    assert report["runtime"]["status"] == "passed"
    assert report["runtime"]["action"] == "created"
    assert report["runtime"]["pre_invariant_sha256"] == report["runtime"]["post_invariant_sha256"]
    assert report["runtime"]["pre_workflow_config"]["exists"] is False
    assert report["runtime"]["post_workflow_config"]["valid"] is True
    assert report["pi"]["workflow_config"]["valid"] is True


def test_cli_validate_reuses_persisted_store_without_discovery(monkeypatch, tmp_path):
    states = iter(
        [
            _runtime_ready_remote(configured=True, selection_source="configured"),
            _runtime_ready_remote(configured=True, selection_source="configured"),
        ]
    )
    captured = {}
    monkeypatch.setattr(workflow, "collect_local_state", lambda *_: _local())
    monkeypatch.setattr(workflow, "collect_remote_state", lambda **_: next(states))

    def validated(**kwargs):
        captured.update(kwargs)
        return {"action": "validated", "config_path": workflow.DEFAULT_WORKFLOW_CONFIG}

    monkeypatch.setattr(workflow, "configure_remote_runtime", validated)
    result = workflow.main(
        ["--action", "validate", "--pi-host", "pi-test", "--output-root", str(tmp_path)]
    )
    assert result == 0
    assert captured["development_machine_data_root"] == "/machine-data/dev"
    report = json.loads(next(tmp_path.rglob("status.json")).read_text(encoding="utf-8"))
    assert report["runtime"]["action"] == "validated"
    assert report["pi"]["development_machine_data"]["selection_source"] == "configured"


def test_cli_configure_requires_explicit_store_and_exact_development_head(
    monkeypatch, tmp_path
):
    called = False

    def unexpected(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("runtime configuration must not run")

    monkeypatch.setattr(workflow, "collect_local_state", lambda *_: _local())
    monkeypatch.setattr(
        workflow,
        "collect_remote_state",
        lambda **_: _runtime_ready_remote(configured=False, selection_source="single_candidate"),
    )
    monkeypatch.setattr(workflow, "configure_remote_runtime", unexpected)
    result = workflow.main(
        ["--action", "configure", "--pi-host", "pi-test", "--output-root", str(tmp_path)]
    )
    assert result == 2
    assert called is False
    report = json.loads(next(tmp_path.rglob("status.json")).read_text(encoding="utf-8"))
    assert "explicit development machine-data root" in report["runtime"]["error"]

    second_output = tmp_path / "head-mismatch"
    remote = _runtime_ready_remote(configured=False)
    remote["development_worktree"]["head"] = "c" * 40
    monkeypatch.setattr(workflow, "collect_remote_state", lambda **_: remote)
    result = workflow.main(
        [
            "--action", "configure", "--pi-host", "pi-test",
            "--development-machine-data-root", "/machine-data/dev",
            "--output-root", str(second_output),
        ]
    )
    assert result == 2
    assert called is False


def test_cli_runtime_failure_writes_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(workflow, "collect_local_state", lambda *_: _local())
    monkeypatch.setattr(
        workflow,
        "collect_remote_state",
        lambda **_: _runtime_ready_remote(configured=False),
    )
    monkeypatch.setattr(
        workflow,
        "configure_remote_runtime",
        lambda **_: (_ for _ in ()).throw(workflow.WorkflowError("dependency mismatch")),
    )
    result = workflow.main(
        [
            "--action", "configure", "--pi-host", "pi-test",
            "--development-machine-data-root", "/machine-data/dev",
            "--output-root", str(tmp_path),
        ]
    )
    assert result == 1
    report = json.loads(next(tmp_path.rglob("status.json")).read_text(encoding="utf-8"))
    assert report["runtime"] == {"status": "failed", "error": "dependency mismatch"}


def test_launch_remote_app_uses_bounded_no_hardware_supervisor(monkeypatch):
    captured = {}

    def fake_run(arguments, **kwargs):
        captured["arguments"] = list(arguments)
        captured["input"] = kwargs["input_text"]
        captured["timeout"] = kwargs["timeout_seconds"]
        return subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({
                "status": "passed",
                "launch_mode": "offscreen",
                "report_path": "/evidence/launch.json",
            }), stderr=""
        )

    monkeypatch.setattr(workflow, "_run", fake_run)
    result = workflow.launch_remote_app(
        pi_host="pi-test",
        pi_user="labcraft",
        identity_file=None,
        production_repo=workflow.DEFAULT_PRODUCTION_REPO,
        development_repo=workflow.DEFAULT_DEVELOPMENT_REPO,
        shared_python=workflow.DEFAULT_SHARED_PYTHON,
        workflow_config=workflow.DEFAULT_WORKFLOW_CONFIG,
        operator="Conary-Codex",
        expected_commit="a" * 40,
        expected_production_head="b" * 40,
        expected_production_branch="protected-update-rc5",
        launch_mode="offscreen",
        auto_close_seconds=3.0,
        launch_timeout_seconds=60,
        remote_session_root=workflow.DEFAULT_REMOTE_SESSION_ROOT,
    )
    request = json.loads(
        base64.urlsafe_b64decode(captured["arguments"][-1]).decode("utf-8")
    )
    assert result["status"] == "passed"
    assert request["launch_mode"] == "offscreen"
    assert request["auto_close_seconds"] == 3.0
    assert request["remote_session_root"] == workflow.DEFAULT_REMOTE_SESSION_ROOT
    assert "enable_hardware" not in request
    assert captured["timeout"] == 105
    assert '"bwrap", "--unshare-all"' in captured["input"]
    assert '"strace", "-f"' in captured["input"]
    assert 'start_new_session=True' in captured["input"]
    assert "forbidden_hardware_matches" in captured["input"]
    assert "SimulatedMachine" in captured["input"]


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"launch_mode": "hardware"}, "Unsupported launch mode"),
        ({"operator": "  "}, "operator"),
        ({"auto_close_seconds": 0.1}, "Auto-close"),
        ({"launch_timeout_seconds": 9}, "timeout"),
        ({"remote_session_root": "/home/labcraft"}, "external"),
    ],
)
def test_launch_remote_app_rejects_unsafe_contract(monkeypatch, updates, message):
    arguments = {
        "pi_host": "pi-test",
        "pi_user": "labcraft",
        "identity_file": None,
        "production_repo": workflow.DEFAULT_PRODUCTION_REPO,
        "development_repo": workflow.DEFAULT_DEVELOPMENT_REPO,
        "shared_python": workflow.DEFAULT_SHARED_PYTHON,
        "workflow_config": workflow.DEFAULT_WORKFLOW_CONFIG,
        "operator": "Conary-Codex",
        "expected_commit": "a" * 40,
        "expected_production_head": "b" * 40,
        "expected_production_branch": "protected-update-rc5",
        "launch_mode": "offscreen",
        "auto_close_seconds": 3.0,
        "launch_timeout_seconds": 60,
        "remote_session_root": workflow.DEFAULT_REMOTE_SESSION_ROOT,
    }
    arguments.update(updates)
    monkeypatch.setattr(
        workflow, "_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no SSH")),
    )
    with pytest.raises(workflow.WorkflowError, match=message):
        workflow.launch_remote_app(**arguments)


def test_launch_invariant_excludes_only_development_runtime_writes():
    before = _runtime_ready_remote(configured=True, selection_source="configured")
    after = json.loads(json.dumps(before))
    after["development_machine_data"]["selected"]["development_tree_evidence"][
        "tree_sha256"
    ] = "9" * 64
    assert workflow.canonical_sha256(workflow.launch_invariant_payload(before)) == (
        workflow.canonical_sha256(workflow.launch_invariant_payload(after))
    )
    after["development_machine_data"]["selected"]["source_tree_evidence"][
        "tree_sha256"
    ] = "8" * 64
    assert workflow.canonical_sha256(workflow.launch_invariant_payload(before)) != (
        workflow.canonical_sha256(workflow.launch_invariant_payload(after))
    )


def test_cli_launch_validates_then_launches_and_proves_invariants(monkeypatch, tmp_path):
    states = iter([
        _runtime_ready_remote(configured=True, selection_source="configured"),
        _runtime_ready_remote(configured=True, selection_source="configured"),
        _runtime_ready_remote(configured=True, selection_source="configured"),
    ])
    calls = []
    monkeypatch.setattr(workflow, "collect_local_state", lambda *_: _local())
    monkeypatch.setattr(workflow, "collect_remote_state", lambda **_: next(states))
    monkeypatch.setattr(
        workflow, "configure_remote_runtime",
        lambda **kwargs: calls.append(("validate", kwargs)) or {
            "action": "validated", "config_path": workflow.DEFAULT_WORKFLOW_CONFIG,
        },
    )
    monkeypatch.setattr(
        workflow, "launch_remote_app",
        lambda **kwargs: calls.append(("launch", kwargs)) or {
            "status": "passed", "launch_mode": "offscreen",
            "report_path": "/evidence/launch.json", "report_sha256": "e" * 64,
        },
    )
    result = workflow.main([
        "--action", "launch", "--pi-host", "pi-test",
        "--operator", "Conary-Codex", "--auto-close-seconds", "3",
        "--launch-timeout-seconds", "60", "--output-root", str(tmp_path),
    ])
    assert result == 0
    assert [name for name, _kwargs in calls] == ["validate", "launch"]
    assert calls[0][1]["mode"] == "validate"
    assert calls[1][1]["auto_close_seconds"] == 3.0
    report = json.loads(next(tmp_path.rglob("status.json")).read_text(encoding="utf-8"))
    assert report["launch"]["status"] == "passed"
    assert report["launch"]["pre_invariant_sha256"] == report["launch"]["post_invariant_sha256"]


def test_cli_launch_rejects_explicit_store_and_writes_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(workflow, "collect_local_state", lambda *_: _local())
    monkeypatch.setattr(
        workflow, "collect_remote_state",
        lambda **_: _runtime_ready_remote(configured=True, selection_source="configured"),
    )
    monkeypatch.setattr(
        workflow, "launch_remote_app",
        lambda **_: (_ for _ in ()).throw(AssertionError("launch must not run")),
    )
    result = workflow.main([
        "--action", "launch", "--pi-host", "pi-test",
        "--development-machine-data-root", "/machine-data/dev",
        "--output-root", str(tmp_path),
    ])
    assert result == 2
    report = json.loads(next(tmp_path.rglob("status.json")).read_text(encoding="utf-8"))
    assert "persisted workflow configuration" in report["launch"]["error"]


def test_powershell_wrapper_exposes_slice4_no_hardware_launch():
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    result = subprocess.run(
        [
            powershell, "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER_PATH),
            "-Action", "Launch", "-PiHost", "pi-test", "-LaunchMode", "Offscreen",
            "-AutoCloseSeconds", "3", "-LaunchTimeoutSeconds", "60", "-DryRun",
        ],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "DRY RUN action=launch" in result.stdout
    assert "Launch mode: offscreen" in result.stdout
    assert "Auto-close seconds: 3" in result.stdout
    assert "Launch timeout seconds: 60" in result.stdout
    assert workflow.DEFAULT_REMOTE_SESSION_ROOT in result.stdout
