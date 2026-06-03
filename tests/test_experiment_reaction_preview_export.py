from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QFileDialog,
)

import View
from Model import AdditionalConditionSpec, CURRENT_PROFILE, ExperimentModel
from View import ExperimentDesignDialog, ReactionPreviewDialog


def _make_model():
    return ExperimentModel(prof=CURRENT_PROFILE)


def _configure_signal_design(em, *, replicates=2):
    em.factors = []
    em.add_additive(
        "Signal",
        [0.0, 1.0],
        "mM",
        10.0,
        forced_stock_conc=25.0,
    )
    em.set_metadata(
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        replicates=replicates,
        target_reaction_volume_nL=500.0,
        final_reaction_volume_nL=500.0,
        fill_reagent_name="Water",
        fill_droplet_volume_nL=10.0,
    )


def _preview_df():
    return pd.DataFrame(
        [
            {
                "global_index": 0,
                "design_source": "base",
                "additional_condition_label": "",
                "replicate": 1,
                "reaction_index": 0,
                "nonfill_volume_nL": 0.0,
                "fill_drops": 50,
                "Signal (mM)": 0.0,
            },
            {
                "global_index": 1,
                "design_source": "additional_condition",
                "additional_condition_label": "Control",
                "replicate": 1,
                "reaction_index": 0,
                "nonfill_volume_nL": 10.0,
                "fill_drops": 49,
                "Signal (mM)": 0.5,
            },
        ]
    )


def test_reaction_preview_dataframe_contains_generated_base_and_unique_rows():
    em = _make_model()
    _configure_signal_design(em, replicates=2)
    em.set_additional_conditions(
        [
            AdditionalConditionSpec(
                label="Midpoint",
                replicates=2,
                targets={("Signal", None): 0.5},
            )
        ]
    )

    assert em.optimize_stock_solutions(allow_two=False)["best"]
    em.generate_experiment()

    preview = em.get_reaction_preview_dataframe()

    assert preview.columns.tolist() == [
        "global_index",
        "design_source",
        "additional_condition_label",
        "replicate",
        "reaction_index",
        "nonfill_volume_nL",
        "fill_drops",
        "Signal (mM)",
    ]
    assert preview["global_index"].tolist() == list(range(6))
    assert preview["design_source"].tolist() == [
        "base",
        "base",
        "base",
        "base",
        "additional_condition",
        "additional_condition",
    ]
    assert preview["additional_condition_label"].tolist() == ["", "", "", "", "Midpoint", "Midpoint"]
    assert preview["replicate"].tolist() == [1, 1, 2, 2, 1, 2]
    assert preview["reaction_index"].tolist() == [0, 1, 0, 1, 0, 0]
    assert preview["Signal (mM)"].tolist() == pytest.approx([0.0, 1.0, 0.0, 1.0, 0.5, 0.5])
    assert preview["nonfill_volume_nL"].tolist() == pytest.approx([0.0, 20.0, 0.0, 20.0, 10.0, 10.0])
    assert preview["fill_drops"].tolist() == [50, 48, 50, 48, 49, 49]


def test_reaction_preview_dataframe_populates_targets_before_generation_and_unknown_columns():
    em = _make_model()
    em.factors = []
    em.add_additive("Buffer", [1.0], "mM", 10.0)
    em.add_choice_group("Reporter")
    em.add_choice_option("Reporter", "GFP", [2.0], "uM", 10.0)
    em.add_choice_option("Reporter", "mCherry", [3.0], "uM", 10.0)
    em.set_metadata(replicates=1)
    em.set_additional_conditions(
        [
            AdditionalConditionSpec(
                label="No reporter",
                replicates=1,
                targets={
                    ("Buffer", None): 0.0,
                    ("Reporter", "GFP"): 0.0,
                    ("UniqueOnly", None): 7.5,
                },
            )
        ]
    )

    preview = em.get_reaction_preview_dataframe()

    assert preview.columns.tolist() == [
        "global_index",
        "design_source",
        "additional_condition_label",
        "replicate",
        "reaction_index",
        "nonfill_volume_nL",
        "fill_drops",
        "Buffer (mM)",
        "Reporter/GFP (uM)",
        "Reporter/mCherry (uM)",
        "UniqueOnly",
    ]
    assert len(preview) == 3
    assert preview["nonfill_volume_nL"].tolist() == ["", "", ""]
    assert preview["fill_drops"].tolist() == ["", "", ""]
    assert preview["Reporter/GFP (uM)"].tolist() == pytest.approx([2.0, 0.0, 0.0])
    assert preview["Reporter/mCherry (uM)"].tolist() == pytest.approx([0.0, 3.0, 0.0])
    assert preview["Buffer (mM)"].tolist() == pytest.approx([1.0, 1.0, 0.0])
    assert preview["UniqueOnly"].tolist() == pytest.approx([0.0, 0.0, 7.5])


def test_reaction_preview_dataframe_without_unique_conditions_preserves_base_rows():
    em = _make_model()
    _configure_signal_design(em, replicates=1)

    preview = em.get_reaction_preview_dataframe()

    assert len(preview) == 2
    assert preview["design_source"].tolist() == ["base", "base"]
    assert preview["additional_condition_label"].tolist() == ["", ""]
    assert preview["Signal (mM)"].tolist() == pytest.approx([0.0, 1.0])


def test_reaction_preview_dialog_is_read_only_and_summarizes_rows(qapp):
    dialog = ReactionPreviewDialog(_preview_df())

    assert dialog.table.rowCount() == 2
    assert dialog.table.columnCount() == len(_preview_df().columns)
    assert "Total rows: 2" in dialog.status_lbl.text()
    assert "Base rows: 1" in dialog.status_lbl.text()
    assert "Unique-condition rows: 1" in dialog.status_lbl.text()
    assert "Expanded unique-condition replicates: 1" in dialog.status_lbl.text()
    assert not bool(dialog.table.item(0, 0).flags() & View.Qt.ItemFlag.ItemIsEditable)


def _make_preview_action_dialog(preview_df, tmp_path=None):
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.model = SimpleNamespace(
        experiment_dir_path=str(tmp_path) if tmp_path is not None else None,
        get_reaction_preview_dataframe=lambda: preview_df.copy(),
    )
    dialog._manual_assignments_active = lambda: False
    dialog._can_reuse_current_generated_design = lambda: False
    dialog._has_current_generated_design = lambda: True
    dialog._set_status = lambda message: setattr(dialog, "_last_status", message)
    dialog._optimization_calls = []

    def run_flow(**kwargs):
        dialog._optimization_calls.append(kwargs)
        return True, {"best": True}

    dialog._run_design_optimization_flow = run_flow
    return dialog


def test_preview_button_runs_generation_when_dirty_and_opens_dialog(qapp, monkeypatch):
    preview_df = _preview_df()
    dialog = _make_preview_action_dialog(preview_df)
    opened = {}

    class _FakeReactionPreviewDialog:
        def __init__(self, df, parent):
            opened["df"] = df.copy()
            opened["parent"] = parent

        def exec(self):
            opened["exec"] = True

    monkeypatch.setattr(View, "ReactionPreviewDialog", _FakeReactionPreviewDialog)

    ExperimentDesignDialog._on_preview_reactions(dialog)

    assert dialog._optimization_calls
    assert dialog._optimization_calls[0]["failure_title"] == "Optimization failed"
    assert opened["parent"] is dialog
    assert opened["exec"] is True
    pd.testing.assert_frame_equal(opened["df"], preview_df)


def test_export_button_runs_generation_when_dirty_and_writes_preview_csv(qapp, monkeypatch, tmp_path):
    preview_df = _preview_df()
    dialog = _make_preview_action_dialog(preview_df, tmp_path=tmp_path)
    export_path = tmp_path / "chosen_preview.csv"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(export_path), "CSV files (*.csv)"),
    )

    ExperimentDesignDialog._on_export_reaction_preview_csv(dialog)

    assert dialog._optimization_calls
    written = pd.read_csv(export_path)
    assert written["design_source"].tolist() == preview_df["design_source"].tolist()
    assert written["additional_condition_label"].fillna("").tolist() == preview_df["additional_condition_label"].tolist()
    assert written["Signal (mM)"].tolist() == pytest.approx(preview_df["Signal (mM)"].tolist())
    assert dialog._last_status.startswith("Reaction preview exported to:")


def test_export_cancel_does_not_write_file(qapp, monkeypatch, tmp_path):
    dialog = _make_preview_action_dialog(_preview_df(), tmp_path=tmp_path)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: ("", ""))

    ExperimentDesignDialog._on_export_reaction_preview_csv(dialog)

    assert not list(tmp_path.glob("*.csv"))


def _install_lock_widgets(dialog):
    dialog.add_reagent_btn = QPushButton()
    dialog.upload_design_btn = QPushButton()
    dialog.reset_upload_btn = QPushButton()
    dialog.unique_conditions_btn = QPushButton()
    dialog.preview_reactions_btn = QPushButton()
    dialog.export_reaction_preview_btn = QPushButton()
    dialog.run_btn = QPushButton()
    dialog.new_btn = QPushButton()
    dialog.save_btn = QPushButton()
    dialog.load_btn = QPushButton()
    dialog.finish_btn = QPushButton()
    dialog.rep_spin = QSpinBox()
    dialog.v_spin = QDoubleSpinBox()
    dialog.final_v_spin = QDoubleSpinBox()
    dialog.volume_tolerance_spin = QDoubleSpinBox()
    dialog.fill_name_edit = QLineEdit()
    dialog.fill_mode_combo = QComboBox()
    dialog.fill_dv_spin = QDoubleSpinBox()
    dialog.allow_two_chk = QCheckBox()
    dialog.randomize_chk = QCheckBox()
    dialog.random_seed_spin = QSpinBox()
    dialog.subset_chk = QCheckBox()
    dialog.reduction_spin = QSpinBox()
    dialog.start_col_spin = QSpinBox()
    dialog.start_row_spin = QSpinBox()
    dialog.plate_format_combo = QComboBox()
    dialog._iter_reagent_widgets = lambda: []
    dialog.status_lbl = QLabel("")
    dialog._set_status = ExperimentDesignDialog._set_status.__get__(dialog, ExperimentDesignDialog)


def test_preview_export_buttons_participate_in_busy_and_lock_states(qapp):
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    _install_lock_widgets(dialog)
    dialog.model = SimpleNamespace(_uploaded_well_ids=["A1"])

    busy_widgets = ExperimentDesignDialog._design_busy_widgets(dialog)
    assert dialog.preview_reactions_btn in busy_widgets
    assert dialog.export_reaction_preview_btn in busy_widgets

    dialog._can_reuse_current_generated_design = lambda: False
    ExperimentDesignDialog._apply_manual_assignment_lock_state(dialog)
    assert dialog.unique_conditions_btn.isEnabled() is False
    assert dialog.preview_reactions_btn.isEnabled() is False
    assert dialog.export_reaction_preview_btn.isEnabled() is False

    dialog.preview_reactions_btn.setEnabled(False)
    dialog.export_reaction_preview_btn.setEnabled(False)
    dialog._can_reuse_current_generated_design = lambda: True
    ExperimentDesignDialog._apply_manual_assignment_lock_state(dialog)
    assert dialog.unique_conditions_btn.isEnabled() is False
    assert dialog.preview_reactions_btn.isEnabled() is True
    assert dialog.export_reaction_preview_btn.isEnabled() is True

    dialog._progress_protected = True
    dialog._progress_lock_status_message = "locked"
    ExperimentDesignDialog._apply_progress_edit_lock_state(dialog)
    assert dialog.preview_reactions_btn.isEnabled() is False
    assert dialog.export_reaction_preview_btn.isEnabled() is False

    dialog.preview_reactions_btn.setEnabled(True)
    dialog.export_reaction_preview_btn.setEnabled(True)
    dialog.main_window = SimpleNamespace(
        model=SimpleNamespace(
            rack_model=SimpleNamespace(get_gripper_printer_head=lambda: object())
        )
    )
    ExperimentDesignDialog._apply_gripper_edit_lock_state(dialog)
    assert dialog.preview_reactions_btn.isEnabled() is False
    assert dialog.export_reaction_preview_btn.isEnabled() is False


def test_manual_assignment_dirty_guard_blocks_preview_action(qapp):
    dialog = _make_preview_action_dialog(_preview_df())
    dialog._manual_assignments_active = lambda: True
    dialog._can_reuse_current_generated_design = lambda: False
    dialog._run_design_optimization_flow = Mock()

    assert ExperimentDesignDialog._ensure_reaction_preview_current(dialog) is False
    dialog._run_design_optimization_flow.assert_not_called()
    assert "explicit well assignments" in dialog._last_status
