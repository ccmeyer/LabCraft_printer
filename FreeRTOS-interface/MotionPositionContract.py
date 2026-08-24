"""Host-side mirror of the firmware's Cartesian position quantization.

The current firmware exposes coordinates in historical logical units while
each complete native STEP cycle advances two of those units.  Commands must
therefore be canonicalized from the commanded position frontier before they
are validated, queued, or used as an expected endpoint.

Keep the vectors in this module aligned with
``firmware/Core/Inc/MotionUnitScale.h``.  Changing this contract requires a
coordinated application/firmware change; there is deliberately no runtime
fallback.
"""

from __future__ import annotations

import operator
from typing import Mapping


POSITION_LOGICAL_UNITS_PER_NATIVE_STEP = 2
POSITION_AXES = ("X", "Y", "Z")
INT32_MIN = -(2**31)
INT32_MAX = (2**31) - 1


class MotionPositionContractError(ValueError):
    """Raised when a requested endpoint cannot be represented safely."""


def _integer(value, *, label: str) -> int:
    if isinstance(value, bool):
        raise MotionPositionContractError(f"{label} must be an integer, not bool")
    try:
        result = operator.index(value)
    except TypeError as exc:
        raise MotionPositionContractError(f"{label} must be an integer") from exc
    return int(result)


def _int32(value, *, label: str) -> int:
    result = _integer(value, label=label)
    if result < INT32_MIN or result > INT32_MAX:
        raise MotionPositionContractError(f"{label} is outside signed 32-bit range")
    return result


def _quantum(value) -> int:
    result = _integer(value, label="position quantum")
    if result <= 0:
        raise MotionPositionContractError("position quantum must be positive")
    return result


def canonicalize_displacement(
    current,
    requested_delta,
    *,
    quantum=POSITION_LOGICAL_UNITS_PER_NATIVE_STEP,
) -> tuple[int, int]:
    """Return ``(canonical_delta, canonical_target)`` using C++ truncation.

    The firmware truncates odd displacement magnitudes toward zero.  Python's
    ``//`` floors negative values, so the sign and magnitude are handled
    separately here to retain exact parity with the firmware implementation.
    """

    origin = _int32(current, label="current position")
    delta = _integer(requested_delta, label="requested displacement")
    scale = _quantum(quantum)
    requested_target = origin + delta
    if requested_target < INT32_MIN or requested_target > INT32_MAX:
        raise MotionPositionContractError(
            "requested displacement produces a target outside signed 32-bit range"
        )

    magnitude = abs(delta)
    canonical_magnitude = (magnitude // scale) * scale
    canonical_delta = canonical_magnitude if delta >= 0 else -canonical_magnitude
    canonical_target = origin + canonical_delta
    return canonical_delta, canonical_target


def canonicalize_absolute_target(
    current,
    requested,
    *,
    quantum=POSITION_LOGICAL_UNITS_PER_NATIVE_STEP,
) -> int:
    """Return the endpoint the firmware will accept for one absolute axis."""

    origin = _int32(current, label="current position")
    target = _int32(requested, label="requested position")
    _delta, canonical = canonicalize_displacement(
        origin,
        target - origin,
        quantum=quantum,
    )
    return canonical


def canonicalize_position(
    origin: Mapping[str, object],
    requested: Mapping[str, object],
    *,
    quantum=POSITION_LOGICAL_UNITS_PER_NATIVE_STEP,
) -> dict:
    """Build JSON-safe requested/canonical endpoint evidence for X/Y/Z."""

    if not isinstance(origin, Mapping) or not isinstance(requested, Mapping):
        raise MotionPositionContractError(
            "origin and requested positions must be mappings"
        )
    scale = _quantum(quantum)
    normalized_origin = {}
    normalized_requested = {}
    canonical = {}
    for axis in POSITION_AXES:
        if axis not in origin or axis not in requested:
            raise MotionPositionContractError(f"position is missing axis {axis}")
        normalized_origin[axis] = _int32(origin[axis], label=f"origin {axis}")
        normalized_requested[axis] = _int32(
            requested[axis], label=f"requested {axis}"
        )
        canonical[axis] = canonicalize_absolute_target(
            normalized_origin[axis],
            normalized_requested[axis],
            quantum=scale,
        )

    adjustments = {
        axis: canonical[axis] - normalized_requested[axis]
        for axis in POSITION_AXES
    }
    return {
        "position_quantum": scale,
        "origin_position": normalized_origin,
        "requested_position": normalized_requested,
        "canonical_position": canonical,
        "adjustments": adjustments,
        "adjusted_axes": [axis for axis in POSITION_AXES if adjustments[axis] != 0],
    }


def canonicalize_relative_position(
    origin: Mapping[str, object],
    requested_displacement: Mapping[str, object],
    *,
    quantum=POSITION_LOGICAL_UNITS_PER_NATIVE_STEP,
) -> dict:
    """Build endpoint evidence from an X/Y/Z relative displacement request."""

    if not isinstance(origin, Mapping) or not isinstance(
        requested_displacement, Mapping
    ):
        raise MotionPositionContractError(
            "origin and requested displacements must be mappings"
        )
    scale = _quantum(quantum)
    normalized_origin = {}
    normalized_displacement = {}
    requested = {}
    for axis in POSITION_AXES:
        if axis not in origin or axis not in requested_displacement:
            raise MotionPositionContractError(
                f"relative position is missing axis {axis}"
            )
        normalized_origin[axis] = _int32(origin[axis], label=f"origin {axis}")
        normalized_displacement[axis] = _integer(
            requested_displacement[axis],
            label=f"requested {axis} displacement",
        )
        requested[axis] = normalized_origin[axis] + normalized_displacement[axis]
        if requested[axis] < INT32_MIN or requested[axis] > INT32_MAX:
            raise MotionPositionContractError(
                f"requested {axis} displacement produces a target outside signed 32-bit range"
            )

    plan = canonicalize_position(normalized_origin, requested, quantum=scale)
    plan["requested_displacement"] = normalized_displacement
    plan["canonical_displacement"] = {
        axis: plan["canonical_position"][axis] - normalized_origin[axis]
        for axis in POSITION_AXES
    }
    return plan
