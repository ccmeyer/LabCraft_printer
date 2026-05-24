import sys
from types import SimpleNamespace

import Machine_FreeRTOS as machine_mod
from Machine_FreeRTOS import RefuelCamera


class _FakeLine:
    def __init__(self):
        self.values = []
        self.release_count = 0

    def set_value(self, value):
        self.values.append(int(value))

    def release(self):
        self.release_count += 1


class _FakePicamera2:
    instances = []

    def __init__(self, camera_index):
        self.camera_index = camera_index
        self.sensor_resolution = (3280, 2464)
        self.still_config_kwargs = None
        self.configured_with = None
        self.controls = None
        self.start_count = 0
        self.stop_count = 0
        self.close_count = 0
        _FakePicamera2.instances.append(self)

    def create_still_configuration(self, **kwargs):
        self.still_config_kwargs = dict(kwargs)
        return {"kind": "still", **kwargs}

    def configure(self, config):
        self.configured_with = dict(config)

    def set_controls(self, controls):
        self.controls = dict(controls)

    def start(self):
        self.start_count += 1

    def stop(self):
        self.stop_count += 1

    def close(self):
        self.close_count += 1


def _install_refuel_camera_fakes(monkeypatch):
    _FakePicamera2.instances = []
    fake_line = _FakeLine()
    monkeypatch.setattr(machine_mod, "_gpiofind", lambda _name: ("gpiochip-test", 27))
    monkeypatch.setattr(machine_mod, "_make_output_line", lambda *_args, **_kwargs: fake_line)
    monkeypatch.setitem(
        sys.modules,
        "picamera2",
        SimpleNamespace(Picamera2=_FakePicamera2),
    )
    return fake_line


def test_refuel_camera_start_locks_picamera_controls(monkeypatch):
    _install_refuel_camera_fakes(monkeypatch)
    refuel_camera = RefuelCamera()

    refuel_camera.start_camera()

    assert len(_FakePicamera2.instances) == 1
    camera = _FakePicamera2.instances[0]
    assert camera.camera_index == 0
    assert camera.still_config_kwargs == {
        "main": {"size": camera.sensor_resolution, "format": "RGB888"}
    }
    assert camera.configured_with == {
        "kind": "still",
        "main": {"size": camera.sensor_resolution, "format": "RGB888"},
    }
    assert camera.controls == {
        "FrameDurationLimits": (20_000, 20_000),
        "ExposureTime": 20_000,
        "AeEnable": False,
        "AwbEnable": False,
        "AnalogueGain": 1.0,
    }
    assert camera.start_count == 1


def test_refuel_camera_start_is_idempotent(monkeypatch):
    _install_refuel_camera_fakes(monkeypatch)
    refuel_camera = RefuelCamera()

    refuel_camera.start_camera()
    first_camera = refuel_camera.camera
    refuel_camera.start_camera()

    assert refuel_camera.camera is first_camera
    assert len(_FakePicamera2.instances) == 1
    assert first_camera.start_count == 1


def test_refuel_camera_control_defaults_follow_instance_settings(monkeypatch):
    _install_refuel_camera_fakes(monkeypatch)
    refuel_camera = RefuelCamera()
    refuel_camera.exposure_time = 15_000
    refuel_camera.frame_duration_us = 18_000
    refuel_camera.analogue_gain = 1.5

    assert refuel_camera.get_camera_control_defaults() == {
        "FrameDurationLimits": (18_000, 18_000),
        "ExposureTime": 15_000,
        "AeEnable": False,
        "AwbEnable": False,
        "AnalogueGain": 1.5,
    }
