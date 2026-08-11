from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.virtual_workflows.actions import (
    ACTION_INTERACTION_SURFACES,
    ACTION_IDS,
    COMPOSED_SMOKE_ACTION_IDS,
    COMPOSED_MULTI_STOCK_ACTION_IDS,
    COMPOSED_SOFT_STOP_ACTION_IDS,
    COMPOSED_DISCONNECT_ACTION_IDS,
    InteractionSurface,
    ScenarioActionError,
    ScenarioContext,
    capture_milestone,
    close_simulated_session,
    drive_editor_create_finalize,
    drive_editor_post_start_lock_and_copy,
    drive_editor_prestart_rename_refinalize,
    execute_action,
    install_dialog_handler,
    observe_stopped_quiescence,
    request_soft_stop_via_ui,
    stage_virtual_head,
    teardown_scenario,
    validate_stock_pass_boundary,
    wait_for_completions,
    wait_until,
)
from tools.virtual_workflows.page_drivers import inspect_editor_lock_controls
from tools.virtual_workflows.registry import load_capability_manifest


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_composed_multi_stock_actions_report_truthful_surfaces():
    assert COMPOSED_SMOKE_ACTION_IDS < COMPOSED_MULTI_STOCK_ACTION_IDS
    assert ACTION_INTERACTION_SURFACES["head.bind_identity"] is (
        InteractionSurface.MODEL
    )


def test_composed_soft_stop_actions_add_one_truthful_resume_contract():
    assert COMPOSED_SMOKE_ACTION_IDS < COMPOSED_SOFT_STOP_ACTION_IDS
    assert ACTION_INTERACTION_SURFACES["array.resume_via_ui"] is (
        InteractionSurface.UI
    )
    assert ACTION_INTERACTION_SURFACES["array.observe_stopped_quiescence"] is (
        InteractionSurface.HARNESS
    )
    assert ACTION_INTERACTION_SURFACES["head.return_via_ui"] is (
        InteractionSurface.UI
    )


def test_composed_disconnect_actions_replace_terminal_wait_truthfully():
    assert "array.wait_for_completions" not in COMPOSED_DISCONNECT_ACTION_IDS
    assert "machine.disconnect_via_ui" in COMPOSED_DISCONNECT_ACTION_IDS
    assert "array.observe_disconnected_quiescence" in COMPOSED_DISCONNECT_ACTION_IDS
    assert ACTION_INTERACTION_SURFACES["machine.disconnect_via_ui"] is (
        InteractionSurface.UI
    )
    assert ACTION_INTERACTION_SURFACES[
        "array.observe_disconnected_quiescence"
    ] is InteractionSurface.HARNESS


def test_post_start_synthetic_setup_actions_report_model_surfaces():
    assert ACTION_INTERACTION_SURFACES["experiment.activate_authoritative"] is (
        InteractionSurface.MODEL
    )
    assert ACTION_INTERACTION_SURFACES["execution.lock_for_printing"] is (
        InteractionSurface.MODEL
    )


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += float(seconds)


def _context(tmp_path, *, timeout_seconds=5.0, clock=None):
    fake_clock = clock or FakeClock()
    events = []
    report_dir = tmp_path / "report"
    return (
        ScenarioContext(
            scenario_id="scenario",
            workload_id="workload",
            report_dir=report_dir,
            scenario_root=report_dir / "scenario-root",
            screenshots_dir=report_dir / "screenshots",
            timeout_seconds=timeout_seconds,
            record_event=lambda kind, **values: events.append(
                {"kind": kind, **values}
            ),
            clock=fake_clock,
            sleep=fake_clock.sleep,
        ),
        fake_clock,
        events,
    )


def test_action_catalog_matches_the_tracked_manifest(tmp_path):
    del tmp_path
    manifest = load_capability_manifest()
    catalog = manifest["policy"]["action_catalog"]

    assert {item["id"] for item in catalog} == ACTION_IDS
    assert {item["implementation_status"] for item in catalog} == {"reusable"}
    assert {item["source_path"] for item in catalog} == {
        "tools/virtual_workflows/actions.py",
        "tools/virtual_workflows/page_drivers.py",
    }
    assert next(
        item for item in catalog
        if item["id"] == "manual_refuel.complete_check_via_ui"
    )["interaction_surface"] == "ui"
    declared = {
        item["id"]: item["interaction_surface"]
        for item in catalog
        if "interaction_surface" in item
    }
    assert declared
    assert all(
        ACTION_INTERACTION_SURFACES[action_id].value == surface
        for action_id, surface in declared.items()
    )


def test_composed_smoke_actions_have_explicit_truthful_surfaces():
    assert COMPOSED_SMOKE_ACTION_IDS <= ACTION_IDS
    assert {
        ACTION_INTERACTION_SURFACES[action_id]
        for action_id in COMPOSED_SMOKE_ACTION_IDS
        if action_id.endswith("_via_ui")
    } == {InteractionSurface.UI}


def test_action_precondition_blocks_operation_and_records_one_failure(tmp_path):
    context, _, events = _context(tmp_path)
    called = False

    def operation():
        nonlocal called
        called = True
        return {}

    with pytest.raises(ScenarioActionError, match="not ready") as caught:
        execute_action(
            context,
            "app.launch_simulated",
            operation,
            precondition=lambda: (False, "not ready", {"state": "draft"}),
        )

    assert called is False
    assert caught.value.stage == "precondition"
    assert len(context.action_results) == 1
    result = context.action_results[0]
    assert result["action_id"] == "app.launch_simulated"
    assert result["status"] == "fail"
    assert result["evidence"] == {"state": "draft"}
    assert result["failure_stage"] == "precondition"
    assert result["failure_type"] == "ScenarioActionError"
    assert [event["kind"] for event in events] == [
        "action_started",
        "action_completed",
    ]


def test_action_results_bound_and_serialize_evidence(tmp_path):
    context, _, _ = _context(tmp_path)
    result = execute_action(
        context,
        "fixture.prepare_authoritative",
        lambda: {
            "path": tmp_path / "fixture",
            "values": set(range(3)),
            "long": "x" * 3000,
        },
    )

    assert result["status"] == "pass"
    assert result["evidence"]["path"] == str(tmp_path / "fixture")
    assert sorted(result["evidence"]["values"]) == [0, 1, 2]
    assert len(result["evidence"]["long"]) == 2000
    json.dumps(context.action_results, allow_nan=False)


def test_operation_failure_is_explicit_and_records_one_result(tmp_path):
    context, _, _ = _context(tmp_path)

    with pytest.raises(ScenarioActionError, match="broken") as caught:
        execute_action(
            context,
            "fixture.prepare_authoritative",
            lambda: (_ for _ in ()).throw(ValueError("broken")),
        )

    assert caught.value.stage == "operation"
    assert len(context.action_results) == 1
    assert context.action_results[0]["failure_stage"] == "operation"
    assert context.action_results[0]["evidence"] == {
        "exception_type": "ValueError"
    }


def test_wait_caps_local_timeout_and_checks_the_final_boundary(tmp_path):
    context, clock, _ = _context(tmp_path, timeout_seconds=0.003)

    wait_until(
        context,
        lambda: clock.value >= context.deadline.expires_monotonic,
        10.0,
        "deadline transition",
        action_id="array.wait_for_state",
    )

    assert clock.value - context.deadline.started_monotonic < 0.01


def test_wait_action_uses_one_global_deadline_and_records_timeout(tmp_path):
    context, clock, _ = _context(tmp_path, timeout_seconds=0.01)
    clock.value += 0.02

    with pytest.raises(ScenarioActionError, match="deadline is exhausted") as caught:
        wait_for_completions(
            context,
            completed_count=lambda: 0,
            target_count=1,
            timeout_seconds=10.0,
            label="one completion",
        )

    assert caught.value.stage == "timeout"
    assert len(context.action_results) == 1
    assert context.action_results[0]["action_id"] == "array.wait_for_completions"
    assert context.action_results[0]["failure_stage"] == "timeout"


def test_completion_wait_resets_rolling_no_progress_deadline(tmp_path):
    context, clock, _ = _context(tmp_path, timeout_seconds=1.0)
    completed = {"value": 0}

    def advancing_sleep(seconds):
        clock.sleep(seconds)
        if clock.value >= 100.004:
            completed["value"] = 1
        if clock.value >= 100.008:
            completed["value"] = 2

    context.sleep = advancing_sleep
    result = wait_for_completions(
        context,
        completed_count=lambda: completed["value"],
        target_count=2,
        timeout_seconds=1.0,
        label="rolling progress",
        no_progress_timeout_seconds=0.005,
    )

    assert result["status"] == "pass"
    assert result["evidence"]["observed_count"] == 2


def test_completion_wait_fails_closed_with_no_progress_evidence(tmp_path):
    context, _, _ = _context(tmp_path, timeout_seconds=1.0)

    with pytest.raises(ScenarioActionError, match="no progress") as caught:
        wait_for_completions(
            context,
            completed_count=lambda: 7,
            target_count=8,
            timeout_seconds=1.0,
            label="stalled completion",
            no_progress_timeout_seconds=0.005,
            no_progress_evidence=lambda observed, stalled: {
                "observed": observed,
                "stalled": stalled,
            },
        )

    assert caught.value.stage == "no_progress"
    assert caught.value.evidence["last_progress_count"] == 7
    assert caught.value.evidence["stalled_seconds"] >= 0.005
    assert caught.value.evidence["liveness"]["observed"] == 7
    assert context.action_results[-1]["failure_stage"] == "no_progress"


def test_completion_wait_preserves_stall_when_evidence_capture_fails(tmp_path):
    context, _, _ = _context(tmp_path, timeout_seconds=1.0)

    with pytest.raises(ScenarioActionError) as caught:
        wait_for_completions(
            context,
            completed_count=lambda: 0,
            target_count=1,
            timeout_seconds=1.0,
            label="stalled completion",
            no_progress_timeout_seconds=0.003,
            no_progress_evidence=lambda *_args: (_ for _ in ()).throw(
                RuntimeError("snapshot unavailable")
            ),
        )

    assert caught.value.stage == "no_progress"
    assert caught.value.evidence["liveness"] == {
        "capture_error": "RuntimeError: snapshot unavailable"
    }


def test_completion_wait_outer_deadline_precedes_long_progress_timeout(tmp_path):
    context, _, _ = _context(tmp_path, timeout_seconds=0.004)

    with pytest.raises(ScenarioActionError) as caught:
        wait_for_completions(
            context,
            completed_count=lambda: 0,
            target_count=1,
            timeout_seconds=1.0,
            label="outer deadline",
            no_progress_timeout_seconds=10.0,
        )

    assert caught.value.stage == "timeout"


def test_soft_stop_action_rejects_incorrect_array_state(tmp_path):
    context, _, _ = _context(tmp_path)
    context.app = object()
    context.qt_core = object()
    context.model = object()
    context.view = object()
    context.controller = SimpleNamespace(
        get_array_run_state=lambda: "resume_ready"
    )

    with pytest.raises(ScenarioActionError, match="state running"):
        request_soft_stop_via_ui(
            context,
            completed_count=lambda: 6,
            trigger_count=6,
            timeout_seconds=1,
        )

    assert context.action_results[-1]["failure_stage"] == "precondition"
    assert context.action_results[-1]["evidence"] == {
        "array_state": "resume_ready"
    }


def test_stopped_quiescence_passes_without_progress(tmp_path):
    context, _, _ = _context(tmp_path)
    context.controller = SimpleNamespace(
        get_array_run_state=lambda: "resume_ready"
    )
    context.machine = SimpleNamespace(check_if_all_completed=lambda: True)
    completed = 7
    progress = 7

    result = observe_stopped_quiescence(
        context,
        completed_count=lambda: completed,
        progress_count=lambda: progress,
        observation_ms=250,
    )

    assert result["status"] == "pass"
    assert result["evidence"]["starting_completion_count"] == 7
    assert result["evidence"]["ending_completion_count"] == 7
    assert result["evidence"]["simulator_queue_empty"] is True


def test_stopped_quiescence_rejects_progress_and_deadline(tmp_path):
    context, clock, _ = _context(tmp_path)
    context.controller = SimpleNamespace(
        get_array_run_state=lambda: "resume_ready"
    )
    context.machine = SimpleNamespace(check_if_all_completed=lambda: True)

    with pytest.raises(ScenarioActionError, match="deadline"):
        observe_stopped_quiescence(
            context,
            completed_count=lambda: 7,
            progress_count=lambda: 7,
            observation_ms=6000,
        )
    assert context.action_results[-1]["failure_stage"] == "timeout"

    context, clock, _ = _context(tmp_path / "advances")
    context.controller = SimpleNamespace(
        get_array_run_state=lambda: "resume_ready"
    )
    context.machine = SimpleNamespace(check_if_all_completed=lambda: True)
    starting = clock.value
    with pytest.raises(ScenarioActionError, match="advanced"):
        observe_stopped_quiescence(
            context,
            completed_count=lambda: 8 if clock.value > starting else 7,
            progress_count=lambda: 7,
            observation_ms=250,
        )
    assert context.action_results[-1]["failure_stage"] == "operation"


def test_head_exchange_precondition_requires_idle_and_drained_queue(tmp_path):
    context, _, _ = _context(tmp_path)
    context.controller = SimpleNamespace(get_array_run_state=lambda: "running")
    context.machine = SimpleNamespace(check_if_all_completed=lambda: False)
    context.model = object()

    with pytest.raises(ScenarioActionError, match="idle array"):
        stage_virtual_head(
            context,
            stock_index=0,
            stock_specs=({"factor_name": "A"},),
            calibrated_heads={},
            staging_slot=0,
            stock_id_for=lambda stock: stock["factor_name"],
        )

    assert context.action_results[0]["failure_stage"] == "precondition"
    assert context.action_results[0]["evidence"] == {
        "array_state": "running",
        "queue_drained": False,
    }


def test_head_exchange_records_returned_head_and_effective_settings(tmp_path):
    context, _, events = _context(tmp_path)

    class Head:
        def __init__(self, stock_id, head_id):
            self.stock_id = stock_id
            self.printer_head_id = head_id

        def get_stock_id(self):
            return self.stock_id

    class Slot:
        def __init__(self, printer_head=None):
            self.printer_head = printer_head

    previous = Head("stock-1", "head-1")
    target = Head("stock-2", "head-2")

    class Rack:
        def __init__(self):
            self.slots = [Slot(), Slot(target)]
            self.gripper = previous
            self.gripper_slot_number = 0

        def get_gripper_printer_head(self):
            return self.gripper

        def transfer_from_gripper(self, slot):
            self.slots[slot].printer_head = self.gripper
            self.gripper = None

        def update_slot_with_printer_head(self, slot, head):
            self.slots[slot].printer_head = head

        def confirm_slot(self, _slot):
            return None

        def transfer_to_gripper(self, slot):
            self.gripper = self.slots[slot].printer_head
            self.slots[slot].printer_head = None
            self.gripper_slot_number = slot

    machine_model = SimpleNamespace(
        pulse=0,
        pressure=0.0,
        get_print_pulse_width=lambda: machine_model.pulse,
        get_target_print_pressure=lambda: machine_model.pressure,
    )
    controller = SimpleNamespace(
        get_array_run_state=lambda: "idle",
        set_print_pulse_width=lambda value, update_model: setattr(
            machine_model, "pulse", int(value)
        ),
        set_absolute_print_pressure=lambda value: setattr(
            machine_model, "pressure", float(value)
        ),
    )
    context.machine = SimpleNamespace(check_if_all_completed=lambda: True)
    context.controller = controller
    context.model = SimpleNamespace(rack_model=Rack(), machine_model=machine_model)

    stock_id, head = stage_virtual_head(
        context,
        stock_index=0,
        stock_specs=(
            {
                "factor_name": "stock-2",
                "printer_head": {
                    "printer_head_id": "head-2",
                    "print_pulse_width_us": 1500,
                    "print_pressure_psi": 1.5,
                },
            },
        ),
        calibrated_heads={"stock-2": target},
        staging_slot=0,
        stock_id_for=lambda stock: stock["factor_name"],
    )

    assert stock_id == "stock-2"
    assert head["printer_head_id"] == "head-2"
    evidence = context.action_results[-1]["evidence"]
    assert evidence["previous_stock_id"] == "stock-1"
    assert evidence["previous_printer_head_id"] == "head-1"
    assert evidence["returned_previous"] is True
    assert evidence["queue_drained_before"] is True
    assert evidence["queue_drained_after"] is True
    assert evidence["effective_print_pulse_width_us"] == 1500
    assert evidence["effective_print_pressure_psi"] == 1.5
    assert next(
        event for event in events if event["kind"] == "virtual_head_exchange"
    )["previous_printer_head_id"] == "head-1"


def test_stock_pass_boundary_rejects_wrong_head_association(
    tmp_path,
    monkeypatch,
):
    import ExecutionResumeStore

    context, _, _ = _context(tmp_path)
    active_head = SimpleNamespace(
        printer_head_id="wrong-head",
        get_stock_id=lambda: "stock-1",
    )
    context.controller = SimpleNamespace(get_array_run_state=lambda: "idle")
    context.machine = SimpleNamespace(check_if_all_completed=lambda: True)
    context.model = SimpleNamespace(
        rack_model=SimpleNamespace(
            get_gripper_printer_head=lambda: active_head
        )
    )
    context.experiment_model = SimpleNamespace(
        execution_resume_file_path=tmp_path / "execution_resume.json",
        get_execution_plan_snapshot=lambda: SimpleNamespace(
            state=SimpleNamespace(value="active")
        ),
    )
    monkeypatch.setattr(
        ExecutionResumeStore,
        "load_execution_resume",
        lambda _path: SimpleNamespace(state="clean", intents=()),
    )

    with pytest.raises(ScenarioActionError, match="correctly associated"):
        validate_stock_pass_boundary(
            context,
            pass_index=1,
            stock_id="stock-1",
            printer_head_id="head-1",
            expected_completed_count=24,
            observed_completed_count=lambda: 24,
            expected_plan_state="active",
        )

    assert context.action_results[-1]["failure_stage"] == "operation"
    assert context.action_results[-1]["evidence"][
        "active_printer_head_id"
    ] == "wrong-head"


class FakeImage:
    def __init__(self, *, save=True, null=False):
        self.save_result = save
        self.null = null

    def isNull(self):
        return self.null

    def save(self, path, image_format):
        assert image_format == "PNG"
        if self.save_result:
            Path(path).write_bytes(b"png")
        return self.save_result


def test_milestone_capture_is_contained_nonempty_and_reported(tmp_path):
    context, _, _ = _context(tmp_path)
    context.view = SimpleNamespace(grab=lambda: FakeImage())
    explicit_widget = SimpleNamespace(grab=lambda: FakeImage())

    result = capture_milestone(
        context,
        "ready",
        evidence={"state": "idle"},
        widget=explicit_widget,
    )

    screenshot = context.report_dir / result["evidence"]["screenshot"]
    assert screenshot.read_bytes() == b"png"
    assert context.milestones == [
        {
            "name": "ready",
            "screenshot": "screenshots/ready.png",
            "evidence": {"state": "idle"},
        }
    ]

    with pytest.raises(ScenarioActionError, match="escaped"):
        capture_milestone(context, "../outside")


def test_editor_driver_rejects_the_wrong_modal(qapp, tmp_path):
    from PySide6 import QtCore, QtWidgets

    context, _, _ = _context(tmp_path)
    context.app = qapp
    context.qt_core = QtCore
    button = QtWidgets.QPushButton("Experiment Editor")
    wrong = QtWidgets.QDialog()
    wrong.setWindowTitle("Wrong modal")
    button.clicked.connect(wrong.exec)
    context.view = SimpleNamespace(
        well_plate_widget=SimpleNamespace(
            design_experiment_button=button
        )
    )

    with pytest.raises(
        ScenarioActionError,
        match="unexpected active modal",
    ) as caught:
        drive_editor_create_finalize(context, {})

    assert caught.value.action_id == "editor.open_via_ui"
    assert caught.value.evidence["modal_title"] == "Wrong modal"
    assert wrong.isVisible() is False
    wrong.deleteLater()
    button.deleteLater()
    qapp.processEvents()


def test_editor_driver_propagates_global_deadline_and_rejects_dialog(
    qapp,
    tmp_path,
    monkeypatch,
):
    from PySide6 import QtCore, QtWidgets
    import View

    clock = FakeClock()
    context, _, _ = _context(
        tmp_path,
        timeout_seconds=0.01,
        clock=clock,
    )
    context.app = qapp
    context.qt_core = QtCore
    button = QtWidgets.QPushButton("Experiment Editor")
    dialog = QtWidgets.QDialog()
    dialog.setWindowTitle("Synthetic editor")
    button.clicked.connect(dialog.exec)
    context.view = SimpleNamespace(
        well_plate_widget=SimpleNamespace(
            design_experiment_button=button
        )
    )
    monkeypatch.setattr(View, "ExperimentDesignDialog", QtWidgets.QDialog)
    clock.value += 1.0

    with pytest.raises(ScenarioActionError) as caught:
        drive_editor_create_finalize(context, {})

    assert caught.value.action_id == "editor.open_via_ui"
    assert caught.value.stage == "timeout"
    assert context.action_results[0]["failure_stage"] == "timeout"
    assert dialog.isVisible() is False
    dialog.deleteLater()
    button.deleteLater()
    qapp.processEvents()


def test_editor_rename_driver_rejects_the_wrong_modal(qapp, tmp_path):
    from PySide6 import QtCore, QtWidgets

    context, _, _ = _context(tmp_path)
    context.app = qapp
    context.qt_core = QtCore
    button = QtWidgets.QPushButton("Experiment Editor")
    wrong = QtWidgets.QDialog()
    wrong.setWindowTitle("Wrong rename modal")
    button.clicked.connect(wrong.exec)
    context.view = SimpleNamespace(
        well_plate_widget=SimpleNamespace(
            design_experiment_button=button
        )
    )

    with pytest.raises(
        ScenarioActionError,
        match="unexpected active modal",
    ) as caught:
        drive_editor_prestart_rename_refinalize(
            context,
            initial_name="before",
            renamed_name="after",
            experiment={},
            reagent={},
        )

    assert caught.value.action_id == "editor.open_via_ui"
    assert caught.value.evidence["modal_title"] == "Wrong rename modal"
    assert wrong.isVisible() is False
    assert (context.screenshots_dir / "failure.png").is_file()
    wrong.deleteLater()
    button.deleteLater()
    qapp.processEvents()


def test_editor_rename_driver_propagates_global_deadline_and_rejects_dialog(
    qapp,
    tmp_path,
    monkeypatch,
):
    from PySide6 import QtCore, QtWidgets
    import View

    clock = FakeClock()
    context, _, _ = _context(
        tmp_path,
        timeout_seconds=0.01,
        clock=clock,
    )
    context.app = qapp
    context.qt_core = QtCore
    button = QtWidgets.QPushButton("Experiment Editor")
    dialog = QtWidgets.QDialog()
    dialog.setWindowTitle("Synthetic prepared editor")
    button.clicked.connect(dialog.exec)
    context.view = SimpleNamespace(
        well_plate_widget=SimpleNamespace(
            design_experiment_button=button
        )
    )
    monkeypatch.setattr(View, "ExperimentDesignDialog", QtWidgets.QDialog)
    clock.value += 1.0

    with pytest.raises(ScenarioActionError) as caught:
        drive_editor_prestart_rename_refinalize(
            context,
            initial_name="before",
            renamed_name="after",
            experiment={},
            reagent={},
        )

    assert caught.value.action_id == "editor.open_via_ui"
    assert caught.value.stage == "timeout"
    assert context.action_results[0]["failure_stage"] == "timeout"
    assert dialog.isVisible() is False
    dialog.deleteLater()
    button.deleteLater()
    qapp.processEvents()


def test_post_start_lock_control_matrix_requires_every_mutating_surface(
    qapp,
):
    from PySide6 import QtWidgets

    dialog = QtWidgets.QDialog()
    for name, widget in {
        "exp_name_edit": QtWidgets.QLineEdit(),
        "rep_spin": QtWidgets.QSpinBox(),
        "v_spin": QtWidgets.QDoubleSpinBox(),
        "final_v_spin": QtWidgets.QDoubleSpinBox(),
        "volume_tolerance_spin": QtWidgets.QDoubleSpinBox(),
        "plate_format_combo": QtWidgets.QComboBox(),
        "well_selection_btn": QtWidgets.QPushButton(),
        "add_reagent_btn": QtWidgets.QPushButton(),
        "run_btn": QtWidgets.QPushButton(),
        "save_btn": QtWidgets.QPushButton(),
        "finish_btn": QtWidgets.QPushButton("Experiment Loaded"),
        "duplicate_btn": QtWidgets.QPushButton(),
        "status_lbl": QtWidgets.QLabel("Transient status"),
        "lifecycle_banner": QtWidgets.QLabel(
            "This execution is locked and read-only; create an editable copy."
        ),
        "reagent_table": QtWidgets.QTableWidget(1, 1),
    }.items():
        setattr(dialog, name, widget)
    reagent = QtWidgets.QLineEdit()
    dialog.reagent_table.setCellWidget(0, 0, reagent)
    dialog.lifecycle_banner.show()

    for name in (
        "exp_name_edit",
        "rep_spin",
        "v_spin",
        "final_v_spin",
        "volume_tolerance_spin",
        "plate_format_combo",
        "well_selection_btn",
        "add_reagent_btn",
        "run_btn",
        "save_btn",
        "finish_btn",
    ):
        getattr(dialog, name).setEnabled(False)
    reagent.setReadOnly(True)

    matrix = inspect_editor_lock_controls(dialog)
    assert matrix["all_mutating_controls_locked"] is True
    assert matrix["editable_copy_enabled"] is True
    assert matrix["actionable_lock_guidance"] is True
    assert matrix["banner_visible"] is True
    assert matrix["action_label"] == "Experiment Loaded"

    dialog.exp_name_edit.setEnabled(True)
    matrix = inspect_editor_lock_controls(dialog)
    assert matrix["all_mutating_controls_locked"] is False
    dialog.deleteLater()
    qapp.processEvents()


def test_post_start_driver_rejects_wrong_modal_and_captures_failure(
    qapp,
    tmp_path,
):
    from PySide6 import QtCore, QtWidgets

    context, _, _ = _context(tmp_path)
    context.app = qapp
    context.qt_core = QtCore
    button = QtWidgets.QPushButton("Experiment Editor")
    wrong = QtWidgets.QDialog()
    wrong.setWindowTitle("Wrong post-start modal")
    button.clicked.connect(wrong.exec)
    context.view = SimpleNamespace(
        well_plate_widget=SimpleNamespace(
            design_experiment_button=button
        )
    )

    with pytest.raises(
        ScenarioActionError,
        match="unexpected active modal",
    ) as caught:
        drive_editor_post_start_lock_and_copy(
            context,
            source_dir=tmp_path / "source",
            source_name="source",
            copy_name="copy",
            copy_tolerance_nl=1.0,
        )

    assert caught.value.action_id == "editor.inspect_active_lock_via_ui"
    assert caught.value.evidence["modal_title"] == "Wrong post-start modal"
    assert wrong.isVisible() is False
    assert (context.screenshots_dir / "failure.png").is_file()
    wrong.deleteLater()
    button.deleteLater()
    qapp.processEvents()


def test_post_start_driver_propagates_deadline_and_rejects_dialog(
    qapp,
    tmp_path,
    monkeypatch,
):
    from PySide6 import QtCore, QtWidgets
    import View

    clock = FakeClock()
    context, _, _ = _context(
        tmp_path,
        timeout_seconds=0.01,
        clock=clock,
    )
    context.app = qapp
    context.qt_core = QtCore
    button = QtWidgets.QPushButton("Experiment Editor")
    dialog = QtWidgets.QDialog()
    dialog.setWindowTitle("Synthetic locked editor")
    button.clicked.connect(dialog.exec)
    context.view = SimpleNamespace(
        well_plate_widget=SimpleNamespace(
            design_experiment_button=button
        )
    )
    monkeypatch.setattr(View, "ExperimentDesignDialog", QtWidgets.QDialog)
    clock.value += 1.0

    with pytest.raises(ScenarioActionError) as caught:
        drive_editor_post_start_lock_and_copy(
            context,
            source_dir=tmp_path / "source",
            source_name="source",
            copy_name="copy",
            copy_tolerance_nl=1.0,
        )

    assert caught.value.action_id == "editor.inspect_active_lock_via_ui"
    assert caught.value.stage == "timeout"
    assert dialog.isVisible() is False
    dialog.deleteLater()
    button.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize(
    ("image", "message"),
    [
        (FakeImage(save=False), "could not capture"),
        (FakeImage(null=True), "could not capture"),
    ],
)
def test_milestone_capture_rejects_invalid_images(tmp_path, image, message):
    context, _, _ = _context(tmp_path)
    context.view = SimpleNamespace(grab=lambda: image)

    with pytest.raises(ScenarioActionError, match=message):
        capture_milestone(context, "invalid")


def test_dialog_handler_accepts_allowlisted_and_rejects_unexpected(
    qapp,
    tmp_path,
):
    from PySide6 import QtCore, QtTest, QtWidgets

    context, _, _ = _context(tmp_path)
    context.app = qapp
    context.qt_core = QtCore
    install_dialog_handler(context, ("Allowed",))

    allowed = QtWidgets.QMessageBox(
        QtWidgets.QMessageBox.Icon.Question,
        "Allowed",
        "Proceed?",
        (
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No
        ),
    )
    allowed.show()
    QtTest.QTest.qWait(30)

    unexpected = QtWidgets.QMessageBox(
        QtWidgets.QMessageBox.Icon.Warning,
        "Unexpected",
        "Reject this dialog",
        QtWidgets.QMessageBox.StandardButton.Ok,
    )
    unexpected.show()
    QtTest.QTest.qWait(30)

    assert [item["title"] for item in context.dialogs] == [
        "Allowed",
        "Unexpected",
    ]
    assert context.unexpected_dialogs == [
        {"title": "Unexpected", "text": "Reject this dialog"}
    ]
    assert allowed.isVisible() is False
    assert unexpected.isVisible() is False
    context.dialog_timer.stop()
    allowed.deleteLater()
    unexpected.deleteLater()
    qapp.processEvents()


def test_teardown_attempts_every_phase_after_failure_and_is_idempotent(tmp_path):
    context, clock, _ = _context(tmp_path, timeout_seconds=0.01)
    calls = []

    class Item:
        def __init__(self, name, *, fail=False):
            self.name = name
            self.fail = fail

        def stop(self):
            calls.append(self.name)

        def restore(self):
            calls.append(self.name)
            if self.fail:
                raise RuntimeError(f"{self.name} failure")

        def __exit__(self, *_args):
            calls.append(self.name)

    class App:
        def removeEventFilter(self, _item):
            calls.append("paint_event_filter")

        def processEvents(self):
            calls.append("process_events")

        def sendPostedEvents(self, *_args):
            calls.append("send_posted_events")

    class Machine:
        _command_timer = SimpleNamespace(isActive=lambda: False)
        _connection_timer = SimpleNamespace(isActive=lambda: False)
        _deferred_timers = set()

        def disconnect_board(self):
            calls.append("machine_disconnect")

    class Components:
        view = SimpleNamespace(
            pressure_box=SimpleNamespace(
                _pressure_render_timer=SimpleNamespace(isActive=lambda: False)
            )
        )

        def close(self):
            calls.append("components")

    context.stdout_redirect = Item("stdout_redirect")
    context.dialog_timer = Item("dialog_timer")
    context.paint_filter = object()
    context.instrumentation = Item("instrumentation", fail=True)
    context.progress_observer = Item("progress_observer")
    context.io_observer = Item("persistence_io_observer")
    context.probe = Item("event_loop_probe")
    context.probe_started = True
    context.app = App()
    context.qt_core = SimpleNamespace(
        QEvent=SimpleNamespace(Type=SimpleNamespace(DeferredDelete=object()))
    )
    context.machine = Machine()
    context.components = Components()
    clock.value += 1.0

    with pytest.raises(ScenarioActionError, match="cleanup phase"):
        teardown_scenario(context)

    assert [result["name"] for result in context.cleanup_results] == [
        "stdout_redirect",
        "dialog_timer",
        "paint_event_filter",
        "instrumentation",
        "progress_observer",
        "persistence_io_observer",
        "event_loop_probe",
        "machine_disconnect",
        "components",
        "deferred_qt_deletes",
        "pressure_render_timer",
    ]
    assert calls == [
        "stdout_redirect",
        "dialog_timer",
        "paint_event_filter",
        "instrumentation",
        "progress_observer",
        "persistence_io_observer",
        "event_loop_probe",
        "machine_disconnect",
        "components",
        "process_events",
        "send_posted_events",
        "process_events",
    ]
    assert context.cleanup_results[3]["status"] == "fail"
    assert context.cleanup_results[-1]["status"] == "pass"
    assert context.action_results[-1]["action_id"] == "scenario.teardown"
    assert context.action_results[-1]["failure_stage"] == "cleanup"
    assert context.closed is True

    first_result = context.action_results[-1]
    assert teardown_scenario(context) is first_result
    assert len(context.cleanup_results) == 11


def test_closed_context_rejects_new_actions(tmp_path):
    context, _, _ = _context(tmp_path)
    teardown_scenario(context)

    with pytest.raises(ScenarioActionError, match="already closed"):
        execute_action(
            context,
            "fixture.prepare_authoritative",
            lambda: {},
        )


def test_close_simulated_session_preserves_parent_deadline_and_context(
    tmp_path,
):
    context, clock, events = _context(tmp_path)
    started = context.deadline.started_monotonic

    class Components:
        view = SimpleNamespace(
            pressure_box=SimpleNamespace(
                _pressure_render_timer=SimpleNamespace(
                    isActive=lambda: False
                )
            )
        )

        def close(self):
            return None

    context.components = Components()
    context.application_session_id = "session_1"
    result = close_simulated_session(context, session_id="session_1")

    assert result["status"] == "pass"
    assert result["application_session_id"] == "session_1"
    assert context.deadline.started_monotonic == started
    assert context.closed is False
    assert context.components is None
    assert [item["name"] for item in context.cleanup_results] == [
        f"session_1.{name}"
        for name in (
            "stdout_redirect",
            "dialog_timer",
            "paint_event_filter",
            "instrumentation",
            "progress_observer",
            "persistence_io_observer",
            "event_loop_probe",
            "machine_disconnect",
            "components",
            "deferred_qt_deletes",
            "pressure_render_timer",
        )
    ]
    assert any(
        item.get("application_session_id") == "session_1"
        for item in events
    )
    clock.value += 0.1
    with pytest.raises(ScenarioActionError, match="not active"):
        close_simulated_session(context, session_id="session_1")


def test_action_module_import_is_qt_and_application_free():
    script = """
import sys
import tools.virtual_workflows.actions
forbidden = {
    "App",
    "Controller",
    "Model",
    "View",
    "Machine_FreeRTOS",
    "PySide6",
}
loaded = sorted(forbidden.intersection(sys.modules))
if loaded:
    raise SystemExit(f"unexpected imports: {loaded}")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_prepared_revision_action_supports_legacy_and_harness_execution():
    import inspect

    from tools.virtual_workflows.actions import (
        drive_editor_prestart_rename_refinalize,
    )

    parameter = inspect.signature(
        drive_editor_prestart_rename_refinalize
    ).parameters["action_runner"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None
