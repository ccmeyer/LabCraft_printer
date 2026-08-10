from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from PySide6 import QtCore, QtTest, QtWidgets

from tests.calibration_test_utils import SignalStub, ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from ApplicationComposition import SIMULATION_RUNTIME_CONTEXT
from CalibrationClasses.Model import CalibrationManager
from CalibrationClasses.View import (
    CalibrationModePreflightDialog,
    DropletImagingDialog,
    ManualRefuelCheckDialog,
)
from tools.sil.session import (
    ArtifactRetentionPolicy,
    SessionRootPolicy,
    SimulationSession,
    SimulationSessionConfigV1,
)
from tools.virtual_workflows.page_drivers import CalibrationDialogDriver


_PRINT_PROFILES = [
    {
        "id": "water_droplet",
        "name": "Water - droplet",
        "mode": "droplet",
        "print_pressure": 0.6,
        "refuel_pressure": 0.3,
        "print_pulse_width": 1300,
        "refuel_pulse_width": 3000,
    },
    {
        "id": "water_stream",
        "name": "Water - stream",
        "mode": "stream",
        "print_pressure": 0.8,
        "refuel_pressure": 0.8,
        "print_pulse_width": 2500,
        "refuel_pulse_width": 6000,
    },
]


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
        print_profiles=[dict(profile) for profile in _PRINT_PROFILES],
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
    settings = {
        "current_print": 1.2,
        "current_refuel": 0.3,
        "target_print": 1.2,
        "target_refuel": 0.3,
        "print_pw": 1400,
        "refuel_pw": 3000,
    }
    model.machine_model = SimpleNamespace(
        machine_connected=True,
        machine_state_updated=SignalStub(),
        pressure_updated=SignalStub(),
        printing_parameters_updated=SignalStub(),
        is_connected=lambda: True,
        get_print_pressure_bounds=lambda: (0.1, 5.0),
        get_print_pulse_width=lambda: settings["print_pw"],
        get_refuel_pulse_width=lambda: settings["refuel_pw"],
        get_current_print_pressure=lambda: settings["current_print"],
        get_current_refuel_pressure=lambda: settings["current_refuel"],
        get_target_print_pressure=lambda: settings["target_print"],
        get_target_refuel_pressure=lambda: settings["target_refuel"],
        get_print_pressure_readings=lambda: [1.0, 1.1, settings["current_print"]],
        get_refuel_pressure_readings=lambda: [0.2, 0.25, settings["current_refuel"]],
        _settings=settings,
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
    settings = model.machine_model._settings
    printing_setting_calls = []

    def set_setting(key, value, name, **kwargs):
        settings[key] = value
        printing_setting_calls.append((name, value, dict(kwargs)))
        model.machine_model.printing_parameters_updated.emit()
        return True

    controller.set_absolute_print_pressure = lambda value, **kwargs: set_setting(
        "target_print", float(value), "print_pressure", **kwargs
    )
    controller.set_absolute_refuel_pressure = lambda value, **kwargs: set_setting(
        "target_refuel", float(value), "refuel_pressure", **kwargs
    )
    controller.set_print_pulse_width = lambda value, **kwargs: set_setting(
        "print_pw", int(value), "print_pw", **kwargs
    )
    controller.set_refuel_pulse_width = lambda value, **kwargs: set_setting(
        "refuel_pw", int(value), "refuel_pw", **kwargs
    )

    def apply_profile(profile, callback=None):
        settings.update(
            target_print=float(profile["print_pressure"]),
            target_refuel=float(profile["refuel_pressure"]),
            print_pw=int(profile["print_pulse_width"]),
            refuel_pw=int(profile["refuel_pulse_width"]),
        )
        model.machine_model.printing_parameters_updated.emit()
        if callable(callback):
            callback()
        return True

    controller.apply_print_profile = apply_profile
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
    assert dialog.printing_controls_section.isVisible()
    assert dialog.printing_controls_toggle.isChecked()
    assert dialog.live_pressure_section.isVisible()
    assert dialog.live_pressure_toggle.isChecked()
    dialog._render_live_pressure_plot()
    assert dialog.live_print_pressure_series.count() == 3
    assert dialog.live_refuel_pressure_series.count() == 3
    assert dialog.live_target_print_pressure_series.count() == 2
    assert dialog.live_target_refuel_pressure_series.count() == 2
    assert dialog.target_print_pressure_spinbox.isEnabled()
    assert [
        dialog.print_profile_combo.itemData(index)["id"]
        for index in range(dialog.print_profile_combo.count())
    ] == ["water_droplet"]

    dialog.target_print_pressure_spinbox.setValue(0.7)
    dialog.target_refuel_pressure_spinbox.setValue(0.4)
    dialog.print_pulse_width_spinbox.setValue(1350)
    dialog.refuel_pulse_width_spinbox.setValue(3200)
    qapp.processEvents()
    assert settings == {
        "current_print": 1.2,
        "current_refuel": 0.3,
        "target_print": 0.7,
        "target_refuel": 0.4,
        "print_pw": 1350,
        "refuel_pw": 3200,
    }
    assert [call[0] for call in printing_setting_calls] == [
        "print_pressure",
        "refuel_pressure",
        "print_pw",
        "refuel_pw",
    ]

    dialog.calibration_tabs.setCurrentWidget(dialog.stream_tab)
    qapp.processEvents()
    assert [
        dialog.print_profile_combo.itemData(index)["id"]
        for index in range(dialog.print_profile_combo.count())
    ] == ["water_stream"]
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


def test_synthetic_pulse_preflight_offers_profiles_without_override(qapp):
    profile = {
        "id": "water_stream",
        "name": "Water - stream",
        "mode": "stream",
        "print_pressure": 0.8,
        "refuel_pressure": 0.8,
        "print_pulse_width": 2500,
        "refuel_pulse_width": 6000,
    }
    dialog = CalibrationModePreflightDialog(
        preflight={
            "code": "synthetic_pulse_width_out_of_range",
            "requested_mode": "droplet",
            "head_mode": "droplet",
            "current_print_pulse_width_us": 1300,
            "expected_print_pulse_width_us": 2500,
            "minimum_print_pulse_width_us": 2500,
            "maximum_print_pulse_width_us": 10000,
            "matching_profiles": [profile],
            "message": "Select a compatible Stream profile.",
        }
    )

    button_texts = {button.text() for button in dialog.findChildren(QtWidgets.QPushButton)}

    assert "Apply Selected Profile and Continue" in button_texts
    assert "Review Settings" in button_texts
    assert "Cancel" in button_texts
    assert "Continue Anyway" not in button_texts
    combo = dialog.findChild(QtWidgets.QComboBox)
    assert combo is not None
    assert combo.currentData()["id"] == "water_stream"
    assert "2500 us to 10000 us" in " ".join(
        label.text() for label in dialog.findChildren(QtWidgets.QLabel)
    )
    dialog.close()


def test_synthetic_profile_correction_uses_controller_then_continues(qapp):
    setting = {"pulse": 1300}
    profile = {
        "id": "water_stream",
        "name": "Water - stream",
        "mode": "stream",
        "print_pressure": 0.8,
        "refuel_pressure": 0.8,
        "print_pulse_width": 2500,
        "refuel_pulse_width": 6000,
    }
    applied = []
    continued = []

    def apply_profile(selected, callback=None):
        applied.append(selected["id"])
        setting["pulse"] = selected["print_pulse_width"]
        if callable(callback):
            callback()
        return True

    host = SimpleNamespace(
        controller=SimpleNamespace(apply_print_profile=apply_profile),
        _synthetic_settings_correction_pending=False,
        _refresh_synthetic_workflow_controls=lambda: None,
        _show_calibration_mode_preflight_error=lambda _payload: None,
        isVisible=lambda: True,
        _finish_synthetic_settings_correction=lambda profile_id, **kwargs: continued.append(
            (profile_id, kwargs.get("applied_profile", {}).get("id"))
        ),
    )

    result = DropletImagingDialog._apply_synthetic_profile_then_generate(
        host,
        "droplet_to_stream",
        profile,
    )
    qapp.processEvents()

    assert result is True
    assert applied == ["water_stream"]
    assert setting["pulse"] == 2500
    assert continued == [("droplet_to_stream", "water_stream")]


def test_reusable_historical_candidate_requires_idle_array_and_empty_queue():
    machine = SimpleNamespace(check_if_all_completed=lambda: False)
    host = SimpleNamespace(
        model=SimpleNamespace(
            calibration_manager=SimpleNamespace(
                validate_characterization_candidate_for_application=lambda _row: {
                    "ok": True,
                    "code": "ok",
                }
            )
        ),
        controller=SimpleNamespace(
            machine=machine,
            get_array_run_state=lambda: "running",
        ),
    )
    row = {
        "synthetic": True,
        "_historical_candidate_id": "a" * 64,
        "application_record_state": "generated_unapplied",
    }

    blocked = DropletImagingDialog._validate_selected_characterization_candidate(
        host,
        row,
        require_idle=True,
    )

    assert blocked["ok"] is False
    assert blocked["code"] == "application_busy"

    host.controller.get_array_run_state = lambda: "idle"
    machine.check_if_all_completed = lambda: True
    allowed = DropletImagingDialog._validate_selected_characterization_candidate(
        host,
        row,
        require_idle=True,
    )
    assert allowed["ok"] is True


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


def test_imager_printing_controls_round_trip_through_virtual_machine(qapp, tmp_path):
    session = SimulationSession.create(
        SimulationSessionConfigV1(
            visible=False,
            qt_ownership="borrowed",
            root_policy=SessionRootPolicy.RETAINED,
            session_root=(tmp_path / "imager-printing-controls").resolve(),
            artifact_retention=ArtifactRetentionPolicy.RETAIN,
            seed=1,
            speed_multiplier=1000.0,
            source_identity="pytest-imager-printing-controls",
        )
    )
    dialog = None
    try:
        view = session.launch()
        box = view.pressure_box
        box._simulation_calibration_generate_callback = lambda profile_id: {
            "ok": True,
            "profile_id": profile_id,
            "result_fingerprint": "1" * 64,
        }
        box._simulation_calibration_availability_callback = lambda _profile_id: {
            "ok": True,
            "message": "ready",
        }
        assert session.connect_simulator() is not False
        for _ in range(500):
            qapp.processEvents()
            if session.components.model.machine_model.is_connected():
                break
            QtTest.QTest.qWait(2)
        assert session.components.model.machine_model.is_connected()

        dialog = box._launch_simulation_calibration_dialog()
        assert box._pressure_render_suspended is True
        assert not box._pressure_render_timer.isActive()
        main_print_before = [
            box.print_series.at(index).y()
            for index in range(box.print_series.count())
        ]
        driver = CalibrationDialogDriver(qapp, dialog, timeout_seconds=10.0)
        direct = driver.set_printing_controls(
            "droplet",
            print_pressure_psi=0.72,
            refuel_pressure_psi=0.42,
            print_pulse_width_us=1450,
            refuel_pulse_width_us=3250,
        )
        assert direct["target_print_pressure_psi"] == 0.72
        assert direct["target_refuel_pressure_psi"] == 0.42
        assert direct["print_pulse_width_us"] == 1450
        assert direct["refuel_pulse_width_us"] == 3250
        driver.wait_until(
            lambda: (
                driver.inspect_live_pressure_plot()["series"]["print"]["count"] > 0
                and abs(
                    driver.inspect_live_pressure_plot()["target_print_pressure_psi"]
                    - 0.72
                ) <= 0.005
            ),
            "live pressure samples and direct targets",
        )
        live_direct = driver.inspect_live_pressure_plot()
        assert abs(live_direct["target_print_pressure_psi"] - 0.72) <= 0.005
        assert abs(live_direct["target_refuel_pressure_psi"] - 0.42) <= 0.005
        assert [
            box.print_series.at(index).y()
            for index in range(box.print_series.count())
        ] == main_print_before

        droplet = driver.apply_print_profile_from_panel(
            "droplet",
            "water_droplet",
        )
        assert droplet["profile_ids"] == ["water_droplet"]
        assert droplet["profile_button_text"] == "Loaded"
        assert droplet["target_print_pressure_psi"] == 0.6
        assert droplet["target_refuel_pressure_psi"] == 0.3
        assert droplet["print_pulse_width_us"] == 1300
        assert droplet["refuel_pulse_width_us"] == 3000

        stream = driver.apply_print_profile_from_panel("stream", "water_stream")
        assert "water_droplet" not in stream["profile_ids"]
        assert "water_stream" in stream["profile_ids"]
        assert stream["profile_button_text"] == "Loaded"
        assert stream["target_print_pressure_psi"] == 0.8
        assert stream["target_refuel_pressure_psi"] == 0.8
        assert stream["print_pulse_width_us"] == 2500
        assert stream["refuel_pulse_width_us"] == 6000
        driver.wait_until(
            lambda: abs(
                driver.inspect_live_pressure_plot()["target_print_pressure_psi"]
                - 0.8
            ) <= 0.005,
            "stream target line",
        )
        live_stream = driver.inspect_live_pressure_plot()
        assert abs(live_stream["target_print_pressure_psi"] - 0.8) <= 0.005
        assert abs(live_stream["target_refuel_pressure_psi"] - 0.8) <= 0.005

        dialog.close()
        qapp.processEvents()
        dialog = None
        assert box._pressure_render_suspended is False
        print_readings = (
            session.components.model.machine_model.get_print_pressure_readings()
        )
        assert box.print_series.at(box.print_series.count() - 1).y() == float(
            print_readings[-1]
        )
    finally:
        if dialog is not None:
            dialog.close()
            qapp.processEvents()
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
