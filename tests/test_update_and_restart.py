import json
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
        upstream: str = "origin/main",
        upstream_returncode: int = 0,
        upstream_sha: str = "upstream456",
        fetch_returncode: int = 0,
        ahead_count: int = 0,
        behind_count: int = 0,
        check_commits: tuple[str, ...] = (),
        update_commits: tuple[str, ...] = (),
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

        if git_args == ("fetch", "--prune"):
            if self.fetch_returncode:
                return updater.CommandResult(args_tuple, self.fetch_returncode, stderr="network unavailable")
            return updater.CommandResult(args_tuple, 0, stdout="")

        if git_args == ("rev-parse", "@{u}"):
            return updater.CommandResult(args_tuple, 0, stdout=f"{self.upstream_sha}\n")

        if git_args == ("rev-list", "--left-right", "--count", "HEAD...@{u}"):
            return updater.CommandResult(args_tuple, 0, stdout=f"{self.ahead_count}\t{self.behind_count}\n")

        if git_args == ("log", "--oneline", "HEAD..@{u}"):
            return updater.CommandResult(args_tuple, 0, stdout="\n".join(self.check_commits) + ("\n" if self.check_commits else ""))

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
    assert config.record_result is False
    assert config.latest_result_path is None
    assert config.git_timeout_s == 300.0
    assert config.log_path is None


def test_cli_parser_accepts_relaunch_on_failure():
    config = updater.parse_args(["--repo-root", ".", "--wait-pid", "4321", "--relaunch-on-failure"])

    assert config.relaunch_on_failure is True


def test_cli_parser_accepts_gui():
    config = updater.parse_args(["--repo-root", ".", "--gui", "--record-result", "--latest-result-path", "local/result.json"])

    assert config.gui is True
    assert config.record_result is True
    assert config.latest_result_path == Path("local/result.json")


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
