from types import SimpleNamespace

import View
from View import MainWindow


class _FakeMessageBox:
    ActionRole = "action"
    Ok = "ok"
    instances = []

    def __init__(self, parent=None):
        self.parent = parent
        self.title = None
        self.text = None
        self.icon = None
        self.buttons = []
        self.default_button = None
        self.executed = False
        _FakeMessageBox.instances.append(self)

    def setWindowTitle(self, title):
        self.title = title

    def setText(self, text):
        self.text = text

    def setWindowIcon(self, icon):
        self.icon = icon

    def addButton(self, *args):
        button = {"args": args, "owner": self}
        self.buttons.append(button)
        return button

    def setDefaultButton(self, button):
        self.default_button = button

    def clickedButton(self):
        if self.title == "Board Reset Detected":
            for button in self.buttons:
                if button["args"] and button["args"][0] == "Export Debug Bundle":
                    return button
        return self.default_button

    def exec(self):
        self.executed = True
        return 0


def _make_main_window(monkeypatch, export_fn):
    _FakeMessageBox.instances = []
    monkeypatch.setattr(View.QtWidgets, "QMessageBox", _FakeMessageBox)
    mw = MainWindow.__new__(MainWindow)
    mw.make_transparent_icon = lambda: "icon"
    mw.controller = SimpleNamespace(export_last_reset_debug_bundle=export_fn)
    return mw


def test_board_reset_popup_exports_debug_bundle_and_shows_success(monkeypatch, tmp_path):
    calls = []

    def export_bundle():
        calls.append(True)
        return {"archive_path": str(tmp_path / "bundle.zip")}

    mw = _make_main_window(monkeypatch, export_bundle)

    MainWindow.popup_message(mw, "Board Reset Detected", "Board restarted.")

    assert calls == [True]
    assert len(_FakeMessageBox.instances) == 2
    reset_box, success_box = _FakeMessageBox.instances
    assert reset_box.title == "Board Reset Detected"
    assert any(button["args"][0] == "Export Debug Bundle" for button in reset_box.buttons)
    assert success_box.title == "Debug Bundle Exported"
    assert "bundle.zip" in success_box.text
    assert reset_box.icon == "icon"


def test_board_reset_popup_shows_export_failure(monkeypatch):
    def export_bundle():
        raise OSError("disk unavailable")

    mw = _make_main_window(monkeypatch, export_bundle)

    MainWindow.popup_message(mw, "Board Reset Detected", "Board restarted.")

    assert len(_FakeMessageBox.instances) == 2
    assert _FakeMessageBox.instances[1].title == "Debug Bundle Export Failed"
    assert "disk unavailable" in _FakeMessageBox.instances[1].text


def test_generic_popup_does_not_show_debug_bundle_button(monkeypatch):
    calls = []
    mw = _make_main_window(monkeypatch, lambda: calls.append(True))

    MainWindow.popup_message(mw, "Other Error", "Something happened.")

    assert calls == []
    assert len(_FakeMessageBox.instances) == 1
    assert _FakeMessageBox.instances[0].buttons == []
