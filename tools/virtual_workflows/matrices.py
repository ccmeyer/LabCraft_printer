"""Typed, deterministic parameter matrices for composed host SIL journeys."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from tools.sil.ejection_response import PulseAwareSyntheticEjectionModelV1


REPO_ROOT = Path(__file__).resolve().parents[2]
MIXED_MODE_MATRIX_ID = "mixed_mode_calibration_v1"
MATRIX_PLAN_SCHEMA_NAME = "labcraft.virtual_workflow_matrix_plan"
MATRIX_SCHEMA_VERSION = 1
BASE_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "print_array_mixed_mode_24x2_v1.json"
)
BASE_SCENARIO_ID = "print_array_mixed_mode_24x2_v1"


class MatrixValidationError(ValueError):
    """Raised when a matrix definition or requested case is invalid."""


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


def _canonical_json(value: Mapping[str, Any] | list[Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_json(value: Mapping[str, Any] | list[Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


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


def matrix_case_ids(matrix_id: str = MIXED_MODE_MATRIX_ID) -> tuple[str, ...]:
    if matrix_id != MIXED_MODE_MATRIX_ID:
        raise MatrixValidationError(f"unsupported matrix: {matrix_id!r}")
    return tuple(case.case_id for case in MATRIX_CASES)


def get_matrix_case(matrix_id: str, case_id: str) -> MatrixCase:
    if matrix_id != MIXED_MODE_MATRIX_ID:
        raise MatrixValidationError(f"unsupported matrix: {matrix_id!r}")
    matches = [case for case in MATRIX_CASES if case.case_id == str(case_id)]
    if len(matches) != 1:
        raise MatrixValidationError(f"unsupported matrix case: {case_id!r}")
    return matches[0]


def normalized_catalog() -> dict[str, Any]:
    return {
        "matrix_id": MIXED_MODE_MATRIX_ID,
        "base_scenario_id": BASE_SCENARIO_ID,
        "profiles": [PROFILES[key].normalized() for key in sorted(PROFILES)],
        "cases": [case.normalized() for case in MATRIX_CASES],
    }


def catalog_sha256() -> str:
    return _sha256_json(normalized_catalog())


def resolve_matrix_plan(
    matrix_id: str,
    *,
    case_id: str | None = None,
    seed: int = 1,
    timeout_seconds: float = 90.0,
    execution_authorized: bool = True,
) -> dict[str, Any]:
    if matrix_id != MIXED_MODE_MATRIX_ID:
        raise MatrixValidationError(f"unsupported matrix: {matrix_id!r}")
    selected = (
        (get_matrix_case(matrix_id, case_id),)
        if case_id is not None
        else MATRIX_CASES
    )
    return {
        "schema_name": MATRIX_PLAN_SCHEMA_NAME,
        "schema_version": MATRIX_SCHEMA_VERSION,
        "matrix": {
            "id": matrix_id,
            "catalog_sha256": catalog_sha256(),
            "base_scenario_id": BASE_SCENARIO_ID,
        },
        "platform": "windows_sil",
        "seed": int(seed),
        "timeout_seconds": float(timeout_seconds),
        "case_count": len(selected),
        "cases": [
            {
                "order": index,
                "case": case.normalized(),
                "case_sha256": _sha256_json(case.normalized()),
            }
            for index, case in enumerate(selected, 1)
        ],
        "execution_authorized": bool(execution_authorized),
    }


def build_case_fixture(matrix_id: str, case_id: str) -> tuple[dict[str, Any], Path]:
    """Build one validated in-memory case from the single tracked reference fixture."""

    case = get_matrix_case(matrix_id, case_id)
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
        "matrix_id": matrix_id,
        "catalog_sha256": catalog_sha256(),
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


def matrix_catalog() -> dict[str, Any]:
    return {
        "schema_name": "labcraft.virtual_workflow_matrix_catalog",
        "schema_version": MATRIX_SCHEMA_VERSION,
        "matrices": [
            {
                "id": MIXED_MODE_MATRIX_ID,
                "case_ids": list(matrix_case_ids()),
                "case_count": len(MATRIX_CASES),
                "catalog_sha256": catalog_sha256(),
                "platform": "windows_sil",
                "execution": "manual_on_demand",
            }
        ],
    }


__all__ = [
    "BASE_FIXTURE_PATH",
    "BASE_SCENARIO_ID",
    "MATRIX_CASES",
    "MATRIX_PLAN_SCHEMA_NAME",
    "MATRIX_SCHEMA_VERSION",
    "MIXED_MODE_MATRIX_ID",
    "MatrixCase",
    "MatrixValidationError",
    "build_case_fixture",
    "catalog_sha256",
    "get_matrix_case",
    "matrix_case_ids",
    "matrix_catalog",
    "normalized_catalog",
    "resolve_matrix_plan",
]
