import json
from types import SimpleNamespace

from CalibrationClasses.Model import DropletCameraModel
from Model import MachineModel, Model
from tests.test_calibration_memory_ui_recommendation import _build_real_dialog_for_layout


def test_repeated_status_chunks_preserve_frontiers_but_batch_ui_signals(
    qapp,
    monkeypatch,
    tmp_path,
):
    machine_model = MachineModel()
    steps_path = tmp_path / "steps.json"
    steps_path.write_text(
        json.dumps(
            {
                "intercept_cx": 0,
                "intercept_cy": 0,
                "A": [[1.0, 0.0], [0.0, 1.0]],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(DropletCameraModel, "OPTICS_CONFIG_PATH", tmp_path / "optics.json")
    camera_model = DropletCameraModel(steps_conv_path=str(steps_path))
    host_model = Model.__new__(Model)
    host_model.machine_model = machine_model
    host_model.droplet_camera_model = camera_model
    machine_state_emissions = []
    host_model.machine_state_updated = SimpleNamespace(
        emit=lambda: machine_state_emissions.append(1)
    )
    printing_emissions = []
    flash_emissions = []
    pressure_emissions = []
    frontier_emissions = []
    machine_model.printing_parameters_updated.connect(
        lambda: printing_emissions.append(1)
    )
    camera_model.flash_signal.connect(lambda: flash_emissions.append(1))
    machine_model.pressure_updated.connect(lambda: pressure_emissions.append(1))
    machine_model.command_numbers_updated.connect(lambda: frontier_emissions.append(1))
    status = {
        "Pressure_P": machine_model.psi_offset + 100,
        "Pressure_R": machine_model.psi_offset + 50,
        "Tar_print": machine_model.psi_offset + 1000,
        "Tar_refuel": machine_model.psi_offset + 500,
        "Print_width": 1400,
        "Refuel_width": 3200,
        "Grip_pulse": 1500,
        "Grip_refresh": 30000,
        "Flashes": 3,
        "Flash_width": 1100,
        "Flash_delay": 2100,
        "Flash_droplets": 2,
        "Ext_counter": 7,
        "Current_command": 9,
        "Last_completed": 8,
        "Last_accepted": 9,
        "Last_retired": 8,
        "cmd_depth": 1,
    }

    try:
        for _ in range(1000):
            Model.update_state(host_model, status)
    finally:
        camera_model.shutdown()

    assert printing_emissions == [1]
    assert flash_emissions == [1]
    assert len(pressure_emissions) == 2000
    assert len(frontier_emissions) == 1000
    assert len(machine_state_emissions) == 1000


def test_dialog_coalesces_status_bursts_without_model_driven_focus_work(
    monkeypatch,
    qapp,
):
    dialog = _build_real_dialog_for_layout(
        monkeypatch,
        qapp,
        main_window=SimpleNamespace(color_dict={}),
    )
    camera = dialog.model.droplet_camera_model
    camera.num_flashes = 0
    camera.ext_counter = 0
    camera.get_num_flashes = lambda: int(camera.num_flashes)
    camera.get_trigger_counter = lambda: 0
    camera.get_flash_duration = lambda: int(camera.flash_duration)
    camera.get_flash_delay = lambda: int(camera.flash_delay)
    camera.get_num_droplets = lambda: int(camera.num_droplets)
    camera.get_exposure_time = lambda: int(camera.exposure_time)
    dialog._reset_status_ui_runtime_diagnostics()

    for _ in range(1000):
        dialog.model.machine_model.pressure_updated.emit()
        dialog.model.machine_model.printing_parameters_updated.emit()
        camera.flash_signal.emit()
        dialog.model.machine_model.machine_state_updated.emit()

    before = dialog.get_status_ui_refresh_diagnostics()
    assert before["pending_count"] == 1
    assert before["max_pending_count"] == 1
    assert before["batch_count"] == 0
    assert before["manual_focus"]["request_count"] == 0

    qapp.processEvents()
    after = dialog.get_status_ui_refresh_diagnostics()
    assert after["pending_count"] == 0
    assert after["batch_count"] == 1
    assert after["request_count"] == 3001
    assert after["coalesced_request_count"] == 3000
    assert after["manual_focus"]["request_count"] == 0

    dialog._mark_manual_spinbox_typed_edit(dialog.flash_duration_spinbox)
    dialog._mark_manual_spinbox_typed_edit(dialog.flash_duration_spinbox)
    assert dialog.manual_focus_refresh_timer.isActive()
    qapp.processEvents()
    focus = dialog.get_status_ui_refresh_diagnostics()["manual_focus"]
    assert focus == {
        "request_count": 2,
        "batch_count": 1,
        "coalesced_request_count": 1,
        "pending_count": 0,
        "max_pending_count": 1,
    }

    dialog.deactivate_session(reason="test_complete")
    retained = dialog.get_status_ui_refresh_diagnostics()["request_count"]
    dialog.model.machine_model.pressure_updated.emit()
    dialog.model.machine_model.printing_parameters_updated.emit()
    camera.flash_signal.emit()
    qapp.processEvents()
    assert dialog.get_status_ui_refresh_diagnostics()["request_count"] == retained
    assert not dialog.status_ui_refresh_timer.isActive()
    assert not dialog.manual_focus_refresh_timer.isActive()
    dialog.deleteLater()
    qapp.processEvents()
