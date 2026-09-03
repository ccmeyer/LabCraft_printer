import json
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QDoubleSpinBox, QPushButton

import View
from ExecutionPlan import ExecutionPlanState, canonical_sha256
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
        writable=True,
        warning=None,
    ):
        self._rows = [self._with_stock_id(row) for row in rows]
        self.include_fill_calls = []
        self.snapshot_calls = []
        self.save_calls = 0
        self.experiment_file_path = experiment_file_path
        self.save_error = save_error
        self.writable = writable
        self.warning = warning
        self.stock_prep_state = stock_prep_state or self._default_stock_prep_state()

    @staticmethod
    def _with_stock_id(row):
        normalized = dict(row)
        name = normalized.get("option_name") or normalized.get("factor_name") or ""
        normalized["stock_id"] = (
            f"{name}_{float(normalized.get('stock_concentration', 0.0)):.2f}_"
            f"{normalized.get('units', '')}"
        )
        return normalized

    @staticmethod
    def _default_stock_prep_state():
        return {
            "schema_name": "labcraft.stock_prep",
            "schema_version": 1,
            "plan_id": None,
            "plan_revision": 1,
            "defaults": {
                "dead_volume_extra_uL": 20.0,
                "calibration_extra_uL": 10.0,
            },
            "entries": {},
        }

    def get_stock_table_rows(self, include_fill=True):
        self.include_fill_calls.append(include_fill)
        return list(self._rows)

    def get_stock_prep_rows(self):
        self.include_fill_calls.append(False)
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
        stock_id = row.get("stock_id") or self._with_stock_id(row)["stock_id"]
        entries = self.stock_prep_state.get("entries", {})
        entry = entries.get(stock_id) or entries.get(self.build_stock_prep_key(row))
        return None if entry is None else dict(entry)

    def can_persist_stock_prep_worksheet(self):
        return self.writable

    def get_stock_prep_worksheet_warning(self):
        return self.warning

    def save_stock_prep_worksheet(self, rows, *, dead_volume_extra_uL, calibration_extra_uL):
        self.save_calls += 1
        if self.save_error is not None:
            raise self.save_error
        entries = {}
        normalized_rows = []
        for row in rows:
            normalized = {
                "stock_id": str(row.get("stock_id", "") or ""),
                "factor_name": str(row.get("factor_name", "") or ""),
                "option_name": str(row.get("option_name", "") or ""),
                "stock_concentration": float(row.get("stock_concentration", 0.0) or 0.0),
                "units": str(row.get("units", "") or ""),
                "prep_volume_uL": float(row.get("prep_volume_uL", 0.0) or 0.0),
                "source_concentration": float(row.get("source_concentration", 0.0) or 0.0),
            }
            normalized_rows.append(normalized)
            entries[normalized["stock_id"]] = {
                "prep_volume_uL": normalized["prep_volume_uL"],
                "source_concentration": normalized["source_concentration"],
            }

        self.snapshot_calls.append(
            {
                "rows": normalized_rows,
                "dead_volume_extra_uL": float(dead_volume_extra_uL),
                "calibration_extra_uL": float(calibration_extra_uL),
            }
        )
        self.stock_prep_state = {
            "schema_name": "labcraft.stock_prep",
            "schema_version": 1,
            "plan_id": None,
            "plan_revision": 1,
            "defaults": {
                "dead_volume_extra_uL": float(dead_volume_extra_uL),
                "calibration_extra_uL": float(calibration_extra_uL),
            },
            "entries": entries,
        }


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
        "prep_volume_uL": float(prep_volume_uL),
        "source_concentration": float(source_concentration),
    }


def _make_dialog(
    rows,
    *,
    stock_prep_state=None,
    experiment_file_path="Experiments\\demo\\experiment_design.json",
    save_error=None,
    writable=True,
    warning=None,
):
    model = _StockRowsModel(
        rows,
        stock_prep_state=stock_prep_state,
        experiment_file_path=experiment_file_path,
        save_error=save_error,
        writable=writable,
        warning=warning,
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


def _plan_fixture(*, state=ExecutionPlanState.PREPARED, plan_id=None, revision=1):
    stock_a = SimpleNamespace(
        stock_id="BufferA_400.00_mM",
        factor_name="BufferA",
        option_name=None,
        reagent_name="BufferA",
        concentration=400.0,
        units="mM",
        effective_volume_nL=50.0,
    )
    stock_b = SimpleNamespace(
        stock_id="Choice1_100.00_mM",
        factor_name="GroupA",
        option_name="Choice1",
        reagent_name="Choice1",
        concentration=100.0,
        units="mM",
        effective_volume_nL=40.0,
    )
    fill = SimpleNamespace(
        stock_id="Water_1.00_--",
        factor_name="Water",
        option_name=None,
        reagent_name="Water",
        concentration=1.0,
        units="--",
        effective_volume_nL=50.0,
    )
    wells = (
        SimpleNamespace(
            dispenses=(
                SimpleNamespace(stock_id=stock_a.stock_id, target_dispenses=10),
                SimpleNamespace(stock_id=stock_b.stock_id, target_dispenses=5),
                SimpleNamespace(stock_id=fill.stock_id, target_dispenses=20),
            )
        ),
        SimpleNamespace(
            dispenses=(
                SimpleNamespace(stock_id=stock_a.stock_id, target_dispenses=4),
                SimpleNamespace(stock_id=stock_b.stock_id, target_dispenses=2),
            )
        ),
    )
    return SimpleNamespace(
        plan_id=plan_id or str(uuid.uuid4()),
        plan_revision=revision,
        state=state,
        stocks=(stock_a, stock_b, fill),
        wells=wells,
    )


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


def test_stock_prep_dialog_displays_values_with_two_decimal_places(qapp):
    row = _row(factor_name="GroupA", option_name="Choice1", stock_concentration=400.126, total_volume_uL=55.556)
    dialog, _model, _main_window = _make_dialog([row])

    _prep_spin(dialog, 0).setValue(100.129)
    _source_spin(dialog, 0).setValue(2000.0)

    assert dialog.table.item(0, StockPrepDialog.COL_TARGET_CONC).text() == "400.13"
    assert dialog.table.item(0, StockPrepDialog.COL_REQUIRED_VOL).text() == "55.56"
    assert dialog.table.item(0, StockPrepDialog.COL_STOCK_TO_ADD).text() == "20.03"
    assert dialog.table.item(0, StockPrepDialog.COL_DILUENT_TO_ADD).text() == "80.1"


def test_stock_prep_dialog_hydrates_saved_defaults_and_row_values(qapp):
    row = _row(factor_name="GroupA", option_name="Choice1", stock_concentration=400.0, total_volume_uL=100.0)
    entry = _stock_prep_entry(row, prep_volume_uL=222.0, source_concentration=1500.0)
    stock_id = _StockRowsModel([row])._rows[0]["stock_id"]
    stock_prep_state = {
        "schema_name": "labcraft.stock_prep",
        "schema_version": 1,
        "plan_id": None,
        "plan_revision": 1,
        "defaults": {
            "dead_volume_extra_uL": 7.0,
            "calibration_extra_uL": 9.0,
        },
        "entries": {
            stock_id: entry,
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


def test_stock_prep_dialog_save_and_close_persists_sidecar_state(qapp):
    row = _row(factor_name="BufferA", stock_concentration=400.0, total_volume_uL=100.0)
    dialog, model, _main_window = _make_dialog([row])

    dialog.dead_volume_spin.setValue(11.0)
    dialog.calibration_extra_spin.setValue(12.0)
    _prep_spin(dialog, 0).setValue(144.0)
    _source_spin(dialog, 0).setValue(2500.0)

    dialog.close_button.click()

    stock_id = model._rows[0]["stock_id"]
    assert dialog.result() == QDialog.Accepted
    assert model.save_calls == 1
    assert model.stock_prep_state["defaults"]["dead_volume_extra_uL"] == 11.0
    assert model.stock_prep_state["defaults"]["calibration_extra_uL"] == 12.0
    assert model.stock_prep_state["entries"][stock_id]["prep_volume_uL"] == 144.0
    assert model.stock_prep_state["entries"][stock_id]["source_concentration"] == 2500.0
    assert dialog.close_button.text() == "Save and Close"


def test_stock_prep_dialog_close_event_persists_sidecar_state(qapp):
    row = _row(factor_name="BufferA", stock_concentration=400.0, total_volume_uL=100.0)
    dialog, model, _main_window = _make_dialog([row])

    _prep_spin(dialog, 0).setValue(166.0)
    _source_spin(dialog, 0).setValue(2200.0)
    event = QCloseEvent()

    dialog.closeEvent(event)

    stock_id = model._rows[0]["stock_id"]
    assert event.isAccepted() is True
    assert model.save_calls == 1
    assert model.stock_prep_state["entries"][stock_id]["prep_volume_uL"] == 166.0
    assert model.stock_prep_state["entries"][stock_id]["source_concentration"] == 2200.0


def test_stock_prep_dialog_escape_persists_and_closes(qapp):
    dialog, model, _main_window = _make_dialog([_row()])
    _prep_spin(dialog, 0).setValue(155.0)
    _source_spin(dialog, 0).setValue(2100.0)
    dialog.show()
    qapp.processEvents()

    QTest.keyClick(dialog, Qt.Key_Escape)
    qapp.processEvents()

    assert dialog.result() == QDialog.Rejected
    assert dialog.isVisible() is False
    assert model.save_calls == 1


def test_stock_prep_dialog_in_memory_persist_when_no_experiment_file_path(qapp):
    row = _row(factor_name="BufferA", stock_concentration=400.0, total_volume_uL=100.0)
    dialog, model, _main_window = _make_dialog([row], experiment_file_path=None)

    _prep_spin(dialog, 0).setValue(141.0)
    _source_spin(dialog, 0).setValue(1800.0)
    dialog.accept()

    stock_id = model._rows[0]["stock_id"]
    assert model.save_calls == 1
    assert model.stock_prep_state["entries"][stock_id]["prep_volume_uL"] == 141.0
    assert model.stock_prep_state["entries"][stock_id]["source_concentration"] == 1800.0


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

    assert list(model.stock_prep_state["entries"].keys()) == [model._rows[0]["stock_id"]]
    assert len(model.snapshot_calls[-1]["rows"]) == 1


def test_stock_prep_dialog_save_failure_can_close_without_saving(qapp, monkeypatch):
    row = _row(factor_name="BufferA", stock_concentration=400.0, total_volume_uL=100.0)
    dialog, model, main_window = _make_dialog([row], save_error=RuntimeError("disk full"))

    _prep_spin(dialog, 0).setValue(151.0)
    _source_spin(dialog, 0).setValue(1900.0)
    prompts = []
    monkeypatch.setattr(
        dialog,
        "_prompt_stock_prep_save_failure",
        lambda exc: prompts.append(str(exc)) or False,
    )
    dialog.accept()

    assert model.save_calls == 1
    assert dialog.result() == QDialog.Accepted
    assert prompts == ["disk full"]
    assert model.stock_prep_state["entries"] == {}
    main_window.popup_message.assert_not_called()


def test_stock_prep_dialog_save_failure_retry_then_succeeds(qapp, monkeypatch):
    row = _row(factor_name="BufferA", stock_concentration=400.0, total_volume_uL=100.0)
    dialog, model, _main_window = _make_dialog(
        [row],
        save_error=RuntimeError("temporary failure"),
    )
    prompts = []

    def retry_once(exc):
        prompts.append(str(exc))
        model.save_error = None
        return True

    monkeypatch.setattr(dialog, "_prompt_stock_prep_save_failure", retry_once)
    dialog.accept()

    assert model.save_calls == 2
    assert prompts == ["temporary failure"]
    assert dialog.result() == QDialog.Accepted


def test_stock_prep_dialog_read_only_calculator_never_persists(qapp):
    dialog, model, _main_window = _make_dialog([_row()], writable=False)
    _prep_spin(dialog, 0).setValue(145.0)
    _source_spin(dialog, 0).setValue(2000.0)

    dialog.reject()

    assert dialog.result() == QDialog.Rejected
    assert model.save_calls == 0
    assert dialog.close_button.text() == "Close"
    assert StockPrepDialog.READ_ONLY_TEXT in dialog.worksheet_notice_label.text()


def test_experiment_model_stock_prep_sidecar_round_trip_preserves_design(tmp_path):
    row = _row(factor_name="BufferA", option_name="Choice1", stock_concentration=400.0, units="mM")
    em = _make_real_model()
    em._stock_rows_cache = [dict(row)]
    em.experiment_dir_path = str(tmp_path)
    em.update_all_paths()
    design_before = em.to_dict()
    design_hash_before = canonical_sha256(design_before)
    em.unsaved_changes = False

    em.save_stock_prep_worksheet(
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

    saved = json.loads((tmp_path / "stock_prep.json").read_text(encoding="utf-8"))
    assert saved["schema_name"] == "labcraft.stock_prep"
    assert saved["schema_version"] == 1
    assert saved["plan_id"] is None
    assert saved["plan_revision"] == 1
    assert canonical_sha256(em.to_dict()) == design_hash_before
    assert em.to_dict() == design_before
    assert em.unsaved_changes is False

    restored = _make_real_model()
    restored._stock_rows_cache = [dict(row)]
    restored.experiment_dir_path = str(tmp_path)
    restored.update_all_paths()

    assert restored.get_stock_prep_defaults()["dead_volume_extra_uL"] == 5.0
    assert restored.get_stock_prep_defaults()["calibration_extra_uL"] == 6.0
    entry = restored.get_stock_prep_entry(row)
    assert entry is not None
    assert entry["prep_volume_uL"] == 130.0
    assert entry["source_concentration"] == 2000.0


def test_experiment_model_legacy_embedded_stock_prep_is_read_only_fallback():
    row = _row(factor_name="BufferA", option_name="Choice1", stock_concentration=400.0, units="mM")
    key = _make_real_model().build_stock_prep_key(row)
    payload = _make_real_model().to_dict()
    payload["stock_prep"] = {
        "version": 1,
        "defaults": {
            "dead_volume_extra_uL": 5.0,
            "calibration_extra_uL": 6.0,
        },
        "entries": {
            key: {
                **_stock_prep_entry(
                    row,
                    prep_volume_uL=130.0,
                    source_concentration=2000.0,
                ),
                "factor_name": row["factor_name"],
                "option_name": row["option_name"],
                "stock_concentration": row["stock_concentration"],
                "units": row["units"],
            }
        },
    }
    restored = _make_real_model()
    restored.from_dict(payload)
    restored._stock_rows_cache = [dict(row)]

    assert restored.get_stock_prep_defaults()["dead_volume_extra_uL"] == 5.0
    assert restored.get_stock_prep_entry(row)["prep_volume_uL"] == 130.0
    assert restored.get_stock_prep_worksheet_source() == "legacy_embedded"
    assert restored.to_dict()["stock_prep"] == payload["stock_prep"]


def test_experiment_model_build_stock_prep_key_is_stable_for_equivalent_rows():
    em = _make_real_model()
    row_a = _row(factor_name="BufferA", option_name="Choice1", stock_concentration=400.0, units="mM")
    row_b = _row(factor_name="BufferA", option_name="Choice1", stock_concentration=400.0000000000, units="mM")

    assert em.build_stock_prep_key(row_a) == em.build_stock_prep_key(row_b)


def test_experiment_model_set_stock_prep_snapshot_prunes_stale_entries():
    em = _make_real_model()
    row_a = _row(factor_name="BufferA", stock_concentration=400.0, units="mM")
    row_b = _row(factor_name="BufferB", stock_concentration=200.0, units="mM")
    em._stock_rows_cache = [dict(row_a), dict(row_b)]
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


def test_stock_prep_rows_use_current_plan_totals_and_exclude_fill():
    em = _make_real_model()
    plan = _plan_fixture(state=ExecutionPlanState.ACTIVE, revision=3)
    em._execution_plan_snapshot = plan
    em._execution_plan_source = "new_finalization"

    rows = em.get_stock_prep_rows()

    assert [row["stock_id"] for row in rows] == [
        "BufferA_400.00_mM",
        "Choice1_100.00_mM",
    ]
    assert rows[0]["total_droplets"] == 14
    assert rows[0]["total_volume_uL"] == 0.7
    assert rows[1]["total_droplets"] == 7
    assert rows[1]["total_volume_uL"] == 0.28


def test_real_two_stock_plan_renders_and_persists_rows_by_exact_stock_id(
    qapp,
    tmp_path,
):
    em = _make_real_model()
    em.experiment_dir_path = str(tmp_path)
    em.update_all_paths()
    em.set_metadata(
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        replicates=1,
        target_reaction_volume_nL=240.0,
        final_reaction_volume_nL=5000.0,
        printed_volume_tolerance_nL=0.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
        allow_two_stock_solutions=True,
        allow_avoidable_target_grouping=False,
    )
    em.add_additive(
        "Signal",
        [0.5, 1.0, 5.0, 20.0],
        "mM",
        10.0,
        max_stock_conc=2000.0,
    )
    result = em.optimize_stock_solutions(
        quantum=0.1,
        max_refine=20,
        two_max_refine=20,
        allow_two=True,
    )
    assert result["best"] is True
    assert result["two_stock_keys"] == [("Signal", None)]
    em.generate_experiment()
    em.save_experiment()

    rows = em.get_stock_prep_rows()
    stock_ids = [row["stock_id"] for row in rows]
    assert len(rows) == 2
    assert len(set(stock_ids)) == 2

    main_window = SimpleNamespace(color_dict={}, popup_message=Mock())
    dialog = StockPrepDialog(em, main_window)
    assert dialog.table.rowCount() == 2
    assert [
        dialog.table.item(index, StockPrepDialog.COL_REAGENT).text()
        for index in range(2)
    ] == ["Signal", "Signal"]
    assert len(
        {
            dialog.table.item(
                index,
                StockPrepDialog.COL_TARGET_CONC,
            ).text()
            for index in range(2)
        }
    ) == 2

    for index, (prep_volume, source_concentration) in enumerate(
        ((111.0, 1500.0), (222.0, 2500.0))
    ):
        _prep_spin(dialog, index).setValue(prep_volume)
        _source_spin(dialog, index).setValue(source_concentration)
    assert dialog._persist_stock_prep_state() is True

    persisted = em.load_stock_prep_worksheet()
    assert list(persisted["entries"]) == stock_ids
    assert persisted["entries"][stock_ids[0]]["prep_volume_uL"] == 111.0
    assert persisted["entries"][stock_ids[1]]["prep_volume_uL"] == 222.0


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (ExecutionPlanState.PREPARED, True),
        (ExecutionPlanState.ACTIVE, True),
        (ExecutionPlanState.COMPLETED, False),
        (ExecutionPlanState.ABORTED, False),
    ],
)
def test_stock_prep_persistence_follows_plan_lifecycle(state, expected):
    em = _make_real_model()
    em._execution_plan_snapshot = _plan_fixture(state=state)
    em._execution_plan_source = "new_finalization"

    assert em.can_persist_stock_prep_worksheet() is expected


def test_stock_prep_sidecar_rebinds_only_exact_stock_ids(tmp_path):
    em = _make_real_model()
    plan = _plan_fixture(state=ExecutionPlanState.PREPARED, revision=2)
    em._execution_plan_snapshot = plan
    em._execution_plan_source = "new_finalization"
    em.experiment_dir_path = str(tmp_path)
    em.update_all_paths()
    prior = {
        "schema_name": "labcraft.stock_prep",
        "schema_version": 1,
        "plan_id": str(uuid.uuid4()),
        "plan_revision": 1,
        "defaults": {
            "dead_volume_extra_uL": 7.0,
            "calibration_extra_uL": 9.0,
        },
        "entries": {
            "BufferA_400.00_mM": {
                "prep_volume_uL": 222.0,
                "source_concentration": 1500.0,
            },
            "Removed_50.00_mM": {
                "prep_volume_uL": 100.0,
                "source_concentration": 1000.0,
            },
        },
    }
    (tmp_path / "stock_prep.json").write_text(json.dumps(prior), encoding="utf-8")

    rebound = em.load_stock_prep_worksheet()

    assert rebound["plan_id"] == plan.plan_id
    assert rebound["plan_revision"] == 2
    assert list(rebound["entries"]) == ["BufferA_400.00_mM"]
    assert "exact stock ID" in em.get_stock_prep_worksheet_warning()


def test_missing_stock_prep_sidecar_uses_defaults_without_creating_file(tmp_path):
    em = _make_real_model()
    em._stock_rows_cache = [dict(_row())]
    em.experiment_dir_path = str(tmp_path)
    em.update_all_paths()

    state = em.load_stock_prep_worksheet()

    assert state["plan_id"] is None
    assert state["plan_revision"] == 1
    assert state["entries"] == {}
    assert em.get_stock_prep_worksheet_source() == "defaults"
    assert not (tmp_path / "stock_prep.json").exists()


def test_stock_prep_sidecar_ignores_individually_malformed_entries(tmp_path):
    valid_row = _row(factor_name="Valid")
    invalid_row = _row(factor_name="Invalid")
    em = _make_real_model()
    em._stock_rows_cache = [dict(valid_row), dict(invalid_row)]
    em.experiment_dir_path = str(tmp_path)
    em.update_all_paths()
    valid_id = em.build_stock_prep_stock_id(valid_row)
    invalid_id = em.build_stock_prep_stock_id(invalid_row)
    payload = {
        "schema_name": "labcraft.stock_prep",
        "schema_version": 1,
        "plan_id": None,
        "plan_revision": 1,
        "defaults": {
            "dead_volume_extra_uL": 7.0,
            "calibration_extra_uL": 9.0,
        },
        "entries": {
            valid_id: {
                "prep_volume_uL": 222.0,
                "source_concentration": 1500.0,
            },
            invalid_id: {
                "prep_volume_uL": True,
                "source_concentration": "1500",
            },
        },
    }
    (tmp_path / "stock_prep.json").write_text(json.dumps(payload), encoding="utf-8")

    state = em.load_stock_prep_worksheet()

    assert list(state["entries"]) == [valid_id]
    assert em.get_stock_prep_worksheet_warning() is None


@pytest.mark.parametrize(
    "contents",
    [
        "{broken",
        json.dumps(
            {
                "schema_name": "labcraft.stock_prep",
                "schema_version": 999,
                "plan_id": None,
                "plan_revision": None,
                "defaults": {},
                "entries": {},
            }
        ),
        json.dumps(
            {
                "schema_name": "labcraft.stock_prep",
                "schema_version": 1,
                "plan_id": "not-a-uuid",
                "plan_revision": 1,
                "defaults": {},
                "entries": {},
            }
        ),
    ],
)
def test_invalid_stock_prep_sidecar_falls_back_without_execution_error(tmp_path, contents):
    em = _make_real_model()
    em._stock_rows_cache = [dict(_row())]
    em.experiment_dir_path = str(tmp_path)
    em.update_all_paths()
    (tmp_path / "stock_prep.json").write_text(contents, encoding="utf-8")

    state = em.load_stock_prep_worksheet()

    assert state["entries"] == {}
    assert state["defaults"]["dead_volume_extra_uL"] == 20.0
    assert "execution is unaffected" in em.get_stock_prep_worksheet_warning()
    assert em.get_execution_plan_sync_error() is None


def test_stock_prep_atomic_write_failure_preserves_saved_state(tmp_path, monkeypatch):
    row = _row()
    em = _make_real_model()
    em._stock_rows_cache = [dict(row)]
    em.experiment_dir_path = str(tmp_path)
    em.update_all_paths()
    em.save_stock_prep_worksheet(
        [{**row, "prep_volume_uL": 130.0, "source_concentration": 2000.0}],
        dead_volume_extra_uL=5.0,
        calibration_extra_uL=6.0,
    )
    saved_before = (tmp_path / "stock_prep.json").read_bytes()
    state_before = em.load_stock_prep_worksheet()
    monkeypatch.setattr(
        em,
        "_atomic_json_dump",
        Mock(side_effect=OSError("disk full")),
    )

    with pytest.raises(OSError, match="disk full"):
        em.save_stock_prep_worksheet(
            [{**row, "prep_volume_uL": 999.0, "source_concentration": 3000.0}],
            dead_volume_extra_uL=1.0,
            calibration_extra_uL=2.0,
        )

    assert (tmp_path / "stock_prep.json").read_bytes() == saved_before
    assert em.load_stock_prep_worksheet() == state_before


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


def test_completed_read_only_view_opens_stock_prep_calculator(monkeypatch):
    opened = []

    class _DialogStub:
        def __init__(self, experiment_model, main_window):
            opened.append((experiment_model, main_window))

        def exec(self):
            opened.append("exec")

    widget = WellPlateWidget.__new__(WellPlateWidget)
    widget.model = SimpleNamespace(
        experiment_model=object(),
        is_completed_execution_view_active=lambda: True,
    )
    widget.main_window = SimpleNamespace()
    monkeypatch.setattr(View, "StockPrepDialog", _DialogStub)

    WellPlateWidget.open_stock_prep_dialog(widget)

    assert opened == [
        (widget.model.experiment_model, widget.main_window),
        "exec",
    ]


def test_historical_load_enables_stock_prep_but_not_calibration(qapp):
    widget = WellPlateWidget.__new__(WellPlateWidget)
    widget.model = SimpleNamespace(
        is_read_only_experiment_view_active=lambda: True,
    )
    widget.stock_prep_button = QPushButton()
    widget.stock_prep_button.setEnabled(False)
    widget.calibration_button = QPushButton()
    widget.calibration_button.setEnabled(True)
    widget.start_print_array_button = None
    widget._populate_reagent_selection = Mock()
    widget.update_well_colors = Mock()

    WellPlateWidget.on_experiment_loaded(widget)

    assert widget.stock_prep_button.isEnabled() is True
    assert widget.calibration_button.isEnabled() is False


def test_stock_prep_dialog_uses_spinbox_widgets_for_editable_columns(qapp):
    dialog, _model, _main_window = _make_dialog([_row()])

    assert isinstance(_prep_spin(dialog, 0), QDoubleSpinBox)
    assert isinstance(_source_spin(dialog, 0), QDoubleSpinBox)
    assert dialog.dead_volume_spin.decimals() == 2
    assert dialog.calibration_extra_spin.decimals() == 2
    assert _prep_spin(dialog, 0).decimals() == 2
    assert _source_spin(dialog, 0).decimals() == 2
    assert _source_spin(dialog, 0).specialValueText() == "--"
