"""Real-UI, hardware-isolated virtual workflow scenarios."""

from __future__ import annotations

import json
import math
import os
import sys
import time
import traceback
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[2]
UI_DIR = REPO_ROOT / "FreeRTOS-interface"
FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "virtual_print_array_96_v1.json"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "verification_reports" / "virtual_workflows"
WORKLOAD_ID = "virtual_print_array_96_v1"
SCENARIO_NAME = "virtual_print_array"
SCENARIO_VERSION = "1"
EXPECTED_START_DIALOGS = (
    "Start Print Array",
    "Evaporation Plate Dock Check",
)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))

from tools.virtual_workflows.metrics import (  # noqa: E402
    NamedPhaseRecorder,
    ProcessResourceSampler,
    QtEventLoopProbe,
)
from tools.virtual_workflows.report import (  # noqa: E402
    REPORT_SCHEMA_NAME,
    REPORT_SCHEMA_VERSION,
    collect_environment_identity,
    validate_report_v1,
    write_report_atomic,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _resolved_beneath(path: str | Path, root: str | Path) -> bool:
    candidate = Path(path).resolve()
    parent = Path(root).resolve()
    return candidate == parent or parent in candidate.parents


@dataclass(frozen=True)
class VirtualPrintArrayScenarioConfig:
    """Runtime controls for the versioned real-UI print-array scenario."""

    output_root: Path = DEFAULT_OUTPUT_ROOT
    fixture_path: Path = FIXTURE_PATH
    visible: bool = False
    speed_multiplier: float = 1.0
    timeout_seconds: float = 180.0
    inject_ui_stall_ms: int = 0
    inject_after_completion: int = 48
    run_id: str | None = None
    pi_preflight_path: Path | None = None
    pi_hardware_proof_path: Path | None = None

    def __post_init__(self):
        output_root = Path(self.output_root).resolve()
        fixture_path = Path(self.fixture_path).resolve()
        speed = float(self.speed_multiplier)
        timeout = float(self.timeout_seconds)
        stall = int(self.inject_ui_stall_ms)
        inject_after = int(self.inject_after_completion)
        pi_preflight_path = (
            Path(self.pi_preflight_path).resolve()
            if self.pi_preflight_path is not None
            else None
        )
        pi_hardware_proof_path = (
            Path(self.pi_hardware_proof_path).resolve()
            if self.pi_hardware_proof_path is not None
            else None
        )
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError("speed_multiplier must be finite and greater than zero")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout_seconds must be finite and greater than zero")
        if stall < 0:
            raise ValueError("inject_ui_stall_ms must be non-negative")
        if not 1 <= inject_after <= 96:
            raise ValueError("inject_after_completion must be between 1 and 96")
        if (pi_preflight_path is None) != (pi_hardware_proof_path is None):
            raise ValueError(
                "pi_preflight_path and pi_hardware_proof_path must be provided together"
            )
        object.__setattr__(self, "output_root", output_root)
        object.__setattr__(self, "fixture_path", fixture_path)
        object.__setattr__(self, "speed_multiplier", speed)
        object.__setattr__(self, "timeout_seconds", timeout)
        object.__setattr__(self, "inject_ui_stall_ms", stall)
        object.__setattr__(self, "inject_after_completion", inject_after)
        object.__setattr__(self, "pi_preflight_path", pi_preflight_path)
        object.__setattr__(
            self, "pi_hardware_proof_path", pi_hardware_proof_path
        )


class VirtualWorkflowScenarioError(RuntimeError):
    """A scenario setup or reporting failure with a stable CLI exit code."""

    def __init__(self, message: str, *, exit_code: int = 3):
        super().__init__(message)
        self.exit_code = int(exit_code)


def load_virtual_print_array_fixture(
    path: str | Path = FIXTURE_PATH,
) -> dict[str, Any]:
    """Load and strictly validate the tracked v1 fixture manifest."""

    fixture_path = Path(path)
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VirtualWorkflowScenarioError(
            f"could not load fixture {fixture_path}: {exc}"
        ) from exc
    expected_top = {
        "schema_version",
        "fixture_id",
        "plate",
        "workload",
        "stock",
        "fill_stock",
        "printer_head",
        "simulation",
    }
    if not isinstance(payload, dict) or set(payload) != expected_top:
        raise VirtualWorkflowScenarioError(
            "virtual print-array fixture has an invalid top-level contract"
        )
    if payload["schema_version"] != 1 or payload["fixture_id"] != WORKLOAD_ID:
        raise VirtualWorkflowScenarioError(
            "virtual print-array fixture identity/version is unsupported"
        )
    plate = payload["plate"]
    if (
        not isinstance(plate, dict)
        or plate.get("name") != "shallow-384_well_plate"
        or plate.get("rows") != 16
        or plate.get("columns") != 24
        or plate.get("included_rows") != ["A", "B", "C", "D"]
        or plate.get("serpentine") is not True
    ):
        raise VirtualWorkflowScenarioError("fixture plate contract is invalid")
    workload = payload["workload"]
    if workload != {
        "target_dispenses_per_well": 1,
        "completion_count": 96,
    }:
        raise VirtualWorkflowScenarioError("fixture workload contract is invalid")
    stock = payload["stock"]
    fill = payload["fill_stock"]
    head = payload["printer_head"]
    simulation = payload["simulation"]
    if (
        not isinstance(stock, dict)
        or stock.get("printing_mode") != "droplet"
        or float(stock.get("prepared_droplet_volume_nL", -1)) != 5.0
        or float(stock.get("droplet_volume_nL", -1)) != 10.0
        or not isinstance(fill, dict)
        or fill.get("factor_name") != "Water"
        or fill.get("units") != "--"
        or fill.get("target_dispenses_per_well") != 0
        or not isinstance(head, dict)
        or not str(head.get("printer_head_id") or "")
        or int(head.get("print_pulse_width_us", 0)) != 1300
        or float(head.get("print_pressure_psi", -1)) <= 0
        or float(head.get("initial_volume_uL", -1)) <= 0
        or not isinstance(simulation, dict)
        or int(simulation.get("dispense_frequency_hz", 0)) <= 0
        or int(simulation.get("lookahead_wells", 0)) != 2
    ):
        raise VirtualWorkflowScenarioError("fixture stock/head contract is invalid")
    return payload


def fixture_well_ids(fixture: dict[str, Any]) -> tuple[str, ...]:
    """Expand the fixture's four rows into deterministic row-serpentine order."""

    columns = int(fixture["plate"]["columns"])
    result: list[str] = []
    for index, row in enumerate(fixture["plate"]["included_rows"]):
        values = range(1, columns + 1)
        if index % 2:
            values = range(columns, 0, -1)
        result.extend(f"{row}{column}" for column in values)
    if len(result) != 96 or len(set(result)) != 96:
        raise VirtualWorkflowScenarioError(
            "fixture expansion did not produce 96 unique wells"
        )
    return tuple(result)


def _stock_id(spec: dict[str, Any]) -> str:
    return (
        f"{spec['factor_name']}_{float(spec['concentration']):.2f}_"
        f"{spec['units']}"
    )


def _create_prepared_fixture(
    experiment_dir: Path,
    fixture: dict[str, Any],
) -> dict[str, Any]:
    from ExecutionPlan import ProgressExecutionReference, save_execution_plan
    from ExecutionPlanRevision import persist_immutable_revision
    from InitialExecutionPlan import build_initial_execution_plan

    if experiment_dir.exists():
        raise VirtualWorkflowScenarioError(
            f"scenario experiment directory already exists: {experiment_dir}"
        )
    experiment_dir.mkdir(parents=True)
    wells = fixture_well_ids(fixture)
    stock = fixture["stock"]
    fill = fixture["fill_stock"]
    stock_id = _stock_id(stock)
    fill_stock_id = _stock_id(fill)
    droplet_volume = float(stock["droplet_volume_nL"])
    prepared_droplet_volume = float(stock["prepared_droplet_volume_nL"])
    target = int(fixture["workload"]["target_dispenses_per_well"])
    prepared_target = int(round((droplet_volume * target) / prepared_droplet_volume))
    design = {
        "schema_version": 2,
        "metadata": {
            "name": WORKLOAD_ID,
            "target_reaction_volume_nL": droplet_volume * target,
            "final_reaction_volume_nL": droplet_volume * target,
            "printed_volume_tolerance_nL": 0.0,
            "fill_reagent_name": fill["factor_name"],
            "fill_droplet_volume_nL": float(fill["droplet_volume_nL"]),
            "fill_printing_mode": fill["printing_mode"],
            "plate_format": fixture["plate"]["name"],
            "start_row": 0,
            "start_col": 0,
            "replicates": len(wells),
            "randomize_assignments": False,
        },
        "factors": [
            {
                "name": stock["factor_name"],
                "kind": "additive",
                "options": [
                    {
                        "name": stock["factor_name"],
                        "targets": [float(stock["concentration"])],
                        "units": stock["units"],
                        "droplet_nL": droplet_volume,
                        "printing_mode": stock["printing_mode"],
                        "intended_droplet_nL": droplet_volume,
                    }
                ],
            }
        ],
    }
    stock_rows = [
        {
            "factor_name": stock["factor_name"],
            "option_name": None,
            "stock_concentration": float(stock["concentration"]),
            "units": stock["units"],
            "printing_mode": stock["printing_mode"],
            "droplet_volume_nL": prepared_droplet_volume,
        },
        {
            "factor_name": fill["factor_name"],
            "option_name": None,
            "stock_concentration": float(fill["concentration"]),
            "units": fill["units"],
            "printing_mode": fill["printing_mode"],
            "droplet_volume_nL": float(fill["droplet_volume_nL"]),
        },
    ]
    assigned_wells = [
        {
            "well_id": well_id,
            "reaction_id": f"R{index}",
            "target_dispenses": {
                stock_id: prepared_target,
                fill_stock_id: int(fill["target_dispenses_per_well"]),
            },
        }
        for index, well_id in enumerate(wells, start=1)
    ]
    plan = build_initial_execution_plan(
        design_payload=design,
        plate_name=fixture["plate"]["name"],
        plate_rows=int(fixture["plate"]["rows"]),
        plate_columns=int(fixture["plate"]["columns"]),
        stock_rows=stock_rows,
        assigned_wells=assigned_wells,
        plan_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"labcraft:{WORKLOAD_ID}")),
        timestamp_utc="2026-07-23T00:00:00Z",
    )
    design_path = experiment_dir / "experiment_design.json"
    design_path.write_text(json.dumps(design, indent=2) + "\n", encoding="utf-8")
    save_execution_plan(experiment_dir / "execution_plan.json", plan)
    persist_immutable_revision(experiment_dir / "execution_plan_revisions", plan)
    progress = {
        well.well_id: {
            "reaction_id": well.reaction_id,
            "reagents": {
                dispense.stock_id: {
                    "target_droplets": dispense.target_dispenses,
                    "added_droplets": 0,
                }
                for dispense in well.dispenses
            },
            "completed": False,
        }
        for well in plan.wells
    }
    progress["__plate__"] = {
        "name": fixture["plate"]["name"],
        "rows": int(fixture["plate"]["rows"]),
        "columns": int(fixture["plate"]["columns"]),
        "schema_version": 1,
    }
    progress["__execution__"] = ProgressExecutionReference(
        plan.plan_id,
        plan.plan_revision,
    ).to_dict()
    (experiment_dir / "progress.json").write_text(
        json.dumps(progress, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "experiment_dir": experiment_dir,
        "design_path": design_path,
        "stock_id": stock_id,
        "fill_stock_id": fill_stock_id,
        "well_ids": wells,
        "plan_id": plan.plan_id,
    }


class _InstanceInstrumentation:
    def __init__(
        self,
        phases: NamedPhaseRecorder,
        *,
        inject_ms: int,
        inject_after_completion: int,
        completed_count: Callable[[], int],
    ):
        self.phases = phases
        self.inject_ms = int(inject_ms)
        self.inject_after_completion = int(inject_after_completion)
        self.completed_count = completed_count
        self.injected = False
        self._originals: list[tuple[Any, str, Any]] = []
        self._connected_slots: list[tuple[Any, Any, str, Any, Any]] = []

    def wrap(
        self,
        obj: Any,
        method_name: str,
        phase_name: str,
        *,
        after: Callable[[], None] | None = None,
    ) -> None:
        original = getattr(obj, method_name)

        def measured(*args, **kwargs):
            with self.phases.phase(phase_name):
                result = original(*args, **kwargs)
            if after is not None:
                after()
            return result

        self._originals.append((obj, method_name, original))
        setattr(obj, method_name, measured)

    def wrap_connected_slot(
        self,
        obj: Any,
        method_name: str,
        signal: Any,
        phase_name: str,
    ) -> None:
        """Measure a slot already connected before instrumentation was installed."""

        original = getattr(obj, method_name)

        def measured(*args, **kwargs):
            with self.phases.phase(phase_name):
                return original(*args, **kwargs)

        try:
            signal.disconnect(original)
        except (RuntimeError, TypeError) as exc:
            raise RuntimeError(
                f"could not instrument connected slot {method_name}"
            ) from exc
        try:
            setattr(obj, method_name, measured)
            signal.connect(measured)
        except Exception:
            setattr(obj, method_name, original)
            signal.connect(original)
            raise
        self._connected_slots.append(
            (signal, measured, method_name, obj, original)
        )

    def maybe_inject(self) -> None:
        if (
            self.inject_ms <= 0
            or self.injected
            or self.completed_count() < self.inject_after_completion
        ):
            return
        self.injected = True
        with self.phases.phase(
            "injected_ui_stall",
            {
                "kind": "injected_qt_stall",
                "requested_duration_ms": self.inject_ms,
                "after_completion": self.inject_after_completion,
            },
        ):
            time.sleep(self.inject_ms / 1000.0)

    def restore(self) -> None:
        for signal, measured, name, obj, original in reversed(
            self._connected_slots
        ):
            try:
                signal.disconnect(measured)
            except (RuntimeError, TypeError):
                pass
            try:
                setattr(obj, name, original)
                signal.connect(original)
            except (RuntimeError, TypeError):
                pass
        self._connected_slots.clear()
        for obj, name, original in reversed(self._originals):
            try:
                setattr(obj, name, original)
            except (RuntimeError, TypeError):
                pass
        self._originals.clear()


def _install_instrumentation(
    phases: NamedPhaseRecorder,
    *,
    experiment_model: Any,
    controller: Any,
    well_plate_widget: Any,
    pressure_plot_widget: Any,
    pressure_updated_signal: Any,
    inject_ms: int,
    inject_after_completion: int,
    completed_count: Callable[[], int],
) -> _InstanceInstrumentation:
    instrumentation = _InstanceInstrumentation(
        phases,
        inject_ms=inject_ms,
        inject_after_completion=inject_after_completion,
        completed_count=completed_count,
    )
    for method, phase in (
        ("begin_execution_print_intent", "persistence.begin_intent"),
        ("attach_execution_print_command", "persistence.attach_sequence"),
        ("create_progress_file", "persistence.write_progress"),
        ("complete_execution_print_intent", "persistence.complete_intent"),
    ):
        instrumentation.wrap(experiment_model, method, phase)
    instrumentation.wrap(
        controller,
        "_handle_array_well_complete",
        "controller.well_completion",
        after=instrumentation.maybe_inject,
    )
    instrumentation.wrap(
        well_plate_widget,
        "update_well_colors",
        "ui.well_plate_update",
    )
    instrumentation.wrap(
        well_plate_widget,
        "update_grid",
        "ui.well_plate_rebuild",
    )
    instrumentation.wrap_connected_slot(
        pressure_plot_widget,
        "update_pressure",
        pressure_updated_signal,
        "ui.pressure_render",
    )
    return instrumentation


def _wait_until(app: Any, predicate: Callable[[], bool], timeout_s: float, label: str):
    from PySide6 import QtCore

    deadline = time.perf_counter() + float(timeout_s)
    while time.perf_counter() < deadline:
        app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 10)
        if predicate():
            return
        QtCore.QThread.msleep(1)
    app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 10)
    if not predicate():
        raise RuntimeError(f"timed out waiting for {label}")


def _capture_window(view: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = view.grab()
    if image.isNull() or not image.save(str(path), "PNG"):
        raise RuntimeError(f"could not capture screenshot {path.name}")
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"screenshot {path.name} is empty")


def _write_event_trace(path: Path, events: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for event in events:
            handle.write(json.dumps(event, sort_keys=True, default=str) + "\n")


def _relative(path: Path, report_dir: Path) -> str:
    return path.resolve().relative_to(report_dir.resolve()).as_posix()


def _validate_completed_scenario(
    *,
    experiment_model: Any,
    fixture_info: dict[str, Any],
    well_updates: list[str],
    array_states: list[str],
    array_complete_count: int,
    errors: list[dict[str, Any]],
    unexpected_dialogs: list[dict[str, Any]],
    starvation_events: list[dict[str, Any]],
) -> dict[str, Any]:
    from AuthoritativeExecutionLoad import inspect_authoritative_execution
    from ExecutionPlan import ExecutionPlanState, load_execution_plan
    from ExecutionResumeStore import load_execution_resume

    experiment_dir = Path(fixture_info["experiment_dir"])
    expected_wells = tuple(fixture_info["well_ids"])
    stock_id = fixture_info["stock_id"]
    checkpoint = load_execution_resume(experiment_model.execution_resume_file_path)
    intents = list(checkpoint.intents)
    sequences = [intent.command_seq32 for intent in intents]
    completed_well_updates = [
        well_id for well_id in well_updates if well_id in set(expected_wells)
    ]
    design = json.loads(
        Path(experiment_model.experiment_file_path).read_text(encoding="utf-8")
    )
    bundle = inspect_authoritative_execution(experiment_dir, design)
    terminal_plan = load_execution_plan(experiment_model.execution_plan_file_path)
    checks = {
        "checkpoint_clean": checkpoint.state == "clean",
        "intent_count_exact": len(intents) == 96,
        "intent_sequences_unique_monotonic": (
            len(sequences) == 96
            and all(isinstance(value, int) for value in sequences)
            and sequences == sorted(set(sequences))
        ),
        "all_intents_completed": all(
            intent.status == "completed" for intent in intents
        ),
        "authoritative_bundle_valid": bool(bundle.valid),
        "terminal_plan_completed": terminal_plan.state is ExecutionPlanState.COMPLETED,
        "array_complete_once": array_complete_count == 1,
        "ui_running_then_idle": (
            "running" in array_states
            and array_states[-1] == "idle"
            and array_states.index("running") < len(array_states) - 1
        ),
        "well_updates_exact": (
            len(completed_well_updates) == 96
            and set(completed_well_updates) == set(expected_wells)
            and all(count == 1 for count in Counter(completed_well_updates).values())
        ),
        "no_errors": not errors,
        "no_unexpected_dialogs": not unexpected_dialogs,
        "no_lookahead_starvation": not starvation_events,
    }
    targets_match = True
    for well_id in expected_wells:
        entry = bundle.progress_wells.get(well_id, {})
        reagent = (entry.get("reagents") or {}).get(stock_id, {})
        if (
            int(reagent.get("target_droplets", -1)) != 1
            or int(reagent.get("added_droplets", -1)) != 1
        ):
            targets_match = False
            break
    checks["targets_match_progress"] = targets_match
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise RuntimeError("scenario invariants failed: " + ", ".join(failed))
    return {
        "checks": checks,
        "checkpoint_state": checkpoint.state,
        "intent_count": len(intents),
        "intent_command_sequences": sequences,
        "terminal_plan_state": terminal_plan.state.value,
        "terminal_plan_revision": terminal_plan.plan_revision,
        "file_sizes_bytes": {
            path.name: path.stat().st_size
            for path in (
                experiment_dir / "execution_plan.json",
                experiment_dir / "progress.json",
                experiment_dir / "execution_resume.json",
                experiment_dir / "execution_calibrations.json",
            )
        },
    }


def _summary_text(report: dict[str, Any]) -> str:
    workflow = report["metrics"]["workflow"]["values"]
    responsiveness = report["metrics"]["responsiveness"]["values"]
    queue = report["metrics"]["queue"]["values"]
    persistence = report["metrics"]["persistence"]["values"]
    gap = responsiveness.get("event_loop_gap_ms") or {}
    pressure_render = (
        responsiveness.get("phase_timings", {})
        .get("duration_by_name_ms", {})
        .get("ui.pressure_render", {})
    )
    lines = [
        f"Scenario: {report['run']['scenario_name']} v{report['run']['scenario_version']}",
        f"Workload: {report['workload']['workload_id']}",
        f"Run mode: {report['run']['run_mode']}",
        f"Classification: {report['classification']['status']}",
        f"Duration: {report['run']['duration_ms']:.3f} ms",
        (
            "Wells: "
            f"{workflow.get('completed_well_count', 0)}/"
            f"{workflow.get('expected_well_count', 96)}"
        ),
        f"Array complete signals: {workflow.get('array_complete_count', 0)}",
        f"Maximum event-loop gap: {gap.get('maximum')} ms",
        (
            "Pressure renders: "
            f"{pressure_render.get('count', 0)}; "
            f"p95 {pressure_render.get('p95')} ms; "
            f"max {pressure_render.get('maximum')} ms"
        ),
        f"Queue starvation events: {queue.get('unexpected_starvation_count', 0)}",
        f"Execution intents: {persistence.get('intent_count', 0)}",
        (
            "Injected stall: "
            f"{responsiveness.get('injected_stall_assessment', {}).get('decision', 'not_requested')}"
        ),
    ]
    pi_sil = report["safety"].get("pi_sil")
    if isinstance(pi_sil, dict):
        lines.extend(
            [
                f"Pi sandbox: {pi_sil.get('sandbox_method')}",
                f"Pi hardware proof: {pi_sil.get('proof_sha256')}",
            ]
        )
    for reason in report["classification"]["reasons"]:
        lines.append(f"Reason: {reason}")
    return "\n".join(lines) + "\n"


def run_virtual_print_array_scenario(
    config: VirtualPrintArrayScenarioConfig,
) -> dict[str, Any]:
    """Run the versioned real-UI scenario and return its validated v1 report."""

    identity = collect_environment_identity(REPO_ROOT)
    qt_identity = identity["environment"]["qt"]
    if qt_identity.get("binding") != "real":
        raise VirtualWorkflowScenarioError(
            "the real-UI scenario requires an installed real PySide6 binding"
        )
    pi_preflight: dict[str, Any] | None = None
    pi_hardware_proof: dict[str, Any] | None = None
    pi_environment: dict[str, Any] | None = None
    pi_safety: dict[str, Any] | None = None
    if config.pi_preflight_path is not None:
        from tools.virtual_workflows.pi_sil import (
            PiSilError,
            load_and_validate_pi_evidence,
            pi_report_identity,
        )

        try:
            pi_preflight, pi_hardware_proof = load_and_validate_pi_evidence(
                config.pi_preflight_path,
                config.pi_hardware_proof_path,
                expected_qt_platform=str(qt_identity.get("platform")),
            )
        except PiSilError as exc:
            raise VirtualWorkflowScenarioError(
                f"Pi SIL evidence is invalid: {exc}"
            ) from exc
        if identity["source"].get("git_commit") != pi_preflight.get(
            "source_commit"
        ):
            raise VirtualWorkflowScenarioError(
                "Pi SIL preflight source commit does not match the scenario source"
            )
        expected_environment = {
            "operating_system": pi_preflight.get("operating_system"),
            "architecture": pi_preflight.get("architecture"),
            "python_version": pi_preflight.get("python_version"),
            "python_executable": pi_preflight.get("python_executable"),
        }
        for field, expected in expected_environment.items():
            if identity["environment"].get(field) != expected:
                raise VirtualWorkflowScenarioError(
                    f"Pi SIL preflight {field} does not match the scenario process"
                )
        pi_environment, pi_safety = pi_report_identity(
            pi_preflight,
            pi_hardware_proof,
            config.pi_hardware_proof_path,
        )
        identity["environment"]["target_pi"] = pi_environment

    fixture = load_virtual_print_array_fixture(config.fixture_path)
    expected_wells = fixture_well_ids(fixture)
    stamp = _run_stamp()
    short_commit = identity["source"].get("git_short_commit") or "unknown"
    run_id = config.run_id or str(uuid.uuid4())
    report_dir = (
        config.output_root
        / WORKLOAD_ID
        / f"{stamp}_{short_commit}"
    ).resolve()
    report_dir.mkdir(parents=True, exist_ok=False)
    scenario_root = report_dir / "scenario-root"
    screenshots_dir = report_dir / "screenshots"
    scenario_root.mkdir()
    screenshots_dir.mkdir()
    if not _resolved_beneath(scenario_root, report_dir):
        raise VirtualWorkflowScenarioError("scenario root escaped its report directory")

    started_utc = _utc_now()
    started_ns = time.perf_counter_ns()
    events: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    dialogs: list[dict[str, Any]] = []
    unexpected_dialogs: list[dict[str, Any]] = []
    well_updates: list[str] = []
    array_states: list[str] = ["idle"]
    command_events: list[dict[str, Any]] = []
    starvation_events: list[dict[str, Any]] = []
    screenshots: dict[str, Path] = {}
    array_complete_count = 0
    paint_event_count = 0
    fixture_info: dict[str, Any] | None = None
    validation: dict[str, Any] = {}
    failure_text: str | None = None
    phases = NamedPhaseRecorder(max_records=50_000)
    resources = ProcessResourceSampler(max_samples=100_000)
    probe = QtEventLoopProbe(
        heartbeat_interval_ms=10,
        stack_capture_ms=250.0,
        observer_interval_ms=5,
        resource_interval_ms=100,
        phase_recorder=phases,
        resource_sampler=resources,
    )
    components = None
    instrumentation = None
    dialog_timer = None
    paint_filter = None
    app = None
    probe_started = False
    machine_cleanup = {
        "command_timer_active": None,
        "connection_timer_active": None,
        "deferred_timer_count": None,
    }

    try:
        from PySide6 import QtCore, QtTest, QtWidgets
        import ApplicationComposition as composition
        from ExecutionPlan import ExecutionPlanState
        from hardware.profile import CURRENT_PROFILE
        from simulation import (
            SIMULATED_PORT,
            SimulationConfig,
            SimulationTimingPolicy,
            make_simulated_machine_factory,
        )

        app = QtWidgets.QApplication.instance()
        if app is None:
            app = QtWidgets.QApplication(["labcraft-virtual-workflow"])
        app.setQuitOnLastWindowClosed(False)

        simulation_config = SimulationConfig(
            timing=SimulationTimingPolicy(
                speed_multiplier=config.speed_multiplier,
            ),
            completed_history_limit=512,
            event_history_limit=4096,
        )
        dependencies = composition.simulation_dependencies(
            scenario_root,
            machine_factory=make_simulated_machine_factory(simulation_config),
        )
        for root in (
            dependencies.roots.config_root,
            dependencies.roots.experiments_root,
            dependencies.roots.calibration_memory_root,
        ):
            if not _resolved_beneath(root, scenario_root):
                raise RuntimeError(f"simulation root escaped scenario root: {root}")

        fixture_info = _create_prepared_fixture(
            dependencies.roots.experiments_root / WORKLOAD_ID,
            fixture,
        )
        components = composition.build_application_components(
            CURRENT_PROFILE,
            dependencies,
        )
        model = components.model
        machine = components.machine
        controller = components.controller
        view = components.view
        experiment_model = model.experiment_model

        experiment_model.load_experiment(
            str(fixture_info["design_path"]),
            str(fixture_info["experiment_dir"]),
        )
        eligibility = model.load_authoritative_execution_runtime()
        if eligibility["status"] not in {"ready_to_start", "ready_to_resume"}:
            raise RuntimeError(
                f"unexpected execution activation eligibility: {eligibility['status']}"
            )

        stock_id = fixture_info["stock_id"]
        stock_slot = None
        for index, slot in enumerate(model.rack_model.slots):
            head = getattr(slot, "printer_head", None)
            if head is not None and head.get_stock_id() == stock_id:
                stock_slot = index
                break
        if stock_slot is None:
            raise RuntimeError("fixture printer head was not assigned to a rack slot")
        model.rack_model.confirm_slot(stock_slot)
        model.rack_model.transfer_to_gripper(stock_slot)
        printer_head = model.rack_model.get_gripper_printer_head()
        head_spec = fixture["printer_head"]
        printer_head.set_identity_metadata(
            printer_head_id=head_spec["printer_head_id"],
            display_name="Virtual workflow head",
            tags=["simulation", WORKLOAD_ID],
        )
        printer_head.set_absolute_volume(float(head_spec["initial_volume_uL"]))
        printer_head.target_droplet_volume = float(
            fixture["stock"]["droplet_volume_nL"]
        )

        calibration = experiment_model.apply_execution_calibration(
            stock_id=stock_id,
            new_effective_volume_nL=float(
                fixture["stock"]["droplet_volume_nL"]
            ),
            printing_mode=fixture["stock"]["printing_mode"],
            printer_head_id=head_spec["printer_head_id"],
            factor_name=fixture["stock"]["factor_name"],
            option_name=None,
            is_fill=False,
            calibration_payload={
                "measured_volume_nL": float(
                    fixture["stock"]["droplet_volume_nL"]
                ),
                "pw_us": int(head_spec["print_pulse_width_us"]),
                "pressure_psi": float(head_spec["print_pressure_psi"]),
                "run_id": WORKLOAD_ID,
                "phase": "canned_virtual_calibration",
                "timestamp": "2026-07-23T00:00:00Z",
                "source_row_fingerprint": [
                    WORKLOAD_ID,
                    int(head_spec["print_pulse_width_us"]),
                    float(head_spec["print_pressure_psi"]),
                ],
                "original_printing_mode": fixture["stock"]["printing_mode"],
            },
            timestamp_utc="2026-07-23T00:00:00Z",
        )
        if (
            calibration["plan"].state is not ExecutionPlanState.ACTIVE
            or calibration["record"]["printer_head_id"]
            != head_spec["printer_head_id"]
        ):
            raise RuntimeError("canned execution calibration was not activated")

        def record_event(kind: str, **values: Any) -> None:
            events.append(
                {
                    "kind": kind,
                    "monotonic_ns": time.perf_counter_ns(),
                    **values,
                }
            )

        def on_well_update(well_id: str) -> None:
            text = str(well_id)
            well_updates.append(text)
            record_event("well_update", well_id=text)

        def on_array_state(state: str) -> None:
            value = str(state)
            array_states.append(value)
            record_event("array_state", state=value)

        def on_array_complete() -> None:
            nonlocal array_complete_count
            array_complete_count += 1
            record_event("array_complete", count=array_complete_count)

        def on_error(source: str, *args: Any) -> None:
            entry = {
                "source": source,
                "arguments": [str(value) for value in args],
            }
            errors.append(entry)
            record_event("error", **entry)

        def on_command(payload: dict[str, Any]) -> None:
            item = dict(payload)
            command_events.append(item)
            record_event("command", **item)

        model.well_plate.well_state_changed_signal.connect(on_well_update)
        controller.array_state_changed.connect(on_array_state)
        controller.array_complete.connect(on_array_complete)
        controller.error_occurred_signal.connect(
            lambda *args: on_error("controller", *args)
        )
        machine.error_occurred.connect(lambda *args: on_error("machine", *args))
        machine.simulation_faulted.connect(
            lambda *args: on_error("simulation_fault", *args)
        )
        machine.command_lifecycle_changed.connect(on_command)

        def on_queue_drained() -> None:
            completed = len(
                [well for well in well_updates if well in set(expected_wells)]
            )
            state = controller.get_array_run_state()
            if state == "running" and completed < len(expected_wells):
                item = {
                    "completed_wells": completed,
                    "array_state": state,
                }
                starvation_events.append(item)
                record_event("unexpected_queue_starvation", **item)

        machine.command_queue.commands_completed.connect(on_queue_drained)

        class PaintFilter(QtCore.QObject):
            def eventFilter(self, watched, event):
                nonlocal paint_event_count
                if event.type() == QtCore.QEvent.Type.Paint:
                    root = view.well_plate_widget
                    if watched is root or (
                        isinstance(watched, QtWidgets.QWidget)
                        and root.isAncestorOf(watched)
                    ):
                        paint_event_count += 1
                return False

        paint_filter = PaintFilter(app)
        app.installEventFilter(paint_filter)

        handled_dialogs: set[int] = set()

        def inspect_dialogs() -> None:
            for widget in app.topLevelWidgets():
                if not isinstance(widget, QtWidgets.QMessageBox) or not widget.isVisible():
                    continue
                identifier = id(widget)
                if identifier in handled_dialogs:
                    continue
                handled_dialogs.add(identifier)
                entry = {
                    "title": widget.windowTitle(),
                    "text": widget.text(),
                }
                dialogs.append(entry)
                record_event("dialog", **entry)
                if entry["title"] in EXPECTED_START_DIALOGS:
                    button = widget.button(QtWidgets.QMessageBox.StandardButton.Yes)
                    if button is not None:
                        QtTest.QTest.mouseClick(
                            button,
                            QtCore.Qt.MouseButton.LeftButton,
                        )
                        continue
                unexpected_dialogs.append(entry)
                widget.reject()

        dialog_timer = QtCore.QTimer(app)
        dialog_timer.setInterval(5)
        dialog_timer.timeout.connect(inspect_dialogs)
        dialog_timer.start()

        completed_count = lambda: len(
            [well for well in well_updates if well in set(expected_wells)]
        )
        instrumentation = _install_instrumentation(
            phases,
            experiment_model=experiment_model,
            controller=controller,
            well_plate_widget=view.well_plate_widget,
            pressure_plot_widget=view.pressure_box,
            pressure_updated_signal=model.machine_model.pressure_updated,
            inject_ms=config.inject_ui_stall_ms,
            inject_after_completion=config.inject_after_completion,
            completed_count=completed_count,
        )

        if config.visible:
            view.show()
        else:
            view.show()
        app.processEvents()
        probe.start(app)
        probe_started = True

        if machine.connect_board(SIMULATED_PORT) is False:
            raise RuntimeError("simulator rejected the sentinel port")
        _wait_until(
            app,
            lambda: model.machine_model.is_connected(),
            5.0,
            "simulated connection",
        )
        controller.toggle_motors()
        controller.home_machine()
        controller.set_print_pulse_width(
            int(head_spec["print_pulse_width_us"]),
            update_model=True,
        )
        controller.set_absolute_print_pressure(
            float(head_spec["print_pressure_psi"])
        )
        controller.set_dispense_frequency_hz(
            int(fixture["simulation"]["dispense_frequency_hz"])
        )
        controller.toggle_regulation()
        _wait_until(app, machine.check_if_all_completed, 10.0, "machine readiness")
        _wait_until(
            app,
            lambda: (
                model.machine_model.motors_are_enabled()
                and model.machine_model.motors_are_homed()
                and model.machine_model.regulating_print_pressure
            ),
            5.0,
            "ready model state",
        )
        preflight = controller.get_print_array_imaging_calibration_preflight()
        if not preflight.get("ok"):
            raise RuntimeError(
                "canned imaging-calibration preflight failed: "
                + str(preflight.get("message") or preflight.get("code"))
            )

        screenshots["ready"] = screenshots_dir / "ready.png"
        _capture_window(view, screenshots["ready"])
        record_event("milestone", name="ready")

        QtTest.QTest.mouseClick(
            view.well_plate_widget.start_print_array_button,
            QtCore.Qt.MouseButton.LeftButton,
        )
        _wait_until(
            app,
            lambda: "running" in array_states or bool(errors),
            10.0,
            "array running state",
        )
        if errors:
            raise RuntimeError(f"array start emitted an error: {errors[-1]}")
        screenshots["printing"] = screenshots_dir / "printing.png"
        _capture_window(view, screenshots["printing"])
        record_event("milestone", name="printing")

        deadline = max(0.1, config.timeout_seconds - 10.0)
        _wait_until(
            app,
            lambda: completed_count() >= 48 or bool(errors),
            deadline,
            "48 completed wells",
        )
        if errors:
            raise RuntimeError(f"array execution emitted an error: {errors[-1]}")
        screenshots["mid_array"] = screenshots_dir / "mid_array.png"
        _capture_window(view, screenshots["mid_array"])
        record_event("milestone", name="mid_array", completed=completed_count())

        elapsed_seconds = (time.perf_counter_ns() - started_ns) / 1_000_000_000.0
        remaining_timeout = max(0.1, config.timeout_seconds - elapsed_seconds)
        _wait_until(
            app,
            lambda: array_complete_count == 1 or bool(errors),
            remaining_timeout,
            "array completion",
        )
        if errors:
            raise RuntimeError(f"array completion emitted an error: {errors[-1]}")
        _wait_until(
            app,
            lambda: controller.get_array_run_state() == "idle",
            5.0,
            "idle array state",
        )
        app.processEvents()
        screenshots["completed"] = screenshots_dir / "completed.png"
        _capture_window(view, screenshots["completed"])
        record_event("milestone", name="completed")

        validation = _validate_completed_scenario(
            experiment_model=experiment_model,
            fixture_info=fixture_info,
            well_updates=well_updates,
            array_states=array_states,
            array_complete_count=array_complete_count,
            errors=errors,
            unexpected_dialogs=unexpected_dialogs,
            starvation_events=starvation_events,
        )
    except Exception:
        failure_text = traceback.format_exc()
        if components is not None and app is not None:
            try:
                screenshots["failure"] = screenshots_dir / "failure.png"
                _capture_window(components.view, screenshots["failure"])
            except Exception:
                failure_text += "\nFailure screenshot error:\n" + traceback.format_exc()
    finally:
        if dialog_timer is not None:
            dialog_timer.stop()
        if app is not None and paint_filter is not None:
            try:
                app.removeEventFilter(paint_filter)
            except RuntimeError:
                pass
        if instrumentation is not None:
            instrumentation.restore()
        if probe_started:
            try:
                probe.stop()
            except Exception:
                cleanup_failure = "Probe cleanup error:\n" + traceback.format_exc()
                failure_text = (
                    f"{failure_text}\n{cleanup_failure}"
                    if failure_text
                    else cleanup_failure
                )
        if components is not None:
            machine = components.machine
            try:
                machine.disconnect_board()
            except Exception:
                cleanup_failure = "Machine cleanup error:\n" + traceback.format_exc()
                failure_text = (
                    f"{failure_text}\n{cleanup_failure}"
                    if failure_text
                    else cleanup_failure
                )
            machine_cleanup = {
                "command_timer_active": bool(
                    getattr(machine, "_command_timer", None)
                    and machine._command_timer.isActive()
                ),
                "connection_timer_active": bool(
                    getattr(machine, "_connection_timer", None)
                    and machine._connection_timer.isActive()
                ),
                "deferred_timer_count": len(
                    getattr(machine, "_deferred_timers", set())
                ),
            }
            components.close()
        if app is not None:
            app.processEvents()

    ended_ns = time.perf_counter_ns()
    ended_utc = _utc_now()
    duration_ms = (ended_ns - started_ns) / 1_000_000.0
    probe_snapshot = probe.snapshot()
    resource_snapshot = resources.snapshot()
    completed_updates = [
        well for well in well_updates if well in set(expected_wells)
    ]
    lifecycle_counts = Counter(
        str(event.get("event")) for event in command_events
    )
    queue_depths = [
        int(event.get("queue_depth", 0)) for event in command_events
    ]
    injected_candidates = [
        event
        for event in probe_snapshot.get("stall_events", [])
        if (event.get("phase") or {}).get("name") == "injected_ui_stall"
    ]
    injected_stacks = [
        capture
        for capture in probe_snapshot.get("stack_captures", [])
        if (capture.get("phase") or {}).get("name") == "injected_ui_stall"
    ]
    injection_requested = config.inject_ui_stall_ms > 0
    injection_detected = bool(
        injected_candidates
        and max(
            event.get("event_loop_gap_ms", 0.0)
            for event in injected_candidates
        )
        >= config.inject_ui_stall_ms * 0.60
    )
    injection_stack_captured = bool(injected_stacks)
    if (
        failure_text is None
        and injection_requested
        and not (injection_detected and injection_stack_captured)
    ):
        failure_text = (
            "Injected UI stall evidence was incomplete: "
            f"detected={injection_detected}, stack_captured={injection_stack_captured}"
        )
    if (
        failure_text is None
        and any(
            (
                machine_cleanup["command_timer_active"],
                machine_cleanup["connection_timer_active"],
                machine_cleanup["deferred_timer_count"],
            )
        )
    ):
        failure_text = f"simulator teardown left active timers: {machine_cleanup}"

    status = "fail" if failure_text else "pass"
    reasons = (
        [failure_text.splitlines()[-1] if failure_text else "scenario failed"]
        if failure_text
        else ["All functional, persistence, UI, and simulation-safety invariants passed."]
    )
    response_values = {
        **probe_snapshot,
        "well_plate_paint_event_count": paint_event_count,
        "injected_stall_assessment": {
            "requested": injection_requested,
            "requested_duration_ms": config.inject_ui_stall_ms,
            "after_completion": config.inject_after_completion,
            "detected": injection_detected,
            "stack_captured": injection_stack_captured,
            "decision": (
                "detected"
                if injection_requested and injection_detected and injection_stack_captured
                else "missing"
                if injection_requested
                else "not_requested"
            ),
        },
    }
    platform_name = str(qt_identity.get("platform") or "unknown")
    operating_system = str(identity["environment"].get("operating_system") or "")
    architecture = str(identity["environment"].get("architecture") or "").lower()
    is_pi_process = pi_preflight is not None or (
        operating_system == "Linux" and architecture in {"aarch64", "arm64"}
    )
    run_mode = (
        f"{platform_name}_pi_sil"
        if is_pi_process
        else "visible_windows_sil"
        if config.visible
        else "offscreen_windows_sil"
    )
    safety_values = {
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
            scenario_root,
            report_dir,
        ),
    }
    if pi_safety is not None:
        safety_values["pi_sil"] = pi_safety

    report = {
        "schema_name": REPORT_SCHEMA_NAME,
        "schema_version": REPORT_SCHEMA_VERSION,
        "run": {
            "run_id": run_id,
            "scenario_name": SCENARIO_NAME,
            "scenario_version": SCENARIO_VERSION,
            "run_mode": run_mode,
            "timing_policy": (
                f"simulated_command_durations_x{config.speed_multiplier:g}"
            ),
            "warmup_runs": 0,
            "measured_runs": 1,
            "started_at_utc": started_utc,
            "ended_at_utc": ended_utc,
            "duration_ms": duration_ms,
        },
        "source": identity["source"],
        "environment": identity["environment"],
        "safety": safety_values,
        "workload": {
            "workload_id": WORKLOAD_ID,
            "fixture_schema_version": fixture["schema_version"],
            "plate_name": fixture["plate"]["name"],
            "plate_rows": fixture["plate"]["rows"],
            "plate_columns": fixture["plate"]["columns"],
            "well_ids": list(expected_wells),
            "stock_id": (
                fixture_info["stock_id"] if fixture_info else _stock_id(fixture["stock"])
            ),
            "target_dispenses_per_well": 1,
            "expected_completion_count": 96,
            "speed_multiplier": config.speed_multiplier,
            "timeout_seconds": config.timeout_seconds,
        },
        "metrics": {
            "responsiveness": {
                "status": "measured" if probe_started else "not_available",
                "values": response_values if probe_started else {},
            },
            "workflow": {
                "status": "measured",
                "values": {
                    "expected_well_count": 96,
                    "completed_well_count": len(completed_updates),
                    "completed_well_ids": completed_updates,
                    "well_update_count": len(well_updates),
                    "array_states": array_states,
                    "array_complete_count": array_complete_count,
                    "dialogs": dialogs,
                    "unexpected_dialogs": unexpected_dialogs,
                    "errors": errors,
                    "validation_checks": validation.get("checks", {}),
                },
            },
            "queue": {
                "status": "measured",
                "values": {
                    "lifecycle_event_count": len(command_events),
                    "lifecycle_counts": dict(sorted(lifecycle_counts.items())),
                    "maximum_queue_depth": max(queue_depths) if queue_depths else 0,
                    "minimum_queue_depth": min(queue_depths) if queue_depths else 0,
                    "unexpected_starvation_count": len(starvation_events),
                    "unexpected_starvation_events": starvation_events,
                    "simulator_cleanup": machine_cleanup,
                },
            },
            "persistence": {
                "status": "measured" if validation else "partial",
                "values": {
                    **validation,
                    "phase_timings": phases.snapshot(),
                },
            },
            "resources": resource_snapshot,
        },
        "artifacts": {
            "report_json": "report.json",
            "summary_text": "summary.txt",
            "event_trace": "events.jsonl",
            "stall_stacks": "stall_stacks.txt",
            "failure_traceback": (
                "failure_traceback.txt" if failure_text else None
            ),
            "scenario_root": _relative(scenario_root, report_dir),
            "screenshots": {
                name: _relative(path, report_dir)
                for name, path in sorted(screenshots.items())
            },
        },
        "classification": {
            "status": status,
            "threshold_maturity": "informational",
            "reasons": reasons,
        },
        "limitations": [
            "The simulator verifies the application-facing contract, not firmware framing or ACK behavior.",
            "No physical motion, collision safety, pressure response, camera analysis, balance behavior, or droplet quality is modeled.",
            "Raw responsiveness measurements are informational until Slice 6 defines compatible baselines and acceptance gates.",
            "Well-plate update and pressure-render method durations are observed; native Qt paint dispatch duration is not separately instrumented.",
        ],
    }
    validate_report_v1(report)

    event_path = report_dir / "events.jsonl"
    stack_path = report_dir / "stall_stacks.txt"
    summary_path = report_dir / "summary.txt"
    _write_event_trace(event_path, events)
    stack_path.write_text(
        "\n\n".join(
            str(capture.get("stack") or "")
            for capture in probe_snapshot.get("stack_captures", [])
        ),
        encoding="utf-8",
    )
    if failure_text:
        (report_dir / "failure_traceback.txt").write_text(
            failure_text,
            encoding="utf-8",
        )
    summary_path.write_text(_summary_text(report), encoding="utf-8")
    write_report_atomic(report_dir / "report.json", report)
    return report


__all__ = [
    "SCENARIO_NAME",
    "SCENARIO_VERSION",
    "WORKLOAD_ID",
    "VirtualPrintArrayScenarioConfig",
    "VirtualWorkflowScenarioError",
    "fixture_well_ids",
    "load_virtual_print_array_fixture",
    "run_virtual_print_array_scenario",
]
