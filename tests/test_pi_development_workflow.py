from __future__ import annotations

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
                "store_id": "00000000-0000-0000-0000-000000000001",
                "machine_id": "LC-001",
                "errors": [],
            },
        },
    }
    payload.update(updates)
    return payload


def _codes(values):
    return {value["code"] for value in values}


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
        {"development_machine_data_root": "/home/labcraft/LabCraft_printer-dev/data"},
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
