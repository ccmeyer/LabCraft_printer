from pathlib import Path

import tools.update_and_restart as updater


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

        if git_args == ("status", "--porcelain"):
            return updater.CommandResult(args_tuple, self.status_returncode, stdout=self.dirty_status)

        if git_args == ("pull", "--ff-only"):
            return updater.CommandResult(
                args_tuple,
                self.pull_returncode,
                stdout=self.pull_stdout if self.pull_returncode == 0 else "",
                stderr="" if self.pull_returncode == 0 else "fatal: Not possible to fast-forward",
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
    assert config.git_timeout_s == 300.0
    assert config.log_path is None


def test_cli_parser_accepts_relaunch_on_failure():
    config = updater.parse_args(["--repo-root", ".", "--wait-pid", "4321", "--relaunch-on-failure"])

    assert config.relaunch_on_failure is True


def test_cli_parser_accepts_gui():
    config = updater.parse_args(["--repo-root", ".", "--gui"])

    assert config.gui is True


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
