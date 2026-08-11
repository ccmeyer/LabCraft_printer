"""Real-UI, hardware-isolated virtual workflow scenarios."""

from __future__ import annotations

import io
import hashlib
import json
import math
import os
import sys
import time
import traceback
import uuid
from contextlib import contextmanager, nullcontext, redirect_stdout
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
SMOKE_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "virtual_print_array_24_v1.json"
)
STRESS_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "virtual_print_array_384x10_v1.json"
)
SOFT_STOP_RESUME_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "print_array_soft_stop_resume_24_v1.json"
)
AUTHORITATIVE_RELOAD_RESUME_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "authoritative_reload_resume_24_v1.json"
)
MULTI_STOCK_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "print_array_multi_stock_24x2_v1.json"
)
MIXED_MODE_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "print_array_mixed_mode_24x2_v1.json"
)
DISCONNECT_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "print_array_disconnect_mid_array_24_v1.json"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "verification_reports" / "virtual_workflows"
WORKLOAD_ID = "virtual_print_array_96_v1"
SMOKE_WORKLOAD_ID = "virtual_print_array_24_v1"
STRESS_WORKLOAD_ID = "virtual_print_array_384x10_v1"
SOFT_STOP_RESUME_WORKLOAD_ID = "print_array_soft_stop_resume_24_v1"
AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID = "authoritative_reload_resume_24_v1"
MULTI_STOCK_WORKLOAD_ID = "print_array_multi_stock_24x2_v1"
MIXED_MODE_WORKLOAD_ID = "print_array_mixed_mode_24x2_v1"
DISCONNECT_WORKLOAD_ID = "print_array_disconnect_mid_array_24_v1"
SCENARIO_FIXTURES = {
    WORKLOAD_ID: FIXTURE_PATH,
    STRESS_WORKLOAD_ID: STRESS_FIXTURE_PATH,
    SMOKE_WORKLOAD_ID: SMOKE_FIXTURE_PATH,
    SOFT_STOP_RESUME_WORKLOAD_ID: SOFT_STOP_RESUME_FIXTURE_PATH,
    AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID: AUTHORITATIVE_RELOAD_RESUME_FIXTURE_PATH,
    MULTI_STOCK_WORKLOAD_ID: MULTI_STOCK_FIXTURE_PATH,
    MIXED_MODE_WORKLOAD_ID: MIXED_MODE_FIXTURE_PATH,
    DISCONNECT_WORKLOAD_ID: DISCONNECT_FIXTURE_PATH,
}
SCENARIO_COMPLETION_COUNTS = {
    WORKLOAD_ID: 96,
    STRESS_WORKLOAD_ID: 3840,
    SMOKE_WORKLOAD_ID: 24,
    SOFT_STOP_RESUME_WORKLOAD_ID: 24,
    AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID: 24,
    MULTI_STOCK_WORKLOAD_ID: 48,
    MIXED_MODE_WORKLOAD_ID: 48,
    DISCONNECT_WORKLOAD_ID: 24,
}
SCENARIO_WORKFLOW_STRATEGIES = {
    WORKLOAD_ID: "uninterrupted",
    STRESS_WORKLOAD_ID: "uninterrupted",
    SMOKE_WORKLOAD_ID: "uninterrupted",
    SOFT_STOP_RESUME_WORKLOAD_ID: "soft_stop_resume",
    AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID: "authoritative_reload_resume",
    MULTI_STOCK_WORKLOAD_ID: "multi_stock_head_exchange",
    MIXED_MODE_WORKLOAD_ID: "mixed_droplet_stream",
}
SCENARIO_NAME = "virtual_print_array"
SCENARIO_VERSION = "1"
EXPECTED_START_DIALOGS = (
    "Start Print Array",
    "Evaporation Plate Dock Check",
)
EXPECTED_SOFT_STOP_RESUME_DIALOGS = EXPECTED_START_DIALOGS + (
    "Resume Print Array",
)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))

from tools.virtual_workflows.metrics import (  # noqa: E402
    NamedPhaseRecorder,
    ProcessResourceSampler,
    QtEventLoopProbe,
    summarize_samples,
)
from tools.virtual_workflows.actions import (  # noqa: E402
    ScenarioActionError,
    ScenarioContext,
    capture_failure_screenshot,
    capture_milestone,
    close_simulated_session,
    connect_machine_ready,
    drive_authoritative_reload_via_editor,
    enable_pressure_regulation,
    install_dialog_handler,
    launch_simulated_application,
    prepare_authoritative_fixture,
    request_soft_stop_via_ui,
    stage_virtual_head,
    start_array_via_ui,
    teardown_scenario,
    validate_terminal_bundle,
    validate_paused_bundle,
    validate_reload_boundary,
    validate_stock_pass_boundary,
    observe_stopped_quiescence,
    wait_for_array_state,
    wait_for_completions,
    wait_until,
)
from tools.virtual_workflows.authoritative_evidence import (  # noqa: E402
    authoritative_activation_boundary,
    authoritative_loaded_boundary,
    capture_authoritative_bundle,
    completed_stock_well_pairs,
    read_model_audit_rows as _read_audit_rows,
    rich_file_inventory as _file_inventory,
)
from tools.virtual_workflows.persistence_io import PersistenceIoObserver  # noqa: E402
from tools.virtual_workflows.progress_snapshot import (  # noqa: E402
    ProgressSnapshotObserver,
    non_durable_progress_samples,
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _resolved_beneath(path: str | Path, root: str | Path) -> bool:
    candidate = Path(path).resolve()
    parent = Path(root).resolve()
    return candidate == parent or parent in candidate.parents


def _merge_session_lifecycles(
    sessions: tuple[tuple[str, dict[str, Any]], ...],
) -> dict[str, list[Any]]:
    from tools.virtual_workflows.authoritative_evidence import (
        merge_session_lifecycles,
    )

    return merge_session_lifecycles(sessions)


def _merge_progress_snapshots(
    first: dict[str, Any],
    second: dict[str, Any],
) -> dict[str, Any]:
    duration_keys = set(first.get("duration_samples_ms", {})) | set(
        second.get("duration_samples_ms", {})
    )
    durations = {
        key: [
            *first.get("duration_samples_ms", {}).get(key, ()),
            *second.get("duration_samples_ms", {}).get(key, ()),
        ]
        for key in sorted(duration_keys)
    }
    sizes = [
        *first.get("serialized_size_bytes", ()),
        *second.get("serialized_size_bytes", ()),
    ]
    non_durable = [
        *first.get("non_durable_write_samples_ms", ()),
        *second.get("non_durable_write_samples_ms", ()),
    ]
    return {
        "mode_counts": {
            key: int(first.get("mode_counts", {}).get(key, 0))
            + int(second.get("mode_counts", {}).get(key, 0))
            for key in {"cached_update", "full_rebuild"}
        },
        "duration_samples_ms": durations,
        "duration_statistics_ms": {
            key: summarize_samples(values)
            for key, values in durations.items()
        },
        "serialized_size_bytes": sizes,
        "serialized_size_statistics_bytes": summarize_samples(
            sizes,
            bands_ms=(),
        ),
        "non_durable_write_samples_ms": non_durable,
        "non_durable_write_ms": summarize_samples(
            non_durable,
            bands_ms=(),
        ),
        "observer_restored": bool(first.get("observer_restored"))
        and bool(second.get("observer_restored")),
    }


def _merge_durable_io_snapshots(
    first: dict[str, Any],
    second: dict[str, Any],
) -> dict[str, dict[str, list[float]]]:
    operations = set(first) | set(second)
    return {
        operation: {
            phase: [
                *first.get(operation, {}).get(phase, ()),
                *second.get(operation, {}).get(phase, ()),
            ]
            for phase in sorted(
                set(first.get(operation, {}))
                | set(second.get(operation, {}))
            )
        }
        for operation in sorted(operations)
    }
    return {
        key: [
            (
                {**dict(item), "application_session_id": session_id}
                if isinstance(item, dict)
                else item
            )
            for session_id, snapshot in sessions
            for item in snapshot.get(key, ())
        ]
        for key in sorted(keys)
    }


def _progress_format_evidence(experiment_dir: Path) -> dict[str, Any]:
    from ExecutionPlan import load_execution_plan
    from ExecutionProgressStore import execution_progress_storage_evidence

    try:
        plan = load_execution_plan(experiment_dir / "execution_plan.json")
        payload = json.loads(
            (experiment_dir / "progress.json").read_text(encoding="utf-8")
        )
        return execution_progress_storage_evidence(plan, payload)
    except Exception as exc:
        return {"error": str(exc)}


class _BoundedEventLog:
    """Retain critical events and a bounded sample of verbose command events."""

    def __init__(self, *, limit: int = 50_000, command_sample_rate: int = 20):
        self.limit = max(1, int(limit))
        self.command_sample_rate = max(1, int(command_sample_rate))
        self.events: list[dict[str, Any]] = []
        self.counts: Counter[str] = Counter()
        self.dropped_count = 0

    def record(self, kind: str, **values: Any) -> None:
        kind = str(kind)
        self.counts[kind] += 1
        event = {
            "kind": kind,
            "monotonic_ns": time.perf_counter_ns(),
            **values,
        }
        retain = kind != "command" or (
            self.counts[kind] % self.command_sample_rate == 1
        )
        if retain and len(self.events) < self.limit:
            self.events.append(event)
        else:
            self.dropped_count += 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "retained_count": len(self.events),
            "dropped_count": self.dropped_count,
            "counts": dict(sorted(self.counts.items())),
            "command_sample_rate": self.command_sample_rate,
            "limit": self.limit,
        }


@dataclass(frozen=True)
class VirtualPrintArrayScenarioConfig:
    """Runtime controls for the versioned real-UI print-array scenario."""

    output_root: Path = DEFAULT_OUTPUT_ROOT
    fixture_path: Path | None = None
    scenario_id: str = WORKLOAD_ID
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
        scenario_id = str(self.scenario_id or "").strip()
        if scenario_id not in SCENARIO_FIXTURES:
            raise ValueError(f"unsupported scenario_id: {scenario_id!r}")
        fixture_path = Path(
            self.fixture_path
            if self.fixture_path is not None
            else SCENARIO_FIXTURES[scenario_id]
        ).resolve()
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
        maximum_completion = SCENARIO_COMPLETION_COUNTS[scenario_id]
        if scenario_id in {
            SMOKE_WORKLOAD_ID,
            SOFT_STOP_RESUME_WORKLOAD_ID,
            AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID,
        } and inject_after == 48:
            inject_after = maximum_completion // 2
        if not 1 <= inject_after <= maximum_completion:
            raise ValueError(
                "inject_after_completion must be between 1 and "
                f"{maximum_completion}"
            )
        if (pi_preflight_path is None) != (pi_hardware_proof_path is None):
            raise ValueError(
                "pi_preflight_path and pi_hardware_proof_path must be provided together"
            )
        object.__setattr__(self, "output_root", output_root)
        object.__setattr__(self, "fixture_path", fixture_path)
        object.__setattr__(self, "scenario_id", scenario_id)
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
    path: str | Path | None = None,
    *,
    scenario_id: str = WORKLOAD_ID,
) -> dict[str, Any]:
    """Load and strictly validate a tracked print-array fixture manifest."""

    scenario_id = str(scenario_id or "").strip()
    if scenario_id not in SCENARIO_FIXTURES:
        raise VirtualWorkflowScenarioError(
            f"unsupported virtual print-array scenario {scenario_id!r}"
        )
    fixture_path = Path(path if path is not None else SCENARIO_FIXTURES[scenario_id])
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VirtualWorkflowScenarioError(
            f"could not load fixture {fixture_path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise VirtualWorkflowScenarioError(
            "virtual print-array fixture has an invalid top-level contract"
        )
    if payload.get("fixture_id") != scenario_id:
        raise VirtualWorkflowScenarioError(
            "virtual print-array fixture identity/version is unsupported"
        )
    schema_version = payload.get("schema_version")
    expected_top = (
        {
            "schema_version",
            "fixture_id",
            "plate",
            "workload",
            "stock",
            "fill_stock",
            "printer_head",
            "simulation",
        }
        if schema_version == 1
        else {
            "schema_version",
            "fixture_id",
            "plate",
            "workload",
            "stocks",
            "fill_stock",
            "simulation",
            *({"lifecycle"} if schema_version in {3, 4} else set()),
        }
    )
    if set(payload) != expected_top or schema_version not in {1, 2, 3, 4}:
        raise VirtualWorkflowScenarioError(
            "virtual print-array fixture has an invalid top-level contract"
        )
    plate = payload["plate"]
    included_rows = plate.get("included_rows") if isinstance(plate, dict) else None
    expected_rows = ["A", "B", "C", "D"] if schema_version == 1 else included_rows
    if (
        not isinstance(plate, dict)
        or plate.get("name") != "shallow-384_well_plate"
        or plate.get("rows") != 16
        or plate.get("columns") != 24
        or plate.get("included_rows") != expected_rows
        or not isinstance(expected_rows, list)
        or not expected_rows
        or len(set(expected_rows)) != len(expected_rows)
        or any(row not in tuple("ABCDEFGHIJKLMNOP") for row in expected_rows)
        or plate.get("serpentine") is not True
    ):
        raise VirtualWorkflowScenarioError("fixture plate contract is invalid")
    workload = payload["workload"]
    if schema_version == 1:
        expected_workload = {
            "target_dispenses_per_well": 1,
            "completion_count": 96,
        }
        workload_valid = workload == expected_workload
    else:
        stock_count = len(payload.get("stocks") or [])
        well_count = len(expected_rows) * int(plate.get("columns", 0))
        expected_workload = {
            "target_dispenses_per_stock_per_well": 1,
            "well_count": well_count,
            "stock_count": stock_count,
            "array_passes": stock_count,
            "completion_count": well_count * stock_count,
        }
        workload_valid = workload == expected_workload
    if not workload_valid:
        raise VirtualWorkflowScenarioError("fixture workload contract is invalid")
    fill = payload["fill_stock"]
    simulation = payload["simulation"]
    stock_specs = _fixture_stock_specs(payload)
    if (
        not isinstance(fill, dict)
        or fill.get("factor_name") != "Water"
        or fill.get("units") != "--"
        or fill.get("target_dispenses_per_well") != 0
        or not isinstance(simulation, dict)
        or int(simulation.get("dispense_frequency_hz", 0)) <= 0
        or int(simulation.get("lookahead_wells", 0)) != 2
    ):
        raise VirtualWorkflowScenarioError("fixture stock/head contract is invalid")
    stock_ids: set[str] = set()
    head_ids: set[str] = set()
    for stock in stock_specs:
        head = stock["printer_head"]
        stock_id = _stock_id(stock)
        head_id = str(head.get("printer_head_id") or "")
        is_multi_fixture = scenario_id in {
            MULTI_STOCK_WORKLOAD_ID,
            MIXED_MODE_WORKLOAD_ID,
        }
        expected_prepared_volume = (
            float(stock.get("droplet_volume_nL", -1))
            if is_multi_fixture
            else 9.0 if scenario_id == SMOKE_WORKLOAD_ID else 5.0
        )
        expected_calibrated_volume = (
            float(stock.get("prepared_droplet_volume_nL", -1))
            if is_multi_fixture
            else 9.0 if scenario_id == SMOKE_WORKLOAD_ID else 10.0
        )
        expected_modes = ("droplet", "stream")
        expected_mode = (
            expected_modes[len(stock_ids)]
            if scenario_id == MIXED_MODE_WORKLOAD_ID
            and len(stock_ids) < len(expected_modes)
            else "droplet"
        )
        mixed_head_valid = True
        if scenario_id == MIXED_MODE_WORKLOAD_ID:
            if expected_mode == "stream":
                mixed_head_valid = (
                    int(head.get("refuel_pulse_width_us", 0)) == 6000
                    and float(head.get("refuel_pressure_psi", -1)) == 0.4
                )
            else:
                mixed_head_valid = not {
                    "refuel_pulse_width_us", "refuel_pressure_psi"
                }.intersection(head)
        if (
            stock.get("printing_mode") != expected_mode
            or float(stock.get("prepared_droplet_volume_nL", -1))
            != expected_prepared_volume
            or float(stock.get("droplet_volume_nL", -1))
            != expected_calibrated_volume
            or not head_id
            or int(head.get("print_pulse_width_us", 0)) <= 0
            or float(head.get("print_pressure_psi", -1)) <= 0
            or float(head.get("initial_volume_uL", -1)) <= 0
            or stock_id in stock_ids
            or head_id in head_ids
            or not mixed_head_valid
        ):
            raise VirtualWorkflowScenarioError("fixture stock/head contract is invalid")
        stock_ids.add(stock_id)
        head_ids.add(head_id)
    if len(stock_specs) != int(
        workload.get("stock_count", 1)
    ):
        raise VirtualWorkflowScenarioError("fixture stock count is invalid")
    if scenario_id == MIXED_MODE_WORKLOAD_ID:
        expected_mixed = (
            ("Virtual Mixed Droplet", 23.0, 3.0, "mM", "droplet", 9.0, 1300, 1.2),
            ("Virtual Mixed Stream", 23.0, 20.0, "mM", "stream", 60.0, 2500, 1.2),
        )
        observed_mixed = tuple(
            (
                stock.get("factor_name"),
                float(stock.get("concentration", -1)),
                float(stock.get("target_concentration", -1)),
                stock.get("units"),
                stock.get("printing_mode"),
                float(stock.get("droplet_volume_nL", -1)),
                int(stock.get("printer_head", {}).get("print_pulse_width_us", 0)),
                float(stock.get("printer_head", {}).get("print_pressure_psi", -1)),
            )
            for stock in stock_specs
        )
        if observed_mixed != expected_mixed:
            raise VirtualWorkflowScenarioError(
                "mixed-mode fixture stock contract is invalid"
            )
    if schema_version in {2, 3, 4} and int(simulation.get("staging_slot", -1)) != 0:
        raise VirtualWorkflowScenarioError("fixture staging-slot contract is invalid")
    if schema_version in {3, 4}:
        lifecycle = payload.get("lifecycle")
        expected_lifecycle = {
            SOFT_STOP_RESUME_WORKLOAD_ID: {
                "kind": "soft_stop_resume",
                "request_after_completion_count": 6,
                "maximum_completion_catchup": 2,
                "quiescence_observation_ms": 250,
            },
            AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID: {
                "kind": "authoritative_reload_resume",
                "request_after_completion_count": 6,
                "maximum_completion_catchup": 2,
                "quiescence_observation_ms": 250,
                "expected_application_session_count": 2,
            },
            MULTI_STOCK_WORKLOAD_ID: {
                "kind": "multi_stock_head_exchange",
                "expected_stock_pass_count": 2,
                "expected_head_stage_count": 2,
                "expected_between_pass_exchange_count": 1,
            },
            MIXED_MODE_WORKLOAD_ID: {
                "kind": "mixed_droplet_stream",
                "expected_stock_pass_count": 2,
                "expected_head_stage_count": 2,
                "expected_between_pass_exchange_count": 1,
                "manual_refuel_check": {
                    "status": "passed",
                    "operator_judgment": "stable",
                    "trial_count": 2,
                    "trial_droplet_count": 5,
                },
            },
            DISCONNECT_WORKLOAD_ID: {
                "kind": "disconnect_fail_closed",
                "disconnect_after_completion_count": 6,
                "expected_canceled_intent_count": 2,
                "quiescence_observation_ms": 250,
            },
        }.get(str(payload.get("fixture_id")))
        if expected_lifecycle is None or lifecycle != expected_lifecycle:
            raise VirtualWorkflowScenarioError(
                "fixture lifecycle contract is invalid"
            )
    return payload


def fixture_well_ids(fixture: dict[str, Any]) -> tuple[str, ...]:
    """Expand included rows into deterministic row-serpentine order."""

    columns = int(fixture["plate"]["columns"])
    result: list[str] = []
    for index, row in enumerate(fixture["plate"]["included_rows"]):
        values = range(1, columns + 1)
        if index % 2:
            values = range(columns, 0, -1)
        result.extend(f"{row}{column}" for column in values)
    expected_count = int(
        fixture["workload"].get(
            "well_count",
            fixture["workload"]["completion_count"],
        )
    )
    if len(result) != expected_count or len(set(result)) != expected_count:
        raise VirtualWorkflowScenarioError(
            "fixture expansion did not produce the expected unique wells"
        )
    return tuple(result)


def _stock_id(spec: dict[str, Any]) -> str:
    return (
        f"{spec['factor_name']}_{float(spec['concentration']):.2f}_"
        f"{spec['units']}"
    )


def _fixture_stock_specs(fixture: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    if fixture.get("schema_version") == 1:
        return (
            {
                **fixture["stock"],
                "printer_head": dict(fixture["printer_head"]),
            },
        )
    stocks = fixture.get("stocks")
    if not isinstance(stocks, list) or not stocks:
        raise VirtualWorkflowScenarioError("fixture stocks must be a nonempty list")
    if not all(isinstance(stock, dict) for stock in stocks):
        raise VirtualWorkflowScenarioError("fixture stock entries must be objects")
    return tuple(dict(stock) for stock in stocks)


def _fixture_target_per_stock(fixture: dict[str, Any]) -> int:
    workload = fixture["workload"]
    return int(
        workload.get(
            "target_dispenses_per_stock_per_well",
            workload.get("target_dispenses_per_well", 0),
        )
    )


def _create_prepared_fixture(
    experiment_dir: Path,
    fixture: dict[str, Any],
) -> dict[str, Any]:
    from ExecutionPlan import save_execution_plan
    from ExecutionPlanRevision import persist_immutable_revision
    from ExecutionProgressStore import (
        encode_execution_progress_v2,
        serialize_execution_progress,
    )
    from InitialExecutionPlan import build_initial_execution_plan

    if experiment_dir.exists():
        raise VirtualWorkflowScenarioError(
            f"scenario experiment directory already exists: {experiment_dir}"
        )
    experiment_dir.mkdir(parents=True)
    wells = fixture_well_ids(fixture)
    workload_id = str(fixture["fixture_id"])
    stocks = _fixture_stock_specs(fixture)
    fill = fixture["fill_stock"]
    stock_ids = tuple(_stock_id(stock) for stock in stocks)
    fill_stock_id = _stock_id(fill)
    target = _fixture_target_per_stock(fixture)
    prepared_targets = {
        _stock_id(stock): int(
            round(
                float(stock["droplet_volume_nL"])
                * target
                / float(stock["prepared_droplet_volume_nL"])
            )
        )
        for stock in stocks
    }
    reaction_volume = sum(
        float(stock["droplet_volume_nL"]) * target for stock in stocks
    )
    design = {
        "schema_version": 2,
        "metadata": {
            "name": workload_id,
            "target_reaction_volume_nL": reaction_volume,
            "final_reaction_volume_nL": reaction_volume,
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
                        "targets": [
                            float(
                                stock.get(
                                    "target_concentration",
                                    stock["concentration"],
                                )
                            )
                        ],
                        "units": stock["units"],
                        "droplet_nL": float(stock["droplet_volume_nL"]),
                        "printing_mode": stock["printing_mode"],
                        "intended_droplet_nL": float(stock["droplet_volume_nL"]),
                    }
                ],
            }
            for stock in stocks
        ],
    }
    stock_rows = [
        {
            "factor_name": stock["factor_name"],
            "option_name": None,
            "stock_concentration": float(stock["concentration"]),
            "units": stock["units"],
            "printing_mode": stock["printing_mode"],
            "droplet_volume_nL": float(stock["prepared_droplet_volume_nL"]),
        }
        for stock in stocks
    ]
    stock_rows.append(
        {
            "factor_name": fill["factor_name"],
            "option_name": None,
            "stock_concentration": float(fill["concentration"]),
            "units": fill["units"],
            "printing_mode": fill["printing_mode"],
            "droplet_volume_nL": float(fill["droplet_volume_nL"]),
        }
    )
    assigned_wells = [
        {
            "well_id": well_id,
            "reaction_id": f"R{index}",
            "target_dispenses": {
                **prepared_targets,
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
        plan_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"labcraft:{workload_id}")),
        timestamp_utc="2026-07-23T00:00:00Z",
    )
    design_path = experiment_dir / "experiment_design.json"
    design_path.write_text(json.dumps(design, indent=2) + "\n", encoding="utf-8")
    save_execution_plan(experiment_dir / "execution_plan.json", plan)
    persist_immutable_revision(experiment_dir / "execution_plan_revisions", plan)
    progress_wells = {
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
    progress = encode_execution_progress_v2(plan, progress_wells)
    (experiment_dir / "progress.json").write_text(
        serialize_execution_progress(progress),
        encoding="utf-8",
    )
    return {
        "experiment_dir": experiment_dir,
        "design_path": design_path,
        "stock_id": stock_ids[0],
        "stock_ids": stock_ids,
        "stock_specs": {
            _stock_id(stock): stock for stock in stocks
        },
        "target_dispenses_per_stock": target,
        "fill_stock_id": fill_stock_id,
        "well_ids": wells,
        "plan_id": plan.plan_id,
    }


class _InstanceInstrumentation:
    _MAX_SIMULATOR_DISPENSES = 10_000

    def __init__(
        self,
        phases: NamedPhaseRecorder,
        *,
        inject_ms: int,
        inject_after_completion: int,
        completed_count: Callable[[], int],
        io_observer: PersistenceIoObserver | None = None,
        pass_context: Callable[[], dict[str, Any] | None] | None = None,
    ):
        self.phases = phases
        self.inject_ms = int(inject_ms)
        self.inject_after_completion = int(inject_after_completion)
        self.completed_count = completed_count
        self.io_observer = io_observer or PersistenceIoObserver()
        self.pass_context = pass_context or (lambda: None)
        self.injected = False
        self.intent_begins: list[dict[str, Any]] = []
        self.intent_attachments: list[dict[str, Any]] = []
        self.intent_completions: list[str] = []
        self.intent_discard_batches: list[dict[str, Any]] = []
        self.simulator_dispenses: list[tuple[Any, bool]] = []
        self.simulator_dispense_overflow_count = 0
        self.soft_stop_events: list[dict[str, Any]] = []
        self.checkpoint_observations: list[dict[str, Any]] = []
        self.pass_starts: list[dict[str, Any]] = []
        self.terminal_transitions: list[dict[str, Any]] = []
        self._terminal_depth = 0
        self._originals: list[tuple[Any, str, Any]] = []
        self._connected_slots: list[tuple[Any, Any, str, Any, Any]] = []
        self._suppressed_phases: set[str] = set()

    def _pass_metadata(self) -> dict[str, Any]:
        context = self.pass_context()
        return dict(context or {})

    def _io_totals(self) -> dict[str, int]:
        return self.io_observer.totals()

    def wrap_pass_start(self, controller: Any, experiment_model: Any) -> None:
        original = getattr(controller, "print_array")

        def measured(*args, **kwargs):
            metadata = self._pass_metadata()
            before_io = self._io_totals()
            starting_plan = experiment_model.get_execution_plan_snapshot()
            started_ns = time.perf_counter_ns()
            error_type = None
            try:
                with self.phases.phase(
                    "pass_start.total",
                    metadata,
                ), self.io_observer.phase("pass_start.total"):
                    return original(*args, **kwargs)
            except BaseException as exc:
                error_type = type(exc).__name__
                raise
            finally:
                ended_ns = time.perf_counter_ns()
                after_io = self._io_totals()
                final_plan = experiment_model.get_execution_plan_snapshot()
                records = self.phases.snapshot().get("records", [])
                nested = [
                    record
                    for record in records
                    if int(record.get("started_ns", 0)) >= started_ns
                    and int(record.get("ended_ns", 0)) <= ended_ns
                ]
                self.pass_starts.append(
                    {
                        **metadata,
                        "started_monotonic_ns": started_ns,
                        "ended_monotonic_ns": ended_ns,
                        "duration_ms": (ended_ns - started_ns) / 1_000_000.0,
                        "starting_plan_revision": (
                            None
                            if starting_plan is None
                            else int(starting_plan.plan_revision)
                        ),
                        "final_plan_revision": (
                            None
                            if final_plan is None
                            else int(final_plan.plan_revision)
                        ),
                        "error_type": error_type,
                        "full_bundle_refresh_count": sum(
                            record.get("name")
                            == "persistence.full_bundle_refresh"
                            for record in nested
                        ),
                        "history_validation_count": sum(
                            record.get("name")
                            == "pass_start.history_validation"
                            for record in nested
                        ),
                        "io_delta": {
                            name: after_io[name] - before_io[name]
                            for name in before_io
                        },
                        "preparation": dict(
                            getattr(
                                experiment_model,
                                "_last_authoritative_pass_preparation",
                                None,
                            )
                            or {}
                        ),
                        "calibration": dict(
                            getattr(
                                experiment_model,
                                "_last_authoritative_calibration_transition",
                                None,
                            )
                            or {}
                        ),
                    }
                )

        self._originals.append((controller, "print_array", original))
        setattr(controller, "print_array", measured)

    def wrap_terminal_transition(self, experiment_model: Any) -> None:
        original = getattr(experiment_model, "transition_execution_plan_terminal")

        def measured(state, reason, *args, **kwargs):
            before_io = self._io_totals()
            starting_plan = experiment_model.get_execution_plan_snapshot()
            started_ns = time.perf_counter_ns()
            error_type = None
            self._terminal_depth += 1
            try:
                with self.phases.phase(
                    "terminal_transition.total",
                    {"state": str(getattr(state, "value", state)), "reason": str(reason)},
                ), self.io_observer.phase("terminal_transition.total"):
                    return original(state, reason, *args, **kwargs)
            except BaseException as exc:
                error_type = type(exc).__name__
                raise
            finally:
                self._terminal_depth -= 1
                ended_ns = time.perf_counter_ns()
                after_io = self._io_totals()
                final_plan = experiment_model.get_execution_plan_snapshot()
                records = self.phases.snapshot().get("records", [])
                nested = [
                    record
                    for record in records
                    if int(record.get("started_ns", 0)) >= started_ns
                    and int(record.get("ended_ns", 0)) <= ended_ns
                ]
                self.terminal_transitions.append(
                    {
                        "state": str(getattr(state, "value", state)),
                        "reason": str(reason),
                        "started_monotonic_ns": started_ns,
                        "ended_monotonic_ns": ended_ns,
                        "duration_ms": (ended_ns - started_ns) / 1_000_000.0,
                        "starting_plan_revision": (
                            None
                            if starting_plan is None
                            else int(starting_plan.plan_revision)
                        ),
                        "final_plan_revision": (
                            None
                            if final_plan is None
                            else int(final_plan.plan_revision)
                        ),
                        "error_type": error_type,
                        "full_bundle_refresh_count": sum(
                            str(record.get("name", "")).endswith("full_validation")
                            for record in nested
                        ),
                        "io_delta": {
                            name: after_io[name] - before_io[name]
                            for name in before_io
                        },
                        "preparation": dict(
                            getattr(
                                experiment_model,
                                "_last_authoritative_terminal_transition",
                                None,
                            )
                            or {}
                        ),
                    }
                )

        self._originals.append(
            (experiment_model, "transition_execution_plan_terminal", original)
        )
        setattr(experiment_model, "transition_execution_plan_terminal", measured)

    def wrap_contextual(
        self,
        obj: Any,
        method_name: str,
        normal_phase: str,
        terminal_phase: str,
    ) -> None:
        original = getattr(obj, method_name)

        def measured(*args, **kwargs):
            phase_name = terminal_phase if self._terminal_depth else normal_phase
            metadata = (
                self._pass_metadata()
                if phase_name.startswith("pass_start.")
                else None
            )
            with self.phases.phase(
                phase_name,
                metadata,
            ), self.io_observer.phase(phase_name):
                return original(*args, **kwargs)

        self._originals.append((obj, method_name, original))
        setattr(obj, method_name, measured)

    def wrap(
        self,
        obj: Any,
        method_name: str,
        phase_name: str,
        *,
        before: Callable[[], None] | None = None,
        after: Callable[[], None] | None = None,
        observe: Callable[[tuple[Any, ...], dict[str, Any], Any], None] | None = None,
    ) -> None:
        original = getattr(obj, method_name)

        def measured(*args, **kwargs):
            if phase_name in self._suppressed_phases:
                return original(*args, **kwargs)
            if before is not None:
                before()
            metadata = (
                self._pass_metadata()
                if phase_name.startswith("pass_start.")
                or phase_name.startswith("ui.experiment_guidance_")
                else None
            )
            with self.phases.phase(
                phase_name,
                metadata,
            ), self.io_observer.phase(phase_name):
                result = original(*args, **kwargs)
            if observe is not None:
                observe(args, kwargs, result)
            if after is not None:
                after()
            return result

        self._originals.append((obj, method_name, original))
        setattr(obj, method_name, measured)

    def observe_method(
        self,
        obj: Any,
        method_name: str,
        observe: Callable[[tuple[Any, ...], dict[str, Any], Any], None],
    ) -> None:
        """Observe one instance method without adding a timing phase."""

        original = getattr(obj, method_name)

        def observed(*args, **kwargs):
            result = original(*args, **kwargs)
            observe(args, kwargs, result)
            return result

        self._originals.append((obj, method_name, original))
        setattr(obj, method_name, observed)

    @contextmanager
    def suppress_phases(self, *phase_names: str):
        added = {
            str(name)
            for name in phase_names
            if str(name) not in self._suppressed_phases
        }
        self._suppressed_phases.update(added)
        try:
            yield
        finally:
            self._suppressed_phases.difference_update(added)

    def capture_checkpoint(self, experiment_model: Any, phase: str) -> None:
        session = experiment_model._active_authoritative_execution_session
        path = Path(experiment_model.execution_resume_file_path)
        self.checkpoint_observations.append(
            {
                "phase": phase,
                "retained_intent_count": len(session.resume.intents),
                "size_bytes": path.stat().st_size,
            }
        )

    def lifecycle_snapshot(self) -> dict[str, Any]:
        return {
            "begins": list(self.intent_begins),
            "attachments": list(self.intent_attachments),
            "completions": list(self.intent_completions),
            "discard_batches": list(self.intent_discard_batches),
            "simulator_dispenses": [
                {
                    "command_seq32": int(
                        getattr(command, "command_number", 0) or 0
                    ),
                    "command_type": str(
                        getattr(command, "command_type", "") or ""
                    ),
                    "commanded_droplets": int(
                        getattr(command, "param1", 0) or 0
                    ),
                    "manual": bool(manual),
                    "status": str(getattr(command, "status", "") or ""),
                }
                for command, manual in self.simulator_dispenses
            ],
            "simulator_dispense_limit": self._MAX_SIMULATOR_DISPENSES,
            "simulator_dispense_overflow_count": (
                self.simulator_dispense_overflow_count
            ),
            "soft_stop_events": list(self.soft_stop_events),
            "checkpoint_observations": list(self.checkpoint_observations),
            "pass_starts": list(self.pass_starts),
            "terminal_transitions": list(self.terminal_transitions),
        }

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
            with self.phases.phase(phase_name), self.io_observer.phase(phase_name):
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
    machine: Any,
    well_plate_widget: Any,
    pressure_plot_widget: Any,
    experiment_task_list: Any,
    inject_ms: int,
    inject_after_completion: int,
    completed_count: Callable[[], int],
    io_observer: PersistenceIoObserver,
    pressure_rendered: Callable[[], None] | None = None,
    pass_context: Callable[[], dict[str, Any] | None] | None = None,
) -> _InstanceInstrumentation:
    instrumentation = _InstanceInstrumentation(
        phases,
        inject_ms=inject_ms,
        inject_after_completion=inject_after_completion,
        completed_count=completed_count,
        io_observer=io_observer,
        pass_context=pass_context,
    )
    def argument(
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        name: str,
        index: int,
    ) -> Any:
        return kwargs[name] if name in kwargs else args[index]

    def observe_begin(args, kwargs, result) -> None:
        instrumentation.intent_begins.append(
            {
                "intent_id": result,
                "well_id": argument(args, kwargs, "well_id", 0),
                "stock_id": argument(args, kwargs, "stock_id", 1),
                "commanded_droplets": int(
                    argument(args, kwargs, "commanded_droplets", 2)
                ),
            }
        )
        instrumentation.capture_checkpoint(experiment_model, "after_begin")

    def observe_attach(args, kwargs, _result) -> None:
        instrumentation.intent_attachments.append(
            {
                "intent_id": argument(args, kwargs, "intent_id", 0),
                "command_seq32": int(
                    argument(args, kwargs, "command_seq32", 1)
                ),
            }
        )
        instrumentation.capture_checkpoint(experiment_model, "after_attach")

    def observe_complete(args, kwargs, _result) -> None:
        instrumentation.intent_completions.append(
            argument(args, kwargs, "intent_id", 0)
        )
        instrumentation.capture_checkpoint(experiment_model, "after_complete")

    def observe_discard(args, kwargs, _result) -> None:
        intent_ids = list(argument(args, kwargs, "intent_ids", 0))
        begin_by_id = {
            item["intent_id"]: item
            for item in instrumentation.intent_begins
        }
        instrumentation.intent_discard_batches.append(
            {
                "intent_ids": intent_ids,
                "intents": [
                    dict(begin_by_id[intent_id])
                    for intent_id in intent_ids
                    if intent_id in begin_by_id
                ],
            }
        )
        instrumentation.capture_checkpoint(experiment_model, "after_discard")

    def observe_dispense(args, kwargs, result) -> None:
        if not result or str(getattr(result, "command_type", "")) != "DISPENSE":
            return
        manual = bool(
            kwargs.get("manual", args[3] if len(args) > 3 else False)
        )
        if len(instrumentation.simulator_dispenses) >= (
            instrumentation._MAX_SIMULATOR_DISPENSES
        ):
            instrumentation.simulator_dispense_overflow_count += 1
            return
        instrumentation.simulator_dispenses.append((result, manual))

    instrumentation.wrap(
        experiment_model,
        "begin_execution_print_intent",
        "persistence.begin_intent",
        observe=observe_begin,
    )
    instrumentation.wrap(
        experiment_model,
        "attach_execution_print_command",
        "persistence.attach_sequence",
        observe=observe_attach,
    )
    instrumentation.wrap(
        experiment_model,
        "create_progress_file",
        "persistence.write_progress",
    )
    instrumentation.wrap(
        experiment_model,
        "complete_execution_print_intent",
        "persistence.complete_intent",
        observe=observe_complete,
    )
    instrumentation.wrap(
        experiment_model,
        "discard_execution_print_intents",
        "persistence.discard_intents",
        observe=observe_discard,
    )
    instrumentation.observe_method(
        machine,
        "print_droplets",
        observe_dispense,
    )
    for method, phase in (
        ("_save_active_execution_resume", "persistence.save_resume"),
        ("_reconcile_authoritative_runtime_session", "persistence.reconcile_cache"),
        ("lock_execution_plan", "pass_start.plan_lock"),
        ("ensure_execution_printer_head_binding", "pass_start.head_binding"),
        ("ensure_execution_resume_checkpoint", "pass_start.checkpoint_activation"),
        ("validate_authoritative_print_context", "pass_start.authoritative_preflight"),
        ("_guard_authoritative_print_preflight", "pass_start.preflight_guard"),
        ("_guard_authoritative_pass_files", "pass_start.revision_guard"),
        ("_commit_authoritative_pass_revision", "pass_start.cached_revision_commit"),
        ("_advance_authoritative_pass_bundle", "pass_start.history_validation"),
        (
            "_persist_authoritative_pass_immutable_revision",
            "pass_start.immutable_revision_write",
        ),
        (
            "_write_authoritative_pass_current_plan",
            "pass_start.current_plan_write",
        ),
        ("_write_authoritative_pass_progress", "pass_start.progress_write"),
        ("_write_authoritative_pass_resume", "pass_start.resume_write"),
        ("_create_authoritative_pass_checkpoint", "pass_start.checkpoint_create"),
        (
            "_commit_authoritative_calibration_revision",
            "pass_start.calibration_cached_commit",
        ),
        (
            "_advance_authoritative_calibration_bundle",
            "pass_start.calibration_successor_validation",
        ),
        (
            "_guard_authoritative_calibration_files",
            "pass_start.calibration_prewrite_guard",
        ),
        (
            "_write_authoritative_calibration_document",
            "pass_start.calibration_document_write",
        ),
        (
            "_persist_authoritative_calibration_immutable_revision",
            "pass_start.calibration_immutable_revision_write",
        ),
        (
            "_write_authoritative_calibration_current_plan",
            "pass_start.calibration_current_plan_write",
        ),
        (
            "_write_authoritative_calibration_progress",
            "pass_start.calibration_progress_write",
        ),
        (
            "_write_authoritative_calibration_resume",
            "pass_start.calibration_resume_write",
        ),
        (
            "_accept_authoritative_calibration_writes",
            "pass_start.calibration_post_write_acceptance",
        ),
        (
            "_install_authoritative_calibration_bundle",
            "pass_start.calibration_cache_install",
        ),
        (
            "_complete_authoritative_execution_cached",
            "terminal_transition.cached_commit",
        ),
        (
            "_build_authoritative_terminal_candidate",
            "terminal_transition.candidate_construction",
        ),
        (
            "_synchronize_authoritative_terminal_resume",
            "terminal_transition.resume_synchronization",
        ),
        (
            "_advance_authoritative_terminal_bundle",
            "terminal_transition.successor_validation",
        ),
        (
            "_guard_authoritative_terminal_files",
            "terminal_transition.prewrite_guard",
        ),
        (
            "_persist_authoritative_terminal_immutable_revision",
            "terminal_transition.immutable_revision_write",
        ),
        (
            "_write_authoritative_terminal_current_plan",
            "terminal_transition.current_plan_write",
        ),
        (
            "_write_authoritative_terminal_progress",
            "terminal_transition.progress_write",
        ),
        (
            "_write_authoritative_terminal_resume",
            "terminal_transition.resume_write",
        ),
        (
            "_accept_authoritative_terminal_writes",
            "terminal_transition.post_write_acceptance",
        ),
        (
            "_install_validated_authoritative_terminal_bundle",
            "terminal_transition.cache_deactivation",
        ),
    ):
        instrumentation.wrap(experiment_model, method, phase)
    for method, normal_phase, terminal_phase in (
        (
            "_guard_authoritative_runtime_session",
            "persistence.guard_bundle",
            "terminal_transition.initial_guard",
        ),
        (
            "_refresh_authoritative_execution_bundle",
            "persistence.full_bundle_refresh",
            "terminal_transition.full_validation",
        ),
        (
            "_recover_persisted_execution_plan_for_transition",
            "pass_start.plan_recovery",
            "terminal_transition.plan_recovery",
        ),
        (
            "_commit_plan_revision",
            "pass_start.commit_revision",
            "terminal_transition.commit_revision",
        ),
        (
            "_write_progress_for_execution_plan",
            "pass_start.progress_revision_sync",
            "terminal_transition.progress_revision_sync",
        ),
        (
            "synchronize_execution_resume_revision",
            "pass_start.resume_revision_sync",
            "terminal_transition.resume_revision_sync",
        ),
        (
            "_write_execution_plan_exports",
            "pass_start.exports",
            "terminal_transition.exports",
        ),
    ):
        instrumentation.wrap_contextual(
            experiment_model,
            method,
            normal_phase,
            terminal_phase,
        )
    if hasattr(experiment_model, "prepare_authoritative_print_pass"):
        instrumentation.wrap(
            experiment_model,
            "prepare_authoritative_print_pass",
            "pass_start.prepare_transaction",
        )
    instrumentation.wrap_pass_start(controller, experiment_model)
    instrumentation.wrap_terminal_transition(experiment_model)
    instrumentation.wrap(
        controller,
        "_finish_array_finalize",
        "terminal_finalize.total",
    )

    def observe_watermark(_args, _kwargs, _result) -> None:
        context = dict(getattr(controller, "_array_context", {}) or {})
        machine_model = controller.model.machine_model
        instrumentation.soft_stop_events.append(
            {
                "event": "watermark_observed",
                "barrier_seq32": context.get("soft_stop_barrier_seq32"),
                "pause_watermark_reached": bool(
                    getattr(machine_model, "pause_watermark_reached", False)
                ),
                "transport_paused": bool(
                    getattr(machine_model, "transport_paused", False)
                ),
                "soft_stop_phase": context.get("soft_stop_phase"),
            }
        )

    def observe_clear(args, kwargs, _result) -> None:
        clear_result = dict(
            kwargs.get("clear_result")
            if "clear_result" in kwargs
            else (args[0] if args else {})
            or {}
        )
        instrumentation.soft_stop_events.append(
            {
                "event": "queue_clear_completed",
                "clear_result": clear_result,
                "soft_stop_uncertain": bool(
                    getattr(controller, "_soft_stop_clear_uncertain", False)
                ),
            }
        )

    instrumentation.wrap(
        controller,
        "_begin_soft_stop_clear_and_park",
        "soft_stop.watermark",
        before=lambda: observe_watermark((), {}, None),
    )
    instrumentation.wrap(
        controller,
        "_on_soft_stop_queue_cleared",
        "soft_stop.queue_clear",
        observe=observe_clear,
    )
    instrumentation.wrap(
        experiment_model,
        "try_complete_execution_plan",
        "terminal_finalize.eligibility",
    )
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
    instrumentation.wrap(
        pressure_plot_widget,
        "update_pressure",
        "ui.pressure_render",
        after=pressure_rendered,
    )
    instrumentation.wrap(
        experiment_task_list,
        "_build_guide_snapshot",
        "ui.experiment_guidance_snapshot",
    )
    instrumentation.wrap(
        experiment_task_list,
        "_full_rebuild",
        "ui.experiment_guidance_rebuild",
    )
    return instrumentation


def _write_event_trace(path: Path, events: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for event in events:
            handle.write(json.dumps(event, sort_keys=True, default=str) + "\n")


def _exclusive_phase_evidence(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize nested phase time without double-counting child intervals."""
    samples: dict[str, list[float]] = {}
    for record in records:
        started = int(record.get("started_ns", 0))
        ended = int(record.get("ended_ns", started))
        depth = int(record.get("depth", 0))
        child_intervals = sorted(
            (
                max(started, int(child.get("started_ns", started))),
                min(ended, int(child.get("ended_ns", ended))),
            )
            for child in records
            if int(child.get("depth", 0)) > depth
            and int(child.get("started_ns", 0)) >= started
            and int(child.get("ended_ns", 0)) <= ended
        )
        covered_ns = 0
        cursor_start = None
        cursor_end = None
        for child_start, child_end in child_intervals:
            if child_end <= child_start:
                continue
            if cursor_start is None:
                cursor_start, cursor_end = child_start, child_end
            elif child_start <= cursor_end:
                cursor_end = max(cursor_end, child_end)
            else:
                covered_ns += cursor_end - cursor_start
                cursor_start, cursor_end = child_start, child_end
        if cursor_start is not None:
            covered_ns += cursor_end - cursor_start
        exclusive_ms = max(0, ended - started - covered_ns) / 1_000_000.0
        samples.setdefault(str(record.get("name")), []).append(exclusive_ms)
    return {
        "samples_ms": samples,
        "summary_ms": {
            name: summarize_samples(values, bands_ms=())
            for name, values in sorted(samples.items())
        },
    }


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
    intent_lifecycle: dict[str, Any],
    pass_terminal_states: list[str],
) -> dict[str, Any]:
    from AuthoritativeExecutionLoad import inspect_authoritative_execution
    from ExecutionPlan import ExecutionPlanState, load_execution_plan
    from ExecutionResumeStore import load_execution_resume

    experiment_dir = Path(fixture_info["experiment_dir"])
    expected_wells = tuple(fixture_info["well_ids"])
    stock_ids = tuple(fixture_info["stock_ids"])
    target_per_stock = int(fixture_info["target_dispenses_per_stock"])
    expected_completions = len(expected_wells) * len(stock_ids)
    expected_pairs = {
        (stock_id, well_id)
        for stock_id in stock_ids
        for well_id in expected_wells
    }
    checkpoint = load_execution_resume(experiment_model.execution_resume_file_path)
    begins = list(intent_lifecycle.get("begins", ()))
    attachments = list(intent_lifecycle.get("attachments", ()))
    completions = list(intent_lifecycle.get("completions", ()))
    observations = list(intent_lifecycle.get("checkpoint_observations", ()))
    intent_ids = [item.get("intent_id") for item in begins]
    intent_pairs = {
        (str(item.get("stock_id")), str(item.get("well_id")))
        for item in begins
    }
    attached_ids = [item.get("intent_id") for item in attachments]
    sequences = [item.get("command_seq32") for item in attachments]
    max_retained = max(
        (int(item.get("retained_intent_count", 0)) for item in observations),
        default=0,
    )
    peak_checkpoint_size = max(
        (int(item.get("size_bytes", 0)) for item in observations),
        default=0,
    )
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
        "checkpoint_empty": not checkpoint.intents,
        "checkpoint_bounded_to_lookahead": max_retained <= 2,
        "intent_count_exact": len(intent_ids) == expected_completions,
        "intent_ids_unique": len(set(intent_ids)) == expected_completions,
        "intent_stock_well_pairs_exact": intent_pairs == expected_pairs,
        "intent_attachments_exact": (
            len(attached_ids) == expected_completions
            and Counter(attached_ids) == Counter(intent_ids)
        ),
        "intent_sequences_unique_monotonic": (
            len(sequences) == expected_completions
            and all(isinstance(value, int) for value in sequences)
            and sequences == sorted(set(sequences))
        ),
        "all_intents_retired": (
            len(completions) == expected_completions
            and Counter(completions) == Counter(intent_ids)
        ),
        "authoritative_bundle_valid": bool(bundle.valid),
        "terminal_plan_completed": terminal_plan.state is ExecutionPlanState.COMPLETED,
        "array_complete_per_stock": array_complete_count == len(stock_ids),
        "ui_running_idle_per_stock": (
            array_states.count("running") == len(stock_ids)
            and array_states.count("idle") >= len(stock_ids) + 1
            and array_states[-1] == "idle"
        ),
        "plan_completes_only_after_last_stock": pass_terminal_states
        == (["active"] * (len(stock_ids) - 1) + ["completed"]),
        "well_updates_exact": (
            len(completed_well_updates) == expected_completions
            and set(completed_well_updates) == set(expected_wells)
            and all(
                count == len(stock_ids)
                for count in Counter(completed_well_updates).values()
            )
        ),
        "no_errors": not errors,
        "no_unexpected_dialogs": not unexpected_dialogs,
        "no_lookahead_starvation": not starvation_events,
    }
    targets_match = True
    for well_id in expected_wells:
        entry = bundle.progress_wells.get(well_id, {})
        for stock_id in stock_ids:
            reagent = (entry.get("reagents") or {}).get(stock_id, {})
            if (
                int(reagent.get("target_droplets", -1)) != target_per_stock
                or int(reagent.get("added_droplets", -1)) != target_per_stock
            ):
                targets_match = False
                break
        if not targets_match:
            break
    checks["targets_match_progress"] = targets_match
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise RuntimeError("scenario invariants failed: " + ", ".join(failed))
    return {
        "checks": checks,
        "checkpoint_state": checkpoint.state,
        "intent_count": len(completions),
        "stock_well_completion_count": len(intent_pairs),
        "stock_pass_count": len(stock_ids),
        "pass_terminal_states": list(pass_terminal_states),
        "observed_completed_intent_count": len(completions),
        "checkpoint_retained_intent_count": len(checkpoint.intents),
        "checkpoint_pending_intent_count": sum(
            intent.status == "pending" for intent in checkpoint.intents
        ),
        "checkpoint_max_observed_intent_count": max_retained,
        "checkpoint_peak_size_bytes": peak_checkpoint_size,
        "checkpoint_observations": observations,
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


def _validate_multi_stock_completed_scenario(
    *,
    context: ScenarioContext,
    machine: Any,
    fixture: dict[str, Any],
    stock_specs: tuple[dict[str, Any], ...],
    event_retention: dict[str, Any],
    experiment_model: Any,
    fixture_info: dict[str, Any],
    well_updates: list[str],
    array_states: list[str],
    array_complete_count: int,
    errors: list[dict[str, Any]],
    unexpected_dialogs: list[dict[str, Any]],
    starvation_events: list[dict[str, Any]],
    intent_lifecycle: dict[str, Any],
    pass_terminal_states: list[str],
) -> dict[str, Any]:
    """Validate the named two-stock lifecycle and its exchange boundaries."""

    result = _validate_completed_scenario(
        experiment_model=experiment_model,
        fixture_info=fixture_info,
        well_updates=well_updates,
        array_states=array_states,
        array_complete_count=array_complete_count,
        errors=errors,
        unexpected_dialogs=unexpected_dialogs,
        starvation_events=starvation_events,
        intent_lifecycle=intent_lifecycle,
        pass_terminal_states=pass_terminal_states,
    )
    stage_actions = [
        dict(item)
        for item in context.action_results
        if item.get("action_id") == "head.stage_virtual"
    ]
    boundary_actions = [
        dict(item)
        for item in context.action_results
        if item.get("action_id") == "validation.stock_pass_boundary"
    ]
    expected_stock_ids = [_stock_id(stock) for stock in stock_specs]
    expected_well_count = int(fixture["workload"]["well_count"])
    expected_completion_count = int(fixture["workload"]["completion_count"])
    expected_head_ids = [
        str(stock["printer_head"]["printer_head_id"])
        for stock in stock_specs
    ]
    expected_settings = [
        {
            "print_pulse_width_us": int(
                stock["printer_head"]["print_pulse_width_us"]
            ),
            "print_pressure_psi": float(
                stock["printer_head"]["print_pressure_psi"]
            ),
        }
        for stock in stock_specs
    ]
    stage_evidence = [dict(item.get("evidence") or {}) for item in stage_actions]
    boundary_evidence = [
        dict(item.get("evidence") or {}) for item in boundary_actions
    ]
    begins = list(intent_lifecycle.get("begins", ()))
    attachments = list(intent_lifecycle.get("attachments", ()))
    completions = list(intent_lifecycle.get("completions", ()))
    discard_batches = list(intent_lifecycle.get("discard_batches", ()))
    completed_history = getattr(machine.command_queue, "completed", ())
    command_events = getattr(machine, "command_event_history", ())
    completed_history_limit = getattr(completed_history, "maxlen", None)
    event_history_limit = getattr(command_events, "maxlen", None)
    history = {
        "simulator_completed_history_count": len(completed_history),
        "simulator_completed_history_limit": completed_history_limit,
        "simulator_event_history_count": len(command_events),
        "simulator_event_history_limit": event_history_limit,
        "report_event_retention": dict(event_retention),
    }
    settings_match = len(stage_evidence) == 2 and all(
        all(
            (
                evidence.get("pass_index") == index + 1,
                evidence.get("stock_id") == expected_stock_ids[index],
                evidence.get("printer_head_id") == expected_head_ids[index],
                evidence.get("requested_print_pulse_width_us")
                == expected_settings[index]["print_pulse_width_us"],
                evidence.get("effective_print_pulse_width_us")
                == expected_settings[index]["print_pulse_width_us"],
                math.isclose(
                    float(evidence.get("requested_print_pressure_psi", -1)),
                    expected_settings[index]["print_pressure_psi"],
                    rel_tol=0.0,
                    abs_tol=0.01,
                ),
                math.isclose(
                    float(evidence.get("effective_print_pressure_psi", -1)),
                    expected_settings[index]["print_pressure_psi"],
                    rel_tol=0.0,
                    abs_tol=0.01,
                ),
            )
        )
        for index, evidence in enumerate(stage_evidence)
    )
    exchange_safe = (
        len(stage_evidence) == 2
        and all(
            evidence.get("array_state_before") == "idle"
            and evidence.get("queue_drained_before") is True
            and evidence.get("queue_drained_after") is True
            for evidence in stage_evidence
        )
        and stage_evidence[0].get("previous_printer_head_id") is None
        and stage_evidence[0].get("returned_previous") is False
        and stage_evidence[1].get("previous_stock_id") == expected_stock_ids[0]
        and stage_evidence[1].get("previous_printer_head_id")
        == expected_head_ids[0]
        and stage_evidence[1].get("returned_previous") is True
    )
    boundaries_valid = (
        len(boundary_evidence) == 2
        and [item.get("pass_index") for item in boundary_evidence] == [1, 2]
        and [item.get("observed_completed_count") for item in boundary_evidence]
        == [expected_well_count, expected_completion_count]
        and [item.get("plan_state") for item in boundary_evidence]
        == ["active", "completed"]
        and all(
            item.get("controller_state") == "idle"
            and item.get("queue_drained") is True
            and item.get("checkpoint_state") == "clean"
            and item.get("outstanding_intent_count") == 0
            for item in boundary_evidence
        )
    )
    history_bounded = (
        isinstance(completed_history_limit, int)
        and len(completed_history) <= completed_history_limit
        and isinstance(event_history_limit, int)
        and len(command_events) <= event_history_limit
        and int(event_retention.get("retained_count", 0))
        <= int(event_retention.get("limit", 0))
    )
    checks = result.setdefault("checks", {})
    multi_checks = {
        "two_distinct_stock_ids": len(set(expected_stock_ids)) == 2,
        "two_distinct_printer_head_ids": len(set(expected_head_ids)) == 2,
        "two_stock_passes_recorded": result.get("stock_pass_count") == 2,
        "head_exchange_idle_and_drained": exchange_safe,
        "stock_head_settings_match": settings_match,
        "stock_pass_boundaries_valid": boundaries_valid,
        "intent_lifecycle_exact_without_discards": (
            len(begins)
            == len(attachments)
            == len(completions)
            == expected_completion_count
            and not discard_batches
        ),
        "event_history_bounded": history_bounded,
        "virtual_head_exchange_events_exact": (
            int(
                event_retention.get("counts", {}).get(
                    "virtual_head_exchange", 0
                )
            )
            == 2
        ),
    }
    checks.update(multi_checks)
    evidence = {
        "stock_identities": expected_stock_ids,
        "head_identities": expected_head_ids,
        "head_staging": stage_evidence,
        "pass_boundaries": boundary_evidence,
        "pass_settings": expected_settings,
        "intent_reconciliation": {
            "begin_count": len(begins),
            "attachment_count": len(attachments),
            "completion_count": len(completions),
            "discard_batch_count": len(discard_batches),
        },
        "event_history": history,
        "terminal": {
            "plan_state": result.get("terminal_plan_state"),
            "completion_count": result.get("stock_well_completion_count"),
            "pass_terminal_states": result.get("pass_terminal_states"),
        },
        "checks": multi_checks,
    }
    result["multi_stock_head_exchange"] = evidence
    if not all(multi_checks.values()):
        failed = [name for name, passed in multi_checks.items() if not passed]
        raise RuntimeError(
            "multi-stock lifecycle invariants failed: " + ", ".join(failed)
        )
    return result


def _progress_added_count(experiment_model: Any) -> int:
    total = 0
    for entry in (experiment_model.progress_data or {}).values():
        for reagent in (entry.get("reagents") or {}).values():
            total += int(reagent.get("added_droplets", 0))
    return total


def _contains_ordered_subsequence(
    values: list[str],
    expected: tuple[str, ...],
) -> bool:
    iterator = iter(values)
    return all(any(value == target for value in iterator) for target in expected)


def _validate_soft_stop_paused_scenario(
    *,
    experiment_model: Any,
    fixture_info: dict[str, Any],
    controller: Any,
    machine: Any,
    request_evidence: dict[str, Any],
    completed_count: int,
    errors: list[dict[str, Any]],
    unexpected_dialogs: list[dict[str, Any]],
    intent_lifecycle: dict[str, Any],
) -> dict[str, Any]:
    from AuthoritativeExecutionLoad import inspect_authoritative_execution
    from ExecutionPlan import ExecutionPlanState, load_execution_plan
    from ExecutionResumeStore import load_execution_resume

    experiment_dir = Path(fixture_info["experiment_dir"])
    design = json.loads(
        Path(experiment_model.experiment_file_path).read_text(encoding="utf-8")
    )
    bundle = inspect_authoritative_execution(experiment_dir, design)
    plan = load_execution_plan(experiment_model.execution_plan_file_path)
    checkpoint = load_execution_resume(experiment_model.execution_resume_file_path)
    eligibility = experiment_model.get_execution_resume_eligibility() or {}
    trigger_count = int(request_evidence["trigger_count"])
    maximum_catchup = int(
        request_evidence.get("maximum_completion_catchup", 0)
    )
    catchup = int(completed_count) - trigger_count
    soft_stop_events = list(intent_lifecycle.get("soft_stop_events", ()))
    watermark = next(
        (
            item
            for item in soft_stop_events
            if item.get("event") == "watermark_observed"
        ),
        {},
    )
    clear = next(
        (
            item
            for item in soft_stop_events
            if item.get("event") == "queue_clear_completed"
        ),
        {},
    )
    clear_result = dict(clear.get("clear_result") or {})
    audit_rows = _read_audit_rows(experiment_model)
    audit_types = [str(row.get("event_type")) for row in audit_rows]
    checks = {
        "request_trigger_exact": request_evidence.get("clicked_count")
        == trigger_count,
        "completion_catchup_bounded": 1 <= catchup <= maximum_catchup,
        "plan_remains_active": plan.state is ExecutionPlanState.ACTIVE,
        "plan_identity_unchanged": plan.plan_id == fixture_info["plan_id"],
        "authoritative_bundle_valid": bool(bundle.valid),
        "checkpoint_paused": checkpoint.state == "paused",
        "checkpoint_empty": not checkpoint.intents,
        "eligibility_ready_to_resume": eligibility.get("status")
        == "ready_to_resume",
        "watermark_confirmed": bool(watermark.get("pause_watermark_reached"))
        and bool(watermark.get("transport_paused")),
        "clear_confirmed": bool(clear_result.get("status_confirmed")),
        "clear_certain": not bool(clear.get("soft_stop_uncertain")),
        "resume_ready": controller.get_array_run_state() == "resume_ready",
        "simulator_queue_empty": bool(machine.check_if_all_completed()),
        "audit_boundary_ordered": _contains_ordered_subsequence(
            audit_types,
            (
                "print_array_requested",
                "print_array_started",
                "print_array_soft_stop_requested",
                "print_array_paused",
            ),
        ),
        "no_errors": not errors,
        "no_unexpected_dialogs": not unexpected_dialogs,
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise RuntimeError(
            "paused soft-stop invariants failed: " + ", ".join(failed)
        )
    return {
        "checks": checks,
        "plan_state": plan.state.value,
        "plan_id": plan.plan_id,
        "plan_revision": plan.plan_revision,
        "checkpoint_state": checkpoint.state,
        "checkpoint_intent_count": len(checkpoint.intents),
        "eligibility_status": eligibility.get("status"),
        "completed_count": int(completed_count),
        "request_completion_count": trigger_count,
        "completion_catchup": catchup,
        "watermark": watermark,
        "clear": clear,
        "audit_rows": audit_rows,
    }


def _validate_soft_stop_completed_scenario(
    *,
    experiment_model: Any,
    fixture_info: dict[str, Any],
    well_updates: list[str],
    array_states: list[str],
    array_complete_count: int,
    errors: list[dict[str, Any]],
    unexpected_dialogs: list[dict[str, Any]],
    starvation_events: list[dict[str, Any]],
    intent_lifecycle: dict[str, Any],
    paused_validation: dict[str, Any],
    quiescence: dict[str, Any],
) -> dict[str, Any]:
    from AuthoritativeExecutionLoad import inspect_authoritative_execution
    from ExecutionPlan import ExecutionPlanState, load_execution_plan
    from ExecutionResumeStore import load_execution_resume

    experiment_dir = Path(fixture_info["experiment_dir"])
    expected_wells = tuple(fixture_info["well_ids"])
    stock_ids = tuple(fixture_info["stock_ids"])
    expected_pairs = {
        (stock_id, well_id)
        for stock_id in stock_ids
        for well_id in expected_wells
    }
    begins = list(intent_lifecycle.get("begins", ()))
    attachments = list(intent_lifecycle.get("attachments", ()))
    completions = list(intent_lifecycle.get("completions", ()))
    discard_batches = list(intent_lifecycle.get("discard_batches", ()))
    discarded_ids = [
        intent_id
        for batch in discard_batches
        for intent_id in batch.get("intent_ids", ())
    ]
    begin_by_id = {item.get("intent_id"): item for item in begins}
    begun_ids = [item.get("intent_id") for item in begins]
    completed_ids = list(completions)
    attached_ids = [item.get("intent_id") for item in attachments]
    sequences = [item.get("command_seq32") for item in attachments]
    sequences_by_session: dict[str, list[Any]] = {}
    for item in attachments:
        session_id = str(
            item.get("application_session_id") or "single_session"
        )
        sequences_by_session.setdefault(session_id, []).append(
            item.get("command_seq32")
        )
    completed_pairs = [
        (
            str(begin_by_id[intent_id].get("stock_id")),
            str(begin_by_id[intent_id].get("well_id")),
        )
        for intent_id in completed_ids
        if intent_id in begin_by_id
    ]
    discarded_pairs = [
        (
            str(begin_by_id[intent_id].get("stock_id")),
            str(begin_by_id[intent_id].get("well_id")),
        )
        for intent_id in discarded_ids
        if intent_id in begin_by_id
    ]
    checkpoint = load_execution_resume(experiment_model.execution_resume_file_path)
    design = json.loads(
        Path(experiment_model.experiment_file_path).read_text(encoding="utf-8")
    )
    bundle = inspect_authoritative_execution(experiment_dir, design)
    terminal_plan = load_execution_plan(experiment_model.execution_plan_file_path)
    eligibility = experiment_model.get_execution_resume_eligibility() or {}
    completed_updates = [
        well_id for well_id in well_updates if well_id in set(expected_wells)
    ]
    target = int(fixture_info["target_dispenses_per_stock"])
    targets_match = all(
        int(
            ((bundle.progress_wells.get(well_id, {}).get("reagents") or {})
             .get(stock_id, {}))
            .get("target_droplets", -1)
        )
        == target
        and int(
            ((bundle.progress_wells.get(well_id, {}).get("reagents") or {})
             .get(stock_id, {}))
            .get("added_droplets", -1)
        )
        == target
        for stock_id, well_id in expected_pairs
    )
    retired = completed_ids + discarded_ids
    reissued_pairs = all(
        Counter(completed_pairs)[pair] == 1
        and sum(
            1
            for item in begins
            if (str(item.get("stock_id")), str(item.get("well_id"))) == pair
        )
        >= 2
        for pair in discarded_pairs
    )
    audit_rows = _read_audit_rows(experiment_model)
    audit_types = [str(row.get("event_type")) for row in audit_rows]
    checks = {
        "checkpoint_clean": checkpoint.state == "clean",
        "checkpoint_empty": not checkpoint.intents,
        "begun_intent_occurrences_reconcilable": (
            Counter(begun_ids) == Counter(retired)
            and all(
                count == 1
                or (
                    count == 2
                    and intent_id in discarded_ids
                    and intent_id in completed_ids
                )
                for intent_id, count in Counter(begun_ids).items()
            )
        ),
        "attachments_exact": Counter(attached_ids) == Counter(begun_ids),
        "sequences_unique_monotonic": all(
            session_sequences
            == sorted(set(session_sequences))
            for session_sequences in sequences_by_session.values()
        ),
        "terminal_intent_partition_exact": (
            Counter(retired) == Counter(begun_ids)
            and all(
                Counter(completed_ids)[intent_id] == 1
                and Counter(discarded_ids)[intent_id] == 1
                for intent_id in set(completed_ids) & set(discarded_ids)
            )
        ),
        "discarded_pairs_reissued": bool(discarded_ids) and reissued_pairs,
        "completed_pairs_exactly_once": Counter(completed_pairs)
        == Counter(expected_pairs),
        "completion_count_exact": len(completed_ids) == len(expected_pairs),
        "well_updates_exact": Counter(completed_updates)
        == Counter(expected_wells),
        "progress_targets_exact": targets_match,
        "authoritative_bundle_valid": bool(bundle.valid),
        "terminal_plan_completed": terminal_plan.state
        is ExecutionPlanState.COMPLETED,
        "terminal_intents_unambiguous": (
            not eligibility.get("ambiguous_intent_ids")
            and not eligibility.get("repairable_intent_ids")
        ),
        "plan_identity_unchanged": terminal_plan.plan_id
        == fixture_info["plan_id"],
        "array_completed_once": array_complete_count == 1,
        "ui_resumed_once": array_states.count("running") == 2,
        "audit_lifecycle_ordered": _contains_ordered_subsequence(
            audit_types,
            (
                "print_array_requested",
                "print_array_started",
                "print_array_soft_stop_requested",
                "print_array_paused",
                "print_array_requested",
                "print_array_resumed",
                "print_array_started",
                "print_array_completed",
            ),
        ),
        "paused_boundary_valid": all(
            paused_validation.get("checks", {}).values()
        ),
        "quiescence_valid": (
            quiescence.get("starting_completion_count")
            == quiescence.get("ending_completion_count")
            and quiescence.get("starting_progress_count")
            == quiescence.get("ending_progress_count")
            and quiescence.get("simulator_queue_empty") is True
        ),
        "no_errors": not errors,
        "no_unexpected_dialogs": not unexpected_dialogs,
        "no_lookahead_starvation": not starvation_events,
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise RuntimeError(
            "soft-stop/resume terminal invariants failed: "
            + ", ".join(failed)
        )
    return {
        "checks": checks,
        "checkpoint_state": checkpoint.state,
        "intent_count": len(completed_ids),
        "begin_intent_count": len(begun_ids),
        "discarded_intent_count": len(discarded_ids),
        "discard_batch_count": len(discard_batches),
        "discarded_intent_ids": discarded_ids,
        "discarded_stock_well_pairs": [
            {"stock_id": stock_id, "well_id": well_id}
            for stock_id, well_id in discarded_pairs
        ],
        "stock_well_completion_count": len(completed_pairs),
        "observed_completed_intent_count": len(completed_ids),
        "terminal_plan_state": terminal_plan.state.value,
        "terminal_plan_revision": terminal_plan.plan_revision,
        "audit_rows": audit_rows,
        "paused_boundary": paused_validation,
        "quiescence": quiescence,
        "intent_command_sequences": sequences,
        "intent_command_sequences_by_session": sequences_by_session,
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
    pressure_assessment = responsiveness.get("pressure_render_assessment", {})
    lines = [
        f"Scenario: {report['run']['scenario_name']} v{report['run']['scenario_version']}",
        f"Workload: {report['workload']['workload_id']}",
        f"Run mode: {report['run']['run_mode']}",
        f"Classification: {report['classification']['status']}",
        f"Duration: {report['run']['duration_ms']:.3f} ms",
        (
            "Wells: "
            f"{workflow.get('completed_well_count', 0)}/"
            f"{workflow.get('expected_well_count', 0)}"
        ),
        (
            "Stock/well completions: "
            f"{workflow.get('completed_stock_well_count', workflow.get('completed_well_count', 0))}/"
            f"{workflow.get('expected_stock_well_completion_count', report['workload'].get('expected_completion_count', 0))}"
        ),
        f"Array complete signals: {workflow.get('array_complete_count', 0)}",
        f"Maximum event-loop gap: {gap.get('maximum')} ms",
        (
            "Pressure renders: "
            f"{pressure_render.get('count', 0)}; "
            f"p95 {pressure_render.get('p95')} ms; "
            f"max {pressure_render.get('maximum')} ms"
        ),
        (
            "Pressure updates coalesced: "
            f"{pressure_assessment.get('coalesced_update_count', 0)}/"
            f"{pressure_assessment.get('update_signal_count', 0)}; "
            f"interval {pressure_assessment.get('render_interval_ms')} ms"
        ),
        f"Queue starvation events: {queue.get('unexpected_starvation_count', 0)}",
        f"Execution intents: {persistence.get('intent_count', 0)}",
        (
            "Checkpoint retained/max intents: "
            f"{persistence.get('checkpoint_retained_intent_count', 0)} / "
            f"{persistence.get('checkpoint_max_observed_intent_count', 0)}"
        ),
        (
            "Authoritative hot-path reads / resume loads: "
            f"{persistence.get('authoritative_io', {}).get('hot_path_read_count', 0)} / "
            f"{persistence.get('authoritative_io', {}).get('execution_resume_hot_path_disk_load_count', 0)}"
        ),
        (
            "Resume/progress fsync counts: "
            f"{persistence.get('authoritative_io', {}).get('resume_save_fsync_count', 0)} / "
            f"{persistence.get('authoritative_io', {}).get('progress_write_fsync_count', 0)}"
        ),
        (
            "Progress full rebuilds / cached updates: "
            f"{persistence.get('progress_snapshot', {}).get('mode_counts', {}).get('full_rebuild', 0)} / "
            f"{persistence.get('progress_snapshot', {}).get('mode_counts', {}).get('cached_update', 0)}"
        ),
        (
            "Progress non-durable p95: "
            f"{persistence.get('progress_snapshot', {}).get('non_durable_write_ms', {}).get('p95', 0.0)} ms"
        ),
        (
            "Progress schema/final bytes/v1 ratio: "
            f"v{persistence.get('progress_format', {}).get('schema_version', 'unknown')} / "
            f"{persistence.get('progress_format', {}).get('encoded_size_bytes', 0)} / "
            f"{persistence.get('progress_format', {}).get('encoded_to_v1_ratio', 0.0):.4f}"
        ),
        (
            "Cumulative progress serialized bytes: "
            f"{persistence.get('cumulative_progress_serialized_bytes', 0)}"
        ),
        (
            "Pass starts / p95 / max: "
            f"{persistence.get('pass_start', {}).get('count', 0)} / "
            f"{persistence.get('pass_start', {}).get('total_duration_ms', {}).get('p95', 0.0)} ms / "
            f"{persistence.get('pass_start', {}).get('total_duration_ms', {}).get('maximum', 0.0)} ms"
        ),
        (
            "Pass-start history reads / full refreshes: "
            f"{sum(item.get('io_delta', {}).get('revision_read_count', 0) for item in persistence.get('pass_start', {}).get('records', []))} / "
            f"{sum(item.get('full_bundle_refresh_count', 0) for item in persistence.get('pass_start', {}).get('records', []))}"
        ),
        (
            "Terminal transitions / p95 / max: "
            f"{persistence.get('terminal_transition', {}).get('count', 0)} / "
            f"{persistence.get('terminal_transition', {}).get('total_duration_ms', {}).get('p95', 0.0)} ms / "
            f"{persistence.get('terminal_transition', {}).get('total_duration_ms', {}).get('maximum', 0.0)} ms"
        ),
        (
            "Terminal revision reads / full validations: "
            f"{sum(item.get('io_delta', {}).get('revision_read_count', 0) for item in persistence.get('terminal_transition', {}).get('records', []))} / "
            f"{sum(item.get('full_bundle_refresh_count', 0) for item in persistence.get('terminal_transition', {}).get('records', []))}"
        ),
        (
            "Injected stall: "
            f"{responsiveness.get('injected_stall_assessment', {}).get('decision', 'not_requested')}"
        ),
        (
            "Stress responsiveness: "
            f"{responsiveness.get('stress_assessment', {}).get('decision', 'not_applicable')}"
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

    fixture = load_virtual_print_array_fixture(
        config.fixture_path,
        scenario_id=config.scenario_id,
    )
    workload_id = str(fixture["fixture_id"])
    expected_wells = fixture_well_ids(fixture)
    stock_specs = _fixture_stock_specs(fixture)
    workflow_strategy = SCENARIO_WORKFLOW_STRATEGIES[workload_id]
    is_soft_stop_resume = workflow_strategy == "soft_stop_resume"
    is_authoritative_reload_resume = (
        workflow_strategy == "authoritative_reload_resume"
    )
    is_multi_stock_lifecycle = (
        workflow_strategy == "multi_stock_head_exchange"
    )
    is_pause_resume_lifecycle = (
        is_soft_stop_resume or is_authoritative_reload_resume
    )
    is_targeted_lifecycle = (
        is_pause_resume_lifecycle or is_multi_stock_lifecycle
    )
    expected_stock_count = len(stock_specs)
    expected_completions = len(expected_wells) * expected_stock_count
    stamp = _run_stamp()
    short_commit = identity["source"].get("git_short_commit") or "unknown"
    run_id = config.run_id or str(uuid.uuid4())
    report_dir = (
        config.output_root
        / workload_id
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
    event_log = _BoundedEventLog()
    context = ScenarioContext(
        scenario_id=SCENARIO_NAME,
        workload_id=workload_id,
        report_dir=report_dir,
        scenario_root=scenario_root,
        screenshots_dir=screenshots_dir,
        timeout_seconds=config.timeout_seconds,
        record_event=event_log.record,
    )
    if is_authoritative_reload_resume:
        context.application_session_id = "session_1"
    errors = context.errors
    dialogs = context.dialogs
    unexpected_dialogs = context.unexpected_dialogs
    well_updates: list[str] = []
    array_states = context.array_states
    command_lifecycle_counts: Counter[str] = Counter()
    command_event_count = 0
    minimum_queue_depth: int | None = None
    maximum_queue_depth: int | None = None
    starvation_events: list[dict[str, Any]] = []
    screenshots = context.screenshots
    array_complete_count = 0
    paint_event_count = 0
    pressure_update_signal_count = 0
    pressure_render_interval_ms: int | None = None
    pressure_render_timestamps_ns: list[int] = []
    pressure_timer_active_after_teardown: bool | None = None
    pass_terminal_states: list[str] = []
    stock_passes: list[dict[str, Any]] = []
    current_pass_index = -1
    fixture_info: dict[str, Any] | None = None
    validation: dict[str, Any] = {}
    paused_validation: dict[str, Any] = {}
    quiescence_evidence: dict[str, Any] = {}
    authoritative_reload_evidence: dict[str, Any] = {}
    terminal_lifecycle: dict[str, Any] = {}
    session_1_lifecycle: dict[str, Any] = {}
    session_1_progress_snapshot: dict[str, Any] = {}
    session_1_durable_io_snapshot: dict[str, Any] = {}
    session_1_read_snapshot: dict[str, Any] = {}
    failure_text: str | None = None
    phases = NamedPhaseRecorder(
        max_records=max(50_000, expected_completions * 24)
    )
    resources = ProcessResourceSampler(max_samples=100_000)
    probe = QtEventLoopProbe(
        heartbeat_interval_ms=10,
        stack_capture_ms=250.0,
        observer_interval_ms=5,
        resource_interval_ms=100,
        phase_recorder=phases,
        resource_sampler=resources,
    )
    context.probe = probe
    components = None
    instrumentation = None
    io_observer = None
    progress_observer = None
    paint_filter = None
    app = None
    probe_started = False
    application_stdout = io.StringIO()
    stdout_redirect = None
    machine_cleanup = {
        "command_timer_active": None,
        "connection_timer_active": None,
        "deferred_timer_count": None,
    }

    try:
        from PySide6 import QtCore, QtWidgets
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
        context.app = app
        context.qt_core = QtCore
        font_evidence: dict[str, Any] = {}

        def prepare_fixture() -> dict[str, Any]:
            simulation_config = SimulationConfig(
                timing=SimulationTimingPolicy(
                    speed_multiplier=config.speed_multiplier,
                ),
                completed_history_limit=512,
                event_history_limit=4096,
            )
            context.dependencies = composition.simulation_dependencies(
                scenario_root,
                machine_factory=make_simulated_machine_factory(simulation_config),
            )
            for root in (
                context.dependencies.roots.config_root,
                context.dependencies.roots.experiments_root,
                context.dependencies.roots.calibration_memory_root,
            ):
                if not _resolved_beneath(root, scenario_root):
                    raise RuntimeError(f"simulation root escaped scenario root: {root}")
            context.fixture_info = _create_prepared_fixture(
                context.dependencies.roots.experiments_root / workload_id,
                fixture,
            )
            return {
                "experiment_dir": context.fixture_info["experiment_dir"],
                "design_path": context.fixture_info["design_path"],
            }

        prepare_authoritative_fixture(context, prepare_fixture)
        dependencies = context.dependencies
        fixture_info = context.fixture_info
        assert fixture_info is not None

        def launch_application() -> dict[str, Any]:
            nonlocal font_evidence
            try:
                font_evidence = apply_and_validate_sil_application_font(app)
            except SilQtFontEnvironmentError as exc:
                qt_identity["font"] = dict(exc.evidence)
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
            context.experiment_model.load_experiment(
                str(fixture_info["design_path"]),
                str(fixture_info["experiment_dir"]),
            )
            eligibility = context.model.load_authoritative_execution_runtime()
            if eligibility["status"] not in {"ready_to_start", "ready_to_resume"}:
                raise RuntimeError(
                    "unexpected execution activation eligibility: "
                    f"{eligibility['status']}"
                )
            context.view.show()
            app.processEvents()
            banner = getattr(context.view, "simulation_identity_banner", None)
            banner_label = getattr(
                context.view,
                "simulation_identity_label",
                None,
            )
            well_labels = context.view.well_plate_widget.well_labels
            return {
                "eligibility": eligibility["status"],
                "visible": bool(config.visible),
                "font_rendering": font_evidence,
                "simulation_banner": {
                    "present": banner is not None,
                    "visible": bool(banner is not None and banner.isVisible()),
                    "object_name": (
                        banner.objectName() if banner is not None else None
                    ),
                    "text": (
                        banner_label.text() if banner_label is not None else None
                    ),
                },
                "plate_widget": {
                    "rows": len(well_labels),
                    "columns": len(well_labels[0]) if well_labels else 0,
                    "well_label_count": sum(len(row) for row in well_labels),
                },
            }

        launch_simulated_application(context, launch_application)
        components = context.components
        model = components.model
        machine = components.machine
        controller = components.controller
        view = components.view
        experiment_model = model.experiment_model
        pressure_render_interval_ms = int(
            view.pressure_box._pressure_render_timer.interval()
        )

        heads_by_stock = {
            head.get_stock_id(): head
            for head in model.printer_head_manager.printer_heads
            if not getattr(head, "calibration_chip", False)
        }
        calibrated_heads: dict[str, Any] = {}
        for stock in stock_specs:
            stock_id = _stock_id(stock)
            printer_head = heads_by_stock.get(stock_id)
            if printer_head is None:
                raise RuntimeError(
                    f"fixture printer head was not created for stock {stock_id}"
                )
            head_spec = stock["printer_head"]
            printer_head.set_identity_metadata(
                printer_head_id=head_spec["printer_head_id"],
                display_name=f"Virtual workflow head {stock['factor_name']}",
                tags=["simulation", workload_id],
            )
            printer_head.set_absolute_volume(float(head_spec["initial_volume_uL"]))
            printer_head.target_droplet_volume = float(stock["droplet_volume_nL"])
            calibration = experiment_model.apply_execution_calibration(
                stock_id=stock_id,
                new_effective_volume_nL=float(stock["droplet_volume_nL"]),
                printing_mode=stock["printing_mode"],
                printer_head_id=head_spec["printer_head_id"],
                factor_name=stock["factor_name"],
                option_name=None,
                is_fill=False,
                calibration_payload={
                    "measured_volume_nL": float(stock["droplet_volume_nL"]),
                    "pw_us": int(head_spec["print_pulse_width_us"]),
                    "pressure_psi": float(head_spec["print_pressure_psi"]),
                    "run_id": workload_id,
                    "phase": "canned_virtual_calibration",
                    "timestamp": "2026-07-23T00:00:00Z",
                    "source_row_fingerprint": [
                        workload_id,
                        stock_id,
                        int(head_spec["print_pulse_width_us"]),
                        float(head_spec["print_pressure_psi"]),
                    ],
                    "original_printing_mode": stock["printing_mode"],
                },
                timestamp_utc="2026-07-23T00:00:00Z",
            )
            if (
                calibration["plan"].state is not ExecutionPlanState.ACTIVE
                or calibration["record"]["printer_head_id"]
                != head_spec["printer_head_id"]
            ):
                raise RuntimeError(
                    f"canned execution calibration was not activated for {stock_id}"
                )
            calibrated_heads[stock_id] = printer_head

        def record_event(kind: str, **values: Any) -> None:
            event_log.record(kind, **values)

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
            nonlocal command_event_count, minimum_queue_depth, maximum_queue_depth
            item = dict(payload)
            command_event_count += 1
            command_lifecycle_counts[str(item.get("event"))] += 1
            depth = int(item.get("queue_depth", 0))
            minimum_queue_depth = (
                depth if minimum_queue_depth is None else min(minimum_queue_depth, depth)
            )
            maximum_queue_depth = (
                depth if maximum_queue_depth is None else max(maximum_queue_depth, depth)
            )
            record_event("command", **item)

        def on_pressure_update() -> None:
            nonlocal pressure_update_signal_count
            pressure_update_signal_count += 1

        model.well_plate.well_state_changed_signal.connect(on_well_update)
        model.machine_model.pressure_updated.connect(on_pressure_update)
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
            state = controller.get_array_run_state()
            current = (
                stock_passes[current_pass_index]
                if 0 <= current_pass_index < len(stock_passes)
                else None
            )
            completed = (
                len(well_updates) - int(current["starting_well_update_count"])
                if current is not None
                else 0
            )
            if (
                state == "running"
                and current is not None
                and completed < len(expected_wells)
            ):
                item = {
                    "completed_in_pass": completed,
                    "pass_index": current_pass_index + 1,
                    "stock_id": current["stock_id"],
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
        context.paint_filter = paint_filter
        install_dialog_handler(
            context,
            (
                EXPECTED_SOFT_STOP_RESUME_DIALOGS
                if is_pause_resume_lifecycle
                else EXPECTED_START_DIALOGS
            ),
        )

        completed_count = lambda: len(
            [well for well in well_updates if well in set(expected_wells)]
        )

        def on_pressure_rendered() -> None:
            if controller.get_array_run_state() == "running":
                pressure_render_timestamps_ns.append(time.perf_counter_ns())

        def current_pass_context() -> dict[str, Any] | None:
            if not (0 <= current_pass_index < len(stock_passes)):
                return None
            current = stock_passes[current_pass_index]
            return {
                "pass_index": int(current["pass_index"]),
                "stock_id": str(current["stock_id"]),
            }

        instrumentation = _install_instrumentation(
            phases,
            experiment_model=experiment_model,
            controller=controller,
            machine=machine,
            well_plate_widget=view.well_plate_widget,
            pressure_plot_widget=view.pressure_box,
            experiment_task_list=view.experiment_task_list,
            inject_ms=config.inject_ui_stall_ms,
            inject_after_completion=config.inject_after_completion,
            completed_count=completed_count,
            io_observer=PersistenceIoObserver(fixture_info["experiment_dir"]),
            pressure_rendered=on_pressure_rendered,
            pass_context=current_pass_context,
        )
        io_observer = instrumentation.io_observer
        progress_observer = ProgressSnapshotObserver(experiment_model)
        progress_observer.install()
        io_observer.install()
        context.instrumentation = instrumentation
        context.io_observer = io_observer
        context.progress_observer = progress_observer

        probe.start(app)
        probe_started = True
        context.probe_started = True

        connect_machine_ready(
            context,
            simulated_port=SIMULATED_PORT,
            dispense_frequency_hz=int(
                fixture["simulation"]["dispense_frequency_hz"]
            ),
        )

        staging_slot = int(fixture["simulation"].get("staging_slot", 0))

        def stage_stock_head(stock_index: int) -> tuple[str, dict[str, Any]]:
            return stage_virtual_head(
                context,
                stock_index=stock_index,
                stock_specs=stock_specs,
                calibrated_heads=calibrated_heads,
                staging_slot=staging_slot,
                stock_id_for=_stock_id,
            )

        first_stock_id, first_head = stage_stock_head(0)
        enable_pressure_regulation(context)
        capture_milestone(
            context,
            (
                "session_1_ready"
                if is_authoritative_reload_resume
                else "stock_1_ready"
                if is_multi_stock_lifecycle
                else "ready"
            ),
            evidence={
                "stock_id": first_stock_id,
                "printer_head_id": first_head["printer_head_id"],
            },
        )

        midpoint_completion = max(1, expected_completions // 2)
        midpoint_captured = False
        stdout_redirect = redirect_stdout(application_stdout)
        stdout_redirect.__enter__()
        context.stdout_redirect = stdout_redirect
        for stock_index, stock in enumerate(stock_specs):
            print(
                f"Starting stock pass {stock_index + 1}/{expected_stock_count}",
                file=sys.stderr,
                flush=True,
            )
            current_pass_index = stock_index
            if stock_index == 0:
                stock_id = first_stock_id
                head = first_head
            else:
                stock_id, head = stage_stock_head(stock_index)
                if is_multi_stock_lifecycle:
                    capture_milestone(
                        context,
                        f"stock_{stock_index + 1}_staged",
                        evidence={
                            "stock_id": stock_id,
                            "printer_head_id": head["printer_head_id"],
                        },
                    )
            preflight_suppression = (
                instrumentation.suppress_phases("persistence.guard_bundle")
                if instrumentation is not None
                else nullcontext()
            )
            with preflight_suppression:
                preflight = controller.get_print_array_imaging_calibration_preflight()
            if not preflight.get("ok"):
                raise RuntimeError(
                    "canned imaging-calibration preflight failed: "
                    + str(preflight.get("message") or preflight.get("code"))
                )
            pass_record = {
                "pass_index": stock_index + 1,
                "stock_id": stock_id,
                "starting_well_update_count": len(well_updates),
                "started_monotonic_ns": time.perf_counter_ns(),
            }
            stock_passes.append(pass_record)
            record_event(
                "stock_pass_started",
                pass_index=stock_index + 1,
                stock_id=stock_id,
            )
            start_array_via_ui(
                context,
                expected_running_count=stock_index + 1,
            )
            pass_record["running_monotonic_ns"] = time.perf_counter_ns()
            if stock_index == 0:
                capture_milestone(
                    context,
                    (
                        "session_1_printing"
                        if is_authoritative_reload_resume
                        else "stock_1_printing"
                        if is_multi_stock_lifecycle
                        else "printing"
                    ),
                    evidence={"stock_id": stock_id},
                )
            elif is_multi_stock_lifecycle:
                capture_milestone(
                    context,
                    f"stock_{stock_index + 1}_printing",
                    evidence={
                        "stock_id": stock_id,
                        "printer_head_id": head["printer_head_id"],
                    },
                )

            if is_pause_resume_lifecycle:
                lifecycle = fixture["lifecycle"]
                request_result = request_soft_stop_via_ui(
                    context,
                    completed_count=completed_count,
                    trigger_count=int(
                        lifecycle["request_after_completion_count"]
                    ),
                    timeout_seconds=config.timeout_seconds,
                )
                request_evidence = dict(request_result["evidence"])
                request_evidence["maximum_completion_catchup"] = int(
                    lifecycle["maximum_completion_catchup"]
                )
                capture_milestone(
                    context,
                    (
                        "session_1_stop_requested"
                        if is_authoritative_reload_resume
                        else "stop_requested"
                    ),
                    evidence=request_evidence,
                )
                wait_for_array_state(
                    context,
                    state="resume_ready",
                    timeout_seconds=10.0,
                    label="soft-stop resume-ready state",
                )
                paused_validation = validate_paused_bundle(
                    context,
                    lambda: _validate_soft_stop_paused_scenario(
                        experiment_model=experiment_model,
                        fixture_info=fixture_info,
                        controller=controller,
                        machine=machine,
                        request_evidence=request_evidence,
                        completed_count=completed_count(),
                        errors=errors,
                        unexpected_dialogs=unexpected_dialogs,
                        intent_lifecycle=instrumentation.lifecycle_snapshot(),
                    ),
                )
                capture_milestone(
                    context,
                    (
                        "session_1_stopped"
                        if is_authoritative_reload_resume
                        else "stopped"
                    ),
                    evidence={
                        "completed": completed_count(),
                        "checkpoint_state": paused_validation[
                            "checkpoint_state"
                        ],
                        "eligibility_status": paused_validation[
                            "eligibility_status"
                        ],
                    },
                )
                quiescence_result = observe_stopped_quiescence(
                    context,
                    completed_count=completed_count,
                    progress_count=lambda: _progress_added_count(
                        experiment_model
                    ),
                    observation_ms=int(
                        lifecycle["quiescence_observation_ms"]
                    ),
                )
                quiescence_evidence = dict(quiescence_result["evidence"])
                if is_authoritative_reload_resume:
                    session_1_authoritative = capture_authoritative_bundle(context)
                    paused_inventory = (
                        session_1_authoritative.directory.rich_inventory()
                    )
                    session_1_lifecycle = instrumentation.lifecycle_snapshot()
                    first_instrumentation = instrumentation
                    first_progress_observer = progress_observer
                    first_io_observer = io_observer
                    session_1_completed_pairs = completed_stock_well_pairs(
                        session_1_lifecycle
                    )
                    session_1_cleanup_result = close_simulated_session(
                        context,
                        session_id="session_1",
                    )
                    stdout_redirect = None
                    session_1_progress_snapshot = (
                        first_progress_observer.snapshot()
                    )
                    session_1_durable_io_snapshot = (
                        first_io_observer.snapshot()
                    )
                    session_1_read_snapshot = (
                        first_io_observer.read_snapshot()
                    )
                    inventory_after_close = _file_inventory(
                        fixture_info["experiment_dir"]
                    )
                    if inventory_after_close != paused_inventory:
                        raise RuntimeError(
                            "first-session teardown mutated authoritative files"
                        )

                    context.application_session_id = "session_2"
                    simulation_config = SimulationConfig(
                        timing=SimulationTimingPolicy(
                            speed_multiplier=config.speed_multiplier,
                        ),
                        completed_history_limit=512,
                        event_history_limit=4096,
                    )
                    context.dependencies = composition.simulation_dependencies(
                        scenario_root,
                        machine_factory=make_simulated_machine_factory(
                            simulation_config
                        ),
                    )
                    dependencies = context.dependencies

                    def launch_second_application() -> dict[str, Any]:
                        context.components = (
                            composition.build_application_components(
                                CURRENT_PROFILE,
                                dependencies,
                            )
                        )
                        context.model = context.components.model
                        context.machine = context.components.machine
                        context.controller = context.components.controller
                        context.view = context.components.view
                        context.experiment_model = (
                            context.model.experiment_model
                        )
                        context.view.show()
                        app.processEvents()
                        return {
                            "fresh_components": True,
                            "runtime_active": bool(
                                context.experiment_model
                                .is_authoritative_execution_runtime_active()
                            ),
                            "scenario_root": str(scenario_root),
                        }

                    launch_simulated_application(
                        context,
                        launch_second_application,
                    )
                    components = context.components
                    model = context.model
                    machine = context.machine
                    controller = context.controller
                    view = context.view
                    experiment_model = context.experiment_model

                    model.well_plate.well_state_changed_signal.connect(
                        on_well_update
                    )
                    model.machine_model.pressure_updated.connect(
                        on_pressure_update
                    )
                    controller.array_state_changed.connect(on_array_state)
                    controller.array_complete.connect(on_array_complete)
                    controller.error_occurred_signal.connect(
                        lambda *args: on_error("controller", *args)
                    )
                    machine.error_occurred.connect(
                        lambda *args: on_error("machine", *args)
                    )
                    machine.simulation_faulted.connect(
                        lambda *args: on_error(
                            "simulation_fault", *args
                        )
                    )
                    machine.command_lifecycle_changed.connect(on_command)
                    machine.command_queue.commands_completed.connect(
                        on_queue_drained
                    )

                    paint_filter = PaintFilter(app)
                    app.installEventFilter(paint_filter)
                    context.paint_filter = paint_filter
                    install_dialog_handler(
                        context,
                        ("Resume Print Array",),
                    )
                    instrumentation = _install_instrumentation(
                        phases,
                        experiment_model=experiment_model,
                        controller=controller,
                        machine=machine,
                        well_plate_widget=view.well_plate_widget,
                        pressure_plot_widget=view.pressure_box,
                        experiment_task_list=view.experiment_task_list,
                        inject_ms=0,
                        inject_after_completion=48,
                        completed_count=completed_count,
                        io_observer=PersistenceIoObserver(
                            fixture_info["experiment_dir"]
                        ),
                        pressure_rendered=on_pressure_rendered,
                        pass_context=current_pass_context,
                    )
                    io_observer = instrumentation.io_observer
                    progress_observer = ProgressSnapshotObserver(
                        experiment_model
                    )
                    progress_observer.install()
                    io_observer.install()
                    context.instrumentation = instrumentation
                    context.io_observer = io_observer
                    context.progress_observer = progress_observer
                    probe.start(app)
                    probe_started = True
                    context.probe_started = True
                    stdout_redirect = redirect_stdout(application_stdout)
                    stdout_redirect.__enter__()
                    context.stdout_redirect = stdout_redirect

                    loaded_boundary: dict[str, Any] = {}
                    activated_boundary: dict[str, Any] = {}

                    def validate_loaded_boundary() -> Mapping[str, Any]:
                        loaded_snapshot = capture_authoritative_bundle(context)
                        loaded_boundary.update(
                            authoritative_loaded_boundary(
                                session_1_authoritative, loaded_snapshot
                            )
                        )
                        if loaded_boundary["failed_checks"]:
                            raise RuntimeError(
                                "authoritative reload boundary is invalid"
                            )
                        return loaded_boundary

                    def validate_activated_boundary() -> Mapping[str, Any]:
                        evidence = authoritative_activation_boundary(
                            session_1_authoritative,
                            capture_authoritative_bundle(context),
                            completed_pair_count=len(session_1_completed_pairs),
                        )
                        if evidence["failed_checks"]:
                            raise RuntimeError(
                                "authoritative activation boundary is invalid"
                            )
                        activated_boundary.update(evidence)
                        return activated_boundary

                    validate_reload_boundary(
                        context,
                        lambda: {
                            "between_sessions": {
                                "inventory_unchanged": (
                                    inventory_after_close
                                    == paused_inventory
                                ),
                                "first_session_cleanup": (
                                    session_1_cleanup_result["evidence"]
                                ),
                            }
                        },
                    )
                    editor_reload = drive_authoritative_reload_via_editor(
                        context,
                        experiment_dir=Path(
                            fixture_info["experiment_dir"]
                        ),
                        expected_name=workload_id,
                        before_activation=lambda: validate_reload_boundary(
                            context,
                            validate_loaded_boundary,
                        )["evidence"],
                        after_activation=lambda: validate_reload_boundary(
                            context,
                            validate_activated_boundary,
                        )["evidence"],
                    )
                    capture_milestone(
                        context,
                        "session_2_activated",
                        evidence=editor_reload["activated"],
                    )
                    connect_machine_ready(
                        context,
                        simulated_port=SIMULATED_PORT,
                        dispense_frequency_hz=int(
                            fixture["simulation"][
                                "dispense_frequency_hz"
                            ]
                        ),
                    )
                    calibrated_heads = {
                        head.get_stock_id(): head
                        for head in (
                            model.printer_head_manager.printer_heads
                        )
                        if not getattr(head, "calibration_chip", False)
                    }
                    stage_stock_head(0)
                    enable_pressure_regulation(context)
                    start_array_via_ui(
                        context,
                        expected_running_count=2,
                    )
                    capture_milestone(
                        context,
                        "session_2_resumed",
                        evidence={
                            "completed_before_resume": len(
                                session_1_completed_pairs
                            ),
                            "array_state": (
                                controller.get_array_run_state()
                            ),
                        },
                    )
                    authoritative_reload_evidence.update(
                        {
                            "session_1_paused": paused_validation,
                            "session_1_cleanup": (
                                session_1_cleanup_result["evidence"]
                            ),
                            "between_sessions": {
                                "inventory_before_close": paused_inventory,
                                "inventory_after_close": (
                                    inventory_after_close
                                ),
                                "byte_identical": (
                                    inventory_after_close
                                    == paused_inventory
                                ),
                            },
                            "session_2_loaded": loaded_boundary,
                            "session_2_activation": activated_boundary,
                            "session_1_completed_pairs": [
                                list(pair)
                                for pair in sorted(
                                    session_1_completed_pairs
                                )
                            ],
                        }
                    )
                else:
                    start_array_via_ui(
                        context,
                        expected_running_count=2,
                    )
                    capture_milestone(
                        context,
                        "resumed",
                        evidence={
                            "completed": completed_count(),
                            "array_state": (
                                controller.get_array_run_state()
                            ),
                        },
                    )

            elapsed_seconds = (
                time.perf_counter_ns() - started_ns
            ) / 1_000_000_000.0
            remaining_timeout = max(
                0.1,
                config.timeout_seconds - elapsed_seconds,
            )
            if (
                not is_targeted_lifecycle
                and
                not midpoint_captured
                and (stock_index + 1) * len(expected_wells)
                >= midpoint_completion
            ):
                wait_for_completions(
                    context,
                    completed_count=completed_count,
                    target_count=midpoint_completion,
                    timeout_seconds=remaining_timeout,
                    label=f"{midpoint_completion} stock/well completions",
                )
                capture_milestone(
                    context,
                    "mid_array",
                    evidence={"completed": completed_count()},
                )
                midpoint_captured = True

            elapsed_seconds = (
                time.perf_counter_ns() - started_ns
            ) / 1_000_000_000.0
            remaining_timeout = max(
                0.1,
                config.timeout_seconds - elapsed_seconds,
            )
            wait_for_completions(
                context,
                completed_count=lambda: array_complete_count,
                target_count=stock_index + 1,
                timeout_seconds=remaining_timeout,
                label=f"stock pass {stock_index + 1} completion",
            )
            wait_for_array_state(
                context,
                state="idle",
                timeout_seconds=5.0,
                label=f"stock pass {stock_index + 1} idle state",
            )
            pass_state = experiment_model.get_execution_plan_snapshot().state.value
            pass_terminal_states.append(pass_state)
            pass_record.update(
                {
                    "completed_well_updates": (
                        len(well_updates)
                        - int(pass_record["starting_well_update_count"])
                    ),
                    "ended_monotonic_ns": time.perf_counter_ns(),
                    "plan_state_after_pass": pass_state,
                }
            )
            record_event(
                "stock_pass_completed",
                pass_index=stock_index + 1,
                stock_id=stock_id,
                plan_state=pass_state,
            )
            if is_multi_stock_lifecycle:
                validate_stock_pass_boundary(
                    context,
                    pass_index=stock_index + 1,
                    stock_id=stock_id,
                    printer_head_id=head["printer_head_id"],
                    expected_completed_count=(
                        (stock_index + 1) * len(expected_wells)
                    ),
                    observed_completed_count=completed_count,
                    expected_plan_state=(
                        "completed"
                        if stock_index + 1 == expected_stock_count
                        else "active"
                    ),
                )
                if stock_index == 0:
                    capture_milestone(
                        context,
                        "stock_1_completed",
                        evidence={
                            "stock_id": stock_id,
                            "plan_state": pass_state,
                            "completed": completed_count(),
                        },
                    )
            print(
                f"Completed stock pass {stock_index + 1}/{expected_stock_count}",
                file=sys.stderr,
                flush=True,
            )
        stdout_redirect.__exit__(None, None, None)
        stdout_redirect = None
        context.stdout_redirect = None

        wait_until(
            context,
            lambda: not view.pressure_box._pressure_render_timer.isActive(),
            1.0,
            "final pressure render",
            action_id="artifact.capture_milestone",
        )
        app.processEvents()
        capture_milestone(context, "completed")

        terminal_lifecycle = (
            _merge_session_lifecycles(
                (
                    ("session_1", session_1_lifecycle),
                    (
                        "session_2",
                        instrumentation.lifecycle_snapshot(),
                    ),
                )
            )
            if is_authoritative_reload_resume
            else instrumentation.lifecycle_snapshot()
            if instrumentation is not None
            else {}
        )
        validation = validate_terminal_bundle(
            context,
            lambda: (
                _validate_soft_stop_completed_scenario(
                    experiment_model=experiment_model,
                    fixture_info=fixture_info,
                    well_updates=well_updates,
                    array_states=array_states,
                    array_complete_count=array_complete_count,
                    errors=errors,
                    unexpected_dialogs=unexpected_dialogs,
                    starvation_events=starvation_events,
                    intent_lifecycle=terminal_lifecycle,
                    paused_validation=paused_validation,
                    quiescence=quiescence_evidence,
                )
                if is_pause_resume_lifecycle
                else _validate_multi_stock_completed_scenario(
                    context=context,
                    machine=machine,
                    fixture=fixture,
                    stock_specs=stock_specs,
                    event_retention=event_log.snapshot(),
                    experiment_model=experiment_model,
                    fixture_info=fixture_info,
                    well_updates=well_updates,
                    array_states=array_states,
                    array_complete_count=array_complete_count,
                    errors=errors,
                    unexpected_dialogs=unexpected_dialogs,
                    starvation_events=starvation_events,
                    intent_lifecycle=terminal_lifecycle,
                    pass_terminal_states=pass_terminal_states,
                )
                if is_multi_stock_lifecycle
                else _validate_completed_scenario(
                experiment_model=experiment_model,
                fixture_info=fixture_info,
                well_updates=well_updates,
                array_states=array_states,
                array_complete_count=array_complete_count,
                errors=errors,
                unexpected_dialogs=unexpected_dialogs,
                starvation_events=starvation_events,
                intent_lifecycle=(
                    terminal_lifecycle
                ),
                pass_terminal_states=pass_terminal_states,
                )
            ),
        )
        if is_authoritative_reload_resume:
            session_2_lifecycle = instrumentation.lifecycle_snapshot()
            session_2_begin_pairs = {
                (str(item["stock_id"]), str(item["well_id"]))
                for item in session_2_lifecycle.get("begins", ())
            }
            session_1_completed_pairs = {
                tuple(pair)
                for pair in authoritative_reload_evidence.get(
                    "session_1_completed_pairs", ()
                )
            }
            no_replay = not (
                session_1_completed_pairs & session_2_begin_pairs
            )
            validation.setdefault("checks", {})[
                "session_1_completed_pairs_not_replayed"
            ] = no_replay
            validation["checks"][
                "fresh_application_session_count_exact"
            ] = len(
                {
                    item.get("application_session_id")
                    for item in context.action_results
                    if item.get("action_id") == "app.launch_simulated"
                }
            ) == int(
                fixture["lifecycle"][
                    "expected_application_session_count"
                ]
            )
            authoritative_reload_evidence["resume_reconciliation"] = {
                "session_1_lifecycle": session_1_lifecycle,
                "session_2_lifecycle": session_2_lifecycle,
                "combined_lifecycle": terminal_lifecycle,
                "session_1_completed_pairs_not_replayed": no_replay,
                "session_2_begin_pairs": [
                    list(pair) for pair in sorted(session_2_begin_pairs)
                ],
            }
            authoritative_reload_evidence["audit"] = validation.get(
                "audit_rows", []
            )
            authoritative_reload_evidence["terminal"] = {
                "plan_state": validation.get("terminal_plan_state"),
                "completion_count": validation.get(
                    "stock_well_completion_count"
                ),
                "checks": validation.get("checks", {}),
            }
            if not no_replay:
                raise RuntimeError(
                    "the fresh application replayed completed stock/well pairs"
                )
    except Exception:
        failure_text = traceback.format_exc()
        if context.view is not None and context.app is not None:
            try:
                capture_failure_screenshot(context)
            except Exception:
                failure_text += "\nFailure screenshot error:\n" + traceback.format_exc()
    finally:
        context.stdout_redirect = stdout_redirect
        try:
            teardown_scenario(context)
        except Exception:
            cleanup_failure = "Scenario cleanup error:\n" + traceback.format_exc()
            failure_text = (
                f"{failure_text}\n{cleanup_failure}"
                if failure_text
                else cleanup_failure
            )
        stdout_redirect = None
        machine_cleanup = context.machine_cleanup
        pressure_timer_active_after_teardown = (
            context.pressure_timer_active_after_teardown
        )

    ended_ns = time.perf_counter_ns()
    ended_utc = _utc_now()
    duration_ms = (ended_ns - started_ns) / 1_000_000.0
    probe_snapshot = probe.snapshot()
    resource_snapshot = resources.snapshot()
    resource_values = resource_snapshot.setdefault("values", {})
    rss_growth_bytes = resource_values.get("rss_growth_bytes")
    rss_growth_ratio = resource_values.get("rss_growth_ratio")
    resource_growth_warning = bool(
        workload_id == STRESS_WORKLOAD_ID
        and isinstance(rss_growth_bytes, (int, float))
        and isinstance(rss_growth_ratio, (int, float))
        and float(rss_growth_bytes) > 100 * 1024 * 1024
        and float(rss_growth_ratio) > 1.25
    )
    resource_values["growth_assessment"] = {
        "applicable": workload_id == STRESS_WORKLOAD_ID,
        "absolute_warning_bytes": 100 * 1024 * 1024,
        "ratio_warning_threshold": 1.25,
        "observed_growth_bytes": rss_growth_bytes,
        "observed_growth_ratio": rss_growth_ratio,
        "decision": "warning" if resource_growth_warning else "pass",
    }
    durable_io_snapshot = io_observer.snapshot() if io_observer is not None else {}
    progress_snapshot = (
        progress_observer.snapshot()
        if progress_observer is not None
        else {
            "mode_counts": {"full_rebuild": 0, "cached_update": 0},
            "duration_samples_ms": {},
            "serialized_size_bytes": [],
            "observer_restored": True,
        }
    )
    if is_authoritative_reload_resume:
        durable_io_snapshot = _merge_durable_io_snapshots(
            session_1_durable_io_snapshot,
            durable_io_snapshot,
        )
        progress_snapshot = _merge_progress_snapshots(
            session_1_progress_snapshot,
            progress_snapshot,
        )
    authoritative_read_snapshot = (
        io_observer.read_snapshot()
        if io_observer is not None
        else {
            "by_phase": {},
            "by_path": {},
            "total_count": 0,
            "observer_restored": True,
        }
    )
    hot_persistence_phases = {
        "persistence.begin_intent",
        "persistence.attach_sequence",
        "persistence.write_progress",
        "persistence.complete_intent",
        "persistence.discard_intents",
        "persistence.guard_bundle",
        "persistence.save_resume",
        "persistence.reconcile_cache",
    }
    hot_path_read_count = sum(
        int(values.get("count", 0))
        for phase, paths in authoritative_read_snapshot.get("by_phase", {}).items()
        if phase in hot_persistence_phases
        for values in paths.values()
    )
    resume_disk_load_count = sum(
        int(values.get("count", 0))
        for phase, paths in authoritative_read_snapshot.get("by_phase", {}).items()
        if phase in hot_persistence_phases
        for path, values in paths.items()
        if path == "execution_resume.json"
    )
    phase_duration_values = (
        probe_snapshot.get("phase_timings", {}).get("duration_by_name_ms", {})
    )
    phase_records = list(
        probe_snapshot.get("phase_timings", {}).get("records", [])
    )
    pass_phase_records = [
        record
        for record in phase_records
        if str(record.get("name", "")).startswith("pass_start.")
        or str(record.get("name", "")).startswith(
            "ui.experiment_guidance_"
        )
    ]
    pass_start_records = (
        list(instrumentation.pass_starts)
        if instrumentation is not None
        else []
    )
    if is_authoritative_reload_resume and terminal_lifecycle:
        pass_start_records = list(
            terminal_lifecycle.get("pass_starts", ())
        )
    pass_gap_events: list[dict[str, Any]] = []
    for event in probe_snapshot.get("stall_events", []):
        phase = event.get("phase") or {}
        metadata = phase.get("metadata") or {}
        if (
            metadata.get("pass_index") is None
            or not str(phase.get("name") or "").startswith("pass_start.")
        ):
            continue
        pass_gap_events.append(
            {
                "pass_index": int(metadata["pass_index"]),
                "stock_id": str(metadata.get("stock_id") or ""),
                "event_loop_gap_ms": float(
                    event.get("event_loop_gap_ms", 0.0)
                ),
                "scheduling_lateness_ms": float(
                    event.get("scheduling_lateness_ms", 0.0)
                ),
                "phase_name": str(phase.get("name") or ""),
            }
        )
    pass_start_evidence = {
        "count": len(pass_start_records),
        "records": pass_start_records,
        "total_duration_ms": summarize_samples(
            [
                float(record.get("duration_ms", 0.0))
                for record in pass_start_records
            ],
            bands_ms=(250.0, 1000.0),
        ),
        "inclusive_duration_by_name_ms": {
            name: values
            for name, values in phase_duration_values.items()
            if name.startswith("pass_start.")
            or name.startswith("ui.experiment_guidance_")
        },
        "exclusive_phase_evidence": _exclusive_phase_evidence(
            pass_phase_records
        ),
        "event_loop_gaps": pass_gap_events,
        "maximum_correlated_event_loop_gap_ms": max(
            (
                float(event["event_loop_gap_ms"])
                for event in pass_gap_events
            ),
            default=0.0,
        ),
    }
    terminal_records = (
        list(instrumentation.terminal_transitions)
        if instrumentation is not None
        else []
    )
    if is_authoritative_reload_resume and terminal_lifecycle:
        terminal_records = list(
            terminal_lifecycle.get("terminal_transitions", ())
        )
    terminal_phase_records = [
        record
        for record in phase_records
        if str(record.get("name", "")).startswith("terminal_transition.")
        or str(record.get("name", "")).startswith("terminal_finalize.")
    ]
    terminal_gap_events = [
        {
            "event_loop_gap_ms": float(event.get("event_loop_gap_ms", 0.0)),
            "scheduling_lateness_ms": float(
                event.get("scheduling_lateness_ms", 0.0)
            ),
            "phase_name": str((event.get("phase") or {}).get("name") or ""),
        }
        for event in probe_snapshot.get("stall_events", [])
        if str((event.get("phase") or {}).get("name") or "").startswith(
            ("terminal_transition.", "terminal_finalize.")
        )
    ]
    terminal_transition_evidence = {
        "count": len(terminal_records),
        "records": terminal_records,
        "total_duration_ms": summarize_samples(
            [
                float(record.get("duration_ms", 0.0))
                for record in terminal_records
            ],
            bands_ms=(250.0, 1000.0),
        ),
        "inclusive_duration_by_name_ms": {
            name: values
            for name, values in phase_duration_values.items()
            if name.startswith("terminal_transition.")
            or name.startswith("terminal_finalize.")
        },
        "exclusive_phase_evidence": _exclusive_phase_evidence(
            terminal_phase_records
        ),
        "event_loop_gaps": terminal_gap_events,
        "maximum_correlated_event_loop_gap_ms": max(
            (
                float(event["event_loop_gap_ms"])
                for event in terminal_gap_events
            ),
            default=0.0,
        ),
    }
    progress_total_samples = [
        float(record["duration_ms"])
        for record in probe_snapshot.get("phase_timings", {}).get("records", [])
        if record.get("name") == "persistence.write_progress"
    ]
    progress_fsync_samples = durable_io_snapshot.get("fsync", {}).get(
        "persistence.write_progress",
        [],
    )
    progress_replace_samples = durable_io_snapshot.get(
        "atomic_replace",
        {},
    ).get("persistence.write_progress", [])
    try:
        progress_snapshot["non_durable_write_samples_ms"] = (
            non_durable_progress_samples(
                progress_total_samples,
                progress_fsync_samples,
                progress_replace_samples,
            )
        )
    except ValueError as exc:
        progress_snapshot["non_durable_write_samples_ms"] = []
        progress_snapshot["sample_alignment_error"] = str(exc)
    progress_snapshot["duration_statistics_ms"] = {
        name: summarize_samples(samples, bands_ms=())
        for name, samples in progress_snapshot.get(
            "duration_samples_ms",
            {},
        ).items()
    }
    progress_snapshot["serialized_size_statistics_bytes"] = (
        summarize_samples(
            progress_snapshot.get("serialized_size_bytes", []),
            bands_ms=(),
        )
    )
    progress_snapshot["non_durable_write_ms"] = summarize_samples(
        progress_snapshot.get("non_durable_write_samples_ms", []),
        bands_ms=(),
    )

    def durable_count(operation: str, phase: str) -> int:
        return len(durable_io_snapshot.get(operation, {}).get(phase, []))

    authoritative_io = {
        "read_opens": authoritative_read_snapshot,
        "hot_path_read_count": hot_path_read_count,
        "execution_resume_hot_path_disk_load_count": resume_disk_load_count,
        "full_bundle_refresh_count": int(
            phase_duration_values.get(
                "persistence.full_bundle_refresh",
                {},
            ).get("count", 0)
        )
        + int(
            phase_duration_values.get(
                "terminal_transition.full_validation",
                {},
            ).get("count", 0)
        ),
        "guard_count": int(
            phase_duration_values.get("persistence.guard_bundle", {}).get("count", 0)
        )
        + int(
            phase_duration_values.get(
                "pass_start.preflight_guard",
                {},
            ).get("count", 0)
        )
        + int(
            phase_duration_values.get(
                "pass_start.revision_guard",
                {},
            ).get("count", 0)
        )
        + int(
            phase_duration_values.get(
                "terminal_transition.initial_guard",
                {},
            ).get("count", 0)
        )
        + int(
            phase_duration_values.get(
                "terminal_transition.prewrite_guard",
                {},
            ).get("count", 0)
        ),
        "cache_reconciliation_count": int(
            phase_duration_values.get(
                "persistence.reconcile_cache",
                {},
            ).get("count", 0)
        ),
        "resume_save_fsync_count": durable_count(
            "fsync",
            "persistence.save_resume",
        ),
        "resume_save_replace_count": durable_count(
            "atomic_replace",
            "persistence.save_resume",
        ),
        "progress_write_fsync_count": durable_count(
            "fsync",
            "persistence.write_progress",
        ),
        "progress_write_replace_count": durable_count(
            "atomic_replace",
            "persistence.write_progress",
        ),
        "durable_io_samples_ms": durable_io_snapshot,
        "observer_restored": bool(
            authoritative_read_snapshot.get("observer_restored")
        ),
    }
    completed_updates = [
        well for well in well_updates if well in set(expected_wells)
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
    pressure_render_summary = (
        probe_snapshot.get("phase_timings", {})
        .get("duration_by_name_ms", {})
        .get("ui.pressure_render", {})
    )
    pressure_render_count = int(pressure_render_summary.get("count", 0))
    pressure_coalesced_count = max(
        0,
        pressure_update_signal_count - pressure_render_count,
    )
    pressure_render_ratio = (
        pressure_render_count / pressure_update_signal_count
        if pressure_update_signal_count
        else 0.0
    )
    pressure_render_intervals_ms = [
        (right - left) / 1_000_000.0
        for left, right in zip(
            pressure_render_timestamps_ns,
            pressure_render_timestamps_ns[1:],
        )
    ]
    pressure_interval_summary = summarize_samples(
        pressure_render_intervals_ms,
        bands_ms=(250.0, 1000.0),
    )
    if (
        failure_text is None
        and injection_requested
        and not (injection_detected and injection_stack_captured)
    ):
        failure_text = (
            "Injected UI stall evidence was incomplete: "
            f"detected={injection_detected}, stack_captured={injection_stack_captured}"
        )
    if failure_text is None and progress_snapshot.get("sample_alignment_error"):
        failure_text = (
            "Progress snapshot evidence was incomplete: "
            f"{progress_snapshot['sample_alignment_error']}"
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
    if (
        failure_text is None
        and pressure_update_signal_count > 0
        and pressure_render_count == 0
    ):
        failure_text = "pressure updates occurred without a pressure render"
    if failure_text is None and pressure_timer_active_after_teardown:
        failure_text = "pressure render timer remained active after teardown"
    expected_completions = len(expected_wells)
    expected_completions *= expected_stock_count
    progress_modes = progress_snapshot.get("mode_counts", {})
    progress_durations = progress_snapshot.get("duration_samples_ms", {})
    expected_pass_start_guards = 0
    for record in pass_start_records:
        preparation = record.get("preparation") or {}
        cache_path = str(preparation.get("cache_path", ""))
        expected_pass_start_guards += (
            1 if cache_path.startswith("bootstrap") else 2
        )
        expected_pass_start_guards += len(
            preparation.get("created_revisions") or ()
        )
        if preparation.get("checkpoint_action") == "created":
            expected_pass_start_guards += 1
    expected_terminal_guards = sum(
        2
        for record in terminal_records
        if (record.get("preparation") or {}).get("cache_path")
        == "cached_completion"
    )
    lifecycle_snapshot = (
        terminal_lifecycle
        if terminal_lifecycle
        else instrumentation.lifecycle_snapshot()
        if instrumentation is not None
        else {}
    )
    lifecycle_begin_count = len(lifecycle_snapshot.get("begins", ()))
    lifecycle_attachment_count = len(
        lifecycle_snapshot.get("attachments", ())
    )
    lifecycle_completion_count = len(
        lifecycle_snapshot.get("completions", ())
    )
    lifecycle_discard_batch_count = len(
        lifecycle_snapshot.get("discard_batches", ())
    )
    lifecycle_discarded_count = sum(
        len(batch.get("intent_ids", ()))
        for batch in lifecycle_snapshot.get("discard_batches", ())
    )
    activation_changed_paths = set(
        authoritative_reload_evidence.get(
            "session_2_activation",
            {},
        ).get("changed_paths", ())
    )
    activation_checkpoint_sync_count = (
        1
        if (
            is_authoritative_reload_resume
            and "execution_resume.json" in activation_changed_paths
        )
        else 0
    )
    expected_resume_saves = (
        lifecycle_begin_count
        + lifecycle_attachment_count
        + lifecycle_completion_count
        + lifecycle_discard_batch_count
        + activation_checkpoint_sync_count
    )
    expected_guard_count = (
        expected_completions * 4
        + expected_pass_start_guards
        + expected_terminal_guards
        + (
            lifecycle_discarded_count * 2
            + lifecycle_discard_batch_count
            if is_pause_resume_lifecycle
            else 0
        )
    )
    if failure_text is None and (
        progress_modes.get("cached_update") != expected_completions
        or progress_modes.get("full_rebuild") != 0
        or len(progress_durations.get("serialization", []))
        != expected_completions
        or len(progress_durations.get("atomic_write", []))
        != expected_completions
        or len(progress_snapshot.get("serialized_size_bytes", []))
        != expected_completions
        or len(progress_snapshot.get("non_durable_write_samples_ms", []))
        != expected_completions
        or not progress_snapshot.get("observer_restored")
    ):
        failure_text = (
            "progress snapshot evidence violated the cached-construction "
            f"contract: {progress_snapshot}"
        )
    if failure_text is None and (
        authoritative_io["hot_path_read_count"] != 0
        or authoritative_io["execution_resume_hot_path_disk_load_count"] != 0
        or authoritative_io["guard_count"] != expected_guard_count
        or authoritative_io["resume_save_fsync_count"] != expected_resume_saves
        or authoritative_io["resume_save_replace_count"] != expected_resume_saves
        or authoritative_io["progress_write_fsync_count"] != expected_completions
        or authoritative_io["progress_write_replace_count"] != expected_completions
        or not authoritative_io["observer_restored"]
    ):
        failure_text = (
            "authoritative persistence I/O evidence violated the cached-runtime "
            f"contract: {authoritative_io}"
        )

    gap_maximum_ms = float(
        (probe_snapshot.get("event_loop_gap_ms") or {}).get("maximum", 0.0)
        or 0.0
    )
    scheduling_p99_ms = float(
        (probe_snapshot.get("scheduling_lateness_ms") or {}).get("p99", 0.0)
        or 0.0
    )
    pressure_interval_maximum_ms = float(
        pressure_interval_summary.get("maximum", 0.0) or 0.0
    )
    responsiveness_unacceptable = (
        workload_id == STRESS_WORKLOAD_ID
        and (
            gap_maximum_ms > 1000.0
            or pressure_interval_maximum_ms > 1000.0
            or scheduling_p99_ms > 250.0
        )
    )
    responsiveness_warning = (
        workload_id == STRESS_WORKLOAD_ID
        and not responsiveness_unacceptable
        and (
            gap_maximum_ms > 250.0
            or pressure_interval_maximum_ms > 250.0
        )
    )
    if failure_text is None and responsiveness_unacceptable:
        failure_text = (
            "384x10 responsiveness was unacceptable: "
            f"event_loop_gap_max={gap_maximum_ms:.3f} ms, "
            f"pressure_render_interval_max={pressure_interval_maximum_ms:.3f} ms, "
            f"scheduling_lateness_p99={scheduling_p99_ms:.3f} ms"
        )
    stress_warning = responsiveness_warning or resource_growth_warning
    status = (
        "fail"
        if failure_text
        else "warning"
        if stress_warning
        else "pass"
    )
    reasons = (
        [failure_text.splitlines()[-1] if failure_text else "scenario failed"]
        if failure_text
        else [
            "The 384x10 workflow passed, but an event-loop or pressure-render "
            "interval exceeded the 250 ms warning threshold."
        ]
        if responsiveness_warning
        else [
            "The 384x10 workflow passed, but process RSS increased by more "
            "than 100 MiB and 25%."
        ]
        if resource_growth_warning
        else ["All functional, persistence, UI, and simulation-safety invariants passed."]
    )
    lifecycle_assertion_ids = (
        (
            "sil.host_hardware_disabled",
            "ui.real_app_constructed",
            "ui.fresh_application_session_constructed",
            "execution.first_session_paused",
            "execution.first_session_teardown_clean",
            "execution.authoritative_reload_valid",
            "execution.authoritative_runtime_rehydrated",
            "execution.reload_resume_exactly_once",
            "execution.expected_completions",
            "execution.intent_durability_exact",
            "execution.terminal_bundle_valid",
            "artifacts.required_present",
        )
        if is_authoritative_reload_resume
        else (
            "sil.host_hardware_disabled",
            "ui.real_app_constructed",
            "execution.multi_stock_head_exchange",
            "execution.stock_pass_boundaries_valid",
            "execution.stock_head_settings_match",
            "execution.expected_completions",
            "execution.no_queue_starvation",
            "execution.intent_durability_exact",
            "execution.event_history_bounded",
            "execution.terminal_bundle_valid",
            "artifacts.required_present",
        )
        if is_multi_stock_lifecycle
        else (
            "sil.host_hardware_disabled",
            "ui.real_app_constructed",
            "execution.soft_stop_requested",
            "execution.soft_stop_boundary_valid",
            "execution.stopped_boundary_quiescent",
            "execution.resume_exactly_once",
            "execution.expected_completions",
            "execution.intent_durability_exact",
            "execution.terminal_bundle_valid",
            "artifacts.required_present",
        )
    )
    assertion_results: list[dict[str, Any]] = []
    if is_targeted_lifecycle:
        action_by_id = {
            item["action_id"]: item
            for item in context.action_results
        }
        actions_by_id: dict[str, list[dict[str, Any]]] = {}
        for item in context.action_results:
            actions_by_id.setdefault(item["action_id"], []).append(item)
        terminal_checks = validation.get("checks", {})
        paused_checks = paused_validation.get("checks", {})
        shared_outcomes: dict[str, bool | None] = {
            "sil.host_hardware_disabled": True,
            "ui.real_app_constructed": (
                bool(actions_by_id.get("app.launch_simulated"))
                and all(
                    item.get("status") == "pass"
                    for item in actions_by_id["app.launch_simulated"]
                )
            ),
            "execution.expected_completions": (
                bool(terminal_checks.get("completion_count_exact"))
                if terminal_checks
                else None
            ),
            "execution.intent_durability_exact": (
                all(
                    terminal_checks.get(name) is True
                    for name in (
                        "terminal_intent_partition_exact",
                        "discarded_pairs_reissued",
                        "completed_pairs_exactly_once",
                    )
                )
                if terminal_checks
                else None
            ),
            "execution.terminal_bundle_valid": (
                all(
                    terminal_checks.get(name) is True
                    for name in (
                        "checkpoint_clean",
                        "checkpoint_empty",
                        "authoritative_bundle_valid",
                        "terminal_plan_completed",
                    )
                )
                if terminal_checks
                else None
            ),
            "artifacts.required_present": (
                set(screenshots)
                == {
                    "ready",
                    "printing",
                    "stop_requested",
                    "stopped",
                    "resumed",
                    "completed",
                }
                and all(
                    path.is_file() and path.stat().st_size > 0
                    for path in screenshots.values()
                )
            ),
        }
        if is_multi_stock_lifecycle:
            multi_checks = validation.get(
                "multi_stock_head_exchange", {}
            ).get("checks", {})
            outcomes = {
                "sil.host_hardware_disabled": True,
                "ui.real_app_constructed": (
                    bool(actions_by_id.get("app.launch_simulated"))
                    and all(
                        item.get("status") == "pass"
                        for item in actions_by_id["app.launch_simulated"]
                    )
                ),
                "execution.multi_stock_head_exchange": (
                    all(
                        multi_checks.get(name) is True
                        for name in (
                            "two_distinct_stock_ids",
                            "two_distinct_printer_head_ids",
                            "two_stock_passes_recorded",
                            "head_exchange_idle_and_drained",
                            "virtual_head_exchange_events_exact",
                        )
                    )
                    if multi_checks
                    else None
                ),
                "execution.stock_pass_boundaries_valid": (
                    multi_checks.get("stock_pass_boundaries_valid")
                    if multi_checks
                    else None
                ),
                "execution.stock_head_settings_match": (
                    multi_checks.get("stock_head_settings_match")
                    if multi_checks
                    else None
                ),
                "execution.expected_completions": (
                    all(
                        terminal_checks.get(name) is True
                        for name in (
                            "intent_count_exact",
                            "intent_stock_well_pairs_exact",
                            "well_updates_exact",
                            "targets_match_progress",
                        )
                    )
                    if terminal_checks
                    else None
                ),
                "execution.no_queue_starvation": (
                    terminal_checks.get("no_lookahead_starvation")
                    if terminal_checks
                    else None
                ),
                "execution.intent_durability_exact": (
                    all(
                        terminal_checks.get(name) is True
                        for name in (
                            "intent_ids_unique",
                            "intent_attachments_exact",
                            "all_intents_retired",
                            "intent_lifecycle_exact_without_discards",
                        )
                    )
                    if terminal_checks
                    else None
                ),
                "execution.event_history_bounded": (
                    multi_checks.get("event_history_bounded")
                    if multi_checks
                    else None
                ),
                "execution.terminal_bundle_valid": (
                    all(
                        terminal_checks.get(name) is True
                        for name in (
                            "checkpoint_clean",
                            "checkpoint_empty",
                            "authoritative_bundle_valid",
                            "terminal_plan_completed",
                            "plan_completes_only_after_last_stock",
                        )
                    )
                    if terminal_checks
                    else None
                ),
                "artifacts.required_present": (
                    set(screenshots)
                    == {
                        "stock_1_ready",
                        "stock_1_printing",
                        "stock_1_completed",
                        "stock_2_staged",
                        "stock_2_printing",
                        "completed",
                    }
                    and all(
                        path.is_file() and path.stat().st_size > 0
                        for path in screenshots.values()
                    )
                ),
            }
        elif is_authoritative_reload_resume:
            loaded_checks = authoritative_reload_evidence.get(
                "session_2_loaded", {}
            ).get("checks", {})
            activated_checks = authoritative_reload_evidence.get(
                "session_2_activation", {}
            ).get("checks", {})
            outcomes: dict[str, bool | None] = {
                **shared_outcomes,
                "ui.fresh_application_session_constructed": (
                    len(actions_by_id.get("app.launch_simulated", ())) == 2
                    and all(
                        item.get("status") == "pass"
                        for item in actions_by_id.get(
                            "app.launch_simulated", ()
                        )
                    )
                ),
                "execution.first_session_paused": (
                    all(paused_checks.values()) if paused_checks else None
                ),
                "execution.first_session_teardown_clean": (
                    action_by_id.get(
                        "app.close_simulated_session", {}
                    ).get("status")
                    == "pass"
                    if "app.close_simulated_session" in action_by_id
                    else None
                ),
                "execution.authoritative_reload_valid": (
                    all(loaded_checks.values()) if loaded_checks else None
                    if action_by_id.get(
                        "experiment.load_authoritative_via_ui", {}
                    ).get("status")
                    != "fail"
                    else False
                ),
                "execution.authoritative_runtime_rehydrated": (
                    all(activated_checks.values())
                    if activated_checks
                    else None
                ),
                "execution.reload_resume_exactly_once": (
                    all(
                        terminal_checks.get(name) is True
                        for name in (
                            "ui_resumed_once",
                            "terminal_intent_partition_exact",
                            "discarded_pairs_reissued",
                            "completed_pairs_exactly_once",
                            "session_1_completed_pairs_not_replayed",
                            "audit_lifecycle_ordered",
                        )
                    )
                    if terminal_checks
                    else None
                ),
                "artifacts.required_present": (
                    set(screenshots)
                    == {
                        "session_1_ready",
                        "session_1_printing",
                        "session_1_stop_requested",
                        "session_1_stopped",
                        "session_2_loaded",
                        "session_2_activated",
                        "session_2_resumed",
                        "completed",
                    }
                    and all(
                        path.is_file() and path.stat().st_size > 0
                        for path in screenshots.values()
                    )
                ),
            }
        else:
            outcomes = {
                **shared_outcomes,
                "execution.soft_stop_requested": (
                    action_by_id.get(
                        "array.request_soft_stop_via_ui", {}
                    ).get("status")
                    == "pass"
                    if "array.request_soft_stop_via_ui" in action_by_id
                    else None
                ),
                "execution.soft_stop_boundary_valid": (
                    all(paused_checks.values())
                    if paused_checks
                    else False
                    if action_by_id.get(
                        "validation.paused_bundle", {}
                    ).get("status")
                    == "fail"
                    else None
                ),
                "execution.stopped_boundary_quiescent": (
                    action_by_id.get(
                        "array.observe_stopped_quiescence", {}
                    ).get("status")
                    == "pass"
                    if "array.observe_stopped_quiescence" in action_by_id
                    else None
                ),
                "execution.resume_exactly_once": (
                    all(
                        terminal_checks.get(name) is True
                        for name in (
                            "ui_resumed_once",
                            "terminal_intent_partition_exact",
                            "discarded_pairs_reissued",
                            "completed_pairs_exactly_once",
                            "audit_lifecycle_ordered",
                        )
                    )
                    if terminal_checks
                    else None
                ),
                "artifacts.required_present": (
                    set(screenshots)
                    == {
                        "ready",
                        "printing",
                        "stop_requested",
                        "stopped",
                        "resumed",
                        "completed",
                    }
                    and all(
                        path.is_file() and path.stat().st_size > 0
                        for path in screenshots.values()
                    )
                ),
            }
        assertion_results = [
            {
                "assertion_id": assertion_id,
                "decision": (
                    "pass"
                    if outcomes[assertion_id] is True
                    else "fail"
                    if outcomes[assertion_id] is False
                    else "incomplete"
                ),
            }
            for assertion_id in lifecycle_assertion_ids
        ]
        if failure_text is None and any(
            item["decision"] != "pass" for item in assertion_results
        ):
            failure_text = (
                "authoritative reload lifecycle assertion evidence was incomplete"
                if is_authoritative_reload_resume
                else "multi-stock lifecycle assertion evidence was incomplete"
                if is_multi_stock_lifecycle
                else "soft-stop lifecycle assertion evidence was incomplete"
            )
            status = "fail"
            reasons = [failure_text]
    response_values = {
        **probe_snapshot,
        "well_plate_paint_event_count": paint_event_count,
        "pressure_render_assessment": {
            "update_signal_count": pressure_update_signal_count,
            "render_count": pressure_render_count,
            "coalesced_update_count": pressure_coalesced_count,
            "render_to_signal_ratio": pressure_render_ratio,
            "render_interval_ms": pressure_render_interval_ms,
            "timer_active_after_teardown": pressure_timer_active_after_teardown,
            "duration_ms": pressure_render_summary,
            "active_render_interval_ms": pressure_interval_summary,
        },
        "stress_assessment": {
            "applicable": workload_id == STRESS_WORKLOAD_ID,
            "event_loop_gap_warning_ms": 250.0,
            "active_pressure_render_interval_warning_ms": 250.0,
            "maximum_service_gap_ms": 1000.0,
            "maximum_scheduling_lateness_p99_ms": 250.0,
            "event_loop_gap_maximum_ms": gap_maximum_ms,
            "active_pressure_render_interval_maximum_ms": (
                pressure_interval_maximum_ms
            ),
            "scheduling_lateness_p99_ms": scheduling_p99_ms,
            "decision": (
                "unacceptable"
                if responsiveness_unacceptable
                else "warning"
                if responsiveness_warning
                else "responsive"
                if workload_id == STRESS_WORKLOAD_ID
                else "not_applicable"
            ),
        },
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
            "scenario_name": (
                "authoritative_reload_resume"
                if is_authoritative_reload_resume
                else "print_array_soft_stop_resume"
                if is_soft_stop_resume
                else "print_array_multi_stock_head_exchange"
                if is_multi_stock_lifecycle
                else SCENARIO_NAME
            ),
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
            "workload_id": workload_id,
            "fixture_schema_version": fixture["schema_version"],
            "fixture_path": config.fixture_path.relative_to(REPO_ROOT).as_posix(),
            "fixture_sha256": hashlib.sha256(
                config.fixture_path.read_bytes()
            ).hexdigest(),
            "plate_name": fixture["plate"]["name"],
            "plate_rows": fixture["plate"]["rows"],
            "plate_columns": fixture["plate"]["columns"],
            "well_ids": list(expected_wells),
            "stock_id": (
                fixture_info["stock_id"]
                if fixture_info
                else _stock_id(stock_specs[0])
            ),
            "stock_ids": (
                list(fixture_info["stock_ids"])
                if fixture_info
                else [_stock_id(stock) for stock in stock_specs]
            ),
            "stock_count": expected_stock_count,
            "array_passes": expected_stock_count,
            "target_dispenses_per_well": _fixture_target_per_stock(fixture),
            "expected_completion_count": expected_completions,
            "speed_multiplier": config.speed_multiplier,
            "timeout_seconds": config.timeout_seconds,
        },
        "metrics": {
            "responsiveness": {
                "status": (
                    "not_applicable"
                    if is_targeted_lifecycle
                    else "measured"
                    if probe_started
                    else "not_available"
                ),
                "values": response_values if probe_started else {},
            },
            "workflow": {
                "status": "measured",
                "values": {
                    "expected_well_count": len(expected_wells),
                    "completed_well_count": len(set(completed_updates)),
                    "expected_stock_well_completion_count": expected_completions,
                    "completed_stock_well_count": len(completed_updates),
                    "completed_well_ids": completed_updates,
                    "well_update_count": len(well_updates),
                    "array_states": array_states,
                    "array_complete_count": array_complete_count,
                    "stock_passes": stock_passes,
                    "pass_terminal_states": pass_terminal_states,
                    "dialogs": dialogs,
                    "unexpected_dialogs": unexpected_dialogs,
                    "errors": errors,
                    "validation_checks": validation.get("checks", {}),
                    "action_results": list(context.action_results),
                    "lifecycle_milestones": list(context.milestones),
                    "cleanup_results": list(context.cleanup_results),
                    **(
                        {"assertion_results": assertion_results}
                        if is_targeted_lifecycle
                        else {}
                    ),
                },
            },
            "queue": {
                "status": "measured",
                "values": {
                    "lifecycle_event_count": command_event_count,
                    "lifecycle_counts": dict(
                        sorted(command_lifecycle_counts.items())
                    ),
                    "maximum_queue_depth": maximum_queue_depth or 0,
                    "minimum_queue_depth": minimum_queue_depth or 0,
                    "unexpected_starvation_count": len(starvation_events),
                    "unexpected_starvation_events": starvation_events,
                    "event_trace_retention": event_log.snapshot(),
                    "simulator_cleanup": machine_cleanup,
                },
            },
            "persistence": {
                "status": "measured" if validation else "partial",
                "values": {
                    **validation,
                    **(
                        {
                            "soft_stop_resume": {
                                "request": next(
                                    (
                                        item.get("evidence", {})
                                        for item in context.action_results
                                        if item.get("action_id")
                                        == "array.request_soft_stop_via_ui"
                                    ),
                                    {},
                                ),
                                "watermark": paused_validation.get(
                                    "watermark", {}
                                ),
                                "clear": paused_validation.get("clear", {}),
                                "stopped_checkpoint": paused_validation,
                                "quiescence": quiescence_evidence,
                                "resume": {
                                    "running_state_count": array_states.count(
                                        "running"
                                    ),
                                    "dialog_seen": any(
                                        item.get("title")
                                        == "Resume Print Array"
                                        for item in dialogs
                                    ),
                                },
                                "intent_reconciliation": {
                                    "begin_count": validation.get(
                                        "begin_intent_count"
                                    ),
                                    "completed_count": validation.get(
                                        "observed_completed_intent_count"
                                    ),
                                    "discarded_count": validation.get(
                                        "discarded_intent_count"
                                    ),
                                    "discard_batch_count": validation.get(
                                        "discard_batch_count"
                                    ),
                                    "discarded_intent_ids": validation.get(
                                        "discarded_intent_ids", []
                                    ),
                                    "lifecycle": lifecycle_snapshot,
                                },
                                "audit": validation.get("audit_rows", []),
                                "terminal": {
                                    "plan_state": validation.get(
                                        "terminal_plan_state"
                                    ),
                                    "completion_count": validation.get(
                                        "stock_well_completion_count"
                                    ),
                                },
                            }
                        }
                        if is_soft_stop_resume
                        else {}
                    ),
                    **(
                        {
                            "authoritative_reload_resume": {
                                **authoritative_reload_evidence,
                                "request": next(
                                    (
                                        item.get("evidence", {})
                                        for item in context.action_results
                                        if item.get("action_id")
                                        == "array.request_soft_stop_via_ui"
                                    ),
                                    {},
                                ),
                                "quiescence": quiescence_evidence,
                            }
                        }
                        if is_authoritative_reload_resume
                        else {}
                    ),
                    "phase_timings": phases.snapshot(),
                    "pass_start": pass_start_evidence,
                    "terminal_transition": terminal_transition_evidence,
                    "authoritative_io": authoritative_io,
                    "progress_snapshot": progress_snapshot,
                    "cumulative_progress_serialized_bytes": sum(
                        int(value)
                        for value in progress_snapshot.get(
                            "serialized_size_bytes",
                            [],
                        )
                    ),
                    "progress_format": (
                        _progress_format_evidence(
                            Path(fixture_info["experiment_dir"])
                        )
                        if fixture_info is not None
                        else {"error": "scenario fixture was not created"}
                    ),
                },
            },
            "resources": (
                {
                    **resource_snapshot,
                    "status": "not_applicable",
                }
                if is_targeted_lifecycle
                else resource_snapshot
            ),
        },
        "artifacts": {
            "report_json": "report.json",
            "summary_text": "summary.txt",
            "event_trace": "events.jsonl",
            "stall_stacks": "stall_stacks.txt",
            "failure_traceback": (
                "failure_traceback.txt" if failure_text else None
            ),
            "application_stdout": "application_stdout.log",
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
    _write_event_trace(event_path, event_log.events)
    (report_dir / "application_stdout.log").write_text(
        application_stdout.getvalue(),
        encoding="utf-8",
    )
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
    "AUTHORITATIVE_RELOAD_RESUME_WORKLOAD_ID",
    "MULTI_STOCK_WORKLOAD_ID",
    "MIXED_MODE_WORKLOAD_ID",
    "SCENARIO_NAME",
    "SCENARIO_VERSION",
    "SCENARIO_FIXTURES",
    "SMOKE_WORKLOAD_ID",
    "SOFT_STOP_RESUME_WORKLOAD_ID",
    "STRESS_WORKLOAD_ID",
    "WORKLOAD_ID",
    "VirtualPrintArrayScenarioConfig",
    "VirtualWorkflowScenarioError",
    "fixture_well_ids",
    "load_virtual_print_array_fixture",
    "run_virtual_print_array_scenario",
]
