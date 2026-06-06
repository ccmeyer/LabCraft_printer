from pathlib import Path

import pytest

from tools import update_and_restart as updater
from tools import update_window


def _config(tmp_path: Path, **kwargs) -> updater.UpdaterConfig:
    return updater.UpdaterConfig(
        repo_root=tmp_path,
        log_path=tmp_path / "update.log",
        no_relaunch=kwargs.pop("no_relaunch", False),
        **kwargs,
    )


def _make_window(qapp, tmp_path, **kwargs):
    window = update_window.UpdaterWindow(
        _config(tmp_path, **kwargs.pop("config_kwargs", {})),
        auto_start=False,
        auto_close_on_launch=False,
        **kwargs,
    )
    return window


def test_update_window_initializes_with_title(qapp, tmp_path):
    window = _make_window(qapp, tmp_path)

    assert window.windowTitle() == "LabCraft Updater"
    assert window.status_label.text() == "Preparing update..."

    window.close()


def test_update_window_progress_event_updates_status(qapp, tmp_path):
    window = _make_window(qapp, tmp_path)

    window.handle_progress_event(
        updater.ProgressEvent(kind="waiting", message="Waiting for LabCraft to close...")
    )

    assert window.status_label.text() == "Waiting for LabCraft to close..."

    window.close()


def test_update_window_details_toggle_shows_command_output(qapp, tmp_path):
    window = _make_window(qapp, tmp_path)
    command = updater.CommandResult(
        ("git", "pull", "--ff-only"),
        128,
        stderr="fatal: Not possible to fast-forward",
    )

    window.handle_progress_event(
        updater.ProgressEvent(kind="command", message="Command completed.", command_result=command)
    )
    window.details_button.setChecked(True)

    assert window.details_text.isHidden() is False
    assert "git pull --ff-only" in window.details_text.toPlainText()
    assert "fatal: Not possible to fast-forward" in window.details_text.toPlainText()
    assert window.details_button.text() == "Hide Details"

    window.close()


def test_update_window_failure_state_shows_reopen_close_and_log_path(qapp, tmp_path):
    window = _make_window(qapp, tmp_path)
    result = updater.UpdateResult(
        updater.STATUS_DIRTY_WORKTREE,
        3,
        "Update cannot continue because this installation has local developer changes.",
        repo_root=tmp_path,
        before_sha="abc",
        after_sha="abc",
        log_path=tmp_path / "update.log",
    )

    window.handle_finished(result)

    assert window.reopen_button.isHidden() is False
    assert window.close_button.isHidden() is False
    assert window.retry_launch_button.isHidden() is True
    assert "local developer changes" in window.status_label.text()
    assert str(tmp_path / "update.log") in window.log_path_label.text()
    assert window.exit_code == 3

    window.close()


def test_update_window_reopen_current_version_launches_and_preserves_failure_code(qapp, tmp_path):
    launches = []
    window = _make_window(
        qapp,
        tmp_path,
        launcher=lambda command, cwd: launches.append((tuple(command), Path(cwd))),
    )
    result = updater.UpdateResult(
        updater.STATUS_GIT_PULL_FAILED,
        5,
        "Update cannot continue because git pull --ff-only failed.",
        repo_root=tmp_path,
        before_sha="abc",
        after_sha="abc",
        log_path=tmp_path / "update.log",
    )
    window.handle_finished(result)

    window.reopen_button.click()

    assert launches == [
        (
            (
                str(updater.resolve_python_path(tmp_path)),
                str(tmp_path / "FreeRTOS-interface" / "App.py"),
            ),
            tmp_path,
        )
    ]
    assert window.status_label.text() == "LabCraft started."
    assert window.exit_code == 5

    window.close()


def test_update_window_success_auto_close_defers_launch_until_updater_exits(qapp, tmp_path, monkeypatch):
    launches = []
    monkeypatch.setattr(update_window.os, "getpid", lambda: 555)
    window = update_window.UpdaterWindow(
        _config(tmp_path, python_path=Path("custom-python")),
        auto_start=False,
        auto_close_on_launch=True,
        launcher=lambda command, cwd: launches.append((tuple(command), Path(cwd))),
    )
    result = updater.UpdateResult(
        updater.STATUS_UPDATED,
        0,
        "LabCraft was updated successfully.",
        repo_root=tmp_path,
        before_sha="abc",
        after_sha="def",
        log_path=tmp_path / "update.log",
    )

    window.handle_finished(result)

    assert len(launches) == 1
    helper_command, cwd = launches[0]
    assert cwd == tmp_path
    assert updater.DEFERRED_LAUNCH_ARG in helper_command
    assert "--wait-pid" in helper_command
    assert "555" in helper_command
    assert str(tmp_path / "custom-python") in helper_command
    assert str(tmp_path / "FreeRTOS-interface" / "App.py") in helper_command
    assert window.status_label.text() == "LabCraft will reopen."
    assert "Deferred launch command" in window.details_text.toPlainText()
    assert "App launch command" in window.details_text.toPlainText()
    assert window.exit_code == 0

    window.close()


def test_update_window_relaunch_failure_after_success_shows_retry(qapp, tmp_path):
    def failing_launcher(command, cwd):
        raise OSError("launch failed")

    window = _make_window(qapp, tmp_path, launcher=failing_launcher)
    result = updater.UpdateResult(
        updater.STATUS_UPDATED,
        0,
        "LabCraft was updated successfully.",
        repo_root=tmp_path,
        before_sha="abc",
        after_sha="def",
        log_path=tmp_path / "update.log",
    )

    window.handle_finished(result)

    assert "could not be started" in window.status_label.text()
    assert window.retry_launch_button.isHidden() is False
    assert window.reopen_button.isHidden() is True
    assert window.close_button.isHidden() is False
    assert window.exit_code == updater.EXIT_CODES[updater.STATUS_RELAUNCH_FAILED]
    assert "Launch command" in window.details_text.toPlainText()

    window.close()
