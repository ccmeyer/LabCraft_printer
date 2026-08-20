"""Target-side, hardware-free machine-data schema transition recovery."""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping

from MachineData import parse_machine_identity
from MachineDataArchive import canonical_json_bytes, semantic_json_sha256, sha256_file
from MachineDataTransactions import ConfigurationTransactionService, read_governed_documents
from MachineDataUpdate import (
    MachineDataUpdateError,
    TRANSITION_BOOTSTRAP_RECOVERY,
    authorize_deployment_from_evidence,
    capture_protected_snapshot,
    verify_update_backup,
)
from MachineDataVerification import load_machine_verification


SCHEMA_TRANSITION_EVIDENCE_NAME = "labcraft.machine_data_schema_transition"
SCHEMA_TRANSITION_EVIDENCE_VERSION = 1
SYNTHETIC_REFORMAT_TRANSITION_ID = "synthetic.reformat-governed-json.v1"

SchemaAdapter = Callable[[Mapping[str, object]], Mapping[str, bytes]]


def _synthetic_reformat_adapter(
    documents: Mapping[str, object],
) -> Mapping[str, bytes]:
    # Intentionally changes representation while retaining the parsed value.
    payload = documents["Locations.json"]
    return {
        "Locations.json": (
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
            + b"\n"
        )
    }


TRANSITION_ADAPTERS: Mapping[str, SchemaAdapter] = MappingProxyType(
    {SYNTHETIC_REFORMAT_TRANSITION_ID: _synthetic_reformat_adapter}
)


def _target_semantics(snapshot) -> dict[str, object]:
    safety = snapshot.safety_snapshot
    targets = safety["targets"]
    return {
        "machine_id": safety["machine_id"],
        "machine_uuid": safety["machine_uuid"],
        "activation_id": safety["activation_id"],
        "migration_id": safety["migration_id"],
        "hardware_profile": safety["hardware_profile"],
        "governed_semantic_sha256": dict(safety["governed_semantic_sha256"]),
        "locations": safety["locations"],
        "plates": safety["plates"],
        "obstacles": safety["obstacles"],
        "targets": {
            key: {
                "kind": value["kind"],
                "source_file": value["source_file"],
                "value": value["value"],
                "authorization_state": value["authorization"]["state"],
                "authorization_value_sha256": value["authorization"]["value_sha256"],
            }
            for key, value in sorted(targets.items())
        },
    }


def complete_prepared_schema_transition(
    prepared,
    *,
    adapters: Mapping[str, SchemaAdapter] | None = None,
) -> Path:
    """Complete a declared transition while the updater owns both locks."""

    contract = prepared.target.machine_data_contract
    if contract.get("transition") != TRANSITION_BOOTSTRAP_RECOVERY:
        raise MachineDataUpdateError(
            "schema_transition_not_declared",
            "The target release does not declare bootstrap recovery.",
            recovery_required=True,
        )
    transition_id = str(contract.get("transition_id") or "")
    registry = TRANSITION_ADAPTERS if adapters is None else adapters
    adapter = registry.get(transition_id)
    if adapter is None:
        raise MachineDataUpdateError(
            "schema_transition_adapter_missing",
            f"No reviewed target-side adapter is registered for {transition_id!r}.",
            recovery_required=True,
        )
    if not prepared._git_applied:
        raise MachineDataUpdateError(
            "schema_transition_state_invalid",
            "Schema recovery cannot run before the verified target Git revision is active.",
            recovery_required=True,
        )
    verify_update_backup(prepared.archive_path, policy=prepared.policy)
    before = capture_protected_snapshot(prepared.paths, prepared.active, policy=prepared.policy)
    if before.fingerprint != prepared.snapshot.fingerprint:
        raise MachineDataUpdateError(
            "pre_transition_data_mismatch",
            "Protected bytes changed before target-side schema recovery.",
            recovery_required=True,
        )

    documents = read_governed_documents(prepared.paths)
    try:
        output = dict(adapter(MappingProxyType(dict(documents))))
    except Exception as exc:
        raise MachineDataUpdateError(
            "schema_transition_adapter_failed",
            f"Schema adapter failed before commit: {exc}",
            recovery_required=True,
        ) from exc
    identity = parse_machine_identity(
        json.loads(prepared.paths.identity_path.read_text(encoding="utf-8"))
    )
    verification = load_machine_verification(prepared.paths.verification_path)
    service = ConfigurationTransactionService(
        paths=prepared.paths,
        identity=identity,
        active=prepared.active,
        verification=verification,
        configuration_lock=prepared.configuration_lock,
        app_version=prepared.target.version,
        app_commit=prepared.target.commit,
        io=prepared.io,
        clock=prepared.clock,
    )
    prior_state = service.state
    result = service.commit_schema_transition(
        output,
        transition_id=transition_id,
        expected_config_sha256=prior_state.config_sha256,
    )
    after = capture_protected_snapshot(prepared.paths, prepared.active, policy=prepared.policy)
    if _target_semantics(after) != _target_semantics(prepared.snapshot):
        raise MachineDataUpdateError(
            "schema_transition_semantic_drift",
            "Schema recovery changed machine safety semantics.",
            recovery_required=True,
        )
    if result.state.sequence != prior_state.sequence + 1:
        raise MachineDataUpdateError(
            "schema_transition_audit_missing",
            "Schema recovery did not append exactly one configuration event.",
            recovery_required=True,
        )
    pointer_sha, _ = sha256_file(prepared.paths.base.active_machine_path)
    if pointer_sha != prepared.binding.active_pointer_sha256:
        raise MachineDataUpdateError(
            "schema_transition_authority_changed",
            "Active-machine authority changed during schema recovery.",
            recovery_required=True,
        )

    transition_path, _ = prepared._write_stage(
        "05b_schema_transition_verification.json",
        "schema_transition_verified",
        {
            "transition_schema_name": SCHEMA_TRANSITION_EVIDENCE_NAME,
            "transition_schema_version": SCHEMA_TRANSITION_EVIDENCE_VERSION,
            "transition_id": transition_id,
            "configuration_event_id": result.event_id,
            "configuration_sequence_before": prior_state.sequence,
            "configuration_sequence_after": result.state.sequence,
            "before_safety_snapshot_sha256": prepared.snapshot.safety_snapshot_sha256,
            "after_safety_snapshot_sha256": after.safety_snapshot_sha256,
            "semantic_safety_sha256": semantic_json_sha256(_target_semantics(after)),
        },
    )
    authorize_deployment_from_evidence(
        prepared.paths,
        prepared.active,
        prepared.configuration_lock,
        app_version=prepared.target.version,
        app_commit=prepared.target.commit,
        release_contract=contract,
        authorization_kind="schema_transition",
        update_id=prepared.update_id,
        authority_path=transition_path,
        io=prepared.io,
        clock=prepared.clock,
    )
    return prepared._write_terminal(
        status="relaunch_authorized",
        relaunch_authorized=True,
        recovery_required=False,
        message="Target-side schema transition and safety semantics were verified.",
    )


__all__ = [
    "SCHEMA_TRANSITION_EVIDENCE_NAME",
    "SCHEMA_TRANSITION_EVIDENCE_VERSION",
    "SYNTHETIC_REFORMAT_TRANSITION_ID",
    "TRANSITION_ADAPTERS",
    "complete_prepared_schema_transition",
]
