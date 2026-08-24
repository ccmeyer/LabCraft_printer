"""Pure validation for calibration evidence that can authorize saved targets."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence


class ControlledCalibrationError(ValueError):
    """Controlled calibration evidence is incomplete or inconsistent."""


_WORKFLOW_POINTS = {
    "rack_calibration": ("rack_position_Left", "rack_position_Right"),
    "plate_calibration": (
        "top_left",
        "top_right",
        "bottom_right",
        "bottom_left",
    ),
}


@dataclass(frozen=True)
class ControlledCalibrationEvidence:
    workflow: str
    primary_target_key: str
    authorization_target_keys: tuple[str, ...]
    point_names: tuple[str, ...]
    trust_epoch: int


@dataclass(frozen=True)
class ControlledPositionCaptureEvidence:
    workflow: str
    target_name: str
    authorization_target_keys: tuple[str, ...]
    trust_epoch: int


def _point(value: object, label: str) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {"X", "Y", "Z"}:
        raise ControlledCalibrationError(f"{label} must contain exact X/Y/Z coordinates.")
    result: dict[str, int] = {}
    for axis in ("X", "Y", "Z"):
        coordinate = value.get(axis)
        if type(coordinate) is not int:
            raise ControlledCalibrationError(f"{label} {axis} must be an integer.")
        result[axis] = coordinate
    return result


def _validate_capture_record(
    raw_capture: object,
    *,
    workflow: str,
    point_name: str,
    expected: Mapping[str, object],
    machine_uuid: str,
    allow_unlabelled: bool = False,
) -> int:
    if not isinstance(raw_capture, Mapping):
        raise ControlledCalibrationError(f"Capture {point_name} is invalid.")
    labelled_workflow = raw_capture.get("workflow")
    labelled_point = raw_capture.get("target_key")
    if labelled_workflow is None and labelled_point is None:
        if not allow_unlabelled:
            raise ControlledCalibrationError("Capture labels are required.")
    elif labelled_workflow != workflow or labelled_point != point_name:
        raise ControlledCalibrationError("Capture order or workflow label differs.")
    if raw_capture.get("ready") is not True or raw_capture.get("reason_codes") != []:
        raise ControlledCalibrationError(f"Capture {point_name} was not ready.")
    if raw_capture.get("machine_uuid") != machine_uuid:
        raise ControlledCalibrationError(f"Capture {point_name} belongs to another machine.")
    trust_epoch = raw_capture.get("trust_epoch")
    if type(trust_epoch) is not int:
        raise ControlledCalibrationError(f"Capture {point_name} has no trust epoch.")

    captured = _point(raw_capture.get("captured_position"), f"capture {point_name}")
    commanded = _point(raw_capture.get("expected_position"), f"expected {point_name}")
    expected_point = _point(expected, f"committed {point_name}")
    if captured != commanded or captured != expected_point:
        raise ControlledCalibrationError(
            f"Capture {point_name} differs from the committed calibration."
        )

    reconciliation = raw_capture.get("position_reconciliation")
    if not isinstance(reconciliation, Mapping) or reconciliation.get("state") != "settled":
        raise ControlledCalibrationError(f"Capture {point_name} did not settle.")
    reconciled_expected = _point(
        reconciliation.get("expected_position"), f"reconciled expected {point_name}"
    )
    reconciled_reported = _point(
        reconciliation.get("reported_position"), f"reconciled reported {point_name}"
    )
    if reconciled_expected != captured or reconciled_reported != captured:
        raise ControlledCalibrationError(
            f"Capture {point_name} reconciliation differs from the saved point."
        )
    if reconciliation.get("trust_epoch") != trust_epoch:
        raise ControlledCalibrationError(
            f"Capture {point_name} reconciliation trust changed."
        )

    max_age = raw_capture.get("telemetry_max_age_ms")
    telemetry = raw_capture.get("telemetry")
    if type(max_age) is not int or max_age <= 0 or not isinstance(telemetry, Mapping):
        raise ControlledCalibrationError(f"Capture {point_name} telemetry policy is invalid.")
    for axis in ("X", "Y", "Z"):
        axis_evidence = telemetry.get(axis)
        if not isinstance(axis_evidence, Mapping):
            raise ControlledCalibrationError(f"Capture {point_name} lacks {axis} telemetry.")
        generation = axis_evidence.get("generation")
        age_ms = axis_evidence.get("age_ms")
        value = axis_evidence.get("value")
        if type(generation) is not int or generation <= 0:
            raise ControlledCalibrationError(f"Capture {point_name} {axis} generation is invalid.")
        if isinstance(age_ms, bool) or not isinstance(age_ms, (int, float)):
            raise ControlledCalibrationError(f"Capture {point_name} {axis} age is invalid.")
        if not math.isfinite(float(age_ms)) or age_ms < 0 or age_ms > max_age:
            raise ControlledCalibrationError(f"Capture {point_name} {axis} telemetry is stale.")
        if type(value) is not int or value != captured[axis]:
            raise ControlledCalibrationError(f"Capture {point_name} {axis} telemetry differs.")
    return trust_epoch


def validate_controlled_position_capture_evidence(
    assessment: Mapping[str, object],
    documents: Mapping[str, object],
    *,
    machine_uuid: str,
) -> ControlledPositionCaptureEvidence:
    """Validate one exact live-position capture used by a named-location save."""

    workflow = str(assessment.get("workflow") or "")
    if workflow not in {"named_location_add", "named_location_modify"}:
        raise ControlledCalibrationError(
            "Only named-location capture workflows can verify a saved location."
        )
    target_keys = assessment.get("target_keys")
    if (
        not isinstance(target_keys, Sequence)
        or isinstance(target_keys, (str, bytes))
        or len(target_keys) != 1
    ):
        raise ControlledCalibrationError("Named-location capture requires one target.")
    target_name = str(target_keys[0]).strip()
    locations = documents.get("Locations.json")
    if not target_name or not isinstance(locations, Mapping) or target_name not in locations:
        raise ControlledCalibrationError("The captured named location is missing.")
    if assessment.get("result") == "reject":
        raise ControlledCalibrationError("Rejected position evidence cannot verify a target.")
    if assessment.get("authorization_consequence") != "verified_by_controlled_position_capture":
        raise ControlledCalibrationError("Named-location capture is not marked for verification.")
    hard_checks = assessment.get("hard_checks")
    if (
        not isinstance(hard_checks, list)
        or any(
            not isinstance(item, Mapping) or item.get("passed") is not True
            for item in hard_checks
        )
        or "hard_validation_passed"
        not in {str(item.get("code") or "") for item in hard_checks}
    ):
        raise ControlledCalibrationError("Named-location hard validation is incomplete.")
    preconditions = assessment.get("preconditions")
    captures = preconditions.get("captures") if isinstance(preconditions, Mapping) else None
    if not isinstance(captures, list) or len(captures) != 1:
        raise ControlledCalibrationError("Named-location capture requires one capture record.")
    trust_epoch = _validate_capture_record(
        captures[0],
        workflow=workflow,
        point_name=target_name,
        expected=locations[target_name],
        machine_uuid=machine_uuid,
    )
    return ControlledPositionCaptureEvidence(
        workflow=workflow,
        target_name=target_name,
        authorization_target_keys=(f"location:{target_name.casefold()}",),
        trust_epoch=trust_epoch,
    )


def _expected_points(
    assessment: Mapping[str, object],
    documents: Mapping[str, object],
) -> tuple[tuple[str, ...], dict[str, dict[str, int]], str, tuple[str, ...]]:
    workflow = str(assessment.get("workflow") or "")
    point_names = _WORKFLOW_POINTS.get(workflow)
    if point_names is None:
        raise ControlledCalibrationError("Only rack and plate calibration can verify controlled targets.")

    if workflow == "rack_calibration":
        locations = documents.get("Locations.json")
        if not isinstance(locations, Mapping):
            raise ControlledCalibrationError("Rack calibration requires Locations.json.")
        expected = {
            name: _point(locations.get(name), f"rack point {name}")
            for name in point_names
        }
        primary = "rack:primary"
        authorization_keys = (
            primary,
            "location:rack_position_left",
            "location:rack_position_right",
        )
    else:
        target_keys = assessment.get("target_keys")
        if not isinstance(target_keys, Sequence) or isinstance(target_keys, (str, bytes)) or len(target_keys) != 1:
            raise ControlledCalibrationError("Plate calibration requires one plate target.")
        plate_name = str(target_keys[0]).strip()
        plates = documents.get("Plates.json")
        if not plate_name or not isinstance(plates, list):
            raise ControlledCalibrationError("Plate calibration requires Plates.json and one plate name.")
        plate = next(
            (
                item for item in plates
                if isinstance(item, Mapping) and item.get("name") == plate_name
            ),
            None,
        )
        if plate is None or not isinstance(plate.get("calibrations"), Mapping):
            raise ControlledCalibrationError("The calibrated plate is missing from Plates.json.")
        expected = {
            name: _point(plate["calibrations"].get(name), f"plate point {name}")
            for name in point_names
        }
        primary = f"plate:{plate_name.casefold()}"
        hard_codes = {
            str(item.get("code") or "")
            for item in assessment.get("hard_checks", [])
            if isinstance(item, Mapping)
        }
        authorization_keys = (primary,)
        if "plate_pause_location_derived" in hard_codes:
            locations = documents.get("Locations.json")
            if not isinstance(locations, Mapping):
                raise ControlledCalibrationError(
                    "Pause derivation requires Locations.json."
                )
            pause_names = [
                str(name) for name in locations if str(name).casefold() == "pause"
            ]
            if len(pause_names) != 1:
                raise ControlledCalibrationError(
                    "Pause derivation requires one saved Pause location."
                )
            pause = _point(locations[pause_names[0]], "derived Pause location")
            if pause["Z"] != expected["top_left"]["Z"]:
                raise ControlledCalibrationError(
                    "Derived Pause Z differs from the calibrated top-left Z."
                )
            authorization_keys = (primary, "location:pause")

    return point_names, expected, primary, authorization_keys


def validate_controlled_calibration_evidence(
    assessment: Mapping[str, object],
    documents: Mapping[str, object],
    *,
    machine_uuid: str,
    allow_legacy_unlabelled_captures: bool = False,
    require_pause_derivation: bool = False,
) -> ControlledCalibrationEvidence:
    """Validate exact physical capture evidence and return authorized target keys."""

    workflow = str(assessment.get("workflow") or "")
    point_names, expected, primary, authorization_keys = _expected_points(
        assessment, documents
    )
    if assessment.get("result") == "reject":
        raise ControlledCalibrationError("Rejected calibration evidence cannot verify a target.")
    hard_checks = assessment.get("hard_checks")
    if not isinstance(hard_checks, list) or not hard_checks:
        raise ControlledCalibrationError("Calibration hard checks are missing.")
    if any(not isinstance(item, Mapping) or item.get("passed") is not True for item in hard_checks):
        raise ControlledCalibrationError("Every calibration hard check must pass.")
    required_codes = {
        "hard_validation_passed",
        "rack_geometry_valid" if workflow == "rack_calibration" else "plate_geometry_valid",
        "rack_derived_slots" if workflow == "rack_calibration" else "plate_derived_wells",
    }
    if workflow == "plate_calibration" and require_pause_derivation:
        required_codes.add("plate_pause_location_derived")
    codes = {str(item.get("code") or "") for item in hard_checks}
    if not required_codes.issubset(codes):
        raise ControlledCalibrationError("Calibration geometry evidence is incomplete.")

    preconditions = assessment.get("preconditions")
    captures = preconditions.get("captures") if isinstance(preconditions, Mapping) else None
    if not isinstance(captures, list) or len(captures) != len(point_names):
        raise ControlledCalibrationError(
            f"{workflow} requires exactly {len(point_names)} capture records."
        )

    trust_epochs: set[int] = set()
    for point_name, raw_capture in zip(point_names, captures):
        trust_epoch = _validate_capture_record(
            raw_capture,
            workflow=workflow,
            point_name=point_name,
            expected=expected[point_name],
            machine_uuid=machine_uuid,
            allow_unlabelled=allow_legacy_unlabelled_captures,
        )
        trust_epochs.add(trust_epoch)

    if len(trust_epochs) != 1:
        raise ControlledCalibrationError("Calibration captures do not share one trust epoch.")
    return ControlledCalibrationEvidence(
        workflow=workflow,
        primary_target_key=primary,
        authorization_target_keys=authorization_keys,
        point_names=tuple(point_names),
        trust_epoch=next(iter(trust_epochs)),
    )


__all__ = [
    "ControlledCalibrationError",
    "ControlledCalibrationEvidence",
    "ControlledPositionCaptureEvidence",
    "validate_controlled_calibration_evidence",
    "validate_controlled_position_capture_evidence",
]
