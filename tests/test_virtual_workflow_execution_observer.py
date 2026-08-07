from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

from tools.virtual_workflows.execution_observer import (
    ExecutionObserver,
    capture_execution_liveness_snapshot,
)
from tools.virtual_workflows.regression_evidence import (
    active_pressure_render_intervals_ms,
)


def test_execution_observer_installs_and_restores_every_hook(tmp_path, monkeypatch):
    restored = []

    class Instrumentation:
        def restore(self):
            restored.append("instrumentation")

        def lifecycle_snapshot(self):
            return {
                "begins": [],
                "attachments": [],
                "completions": [],
                "discard_batches": [],
                "checkpoint_observations": [],
                "pass_starts": [],
                "terminal_transitions": [],
                "soft_stop_events": [{"event": "watermark_observed"}],
            }

    from tools.virtual_workflows import scenarios

    monkeypatch.setattr(
        scenarios,
        "_install_instrumentation",
        lambda *_args, **_kwargs: Instrumentation(),
    )
    context = SimpleNamespace(
        experiment_model=SimpleNamespace(),
        controller=SimpleNamespace(),
        view=SimpleNamespace(
            well_plate_widget=SimpleNamespace(),
            pressure_box=SimpleNamespace(),
            experiment_task_list=SimpleNamespace(),
        ),
        instrumentation=None,
        io_observer=None,
        progress_observer=None,
    )
    observer = ExecutionObserver(
        context,
        experiment_dir=tmp_path,
        completed_count=lambda: 0,
    )
    observer.install()
    assert observer.snapshot()["installed"] is True
    observer.restore()
    observer.restore()
    snapshot = observer.snapshot()
    assert snapshot["installed"] is False
    assert snapshot["restored"] is True
    assert snapshot["progress_snapshot"]["observer_restored"] is True
    assert snapshot["authoritative_reads"]["observer_restored"] is True
    assert snapshot["lifecycle"]["soft_stop_events"] == [
        {"event": "watermark_observed"}
    ]
    assert restored == ["instrumentation"]


def test_liveness_snapshot_is_bounded_serializable_and_read_only(tmp_path, monkeypatch):
    class Timer:
        def isActive(self):
            return True

        def remainingTime(self):
            return 7

    commands = [
        SimpleNamespace(command_number=index, command_type="WAIT", status="Accepted")
        for index in range(1, 8)
    ]
    intents = [
        SimpleNamespace(
            intent_id=f"intent-{index}", well_id=f"A{index}", stock_id="stock-a",
            status="pending", command_seq32=index,
        )
        for index in range(1, 7)
    ]
    checkpoint_loader = Mock(return_value=SimpleNamespace(state="dirty", intents=intents))
    from ExecutionResumeStore import load_execution_resume
    monkeypatch.setattr("ExecutionResumeStore.load_execution_resume", checkpoint_loader)
    assert load_execution_resume is not checkpoint_loader

    plan_getter = Mock(return_value=SimpleNamespace(state=SimpleNamespace(value="active"), revision=5))
    sync_getter = Mock(return_value=None)
    controller = SimpleNamespace(
        _array_context={
            "finalize_reason": None,
            "current_barrier_seq32": 44,
            "queued_wells": [
                {
                    "well_id": f"A{index}", "target_droplets": 1,
                    "dispense_seq32": index, "execution_intent_id": f"intent-{index}",
                }
                for index in range(1, 5)
            ],
        },
        get_array_run_state=Mock(return_value="running"),
    )
    state = SimpleNamespace(
        connected=True, transport_paused=False, current_command=2,
        last_completed=1, last_accepted=7, last_retired=1,
    )
    context = SimpleNamespace(
        controller=controller,
        machine=SimpleNamespace(
            command_queue=SimpleNamespace(queue=commands),
            state=state,
            _command_timer=Timer(),
            _active_command=commands[0],
            _sequence_pause=False,
            _completing=True,
        ),
        experiment_model=SimpleNamespace(
            execution_resume_file_path=tmp_path / "execution_resume.json",
            get_execution_plan_snapshot=plan_getter,
            get_execution_plan_sync_error=sync_getter,
        ),
        model=SimpleNamespace(
            rack_model=SimpleNamespace(
                get_gripper_printer_head=Mock(return_value=SimpleNamespace(
                    printer_head_id="head-a"
                ))
            )
        ),
        probe=SimpleNamespace(snapshot=lambda: {"maximum_gap_ms": 321.0}),
    )

    snapshot = capture_execution_liveness_snapshot(
        context,
        completed_count=1656,
        target_count=1920,
        stalled_seconds=120.5,
        pass_context={"pass_index": 5, "stock_id": "stock-a"},
    )

    json.dumps(snapshot, allow_nan=False)
    assert len(snapshot["controller"]["queued_wells"]) == 2
    assert len(snapshot["simulator"]["nonterminal_commands"]) == 4
    assert snapshot["execution"]["checkpoint"]["pending_intent_count"] == 6
    assert len(snapshot["execution"]["checkpoint"]["pending_intents"]) == 4
    assert snapshot["pass"]["head_id"] == "head-a"
    checkpoint_loader.assert_called_once_with(tmp_path / "execution_resume.json")
    plan_getter.assert_called_once_with()
    sync_getter.assert_called_once_with()
    controller.get_array_run_state.assert_called_once_with()


def test_liveness_snapshot_survives_missing_partial_components():
    snapshot = capture_execution_liveness_snapshot(
        SimpleNamespace(),
        completed_count=0,
        target_count=1,
        stalled_seconds=3.0,
    )

    json.dumps(snapshot, allow_nan=False)
    assert snapshot["controller"]["array_state"] is None
    assert snapshot["simulator"]["queue_depth"] == 0
    assert snapshot["execution"]["checkpoint"]["available"] is False


def test_pressure_render_intervals_exclude_inactive_stock_pass_boundaries():
    intervals, excluded = active_pressure_render_intervals_ms(
        [
            {"pass_index": 0, "timestamp_ns": 100_000_000},
            {"pass_index": 0, "timestamp_ns": 250_000_000},
            # Three seconds of head exchange/calibration is outside active rendering.
            {"pass_index": 1, "timestamp_ns": 3_250_000_000},
            {"pass_index": 1, "timestamp_ns": 3_400_000_000},
        ]
    )

    assert intervals == [150.0, 150.0]
    assert excluded == 1
