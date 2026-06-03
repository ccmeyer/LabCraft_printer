from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
)

import View
from Model import AdditionalConditionSpec, CURRENT_PROFILE, ExperimentModel
from View import AdditionalConditionsDialog, ExperimentDesignDialog


def _column_specs():
    return [
        {"key": ("Buffer", None), "label": "Buffer", "units": "mM"},
        {"key": ("Reporter", "GFP"), "label": "Reporter/GFP", "units": "uM"},
    ]


def test_unique_conditions_dialog_collects_tuple_keys_blank_zeros_and_replicates(qapp):
    dialog = AdditionalConditionsDialog(_column_specs(), [])
    dialog._add_empty_row()

    dialog.table.item(0, 0).setText("No reporter")
    dialog.table.item(0, 1).setText("")
    dialog.table.item(0, 2).setText("1.5")
    dialog.table.cellWidget(0, 3).setValue(3)

    conditions = dialog.get_conditions()

    assert len(conditions) == 1
    assert conditions[0].label == "No reporter"
    assert conditions[0].replicates == 3
    assert conditions[0].targets == {
        ("Buffer", None): 0.0,
        ("Reporter", "GFP"): 1.5,
    }
    assert dialog.table.horizontalHeaderItem(1).text() == "Buffer (mM)"
    assert dialog.table.horizontalHeaderItem(2).text() == "Reporter/GFP (uM)"


@pytest.mark.parametrize("bad_text", ["bad", "-0.1", "nan", "inf"])
def test_unique_conditions_dialog_rejects_invalid_target_cells(qapp, monkeypatch, bad_text):
    dialog = AdditionalConditionsDialog(_column_specs(), [])
    dialog._add_empty_row()
    dialog.table.item(0, 1).setText(bad_text)
    warn = Mock()
    monkeypatch.setattr(QMessageBox, "warning", warn)

    dialog.accept()

    warn.assert_called_once()
    assert dialog.result() != QDialog.Accepted
    assert dialog._accepted_conditions is None


def test_unique_conditions_dialog_round_trips_existing_rows_and_unknown_columns(qapp):
    specs = _column_specs() + [
        {"key": ("MissingFactor", None), "label": "Missing: MissingFactor", "units": "", "missing": True}
    ]
    existing = [
        AdditionalConditionSpec(
            label="Known control",
            replicates=2,
            targets={
                ("Buffer", None): 2.0,
                ("Reporter", "GFP"): 0.0,
                ("MissingFactor", None): 4.5,
            },
        )
    ]

    dialog = AdditionalConditionsDialog(specs, existing)

    assert dialog.table.rowCount() == 1
    assert dialog.table.horizontalHeaderItem(3).text() == "Missing: MissingFactor"
    conditions = dialog.get_conditions()
    assert conditions[0].label == "Known control"
    assert conditions[0].replicates == 2
    assert conditions[0].targets == existing[0].targets


def test_experiment_dialog_column_specs_include_additives_choices_and_missing_saved_keys(qapp):
    model = ExperimentModel(prof=CURRENT_PROFILE)
    model.add_additive("Buffer", [0.0, 1.0], "mM", 10.0)
    model.add_choice_group("Reporter")
    model.add_choice_option("Reporter", "GFP", [0.0, 2.0], "uM", 10.0)
    model.set_additional_conditions(
        [
            AdditionalConditionSpec(
                label="Saved missing",
                replicates=1,
                targets={("Other", None): 3.0},
            )
        ]
    )
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.model = model

    specs = ExperimentDesignDialog._current_additional_condition_column_specs(dialog)

    assert [spec["key"] for spec in specs] == [
        ("Buffer", None),
        ("Reporter", "GFP"),
        ("Other", None),
    ]
    assert specs[-1]["label"] == "Missing: Other"
    assert specs[-1]["missing"] is True


def test_on_unique_conditions_applies_conditions_marks_dirty_and_updates_button(qapp, monkeypatch):
    model = ExperimentModel(prof=CURRENT_PROFILE)
    model.add_additive("Signal", [0.0, 1.0], "mM", 10.0)
    accepted = [
        AdditionalConditionSpec(
            label="Control",
            replicates=2,
            targets={("Signal", None): 0.0},
        )
    ]
    constructed = {}

    class _FakeAdditionalConditionsDialog:
        def __init__(self, column_specs, conditions, parent):
            constructed["column_specs"] = column_specs
            constructed["conditions"] = conditions
            constructed["parent"] = parent

        def exec(self):
            return QDialog.Accepted

        def get_conditions(self):
            return accepted

    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.model = model
    dialog.unique_conditions_btn = QPushButton("Unique Conditions...")
    dialog.status_lbl = QLabel("")
    dialog._editing_locked_by_gripper = False
    dialog._progress_protected = False
    dialog._manual_assignments_active = lambda: False
    dialog._rebuild_model_from_table = lambda: None
    dialog._refresh_all_lock_states = lambda: None
    dialog._schedule_calls = 0

    def schedule():
        dialog._schedule_calls += 1
        dialog._design_optimization_dirty = True

    dialog._schedule_auto_update = schedule
    monkeypatch.setattr(View, "AdditionalConditionsDialog", _FakeAdditionalConditionsDialog)

    ExperimentDesignDialog._on_unique_conditions(dialog)

    assert constructed["column_specs"][0]["key"] == ("Signal", None)
    stored = model.get_additional_conditions()
    assert len(stored) == 1
    assert stored[0].label == "Control"
    assert stored[0].replicates == 2
    assert dialog._schedule_calls == 1
    assert dialog._design_optimization_dirty is True
    assert dialog.unique_conditions_btn.text() == "Unique Conditions (1)..."
    assert "2 extra reaction" in dialog.unique_conditions_btn.toolTip()


def test_unique_conditions_button_count_refreshes_after_new_experiment(qapp):
    model = ExperimentModel(prof=CURRENT_PROFILE)
    model.set_additional_conditions(
        [
            AdditionalConditionSpec(
                label="Control",
                replicates=3,
                targets={("Signal", None): 0.0},
            )
        ]
    )

    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.model = model
    dialog.unique_conditions_btn = QPushButton("Unique Conditions...")
    dialog.exp_name_edit = QLineEdit("Old")
    dialog.rep_spin = QSpinBox()
    dialog.v_spin = QDoubleSpinBox()
    dialog.v_spin.setRange(1.0, 1_000_000.0)
    dialog.volume_tolerance_spin = QDoubleSpinBox()
    dialog.volume_tolerance_spin.setRange(0.0, 1_000_000.0)
    dialog.fill_name_edit = QLineEdit("Water")
    dialog.fill_mode_combo = QComboBox()
    dialog.fill_dv_spin = QDoubleSpinBox()
    dialog.fill_dv_spin.setRange(1.0, 1_000_000.0)
    dialog.allow_two_chk = QCheckBox()
    dialog.randomize_chk = QCheckBox()
    dialog.random_seed_spin = QSpinBox()
    dialog.subset_chk = QCheckBox()
    dialog.reduction_spin = QSpinBox()
    dialog.start_col_spin = QSpinBox()
    dialog.start_row_spin = QSpinBox()
    dialog.choice_groups = set()
    dialog._progress_reset_confirmed = False
    dialog._set_progress_protection = lambda protected, status=None: None
    dialog._load_factors_into_table = lambda: None
    dialog._sync_controls_from_model = lambda: None
    dialog._refresh_stock_table = lambda: None
    dialog._update_summary_labels = lambda: None
    dialog._refresh_all_prior_availability = lambda: None
    dialog._set_status = lambda message: setattr(dialog, "_last_status", message)

    ExperimentDesignDialog._update_unique_conditions_button_label(dialog)
    assert dialog.unique_conditions_btn.text() == "Unique Conditions (1)..."

    ExperimentDesignDialog._on_new_experiment(dialog)

    assert model.get_additional_conditions() == []
    assert dialog.unique_conditions_btn.text() == "Unique Conditions..."


def test_unique_conditions_button_lock_states(qapp):
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.model = SimpleNamespace(_uploaded_well_ids=["A1"])
    dialog.unique_conditions_btn = QPushButton("Unique Conditions...")
    dialog.rep_spin = QSpinBox()
    dialog.randomize_chk = QCheckBox()
    dialog.random_seed_spin = QSpinBox()
    dialog.start_col_spin = QSpinBox()
    dialog.start_row_spin = QSpinBox()
    dialog.plate_format_combo = QComboBox()

    ExperimentDesignDialog._apply_manual_assignment_lock_state(dialog)
    assert dialog.unique_conditions_btn.isEnabled() is False

    dialog.model = SimpleNamespace(_uploaded_well_ids=[])
    dialog.unique_conditions_btn.setEnabled(True)
    dialog._progress_protected = True
    dialog._progress_lock_status_message = "locked"
    dialog.status_lbl = QLabel("")
    dialog._set_status = ExperimentDesignDialog._set_status.__get__(dialog, ExperimentDesignDialog)
    dialog._iter_reagent_widgets = lambda: []
    dialog.add_reagent_btn = QPushButton()
    dialog.upload_design_btn = QPushButton()
    dialog.reset_upload_btn = QPushButton()
    dialog.run_btn = QPushButton()
    dialog.save_btn = QPushButton()
    dialog.v_spin = QDoubleSpinBox()
    dialog.final_v_spin = QDoubleSpinBox()
    dialog.volume_tolerance_spin = QDoubleSpinBox()
    dialog.fill_name_edit = QLineEdit()
    dialog.fill_mode_combo = QComboBox()
    dialog.fill_dv_spin = QDoubleSpinBox()
    dialog.allow_two_chk = QCheckBox()
    dialog.subset_chk = QCheckBox()
    dialog.reduction_spin = QSpinBox()

    ExperimentDesignDialog._apply_progress_edit_lock_state(dialog)
    assert dialog.unique_conditions_btn.isEnabled() is False

    dialog.unique_conditions_btn.setEnabled(True)
    dialog._is_gripper_loaded = lambda: True
    dialog.new_btn = QPushButton()
    dialog.load_btn = QPushButton()
    dialog.finish_btn = QPushButton()

    ExperimentDesignDialog._apply_gripper_edit_lock_state(dialog)
    assert dialog.unique_conditions_btn.isEnabled() is False
