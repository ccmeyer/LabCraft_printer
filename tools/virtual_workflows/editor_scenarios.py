"""Editor-driven, hardware-isolated SIL lifecycle scenarios."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import sys
import time
import traceback
import uuid
from collections import Counter
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
UI_DIR = REPO_ROOT / "FreeRTOS-interface"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "verification_reports" / "virtual_workflows"
WORKLOAD_ID = "experiment_editor_create_finalize_v1"
SCENARIO_NAME = "experiment_editor_create_finalize"
SCENARIO_VERSION = "1"
RENAME_WORKLOAD_ID = "experiment_editor_prestart_rename_refinalize_v1"
RENAME_SCENARIO_NAME = "experiment_editor_prestart_rename_refinalize"
POST_START_LOCK_WORKLOAD_ID = "experiment_editor_post_start_lock_v1"
POST_START_LOCK_SCENARIO_NAME = "experiment_editor_post_start_lock"
FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / f"{WORKLOAD_ID}.json"
)
RENAME_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / f"{RENAME_WORKLOAD_ID}.json"
)
POST_START_LOCK_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / f"{POST_START_LOCK_WORKLOAD_ID}.json"
)
EDITOR_FIXTURE_PATHS = {
    WORKLOAD_ID: FIXTURE_PATH,
    RENAME_WORKLOAD_ID: RENAME_FIXTURE_PATH,
    POST_START_LOCK_WORKLOAD_ID: POST_START_LOCK_FIXTURE_PATH,
}
ASSERTION_IDS = (
    "sil.host_hardware_disabled",
    "ui.real_app_constructed",
    "experiment.editor_create_finalize",
    "experiment.prepared_bundle_valid",
    "experiment.prepared_reload_ready",
    "experiment.runtime_assignments_match",
    "experiment.key_files_consistent",
    "artifacts.required_present",
)
RENAME_ASSERTION_IDS = (
    "sil.host_hardware_disabled",
    "ui.real_app_constructed",
    "experiment.prepared_rename_refinalize",
    "experiment.prepared_design_refinalize",
    "experiment.renamed_artifacts_unique",
    "experiment.refinalized_bundle_valid",
    "experiment.prepared_reload_ready",
    "experiment.runtime_assignments_match",
    "experiment.key_files_consistent",
    "artifacts.required_present",
)
POST_START_LOCK_ASSERTION_IDS = (
    "sil.host_hardware_disabled",
    "ui.real_app_constructed",
    "experiment.active_edit_lock",
    "experiment.in_place_edit_rejected",
    "experiment.source_bundle_immutable",
    "experiment.editable_copy_created",
    "experiment.editable_copy_fresh_execution",
    "experiment.editable_copy_editable",
    "artifacts.required_present",
)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))

from tools.virtual_workflows.actions import (  # noqa: E402
    ScenarioActionError,
    ScenarioContext,
    activate_authoritative_execution,
    capture_failure_screenshot,
    capture_milestone,
    drive_editor_create_finalize,
    drive_editor_post_start_lock_and_copy,
    drive_editor_prestart_rename_refinalize,
    install_dialog_handler,
    launch_simulated_application,
    lock_execution_for_printing,
    reload_authoritative_experiment,
    teardown_scenario,
    validate_prepared_bundle,
    validate_refinalized_bundle,
)
from tools.virtual_workflows.report import (  # noqa: E402
    REPORT_SCHEMA_NAME,
    REPORT_SCHEMA_VERSION,
    collect_environment_identity,
    validate_report_v1,
    write_report_atomic,
)
from tools.virtual_workflows.qt_font_environment import (  # noqa: E402
    SilQtFontEnvironmentError,
    apply_and_validate_sil_application_font,
)
from tools.virtual_workflows.scenarios import (  # noqa: E402
    VirtualWorkflowScenarioError,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _resolved_beneath(path: str | Path, root: str | Path) -> bool:
    candidate = Path(path).resolve()
    parent = Path(root).resolve()
    return candidate == parent or parent in candidate.parents


def _exact_fields(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VirtualWorkflowScenarioError(f"{label} must be an object")
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise VirtualWorkflowScenarioError(f"{label} is missing fields: {missing}")
    if unknown:
        raise VirtualWorkflowScenarioError(f"{label} has unknown fields: {unknown}")
    return value


def load_editor_create_finalize_fixture(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load the exact tracked editor lifecycle fixture."""

    fixture_path = Path(path or FIXTURE_PATH).resolve()
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VirtualWorkflowScenarioError(
            f"could not load editor lifecycle fixture: {exc}"
        ) from exc
    top = _exact_fields(
        payload,
        {"fixture_id", "schema_version", "experiment", "reagent", "workload"},
        "fixture",
    )
    experiment = _exact_fields(
        top["experiment"],
        {
            "name",
            "plate_name",
            "replicates",
            "expected_well_ids",
            "printed_volume_nL",
            "final_volume_nL",
            "printed_volume_tolerance_nL",
            "randomize_assignments",
            "allow_two_stock_solutions",
        },
        "fixture.experiment",
    )
    reagent = _exact_fields(
        top["reagent"],
        {
            "stock_label",
            "group",
            "printing_mode",
            "starting_concentration",
            "targets",
            "units",
            "fixed_stock_concentration",
            "droplet_volume_nL",
        },
        "fixture.reagent",
    )
    workload = _exact_fields(
        top["workload"],
        {"completion_count", "expected_editor_finalization_operations"},
        "fixture.workload",
    )
    expected = {
        "fixture_id": WORKLOAD_ID,
        "schema_version": 1,
        "experiment": {
            "name": "sil-editor-create-finalize-v1",
            "plate_name": "shallow-384_well_plate",
            "replicates": 2,
            "expected_well_ids": ["A1", "A2"],
            "printed_volume_nL": 10.0,
            "final_volume_nL": 10.0,
            "printed_volume_tolerance_nL": 0.0,
            "randomize_assignments": False,
            "allow_two_stock_solutions": False,
        },
        "reagent": {
            "stock_label": "Editor Stock",
            "group": "Additive",
            "printing_mode": "droplet",
            "starting_concentration": 0.0,
            "targets": [1.0],
            "units": "x",
            "fixed_stock_concentration": 1.0,
            "droplet_volume_nL": 10.0,
        },
        "workload": {
            "completion_count": 1,
            "expected_editor_finalization_operations": 1,
        },
    }
    normalized = {
        "fixture_id": str(top["fixture_id"]),
        "schema_version": top["schema_version"],
        "experiment": dict(experiment),
        "reagent": dict(reagent),
        "workload": dict(workload),
    }
    if normalized != expected:
        raise VirtualWorkflowScenarioError(
            "editor lifecycle fixture differs from the frozen Slice 4.1 contract"
        )
    return normalized


def load_editor_prestart_rename_refinalize_fixture(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load the exact tracked prepared edit/rename/refinalize fixture."""

    fixture_path = Path(path or RENAME_FIXTURE_PATH).resolve()
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VirtualWorkflowScenarioError(
            f"could not load editor rename lifecycle fixture: {exc}"
        ) from exc
    top = _exact_fields(
        payload,
        {"fixture_id", "schema_version", "experiment", "reagent", "workload"},
        "fixture",
    )
    experiment = _exact_fields(
        top["experiment"],
        {
            "initial_name",
            "renamed_name",
            "plate_name",
            "initial_replicates",
            "initial_expected_well_ids",
            "initial_printed_volume_nL",
            "initial_final_volume_nL",
            "refinalized_replicates",
            "refinalized_expected_well_ids",
            "refinalized_printed_volume_nL",
            "refinalized_final_volume_nL",
            "printed_volume_tolerance_nL",
            "randomize_assignments",
            "allow_two_stock_solutions",
            "initial_fill_printing_mode",
            "initial_fill_droplet_volume_nL",
            "refinalized_fill_printing_mode",
            "refinalized_fill_droplet_volume_nL",
        },
        "fixture.experiment",
    )
    reagent = _exact_fields(
        top["reagent"],
        {
            "stock_label",
            "group",
            "initial_printing_mode",
            "refinalized_printing_mode",
            "starting_concentration",
            "initial_targets",
            "refinalized_targets",
            "units",
            "fixed_stock_concentration",
            "initial_droplet_volume_nL",
            "refinalized_droplet_volume_nL",
        },
        "fixture.reagent",
    )
    workload = _exact_fields(
        top["workload"],
        {
            "completion_count",
            "expected_editor_finalization_operations",
            "expected_rename_operations",
            "expected_prepared_design_edit_operations",
        },
        "fixture.workload",
    )
    expected = {
        "fixture_id": RENAME_WORKLOAD_ID,
        "schema_version": 2,
        "experiment": {
            "initial_name": "sil-editor-prestart-rename-v1",
            "renamed_name": "sil-editor-prestart-renamed-v1",
            "plate_name": "shallow-384_well_plate",
            "initial_replicates": 2,
            "initial_expected_well_ids": ["A1", "A2"],
            "initial_printed_volume_nL": 10.0,
            "initial_final_volume_nL": 10.0,
            "refinalized_replicates": 3,
            "refinalized_expected_well_ids": [
                "A1",
                "A2",
                "A3",
                "A4",
                "A5",
                "A6",
            ],
            "refinalized_printed_volume_nL": 120.0,
            "refinalized_final_volume_nL": 120.0,
            "printed_volume_tolerance_nL": 0.0,
            "randomize_assignments": False,
            "allow_two_stock_solutions": False,
            "initial_fill_printing_mode": "droplet",
            "initial_fill_droplet_volume_nL": 10.0,
            "refinalized_fill_printing_mode": "stream",
            "refinalized_fill_droplet_volume_nL": 60.0,
        },
        "reagent": {
            "stock_label": "Editor Stock",
            "group": "Additive",
            "initial_printing_mode": "droplet",
            "refinalized_printing_mode": "stream",
            "starting_concentration": 0.0,
            "initial_targets": [1.0],
            "refinalized_targets": [0.5, 1.0],
            "units": "x",
            "fixed_stock_concentration": 1.0,
            "initial_droplet_volume_nL": 10.0,
            "refinalized_droplet_volume_nL": 60.0,
        },
        "workload": {
            "completion_count": 2,
            "expected_editor_finalization_operations": 2,
            "expected_rename_operations": 1,
            "expected_prepared_design_edit_operations": 1,
        },
    }
    normalized = {
        "fixture_id": str(top["fixture_id"]),
        "schema_version": top["schema_version"],
        "experiment": dict(experiment),
        "reagent": dict(reagent),
        "workload": dict(workload),
    }
    if normalized != expected:
        raise VirtualWorkflowScenarioError(
            "editor rename fixture differs from the frozen Slice 4.2 contract"
        )
    return normalized


def load_editor_post_start_lock_fixture(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load the exact tracked post-start lock/editable-copy fixture."""

    fixture_path = Path(path or POST_START_LOCK_FIXTURE_PATH).resolve()
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VirtualWorkflowScenarioError(
            f"could not load editor post-start lifecycle fixture: {exc}"
        ) from exc
    top = _exact_fields(
        payload,
        {"fixture_id", "schema_version", "experiment", "reagent", "workload"},
        "fixture",
    )
    experiment = _exact_fields(
        top["experiment"],
        {
            "source_name",
            "copy_name",
            "plate_name",
            "replicates",
            "expected_well_ids",
            "printed_volume_nL",
            "final_volume_nL",
            "printed_volume_tolerance_nL",
            "copy_printed_volume_tolerance_nL",
            "randomize_assignments",
            "allow_two_stock_solutions",
        },
        "fixture.experiment",
    )
    reagent = _exact_fields(
        top["reagent"],
        {
            "stock_label",
            "group",
            "printing_mode",
            "starting_concentration",
            "targets",
            "units",
            "fixed_stock_concentration",
            "droplet_volume_nL",
        },
        "fixture.reagent",
    )
    workload = _exact_fields(
        top["workload"],
        {
            "completion_count",
            "expected_editor_finalization_operations",
            "expected_authoritative_activations",
            "expected_printing_start_locks",
            "expected_editable_copy_operations",
        },
        "fixture.workload",
    )
    expected = {
        "fixture_id": POST_START_LOCK_WORKLOAD_ID,
        "schema_version": 1,
        "experiment": {
            "source_name": "sil-editor-post-start-lock-v1",
            "copy_name": "sil-editor-post-start-copy-v1",
            "plate_name": "shallow-384_well_plate",
            "replicates": 2,
            "expected_well_ids": ["A1", "A2"],
            "printed_volume_nL": 10.0,
            "final_volume_nL": 10.0,
            "printed_volume_tolerance_nL": 0.0,
            "copy_printed_volume_tolerance_nL": 1.0,
            "randomize_assignments": False,
            "allow_two_stock_solutions": False,
        },
        "reagent": {
            "stock_label": "Editor Stock",
            "group": "Additive",
            "printing_mode": "droplet",
            "starting_concentration": 0.0,
            "targets": [1.0],
            "units": "x",
            "fixed_stock_concentration": 1.0,
            "droplet_volume_nL": 10.0,
        },
        "workload": {
            "completion_count": 2,
            "expected_editor_finalization_operations": 2,
            "expected_authoritative_activations": 1,
            "expected_printing_start_locks": 1,
            "expected_editable_copy_operations": 1,
        },
    }
    normalized = {
        "fixture_id": str(top["fixture_id"]),
        "schema_version": top["schema_version"],
        "experiment": dict(experiment),
        "reagent": dict(reagent),
        "workload": dict(workload),
    }
    if normalized != expected:
        raise VirtualWorkflowScenarioError(
            "editor post-start fixture differs from the frozen Slice 4.3 contract"
        )
    return normalized


def _initial_design_fixture(fixture: Mapping[str, Any]) -> dict[str, Any]:
    if fixture["fixture_id"] == WORKLOAD_ID:
        return json.loads(json.dumps(fixture))
    initial = json.loads(json.dumps(fixture))
    experiment = initial["experiment"]
    if fixture["fixture_id"] == RENAME_WORKLOAD_ID:
        experiment["name"] = experiment.pop("initial_name")
        experiment.pop("renamed_name")
        experiment["replicates"] = experiment.pop("initial_replicates")
        experiment["expected_well_ids"] = experiment.pop(
            "initial_expected_well_ids"
        )
        experiment["printed_volume_nL"] = experiment.pop(
            "initial_printed_volume_nL"
        )
        experiment["final_volume_nL"] = experiment.pop(
            "initial_final_volume_nL"
        )
        experiment["fill_printing_mode"] = experiment.pop(
            "initial_fill_printing_mode"
        )
        experiment["fill_droplet_volume_nL"] = experiment.pop(
            "initial_fill_droplet_volume_nL"
        )
        for key in (
            "refinalized_replicates",
            "refinalized_expected_well_ids",
            "refinalized_printed_volume_nL",
            "refinalized_final_volume_nL",
            "refinalized_fill_printing_mode",
            "refinalized_fill_droplet_volume_nL",
        ):
            experiment.pop(key)
        reagent = initial["reagent"]
        reagent["printing_mode"] = reagent.pop("initial_printing_mode")
        reagent["targets"] = reagent.pop("initial_targets")
        reagent["droplet_volume_nL"] = reagent.pop(
            "initial_droplet_volume_nL"
        )
        reagent.pop("refinalized_printing_mode")
        reagent.pop("refinalized_targets")
        reagent.pop("refinalized_droplet_volume_nL")
    else:
        experiment["name"] = experiment.pop("source_name")
        experiment.pop("copy_name")
        experiment.pop("copy_printed_volume_tolerance_nL")
    return initial


@dataclass(frozen=True)
class _EditorScenarioDefinition:
    scenario_name: str
    fixture_loader: Any
    assertion_ids: tuple[str, ...]
    required_screenshots: frozenset[str]


EDITOR_SCENARIO_DEFINITIONS = {
    WORKLOAD_ID: _EditorScenarioDefinition(
        SCENARIO_NAME,
        load_editor_create_finalize_fixture,
        ASSERTION_IDS,
        frozenset(
            {"editor_opened", "generated", "finalized", "validated", "reloaded"}
        ),
    ),
    RENAME_WORKLOAD_ID: _EditorScenarioDefinition(
        RENAME_SCENARIO_NAME,
        load_editor_prestart_rename_refinalize_fixture,
        RENAME_ASSERTION_IDS,
        frozenset(
            {
                "editor_opened",
                "generated",
                "initial_finalized",
                "rename_editor_opened",
                "renamed",
                "prepared_design_edited",
                "regenerated",
                "refinalized",
                "reloaded",
                "validated",
            }
        ),
    ),
    POST_START_LOCK_WORKLOAD_ID: _EditorScenarioDefinition(
        POST_START_LOCK_SCENARIO_NAME,
        load_editor_post_start_lock_fixture,
        POST_START_LOCK_ASSERTION_IDS,
        frozenset(
            {
                "editor_opened",
                "generated",
                "initial_finalized",
                "source_locked",
                "locked_editor_opened",
                "in_place_edit_rejected",
                "editable_copy_created",
                "copy_edited",
                "copy_finalized",
                "validated",
            }
        ),
    ),
}


@dataclass(frozen=True)
class EditorLifecycleScenarioConfig:
    """Runtime controls accepted by the editor lifecycle runner."""

    output_root: Path = DEFAULT_OUTPUT_ROOT
    fixture_path: Path | None = None
    scenario_id: str = WORKLOAD_ID
    visible: bool = False
    speed_multiplier: float = 1.0
    timeout_seconds: float = 60.0
    run_id: str | None = None

    def __post_init__(self) -> None:
        scenario_id = str(self.scenario_id or "").strip()
        speed = float(self.speed_multiplier)
        timeout = float(self.timeout_seconds)
        if scenario_id not in EDITOR_FIXTURE_PATHS:
            raise ValueError(f"unsupported scenario_id: {scenario_id!r}")
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError("speed_multiplier must be finite and greater than zero")
        if not math.isfinite(timeout) or timeout <= 0 or timeout > 60:
            raise ValueError(
                "editor lifecycle timeout_seconds must be greater than zero and at most 60"
            )
        object.__setattr__(self, "scenario_id", scenario_id)
        object.__setattr__(self, "output_root", Path(self.output_root).resolve())
        object.__setattr__(
            self,
            "fixture_path",
            Path(
                self.fixture_path or EDITOR_FIXTURE_PATHS[scenario_id]
            ).resolve(),
        )
        object.__setattr__(self, "speed_multiplier", speed)
        object.__setattr__(self, "timeout_seconds", timeout)


class _EventLog:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.counts: Counter[str] = Counter()

    def record(self, kind: str, **values: Any) -> None:
        self.counts[str(kind)] += 1
        self.events.append(
            {
                "kind": str(kind),
                "monotonic_ns": time.perf_counter_ns(),
                **values,
            }
        )

    def write(self, path: Path) -> None:
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for event in self.events:
                handle.write(json.dumps(event, sort_keys=True) + "\n")


def _runtime_assignments(model: Any) -> dict[str, str]:
    return {
        well.well_id: well.get_assigned_reaction().unique_id
        for well in model.well_plate.get_all_wells()
        if well.get_assigned_reaction() is not None
    }


def _csv_rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or "Well ID" not in rows[0]:
        raise RuntimeError(f"{path.name} has no Well ID rows")
    return {
        str(row.pop("Well ID")): {str(key): str(value) for key, value in row.items()}
        for row in rows
    }


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _audit_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _design_without_name(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(payload))
    metadata = normalized.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("name", None)
    return normalized


def _directory_file_snapshot(directory: Path) -> dict[str, Any]:
    files = sorted(path for path in directory.rglob("*") if path.is_file())
    return {
        "inventory": [path.relative_to(directory).as_posix() for path in files],
        "sha256": {
            path.relative_to(directory).as_posix(): _file_sha256(path)
            for path in files
        },
    }


def _copy_semantic_design(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(payload))
    metadata = normalized.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("name", None)
        metadata.pop("printed_volume_tolerance_nL", None)
    return normalized


def _check_evidence(
    checks: Mapping[str, bool],
    **values: Any,
) -> dict[str, Any]:
    failed = sorted(name for name, passed in checks.items() if not passed)
    return {"checks": dict(checks), "failed_checks": failed, **values}


def _write_summary(report: Mapping[str, Any]) -> str:
    workflow = report["metrics"]["workflow"]["values"]
    lines = [
        f"Scenario: {report['run']['scenario_name']} v{report['run']['scenario_version']}",
        f"Workload: {report['workload']['workload_id']}",
        f"Classification: {report['classification']['status']}",
        f"Duration: {report['run']['duration_ms']:.3f} ms",
        f"Assertions passed: {sum(item['decision'] == 'pass' for item in workflow['assertion_results'])}/{len(workflow['assertion_results'])}",
    ]
    lines.extend(
        f"Reason: {reason}" for reason in report["classification"]["reasons"]
    )
    return "\n".join(lines) + "\n"


def _run_editor_lifecycle_scenario(
    config: EditorLifecycleScenarioConfig,
) -> dict[str, Any]:
    """Run one editor lifecycle through the shared isolated application harness."""

    identity = collect_environment_identity(REPO_ROOT)
    qt_identity = identity["environment"]["qt"]
    if qt_identity.get("binding") != "real":
        raise VirtualWorkflowScenarioError(
            "the editor lifecycle scenario requires an installed real PySide6 binding"
        )
    definition = EDITOR_SCENARIO_DEFINITIONS[config.scenario_id]
    rename_refinalize = config.scenario_id == RENAME_WORKLOAD_ID
    post_start_lock = config.scenario_id == POST_START_LOCK_WORKLOAD_ID
    fixture = definition.fixture_loader(config.fixture_path)
    initial_fixture = _initial_design_fixture(fixture)
    workload_id = fixture["fixture_id"]
    scenario_name = definition.scenario_name
    assertion_ids = definition.assertion_ids
    required_screenshots = definition.required_screenshots
    stamp = _run_stamp()
    short_commit = identity["source"].get("git_short_commit") or "unknown"
    report_dir = (
        config.output_root / workload_id / f"{stamp}_{short_commit}"
    ).resolve()
    report_dir.mkdir(parents=True, exist_ok=False)
    scenario_root = (report_dir / "scenario-root").resolve()
    screenshots_dir = (report_dir / "screenshots").resolve()
    scenario_root.mkdir()
    screenshots_dir.mkdir()
    if not _resolved_beneath(scenario_root, report_dir):
        raise VirtualWorkflowScenarioError(
            "scenario root escaped its report directory"
        )

    event_log = _EventLog()
    context = ScenarioContext(
        scenario_id=scenario_name,
        workload_id=workload_id,
        report_dir=report_dir,
        scenario_root=scenario_root,
        screenshots_dir=screenshots_dir,
        timeout_seconds=config.timeout_seconds,
        record_event=event_log.record,
    )
    started_at = _utc_now()
    started_ns = time.perf_counter_ns()
    application_stdout = io.StringIO()
    stdout_redirect = redirect_stdout(application_stdout)
    stdout_redirect.__enter__()
    context.stdout_redirect = stdout_redirect
    failure_text: str | None = None
    prepared_evidence: dict[str, Any] = {}
    refinalized_evidence: dict[str, Any] = {}
    reload_evidence: dict[str, Any] = {}
    rename_evidence: dict[str, Any] = {}
    post_start_evidence: dict[str, Any] = {}
    assertion_evidence: dict[str, dict[str, Any]] = {}
    assertion_failures: dict[str, dict[str, Any]] = {}

    try:
        from PySide6 import QtCore, QtWidgets
        import ApplicationComposition as composition
        from AuthoritativeExecutionLoad import inspect_authoritative_execution
        from ExecutionCalibrationStore import load_execution_calibrations
        from ExecutionPlan import (
            ExecutionPlanState,
            canonical_sha256,
            load_execution_plan,
        )
        from ExecutionProgressStore import decode_execution_progress
        from ExecutionResumeStore import load_execution_resume
        from hardware.profile import CURRENT_PROFILE
        from simulation import (
            SimulationConfig,
            SimulationTimingPolicy,
            make_simulated_machine_factory,
        )

        app = QtWidgets.QApplication.instance()
        if app is None:
            app = QtWidgets.QApplication(["labcraft-editor-lifecycle"])
        app.setQuitOnLastWindowClosed(False)
        context.app = app
        context.qt_core = QtCore
        font_evidence: dict[str, Any] = {}

        dependencies = composition.simulation_dependencies(
            scenario_root,
            machine_factory=make_simulated_machine_factory(
                SimulationConfig(
                    timing=SimulationTimingPolicy(
                        speed_multiplier=config.speed_multiplier
                    )
                )
            ),
        )
        context.dependencies = dependencies
        roots = (
            dependencies.roots.config_root,
            dependencies.roots.experiments_root,
            dependencies.roots.calibration_memory_root,
        )
        if not all(_resolved_beneath(root, scenario_root) for root in roots):
            raise RuntimeError("one or more simulation roots escaped the scenario root")

        def launch() -> Mapping[str, Any]:
            nonlocal font_evidence
            try:
                font_evidence = apply_and_validate_sil_application_font(app)
            except SilQtFontEnvironmentError as exc:
                qt_identity["font"] = dict(exc.evidence)
                assertion_failures["ui.real_app_constructed"] = {
                    "font_rendering": dict(exc.evidence),
                }
                raise ScenarioActionError(
                    "app.launch_simulated",
                    str(exc),
                    stage="precondition",
                    evidence={"font_rendering": dict(exc.evidence)},
                ) from exc
            qt_identity["font"] = font_evidence
            context.components = composition.build_application_components(
                CURRENT_PROFILE,
                dependencies,
            )
            context.model = context.components.model
            context.machine = context.components.machine
            context.controller = context.components.controller
            context.view = context.components.view
            context.experiment_model = context.model.experiment_model
            context.view.show()
            app.processEvents()
            banner = context.view.simulation_identity_banner
            return {
                "runtime_mode": dependencies.runtime_context.mode.value,
                "visible": bool(config.visible),
                "simulation_banner": {
                    "present": banner is not None,
                    "visible": bool(banner.isVisible()),
                    "text": context.view.simulation_identity_label.text(),
                },
            }

        launch_simulated_application(context, launch)
        assertion_evidence["ui.real_app_constructed"] = {
            "component_type": type(context.components).__name__,
            "view_type": type(context.view).__name__,
            "font_rendering": font_evidence,
        }
        assertion_evidence["sil.host_hardware_disabled"] = {
            "runtime_mode": dependencies.runtime_context.mode.value,
            "machine_connected": bool(
                context.model.machine_model.is_connected()
            ),
            "roots_contained": True,
        }
        install_dialog_handler(context, ())
        drive_editor_create_finalize(context, initial_fixture)
        capture_milestone(
            context,
            (
                "initial_finalized"
                if rename_refinalize or post_start_lock
                else "finalized"
            ),
            evidence={
                "experiment_name": initial_fixture["experiment"]["name"]
            },
        )
        if not rename_refinalize and not post_start_lock:
            assertion_evidence["experiment.editor_create_finalize"] = {
                "experiment_name": initial_fixture["experiment"]["name"],
                "editor_action_ids": [
                    item["action_id"]
                    for item in context.action_results
                    if item["action_id"].startswith("editor.")
                ],
            }

        experiment_model = context.experiment_model
        experiment_dir = Path(experiment_model.experiment_dir_path).resolve()
        design_path = Path(experiment_model.experiment_file_path).resolve()
        resume_path = Path(experiment_model.execution_resume_file_path).resolve()

        def validate_pre_activation() -> Mapping[str, Any]:
            design = json.loads(design_path.read_text(encoding="utf-8"))
            plan = load_execution_plan(
                experiment_model.execution_plan_file_path
            )
            bundle = inspect_authoritative_execution(experiment_dir, design)
            decoded = decode_execution_progress(plan, bundle.progress_payload)
            expected_wells = initial_fixture["experiment"]["expected_well_ids"]
            plan_wells = [well.well_id for well in plan.wells]
            expected_assignments = {
                well.well_id: well.reaction_id for well in plan.wells
            }
            assignments = _runtime_assignments(context.model)
            total_added = sum(
                int(details["added_droplets"])
                for well in decoded.progress_wells.values()
                for details in well["reagents"].values()
            )
            all_incomplete = all(
                not bool(well["completed"])
                for well in decoded.progress_wells.values()
            )
            key_rows = _csv_rows(Path(experiment_model.key_file_path))
            concentration_rows = _csv_rows(
                Path(experiment_model.concentration_key_file_path)
            )
            target_by_well = {
                well_id: sum(
                    int(details["target_droplets"])
                    for details in entry["reagents"].values()
                )
                for well_id, entry in decoded.progress_wells.items()
            }
            key_totals = {
                well_id: sum(int(float(value or 0)) for value in row.values())
                for well_id, row in key_rows.items()
            }
            concentration_values = {
                well_id: sum(float(value or 0) for value in row.values())
                for well_id, row in concentration_rows.items()
            }
            calibration_path = experiment_dir / "execution_calibrations.json"
            calibration_empty = True
            if calibration_path.exists():
                calibration = load_execution_calibrations(calibration_path)
                calibration_empty = (
                    not calibration.records
                    and not calibration.manual_refuel_checks
                )
            checks = {
                "directory_name_matches": experiment_dir.name
                == initial_fixture["experiment"]["name"],
                "metadata_name_matches": design.get("metadata", {}).get("name")
                == initial_fixture["experiment"]["name"],
                "design_hash_matches": plan.design_sha256
                == canonical_sha256(design),
                "plan_revision_one": plan.plan_revision == 1,
                "plan_prepared": plan.state is ExecutionPlanState.PREPARED,
                "plan_wells_exact": plan_wells == expected_wells,
                "history_exact": len(bundle.history) == 1
                and bundle.history[0] == plan,
                "bundle_valid": bool(bundle.valid),
                "ready_to_start": bundle.eligibility.status
                == "ready_to_start",
                "progress_schema_v2": decoded.schema_version == 2,
                "progress_reference_matches": decoded.reference.plan_id
                == plan.plan_id
                and decoded.reference.plan_revision == plan.plan_revision,
                "progress_zero": total_added == 0 and all_incomplete,
                "resume_absent": not resume_path.exists(),
                "key_wells_exact": list(key_rows) == expected_wells,
                "concentration_wells_exact": list(concentration_rows)
                == expected_wells,
                "key_targets_match": key_totals == target_by_well,
                "concentration_targets_match": all(
                    math.isclose(value, 1.0, rel_tol=0.0, abs_tol=1e-9)
                    for value in concentration_values.values()
                ),
                "runtime_assignments_match": assignments
                == expected_assignments,
                "calibration_history_absent": calibration_empty,
                "printing_history_absent": total_added == 0,
            }
            evidence = _check_evidence(
                checks,
                experiment_dir=str(experiment_dir),
                design_path=str(design_path),
                plan_id=plan.plan_id,
                plan_revision=plan.plan_revision,
                plan_state=plan.state.value,
                eligibility_status=bundle.eligibility.status,
                well_ids=plan_wells,
                runtime_assignments=assignments,
                key_rows=key_rows,
                concentration_rows=concentration_rows,
                total_added_droplets=total_added,
            )
            prepared_evidence.update(evidence)
            if evidence["failed_checks"]:
                raise RuntimeError(
                    "authoritative lifecycle checks failed: "
                    + ", ".join(evidence["failed_checks"])
                )
            return evidence

        validate_prepared_bundle(context, validate_pre_activation)
        assertion_evidence["experiment.prepared_bundle_valid"] = {
            "plan_state": prepared_evidence["plan_state"],
            "history_count": 1,
            "total_added_droplets": prepared_evidence[
                "total_added_droplets"
            ],
        }
        assertion_evidence["experiment.key_files_consistent"] = {
            "key_rows": prepared_evidence["key_rows"],
            "concentration_rows": prepared_evidence[
                "concentration_rows"
            ],
        }

        if rename_refinalize:
            initial_dir = experiment_dir
            initial_design_path = design_path
            initial_design = json.loads(
                initial_design_path.read_text(encoding="utf-8")
            )
            initial_plan = load_execution_plan(
                experiment_model.execution_plan_file_path
            )
            initial_assignments = dict(
                prepared_evidence["runtime_assignments"]
            )
            initial_audit_path = Path(
                experiment_model.experiment_audit_file_path
            )
            initial_audit = _audit_rows(initial_audit_path)
            initial_revision_paths = sorted(
                Path(experiment_model.execution_plan_revisions_dir_path).glob(
                    "*.json"
                )
            )
            initial_hashes = {
                "experiment_design.json": _file_sha256(initial_design_path),
                "execution_plan.json": _file_sha256(
                    Path(experiment_model.execution_plan_file_path)
                ),
                "progress.json": _file_sha256(
                    Path(experiment_model.progress_file_path)
                ),
                "key.csv": _file_sha256(
                    Path(experiment_model.key_file_path)
                ),
                "concentration_key.csv": _file_sha256(
                    Path(experiment_model.concentration_key_file_path)
                ),
                **{
                    f"execution_plan_revisions/{path.name}": _file_sha256(
                        path
                    )
                    for path in initial_revision_paths
                },
            }
            rename_evidence["before"] = {
                "experiment_dir": str(initial_dir),
                "metadata_name": initial_design.get("metadata", {}).get(
                    "name"
                ),
                "plan_id": initial_plan.plan_id,
                "plan_revision": initial_plan.plan_revision,
                "plan_design_sha256": initial_plan.design_sha256,
                "resume_present": resume_path.exists(),
                "runtime_assignments": initial_assignments,
                "file_sha256": initial_hashes,
                "audit_rows": initial_audit,
            }

            drive_editor_prestart_rename_refinalize(
                context,
                initial_name=fixture["experiment"]["initial_name"],
                renamed_name=fixture["experiment"]["renamed_name"],
                experiment=fixture["experiment"],
                reagent=fixture["reagent"],
            )
            assertion_evidence["experiment.prepared_rename_refinalize"] = {
                "initial_name": fixture["experiment"]["initial_name"],
                "renamed_name": fixture["experiment"]["renamed_name"],
                "finalization_operations": fixture["workload"][
                    "expected_editor_finalization_operations"
                ],
            }
            assertion_evidence["experiment.prepared_design_refinalize"] = {
                "edit_operations": fixture["workload"][
                    "expected_prepared_design_edit_operations"
                ],
                "refinalized_replicates": fixture["experiment"][
                    "refinalized_replicates"
                ],
                "refinalized_well_ids": fixture["experiment"][
                    "refinalized_expected_well_ids"
                ],
                "refinalized_reagent_mode": fixture["reagent"][
                    "refinalized_printing_mode"
                ],
                "refinalized_fill_mode": fixture["experiment"][
                    "refinalized_fill_printing_mode"
                ],
            }

            experiment_dir = Path(
                experiment_model.experiment_dir_path
            ).resolve()
            design_path = Path(
                experiment_model.experiment_file_path
            ).resolve()
            resume_path = Path(
                experiment_model.execution_resume_file_path
            ).resolve()

            def validate_after_refinalization() -> Mapping[str, Any]:
                design = json.loads(design_path.read_text(encoding="utf-8"))
                plan = load_execution_plan(
                    experiment_model.execution_plan_file_path
                )
                bundle = inspect_authoritative_execution(
                    experiment_dir,
                    design,
                )
                decoded = decode_execution_progress(
                    plan,
                    bundle.progress_payload,
                )
                expected_wells = fixture["experiment"][
                    "refinalized_expected_well_ids"
                ]
                plan_wells = [well.well_id for well in plan.wells]
                expected_assignments = {
                    well.well_id: well.reaction_id for well in plan.wells
                }
                assignments = _runtime_assignments(context.model)
                total_added = sum(
                    int(details["added_droplets"])
                    for well in decoded.progress_wells.values()
                    for details in well["reagents"].values()
                )
                all_incomplete = all(
                    not bool(well["completed"])
                    for well in decoded.progress_wells.values()
                )
                key_rows = _csv_rows(
                    Path(experiment_model.key_file_path)
                )
                concentration_rows = _csv_rows(
                    Path(experiment_model.concentration_key_file_path)
                )
                target_by_well = {
                    well_id: sum(
                        int(details["target_droplets"])
                        for details in entry["reagents"].values()
                    )
                    for well_id, entry in decoded.progress_wells.items()
                }
                key_totals = {
                    well_id: sum(
                        int(float(value or 0)) for value in row.values()
                    )
                    for well_id, row in key_rows.items()
                }
                concentration_values = {
                    well_id: sum(
                        float(value or 0)
                        for column, value in row.items()
                        if column.startswith(
                            f"{fixture['reagent']['stock_label']}_"
                        )
                    )
                    for well_id, row in concentration_rows.items()
                }
                expected_concentrations = sorted(
                    float(target)
                    for target in fixture["reagent"]["refinalized_targets"]
                    for _ in range(
                        fixture["experiment"]["refinalized_replicates"]
                    )
                )
                observed_concentrations = sorted(
                    concentration_values.values()
                )
                metadata = design.get("metadata", {})
                factors = design.get("factors", [])
                reagent_option = (
                    factors[0].get("options", [{}])[0]
                    if len(factors) == 1
                    else {}
                )
                calibration_path = (
                    experiment_dir / "execution_calibrations.json"
                )
                calibration_empty = True
                if calibration_path.exists():
                    calibration = load_execution_calibrations(
                        calibration_path
                    )
                    calibration_empty = (
                        not calibration.records
                        and not calibration.manual_refuel_checks
                    )
                experiments_root = Path(
                    dependencies.roots.experiments_root
                ).resolve()
                experiment_directories = sorted(
                    path.name
                    for path in experiments_root.iterdir()
                    if path.is_dir() and not path.name.startswith(".")
                )
                staging_directories = sorted(
                    str(path.relative_to(experiments_root))
                    for path in experiments_root.rglob(".*.staging-*")
                    if path.is_dir()
                )
                current_plan_paths = sorted(
                    path.relative_to(experiments_root).as_posix()
                    for path in experiments_root.rglob(
                        "execution_plan.json"
                    )
                )
                audit_rows = _audit_rows(
                    Path(experiment_model.experiment_audit_file_path)
                )
                revision_paths = sorted(
                    Path(
                        experiment_model.execution_plan_revisions_dir_path
                    ).glob("*.json")
                )
                file_hashes = {
                    "experiment_design.json": _file_sha256(design_path),
                    "execution_plan.json": _file_sha256(
                        Path(experiment_model.execution_plan_file_path)
                    ),
                    "progress.json": _file_sha256(
                        Path(experiment_model.progress_file_path)
                    ),
                    "key.csv": _file_sha256(
                        Path(experiment_model.key_file_path)
                    ),
                    "concentration_key.csv": _file_sha256(
                        Path(experiment_model.concentration_key_file_path)
                    ),
                    **{
                        f"execution_plan_revisions/{path.name}": (
                            _file_sha256(path)
                        )
                        for path in revision_paths
                    },
                }
                archived_root = (
                    experiment_dir
                    / "superseded_prepared_execution_plans"
                    / initial_plan.plan_id
                )
                archived_plan_path = (
                    archived_root / "prepared_plan_at_replacement.json"
                )
                archived_design_path = (
                    archived_root / "experiment_design_at_replacement.json"
                )
                checks = {
                    "old_directory_absent": not initial_dir.exists(),
                    "renamed_directory_present": experiment_dir.is_dir(),
                    "directory_name_matches": experiment_dir.name
                    == fixture["experiment"]["renamed_name"],
                    "metadata_name_matches": design.get(
                        "metadata", {}
                    ).get("name")
                    == fixture["experiment"]["renamed_name"],
                    "replicates_updated": metadata.get("replicates")
                    == fixture["experiment"]["refinalized_replicates"],
                    "printed_volume_updated": math.isclose(
                        float(metadata.get("target_reaction_volume_nL", -1)),
                        fixture["experiment"][
                            "refinalized_printed_volume_nL"
                        ],
                        rel_tol=0.0,
                        abs_tol=1e-9,
                    ),
                    "final_volume_updated": math.isclose(
                        float(metadata.get("final_reaction_volume_nL", -1)),
                        fixture["experiment"][
                            "refinalized_final_volume_nL"
                        ],
                        rel_tol=0.0,
                        abs_tol=1e-9,
                    ),
                    "fill_mode_updated": metadata.get("fill_printing_mode")
                    == fixture["experiment"][
                        "refinalized_fill_printing_mode"
                    ],
                    "fill_droplet_updated": math.isclose(
                        float(metadata.get("fill_droplet_volume_nL", -1)),
                        fixture["experiment"][
                            "refinalized_fill_droplet_volume_nL"
                        ],
                        rel_tol=0.0,
                        abs_tol=1e-9,
                    ),
                    "reagent_mode_updated": reagent_option.get(
                        "printing_mode"
                    )
                    == fixture["reagent"]["refinalized_printing_mode"],
                    "reagent_targets_updated": reagent_option.get("targets")
                    == fixture["reagent"]["refinalized_targets"],
                    "reagent_droplet_updated": math.isclose(
                        float(reagent_option.get("droplet_nL", -1)),
                        fixture["reagent"][
                            "refinalized_droplet_volume_nL"
                        ],
                        rel_tol=0.0,
                        abs_tol=1e-9,
                    ),
                    "bundle_valid": bool(bundle.valid),
                    "design_hash_matches": plan.design_sha256
                    == canonical_sha256(design),
                    "fresh_plan_identity": plan.plan_id
                    != initial_plan.plan_id,
                    "plan_revision_one": plan.plan_revision == 1,
                    "plan_prepared": plan.state
                    is ExecutionPlanState.PREPARED,
                    "plan_volume_basis_updated": (
                        math.isclose(
                            plan.volume_basis.target_printed_volume_nL,
                            fixture["experiment"][
                                "refinalized_printed_volume_nL"
                            ],
                            rel_tol=0.0,
                            abs_tol=1e-9,
                        )
                        and math.isclose(
                            plan.volume_basis.final_reaction_volume_nL,
                            fixture["experiment"][
                                "refinalized_final_volume_nL"
                            ],
                            rel_tol=0.0,
                            abs_tol=1e-9,
                        )
                    ),
                    "plan_modes_updated": {
                        stock.printing_mode for stock in plan.stocks
                    }
                    == {fixture["reagent"]["refinalized_printing_mode"]},
                    "plan_wells_exact": plan_wells == expected_wells,
                    "history_current_matches": bool(bundle.history)
                    and bundle.history[-1] == plan,
                    "ready_to_start": bundle.eligibility.status
                    == "ready_to_start",
                    "progress_reference_matches": decoded.reference.plan_id
                    == plan.plan_id
                    and decoded.reference.plan_revision
                    == plan.plan_revision,
                    "progress_zero": total_added == 0 and all_incomplete,
                    "resume_absent": not resume_path.exists(),
                    "key_wells_exact": list(key_rows) == expected_wells,
                    "concentration_wells_exact": list(
                        concentration_rows
                    )
                    == expected_wells,
                    "key_targets_match": key_totals == target_by_well,
                    "concentration_targets_match": len(
                        observed_concentrations
                    )
                    == len(expected_concentrations)
                    and all(
                        math.isclose(
                            observed,
                            expected,
                            rel_tol=0.0,
                            abs_tol=1e-9,
                        )
                        for observed, expected in zip(
                            observed_concentrations,
                            expected_concentrations,
                        )
                    ),
                    "runtime_assignments_match_plan": assignments
                    == expected_assignments,
                    "runtime_assignments_replaced": assignments
                    != initial_assignments,
                    "original_plan_archived": archived_plan_path.is_file()
                    and load_execution_plan(archived_plan_path)
                    == initial_plan,
                    "original_design_archived": archived_design_path.is_file()
                    and json.loads(
                        archived_design_path.read_text(encoding="utf-8")
                    )
                    == initial_design,
                    "calibration_history_absent": calibration_empty,
                    "printing_history_absent": total_added == 0,
                    "single_experiment_directory": (
                        experiment_directories
                        == [fixture["experiment"]["renamed_name"]]
                    ),
                    "no_staging_directories": not staging_directories,
                    "single_current_plan": current_plan_paths
                    == [
                        (
                            f"{fixture['experiment']['renamed_name']}"
                            "/execution_plan.json"
                        )
                    ],
                    "audit_retained_and_advanced": len(audit_rows)
                    > len(initial_audit),
                }
                evidence = _check_evidence(
                    checks,
                    experiment_dir=str(experiment_dir),
                    design_path=str(design_path),
                    initial_name=fixture["experiment"]["initial_name"],
                    renamed_name=fixture["experiment"]["renamed_name"],
                    previous_plan_id=initial_plan.plan_id,
                    plan_id=plan.plan_id,
                    plan_revision=plan.plan_revision,
                    plan_state=plan.state.value,
                    eligibility_status=bundle.eligibility.status,
                    history_count=len(bundle.history),
                    well_ids=plan_wells,
                    runtime_assignments=assignments,
                    runtime_assignments_before=initial_assignments,
                    expected_design_updates={
                        "replicates": fixture["experiment"][
                            "refinalized_replicates"
                        ],
                        "well_ids": expected_wells,
                        "printed_volume_nL": fixture["experiment"][
                            "refinalized_printed_volume_nL"
                        ],
                        "final_volume_nL": fixture["experiment"][
                            "refinalized_final_volume_nL"
                        ],
                        "reagent_targets": fixture["reagent"][
                            "refinalized_targets"
                        ],
                        "reagent_printing_mode": fixture["reagent"][
                            "refinalized_printing_mode"
                        ],
                        "fill_printing_mode": fixture["experiment"][
                            "refinalized_fill_printing_mode"
                        ],
                    },
                    superseded_prepared_execution={
                        "directory": str(archived_root),
                        "plan_path": str(archived_plan_path),
                        "design_path": str(archived_design_path),
                    },
                    key_rows=key_rows,
                    concentration_rows=concentration_rows,
                    total_added_droplets=total_added,
                    experiment_directories=experiment_directories,
                    staging_directories=staging_directories,
                    current_plan_paths=current_plan_paths,
                    file_sha256=file_hashes,
                    audit_rows=audit_rows,
                )
                refinalized_evidence.update(evidence)
                rename_evidence["after"] = {
                    key: evidence[key]
                    for key in (
                        "experiment_dir",
                        "renamed_name",
                        "plan_id",
                        "plan_revision",
                        "file_sha256",
                        "audit_rows",
                    )
                }
                if evidence["failed_checks"]:
                    raise RuntimeError(
                        "refinalized lifecycle checks failed: "
                        + ", ".join(evidence["failed_checks"])
                    )
                return evidence

            validate_refinalized_bundle(
                context,
                validate_after_refinalization,
            )
            assertion_evidence.update(
                {
                    "experiment.renamed_artifacts_unique": {
                        "experiment_directories": refinalized_evidence[
                            "experiment_directories"
                        ],
                        "current_plan_paths": refinalized_evidence[
                            "current_plan_paths"
                        ],
                        "staging_directories": refinalized_evidence[
                            "staging_directories"
                        ],
                    },
                    "experiment.refinalized_bundle_valid": {
                        "plan_state": refinalized_evidence[
                            "plan_state"
                        ],
                        "eligibility_status": refinalized_evidence[
                            "eligibility_status"
                        ],
                        "history_count": refinalized_evidence[
                            "history_count"
                        ],
                        "total_added_droplets": refinalized_evidence[
                            "total_added_droplets"
                        ],
                    },
                    "experiment.key_files_consistent": {
                        "key_rows": refinalized_evidence["key_rows"],
                        "concentration_rows": refinalized_evidence[
                            "concentration_rows"
                        ],
                    },
                }
            )

        if post_start_lock:
            source_dir = experiment_dir
            source_design_path = design_path
            source_design = json.loads(
                source_design_path.read_text(encoding="utf-8")
            )

            def activate_source() -> Mapping[str, Any]:
                eligibility = (
                    context.model.load_authoritative_execution_runtime()
                )
                resume = load_execution_resume(
                    experiment_model.execution_resume_file_path
                )
                checks = {
                    "ready_to_start": eligibility["status"]
                    == "ready_to_start",
                    "resume_clean": resume.state == "clean",
                    "resume_zero_intents": not resume.intents,
                }
                if not all(checks.values()):
                    raise RuntimeError(
                        "source activation failed: "
                        + ", ".join(
                            name
                            for name, passed in checks.items()
                            if not passed
                        )
                    )
                return {
                    "checks": checks,
                    "eligibility_status": eligibility["status"],
                    "resume_state": resume.state,
                    "resume_intent_count": len(resume.intents),
                }

            activation = activate_authoritative_execution(
                context,
                activate_source,
            )

            def lock_source() -> Mapping[str, Any]:
                plan = experiment_model.lock_execution_plan(
                    "printing_started"
                )
                if plan is None:
                    raise RuntimeError(
                        "printing-start lock returned no execution plan"
                    )
                return {
                    "plan_id": plan.plan_id,
                    "plan_revision": plan.plan_revision,
                    "plan_state": plan.state.value,
                    "lock_reason": plan.lock_reason,
                }

            locked = lock_execution_for_printing(context, lock_source)
            locked_design = json.loads(
                source_design_path.read_text(encoding="utf-8")
            )
            locked_bundle = inspect_authoritative_execution(
                source_dir,
                locked_design,
            )
            locked_plan = load_execution_plan(
                experiment_model.execution_plan_file_path
            )
            locked_resume = load_execution_resume(
                experiment_model.execution_resume_file_path
            )
            locked_decoded = decode_execution_progress(
                locked_plan,
                locked_bundle.progress_payload,
            )
            locked_total_added = sum(
                int(details["added_droplets"])
                for well in locked_decoded.progress_wells.values()
                for details in well["reagents"].values()
            )
            locked_snapshot = _directory_file_snapshot(source_dir)
            locked_checks = {
                "bundle_valid": bool(locked_bundle.valid),
                "active": locked_plan.state is ExecutionPlanState.ACTIVE,
                "revision_two": locked_plan.plan_revision == 2,
                "printing_started": locked_plan.lock_reason
                == "printing_started",
                "history_two": len(locked_bundle.history) == 2
                and locked_bundle.history[-1] == locked_plan,
                "resume_clean": locked_resume.state == "clean",
                "resume_zero_intents": not locked_resume.intents,
                "resume_reference_matches": locked_resume.plan_id
                == locked_plan.plan_id
                and locked_resume.plan_revision
                == locked_plan.plan_revision,
                "zero_progress": locked_total_added == 0,
                "design_unchanged": locked_design == source_design,
            }
            post_start_evidence["source_locked"] = _check_evidence(
                locked_checks,
                activation=activation,
                lock=locked,
                experiment_dir=str(source_dir),
                plan_id=locked_plan.plan_id,
                plan_revision=locked_plan.plan_revision,
                plan_state=locked_plan.state.value,
                lock_reason=locked_plan.lock_reason,
                history_count=len(locked_bundle.history),
                total_added_droplets=locked_total_added,
                resume_state=locked_resume.state,
                resume_intent_count=len(locked_resume.intents),
                runtime_assignments=_runtime_assignments(context.model),
                directory_snapshot=locked_snapshot,
                audit_rows=_audit_rows(
                    Path(experiment_model.experiment_audit_file_path)
                ),
            )
            if post_start_evidence["source_locked"]["failed_checks"]:
                raise RuntimeError(
                    "post-start source lock checks failed: "
                    + ", ".join(
                        post_start_evidence["source_locked"][
                            "failed_checks"
                        ]
                    )
                )
            assertion_evidence["experiment.active_edit_lock"] = {
                "plan_state": locked_plan.state.value,
                "plan_revision": locked_plan.plan_revision,
                "lock_reason": locked_plan.lock_reason,
            }
            capture_milestone(
                context,
                "source_locked",
                evidence={
                    "plan_state": locked_plan.state.value,
                    "plan_revision": locked_plan.plan_revision,
                    "lock_reason": locked_plan.lock_reason,
                },
            )

            editor_boundary = drive_editor_post_start_lock_and_copy(
                context,
                source_dir=source_dir,
                source_name=fixture["experiment"]["source_name"],
                copy_name=fixture["experiment"]["copy_name"],
                copy_tolerance_nl=fixture["experiment"][
                    "copy_printed_volume_tolerance_nL"
                ],
            )
            post_start_evidence["locked_editor"] = editor_boundary[
                "lock_matrix"
            ]
            post_start_evidence["editable_copy_before_finalize"] = (
                editor_boundary["copy_before_finalize"]
            )
            assertion_evidence["experiment.in_place_edit_rejected"] = {
                "source_name": fixture["experiment"]["source_name"],
                "control_matrix": editor_boundary["lock_matrix"],
            }
            assertion_evidence["experiment.editable_copy_created"] = {
                "copy_name": fixture["experiment"]["copy_name"],
                "copy_before_finalize": editor_boundary[
                    "copy_before_finalize"
                ],
            }
            assertion_evidence["experiment.editable_copy_editable"] = {
                "copy_tolerance_nL": fixture["experiment"][
                    "copy_printed_volume_tolerance_nL"
                ],
                "controls_editable": True,
            }

            copy_dir = Path(
                experiment_model.experiment_dir_path
            ).resolve()
            copy_design_path = Path(
                experiment_model.experiment_file_path
            ).resolve()
            copy_resume_path = Path(
                experiment_model.execution_resume_file_path
            ).resolve()
            copy_design = json.loads(
                copy_design_path.read_text(encoding="utf-8")
            )
            copy_plan = load_execution_plan(
                experiment_model.execution_plan_file_path
            )
            copy_bundle = inspect_authoritative_execution(
                copy_dir,
                copy_design,
            )
            copy_decoded = decode_execution_progress(
                copy_plan,
                copy_bundle.progress_payload,
            )
            copy_total_added = sum(
                int(details["added_droplets"])
                for well in copy_decoded.progress_wells.values()
                for details in well["reagents"].values()
            )
            copy_key_rows = _csv_rows(
                Path(experiment_model.key_file_path)
            )
            copy_concentration_rows = _csv_rows(
                Path(experiment_model.concentration_key_file_path)
            )
            copy_calibration_path = (
                copy_dir / "execution_calibrations.json"
            )
            copy_calibration_absent = not copy_calibration_path.exists()
            source_after_snapshot = _directory_file_snapshot(source_dir)
            copy_checks = {
                "copy_directory_distinct": copy_dir != source_dir,
                "copy_directory_name": copy_dir.name
                == fixture["experiment"]["copy_name"],
                "copy_metadata_name": copy_design.get(
                    "metadata", {}
                ).get("name")
                == fixture["experiment"]["copy_name"],
                "copy_semantics_match_source": _copy_semantic_design(
                    copy_design
                )
                == _copy_semantic_design(source_design),
                "copy_tolerance_changed": math.isclose(
                    float(
                        copy_design.get("metadata", {}).get(
                            "printed_volume_tolerance_nL", -1
                        )
                    ),
                    float(
                        fixture["experiment"][
                            "copy_printed_volume_tolerance_nL"
                        ]
                    ),
                    rel_tol=0.0,
                    abs_tol=1e-9,
                ),
                "copy_bundle_valid": bool(copy_bundle.valid),
                "copy_prepared": copy_plan.state
                is ExecutionPlanState.PREPARED,
                "copy_revision_one": copy_plan.plan_revision == 1,
                "copy_ready_to_start": copy_bundle.eligibility.status
                == "ready_to_start",
                "copy_plan_distinct": copy_plan.plan_id
                != locked_plan.plan_id,
                "copy_history_fresh": len(copy_bundle.history) == 1
                and copy_bundle.history[0] == copy_plan,
                "copy_zero_progress": copy_total_added == 0,
                "copy_resume_absent": not copy_resume_path.exists(),
                "copy_calibration_absent": copy_calibration_absent,
                "copy_wells_exact": [
                    well.well_id for well in copy_plan.wells
                ]
                == fixture["experiment"]["expected_well_ids"],
                "copy_key_wells_exact": list(copy_key_rows)
                == fixture["experiment"]["expected_well_ids"],
                "copy_concentration_wells_exact": list(
                    copy_concentration_rows
                )
                == fixture["experiment"]["expected_well_ids"],
                "source_inventory_unchanged": (
                    source_after_snapshot["inventory"]
                    == locked_snapshot["inventory"]
                ),
                "source_files_byte_identical": (
                    source_after_snapshot["sha256"]
                    == locked_snapshot["sha256"]
                ),
            }
            copy_evidence = _check_evidence(
                copy_checks,
                experiment_dir=str(copy_dir),
                design_path=str(copy_design_path),
                plan_id=copy_plan.plan_id,
                plan_revision=copy_plan.plan_revision,
                plan_state=copy_plan.state.value,
                eligibility_status=copy_bundle.eligibility.status,
                history_count=len(copy_bundle.history),
                total_added_droplets=copy_total_added,
                resume_present=copy_resume_path.exists(),
                runtime_assignments=_runtime_assignments(context.model),
                key_rows=copy_key_rows,
                concentration_rows=copy_concentration_rows,
                directory_snapshot=_directory_file_snapshot(copy_dir),
            )
            post_start_evidence["editable_copy_after_finalize"] = (
                copy_evidence
            )
            post_start_evidence["source_after_copy"] = {
                "directory_snapshot": source_after_snapshot,
                "inventory_unchanged": copy_checks[
                    "source_inventory_unchanged"
                ],
                "files_byte_identical": copy_checks[
                    "source_files_byte_identical"
                ],
            }
            refinalized_evidence.update(copy_evidence)
            if copy_evidence["failed_checks"]:
                raise RuntimeError(
                    "editable-copy lifecycle checks failed: "
                    + ", ".join(copy_evidence["failed_checks"])
                )
            assertion_evidence["experiment.source_bundle_immutable"] = {
                "inventory_unchanged": True,
                "files_byte_identical": True,
                "file_count": len(locked_snapshot["inventory"]),
            }
            assertion_evidence[
                "experiment.editable_copy_fresh_execution"
            ] = {
                "source_plan_id": locked_plan.plan_id,
                "copy_plan_id": copy_plan.plan_id,
                "copy_plan_revision": copy_plan.plan_revision,
                "copy_plan_state": copy_plan.state.value,
                "copy_resume_absent_before_activation": True,
                "copy_history_count": len(copy_bundle.history),
            }
            experiment_dir = copy_dir
            design_path = copy_design_path
            resume_path = copy_resume_path

        design_payload = json.loads(design_path.read_text(encoding="utf-8"))
        prepared_plan = load_execution_plan(
            experiment_model.execution_plan_file_path
        )
        assignments_before = dict(
            (
                refinalized_evidence
                if rename_refinalize or post_start_lock
                else prepared_evidence
            )["runtime_assignments"]
        )

        def reload() -> Mapping[str, Any]:
            experiment_model.load_experiment(
                str(design_path),
                str(experiment_dir),
            )
            before_activation = inspect_authoritative_execution(
                experiment_dir,
                design_payload,
            )
            eligibility = context.model.load_authoritative_execution_runtime()
            active_plan = load_execution_plan(
                experiment_model.execution_plan_file_path
            )
            resume = load_execution_resume(
                experiment_model.execution_resume_file_path
            )
            assignments_after = _runtime_assignments(context.model)
            checks = {
                "reloaded_bundle_valid": bool(before_activation.valid),
                "reloaded_ready_to_start": before_activation.eligibility.status
                == "ready_to_start",
                "activation_ready_to_start": eligibility["status"]
                == "ready_to_start",
                "resume_clean": resume.state == "clean",
                "resume_zero_intents": not resume.intents,
                "resume_plan_reference_matches": resume.plan_id
                == prepared_plan.plan_id
                and resume.plan_revision == prepared_plan.plan_revision,
                "plan_still_prepared": active_plan.state
                is ExecutionPlanState.PREPARED,
                "plan_identity_unchanged": active_plan == prepared_plan,
                "runtime_assignments_unchanged": assignments_after
                == assignments_before,
            }
            evidence = _check_evidence(
                checks,
                eligibility_status=eligibility["status"],
                resume_state=resume.state,
                resume_intent_count=len(resume.intents),
                runtime_assignments=assignments_after,
                plan_id=active_plan.plan_id,
                plan_revision=active_plan.plan_revision,
            )
            reload_evidence.update(evidence)
            if evidence["failed_checks"]:
                raise RuntimeError(
                    "authoritative reload checks failed: "
                    + ", ".join(evidence["failed_checks"])
                )
            return evidence

        reload_authoritative_experiment(context, reload)
        capture_milestone(
            context,
            "reloaded" if not post_start_lock else "validated",
            evidence=(
                {
                    "eligibility_status": reload_evidence[
                        "eligibility_status"
                    ],
                    "resume_state": reload_evidence["resume_state"],
                }
                if not post_start_lock
                else {
                    "source_plan_state": "ACTIVE",
                    "copy_plan_state": refinalized_evidence["plan_state"],
                    "assertion_count": len(assertion_ids),
                }
            ),
        )
        if not post_start_lock:
            capture_milestone(
                context,
                "validated",
                evidence={
                    "plan_state": (
                        refinalized_evidence
                        if rename_refinalize
                        else prepared_evidence
                    )["plan_state"],
                    "eligibility_status": reload_evidence[
                        "eligibility_status"
                    ],
                    "assertion_count": len(assertion_ids),
                },
            )

        assertion_evidence.update(
            {
                "experiment.prepared_reload_ready": {
                    "eligibility_status": reload_evidence[
                        "eligibility_status"
                    ],
                    "resume_state": reload_evidence["resume_state"],
                    "resume_intent_count": reload_evidence[
                        "resume_intent_count"
                    ],
                },
                "experiment.runtime_assignments_match": {
                    "before": prepared_evidence["runtime_assignments"],
                    "after": reload_evidence["runtime_assignments"],
                },
            }
        )
    except BaseException as exc:
        failure_text = traceback.format_exc()
        if post_start_lock:
            action_evidence = dict(getattr(exc, "evidence", {}) or {})
            control_matrix = action_evidence.get("control_matrix")
            if isinstance(control_matrix, Mapping):
                post_start_evidence["locked_editor"] = dict(
                    control_matrix
                )
        if post_start_lock and post_start_evidence.get("source_locked"):
            try:
                source_path = Path(
                    post_start_evidence["source_locked"]["experiment_dir"]
                ).resolve()
                post_start_evidence["source_after_copy"] = {
                    "directory_snapshot": _directory_file_snapshot(
                        source_path
                    ),
                    "diagnostic_only": True,
                }
            except Exception as diagnostic_exc:
                post_start_evidence["source_after_copy"] = {
                    "diagnostic_error": (
                        f"{type(diagnostic_exc).__name__}: "
                        f"{diagnostic_exc}"
                    )[:2000]
                }
        if rename_refinalize and rename_evidence.get("before"):
            try:
                current_dir = Path(
                    context.experiment_model.experiment_dir_path
                ).resolve()
                experiments_root = Path(
                    context.dependencies.roots.experiments_root
                ).resolve()
                current_design_path = Path(
                    context.experiment_model.experiment_file_path
                ).resolve()
                current_design = (
                    json.loads(
                        current_design_path.read_text(encoding="utf-8")
                    )
                    if current_design_path.is_file()
                    else None
                )
                current_plan_path = Path(
                    context.experiment_model.execution_plan_file_path
                ).resolve()
                rename_evidence["failure_state"] = {
                    "experiment_dir": str(current_dir),
                    "experiment_dir_exists": current_dir.is_dir(),
                    "old_directory_exists": Path(
                        rename_evidence["before"]["experiment_dir"]
                    ).exists(),
                    "experiment_directories": sorted(
                        path.name
                        for path in experiments_root.iterdir()
                        if path.is_dir() and not path.name.startswith(".")
                    ),
                    "metadata_name": (
                        current_design.get("metadata", {}).get("name")
                        if isinstance(current_design, dict)
                        else None
                    ),
                    "design_sha256": (
                        canonical_sha256(current_design)
                        if isinstance(current_design, dict)
                        else None
                    ),
                    "execution_plan_present": current_plan_path.is_file(),
                    "execution_plan_file_sha256": (
                        _file_sha256(current_plan_path)
                        if current_plan_path.is_file()
                        else None
                    ),
                    "current_file_paths": sorted(
                        str(path.relative_to(experiments_root))
                        for path in experiments_root.rglob("*")
                        if path.is_file()
                    ),
                    "audit_rows": _audit_rows(
                        Path(
                            context.experiment_model.experiment_audit_file_path
                        )
                    ),
                }
            except Exception as diagnostic_exc:
                rename_evidence["failure_state"] = {
                    "diagnostic_error": (
                        f"{type(diagnostic_exc).__name__}: "
                        f"{diagnostic_exc}"
                    )[:2000]
                }
        context.errors.append(
            {
                "type": type(exc).__name__,
                "message": str(exc)[:2000],
            }
        )
        event_log.record(
            "error",
            error_type=type(exc).__name__,
            message=str(exc)[:2000],
        )
        action_id = getattr(exc, "action_id", None)
        failure_evidence = {
            "action_id": action_id,
            "failure_type": type(exc).__name__,
            "failure_message": str(exc)[:2000],
            "action_evidence": dict(getattr(exc, "evidence", {}) or {}),
        }
        if post_start_lock and action_id in {
            "editor.inspect_active_lock_via_ui",
            "editor.reject_in_place_edit_via_ui",
        }:
            assertion_failures[
                (
                    "experiment.active_edit_lock"
                    if action_id == "editor.inspect_active_lock_via_ui"
                    else "experiment.in_place_edit_rejected"
                )
            ] = {
                **failure_evidence,
                "locked_editor": post_start_evidence.get(
                    "locked_editor", {}
                ),
            }
        elif post_start_lock and action_id in {
            "editor.create_editable_copy_via_ui",
            "editor.edit_copy_via_ui",
            "editor.finalize_copy_via_ui",
        }:
            assertion_failures["experiment.editable_copy_created"] = (
                failure_evidence
            )
        elif post_start_lock and action_id in {
            "experiment.activate_authoritative",
            "execution.lock_for_printing",
        }:
            assertion_failures["experiment.active_edit_lock"] = (
                failure_evidence
            )
        elif isinstance(action_id, str) and action_id.startswith("editor."):
            if rename_refinalize and action_id in {
                "editor.edit_prepared_design_via_ui",
                "editor.regenerate_prepared_design_via_ui",
            }:
                assertion_failures[
                    "experiment.prepared_design_refinalize"
                ] = failure_evidence
            else:
                assertion_failures[
                    (
                        "experiment.prepared_rename_refinalize"
                        if rename_refinalize
                        else "experiment.editor_create_finalize"
                    )
                ] = failure_evidence
        elif action_id == "validation.prepared_bundle":
            assertion_failures[
                "experiment.prepared_bundle_valid"
            ] = {
                **failure_evidence,
                "failed_checks": prepared_evidence.get(
                    "failed_checks", []
                ),
            }
            failed_checks = set(prepared_evidence.get("failed_checks", []))
            if failed_checks & {
                "key_wells_exact",
                "concentration_wells_exact",
                "key_targets_match",
                "concentration_targets_match",
            }:
                assertion_failures[
                    "experiment.key_files_consistent"
                ] = {
                    **failure_evidence,
                    "failed_checks": sorted(failed_checks),
                }
            if failed_checks & {
                "replicates_updated",
                "printed_volume_updated",
                "final_volume_updated",
                "fill_mode_updated",
                "fill_droplet_updated",
                "reagent_mode_updated",
                "reagent_targets_updated",
                "reagent_droplet_updated",
                "fresh_plan_identity",
                "plan_revision_one",
                "plan_volume_basis_updated",
                "plan_modes_updated",
                "runtime_assignments_replaced",
                "original_plan_archived",
                "original_design_archived",
            }:
                assertion_failures[
                    "experiment.prepared_design_refinalize"
                ] = {
                    **failure_evidence,
                    "failed_checks": sorted(failed_checks),
                }
        elif action_id == "validation.refinalized_bundle":
            assertion_failures[
                "experiment.refinalized_bundle_valid"
            ] = {
                **failure_evidence,
                "failed_checks": refinalized_evidence.get(
                    "failed_checks", []
                ),
            }
            failed_checks = set(
                refinalized_evidence.get("failed_checks", [])
            )
            if failed_checks & {
                "old_directory_absent",
                "renamed_directory_present",
                "single_experiment_directory",
                "no_staging_directories",
                "single_current_plan",
            }:
                assertion_failures[
                    "experiment.renamed_artifacts_unique"
                ] = {
                    **failure_evidence,
                    "failed_checks": sorted(failed_checks),
                }
            if failed_checks & {
                "key_wells_exact",
                "concentration_wells_exact",
                "key_targets_match",
                "concentration_targets_match",
            }:
                assertion_failures[
                    "experiment.key_files_consistent"
                ] = {
                    **failure_evidence,
                    "failed_checks": sorted(failed_checks),
                }
        elif action_id == "experiment.reload_authoritative":
            assertion_failures[
                "experiment.prepared_reload_ready"
            ] = {
                **failure_evidence,
                "failed_checks": reload_evidence.get("failed_checks", []),
            }
            if "runtime_assignments_unchanged" in set(
                reload_evidence.get("failed_checks", [])
            ):
                assertion_failures[
                    "experiment.runtime_assignments_match"
                ] = failure_evidence
        try:
            if "failure" not in context.screenshots:
                capture_failure_screenshot(context)
        except Exception as screenshot_exc:
            context.errors.append(
                {
                    "type": type(screenshot_exc).__name__,
                    "message": f"failure screenshot: {screenshot_exc}"[:2000],
                }
            )
    finally:
        try:
            teardown_scenario(context)
        except Exception as cleanup_exc:
            if failure_text is None:
                failure_text = traceback.format_exc()
            context.errors.append(
                {
                    "type": type(cleanup_exc).__name__,
                    "message": str(cleanup_exc)[:2000],
                }
            )

    ended_at = _utc_now()
    duration_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
    event_path = report_dir / "events.jsonl"
    summary_path = report_dir / "summary.txt"
    stdout_path = report_dir / "application_stdout.log"
    stack_path = report_dir / "stall_stacks.txt"
    event_log.write(event_path)
    stdout_path.write_text(application_stdout.getvalue(), encoding="utf-8")
    stack_path.write_text("", encoding="utf-8")
    if failure_text is not None:
        (report_dir / "failure_traceback.txt").write_text(
            failure_text,
            encoding="utf-8",
        )

    required_artifacts_present = (
        event_path.is_file()
        and stdout_path.is_file()
        and stack_path.is_file()
        and scenario_root.is_dir()
        and set(context.screenshots) == required_screenshots
        and all(
            path.is_file() and path.stat().st_size > 0
            for path in context.screenshots.values()
        )
    )
    if required_artifacts_present:
        assertion_evidence["artifacts.required_present"] = {
            "screenshot_names": sorted(context.screenshots),
            "required_file_names": [
                "events.jsonl",
                "application_stdout.log",
                "stall_stacks.txt",
            ],
        }
    else:
        assertion_failures["artifacts.required_present"] = {
            "screenshot_names": sorted(context.screenshots),
            "reason": "one or more required lifecycle artifacts are absent or empty",
        }

    assertion_results = [
        {
            "assertion_id": assertion_id,
            "decision": (
                "fail"
                if assertion_id in assertion_failures
                else "pass"
                if assertion_id in assertion_evidence
                else "incomplete"
            ),
            "evidence": (
                assertion_failures[assertion_id]
                if assertion_id in assertion_failures
                else assertion_evidence.get(
                    assertion_id,
                    {"reason": "scenario did not reach this assertion"},
                )
            ),
        }
        for assertion_id in assertion_ids
    ]
    failed_actions = [
        item for item in context.action_results if item["status"] != "pass"
    ]
    failed_cleanup = [
        item for item in context.cleanup_results if item["status"] != "pass"
    ]
    passed = (
        not context.errors
        and not context.unexpected_dialogs
        and not failed_actions
        and not failed_cleanup
        and all(item["decision"] == "pass" for item in assertion_results)
    )
    reasons = (
        []
        if passed
        else [
            "The editor lifecycle did not complete every required action, assertion, and cleanup phase."
        ]
    )
    platform_name = str(qt_identity.get("platform") or "unknown")
    report = {
        "schema_name": REPORT_SCHEMA_NAME,
        "schema_version": REPORT_SCHEMA_VERSION,
        "run": {
            "run_id": config.run_id or str(uuid.uuid4()),
            "scenario_name": scenario_name,
            "scenario_version": SCENARIO_VERSION,
            "run_mode": (
                "visible_windows_sil"
                if config.visible
                else f"{platform_name}_windows_sil"
            ),
            "timing_policy": (
                f"isolated_simulator_x{config.speed_multiplier:g}_no_commands"
            ),
            "warmup_runs": 0,
            "measured_runs": 1,
            "started_at_utc": started_at,
            "ended_at_utc": ended_at,
            "duration_ms": duration_ms,
        },
        "source": identity["source"],
        "environment": identity["environment"],
        "safety": {
            "simulation": True,
            "hardware_access_allowed": False,
            "hardware_interfaces": {
                "serial": False,
                "GPIO": False,
                "camera": False,
                "balance": False,
                "MCU": False,
                "firmware_update": False,
            },
            "simulated_port": "SIMULATED",
            "scenario_root": str(scenario_root),
            "root_containment_valid": _resolved_beneath(
                scenario_root, report_dir
            ),
        },
        "workload": {
            "workload_id": workload_id,
            "fixture_schema_version": fixture["schema_version"],
            "operation_count": fixture["workload"][
                "expected_editor_finalization_operations"
            ],
            "experiment_name": (
                fixture["experiment"]["initial_name"]
                if rename_refinalize
                else (
                    fixture["experiment"]["source_name"]
                    if post_start_lock
                    else fixture["experiment"]["name"]
                )
            ),
            **(
                {
                    "renamed_experiment_name": fixture["experiment"][
                        "renamed_name"
                    ],
                    "expected_rename_operations": fixture["workload"][
                        "expected_rename_operations"
                    ],
                }
                if rename_refinalize
                else {}
            ),
            **(
                {
                    "copy_experiment_name": fixture["experiment"][
                        "copy_name"
                    ],
                    "expected_editable_copy_operations": fixture[
                        "workload"
                    ]["expected_editable_copy_operations"],
                    "expected_printing_start_locks": fixture["workload"][
                        "expected_printing_start_locks"
                    ],
                }
                if post_start_lock
                else {}
            ),
            "plate_name": fixture["experiment"]["plate_name"],
            "expected_reaction_count": (
                fixture["experiment"]["refinalized_replicates"]
                if rename_refinalize
                else fixture["experiment"]["replicates"]
            ),
            "well_ids": (
                fixture["experiment"]["refinalized_expected_well_ids"]
                if rename_refinalize
                else fixture["experiment"]["expected_well_ids"]
            ),
            "speed_multiplier": config.speed_multiplier,
            "timeout_seconds": config.timeout_seconds,
        },
        "metrics": {
            "responsiveness": {"status": "not_applicable", "values": {}},
            "workflow": {
                "status": "measured",
                "values": {
                    "action_results": list(context.action_results),
                    "lifecycle_milestones": list(context.milestones),
                    "assertion_results": assertion_results,
                    "cleanup_results": list(context.cleanup_results),
                    "dialogs": list(context.dialogs),
                    "unexpected_dialogs": list(context.unexpected_dialogs),
                    "errors": list(context.errors),
                },
            },
            "queue": {
                "status": "not_applicable",
                "values": {
                    "simulator_cleanup": context.machine_cleanup,
                    "print_commands_executed": 0,
                },
            },
            "persistence": {
                "status": "measured" if prepared_evidence else "partial",
                "values": {
                    "prepared_bundle": prepared_evidence,
                    **(
                        {
                            "rename_refinalization": rename_evidence,
                            "refinalized_bundle": refinalized_evidence,
                        }
                        if rename_refinalize
                        else {}
                    ),
                    **(
                        {
                            "post_start_edit_boundary": (
                                post_start_evidence
                            )
                        }
                        if post_start_lock
                        else {}
                    ),
                    "reload_activation": reload_evidence,
                },
            },
            "resources": {"status": "not_applicable", "values": {}},
        },
        "artifacts": {
            "report_json": "report.json",
            "summary_text": "summary.txt",
            "event_trace": "events.jsonl",
            "stall_stacks": "stall_stacks.txt",
            "failure_traceback": (
                "failure_traceback.txt" if failure_text is not None else None
            ),
            "application_stdout": "application_stdout.log",
            "scenario_root": "scenario-root",
            "screenshots": {
                name: path.relative_to(report_dir).as_posix()
                for name, path in sorted(context.screenshots.items())
            },
        },
        "classification": {
            "status": "pass" if passed else "fail",
            "threshold_maturity": "informational",
            "reasons": reasons,
        },
        "limitations": [
            "The scenario validates the editor and authoritative application lifecycle without printing or connecting the simulated machine.",
            "The in-process simulator does not validate firmware, protocol framing, motion, pressure, cameras, balance behavior, or droplet quality.",
            "Speed multiplier configures only the isolated simulator and is not performance evidence.",
        ],
    }
    validate_report_v1(report)
    summary_path.write_text(_write_summary(report), encoding="utf-8")
    write_report_atomic(report_dir / "report.json", report)
    return report


def run_editor_create_finalize_scenario(
    config: EditorLifecycleScenarioConfig,
) -> dict[str, Any]:
    """Create, finalize, reload, and validate through the real editor."""

    if config.scenario_id != WORKLOAD_ID:
        raise ValueError(
            "run_editor_create_finalize_scenario requires "
            f"scenario_id={WORKLOAD_ID!r}"
        )
    return _run_editor_lifecycle_scenario(config)


def run_editor_prestart_rename_refinalize_scenario(
    config: EditorLifecycleScenarioConfig,
) -> dict[str, Any]:
    """Rename and refinalize a prepared, unstarted editor design."""

    if config.scenario_id != RENAME_WORKLOAD_ID:
        raise ValueError(
            "run_editor_prestart_rename_refinalize_scenario requires "
            f"scenario_id={RENAME_WORKLOAD_ID!r}"
        )
    return _run_editor_lifecycle_scenario(config)


def run_editor_post_start_lock_scenario(
    config: EditorLifecycleScenarioConfig,
) -> dict[str, Any]:
    """Prove an active source is immutable and its copy is fresh/editable."""

    if config.scenario_id != POST_START_LOCK_WORKLOAD_ID:
        raise ValueError(
            "run_editor_post_start_lock_scenario requires "
            f"scenario_id={POST_START_LOCK_WORKLOAD_ID!r}"
        )
    return _run_editor_lifecycle_scenario(config)


__all__ = [
    "ASSERTION_IDS",
    "EDITOR_FIXTURE_PATHS",
    "EditorLifecycleScenarioConfig",
    "FIXTURE_PATH",
    "POST_START_LOCK_ASSERTION_IDS",
    "POST_START_LOCK_FIXTURE_PATH",
    "POST_START_LOCK_SCENARIO_NAME",
    "POST_START_LOCK_WORKLOAD_ID",
    "RENAME_ASSERTION_IDS",
    "RENAME_FIXTURE_PATH",
    "RENAME_SCENARIO_NAME",
    "RENAME_WORKLOAD_ID",
    "SCENARIO_NAME",
    "SCENARIO_VERSION",
    "WORKLOAD_ID",
    "load_editor_create_finalize_fixture",
    "load_editor_post_start_lock_fixture",
    "load_editor_prestart_rename_refinalize_fixture",
    "run_editor_create_finalize_scenario",
    "run_editor_post_start_lock_scenario",
    "run_editor_prestart_rename_refinalize_scenario",
]
