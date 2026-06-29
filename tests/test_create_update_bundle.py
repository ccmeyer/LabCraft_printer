import hashlib
import io
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools import create_update_bundle as bundler


NOW = datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc)
BUNDLE_BYTES = b"fake bundle bytes\n"
HEAD_SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
BASE_SHA = "00112233445566778899aabbccddeeff00112233"


class FakeGitRunner:
    def __init__(
        self,
        repo_root: Path,
        *,
        branch: str = "stable",
        remote: str = "origin",
        remote_url: str = "https://github.com/ccmeyer/LabCraft_printer",
        head_sha: str = HEAD_SHA,
        base_sha: str = BASE_SHA,
        fetch_returncode: int = 0,
        ref_returncode: int = 0,
        bundle_returncode: int = 0,
        verify_returncode: int = 0,
        remote_url_returncode: int = 0,
        top_level_returncode: int = 0,
        base_returncode: int = 0,
        ancestor_returncode: int = 0,
        count_returncode: int = 0,
        incremental_count: int = 2,
    ):
        self.repo_root = Path(repo_root)
        self.branch = branch
        self.remote = remote
        self.remote_url = remote_url
        self.head_sha = head_sha
        self.base_sha = base_sha
        self.fetch_returncode = fetch_returncode
        self.ref_returncode = ref_returncode
        self.bundle_returncode = bundle_returncode
        self.verify_returncode = verify_returncode
        self.remote_url_returncode = remote_url_returncode
        self.top_level_returncode = top_level_returncode
        self.base_returncode = base_returncode
        self.ancestor_returncode = ancestor_returncode
        self.count_returncode = count_returncode
        self.incremental_count = incremental_count
        self.calls: list[tuple[tuple[str, ...], Path]] = []

    def __call__(self, args, cwd):
        args_tuple = tuple(str(arg) for arg in args)
        self.calls.append((args_tuple, Path(cwd)))
        git_args = args_tuple[1:]

        if git_args == ("rev-parse", "--show-toplevel"):
            if self.top_level_returncode:
                return bundler.CommandResult(args_tuple, self.top_level_returncode, stderr="not a repo")
            return bundler.CommandResult(args_tuple, 0, stdout=f"{self.repo_root}\n")

        if git_args == ("fetch", "--prune", "--tags", self.remote):
            if self.fetch_returncode:
                return bundler.CommandResult(args_tuple, self.fetch_returncode, stderr="network unavailable")
            return bundler.CommandResult(args_tuple, 0, stdout="")

        if git_args == ("config", "--get", f"remote.{self.remote}.url"):
            if self.remote_url_returncode:
                return bundler.CommandResult(args_tuple, self.remote_url_returncode, stderr="no remote url")
            return bundler.CommandResult(args_tuple, 0, stdout=f"{self.remote_url}\n")

        source_ref = f"refs/remotes/{self.remote}/{self.branch}"
        if git_args == ("rev-parse", source_ref):
            if self.ref_returncode:
                return bundler.CommandResult(args_tuple, self.ref_returncode, stderr="bad ref")
            return bundler.CommandResult(args_tuple, 0, stdout=f"{self.head_sha}\n")

        if len(git_args) == 3 and git_args[:2] == ("rev-parse", "--verify") and git_args[2].endswith("^{commit}"):
            if self.base_returncode:
                return bundler.CommandResult(args_tuple, self.base_returncode, stderr="bad base")
            return bundler.CommandResult(args_tuple, 0, stdout=f"{self.base_sha}\n")

        if git_args == ("merge-base", "--is-ancestor", self.base_sha, self.head_sha):
            if self.ancestor_returncode:
                return bundler.CommandResult(args_tuple, self.ancestor_returncode, stderr="not ancestor")
            return bundler.CommandResult(args_tuple, 0, stdout="")

        if git_args == ("rev-list", "--count", f"{self.base_sha}..{self.head_sha}"):
            if self.count_returncode:
                return bundler.CommandResult(args_tuple, self.count_returncode, stderr="bad range")
            return bundler.CommandResult(args_tuple, 0, stdout=f"{self.incremental_count}\n")

        if len(git_args) >= 4 and git_args[:2] == ("bundle", "create"):
            if self.bundle_returncode:
                return bundler.CommandResult(args_tuple, self.bundle_returncode, stderr="bundle failed")
            Path(git_args[2]).write_bytes(BUNDLE_BYTES)
            return bundler.CommandResult(args_tuple, 0, stdout="")

        if len(git_args) == 3 and git_args[:2] == ("bundle", "verify"):
            if self.verify_returncode:
                return bundler.CommandResult(args_tuple, self.verify_returncode, stderr="verify failed")
            return bundler.CommandResult(args_tuple, 0, stdout="The bundle is okay\n")

        return bundler.CommandResult(args_tuple, 99, stderr=f"unexpected command: {git_args!r}")

    def git_calls(self):
        return [call[0] for call in self.calls]


def test_create_update_bundle_writes_manifest_and_summary_contract(tmp_path):
    runner = FakeGitRunner(tmp_path)
    result = bundler.create_update_bundle(
        bundler.BundleConfig(repo_root=tmp_path, output_dir=tmp_path / "out"),
        command_runner=runner,
        now=NOW,
    )

    expected_name = "labcraft-stable-20260618T120000Z-a1b2c3d4e5f6"
    assert result.bundle_path.name == f"{expected_name}.bundle"
    assert result.manifest_path.name == f"{expected_name}.json"
    assert result.bundle_path.read_bytes() == BUNDLE_BYTES

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest == result.manifest
    assert manifest["schema_version"] == bundler.SCHEMA_VERSION
    assert manifest["repo"] == "ccmeyer/LabCraft_printer"
    assert manifest["remote"] == "origin"
    assert manifest["remote_url"] == "https://github.com/ccmeyer/LabCraft_printer"
    assert manifest["branch"] == "stable"
    assert manifest["source_ref"] == "refs/remotes/origin/stable"
    assert manifest["head_sha"] == HEAD_SHA
    assert manifest["head_short_sha"] == "a1b2c3d4e5f6"
    assert manifest["created_at_utc"] == "2026-06-18T12:00:00Z"
    assert manifest["bundle_filename"] == result.bundle_path.name
    assert manifest["bundle_sha256"] == hashlib.sha256(BUNDLE_BYTES).hexdigest()
    assert manifest["bundle_size_bytes"] == len(BUNDLE_BYTES)
    assert manifest["include_tags"] is True
    assert manifest["bundle_mode"] == "full"
    assert manifest["base_selector"] is None
    assert manifest["base_sha"] is None
    assert manifest["base_short_sha"] is None
    assert manifest["incremental_commit_count"] is None
    assert manifest["producer"] == "tools/create_update_bundle.py"

    bundle_call = next(call for call in runner.git_calls() if call[1:3] == ("bundle", "create"))
    assert bundle_call[4:] == ("refs/remotes/origin/stable", "--tags")


def test_fetch_runs_by_default_and_can_be_skipped(tmp_path):
    default_runner = FakeGitRunner(tmp_path)
    bundler.create_update_bundle(
        bundler.BundleConfig(repo_root=tmp_path, output_dir=tmp_path / "default"),
        command_runner=default_runner,
        now=NOW,
    )
    assert ("git", "fetch", "--prune", "--tags", "origin") in default_runner.git_calls()

    skip_runner = FakeGitRunner(tmp_path)
    bundler.create_update_bundle(
        bundler.BundleConfig(repo_root=tmp_path, output_dir=tmp_path / "skip", fetch=False),
        command_runner=skip_runner,
        now=NOW,
    )
    assert ("git", "fetch", "--prune", "--tags", "origin") not in skip_runner.git_calls()


def test_no_tags_omits_tags_from_bundle_create(tmp_path):
    runner = FakeGitRunner(tmp_path)
    bundler.create_update_bundle(
        bundler.BundleConfig(repo_root=tmp_path, output_dir=tmp_path / "out", include_tags=False),
        command_runner=runner,
        now=NOW,
    )

    bundle_call = next(call for call in runner.git_calls() if call[1:3] == ("bundle", "create"))
    assert bundle_call[4:] == ("refs/remotes/origin/stable",)


def test_parser_rejects_since_and_last_together():
    parser = bundler.build_arg_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--since", "abc123", "--last", "20"])


def test_incremental_since_writes_manifest_and_omits_tags_by_default(tmp_path):
    runner = FakeGitRunner(tmp_path)
    result = bundler.create_update_bundle(
        bundler.BundleConfig(repo_root=tmp_path, output_dir=tmp_path / "out", since="abc123"),
        command_runner=runner,
        now=NOW,
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["bundle_mode"] == "incremental"
    assert manifest["base_selector"] == "abc123"
    assert manifest["base_sha"] == BASE_SHA
    assert manifest["base_short_sha"] == BASE_SHA[:12]
    assert manifest["incremental_commit_count"] == 2
    assert manifest["include_tags"] is False

    bundle_call = next(call for call in runner.git_calls() if call[1:3] == ("bundle", "create"))
    assert bundle_call[4:] == ("refs/remotes/origin/stable", f"^{BASE_SHA}")


def test_incremental_last_resolves_remote_tracking_base(tmp_path):
    runner = FakeGitRunner(tmp_path, incremental_count=20)
    result = bundler.create_update_bundle(
        bundler.BundleConfig(repo_root=tmp_path, output_dir=tmp_path / "out", last=20),
        command_runner=runner,
        now=NOW,
    )

    assert result.manifest["base_selector"] == "refs/remotes/origin/stable~20"
    assert result.manifest["incremental_commit_count"] == 20
    assert ("git", "rev-parse", "--verify", "refs/remotes/origin/stable~20^{commit}") in runner.git_calls()


def test_incremental_include_tags_can_be_forced(tmp_path):
    runner = FakeGitRunner(tmp_path)
    bundler.create_update_bundle(
        bundler.BundleConfig(repo_root=tmp_path, output_dir=tmp_path / "out", since="abc123", include_tags=True),
        command_runner=runner,
        now=NOW,
    )

    bundle_call = next(call for call in runner.git_calls() if call[1:3] == ("bundle", "create"))
    assert bundle_call[4:] == ("refs/remotes/origin/stable", f"^{BASE_SHA}", "--tags")


@pytest.mark.parametrize(
    ("config_kwargs", "runner_kwargs", "expected_status"),
    [
        ({"last": 0}, {}, bundler.STATUS_INVALID_ARGUMENT),
        ({"since": "missing"}, {"base_returncode": 128}, bundler.STATUS_BASE_RESOLVE_FAILED),
        ({"since": "abc123"}, {"ancestor_returncode": 1}, bundler.STATUS_BASE_NOT_ANCESTOR),
        ({"since": "abc123"}, {"incremental_count": 0}, bundler.STATUS_EMPTY_INCREMENTAL_RANGE),
        ({"since": "abc123"}, {"bundle_returncode": 1}, bundler.STATUS_BUNDLE_CREATE_FAILED),
        ({"since": "abc123"}, {"verify_returncode": 1}, bundler.STATUS_BUNDLE_VERIFY_FAILED),
    ],
)
def test_incremental_failures_return_clear_status(tmp_path, config_kwargs, runner_kwargs, expected_status):
    runner = FakeGitRunner(tmp_path, **runner_kwargs)

    with pytest.raises(bundler.BundleCreateError) as exc_info:
        bundler.create_update_bundle(
            bundler.BundleConfig(repo_root=tmp_path, output_dir=tmp_path / "out", **config_kwargs),
            command_runner=runner,
            now=NOW,
        )

    assert exc_info.value.status == expected_status


@pytest.mark.parametrize(
    ("runner_kwargs", "expected_status"),
    [
        ({"fetch_returncode": 1}, bundler.STATUS_FETCH_FAILED),
        ({"ref_returncode": 1}, bundler.STATUS_REF_RESOLVE_FAILED),
        ({"bundle_returncode": 1}, bundler.STATUS_BUNDLE_CREATE_FAILED),
        ({"verify_returncode": 1}, bundler.STATUS_BUNDLE_VERIFY_FAILED),
    ],
)
def test_cli_returns_nonzero_json_failure_for_git_errors(tmp_path, runner_kwargs, expected_status):
    runner = FakeGitRunner(tmp_path, **runner_kwargs)
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = bundler.main(
        ["--repo-root", str(tmp_path), "--output-dir", str(tmp_path / "out")],
        command_runner=runner,
        now=NOW,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == bundler.EXIT_CODES[expected_status]
    assert stdout.getvalue() == ""
    payload = json.loads(stderr.getvalue())
    assert payload["status"] == expected_status
    assert "message" in payload
    assert "command" in payload


def test_cli_returns_success_json(tmp_path):
    runner = FakeGitRunner(tmp_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = bundler.main(
        ["--repo-root", str(tmp_path), "--output-dir", str(tmp_path / "out")],
        command_runner=runner,
        now=NOW,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    payload = json.loads(stdout.getvalue())
    assert payload["status"] == "created"
    assert payload["branch"] == "stable"
    assert payload["head_sha"] == HEAD_SHA
    assert Path(payload["bundle_path"]).is_file()
    assert Path(payload["manifest_path"]).is_file()


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
def test_real_git_smoke_creates_verifiable_bundle(tmp_path):
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    out = tmp_path / "out"

    repo.mkdir()
    _git(tmp_path, "init", "--bare", str(remote))
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "branch", "-M", "stable")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-u", "origin", "stable")

    result = bundler.create_update_bundle(
        bundler.BundleConfig(repo_root=repo, output_dir=out),
        now=NOW,
    )

    verify = subprocess.run(
        ["git", "bundle", "verify", str(result.bundle_path)],
        cwd=str(repo),
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    assert verify.returncode == 0, verify.stderr
    assert result.manifest_path.is_file()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_real_git_smoke_creates_incremental_bundle_with_prerequisite(tmp_path):
    support = tmp_path / "support"
    remote = tmp_path / "remote.git"
    deployed = tmp_path / "deployed"
    missing_base = tmp_path / "missing-base"
    out = tmp_path / "out"

    support.mkdir()
    _git(tmp_path, "init", "--bare", str(remote))
    _git(support, "init")
    _git(support, "config", "user.email", "test@example.com")
    _git(support, "config", "user.name", "Test User")
    (support / "README.md").write_text("base\n", encoding="utf-8")
    _git(support, "add", "README.md")
    _git(support, "commit", "-m", "base")
    _git(support, "branch", "-M", "stable")
    _git(support, "remote", "add", "origin", str(remote))
    _git(support, "push", "-u", "origin", "stable")
    _git(remote, "symbolic-ref", "HEAD", "refs/heads/stable")
    base_sha = _git(support, "rev-parse", "HEAD").stdout.strip()

    _git(tmp_path, "clone", "-b", "stable", str(remote), str(deployed))

    (support / "README.md").write_text("base\nupdate 1\n", encoding="utf-8")
    _git(support, "add", "README.md")
    _git(support, "commit", "-m", "update 1")
    (support / "README.md").write_text("base\nupdate 1\nupdate 2\n", encoding="utf-8")
    _git(support, "add", "README.md")
    _git(support, "commit", "-m", "update 2")
    _git(support, "push", "origin", "stable")

    result = bundler.create_update_bundle(
        bundler.BundleConfig(repo_root=support, output_dir=out, since=base_sha),
        now=NOW,
    )

    assert result.manifest["bundle_mode"] == "incremental"
    assert result.manifest["base_sha"] == base_sha
    assert result.manifest["incremental_commit_count"] == 2

    verify = subprocess.run(
        ["git", "bundle", "verify", str(result.bundle_path)],
        cwd=str(deployed),
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    assert verify.returncode == 0, verify.stderr

    _git(
        deployed,
        "fetch",
        "--force",
        str(result.bundle_path),
        "refs/remotes/origin/stable:refs/labcraft/offline-update",
    )
    _git(deployed, "merge", "--ff-only", "refs/labcraft/offline-update")
    assert _git(deployed, "rev-parse", "HEAD").stdout.strip() == result.manifest["head_sha"]

    missing_base.mkdir()
    _git(missing_base, "init")
    missing_verify = subprocess.run(
        ["git", "bundle", "verify", str(result.bundle_path)],
        cwd=str(missing_base),
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_verify.returncode != 0
