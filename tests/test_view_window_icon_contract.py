import os
from pathlib import Path

import App
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
        def __init__(self, parent=None):
            captured["parent"] = parent

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

    assert captured["parent"] is mw
    assert captured["icon"] is sentinel
    assert captured["executed"] is True


def test_popup_yes_no_keeps_transparent_icon(monkeypatch):
    captured = {}

    class FakeMessageBox:
        Yes = 1
        No = 2
        StandardButton = int

        def __init__(self, parent=None):
            captured["parent"] = parent

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

    assert captured["parent"] is mw
    assert captured["icon"] is sentinel
    assert captured["executed"] is True
    assert result == FakeMessageBox.Yes


def test_app_main_sets_labcraft_icon_before_showing_window():
    app_source = Path("FreeRTOS-interface/App.py").read_text(encoding="utf-8")
    pre_main_source = app_source.split("def main():", 1)[0]

    assert 'APP_DESKTOP_FILE_NAME = "labcraft-printer"' in app_source
    assert "configure_app_identity(app)" in app_source
    assert "LabCraft_icon.png" in app_source
    assert "app.setWindowIcon(app_icon)" in app_source
    assert "app.processEvents()" in app_source
    assert "from legacy.mass_calibration import MassCalibrationModel, Balance" not in pre_main_source
    assert "from legacy.mass_calibration import MassCalibrationModel, Balance" in app_source.split("if profile.name == \"legacy\":", 1)[1]


def test_app_single_instance_guard_runs_before_hardware_import():
    app_source = Path("FreeRTOS-interface/App.py").read_text(encoding="utf-8")
    main_source = app_source.split("def main():", 1)[1]

    lock_index = main_source.index("app_lock = acquire_single_instance_lock(lock_path)")
    hardware_import_index = main_source.index("from Machine_FreeRTOS import Machine")

    assert lock_index < hardware_import_index


def test_single_instance_lock_path_uses_app_local_storage(monkeypatch, tmp_path):
    requested_locations = []
    app_data_dir = tmp_path / "app-local-data"

    class FakeStandardPaths:
        AppLocalDataLocation = "app-local-location"

        @staticmethod
        def writableLocation(location):
            requested_locations.append(location)
            return str(app_data_dir)

    monkeypatch.setattr(App, "QStandardPaths", FakeStandardPaths)

    lock_path = App.single_instance_lock_path()

    assert requested_locations == [FakeStandardPaths.AppLocalDataLocation]
    assert lock_path == app_data_dir / App.SINGLE_INSTANCE_LOCK_FILENAME
    assert lock_path.parent.is_dir()


def test_acquire_single_instance_lock_configures_long_lived_lock(monkeypatch, tmp_path):
    created_locks = []

    class FakeLock:
        def __init__(self, path):
            self.path = path
            self.stale_lock_time = None
            self.try_timeout = None
            created_locks.append(self)

        def setStaleLockTime(self, stale_lock_time):
            self.stale_lock_time = stale_lock_time

        def tryLock(self, timeout):
            self.try_timeout = timeout
            return True

    lock_path = tmp_path / "labcraft.lock"
    monkeypatch.setattr(App, "QLockFile", FakeLock)

    lock = App.acquire_single_instance_lock(lock_path)

    assert lock is created_locks[0]
    assert lock.path == str(lock_path)
    assert lock.stale_lock_time == 0
    assert lock.try_timeout == 0


def test_acquire_single_instance_lock_returns_none_when_lock_is_held(monkeypatch, tmp_path):
    class FakeLock:
        def __init__(self, path):
            self.path = path

        def setStaleLockTime(self, stale_lock_time):
            self.stale_lock_time = stale_lock_time

        def tryLock(self, timeout):
            self.try_timeout = timeout
            return False

    monkeypatch.setattr(App, "QLockFile", FakeLock)

    assert App.acquire_single_instance_lock(tmp_path / "labcraft.lock") is None


def test_app_main_duplicate_instance_exits_before_splash_or_hardware(monkeypatch, tmp_path):
    calls = []
    lock_path = tmp_path / "labcraft-printer-main.lock"

    class FakeApplication:
        def __init__(self, argv):
            calls.append(("QApplication", tuple(argv)))

        def setOrganizationName(self, name):
            calls.append(("organization", name))

        def setApplicationName(self, name):
            calls.append(("application", name))

        def setApplicationDisplayName(self, name):
            calls.append(("display", name))

        def setDesktopFileName(self, name):
            calls.append(("desktop", name))

        def exec(self):
            raise AssertionError("event loop should not start for duplicate instances")

    def fail_splash(*args, **kwargs):
        raise AssertionError("splash should not be created for duplicate instances")

    monkeypatch.setattr(App, "QApplication", FakeApplication)
    monkeypatch.setattr(App, "single_instance_lock_path", lambda: lock_path)
    monkeypatch.setattr(App, "acquire_single_instance_lock", lambda path: None)
    monkeypatch.setattr(App, "show_single_instance_warning", lambda path: calls.append(("warning", path)))
    monkeypatch.setattr(App, "QSplashScreen", fail_splash)

    assert App.main() == App.EXIT_ALREADY_RUNNING
    assert ("warning", lock_path) in calls
    assert ("desktop", App.APP_DESKTOP_FILE_NAME) in calls


def test_view_lazy_loads_mass_calibration_dialog_only_for_legacy_path():
    view_source = Path("FreeRTOS-interface/View.py").read_text(encoding="utf-8")

    assert "from legacy.mass_calibration import MassCalibrationDialog" not in view_source.splitlines()[:80]
    assert "MassCalibrationDialog = None" in view_source
    assert "def _get_mass_calibration_dialog_class():" in view_source
