"""Typed, deterministic parameter matrices for composed host SIL journeys."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol

from tools.sil.ejection_response import PulseAwareSyntheticEjectionModelV1


REPO_ROOT = Path(__file__).resolve().parents[2]
MIXED_MODE_MATRIX_ID = "mixed_mode_calibration_v1"
CALIBRATION_REQUANTIZATION_MATRIX_ID = "calibration_requantization_v1"
MATRIX_PLAN_SCHEMA_NAME = "labcraft.virtual_workflow_matrix_plan"
MATRIX_SCHEMA_VERSION = 1
BASE_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "print_array_mixed_mode_24x2_v1.json"
)
BASE_SCENARIO_ID = "print_array_mixed_mode_24x2_v1"
REQUANTIZATION_BASE_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "print_array_multi_stock_24x2_v1.json"
)
REQUANTIZATION_BASE_SCENARIO_ID = "print_array_multi_stock_24x2_v1"
REQUANTIZATION_PROFILE_ID = "droplet_1300_9nl_v1"
REQUANTIZATION_STOCK_ID = "Virtual Requantization Stock_10.00_mM"
REQUANTIZATION_WELL_IDS = tuple(f"A{column}" for column in range(1, 25))


class MatrixValidationError(ValueError):
    """Raised when a matrix definition or requested case is invalid."""


class MatrixCaseContract(Protocol):
    """Minimum immutable case surface required by the generic registry."""

    case_id: str

    def normalized(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CalibrationProfile:
    profile_id: str
    droplet_pulse_width_us: int
    stream_pulse_width_us: int
    print_pressure_psi: float
    refuel_pulse_width_us: int
    refuel_pressure_psi: float
    trial_count: int
    trial_droplet_count: int

    def __post_init__(self) -> None:
        response = PulseAwareSyntheticEjectionModelV1()
        if not self.profile_id.strip():
            raise MatrixValidationError("profile ID must be non-empty")
        if not response.supports("droplet", self.droplet_pulse_width_us):
            raise MatrixValidationError("profile droplet pulse width is unsupported")
        if not response.supports("stream", self.stream_pulse_width_us):
            raise MatrixValidationError("profile stream pulse width is unsupported")
        if self.print_pressure_psi <= 0 or self.refuel_pressure_psi <= 0:
            raise MatrixValidationError("profile pressures must be positive")
        if self.refuel_pulse_width_us <= 0:
            raise MatrixValidationError("profile refuel pulse width must be positive")
        if self.trial_count <= 0 or self.trial_droplet_count <= 0:
            raise MatrixValidationError("profile trial counts must be positive")

    def normalized(self) -> dict[str, Any]:
        response = PulseAwareSyntheticEjectionModelV1()
        return {
            "profile_id": self.profile_id,
            "droplet": {
                "pulse_width_us": self.droplet_pulse_width_us,
                "volume_nL": response.predict_volume_nl(
                    "droplet", self.droplet_pulse_width_us
                ),
            },
            "stream": {
                "pulse_width_us": self.stream_pulse_width_us,
                "volume_nL": response.predict_volume_nl(
                    "stream", self.stream_pulse_width_us
                ),
                "refuel_pulse_width_us": self.refuel_pulse_width_us,
                "refuel_pressure_psi": self.refuel_pressure_psi,
            },
            "print_pressure_psi": self.print_pressure_psi,
            "manual_refuel": {
                "trial_count": self.trial_count,
                "trial_droplet_count": self.trial_droplet_count,
            },
        }


@dataclass(frozen=True)
class RefuelOutcome:
    stock_key: str
    status: str
    operator_judgment: str

    def __post_init__(self) -> None:
        valid = {
            ("passed", "stable"),
            ("failed", "level_rose"),
            ("failed", "level_fell"),
            ("unclear", "unclear"),
        }
        if self.stock_key not in {"A", "B"}:
            raise MatrixValidationError("refuel stock key must be A or B")
        if (self.status, self.operator_judgment) not in valid:
            raise MatrixValidationError("unsupported manual-refuel outcome")

    def normalized(self) -> dict[str, str]:
        return {
            "stock_key": self.stock_key,
            "status": self.status,
            "operator_judgment": self.operator_judgment,
        }


@dataclass(frozen=True)
class MatrixCase:
    case_id: str
    mode_a: str
    mode_b: str
    stock_order: tuple[str, str]
    profile_id: str
    refuel_outcomes: tuple[RefuelOutcome, ...]
    expected_terminal: str
    expected_completion_count: int

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise MatrixValidationError("case ID must be non-empty")
        if self.mode_a not in {"droplet", "stream"} or self.mode_b not in {
            "droplet",
            "stream",
        }:
            raise MatrixValidationError("case modes must be droplet or stream")
        if self.stock_order not in {("A", "B"), ("B", "A")}:
            raise MatrixValidationError("case stock order is unsupported")
        if self.profile_id not in PROFILES:
            raise MatrixValidationError("case calibration profile is unsupported")
        if self.expected_terminal not in {"completed", "manual_refuel_cancelled"}:
            raise MatrixValidationError("case terminal outcome is unsupported")
        modes = {"A": self.mode_a, "B": self.mode_b}
        outcomes = {item.stock_key: item for item in self.refuel_outcomes}
        stream_keys = {key for key, mode in modes.items() if mode == "stream"}
        if len(outcomes) != len(self.refuel_outcomes) or set(outcomes) != stream_keys:
            raise MatrixValidationError(
                "each stream stock requires exactly one manual-refuel outcome"
            )
        first_nonpass = next(
            (
                index
                for index, key in enumerate(self.stock_order)
                if key in outcomes and outcomes[key].status != "passed"
            ),
            None,
        )
        expected_count = 48 if first_nonpass is None else first_nonpass * 24
        expected_terminal = (
            "completed" if first_nonpass is None else "manual_refuel_cancelled"
        )
        if self.expected_completion_count != expected_count:
            raise MatrixValidationError("case expected completion count drifted")
        if self.expected_terminal != expected_terminal:
            raise MatrixValidationError("case expected terminal outcome drifted")

    @property
    def mode_family(self) -> str:
        if self.mode_a == self.mode_b:
            return f"{self.mode_a}_pair"
        return "mixed"

    def normalized(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "stock_modes": {"A": self.mode_a, "B": self.mode_b},
            "mode_family": self.mode_family,
            "stock_order": list(self.stock_order),
            "profile_id": self.profile_id,
            "refuel_outcomes": [item.normalized() for item in self.refuel_outcomes],
            "expected_terminal": self.expected_terminal,
            "expected_completion_count": self.expected_completion_count,
        }


PROFILES: Mapping[str, CalibrationProfile] = {
    "baseline": CalibrationProfile(
        "baseline", 1300, 2500, 1.2, 6000, 0.4, 2, 5
    ),
    "alternate": CalibrationProfile(
        "alternate", 1550, 4000, 1.6, 8000, 0.6, 3, 10
    ),
}


def _outcome(stock: str, status: str, judgment: str) -> RefuelOutcome:
    return RefuelOutcome(stock, status, judgment)


MATRIX_CASES: tuple[MatrixCase, ...] = (
    MatrixCase(
        "mixed_ab_baseline_pass", "droplet", "stream", ("A", "B"),
        "baseline", (_outcome("B", "passed", "stable"),), "completed", 48,
    ),
    MatrixCase(
        "mixed_ba_alternate_pass", "droplet", "stream", ("B", "A"),
        "alternate", (_outcome("B", "passed", "stable"),), "completed", 48,
    ),
    MatrixCase(
        "droplet_pair_ab_alternate", "droplet", "droplet", ("A", "B"),
        "alternate", (), "completed", 48,
    ),
    MatrixCase(
        "droplet_pair_ba_baseline", "droplet", "droplet", ("B", "A"),
        "baseline", (), "completed", 48,
    ),
    MatrixCase(
        "stream_pair_ab_baseline_pass", "stream", "stream", ("A", "B"),
        "baseline", (
            _outcome("A", "passed", "stable"),
            _outcome("B", "passed", "stable"),
        ), "completed", 48,
    ),
    MatrixCase(
        "stream_pair_ba_alternate_second_rise", "stream", "stream", ("B", "A"),
        "alternate", (
            _outcome("A", "failed", "level_rose"),
            _outcome("B", "passed", "stable"),
        ), "manual_refuel_cancelled", 24,
    ),
    MatrixCase(
        "mixed_ab_alternate_fell", "droplet", "stream", ("A", "B"),
        "alternate", (_outcome("B", "failed", "level_fell"),),
        "manual_refuel_cancelled", 24,
    ),
    MatrixCase(
        "mixed_ba_baseline_unclear", "droplet", "stream", ("B", "A"),
        "baseline", (_outcome("B", "unclear", "unclear"),),
        "manual_refuel_cancelled", 0,
    ),
)


def _fraction(value: int | float, label: str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MatrixValidationError(f"{label} must be numeric")
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise MatrixValidationError(f"{label} must be finite") from exc


@dataclass(frozen=True)
class RequantizationCase:
    """One independently frozen nearest-integer calibration boundary case."""

    case_id: str
    transition: str
    prepared_volume_nL: float
    calibrated_volume_nL: float
    design_printed_volume_nL: float
    expected_prepared_droplets: int
    expected_requantized_droplets: int
    margin_numerator: int
    margin_denominator: int
    profile_id: str = REQUANTIZATION_PROFILE_ID
    expected_terminal: str = "completed"
    expected_completion_count: int = 24

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or not self.case_id.strip():
            raise MatrixValidationError("requantization case ID must be non-empty")
        transitions = {
            "idempotent": 0,
            "volume_increase": -1,
            "volume_decrease": 1,
        }
        if self.transition not in transitions:
            raise MatrixValidationError("requantization transition is unsupported")
        if self.profile_id != REQUANTIZATION_PROFILE_ID:
            raise MatrixValidationError("requantization profile is unsupported")
        if self.expected_terminal != "completed":
            raise MatrixValidationError("requantization cases must complete")
        if self.expected_completion_count != len(REQUANTIZATION_WELL_IDS):
            raise MatrixValidationError("requantization completion count drifted")
        for label, count in (
            ("prepared count", self.expected_prepared_droplets),
            ("requantized count", self.expected_requantized_droplets),
        ):
            if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
                raise MatrixValidationError(f"requantization {label} must be positive")
        prepared = _fraction(self.prepared_volume_nL, "prepared volume")
        calibrated = _fraction(self.calibrated_volume_nL, "calibrated volume")
        printed = _fraction(self.design_printed_volume_nL, "printed volume")
        if min(prepared, calibrated, printed) <= 0:
            raise MatrixValidationError("requantization volumes must be positive")
        response = PulseAwareSyntheticEjectionModelV1()
        if calibrated != Fraction(str(response.predict_volume_nl("droplet", 1300))):
            raise MatrixValidationError(
                "requantization calibrated volume must match the frozen response"
            )
        expected_delta = transitions[self.transition]
        observed_delta = (
            self.expected_requantized_droplets
            - self.expected_prepared_droplets
        )
        if observed_delta != expected_delta:
            raise MatrixValidationError("requantization count direction drifted")
        if (
            self.transition == "idempotent" and prepared != calibrated
        ) or (
            self.transition == "volume_increase" and prepared >= calibrated
        ) or (
            self.transition == "volume_decrease" and prepared <= calibrated
        ):
            raise MatrixValidationError("requantization volume direction drifted")

        quotients = (
            (printed / prepared, self.expected_prepared_droplets),
            (printed / calibrated, self.expected_requantized_droplets),
        )
        margins: list[Fraction] = []
        for quotient, expected in quotients:
            distance = abs(quotient - expected)
            if distance >= Fraction(1, 2):
                raise MatrixValidationError(
                    "requantization expected count is outside its rounding interval"
                )
            margins.append(Fraction(1, 2) - distance)
        if (
            isinstance(self.margin_numerator, bool)
            or isinstance(self.margin_denominator, bool)
            or not isinstance(self.margin_numerator, int)
            or not isinstance(self.margin_denominator, int)
            or self.margin_numerator <= 0
            or self.margin_denominator <= 0
        ):
            raise MatrixValidationError("requantization boundary margin is invalid")
        margin = Fraction(self.margin_numerator, self.margin_denominator)
        if margin != min(margins):
            raise MatrixValidationError("requantization boundary margin drifted")
        if margin < Fraction(1, 3):
            raise MatrixValidationError("requantization boundary margin is too small")

    def normalized(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "transition": self.transition,
            "printing_mode": "droplet",
            "profile_id": self.profile_id,
            "prepared_volume_nL": self.prepared_volume_nL,
            "calibrated_volume_nL": self.calibrated_volume_nL,
            "design_printed_volume_nL": self.design_printed_volume_nL,
            "expected_prepared_droplets": self.expected_prepared_droplets,
            "expected_requantized_droplets": self.expected_requantized_droplets,
            "expected_count_delta": (
                self.expected_requantized_droplets
                - self.expected_prepared_droplets
            ),
            "rounding_boundary_margin": {
                "numerator": self.margin_numerator,
                "denominator": self.margin_denominator,
            },
            "expected_terminal": self.expected_terminal,
            "expected_completion_count": self.expected_completion_count,
        }


REQUANTIZATION_CASES: tuple[RequantizationCase, ...] = (
    RequantizationCase(
        "droplet_idempotent_10_to_10",
        "idempotent",
        9.0,
        9.0,
        90.0,
        10,
        10,
        1,
        2,
    ),
    RequantizationCase(
        "droplet_volume_increase_10_to_9",
        "volume_increase",
        8.0,
        9.0,
        80.0,
        10,
        9,
        7,
        18,
    ),
    RequantizationCase(
        "droplet_volume_decrease_10_to_11",
        "volume_decrease",
        10.0,
        9.0,
        100.0,
        10,
        11,
        7,
        18,
    ),
)


def _canonical_json(value: Mapping[str, Any] | list[Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_json(value: Mapping[str, Any] | list[Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MatrixDefinition:
    """One typed matrix catalog and its fixture/journey dispatch contract."""

    matrix_id: str
    base_scenario_id: str
    journey_family: str
    platform: str
    execution: str
    cases: tuple[MatrixCaseContract, ...]
    catalog_metadata: Mapping[str, Any]
    fixture_builder: Callable[[MatrixCaseContract], tuple[dict[str, Any], Path]]

    def __post_init__(self) -> None:
        for label, value in (
            ("matrix ID", self.matrix_id),
            ("base scenario ID", self.base_scenario_id),
            ("journey family", self.journey_family),
            ("platform", self.platform),
            ("execution policy", self.execution),
        ):
            if not isinstance(value, str) or not value.strip():
                raise MatrixValidationError(f"{label} must be non-empty")
        if not callable(self.fixture_builder):
            raise MatrixValidationError("matrix fixture builder must be callable")
        if not isinstance(self.catalog_metadata, Mapping):
            raise MatrixValidationError("matrix catalog metadata must be an object")
        reserved = {"matrix_id", "base_scenario_id", "cases"}
        overlap = reserved.intersection(self.catalog_metadata)
        if overlap:
            raise MatrixValidationError(
                "matrix catalog metadata uses reserved keys: "
                + ", ".join(sorted(overlap))
            )
        try:
            normalized_metadata = json.loads(
                _canonical_json(dict(self.catalog_metadata))
            )
        except (TypeError, ValueError) as exc:
            raise MatrixValidationError(
                "matrix catalog metadata must be deterministic JSON"
            ) from exc
        object.__setattr__(
            self, "catalog_metadata", MappingProxyType(normalized_metadata)
        )
        try:
            normalized_cases = tuple(self.cases)
        except TypeError as exc:
            raise MatrixValidationError("matrix cases must be an iterable") from exc
        object.__setattr__(self, "cases", normalized_cases)
        if not self.cases:
            raise MatrixValidationError("matrix definition must contain at least one case")
        case_ids: list[str] = []
        for case in self.cases:
            case_id = getattr(case, "case_id", None)
            normalizer = getattr(case, "normalized", None)
            if not isinstance(case_id, str) or not case_id.strip():
                raise MatrixValidationError("matrix case ID must be non-empty")
            if not callable(normalizer):
                raise MatrixValidationError(
                    f"matrix case {case_id!r} has no normalized contract"
                )
            normalized = normalizer()
            if not isinstance(normalized, Mapping):
                raise MatrixValidationError(
                    f"matrix case {case_id!r} normalized payload must be an object"
                )
            if normalized.get("case_id") != case_id:
                raise MatrixValidationError(
                    f"matrix case {case_id!r} normalized identity drifted"
                )
            try:
                canonical = _canonical_json(dict(normalized))
                repeated = normalizer()
                repeated_canonical = _canonical_json(dict(repeated))
            except (TypeError, ValueError) as exc:
                raise MatrixValidationError(
                    f"matrix case {case_id!r} must be deterministic JSON"
                ) from exc
            if canonical != repeated_canonical:
                raise MatrixValidationError(
                    f"matrix case {case_id!r} normalized payload is not deterministic"
                )
            case_ids.append(case_id)
        if len(set(case_ids)) != len(case_ids):
            raise MatrixValidationError("matrix definition contains duplicate case IDs")

    def case_ids(self) -> tuple[str, ...]:
        return tuple(case.case_id for case in self.cases)

    def get_case(self, case_id: str) -> MatrixCaseContract:
        matches = [case for case in self.cases if case.case_id == str(case_id)]
        if len(matches) != 1:
            raise MatrixValidationError(f"unsupported matrix case: {case_id!r}")
        return matches[0]

    def normalized_catalog(self) -> dict[str, Any]:
        return {
            "matrix_id": self.matrix_id,
            "base_scenario_id": self.base_scenario_id,
            **copy.deepcopy(dict(self.catalog_metadata)),
            "cases": [dict(case.normalized()) for case in self.cases],
        }

    def catalog_sha256(self) -> str:
        return _sha256_json(self.normalized_catalog())

    def build_case_fixture(
        self, case_id: str
    ) -> tuple[dict[str, Any], Path]:
        result = self.fixture_builder(self.get_case(case_id))
        if not isinstance(result, tuple) or len(result) != 2:
            raise MatrixValidationError("matrix fixture builder returned an invalid bundle")
        fixture, source = result
        if not isinstance(fixture, dict):
            raise MatrixValidationError("matrix fixture payload must be an object")
        try:
            source_path = Path(source)
        except TypeError as exc:
            raise MatrixValidationError(
                "matrix reference fixture path is invalid"
            ) from exc
        if not source_path.is_file():
            raise MatrixValidationError("matrix reference fixture does not exist")
        return fixture, source_path

    def catalog_entry(self) -> dict[str, Any]:
        return {
            "id": self.matrix_id,
            "case_ids": list(self.case_ids()),
            "case_count": len(self.cases),
            "catalog_sha256": self.catalog_sha256(),
            "platform": self.platform,
            "execution": self.execution,
        }


class MatrixRegistry:
    """Immutable, deterministic registry for typed matrix definitions."""

    def __init__(self, definitions: tuple[MatrixDefinition, ...]) -> None:
        definitions = tuple(definitions)
        if not definitions:
            raise MatrixValidationError("matrix registry must not be empty")
        if any(
            not isinstance(definition, MatrixDefinition)
            for definition in definitions
        ):
            raise MatrixValidationError(
                "matrix registry accepts only MatrixDefinition entries"
            )
        ids = [definition.matrix_id for definition in definitions]
        if len(set(ids)) != len(ids):
            raise MatrixValidationError("matrix registry contains duplicate matrix IDs")
        ordered = sorted(definitions, key=lambda definition: definition.matrix_id)
        self._definitions = MappingProxyType(
            {definition.matrix_id: definition for definition in ordered}
        )

    def registered_ids(self) -> tuple[str, ...]:
        return tuple(self._definitions)

    def get_definition(self, matrix_id: str) -> MatrixDefinition:
        try:
            return self._definitions[str(matrix_id)]
        except KeyError as exc:
            raise MatrixValidationError(f"unsupported matrix: {matrix_id!r}") from exc

    def matrix_case_ids(self, matrix_id: str) -> tuple[str, ...]:
        return self.get_definition(matrix_id).case_ids()

    def get_case(self, matrix_id: str, case_id: str) -> MatrixCaseContract:
        return self.get_definition(matrix_id).get_case(case_id)

    def normalized_catalog(self, matrix_id: str) -> dict[str, Any]:
        return self.get_definition(matrix_id).normalized_catalog()

    def catalog_sha256(self, matrix_id: str) -> str:
        return self.get_definition(matrix_id).catalog_sha256()

    def build_case_fixture(
        self, matrix_id: str, case_id: str
    ) -> tuple[dict[str, Any], Path]:
        return self.get_definition(matrix_id).build_case_fixture(case_id)

    def resolve_plan(
        self,
        matrix_id: str,
        *,
        case_id: str | None = None,
        seed: int = 1,
        timeout_seconds: float = 90.0,
        execution_authorized: bool = True,
    ) -> dict[str, Any]:
        definition = self.get_definition(matrix_id)
        selected = (
            (definition.get_case(case_id),)
            if case_id is not None
            else definition.cases
        )
        return {
            "schema_name": MATRIX_PLAN_SCHEMA_NAME,
            "schema_version": MATRIX_SCHEMA_VERSION,
            "matrix": {
                "id": definition.matrix_id,
                "catalog_sha256": definition.catalog_sha256(),
                "base_scenario_id": definition.base_scenario_id,
            },
            "platform": definition.platform,
            "seed": int(seed),
            "timeout_seconds": float(timeout_seconds),
            "case_count": len(selected),
            "cases": [
                self._plan_case(index, case)
                for index, case in enumerate(selected, 1)
            ],
            "execution_authorized": bool(execution_authorized),
        }

    @staticmethod
    def _plan_case(index: int, case: MatrixCaseContract) -> dict[str, Any]:
        normalized = dict(case.normalized())
        return {
            "order": index,
            "case": normalized,
            "case_sha256": _sha256_json(normalized),
        }

    def operator_catalog(self) -> dict[str, Any]:
        return {
            "schema_name": "labcraft.virtual_workflow_matrix_catalog",
            "schema_version": MATRIX_SCHEMA_VERSION,
            "matrices": [
                definition.catalog_entry()
                for definition in self._definitions.values()
            ],
        }


def _validate_catalog() -> None:
    ids = [case.case_id for case in MATRIX_CASES]
    if len(ids) != 8 or len(set(ids)) != len(ids):
        raise MatrixValidationError("matrix must contain eight uniquely named cases")
    required_mode_order = {
        (family, order)
        for family in {"mixed", "droplet_pair", "stream_pair"}
        for order in {("A", "B"), ("B", "A")}
    }
    required_mode_profile = {
        (family, profile)
        for family in {"mixed", "droplet_pair", "stream_pair"}
        for profile in PROFILES
    }
    required_order_profile = {
        (order, profile)
        for order in {("A", "B"), ("B", "A")}
        for profile in PROFILES
    }
    if {(case.mode_family, case.stock_order) for case in MATRIX_CASES} != required_mode_order:
        raise MatrixValidationError("matrix mode/order pairwise coverage drifted")
    if {(case.mode_family, case.profile_id) for case in MATRIX_CASES} != required_mode_profile:
        raise MatrixValidationError("matrix mode/profile pairwise coverage drifted")
    if {(case.stock_order, case.profile_id) for case in MATRIX_CASES} != required_order_profile:
        raise MatrixValidationError("matrix order/profile pairwise coverage drifted")
    judgments = {
        item.operator_judgment for case in MATRIX_CASES for item in case.refuel_outcomes
    }
    if judgments != {"stable", "level_rose", "level_fell", "unclear"}:
        raise MatrixValidationError("matrix manual-refuel judgment coverage drifted")


_validate_catalog()


def _build_mixed_mode_case_fixture(
    case: MatrixCaseContract,
) -> tuple[dict[str, Any], Path]:
    """Build one validated in-memory case from the single tracked reference fixture."""

    if not isinstance(case, MatrixCase):
        raise MatrixValidationError("mixed-mode matrix received an invalid case type")
    profile = PROFILES[case.profile_id]
    payload = json.loads(BASE_FIXTURE_PATH.read_text(encoding="utf-8"))
    fixture = copy.deepcopy(payload)
    modes = {"A": case.mode_a, "B": case.mode_b}
    outcomes = {item.stock_key: item for item in case.refuel_outcomes}
    response = PulseAwareSyntheticEjectionModelV1()
    stocks: dict[str, dict[str, Any]] = {}
    volumes: dict[str, float] = {}
    for key in ("A", "B"):
        mode = modes[key]
        pulse = (
            profile.droplet_pulse_width_us
            if mode == "droplet"
            else profile.stream_pulse_width_us
        )
        volume = response.predict_volume_nl(mode, pulse)
        volumes[key] = volume
        head = {
            "printer_head_id": f"virtual-head-matrix-{key.lower()}-v1",
            "initial_volume_uL": 1000.0,
            "print_pulse_width_us": pulse,
            "print_pressure_psi": profile.print_pressure_psi,
        }
        if mode == "stream":
            head.update(
                refuel_pulse_width_us=profile.refuel_pulse_width_us,
                refuel_pressure_psi=profile.refuel_pressure_psi,
            )
        stocks[key] = {
            "matrix_stock_key": key,
            "factor_name": f"Virtual Matrix {key}",
            "concentration": 23.0,
            "target_concentration": 0.0,
            "units": "mM",
            "printing_mode": mode,
            "prepared_droplet_volume_nL": volume,
            "droplet_volume_nL": volume,
            "printer_head": head,
        }
    total = sum(volumes.values())
    for key in stocks:
        stocks[key]["target_concentration"] = 23.0 * volumes[key] / total
    fixture["stocks"] = [stocks[key] for key in case.stock_order]
    fixture["fixture_id"] = f"{MIXED_MODE_MATRIX_ID}__{case.case_id}"
    fixture["lifecycle"] = {
        "kind": "parameterized_calibration_matrix_case",
        "matrix_id": MIXED_MODE_MATRIX_ID,
        "catalog_sha256": catalog_sha256(MIXED_MODE_MATRIX_ID),
        "case": case.normalized(),
        "case_sha256": _sha256_json(case.normalized()),
        "profile": profile.normalized(),
        "manual_refuel_checks": {
            key: {
                **outcomes[key].normalized(),
                "trial_count": profile.trial_count,
                "trial_droplet_count": profile.trial_droplet_count,
            }
            for key in outcomes
        },
    }
    if len(fixture["stocks"]) != 2 or fixture["workload"]["completion_count"] != 48:
        raise MatrixValidationError("built matrix fixture cardinality drifted")
    return fixture, BASE_FIXTURE_PATH


def _requantization_profile() -> dict[str, Any]:
    return {
        "profile_id": REQUANTIZATION_PROFILE_ID,
        "droplet": {
            "pulse_width_us": 1300,
            "volume_nL": 9.0,
        },
        "print_pressure_psi": 1.2,
    }


def _build_requantization_case_fixture(
    case: MatrixCaseContract,
) -> tuple[dict[str, Any], Path]:
    """Build a one-stock boundary case from the tracked multi-stock fixture."""

    if not isinstance(case, RequantizationCase):
        raise MatrixValidationError(
            "requantization matrix received an invalid case type"
        )
    payload = json.loads(
        REQUANTIZATION_BASE_FIXTURE_PATH.read_text(encoding="utf-8")
    )
    fixture = copy.deepcopy(payload)
    stock = {
        "factor_name": "Virtual Requantization Stock",
        "concentration": 10.0,
        "target_concentration": 10.0,
        "units": "mM",
        "printing_mode": "droplet",
        "prepared_droplet_volume_nL": case.prepared_volume_nL,
        "droplet_volume_nL": case.calibrated_volume_nL,
        "printer_head": {
            "printer_head_id": "virtual-head-requantization-v1",
            "initial_volume_uL": 1000.0,
            "print_pulse_width_us": 1300,
            "print_pressure_psi": 1.2,
        },
    }
    fixture["fixture_id"] = (
        f"{CALIBRATION_REQUANTIZATION_MATRIX_ID}__{case.case_id}"
    )
    fixture["stocks"] = [stock]
    fixture["workload"] = {
        "target_dispenses_per_stock_per_well": (
            case.expected_requantized_droplets
        ),
        "well_count": len(REQUANTIZATION_WELL_IDS),
        "stock_count": 1,
        "array_passes": 1,
        "completion_count": case.expected_completion_count,
    }
    fixture["lifecycle"] = {
        "kind": "parameterized_calibration_matrix_case",
        "matrix_id": CALIBRATION_REQUANTIZATION_MATRIX_ID,
        "catalog_sha256": catalog_sha256(
            CALIBRATION_REQUANTIZATION_MATRIX_ID
        ),
        "case": case.normalized(),
        "case_sha256": _sha256_json(case.normalized()),
        "profile": _requantization_profile(),
        "manual_refuel_checks": {},
        "design": {
            "printed_volume_nL": case.design_printed_volume_nL,
            "final_volume_nL": case.design_printed_volume_nL,
        },
        "dispense_count_oracle": {
            "schema_version": 1,
            "source": "calibration_requantization_v1_catalog",
            "stock_id": REQUANTIZATION_STOCK_ID,
            "well_ids": list(REQUANTIZATION_WELL_IDS),
            "prepared_droplets_per_well": (
                case.expected_prepared_droplets
            ),
            "requantized_droplets_per_well": (
                case.expected_requantized_droplets
            ),
            "expected_count_delta": (
                case.expected_requantized_droplets
                - case.expected_prepared_droplets
            ),
            "transition": case.transition,
            "rounding_boundary_margin": {
                "numerator": case.margin_numerator,
                "denominator": case.margin_denominator,
            },
        },
    }
    built_stock_id = (
        f"{stock['factor_name']}_{float(stock['concentration']):.2f}_"
        f"{stock['units']}"
    )
    if (
        built_stock_id != REQUANTIZATION_STOCK_ID
        or len(fixture["stocks"]) != 1
        or fixture["workload"]["completion_count"] != 24
    ):
        raise MatrixValidationError("built requantization fixture cardinality drifted")
    return fixture, REQUANTIZATION_BASE_FIXTURE_PATH


MIXED_MODE_DEFINITION = MatrixDefinition(
    matrix_id=MIXED_MODE_MATRIX_ID,
    base_scenario_id=BASE_SCENARIO_ID,
    journey_family="mixed_mode_calibration",
    platform="windows_sil",
    execution="manual_on_demand",
    cases=MATRIX_CASES,
    catalog_metadata={
        "profiles": [PROFILES[key].normalized() for key in sorted(PROFILES)]
    },
    fixture_builder=_build_mixed_mode_case_fixture,
)

CALIBRATION_REQUANTIZATION_DEFINITION = MatrixDefinition(
    matrix_id=CALIBRATION_REQUANTIZATION_MATRIX_ID,
    base_scenario_id=REQUANTIZATION_BASE_SCENARIO_ID,
    journey_family="calibration_requantization",
    platform="windows_sil",
    execution="manual_on_demand",
    cases=REQUANTIZATION_CASES,
    catalog_metadata={
        "profile": _requantization_profile(),
        "stock_id": REQUANTIZATION_STOCK_ID,
        "well_ids": list(REQUANTIZATION_WELL_IDS),
        "oracle": {
            "method": "exact_rational_nearest_integer",
            "half_ties": "rejected",
            "minimum_boundary_margin": {
                "numerator": 1,
                "denominator": 3,
            },
        },
    },
    fixture_builder=_build_requantization_case_fixture,
)

MATRIX_REGISTRY = MatrixRegistry(
    (MIXED_MODE_DEFINITION, CALIBRATION_REQUANTIZATION_DEFINITION)
)


def registered_matrix_ids() -> tuple[str, ...]:
    return MATRIX_REGISTRY.registered_ids()


def get_matrix_definition(matrix_id: str) -> MatrixDefinition:
    return MATRIX_REGISTRY.get_definition(matrix_id)


def matrix_case_ids(matrix_id: str = MIXED_MODE_MATRIX_ID) -> tuple[str, ...]:
    return MATRIX_REGISTRY.matrix_case_ids(matrix_id)


def get_matrix_case(matrix_id: str, case_id: str) -> MatrixCaseContract:
    return MATRIX_REGISTRY.get_case(matrix_id, case_id)


def normalized_catalog(
    matrix_id: str = MIXED_MODE_MATRIX_ID,
) -> dict[str, Any]:
    return MATRIX_REGISTRY.normalized_catalog(matrix_id)


def catalog_sha256(matrix_id: str = MIXED_MODE_MATRIX_ID) -> str:
    return MATRIX_REGISTRY.catalog_sha256(matrix_id)


def resolve_matrix_plan(
    matrix_id: str,
    *,
    case_id: str | None = None,
    seed: int = 1,
    timeout_seconds: float = 90.0,
    execution_authorized: bool = True,
) -> dict[str, Any]:
    return MATRIX_REGISTRY.resolve_plan(
        matrix_id,
        case_id=case_id,
        seed=seed,
        timeout_seconds=timeout_seconds,
        execution_authorized=execution_authorized,
    )


def build_case_fixture(
    matrix_id: str, case_id: str
) -> tuple[dict[str, Any], Path]:
    return MATRIX_REGISTRY.build_case_fixture(matrix_id, case_id)


def matrix_catalog() -> dict[str, Any]:
    return MATRIX_REGISTRY.operator_catalog()


__all__ = [
    "BASE_FIXTURE_PATH",
    "BASE_SCENARIO_ID",
    "CALIBRATION_REQUANTIZATION_DEFINITION",
    "CALIBRATION_REQUANTIZATION_MATRIX_ID",
    "MATRIX_CASES",
    "MATRIX_PLAN_SCHEMA_NAME",
    "MATRIX_REGISTRY",
    "MATRIX_SCHEMA_VERSION",
    "MIXED_MODE_MATRIX_ID",
    "MIXED_MODE_DEFINITION",
    "MatrixCase",
    "MatrixCaseContract",
    "MatrixDefinition",
    "MatrixRegistry",
    "MatrixValidationError",
    "REQUANTIZATION_BASE_FIXTURE_PATH",
    "REQUANTIZATION_BASE_SCENARIO_ID",
    "REQUANTIZATION_CASES",
    "REQUANTIZATION_PROFILE_ID",
    "REQUANTIZATION_STOCK_ID",
    "REQUANTIZATION_WELL_IDS",
    "RequantizationCase",
    "build_case_fixture",
    "catalog_sha256",
    "get_matrix_definition",
    "get_matrix_case",
    "matrix_case_ids",
    "matrix_catalog",
    "normalized_catalog",
    "registered_matrix_ids",
    "resolve_matrix_plan",
]
