from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from PySide6 import QtCore, QtTest, QtWidgets

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from ApplicationComposition import SIMULATION_RUNTIME_CONTEXT
from CalibrationClasses.Model import CalibrationManager
from CalibrationClasses.View import DropletImagingDialog, ManualRefuelCheckDialog
from tools.sil.session import (
    ArtifactRetentionPolicy,
    SessionRootPolicy,
    SimulationSession,
    SimulationSessionConfigV1,
)


def _camera_free_model():
    context = {
        "printer_head_id": "head-1",
        "stock_id": "stock-1",
        "factor_name": "Factor A",
        "option_name": "",
        "is_fill": False,
        "printing_mode": "droplet",
        "design_volume_nL": 9.0,
    }
    head = SimpleNamespace(serial="head-1", printing_mode="droplet")
    experiment = SimpleNamespace(
        _resolve_applied_imaging_context=lambda **_kwargs: dict(context),
    )
    model = SimpleNamespace(
        machine_state_updated=SignalStub(),
        rack_model=SimpleNamespace(get_gripper_printer_head=lambda: head),
        experiment_model=experiment,
    )
    manager = CalibrationManager(model)
    manager.ensure_loaded = lambda: None
    manager.data = {"runs": []}
    model.calibration_manager = manager
    model.droplet_camera_model = SimpleNamespace(
        flash_duration=1000,
        flash_delay=2000,
        num_droplets=1,
        exposure_time=5000,
        droplet_image_updated=SignalStub(),
        flash_signal=SignalStub(),
    )
    model.refuel_camera_model = None
    model.machine_model = SimpleNamespace(
        get_print_pressure_bounds=lambda: (0.1, 5.0),
        get_print_pulse_width=lambda: 1400,
        get_current_print_pressure=lambda: 1.2,
    )
    return model, context, head


def test_experiment_switch_detaches_run_and_preserves_legacy_empty_file(
    tmp_path,
):
    model, _context, _head = _camera_free_model()
    manager = model.calibration_manager
    prior_path = tmp_path / "prior-calibration.json"
    empty_path = tmp_path / "empty-calibration.json"
    prior_path.write_text(
        '{"schema_version":1,"runs":[{"steps":{}}]}',
        encoding="utf-8",
    )
    empty_path.write_text("{}", encoding="utf-8")
    empty_before = empty_path.read_bytes()
    manager.calibration_file_path = str(prior_path)
    manager.data = {"schema_version": 1, "runs": [{"steps": {}}]}
    manager._run_id = "prior-run"
    manager._run_idx = 0

    manager.update_calibration_file_path(str(empty_path))

    assert manager._run_id is None
    assert manager._run_idx is None
    assert manager.data == {"schema_version": 1, "runs": []}
    assert manager._latest_step_list("droplet_emergence") == []
    manager._emit_readiness()
    assert empty_path.read_bytes() == empty_before


def test_full_layout_simulation_calibration_uses_real_tabs_but_no_camera(
    monkeypatch,
    qapp,
):
    model, _context, _head = _camera_free_model()
    physical_calls = []

    def forbidden(name):
        return lambda *args, **kwargs: physical_calls.append(name)

    controller = SimpleNamespace(
        start_droplet_camera=forbidden("start_droplet_camera"),
        stop_droplet_camera=forbidden("stop_droplet_camera"),
        start_read_camera=forbidden("start_read_camera"),
        stop_read_camera=forbidden("stop_read_camera"),
        set_droplet_capture_profile=forbidden("set_droplet_capture_profile"),
        set_command_dispatch_interval=forbidden("set_command_dispatch_interval"),
        disable_print_profile=forbidden("disable_print_profile"),
        start_droplet_calibration_sequence=forbidden("droplet_sequence"),
        start_stream_calibration_sequence=forbidden("stream_sequence"),
        get_array_run_state=lambda: "idle",
        machine=SimpleNamespace(check_if_all_completed=lambda: True),
    )
    main_window = QtWidgets.QWidget()
    main_window.color_dict = {}
    main_window.runtime_context = SIMULATION_RUNTIME_CONTEXT
    generated = []

    def generate(profile_id):
        generated.append(profile_id)
        return {
            "ok": True,
            "result_fingerprint": f"{len(generated):064x}",
        }

    monkeypatch.setattr(
        DropletImagingDialog,
        "refresh_calibration_memory_recommendation",
        lambda self, *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "CalibrationClasses.View.QtWidgets.QMessageBox.question",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )

    dialog = DropletImagingDialog(
        main_window,
        model,
        controller,
        simulation_workflow_mode=True,
        synthetic_generation_callback=generate,
        synthetic_availability_callback=lambda profile_id: {
            "ok": True,
            "message": (
                "Ready: 9.000 nL Droplet -> 40.000 nL Stream."
                if profile_id == "droplet_to_stream"
                else f"Ready for {profile_id}"
            ),
        },
    )
    finished_results = []
    dialog.finished.connect(finished_results.append)
    dialog.open()
    qapp.processEvents()

    assert dialog.parentWidget() is main_window
    assert dialog.synthetic_calibration_banner.isVisible()
    assert dialog.control_panel_scroll.isVisible()
    assert dialog.analysis_panel.isVisible()
    assert "CAMERA DISABLED" in dialog.image_label.text()
    assert not dialog.calibration_tabs.isTabEnabled(
        dialog.calibration_tabs.indexOf(dialog.debug_tab)
    )
    assert not dialog.calibration_tabs.isTabEnabled(
        dialog.calibration_tabs.indexOf(dialog.optics_tab)
    )
    assert not dialog.prime_head_button.isEnabled()
    assert not dialog.calibrate_pressure_scan_button.isEnabled()
    assert dialog.calibrate_all_button.isEnabled()
    assert dialog.calibrate_all_stream_button.isEnabled()

    dialog.calibration_tabs.setCurrentWidget(dialog.stream_tab)
    qapp.processEvents()
    assert "Droplet \u2192 Stream" in dialog.synthetic_calibration_mode_label.text()
    assert "9.000 nL Droplet -> 40.000 nL Stream" in (
        dialog.synthetic_calibration_mode_label.text()
    )

    dialog.calibrate_all_button.click()
    dialog.calibrate_all_stream_button.click()
    qapp.processEvents()

    assert generated == ["nominal_droplet", "droplet_to_stream"]
    assert dialog.isVisible()
    assert QtWidgets.QApplication.activeModalWidget() is dialog
    assert physical_calls == []
    dialog.close()
    qapp.processEvents()
    assert finished_results == [QtWidgets.QDialog.Rejected]
    assert physical_calls == []
    main_window.close()


def test_normal_calibrate_button_routes_to_simulation_workflow(qapp, tmp_path):
    session = SimulationSession.create(
        SimulationSessionConfigV1(
            visible=False,
            qt_ownership="borrowed",
            root_policy=SessionRootPolicy.RETAINED,
            session_root=(tmp_path / "normal-calibrate-button").resolve(),
            artifact_retention=ArtifactRetentionPolicy.RETAIN,
            seed=1,
            speed_multiplier=1000.0,
            source_identity="pytest-m4c",
        )
    )
    try:
        view = session.launch()
        box = view.pressure_box
        launches = []
        box._simulation_calibration_availability_callback = lambda _profile: {
            "ok": True,
            "message": "ready",
        }
        box._launch_simulation_calibration_dialog = (
            lambda: launches.append("simulation_calibration")
        )

        box.calibrate_pressure_button.click()
        qapp.processEvents()

        assert launches == ["simulation_calibration"]
    finally:
        assert session.close()


def test_post_calibration_refuel_trial_dispatches_before_dialog_closes(
    monkeypatch,
    qapp,
    tmp_path,
):
    session = SimulationSession.create(
        SimulationSessionConfigV1(
            visible=False,
            qt_ownership="borrowed",
            root_policy=SessionRootPolicy.RETAINED,
            session_root=(tmp_path / "post-calibration-refuel-dispatch").resolve(),
            artifact_retention=ArtifactRetentionPolicy.RETAIN,
            seed=1,
            speed_multiplier=1000.0,
            source_identity="pytest-m4c-refuel-handoff",
        )
    )
    try:
        view = session.launch()
        box = view.pressure_box
        machine = session.components.machine
        controller = session.components.controller
        lifecycle = []
        dialog_events = []
        completed_while_visible = []
        machine.command_lifecycle_changed.connect(
            lambda payload: lifecycle.append(dict(payload))
        )

        assert session.connect_simulator() is not False
        for _ in range(400):
            qapp.processEvents()
            if machine.state.connected:
                break
            QtTest.QTest.qWait(1)
        assert machine.state.connected is True

        assert machine.regulate_print_pressure() is not False
        for _ in range(400):
            qapp.processEvents()
            if machine.check_if_all_completed():
                break
            QtTest.QTest.qWait(1)
        assert machine.check_if_all_completed()

        monkeypatch.setattr(box, "_manual_refuel_check_preflight_passed", lambda: True)

        def move_to_loading(_name, *, manual, on_complete):
            assert manual is True
            return machine.set_absolute_XY(123, 456, handler=on_complete)

        monkeypatch.setattr(controller, "move_to_location", move_to_loading)

        class _DispatchProbeDialog(QtWidgets.QDialog):
            def __init__(self, main_window_arg, model_arg, controller_arg, **kwargs):
                super().__init__(main_window_arg)
                assert main_window_arg is view
                assert model_arg is session.components.model
                assert controller_arg is controller
                assert callable(kwargs.get("simulation_outcome_callback"))
                dialog_events.append("initialized")

            def exec(self):
                dialog_events.append("exec")

                def queue_trial():
                    assert self.isVisible()
                    command = controller.print_droplets(5, manual=True)
                    assert command is not False and command is not None
                    dialog_events.append("trial_queued")

                    def finish_when_completed():
                        if command.status == "Completed":
                            completed_while_visible.append(self.isVisible())
                            dialog_events.append("trial_completed")
                            self.accept()
                            return
                        QtCore.QTimer.singleShot(1, finish_when_completed)

                    finish_when_completed()

                QtCore.QTimer.singleShot(0, queue_trial)
                QtCore.QTimer.singleShot(3000, self.reject)
                return super().exec()

        monkeypatch.setattr(
            "View.CalibrationClasses.ManualRefuelCheckDialog",
            _DispatchProbeDialog,
        )

        box.manual_refuel_check_after_stream_apply()
        for _ in range(800):
            qapp.processEvents()
            if "trial_completed" in dialog_events:
                break
            QtTest.QTest.qWait(1)

        assert dialog_events == [
            "initialized",
            "exec",
            "trial_queued",
            "trial_completed",
        ]
        assert completed_while_visible == [True]
        dispense_events = [
            event["event"]
            for event in lifecycle
            if event.get("command_type") == "DISPENSE"
        ]
        assert dispense_events == [
            "queued",
            "sent",
            "accepted",
            "executing",
            "completed",
        ]
        assert box._manual_refuel_check_launch_is_active() is False
    finally:
        assert session.close()


def test_simulation_calibration_mode_rejects_noncanonical_runtime(qapp):
    calls = []
    main_window = SimpleNamespace(color_dict={}, runtime_context=object())
    model = SimpleNamespace(droplet_camera_model=object(), refuel_camera_model=None)
    controller = SimpleNamespace(start_droplet_camera=lambda: calls.append("camera"))

    try:
        DropletImagingDialog(
            main_window,
            model,
            controller,
            simulation_workflow_mode=True,
            synthetic_generation_callback=lambda _profile: {"ok": True},
            synthetic_availability_callback=lambda _profile: {"ok": True},
        )
    except RuntimeError as exc:
        assert "canonical simulation runtime" in str(exc)
    else:
        raise AssertionError("noncanonical simulation workflow was accepted")
    assert calls == []


def test_real_manual_refuel_dialog_uses_simulated_recorder_with_trial_metadata(qapp):
    parent = QtWidgets.QWidget()
    parent.runtime_context = SIMULATION_RUNTIME_CONTEXT
    parent.color_dict = {}
    recorded = []
    controller = SimpleNamespace(
        check_if_all_completed=Mock(return_value=True),
        move_to_location=Mock(return_value=True),
        refuel_only=Mock(return_value=True),
        print_only=Mock(return_value=True),
        print_droplets=Mock(return_value=True),
        set_relative_refuel_pressure=Mock(return_value=True),
        record_manual_refuel_check_outcome=Mock(
            side_effect=AssertionError("production recorder must not be called")
        ),
        pause_commands=Mock(),
    )

    def record(status, **kwargs):
        recorded.append((status, kwargs))
        return {"ok": True, "status": status}

    dialog = ManualRefuelCheckDialog(
        parent,
        SimpleNamespace(),
        controller,
        simulation_outcome_callback=record,
        expected_calibration_fingerprint="fingerprint-1",
    )
    dialog.show()
    qapp.processEvents()

    assert dialog.synthetic_refuel_banner.isVisible()
    assert dialog.run_paired_trial(10) is True
    assert dialog.record_outcome("unclear", "unclear") is True
    assert recorded == [
        (
            "unclear",
            {
                "expected_calibration_fingerprint": "fingerprint-1",
                "operator_judgment": "unclear",
                "trial_droplet_count": 10,
                "trial_count": 1,
            },
        )
    ]
    controller.print_droplets.assert_called_once_with(10, manual=True)
    controller.record_manual_refuel_check_outcome.assert_not_called()
    dialog.close()
