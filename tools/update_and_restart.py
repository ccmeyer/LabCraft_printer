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

EXIT_CODES = {
    STATUS_UPDATED: 0,
    STATUS_ALREADY_CURRENT: 0,
    STATUS_NOT_GIT_REPO: 2,
    STATUS_DIRTY_WORKTREE: 3,
    STATUS_WAIT_TIMEOUT: 4,
    STATUS_GIT_PULL_FAILED: 5,
    STATUS_RELAUNCH_FAILED: 6,
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
class UpdaterConfig:
    repo_root: Path = Path(".")
    wait_pid: int | None = None
    wait_timeout_s: float = DEFAULT_WAIT_TIMEOUT_S
    python_path: Path | None = None
    app_path: Path = DEFAULT_APP_PATH
    no_relaunch: bool = False
    git_timeout_s: float = DEFAULT_GIT_TIMEOUT_S
    log_path: Path | None = None
    platform_name: str | None = None


CommandRunner = Callable[[Sequence[str], Path, float, Mapping[str, str] | None], CommandResult]
Launcher = Callable[[Sequence[str], Path], object]
Waiter = Callable[[int, float], bool]


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


def run_update(
    config: UpdaterConfig,
    *,
    command_runner: CommandRunner = default_command_runner,
    launcher: Launcher = default_launcher,
    waiter: Waiter | None = None,
) -> UpdateResult:
    requested_root = Path(config.repo_root).resolve()
    log = _LogBuffer()
    log.add("LabCraft updater started.")
    log.add(f"platform: {platform.platform()}")
    log.add(f"requested_repo_root: {requested_root}")

    log_path = Path(config.log_path).resolve() if config.log_path is not None else default_log_path(requested_root)

    if config.wait_pid is not None:
        log.add(f"waiting_for_pid: {config.wait_pid}")
        wait_func = waiter or (lambda pid, timeout: wait_for_process_exit(pid, timeout, platform_name=config.platform_name))
        if not wait_func(int(config.wait_pid), float(config.wait_timeout_s)):
            result = _make_result(
                STATUS_WAIT_TIMEOUT,
                f"Timed out waiting for process {config.wait_pid} to exit.",
                repo_root=None,
                log_path=log_path,
            )
            log.add(f"status: {result.status}")
            log.add(result.message)
            log.write(log_path)
            return result

    top_level = _run_git(requested_root, ["rev-parse", "--show-toplevel"], config.git_timeout_s, command_runner)
    log.add_command(top_level)
    if top_level.returncode != 0 or not top_level.stdout.strip():
        result = _make_result(
            STATUS_NOT_GIT_REPO,
            "Update cannot continue because the selected path is not a Git checkout.",
            repo_root=None,
            log_path=log_path,
        )
        log.add(f"status: {result.status}")
        log.add(result.message)
        log.write(log_path)
        return result

    repo_root = Path(top_level.stdout.strip()).resolve()
    if config.log_path is None:
        log_path = default_log_path(repo_root)
    log.add(f"repo_root: {repo_root}")

    branch_result = _run_git(repo_root, ["branch", "--show-current"], config.git_timeout_s, command_runner)
    log.add_command(branch_result)
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""

    before_result = _run_git(repo_root, ["rev-parse", "HEAD"], config.git_timeout_s, command_runner)
    log.add_command(before_result)
    if before_result.returncode != 0 or not before_result.stdout.strip():
        result = _make_result(
            STATUS_GIT_PULL_FAILED,
            "Update cannot continue because the current commit could not be resolved.",
            repo_root=repo_root,
            branch=branch,
            log_path=log_path,
        )
        log.add(f"status: {result.status}")
        log.add(result.message)
        log.write(log_path)
        return result
    before_sha = before_result.stdout.strip()

    status_result = _run_git(repo_root, ["status", "--porcelain"], config.git_timeout_s, command_runner)
    log.add_command(status_result)
    if status_result.returncode != 0:
        result = _make_result(
            STATUS_GIT_PULL_FAILED,
            "Update cannot continue because Git status failed.",
            repo_root=repo_root,
            branch=branch,
            before_sha=before_sha,
            log_path=log_path,
        )
        log.add(f"status: {result.status}")
        log.add(result.message)
        log.write(log_path)
        return result
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
        log.add(f"status: {result.status}")
        log.add(result.message)
        log.write(log_path)
        return result

    pull_result = _run_git(repo_root, ["pull", "--ff-only"], config.git_timeout_s, command_runner)
    log.add_command(pull_result)
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
        log.add(f"status: {result.status}")
        log.add(result.message)
        log.write(log_path)
        return result

    after_result = _run_git(repo_root, ["rev-parse", "HEAD"], config.git_timeout_s, command_runner)
    log.add_command(after_result)
    if after_result.returncode != 0 or not after_result.stdout.strip():
        result = _make_result(
            STATUS_GIT_PULL_FAILED,
            "Update completed, but the resulting commit could not be resolved.",
            repo_root=repo_root,
            branch=branch,
            before_sha=before_sha,
            log_path=log_path,
        )
        log.add(f"status: {result.status}")
        log.add(result.message)
        log.write(log_path)
        return result
    after_sha = after_result.stdout.strip()

    status = STATUS_ALREADY_CURRENT if after_sha == before_sha else STATUS_UPDATED
    message = "LabCraft is already current." if status == STATUS_ALREADY_CURRENT else "LabCraft was updated successfully."

    python_path = resolve_python_path(repo_root, config.python_path, platform_name=config.platform_name)
    app_path = _resolve_under_repo(repo_root, config.app_path)
    log.add(f"python: {python_path}")
    log.add(f"app: {app_path}")

    if not config.no_relaunch:
        command = [str(python_path), str(app_path)]
        log.add(f"relaunch_command: {' '.join(command)}")
        try:
            launcher(command, repo_root)
        except Exception as exc:
            result = _make_result(
                STATUS_RELAUNCH_FAILED,
                f"Update succeeded, but LabCraft could not be relaunched: {exc}",
                repo_root=repo_root,
                branch=branch,
                before_sha=before_sha,
                after_sha=after_sha,
                log_path=log_path,
            )
            log.add(f"status: {result.status}")
            log.add(result.message)
            log.write(log_path)
            return result
    else:
        log.add("relaunch skipped by --no-relaunch.")

    result = _make_result(
        status,
        message,
        repo_root=repo_root,
        branch=branch,
        before_sha=before_sha,
        after_sha=after_sha,
        log_path=log_path,
    )
    log.add(f"status: {result.status}")
    log.add(result.message)
    log.write(log_path)
    return result


def parse_args(argv: Sequence[str] | None = None) -> UpdaterConfig:
    parser = argparse.ArgumentParser(description="Update the LabCraft app checkout and optionally relaunch it.")
    parser.add_argument("--repo-root", default=".", help="Repository root or any path inside the repository.")
    parser.add_argument("--wait-pid", type=int, default=None, help="Process ID to wait for before updating.")
    parser.add_argument("--wait-timeout-s", type=float, default=DEFAULT_WAIT_TIMEOUT_S, help="Seconds to wait for --wait-pid.")
    parser.add_argument("--python", dest="python_path", default=None, help="Python interpreter to use when relaunching.")
    parser.add_argument("--app", default=str(DEFAULT_APP_PATH), help="App entrypoint to relaunch.")
    parser.add_argument("--no-relaunch", action="store_true", help="Run the update without relaunching the app.")
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
        git_timeout_s=float(args.git_timeout_s),
        log_path=Path(args.log_path) if args.log_path else None,
    )


def main(argv: Sequence[str] | None = None) -> int:
    result = run_update(parse_args(argv))
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
