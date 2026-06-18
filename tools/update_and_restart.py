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
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass, replace
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
STATUS_OFFLINE_BUNDLE_INVALID = "offline_bundle_invalid"
STATUS_OFFLINE_UPDATE_FAILED = "offline_update_failed"

UPDATE_SOURCE_ONLINE = "online"
UPDATE_SOURCE_OFFLINE = "offline"
OFFLINE_BUNDLE_SCHEMA_VERSION = "labcraft_update_bundle_v1"
OFFLINE_UPDATE_REF = "refs/labcraft/offline-update"

EXIT_CODES = {
    STATUS_UPDATED: 0,
    STATUS_ALREADY_CURRENT: 0,
    STATUS_NOT_GIT_REPO: 2,
    STATUS_DIRTY_WORKTREE: 3,
    STATUS_WAIT_TIMEOUT: 4,
    STATUS_GIT_PULL_FAILED: 5,
    STATUS_RELAUNCH_FAILED: 6,
    STATUS_OFFLINE_BUNDLE_INVALID: 7,
    STATUS_OFFLINE_UPDATE_FAILED: 8,
}

CHECK_EXIT_CODES = {
    STATUS_UPDATE_AVAILABLE: 0,
    STATUS_UP_TO_DATE: 0,
    STATUS_NOT_GIT_REPO: 2,
    STATUS_DIRTY_WORKTREE: 3,
    STATUS_NO_UPSTREAM: 7,
    STATUS_DIVERGED: 8,
    STATUS_FETCH_FAILED: 9,
    STATUS_OFFLINE_BUNDLE_INVALID: 10,
}

DEFAULT_APP_PATH = Path("FreeRTOS-interface") / "App.py"
DEFAULT_WAIT_TIMEOUT_S = 120.0
DEFAULT_GIT_TIMEOUT_S = 300.0
DEFAULT_DEFERRED_LAUNCH_WAIT_TIMEOUT_S = 30.0
DEFERRED_LAUNCH_ARG = "--deferred-launch"
OFFLINE_UPDATES_DIR_NAME = "LabCraftUpdates"


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
    update_source: str = UPDATE_SOURCE_ONLINE
    offline_manifest_path: Path | None = None


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
    update_source: str = UPDATE_SOURCE_ONLINE
    offline_manifest_path: Path | None = None
    offline_bundle_path: Path | None = None


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
    offline_manifest_path: Path | None = None


CommandRunner = Callable[[Sequence[str], Path, float, Mapping[str, str] | None], CommandResult]
Launcher = Callable[[Sequence[str], Path], object]
Waiter = Callable[[int, float], bool]
ProgressCallback = Callable[[ProgressEvent], None]


@dataclass(frozen=True)
class OfflineBundleInfo:
    manifest_path: Path
    bundle_path: Path
    manifest: dict
    branch: str
    remote: str
    remote_url: str
    repo: str
    source_ref: str
    head_sha: str


class OfflineBundleError(RuntimeError):
    def __init__(self, message: str, *, command_result: CommandResult | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.command_result = command_result


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_slug_from_remote_url(remote_url: str) -> str:
    text = str(remote_url or "").strip()
    if not text:
        return ""

    match = re.search(r"github\.com[:/](?P<owner>[^/\s:]+)/(?P<repo>[^/\s]+?)(?:\.git)?/?$", text)
    if match:
        return f"{match.group('owner')}/{match.group('repo')}"

    path_text = text.replace("\\", "/").rstrip("/")
    name = path_text.rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name


def _record_or_log_command(
    log: _LogBuffer,
    result: CommandResult,
    progress_callback: ProgressCallback | None,
) -> None:
    if progress_callback is None:
        log.add_command(result)
    else:
        _record_command(log, result, progress_callback)


def _resolve_offline_manifest_path(repo_root: Path, manifest_path: Path | str) -> Path:
    path = Path(manifest_path)
    return (path if path.is_absolute() else repo_root / path).resolve()


def _resolve_manifest_bundle_path(manifest_path: Path, bundle_filename: object) -> Path:
    if not isinstance(bundle_filename, str) or not bundle_filename.strip():
        raise OfflineBundleError("Offline update manifest is missing bundle_filename.")

    bundle_name = Path(bundle_filename)
    if bundle_name.is_absolute() or "/" in bundle_filename or "\\" in bundle_filename or bundle_name.name != bundle_filename:
        raise OfflineBundleError("Offline update manifest bundle_filename must be a filename next to the manifest.")

    return (manifest_path.parent / bundle_name).resolve()


def _load_offline_manifest(manifest_path: Path) -> dict:
    if not manifest_path.is_file():
        raise OfflineBundleError(f"Offline update manifest was not found: {manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OfflineBundleError(f"Offline update manifest is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise OfflineBundleError(f"Offline update manifest could not be read: {exc}") from exc
    if not isinstance(payload, dict):
        raise OfflineBundleError("Offline update manifest must contain a JSON object.")
    return payload


def _validate_offline_bundle(
    repo_root: Path,
    *,
    manifest_path: Path | str,
    branch: str,
    config: UpdaterConfig,
    log: _LogBuffer,
    command_runner: CommandRunner,
    progress_callback: ProgressCallback | None = None,
) -> OfflineBundleInfo:
    resolved_manifest_path = _resolve_offline_manifest_path(repo_root, manifest_path)
    log.add(f"offline_manifest_path: {resolved_manifest_path}")
    manifest = _load_offline_manifest(resolved_manifest_path)

    schema_version = str(manifest.get("schema_version", "") or "")
    if schema_version != OFFLINE_BUNDLE_SCHEMA_VERSION:
        raise OfflineBundleError("Offline update manifest has an unsupported schema version.")

    manifest_branch = str(manifest.get("branch", "") or "")
    if not branch:
        raise OfflineBundleError("Offline update cannot continue because the current branch could not be resolved.")
    if manifest_branch != branch:
        raise OfflineBundleError(
            f"Offline update bundle is for branch {manifest_branch!r}, but this checkout is on {branch!r}."
        )

    remote = str(manifest.get("remote", "") or "")
    if not remote:
        raise OfflineBundleError("Offline update manifest is missing remote.")

    repo = str(manifest.get("repo", "") or "")
    if not repo:
        raise OfflineBundleError("Offline update manifest is missing repo.")

    remote_url = str(manifest.get("remote_url", "") or "")
    manifest_remote_slug = _repo_slug_from_remote_url(remote_url)
    if manifest_remote_slug and manifest_remote_slug != repo:
        raise OfflineBundleError("Offline update manifest repo does not match its remote_url.")

    remote_url_result = _run_git(
        repo_root,
        ["config", "--get", f"remote.{remote}.url"],
        config.git_timeout_s,
        command_runner,
    )
    _record_or_log_command(log, remote_url_result, progress_callback)
    if remote_url_result.returncode != 0 or not remote_url_result.stdout.strip():
        raise OfflineBundleError(
            f"Offline update cannot resolve local remote URL for {remote!r}.",
            command_result=remote_url_result,
        )
    local_remote_url = remote_url_result.stdout.strip()
    local_repo_slug = _repo_slug_from_remote_url(local_remote_url)
    if local_repo_slug != repo:
        raise OfflineBundleError(
            f"Offline update bundle is for repo {repo!r}, but this checkout remote is {local_repo_slug!r}."
        )

    source_ref = str(manifest.get("source_ref", "") or "")
    expected_source_ref = f"refs/remotes/{remote}/{manifest_branch}"
    if source_ref != expected_source_ref:
        raise OfflineBundleError("Offline update manifest source_ref does not match its remote and branch.")

    head_sha = str(manifest.get("head_sha", "") or "")
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", head_sha):
        raise OfflineBundleError("Offline update manifest has an invalid head_sha.")

    bundle_path = _resolve_manifest_bundle_path(resolved_manifest_path, manifest.get("bundle_filename"))
    if not bundle_path.is_file():
        raise OfflineBundleError(f"Offline update bundle was not found: {bundle_path}")

    expected_sha256 = str(manifest.get("bundle_sha256", "") or "").lower()
    actual_sha256 = _sha256_file(bundle_path).lower()
    if not expected_sha256 or actual_sha256 != expected_sha256:
        raise OfflineBundleError("Offline update bundle SHA256 does not match the manifest.")

    verify_result = _run_git(
        repo_root,
        ["bundle", "verify", str(bundle_path)],
        config.git_timeout_s,
        command_runner,
    )
    _record_or_log_command(log, verify_result, progress_callback)
    if verify_result.returncode != 0:
        raise OfflineBundleError(
            "Git could not verify the offline update bundle.",
            command_result=verify_result,
        )

    return OfflineBundleInfo(
        manifest_path=resolved_manifest_path,
        bundle_path=bundle_path,
        manifest=manifest,
        branch=manifest_branch,
        remote=remote,
        remote_url=remote_url,
        repo=repo,
        source_ref=source_ref,
        head_sha=head_sha,
    )


def _prepare_offline_update_ref(
    repo_root: Path,
    *,
    manifest_path: Path | str,
    branch: str,
    config: UpdaterConfig,
    log: _LogBuffer,
    command_runner: CommandRunner,
    progress_callback: ProgressCallback | None = None,
) -> OfflineBundleInfo:
    info = _validate_offline_bundle(
        repo_root,
        manifest_path=manifest_path,
        branch=branch,
        config=config,
        log=log,
        command_runner=command_runner,
        progress_callback=progress_callback,
    )
    fetch_result = _run_git(
        repo_root,
        ["fetch", "--force", str(info.bundle_path), f"{info.source_ref}:{OFFLINE_UPDATE_REF}"],
        config.git_timeout_s,
        command_runner,
    )
    _record_or_log_command(log, fetch_result, progress_callback)
    if fetch_result.returncode != 0:
        raise OfflineBundleError(
            "Git could not fetch the offline update bundle.",
            command_result=fetch_result,
        )

    ref_result = _run_git(repo_root, ["rev-parse", OFFLINE_UPDATE_REF], config.git_timeout_s, command_runner)
    _record_or_log_command(log, ref_result, progress_callback)
    if ref_result.returncode != 0 or not ref_result.stdout.strip():
        raise OfflineBundleError(
            "Git could not resolve the fetched offline update ref.",
            command_result=ref_result,
        )
    fetched_sha = ref_result.stdout.strip()
    if fetched_sha.lower() != info.head_sha.lower():
        raise OfflineBundleError("Fetched offline update ref does not match the manifest head_sha.")

    return info


def _dedupe_paths(paths: Sequence[Path]) -> tuple[Path, ...]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        resolved = Path(path).resolve()
        key = str(resolved).lower() if _is_windows() else str(resolved)
        if key in seen:
            continue
        seen.add(key)
        result.append(resolved)
    return tuple(result)


def _psutil_removable_roots(*, platform_name: str | None = None) -> tuple[Path, ...]:
    try:
        import psutil
    except Exception:
        return ()

    roots: list[Path] = []
    try:
        partitions = psutil.disk_partitions(all=False)
    except Exception:
        return ()

    is_windows = _is_windows(platform_name)
    for partition in partitions:
        mountpoint = getattr(partition, "mountpoint", "") or ""
        if not mountpoint:
            continue
        opts = {part.strip().lower() for part in str(getattr(partition, "opts", "") or "").split(",")}
        if is_windows:
            if "removable" in opts or "cdrom" in opts:
                roots.append(Path(mountpoint))
        elif "removable" in opts or "cdrom" in opts:
            roots.append(Path(mountpoint))
    return _dedupe_paths(roots)


def _default_offline_search_roots(*, platform_name: str | None = None) -> tuple[Path, ...]:
    roots = list(_psutil_removable_roots(platform_name=platform_name))
    if _is_windows(platform_name):
        if not roots:
            for code in range(ord("A"), ord("Z") + 1):
                root = Path(f"{chr(code)}:\\")
                if root.exists():
                    roots.append(root)
    else:
        for root in (Path("/media"), Path("/run/media"), Path("/mnt"), Path("/Volumes")):
            if root.exists():
                roots.append(root)
    return _dedupe_paths(roots)


def _iter_labcraft_update_dirs(root: Path) -> tuple[Path, ...]:
    root = Path(root)
    candidates: list[Path] = []
    if root.name == OFFLINE_UPDATES_DIR_NAME:
        candidates.append(root)
    candidates.append(root / OFFLINE_UPDATES_DIR_NAME)

    try:
        children = [child for child in root.iterdir() if child.is_dir()]
    except OSError:
        children = []
    for child in children:
        if child.name == OFFLINE_UPDATES_DIR_NAME:
            candidates.append(child)
        candidates.append(child / OFFLINE_UPDATES_DIR_NAME)
        try:
            grandchildren = [grandchild for grandchild in child.iterdir() if grandchild.is_dir()]
        except OSError:
            grandchildren = []
        for grandchild in grandchildren:
            if grandchild.name == OFFLINE_UPDATES_DIR_NAME:
                candidates.append(grandchild)
            candidates.append(grandchild / OFFLINE_UPDATES_DIR_NAME)

    return _dedupe_paths([candidate for candidate in candidates if candidate.is_dir()])


def find_offline_update_manifests(search_roots: Sequence[Path | str] | None = None) -> tuple[Path, ...]:
    roots = (
        tuple(Path(root) for root in search_roots)
        if search_roots is not None
        else _default_offline_search_roots()
    )
    manifests: list[Path] = []
    for root in roots:
        for updates_dir in _iter_labcraft_update_dirs(Path(root)):
            try:
                manifests.extend(path for path in updates_dir.glob("*.json") if path.is_file())
            except OSError:
                continue
    return _dedupe_paths(sorted(manifests, key=lambda path: str(path)))


def _offline_manifest_sort_timestamp(path: Path) -> float:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        created_at = str(payload.get("created_at_utc") or "")
        if created_at:
            return datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
    except Exception:
        pass
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _sort_offline_manifest_candidates(manifest_paths: Sequence[Path | str]) -> tuple[Path, ...]:
    paths = _dedupe_paths([Path(path) for path in manifest_paths])
    return tuple(
        sorted(
            paths,
            key=lambda path: (_offline_manifest_sort_timestamp(path), str(path)),
            reverse=True,
        )
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

    try:
        from ctypes import wintypes

        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
    except Exception:
        pass

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


def detached_process_launcher(command: Sequence[str], cwd: Path) -> object:
    str_command = [str(part) for part in command]
    base_kwargs = {
        "cwd": str(cwd),
        "shell": False,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }

    if _is_windows():
        detached = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        new_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
        flag_options = (detached | new_group | breakaway, detached | new_group)
        last_error: OSError | None = None
        for flags in flag_options:
            try:
                return subprocess.Popen(str_command, creationflags=flags, **base_kwargs)
            except OSError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error

    return subprocess.Popen(str_command, start_new_session=True, **base_kwargs)


def default_launcher(command: Sequence[str], cwd: Path) -> object:
    return detached_process_launcher(command, cwd)


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


def build_deferred_relaunch_command(
    config: UpdaterConfig,
    repo_root: Path,
    *,
    wait_pid: int,
    wait_timeout_s: float = DEFAULT_DEFERRED_LAUNCH_WAIT_TIMEOUT_S,
) -> tuple[list[str], list[str]]:
    app_command = build_relaunch_command(config, repo_root)
    helper_command = [
        str(Path(sys.executable)),
        "-u",
        str(Path(__file__).resolve()),
        DEFERRED_LAUNCH_ARG,
        "--wait-pid",
        str(int(wait_pid)),
        "--wait-timeout-s",
        f"{float(wait_timeout_s):g}",
        "--cwd",
        str(repo_root),
        "--",
        *app_command,
    ]
    return helper_command, app_command


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


def relaunch_app_after_process_exit(
    config: UpdaterConfig,
    repo_root: Path,
    *,
    wait_pid: int,
    wait_timeout_s: float = DEFAULT_DEFERRED_LAUNCH_WAIT_TIMEOUT_S,
    launcher: Launcher = default_launcher,
) -> tuple[bool, str, list[str], list[str]]:
    helper_command, app_command = build_deferred_relaunch_command(
        config,
        repo_root,
        wait_pid=wait_pid,
        wait_timeout_s=wait_timeout_s,
    )
    try:
        launcher(helper_command, repo_root)
    except Exception as exc:
        return False, str(exc), helper_command, app_command
    return True, "", helper_command, app_command


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
        "update_source": result.update_source,
        "offline_manifest_path": str(result.offline_manifest_path) if result.offline_manifest_path is not None else "",
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
    update_source: str = UPDATE_SOURCE_ONLINE,
    offline_manifest_path: Path | None = None,
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
        update_source=update_source,
        offline_manifest_path=offline_manifest_path,
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
    update_source: str = UPDATE_SOURCE_ONLINE,
    offline_manifest_path: Path | None = None,
    offline_bundle_path: Path | None = None,
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
        update_source=update_source,
        offline_manifest_path=offline_manifest_path,
        offline_bundle_path=offline_bundle_path,
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

    if config.offline_manifest_path is not None:
        try:
            offline_info = _prepare_offline_update_ref(
                repo_root,
                manifest_path=config.offline_manifest_path,
                branch=branch,
                config=config,
                log=log,
                command_runner=command_runner,
            )
        except OfflineBundleError as exc:
            if exc.command_result is not None:
                log.add(f"offline_error_command: {' '.join(exc.command_result.args)}")
            return _finish_check_result(
                _make_check_result(
                    STATUS_OFFLINE_BUNDLE_INVALID,
                    str(exc.message),
                    repo_root=repo_root,
                    branch=branch,
                    head_sha=head_sha,
                    log_path=log_path,
                    update_source=UPDATE_SOURCE_OFFLINE,
                    offline_manifest_path=_resolve_offline_manifest_path(repo_root, config.offline_manifest_path),
                ),
                log,
                log_path,
            )

        count_result = _run_git(
            repo_root,
            ["rev-list", "--left-right", "--count", f"HEAD...{OFFLINE_UPDATE_REF}"],
            config.git_timeout_s,
            command_runner,
        )
        log.add_command(count_result)
        counts = _parse_rev_list_counts(count_result.stdout)
        if count_result.returncode != 0 or counts is None:
            return _finish_check_result(
                _make_check_result(
                    STATUS_OFFLINE_BUNDLE_INVALID,
                    "Update check could not compare this checkout with the offline bundle.",
                    repo_root=repo_root,
                    branch=branch,
                    upstream=OFFLINE_UPDATE_REF,
                    head_sha=head_sha,
                    upstream_sha=offline_info.head_sha,
                    log_path=log_path,
                    update_source=UPDATE_SOURCE_OFFLINE,
                    offline_manifest_path=offline_info.manifest_path,
                    offline_bundle_path=offline_info.bundle_path,
                ),
                log,
                log_path,
            )

        ahead_count, behind_count = counts
        if ahead_count > 0 and behind_count > 0:
            return _finish_check_result(
                _make_check_result(
                    STATUS_DIVERGED,
                    "This checkout has diverged from the offline update bundle. Contact support before updating.",
                    repo_root=repo_root,
                    branch=branch,
                    upstream=OFFLINE_UPDATE_REF,
                    head_sha=head_sha,
                    upstream_sha=offline_info.head_sha,
                    ahead_count=ahead_count,
                    behind_count=behind_count,
                    log_path=log_path,
                    update_source=UPDATE_SOURCE_OFFLINE,
                    offline_manifest_path=offline_info.manifest_path,
                    offline_bundle_path=offline_info.bundle_path,
                ),
                log,
                log_path,
            )

        if behind_count > 0:
            log_result = _run_git(
                repo_root,
                ["log", "--oneline", f"HEAD..{OFFLINE_UPDATE_REF}"],
                config.git_timeout_s,
                command_runner,
            )
            log.add_command(log_result)
            commits = _split_commit_lines(log_result.stdout) if log_result.returncode == 0 else ()
            return _finish_check_result(
                _make_check_result(
                    STATUS_UPDATE_AVAILABLE,
                    f"{behind_count} offline update commit{'s' if behind_count != 1 else ''} available.",
                    repo_root=repo_root,
                    branch=branch,
                    upstream=OFFLINE_UPDATE_REF,
                    head_sha=head_sha,
                    upstream_sha=offline_info.head_sha,
                    ahead_count=ahead_count,
                    behind_count=behind_count,
                    commits=commits,
                    log_path=log_path,
                    update_source=UPDATE_SOURCE_OFFLINE,
                    offline_manifest_path=offline_info.manifest_path,
                    offline_bundle_path=offline_info.bundle_path,
                ),
                log,
                log_path,
            )

        message = "LabCraft is up to date with the offline update bundle."
        if ahead_count > 0:
            message = "No offline update is available. This checkout has local commits not present in the offline bundle."
        return _finish_check_result(
            _make_check_result(
                STATUS_UP_TO_DATE,
                message,
                repo_root=repo_root,
                branch=branch,
                upstream=OFFLINE_UPDATE_REF,
                head_sha=head_sha,
                upstream_sha=offline_info.head_sha,
                ahead_count=ahead_count,
                behind_count=behind_count,
                log_path=log_path,
                update_source=UPDATE_SOURCE_OFFLINE,
                offline_manifest_path=offline_info.manifest_path,
                offline_bundle_path=offline_info.bundle_path,
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
        update_source=result.update_source,
        offline_manifest_path=result.offline_manifest_path,
        offline_bundle_path=result.offline_bundle_path,
    )
    log.add(f"status: {result.status}")
    log.add(result.message)
    log.write(log_path)
    return result


def run_update_check_with_offline_fallback(
    config: UpdaterConfig,
    *,
    command_runner: CommandRunner = default_command_runner,
    manifest_paths: Sequence[Path | str] | None = None,
    search_roots: Sequence[Path | str] | None = None,
) -> UpdateCheckResult:
    online_result = run_update_check(config, command_runner=command_runner)
    if online_result.status != STATUS_FETCH_FAILED:
        return online_result

    candidates = (
        _sort_offline_manifest_candidates(manifest_paths)
        if manifest_paths is not None
        else _sort_offline_manifest_candidates(find_offline_update_manifests(search_roots))
    )
    first_up_to_date: UpdateCheckResult | None = None
    for manifest_path in candidates:
        offline_config = replace(config, offline_manifest_path=Path(manifest_path))
        offline_result = run_update_check(offline_config, command_runner=command_runner)
        if offline_result.status == STATUS_UPDATE_AVAILABLE:
            return offline_result
        if offline_result.status == STATUS_UP_TO_DATE and first_up_to_date is None:
            first_up_to_date = offline_result

    if first_up_to_date is not None:
        return first_up_to_date

    return replace(
        online_result,
        message=f"{online_result.message} No usable offline update bundle was found.",
    )


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
    update_source = UPDATE_SOURCE_OFFLINE if config.offline_manifest_path is not None else UPDATE_SOURCE_ONLINE
    resolved_offline_manifest_path = (
        _resolve_offline_manifest_path(repo_root, config.offline_manifest_path)
        if config.offline_manifest_path is not None
        else None
    )

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
            update_source=update_source,
            offline_manifest_path=resolved_offline_manifest_path,
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
            update_source=update_source,
            offline_manifest_path=resolved_offline_manifest_path,
        )
        return _finish_failure_result(result, repo_root, config, log, launcher, log_path, progress_callback)

    offline_manifest_path = resolved_offline_manifest_path
    if config.offline_manifest_path is not None:
        _emit_progress(progress_callback, "validating_offline_bundle", "Validating offline update bundle...", log_path=log_path)
        try:
            offline_info = _prepare_offline_update_ref(
                repo_root,
                manifest_path=config.offline_manifest_path,
                branch=branch,
                config=config,
                log=log,
                command_runner=command_runner,
                progress_callback=progress_callback,
            )
            offline_manifest_path = offline_info.manifest_path
        except OfflineBundleError as exc:
            result = _make_result(
                STATUS_OFFLINE_BUNDLE_INVALID,
                str(exc.message),
                repo_root=repo_root,
                branch=branch,
                before_sha=before_sha,
                after_sha=before_sha,
                log_path=log_path,
                update_source=UPDATE_SOURCE_OFFLINE,
                offline_manifest_path=resolved_offline_manifest_path,
            )
            return _finish_failure_result(result, repo_root, config, log, launcher, log_path, progress_callback)

        _emit_progress(progress_callback, "applying_update", "Applying offline update...", log_path=log_path)
        pull_result = _run_git(repo_root, ["merge", "--ff-only", OFFLINE_UPDATE_REF], config.git_timeout_s, command_runner)
        _record_command(log, pull_result, progress_callback)
        if pull_result.returncode != 0:
            result = _make_result(
                STATUS_OFFLINE_UPDATE_FAILED,
                f"Update cannot continue because git merge --ff-only {OFFLINE_UPDATE_REF} failed. The current app version was not changed.",
                repo_root=repo_root,
                branch=branch,
                before_sha=before_sha,
                after_sha=before_sha,
                log_path=log_path,
                update_source=UPDATE_SOURCE_OFFLINE,
                offline_manifest_path=offline_manifest_path,
            )
            return _finish_failure_result(result, repo_root, config, log, launcher, log_path, progress_callback)
    else:
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
            STATUS_OFFLINE_UPDATE_FAILED if update_source == UPDATE_SOURCE_OFFLINE else STATUS_GIT_PULL_FAILED,
            "Update completed, but the resulting commit could not be resolved.",
            repo_root=repo_root,
            branch=branch,
            before_sha=before_sha,
            log_path=log_path,
            update_source=update_source,
            offline_manifest_path=offline_manifest_path,
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
        update_source=update_source,
        offline_manifest_path=offline_manifest_path,
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
                update_source=update_source,
                offline_manifest_path=offline_manifest_path,
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
    parser.add_argument("--offline-manifest", default=None, help="Manifest JSON for an offline update bundle.")
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
        offline_manifest_path=Path(args.offline_manifest) if args.offline_manifest else None,
    )


def run_deferred_launch(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wait for a process to exit, then launch LabCraft detached.")
    parser.add_argument("--wait-pid", type=int, required=True)
    parser.add_argument("--wait-timeout-s", type=float, default=DEFAULT_DEFERRED_LAUNCH_WAIT_TIMEOUT_S)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    command = [str(part) for part in args.command]
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a launch command is required after --")

    wait_for_process_exit(int(args.wait_pid), float(args.wait_timeout_s))
    try:
        detached_process_launcher(command, Path(args.cwd))
    except Exception as exc:
        print(f"Could not launch LabCraft: {exc}", file=sys.stderr)
        return EXIT_CODES[STATUS_RELAUNCH_FAILED]
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == DEFERRED_LAUNCH_ARG:
        return run_deferred_launch(argv[1:])

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
    if result.update_source:
        print(f"Source: {result.update_source}")
    if result.offline_manifest_path is not None:
        print(f"Offline manifest: {result.offline_manifest_path}")
    if result.before_sha:
        print(f"Before: {result.before_sha}")
    if result.after_sha:
        print(f"After: {result.after_sha}")
    if result.log_path is not None:
        print(f"Log: {result.log_path}")
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
