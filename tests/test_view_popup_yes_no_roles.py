from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtWidgets import QMessageBox

from View import MainWindow


def test_popup_yes_no_callers_do_not_depend_on_button_text_literals():
    mw = MainWindow.__new__(MainWindow)
    mw.controller = SimpleNamespace(
        reset_all_arrays=Mock(),
        pause_commands=Mock(),
        resume_commands=Mock(),
        clear_command_queue=Mock(),
    )

    mw.popup_yes_no = lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    MainWindow.reset_all_arrays(mw)
    mw.controller.reset_all_arrays.assert_called_once_with()

    mw.controller.pause_commands.reset_mock()
    mw.controller.resume_commands.reset_mock()
    mw.controller.clear_command_queue.reset_mock()
    MainWindow.pause_machine(mw)
    mw.controller.pause_commands.assert_called_once_with()
    mw.controller.resume_commands.assert_called_once_with()
    mw.controller.clear_command_queue.assert_not_called()


def test_popup_yes_no_no_response_preserves_negative_paths():
    mw = MainWindow.__new__(MainWindow)
    mw.controller = SimpleNamespace(
        reset_all_arrays=Mock(),
        pause_commands=Mock(),
        resume_commands=Mock(),
        clear_command_queue=Mock(),
    )

    mw.popup_yes_no = lambda *args, **kwargs: QMessageBox.StandardButton.No
    MainWindow.reset_all_arrays(mw)
    mw.controller.reset_all_arrays.assert_not_called()

    MainWindow.pause_machine(mw)
    mw.controller.pause_commands.assert_called_once_with()
    mw.controller.resume_commands.assert_not_called()
    mw.controller.clear_command_queue.assert_called_once_with()
