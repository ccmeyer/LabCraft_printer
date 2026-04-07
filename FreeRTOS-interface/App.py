import sys
from PySide6.QtWidgets import QApplication, QSplashScreen
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QStyleFactory
from PySide6.QtGui import QPalette, QColor, QPixmap, QIcon
import os, json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hardware.profile import get_profile

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
    app.setDesktopFileName("labcraft-printer")

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

    settings = load_settings(os.path.join(script_dir, 'Presets','Settings.json'))

    profile = get_profile(settings.get("HARDWARE_PROFILE", "current"))


    # Initialize components
    model = Model(profile=profile)

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

    # Delay for the splash screen to simulate loading tasks
    QTimer.singleShot(100, lambda: (splash.finish(view), view.show()))  # 2000 ms = 2 seconds


    # # Show the main window
    # view.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    print("Starting application...")
    main()
