from __future__ import annotations

from types import SimpleNamespace

from tools.virtual_workflows.execution_observer import ExecutionObserver


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
