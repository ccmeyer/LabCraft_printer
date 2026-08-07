from __future__ import annotations

from collections import Counter

import pytest

from tools.virtual_workflows.composition import normalized_steps
from tools.virtual_workflows.journey_phases import (
    PostStartLockCopySpec,
    PreparedEditorRevisionSpec,
    SoftStopResumeSpec,
    StockPassSpec,
    capture_completion_midpoint,
    machine_startup_steps,
    normalized_prepared_revision_steps,
    normalized_stock_pass_steps,
    normalized_soft_stop_resume_steps,
)


def _stock(
    stock_id: str,
    head_id: str,
    *,
    completion_count: int,
    plan_state: str,
    first: bool,
) -> StockPassSpec:
    return StockPassSpec(
        stock_id=stock_id,
        printer_head_id=head_id,
        pulse_width_us=1300 if first else 1800,
        pressure_psi=1.2 if first else 1.5,
        frequency_hz=20,
        initial_volume_uL=1000.0,
        expected_volume_nL=9.0 if first else 18.0,
        expected_completion_count=completion_count,
        expected_plan_state=plan_state,
        ready_milestone="stock_1_ready" if first else "stock_2_staged",
        printing_milestone="stock_1_printing" if first else "stock_2_printing",
        completed_milestone="stock_1_completed" if first else "completed",
        start_dialog_titles=(
            ("Start Print Array", "Evaporation Plate Dock Check")
            if first
            else ("Start Print Array",)
        ),
        bind_identity=True,
        enable_pressure_regulation=first,
        validate_pass_boundary=True,
        return_head=True,
        detailed_evidence=True,
        include_frequency_evidence=False,
    )


def test_machine_startup_is_one_normalized_reusable_ui_phase():
    assert normalized_steps(machine_startup_steps()) == [
        {"action_id": "machine.connect_via_ui", "interaction_surface": "ui"},
        {
            "action_id": "machine.enable_motors_via_ui",
            "interaction_surface": "ui",
        },
        {"action_id": "machine.home_via_ui", "interaction_surface": "ui"},
    ]


def test_completion_midpoint_rejects_an_unbounded_target():
    with pytest.raises(ValueError, match="midpoint"):
        capture_completion_midpoint(object(), 0)


def test_two_stock_plan_has_exact_repeated_groups_and_truthful_surfaces():
    specs = (
        _stock("stock-a", "head-a", completion_count=24, plan_state="active", first=True),
        _stock("stock-b", "head-b", completion_count=48, plan_state="completed", first=False),
    )

    plan = normalized_stock_pass_steps(specs)
    action_ids = [row["action_id"] for row in plan]

    assert action_ids.count("head.bind_identity") == 1
    for action_id in (
        "machine.configure_print_settings_via_ui",
        "head.set_volume_via_ui",
        "head.stage_via_ui",
        "calibration.open_via_ui",
        "calibration.generate_via_ui",
        "calibration.select_via_ui",
        "calibration.apply_via_ui",
        "array.start_via_ui",
        "array.wait_for_completions",
        "validation.stock_pass_boundary",
        "head.return_via_ui",
    ):
        assert action_ids.count(action_id) == 2
    assert action_ids.count("pressure.enable_regulation_via_ui") == 1
    assert next(row for row in plan if row["action_id"] == "head.bind_identity")[
        "interaction_surface"
    ] == "model"
    assert {
        row["interaction_surface"]
        for row in plan
        if row["action_id"] == "array.wait_for_completions"
    } == {"harness"}


def test_stock_values_and_order_vary_without_new_runner_code():
    first = _stock("stock-a", "head-a", completion_count=24, plan_state="active", first=True)
    second = _stock("stock-b", "head-b", completion_count=48, plan_state="completed", first=False)

    forward = normalized_stock_pass_steps((first, second))
    reverse = normalized_stock_pass_steps((second, first))

    assert [row["stock_id"] for row in forward if row["action_id"] == "head.stage_via_ui"] == [
        "stock-a",
        "stock-b",
    ]
    assert [row["stock_id"] for row in reverse if row["action_id"] == "head.stage_via_ui"] == [
        "stock-b",
        "stock-a",
    ]
    assert Counter(row["action_id"] for row in forward) == Counter(
        row["action_id"] for row in reverse
    )


def test_stock_pass_contract_rejects_invalid_boundary_values():
    with pytest.raises(ValueError, match="completion count"):
        StockPassSpec(
            stock_id="stock",
            printer_head_id="head",
            pulse_width_us=1300,
            pressure_psi=1.2,
            frequency_hz=20,
            initial_volume_uL=1000.0,
            expected_volume_nL=9.0,
            expected_completion_count=0,
            expected_plan_state="completed",
            ready_milestone="ready",
            printing_milestone="printing",
            completed_milestone="completed",
        )


def test_soft_stop_resume_plan_is_short_typed_and_parameterized():
    first = normalized_soft_stop_resume_steps(SoftStopResumeSpec(6, 2, 250))
    second = normalized_soft_stop_resume_steps(SoftStopResumeSpec(12, 3, 500))

    expected = [
        "array.request_soft_stop_via_ui",
        "artifact.capture_milestone",
        "array.wait_for_state",
        "artifact.capture_milestone",
        "array.observe_stopped_quiescence",
        "array.resume_via_ui",
        "artifact.capture_milestone",
    ]
    assert [row["action_id"] for row in first] == expected
    assert [row["action_id"] for row in second] == expected
    assert {row["request_after_completion_count"] for row in first} == {6}
    assert {row["request_after_completion_count"] for row in second} == {12}
    assert next(row for row in first if row["action_id"] == "array.resume_via_ui")[
        "interaction_surface"
    ] == "ui"


def test_soft_stop_resume_spec_rejects_unbounded_values():
    with pytest.raises(ValueError, match="trigger count"):
        SoftStopResumeSpec(0, 2, 250)
    with pytest.raises(ValueError, match="quiescence"):
        SoftStopResumeSpec(6, 2, 0)


def _prepared_revision(**values) -> PreparedEditorRevisionSpec:
    defaults = {
        "initial_name": "initial",
        "renamed_name": "renamed",
        "replicates": 3,
        "well_ids": ("A1", "A2", "A3"),
        "printed_volume_nL": 120.0,
        "final_volume_nL": 120.0,
        "fill_printing_mode": "stream",
        "fill_droplet_volume_nL": 60.0,
        "reagent_printing_mode": "stream",
        "reagent_targets": (0.5, 1.0),
        "reagent_droplet_volume_nL": 60.0,
    }
    defaults.update(values)
    return PreparedEditorRevisionSpec(**defaults)


def test_prepared_revision_plan_is_short_typed_and_ui_only():
    plan = normalized_prepared_revision_steps(_prepared_revision())

    assert [row["action_id"] for row in plan] == [
        "editor.open_via_ui",
        "editor.rename_prepared_via_ui",
        "editor.edit_prepared_design_via_ui",
        "editor.regenerate_prepared_design_via_ui",
        "editor.refinalize_prepared_via_ui",
    ]
    assert {row["interaction_surface"] for row in plan} == {"ui"}
    assert {tuple(row["well_ids"]) for row in plan} == {("A1", "A2", "A3")}


def test_prepared_revision_values_vary_without_a_new_runner():
    first = normalized_prepared_revision_steps(_prepared_revision())
    second = normalized_prepared_revision_steps(
        _prepared_revision(
            renamed_name="second",
            replicates=2,
            well_ids=("B1", "B2"),
            printed_volume_nL=90.0,
        )
    )

    assert [row["action_id"] for row in first] == [
        row["action_id"] for row in second
    ]
    assert {row["renamed_name"] for row in second} == {"second"}
    assert {tuple(row["well_ids"]) for row in second} == {("B1", "B2")}


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"renamed_name": "initial"}, "change the experiment name"),
        ({"replicates": 0}, "replicates"),
        ({"well_ids": ("A1", "A1")}, "unique"),
        ({"fill_printing_mode": "invalid"}, "fill mode"),
        ({"reagent_targets": ()}, "targets"),
        ({"reagent_targets": (float("nan"),)}, "targets"),
        ({"reagent_droplet_volume_nL": 0}, "droplet volume"),
    ],
)
def test_prepared_revision_rejects_invalid_values(values, message):
    with pytest.raises(ValueError, match=message):
        _prepared_revision(**values)


def test_post_start_lock_copy_spec_is_typed_and_bounded(tmp_path):
    spec = PostStartLockCopySpec(
        source_dir=tmp_path / "source",
        source_name="source",
        copy_name="copy",
        copy_tolerance_nl=1.0,
    )

    assert spec.source_dir == (tmp_path / "source").resolve()
    assert spec.copy_tolerance_nl == 1.0
    with pytest.raises(ValueError, match="distinct"):
        PostStartLockCopySpec(tmp_path, "same", "same", 1.0)
    with pytest.raises(ValueError, match="non-negative"):
        PostStartLockCopySpec(tmp_path, "source", "copy", -1.0)
