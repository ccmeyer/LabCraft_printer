"""Exercise real imager conversions and motion guards without physical dependencies."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget

from CalibrationClasses.Model import DropletCameraModel
from CalibrationClasses.View import DropletImagingDialog, NozzlePositionDatasetCaptureWindow
from ConfigurationSafetyPolicy import (
    ConfigurationChangeGuard,
    load_configuration_change_policy,
    parse_safety_bounds,
)
from Controller import Controller
from utilities.shortcuts import ShortcutManager


AXES = ('X', 'Y', 'Z')
ORIGIN = {'X': 10000, 'Y': 10000, 'Z': 10000}
WINDOWS = (DropletImagingDialog, NozzlePositionDatasetCaptureWindow)


class RecordingMachine:
    def __init__(self):
        self.calls = []
        self.fail_axis = None

    def _queue(self, axis, value, **kwargs):
        self.calls.append((axis, value, kwargs))
        return False if axis == self.fail_axis else object()

    def set_relative_X(self, value, **kwargs):
        return self._queue('X', value, **kwargs)

    def set_relative_Y(self, value, **kwargs):
        return self._queue('Y', value, **kwargs)

    def set_relative_Z(self, value, **kwargs):
        return self._queue('Z', value, **kwargs)


@pytest.fixture
def motion(tmp_path):
    calibration = tmp_path / 'steps.json'
    calibration.write_text(
        json.dumps({'intercept_cx': 0, 'intercept_cy': 0, 'A': [[1, 0], [0, 1]]}),
        encoding='utf-8',
    )
    camera = DropletCameraModel(calibration, optics_config_path=tmp_path / 'optics.json')
    camera.image_width, camera.image_height = 100, 80
    safety = {
        'boundaries': {'min': dict.fromkeys(AXES, 0), 'max': dict.fromkeys(AXES, 20000)},
        'obstacles': [],
    }
    controller = Controller.__new__(Controller)
    controller.machine = RecordingMachine()
    controller.model = SimpleNamespace(
        droplet_camera_model=camera,
        location_model=SimpleNamespace(
            get_boundaries=lambda: safety['boundaries'],
            get_obstacles=lambda: safety['obstacles'],
        ),
    )
    controller.expected_position = dict(ORIGIN)
    controller.error_occurred_signal = Mock()
    controller._pending_motion_endpoint_evidence = {'queue_result': 'previous'}
    controller.configuration_safety_guard = ConfigurationChangeGuard(
        load_configuration_change_policy(), parse_safety_bounds(safety)
    )
    yield SimpleNamespace(controller=controller, camera=camera, safety=safety)
    camera.shutdown()


@pytest.fixture(params=WINDOWS, ids=lambda window: window.__name__)
def imager(request, motion, qapp):
    # Avoid window bootstrap, camera acquisition, and flash-session initialization.
    parent = QWidget()
    window_type = request.param
    host = SimpleNamespace(
        model=motion.controller.model,
        controller=motion.controller,
        shortcut_manager=ShortcutManager(parent),
        _pressure_shortcuts=[],
        toggle_flash=Mock(),
    )
    host.move_fraction_of_frame = window_type.move_fraction_of_frame.__get__(host, window_type)
    window_type.setup_shortcuts(host)
    shortcuts = {shortcut.key().toString(): shortcut for shortcut in parent.findChildren(QShortcut)}
    yield SimpleNamespace(host=host, shortcuts=shortcuts)
    parent.deleteLater()
    qapp.processEvents()


def _activate(imager, key):
    imager.shortcuts[QKeySequence(key).toString()].activated.emit()


@pytest.mark.parametrize(
    ('key', 'axis', 'delta'),
    [
        ('Left', 'X', -10),
        ('Right', 'X', 10),
        ('Up', 'Z', -8),
        ('Down', 'Z', 8),
        ('Ctrl+Left', 'X', -100),
        ('Ctrl+Right', 'X', 100),
        ('Ctrl+Up', 'Z', -80),
        ('Ctrl+Down', 'Z', 80),
    ],
)
def test_arrow_shortcuts_queue_integer_image_plane_jogs(imager, motion, key, axis, delta):
    controller = motion.controller

    _activate(imager, key)

    assert controller.machine.calls == [(axis, delta, {'manual': False, 'handler': None})]
    assert type(controller.machine.calls[0][1]) is int
    assert controller.expected_position == {**ORIGIN, axis: ORIGIN[axis] + delta}
    assert all(type(value) is int for value in controller.expected_position.values())
    controller.error_occurred_signal.emit.assert_not_called()


@pytest.mark.parametrize(
    ('key', 'delta'),
    [('k', 4), ('j', -4), ('Ctrl+k', 24), ('Ctrl+j', -24)],
)
def test_focus_shortcuts_preserve_integer_y_jogs(imager, motion, key, delta):
    controller = motion.controller

    _activate(imager, key)

    assert controller.machine.calls == [('Y', delta, {'manual': True, 'handler': None})]
    assert type(controller.machine.calls[0][1]) is int
    assert controller.expected_position == {**ORIGIN, 'Y': ORIGIN['Y'] + delta}
    controller.error_occurred_signal.emit.assert_not_called()


@pytest.mark.parametrize(
    ('key', 'requested', 'canonical'),
    [('Right', 5, 4), ('Left', -5, -4)],
)
def test_imager_jogs_preserve_odd_displacement_quantization(imager, motion, key, requested, canonical):
    motion.camera.image_width = 50

    _activate(imager, key)

    controller = motion.controller
    assert controller.machine.calls == [('X', canonical, {'manual': False, 'handler': None})]
    assert controller.expected_position == {**ORIGIN, 'X': ORIGIN['X'] + canonical}
    assert controller._pending_motion_endpoint_evidence['requested_displacement']['X'] == requested
    controller.error_occurred_signal.emit.assert_not_called()


@pytest.mark.parametrize('fractions', [(0.1, 0), (-0.1, 0), (0, 0)])
def test_imager_subquantum_and_zero_jogs_queue_nothing(imager, motion, fractions):
    motion.camera.image_width = 10
    controller = motion.controller
    previous = controller._pending_motion_endpoint_evidence

    imager.host.move_fraction_of_frame(*fractions)

    assert controller.machine.calls == []
    assert controller.expected_position == ORIGIN
    assert controller._pending_motion_endpoint_evidence is previous
    controller.error_occurred_signal.emit.assert_not_called()


@pytest.mark.parametrize('axis', AXES)
@pytest.mark.parametrize('invalid', [0.0, 1.5, True])
def test_invalid_relative_input_fails_before_queueing_or_callback(motion, axis, invalid):
    controller = motion.controller
    previous = controller._pending_motion_endpoint_evidence
    completed = Mock()
    delta = dict.fromkeys(AXES, 0)
    delta[axis] = invalid

    accepted = controller.set_relative_coordinates(
        delta['X'], delta['Y'], delta['Z'], handler=completed
    )

    assert accepted is False
    assert controller.machine.calls == []
    assert controller.expected_position == ORIGIN
    assert controller._pending_motion_endpoint_evidence is previous
    completed.assert_not_called()
    title, message = controller.error_occurred_signal.emit.call_args.args
    assert title == 'Motion Target Rejected'
    assert f'requested {axis} displacement must be an integer' in message


@pytest.mark.parametrize('blocked_by', ['bounds', 'obstacle'])
def test_imager_jog_preserves_normal_safety_rejection(imager, motion, blocked_by):
    controller = motion.controller
    previous = controller._pending_motion_endpoint_evidence
    if blocked_by == 'bounds':
        motion.safety['boundaries']['max']['X'] = ORIGIN['X'] + 5
    else:
        motion.safety['obstacles'].append({
            'corner1': {'X': 10004, 'Y': 9999, 'Z': 9999},
            'corner2': {'X': 10006, 'Y': 10001, 'Z': 10001},
        })
    controller.configuration_safety_guard = ConfigurationChangeGuard(
        load_configuration_change_policy(), parse_safety_bounds(motion.safety)
    )

    _activate(imager, 'Right')

    assert controller.machine.calls == []
    assert controller.expected_position == ORIGIN
    assert controller._pending_motion_endpoint_evidence is previous
    if blocked_by == 'bounds':
        assert controller.error_occurred_signal.emit.call_args.args[0] == 'Motion Endpoint Rejected'
    else:
        controller.error_occurred_signal.emit.assert_not_called()


@pytest.mark.parametrize('z_fraction', [-0.1, 0.1])
def test_camera_move_stops_after_first_queue_rejection(motion, z_fraction):
    controller = motion.controller
    previous = controller._pending_motion_endpoint_evidence
    move = motion.camera.compute_move_by_fraction(0.1, z_fraction)
    first_axis, first_delta = ('Z', -8) if z_fraction < 0 else ('X', 10)
    controller.machine.fail_axis = first_axis
    completed = Mock()

    accepted = controller.set_relative_coordinates(*move, handler=completed)

    assert accepted is False
    assert controller.machine.calls == [(first_axis, first_delta, {'manual': False, 'handler': None})]
    assert controller.expected_position == ORIGIN
    assert controller._pending_motion_endpoint_evidence is previous
    completed.assert_not_called()
