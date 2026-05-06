from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
)

import View
from View import ExperimentDesignDialog


class _OptimizeModelStub:
    def __init__(self, responses, stock_rows=None):
        self._responses = list(responses)
        self.optimize_calls = 0
        self.generated = 0
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

    def get_stock_table_rows(self, include_fill=True):
        return list(self._stock_rows)

    def get_target_preview_map(self):
        return {}

    def get_reactions_dataframe(self):
        return []

    def get_worst_nonfill_volume_nL(self):
        return 0.0


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
