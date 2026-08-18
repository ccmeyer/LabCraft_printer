from types import SimpleNamespace
from unittest.mock import Mock

import View
from View import MainWindow, XyMotionRecoveryDialog


def test_recovery_dialog_guides_clear_retry_home_and_completion(qapp):
    controller = SimpleNamespace(
        clear_xy_motion_recovery=Mock(return_value=True),
        home_machine=Mock(return_value=True),
    )
    dialog = XyMotionRecoveryDialog(None, controller)
    dialog.update_report(
        {
            "summary": "XY motion stopped.",
            "failed_command_number": 77,
            "black_box_log_path": "logs/machine_black_box/xy.json",
        }
    )
    dialog.show()

    dialog.set_recovery_state("clear_required")
    assert dialog.primary_button.text() == "I Checked the Machine — Clear Queue"
    assert dialog.primary_button.isEnabled()
    assert "did not reset" in dialog.detail_label.text()
    assert "sequence 77" in dialog.detail_label.text()

    dialog.primary_button.click()
    controller.clear_xy_motion_recovery.assert_called_once_with()
    assert not dialog.primary_button.isEnabled()

    dialog.set_recovery_state("clear_pending")
    assert dialog.primary_button.text() == "Clearing Queue…"
    dialog.set_recovery_state("clear_required")
    assert dialog.feedback_label.isVisible()
    assert "not confirmed" in dialog.feedback_label.text()

    dialog.set_recovery_state("home_required")
    assert dialog.primary_button.text() == "Home Machine"
    dialog.primary_button.click()
    controller.home_machine.assert_called_once_with()

    dialog.set_recovery_state("home_in_progress")
    assert dialog.primary_button.text() == "Homing…"
    assert not dialog.primary_button.isEnabled()

    assert dialog.isVisible()
    dialog.set_recovery_state("idle")
    assert not dialog.isVisible()


def test_recovery_dialog_keeps_action_available_when_submission_fails(qapp):
    controller = SimpleNamespace(
        clear_xy_motion_recovery=Mock(return_value=False),
        home_machine=Mock(return_value=False),
    )
    dialog = XyMotionRecoveryDialog(None, controller)

    dialog.set_recovery_state("clear_required")
    dialog.primary_button.click()
    assert dialog.primary_button.isEnabled()
    assert "could not be sent" in dialog.feedback_label.text()

    dialog.set_recovery_state("home_required")
    dialog.primary_button.click()
    assert dialog.primary_button.isEnabled()
    assert "could not be queued" in dialog.feedback_label.text()


class _FakeRecoveryDialog:
    def __init__(self, _main_window, _controller):
        self.reports = []
        self.states = []
        self.shown = 0
        self.raised = 0
        self.activated = 0

    def update_report(self, report):
        self.reports.append(dict(report or {}))

    def set_recovery_state(self, state):
        self.states.append(state)

    def show(self):
        self.shown += 1

    def raise_(self):
        self.raised += 1

    def activateWindow(self):
        self.activated += 1


def test_mainwindow_reuses_one_recovery_dialog_for_repeated_faults(monkeypatch):
    created = []

    def make_dialog(main_window, controller):
        dialog = _FakeRecoveryDialog(main_window, controller)
        created.append(dialog)
        return dialog

    monkeypatch.setattr(View, "XyMotionRecoveryDialog", make_dialog)
    window = MainWindow.__new__(MainWindow)
    window.controller = SimpleNamespace(
        get_xy_motion_recovery_state=lambda: "clear_required"
    )
    window._xy_motion_recovery_dialog = None
    window._xy_motion_recovery_report = {}
    window._xy_motion_recovery_state = "clear_required"

    first_report = {"failed_command_number": 41}
    MainWindow.show_xy_motion_recovery(window, first_report)
    MainWindow.show_xy_motion_recovery(window, first_report)

    assert len(created) == 1
    assert created[0].shown == 2
    assert created[0].raised == 2
    assert created[0].states == ["clear_required", "clear_required"]


def test_mainwindow_banner_persists_when_dialog_is_closed_and_hides_at_idle():
    visibility = []
    labels = []
    dialog = _FakeRecoveryDialog(None, None)
    window = MainWindow.__new__(MainWindow)
    window.xy_motion_recovery_banner = SimpleNamespace(
        setVisible=lambda visible: visibility.append(bool(visible))
    )
    window.xy_motion_recovery_banner_label = SimpleNamespace(
        setText=lambda text: labels.append(text)
    )
    window._xy_motion_recovery_dialog = dialog
    window._xy_motion_recovery_state = "idle"

    MainWindow._on_xy_motion_recovery_state_changed(window, "home_required")
    MainWindow._on_xy_motion_recovery_state_changed(window, "home_in_progress")
    MainWindow._on_xy_motion_recovery_state_changed(window, "idle")

    assert visibility == [True, True, False]
    assert "Home Machine" in labels[0]
    assert dialog.states == ["home_required", "home_in_progress", "idle"]
