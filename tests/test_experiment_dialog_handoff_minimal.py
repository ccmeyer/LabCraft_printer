from types import SimpleNamespace
from unittest.mock import Mock

from View import ExperimentDesignDialog, MainWindow


def test_complete_experiment_design_calls_model_load_from_model():
    main_window = MainWindow.__new__(MainWindow)
    load_mock = Mock()
    main_window.model = SimpleNamespace(
        load_experiment_from_model=load_mock,
        experiment_model=SimpleNamespace(metadata={"plate_name": "96well-8x12"}),
    )

    MainWindow.complete_experiment_design(main_window)

    load_mock.assert_called_once_with(
        plate_name="96well-8x12",
        load_progress=False,
        finalize_execution_plan=True,
    )


def test_complete_experiment_design_can_preserve_progress_for_resume():
    main_window = MainWindow.__new__(MainWindow)
    load_mock = Mock()
    main_window.model = SimpleNamespace(
        load_experiment_from_model=load_mock,
        experiment_model=SimpleNamespace(metadata={"plate_name": "96well-8x12"}),
    )

    MainWindow.complete_experiment_design(main_window, load_progress=True)

    load_mock.assert_called_once_with(
        plate_name="96well-8x12",
        load_progress=True,
        finalize_execution_plan=False,
    )


def test_complete_experiment_design_uses_transactional_prepared_commit(
    tmp_path,
):
    main_window = MainWindow.__new__(MainWindow)
    plan_path = tmp_path / "execution_plan.json"
    plan_path.write_text("{}", encoding="utf-8")
    commit_mock = Mock(return_value={"status": "replaced"})
    load_mock = Mock()
    main_window.model = SimpleNamespace(
        commit_prepared_experiment_design_from_editor=commit_mock,
        load_experiment_from_model=load_mock,
        experiment_model=SimpleNamespace(
            metadata={"plate_name": "96well-8x12"},
            execution_plan_file_path=str(plan_path),
        ),
    )

    result = MainWindow.complete_experiment_design(
        main_window,
        requested_name="prepared-edited",
    )

    assert result == {"status": "replaced"}
    commit_mock.assert_called_once_with(requested_name="prepared-edited")
    load_mock.assert_not_called()


def test_view_completed_execution_requires_idle_queue_and_only_projects_display():
    main_window = MainWindow.__new__(MainWindow)
    project = Mock(return_value={"status": "analysis_only"})
    main_window.model = SimpleNamespace(load_completed_execution_view=project)
    main_window.controller = SimpleNamespace(
        get_array_run_state=Mock(return_value="idle"),
        check_if_all_completed=Mock(return_value=True),
        _set_array_run_state=Mock(),
    )

    result = MainWindow.view_completed_execution(main_window)

    assert result == {"status": "analysis_only"}
    project.assert_called_once_with()
    main_window.controller._set_array_run_state.assert_not_called()


def test_view_completed_execution_rejects_nonidle_controller_without_projection():
    main_window = MainWindow.__new__(MainWindow)
    project = Mock()
    main_window.model = SimpleNamespace(load_completed_execution_view=project)
    main_window.controller = SimpleNamespace(
        get_array_run_state=Mock(return_value="resume_ready"),
        check_if_all_completed=Mock(return_value=True),
    )

    try:
        MainWindow.view_completed_execution(main_window)
    except RuntimeError as exc:
        assert "array runner is idle" in str(exc)
    else:
        raise AssertionError("non-idle completed view was accepted")

    project.assert_not_called()


def _dialog_for_progress_policy(prompt_policy):
    dialog = ExperimentDesignDialog.__new__(ExperimentDesignDialog)
    dialog.model = SimpleNamespace(
        get_progress_status=Mock(
            return_value={
                "has_printed_progress": True,
                "total_added_droplets": 3,
                "wells_with_progress": 2,
            }
        ),
        clear_progress_for_design_edit=Mock(),
    )
    dialog._prompt_progress_policy = Mock(return_value=prompt_policy)
    dialog._set_status = Mock()
    dialog._refresh_all_lock_states = Mock()
    dialog._progress_protected = False
    dialog._preserve_progress_on_finish = False
    dialog._progress_reset_confirmed = False
    dialog._progress_lock_status_message = ""
    dialog._progress_status_message = (
        ExperimentDesignDialog._progress_status_message.__get__(
            dialog, ExperimentDesignDialog
        )
    )
    dialog._set_progress_protection = (
        ExperimentDesignDialog._set_progress_protection.__get__(
            dialog, ExperimentDesignDialog
        )
    )
    dialog.prepare_progress_policy_for_current_design = (
        ExperimentDesignDialog.prepare_progress_policy_for_current_design.__get__(
            dialog, ExperimentDesignDialog
        )
    )
    return dialog


def test_prepare_progress_policy_reset_clears_progress_and_allows_editing():
    dialog = _dialog_for_progress_policy(ExperimentDesignDialog.PROGRESS_POLICY_RESET)

    assert dialog.prepare_progress_policy_for_current_design() is True

    dialog.model.clear_progress_for_design_edit.assert_called_once_with()
    assert dialog._progress_protected is False
    assert dialog._preserve_progress_on_finish is False
    assert dialog._progress_reset_confirmed is True


def test_prepare_progress_policy_resume_preserves_progress_and_locks_editing():
    dialog = _dialog_for_progress_policy(ExperimentDesignDialog.PROGRESS_POLICY_RESUME)

    assert dialog.prepare_progress_policy_for_current_design() is True

    dialog.model.clear_progress_for_design_edit.assert_not_called()
    assert dialog._progress_protected is True
    assert dialog._preserve_progress_on_finish is True
    assert dialog._progress_reset_confirmed is False
