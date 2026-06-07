from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QLabel, QPushButton, QSpinBox

import View
from Model import WellPlate
from View import ExperimentDesignDialog, WellSelectionDialog, WellSelectionGridWidget


def _mouse_event(event_type, pos, button, buttons=None):
    point = QPointF(pos)
    return QMouseEvent(
        event_type,
        point,
        point,
        point,
        button,
        button if buttons is None else buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def _plate(rows=3, cols=3, excluded=None):
    plate_data = [{
        "name": "test-plate",
        "rows": rows,
        "columns": cols,
        "spacing": 10,
        "default": True,
        "calibrations": {},
    }]
    well_plate = WellPlate(plate_data, "unused")
    well_plate.excluded_wells = set(excluded or set())
    return well_plate


class _ExperimentModelStub:
    def __init__(self, included_wells=None, *, manual=False):
        self.metadata = {"well_selection": {"mode": "start_offset", "included_wells": None}}
        self._included_wells = included_wells
        self._manual = manual
        self.set_well_selection = Mock(side_effect=self._set_well_selection)

    def _set_well_selection(self, included_wells):
        self._included_wells = list(included_wells)
        self.metadata["well_selection"] = {
            "mode": "custom",
            "included_wells": list(included_wells),
        }

    def get_auto_assignment_included_wells(self):
        return list(self._included_wells) if self._included_wells is not None else None

    def has_explicit_well_assignments(self):
        return self._manual


def _dialog_stub(*, included_wells=None, manual=False, excluded=None, rows=3, cols=3, start_row=0, start_col=0):
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.model = _ExperimentModelStub(included_wells=included_wells, manual=manual)
    dialog.main_window = SimpleNamespace(model=SimpleNamespace(well_plate=_plate(rows, cols, excluded=excluded)))
    dialog.plate_format_combo = QComboBox()
    dialog.plate_format_combo.addItem("test-plate")
    dialog.start_row_spin = QSpinBox()
    dialog.start_row_spin.setValue(start_row)
    dialog.start_col_spin = QSpinBox()
    dialog.start_col_spin.setValue(start_col)
    dialog.status_lbl = QLabel("")
    dialog.summary_lbl = QLabel("")
    dialog.well_selection_summary_lbl = QLabel("")
    dialog.well_selection_btn = QPushButton()
    dialog._progress_protected = False
    dialog._editing_locked_by_gripper = False
    dialog._set_status = ExperimentDesignDialog._set_status.__get__(dialog, ExperimentDesignDialog)
    dialog._update_summary_labels = Mock()
    dialog._schedule_auto_update = Mock()
    dialog._refresh_all_lock_states = Mock()
    return dialog


def test_well_selection_grid_rectangle_helper_selects_region(qapp):
    grid = WellSelectionGridWidget(3, 3)

    grid.apply_rect_selection("A1", "B2", selected=True)

    assert grid.selected_well_ids() == ["A1", "A2", "B1", "B2"]


def test_well_selection_grid_rectangle_clear_removes_region(qapp):
    grid = WellSelectionGridWidget(3, 3)
    grid.apply_rect_selection("A1", "C3", selected=True)

    grid.apply_rect_selection("A1", "B2", selected=False)

    assert grid.selected_well_ids() == ["A3", "B3", "C1", "C2", "C3"]


def test_well_selection_grid_disabled_wells_are_not_selected(qapp):
    grid = WellSelectionGridWidget(2, 2, disabled_wells=["A1", "B2"])

    grid.apply_rect_selection("A1", "B2", selected=True)
    grid.select_all()
    press = _mouse_event(
        QEvent.Type.MouseButtonPress,
        grid._cell_rect(0, 0).center(),
        Qt.MouseButton.LeftButton,
    )
    release = _mouse_event(
        QEvent.Type.MouseButtonRelease,
        grid._cell_rect(0, 0).center(),
        Qt.MouseButton.LeftButton,
    )
    grid.mousePressEvent(press)
    grid.mouseReleaseEvent(release)

    assert grid.selected_well_ids() == ["A2", "B1"]


def test_well_selection_grid_left_drag_previews_before_commit(qapp):
    grid = WellSelectionGridWidget(3, 3)

    grid.mousePressEvent(_mouse_event(
        QEvent.Type.MouseButtonPress,
        grid._cell_rect(0, 0).center(),
        Qt.MouseButton.LeftButton,
    ))
    assert grid.drag_preview_well_ids() == ["A1"]
    assert grid.selected_well_ids() == []

    grid.mouseMoveEvent(_mouse_event(
        QEvent.Type.MouseMove,
        grid._cell_rect(1, 1).center(),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
    ))
    assert grid.drag_preview_well_ids() == ["A1", "A2", "B1", "B2"]
    assert grid.selected_well_ids() == []

    grid.mouseReleaseEvent(_mouse_event(
        QEvent.Type.MouseButtonRelease,
        grid._cell_rect(1, 1).center(),
        Qt.MouseButton.LeftButton,
    ))
    assert grid.drag_preview_well_ids() == []
    assert grid.selected_well_ids() == ["A1", "A2", "B1", "B2"]


def test_well_selection_grid_right_drag_previews_clear_before_commit(qapp):
    grid = WellSelectionGridWidget(3, 3)
    grid.apply_rect_selection("A1", "C3", selected=True)

    grid.mousePressEvent(_mouse_event(
        QEvent.Type.MouseButtonPress,
        grid._cell_rect(0, 0).center(),
        Qt.MouseButton.RightButton,
    ))
    grid.mouseMoveEvent(_mouse_event(
        QEvent.Type.MouseMove,
        grid._cell_rect(1, 1).center(),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.RightButton,
    ))

    assert grid.drag_preview_well_ids() == ["A1", "A2", "B1", "B2"]
    assert grid.selected_well_ids() == ["A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "C3"]

    grid.mouseReleaseEvent(_mouse_event(
        QEvent.Type.MouseButtonRelease,
        grid._cell_rect(1, 1).center(),
        Qt.MouseButton.RightButton,
    ))
    assert grid.drag_preview_well_ids() == []
    assert grid.selected_well_ids() == ["A3", "B3", "C1", "C2", "C3"]


def test_well_selection_grid_left_drag_from_selected_well_clears_region(qapp):
    grid = WellSelectionGridWidget(3, 3)
    grid.apply_rect_selection("A1", "C3", selected=True)

    grid.mousePressEvent(_mouse_event(
        QEvent.Type.MouseButtonPress,
        grid._cell_rect(0, 0).center(),
        Qt.MouseButton.LeftButton,
    ))
    grid.mouseMoveEvent(_mouse_event(
        QEvent.Type.MouseMove,
        grid._cell_rect(1, 1).center(),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
    ))

    assert grid.drag_preview_well_ids() == ["A1", "A2", "B1", "B2"]
    assert grid.selected_well_ids() == ["A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "C3"]

    grid.mouseReleaseEvent(_mouse_event(
        QEvent.Type.MouseButtonRelease,
        grid._cell_rect(1, 1).center(),
        Qt.MouseButton.LeftButton,
    ))
    assert grid.drag_preview_well_ids() == []
    assert grid.selected_well_ids() == ["A3", "B3", "C1", "C2", "C3"]


def test_well_selection_dialog_ok_requires_selection(qapp):
    dialog = WellSelectionDialog("test-plate", 2, 2, selected_wells=[])

    assert dialog.ok_btn.isEnabled() is False

    dialog.grid.apply_rect_selection("A1", "A1", selected=True)

    assert dialog.ok_btn.isEnabled() is True


def test_printable_wells_accept_updates_model_and_summary(monkeypatch, qapp):
    dialog = _dialog_stub()

    class FakeWellSelectionDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return QDialog.Accepted

        def selected_well_ids(self):
            return ["A1", "B2"]

    monkeypatch.setattr(View, "WellSelectionDialog", FakeWellSelectionDialog)

    ExperimentDesignDialog._on_choose_printable_wells(dialog)

    dialog.model.set_well_selection.assert_called_once_with(["A1", "B2"])
    assert "2 printable" in dialog.well_selection_summary_lbl.text()
    dialog._update_summary_labels.assert_called_once()
    dialog._schedule_auto_update.assert_called_once()


def test_printable_wells_cancel_leaves_selection_unchanged(monkeypatch, qapp):
    dialog = _dialog_stub(included_wells=["C3"])

    class FakeWellSelectionDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return QDialog.Rejected

        def selected_well_ids(self):
            return ["A1"]

    monkeypatch.setattr(View, "WellSelectionDialog", FakeWellSelectionDialog)

    ExperimentDesignDialog._on_choose_printable_wells(dialog)

    dialog.model.set_well_selection.assert_not_called()
    assert dialog.model.get_auto_assignment_included_wells() == ["C3"]
    dialog._schedule_auto_update.assert_not_called()


def test_printable_wells_default_mode_initializes_from_legacy_start_rectangle(qapp):
    dialog = _dialog_stub(rows=3, cols=3, start_row=1, start_col=1, excluded={"B2"})

    selected = ExperimentDesignDialog._current_selection_for_picker(dialog, "test-plate")

    assert selected == ["B3", "C2", "C3"]


def test_printable_wells_custom_mode_initializes_from_saved_selection(qapp):
    dialog = _dialog_stub(
        included_wells=["C3", "A1", "D1", "B2"],
        rows=3,
        cols=3,
        excluded={"B2"},
    )

    selected = ExperimentDesignDialog._current_selection_for_picker(dialog, "test-plate")

    assert selected == ["C3", "A1"]


def test_printable_wells_manual_mode_disables_picker(qapp):
    dialog = _dialog_stub(manual=True)
    dialog.randomize_chk = QCheckBox()
    dialog.rep_spin = QSpinBox()
    dialog.random_seed_spin = QSpinBox()
    dialog.unique_conditions_btn = QPushButton()
    dialog.preview_reactions_btn = QPushButton()
    dialog.export_reaction_preview_btn = QPushButton()
    dialog._can_reuse_current_generated_design = lambda: False

    ExperimentDesignDialog._apply_manual_assignment_lock_state(dialog)

    assert dialog.well_selection_btn.isEnabled() is False
    assert "Explicit uploaded wells" in dialog.well_selection_summary_lbl.text()
