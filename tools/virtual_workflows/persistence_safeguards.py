"""Contained authoritative-persistence fault fixtures for Milestone 12."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from tools.virtual_workflows.safeguards import (
    ExpectedSafeguardOutcome,
    PersistenceFaultSpec,
    SafeguardCase,
    SafeguardCatalog,
    SafeguardContractError,
)


PERSISTENCE_SAFEGUARD_MATRIX_ID = "authoritative_persistence_safeguards_v1"
PERSISTENCE_SAFEGUARD_BASE_SCENARIO_ID = "experiment_editor_create_finalize_v1"
PERSISTENCE_SAFEGUARD_JOURNEY_FAMILY = "persistence_safeguards"
PERSISTENCE_SAFEGUARD_CATALOG_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "authoritative_persistence_safeguards_v1.json"
)

EXPECTED_CASE_IDS = (
    "unreflected_pending_intent_blocked",
    "positive_progress_without_checkpoint_blocked",
    "checkpoint_plan_revision_conflict_blocked",
    "checkpoint_progress_fingerprint_conflict_blocked",
    "progress_plan_revision_conflict_invalid",
    "latest_plan_history_conflict_invalid",
    "progressed_calibration_link_missing_invalid",
    "design_plan_hash_conflict_invalid",
    "incomplete_authoritative_bundle_invalid",
)

PLAN_ID = "a5e8dc75-6540-45c1-8898-a18e68f1cf00"
SESSION_ID = "394d8719-50ec-458a-bc4c-60d65707182e"
HEAD_ID = "m12-persistence-head-a"
STOCK_ID = "Compact A_10.00_mM"
NOW = "2026-08-09T07:30:00Z"
ABSENT_SHA256 = hashlib.sha256(b"<absent>").hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inventory(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _load_source() -> dict[str, Any]:
    try:
        payload = json.loads(PERSISTENCE_SAFEGUARD_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SafeguardContractError(f"cannot load persistence safeguard catalog: {exc}") from exc
    if payload.get("schema_version") != 1:
        raise SafeguardContractError("persistence safeguard catalog version drifted")
    if payload.get("catalog_id") != PERSISTENCE_SAFEGUARD_MATRIX_ID:
        raise SafeguardContractError("persistence safeguard catalog identity drifted")
    if payload.get("base_scenario_id") != PERSISTENCE_SAFEGUARD_BASE_SCENARIO_ID:
        raise SafeguardContractError("persistence safeguard base scenario drifted")
    return payload


def _expand_case(row: Mapping[str, Any]) -> SafeguardCase:
    technical_message = str(row["message"])
    operator_messages = {
        "blocked_ambiguous_intent": (
            "The app cannot determine whether some droplets were printed. Printing "
            "is unavailable to prevent duplicate dispensing."
        ),
        "blocked_missing_checkpoint": (
            "Saved progress is incomplete, so this experiment cannot be resumed safely."
        ),
        "blocked_checkpoint_reference": (
            "The saved progress does not match this version of the experiment. "
            "Printing is unavailable."
        ),
        "blocked_checkpoint_progress": (
            "The saved progress does not match the experiment data. Printing is "
            "unavailable."
        ),
        "authoritative_bundle_invalid": (
            "The saved experiment data could not be validated. Printing is unavailable."
        ),
    }
    expected = ExpectedSafeguardOutcome(
        outcome_kind="persistence_classification",
        classification=str(row["classification"]),
        code=str(row["code"]),
        message=operator_messages[str(row["classification"])],
        ui_surface="load_status",
        ui_title=None,
        selected_control="Experiment Locked",
        workflow_state="analysis_only_inactive",
        queue_state="idle",
    )
    fault = PersistenceFaultSpec(
        relative_path=str(row["relative_path"]),
        operation=str(row["operation"]),
        phase="prelaunch",
        original_sha256=str(row["original_sha256"]),
        faulted_sha256=str(row["faulted_sha256"]),
    )
    return SafeguardCase(
        case_id=str(row["case_id"]),
        family="persistence",
        fixture_id=str(row["fixture_id"]),
        operator_action_id="experiment.load_rejected_authoritative_via_ui",
        operator_action_label="Select Experiment Folder",
        invalid_invariant=str(row["invalid_invariant"]),
        expected=expected,
        identity_keys=dict(row["identity_keys"]),
        setup={
            "driver": "persistence_safeguard",
            "baseline_kind": str(row["baseline_kind"]),
            "mutation_kind": str(row["mutation_kind"]),
            "technical_message": technical_message,
        },
        fault=fault,
        fresh_process_required=True,
        replay_required=True,
        visible_required=bool(row.get("visible_required", False)),
    )


def persistence_safeguard_catalog() -> SafeguardCatalog:
    rows = _load_source().get("cases")
    if not isinstance(rows, list):
        raise SafeguardContractError("persistence safeguard cases must be a list")
    catalog = SafeguardCatalog(cases=tuple(_expand_case(dict(row)) for row in rows))
    if tuple(case.case_id for case in catalog.cases) != EXPECTED_CASE_IDS:
        raise SafeguardContractError("persistence safeguard case order or identity drifted")
    return catalog


def persistence_safeguard_cases() -> tuple[SafeguardCase, ...]:
    return persistence_safeguard_catalog().cases


def get_persistence_safeguard_case(case_id: str) -> SafeguardCase:
    matches = [case for case in persistence_safeguard_cases() if case.case_id == str(case_id)]
    if len(matches) != 1:
        raise SafeguardContractError(f"unsupported persistence safeguard: {case_id!r}")
    return matches[0]


def build_persistence_safeguard_fixture(case: SafeguardCase) -> tuple[dict[str, Any], Path]:
    if case.case_id not in EXPECTED_CASE_IDS:
        raise SafeguardContractError("persistence fixture received an unknown case")
    return (
        {
            "schema_version": 1,
            "fixture_id": PERSISTENCE_SAFEGUARD_BASE_SCENARIO_ID,
            "experiment": {"name": case.fixture_id, "plate_name": "shallow-384_well_plate"},
            "workload": {"completion_count": 0},
            "lifecycle": {
                "matrix_id": PERSISTENCE_SAFEGUARD_MATRIX_ID,
                "catalog_sha256": persistence_safeguard_catalog().contract_sha256,
                "case_sha256": case.contract_sha256,
                "case": case.to_dict(),
            },
        },
        PERSISTENCE_SAFEGUARD_CATALOG_PATH,
    )


def _design(name: str) -> dict[str, Any]:
    return {
        "metadata": {
            "name": name,
            "plate_name": "shallow-384_well_plate",
            "replicates": 1,
            "target_reaction_volume_nL": 160.0,
            "final_reaction_volume_nL": 160.0,
            "printed_volume_tolerance_nL": 1.0,
            "fill_reagent_name": "Water",
            "fill_droplet_volume_nL": 10.0,
        },
        "stock_prep": {},
        "applied_imaging_calibrations": {},
        "manual_refuel_checks": {},
        "factors": [
            {
                "name": "Compact A",
                "kind": "additive",
                "options": [
                    {
                        "name": "Compact A",
                        "targets": [1.0],
                        "units": "mM",
                        "droplet_nL": 10.0,
                        "printing_mode": "droplet",
                        "starting_conc": 10.0,
                        "forced_stock_conc": 10.0,
                        "max_stock_conc": None,
                    }
                ],
            }
        ],
        "additional_conditions": {"schema_version": 1, "conditions": []},
    }


def _write_pristine_bundle(root: Path, *, baseline_kind: str, name: str) -> None:
    from ExecutionCalibrationStore import (
        ExecutionCalibrationDocument,
        ExecutionCalibrationRecord,
        deterministic_calibration_record_id,
        save_execution_calibrations,
    )
    from ExecutionPlan import (
        ExecutionDispense,
        ExecutionPlan,
        ExecutionPlanState,
        ExecutionPlate,
        ExecutionStock,
        ExecutionVolumeBasis,
        ExecutionWell,
        ProgressExecutionReference,
        canonical_sha256,
        save_execution_plan,
    )
    from ExecutionPlanRevision import persist_immutable_revision
    from ExecutionResumeStore import new_resume_document, save_execution_resume

    if root.exists():
        raise SafeguardContractError("pristine persistence fixture already exists")
    root.mkdir(parents=True, exist_ok=False)
    progressed = baseline_kind in {"progressed_checkpoint", "calibrated_progressed_checkpoint"}
    calibrated = baseline_kind == "calibrated_progressed_checkpoint"
    added = 3 if progressed else 0
    design = _design(name)
    calibration_record = None
    calibration_key = None
    if calibrated:
        payload = {
            "stock_id": STOCK_ID,
            "printer_head_id": HEAD_ID,
            "factor_name": "Compact A",
            "option_name": None,
            "is_fill": False,
            "measured_volume_nL": 10.0,
            "effective_volume_nL": 10.0,
            "pw_us": 1300,
            "pressure_psi": 1.2,
            "run_id": "m12-persistence-calibration",
            "phase": "verification",
            "timestamp": NOW,
            "source_row_fingerprint": ["m12", 10.0],
            "original_printing_mode": "droplet",
            "applied_printing_mode": "droplet",
        }
        calibration_key = deterministic_calibration_record_id(PLAN_ID, payload)
        calibration_record = ExecutionCalibrationRecord(
            record_id=calibration_key,
            printing_mode="droplet",
            applied_design_volume_nL=10.0,
            recorded_at=NOW,
            recorded_at_utc=NOW,
            **{**payload, "source_row_fingerprint": tuple(payload["source_row_fingerprint"])},
        )
    stock = ExecutionStock(
        stock_id=STOCK_ID,
        factor_name="Compact A",
        option_name=None,
        reagent_name="Compact A",
        concentration=10.0,
        units="mM",
        printing_mode="droplet",
        intended_volume_nL=10.0,
        effective_volume_nL=10.0,
        printer_head_id=HEAD_ID if calibrated else None,
        calibration_record_key=calibration_key,
    )
    plan = ExecutionPlan(
        plan_id=PLAN_ID,
        plan_revision=1,
        state=ExecutionPlanState.PREPARED,
        design_sha256=canonical_sha256(design),
        created_at_utc=NOW,
        updated_at_utc=NOW,
        locked_at_utc=None,
        lock_reason=None,
        plate=ExecutionPlate("shallow-384_well_plate", 16, 24),
        volume_basis=ExecutionVolumeBasis(160.0, 160.0, 1.0),
        stocks=(stock,),
        wells=(ExecutionWell("A1", "m12-reaction-a1", (ExecutionDispense(STOCK_ID, 16),), 160.0),),
    )
    (root / "experiment_design.json").write_text(
        json.dumps(design, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    save_execution_plan(root / "execution_plan.json", plan)
    persist_immutable_revision(root / "execution_plan_revisions", plan)
    progress = {
        "A1": {
            "reaction_id": "m12-reaction-a1",
            "reagents": {STOCK_ID: {"target_droplets": 16, "added_droplets": added}},
            "completed": False,
        },
        "__plate__": {"name": "shallow-384_well_plate", "rows": 16, "columns": 24, "schema_version": 1},
        "__execution__": ProgressExecutionReference(PLAN_ID, 1).to_dict(),
    }
    (root / "progress.json").write_text(
        json.dumps(progress, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    (root / "calibration.json").write_text(
        json.dumps({"schema_version": 1, "runs": []}, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    wells = {"A1": progress["A1"]}
    resume = new_resume_document(
        plan_id=PLAN_ID,
        plan_revision=1,
        progress_wells=wells,
        session_id=SESSION_ID,
        timestamp_utc=NOW,
    )
    save_execution_resume(root / "execution_resume.json", resume)
    if calibration_record is not None:
        save_execution_calibrations(
            root / "execution_calibrations.json",
            ExecutionCalibrationDocument(PLAN_ID, {calibration_key: calibration_record}),
        )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    json.loads(path.read_text(encoding="utf-8"))


def _mutate(root: Path, case: SafeguardCase) -> dict[str, Any]:
    from ExecutionResumeStore import add_pending_intent, load_execution_resume, save_execution_resume

    target = (root / case.fault.relative_path).resolve()
    if not target.is_relative_to(root.resolve()):
        raise SafeguardContractError("persistence fault target escaped its case copy")
    kind = str(case.setup["mutation_kind"])
    original_hash = _sha256(target)
    if kind == "add_unreflected_pending_intent":
        document = load_execution_resume(target)
        document, intent = add_pending_intent(
            document,
            well_id="A1",
            reaction_id="m12-reaction-a1",
            stock_id=STOCK_ID,
            baseline_added=0,
            commanded_droplets=4,
            printer_head_id=HEAD_ID,
            timestamp_utc=NOW,
        )
        save_execution_resume(target, document)
        detail = {"ambiguous_intent_id": intent.intent_id}
    elif kind == "remove_resume":
        target.unlink()
        detail = {}
    elif kind == "resume_plan_revision":
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["plan_revision"] = 2
        _write_json(target, payload)
        detail = {}
    elif kind == "progress_after_checkpoint":
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["A1"]["reagents"][STOCK_ID]["added_droplets"] = 4
        _write_json(target, payload)
        detail = {}
    elif kind == "progress_plan_revision":
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["__execution__"]["plan_revision"] = 2
        _write_json(target, payload)
        detail = {}
    elif kind == "latest_plan_history_conflict":
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["updated_at_utc"] = "2026-08-09T07:31:00Z"
        _write_json(target, payload)
        detail = {}
    elif kind in {"remove_calibration_sidecar", "remove_progress"}:
        target.unlink()
        detail = {}
    elif kind == "design_hash_conflict":
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["metadata"]["name"] = "m12-mutated-design"
        _write_json(target, payload)
        detail = {}
    else:
        raise SafeguardContractError(f"unsupported persistence mutation {kind!r}")
    mutated_hash = _sha256(target) if target.is_file() else None
    contract_faulted_hash = mutated_hash or ABSENT_SHA256
    if original_hash != case.fault.original_sha256:
        raise SafeguardContractError("pristine fault target hash drifted")
    if contract_faulted_hash != case.fault.faulted_sha256:
        raise SafeguardContractError("faulted target hash drifted")
    return {
        "relative_path": case.fault.relative_path,
        "operation": case.fault.operation,
        "phase": "prelaunch",
        "original_sha256": original_hash,
        "mutated_sha256": mutated_hash,
        "faulted_contract_sha256": contract_faulted_hash,
        **detail,
    }


@dataclass(frozen=True)
class PreparedPersistenceFault:
    source_root: Path
    faulted_root: Path
    source_inventory: Mapping[str, str]
    faulted_inventory: Mapping[str, str]
    fault_manifest: Mapping[str, Any]
    fault_manifest_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_root": str(self.source_root),
            "faulted_root": str(self.faulted_root),
            "source_inventory": dict(self.source_inventory),
            "faulted_inventory": dict(self.faulted_inventory),
            "fault_manifest": dict(self.fault_manifest),
            "fault_manifest_path": str(self.fault_manifest_path),
        }


def prepare_persistence_fault(case: SafeguardCase, scenario_root: Path) -> PreparedPersistenceFault:
    root = Path(scenario_root).resolve()
    marker = root / "session.json"
    if not marker.is_file():
        raise SafeguardContractError("persistence faults require an initialized SIL session root")
    case_root = (root / "experiments" / "m12-persistence" / case.case_id).resolve()
    if not case_root.is_relative_to(root) or case_root.exists():
        raise SafeguardContractError("persistence case root is unsafe or already exists")
    source = case_root / "source"
    faulted = case_root / "faulted"
    _write_pristine_bundle(
        source,
        baseline_kind=str(case.setup["baseline_kind"]),
        name=case.fixture_id,
    )
    source_before = _inventory(source)
    if any(path.is_symlink() for path in source.rglob("*")):
        raise SafeguardContractError("persistence source cannot contain symlinks")
    shutil.copytree(source, faulted)
    mutation = _mutate(faulted, case)
    source_after = _inventory(source)
    faulted_inventory = _inventory(faulted)
    if source_after != source_before:
        raise SafeguardContractError("pristine persistence source was modified")
    changed = sorted(
        key for key in set(source_before) | set(faulted_inventory)
        if source_before.get(key) != faulted_inventory.get(key)
    )
    if changed != [case.fault.relative_path]:
        raise SafeguardContractError(f"persistence fault changed unexpected files: {changed}")
    manifest = {
        "schema_version": 1,
        "case_id": case.case_id,
        "case_sha256": case.contract_sha256,
        "source_root": str(source),
        "faulted_root": str(faulted),
        "application_launched": False,
        "mutation_count": 1,
        "changed_paths": changed,
        **mutation,
    }
    manifest_path = case_root / "fault_manifest.json"
    _write_json(manifest_path, manifest)
    return PreparedPersistenceFault(
        source,
        faulted,
        source_before,
        faulted_inventory,
        manifest,
        manifest_path,
    )


def persistence_fixture_inventory(root: Path) -> dict[str, str]:
    """Return deterministic file hashes for one already-contained fixture."""

    resolved = Path(root).resolve()
    if not resolved.is_dir():
        raise SafeguardContractError("persistence fixture inventory root is missing")
    return _inventory(resolved)


__all__ = [
    "ABSENT_SHA256",
    "EXPECTED_CASE_IDS",
    "PERSISTENCE_SAFEGUARD_BASE_SCENARIO_ID",
    "PERSISTENCE_SAFEGUARD_CATALOG_PATH",
    "PERSISTENCE_SAFEGUARD_JOURNEY_FAMILY",
    "PERSISTENCE_SAFEGUARD_MATRIX_ID",
    "PreparedPersistenceFault",
    "build_persistence_safeguard_fixture",
    "get_persistence_safeguard_case",
    "persistence_safeguard_cases",
    "persistence_safeguard_catalog",
    "persistence_fixture_inventory",
    "prepare_persistence_fault",
]
