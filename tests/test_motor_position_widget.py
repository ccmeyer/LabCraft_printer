from types import SimpleNamespace
from unittest.mock import Mock, call

from PySide6.QtCore import QObject, Qt, Signal

from View import MotorPositionWidget


class _FakeMachineModel(QObject):
    step_size_changed = Signal(int)
    motor_state_changed = Signal(bool)
    machine_state_updated = Signal(bool)
    home_status_signal = Signal()

    def __init__(self, *, connected=False, motors_enabled=False, motors_homed=False):
        super().__init__()
        self.machine_connected = connected
        self.motors_enabled = motors_enabled
        self.motors_homed = motors_homed
        self.possible_steps = [10, 50, 250]
        self.step_size = 50
        self.current_x = 0
        self.current_y = 0
        self.current_z = 0
        self.current_p = 0
        self.current_r = 0
        self.target_x = 0
        self.target_y = 0
        self.target_z = 0
        self.target_p = 0
        self.target_r = 0

    def is_connected(self):
        return self.machine_connected

    def motors_are_enabled(self):
        return self.motors_enabled

    def motors_are_homed(self):
        return self.motors_homed

    def set_step_size(self, step_size):
        self.step_size = step_size


class _FakeLocationModel(QObject):
    locations_updated = Signal()

    def __init__(self, location_names):
        super().__init__()
        self.location_names = list(location_names)

    def get_location_names(self):
        return list(self.location_names)


class _FakeModel(QObject):
    machine_state_updated = Signal()

    def __init__(self, machine_model, location_model):
        super().__init__()
        self.machine_model = machine_model
        self.location_model = location_model


def _make_widget(
    *,
    connected=False,
    motors_enabled=False,
    motors_homed=False,
    location_names=("home", "loading", "camera"),
    profile_name="legacy",
):
    machine_model = _FakeMachineModel(
        connected=connected,
        motors_enabled=motors_enabled,
        motors_homed=motors_homed,
    )
    location_model = _FakeLocationModel(location_names)
    model = _FakeModel(machine_model, location_model)
    main_window = SimpleNamespace(
        color_dict={
            "green": "#16a34a",
            "dark_blue": "#1d4ed8",
            "light_blue": "#60a5fa",
        },
        profile=SimpleNamespace(name=profile_name),
        move_to_location=Mock(),
    )
    controller = SimpleNamespace(home_machine=Mock(), toggle_motors=Mock())
    widget = MotorPositionWidget(main_window, model, controller)
    return widget, main_window, machine_model, location_model


def _assert_all_location_buttons_enabled(widget, expected):
    assert all(button.isEnabled() is expected for button in widget.location_buttons.values())


def test_standard_location_buttons_and_home_motors_label(qapp):
    widget, _main_window, _machine_model, _location_model = _make_widget(
        connected=True,
        motors_enabled=True,
        motors_homed=True,
    )

    assert widget.home_button.text() == "Home Motors"
    assert widget.location_buttons["home"].text() == "Home Position"
    assert widget.location_buttons["loading"].text() == "Loading"
    assert widget.location_buttons["camera"].text() == "Camera"
    _assert_all_location_buttons_enabled(widget, True)


def test_location_buttons_follow_connection_motor_and_home_signals(qapp):
    widget, _main_window, machine_model, _location_model = _make_widget()

    _assert_all_location_buttons_enabled(widget, False)
    assert "Connect" in widget.location_buttons["home"].toolTip()

    machine_model.machine_connected = True
    machine_model.machine_state_updated.emit(True)
    _assert_all_location_buttons_enabled(widget, False)
    assert "Enable" in widget.location_buttons["home"].toolTip()

    machine_model.motors_enabled = True
    machine_model.motor_state_changed.emit(True)
    _assert_all_location_buttons_enabled(widget, False)
    assert "Home" in widget.location_buttons["home"].toolTip()

    machine_model.motors_homed = True
    machine_model.home_status_signal.emit()
    _assert_all_location_buttons_enabled(widget, True)

    machine_model.motors_homed = False
    machine_model.home_status_signal.emit()
    _assert_all_location_buttons_enabled(widget, False)

    machine_model.motors_homed = True
    machine_model.motors_enabled = False
    machine_model.motor_state_changed.emit(False)
    _assert_all_location_buttons_enabled(widget, False)


def test_missing_location_disables_only_its_button_and_refreshes(qapp):
    widget, _main_window, _machine_model, location_model = _make_widget(
        connected=True,
        motors_enabled=True,
        motors_homed=True,
        location_names=("home", "loading"),
    )

    assert widget.location_buttons["home"].isEnabled()
    assert widget.location_buttons["loading"].isEnabled()
    assert not widget.location_buttons["camera"].isEnabled()
    assert "not configured" in widget.location_buttons["camera"].toolTip()

    location_model.location_names.append("camera")
    location_model.locations_updated.emit()

    _assert_all_location_buttons_enabled(widget, True)


def test_location_buttons_use_guarded_main_window_move_path(qapp):
    widget, main_window, _machine_model, _location_model = _make_widget(
        connected=True,
        motors_enabled=True,
        motors_homed=True,
    )

    widget.location_buttons["home"].click()
    widget.location_buttons["loading"].click()
    widget.location_buttons["camera"].click()

    assert main_window.move_to_location.call_args_list == [
        call(location="home", manual=True),
        call(location="loading", manual=True),
        call(location="camera", manual=True),
    ]


def test_position_columns_remain_fixed_as_values_gain_digits(qapp):
    widget, _main_window, machine_model, _location_model = _make_widget(profile_name="current")
    widget.resize(432, widget.sizeHint().height())
    widget.show()
    qapp.processEvents()

    position_labels = [
        label
        for positions in widget.labels.values()
        for label in positions.values()
    ]
    initial_geometry = [
        (label.geometry().x(), label.geometry().width())
        for label in position_labels
    ]

    for label in position_labels:
        assert label.minimumWidth() == label.maximumWidth()
        assert label.alignment() & Qt.AlignRight

    for value in (9999, 10000, 130000):
        machine_model.current_x = value
        machine_model.current_y = value
        machine_model.current_z = value
        machine_model.current_p = value
        machine_model.current_r = value
        machine_model.target_x = value
        machine_model.target_y = value
        machine_model.target_z = value
        machine_model.target_p = value
        machine_model.target_r = value

        widget.update_labels()
        qapp.processEvents()

        assert [
            (label.geometry().x(), label.geometry().width())
            for label in position_labels
        ] == initial_geometry
        assert all(label.text() == str(value) for label in position_labels)
        assert all(label.toolTip() == str(value) for label in position_labels)

    assert widget.minimumSizeHint().width() <= 432
    widget.close()
