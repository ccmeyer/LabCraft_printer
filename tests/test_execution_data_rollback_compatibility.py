"""Real release selection and installation against isolated Git repositories."""
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from tools import update_and_restart as updater
from tools import create_update_bundle
from tests.test_update_and_restart import _git


POLICY_PATH = "FreeRTOS-interface/execution_data_compatibility.json"
POLICY = {
    "schema_name": "labcraft.execution_data_compatibility",
    "schema_version": 1,
    "capabilities": ["execution_calibrations_v4", "execution_volume_budget_v1"],
    "required_capabilities": ["execution_calibrations_v4", "execution_volume_budget_v1"],
}


def _release(repo, version, rollback, policy, *, schema="labcraft_release_v1", channel="stable"):
    (repo / "VERSION").write_text(version + "\n")
    releases = repo / "releases"
    releases.mkdir(exist_ok=True)
    manifest = {
        "schema_version": schema, "version": version, "tag": version,
        "channel": channel, "release_date": "2026-09-08",
        "previous_version": rollback, "rollback_version": rollback,
        "requires_firmware": None, "summary": "Compatibility test release",
        "notes": [], "validation": ["isolated Git workflow"],
        "machine_data": {"preservation_contract": "labcraft.machine_data_update.v1",
                         "data_schema_version": 1, "transition": "none", "transition_id": None},
    }
    (releases / (version + ".json")).write_text(json.dumps(manifest))
    (releases / "latest.json").write_text(json.dumps({
        "schema_version": "labcraft_release_index_v1", "stable": version,
        "release_candidate": None, "releases": [version]}))
    if policy is not None:
        path = repo / POLICY_PATH
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(policy))
        for name in ["ExecutionCalibrationStore.py", "ExecutionPlan.py", "ExperimentAuditLog.py"]:
            (path.parent / name).write_bytes((Path(__file__).parents[1] / "FreeRTOS-interface" / name).read_bytes())
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", version)
    _git(repo, "tag", "-a", version, "-m", version)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _repositories(tmp_path, *, target_policy=None):
    remote, source, deployed = (tmp_path / n for n in ["remote.git", "source", "deployed"])
    _git(tmp_path, "init", "--bare", str(remote))
    source.mkdir()
    _git(source, "init", "-b", "stable")
    _git(source, "config", "user.email", "test@example.com")
    _git(source, "config", "user.name", "Compatibility Test")
    _git(source, "remote", "add", "origin", str(remote))
    target = _release(source, "v9.0.1", "v9.0.0", target_policy)
    current = _release(source, "v9.0.2", "v9.0.1", POLICY)
    _git(source, "push", "-u", "origin", "stable", "--tags")
    _git(tmp_path, "clone", "--branch", "stable", str(remote), str(deployed))
    config = updater.UpdaterConfig(repo_root=deployed, no_relaunch=True,
        log_path=tmp_path / "updater.log", rollback=True)
    return source, deployed, target, current, config


def test_incompatible_rollback_is_unavailable_before_app_closes(tmp_path):
    _, repo, _, current, config = _repositories(tmp_path)
    result = updater.run_rollback_check(config)
    assert result.status == updater.STATUS_ROLLBACK_TARGET_INVALID
    assert "Reopen Current Version" in result.message
    assert "version-4" in result.message
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == current
    assert not _git(repo, "status", "--porcelain").stdout.strip()


@pytest.mark.parametrize("offline", [False, True])
def test_incompatible_apply_preserves_current_version_and_external_experiment(tmp_path, offline):
    source, repo, _, current, config = _repositories(tmp_path)
    experiment = tmp_path / "removable-experiment"
    experiment.mkdir()
    saved = experiment / "execution_calibrations.json"
    saved.write_text('{"schema_version":4,"sentinel":"never downgrade"}')
    before = saved.read_bytes()
    if offline:
        bundle = create_update_bundle.create_update_bundle(create_update_bundle.BundleConfig(
            repo_root=source, branch="stable", output_dir=tmp_path / "bundle", release="v9.0.1"))
        config = replace(config, offline_manifest_path=bundle.manifest_path)
    result = updater.run_rollback(config)
    assert result.status != updater.STATUS_ROLLED_BACK
    assert "version-4" in result.message
    assert result.safe_to_reopen_current
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == current
    assert saved.read_bytes() == before


def _protected_config(tmp_path, config, current, *, version="v9.0.2"):
    from MachineDataUpdate import build_update_launch_binding
    from tests.test_machine_data_update_preservation import _active_context, CONTRACT
    context = _active_context(tmp_path / "machine", app_version=version,
        app_commit=current, release_contract=CONTRACT, update_compatibility={
            "schema_version": "labcraft_update_compatibility_v1",
            "direct_legacy_sources": ["v1.3.0-rc.1"]})
    binding = build_update_launch_binding(context, source_app_version=version,
        source_commit=current, request_id="00000000-0000-0000-0000-000000000099")
    paths = context.paths
    context.close()
    return replace(config, machine_data_required=True, machine_data_root=binding.machine_data_root,
        machine_uuid=binding.machine_uuid, machine_id=binding.machine_id,
        activation_id=binding.activation_id, migration_id=binding.migration_id,
        active_pointer_sha256=binding.active_pointer_sha256,
        source_app_version=binding.source_app_version, source_commit=binding.source_commit,
        update_request_id=binding.request_id), paths


@pytest.mark.parametrize("compatible", [False, True])
def test_calibrate_save_rollback_reopen_and_resume(tmp_path, experiment_model_factory, compatible):
    from tests.test_execution_calibration_volume_budget import _captured_execution, MEASURED_VOLUME
    from tests.test_execution_two_stock_workflow import _apply, _print, _reload, _files
    _, repo, target, current, config = _repositories(tmp_path, target_policy=POLICY if compatible else None)
    # Start as the earlier installed release, then perform the real protected
    # forward update before producing a version-4 calibration document.
    _git(repo, "reset", "--hard", target)
    config, paths = _protected_config(tmp_path, config, target, version="v9.0.1")
    update = updater.run_update(replace(config, rollback=False))
    assert update.status == updater.STATUS_UPDATED
    assert update.relaunch_authorized and update.after_sha == current
    config = replace(config, source_app_version="v9.0.2", source_commit=current,
        update_request_id="00000000-0000-0000-0000-000000000100")
    model, em = _captured_execution(experiment_model_factory)
    plan = em.get_execution_plan_snapshot()
    high = next(s for s in plan.stocks if s.stock_id == "reagent-1_1111.11_mM")
    low = next(s for s in plan.stocks if s.stock_id == "reagent-1_27.78_mM")
    _apply(em, high, MEASURED_VOLUME)
    _print(em, high.stock_id, partial=True)
    files = _files(em)
    assert json.loads(Path(em.execution_calibrations_file_path).read_text())["schema_version"] == 4
    result = updater.run_rollback(config)
    assert _files(em) == files
    assert result.status == (updater.STATUS_ROLLED_BACK if compatible else updater.STATUS_ROLLBACK_TARGET_INVALID)
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == (target if compatible else current)
    if compatible:
        assert result.relaunch_authorized
        anchor = json.loads(paths.deployment_anchor_path.read_text())
        assert anchor["app_commit"] == target
        assert result.machine_data_evidence_path.is_file()
    # Read the saved v4 records with the reader actually present after install,
    # in a fresh interpreter so cached modules cannot mask an old reader.
    reader = subprocess.run([sys.executable, "-B", "-c",
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from ExecutionCalibrationStore import load_execution_calibrations; "
        "d=load_execution_calibrations(sys.argv[2]); assert d.records",
        str(repo / "FreeRTOS-interface"), em.execution_calibrations_file_path],
        capture_output=True, text=True)
    assert reader.returncode == 0, reader.stderr
    resumed, restored = _reload(experiment_model_factory, em)
    # Real revision validation still fixes the partially printed companion map.
    _apply(restored, low, 8.8)
    _print(restored, low.stock_id)
    assert restored.get_execution_plan_snapshot().plan_revision > plan.plan_revision


@pytest.mark.parametrize("policy", [
    {**POLICY, "capabilities": ["execution_calibrations_v4"], "required_capabilities": ["execution_calibrations_v4"]},
    {**POLICY, "required_capabilities": ["execution_calibrations_v4"]},
    {**POLICY, "schema_version": True},
    {**POLICY, "schema_version": 2},
    {**POLICY, "unknown": True},
])
def test_incomplete_or_invalid_target_contract_is_not_available(tmp_path, policy):
    _, repo, _, current, config = _repositories(tmp_path, target_policy=policy)
    assert updater.run_rollback_check(config).status == updater.STATUS_ROLLBACK_TARGET_INVALID
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == current


def test_shipped_contract_matches_calibration_reader_and_allocation_policy():
    from ExecutionCalibrationStore import SCHEMA_VERSION
    from Model import EXECUTION_CALIBRATION_ALLOCATION_POLICY
    payload = json.loads((Path(__file__).parents[1] / POLICY_PATH).read_text())
    supported, required = updater._parse_execution_data_compatibility(payload)
    assert f"execution_calibrations_v{SCHEMA_VERSION}" in required <= supported
    assert EXECUTION_CALIBRATION_ALLOCATION_POLICY in required


@pytest.mark.parametrize("receipt_failure", [False, True])
def test_late_read_failure_closes_transaction_without_install(tmp_path, monkeypatch, receipt_failure):
    from MachineDataUpdate import PreparedUpdate
    _, repo, target, current, config = _repositories(tmp_path, target_policy=POLICY)
    config, paths = _protected_config(tmp_path, config, current)
    anchor = paths.deployment_anchor_path.read_bytes()
    target_reads = 0
    commands = []

    def runner(args, cwd, timeout_s, env):
        nonlocal target_reads
        commands.append(tuple(args))
        if tuple(args)[-2:] == ("show", f"{target}:{POLICY_PATH}"):
            target_reads += 1
            if target_reads == 2:
                return updater.CommandResult(tuple(args), 1, stderr="injected target read failure")
        return updater.default_command_runner(args, cwd, timeout_s, env)

    if receipt_failure:
        def fail_receipt(*args, **kwargs):
            raise OSError("injected receipt write failure")
        monkeypatch.setattr(PreparedUpdate, "fail", fail_receipt)
    result = updater.run_rollback(config, command_runner=runner)
    assert target_reads == 2
    assert result.status == (updater.STATUS_RECOVERY_REQUIRED if receipt_failure else updater.STATUS_ROLLBACK_TARGET_INVALID)
    assert result.safe_to_reopen_current is (not receipt_failure)
    assert not result.relaunch_authorized
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == current
    assert paths.deployment_anchor_path.read_bytes() == anchor
    assert not any("reset" in c or "merge" in c for c in commands)
    # The real transaction and verified backup exist even though Git never ran.
    transaction = paths.update_history_root / "transactions" / config.update_request_id
    assert (transaction / "03_backup_verification.json").is_file()
    if not receipt_failure:
        assert result.machine_data_evidence_path.is_file()


def test_compatible_install_uses_verified_sha_not_mutable_ref(tmp_path):
    _, repo, target, _, config = _repositories(tmp_path, target_policy=POLICY)
    commands = []
    def runner(args, cwd, timeout_s, env):
        commands.append(tuple(args))
        return updater.default_command_runner(args, cwd, timeout_s, env)
    result = updater.run_rollback(config, command_runner=runner)
    assert result.status == updater.STATUS_ROLLED_BACK
    assert any(c[-3:] == ("reset", "--hard", target) for c in commands)
    assert not any(c[-3:] == ("reset", "--hard", "v9.0.1") for c in commands)
    assert any(c[-2:] == ("show", f"{target}:releases/v9.0.1.json") for c in commands)
    assert not any(c[-2:] == ("show", "v9.0.1:releases/v9.0.1.json") for c in commands)


def test_worker_disables_incompatible_rollback_and_updater_offers_reopen(tmp_path, qapp):
    from Controller import AppRollbackCheckWorker
    from View import SpeedProfilesTab
    from tests.test_app_update_request import _make_speed_tab_for_update_check
    from tools.update_window import UpdaterWindow
    _, repo, _, current, config = _repositories(tmp_path)
    worker = AppRollbackCheckWorker(repo)
    # Use an explicit offline path so this test does not enumerate removable media.
    source = tmp_path / "source"
    bundle = create_update_bundle.create_update_bundle(create_update_bundle.BundleConfig(
        repo_root=source, branch="stable", output_dir=tmp_path / "bundle", release="v9.0.1"))
    worker.offline_manifest_path = bundle.manifest_path
    results = []
    worker.finished.connect(results.append)
    worker.run()
    assert len(results) == 1
    tab = _make_speed_tab_for_update_check()
    SpeedProfilesTab._on_app_update_check_finished(tab, results[0])
    assert not tab.app_rollback_button.enabled
    assert "Reopen Current Version" in tab.app_update_status_label.text_value
    # Real backend refusal after app closure, then real Qt recovery control.
    result = updater.run_rollback(config)
    launches = []
    window = UpdaterWindow(replace(config, no_relaunch=False), auto_start=False,
        auto_close_on_launch=False, launcher=lambda cmd, cwd: launches.append((cmd, cwd)))
    window.handle_finished(result)
    assert not window.reopen_button.isHidden()
    window.reopen_button.click()
    assert len(launches) == 1 and Path(launches[0][1]) == repo
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == current
    window.close()


@pytest.mark.parametrize("offline", [False, True])
def test_update_path_also_refuses_incompatible_target(tmp_path, offline):
    source, repo, _, current, config = _repositories(tmp_path)
    config = replace(config, rollback=False, target_release="v9.0.1")
    if offline:
        bundle = create_update_bundle.create_update_bundle(create_update_bundle.BundleConfig(
            repo_root=source, branch="stable", output_dir=tmp_path / "bundle", release="v9.0.1"))
        config = replace(config, offline_manifest_path=bundle.manifest_path)
    check = updater.run_update_check(config)
    assert check.status != updater.STATUS_UPDATE_AVAILABLE
    assert "version-4" in check.message
    result = updater.run_update(config)
    assert result.status != updater.STATUS_UPDATED
    assert "version-4" in result.message
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == current


def test_offline_selection_is_rechecked_after_preview(tmp_path):
    source, repo, _, current, config = _repositories(tmp_path)
    bundle_root = tmp_path / "bundles"
    bundles = [create_update_bundle.create_update_bundle(create_update_bundle.BundleConfig(
        repo_root=source, branch="stable", output_dir=bundle_root, release=version))
        for version in ["v9.0.2", "v9.0.1"]]
    selected = bundle_root / "selected.json"
    selected.write_bytes(bundles[0].manifest_path.read_bytes())
    config = replace(config, offline_manifest_path=selected)
    assert updater.run_rollback_check(config).status == updater.STATUS_ROLLBACK_AVAILABLE
    # A changed USB selection remains a valid bundle, but is no longer compatible.
    selected.write_bytes(bundles[1].manifest_path.read_bytes())
    result = updater.run_rollback(config)
    assert result.status == updater.STATUS_ROLLBACK_TARGET_INVALID
    assert "version-4" in result.message and result.safe_to_reopen_current
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == current


def test_compatible_offline_rollback_remains_available(tmp_path):
    source, repo, target, _, config = _repositories(tmp_path, target_policy=POLICY)
    bundle = create_update_bundle.create_update_bundle(create_update_bundle.BundleConfig(
        repo_root=source, branch="stable", output_dir=tmp_path / "bundle", release="v9.0.1"))
    config = replace(config, offline_manifest_path=bundle.manifest_path)
    assert updater.run_rollback_check(config).status == updater.STATUS_ROLLBACK_AVAILABLE
    result = updater.run_rollback(config)
    assert result.status == updater.STATUS_ROLLED_BACK
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == target


@pytest.mark.parametrize("incremental", [False, True])
@pytest.mark.parametrize("schema", ["labcraft_release_v1", "labcraft_release_v2"])
def test_rc_bundle_protected_install_and_current_version_recovery(tmp_path, incremental, schema):
    source, repo, _, current, config = _repositories(tmp_path)
    version = "v9.1.0-rc.1"
    target = _release(source, version, None, POLICY, schema=schema, channel="release_candidate")
    _git(source, "push", "origin", "stable", "--tags")
    bundle = create_update_bundle.create_update_bundle(create_update_bundle.BundleConfig(
        repo_root=source, output_dir=tmp_path / "rc-bundle", release=version,
        since=current if incremental else None))
    assert bundle.manifest["head_sha"] == target
    assert bundle.manifest["release_manifest"]["rollback_version"] is None
    config, paths = _protected_config(tmp_path, config, current)
    config = replace(config, rollback=False, offline_manifest_path=bundle.manifest_path)
    result = updater.run_update(config)
    assert result.status == updater.STATUS_UPDATED, result.message
    assert result.after_sha == target and result.relaunch_authorized
    assert json.loads(paths.deployment_anchor_path.read_text())["app_commit"] == target
    assert updater.run_rollback_check(replace(config, offline_manifest_path=None)).status == updater.STATUS_ROLLBACK_NOT_CONFIGURED
    # Recovery uses the same compatible package and the protected receipt path.
    result = updater.run_rollback(replace(config, rollback=True, source_commit=target,
        source_app_version=version, update_request_id="00000000-0000-0000-0000-000000000101"))
    assert result.status == updater.STATUS_ALREADY_CURRENT, result.message
    assert result.after_sha == target and result.relaunch_authorized


def test_packaging_ref_change_cannot_publish_mismatched_manifest(tmp_path):
    source, _, _, current, _ = _repositories(tmp_path, target_policy=POLICY)
    def runner(args, cwd):
        if tuple(args)[1:3] == ("bundle", "create"):
            # Simulate another process changing a synthetic test ref while packing.
            _git(source, "update-ref", "refs/tags/v9.0.1", current)
        return create_update_bundle.default_command_runner(args, cwd)
    output = tmp_path / "raced-bundle"
    with pytest.raises(create_update_bundle.BundleCreateError, match="resolved commit"):
        create_update_bundle.create_update_bundle(create_update_bundle.BundleConfig(
            repo_root=source, output_dir=output, release="v9.0.1"), command_runner=runner)
    assert not list(output.glob("*.json"))
