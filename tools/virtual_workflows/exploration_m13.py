"""Pure versioned contracts for Milestone 13 semantic exploration.

Slice 13.1 intentionally exposes planning evidence only.  Nothing in this
module imports Qt, application MVC code, persistence helpers, or a simulator.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


CAMPAIGN_ID = "design_calibration_lifecycle_v1"
GENERATOR_VERSION = "design-calibration-lifecycle-v1"
STATE_MODEL_VERSION = "design-calibration-state-v1"
OPERATION_CATALOG_VERSION = "design-calibration-operation-v1"
ORACLE_LEDGER_VERSION = "design-calibration-oracle-ledger-v1"
SEMANTIC_COVERAGE_VERSION = "design-calibration-semantic-coverage-v1"
PLAN_SCHEMA_NAME = "labcraft.virtual_workflow_exploration_plan"
PLAN_SCHEMA_VERSION = 2
FROZEN_SEEDS = (13, 29, 47, 83, 131, 197)
DIAGNOSTIC_COMPATIBILITY_SEEDS = (1, 101)
MAX_DIAGNOSTIC_SEEDS = 4
EXPECTED_STATE_MODEL_SHA256 = "71e7ca63e564a3a841bb95f9bf157fb3d491dbf2e4b80cdf027c956dab884cc8"
EXPECTED_OPERATION_CATALOG_SHA256 = "de7cdb01967b5e9fe1da4d2759017e6d2fd75c9e32379f01b616b90fb0cbd106"
EXPECTED_ORACLE_LEDGER_SHA256 = "7ca216df7d28fd8c01e94efebb5c51ba0db249a8fde3dfa6385de5381d77351e"
EXPECTED_FROZEN_SET_SHA256 = "1b4a2b4f9b56295428f9b2565ba048960ba0957b282e1c3d7296e57908a14a4e"
EXPECTED_FIXTURE_PROJECTION_SHA256 = "5687adab7dabbe7d94112fb18b2c8eb8e8740b655c47b2352010c635cf028043"
EXPECTED_CATALOG_SHA256 = "9d444efa4382fdcc4762fb3b7e232beaf633fb8abc2ff9ec4121655a61a6cc5c"
EXPECTED_CAMPAIGN_SHA256 = "aa4ae1175d6c34d03cae876b29d38820a690e3db0307183303326fe520283de3"
EXPECTED_SEQUENCE_SHA256 = (
    "992abf215250df32bbe9a23d47aba3b26faab96964082d66a29a4dd14f0d1fdd",
    "d07f1d44869e0849cfd652e09c6b2adc1c6bfd05f70512a166deb823113ee6f4",
    "776c9e7670a5022954cefd753a0aad3d059fe4c04738a1ea926e9177cd9564f7",
    "065a1d08c1de18eaf271faccee302e33cd3b58c70786e734c2c6ae5ee1d9c3e4",
    "38963d167b14115254282dc81bec8eddb05c0fb845d1e9790f2c5be6f96ce9e5",
    "faf4de186bbf103db5a46ec62b8dba60ad53771bfcd46907d3eda827618306fe",
)


class M13ExplorationValidationError(ValueError):
    """Raised when a Milestone 13 planning contract fails closed."""


@dataclass(frozen=True)
class BudgetContract:
    semantic_operations: int
    action_rows: int
    sessions: int
    session_rotations: int
    screenshots: int
    retained_files: int
    retained_bytes: int
    scenario_deadline_seconds: int
    child_watchdog_seconds: int
    reactions: int
    executable_stocks: int
    intents: int
    droplets: int

    def normalized(self) -> dict[str, int]:
        return {
            name: int(getattr(self, name))
            for name in self.__dataclass_fields__
        }


SEQUENCE_BUDGET = BudgetContract(
    semantic_operations=18,
    action_rows=80,
    sessions=3,
    session_rotations=2,
    screenshots=4,
    retained_files=256,
    retained_bytes=48 * 1024 * 1024,
    scenario_deadline_seconds=270,
    child_watchdog_seconds=300,
    reactions=4,
    executable_stocks=2,
    intents=8,
    droplets=44,
)

CAMPAIGN_BUDGET = BudgetContract(
    semantic_operations=108,
    action_rows=480,
    sessions=18,
    session_rotations=12,
    screenshots=24,
    retained_files=1600,
    retained_bytes=320 * 1024 * 1024,
    scenario_deadline_seconds=1800,
    child_watchdog_seconds=1800,
    reactions=24,
    executable_stocks=12,
    intents=48,
    droplets=264,
)


@dataclass(frozen=True)
class StateDefinition:
    state_id: str
    validity: str
    materialization: str
    calibration: str
    persistence: str
    runtime: str
    progress: str
    lock: str

    def normalized(self) -> dict[str, str]:
        return {
            "state_id": self.state_id,
            "validity": self.validity,
            "materialization": self.materialization,
            "calibration": self.calibration,
            "persistence": self.persistence,
            "runtime": self.runtime,
            "progress": self.progress,
            "lock": self.lock,
        }


def _state(
    state_id: str,
    validity: str,
    materialization: str,
    calibration: str,
    persistence: str,
    runtime: str,
    progress: str,
    lock: str,
) -> StateDefinition:
    return StateDefinition(
        state_id,
        validity,
        materialization,
        calibration,
        persistence,
        runtime,
        progress,
        lock,
    )


STATES = (
    _state("draft_valid", "valid", "dirty", "none", "draft", "inactive", "zero", "editable"),
    _state("draft_invalid", "named_invalid", "dirty", "none", "draft", "inactive", "zero", "editable"),
    _state("draft_generated", "valid", "generated", "none", "draft", "inactive", "zero", "editable"),
    _state("prepared_zero_progress", "valid", "finalized", "none", "authoritative", "inactive", "zero", "prepared_editable"),
    _state("calibration_available_unapplied", "valid", "finalized", "available_unapplied", "authoritative", "inactive", "zero", "prepared_editable"),
    _state("calibration_selected_unapplied", "valid", "finalized", "selected_unapplied", "authoritative", "inactive", "zero", "prepared_editable"),
    _state("calibrated_zero_progress", "valid", "finalized", "complete", "authoritative", "inactive", "zero", "prepared_editable"),
    _state("session_closed", "valid", "finalized", "persisted", "authoritative", "inactive", "zero", "closed"),
    _state("reloaded_inactive", "valid", "finalized", "persisted", "reloaded_exact", "inactive", "zero", "prepared_editable"),
    _state("active_zero_progress", "valid", "finalized", "complete", "authoritative", "active", "zero", "active_locked"),
    _state("progressed_locked", "valid", "finalized", "complete", "authoritative", "active", "positive", "progressed_locked"),
    _state("terminal", "valid", "finalized", "complete", "reloaded_exact", "inactive", "complete", "terminal_read_only"),
)
STATE_BY_ID = {item.state_id: item for item in STATES}


@dataclass(frozen=True)
class OperationDefinition:
    operation_id: str
    oracle_id: str
    oracle_owner: str
    expected_outcome: str
    transitions: tuple[tuple[str, str], ...]
    rejection_class: str | None = None
    max_action_rows: int = 3
    screenshot_policy: str = "checkpoint_optional"

    def normalized(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "oracle_id": self.oracle_id,
            "oracle_owner": self.oracle_owner,
            "expected_outcome": self.expected_outcome,
            "transitions": [
                {"from_state": source, "to_state": target}
                for source, target in self.transitions
            ],
            "rejection_class": self.rejection_class,
            "max_action_rows": self.max_action_rows,
            "screenshot_policy": self.screenshot_policy,
        }


def _op(
    operation_id: str,
    oracle_id: str,
    oracle_owner: str,
    transitions: Sequence[tuple[str, str]],
    *,
    outcome: str = "accepted",
    rejection_class: str | None = None,
    rows: int = 3,
) -> OperationDefinition:
    return OperationDefinition(
        operation_id,
        oracle_id,
        oracle_owner,
        outcome,
        tuple(transitions),
        rejection_class,
        rows,
    )


OPERATIONS = (
    _op("editor.change_existing_reagent_via_ui", "m8.prepared_edit_regenerate_refinalize", "editor_prepared_guard_v1 plus focused action/assertion tests", (("draft_valid", "draft_invalid"), ("draft_invalid", "draft_valid"), ("prepared_zero_progress", "draft_valid"))),
    _op("editor.toggle_two_stock_via_ui", "m10.one_two_stock_literal", "one_stock_feasible/two_stock_required and M12 stock-mode safeguards", (("draft_valid", "draft_valid"), ("draft_valid", "draft_invalid"), ("draft_invalid", "draft_valid"))),
    _op("editor.change_printable_wells_via_ui", "m10.custom_wells_literal", "custom_wells_with_exclusions and exact-capacity picker assertions", (("draft_valid", "draft_valid"),)),
    _op("editor.set_randomization_seed_via_ui", "m10.seed_assignment_literal", "multi_reagent_seed_4321/1234 literal assignment and multiset hashes", (("draft_valid", "draft_valid"),)),
    _op("editor.optimize_generate_via_ui", "m10.optimize_generate_literal", "M10 positive cases and M12 optimizer-infeasible safeguards", (("draft_valid", "draft_generated"),)),
    _op("editor.regenerate_prepared_design_via_ui", "m8.prepared_regenerate", "M8 prepared campaign and M12 stale-calibration case", (("draft_valid", "draft_generated"),)),
    _op("editor.finalize_via_ui", "m10.finalize_authority_literal", "M10 positive/rejected Finalize and authoritative reconstruction", (("draft_generated", "prepared_zero_progress"),)),
    _op("editor.refinalize_prepared_via_ui", "m8.prepared_refinalize_reload", "M8 refinalize/reload and M12 stale-calibration identity", (("draft_generated", "prepared_zero_progress"),)),
    _op("head.stage_matching_via_ui", "m11.keyed_head_stage", "M11 joined lifecycle stock/head identities and focused head staging", (("prepared_zero_progress", "prepared_zero_progress"), ("reloaded_inactive", "prepared_zero_progress"), ("active_zero_progress", "prepared_zero_progress"))),
    _op("head.stage_mismatching_via_ui", "m12.wrong_head_stage", "M12 wrong-head/wrong-stock binding safeguards", (("prepared_zero_progress", "prepared_zero_progress"),)),
    _op("calibration.generate_via_ui", "m11.calibration_generation_fingerprint", "M9 requantization and M11 calibration generation", (("prepared_zero_progress", "calibration_available_unapplied"),)),
    _op("calibration.select_via_ui", "m11.calibration_selection_fingerprint", "M9/M11 calibration-dialog selection evidence", (("calibration_available_unapplied", "calibration_selected_unapplied"),)),
    _op("calibration.apply_via_ui", "m11.keyed_calibration_revision", "M9 literal count transition and M11 keyed revision evidence", (("calibration_selected_unapplied", "calibrated_zero_progress"),)),
    _op("app.close_simulated_session", "m11.clean_session_rotation", "M11 clean rotation and shared cleanup contract", (("calibrated_zero_progress", "session_closed"), ("prepared_zero_progress", "session_closed"), ("active_zero_progress", "session_closed"))),
    _op("experiment.reload_inactive_via_ui", "m11.byte_identical_inactive_reload", "M11 inactive inspection and M12 persistence classification", (("session_closed", "reloaded_inactive"),)),
    _op("experiment.activate_authoritative_via_ui", "m11.explicit_activation", "M11 activation and M12 invalid-activation safeguard", (("reloaded_inactive", "active_zero_progress"),)),
    _op("array.start_pass_via_ui", "m11.literal_dispatch_terminal", "M9 per-stock/well counts and M11 intent/completion/terminal assertions", (("active_zero_progress", "progressed_locked"), ("active_zero_progress", "terminal"), ("progressed_locked", "terminal"))),
    _op("editor.finalize_invalid_via_ui", "m12.editor_invalid_shared_safeguard", "M12 typed invalid-editor dialog plus shared no-mutation/no-dispatch oracle", (("draft_invalid", "draft_invalid"),), outcome="rejected", rejection_class="editor_invalid", rows=2),
    _op("editor.optimize_one_stock_invalid_via_ui", "m12.one_stock_infeasible_shared_safeguard", "M10 two_stock_required and M12 shared no-mutation/no-dispatch oracle", (("draft_invalid", "draft_invalid"),), outcome="rejected", rejection_class="optimizer_infeasible", rows=2),
    _op("calibration.attempt_mismatch_cancel_via_ui", "m12.calibration_mismatch_shared_safeguard", "M12 calibration mode/settings Cancel code/dialog/shared oracle", (("prepared_zero_progress", "prepared_zero_progress"),), outcome="rejected", rejection_class="calibration_mismatch", rows=2),
    _op("array.start_wrong_identity_via_ui", "m12.wrong_identity_shared_safeguard", "M12 wrong-printer-head typed rejection/shared oracle", (("active_zero_progress", "active_zero_progress"),), outcome="rejected", rejection_class="identity_mismatch", rows=2),
    _op("array.start_inactive_via_ui", "m12.inactive_start_shared_safeguard", "M12 inspected_not_activated_start_rejected", (("reloaded_inactive", "reloaded_inactive"),), outcome="rejected", rejection_class="inactive_lifecycle", rows=2),
    _op("editor.attempt_progressed_edit_via_ui", "m12.progressed_edit_shared_safeguard", "M12 active_execution_edit_rejected and post-start lock tests", (("progressed_locked", "progressed_locked"),), outcome="rejected", rejection_class="progress_lock", rows=2),
    _op("calibration.attempt_progressed_apply_via_ui", "m12.progressed_calibration_shared_safeguard", "M12 progressed_stock_recalibration_rejected", (("progressed_locked", "progressed_locked"),), outcome="rejected", rejection_class="progress_lock", rows=2),
    _op("array.start_while_active_via_ui", "m12.start_while_active_shared_safeguard", "M12 start_while_active_rejected", (("progressed_locked", "progressed_locked"),), outcome="rejected", rejection_class="active_lifecycle", rows=2),
    _op("head.attempt_unsafe_exchange_via_ui", "m12.unsafe_exchange_shared_safeguard", "M12 head_exchange_at_invalid_boundary_rejected and precondition tests", (("progressed_locked", "progressed_locked"),), outcome="rejected", rejection_class="unsafe_exchange", rows=2),
)
OPERATION_BY_ID = {item.operation_id: item for item in OPERATIONS}
M13_REJECTION_CASES = {
    "editor.finalize_invalid_via_ui": "printed_exceeds_final_finalize_rejected",
    "editor.optimize_one_stock_invalid_via_ui": "one_stock_infeasible_finalize_rejected",
    "calibration.attempt_mismatch_cancel_via_ui": "calibration_head_mode_cancelled",
    "array.start_wrong_identity_via_ui": "wrong_printer_head_calibration_binding_rejected",
    "array.start_inactive_via_ui": "inspected_not_activated_start_rejected",
    "editor.attempt_progressed_edit_via_ui": "active_execution_edit_rejected",
    "calibration.attempt_progressed_apply_via_ui": "progressed_stock_recalibration_rejected",
    "array.start_while_active_via_ui": "start_while_active_rejected",
    "head.attempt_unsafe_exchange_via_ui": "head_exchange_at_invalid_boundary_rejected",
}


@dataclass(frozen=True)
class SequenceStep:
    operation_id: str
    from_state: str
    to_state: str

    def normalized(self, ordinal: int) -> dict[str, Any]:
        operation = OPERATION_BY_ID[self.operation_id]
        return {
            "ordinal": ordinal,
            "operation_id": self.operation_id,
            "interaction_surface": "real_qt_operator_action",
            "from_state": self.from_state,
            "to_state": self.to_state,
            "expected_outcome": operation.expected_outcome,
            "rejection_class": operation.rejection_class,
            "oracle_id": operation.oracle_id,
            "maximum_action_rows": operation.max_action_rows,
        }


@dataclass(frozen=True)
class ExplorationSequence:
    sequence_id: str
    seed: int
    seed_tier: str
    role: str
    initial_state: str
    steps: tuple[SequenceStep, ...]
    sessions: int
    session_rotations: int
    screenshots: int
    choice_token: str

    def normalized(self) -> dict[str, Any]:
        return {
            "sequence_id": self.sequence_id,
            "seed": self.seed,
            "seed_tier": self.seed_tier,
            "role": self.role,
            "initial_state": self.initial_state,
            "choice_token": self.choice_token,
            "operation_count": len(self.steps),
            "projected_action_rows": sum(
                OPERATION_BY_ID[item.operation_id].max_action_rows
                for item in self.steps
            ),
            "sessions": self.sessions,
            "session_rotations": self.session_rotations,
            "screenshots": self.screenshots,
            "durable_identity_contract": {
                "design_id": f"m13-design-{self.seed}",
                "plan_id": f"m13-plan-{self.seed}",
                "progress_id": f"m13-progress-{self.seed}",
                "stock_ids": [f"m13-{self.seed}-stock-a", f"m13-{self.seed}-stock-b", "Water"],
                "head_id": f"m13-head-{self.seed}",
                "calibration_id": f"m13-calibration-{self.seed}",
                "revision_lineage": f"m13-revision-lineage-{self.seed}",
            },
            "workload_projection": {
                "reactions": 4,
                "executable_stocks": 2,
                "intents": 8,
                "droplets": 44,
            },
            "steps": [item.normalized(index) for index, item in enumerate(self.steps, 1)],
        }


def _canonical_json(value: Mapping[str, Any] | list[Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_json(value: Mapping[str, Any] | list[Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def sequence_sha256(sequence: ExplorationSequence | Mapping[str, Any]) -> str:
    normalized = (
        sequence.normalized()
        if isinstance(sequence, ExplorationSequence)
        else dict(sequence)
    )
    return _sha256_json(normalized)


def _choice_token(seed: int, role: str) -> str:
    payload = f"{GENERATOR_VERSION}:{int(seed)}:{role}:0".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _steps(initial_state: str, *operations: tuple[str, str]) -> tuple[SequenceStep, ...]:
    state = initial_state
    result: list[SequenceStep] = []
    for operation_id, target in operations:
        result.append(SequenceStep(operation_id, state, target))
        state = target
    return tuple(result)


_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "seed": 13,
        "sequence_id": "seed_13_legal_design_calibration_terminal",
        "role": "legal_design_calibration_terminal",
        "initial": "draft_valid",
        "sessions": 2,
        "rotations": 1,
        "screenshots": 4,
        "operations": (
            ("editor.toggle_two_stock_via_ui", "draft_valid"),
            ("editor.change_printable_wells_via_ui", "draft_valid"),
            ("editor.set_randomization_seed_via_ui", "draft_valid"),
            ("editor.optimize_generate_via_ui", "draft_generated"),
            ("editor.finalize_via_ui", "prepared_zero_progress"),
            ("head.stage_matching_via_ui", "prepared_zero_progress"),
            ("calibration.generate_via_ui", "calibration_available_unapplied"),
            ("calibration.select_via_ui", "calibration_selected_unapplied"),
            ("calibration.apply_via_ui", "calibrated_zero_progress"),
            ("app.close_simulated_session", "session_closed"),
            ("experiment.reload_inactive_via_ui", "reloaded_inactive"),
            ("experiment.activate_authoritative_via_ui", "active_zero_progress"),
            ("array.start_pass_via_ui", "terminal"),
        ),
    },
    {
        "seed": 29,
        "sequence_id": "seed_29_legal_refinalize_reload_terminal",
        "role": "legal_refinalize_reload_terminal",
        "initial": "prepared_zero_progress",
        "sessions": 2,
        "rotations": 1,
        "screenshots": 4,
        "operations": (
            ("editor.change_existing_reagent_via_ui", "draft_valid"),
            ("editor.regenerate_prepared_design_via_ui", "draft_generated"),
            ("editor.refinalize_prepared_via_ui", "prepared_zero_progress"),
            ("head.stage_matching_via_ui", "prepared_zero_progress"),
            ("calibration.generate_via_ui", "calibration_available_unapplied"),
            ("calibration.select_via_ui", "calibration_selected_unapplied"),
            ("calibration.apply_via_ui", "calibrated_zero_progress"),
            ("app.close_simulated_session", "session_closed"),
            ("experiment.reload_inactive_via_ui", "reloaded_inactive"),
            ("experiment.activate_authoritative_via_ui", "active_zero_progress"),
            ("array.start_pass_via_ui", "terminal"),
        ),
    },
    {
        "seed": 47,
        "sequence_id": "seed_47_illegal_editor_recovery_terminal",
        "role": "illegal_editor_recovery_terminal",
        "initial": "draft_valid",
        "sessions": 2,
        "rotations": 1,
        "screenshots": 4,
        "operations": (
            ("editor.change_existing_reagent_via_ui", "draft_invalid"),
            ("editor.finalize_invalid_via_ui", "draft_invalid"),
            ("editor.change_existing_reagent_via_ui", "draft_valid"),
            ("editor.toggle_two_stock_via_ui", "draft_invalid"),
            ("editor.optimize_one_stock_invalid_via_ui", "draft_invalid"),
            ("editor.toggle_two_stock_via_ui", "draft_valid"),
            ("editor.optimize_generate_via_ui", "draft_generated"),
            ("editor.finalize_via_ui", "prepared_zero_progress"),
            ("head.stage_matching_via_ui", "prepared_zero_progress"),
            ("calibration.generate_via_ui", "calibration_available_unapplied"),
            ("calibration.select_via_ui", "calibration_selected_unapplied"),
            ("calibration.apply_via_ui", "calibrated_zero_progress"),
            ("app.close_simulated_session", "session_closed"),
            ("experiment.reload_inactive_via_ui", "reloaded_inactive"),
            ("experiment.activate_authoritative_via_ui", "active_zero_progress"),
            ("array.start_pass_via_ui", "terminal"),
        ),
    },
    {
        "seed": 83,
        "sequence_id": "seed_83_illegal_calibration_recovery_terminal",
        "role": "illegal_calibration_recovery_terminal",
        "initial": "prepared_zero_progress",
        "sessions": 2,
        "rotations": 1,
        "screenshots": 4,
        "operations": (
            ("head.stage_mismatching_via_ui", "prepared_zero_progress"),
            ("calibration.attempt_mismatch_cancel_via_ui", "prepared_zero_progress"),
            ("head.stage_matching_via_ui", "prepared_zero_progress"),
            ("calibration.generate_via_ui", "calibration_available_unapplied"),
            ("calibration.select_via_ui", "calibration_selected_unapplied"),
            ("calibration.apply_via_ui", "calibrated_zero_progress"),
            ("app.close_simulated_session", "session_closed"),
            ("experiment.reload_inactive_via_ui", "reloaded_inactive"),
            ("experiment.activate_authoritative_via_ui", "active_zero_progress"),
            ("array.start_pass_via_ui", "terminal"),
        ),
    },
    {
        "seed": 131,
        "sequence_id": "seed_131_illegal_identity_activation_recovery_terminal",
        "role": "illegal_identity_activation_recovery_terminal",
        "initial": "prepared_zero_progress",
        "sessions": 3,
        "rotations": 2,
        "screenshots": 4,
        "operations": (
            ("head.stage_mismatching_via_ui", "prepared_zero_progress"),
            ("app.close_simulated_session", "session_closed"),
            ("experiment.reload_inactive_via_ui", "reloaded_inactive"),
            ("array.start_inactive_via_ui", "reloaded_inactive"),
            ("experiment.activate_authoritative_via_ui", "active_zero_progress"),
            ("array.start_wrong_identity_via_ui", "active_zero_progress"),
            ("head.stage_matching_via_ui", "prepared_zero_progress"),
            ("calibration.generate_via_ui", "calibration_available_unapplied"),
            ("calibration.select_via_ui", "calibration_selected_unapplied"),
            ("calibration.apply_via_ui", "calibrated_zero_progress"),
            ("app.close_simulated_session", "session_closed"),
            ("experiment.reload_inactive_via_ui", "reloaded_inactive"),
            ("experiment.activate_authoritative_via_ui", "active_zero_progress"),
            ("array.start_pass_via_ui", "terminal"),
        ),
    },
    {
        "seed": 197,
        "sequence_id": "seed_197_illegal_progress_lock_recovery_terminal",
        "role": "illegal_progress_lock_recovery_terminal",
        "initial": "active_zero_progress",
        "sessions": 1,
        "rotations": 0,
        "screenshots": 4,
        "operations": (
            ("array.start_pass_via_ui", "progressed_locked"),
            ("editor.attempt_progressed_edit_via_ui", "progressed_locked"),
            ("calibration.attempt_progressed_apply_via_ui", "progressed_locked"),
            ("array.start_while_active_via_ui", "progressed_locked"),
            ("head.attempt_unsafe_exchange_via_ui", "progressed_locked"),
            ("array.start_pass_via_ui", "terminal"),
        ),
    },
)


def _from_profile(profile: Mapping[str, Any], *, seed: int | None = None, tier: str = "frozen") -> ExplorationSequence:
    actual_seed = int(profile["seed"] if seed is None else seed)
    role = str(profile["role"])
    sequence_id = str(profile["sequence_id"])
    if tier == "diagnostic":
        sequence_id = f"diagnostic_seed_{actual_seed}_{role}"
    sequence = ExplorationSequence(
        sequence_id=sequence_id,
        seed=actual_seed,
        seed_tier=tier,
        role=role,
        initial_state=str(profile["initial"]),
        steps=_steps(str(profile["initial"]), *profile["operations"]),
        sessions=int(profile["sessions"]),
        session_rotations=int(profile["rotations"]),
        screenshots=int(profile["screenshots"]),
        choice_token=_choice_token(actual_seed, role),
    )
    validate_sequence(sequence)
    return sequence


def validate_sequence(sequence: ExplorationSequence) -> None:
    if sequence.seed_tier not in {"frozen", "diagnostic"}:
        raise M13ExplorationValidationError("sequence seed tier is unsupported")
    if sequence.initial_state not in STATE_BY_ID or not sequence.steps:
        raise M13ExplorationValidationError("sequence initial state or steps are invalid")
    state = sequence.initial_state
    for step in sequence.steps:
        operation = OPERATION_BY_ID.get(step.operation_id)
        if operation is None:
            raise M13ExplorationValidationError("sequence operation is not oracle-admitted")
        if step.from_state != state or step.to_state not in STATE_BY_ID:
            raise M13ExplorationValidationError("sequence state continuity drifted")
        if (step.from_state, step.to_state) not in operation.transitions:
            raise M13ExplorationValidationError(
                "sequence transition is not admitted: "
                f"{step.operation_id} {step.from_state}->{step.to_state}"
            )
        if operation.expected_outcome == "rejected" and step.from_state != step.to_state:
            raise M13ExplorationValidationError("rejected operation mutated modeled state")
        if not operation.oracle_id or not operation.oracle_owner:
            raise M13ExplorationValidationError("sequence operation lacks deterministic oracle")
        state = step.to_state
    normalized = sequence.normalized()
    if state != "terminal":
        raise M13ExplorationValidationError("sequence does not reach terminal authority")
    limits = SEQUENCE_BUDGET.normalized()
    projected = {
        "semantic_operations": normalized["operation_count"],
        "action_rows": normalized["projected_action_rows"],
        "sessions": normalized["sessions"],
        "session_rotations": normalized["session_rotations"],
        "screenshots": normalized["screenshots"],
        **normalized["workload_projection"],
    }
    for name, value in projected.items():
        if int(value) > limits[name]:
            raise M13ExplorationValidationError(f"sequence exceeds {name} budget")


def _validate_catalog() -> None:
    if len(STATE_BY_ID) != len(STATES):
        raise M13ExplorationValidationError("state identities are not unique")
    if len(OPERATION_BY_ID) != len(OPERATIONS):
        raise M13ExplorationValidationError("operation identities are not unique")
    if tuple(item.seed for item in FROZEN_SEQUENCES) != FROZEN_SEEDS:
        raise M13ExplorationValidationError("frozen seed order drifted")
    if len({item.sequence_id for item in FROZEN_SEQUENCES}) != len(FROZEN_SEQUENCES):
        raise M13ExplorationValidationError("frozen sequence identities are not unique")
    reached_operations = {step.operation_id for item in FROZEN_SEQUENCES for step in item.steps}
    if reached_operations != set(OPERATION_BY_ID):
        raise M13ExplorationValidationError("frozen campaign operation coverage drifted")
    reached_states = {item.initial_state for item in FROZEN_SEQUENCES} | {
        step.to_state for item in FROZEN_SEQUENCES for step in item.steps
    }
    if reached_states != set(STATE_BY_ID):
        raise M13ExplorationValidationError("frozen campaign state coverage drifted")
    rejected = {
        item.operation_id for item in OPERATIONS if item.expected_outcome == "rejected"
    }
    if set(M13_REJECTION_CASES) != rejected:
        raise M13ExplorationValidationError("rejected operation case coverage drifted")


FROZEN_SEQUENCES = tuple(_from_profile(profile) for profile in _PROFILES)
_validate_catalog()


def sequence_ids() -> tuple[str, ...]:
    return tuple(item.sequence_id for item in FROZEN_SEQUENCES)


def get_sequence(sequence_id: str) -> ExplorationSequence:
    matches = [item for item in FROZEN_SEQUENCES if item.sequence_id == sequence_id]
    if len(matches) != 1:
        raise M13ExplorationValidationError(f"unsupported Milestone 13 sequence: {sequence_id!r}")
    return matches[0]


def generate_diagnostic_sequence(seed: int) -> ExplorationSequence:
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise M13ExplorationValidationError("diagnostic seed must be a non-negative integer")
    digest = hashlib.sha256(f"{GENERATOR_VERSION}:{seed}:profile".encode("utf-8")).digest()
    return _from_profile(_PROFILES[digest[0] % len(_PROFILES)], seed=seed, tier="diagnostic")


def sequence_from_normalized(payload: Mapping[str, Any]) -> ExplorationSequence:
    """Resolve exact retained sequence bytes without accepting semantic drift."""

    if not isinstance(payload, Mapping):
        raise M13ExplorationValidationError("normalized sequence must be an object")
    tier = payload.get("seed_tier")
    seed = payload.get("seed")
    if tier == "frozen":
        sequence = get_sequence(str(payload.get("sequence_id") or ""))
    elif tier == "diagnostic":
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise M13ExplorationValidationError(
                "diagnostic normalized sequence seed is invalid"
            )
        sequence = generate_diagnostic_sequence(seed)
    else:
        raise M13ExplorationValidationError(
            "normalized sequence seed tier is unsupported"
        )
    if sequence.normalized() != dict(payload):
        raise M13ExplorationValidationError(
            "retained normalized sequence differs from the reviewed generator output"
        )
    return sequence


def normalized_state_model() -> dict[str, Any]:
    return {
        "version": STATE_MODEL_VERSION,
        "rejection_overlay": "safely_rejected",
        "identity_policy": "durable_ids_never_ui_positions",
        "states": [item.normalized() for item in STATES],
    }


def normalized_operation_catalog() -> dict[str, Any]:
    return {
        "version": OPERATION_CATALOG_VERSION,
        "operations": [item.normalized() for item in OPERATIONS],
        "excluded_operations": {
            "editor.add_reagent_via_ui": "no complete real-Qt add/reload identity oracle",
            "editor.remove_reagent_via_ui": "no complete real-Qt remove/reload identity oracle",
            "editor.optimize_via_ui": (
                "qualified operator action is Update Reactions and Stock Solutions"
            ),
            "editor.generate_via_ui": (
                "qualified operator action is Update Reactions and Stock Solutions"
            ),
            "execution.refill_resume": "deferred while volume tracking is disabled",
            "persistence.mutate_active_authority": "prohibited outside isolated M12 fault fixtures",
        },
    }


def normalized_oracle_ledger() -> dict[str, Any]:
    return {
        "version": ORACLE_LEDGER_VERSION,
        "policy": "literal_existing_deterministic_oracle_required",
        "operations": [
            {
                "operation_id": item.operation_id,
                "oracle_id": item.oracle_id,
                "oracle_owner": item.oracle_owner,
                "expected_outcome": item.expected_outcome,
                "rejection_class": item.rejection_class,
                "shared_no_mutation_no_dispatch_required": item.expected_outcome == "rejected",
            }
            for item in OPERATIONS
        ],
    }


def normalized_frozen_catalog() -> dict[str, Any]:
    sequence_rows = [item.normalized() for item in FROZEN_SEQUENCES]
    sequence_hashes = [_sha256_json(item) for item in sequence_rows]
    fixture_projection = [
        {
            "sequence_id": item["sequence_id"],
            "durable_identity_contract": item["durable_identity_contract"],
            "workload_projection": item["workload_projection"],
        }
        for item in sequence_rows
    ]
    return {
        "campaign_id": CAMPAIGN_ID,
        "generator_version": GENERATOR_VERSION,
        "state_model_version": STATE_MODEL_VERSION,
        "operation_catalog_version": OPERATION_CATALOG_VERSION,
        "oracle_ledger_version": ORACLE_LEDGER_VERSION,
        "semantic_coverage_version": SEMANTIC_COVERAGE_VERSION,
        "seed_policy": {
            "frozen": list(FROZEN_SEEDS),
            "diagnostic_compatibility_samples": list(DIAGNOSTIC_COMPATIBILITY_SEEDS),
            "maximum_diagnostic_seeds_per_invocation": MAX_DIAGNOSTIC_SEEDS,
            "diagnostic_changes_release_gate": False,
        },
        "budgets": {
            "sequence": SEQUENCE_BUDGET.normalized(),
            "campaign": CAMPAIGN_BUDGET.normalized(),
        },
        "state_model_sha256": _sha256_json(normalized_state_model()),
        "operation_catalog_sha256": _sha256_json(normalized_operation_catalog()),
        "oracle_ledger_sha256": _sha256_json(normalized_oracle_ledger()),
        "frozen_sequence_sha256": sequence_hashes,
        "frozen_set_sha256": _sha256_json(sequence_hashes),
        "fixture_projection_sha256": _sha256_json(fixture_projection),
        "sequences": sequence_rows,
    }


def catalog_sha256() -> str:
    return _sha256_json(normalized_frozen_catalog())


def campaign_sha256() -> str:
    catalog = normalized_frozen_catalog()
    return _sha256_json(
        {
            "campaign_id": CAMPAIGN_ID,
            "generator_version": GENERATOR_VERSION,
            "catalog_sha256": catalog_sha256(),
            "frozen_set_sha256": catalog["frozen_set_sha256"],
            "fixture_projection_sha256": catalog["fixture_projection_sha256"],
            "budgets": catalog["budgets"],
        }
    )


def _validate_frozen_hashes() -> None:
    catalog = normalized_frozen_catalog()
    actual = {
        "state model": catalog["state_model_sha256"],
        "operation catalog": catalog["operation_catalog_sha256"],
        "oracle ledger": catalog["oracle_ledger_sha256"],
        "frozen set": catalog["frozen_set_sha256"],
        "fixture projection": catalog["fixture_projection_sha256"],
        "catalog": catalog_sha256(),
        "campaign": campaign_sha256(),
    }
    expected = {
        "state model": EXPECTED_STATE_MODEL_SHA256,
        "operation catalog": EXPECTED_OPERATION_CATALOG_SHA256,
        "oracle ledger": EXPECTED_ORACLE_LEDGER_SHA256,
        "frozen set": EXPECTED_FROZEN_SET_SHA256,
        "fixture projection": EXPECTED_FIXTURE_PROJECTION_SHA256,
        "catalog": EXPECTED_CATALOG_SHA256,
        "campaign": EXPECTED_CAMPAIGN_SHA256,
    }
    if actual != expected or tuple(catalog["frozen_sequence_sha256"]) != EXPECTED_SEQUENCE_SHA256:
        raise M13ExplorationValidationError("reviewed Milestone 13 frozen hashes drifted")


_validate_frozen_hashes()


def resolve_plan(
    *,
    sequence_id: str | None = None,
    timeout_seconds: float = 270.0,
    execution_authorized: bool = False,
    seed_tier: str = "frozen",
    diagnostic_seeds: Sequence[int] = (),
) -> dict[str, Any]:
    if not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise M13ExplorationValidationError("exploration timeout is invalid")
    if float(timeout_seconds) > SEQUENCE_BUDGET.scenario_deadline_seconds:
        raise M13ExplorationValidationError("exploration timeout exceeds the frozen deadline")
    if seed_tier not in {"frozen", "diagnostic"}:
        raise M13ExplorationValidationError("seed tier is unsupported")
    if seed_tier == "frozen":
        if diagnostic_seeds:
            raise M13ExplorationValidationError("diagnostic seeds cannot alter the frozen tier")
        selected = (get_sequence(sequence_id),) if sequence_id else FROZEN_SEQUENCES
    else:
        if sequence_id is not None:
            raise M13ExplorationValidationError("diagnostic planning does not accept a frozen sequence ID")
        if not diagnostic_seeds:
            raise M13ExplorationValidationError("diagnostic tier requires an explicit diagnostic seed")
        if len(diagnostic_seeds) > MAX_DIAGNOSTIC_SEEDS or len(set(diagnostic_seeds)) != len(diagnostic_seeds):
            raise M13ExplorationValidationError("diagnostic seed selection exceeds its unique-seed cap")
        selected = tuple(generate_diagnostic_sequence(seed) for seed in diagnostic_seeds)
    rows = [
        {
            "order": index,
            "sequence": item.normalized(),
            "sequence_sha256": _sha256_json(item.normalized()),
        }
        for index, item in enumerate(selected, 1)
    ]
    return {
        "schema_name": PLAN_SCHEMA_NAME,
        "schema_version": PLAN_SCHEMA_VERSION,
        "campaign": {
            "id": CAMPAIGN_ID,
            "generator_version": GENERATOR_VERSION,
            "catalog_sha256": catalog_sha256(),
            "campaign_sha256": campaign_sha256(),
            "state_model_sha256": _sha256_json(normalized_state_model()),
            "operation_catalog_sha256": _sha256_json(normalized_operation_catalog()),
            "oracle_ledger_sha256": _sha256_json(normalized_oracle_ledger()),
        },
        "platform": "windows_sil",
        "seed_tier": seed_tier,
        "timeout_seconds": float(timeout_seconds),
        "sequence_count": len(rows),
        "sequences": rows,
        "execution_authorized": bool(execution_authorized),
        "release_gate_affected": seed_tier == "frozen",
    }


def catalog_descriptor() -> dict[str, Any]:
    return {
        "id": CAMPAIGN_ID,
        "generator_version": GENERATOR_VERSION,
        "schema_version": PLAN_SCHEMA_VERSION,
        "fixed_seeds": list(FROZEN_SEEDS),
        "sequence_ids": list(sequence_ids()),
        "sequence_count": len(FROZEN_SEQUENCES),
        "maximum_actions": SEQUENCE_BUDGET.semantic_operations,
        "maximum_action_rows": SEQUENCE_BUDGET.action_rows,
        "catalog_sha256": catalog_sha256(),
        "campaign_sha256": campaign_sha256(),
        "platform": "windows_sil",
        "execution": "fresh_process_aggregate_or_explicit_sequence",
        "diagnostic_seed_policy": "explicit_nonblocking",
    }


__all__ = [
    "CAMPAIGN_BUDGET",
    "CAMPAIGN_ID",
    "DIAGNOSTIC_COMPATIBILITY_SEEDS",
    "EXPECTED_CAMPAIGN_SHA256",
    "EXPECTED_CATALOG_SHA256",
    "EXPECTED_FIXTURE_PROJECTION_SHA256",
    "EXPECTED_FROZEN_SET_SHA256",
    "EXPECTED_OPERATION_CATALOG_SHA256",
    "EXPECTED_ORACLE_LEDGER_SHA256",
    "EXPECTED_SEQUENCE_SHA256",
    "EXPECTED_STATE_MODEL_SHA256",
    "FROZEN_SEEDS",
    "FROZEN_SEQUENCES",
    "GENERATOR_VERSION",
    "MAX_DIAGNOSTIC_SEEDS",
    "M13ExplorationValidationError",
    "M13_REJECTION_CASES",
    "OPERATIONS",
    "OPERATION_CATALOG_VERSION",
    "ORACLE_LEDGER_VERSION",
    "PLAN_SCHEMA_NAME",
    "PLAN_SCHEMA_VERSION",
    "SEMANTIC_COVERAGE_VERSION",
    "SEQUENCE_BUDGET",
    "STATES",
    "STATE_MODEL_VERSION",
    "catalog_descriptor",
    "catalog_sha256",
    "campaign_sha256",
    "generate_diagnostic_sequence",
    "get_sequence",
    "normalized_frozen_catalog",
    "normalized_operation_catalog",
    "normalized_oracle_ledger",
    "normalized_state_model",
    "resolve_plan",
    "sequence_from_normalized",
    "sequence_sha256",
    "sequence_ids",
    "validate_sequence",
]
