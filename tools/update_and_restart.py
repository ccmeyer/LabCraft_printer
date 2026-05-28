#!/usr/bin/env python3
"""Conservative Git updater for the LabCraft app.

This is the standalone backend for the app-update flow. It intentionally avoids
stash/reset/clean/merge behavior so an operator update either fast-forwards the
checkout cleanly or leaves it untouched.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence


STATUS_UPDATED = "updated"
STATUS_ALREADY_CURRENT = "already_current"
STATUS_NOT_GIT_REPO = "not_git_repo"
STATUS_DIRTY_WORKTREE = "dirty_worktree"
STATUS_WAIT_TIMEOUT = "wait_timeout"
STATUS_GIT_PULL_FAILED = "git_pull_failed"
STATUS_RELAUNCH_FAILED = "relaunch_failed"
STATUS_UPDATE_AVAILABLE = "update_available"
STATUS_UP_TO_DATE = "up_to_date"
STATUS_NO_UPSTREAM = "no_upstream"
STATUS_DIVERGED = "diverged"
STATUS_FETCH_FAILED = "fetch_failed"

EXIT_CODES = {
    STATUS_UPDATED: 0,
    STATUS_ALREADY_CURRENT: 0,
    STATUS_NOT_GIT_REPO: 2,
    STATUS_DIRTY_WORKTREE: 3,
    STATUS_WAIT_TIMEOUT: 4,
    STATUS_GIT_PULL_FAILED: 5,
    STATUS_RELAUNCH_FAILED: 6,
}

CHECK_EXIT_CODES = {
    STATUS_UPDATE_AVAILABLE: 0,
    STATUS_UP_TO_DATE: 0,
    STATUS_NOT_GIT_REPO: 2,
    STATUS_DIRTY_WORKTREE: 3,
    STATUS_NO_UPSTREAM: 7,
    STATUS_DIVERGED: 8,
    STATUS_FETCH_FAILED: 9,
}

DEFAULT_APP_PATH = Path("FreeRTOS-interface") / "App.py"
DEFAULT_WAIT_TIMEOUT_S = 120.0
DEFAULT_GIT_TIMEOUT_S = 300.0


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class UpdateResult:
    status: str
    returncode: int
    message: str
    repo_root: Path | None
    branch: str = ""
    before_sha: str = ""
    after_sha: str = ""
    log_path: Path | None = None


@dataclass(frozen=True)
class UpdateCheckResult:
    status: str
    returncode: int
    message: str
    repo_root: Path | None
    branch: str = ""
    upstream: str = ""
    head_sha: str = ""
    upstream_sha: str = ""
    ahead_count: int = 0
    behind_count: int = 0
    commits: tuple[str, ...] = ()
    log_path: Path | None = None


@dataclass(frozen=True)
class ProgressEvent:
    kind: str
    message: str
    details: str = ""
    command_result: CommandResult | None = None
    result: UpdateResult | None = None
    log_path: Path | None = None


@dataclass(frozen=True)
class UpdaterConfig:
    repo_root: Path = Path(".")
    wait_pid: int | None = None
    wait_timeout_s: float = DEFAULT_WAIT_TIMEOUT_S
    python_path: Path | None = None
    app_path: Path = DEFAULT_APP_PATH
    no_relaunch: bool = False
    relaunch_on_failure: bool = False
    gui: bool = False
    record_result: bool = False
    latest_result_path: Path | None = None
    git_timeout_s: float = DEFAULT_GIT_TIMEOUT_S
    log_path: Path | None = None
    platform_name: str | None = None


CommandRunner = Callable[[Sequence[str], Path, float, Mapping[str, str] | None], CommandResult]
Launcher = Callable[[Sequence[str], Path], object]
Waiter = Callable[[int, float], bool]
ProgressCallback = Callable[[ProgressEvent], None]


class _LogBuffer:
    def __init__(self) -> None:
        self._lines: list[str] = []

    def add(self, message: str = "") -> None:
        stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if message:
            self._lines.append(f"[{stamp}] {message}")
        else:
            self._lines.append("")

    def add_command(self, result: CommandResult) -> None:
        self.add(f"$ {' '.join(result.args)}")
        self.add(f"returncode: {result.returncode}")
        if result.stdout:
            self.add("stdout:")
            self._lines.extend(result.stdout.rstrip().splitlines())
        if result.stderr:
            self.add("stderr:")
            self._lines.extend(result.stderr.rstrip().splitlines())
        self.add()

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(self._lines).rstrip() + "\n", encoding="utf-8")
        return path


def _utc_file_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def default_log_path(repo_root: Path) -> Path:
    return repo_root / "local" / "update_logs" / f"update_{_utc_file_stamp()}.log"


def default_latest_result_path(repo_root: Path) -> Path:
    return repo_root / "local" / "update_logs" / "latest_update_result.json"


def _resolve_under_repo(repo_root: Path, value: Path | str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repo_root / path


def _is_windows(platform_name: str | None = None) -> bool:
    if platform_name is None:
        return os.name == "nt" or sys.platform.startswith("win")
    return platform_name.lower().startswith("win")


def resolve_python_path(
    repo_root: Path,
    explicit: Path | str | None = None,
    *,
    platform_name: str | None = None,
) -> Path:
    if explicit is not None:
        return _resolve_under_repo(repo_root, explicit)

    if _is_windows(platform_name):
        candidates = (
            Path("env") / "Scripts" / "python.exe",
            Path(".venv") / "Scripts" / "python.exe",
            Path("venv") / "Scripts" / "python.exe",
        )
    else:
        candidates = (
            Path("venv") / "bin" / "python",
            Path(".venv") / "bin" / "python",
            Path("env") / "bin" / "python",
        )

    for rel_path in candidates:
        candidate = repo_root / rel_path
        if candidate.is_file():
            return candidate

    return Path(sys.executable)


def default_command_runner(
    args: Sequence[str],
    cwd: Path,
    timeout_s: float,
    env_updates: Mapping[str, str] | None = None,
) -> CommandResult:
    env = os.environ.copy()
    if env_updates:
        env.update(env_updates)

    str_args = tuple(str(arg) for arg in args)
    try:
        completed = subprocess.run(
            list(str_args),
            cwd=str(cwd),
            env=env,
            shell=False,
            capture_output=True,
            text=True,
            check=False,
            timeout=max(0.0, float(timeout_s)),
        )
        return CommandResult(
            args=str_args,
            returncode=int(completed.returncode),
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
    except FileNotFoundError as exc:
        return CommandResult(args=str_args, returncode=127, stderr=str(exc))
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        timeout_msg = f"Command timed out after {timeout_s:.1f} seconds."
        return CommandResult(args=str_args, returncode=124, stdout=stdout, stderr=(stderr + "\n" + timeout_msg).strip())


def _run_git(
    repo_root: Path,
    git_args: Sequence[str],
    timeout_s: float,
    command_runner: CommandRunner,
) -> CommandResult:
    return command_runner(
        ["git", *git_args],
        repo_root,
        timeout_s,
        {"GIT_TERMINAL_PROMPT": "0"},
    )


def _process_exists_posix(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        return True
    return True


def _wait_for_process_exit_windows(pid: int, timeout_s: float) -> bool:
    try:
        kernel32 = ctypes.windll.kernel32
    except AttributeError:
        return _wait_for_process_exit_by_polling(pid, timeout_s)

    synchronize = 0x00100000
    process_query_limited_information = 0x1000
    wait_object_0 = 0x00000000
    wait_timeout = 0x00000102
    wait_failed = 0xFFFFFFFF
    error_invalid_parameter = 87

    handle = kernel32.OpenProcess(
        synchronize | process_query_limited_information,
        False,
        int(pid),
    )
    if not handle:
        err = int(kernel32.GetLastError())
        return err == error_invalid_parameter

    try:
        timeout_ms = max(0, int(float(timeout_s) * 1000))
        result = int(kernel32.WaitForSingleObject(handle, timeout_ms))
        if result == wait_object_0:
            return True
        if result == wait_timeout:
            return False
        if result == wait_failed:
            return _wait_for_process_exit_by_polling(pid, timeout_s)
        return False
    finally:
        kernel32.CloseHandle(handle)


def _wait_for_process_exit_by_polling(
    pid: int,
    timeout_s: float,
    *,
    process_exists: Callable[[int], bool] = _process_exists_posix,
    sleep: Callable[[float], None] = time.sleep,
    poll_s: float = 0.25,
) -> bool:
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    while time.monotonic() <= deadline:
        if not process_exists(int(pid)):
            return True
        sleep(max(0.01, float(poll_s)))
    return not process_exists(int(pid))


def wait_for_process_exit(pid: int, timeout_s: float, *, platform_name: str | None = None) -> bool:
    if _is_windows(platform_name):
        return _wait_for_process_exit_windows(pid, timeout_s)
    return _wait_for_process_exit_by_polling(pid, timeout_s)


def default_launcher(command: Sequence[str], cwd: Path) -> object:
    return subprocess.Popen([str(part) for part in command], cwd=str(cwd), shell=False)


def format_command_result(result: CommandResult) -> str:
    lines = [f"$ {' '.join(result.args)}", f"returncode: {result.returncode}"]
    if result.stdout:
        lines.append("stdout:")
        lines.extend(result.stdout.rstrip().splitlines())
    if result.stderr:
        lines.append("stderr:")
        lines.extend(result.stderr.rstrip().splitlines())
    return "\n".join(lines)


def _emit_progress(
    progress_callback: ProgressCallback | None,
    kind: str,
    message: str,
    *,
    details: str = "",
    command_result: CommandResult | None = None,
    result: UpdateResult | None = None,
    log_path: Path | None = None,
) -> None:
    if progress_callback is None:
        return
    progress_callback(
        ProgressEvent(
            kind=kind,
            message=message,
            details=details,
            command_result=command_result,
            result=result,
            log_path=log_path,
        )
    )


def _record_command(
    log: _LogBuffer,
    result: CommandResult,
    progress_callback: ProgressCallback | None,
) -> None:
    log.add_command(result)
    _emit_progress(
        progress_callback,
        "command",
        "Command completed.",
        details=format_command_result(result),
        command_result=result,
    )


def build_relaunch_command(config: UpdaterConfig, repo_root: Path) -> list[str]:
    python_path = resolve_python_path(repo_root, config.python_path, platform_name=config.platform_name)
    app_path = _resolve_under_repo(repo_root, config.app_path)
    return [str(python_path), str(app_path)]


def relaunch_app(
    config: UpdaterConfig,
    repo_root: Path,
    *,
    launcher: Launcher = default_launcher,
) -> tuple[bool, str, list[str]]:
    command = build_relaunch_command(config, repo_root)
    try:
        launcher(command, repo_root)
    except Exception as exc:
        return False, str(exc), command
    return True, "", command


def update_result_payload(result: UpdateResult, *, commits: Sequence[str] = ()) -> dict:
    return {
        "status": result.status,
        "message": result.message,
        "branch": result.branch,
        "before_sha": result.before_sha,
        "after_sha": result.after_sha,
        "log_path": str(result.log_path) if result.log_path is not None else "",
        "updated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "commits": [str(commit) for commit in commits],
    }


def write_latest_update_result(
    result: UpdateResult,
    repo_root: Path,
    *,
    result_path: Path | None = None,
    commits: Sequence[str] = (),
) -> Path:
    path = result_path or default_latest_result_path(repo_root)
    path = path if path.is_absolute() else repo_root / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(update_result_payload(result, commits=commits), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _collect_update_commits(
    result: UpdateResult,
    config: UpdaterConfig,
    command_runner: CommandRunner,
) -> tuple[str, ...]:
    if result.repo_root is None:
        return ()
    if result.status != STATUS_UPDATED:
        return ()
    if not result.before_sha or not result.after_sha or result.before_sha == result.after_sha:
        return ()

    log_result = _run_git(
        result.repo_root,
        ["log", "--oneline", f"{result.before_sha}..{result.after_sha}"],
        config.git_timeout_s,
        command_runner,
    )
    if log_result.returncode != 0:
        return ()
    return _split_commit_lines(log_result.stdout)


def _maybe_write_latest_update_result(
    config: UpdaterConfig,
    result: UpdateResult,
    fallback_root: Path,
    command_runner: CommandRunner,
) -> Path | None:
    if not config.record_result:
        return None

    repo_root = result.repo_root or fallback_root
    result_path = config.latest_result_path
    if result_path is not None and not result_path.is_absolute():
        result_path = repo_root / result_path
    commits = _collect_update_commits(result, config, command_runner)
    return write_latest_update_result(
        result,
        repo_root,
        result_path=result_path,
        commits=commits,
    )


def _attempt_relaunch(
    config: UpdaterConfig,
    repo_root: Path,
    log: _LogBuffer,
    launcher: Launcher,
    *,
    context: str,
    progress_callback: ProgressCallback | None = None,
) -> str | None:
    if config.no_relaunch:
        log.add(f"{context} relaunch skipped by --no-relaunch.")
        return None

    _emit_progress(progress_callback, "launching_app", "Starting LabCraft...")
    ok, message, command = relaunch_app(config, repo_root, launcher=launcher)
    log.add(f"python: {command[0]}")
    log.add(f"app: {command[1]}")
    log.add(f"{context}_relaunch_command: {' '.join(command)}")
    return None if ok else message


def _make_result(
    status: str,
    message: str,
    *,
    repo_root: Path | None,
    branch: str = "",
    before_sha: str = "",
    after_sha: str = "",
    log_path: Path | None = None,
) -> UpdateResult:
    return UpdateResult(
        status=status,
        returncode=EXIT_CODES[status],
        message=message,
        repo_root=repo_root,
        branch=branch,
        before_sha=before_sha,
        after_sha=after_sha,
        log_path=log_path,
    )


def _make_check_result(
    status: str,
    message: str,
    *,
    repo_root: Path | None,
    branch: str = "",
    upstream: str = "",
    head_sha: str = "",
    upstream_sha: str = "",
    ahead_count: int = 0,
    behind_count: int = 0,
    commits: Sequence[str] = (),
    log_path: Path | None = None,
) -> UpdateCheckResult:
    return UpdateCheckResult(
        status=status,
        returncode=CHECK_EXIT_CODES[status],
        message=message,
        repo_root=repo_root,
        branch=branch,
        upstream=upstream,
        head_sha=head_sha,
        upstream_sha=upstream_sha,
        ahead_count=int(ahead_count),
        behind_count=int(behind_count),
        commits=tuple(str(commit) for commit in commits),
        log_path=log_path,
    )


def _parse_rev_list_counts(text: str) -> tuple[int, int] | None:
    parts = str(text or "").strip().split()
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _split_commit_lines(text: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in str(text or "").splitlines() if line.strip())


def run_update_check(
    config: UpdaterConfig,
    *,
    command_runner: CommandRunner = default_command_runner,
) -> UpdateCheckResult:
    requested_root = Path(config.repo_root).resolve()
    log = _LogBuffer()
    log.add("LabCraft update check started.")
    log.add(f"platform: {platform.platform()}")
    log.add(f"requested_repo_root: {requested_root}")

    log_path = Path(config.log_path).resolve() if config.log_path is not None else default_log_path(requested_root)

    top_level = _run_git(requested_root, ["rev-parse", "--show-toplevel"], config.git_timeout_s, command_runner)
    log.add_command(top_level)
    if top_level.returncode != 0 or not top_level.stdout.strip():
        return _finish_check_result(
            _make_check_result(
                STATUS_NOT_GIT_REPO,
                "Update check cannot continue because the selected path is not a Git checkout.",
                repo_root=None,
                log_path=log_path,
            ),
            log,
            log_path,
        )

    repo_root = Path(top_level.stdout.strip()).resolve()
    if config.log_path is None:
        log_path = default_log_path(repo_root)
    log.add(f"repo_root: {repo_root}")

    branch_result = _run_git(repo_root, ["branch", "--show-current"], config.git_timeout_s, command_runner)
    log.add_command(branch_result)
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""

    head_result = _run_git(repo_root, ["rev-parse", "HEAD"], config.git_timeout_s, command_runner)
    log.add_command(head_result)
    head_sha = head_result.stdout.strip() if head_result.returncode == 0 else ""

    status_result = _run_git(repo_root, ["status", "--porcelain"], config.git_timeout_s, command_runner)
    log.add_command(status_result)
    if status_result.returncode != 0:
        return _finish_check_result(
            _make_check_result(
                STATUS_FETCH_FAILED,
                "Update check cannot continue because Git status failed.",
                repo_root=repo_root,
                branch=branch,
                head_sha=head_sha,
                log_path=log_path,
            ),
            log,
            log_path,
        )
    if status_result.stdout.strip():
        return _finish_check_result(
            _make_check_result(
                STATUS_DIRTY_WORKTREE,
                "Update check found local developer changes. Contact support before updating.",
                repo_root=repo_root,
                branch=branch,
                head_sha=head_sha,
                log_path=log_path,
            ),
            log,
            log_path,
        )

    upstream_result = _run_git(repo_root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], config.git_timeout_s, command_runner)
    log.add_command(upstream_result)
    if upstream_result.returncode != 0 or not upstream_result.stdout.strip():
        return _finish_check_result(
            _make_check_result(
                STATUS_NO_UPSTREAM,
                "Update check cannot find an upstream branch for this checkout. Contact support.",
                repo_root=repo_root,
                branch=branch,
                head_sha=head_sha,
                log_path=log_path,
            ),
            log,
            log_path,
        )
    upstream = upstream_result.stdout.strip()

    fetch_result = _run_git(repo_root, ["fetch", "--prune"], config.git_timeout_s, command_runner)
    log.add_command(fetch_result)
    if fetch_result.returncode != 0:
        return _finish_check_result(
            _make_check_result(
                STATUS_FETCH_FAILED,
                "Update check could not contact the remote repository. Check network access or contact support.",
                repo_root=repo_root,
                branch=branch,
                upstream=upstream,
                head_sha=head_sha,
                log_path=log_path,
            ),
            log,
            log_path,
        )

    upstream_sha_result = _run_git(repo_root, ["rev-parse", "@{u}"], config.git_timeout_s, command_runner)
    log.add_command(upstream_sha_result)
    upstream_sha = upstream_sha_result.stdout.strip() if upstream_sha_result.returncode == 0 else ""

    count_result = _run_git(repo_root, ["rev-list", "--left-right", "--count", "HEAD...@{u}"], config.git_timeout_s, command_runner)
    log.add_command(count_result)
    counts = _parse_rev_list_counts(count_result.stdout)
    if count_result.returncode != 0 or counts is None:
        return _finish_check_result(
            _make_check_result(
                STATUS_FETCH_FAILED,
                "Update check could not compare this checkout with the remote branch. Contact support.",
                repo_root=repo_root,
                branch=branch,
                upstream=upstream,
                head_sha=head_sha,
                upstream_sha=upstream_sha,
                log_path=log_path,
            ),
            log,
            log_path,
        )

    ahead_count, behind_count = counts
    if ahead_count > 0 and behind_count > 0:
        return _finish_check_result(
            _make_check_result(
                STATUS_DIVERGED,
                "This checkout has diverged from the remote branch. Contact support before updating.",
                repo_root=repo_root,
                branch=branch,
                upstream=upstream,
                head_sha=head_sha,
                upstream_sha=upstream_sha,
                ahead_count=ahead_count,
                behind_count=behind_count,
                log_path=log_path,
            ),
            log,
            log_path,
        )

    commits: tuple[str, ...] = ()
    if behind_count > 0:
        log_result = _run_git(repo_root, ["log", "--oneline", "HEAD..@{u}"], config.git_timeout_s, command_runner)
        log.add_command(log_result)
        commits = _split_commit_lines(log_result.stdout) if log_result.returncode == 0 else ()
        return _finish_check_result(
            _make_check_result(
                STATUS_UPDATE_AVAILABLE,
                f"{behind_count} update commit{'s' if behind_count != 1 else ''} available.",
                repo_root=repo_root,
                branch=branch,
                upstream=upstream,
                head_sha=head_sha,
                upstream_sha=upstream_sha,
                ahead_count=ahead_count,
                behind_count=behind_count,
                commits=commits,
                log_path=log_path,
            ),
            log,
            log_path,
        )

    message = "LabCraft is up to date."
    if ahead_count > 0:
        message = "No remote update is available. This checkout has local commits not present upstream."
    return _finish_check_result(
        _make_check_result(
            STATUS_UP_TO_DATE,
            message,
            repo_root=repo_root,
            branch=branch,
            upstream=upstream,
            head_sha=head_sha,
            upstream_sha=upstream_sha,
            ahead_count=ahead_count,
            behind_count=behind_count,
            log_path=log_path,
        ),
        log,
        log_path,
    )


def _finish_check_result(result: UpdateCheckResult, log: _LogBuffer, log_path: Path) -> UpdateCheckResult:
    result = UpdateCheckResult(
        status=result.status,
        returncode=result.returncode,
        message=result.message,
        repo_root=result.repo_root,
        branch=result.branch,
        upstream=result.upstream,
        head_sha=result.head_sha,
        upstream_sha=result.upstream_sha,
        ahead_count=result.ahead_count,
        behind_count=result.behind_count,
        commits=result.commits,
        log_path=log_path,
    )
    log.add(f"status: {result.status}")
    log.add(result.message)
    log.write(log_path)
    return result


def run_update(
    config: UpdaterConfig,
    *,
    command_runner: CommandRunner = default_command_runner,
    launcher: Launcher = default_launcher,
    waiter: Waiter | None = None,
    progress_callback: ProgressCallback | None = None,
) -> UpdateResult:
    requested_root = Path(config.repo_root).resolve()
    log = _LogBuffer()
    log.add("LabCraft updater started.")
    log.add(f"platform: {platform.platform()}")
    log.add(f"requested_repo_root: {requested_root}")

    log_path = Path(config.log_path).resolve() if config.log_path is not None else default_log_path(requested_root)

    _emit_progress(progress_callback, "starting", "Starting LabCraft updater...", log_path=log_path)

    if config.wait_pid is not None:
        log.add(f"waiting_for_pid: {config.wait_pid}")
        _emit_progress(
            progress_callback,
            "waiting",
            "Waiting for LabCraft to close...",
            log_path=log_path,
        )
        wait_func = waiter or (lambda pid, timeout: wait_for_process_exit(pid, timeout, platform_name=config.platform_name))
        if not wait_func(int(config.wait_pid), float(config.wait_timeout_s)):
            result = _make_result(
                STATUS_WAIT_TIMEOUT,
                f"Timed out waiting for process {config.wait_pid} to exit.",
                repo_root=None,
                log_path=log_path,
            )
            return _finish_failure_result(result, requested_root, config, log, launcher, log_path, progress_callback)

    _emit_progress(progress_callback, "checking_checkout", "Checking local checkout...", log_path=log_path)
    top_level = _run_git(requested_root, ["rev-parse", "--show-toplevel"], config.git_timeout_s, command_runner)
    _record_command(log, top_level, progress_callback)
    if top_level.returncode != 0 or not top_level.stdout.strip():
        result = _make_result(
            STATUS_NOT_GIT_REPO,
            "Update cannot continue because the selected path is not a Git checkout.",
            repo_root=None,
            log_path=log_path,
        )
        return _finish_failure_result(result, requested_root, config, log, launcher, log_path, progress_callback)

    repo_root = Path(top_level.stdout.strip()).resolve()
    if config.log_path is None:
        log_path = default_log_path(repo_root)
    log.add(f"repo_root: {repo_root}")
    _emit_progress(progress_callback, "checking_for_updates", "Checking for updates...", log_path=log_path)

    branch_result = _run_git(repo_root, ["branch", "--show-current"], config.git_timeout_s, command_runner)
    _record_command(log, branch_result, progress_callback)
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""

    before_result = _run_git(repo_root, ["rev-parse", "HEAD"], config.git_timeout_s, command_runner)
    _record_command(log, before_result, progress_callback)
    if before_result.returncode != 0 or not before_result.stdout.strip():
        result = _make_result(
            STATUS_GIT_PULL_FAILED,
            "Update cannot continue because the current commit could not be resolved.",
            repo_root=repo_root,
            branch=branch,
            log_path=log_path,
        )
        return _finish_failure_result(result, repo_root, config, log, launcher, log_path, progress_callback)
    before_sha = before_result.stdout.strip()

    _emit_progress(progress_callback, "checking_local_changes", "Checking local changes...", log_path=log_path)
    status_result = _run_git(repo_root, ["status", "--porcelain"], config.git_timeout_s, command_runner)
    _record_command(log, status_result, progress_callback)
    if status_result.returncode != 0:
        result = _make_result(
            STATUS_GIT_PULL_FAILED,
            "Update cannot continue because Git status failed.",
            repo_root=repo_root,
            branch=branch,
            before_sha=before_sha,
            log_path=log_path,
        )
        return _finish_failure_result(result, repo_root, config, log, launcher, log_path, progress_callback)
    if status_result.stdout.strip():
        result = _make_result(
            STATUS_DIRTY_WORKTREE,
            "Update cannot continue because this installation has local developer changes. The current app version was not changed.",
            repo_root=repo_root,
            branch=branch,
            before_sha=before_sha,
            after_sha=before_sha,
            log_path=log_path,
        )
        return _finish_failure_result(result, repo_root, config, log, launcher, log_path, progress_callback)

    _emit_progress(progress_callback, "applying_update", "Downloading and applying update...", log_path=log_path)
    pull_result = _run_git(repo_root, ["pull", "--ff-only"], config.git_timeout_s, command_runner)
    _record_command(log, pull_result, progress_callback)
    if pull_result.returncode != 0:
        result = _make_result(
            STATUS_GIT_PULL_FAILED,
            "Update cannot continue because git pull --ff-only failed. The current app version was not changed.",
            repo_root=repo_root,
            branch=branch,
            before_sha=before_sha,
            after_sha=before_sha,
            log_path=log_path,
        )
        return _finish_failure_result(result, repo_root, config, log, launcher, log_path, progress_callback)

    after_result = _run_git(repo_root, ["rev-parse", "HEAD"], config.git_timeout_s, command_runner)
    _record_command(log, after_result, progress_callback)
    if after_result.returncode != 0 or not after_result.stdout.strip():
        result = _make_result(
            STATUS_GIT_PULL_FAILED,
            "Update completed, but the resulting commit could not be resolved.",
            repo_root=repo_root,
            branch=branch,
            before_sha=before_sha,
            log_path=log_path,
        )
        return _finish_failure_result(result, repo_root, config, log, launcher, log_path, progress_callback)
    after_sha = after_result.stdout.strip()

    status = STATUS_ALREADY_CURRENT if after_sha == before_sha else STATUS_UPDATED
    message = "LabCraft is already current." if status == STATUS_ALREADY_CURRENT else "LabCraft was updated successfully."

    result = _make_result(
        status,
        message,
        repo_root=repo_root,
        branch=branch,
        before_sha=before_sha,
        after_sha=after_sha,
        log_path=log_path,
    )
    _maybe_write_latest_update_result(config, result, repo_root, command_runner)

    if not config.no_relaunch:
        relaunch_error = _attempt_relaunch(
            config,
            repo_root,
            log,
            launcher,
            context="success",
            progress_callback=progress_callback,
        )
        if relaunch_error:
            result = _make_result(
                STATUS_RELAUNCH_FAILED,
                f"Update succeeded, but LabCraft could not be relaunched: {relaunch_error}",
                repo_root=repo_root,
                branch=branch,
                before_sha=before_sha,
                after_sha=after_sha,
                log_path=log_path,
            )
            log.add(f"status: {result.status}")
            log.add(result.message)
            log.write(log_path)
            _emit_progress(
                progress_callback,
                "failed",
                result.message,
                result=result,
                log_path=log_path,
            )
            return result
    else:
        log.add("relaunch skipped by --no-relaunch.")

    log.add(f"status: {result.status}")
    log.add(result.message)
    log.write(log_path)
    _emit_progress(progress_callback, "complete", result.message, result=result, log_path=log_path)
    return result


def _finish_failure_result(
    result: UpdateResult,
    launch_root: Path,
    config: UpdaterConfig,
    log: _LogBuffer,
    launcher: Launcher,
    log_path: Path,
    progress_callback: ProgressCallback | None = None,
) -> UpdateResult:
    final_result = result
    if config.relaunch_on_failure:
        log.add(f"failure_status: {result.status}")
        relaunch_error = _attempt_relaunch(
            config,
            launch_root,
            log,
            launcher,
            context="failure",
            progress_callback=progress_callback,
        )
        if relaunch_error:
            final_result = _make_result(
                STATUS_RELAUNCH_FAILED,
                f"{result.message} Also, LabCraft could not be relaunched: {relaunch_error}",
                repo_root=result.repo_root,
                branch=result.branch,
                before_sha=result.before_sha,
                after_sha=result.after_sha,
                log_path=log_path,
            )

    log.add(f"status: {final_result.status}")
    log.add(final_result.message)
    _maybe_write_latest_update_result(config, final_result, launch_root, command_runner=default_command_runner)
    log.write(log_path)
    _emit_progress(
        progress_callback,
        "failed",
        final_result.message,
        result=final_result,
        log_path=log_path,
    )
    return final_result


def parse_args(argv: Sequence[str] | None = None) -> UpdaterConfig:
    parser = argparse.ArgumentParser(description="Update the LabCraft app checkout and optionally relaunch it.")
    parser.add_argument("--repo-root", default=".", help="Repository root or any path inside the repository.")
    parser.add_argument("--wait-pid", type=int, default=None, help="Process ID to wait for before updating.")
    parser.add_argument("--wait-timeout-s", type=float, default=DEFAULT_WAIT_TIMEOUT_S, help="Seconds to wait for --wait-pid.")
    parser.add_argument("--python", dest="python_path", default=None, help="Python interpreter to use when relaunching.")
    parser.add_argument("--app", default=str(DEFAULT_APP_PATH), help="App entrypoint to relaunch.")
    parser.add_argument("--no-relaunch", action="store_true", help="Run the update without relaunching the app.")
    parser.add_argument(
        "--relaunch-on-failure",
        action="store_true",
        help="Relaunch the current app if the update cannot complete.",
    )
    parser.add_argument("--gui", action="store_true", help="Show the operator updater window.")
    parser.add_argument("--record-result", action="store_true", help="Write latest update result for the relaunched app.")
    parser.add_argument("--latest-result-path", default=None, help="Optional path for the latest update result JSON.")
    parser.add_argument("--git-timeout-s", type=float, default=DEFAULT_GIT_TIMEOUT_S, help="Timeout for each Git command.")
    parser.add_argument("--log-path", default=None, help="Optional updater log path.")
    args = parser.parse_args(argv)

    return UpdaterConfig(
        repo_root=Path(args.repo_root),
        wait_pid=args.wait_pid,
        wait_timeout_s=float(args.wait_timeout_s),
        python_path=Path(args.python_path) if args.python_path else None,
        app_path=Path(args.app),
        no_relaunch=bool(args.no_relaunch),
        relaunch_on_failure=bool(args.relaunch_on_failure),
        gui=bool(args.gui),
        record_result=bool(args.record_result),
        latest_result_path=Path(args.latest_result_path) if args.latest_result_path else None,
        git_timeout_s=float(args.git_timeout_s),
        log_path=Path(args.log_path) if args.log_path else None,
    )


def main(argv: Sequence[str] | None = None) -> int:
    config = parse_args(argv)
    if config.gui:
        try:
            repo_parent = Path(__file__).resolve().parents[1]
            if str(repo_parent) not in sys.path:
                sys.path.insert(0, str(repo_parent))
            from tools import update_window

            return int(update_window.run_gui(config))
        except ImportError as exc:
            print(f"Could not start updater window, falling back to headless update: {exc}", file=sys.stderr)

    result = run_update(config)
    print(result.message)
    print(f"Status: {result.status}")
    if result.branch:
        print(f"Branch: {result.branch}")
    if result.before_sha:
        print(f"Before: {result.before_sha}")
    if result.after_sha:
        print(f"After: {result.after_sha}")
    if result.log_path is not None:
        print(f"Log: {result.log_path}")
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
