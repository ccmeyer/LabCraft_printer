from types import SimpleNamespace

import View


LEFT = {"X": 1000, "Y": 100, "Z": 48000}
RIGHT = {"X": 1000, "Y": 4000, "Z": 48000}
HOME = {"X": 500, "Y": 500, "Z": 500}


class FakeMainWindow:
    def __init__(self):
        self.color_dict = {
            "dark_blue": "#000088",
            "darker_gray": "#222222",
        }
        self.messages = []

    def popup_message(self, title, message):
        self.messages.append((title, message))


class FakeController:
    def __init__(self):
        self.calls = []

    def set_absolute_coordinates(self, x, y, z, **kwargs):
        self.calls.append((int(x), int(y), int(z), dict(kwargs)))
        return True


class FakeButton:
    def __init__(self):
        self.enabled = None
        self.styles = []

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)

    def setStyleSheet(self, style):
        self.styles.append(style)


class FakeLabel:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = text


class FakeMachineModel:
    def __init__(self, current_position):
        self.current_position = current_position.copy()

    def get_current_position_dict_capital(self):
        return self.current_position.copy()

    def is_busy(self):
        return False


class FakeLocationModel:
    def __init__(self, home_location=HOME):
        self.home_location = home_location

    def get_location_dict(self, name):
        if name == "home":
            return self.home_location
        return None


class FakeRackModel:
    def __init__(self):
        self.calibrations = {
            "rack_position_Left": LEFT.copy(),
            "rack_position_Right": RIGHT.copy(),
        }
        self.temp_calibration_data = {}

    def get_all_current_rack_calibrations(self):
        return self.calibrations

    def get_calibration_by_name(self, name):
        return self.calibrations.get(name)

    def get_temp_calibration_by_name(self, name):
        return self.temp_calibration_data.get(name)

    def set_calibration_position(self, name, position):
        self.temp_calibration_data[name] = position.copy()

    def discard_temp_calibrations(self):
        self.temp_calibration_data.clear()


class FakeWellPlate:
    def __init__(self):
        self.calibrations = {
            "top_left": {"X": 100, "Y": 200, "Z": 300},
            "top_right": {"X": 100, "Y": 400, "Z": 300},
            "bottom_right": {"X": 300, "Y": 400, "Z": 300},
            "bottom_left": {"X": 300, "Y": 200, "Z": 300},
        }
        self.temp_calibration_data = {}

    def get_all_current_plate_calibrations(self):
        return self.calibrations

    def get_calibration_by_name(self, name):
        return self.calibrations.get(name)

    def get_temp_calibration_by_name(self, name):
        return self.temp_calibration_data.get(name)

    def set_calibration_position(self, name, position):
        self.temp_calibration_data[name] = position.copy()

    def discard_temp_calibrations(self):
        self.temp_calibration_data.clear()


def _install_ui_stubs(dialog):
    dialog.instructions_label = FakeLabel()
    dialog.next_button = FakeButton()
    dialog.back_button = FakeButton()
    dialog.submit_button = FakeButton()
    dialog.update_step_labels = lambda: None
    dialog.update_visual_aid = lambda: None


def make_rack_dialog(*, current_step=0, current_position=None, home_location=HOME):
    dialog = View.RackCalibrationDialog.__new__(View.RackCalibrationDialog)
    dialog.main_window = FakeMainWindow()
    dialog.color_dict = dialog.main_window.color_dict
    dialog.controller = FakeController()
    dialog.steps = ["Left", "Right"]
    dialog.name_dict = {
        "Left": "rack_position_Left",
        "Right": "rack_position_Right",
    }
    dialog.offsets = {"X": 2500, "Y": 0, "Z": 0}
    dialog.current_step = current_step
    dialog.model = SimpleNamespace(
        rack_model=FakeRackModel(),
        machine_model=FakeMachineModel(current_position or LEFT),
        location_model=FakeLocationModel(home_location),
    )
    _install_ui_stubs(dialog)
    return dialog


def make_plate_dialog():
    dialog = View.PlateCalibrationDialog.__new__(View.PlateCalibrationDialog)
    dialog.main_window = FakeMainWindow()
    dialog.color_dict = dialog.main_window.color_dict
    dialog.controller = FakeController()
    dialog.steps = ["Top-Left", "Top-Right", "Bottom-Right", "Bottom-Left"]
    dialog.name_dict = {
        "Top-Left": "top_left",
        "Top-Right": "top_right",
        "Bottom-Right": "bottom_right",
        "Bottom-Left": "bottom_left",
    }
    dialog.offsets = {"X": 0, "Y": 0, "Z": -500}
    dialog.current_step = 0
    dialog.model = SimpleNamespace(
        well_plate=FakeWellPlate(),
        machine_model=FakeMachineModel({"X": 100, "Y": 200, "Z": 300}),
    )
    return dialog


def coord_calls(dialog):
    return [(x, y, z, kwargs) for x, y, z, kwargs in dialog.controller.calls]


def test_initial_rack_dialog_move_uses_existing_clearance_then_target():
    dialog = make_rack_dialog(current_step=0, current_position=HOME)

    result = View.RackCalibrationDialog.move_to_initial_position(dialog)

    assert result is True
    assert coord_calls(dialog) == [
        (3500, 100, 48000, {"override": True}),
        (1000, 100, 48000, {"override": True}),
    ]
    assert dialog.main_window.messages == []


def test_rack_next_step_lifts_to_home_z_before_crossing_left_to_right():
    dialog = make_rack_dialog(current_step=0, current_position=LEFT)

    result = View.RackCalibrationDialog.next_step(dialog)

    assert result is True
    assert dialog.current_step == 1
    assert coord_calls(dialog) == [
        (3500, 100, 48000, {"override": True}),
        (3500, 4000, 500, {"override": True}),
        (3500, 4000, 48000, {"override": True}),
        (1000, 4000, 48000, {"override": True}),
    ]


def test_rack_previous_step_lifts_to_home_z_before_crossing_right_to_left():
    dialog = make_rack_dialog(current_step=1, current_position=RIGHT)

    result = View.RackCalibrationDialog.previous_step(dialog)

    assert result is True
    assert dialog.current_step == 0
    assert coord_calls(dialog) == [
        (3500, 4000, 48000, {"override": True}),
        (3500, 100, 500, {"override": True}),
        (3500, 100, 48000, {"override": True}),
        (1000, 100, 48000, {"override": True}),
    ]


def test_rack_final_confirm_only_moves_to_existing_clearance_position():
    dialog = make_rack_dialog(current_step=1, current_position=RIGHT)

    result = View.RackCalibrationDialog.next_step(dialog)

    assert result is True
    assert dialog.current_step == 2
    assert coord_calls(dialog) == [
        (3500, 4000, 48000, {"override": True}),
    ]
    assert dialog.instructions_label.text == "Calibration complete."
    assert dialog.next_button.enabled is False
    assert dialog.submit_button.enabled is True


def test_rack_side_to_side_blocks_when_home_z_is_unavailable():
    dialog = make_rack_dialog(current_step=0, current_position=LEFT, home_location={"X": 1, "Y": 2})

    result = View.RackCalibrationDialog.next_step(dialog)

    assert result is False
    assert dialog.current_step == 0
    assert coord_calls(dialog) == []
    assert dialog.model.rack_model.temp_calibration_data == {}
    assert dialog.main_window.messages == [
        (
            "Rack Calibration Move Error",
            "Cannot move between rack calibration positions because home Z is unavailable.",
        )
    ]


def test_plate_calibration_initial_move_remains_unchanged():
    dialog = make_plate_dialog()

    result = View.PlateCalibrationDialog.move_to_initial_position(dialog)

    assert result is None
    assert coord_calls(dialog) == [
        (100, 200, -200, {"override": True}),
        (100, 200, 300, {"override": True}),
    ]
    assert dialog.main_window.messages == []
