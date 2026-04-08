import importlib
import sys
import types

import pytest

from tests.calibration_test_utils import (
    _CALIBRATION_STUB_SENTINEL,
    ensure_calibration_import_stubs,
)


def _helper_stub(name: str, *, package: bool = False):
    module = types.ModuleType(name)
    setattr(module, _CALIBRATION_STUB_SENTINEL, True)
    if package:
        module.__path__ = []
    return module


def test_force_prefers_real_matplotlib_and_scipy_over_helper_stubs(monkeypatch):
    pytest.importorskip("matplotlib")
    pytest.importorskip("scipy.stats")

    monkeypatch.setitem(sys.modules, "matplotlib", _helper_stub("matplotlib", package=True))
    monkeypatch.setitem(
        sys.modules,
        "matplotlib.backends",
        _helper_stub("matplotlib.backends", package=True),
    )
    monkeypatch.setitem(sys.modules, "scipy", _helper_stub("scipy", package=True))

    fake_stats = _helper_stub("scipy.stats")
    fake_stats.theilslopes = lambda *_args, **_kwargs: (0.0, 0.0, 0.0, 0.0)
    monkeypatch.setitem(sys.modules, "scipy.stats", fake_stats)

    ensure_calibration_import_stubs(force=True)

    backends_mod = importlib.import_module("matplotlib.backends")
    backend_agg = importlib.import_module("matplotlib.backends.backend_agg")
    stats_mod = importlib.import_module("scipy.stats")

    assert backend_agg.__name__ == "matplotlib.backends.backend_agg"
    assert not getattr(sys.modules["matplotlib"], _CALIBRATION_STUB_SENTINEL, False)
    assert not getattr(backends_mod, _CALIBRATION_STUB_SENTINEL, False)
    assert not getattr(stats_mod, _CALIBRATION_STUB_SENTINEL, False)

    slope, intercept, lower_slope, upper_slope = stats_mod.theilslopes(
        [1.0, 2.0, 3.0],
        [1.0, 2.0, 3.0],
    )
    assert slope == pytest.approx(1.0)
    assert intercept == pytest.approx(0.0)
    assert lower_slope == pytest.approx(1.0)
    assert upper_slope == pytest.approx(1.0)
