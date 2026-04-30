import json
from unittest.mock import Mock

import pytest

from Controller import Controller
from Model import Model


def _write_profiles(path, profiles):
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "profiles": profiles,
            }
        ),
        encoding="utf-8",
    )


def test_model_loads_valid_print_profiles(tmp_path):
    path = tmp_path / "PrintProfiles.json"
    _write_profiles(
        path,
        [
            {
                "id": "water_droplet",
                "name": "Water - droplet",
                "mode": "droplet",
                "material": "water",
                "print_pressure": 0.6,
                "refuel_pressure": 0.3,
                "print_pulse_width": 1300,
                "refuel_pulse_width": 3000,
            }
        ],
    )

    profiles = Model.load_print_profiles(Model.__new__(Model), str(path))

    assert profiles == [
        {
            "id": "water_droplet",
            "name": "Water - droplet",
            "mode": "droplet",
            "material": "water",
            "print_pressure": 0.6,
            "refuel_pressure": 0.3,
            "print_pulse_width": 1300,
            "refuel_pulse_width": 3000,
        }
    ]


def test_model_rejects_invalid_print_profile_shape(tmp_path):
    path = tmp_path / "PrintProfiles.json"
    _write_profiles(
        path,
        [
            {
                "id": "water_droplet",
                "name": "Water - droplet",
                "mode": "droplet",
                "material": "water",
                "print_pressure": 0.6,
                "refuel_pressure": 0.3,
                "print_pulse_width": 1300,
            }
        ],
    )

    with pytest.raises(ValueError, match="missing required keys"):
        Model.load_print_profiles(Model.__new__(Model), str(path))


def test_controller_apply_print_profile_queues_only_existing_print_settings():
    controller = Controller.__new__(Controller)
    calls = []
    callback = object()
    controller.intermediate_callback = Mock()
    controller.handle_settings_change_request = Mock(
        side_effect=lambda settings, cb: calls.append((dict(settings), cb))
    )
    controller.toggle_regulation = Mock()
    controller.enable_print_profile = Mock()

    result = Controller.apply_print_profile(
        controller,
        {
            "id": "water_stream",
            "name": "Water - stream",
            "mode": "stream",
            "material": "water",
            "print_pressure": 0.8,
            "refuel_pressure": 0.8,
            "print_pulse_width": 2500,
            "refuel_pulse_width": 6000,
        },
        callback=callback,
    )

    assert result is True
    assert calls == [
        (
            {
                "print_pressure": 0.8,
                "refuel_pressure": 0.8,
                "print_pulse_width": 2500,
                "refuel_pulse_width": 6000,
            },
            callback,
        )
    ]
    controller.toggle_regulation.assert_not_called()
    controller.enable_print_profile.assert_not_called()
