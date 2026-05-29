from types import SimpleNamespace

from PySide6 import QtCore, QtWidgets

import RegulatorProfiles as rp
import View
from RegulatorCalibrationWindow import RegulatorCalibrationWindow


class _WindowController(QtCore.QObject):
    regulator_calibration_stage = QtCore.Signal(str)
    regulator_calibration_output = QtCore.Signal(str)
    regulator_calibration_finished = QtCore.Signal(bool, str, object)
    regulator_calibration_batch_stage = QtCore.Signal(str)
    regulator_calibration_batch_output = QtCore.Signal(str)
    regulator_calibration_batch_progress = QtCore.Signal(int, int, object)
    regulator_calibration_batch_finished = QtCore.Signal(bool, str, object)

    def __init__(self):
        super().__init__()
        self.started_config = None
        self.started_batch_config = None
        self.started_sweep_config = None

    def list_regulator_calibration_profiles(self):
        return list(rp.factory_default_document()["profiles"].values())

    def get_regulator_calibration_active_profile_id(self, mode):
        return rp.factory_default_document()["active_profiles"].get(mode)

    def start_regulator_calibration_run(self, config):
        self.started_config = dict(config)
        return True

    def cancel_regulator_calibration_run(self):
        return True

    def start_regulator_calibration_batch(self, config):
        self.started_batch_config = dict(config)
        return True

    def cancel_regulator_calibration_batch(self):
        return True

    def start_regulator_calibration_sweep(self, config):
        self.started_sweep_config = dict(config)
        return True

    def cancel_regulator_calibration_sweep(self):
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
    assert controller.started_config["serial_handoff_mode"] == "soft"
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


def test_regulator_calibration_window_custom_trace_config(qapp):
    controller = _WindowController()
    window = RegulatorCalibrationWindow(None, SimpleNamespace(), controller)

    custom_index = window.trace_case_combo.findData(2110)
    assert custom_index >= 0
    window.trace_case_combo.setCurrentIndex(custom_index)
    window.custom_channel_combo.setCurrentText("print")
    window.custom_pressure_spin.setValue(1.25)
    window.custom_pulse_spin.setValue(1450)
    window.custom_pulse_count_spin.setValue(20)
    window.custom_frequency_spin.setValue(20)
    window.calibrated_head_checkbox.setChecked(True)
    qapp.processEvents()

    assert window.custom_group.isHidden() is False
    assert window.start_button.isEnabled() is True
    window._on_start_clicked()

    assert controller.started_config["trace_case_id"] == 2110
    assert controller.started_config["trace_channel"] == "print"
    assert controller.started_config["trace_pressure_psi"] == 1.25
    assert controller.started_config["trace_pulse_us"] == 1450
    assert controller.started_config["trace_pulse_count"] == 20
    assert controller.started_config["trace_frequency_hz"] == 20

    window.close()


def test_regulator_calibration_window_batch_controls_validate_and_finish(qapp):
    controller = _WindowController()
    window = RegulatorCalibrationWindow(None, SimpleNamespace(), controller)

    assert window.batch_start_button.isEnabled() is False

    window.batch_calibrated_head_checkbox.setChecked(True)
    for index in range(window.batch_candidate_list.count()):
        item = window.batch_candidate_list.item(index)
        if item.data(QtCore.Qt.UserRole) == "stream_default":
            item.setCheckState(QtCore.Qt.Checked)
            break
    qapp.processEvents()

    assert window.batch_start_button.isEnabled() is True
    window._on_batch_start_clicked()

    assert controller.started_batch_config["mode"] == "stream"
    assert controller.started_batch_config["candidate_profile_ids"] == ["stream_default"]
    assert controller.started_batch_config["repeat_count"] == 1
    assert controller.started_batch_config["calibrated_head_confirmed"] is True
    assert controller.started_batch_config["serial_handoff_mode"] == "soft"
    assert window.batch_start_button.isEnabled() is False
    assert window.start_button.isEnabled() is False

    controller.regulator_calibration_batch_progress.emit(
        1,
        2,
        {"role": "candidate", "profile_id": "stream_default"},
    )
    assert "1/2" in window.batch_status_label.text()

    controller.regulator_calibration_batch_finished.emit(
        True,
        "batch done",
        {
            "session_dir": "local/regulator_optimization/session",
            "manifest": {"analysis": {"candidate_ranking_csv": "local/ranking.csv"}},
        },
    )
    assert window.batch_start_button.isEnabled() is True
    assert window.batch_path_label.text().endswith("ranking.csv")

    window.close()


def test_regulator_calibration_window_can_select_full_shutdown_handoff(qapp):
    controller = _WindowController()
    window = RegulatorCalibrationWindow(None, SimpleNamespace(), controller)

    window.calibrated_head_checkbox.setChecked(True)
    window.handoff_combo.setCurrentIndex(window.handoff_combo.findData("full_disconnect"))
    qapp.processEvents()
    window._on_start_clicked()

    assert controller.started_config["serial_handoff_mode"] == "full_disconnect"

    window.batch_calibrated_head_checkbox.setChecked(True)
    for index in range(window.batch_candidate_list.count()):
        item = window.batch_candidate_list.item(index)
        if item.data(QtCore.Qt.UserRole) == "stream_default":
            item.setCheckState(QtCore.Qt.Checked)
            break
    window.batch_handoff_combo.setCurrentIndex(window.batch_handoff_combo.findData("full_disconnect"))
    qapp.processEvents()
    controller.regulator_calibration_finished.emit(True, "done", {})
    window._on_batch_start_clicked()

    assert controller.started_batch_config["serial_handoff_mode"] == "full_disconnect"

    window.close()


def test_regulator_calibration_window_sweep_controls_validate_preview_and_start(qapp):
    controller = _WindowController()
    window = RegulatorCalibrationWindow(None, SimpleNamespace(), controller)

    assert window.sweep_start_button.isEnabled() is False

    window.sweep_calibrated_head_checkbox.setChecked(True)
    window.sweep_value_edits[0].setText("3,4")
    window.sweep_field_combos[1].setCurrentText("slew.max_hz_delta_up_per_loop")
    window.sweep_value_edits[1].setText("800")
    qapp.processEvents()

    assert window.sweep_start_button.isEnabled() is True
    assert "3 candidates" in window.sweep_preview_label.text()

    window._on_sweep_start_clicked()

    assert controller.started_sweep_config["mode"] == "stream"
    assert controller.started_sweep_config["baseline_profile_id"] == "stream_default"
    assert controller.started_sweep_config["mutated_channel"] == "print"
    assert controller.started_sweep_config["sweep_strategy"] == "one_at_a_time"
    assert controller.started_sweep_config["sweep_fields"] == [
        {"field_path": "recovery.active_ticks", "values": "3,4"},
        {"field_path": "slew.max_hz_delta_up_per_loop", "values": "800"},
    ]
    assert controller.started_sweep_config["serial_handoff_mode"] == "soft"
    assert window.start_button.isEnabled() is False
    assert window.batch_start_button.isEnabled() is False
    assert window.sweep_start_button.isEnabled() is False

    controller.regulator_calibration_batch_finished.emit(
        True,
        "sweep done",
        {
            "session_dir": "local/regulator_optimization/session",
            "manifest": {"analysis": {"candidate_ranking_csv": "local/sweep_ranking.csv"}},
        },
    )
    assert window.sweep_start_button.isEnabled() is True
    assert window.sweep_path_label.text().endswith("sweep_ranking.csv")

    window.close()


def test_regulator_calibration_window_sweep_grid_limit_blocks_start(qapp):
    controller = _WindowController()
    window = RegulatorCalibrationWindow(None, SimpleNamespace(), controller)

    window.sweep_calibrated_head_checkbox.setChecked(True)
    window.sweep_strategy_combo.setCurrentIndex(window.sweep_strategy_combo.findData("grid"))
    window.sweep_value_edits[0].setText("3,4,5,6")
    window.sweep_field_combos[1].setCurrentText("slew.max_hz_delta_up_per_loop")
    window.sweep_value_edits[1].setText("800,900,1000,1100")
    qapp.processEvents()

    assert window.sweep_start_button.isEnabled() is False
    assert "exceeds" in window.sweep_preview_label.text()

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
