import importlib.util
import sys
import types

import numpy as np
import cv2

_CALIBRATION_STUB_SENTINEL = "__calibration_stub__"


def _find_spec_or_none(name: str):
    try:
        return importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return None


def _stub_module(name: str, *, package: bool = False):
    module = types.ModuleType(name)
    setattr(module, _CALIBRATION_STUB_SENTINEL, True)
    if package:
        module.__path__ = []
    return module


def _register_stub_module(name: str, module):
    setattr(module, _CALIBRATION_STUB_SENTINEL, True)
    sys.modules[name] = module
    return module


def _is_helper_stub(name: str) -> bool:
    module = sys.modules.get(name)
    return bool(getattr(module, _CALIBRATION_STUB_SENTINEL, False))


def _clear_helper_stubs(*module_names: str) -> None:
    for module_name in module_names:
        if _is_helper_stub(module_name):
            sys.modules.pop(module_name, None)


def ensure_calibration_import_stubs(*, force: bool = False) -> None:
    """
    Provide minimal optional-module stubs so CalibrationClasses.Model can import
    in lean test environments.
    """
    if force:
        _clear_helper_stubs(
            "pyDOE3",
            "matplotlib",
            "matplotlib.pyplot",
            "matplotlib.figure",
            "matplotlib.backends",
            "matplotlib.backends.backend_qt5agg",
            "scipy",
            "scipy.optimize",
            "scipy.signal",
            "scipy.stats",
            "scipy.ndimage",
            "skimage",
            "skimage.metrics",
        )

    if _find_spec_or_none("pyDOE3") is None and "pyDOE3" not in sys.modules:
        _register_stub_module("pyDOE3", _stub_module("pyDOE3"))

    if _find_spec_or_none("matplotlib") is None and "matplotlib" not in sys.modules:
        mpl = _stub_module("matplotlib", package=True)
        plt = _stub_module("matplotlib.pyplot")
        figure_mod = _stub_module("matplotlib.figure")
        backends = _stub_module("matplotlib.backends", package=True)
        backend_qt5agg = _stub_module("matplotlib.backends.backend_qt5agg")

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
        _register_stub_module("matplotlib", mpl)
        _register_stub_module("matplotlib.pyplot", plt)
        _register_stub_module("matplotlib.figure", figure_mod)
        _register_stub_module("matplotlib.backends", backends)
        _register_stub_module("matplotlib.backends.backend_qt5agg", backend_qt5agg)
    elif _find_spec_or_none("matplotlib.pyplot") is None and "matplotlib.pyplot" not in sys.modules:
        plt = _stub_module("matplotlib.pyplot")
        _register_stub_module("matplotlib.pyplot", plt)
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
    if _find_spec_or_none("matplotlib.backends") is None and "matplotlib.backends" not in sys.modules:
        _register_stub_module(
            "matplotlib.backends",
            _stub_module("matplotlib.backends", package=True),
        )
    if _find_spec_or_none("matplotlib.figure") is None and "matplotlib.figure" not in sys.modules:
        figure_mod = _stub_module("matplotlib.figure")

        class _Figure:
            pass

        figure_mod.Figure = _Figure
        _register_stub_module("matplotlib.figure", figure_mod)
    if _find_spec_or_none("matplotlib.backends.backend_qt5agg") is None and "matplotlib.backends.backend_qt5agg" not in sys.modules:
        backend_qt5agg = _stub_module("matplotlib.backends.backend_qt5agg")

        class _FigureCanvasQTAgg:
            pass

        backend_qt5agg.FigureCanvasQTAgg = _FigureCanvasQTAgg
        _register_stub_module("matplotlib.backends.backend_qt5agg", backend_qt5agg)

    if _find_spec_or_none("scipy") is None and "scipy" not in sys.modules:
        scipy = _stub_module("scipy", package=True)
        optimize = _stub_module("scipy.optimize")
        signal = _stub_module("scipy.signal")
        stats = _stub_module("scipy.stats")
        ndimage = _stub_module("scipy.ndimage")
        optimize.minimize = lambda *a, **k: None
        optimize.fsolve = lambda *a, **k: None
        signal.find_peaks = lambda *a, **k: ([], {})
        stats.theilslopes = lambda y, x, *a, **k: (0.0, 0.0, 0.0, 0.0)
        ndimage.binary_fill_holes = lambda arr, *a, **k: arr
        ndimage.label = lambda arr, *a, **k: (arr, 1)
        scipy.optimize = optimize
        scipy.signal = signal
        scipy.stats = stats
        scipy.ndimage = ndimage
        _register_stub_module("scipy", scipy)
        _register_stub_module("scipy.optimize", optimize)
        _register_stub_module("scipy.signal", signal)
        _register_stub_module("scipy.stats", stats)
        _register_stub_module("scipy.ndimage", ndimage)
    else:
        if _find_spec_or_none("scipy.optimize") is None and "scipy.optimize" not in sys.modules:
            optimize = _stub_module("scipy.optimize")
            optimize.minimize = lambda *a, **k: None
            optimize.fsolve = lambda *a, **k: None
            _register_stub_module("scipy.optimize", optimize)
        if _find_spec_or_none("scipy.signal") is None and "scipy.signal" not in sys.modules:
            signal = _stub_module("scipy.signal")
            signal.find_peaks = lambda *a, **k: ([], {})
            _register_stub_module("scipy.signal", signal)
        if _find_spec_or_none("scipy.stats") is None and "scipy.stats" not in sys.modules:
            stats = _stub_module("scipy.stats")
            stats.theilslopes = lambda y, x, *a, **k: (0.0, 0.0, 0.0, 0.0)
            _register_stub_module("scipy.stats", stats)
        if _find_spec_or_none("scipy.ndimage") is None and "scipy.ndimage" not in sys.modules:
            ndimage = _stub_module("scipy.ndimage")
            ndimage.binary_fill_holes = lambda arr, *a, **k: arr
            ndimage.label = lambda arr, *a, **k: (arr, 1)
            _register_stub_module("scipy.ndimage", ndimage)
        if "scipy" in sys.modules:
            if "scipy.optimize" in sys.modules:
                sys.modules["scipy"].optimize = sys.modules["scipy.optimize"]
            if "scipy.signal" in sys.modules:
                sys.modules["scipy"].signal = sys.modules["scipy.signal"]
            if "scipy.stats" in sys.modules:
                sys.modules["scipy"].stats = sys.modules["scipy.stats"]
            if "scipy.ndimage" in sys.modules:
                sys.modules["scipy"].ndimage = sys.modules["scipy.ndimage"]

    if _find_spec_or_none("skimage") is None and "skimage" not in sys.modules:
        skimage = _stub_module("skimage", package=True)
        metrics = _stub_module("skimage.metrics")
        metrics.structural_similarity = lambda *a, **k: 1.0
        skimage.metrics = metrics
        _register_stub_module("skimage", skimage)
        _register_stub_module("skimage.metrics", metrics)
    elif _find_spec_or_none("skimage.metrics") is None and "skimage.metrics" not in sys.modules:
        metrics = _stub_module("skimage.metrics")
        metrics.structural_similarity = lambda *a, **k: 1.0
        _register_stub_module("skimage.metrics", metrics)
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
