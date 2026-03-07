import importlib.util
import sys
import types

import numpy as np
import cv2


def _find_spec_or_none(name: str):
    try:
        return importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return None


def ensure_calibration_import_stubs(*, force: bool = False) -> None:
    """
    Provide minimal optional-module stubs so CalibrationClasses.Model can import
    in lean test environments.
    """
    if (force or _find_spec_or_none("pyDOE3") is None) and "pyDOE3" not in sys.modules:
        sys.modules["pyDOE3"] = types.ModuleType("pyDOE3")

    if force:
        sys.modules.pop("matplotlib", None)
        sys.modules.pop("matplotlib.pyplot", None)
        sys.modules.pop("matplotlib.figure", None)
        sys.modules.pop("matplotlib.backends", None)
        sys.modules.pop("matplotlib.backends.backend_qt5agg", None)

    if (force or _find_spec_or_none("matplotlib") is None) and "matplotlib" not in sys.modules:
        mpl = types.ModuleType("matplotlib")
        plt = types.ModuleType("matplotlib.pyplot")
        figure_mod = types.ModuleType("matplotlib.figure")
        backends = types.ModuleType("matplotlib.backends")
        backend_qt5agg = types.ModuleType("matplotlib.backends.backend_qt5agg")

        class _FigureCanvasQTAgg:
            pass

        class _Axes:
            def plot(self, *args, **kwargs):
                return []

            def step(self, *args, **kwargs):
                return []

            def bar(self, *args, **kwargs):
                return []

            def scatter(self, *args, **kwargs):
                return []

            def imshow(self, *args, **kwargs):
                return object()

            def axvline(self, *args, **kwargs):
                return None

            def axhline(self, *args, **kwargs):
                return None

            def set_ylabel(self, *args, **kwargs):
                return None

            def set_xlabel(self, *args, **kwargs):
                return None

            def set_title(self, *args, **kwargs):
                return None

            def set_ylim(self, *args, **kwargs):
                return None

            def set_yticks(self, *args, **kwargs):
                return None

            def set_yticklabels(self, *args, **kwargs):
                return None

            def set_xticks(self, *args, **kwargs):
                return None

            def set_xticklabels(self, *args, **kwargs):
                return None

            def grid(self, *args, **kwargs):
                return None

            def legend(self, *args, **kwargs):
                return None

        class _Figure:
            def suptitle(self, *args, **kwargs):
                return None

            def tight_layout(self, *args, **kwargs):
                return None

            def colorbar(self, *args, **kwargs):
                return None

            def savefig(self, path, *args, **kwargs):
                with open(path, "wb") as handle:
                    handle.write(b"stub-figure")

        backend_qt5agg.FigureCanvasQTAgg = _FigureCanvasQTAgg
        figure_mod.Figure = _Figure
        mpl.use = lambda *a, **k: None
        plt.close = lambda *a, **k: None

        def _subplots(nrows=1, ncols=1, **kwargs):
            fig = _Figure()
            if nrows == 1 and ncols == 1:
                return fig, _Axes()
            axes = [_Axes() for _ in range(nrows * ncols)]
            if nrows == 1 or ncols == 1:
                return fig, axes
            grid = []
            idx = 0
            for _ in range(nrows):
                row = []
                for _ in range(ncols):
                    row.append(axes[idx])
                    idx += 1
                grid.append(row)
            return fig, grid

        plt.subplots = _subplots
        mpl.pyplot = plt
        mpl.figure = figure_mod
        mpl.backends = backends
        sys.modules["matplotlib"] = mpl
        sys.modules["matplotlib.pyplot"] = plt
        sys.modules["matplotlib.figure"] = figure_mod
        sys.modules["matplotlib.backends"] = backends
        sys.modules["matplotlib.backends.backend_qt5agg"] = backend_qt5agg
    elif (force or _find_spec_or_none("matplotlib.pyplot") is None) and "matplotlib.pyplot" not in sys.modules:
        plt = types.ModuleType("matplotlib.pyplot")
        sys.modules["matplotlib.pyplot"] = plt
        if "matplotlib" in sys.modules:
            sys.modules["matplotlib"].pyplot = plt
            if not hasattr(sys.modules["matplotlib"], "use"):
                sys.modules["matplotlib"].use = lambda *a, **k: None
    if "matplotlib.pyplot" in sys.modules:
        plt = sys.modules["matplotlib.pyplot"]
        if not hasattr(plt, "close"):
            plt.close = lambda *a, **k: None
        if not hasattr(plt, "subplots"):
            class _Axes:
                def plot(self, *args, **kwargs):
                    return []

                def step(self, *args, **kwargs):
                    return []

                def bar(self, *args, **kwargs):
                    return []

                def scatter(self, *args, **kwargs):
                    return []

                def imshow(self, *args, **kwargs):
                    return object()

                def axvline(self, *args, **kwargs):
                    return None

                def axhline(self, *args, **kwargs):
                    return None

                def set_ylabel(self, *args, **kwargs):
                    return None

                def set_xlabel(self, *args, **kwargs):
                    return None

                def set_title(self, *args, **kwargs):
                    return None

                def set_ylim(self, *args, **kwargs):
                    return None

                def set_yticks(self, *args, **kwargs):
                    return None

                def set_yticklabels(self, *args, **kwargs):
                    return None

                def set_xticks(self, *args, **kwargs):
                    return None

                def set_xticklabels(self, *args, **kwargs):
                    return None

                def grid(self, *args, **kwargs):
                    return None

                def legend(self, *args, **kwargs):
                    return None

            class _Figure:
                def suptitle(self, *args, **kwargs):
                    return None

                def tight_layout(self, *args, **kwargs):
                    return None

                def colorbar(self, *args, **kwargs):
                    return None

                def savefig(self, path, *args, **kwargs):
                    with open(path, "wb") as handle:
                        handle.write(b"stub-figure")

            def _subplots(nrows=1, ncols=1, **kwargs):
                fig = _Figure()
                if nrows == 1 and ncols == 1:
                    return fig, _Axes()
                axes = [_Axes() for _ in range(nrows * ncols)]
                if nrows == 1 or ncols == 1:
                    return fig, axes
                grid = []
                idx = 0
                for _ in range(nrows):
                    row = []
                    for _ in range(ncols):
                        row.append(axes[idx])
                        idx += 1
                    grid.append(row)
                return fig, grid

            plt.subplots = _subplots
    if (force or _find_spec_or_none("matplotlib.backends") is None) and "matplotlib.backends" not in sys.modules:
        sys.modules["matplotlib.backends"] = types.ModuleType("matplotlib.backends")
    if (force or _find_spec_or_none("matplotlib.figure") is None) and "matplotlib.figure" not in sys.modules:
        figure_mod = types.ModuleType("matplotlib.figure")

        class _Figure:
            pass

        figure_mod.Figure = _Figure
        sys.modules["matplotlib.figure"] = figure_mod
    if (
        force or _find_spec_or_none("matplotlib.backends.backend_qt5agg") is None
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

    if (force or _find_spec_or_none("scipy") is None) and "scipy" not in sys.modules:
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
        if (force or _find_spec_or_none("scipy.optimize") is None) and "scipy.optimize" not in sys.modules:
            optimize = types.ModuleType("scipy.optimize")
            optimize.minimize = lambda *a, **k: None
            optimize.fsolve = lambda *a, **k: None
            sys.modules["scipy.optimize"] = optimize
        if (force or _find_spec_or_none("scipy.signal") is None) and "scipy.signal" not in sys.modules:
            signal = types.ModuleType("scipy.signal")
            signal.find_peaks = lambda *a, **k: ([], {})
            sys.modules["scipy.signal"] = signal

    if force:
        sys.modules.pop("skimage", None)
        sys.modules.pop("skimage.metrics", None)

    if (force or _find_spec_or_none("skimage") is None) and "skimage" not in sys.modules:
        skimage = types.ModuleType("skimage")
        metrics = types.ModuleType("skimage.metrics")
        metrics.structural_similarity = lambda *a, **k: 1.0
        skimage.metrics = metrics
        sys.modules["skimage"] = skimage
        sys.modules["skimage.metrics"] = metrics
    elif (force or _find_spec_or_none("skimage.metrics") is None) and "skimage.metrics" not in sys.modules:
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
