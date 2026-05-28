from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMessageBox

import Controller as controller_mod
import View as view_mod
from Controller import Controller
from View import MainWindow


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
    controller._array_state = "idle"
    controller._seq_state = "idle"
    controller.pending_capture_active = False
    controller.model = SimpleNamespace(calibration_manager=_idle_calibration_manager())
    controller.check_if_all_completed = lambda: True
    return controller


def test_controller_builds_update_command_with_relaunch_on_failure(tmp_path, monkeypatch):
    controller = _make_controller(tmp_path)
    monkeypatch.setattr(controller_mod.sys, "executable", "python-under-test")

    command = controller.build_app_update_command(wait_pid=1234)

    assert command == [
        "python-under-test",
        "-u",
        str((tmp_path / "tools" / "update_and_restart.py").resolve()),
        "--repo-root",
        str(tmp_path),
        "--wait-pid",
        "1234",
        "--relaunch-on-failure",
    ]


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


def test_controller_launch_failure_does_not_mark_update_running(tmp_path):
    controller = _make_controller(tmp_path)

    def launcher(command, *, cwd):
        raise OSError("boom")

    ok, message = controller.launch_app_updater(wait_pid=99, launcher=launcher)

    assert ok is False
    assert "boom" in message
    assert controller._app_update_process is None
    assert controller.is_app_update_process_running() is False


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

    assert "An application update is already running." in blockers
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
