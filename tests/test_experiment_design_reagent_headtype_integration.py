import json
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QLabel, QLineEdit, QTableWidget

import LocalConfig
from CalibrationMemoryStore import CalibrationMemoryStore
from Model import (
    CURRENT_PROFILE,
    EJECTION_VOLUME_HARD_MAX_NL,
    EJECTION_VOLUME_HARD_MIN_NL,
    PRINTING_MODE_DROPLET,
    ExperimentModel,
    Model,
    PrinterHead,
    StockSolution,
    printing_mode_default_ejection_volume_nl,
)
from View import ExperimentDesignDialog


class _RuntimeModelStub:
    def __init__(self, *, preview=None):
        self.preview = dict(preview or {})
        self.preview_requests = []
        self.register_calls = []

    def list_known_reagent_identities(self):
        return [
            {
                "reagent_id": "water",
                "display_name": "Water",
                "aliases": ["water"],
            }
        ]

    def list_known_printer_head_types(self):
        return [
            {
                "head_type_id": "nozzle_80um",
                "display_name": "80 um nozzle",
                "nominal_nozzle_diameter_um": 80.0,
                "default_droplet_ejection_volume_nL": 7.0,
                "default_stream_ejection_volume_nL": 35.0,
            },
            {
                "head_type_id": "nozzle_100um",
                "display_name": "100 um nozzle",
                "nominal_nozzle_diameter_um": 100.0,
                "default_droplet_ejection_volume_nL": 9.0,
                "default_stream_ejection_volume_nL": 60.0,
            },
            {
                "head_type_id": "nozzle_120um",
                "display_name": "120 um nozzle",
                "nominal_nozzle_diameter_um": 120.0,
                "default_droplet_ejection_volume_nL": 12.0,
                "default_stream_ejection_volume_nL": 80.0,
            }
        ]

    def resolve_design_reagent_identity(self, *, reagent_name=None, reagent_id=None, stock_label=None):
        text = (reagent_name or stock_label or "").strip()
        if reagent_id == "water" or text.lower() == "water":
            return {
                "reagent_id": "water",
                "display_name": "Water",
                "reagent_family": "aqueous",
                "known": True,
                "quality": {"reagent_id": "explicit" if reagent_id else "inferred"},
                "match_source": "alias",
            }
        slug = (text or "custom_reagent").strip().lower().replace(" ", "_")
        return {
            "reagent_id": slug,
            "display_name": text or slug,
            "reagent_family": None,
            "known": False,
            "quality": {"reagent_id": "inferred" if text else "unknown"},
            "match_source": "derived_from_name",
        }

    def preview_experiment_design_prior(self, **kwargs):
        self.preview_requests.append(dict(kwargs))
        return dict(self.preview)

    def register_experiment_design_reagents(self, experiment_model):
        self.register_calls.append(experiment_model)
        return ["water"]


class _SignalStub:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)
        return callback

    def disconnect(self, callback=None):
        if callback is None:
            self._callbacks.clear()
            return
        if callback in self._callbacks:
            self._callbacks.remove(callback)


class _WellPlateStub:
    excluded_wells = set()

    def get_all_plate_names(self):
        return ["shallow-384_well_plate"]

    def get_current_plate_name(self):
        return "shallow-384_well_plate"

    def get_plate_data_by_name(self, _name):
        return {"rows": 16, "columns": 24}


def _configure_local_calibration_memory(monkeypatch, tmp_path):
    template_root = tmp_path / "FreeRTOS-interface" / "CalibrationMemory"
    local_dir = tmp_path / "local"
    entities_dir = template_root / "entities"
    entities_dir.mkdir(parents=True)
    local_dir.mkdir()
    (template_root / "schema.json").write_text(
        json.dumps({"schema_family": "labcraft.calibration_memory", "schema_version": 1}, indent=2),
        encoding="utf-8",
    )
    (template_root / "config.json").write_text(
        json.dumps(
            {"schema_name": "labcraft.calibration_memory.runtime_config", "schema_version": 1, "memory_enabled": True},
            indent=2,
        ),
        encoding="utf-8",
    )
    (entities_dir / "reagents.json").write_text(
        json.dumps(
            {
                "schema_name": "labcraft.calibration_memory.reagents_registry",
                "schema_version": 1,
                "items": [{"reagent_id": "water", "display_name": "Water", "aliases": ["water"]}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (entities_dir / "printer_head_types.json").write_text(
        json.dumps(
            {
                "schema_name": "labcraft.calibration_memory.printer_head_types_registry",
                "schema_version": 1,
                "items": [{"head_type_id": "nozzle_100um", "display_name": "100 um nozzle"}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (entities_dir / "printer_heads.json").write_text(
        json.dumps(
            {"schema_name": "labcraft.calibration_memory.printer_heads_registry", "schema_version": 1, "items": []},
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(LocalConfig, "CALIBRATION_MEMORY_TEMPLATE_DIR", template_root)
    monkeypatch.setattr(LocalConfig, "LOCAL_DIR", local_dir)
    return template_root, local_dir / "CalibrationMemory"


def _bind_dialog_method(dialog, name):
    method = getattr(ExperimentDesignDialog, name)
    setattr(dialog, name, method.__get__(dialog, ExperimentDesignDialog))


def _build_dialog_stub(runtime_model):
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.runtime_model = runtime_model
    dialog.main_window = SimpleNamespace(model=runtime_model)
    dialog.model = ExperimentModel(prof=CURRENT_PROFILE)
    dialog.choice_groups = set()
    dialog.reagent_name_table = None
    dialog._reagent_field_labels = [
        "Stock / Label",
        "Reagent",
        "Group",
        "Head Type",
        "Mode",
        "Starting",
        "Targets",
        "Units",
        "Fixed Stock Conc",
        "Max Stock Conc",
        "Ejection Vol (nL)",
        "Prior",
        "Delete",
    ]
    dialog.reagent_table = QTableWidget(ExperimentDesignDialog.COL_DELETE + 1, 0)
    dialog.reagent_table.setVerticalHeaderLabels(dialog._reagent_field_labels)
    dialog._auto_timer = SimpleNamespace(start=lambda: None)
    dialog.default_droplet_volume_nL = printing_mode_default_ejection_volume_nl(PRINTING_MODE_DROPLET)
    dialog.color_dict = {"dark_red": "#8a0303"}
    dialog._test_sender = None
    dialog.sender = lambda: dialog._test_sender
    for name in (
        "_bridge_get_runtime_model",
        "_list_known_reagent_identities",
        "_list_known_printer_head_types",
        "_resolve_design_reagent_identity",
        "_find_row_for_widget",
        "_combo_current_payload",
        "_current_printing_mode_from_combo",
        "_build_printing_mode_selector",
        "_configure_ejection_volume_spinbox",
        "_build_known_reagent_selector",
        "_build_head_type_selector",
        "_default_ejection_volume_for_head_type",
        "_volumes_close",
        "_is_default_like_ejection_volume",
        "_maybe_update_ejection_volume_for_head_type_change",
        "_format_prior_availability",
        "_resolve_reagent_selection_from_row",
        "_refresh_prior_availability_for_row",
        "_refresh_all_prior_availability",
        "_on_reagent_identity_changed",
        "_on_reagent_printing_mode_changed",
        "_on_fill_printing_mode_changed",
        "_make_group_combo",
        "_parse_targets",
        "_add_reagent_row",
        "_rebuild_model_from_table",
        "_persist_design_identity_registry_entries",
        "_schedule_auto_update",
    ):
        _bind_dialog_method(dialog, name)
    dialog._combo_current_text = ExperimentDesignDialog._combo_current_text
    dialog._is_placeholder_stock_label = ExperimentDesignDialog._is_placeholder_stock_label
    return dialog


def _build_real_dialog():
    runtime_model = _RuntimeModelStub()
    runtime_model.well_plate = _WellPlateStub()
    runtime_model.rack_model = SimpleNamespace(
        gripper_updated=_SignalStub(),
        get_gripper_printer_head=lambda: None,
    )
    main_window = SimpleNamespace(
        model=runtime_model,
        color_dict={
            "dark_red": "#8a0303",
            "blue": "#1e64b4",
            "dark_blue": "#1b3a57",
            "light_blue": "#3b82f6",
        },
        profile=SimpleNamespace(name="modern"),
    )
    return ExperimentDesignDialog(ExperimentModel(prof=CURRENT_PROFILE), main_window)


def _head_type_index(combo: QComboBox, head_type_id: str) -> int:
    for idx in range(combo.count()):
        data = combo.itemData(idx)
        if isinstance(data, dict) and data.get("head_type_id") == head_type_id:
            return idx
    raise AssertionError(f"Head type {head_type_id!r} not found")


def test_experiment_designer_uses_printed_volume_label_and_2000_nl_defaults(qapp):
    dialog = _build_real_dialog()
    labels = {label.text() for label in dialog.findChildren(QLabel)}

    assert "Printed Volume (nL)" in labels
    assert "Target Reaction Volume (nL)" not in labels
    assert dialog.v_spin.value() == pytest.approx(2000.0)
    assert dialog.final_v_spin.value() == pytest.approx(2000.0)
    assert dialog.fill_dv_spin.value() == pytest.approx(
        printing_mode_default_ejection_volume_nl(PRINTING_MODE_DROPLET)
    )

    dialog.close()


def test_experiment_model_from_dict_keeps_legacy_rows_backward_compatible():
    model = ExperimentModel(prof=CURRENT_PROFILE)
    model.from_dict(
        {
            "metadata": {
                "name": "legacy",
                "fill_droplet_volume_nL": 10.0,
            },
            "factors": [
                {
                    "name": "Water stock",
                    "kind": "additive",
                    "options": [
                        {
                            "name": "Water stock",
                            "targets": [0.0, 1.0],
                            "units": "mM",
                            "droplet_nL": 10.0,
                            "starting_conc": 0.0,
                        }
                    ],
                }
            ],
        }
    )

    option = model.factors[0].options[0]
    assert option.reagent_id is None
    assert option.reagent_display_name is None
    assert option.intended_head_type_id is None
    assert option.intended_head_type_display_name is None
    assert option.printing_mode == "droplet"
    assert model.metadata["fill_printing_mode"] == "droplet"


def test_experiment_model_from_dict_infers_stream_mode_from_legacy_volume():
    model = ExperimentModel(prof=CURRENT_PROFILE)
    model.from_dict(
        {
            "metadata": {
                "name": "legacy-stream",
                "fill_droplet_volume_nL": 40.0,
            },
            "factors": [
                {
                    "name": "Water stock",
                    "kind": "additive",
                    "options": [
                        {
                            "name": "Water stock",
                            "targets": [0.0, 1.0],
                            "units": "mM",
                            "droplet_nL": 40.0,
                            "starting_conc": 0.0,
                        }
                    ],
                }
            ],
        }
    )

    option = model.factors[0].options[0]
    assert option.printing_mode == "stream"
    assert model.metadata["fill_printing_mode"] == "stream"


def test_experiment_designer_rebuild_model_persists_reagent_and_head_type(qapp):
    runtime_model = _RuntimeModelStub()
    dialog = _build_dialog_stub(runtime_model)

    dialog._add_reagent_row(
        name="Water stock",
        targets="0, 1",
        units="mM",
        droplet_nL=60.0,
        reagent_id="water",
        reagent_display_name="Water",
        intended_head_type_id="nozzle_100um",
        intended_head_type_display_name="100 um nozzle",
        printing_mode="stream",
    )

    dialog._rebuild_model_from_table()

    option = dialog.model.factors[0].options[0]
    assert option.name == "Water stock"
    assert option.reagent_id == "water"
    assert option.reagent_display_name == "Water"
    assert option.intended_head_type_id == "nozzle_100um"
    assert option.intended_head_type_display_name == "100 um nozzle"
    assert option.printing_mode == "stream"


def test_experiment_designer_stream_mode_preserves_low_volume_inside_shared_range(qapp):
    dialog = _build_dialog_stub(_RuntimeModelStub())

    dialog._add_reagent_row(
        name="Water stock",
        targets="0, 1",
        units="mM",
        droplet_nL=10.0,
        printing_mode="stream",
    )

    mode_combo: QComboBox = dialog._reagent_cell_widget(0, ExperimentDesignDialog.COL_MODE)
    dv_spin: QDoubleSpinBox = dialog._reagent_cell_widget(0, ExperimentDesignDialog.COL_DROPLET)

    assert mode_combo.currentData() == "stream"
    assert dv_spin.minimum() == pytest.approx(EJECTION_VOLUME_HARD_MIN_NL)
    assert dv_spin.maximum() == pytest.approx(EJECTION_VOLUME_HARD_MAX_NL)
    assert dv_spin.value() == pytest.approx(10.0)


def test_experiment_designer_mode_switch_applies_mode_default_with_shared_range(qapp):
    dialog = _build_dialog_stub(_RuntimeModelStub())
    dialog._add_reagent_row(
        name="Water stock",
        targets="0, 1",
        units="mM",
        droplet_nL=20.0,
        printing_mode="droplet",
    )

    mode_combo: QComboBox = dialog._reagent_cell_widget(0, ExperimentDesignDialog.COL_MODE)
    dv_spin: QDoubleSpinBox = dialog._reagent_cell_widget(0, ExperimentDesignDialog.COL_DROPLET)

    dialog._test_sender = mode_combo
    mode_combo.setCurrentIndex(mode_combo.findData("stream"))
    qapp.processEvents()
    assert dv_spin.minimum() == pytest.approx(EJECTION_VOLUME_HARD_MIN_NL)
    assert dv_spin.maximum() == pytest.approx(EJECTION_VOLUME_HARD_MAX_NL)
    assert dv_spin.value() == pytest.approx(60.0)

    dv_spin.setValue(80.0)
    mode_combo.setCurrentIndex(mode_combo.findData("droplet"))
    qapp.processEvents()
    assert dv_spin.minimum() == pytest.approx(EJECTION_VOLUME_HARD_MIN_NL)
    assert dv_spin.maximum() == pytest.approx(EJECTION_VOLUME_HARD_MAX_NL)
    assert dv_spin.value() == pytest.approx(printing_mode_default_ejection_volume_nl(PRINTING_MODE_DROPLET))


@pytest.mark.parametrize(
    ("head_type_id", "expected_stream_nl"),
    [
        ("nozzle_80um", 35.0),
        ("nozzle_100um", 60.0),
        ("nozzle_120um", 80.0),
    ],
)
def test_experiment_designer_mode_switch_uses_head_type_stream_default(
    qapp,
    head_type_id,
    expected_stream_nl,
):
    dialog = _build_dialog_stub(_RuntimeModelStub())
    dialog._add_reagent_row(
        name="Water stock",
        targets="0, 1",
        units="mM",
        droplet_nL=7.0,
        intended_head_type_id=head_type_id,
        printing_mode="droplet",
    )

    mode_combo: QComboBox = dialog._reagent_cell_widget(0, ExperimentDesignDialog.COL_MODE)
    dv_spin: QDoubleSpinBox = dialog._reagent_cell_widget(0, ExperimentDesignDialog.COL_DROPLET)

    dialog._test_sender = mode_combo
    mode_combo.setCurrentIndex(mode_combo.findData("stream"))
    qapp.processEvents()

    assert dv_spin.value() == pytest.approx(expected_stream_nl)


def test_experiment_designer_mode_switch_uses_head_type_droplet_default(qapp):
    dialog = _build_dialog_stub(_RuntimeModelStub())
    dialog._add_reagent_row(
        name="Water stock",
        targets="0, 1",
        units="mM",
        droplet_nL=80.0,
        intended_head_type_id="nozzle_120um",
        printing_mode="stream",
    )

    mode_combo: QComboBox = dialog._reagent_cell_widget(0, ExperimentDesignDialog.COL_MODE)
    dv_spin: QDoubleSpinBox = dialog._reagent_cell_widget(0, ExperimentDesignDialog.COL_DROPLET)

    dialog._test_sender = mode_combo
    mode_combo.setCurrentIndex(mode_combo.findData("droplet"))
    qapp.processEvents()

    assert dv_spin.value() == pytest.approx(12.0)


def test_experiment_designer_head_type_switch_updates_default_like_volume(qapp):
    dialog = _build_dialog_stub(_RuntimeModelStub())
    dialog._add_reagent_row(
        name="Water stock",
        targets="0, 1",
        units="mM",
        droplet_nL=60.0,
        intended_head_type_id="nozzle_100um",
        printing_mode="stream",
    )

    head_type_combo: QComboBox = dialog._reagent_cell_widget(0, ExperimentDesignDialog.COL_HEAD_TYPE)
    dv_spin: QDoubleSpinBox = dialog._reagent_cell_widget(0, ExperimentDesignDialog.COL_DROPLET)

    dialog._test_sender = head_type_combo
    head_type_combo.setCurrentIndex(_head_type_index(head_type_combo, "nozzle_80um"))
    qapp.processEvents()

    assert dv_spin.value() == pytest.approx(35.0)

    head_type_combo.setCurrentIndex(_head_type_index(head_type_combo, "nozzle_120um"))
    qapp.processEvents()

    assert dv_spin.value() == pytest.approx(80.0)


def test_experiment_designer_head_type_switch_preserves_custom_volume(qapp):
    dialog = _build_dialog_stub(_RuntimeModelStub())
    dialog._add_reagent_row(
        name="Water stock",
        targets="0, 1",
        units="mM",
        droplet_nL=42.0,
        intended_head_type_id="nozzle_100um",
        printing_mode="stream",
    )

    head_type_combo: QComboBox = dialog._reagent_cell_widget(0, ExperimentDesignDialog.COL_HEAD_TYPE)
    dv_spin: QDoubleSpinBox = dialog._reagent_cell_widget(0, ExperimentDesignDialog.COL_DROPLET)

    dialog._test_sender = head_type_combo
    head_type_combo.setCurrentIndex(_head_type_index(head_type_combo, "nozzle_80um"))
    qapp.processEvents()

    assert dv_spin.value() == pytest.approx(42.0)


def test_experiment_designer_loaded_row_preserves_saved_volume_with_head_type_default(qapp):
    dialog = _build_dialog_stub(_RuntimeModelStub())
    dialog._add_reagent_row(
        name="Water stock",
        targets="0, 1",
        units="mM",
        droplet_nL=9.0,
        intended_head_type_id="nozzle_80um",
        printing_mode="stream",
    )

    dv_spin: QDoubleSpinBox = dialog._reagent_cell_widget(0, ExperimentDesignDialog.COL_DROPLET)

    assert dv_spin.value() == pytest.approx(9.0)


def test_experiment_designer_prior_indicator_uses_preview_status(qapp):
    runtime_model = _RuntimeModelStub(
        preview={
            "status": "strong",
            "prior": {
                "aggregation_level": "exact_reagent_head_type",
                "recommendation_confidence_adjusted": 0.86,
                "recommended_pressure_psi": 1.62,
                "expected_mean_volume_nL": 10.1,
                "expected_cv_pct": 4.2,
                "contributing_runs": 5,
            },
        }
    )
    dialog = _build_dialog_stub(runtime_model)
    dialog._add_reagent_row(
        name="Water stock",
        targets="0, 1",
        units="mM",
        droplet_nL=10.0,
        reagent_id="water",
        reagent_display_name="Water",
        intended_head_type_id="nozzle_100um",
    )

    preview = dialog._refresh_prior_availability_for_row(0)
    label: QLabel = dialog._reagent_cell_widget(0, ExperimentDesignDialog.COL_PRIOR)

    assert preview["status"] == "strong"
    assert label.text() == "Strong prior"
    assert "Exact reagent + head type" in label.toolTip()
    assert "confidence 0.86" in label.toolTip()
    assert runtime_model.preview_requests[0]["head_type_id"] == "nozzle_100um"
    assert runtime_model.preview_requests[0]["target_volume_nl"] == pytest.approx(10.0)


def test_experiment_designer_prior_indicator_shows_memory_disabled(qapp):
    runtime_model = _RuntimeModelStub(
        preview={
            "status": "memory_disabled",
            "status_label": "Memory disabled",
            "prior": None,
        }
    )
    dialog = _build_dialog_stub(runtime_model)
    dialog._add_reagent_row(
        name="Water stock",
        targets="0, 1",
        units="mM",
        droplet_nL=10.0,
        reagent_id="water",
        reagent_display_name="Water",
        intended_head_type_id="nozzle_100um",
    )

    preview = dialog._refresh_prior_availability_for_row(0)
    label: QLabel = dialog._reagent_cell_widget(0, ExperimentDesignDialog.COL_PRIOR)

    assert preview["status"] == "memory_disabled"
    assert label.text() == "Memory disabled"
    assert "disabled" in label.toolTip().lower()


def test_load_reactions_from_model_applies_design_identity(experiment_model_factory, tmp_path):
    model = experiment_model_factory()
    model.calibration_memory_store = CalibrationMemoryStore(model=model, root_dir=tmp_path / "CalibrationMemory")
    model.calibration_memory_store.ensure_initialized()
    model.experiment_model.set_metadata(
        fill_reagent_name="Water",
        fill_droplet_volume_nL=60.0,
        fill_printing_mode="stream",
    )
    model.experiment_model.add_additive(
        name="Water stock",
        targets=[0.0, 1.0],
        units="mM",
        droplet_nL=10.0,
        reagent_id="water",
        reagent_display_name="Water",
        intended_head_type_id="nozzle_100um",
        intended_head_type_display_name="100 um nozzle",
    )
    result = model.experiment_model.optimize_stock_solutions(quantum=0.1, max_refine=60, two_max_refine=40, allow_two=True)
    assert result["best"] is True
    model.experiment_model.generate_experiment()

    stock_solutions, _reaction_collection = Model.load_reactions_from_model(model)
    water_stock = next(
        stock for stock in stock_solutions.get_all_stock_solutions()
        if stock.get_reagent_name() == "Water stock"
    )

    assert water_stock.reagent_id == "water"
    assert water_stock.display_name == "Water"
    assert water_stock.intended_head_type_id == "nozzle_100um"
    assert water_stock.intended_head_type_display_name == "100 um nozzle"
    assert water_stock.get_printing_mode() == "droplet"

    fill_stock = next(
        stock for stock in stock_solutions.get_all_stock_solutions()
        if stock.get_reagent_name() == "Water"
    )
    assert fill_stock.get_printing_mode() == "stream"


def test_experiment_designer_fill_mode_updates_volume_range_and_metadata(qapp):
    dialog = _build_real_dialog()
    dialog.show()
    qapp.processEvents()

    dialog.fill_mode_combo.setCurrentIndex(dialog.fill_mode_combo.findData("stream"))
    qapp.processEvents()

    assert dialog.fill_dv_spin.minimum() == pytest.approx(EJECTION_VOLUME_HARD_MIN_NL)
    assert dialog.fill_dv_spin.maximum() == pytest.approx(EJECTION_VOLUME_HARD_MAX_NL)
    assert dialog.fill_dv_spin.value() == pytest.approx(60.0)

    dialog.fill_dv_spin.setValue(85.0)
    dialog._update_metadata_from_controls()

    assert dialog.model.metadata["fill_printing_mode"] == "stream"
    assert dialog.model.metadata["fill_droplet_volume_nL"] == pytest.approx(85.0)

    dialog.close()


def test_experiment_designer_transposes_reagent_fields_and_reorders_prior(qapp):
    dialog = _build_real_dialog()
    dialog.setMinimumSize(0, 0)
    for idx in range(12):
        dialog._add_reagent_row(
            name=f"Water stock {idx + 1}",
            targets="0, 1, 2, 3",
            units="mM",
            droplet_nL=10.0,
            reagent_id="water",
            reagent_display_name="Water",
            intended_head_type_id="nozzle_100um",
            intended_head_type_display_name="100 um nozzle",
        )

    dialog.resize(640, 260)
    dialog.show()
    qapp.processEvents()

    assert dialog.reagent_name_table is None
    assert dialog._has_frozen_reagent_column() is False
    assert dialog._reagent_row_count() == dialog.reagent_table.columnCount() == 12
    assert dialog.reagent_table.rowCount() == ExperimentDesignDialog.COL_DELETE + 1
    assert dialog._reagent_cell_widget(0, ExperimentDesignDialog.COL_STOCK_LABEL) is dialog.reagent_table.cellWidget(
        ExperimentDesignDialog.COL_STOCK_LABEL,
        0,
    )
    assert dialog.reagent_table.verticalHeaderItem(dialog.COL_PRIOR).text() == "Prior"
    assert dialog.reagent_table.verticalHeader().isVisible()
    assert "padding-left: 10px" in dialog.reagent_table.verticalHeader().styleSheet()
    assert dialog.reagent_table.horizontalHeaderItem(0).text() == "Water stock 1"

    first_name = dialog._reagent_cell_widget(0, ExperimentDesignDialog.COL_STOCK_LABEL)
    first_name.setText("Renamed stock")
    qapp.processEvents()
    assert dialog.reagent_table.horizontalHeaderItem(0).text() == "Renamed stock"

    dialog.reagent_table.horizontalScrollBar().setValue(dialog.reagent_table.horizontalScrollBar().maximum())
    qapp.processEvents()
    assert dialog.reagent_table.horizontalScrollBar().value() == dialog.reagent_table.horizontalScrollBar().maximum()

    dialog.close()


def test_runtime_printer_head_identity_is_generated_from_intended_head_type(tmp_path):
    model = Model.__new__(Model)
    model.experiment_model = SimpleNamespace(metadata={"name": "screening-run"})
    model.calibration_memory_store = CalibrationMemoryStore(model=model, root_dir=tmp_path / "CalibrationMemory")
    model.calibration_memory_store.ensure_initialized()
    model._disposable_printer_head_counter = 0

    stock = StockSolution("Water stock_1.00_mM", "Water stock", 1.0, "mM")
    stock.set_intended_head_type(
        head_type_id="nozzle_100um",
        display_name="100 um nozzle",
        nominal_nozzle_diameter_um=100.0,
    )
    printer_head = PrinterHead(stock)

    Model._apply_runtime_printer_head_identity(model, printer_head)

    assert printer_head.head_type_id == "nozzle_100um"
    assert printer_head.nominal_nozzle_diameter_um == pytest.approx(100.0)
    assert printer_head.printer_head_id.startswith("nozzle_100um__screening_run__")


def test_list_known_printer_head_types_includes_default_ejection_volumes(tmp_path):
    model = Model.__new__(Model)
    model.calibration_memory_store = CalibrationMemoryStore(model=model, root_dir=tmp_path / "CalibrationMemory")
    model.calibration_memory_store.ensure_initialized()

    rows = Model.list_known_printer_head_types(model)
    by_id = {row["head_type_id"]: row for row in rows}

    assert by_id["nozzle_80um"]["default_droplet_ejection_volume_nL"] == pytest.approx(7.0)
    assert by_id["nozzle_80um"]["default_stream_ejection_volume_nL"] == pytest.approx(35.0)
    assert by_id["nozzle_100um"]["default_droplet_ejection_volume_nL"] == pytest.approx(9.0)
    assert by_id["nozzle_100um"]["default_stream_ejection_volume_nL"] == pytest.approx(60.0)
    assert by_id["nozzle_120um"]["default_droplet_ejection_volume_nL"] == pytest.approx(12.0)
    assert by_id["nozzle_120um"]["default_stream_ejection_volume_nL"] == pytest.approx(80.0)


def test_register_experiment_design_reagents_updates_local_registry_not_template(monkeypatch, tmp_path):
    template_root, local_root = _configure_local_calibration_memory(monkeypatch, tmp_path)
    template_reagents_path = template_root / "entities" / "reagents.json"
    template_before = template_reagents_path.read_text(encoding="utf-8")
    model = Model.__new__(Model)
    model.experiment_model = SimpleNamespace(metadata={"name": "screening-run"})
    model.calibration_memory_store = CalibrationMemoryStore(model=model)

    design = ExperimentModel(prof=CURRENT_PROFILE)
    design.add_additive(
        name="Custom reagent stock",
        targets=[0.0, 1.0],
        units="mM",
        droplet_nL=10.0,
        reagent_display_name="Custom reagent",
    )

    registered = Model.register_experiment_design_reagents(model, design)

    assert registered == ["custom_reagent"]
    local_payload = json.loads((local_root / "entities" / "reagents.json").read_text(encoding="utf-8"))
    assert "custom_reagent" in {item["reagent_id"] for item in local_payload["items"]}
    assert template_reagents_path.read_text(encoding="utf-8") == template_before


def test_preview_experiment_design_prior_returns_memory_disabled(experiment_model_factory, tmp_path):
    model = experiment_model_factory()
    model.calibration_memory_store = CalibrationMemoryStore(model=model, root_dir=tmp_path / "CalibrationMemory")
    model.calibration_memory_store.ensure_initialized()
    model.calibration_memory_store.set_memory_enabled(False)

    preview = Model.preview_experiment_design_prior(
        model,
        reagent_name="Water",
        reagent_id="water",
        head_type_id="nozzle_100um",
        target_volume_nl=10.0,
    )

    assert preview["status"] == "memory_disabled"
    assert preview["prior"] is None
