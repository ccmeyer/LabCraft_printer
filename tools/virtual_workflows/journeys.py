"""Short typed compositions for migrated SIL journeys."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from tools.virtual_workflows.actions import (
    InteractionSurface,
    capture_milestone,
)
from tools.virtual_workflows.assertions import (
    AssertionResult,
    calibration_assertion,
    cleanup_assertion,
    machine_ready_assertion,
    prepared_execution_assertion,
    rack_head_assertion,
    simulation_identity_assertion,
    terminal_execution_assertion,
)
from tools.virtual_workflows.harness import AutomationHarness, AutomationHarnessConfig
from tools.virtual_workflows.page_drivers import (
    ArrayDriver,
    CalibrationDialogDriver,
    ExperimentEditorDriver,
    MachineControlsDriver,
    RackDriver,
)
from tools.virtual_workflows.report import (
    REPORT_SCHEMA_NAME,
    REPORT_SCHEMA_VERSION,
    collect_environment_identity,
    validate_interaction_surface_claims,
    validate_report_v1,
    write_report_atomic,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_WORKLOAD_ID = "virtual_print_array_24_v1"
SMOKE_SCENARIO_NAME = "virtual_print_array"
SMOKE_SCENARIO_VERSION = "1"
SMOKE_REQUIRED_ASSERTIONS = (
    "sil.host_hardware_disabled",
    "machine.normal_ui_ready",
    "experiment.prepared_bundle_valid",
    "execution.rack_head_associated",
    "execution.applied_calibration_valid",
    "execution.terminal_bundle_valid",
    "artifacts.cleanup_complete",
)
SMOKE_REQUIRED_UI_ACTIONS = frozenset(
    {
        "machine.connect_via_ui",
        "machine.enable_motors_via_ui",
        "machine.home_via_ui",
        "machine.configure_print_settings_via_ui",
        "editor.open_via_ui",
        "editor.new_experiment_via_ui",
        "editor.configure_design_via_ui",
        "editor.optimize_generate_via_ui",
        "editor.finish_via_ui",
        "head.set_volume_via_ui",
        "head.stage_via_ui",
        "pressure.enable_regulation_via_ui",
        "calibration.open_via_ui",
        "calibration.generate_via_ui",
        "calibration.select_via_ui",
        "calibration.apply_via_ui",
        "array.start_via_ui",
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class JourneyRunConfig:
    scenario_id: str = SMOKE_WORKLOAD_ID
    output_root: Path = REPO_ROOT / "verification_reports" / "virtual_workflows"
    visible: bool = False
    seed: int = 1
    speed_multiplier: float = 1.0
    timeout_seconds: float = 180.0
    run_id: str | None = None

    def __post_init__(self) -> None:
        if self.scenario_id != SMOKE_WORKLOAD_ID:
            raise ValueError(f"unsupported composed journey: {self.scenario_id!r}")
        object.__setattr__(self, "output_root", Path(self.output_root).resolve())


def _fixture() -> tuple[dict[str, Any], Path]:
    from tools.virtual_workflows.scenarios import load_virtual_print_array_fixture

    path = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "virtual_print_array_24_v1.json"
    )
    return load_virtual_print_array_fixture(path, scenario_id=SMOKE_WORKLOAD_ID), path


def _well_ids(fixture: Mapping[str, Any]) -> tuple[str, ...]:
    from tools.virtual_workflows.scenarios import fixture_well_ids

    return fixture_well_ids(dict(fixture))


def _editor_specification(
    fixture: Mapping[str, Any], expected_wells: tuple[str, ...]
) -> dict[str, Any]:
    stock = fixture["stocks"][0]
    volume = float(stock["droplet_volume_nL"])
    return {
        "experiment": {
            "name": SMOKE_WORKLOAD_ID,
            "plate_name": fixture["plate"]["name"],
            "replicates": len(expected_wells),
            "expected_well_ids": list(expected_wells),
            "printed_volume_nL": volume,
            "final_volume_nL": volume,
            "printed_volume_tolerance_nL": 0.0,
            "randomize_assignments": False,
            "allow_two_stock_solutions": False,
        },
        "reagent": {
            "stock_label": stock["factor_name"],
            "group": "Additive",
            "printing_mode": stock["printing_mode"],
            "starting_concentration": 0.0,
            "targets": [float(stock["target_concentration"])],
            "units": stock["units"],
            "fixed_stock_concentration": float(stock["concentration"]),
            "droplet_volume_nL": volume,
        },
    }


def _add_assertion(harness: AutomationHarness, result: AssertionResult) -> None:
    harness.add_assertion_result(result.to_dict())
    if result.decision != "pass":
        raise RuntimeError(
            f"required assertion {result.assertion_id} was {result.decision}: "
            f"{result.message or result.evidence}"
        )


def _mark_incomplete_assertions(harness: AutomationHarness) -> None:
    present = {
        str(item.get("assertion_id")) for item in harness.assertion_results
    }
    for assertion_id in SMOKE_REQUIRED_ASSERTIONS:
        if assertion_id in present:
            continue
        harness.add_assertion_result(
            {
                "assertion_id": assertion_id,
                "checkpoint": "not_reached",
                "decision": "incomplete",
                "observable_sources": [],
                "evidence": {},
                "message": "journey failed before this required checkpoint",
            }
        )


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _report(
    harness: AutomationHarness,
    *,
    fixture: Mapping[str, Any],
    fixture_path: Path,
    expected_wells: tuple[str, ...],
    completed_wells: list[str],
    teardown: Mapping[str, Any],
) -> dict[str, Any]:
    import hashlib

    identity = collect_environment_identity(REPO_ROOT)
    fixture_hash = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    decisions = {
        str(row.get("assertion_id")): str(row.get("decision"))
        for row in harness.assertion_results
    }
    passed = all(decisions.get(item) == "pass" for item in SMOKE_REQUIRED_ASSERTIONS)
    failure_text = str(harness.failure) if harness.failure is not None else None
    classification = "pass" if passed and failure_text is None else "fail"
    replay_parts = [
        r".\env\Scripts\python.exe",
        r"tools\run_virtual_workflow.py",
        "--scenario",
        SMOKE_WORKLOAD_ID,
        "--output-root",
        str(harness.config.output_root),
        "--seed",
        str(harness.config.seed),
        "--speed-multiplier",
        str(harness.config.speed_multiplier),
        "--timeout-seconds",
        str(harness.config.timeout_seconds),
    ]
    if harness.config.visible:
        replay_parts.append("--visible")
    report = {
        "schema_name": REPORT_SCHEMA_NAME,
        "schema_version": REPORT_SCHEMA_VERSION,
        "run": {
            "run_id": harness.run_id,
            "scenario_name": SMOKE_SCENARIO_NAME,
            "scenario_version": SMOKE_SCENARIO_VERSION,
            "run_mode": (
                "visible_windows_sil"
                if harness.config.visible
                else "offscreen_windows_sil"
            ),
            "timing_policy": (
                "simulated_command_durations_x"
                f"{harness.config.speed_multiplier:g}"
            ),
            "warmup_runs": 0,
            "measured_runs": 1,
            "started_at_utc": harness.started_at_utc,
            "ended_at_utc": _utc_now(),
            "duration_ms": harness.duration_ms,
            "seed": harness.config.seed,
            "replay_command": replay_parts,
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
            "scenario_root": str(harness.scenario_root),
            "report_dir": str(harness.report_dir),
            "root_containment_valid": bool(
                harness.session is not None
                and harness.session.application_roots is not None
                and all(
                    Path(value).resolve().is_relative_to(harness.scenario_root)
                    for value in (
                        harness.session.application_roots.config_root,
                        harness.session.application_roots.experiments_root,
                        harness.session.application_roots.calibration_memory_root,
                    )
                )
            ),
        },
        "workload": {
            "workload_id": SMOKE_WORKLOAD_ID,
            "fixture_schema_version": fixture["schema_version"],
            "fixture_path": fixture_path.relative_to(REPO_ROOT).as_posix(),
            "fixture_sha256": fixture_hash,
            "plate_name": fixture["plate"]["name"],
            "plate_rows": fixture["plate"]["rows"],
            "plate_columns": fixture["plate"]["columns"],
            "well_ids": list(expected_wells),
            "stock_count": 1,
            "array_passes": 1,
            "target_dispenses_per_well": 1,
            "expected_completion_count": len(expected_wells),
            "speed_multiplier": harness.config.speed_multiplier,
            "timeout_seconds": harness.config.timeout_seconds,
        },
        "metrics": {
            "responsiveness": {"status": "not_applicable", "values": {}},
            "workflow": {
                "status": "measured",
                "values": {
                    "expected_well_count": len(expected_wells),
                    "completed_well_count": len(completed_wells),
                    "expected_stock_well_completion_count": len(expected_wells),
                    "completed_stock_well_count": len(completed_wells),
                    "completed_well_ids": list(completed_wells),
                    "well_update_count": len(completed_wells),
                    "array_states": list(harness.context.array_states),
                    "dialogs": list(harness.context.dialogs),
                    "unexpected_dialogs": list(harness.context.unexpected_dialogs),
                    "errors": list(harness.context.errors),
                    "action_results": list(harness.context.action_results),
                    "assertion_results": list(harness.assertion_results),
                    "lifecycle_milestones": list(harness.context.milestones),
                    "cleanup_results": [dict(teardown)],
                    "interaction_surface_policy": "state-changing UI actions require QTest",
                },
            },
            "queue": {
                "status": "measured",
                "values": {
                    "queue_drained_at_terminal": bool(
                        (
                            next(
                                (
                                    row for row in harness.assertion_results
                                    if row.get("assertion_id")
                                    == "execution.terminal_bundle_valid"
                                ),
                                {},
                            ).get("evidence")
                            or {}
                        ).get("queue_drained")
                    )
                },
            },
            "persistence": {
                "status": "measured" if passed else "partial",
                "values": {
                    "assertion_decisions": decisions,
                    "terminal": next(
                        (
                            row.get("evidence", {})
                            for row in harness.assertion_results
                            if row.get("assertion_id")
                            == "execution.terminal_bundle_valid"
                        ),
                        {},
                    ),
                },
            },
            "resources": {"status": "not_applicable", "values": {}},
        },
        "artifacts": {
            "report_json": "report.json",
            "summary_text": "summary.txt",
            "event_trace": "events.jsonl",
            "action_ledger": "action_ledger.json",
            "assertion_ledger": "assertion_ledger.json",
            "evidence_manifest": "evidence_manifest.json",
            "failure_traceback": (
                "failure_traceback.txt" if harness.failure is not None else None
            ),
            "scenario_root": str(harness.scenario_root),
            "screenshots": {
                name: _relative(path, harness.report_dir)
                for name, path in sorted(harness.context.screenshots.items())
            },
        },
        "classification": {
            "status": classification,
            "threshold_maturity": "informational",
            "reasons": [] if classification == "pass" else [failure_text or "required assertion failed"],
        },
        "limitations": [
            "The simulator verifies the application-facing contract, not firmware framing or ACK behavior.",
            "No physical motion, collision safety, pressure response, camera analysis, balance behavior, or droplet quality is modeled.",
            "Session-specific plan, printer-head, timestamp, and calibration identities are recorded but are not expected to be byte-identical across replay.",
        ],
    }
    action_results = report["metrics"]["workflow"]["values"]["action_results"]
    observed_action_ids = {str(row.get("action_id")) for row in action_results}
    validate_interaction_surface_claims(
        action_results,
        required_ui_action_ids=(
            SMOKE_REQUIRED_UI_ACTIONS
            if classification == "pass"
            else SMOKE_REQUIRED_UI_ACTIONS & observed_action_ids
        ),
    )
    validate_report_v1(report)
    return report


def _summary(report: Mapping[str, Any]) -> str:
    workflow = report["metrics"]["workflow"]["values"]
    return (
        "Milestone 6 composed 24-well smoke\n"
        f"Status: {report['classification']['status']}\n"
        f"Completions: {workflow['completed_stock_well_count']} / "
        f"{report['workload']['expected_completion_count']}\n"
        f"Seed: {report['run']['seed']}\n"
        "Replay: " + " ".join(report["run"]["replay_command"]) + "\n"
    )


def run_virtual_print_array_24_journey(config: JourneyRunConfig) -> dict[str, Any]:
    fixture, fixture_path = _fixture()
    expected_wells = _well_ids(fixture)
    stock = fixture["stocks"][0]
    head = stock["printer_head"]
    harness = AutomationHarness(
        AutomationHarnessConfig(
            scenario_id=SMOKE_SCENARIO_NAME,
            workload_id=SMOKE_WORKLOAD_ID,
            output_root=config.output_root,
            visible=config.visible,
            seed=config.seed,
            speed_multiplier=config.speed_multiplier,
            timeout_seconds=config.timeout_seconds,
            run_id=config.run_id,
        )
    )
    completed_wells: list[str] = []
    teardown: dict[str, Any] = {}
    try:
        harness.start()
        context = harness.context
        context.model.well_plate.well_state_changed_signal.connect(
            lambda well_id: completed_wells.append(str(well_id))
        )
        context.controller.array_state_changed.connect(
            lambda state: context.array_states.append(str(state))
        )
        context.controller.error_occurred_signal.connect(
            lambda *args: context.errors.append(
                {"source": "controller", "arguments": [str(value) for value in args]}
            )
        )

        _add_assertion(harness, simulation_identity_assertion(context))
        machine = MachineControlsDriver(context)
        harness.run_action(
            "machine.connect_via_ui",
            lambda: machine.connect() or {"port": "SIMULATED"},
        )
        harness.run_action(
            "machine.enable_motors_via_ui",
            lambda: machine.enable_motors() or {"motors_enabled": True},
        )
        harness.run_action(
            "machine.home_via_ui",
            lambda: machine.home_motors() or {"motors_homed": True},
        )
        _add_assertion(harness, machine_ready_assertion(context))

        editor = ExperimentEditorDriver(context)
        editor.create_and_finalize(
            _editor_specification(fixture, expected_wells)
        )
        harness.assert_no_unexpected_dialog()
        harness.session.snapshot(
            "action:editor.finish_via_ui",
            include_persistence=True,
            correlation={"action_id": "editor.finish_via_ui"},
        )
        _add_assertion(
            harness, prepared_execution_assertion(context, len(expected_wells))
        )

        harness.run_action(
            "machine.configure_print_settings_via_ui",
            lambda: machine.configure_print_settings(
                pulse_width_us=int(head["print_pulse_width_us"]),
                pressure_psi=float(head["print_pressure_psi"]),
                frequency_hz=int(fixture["simulation"]["dispense_frequency_hz"]),
            )
            or {
                "pulse_width_us": int(head["print_pulse_width_us"]),
                "pressure_psi": float(head["print_pressure_psi"]),
                "frequency_hz": int(
                    fixture["simulation"]["dispense_frequency_hz"]
                ),
            },
        )

        rack = RackDriver(context)
        slot = int(fixture["simulation"]["staging_slot"])
        harness.run_action(
            "head.set_volume_via_ui",
            lambda: rack.set_slot_volume(slot, float(head["initial_volume_uL"]))
            or {"slot": slot, "volume_uL": float(head["initial_volume_uL"])},
        )
        harness.run_action(
            "head.stage_via_ui",
            lambda: rack.confirm_and_load(slot)
            or {
                "slot": slot,
                "stock_id": context.model.rack_model.get_gripper_printer_head().get_stock_id(),
            },
        )
        _add_assertion(harness, rack_head_assertion(context))

        harness.run_action(
            "pressure.enable_regulation_via_ui",
            lambda: machine.enable_pressure_regulation()
            or {"regulating_print_pressure": True},
        )

        dialog_state: dict[str, Any] = {}

        def open_calibration() -> Mapping[str, Any]:
            dialog_state["dialog"] = machine.open_calibration_dialog()
            return {"window_title": dialog_state["dialog"].windowTitle()}

        harness.run_action("calibration.open_via_ui", open_calibration)
        calibration = CalibrationDialogDriver(
            context.app,
            dialog_state["dialog"],
            timeout_seconds=min(20.0, context.deadline.remaining_seconds()),
        )
        generated: dict[str, Any] = {}

        def generate() -> Mapping[str, Any]:
            generated.update(calibration.generate_from_tab("droplet"))
            return {
                "result_fingerprint": generated.get(
                    "synthetic_result_fingerprint"
                ),
                "printing_mode": generated.get("printing_mode"),
            }

        harness.run_action("calibration.generate_via_ui", generate)
        fingerprint = str(generated["synthetic_result_fingerprint"])
        harness.run_action(
            "calibration.select_via_ui",
            lambda: calibration.select_result(fingerprint),
        )

        def apply_calibration() -> Mapping[str, Any]:
            preview = calibration.inspect_preview()
            handled = calibration.apply_selected(expected_title="Applied")
            calibration.close()
            return {"preview": preview, "handled_dialogs": handled}

        harness.run_action("calibration.apply_via_ui", apply_calibration)
        _add_assertion(
            harness,
            calibration_assertion(
                context,
                expected_volume_nL=float(stock["droplet_volume_nL"]),
                expected_pulse_width_us=int(head["print_pulse_width_us"]),
                expected_pressure_psi=float(head["print_pressure_psi"]),
            ),
        )

        capture_milestone(context, "ready")

        array = ArrayDriver(context)
        harness.run_action(
            "array.start_via_ui",
            lambda: {"dialogs": array.start()},
        )
        capture_milestone(context, "printing")
        harness.run_action(
            "array.wait_for_completions",
            lambda: _wait_for_terminal(
                harness,
                completed_wells=completed_wells,
                expected_count=len(expected_wells),
            ),
            surface=InteractionSurface.HARNESS,
        )
        capture_milestone(context, "completed")
        _add_assertion(
            harness,
            terminal_execution_assertion(
                context,
                completed_wells=completed_wells,
                expected_well_ids=expected_wells,
            ),
        )
    except BaseException as exc:
        harness.capture_failure(exc)
    finally:
        try:
            teardown = harness.close()
        except BaseException as exc:
            if harness.failure is None:
                harness.capture_failure(exc)
            teardown = {
                "action_id": "scenario.teardown",
                "status": "fail",
                "evidence": {"close_succeeded": False},
            }

    cleanup = cleanup_assertion(teardown)
    harness.add_assertion_result(cleanup.to_dict())
    if cleanup.decision != "pass" and harness.failure is None:
        harness.failure = RuntimeError("required cleanup assertion failed")
    _mark_incomplete_assertions(harness)
    harness.write_ledgers()
    report = _report(
        harness,
        fixture=fixture,
        fixture_path=fixture_path,
        expected_wells=expected_wells,
        completed_wells=completed_wells,
        teardown=teardown,
    )
    write_report_atomic(harness.report_dir / "report.json", report)
    (harness.report_dir / "summary.txt").write_text(
        _summary(report), encoding="utf-8"
    )
    harness.write_evidence_manifest()
    return report


def _wait_for_terminal(
    harness: AutomationHarness,
    *,
    completed_wells: list[str],
    expected_count: int,
) -> dict[str, Any]:
    context = harness.context
    allowed = context.deadline.remaining_seconds()
    deadline = context.clock() + allowed
    while context.clock() < deadline:
        context.pump_events()
        if len(completed_wells) >= int(expected_count):
            break
        context.sleep(0.001)
    if len(completed_wells) != int(expected_count):
        raise RuntimeError(
            f"timed out after {len(completed_wells)} / {expected_count} completions"
        )
    while context.clock() < deadline:
        context.pump_events()
        plan = context.experiment_model.get_execution_plan_snapshot()
        if plan.state.value == "completed" and context.machine.check_if_all_completed():
            return {
                "completed_count": len(completed_wells),
                "plan_state": plan.state.value,
                "queue_drained": True,
            }
        context.sleep(0.001)
    raise RuntimeError("terminal plan/queue state did not settle")


__all__ = [
    "JourneyRunConfig",
    "SMOKE_WORKLOAD_ID",
    "run_virtual_print_array_24_journey",
]
