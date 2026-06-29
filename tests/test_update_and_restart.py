import json
import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from tools import create_update_bundle
import tools.update_and_restart as updater

OFFLINE_SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER_OFFLINE_SHA = "fedcba9876543210fedcba9876543210fedcba98"


def _write_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


class FakeGitRunner:
    def __init__(
        self,
        repo_root: Path,
        *,
        branch: str = "main",
        before_sha: str = "before123",
        after_sha: str | None = None,
        dirty_status: str = "",
        top_level_returncode: int = 0,
        status_returncode: int = 0,
        pull_returncode: int = 0,
        pull_stdout: str = "Already up to date.\n",
        after_rev_parse_returncode: int = 0,
        upstream: str = "origin/main",
        upstream_returncode: int = 0,
        upstream_sha: str = "upstream456",
        fetch_returncode: int = 0,
        ahead_count: int = 0,
        behind_count: int = 0,
        check_commits: tuple[str, ...] = (),
        update_commits: tuple[str, ...] = (),
        remote_url: str = "https://github.com/ccmeyer/LabCraft_printer",
        offline_ref_sha: str = OFFLINE_SHA,
        offline_fetch_returncode: int = 0,
        offline_verify_returncode: int = 0,
        offline_merge_returncode: int = 0,
        offline_ahead_count: int | None = None,
        offline_behind_count: int | None = None,
        offline_check_commits: tuple[str, ...] = (),
    ):
        self.repo_root = repo_root
        self.branch = branch
        self.before_sha = before_sha
        self.after_sha = after_sha if after_sha is not None else before_sha
        self.dirty_status = dirty_status
        self.top_level_returncode = top_level_returncode
        self.status_returncode = status_returncode
        self.pull_returncode = pull_returncode
        self.pull_stdout = pull_stdout
        self.after_rev_parse_returncode = after_rev_parse_returncode
        self.upstream = upstream
        self.upstream_returncode = upstream_returncode
        self.upstream_sha = upstream_sha
        self.fetch_returncode = fetch_returncode
        self.ahead_count = ahead_count
        self.behind_count = behind_count
        self.check_commits = check_commits
        self.update_commits = update_commits
        self.remote_url = remote_url
        self.offline_ref_sha = offline_ref_sha
        self.offline_fetch_returncode = offline_fetch_returncode
        self.offline_verify_returncode = offline_verify_returncode
        self.offline_merge_returncode = offline_merge_returncode
        self.offline_ahead_count = offline_ahead_count
        self.offline_behind_count = offline_behind_count
        self.offline_check_commits = offline_check_commits
        self.rev_parse_head_calls = 0
        self.calls: list[tuple[tuple[str, ...], Path, float, dict]] = []

    def __call__(self, args, cwd, timeout_s, env_updates):
        args_tuple = tuple(str(arg) for arg in args)
        self.calls.append((args_tuple, Path(cwd), float(timeout_s), dict(env_updates or {})))

        git_args = args_tuple[1:]
        if git_args == ("rev-parse", "--show-toplevel"):
            if self.top_level_returncode:
                return updater.CommandResult(args_tuple, self.top_level_returncode, stderr="not a repo")
            return updater.CommandResult(args_tuple, 0, stdout=f"{self.repo_root}\n")

        if git_args == ("branch", "--show-current"):
            return updater.CommandResult(args_tuple, 0, stdout=f"{self.branch}\n")

        if git_args == ("rev-parse", "HEAD"):
            self.rev_parse_head_calls += 1
            if self.rev_parse_head_calls >= 2:
                if self.after_rev_parse_returncode:
                    return updater.CommandResult(args_tuple, self.after_rev_parse_returncode, stderr="bad after")
                return updater.CommandResult(args_tuple, 0, stdout=f"{self.after_sha}\n")
            return updater.CommandResult(args_tuple, 0, stdout=f"{self.before_sha}\n")

        if git_args == ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"):
            if self.upstream_returncode:
                return updater.CommandResult(args_tuple, self.upstream_returncode, stderr="no upstream")
            return updater.CommandResult(args_tuple, 0, stdout=f"{self.upstream}\n")

        if git_args == ("config", "--get", "remote.origin.url"):
            return updater.CommandResult(args_tuple, 0, stdout=f"{self.remote_url}\n")

        if git_args == ("fetch", "--prune"):
            if self.fetch_returncode:
                return updater.CommandResult(args_tuple, self.fetch_returncode, stderr="network unavailable")
            return updater.CommandResult(args_tuple, 0, stdout="")

        if git_args == ("rev-parse", "@{u}"):
            return updater.CommandResult(args_tuple, 0, stdout=f"{self.upstream_sha}\n")

        if git_args == ("rev-parse", updater.OFFLINE_UPDATE_REF):
            return updater.CommandResult(args_tuple, 0, stdout=f"{self.offline_ref_sha}\n")

        if git_args == ("rev-list", "--left-right", "--count", "HEAD...@{u}"):
            return updater.CommandResult(args_tuple, 0, stdout=f"{self.ahead_count}\t{self.behind_count}\n")

        if git_args == ("rev-list", "--left-right", "--count", f"HEAD...{updater.OFFLINE_UPDATE_REF}"):
            ahead = self.ahead_count if self.offline_ahead_count is None else self.offline_ahead_count
            behind = self.behind_count if self.offline_behind_count is None else self.offline_behind_count
            return updater.CommandResult(args_tuple, 0, stdout=f"{ahead}\t{behind}\n")

        if git_args == ("log", "--oneline", "HEAD..@{u}"):
            return updater.CommandResult(args_tuple, 0, stdout="\n".join(self.check_commits) + ("\n" if self.check_commits else ""))

        if git_args == ("log", "--oneline", f"HEAD..{updater.OFFLINE_UPDATE_REF}"):
            return updater.CommandResult(args_tuple, 0, stdout="\n".join(self.offline_check_commits) + ("\n" if self.offline_check_commits else ""))

        if len(git_args) == 3 and git_args[:2] == ("log", "--oneline"):
            return updater.CommandResult(args_tuple, 0, stdout="\n".join(self.update_commits) + ("\n" if self.update_commits else ""))

        if git_args == ("status", "--porcelain"):
            return updater.CommandResult(args_tuple, self.status_returncode, stdout=self.dirty_status)

        if git_args == ("pull", "--ff-only"):
            return updater.CommandResult(
                args_tuple,
                self.pull_returncode,
                stdout=self.pull_stdout if self.pull_returncode == 0 else "",
                stderr="" if self.pull_returncode == 0 else "fatal: Not possible to fast-forward",
            )

        if len(git_args) == 3 and git_args[:2] == ("bundle", "verify"):
            if self.offline_verify_returncode:
                return updater.CommandResult(args_tuple, self.offline_verify_returncode, stderr="bundle verify failed")
            return updater.CommandResult(args_tuple, 0, stdout="The bundle is okay\n")

        if len(git_args) == 4 and git_args[:2] == ("fetch", "--force"):
            if self.offline_fetch_returncode:
                return updater.CommandResult(args_tuple, self.offline_fetch_returncode, stderr="bundle fetch failed")
            return updater.CommandResult(args_tuple, 0, stdout="")

        if git_args == ("merge", "--ff-only", updater.OFFLINE_UPDATE_REF):
            return updater.CommandResult(
                args_tuple,
                self.offline_merge_returncode,
                stdout="Fast-forward\n" if self.offline_merge_returncode == 0 else "",
                stderr="" if self.offline_merge_returncode == 0 else "fatal: Not possible to fast-forward",
            )

        return updater.CommandResult(args_tuple, 99, stderr=f"unexpected command: {git_args!r}")


def _config(tmp_path: Path, **kwargs) -> updater.UpdaterConfig:
    log_path = kwargs.pop("log_path", tmp_path / "update.log")
    return updater.UpdaterConfig(
        repo_root=tmp_path,
        no_relaunch=kwargs.pop("no_relaunch", True),
        log_path=log_path,
        **kwargs,
    )


def _write_offline_manifest(
    tmp_path: Path,
    *,
    branch: str = "main",
    repo: str = "ccmeyer/LabCraft_printer",
    remote: str = "origin",
    head_sha: str = OFFLINE_SHA,
    schema_version: str = updater.OFFLINE_BUNDLE_SCHEMA_VERSION,
    bundle_name: str = "labcraft-main.bundle",
    bundle_bytes: bytes = b"bundle bytes\n",
    created_at_utc: str = "2026-06-18T12:00:00Z",
) -> Path:
    bundle_path = tmp_path / bundle_name
    bundle_path.write_bytes(bundle_bytes)
    manifest = {
        "schema_version": schema_version,
        "repo": repo,
        "remote": remote,
        "remote_url": "https://github.com/ccmeyer/LabCraft_printer",
        "branch": branch,
        "source_ref": f"refs/remotes/{remote}/{branch}",
        "head_sha": head_sha,
        "bundle_filename": bundle_name,
        "bundle_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
        "created_at_utc": created_at_utc,
    }
    manifest_path = tmp_path / f"{Path(bundle_name).stem}.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def test_linux_python_resolution_prefers_repo_venv_order(tmp_path):
    env_python = tmp_path / "env" / "bin" / "python"
    dotvenv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python = tmp_path / "venv" / "bin" / "python"
    _write_file(env_python)
    _write_file(dotvenv_python)
    _write_file(venv_python)

    assert updater.resolve_python_path(tmp_path, platform_name="Linux") == venv_python

    venv_python.unlink()
    assert updater.resolve_python_path(tmp_path, platform_name="Linux") == dotvenv_python

    dotvenv_python.unlink()
    assert updater.resolve_python_path(tmp_path, platform_name="Linux") == env_python


def test_windows_python_resolution_prefers_repo_env_order(tmp_path):
    venv_python = tmp_path / "venv" / "Scripts" / "python.exe"
    dotvenv_python = tmp_path / ".venv" / "Scripts" / "python.exe"
    env_python = tmp_path / "env" / "Scripts" / "python.exe"
    _write_file(venv_python)
    _write_file(dotvenv_python)
    _write_file(env_python)

    assert updater.resolve_python_path(tmp_path, platform_name="Windows") == env_python

    env_python.unlink()
    assert updater.resolve_python_path(tmp_path, platform_name="Windows") == dotvenv_python

    dotvenv_python.unlink()
    assert updater.resolve_python_path(tmp_path, platform_name="Windows") == venv_python


def test_invalid_repo_returns_not_git_repo(tmp_path):
    runner = FakeGitRunner(tmp_path, top_level_returncode=128)

    result = updater.run_update(_config(tmp_path), command_runner=runner)

    assert result.status == updater.STATUS_NOT_GIT_REPO
    assert result.returncode == 2
    assert "not a Git checkout" in result.message
    assert result.log_path and result.log_path.exists()


def test_dirty_worktree_blocks_before_pull_and_does_not_relaunch(tmp_path):
    runner = FakeGitRunner(tmp_path, dirty_status=" M FreeRTOS-interface/App.py\n")
    launches = []

    result = updater.run_update(
        _config(tmp_path),
        command_runner=runner,
        launcher=lambda command, cwd: launches.append((command, cwd)),
    )

    assert result.status == updater.STATUS_DIRTY_WORKTREE
    assert result.returncode == 3
    assert not launches
    assert ("git", "pull", "--ff-only") not in [call[0] for call in runner.calls]


def test_clean_noop_pull_returns_already_current(tmp_path):
    runner = FakeGitRunner(tmp_path, before_sha="abc", after_sha="abc")

    result = updater.run_update(_config(tmp_path), command_runner=runner)

    assert result.status == updater.STATUS_ALREADY_CURRENT
    assert result.returncode == 0
    assert result.before_sha == "abc"
    assert result.after_sha == "abc"
    assert all(call[3].get("GIT_TERMINAL_PROMPT") == "0" for call in runner.calls)


def test_clean_fast_forward_returns_updated(tmp_path):
    runner = FakeGitRunner(tmp_path, before_sha="abc", after_sha="def", pull_stdout="Fast-forward\n")

    result = updater.run_update(_config(tmp_path), command_runner=runner)

    assert result.status == updater.STATUS_UPDATED
    assert result.returncode == 0
    assert result.before_sha == "abc"
    assert result.after_sha == "def"


def test_pull_failure_returns_git_pull_failed_and_does_not_relaunch(tmp_path):
    runner = FakeGitRunner(tmp_path, pull_returncode=128)
    launches = []

    result = updater.run_update(
        _config(tmp_path),
        command_runner=runner,
        launcher=lambda command, cwd: launches.append((command, cwd)),
    )

    assert result.status == updater.STATUS_GIT_PULL_FAILED
    assert result.returncode == 5
    assert result.after_sha == result.before_sha
    assert not launches


def test_offline_update_uses_bundle_merge_not_git_pull(tmp_path):
    manifest_path = _write_offline_manifest(tmp_path, head_sha=OFFLINE_SHA)
    runner = FakeGitRunner(tmp_path, before_sha="abc", after_sha=OFFLINE_SHA, offline_ref_sha=OFFLINE_SHA)

    result = updater.run_update(
        _config(tmp_path, offline_manifest_path=manifest_path),
        command_runner=runner,
    )

    calls = [call[0] for call in runner.calls]
    assert result.status == updater.STATUS_UPDATED
    assert result.update_source == updater.UPDATE_SOURCE_OFFLINE
    assert result.offline_manifest_path == manifest_path.resolve()
    assert ("git", "pull", "--ff-only") not in calls
    assert ("git", "merge", "--ff-only", updater.OFFLINE_UPDATE_REF) in calls
    assert any(call[:3] == ("git", "fetch", "--force") for call in calls)


def test_offline_update_merge_failure_returns_offline_update_failed(tmp_path):
    manifest_path = _write_offline_manifest(tmp_path, head_sha=OFFLINE_SHA)
    runner = FakeGitRunner(
        tmp_path,
        before_sha="abc",
        after_sha="abc",
        offline_ref_sha=OFFLINE_SHA,
        offline_merge_returncode=128,
    )

    result = updater.run_update(
        _config(tmp_path, offline_manifest_path=manifest_path),
        command_runner=runner,
    )

    assert result.status == updater.STATUS_OFFLINE_UPDATE_FAILED
    assert result.returncode == updater.EXIT_CODES[updater.STATUS_OFFLINE_UPDATE_FAILED]
    assert result.after_sha == result.before_sha


def test_offline_update_dirty_worktree_blocks_before_bundle_fetch(tmp_path):
    manifest_path = _write_offline_manifest(tmp_path, head_sha=OFFLINE_SHA)
    runner = FakeGitRunner(tmp_path, dirty_status=" M FreeRTOS-interface/App.py\n")

    result = updater.run_update(
        _config(tmp_path, offline_manifest_path=manifest_path),
        command_runner=runner,
    )

    assert result.status == updater.STATUS_DIRTY_WORKTREE
    assert result.update_source == updater.UPDATE_SOURCE_OFFLINE
    assert not any(call[0][:3] == ("git", "fetch", "--force") for call in runner.calls)


def test_relaunch_on_failure_relaunches_current_app_on_dirty_worktree(tmp_path):
    runner = FakeGitRunner(tmp_path, dirty_status=" M FreeRTOS-interface/App.py\n")
    python_path = tmp_path / "venv" / "bin" / "python"
    _write_file(python_path)
    launches = []

    result = updater.run_update(
        _config(tmp_path, no_relaunch=False, relaunch_on_failure=True, platform_name="Linux"),
        command_runner=runner,
        launcher=lambda command, cwd: launches.append((tuple(command), Path(cwd))),
    )

    assert result.status == updater.STATUS_DIRTY_WORKTREE
    assert result.returncode == 3
    assert launches == [
        (
            (str(python_path), str(tmp_path / "FreeRTOS-interface" / "App.py")),
            tmp_path,
        )
    ]


def test_relaunch_on_failure_relaunches_current_app_on_pull_failure(tmp_path):
    runner = FakeGitRunner(tmp_path, pull_returncode=128)
    launches = []

    result = updater.run_update(
        _config(
            tmp_path,
            no_relaunch=False,
            relaunch_on_failure=True,
            python_path=Path("custom-python"),
        ),
        command_runner=runner,
        launcher=lambda command, cwd: launches.append((tuple(command), Path(cwd))),
    )

    assert result.status == updater.STATUS_GIT_PULL_FAILED
    assert result.returncode == 5
    assert launches == [
        (
            (str(tmp_path / "custom-python"), str(tmp_path / "FreeRTOS-interface" / "App.py")),
            tmp_path,
        )
    ]


def test_relaunch_on_failure_reports_relaunch_failed_when_failure_relaunch_fails(tmp_path):
    runner = FakeGitRunner(tmp_path, dirty_status=" M FreeRTOS-interface/App.py\n")

    def failing_launcher(command, cwd):
        raise OSError("launch failed")

    result = updater.run_update(
        _config(tmp_path, no_relaunch=False, relaunch_on_failure=True),
        command_runner=runner,
        launcher=failing_launcher,
    )

    assert result.status == updater.STATUS_RELAUNCH_FAILED
    assert result.returncode == 6
    assert "local developer changes" in result.message
    assert "launch failed" in result.message


def test_wait_pid_timeout_returns_before_running_git(tmp_path):
    runner = FakeGitRunner(tmp_path)

    result = updater.run_update(
        _config(tmp_path, wait_pid=1234),
        command_runner=runner,
        waiter=lambda pid, timeout: False,
    )

    assert result.status == updater.STATUS_WAIT_TIMEOUT
    assert result.returncode == 4
    assert runner.calls == []


def test_relaunch_failure_is_reported_after_successful_update(tmp_path):
    runner = FakeGitRunner(tmp_path, before_sha="abc", after_sha="def")

    def failing_launcher(command, cwd):
        raise OSError("launch failed")

    result = updater.run_update(
        _config(tmp_path, no_relaunch=False),
        command_runner=runner,
        launcher=failing_launcher,
    )

    assert result.status == updater.STATUS_RELAUNCH_FAILED
    assert result.returncode == 6
    assert "launch failed" in result.message
    assert result.before_sha == "abc"
    assert result.after_sha == "def"


def test_no_relaunch_suppresses_launch_after_success(tmp_path):
    runner = FakeGitRunner(tmp_path)
    launches = []

    result = updater.run_update(
        _config(tmp_path, no_relaunch=True),
        command_runner=runner,
        launcher=lambda command, cwd: launches.append((command, cwd)),
    )

    assert result.status == updater.STATUS_ALREADY_CURRENT
    assert launches == []


def test_successful_relaunch_uses_repo_local_python_and_app_path(tmp_path):
    runner = FakeGitRunner(tmp_path)
    python_path = tmp_path / "venv" / "bin" / "python"
    _write_file(python_path)
    launches = []

    result = updater.run_update(
        _config(tmp_path, no_relaunch=False, platform_name="Linux"),
        command_runner=runner,
        launcher=lambda command, cwd: launches.append((tuple(command), Path(cwd))),
    )

    assert result.status == updater.STATUS_ALREADY_CURRENT
    assert launches == [
        (
            (str(python_path), str(tmp_path / "FreeRTOS-interface" / "App.py")),
            tmp_path,
        )
    ]


def test_relaunch_helper_uses_same_repo_local_python_and_app_path(tmp_path):
    python_path = tmp_path / "venv" / "bin" / "python"
    _write_file(python_path)
    launches = []
    config = _config(tmp_path, platform_name="Linux")

    ok, message, command = updater.relaunch_app(
        config,
        tmp_path,
        launcher=lambda launch_command, cwd: launches.append((tuple(launch_command), Path(cwd))),
    )

    assert ok is True
    assert message == ""
    assert command == [str(python_path), str(tmp_path / "FreeRTOS-interface" / "App.py")]
    assert launches == [(tuple(command), tmp_path)]


def test_deferred_relaunch_helper_waits_for_updater_before_app_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.sys, "executable", "helper-python")
    launches = []
    config = _config(tmp_path, python_path=Path("custom-python"))

    ok, message, helper_command, app_command = updater.relaunch_app_after_process_exit(
        config,
        tmp_path,
        wait_pid=1234,
        launcher=lambda launch_command, cwd: launches.append((tuple(launch_command), Path(cwd))),
    )

    assert ok is True
    assert message == ""
    assert app_command == [
        str(tmp_path / "custom-python"),
        str(tmp_path / "FreeRTOS-interface" / "App.py"),
    ]
    assert helper_command == [
        "helper-python",
        "-u",
        str(Path(updater.__file__).resolve()),
        updater.DEFERRED_LAUNCH_ARG,
        "--wait-pid",
        "1234",
        "--wait-timeout-s",
        "30",
        "--cwd",
        str(tmp_path),
        "--",
        *app_command,
    ]
    assert launches == [(tuple(helper_command), tmp_path)]


def test_run_deferred_launch_waits_then_launches_detached(tmp_path, monkeypatch):
    calls = []

    monkeypatch.setattr(updater, "wait_for_process_exit", lambda pid, timeout: calls.append(("wait", pid, timeout)) or True)
    monkeypatch.setattr(
        updater,
        "detached_process_launcher",
        lambda command, cwd: calls.append(("launch", tuple(command), Path(cwd))),
    )

    returncode = updater.run_deferred_launch(
        [
            "--wait-pid",
            "4321",
            "--wait-timeout-s",
            "2.5",
            "--cwd",
            str(tmp_path),
            "--",
            "python",
            "FreeRTOS-interface/App.py",
        ]
    )

    assert returncode == 0
    assert calls == [
        ("wait", 4321, 2.5),
        ("launch", ("python", "FreeRTOS-interface/App.py"), tmp_path),
    ]


def test_log_file_created_under_local_update_logs_by_default(tmp_path):
    runner = FakeGitRunner(tmp_path, before_sha="abc", after_sha="def", pull_stdout="Fast-forward\n")

    result = updater.run_update(
        updater.UpdaterConfig(repo_root=tmp_path, no_relaunch=True),
        command_runner=runner,
    )

    assert result.status == updater.STATUS_UPDATED
    assert result.log_path is not None
    assert result.log_path.parent == tmp_path / "local" / "update_logs"
    text = result.log_path.read_text(encoding="utf-8")
    assert "status: updated" in text
    assert "Fast-forward" in text
    assert "GIT_TERMINAL_PROMPT" not in text


def test_cli_parser_defaults_match_documented_usage():
    config = updater.parse_args(["--repo-root", ".", "--wait-pid", "4321"])

    assert config.repo_root == Path(".")
    assert config.wait_pid == 4321
    assert config.wait_timeout_s == 120.0
    assert config.python_path is None
    assert config.app_path == Path("FreeRTOS-interface") / "App.py"
    assert config.no_relaunch is False
    assert config.relaunch_on_failure is False
    assert config.gui is False
    assert config.record_result is False
    assert config.latest_result_path is None
    assert config.git_timeout_s == 300.0
    assert config.log_path is None
    assert config.offline_manifest_path is None


def test_cli_parser_accepts_relaunch_on_failure():
    config = updater.parse_args(["--repo-root", ".", "--wait-pid", "4321", "--relaunch-on-failure"])

    assert config.relaunch_on_failure is True


def test_cli_parser_accepts_gui():
    config = updater.parse_args(["--repo-root", ".", "--gui", "--record-result", "--latest-result-path", "local/result.json"])

    assert config.gui is True
    assert config.record_result is True
    assert config.latest_result_path == Path("local/result.json")


def test_cli_parser_accepts_offline_manifest():
    config = updater.parse_args(["--repo-root", ".", "--offline-manifest", "LabCraftUpdates/update.json"])

    assert config.offline_manifest_path == Path("LabCraftUpdates/update.json")


def test_progress_events_for_clean_noop_update(tmp_path):
    runner = FakeGitRunner(tmp_path, before_sha="abc", after_sha="abc")
    events = []

    result = updater.run_update(
        _config(tmp_path),
        command_runner=runner,
        progress_callback=events.append,
    )

    assert result.status == updater.STATUS_ALREADY_CURRENT
    kinds = [event.kind for event in events]
    assert "starting" in kinds
    assert "checking_checkout" in kinds
    assert "checking_for_updates" in kinds
    assert "checking_local_changes" in kinds
    assert "applying_update" in kinds
    assert "complete" in kinds
    assert any(event.kind == "command" and "git pull --ff-only" in event.details for event in events)


def test_progress_events_for_dirty_worktree_failure(tmp_path):
    runner = FakeGitRunner(tmp_path, dirty_status=" M FreeRTOS-interface/App.py\n")
    events = []

    result = updater.run_update(
        _config(tmp_path),
        command_runner=runner,
        progress_callback=events.append,
    )

    assert result.status == updater.STATUS_DIRTY_WORKTREE
    kinds = [event.kind for event in events]
    assert "checking_local_changes" in kinds
    assert "failed" in kinds
    assert "applying_update" not in kinds


def test_progress_events_for_pull_failure(tmp_path):
    runner = FakeGitRunner(tmp_path, pull_returncode=128)
    events = []

    result = updater.run_update(
        _config(tmp_path),
        command_runner=runner,
        progress_callback=events.append,
    )

    assert result.status == updater.STATUS_GIT_PULL_FAILED
    kinds = [event.kind for event in events]
    assert "applying_update" in kinds
    assert "failed" in kinds
    assert any("fatal: Not possible to fast-forward" in event.details for event in events)


def test_progress_events_for_wait_timeout(tmp_path):
    runner = FakeGitRunner(tmp_path)
    events = []

    result = updater.run_update(
        _config(tmp_path, wait_pid=1234),
        command_runner=runner,
        waiter=lambda pid, timeout: False,
        progress_callback=events.append,
    )

    assert result.status == updater.STATUS_WAIT_TIMEOUT
    assert [event.kind for event in events] == ["starting", "waiting", "failed"]
    assert runner.calls == []


def test_update_check_clean_up_to_date_returns_up_to_date(tmp_path):
    runner = FakeGitRunner(tmp_path, ahead_count=0, behind_count=0)

    result = updater.run_update_check(_config(tmp_path), command_runner=runner)

    assert result.status == updater.STATUS_UP_TO_DATE
    assert result.returncode == 0
    assert result.message == "LabCraft is up to date."
    assert result.upstream == "origin/main"
    assert ("git", "fetch", "--prune") in [call[0] for call in runner.calls]


def test_update_check_behind_upstream_returns_update_available_with_commits(tmp_path):
    runner = FakeGitRunner(
        tmp_path,
        ahead_count=0,
        behind_count=2,
        check_commits=("def456 Add updater result dialog", "abc123 Improve update check"),
    )

    result = updater.run_update_check(_config(tmp_path), command_runner=runner)

    assert result.status == updater.STATUS_UPDATE_AVAILABLE
    assert result.behind_count == 2
    assert result.commits == (
        "def456 Add updater result dialog",
        "abc123 Improve update check",
    )


def test_update_check_dirty_worktree_blocks_before_fetch(tmp_path):
    runner = FakeGitRunner(tmp_path, dirty_status=" M FreeRTOS-interface/App.py\n")

    result = updater.run_update_check(_config(tmp_path), command_runner=runner)

    assert result.status == updater.STATUS_DIRTY_WORKTREE
    assert ("git", "fetch", "--prune") not in [call[0] for call in runner.calls]


def test_update_check_missing_upstream_returns_no_upstream(tmp_path):
    runner = FakeGitRunner(tmp_path, upstream_returncode=128)

    result = updater.run_update_check(_config(tmp_path), command_runner=runner)

    assert result.status == updater.STATUS_NO_UPSTREAM
    assert "upstream" in result.message


def test_update_check_diverged_returns_diverged(tmp_path):
    runner = FakeGitRunner(tmp_path, ahead_count=1, behind_count=2)

    result = updater.run_update_check(_config(tmp_path), command_runner=runner)

    assert result.status == updater.STATUS_DIVERGED
    assert result.ahead_count == 1
    assert result.behind_count == 2


def test_update_check_fetch_failure_returns_fetch_failed(tmp_path):
    runner = FakeGitRunner(tmp_path, fetch_returncode=128)

    result = updater.run_update_check(_config(tmp_path), command_runner=runner)

    assert result.status == updater.STATUS_FETCH_FAILED
    assert "remote repository" in result.message


def test_offline_update_check_skips_online_fetch_and_reports_available(tmp_path):
    manifest_path = _write_offline_manifest(tmp_path, head_sha=OFFLINE_SHA)
    runner = FakeGitRunner(
        tmp_path,
        offline_ref_sha=OFFLINE_SHA,
        offline_ahead_count=0,
        offline_behind_count=2,
        offline_check_commits=("def456 Offline update", "abc123 Earlier update"),
    )

    result = updater.run_update_check(
        _config(tmp_path, offline_manifest_path=manifest_path),
        command_runner=runner,
    )

    calls = [call[0] for call in runner.calls]
    assert result.status == updater.STATUS_UPDATE_AVAILABLE
    assert result.update_source == updater.UPDATE_SOURCE_OFFLINE
    assert result.offline_manifest_path == manifest_path.resolve()
    assert result.offline_bundle_path == (tmp_path / "labcraft-main.bundle").resolve()
    assert result.upstream == updater.OFFLINE_UPDATE_REF
    assert result.behind_count == 2
    assert result.commits == ("def456 Offline update", "abc123 Earlier update")
    assert ("git", "fetch", "--prune") not in calls
    assert ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}") not in calls
    assert any(call[:3] == ("git", "fetch", "--force") for call in calls)


def test_offline_update_check_accepts_incremental_manifest_metadata(tmp_path):
    manifest_path = _write_offline_manifest(tmp_path, head_sha=OFFLINE_SHA)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload.update(
        {
            "bundle_mode": "incremental",
            "base_selector": "abc123",
            "base_sha": "abc123abc123abc123abc123abc123abc123abc1",
            "base_short_sha": "abc123abc123",
            "incremental_commit_count": 2,
        }
    )
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    runner = FakeGitRunner(
        tmp_path,
        offline_ref_sha=OFFLINE_SHA,
        offline_ahead_count=0,
        offline_behind_count=1,
        offline_check_commits=("def456 Incremental update",),
    )

    result = updater.run_update_check(
        _config(tmp_path, offline_manifest_path=manifest_path),
        command_runner=runner,
    )

    assert result.status == updater.STATUS_UPDATE_AVAILABLE
    assert result.update_source == updater.UPDATE_SOURCE_OFFLINE
    assert result.commits == ("def456 Incremental update",)


def test_offline_update_check_up_to_date_and_diverged(tmp_path):
    manifest_path = _write_offline_manifest(tmp_path, head_sha=OFFLINE_SHA)

    up_to_date = updater.run_update_check(
        _config(tmp_path, offline_manifest_path=manifest_path),
        command_runner=FakeGitRunner(
            tmp_path,
            offline_ref_sha=OFFLINE_SHA,
            offline_ahead_count=0,
            offline_behind_count=0,
        ),
    )
    assert up_to_date.status == updater.STATUS_UP_TO_DATE
    assert up_to_date.update_source == updater.UPDATE_SOURCE_OFFLINE

    diverged = updater.run_update_check(
        _config(tmp_path, offline_manifest_path=manifest_path),
        command_runner=FakeGitRunner(
            tmp_path,
            offline_ref_sha=OFFLINE_SHA,
            offline_ahead_count=1,
            offline_behind_count=2,
        ),
    )
    assert diverged.status == updater.STATUS_DIVERGED
    assert diverged.update_source == updater.UPDATE_SOURCE_OFFLINE


@pytest.mark.parametrize(
    ("manifest_mutation", "runner_kwargs", "message_part"),
    [
        (lambda path: path.unlink(), {}, "was not found"),
        (lambda path: path.write_text("{ not json", encoding="utf-8"), {}, "not valid JSON"),
        (
            lambda path: path.write_text(
                json.dumps({**json.loads(path.read_text(encoding="utf-8")), "schema_version": "bad"}),
                encoding="utf-8",
            ),
            {},
            "unsupported schema",
        ),
        (
            lambda path: path.write_text(
                json.dumps({**json.loads(path.read_text(encoding="utf-8")), "branch": "stable"}),
                encoding="utf-8",
            ),
            {},
            "branch",
        ),
        (lambda path: (path.parent / "labcraft-main.bundle").unlink(), {}, "bundle was not found"),
        (
            lambda path: path.write_text(
                json.dumps({**json.loads(path.read_text(encoding="utf-8")), "bundle_sha256": "0" * 64}),
                encoding="utf-8",
            ),
            {},
            "SHA256",
        ),
        (lambda path: None, {"offline_verify_returncode": 1}, "verify"),
        (lambda path: None, {"offline_fetch_returncode": 1}, "fetch"),
        (lambda path: None, {"offline_ref_sha": OTHER_OFFLINE_SHA}, "head_sha"),
    ],
)
def test_offline_update_check_invalid_bundle_returns_offline_bundle_invalid(tmp_path, manifest_mutation, runner_kwargs, message_part):
    manifest_path = _write_offline_manifest(tmp_path, head_sha=OFFLINE_SHA)
    manifest_mutation(manifest_path)
    fake_kwargs = {"offline_ref_sha": OFFLINE_SHA}
    fake_kwargs.update(runner_kwargs)
    runner = FakeGitRunner(tmp_path, **fake_kwargs)

    result = updater.run_update_check(
        _config(tmp_path, offline_manifest_path=manifest_path),
        command_runner=runner,
    )

    assert result.status == updater.STATUS_OFFLINE_BUNDLE_INVALID
    assert result.returncode == updater.CHECK_EXIT_CODES[updater.STATUS_OFFLINE_BUNDLE_INVALID]
    assert result.update_source == updater.UPDATE_SOURCE_OFFLINE
    assert message_part in result.message


def test_offline_update_check_dirty_worktree_blocks_before_bundle_fetch(tmp_path):
    manifest_path = _write_offline_manifest(tmp_path, head_sha=OFFLINE_SHA)
    runner = FakeGitRunner(tmp_path, dirty_status=" M FreeRTOS-interface/App.py\n")

    result = updater.run_update_check(
        _config(tmp_path, offline_manifest_path=manifest_path),
        command_runner=runner,
    )

    assert result.status == updater.STATUS_DIRTY_WORKTREE
    assert not any(call[0][:3] == ("git", "fetch", "--force") for call in runner.calls)


def test_find_offline_update_manifests_scans_labcraftupdates_dirs_only(tmp_path):
    root = tmp_path / "usb"
    updates_dir = root / "LabCraftUpdates"
    nested_dir = updates_dir / "nested"
    nested_dir.mkdir(parents=True)
    manifest = updates_dir / "update.json"
    nested_manifest = nested_dir / "nested.json"
    manifest.write_text("{}", encoding="utf-8")
    nested_manifest.write_text("{}", encoding="utf-8")

    found = updater.find_offline_update_manifests([root])

    assert found == (manifest.resolve(),)


def test_offline_fallback_does_not_scan_when_online_check_succeeds(tmp_path):
    invalid_manifest = tmp_path / "missing.json"
    runner = FakeGitRunner(tmp_path, fetch_returncode=0, ahead_count=0, behind_count=0)

    result = updater.run_update_check_with_offline_fallback(
        _config(tmp_path),
        command_runner=runner,
        manifest_paths=[invalid_manifest],
    )

    assert result.status == updater.STATUS_UP_TO_DATE
    assert result.update_source == updater.UPDATE_SOURCE_ONLINE


def test_offline_fallback_selects_newest_update_available_bundle(tmp_path):
    old_manifest = _write_offline_manifest(
        tmp_path,
        head_sha=OFFLINE_SHA,
        bundle_name="old.bundle",
        created_at_utc="2026-06-18T10:00:00Z",
    )
    new_manifest = _write_offline_manifest(
        tmp_path,
        head_sha=OFFLINE_SHA,
        bundle_name="new.bundle",
        created_at_utc="2026-06-18T12:00:00Z",
    )
    runner = FakeGitRunner(
        tmp_path,
        fetch_returncode=128,
        offline_ref_sha=OFFLINE_SHA,
        offline_ahead_count=0,
        offline_behind_count=1,
        offline_check_commits=("def Offline update",),
    )

    result = updater.run_update_check_with_offline_fallback(
        _config(tmp_path),
        command_runner=runner,
        manifest_paths=[old_manifest, new_manifest],
    )

    assert result.status == updater.STATUS_UPDATE_AVAILABLE
    assert result.update_source == updater.UPDATE_SOURCE_OFFLINE
    assert result.offline_manifest_path == new_manifest.resolve()


def test_offline_fallback_returns_up_to_date_when_no_bundle_has_updates(tmp_path):
    manifest_path = _write_offline_manifest(tmp_path, head_sha=OFFLINE_SHA)
    runner = FakeGitRunner(
        tmp_path,
        fetch_returncode=128,
        offline_ref_sha=OFFLINE_SHA,
        offline_ahead_count=0,
        offline_behind_count=0,
    )

    result = updater.run_update_check_with_offline_fallback(
        _config(tmp_path),
        command_runner=runner,
        manifest_paths=[manifest_path],
    )

    assert result.status == updater.STATUS_UP_TO_DATE
    assert result.update_source == updater.UPDATE_SOURCE_OFFLINE


def test_offline_fallback_skips_invalid_and_diverged_candidates(tmp_path):
    wrong_branch = _write_offline_manifest(
        tmp_path,
        branch="stable",
        bundle_name="wrong-branch.bundle",
        created_at_utc="2026-06-18T13:00:00Z",
    )
    diverged = _write_offline_manifest(
        tmp_path,
        head_sha=OFFLINE_SHA,
        bundle_name="diverged.bundle",
        created_at_utc="2026-06-18T12:00:00Z",
    )
    valid = _write_offline_manifest(
        tmp_path,
        head_sha=OFFLINE_SHA,
        bundle_name="valid.bundle",
        created_at_utc="2026-06-18T11:00:00Z",
    )
    base_runner = FakeGitRunner(tmp_path, fetch_returncode=128, offline_ref_sha=OFFLINE_SHA)
    state = {"bundle_name": ""}

    def runner(args, cwd, timeout_s, env_updates):
        args_tuple = tuple(str(arg) for arg in args)
        git_args = args_tuple[1:]
        if len(git_args) == 4 and git_args[:2] == ("fetch", "--force"):
            state["bundle_name"] = Path(git_args[2]).name
        if git_args == ("rev-list", "--left-right", "--count", f"HEAD...{updater.OFFLINE_UPDATE_REF}"):
            if state["bundle_name"] == "diverged.bundle":
                return updater.CommandResult(args_tuple, 0, stdout="1\t2\n")
            return updater.CommandResult(args_tuple, 0, stdout="0\t1\n")
        if git_args == ("log", "--oneline", f"HEAD..{updater.OFFLINE_UPDATE_REF}"):
            return updater.CommandResult(args_tuple, 0, stdout="def Offline update\n")
        return base_runner(args, cwd, timeout_s, env_updates)

    result = updater.run_update_check_with_offline_fallback(
        _config(tmp_path),
        command_runner=runner,
        manifest_paths=[valid, diverged, wrong_branch],
    )

    assert result.status == updater.STATUS_UPDATE_AVAILABLE
    assert result.offline_manifest_path == valid.resolve()


def test_offline_fallback_preserves_fetch_failed_when_no_usable_bundle(tmp_path):
    manifest_path = tmp_path / "missing.json"
    runner = FakeGitRunner(tmp_path, fetch_returncode=128)

    result = updater.run_update_check_with_offline_fallback(
        _config(tmp_path),
        command_runner=runner,
        manifest_paths=[manifest_path],
    )

    assert result.status == updater.STATUS_FETCH_FAILED
    assert result.update_source == updater.UPDATE_SOURCE_ONLINE
    assert "No usable offline update bundle was found." in result.message


def test_latest_result_json_written_for_updated_result(tmp_path):
    runner = FakeGitRunner(
        tmp_path,
        before_sha="abc",
        after_sha="def",
        pull_stdout="Fast-forward\n",
        update_commits=("def Updated app",),
    )

    result = updater.run_update(
        updater.UpdaterConfig(repo_root=tmp_path, no_relaunch=True, record_result=True),
        command_runner=runner,
    )

    result_path = updater.default_latest_result_path(tmp_path)
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert result.status == updater.STATUS_UPDATED
    assert payload["status"] == updater.STATUS_UPDATED
    assert payload["before_sha"] == "abc"
    assert payload["after_sha"] == "def"
    assert payload["commits"] == ["def Updated app"]


def test_latest_result_json_written_for_offline_updated_result(tmp_path):
    manifest_path = _write_offline_manifest(tmp_path, head_sha=OFFLINE_SHA)
    runner = FakeGitRunner(
        tmp_path,
        before_sha="abc",
        after_sha=OFFLINE_SHA,
        offline_ref_sha=OFFLINE_SHA,
        update_commits=("def Offline update",),
    )

    result = updater.run_update(
        updater.UpdaterConfig(
            repo_root=tmp_path,
            no_relaunch=True,
            record_result=True,
            offline_manifest_path=manifest_path,
        ),
        command_runner=runner,
    )

    result_path = updater.default_latest_result_path(tmp_path)
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert result.status == updater.STATUS_UPDATED
    assert payload["status"] == updater.STATUS_UPDATED
    assert payload["update_source"] == updater.UPDATE_SOURCE_OFFLINE
    assert payload["offline_manifest_path"] == str(manifest_path.resolve())


def test_latest_result_json_written_for_already_current_result(tmp_path):
    runner = FakeGitRunner(tmp_path, before_sha="abc", after_sha="abc")

    result = updater.run_update(
        updater.UpdaterConfig(repo_root=tmp_path, no_relaunch=True, record_result=True),
        command_runner=runner,
    )

    payload = json.loads(updater.default_latest_result_path(tmp_path).read_text(encoding="utf-8"))
    assert result.status == updater.STATUS_ALREADY_CURRENT
    assert payload["status"] == updater.STATUS_ALREADY_CURRENT
    assert payload["commits"] == []


def test_latest_result_json_written_for_failed_result(tmp_path):
    runner = FakeGitRunner(tmp_path, dirty_status=" M FreeRTOS-interface/App.py\n")

    result = updater.run_update(
        updater.UpdaterConfig(repo_root=tmp_path, no_relaunch=True, record_result=True),
        command_runner=runner,
    )

    payload = json.loads(updater.default_latest_result_path(tmp_path).read_text(encoding="utf-8"))
    assert result.status == updater.STATUS_DIRTY_WORKTREE
    assert payload["status"] == updater.STATUS_DIRTY_WORKTREE
    assert "local developer changes" in payload["message"]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        shell=False,
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_real_git_offline_bundle_check_and_update(tmp_path):
    remote = tmp_path / "remote.git"
    support = tmp_path / "support"
    deployed = tmp_path / "deployed"
    output_dir = tmp_path / "updates"

    _git(tmp_path, "init", "--bare", str(remote))
    support.mkdir()
    _git(support, "init")
    _git(support, "config", "user.email", "test@example.com")
    _git(support, "config", "user.name", "Test User")
    (support / "README.md").write_text("initial\n", encoding="utf-8")
    _git(support, "add", "README.md")
    _git(support, "commit", "-m", "initial")
    _git(support, "branch", "-M", "stable")
    _git(support, "remote", "add", "origin", str(remote))
    _git(support, "push", "-u", "origin", "stable")

    _git(tmp_path, "clone", "--branch", "stable", str(remote), str(deployed))
    deployed_start = _git(deployed, "rev-parse", "HEAD").stdout.strip()

    (support / "README.md").write_text("initial\nupdated\n", encoding="utf-8")
    _git(support, "commit", "-am", "update app")
    _git(support, "push", "origin", "stable")

    bundle_result = create_update_bundle.create_update_bundle(
        create_update_bundle.BundleConfig(repo_root=support, branch="stable", output_dir=output_dir),
    )
    manifest_path = bundle_result.manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    check = updater.run_update_check(
        updater.UpdaterConfig(repo_root=deployed, log_path=tmp_path / "check.log", offline_manifest_path=manifest_path),
    )
    assert check.status == updater.STATUS_UPDATE_AVAILABLE
    assert check.update_source == updater.UPDATE_SOURCE_OFFLINE
    assert check.behind_count == 1
    assert check.head_sha == deployed_start
    assert check.upstream_sha == manifest["head_sha"]

    result = updater.run_update(
        updater.UpdaterConfig(repo_root=deployed, no_relaunch=True, log_path=tmp_path / "update.log", offline_manifest_path=manifest_path),
    )

    assert result.status == updater.STATUS_UPDATED
    assert result.update_source == updater.UPDATE_SOURCE_OFFLINE
    assert result.after_sha == manifest["head_sha"]
    assert _git(deployed, "rev-parse", "HEAD").stdout.strip() == manifest["head_sha"]
