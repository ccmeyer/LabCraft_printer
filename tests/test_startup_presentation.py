import threading
from pathlib import Path

import pytest
from PySide6 import QtCore, QtGui, QtTest

from StartupPresentation import StartupSplash, run_startup_operation


@pytest.mark.parametrize(
    "message",
    [
        "Checking machine data...",
        "Loading interface...",
        "Cancellation requested. Waiting for a safe checkpoint...",
    ],
)
def test_live_status_renders_white_beneath_wordmark_without_a_background(qapp, message):
    logo = QtGui.QPixmap("FreeRTOS-interface/Presets/LabCraft_logo.png")
    splash = StartupSplash(logo)
    splash.set_status(message)
    image = QtGui.QImage(logo.size(), QtGui.QImage.Format_RGBA8888)
    image.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(image)
    splash.drawContents(painter)
    painter.end()
    pixels = bytes(image.constBits())
    drawn = [i for i, alpha in enumerate(pixels[3::4]) if alpha]
    assert drawn
    xs = [i % image.width() for i in drawn]
    ys = [i // image.width() for i in drawn]
    assert min(xs) >= image.width() * 0.08
    assert max(xs) <= image.width() * 0.92
    assert min(ys) >= image.height() * 0.69
    assert max(ys) <= image.height() * 0.745
    assert all(pixels[i * 4:i * 4 + 3] == b"\xff\xff\xff" for i in drawn)
    # An opaque rectangle would fill this entire region, including its corners.
    assert image.pixelColor(40, 416).alpha() == 0
    splash.close_startup()


def test_logo_source_and_export_have_no_static_initializing_label(qapp):
    source = Path("FreeRTOS-interface/Presets/LabCraft_logo.svg")
    assert "Initializing" not in source.read_text(encoding="utf-8")
    image = QtGui.QImage(str(source.with_suffix(".png")))
    assert image.size() == QtCore.QSize(453, 602)
    assert image.pixelColor(0, 0).alpha() == 0
    for y in range(420, 450):
        for x in range(100, 350):
            color = image.pixelColor(x, y)
            assert max(color.red(), color.green(), color.blue()) < 30


def _splash():
    pixmap = QtGui.QPixmap(240, 120)
    pixmap.fill(QtGui.QColor("black"))
    splash = StartupSplash(pixmap)
    splash.set_status("Checking machine data...")
    splash.show()
    return splash


def test_first_frame_paints_before_worker_and_events_continue_during_work(qapp):
    splash = _splash()
    release = threading.Event()
    started = threading.Event()
    worker_threads = []
    gui_ticks = []
    timer = QtCore.QTimer()

    def service_gui():
        if started.is_set():
            gui_ticks.append("tick")
            release.set()

    timer.timeout.connect(service_gui)
    timer.start(1)

    def operation():
        assert splash.has_painted
        worker_threads.append(QtCore.QThread.currentThread())
        started.set()
        assert release.wait(3), "Qt must continue servicing events during validation"
        return "authorized"

    try:
        assert run_startup_operation(operation, splash=splash) == "authorized"
        assert gui_ticks
        assert worker_threads[0] is not qapp.thread()
        assert worker_threads[0].isFinished()
        assert splash.isVisible()
    finally:
        timer.stop()
        splash.close_startup()


def test_worker_error_preserves_typed_failure_and_waits_for_thread_stop(qapp):
    splash = _splash()
    error = RuntimeError("Configuration lock unavailable")
    error.code = "configuration_lock_unavailable"
    worker_threads = []

    def fail():
        worker_threads.append(QtCore.QThread.currentThread())
        raise error

    try:
        with pytest.raises(RuntimeError) as caught:
            run_startup_operation(fail, splash=splash)
        assert caught.value is error
        assert caught.value.code == "configuration_lock_unavailable"
        assert worker_threads[0].isFinished()
    finally:
        splash.close_startup()


def test_quit_request_cancels_without_unwinding_a_live_worker(qapp):
    splash = _splash()
    cancelled = threading.Event()
    worker_threads = []
    splash.cancel_requested.connect(cancelled.set)

    def operation():
        worker_threads.append(QtCore.QThread.currentThread())
        QtCore.QCoreApplication.postEvent(qapp, QtCore.QEvent(QtCore.QEvent.Quit))
        assert cancelled.wait(3), "Quit must request cancellation on the GUI thread"
        return "safe checkpoint reached"

    try:
        result = run_startup_operation(operation, splash=splash)
        assert result == "safe checkpoint reached"
        assert worker_threads[0].isFinished()
    finally:
        splash.close_startup()


def test_real_ready_store_retains_its_lock_until_the_returned_context_closes(
    qapp, tmp_path
):
    from MachineDataBootstrap import (
        BootstrapError, BootstrapState, MachineDataBootstrap,
        PublishedActivationSubmission,
    )
    from tests.machine_data_migration_helpers import (
        FIXED_TIME, MACHINE_UUID, migration_policy, publish_candidate,
    )

    base, paths, _identity, candidate, _migration = publish_candidate(tmp_path)
    bootstrap = MachineDataBootstrap(
        base, app_version="v1.3.0-rc.2", app_commit="test-commit",
        migration_policy=migration_policy(), clock=lambda: FIXED_TIME,
    )
    activated = bootstrap.activate_published(
        PublishedActivationSubmission(
            machine_uuid=MACHINE_UUID, operator="Test Operator",
            source_reason="synthetic startup test",
            camera_confirmation=candidate.safety_snapshot["locations"]["camera"],
        )
    )
    activated.close()
    settings_before = (paths.config_root / "Settings.json").read_bytes()
    receipts_before = (
        paths.verification_path.read_bytes(), paths.activation_receipt_path.read_bytes(),
        base.active_machine_path.read_bytes(),
    )
    splash = _splash()

    def open_verified_store():
        assert bootstrap.inspect().state is BootstrapState.READY
        return bootstrap.open_ready()

    context = None
    try:
        context = run_startup_operation(open_verified_store, splash=splash)
        assert not context.configuration_lock.released
        context.configuration_lock.assert_owns(paths)
        with pytest.raises(BootstrapError) as rejected:
            bootstrap.open_ready()
        assert rejected.value.code == "configuration_lock_unavailable"
        assert (paths.config_root / "Settings.json").read_bytes() == settings_before
        assert receipts_before == (
            paths.verification_path.read_bytes(), paths.activation_receipt_path.read_bytes(),
            base.active_machine_path.read_bytes(),
        )
    finally:
        if context is not None:
            context.close()
        splash.close_startup()
    assert context.configuration_lock.released
    reopened = bootstrap.open_ready()
    reopened.close()


def test_splash_click_does_not_hide_and_close_requests_safe_cancellation(qapp):
    splash = _splash()
    cancelled = []
    splash.cancel_requested.connect(lambda: cancelled.append(True))
    try:
        qapp.processEvents()
        QtTest.QTest.mouseClick(splash, QtCore.Qt.LeftButton)
        assert splash.isVisible()
        splash.close()
        assert cancelled == [True]
        assert splash.isVisible()
    finally:
        splash.close_startup()
    assert not splash.isVisible()
    assert cancelled == [True]


def test_missing_logo_still_provides_a_paintable_loading_screen(qapp):
    splash = StartupSplash(QtGui.QPixmap())
    splash.set_status("Checking machine data...")
    splash.show()
    try:
        assert run_startup_operation(lambda: "ready", splash=splash) == "ready"
        assert splash.has_painted
        assert not splash.pixmap().isNull()
    finally:
        splash.close_startup()
