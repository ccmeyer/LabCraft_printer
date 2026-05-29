from types import SimpleNamespace

from PySide6 import QtCore, QtWidgets

import RegulatorProfiles as rp
import View
from RegulatorCalibrationWindow import RegulatorCalibrationWindow


class _WindowController(QtCore.QObject):
    regulator_calibration_stage = QtCore.Signal(str)
    regulator_calibration_output = QtCore.Signal(str)
    regulator_calibration_finished = QtCore.Signal(bool, str, object)

    def __init__(self):
        super().__init__()
        self.started_config = None

    def list_regulator_calibration_profiles(self):
        return list(rp.factory_default_document()["profiles"].values())

    def start_regulator_calibration_run(self, config):
        self.started_config = dict(config)
        return True

    def cancel_regulator_calibration_run(self):
        return True


def test_regulator_calibration_window_requires_profile_and_head_confirmation(qapp):
    controller = _WindowController()
    window = RegulatorCalibrationWindow(None, SimpleNamespace(), controller)

    assert window.profile_combo.count() >= 2
    assert window.start_button.isEnabled() is False

    window.calibrated_head_checkbox.setChecked(True)
    qapp.processEvents()
    assert window.start_button.isEnabled() is True

    window._on_start_clicked()

    assert controller.started_config["profile_id"]
    assert controller.started_config["trace_case_id"] in {2101, 2102, 2103, 2104}
    assert controller.started_config["calibrated_head_confirmed"] is True
    assert "print_pressure_psi" not in controller.started_config
    assert window.start_button.isEnabled() is False

    controller.regulator_calibration_finished.emit(
        True,
        "done",
        {"run_dir": "local/regulator_optimization/session/run"},
    )
    assert window.start_button.isEnabled() is True
    assert window.output_path_label.text().endswith("session/run")

    window.close()


class _MachineModel(QtCore.QObject):
    speeds_changed = QtCore.Signal(object)
    accelerations_changed = QtCore.Signal(object)

    def get_current_speeds(self):
        return (1000, 1000, 1000)

    def get_current_accelerations(self):
        return (1000, 1000, 1000)


class _Machine(QtCore.QObject):
    log_stats_updated = QtCore.Signal(object)
    log_message_received = QtCore.Signal(str)


class _SpeedTabController(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.machine = _Machine()

    def set_axis_maxspeed(self, axis, value):
        pass

    def set_axis_accel(self, axis, value):
        pass


def test_firmware_tab_exposes_regulator_calibration_button(qapp):
    main_window = QtWidgets.QWidget()
    main_window.color_dict = {"darker_gray": "#222222"}
    main_window.popup_message = lambda *_args: None
    main_window.popup_yes_no = lambda *_args: QtWidgets.QMessageBox.No
    main_window._is_yes_response = lambda _response: False
    model = SimpleNamespace(machine_model=_MachineModel())
    controller = _SpeedTabController()

    tab = View.SpeedProfilesTab(main_window, model, controller, {"darker_gray": "#222222"})
    button = tab.findChild(QtWidgets.QPushButton, "regulatorCalibrationButton")

    assert button is not None
    assert button.text() == "Regulator Calibration..."

    tab.close()
