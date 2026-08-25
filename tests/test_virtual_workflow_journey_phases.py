from __future__ import annotations

import ast
from collections import Counter
import inspect

import pytest

from tools.virtual_workflows.composition import normalized_steps
from tools.virtual_workflows.journey_phases import (
    CalibrationOnlySpec,
    PrecalibratedStockPassSpec,
    PostStartLockCopySpec,
    PreparedEditorRevisionSpec,
    SoftStopResumeSpec,
    DisconnectFailClosedSpec,
    StockPassSpec,
    ManualRefuelCheckSpec,
    _expected_completed_array_control_text,
    _run_stock_pass,
    capture_completion_midpoint,
    machine_startup_steps,
    normalized_prepared_revision_steps,
    normalized_stock_pass_steps,
    normalized_soft_stop_resume_steps,
    normalized_disconnect_fail_closed_steps,
    normalized_calibration_only_steps,
    normalized_precalibrated_stock_pass_steps,
)


@pytest.mark.parametrize(
    ("expected_plan_state", "head_returned", "expected_text"),
    (
        ("completed", False, "Array Complete"),
        ("completed", True, "Experiment Complete"),
        ("active", False, "Array Complete"),
        ("active", True, "Start Array"),
    ),
)
def test_completed_array_control_text_follows_terminal_state_before_head_state(
    expected_plan_state,
    head_returned,
    expected_text,
):
    assert _expected_completed_array_control_text(
        expected_plan_state=expected_plan_state,
        head_returned=head_returned,
    ) == expected_text


def test_final_stock_pass_wait_uses_the_outer_scenario_deadline():
    tree = ast.parse(inspect.getsource(_run_stock_pass))
    waits = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "wait_for_completions"
    ]

    assert len(waits) == 1
    timeout = next(
        keyword.value
        for keyword in waits[0].keywords
        if keyword.arg == "timeout_seconds"
    )
    assert ast.unparse(timeout) == "context.deadline.remaining_seconds()"


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


def test_calibration_only_phase_has_exact_actions_and_no_execution_control():
    spec = CalibrationOnlySpec(
        stock_id="Design A_10.00_x",
        printer_head_id="virtual-head-m11-design-a-v1",
        pulse_width_us=1800,
        pressure_psi=2.0,
        frequency_hz=100,
        initial_volume_uL=100.0,
        expected_volume_nL=18.0,
    )

    assert normalized_calibration_only_steps(spec) == [
        {"action_id": "head.bind_identity", "interaction_surface": "model"},
        {"action_id": "machine.configure_print_settings_via_ui", "interaction_surface": "ui"},
        {"action_id": "head.set_volume_via_ui", "interaction_surface": "ui"},
        {"action_id": "head.stage_via_ui", "interaction_surface": "ui"},
        {"action_id": "pressure.enable_regulation_via_ui", "interaction_surface": "ui"},
        {"action_id": "calibration.open_via_ui", "interaction_surface": "ui"},
        {"action_id": "calibration.generate_via_ui", "interaction_surface": "ui"},
        {"action_id": "calibration.select_via_ui", "interaction_surface": "ui"},
        {"action_id": "calibration.apply_via_ui", "interaction_surface": "ui"},
    ]
    assert all(
        not row["action_id"].startswith(("array.", "manual_refuel."))
        for row in normalized_calibration_only_steps(spec)
    )


def test_calibration_only_phase_optionally_returns_the_exact_head():
    spec = CalibrationOnlySpec(
        stock_id="Water_1.00_--",
        printer_head_id="virtual-head-m11-water-v1",
        pulse_width_us=1300,
        pressure_psi=2.0,
        frequency_hz=100,
        initial_volume_uL=100.0,
        expected_volume_nL=9.0,
        return_head=True,
    )

    action_ids = [
        row["action_id"] for row in normalized_calibration_only_steps(spec)
    ]
    assert action_ids[-1] == "head.return_via_ui"
    assert action_ids.count("head.return_via_ui") == 1
    assert "array.start_via_ui" not in action_ids


def test_precalibrated_stock_passes_have_no_calibration_or_refill_actions():
    specs = tuple(
        PrecalibratedStockPassSpec(
            stock_id=f"stock-{index}",
            printer_head_id=f"head-{index}",
            pulse_width_us=1300 + index * 100,
            pressure_psi=2.0,
            frequency_hz=100,
            initial_volume_uL=100.0,
            expected_volume_nL=9.0 + index,
            expected_completion_count=8 * (index + 1),
            expected_plan_state="completed" if index == 2 else "active",
            completed_milestone=f"pass-{index + 1}",
            start_dialog_titles=(
                ("Start Print Array", "Evaporation Plate Dock Check")
                if index == 0
                else ("Start Print Array",)
            ),
            bind_identity=index == 0,
        )
        for index in range(3)
    )

    plan = normalized_precalibrated_stock_pass_steps(specs)
    action_ids = [row["action_id"] for row in plan]
    assert action_ids.count("head.bind_identity") == 1
    for action_id in (
        "machine.configure_print_settings_via_ui",
        "head.set_volume_via_ui",
        "head.stage_via_ui",
        "array.start_via_ui",
        "array.wait_for_completions",
        "validation.stock_pass_boundary",
        "artifact.capture_milestone",
        "head.return_via_ui",
    ):
        assert action_ids.count(action_id) == 3
    assert not any(
        action_id.startswith(("calibration.", "manual_refuel."))
        for action_id in action_ids
    )
    assert [
        row["stock_id"] for row in plan if row["action_id"] == "head.stage_via_ui"
    ] == ["stock-0", "stock-1", "stock-2"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("stock_id", "", "stock and head"),
        ("expected_completion_count", 0, "volume/count"),
        ("expected_plan_state", "paused", "plan state"),
        ("completed_milestone", "", "milestone"),
    ),
)
def test_precalibrated_stock_pass_rejects_ambiguous_boundaries(
    field, value, message
):
    values = {
        "stock_id": "stock-a",
        "printer_head_id": "head-a",
        "pulse_width_us": 1300,
        "pressure_psi": 2.0,
        "frequency_hz": 100,
        "initial_volume_uL": 100.0,
        "expected_volume_nL": 9.0,
        "expected_completion_count": 8,
        "expected_plan_state": "active",
        "completed_milestone": "stock-a-complete",
    }
    values[field] = value
    with pytest.raises(ValueError, match=message):
        PrecalibratedStockPassSpec(**values)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("stock_id", "", "stock and head"),
        ("pulse_width_us", 0, "pulse and frequency"),
        ("expected_volume_nL", 0, "expected volume"),
        ("calibration_mode", "unsupported", "mode"),
        ("refuel_pulse_width_us", 6000, "does not support refuel"),
    ),
)
def test_calibration_only_spec_rejects_scope_and_identity_drift(field, value, message):
    values = {
        "stock_id": "stock-a",
        "printer_head_id": "head-a",
        "pulse_width_us": 1800,
        "pressure_psi": 2.0,
        "frequency_hz": 100,
        "initial_volume_uL": 100.0,
        "expected_volume_nL": 18.0,
    }
    values[field] = value
    with pytest.raises(ValueError, match=message):
        CalibrationOnlySpec(**values)


def test_completion_midpoint_rejects_an_unbounded_target():
    with pytest.raises(ValueError, match="midpoint"):
        capture_completion_midpoint(object(), 0)


def test_interrupted_stock_pass_skips_only_terminal_actions():
    spec = StockPassSpec(
        stock_id="stock-a", printer_head_id="head-a", pulse_width_us=1300,
        pressure_psi=1.2, frequency_hz=20, initial_volume_uL=1000.0,
        expected_volume_nL=10.0, expected_completion_count=24,
        expected_plan_state="active", ready_milestone="ready",
        printing_milestone="printing", completed_milestone=None,
        staging_slot=0, enable_pressure_regulation=True,
        await_terminal_boundary=False,
    )
    action_ids = [row["action_id"] for row in normalized_stock_pass_steps((spec,))]
    assert "array.start_via_ui" in action_ids
    assert "array.wait_for_completions" not in action_ids
    assert "head.return_via_ui" not in action_ids
    assert action_ids.count("artifact.capture_milestone") == 2


def test_disconnect_phase_is_short_typed_composition():
    spec = DisconnectFailClosedSpec(6, 2, 250)
    assert normalized_disconnect_fail_closed_steps(spec) == [
        {"action_id": "machine.disconnect_via_ui", "interaction_surface": "ui", "disconnect_after_completion_count": 6},
        {"action_id": "artifact.capture_milestone", "interaction_surface": "harness", "disconnect_after_completion_count": 6},
        {"action_id": "array.observe_disconnected_quiescence", "interaction_surface": "harness", "disconnect_after_completion_count": 6},
        {"action_id": "artifact.capture_milestone", "interaction_surface": "harness", "disconnect_after_completion_count": 6},
    ]


def test_interrupted_stock_pass_rejects_terminal_policy_mix():
    with pytest.raises(ValueError, match="interrupted stock passes"):
        StockPassSpec(
            stock_id="stock-a", printer_head_id="head-a", pulse_width_us=1300,
            pressure_psi=1.2, frequency_hz=20, initial_volume_uL=1000.0,
            expected_volume_nL=10.0, expected_completion_count=24,
            expected_plan_state="active", ready_milestone=None,
            printing_milestone=None, completed_milestone="invalid",
            await_terminal_boundary=False,
        )


def test_manual_refuel_cancelled_pass_stops_at_the_ui_start_guard():
    spec = StockPassSpec(
        stock_id="stream-stock",
        printer_head_id="stream-head",
        pulse_width_us=2500,
        pressure_psi=1.2,
        frequency_hz=20,
        initial_volume_uL=1000.0,
        expected_volume_nL=60.0,
        expected_completion_count=1,
        expected_plan_state="active",
        ready_milestone="ready",
        printing_milestone=None,
        completed_milestone=None,
        calibration_mode="stream",
        refuel_pulse_width_us=6000,
        refuel_pressure_psi=0.4,
        manual_refuel_check=ManualRefuelCheckSpec(
            trial_count=2,
            trial_droplet_count=5,
            outcome="unclear",
            operator_judgment="unclear",
        ),
        expected_start_outcome="manual_refuel_cancelled",
        return_head=True,
    )

    action_ids = [
        row["action_id"] for row in normalized_stock_pass_steps((spec,))
    ]
    assert action_ids.count("manual_refuel.complete_check_via_ui") == 1
    assert action_ids.count("array.start_via_ui") == 1
    assert "array.wait_for_completions" not in action_ids
    assert "validation.stock_pass_boundary" not in action_ids
    assert action_ids[-1] == "head.return_via_ui"


def test_manual_refuel_cancelled_requires_a_nonpassing_stream_check():
    values = dict(
        stock_id="stock-a",
        printer_head_id="head-a",
        pulse_width_us=1300,
        pressure_psi=1.2,
        frequency_hz=20,
        initial_volume_uL=1000.0,
        expected_volume_nL=9.0,
        expected_completion_count=1,
        expected_plan_state="active",
        ready_milestone=None,
        printing_milestone=None,
        completed_milestone=None,
        expected_start_outcome="manual_refuel_cancelled",
    )
    with pytest.raises(ValueError, match="non-passed stream check"):
        StockPassSpec(**values)

    values.update(
        calibration_mode="stream",
        refuel_pulse_width_us=6000,
        refuel_pressure_psi=0.4,
        manual_refuel_check=ManualRefuelCheckSpec(
            trial_count=2,
            trial_droplet_count=5,
            outcome="passed",
            operator_judgment="stable",
        ),
    )
    with pytest.raises(ValueError, match="non-passed stream check"):
        StockPassSpec(**values)


def test_calibration_rejection_has_no_array_start_or_terminal_actions():
    spec = StockPassSpec(
        stock_id="stock-a",
        printer_head_id="head-a",
        pulse_width_us=1300,
        pressure_psi=1.2,
        frequency_hz=20,
        initial_volume_uL=1000.0,
        expected_volume_nL=9.0,
        expected_completion_count=24,
        expected_plan_state="active",
        ready_milestone=None,
        printing_milestone=None,
        completed_milestone=None,
        expected_start_outcome="calibration_apply_rejected",
        rejected_calibration_mode="stream",
        rejected_calibration_pulse_width_us=2500,
        rejected_calibration_profile_id="droplet_to_stream",
        rejected_calibration_title="Apply failed",
        rejected_calibration_message_fragment="missing fill",
        return_head=True,
    )

    action_ids = [
        row["action_id"] for row in normalized_stock_pass_steps((spec,))
    ]
    assert action_ids.count("calibration.generate_via_ui") == 2
    assert action_ids.count("calibration.apply_via_ui") == 2
    assert "array.start_via_ui" not in action_ids
    assert "array.wait_for_completions" not in action_ids
    assert "validation.stock_pass_boundary" not in action_ids
    assert action_ids[-1] == "head.return_via_ui"


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


def test_stream_pass_inserts_one_ui_manual_refuel_gate_before_start():
    stream = StockPassSpec(
        stock_id="stream-stock",
        printer_head_id="stream-head",
        pulse_width_us=2500,
        pressure_psi=1.2,
        frequency_hz=20,
        initial_volume_uL=1000.0,
        expected_volume_nL=60.0,
        expected_completion_count=24,
        expected_plan_state="completed",
        ready_milestone="stream-ready",
        printing_milestone="stream-printing",
        completed_milestone="completed",
        calibration_mode="stream",
        refuel_pulse_width_us=6000,
        refuel_pressure_psi=0.4,
        manual_refuel_check=ManualRefuelCheckSpec(),
    )

    plan = normalized_stock_pass_steps((stream,))
    action_ids = [row["action_id"] for row in plan]
    manual_index = action_ids.index("manual_refuel.complete_check_via_ui")

    assert action_ids.index("calibration.apply_via_ui") < manual_index
    assert manual_index < action_ids.index("array.start_via_ui")
    assert plan[manual_index]["interaction_surface"] == "ui"


def test_manual_refuel_contract_is_stream_only_and_requires_refuel_settings():
    values = dict(
        stock_id="stock",
        printer_head_id="head",
        pulse_width_us=2500,
        pressure_psi=1.2,
        frequency_hz=20,
        initial_volume_uL=1000.0,
        expected_volume_nL=60.0,
        expected_completion_count=24,
        expected_plan_state="completed",
        ready_milestone=None,
        printing_milestone=None,
        completed_milestone=None,
        manual_refuel_check=ManualRefuelCheckSpec(),
    )
    with pytest.raises(ValueError, match="stream mode"):
        StockPassSpec(**values)
    with pytest.raises(ValueError, match="both refuel settings"):
        StockPassSpec(**values, calibration_mode="stream")


def test_ten_stock_compact_plan_retains_only_six_named_milestones():
    specs = tuple(
        StockPassSpec(
            stock_id=f"stock-{index}", printer_head_id=f"head-{index}",
            pulse_width_us=1300 + index * 10, pressure_psi=1.2,
            frequency_hz=20, initial_volume_uL=1000.0,
            expected_volume_nL=9.0, expected_completion_count=384 * (index + 1),
            expected_plan_state="completed" if index == 9 else "active",
            ready_milestone="ready" if index == 0 else None,
            printing_milestone="printing" if index == 0 else None,
            completed_milestone=("mid_array" if index == 4 else "completed" if index == 9 else None),
            staging_slot=0, bind_identity=True, enable_pressure_regulation=index == 0,
            validate_pass_boundary=True, return_head=True,
        )
        for index in range(10)
    )
    plan = normalized_stock_pass_steps(specs)
    action_ids = [row["action_id"] for row in plan]

    assert action_ids.count("machine.configure_print_settings_via_ui") == 10
    assert action_ids.count("array.start_via_ui") == 10
    assert action_ids.count("validation.stock_pass_boundary") == 10
    assert action_ids.count("artifact.capture_milestone") == 4


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
