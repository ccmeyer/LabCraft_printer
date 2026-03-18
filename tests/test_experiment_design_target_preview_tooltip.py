from PySide6.QtWidgets import QComboBox, QLineEdit, QTableWidget

from View import ExperimentDesignDialog


class _PreviewModelStub:
    def __init__(self, preview_map):
        self._preview_map = dict(preview_map)

    def get_target_preview_map(self):
        return dict(self._preview_map)


def _build_dialog(preview_map, *, forced_stock_text="35", reagent_name="AddA", group_name=None):
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.model = _PreviewModelStub(preview_map)
    dialog.color_dict = {"dark_red": "#8a0303"}
    dialog.reagent_table = QTableWidget(1, 12)

    name_edit = QLineEdit(reagent_name)
    group_combo = QComboBox()
    group_combo.addItem(ExperimentDesignDialog.GROUP_ADDITIVE)
    chosen_group = group_name or ExperimentDesignDialog.GROUP_ADDITIVE
    if chosen_group != ExperimentDesignDialog.GROUP_ADDITIVE:
        group_combo.addItem(chosen_group)
    group_combo.setCurrentText(chosen_group)
    stock_edit = QLineEdit(forced_stock_text)
    target_edit = QLineEdit("0.001, 0.149")

    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_STOCK_LABEL, name_edit)
    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_GROUP, group_combo)
    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_SET_STOCK, stock_edit)
    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_TARGETS, target_edit)
    return dialog, target_edit


def test_apply_target_color_state_shows_tooltip_for_auto_stock(qapp):
    rows = [
        {
            "requested_final": 0.149,
            "achieved_final": 0.168,
            "droplets": 2,
            "signed_error": 0.019,
            "reachable": True,
            "reason": "nearest_achievable",
            "stock_concentration": 35.0,
            "units": "mM",
            "plan_mode": "auto",
        }
    ]
    dialog, target_edit = _build_dialog({("AddA", None): rows}, forced_stock_text="")

    ExperimentDesignDialog._apply_target_color_state(dialog)

    assert "Achievable with stock 35 mM:" in target_edit.toolTip()
    assert target_edit.styleSheet() == ""


def test_apply_target_color_state_shows_tooltip_for_reachable_forced_stock(qapp):
    rows = [
        {
            "requested_final": 0.149,
            "achieved_final": 0.168,
            "droplets": 2,
            "signed_error": 0.019,
            "reachable": True,
            "reason": "nearest_achievable",
            "stock_concentration": 35.0,
            "units": "mM",
            "plan_mode": "fixed",
        },
        {
            "requested_final": 0.192,
            "achieved_final": 0.168,
            "droplets": 2,
            "signed_error": -0.024,
            "reachable": True,
            "reason": "nearest_achievable",
            "stock_concentration": 35.0,
            "units": "mM",
            "plan_mode": "fixed",
        },
    ]
    dialog, target_edit = _build_dialog({("AddA", None): rows})

    ExperimentDesignDialog._apply_target_color_state(dialog)

    tip = target_edit.toolTip()
    assert target_edit.styleSheet() == ""
    assert "Achievable with fixed stock 35 mM:" in tip
    assert "0.149 -> 0.168 (2 drops, +0.019)" in tip
    assert "0.192 -> 0.168 (2 drops, -0.024)" in tip


def test_apply_target_color_state_marks_unreachable_forced_stock_in_red(qapp):
    rows = [
        {
            "requested_final": 0.001,
            "achieved_final": 0.0,
            "droplets": 0,
            "signed_error": -0.001,
            "reachable": False,
            "reason": "rounds_to_zero_drops",
            "stock_concentration": 35.0,
            "units": "mM",
            "plan_mode": "fixed",
        },
        {
            "requested_final": 0.149,
            "achieved_final": 0.168,
            "droplets": 2,
            "signed_error": 0.019,
            "reachable": True,
            "reason": "nearest_achievable",
            "stock_concentration": 35.0,
            "units": "mM",
            "plan_mode": "fixed",
        },
    ]
    dialog, target_edit = _build_dialog({("AddA", None): rows})

    ExperimentDesignDialog._apply_target_color_state(dialog)

    tip = target_edit.toolTip()
    assert "#8a0303" in target_edit.styleSheet()
    assert "0.001 -> 0 (0 drops, -0.001); 0 drops; positive targets may not round to zero" in tip
    assert "0.149 -> 0.168 (2 drops, +0.019)" in tip


def test_apply_target_color_state_formats_two_stock_tooltip(qapp):
    rows = [
        {
            "requested_final": 0.1,
            "achieved_final": 0.1,
            "droplets": (1, 0),
            "signed_error": 0.0,
            "reachable": True,
            "reason": "nearest_achievable",
            "stock_concentration": (5.0, 10.0),
            "units": "mM",
            "plan_mode": "auto",
            "n_stocks": 2,
        },
        {
            "requested_final": 0.2,
            "achieved_final": 0.2,
            "droplets": (0, 1),
            "signed_error": 0.0,
            "reachable": True,
            "reason": "nearest_achievable",
            "stock_concentration": (5.0, 10.0),
            "units": "mM",
            "plan_mode": "auto",
            "n_stocks": 2,
        },
    ]
    dialog, target_edit = _build_dialog({("AddA", None): rows}, forced_stock_text="")

    ExperimentDesignDialog._apply_target_color_state(dialog)

    tip = target_edit.toolTip()
    assert "Achievable with 2 stocks 5 mM + 10 mM:" in tip
    assert "0.1 -> 0.1 (1 + 0 drop, +0)" in tip
    assert "0.2 -> 0.2 (0 + 1 drop, +0)" in tip
