"""Lightweight startup presentation; no machine-data, MVC, or hardware imports."""

from PySide6 import QtCore, QtGui, QtWidgets


class StartupSplash(QtWidgets.QSplashScreen):
    painted = QtCore.Signal()
    cancel_requested = QtCore.Signal()

    def __init__(self, pixmap):
        if pixmap.isNull():
            pixmap = QtGui.QPixmap(520, 200)
            pixmap.fill(QtGui.QColor(53, 53, 53))
        super().__init__(pixmap)
        self.has_painted = False
        self._startup_active = True

    def set_status(self, message):
        self.showMessage(
            message,
            QtCore.Qt.AlignCenter,
            QtGui.QColor("white"),
        )

    def drawContents(self, painter):
        # Match the former text beneath the wordmark in the 120 x 160 SVG.
        area = QtCore.QRect(
            round(self.width() * 0.08), round(self.height() * 0.69),
            round(self.width() * 0.84), round(self.height() * 0.055),
        )
        flags = QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap
        font = QtGui.QFont(self.font())
        font.setWeight(QtGui.QFont.DemiBold)
        size = max(8, round(self.height() * 5.64444 / 160))
        while True:
            font.setPixelSize(size)
            bounds = QtGui.QFontMetrics(font).boundingRect(area, flags, self.message())
            if size <= 8 or (bounds.width() <= area.width() and bounds.height() <= area.height()):
                break
            size -= 1
        painter.save()
        painter.setFont(font)
        painter.setPen(QtGui.QColor("white"))
        painter.drawText(area, flags, self.message())
        painter.restore()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.isVisible() and not self.has_painted:
            self.has_painted = True
            self.painted.emit()

    def mousePressEvent(self, event):
        # QSplashScreen normally hides on a click, leaving startup invisible.
        event.accept()

    def closeEvent(self, event):
        if self._startup_active:
            event.ignore()
            self.cancel_requested.emit()
            return
        super().closeEvent(event)

    def finish(self, widget):
        self._startup_active = False
        super().finish(widget)

    def close_startup(self):
        self._startup_active = False
        self.close()


class _StartupWorker(QtCore.QObject):
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(object)

    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    @QtCore.Slot()
    def run(self):
        try:
            self.finished.emit(self.operation())
        except Exception as exc:
            self.failed.emit(exc)


class _StartupWaiter(QtCore.QObject):
    """Deliver results on the GUI thread only after the worker has stopped."""

    def __init__(self, splash):
        super().__init__()
        self.splash = splash
        self.loop = QtCore.QEventLoop()
        self.outcome = None
        self.stopped = False

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.Quit:
            # Do not unwind the local loop while durable work is still active.
            self.splash.cancel_requested.emit()
            return True
        return super().eventFilter(watched, event)

    @QtCore.Slot(object)
    def succeeded(self, result):
        self.outcome = (True, result)
        self._finish_if_stopped()

    @QtCore.Slot(object)
    def failed(self, error):
        self.outcome = (False, error)
        self._finish_if_stopped()

    @QtCore.Slot()
    def thread_stopped(self):
        self.stopped = True
        self._finish_if_stopped()

    def _finish_if_stopped(self):
        if self.stopped and self.outcome is not None:
            self.loop.quit()


def run_startup_operation(operation, *, splash):
    """Paint first, then service Qt events until hardware-free work has stopped.

    Like the verification dialog, this uses a local event loop. The existing
    application lifecycle stays synchronous and owns cleanup on every exit.
    Never force-terminate a worker that may be at a durable write checkpoint.
    """
    if not splash.isVisible():
        raise RuntimeError("The loading screen must be shown before startup work.")
    waiter = _StartupWaiter(splash)
    thread = QtCore.QThread()
    worker = _StartupWorker(operation)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(waiter.succeeded)
    worker.failed.connect(waiter.failed)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    worker.failed.connect(worker.deleteLater)
    thread.finished.connect(waiter.thread_stopped)
    if splash.has_painted:
        QtCore.QTimer.singleShot(0, thread.start)
    else:
        splash.painted.connect(thread.start, QtCore.Qt.QueuedConnection)
    app = QtCore.QCoreApplication.instance()
    app.installEventFilter(waiter)
    try:
        waiter.loop.exec()
    finally:
        app.removeEventFilter(waiter)
        if not waiter.stopped and thread.isRunning():
            # An exceptional event-loop exit must not destroy a live QThread
            # or let App release the store lock while its worker still uses it.
            splash.cancel_requested.emit()
            thread.quit()
        thread.wait()
    if not splash.has_painted:
        raise RuntimeError("Startup ended before the loading screen painted.")
    if waiter.outcome is None:
        raise RuntimeError("Startup was interrupted before its result was delivered.")
    succeeded, result = waiter.outcome
    if not succeeded:
        raise result
    return result
