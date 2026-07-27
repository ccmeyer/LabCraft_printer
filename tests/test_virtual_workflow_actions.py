from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.virtual_workflows.actions import (
    ACTION_IDS,
    ScenarioActionError,
    ScenarioContext,
    capture_milestone,
    drive_editor_create_finalize,
    execute_action,
    install_dialog_handler,
    stage_virtual_head,
    teardown_scenario,
    wait_for_completions,
    wait_until,
)
from tools.virtual_workflows.registry import load_capability_manifest


REPO_ROOT = Path(__file__).resolve().parents[1]


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
        "tools/virtual_workflows/actions.py"
    }


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
