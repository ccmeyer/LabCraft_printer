from types import SimpleNamespace
from unittest.mock import Mock

import View
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


class _FakeSignal:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback


class _FakeMigrationWorker:
    instances = []

    def __init__(self, source, parent=None):
        self.source = source
        self.parent = parent
        self.failed = _FakeSignal()
        self.succeeded = _FakeSignal()
        self.finished = _FakeSignal()
        self.started = False
        self.cancel = Mock()
        self.instances.append(self)

    def start(self):
        self.started = True

    def deleteLater(self):
        pass


class _FakeProgressDialog:
    def __init__(self, *_args, **_kwargs):
        self.canceled = _FakeSignal()
        self.shown = False

    def setWindowTitle(self, _title):
        pass

    def setWindowModality(self, _modality):
        pass

    def setMinimumDuration(self, _duration):
        pass

    def show(self):
        self.shown = True

    def close(self):
        pass


def _migration_dialog():
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.model = SimpleNamespace(
        experiment_dir_path="C:/experiments/legacy",
        is_read_only_legacy_execution=lambda: True,
    )
    dialog._set_status = Mock()
    return dialog


def test_migrate_legacy_copy_no_response_does_not_start_worker(monkeypatch):
    dialog = _migration_dialog()
    _FakeMigrationWorker.instances.clear()
    monkeypatch.setattr(
        View.QMessageBox,
        "question",
        lambda *_args, **_kwargs: View.QMessageBox.No,
    )
    monkeypatch.setattr(View, "LegacyExecutionMigrationWorker", _FakeMigrationWorker)

    ExperimentDesignDialog._on_migrate_legacy_copy(dialog)

    assert _FakeMigrationWorker.instances == []


def test_migrate_legacy_copy_yes_response_starts_worker(monkeypatch):
    dialog = _migration_dialog()
    _FakeMigrationWorker.instances.clear()
    monkeypatch.setattr(
        View.QMessageBox,
        "question",
        lambda *_args, **_kwargs: View.QMessageBox.Yes,
    )
    monkeypatch.setattr(View, "LegacyExecutionMigrationWorker", _FakeMigrationWorker)
    monkeypatch.setattr(View.QtWidgets, "QProgressDialog", _FakeProgressDialog)

    ExperimentDesignDialog._on_migrate_legacy_copy(dialog)

    assert len(_FakeMigrationWorker.instances) == 1
    worker = _FakeMigrationWorker.instances[0]
    assert worker.source == "C:/experiments/legacy"
    assert worker.started is True
    assert dialog._legacy_migration_progress.shown is True
