import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from Controller import Controller
from Model import Model


_PREFLIGHT_PROFILES = [
    {
        "id": "water_droplet",
        "name": "Water - droplet",
        "mode": "droplet",
        "material": "water",
        "print_pressure": 0.6,
        "refuel_pressure": 0.3,
        "print_pulse_width": 1300,
        "refuel_pulse_width": 3000,
    },
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
]


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


def _controller_for_mode_preflight(*, head_mode="droplet", print_pulse_width=1300, profiles=None):
    controller = Controller.__new__(Controller)
    printer_head = (
        None
        if head_mode is None
        else SimpleNamespace(get_printing_mode=lambda mode=head_mode: mode)
    )
    controller.model = SimpleNamespace(
        machine_model=SimpleNamespace(get_print_pulse_width=lambda: print_pulse_width),
        rack_model=SimpleNamespace(get_gripper_printer_head=lambda: printer_head),
        print_profiles=list(profiles if profiles is not None else _PREFLIGHT_PROFILES),
    )
    return controller


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


def test_calibration_mode_preflight_accepts_droplet_head_with_droplet_pulse_width():
    controller = _controller_for_mode_preflight(
        head_mode="droplet",
        print_pulse_width=1300,
    )

    result = Controller.get_calibration_mode_preflight(controller, "droplet")

    assert result["ok"] is True
    assert result["code"] == "ok"
    assert result["requested_mode"] == "droplet"
    assert result["head_mode"] == "droplet"
    assert result["current_print_pulse_width_us"] == 1300
    assert result["expected_print_pulse_width_us"] == 1300


def test_calibration_mode_preflight_accepts_stream_head_with_stream_pulse_width():
    controller = _controller_for_mode_preflight(
        head_mode="stream",
        print_pulse_width=2500,
    )

    result = Controller.get_calibration_mode_preflight(controller, "stream")

    assert result["ok"] is True
    assert result["code"] == "ok"
    assert result["requested_mode"] == "stream"
    assert result["head_mode"] == "stream"
    assert result["current_print_pulse_width_us"] == 2500
    assert result["expected_print_pulse_width_us"] == 2500


def test_calibration_mode_preflight_flags_droplet_pulse_width_mismatch_with_profiles():
    controller = _controller_for_mode_preflight(
        head_mode="droplet",
        print_pulse_width=2500,
    )

    result = Controller.get_calibration_mode_preflight(controller, "droplet")

    assert result["ok"] is False
    assert result["code"] == "pulse_width_mismatch"
    assert result["matching_profiles"] == [_PREFLIGHT_PROFILES[0]]


def test_calibration_mode_preflight_flags_stream_pulse_width_mismatch_with_profiles():
    controller = _controller_for_mode_preflight(
        head_mode="stream",
        print_pulse_width=1300,
    )

    result = Controller.get_calibration_mode_preflight(controller, "stream")

    assert result["ok"] is False
    assert result["code"] == "pulse_width_mismatch"
    assert result["matching_profiles"] == [_PREFLIGHT_PROFILES[1]]


def test_calibration_mode_preflight_flags_head_mode_mismatch():
    controller = _controller_for_mode_preflight(
        head_mode="stream",
        print_pulse_width=1300,
    )

    result = Controller.get_calibration_mode_preflight(controller, "droplet")

    assert result["ok"] is False
    assert result["code"] == "head_mode_mismatch"
    assert result["requested_mode"] == "droplet"
    assert result["head_mode"] == "stream"


def test_calibration_mode_preflight_fails_closed_without_loaded_head():
    controller = _controller_for_mode_preflight(
        head_mode=None,
        print_pulse_width=1300,
    )

    result = Controller.get_calibration_mode_preflight(controller, "droplet")

    assert result["ok"] is False
    assert result["code"] == "no_printer_head"
