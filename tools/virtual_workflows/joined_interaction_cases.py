"""Literal truth for the Milestone 11 joined randomized lifecycle.

The contract intentionally depends only on other SIL contract modules.  It
never imports the application Model, View, assignment optimizer, calibration
implementation, or execution planner, so expected values cannot be computed
from the behavior they will later verify.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.virtual_workflows.experiment_design_cases import (
    EXPERIMENT_DESIGN_MATRIX_ID,
    REFERENCE_FIXTURE_PATH,
    REFERENCE_FIXTURE_SHA256,
    get_experiment_design_case,
    planned_catalog_sha256,
)
from tools.virtual_workflows.matrices import (
    CALIBRATION_REQUANTIZATION_MATRIX_ID,
    MIXED_MODE_MATRIX_ID,
    catalog_sha256,
)


JOINED_INTERACTION_CASE_ID = "randomized_calibration_reload_execution_v1"
SOURCE_DESIGN_CASE_ID = "multi_reagent_seed_4321"
JOINED_INTERACTION_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / f"{JOINED_INTERACTION_CASE_ID}.json"
)

SOURCE_CASE_SHA256 = (
    "5d2e7dff0ea9c2e0bcd1e3b218b39280aca57b745834024226fece850f110f51"
)
SOURCE_MATRIX_CATALOG_SHA256 = (
    "acbd4d82f8c7ea6dd842c4ad88bd472c4b50f3a73822dc8c34cfded0dec6f59f"
)
SOURCE_PLANNED_CATALOG_SHA256 = (
    "15ec261cf19bec2f2758d76f8c8102d0d246eef02ff165a4bdb104b1a9e8dfcd"
)
SOURCE_REACTION_MULTISET_SHA256 = (
    "b189fe1ed4b975953600c7d299fd320be366eda827ceb39f28cf3a3bbc22b696"
)
SOURCE_ASSIGNMENT_SHA256 = (
    "e264b345bddb83c2aeb12bf6421d83a81d21c8b9f31ff6698780164a1bee82ef"
)
REQUANTIZATION_CATALOG_SHA256 = (
    "d826a9e54c2e6190acfd5afdb0b2475de2be62557647aafa378890ca826c55af"
)
MIXED_MODE_CATALOG_SHA256 = (
    "d2439c2e47cb9825ad5a5024e014fd4429ff6b28dcafa54809c92fa674cff884"
)

DESIGN_A_STOCK_ID = "Design A_10.00_x"
DESIGN_B_STOCK_ID = "Design B_10.00_x"
WATER_STOCK_ID = "Water_1.00_--"
EXPECTED_STOCK_IDS = (DESIGN_A_STOCK_ID, DESIGN_B_STOCK_ID, WATER_STOCK_ID)
EXPECTED_WELL_IDS = tuple(f"A{index}" for index in range(1, 9))


class JoinedInteractionCaseError(ValueError):
    """Raised when joined lifecycle truth is malformed or drifts."""


def _canonical_json(value: Mapping[str, Any] | Sequence[Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_json(value: Mapping[str, Any] | Sequence[Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _identity(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise JoinedInteractionCaseError(f"{label} must be non-empty")
    return text


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise JoinedInteractionCaseError(f"{label} must be a positive integer")
    return value


def _sha(value: Any, label: str) -> str:
    text = _identity(value, label)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise JoinedInteractionCaseError(f"{label} must be a lowercase SHA-256")
    return text


def _keys(payload: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(payload)
    if actual != expected:
        raise JoinedInteractionCaseError(
            f"{label} keys differ: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


@dataclass(frozen=True)
class JoinedSourceIdentity:
    matrix_id: str
    case_id: str
    case_sha256: str
    catalog_sha256: str
    planned_catalog_sha256: str
    reaction_multiset_sha256: str
    assignment_sha256: str
    editor_fixture_sha256: str
    requantization_catalog_sha256: str
    mixed_mode_catalog_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "matrix_id", _identity(self.matrix_id, "source matrix"))
        object.__setattr__(self, "case_id", _identity(self.case_id, "source case"))
        for name in (
            "case_sha256", "catalog_sha256", "planned_catalog_sha256",
            "reaction_multiset_sha256", "assignment_sha256",
            "editor_fixture_sha256", "requantization_catalog_sha256",
            "mixed_mode_catalog_sha256",
        ):
            object.__setattr__(self, name, _sha(getattr(self, name), name))

    def normalized(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class JoinedEditorInput:
    experiment_name: str
    plate_name: str
    replicates: int
    selected_well_ids: tuple[str, ...]
    printed_volume_nL: str
    final_volume_nL: str
    randomize_assignments: bool
    random_seed: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "experiment_name", _identity(self.experiment_name, "experiment"))
        object.__setattr__(self, "plate_name", _identity(self.plate_name, "plate"))
        _positive_int(self.replicates, "replicates")
        wells = tuple(_identity(value, "selected well") for value in self.selected_well_ids)
        if len(wells) != len(set(wells)) or not wells:
            raise JoinedInteractionCaseError("selected wells must be unique and non-empty")
        object.__setattr__(self, "selected_well_ids", wells)
        for name in ("printed_volume_nL", "final_volume_nL"):
            object.__setattr__(self, name, _identity(getattr(self, name), name))
        if self.randomize_assignments is not True:
            raise JoinedInteractionCaseError("joined design must randomize assignments")
        _positive_int(self.random_seed, "random seed")

    def normalized(self) -> dict[str, Any]:
        return {
            "experiment_name": self.experiment_name,
            "plate_name": self.plate_name,
            "replicates": self.replicates,
            "selected_well_ids": list(self.selected_well_ids),
            "printed_volume_nL": self.printed_volume_nL,
            "final_volume_nL": self.final_volume_nL,
            "randomize_assignments": self.randomize_assignments,
            "random_seed": self.random_seed,
        }


@dataclass(frozen=True)
class JoinedStock:
    stock_id: str
    reagent_name: str
    role: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_id", _identity(self.stock_id, "stock ID"))
        object.__setattr__(self, "reagent_name", _identity(self.reagent_name, "reagent"))
        if self.role not in {"non_fill", "fill"}:
            raise JoinedInteractionCaseError("stock role is unsupported")

    def normalized(self) -> dict[str, str]:
        return {"stock_id": self.stock_id, "reagent_name": self.reagent_name, "role": self.role}


@dataclass(frozen=True)
class JoinedAssignment:
    well_id: str
    reaction_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "well_id", _identity(self.well_id, "assignment well"))
        object.__setattr__(self, "reaction_id", _identity(self.reaction_id, "reaction ID"))

    def normalized(self) -> dict[str, str]:
        return {"well_id": self.well_id, "reaction_id": self.reaction_id}


@dataclass(frozen=True)
class JoinedCalibration:
    order: int
    stock_id: str
    reagent_name: str
    printer_head_id: str
    print_pulse_width_us: int
    droplet_volume_nL: str
    input_revision: int
    output_revision: int

    def __post_init__(self) -> None:
        for name in ("order", "print_pulse_width_us", "input_revision", "output_revision"):
            _positive_int(getattr(self, name), name)
        for name in ("stock_id", "reagent_name", "printer_head_id", "droplet_volume_nL"):
            object.__setattr__(self, name, _identity(getattr(self, name), name))
        if self.output_revision != self.input_revision + 1:
            raise JoinedInteractionCaseError("calibration must advance exactly one revision")

    def normalized(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class JoinedCheckpoint:
    checkpoint_id: str
    session: int
    phase: str
    plan_revision: int
    progress_reference_revision: int
    resume_reference_revision: int | None
    eligibility: str

    def __post_init__(self) -> None:
        for name in ("checkpoint_id", "phase", "eligibility"):
            object.__setattr__(self, name, _identity(getattr(self, name), name))
        for name in ("session", "plan_revision", "progress_reference_revision"):
            _positive_int(getattr(self, name), name)
        if self.resume_reference_revision is not None:
            _positive_int(self.resume_reference_revision, "resume reference revision")
        if self.progress_reference_revision != self.plan_revision:
            raise JoinedInteractionCaseError("progress reference must join the plan revision")
        if self.resume_reference_revision not in {None, self.plan_revision}:
            raise JoinedInteractionCaseError("resume reference must be absent or join the plan revision")

    def normalized(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, order=True)
class JoinedStockWellCount:
    stock_id: str
    well_id: str
    target_droplets: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_id", _identity(self.stock_id, "count stock"))
        object.__setattr__(self, "well_id", _identity(self.well_id, "count well"))
        _positive_int(self.target_droplets, "target droplets")

    def normalized(self) -> dict[str, Any]:
        return {"stock_id": self.stock_id, "well_id": self.well_id, "target_droplets": self.target_droplets}


@dataclass(frozen=True)
class JoinedCountOracle:
    checkpoint_id: str
    rows: tuple[JoinedStockWellCount, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "checkpoint_id", _identity(self.checkpoint_id, "count checkpoint"))
        keys = [(row.stock_id, row.well_id) for row in self.rows]
        if len(keys) != len(set(keys)):
            raise JoinedInteractionCaseError("count rows must have unique (stock_id, well_id) keys")

    def normalized(self) -> dict[str, Any]:
        return {"checkpoint_id": self.checkpoint_id, "rows": [row.normalized() for row in self.rows]}

    def keyed(self) -> dict[tuple[str, str], int]:
        return {(row.stock_id, row.well_id): row.target_droplets for row in self.rows}


@dataclass(frozen=True)
class JoinedExecutionPass:
    order: int
    stock_id: str
    expected_intents: int
    expected_droplets: int

    def __post_init__(self) -> None:
        for name in ("order", "expected_intents", "expected_droplets"):
            _positive_int(getattr(self, name), name)
        object.__setattr__(self, "stock_id", _identity(self.stock_id, "pass stock"))

    def normalized(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class JoinedQualification:
    cli_seed: int
    action_cap: int
    offscreen_timeout_seconds: int
    visible_timeout_seconds: int
    visible_speed: int
    required_screenshots: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("cli_seed", "action_cap", "offscreen_timeout_seconds", "visible_timeout_seconds", "visible_speed"):
            _positive_int(getattr(self, name), name)
        screenshots = tuple(_identity(value, "screenshot") for value in self.required_screenshots)
        if len(screenshots) != len(set(screenshots)):
            raise JoinedInteractionCaseError("required screenshots must be unique")
        object.__setattr__(self, "required_screenshots", screenshots)

    def normalized(self) -> dict[str, Any]:
        return {
            "cli_seed": self.cli_seed,
            "action_cap": self.action_cap,
            "offscreen_timeout_seconds": self.offscreen_timeout_seconds,
            "visible_timeout_seconds": self.visible_timeout_seconds,
            "visible_speed": self.visible_speed,
            "required_screenshots": list(self.required_screenshots),
        }


@dataclass(frozen=True)
class JoinedTerminalOracle:
    expected_intents: int
    expected_droplets: int
    expected_completed_wells: int
    expected_completed_stocks: int
    application_sessions: int

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            _positive_int(getattr(self, name), name)

    def normalized(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class JoinedInteractionCase:
    case_id: str
    schema_version: int
    source: JoinedSourceIdentity
    editor: JoinedEditorInput
    stocks: tuple[JoinedStock, ...]
    assignments: tuple[JoinedAssignment, ...]
    calibrations: tuple[JoinedCalibration, ...]
    checkpoints: tuple[JoinedCheckpoint, ...]
    count_oracles: tuple[JoinedCountOracle, ...]
    execution_passes: tuple[JoinedExecutionPass, ...]
    qualification: JoinedQualification
    terminal: JoinedTerminalOracle

    def normalized(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "schema_version": self.schema_version,
            "source": self.source.normalized(),
            "editor": self.editor.normalized(),
            "stocks": [value.normalized() for value in self.stocks],
            "assignments": [value.normalized() for value in self.assignments],
            "calibrations": [value.normalized() for value in self.calibrations],
            "checkpoints": [value.normalized() for value in self.checkpoints],
            "count_oracles": {value.checkpoint_id: [[row.stock_id, row.well_id, row.target_droplets] for row in value.rows] for value in self.count_oracles},
            "execution_passes": [value.normalized() for value in self.execution_passes],
            "qualification": self.qualification.normalized(),
            "terminal": self.terminal.normalized(),
        }

    def sha256(self) -> str:
        return _sha256_json(self.normalized())

    def count_oracle_sha256(self) -> str:
        return _sha256_json([value.normalized() for value in self.count_oracles])

    def oracle(self, checkpoint_id: str) -> JoinedCountOracle:
        matches = [value for value in self.count_oracles if value.checkpoint_id == checkpoint_id]
        if len(matches) != 1:
            raise JoinedInteractionCaseError(f"unknown or duplicate count checkpoint: {checkpoint_id}")
        return matches[0]


def validate_joined_interaction_case(case: JoinedInteractionCase) -> None:
    """Validate the complete literal joined contract without production code."""

    if case.case_id != JOINED_INTERACTION_CASE_ID or case.schema_version != 1:
        raise JoinedInteractionCaseError("joined case identity or schema version drifted")
    expected_source = (
        EXPERIMENT_DESIGN_MATRIX_ID, SOURCE_DESIGN_CASE_ID, SOURCE_CASE_SHA256,
        SOURCE_MATRIX_CATALOG_SHA256, SOURCE_PLANNED_CATALOG_SHA256,
        SOURCE_REACTION_MULTISET_SHA256, SOURCE_ASSIGNMENT_SHA256,
        REFERENCE_FIXTURE_SHA256, REQUANTIZATION_CATALOG_SHA256,
        MIXED_MODE_CATALOG_SHA256,
    )
    if tuple(case.source.normalized().values()) != expected_source:
        raise JoinedInteractionCaseError("source identity/hash compatibility contract drifted")
    if case.editor.selected_well_ids != EXPECTED_WELL_IDS or case.editor.random_seed != 4321:
        raise JoinedInteractionCaseError("editor well/seed contract drifted")

    stock_ids = tuple(stock.stock_id for stock in case.stocks)
    if stock_ids != EXPECTED_STOCK_IDS or len(set(stock_ids)) != 3:
        raise JoinedInteractionCaseError("stock identities/order drifted")
    expected_assignments = tuple(zip(EXPECTED_WELL_IDS, ("R8", "R6", "R3", "R2", "R7", "R4", "R1", "R5")))
    if tuple((row.well_id, row.reaction_id) for row in case.assignments) != expected_assignments:
        raise JoinedInteractionCaseError("literal reaction-to-well mapping drifted")

    calibration_identity = tuple(
        (row.order, row.stock_id, row.reagent_name, row.printer_head_id,
         row.print_pulse_width_us, row.droplet_volume_nL,
         row.input_revision, row.output_revision)
        for row in case.calibrations
    )
    if calibration_identity != (
        (1, DESIGN_A_STOCK_ID, "Design A", "virtual-head-m11-design-a-v1", 1800, "18", 2, 3),
        (2, WATER_STOCK_ID, "Water", "virtual-head-m11-water-v1", 1300, "9", 3, 4),
        (3, DESIGN_B_STOCK_ID, "Design B", "virtual-head-m11-design-b-v1", 1400, "10.8", 4, 5),
    ):
        raise JoinedInteractionCaseError("calibration/head/revision joins drifted")
    if sum(row.reagent_name == "Design A" for row in case.calibrations) != 1:
        raise JoinedInteractionCaseError("calibrated reagent must map to one execution stock")

    checkpoint_identity = tuple(
        (row.checkpoint_id, row.session, row.phase, row.plan_revision,
         row.progress_reference_revision, row.resume_reference_revision, row.eligibility)
        for row in case.checkpoints
    )
    if checkpoint_identity != (
        ("prepared", 1, "prepared", 1, 1, None, "calibration_required"),
        ("locked_for_design_a", 1, "calibration_locked", 2, 2, None, "calibration_required"),
        ("calibrated_zero_progress", 1, "calibrated", 3, 3, None, "ready_to_start"),
        ("fresh_loaded", 2, "calibrated", 3, 3, None, "ready_to_start"),
        ("fresh_activated", 2, "calibrated", 3, 3, 3, "active"),
        ("water_calibrated", 2, "calibrated", 4, 4, 4, "active"),
        ("all_stocks_calibrated", 2, "calibrated", 5, 5, 5, "active"),
        ("completed", 2, "completed", 6, 6, 6, "analysis_only"),
        ("terminal_reloaded", 3, "completed", 6, 6, 6, "analysis_only"),
    ):
        raise JoinedInteractionCaseError("session/revision/progress-reference chain drifted")

    if tuple(value.checkpoint_id for value in case.count_oracles) != (
        "prepared", "calibrated_zero_progress", "all_stocks_calibrated"
    ):
        raise JoinedInteractionCaseError("count checkpoint identities/order drifted")
    expected_keys = {(stock_id, well_id) for stock_id in EXPECTED_STOCK_IDS for well_id in EXPECTED_WELL_IDS}
    for oracle in case.count_oracles:
        if set(oracle.keyed()) != expected_keys or len(oracle.rows) != 24:
            raise JoinedInteractionCaseError("count oracle must cover 24 exact stock/well keys")
    prepared = case.oracle("prepared").keyed()
    calibrated = case.oracle("calibrated_zero_progress").keyed()
    final = case.oracle("all_stocks_calibrated").keyed()
    expected_b = {"A1": 3, "A2": 3, "A3": 1, "A4": 3, "A5": 1, "A6": 3, "A7": 1, "A8": 1}
    for well_id, count in expected_b.items():
        if not (prepared[(DESIGN_B_STOCK_ID, well_id)] == calibrated[(DESIGN_B_STOCK_ID, well_id)] == final[(DESIGN_B_STOCK_ID, well_id)] == count):
            raise JoinedInteractionCaseError("unchanged Design B stock/count oracle drifted")

    pass_identity = tuple((row.order, row.stock_id, row.expected_intents, row.expected_droplets) for row in case.execution_passes)
    if pass_identity != ((1, DESIGN_A_STOCK_ID, 8, 8), (2, DESIGN_B_STOCK_ID, 8, 16), (3, WATER_STOCK_ID, 8, 56)):
        raise JoinedInteractionCaseError("explicit stock-keyed execution pass contract drifted")
    if case.qualification.cli_seed != 1 or case.qualification.action_cap != 96:
        raise JoinedInteractionCaseError("qualification seed/action cap drifted")
    if (case.qualification.offscreen_timeout_seconds, case.qualification.visible_timeout_seconds, case.qualification.visible_speed) != (180, 240, 20):
        raise JoinedInteractionCaseError("qualification timeout/speed policy drifted")
    if case.terminal != JoinedTerminalOracle(24, 80, 24, 3, 3):
        raise JoinedInteractionCaseError("terminal identity/count oracle drifted")
    if sum(row.expected_intents for row in case.execution_passes) != case.terminal.expected_intents or sum(row.expected_droplets for row in case.execution_passes) != case.terminal.expected_droplets:
        raise JoinedInteractionCaseError("pass totals differ from terminal 24/80 oracle")
    for execution_pass in case.execution_passes:
        observed = sum(value for (stock_id, _), value in final.items() if stock_id == execution_pass.stock_id)
        if observed != execution_pass.expected_droplets:
            raise JoinedInteractionCaseError("literal final counts differ from pass droplet total")


def validate_source_compatibility(case: JoinedInteractionCase) -> dict[str, Any]:
    """Prove that every joined source points to the qualified M9/M10 truth."""

    validate_joined_interaction_case(case)
    source_case = get_experiment_design_case(SOURCE_DESIGN_CASE_ID)
    observed = {
        "case_sha256": source_case.sha256(),
        "catalog_sha256": catalog_sha256(EXPERIMENT_DESIGN_MATRIX_ID),
        "planned_catalog_sha256": planned_catalog_sha256(),
        "reaction_multiset_sha256": source_case.expected.reaction_multiset_sha256(),
        "assignment_sha256": source_case.expected.assignment_sha256(),
        "editor_fixture_sha256": hashlib.sha256(REFERENCE_FIXTURE_PATH.read_bytes()).hexdigest(),
        "requantization_catalog_sha256": catalog_sha256(CALIBRATION_REQUANTIZATION_MATRIX_ID),
        "mixed_mode_catalog_sha256": catalog_sha256(MIXED_MODE_MATRIX_ID),
    }
    expected = case.source.normalized()
    expected.pop("matrix_id")
    expected.pop("case_id")
    if observed != expected:
        raise JoinedInteractionCaseError(f"source compatibility audit failed: {observed!r}")

    source_assignments = tuple((row.well_id, row.reaction_id) for row in source_case.expected.assignments)
    source_counts = {(row.stock_id, row.well_id): row.target_droplets for row in source_case.expected.stock_well_counts}
    if source_assignments != tuple((row.well_id, row.reaction_id) for row in case.assignments):
        raise JoinedInteractionCaseError("joined assignment truth differs from source case")
    if source_counts != case.oracle("prepared").keyed():
        raise JoinedInteractionCaseError("joined prepared count truth differs from source case")
    return {"complete": True, "source": case.source.normalized(), "observed": observed}


def _parse_case(payload: Mapping[str, Any]) -> JoinedInteractionCase:
    _keys(payload, {"case_id", "schema_version", "source", "editor", "stocks", "assignments", "calibrations", "checkpoints", "count_oracles", "execution_passes", "qualification", "terminal"}, "fixture")
    source = payload["source"]
    editor = payload["editor"]
    qualification = payload["qualification"]
    terminal = payload["terminal"]
    _keys(source, set(JoinedSourceIdentity.__dataclass_fields__), "source")
    _keys(editor, set(JoinedEditorInput.__dataclass_fields__), "editor")
    _keys(qualification, set(JoinedQualification.__dataclass_fields__), "qualification")
    _keys(terminal, set(JoinedTerminalOracle.__dataclass_fields__), "terminal")
    count_oracles = tuple(
        JoinedCountOracle(str(checkpoint_id), tuple(JoinedStockWellCount(*row) for row in rows))
        for checkpoint_id, rows in payload["count_oracles"].items()
    )
    case = JoinedInteractionCase(
        case_id=str(payload["case_id"]),
        schema_version=int(payload["schema_version"]),
        source=JoinedSourceIdentity(**source),
        editor=JoinedEditorInput(**{**editor, "selected_well_ids": tuple(editor["selected_well_ids"])}),
        stocks=tuple(JoinedStock(**row) for row in payload["stocks"]),
        assignments=tuple(JoinedAssignment(**row) for row in payload["assignments"]),
        calibrations=tuple(JoinedCalibration(**row) for row in payload["calibrations"]),
        checkpoints=tuple(JoinedCheckpoint(**row) for row in payload["checkpoints"]),
        count_oracles=count_oracles,
        execution_passes=tuple(JoinedExecutionPass(**row) for row in payload["execution_passes"]),
        qualification=JoinedQualification(**{**qualification, "required_screenshots": tuple(qualification["required_screenshots"])}),
        terminal=JoinedTerminalOracle(**terminal),
    )
    validate_joined_interaction_case(case)
    return case


def load_joined_interaction_case(path: Path | None = None) -> JoinedInteractionCase:
    fixture_path = Path(path or JOINED_INTERACTION_FIXTURE_PATH).resolve()
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JoinedInteractionCaseError(f"could not load joined fixture: {exc}") from exc
    if not isinstance(payload, dict):
        raise JoinedInteractionCaseError("joined fixture root must be an object")
    return _parse_case(payload)


def joined_fixture_sha256(path: Path | None = None) -> str:
    return hashlib.sha256(Path(path or JOINED_INTERACTION_FIXTURE_PATH).read_bytes()).hexdigest()


JOINED_INTERACTION_CASE = load_joined_interaction_case()
validate_source_compatibility(JOINED_INTERACTION_CASE)


__all__ = [
    "DESIGN_A_STOCK_ID", "DESIGN_B_STOCK_ID", "WATER_STOCK_ID",
    "EXPECTED_STOCK_IDS", "EXPECTED_WELL_IDS", "JOINED_INTERACTION_CASE",
    "JOINED_INTERACTION_CASE_ID", "JOINED_INTERACTION_FIXTURE_PATH",
    "JoinedAssignment", "JoinedCalibration", "JoinedCheckpoint",
    "JoinedCountOracle", "JoinedEditorInput", "JoinedExecutionPass",
    "JoinedInteractionCase", "JoinedInteractionCaseError", "JoinedQualification",
    "JoinedSourceIdentity", "JoinedStock", "JoinedStockWellCount",
    "JoinedTerminalOracle", "joined_fixture_sha256", "load_joined_interaction_case",
    "validate_joined_interaction_case", "validate_source_compatibility",
]
