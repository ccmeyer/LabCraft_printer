from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QLabel, QLineEdit, QTableWidget

from CalibrationMemoryStore import CalibrationMemoryStore
from Model import CURRENT_PROFILE, ExperimentModel, Model, PrinterHead, StockSolution
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
                "head_type_id": "nozzle_100um",
                "display_name": "100 um nozzle",
                "nominal_nozzle_diameter_um": 100.0,
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


def _bind_dialog_method(dialog, name):
    method = getattr(ExperimentDesignDialog, name)
    setattr(dialog, name, method.__get__(dialog, ExperimentDesignDialog))


def _build_dialog_stub(runtime_model):
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.runtime_model = runtime_model
    dialog.main_window = SimpleNamespace(model=runtime_model)
    dialog.model = ExperimentModel(prof=CURRENT_PROFILE)
    dialog.choice_groups = set()
    dialog.reagent_table = QTableWidget(0, 12)
    dialog._auto_timer = SimpleNamespace(start=lambda: None)
    dialog.default_droplet_volume_nL = 10.0
    dialog.color_dict = {"dark_red": "#8a0303"}
    for name in (
        "_bridge_get_runtime_model",
        "_list_known_reagent_identities",
        "_list_known_printer_head_types",
        "_resolve_design_reagent_identity",
        "_find_row_for_widget",
        "_combo_current_payload",
        "_build_known_reagent_selector",
        "_build_head_type_selector",
        "_format_prior_availability",
        "_resolve_reagent_selection_from_row",
        "_refresh_prior_availability_for_row",
        "_refresh_all_prior_availability",
        "_on_reagent_identity_changed",
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


def test_experiment_model_from_dict_keeps_legacy_rows_backward_compatible():
    model = ExperimentModel(prof=CURRENT_PROFILE)
    model.from_dict(
        {
            "metadata": {"name": "legacy"},
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


def test_experiment_designer_rebuild_model_persists_reagent_and_head_type(qapp):
    runtime_model = _RuntimeModelStub()
    dialog = _build_dialog_stub(runtime_model)

    dialog._add_reagent_row(
        name="Water stock",
        targets="0, 1",
        units="mM",
        droplet_nL=10.0,
        reagent_id="water",
        reagent_display_name="Water",
        intended_head_type_id="nozzle_100um",
        intended_head_type_display_name="100 um nozzle",
    )

    dialog._rebuild_model_from_table()

    option = dialog.model.factors[0].options[0]
    assert option.name == "Water stock"
    assert option.reagent_id == "water"
    assert option.reagent_display_name == "Water"
    assert option.intended_head_type_id == "nozzle_100um"
    assert option.intended_head_type_display_name == "100 um nozzle"


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
    label: QLabel = dialog.reagent_table.cellWidget(0, ExperimentDesignDialog.COL_PRIOR)

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
    label: QLabel = dialog.reagent_table.cellWidget(0, ExperimentDesignDialog.COL_PRIOR)

    assert preview["status"] == "memory_disabled"
    assert label.text() == "Memory disabled"
    assert "disabled" in label.toolTip().lower()


def test_load_reactions_from_model_applies_design_identity(experiment_model_factory, tmp_path):
    model = experiment_model_factory()
    model.calibration_memory_store = CalibrationMemoryStore(model=model, root_dir=tmp_path / "CalibrationMemory")
    model.calibration_memory_store.ensure_initialized()
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
