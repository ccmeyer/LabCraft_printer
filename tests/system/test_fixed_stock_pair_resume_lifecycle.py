"""Real-Qt fixed-pair print, durable stop, fresh load, and resume acceptance."""
from collections import Counter
import json
from pathlib import Path

import pytest

from tools.virtual_workflows.actions import capture_milestone
from tools.virtual_workflows.authoritative_evidence import (
    compare_directories, completed_stock_well_pairs, snapshot_directory,
)
from tools.virtual_workflows.composition import JourneyRuntime
from tools.virtual_workflows.dispense_counts import capture_count_snapshot, intent_and_simulator_counts
from tools.virtual_workflows.execution_observer import ExecutionObserver
from tools.virtual_workflows.harness import AutomationHarness, AutomationHarnessConfig
from tools.virtual_workflows.journey_phases import (
    EditorPreparationSpec, SoftStopResumeSpec, StockPassSpec,
    machine_startup_steps, prepare_persisted_head_for_resume,
    resume_soft_stopped_array, run_editor_preparation, run_soft_stop_boundary,
    run_stock_passes,
)
from tools.virtual_workflows.journeys import AUTHORITATIVE_RELOAD_DEFINITION, _connect_execution_signals
from tools.virtual_workflows.page_drivers import ExperimentLoaderDriver


pytestmark = pytest.mark.sil_lifecycle

HIGH = "Signal_500.00_mM"
LOW = "Signal_5.00_mM"
NAME = "fixed-pair-partial-print-reload"
WELLS = tuple(f"A{i}" for i in range(1, 13))


def _counts(rows):
    return {(row["stock_id"], row["well_id"]): row["droplets"] for row in rows}


def test_fixed_pair_finalize_partial_print_close_reload_resume(qapp, tmp_path):
    harness = AutomationHarness(AutomationHarnessConfig(
        scenario_id=NAME, workload_id=NAME, output_root=tmp_path,
        visible=False, speed_multiplier=100.0, timeout_seconds=240,
    ))
    runtime = JourneyRuntime(
        definition=AUTHORITATIVE_RELOAD_DEFINITION, harness=harness,
        fixture={}, fixture_path=Path(__file__),
    )
    evidence = {"status": "running", "stock_ids": [HIGH, LOW], "well_ids": list(WELLS)}
    expected = {(stock, well): count for stock, count in ((HIGH, 1), (LOW, 3)) for well in WELLS}

    def install_observer(name, directory=None):
        observer = ExecutionObserver(
            runtime.context,
            experiment_dir=Path(directory or runtime.context.experiment_model.experiment_dir_path),
            completed_count=lambda: len(runtime.observations.get("completed_wells", [])),
            pass_context=lambda: dict(runtime.observations.get("current_pass", {})),
        )
        runtime.observations["execution_observer"] = observer
        runtime.register_restorable(name, observer)
        observer.install()

    def verify_counts(snapshot, added=None):
        for source in ("plan_targets", "progress_targets", "runtime_targets"):
            assert _counts(snapshot[source]) == expected, (source, snapshot)
        if added is not None:
            assert _counts(snapshot["progress_added"]) == added

    def rotate_during_low_pass(_runtime, stock_spec):
        if stock_spec.stock_id != LOW:
            return
        run_soft_stop_boundary(runtime, SoftStopResumeSpec(
            request_after_completion_count=15, maximum_completion_catchup=2,
            quiescence_observation_ms=250,
        ))
        paused = capture_count_snapshot(runtime.context)
        verify_counts(paused)
        saved = _counts(paused["progress_added"])
        assert all(saved[(HIGH, well)] == 1 for well in WELLS)
        low_counts = [saved[(LOW, well)] for well in WELLS]
        assert all(value in (0, 3) for value in low_counts)
        assert 0 < sum(low_counts) < 36
        quiet = runtime.observations["stopped_quiescence"]
        assert quiet["starting_completion_count"] == quiet["ending_completion_count"]
        assert quiet["starting_progress_count"] == quiet["ending_progress_count"]
        assert quiet["simulator_queue_empty"]
        evidence["paused"] = paused
        directory = Path(runtime.context.experiment_model.experiment_dir_path)
        before_close = snapshot_directory(directory)
        runtime.restore_all()
        first_lifecycle = runtime.observations["session_1_snapshot"]["lifecycle"]
        evidence["session_1_lifecycle"] = first_lifecycle
        evidence["close"] = harness.close_application_session()["evidence"]
        evidence["close_files"] = compare_directories(before_close, snapshot_directory(directory)).to_dict()
        assert evidence["close_files"]["checks"]["files_byte_identical"]
        harness.reopen_application_session()
        _connect_execution_signals(runtime, array_complete=True, machine_errors=True)
        install_observer("session_2", directory)

        def validate_load():
            loaded = capture_count_snapshot(runtime.context, include_runtime=False)
            assert loaded["plan_id"] == paused["plan_id"]
            assert loaded["plan_revision"] == paused["plan_revision"]
            assert _counts(loaded["progress_added"]) == saved
            evidence["loaded"] = loaded
            return {"stock_progress_identical": True}

        def validate_activation():
            activated = capture_count_snapshot(runtime.context)
            verify_counts(activated, saved)
            option = runtime.context.experiment_model.factors[0].options[0]
            assert option.forced_stock_concs == (500.0, 5.0)
            assert option.forced_stock_conc is None
            evidence["activated"] = activated
            return {"stock_progress_identical": True, "fixed_pair_preserved": True}

        ExperimentLoaderDriver(runtime.context).load_authoritative_execution(
            directory, expected_name=NAME,
            before_activation=validate_load, after_activation=validate_activation,
        )
        runtime.run_steps(machine_startup_steps())
        prepare_persisted_head_for_resume(runtime, stock_spec)
        # Restaging a calibrated head must not consume or reset stock progress.
        verify_counts(capture_count_snapshot(runtime.context), saved)
        resume_soft_stopped_array(runtime, milestone_name="reopened_resumed")

    try:
        harness.start()
        runtime.run_steps(machine_startup_steps())
        run_editor_preparation(runtime, EditorPreparationSpec({
            "experiment": {
                "name": NAME, "plate_name": "shallow-384_well_plate",
                "replicates": 12, "expected_reaction_count": 12,
                "expected_well_ids": list(WELLS), "printed_volume_nL": 36.0,
                "final_volume_nL": 1000.0, "printed_volume_tolerance_nL": 0.0,
                "randomize_assignments": False, "allow_two_stock_solutions": False,
                "fill_droplet_volume_nL": 9.0,
            },
            "reagent": {
                "stock_label": "Signal", "group": "Additive", "printing_mode": "droplet",
                "starting_concentration": 0.0, "targets": [4.635], "units": "mM",
                "fixed_stock_concentration": "5, 500", "droplet_volume_nL": 9.0,
            },
        }, capture_editor_milestones=False))
        evidence["prepared"] = capture_count_snapshot(runtime.context)
        verify_counts(evidence["prepared"], {key: 0 for key in expected})
        capture_milestone(runtime.context, "fixed_pair_prepared")
        _connect_execution_signals(runtime, array_complete=True, machine_errors=True)
        install_observer("session_1")
        specs = tuple(StockPassSpec(
            stock_id=stock, printer_head_id=f"fixed-pair-head-{index}",
            pulse_width_us=1300, pressure_psi=1.2, frequency_hz=20,
            initial_volume_uL=100.0, expected_volume_nL=9.0,
            expected_completion_count=12 * index,
            expected_plan_state="active" if index == 1 else "completed",
            ready_milestone=f"stock_{index}_ready", printing_milestone=f"stock_{index}_printing",
            completed_milestone=f"stock_{index}_completed", staging_slot=index - 1,
            start_dialog_titles=("Start Print Array", "Evaporation Plate Dock Check") if index == 1 else ("Start Print Array",),
            bind_identity=True, enable_pressure_regulation=index == 1,
            return_head=index == 1,
        ) for index, stock in enumerate((HIGH, LOW), 1))
        run_stock_passes(runtime, specs, active_phase=rotate_during_low_pass)
        terminal = capture_count_snapshot(runtime.context)
        verify_counts(terminal, expected)
        assert terminal["plan_state"] == "completed"
        capture_milestone(runtime.context, "fixed_pair_completed")
        runtime.restore_all()
        second_lifecycle = runtime.observations["session_2_snapshot"]["lifecycle"]
        first_lifecycle = evidence["session_1_lifecycle"]
        first_pairs = completed_stock_well_pairs(first_lifecycle)
        second_pairs = completed_stock_well_pairs(second_lifecycle)
        assert not first_pairs & second_pairs
        assert first_pairs | second_pairs == set(expected)
        # Join command sequences within each application session; sequence numbers
        # can legitimately restart in the fresh simulator.
        actual = Counter()
        session_commands = []
        for lifecycle in (first_lifecycle, second_lifecycle):
            done = set(lifecycle["completions"])
            completed_attachments = [row for row in lifecycle["attachments"] if row["intent_id"] in done]
            sequences = {row["command_seq32"] for row in completed_attachments}
            # Soft stop clears queued lookahead commands. They must not be
            # counted as printed, and none may have completed in the simulator.
            not_completed = [row for row in lifecycle["simulator_dispenses"] if row["command_seq32"] not in sequences]
            assert all(row["status"] != "Completed" for row in not_completed)
            completed_lifecycle = {
                **lifecycle,
                "begins": [row for row in lifecycle["begins"] if row["intent_id"] in done],
                "attachments": completed_attachments,
                "simulator_dispenses": [row for row in lifecycle["simulator_dispenses"] if row["command_seq32"] in sequences],
            }
            intent_counts, simulator_counts, commands = intent_and_simulator_counts(completed_lifecycle)
            assert intent_counts == simulator_counts
            actual.update({(row.stock_id, row.well_id): row.droplets for row in simulator_counts})
            session_commands.append(commands)
        assert dict(actual) == expected
        assert len(first_pairs) + len(second_pairs) == 24
        assert not runtime.context.errors
        evidence.update(status="passed", terminal=terminal,
                        session_2_lifecycle=second_lifecycle,
                        simulator_commands=session_commands,
                        no_completed_stock_well_replayed=True,
                        total_dispensed_droplets=sum(actual.values()),
                        report_directory=str(harness.report_dir),
                        session_root=str(harness.scenario_root))
    except BaseException as exc:
        harness.failure = exc
        evidence.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        runtime.restore_all()
        evidence["cleanup"] = harness.close()
        harness.write_ledgers()
        (harness.report_dir / "fixed_pair_resume_evidence.json").write_text(
            json.dumps(evidence, indent=2, default=str), encoding="utf-8",
        )
        harness.write_evidence_manifest()
        print(f"Fixed-pair resume evidence: {harness.report_dir}")
