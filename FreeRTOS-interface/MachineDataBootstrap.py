"""Hardware-free production bootstrap for external machine data."""

from __future__ import annotations

import json
import shutil
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping
from uuid import UUID, uuid4

import LocalConfig
from ConfigurationSafetyPolicy import (
    ConfigurationChangeGuard,
    ConfigurationSafetyError,
    load_configuration_change_policy,
    parse_safety_bounds,
)
from MachineData import (
    ActiveMachine,
    ActiveMachineError,
    MachineDataBasePaths,
    MachineDataPaths,
    MachineIdentity,
    MachineIdentityError,
    UNASSIGNED_MACHINE_ID,
    build_machine_data_paths,
    parse_machine_identity,
    require_authorized_active_machine,
)
from MachineDataArchive import DurableFileOps, sha256_file
from MachineDataLock import (
    AcquiredConfigurationLock,
    ConfigurationLockUnavailable,
    MigrationLockUnavailable,
    acquire_configuration_lock,
    acquire_migration_lock,
)
from MachineDataMigration import (
    CandidateEvidence,
    CandidateSelection,
    MigrationPolicy,
    MigrationFileOps,
    MigrationRecoveryRequired,
    MigrationResult,
    PublishedMigrationEvidence,
    PublishedMigrationPhase,
    build_migration_workspace_paths,
    create_verified_backup,
    import_verified_candidate,
    inspect_candidate,
    reconcile_migration,
    verify_published_migration,
)
from MachineDataOwnership import (
    MachineDataOwnershipPolicy,
    OwnershipDecision,
    OwnershipPolicyError,
)
from MachineDataVerification import (
    ActivationReceipt,
    MachineVerification,
    SavedTargetAuthorizer,
    VerificationError,
    create_machine_verification,
    load_activation_receipt,
    load_machine_verification,
    utc_now,
    validate_verification_against_files,
    write_activation_receipt,
    write_machine_verification,
)
from MachineDataTransactions import (
    ConfigurationRecoveryRequired,
    ConfigurationState,
    ConfigurationTransactionService,
    build_active_tree_overrides,
    inspect_configuration_state,
    read_governed_documents,
)
from MachineDataUpdate import (
    MachineDataUpdateError,
    inspect_deployment_gate,
    load_current_release_machine_data_contract,
    load_current_release_update_compatibility,
    parse_release_update_compatibility,
    validate_or_enroll_deployment,
)


ACTIVATION_JOURNAL_SCHEMA_NAME = "labcraft.activation_journal"
ACTIVATION_JOURNAL_SCHEMA_VERSION = 1
ACTIVATION_ASSIGNMENT_SCHEMA_NAME = "labcraft.activation_identity_assignment"
ACTIVATION_ASSIGNMENT_SCHEMA_VERSION = 1


class BootstrapState(str, Enum):
    READY = "ready"
    NO_EXTERNAL_STORE = "no_external_store"
    CANDIDATE_SELECTION_REQUIRED = "candidate_selection_required"
    MIGRATION_RESUME_REQUIRED = "migration_resume_required"
    ACTIVATION_RESUME_REQUIRED = "activation_resume_required"
    RECOVERY_REQUIRED = "recovery_required"
    LOCK_UNAVAILABLE = "lock_unavailable"


class BootstrapError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class BootstrapIssue:
    code: str
    message: str
    fatal: bool = True


@dataclass(frozen=True)
class ActivationWorkspacePaths:
    base: MachineDataBasePaths
    machine_uuid: str
    activation_id: str
    root: Path
    assignment_path: Path
    journal_path: Path

    def __post_init__(self) -> None:
        machine_uuid = _canonical_uuid(self.machine_uuid, "machine_uuid")
        activation_id = _canonical_uuid(self.activation_id, "activation_id")
        expected = (
            self.base.activation_work_root / machine_uuid / activation_id
        ).resolve(strict=False)
        actual_root = Path(self.root).resolve(strict=False)
        if actual_root != expected:
            raise BootstrapError("unsafe_workspace", "Activation workspace escaped its base.")
        if Path(self.assignment_path).resolve(strict=False) != expected / "identity_assignment.json":
            raise BootstrapError("unsafe_workspace", "Assignment path is not contained.")
        if Path(self.journal_path).resolve(strict=False) != expected / "journal.json":
            raise BootstrapError("unsafe_workspace", "Journal path is not contained.")
        object.__setattr__(self, "machine_uuid", machine_uuid)
        object.__setattr__(self, "activation_id", activation_id)
        object.__setattr__(self, "root", actual_root)
        object.__setattr__(self, "assignment_path", expected / "identity_assignment.json")
        object.__setattr__(self, "journal_path", expected / "journal.json")


@dataclass(frozen=True)
class BootstrapInspection:
    state: BootstrapState
    base: MachineDataBasePaths
    active_machine: ActiveMachine | None = None
    machine_paths: MachineDataPaths | None = None
    issues: tuple[BootstrapIssue, ...] = ()
    allowed_actions: frozenset[str] = frozenset()


@dataclass(frozen=True)
class BootstrapSubmission:
    selection: CandidateSelection
    machine_id: str
    operator: str
    source_reason: str
    camera_confirmation: Mapping[str, object]
    service_record_reference: str | None = None
    machine_uuid: str | None = None
    activation_id: str | None = None


@dataclass(frozen=True)
class PublishedActivationSubmission:
    machine_uuid: str
    operator: str
    source_reason: str
    camera_confirmation: Mapping[str, object]
    service_record_reference: str | None = None
    activation_id: str | None = None


@dataclass(frozen=True)
class AuthorizedMachineContext:
    paths: MachineDataPaths
    identity: MachineIdentity
    active_machine: ActiveMachine
    migration: PublishedMigrationEvidence
    verification: MachineVerification
    activation_receipt: ActivationReceipt
    settings: Mapping[str, object]
    settings_raw_sha256: str
    saved_target_authorizer: object
    configuration_state: ConfigurationState
    configuration_transactions: ConfigurationTransactionService
    configuration_safety_guard: ConfigurationChangeGuard
    configuration_lock: AcquiredConfigurationLock
    deployment_anchor: Mapping[str, object] | None = None

    def close(self) -> None:
        self.configuration_lock.release()


def _canonical_uuid(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise BootstrapError("invalid_identity", f"{label} must be UUID text.")
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise BootstrapError("invalid_identity", f"{label} is invalid.") from exc


def build_activation_workspace_paths(
    base: MachineDataBasePaths,
    machine_uuid: str,
    activation_id: str,
) -> ActivationWorkspacePaths:
    root = (
        base.activation_work_root
        / _canonical_uuid(machine_uuid, "machine_uuid")
        / _canonical_uuid(activation_id, "activation_id")
    ).resolve(strict=False)
    return ActivationWorkspacePaths(
        base,
        machine_uuid,
        activation_id,
        root,
        root / "identity_assignment.json",
        root / "journal.json",
    )


class MachineDataBootstrap:
    """Orchestrate migration/activation without importing hardware or MVC modules."""

    def __init__(
        self,
        base: MachineDataBasePaths,
        *,
        app_version: str,
        app_commit: str,
        ownership_policy: MachineDataOwnershipPolicy | None = None,
        migration_policy: MigrationPolicy | None = None,
        clock: Callable[[], str] = utc_now,
        uuid_factory: Callable[[], object] = uuid4,
        io: DurableFileOps | None = None,
        release_contract: Mapping[str, object] | None = None,
        update_compatibility: Mapping[str, object] | None = None,
        deployment_gate_enabled: bool = True,
    ) -> None:
        self.base = base
        self.app_version = str(app_version or "").strip()
        self.app_commit = str(app_commit or "").strip()
        if not self.app_version or not self.app_commit:
            raise BootstrapError("missing_provenance", "App version and commit are required.")
        self.ownership_policy = ownership_policy or MachineDataOwnershipPolicy.load()
        self.migration_policy = migration_policy or MigrationPolicy()
        self.clock = clock
        self.uuid_factory = uuid_factory
        self._cancel_event = threading.Event()
        self.io = io or MigrationFileOps(fault_hook=self._cancel_checkpoint)
        if type(deployment_gate_enabled) is not bool:
            raise BootstrapError(
                "invalid_deployment_mode",
                "deployment_gate_enabled must be a boolean.",
            )
        self.deployment_gate_enabled = deployment_gate_enabled
        self.release_contract = None
        self.update_compatibility = None
        if deployment_gate_enabled:
            self.release_contract = (
                release_contract
                if release_contract is not None
                else load_current_release_machine_data_contract(
                    Path(__file__).resolve().parents[1],
                    self.app_version,
                )
            )
            self.update_compatibility = (
                parse_release_update_compatibility(update_compatibility, required=False)
                if update_compatibility is not None
                else load_current_release_update_compatibility(
                    Path(__file__).resolve().parents[1],
                    self.app_version,
                )
            )

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def reset_cancel(self) -> None:
        self._cancel_event.clear()

    def _cancel_checkpoint(self, _name: str, _path: Path) -> None:
        if self._cancel_event.is_set():
            raise BootstrapError(
                "bootstrap_cancelled",
                "Bootstrap cancellation was reconciled at a durability checkpoint.",
            )

    def inspect(self) -> BootstrapInspection:
        if self.base.active_machine_path.exists():
            try:
                payload = json.loads(self.base.active_machine_path.read_text(encoding="utf-8"))
                active = require_authorized_active_machine(payload)
                paths = build_machine_data_paths(self.base, active.machine_uuid)
                self._validate_active_without_lock(paths, active)
                return BootstrapInspection(
                    BootstrapState.READY,
                    self.base,
                    active_machine=active,
                    machine_paths=paths,
                    allowed_actions=frozenset({"open_ready"}),
                )
            except Exception as exc:
                return BootstrapInspection(
                    BootstrapState.RECOVERY_REQUIRED,
                    self.base,
                    issues=(BootstrapIssue("active_state_invalid", str(exc)),),
                    allowed_actions=frozenset({"exit", "copy_diagnostics"}),
                )

        roots = []
        if self.base.machines_root.is_dir():
            for child in self.base.machines_root.iterdir():
                if not child.is_dir():
                    continue
                try:
                    paths = build_machine_data_paths(self.base, child.name)
                except Exception:
                    return BootstrapInspection(
                        BootstrapState.RECOVERY_REQUIRED,
                        self.base,
                        issues=(BootstrapIssue("invalid_machine_directory", str(child)),),
                        allowed_actions=frozenset({"exit", "copy_diagnostics"}),
                    )
                roots.append(paths)
        if len(roots) > 1:
            return BootstrapInspection(
                BootstrapState.RECOVERY_REQUIRED,
                self.base,
                issues=(BootstrapIssue("multiple_machine_roots", "Multiple inactive canonical machine roots require support review."),),
                allowed_actions=frozenset({"exit", "copy_diagnostics"}),
            )
        if len(roots) == 1:
            paths = roots[0]
            try:
                phase = (
                    PublishedMigrationPhase.ACTIVATION_STAGED
                    if paths.verification_path.exists() or paths.activation_receipt_path.exists()
                    else PublishedMigrationPhase.COPIED_UNVERIFIED
                )
                verify_published_migration(paths, phase=phase)
                state = (
                    BootstrapState.ACTIVATION_RESUME_REQUIRED
                    if phase is PublishedMigrationPhase.ACTIVATION_STAGED
                    else BootstrapState.MIGRATION_RESUME_REQUIRED
                )
                return BootstrapInspection(
                    state,
                    self.base,
                    machine_paths=paths,
                    allowed_actions=frozenset({"resume_activation", "exit"}),
                )
            except Exception as exc:
                return BootstrapInspection(
                    BootstrapState.RECOVERY_REQUIRED,
                    self.base,
                    machine_paths=paths,
                    issues=(BootstrapIssue("published_state_invalid", str(exc)),),
                    allowed_actions=frozenset({"exit", "copy_diagnostics"}),
                )
        try:
            activation_workspaces = self._activation_workspaces()
        except BootstrapError as exc:
            return BootstrapInspection(
                BootstrapState.RECOVERY_REQUIRED,
                self.base,
                issues=(BootstrapIssue("activation_workspace_invalid", str(exc)),),
                allowed_actions=frozenset({"exit", "copy_diagnostics"}),
            )
        if len(activation_workspaces) > 1:
            return BootstrapInspection(
                BootstrapState.RECOVERY_REQUIRED,
                self.base,
                issues=(
                    BootstrapIssue(
                        "multiple_activation_workspaces",
                        "Multiple incomplete identity/activation assignments require support review.",
                    ),
                ),
                allowed_actions=frozenset({"exit", "copy_diagnostics"}),
            )
        if activation_workspaces:
            return BootstrapInspection(
                BootstrapState.CANDIDATE_SELECTION_REQUIRED,
                self.base,
                issues=(
                    BootstrapIssue(
                        "identity_assignment_resume",
                        "An incomplete bootstrap assignment was preserved. Reselect the same source to resume with the same machine identity.",
                        fatal=False,
                    ),
                ),
                allowed_actions=frozenset({"select_candidate", "exit"}),
            )
        return BootstrapInspection(
            BootstrapState.CANDIDATE_SELECTION_REQUIRED,
            self.base,
            allowed_actions=frozenset({"select_candidate", "exit"}),
        )

    def inspect_candidate(self, selection: CandidateSelection) -> CandidateEvidence:
        return inspect_candidate(
            selection,
            archive_policy=self.migration_policy.archive_policy,
            clock=self.clock,
        )

    def bootstrap_from_candidate(self, submission: BootstrapSubmission) -> AuthorizedMachineContext:
        self.reset_cancel()
        if self.base.active_machine_path.exists():
            raise BootstrapError("active_exists", "An active machine already exists; legacy fallback is forbidden.")
        candidate = self.inspect_candidate(submission.selection)
        if not candidate.is_importable:
            raise BootstrapError("invalid_source", "Selected candidate is not importable.")
        resume = self._resume_assignment(candidate, submission)
        if resume is None:
            identity = self._identity_for_submission(candidate, submission)
            activation_id = _canonical_uuid(
                submission.activation_id or str(self.uuid_factory()), "activation_id"
            )
            migration_id = str(self.uuid_factory())
            workspace = build_activation_workspace_paths(
                self.base, identity.machine_uuid, activation_id
            )
        else:
            workspace, identity, migration_id = resume
            activation_id = workspace.activation_id
        paths = build_machine_data_paths(self.base, identity.machine_uuid)
        if paths.machine_root.exists() and resume is None:
            raise BootstrapError("target_conflict", "Canonical target already exists; use activation resume.")
        migration_workspace = build_migration_workspace_paths(
            self.base, identity.machine_uuid, migration_id
        )
        with self._migration_lock(identity.machine_uuid) as migration_lock:
            self._write_assignment(workspace, identity, candidate, migration_id)
            self._write_journal(workspace, "identity_assigned", identity, migration_id)
            if paths.machine_root.exists() or migration_workspace.root.exists():
                result = reconcile_migration(
                    workspace=migration_workspace,
                    target_paths=paths,
                    acquired_lock=migration_lock,
                    io=self.io if isinstance(self.io, MigrationFileOps) else None,
                    policy=self.migration_policy,
                    clock=self.clock,
                )
            else:
                backup = create_verified_backup(
                    candidate,
                    workspace=migration_workspace,
                    target_identity=identity,
                    acquired_lock=migration_lock,
                    io=self.io if isinstance(self.io, MigrationFileOps) else None,
                    policy=self.migration_policy,
                    clock=self.clock,
                )
                result = import_verified_candidate(
                    candidate,
                    backup,
                    workspace=migration_workspace,
                    target_paths=paths,
                    target_identity=identity,
                    acquired_lock=migration_lock,
                    io=self.io if isinstance(self.io, MigrationFileOps) else None,
                    policy=self.migration_policy,
                    clock=self.clock,
                )
            self._write_journal(workspace, "migration_published", identity, result.receipt.migration_id)
            return self._activate_published_locked(
                paths,
                identity,
                operator=submission.operator,
                source_reason=submission.source_reason,
                camera_confirmation=submission.camera_confirmation,
                service_record_reference=submission.service_record_reference,
                activation_id=activation_id,
                workspace=workspace,
            )

    def activate_published(
        self, submission: PublishedActivationSubmission
    ) -> AuthorizedMachineContext:
        self.reset_cancel()
        if self.base.active_machine_path.exists():
            raise BootstrapError("active_exists", "An active pointer already exists.")
        paths = build_machine_data_paths(self.base, submission.machine_uuid)
        identity = self._load_identity(paths)
        resume_activation_id = self._find_resume_activation_id(identity.machine_uuid)
        if paths.activation_receipt_path.exists():
            try:
                recorded_activation_id = load_activation_receipt(
                    paths.activation_receipt_path
                ).activation_id
            except VerificationError as exc:
                raise BootstrapError("recovery_required", str(exc)) from exc
            if resume_activation_id and resume_activation_id != recorded_activation_id:
                raise BootstrapError(
                    "recovery_required",
                    "Activation receipt and workspace identify different activations.",
                )
            resume_activation_id = recorded_activation_id
        activation_id = _canonical_uuid(
            submission.activation_id
            or resume_activation_id
            or str(self.uuid_factory()),
            "activation_id",
        )
        if resume_activation_id and activation_id != resume_activation_id:
            raise BootstrapError(
                "identity_conflict", "Requested activation differs from preserved evidence."
            )
        workspace = build_activation_workspace_paths(
            self.base, identity.machine_uuid, activation_id
        )
        with self._migration_lock(identity.machine_uuid):
            phase = (
                PublishedMigrationPhase.ACTIVATION_STAGED
                if paths.verification_path.exists()
                or paths.activation_receipt_path.exists()
                else PublishedMigrationPhase.COPIED_UNVERIFIED
            )
            published = verify_published_migration(
                paths,
                phase=phase,
                archive_policy=self.migration_policy.archive_policy,
            )
            self._write_assignment(
                workspace,
                identity,
                None,
                published.receipt.migration_id,
            )
            return self._activate_published_locked(
                paths,
                identity,
                operator=submission.operator,
                source_reason=submission.source_reason,
                camera_confirmation=submission.camera_confirmation,
                service_record_reference=submission.service_record_reference,
                activation_id=activation_id,
                workspace=workspace,
            )

    def open_ready(self) -> AuthorizedMachineContext:
        try:
            active = require_authorized_active_machine(
                json.loads(self.base.active_machine_path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError, ActiveMachineError) as exc:
            raise BootstrapError("recovery_required", f"Active pointer is invalid: {exc}") from exc
        paths = build_machine_data_paths(self.base, active.machine_uuid)
        try:
            lock = acquire_configuration_lock(paths)
        except ConfigurationLockUnavailable as exc:
            raise BootstrapError("configuration_lock_unavailable", str(exc)) from exc
        try:
            return self._context_from_active(paths, active, lock)
        except Exception:
            lock.release()
            raise

    def _migration_lock(self, machine_uuid: str):
        try:
            return acquire_migration_lock(self.base, machine_uuid)
        except MigrationLockUnavailable as exc:
            raise BootstrapError("migration_lock_unavailable", str(exc)) from exc

    def _identity_for_submission(
        self, candidate: CandidateEvidence, submission: BootstrapSubmission
    ) -> MachineIdentity:
        machine_id = str(submission.machine_id or "").strip()
        if not machine_id or machine_id.casefold() == UNASSIGNED_MACHINE_ID.casefold():
            raise BootstrapError("invalid_identity", "An assigned machine display ID is required.")
        legacy = candidate.legacy_identity
        if legacy is not None and candidate.identity_status == "assigned":
            if legacy.machine_id != machine_id:
                raise BootstrapError("identity_conflict", "Candidate identity differs from operator confirmation.")
            if submission.machine_uuid and _canonical_uuid(submission.machine_uuid, "machine_uuid") != legacy.machine_uuid:
                raise BootstrapError("identity_conflict", "Candidate UUID differs from requested UUID.")
            return legacy
        machine_uuid = _canonical_uuid(
            submission.machine_uuid or str(self.uuid_factory()), "machine_uuid"
        )
        return MachineIdentity(machine_id, machine_uuid, self.clock(), "Assigned during rc.2 bootstrap")

    def _load_identity(self, paths: MachineDataPaths) -> MachineIdentity:
        try:
            payload = json.loads(paths.identity_path.read_text(encoding="utf-8"))
            return parse_machine_identity(payload)
        except (OSError, json.JSONDecodeError, MachineIdentityError) as exc:
            raise BootstrapError("recovery_required", f"Canonical identity is invalid: {exc}") from exc

    def _activation_workspaces(self) -> tuple[ActivationWorkspacePaths, ...]:
        root = self.base.activation_work_root.resolve(strict=False)
        if not root.exists():
            return ()
        if not root.is_dir():
            raise BootstrapError(
                "recovery_required", "Activation workspace root is not a directory."
            )
        workspaces = []
        for machine_child in sorted(root.iterdir(), key=lambda item: item.name):
            if not machine_child.is_dir():
                raise BootstrapError(
                    "recovery_required",
                    f"Unexpected activation-work item: {machine_child}",
                )
            machine_uuid = _canonical_uuid(machine_child.name, "machine_uuid")
            for activation_child in sorted(
                machine_child.iterdir(), key=lambda item: item.name
            ):
                if not activation_child.is_dir():
                    raise BootstrapError(
                        "recovery_required",
                        f"Unexpected activation assignment item: {activation_child}",
                    )
                activation_id = _canonical_uuid(
                    activation_child.name, "activation_id"
                )
                workspaces.append(
                    build_activation_workspace_paths(
                        self.base, machine_uuid, activation_id
                    )
                )
        return tuple(workspaces)

    def _resume_assignment(
        self,
        candidate: CandidateEvidence,
        submission: BootstrapSubmission,
    ) -> tuple[ActivationWorkspacePaths, MachineIdentity, str] | None:
        workspaces = self._activation_workspaces()
        if not workspaces:
            return None
        if len(workspaces) != 1:
            raise BootstrapError(
                "recovery_required",
                "Multiple incomplete bootstrap assignments require support review.",
            )
        workspace = workspaces[0]
        try:
            payload = json.loads(
                workspace.assignment_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise BootstrapError(
                "recovery_required", f"Bootstrap assignment is invalid: {exc}"
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema_name") != ACTIVATION_ASSIGNMENT_SCHEMA_NAME
            or payload.get("schema_version") != ACTIVATION_ASSIGNMENT_SCHEMA_VERSION
            or payload.get("activation_id") != workspace.activation_id
            or payload.get("machine_uuid") != workspace.machine_uuid
        ):
            raise BootstrapError(
                "recovery_required", "Bootstrap assignment identity is invalid."
            )
        try:
            identity = parse_machine_identity(payload.get("identity"))
        except MachineIdentityError as exc:
            raise BootstrapError(
                "recovery_required", f"Assigned machine identity is invalid: {exc}"
            ) from exc
        migration_id = _canonical_uuid(
            payload.get("migration_id"), "migration_id"
        )
        if (
            identity.machine_uuid != workspace.machine_uuid
            or identity.machine_id != payload.get("machine_id")
        ):
            raise BootstrapError(
                "recovery_required", "Assigned machine identity fields differ."
            )
        if payload.get("candidate_id") != candidate.candidate_id:
            raise BootstrapError(
                "identity_conflict",
                "A different source was selected for the preserved identity assignment.",
            )
        requested_machine_id = str(submission.machine_id or "").strip()
        if requested_machine_id != identity.machine_id:
            raise BootstrapError(
                "identity_conflict",
                "Machine ID differs from the preserved identity assignment.",
            )
        if submission.machine_uuid and (
            _canonical_uuid(submission.machine_uuid, "machine_uuid")
            != identity.machine_uuid
        ):
            raise BootstrapError(
                "identity_conflict",
                "Requested machine UUID differs from the preserved assignment.",
            )
        if submission.activation_id and (
            _canonical_uuid(submission.activation_id, "activation_id")
            != workspace.activation_id
        ):
            raise BootstrapError(
                "identity_conflict",
                "Requested activation differs from the preserved assignment.",
            )
        return workspace, identity, migration_id

    def _write_assignment(
        self,
        workspace: ActivationWorkspacePaths,
        identity: MachineIdentity,
        candidate: CandidateEvidence | None,
        migration_id: str,
    ) -> None:
        migration_id = _canonical_uuid(migration_id, "migration_id")
        payload = {
            "schema_name": ACTIVATION_ASSIGNMENT_SCHEMA_NAME,
            "schema_version": ACTIVATION_ASSIGNMENT_SCHEMA_VERSION,
            "activation_id": workspace.activation_id,
            "machine_id": identity.machine_id,
            "machine_uuid": identity.machine_uuid,
            "assigned_at_utc": identity.assigned_at,
            "identity": identity.to_payload(),
            "migration_id": migration_id,
            "candidate_id": candidate.candidate_id if candidate else None,
            "candidate_source_kind": (
                candidate.source_kind.value if candidate else None
            ),
            "candidate_source": (
                str(candidate.normalized_source) if candidate else None
            ),
        }
        if workspace.assignment_path.exists():
            try:
                existing = json.loads(workspace.assignment_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise BootstrapError("recovery_required", f"Assignment record is invalid: {exc}") from exc
            if existing != payload:
                stable_fields = (
                    "activation_id",
                    "machine_id",
                    "machine_uuid",
                    "identity",
                    "migration_id",
                )
                if any(existing.get(name) != payload.get(name) for name in stable_fields) or (
                    candidate is not None
                    and existing.get("candidate_id") != payload.get("candidate_id")
                ):
                    raise BootstrapError(
                        "identity_conflict", "Activation assignment evidence conflicts."
                    )
            return
        self.io.atomic_write_json(
            workspace.assignment_path, payload, checkpoint_prefix="activation_assignment"
        )

    def _write_journal(
        self,
        workspace: ActivationWorkspacePaths,
        state: str,
        identity: MachineIdentity,
        migration_id: str,
    ) -> None:
        order = (
            "identity_assigned",
            "migration_published",
            "verification_written",
            "activation_receipt_written",
            "deployment_enrolled",
            "pointer_written",
        )
        if state not in order:
            raise BootstrapError("invalid_state", f"Unknown activation state {state}.")
        prior = None
        if workspace.journal_path.exists():
            try:
                prior = json.loads(workspace.journal_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise BootstrapError("recovery_required", f"Activation journal is invalid: {exc}") from exc
            if (
                prior.get("schema_name") != ACTIVATION_JOURNAL_SCHEMA_NAME
                or prior.get("schema_version") != ACTIVATION_JOURNAL_SCHEMA_VERSION
                or prior.get("activation_id") != workspace.activation_id
                or prior.get("machine_uuid") != identity.machine_uuid
            ):
                raise BootstrapError("recovery_required", "Activation journal identity is invalid.")
            prior_state = prior.get("state")
            if prior_state not in order:
                raise BootstrapError("recovery_required", "Activation journal state is invalid.")
            if order.index(state) < order.index(prior_state):
                if prior.get("migration_id") != migration_id:
                    raise BootstrapError(
                        "recovery_required",
                        "Activation journal migration binding changed.",
                    )
                return
            if state == prior_state and prior.get("migration_id") == migration_id:
                return
        self.io.atomic_write_json(
            workspace.journal_path,
            {
                "schema_name": ACTIVATION_JOURNAL_SCHEMA_NAME,
                "schema_version": ACTIVATION_JOURNAL_SCHEMA_VERSION,
                "activation_id": workspace.activation_id,
                "migration_id": migration_id,
                "machine_id": identity.machine_id,
                "machine_uuid": identity.machine_uuid,
                "state": state,
                "updated_at_utc": self.clock(),
            },
            checkpoint_prefix="activation_journal",
        )

    def _activate_published_locked(
        self,
        paths: MachineDataPaths,
        identity: MachineIdentity,
        *,
        operator: str,
        source_reason: str,
        camera_confirmation: Mapping[str, object],
        service_record_reference: str | None,
        activation_id: str,
        workspace: ActivationWorkspacePaths,
    ) -> AuthorizedMachineContext:
        phase = (
            PublishedMigrationPhase.ACTIVATION_STAGED
            if paths.verification_path.exists() or paths.activation_receipt_path.exists()
            else PublishedMigrationPhase.COPIED_UNVERIFIED
        )
        published = verify_published_migration(
            paths, phase=phase, archive_policy=self.migration_policy.archive_policy
        )
        try:
            ownership = self.ownership_policy.classify_all(
                published.receipt.unclassified_source_paths
            )
        except OwnershipPolicyError as exc:
            raise BootstrapError("ownership_unresolved", str(exc)) from exc
        if any(not decision.activation_allowed for decision in ownership):
            unresolved = ", ".join(
                item.relative_path for item in ownership if not item.activation_allowed
            )
            raise BootstrapError(
                "ownership_unresolved",
                f"Unreviewed/prohibited source paths block activation: {unresolved}",
            )
        try:
            configuration_lock = acquire_configuration_lock(paths)
        except ConfigurationLockUnavailable as exc:
            raise BootstrapError("configuration_lock_unavailable", str(exc)) from exc
        try:
            # Lock creation is a known phase file; baseline bytes must still match.
            published = verify_published_migration(
                paths,
                phase=PublishedMigrationPhase.ACTIVATION_STAGED,
                archive_policy=self.migration_policy.archive_policy,
            )
            if paths.verification_path.exists():
                verification = load_machine_verification(paths.verification_path)
                self._validate_resumable_verification(
                    paths, identity, published, verification, ownership
                )
                verification_sha = sha256_file(paths.verification_path)[0]
                directory_synced = self.io.fsync_directory(paths.metadata_root)
            else:
                verification = create_machine_verification(
                    paths=paths,
                    identity=identity,
                    published=published,
                    ownership_decisions=ownership,
                    operator=operator,
                    machine_id_confirmation=identity.machine_id,
                    source_reason=source_reason,
                    camera_confirmation=camera_confirmation,
                    service_record_reference=service_record_reference,
                    app_version=self.app_version,
                    app_commit=self.app_commit,
                    clock=self.clock,
                )
                verification_sha, directory_synced = write_machine_verification(
                    paths, verification, io=self.io
                )
            self._write_journal(
                workspace,
                "verification_written",
                identity,
                published.receipt.migration_id,
            )
            if paths.activation_receipt_path.exists():
                activation_receipt = load_activation_receipt(
                    paths.activation_receipt_path
                )
                if activation_receipt.activation_id != activation_id:
                    raise BootstrapError(
                        "recovery_required", "Activation receipt ID differs from resume ID."
                    )
                self._validate_pre_pointer_bindings(
                    paths,
                    identity,
                    published,
                    verification,
                    activation_receipt,
                    ownership,
                )
                activation_sha = sha256_file(paths.activation_receipt_path)[0]
            else:
                activation_receipt = ActivationReceipt(
                    activation_id=activation_id,
                    migration_id=published.receipt.migration_id,
                    machine_id=identity.machine_id,
                    machine_uuid=identity.machine_uuid,
                    migration_receipt_sha256=verification.migration_receipt_sha256,
                    migration_tree_manifest_sha256=published.migration_tree_manifest_sha256,
                    verification_sha256=verification_sha,
                    backup_archive_sha256=published.receipt.backup_archive_sha256,
                    ownership_policy_version=self.ownership_policy.schema_version,
                    directory_sync_supported=directory_synced,
                    created_at_utc=self.clock(),
                    app_version=self.app_version,
                    app_commit=self.app_commit,
                )
                activation_sha = write_activation_receipt(
                    paths, activation_receipt, io=self.io
                )
            self._write_journal(
                workspace,
                "activation_receipt_written",
                identity,
                published.receipt.migration_id,
            )
            verify_published_migration(
                paths,
                phase=PublishedMigrationPhase.ACTIVE,
                archive_policy=self.migration_policy.archive_policy,
            )
            active = ActiveMachine(
                machine_id=identity.machine_id,
                machine_uuid=identity.machine_uuid,
                selected_at_utc=self.clock(),
                selection_source="migration",
                activation_id=activation_id,
                migration_id=published.receipt.migration_id,
                activation_receipt_sha256=activation_sha,
            )
            try:
                validate_or_enroll_deployment(
                    paths,
                    active,
                    configuration_lock,
                    app_version=self.app_version,
                    app_commit=self.app_commit,
                    release_contract=self.release_contract,
                    update_compatibility=self.update_compatibility,
                    allow_genesis_enrollment=True,
                    io=self.io,
                    clock=self.clock,
                )
            except MachineDataUpdateError as exc:
                raise BootstrapError("recovery_required", str(exc)) from exc
            self._write_journal(
                workspace,
                "deployment_enrolled",
                identity,
                published.receipt.migration_id,
            )
            self.io.atomic_write_json(
                self.base.active_machine_path,
                active.to_payload(),
                checkpoint_prefix="active_machine",
            )
            reopened = require_authorized_active_machine(
                json.loads(self.base.active_machine_path.read_text(encoding="utf-8"))
            )
            if reopened != active:
                raise BootstrapError("recovery_required", "Reopened active pointer differs.")
            self._write_journal(
                workspace, "pointer_written", identity, published.receipt.migration_id
            )
            context = self._context_from_active(paths, active, configuration_lock)
            self._cleanup_workspace(workspace)
            return context
        except Exception:
            configuration_lock.release()
            raise

    def _validate_active_without_lock(
        self, paths: MachineDataPaths, active: ActiveMachine
    ) -> None:
        verification = load_machine_verification(paths.verification_path)
        activation = load_activation_receipt(paths.activation_receipt_path)
        identity = self._load_identity(paths)
        try:
            configuration_state = inspect_configuration_state(
                paths, identity, active, verification, allow_pending=True
            )
        except ConfigurationRecoveryRequired as exc:
            raise BootstrapError("recovery_required", str(exc)) from exc
        overrides = (
            build_active_tree_overrides(paths, configuration_state)
            if configuration_state.has_history or configuration_state.pending is not None
            else None
        )
        published = verify_published_migration(
            paths,
            phase=PublishedMigrationPhase.ACTIVE,
            archive_policy=self.migration_policy.archive_policy,
            active_tree_overrides=overrides,
        )
        self._validate_bindings(
            paths, active, published, verification, activation,
            configuration_state=configuration_state,
        )
        try:
            inspect_deployment_gate(
                paths,
                active,
                app_version=self.app_version,
                app_commit=self.app_commit,
                release_contract=self.release_contract,
            )
        except MachineDataUpdateError as exc:
            raise BootstrapError("recovery_required", str(exc)) from exc

    def _context_from_active(
        self,
        paths: MachineDataPaths,
        active: ActiveMachine,
        configuration_lock: AcquiredConfigurationLock,
    ) -> AuthorizedMachineContext:
        configuration_lock.assert_owns(paths)
        verification = load_machine_verification(paths.verification_path)
        activation = load_activation_receipt(paths.activation_receipt_path)
        identity = self._load_identity(paths)
        try:
            initial_state = inspect_configuration_state(
                paths, identity, active, verification, allow_pending=True
            )
        except ConfigurationRecoveryRequired as exc:
            raise BootstrapError("recovery_required", str(exc)) from exc
        initial_overrides = (
            build_active_tree_overrides(paths, initial_state)
            if initial_state.has_history or initial_state.pending is not None
            else None
        )
        published = verify_published_migration(
            paths,
            phase=PublishedMigrationPhase.ACTIVE,
            archive_policy=self.migration_policy.archive_policy,
            active_tree_overrides=initial_overrides,
        )
        self._validate_bindings(
            paths, active, published, verification, activation,
            configuration_state=initial_state,
        )
        if identity.machine_uuid != active.machine_uuid or identity.machine_id != active.machine_id:
            raise BootstrapError("recovery_required", "Active pointer and identity differ.")
        transactions = ConfigurationTransactionService(
            paths=paths,
            identity=identity,
            active=active,
            verification=verification,
            configuration_lock=configuration_lock,
            app_version=self.app_version,
            app_commit=self.app_commit,
            clock=self.clock,
        )
        try:
            configuration_state = transactions.reconcile()
        except ConfigurationRecoveryRequired as exc:
            raise BootstrapError("recovery_required", str(exc)) from exc
        overrides = (
            build_active_tree_overrides(paths, configuration_state)
            if configuration_state.has_history
            else None
        )
        published = verify_published_migration(
            paths,
            phase=PublishedMigrationPhase.ACTIVE,
            archive_policy=self.migration_policy.archive_policy,
            active_tree_overrides=overrides,
        )
        self._validate_bindings(
            paths, active, published, verification, activation,
            configuration_state=configuration_state,
        )
        settings_path = LocalConfig.get_existing_machine_config_path(
            "Settings.json", config_root=paths.config_root
        )
        settings = LocalConfig.validate_machine_config_file(settings_path, "Settings.json")
        settings_sha = sha256_file(settings_path)[0]
        try:
            policy = load_configuration_change_policy()
            documents = read_governed_documents(paths)
            guard = ConfigurationChangeGuard(
                policy,
                parse_safety_bounds(documents["Obstacles.json"]),
            )
            guard.validate_active_documents(documents)
        except (ConfigurationSafetyError, OSError, ValueError) as exc:
            raise BootstrapError(
                "recovery_required",
                f"Active configuration safety validation failed: {exc}",
            ) from exc
        transactions.configuration_safety_guard = guard
        transactions.require_configuration_guard_evidence = True
        deployment_anchor = None
        try:
            if self.release_contract is not None and paths.legacy_session_path.exists():
                from MachineDataCompatibility import resolve_legacy_session

                deployment_anchor = resolve_legacy_session(
                    paths,
                    active,
                    configuration_lock,
                    app_version=self.app_version,
                    app_commit=self.app_commit,
                    release_contract=self.release_contract,
                    keep_canonical=False,
                    io=self.io,
                    clock=self.clock,
                )
            if deployment_anchor is None:
                deployment_anchor = validate_or_enroll_deployment(
                    paths,
                    active,
                    configuration_lock,
                    app_version=self.app_version,
                    app_commit=self.app_commit,
                    release_contract=self.release_contract,
                    io=self.io,
                    clock=self.clock,
                )
        except MachineDataUpdateError as exc:
            raise BootstrapError("recovery_required", str(exc)) from exc
        return AuthorizedMachineContext(
            paths=paths,
            identity=identity,
            active_machine=active,
            migration=published,
            verification=verification,
            activation_receipt=activation,
            settings=settings,
            settings_raw_sha256=settings_sha,
            saved_target_authorizer=transactions.saved_target_authorizer,
            configuration_state=configuration_state,
            configuration_transactions=transactions,
            configuration_safety_guard=guard,
            configuration_lock=configuration_lock,
            deployment_anchor=deployment_anchor,
        )

    def _validate_bindings(
        self,
        paths: MachineDataPaths,
        active: ActiveMachine,
        published: PublishedMigrationEvidence,
        verification: MachineVerification,
        activation: ActivationReceipt,
        configuration_state: ConfigurationState | None = None,
    ) -> None:
        activation_sha = sha256_file(paths.activation_receipt_path)[0]
        receipt_sha = sha256_file(paths.migration_receipt_path)[0]
        verification_sha = sha256_file(paths.verification_path)[0]
        if (
            active.activation_id != activation.activation_id
            or active.migration_id != activation.migration_id
            or active.activation_receipt_sha256 != activation_sha
            or activation.migration_id != published.receipt.migration_id
            or activation.machine_uuid != paths.machine_uuid
            or activation.migration_receipt_sha256 != receipt_sha
            or activation.migration_tree_manifest_sha256
            != published.migration_tree_manifest_sha256
            or activation.verification_sha256 != verification_sha
            or activation.backup_archive_sha256 != published.receipt.backup_archive_sha256
            or verification.migration_receipt_sha256 != receipt_sha
            or verification.migration_id != published.receipt.migration_id
        ):
            raise BootstrapError("recovery_required", "Activation evidence bindings differ.")
        decisions = self.ownership_policy.classify_all(
            published.receipt.unclassified_source_paths
        )
        if decisions != verification.ownership_decisions or any(
            not decision.activation_allowed for decision in decisions
        ):
            raise BootstrapError("recovery_required", "Ownership evidence/policy changed.")
        if configuration_state is None or (
            not configuration_state.has_history
            and configuration_state.pending is None
        ):
            validate_verification_against_files(paths, verification)

    def _validate_resumable_verification(
        self,
        paths: MachineDataPaths,
        identity: MachineIdentity,
        published: PublishedMigrationEvidence,
        verification: MachineVerification,
        ownership: tuple[OwnershipDecision, ...],
    ) -> None:
        if (
            verification.machine_id != identity.machine_id
            or verification.machine_uuid != identity.machine_uuid
            or verification.migration_id != published.receipt.migration_id
            or verification.migration_receipt_sha256
            != sha256_file(paths.migration_receipt_path)[0]
            or verification.ownership_decisions != ownership
            or verification.app_version != self.app_version
            or verification.app_commit != self.app_commit
        ):
            raise BootstrapError(
                "recovery_required", "Preserved verification cannot resume this activation."
            )
        validate_verification_against_files(paths, verification)

    def _validate_pre_pointer_bindings(
        self,
        paths: MachineDataPaths,
        identity: MachineIdentity,
        published: PublishedMigrationEvidence,
        verification: MachineVerification,
        activation: ActivationReceipt,
        ownership: tuple[OwnershipDecision, ...],
    ) -> None:
        self._validate_resumable_verification(
            paths, identity, published, verification, ownership
        )
        if (
            activation.machine_id != identity.machine_id
            or activation.machine_uuid != identity.machine_uuid
            or activation.migration_id != published.receipt.migration_id
            or activation.migration_receipt_sha256
            != sha256_file(paths.migration_receipt_path)[0]
            or activation.migration_tree_manifest_sha256
            != published.migration_tree_manifest_sha256
            or activation.verification_sha256
            != sha256_file(paths.verification_path)[0]
            or activation.backup_archive_sha256
            != published.receipt.backup_archive_sha256
            or activation.ownership_policy_version
            != self.ownership_policy.schema_version
            or activation.app_version != self.app_version
            or activation.app_commit != self.app_commit
        ):
            raise BootstrapError(
                "recovery_required", "Preserved activation receipt bindings differ."
            )

    def _find_resume_activation_id(self, machine_uuid: str) -> str | None:
        parent = (
            self.base.activation_work_root / _canonical_uuid(machine_uuid, "machine_uuid")
        ).resolve(strict=False)
        if not parent.is_dir():
            return None
        candidates: list[str] = []
        for child in parent.iterdir():
            if not child.is_dir():
                continue
            try:
                candidates.append(_canonical_uuid(child.name, "activation_id"))
            except BootstrapError as exc:
                raise BootstrapError(
                    "recovery_required", f"Invalid activation workspace: {child}"
                ) from exc
        if len(candidates) > 1:
            raise BootstrapError(
                "recovery_required", "Multiple activation workspaces require support review."
            )
        return candidates[0] if candidates else None

    def _cleanup_workspace(self, workspace: ActivationWorkspacePaths) -> None:
        expected_parent = (
            self.base.activation_work_root / workspace.machine_uuid
        ).resolve(strict=False)
        if workspace.root.parent != expected_parent or workspace.root.name != workspace.activation_id:
            raise BootstrapError("unsafe_workspace", "Refusing unexpected workspace cleanup.")
        if workspace.root.exists():
            shutil.rmtree(workspace.root)


__all__ = [
    "ACTIVATION_ASSIGNMENT_SCHEMA_NAME",
    "ACTIVATION_JOURNAL_SCHEMA_NAME",
    "ActivationWorkspacePaths",
    "AuthorizedMachineContext",
    "BootstrapError",
    "BootstrapInspection",
    "BootstrapIssue",
    "BootstrapState",
    "BootstrapSubmission",
    "MachineDataBootstrap",
    "PublishedActivationSubmission",
    "build_activation_workspace_paths",
]
