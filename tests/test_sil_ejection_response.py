from __future__ import annotations

import pytest

from tools.sil.ejection_response import (
    DROPLET_PULSE_WIDTH_RANGE_US,
    STREAM_PULSE_WIDTH_RANGE_US,
    PulseAwareSyntheticEjectionModelV1,
    SyntheticEjectionResponseError,
)


def test_response_endpoints_are_exact():
    model = PulseAwareSyntheticEjectionModelV1()

    assert model.predict_volume_nl("droplet", 1300) == 9.0
    assert model.predict_volume_nl("droplet", 1800) == 18.0
    assert model.predict_volume_nl("stream", 2500) == 60.0
    assert model.predict_volume_nl("stream", 10000) == 250.0


def test_response_is_linear_and_monotonic_inside_each_segment():
    model = PulseAwareSyntheticEjectionModelV1()

    assert model.predict_volume_nl("droplet", 1550) == 13.5
    assert model.predict_volume_nl("stream", 6250) == 155.0
    assert model.predict_volume_nl("droplet", 1301) > 9.0
    assert model.predict_volume_nl("stream", 2501) > 60.0


@pytest.mark.parametrize(
    ("mode", "pulse"),
    (
        ("droplet", 1299),
        ("droplet", 1801),
        ("stream", 2499),
        ("stream", 10001),
        ("droplet", 2000),
        ("stream", 2000),
        ("invalid", 1300),
        ("droplet", 1300.5),
        ("droplet", float("nan")),
        ("droplet", float("inf")),
    ),
)
def test_response_rejects_unsupported_or_non_integral_inputs(mode, pulse):
    with pytest.raises(SyntheticEjectionResponseError):
        PulseAwareSyntheticEjectionModelV1().predict_volume_nl(mode, pulse)


def test_response_ranges_are_explicit_and_support_is_fail_closed():
    model = PulseAwareSyntheticEjectionModelV1()

    assert DROPLET_PULSE_WIDTH_RANGE_US == (1300, 1800)
    assert STREAM_PULSE_WIDTH_RANGE_US == (2500, 10000)
    assert model.supports("droplet", 1800)
    assert model.supports("stream", 2500)
    assert not model.supports("droplet", 2500)
    assert not model.supports("stream", True)
