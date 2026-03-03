import importlib.util
import sys
import types

import numpy as np
import cv2


def ensure_calibration_import_stubs() -> None:
    """
    Provide minimal optional-module stubs so CalibrationClasses.Model can import
    in lean test environments.
    """
    if importlib.util.find_spec("pyDOE3") is None and "pyDOE3" not in sys.modules:
        sys.modules["pyDOE3"] = types.ModuleType("pyDOE3")

    if importlib.util.find_spec("matplotlib") is None and "matplotlib" not in sys.modules:
        mpl = types.ModuleType("matplotlib")
        plt = types.ModuleType("matplotlib.pyplot")
        mpl.pyplot = plt
        sys.modules["matplotlib"] = mpl
        sys.modules["matplotlib.pyplot"] = plt
    elif importlib.util.find_spec("matplotlib.pyplot") is None and "matplotlib.pyplot" not in sys.modules:
        plt = types.ModuleType("matplotlib.pyplot")
        sys.modules["matplotlib.pyplot"] = plt
        if "matplotlib" in sys.modules:
            sys.modules["matplotlib"].pyplot = plt

    if importlib.util.find_spec("scipy") is None and "scipy" not in sys.modules:
        scipy = types.ModuleType("scipy")
        optimize = types.ModuleType("scipy.optimize")
        signal = types.ModuleType("scipy.signal")
        optimize.minimize = lambda *a, **k: None
        optimize.fsolve = lambda *a, **k: None
        signal.find_peaks = lambda *a, **k: ([], {})
        scipy.optimize = optimize
        scipy.signal = signal
        sys.modules["scipy"] = scipy
        sys.modules["scipy.optimize"] = optimize
        sys.modules["scipy.signal"] = signal
    else:
        if importlib.util.find_spec("scipy.optimize") is None and "scipy.optimize" not in sys.modules:
            optimize = types.ModuleType("scipy.optimize")
            optimize.minimize = lambda *a, **k: None
            optimize.fsolve = lambda *a, **k: None
            sys.modules["scipy.optimize"] = optimize
        if importlib.util.find_spec("scipy.signal") is None and "scipy.signal" not in sys.modules:
            signal = types.ModuleType("scipy.signal")
            signal.find_peaks = lambda *a, **k: ([], {})
            sys.modules["scipy.signal"] = signal

    if importlib.util.find_spec("skimage") is None and "skimage" not in sys.modules:
        skimage = types.ModuleType("skimage")
        metrics = types.ModuleType("skimage.metrics")
        metrics.structural_similarity = lambda *a, **k: 1.0
        skimage.metrics = metrics
        sys.modules["skimage"] = skimage
        sys.modules["skimage.metrics"] = metrics
    elif importlib.util.find_spec("skimage.metrics") is None and "skimage.metrics" not in sys.modules:
        metrics = types.ModuleType("skimage.metrics")
        metrics.structural_similarity = lambda *a, **k: 1.0
        sys.modules["skimage.metrics"] = metrics
        if "skimage" in sys.modules:
            sys.modules["skimage"].metrics = metrics


class Recorder:
    def __init__(self):
        self.calls = []

    def emit(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class SignalStub:
    def __init__(self):
        self._subs = []
        self.calls = []

    def connect(self, fn):
        self._subs.append(fn)

    def emit(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        for fn in list(self._subs):
            fn(*args, **kwargs)


def contour_from_rect(x: int, y: int, w: int, h: int):
    img = np.zeros((max(y + h + 5, 64), max(x + w + 5, 64)), dtype=np.uint8)
    cv2.rectangle(img, (x, y), (x + w, y + h), 255, -1)
    contours, _ = cv2.findContours(img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return contours[0]
