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


def test_missing_anchor_cannot_be_reenrolled_by_later_release(tmp_path):
    context = _active_context(tmp_path)
    paths = context.paths
    paths.deployment_anchor_path.unlink()
    with pytest.raises(MachineDataUpdateError, match="Only the reviewed"):
        validate_or_enroll_deployment(
            paths,
            context.active_machine,
            context.configuration_lock,
            app_version="v1.3.0-rc.3",
            app_commit="3" * 40,
            release_contract=CONTRACT,
        )
    context.close()


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
