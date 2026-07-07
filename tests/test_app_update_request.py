from pathlib import Path
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMessageBox

import Controller as controller_mod
import View as view_mod
from tools import update_and_restart as updater_mod
from Controller import Controller
from View import MainWindow, SpeedProfilesTab


class FakeProcess:
    def __init__(self, *, running=True):
        self.returncode = None if running else 0
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = -15
        return self.returncode


def _idle_calibration_manager(**overrides):
    manager = SimpleNamespace(
        activeCalibration=None,
        calibration_queue=[],
        is_pulsewidth_sweep_active=lambda: False,
        get_stream_gravimetric_capture_state=lambda: {"status": "idle"},
        get_stream_calibration_sequence_state=lambda: {"status": "idle"},
        get_droplet_calibration_sequence_state=lambda: {"status": "idle"},
    )
    for key, value in overrides.items():
        setattr(manager, key, value)
    return manager


def _make_controller(tmp_path):
    controller = Controller.__new__(Controller)
    controller._repo_root = Path(tmp_path)
    controller._app_update_process = None
    controller._dfu_thread = None
    controller._qualification_worker = None
    controller._last_app_update_check_result = None
    controller._last_app_rollback_check_result = None
    controller._array_state = "idle"
    controller._seq_state = "idle"
    controller.pending_capture_active = False
    controller.model = SimpleNamespace(calibration_manager=_idle_calibration_manager())
    controller.check_if_all_completed = lambda: True
    return controller


def test_controller_builds_update_command_without_auto_relaunch(tmp_path, monkeypatch):
    controller = _make_controller(tmp_path)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    controller._resolve_app_update_python = lambda: "python-under-test"

    command = controller.build_app_update_command(wait_pid=1234)

    assert command == [
        "python-under-test",
        "-u",
        str((tmp_path / "tools" / "update_and_restart.py").resolve()),
        "--repo-root",
        str(tmp_path),
        "--python",
        "python-under-test",
        "--wait-pid",
        "1234",
        "--gui",
        "--no-relaunch",
        "--record-result",
    ]


def test_controller_builds_update_command_with_offline_manifest(tmp_path, monkeypatch):
    controller = _make_controller(tmp_path)
    manifest_path = tmp_path / "LabCraftUpdates" / "update.json"
    controller._last_app_update_check_result = SimpleNamespace(
        status="update_available",
        update_source="offline",
        offline_manifest_path=manifest_path,
    )
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    controller._resolve_app_update_python = lambda: "python-under-test"

    command = controller.build_app_update_command(wait_pid=1234)

    assert command[-2:] == ["--offline-manifest", str(manifest_path)]
    assert "--record-result" in command


def test_controller_builds_update_command_without_offline_manifest_for_online_update(tmp_path, monkeypatch):
    controller = _make_controller(tmp_path)
    controller._last_app_update_check_result = SimpleNamespace(
        status="update_available",
        update_source="online",
    )
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    controller._resolve_app_update_python = lambda: "python-under-test"

    command = controller.build_app_update_command(wait_pid=1234)

    assert "--offline-manifest" not in command


def test_controller_builds_update_command_with_target_release_for_online_update(tmp_path, monkeypatch):
    controller = _make_controller(tmp_path)
    controller._last_app_update_check_result = SimpleNamespace(
        status="update_available",
        update_source="online",
        target_release_version="v1.1.2",
    )
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    controller._resolve_app_update_python = lambda: "python-under-test"

    command = controller.build_app_update_command(wait_pid=1234)

    assert command[-2:] == ["--target-release", "v1.1.2"]
    assert "--offline-manifest" not in command


def test_controller_builds_rollback_command(tmp_path, monkeypatch):
    controller = _make_controller(tmp_path)
    controller._last_app_rollback_check_result = SimpleNamespace(
        status="rollback_available",
        update_source="online",
    )
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    controller._resolve_app_update_python = lambda: "python-under-test"

    command = controller.build_app_rollback_command(wait_pid=1234)

    assert command == [
        "python-under-test",
        "-u",
        str((tmp_path / "tools" / "update_and_restart.py").resolve()),
        "--repo-root",
        str(tmp_path),
        "--python",
        "python-under-test",
        "--wait-pid",
        "1234",
        "--gui",
        "--no-relaunch",
        "--record-result",
        "--rollback",
    ]


def test_controller_builds_offline_rollback_command_with_manifest(tmp_path, monkeypatch):
    controller = _make_controller(tmp_path)
    manifest_path = tmp_path / "LabCraftUpdates" / "rollback.json"
    controller._last_app_rollback_check_result = SimpleNamespace(
        status="rollback_available",
        update_source="offline",
        offline_manifest_path=manifest_path,
    )
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    controller._resolve_app_update_python = lambda: "python-under-test"

    command = controller.build_app_rollback_command(wait_pid=1234)

    assert "--rollback" in command
    assert command[-2:] == ["--offline-manifest", str(manifest_path)]


def test_controller_resolves_active_virtualenv_python_first(tmp_path, monkeypatch):
    controller = _make_controller(tmp_path)
    active_python = tmp_path / "active-env" / "Scripts" / "python.exe"
    active_python.parent.mkdir(parents=True)
    active_python.write_text("", encoding="utf-8")
    repo_python = tmp_path / "env" / "Scripts" / "python.exe"
    repo_python.parent.mkdir(parents=True)
    repo_python.write_text("", encoding="utf-8")
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "active-env"))
    monkeypatch.setattr(controller_mod.sys, "executable", "python-under-test")
    monkeypatch.setattr(controller, "_probe_app_update_python", lambda path: (True, f"{path}: PySide6 OK"))

    assert controller._resolve_app_update_python() == str(active_python.absolute())


def test_controller_resolves_repo_env_python_before_sys_executable(tmp_path, monkeypatch):
    controller = _make_controller(tmp_path)
    repo_python = tmp_path / "env" / "bin" / "python"
    repo_python.parent.mkdir(parents=True)
    repo_python.write_text("", encoding="utf-8")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(controller_mod.sys, "executable", "python-under-test")
    monkeypatch.setattr(controller, "_probe_app_update_python", lambda path: (True, f"{path}: PySide6 OK"))

    assert controller._resolve_app_update_python() == str(repo_python.absolute())


def test_controller_resolver_skips_python_without_pyside6(tmp_path, monkeypatch):
    controller = _make_controller(tmp_path)
    active_python = tmp_path / "active-env" / "bin" / "python"
    active_python.parent.mkdir(parents=True)
    active_python.write_text("", encoding="utf-8")
    repo_python = tmp_path / "env" / "bin" / "python"
    repo_python.parent.mkdir(parents=True)
    repo_python.write_text("", encoding="utf-8")
    calls = []

    def fake_probe(path):
        calls.append(path)
        if path == str(repo_python.absolute()):
            return True, f"{path}: PySide6 OK"
        return False, f"{path}: PySide6 unavailable (No module named 'PySide6')"

    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "active-env"))
    monkeypatch.setattr(controller_mod.sys, "executable", "python-under-test")
    monkeypatch.setattr(controller, "_probe_app_update_python", fake_probe)

    assert controller._resolve_app_update_python() == str(repo_python.absolute())
    assert str(active_python.absolute()) in calls
    assert str(repo_python.absolute()) in calls
    assert any("PySide6 unavailable" in line for line in controller._last_app_update_python_probe_lines)
    assert any("PySide6 OK" in line for line in controller._last_app_update_python_probe_lines)


def test_app_update_check_worker_uses_offline_fallback_helper(tmp_path, monkeypatch, qapp):
    calls = []
    result = SimpleNamespace(status="up_to_date", message="done")

    def fake_fallback(config, **kwargs):
        calls.append((config, kwargs))
        return result

    monkeypatch.setattr(updater_mod, "run_update_check_with_offline_fallback", fake_fallback)
    worker = controller_mod.AppUpdateCheckWorker(tmp_path, command_runner="runner")
    emitted = []
    worker.finished.connect(emitted.append)

    worker.run()

    assert emitted == [result]
    assert calls[0][0].repo_root == tmp_path
    assert calls[0][0].release_channel == "stable"
    assert calls[0][1]["command_runner"] == "runner"


def test_app_update_check_worker_passes_release_candidate_channel(tmp_path, monkeypatch, qapp):
    calls = []
    fallback_calls = []
    result = SimpleNamespace(status="update_available", message="rc ready")

    def fake_check(config, **kwargs):
        calls.append((config, kwargs))
        return result

    monkeypatch.setattr(updater_mod, "run_update_check", fake_check)
    monkeypatch.setattr(updater_mod, "run_update_check_with_offline_fallback", lambda *args, **kwargs: fallback_calls.append((args, kwargs)))
    worker = controller_mod.AppUpdateCheckWorker(
        tmp_path,
        command_runner="runner",
        release_channel="release_candidate",
    )
    emitted = []
    worker.finished.connect(emitted.append)

    worker.run()

    assert emitted == [result]
    assert calls[0][0].release_channel == "release_candidate"
    assert calls[0][1]["command_runner"] == "runner"
    assert fallback_calls == []


def test_app_update_check_worker_uses_selected_offline_manifest(tmp_path, monkeypatch, qapp):
    calls = []
    fallback_calls = []
    result = SimpleNamespace(status="update_available", message="offline ready")
    manifest_path = tmp_path / "LabCraftUpdates" / "update.json"

    def fake_check(config, **kwargs):
        calls.append((config, kwargs))
        return result

    monkeypatch.setattr(updater_mod, "run_update_check", fake_check)
    monkeypatch.setattr(updater_mod, "run_update_check_with_offline_fallback", lambda *args, **kwargs: fallback_calls.append((args, kwargs)))
    worker = controller_mod.AppUpdateCheckWorker(tmp_path, command_runner="runner", offline_manifest_path=manifest_path)
    emitted = []
    worker.finished.connect(emitted.append)

    worker.run()

    assert emitted == [result]
    assert calls[0][0].repo_root == tmp_path
    assert calls[0][0].offline_manifest_path == manifest_path
    assert calls[0][0].release_channel == "stable"
    assert calls[0][1]["command_runner"] == "runner"
    assert fallback_calls == []


def test_app_rollback_check_worker_uses_rollback_check_helper(tmp_path, monkeypatch, qapp):
    calls = []
    result = SimpleNamespace(status="rollback_available", message="rollback ready")
    manifest_path = tmp_path / "LabCraftUpdates" / "rollback.json"

    def fake_rollback_check(config, **kwargs):
        calls.append((config, kwargs))
        return result

    monkeypatch.setattr(updater_mod, "run_rollback_check", fake_rollback_check)
    worker = controller_mod.AppRollbackCheckWorker(tmp_path, command_runner="runner", offline_manifest_path=manifest_path)
    emitted = []
    worker.finished.connect(emitted.append)

    worker.run()

    assert emitted == [result]
    assert calls[0][0].repo_root == tmp_path
    assert calls[0][0].rollback is True
    assert calls[0][0].offline_manifest_path == manifest_path
    assert calls[0][1]["command_runner"] == "runner"


def test_controller_start_offline_app_update_check_passes_manifest(tmp_path, monkeypatch, qapp):
    controller = _make_controller(tmp_path)
    manifest_path = tmp_path / "LabCraftUpdates" / "update.json"
    created = []
    started = []
    controller.app_update_check_started = SimpleNamespace(emit=lambda: started.append(True))

    class FakeThread:
        def __init__(self, parent=None):
            self.parent = parent
            self.started = SimpleNamespace(connect=lambda callback: setattr(self, "_started_callback", callback))
            self.finished = SimpleNamespace(connect=lambda callback: None)

        def start(self):
            started.append("thread")

        def isRunning(self):
            return False

        def quit(self):
            pass

        def deleteLater(self):
            pass

    class FakeWorker:
        def __init__(self, repo_root, command_runner=None, offline_manifest_path=None, release_channel="stable"):
            created.append((Path(repo_root), command_runner, Path(offline_manifest_path), release_channel))
            self.finished = SimpleNamespace(connect=lambda callback: None)

        def moveToThread(self, thread):
            pass

        def run(self):
            pass

        def deleteLater(self):
            pass

    monkeypatch.setattr(controller_mod.QtCore, "QThread", FakeThread)
    monkeypatch.setattr(controller_mod, "AppUpdateCheckWorker", FakeWorker)

    ok, message = controller.start_offline_app_update_check(manifest_path, command_runner="runner")

    assert ok is True
    assert "started" in message
    assert created == [(tmp_path, "runner", manifest_path, "stable")]
    assert started


def test_controller_start_app_update_check_passes_release_candidate_channel(tmp_path, monkeypatch, qapp):
    controller = _make_controller(tmp_path)
    created = []
    started = []
    controller.app_update_check_started = SimpleNamespace(emit=lambda: started.append(True))

    class FakeThread:
        def __init__(self, parent=None):
            self.parent = parent
            self.started = SimpleNamespace(connect=lambda callback: setattr(self, "_started_callback", callback))
            self.finished = SimpleNamespace(connect=lambda callback: None)

        def start(self):
            started.append("thread")

        def isRunning(self):
            return False

        def quit(self):
            pass

        def deleteLater(self):
            pass

    class FakeWorker:
        def __init__(self, repo_root, command_runner=None, offline_manifest_path=None, release_channel="stable"):
            created.append((Path(repo_root), command_runner, offline_manifest_path, release_channel))
            self.finished = SimpleNamespace(connect=lambda callback: None)

        def moveToThread(self, thread):
            pass

        def run(self):
            pass

        def deleteLater(self):
            pass

    monkeypatch.setattr(controller_mod.QtCore, "QThread", FakeThread)
    monkeypatch.setattr(controller_mod, "AppUpdateCheckWorker", FakeWorker)

    ok, message = controller.start_app_update_check(command_runner="runner", release_channel="release_candidate")

    assert ok is True
    assert "started" in message
    assert created == [(tmp_path, "runner", None, "release_candidate")]
    assert started


def test_controller_start_offline_app_rollback_check_passes_manifest(tmp_path, monkeypatch, qapp):
    controller = _make_controller(tmp_path)
    manifest_path = tmp_path / "LabCraftUpdates" / "rollback.json"
    created = []
    started = []
    controller.app_update_check_started = SimpleNamespace(emit=lambda: started.append(True))

    class FakeThread:
        def __init__(self, parent=None):
            self.parent = parent
            self.started = SimpleNamespace(connect=lambda callback: setattr(self, "_started_callback", callback))
            self.finished = SimpleNamespace(connect=lambda callback: None)

        def start(self):
            started.append("thread")

        def isRunning(self):
            return False

        def quit(self):
            pass

        def deleteLater(self):
            pass

    class FakeWorker:
        def __init__(self, repo_root, command_runner=None, offline_manifest_path=None):
            created.append((Path(repo_root), command_runner, Path(offline_manifest_path)))
            self.finished = SimpleNamespace(connect=lambda callback: None)

        def moveToThread(self, thread):
            pass

        def run(self):
            pass

        def deleteLater(self):
            pass

    monkeypatch.setattr(controller_mod.QtCore, "QThread", FakeThread)
    monkeypatch.setattr(controller_mod, "AppRollbackCheckWorker", FakeWorker)

    ok, message = controller.start_offline_app_rollback_check(manifest_path, command_runner="runner")

    assert ok is True
    assert "started" in message
    assert created == [(tmp_path, "runner", manifest_path)]
    assert started


def test_controller_launch_success_stores_process(tmp_path):
    controller = _make_controller(tmp_path)
    process = FakeProcess()
    calls = []

    def launcher(command, *, cwd):
        calls.append((command, cwd))
        return process

    ok, message = controller.launch_app_updater(wait_pid=99, launcher=launcher)

    assert ok is True
    assert "started" in message
    assert controller._app_update_process is process
    assert controller.is_app_update_process_running() is True
    assert calls[0][1] == tmp_path


def test_controller_launch_rollback_success_stores_process(tmp_path):
    controller = _make_controller(tmp_path)
    process = FakeProcess()
    calls = []

    def launcher(command, *, cwd):
        calls.append((command, cwd))
        return process

    ok, message = controller.launch_app_rollback(wait_pid=99, launcher=launcher)

    assert ok is True
    assert "rollback started" in message
    assert controller._app_update_process is process
    assert "--rollback" in calls[0][0]
    assert calls[0][1] == tmp_path


def test_controller_launch_failure_does_not_mark_update_running(tmp_path):
    controller = _make_controller(tmp_path)

    def launcher(command, *, cwd):
        raise OSError("boom")

    ok, message = controller.launch_app_updater(wait_pid=99, launcher=launcher)

    assert ok is False
    assert "boom" in message
    assert controller._app_update_process is None
    assert controller.is_app_update_process_running() is False


def test_controller_default_launcher_uses_detached_process_and_log(tmp_path, monkeypatch):
    controller = _make_controller(tmp_path)
    controller._app_update_launch_grace_s = 0
    controller._resolve_app_update_python = lambda: "python-under-test"
    controller._last_app_update_python_probe_lines = ("python-under-test: PySide6 OK",)
    popen_calls = []
    process = FakeProcess()
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setenv("QT_QPA_PLATFORM_PLUGIN_PATH", "/home/labcraft/LabCraft_printer/env/lib/python3.11/site-packages/cv2/qt/plugins")
    monkeypatch.setenv("QT_QPA_FONTDIR", "/home/labcraft/LabCraft_printer/env/lib/python3.11/site-packages/cv2/qt/fonts")
    monkeypatch.setenv("QT_PLUGIN_PATH", "/bad/plugin/path")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XAUTHORITY", "/home/labcraft/.Xauthority")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")

    def fake_popen(command, **kwargs):
        popen_calls.append((command, kwargs))
        return process

    monkeypatch.setattr(controller_mod.subprocess, "Popen", fake_popen)

    ok, message = controller.launch_app_updater(wait_pid=99)

    assert ok is True
    assert "started" in message
    assert controller._app_update_process is process
    assert len(popen_calls) == 1
    command, kwargs = popen_calls[0]
    assert command[0] == "python-under-test"
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["shell"] is False
    assert kwargs["stdin"] is controller_mod.subprocess.DEVNULL
    assert kwargs["stderr"] is controller_mod.subprocess.STDOUT
    assert kwargs["close_fds"] is True
    env = kwargs["env"]
    assert "QT_QPA_PLATFORM_PLUGIN_PATH" not in env
    assert "QT_QPA_FONTDIR" not in env
    assert "QT_PLUGIN_PATH" not in env
    assert env["DISPLAY"] == ":0"
    assert env["WAYLAND_DISPLAY"] == "wayland-0"
    assert env["XAUTHORITY"] == "/home/labcraft/.Xauthority"
    assert env["XDG_RUNTIME_DIR"] == "/run/user/1000"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1000/bus"
    assert env["PYTHONUNBUFFERED"] == "1"
    if controller_mod.os.name == "nt":
        assert kwargs["creationflags"]
    else:
        assert kwargs["start_new_session"] is True

    log_files = list((tmp_path / "local" / "update_logs").glob("app_update_launcher_updater_*.log"))
    assert len(log_files) == 1
    log_text = log_files[0].read_text(encoding="utf-8")
    assert f"cwd: {tmp_path}" in log_text
    assert "command: python-under-test -u" in log_text
    assert "python_probe:" in log_text
    assert "python-under-test: PySide6 OK" in log_text
    assert "sanitized_qt_environment:" in log_text
    assert "removed QT_QPA_PLATFORM_PLUGIN_PATH=" in log_text
    assert "removed QT_QPA_FONTDIR=" in log_text
    assert "removed QT_PLUGIN_PATH=" in log_text


def test_controller_default_launcher_reports_immediate_exit(tmp_path, monkeypatch):
    controller = _make_controller(tmp_path)
    controller._app_update_launch_grace_s = 0
    controller._resolve_app_update_python = lambda: "python-under-test"
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(controller_mod.subprocess, "Popen", lambda *args, **kwargs: FakeProcess(running=False))

    ok, message = controller.launch_app_updater(wait_pid=99)

    assert ok is False
    assert "exited immediately" in message
    assert "Launcher log:" in message
    assert controller._app_update_process is None
    log_files = list((tmp_path / "local" / "update_logs").glob("app_update_launcher_updater_*.log"))
    assert len(log_files) == 1


def test_controller_default_launcher_failure_includes_launcher_log(tmp_path, monkeypatch):
    controller = _make_controller(tmp_path)
    controller._app_update_launch_grace_s = 0
    controller._resolve_app_update_python = lambda: "python-under-test"
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)

    def fake_popen(command, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(controller_mod.subprocess, "Popen", fake_popen)

    ok, message = controller.launch_app_updater(wait_pid=99)

    assert ok is False
    assert "boom" in message
    assert "Launcher log:" in message
    assert controller._app_update_process is None
    log_files = list((tmp_path / "local" / "update_logs").glob("app_update_launcher_updater_*.log"))
    assert len(log_files) == 1
    assert "launch_error: boom" in log_files[0].read_text(encoding="utf-8")


def test_controller_launch_fails_before_spawn_without_gui_python(tmp_path, monkeypatch):
    controller = _make_controller(tmp_path)
    fake_python = tmp_path / "python-under-test"
    fake_python.write_text("", encoding="utf-8")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(controller_mod.sys, "executable", str(fake_python))
    monkeypatch.setattr(
        controller,
        "_probe_app_update_python",
        lambda path: (False, f"{path}: PySide6 unavailable (No module named 'PySide6')"),
    )
    monkeypatch.setattr(
        controller_mod.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("updater process should not be spawned"),
    )

    ok, message = controller.launch_app_updater(wait_pid=99)

    assert ok is False
    assert "No Python environment with PySide6" in message
    assert "Launcher log:" in message
    assert controller._app_update_process is None
    log_files = list((tmp_path / "local" / "update_logs").glob("app_update_launcher_updater_*.log"))
    assert len(log_files) == 1
    log_text = log_files[0].read_text(encoding="utf-8")
    assert "python_probe:" in log_text
    assert "PySide6 unavailable" in log_text
    assert "launch_error:" in log_text


def test_controller_cancel_app_update_process_terminates_running_process(tmp_path):
    controller = _make_controller(tmp_path)
    process = FakeProcess()
    controller._app_update_process = process

    controller.cancel_app_update_process()

    assert process.terminated is True
    assert controller._app_update_process is None


def test_controller_app_update_blockers_cover_busy_states(tmp_path):
    controller = _make_controller(tmp_path)
    controller._app_update_process = FakeProcess()
    controller._dfu_thread = SimpleNamespace(isRunning=lambda: True)
    controller._qualification_worker = SimpleNamespace(isRunning=lambda: True)
    controller._array_state = "running"
    controller._seq_state = "countdown"
    controller.check_if_all_completed = lambda: False
    controller.pending_capture_active = True
    controller.model.calibration_manager = _idle_calibration_manager(
        activeCalibration=object(),
        calibration_queue=["NozzlePosition"],
        is_pulsewidth_sweep_active=lambda: True,
        get_stream_gravimetric_capture_state=lambda: {"status": "pending_loading_move"},
        get_stream_calibration_sequence_state=lambda: {"status": "running"},
        get_droplet_calibration_sequence_state=lambda: {"status": "pending_gripper_restore"},
    )

    blockers = controller.get_app_update_blockers()

    assert "An application update or rollback is already running." in blockers
    assert "Firmware update is running." in blockers
    assert "Machine qualification is running." in blockers
    assert "Print array state is running." in blockers
    assert "Preprogrammed sequence state is countdown." in blockers
    assert "Command queue is not empty." in blockers
    assert "Image capture is active." in blockers
    assert "Calibration is active." in blockers
    assert "Calibration queue is not empty." in blockers
    assert "Pulse-width sweep is active." in blockers
    assert "Stream gravimetric capture state is pending_loading_move." in blockers
    assert "Stream calibration sequence state is running." in blockers
    assert "Droplet calibration sequence state is pending_gripper_restore." in blockers


def _make_update_mainwindow(controller, *, popup_response=QMessageBox.StandardButton.Yes):
    messages = []
    close_calls = {"count": 0}
    window = MainWindow.__new__(MainWindow)
    window.controller = controller
    window._app_update_close_requested = False
    window.popup_yes_no = lambda *args, **kwargs: popup_response
    window.popup_message = lambda title, message: messages.append((title, message))
    window.close = lambda: close_calls.__setitem__("count", close_calls["count"] + 1)
    window.messages = messages
    window.close_calls = close_calls
    return window


class _FakeLabel:
    def __init__(self):
        self.text_value = ""

    def setText(self, value):
        self.text_value = str(value)


class _FakeButton:
    def __init__(self):
        self.enabled = True
        self.style_value = ""

    def setEnabled(self, value):
        self.enabled = bool(value)

    def setStyleSheet(self, value):
        self.style_value = str(value)


class _FakeCheckBox(_FakeButton):
    def __init__(self, checked=False):
        super().__init__()
        self.checked = bool(checked)

    def isChecked(self):
        return self.checked

    def setChecked(self, value):
        self.checked = bool(value)


def test_mainwindow_request_app_update_cancels_when_user_says_no(qapp):
    controller = SimpleNamespace(
        get_app_update_blockers=lambda: [],
        launch_app_updater=lambda wait_pid: pytest.fail("updater should not launch"),
    )
    window = _make_update_mainwindow(controller, popup_response=QMessageBox.StandardButton.No)

    assert MainWindow.request_app_update(window) is False
    assert window.close_calls["count"] == 0
    assert window._app_update_close_requested is False


def test_mainwindow_request_app_update_launches_and_closes(qapp, monkeypatch):
    calls = []
    controller = SimpleNamespace(
        get_app_update_blockers=lambda: [],
        launch_app_updater=lambda wait_pid: calls.append(wait_pid) or (True, "started"),
    )
    window = _make_update_mainwindow(controller)
    monkeypatch.setattr(view_mod.os, "getpid", lambda: 777)

    assert MainWindow.request_app_update(window) is True
    assert calls == [777]
    assert window.close_calls["count"] == 1
    assert window._app_update_close_requested is True


def test_mainwindow_request_app_update_confirmation_mentions_offline_source(qapp, monkeypatch):
    calls = []
    prompts = []
    controller = SimpleNamespace(
        get_last_app_update_check_result=lambda: SimpleNamespace(
            status="update_available",
            update_source="offline",
            offline_manifest_path="E:/LabCraftUpdates/update.json",
        ),
        get_app_update_blockers=lambda: [],
        launch_app_updater=lambda wait_pid: calls.append(wait_pid) or (True, "started"),
    )
    window = _make_update_mainwindow(controller)
    window.popup_yes_no = lambda title, message: prompts.append((title, message)) or QMessageBox.StandardButton.Yes
    monkeypatch.setattr(view_mod.os, "getpid", lambda: 777)

    assert MainWindow.request_app_update(window) is True
    assert calls == [777]
    assert "offline update bundle" in prompts[0][1]


def test_mainwindow_request_app_update_confirmation_mentions_release_candidate(qapp, monkeypatch):
    calls = []
    prompts = []
    controller = SimpleNamespace(
        get_last_app_update_check_result=lambda: SimpleNamespace(
            status="update_available",
            update_source="online",
            target_release_version="v1.2.0-rc.3",
        ),
        get_app_update_blockers=lambda: [],
        launch_app_updater=lambda wait_pid: calls.append(wait_pid) or (True, "started"),
    )
    window = _make_update_mainwindow(controller)
    window.popup_yes_no = lambda title, message: prompts.append((title, message)) or QMessageBox.StandardButton.Yes
    monkeypatch.setattr(view_mod.os, "getpid", lambda: 777)

    assert MainWindow.request_app_update(window) is True
    assert calls == [777]
    assert "selected release candidate" in prompts[0][1]
    assert "support-guided testing" in prompts[0][1]
    assert "Firmware will not be updated." in prompts[0][1]


def test_mainwindow_request_app_update_launch_failure_stays_open(qapp):
    controller = SimpleNamespace(
        get_app_update_blockers=lambda: [],
        launch_app_updater=lambda wait_pid: (False, "launch failed"),
    )
    window = _make_update_mainwindow(controller)

    assert MainWindow.request_app_update(window) is False
    assert window.close_calls["count"] == 0
    assert window._app_update_close_requested is False
    assert window.messages == [("Cannot Update App", "launch failed")]


def test_mainwindow_request_app_update_blocker_stays_open(qapp):
    controller = SimpleNamespace(
        get_app_update_blockers=lambda: ["Firmware update is running."],
        launch_app_updater=lambda wait_pid: pytest.fail("updater should not launch"),
    )
    window = _make_update_mainwindow(controller)

    assert MainWindow.request_app_update(window) is False
    assert window.close_calls["count"] == 0
    assert window._app_update_close_requested is False
    assert window.messages
    assert "Firmware update is running." in window.messages[0][1]


def test_mainwindow_request_app_update_requires_update_check_when_supported(qapp):
    controller = SimpleNamespace(
        get_last_app_update_check_result=lambda: None,
        get_app_update_blockers=lambda: [],
        launch_app_updater=lambda wait_pid: pytest.fail("updater should not launch"),
    )
    window = _make_update_mainwindow(controller)

    assert MainWindow.request_app_update(window) is False
    assert window.messages == [("Check for Updates", "Check for updates before starting an app update.")]
    assert window.close_calls["count"] == 0


def test_mainwindow_request_app_update_blocks_when_check_is_up_to_date(qapp):
    controller = SimpleNamespace(
        get_last_app_update_check_result=lambda: SimpleNamespace(status="up_to_date", message="LabCraft is up to date."),
        get_app_update_blockers=lambda: [],
        launch_app_updater=lambda wait_pid: pytest.fail("updater should not launch"),
    )
    window = _make_update_mainwindow(controller)

    assert MainWindow.request_app_update(window) is False
    assert window.messages == [("No Update Available", "LabCraft is up to date.")]
    assert window.close_calls["count"] == 0


def test_mainwindow_request_app_rollback_requires_rollback_check(qapp):
    controller = SimpleNamespace(
        get_last_app_rollback_check_result=lambda: None,
        get_app_update_blockers=lambda: [],
        launch_app_rollback=lambda wait_pid: pytest.fail("rollback should not launch"),
    )
    window = _make_update_mainwindow(controller)

    assert MainWindow.request_app_rollback(window) is False
    assert window.messages == [("Check Rollback", "Check rollback before restoring a previous app version.")]
    assert window.close_calls["count"] == 0


def test_mainwindow_request_app_rollback_launches_and_closes(qapp, monkeypatch):
    calls = []
    prompts = []
    controller = SimpleNamespace(
        get_last_app_rollback_check_result=lambda: SimpleNamespace(
            status="rollback_available",
            update_source="online",
            before_release_version="v1.2.0",
            after_release_version="v1.1.2",
            target_release_version="v1.1.2",
        ),
        get_app_update_blockers=lambda: [],
        launch_app_rollback=lambda wait_pid: calls.append(wait_pid) or (True, "started"),
    )
    window = _make_update_mainwindow(controller)
    window.popup_yes_no = lambda title, message: prompts.append((title, message)) or QMessageBox.StandardButton.Yes
    monkeypatch.setattr(view_mod.os, "getpid", lambda: 777)

    assert MainWindow.request_app_rollback(window) is True

    assert calls == [777]
    assert window.close_calls["count"] == 1
    assert window._app_update_close_requested is True
    assert prompts[0][0] == "Restore Previous App Version"
    assert "v1.2.0 -> v1.1.2" in prompts[0][1]
    assert "Firmware will not be updated" in prompts[0][1]
    assert "support guidance" in prompts[0][1]


def test_mainwindow_request_app_rollback_blocker_stays_open(qapp):
    controller = SimpleNamespace(
        get_last_app_rollback_check_result=lambda: SimpleNamespace(
            status="rollback_available",
            before_release_version="v1.2.0",
            after_release_version="v1.1.2",
        ),
        get_app_update_blockers=lambda: ["Firmware update is running."],
        launch_app_rollback=lambda wait_pid: pytest.fail("rollback should not launch"),
    )
    window = _make_update_mainwindow(controller)

    assert MainWindow.request_app_rollback(window) is False
    assert window.close_calls["count"] == 0
    assert "Firmware update is running." in window.messages[0][1]


def test_mainwindow_request_app_rollback_no_available_result_stays_open(qapp):
    controller = SimpleNamespace(
        get_last_app_rollback_check_result=lambda: SimpleNamespace(status="rollback_not_configured", message="No rollback."),
        get_app_update_blockers=lambda: [],
        launch_app_rollback=lambda wait_pid: pytest.fail("rollback should not launch"),
    )
    window = _make_update_mainwindow(controller)

    assert MainWindow.request_app_rollback(window) is False
    assert window.messages == [("No Rollback Available", "No rollback.")]
    assert window.close_calls["count"] == 0


def test_mainwindow_request_app_update_check_starts_controller_check(qapp):
    calls = []
    controller = SimpleNamespace(
        get_app_update_blockers=lambda: [],
        start_app_update_check=lambda release_channel="stable": calls.append(release_channel) or (True, "started"),
    )
    window = _make_update_mainwindow(controller)

    assert MainWindow.request_app_update_check(window) is True
    assert calls == ["stable"]
    assert window.messages == []


def test_mainwindow_request_app_update_check_passes_release_candidate_channel(qapp):
    calls = []
    controller = SimpleNamespace(
        get_app_update_blockers=lambda: [],
        start_app_update_check=lambda release_channel="stable": calls.append(release_channel) or (True, "started"),
    )
    window = _make_update_mainwindow(controller)

    assert MainWindow.request_app_update_check(window, release_channel="release_candidate") is True
    assert calls == ["release_candidate"]
    assert window.messages == []


def test_mainwindow_request_app_update_check_blocks_when_busy(qapp):
    controller = SimpleNamespace(
        get_app_update_blockers=lambda: ["Command queue is not empty."],
        start_app_update_check=lambda: pytest.fail("check should not start"),
    )
    window = _make_update_mainwindow(controller)

    assert MainWindow.request_app_update_check(window) is False
    assert "Command queue is not empty." in window.messages[0][1]


def test_mainwindow_request_app_rollback_check_starts_controller_check(qapp):
    calls = {"count": 0}
    controller = SimpleNamespace(
        get_app_update_blockers=lambda: [],
        start_app_rollback_check=lambda: calls.__setitem__("count", calls["count"] + 1) or (True, "started"),
    )
    window = _make_update_mainwindow(controller)

    assert MainWindow.request_app_rollback_check(window) is True
    assert calls["count"] == 1
    assert window.messages == []


def test_mainwindow_request_app_rollback_check_blocks_when_busy(qapp):
    controller = SimpleNamespace(
        get_app_update_blockers=lambda: ["Command queue is not empty."],
        start_app_rollback_check=lambda: pytest.fail("rollback check should not start"),
    )
    window = _make_update_mainwindow(controller)

    assert MainWindow.request_app_rollback_check(window) is False
    assert "Command queue is not empty." in window.messages[0][1]


def test_mainwindow_request_offline_app_update_cancel_does_not_start(qapp, monkeypatch):
    controller = SimpleNamespace(
        get_app_update_blockers=lambda: [],
        start_offline_app_update_check=lambda manifest_path: pytest.fail("offline check should not start"),
    )
    window = _make_update_mainwindow(controller)
    monkeypatch.setattr(view_mod.QFileDialog, "getOpenFileName", lambda *args, **kwargs: ("", ""))

    assert MainWindow.request_offline_app_update(window) is False
    assert window.messages == []


def test_mainwindow_request_offline_app_update_starts_selected_manifest(qapp, tmp_path):
    calls = []
    manifest_path = tmp_path / "LabCraftUpdates" / "update.json"
    controller = SimpleNamespace(
        get_app_update_blockers=lambda: [],
        start_offline_app_update_check=lambda selected: calls.append(Path(selected)) or (True, "started"),
    )
    window = _make_update_mainwindow(controller)

    assert MainWindow.request_offline_app_update(window, manifest_path=manifest_path) is True
    assert calls == [manifest_path]
    assert window.messages == []


def test_mainwindow_request_offline_app_update_blocks_when_busy(qapp, tmp_path):
    controller = SimpleNamespace(
        get_app_update_blockers=lambda: ["Firmware update is running."],
        start_offline_app_update_check=lambda manifest_path: pytest.fail("offline check should not start"),
    )
    window = _make_update_mainwindow(controller)

    assert MainWindow.request_offline_app_update(window, manifest_path=tmp_path / "update.json") is False
    assert "Firmware update is running." in window.messages[0][1]


def test_mainwindow_request_offline_app_update_start_failure(qapp, tmp_path):
    controller = SimpleNamespace(
        get_app_update_blockers=lambda: [],
        start_offline_app_update_check=lambda manifest_path: (False, "already running"),
    )
    window = _make_update_mainwindow(controller)

    assert MainWindow.request_offline_app_update(window, manifest_path=tmp_path / "update.json") is False
    assert window.messages == [("Cannot Install Offline Bundle", "already running")]


def test_mainwindow_request_offline_app_rollback_cancel_does_not_start(qapp, monkeypatch):
    controller = SimpleNamespace(
        get_app_update_blockers=lambda: [],
        start_offline_app_rollback_check=lambda manifest_path: pytest.fail("offline rollback check should not start"),
    )
    window = _make_update_mainwindow(controller)
    monkeypatch.setattr(view_mod.QFileDialog, "getOpenFileName", lambda *args, **kwargs: ("", ""))

    assert MainWindow.request_offline_app_rollback(window) is False
    assert window.messages == []


def test_mainwindow_request_offline_app_rollback_starts_selected_manifest(qapp, tmp_path):
    calls = []
    manifest_path = tmp_path / "LabCraftUpdates" / "rollback.json"
    controller = SimpleNamespace(
        get_app_update_blockers=lambda: [],
        start_offline_app_rollback_check=lambda selected: calls.append(Path(selected)) or (True, "started"),
    )
    window = _make_update_mainwindow(controller)

    assert MainWindow.request_offline_app_rollback(window, manifest_path=manifest_path) is True
    assert calls == [manifest_path]
    assert window.messages == []


def test_mainwindow_request_offline_app_rollback_blocks_when_busy(qapp, tmp_path):
    controller = SimpleNamespace(
        get_app_update_blockers=lambda: ["Firmware update is running."],
        start_offline_app_rollback_check=lambda manifest_path: pytest.fail("offline rollback check should not start"),
    )
    window = _make_update_mainwindow(controller)

    assert MainWindow.request_offline_app_rollback(window, manifest_path=tmp_path / "rollback.json") is False
    assert "Firmware update is running." in window.messages[0][1]


def _make_speed_tab_for_update_check():
    tab = SpeedProfilesTab.__new__(SpeedProfilesTab)
    tab.color_dict = {"light_blue": "#55AAFF"}
    tab.app_update_status_label = _FakeLabel()
    tab.app_update_release_candidate_checkbox = _FakeCheckBox()
    tab.app_update_check_button = _FakeButton()
    tab.app_update_offline_button = _FakeButton()
    tab.app_update_button = _FakeButton()
    tab.app_rollback_check_button = _FakeButton()
    tab.app_rollback_offline_button = _FakeButton()
    tab.app_rollback_button = _FakeButton()
    tab.controller = SimpleNamespace(get_app_update_blockers=lambda: [])
    tab.main_window = SimpleNamespace(messages=[], popup_message=lambda title, message: tab.main_window.messages.append((title, message)))
    return tab


class _FirmwareTabMachineModel(view_mod.QtCore.QObject):
    speeds_changed = view_mod.QtCore.Signal(object)
    accelerations_changed = view_mod.QtCore.Signal(object)

    def get_current_speeds(self):
        return (1000, 1000, 1000)

    def get_current_accelerations(self):
        return (1000, 1000, 1000)


class _FirmwareTabMachine(view_mod.QtCore.QObject):
    log_stats_updated = view_mod.QtCore.Signal(object)
    log_message_received = view_mod.QtCore.Signal(str)


class _FirmwareTabController(view_mod.QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.machine = _FirmwareTabMachine()

    def get_app_version(self):
        return "v1.1.5"


def test_speed_tab_constructs_maintenance_layout_without_speed_controls(qapp):
    main_window = view_mod.QtWidgets.QWidget()
    main_window.color_dict = {"darker_gray": "#222222"}
    main_window.popup_message = lambda *_args: None
    main_window.popup_yes_no = lambda *_args: QMessageBox.StandardButton.No
    main_window._is_yes_response = lambda _response: False
    model = SimpleNamespace(machine_model=_FirmwareTabMachineModel())
    controller = _FirmwareTabController()

    tab = SpeedProfilesTab(main_window, model, controller, {"darker_gray": "#222222"})

    assert tab.findChild(view_mod.QtWidgets.QWidget, "firmwareMaintenanceActions") is not None
    assert tab.findChild(view_mod.QtWidgets.QWidget, "firmwareMaintenanceMonitor") is not None
    assert tab.findChild(view_mod.QtWidgets.QGroupBox, "firmwareUpdateGroup") is not None
    assert tab.findChild(view_mod.QtWidgets.QGroupBox, "applicationUpdateGroup") is not None
    assert tab.findChild(view_mod.QtWidgets.QGroupBox, "serviceGroup") is not None
    assert tab.findChild(view_mod.QtWidgets.QGroupBox, "logMessagesGroup") is not None
    assert tab.findChild(view_mod.QtWidgets.QGroupBox, "mcuTaskUsageGroup") is not None
    assert tab.app_update_check_button.text() == "Check Updates"
    assert tab.app_update_offline_button.text() == "Install Bundle"
    assert tab.app_rollback_offline_button.text() == "Offline Restore"
    assert tab.app_rollback_button.text() == "Restore Previous"
    assert tab.app_update_button.isEnabled() is False
    assert tab.app_rollback_button.isEnabled() is False
    assert tab.findChildren(view_mod.QtWidgets.QSpinBox) == []
    assert not hasattr(tab, "_speed_boxes")
    assert not hasattr(tab, "_accel_boxes")

    tab.close()


def test_speed_tab_formats_current_app_version_label(qapp):
    tab = SpeedProfilesTab.__new__(SpeedProfilesTab)
    tab.controller = SimpleNamespace(get_app_version=lambda: "v1.1.2")

    assert SpeedProfilesTab._format_current_app_version_label(tab) == "Current version: v1.1.2"


def test_speed_tab_current_app_version_label_falls_back_to_unknown(qapp):
    tab = SpeedProfilesTab.__new__(SpeedProfilesTab)
    tab.controller = SimpleNamespace(get_app_version=lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    assert SpeedProfilesTab._format_current_app_version_label(tab) == "Current version: unknown"


def test_speed_tab_update_check_started_disables_update_controls(qapp):
    tab = _make_speed_tab_for_update_check()
    tab.app_update_button.setStyleSheet("background-color: #55AAFF; color: white;")
    tab.app_rollback_button.setStyleSheet("background-color: #55AAFF; color: white;")

    SpeedProfilesTab._on_app_update_check_started(tab)

    assert tab.app_update_status_label.text_value == "Checking for updates..."
    assert tab.app_update_release_candidate_checkbox.enabled is False
    assert tab.app_update_check_button.enabled is False
    assert tab.app_update_offline_button.enabled is False
    assert tab.app_update_button.enabled is False
    assert tab.app_rollback_check_button.enabled is False
    assert tab.app_rollback_offline_button.enabled is False
    assert tab.app_rollback_button.enabled is False
    assert tab.app_update_button.style_value == ""
    assert tab.app_rollback_button.style_value == ""


def test_speed_tab_offline_update_check_started_uses_offline_status(qapp):
    tab = _make_speed_tab_for_update_check()
    tab._app_update_check_mode = "offline"

    SpeedProfilesTab._on_app_update_check_started(tab)

    assert tab.app_update_status_label.text_value == "Checking offline bundle..."
    assert tab.app_update_release_candidate_checkbox.enabled is False
    assert tab.app_update_check_button.enabled is False
    assert tab.app_update_offline_button.enabled is False
    assert tab.app_update_button.enabled is False
    assert tab.app_rollback_check_button.enabled is False
    assert tab.app_rollback_offline_button.enabled is False
    assert tab.app_rollback_button.enabled is False


def test_speed_tab_rollback_check_started_uses_rollback_status(qapp):
    tab = _make_speed_tab_for_update_check()
    tab._app_update_check_mode = "rollback"

    SpeedProfilesTab._on_app_update_check_started(tab)

    assert tab.app_update_status_label.text_value == "Checking rollback target..."
    assert tab.app_update_release_candidate_checkbox.enabled is False
    assert tab.app_update_check_button.enabled is False
    assert tab.app_update_offline_button.enabled is False
    assert tab.app_update_button.enabled is False
    assert tab.app_rollback_check_button.enabled is False
    assert tab.app_rollback_offline_button.enabled is False
    assert tab.app_rollback_button.enabled is False


def test_speed_tab_offline_rollback_check_started_uses_offline_rollback_status(qapp):
    tab = _make_speed_tab_for_update_check()
    tab._app_update_check_mode = "offline_rollback"

    SpeedProfilesTab._on_app_update_check_started(tab)

    assert tab.app_update_status_label.text_value == "Checking offline rollback bundle..."
    assert tab.app_update_release_candidate_checkbox.enabled is False
    assert tab.app_update_button.enabled is False
    assert tab.app_rollback_button.enabled is False


def test_speed_tab_release_candidate_check_started_uses_candidate_status(qapp):
    tab = _make_speed_tab_for_update_check()
    tab._app_update_check_mode = "release_candidate"

    SpeedProfilesTab._on_app_update_check_started(tab)

    assert tab.app_update_status_label.text_value == "Checking release candidate updates..."
    assert tab.app_update_release_candidate_checkbox.enabled is False
    assert tab.app_update_button.enabled is False
    assert tab.app_rollback_button.enabled is False


def test_speed_tab_online_update_button_requests_stable_check_by_default(qapp):
    tab = _make_speed_tab_for_update_check()
    calls = []
    tab.main_window.request_app_update_check = lambda release_channel="stable": calls.append(release_channel) or True

    SpeedProfilesTab._on_app_update_check_requested(tab)

    assert calls == ["stable"]
    assert tab._app_update_check_mode == "online"


def test_speed_tab_online_update_button_requests_release_candidate_when_checked(qapp):
    tab = _make_speed_tab_for_update_check()
    tab.app_update_release_candidate_checkbox.setChecked(True)
    calls = []
    tab.main_window.request_app_update_check = lambda release_channel="stable": calls.append(release_channel) or True

    SpeedProfilesTab._on_app_update_check_requested(tab)

    assert calls == ["release_candidate"]
    assert tab._app_update_check_mode == "release_candidate"


def test_speed_tab_release_candidate_toggle_disables_stale_actions(qapp):
    tab = _make_speed_tab_for_update_check()
    tab.app_update_button.setEnabled(True)
    tab.app_rollback_button.setEnabled(True)
    tab.app_update_button.setStyleSheet("background-color: #55AAFF; color: white;")
    tab.app_rollback_button.setStyleSheet("background-color: #55AAFF; color: white;")
    tab.app_update_status_label.setText("LabCraft v1.2.0-rc.3 is available.")

    SpeedProfilesTab._on_app_release_candidate_toggled(tab, True)

    assert tab.app_update_button.enabled is False
    assert tab.app_rollback_button.enabled is False
    assert tab.app_update_button.style_value == ""
    assert tab.app_rollback_button.style_value == ""
    assert tab.app_update_status_label.text_value == "Check for updates before updating."


def test_speed_tab_offline_update_button_requests_manifest_check(qapp):
    tab = _make_speed_tab_for_update_check()
    calls = []
    tab.main_window.request_offline_app_update = lambda: calls.append(True) or True

    SpeedProfilesTab._on_offline_app_update_requested(tab)

    assert calls == [True]
    assert tab._app_update_check_mode == "offline"


def test_speed_tab_offline_update_button_resets_mode_when_cancelled(qapp):
    tab = _make_speed_tab_for_update_check()
    tab.main_window.request_offline_app_update = lambda: False

    SpeedProfilesTab._on_offline_app_update_requested(tab)

    assert tab._app_update_check_mode == ""


def test_speed_tab_rollback_check_button_requests_rollback_check(qapp):
    tab = _make_speed_tab_for_update_check()
    calls = []
    tab.main_window.request_app_rollback_check = lambda: calls.append(True) or True

    SpeedProfilesTab._on_app_rollback_check_requested(tab)

    assert calls == [True]
    assert tab._app_update_check_mode == "rollback"


def test_speed_tab_offline_rollback_button_requests_manifest_check(qapp):
    tab = _make_speed_tab_for_update_check()
    calls = []
    tab.main_window.request_offline_app_rollback = lambda: calls.append(True) or True

    SpeedProfilesTab._on_offline_app_rollback_requested(tab)

    assert calls == [True]
    assert tab._app_update_check_mode == "offline_rollback"


def test_speed_tab_rollback_check_button_resets_mode_when_cancelled(qapp):
    tab = _make_speed_tab_for_update_check()
    tab.main_window.request_app_rollback_check = lambda: False

    SpeedProfilesTab._on_app_rollback_check_requested(tab)

    assert tab._app_update_check_mode == ""


def test_speed_tab_up_to_date_check_keeps_update_disabled(qapp):
    tab = _make_speed_tab_for_update_check()
    tab.app_update_button.setStyleSheet("background-color: #55AAFF; color: white;")
    tab.app_rollback_button.setStyleSheet("background-color: #55AAFF; color: white;")

    SpeedProfilesTab._on_app_update_check_finished(
        tab,
        SimpleNamespace(status="up_to_date", message="LabCraft is up to date.", commits=()),
    )

    assert tab.app_update_status_label.text_value == "LabCraft is up to date."
    assert tab.app_update_release_candidate_checkbox.enabled is True
    assert tab.app_update_check_button.enabled is True
    assert tab.app_update_offline_button.enabled is True
    assert tab.app_update_button.enabled is False
    assert tab.app_rollback_check_button.enabled is True
    assert tab.app_rollback_offline_button.enabled is True
    assert tab.app_rollback_button.enabled is False
    assert tab.app_update_button.style_value == ""
    assert tab.app_rollback_button.style_value == ""
    assert tab.main_window.messages == []


def test_speed_tab_update_available_enables_update_and_shows_commits(qapp):
    tab = _make_speed_tab_for_update_check()

    SpeedProfilesTab._on_app_update_check_finished(
        tab,
        SimpleNamespace(
            status="update_available",
            message="2 update commits available.",
            behind_count=2,
            commits=("def Add result popup", "abc Add check button"),
        ),
    )

    assert tab.app_update_status_label.text_value == "2 update commits available."
    assert tab.app_update_release_candidate_checkbox.enabled is True
    assert tab.app_update_button.enabled is True
    assert tab.app_update_button.style_value == "background-color: #55AAFF; color: white;"
    assert tab.app_rollback_button.enabled is False
    assert tab.app_rollback_button.style_value == ""
    assert tab.main_window.messages
    assert "def Add result popup" in tab.main_window.messages[0][1]


def test_speed_tab_update_available_with_blockers_does_not_highlight_update(qapp):
    tab = _make_speed_tab_for_update_check()
    tab.controller = SimpleNamespace(get_app_update_blockers=lambda: ["Firmware update is running."])

    SpeedProfilesTab._on_app_update_check_finished(
        tab,
        SimpleNamespace(
            status="update_available",
            message="LabCraft v1.1.7 is available.",
            behind_count=1,
            commits=("abc Highlight update action",),
        ),
    )

    assert tab.app_update_button.enabled is False
    assert tab.app_update_button.style_value == ""
    assert tab.app_rollback_button.enabled is False
    assert tab.app_rollback_button.style_value == ""


def test_speed_tab_rollback_available_enables_restore_and_shows_details(qapp):
    tab = _make_speed_tab_for_update_check()

    SpeedProfilesTab._on_app_update_check_finished(
        tab,
        SimpleNamespace(
            status="rollback_available",
            message="Rollback is available from v1.2.0 to v1.1.2.",
            update_source="online",
            before_release_version="v1.2.0",
            after_release_version="v1.1.2",
            target_release_version="v1.1.2",
            target_release_tag="v1.1.2",
            release_summary="Previous stable release.",
            release_notes=("Restores previous camera behavior.",),
        ),
    )

    assert tab.app_update_status_label.text_value == "Rollback is available from v1.2.0 to v1.1.2."
    assert tab.app_update_button.enabled is False
    assert tab.app_update_button.style_value == ""
    assert tab.app_rollback_button.enabled is True
    assert tab.app_rollback_button.style_value == "background-color: #55AAFF; color: white;"
    title, message = tab.main_window.messages[0]
    assert title == "Rollback Available"
    assert "Configured release rollback target" in message
    assert "Rollback: v1.2.0 -> v1.1.2" in message
    assert "Tag: v1.1.2" in message
    assert "Restores previous camera behavior." in message


def test_speed_tab_offline_rollback_available_shows_source_details(qapp, tmp_path):
    tab = _make_speed_tab_for_update_check()
    manifest_path = tmp_path / "LabCraftUpdates" / "rollback.json"

    SpeedProfilesTab._on_app_update_check_finished(
        tab,
        SimpleNamespace(
            status="rollback_available",
            message="Rollback is available from v1.2.0 to v1.1.2 using the offline bundle.",
            update_source="offline",
            offline_manifest_path=manifest_path,
            before_release_version="v1.2.0",
            after_release_version="v1.1.2",
            target_release_version="v1.1.2",
        ),
    )

    assert tab.app_update_button.enabled is False
    assert tab.app_update_button.style_value == ""
    assert tab.app_rollback_button.enabled is True
    assert tab.app_rollback_button.style_value == "background-color: #55AAFF; color: white;"
    title, message = tab.main_window.messages[0]
    assert title == "Rollback Available"
    assert "Offline rollback bundle" in message
    assert str(manifest_path) in message


def test_speed_tab_release_update_available_shows_release_details(qapp):
    tab = _make_speed_tab_for_update_check()

    SpeedProfilesTab._on_app_update_check_finished(
        tab,
        SimpleNamespace(
            status="update_available",
            message="LabCraft v1.1.2 is available.",
            update_source="online",
            target_release_version="v1.1.2",
            release_summary="Release-aware online updates.",
            release_notes=("Uses stable release tags.", "Leaves offline bundles unchanged."),
            rollback_version="v1.1.1",
            behind_count=2,
            commits=("def Release-aware updater", "abc Metadata display"),
        ),
    )

    assert tab.app_update_status_label.text_value == "LabCraft v1.1.2 is available."
    assert tab.app_update_button.enabled is True
    assert tab.app_update_button.style_value == "background-color: #55AAFF; color: white;"
    assert tab.app_rollback_button.enabled is False
    assert tab.app_rollback_button.style_value == ""
    title, message = tab.main_window.messages[0]
    assert title == "Updates Available"
    assert "Release: v1.1.2" in message
    assert "Summary: Release-aware online updates." in message
    assert "Uses stable release tags." in message
    assert "Rollback: v1.1.1" in message
    assert "def Release-aware updater" in message


def test_speed_tab_release_candidate_update_available_shows_warning(qapp):
    tab = _make_speed_tab_for_update_check()

    SpeedProfilesTab._on_app_update_check_finished(
        tab,
        SimpleNamespace(
            status="update_available",
            message="LabCraft v1.2.0-rc.3 is available.",
            update_source="online",
            target_release_version="v1.2.0-rc.3",
            release_summary="Camera refactor release candidate.",
            release_notes=("Adds camera refactor test code.",),
            rollback_version="v1.1.3",
            behind_count=2,
            commits=("def Camera refactor", "abc Manual refuel checks"),
        ),
    )

    assert tab.app_update_status_label.text_value == "LabCraft v1.2.0-rc.3 is available."
    assert tab.app_update_button.enabled is True
    assert tab.app_update_button.style_value == "background-color: #55AAFF; color: white;"
    title, message = tab.main_window.messages[0]
    assert title == "Updates Available"
    assert "Release: v1.2.0-rc.3" in message
    assert "Release candidate: support-guided test release" in message
    assert "Adds camera refactor test code." in message


def test_speed_tab_offline_update_available_shows_source_details(qapp, tmp_path):
    tab = _make_speed_tab_for_update_check()
    manifest_path = tmp_path / "LabCraftUpdates" / "update.json"

    SpeedProfilesTab._on_app_update_check_finished(
        tab,
        SimpleNamespace(
            status="update_available",
            message="1 offline update commit available.",
            update_source="offline",
            offline_manifest_path=manifest_path,
            behind_count=1,
            commits=("def Offline update",),
        ),
    )

    assert tab.app_update_button.enabled is True
    assert tab.app_update_button.style_value == "background-color: #55AAFF; color: white;"
    assert tab.app_rollback_button.enabled is False
    assert tab.app_rollback_button.style_value == ""
    title, message = tab.main_window.messages[0]
    assert title == "Updates Available"
    assert "Source: Offline bundle" in message
    assert str(manifest_path) in message


def test_speed_tab_offline_release_update_available_shows_release_details(qapp, tmp_path):
    tab = _make_speed_tab_for_update_check()
    manifest_path = tmp_path / "LabCraftUpdates" / "update.json"

    SpeedProfilesTab._on_app_update_check_finished(
        tab,
        SimpleNamespace(
            status="update_available",
            message="LabCraft v1.1.2 is available from the offline bundle.",
            update_source="offline",
            offline_manifest_path=manifest_path,
            target_release_version="v1.1.2",
            release_summary="Release-aware offline bundle.",
            release_notes=("Installs a named release from USB.",),
            rollback_version="v1.1.1",
            behind_count=1,
            commits=("def Offline release update",),
        ),
    )

    assert tab.app_update_button.enabled is True
    assert tab.app_update_button.style_value == "background-color: #55AAFF; color: white;"
    assert tab.app_rollback_button.enabled is False
    assert tab.app_rollback_button.style_value == ""
    title, message = tab.main_window.messages[0]
    assert title == "Updates Available"
    assert "Source: Offline bundle" in message
    assert str(manifest_path) in message
    assert "Release: v1.1.2" in message
    assert "Summary: Release-aware offline bundle." in message
    assert "Installs a named release from USB." in message
    assert "Rollback: v1.1.1" in message


def test_speed_tab_update_check_failure_keeps_update_disabled(qapp):
    tab = _make_speed_tab_for_update_check()
    tab.app_update_button.setStyleSheet("background-color: #55AAFF; color: white;")
    tab.app_rollback_button.setStyleSheet("background-color: #55AAFF; color: white;")

    SpeedProfilesTab._on_app_update_check_finished(
        tab,
        SimpleNamespace(status="fetch_failed", message="Update check could not contact the remote.", commits=()),
    )

    assert tab.app_update_status_label.text_value == "Update check could not contact the remote."
    assert tab.app_update_button.enabled is False
    assert tab.app_rollback_button.enabled is False
    assert tab.app_update_button.style_value == ""
    assert tab.app_rollback_button.style_value == ""


def test_mainwindow_init_does_not_schedule_startup_update_result():
    source = inspect.getsource(MainWindow.__init__)

    assert "show_pending_app_update_result" not in source


def test_mainwindow_startup_update_result_helper_schedules_after_startup(monkeypatch):
    window = _make_update_mainwindow(SimpleNamespace(_repo_root=Path(".")))
    calls = []

    def fake_single_shot(delay_ms, callback):
        calls.append((delay_ms, callback))

    window.show_pending_app_update_result = lambda: "shown"
    monkeypatch.setattr(view_mod.QTimer, "singleShot", fake_single_shot)

    MainWindow.show_pending_app_update_result_after_startup(window)

    assert calls == [(500, window.show_pending_app_update_result)]


def test_mainwindow_startup_update_result_popup_shows_once_and_clears_marker(qapp, tmp_path):
    result_path = tmp_path / "local" / "update_logs" / "latest_update_result.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text(
        json.dumps(
            {
                "status": "updated",
                "message": "LabCraft was updated successfully.",
                "before_sha": "abc",
                "after_sha": "def",
                "log_path": str(tmp_path / "local" / "update_logs" / "update.log"),
                "target_release_version": "v1.1.2",
                "target_release_tag": "v1.1.2",
                "commits": ["def Add result popup"],
            }
        ),
        encoding="utf-8",
    )
    window = _make_update_mainwindow(SimpleNamespace(_repo_root=tmp_path))
    popup_state = {}

    def popup_message(title, message):
        popup_state["marker_exists_during_popup"] = result_path.exists()
        window.messages.append((title, message))

    window.popup_message = popup_message

    assert MainWindow.show_pending_app_update_result(window) is True

    assert popup_state["marker_exists_during_popup"] is True
    assert result_path.exists() is False
    assert window.messages
    title, message = window.messages[0]
    assert title == "Application Update Result"
    assert "LabCraft was updated successfully." in message
    assert "Release: v1.1.2" in message
    assert "Tag: v1.1.2" in message
    assert "def Add result popup" in message


def test_mainwindow_startup_rollback_result_uses_rollback_title_and_message(qapp, tmp_path):
    result_path = tmp_path / "local" / "update_logs" / "latest_update_result.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text(
        json.dumps(
            {
                "operation": "rollback",
                "status": "rolled_back",
                "message": "LabCraft was rolled back from v1.2.0 to v1.1.2.",
                "before_release_version": "v1.2.0",
                "after_release_version": "v1.1.2",
                "target_release_version": "v1.1.2",
                "target_release_tag": "v1.1.2",
                "before_sha": "newer",
                "after_sha": "older",
                "commits": ["newer Removed by rollback"],
            }
        ),
        encoding="utf-8",
    )
    window = _make_update_mainwindow(SimpleNamespace(_repo_root=tmp_path))

    assert MainWindow.show_pending_app_update_result(window) is True

    assert window.messages
    title, message = window.messages[0]
    assert title == "Application Rollback Result"
    assert "Operation: Rollback" in message
    assert "Before release: v1.2.0" in message
    assert "After release: v1.1.2" in message
    assert "Rollback commits:" in message


def test_mainwindow_update_result_message_includes_offline_source(tmp_path):
    manifest_path = tmp_path / "LabCraftUpdates" / "update.json"

    message = MainWindow._format_app_update_result_message(
        {
            "status": "updated",
            "message": "LabCraft was updated successfully.",
            "update_source": "offline",
            "offline_manifest_path": str(manifest_path),
            "before_sha": "abc",
            "after_sha": "def",
        }
    )

    assert "Source: Offline bundle" in message
    assert f"Manifest: {manifest_path}" in message
