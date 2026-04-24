from types import SimpleNamespace
from Model import Model, MachineModel


def test_model_update_state_maps_status_fields(qapp):
    model = Model.__new__(Model)
    model.machine_model = MachineModel()
    model.droplet_camera_model = SimpleNamespace(
        update_num_flashes=lambda *_: None,
        update_flash_duration=lambda *_: None,
        update_flash_delay=lambda *_: None,
        update_num_droplets=lambda *_: None,
        update_trigger_counter=lambda *_: None,
    )
    emitted = []
    model.machine_state_updated = SimpleNamespace(emit=lambda: emitted.append(1))

    status = {
        "X": 100,
        "Y": 200,
        "Z": 300,
        "P": 400,
        "R": 500,
        "Tar_X": 110,
        "Tar_Y": 210,
        "Tar_Z": 310,
        "Tar_P": 410,
        "Tar_R": 510,
        "Pressure_P": model.machine_model.psi_offset,
        "Pressure_R": model.machine_model.psi_offset + model.machine_model.fss,
        "Current_command": 9,
        "Last_completed": 8,
        "Disp_freq": 12,
        "X_max_hz": 1000,
        "Y_max_hz": 1100,
        "Z_max_hz": 1200,
        "X_accel": 10,
        "Y_accel": 11,
        "Z_accel": 12,
    }

    model.update_state(status)

    mm = model.machine_model
    assert (mm.current_x, mm.current_y, mm.current_z) == (100, 200, 300)
    assert (mm.target_x, mm.target_y, mm.target_z) == (110, 210, 310)
    assert (mm.current_p, mm.current_r) == (400, 500)
    assert (mm.target_p, mm.target_r) == (410, 510)
    assert mm.current_command_num == 9
    assert mm.last_completed_command_num == 8
    assert mm.get_dispense_frequency_hz() == 12
    assert mm.x_max_hz == 1000 and mm.y_max_hz == 1100 and mm.z_max_hz == 1200
    assert mm.x_accel == 10 and mm.y_accel == 11 and mm.z_accel == 12
    assert len(emitted) == 1


def test_model_update_state_applies_regulator_activity_flags(qapp):
    model = Model.__new__(Model)
    model.machine_model = MachineModel()
    model.droplet_camera_model = SimpleNamespace(
        update_num_flashes=lambda *_: None,
        update_flash_duration=lambda *_: None,
        update_flash_delay=lambda *_: None,
        update_num_droplets=lambda *_: None,
        update_trigger_counter=lambda *_: None,
    )
    model.machine_state_updated = SimpleNamespace(emit=lambda: None)

    emissions = []
    model.machine_model.regulation_state_changed.connect(lambda active: emissions.append(active))

    model.update_state({"print_active": 1, "refuel_active": 0})

    assert model.machine_model.regulating_print_pressure is True
    assert model.machine_model.regulating_refuel_pressure is False
    assert emissions == [True]


def test_model_update_state_maps_gripper_refresh_and_pulse_fields(qapp):
    model = Model.__new__(Model)
    model.machine_model = MachineModel()
    model.droplet_camera_model = SimpleNamespace(
        update_num_flashes=lambda *_: None,
        update_flash_duration=lambda *_: None,
        update_flash_delay=lambda *_: None,
        update_num_droplets=lambda *_: None,
        update_trigger_counter=lambda *_: None,
    )
    model.machine_state_updated = SimpleNamespace(emit=lambda: None)

    model.update_state({"Grip_refresh": 30000, "Grip_pulse": 1500})

    assert model.machine_model.get_gripper_settings() == (30000, 1500)


def test_model_update_flash_session_state_updates_droplet_camera_and_emits(qapp):
    model = Model.__new__(Model)
    captured = []
    model.droplet_camera_model = SimpleNamespace(
        update_flash_session_state=lambda **kwargs: captured.append(kwargs),
    )
    emissions = []
    model.machine_state_updated = SimpleNamespace(emit=lambda: emissions.append(True))

    model.update_flash_session_state(
        {
            "flash_session_armed": True,
            "flash_fault_latched": True,
            "flash_fault_reason": "line_stuck_high",
        }
    )

    assert captured == [
        {
            "armed": True,
            "fault_latched": True,
            "fault_reason": "line_stuck_high",
        }
    ]
    assert emissions == [True]


def test_model_set_dispense_frequency_hz_is_session_only(tmp_path):
    model = Model.__new__(Model)
    model.machine_model = MachineModel()
    model.settings_path = str(tmp_path / "Settings.json")
    model.settings = {
        "DEFAULT_DISPENSER": "droplet",
        "DISPENSER_TYPES": {
            "droplet": {
                "frequency": 10,
            }
        },
    }

    assert Model.set_dispense_frequency_hz(model, 14) is True

    assert model.machine_model.get_dispense_frequency_hz() == 14
    assert model.settings["DISPENSER_TYPES"]["droplet"]["frequency"] == 10
    assert not (tmp_path / "Settings.json").exists()
