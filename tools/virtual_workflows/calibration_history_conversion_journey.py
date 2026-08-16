"""Short composed SIL journey for offline historical calibration conversion."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Mapping
import zipfile

from tools.sil.calibration_history_conversion_fixture import (
    FIXTURE_PATH,
    load_fixture,
    materialize_fixture,
)
from tools.sil.calibration_storage_contract import file_sha256
from tools.sil.calibration_storage_process import SyntheticStorageHead
from tools.virtual_workflows.actions import InteractionSurface
from tools.virtual_workflows.assertions import (
    AssertionResult,
    cleanup_assertion,
    simulation_identity_assertion,
)
from tools.virtual_workflows.composition import JourneyDefinition, JourneyRuntime
from tools.virtual_workflows.page_drivers import MachineControlsDriver
from tools.virtual_workflows.report import ComposedReportPayload


REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_ID = "calibration_storage_historical_conversion_contract_v1"
SCENARIO_NAME = "calibration_storage_historical_conversion_contract"
ASSERTIONS = (
    "sil.host_hardware_disabled",
    "calibration.migration.plan_exact",
    "calibration.migration.source_immutable",
    "calibration.migration.reader_application_exact",
    "calibration.migration.export_exact",
    "calibration.migration.idempotent",
    "artifacts.cleanup_complete",
)
ACTIONS = frozenset(
    {
        "fixture.prepare_calibration_storage",
        "calibration.inspect_storage_artifacts",
        "calibration.stage_persisted_selection",
        "app.launch_simulated",
        "app.close_simulated_session",
        "machine.connect_via_ui",
        "scenario.teardown",
    }
)


def _live_progress(stage: str, completed: int, total: int, detail: str = "") -> None:
    suffix = f" ({detail})" if detail else ""
    print(
        f"[calibration-migration] {stage}: {completed}/{total}{suffix}",
        flush=True,
    )


def _fixture():
    return load_fixture(FIXTURE_PATH), FIXTURE_PATH


def _assertion(assertion_id: str, passed: bool, evidence: Mapping[str, Any]):
    return AssertionResult(
        assertion_id,
        "historical_conversion",
        "pass" if passed else "fail",
        ("fixture", "filesystem", "canonical_reader"),
        dict(evidence),
        None if passed else f"{assertion_id} failed",
    )


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): file_sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _prepare(runtime: JourneyRuntime) -> dict[str, Any]:
    experiment_dir = Path(runtime.context.scenario_root) / "historical_conversion_experiment"
    evidence = materialize_fixture(experiment_dir, runtime.fixture)
    evidence["source_calibration_sha256"] = file_sha256(evidence["calibration_path"])
    runtime.observations["migration_experiment"] = evidence
    return evidence


def _convert(runtime: JourneyRuntime) -> dict[str, Any]:
    from CalibrationHistoricalConversion import CalibrationHistoricalConverter

    prepared = runtime.observations["migration_experiment"]
    root = Path(prepared["experiment_dir"])

    def progress(stage, completed, total, details):
        detail = str(details.get("item_id") or "")
        _live_progress(stage, completed, total, detail)
        runtime.emit_progress(
            stage,
            completed=completed,
            total=total,
            detail=detail or None,
        )

    converter = CalibrationHistoricalConverter(root, progress_callback=progress)
    plan_started = time.perf_counter_ns()
    plan = converter.plan()
    plan_ms = (time.perf_counter_ns() - plan_started) / 1_000_000.0
    apply_started = time.perf_counter_ns()
    report = converter.apply()
    apply_ms = (time.perf_counter_ns() - apply_started) / 1_000_000.0
    expected = dict(prepared["expected_counts"])
    expected_plan = dict(expected)
    expected_plan.pop("generated_count")
    exact = plan.counts == expected_plan and report["generated_count"] == expected["generated_count"]
    evidence = {
        "plan_counts": plan.counts,
        "expected_counts": expected,
        "generated_count": report["generated_count"],
        "plan_latency_ms": plan_ms,
        "apply_latency_ms": apply_ms,
        "exact": exact,
    }
    runtime.add_assertion(_assertion("calibration.migration.plan_exact", exact, evidence))
    runtime.observations["conversion"] = {**evidence, "report": report}
    return evidence


def _fresh_reader_application_export(runtime: JourneyRuntime) -> dict[str, Any]:
    from CalibrationRecordExport import export_calibration_records
    from CalibrationHistoricalConversion import CalibrationHistoricalConverter

    prepared = runtime.observations["migration_experiment"]
    root = Path(prepared["experiment_dir"])
    calibration_path = Path(prepared["calibration_path"])
    source_before = prepared["source_calibration_sha256"]

    _live_progress("fresh_reload", 0, 1)
    runtime.emit_progress("fresh_reload", completed=0, total=1)
    runtime.harness.close_application_session()
    runtime.harness.reopen_application_session()
    runtime.harness.run_action(
        "machine.connect_via_ui",
        lambda: MachineControlsDriver(runtime.context).connect()
        or {"port": "SIMULATED"},
        surface=InteractionSurface.UI,
    )
    _live_progress("fresh_reload_bind", 0, 5, "set calibration path")
    manager = runtime.context.model.calibration_manager
    manager.update_calibration_file_path(str(calibration_path))
    _live_progress("fresh_reload_bind", 1, 5, "stage synthetic head")
    head = SyntheticStorageHead(runtime.fixture["identity"])
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
    _live_progress("fresh_reload_bind", 2, 5, "read history")
    history_started = time.perf_counter_ns()
    history = manager.get_characterization_history_snapshot()
    history_ms = (time.perf_counter_ns() - history_started) / 1_000_000.0
    rows = list(history["rows"])
    migrated_rows = [
        row for row in rows
        if row.get("reader_state") == "matching_dual"
        and row.get("source_phase_key") == "pressure_sweep_characterization"
        and row.get("process_run_id", "").startswith("migration_")
    ]
    target = next(
        (row for row in migrated_rows if row.get("source_pressure_index") == 0),
        None,
    )
    _live_progress("fresh_reload_bind", 3, 5, "resolve selection")
    resolved = manager.resolve_characterization_selection(target or {})
    _live_progress("fresh_reload_bind", 4, 5, "apply settings")
    command_count_before = len(runtime.context.machine.command_event_history)
    settings = (
        runtime.context.controller.apply_applied_imaging_calibration_print_settings(
            resolved.get("row") or {}
        )
        if resolved.get("ok")
        else {"ok": False, "message": resolved.get("message")}
    )
    runtime.context.app.processEvents()
    _live_progress("fresh_reload_bind", 5, 5, "settings applied")
    commands = list(runtime.context.machine.command_event_history)[command_count_before:]
    command_types = [str(row.get("command_type") or "") for row in commands]
    application_ok = bool(
        target
        and resolved.get("ok")
        and settings.get("ok")
        and set(command_types) <= {"SET_WIDTH_P", "ABSOLUTE_PRESSURE_P"}
        and not any(
            value.startswith(("DISPENSE", "ABSOLUTE_X", "ABSOLUTE_Y", "ABSOLUTE_Z", "HOME_"))
            for value in command_types
        )
    )
    application_evidence = {
        "history_row_count": len(rows),
        "migrated_sweep_row_count": len(migrated_rows),
        "reader_issue_count": len(history["issues"]),
        "history_latency_ms": history_ms,
        "resolved_code": resolved.get("code"),
        "settings_result": settings,
        "command_types": command_types,
    }
    runtime.add_assertion(
        _assertion(
            "calibration.migration.reader_application_exact",
            application_ok,
            application_evidence,
        )
    )
    runtime.emit_progress("fresh_reload", completed=1, total=1)
    _live_progress("fresh_reload", 1, 1)

    export_root = Path(runtime.context.scenario_root) / "exports"
    export_root.mkdir(parents=True, exist_ok=True)
    export_started = time.perf_counter_ns()
    export = export_calibration_records(
        root,
        export_root,
        progress_callback=lambda stage, completed, total: runtime.emit_progress(
            f"export_{stage}", completed=completed, total=total
        ),
    )
    export_ms = (time.perf_counter_ns() - export_started) / 1_000_000.0
    with zipfile.ZipFile(export["archive_path"]) as archive:
        names = set(archive.namelist())
    export_ok = bool(
        "calibration_history_migration.json" in names
        and "calibration.json" in names
        and "calibration_index.jsonl" in names
        and "manifest.json" in names
        and export["canonical_storage"]["status"] == "valid"
    )
    export_evidence = {
        "archive_path": export["archive_path"],
        "archive_size_bytes": export["archive_size_bytes"],
        "export_latency_ms": export_ms,
        "required_files_present": export_ok,
        "canonical_storage": export["canonical_storage"],
    }
    runtime.add_assertion(
        _assertion("calibration.migration.export_exact", export_ok, export_evidence)
    )

    before_reapply = _tree_hashes(root)
    reapply_started = time.perf_counter_ns()
    reapply = CalibrationHistoricalConverter(root).apply()
    reapply_ms = (time.perf_counter_ns() - reapply_started) / 1_000_000.0
    after_reapply = _tree_hashes(root)
    idempotent = before_reapply == after_reapply and reapply["status"] == "valid"
    runtime.add_assertion(
        _assertion(
            "calibration.migration.idempotent",
            idempotent,
            {
                "tree_hashes_unchanged": before_reapply == after_reapply,
                "reapply_latency_ms": reapply_ms,
                "manifest_sha256": reapply.get("manifest_sha256"),
            },
        )
    )
    source_after = file_sha256(calibration_path)
    source_immutable = source_after == source_before
    runtime.add_assertion(
        _assertion(
            "calibration.migration.source_immutable",
            source_immutable,
            {"source_before": source_before, "source_after": source_after},
        )
    )
    observed = {
        **application_evidence,
        **export_evidence,
        "reapply_latency_ms": reapply_ms,
        "source_immutable": source_immutable,
        "idempotent": idempotent,
    }
    runtime.observations["reader_export"] = observed
    return observed


def _body(runtime: JourneyRuntime) -> None:
    _live_progress("journey_body", 0, 3)
    runtime.add_assertion(simulation_identity_assertion(runtime.context))
    runtime.harness.run_action(
        "fixture.prepare_calibration_storage",
        lambda: _prepare(runtime),
        surface=InteractionSurface.HARNESS,
    )
    _live_progress("journey_body", 1, 3)
    runtime.harness.run_action(
        "calibration.inspect_storage_artifacts",
        lambda: _convert(runtime),
        surface=InteractionSurface.HARNESS,
    )
    _live_progress("journey_body", 2, 3)
    runtime.harness.run_action(
        "calibration.stage_persisted_selection",
        lambda: _fresh_reader_application_export(runtime),
        surface=InteractionSurface.MODEL,
    )
    _live_progress("journey_body", 3, 3)


def _artifact(runtime: JourneyRuntime, teardown: Mapping[str, Any]):
    return cleanup_assertion(teardown)


def _payload(runtime: JourneyRuntime, teardown: Mapping[str, Any]):
    conversion = dict(runtime.observations.get("conversion") or {})
    reader_export = dict(runtime.observations.get("reader_export") or {})
    return ComposedReportPayload(
        workload={
            "workload_id": SCENARIO_ID,
            "fixture_path": FIXTURE_PATH.relative_to(REPO_ROOT).as_posix(),
            "fixture_sha256": file_sha256(FIXTURE_PATH),
            "source_step_count": 12,
            "expected_generated_count": 9,
            "timeout_seconds": runtime.harness.config.timeout_seconds,
        },
        workflow_values={
            "application_sessions": len(runtime.harness.application_sessions),
            "cleanup_results": [dict(teardown)],
            "progress_checkpoints": list(runtime.observations.get("progress_checkpoints") or ()),
        },
        persistence={
            "status": "measured",
            "values": {
                "calibration_history_conversion": {
                    **conversion,
                    "reader_export": reader_export,
                }
            },
        },
        limitations=(
            "Offline storage conversion only; no camera or image-analysis claim.",
            "No physical motion, pressure response, dispense, firmware, or device protocol is exercised.",
            "This short correctness workload replaces the previous 200-process stress workload for Milestone 5.",
        ),
    )


def _summary(report: Mapping[str, Any], runtime: JourneyRuntime) -> str:
    return (
        "Historical calibration conversion SIL\n"
        f"Status: {report['classification']['status']}\n"
        "Source steps: 12\nGenerated bundles: 9\n"
        "Replay: " + " ".join(report["run"]["replay_command"]) + "\n"
    )


DEFINITION = JourneyDefinition(
    registry_id=SCENARIO_ID,
    scenario_name=SCENARIO_NAME,
    scenario_version="1",
    workload_id=SCENARIO_ID,
    required_action_ids=ACTIONS,
    required_ui_action_ids=frozenset({"machine.connect_via_ui"}),
    required_assertion_ids=ASSERTIONS,
    required_screenshots=frozenset(),
    fixture_loader=_fixture,
    body=_body,
    artifact_assertion=_artifact,
    payload_builder=_payload,
    summary_builder=_summary,
)


__all__ = ["ASSERTIONS", "DEFINITION", "SCENARIO_ID", "SCENARIO_NAME"]
