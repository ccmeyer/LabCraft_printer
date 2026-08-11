"""Literal Milestone 12 calibration, identity, and lifecycle safeguards."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.virtual_workflows.safeguards import (
    ExpectedSafeguardOutcome,
    SafeguardCase,
    SafeguardCatalog,
    SafeguardContractError,
)


EXECUTION_PREFLIGHT_MATRIX_ID = "execution_preflight_safeguards_v1"
EXECUTION_PREFLIGHT_BASE_SCENARIO_ID = "experiment_editor_create_finalize_v1"
EXECUTION_PREFLIGHT_JOURNEY_FAMILY = "execution_preflight_safeguards"
EXECUTION_PREFLIGHT_CATALOG_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "execution_preflight_safeguards_v1.json"
)

EXPECTED_CASE_IDS = (
    "calibration_head_mode_cancelled",
    "calibration_pulse_profile_cancelled",
    "start_missing_applied_calibration_cancelled",
    "start_stale_design_volume_cancelled",
    "start_pulse_width_mismatch_cancelled",
    "start_pressure_mismatch_cancelled",
    "wrong_stock_calibration_binding_rejected",
    "wrong_printer_head_calibration_binding_rejected",
    "reordered_stock_rows_keyed_valid",
    "regenerated_design_stale_calibration_rejected",
    "inspected_not_activated_start_rejected",
    "invalid_activation_rejected",
    "active_execution_edit_rejected",
    "progressed_stock_recalibration_rejected",
    "start_while_active_rejected",
    "resume_at_invalid_boundary_rejected",
    "head_exchange_at_invalid_boundary_rejected",
)


def _load_source() -> dict[str, Any]:
    try:
        payload = json.loads(EXECUTION_PREFLIGHT_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SafeguardContractError(f"cannot load execution-preflight catalog: {exc}") from exc
    if payload.get("schema_version") != 1:
        raise SafeguardContractError("execution-preflight catalog version drifted")
    if payload.get("catalog_id") != EXECUTION_PREFLIGHT_MATRIX_ID:
        raise SafeguardContractError("execution-preflight catalog identity drifted")
    if payload.get("base_scenario_id") != EXECUTION_PREFLIGHT_BASE_SCENARIO_ID:
        raise SafeguardContractError("execution-preflight base scenario drifted")
    return payload


def _expand_case(row: dict[str, Any]) -> SafeguardCase:
    safe_inactive = bool(row.get("safe_inactive", False))
    ui_kind = str(row["ui_kind"])
    ui_surface = "dialog" if ui_kind in {"calibration_preflight", "start_choice", "message"} else "control_state"
    expected = ExpectedSafeguardOutcome(
        outcome_kind="safe_inactive" if safe_inactive else "typed_rejection",
        classification=str(row["classification"]),
        code=str(row["code"]),
        message=str(row["message"]),
        ui_surface=ui_surface,
        ui_title=row.get("title"),
        selected_control=("Inspect Saved Execution" if safe_inactive else ("Cancel" if ui_kind in {"calibration_preflight", "start_choice"} else ("OK" if ui_kind == "message" else str(row["action_label"])))),
        workflow_state=str(row["workflow_state"]),
        queue_state=(
            "stop_requested"
            if row["workflow_state"] == "stop_requested"
            else "idle"
        ),
        runtime_active=bool(row.get("runtime_active", False)),
    )
    return SafeguardCase(
        case_id=str(row["case_id"]),
        family=str(row["family"]),
        fixture_id=str(row["fixture_id"]),
        operator_action_id=str(row["action_id"]),
        operator_action_label=str(row["action_label"]),
        invalid_invariant=str(row["invalid_invariant"]),
        expected=expected,
        identity_keys=dict(row["identity_keys"]),
        setup={
            "driver": "execution_preflight_safeguard",
            "ui_kind": ui_kind,
            "literal_preflight": {
                "ok": safe_inactive,
                "code": str(row["code"]),
                "message": str(row["message"]),
                "title": row.get("title"),
            },
        },
        fresh_process_required=True,
        visible_required=bool(row.get("visible_required", False)),
    )


def execution_preflight_catalog() -> SafeguardCatalog:
    payload = _load_source()
    rows = payload.get("cases")
    if not isinstance(rows, list):
        raise SafeguardContractError("execution-preflight cases must be a list")
    catalog = SafeguardCatalog(cases=tuple(_expand_case(dict(row)) for row in rows))
    if tuple(case.case_id for case in catalog.cases) != EXPECTED_CASE_IDS:
        raise SafeguardContractError("execution-preflight case order or identity drifted")
    return catalog


def execution_preflight_cases() -> tuple[SafeguardCase, ...]:
    return execution_preflight_catalog().cases


def get_execution_preflight_case(case_id: str) -> SafeguardCase:
    matches = [case for case in execution_preflight_cases() if case.case_id == str(case_id)]
    if len(matches) != 1:
        raise SafeguardContractError(f"unsupported execution-preflight safeguard: {case_id!r}")
    return matches[0]


def build_execution_preflight_fixture(case: SafeguardCase) -> tuple[dict[str, Any], Path]:
    if case.case_id not in EXPECTED_CASE_IDS:
        raise SafeguardContractError("execution-preflight fixture received an unknown case")
    fixture = {
        "schema_version": 1,
        "fixture_id": EXECUTION_PREFLIGHT_BASE_SCENARIO_ID,
        "experiment": {
            "name": case.fixture_id,
            "plate_name": "shallow-384_well_plate",
        },
        "workload": {"completion_count": 0},
        "lifecycle": {
            "matrix_id": EXECUTION_PREFLIGHT_MATRIX_ID,
            "catalog_sha256": execution_preflight_catalog().contract_sha256,
            "case_sha256": case.contract_sha256,
            "case": case.to_dict(),
        },
    }
    return fixture, EXECUTION_PREFLIGHT_CATALOG_PATH


__all__ = [
    "EXECUTION_PREFLIGHT_BASE_SCENARIO_ID",
    "EXECUTION_PREFLIGHT_CATALOG_PATH",
    "EXECUTION_PREFLIGHT_JOURNEY_FAMILY",
    "EXECUTION_PREFLIGHT_MATRIX_ID",
    "EXPECTED_CASE_IDS",
    "build_execution_preflight_fixture",
    "execution_preflight_cases",
    "execution_preflight_catalog",
    "get_execution_preflight_case",
]
