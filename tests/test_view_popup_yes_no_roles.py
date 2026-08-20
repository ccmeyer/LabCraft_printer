from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtWidgets import QMessageBox

from View import MainWindow


def test_popup_yes_no_callers_do_not_depend_on_button_text_literals():
    mw = MainWindow.__new__(MainWindow)
    mw.controller = SimpleNamespace(
        reset_all_arrays=Mock(),
    )

    mw.popup_yes_no = lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    MainWindow.reset_all_arrays(mw)
    mw.controller.reset_all_arrays.assert_called_once_with()


def test_popup_yes_no_no_response_preserves_negative_paths():
    mw = MainWindow.__new__(MainWindow)
    mw.controller = SimpleNamespace(
        reset_all_arrays=Mock(),
    )

    mw.popup_yes_no = lambda *args, **kwargs: QMessageBox.StandardButton.No
    MainWindow.reset_all_arrays(mw)
    mw.controller.reset_all_arrays.assert_not_called()
