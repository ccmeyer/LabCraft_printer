import os
from pathlib import Path

import View
from View import MainWindow


def test_make_window_icon_uses_labcraft_icon_asset(monkeypatch, tmp_path):
    presets_dir = tmp_path / "Presets"
    presets_dir.mkdir()
    icon_file = presets_dir / "LabCraft_icon.png"
    icon_file.write_bytes(b"not-a-real-png")

    captured = {}

    class FakeIcon:
        def __init__(self, path):
            captured["path"] = path

    monkeypatch.setattr(View.QtGui, "QIcon", FakeIcon)

    mw = MainWindow.__new__(MainWindow)
    mw.script_dir = str(tmp_path)

    icon = MainWindow.make_window_icon(mw)

    assert isinstance(icon, FakeIcon)
    assert captured["path"] == os.path.join(str(tmp_path), "Presets", "LabCraft_icon.png")


def test_make_window_icon_falls_back_to_transparent_icon_when_asset_missing(tmp_path):
    mw = MainWindow.__new__(MainWindow)
    mw.script_dir = str(tmp_path)
    sentinel = object()
    mw.make_transparent_icon = lambda: sentinel

    icon = MainWindow.make_window_icon(mw)

    assert icon is sentinel


def test_popup_message_keeps_transparent_icon(monkeypatch):
    captured = {}

    class FakeMessageBox:
        def setWindowTitle(self, title):
            captured["title"] = title

        def setText(self, text):
            captured["text"] = text

        def setWindowIcon(self, icon):
            captured["icon"] = icon

        def exec(self):
            captured["executed"] = True
            return 0

    monkeypatch.setattr(View.QtWidgets, "QMessageBox", FakeMessageBox)

    mw = MainWindow.__new__(MainWindow)
    sentinel = object()
    mw.make_transparent_icon = lambda: sentinel

    MainWindow.popup_message(mw, "Title", "Body")

    assert captured["icon"] is sentinel
    assert captured["executed"] is True


def test_popup_yes_no_keeps_transparent_icon(monkeypatch):
    captured = {}

    class FakeMessageBox:
        Yes = 1
        No = 2
        StandardButton = int

        def setWindowTitle(self, title):
            captured["title"] = title

        def setText(self, text):
            captured["text"] = text

        def setStandardButtons(self, buttons):
            captured["buttons"] = buttons

        def setWindowIcon(self, icon):
            captured["icon"] = icon

        def exec(self):
            captured["executed"] = True
            return self.Yes

    monkeypatch.setattr(View.QtWidgets, "QMessageBox", FakeMessageBox)

    mw = MainWindow.__new__(MainWindow)
    sentinel = object()
    mw.make_transparent_icon = lambda: sentinel

    result = MainWindow.popup_yes_no(mw, "Confirm", "Proceed?")

    assert captured["icon"] is sentinel
    assert captured["executed"] is True
    assert result == FakeMessageBox.Yes


def test_app_main_sets_labcraft_icon_before_showing_window():
    app_source = Path("FreeRTOS-interface/App.py").read_text(encoding="utf-8")
    pre_main_source = app_source.split("def main():", 1)[0]

    assert 'app.setDesktopFileName("labcraft-printer")' in app_source
    assert "LabCraft_icon.png" in app_source
    assert "app.setWindowIcon(app_icon)" in app_source
    assert "app.processEvents()" in app_source
    assert "from legacy.mass_calibration import MassCalibrationModel, Balance" not in pre_main_source
    assert "from legacy.mass_calibration import MassCalibrationModel, Balance" in app_source.split("if profile.name == \"legacy\":", 1)[1]


def test_view_lazy_loads_mass_calibration_dialog_only_for_legacy_path():
    view_source = Path("FreeRTOS-interface/View.py").read_text(encoding="utf-8")

    assert "from legacy.mass_calibration import MassCalibrationDialog" not in view_source.splitlines()[:80]
    assert "MassCalibrationDialog = None" in view_source
    assert "def _get_mass_calibration_dialog_class():" in view_source
