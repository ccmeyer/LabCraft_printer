import json
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QDoubleSpinBox, QGroupBox, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget

import LocalConfig
import View as view_module
from CalibrationMemoryStore import CalibrationMemoryStore
from ExecutionPlan import ExecutionPlanState
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
        "Actions",
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
    dialog = ExperimentDesignDialog(ExperimentModel(prof=CURRENT_PROFILE), main_window)
    # Most layout/integration tests close the dialog as fixture cleanup. Tests
    # exercising the unsaved prompt explicitly restore this to False.
    dialog._allow_close_without_prompt = True
    return dialog


def _install_successful_new_session_handler(dialog, base_dir):
    dialog.model.experiments_root = str(base_dir)

    def start_new_session():
        dialog.model.reset_experiment_model()
        dialog.model.initialize_experiment(base_dir=str(base_dir))
        return dialog.model.experiment_dir_path

    dialog.main_window.start_new_experiment_session = Mock(
        side_effect=start_new_session
    )
    return dialog.main_window.start_new_experiment_session


def _seed_new_experiment_origin(dialog, *, upload_mode, lifecycle):
    if upload_mode is not None:
        data = {"Drug (mM)": [1.0, 2.0]}
        if upload_mode == "explicit_wells":
            data = {"Well": ["A1", "B1"], **data}
        dialog.model.set_uploaded_design_from_dataframe(
            pd.DataFrame(data), source_path="prior-design.csv"
        )
        dialog._uploaded_design_active = True
        dialog._uploaded_design_path = "prior-design.csv"
        dialog._load_factors_into_table()
        dialog._apply_uploaded_design_mode_to_ui(True)
        dialog._apply_manual_assignment_lock_state()

    plan_state = {
        "editable": None,
        "reloaded_zero_progress": ExecutionPlanState.PREPARED,
        "partial": ExecutionPlanState.ACTIVE,
        "completed": ExecutionPlanState.COMPLETED,
    }[lifecycle]
    if plan_state is not None:
        dialog.model._execution_plan_snapshot = SimpleNamespace(state=plan_state)
        dialog.model._execution_plan_reload_read_only = True

    if lifecycle in {"partial", "completed"}:
        added = 1 if lifecycle == "partial" else 2
        dialog.model.progress_data = {
            "A1": {
                "reagents": {
                    "Drug_1_mM": {
                        "target_droplets": 2,
                        "added_droplets": added,
                    }
                }
            }
        }
        dialog._set_progress_protection(
            True,
            {
                "total_added_droplets": added,
                "wells_with_progress": 1,
            },
        )

    dialog._refresh_all_lock_states()


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


def test_experiment_designer_uses_grouped_wide_layout_without_export_action(qapp):
    dialog = _build_real_dialog()
    dialog.resize(1560, 840)
    dialog.show()
    qapp.processEvents()

    group_titles = {group.title() for group in dialog.findChildren(QGroupBox)}

    assert dialog.minimumWidth() == 1560
    assert {
        "Experiment",
        "Reaction Setup",
        "Design Options",
        "Design Tools",
        "Experiment Actions",
        "Design Information",
    }.issubset(group_titles)
    assert "Design Status" not in group_titles
    assert dialog.design_information_panel.minimumWidth() == 350
    assert dialog.design_information_panel.maximumWidth() == 350
    assert dialog.stock_table.minimumWidth() == 700
    assert dialog.stock_table.parentWidget() is dialog.stock_information_region
    assert dialog.design_information_panel.parentWidget() is dialog.stock_information_region
    assert dialog.reagent_table.parentWidget() is dialog
    assert not hasattr(dialog, "reagent_editor_region")
    assert not hasattr(dialog, "reagent_action_rail")
    assert not hasattr(dialog, "table_add_reagent_btn")
    assert abs(
        dialog.reagent_table.geometry().right()
        - dialog.stock_information_region.geometry().right()
    ) <= 1
    assert dialog._stock_information_layout.indexOf(dialog.design_information_panel) < dialog._stock_information_layout.indexOf(dialog.stock_table)
    assert dialog.design_messages_scroll.isAncestorOf(dialog.status_lbl)
    assert dialog.design_messages_scroll.isAncestorOf(dialog.stock_table_status_lbl)
    assert dialog.design_messages_scroll.isAncestorOf(dialog.tip_lbl)
    assert not hasattr(dialog, "summary_lbl")
    assert dialog.summary_total_reactions_value_lbl.alignment() & Qt.AlignRight
    assert dialog.summary_available_wells_value_lbl.alignment() & Qt.AlignRight
    assert dialog.summary_worst_nonfill_value_lbl.alignment() & Qt.AlignRight
    assert dialog.status_lbl.styleSheet() == ""
    assert dialog.stock_table_status_lbl.styleSheet() == ""
    assert not hasattr(dialog, "export_reaction_preview_btn")
    assert dialog.reset_upload_btn.text() == "Clear Imported Design"
    assert dialog.reset_upload_btn.isHidden() is True
    assert dialog.add_reagent_btn.minimumHeight() == 36
    assert dialog.add_reagent_btn.styleSheet() == ""
    assert dialog.auto_update_chk.text() == "Automatically recalculate design"
    assert "does not save" in dialog.auto_update_chk.toolTip()
    assert dialog.save_btn.text() == "Save Draft"
    assert dialog.advanced_settings_panel.isHidden() is True
    assert "Allowed Printed-Volume Overage (nL)" in {
        label.text() for label in dialog.advanced_settings_panel.findChildren(QLabel)
    }

    add_position = dialog.design_tools_layout.getItemPosition(
        dialog.design_tools_layout.indexOf(dialog.add_reagent_btn)
    )
    conditions_position = dialog.design_tools_layout.getItemPosition(
        dialog.design_tools_layout.indexOf(dialog.unique_conditions_btn)
    )
    preview_position = dialog.design_tools_layout.getItemPosition(
        dialog.design_tools_layout.indexOf(dialog.preview_reactions_btn)
    )
    import_position = dialog.design_tools_layout.getItemPosition(
        dialog.design_tools_layout.indexOf(dialog.upload_design_btn)
    )
    assert add_position == (0, 0, 1, 2)
    assert conditions_position == (1, 0, 1, 1)
    assert preview_position == (1, 1, 1, 1)
    assert import_position == (2, 0, 1, 2)

    dialog._apply_uploaded_design_mode_to_ui(True)

    assert dialog.reset_upload_btn.isHidden() is False
    assert dialog.add_reagent_btn.isEnabled() is False
    assert dialog.design_tools_layout.getItemPosition(
        dialog.design_tools_layout.indexOf(dialog.upload_design_btn)
    ) == (2, 0, 1, 1)
    assert dialog.design_tools_layout.getItemPosition(
        dialog.design_tools_layout.indexOf(dialog.reset_upload_btn)
    ) == (2, 1, 1, 1)

    dialog._apply_uploaded_design_mode_to_ui(False)
    assert dialog.design_tools_layout.getItemPosition(
        dialog.design_tools_layout.indexOf(dialog.upload_design_btn)
    ) == (2, 0, 1, 2)
    layout_count = dialog.design_tools_layout.count()
    for _ in range(3):
        dialog._apply_uploaded_design_mode_to_ui(True)
        dialog._apply_uploaded_design_mode_to_ui(False)
    assert dialog.design_tools_layout.count() == layout_count
    dialog.close()


def test_stock_solution_table_is_read_only_calculated_output(qapp):
    dialog = _build_real_dialog()
    dialog.model.get_stock_table_rows = lambda include_fill=True: [
        {
            "factor_name": "Calculated stock",
            "option_name": "",
            "stock_concentration": 12.5,
            "delta_per_drop": 0.25,
            "units": "mM",
            "droplet_volume_nL": 10.0,
            "max_per_rxn_nL": 20.0,
            "total_droplets": 4,
            "total_volume_uL": 1.0,
        }
    ]

    dialog._refresh_stock_table()
    first_item = dialog.stock_table.item(0, 0)

    assert dialog.stock_table.isEnabled() is True
    assert dialog.stock_table.editTriggers() == QAbstractItemView.NoEditTriggers
    assert "Calculated stock solutions" in dialog.stock_table.toolTip()
    for column in range(dialog.stock_table.columnCount()):
        assert not (
            dialog.stock_table.item(0, column).flags() & Qt.ItemFlag.ItemIsEditable
        )

    dialog.stock_table.editItem(first_item)
    qapp.processEvents()
    assert dialog.stock_table.findChildren(QLineEdit) == []

    first_item.setText("Temporary widget-only edit")
    dialog._refresh_stock_table()
    assert dialog.stock_table.item(0, 0).text() == "Calculated stock"
    dialog.close()


def test_primary_add_reagent_button_uses_standard_style_and_shared_action(qapp):
    dialog = _build_real_dialog()
    dialog.auto_update_chk.setChecked(False)

    dialog.add_reagent_btn.click()

    assert dialog._reagent_row_count() == 1
    assert dialog._draft_is_dirty() is True
    assert dialog.add_reagent_btn.minimumHeight() == 36
    assert dialog.add_reagent_btn.styleSheet() == ""
    assert not hasattr(dialog, "table_add_reagent_btn")
    dialog.close()


def test_compact_design_option_rows_toggle_dependents_without_reset(qapp):
    dialog = _build_real_dialog()

    assert dialog.randomize_chk.parentWidget() is dialog.randomization_options_row
    assert dialog.random_seed_lbl.parentWidget() is dialog.randomization_options_row
    assert dialog.random_seed_spin.parentWidget() is dialog.randomization_options_row
    assert dialog.subset_chk.parentWidget() is dialog.subset_design_options_row
    assert dialog.reduction_factor_lbl.parentWidget() is dialog.subset_design_options_row
    assert dialog.reduction_spin.parentWidget() is dialog.subset_design_options_row
    assert dialog.random_seed_spin.width() == 100
    assert dialog.reduction_spin.width() == 100
    assert dialog.randomize_chk.text() == "Randomize well assignments"
    assert dialog.subset_chk.text() == "Use subset design"
    assert "reproduce randomized reaction-well assignments" in dialog.random_seed_spin.toolTip()
    assert "factorial source space" in dialog.reduction_spin.toolTip()

    dialog.random_seed_spin.setValue(2468)
    dialog.reduction_spin.setValue(7)
    dialog.randomize_chk.setChecked(False)
    dialog.subset_chk.setChecked(False)

    assert dialog.random_seed_lbl.isEnabled() is False
    assert dialog.random_seed_spin.isEnabled() is False
    assert dialog.reduction_factor_lbl.isEnabled() is False
    assert dialog.reduction_spin.isEnabled() is False

    dialog.randomize_chk.setChecked(True)
    dialog.subset_chk.setChecked(True)

    assert dialog.random_seed_lbl.isEnabled() is True
    assert dialog.random_seed_spin.isEnabled() is True
    assert dialog.reduction_factor_lbl.isEnabled() is True
    assert dialog.reduction_spin.isEnabled() is True
    assert dialog.random_seed_spin.value() == 2468
    assert dialog.reduction_spin.value() == 7

    dialog.randomize_chk.setChecked(False)
    dialog.subset_chk.setChecked(False)
    assert dialog.random_seed_spin.value() == 2468
    assert dialog.reduction_spin.value() == 7
    dialog._update_metadata_from_controls()
    assert dialog.model.metadata["random_seed"] is None
    assert dialog.model.metadata["reduction_factor"] == 1
    assert dialog.random_seed_spin.value() == 2468
    assert dialog.reduction_spin.value() == 7
    dialog.close()


def test_design_option_model_sync_restores_values_and_conditional_state(qapp):
    dialog = _build_real_dialog()
    dialog._recompute_silent = Mock()
    dialog.model.metadata.update(
        {
            "randomize_assignments": True,
            "random_seed": 9876,
            "use_subset_design": True,
            "reduction_factor": 9,
        }
    )

    dialog._sync_controls_from_model()

    assert dialog.randomize_chk.isChecked() is True
    assert dialog.random_seed_spin.value() == 9876
    assert dialog.random_seed_lbl.isEnabled() is True
    assert dialog.random_seed_spin.isEnabled() is True
    assert dialog.subset_chk.isChecked() is True
    assert dialog.reduction_spin.value() == 9
    assert dialog.reduction_factor_lbl.isEnabled() is True
    assert dialog.reduction_spin.isEnabled() is True
    dialog._recompute_silent.assert_called_once_with()
    dialog.close()


def test_design_option_rows_are_disabled_together_during_busy_work(qapp):
    dialog = _build_real_dialog()
    dialog.randomize_chk.setChecked(True)
    dialog.subset_chk.setChecked(True)

    with view_module._BusyUiContext(
        dialog,
        "Updating design...",
        widgets=dialog._design_busy_widgets(),
        show_dialog=False,
    ):
        assert dialog.randomization_options_row.isEnabled() is False
        assert dialog.random_seed_lbl.isEnabled() is False
        assert dialog.random_seed_spin.isEnabled() is False
        assert dialog.subset_design_options_row.isEnabled() is False
        assert dialog.reduction_factor_lbl.isEnabled() is False
        assert dialog.reduction_spin.isEnabled() is False

    assert dialog.randomization_options_row.isEnabled() is True
    assert dialog.random_seed_spin.isEnabled() is True
    assert dialog.subset_design_options_row.isEnabled() is True
    assert dialog.reduction_spin.isEnabled() is True
    dialog.close()


def test_duplicate_reagent_copies_editable_fields_and_waits_for_unique_label(qapp):
    dialog = _build_real_dialog()
    dialog.auto_update_chk.setChecked(False)
    dialog.choice_groups = {"Buffer options"}
    dialog._add_reagent_row(
        name="Buffer A",
        group="Buffer options",
        targets="0.5, 1.25, 2.5",
        units="mg/mL",
        droplet_nL=37.0,
        starting_conc=0.75,
        forced_stock_conc=8.5,
        max_stock_conc=12.25,
        reagent_id="water",
        reagent_display_name="Water",
        intended_head_type_id="nozzle_100um",
        intended_head_type_display_name="100 um nozzle",
        printing_mode="stream",
        schedule_update=False,
    )
    dialog._add_reagent_row(
        name="Trailing reagent",
        group=dialog.GROUP_ADDITIVE,
        schedule_update=False,
    )
    source_prior = dialog._reagent_cell_widget(0, dialog.COL_PRIOR)
    source_prior.setText("sentinel that must not be copied")
    optimize = Mock()
    dialog.model.optimize_stock_solutions = optimize
    dialog.show()
    qapp.processEvents()

    actions = dialog._reagent_cell_widget(0, dialog.COL_ACTIONS)
    duplicate_button = actions.findChild(QPushButton, "duplicateReagentButton")
    duplicate_button.click()
    qapp.processEvents()

    assert dialog._reagent_row_count() == 3
    assert dialog._reagent_cell_widget(2, dialog.COL_STOCK_LABEL).text() == "Trailing reagent"
    for field in (
        dialog.COL_STOCK_LABEL,
        dialog.COL_REAGENT,
        dialog.COL_GROUP,
        dialog.COL_HEAD_TYPE,
        dialog.COL_MODE,
        dialog.COL_STARTING,
        dialog.COL_TARGETS,
        dialog.COL_UNITS,
        dialog.COL_SET_STOCK,
        dialog.COL_MAX_STOCK,
        dialog.COL_DROPLET,
    ):
        source = dialog._reagent_cell_widget(0, field)
        copied = dialog._reagent_cell_widget(1, field)
        if isinstance(source, QLineEdit):
            assert copied.text() == source.text()
        elif isinstance(source, QComboBox):
            assert copied.currentText() == source.currentText()
            assert copied.currentData() == source.currentData()
        elif isinstance(source, QDoubleSpinBox):
            assert copied.value() == pytest.approx(source.value())
    assert dialog._reagent_cell_widget(1, dialog.COL_PRIOR).text() != source_prior.text()
    assert dialog._duplicate_reagent_label_rows() == {0, 1}
    copied_name = dialog._reagent_cell_widget(1, dialog.COL_STOCK_LABEL)
    assert copied_name.hasFocus()
    assert copied_name.selectedText() == "Buffer A"
    assert dialog._auto_timer.isActive() is False
    assert dialog._design_optimization_dirty is True
    assert dialog._draft_is_dirty() is True
    assert "Rename one Stock / Label" in dialog.status_lbl.text()
    optimize.assert_not_called()

    copied_name.setText("Buffer B")
    assert dialog._reject_duplicate_reagent_labels(show_dialog=False) is None
    dialog.close()


def test_duplicate_label_preflight_scopes_choice_options_by_group(qapp):
    dialog = _build_real_dialog()
    dialog.auto_update_chk.setChecked(False)
    dialog.choice_groups = {"Group A", "Group B"}
    dialog._add_reagent_row(
        name="Shared option", group="Group A", schedule_update=False
    )
    dialog._add_reagent_row(
        name="Shared option", group="Group B", schedule_update=False
    )
    assert dialog._duplicate_reagent_label_rows() == set()

    dialog._add_reagent_row(
        name="Shared option", group="Group A", schedule_update=False
    )
    rebuild = Mock()
    dialog._rebuild_model_from_table = rebuild

    ok, result = dialog._run_design_optimization_flow(
        show_failure_dialog=False,
        show_capacity_dialog=False,
    )

    assert ok is False
    assert result["duplicate_reagent_rows"] == [0, 2]
    assert dialog._duplicate_reagent_label_rows() == {0, 2}
    assert dialog.status_heading_lbl.text() == "Error"
    rebuild.assert_not_called()
    dialog.close()


def test_advanced_overage_setting_remains_metadata_compatible(qapp):
    dialog = _build_real_dialog()

    assert dialog.advanced_settings_panel.isHidden() is True
    dialog.advanced_settings_toggle.setChecked(True)
    assert dialog.advanced_settings_panel.isHidden() is False
    assert "droplet-rounding overages" in dialog.volume_tolerance_spin.toolTip()

    dialog.volume_tolerance_spin.setValue(123.5)
    dialog._update_metadata_from_controls()

    assert dialog.model.metadata["printed_volume_tolerance_nL"] == pytest.approx(123.5)
    dialog.close()


def test_draft_dirty_indicator_is_separate_from_recalculation_freshness(qapp):
    dialog = _build_real_dialog()
    dialog._mark_draft_saved()

    assert dialog.windowTitle() == "Experiment Design (v2)"
    assert dialog.save_btn.text() == "Save Draft"

    dialog._mark_draft_dirty()
    dialog._mark_design_optimization_clean({"best": True})

    assert dialog._draft_is_dirty() is True
    assert dialog.windowTitle().endswith(" *")
    assert dialog.save_btn.text() == "Save Draft *"

    dialog._mark_draft_saved()
    assert dialog._draft_is_dirty() is False
    assert dialog.windowTitle() == "Experiment Design (v2)"
    assert dialog.save_btn.text() == "Save Draft"
    dialog.close()


def test_save_draft_clears_dirty_only_after_persistence_succeeds(monkeypatch, qapp):
    dialog = _build_real_dialog()
    dialog._run_design_optimization_flow = Mock(return_value=(True, {}))
    dialog._persist_design_identity_registry_entries = Mock()
    dialog._ensure_experiment_dir = Mock()
    dialog.model.execution_plan_file_path = None
    dialog.model.save_experiment = Mock()
    dialog._mark_draft_dirty()

    assert dialog._on_save_design() is True
    assert dialog._draft_is_dirty() is False

    dialog.model.save_experiment = Mock(side_effect=OSError("disk unavailable"))
    dialog._mark_draft_dirty()
    warning = Mock()
    monkeypatch.setattr(QMessageBox, "warning", warning)

    assert dialog._on_save_design() is False
    assert dialog._draft_is_dirty() is True
    assert dialog.save_btn.text() == "Save Draft *"
    warning.assert_called_once()
    dialog.close()


class _UnsavedPromptFake:
    Warning = QMessageBox.Warning
    AcceptRole = QMessageBox.AcceptRole
    DestructiveRole = QMessageBox.DestructiveRole
    RejectRole = QMessageBox.RejectRole
    choice = "Cancel"
    last_instance = None

    def __init__(self, _parent):
        type(self).last_instance = self
        self.buttons = {}
        self.default_button = None
        self.escape_button = None
        self.clicked_button = None

    def setWindowTitle(self, title):
        self.title = title

    def setIcon(self, icon):
        self.icon = icon

    def setText(self, text):
        self.text = text

    def setInformativeText(self, text):
        self.informative_text = text

    def addButton(self, label, _role):
        button = object()
        self.buttons[label] = button
        return button

    def setDefaultButton(self, button):
        self.default_button = button

    def setEscapeButton(self, button):
        self.escape_button = button

    def exec(self):
        self.clicked_button = self.buttons[type(self).choice]

    def clickedButton(self):
        return self.clicked_button

    @staticmethod
    def warning(*_args, **_kwargs):
        return None


@pytest.mark.parametrize(
    ("choice", "save_result", "expected", "expected_save_calls"),
    [
        ("Save Draft", True, True, 1),
        ("Save Draft", False, False, 1),
        ("Discard Changes", True, True, 0),
        ("Cancel", True, False, 0),
    ],
)
def test_unsaved_prompt_save_discard_cancel_paths(
    monkeypatch,
    qapp,
    choice,
    save_result,
    expected,
    expected_save_calls,
):
    dialog = _build_real_dialog()
    dialog._allow_close_without_prompt = False
    dialog._mark_draft_dirty()
    save = Mock(return_value=save_result)
    dialog._on_save_design = save
    _UnsavedPromptFake.choice = choice
    monkeypatch.setattr(view_module, "QMessageBox", _UnsavedPromptFake)

    assert dialog._confirm_unsaved_changes("closing the editor") is expected
    assert save.call_count == expected_save_calls
    prompt = _UnsavedPromptFake.last_instance
    assert prompt.title == "Unsaved Experiment Design"
    assert prompt.default_button is prompt.buttons["Save Draft"]
    assert prompt.escape_button is prompt.buttons["Cancel"]

    dialog._allow_close_without_prompt = True
    dialog.close()


def test_new_experiment_is_cancelled_before_replacing_an_unsaved_draft(qapp):
    dialog = _build_real_dialog()
    dialog._allow_close_without_prompt = False
    dialog._mark_draft_dirty()
    dialog._confirm_unsaved_changes = Mock(return_value=False)
    dialog.main_window.start_new_experiment_session = Mock()

    assert dialog._on_new_experiment() is False
    dialog._confirm_unsaved_changes.assert_called_once_with(
        "starting a new experiment"
    )
    dialog.main_window.start_new_experiment_session.assert_not_called()

    dialog._allow_close_without_prompt = True
    dialog.close()


def test_new_experiment_cancelled_from_resume_ready_preserves_current_session(
    monkeypatch,
    qapp,
):
    dialog = _build_real_dialog()
    _seed_new_experiment_origin(
        dialog,
        upload_mode="explicit_wells",
        lifecycle="partial",
    )
    dialog._confirm_unsaved_changes = Mock(return_value=True)
    dialog.main_window.controller = SimpleNamespace(
        get_array_run_state=Mock(return_value="resume_ready")
    )
    dialog.main_window.start_new_experiment_session = Mock()
    _UnsavedPromptFake.choice = "Cancel"
    monkeypatch.setattr(view_module, "QMessageBox", _UnsavedPromptFake)

    assert dialog._on_new_experiment() is False

    dialog.main_window.start_new_experiment_session.assert_not_called()
    assert dialog.model.has_uploaded_design() is True
    assert dialog.model.progress_data
    assert dialog._progress_protected is True
    prompt = _UnsavedPromptFake.last_instance
    assert prompt.title == "Start New Experiment?"
    assert "will not be deleted" in prompt.informative_text
    assert prompt.default_button is prompt.buttons["Cancel"]
    assert prompt.escape_button is prompt.buttons["Cancel"]

    dialog._allow_close_without_prompt = True
    dialog.close()


def test_new_experiment_accepts_resume_ready_detach_before_fresh_reset(
    monkeypatch,
    qapp,
    tmp_path,
):
    dialog = _build_real_dialog()
    _seed_new_experiment_origin(
        dialog,
        upload_mode="automatic_wells",
        lifecycle="partial",
    )
    dialog._confirm_unsaved_changes = Mock(return_value=True)
    dialog.main_window.controller = SimpleNamespace(
        get_array_run_state=Mock(return_value="resume_ready")
    )
    start_new_session = _install_successful_new_session_handler(dialog, tmp_path)
    _UnsavedPromptFake.choice = "Start New Experiment"
    monkeypatch.setattr(view_module, "QMessageBox", _UnsavedPromptFake)

    assert dialog._on_new_experiment() is True

    start_new_session.assert_called_once_with()
    assert dialog.model.has_uploaded_design() is False
    assert dialog.model.progress_data == {}
    assert dialog._progress_protected is False
    assert dialog.add_reagent_btn.isEnabled() is True
    assert dialog.status_lbl.text().startswith("New experiment created:")

    dialog._allow_close_without_prompt = True
    dialog.close()


@pytest.mark.parametrize("lifecycle", ["editable", "completed"])
def test_idle_new_experiment_does_not_show_resume_detach_prompt(
    monkeypatch,
    qapp,
    lifecycle,
):
    dialog = _build_real_dialog()
    _seed_new_experiment_origin(
        dialog,
        upload_mode=None,
        lifecycle=lifecycle,
    )
    dialog.main_window.controller = SimpleNamespace(
        get_array_run_state=Mock(return_value="idle")
    )

    def unexpected_prompt(*_args, **_kwargs):
        raise AssertionError("idle experiments must not show the resume prompt")

    monkeypatch.setattr(view_module, "QMessageBox", unexpected_prompt)

    assert dialog._confirm_resume_ready_new_experiment() is True

    dialog._allow_close_without_prompt = True
    dialog.close()


@pytest.mark.parametrize(
    "upload_mode,lifecycle",
    [
        (None, "editable"),
        (None, "reloaded_zero_progress"),
        (None, "partial"),
        (None, "completed"),
        ("automatic_wells", "editable"),
        ("explicit_wells", "editable"),
        ("automatic_wells", "partial"),
        ("explicit_wells", "partial"),
        ("automatic_wells", "completed"),
        ("explicit_wells", "completed"),
    ],
)
def test_new_experiment_restores_fresh_editable_state(
    qapp,
    tmp_path,
    upload_mode,
    lifecycle,
):
    dialog = _build_real_dialog()
    _seed_new_experiment_origin(
        dialog,
        upload_mode=upload_mode,
        lifecycle=lifecycle,
    )
    start_new_session = _install_successful_new_session_handler(dialog, tmp_path)

    dialog.auto_update_chk.setChecked(False)
    dialog.advanced_settings_panel.show()
    dialog._auto_timer.start()
    dialog._apply_requested = True
    dialog._last_optimization_result = {"best": True, "source": "prior"}
    dialog._design_optimization_dirty = False
    dialog._set_stock_table_stale(True, "Prior stock warning")
    dialog.v_spin.setStyleSheet("border:1px solid red;")
    dialog.final_v_spin.setStyleSheet("border:1px solid red;")
    dialog._recompute_silent = Mock(
        side_effect=AssertionError("new experiment must not optimize an empty design")
    )

    assert dialog._on_new_experiment() is True

    start_new_session.assert_called_once_with()
    dialog._recompute_silent.assert_not_called()
    assert dialog.model.factors == []
    assert dialog.model.additional_conditions == []
    assert dialog.model.has_uploaded_design() is False
    assert dialog.model._uploaded_well_ids is None
    assert dialog.model.progress_data == {}
    assert dialog.model.is_execution_design_locked() is False

    assert dialog._uploaded_design_active is False
    assert dialog._uploaded_design_path is None
    assert dialog._progress_protected is False
    assert dialog._preserve_progress_on_finish is False
    assert dialog._progress_reset_confirmed is False
    assert dialog._progress_lock_status_message == ""
    assert dialog._apply_requested is False
    assert dialog.choice_groups == set()
    assert dialog._design_optimization_dirty is True
    assert dialog._last_optimization_result is None
    assert dialog._stock_table_stale_active is False
    assert dialog._auto_timer.isActive() is False
    assert dialog._draft_is_dirty() is False

    assert dialog.exp_name_edit.isEnabled() is True
    assert dialog.exp_name_edit.isReadOnly() is False
    assert dialog.add_reagent_btn.isEnabled() is True
    assert dialog.upload_design_btn.isEnabled() is True
    assert dialog.reset_upload_btn.isHidden() is True
    assert dialog.run_btn.isEnabled() is True
    assert dialog.save_btn.isEnabled() is True
    assert dialog.v_spin.isEnabled() is True
    assert dialog.final_v_spin.isEnabled() is True
    assert dialog.fill_name_edit.isEnabled() is True
    assert dialog.allow_two_chk.isEnabled() is True
    assert dialog.subset_chk.isEnabled() is True
    assert dialog.finish_btn.isEnabled() is True
    assert dialog.finish_btn.text() == ExperimentDesignDialog.ACTION_FINALIZE_DESIGN
    assert dialog.lifecycle_banner.isHidden() is True
    assert dialog.stock_table_status_lbl.text() == ""
    assert dialog.stock_warning_heading_lbl.isHidden() is True
    assert dialog.v_spin.styleSheet() == ""
    assert dialog.final_v_spin.styleSheet() == ""
    assert dialog.status_lbl.text().startswith("New experiment created:")

    # User workflow/presentation preferences survive the experiment reset.
    assert dialog.auto_update_chk.isChecked() is False
    assert dialog.advanced_settings_panel.isHidden() is False

    dialog._allow_close_without_prompt = True
    dialog.close()


def test_new_experiment_backend_failure_preserves_prior_editor_state(
    monkeypatch,
    qapp,
):
    dialog = _build_real_dialog()
    _seed_new_experiment_origin(
        dialog,
        upload_mode="explicit_wells",
        lifecycle="partial",
    )
    dialog._last_optimization_result = {"best": True, "source": "prior"}
    dialog._design_optimization_dirty = False
    dialog.main_window.start_new_experiment_session = Mock(
        side_effect=RuntimeError("new session failed")
    )
    dialog.main_window.controller = SimpleNamespace(
        get_array_run_state=Mock(return_value="resume_ready")
    )
    _UnsavedPromptFake.choice = "Start New Experiment"
    monkeypatch.setattr(view_module, "QMessageBox", _UnsavedPromptFake)
    refresh_locks = Mock()
    dialog._refresh_all_lock_states = refresh_locks

    assert dialog._on_new_experiment() is None

    dialog.main_window.start_new_experiment_session.assert_called_once_with()
    refresh_locks.assert_not_called()
    assert dialog.model.has_uploaded_design() is True
    assert dialog._uploaded_design_active is True
    assert dialog._uploaded_design_path == "prior-design.csv"
    assert dialog._progress_protected is True
    assert dialog._preserve_progress_on_finish is True
    assert dialog._design_optimization_dirty is False
    assert dialog._last_optimization_result == {
        "best": True,
        "source": "prior",
    }
    assert dialog.add_reagent_btn.isEnabled() is False
    assert dialog.status_lbl.text() == "New experiment failed: new session failed"

    dialog._allow_close_without_prompt = True
    dialog.close()


def test_sync_controls_from_model_can_skip_recompute(qapp):
    dialog = _build_real_dialog()
    dialog.model.metadata["name"] = "fresh-controls"
    dialog.model.metadata["target_reaction_volume_nL"] = 1234.0
    dialog._recompute_silent = Mock()

    dialog._sync_controls_from_model(recompute=False)

    assert dialog.exp_name_edit.text() == "fresh-controls"
    assert dialog.v_spin.value() == pytest.approx(1234.0)
    dialog._recompute_silent.assert_not_called()

    dialog._allow_close_without_prompt = True
    dialog.close()


def test_advanced_grouping_control_persists_resets_and_marks_design_dirty(qapp):
    dialog = _build_real_dialog()
    checkbox = dialog.allow_avoidable_grouping_chk

    assert checkbox.isChecked() is False
    assert "Unavoidable grouping is always allowed and reported" in checkbox.toolTip()
    assert any(
        label.text() == "Allow avoidable target-level grouping"
        for label in dialog.advanced_settings_panel.findChildren(QLabel)
    )

    dialog._design_optimization_dirty = False
    dialog._last_optimization_result = {"best": True}
    checkbox.setChecked(True)
    assert dialog._design_optimization_dirty is True
    assert dialog._auto_timer.isActive() is True
    dialog._auto_timer.stop()

    dialog._update_metadata_from_controls()
    assert dialog.model.metadata["allow_avoidable_target_grouping"] is True

    checkbox.setChecked(False)
    dialog.model.metadata["allow_avoidable_target_grouping"] = True
    dialog._sync_controls_from_model(recompute=False)
    assert checkbox.isChecked() is True

    dialog.model.reset_experiment_model()
    dialog._sync_controls_from_model(recompute=False)
    assert checkbox.isChecked() is False

    dialog._allow_close_without_prompt = True
    dialog.close()


def test_advanced_grouping_control_obeys_execution_design_lock(qapp):
    dialog = _build_real_dialog()
    assert dialog.allow_avoidable_grouping_chk.isEnabled() is True

    dialog.model._execution_plan_snapshot = SimpleNamespace(
        state=ExecutionPlanState.PREPARED
    )
    dialog.model._execution_plan_reload_read_only = True
    dialog._apply_execution_edit_lock_state()

    assert dialog.allow_avoidable_grouping_chk.isEnabled() is False
    dialog._allow_close_without_prompt = True
    dialog.close()


@pytest.mark.parametrize("dialog_size", [(1760, 900), (1560, 840)])
def test_long_design_message_scrolls_without_resizing_editor_sections(qapp, dialog_size):
    dialog = _build_real_dialog()
    dialog.resize(*dialog_size)
    dialog.show()
    qapp.processEvents()

    stable_group_titles = {
        "Experiment",
        "Reaction Setup",
        "Design Options",
        "Design Tools",
        "Experiment Actions",
    }
    stable_groups = {
        group.title(): group
        for group in dialog.findChildren(QGroupBox)
        if group.title() in stable_group_titles
    }
    before_groups = {
        title: group.geometry().getRect()
        for title, group in stable_groups.items()
    }
    before_controls = dialog.controls_panel.geometry().getRect()
    before_reagents = dialog.reagent_table.geometry().getRect()
    before_stock_region = dialog.stock_information_region.geometry().getRect()

    long_message = "\n\n".join(
        f"Validation issue {index}: " + ("Detailed guidance remains available. " * 18)
        for index in range(1, 13)
    )
    dialog._set_status(long_message)
    qapp.processEvents()

    assert dialog.status_lbl.text() == long_message
    assert dialog.status_lbl.textInteractionFlags() & Qt.TextSelectableByMouse
    assert dialog.design_messages_scroll.verticalScrollBar().maximum() > 0
    assert dialog.controls_panel.geometry().getRect() == before_controls
    assert dialog.reagent_table.geometry().getRect() == before_reagents
    assert dialog.stock_information_region.geometry().getRect() == before_stock_region
    assert {
        title: group.geometry().getRect()
        for title, group in stable_groups.items()
    } == before_groups
    assert dialog.design_information_panel.width() == 350
    dialog.close()


def test_stock_warning_and_general_status_coexist_in_information_panel(qapp):
    dialog = _build_real_dialog()
    dialog.show()
    qapp.processEvents()
    status_message = "The current design needs attention before it can be generated."
    stock_warning = "Showing the last valid stock solutions; current inputs are invalid."

    dialog._set_status(status_message)
    dialog._set_stock_table_stale(True, stock_warning)
    qapp.processEvents()

    assert dialog.status_lbl.text() == status_message
    assert dialog.stock_table_status_lbl.text() == stock_warning
    assert dialog.stock_table_status_lbl.isVisible() is True
    assert dialog.stock_warning_heading_lbl.isVisible() is True
    assert dialog.status_heading_lbl.text() == "Error"
    assert "border:2px solid #8a0303" in dialog.design_information_panel.styleSheet()
    assert dialog.design_messages_scroll.isAncestorOf(dialog.status_lbl)
    assert dialog.design_messages_scroll.isAncestorOf(dialog.stock_table_status_lbl)
    assert dialog.stock_table.styleSheet() == "QTableWidget { border:1px solid #8a0303; }"

    dialog._set_stock_table_stale(False, "")

    assert dialog.status_lbl.text() == status_message
    assert dialog.stock_table_status_lbl.text() == ""
    assert dialog.stock_table_status_lbl.isVisible() is False
    assert dialog.stock_warning_heading_lbl.isVisible() is False
    assert dialog.stock_table.styleSheet() == ""
    dialog.close()


def test_design_information_summary_uses_structured_rows(qapp):
    dialog = _build_real_dialog()
    dialog._available_wells_for_selected_plate = lambda: (4, "test plate")

    dialog._update_summary_labels(total_reactions=5, worst_nonfill_nL=12.5)

    assert dialog.summary_total_reactions_value_lbl.text() == "5"
    assert dialog.summary_available_wells_value_lbl.text() == "4"
    assert dialog.summary_worst_nonfill_value_lbl.text() == "12.5 nL"
    assert "color:#8a0303" in dialog.summary_total_reactions_value_lbl.styleSheet()

    dialog._update_summary_labels(total_reactions=3, worst_nonfill_nL=10.0)

    assert dialog.summary_total_reactions_value_lbl.text() == "3"
    assert dialog.summary_total_reactions_value_lbl.styleSheet() == ""
    dialog.close()


def test_design_information_severity_and_tip_states(qapp):
    dialog = _build_real_dialog()
    dialog.show()
    qapp.processEvents()
    before_geometry = dialog.design_information_panel.geometry().getRect()

    dialog._set_status("Update completed.", severity="success")
    dialog._set_tip("Hover a Targets field for details.")
    qapp.processEvents()

    assert dialog.status_heading_lbl.text() == "Ready"
    assert dialog.tip_lbl.isVisible() is True
    assert "Hover a Targets field" not in dialog.status_lbl.text()
    assert "border:2px solid #8c8c8c" in dialog.design_information_panel.styleSheet()

    dialog._set_status("The design cannot be generated.", severity="error")
    qapp.processEvents()

    assert dialog.status_heading_lbl.text() == "Error"
    assert dialog.tip_lbl.text() == ""
    assert dialog.tip_lbl.isVisible() is False
    assert "border:2px solid #8a0303" in dialog.design_information_panel.styleSheet()
    assert dialog.design_information_panel.geometry().getRect() == before_geometry

    dialog._set_status("Check the selected settings.", severity="warning")
    assert dialog.status_heading_lbl.text() == "Warning"
    assert "border:2px solid #c58a00" in dialog.design_information_panel.styleSheet()

    dialog._set_stock_table_stale(True, "Stock solutions are stale.")
    dialog._set_status("Update completed.", severity="success")
    assert dialog.status_heading_lbl.text() == "Error"
    assert "border:2px solid #8a0303" in dialog.design_information_panel.styleSheet()

    dialog._set_stock_table_stale(False, "")
    assert dialog.status_heading_lbl.text() == "Ready"
    assert "border:2px solid #8c8c8c" in dialog.design_information_panel.styleSheet()
    dialog.close()


def test_optimization_guidance_does_not_replace_success_status(qapp):
    dialog = _build_real_dialog()
    dialog.model.plans_per_option = {("Reagent A", None): {"n_stocks": 1}}
    dialog.model.get_target_preview_map = lambda: {
        ("Reagent A", None): [
            {"reachable": True, "abs_error": 0.05},
        ]
    }

    dialog._update_optimization_status(
        {"best": True, "two_stock_search_limited_keys": []}
    )

    assert dialog.status_lbl.text() == "Reactions and stock solutions updated."
    assert dialog.tip_lbl.text().startswith("Hover a Targets field")
    assert dialog.status_heading_lbl.text() == "Ready"
    dialog.close()


def test_two_stock_status_explains_stock_specific_calibration_requirements(qapp):
    dialog = _build_real_dialog()
    dialog.model.plans_per_option = {("Reagent A", None): {"n_stocks": 2}}
    dialog.model.get_target_preview_map = lambda: {}

    dialog._update_optimization_status(
        {"best": True, "two_stock_search_limited_keys": []}
    )

    assert "Two stock solutions are required for: Reagent A." in dialog.status_lbl.text()
    assert (
        "Each stock leg requires its own identified printer head. A measured calibration "
        "can be applied before either leg or the fill stock dispenses."
    ) in dialog.status_lbl.text()
    assert dialog.status_heading_lbl.text() == "Warning"
    dialog.close()


@pytest.mark.parametrize(("change_stock_input", "expected_optimize_calls"), [(False, 0), (True, 1)])
def test_import_apply_reuses_validated_plan_or_reoptimizes_on_fingerprint_mismatch(
    qapp, monkeypatch, change_stock_input, expected_optimize_calls
):
    dialog = _build_real_dialog()
    monkeypatch.setattr(view_module.QMessageBox, "warning", lambda *_args: None)
    design = pd.DataFrame({"R mM": [0.1, 0.2]})
    stocks = pd.DataFrame(
        {"reagent": ["R"], "stock_conc": [10.0], "units": ["mM"]}
    )
    report = dialog.model.build_import_feasibility_report(
        design,
        max_stock_df=stocks,
        printed_volume_nL=9.0,
        printed_volume_tolerance_nL=0.0,
        final_volume_nL=450.0,
        allow_two=True,
    )
    max_stock = 11.0 if change_stock_input else 10.0
    payload = {
        "design_df": design,
        "source_path": "two-stock.csv",
        "max_stock_by_reagent": {"R": max_stock},
        "stock_settings_by_reagent": {
            "R": {
                "max_stock_conc": max_stock,
                "printing_mode": "droplet",
                "droplet_nL": 9.0,
            }
        },
        "printed_volume_nL": 9.0,
        "printed_volume_tolerance_nL": 0.0,
        "final_volume_nL": 450.0,
        "allow_two": True,
        "stock_allocation_reuse_payload": report["stock_allocation_reuse_payload"],
    }
    optimize_calls = []
    original_optimize = dialog.model.optimize_stock_solutions

    def counted_optimize(**kwargs):
        optimize_calls.append(dict(kwargs))
        return original_optimize(**kwargs)

    dialog.model.optimize_stock_solutions = counted_optimize

    dialog._apply_uploaded_design_payload(payload)

    assert len(optimize_calls) == expected_optimize_calls
    assert dialog.model.plans_per_option[("R", None)]["n_stocks"] == 2
    assert dialog.model.get_number_of_reactions() == 2
    assert dialog._stock_allocation_dirty is False
    dialog.close()


def test_optimization_status_distinguishes_time_and_state_limits(qapp):
    dialog = _build_real_dialog()
    dialog.model.plans_per_option = {}
    dialog.model.get_target_preview_map = lambda: {}

    dialog._update_optimization_status(
        {
            "best": True,
            "two_stock_search_limited_keys": [],
            "stock_allocation_search_limited": True,
            "stock_allocation_limit_reasons": ["time_budget"],
            "stock_allocation_time_budget_ms": 75.0,
            "optimizer_seed_distinct_level_loss": 4,
            "optimizer_selected_rank": {"total_distinct_level_loss": 4},
            "stock_allocation_improved_seed": False,
        }
    )
    assert (
        "No better level resolution was found within 75 ms; the "
        "concentration-first plan was retained."
    ) in dialog.status_lbl.text()

    dialog._update_optimization_status(
        {
            "best": True,
            "two_stock_search_limited_keys": [],
            "stock_allocation_search_limited": True,
            "stock_allocation_limit_reasons": ["state_cap"],
            "optimizer_seed_distinct_level_loss": 4,
            "optimizer_selected_rank": {"total_distinct_level_loss": 4},
            "stock_allocation_improved_seed": False,
        }
    )
    assert "allocation-state limit without finding better" in dialog.status_lbl.text()

    dialog._update_optimization_status(
        {
            "best": True,
            "two_stock_search_limited_keys": [],
            "stock_allocation_search_limited": True,
            "stock_allocation_limit_reasons": ["time_budget"],
            "stock_allocation_time_budget_ms": 75.0,
            "optimizer_seed_distinct_level_loss": 4,
            "optimizer_selected_rank": {"total_distinct_level_loss": 1},
            "stock_allocation_improved_seed": True,
            "stock_allocation_time_to_best_ms": 42.0,
        }
    )
    assert "reduced grouped levels from 4 to 1 before its 75 ms limit" in (
        dialog.status_lbl.text()
    )
    assert "secondary optimality was not proven" in dialog.status_lbl.text()

    dialog._update_optimization_status(
        {
            "best": True,
            "two_stock_search_limited_keys": [],
            "stock_allocation_search_limited": False,
            "optimizer_seed_distinct_level_loss": 1,
            "optimizer_selected_rank": {"total_distinct_level_loss": 0},
            "stock_allocation_improved_seed": True,
            "stock_allocation_time_to_best_ms": 11.25,
            "stock_allocation_stop_reason": "search_exhausted",
        }
    )
    assert "reduced grouped levels from 1 to 0 in 11.2 ms" in (
        dialog.status_lbl.text()
    )
    dialog.close()


def test_clear_imported_design_returns_to_an_empty_manual_editor(monkeypatch, qapp):
    dialog = _build_real_dialog()
    sample_design = pd.DataFrame(
        {
            "well": ["A1", "A2"],
            "[tRNA] mM": [0.0, 1.0],
        }
    )
    dialog.model.set_uploaded_design_from_dataframe(
        sample_design,
        source_path="synthetic_clear_import.csv",
    )
    dialog.model.set_additional_conditions(
        [{"label": "Control", "replicates": 2, "targets": {("tRNA", None): 0.0}}]
    )
    dialog._uploaded_design_active = True
    dialog._uploaded_design_path = "import.csv"
    dialog._load_factors_into_table()
    dialog._apply_uploaded_design_mode_to_ui(True)

    optimize = Mock(side_effect=AssertionError("clear must not optimize"))
    generate = Mock(side_effect=AssertionError("clear must not generate"))
    dialog.model.optimize_stock_solutions = optimize
    dialog.model.generate_experiment = generate
    monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.Yes)

    dialog._on_reset_uploaded_design()

    assert dialog.model.factors == []
    assert dialog.model.additional_conditions == []
    assert dialog.model.has_uploaded_design() is False
    assert dialog.model.get_number_of_reactions() == 0
    assert dialog.reagent_table.columnCount() == 0
    assert dialog.stock_table.rowCount() == 0
    assert dialog.reset_upload_btn.isHidden() is True
    assert dialog.add_reagent_btn.isEnabled() is True
    assert dialog.model.unsaved_changes is True
    assert dialog.status_lbl.text() == "Imported design cleared. Add reagents or import another design."
    optimize.assert_not_called()
    generate.assert_not_called()
    dialog.close()


def test_reagent_columns_keep_default_width_then_compact_to_available_space(qapp):
    width_for = ExperimentDesignDialog._responsive_reagent_column_width

    assert width_for(3, 510) == 230
    assert width_for(4, 800) == 200
    assert width_for(8, 800) == 170
    assert width_for(4, 1200) == 230

    dialog = _build_real_dialog()
    dialog.reagent_table.setColumnCount(4)
    dialog.reagent_table.resize(800, 400)
    dialog._update_reagent_column_widths()
    expected = width_for(4, dialog.reagent_table.viewport().width())

    assert {dialog.reagent_table.columnWidth(column) for column in range(4)} == {expected}
    dialog.close()


def test_experiment_designer_transposes_reagent_fields_and_reorders_prior(qapp):
    dialog = _build_real_dialog()
    dialog.auto_update_chk.setChecked(False)
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
