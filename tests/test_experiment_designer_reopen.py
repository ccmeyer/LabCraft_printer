from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtWidgets import QDialog

import View
from View import WellPlateWidget


class _RejectDialog:
    def __init__(self, experiment_model, main_window):
        self.experiment_model = experiment_model
        self.main_window = main_window

    def exec(self):
        return QDialog.Rejected


class _SessionDialog:
    _exec_results = []

    def __init__(self, experiment_model, main_window):
        self.main_window = main_window

    def exec(self):
        if not self._exec_results:
            return QDialog.Rejected
        result = self._exec_results.pop(0)
        if result == QDialog.Accepted:
            self.main_window.complete_experiment_design()
        return result


def _make_widget():
    widget = WellPlateWidget.__new__(WellPlateWidget)
    runtime_state = {"assigned_wells": ["A1", "A2"], "progress_sentinel": 7}
    widget.model = SimpleNamespace(experiment_model=object(), runtime_state=runtime_state)
    widget.main_window = SimpleNamespace(complete_experiment_design=Mock())
    return widget


def test_open_close_designer_does_not_apply_when_not_finished(monkeypatch):
    widget = _make_widget()
    monkeypatch.setattr(View, "ExperimentDesignDialog", _RejectDialog)

    WellPlateWidget.open_experiment_designer(widget)

    widget.main_window.complete_experiment_design.assert_not_called()


def test_open_close_repeated_cycles_do_not_mutate_runtime_state(monkeypatch):
    widget = _make_widget()
    baseline = dict(widget.model.runtime_state)
    monkeypatch.setattr(View, "ExperimentDesignDialog", _RejectDialog)

    for _ in range(3):
        WellPlateWidget.open_experiment_designer(widget)

    assert widget.model.runtime_state == baseline
    widget.main_window.complete_experiment_design.assert_not_called()


def test_finish_path_still_applies_once_on_reopen_session(monkeypatch):
    widget = _make_widget()
    _SessionDialog._exec_results = [QDialog.Accepted, QDialog.Rejected]
    monkeypatch.setattr(View, "ExperimentDesignDialog", _SessionDialog)

    WellPlateWidget.open_experiment_designer(widget)
    WellPlateWidget.open_experiment_designer(widget)

    widget.main_window.complete_experiment_design.assert_called_once_with()
