from unittest.mock import Mock

from PySide6 import QtWidgets
from PySide6.QtCore import Qt

import View
from View import KeyboardShortcutsDialog, MainWindow


class ShortcutManagerStub:
    def __init__(self, shortcuts=None):
        self.shortcuts = list(
            shortcuts
            if shortcuts is not None
            else [
                ("Left", "Move left"),
                ("Ctrl+Shift+A", "Audit Timeline"),
            ]
        )

    def get_shortcuts(self):
        return list(self.shortcuts)


class MainWindowWidgetStub(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.color_dict = {"darker_gray": "#222222"}


def test_keyboard_shortcuts_dialog_loads_shortcuts(qapp):
    main_window = MainWindowWidgetStub()
    shortcut_manager = ShortcutManagerStub(
        [
            ("Left", "Move left"),
            ("Shift+p", "Print Array"),
            ("Esc", "Pause Action"),
        ]
    )

    dialog = KeyboardShortcutsDialog(main_window, shortcut_manager)

    assert dialog.windowTitle() == "Keyboard Shortcuts"
    assert dialog.windowModality() == Qt.ApplicationModal
    assert dialog.isModal() is True

    table = dialog.shortcut_table.table
    assert table.rowCount() == 3
    assert table.item(0, 0).text() == "Left"
    assert table.item(0, 1).text() == "Move left"
    assert table.item(1, 0).text() == "Shift+p"
    assert table.item(1, 1).text() == "Print Array"
    assert table.item(2, 0).text() == "Esc"
    assert table.item(2, 1).text() == "Pause Action"


def test_keyboard_shortcuts_dialog_close_button_accepts(qapp):
    dialog = KeyboardShortcutsDialog(MainWindowWidgetStub(), ShortcutManagerStub())

    dialog.close_button.click()

    assert dialog.result() == QtWidgets.QDialog.Accepted


def test_show_keyboard_shortcuts_execs_fresh_dialog_without_shortcut_callbacks(monkeypatch):
    callback = Mock()
    shortcut_manager = ShortcutManagerStub([("Ctrl+K", "Callback should not run")])
    instances = []

    class FakeKeyboardShortcutsDialog:
        def __init__(self, parent, manager):
            self.parent = parent
            self.manager = manager
            self.exec = Mock(return_value=QtWidgets.QDialog.Accepted)
            instances.append(self)

    monkeypatch.setattr(View, "KeyboardShortcutsDialog", FakeKeyboardShortcutsDialog)

    main_window = MainWindow.__new__(MainWindow)
    main_window.shortcut_manager = shortcut_manager

    MainWindow.show_keyboard_shortcuts(main_window)
    MainWindow.show_keyboard_shortcuts(main_window)

    assert len(instances) == 2
    assert instances[0].parent is main_window
    assert instances[0].manager is shortcut_manager
    instances[0].exec.assert_called_once_with()
    instances[1].exec.assert_called_once_with()
    callback.assert_not_called()


def test_right_panel_action_row_wires_shortcuts_button(qapp):
    main_window = MainWindow.__new__(MainWindow)
    main_window.show_experiment_audit = Mock()
    main_window.show_keyboard_shortcuts = Mock()

    container = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(container)

    MainWindow._add_right_panel_action_buttons(main_window, layout)

    assert main_window.audit_timeline_button.text() == "Audit Timeline"
    assert main_window.keyboard_shortcuts_button.text() == "Shortcuts"
    assert main_window.keyboard_shortcuts_button.toolTip() == "Show keyboard shortcuts"

    main_window.keyboard_shortcuts_button.click()
    main_window.audit_timeline_button.click()

    assert main_window.show_keyboard_shortcuts.call_count == 1
    assert main_window.show_experiment_audit.call_count == 1
