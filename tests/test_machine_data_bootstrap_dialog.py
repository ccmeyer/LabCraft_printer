from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6 import QtCore, QtWidgets

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


def _wait_until(qapp, predicate, timeout_ms=3000):
    deadline = QtCore.QDeadlineTimer(timeout_ms)
    while not deadline.hasExpired():
        qapp.processEvents(QtCore.QEventLoop.AllEvents, 5)
        if predicate():
            return
        QtCore.QThread.msleep(1)
    qapp.processEvents(QtCore.QEventLoop.AllEvents, 5)
    assert predicate(), "condition did not become true before timeout"


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
    selection = dialog._selection()
    assert (
        selection.source_kind
        is MachineDataMigration.CandidateSourceKind.OPERATOR_SELECTED_LOCAL
    )
    evidence = MachineDataMigration.inspect_candidate(selection)
    assert evidence.is_importable
    assert evidence.normalized_source == current_local.resolve()


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
    camera = candidate.safety_snapshot["locations"]["camera"]
    assert dialog.camera_x.text() == str(camera["X"])
    assert dialog.camera_y.text() == str(camera["Y"])
    assert dialog.camera_z.text() == str(camera["Z"])
    assert dialog.camera_x.isReadOnly()
    assert dialog.camera_y.isReadOnly()
    assert dialog.camera_z.isReadOnly()
    assert not dialog.camera_attest.isChecked()
    assert not dialog.attest.isChecked()


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
    # Even a programmatic widget mutation cannot change the submitted value;
    # the immutable inspected candidate is the source of truth.
    dialog.camera_x.setText("0")
    dialog.camera_y.setText("0")
    dialog.camera_z.setText("0")
    dialog.camera_attest.setChecked(True)
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


def test_missing_camera_preservation_approval_cannot_start_work(
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
    dialog.machine_id.setText("LC-001")
    dialog.operator.setText("Operator A")
    dialog.source_reason.setText("External pre-update backup")
    dialog.attest.setChecked(True)
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
    assert "Camera preservation approval" in warnings[0][2]
    assert bootstrap.submissions == []


def test_noninteger_inspected_camera_is_shown_but_activation_fails_cleanly(
    qapp, monkeypatch, tmp_path
):
    _wrapper, candidate = _candidate(tmp_path / "source")
    locations = dict(candidate.safety_snapshot["locations"])
    camera = dict(locations["camera"])
    camera["Y"] = camera["Y"] + 0.5
    locations["camera"] = camera
    snapshot = dict(candidate.safety_snapshot)
    snapshot["locations"] = locations
    candidate = replace(candidate, safety_snapshot=snapshot)
    bootstrap = FakeBootstrap(
        _inspection(
            tmp_path / "state",
            MachineDataBootstrap.BootstrapState.CANDIDATE_SELECTION_REQUIRED,
        ),
        candidate,
    )
    dialog = MachineDataBootstrapDialog.MachineDataBootstrapDialog(bootstrap)
    dialog._candidate_inspected(candidate)
    assert dialog.camera_y.text().endswith(".5")
    dialog.operator.setText("Operator A")
    dialog.source_reason.setText("External pre-update backup")
    dialog.camera_attest.setChecked(True)
    dialog.attest.setChecked(True)
    warnings = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *_args: warnings.append(_args),
    )
    dialog._start_worker = lambda _operation, **_kwargs: (_ for _ in ()).throw(
        AssertionError("invalid Camera evidence cannot start")
    )

    dialog._activate()

    assert warnings
    assert "integer step value" in warnings[0][2]
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
    dialog.camera_attest.setChecked(True)
    dialog.attest.setChecked(True)
    dialog._candidate_inspected(second)

    text = dialog.review_summary.toPlainText()
    assert "Comparison with other inspected candidates:" in text
    assert str(first.normalized_source) in text
    assert ": conflict" in text
    assert not dialog.camera_attest.isChecked()
    assert not dialog.attest.isChecked()


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


def test_worker_success_accepts_only_after_qthread_has_stopped(qapp, tmp_path):
    bootstrap = FakeBootstrap(
        _inspection(
            tmp_path,
            MachineDataBootstrap.BootstrapState.CANDIDATE_SELECTION_REQUIRED,
        )
    )
    dialog = MachineDataBootstrapDialog.MachineDataBootstrapDialog(bootstrap)
    accepted_after_stop = []
    dialog.accepted.connect(
        lambda: accepted_after_stop.append(
            dialog._thread is None or dialog._thread.isFinished()
        )
    )

    dialog._start_worker(
        lambda: SimpleNamespace(kind="authorized"),
        mode="activate",
    )

    _wait_until(qapp, lambda: bool(accepted_after_stop))
    assert accepted_after_stop == [True]
    assert dialog.context.kind == "authorized"
    assert dialog._busy is False
    assert dialog._thread is None
    assert dialog._worker is None


def test_worker_failure_shows_error_only_after_qthread_has_stopped(
    qapp, monkeypatch, tmp_path
):
    bootstrap = FakeBootstrap(
        _inspection(
            tmp_path,
            MachineDataBootstrap.BootstrapState.CANDIDATE_SELECTION_REQUIRED,
        )
    )
    dialog = MachineDataBootstrapDialog.MachineDataBootstrapDialog(bootstrap)
    errors_after_stop = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "critical",
        lambda *_args: errors_after_stop.append(
            dialog._thread is None or dialog._thread.isFinished()
        ),
    )

    def fail():
        raise RuntimeError("injected failure")

    dialog._start_worker(fail, mode="activate")

    _wait_until(qapp, lambda: bool(errors_after_stop))
    assert errors_after_stop == [True]
    assert dialog.failure_code == "bootstrap_failed"
    assert dialog.failure_message == "injected failure"
    assert dialog._busy is False


def test_worker_cancellation_rejects_only_after_qthread_has_stopped(qapp, tmp_path):
    bootstrap = FakeBootstrap(
        _inspection(
            tmp_path,
            MachineDataBootstrap.BootstrapState.CANDIDATE_SELECTION_REQUIRED,
        )
    )
    dialog = MachineDataBootstrapDialog.MachineDataBootstrapDialog(bootstrap)
    rejected_after_stop = []
    dialog.rejected.connect(
        lambda: rejected_after_stop.append(
            dialog._thread is None or dialog._thread.isFinished()
        )
    )

    def cancel():
        raise MachineDataBootstrap.BootstrapError(
            "bootstrap_cancelled", "injected cancellation"
        )

    dialog._start_worker(cancel, mode="activate")

    _wait_until(qapp, lambda: bool(rejected_after_stop))
    assert rejected_after_stop == [True]
    assert dialog.failure_code is None
    assert dialog.failure_message is None
    assert dialog._busy is False


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
