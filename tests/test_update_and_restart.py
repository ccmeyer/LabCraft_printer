import json
import json
import hashlib
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools
from tools import create_update_bundle
import tools.update_and_restart as updater

OFFLINE_SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER_OFFLINE_SHA = "fedcba9876543210fedcba9876543210fedcba98"
ROLLBACK_SHA = "1111111111111111111111111111111111111111"


def _write_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def _write_version(repo_root: Path, version: str = "v1.1.2") -> None:
    (repo_root / "VERSION").write_text(f"{version}\n", encoding="utf-8")


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
        target_release_version: str = "v1.1.2",
        target_release_sha: str = "release789",
        target_release_channel: str = "stable",
        release_summary: str = "Release-aware updater bootstrap.",
        release_notes: tuple[str, ...] = ("Adds release metadata.",),
        rollback_version: str = "v1.1.1",
        release_index_payload: dict | None = None,
        release_manifest_payload: dict | None = None,
        release_index_returncode: int = 0,
        release_manifest_returncode: int = 0,
        release_tag_returncode: int = 0,
        release_tag_list: tuple[str, ...] = (),
        release_tag_shas: dict[str, str] | None = None,
        release_manifest_payloads: dict[str, dict] | None = None,
        release_manifest_returncodes: dict[str, int] | None = None,
        tag_list_returncode: int = 0,
        release_merge_returncode: int | None = None,
        rollback_release_version: str = "v1.1.1",
        rollback_release_sha: str = ROLLBACK_SHA,
        rollback_release_manifest_payload: dict | None = None,
        rollback_release_tag_returncode: int = 0,
        rollback_release_manifest_returncode: int = 0,
        reset_returncode: int = 0,
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
        self.target_release_version = target_release_version
        self.target_release_sha = target_release_sha
        self.target_release_channel = target_release_channel
        self.release_summary = release_summary
        self.release_notes = release_notes
        self.rollback_version = rollback_version
        self.release_index_payload = release_index_payload
        self.release_manifest_payload = release_manifest_payload
        self.release_index_returncode = release_index_returncode
        self.release_manifest_returncode = release_manifest_returncode
        self.release_tag_returncode = release_tag_returncode
        self.release_tag_list = release_tag_list
        self.release_tag_shas = dict(release_tag_shas or {})
        self.release_manifest_payloads = dict(release_manifest_payloads or {})
        self.release_manifest_returncodes = dict(release_manifest_returncodes or {})
        self.tag_list_returncode = tag_list_returncode
        self.release_merge_returncode = pull_returncode if release_merge_returncode is None else release_merge_returncode
        self.rollback_release_version = rollback_release_version
        self.rollback_release_sha = rollback_release_sha
        self.rollback_release_manifest_payload = rollback_release_manifest_payload
        self.rollback_release_tag_returncode = rollback_release_tag_returncode
        self.rollback_release_manifest_returncode = rollback_release_manifest_returncode
        self.reset_returncode = reset_returncode
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
        offline_target_ref = f"{updater.OFFLINE_UPDATE_REF}^{{commit}}"
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

        if git_args in (("fetch", "--prune"), ("fetch", "--prune", "--tags")):
            if self.fetch_returncode:
                return updater.CommandResult(args_tuple, self.fetch_returncode, stderr="network unavailable")
            return updater.CommandResult(args_tuple, 0, stdout="")

        if len(git_args) == 3 and git_args[:2] == ("tag", "--list"):
            if self.tag_list_returncode:
                return updater.CommandResult(args_tuple, self.tag_list_returncode, stderr="tag list failed")
            pattern = git_args[2]
            if pattern.endswith("*"):
                prefix = pattern[:-1]
                tags = [tag for tag in self.release_tag_list if tag.startswith(prefix)]
            else:
                tags = [tag for tag in self.release_tag_list if tag == pattern]
            return updater.CommandResult(args_tuple, 0, stdout="\n".join(tags) + ("\n" if tags else ""))

        if git_args in (("rev-parse", updater.OFFLINE_UPDATE_REF), ("rev-parse", offline_target_ref)):
            return updater.CommandResult(args_tuple, 0, stdout=f"{self.offline_ref_sha}\n")

        if len(git_args) == 2 and git_args[0] == "show" and git_args[1] == f"{self.upstream}:{updater.RELEASE_INDEX_PATH}":
            if self.release_index_returncode:
                return updater.CommandResult(args_tuple, self.release_index_returncode, stderr="missing release index")
            payload = self.release_index_payload or {
                "schema_version": updater.RELEASE_INDEX_SCHEMA_VERSION,
                "stable": self.target_release_version,
                "release_candidate": None,
                "releases": [self.target_release_version],
            }
            return updater.CommandResult(args_tuple, 0, stdout=json.dumps(payload) + "\n")

        if len(git_args) == 2 and git_args[0] == "rev-parse" and git_args[1].endswith("^{commit}"):
            release_tag = git_args[1][: -len("^{commit}")]
            if release_tag in self.release_tag_shas:
                return updater.CommandResult(args_tuple, 0, stdout=f"{self.release_tag_shas[release_tag]}\n")
            if release_tag == self.target_release_version:
                if self.release_tag_returncode:
                    return updater.CommandResult(args_tuple, self.release_tag_returncode, stderr="missing release tag")
                return updater.CommandResult(args_tuple, 0, stdout=f"{self.target_release_sha}\n")
            if release_tag == self.rollback_release_version:
                if self.rollback_release_tag_returncode:
                    return updater.CommandResult(args_tuple, self.rollback_release_tag_returncode, stderr="missing rollback tag")
                return updater.CommandResult(args_tuple, 0, stdout=f"{self.rollback_release_sha}\n")
            if self.release_tag_returncode:
                return updater.CommandResult(args_tuple, self.release_tag_returncode or 1, stderr="missing release tag")
            return updater.CommandResult(args_tuple, 1, stderr="missing release tag")

        if len(git_args) == 2 and git_args[0] == "show":
            ref, sep, path = git_args[1].partition(":")
            if sep and ref in self.release_tag_shas and path == f"releases/{ref}.json":
                returncode = self.release_manifest_returncodes.get(ref, 0)
                if returncode:
                    return updater.CommandResult(args_tuple, returncode, stderr="missing release manifest")
                payload = self.release_manifest_payloads.get(ref) or {
                    "schema_version": updater.RELEASE_MANIFEST_SCHEMA_VERSION,
                    "version": ref,
                    "tag": ref,
                    "channel": "release_candidate",
                    "release_date": "2026-07-06",
                    "previous_version": self.rollback_version,
                    "rollback_version": self.rollback_version,
                    "requires_firmware": None,
                    "summary": f"{ref} release candidate.",
                    "notes": [f"Installs {ref}."],
                    "validation": ["Focused updater tests pass."],
                }
                return updater.CommandResult(args_tuple, 0, stdout=json.dumps(payload) + "\n")

        if len(git_args) == 2 and git_args[0] == "show" and git_args[1] == f"{self.target_release_version}:releases/{self.target_release_version}.json":
            if self.release_manifest_returncode:
                return updater.CommandResult(args_tuple, self.release_manifest_returncode, stderr="missing release manifest")
            payload = self.release_manifest_payload or {
                "schema_version": updater.RELEASE_MANIFEST_SCHEMA_VERSION,
                "version": self.target_release_version,
                "tag": self.target_release_version,
                "channel": self.target_release_channel,
                "release_date": "2026-07-06",
                "previous_version": self.rollback_version,
                "rollback_version": self.rollback_version,
                "requires_firmware": None,
                "summary": self.release_summary,
                "notes": list(self.release_notes),
                "validation": ["Focused updater tests pass."],
            }
            return updater.CommandResult(args_tuple, 0, stdout=json.dumps(payload) + "\n")

        if len(git_args) == 2 and git_args[0] == "show" and git_args[1] == f"{self.rollback_release_version}:releases/{self.rollback_release_version}.json":
            if self.rollback_release_manifest_returncode:
                return updater.CommandResult(args_tuple, self.rollback_release_manifest_returncode, stderr="missing rollback manifest")
            payload = self.rollback_release_manifest_payload or {
                "schema_version": updater.RELEASE_MANIFEST_SCHEMA_VERSION,
                "version": self.rollback_release_version,
                "tag": self.rollback_release_version,
                "channel": "stable",
                "release_date": "2026-07-05",
                "previous_version": "v1.1.0",
                "rollback_version": "v1.1.0",
                "requires_firmware": None,
                "summary": "Rollback release.",
                "notes": ["Previous stable release."],
                "validation": ["Focused updater tests pass."],
            }
            return updater.CommandResult(args_tuple, 0, stdout=json.dumps(payload) + "\n")

        if git_args == ("rev-list", "--left-right", "--count", f"HEAD...{self.target_release_sha}"):
            return updater.CommandResult(args_tuple, 0, stdout=f"{self.ahead_count}\t{self.behind_count}\n")

        if (
            len(git_args) == 4
            and git_args[:3] == ("rev-list", "--left-right", "--count")
            and git_args[3].startswith("HEAD...")
            and git_args[3][len("HEAD...") :] in set(self.release_tag_shas.values())
        ):
            return updater.CommandResult(args_tuple, 0, stdout=f"{self.ahead_count}\t{self.behind_count}\n")

        if git_args in (
            ("rev-list", "--left-right", "--count", f"HEAD...{updater.OFFLINE_UPDATE_REF}"),
            ("rev-list", "--left-right", "--count", f"HEAD...{offline_target_ref}"),
        ):
            ahead = self.ahead_count if self.offline_ahead_count is None else self.offline_ahead_count
            behind = self.behind_count if self.offline_behind_count is None else self.offline_behind_count
            return updater.CommandResult(args_tuple, 0, stdout=f"{ahead}\t{behind}\n")

        if git_args == ("log", "--oneline", f"HEAD..{self.target_release_version}"):
            return updater.CommandResult(args_tuple, 0, stdout="\n".join(self.check_commits) + ("\n" if self.check_commits else ""))

        if (
            len(git_args) == 3
            and git_args[:2] == ("log", "--oneline")
            and git_args[2].startswith("HEAD..")
            and git_args[2][len("HEAD..") :] in self.release_tag_shas
        ):
            return updater.CommandResult(args_tuple, 0, stdout="\n".join(self.check_commits) + ("\n" if self.check_commits else ""))

        if git_args in (
            ("log", "--oneline", f"HEAD..{updater.OFFLINE_UPDATE_REF}"),
            ("log", "--oneline", f"HEAD..{offline_target_ref}"),
        ):
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

        if git_args == ("merge", "--ff-only", self.target_release_version):
            return updater.CommandResult(
                args_tuple,
                self.release_merge_returncode,
                stdout="Fast-forward\n" if self.release_merge_returncode == 0 else "",
                stderr="" if self.release_merge_returncode == 0 else "fatal: Not possible to fast-forward",
            )

        if len(git_args) == 3 and git_args[:2] == ("bundle", "verify"):
            if self.offline_verify_returncode:
                return updater.CommandResult(args_tuple, self.offline_verify_returncode, stderr="bundle verify failed")
            return updater.CommandResult(args_tuple, 0, stdout="The bundle is okay\n")

        if len(git_args) == 4 and git_args[:2] == ("fetch", "--force"):
            if self.offline_fetch_returncode:
                return updater.CommandResult(args_tuple, self.offline_fetch_returncode, stderr="bundle fetch failed")
            return updater.CommandResult(args_tuple, 0, stdout="")

        if git_args in (
            ("merge", "--ff-only", updater.OFFLINE_UPDATE_REF),
            ("merge", "--ff-only", offline_target_ref),
        ):
            return updater.CommandResult(
                args_tuple,
                self.offline_merge_returncode,
                stdout="Fast-forward\n" if self.offline_merge_returncode == 0 else "",
                stderr="" if self.offline_merge_returncode == 0 else "fatal: Not possible to fast-forward",
            )

        if git_args in (
            ("reset", "--hard", self.rollback_release_version),
            ("reset", "--hard", offline_target_ref),
        ):
            return updater.CommandResult(
                args_tuple,
                self.reset_returncode,
                stdout="HEAD is now at rollback\n" if self.reset_returncode == 0 else "",
                stderr="" if self.reset_returncode == 0 else "fatal: reset failed",
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
    release_version: str | None = None,
    release_tag: str | None = None,
    rollback_version: str = "v1.1.1",
    release_manifest: dict | None = None,
) -> Path:
    bundle_path = tmp_path / bundle_name
    bundle_path.write_bytes(bundle_bytes)
    release_tag = release_tag or release_version
    source_ref = f"refs/remotes/{remote}/{branch}"
    if release_version:
        source_ref = f"refs/tags/{release_tag}"
    manifest = {
        "schema_version": schema_version,
        "repo": repo,
        "remote": remote,
        "remote_url": "https://github.com/ccmeyer/LabCraft_printer",
        "branch": branch,
        "source_ref": source_ref,
        "head_sha": head_sha,
        "bundle_filename": bundle_name,
        "bundle_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
        "created_at_utc": created_at_utc,
    }
    if release_version:
        manifest.update(
            {
                "release_version": release_version,
                "release_tag": release_tag,
                "rollback_version": rollback_version,
                "release_manifest": release_manifest
                or {
                    "schema_version": updater.RELEASE_MANIFEST_SCHEMA_VERSION,
                    "version": release_version,
                    "tag": release_tag,
                    "channel": "stable",
                    "release_date": "2026-07-06",
                    "previous_version": rollback_version,
                    "rollback_version": rollback_version,
                    "requires_firmware": None,
                    "summary": "Release-aware offline bundle.",
                    "notes": ["Installs a named release from USB."],
                    "validation": ["Focused updater tests pass."],
                },
            }
        )
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
    calls = [call[0] for call in runner.calls]
    assert ("git", "fetch", "--prune", "--tags") not in calls
    assert ("git", "merge", "--ff-only", "v1.1.2") not in calls
    assert ("git", "pull", "--ff-only") not in calls


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
    assert result.target_release_version == "v1.1.2"
    assert result.target_release_tag == "v1.1.2"
    assert result.target_release_sha == "release789"


def _m6_release_manifest(version="v1.1.2"):
    return {
        "schema_version": updater.RELEASE_MANIFEST_SCHEMA_VERSION,
        "version": version,
        "tag": version,
        "channel": "stable",
        "release_date": "2026-08-20",
        "previous_version": "v1.1.1",
        "rollback_version": "v1.1.1",
        "requires_firmware": None,
        "summary": "Protected update fixture.",
        "notes": [],
        "validation": [],
        "machine_data": {
            "preservation_contract": "labcraft.machine_data_update.v1",
            "data_schema_version": 1,
            "transition": "none",
            "transition_id": None,
        },
    }


def test_release_manifest_parses_explicit_legacy_bridge_compatibility():
    manifest = _m6_release_manifest("v1.3.0-rc.11")
    manifest["channel"] = updater.RELEASE_CHANNEL_RELEASE_CANDIDATE
    manifest["update_compatibility"] = {
        "schema_version": updater.UPDATE_COMPATIBILITY_SCHEMA_VERSION,
        "direct_legacy_sources": [
            "v1.2.0-rc.6",
            "v1.2.0",
            "v1.3.0-rc.1",
        ],
    }

    info = updater._validate_release_manifest(
        manifest,
        expected_version="v1.3.0-rc.11",
        expected_channel=updater.RELEASE_CHANNEL_RELEASE_CANDIDATE,
    )

    assert info.update_compatibility == {
        "schema_version": updater.UPDATE_COMPATIBILITY_SCHEMA_VERSION,
        "direct_legacy_sources": (
            "v1.2.0-rc.6",
            "v1.2.0",
            "v1.3.0-rc.1",
        ),
    }


def test_release_manifest_v2_is_accepted_for_future_release_candidates():
    manifest = _m6_release_manifest("v1.3.0-rc.12")
    manifest["schema_version"] = updater.RELEASE_MANIFEST_SCHEMA_VERSION_V2
    manifest["channel"] = updater.RELEASE_CHANNEL_RELEASE_CANDIDATE

    info = updater._validate_release_manifest(
        manifest,
        expected_version="v1.3.0-rc.12",
        expected_channel=updater.RELEASE_CHANNEL_RELEASE_CANDIDATE,
    )

    assert info.version == "v1.3.0-rc.12"


def test_release_manifest_v2_is_rejected_for_stable_channel():
    manifest = _m6_release_manifest("v1.3.0")
    manifest["schema_version"] = updater.RELEASE_MANIFEST_SCHEMA_VERSION_V2

    with pytest.raises(
        updater.ReleaseMetadataError,
        match="schema v2 is reserved for release_candidate",
    ):
        updater._validate_release_manifest(
            manifest,
            expected_version="v1.3.0",
            expected_channel=updater.RELEASE_CHANNEL_STABLE,
        )


@pytest.mark.parametrize(
    "compatibility",
    [
        {},
        {
            "schema_version": "unsupported",
            "direct_legacy_sources": ["v1.2.0-rc.6"],
        },
        {
            "schema_version": updater.UPDATE_COMPATIBILITY_SCHEMA_VERSION,
            "direct_legacy_sources": [],
        },
        {
            "schema_version": updater.UPDATE_COMPATIBILITY_SCHEMA_VERSION,
            "direct_legacy_sources": ["v1.2.0-rc.6", "v1.2.0-rc.6"],
        },
    ],
)
def test_release_manifest_rejects_malformed_bridge_compatibility(compatibility):
    manifest = _m6_release_manifest("v1.3.0-rc.11")
    manifest["update_compatibility"] = compatibility

    with pytest.raises(updater.ReleaseMetadataError):
        updater._validate_release_manifest(manifest, expected_version="v1.3.0-rc.11")


class _PreparedUpdateDouble:
    def __init__(self, tmp_path, events, *, fail_verify=False):
        self.update_id = "00000000-0000-0000-0000-000000000099"
        self.target = SimpleNamespace(machine_data_contract={"transition": "none"})
        self.events = events
        self.fail_verify = fail_verify
        self.terminal = tmp_path / "external" / "terminal_result.json"

    def record_git_result(self, **_kwargs):
        self.events.append("git_result")

    def verify_after(self):
        self.events.append("post_verify")
        if self.fail_verify:
            raise RuntimeError("simulated post-check drift")

    def authorize_relaunch(self):
        self.events.append("authorize")
        self.terminal.parent.mkdir(parents=True, exist_ok=True)
        self.terminal.write_text("{}", encoding="utf-8")
        return self.terminal

    def fail(self, _message, *, recovery_required=None):
        self.events.append(f"fail:{bool(recovery_required)}")
        self.terminal.parent.mkdir(parents=True, exist_ok=True)
        self.terminal.write_text("{}", encoding="utf-8")
        return self.terminal

    def close(self):
        self.events.append("close")


def test_protected_update_backup_gate_precedes_merge_and_authorizes_relaunch(tmp_path, monkeypatch):
    _write_version(tmp_path, "v1.1.1")
    events = []
    prepared = _PreparedUpdateDouble(tmp_path, events)
    runner = FakeGitRunner(
        tmp_path,
        before_sha="abc",
        after_sha="release789",
        release_manifest_payload=_m6_release_manifest(),
    )

    def recording_runner(args, cwd, timeout_s, env_updates):
        if tuple(args[1:]) == ("merge", "--ff-only", "v1.1.2"):
            events.append("merge")
        return runner(args, cwd, timeout_s, env_updates)

    monkeypatch.setattr(
        updater,
        "_begin_machine_data_protection",
        lambda *args, **kwargs: events.append("backup_verified") or prepared,
    )
    result = updater.run_update(
        _config(
            tmp_path,
            machine_data_required=True,
            source_app_version="v1.1.1",
            source_commit="abc",
        ),
        command_runner=recording_runner,
    )

    assert result.status == updater.STATUS_UPDATED
    assert result.relaunch_authorized is True
    assert result.machine_data_update_id == prepared.update_id
    assert events == ["backup_verified", "merge", "git_result", "post_verify", "authorize", "close"]


def test_begin_protection_canonicalizes_exact_rc2_short_source_commit(tmp_path, monkeypatch):
    import MachineDataUpdate

    full_commit = "5f54a4a174cd50f145e1bfa98aa61535b7aa59e9"
    captured = {}
    monkeypatch.setattr(
        MachineDataUpdate,
        "begin_update_preservation",
        lambda binding, target, **kwargs: captured.update(
            binding=binding,
            target=target,
            kwargs=kwargs,
        ) or "prepared",
    )
    target = updater.ReleaseTargetInfo(
        version="v1.3.0-rc.3",
        tag="v1.3.0-rc.3",
        sha="d" * 40,
        release_manifest_sha256="e" * 64,
        machine_data_contract=_m6_release_manifest()["machine_data"],
    )
    config = _config(
        tmp_path,
        machine_data_required=True,
        machine_data_root=(tmp_path / "machine-data").resolve(),
        machine_id="LC-001",
        machine_uuid="00000000-0000-0000-0000-000000000001",
        activation_id="00000000-0000-0000-0000-000000000002",
        migration_id="00000000-0000-0000-0000-000000000003",
        active_pointer_sha256="a" * 64,
        source_app_version="v1.3.0-rc.2",
        source_commit=full_commit[:12],
        update_request_id="00000000-0000-0000-0000-000000000004",
    )

    prepared = updater._begin_machine_data_protection(
        config,
        repo_root=tmp_path,
        before_release_version="v1.3.0-rc.2",
        before_sha=full_commit,
        target_info=target,
        operation=updater.OPERATION_UPDATE,
        update_source=updater.UPDATE_SOURCE_ONLINE,
    )

    assert prepared == "prepared"
    assert captured["binding"].source_commit == full_commit


@pytest.mark.parametrize(
    "source_commit",
    [
        "5f54a4a174c",
        "5f54a4a174ce",
        "5F54A4A174CD",
        "not-a-commit",
    ],
)
def test_begin_protection_rejects_unsafe_legacy_source_commit(tmp_path, source_commit):
    target = updater.ReleaseTargetInfo(
        version="v1.3.0-rc.3",
        tag="v1.3.0-rc.3",
        sha="d" * 40,
        release_manifest_sha256="e" * 64,
        machine_data_contract=_m6_release_manifest()["machine_data"],
    )
    config = _config(
        tmp_path,
        machine_data_required=True,
        machine_data_root=(tmp_path / "machine-data").resolve(),
        source_app_version="v1.3.0-rc.2",
        source_commit=source_commit,
    )

    with pytest.raises(Exception) as error:
        updater._begin_machine_data_protection(
            config,
            repo_root=tmp_path,
            before_release_version="v1.3.0-rc.2",
            before_sha="5f54a4a174cd50f145e1bfa98aa61535b7aa59e9",
            target_info=target,
            operation=updater.OPERATION_UPDATE,
            update_source=updater.UPDATE_SOURCE_ONLINE,
        )

    assert getattr(error.value, "code", "") == "source_binding_mismatch"


def test_external_candidate_updater_uses_its_own_machine_data_modules(tmp_path):
    production = tmp_path / "production"
    candidate = tmp_path / "candidate"
    production_interface = production / "FreeRTOS-interface"
    candidate_interface = candidate / "FreeRTOS-interface"
    production_interface.mkdir(parents=True)
    candidate_interface.mkdir(parents=True)
    candidate_script = candidate / "tools" / "update_and_restart.py"
    candidate_script.parent.mkdir()
    candidate_script.write_text("", encoding="utf-8")
    (candidate_interface / "MachineDataUpdate.py").write_text("", encoding="utf-8")

    assert updater._machine_data_import_root(
        production,
        updater_script=candidate_script,
    ) == candidate_interface.resolve()


def test_rc2_recovery_mode_builds_exact_binding_from_authorized_store(
    tmp_path,
    monkeypatch,
):
    from tests.test_machine_data_update_preservation import (
        SOURCE_COMMIT,
        _active_context,
    )

    context = _active_context(tmp_path)
    machine_data_root = context.paths.base.root
    anchor_path = context.paths.deployment_anchor_path
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    anchor["app_commit"] = SOURCE_COMMIT[:12]
    anchor_path.write_text(json.dumps(anchor), encoding="utf-8")
    support_reference = context.paths.update_history_root / "launcher_logs" / "failed.log"
    support_reference.parent.mkdir(parents=True)
    support_reference.write_text("source_binding_mismatch\n", encoding="utf-8")
    context.close()

    production = tmp_path / "production"
    candidate = tmp_path / "candidate"
    (production / "releases").mkdir(parents=True)
    (production / "VERSION").write_text("v1.3.0-rc.2\n", encoding="utf-8")
    (production / "releases" / "v1.3.0-rc.2.json").write_text(
        json.dumps(_m6_release_manifest("v1.3.0-rc.2")),
        encoding="utf-8",
    )
    (candidate / "tools").mkdir(parents=True)
    candidate_script = candidate / "tools" / "update_and_restart.py"
    candidate_script.write_text("", encoding="utf-8")
    (candidate / "VERSION").write_text("v1.3.0-rc.3\n", encoding="utf-8")
    target_commit = "d" * 40

    def runner(args, cwd, timeout_s, env_updates):
        git_args = tuple(str(value) for value in args[1:])
        root = Path(cwd)
        if root == production and git_args == ("rev-parse", "--show-toplevel"):
            return updater.CommandResult(tuple(args), 0, stdout=f"{production}\n")
        if root == production and git_args == ("rev-parse", "HEAD"):
            return updater.CommandResult(tuple(args), 0, stdout=f"{SOURCE_COMMIT}\n")
        if root == production and git_args == (
            "rev-parse",
            "refs/tags/v1.3.0-rc.3^{commit}",
        ):
            return updater.CommandResult(tuple(args), 0, stdout=f"{target_commit}\n")
        if root == candidate and git_args == ("rev-parse", "--show-toplevel"):
            return updater.CommandResult(tuple(args), 0, stdout=f"{candidate}\n")
        if root == candidate and git_args == ("rev-parse", "HEAD"):
            return updater.CommandResult(tuple(args), 0, stdout=f"{target_commit}\n")
        if root == candidate and git_args == ("status", "--porcelain"):
            return updater.CommandResult(tuple(args), 0, stdout="")
        return updater.CommandResult(tuple(args), 99, stderr=f"unexpected: {root} {git_args}")

    actual_interface = Path(updater.__file__).resolve().parents[1] / "FreeRTOS-interface"
    monkeypatch.setattr(updater, "_machine_data_import_root", lambda *args, **kwargs: actual_interface)
    config = _config(
        production,
        machine_data_required=True,
        machine_data_root=machine_data_root,
        target_release="v1.3.0-rc.3",
        gui=True,
        record_result=True,
        recover_rc2_source_binding=True,
        support_operator="Conary-Codex",
        support_reason="Recover the rc.2 short source binding defect",
        support_reference=str(support_reference),
    )

    recovered = updater.prepare_rc2_source_binding_recovery(
        config,
        command_runner=runner,
        updater_script=candidate_script,
    )

    assert recovered.source_app_version == "v1.3.0-rc.2"
    assert recovered.source_commit == SOURCE_COMMIT
    assert recovered.machine_id == "LC-001"
    assert recovered.active_pointer_sha256
    assert recovered.update_request_id
    assert recovered.log_path.parent.name == "updater_logs"
    assert recovered.latest_result_path.name == "latest_ui_result.json"


def test_rc2_recovery_mode_rejects_manually_supplied_identity(tmp_path):
    config = _config(
        tmp_path,
        machine_data_required=True,
        machine_data_root=(tmp_path / "machine-data").resolve(),
        target_release="v1.3.0-rc.3",
        gui=True,
        record_result=True,
        recover_rc2_source_binding=True,
        source_commit="a" * 40,
        support_operator="Operator",
        support_reason="Recovery",
        support_reference="failed.log",
    )

    with pytest.raises(updater.SourceBindingRecoveryError, match="must be derived"):
        updater.prepare_rc2_source_binding_recovery(config)


@pytest.mark.parametrize(
    "overrides",
    [
        {"rollback": True},
        {"offline_manifest_path": Path("offline.json")},
        {"wait_pid": 1234},
        {"gui": False},
        {"no_relaunch": False},
        {"record_result": False},
        {"relaunch_on_failure": True},
    ],
)
def test_rc2_recovery_mode_rejects_nonattended_modes(tmp_path, overrides):
    values = {
        "machine_data_required": True,
        "machine_data_root": (tmp_path / "machine-data").resolve(),
        "target_release": "v1.3.0-rc.3",
        "gui": True,
        "no_relaunch": True,
        "record_result": True,
        "recover_rc2_source_binding": True,
        "support_operator": "Operator",
        "support_reason": "Recovery",
        "support_reference": "failed.log",
    }
    values.update(overrides)

    with pytest.raises(updater.SourceBindingRecoveryError, match="attended online GUI"):
        updater.prepare_rc2_source_binding_recovery(_config(tmp_path, **values))


@pytest.mark.parametrize(
    ("candidate_status", "target_commit", "expected"),
    [
        (" M tools/update_and_restart.py\n", "d" * 40, "not clean"),
        ("", "e" * 40, "does not equal"),
    ],
)
def test_rc2_recovery_mode_rejects_unqualified_candidate(
    tmp_path,
    candidate_status,
    target_commit,
    expected,
):
    production = tmp_path / "production"
    candidate = tmp_path / "candidate"
    production.mkdir()
    (production / "VERSION").write_text("v1.3.0-rc.2\n", encoding="utf-8")
    (candidate / "tools").mkdir(parents=True)
    candidate_script = candidate / "tools" / "update_and_restart.py"
    candidate_script.write_text("", encoding="utf-8")
    (candidate / "VERSION").write_text("v1.3.0-rc.3\n", encoding="utf-8")
    source_commit = "a" * 40
    candidate_commit = "d" * 40

    def runner(args, cwd, timeout_s, env_updates):
        git_args = tuple(str(value) for value in args[1:])
        root = Path(cwd)
        responses = {
            (production, ("rev-parse", "--show-toplevel")): (0, str(production)),
            (production, ("rev-parse", "HEAD")): (0, source_commit),
            (candidate, ("rev-parse", "--show-toplevel")): (0, str(candidate)),
            (candidate, ("rev-parse", "HEAD")): (0, candidate_commit),
            (candidate, ("status", "--porcelain")): (0, candidate_status),
            (
                production,
                ("rev-parse", "refs/tags/v1.3.0-rc.3^{commit}"),
            ): (0, target_commit),
        }
        returncode, stdout = responses.get((root, git_args), (99, ""))
        return updater.CommandResult(tuple(args), returncode, stdout=f"{stdout}\n")

    config = _config(
        production,
        machine_data_required=True,
        machine_data_root=(tmp_path / "machine-data").resolve(),
        target_release="v1.3.0-rc.3",
        gui=True,
        record_result=True,
        recover_rc2_source_binding=True,
        support_operator="Operator",
        support_reason="Recovery",
        support_reference="failed.log",
    )

    with pytest.raises(updater.SourceBindingRecoveryError, match=expected):
        updater.prepare_rc2_source_binding_recovery(
            config,
            command_runner=runner,
            updater_script=candidate_script,
        )


def test_protected_update_preflight_failure_issues_zero_merge(tmp_path, monkeypatch):
    _write_version(tmp_path, "v1.1.1")
    runner = FakeGitRunner(
        tmp_path,
        before_sha="abc",
        after_sha="release789",
        release_manifest_payload=_m6_release_manifest(),
    )

    def stop(*_args, **_kwargs):
        raise RuntimeError("simulated backup failure")

    monkeypatch.setattr(updater, "_begin_machine_data_protection", stop)
    result = updater.run_update(
        _config(
            tmp_path,
            machine_data_required=True,
            source_app_version="v1.1.1",
            source_commit="abc",
        ),
        command_runner=runner,
    )

    assert result.status == updater.STATUS_MACHINE_DATA_PROTECTION_FAILED
    assert result.safe_to_reopen_current is True
    assert not any(call[0][1:3] == ("merge", "--ff-only") for call in runner.calls)


def test_protected_update_post_check_failure_blocks_relaunch(tmp_path, monkeypatch):
    _write_version(tmp_path, "v1.1.1")
    events = []
    prepared = _PreparedUpdateDouble(tmp_path, events, fail_verify=True)
    runner = FakeGitRunner(
        tmp_path,
        before_sha="abc",
        after_sha="release789",
        release_manifest_payload=_m6_release_manifest(),
    )
    monkeypatch.setattr(updater, "_begin_machine_data_protection", lambda *args, **kwargs: prepared)

    result = updater.run_update(
        _config(
            tmp_path,
            machine_data_required=True,
            source_app_version="v1.1.1",
            source_commit="abc",
        ),
        command_runner=runner,
    )

    assert result.status == updater.STATUS_RECOVERY_REQUIRED
    assert result.relaunch_authorized is False
    assert result.safe_to_reopen_current is False
    assert events == ["git_result", "post_verify", "fail:True", "close"]


def test_protected_failed_merge_with_changed_head_is_recovery_only(tmp_path, monkeypatch):
    _write_version(tmp_path, "v1.1.1")
    events = []
    prepared = _PreparedUpdateDouble(tmp_path, events)
    runner = FakeGitRunner(
        tmp_path,
        before_sha="abc",
        after_sha="ambiguous-head",
        pull_returncode=128,
        release_manifest_payload=_m6_release_manifest(),
    )
    monkeypatch.setattr(updater, "_begin_machine_data_protection", lambda *args, **kwargs: prepared)

    result = updater.run_update(
        _config(
            tmp_path,
            machine_data_required=True,
            source_app_version="v1.1.1",
            source_commit="abc",
        ),
        command_runner=runner,
    )

    assert result.status == updater.STATUS_RECOVERY_REQUIRED
    assert result.after_sha == "ambiguous-head"
    assert result.relaunch_authorized is False
    assert result.safe_to_reopen_current is False
    assert events == ["fail:True", "close"]


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
    assert "git merge --ff-only v1.1.2 failed" in result.message
    assert not launches


def test_online_update_merges_release_tag_not_git_pull(tmp_path):
    runner = FakeGitRunner(tmp_path, before_sha="abc", after_sha="def")

    result = updater.run_update(_config(tmp_path), command_runner=runner)

    calls = [call[0] for call in runner.calls]
    assert result.status == updater.STATUS_UPDATED
    assert ("git", "fetch", "--prune", "--tags") in calls
    assert ("git", "merge", "--ff-only", "v1.1.2") in calls
    assert ("git", "pull", "--ff-only") not in calls


def test_online_update_target_release_skips_latest_index_lookup(tmp_path):
    runner = FakeGitRunner(
        tmp_path,
        before_sha="abc",
        after_sha="def",
        release_index_returncode=128,
    )

    result = updater.run_update(
        _config(tmp_path, target_release="v1.1.2"),
        command_runner=runner,
    )

    calls = [call[0] for call in runner.calls]
    assert result.status == updater.STATUS_UPDATED
    assert ("git", "show", f"origin/main:{updater.RELEASE_INDEX_PATH}") not in calls
    assert not any(call[:2] == ("git", "tag") for call in calls)
    assert ("git", "merge", "--ff-only", "v1.1.2") in calls


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
    assert ("git", "merge", "--ff-only", f"{updater.OFFLINE_UPDATE_REF}^{{commit}}") in calls
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


def test_offline_release_update_apply_records_release_fields(tmp_path):
    manifest_path = _write_offline_manifest(tmp_path, head_sha=OFFLINE_SHA, release_version="v1.1.2")
    runner = FakeGitRunner(tmp_path, before_sha="abc", after_sha=OFFLINE_SHA, offline_ref_sha=OFFLINE_SHA)

    result = updater.run_update(
        _config(tmp_path, offline_manifest_path=manifest_path),
        command_runner=runner,
    )

    assert result.status == updater.STATUS_UPDATED
    assert result.update_source == updater.UPDATE_SOURCE_OFFLINE
    assert result.target_release_version == "v1.1.2"
    assert result.target_release_tag == "v1.1.2"
    assert result.target_release_sha == OFFLINE_SHA
    assert result.release_summary == "Release-aware offline bundle."
    assert result.release_notes == ("Installs a named release from USB.",)
    assert result.rollback_version == "v1.1.1"
    payload = updater.update_result_payload(result)
    assert payload["target_release_version"] == "v1.1.2"
    assert payload["target_release_tag"] == "v1.1.2"
    assert payload["target_release_sha"] == OFFLINE_SHA


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


def test_online_rollback_check_reports_available_target(tmp_path):
    _write_version(tmp_path, "v1.2.0")
    runner = FakeGitRunner(
        tmp_path,
        target_release_version="v1.2.0",
        target_release_sha="2222222222222222222222222222222222222222",
        rollback_version="v1.1.2",
        rollback_release_version="v1.1.2",
        rollback_release_sha=ROLLBACK_SHA,
    )

    result = updater.run_rollback_check(_config(tmp_path, rollback=True), command_runner=runner)

    calls = [call[0] for call in runner.calls]
    assert result.status == updater.STATUS_ROLLBACK_AVAILABLE
    assert result.operation == updater.OPERATION_ROLLBACK
    assert result.update_source == updater.UPDATE_SOURCE_ONLINE
    assert result.before_release_version == "v1.2.0"
    assert result.after_release_version == "v1.1.2"
    assert result.target_release_version == "v1.1.2"
    assert result.target_release_tag == "v1.1.2"
    assert result.target_release_sha == ROLLBACK_SHA
    assert result.message == "Rollback is available from v1.2.0 to v1.1.2."
    assert ("git", "fetch", "--prune", "--tags") in calls
    assert not any(call[:3] == ("git", "reset", "--hard") for call in calls)


def test_online_rollback_check_dirty_worktree_blocks_before_fetch(tmp_path):
    _write_version(tmp_path, "v1.1.2")
    runner = FakeGitRunner(tmp_path, dirty_status=" M FreeRTOS-interface/App.py\n")

    result = updater.run_rollback_check(_config(tmp_path, rollback=True), command_runner=runner)

    calls = [call[0] for call in runner.calls]
    assert result.status == updater.STATUS_DIRTY_WORKTREE
    assert result.operation == updater.OPERATION_ROLLBACK
    assert ("git", "fetch", "--prune", "--tags") not in calls
    assert not any(call[:3] == ("git", "reset", "--hard") for call in calls)


def test_online_rollback_check_missing_version_fails_safely(tmp_path):
    runner = FakeGitRunner(tmp_path)

    result = updater.run_rollback_check(_config(tmp_path, rollback=True), command_runner=runner)

    calls = [call[0] for call in runner.calls]
    assert result.status == updater.STATUS_ROLLBACK_TARGET_INVALID
    assert "current release version" in result.message
    assert ("git", "fetch", "--prune", "--tags") not in calls
    assert not any(call[:3] == ("git", "reset", "--hard") for call in calls)


def test_online_rollback_check_missing_current_manifest_fails_safely(tmp_path):
    _write_version(tmp_path, "v1.1.2")
    runner = FakeGitRunner(tmp_path, release_manifest_returncode=128)

    result = updater.run_rollback_check(_config(tmp_path, rollback=True), command_runner=runner)

    assert result.status == updater.STATUS_ROLLBACK_TARGET_INVALID
    assert "current release metadata" in result.message
    assert not any(call[0][:3] == ("git", "reset", "--hard") for call in runner.calls)


def test_online_rollback_check_missing_rollback_version_returns_not_configured(tmp_path):
    _write_version(tmp_path, "v1.1.2")
    runner = FakeGitRunner(
        tmp_path,
        release_manifest_payload={
            "schema_version": updater.RELEASE_MANIFEST_SCHEMA_VERSION,
            "version": "v1.1.2",
            "tag": "v1.1.2",
            "channel": "stable",
            "release_date": "2026-07-06",
            "previous_version": "v1.1.1",
            "rollback_version": None,
            "requires_firmware": None,
            "summary": "No rollback.",
            "notes": [],
            "validation": [],
        },
    )

    result = updater.run_rollback_check(_config(tmp_path, rollback=True), command_runner=runner)

    assert result.status == updater.STATUS_ROLLBACK_NOT_CONFIGURED
    assert result.returncode == 0
    assert "does not define a rollback version" in result.message
    assert not any(call[0][:3] == ("git", "reset", "--hard") for call in runner.calls)


def test_online_rollback_check_unknown_target_tag_fails_safely(tmp_path):
    _write_version(tmp_path, "v1.1.2")
    runner = FakeGitRunner(tmp_path, rollback_release_tag_returncode=128)

    result = updater.run_rollback_check(_config(tmp_path, rollback=True), command_runner=runner)

    assert result.status == updater.STATUS_ROLLBACK_TARGET_INVALID
    assert "Release tag v1.1.1" in result.message
    assert not any(call[0][:3] == ("git", "reset", "--hard") for call in runner.calls)


def test_online_rollback_check_invalid_target_manifest_fails_safely(tmp_path):
    _write_version(tmp_path, "v1.1.2")
    runner = FakeGitRunner(
        tmp_path,
        rollback_release_manifest_payload={
            "schema_version": updater.RELEASE_MANIFEST_SCHEMA_VERSION,
            "version": "v9.9.9",
            "tag": "v9.9.9",
            "channel": "stable",
            "release_date": "2026-07-05",
            "previous_version": None,
            "rollback_version": None,
            "requires_firmware": None,
            "summary": "Wrong target.",
            "notes": [],
            "validation": [],
        },
    )

    result = updater.run_rollback_check(_config(tmp_path, rollback=True), command_runner=runner)

    assert result.status == updater.STATUS_ROLLBACK_TARGET_INVALID
    assert "version does not match" in result.message
    assert not any(call[0][:3] == ("git", "reset", "--hard") for call in runner.calls)


def test_online_rollback_check_fetch_failure_returns_fetch_failed(tmp_path):
    _write_version(tmp_path, "v1.2.0")
    runner = FakeGitRunner(tmp_path, fetch_returncode=128)

    result = updater.run_rollback_check(_config(tmp_path, rollback=True), command_runner=runner)

    assert result.status == updater.STATUS_FETCH_FAILED
    assert result.operation == updater.OPERATION_ROLLBACK
    assert result.update_source == updater.UPDATE_SOURCE_ONLINE
    assert "fetch release tags" in result.message


def test_offline_rollback_check_accepts_release_aware_bundle(tmp_path):
    _write_version(tmp_path, "v1.2.0")
    manifest_path = _write_offline_manifest(tmp_path, head_sha=OFFLINE_SHA, release_version="v1.1.2")
    runner = FakeGitRunner(tmp_path, offline_ref_sha=OFFLINE_SHA)

    result = updater.run_rollback_check(
        _config(tmp_path, rollback=True, offline_manifest_path=manifest_path),
        command_runner=runner,
    )

    calls = [call[0] for call in runner.calls]
    assert result.status == updater.STATUS_ROLLBACK_AVAILABLE
    assert result.operation == updater.OPERATION_ROLLBACK
    assert result.update_source == updater.UPDATE_SOURCE_OFFLINE
    assert result.offline_manifest_path == manifest_path.resolve()
    assert result.before_release_version == "v1.2.0"
    assert result.after_release_version == "v1.1.2"
    assert result.target_release_version == "v1.1.2"
    assert result.target_release_sha == OFFLINE_SHA
    assert any(call[:3] == ("git", "fetch", "--force") for call in calls)
    assert not any(call[:3] == ("git", "reset", "--hard") for call in calls)


def test_offline_rollback_check_rejects_legacy_bundle(tmp_path):
    _write_version(tmp_path, "v1.2.0")
    manifest_path = _write_offline_manifest(tmp_path, head_sha=OFFLINE_SHA)
    runner = FakeGitRunner(tmp_path, offline_ref_sha=OFFLINE_SHA)

    result = updater.run_rollback_check(
        _config(tmp_path, rollback=True, offline_manifest_path=manifest_path),
        command_runner=runner,
    )

    assert result.status == updater.STATUS_OFFLINE_BUNDLE_INVALID
    assert "release-aware offline bundle" in result.message
    assert not any(call[0][:3] == ("git", "reset", "--hard") for call in runner.calls)


def test_online_rollback_resets_to_manifest_rollback_version(tmp_path):
    _write_version(tmp_path, "v1.1.2")
    runner = FakeGitRunner(tmp_path, before_sha="abc", after_sha=ROLLBACK_SHA)

    result = updater.run_rollback(_config(tmp_path, rollback=True), command_runner=runner)

    calls = [call[0] for call in runner.calls]
    assert result.status == updater.STATUS_ROLLED_BACK
    assert result.operation == updater.OPERATION_ROLLBACK
    assert result.update_source == updater.UPDATE_SOURCE_ONLINE
    assert result.before_release_version == "v1.1.2"
    assert result.after_release_version == "v1.1.1"
    assert result.target_release_version == "v1.1.1"
    assert result.target_release_tag == "v1.1.1"
    assert result.target_release_sha == ROLLBACK_SHA
    assert result.before_sha == "abc"
    assert result.after_sha == ROLLBACK_SHA
    assert ("git", "fetch", "--prune", "--tags") in calls
    assert ("git", "reset", "--hard", "v1.1.1") in calls
    assert ("git", "merge", "--ff-only", "v1.1.1") not in calls
    assert ("git", "pull", "--ff-only") not in calls


def test_online_rollback_dirty_worktree_blocks_before_fetch_or_reset(tmp_path):
    _write_version(tmp_path, "v1.1.2")
    runner = FakeGitRunner(tmp_path, dirty_status=" M FreeRTOS-interface/App.py\n")

    result = updater.run_rollback(_config(tmp_path, rollback=True), command_runner=runner)

    calls = [call[0] for call in runner.calls]
    assert result.status == updater.STATUS_DIRTY_WORKTREE
    assert result.operation == updater.OPERATION_ROLLBACK
    assert ("git", "fetch", "--prune", "--tags") not in calls
    assert not any(call[:3] == ("git", "reset", "--hard") for call in calls)


def test_online_rollback_missing_version_fails_before_fetch_or_reset(tmp_path):
    runner = FakeGitRunner(tmp_path)

    result = updater.run_rollback(_config(tmp_path, rollback=True), command_runner=runner)

    calls = [call[0] for call in runner.calls]
    assert result.status == updater.STATUS_ROLLBACK_TARGET_INVALID
    assert "VERSION" in result.message
    assert ("git", "fetch", "--prune", "--tags") not in calls
    assert not any(call[:3] == ("git", "reset", "--hard") for call in calls)


def test_online_rollback_missing_current_release_manifest_fails_safely(tmp_path):
    _write_version(tmp_path, "v1.1.2")
    runner = FakeGitRunner(tmp_path, release_manifest_returncode=128)

    result = updater.run_rollback(_config(tmp_path, rollback=True), command_runner=runner)

    assert result.status == updater.STATUS_ROLLBACK_TARGET_INVALID
    assert "rollback release target is invalid" in result.message
    assert not any(call[0][:3] == ("git", "reset", "--hard") for call in runner.calls)


def test_online_rollback_missing_rollback_version_fails_safely(tmp_path):
    _write_version(tmp_path, "v1.1.2")
    runner = FakeGitRunner(
        tmp_path,
        release_manifest_payload={
            "schema_version": updater.RELEASE_MANIFEST_SCHEMA_VERSION,
            "version": "v1.1.2",
            "tag": "v1.1.2",
            "channel": "stable",
            "release_date": "2026-07-06",
            "previous_version": "v1.1.1",
            "rollback_version": None,
            "requires_firmware": None,
            "summary": "No rollback.",
            "notes": [],
            "validation": [],
        },
    )

    result = updater.run_rollback(_config(tmp_path, rollback=True), command_runner=runner)

    assert result.status == updater.STATUS_ROLLBACK_TARGET_INVALID
    assert "does not define rollback_version" in result.message
    assert not any(call[0][:3] == ("git", "reset", "--hard") for call in runner.calls)


def test_online_rollback_unknown_target_tag_fails_safely(tmp_path):
    _write_version(tmp_path, "v1.1.2")
    runner = FakeGitRunner(tmp_path, rollback_release_tag_returncode=128)

    result = updater.run_rollback(_config(tmp_path, rollback=True), command_runner=runner)

    assert result.status == updater.STATUS_ROLLBACK_TARGET_INVALID
    assert "Release tag v1.1.1" in result.message
    assert not any(call[0][:3] == ("git", "reset", "--hard") for call in runner.calls)


def test_online_rollback_invalid_target_manifest_fails_safely(tmp_path):
    _write_version(tmp_path, "v1.1.2")
    runner = FakeGitRunner(
        tmp_path,
        rollback_release_manifest_payload={
            "schema_version": updater.RELEASE_MANIFEST_SCHEMA_VERSION,
            "version": "v9.9.9",
            "tag": "v9.9.9",
            "channel": "stable",
            "release_date": "2026-07-05",
            "previous_version": None,
            "rollback_version": None,
            "requires_firmware": None,
            "summary": "Wrong target.",
            "notes": [],
            "validation": [],
        },
    )

    result = updater.run_rollback(_config(tmp_path, rollback=True), command_runner=runner)

    assert result.status == updater.STATUS_ROLLBACK_TARGET_INVALID
    assert "version does not match" in result.message
    assert not any(call[0][:3] == ("git", "reset", "--hard") for call in runner.calls)


def test_offline_rollback_resets_to_selected_release_bundle(tmp_path):
    _write_version(tmp_path, "v1.1.2")
    manifest_path = _write_offline_manifest(tmp_path, head_sha=OFFLINE_SHA, release_version="v1.1.1")
    runner = FakeGitRunner(tmp_path, before_sha="abc", after_sha=OFFLINE_SHA, offline_ref_sha=OFFLINE_SHA)

    result = updater.run_rollback(
        _config(tmp_path, rollback=True, offline_manifest_path=manifest_path),
        command_runner=runner,
    )

    calls = [call[0] for call in runner.calls]
    assert result.status == updater.STATUS_ROLLED_BACK
    assert result.operation == updater.OPERATION_ROLLBACK
    assert result.update_source == updater.UPDATE_SOURCE_OFFLINE
    assert result.offline_manifest_path == manifest_path.resolve()
    assert result.before_release_version == "v1.1.2"
    assert result.after_release_version == "v1.1.1"
    assert result.target_release_version == "v1.1.1"
    assert result.target_release_sha == OFFLINE_SHA
    assert ("git", "reset", "--hard", f"{updater.OFFLINE_UPDATE_REF}^{{commit}}") in calls
    assert not any(call[:2] == ("git", "merge") for call in calls)
    assert ("git", "pull", "--ff-only") not in calls


def test_offline_rollback_requires_release_aware_bundle(tmp_path):
    _write_version(tmp_path, "v1.1.2")
    manifest_path = _write_offline_manifest(tmp_path, head_sha=OFFLINE_SHA)
    runner = FakeGitRunner(tmp_path, offline_ref_sha=OFFLINE_SHA)

    result = updater.run_rollback(
        _config(tmp_path, rollback=True, offline_manifest_path=manifest_path),
        command_runner=runner,
    )

    assert result.status == updater.STATUS_ROLLBACK_TARGET_INVALID
    assert "release-aware offline bundle" in result.message
    assert not any(call[0][:3] == ("git", "reset", "--hard") for call in runner.calls)


def test_latest_result_json_written_for_rollback_result(tmp_path):
    _write_version(tmp_path, "v1.1.2")
    runner = FakeGitRunner(
        tmp_path,
        before_sha="abc",
        after_sha=ROLLBACK_SHA,
        update_commits=("def Newer release commit",),
    )

    result = updater.run_rollback(
        updater.UpdaterConfig(repo_root=tmp_path, no_relaunch=True, record_result=True, rollback=True),
        command_runner=runner,
    )

    payload = json.loads(updater.default_latest_result_path(tmp_path).read_text(encoding="utf-8"))
    assert result.status == updater.STATUS_ROLLED_BACK
    assert payload["operation"] == updater.OPERATION_ROLLBACK
    assert payload["status"] == updater.STATUS_ROLLED_BACK
    assert payload["before_sha"] == "abc"
    assert payload["after_sha"] == ROLLBACK_SHA
    assert payload["before_release_version"] == "v1.1.2"
    assert payload["after_release_version"] == "v1.1.1"
    assert payload["target_release_version"] == "v1.1.1"
    assert payload["commits"] == ["def Newer release commit"]


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
    assert config.target_release is None
    assert config.rollback is False
    assert config.recover_rc2_source_binding is False


def test_cli_parser_accepts_rc2_source_binding_recovery():
    config = updater.parse_args(
        [
            "--repo-root",
            ".",
            "--recover-rc2-source-binding",
            "--support-operator",
            "Conary-Codex",
            "--support-reason",
            "Recover rc.2 binding",
            "--support-reference",
            "failed.log",
        ]
    )

    assert config.recover_rc2_source_binding is True
    assert config.support_operator == "Conary-Codex"


def test_cli_parser_accepts_relaunch_on_failure():
    config = updater.parse_args(["--repo-root", ".", "--wait-pid", "4321", "--relaunch-on-failure"])

    assert config.relaunch_on_failure is True


def test_cli_parser_accepts_gui():
    config = updater.parse_args(["--repo-root", ".", "--gui", "--record-result", "--latest-result-path", "local/result.json"])

    assert config.gui is True
    assert config.record_result is True
    assert config.latest_result_path == Path("local/result.json")


def test_gui_main_sanitizes_qt_environment_before_import(tmp_path, monkeypatch):
    fake_update_window = types.ModuleType("tools.update_window")
    observed = {}

    def fake_run_gui(config):
        observed["config"] = config
        observed["env"] = {name: os.environ.get(name) for name in updater.QT_ENV_VARS_TO_REMOVE_FOR_GUI}
        observed["qt_platform"] = os.environ.get("QT_QPA_PLATFORM")
        return 0

    fake_update_window.run_gui = fake_run_gui
    monkeypatch.delattr(tools, "update_window", raising=False)
    monkeypatch.setitem(sys.modules, "tools.update_window", fake_update_window)
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setenv("QT_QPA_PLATFORM_PLUGIN_PATH", "/home/labcraft/LabCraft_printer/env/lib/python3.11/site-packages/cv2/qt/plugins")
    monkeypatch.setenv("QT_QPA_FONTDIR", "/home/labcraft/LabCraft_printer/env/lib/python3.11/site-packages/cv2/qt/fonts")
    monkeypatch.setenv("QT_PLUGIN_PATH", "/bad/plugin/path")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

    exit_code = updater.main(["--repo-root", str(tmp_path), "--gui", "--no-relaunch"])

    assert exit_code == 0
    assert observed["config"].gui is True
    assert observed["env"] == {
        "QT_QPA_PLATFORM_PLUGIN_PATH": None,
        "QT_QPA_FONTDIR": None,
        "QT_PLUGIN_PATH": None,
    }
    assert observed["qt_platform"] == "wayland;xcb"


def test_gui_qt_platform_preference_preserves_explicit_platform():
    env = {
        "WAYLAND_DISPLAY": "wayland-0",
        "QT_QPA_PLATFORM": "offscreen",
        "QT_QPA_PLATFORM_PLUGIN_PATH": "/bad/plugins",
    }

    removed = updater.sanitize_qt_environment_for_gui(env)

    assert removed == {"QT_QPA_PLATFORM_PLUGIN_PATH": "/bad/plugins"}
    assert env["QT_QPA_PLATFORM"] == "offscreen"


def test_gui_qt_platform_preference_overrides_xcb_in_wayland_session():
    env = {
        "WAYLAND_DISPLAY": "wayland-0",
        "QT_QPA_PLATFORM": "xcb",
        "QT_QPA_PLATFORM_PLUGIN_PATH": "/bad/plugins",
    }

    removed = updater.sanitize_qt_environment_for_gui(env)

    assert removed == {"QT_QPA_PLATFORM_PLUGIN_PATH": "/bad/plugins"}
    assert env["QT_QPA_PLATFORM"] == "wayland;xcb"


def test_cli_parser_accepts_offline_manifest():
    config = updater.parse_args(["--repo-root", ".", "--offline-manifest", "LabCraftUpdates/update.json"])

    assert config.offline_manifest_path == Path("LabCraftUpdates/update.json")


def test_cli_parser_accepts_target_release():
    config = updater.parse_args(["--repo-root", ".", "--target-release", "v1.1.2"])

    assert config.target_release == "v1.1.2"


def test_cli_parser_accepts_release_channel():
    config = updater.parse_args(["--repo-root", ".", "--release-channel", "release_candidate"])

    assert config.release_channel == "release_candidate"


def test_cli_parser_accepts_rollback():
    config = updater.parse_args(["--repo-root", ".", "--rollback"])

    assert config.rollback is True


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
    assert "resolving_release" in kinds
    assert any(event.kind == "command" and "git merge --ff-only v1.1.2" in event.details for event in events)
    assert not any(event.kind == "command" and "git pull --ff-only" in event.details for event in events)


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
    assert result.message == "LabCraft is up to date with v1.1.2."
    assert result.upstream == "origin/main"
    assert result.target_release_version == "v1.1.2"
    assert result.target_release_sha == "release789"
    calls = [call[0] for call in runner.calls]
    assert ("git", "fetch", "--prune", "--tags") in calls
    assert not any(call[:2] == ("git", "tag") for call in calls)


def test_update_check_behind_upstream_returns_update_available_with_commits(tmp_path):
    runner = FakeGitRunner(
        tmp_path,
        ahead_count=0,
        behind_count=2,
        check_commits=("def456 Add updater result dialog", "abc123 Improve update check"),
    )

    result = updater.run_update_check(_config(tmp_path), command_runner=runner)

    assert result.status == updater.STATUS_UPDATE_AVAILABLE
    assert result.message == "LabCraft v1.1.2 is available."
    assert result.behind_count == 2
    assert result.target_release_version == "v1.1.2"
    assert result.release_summary == "Release-aware updater bootstrap."
    assert result.release_notes == ("Adds release metadata.",)
    assert result.rollback_version == "v1.1.1"
    assert result.commits == (
        "def456 Add updater result dialog",
        "abc123 Improve update check",
    )


def test_update_check_release_candidate_channel_reports_candidate_update(tmp_path):
    runner = FakeGitRunner(
        tmp_path,
        ahead_count=0,
        behind_count=2,
        check_commits=("def456 Camera refactor RC", "abc123 Manual refuel checks"),
        target_release_version="v1.2.0-rc.3",
        target_release_sha="rc789",
        target_release_channel="release_candidate",
        release_summary="Camera refactor release candidate.",
        release_notes=("Adds the camera refactor release candidate.",),
        release_index_payload={
            "schema_version": updater.RELEASE_INDEX_SCHEMA_VERSION,
            "stable": "v1.1.3",
            "release_candidate": "v1.2.0-rc.3",
            "releases": ["v1.2.0-rc.3", "v1.1.3", "v1.1.2"],
        },
    )

    result = updater.run_update_check(
        _config(tmp_path, release_channel="release_candidate"),
        command_runner=runner,
    )

    assert result.status == updater.STATUS_UPDATE_AVAILABLE
    assert result.message == "LabCraft v1.2.0-rc.3 is available."
    assert result.target_release_version == "v1.2.0-rc.3"
    assert result.target_release_sha == "rc789"
    assert result.release_summary == "Camera refactor release candidate."
    assert result.release_notes == ("Adds the camera refactor release candidate.",)
    assert ("git", "merge", "--ff-only", "v1.2.0-rc.3") not in [call[0] for call in runner.calls]


def test_update_check_release_candidate_series_selects_highest_valid_candidate(tmp_path):
    rc6_sha = "6666666666666666666666666666666666666666"
    rc7_sha = "7777777777777777777777777777777777777777"
    runner = FakeGitRunner(
        tmp_path,
        ahead_count=0,
        behind_count=2,
        check_commits=("def456 Camera refactor RC7", "abc123 Manual refuel checks"),
        target_release_version="v1.2.0-rc.6",
        target_release_sha=rc6_sha,
        target_release_channel="release_candidate",
        release_tag_list=("v1.2.0-rc.6", "v1.2.0-rc.7", "v1.2.0-rc.beta", "v1.3.0-rc.9"),
        release_tag_shas={
            "v1.2.0-rc.6": rc6_sha,
            "v1.2.0-rc.7": rc7_sha,
        },
        release_manifest_payloads={
            "v1.2.0-rc.7": {
                "schema_version": updater.RELEASE_MANIFEST_SCHEMA_VERSION,
                "version": "v1.2.0-rc.7",
                "tag": "v1.2.0-rc.7",
                "channel": "release_candidate",
                "release_date": "2026-07-09",
                "previous_version": "v1.2.0-rc.6",
                "rollback_version": "v1.1.17",
                "requires_firmware": None,
                "summary": "Camera refactor RC7.",
                "notes": ["Adds the latest release candidate."],
                "validation": ["Focused updater tests pass."],
            },
        },
        release_index_payload={
            "schema_version": updater.RELEASE_INDEX_SCHEMA_VERSION,
            "stable": "v1.1.17",
            "release_candidate": "v1.2.0-rc.6",
            "release_candidate_series": {
                "tag_prefix": "v1.2.0-rc.",
                "minimum": "v1.2.0-rc.6",
            },
            "releases": ["v1.2.0-rc.6", "v1.1.17"],
        },
    )

    result = updater.run_update_check(
        _config(tmp_path, release_channel="release_candidate"),
        command_runner=runner,
    )

    calls = [call[0] for call in runner.calls]
    assert result.status == updater.STATUS_UPDATE_AVAILABLE
    assert result.message == "LabCraft v1.2.0-rc.7 is available."
    assert result.target_release_version == "v1.2.0-rc.7"
    assert result.target_release_sha == rc7_sha
    assert result.release_summary == "Camera refactor RC7."
    assert result.release_notes == ("Adds the latest release candidate.",)
    assert ("git", "tag", "--list", "v1.2.0-rc.*") in calls


def test_update_check_release_candidate_series_skips_invalid_candidates(tmp_path):
    rc6_sha = "6666666666666666666666666666666666666666"
    rc7_sha = "7777777777777777777777777777777777777777"
    rc8_sha = "8888888888888888888888888888888888888888"
    rc5_sha = "5555555555555555555555555555555555555555"
    runner = FakeGitRunner(
        tmp_path,
        ahead_count=0,
        behind_count=1,
        target_release_version="v1.2.0-rc.6",
        target_release_sha=rc6_sha,
        target_release_channel="release_candidate",
        release_tag_list=("v1.2.0-rc.5", "v1.2.0-rc.6", "v1.2.0-rc.7", "v1.2.0-rc.8"),
        release_tag_shas={
            "v1.2.0-rc.5": rc5_sha,
            "v1.2.0-rc.6": rc6_sha,
            "v1.2.0-rc.7": rc7_sha,
            "v1.2.0-rc.8": rc8_sha,
        },
        release_manifest_returncodes={"v1.2.0-rc.8": 128},
        release_manifest_payloads={
            "v1.2.0-rc.7": {
                "schema_version": updater.RELEASE_MANIFEST_SCHEMA_VERSION,
                "version": "v1.2.0-rc.7",
                "tag": "v1.2.0-rc.7",
                "channel": "stable",
                "release_date": "2026-07-09",
                "previous_version": "v1.2.0-rc.6",
                "rollback_version": "v1.1.17",
                "requires_firmware": None,
                "summary": "Wrong channel.",
                "notes": ["This should be ignored."],
                "validation": [],
            },
        },
        release_index_payload={
            "schema_version": updater.RELEASE_INDEX_SCHEMA_VERSION,
            "stable": "v1.1.17",
            "release_candidate": "v1.2.0-rc.6",
            "release_candidate_series": {
                "tag_prefix": "v1.2.0-rc.",
                "minimum": "v1.2.0-rc.6",
            },
            "releases": ["v1.2.0-rc.6", "v1.1.17"],
        },
    )

    result = updater.run_update_check(
        _config(tmp_path, release_channel="release_candidate"),
        command_runner=runner,
    )

    calls = [call[0] for call in runner.calls]
    assert result.status == updater.STATUS_UPDATE_AVAILABLE
    assert result.target_release_version == "v1.2.0-rc.6"
    assert result.target_release_sha == rc6_sha
    assert ("git", "rev-parse", "v1.2.0-rc.5^{commit}") not in calls


def test_update_check_release_candidate_series_falls_back_to_exact_pointer(tmp_path):
    runner = FakeGitRunner(
        tmp_path,
        ahead_count=0,
        behind_count=1,
        target_release_version="v1.2.0-rc.6",
        target_release_sha="6666666666666666666666666666666666666666",
        target_release_channel="release_candidate",
        release_tag_list=("v1.2.0-rc.5",),
        release_index_payload={
            "schema_version": updater.RELEASE_INDEX_SCHEMA_VERSION,
            "stable": "v1.1.17",
            "release_candidate": "v1.2.0-rc.6",
            "release_candidate_series": {
                "tag_prefix": "v1.2.0-rc.",
                "minimum": "v1.2.0-rc.6",
            },
            "releases": ["v1.2.0-rc.6", "v1.1.17"],
        },
    )

    result = updater.run_update_check(
        _config(tmp_path, release_channel="release_candidate"),
        command_runner=runner,
    )

    calls = [call[0] for call in runner.calls]
    assert result.status == updater.STATUS_UPDATE_AVAILABLE
    assert result.target_release_version == "v1.2.0-rc.6"
    assert ("git", "tag", "--list", "v1.2.0-rc.*") in calls
    assert ("git", "rev-parse", "v1.2.0-rc.6^{commit}") in calls


def test_update_check_release_candidate_series_invalid_metadata_fails_safely(tmp_path):
    runner = FakeGitRunner(
        tmp_path,
        target_release_version="v1.2.0-rc.6",
        target_release_channel="release_candidate",
        release_index_payload={
            "schema_version": updater.RELEASE_INDEX_SCHEMA_VERSION,
            "stable": "v1.1.17",
            "release_candidate": "v1.2.0-rc.6",
            "release_candidate_series": {
                "tag_prefix": "v1.2.0-rc.",
                "minimum": "v1.3.0-rc.1",
            },
            "releases": ["v1.2.0-rc.6", "v1.1.17"],
        },
    )

    result = updater.run_update_check(
        _config(tmp_path, release_channel="release_candidate"),
        command_runner=runner,
    )

    calls = [call[0] for call in runner.calls]
    assert result.status == updater.STATUS_FETCH_FAILED
    assert "release_candidate_series minimum" in result.message
    assert not any(call[:2] == ("git", "merge") for call in calls)


def test_update_check_release_candidate_channel_without_candidate_fails_safely(tmp_path):
    runner = FakeGitRunner(
        tmp_path,
        release_index_payload={
            "schema_version": updater.RELEASE_INDEX_SCHEMA_VERSION,
            "stable": "v1.1.3",
            "release_candidate": None,
            "releases": ["v1.1.3", "v1.1.2"],
        },
    )

    result = updater.run_update_check(
        _config(tmp_path, release_channel="release_candidate"),
        command_runner=runner,
    )

    calls = [call[0] for call in runner.calls]
    assert result.status == updater.STATUS_FETCH_FAILED
    assert "release candidate release metadata" in result.message
    assert "release_candidate" in result.message
    assert not any(call[:2] == ("git", "merge") for call in calls)


def test_update_check_dirty_worktree_blocks_before_fetch(tmp_path):
    runner = FakeGitRunner(tmp_path, dirty_status=" M FreeRTOS-interface/App.py\n")

    result = updater.run_update_check(_config(tmp_path), command_runner=runner)

    assert result.status == updater.STATUS_DIRTY_WORKTREE
    assert ("git", "fetch", "--prune", "--tags") not in [call[0] for call in runner.calls]


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
    assert result.target_release_version == "v1.1.2"


def test_update_check_fetch_failure_returns_fetch_failed(tmp_path):
    runner = FakeGitRunner(tmp_path, fetch_returncode=128)

    result = updater.run_update_check(_config(tmp_path), command_runner=runner)

    assert result.status == updater.STATUS_FETCH_FAILED
    assert "remote repository" in result.message


def test_update_check_invalid_release_index_fails_safely(tmp_path):
    runner = FakeGitRunner(
        tmp_path,
        release_index_payload={
            "schema_version": updater.RELEASE_INDEX_SCHEMA_VERSION,
            "stable": "../bad",
            "release_candidate": None,
            "releases": ["../bad"],
        },
    )

    result = updater.run_update_check(_config(tmp_path), command_runner=runner)

    calls = [call[0] for call in runner.calls]
    assert result.status == updater.STATUS_FETCH_FAILED
    assert "release metadata" in result.message
    assert ("git", "merge", "--ff-only", "../bad") not in calls


def test_update_check_missing_release_manifest_fails_safely(tmp_path):
    runner = FakeGitRunner(tmp_path, release_manifest_returncode=128)

    result = updater.run_update_check(_config(tmp_path), command_runner=runner)

    assert result.status == updater.STATUS_FETCH_FAILED
    assert "release metadata" in result.message


def test_update_check_missing_release_index_fails_safely(tmp_path):
    runner = FakeGitRunner(tmp_path, release_index_returncode=128)

    result = updater.run_update_check(_config(tmp_path), command_runner=runner)

    assert result.status == updater.STATUS_FETCH_FAILED
    assert "release metadata" in result.message


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


def test_offline_release_update_check_reports_release_details(tmp_path):
    manifest_path = _write_offline_manifest(tmp_path, head_sha=OFFLINE_SHA, release_version="v1.1.2")
    runner = FakeGitRunner(
        tmp_path,
        offline_ref_sha=OFFLINE_SHA,
        offline_ahead_count=0,
        offline_behind_count=2,
        offline_check_commits=("def Offline release update", "abc Earlier metadata"),
    )

    result = updater.run_update_check(
        _config(tmp_path, offline_manifest_path=manifest_path),
        command_runner=runner,
    )

    assert result.status == updater.STATUS_UPDATE_AVAILABLE
    assert result.message == "LabCraft v1.1.2 is available from the offline bundle."
    assert result.update_source == updater.UPDATE_SOURCE_OFFLINE
    assert result.target_release_version == "v1.1.2"
    assert result.target_release_tag == "v1.1.2"
    assert result.target_release_sha == OFFLINE_SHA
    assert result.release_summary == "Release-aware offline bundle."
    assert result.release_notes == ("Installs a named release from USB.",)
    assert result.rollback_version == "v1.1.1"
    assert result.commits == ("def Offline release update", "abc Earlier metadata")


def test_offline_release_manifest_invalid_fails_before_bundle_fetch(tmp_path):
    manifest_path = _write_offline_manifest(
        tmp_path,
        head_sha=OFFLINE_SHA,
        release_version="v1.1.2",
        release_manifest={
            "schema_version": updater.RELEASE_MANIFEST_SCHEMA_VERSION,
            "version": "v9.9.9",
            "tag": "v9.9.9",
            "channel": "stable",
            "release_date": "2026-07-06",
            "previous_version": "v1.1.1",
            "rollback_version": "v1.1.1",
            "requires_firmware": None,
            "summary": "Wrong release.",
            "notes": [],
            "validation": [],
        },
    )
    runner = FakeGitRunner(tmp_path, offline_ref_sha=OFFLINE_SHA)

    result = updater.run_update_check(
        _config(tmp_path, offline_manifest_path=manifest_path),
        command_runner=runner,
    )

    assert result.status == updater.STATUS_OFFLINE_BUNDLE_INVALID
    assert "version does not match" in result.message
    assert not any(call[0][:3] == ("git", "fetch", "--force") for call in runner.calls)


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
        offline_target_ref = f"{updater.OFFLINE_UPDATE_REF}^{{commit}}"
        if len(git_args) == 4 and git_args[:2] == ("fetch", "--force"):
            state["bundle_name"] = Path(git_args[2]).name
        if git_args == ("rev-list", "--left-right", "--count", f"HEAD...{offline_target_ref}"):
            if state["bundle_name"] == "diverged.bundle":
                return updater.CommandResult(args_tuple, 0, stdout="1\t2\n")
            return updater.CommandResult(args_tuple, 0, stdout="0\t1\n")
        if git_args == ("log", "--oneline", f"HEAD..{offline_target_ref}"):
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


def test_rollback_fallback_does_not_scan_when_online_check_succeeds(tmp_path):
    _write_version(tmp_path, "v1.2.0")
    missing_manifest = tmp_path / "missing.json"
    runner = FakeGitRunner(
        tmp_path,
        target_release_version="v1.2.0",
        rollback_version="v1.1.2",
        rollback_release_version="v1.1.2",
        rollback_release_sha=ROLLBACK_SHA,
    )

    result = updater.run_rollback_check_with_offline_fallback(
        _config(tmp_path, rollback=True),
        command_runner=runner,
        manifest_paths=[missing_manifest],
    )

    assert result.status == updater.STATUS_ROLLBACK_AVAILABLE
    assert result.update_source == updater.UPDATE_SOURCE_ONLINE
    assert result.after_release_version == "v1.1.2"


def test_rollback_fallback_selects_valid_release_bundle_after_fetch_failure(tmp_path):
    _write_version(tmp_path, "v1.2.0")
    old_manifest = _write_offline_manifest(
        tmp_path,
        head_sha=OFFLINE_SHA,
        bundle_name="old-rollback.bundle",
        created_at_utc="2026-06-18T10:00:00Z",
        release_version="v1.1.1",
    )
    new_manifest = _write_offline_manifest(
        tmp_path,
        head_sha=OFFLINE_SHA,
        bundle_name="new-rollback.bundle",
        created_at_utc="2026-06-18T12:00:00Z",
        release_version="v1.1.2",
    )
    runner = FakeGitRunner(tmp_path, fetch_returncode=128, offline_ref_sha=OFFLINE_SHA)

    result = updater.run_rollback_check_with_offline_fallback(
        _config(tmp_path, rollback=True),
        command_runner=runner,
        manifest_paths=[old_manifest, new_manifest],
    )

    assert result.status == updater.STATUS_ROLLBACK_AVAILABLE
    assert result.update_source == updater.UPDATE_SOURCE_OFFLINE
    assert result.offline_manifest_path == new_manifest.resolve()
    assert result.before_release_version == "v1.2.0"
    assert result.after_release_version == "v1.1.2"


def test_rollback_fallback_skips_invalid_and_unusable_candidates(tmp_path):
    _write_version(tmp_path, "v1.2.0")
    wrong_branch = _write_offline_manifest(
        tmp_path,
        branch="stable",
        bundle_name="wrong-branch-rollback.bundle",
        created_at_utc="2026-06-18T13:00:00Z",
        release_version="v1.1.2",
    )
    legacy = _write_offline_manifest(
        tmp_path,
        bundle_name="legacy-rollback.bundle",
        created_at_utc="2026-06-18T12:00:00Z",
    )
    current_release = _write_offline_manifest(
        tmp_path,
        bundle_name="current-release-rollback.bundle",
        created_at_utc="2026-06-18T11:00:00Z",
        release_version="v1.2.0",
    )
    valid = _write_offline_manifest(
        tmp_path,
        bundle_name="valid-rollback.bundle",
        created_at_utc="2026-06-18T10:00:00Z",
        release_version="v1.1.2",
    )
    runner = FakeGitRunner(tmp_path, fetch_returncode=128, offline_ref_sha=OFFLINE_SHA)

    result = updater.run_rollback_check_with_offline_fallback(
        _config(tmp_path, rollback=True),
        command_runner=runner,
        manifest_paths=[valid, current_release, legacy, wrong_branch],
    )

    assert result.status == updater.STATUS_ROLLBACK_AVAILABLE
    assert result.update_source == updater.UPDATE_SOURCE_OFFLINE
    assert result.offline_manifest_path == valid.resolve()
    assert result.after_release_version == "v1.1.2"


def test_rollback_fallback_preserves_fetch_failed_when_no_usable_bundle(tmp_path):
    _write_version(tmp_path, "v1.2.0")
    manifest_path = tmp_path / "missing.json"
    runner = FakeGitRunner(tmp_path, fetch_returncode=128)

    result = updater.run_rollback_check_with_offline_fallback(
        _config(tmp_path, rollback=True),
        command_runner=runner,
        manifest_paths=[manifest_path],
    )

    assert result.status == updater.STATUS_FETCH_FAILED
    assert result.update_source == updater.UPDATE_SOURCE_ONLINE
    assert "No usable offline rollback bundle was found." in result.message


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
    assert payload["target_release_version"] == "v1.1.2"
    assert payload["target_release_tag"] == "v1.1.2"
    assert payload["target_release_sha"] == "release789"
    assert payload["release_summary"] == "Release-aware updater bootstrap."
    assert payload["release_notes"] == ["Adds release metadata."]
    assert payload["rollback_version"] == "v1.1.1"


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


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_real_git_release_offline_bundle_check_and_update(tmp_path):
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

    (support / "README.md").write_text("initial\nrelease\n", encoding="utf-8")
    releases_dir = support / "releases"
    releases_dir.mkdir()
    release_manifest = {
        "schema_version": "labcraft_release_v1",
        "version": "v1.1.2",
        "tag": "v1.1.2",
        "channel": "stable",
        "release_date": "2026-07-06",
        "previous_version": "v1.1.1",
        "rollback_version": "v1.1.1",
        "requires_firmware": None,
        "summary": "Release bundle smoke.",
        "notes": ["Installs a named release."],
        "validation": ["Real Git release bundle smoke test."],
    }
    (releases_dir / "v1.1.2.json").write_text(json.dumps(release_manifest), encoding="utf-8")
    _git(support, "add", "README.md", "releases/v1.1.2.json")
    _git(support, "commit", "-m", "release v1.1.2")
    release_sha = _git(support, "rev-parse", "HEAD").stdout.strip()
    _git(support, "tag", "-a", "v1.1.2", "-m", "LabCraft v1.1.2")
    _git(support, "push", "origin", "stable", "--tags")

    bundle_result = create_update_bundle.create_update_bundle(
        create_update_bundle.BundleConfig(repo_root=support, branch="stable", output_dir=output_dir, release="v1.1.2"),
    )
    manifest_path = bundle_result.manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    check = updater.run_update_check(
        updater.UpdaterConfig(repo_root=deployed, log_path=tmp_path / "release-check.log", offline_manifest_path=manifest_path),
    )
    assert check.status == updater.STATUS_UPDATE_AVAILABLE
    assert check.update_source == updater.UPDATE_SOURCE_OFFLINE
    assert check.target_release_version == "v1.1.2"
    assert check.release_summary == "Release bundle smoke."
    assert check.upstream_sha == release_sha
    assert manifest["source_ref"] == "refs/tags/v1.1.2"

    result = updater.run_update(
        updater.UpdaterConfig(repo_root=deployed, no_relaunch=True, log_path=tmp_path / "release-update.log", offline_manifest_path=manifest_path),
    )

    assert result.status == updater.STATUS_UPDATED
    assert result.update_source == updater.UPDATE_SOURCE_OFFLINE
    assert result.target_release_version == "v1.1.2"
    assert result.after_sha == release_sha
    assert _git(deployed, "rev-parse", "HEAD").stdout.strip() == release_sha


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_real_git_online_rollback_resets_to_manifest_rollback_version(tmp_path):
    remote = tmp_path / "remote.git"
    support = tmp_path / "support"
    deployed = tmp_path / "deployed"

    _git(tmp_path, "init", "--bare", str(remote))
    support.mkdir()
    _git(support, "init")
    _git(support, "config", "user.email", "test@example.com")
    _git(support, "config", "user.name", "Test User")
    _git(support, "remote", "add", "origin", str(remote))

    releases_dir = support / "releases"
    releases_dir.mkdir()
    (support / "VERSION").write_text("v1.1.1\n", encoding="utf-8")
    (support / "README.md").write_text("v1.1.1\n", encoding="utf-8")
    release_111 = {
        "schema_version": "labcraft_release_v1",
        "version": "v1.1.1",
        "tag": "v1.1.1",
        "channel": "stable",
        "release_date": "2026-07-05",
        "previous_version": "v1.1.0",
        "rollback_version": "v1.1.0",
        "requires_firmware": None,
        "summary": "Bugfix release.",
        "notes": ["Small UI fixes."],
        "validation": ["Real Git rollback smoke test."],
    }
    (releases_dir / "v1.1.1.json").write_text(json.dumps(release_111), encoding="utf-8")
    _git(support, "add", "README.md", "VERSION", "releases/v1.1.1.json")
    _git(support, "commit", "-m", "release v1.1.1")
    _git(support, "branch", "-M", "stable")
    rollback_sha = _git(support, "rev-parse", "HEAD").stdout.strip()
    _git(support, "tag", "-a", "v1.1.1", "-m", "LabCraft v1.1.1")

    (support / "VERSION").write_text("v1.1.2\n", encoding="utf-8")
    (support / "README.md").write_text("v1.1.2\n", encoding="utf-8")
    release_112 = {
        "schema_version": "labcraft_release_v1",
        "version": "v1.1.2",
        "tag": "v1.1.2",
        "channel": "stable",
        "release_date": "2026-07-06",
        "previous_version": "v1.1.1",
        "rollback_version": "v1.1.1",
        "requires_firmware": None,
        "summary": "Updater bootstrap.",
        "notes": ["Adds release-aware updater support."],
        "validation": ["Real Git rollback smoke test."],
    }
    (releases_dir / "v1.1.2.json").write_text(json.dumps(release_112), encoding="utf-8")
    _git(support, "add", "README.md", "VERSION", "releases/v1.1.2.json")
    _git(support, "commit", "-m", "release v1.1.2")
    release_sha = _git(support, "rev-parse", "HEAD").stdout.strip()
    _git(support, "tag", "-a", "v1.1.2", "-m", "LabCraft v1.1.2")
    _git(support, "push", "-u", "origin", "stable", "--tags")

    _git(tmp_path, "clone", "--branch", "stable", str(remote), str(deployed))
    assert _git(deployed, "rev-parse", "HEAD").stdout.strip() == release_sha

    result = updater.run_rollback(
        updater.UpdaterConfig(repo_root=deployed, no_relaunch=True, log_path=tmp_path / "rollback.log", rollback=True),
    )

    assert result.status == updater.STATUS_ROLLED_BACK
    assert result.operation == updater.OPERATION_ROLLBACK
    assert result.before_release_version == "v1.1.2"
    assert result.after_release_version == "v1.1.1"
    assert result.before_sha == release_sha
    assert result.after_sha == rollback_sha
    assert _git(deployed, "rev-parse", "HEAD").stdout.strip() == rollback_sha
