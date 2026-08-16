from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6 import QtCharts, QtCore, QtWidgets

from tests.calibration_test_utils import ensure_calibration_import_stubs


ensure_calibration_import_stubs()

from CalibrationClasses.View import (
    CharacterizationSummaryProxyModel,
    CharacterizationSummaryTableModel,
)
from tools.sil.synthetic_calibration import (
    CalibrationGenerationRequestV1,
    SyntheticCalibrationProvider,
)
from tools.virtual_workflows.page_drivers import CalibrationDialogDriver
from utilities import apply_pressure_plot_style


class _Dialog(QtWidgets.QDialog):
    def __init__(self, row):
        super().__init__()
        self.setWindowTitle("Synthetic Droplet Calibration Result — No Hardware")
        layout = QtWidgets.QVBoxLayout(self)
        banner = QtWidgets.QLabel(
            "SYNTHETIC CALIBRATION — NO CAMERA OR PHYSICAL EVIDENCE"
        )
        banner.setObjectName("syntheticCalibrationBanner")
        layout.addWidget(banner)
        mode_label = QtWidgets.QLabel("Synthetic mode: Droplet")
        mode_label.setObjectName("syntheticCalibrationModeLabel")
        layout.addWidget(mode_label)
        self.summary_source_combo = QtWidgets.QComboBox()
        self.summary_source_combo.addItem("Synthetic", "synthetic")
        layout.addWidget(self.summary_source_combo)
        self.summary_table_model = CharacterizationSummaryTableModel(self)
        self.summary_table_proxy_model = CharacterizationSummaryProxyModel(self)
        self.summary_table_proxy_model.setSourceModel(self.summary_table_model)
        self.summary_table_model.set_rows([row])
        self.summary_table = QtWidgets.QTableView()
        self.summary_table.setObjectName("characterizationSummaryTable")
        self.summary_table.setModel(self.summary_table_proxy_model)
        self.summary_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        layout.addWidget(self.summary_table)
        self.calibration_tabs = QtWidgets.QTabWidget()
        self.droplet_tab = QtWidgets.QWidget()
        self.stream_tab = QtWidgets.QWidget()
        self.calibration_tabs.addTab(self.droplet_tab, "Droplet")
        self.calibration_tabs.addTab(self.stream_tab, "Stream")
        self.calibrate_all_button = QtWidgets.QPushButton("Calibrate All")
        self.calibrate_all_stream_button = QtWidgets.QPushButton("Calibrate All")
        self.droplet_tab.setLayout(QtWidgets.QVBoxLayout())
        self.stream_tab.setLayout(QtWidgets.QVBoxLayout())
        self.droplet_tab.layout().addWidget(self.calibrate_all_button)
        self.stream_tab.layout().addWidget(self.calibrate_all_stream_button)
        layout.addWidget(self.calibration_tabs)
        self._printing_settings = {
            "print_pressure": 1.2,
            "refuel_pressure": 0.4,
            "print_pulse_width": 1400,
            "refuel_pulse_width": 3000,
        }
        self._printing_profiles = [
            {
                "id": "water_droplet",
                "name": "Water - droplet",
                "mode": "droplet",
                "print_pressure": 0.6,
                "refuel_pressure": 0.3,
                "print_pulse_width": 1300,
                "refuel_pulse_width": 3000,
            },
            {
                "id": "water_stream",
                "name": "Water - stream",
                "mode": "stream",
                "print_pressure": 0.8,
                "refuel_pressure": 0.8,
                "print_pulse_width": 2500,
                "refuel_pulse_width": 6000,
            },
        ]
        self.printing_controls_section = QtWidgets.QWidget()
        printing_layout = QtWidgets.QVBoxLayout(self.printing_controls_section)
        self.printing_controls_toggle = QtWidgets.QToolButton()
        self.printing_controls_toggle.setText("Printing Controls")
        self.printing_controls_toggle.setCheckable(True)
        self.printing_controls_toggle.setChecked(True)
        self.printing_controls_content = QtWidgets.QWidget()
        printing_grid = QtWidgets.QGridLayout(self.printing_controls_content)
        self.print_profile_combo = QtWidgets.QComboBox()
        self.print_profile_apply_button = QtWidgets.QPushButton("Apply")
        self.current_print_pressure_value = QtWidgets.QLabel("1.20 psi")
        self.current_refuel_pressure_value = QtWidgets.QLabel("0.40 psi")
        self.target_print_pressure_spinbox = QtWidgets.QDoubleSpinBox()
        self.target_refuel_pressure_spinbox = QtWidgets.QDoubleSpinBox()
        self.print_pulse_width_spinbox = QtWidgets.QSpinBox()
        self.refuel_pulse_width_spinbox = QtWidgets.QSpinBox()
        for spinbox in (
            self.target_print_pressure_spinbox,
            self.target_refuel_pressure_spinbox,
        ):
            spinbox.setRange(0.1, 5.0)
            spinbox.setDecimals(2)
        for spinbox in (
            self.print_pulse_width_spinbox,
            self.refuel_pulse_width_spinbox,
        ):
            spinbox.setRange(0, 10000)
        self.target_print_pressure_spinbox.setValue(1.2)
        self.target_refuel_pressure_spinbox.setValue(0.4)
        self.print_pulse_width_spinbox.setValue(1400)
        self.refuel_pulse_width_spinbox.setValue(3000)
        printing_grid.addWidget(self.print_profile_combo, 0, 0, 1, 2)
        printing_grid.addWidget(self.print_profile_apply_button, 0, 2)
        printing_grid.addWidget(self.current_print_pressure_value, 1, 0)
        printing_grid.addWidget(self.target_print_pressure_spinbox, 1, 1)
        printing_grid.addWidget(self.current_refuel_pressure_value, 2, 0)
        printing_grid.addWidget(self.target_refuel_pressure_spinbox, 2, 1)
        printing_grid.addWidget(self.print_pulse_width_spinbox, 3, 1)
        printing_grid.addWidget(self.refuel_pulse_width_spinbox, 4, 1)
        printing_layout.addWidget(self.printing_controls_toggle)
        printing_layout.addWidget(self.printing_controls_content)
        self.printing_controls_toggle.toggled.connect(
            self.printing_controls_content.setVisible
        )
        layout.addWidget(self.printing_controls_section)

        self.live_pressure_section = QtWidgets.QWidget()
        live_layout = QtWidgets.QVBoxLayout(self.live_pressure_section)
        self.live_pressure_toggle = QtWidgets.QToolButton()
        self.live_pressure_toggle.setText("Live Pressure")
        self.live_pressure_toggle.setCheckable(True)
        self.live_pressure_toggle.setChecked(True)
        self.live_pressure_chart = QtCharts.QChart()
        self.live_print_pressure_series = QtCharts.QLineSeries()
        self.live_refuel_pressure_series = QtCharts.QLineSeries()
        self.live_target_print_pressure_series = QtCharts.QLineSeries()
        self.live_target_refuel_pressure_series = QtCharts.QLineSeries()
        for series, name, values in (
            (self.live_print_pressure_series, "Print", [1.1, 1.2]),
            (self.live_refuel_pressure_series, "Refuel", [0.3, 0.4]),
            (self.live_target_print_pressure_series, "Print target", [1.2, 1.2]),
            (self.live_target_refuel_pressure_series, "Refuel target", [0.4, 0.4]),
        ):
            series.setName(name)
            for index, value in enumerate(values):
                series.append(float(index), float(value))
            self.live_pressure_chart.addSeries(series)
        self.live_pressure_axis_x = QtCharts.QValueAxis()
        self.live_pressure_axis_x.setRange(0.0, 1.0)
        self.live_pressure_axis_y = QtCharts.QValueAxis()
        self.live_pressure_axis_y.setRange(0.0, 1.4)
        self.live_pressure_chart.addAxis(self.live_pressure_axis_x, QtCore.Qt.AlignBottom)
        self.live_pressure_chart.addAxis(self.live_pressure_axis_y, QtCore.Qt.AlignLeft)
        for series in (
            self.live_print_pressure_series,
            self.live_refuel_pressure_series,
            self.live_target_print_pressure_series,
            self.live_target_refuel_pressure_series,
        ):
            series.attachAxis(self.live_pressure_axis_x)
            series.attachAxis(self.live_pressure_axis_y)
        apply_pressure_plot_style(
            self.live_pressure_chart,
            (self.live_pressure_axis_x, self.live_pressure_axis_y),
            colors={
                "light_blue": "#275fb8",
                "white": "#ffffff",
                "light_gray": "#c4c4c4",
                "mid_gray": "#6e6e6e",
            },
            print_series=self.live_print_pressure_series,
            refuel_series=self.live_refuel_pressure_series,
            target_print_series=self.live_target_print_pressure_series,
            target_refuel_series=self.live_target_refuel_pressure_series,
        )
        self.live_pressure_chart_view = QtCharts.QChartView(self.live_pressure_chart)
        self.live_pressure_render_timer = QtCore.QTimer(self)
        self.live_pressure_render_timer.setSingleShot(True)
        self.live_pressure_render_timer.setInterval(100)
        live_layout.addWidget(self.live_pressure_toggle)
        live_layout.addWidget(self.live_pressure_chart_view)
        self.live_pressure_toggle.toggled.connect(
            self.live_pressure_chart_view.setVisible
        )
        layout.addWidget(self.live_pressure_section)

        def refresh_profile_button():
            profile = self.print_profile_combo.currentData()
            if not isinstance(profile, dict):
                self.print_profile_apply_button.setText("No Profiles")
                self.print_profile_apply_button.setEnabled(False)
                return
            loaded = all(
                self._printing_settings[key] == profile[key]
                for key in self._printing_settings
            )
            self.print_profile_apply_button.setText("Loaded" if loaded else "Apply")
            self.print_profile_apply_button.setEnabled(not loaded)

        def refresh_profiles():
            mode = "stream" if self.calibration_tabs.currentWidget() is self.stream_tab else "droplet"
            self.print_profile_combo.clear()
            for profile in self._printing_profiles:
                if profile["mode"] == mode:
                    self.print_profile_combo.addItem(profile["name"], dict(profile))
            refresh_profile_button()

        def commit_settings():
            self._printing_settings.update(
                print_pressure=float(self.target_print_pressure_spinbox.value()),
                refuel_pressure=float(self.target_refuel_pressure_spinbox.value()),
                print_pulse_width=int(self.print_pulse_width_spinbox.value()),
                refuel_pulse_width=int(self.refuel_pulse_width_spinbox.value()),
            )
            refresh_profile_button()

        def apply_profile():
            profile = dict(self.print_profile_combo.currentData())
            for key in self._printing_settings:
                self._printing_settings[key] = profile[key]
            self.target_print_pressure_spinbox.setValue(profile["print_pressure"])
            self.target_refuel_pressure_spinbox.setValue(profile["refuel_pressure"])
            self.print_pulse_width_spinbox.setValue(profile["print_pulse_width"])
            self.refuel_pulse_width_spinbox.setValue(profile["refuel_pulse_width"])
            refresh_profile_button()

        for spinbox in (
            self.target_print_pressure_spinbox,
            self.target_refuel_pressure_spinbox,
            self.print_pulse_width_spinbox,
            self.refuel_pulse_width_spinbox,
        ):
            spinbox.editingFinished.connect(commit_settings)
        self.print_profile_combo.currentIndexChanged.connect(refresh_profile_button)
        self.print_profile_apply_button.clicked.connect(apply_profile)
        self.calibration_tabs.currentChanged.connect(lambda _index: refresh_profiles())
        refresh_profiles()
        self.model = SimpleNamespace(
            calibration_manager=SimpleNamespace(
                _transient_characterization_candidate=None
            ),
            machine_model=SimpleNamespace(
                get_target_print_pressure=lambda: self._printing_settings["print_pressure"],
                get_target_refuel_pressure=lambda: self._printing_settings["refuel_pressure"],
                get_print_pulse_width=lambda: self._printing_settings["print_pulse_width"],
                get_refuel_pulse_width=lambda: self._printing_settings["refuel_pulse_width"],
            ),
        )
        self.controller = SimpleNamespace(
            machine=SimpleNamespace(check_if_all_completed=lambda: True)
        )
        self.calibrate_all_button.clicked.connect(lambda: self._mark_generated(row))
        self.calibrate_all_stream_button.clicked.connect(lambda: self._mark_generated(row))
        self.bridge_status_label = QtWidgets.QLabel("Preview ready")
        self.bridge_table = QtWidgets.QTableWidget(1, 7)
        self.bridge_table.setHorizontalHeaderLabels(
            [
                "Target",
                "Achievable",
                "Error (%)",
                "Drops",
                "Δ/drop",
                "Printed nL (new)",
                "Δ printed nL",
            ]
        )
        for column, text in enumerate(
            ("23.00", "23.00", "0.00%", "1", "2.3 mM/drop", "9.00 nL")
        ):
            self.bridge_table.setItem(
                0, column, QtWidgets.QTableWidgetItem(text)
            )
        self.bridge_apply_btn = QtWidgets.QPushButton("Apply selected calibration to design")
        self.bridge_apply_btn.setEnabled(True)
        self._bridge_apply_button_state = "available"
        self.load_selected_button = QtWidgets.QPushButton("Load selected")
        self.recheck_selected_button = QtWidgets.QPushButton("Recheck")
        self.bridge_apply_btn.clicked.connect(
            lambda: QtWidgets.QMessageBox.information(self, "Applied", "Applied")
        )
        layout.addWidget(self.bridge_status_label)
        layout.addWidget(self.bridge_table)
        layout.addWidget(self.bridge_apply_btn)
        self._bridge_preview_payload = {"new_droplet_nL": row["mean_nL"]}

    def _mark_generated(self, row):
        self.model.calibration_manager._transient_characterization_candidate = {
            "candidate": SimpleNamespace(
                result_fingerprint=row["synthetic_result_fingerprint"]
            )
        }

    def _selected_summary_row(self):
        selected = self.summary_table.selectionModel().selectedRows()
        if not selected:
            return None, None
        proxy_index = selected[0]
        source_index = self.summary_table_proxy_model.mapToSource(proxy_index)
        return proxy_index.row(), self.summary_table_model.raw_row_at(source_index.row())


def _row():
    request = CalibrationGenerationRequestV1(
        seed=2,
        profile_id="nominal_droplet",
        virtual_run_id="driver-run",
        printer_head_id="head-1",
        stock_id="stock-1",
        factor_name="Factor A",
        option_name=None,
        is_fill=False,
        requested_mode="droplet",
        nominal_volume_nL=10.0,
        volume_variation_fraction=0.05,
        pressure_bounds_psi=(1.0, 1.0),
        pulse_width_bounds_us=(1400, 1400),
    )
    row = SyntheticCalibrationProvider().generate(request).to_application_summary_row()
    row.update({"phase_label": "Synthetic", "source_filter_key": "synthetic"})
    return row


def test_calibration_dialog_driver_uses_visible_qt_controls(qapp):
    row = _row()
    dialog = _Dialog(row)
    dialog.show()
    qapp.processEvents()
    driver = CalibrationDialogDriver(qapp, dialog)

    presentation = driver.inspect_presentation()
    generated = driver.generate_from_tab("droplet")
    selected = driver.select_result(row["synthetic_result_fingerprint"])
    preview = driver.inspect_preview()
    driver.apply_selected()
    driver.close()

    assert presentation["banner_visible"] is True
    assert presentation["mode_visible"] is True
    assert presentation["row_count"] == 1
    assert generated["synthetic_result_fingerprint"] == row[
        "synthetic_result_fingerprint"
    ]
    assert selected["synthetic"] is True
    assert preview["apply_enabled"] is True
    assert preview["apply_state"] == "available"
    assert preview["apply_tooltip"] == ""
    assert preview["load_selected_enabled"] is True
    assert preview["recheck_enabled"] is True
    assert preview["calibrate_all_enabled"] is True
    assert preview["payload"]["new_droplet_nL"] == row["mean_nL"]
    assert preview["visible_table"] == {
        "headers": [
            "Target", "Achievable", "Error (%)", "Drops", "Δ/drop",
            "Printed nL (new)", "Δ printed nL",
        ],
        "rows": [[
            "23.00", "23.00", "0.00%", "1", "2.3 mM/drop",
            "9.00 nL", None,
        ]],
        "row_count": 1,
        "column_count": 7,
    }


def test_calibration_dialog_driver_operates_printing_controls(qapp):
    dialog = _Dialog(_row())
    dialog.show()
    qapp.processEvents()
    driver = CalibrationDialogDriver(qapp, dialog)

    initial = driver.inspect_printing_controls("droplet")
    assert initial["profile_ids"] == ["water_droplet"]
    direct = driver.set_printing_controls(
        "droplet",
        print_pressure_psi=0.72,
        refuel_pressure_psi=0.42,
        print_pulse_width_us=1450,
        refuel_pulse_width_us=3250,
    )
    assert direct["target_print_pressure_psi"] == 0.72
    assert direct["target_refuel_pressure_psi"] == 0.42
    assert direct["print_pulse_width_us"] == 1450
    assert direct["refuel_pulse_width_us"] == 3250

    droplet = driver.apply_print_profile_from_panel("droplet", "water_droplet")
    assert droplet["profile_button_text"] == "Loaded"
    assert droplet["print_pulse_width_us"] == 1300
    stream = driver.apply_print_profile_from_panel("stream", "water_stream")
    assert stream["profile_ids"] == ["water_stream"]
    assert stream["refuel_pulse_width_us"] == 6000

    with pytest.raises(RuntimeError, match="unavailable"):
        driver.apply_print_profile_from_panel("droplet", "water_stream")
    dialog.close()


def test_calibration_dialog_driver_inspects_live_pressure_plot(qapp):
    dialog = _Dialog(_row())
    dialog.show()
    qapp.processEvents()
    driver = CalibrationDialogDriver(qapp, dialog)

    evidence = driver.inspect_live_pressure_plot()

    assert evidence["section_visible"] is True
    assert evidence["expanded"] is True
    assert evidence["timer_active"] is False
    assert evidence["series_names"] == [
        "Print",
        "Refuel",
        "Print target",
        "Refuel target",
    ]
    assert evidence["series"]["print"]["name"] == "Print"
    assert evidence["series"]["print"]["count"] == 2
    assert evidence["series"]["print"]["latest_value"] == 1.2
    assert evidence["series"]["print"]["color"] == "#275fb8"
    assert evidence["series"]["print"]["opacity"] == pytest.approx(1.0)
    assert evidence["series"]["print"]["line_width"] == pytest.approx(1.25)
    assert evidence["series"]["print"]["line_style"] == "solid"
    assert evidence["series"]["target_print"]["color"] == "#275fb8"
    assert evidence["series"]["target_print"]["line_style"] == "dash"
    assert evidence["series"]["refuel"]["color"] == "#ffffff"
    assert evidence["series"]["target_refuel"]["color"] == "#ffffff"
    assert evidence["animation"] == "none"
    assert evidence["legend_entries"] == ["Print", "Refuel"]
    assert evidence["target_print_pressure_psi"] == 1.2
    assert evidence["target_refuel_pressure_psi"] == 0.4
    assert evidence["axis_x"] == {"minimum": 0.0, "maximum": 1.0}
    assert evidence["axis_y"] == {"minimum": 0.0, "maximum": 1.4}
    dialog.close()


def test_calibration_dialog_driver_rejects_incomplete_live_pressure_plot(qapp):
    dialog = _Dialog(_row())
    dialog.live_pressure_axis_y = None
    driver = CalibrationDialogDriver(qapp, dialog)

    with pytest.raises(RuntimeError, match="live pressure plot is incomplete"):
        driver.inspect_live_pressure_plot()


def test_calibration_dialog_driver_handles_mode_switch_and_refuel_prompt(qapp):
    row = _row()
    dialog = _Dialog(row)
    dialog.bridge_apply_btn.clicked.disconnect()
    choices = []

    def apply_stream():
        mode = QtWidgets.QMessageBox.question(
            dialog,
            "Apply calibration as mode switch?",
            "Switch mode?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        choices.append(mode)
        if mode == QtWidgets.QMessageBox.Yes:
            refuel = QtWidgets.QMessageBox.question(
                dialog,
                "Manual Refuel Check Required",
                "Run now?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            )
            choices.append(refuel)

    dialog.bridge_apply_btn.clicked.connect(apply_stream)
    dialog.show()
    qapp.processEvents()
    driver = CalibrationDialogDriver(qapp, dialog)

    handled = driver.apply_selected(
        expected_title=None,
        mode_switch_choice="yes",
        manual_refuel_choice="no",
    )
    driver.close()

    assert handled == [
        "Apply calibration as mode switch?",
        "Manual Refuel Check Required",
    ]
    assert choices == [QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No]


def test_calibration_dialog_driver_retains_expected_apply_failure(qapp):
    row = _row()
    dialog = _Dialog(row)
    dialog.bridge_apply_btn.clicked.disconnect()

    def reject_stream():
        choice = QtWidgets.QMessageBox.question(
            dialog,
            "Apply calibration as mode switch?",
            "Switch mode?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if choice == QtWidgets.QMessageBox.Yes:
            QtWidgets.QMessageBox.critical(
                dialog,
                "Apply failed",
                "Calibration would require a fill stock that is absent.",
            )

    dialog.bridge_apply_btn.clicked.connect(reject_stream)
    dialog.show()
    qapp.processEvents()
    driver = CalibrationDialogDriver(qapp, dialog)
    captured = []

    evidence = driver.apply_expected_failure(
        expected_title="Apply failed",
        expected_message_fragment="would require a fill stock that is absent",
        mode_switch_choice="yes",
        capture_modal=lambda value: captured.append(value),
    )
    driver.close()

    assert evidence["handled_dialogs"] == [
        "Apply calibration as mode switch?",
        "Apply failed",
    ]
    assert evidence["failure"]["icon"] == "Critical"
    assert evidence["failure"]["selected_button"] == "Ok"
    assert captured == [evidence["failure"]]
