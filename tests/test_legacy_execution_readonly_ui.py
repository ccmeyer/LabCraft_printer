from types import SimpleNamespace
from unittest.mock import Mock

from View import ExperimentDesignDialog


def _read_only_model():
    return SimpleNamespace(is_read_only_legacy_execution=lambda: True)


def test_read_only_snapshot_suppresses_silent_recompute():
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.model = _read_only_model()
    dialog._run_design_optimization_flow = Mock()

    ExperimentDesignDialog._recompute_silent(dialog)

    dialog._run_design_optimization_flow.assert_not_called()


def test_read_only_snapshot_suppresses_explicit_optimization():
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.model = _read_only_model()
    dialog._set_status = Mock()
    dialog._rebuild_model_from_table = Mock()

    ok, result = ExperimentDesignDialog._run_design_optimization_flow(dialog)

    assert ok is False
    assert result["read_only"] is True
    dialog._rebuild_model_from_table.assert_not_called()
    dialog._set_status.assert_called_once()


def test_read_only_snapshot_blocks_save_and_finish_actions():
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.model = _read_only_model()
    dialog._set_status = Mock()
    dialog._run_design_optimization_flow = Mock()
    dialog._editing_locked_by_gripper = False

    ExperimentDesignDialog._on_save_design(dialog)
    ExperimentDesignDialog._on_finish(dialog)

    dialog._run_design_optimization_flow.assert_not_called()
    assert dialog._set_status.call_count == 2


def test_active_execution_lock_uses_same_editor_mutation_guards():
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.model = SimpleNamespace(
        is_execution_design_locked=lambda: True,
        is_read_only_legacy_execution=lambda: False,
    )
    dialog._set_status = Mock()
    dialog._run_design_optimization_flow = Mock()
    dialog._editing_locked_by_gripper = False

    ExperimentDesignDialog._recompute_silent(dialog)
    ExperimentDesignDialog._on_save_design(dialog)
    ExperimentDesignDialog._on_finish(dialog)

    dialog._run_design_optimization_flow.assert_not_called()
    assert dialog._set_status.call_count == 2


def test_legacy_conversion_is_not_exposed_by_the_experiment_editor():
    assert not hasattr(ExperimentDesignDialog, "_on_migrate_legacy_copy")
