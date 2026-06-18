#!/usr/bin/env python3
"""Create a portable Git bundle for offline LabCraft app updates."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence, TextIO


SCHEMA_VERSION = "labcraft_update_bundle_v1"
DEFAULT_BRANCH = "stable"
DEFAULT_REMOTE = "origin"
DEFAULT_OUTPUT_DIR = Path("local") / "LabCraftUpdates"
PRODUCER = "tools/create_update_bundle.py"

STATUS_CREATED = "created"
STATUS_NOT_GIT_REPO = "not_git_repo"
STATUS_FETCH_FAILED = "fetch_failed"
STATUS_REMOTE_URL_FAILED = "remote_url_failed"
STATUS_REF_RESOLVE_FAILED = "ref_resolve_failed"
STATUS_BUNDLE_CREATE_FAILED = "bundle_create_failed"
STATUS_BUNDLE_VERIFY_FAILED = "bundle_verify_failed"
STATUS_WRITE_FAILED = "write_failed"

EXIT_CODES = {
    STATUS_CREATED: 0,
    STATUS_NOT_GIT_REPO: 2,
    STATUS_FETCH_FAILED: 3,
    STATUS_REMOTE_URL_FAILED: 4,
    STATUS_REF_RESOLVE_FAILED: 5,
    STATUS_BUNDLE_CREATE_FAILED: 6,
    STATUS_BUNDLE_VERIFY_FAILED: 7,
    STATUS_WRITE_FAILED: 8,
}


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class BundleConfig:
    repo_root: Path
    branch: str = DEFAULT_BRANCH
    remote: str = DEFAULT_REMOTE
    output_dir: Path = DEFAULT_OUTPUT_DIR
    fetch: bool = True
    include_tags: bool = True


@dataclass(frozen=True)
class BundleResult:
    status: str
    returncode: int
    message: str
    repo_root: Path
    bundle_path: Path
    manifest_path: Path
    manifest: dict


class BundleCreateError(RuntimeError):
    def __init__(
        self,
        status: str,
        message: str,
        *,
        command_result: CommandResult | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.returncode = EXIT_CODES[status]
        self.command_result = command_result


CommandRunner = Callable[[Sequence[str], Path], CommandResult]


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_command_runner(args: Sequence[str], cwd: Path) -> CommandResult:
    str_args = tuple(str(arg) for arg in args)
    try:
        completed = subprocess.run(
            list(str_args),
            cwd=str(cwd),
            shell=False,
            capture_output=True,
            text=True,
            check=False,
        )
        return CommandResult(
            args=str_args,
            returncode=int(completed.returncode),
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
    except FileNotFoundError as exc:
        return CommandResult(args=str_args, returncode=127, stderr=str(exc))


def _run_git(repo_root: Path, git_args: Sequence[str], command_runner: CommandRunner) -> CommandResult:
    return command_runner(["git", *git_args], repo_root)


def _utc_stamp(now: datetime | None = None) -> str:
    when = now or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _utc_iso(now: datetime | None = None) -> str:
    when = now or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
    cleaned = cleaned.strip(".-_")
    return cleaned or "branch"


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _command_summary(result: CommandResult) -> str:
    detail = result.stderr.strip() or result.stdout.strip()
    command = " ".join(result.args)
    if detail:
        return f"{command} failed: {detail}"
    return f"{command} failed with exit code {result.returncode}."


def _resolve_repo_root(requested_root: Path, command_runner: CommandRunner) -> Path:
    result = _run_git(requested_root, ["rev-parse", "--show-toplevel"], command_runner)
    if result.returncode != 0 or not result.stdout.strip():
        raise BundleCreateError(
            STATUS_NOT_GIT_REPO,
            "Bundle creation cannot continue because the selected path is not a Git checkout.",
            command_result=result,
        )
    return Path(result.stdout.strip()).resolve()


def _write_manifest(path: Path, manifest: dict) -> None:
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def create_update_bundle(
    config: BundleConfig,
    *,
    command_runner: CommandRunner = default_command_runner,
    now: datetime | None = None,
) -> BundleResult:
    requested_root = Path(config.repo_root).resolve()
    repo_root = _resolve_repo_root(requested_root, command_runner)

    if config.fetch:
        fetch_result = _run_git(repo_root, ["fetch", "--prune", "--tags", config.remote], command_runner)
        if fetch_result.returncode != 0:
            raise BundleCreateError(
                STATUS_FETCH_FAILED,
                "Bundle creation could not fetch the requested remote.",
                command_result=fetch_result,
            )

    remote_url_result = _run_git(repo_root, ["config", "--get", f"remote.{config.remote}.url"], command_runner)
    if remote_url_result.returncode != 0 or not remote_url_result.stdout.strip():
        raise BundleCreateError(
            STATUS_REMOTE_URL_FAILED,
            f"Bundle creation could not resolve remote URL for {config.remote!r}.",
            command_result=remote_url_result,
        )
    remote_url = remote_url_result.stdout.strip()

    source_ref = f"refs/remotes/{config.remote}/{config.branch}"
    head_result = _run_git(repo_root, ["rev-parse", source_ref], command_runner)
    if head_result.returncode != 0 or not head_result.stdout.strip():
        raise BundleCreateError(
            STATUS_REF_RESOLVE_FAILED,
            f"Bundle creation could not resolve {source_ref}.",
            command_result=head_result,
        )
    head_sha = head_result.stdout.strip()
    head_short_sha = head_sha[:12]

    output_dir = Path(config.output_dir)
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    stamp = _utc_stamp(now)
    branch_part = _safe_filename_part(config.branch)
    base_name = f"labcraft-{branch_part}-{stamp}-{head_short_sha}"
    bundle_path = output_dir / f"{base_name}.bundle"
    manifest_path = output_dir / f"{base_name}.json"

    if bundle_path.exists() or manifest_path.exists():
        raise BundleCreateError(
            STATUS_WRITE_FAILED,
            f"Output files already exist for {base_name}; choose a different output directory or retry later.",
        )

    bundle_args = ["bundle", "create", str(bundle_path), source_ref]
    if config.include_tags:
        bundle_args.append("--tags")
    bundle_result = _run_git(repo_root, bundle_args, command_runner)
    if bundle_result.returncode != 0:
        raise BundleCreateError(
            STATUS_BUNDLE_CREATE_FAILED,
            "Git failed while creating the update bundle.",
            command_result=bundle_result,
        )

    verify_result = _run_git(repo_root, ["bundle", "verify", str(bundle_path)], command_runner)
    if verify_result.returncode != 0:
        raise BundleCreateError(
            STATUS_BUNDLE_VERIFY_FAILED,
            "Git could not verify the created update bundle.",
            command_result=verify_result,
        )

    bundle_sha256 = _sha256_file(bundle_path)
    bundle_size = bundle_path.stat().st_size

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "repo": _repo_slug_from_remote_url(remote_url),
        "remote": config.remote,
        "remote_url": remote_url,
        "branch": config.branch,
        "source_ref": source_ref,
        "head_sha": head_sha,
        "head_short_sha": head_short_sha,
        "created_at_utc": _utc_iso(now),
        "bundle_filename": bundle_path.name,
        "bundle_sha256": bundle_sha256,
        "bundle_size_bytes": bundle_size,
        "include_tags": bool(config.include_tags),
        "producer": PRODUCER,
    }
    _write_manifest(manifest_path, manifest)

    return BundleResult(
        status=STATUS_CREATED,
        returncode=EXIT_CODES[STATUS_CREATED],
        message="Offline update bundle created.",
        repo_root=repo_root,
        bundle_path=bundle_path,
        manifest_path=manifest_path,
        manifest=manifest,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a LabCraft offline update bundle and manifest.")
    parser.add_argument("--repo-root", type=Path, default=default_repo_root(), help="Path inside the Git checkout.")
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help="Branch to package from the remote-tracking ref.")
    parser.add_argument("--remote", default=DEFAULT_REMOTE, help="Remote name to fetch and package.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for bundle and manifest.")
    parser.add_argument("--no-fetch", action="store_true", help="Skip git fetch and use the existing remote-tracking ref.")
    parser.add_argument("--no-tags", action="store_true", help="Do not include tags in the Git bundle.")
    return parser


def _success_summary(result: BundleResult) -> dict:
    return {
        "status": result.status,
        "message": result.message,
        "bundle_path": str(result.bundle_path),
        "manifest_path": str(result.manifest_path),
        "branch": result.manifest["branch"],
        "head_sha": result.manifest["head_sha"],
        "bundle_sha256": result.manifest["bundle_sha256"],
        "bundle_size_bytes": result.manifest["bundle_size_bytes"],
    }


def _error_summary(error: BundleCreateError) -> dict:
    payload = {
        "status": error.status,
        "message": error.message,
    }
    if error.command_result is not None:
        payload["command"] = " ".join(error.command_result.args)
        payload["details"] = _command_summary(error.command_result)
    return payload


def main(
    argv: Sequence[str] | None = None,
    *,
    command_runner: CommandRunner = default_command_runner,
    now: datetime | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    args = build_arg_parser().parse_args(argv)
    config = BundleConfig(
        repo_root=Path(args.repo_root),
        branch=str(args.branch),
        remote=str(args.remote),
        output_dir=Path(args.output_dir),
        fetch=not bool(args.no_fetch),
        include_tags=not bool(args.no_tags),
    )
    try:
        result = create_update_bundle(config, command_runner=command_runner, now=now)
    except BundleCreateError as exc:
        err.write(json.dumps(_error_summary(exc), indent=2, sort_keys=True) + "\n")
        return int(exc.returncode)

    out.write(json.dumps(_success_summary(result), indent=2, sort_keys=True) + "\n")
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
