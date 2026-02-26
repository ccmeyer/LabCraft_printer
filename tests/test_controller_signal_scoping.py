from types import SimpleNamespace

from Controller import Controller


class FakeSignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def disconnect(self, callback=None):
        if callback is None:
            self._callbacks = []
            return
        self._callbacks = [cb for cb in self._callbacks if cb != callback]

    def emit(self, *args, **kwargs):
        for cb in list(self._callbacks):
            cb(*args, **kwargs)


def test_disconnect_droplet_camera_signals_only_removes_controller_handlers():
    c = Controller.__new__(Controller)

    capture = FakeSignal()
    move = FakeSignal()
    move_abs = FakeSignal()
    settings = FakeSignal()
    img = FakeSignal()
    fail = FakeSignal()

    c.model = SimpleNamespace(
        calibration_manager=SimpleNamespace(
            captureImageRequested=capture,
            moveRequested=move,
            moveAbsoluteRequested=move_abs,
            changeSettingsRequested=settings,
        )
    )
    c.machine = SimpleNamespace(
        droplet_camera=SimpleNamespace(
            image_captured_signal=img,
            capture_failed_signal=fail,
        )
    )

    external_calls = {"capture": 0, "img": 0}
    capture.connect(lambda: external_calls.__setitem__("capture", external_calls["capture"] + 1))
    img.connect(lambda *_: external_calls.__setitem__("img", external_calls["img"] + 1))

    Controller.connect_droplet_camera_signals(c)
    Controller.disconnect_droplet_camera_signals(c)

    capture.emit()
    img.emit("frame")

    assert external_calls["capture"] == 1
    assert external_calls["img"] == 1
