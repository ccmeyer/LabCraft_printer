import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import Model as model_module
from Controller import Controller
from Model import ExperimentModel, Model
from hardware.profile import CURRENT_PROFILE


def _calibration_manager_stub():
    return SimpleNamespace(
        set_calibration_storage_policy=Mock(),
        update_calibration_file_path=Mock(),
        update_calibration_storage_paths=Mock(),
        begin_session=Mock(),
    )


def _host_model(tmp_path, *, gripper_head=None):
    experiments_root = tmp_path / "experiments"
    experiments_root.mkdir()
    prior_dir = experiments_root / "prior"
    prior_dir.mkdir()
    (prior_dir / "sentinel.txt").write_text("prior-session\n", encoding="utf-8")

    calibration_manager = _calibration_manager_stub()
    active = ExperimentModel(
        prof=CURRENT_PROFILE,
        experiments_root=experiments_root,
    )
    active.metadata["name"] = "prior"
    active.experiment_dir_path = str(prior_dir)
    active.update_all_paths()
    active._uploaded_reactions = [{("Drug", None): 1.0}]
    active._uploaded_design_source = "prior.csv"
    active._uploaded_well_ids = ["A1"]
    active.progress_data = {"A1": {"reagents": {"stock": {"added_droplets": 1}}}}
    active._execution_plan_snapshot = object()
    active.unsaved_changes = True
    active.set_calibration_manager(calibration_manager)

    host = Model.__new__(Model)
    host.profile = CURRENT_PROFILE
    host.experiments_root = experiments_root
    host.experiment_model = active
    host.calibration_manager = calibration_manager
    host.stock_solutions = SimpleNamespace(clear_all_stock_solutions=Mock())
    host.reaction_collection = SimpleNamespace(clear_all_reactions=Mock())
    host.well_plate = SimpleNamespace(clear_all_wells=Mock())
    host.rack_model = SimpleNamespace(
        get_gripper_printer_head=Mock(return_value=gripper_head),
        clear_all_slots=Mock(),
    )
    calibration_chip = object()
    host.printer_head_manager = SimpleNamespace(
        clear_all_printer_heads=Mock(),
        create_calibration_chip=Mock(),
        get_calibration_chip=Mock(return_value=calibration_chip),
        swap_printer_head=Mock(),
    )
    host.experiment_loaded = SimpleNamespace(emit=Mock())
    host._rack_runtime_plan_id = "prior-plan"
    host._read_only_experiment_view_active = True
    host._read_only_experiment_display_heads = ("head",)
    host._completed_execution_view_active = True
    host._completed_execution_display_heads = ("head",)

    for value in vars(calibration_manager).values():
        value.reset_mock()
    return host, prior_dir


def test_fresh_session_creation_uses_collision_suffixes_without_touching_existing(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(model_module.time, "strftime", lambda *_args, **_kwargs: "20260102_030405")
    expected_names = [
        "Untitled-20260102_030405",
        "Untitled-20260102_030405-2",
        "Untitled-20260102_030405-3",
    ]

    created = []
    for expected_name in expected_names:
        experiment = ExperimentModel(
            prof=CURRENT_PROFILE,
            experiments_root=tmp_path,
        )
        created_path = Path(experiment.initialize_new_experiment_session())
        created.append(created_path)
        assert created_path.name == expected_name
        assert experiment.metadata["name"] == expected_name
        assert json.loads(
            (created_path / "experiment_design.json").read_text(encoding="utf-8")
        )["metadata"]["name"] == expected_name
        assert json.loads(
            (created_path / "progress.json").read_text(encoding="utf-8")
        ) == {}

        if len(created) == 1:
            (created_path / "sentinel.txt").write_text(
                "keep-first\n",
                encoding="utf-8",
            )

    assert (created[0] / "sentinel.txt").read_text(encoding="utf-8") == "keep-first\n"


@pytest.mark.parametrize(
    "failure_stage",
    ["directory", "design", "progress", "validation"],
)
def test_preparation_failure_preserves_prior_session_and_cleans_owned_output(
    monkeypatch,
    tmp_path,
    failure_stage,
):
    host, prior_dir = _host_model(tmp_path)
    active = host.experiment_model
    previous_design = copy.deepcopy(active.to_dict())
    previous_progress = copy.deepcopy(active.progress_data)
    previous_plan = active._execution_plan_snapshot

    method_name = {
        "directory": "_reserve_new_experiment_directory",
        "design": "save_experiment",
        "progress": "create_progress_file",
        "validation": "_validate_new_experiment_session_files",
    }[failure_stage]

    def fail_stage(*_args, **_kwargs):
        raise OSError(f"{failure_stage} failed")

    monkeypatch.setattr(ExperimentModel, method_name, fail_stage)

    with pytest.raises(OSError, match=f"{failure_stage} failed"):
        host.start_new_experiment_session(
            array_runner_idle=True,
            command_queue_empty=True,
        )

    assert host.experiment_model is active
    assert active.to_dict() == previous_design
    assert active.progress_data == previous_progress
    assert active._execution_plan_snapshot is previous_plan
    assert active.experiment_dir_path == str(prior_dir)
    assert (prior_dir / "sentinel.txt").read_text(encoding="utf-8") == "prior-session\n"
    assert sorted(path.name for path in host.experiments_root.iterdir()) == ["prior"]
    host.stock_solutions.clear_all_stock_solutions.assert_not_called()
    host.reaction_collection.clear_all_reactions.assert_not_called()
    host.well_plate.clear_all_wells.assert_not_called()
    host.rack_model.clear_all_slots.assert_not_called()
    host.printer_head_manager.clear_all_printer_heads.assert_not_called()
    host.calibration_manager.begin_session.assert_not_called()
    host.experiment_loaded.emit.assert_not_called()


def test_cleanup_failure_reports_residual_candidate_path(monkeypatch, tmp_path):
    experiment = ExperimentModel(
        prof=CURRENT_PROFILE,
        experiments_root=tmp_path,
    )
    monkeypatch.setattr(
        experiment,
        "save_experiment",
        Mock(side_effect=OSError("design failed")),
    )
    monkeypatch.setattr(
        model_module.shutil,
        "rmtree",
        Mock(side_effect=OSError("cleanup failed")),
    )

    with pytest.raises(RuntimeError, match="incomplete folder could not be removed") as error:
        experiment.initialize_new_experiment_session()

    residual = Path(experiment.experiment_dir_path)
    assert residual.exists()
    assert str(residual) in str(error.value)
    assert "cleanup failed" in str(error.value)


def test_runtime_clear_failure_removes_candidate_and_preserves_active_model(
    tmp_path,
):
    host, prior_dir = _host_model(tmp_path)
    active = host.experiment_model
    host._clear_runtime_experiment_without_signal = Mock(
        side_effect=RuntimeError("runtime clear failed")
    )

    with pytest.raises(RuntimeError, match="runtime clear failed"):
        host.start_new_experiment_session(
            array_runner_idle=True,
            command_queue_empty=True,
        )

    assert host.experiment_model is active
    assert active.experiment_dir_path == str(prior_dir)
    assert sorted(path.name for path in host.experiments_root.iterdir()) == ["prior"]
    host.experiment_loaded.emit.assert_not_called()


def test_successful_new_session_commits_after_preparation_and_emits_once(tmp_path):
    host, prior_dir = _host_model(tmp_path)
    active = host.experiment_model

    created_path = Path(
        host.start_new_experiment_session(
            array_runner_idle=True,
            command_queue_empty=True,
        )
    )

    assert host.experiment_model is active
    assert created_path.is_dir()
    assert active.experiment_dir_path == str(created_path)
    assert active.metadata["name"] == created_path.name
    assert active.factors == []
    assert active.additional_conditions == []
    assert active.has_uploaded_design() is False
    assert active._uploaded_well_ids is None
    assert active.progress_data == {}
    assert active.is_execution_design_locked() is False
    assert active.unsaved_changes is False
    assert json.loads((created_path / "progress.json").read_text(encoding="utf-8")) == {}
    assert (prior_dir / "sentinel.txt").read_text(encoding="utf-8") == "prior-session\n"

    host.stock_solutions.clear_all_stock_solutions.assert_called_once_with()
    host.reaction_collection.clear_all_reactions.assert_called_once_with()
    host.well_plate.clear_all_wells.assert_called_once_with()
    host.rack_model.clear_all_slots.assert_called_once_with()
    host.printer_head_manager.clear_all_printer_heads.assert_called_once_with()
    host.printer_head_manager.create_calibration_chip.assert_called_once_with()
    host.printer_head_manager.swap_printer_head.assert_called_once_with(
        4,
        host.printer_head_manager.get_calibration_chip.return_value,
    )
    host.calibration_manager.begin_session.assert_called_once_with(
        active.calibration_file_path
    )
    host.experiment_loaded.emit.assert_called_once_with()


@pytest.mark.parametrize(
    ("array_runner_idle", "command_queue_empty", "gripper_head", "message"),
    [
        (False, True, None, "array runner is active"),
        (True, False, None, "commands are queued"),
        (True, True, object(), "Remove the printer head"),
    ],
)
def test_model_safety_interlocks_run_before_session_preparation(
    monkeypatch,
    tmp_path,
    array_runner_idle,
    command_queue_empty,
    gripper_head,
    message,
):
    host, _prior_dir = _host_model(tmp_path, gripper_head=gripper_head)
    prepare = Mock(side_effect=AssertionError("preparation must not start"))
    monkeypatch.setattr(
        ExperimentModel,
        "initialize_new_experiment_session",
        prepare,
    )

    with pytest.raises(RuntimeError, match=message):
        host.start_new_experiment_session(
            array_runner_idle=array_runner_idle,
            command_queue_empty=command_queue_empty,
        )

    prepare.assert_not_called()


def _controller_for_new_session(
    array_state,
    *,
    command_queue_empty=True,
    soft_stop_clear_uncertain=False,
    backend_error=None,
):
    controller = Controller.__new__(Controller)
    controller._array_state = array_state
    controller._array_context = {"prior": True}
    controller._soft_stop_clear_uncertain = soft_stop_clear_uncertain
    controller.array_state_changed = SimpleNamespace(emit=Mock())
    controller.check_if_all_completed = Mock(return_value=command_queue_empty)

    def start_session(**kwargs):
        if backend_error is not None:
            raise backend_error
        if not kwargs["array_runner_idle"]:
            raise RuntimeError("array runner is active")
        if not kwargs["command_queue_empty"]:
            raise RuntimeError("commands are queued")
        return "new-session"

    controller.model = SimpleNamespace(
        start_new_experiment_session=Mock(side_effect=start_session)
    )
    return controller


@pytest.mark.parametrize("array_state", ["idle", "resume_ready"])
def test_controller_accepts_quiescent_states_and_normalizes_success_to_idle(
    array_state,
):
    controller = _controller_for_new_session(array_state)

    assert controller.start_new_experiment_session(base_dir="root") == "new-session"

    controller.model.start_new_experiment_session.assert_called_once_with(
        array_runner_idle=True,
        command_queue_empty=True,
        base_dir="root",
    )
    assert controller.get_array_run_state() == "idle"
    assert controller._array_context is None


@pytest.mark.parametrize(
    ("array_state", "command_queue_empty", "soft_stop_clear_uncertain", "message"),
    [
        ("running", True, False, "array runner is active"),
        ("stop_requested", True, False, "array runner is active"),
        ("resume_ready", True, True, "array runner is active"),
        ("idle", False, False, "commands are queued"),
    ],
)
def test_controller_rejected_states_preserve_state_and_context(
    array_state,
    command_queue_empty,
    soft_stop_clear_uncertain,
    message,
):
    controller = _controller_for_new_session(
        array_state,
        command_queue_empty=command_queue_empty,
        soft_stop_clear_uncertain=soft_stop_clear_uncertain,
    )
    prior_context = controller._array_context

    with pytest.raises(RuntimeError, match=message):
        controller.start_new_experiment_session()

    assert controller.get_array_run_state() == array_state
    assert controller._array_context is prior_context


def test_controller_backend_failure_preserves_resume_ready_state():
    controller = _controller_for_new_session(
        "resume_ready",
        backend_error=OSError("disk unavailable"),
    )
    prior_context = controller._array_context

    with pytest.raises(OSError, match="disk unavailable"):
        controller.start_new_experiment_session()

    assert controller.get_array_run_state() == "resume_ready"
    assert controller._array_context is prior_context
    controller.array_state_changed.emit.assert_not_called()
