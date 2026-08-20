"""Helpers for resolving the installed LabCraft application version."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence


def _default_command_runner(args: Sequence[str], cwd: Path):
    return subprocess.run(
        [str(arg) for arg in args],
        cwd=str(cwd),
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )


def _read_version_file(repo_root: Path) -> str:
    try:
        text = (repo_root / "VERSION").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""

    for line in text.splitlines():
        value = line.strip()
        if value:
            return value
    return ""


def _git_short_sha(repo_root: Path, command_runner) -> str:
    try:
        result = command_runner(("git", "rev-parse", "--short=12", "HEAD"), repo_root)
    except Exception:
        return ""

    try:
        returncode = int(getattr(result, "returncode", 1))
    except (TypeError, ValueError):
        return ""
    if returncode != 0:
        return ""

    stdout = str(getattr(result, "stdout", "") or "").strip()
    if not stdout:
        return ""
    return stdout.splitlines()[0].strip()


def get_app_version(repo_root: str | Path, command_runner=None) -> str:
    """Return VERSION content, a local commit fallback, or ``unknown``."""
    root = Path(repo_root)
    version = _read_version_file(root)
    if version:
        return version

    short_sha = _git_short_sha(root, command_runner or _default_command_runner)
    if short_sha:
        return f"commit {short_sha}"
    return "unknown"


def get_app_commit(repo_root: str | Path, command_runner=None) -> str:
    """Return the installed Git commit evidence or ``unknown``."""

    return _git_short_sha(
        Path(repo_root), command_runner or _default_command_runner
    ) or "unknown"
