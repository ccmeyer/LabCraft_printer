from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtWidgets import QLabel, QMessageBox, QSpinBox

from View import ExperimentDesignDialog


def _build_capacity_dialog(required_reactions, *, rows=1, cols=2, start_row=0, start_col=0, excluded=None):
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.model = SimpleNamespace(get_number_of_reactions=lambda: required_reactions)
    dialog.status_lbl = QLabel("")
    dialog.summary_lbl = QLabel("")
    dialog._set_status = ExperimentDesignDialog._set_status.__get__(dialog, ExperimentDesignDialog)

    dialog.start_row_spin = QSpinBox()
    dialog.start_row_spin.setValue(start_row)
    dialog.start_col_spin = QSpinBox()
    dialog.start_col_spin.setValue(start_col)
    dialog.plate_format_combo = SimpleNamespace(currentText=lambda: "test-plate")

    plate_data = {"name": "test-plate", "rows": rows, "columns": cols}
    dialog.main_window = SimpleNamespace(
        model=SimpleNamespace(
            well_plate=SimpleNamespace(
                get_current_plate_name=lambda: "test-plate",
                get_plate_data_by_name=lambda _: plate_data,
                excluded_wells=set(excluded or set()),
            )
        )
    )
    return dialog


def test_validate_plate_capacity_blocks_when_required_exceeds_available(monkeypatch, qapp):
    dialog = _build_capacity_dialog(required_reactions=3, rows=1, cols=2)
    warn = Mock()
    monkeypatch.setattr(QMessageBox, "warning", warn)

    ok = ExperimentDesignDialog._validate_plate_capacity(dialog, show_dialog=True)

    assert ok is False
    warn.assert_called_once()
    _, title, msg = warn.call_args[0]
    assert title == "Insufficient Well Capacity"
    assert "Required reactions: 3" in msg
    assert "Available wells on 'test-plate': 2" in msg


def test_validate_plate_capacity_counts_exclusions_and_start_offset(monkeypatch, qapp):
    dialog = _build_capacity_dialog(
        required_reactions=2,
        rows=2,
        cols=2,
        start_row=1,
        start_col=0,
        excluded={"B1"},
    )
    warn = Mock()
    monkeypatch.setattr(QMessageBox, "warning", warn)

    ok = ExperimentDesignDialog._validate_plate_capacity(dialog, show_dialog=True)

    assert ok is False
    warn.assert_called_once()
    _, _title, msg = warn.call_args[0]
    assert "Required reactions: 2" in msg
    assert "Available wells on 'test-plate': 1" in msg


def test_validate_plate_capacity_no_popup_when_sufficient(monkeypatch, qapp):
    dialog = _build_capacity_dialog(required_reactions=2, rows=2, cols=2)
    warn = Mock()
    monkeypatch.setattr(QMessageBox, "warning", warn)

    ok = ExperimentDesignDialog._validate_plate_capacity(dialog, show_dialog=False)

    assert ok is True
    warn.assert_not_called()


def test_summary_shows_available_wells_and_highlights_required_when_over_capacity(qapp):
    dialog = _build_capacity_dialog(required_reactions=5, rows=2, cols=2)

    ExperimentDesignDialog._update_summary_labels(dialog, total_reactions=5, worst_nonfill_nL=123.0)

    text = dialog.summary_lbl.text()
    assert "Available wells = 4" in text
    assert "Worst non-fill volume = 123 nL" in text
    assert "color:#8a0303" in text
    assert ">5<" in text


def test_summary_shows_plain_required_when_within_capacity(qapp):
    dialog = _build_capacity_dialog(required_reactions=3, rows=2, cols=2)

    ExperimentDesignDialog._update_summary_labels(dialog, total_reactions=3, worst_nonfill_nL=10.0)

    text = dialog.summary_lbl.text()
    assert "Total reactions = 3" in text
    assert "Available wells = 4" in text
    assert "color:#8a0303" not in text
