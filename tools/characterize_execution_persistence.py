#!/usr/bin/env python3
"""Characterize durable execution persistence without constructing hardware."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_DIR = REPO_ROOT / "FreeRTOS-interface"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))

# This tool never creates a window, but Model imports Qt types.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from AuthoritativeExecutionLoad import inspect_authoritative_execution
from ExecutionPlan import save_execution_plan
from ExecutionProgressStore import (
    encode_execution_progress_v2,
    execution_progress_storage_evidence,
    serialize_execution_progress,
)
from ExecutionPlanRevision import persist_immutable_revision
from ExecutionResumeStore import load_execution_resume
from InitialExecutionPlan import build_initial_execution_plan
from Model import (
    CURRENT_PROFILE,
    ExperimentModel,
    Model,
    ReactionCollection,
    StockSolutionManager,
    WellPlate,
)
from tools.virtual_workflows.report import (
    REPORT_SCHEMA_NAME,
    REPORT_SCHEMA_VERSION,
    collect_environment_identity,
    write_report_atomic,
)
from tools.virtual_workflows.metrics import linear_slope, summarize_samples
from tools.virtual_workflows.persistence_io import PersistenceIoObserver
from tools.virtual_workflows.progress_snapshot import (
    ProgressSnapshotObserver,
    non_durable_progress_samples,
)


SCENARIO_NAME = "execution_persistence"
SCENARIO_VERSION = "1"
WORKLOAD_ID = "execution_persistence_v1"
WORKLOAD_96_SINGLE_ID = "execution_persistence_96_single_v1"
WORKLOAD_384_SINGLE_ID = "execution_persistence_384_single_v1"
DEFAULT_OUTPUT_ROOT = Path("verification_reports") / "virtual_workflows"
KEEP_POLICIES = {"never", "on-failure", "always"}
GROWTH_RATIO_WARNING_THRESHOLD = 1.25
GROWTH_DELTA_WARNING_THRESHOLD_MS = 10.0
PHASE_NAMES = (
    "begin_intent",
    "attach_sequence",
    "update_runtime",
    "write_progress",
    "complete_intent",
    "well_total",
)


class WorkloadInvariantError(RuntimeError):
    """Raised when a completed workload violates durable execution invariants."""


@dataclass(frozen=True)
class WorkloadSpec:
    plate_name: str
    plate_rows: int
    plate_columns: int
    well_ids: tuple[str, ...]
    stock_count: int
    target_dispenses: int = 1
    workload_id: str = WORKLOAD_ID

    @property
    def completion_count(self) -> int:
        return len(self.well_ids) * self.stock_count

    def to_report(self) -> dict[str, Any]:
        return {
            "workload_id": self.workload_id,
            "plate_name": self.plate_name,
            "plate_rows": self.plate_rows,
            "plate_columns": self.plate_columns,
            "well_ids": list(self.well_ids),
            "assigned_wells": len(self.well_ids),
            "stock_count": self.stock_count,
            "target_dispenses_per_stock_per_well": self.target_dispenses,
            "array_passes": self.stock_count,
            "lifecycle_completions": self.completion_count,
            "durable_execution": True,
            "characterization_pacing": "unpaced",
            "temporary_experiment_policy": "operating_system_temporary_directory",
            "future_sil_completion_interval_ms": 50,
            "future_sil_lookahead_wells": 2,
        }


def _serpentine_wells(rows: Iterable[str], columns: int) -> tuple[str, ...]:
    wells: list[str] = []
    for index, row in enumerate(rows):
        column_numbers = (
            range(1, columns + 1)
            if index % 2 == 0
            else range(columns, 0, -1)
        )
        wells.extend(f"{row}{column}" for column in column_numbers)
    return tuple(wells)


BASELINE_WORKLOAD = WorkloadSpec(
    plate_name="shallow-384_well_plate",
    plate_rows=16,
    plate_columns=24,
    well_ids=_serpentine_wells(("A", "B", "C", "D"), 24),
    stock_count=4,
)

WORKLOAD_96_SINGLE = WorkloadSpec(
    plate_name="shallow-384_well_plate",
    plate_rows=16,
    plate_columns=24,
    well_ids=_serpentine_wells(("A", "B", "C", "D"), 24),
    stock_count=1,
    workload_id=WORKLOAD_96_SINGLE_ID,
)

WORKLOAD_384_SINGLE = WorkloadSpec(
    plate_name="shallow-384_well_plate",
    plate_rows=16,
    plate_columns=24,
    well_ids=_serpentine_wells(tuple("ABCDEFGHIJKLMNOP"), 24),
    stock_count=1,
    workload_id=WORKLOAD_384_SINGLE_ID,
)

WORKLOAD_CATALOG = {
    WORKLOAD_96_SINGLE.workload_id: WORKLOAD_96_SINGLE,
    BASELINE_WORKLOAD.workload_id: BASELINE_WORKLOAD,
    WORKLOAD_384_SINGLE.workload_id: WORKLOAD_384_SINGLE,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _distribution(values: list[float]) -> dict[str, float | int]:
    summary = summarize_samples(values, bands_ms=())
    return {
        key: summary[key]
        for key in ("count", "mean", "p50", "p95", "p99", "maximum")
    }


def _timed(call: Callable[[], Any]) -> tuple[Any, float]:
    started = time.perf_counter_ns()
    result = call()
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    return result, elapsed_ms


def _quartile_growth(values: list[float]) -> dict[str, Any]:
    if not values:
        raise ValueError("quartile growth requires at least one sample")
    quartile_count = max(1, len(values) // 4)
    first = values[:quartile_count]
    last = values[-quartile_count:]
    first_mean = statistics.fmean(first)
    last_mean = statistics.fmean(last)
    return {
        "quartile_completion_count": quartile_count,
        "first_quartile_ms": _distribution(first),
        "last_quartile_ms": _distribution(last),
        "first_quartile_mean_ms": first_mean,
        "last_quartile_mean_ms": last_mean,
        "last_minus_first_mean_ms": last_mean - first_mean,
        "last_to_first_mean_ratio": (
            last_mean / first_mean if first_mean else 0.0
        ),
    }


def _capture_file_sizes(experiment_dir: Path) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for name in ("progress.json", "execution_resume.json"):
        path = experiment_dir / name
        if not path.is_file():
            raise WorkloadInvariantError(
                f"expected persistence file is unavailable: {name}"
            )
        sizes[name] = path.stat().st_size
    return sizes


def _stock_rows(stock_count: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    factors: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for index in range(1, stock_count + 1):
        name = f"Baseline Stock {index}"
        concentration = float(index)
        factors.append(
            {
                "name": name,
                "kind": "additive",
                "options": [
                    {
                        "name": name,
                        "targets": [concentration],
                        "units": "x",
                        "droplet_nL": 10.0,
                        "printing_mode": "droplet",
                        "intended_droplet_nL": 10.0,
                    }
                ],
            }
        )
        rows.append(
            {
                "factor_name": name,
                "option_name": None,
                "stock_concentration": concentration,
                "units": "x",
                "printing_mode": "droplet",
                "droplet_volume_nL": 10.0,
            }
        )
    return factors, rows


def _create_prepared_bundle(experiment_dir: Path, spec: WorkloadSpec) -> None:
    factors, stock_rows = _stock_rows(spec.stock_count)
    design = {
        "schema_version": 2,
        "metadata": {
            "name": "virtual-workflow-persistence-baseline",
            "target_reaction_volume_nL": float(
                spec.stock_count * spec.target_dispenses * 10
            ),
            "final_reaction_volume_nL": float(
                spec.stock_count * spec.target_dispenses * 10
            ),
            "printed_volume_tolerance_nL": 0.0,
            "fill_reagent_name": "Water",
            "fill_droplet_volume_nL": 10.0,
            "fill_printing_mode": "droplet",
            "plate_format": spec.plate_name,
            "start_row": 0,
            "start_col": 0,
            "replicates": len(spec.well_ids),
            "randomize_assignments": False,
        },
        "factors": factors,
    }
    stock_ids = [
        f"Baseline Stock {index}_{float(index):.2f}_x"
        for index in range(1, spec.stock_count + 1)
    ]
    assigned_wells = [
        {
            "well_id": well_id,
            "reaction_id": f"R{index}",
            "target_dispenses": {
                stock_id: spec.target_dispenses for stock_id in stock_ids
            },
        }
        for index, well_id in enumerate(spec.well_ids, start=1)
    ]
    plan = build_initial_execution_plan(
        design_payload=design,
        plate_name=spec.plate_name,
        plate_rows=spec.plate_rows,
        plate_columns=spec.plate_columns,
        stock_rows=stock_rows,
        assigned_wells=assigned_wells,
    )

    experiment_dir.mkdir(parents=True, exist_ok=False)
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


def _build_hardware_isolated_model(experiment_dir: Path) -> Model:
    plates_path = UI_DIR / "Presets" / "Plates.json"
    plate_data = json.loads(plates_path.read_text(encoding="utf-8"))

    model = Model.__new__(Model)
    model.experiment_model = ExperimentModel(prof=CURRENT_PROFILE)
    model.well_plate = WellPlate(plate_data, str(plates_path))
    model.stock_solutions = StockSolutionManager()
    model.reaction_collection = ReactionCollection()
    model.experiment_loaded = SimpleNamespace(emit=lambda *args, **kwargs: None)
    model.assign_printer_heads = lambda: None
    model.record_experiment_audit_event = lambda *args, **kwargs: None

    experiment = model.experiment_model
    experiment.load_experiment(
        str(experiment_dir / "experiment_design.json"),
        str(experiment_dir),
    )
    eligibility = model.load_authoritative_execution_runtime()
    if eligibility["status"] not in {"ready_to_start", "ready_to_resume"}:
        raise WorkloadInvariantError(
            f"unexpected activation eligibility: {eligibility['status']}"
        )
    return model


def _validate_completed_workload(
    model: Model,
    experiment_dir: Path,
    observed_intent_ids: list[str],
    expected_sequences: list[int],
    completed_intent_ids: list[str],
    max_retained_intent_count: int,
) -> dict[str, Any]:
    experiment = model.experiment_model
    checkpoint = load_execution_resume(experiment.execution_resume_file_path)
    if checkpoint.state != "clean":
        raise WorkloadInvariantError(
            f"execution checkpoint ended in {checkpoint.state!r}, not 'clean'"
        )
    if checkpoint.intents:
        raise WorkloadInvariantError(
            f"clean checkpoint retained {len(checkpoint.intents)} resolved intents"
        )
    if (
        len(observed_intent_ids) != len(expected_sequences)
        or len(observed_intent_ids) != len(set(observed_intent_ids))
    ):
        raise WorkloadInvariantError("execution intent IDs are not unique")
    if completed_intent_ids != observed_intent_ids:
        raise WorkloadInvariantError(
            "completed execution intent order differs from created intent order"
        )
    if expected_sequences != sorted(set(expected_sequences)):
        raise WorkloadInvariantError(
            "intent command sequences are not unique and monotonically increasing"
        )

    design = json.loads(
        Path(experiment.experiment_file_path).read_text(encoding="utf-8")
    )
    bundle = inspect_authoritative_execution(experiment_dir, design)
    if not bundle.valid:
        raise WorkloadInvariantError("final authoritative execution bundle is invalid")
    for well_id, well in bundle.progress_wells.items():
        for stock_id, reagent in well["reagents"].items():
            if int(reagent["target_droplets"]) != int(reagent["added_droplets"]):
                raise WorkloadInvariantError(
                    f"target/progress mismatch for {well_id}/{stock_id}"
                )

    file_sizes = {}
    for name in ("execution_plan.json", "progress.json", "execution_resume.json"):
        path = experiment_dir / name
        file_sizes[name] = path.stat().st_size
    revision_dir = experiment_dir / "execution_plan_revisions"
    file_sizes["execution_plan_revisions"] = sum(
        path.stat().st_size for path in revision_dir.glob("*.json")
    )
    return {
        "checkpoint_state": checkpoint.state,
        "intent_count": len(completed_intent_ids),
        "observed_completed_intent_count": len(completed_intent_ids),
        "checkpoint_retained_intent_count": len(checkpoint.intents),
        "checkpoint_pending_intent_count": sum(
            intent.status == "pending" for intent in checkpoint.intents
        ),
        "checkpoint_max_observed_intent_count": max_retained_intent_count,
        "authoritative_bundle_valid": bundle.valid,
        "targets_match_progress": True,
        "file_sizes_bytes": file_sizes,
        "progress_format": execution_progress_storage_evidence(
            bundle.plan,
            bundle.progress_payload,
        ),
    }


def _execute_workload(
    spec: WorkloadSpec,
    experiment_dir: Path,
    *,
    operation_hook: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    cpu_started = time.process_time_ns()
    run_started = time.perf_counter_ns()
    _create_prepared_bundle(experiment_dir, spec)
    model = _build_hardware_isolated_model(experiment_dir)
    experiment = model.experiment_model
    plan = experiment.get_execution_plan_snapshot()
    if plan is None or len(plan.stocks) != spec.stock_count:
        raise WorkloadInvariantError("activated execution plan does not match workload")

    samples = {phase: [] for phase in PHASE_NAMES}
    observed_intent_ids: list[str] = []
    completed_intent_ids: list[str] = []
    expected_sequences: list[int] = []
    initial_sizes = _capture_file_sizes(experiment_dir)
    file_size_samples = {
        name: [size] for name, size in initial_sizes.items()
    }
    io_observer = PersistenceIoObserver(experiment_dir)
    progress_observer = ProgressSnapshotObserver(experiment)
    checkpoint_sizes_by_phase = {
        "after_begin": [],
        "after_attach": [],
        "after_complete": [],
    }
    retained_intents_by_phase = {
        "after_begin": [],
        "after_attach": [],
        "after_complete": [],
    }
    sequence = 1
    completion_index = 0

    def timed_phase(name: str, call: Callable[[], Any]) -> tuple[Any, float]:
        def invoke():
            if operation_hook is not None:
                operation_hook(name, completion_index, spec.completion_count)
            return call()

        with io_observer.phase(name):
            return _timed(invoke)

    def capture_checkpoint(phase: str) -> None:
        checkpoint_sizes_by_phase[phase].append(
            Path(experiment.execution_resume_file_path).stat().st_size
        )
        session = experiment._active_authoritative_execution_session
        retained_intents_by_phase[phase].append(len(session.resume.intents))

    with io_observer.installed(), progress_observer.installed():
        for stock_index, stock in enumerate(plan.stocks, start=1):
            for well_id in spec.well_ids:
                completion_index += 1
                total_started = time.perf_counter_ns()
                intent_id, elapsed = timed_phase(
                    "begin_intent",
                    lambda well_id=well_id, stock=stock, stock_index=stock_index: (
                        experiment.begin_execution_print_intent(
                            well_id=well_id,
                            stock_id=stock.stock_id,
                            commanded_droplets=spec.target_dispenses,
                            printer_head_id=f"virtual-head-{stock_index}",
                        )
                    ),
                )
                samples["begin_intent"].append(elapsed)
                if not intent_id:
                    raise WorkloadInvariantError(
                        "durable execution intent was not created"
                    )
                observed_intent_ids.append(intent_id)
                capture_checkpoint("after_begin")

                _, elapsed = timed_phase(
                    "attach_sequence",
                    lambda intent_id=intent_id, sequence=sequence: (
                        experiment.attach_execution_print_command(intent_id, sequence)
                    ),
                )
                samples["attach_sequence"].append(elapsed)
                expected_sequences.append(sequence)
                capture_checkpoint("after_attach")
                sequence += 1

                well = model.well_plate.get_well(well_id)
                if well is None:
                    raise WorkloadInvariantError(
                        f"runtime well {well_id!r} is unavailable"
                    )
                _, elapsed = timed_phase(
                    "update_runtime",
                    lambda well=well, stock=stock: well.record_stock_print(
                        stock.stock_id,
                        spec.target_dispenses,
                    ),
                )
                samples["update_runtime"].append(elapsed)

                _, elapsed = timed_phase(
                    "write_progress",
                    lambda intent_id=intent_id: experiment.create_progress_file(
                        execution_intent_id=intent_id,
                    ),
                )
                samples["write_progress"].append(elapsed)
                _, elapsed = timed_phase(
                    "complete_intent",
                    lambda intent_id=intent_id: (
                        experiment.complete_execution_print_intent(intent_id)
                    ),
                )
                samples["complete_intent"].append(elapsed)
                completed_intent_ids.append(intent_id)
                capture_checkpoint("after_complete")
                samples["well_total"].append(
                    (time.perf_counter_ns() - total_started) / 1_000_000.0
                )

                # File-size observation is deliberately outside well_total timing.
                current_sizes = _capture_file_sizes(experiment_dir)
                for name, size in current_sizes.items():
                    file_size_samples[name].append(size)

    durable_io = io_observer.snapshot()
    progress_snapshot = progress_observer.snapshot()
    progress_fsync = durable_io.get("fsync", {}).get("write_progress", [])
    progress_replace = durable_io.get("atomic_replace", {}).get(
        "write_progress",
        [],
    )
    progress_snapshot["non_durable_write_samples_ms"] = (
        non_durable_progress_samples(
            samples["write_progress"],
            progress_fsync,
            progress_replace,
        )
    )
    expected = spec.completion_count
    snapshot_counts = progress_snapshot["mode_counts"]
    snapshot_durations = progress_snapshot["duration_samples_ms"]
    if (
        snapshot_counts.get("cached_update") != expected
        or snapshot_counts.get("full_rebuild") != 0
        or len(snapshot_durations.get("serialization", [])) != expected
        or len(snapshot_durations.get("atomic_write", [])) != expected
        or len(progress_snapshot["serialized_size_bytes"]) != expected
        or len(progress_snapshot["non_durable_write_samples_ms"]) != expected
        or not progress_snapshot.get("observer_restored")
    ):
        raise WorkloadInvariantError(
            "progress snapshot evidence violated the cached-construction contract"
        )
    validation = _validate_completed_workload(
        model,
        experiment_dir,
        observed_intent_ids,
        expected_sequences,
        completed_intent_ids,
        max(
            (
                count
                for values in retained_intents_by_phase.values()
                for count in values
            ),
            default=0,
        ),
    )
    return {
        "duration_ms": (time.perf_counter_ns() - run_started) / 1_000_000.0,
        "process_cpu_ms": (time.process_time_ns() - cpu_started) / 1_000_000.0,
        "samples_ms": samples,
        "phase_statistics_ms": {
            phase: _distribution(values) for phase, values in samples.items()
        },
        "quartile_growth": _quartile_growth(samples["well_total"]),
        "file_size_samples_bytes": file_size_samples,
        "resume_checkpoint_samples": {
            "size_bytes_by_phase": checkpoint_sizes_by_phase,
            "retained_intents_by_phase": retained_intents_by_phase,
        },
        "durable_io_samples_ms": durable_io,
        "progress_snapshot": progress_snapshot,
        "authoritative_read_opens": io_observer.read_snapshot(),
        "validation": validation,
    }


def _empty_metrics() -> dict[str, dict[str, Any]]:
    return {
        "responsiveness": {"status": "not_available", "values": {}},
        "workflow": {"status": "not_available", "values": {}},
        "queue": {"status": "not_applicable", "values": {}},
        "persistence": {"status": "not_available", "values": {}},
        "resources": {"status": "not_available", "values": {}},
    }


def _aggregate_file_growth(
    measured: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    file_names = sorted(
        {
            name
            for run in measured
            for name in run["file_size_samples_bytes"]
        }
    )
    aggregate: dict[str, dict[str, Any]] = {}
    for name in file_names:
        run_rows = []
        for run in measured:
            samples = list(run["file_size_samples_bytes"][name])
            run_rows.append(
                {
                    "run_index": run.get("run_index"),
                    "sample_count": len(samples),
                    "initial_size_bytes": samples[0],
                    "final_size_bytes": samples[-1],
                    "growth_bytes": samples[-1] - samples[0],
                    "linear_slope_bytes_per_completion": linear_slope(samples),
                }
            )
        aggregate[name] = {
            "initial_size_bytes": _distribution(
                [row["initial_size_bytes"] for row in run_rows]
            ),
            "final_size_bytes": _distribution(
                [row["final_size_bytes"] for row in run_rows]
            ),
            "growth_bytes": _distribution(
                [row["growth_bytes"] for row in run_rows]
            ),
            "linear_slope_bytes_per_completion": _distribution(
                [row["linear_slope_bytes_per_completion"] for row in run_rows]
            ),
            "runs": run_rows,
        }
    return aggregate


def _aggregate_durable_io(
    measured: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    operations = ("fsync", "atomic_replace")
    aggregate: dict[str, dict[str, Any]] = {}
    for operation in operations:
        phases = sorted(
            {
                phase
                for run in measured
                for phase in run["durable_io_samples_ms"].get(operation, {})
            }
        )
        by_phase = {
            phase: [
                sample
                for run in measured
                for sample in run["durable_io_samples_ms"]
                .get(operation, {})
                .get(phase, [])
            ]
            for phase in phases
        }
        all_samples = [
            sample for values in by_phase.values() for sample in values
        ]
        aggregate[operation] = {
            "overall": _distribution(all_samples),
            "by_phase": {
                phase: _distribution(values)
                for phase, values in by_phase.items()
            },
        }
    return aggregate


def _aggregate_resume_checkpoint_bounds(
    measured: list[dict[str, Any]],
) -> dict[str, Any]:
    run_rows = []
    for run in measured:
        samples = run["resume_checkpoint_samples"]
        sizes = samples["size_bytes_by_phase"]
        retained = samples["retained_intents_by_phase"]
        all_sizes = [value for values in sizes.values() for value in values]
        all_retained = [value for values in retained.values() for value in values]
        run_rows.append(
            {
                "run_index": run.get("run_index"),
                "peak_size_bytes": max(all_sizes, default=0),
                "clean_size_bytes": (
                    sizes["after_complete"][-1]
                    if sizes["after_complete"]
                    else 0
                ),
                "peak_retained_intent_count": max(all_retained, default=0),
                "final_retained_intent_count": (
                    retained["after_complete"][-1]
                    if retained["after_complete"]
                    else 0
                ),
                "size_bytes_by_phase": sizes,
                "retained_intents_by_phase": retained,
            }
        )
    return {
        "peak_size_bytes": _distribution(
            [row["peak_size_bytes"] for row in run_rows]
        ),
        "clean_size_bytes": _distribution(
            [row["clean_size_bytes"] for row in run_rows]
        ),
        "peak_retained_intent_count": max(
            (row["peak_retained_intent_count"] for row in run_rows),
            default=0,
        ),
        "final_retained_intent_count": max(
            (row["final_retained_intent_count"] for row in run_rows),
            default=0,
        ),
        "runs": run_rows,
    }


def _aggregate_authoritative_reads(
    measured: list[dict[str, Any]],
) -> dict[str, Any]:
    by_path: dict[str, dict[str, int]] = {}
    by_run = []
    for run in measured:
        snapshot = run.get("authoritative_read_opens", {})
        by_run.append(
            {
                "run_index": run.get("run_index"),
                "total_count": int(snapshot.get("total_count", 0)),
                "observer_restored": bool(snapshot.get("observer_restored")),
                "by_path": dict(snapshot.get("by_path", {})),
            }
        )
        for path, values in snapshot.get("by_path", {}).items():
            aggregate = by_path.setdefault(
                path,
                {"count": 0, "observed_file_size_bytes": 0},
            )
            aggregate["count"] += int(values.get("count", 0))
            aggregate["observed_file_size_bytes"] += int(
                values.get("observed_file_size_bytes", 0)
            )
    return {
        "by_path": dict(sorted(by_path.items())),
        "total_count": sum(item["count"] for item in by_path.values()),
        "all_observers_restored": all(
            row["observer_restored"] for row in by_run
        ),
        "runs": by_run,
    }


def _aggregate_progress_snapshots(
    measured: list[dict[str, Any]],
) -> dict[str, Any]:
    modes = ("full_rebuild", "cached_update")
    phases = ("full_rebuild", "cached_update", "serialization", "atomic_write")
    runs = []
    for run in measured:
        snapshot = run.get(
            "progress_snapshot",
            {
                "mode_counts": {},
                "duration_samples_ms": {},
                "serialized_size_bytes": [],
                "non_durable_write_samples_ms": [],
                "observer_restored": True,
            },
        )
        runs.append(
            {
                "run_index": run.get("run_index"),
                **snapshot,
            }
        )
    serialized_samples = [
        sample
        for run in measured
        for sample in run.get("progress_snapshot", {}).get(
            "serialized_size_bytes",
            [],
        )
    ]
    return {
        "mode_counts": {
            mode: sum(
                int(
                    run.get("progress_snapshot", {})
                    .get("mode_counts", {})
                    .get(mode, 0)
                )
                for run in measured
            )
            for mode in modes
        },
        "duration_statistics_ms": {
            phase: _distribution(
                [
                    sample
                    for run in measured
                    for sample in run.get("progress_snapshot", {})
                    .get("duration_samples_ms", {})
                    .get(phase, [])
                ]
            )
            for phase in phases
        },
        "serialized_size_bytes": _distribution(serialized_samples),
        "cumulative_serialized_bytes": sum(
            int(sample) for sample in serialized_samples
        ),
        "progress_formats": [
            {
                "run_index": run.get("run_index"),
                **run.get("validation", {}).get("progress_format", {}),
            }
            for run in measured
        ],
        "non_durable_write_ms": _distribution(
            [
                sample
                for run in measured
                for sample in run.get("progress_snapshot", {}).get(
                    "non_durable_write_samples_ms",
                    [],
                )
            ]
        ),
        "all_observers_restored": all(
            bool(run.get("progress_snapshot", {}).get("observer_restored", True))
            for run in measured
        ),
        "runs": runs,
    }


def _aggregate_metrics(
    measured: list[dict[str, Any]],
    spec: WorkloadSpec,
) -> dict[str, dict[str, Any]]:
    duration_values = [run["duration_ms"] for run in measured]
    cpu_values = [run["process_cpu_ms"] for run in measured]
    combined_samples = {
        phase: [
            sample
            for run in measured
            for sample in run["samples_ms"][phase]
        ]
        for phase in PHASE_NAMES
    }
    well_totals = combined_samples["well_total"]
    growth_rows = [
        {
            "run_index": run.get("run_index"),
            **run["quartile_growth"],
        }
        for run in measured
    ]
    first_quartile = [
        sample
        for run in measured
        for sample in run["samples_ms"]["well_total"][
            : run["quartile_growth"]["quartile_completion_count"]
        ]
    ]
    last_quartile = [
        sample
        for run in measured
        for sample in run["samples_ms"]["well_total"][
            -run["quartile_growth"]["quartile_completion_count"] :
        ]
    ]
    growth_ratio = _distribution(
        [row["last_to_first_mean_ratio"] for row in growth_rows]
    )
    growth_delta = _distribution(
        [row["last_minus_first_mean_ms"] for row in growth_rows]
    )
    candidate_regression = bool(
        growth_ratio["p50"] > GROWTH_RATIO_WARNING_THRESHOLD
        and growth_delta["p50"] > GROWTH_DELTA_WARNING_THRESHOLD_MS
    )
    mean_duration = statistics.fmean(duration_values) if duration_values else 0.0
    duration_cv = (
        statistics.pstdev(duration_values) / mean_duration
        if len(duration_values) > 1 and mean_duration
        else 0.0
    )
    return {
        "responsiveness": {
            "status": "not_available",
            "values": {},
        },
        "workflow": {
            "status": "measured",
            "values": {
                "wells_planned_per_array": len(spec.well_ids),
                "wells_completed_per_array": len(spec.well_ids),
                "array_passes": spec.stock_count,
                "lifecycle_completions_per_run": spec.completion_count,
                "measured_runs": len(measured),
            },
        },
        "queue": {
            "status": "not_applicable",
            "values": {},
        },
        "persistence": {
            "status": "measured",
            "values": {
                "run_duration_ms": _distribution(duration_values),
                "run_duration_coefficient_of_variation": duration_cv,
                "phase_statistics_ms": {
                    phase: {
                        **_distribution(values),
                        "linear_slope_ms_per_operation": linear_slope(values),
                    }
                    for phase, values in combined_samples.items()
                },
                "well_total_first_quartile_ms": _distribution(first_quartile),
                "well_total_last_quartile_ms": _distribution(last_quartile),
                "well_total_last_to_first_mean_ratio": growth_ratio["p50"],
                "well_total_growth_by_run": growth_rows,
                "well_total_growth_ratio": growth_ratio,
                "well_total_growth_delta_ms": growth_delta,
                "growth_assessment": {
                    "threshold_maturity": "informational",
                    "ratio_warning_threshold": GROWTH_RATIO_WARNING_THRESHOLD,
                    "absolute_delta_warning_threshold_ms": (
                        GROWTH_DELTA_WARNING_THRESHOLD_MS
                    ),
                    "observed_median_ratio": growth_ratio["p50"],
                    "observed_median_delta_ms": growth_delta["p50"],
                    "candidate_regression": candidate_regression,
                    "classification_effect": (
                        "warning" if candidate_regression else "pass"
                    ),
                },
                "file_growth": _aggregate_file_growth(measured),
                "resume_checkpoint_bounds": (
                    _aggregate_resume_checkpoint_bounds(measured)
                ),
                "durable_io_statistics_ms": _aggregate_durable_io(measured),
                "authoritative_read_opens": _aggregate_authoritative_reads(measured),
                "progress_snapshot": _aggregate_progress_snapshots(measured),
                "runs": measured,
            },
        },
        "resources": {
            "status": "partial",
            "values": {
                "process_cpu_ms": _distribution(cpu_values),
                "peak_resident_memory_bytes": None,
                "operating_system_io_bytes": None,
            },
        },
    }


def _base_report(
    *,
    identity: dict[str, dict[str, Any]],
    spec: WorkloadSpec,
    warmup_runs: int,
    measured_runs: int,
    started_at: str,
) -> dict[str, Any]:
    return {
        "schema_name": REPORT_SCHEMA_NAME,
        "schema_version": REPORT_SCHEMA_VERSION,
        "run": {
            "run_id": str(uuid.uuid4()),
            "scenario_name": SCENARIO_NAME,
            "scenario_version": SCENARIO_VERSION,
            "run_mode": "host_characterization",
            "timing_policy": "unpaced_host_persistence",
            "warmup_runs": warmup_runs,
            "measured_runs": measured_runs,
            "started_at_utc": started_at,
            "ended_at_utc": started_at,
            "duration_ms": 0.0,
        },
        "source": identity["source"],
        "environment": identity["environment"],
        "safety": {
            "simulation": True,
            "hardware_access_allowed": False,
            "construction_path": (
                "Model.__new__ + ExperimentModel + WellPlate; no App, Controller, "
                "Machine_FreeRTOS, transport, or device construction"
            ),
            "hardware_interfaces": {
                "serial": False,
                "gpio": False,
                "camera": False,
                "balance": False,
                "mcu": False,
                "firmware_update": False,
            },
        },
        "workload": spec.to_report(),
        "metrics": _empty_metrics(),
        "artifacts": {
            "report_json": "report.json",
            "summary_text": "summary.txt",
            "retained_workloads": [],
        },
        "classification": {
            "status": "pass",
            "threshold_maturity": "informational",
            "reasons": [
                "persistence benchmark completed without candidate growth warning; "
                "no acceptance gate evaluated"
            ],
        },
        "limitations": [
            "No Qt event loop or real widget is exercised.",
            "No Controller, command queue, transport, serial framing, MCU, or hardware is exercised.",
            "The workload is intentionally unpaced and does not model physical dispense time.",
            "Peak resident memory and operating-system I/O byte counters are not collected.",
            "Durable I/O timings include the small overhead of the synchronous observation wrapper.",
            "A pass or warning means the benchmark and durability invariants completed; it is not performance acceptance.",
        ],
    }


def _write_summary(path: Path, report: dict[str, Any]) -> None:
    persistence = report["metrics"]["persistence"]["values"]
    lines = [
        "LabCraft execution persistence microbenchmark",
        f"Classification: {report['classification']['status']} "
        f"({report['classification']['threshold_maturity']})",
        f"Run ID: {report['run']['run_id']}",
        f"Workload: {report['workload'].get('workload_id')}",
        f"Assigned wells / stocks / completions: "
        f"{report['workload'].get('assigned_wells')} / "
        f"{report['workload'].get('stock_count')} / "
        f"{report['workload'].get('lifecycle_completions')}",
        f"Commit: {report['source'].get('git_commit') or 'unavailable'}",
        f"Dirty worktree: {report['source'].get('dirty_worktree')}",
        f"Environment: Python {report['environment']['python_version']}, "
        f"PySide6 {report['environment']['qt'].get('pyside_version')}, "
        f"Qt {report['environment']['qt'].get('qt_version')} "
        f"({report['environment']['qt'].get('binding')})",
    ]
    if persistence:
        run_stats = persistence["run_duration_ms"]
        well_stats = persistence["phase_statistics_ms"]["well_total"]
        growth = persistence.get("growth_assessment", {})
        bounds = persistence.get("resume_checkpoint_bounds", {})
        lines.extend(
            [
                f"Measured runs: {report['run']['measured_runs']}",
                f"Run duration mean/p95/max ms: "
                f"{run_stats['mean']:.3f} / {run_stats['p95']:.3f} / "
                f"{run_stats['maximum']:.3f}",
                f"Per-completion p50/p95/p99/max ms: "
                f"{well_stats['p50']:.3f} / {well_stats['p95']:.3f} / "
                f"{well_stats['p99']:.3f} / {well_stats['maximum']:.3f}",
                f"Last/first quartile mean ratio: "
                f"{persistence['well_total_last_to_first_mean_ratio']:.4f}",
                f"Median last-first quartile delta ms: "
                f"{growth.get('observed_median_delta_ms', 0.0):.3f}",
                f"Candidate growth detected: "
                f"{growth.get('candidate_regression', False)}",
                "Resume checkpoint peak/final retained intents: "
                f"{bounds.get('peak_retained_intent_count', 0)} / "
                f"{bounds.get('final_retained_intent_count', 0)}",
                "Resume checkpoint peak/clean p50 bytes: "
                f"{(bounds.get('peak_size_bytes') or {}).get('p50', 0.0):.1f} / "
                f"{(bounds.get('clean_size_bytes') or {}).get('p50', 0.0):.1f}",
                f"Run duration coefficient of variation: "
                f"{persistence['run_duration_coefficient_of_variation']:.4f}",
            ]
        )
        durable_io = persistence.get("durable_io_statistics_ms", {})
        lines.append(
            "Durable fsync / atomic replace calls: "
            f"{durable_io.get('fsync', {}).get('overall', {}).get('count', 0)} / "
            f"{durable_io.get('atomic_replace', {}).get('overall', {}).get('count', 0)}"
        )
        reads = persistence.get("authoritative_read_opens", {})
        lines.append(
            "Authoritative hot-path read opens: "
            f"{reads.get('total_count', 0)}; "
            f"observers restored: {reads.get('all_observers_restored', False)}"
        )
        snapshot = persistence.get("progress_snapshot", {})
        modes = snapshot.get("mode_counts", {})
        non_durable = snapshot.get("non_durable_write_ms", {})
        serialized = snapshot.get("serialized_size_bytes", {})
        progress_formats = snapshot.get("progress_formats", [])
        progress_format = progress_formats[0] if progress_formats else {}
        lines.extend(
            [
                "Progress full rebuild / cached update counts: "
                f"{modes.get('full_rebuild', 0)} / "
                f"{modes.get('cached_update', 0)}",
                "Progress non-durable p50/p95 ms: "
                f"{non_durable.get('p50', 0.0):.3f} / "
                f"{non_durable.get('p95', 0.0):.3f}",
                "Progress serialized p50/max bytes: "
                f"{serialized.get('p50', 0.0):.1f} / "
                f"{serialized.get('maximum', 0.0):.1f}",
                "Progress schema/final bytes/v1 ratio: "
                f"v{progress_format.get('schema_version', 'unknown')} / "
                f"{progress_format.get('encoded_size_bytes', 0)} / "
                f"{progress_format.get('encoded_to_v1_ratio', 0.0):.4f}",
                "Cumulative progress serialized bytes: "
                f"{snapshot.get('cumulative_serialized_bytes', 0)}",
                "Progress snapshot observers restored: "
                f"{snapshot.get('all_observers_restored', False)}",
            ]
        )
        for name, values in persistence.get("file_growth", {}).items():
            growth_bytes = values.get("growth_bytes", {})
            lines.append(
                f"{name} median/final growth bytes: "
                f"{growth_bytes.get('p50', 0.0):.1f} / "
                f"{values.get('final_size_bytes', {}).get('p50', 0.0):.1f}"
            )
    for reason in report["classification"]["reasons"]:
        lines.append(f"Reason: {reason}")
    lines.append("This report is informational and does not establish acceptance.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_characterization(
    *,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    warmup_runs: int = 1,
    measured_runs: int = 5,
    keep_workload_artifacts: str = "on-failure",
    spec: WorkloadSpec = BASELINE_WORKLOAD,
    operation_hook: Callable[[str, int, int], None] | None = None,
) -> tuple[int, Path]:
    if warmup_runs < 0:
        raise ValueError("warmup_runs must be non-negative")
    if measured_runs < 1:
        raise ValueError("measured_runs must be at least one")
    if keep_workload_artifacts not in KEEP_POLICIES:
        raise ValueError(
            "keep_workload_artifacts must be never, on-failure, or always"
        )

    identity = collect_environment_identity(REPO_ROOT)
    started_at = _utc_now()
    directory_stamp = started_at.replace("-", "").replace(":", "").replace(".", "")
    directory_stamp = directory_stamp.replace("+0000", "Z")
    short_commit = identity["source"].get("git_short_commit") or "nogit"
    run_dir = Path(output_root).resolve() / spec.workload_id / (
        f"{directory_stamp}_{short_commit}"
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    workloads_dir = run_dir / "workloads"
    report = _base_report(
        identity=identity,
        spec=spec,
        warmup_runs=warmup_runs,
        measured_runs=measured_runs,
        started_at=started_at,
    )
    overall_started = time.perf_counter_ns()
    exit_code = 0
    measured: list[dict[str, Any]] = []
    failed_workload: Path | None = None

    try:
        total_runs = warmup_runs + measured_runs
        for index in range(total_runs):
            is_warmup = index < warmup_runs
            kind = "warmup" if is_warmup else "measured"
            ordinal = index + 1 if is_warmup else index - warmup_runs + 1
            workload_name = f"{kind}_{ordinal:02d}"
            temporary_root = Path(
                tempfile.mkdtemp(prefix=f"labcraft_{workload_name}_")
            )
            workload_dir = temporary_root / "experiment"
            try:
                # Existing model objects print state-change diagnostics per well.
                # Keep CLI output bounded while preserving the write call itself.
                with open(os.devnull, "w", encoding="utf-8") as output_sink:
                    with contextlib.redirect_stdout(output_sink):
                        if operation_hook is None:
                            result = _execute_workload(spec, workload_dir)
                        else:
                            result = _execute_workload(
                                spec,
                                workload_dir,
                                operation_hook=operation_hook,
                            )
                if keep_workload_artifacts == "always":
                    workloads_dir.mkdir(exist_ok=True)
                    retained = workloads_dir / workload_name
                    shutil.copytree(workload_dir, retained)
                    report["artifacts"]["retained_workloads"].append(
                        retained.relative_to(run_dir).as_posix()
                    )
            except Exception:
                if keep_workload_artifacts in {"on-failure", "always"}:
                    workloads_dir.mkdir(exist_ok=True)
                    retained = workloads_dir / workload_name
                    shutil.copytree(workload_dir, retained)
                    failed_workload = retained
                raise
            finally:
                shutil.rmtree(temporary_root, ignore_errors=True)
            if not is_warmup:
                result["run_index"] = ordinal
                measured.append(result)
    except Exception as exc:
        exit_code = 2
        report["classification"] = {
            "status": "fail",
            "threshold_maturity": "informational",
            "reasons": [f"{type(exc).__name__}: {exc}"],
        }
        report["limitations"].append(
            "The workload aborted before all measurements completed."
        )
        report["artifacts"]["failure_traceback"] = "failure_traceback.txt"
        (run_dir / "failure_traceback.txt").write_text(
            traceback.format_exc(),
            encoding="utf-8",
        )
        if failed_workload is not None and failed_workload.exists():
            report["artifacts"]["retained_workloads"].append(
                failed_workload.relative_to(run_dir).as_posix()
            )
    finally:
        if measured:
            report["metrics"] = _aggregate_metrics(measured, spec)
            growth = report["metrics"]["persistence"]["values"].get(
                "growth_assessment",
                {},
            )
            if exit_code == 0 and growth.get("candidate_regression"):
                report["classification"] = {
                    "status": "warning",
                    "threshold_maturity": "informational",
                    "reasons": [
                        "candidate persistence growth detected: median last/first "
                        f"quartile ratio {growth['observed_median_ratio']:.4f} "
                        f"(>{growth['ratio_warning_threshold']:.2f}) and median "
                        f"delta {growth['observed_median_delta_ms']:.3f} ms "
                        f"(>{growth['absolute_delta_warning_threshold_ms']:.1f} ms); "
                        "no acceptance gate evaluated"
                    ],
                }
        if workloads_dir.exists() and not any(workloads_dir.iterdir()):
            workloads_dir.rmdir()
        report["run"]["ended_at_utc"] = _utc_now()
        report["run"]["duration_ms"] = (
            time.perf_counter_ns() - overall_started
        ) / 1_000_000.0

    report_path = run_dir / "report.json"
    try:
        write_report_atomic(report_path, report)
        _write_summary(run_dir / "summary.txt", report)
    except Exception:
        failure_path = run_dir / "reporting_failure.txt"
        failure_path.write_text(traceback.format_exc(), encoding="utf-8")
        return 3, report_path
    return exit_code, report_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Characterize durable execution persistence without constructing "
            "the UI, Controller, communication stack, or hardware."
        )
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Generated report root (default: verification_reports/virtual_workflows).",
    )
    parser.add_argument(
        "--workload",
        choices=sorted(WORKLOAD_CATALOG),
        default=WORKLOAD_ID,
        help=f"Versioned workload ID (default: {WORKLOAD_ID}).",
    )
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--measured-runs", type=int, default=5)
    parser.add_argument(
        "--keep-workload-artifacts",
        choices=sorted(KEEP_POLICIES),
        default="on-failure",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        exit_code, report_path = run_characterization(
            output_root=args.output_root,
            warmup_runs=args.warmup_runs,
            measured_runs=args.measured_runs,
            keep_workload_artifacts=args.keep_workload_artifacts,
            spec=WORKLOAD_CATALOG[args.workload],
        )
    except (OSError, ValueError) as exc:
        print(f"characterization setup failed: {exc}", file=sys.stderr)
        return 3
    print(report_path)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
