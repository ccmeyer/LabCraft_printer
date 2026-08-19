import sys
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen
from PySide6.QtCore import QLockFile, QStandardPaths, QTimer
from PySide6.QtWidgets import QStyleFactory
from PySide6.QtGui import QPalette, QColor, QPixmap, QIcon
import os, json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
import threading
import time
import traceback

APP_ORGANIZATION_NAME = "LabCraft"
APP_APPLICATION_NAME = "LabCraft Printer"
APP_DESKTOP_FILE_NAME = "labcraft-printer"
SINGLE_INSTANCE_LOCK_FILENAME = "labcraft-printer-main.lock"
EXIT_ALREADY_RUNNING = 1
EXIT_BOOTSTRAP_CANCELLED = 2
EXIT_BOOTSTRAP_FAILED = 3
EXIT_RECOVERY_REQUIRED = 4
EXIT_CONFIGURATION_LOCK_UNAVAILABLE = 5
UI_FREEZE_DIAGNOSTIC_LOG_FILENAME = "ui-freeze-diagnostics.log"
UI_FREEZE_WATCHDOG_INTERVAL_MS = 500
UI_FREEZE_WATCHDOG_STALL_SECONDS = 5.0
UI_FREEZE_WATCHDOG_REPEAT_SECONDS = 30.0

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hardware.profile import get_profile
from AppVersion import get_app_commit, get_app_version

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

def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def freeze_diagnostics_log_path():
    log_dir = REPO_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / UI_FREEZE_DIAGNOSTIC_LOG_FILENAME

def format_thread_dump(reason, *, now=None, current_frames=None):
    timestamp = (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
    frames = current_frames if current_frames is not None else sys._current_frames()
    lines = [
        "",
        f"[{timestamp}] UI freeze watchdog: {reason}",
        f"Process id: {os.getpid()}",
    ]
    for thread in threading.enumerate():
        lines.append("")
        lines.append(
            f"--- Thread {thread.name} ident={thread.ident} daemon={thread.daemon} ---"
        )
        frame = frames.get(thread.ident)
        if frame is None:
            lines.append("No Python frame available.")
            continue
        lines.extend(traceback.format_stack(frame))
    return "\n".join(lines).rstrip() + "\n"

def append_freeze_diagnostics(message, log_path=None):
    path = Path(log_path) if log_path is not None else freeze_diagnostics_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(str(message))
        if not str(message).endswith("\n"):
            handle.write("\n")
    return path

def install_ui_freeze_watchdog(
    app,
    *,
    interval_ms=UI_FREEZE_WATCHDOG_INTERVAL_MS,
    stall_seconds=UI_FREEZE_WATCHDOG_STALL_SECONDS,
    repeat_seconds=UI_FREEZE_WATCHDOG_REPEAT_SECONDS,
    log_path=None,
):
    """
    Log Python thread stacks if the Qt event loop stops servicing timers.

    This is intentionally passive diagnostics. It does not attempt recovery or
    send hardware commands, because the machine state may be mid-experiment.
    """
    heartbeat = {"last": time.monotonic(), "last_dump": 0.0}

    timer = QTimer(app)
    timer.setInterval(max(100, int(interval_ms)))
    timer.timeout.connect(lambda: heartbeat.__setitem__("last", time.monotonic()))
    timer.start()

    def _watch():
        poll_s = max(0.25, min(1.0, float(stall_seconds) / 4.0))
        while True:
            time.sleep(poll_s)
            now_s = time.monotonic()
            stalled_for = now_s - float(heartbeat["last"])
            if stalled_for < float(stall_seconds):
                continue
            if now_s - float(heartbeat["last_dump"]) < float(repeat_seconds):
                continue
            heartbeat["last_dump"] = now_s
            reason = f"Qt heartbeat stalled for {stalled_for:.1f}s"
            dump = format_thread_dump(reason)
            try:
                path = append_freeze_diagnostics(dump, log_path=log_path)
                print(f"[UIWatchdog] {reason}; wrote stack dump to {path}", flush=True)
            except Exception as exc:
                print(f"[UIWatchdog] {reason}; failed to write stack dump: {exc}", flush=True)
                print(dump, flush=True)

    thread = threading.Thread(target=_watch, name="LabCraftUIFreezeWatchdog", daemon=True)
    thread.start()

    # Keep references alive for the life of QApplication.
    app._labcraft_ui_freeze_timer = timer
    app._labcraft_ui_freeze_watchdog = thread
    return timer, thread

def main():
    app = QApplication(sys.argv)
    configure_app_identity(app)

    lock_path = single_instance_lock_path()
    app_lock = acquire_single_instance_lock(lock_path)
    if app_lock is None:
        show_single_instance_warning(lock_path)
        return EXIT_ALREADY_RUNNING

    components = None
    authorized_context = None
    try:
        # Bootstrap-safe presentation only. Production composition, Settings,
        # MVC, serial, camera, balance, and Machine imports happen later.
        script_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(script_dir, 'Presets', 'LabCraft_icon.png')
        app_icon = QIcon(icon_path)
        if not app_icon.isNull():
            app.setWindowIcon(app_icon)
        set_dark_theme(app)

        from MachineData import resolve_machine_data_base
        from MachineDataBootstrap import BootstrapState, MachineDataBootstrap
        from MachineDataBootstrapDialog import run_bootstrap_dialog

        app_local_data = QStandardPaths.writableLocation(
            QStandardPaths.AppLocalDataLocation
        )
        if not app_local_data:
            QMessageBox.critical(
                None,
                "Machine Data Bootstrap Failed",
                "Qt did not provide an application-local data directory.",
            )
            return EXIT_BOOTSTRAP_FAILED
        try:
            base = resolve_machine_data_base(
                app_local_data_root=app_local_data,
                repo_root=REPO_ROOT,
            )
            bootstrap = MachineDataBootstrap(
                base,
                app_version=get_app_version(REPO_ROOT),
                app_commit=get_app_commit(REPO_ROOT),
            )
            authorized_context = run_bootstrap_dialog(
                bootstrap,
                current_checkout_local=REPO_ROOT / "local",
            )
        except Exception as exc:
            code = str(getattr(exc, "code", "bootstrap_failed"))
            QMessageBox.critical(
                None,
                "Machine Data Bootstrap Failed",
                f"{code}: {exc}",
            )
            if code == "configuration_lock_unavailable":
                return EXIT_CONFIGURATION_LOCK_UNAVAILABLE
            if code == "recovery_required":
                return EXIT_RECOVERY_REQUIRED
            return EXIT_BOOTSTRAP_FAILED
        if authorized_context is None:
            state = bootstrap.inspect().state
            if state is BootstrapState.RECOVERY_REQUIRED:
                return EXIT_RECOVERY_REQUIRED
            return EXIT_BOOTSTRAP_CANCELLED

        # Create the normal splash only after exact external-store
        # authorization and configuration-lock ownership.
        logo_path = os.path.join(script_dir, 'Presets','LabCraft_logo.png')
        pixmap = QPixmap(logo_path)  # Replace with your logo image path
        splash = QSplashScreen(pixmap)
        splash.show()
        # Let the splash paint before heavier module imports and object setup continue.
        app.processEvents()

        from ApplicationComposition import (
            ExperimentalFeatures,
            build_application_components,
            production_dependencies,
        )
        settings = dict(authorized_context.settings)
        current_settings_sha = sha256_file(
            authorized_context.paths.config_root / "Settings.json"
        )
        if current_settings_sha != authorized_context.settings_raw_sha256:
            raise RuntimeError(
                "Canonical Settings changed after bootstrap authorization."
            )

        profile = get_profile(settings.get("HARDWARE_PROFILE", "current"))

        def configure_model(model):
            if model.settings != settings:
                raise RuntimeError(
                    "Model Settings differ from the bootstrap-authorized payload."
                )
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
                    model.machine_model.update_dispense_frequency_hz(
                        dispense_frequency_hz
                    )
                except (TypeError, ValueError):
                    pass

        components = build_application_components(
            profile,
            production_dependencies(authorized_context),
            model_setup=configure_model,
            experimental_features=ExperimentalFeatures.from_environment(
                os.environ
            ),
        )
        app.aboutToQuit.connect(components.close)
        view = components.view

        def show_main_window():
            view.show()
            splash.finish(view)
            view.show_pending_app_update_result_after_startup()

        # Delay briefly so the splash can paint before the main window appears.
        QTimer.singleShot(100, show_main_window)


        # # Show the main window
        # view.show()

        install_ui_freeze_watchdog(app)
        return app.exec()
    except Exception as exc:
        QMessageBox.critical(
            None,
            "LabCraft Startup Failed",
            "Verified machine data could not be opened by the application. "
            "No hardware-capable window was started.\n\n"
            f"{exc}",
        )
        return EXIT_BOOTSTRAP_FAILED
    finally:
        if components is not None:
            if not components.close():
                print(
                    "Application components are still active; no forced calibration, "
                    "camera, or balance teardown was attempted."
                )
        elif authorized_context is not None:
            authorized_context.close()
        app_lock.unlock()


if __name__ == "__main__":
    print("Starting application...")
    sys.exit(main())
