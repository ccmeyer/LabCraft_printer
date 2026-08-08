from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.virtual_workflows.journeys import (
    EXPERIMENT_DESIGN_REJECTED_REQUIRED_ASSERTIONS,
    EXPERIMENT_DESIGN_REJECTED_REQUIRED_UI_ACTIONS,
    EXPERIMENT_DESIGN_REQUIRED_ASSERTIONS,
    EXPERIMENT_DESIGN_REQUIRED_SCREENSHOTS,
    EXPERIMENT_DESIGN_REQUIRED_UI_ACTIONS,
)
from tools.virtual_workflows.matrices import EXPERIMENT_DESIGN_MATRIX_ID
from tools.virtual_workflows.report import validate_report_v1


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "tools" / "run_virtual_workflow.py"


def _run_case(tmp_path: Path, case_id: str) -> dict:
    output_root = tmp_path / case_id
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    process = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--matrix",
            EXPERIMENT_DESIGN_MATRIX_ID,
            "--case",
            case_id,
            "--output-root",
            str(output_root),
            "--seed",
            "1",
            "--speed-multiplier",
            "1000",
            "--timeout-seconds",
            "90",
        ],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )
    assert process.returncode == 0, process.stderr or process.stdout
    reports = tuple(output_root.rglob("report.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    validate_report_v1(report)
    return report


@pytest.mark.sil_lifecycle
@pytest.mark.parametrize(
    ("case_id", "expected_assignments"),
    (
        pytest.param(
            "single_reagent_control",
            {"A1": "R1"},
            id="single_reagent_control",
        ),
        pytest.param(
            "multi_reagent_seed_4321",
            {
                "A1": "R8",
                "A2": "R6",
                "A3": "R3",
                "A4": "R2",
                "A5": "R7",
                "A6": "R4",
                "A7": "R1",
                "A8": "R5",
            },
            id="multi_reagent_seed_4321",
        ),
        pytest.param(
            "one_stock_feasible",
            {"A1": "R1", "A2": "R2"},
            id="one_stock_feasible",
        ),
        pytest.param(
            "two_stock_required",
            {"A1": "R1", "A2": "R2"},
            id="two_stock_required",
        ),
        pytest.param(
            "custom_wells_with_exclusions",
            {"A1": "R1", "A3": "R2", "A4": "R3"},
            id="custom_wells_with_exclusions",
        ),
        pytest.param(
            "multi_reagent_seed_1234",
            {
                "A1": "R2",
                "A2": "R4",
                "A3": "R3",
                "A4": "R5",
                "A5": "R6",
                "A6": "R7",
                "A7": "R1",
                "A8": "R8",
            },
            id="multi_reagent_seed_1234",
        ),
        pytest.param(
            "exact_custom_capacity",
            {"B1": "R1", "B2": "R2", "B3": "R3", "B4": "R4"},
            id="exact_custom_capacity",
        ),
    ),
)
def test_experiment_design_positive_case_is_exact(
    tmp_path,
    case_id,
    expected_assignments,
):
    report = _run_case(tmp_path, case_id)

    assert report["classification"]["status"] == "pass"
    assert report["workload"]["workload_id"] == EXPERIMENT_DESIGN_MATRIX_ID
    assert not any(report["safety"]["hardware_interfaces"].values())
    workflow = report["metrics"]["workflow"]["values"]
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    }
    assert tuple(decisions) == EXPERIMENT_DESIGN_REQUIRED_ASSERTIONS
    assert decisions == {
        assertion_id: "pass"
        for assertion_id in EXPERIMENT_DESIGN_REQUIRED_ASSERTIONS
    }
    ui_actions = {
        row["action_id"]
        for row in workflow["action_results"]
        if row["interaction_surface"] == "ui"
    }
    expected_ui_actions = set(EXPERIMENT_DESIGN_REQUIRED_UI_ACTIONS)
    if case_id == "two_stock_required":
        expected_ui_actions.add("editor.regenerate_prepared_design_via_ui")
    assert ui_actions == expected_ui_actions

    values = report["metrics"]["persistence"]["values"]
    case_evidence = values["matrix_case"]
    assert case_evidence["case"]["case_id"] == case_id
    assert all(case_evidence["outcome"]["oracle_checks"].values())
    assert all(case_evidence["outcome"]["runtime_checks"].values())
    prepared = values["experiment_design_evidence"]["prepared_oracle"]
    reconstructed = values["experiment_design_evidence"]["reload_activation"]
    assert prepared["observed"]["runtime_assignments"] == expected_assignments
    expected_case = case_evidence["case"]["expected"]
    assert prepared["observed_reaction_multiset_sha256"] == (
        expected_case["reaction_multiset_sha256"]
    )
    assert prepared["observed_assignment_sha256"] == (
        expected_case["assignment_sha256"]
    )
    assert reconstructed["reconstructed"]["runtime_assignments"] == (
        expected_assignments
    )
    assert reconstructed["checks"]["runtime_inactive"] is True
    assert reconstructed["changed_paths"] == []
    attempts = prepared["driver"]["optimization_attempts"]
    if case_id == "two_stock_required":
        assert [row["observed_outcome"] for row in attempts] == [
            "rejected",
            "generated",
        ]
        assert attempts[0][
            "authoritative_execution_artifacts_unchanged"
        ] is True
        assert attempts[0]["warning"]["title"] == "Optimization failed"
        assert attempts[0]["dirty_after"] is True
        assert attempts[0]["dialog_open_after"] is True
    else:
        assert [row["observed_outcome"] for row in attempts] == ["generated"]
    expected_screenshots = set(EXPERIMENT_DESIGN_REQUIRED_SCREENSHOTS)
    if case_id == "custom_wells_with_exclusions":
        expected_screenshots.add("well_picker_configured")
        configured = prepared["driver"]["configured"]
        assert configured["declared_well_ids"] == [
            "A1", "A2", "A3", "A4", "A5", "A6"
        ]
        assert configured["selected_well_ids"] == ["A1", "A3", "A4", "A6"]
        assert configured["excluded_well_ids"] == ["A2", "A5"]
        assert configured["well_picker"]["disabled_well_ids"] == ["A2", "A5"]
        assert configured["well_picker"]["rejected_disabled_well_ids"] == [
            "A2", "A5"
        ]
        assert prepared["observed_excluded_well_ids"] == ["A2", "A5"]
    assert set(report["artifacts"]["screenshots"]) == expected_screenshots


@pytest.mark.sil_lifecycle
@pytest.mark.parametrize(
    ("case_id", "terminal", "title", "fragments", "generated"),
    (
        pytest.param(
            "capacity_plus_one_rejected",
            "capacity_rejected",
            "Insufficient Well Capacity",
            ("Required reactions: 5", "Available wells", "4"),
            True,
            id="capacity_plus_one_rejected",
        ),
        pytest.param(
            "fixed_stock_exceeds_max_rejected",
            "formulation_rejected",
            "Optimization failed",
            ("exceeds max stock",),
            False,
            id="fixed_stock_exceeds_max_rejected",
        ),
    ),
)
def test_experiment_design_rejected_case_has_exact_no_mutation_evidence(
    tmp_path,
    case_id,
    terminal,
    title,
    fragments,
    generated,
):
    report = _run_case(tmp_path, case_id)

    assert report["classification"]["status"] == "pass"
    assert not any(report["safety"]["hardware_interfaces"].values())
    workflow = report["metrics"]["workflow"]["values"]
    decisions = {
        row["assertion_id"]: row["decision"]
        for row in workflow["assertion_results"]
    }
    assert tuple(decisions) == EXPERIMENT_DESIGN_REJECTED_REQUIRED_ASSERTIONS
    assert set(decisions.values()) == {"pass"}
    ui_actions = {
        row["action_id"]
        for row in workflow["action_results"]
        if row["interaction_surface"] == "ui"
    }
    expected_ui_actions = set(EXPERIMENT_DESIGN_REJECTED_REQUIRED_UI_ACTIONS)
    if generated:
        expected_ui_actions.add("editor.optimize_generate_via_ui")
    assert ui_actions == expected_ui_actions

    values = report["metrics"]["persistence"]["values"]
    matrix_case = values["matrix_case"]
    assert matrix_case["case"]["case_id"] == case_id
    assert matrix_case["outcome"]["terminal"] == terminal
    assert all(matrix_case["outcome"]["oracle_checks"].values())
    assert matrix_case["outcome"]["runtime_checks"] == {}
    rejection = values["experiment_design_evidence"][
        "finalization_rejection"
    ]
    assert rejection["terminal"] == terminal
    assert all(rejection["checks"].values())
    boundary = rejection["rejection"]
    assert boundary["warning"]["title"] == title
    combined = " ".join(
        (boundary["warning"]["text"], boundary["status"])
    ).casefold()
    assert all(fragment.casefold() in combined for fragment in fragments)
    assert boundary["before"]["directory_inventory"] == (
        boundary["after"]["directory_inventory"]
    )
    assert boundary["required_execution_artifacts_absent"] is True
    assert boundary["draft_progress_unchanged"] is True
    assert boundary["authoritative_execution_artifacts_unchanged"] is True
    before_artifacts = boundary["before"]["execution_artifacts"]
    after_artifacts = boundary["after"]["execution_artifacts"]
    assert before_artifacts["progress.json"]["exists"] is True
    assert before_artifacts["progress.json"] == after_artifacts["progress.json"]
    assert all(
        before_artifacts[name]["exists"] is False
        and after_artifacts[name]["exists"] is False
        for name in before_artifacts
        if name != "progress.json"
    )
    assert boundary["before"]["runtime_assignments"] == {}
    assert boundary["after"]["runtime_assignments"] == {}
    assert boundary["before"]["array_state"] == "idle"
    assert boundary["after"]["array_state"] == "idle"
    assert set(report["artifacts"]["screenshots"]) == (
        {"editor_opened", "finalization_rejected", "validated"}
        | ({"generated"} if generated else set())
    )


@pytest.mark.sil_lifecycle
def test_randomized_design_cases_have_same_multiset_and_distinct_assignments(
    tmp_path,
):
    seed_4321 = _run_case(tmp_path, "multi_reagent_seed_4321")
    seed_1234 = _run_case(tmp_path, "multi_reagent_seed_1234")

    prepared_4321 = seed_4321["metrics"]["persistence"]["values"][
        "experiment_design_evidence"
    ]["prepared_oracle"]
    prepared_1234 = seed_1234["metrics"]["persistence"]["values"][
        "experiment_design_evidence"
    ]["prepared_oracle"]
    assert prepared_4321["observed_reaction_multiset_sha256"] == (
        prepared_1234["observed_reaction_multiset_sha256"]
    ) == "b189fe1ed4b975953600c7d299fd320be366eda827ceb39f28cf3a3bbc22b696"
    assert prepared_4321["observed_assignment_sha256"] == (
        "e264b345bddb83c2aeb12bf6421d83a81d21c8b9f31ff6698780164a1bee82ef"
    )
    assert prepared_1234["observed_assignment_sha256"] == (
        "1ecbf5c4967d71a45fe33b6ac8cb858e3334b02bb1933f37ebbeddeae36450e9"
    )
