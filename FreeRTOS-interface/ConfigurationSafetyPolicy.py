"""Pure, versioned safety policy for coordinate configuration and motion endpoints.

This module has no Qt, machine transport, Model, or filesystem-write dependency.
It parses the tracked release policy and the active machine's Obstacles document,
assesses complete configuration proposals, and validates motion endpoints.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

from MachineDataArchive import canonical_json_bytes


POLICY_SCHEMA_NAME = "labcraft.configuration_change_policy"
POLICY_SCHEMA_VERSION = 1
ASSESSMENT_SCHEMA_NAME = "labcraft.configuration_guard_assessment"
ASSESSMENT_SCHEMA_VERSION = 1
AXES = ("X", "Y", "Z")
CONFIRMATION_RESULTS = frozenset(
    {"routine_confirmation", "strong_confirmation", "reject"}
)
WORKFLOWS = frozenset(
    {
        "named_location_add",
        "named_location_modify",
        "rack_calibration",
        "plate_calibration",
        "governed_configuration_import",
        "configuration_restore",
        "configuration_target_verification",
    }
)


class ConfigurationSafetyError(ValueError):
    """Raised when policy, bounds, assessment, or proposal evidence is invalid."""


def _strict_int(value: object, label: str) -> int:
    if type(value) is not int:
        raise ConfigurationSafetyError(f"{label} must be an integer.")
    return value


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationSafetyError(f"{label} must be nonempty text.")
    return value.strip()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def proposal_sha256(documents: Mapping[str, object]) -> str:
    if not isinstance(documents, Mapping) or not documents:
        raise ConfigurationSafetyError("Proposal documents must be a nonempty mapping.")
    normalized = {}
    for filename in sorted(documents):
        if not isinstance(filename, str) or not filename:
            raise ConfigurationSafetyError("Proposal filenames must be nonempty text.")
        normalized[filename] = copy.deepcopy(documents[filename])
    try:
        return _sha256_bytes(canonical_json_bytes(normalized))
    except (TypeError, ValueError) as exc:
        raise ConfigurationSafetyError(f"Proposal is not canonical JSON: {exc}") from exc


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType(copy.deepcopy(dict(value)))


@dataclass(frozen=True)
class ConfigurationChangePolicy:
    policy_id: str
    raw_sha256: str
    supported_hardware_profiles: tuple[str, ...]
    position_telemetry_max_age_ms: int
    reserved_location_names: tuple[str, ...]
    pair_only_location_names: tuple[str, ...]
    reserved_location_prefixes: tuple[str, ...]
    always_strong_target_classes: frozenset[str]
    warning_thresholds_steps: Mapping[str, object]
    rack_slot_count: int
    rack_orientation_axis: str
    rack_orientation_direction: str
    plate_initial_orientation: str
    maximum_transform_condition_number: float | None
    confirmation_phrase_version: int
    confirmation_template: str
    rationale: str
    approval_reference: str

    def classify_location(self, name: str, *, is_new: bool = False) -> str:
        folded = _nonempty_text(name, "location name").casefold()
        if is_new:
            return "new_target"
        if folded == "camera":
            return "camera"
        if folded in {item.casefold() for item in self.reserved_location_names}:
            return "reserved_location"
        return "generic_location"

    def is_pair_only_name(self, name: str) -> bool:
        folded = str(name).casefold()
        return folded in {item.casefold() for item in self.pair_only_location_names}

    def has_reserved_prefix(self, name: str) -> bool:
        folded = str(name).casefold()
        return any(folded.startswith(prefix.casefold()) for prefix in self.reserved_location_prefixes)

    def required_phrase(self, target: str, proposal_hash: str) -> str:
        return self.confirmation_template.format(
            target=str(target), proposal_short_hash=str(proposal_hash)[:12]
        )


def _expect_exact_keys(payload: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(payload) != expected:
        raise ConfigurationSafetyError(
            f"{label} keys differ; missing={sorted(expected.difference(payload))}, "
            f"extra={sorted(set(payload).difference(expected))}."
        )


_POLICY_KEYS = {
    "schema_name",
    "schema_version",
    "policy_id",
    "supported_hardware_profiles",
    "position_telemetry_max_age_ms",
    "reserved_location_names",
    "pair_only_location_names",
    "reserved_location_prefixes",
    "always_strong_target_classes",
    "warning_thresholds_steps",
    "rack",
    "plate",
    "confirmation",
    "rationale",
    "approval_reference",
}


def parse_configuration_change_policy(
    payload: object, *, raw_sha256: str
) -> ConfigurationChangePolicy:
    if not isinstance(payload, dict):
        raise ConfigurationSafetyError("Configuration-change policy must be an object.")
    _expect_exact_keys(payload, _POLICY_KEYS, "configuration-change policy")
    if payload.get("schema_name") != POLICY_SCHEMA_NAME:
        raise ConfigurationSafetyError("Unknown configuration-change policy schema.")
    if payload.get("schema_version") != POLICY_SCHEMA_VERSION:
        raise ConfigurationSafetyError("Unknown configuration-change policy version.")
    if not isinstance(raw_sha256, str) or len(raw_sha256) != 64 or any(
        char not in "0123456789abcdef" for char in raw_sha256
    ):
        raise ConfigurationSafetyError("Policy SHA-256 is invalid.")

    def unique_text_list(key: str) -> tuple[str, ...]:
        raw = payload.get(key)
        if not isinstance(raw, list) or not raw:
            raise ConfigurationSafetyError(f"Policy {key} must be a nonempty list.")
        values = tuple(_nonempty_text(item, f"policy {key} item") for item in raw)
        if len({item.casefold() for item in values}) != len(values):
            raise ConfigurationSafetyError(f"Policy {key} contains duplicates.")
        return values

    profiles = unique_text_list("supported_hardware_profiles")
    if set(profiles) != {"current", "legacy"}:
        raise ConfigurationSafetyError("Policy must explicitly support current and legacy profiles.")
    reserved = unique_text_list("reserved_location_names")
    pair_only = unique_text_list("pair_only_location_names")
    if not {item.casefold() for item in pair_only}.issubset(
        {item.casefold() for item in reserved}
    ):
        raise ConfigurationSafetyError("Pair-only names must also be reserved names.")
    prefixes = unique_text_list("reserved_location_prefixes")
    classes = frozenset(unique_text_list("always_strong_target_classes"))
    allowed_classes = {
        "camera", "reserved_location", "generic_location", "rack", "plate", "new_target"
    }
    if not classes.issubset(allowed_classes):
        raise ConfigurationSafetyError("Policy contains an unknown target class.")
    max_age = _strict_int(
        payload.get("position_telemetry_max_age_ms"),
        "position_telemetry_max_age_ms",
    )
    if max_age <= 0:
        raise ConfigurationSafetyError("Telemetry maximum age must be positive.")
    thresholds = payload.get("warning_thresholds_steps")
    if not isinstance(thresholds, dict):
        raise ConfigurationSafetyError("warning_thresholds_steps must be an object.")
    for target, axes in thresholds.items():
        _nonempty_text(target, "threshold target")
        if not isinstance(axes, dict) or not axes:
            raise ConfigurationSafetyError("Each threshold target must contain axis thresholds.")
        for axis, threshold in axes.items():
            if axis not in AXES:
                raise ConfigurationSafetyError(f"Unknown threshold axis {axis!r}.")
            if type(threshold) is not int or threshold < 0:
                raise ConfigurationSafetyError("Thresholds must be nonnegative integers.")

    rack = payload.get("rack")
    plate = payload.get("plate")
    confirmation = payload.get("confirmation")
    if not isinstance(rack, dict) or not isinstance(plate, dict) or not isinstance(confirmation, dict):
        raise ConfigurationSafetyError("Policy rack, plate, and confirmation entries must be objects.")
    _expect_exact_keys(rack, {"slot_count", "orientation_axis", "orientation_direction"}, "rack policy")
    _expect_exact_keys(plate, {"initial_orientation", "maximum_transform_condition_number"}, "plate policy")
    _expect_exact_keys(confirmation, {"phrase_version", "template"}, "confirmation policy")
    slot_count = _strict_int(rack.get("slot_count"), "rack slot_count")
    if slot_count <= 0:
        raise ConfigurationSafetyError("Rack slot_count must be positive.")
    orientation_axis = _nonempty_text(rack.get("orientation_axis"), "rack orientation axis")
    if orientation_axis not in AXES:
        raise ConfigurationSafetyError("Rack orientation axis is unknown.")
    orientation_direction = _nonempty_text(
        rack.get("orientation_direction"), "rack orientation direction"
    )
    if orientation_direction not in {"increasing", "decreasing"}:
        raise ConfigurationSafetyError("Rack orientation direction is unknown.")
    plate_orientation = _nonempty_text(
        plate.get("initial_orientation"), "plate initial orientation"
    )
    if plate_orientation not in {"clockwise", "counterclockwise"}:
        raise ConfigurationSafetyError("Plate initial orientation is unknown.")
    condition = plate.get("maximum_transform_condition_number")
    if condition is not None:
        if isinstance(condition, bool) or not isinstance(condition, (int, float)):
            raise ConfigurationSafetyError("Plate condition limit must be numeric or null.")
        condition = float(condition)
        if not math.isfinite(condition) or condition <= 1:
            raise ConfigurationSafetyError("Plate condition limit must be finite and greater than one.")
    phrase_version = _strict_int(confirmation.get("phrase_version"), "phrase_version")
    template = _nonempty_text(confirmation.get("template"), "confirmation template")
    if "{target}" not in template or "{proposal_short_hash}" not in template:
        raise ConfigurationSafetyError("Confirmation template must bind target and proposal hash.")

    return ConfigurationChangePolicy(
        policy_id=_nonempty_text(payload.get("policy_id"), "policy_id"),
        raw_sha256=raw_sha256,
        supported_hardware_profiles=profiles,
        position_telemetry_max_age_ms=max_age,
        reserved_location_names=reserved,
        pair_only_location_names=pair_only,
        reserved_location_prefixes=prefixes,
        always_strong_target_classes=classes,
        warning_thresholds_steps=_freeze_mapping(thresholds),
        rack_slot_count=slot_count,
        rack_orientation_axis=orientation_axis,
        rack_orientation_direction=orientation_direction,
        plate_initial_orientation=plate_orientation,
        maximum_transform_condition_number=condition,
        confirmation_phrase_version=phrase_version,
        confirmation_template=template,
        rationale=_nonempty_text(payload.get("rationale"), "policy rationale"),
        approval_reference=_nonempty_text(
            payload.get("approval_reference"), "policy approval_reference"
        ),
    )


def load_configuration_change_policy(path: str | Path | None = None) -> ConfigurationChangePolicy:
    policy_path = Path(path) if path is not None else (
        Path(__file__).resolve().parent / "Policies" / "configuration_change_policy_v1.json"
    )
    try:
        raw = policy_path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationSafetyError(f"Cannot load configuration safety policy: {exc}") from exc
    return parse_configuration_change_policy(payload, raw_sha256=_sha256_bytes(raw))


@dataclass(frozen=True)
class SafetyBounds:
    minimum: Mapping[str, int]
    maximum: Mapping[str, int]
    obstacles: tuple[tuple[Mapping[str, int], Mapping[str, int]], ...]

    def point_result(self, point: Mapping[str, object]) -> tuple[bool, str]:
        try:
            normalized = _point(point, "point")
        except ConfigurationSafetyError:
            return False, "invalid_coordinate"
        for axis in AXES:
            if not self.minimum[axis] <= normalized[axis] <= self.maximum[axis]:
                return False, f"outside_global_bounds_{axis.lower()}"
        for low, high in self.obstacles:
            if all(low[axis] <= normalized[axis] <= high[axis] for axis in AXES):
                return False, "inside_configured_exclusion"
        return True, (
            "no_configured_exclusion_geometry" if not self.obstacles else "point_clear"
        )

    def require_endpoint(self, point: Mapping[str, object]) -> dict[str, int]:
        normalized = _point(point, "motion endpoint")
        for axis in AXES:
            if not self.minimum[axis] <= normalized[axis] <= self.maximum[axis]:
                raise ConfigurationSafetyError(
                    f"Motion endpoint {axis}={normalized[axis]} is outside global bounds "
                    f"[{self.minimum[axis]}, {self.maximum[axis]}]."
                )
        return normalized


def _point(value: object, label: str) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != set(AXES):
        raise ConfigurationSafetyError(f"{label} must contain exactly X, Y, and Z.")
    return {axis: _strict_int(value[axis], f"{label} {axis}") for axis in AXES}


def parse_safety_bounds(payload: object) -> SafetyBounds:
    if not isinstance(payload, Mapping) or set(payload) != {"boundaries", "obstacles"}:
        raise ConfigurationSafetyError(
            "Obstacles.json must contain exactly boundaries and obstacles."
        )
    boundaries = payload.get("boundaries")
    if not isinstance(boundaries, Mapping) or set(boundaries) != {"min", "max"}:
        raise ConfigurationSafetyError("Obstacles boundaries must contain exactly min and max.")
    minimum = _point(boundaries["min"], "boundary min")
    maximum = _point(boundaries["max"], "boundary max")
    for axis in AXES:
        if minimum[axis] > maximum[axis]:
            raise ConfigurationSafetyError(f"Boundary min exceeds max for {axis}.")
    raw_obstacles = payload.get("obstacles")
    if not isinstance(raw_obstacles, list):
        raise ConfigurationSafetyError("Obstacles must be a list.")
    obstacles = []
    for index, item in enumerate(raw_obstacles):
        if not isinstance(item, Mapping) or set(item) != {"corner1", "corner2"}:
            raise ConfigurationSafetyError(
                f"Obstacle {index} must contain exactly corner1 and corner2."
            )
        one = _point(item["corner1"], f"obstacle {index} corner1")
        two = _point(item["corner2"], f"obstacle {index} corner2")
        low = {axis: min(one[axis], two[axis]) for axis in AXES}
        high = {axis: max(one[axis], two[axis]) for axis in AXES}
        obstacles.append((_freeze_mapping(low), _freeze_mapping(high)))
    return SafetyBounds(_freeze_mapping(minimum), _freeze_mapping(maximum), tuple(obstacles))


def _signed_area(points: Sequence[Mapping[str, int]]) -> float:
    return 0.5 * sum(
        points[index]["X"] * points[(index + 1) % len(points)]["Y"]
        - points[(index + 1) % len(points)]["X"] * points[index]["Y"]
        for index in range(len(points))
    )


def _cross(a: Mapping[str, int], b: Mapping[str, int], c: Mapping[str, int]) -> int:
    return (b["X"] - a["X"]) * (c["Y"] - b["Y"]) - (
        b["Y"] - a["Y"]
    ) * (c["X"] - b["X"])


def _solve_linear(matrix: list[list[float]], values: list[float]) -> list[float]:
    """Solve a small dense system with partial pivoting, rejecting singular input."""

    size = len(values)
    augmented = [list(map(float, matrix[row])) + [float(values[row])] for row in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= 1e-12:
            raise ConfigurationSafetyError("Plate perspective transform is singular.")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = augmented[column][column]
        augmented[column] = [value / scale for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                augmented[row][item] - factor * augmented[column][item]
                for item in range(size + 1)
            ]
    solution = [augmented[row][-1] for row in range(size)]
    if not all(math.isfinite(value) for value in solution):
        raise ConfigurationSafetyError("Plate perspective transform is not finite.")
    return solution


def _logical_to_machine_homography(points, rows, columns, spacing):
    if rows <= 1 or columns <= 1:
        raise ConfigurationSafetyError("Perspective-calibrated plates require at least two rows and columns.")
    depth = float((rows - 1) * spacing)
    width = float((columns - 1) * spacing)
    sources = ((0.0, 0.0), (0.0, width), (depth, width), (depth, 0.0))
    matrix = []
    values = []
    for (u, v), point in zip(sources, points):
        x = float(point["X"])
        y = float(point["Y"])
        matrix.append([u, v, 1.0, 0.0, 0.0, 0.0, -u * x, -v * x])
        values.append(x)
        matrix.append([0.0, 0.0, 0.0, u, v, 1.0, -u * y, -v * y])
        values.append(y)
    values8 = _solve_linear(matrix, values)
    return (
        (values8[0], values8[1], values8[2]),
        (values8[3], values8[4], values8[5]),
        (values8[6], values8[7], 1.0),
    )


def _apply_homography(transform, u, v):
    denominator = transform[2][0] * u + transform[2][1] * v + transform[2][2]
    if not math.isfinite(denominator) or abs(denominator) <= 1e-12:
        raise ConfigurationSafetyError("Derived plate well reaches a singular transform point.")
    x = (transform[0][0] * u + transform[0][1] * v + transform[0][2]) / denominator
    y = (transform[1][0] * u + transform[1][1] * v + transform[1][2]) / denominator
    if not math.isfinite(x) or not math.isfinite(y):
        raise ConfigurationSafetyError("Derived plate well coordinate is not finite.")
    return x, y


def _validate_rack(
    locations: Mapping[str, object], bounds: SafetyBounds, policy: ConfigurationChangePolicy
) -> tuple[list[dict[str, int]], list[dict[str, object]]]:
    checks = []
    left = _point(locations.get("rack_position_Left"), "rack_position_Left")
    right = _point(locations.get("rack_position_Right"), "rack_position_Right")
    if left == right:
        raise ConfigurationSafetyError("Rack anchors must be distinct.")
    axis = policy.rack_orientation_axis
    oriented = (
        right[axis] > left[axis]
        if policy.rack_orientation_direction == "increasing"
        else right[axis] < left[axis]
    )
    if not oriented:
        raise ConfigurationSafetyError("Rack anchors violate the approved orientation.")
    derived = []
    for index in range(1, policy.rack_slot_count + 1):
        point = {
            item: int(round(left[item] + index * (right[item] - left[item]) / (policy.rack_slot_count + 1)))
            for item in AXES
        }
        ok, code = bounds.point_result(point)
        if not ok:
            raise ConfigurationSafetyError(f"Derived rack slot {index - 1} is invalid: {code}.")
        derived.append(point)
    if len({tuple(point[axis] for axis in AXES) for point in derived}) != len(derived):
        raise ConfigurationSafetyError("Derived rack slots collapse after integer rounding.")
    checks.append({"code": "rack_geometry_valid", "passed": True, "message": "Rack anchors and derived slots are valid."})
    return derived, checks


def _validate_plate_calibration(
    plate: Mapping[str, object],
    bounds: SafetyBounds,
    policy: ConfigurationChangePolicy,
    prior_calibrations: Mapping[str, object] | None,
) -> tuple[list[dict[str, int]], list[dict[str, object]]]:
    names = ("top_left", "top_right", "bottom_right", "bottom_left")
    calibrations = plate.get("calibrations")
    if not isinstance(calibrations, Mapping) or set(calibrations) != set(names):
        raise ConfigurationSafetyError(f"Plate {plate.get('name')!r} requires all four corners.")
    points = [_point(calibrations[name], f"plate {plate.get('name')} {name}") for name in names]
    for name, point in zip(names, points):
        ok, code = bounds.point_result(point)
        if not ok:
            raise ConfigurationSafetyError(f"Plate corner {name} is invalid: {code}.")
    if len({tuple(point[axis] for axis in AXES) for point in points}) != 4:
        raise ConfigurationSafetyError("Plate corners must be distinct.")
    crosses = [_cross(points[index - 1], points[index], points[(index + 1) % 4]) for index in range(4)]
    if any(value == 0 for value in crosses) or not (
        all(value > 0 for value in crosses) or all(value < 0 for value in crosses)
    ):
        raise ConfigurationSafetyError("Plate corners must form a simple convex quadrilateral.")
    area = _signed_area(points)
    if area == 0:
        raise ConfigurationSafetyError("Plate calibration area is zero.")
    actual_orientation = "counterclockwise" if area > 0 else "clockwise"
    expected_orientation = policy.plate_initial_orientation
    if prior_calibrations:
        try:
            prior_points = [_point(prior_calibrations[name], f"prior plate {name}") for name in names]
            prior_area = _signed_area(prior_points)
            if prior_area:
                expected_orientation = "counterclockwise" if prior_area > 0 else "clockwise"
        except ConfigurationSafetyError:
            pass
    if actual_orientation != expected_orientation:
        raise ConfigurationSafetyError("Plate calibration reverses the approved orientation.")

    rows = _strict_int(plate.get("rows"), "plate rows")
    columns = _strict_int(plate.get("columns"), "plate columns")
    if rows <= 0 or columns <= 0:
        raise ConfigurationSafetyError("Plate dimensions must be positive.")
    spacing = plate.get("spacing")
    if isinstance(spacing, bool) or not isinstance(spacing, (int, float)) or not math.isfinite(float(spacing)) or spacing <= 0:
        raise ConfigurationSafetyError("Plate spacing must be finite and positive.")
    transform = _logical_to_machine_homography(points, rows, columns, spacing)
    determinant = (
        transform[0][0] * (transform[1][1] * transform[2][2] - transform[1][2] * transform[2][1])
        - transform[0][1] * (transform[1][0] * transform[2][2] - transform[1][2] * transform[2][0])
        + transform[0][2] * (transform[1][0] * transform[2][1] - transform[1][1] * transform[2][0])
    )
    if not math.isfinite(determinant) or abs(determinant) <= 1e-12:
        raise ConfigurationSafetyError("Plate perspective transform is not invertible.")
    derived = []
    for row in range(rows):
        for column in range(columns):
            x, y = _apply_homography(transform, row * float(spacing), column * float(spacing))
            point = {
                "X": int(round(x)),
                "Y": int(round(y)),
                "Z": int(round(
                    points[0]["Z"]
                    + row * (points[3]["Z"] - points[0]["Z"]) / rows
                    + column * (points[1]["Z"] - points[0]["Z"]) / columns
                )),
            }
            ok, code = bounds.point_result(point)
            if not ok:
                raise ConfigurationSafetyError(
                    f"Derived plate well ({row}, {column}) is invalid: {code}."
                )
            derived.append(point)
    if len({tuple(point[axis] for axis in AXES) for point in derived}) != len(derived):
        raise ConfigurationSafetyError("Derived plate wells collapse after integer rounding.")
    return derived, [{"code": "plate_geometry_valid", "passed": True, "message": "Plate corners and derived wells are valid."}]


def _config_hashes(documents: Mapping[str, object]) -> dict[str, str]:
    return {
        filename: _sha256_bytes(canonical_json_bytes(value))
        for filename, value in sorted(documents.items())
    }


def _coordinate_changes(
    before: Mapping[str, object] | None,
    after: Mapping[str, object],
    *,
    names: Sequence[str],
) -> list[dict[str, object]]:
    changes = []
    for name in names:
        proposed = _point(after[name], f"proposed {name}")
        prior_raw = before.get(name) if isinstance(before, Mapping) else None
        prior = _point(prior_raw, f"prior {name}") if prior_raw is not None else None
        deltas = {
            axis: None if prior is None else proposed[axis] - prior[axis]
            for axis in AXES
        }
        changes.append(
            {
                "target_key": name,
                "before": prior,
                "proposed": proposed,
                "signed_delta": deltas,
                "absolute_delta": {
                    axis: None if deltas[axis] is None else abs(deltas[axis])
                    for axis in AXES
                },
            }
        )
    return changes


class ConfigurationChangeGuard:
    def __init__(self, policy: ConfigurationChangePolicy, bounds: SafetyBounds):
        if not isinstance(policy, ConfigurationChangePolicy):
            raise TypeError("policy must be ConfigurationChangePolicy")
        if not isinstance(bounds, SafetyBounds):
            raise TypeError("bounds must be SafetyBounds")
        self.policy = policy
        self.bounds = bounds

    def validate_active_documents(self, documents: Mapping[str, object]) -> None:
        locations = documents.get("Locations.json")
        plates = documents.get("Plates.json")
        settings = documents.get("Settings.json")
        if not isinstance(locations, Mapping) or not isinstance(plates, list) or not isinstance(settings, Mapping):
            raise ConfigurationSafetyError("Active governed documents are incomplete.")
        profile = settings.get("HARDWARE_PROFILE", "current")
        if profile not in self.policy.supported_hardware_profiles:
            raise ConfigurationSafetyError(f"Hardware profile {profile!r} is not covered by the policy.")
        folded = set()
        for name, raw in locations.items():
            key = _nonempty_text(name, "location name").casefold()
            if key in folded:
                raise ConfigurationSafetyError("Location names are not unique ignoring case.")
            folded.add(key)
            if self.policy.has_reserved_prefix(name):
                raise ConfigurationSafetyError(f"Persisted location {name!r} uses a reserved prefix.")
            ok, code = self.bounds.point_result(_point(raw, f"location {name}"))
            if not ok:
                raise ConfigurationSafetyError(f"Location {name!r} is invalid: {code}.")
        _validate_rack(locations, self.bounds, self.policy)
        for plate in plates:
            if not isinstance(plate, Mapping):
                raise ConfigurationSafetyError("Plate entries must be objects.")
            calibrations = plate.get("calibrations")
            if calibrations:
                _validate_plate_calibration(plate, self.bounds, self.policy, None)

    def validate_endpoint(self, point: Mapping[str, object]) -> dict[str, int]:
        return self.bounds.require_endpoint(point)

    def assess(
        self,
        *,
        before_documents: Mapping[str, object],
        proposed_documents: Mapping[str, object],
        workflow: str,
        target_keys: Sequence[str],
        hardware_profile: str,
        preconditions: Mapping[str, object] | None = None,
        governed_file_sha256: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        workflow = _nonempty_text(workflow, "workflow")
        if workflow not in WORKFLOWS:
            raise ConfigurationSafetyError(f"Unsupported guarded workflow {workflow!r}.")
        if hardware_profile not in self.policy.supported_hardware_profiles:
            raise ConfigurationSafetyError("Hardware profile is not covered by the active policy.")
        target_keys = tuple(_nonempty_text(item, "target key") for item in target_keys)
        if not target_keys or len(set(target_keys)) != len(target_keys):
            raise ConfigurationSafetyError("Guard target keys must be nonempty and unique.")
        proposal_hash = proposal_sha256(proposed_documents)
        hard_checks: list[dict[str, object]] = []
        result = "strong_confirmation"
        rejection_code = None
        changes: list[dict[str, object]] = []
        target_class = "generic_location"
        try:
            complete = copy.deepcopy(dict(before_documents))
            complete.update(copy.deepcopy(dict(proposed_documents)))
            self.validate_active_documents(complete)
            locations_before = before_documents.get("Locations.json", {})
            locations_after = complete.get("Locations.json", {})
            if workflow.startswith("named_location"):
                name = target_keys[0]
                if self.policy.is_pair_only_name(name) or self.policy.has_reserved_prefix(name):
                    raise ConfigurationSafetyError(
                        f"Location {name!r} can only be changed by its dedicated workflow."
                    )
                changes = _coordinate_changes(locations_before, locations_after, names=(name,))
                target_class = self.policy.classify_location(
                    name, is_new=name not in locations_before
                )
            elif workflow == "rack_calibration":
                rack_names = ("rack_position_Left", "rack_position_Right")
                if set(target_keys) != set(rack_names):
                    raise ConfigurationSafetyError("Rack calibration must assess both anchors.")
                changes = _coordinate_changes(locations_before, locations_after, names=rack_names)
                prior_orientation = None
                try:
                    prior_left = _point(locations_before["rack_position_Left"], "prior rack left")
                    prior_right = _point(locations_before["rack_position_Right"], "prior rack right")
                    prior_orientation = math.copysign(
                        1, prior_right[self.policy.rack_orientation_axis] - prior_left[self.policy.rack_orientation_axis]
                    )
                except (ConfigurationSafetyError, KeyError, ValueError):
                    pass
                derived, rack_checks = _validate_rack(locations_after, self.bounds, self.policy)
                hard_checks.extend(rack_checks)
                if prior_orientation is not None:
                    new_left = locations_after["rack_position_Left"]
                    new_right = locations_after["rack_position_Right"]
                    new_orientation = math.copysign(
                        1, new_right[self.policy.rack_orientation_axis] - new_left[self.policy.rack_orientation_axis]
                    )
                    if new_orientation != prior_orientation:
                        raise ConfigurationSafetyError("Rack calibration reverses prior orientation.")
                hard_checks.append({"code": "rack_derived_slots", "passed": True, "message": f"{len(derived)} derived slots are hard-valid."})
                target_class = "rack"
            elif workflow == "plate_calibration":
                plates_before = before_documents.get("Plates.json", [])
                plates_after = complete.get("Plates.json", [])
                plate_name = target_keys[0]
                prior_plate = next((item for item in plates_before if item.get("name") == plate_name), None)
                proposed_plate = next((item for item in plates_after if item.get("name") == plate_name), None)
                if proposed_plate is None:
                    raise ConfigurationSafetyError(f"Proposed plate {plate_name!r} is missing.")
                corner_names = ("top_left", "top_right", "bottom_right", "bottom_left")
                prior_cals = prior_plate.get("calibrations") if prior_plate else None
                changes = _coordinate_changes(
                    prior_cals if prior_cals else {}, proposed_plate["calibrations"], names=corner_names
                )
                derived, plate_checks = _validate_plate_calibration(
                    proposed_plate, self.bounds, self.policy, prior_cals
                )
                hard_checks.extend(plate_checks)
                hard_checks.append({"code": "plate_derived_wells", "passed": True, "message": f"{len(derived)} derived wells are hard-valid."})
                target_class = "plate"
            else:
                # Imports/restores compare every changed coordinate so the
                # preview cannot hide a large axis behind a file-level label.
                if "Locations.json" in proposed_documents:
                    old_locations = before_documents.get("Locations.json", {})
                    new_locations = complete.get("Locations.json", {})
                    changed_names = sorted(
                        name for name in set(old_locations) | set(new_locations)
                        if old_locations.get(name) != new_locations.get(name)
                    )
                    removed = [name for name in changed_names if name not in new_locations]
                    if removed:
                        raise ConfigurationSafetyError(
                            "Coordinate import/restore cannot remove saved locations: "
                            + ", ".join(removed)
                        )
                    changes.extend(
                        _coordinate_changes(old_locations, new_locations, names=changed_names)
                    )
                if "Plates.json" in proposed_documents:
                    old_plates = {
                        item.get("name"): item for item in before_documents.get("Plates.json", [])
                    }
                    new_plates = {
                        item.get("name"): item for item in complete.get("Plates.json", [])
                    }
                    for plate_name in sorted(set(old_plates) | set(new_plates)):
                        old_cal = (old_plates.get(plate_name) or {}).get("calibrations") or {}
                        new_cal = (new_plates.get(plate_name) or {}).get("calibrations") or {}
                        if old_cal == new_cal:
                            continue
                        if not new_cal:
                            raise ConfigurationSafetyError(
                                f"Coordinate import/restore cannot remove calibration for {plate_name!r}."
                            )
                        changes.extend(
                            _coordinate_changes(
                                old_cal,
                                new_cal,
                                names=("top_left", "top_right", "bottom_right", "bottom_left"),
                            )
                        )
                target_class = "reserved_location"
            hard_checks.insert(0, {"code": "hard_validation_passed", "passed": True, "message": "All configured hard rules passed."})
        except ConfigurationSafetyError as exc:
            result = "reject"
            rejection_code = "hard_validation_failed"
            hard_checks.append({"code": rejection_code, "passed": False, "message": str(exc)})

        thresholds = []
        classifications = []
        for change in changes:
            for axis in AXES:
                delta = change["absolute_delta"][axis]
                configured = None
                target_rule = self.policy.warning_thresholds_steps.get(change["target_key"])
                if not isinstance(target_rule, Mapping):
                    target_rule = self.policy.warning_thresholds_steps.get(target_class)
                if isinstance(target_rule, Mapping):
                    configured = target_rule.get(axis)
                if target_class in self.policy.always_strong_target_classes:
                    classification = "strong_confirmation"
                    rule = f"always_strong_target_class:{target_class}"
                elif delta is None:
                    classification = "strong_confirmation"
                    rule = "new_target_has_no_delta"
                elif type(configured) is int and delta <= configured:
                    classification = "routine_confirmation"
                    rule = f"approved_threshold:{configured}"
                else:
                    classification = "strong_confirmation"
                    rule = (
                        f"approved_threshold_exceeded:{configured}"
                        if type(configured) is int
                        else "no_approved_threshold"
                    )
                classifications.append(classification)
                thresholds.append(
                    {
                        "target_key": change["target_key"],
                        "axis": axis,
                        "absolute_delta": delta,
                        "rule": rule,
                        "classification": classification,
                    }
                )
        if result != "reject" and classifications and all(
            item == "routine_confirmation" for item in classifications
        ):
            result = "routine_confirmation"
        target_label = ", ".join(target_keys)
        assessment = {
            "schema_name": ASSESSMENT_SCHEMA_NAME,
            "schema_version": ASSESSMENT_SCHEMA_VERSION,
            "policy_id": self.policy.policy_id,
            "policy_sha256": self.policy.raw_sha256,
            "proposal_sha256": proposal_hash,
            "workflow": workflow,
            "target_keys": list(target_keys),
            "target_class": target_class,
            "hardware_profile": hardware_profile,
            "governed_file_sha256": (
                copy.deepcopy(dict(governed_file_sha256))
                if governed_file_sha256 is not None
                else _config_hashes(before_documents)
            ),
            "changes": changes,
            "preconditions": copy.deepcopy(dict(preconditions or {})),
            "hard_checks": hard_checks,
            "threshold_results": thresholds,
            "result": result,
            "rejection_code": rejection_code,
            "confirmation_phrase_version": self.policy.confirmation_phrase_version,
            "required_confirmation_phrase": (
                self.policy.required_phrase(target_label, proposal_hash)
                if result == "strong_confirmation" else None
            ),
            "authorization_consequence": "revoked_pending_verification",
        }
        return parse_guard_assessment(assessment)


_ASSESSMENT_KEYS = {
    "schema_name", "schema_version", "policy_id", "policy_sha256",
    "proposal_sha256", "workflow", "target_keys", "target_class",
    "hardware_profile", "governed_file_sha256", "changes", "preconditions",
    "hard_checks", "threshold_results", "result", "rejection_code",
    "confirmation_phrase_version", "required_confirmation_phrase",
    "authorization_consequence",
}


def parse_guard_assessment(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ConfigurationSafetyError("Guard assessment must be an object.")
    _expect_exact_keys(payload, _ASSESSMENT_KEYS, "guard assessment")
    if payload.get("schema_name") != ASSESSMENT_SCHEMA_NAME or payload.get("schema_version") != ASSESSMENT_SCHEMA_VERSION:
        raise ConfigurationSafetyError("Unknown guard assessment schema.")
    for key in ("policy_id", "workflow", "target_class", "hardware_profile", "authorization_consequence"):
        _nonempty_text(payload.get(key), f"assessment {key}")
    for key in ("policy_sha256", "proposal_sha256"):
        value = payload.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ConfigurationSafetyError(f"Assessment {key} is invalid.")
    if payload.get("workflow") not in WORKFLOWS:
        raise ConfigurationSafetyError("Assessment workflow is unknown.")
    targets = payload.get("target_keys")
    if not isinstance(targets, list) or not targets or any(not isinstance(item, str) or not item for item in targets):
        raise ConfigurationSafetyError("Assessment targets are invalid.")
    for key in ("governed_file_sha256", "preconditions"):
        if not isinstance(payload.get(key), dict):
            raise ConfigurationSafetyError(f"Assessment {key} must be an object.")
    for key in ("changes", "hard_checks", "threshold_results"):
        if not isinstance(payload.get(key), list):
            raise ConfigurationSafetyError(f"Assessment {key} must be a list.")
    if payload.get("result") not in CONFIRMATION_RESULTS:
        raise ConfigurationSafetyError("Assessment result is unknown.")
    if type(payload.get("confirmation_phrase_version")) is not int:
        raise ConfigurationSafetyError("Assessment confirmation phrase version is invalid.")
    phrase = payload.get("required_confirmation_phrase")
    if payload["result"] == "strong_confirmation":
        _nonempty_text(phrase, "required confirmation phrase")
    elif phrase is not None:
        raise ConfigurationSafetyError("Only strong confirmation may require a phrase.")
    rejection = payload.get("rejection_code")
    if payload["result"] == "reject":
        _nonempty_text(rejection, "rejection code")
    elif rejection is not None:
        raise ConfigurationSafetyError("Only a rejected assessment may carry a rejection code.")
    if payload.get("authorization_consequence") != "revoked_pending_verification":
        raise ConfigurationSafetyError("Assessment authorization consequence is invalid.")
    return copy.deepcopy(payload)


__all__ = [
    "ASSESSMENT_SCHEMA_NAME",
    "ASSESSMENT_SCHEMA_VERSION",
    "ConfigurationChangeGuard",
    "ConfigurationChangePolicy",
    "ConfigurationSafetyError",
    "SafetyBounds",
    "load_configuration_change_policy",
    "parse_configuration_change_policy",
    "parse_guard_assessment",
    "parse_safety_bounds",
    "proposal_sha256",
]
