class FakeSignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def disconnect(self, callback):
        self._callbacks = [cb for cb in self._callbacks if cb is not callback]

    def emit(self, *args, **kwargs):
        for cb in list(self._callbacks):
            cb(*args, **kwargs)
