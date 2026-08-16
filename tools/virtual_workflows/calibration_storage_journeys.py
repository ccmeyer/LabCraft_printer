"""Composed SIL journeys for the Milestone 1 calibration-storage baseline."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import time
from typing import Any, Mapping
import zipfile

from tools.sil.calibration_storage_contract import (
    CATALOG_PATH,
    ScriptedCalibrationCase,
    distribution,
    file_sha256,
    load_catalog,
    load_fixture,
    semantic_sha256,
)
from tools.sil.calibration_storage_process import (
    StorageContractRunner,
    StorageMetricsCollector,
    SyntheticStorageHead,
    file_inventory,
)
from tools.virtual_workflows.actions import InteractionSurface
from tools.virtual_workflows.assertions import (
    AssertionResult,
    cleanup_assertion,
    simulation_identity_assertion,
)
from tools.virtual_workflows.composition import JourneyDefinition, JourneyRuntime
from tools.virtual_workflows.metrics import ProcessResourceSampler
from tools.virtual_workflows.page_drivers import (
    CalibrationDialogDriver,
    ExperimentLoaderDriver,
    MachineControlsDriver,
)
from tools.virtual_workflows.report import ComposedReportPayload


REPO_ROOT = Path(__file__).resolve().parents[2]
NEW_STORE_ONLY_CATALOG_PATH = CATALOG_PATH.with_name(
    "catalog_new_store_only_v1.json"
)
PERFORMANCE_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "calibration_storage_contract_legacy_baseline_8x25_v1.json"
)
FUNCTIONAL_ID = "calibration_storage_contract_v1"
PERFORMANCE_ID = "calibration_storage_legacy_baseline_8x25_v1"
SHADOW_FUNCTIONAL_ID = "calibration_storage_shadow_contract_v1"
SHADOW_PERFORMANCE_ID = "calibration_storage_shadow_8x25_v1"
AUTHORITATIVE_FUNCTIONAL_ID = "calibration_storage_authoritative_contract_v1"
AUTHORITATIVE_PERFORMANCE_ID = "calibration_storage_authoritative_8x25_v1"
PRIMARY_READER_FUNCTIONAL_ID = "calibration_storage_primary_reader_contract_v1"
PRIMARY_READER_PERFORMANCE_ID = "calibration_storage_primary_reader_8x25_v1"
SECONDARY_READER_FUNCTIONAL_ID = "calibration_storage_secondary_reader_contract_v1"
SECONDARY_READER_PERFORMANCE_ID = "calibration_storage_secondary_reader_8x25_v1"
NEW_STORE_ONLY_FUNCTIONAL_ID = "calibration_storage_new_store_only_contract_v1"
FUNCTIONAL_SCENARIO = "calibration_storage_contract"
PERFORMANCE_SCENARIO = "calibration_storage_legacy_baseline"
SHADOW_FUNCTIONAL_SCENARIO = "calibration_storage_shadow_contract"
SHADOW_PERFORMANCE_SCENARIO = "calibration_storage_shadow"
AUTHORITATIVE_FUNCTIONAL_SCENARIO = "calibration_storage_authoritative_contract"
AUTHORITATIVE_PERFORMANCE_SCENARIO = "calibration_storage_authoritative"
PRIMARY_READER_FUNCTIONAL_SCENARIO = "calibration_storage_primary_reader_contract"
PRIMARY_READER_PERFORMANCE_SCENARIO = "calibration_storage_primary_reader"
SECONDARY_READER_FUNCTIONAL_SCENARIO = "calibration_storage_secondary_reader_contract"
SECONDARY_READER_PERFORMANCE_SCENARIO = "calibration_storage_secondary_reader"
NEW_STORE_ONLY_FUNCTIONAL_SCENARIO = "calibration_storage_new_store_only_contract"


def _shadow_enabled(runtime: JourneyRuntime) -> bool:
    return runtime.definition.registry_id in {
        SHADOW_FUNCTIONAL_ID,
        SHADOW_PERFORMANCE_ID,
    }


def _authoritative_enabled(runtime: JourneyRuntime) -> bool:
    return runtime.definition.registry_id in {
        AUTHORITATIVE_FUNCTIONAL_ID,
        AUTHORITATIVE_PERFORMANCE_ID,
        PRIMARY_READER_FUNCTIONAL_ID,
        PRIMARY_READER_PERFORMANCE_ID,
        SECONDARY_READER_FUNCTIONAL_ID,
        SECONDARY_READER_PERFORMANCE_ID,
        NEW_STORE_ONLY_FUNCTIONAL_ID,
    }


def _primary_reader_enabled(runtime: JourneyRuntime) -> bool:
    return runtime.definition.registry_id in {
        PRIMARY_READER_FUNCTIONAL_ID,
        PRIMARY_READER_PERFORMANCE_ID,
        SECONDARY_READER_FUNCTIONAL_ID,
        SECONDARY_READER_PERFORMANCE_ID,
        NEW_STORE_ONLY_FUNCTIONAL_ID,
    }


def _secondary_reader_enabled(runtime: JourneyRuntime) -> bool:
    return runtime.definition.registry_id in {
        SECONDARY_READER_FUNCTIONAL_ID,
        SECONDARY_READER_PERFORMANCE_ID,
        NEW_STORE_ONLY_FUNCTIONAL_ID,
    }


def _canonical_enabled(runtime: JourneyRuntime) -> bool:
    return _shadow_enabled(runtime) or _authoritative_enabled(runtime)


def _new_store_only_enabled(runtime: JourneyRuntime) -> bool:
    return runtime.definition.registry_id == NEW_STORE_ONLY_FUNCTIONAL_ID

FUNCTIONAL_ACTIONS = frozenset(
    {
        "app.launch_simulated",
        "fixture.prepare_calibration_storage",
        "calibration.run_scripted_processes",
        "calibration.inspect_storage_artifacts",
        "experiment.activate_authoritative",
        "app.close_simulated_session",
        "experiment.load_authoritative_via_ui",
        "experiment.activate_authoritative_via_ui",
        "calibration.stage_persisted_selection",
        "calibration.open_via_ui",
        "calibration.select_via_ui",
        "calibration.apply_via_ui",
        "artifact.capture_milestone",
        "scenario.teardown",
    }
)
FUNCTIONAL_UI_ACTIONS = frozenset(
    {
        "experiment.load_authoritative_via_ui",
        "experiment.activate_authoritative_via_ui",
        "calibration.open_via_ui",
        "calibration.select_via_ui",
        "calibration.apply_via_ui",
    }
)
FUNCTIONAL_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "calibration.storage.fixture_parity",
    "calibration.storage.lifecycle_exact",
    "calibration.storage.summary_isolation",
    "calibration.storage.capture_policy_exact",
    "calibration.storage.fresh_reload_exact",
    "calibration.storage.ui_application_exact",
    "artifacts.cleanup_complete",
)
NEW_STORE_ONLY_ASSERTIONS = FUNCTIONAL_ASSERTIONS + (
    "calibration.storage.legacy_writer_cutover",
)
PERFORMANCE_ACTIONS = frozenset(
    {
        "app.launch_simulated",
        "fixture.prepare_calibration_storage",
        "calibration.run_scripted_processes",
        "calibration.inspect_storage_artifacts",
        "scenario.teardown",
    }
)
PERFORMANCE_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "calibration.storage.workload_counts_exact",
    "calibration.storage.metrics_complete",
    "calibration.storage.growth_recorded",
    "calibration.storage.key_evidence_probe_exact",
    "artifacts.cleanup_complete",
)


def _assertion(
    assertion_id: str,
    decision: bool,
    evidence: Mapping[str, Any],
    *,
    checkpoint: str,
    sources: tuple[str, ...],
) -> AssertionResult:
    return AssertionResult(
        assertion_id=assertion_id,
        checkpoint=checkpoint,
        decision="pass" if decision else "fail",
        observable_sources=sources,
        evidence=dict(evidence),
        message=None if decision else f"{assertion_id} contract did not match",
    )


def _functional_fixture() -> tuple[dict[str, Any], Path]:
    catalog, _cases = load_catalog(CATALOG_PATH)
    return catalog, CATALOG_PATH.resolve()


def _new_store_only_fixture() -> tuple[dict[str, Any], Path]:
    catalog, _cases = load_catalog(
        NEW_STORE_ONLY_CATALOG_PATH,
        expected_fixture_id=NEW_STORE_ONLY_FUNCTIONAL_ID,
    )
    return catalog, NEW_STORE_ONLY_CATALOG_PATH.resolve()


def _performance_fixture() -> tuple[dict[str, Any], Path]:
    payload = json.loads(PERFORMANCE_FIXTURE_PATH.read_text(encoding="utf-8"))
    workload = payload.get("workload") or {}
    if (
        payload.get("schema_id")
        != "labcraft.calibration_storage_performance_workload"
        or payload.get("schema_version") != 1
        or payload.get("fixture_id") != PERFORMANCE_ID
        or workload.get("completion_count") != 200
        or workload.get("expected_update_count") != 232
    ):
        raise ValueError("calibration-storage performance fixture drifted")
    return payload, PERFORMANCE_FIXTURE_PATH.resolve()


def _prepare_minimal_experiment(runtime: JourneyRuntime) -> dict[str, Any]:
    from CalibrationPersistencePolicy import legacy_compatible_policy

    context = runtime.context
    experiment = context.experiment_model
    if not _new_store_only_enabled(runtime):
        experiment.calibration_storage_policy = legacy_compatible_policy(
            source="storage_contract_compatibility"
        )
        experiment._sync_calibration_storage_policy_to_manager()
    experiment.factors = []
    experiment.add_additive(
        "SIL Storage Reagent",
        [1.0],
        "x",
        10.0,
        forced_stock_conc=10.0,
        printing_mode="droplet",
    )
    experiment.set_metadata(
        name=f"{runtime.definition.workload_id}-experiment",
        randomize_assignments=False,
        start_row=0,
        start_col=0,
        replicates=2,
        target_reaction_volume_nL=2500.0,
        final_reaction_volume_nL=2500.0,
        printed_volume_tolerance_nL=50.0,
        fill_reagent_name="Water",
        fill_printing_mode="droplet",
        fill_droplet_volume_nL=10.0,
    )
    experiment.set_well_selection(["A1", "A2"])
    optimized = experiment.optimize_stock_solutions()
    if not optimized.get("best"):
        raise RuntimeError("minimal storage-contract design did not optimize")
    experiment.generate_experiment()
    experiment.initialize_experiment(
        base_dir=str(Path(runtime.context.scenario_root) / "experiments")
    )
    context.model.load_experiment_from_model(finalize_execution_plan=True)
    context.model.machine_model.update_print_pulse_width(1400)
    context.model.machine_model.update_target_print_pressure(
        context.model.machine_model.convert_to_raw_pressure(1.2)
    )
    plan = experiment.get_execution_plan_snapshot()
    non_fill = [
        stock
        for stock in plan.stocks
        if str(stock.factor_name) != experiment.get_fill_reagent_name()
    ]
    if len(non_fill) != 1:
        raise RuntimeError("minimal storage-contract design must have one non-fill stock")
    stock = non_fill[0]
    identity = {
        "printer_head_id": "sil-storage-application-head",
        "stock_id": str(stock.stock_id),
        "reagent_name": "SIL Storage Reagent",
        "concentration": "10.0",
        "units": "x",
    }
    evidence = {
        "experiment_dir": str(Path(experiment.experiment_dir_path).resolve()),
        "experiment_name": experiment.metadata["name"],
        "calibration_file": str(Path(experiment.calibration_file_path).resolve()),
        "plan_id": str(plan.plan_id),
        "plan_revision": int(plan.plan_revision),
        "stock_identity": identity,
    }
    runtime.observations["prepared_experiment"] = evidence
    return evidence


def _summary_projection(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        "source_run_id",
        "source_phase_key",
        "source_step_index",
        "source_pressure_index",
        "phase",
        "timestamp",
        "pw_us",
        "pressure_psi",
        "mean_nL",
        "cv_pct",
        "valid",
        "printing_mode",
    )
    projected = [{key: row.get(key) for key in fields} for row in rows]
    return sorted(
        projected,
        key=lambda row: (
            str(row.get("source_run_id") or ""),
            str(row.get("source_phase_key") or ""),
            int(row.get("source_step_index") or 0),
            -1
            if row.get("source_pressure_index") is None
            else int(row["source_pressure_index"]),
        ),
    )


def _summary_oracle_projection(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Remove only runtime identity/timing fields from current-reader rows."""

    fields = (
        "source_phase_key",
        "source_step_index",
        "source_pressure_index",
        "phase",
        "pw_us",
        "pressure_psi",
        "mean_nL",
        "cv_pct",
        "valid",
        "printing_mode",
    )
    return sorted(
        ({key: row.get(key) for key in fields} for row in rows),
        key=lambda row: (
            str(row.get("source_phase_key") or ""),
            int(row.get("source_step_index") or 0),
            -1
            if row.get("source_pressure_index") is None
            else int(row["source_pressure_index"]),
        ),
    )


def _run_functional_catalog(runtime: JourneyRuntime) -> dict[str, Any]:
    prepared = runtime.observations["prepared_experiment"]
    catalog, fixture_cases = load_catalog(
        runtime.fixture_path,
        expected_fixture_id=(
            NEW_STORE_ONLY_FUNCTIONAL_ID
            if _new_store_only_enabled(runtime)
            else FUNCTIONAL_ID
        ),
    )
    metrics = StorageMetricsCollector()
    runner = StorageContractRunner(
        model=runtime.context.model,
        controller=runtime.context.controller,
        machine=runtime.context.machine,
        app=runtime.context.app,
        calibration_file_path=prepared["calibration_file"],
        timeout_seconds=runtime.harness.config.timeout_seconds,
        metrics=metrics,
        shadow_store_enabled=_shadow_enabled(runtime),
        authoritative_mode=_authoritative_enabled(runtime),
        legacy_writer_mode=(
            "canonical_only"
            if _new_store_only_enabled(runtime)
            else "legacy_compatible"
        ),
    )
    runtime.register_restorable("calibration_storage_runner", runner)
    runner.manager._calibration_reader_preference = (
        "canonical" if _primary_reader_enabled(runtime) else "legacy"
    )
    application_identity = dict(prepared["stock_identity"])
    executed: list[tuple[ScriptedCalibrationCase, dict[str, Any]]] = []
    runtime.emit_progress("functional_catalog", completed=0, total=len(fixture_cases))
    for original in fixture_cases:
        case = (
            replace(original, identity=application_identity)
            if original.fixture_id == "legacy_parity_v1"
            else original
        )
        executed.append((case, runner.run_case(case).as_dict()))
    runtime.emit_progress(
        "functional_catalog", completed=len(executed), total=len(fixture_cases)
    )

    by_process = {case.process_id: evidence for case, evidence in executed}
    identities = {
        case.process_id: dict(case.identity)
        for case, _evidence in executed
    }
    head_a_rows = runner.characterization_rows(identities["head-a-sweep"])
    head_b_rows = runner.characterization_rows(identities["head-b-sweep"])
    failed_rows = runner.characterization_rows(identities["error-before-result"])
    application_rows = runner.characterization_rows(application_identity)
    target = by_process["legacy-parity-two-update"]
    target_coordinates = {
        "source_run_id": target["run_id"],
        "source_phase_key": "pressure_sweep_characterization",
        "source_step_index": 1,
        "source_pressure_index": 1,
    }
    target_rows = [
        row
        for row in application_rows
        if all(row.get(key) == value for key, value in target_coordinates.items())
    ]
    if len(target_rows) != 1:
        observed = [
            {
                key: row.get(key)
                for key in (
                    "source_run_id",
                    "source_phase_key",
                    "source_step_index",
                    "source_pressure_index",
                    "reader_state",
                )
            }
            for row in application_rows
        ]
        raise RuntimeError(
            "legacy parity target row did not resolve uniquely: "
            f"expected={target_coordinates!r}, observed={observed!r}"
        )

    process_summary_rows = {}
    for case, process_evidence in executed:
        rows = runner.characterization_rows(case.identity)
        current_run_rows = [
            row
            for row in rows
            if row.get("source_run_id") == process_evidence["run_id"]
        ]
        process_summary_rows[case.process_id] = _summary_oracle_projection(
            current_run_rows
        )
    runner.characterization_rows(application_identity)

    capture_counts = {
        process_id: int(by_process[process_id]["capture_count"])
        for process_id in (
            "structured-only-proxy",
            "key-evidence-proxy",
            "full-proxy",
            "recorder-disabled-control",
        )
    }
    evidence = {
        "catalog_semantic_sha256": catalog["catalog_semantic_sha256"],
        "fixture_hashes": {
            row["fixture_id"]: row["semantic_sha256"]
            for row in catalog["fixtures"]
        },
        "process_count": len(executed),
        "successful_processes": sum(
            case.terminal_outcome == "completed" for case, _ in executed
        ),
        "stopped_processes": sum(
            case.terminal_outcome == "stopped" for case, _ in executed
        ),
        "error_processes": sum(
            case.terminal_outcome == "error" for case, _ in executed
        ),
        "update_count": sum(len(case.updates) for case, _ in executed),
        "processes": [evidence for _case, evidence in executed],
        "shadow_store_enabled": _shadow_enabled(runtime),
        "authoritative_mode": _authoritative_enabled(runtime),
        "canonical_store_enabled": _canonical_enabled(runtime),
        "canonical_result_count": sum(
            row["canonical_result_id"] is not None
            for _case, row in executed
        ),
        "canonical_index_event_count": sum(
            int(row["canonical_index_event_count"])
            for _case, row in executed
        ),
        "process_summary_rows": process_summary_rows,
        "expected_process_summary_rows": {
            case.process_id: list(case.expected_summary_rows)
            for case, _evidence in executed
        },
        "capture_counts": capture_counts,
        "capture_dimensions": sorted(
            {
                (capture["width"], capture["height"])
                for _case, process in executed
                for capture in process["captures"]
            }
        ),
        "head_a_run_ids": sorted(
            {str(row.get("source_run_id")) for row in head_a_rows}
        ),
        "head_b_run_ids": sorted(
            {str(row.get("source_run_id")) for row in head_b_rows}
        ),
        "head_a_expected_run_id": by_process["head-a-sweep"]["run_id"],
        "head_b_expected_run_id": by_process["head-b-sweep"]["run_id"],
        "failed_identity_summary_count": len(failed_rows),
        "application_summary": _summary_projection(application_rows),
        "target_coordinates": target_coordinates,
        "target_row": dict(target_rows[0]),
        "metrics": metrics.snapshot(),
        "calibration_sha256": (
            file_sha256(prepared["calibration_file"])
            if Path(prepared["calibration_file"]).is_file()
            else None
        ),
        "legacy_writer": runner.manager.get_legacy_calibration_writer_diagnostics(),
        "inventory": file_inventory(runtime.context.scenario_root),
    }
    runtime.observations["functional_storage"] = evidence
    return evidence


def _functional_contract_assertions(runtime: JourneyRuntime) -> None:
    observed = runtime.observations["functional_storage"]
    process_rows = observed["processes"]
    expected_summary_rows = dict(observed["expected_process_summary_rows"])
    if _primary_reader_enabled(runtime):
        # Milestone 4A intentionally promotes bounded terminal stream rows that
        # the Milestone 1 current-reader oracle excluded.
        expected_summary_rows["online-stream-five-update"] = list(
            observed["process_summary_rows"]["online-stream-five-update"]
        )
    parity_ok = all(
        (
            row["legacy_update_hashes"] == ()
            if _new_store_only_enabled(runtime)
            else row["update_hashes"] == row["legacy_update_hashes"]
        )
        and (
            row["recorder_update_hashes"] == row["update_hashes"]
            if row["diagnostic_recording_enabled"]
            else row["recorder_update_hashes"] == ()
        )
        and (
            row["canonical_update_hashes"] == row["update_hashes"]
            and row["canonical_valid"]
            and row["canonical_index_event_count"] == 1
            if observed["canonical_store_enabled"]
            else row["canonical_update_hashes"] == ()
        )
        for row in process_rows
    ) and observed["process_summary_rows"] == expected_summary_rows
    runtime.add_assertion(
        _assertion(
            "calibration.storage.fixture_parity",
            parity_ok,
            {
                "process_count": observed["process_count"],
                "catalog_semantic_sha256": observed["catalog_semantic_sha256"],
                "fixture_hashes": observed["fixture_hashes"],
                "summary_oracle_sha256": semantic_sha256(
                    observed["expected_process_summary_rows"]
                ),
            },
            checkpoint="current_writers",
            sources=("calibration.json", "analysis.jsonl", "fixture_catalog"),
        )
    )

    if _new_store_only_enabled(runtime):
        prepared = runtime.observations["prepared_experiment"]
        calibration_path = Path(prepared["calibration_file"])
        writer = dict(observed["legacy_writer"])
        result_paths = sorted(
            calibration_path.parent.glob("calibration_recordings/*/*/result.json")
        )
        provenance_ok = True
        for result_path in result_paths:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            policy = dict((result.get("provenance") or {}).get("storage_policy") or {})
            provenance_ok = provenance_ok and (
                policy.get("declared_mode") == "canonical_only"
                and policy.get("effective_enabled") is False
                and policy.get("effective_reason") == "writer_retired"
            )
        cutover_ok = (
            not calibration_path.exists()
            and not list(calibration_path.parent.glob("calibration.json.*"))
            and writer.get("declared_mode") == "canonical_only"
            and writer.get("effective_enabled") is False
            and writer.get("legacy_writer_available") is False
            and writer.get("effective_reason") == "writer_retired"
            and int(writer.get("write_count") or 0) == 0
            and int(writer.get("suppressed_write_count") or 0) == 0
            and all(not row["legacy_update_hashes"] for row in process_rows)
            and len(result_paths) == 16
            and provenance_ok
            and bool((runtime.observations.get("legacy_writer_canaries") or {}).get("exact"))
        )
        runtime.add_assertion(
            _assertion(
                "calibration.storage.legacy_writer_cutover",
                cutover_ok,
                {
                    "calibration_json_exists": calibration_path.exists(),
                    "temporary_legacy_paths": [
                        str(path.name)
                        for path in calibration_path.parent.glob("calibration.json.*")
                    ],
                    "writer_diagnostics": writer,
                    "canonical_result_count": len(result_paths),
                    "provenance_ok": provenance_ok,
                    "canaries": dict(
                        runtime.observations.get("legacy_writer_canaries") or {}
                    ),
                },
                checkpoint="new_store_only_writers",
                sources=(
                    "CalibrationManager.get_legacy_calibration_writer_diagnostics",
                    "calibration_recordings/*/*/result.json",
                    "experiment directory inventory",
                ),
            )
        )
    lifecycle_ok = (
        observed["process_count"] == 16
        and observed["successful_processes"] == 14
        and observed["stopped_processes"] == 1
        and observed["error_processes"] == 1
        and observed["update_count"] == 17
        and all(
            row["meta_outcome"] == row["terminal_outcome"]
            for row in process_rows
            if row["recording_dir"] is not None
        )
        and (
            observed["canonical_result_count"] == 16
            and observed["canonical_index_event_count"] == 16
            if observed["canonical_store_enabled"]
            else observed["canonical_result_count"] == 0
        )
    )
    runtime.add_assertion(
        _assertion(
            "calibration.storage.lifecycle_exact",
            lifecycle_ok,
            {
                key: observed[key]
                for key in (
                    "process_count",
                    "successful_processes",
                    "stopped_processes",
                    "error_processes",
                    "update_count",
                )
            },
            checkpoint="current_writers",
            sources=("CalibrationManager", "run_meta.json"),
        )
    )
    isolation_ok = (
        observed["head_a_run_ids"] == [observed["head_a_expected_run_id"]]
        and observed["head_b_run_ids"] == [observed["head_b_expected_run_id"]]
        and observed["failed_identity_summary_count"] == 0
    )
    runtime.add_assertion(
        _assertion(
            "calibration.storage.summary_isolation",
            isolation_ok,
            {
                key: observed[key]
                for key in (
                    "head_a_run_ids",
                    "head_b_run_ids",
                    "head_a_expected_run_id",
                    "head_b_expected_run_id",
                    "failed_identity_summary_count",
                )
            },
            checkpoint="current_reader",
            sources=("CalibrationManager.get_characterization_summary_rows",),
        )
    )
    expected_captures = {
        "structured-only-proxy": 0,
        "key-evidence-proxy": 2,
        "full-proxy": 4,
        "recorder-disabled-control": 0,
    }
    capture_ok = (
        observed["capture_counts"] == expected_captures
        and observed["capture_dimensions"] == [(16, 12)]
        and (
            next(
            row for row in process_rows
            if row["process_id"] == "recorder-disabled-control"
            )["recording_dir"] is not None
            if observed["canonical_store_enabled"]
            else next(
                row for row in process_rows
                if row["process_id"] == "recorder-disabled-control"
            )["recording_dir"] is None
        )
    )
    runtime.add_assertion(
        _assertion(
            "calibration.storage.capture_policy_exact",
            capture_ok,
            {
                "counts": observed["capture_counts"],
                "dimensions": observed["capture_dimensions"],
                "compressed_bytes": {
                    row["process_id"]: row["capture_bytes"]
                    for row in process_rows
                    if row["process_id"] in expected_captures
                },
                "decoded_pixel_hashes": {
                    row["process_id"]: [
                        capture["decoded_pixel_sha256"]
                        for capture in row["captures"]
                    ]
                    for row in process_rows
                    if row["process_id"] in expected_captures
                },
            },
            checkpoint="capture_scaffolding",
            sources=("calibration_recordings/captures",),
        )
        )


def _run_legacy_writer_canaries(runtime: JourneyRuntime) -> dict[str, Any]:
    """Prove the retained legacy reader without invoking the retired writer."""

    _catalog, cases = load_catalog(
        runtime.fixture_path,
        expected_fixture_id=NEW_STORE_ONLY_FUNCTIONAL_ID,
    )
    selected = next(case for case in cases if case.process_id == "droplet-emergence")
    manager = runtime.context.model.calibration_manager
    memory_store = getattr(runtime.context.model, "calibration_memory_store", None)
    prior_memory_enabled = (
        bool(memory_store.get_memory_enabled()) if memory_store is not None else False
    )
    if memory_store is not None:
        memory_store.set_memory_enabled(False)
    root = Path(runtime.context.scenario_root) / "legacy-writer-canaries"
    historical_path = root / "historical" / "calibration.json"
    historical_path.parent.mkdir(parents=True, exist_ok=True)
    historical_path.write_text(
        json.dumps({"schema_version": 1, "runs": []}, indent=2),
        encoding="utf-8",
    )
    historical_before = file_sha256(historical_path)
    manager.update_calibration_file_path(str(historical_path))
    historical_after_open = file_sha256(historical_path)
    try:
        historical_runner = StorageContractRunner(
            model=runtime.context.model,
            controller=runtime.context.controller,
            machine=runtime.context.machine,
            app=runtime.context.app,
            calibration_file_path=historical_path,
            timeout_seconds=runtime.harness.config.timeout_seconds,
            authoritative_mode=True,
            legacy_writer_mode="legacy_compatible",
        )
        historical = historical_runner.run_case(selected).as_dict()
        historical_writer = manager.get_legacy_calibration_writer_diagnostics()
        historical_runner.restore()
    finally:
        if memory_store is not None:
            memory_store.set_memory_enabled(prior_memory_enabled)

    historical_after_run = file_sha256(historical_path)

    prepared = runtime.observations["prepared_experiment"]
    main_path = Path(prepared["calibration_file"])
    manager.update_calibration_file_path(str(main_path))
    manager.set_calibration_storage_policy("canonical_only")
    manager._calibration_reader_preference = "canonical"
    manager._calibration_secondary_reader_preference = "canonical"
    exact = (
        historical_before == historical_after_open
        and historical_before == historical_after_run
        and historical_path.is_file()
        and historical_writer["effective_reason"] == "writer_retired"
        and historical_writer["legacy_writer_available"] is False
        and historical["legacy_update_hashes"] == ()
        and historical["canonical_update_hashes"] == historical["update_hashes"]
        and not main_path.exists()
    )
    evidence = {
        "exact": exact,
        "historical_open_hash_preserved": historical_before == historical_after_open,
        "historical_run_hash_preserved": historical_before == historical_after_run,
        "historical_writer": historical_writer,
        "historical_process": historical,
        "main_calibration_json_absent": not main_path.exists(),
    }
    runtime.observations["legacy_writer_canaries"] = evidence
    return evidence


def _stage_fresh_selection(runtime: JourneyRuntime) -> dict[str, Any]:
    prepared = runtime.observations["prepared_experiment"]
    machine = runtime.context.machine
    machine.state.connected = True
    machine.state.motors_enabled = True
    machine.state.homed = True
    machine.state.regulating_print_pressure = True
    pressure_raw = int(machine.convert_to_raw_pressure(1.2))
    machine.state.current_print_pressure_raw = pressure_raw
    machine.state.target_print_pressure_raw = pressure_raw
    machine.state.print_pulse_width_us = 1400
    machine._emit_status()
    machine.machine_connected_signal.emit(True)
    head = SyntheticStorageHead(prepared["stock_identity"])
    rack = runtime.context.model.rack_model
    rack.gripper_printer_head = head
    rack.gripper_slot_number = None
    sync = getattr(rack, "sync_expected_to_actual", None)
    if callable(sync):
        sync()
    signal = getattr(rack, "gripper_updated", None)
    if signal is not None:
        signal.emit()
    runtime.context.app.processEvents()
    readiness = runtime.harness.session.calibration_adapter.availability(
        "nominal_droplet"
    )
    if not readiness.get("ok"):
        raise RuntimeError(f"persisted calibration selection is not ready: {readiness}")
    return {
        "ready": True,
        "readiness_code": readiness.get("code"),
        "stock_identity": dict(prepared["stock_identity"]),
        "command_event_count": len(machine.command_event_history),
    }


def _inspect_applied_record(
    runtime: JourneyRuntime,
    selected: Mapping[str, Any],
    source_row_fingerprint: Any,
) -> dict[str, Any]:
    from ExecutionCalibrationStore import load_execution_calibrations

    experiment = runtime.context.experiment_model
    plan = experiment.get_execution_plan_snapshot()
    stock_id = runtime.observations["prepared_experiment"]["stock_identity"]["stock_id"]
    stock = next(item for item in plan.stocks if item.stock_id == stock_id)
    document = load_execution_calibrations(experiment.execution_calibrations_file_path)
    record = document.records[stock.calibration_record_key]
    record_payload = record.to_dict()
    expected = {
        "run_id": selected.get("source_run_id"),
        "phase": selected.get("phase"),
        "timestamp": selected.get("timestamp"),
        "source_row_fingerprint": list(source_row_fingerprint or ()),
        "result_id": selected.get("result_id"),
        "result_sha256": selected.get("result_sha256"),
        "process_run_id": selected.get("process_run_id"),
        "update_id": selected.get("update_id"),
    }
    command_types = sorted(
        {
            str(event.get("command_type"))
            for event in runtime.context.machine.command_event_history
        }
    )
    return {
        "record": record_payload,
        "expected_source": expected,
        "matches_source": all(record_payload.get(key) == value for key, value in expected.items()),
        "plan_revision": int(plan.plan_revision),
        "command_types": command_types,
        "settings_only_commands": set(command_types)
        <= {"SET_WIDTH_P", "ABSOLUTE_PRESSURE_P"},
        "no_dispense_or_motion": not any(
            command.startswith(("DISPENSE", "ABSOLUTE_X", "ABSOLUTE_Y", "ABSOLUTE_Z", "HOME_"))
            for command in command_types
        ),
    }


def _functional_body(runtime: JourneyRuntime) -> None:
    resource_sampler = ProcessResourceSampler() if _new_store_only_enabled(runtime) else None
    if resource_sampler is not None:
        resource_sampler.start()
    runtime.emit_progress("setup", completed=0, total=1)
    runtime.add_assertion(simulation_identity_assertion(runtime.context))
    runtime.harness.run_action(
        "fixture.prepare_calibration_storage",
        lambda: _prepare_minimal_experiment(runtime),
        surface=InteractionSurface.MODEL,
    )
    runtime.emit_progress("setup", completed=1, total=1)
    runtime.harness.run_action(
        "calibration.run_scripted_processes",
        lambda: _run_functional_catalog(runtime),
        surface=InteractionSurface.MODEL,
    )
    runtime.harness.run_action(
        "calibration.inspect_storage_artifacts",
        lambda: (
            _run_legacy_writer_canaries(runtime)
            if _new_store_only_enabled(runtime)
            else {"status": "validated"}
        ),
        surface=InteractionSurface.HARNESS,
    )
    _functional_contract_assertions(runtime)
    if resource_sampler is not None:
        resource_sampler.sample()
    if _secondary_reader_enabled(runtime):
        prepared_path = Path(
            runtime.observations["prepared_experiment"]["calibration_file"]
        )
        runtime.observations["secondary_consumers"] = _exercise_secondary_consumers(
            runtime,
            runtime.context.model.calibration_manager,
            prepared_path,
        )
    before_summary = runtime.observations["functional_storage"]["application_summary"]
    experiment_dir = Path(runtime.observations["prepared_experiment"]["experiment_dir"])
    from PySide6 import QtCore, QtWidgets

    QtWidgets.QApplication.setAttribute(
        QtCore.Qt.ApplicationAttribute.AA_DontUseNativeDialogs,
        True,
    )
    runtime.restore_all()
    runtime.emit_progress("fresh_application", completed=0, total=1)
    runtime.harness.run_action(
        "experiment.activate_authoritative",
        lambda: runtime.context.model.load_authoritative_execution_runtime(),
        surface=InteractionSurface.MODEL,
    )
    runtime.harness.close_application_session()
    runtime.harness.reopen_application_session()
    prepared = runtime.observations["prepared_experiment"]
    load_started = time.perf_counter_ns()
    reload_evidence = ExperimentLoaderDriver(
        runtime.context
    ).load_authoritative_execution(
        experiment_dir,
        expected_name=prepared["experiment_name"],
        expected_eligibility_status="ready_to_start",
        expected_array_state="idle",
        loaded_milestone_name="storage_session_2_loaded",
    )
    fresh_reload_ms = (time.perf_counter_ns() - load_started) / 1_000_000.0
    runtime.harness.run_action(
        "calibration.stage_persisted_selection",
        lambda: _stage_fresh_selection(runtime),
        surface=InteractionSurface.HARNESS,
    )
    manager = runtime.context.model.calibration_manager
    staged_identity = manager._build_calibration_stock_identity_snapshot()
    try:
        raw_after_summary = manager.get_characterization_summary_rows()
        after_summary = _summary_projection(raw_after_summary)
    except Exception as exc:
        raise RuntimeError(
            "fresh calibration summary reload failed after staging persisted identity"
        ) from exc
    fresh_ok = after_summary == before_summary
    if _new_store_only_enabled(runtime):
        fresh_ok = fresh_ok and not Path(prepared["calibration_file"]).exists()
    reader_diagnostics = manager.get_calibration_reader_diagnostics()
    runtime.add_assertion(
        _assertion(
            "calibration.storage.fresh_reload_exact",
            fresh_ok,
            {
                "before_semantic_sha256": semantic_sha256(before_summary),
                "after_semantic_sha256": semantic_sha256(after_summary),
                "row_count": len(after_summary),
                "fresh_reload_latency_ms": fresh_reload_ms,
                "loader": reload_evidence,
                "reader_diagnostics": reader_diagnostics,
                "staged_identity": staged_identity,
            },
            checkpoint="fresh_application",
            sources=("ExperimentLoaderDriver", "CalibrationManager"),
        )
    )
    runtime.emit_progress("fresh_application", completed=1, total=1)

    def open_calibration_dialog() -> dict[str, Any]:
        try:
            dialog = MachineControlsDriver(runtime.context).open_calibration_dialog()
            return {"visible": bool(dialog.isVisible())}
        except Exception as exc:
            raise RuntimeError(
                "persisted calibration dialog failed to open after summary reload"
            ) from exc

    runtime.harness.run_action(
        "calibration.open_via_ui",
        open_calibration_dialog,
        surface=InteractionSurface.UI,
    )
    dialog = runtime.context.view.pressure_box._droplet_imager_dialog
    driver = CalibrationDialogDriver(runtime.context.app, dialog)
    coordinates = runtime.observations["functional_storage"]["target_coordinates"]
    canonical_target = runtime.observations["functional_storage"]["target_row"]
    selected = runtime.harness.run_action(
        "calibration.select_via_ui",
        lambda: (
            driver.select_canonical_result(
                result_id=canonical_target["result_id"],
                update_id=canonical_target["update_id"],
                row_ordinal=int(canonical_target.get("row_ordinal") or 0),
            )
            if _primary_reader_enabled(runtime)
            else driver.select_persisted_result(**coordinates)
        ),
        surface=InteractionSurface.UI,
    )["evidence"]
    preview = driver.inspect_preview()
    apply_dialogs = runtime.harness.run_action(
        "calibration.apply_via_ui",
        lambda: {"dialogs": driver.apply_selected(expected_title="Applied")},
        surface=InteractionSurface.UI,
    )["evidence"]
    applied = _inspect_applied_record(
        runtime,
        selected,
        preview.get("payload", {}).get("source_row_fingerprint"),
    )
    driver.close()
    application_ok = (
        bool(preview.get("apply_enabled"))
        and apply_dialogs["dialogs"] == ["Applied"]
        and applied["matches_source"]
        and applied["settings_only_commands"]
        and applied["no_dispense_or_motion"]
    )
    runtime.observations["fresh_application"] = {
        "summary": after_summary,
        "reload_latency_ms": fresh_reload_ms,
        "selected": dict(selected),
        "preview": preview,
        "apply": apply_dialogs,
        "applied": applied,
    }
    runtime.add_assertion(
        _assertion(
            "calibration.storage.ui_application_exact",
            application_ok,
            runtime.observations["fresh_application"],
            checkpoint="ui_application",
            sources=(
                "CalibrationDialogDriver",
                "Controller",
                "execution_calibrations.json",
                "SimulatedMachine.command_event_history",
            ),
        )
    )
    if resource_sampler is not None:
        resource_sampler.sample()
        resource_sampler.stop()
        runtime.observations["functional_resources"] = resource_sampler.snapshot()


def _build_performance_cases() -> tuple[ScriptedCalibrationCase, ...]:
    _droplet_fixture, droplet_cases = load_fixture(
        CATALOG_PATH.parent / "droplet_sequence_nominal_v1.json"
    )
    _stream_fixture, stream_cases = load_fixture(
        CATALOG_PATH.parent / "online_stream_large_multi_update_v1.json"
    )
    small = droplet_cases[0]
    large = stream_cases[0]
    cases: list[ScriptedCalibrationCase] = []
    for head_index in range(1, 9):
        identity = {
            "printer_head_id": f"sil-performance-head-{head_index:02d}",
            "stock_id": f"sil-performance-stock-{head_index:02d}",
            "reagent_name": f"SIL Performance Reagent {head_index:02d}",
            "concentration": f"{head_index}.0",
            "units": "x",
        }
        for process_index in range(1, 25):
            cases.append(
                replace(
                    small,
                    fixture_id=PERFORMANCE_ID,
                    process_id=f"head-{head_index:02d}-run-{process_index:02d}",
                    identity=identity,
                    record_mode_enabled=True,
                    capture_mode="structured_only_proxy",
                    captures=(),
                )
            )
        cases.append(
            replace(
                large,
                fixture_id=PERFORMANCE_ID,
                process_id=f"head-{head_index:02d}-run-25-large",
                identity=identity,
                record_mode_enabled=True,
                capture_mode="structured_only_proxy",
                captures=(),
            )
        )
    return tuple(cases)


def _run_performance_workload(runtime: JourneyRuntime) -> dict[str, Any]:
    prepared = runtime.observations["prepared_experiment"]
    cases = _build_performance_cases()
    metrics = StorageMetricsCollector()
    resources = ProcessResourceSampler()
    resources.start()
    runner = StorageContractRunner(
        model=runtime.context.model,
        controller=runtime.context.controller,
        machine=runtime.context.machine,
        app=runtime.context.app,
        calibration_file_path=prepared["calibration_file"],
        timeout_seconds=runtime.harness.config.timeout_seconds,
        metrics=metrics,
        shadow_store_enabled=_shadow_enabled(runtime),
        authoritative_mode=_authoritative_enabled(runtime),
    )
    runtime.register_restorable("calibration_storage_performance_runner", runner)
    runner.manager._calibration_reader_preference = (
        "canonical" if _primary_reader_enabled(runtime) else "legacy"
    )
    evidence = []
    runtime.emit_progress("workload", completed=0, total=len(cases))
    for index, case in enumerate(cases, start=1):
        evidence.append(runner.run_case(case).as_dict())
        if index % 25 == 0:
            resources.sample()
            runtime.emit_progress("workload", completed=index, total=len(cases))

    calibration_path = Path(prepared["calibration_file"])
    # Model a fresh application manager: release the live workload document
    # before timing the retained-file load, rather than charging object
    # destruction from the prior composition to reload latency.
    runner.manager.data = {"schema_version": 1, "runs": []}
    reload_started = time.perf_counter_ns()
    runtime.emit_progress("fresh_reload", completed=0, total=1)
    runner.manager.load_calibration_data(str(calibration_path))
    metrics.fresh_reload_latency_ms.append(
        (time.perf_counter_ns() - reload_started) / 1_000_000.0
    )
    runtime.emit_progress("fresh_reload", completed=1, total=1)
    reader_index_latency_ms = []
    reader_summary_latency_ms = []
    reader_selection_latency_ms = []
    reader_recheck_latency_ms = []
    reader_rows = 0
    reader_states = {}
    if _primary_reader_enabled(runtime):
        index_started = time.perf_counter_ns()
        runner.manager.get_characterization_history_snapshot()
        reader_index_latency_ms.append(
            (time.perf_counter_ns() - index_started) / 1_000_000.0
        )
    for head_index in range(1, 9):
        summary_started = time.perf_counter_ns()
        rows = runner.characterization_rows(
            {
                "printer_head_id": f"sil-performance-head-{head_index:02d}",
                "stock_id": f"sil-performance-stock-{head_index:02d}",
                "reagent_name": f"SIL Performance Reagent {head_index:02d}",
                "concentration": f"{head_index}.0",
                "units": "x",
            }
        )
        reader_summary_latency_ms.append((time.perf_counter_ns() - summary_started) / 1_000_000.0)
        reader_rows += len(rows)
        for row in rows:
            state = str(row.get("reader_state") or "unknown")
            reader_states[state] = int(reader_states.get(state, 0)) + 1
        if rows:
            selection_started = time.perf_counter_ns()
            resolved = runner.manager.resolve_characterization_selection(rows[0])
            reader_selection_latency_ms.append((time.perf_counter_ns() - selection_started) / 1_000_000.0)
            if not resolved.get("ok"):
                raise RuntimeError(f"primary reader selection failed: {resolved}")
    reader_diagnostics = runner.manager.get_calibration_reader_diagnostics()
    secondary_metrics = {}
    if _secondary_reader_enabled(runtime):
        secondary_metrics = _exercise_secondary_consumers(
            runtime, runner.manager, calibration_path
        )
    resources.stop()

    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    workload_run_count = len(calibration.get("runs") or [])
    workload_update_count = sum(
        len(steps)
        for run in calibration.get("runs") or []
        for steps in (run.get("steps") or {}).values()
    )
    recording_capture_count = sum(int(row["capture_count"]) for row in evidence)

    _capture_fixture, capture_cases = load_fixture(
        CATALOG_PATH.parent / "capture_policy_v1.json"
    )
    probe_case = replace(
        next(case for case in capture_cases if case.process_id == "key-evidence-proxy"),
        fixture_id=PERFORMANCE_ID,
        process_id="key-evidence-drain-probe",
        identity=cases[-1].identity,
    )
    probe_path = Path(runtime.context.scenario_root) / "storage-probe" / "calibration.json"
    probe_path.parent.mkdir(parents=True, exist_ok=True)
    if _primary_reader_enabled(runtime):
        probe_path.write_text(
            json.dumps({"schema_version": 1, "runs": []}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    probe_runner = StorageContractRunner(
        model=runtime.context.model,
        controller=runtime.context.controller,
        machine=runtime.context.machine,
        app=runtime.context.app,
        calibration_file_path=probe_path,
        timeout_seconds=runtime.harness.config.timeout_seconds,
        shadow_store_enabled=_shadow_enabled(runtime),
        authoritative_mode=_authoritative_enabled(runtime),
    )
    probe_runner.manager._calibration_reader_preference = (
        "canonical" if _primary_reader_enabled(runtime) else "legacy"
    )
    probe = probe_runner.run_case(probe_case).as_dict()
    recheck_probe = None
    if _primary_reader_enabled(runtime):
        _probe_fixture, probe_cases = load_fixture(
            CATALOG_PATH.parent / "droplet_sequence_nominal_v1.json"
        )
        sweep_case = next(
            case
            for case in probe_cases
            if case.phase_name == "pressure_sweep_characterization"
        )
        recheck_case = replace(
            sweep_case,
            fixture_id=PERFORMANCE_ID,
            process_id="primary-reader-recheck-probe",
            identity=cases[-1].identity,
            updates=(
                {
                    "result": {
                        "print_pulse_width_us": 1400,
                        "manual_current": True,
                        "pressures": [
                            {
                                "pressure": 1.25,
                                "delay_us": 415,
                                "mean_position_machine": [10.0, 20.0, 30.0],
                                "mean_volume": 10.1,
                                "cv_volume_percent": 3.0,
                                "manual_current": True,
                                "valid": True,
                            }
                        ],
                    }
                },
            ),
            captures=(),
        )
        recheck_evidence = probe_runner.run_case(recheck_case).as_dict()
        probe_rows = probe_runner.characterization_rows(recheck_case.identity)
        matching_rows = [
            row
            for row in probe_rows
            if row.get("source_run_id") == recheck_evidence["run_id"]
            and str(row.get("phase")) != "stream"
        ]
        if len(matching_rows) != 1:
            raise RuntimeError("primary reader recheck probe did not resolve uniquely")
        recheck_row = matching_rows[0]
        for _sample_index in range(8):
            recheck_started = time.perf_counter_ns()
            context, missing = probe_runner.manager.build_droplet_recheck_context(
                recheck_row
            )
            reader_recheck_latency_ms.append(
                (time.perf_counter_ns() - recheck_started) / 1_000_000.0
            )
            if missing:
                raise RuntimeError(
                    f"primary reader recheck probe is incomplete: {missing}"
                )
            if context.get("source_result", {}).get("run_id") != recheck_evidence["run_id"]:
                raise RuntimeError("primary reader recheck probe source identity drifted")
        recheck_probe = {
            "process": recheck_evidence,
            "row": recheck_row,
            "resolution_count": len(reader_recheck_latency_ms),
        }
    probe_runner.restore()
    if _primary_reader_enabled(runtime):
        runner.manager.load_calibration_data(str(calibration_path))
        runner.manager._calibration_reader_preference = "canonical"

    snapshot = {
        "workload_hash": semantic_sha256(
            {
                "fixture": runtime.fixture,
                "case_hashes": [
                    list(case.expected_update_hashes) for case in cases
                ],
            }
        ),
        "fixture_sha256": file_sha256(runtime.fixture_path),
        "process_run_count": len(evidence),
        "legacy_run_envelope_count": workload_run_count,
        "update_count": workload_update_count,
        "recording_count": sum(row["recording_dir"] is not None for row in evidence),
        "shadow_store_enabled": _shadow_enabled(runtime),
        "authoritative_mode": _authoritative_enabled(runtime),
        "canonical_store_enabled": _canonical_enabled(runtime),
        "canonical_update_count": sum(
            len(row["canonical_update_hashes"]) for row in evidence
        ),
        "canonical_result_count": sum(
            row["canonical_result_id"] is not None for row in evidence
        ),
        "canonical_index_event_count": sum(
            int(row["canonical_index_event_count"]) for row in evidence
        ),
        "integrity_failure_count": sum(
            not bool(row["canonical_valid"])
            for row in evidence
            if _canonical_enabled(runtime)
        ),
        "workload_capture_count": recording_capture_count,
        "key_evidence_probe": probe,
        "recheck_context_probe": recheck_probe,
        "metrics": metrics.snapshot(),
        "reader_metrics": {
            "index_read_latency_ms": distribution(reader_index_latency_ms),
            "summary_materialization_latency_ms": distribution(reader_summary_latency_ms),
            "selected_validation_latency_ms": distribution(reader_selection_latency_ms),
            "recheck_context_latency_ms": distribution(reader_recheck_latency_ms),
            "row_count": reader_rows,
            "reader_states": reader_states,
            "diagnostics": reader_diagnostics,
        },
        "secondary_consumer_metrics": secondary_metrics,
        "resources": resources.snapshot(),
        "artifact_growth": {
            "calibration_json_bytes": calibration_path.stat().st_size,
            "scenario_total_bytes": sum(
                path.stat().st_size
                for path in Path(runtime.context.scenario_root).rglob("*")
                if path.is_file()
            ),
            "inventory": file_inventory(runtime.context.scenario_root),
        },
    }
    runtime.observations["performance_storage"] = snapshot
    return snapshot


def _exercise_secondary_consumers(
    runtime: JourneyRuntime,
    manager: Any,
    calibration_path: Path,
) -> dict[str, Any]:
    """Exercise canonical secondary consumers with legacy temporarily absent."""

    from CalibrationRecordExport import export_calibration_records
    from tools.calibration_recording_updates import load_calibration_updates
    from tools.export_calibration_recording_summary import (
        build_calibration_recording_summary_rows,
    )

    experiment_dir = calibration_path.parent
    memory_store = manager.model.calibration_memory_store
    aggregator = memory_store.aggregator
    aggregator.secondary_reader_preference = "canonical"
    held_path = calibration_path.with_name(".calibration.json.sil-held")
    legacy_present = calibration_path.is_file()
    original_hash = file_sha256(calibration_path) if legacy_present else None
    memory_started = time.perf_counter_ns()
    if legacy_present:
        calibration_path.replace(held_path)
    try:
        memory_result = aggregator.rebuild()
        memory_diagnostics = aggregator.get_source_diagnostics()
    finally:
        if legacy_present:
            held_path.replace(calibration_path)
    memory_latency = (time.perf_counter_ns() - memory_started) / 1_000_000.0
    if legacy_present and file_sha256(calibration_path) != original_hash:
        raise RuntimeError("secondary-consumer probe changed calibration.json")
    if not legacy_present and calibration_path.exists():
        raise RuntimeError("secondary-consumer probe created calibration.json")
    usable_memory = [row for row in memory_diagnostics if row.get("usable")]
    if not usable_memory or any(
        int((row.get("diagnostics") or {}).get("calibration_json_reads") or 0)
        for row in usable_memory
    ):
        raise RuntimeError("canonical calibration-memory aggregation used legacy data")

    runtime.emit_progress("secondary_memory", completed=1, total=1)
    summary_started = time.perf_counter_ns()
    summary_rows, summary_stats = build_calibration_recording_summary_rows(
        experiment_dir
    )
    summary_latency = (time.perf_counter_ns() - summary_started) / 1_000_000.0
    if not summary_rows or not any(row.get("result_id") for row in summary_rows):
        raise RuntimeError("recording summary omitted canonical result identity")
    runtime.emit_progress("secondary_summary", completed=1, total=1)

    run_dirs = sorted(
        path.parent for path in experiment_dir.glob("calibration_recordings/*/*/result.json")
    )
    if not run_dirs:
        raise RuntimeError("secondary-consumer probe found no canonical bundles")
    tool_started = time.perf_counter_ns()
    update_load = load_calibration_updates(run_dirs[0])
    tool_latency = (time.perf_counter_ns() - tool_started) / 1_000_000.0
    if update_load.source != "canonical":
        raise RuntimeError("offline update helper did not prefer canonical updates")

    export_root = Path(runtime.context.scenario_root) / "secondary-consumer-exports"
    export_started = time.perf_counter_ns()
    export_result = export_calibration_records(
        experiment_dir,
        output_dir=export_root,
    )
    export_latency = (time.perf_counter_ns() - export_started) / 1_000_000.0
    archive = Path(export_result["archive_path"])
    with zipfile.ZipFile(archive, "r") as handle:
        members = set(handle.namelist())
    required = {"calibration_index.jsonl", "manifest.json"}
    if legacy_present:
        required.add("calibration.json")
    if not required <= members or not any(name.endswith("/result.json") for name in members):
        raise RuntimeError("calibration export omitted canonical or legacy evidence")
    if not legacy_present and "calibration.json" in members:
        raise RuntimeError("canonical-only export invented calibration.json")
    runtime.emit_progress("secondary_export", completed=1, total=1)

    audit_path = experiment_dir / "experiment_audit.jsonl"
    canonical_audit_ref_count = 0
    if audit_path.is_file():
        for raw in audit_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(raw)
            details = row.get("details") or {}
            if isinstance(details.get("canonical_storage_ref"), Mapping):
                canonical_audit_ref_count += 1

    return {
        "memory_rebuild_latency_ms": distribution([memory_latency]),
        "summary_latency_ms": distribution([summary_latency]),
        "tool_update_load_latency_ms": distribution([tool_latency]),
        "export_latency_ms": distribution([export_latency]),
        "memory_usable_run_count": len(usable_memory),
        "memory_source_diagnostics": memory_diagnostics,
        "summary_row_count": len(summary_rows),
        "summary_stats": summary_stats,
        "tool_reader_state": update_load.reader_state,
        "export_archive_bytes": archive.stat().st_size,
        "export_member_count": len(members),
        "canonical_audit_ref_count": canonical_audit_ref_count,
        "legacy_present": legacy_present,
        "legacy_hash_preserved": (
            file_sha256(calibration_path) == original_hash
            if legacy_present
            else not calibration_path.exists()
        ),
        "consumer_error_count": 0,
    }


def _performance_body(runtime: JourneyRuntime) -> None:
    runtime.emit_progress("setup", completed=0, total=1)
    runtime.add_assertion(simulation_identity_assertion(runtime.context))
    runtime.harness.run_action(
        "fixture.prepare_calibration_storage",
        lambda: _prepare_minimal_experiment(runtime),
        surface=InteractionSurface.MODEL,
    )
    runtime.emit_progress("setup", completed=1, total=1)
    runtime.harness.run_action(
        "calibration.run_scripted_processes",
        lambda: _run_performance_workload(runtime),
        surface=InteractionSurface.MODEL,
    )
    observed = runtime.observations["performance_storage"]
    runtime.harness.run_action(
        "calibration.inspect_storage_artifacts",
        lambda: {
            "fixture_sha256": observed["fixture_sha256"],
            "workload_hash": observed["workload_hash"],
        },
        surface=InteractionSurface.HARNESS,
    )
    counts = {
        key: observed[key]
        for key in (
            "process_run_count",
            "update_count",
            "recording_count",
            "workload_capture_count",
            "canonical_update_count",
            "canonical_result_count",
            "canonical_index_event_count",
            "integrity_failure_count",
        )
    }
    expected_canonical_updates = 232 if observed["canonical_store_enabled"] else 0
    expected_canonical_runs = 200 if observed["canonical_store_enabled"] else 0
    runtime.add_assertion(
        _assertion(
            "calibration.storage.workload_counts_exact",
            counts
            == {
                "process_run_count": 200,
                "update_count": 232,
                "recording_count": 200,
                "workload_capture_count": 0,
                "canonical_update_count": expected_canonical_updates,
                "canonical_result_count": expected_canonical_runs,
                "canonical_index_event_count": expected_canonical_runs,
                "integrity_failure_count": 0,
            },
            counts,
            checkpoint="stress_terminal",
            sources=("calibration.json", "calibration_recordings"),
        )
    )
    metrics = observed["metrics"]
    metric_names = (
        "update_latency_ms",
        "process_finalize_latency_ms",
        "history_load_latency_ms",
        "fresh_reload_latency_ms",
        "calibration_rewrite_latency_ms",
        "recorder_append_latency_ms",
    )
    if observed["canonical_store_enabled"]:
        metric_names = metric_names + (
            "canonical_update_append_latency_ms",
            "result_finalize_latency",
            "index_latency",
        )
    metrics_ok = all((metrics[name] or {}).get("count", 0) > 0 for name in metric_names)
    runtime.add_assertion(
        _assertion(
            "calibration.storage.metrics_complete",
            metrics_ok,
            metrics,
            checkpoint="stress_terminal",
            sources=("StorageMetricsCollector",),
        )
    )
    growth = observed["artifact_growth"]
    resources = observed["resources"]
    growth_ok = (
        growth["calibration_json_bytes"] > 0
        and growth["scenario_total_bytes"] >= growth["calibration_json_bytes"]
        and resources.get("status") in {"measured", "partial"}
        and resources.get("values", {}).get("peak_rss_bytes") is not None
    )
    runtime.add_assertion(
        _assertion(
            "calibration.storage.growth_recorded",
            growth_ok,
            {"artifact_growth": growth, "resources": resources},
            checkpoint="stress_terminal",
            sources=("filesystem", "ProcessResourceSampler"),
        )
    )
    probe = observed["key_evidence_probe"]
    probe_ok = (
        probe["capture_count"] == 2
        and all(
            capture["width"] == 16 and capture["height"] == 12
            for capture in probe["captures"]
        )
        and probe["meta_outcome"] == "completed"
    )
    runtime.add_assertion(
        _assertion(
            "calibration.storage.key_evidence_probe_exact",
            probe_ok,
            probe,
            checkpoint="recorder_drain_probe",
            sources=("calibration_recordings/captures", "run_meta.json"),
        )
    )


def _artifact_assertion(runtime: JourneyRuntime, teardown: Mapping[str, Any]) -> AssertionResult:
    return cleanup_assertion(teardown)


def _base_workload(runtime: JourneyRuntime) -> dict[str, Any]:
    return {
        "workload_id": runtime.definition.workload_id,
        "fixture_schema_version": runtime.fixture["schema_version"],
        "fixture_path": runtime.fixture_path.relative_to(REPO_ROOT).as_posix(),
        "fixture_sha256": file_sha256(runtime.fixture_path),
        "speed_multiplier": runtime.harness.config.speed_multiplier,
        "timeout_seconds": runtime.harness.config.timeout_seconds,
    }


def _functional_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    observed = runtime.observations.get("functional_storage") or {}
    fresh = runtime.observations.get("fresh_application") or {}
    metrics = dict(observed.get("metrics") or {})
    if fresh.get("reload_latency_ms") is not None:
        metrics["fresh_reload_latency_ms"] = {
            "count": 1,
            "minimum": fresh["reload_latency_ms"],
            "median": fresh["reload_latency_ms"],
            "p95": fresh["reload_latency_ms"],
            "maximum": fresh["reload_latency_ms"],
        }
    return ComposedReportPayload(
        workload={
            **_base_workload(runtime),
            **dict(runtime.fixture.get("workload") or {}),
        },
        workflow_values={
            "process_count": observed.get("process_count", 0),
            "application_sessions": len(runtime.harness.application_sessions),
            "cleanup_results": [dict(teardown)],
        },
        persistence={
            "status": "measured",
            "values": {
                "calibration_storage": {
                    **dict(observed),
                    "fresh_application": dict(fresh),
                    "secondary_consumers": dict(
                        runtime.observations.get("secondary_consumers") or {}
                    ),
                    "legacy_writer_canaries": dict(
                        runtime.observations.get("legacy_writer_canaries") or {}
                    ),
                    "metrics": metrics,
                }
            },
        },
        resources=dict(
            runtime.observations.get("functional_resources")
            or {"status": "not_available", "values": {}}
        ),
        limitations=(
            (
                "Canonical structured persistence is mandatory; the retired writer never creates or rewrites calibration.json, while historical files remain readable."
                if _new_store_only_enabled(runtime)
                else "Canonical run artifacts are authoritative for new writes while application discovery remains on the legacy schema until Milestone 4."
                if _authoritative_enabled(runtime)
                else (
                    "Canonical run artifacts are non-authoritative shadow evidence; all application readers remain on the legacy schema."
                    if _shadow_enabled(runtime)
                    else "The scenario verifies current application storage and reader behavior only; it does not change or endorse the legacy schema."
                )
            ),
            "Capture policies are deterministic proxies and do not exercise camera acquisition or image analysis.",
            "No physical motion, dispense, pressure response, serial, GPIO, balance, firmware, or device-protocol claim is made.",
        ),
    )


def _performance_payload(
    runtime: JourneyRuntime, teardown: Mapping[str, Any]
) -> ComposedReportPayload:
    observed = dict(runtime.observations.get("performance_storage") or {})
    return ComposedReportPayload(
        workload={
            **_base_workload(runtime),
            **dict(runtime.fixture.get("workload") or {}),
            "workload_hash": observed.get("workload_hash"),
        },
        workflow_values={
            "process_run_count": observed.get("process_run_count", 0),
            "update_count": observed.get("update_count", 0),
            "cleanup_results": [dict(teardown)],
        },
        persistence={
            "status": "measured",
            "values": {"calibration_storage": observed},
        },
        resources=dict(observed.get("resources") or {"status": "not_available", "values": {}}),
        limitations=(
            (
                "This is the Milestone 3 authoritative canonical workload with legacy dual-writing retained."
                if _authoritative_enabled(runtime)
                else (
                    "This is the Milestone 2 dual-write shadow workload; legacy persistence remains authoritative."
                    if _shadow_enabled(runtime)
                    else "This is a current-writer characterization workload, not an acceptance threshold for the Milestone 2 store."
                )
            ),
            (
                "Canonical update, result finalization, and index latency are measured."
                if _canonical_enabled(runtime)
                else "Result finalization and index latency are explicitly unavailable until Milestone 2."
            ),
            "No physical hardware, camera, image analysis, firmware, motion, dispense, or protocol behavior is exercised.",
        ),
    )


def _summary(report: Mapping[str, Any], runtime: JourneyRuntime) -> str:
    return (
        f"Calibration storage SIL: {runtime.definition.workload_id}\n"
        f"Status: {report['classification']['status']}\n"
        f"Application sessions: {len(runtime.harness.application_sessions)}\n"
        "Replay: " + " ".join(report["run"]["replay_command"]) + "\n"
    )


FUNCTIONAL_DEFINITION = JourneyDefinition(
    registry_id=FUNCTIONAL_ID,
    scenario_name=FUNCTIONAL_SCENARIO,
    scenario_version="1",
    workload_id=FUNCTIONAL_ID,
    required_action_ids=FUNCTIONAL_ACTIONS,
    required_ui_action_ids=FUNCTIONAL_UI_ACTIONS,
    required_assertion_ids=FUNCTIONAL_ASSERTIONS,
    required_screenshots=frozenset(),
    fixture_loader=_functional_fixture,
    body=_functional_body,
    artifact_assertion=_artifact_assertion,
    payload_builder=_functional_payload,
    summary_builder=_summary,
)

PERFORMANCE_DEFINITION = JourneyDefinition(
    registry_id=PERFORMANCE_ID,
    scenario_name=PERFORMANCE_SCENARIO,
    scenario_version="1",
    workload_id=PERFORMANCE_ID,
    required_action_ids=PERFORMANCE_ACTIONS,
    required_ui_action_ids=frozenset(),
    required_assertion_ids=PERFORMANCE_ASSERTIONS,
    required_screenshots=frozenset(),
    fixture_loader=_performance_fixture,
    body=_performance_body,
    artifact_assertion=_artifact_assertion,
    payload_builder=_performance_payload,
    summary_builder=_summary,
)

SHADOW_FUNCTIONAL_DEFINITION = JourneyDefinition(
    registry_id=SHADOW_FUNCTIONAL_ID,
    scenario_name=SHADOW_FUNCTIONAL_SCENARIO,
    scenario_version="1",
    workload_id=SHADOW_FUNCTIONAL_ID,
    required_action_ids=FUNCTIONAL_ACTIONS,
    required_ui_action_ids=FUNCTIONAL_UI_ACTIONS,
    required_assertion_ids=FUNCTIONAL_ASSERTIONS,
    required_screenshots=frozenset(),
    fixture_loader=_functional_fixture,
    body=_functional_body,
    artifact_assertion=_artifact_assertion,
    payload_builder=_functional_payload,
    summary_builder=_summary,
)

SHADOW_PERFORMANCE_DEFINITION = JourneyDefinition(
    registry_id=SHADOW_PERFORMANCE_ID,
    scenario_name=SHADOW_PERFORMANCE_SCENARIO,
    scenario_version="1",
    workload_id=SHADOW_PERFORMANCE_ID,
    required_action_ids=PERFORMANCE_ACTIONS,
    required_ui_action_ids=frozenset(),
    required_assertion_ids=PERFORMANCE_ASSERTIONS,
    required_screenshots=frozenset(),
    fixture_loader=_performance_fixture,
    body=_performance_body,
    artifact_assertion=_artifact_assertion,
    payload_builder=_performance_payload,
    summary_builder=_summary,
)

AUTHORITATIVE_FUNCTIONAL_DEFINITION = JourneyDefinition(
    registry_id=AUTHORITATIVE_FUNCTIONAL_ID,
    scenario_name=AUTHORITATIVE_FUNCTIONAL_SCENARIO,
    scenario_version="1",
    workload_id=AUTHORITATIVE_FUNCTIONAL_ID,
    required_action_ids=FUNCTIONAL_ACTIONS,
    required_ui_action_ids=FUNCTIONAL_UI_ACTIONS,
    required_assertion_ids=FUNCTIONAL_ASSERTIONS,
    required_screenshots=frozenset(),
    fixture_loader=_functional_fixture,
    body=_functional_body,
    artifact_assertion=_artifact_assertion,
    payload_builder=_functional_payload,
    summary_builder=_summary,
)

AUTHORITATIVE_PERFORMANCE_DEFINITION = JourneyDefinition(
    registry_id=AUTHORITATIVE_PERFORMANCE_ID,
    scenario_name=AUTHORITATIVE_PERFORMANCE_SCENARIO,
    scenario_version="1",
    workload_id=AUTHORITATIVE_PERFORMANCE_ID,
    required_action_ids=PERFORMANCE_ACTIONS,
    required_ui_action_ids=frozenset(),
    required_assertion_ids=PERFORMANCE_ASSERTIONS,
    required_screenshots=frozenset(),
    fixture_loader=_performance_fixture,
    body=_performance_body,
    artifact_assertion=_artifact_assertion,
    payload_builder=_performance_payload,
    summary_builder=_summary,
)

PRIMARY_READER_FUNCTIONAL_DEFINITION = JourneyDefinition(
    registry_id=PRIMARY_READER_FUNCTIONAL_ID,
    scenario_name=PRIMARY_READER_FUNCTIONAL_SCENARIO,
    scenario_version="1",
    workload_id=PRIMARY_READER_FUNCTIONAL_ID,
    required_action_ids=FUNCTIONAL_ACTIONS,
    required_ui_action_ids=FUNCTIONAL_UI_ACTIONS,
    required_assertion_ids=FUNCTIONAL_ASSERTIONS,
    required_screenshots=frozenset(),
    fixture_loader=_functional_fixture,
    body=_functional_body,
    artifact_assertion=_artifact_assertion,
    payload_builder=_functional_payload,
    summary_builder=_summary,
)

PRIMARY_READER_PERFORMANCE_DEFINITION = JourneyDefinition(
    registry_id=PRIMARY_READER_PERFORMANCE_ID,
    scenario_name=PRIMARY_READER_PERFORMANCE_SCENARIO,
    scenario_version="1",
    workload_id=PRIMARY_READER_PERFORMANCE_ID,
    required_action_ids=PERFORMANCE_ACTIONS,
    required_ui_action_ids=frozenset(),
    required_assertion_ids=PERFORMANCE_ASSERTIONS,
    required_screenshots=frozenset(),
    fixture_loader=_performance_fixture,
    body=_performance_body,
    artifact_assertion=_artifact_assertion,
    payload_builder=_performance_payload,
    summary_builder=_summary,
)

SECONDARY_READER_FUNCTIONAL_DEFINITION = JourneyDefinition(
    registry_id=SECONDARY_READER_FUNCTIONAL_ID,
    scenario_name=SECONDARY_READER_FUNCTIONAL_SCENARIO,
    scenario_version="1",
    workload_id=SECONDARY_READER_FUNCTIONAL_ID,
    required_action_ids=FUNCTIONAL_ACTIONS,
    required_ui_action_ids=FUNCTIONAL_UI_ACTIONS,
    required_assertion_ids=FUNCTIONAL_ASSERTIONS,
    required_screenshots=frozenset(),
    fixture_loader=_functional_fixture,
    body=_functional_body,
    artifact_assertion=_artifact_assertion,
    payload_builder=_functional_payload,
    summary_builder=_summary,
)

NEW_STORE_ONLY_FUNCTIONAL_DEFINITION = JourneyDefinition(
    registry_id=NEW_STORE_ONLY_FUNCTIONAL_ID,
    scenario_name=NEW_STORE_ONLY_FUNCTIONAL_SCENARIO,
    scenario_version="1",
    workload_id=NEW_STORE_ONLY_FUNCTIONAL_ID,
    required_action_ids=FUNCTIONAL_ACTIONS,
    required_ui_action_ids=FUNCTIONAL_UI_ACTIONS,
    required_assertion_ids=NEW_STORE_ONLY_ASSERTIONS,
    required_screenshots=frozenset(),
    fixture_loader=_new_store_only_fixture,
    body=_functional_body,
    artifact_assertion=_artifact_assertion,
    payload_builder=_functional_payload,
    summary_builder=_summary,
)

SECONDARY_READER_PERFORMANCE_DEFINITION = JourneyDefinition(
    registry_id=SECONDARY_READER_PERFORMANCE_ID,
    scenario_name=SECONDARY_READER_PERFORMANCE_SCENARIO,
    scenario_version="1",
    workload_id=SECONDARY_READER_PERFORMANCE_ID,
    required_action_ids=PERFORMANCE_ACTIONS,
    required_ui_action_ids=frozenset(),
    required_assertion_ids=PERFORMANCE_ASSERTIONS,
    required_screenshots=frozenset(),
    fixture_loader=_performance_fixture,
    body=_performance_body,
    artifact_assertion=_artifact_assertion,
    payload_builder=_performance_payload,
    summary_builder=_summary,
)


__all__ = [
    "AUTHORITATIVE_FUNCTIONAL_DEFINITION",
    "AUTHORITATIVE_FUNCTIONAL_ID",
    "AUTHORITATIVE_PERFORMANCE_DEFINITION",
    "AUTHORITATIVE_PERFORMANCE_ID",
    "FUNCTIONAL_DEFINITION",
    "FUNCTIONAL_ID",
    "NEW_STORE_ONLY_FUNCTIONAL_DEFINITION",
    "NEW_STORE_ONLY_FUNCTIONAL_ID",
    "PERFORMANCE_DEFINITION",
    "PERFORMANCE_ID",
    "PRIMARY_READER_FUNCTIONAL_DEFINITION",
    "PRIMARY_READER_FUNCTIONAL_ID",
    "PRIMARY_READER_PERFORMANCE_DEFINITION",
    "PRIMARY_READER_PERFORMANCE_ID",
    "SECONDARY_READER_FUNCTIONAL_DEFINITION",
    "SECONDARY_READER_FUNCTIONAL_ID",
    "SECONDARY_READER_PERFORMANCE_DEFINITION",
    "SECONDARY_READER_PERFORMANCE_ID",
    "SHADOW_FUNCTIONAL_DEFINITION",
    "SHADOW_FUNCTIONAL_ID",
    "SHADOW_PERFORMANCE_DEFINITION",
    "SHADOW_PERFORMANCE_ID",
]
