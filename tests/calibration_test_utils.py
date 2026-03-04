import importlib.util
import sys
import types

import numpy as np
import cv2


def ensure_calibration_import_stubs(*, force: bool = False) -> None:
    """
    Provide minimal optional-module stubs so CalibrationClasses.Model can import
    in lean test environments.
    """
    if (force or importlib.util.find_spec("pyDOE3") is None) and "pyDOE3" not in sys.modules:
        sys.modules["pyDOE3"] = types.ModuleType("pyDOE3")

    if force:
        sys.modules.pop("matplotlib", None)
        sys.modules.pop("matplotlib.pyplot", None)
        sys.modules.pop("matplotlib.figure", None)
        sys.modules.pop("matplotlib.backends", None)
        sys.modules.pop("matplotlib.backends.backend_qt5agg", None)

    if (force or importlib.util.find_spec("matplotlib") is None) and "matplotlib" not in sys.modules:
        mpl = types.ModuleType("matplotlib")
        plt = types.ModuleType("matplotlib.pyplot")
        figure_mod = types.ModuleType("matplotlib.figure")
        backends = types.ModuleType("matplotlib.backends")
        backend_qt5agg = types.ModuleType("matplotlib.backends.backend_qt5agg")

        class _FigureCanvasQTAgg:
            pass

        class _Figure:
            pass

        backend_qt5agg.FigureCanvasQTAgg = _FigureCanvasQTAgg
        figure_mod.Figure = _Figure
        mpl.pyplot = plt
        mpl.figure = figure_mod
        mpl.backends = backends
        sys.modules["matplotlib"] = mpl
        sys.modules["matplotlib.pyplot"] = plt
        sys.modules["matplotlib.figure"] = figure_mod
        sys.modules["matplotlib.backends"] = backends
        sys.modules["matplotlib.backends.backend_qt5agg"] = backend_qt5agg
    elif (force or importlib.util.find_spec("matplotlib.pyplot") is None) and "matplotlib.pyplot" not in sys.modules:
        plt = types.ModuleType("matplotlib.pyplot")
        sys.modules["matplotlib.pyplot"] = plt
        if "matplotlib" in sys.modules:
            sys.modules["matplotlib"].pyplot = plt
    if (force or importlib.util.find_spec("matplotlib.backends") is None) and "matplotlib.backends" not in sys.modules:
        sys.modules["matplotlib.backends"] = types.ModuleType("matplotlib.backends")
    if (force or importlib.util.find_spec("matplotlib.figure") is None) and "matplotlib.figure" not in sys.modules:
        figure_mod = types.ModuleType("matplotlib.figure")

        class _Figure:
            pass

        figure_mod.Figure = _Figure
        sys.modules["matplotlib.figure"] = figure_mod
    if (
        force or importlib.util.find_spec("matplotlib.backends.backend_qt5agg") is None
    ) and "matplotlib.backends.backend_qt5agg" not in sys.modules:
        backend_qt5agg = types.ModuleType("matplotlib.backends.backend_qt5agg")

        class _FigureCanvasQTAgg:
            pass

        backend_qt5agg.FigureCanvasQTAgg = _FigureCanvasQTAgg
        sys.modules["matplotlib.backends.backend_qt5agg"] = backend_qt5agg

    if force:
        sys.modules.pop("scipy", None)
        sys.modules.pop("scipy.optimize", None)
        sys.modules.pop("scipy.signal", None)

    if (force or importlib.util.find_spec("scipy") is None) and "scipy" not in sys.modules:
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
        if (force or importlib.util.find_spec("scipy.optimize") is None) and "scipy.optimize" not in sys.modules:
            optimize = types.ModuleType("scipy.optimize")
            optimize.minimize = lambda *a, **k: None
            optimize.fsolve = lambda *a, **k: None
            sys.modules["scipy.optimize"] = optimize
        if (force or importlib.util.find_spec("scipy.signal") is None) and "scipy.signal" not in sys.modules:
            signal = types.ModuleType("scipy.signal")
            signal.find_peaks = lambda *a, **k: ([], {})
            sys.modules["scipy.signal"] = signal

    if force:
        sys.modules.pop("skimage", None)
        sys.modules.pop("skimage.metrics", None)

    if (force or importlib.util.find_spec("skimage") is None) and "skimage" not in sys.modules:
        skimage = types.ModuleType("skimage")
        metrics = types.ModuleType("skimage.metrics")
        metrics.structural_similarity = lambda *a, **k: 1.0
        skimage.metrics = metrics
        sys.modules["skimage"] = skimage
        sys.modules["skimage.metrics"] = metrics
    elif (force or importlib.util.find_spec("skimage.metrics") is None) and "skimage.metrics" not in sys.modules:
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
