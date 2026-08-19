from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6 import QtWidgets

import MachineDataBootstrap
import MachineDataBootstrapDialog
import MachineDataMigration
from machine_data_migration_helpers import inspect_wrapper, machine_data_paths, write_wrapper


class FakeBootstrap:
    def __init__(self, inspection, candidate=None):
        self.inspection = inspection
        self.candidate = candidate
        self.submissions = []
        self.cancel_calls = 0

    def inspect(self):
        return self.inspection

    def inspect_candidate(self, selection):
        self.selection = selection
        if self.candidate is None:
            raise RuntimeError("no candidate configured")
        return self.candidate

    def bootstrap_from_candidate(self, submission):
        self.submissions.append(submission)
        return SimpleNamespace(kind="authorized")

    def activate_published(self, submission):
        self.submissions.append(submission)
        return SimpleNamespace(kind="resumed")

    def open_ready(self):
        return SimpleNamespace(kind="ready")

    def request_cancel(self):
        self.cancel_calls += 1


def _inspection(tmp_path, state, *, machine_paths_value=None, issues=()):
    base, _paths = machine_data_paths(tmp_path)
    return MachineDataBootstrap.BootstrapInspection(
        state,
        base,
        machine_paths=machine_paths_value,
        issues=tuple(issues),
    )


def _candidate(tmp_path, *, custom_camera=True):
    wrapper, _local = write_wrapper(tmp_path, custom_camera=custom_camera)
    return wrapper, inspect_wrapper(wrapper)


def _inspect_now(dialog):
    dialog._candidate_inspected(
        dialog.bootstrap.inspect_candidate(dialog._selection())
    )


def test_current_checkout_candidate_is_visible_but_not_silently_confirmed(
    qapp, tmp_path
):
    wrapper, candidate = _candidate(tmp_path / "source")
    current_local = wrapper / "local"
    bootstrap = FakeBootstrap(
        _inspection(
            tmp_path / "state",
            MachineDataBootstrap.BootstrapState.CANDIDATE_SELECTION_REQUIRED,
        ),
        candidate,
    )

    dialog = MachineDataBootstrapDialog.MachineDataBootstrapDialog(
        bootstrap,
        current_checkout_local=current_local,
    )

    assert dialog.source_path.text() == str(current_local.resolve())
    assert dialog.inspect_button.isEnabled()
    assert dialog.candidate is None
    assert dialog.pages.currentIndex() == 0


def test_folder_candidate_review_displays_coordinates_plates_and_source_metadata(
    qapp, tmp_path
):
    wrapper, candidate = _candidate(tmp_path / "source")
    bootstrap = FakeBootstrap(
        _inspection(
            tmp_path / "state",
            MachineDataBootstrap.BootstrapState.CANDIDATE_SELECTION_REQUIRED,
        ),
        candidate,
    )
    dialog = MachineDataBootstrapDialog.MachineDataBootstrapDialog(bootstrap)
    dialog.source_path.setText(str(wrapper))

    _inspect_now(dialog)

    assert dialog.pages.currentIndex() == 1
    assert dialog.candidate is candidate
    text = dialog.review_summary.toPlainText()
    assert "Declared VERSION: v1.3.0-rc.1" in text
    assert "camera: X=" in text
    assert "Plate calibrations:" in text
    assert dialog.source_reason.text() == ""


def test_verification_fields_build_explicit_submission_without_hardware(
    qapp, tmp_path
):
    wrapper, candidate = _candidate(tmp_path / "source")
    bootstrap = FakeBootstrap(
        _inspection(
            tmp_path / "state",
            MachineDataBootstrap.BootstrapState.CANDIDATE_SELECTION_REQUIRED,
        ),
        candidate,
    )
    dialog = MachineDataBootstrapDialog.MachineDataBootstrapDialog(bootstrap)
    dialog.source_path.setText(str(wrapper))
    _inspect_now(dialog)
    camera = candidate.safety_snapshot["locations"]["camera"]
    dialog.machine_id.setText("LC-001")
    dialog.operator.setText("Operator A")
    dialog.source_reason.setText("External pre-update backup")
    dialog.camera_x.setText(str(camera["X"]))
    dialog.camera_y.setText(str(camera["Y"]))
    dialog.camera_z.setText(str(camera["Z"]))
    dialog.attest.setChecked(True)
    operations = []
    dialog._start_worker = lambda operation, **_kwargs: operations.append(operation)

    dialog._activate()

    assert len(operations) == 1
    context = operations[0]()
    assert context.kind == "authorized"
    submission = bootstrap.submissions[0]
    assert submission.machine_id == "LC-001"
    assert submission.operator == "Operator A"
    assert submission.source_reason == "External pre-update backup"
    assert dict(submission.camera_confirmation) == dict(camera)


def test_missing_camera_confirmation_and_attestation_cannot_start_work(
    qapp, monkeypatch, tmp_path
):
    wrapper, candidate = _candidate(tmp_path / "source")
    bootstrap = FakeBootstrap(
        _inspection(
            tmp_path / "state",
            MachineDataBootstrap.BootstrapState.CANDIDATE_SELECTION_REQUIRED,
        ),
        candidate,
    )
    dialog = MachineDataBootstrapDialog.MachineDataBootstrapDialog(bootstrap)
    dialog.source_path.setText(str(wrapper))
    _inspect_now(dialog)
    warnings = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *_args: warnings.append(_args),
    )
    dialog._start_worker = lambda _operation, **_kwargs: (_ for _ in ()).throw(
        AssertionError("incomplete verification cannot start")
    )

    dialog._activate()

    assert warnings
    assert bootstrap.submissions == []


def test_preset_like_candidate_surfaces_independent_service_requirement(
    qapp, tmp_path
):
    wrapper, candidate = _candidate(tmp_path / "preset", custom_camera=False)
    assert candidate.camera_preset_match is True
    bootstrap = FakeBootstrap(
        _inspection(
            tmp_path / "state",
            MachineDataBootstrap.BootstrapState.CANDIDATE_SELECTION_REQUIRED,
        ),
        candidate,
    )
    dialog = MachineDataBootstrapDialog.MachineDataBootstrapDialog(bootstrap)
    dialog.source_path.setText(str(wrapper))

    _inspect_now(dialog)

    assert "independent service record" in dialog.service_record.placeholderText()
    assert "Camera preset match: True" in dialog.review_summary.toPlainText()


def test_multiple_inspected_candidates_show_duplicate_or_conflict_relation(
    qapp, tmp_path
):
    _first_wrapper, first = _candidate(tmp_path / "first", custom_camera=True)
    _second_wrapper, second = _candidate(tmp_path / "second", custom_camera=False)
    bootstrap = FakeBootstrap(
        _inspection(
            tmp_path / "state",
            MachineDataBootstrap.BootstrapState.CANDIDATE_SELECTION_REQUIRED,
        )
    )
    dialog = MachineDataBootstrapDialog.MachineDataBootstrapDialog(bootstrap)

    dialog._candidate_inspected(first)
    dialog._candidate_inspected(second)

    text = dialog.review_summary.toPlainText()
    assert "Comparison with other inspected candidates:" in text
    assert str(first.normalized_source) in text
    assert ": conflict" in text


def test_ready_state_revalidates_in_worker_before_accepting(qapp, monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(
        MachineDataBootstrapDialog.MachineDataBootstrapDialog,
        "_start_worker",
        lambda self, operation, **_kwargs: started.append(operation),
    )
    bootstrap = FakeBootstrap(
        _inspection(tmp_path, MachineDataBootstrap.BootstrapState.READY)
    )

    dialog = MachineDataBootstrapDialog.MachineDataBootstrapDialog(bootstrap)

    assert dialog.pages.currentIndex() == 2
    assert len(started) == 1
    assert started[0]().kind == "ready"


def test_recovery_state_disables_candidate_actions_and_returns_typed_error(
    qapp, monkeypatch, tmp_path
):
    issue = MachineDataBootstrap.BootstrapIssue(
        "active_state_invalid", "Activation receipt hash differs."
    )
    bootstrap = FakeBootstrap(
        _inspection(
            tmp_path,
            MachineDataBootstrap.BootstrapState.RECOVERY_REQUIRED,
            issues=(issue,),
        )
    )
    monkeypatch.setattr(
        MachineDataBootstrapDialog.MachineDataBootstrapDialog,
        "exec",
        lambda _self: QtWidgets.QDialog.DialogCode.Rejected,
    )

    with pytest.raises(MachineDataBootstrap.BootstrapError) as error:
        MachineDataBootstrapDialog.run_bootstrap_dialog(bootstrap)

    assert error.value.code == "recovery_required"
    assert "Activation receipt hash differs" in str(error.value)


def test_worker_cancel_requests_checkpoint_cancellation_without_terminating_thread(
    qapp, tmp_path
):
    bootstrap = FakeBootstrap(
        _inspection(
            tmp_path,
            MachineDataBootstrap.BootstrapState.CANDIDATE_SELECTION_REQUIRED,
        )
    )
    dialog = MachineDataBootstrapDialog.MachineDataBootstrapDialog(bootstrap)
    dialog._busy = True

    dialog._request_cancel()

    assert bootstrap.cancel_calls == 1
    assert not dialog.cancel_work_button.isEnabled()
    assert "next durable checkpoint" in dialog.progress_label.text()


def test_dialog_module_has_no_production_hardware_or_mvc_imports():
    source = Path("FreeRTOS-interface/MachineDataBootstrapDialog.py").read_text(
        encoding="utf-8"
    )

    for forbidden in (
        "from ApplicationComposition",
        "from Controller",
        "from Model",
        "from View",
        "Machine_FreeRTOS",
    ):
        assert forbidden not in source
