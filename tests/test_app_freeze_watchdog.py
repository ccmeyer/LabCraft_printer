from __future__ import annotations

import sys
import threading
from types import SimpleNamespace

import App


class _Signal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self):
        for callback in list(self._callbacks):
            callback()


class _FakeTimer:
    instances = []

    def __init__(self, parent=None):
        self.parent = parent
        self.interval_ms = None
        self.started = False
        self.timeout = _Signal()
        self.__class__.instances.append(self)

    def setInterval(self, interval_ms):
        self.interval_ms = int(interval_ms)

    def start(self):
        self.started = True


class _FakeThread:
    instances = []

    def __init__(self, target=None, name="", daemon=False):
        self.target = target
        self.name = name
        self.daemon = daemon
        self.started = False
        self.__class__.instances.append(self)

    def start(self):
        self.started = True


def test_format_thread_dump_includes_reason_and_current_thread():
    frames = {threading.current_thread().ident: sys._getframe()}

    dump = App.format_thread_dump("unit-test stall", current_frames=frames)

    assert "UI freeze watchdog: unit-test stall" in dump
    assert "Process id:" in dump
    assert threading.current_thread().name in dump
    assert "test_format_thread_dump_includes_reason_and_current_thread" in dump


def test_append_freeze_diagnostics_writes_file(tmp_path):
    path = App.append_freeze_diagnostics("diagnostic line", log_path=tmp_path / "freeze.log")

    assert path == tmp_path / "freeze.log"
    assert path.read_text(encoding="utf-8") == "diagnostic line\n"


def test_install_ui_freeze_watchdog_starts_timer_and_daemon(monkeypatch):
    _FakeTimer.instances = []
    _FakeThread.instances = []
    monkeypatch.setattr(App, "QTimer", _FakeTimer)
    monkeypatch.setattr(App.threading, "Thread", _FakeThread)

    app = SimpleNamespace()
    timer, thread = App.install_ui_freeze_watchdog(
        app,
        interval_ms=250,
        stall_seconds=2.0,
        repeat_seconds=10.0,
        log_path="unused.log",
    )

    assert timer is _FakeTimer.instances[0]
    assert timer.parent is app
    assert timer.interval_ms == 250
    assert timer.started is True
    assert thread is _FakeThread.instances[0]
    assert thread.name == "LabCraftUIFreezeWatchdog"
    assert thread.daemon is True
    assert thread.started is True
    assert app._labcraft_ui_freeze_timer is timer
    assert app._labcraft_ui_freeze_watchdog is thread
