from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
)

from View import ExperimentDesignDialog


class _OptimizeModelStub:
    def __init__(self, responses):
        self._responses = list(responses)
        self.optimize_calls = 0
        self.generated = 0

    def optimize_stock_solutions(self, **_kwargs):
        self.optimize_calls += 1
        if self._responses:
            return self._responses.pop(0)
        return {"best": True, "issues_by_key": {}, "two_stock_search_limited_keys": []}

    def generate_experiment(self):
        self.generated += 1

    def get_stock_table_rows(self, include_fill=True):
        return [
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

    def get_target_preview_map(self):
        return {}

    def get_reactions_dataframe(self):
        return []

    def get_worst_nonfill_volume_nL(self):
        return 0.0


def _build_dialog(*, fixed_text="", max_text="", responses=None):
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.color_dict = {"dark_red": "#8a0303"}
    dialog.model = _OptimizeModelStub(responses or [])
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
