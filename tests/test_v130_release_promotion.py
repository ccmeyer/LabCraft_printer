"""Qualify final stable metadata with immutable clients and real bootstrap paths."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

import MachineDataBootstrap
from MachineDataMigration import load_migration_receipt
from MachineDataUpdate import MachineDataUpdateError
from tools import update_and_restart as updater
from tests import test_legacy_bridge_software_qualification as legacy
from tests.test_machine_data_update_preservation import _active_context
from tests.machine_data_migration_helpers import machine_data_paths
from tests.test_update_and_restart import FakeGitRunner, _write_version

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v1.3.0"


def _manifest():
    return json.loads((ROOT / "releases/v1.3.0.json").read_text(encoding="utf-8"))


def _inventory(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("source_version", legacy.LEGACY_SOURCES)
@pytest.mark.parametrize("channel", ["stable", "release_candidate"])
def test_immutable_clients_resolve_final_stable_or_existing_rc_bridge(tmp_path, source_version, channel):
    machine, bridge_commit, bundle, nested = legacy._build_world(tmp_path, source_version)
    author = tmp_path / "author"
    for relative in ("VERSION", "releases/latest.json", "releases/v1.3.0.json"):
        (author / relative).write_bytes((ROOT / relative).read_bytes())
    legacy._git(author, "add", ".")
    legacy._git(author, "commit", "-m", "Owned final stable qualification target")
    final_commit = legacy._git(author, "rev-parse", "HEAD")
    legacy._git(author, "tag", "-a", VERSION, "-m", "Owned synthetic final tag")
    legacy._run(["git", "push", str(tmp_path / "origin.git"), "main", "--tags"], cwd=author)
    before = _inventory(machine / "local")
    result = legacy._run(
        [sys.executable, str(machine / "tools/update_and_restart.py"),
         "--repo-root", str(machine), "--release-channel", channel,
         "--no-relaunch", "--log-path", str(tmp_path / "evidence/updater.log")], cwd=machine,
    )
    assert "Status: updated" in result.stdout
    expected_commit = final_commit if channel == "stable" else bridge_commit
    assert legacy._git(machine, "rev-parse", "HEAD") == expected_commit
    assert (machine / "VERSION").read_text().strip() == (VERSION if channel == "stable" else legacy.BRIDGE_VERSION)
    assert _inventory(machine / "local") == before
    assert (machine / "local/LabCraftUpdates/legacy.bundle").read_bytes() == bundle
    assert (machine / "local/LabCraftUpdates/nested/legacy.json").read_bytes() == nested
    assert legacy._git(machine, "status", "--porcelain") == ""


@pytest.mark.parametrize("source_version", legacy.LEGACY_SOURCES)
def test_final_manifest_authorizes_only_reviewed_legacy_enrollment(tmp_path, source_version):
    manifest = _manifest()
    context = _active_context(
        tmp_path, app_version=VERSION, app_commit="3" * 40,
        cohort="v1.2.0-rc.6" if source_version == "v1.2.0" else source_version,
        source_version=source_version, release_contract=manifest["machine_data"],
        update_compatibility=manifest["update_compatibility"],
    )
    try:
        assert load_migration_receipt(context.paths.migration_receipt_path).source_version == source_version
        anchor = json.loads(context.paths.deployment_anchor_path.read_text())
        assert anchor["app_version"] == VERSION
        assert anchor["app_commit"] == "3" * 40
        assert context.paths.base.active_machine_path.is_file()
        assert context.migration.backup.archive_path.is_file()
    finally:
        context.close()


@pytest.mark.parametrize("defect", ["missing", "undeclared", "wildcard"])
def test_final_legacy_enrollment_refuses_invalid_authority_before_publication(tmp_path, monkeypatch, defect):
    manifest = _manifest()
    compatibility = manifest["update_compatibility"]
    if defect == "missing":
        compatibility = None
        monkeypatch.setattr(MachineDataBootstrap, "load_current_release_update_compatibility",
                            lambda *args: None)
    elif defect == "undeclared":
        compatibility["direct_legacy_sources"] = ["v1.2.0"]
    else:
        compatibility["direct_legacy_sources"] = ["v1.3.0-rc.*"]
    with pytest.raises((MachineDataBootstrap.BootstrapError, MachineDataUpdateError)):
        _active_context(
            tmp_path, app_version=VERSION, app_commit="3" * 40,
            cohort="v1.3.0-rc.1", release_contract=manifest["machine_data"],
            update_compatibility=compatibility,
        )
    base, paths = machine_data_paths(tmp_path)
    assert not base.active_machine_path.exists()
    assert not paths.deployment_anchor_path.exists()


def test_final_release_has_no_automatic_historical_rollback(tmp_path):
    manifest = _manifest()
    assert manifest["rollback_version"] is None
    repo = tmp_path / "checkout"
    repo.mkdir()
    _write_version(repo, VERSION)
    runner = FakeGitRunner(repo, target_release_version=VERSION, release_manifest_payload=manifest)
    result = updater.run_rollback_check(
        updater.UpdaterConfig(repo_root=repo, no_relaunch=True, log_path=tmp_path / "rollback.log"),
        command_runner=runner,
    )
    assert result.status == updater.STATUS_ROLLBACK_NOT_CONFIGURED
    assert not any("merge" in args or "reset" in args for args, *_ in runner.calls)
