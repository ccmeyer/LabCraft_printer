import pytest

from MotionPositionContract import (
    INT32_MAX,
    MotionPositionContractError,
    POSITION_LOGICAL_UNITS_PER_NATIVE_STEP,
    canonicalize_absolute_target,
    canonicalize_displacement,
    canonicalize_position,
    canonicalize_relative_position,
)


def test_host_contract_matches_firmware_motion_unit_scale_vectors():
    assert POSITION_LOGICAL_UNITS_PER_NATIVE_STEP == 2
    assert canonicalize_displacement(100, 5) == (4, 104)
    assert canonicalize_displacement(100, -5) == (-4, 96)
    assert canonicalize_absolute_target(10, 9) == 10
    assert canonicalize_absolute_target(0, 9) == 8
    assert canonicalize_absolute_target(10, 3) == 4


def test_even_zero_and_existing_parity_are_preserved():
    assert canonicalize_displacement(7, 0) == (0, 7)
    assert canonicalize_displacement(7, 6) == (6, 13)
    assert canonicalize_absolute_target(7, 12) == 11


def test_observed_plate_target_is_canonicalized_from_commanded_frontier():
    plan = canonicalize_position(
        {"X": 43840, "Y": 29870, "Z": 85550},
        {"X": 33050, "Y": 29875, "Z": 85850},
    )

    assert plan == {
        "position_quantum": 2,
        "origin_position": {"X": 43840, "Y": 29870, "Z": 85550},
        "requested_position": {"X": 33050, "Y": 29875, "Z": 85850},
        "canonical_position": {"X": 33050, "Y": 29874, "Z": 85850},
        "adjustments": {"X": 0, "Y": -1, "Z": 0},
        "adjusted_axes": ["Y"],
    }


def test_relative_position_retains_requested_and_canonical_displacements():
    plan = canonicalize_relative_position(
        {"X": 100, "Y": 200, "Z": 300},
        {"X": 5, "Y": -5, "Z": 3},
    )

    assert plan["requested_position"] == {"X": 105, "Y": 195, "Z": 303}
    assert plan["canonical_position"] == {"X": 104, "Y": 196, "Z": 302}
    assert plan["requested_displacement"] == {"X": 5, "Y": -5, "Z": 3}
    assert plan["canonical_displacement"] == {"X": 4, "Y": -4, "Z": 2}


@pytest.mark.parametrize(
    ("current", "requested", "message"),
    [
        (True, 0, "current position must be an integer"),
        (0, 1.5, "requested position must be an integer"),
        (0, INT32_MAX + 1, "requested position is outside signed 32-bit range"),
    ],
)
def test_invalid_absolute_values_fail_closed(current, requested, message):
    with pytest.raises(MotionPositionContractError, match=message):
        canonicalize_absolute_target(current, requested)


def test_invalid_quantum_and_relative_overflow_fail_closed():
    with pytest.raises(MotionPositionContractError, match="quantum must be positive"):
        canonicalize_displacement(0, 1, quantum=0)
    with pytest.raises(MotionPositionContractError, match="outside signed 32-bit"):
        canonicalize_displacement(INT32_MAX, 1)


def test_missing_axis_fails_closed():
    with pytest.raises(MotionPositionContractError, match="missing axis Z"):
        canonicalize_position(
            {"X": 0, "Y": 0},
            {"X": 0, "Y": 0, "Z": 0},
        )


def test_noninteger_relative_displacement_fails_closed_before_arithmetic():
    with pytest.raises(
        MotionPositionContractError,
        match="requested X displacement must be an integer",
    ):
        canonicalize_relative_position(
            {"X": 0, "Y": 0, "Z": 0},
            {"X": True, "Y": 0, "Z": 0},
        )
