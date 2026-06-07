import sys
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen
from PySide6.QtCore import QLockFile, QStandardPaths, QTimer
from PySide6.QtWidgets import QStyleFactory
from PySide6.QtGui import QPalette, QColor, QPixmap, QIcon
import os, json
from pathlib import Path

APP_ORGANIZATION_NAME = "LabCraft"
APP_APPLICATION_NAME = "LabCraft Printer"
APP_DESKTOP_FILE_NAME = "labcraft-printer"
SINGLE_INSTANCE_LOCK_FILENAME = "labcraft-printer-main.lock"
EXIT_ALREADY_RUNNING = 1

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hardware.profile import get_profile
from LocalConfig import get_machine_config_path

def configure_app_identity(app):
    app.setOrganizationName(APP_ORGANIZATION_NAME)
    app.setApplicationName(APP_APPLICATION_NAME)
    set_display_name = getattr(app, "setApplicationDisplayName", None)
    if callable(set_display_name):
        set_display_name(APP_APPLICATION_NAME)
    app.setDesktopFileName(APP_DESKTOP_FILE_NAME)

def single_instance_lock_path():
    data_dir = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
    lock_dir = Path(data_dir) if data_dir else Path.home() / ".labcraft-printer"
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir / SINGLE_INSTANCE_LOCK_FILENAME

def acquire_single_instance_lock(lock_path=None):
    path = Path(lock_path) if lock_path is not None else single_instance_lock_path()
    lock = QLockFile(str(path))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        return None
    return lock

def show_single_instance_warning(lock_path):
    QMessageBox.warning(
        None,
        "LabCraft Already Running",
        "LabCraft Printer is already running.\n\n"
        "Only one instance may control the machine at a time. "
        "Use the existing LabCraft window, or close it before starting another copy.\n\n"
        "If LabCraft crashed and no process is running, remove this lock file:\n"
        f"{lock_path}",
    )

def set_dark_theme(app):
    app.setStyle(QStyleFactory.create("Fusion"))

    dark_palette = QPalette()
    
    # Base color
    dark_palette.setColor(QPalette.Window, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.WindowText, QColor(255, 255, 255))  # white
    dark_palette.setColor(QPalette.Base, QColor(25, 25, 25))
    dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ToolTipBase, QColor(50,50,50))  # white
    dark_palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))  # white
    dark_palette.setColor(QPalette.Text, QColor(255, 255, 255))  # white
    dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))  # white
    dark_palette.setColor(QPalette.BrightText, QColor(255, 0, 0))  # red
    
    # Link colors
    dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.LinkVisited, QColor(42, 130, 218))
    
    # Highlight color
    dark_palette.setColor(QPalette.Highlight, QColor(50, 50, 50))
    dark_palette.setColor(QPalette.HighlightedText, QColor(150, 150, 150))

    app.setPalette(dark_palette)

    app.setStyleSheet("""
        QLabel {
            border-radius: 5px;  /* Rounded corners for QLabel */
        }
    """)

def load_settings(file_path):
    defaults = {"HARDWARE_PROFILE": "current"}
    try:
        with open(file_path, 'r', encoding="utf-8") as file:
            loaded = json.load(file)
        return loaded if isinstance(loaded, dict) else defaults.copy()
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
        return defaults.copy()

def main():
    app = QApplication(sys.argv)
    configure_app_identity(app)

    lock_path = single_instance_lock_path()
    app_lock = acquire_single_instance_lock(lock_path)
    if app_lock is None:
        show_single_instance_warning(lock_path)
        return EXIT_ALREADY_RUNNING

    try:
        # Create splash screen
        script_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(script_dir, 'Presets', 'LabCraft_icon.png')
        app_icon = QIcon(icon_path)
        if not app_icon.isNull():
            app.setWindowIcon(app_icon)
        logo_path = os.path.join(script_dir, 'Presets','LabCraft_logo.png')
        pixmap = QPixmap(logo_path)  # Replace with your logo image path
        splash = QSplashScreen(pixmap)
        splash.show()
        # Let the splash paint before heavier module imports and object setup continue.
        app.processEvents()

        from Machine_FreeRTOS import Machine
        from Model import Model
        from Controller import Controller
        from View import MainWindow

        settings = load_settings(get_machine_config_path("Settings.json"))

        profile = get_profile(settings.get("HARDWARE_PROFILE", "current"))


        # Initialize components
        model = Model(profile=profile)
        dispenser_defaults = (
            settings.get("DISPENSER_TYPES", {})
            .get(settings.get("DEFAULT_DISPENSER", ""), {})
        )
        dispense_frequency_hz = (
            dispenser_defaults.get("frequency")
            if isinstance(dispenser_defaults, dict)
            else None
        )
        if dispense_frequency_hz is not None:
            try:
                model.machine_model.update_dispense_frequency_hz(dispense_frequency_hz)
            except (TypeError, ValueError):
                pass

        machine = Machine(model,profile=profile)
        controller = Controller(machine, model, profile=profile)

        if profile.name == "legacy":
            from legacy.mass_calibration import MassCalibrationModel, Balance

            model.calibration_model = MassCalibrationModel(
                machine_model=model.machine_model,
                printer_head_manager=model.printer_head_manager,
                rack_model=model.rack_model,
                prediction_model_dir=model.predictive_model_dir,
            )

            controller.balance = Balance(machine=machine, model=model)

            # mass updates -> calibration model
            controller.balance.balance_mass_updated_signal.connect(model.calibration_model.update_mass)
            controller.balance.connected_signal.connect(lambda ok: model.machine_model.connect_balance() if ok else model.machine_model.disconnect_balance())
            # optional: forward balance errors to your existing popup system
            controller.balance.balance_error_signal.connect(controller.error_occurred_signal.emit)
        else:
            # leave your current calibration model untouched
            # model.calibration_model = CurrentCalibrationModel(...)
            pass

        set_dark_theme(app)
        view = MainWindow(model,controller, profile=profile)

        def show_main_window():
            view.show()
            splash.finish(view)
            view.show_pending_app_update_result_after_startup()

        # Delay briefly so the splash can paint before the main window appears.
        QTimer.singleShot(100, show_main_window)


        # # Show the main window
        # view.show()

        return app.exec()
    finally:
        app_lock.unlock()


if __name__ == "__main__":
    print("Starting application...")
    sys.exit(main())
