from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtWidgets import QDialog, QDoubleSpinBox

import View
from View import StockPrepDialog, WellPlateWidget


class _StockRowsModel:
    def __init__(self, rows):
        self._rows = list(rows)
        self.include_fill_calls = []

    def get_stock_table_rows(self, include_fill=True):
        self.include_fill_calls.append(include_fill)
        return list(self._rows)


def _row(
    *,
    factor_name="BufferA",
    option_name="",
    stock_concentration=400.0,
    units="mM",
    total_volume_uL=100.0,
):
    return {
        "factor_name": factor_name,
        "option_name": option_name,
        "stock_concentration": stock_concentration,
        "units": units,
        "total_volume_uL": total_volume_uL,
    }


def _make_dialog(rows):
    model = _StockRowsModel(rows)
    dialog = StockPrepDialog(model, SimpleNamespace(color_dict={}))
    return dialog, model


def _prep_spin(dialog, row):
    return dialog.table.cellWidget(row, StockPrepDialog.COL_PREP_VOL)


def _source_spin(dialog, row):
    return dialog.table.cellWidget(row, StockPrepDialog.COL_SOURCE_CONC)


def test_stock_prep_dialog_prepopulates_rows_and_filters_invalid_entries(qapp):
    dialog, model = _make_dialog(
        [
            _row(factor_name="GroupA", option_name="Choice1", total_volume_uL=100.0),
            _row(factor_name="ZeroVol", total_volume_uL=0.0),
            _row(factor_name="Fill", units="--", total_volume_uL=50.0),
            _row(factor_name="InfVol", total_volume_uL=float("inf")),
            _row(factor_name="MissingVol", total_volume_uL=None),
        ]
    )

    assert model.include_fill_calls == [False]
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, StockPrepDialog.COL_REAGENT).text() == "Choice1"
    assert dialog.table.item(0, StockPrepDialog.COL_REQUIRED_VOL).text() == "100"
    assert _prep_spin(dialog, 0).value() == 130.0
    assert dialog.table.item(0, StockPrepDialog.COL_STATUS).text() == "Enter source concentration"


def test_stock_prep_dialog_apply_suggested_volumes_updates_each_row_and_preserves_source(qapp):
    dialog, _model = _make_dialog(
        [
            _row(factor_name="A", total_volume_uL=100.0),
            _row(factor_name="B", total_volume_uL=55.5),
        ]
    )
    _prep_spin(dialog, 0).setValue(999.0)
    _prep_spin(dialog, 1).setValue(999.0)
    _source_spin(dialog, 0).setValue(1234.0)
    dialog.dead_volume_spin.setValue(5.0)
    dialog.calibration_extra_spin.setValue(7.0)

    dialog.apply_suggested_button.click()

    assert _prep_spin(dialog, 0).value() == 112.0
    assert _prep_spin(dialog, 1).value() == 67.5
    assert _source_spin(dialog, 0).value() == 1234.0


def test_stock_prep_dialog_example_dilution_math(qapp):
    dialog, _model = _make_dialog([_row(stock_concentration=400.0, total_volume_uL=100.0)])

    _prep_spin(dialog, 0).setValue(100.0)
    _source_spin(dialog, 0).setValue(2000.0)

    assert dialog.table.item(0, StockPrepDialog.COL_STOCK_TO_ADD).text() == "20"
    assert dialog.table.item(0, StockPrepDialog.COL_DILUENT_TO_ADD).text() == "80"
    assert dialog.table.item(0, StockPrepDialog.COL_STATUS).text() == "Ready"


def test_stock_prep_dialog_equal_source_and_target_concentrations_use_all_stock(qapp):
    dialog, _model = _make_dialog([_row(stock_concentration=400.0, total_volume_uL=100.0)])

    _prep_spin(dialog, 0).setValue(100.0)
    _source_spin(dialog, 0).setValue(400.0)

    assert dialog.table.item(0, StockPrepDialog.COL_STOCK_TO_ADD).text() == "100"
    assert dialog.table.item(0, StockPrepDialog.COL_DILUENT_TO_ADD).text() == "0"
    assert dialog.table.item(0, StockPrepDialog.COL_STATUS).text() == "Ready"


def test_stock_prep_dialog_rejects_source_below_target(qapp):
    dialog, _model = _make_dialog([_row(stock_concentration=400.0, total_volume_uL=100.0)])

    _prep_spin(dialog, 0).setValue(100.0)
    _source_spin(dialog, 0).setValue(300.0)

    assert dialog.table.item(0, StockPrepDialog.COL_STOCK_TO_ADD).text() == ""
    assert dialog.table.item(0, StockPrepDialog.COL_DILUENT_TO_ADD).text() == ""
    assert (
        dialog.table.item(0, StockPrepDialog.COL_STATUS).text()
        == "Source concentration must be >= target concentration"
    )


def test_stock_prep_dialog_zero_source_concentration_prompts_for_input(qapp):
    dialog, _model = _make_dialog([_row(stock_concentration=400.0, total_volume_uL=100.0)])

    assert dialog.table.item(0, StockPrepDialog.COL_STOCK_TO_ADD).text() == ""
    assert dialog.table.item(0, StockPrepDialog.COL_DILUENT_TO_ADD).text() == ""
    assert dialog.table.item(0, StockPrepDialog.COL_STATUS).text() == "Enter source concentration"


def test_stock_prep_dialog_zero_prep_volume_prompts_for_input(qapp):
    dialog, _model = _make_dialog([_row(stock_concentration=400.0, total_volume_uL=100.0)])

    _source_spin(dialog, 0).setValue(2000.0)
    _prep_spin(dialog, 0).setValue(0.0)

    assert dialog.table.item(0, StockPrepDialog.COL_STOCK_TO_ADD).text() == ""
    assert dialog.table.item(0, StockPrepDialog.COL_DILUENT_TO_ADD).text() == ""
    assert dialog.table.item(0, StockPrepDialog.COL_STATUS).text() == "Enter prep volume"


def test_stock_prep_dialog_shows_empty_state_when_no_valid_rows_exist(qapp):
    dialog, _model = _make_dialog(
        [
            _row(factor_name="Fill", units="--", total_volume_uL=50.0),
            _row(factor_name="Zero", total_volume_uL=0.0),
        ]
    )

    assert dialog.table.rowCount() == 0
    assert dialog.empty_state_label.text() == StockPrepDialog.EMPTY_TEXT
    assert dialog.empty_state_label.isHidden() is False


def test_open_stock_prep_dialog_launches_dialog_without_touching_controller(monkeypatch):
    opened = []

    class _DialogStub:
        def __init__(self, experiment_model, main_window):
            opened.append(("init", experiment_model, main_window))

        def exec(self):
            opened.append(("exec",))
            return QDialog.Rejected

    widget = WellPlateWidget.__new__(WellPlateWidget)
    runtime_state = {"assigned_wells": ["A1"], "progress_sentinel": 7}
    widget.model = SimpleNamespace(experiment_model=object(), runtime_state=runtime_state)
    widget.main_window = SimpleNamespace()
    widget.controller = Mock()

    monkeypatch.setattr(View, "StockPrepDialog", _DialogStub)

    WellPlateWidget.open_stock_prep_dialog(widget)

    assert opened[0][0] == "init"
    assert opened[0][1] is widget.model.experiment_model
    assert opened[0][2] is widget.main_window
    assert opened[1] == ("exec",)
    assert widget.controller.mock_calls == []
    assert widget.model.runtime_state == runtime_state


def test_stock_prep_dialog_uses_spinbox_widgets_for_editable_columns(qapp):
    dialog, _model = _make_dialog([_row()])

    assert isinstance(_prep_spin(dialog, 0), QDoubleSpinBox)
    assert isinstance(_source_spin(dialog, 0), QDoubleSpinBox)
    assert _source_spin(dialog, 0).specialValueText() == "--"
