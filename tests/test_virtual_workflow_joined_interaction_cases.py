from __future__ import annotations

import json
import ast
from dataclasses import replace

import pytest

from tools.virtual_workflows.joined_interaction_cases import (
    DESIGN_A_STOCK_ID,
    DESIGN_B_STOCK_ID,
    EXPECTED_STOCK_IDS,
    EXPECTED_WELL_IDS,
    JOINED_INTERACTION_CASE,
    JOINED_INTERACTION_CASE_ID,
    JOINED_INTERACTION_FIXTURE_PATH,
    WATER_STOCK_ID,
    JoinedInteractionCaseError,
    joined_fixture_sha256,
    load_joined_interaction_case,
    validate_joined_interaction_case,
    validate_source_compatibility,
)
from tools.virtual_workflows.registry import registered_scenario_ids


EXPECTED_CASE_SHA256 = (
    "95abfc7be2fcb38744d374be8d7af7060fbe5636d7577b3417a7d6082843d992"
)
EXPECTED_FIXTURE_SHA256 = (
    "f27c0331a367a1a104d11582348f602aa8868c904d8d3d22193bceefd6dc45cc"
)
EXPECTED_COUNT_ORACLE_SHA256 = (
    "930a85b245db04e18f4ed9963070baddf18740d39426a33475116ef33b3eb84e"
)


def test_singleton_fixture_and_normalized_hashes_are_exact():
    loaded = load_joined_interaction_case()

    assert loaded == JOINED_INTERACTION_CASE
    assert loaded.case_id == JOINED_INTERACTION_CASE_ID
    assert loaded.sha256() == EXPECTED_CASE_SHA256
    assert joined_fixture_sha256() == EXPECTED_FIXTURE_SHA256
    assert loaded.count_oracle_sha256() == EXPECTED_COUNT_ORACLE_SHA256
    assert json.loads(JOINED_INTERACTION_FIXTURE_PATH.read_text(encoding="utf-8")) == (
        loaded.normalized()
    )


def test_joined_oracle_has_no_production_application_import_boundary():
    source = (
        JOINED_INTERACTION_FIXTURE_PATH.parent.parent / "joined_interaction_cases.py"
    ).read_text(encoding="utf-8")
    imported = {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        str(node.module)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    }

    assert not any(
        name.startswith(("FreeRTOS-interface", "Model", "Controller", "View"))
        for name in imported
    )
    assert "normalize_stock_well_counts" not in source


def test_source_hashes_assignment_and_prepared_counts_join_qualified_truth():
    audit = validate_source_compatibility(JOINED_INTERACTION_CASE)

    assert audit["complete"] is True
    assert JOINED_INTERACTION_CASE.editor.random_seed == 4321
    assert [(row.well_id, row.reaction_id) for row in JOINED_INTERACTION_CASE.assignments] == [
        ("A1", "R8"), ("A2", "R6"), ("A3", "R3"), ("A4", "R2"),
        ("A5", "R7"), ("A6", "R4"), ("A7", "R1"), ("A8", "R5"),
    ]
    assert set(JOINED_INTERACTION_CASE.oracle("prepared").keyed()) == {
        (stock_id, well_id)
        for stock_id in EXPECTED_STOCK_IDS
        for well_id in EXPECTED_WELL_IDS
    }


def test_calibration_revision_head_and_fresh_session_identity_joins_are_literal():
    case = JOINED_INTERACTION_CASE

    assert [row.stock_id for row in case.calibrations] == [
        DESIGN_A_STOCK_ID, WATER_STOCK_ID, DESIGN_B_STOCK_ID
    ]
    assert [(row.input_revision, row.output_revision) for row in case.calibrations] == [
        (2, 3), (3, 4), (4, 5)
    ]
    assert [row.printer_head_id for row in case.calibrations] == [
        "virtual-head-m11-design-a-v1",
        "virtual-head-m11-water-v1",
        "virtual-head-m11-design-b-v1",
    ]
    assert [row.session for row in case.checkpoints] == [1, 1, 1, 2, 2, 2, 2, 2, 3]
    loaded, activated = case.checkpoints[3:5]
    assert loaded.plan_revision == activated.plan_revision == 3
    assert loaded.resume_reference_revision is None
    assert loaded.eligibility == "ready_to_start"
    assert activated.resume_reference_revision == 3
    assert activated.eligibility == "active"


def test_every_count_is_stock_well_keyed_and_design_b_is_unchanged():
    case = JOINED_INTERACTION_CASE
    prepared = case.oracle("prepared").keyed()
    design_a = case.oracle("calibrated_zero_progress").keyed()
    final = case.oracle("all_stocks_calibrated").keyed()
    expected_b = {"A1": 3, "A2": 3, "A3": 1, "A4": 3, "A5": 1, "A6": 3, "A7": 1, "A8": 1}

    assert all(len(oracle.rows) == 24 for oracle in case.count_oracles)
    assert {
        well_id: prepared[(DESIGN_B_STOCK_ID, well_id)] for well_id in EXPECTED_WELL_IDS
    } == expected_b
    assert all(
        prepared[(DESIGN_B_STOCK_ID, well_id)]
        == design_a[(DESIGN_B_STOCK_ID, well_id)]
        == final[(DESIGN_B_STOCK_ID, well_id)]
        for well_id in EXPECTED_WELL_IDS
    )
    assert {(row.stock_id, row.expected_intents, row.expected_droplets) for row in case.execution_passes} == {
        (DESIGN_A_STOCK_ID, 8, 8),
        (DESIGN_B_STOCK_ID, 8, 16),
        (WATER_STOCK_ID, 8, 56),
    }
    assert (case.terminal.expected_intents, case.terminal.expected_droplets) == (24, 80)


def test_qualification_contract_is_exact_but_scenario_is_not_registered_yet():
    qualification = JOINED_INTERACTION_CASE.qualification

    assert (qualification.cli_seed, qualification.action_cap) == (1, 96)
    assert (
        qualification.offscreen_timeout_seconds,
        qualification.visible_timeout_seconds,
        qualification.visible_speed,
    ) == (180, 240, 20)
    assert qualification.required_screenshots == (
        "design_generated", "prepared_randomized", "calibrated_zero_progress",
        "fresh_loaded", "fresh_activated", "remaining_stocks_calibrated",
        "design_a_pass_complete", "design_b_pass_complete",
        "water_pass_complete", "completed", "terminal_reloaded",
    )
    assert JOINED_INTERACTION_CASE_ID not in registered_scenario_ids()


@pytest.mark.parametrize(
    "changed",
    [
        replace(JOINED_INTERACTION_CASE, editor=replace(JOINED_INTERACTION_CASE.editor, random_seed=1234)),
        replace(JOINED_INTERACTION_CASE, source=replace(JOINED_INTERACTION_CASE.source, assignment_sha256="0" * 64)),
        replace(JOINED_INTERACTION_CASE, assignments=(replace(JOINED_INTERACTION_CASE.assignments[0], reaction_id="R1"),) + JOINED_INTERACTION_CASE.assignments[1:]),
        replace(JOINED_INTERACTION_CASE, calibrations=(replace(JOINED_INTERACTION_CASE.calibrations[0], printer_head_id="wrong-head"),) + JOINED_INTERACTION_CASE.calibrations[1:]),
        replace(JOINED_INTERACTION_CASE, checkpoints=JOINED_INTERACTION_CASE.checkpoints[:5] + (replace(JOINED_INTERACTION_CASE.checkpoints[5], plan_revision=5, progress_reference_revision=5, resume_reference_revision=5),) + JOINED_INTERACTION_CASE.checkpoints[6:]),
        replace(JOINED_INTERACTION_CASE, execution_passes=(JOINED_INTERACTION_CASE.execution_passes[1], JOINED_INTERACTION_CASE.execution_passes[0], JOINED_INTERACTION_CASE.execution_passes[2])),
        replace(JOINED_INTERACTION_CASE, qualification=replace(JOINED_INTERACTION_CASE.qualification, action_cap=95)),
        replace(JOINED_INTERACTION_CASE, terminal=replace(JOINED_INTERACTION_CASE.terminal, expected_droplets=79)),
    ],
)
def test_identity_seed_mapping_revision_head_pass_limit_and_terminal_drift_fail_closed(changed):
    with pytest.raises(JoinedInteractionCaseError):
        validate_joined_interaction_case(changed)


def test_duplicate_stock_well_and_changed_design_b_count_fail_closed():
    case = JOINED_INTERACTION_CASE
    prepared = case.count_oracles[0]
    changed_b = replace(
        prepared,
        rows=tuple(
            replace(row, target_droplets=2)
            if (row.stock_id, row.well_id) == (DESIGN_B_STOCK_ID, "A3")
            else row
            for row in prepared.rows
        ),
    )

    with pytest.raises(JoinedInteractionCaseError, match="unique"):
        replace(prepared, rows=(prepared.rows[0], prepared.rows[0]) + prepared.rows[2:])
    with pytest.raises(JoinedInteractionCaseError, match="Design B"):
        validate_joined_interaction_case(replace(case, count_oracles=(changed_b,) + case.count_oracles[1:]))


def test_fixture_loader_rejects_missing_and_extra_contract_fields(tmp_path):
    payload = JOINED_INTERACTION_CASE.normalized()
    payload["unexpected"] = True
    extra_path = tmp_path / "extra.json"
    extra_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(JoinedInteractionCaseError, match="extra"):
        load_joined_interaction_case(extra_path)

    del payload["unexpected"]
    del payload["source"]["case_sha256"]
    missing_path = tmp_path / "missing.json"
    missing_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(JoinedInteractionCaseError, match="missing"):
        load_joined_interaction_case(missing_path)
