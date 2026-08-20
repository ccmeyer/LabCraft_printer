from pathlib import Path
from types import SimpleNamespace

import pytest

from AppVersion import get_app_commit, get_app_version


def test_get_app_version_reads_version_file(tmp_path):
    (tmp_path / "VERSION").write_text("\n v1.1.2 \nignored\n", encoding="utf-8")

    def runner(args, cwd):
        pytest.fail("git fallback should not run when VERSION is present")

    assert get_app_version(tmp_path, command_runner=runner) == "v1.1.2"


def test_get_app_version_falls_back_to_git_short_sha(tmp_path):
    calls = []

    def runner(args, cwd):
        calls.append((tuple(args), Path(cwd)))
        return SimpleNamespace(returncode=0, stdout="abc123def456\n")

    assert get_app_version(tmp_path, command_runner=runner) == "commit abc123def456"
    assert calls == [(("git", "rev-parse", "--short=12", "HEAD"), tmp_path)]


def test_get_app_version_falls_back_when_version_file_is_blank(tmp_path):
    (tmp_path / "VERSION").write_text("\n \n", encoding="utf-8")

    def runner(args, cwd):
        return SimpleNamespace(returncode=0, stdout="fedcba654321\n")

    assert get_app_version(tmp_path, command_runner=runner) == "commit fedcba654321"


def test_get_app_version_returns_unknown_when_no_version_or_git_sha(tmp_path):
    def runner(args, cwd):
        return SimpleNamespace(returncode=128, stdout="")

    assert get_app_version(tmp_path, command_runner=runner) == "unknown"


def test_get_app_commit_returns_full_git_commit(tmp_path):
    calls = []
    full_commit = "abc123def4567890abc123def4567890abc123de"

    def runner(args, cwd):
        calls.append((tuple(args), Path(cwd)))
        return SimpleNamespace(returncode=0, stdout=f"{full_commit}\n")

    assert get_app_commit(tmp_path, command_runner=runner) == full_commit
    assert calls == [(('git', 'rev-parse', 'HEAD'), tmp_path)]


def test_get_app_commit_rejects_noncanonical_git_output(tmp_path):
    def runner(args, cwd):
        return SimpleNamespace(returncode=0, stdout="abc123def456\n")

    assert get_app_commit(tmp_path, command_runner=runner) == "unknown"
