from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QDoubleSpinBox

import View
from Model import CURRENT_PROFILE, ExperimentModel
from View import StockPrepDialog, WellPlateWidget


class _StockRowsModel:
    def __init__(
        self,
        rows,
        *,
        stock_prep_state=None,
        experiment_file_path="Experiments\\demo\\experiment_design.json",
        save_error=None,
    ):
        self._rows = list(rows)
        self.include_fill_calls = []
        self.snapshot_calls = []
        self.save_calls = 0
        self.experiment_file_path = experiment_file_path
        self.save_error = save_error
        self.stock_prep_state = stock_prep_state or self._default_stock_prep_state()

    @staticmethod
    def _default_stock_prep_state():
        return {
            "version": 1,
            "defaults": {
                "dead_volume_extra_uL": 20.0,
                "calibration_extra_uL": 10.0,
            },
            "entries": {},
        }

    def get_stock_table_rows(self, include_fill=True):
        self.include_fill_calls.append(include_fill)
        return list(self._rows)

    def build_stock_prep_key(self, row):
        factor_name = str((row or {}).get("factor_name", "") or "")
        option_name = str((row or {}).get("option_name", "") or "")
        concentration = format(float((row or {}).get("stock_concentration", 0.0) or 0.0), ".12g")
        units = str((row or {}).get("units", "") or "")
        return "|".join([factor_name, option_name, concentration, units])

    def get_stock_prep_defaults(self):
        return dict(self.stock_prep_state.get("defaults", {}))

    def get_stock_prep_entry(self, row):
        entry = self.stock_prep_state.get("entries", {}).get(self.build_stock_prep_key(row))
        return None if entry is None else dict(entry)

    def set_stock_prep_snapshot(self, rows, *, dead_volume_extra_uL, calibration_extra_uL):
        entries = {}
        normalized_rows = []
        for row in rows:
            normalized = {
                "factor_name": str(row.get("factor_name", "") or ""),
                "option_name": str(row.get("option_name", "") or ""),
                "stock_concentration": float(row.get("stock_concentration", 0.0) or 0.0),
                "units": str(row.get("units", "") or ""),
                "prep_volume_uL": float(row.get("prep_volume_uL", 0.0) or 0.0),
                "source_concentration": float(row.get("source_concentration", 0.0) or 0.0),
            }
            normalized_rows.append(normalized)
            entries[self.build_stock_prep_key(normalized)] = dict(normalized)

        self.snapshot_calls.append(
            {
                "rows": normalized_rows,
                "dead_volume_extra_uL": float(dead_volume_extra_uL),
                "calibration_extra_uL": float(calibration_extra_uL),
            }
        )
        self.stock_prep_state = {
            "version": 1,
            "defaults": {
                "dead_volume_extra_uL": float(dead_volume_extra_uL),
                "calibration_extra_uL": float(calibration_extra_uL),
            },
            "entries": entries,
        }

    def save_experiment(self):
        self.save_calls += 1
        if self.save_error is not None:
            raise self.save_error


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


def _stock_prep_entry(row, *, prep_volume_uL, source_concentration):
    return {
        "factor_name": str(row.get("factor_name", "") or ""),
        "option_name": str(row.get("option_name", "") or ""),
        "stock_concentration": float(row.get("stock_concentration", 0.0) or 0.0),
        "units": str(row.get("units", "") or ""),
        "prep_volume_uL": float(prep_volume_uL),
        "source_concentration": float(source_concentration),
    }


def _make_dialog(rows, *, stock_prep_state=None, experiment_file_path="Experiments\\demo\\experiment_design.json", save_error=None):
    model = _StockRowsModel(
        rows,
        stock_prep_state=stock_prep_state,
        experiment_file_path=experiment_file_path,
        save_error=save_error,
    )
    main_window = SimpleNamespace(color_dict={}, popup_message=Mock())
    dialog = StockPrepDialog(model, main_window)
    return dialog, model, main_window


def _prep_spin(dialog, row):
    return dialog.table.cellWidget(row, StockPrepDialog.COL_PREP_VOL)


def _source_spin(dialog, row):
    return dialog.table.cellWidget(row, StockPrepDialog.COL_SOURCE_CONC)


def _make_real_model():
    return ExperimentModel(prof=CURRENT_PROFILE)


def test_stock_prep_dialog_prepopulates_rows_and_filters_invalid_entries(qapp):
    dialog, model, _main_window = _make_dialog(
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


def test_stock_prep_dialog_hydrates_saved_defaults_and_row_values(qapp):
    row = _row(factor_name="GroupA", option_name="Choice1", stock_concentration=400.0, total_volume_uL=100.0)
    entry = _stock_prep_entry(row, prep_volume_uL=222.0, source_concentration=1500.0)
    stock_prep_state = {
        "version": 1,
        "defaults": {
            "dead_volume_extra_uL": 7.0,
            "calibration_extra_uL": 9.0,
        },
        "entries": {
            _StockRowsModel([row]).build_stock_prep_key(row): entry,
        },
    }

    dialog, _model, _main_window = _make_dialog([row], stock_prep_state=stock_prep_state)

    assert dialog.dead_volume_spin.value() == 7.0
    assert dialog.calibration_extra_spin.value() == 9.0
    assert _prep_spin(dialog, 0).value() == 222.0
    assert _source_spin(dialog, 0).value() == 1500.0


def test_stock_prep_dialog_apply_suggested_volumes_updates_each_row_and_preserves_source(qapp):
    dialog, _model, _main_window = _make_dialog(
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
    dialog, _model, _main_window = _make_dialog([_row(stock_concentration=400.0, total_volume_uL=100.0)])

    _prep_spin(dialog, 0).setValue(100.0)
    _source_spin(dialog, 0).setValue(2000.0)

    assert dialog.table.item(0, StockPrepDialog.COL_STOCK_TO_ADD).text() == "20"
    assert dialog.table.item(0, StockPrepDialog.COL_DILUENT_TO_ADD).text() == "80"
    assert dialog.table.item(0, StockPrepDialog.COL_STATUS).text() == "Ready"


def test_stock_prep_dialog_equal_source_and_target_concentrations_use_all_stock(qapp):
    dialog, _model, _main_window = _make_dialog([_row(stock_concentration=400.0, total_volume_uL=100.0)])

    _prep_spin(dialog, 0).setValue(100.0)
    _source_spin(dialog, 0).setValue(400.0)

    assert dialog.table.item(0, StockPrepDialog.COL_STOCK_TO_ADD).text() == "100"
    assert dialog.table.item(0, StockPrepDialog.COL_DILUENT_TO_ADD).text() == "0"
    assert dialog.table.item(0, StockPrepDialog.COL_STATUS).text() == "Ready"


def test_stock_prep_dialog_rejects_source_below_target(qapp):
    dialog, _model, _main_window = _make_dialog([_row(stock_concentration=400.0, total_volume_uL=100.0)])

    _prep_spin(dialog, 0).setValue(100.0)
    _source_spin(dialog, 0).setValue(300.0)

    assert dialog.table.item(0, StockPrepDialog.COL_STOCK_TO_ADD).text() == ""
    assert dialog.table.item(0, StockPrepDialog.COL_DILUENT_TO_ADD).text() == ""
    assert (
        dialog.table.item(0, StockPrepDialog.COL_STATUS).text()
        == "Source concentration must be >= target concentration"
    )


def test_stock_prep_dialog_zero_source_concentration_prompts_for_input(qapp):
    dialog, _model, _main_window = _make_dialog([_row(stock_concentration=400.0, total_volume_uL=100.0)])

    assert dialog.table.item(0, StockPrepDialog.COL_STOCK_TO_ADD).text() == ""
    assert dialog.table.item(0, StockPrepDialog.COL_DILUENT_TO_ADD).text() == ""
    assert dialog.table.item(0, StockPrepDialog.COL_STATUS).text() == "Enter source concentration"


def test_stock_prep_dialog_zero_prep_volume_prompts_for_input(qapp):
    dialog, _model, _main_window = _make_dialog([_row(stock_concentration=400.0, total_volume_uL=100.0)])

    _source_spin(dialog, 0).setValue(2000.0)
    _prep_spin(dialog, 0).setValue(0.0)

    assert dialog.table.item(0, StockPrepDialog.COL_STOCK_TO_ADD).text() == ""
    assert dialog.table.item(0, StockPrepDialog.COL_DILUENT_TO_ADD).text() == ""
    assert dialog.table.item(0, StockPrepDialog.COL_STATUS).text() == "Enter prep volume"


def test_stock_prep_dialog_shows_empty_state_when_no_valid_rows_exist(qapp):
    dialog, _model, _main_window = _make_dialog(
        [
            _row(factor_name="Fill", units="--", total_volume_uL=50.0),
            _row(factor_name="Zero", total_volume_uL=0.0),
        ]
    )

    assert dialog.table.rowCount() == 0
    assert dialog.empty_state_label.text() == StockPrepDialog.EMPTY_TEXT
    assert dialog.empty_state_label.isHidden() is False


def test_stock_prep_dialog_close_button_persists_state_and_saves_experiment(qapp):
    row = _row(factor_name="BufferA", stock_concentration=400.0, total_volume_uL=100.0)
    dialog, model, _main_window = _make_dialog([row])

    dialog.dead_volume_spin.setValue(11.0)
    dialog.calibration_extra_spin.setValue(12.0)
    _prep_spin(dialog, 0).setValue(144.0)
    _source_spin(dialog, 0).setValue(2500.0)

    dialog.close_button.click()

    key = model.build_stock_prep_key(row)
    assert dialog.result() == QDialog.Accepted
    assert model.save_calls == 1
    assert model.stock_prep_state["defaults"]["dead_volume_extra_uL"] == 11.0
    assert model.stock_prep_state["defaults"]["calibration_extra_uL"] == 12.0
    assert model.stock_prep_state["entries"][key]["prep_volume_uL"] == 144.0
    assert model.stock_prep_state["entries"][key]["source_concentration"] == 2500.0


def test_stock_prep_dialog_close_event_persists_state_and_saves_experiment(qapp):
    row = _row(factor_name="BufferA", stock_concentration=400.0, total_volume_uL=100.0)
    dialog, model, _main_window = _make_dialog([row])

    _prep_spin(dialog, 0).setValue(166.0)
    _source_spin(dialog, 0).setValue(2200.0)
    event = QCloseEvent()

    dialog.closeEvent(event)

    key = model.build_stock_prep_key(row)
    assert event.isAccepted() is True
    assert model.save_calls == 1
    assert model.stock_prep_state["entries"][key]["prep_volume_uL"] == 166.0
    assert model.stock_prep_state["entries"][key]["source_concentration"] == 2200.0


def test_stock_prep_dialog_in_memory_persist_when_no_experiment_file_path(qapp):
    row = _row(factor_name="BufferA", stock_concentration=400.0, total_volume_uL=100.0)
    dialog, model, _main_window = _make_dialog([row], experiment_file_path=None)

    _prep_spin(dialog, 0).setValue(141.0)
    _source_spin(dialog, 0).setValue(1800.0)
    dialog.accept()

    key = model.build_stock_prep_key(row)
    assert model.save_calls == 0
    assert model.stock_prep_state["entries"][key]["prep_volume_uL"] == 141.0
    assert model.stock_prep_state["entries"][key]["source_concentration"] == 1800.0


def test_stock_prep_dialog_prunes_filtered_rows_before_save(qapp):
    valid_row = _row(factor_name="Valid", total_volume_uL=100.0)
    dialog, model, _main_window = _make_dialog(
        [
            valid_row,
            _row(factor_name="Fill", units="--", total_volume_uL=50.0),
            _row(factor_name="Zero", total_volume_uL=0.0),
        ]
    )

    _source_spin(dialog, 0).setValue(2200.0)
    dialog.accept()

    assert list(model.stock_prep_state["entries"].keys()) == [model.build_stock_prep_key(valid_row)]
    assert len(model.snapshot_calls[-1]["rows"]) == 1


def test_stock_prep_dialog_save_failure_shows_popup_and_keeps_dialog_open(qapp):
    row = _row(factor_name="BufferA", stock_concentration=400.0, total_volume_uL=100.0)
    dialog, model, main_window = _make_dialog([row], save_error=RuntimeError("disk full"))

    _prep_spin(dialog, 0).setValue(151.0)
    _source_spin(dialog, 0).setValue(1900.0)
    dialog.accept()

    assert model.save_calls == 1
    assert dialog.result() == 0
    main_window.popup_message.assert_called_once()
    title, message = main_window.popup_message.call_args.args
    assert title == "Save Stock Prep Failed"
    assert "disk full" in message


def test_experiment_model_stock_prep_round_trips_through_to_dict_and_from_dict():
    row = _row(factor_name="BufferA", option_name="Choice1", stock_concentration=400.0, units="mM")
    em = _make_real_model()
    em.set_stock_prep_snapshot(
        [
            {
                **row,
                "prep_volume_uL": 130.0,
                "source_concentration": 2000.0,
            }
        ],
        dead_volume_extra_uL=5.0,
        calibration_extra_uL=6.0,
    )

    payload = em.to_dict()

    restored = _make_real_model()
    restored.from_dict(payload)

    assert restored.get_stock_prep_defaults()["dead_volume_extra_uL"] == 5.0
    assert restored.get_stock_prep_defaults()["calibration_extra_uL"] == 6.0
    entry = restored.get_stock_prep_entry(row)
    assert entry is not None
    assert entry["prep_volume_uL"] == 130.0
    assert entry["source_concentration"] == 2000.0


def test_experiment_model_build_stock_prep_key_is_stable_for_equivalent_rows():
    em = _make_real_model()
    row_a = _row(factor_name="BufferA", option_name="Choice1", stock_concentration=400.0, units="mM")
    row_b = _row(factor_name="BufferA", option_name="Choice1", stock_concentration=400.0000000000, units="mM")

    assert em.build_stock_prep_key(row_a) == em.build_stock_prep_key(row_b)


def test_experiment_model_set_stock_prep_snapshot_prunes_stale_entries():
    em = _make_real_model()
    row_a = _row(factor_name="BufferA", stock_concentration=400.0, units="mM")
    row_b = _row(factor_name="BufferB", stock_concentration=200.0, units="mM")
    em.set_stock_prep_snapshot(
        [
            {**row_a, "prep_volume_uL": 111.0, "source_concentration": 2000.0},
            {**row_b, "prep_volume_uL": 222.0, "source_concentration": 1500.0},
        ],
        dead_volume_extra_uL=20.0,
        calibration_extra_uL=10.0,
    )

    em.set_stock_prep_snapshot(
        [
            {**row_b, "prep_volume_uL": 333.0, "source_concentration": 1600.0},
        ],
        dead_volume_extra_uL=8.0,
        calibration_extra_uL=9.0,
    )

    assert em.get_stock_prep_entry(row_a) is None
    entry_b = em.get_stock_prep_entry(row_b)
    assert entry_b is not None
    assert entry_b["prep_volume_uL"] == 333.0
    assert em.get_stock_prep_defaults()["dead_volume_extra_uL"] == 8.0
    assert em.get_stock_prep_defaults()["calibration_extra_uL"] == 9.0


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
    dialog, _model, _main_window = _make_dialog([_row()])

    assert isinstance(_prep_spin(dialog, 0), QDoubleSpinBox)
    assert isinstance(_source_spin(dialog, 0), QDoubleSpinBox)
    assert _source_spin(dialog, 0).specialValueText() == "--"
