from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
)

import pandas as pd
import View
from Model import CURRENT_PROFILE, ExperimentModel
from View import ExperimentDesignDialog


class _OptimizeModelStub:
    def __init__(self, responses, stock_rows=None):
        self._responses = list(responses)
        self.optimize_calls = 0
        self.generated = 0
        self.plans_per_option = {}
        self._reactions_df = pd.DataFrame()
        self._stock_rows = list(
            stock_rows
            or [
                {
                    "factor_name": "AddA",
                    "option_name": "",
                    "stock_concentration": 10.0,
                    "delta_per_drop": 0.2,
                    "units": "mM",
                    "droplet_volume_nL": 10.0,
                    "max_per_rxn_nL": 20.0,
                    "total_droplets": 10,
                    "total_volume_uL": 1.0,
                }
            ]
        )

    def optimize_stock_solutions(self, **_kwargs):
        self.optimize_calls += 1
        if self._responses:
            return self._responses.pop(0)
        return {"best": True, "issues_by_key": {}, "two_stock_search_limited_keys": []}

    def generate_experiment(self):
        self.generated += 1
        self.plans_per_option = {("AddA", None): {"n_stocks": 1}}
        self._reactions_df = pd.DataFrame([{"well_id": "A1"}])

    def get_stock_table_rows(self, include_fill=True):
        return list(self._stock_rows)

    def get_target_preview_map(self):
        return {}

    def get_reactions_dataframe(self):
        return []

    def get_worst_nonfill_volume_nL(self):
        return 0.0

    def get_number_of_reactions(self):
        return int(len(self._reactions_df.index))


class _FakeTimer:
    def __init__(self):
        self.starts = 0
        self.stops = 0

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1


def _build_dialog(*, fixed_text="", max_text="", responses=None, stock_rows=None):
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.color_dict = {"dark_red": "#8a0303"}
    dialog.model = _OptimizeModelStub(responses or [], stock_rows=stock_rows)
    dialog.status_lbl = QLabel("")
    dialog.stock_table_status_lbl = QLabel("")
    dialog.stock_table = QTableWidget(0, 9)
    dialog.summary_lbl = QLabel("")
    dialog.allow_two_chk = QCheckBox()
    dialog.reagent_table = QTableWidget(1, 12)

    name_edit = QLineEdit("AddA")
    group_combo = QComboBox()
    group_combo.addItem(ExperimentDesignDialog.GROUP_ADDITIVE)
    target_edit = QLineEdit("0.1, 0.2")
    fixed_edit = QLineEdit(fixed_text)
    max_edit = QLineEdit(max_text)

    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_STOCK_LABEL, name_edit)
    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_GROUP, group_combo)
    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_TARGETS, target_edit)
    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_SET_STOCK, fixed_edit)
    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_MAX_STOCK, max_edit)

    dialog._rebuild_model_from_table = lambda: None
    dialog._refresh_all_prior_availability = lambda: None
    dialog._update_metadata_from_controls = lambda: None
    dialog._allow_two_setting = lambda: False
    dialog._validate_plate_capacity = lambda show_dialog=False: True
    dialog._update_summary_labels = lambda *args, **kwargs: None
    dialog._design_optimization_dirty = True
    dialog._last_optimization_result = None
    dialog._auto_update_suspended = False
    dialog._uploaded_design_active = False
    dialog._auto_timer = _FakeTimer()

    dialog.stock_table.insertRow(0)
    dialog.stock_table.setItem(0, 0, QTableWidgetItem("AddA"))
    return dialog, fixed_edit, max_edit


def test_invalid_fixed_stock_text_is_styled_and_skips_optimize(qapp):
    dialog, fixed_edit, _max_edit = _build_dialog(fixed_text="abc")

    ok, result = ExperimentDesignDialog._run_design_optimization_flow(dialog, show_failure_dialog=False)

    assert ok is False
    assert dialog.model.optimize_calls == 0
    assert fixed_edit.styleSheet() == "border:1px solid #8a0303;"
    assert "background-color" not in fixed_edit.styleSheet()
    assert "must be a positive number" in fixed_edit.toolTip()
    assert dialog.stock_table.rowCount() == 1
    assert "last valid stock plan" in dialog.stock_table_status_lbl.text()
    assert dialog.stock_table.styleSheet() == "QTableWidget { border:1px solid #8a0303; }"
    assert result["issues_by_key"][("AddA", None)][0]["code"] == "invalid_number"


def test_negative_fixed_stock_is_treated_as_invalid_input(qapp):
    dialog, fixed_edit, _max_edit = _build_dialog(fixed_text="-1")

    ok, result = ExperimentDesignDialog._run_design_optimization_flow(dialog, show_failure_dialog=False)

    assert ok is False
    assert dialog.model.optimize_calls == 0
    assert fixed_edit.styleSheet() == "border:1px solid #8a0303;"
    assert "must be greater than zero" in fixed_edit.toolTip()
    assert result["issues_by_key"][("AddA", None)][0]["code"] == "nonpositive_value"


def test_successful_optimization_marks_design_clean(qapp):
    dialog, _fixed_edit, _max_edit = _build_dialog(
        responses=[{"best": True, "issues_by_key": {}, "two_stock_search_limited_keys": []}]
    )
    dialog._design_optimization_dirty = True

    ok, result = ExperimentDesignDialog._run_design_optimization_flow(dialog, show_failure_dialog=False)

    assert ok is True
    assert result["best"] is True
    assert dialog.model.optimize_calls == 1
    assert dialog.model.generated == 1
    assert dialog._design_optimization_dirty is False
    assert dialog._last_optimization_result is result
    assert dialog._auto_timer.stops == 1


def test_failure_dialog_shows_detailed_issue_summary(qapp, monkeypatch):
    dialog, _fixed_edit, _max_edit = _build_dialog(
        responses=[
            {
                "best": None,
                "reason": "Generic optimizer failure",
                "issues_by_key": {
                    ("__uploaded_design__", None): [
                        {
                            "field": "volume_budget",
                            "severity": "error",
                            "code": "max_stock_volume_budget_exceeded",
                            "message": "Uploaded row A1 needs 1600 nL; top contributor is Reagent A.",
                        }
                    ]
                },
                "two_stock_search_limited_keys": [],
            }
        ]
    )
    captured = {}

    def capture_warning(_parent, title, text):
        captured["title"] = title
        captured["text"] = text

    monkeypatch.setattr(View.QMessageBox, "warning", capture_warning)

    ok, _result = ExperimentDesignDialog._run_design_optimization_flow(
        dialog,
        show_failure_dialog=True,
        failure_prefix="Could not optimize:\n",
    )

    assert ok is False
    assert captured["title"] == "Optimization failed"
    assert captured["text"].startswith("Could not optimize:\n")
    assert "Uploaded row A1 needs 1600 nL" in captured["text"]
    assert "Generic optimizer failure" not in captured["text"]


def test_import_wizard_loads_design_and_stock_tables(qapp):
    model = ExperimentModel(prof=CURRENT_PROFILE)
    wizard = View.ExperimentImportWizard(
        model,
        printed_volume_nL=500.0,
        final_volume_nL=1000.0,
        allow_two=False,
    )
    design_df = pd.DataFrame(
        {
            "well_id": ["A1", "A2"],
            "Reagent A mM": [1.0, 1.0],
            "Reagent B mM": [2.0, 2.0],
        }
    )
    stock_df = pd.DataFrame(
        {
            "reagent": ["Reagent A", "Reagent B"],
            "stock_conc": [10.0, 20.0],
            "units": ["mM", "mM"],
        }
    )

    wizard.load_design_dataframe(design_df, source_path="design.csv")
    wizard.load_max_stock_dataframe(stock_df, source_path="stocks.csv")

    assert wizard.composition_table.rowCount() == 1
    assert wizard.stock_table.rowCount() == 2
    assert wizard.report["composition_rows"][0]["count"] == 2
    assert wizard.report["composition_rows"][0]["total_required_volume_nL"] == 200.0
    assert wizard.apply_btn.isEnabled()


def test_import_wizard_volume_edits_recompute_feasibility(qapp):
    model = ExperimentModel(prof=CURRENT_PROFILE)
    wizard = View.ExperimentImportWizard(
        model,
        printed_volume_nL=600.0,
        final_volume_nL=1000.0,
        allow_two=False,
    )
    wizard.load_design_dataframe(
        pd.DataFrame({"well_id": ["A1"], "Reagent A mM": [4.0]}),
        source_path="design.csv",
    )
    wizard.load_max_stock_dataframe(
        pd.DataFrame({"reagent": ["Reagent A"], "stock_conc": [10.0], "units": ["mM"]}),
        source_path="stocks.csv",
    )

    assert wizard.report["composition_rows"][0]["status"] == "OK"

    wizard.printed_volume_spin.setValue(300.0)

    assert wizard.report["composition_rows"][0]["status"] == "OK"

    wizard.printed_volume_spin.editingFinished.emit()

    assert wizard.report["composition_rows"][0]["status"] == "Volume impossible"
    assert "Volume impossible" in wizard.status_lbl.text()


def test_import_wizard_passes_printed_volume_tolerance_to_report(qapp):
    class _CaptureModel:
        def __init__(self):
            self.calls = []

        def build_import_feasibility_report(self, *_args, **kwargs):
            self.calls.append(kwargs)
            return {
                "ok": True,
                "printed_volume_nL": kwargs.get("printed_volume_nL"),
                "printed_volume_tolerance_nL": kwargs.get("printed_volume_tolerance_nL"),
                "final_volume_nL": kwargs.get("final_volume_nL"),
                "reagent_specs": [],
                "composition_rows": [],
                "stock_rows": [],
                "issues": [],
                "missing_stock_rows": [],
                "unmatched_stock_rows": [],
                "status_counts": {},
                "max_stock_by_reagent": {},
            }

    model = _CaptureModel()
    wizard = View.ExperimentImportWizard(
        model,
        printed_volume_nL=500.0,
        printed_volume_tolerance_nL=25.0,
        final_volume_nL=1000.0,
        allow_two=False,
    )
    wizard.load_design_dataframe(pd.DataFrame({"well_id": ["A1"], "Reagent A mM": [1.0]}))

    assert model.calls[-1]["printed_volume_tolerance_nL"] == 25.0

    wizard.printed_volume_tolerance_spin.setValue(40.0)
    assert model.calls[-1]["printed_volume_tolerance_nL"] == 25.0

    wizard.printed_volume_tolerance_spin.editingFinished.emit()
    assert model.calls[-1]["printed_volume_tolerance_nL"] == 40.0


def test_import_wizard_status_colors_distinguish_warnings_from_errors(qapp):
    warning_wizard = View.ExperimentImportWizard(
        ExperimentModel(prof=CURRENT_PROFILE),
        printed_volume_nL=500.0,
        final_volume_nL=1000.0,
        allow_two=False,
    )
    warning_wizard.load_design_dataframe(
        pd.DataFrame({"well_id": ["A1"], "Reagent A mM": [1.0]}),
        source_path="design.csv",
    )

    warning_item = warning_wizard.composition_table.item(0, 0)
    assert warning_item.background().color().name() == "#7a5a00"
    assert warning_item.foreground().color().name() == "#ffffff"

    error_wizard = View.ExperimentImportWizard(
        ExperimentModel(prof=CURRENT_PROFILE),
        printed_volume_nL=500.0,
        final_volume_nL=1000.0,
        allow_two=False,
    )
    error_wizard.load_design_dataframe(
        pd.DataFrame({"well_id": ["A1"], "Reagent A mM": [10.0]}),
        source_path="design.csv",
    )
    error_wizard.load_max_stock_dataframe(
        pd.DataFrame({"reagent": ["Reagent A"], "stock_conc": [1.0], "units": ["mM"]}),
        source_path="stocks.csv",
    )

    error_item = error_wizard.composition_table.item(0, 0)
    assert error_wizard.report["composition_rows"][0]["status"] == "Volume impossible"
    assert error_item.background().color().name() == "#8b1e1e"
    assert error_item.foreground().color().name() == "#ffffff"
    assert warning_wizard.apply_btn.isEnabled()

    near_budget_wizard = View.ExperimentImportWizard(
        ExperimentModel(prof=CURRENT_PROFILE),
        printed_volume_nL=950.0,
        printed_volume_tolerance_nL=50.0,
        final_volume_nL=1000.0,
        allow_two=False,
    )
    near_budget_wizard.load_design_dataframe(
        pd.DataFrame({"well_id": ["B3"], "Reagent A mM": [5.0], "Reagent B mM": [5.0]}),
        source_path="design.csv",
    )
    near_budget_wizard.load_max_stock_dataframe(
        pd.DataFrame(
            {
                "reagent": ["Reagent A", "Reagent B"],
                "stock_conc": [10.0, 10.0],
                "units": ["mM", "mM"],
            }
        ),
        source_path="stocks.csv",
    )

    near_item = near_budget_wizard.composition_table.item(0, 0)
    assert near_budget_wizard.report["composition_rows"][0]["status"] == "Near budget"
    assert near_item.background().color().name() == "#7a5a00"
    assert near_item.foreground().color().name() == "#ffffff"
    assert near_budget_wizard.apply_btn.isEnabled()


def test_import_wizard_stock_plan_errors_are_red_and_disable_apply(qapp):
    class _ReportModel:
        def build_import_feasibility_report(self, *_args, **_kwargs):
            return {
                "ok": False,
                "printed_volume_nL": 500.0,
                "final_volume_nL": 1000.0,
                "reagent_specs": [{"name": "Reagent A", "units": "mM"}],
                "composition_rows": [
                    {
                        "label": "Composition 1",
                        "wells": ["A1"],
                        "count": 1,
                        "targets": {"Reagent A": 1.0},
                        "reagent_volumes_nL": {"Reagent A": 100.0},
                        "total_required_volume_nL": 100.0,
                        "remaining_printed_volume_nL": 400.0,
                        "status": "OK",
                    }
                ],
                "stock_rows": [
                    {
                        "reagent": "Reagent A",
                        "units": "mM",
                        "max_stock_conc": 10.0,
                        "ideal_stock_conc": None,
                        "delta_per_drop": None,
                        "target_min": 1.0,
                        "target_max": 1.0,
                        "target_span": 0.0,
                        "smallest_nonzero_target": 1.0,
                        "worst_max_stock_volume_nL": 100.0,
                        "smallest_useful_target_step": None,
                        "status": "Stock plan impossible",
                        "recommendation": "Max stock cannot support a single-stock plan.",
                    }
                ],
                "issues": [
                    {
                        "field": "max_stock",
                        "severity": "error",
                        "code": "max_stock_no_single_plan",
                        "message": "Max stock cannot support a single-stock plan.",
                        "reagent": "Reagent A",
                    }
                ],
                "missing_stock_rows": [],
                "unmatched_stock_rows": [],
                "status_counts": {"OK": 1},
                "max_stock_by_reagent": {"Reagent A": 10.0},
            }

    wizard = View.ExperimentImportWizard(
        _ReportModel(),
        printed_volume_nL=500.0,
        final_volume_nL=1000.0,
        allow_two=False,
    )
    wizard.load_design_dataframe(pd.DataFrame({"well_id": ["A1"], "Reagent A mM": [1.0]}))

    stock_item = wizard.stock_table.item(0, 0)
    assert stock_item.background().color().name() == "#8b1e1e"
    assert stock_item.foreground().color().name() == "#ffffff"
    assert not wizard.apply_btn.isEnabled()


def test_import_wizard_composition_table_layout_and_formatting(qapp):
    model = ExperimentModel(prof=CURRENT_PROFILE)
    wizard = View.ExperimentImportWizard(
        model,
        printed_volume_nL=10000.0,
        final_volume_nL=10000.0,
        allow_two=False,
    )
    wizard.load_design_dataframe(
        pd.DataFrame(
            {
                "well_id": ["A1"],
                "Very Long Reagent Name mM": [44.1],
                "Another Long Reagent mM": [3.55],
            }
        ),
        source_path="design.csv",
    )
    wizard.load_max_stock_dataframe(
        pd.DataFrame(
            {
                "reagent": ["Very Long Reagent Name", "Another Long Reagent"],
                "stock_conc": [200.0, 100.0],
                "units": ["mM", "mM"],
            }
        ),
        source_path="stocks.csv",
    )

    assert wizard.composition_table.textElideMode() == Qt.TextElideMode.ElideNone
    assert wizard.composition_table.columnWidth(3) == wizard.composition_table.columnWidth(4)
    assert "\n" in wizard.composition_table.horizontalHeaderItem(3).text()
    assert "..." not in wizard.composition_table.item(0, 3).text()
    assert wizard.composition_table.item(0, 5).text() == "2560"
    assert wizard.composition_table.item(0, 6).text() == "7440"


def test_upload_design_wizard_apply_mutates_model_once(qapp, monkeypatch):
    design_df = pd.DataFrame({"well_id": ["A1"], "Reagent A mM": [1.0]})
    constructed = {}

    class _FakeWizard:
        def __init__(self, *args, **kwargs):
            constructed["args"] = args
            constructed["kwargs"] = kwargs

        def exec(self):
            return QDialog.Accepted

        def get_apply_payload(self):
            return {
                "design_df": design_df,
                "source_path": "design.csv",
                "max_stock_by_reagent": {"Reagent A": 10.0},
                "printed_volume_nL": 750.0,
                "printed_volume_tolerance_nL": 35.0,
                "final_volume_nL": 1000.0,
                "allow_two": True,
            }

    class _ModelStub:
        def __init__(self):
            self.metadata = {}
            self.factors = []
            self.upload_calls = 0
            self.metadata_calls = []

        def set_metadata(self, **kwargs):
            self.metadata.update(kwargs)
            self.metadata_calls.append(kwargs)

        def set_uploaded_design_from_dataframe(self, df, **kwargs):
            self.upload_calls += 1
            self.uploaded_df = df.copy()
            self.upload_kwargs = kwargs
            option = type("Option", (), {"max_stock_conc": None})()
            self.factors = [type("Factor", (), {"name": "Reagent A", "kind": "additive", "options": [option]})()]

        def extract_uploaded_design_well_ids_from_dataframe(self, _df):
            return None

    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.model = _ModelStub()
    dialog.choice_groups = set()
    dialog._uploaded_design_active = False
    dialog._uploaded_design_path = None
    dialog.v_spin = QDoubleSpinBox()
    dialog.v_spin.setRange(1.0, 1_000_000.0)
    dialog.v_spin.setValue(500.0)
    dialog.final_v_spin = QDoubleSpinBox()
    dialog.final_v_spin.setRange(1.0, 1_000_000.0)
    dialog.final_v_spin.setValue(500.0)
    dialog.volume_tolerance_spin = QDoubleSpinBox()
    dialog.volume_tolerance_spin.setRange(0.0, 1_000_000.0)
    dialog.volume_tolerance_spin.setValue(25.0)
    dialog.allow_two_chk = QCheckBox()
    dialog._validate_uploaded_design_well_assignments = lambda _df: True
    dialog._load_factors_into_table = lambda: None
    dialog._update_metadata_from_controls = lambda: None
    run_calls = []
    dialog._design_optimization_dirty = True
    dialog._auto_timer = _FakeTimer()

    def fake_run_design_optimization_flow(**kwargs):
        run_calls.append(kwargs)
        ExperimentDesignDialog._mark_design_optimization_clean(dialog, {"best": True})
        return True, {"best": True}

    dialog._run_design_optimization_flow = fake_run_design_optimization_flow

    monkeypatch.setattr(View, "ExperimentImportWizard", _FakeWizard)

    ExperimentDesignDialog._on_upload_design(dialog)

    assert constructed["kwargs"]["printed_volume_nL"] == 500.0
    assert constructed["kwargs"]["printed_volume_tolerance_nL"] == 25.0
    assert dialog.model.upload_calls == 1
    assert dialog.model.upload_kwargs["source_path"] == "design.csv"
    assert dialog.model.factors[0].options[0].max_stock_conc == 10.0
    assert dialog.model.metadata["target_reaction_volume_nL"] == 750.0
    assert dialog.model.metadata["printed_volume_tolerance_nL"] == 35.0
    assert dialog.model.metadata["final_reaction_volume_nL"] == 1000.0
    assert dialog.model.metadata["allow_two_stock_solutions"] is True
    assert len(run_calls) == 1
    assert dialog._design_optimization_dirty is False


def _build_finish_dialog():
    class _FinishModel:
        def __init__(self):
            self.plans_per_option = {("AddA", None): {"n_stocks": 1}}
            self._reactions_df = pd.DataFrame([{"well_id": "A1"}])
            self.save_calls = 0
            self.experiment_file_path = "experiment_design.json"
            self.experiment_dir_path = "experiment"

        def get_number_of_reactions(self):
            return 1

        def save_experiment(self):
            self.save_calls += 1

    class _MainWindow:
        def __init__(self):
            self.complete_calls = 0

        def complete_experiment_design(self, **kwargs):
            self.complete_calls += 1
            self.complete_kwargs = kwargs

    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.model = _FinishModel()
    dialog.main_window = _MainWindow()
    dialog._editing_locked_by_gripper = False
    dialog._progress_protected = True
    dialog._progress_reset_confirmed = False
    dialog._preserve_progress_on_finish = False
    dialog._apply_requested = False
    dialog._uploaded_design_active = True
    dialog._auto_update_suspended = False
    dialog._auto_timer = _FakeTimer()
    dialog._design_optimization_dirty = False
    dialog._validate_plate_capacity = lambda show_dialog=True: True
    dialog._refresh_stock_table = lambda: None
    dialog._update_summary_labels = lambda *args, **kwargs: None
    dialog._apply_target_color_state = lambda: None
    dialog._ensure_experiment_dir = lambda: None
    dialog._persist_design_identity_registry_entries = lambda: None
    dialog._set_status = lambda msg: setattr(dialog, "_last_status", msg)
    dialog.accept = lambda: setattr(dialog, "_accepted", True)
    return dialog


def test_finish_reuses_clean_generated_design_without_reoptimizing(qapp):
    dialog = _build_finish_dialog()
    optimize_calls = []
    dialog._on_optimize_and_generate = lambda **kwargs: optimize_calls.append(kwargs) or True

    ExperimentDesignDialog._on_finish(dialog)

    assert optimize_calls == []
    assert dialog.model.save_calls == 1
    assert dialog.main_window.complete_calls == 1
    assert dialog._apply_requested is True
    assert getattr(dialog, "_accepted", False) is True


def test_design_edit_marks_dirty_and_finish_reoptimizes(qapp):
    dialog = _build_finish_dialog()
    optimize_calls = []
    dialog._on_optimize_and_generate = lambda **kwargs: optimize_calls.append(kwargs) or True

    ExperimentDesignDialog._schedule_auto_update(dialog)
    ExperimentDesignDialog._on_finish(dialog)

    assert dialog._design_optimization_dirty is True
    assert dialog._auto_timer.starts == 1
    assert len(optimize_calls) == 1
    assert dialog.model.save_calls == 1


def test_schedule_auto_update_ignores_bulk_population(qapp):
    dialog = _build_finish_dialog()
    dialog._design_optimization_dirty = False
    dialog._auto_update_suspended = True

    ExperimentDesignDialog._schedule_auto_update(dialog)

    assert dialog._design_optimization_dirty is False
    assert dialog._auto_timer.starts == 0


def test_load_factors_into_table_suspends_auto_update(qapp):
    option = type(
        "Option",
        (),
        {
            "name": "AddA",
            "targets": [1.0],
            "units": "mM",
            "droplet_nL": 10.0,
        },
    )()
    factor = type("Factor", (), {"name": "AddA", "kind": "additive", "options": [option]})()
    dialog = _build_finish_dialog()
    dialog.model.factors = [factor]
    dialog.choice_groups = set()
    dialog._design_optimization_dirty = False
    dialog._auto_update_suspended = False
    dialog._clear_reagent_rows = lambda: None
    dialog._sync_reagent_tables_geometry = lambda: None
    dialog._refresh_all_prior_availability = lambda: None
    add_calls = []

    def fake_add_reagent_row(**kwargs):
        add_calls.append(kwargs)
        ExperimentDesignDialog._schedule_auto_update(dialog)

    dialog._add_reagent_row = fake_add_reagent_row

    ExperimentDesignDialog._load_factors_into_table(dialog)

    assert len(add_calls) == 1
    assert dialog._auto_update_suspended is False
    assert dialog._design_optimization_dirty is False
    assert dialog._auto_timer.starts == 0


def test_upload_design_wizard_cancel_leaves_model_unchanged(qapp, monkeypatch):
    class _FakeWizard:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return QDialog.Rejected

    class _ModelStub:
        def __init__(self):
            self.upload_calls = 0

        def set_uploaded_design_from_dataframe(self, *_args, **_kwargs):
            self.upload_calls += 1

    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.model = _ModelStub()
    dialog.v_spin = QDoubleSpinBox()
    dialog.v_spin.setRange(1.0, 1_000_000.0)
    dialog.v_spin.setValue(500.0)
    dialog.final_v_spin = QDoubleSpinBox()
    dialog.final_v_spin.setRange(1.0, 1_000_000.0)
    dialog.final_v_spin.setValue(500.0)
    dialog.allow_two_chk = QCheckBox()

    monkeypatch.setattr(View, "ExperimentImportWizard", _FakeWizard)

    ExperimentDesignDialog._on_upload_design(dialog)

    assert dialog.model.upload_calls == 0


def test_invalid_max_stock_keeps_table_stale_until_fixed(qapp):
    dialog, _fixed_edit, max_edit = _build_dialog(
        responses=[
            {"best": True, "issues_by_key": {}, "two_stock_search_limited_keys": []},
            {"best": True, "issues_by_key": {}, "two_stock_search_limited_keys": []},
        ]
    )

    ok, _ = ExperimentDesignDialog._run_design_optimization_flow(dialog, show_failure_dialog=False)
    assert ok is True
    assert dialog.stock_table.rowCount() == 1
    assert dialog.stock_table_status_lbl.text() == ""
    assert dialog.stock_table.styleSheet() == ""

    max_edit.setText("0")
    ok, _ = ExperimentDesignDialog._run_design_optimization_flow(dialog, show_failure_dialog=False)
    assert ok is False
    assert max_edit.styleSheet() == "border:1px solid #8a0303;"
    assert dialog.stock_table.rowCount() == 1
    assert "last valid stock plan" in dialog.stock_table_status_lbl.text()
    assert dialog.stock_table.styleSheet() == "QTableWidget { border:1px solid #8a0303; }"

    max_edit.setText("5")
    ok, _ = ExperimentDesignDialog._run_design_optimization_flow(dialog, show_failure_dialog=False)
    assert ok is True
    assert max_edit.styleSheet() == ""
    assert dialog.stock_table_status_lbl.text() == ""
    assert dialog.stock_table.styleSheet() == ""


def test_refresh_stock_table_formats_stock_concentration_to_three_significant_figures(qapp):
    dialog, _fixed_edit, _max_edit = _build_dialog(
        stock_rows=[
            {
                "factor_name": "AddA",
                "option_name": "",
                "stock_concentration": 99.696,
                "delta_per_drop": 0.2,
                "units": "mM",
                "droplet_volume_nL": 10.0,
                "max_per_rxn_nL": 20.0,
                "total_droplets": 10,
                "total_volume_uL": 1.0,
            },
            {
                "factor_name": "AddB",
                "option_name": "",
                "stock_concentration": 3.465,
                "delta_per_drop": 0.1,
                "units": "mM",
                "droplet_volume_nL": 10.0,
                "max_per_rxn_nL": 10.0,
                "total_droplets": 5,
                "total_volume_uL": 0.5,
            },
        ]
    )

    ExperimentDesignDialog._refresh_stock_table(dialog)

    assert dialog.stock_table.item(0, 2).text() == "99.7"
    assert dialog.stock_table.item(1, 2).text() == "3.47"
    assert dialog.stock_table.item(0, 3).text() == "0.2"
