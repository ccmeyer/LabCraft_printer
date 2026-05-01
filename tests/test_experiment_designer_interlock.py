from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtGui import QCloseEvent
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
    QTableWidget,
)

from View import ExperimentDesignDialog


def _build_dialog_stub(gripper_loaded: bool, *, manual_assignments: bool = False):
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog._uploaded_design_active = False
    dialog._editing_locked_by_gripper = False
    dialog.status_lbl = QLabel("")

    dialog.add_reagent_btn = QPushButton()
    dialog.upload_design_btn = QPushButton()
    dialog.reset_upload_btn = QPushButton()
    dialog.run_btn = QPushButton()
    dialog.new_btn = QPushButton()
    dialog.save_btn = QPushButton()
    dialog.load_btn = QPushButton()
    dialog.finish_btn = QPushButton()
    dialog.rep_spin = QSpinBox()
    dialog.v_spin = QDoubleSpinBox()
    dialog.final_v_spin = QDoubleSpinBox()
    dialog.fill_name_edit = QLineEdit()
    dialog.fill_dv_spin = QDoubleSpinBox()
    dialog.allow_two_chk = QCheckBox()
    dialog.randomize_chk = QCheckBox()
    dialog.random_seed_spin = QSpinBox()
    dialog.subset_chk = QCheckBox()
    dialog.reduction_spin = QSpinBox()
    dialog.start_col_spin = QSpinBox()
    dialog.start_row_spin = QSpinBox()
    dialog.plate_format_combo = QComboBox()
    dialog.plate_format_combo.addItem("shallow-384_well_plate")

    dialog.reagent_table = QTableWidget(1, 12)
    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_STOCK_LABEL, QLineEdit())
    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_REAGENT, QComboBox())
    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_GROUP, QComboBox())
    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_HEAD_TYPE, QComboBox())
    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_STARTING, QDoubleSpinBox())
    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_TARGETS, QLineEdit())
    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_UNITS, QLineEdit())
    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_SET_STOCK, QLineEdit())
    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_MAX_STOCK, QLineEdit())
    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_DROPLET, QDoubleSpinBox())
    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_PRIOR, QLabel(""))
    dialog.reagent_table.setCellWidget(0, ExperimentDesignDialog.COL_DELETE, QPushButton())

    rack_model = SimpleNamespace(get_gripper_printer_head=lambda: object() if gripper_loaded else None)
    dialog.main_window = SimpleNamespace(
        complete_experiment_design=Mock(),
        model=SimpleNamespace(rack_model=rack_model),
    )
    dialog.model = SimpleNamespace(
        has_explicit_well_assignments=lambda: manual_assignments,
        save_experiment=Mock(),
    )
    return dialog


def _assert_mutating_controls_disabled(dialog):
    controls = [
        dialog.finish_btn,
        dialog.run_btn,
        dialog.add_reagent_btn,
        dialog.upload_design_btn,
        dialog.reset_upload_btn,
        dialog.rep_spin,
        dialog.allow_two_chk,
        dialog.randomize_chk,
        dialog.random_seed_spin,
        dialog.start_col_spin,
        dialog.start_row_spin,
        dialog.subset_chk,
        dialog.reduction_spin,
        dialog.plate_format_combo,
    ]
    for control in controls:
        assert control.isEnabled() is False


def test_experiment_designer_close_without_finish_does_not_apply(qapp):
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    QDialog.__init__(dialog)
    complete_mock = Mock()
    dialog.main_window = SimpleNamespace(
        complete_experiment_design=complete_mock,
        model=SimpleNamespace(rack_model=SimpleNamespace(gripper_updated=SimpleNamespace(disconnect=Mock()))),
    )
    dialog._auto_timer = SimpleNamespace(stop=Mock())
    dialog._gripper_lock_connection = None

    ExperimentDesignDialog.closeEvent(dialog, QCloseEvent())

    complete_mock.assert_not_called()


def test_experiment_designer_finish_calls_apply_once():
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog._editing_locked_by_gripper = False
    dialog._apply_requested = False
    dialog._on_optimize_and_generate = Mock()
    dialog._ensure_experiment_dir = Mock()
    dialog._set_status = Mock()
    dialog.accept = Mock()
    complete_mock = Mock()
    save_mock = Mock()
    dialog.main_window = SimpleNamespace(complete_experiment_design=complete_mock)
    dialog.model = SimpleNamespace(save_experiment=save_mock)

    ExperimentDesignDialog._on_finish(dialog)

    complete_mock.assert_called_once_with()
    save_mock.assert_called_once_with()
    assert dialog._apply_requested is True


def test_experiment_designer_finish_stops_when_capacity_check_fails():
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog._editing_locked_by_gripper = False
    dialog._apply_requested = False
    dialog._on_optimize_and_generate = Mock(return_value=False)
    dialog._ensure_experiment_dir = Mock()
    dialog._set_status = Mock()
    dialog.accept = Mock()
    complete_mock = Mock()
    save_mock = Mock()
    dialog.main_window = SimpleNamespace(complete_experiment_design=complete_mock)
    dialog.model = SimpleNamespace(save_experiment=save_mock)

    ExperimentDesignDialog._on_finish(dialog)

    complete_mock.assert_not_called()
    save_mock.assert_not_called()
    dialog.accept.assert_not_called()
    dialog._ensure_experiment_dir.assert_not_called()
    assert dialog._apply_requested is False


def test_experiment_designer_finish_surfaces_apply_errors_and_stays_open(monkeypatch, qapp):
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog._editing_locked_by_gripper = False
    dialog._apply_requested = False
    dialog._on_optimize_and_generate = Mock(return_value=True)
    dialog._ensure_experiment_dir = Mock()
    dialog.status_lbl = QLabel("")
    dialog._set_status = ExperimentDesignDialog._set_status.__get__(dialog, ExperimentDesignDialog)
    dialog.accept = Mock()
    warn = Mock()
    monkeypatch.setattr(QMessageBox, "warning", warn)

    complete_mock = Mock(side_effect=ValueError("Explicit well assignments are invalid for plate '96well-8x12' (8x12). Out of bounds for plate '96well-8x12' (8x12): G16."))
    save_mock = Mock()
    dialog.main_window = SimpleNamespace(complete_experiment_design=complete_mock)
    dialog.model = SimpleNamespace(save_experiment=save_mock)

    ExperimentDesignDialog._on_finish(dialog)

    warn.assert_called_once()
    dialog.accept.assert_not_called()
    assert dialog._apply_requested is False
    assert "G16" in dialog.status_lbl.text()
    assert "96well-8x12" in dialog.status_lbl.text()


def test_experiment_designer_locks_edit_actions_when_gripper_loaded(qapp):
    dialog = _build_dialog_stub(gripper_loaded=True)
    dialog._on_optimize_and_generate = Mock()
    dialog._ensure_experiment_dir = Mock()
    dialog.accept = Mock()

    ExperimentDesignDialog._refresh_all_lock_states(dialog)
    ExperimentDesignDialog._on_finish(dialog)

    assert dialog._editing_locked_by_gripper is True
    assert dialog.finish_btn.isEnabled() is False
    assert "view-only" in dialog.status_lbl.text()
    dialog.main_window.complete_experiment_design.assert_not_called()


def test_experiment_designer_unlocks_when_gripper_unloaded(qapp):
    gripper_loaded = {"value": True}
    dialog = _build_dialog_stub(gripper_loaded=True)
    dialog.main_window.model.rack_model = SimpleNamespace(
        get_gripper_printer_head=lambda: object() if gripper_loaded["value"] else None
    )

    ExperimentDesignDialog._refresh_all_lock_states(dialog)
    assert dialog.finish_btn.isEnabled() is False

    gripper_loaded["value"] = False
    ExperimentDesignDialog._refresh_all_lock_states(dialog)

    assert dialog._editing_locked_by_gripper is False
    assert dialog.finish_btn.isEnabled() is True


@pytest.mark.parametrize(
    "uploaded_active,manual_assignments,gripper_loaded",
    [
        (False, False, False),
        (True, False, False),
        (False, True, False),
        (True, True, False),
        (False, False, True),
        (True, False, True),
        (False, True, True),
        (True, True, True),
    ],
)
def test_experiment_designer_lock_precedence_matrix(
    qapp,
    uploaded_active,
    manual_assignments,
    gripper_loaded,
):
    dialog = _build_dialog_stub(gripper_loaded=gripper_loaded, manual_assignments=manual_assignments)
    dialog._uploaded_design_active = uploaded_active
    dialog.randomize_chk.setChecked(True)
    dialog.subset_chk.setChecked(True)

    ExperimentDesignDialog._refresh_all_lock_states(dialog)

    if gripper_loaded:
        _assert_mutating_controls_disabled(dialog)
        assert "view-only" in dialog.status_lbl.text()
        return

    assert dialog._editing_locked_by_gripper is False

    # Uploaded mode lock behavior
    assert dialog.add_reagent_btn.isEnabled() is (not uploaded_active)
    assert dialog.subset_chk.isEnabled() is (not uploaded_active)
    assert dialog.reduction_spin.isEnabled() is (not uploaded_active)

    # Manual assignment lock behavior
    assert dialog.rep_spin.isEnabled() is (not manual_assignments)
    assert dialog.randomize_chk.isEnabled() is (not manual_assignments)
    assert dialog.start_col_spin.isEnabled() is (not manual_assignments)
    assert dialog.start_row_spin.isEnabled() is (not manual_assignments)
    assert dialog.random_seed_spin.isEnabled() is (not manual_assignments)

    # Unaffected mutating controls remain enabled without gripper lock
    assert dialog.finish_btn.isEnabled() is True
    assert dialog.run_btn.isEnabled() is True


def test_experiment_designer_gripper_lock_dominates_uploaded_manual_modes(qapp):
    dialog = _build_dialog_stub(gripper_loaded=True, manual_assignments=True)
    dialog._uploaded_design_active = True
    dialog.randomize_chk.setChecked(True)
    dialog.subset_chk.setChecked(True)

    ExperimentDesignDialog._refresh_all_lock_states(dialog)

    assert dialog._editing_locked_by_gripper is True
    _assert_mutating_controls_disabled(dialog)
    assert "view-only" in dialog.status_lbl.text()
