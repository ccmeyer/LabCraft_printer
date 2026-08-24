import json

import pytest

from MachineDataBootstrap import BootstrapError, MachineDataBootstrap
from MachineDataUpdate import MachineDataUpdateError, validate_or_enroll_deployment
from tests.test_machine_data_update_preservation import (
    CONTRACT,
    SOURCE_COMMIT,
    _active_context,
)


def test_authorized_deployment_anchor_reopens_same_external_machine(tmp_path):
    context = _active_context(tmp_path)
    base = context.paths.base
    expected_uuid = context.identity.machine_uuid
    context.close()

    reopened = MachineDataBootstrap(
        base,
        app_version="v1.3.0-rc.2",
        app_commit=SOURCE_COMMIT,
        release_contract=CONTRACT,
    ).open_ready()
    try:
        assert reopened.identity.machine_uuid == expected_uuid
        assert reopened.deployment_anchor["authorization_kind"] == "genesis"
    finally:
        reopened.close()


def test_manual_commit_change_is_recovery_before_context_open(tmp_path):
    context = _active_context(tmp_path)
    base = context.paths.base
    context.close()

    bootstrap = MachineDataBootstrap(
        base,
        app_version="v1.3.0-rc.2",
        app_commit="9" * 40,
        release_contract=CONTRACT,
    )
    with pytest.raises(BootstrapError, match="not authorized"):
        bootstrap.open_ready()


def test_rc2_short_genesis_commit_reopens_with_exact_full_commit(tmp_path):
    context = _active_context(tmp_path)
    base = context.paths.base
    anchor_path = context.paths.deployment_anchor_path
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    anchor["app_commit"] = SOURCE_COMMIT[:12]
    anchor_path.write_text(json.dumps(anchor), encoding="utf-8")
    context.close()

    reopened = MachineDataBootstrap(
        base,
        app_version="v1.3.0-rc.2",
        app_commit=SOURCE_COMMIT,
        release_contract=CONTRACT,
    ).open_ready()
    try:
        assert reopened.deployment_anchor["app_commit"] == SOURCE_COMMIT[:12]
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "recorded_commit",
    [
        SOURCE_COMMIT[:11],
        SOURCE_COMMIT[:11] + "2",
        "ABCDEFABCDEF",
        "not-a-commit",
    ],
)
def test_legacy_anchor_compatibility_rejects_nonexact_prefixes(tmp_path, recorded_commit):
    context = _active_context(tmp_path)
    base = context.paths.base
    anchor_path = context.paths.deployment_anchor_path
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    anchor["app_commit"] = recorded_commit
    anchor_path.write_text(json.dumps(anchor), encoding="utf-8")
    context.close()

    with pytest.raises(BootstrapError, match="not authorized"):
        MachineDataBootstrap(
            base,
            app_version="v1.3.0-rc.2",
            app_commit=SOURCE_COMMIT,
            release_contract=CONTRACT,
        ).open_ready()


def test_missing_anchor_cannot_be_reenrolled_by_later_release(tmp_path):
    context = _active_context(tmp_path)
    paths = context.paths
    paths.deployment_anchor_path.unlink()
    with pytest.raises(MachineDataUpdateError, match="Genesis enrollment"):
        validate_or_enroll_deployment(
            paths,
            context.active_machine,
            context.configuration_lock,
            app_version="v1.3.0-rc.3",
            app_commit="3" * 40,
            release_contract=CONTRACT,
        )
    context.close()


def test_rc3_direct_first_start_can_create_genesis_anchor(tmp_path):
    context = _active_context(
        tmp_path,
        app_version="v1.3.0-rc.3",
        app_commit="3" * 40,
    )
    try:
        assert context.deployment_anchor["authorization_kind"] == "genesis"
        assert context.deployment_anchor["app_version"] == "v1.3.0-rc.3"
        assert context.deployment_anchor["app_commit"] == "3" * 40
    finally:
        context.close()


@pytest.mark.parametrize("cohort", ("v1.2.0-rc.6", "v1.3.0-rc.1"))
def test_rc8_direct_first_start_creates_exact_legacy_genesis_anchor(
    tmp_path, cohort
):
    commit = "8" * 40
    context = _active_context(
        tmp_path,
        app_version="v1.3.0-rc.8",
        app_commit=commit,
        cohort=cohort,
        release_contract=CONTRACT,
    )
    try:
        assert context.deployment_anchor["authorization_kind"] == "genesis"
        assert context.deployment_anchor["app_version"] == "v1.3.0-rc.8"
        assert context.deployment_anchor["app_commit"] == commit
    finally:
        context.close()


def test_rc8_missing_anchor_cannot_be_reenrolled_during_ordinary_startup(tmp_path):
    commit = "8" * 40
    context = _active_context(
        tmp_path,
        app_version="v1.3.0-rc.8",
        app_commit=commit,
        release_contract=CONTRACT,
    )
    base = context.paths.base
    anchor_path = context.paths.deployment_anchor_path
    context.close()
    anchor_path.unlink()

    bootstrap = MachineDataBootstrap(
        base,
        app_version="v1.3.0-rc.8",
        app_commit=commit,
        release_contract=CONTRACT,
    )
    inspection = bootstrap.inspect()

    assert inspection.state.value == "recovery_required"
    assert "ordinary startup" in inspection.issues[0].message
    with pytest.raises(BootstrapError, match="current reviewed activation"):
        bootstrap.open_ready()
    assert not anchor_path.exists()


def test_unfinished_update_transaction_blocks_bootstrap(tmp_path):
    context = _active_context(tmp_path)
    base = context.paths.base
    transaction = context.paths.update_transactions_root / "00000000-0000-0000-0000-000000000088"
    transaction.mkdir(parents=True)
    (transaction / "01_intent.json").write_text(json.dumps({"stage": "requested"}), encoding="utf-8")
    context.close()

    with pytest.raises(BootstrapError, match="requires recovery"):
        MachineDataBootstrap(
            base,
            app_version="v1.3.0-rc.2",
            app_commit=SOURCE_COMMIT,
            release_contract=CONTRACT,
        ).open_ready()
