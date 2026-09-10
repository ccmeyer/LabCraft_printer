from __future__ import annotations

import sys
import threading
import pytest
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
    previous = app._labcraft_ui_heartbeat["last"]
    timer.timeout.emit()
    assert app._labcraft_ui_heartbeat["last"] >= previous


def test_default_ui_stall_capture_precedes_mcu_timeout(qapp, test_profile, tmp_path):
    from test_host_black_box_log import _make_machine
    machine = _make_machine(qapp, test_profile, tmp_path)
    assert App.UI_FREEZE_WATCHDOG_STALL_SECONDS * 1000 < machine._mcu_response_timeout_ms


def test_stall_retains_bounded_utf8_evidence_for_fault_snapshot(monkeypatch):
    monkeypatch.setattr(App, "QTimer", _FakeTimer)
    monkeypatch.setattr(App.threading, "Thread", _FakeThread)
    times = iter([100.0, 102.0])
    monkeypatch.setattr(App.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(App.time, "sleep", lambda _: None)
    dump = "\u00e9" * 40000
    monkeypatch.setattr(App, "format_thread_dump", lambda _: dump)
    written = []
    monkeypatch.setattr(App, "append_freeze_diagnostics", lambda text, **_: written.append(text))
    app = SimpleNamespace()
    _timer, thread = App.install_ui_freeze_watchdog(app)
    with pytest.raises(StopIteration):
        thread.target()
    stall = app._labcraft_ui_heartbeat["last_stall"]
    assert len(stall["thread_dump"].encode("utf-8")) == 65536
    assert stall["truncated"]
    assert stall["monotonic_ns"] == 102_000_000_000
    assert written == [dump]
