from __future__ import annotations

from types import SimpleNamespace

from PySide6 import QtWidgets

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
        self.bridge_status_label = QtWidgets.QLabel("Preview ready")
        self.bridge_table = QtWidgets.QTableWidget(1, 1)
        self.bridge_apply_btn = QtWidgets.QPushButton("Apply selected calibration to design")
        self.bridge_apply_btn.setEnabled(True)
        self.bridge_apply_btn.clicked.connect(
            lambda: QtWidgets.QMessageBox.information(self, "Applied", "Applied")
        )
        layout.addWidget(self.bridge_status_label)
        layout.addWidget(self.bridge_table)
        layout.addWidget(self.bridge_apply_btn)
        self._bridge_preview_payload = {"new_droplet_nL": row["mean_nL"]}

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
    selected = driver.select_result(row["synthetic_result_fingerprint"])
    preview = driver.inspect_preview()
    driver.apply_selected()
    driver.close()

    assert presentation["banner_visible"] is True
    assert presentation["row_count"] == 1
    assert selected["synthetic"] is True
    assert preview["apply_enabled"] is True
    assert preview["payload"]["new_droplet_nL"] == row["mean_nL"]
