#!/usr/bin/env python3
"""Characterize durable execution persistence without constructing hardware."""

from __future__ import annotations

import argparse
import contextlib
import json
import math
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
from ExecutionPlan import ProgressExecutionReference, save_execution_plan
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


SCENARIO_NAME = "execution_persistence"
SCENARIO_VERSION = "1"
WORKLOAD_ID = "execution_persistence_v1"
DEFAULT_OUTPUT_ROOT = Path("verification_reports") / "virtual_workflows"
KEEP_POLICIES = {"never", "on-failure", "always"}
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _linear_slope(values: list[float]) -> float:
    count = len(values)
    if count < 2:
        return 0.0
    mean_x = (count - 1) / 2.0
    mean_y = statistics.fmean(values)
    denominator = sum((index - mean_x) ** 2 for index in range(count))
    if denominator == 0:
        return 0.0
    return sum(
        (index - mean_x) * (value - mean_y)
        for index, value in enumerate(values)
    ) / denominator


def _distribution(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {
            "count": 0,
            "mean": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "maximum": 0.0,
        }
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "maximum": max(values),
    }


def _timed(call: Callable[[], Any]) -> tuple[Any, float]:
    started = time.perf_counter_ns()
    result = call()
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    return result, elapsed_ms


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
        "name": spec.plate_name,
        "rows": spec.plate_rows,
        "columns": spec.plate_columns,
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
    expected_sequences: list[int],
) -> dict[str, Any]:
    experiment = model.experiment_model
    checkpoint = load_execution_resume(experiment.execution_resume_file_path)
    if checkpoint.state != "clean":
        raise WorkloadInvariantError(
            f"execution checkpoint ended in {checkpoint.state!r}, not 'clean'"
        )
    intents = list(checkpoint.intents)
    if len(intents) != len(expected_sequences):
        raise WorkloadInvariantError(
            f"expected {len(expected_sequences)} intents, found {len(intents)}"
        )
    actual_sequences = [intent.command_seq32 for intent in intents]
    if actual_sequences != expected_sequences:
        raise WorkloadInvariantError(
            "intent command sequences are not unique and monotonically increasing"
        )
    if any(intent.status != "completed" for intent in intents):
        raise WorkloadInvariantError("not every execution intent is completed")

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
        "intent_count": len(intents),
        "authoritative_bundle_valid": bundle.valid,
        "targets_match_progress": True,
        "file_sizes_bytes": file_sizes,
    }


def _execute_workload(spec: WorkloadSpec, experiment_dir: Path) -> dict[str, Any]:
    cpu_started = time.process_time_ns()
    run_started = time.perf_counter_ns()
    _create_prepared_bundle(experiment_dir, spec)
    model = _build_hardware_isolated_model(experiment_dir)
    experiment = model.experiment_model
    plan = experiment.get_execution_plan_snapshot()
    if plan is None or len(plan.stocks) != spec.stock_count:
        raise WorkloadInvariantError("activated execution plan does not match workload")

    samples = {phase: [] for phase in PHASE_NAMES}
    expected_sequences: list[int] = []
    sequence = 1
    for stock_index, stock in enumerate(plan.stocks, start=1):
        for well_id in spec.well_ids:
            total_started = time.perf_counter_ns()
            intent_id, elapsed = _timed(
                lambda well_id=well_id, stock=stock, stock_index=stock_index: (
                    experiment.begin_execution_print_intent(
                        well_id=well_id,
                        stock_id=stock.stock_id,
                        commanded_droplets=spec.target_dispenses,
                        printer_head_id=f"virtual-head-{stock_index}",
                    )
                )
            )
            samples["begin_intent"].append(elapsed)
            if not intent_id:
                raise WorkloadInvariantError("durable execution intent was not created")

            _, elapsed = _timed(
                lambda intent_id=intent_id, sequence=sequence: (
                    experiment.attach_execution_print_command(intent_id, sequence)
                )
            )
            samples["attach_sequence"].append(elapsed)
            expected_sequences.append(sequence)
            sequence += 1

            well = model.well_plate.get_well(well_id)
            if well is None:
                raise WorkloadInvariantError(f"runtime well {well_id!r} is unavailable")
            _, elapsed = _timed(
                lambda well=well, stock=stock: well.record_stock_print(
                    stock.stock_id,
                    spec.target_dispenses,
                )
            )
            samples["update_runtime"].append(elapsed)

            _, elapsed = _timed(experiment.create_progress_file)
            samples["write_progress"].append(elapsed)
            _, elapsed = _timed(
                lambda intent_id=intent_id: (
                    experiment.complete_execution_print_intent(intent_id)
                )
            )
            samples["complete_intent"].append(elapsed)
            samples["well_total"].append(
                (time.perf_counter_ns() - total_started) / 1_000_000.0
            )

    validation = _validate_completed_workload(
        model,
        experiment_dir,
        expected_sequences,
    )
    return {
        "duration_ms": (time.perf_counter_ns() - run_started) / 1_000_000.0,
        "process_cpu_ms": (time.process_time_ns() - cpu_started) / 1_000_000.0,
        "samples_ms": samples,
        "phase_statistics_ms": {
            phase: _distribution(values) for phase, values in samples.items()
        },
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
    quartile_count = max(1, len(well_totals) // 4)
    first_quartile = well_totals[:quartile_count]
    last_quartile = well_totals[-quartile_count:]
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
                        "linear_slope_ms_per_operation": _linear_slope(values),
                    }
                    for phase, values in combined_samples.items()
                },
                "well_total_first_quartile_ms": _distribution(first_quartile),
                "well_total_last_quartile_ms": _distribution(last_quartile),
                "well_total_last_to_first_mean_ratio": (
                    statistics.fmean(last_quartile)
                    / statistics.fmean(first_quartile)
                    if first_quartile
                    and last_quartile
                    and statistics.fmean(first_quartile)
                    else 0.0
                ),
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
            "reasons": ["characterization completed; no performance gate evaluated"],
        },
        "limitations": [
            "No Qt event loop or real widget is exercised.",
            "No Controller, command queue, transport, serial framing, MCU, or hardware is exercised.",
            "The workload is intentionally unpaced and does not model physical dispense time.",
            "Peak resident memory and operating-system I/O byte counters are not collected in Slice 0.",
            "A pass means the characterization and durability invariants completed; it is not performance acceptance.",
        ],
    }


def _write_summary(path: Path, report: dict[str, Any]) -> None:
    persistence = report["metrics"]["persistence"]["values"]
    lines = [
        "LabCraft execution persistence characterization",
        f"Classification: {report['classification']['status']} "
        f"({report['classification']['threshold_maturity']})",
        f"Run ID: {report['run']['run_id']}",
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
                f"Run duration coefficient of variation: "
                f"{persistence['run_duration_coefficient_of_variation']:.4f}",
            ]
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
    run_dir = Path(output_root).resolve() / WORKLOAD_ID / (
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
                        result = _execute_workload(spec, workload_dir)
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
        )
    except (OSError, ValueError) as exc:
        print(f"characterization setup failed: {exc}", file=sys.stderr)
        return 3
    print(report_path)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
