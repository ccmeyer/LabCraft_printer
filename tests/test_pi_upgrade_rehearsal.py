from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS = REPO_ROOT / "tools"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
SPEC = importlib.util.spec_from_file_location(
    "pi_upgrade_rehearsal", TOOLS / "pi_upgrade_rehearsal.py"
)
assert SPEC is not None and SPEC.loader is not None
rehearsal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rehearsal)


def _remote_arguments(**updates):
    values = {
        "pi_user": "labcraft",
        "production_repo": rehearsal.DEFAULT_PRODUCTION_REPO,
        "development_repo": rehearsal.DEFAULT_DEVELOPMENT_REPO,
        "shared_python": rehearsal.DEFAULT_SHARED_PYTHON,
        "workflow_config": rehearsal.DEFAULT_WORKFLOW_CONFIG,
        "firmware_state_path": rehearsal.DEFAULT_FIRMWARE_STATE,
        "remote_root": rehearsal.DEFAULT_REMOTE_ROOT,
    }
    values.update(updates)
    return values


def test_tool_sources_compile_and_offer_no_cleanup_action():
    compile((TOOLS / "pi_upgrade_rehearsal.py").read_text(encoding="utf-8"), "supervisor", "exec")
    compile(
        (TOOLS / "run_machine_data_bootstrap_only.py").read_text(encoding="utf-8"),
        "bootstrap-only",
        "exec",
    )
    choices = rehearsal.build_parser()._option_string_actions["--action"].choices
    assert set(choices) == {
        "prepare", "status", "update", "cancel", "activate", "verify", "summarize"
    }
    assert "cleanup" not in choices


@pytest.mark.parametrize(
    "updates",
    [
        {"production_repo": "relative"},
        {"development_repo": "/home/labcraft/LabCraft_printer/child"},
        {"shared_python": "/usr/bin/python3"},
        {"remote_root": "/home/labcraft"},
        {"remote_root": "/home/labcraft/LabCraft_printer/rehearsals"},
        {"workflow_config": "/home/labcraft/LabCraft_printer/config.json"},
    ],
)
def test_remote_path_contract_rejects_relative_broad_and_overlapping_paths(updates):
    with pytest.raises(rehearsal.RehearsalError):
        rehearsal.validate_remote_paths(**_remote_arguments(**updates))


def test_remote_path_contract_accepts_external_rehearsal_root():
    rehearsal.validate_remote_paths(**_remote_arguments())


def test_local_release_pair_is_exact_annotated_and_ancestral():
    source, target = rehearsal.validate_local_release_pair(
        "v1.2.0-rc.6", "v1.3.0-rc.7"
    )
    assert source["commit"] == "199807eea95a238896137bddb2a83d3d892e2aab"
    assert target["commit"] == "b6138f9d029289385812fe80c276e0eddea90c23"
    assert source["tag_object"] != source["commit"]
    assert target["tag_object"] != target["commit"]


def test_local_release_pair_rejects_non_ancestral_source(monkeypatch):
    monkeypatch.setattr(
        rehearsal,
        "resolve_annotated_tag",
        lambda tag: {"tag": tag, "tag_object": "1" * 40, "commit": tag[-1] * 40},
    )
    monkeypatch.setattr(
        rehearsal,
        "_git",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr=""),
    )
    with pytest.raises(rehearsal.RehearsalError, match="not an ancestor"):
        rehearsal.validate_local_release_pair("v1.2.0-rc.6", "v1.3.0-rc.7")


def test_local_release_pair_rejects_invalid_target_manifest(monkeypatch):
    monkeypatch.setattr(
        rehearsal,
        "resolve_annotated_tag",
        lambda tag: {"tag": tag, "tag_object": "1" * 40, "commit": tag[-1] * 40},
    )

    def fake_git(*arguments, **_kwargs):
        if arguments[0] == "merge-base":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"version": "v1.3.0-rc.7", "tag": "wrong"}),
            stderr="",
        )

    monkeypatch.setattr(rehearsal, "_git", fake_git)
    with pytest.raises(rehearsal.RehearsalError, match="does not bind"):
        rehearsal.validate_local_release_pair("v1.2.0-rc.6", "v1.3.0-rc.7")


def test_public_and_windows_release_bindings_must_match():
    source = {"tag": "v1.2.0-rc.6", "tag_object": "1" * 40, "commit": "2" * 40}
    target = {"tag": "v1.3.0-rc.7", "tag_object": "3" * 40, "commit": "4" * 40}
    mismatched = dict(target, commit="5" * 40)
    with pytest.raises(rehearsal.RehearsalError, match="Public tag evidence"):
        rehearsal.remote_require_public_release_pair(source, target, source, mismatched)


def test_firmware_readiness_is_derived_from_valid_released_role():
    summary = rehearsal.remote_firmware_readiness(
        {
            "exists": True,
            "payload": {
                "schema_name": "labcraft.firmware_state",
                "schema_version": 1,
                "role": "released",
                "state_revision": 178,
            },
        }
    )
    assert summary == {
        "role": "released",
        "production_ready": True,
        "state_revision": 178,
    }


@pytest.mark.parametrize("role", ["development", "unknown", "recovery-required"])
def test_nonreleased_firmware_role_is_not_production_ready(role):
    summary = rehearsal.remote_firmware_readiness(
        {
            "exists": True,
            "payload": {
                "schema_name": "labcraft.firmware_state",
                "schema_version": 1,
                "role": role,
                "state_revision": 1,
            },
        }
    )
    assert summary["production_ready"] is False


@pytest.mark.parametrize("value", ["main", "v1.3.0-rc.latest", "../v1.3.0", ""])
def test_release_tags_must_be_exact(value):
    with pytest.raises(rehearsal.RehearsalError):
        rehearsal.validate_tag(value, "test")


def test_prepare_dry_run_has_no_ssh_or_evidence_write(monkeypatch, capsys):
    monkeypatch.setattr(
        rehearsal,
        "collect_local_harness",
        lambda: (_ for _ in ()).throw(AssertionError("dry run inspected Git")),
    )
    monkeypatch.setattr(
        rehearsal,
        "invoke_remote",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("dry run used SSH")),
    )
    code = rehearsal.local_main(
        [
            "--action", "prepare",
            "--pi-host", "192.0.2.10",
            "--source-release", "v1.2.0-rc.6",
            "--target-release", "v1.3.0-rc.7",
            "--source-wrapper", "/media/backup/rc6",
            "--expected-machine-id", "LC-TEST",
            "--operator", "Operator",
            "--dry-run",
        ]
    )
    assert code == 0
    output = capsys.readouterr().out
    assert "No SSH call" in output
    assert "hardware action" in output


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is only required on Windows")
def test_powershell_wrapper_forwards_prepare_dry_run():
    completed = subprocess.run(
        [
            POWERSHELL, "-ExecutionPolicy", "Bypass", "-File",
            str(TOOLS / "run_pi_upgrade_rehearsal.ps1"),
            "-Action", "Prepare",
            "-PiHost", "192.0.2.10",
            "-SourceRelease", "v1.2.0-rc.6",
            "-TargetRelease", "v1.3.0-rc.7",
            "-SourceWrapper", "/media/backup/rc6",
            "-ExpectedMachineId", "LC-TEST",
            "-Operator", "Operator",
            "-DryRun",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "No SSH call" in completed.stdout


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is only required on Windows")
def test_powershell_wrapper_splits_comma_separated_summary_ids():
    run_ids = f"{uuid4()},{uuid4()}"
    completed = subprocess.run(
        [
            POWERSHELL, "-ExecutionPolicy", "Bypass", "-File",
            str(TOOLS / "run_pi_upgrade_rehearsal.ps1"),
            "-Action", "Summarize",
            "-PiHost", "192.0.2.10",
            "-RunId", run_ids,
            "-Operator", "Operator",
            "-DryRun",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "No SSH call" in completed.stdout
    assert "2 run ID(s)" in completed.stdout


def test_build_request_binds_bootstrap_runner_bytes(monkeypatch):
    source = {"tag": "v1.2.0-rc.6", "tag_object": "1" * 40, "commit": "2" * 40}
    target = {"tag": "v1.3.0-rc.7", "tag_object": "3" * 40, "commit": "4" * 40}
    monkeypatch.setattr(rehearsal, "validate_local_release_pair", lambda *_args: (source, target))
    args = rehearsal.build_parser().parse_args(
        [
            "--action", "activate", "--pi-host", "pi",
            "--run-id", str(uuid4()), "--operator", "Operator",
        ]
    )
    request = rehearsal.build_request(args, {"head": "5" * 40})
    decoded = __import__("base64").b64decode(request["bootstrap_runner_b64"])
    assert decoded == rehearsal.BOOTSTRAP_RUNNER.read_bytes()
    assert rehearsal.hashlib.sha256(decoded).hexdigest() == request["bootstrap_runner_sha256"]


def test_prepare_request_records_bootstrap_runner_hash(monkeypatch):
    source = {"tag": "v1.2.0-rc.6", "tag_object": "1" * 40, "commit": "2" * 40}
    target = {"tag": "v1.3.0-rc.7", "tag_object": "3" * 40, "commit": "4" * 40}
    monkeypatch.setattr(rehearsal, "validate_local_release_pair", lambda *_args: (source, target))
    args = rehearsal.build_parser().parse_args(
        [
            "--action", "prepare", "--pi-host", "pi",
            "--source-release", source["tag"],
            "--target-release", target["tag"],
            "--source-wrapper", "/media/backup/source",
            "--expected-machine-id", "LC-TEST",
            "--operator", "Operator",
        ]
    )
    request = rehearsal.build_request(args, {"head": "5" * 40})
    assert request["bootstrap_runner_sha256"] == rehearsal.hashlib.sha256(
        rehearsal.BOOTSTRAP_RUNNER.read_bytes()
    ).hexdigest()
    assert "bootstrap_runner_b64" not in request


def test_structured_remote_failure_is_returned_without_private_error(monkeypatch):
    run_id = str(uuid4())
    response = {
        "status": "failed",
        "error": "Pi rehearsal update failed. Review the private Pi failure receipt.",
        "run_ids": [run_id],
        "pi_failure_receipts": [f"/private/{run_id}/failure.json"],
    }
    monkeypatch.setattr(
        rehearsal,
        "_run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1, stdout=json.dumps(response), stderr=""
        ),
    )
    args = rehearsal.build_parser().parse_args(
        ["--action", "status", "--pi-host", "pi", "--run-id", run_id]
    )
    assert rehearsal.invoke_remote(args, {}) == response


def test_legacy_updater_command_keeps_all_results_external(tmp_path):
    clone = tmp_path / "clone"
    evidence = tmp_path / "outside" / "evidence"
    command = rehearsal.remote_update_command(
        {"shared_python": "/protected/env/bin/python"},
        {"target_release": "v1.3.0-rc.7"},
        clone=clone,
        result_path=evidence / "result.json",
        log_path=evidence / "update.log",
    )
    assert command[:2] == [
        "/protected/env/bin/python", str(clone / "tools" / "update_and_restart.py")
    ]
    assert command[command.index("--target-release") + 1] == "v1.3.0-rc.7"
    assert "--no-relaunch" in command
    assert command[command.index("--latest-result-path") + 1].startswith(str(evidence))
    assert command[command.index("--log-path") + 1].startswith(str(evidence))
    assert not any(str(clone / "local") in item for item in command)


def test_public_tag_requires_an_annotated_peeled_ref(monkeypatch):
    monkeypatch.setattr(
        rehearsal,
        "remote_run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="1" * 40 + "\trefs/tags/v1.3.0-rc.7\n"
        ),
    )
    with pytest.raises(rehearsal.RehearsalError, match="not annotated"):
        rehearsal.remote_public_tag("https://example.invalid/repo.git", "v1.3.0-rc.7")


def test_source_wrapper_validation_and_copy_are_exact(tmp_path):
    wrapper = tmp_path / "source"
    local = wrapper / "local"
    local.mkdir(parents=True)
    (wrapper / "VERSION").write_text("v1.2.0-rc.6\n", encoding="utf-8")
    for name in ("Locations.json", "Obstacles.json", "Plates.json", "RegulatorProfiles.json", "Settings.json"):
        (local / name).write_text("{}\n", encoding="utf-8")
    original = rehearsal.remote_validate_source_wrapper(wrapper, "v1.2.0-rc.6")
    copied = rehearsal.remote_copy_tree(wrapper, tmp_path / "copy")
    assert copied["tree_sha256"] == original["tree_sha256"]
    with pytest.raises(rehearsal.RehearsalError, match="VERSION"):
        rehearsal.remote_validate_source_wrapper(wrapper, "v1.3.0-rc.1")


def test_malformed_required_source_configuration_is_rejected(tmp_path):
    wrapper = tmp_path / "source"
    local = wrapper / "local"
    local.mkdir(parents=True)
    (wrapper / "VERSION").write_text("v1.3.0-rc.1\n", encoding="utf-8")
    for name in ("Locations.json", "Obstacles.json", "Plates.json", "RegulatorProfiles.json", "Settings.json"):
        (local / name).write_text("{}\n", encoding="utf-8")
    (local / "Locations.json").write_text("not-json", encoding="utf-8")
    with pytest.raises(rehearsal.RehearsalError, match="Locations.json"):
        rehearsal.remote_validate_source_wrapper(wrapper, "v1.3.0-rc.1")


def test_state_transition_is_revisioned_and_replay_is_blocked(tmp_path):
    run_id = str(uuid4())
    run_root = tmp_path / run_id
    run_root.mkdir()
    state = {
        "schema_name": rehearsal.STATE_SCHEMA,
        "schema_version": rehearsal.STATE_SCHEMA_VERSION,
        "run_id": run_id,
        "revision": 0,
        "stage": "prepared",
    }
    rehearsal._remote_atomic_json(run_root / "state.json", state)
    updated = rehearsal.remote_advance_state(
        run_root, state, action="update", stage="updated", details={"passed": True}
    )
    assert updated["revision"] == 1
    assert (run_root / "receipts" / "001_update.json").is_file()
    with pytest.raises(rehearsal.RehearsalError, match="already exists"):
        rehearsal.remote_write_receipt(run_root, updated, "update", {})


def test_state_load_rejects_revision_mismatch_and_failed_run_reuse(tmp_path):
    run_id = str(uuid4())
    run_root = tmp_path / run_id
    run_root.mkdir()
    state = {
        "schema_name": rehearsal.STATE_SCHEMA,
        "schema_version": rehearsal.STATE_SCHEMA_VERSION,
        "run_id": run_id,
        "revision": 0,
        "stage": "prepared",
        "last_action": "prepare",
    }
    rehearsal.remote_write_receipt(run_root, state, "prepare", {})
    rehearsal._remote_atomic_json(run_root / "state.json", state)
    assert rehearsal.remote_load_state(tmp_path, run_id)["stage"] == "prepared"
    corrupted = dict(state, revision=1)
    rehearsal._remote_atomic_json(run_root / "state.json", corrupted)
    with pytest.raises(rehearsal.RehearsalError, match="sequence"):
        rehearsal.remote_load_state(tmp_path, run_id)
    rehearsal._remote_atomic_json(run_root / "state.json", state)
    failures = run_root / "failures"
    failures.mkdir()
    (failures / "failure.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(rehearsal.RehearsalError, match="cannot be reused"):
        rehearsal.remote_load_state(tmp_path, run_id)
    assert rehearsal.remote_load_state(tmp_path, run_id, allow_failed=True)["stage"] == "prepared"


def test_invariant_check_binds_prepared_harness_before_remote_inspection(monkeypatch):
    monkeypatch.setattr(
        rehearsal,
        "remote_collect_invariants",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("mismatched harness inspected the Pi")
        ),
    )
    with pytest.raises(rehearsal.RehearsalError, match="harness commit"):
        rehearsal.remote_require_invariants(
            {"harness_commit": "b" * 40},
            {"harness_commit": "a" * 40},
        )


def test_migration_comparison_detects_exact_members_and_authorizations(tmp_path):
    run_root = tmp_path / "run"
    source = run_root / "source-wrapper" / "local"
    machine_data = run_root / "activation" / "machine-data"
    machine_uuid = str(uuid4())
    machine_root = machine_data / "machines" / machine_uuid
    config = machine_root / "config"
    metadata = machine_root / "metadata"
    update_history = machine_root / "update_history"
    for path in (source, config, metadata, update_history):
        path.mkdir(parents=True, exist_ok=True)
    documents = {
        "Locations.json": {
            "camera": {"X": 1, "Y": 2, "Z": 3},
            "pause": {"X": 4, "Y": 5, "Z": 6},
            "home": {"X": 500, "Y": 500, "Z": 500},
            "rack_position_Left": {"X": 7, "Y": 8, "Z": 9},
            "rack_position_Right": {"X": 10, "Y": 11, "Z": 12},
        },
        "Obstacles.json": {},
        "Plates.json": [
            {
                "name": "test-plate",
                "calibrations": {
                    "top_left": {"X": 20, "Y": 30, "Z": 40},
                    "top_right": {"X": 20, "Y": 60, "Z": 40},
                    "bottom_right": {"X": 50, "Y": 60, "Z": 40},
                    "bottom_left": {"X": 50, "Y": 30, "Z": 40},
                },
            }
        ],
        "RegulatorProfiles.json": {},
        "Settings.json": {"HARDWARE_PROFILE": "current"},
    }
    inventory = []
    for name, payload in documents.items():
        data = json.dumps(payload, indent=2).encode("utf-8") + b"\n"
        (source / name).write_bytes(data)
        (config / name).write_bytes(data)
        inventory.append(
            {
                "relative_path": f"config/{name}",
                "size": len(data),
                "raw_sha256": rehearsal.hashlib.sha256(data).hexdigest(),
            }
        )
    (machine_data / "active_machine.json").write_text(
        json.dumps({"machine_uuid": machine_uuid}), encoding="utf-8"
    )
    migration_id = str(uuid4())
    archive = machine_root / "backups" / "migration" / migration_id / "source_backup.zip"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"verified archive bytes")
    required = {
        "machine_identity.json": {},
        "candidate_evidence.json": {"migratable_files": inventory},
        "migration_receipt.json": {
            "migration_id": migration_id,
            "backup_archive_sha256": rehearsal.remote_file_sha256(archive),
        },
        "migration_tree_manifest.json": {},
        "verification.json": {
            "targets": {
                "location:camera": {"state": "verified_from_trusted_existing_calibration"}
            },
            "ownership_decisions": [
                {"relative_path": "CalibrationMemory", "activation_allowed": True}
            ],
        },
        "activation_receipt.json": {},
    }
    for name, payload in required.items():
        (metadata / name).write_text(json.dumps(payload), encoding="utf-8")
    (update_history / "deployment_anchor.json").write_text(
        json.dumps({"app_version": "v1.3.0-rc.7", "app_commit": "a" * 40}),
        encoding="utf-8",
    )
    result = rehearsal.remote_compare_migration(
        run_root,
        {"target_release": "v1.3.0-rc.7", "target_commit": "a" * 40},
    )
    assert result["migrated_member_count"] == 5
    assert result["authorization_count"] == 1
    assert result["ownership_decision_count"] == 1
    assert result["calibrated_plate_count"] == 1
    (config / "Locations.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(rehearsal.RehearsalError, match="differs from source"):
        rehearsal.remote_compare_migration(
            run_root,
            {"target_release": "v1.3.0-rc.7", "target_commit": "a" * 40},
        )


def test_sanitized_response_contains_no_identity_coordinates_or_private_paths():
    state = {
        "run_id": str(uuid4()),
        "stage": "verified",
        "revision": 4,
        "source_release": "v1.2.0-rc.6",
        "source_commit": "1" * 40,
        "target_release": "v1.3.0-rc.7",
        "target_commit": "2" * 40,
        "source_tree": {"file_count": 10, "total_size": 20, "tree_sha256": "3" * 64},
        "protected_invariants_sha256": "4" * 64,
        "expected_machine_id": "PRIVATE-MACHINE",
    }
    payload = rehearsal.remote_sanitized(state)
    text = json.dumps(payload)
    assert "PRIVATE-MACHINE" not in text
    assert "source_wrapper" not in text
    assert "camera" not in text.casefold()


def test_summarize_requires_two_distinct_run_ids():
    run_id = str(uuid4())
    args = rehearsal.build_parser().parse_args(
        ["--action", "summarize", "--pi-host", "pi", "--run-id", run_id, "--run-id", run_id]
    )
    with pytest.raises(rehearsal.RehearsalError, match="distinct"):
        rehearsal._validate_cli(args)


def test_remote_failure_response_does_not_echo_private_error(capsys):
    private_text = "/media/private-backup/Camera-12345"
    encoded = __import__("base64").urlsafe_b64encode(
        json.dumps({"action": "unsupported", "remote_root": private_text}).encode("utf-8")
    ).decode("ascii")
    assert rehearsal.remote_main(encoded) == 1
    output = capsys.readouterr().out
    assert private_text not in output
    assert "private Pi failure receipt" in output
