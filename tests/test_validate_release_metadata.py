import io
import json
from pathlib import Path

from tools import validate_release_metadata as validator


def _manifest(
    version: str,
    *,
    channel: str = "stable",
    previous_version: str | None = None,
    rollback_version: str | None = None,
    notes: list[str] | None = None,
    validation: list[str] | None = None,
    requires_firmware=None,
) -> dict:
    return {
        "schema_version": validator.RELEASE_MANIFEST_SCHEMA_VERSION,
        "version": version,
        "tag": version,
        "channel": channel,
        "release_date": "2026-07-13",
        "previous_version": previous_version,
        "rollback_version": rollback_version,
        "requires_firmware": requires_firmware,
        "summary": f"{version} summary.",
        "notes": ["Release note."] if notes is None else notes,
        "validation": ["Focused tests pass."] if validation is None else validation,
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_release_tree(
    root: Path,
    *,
    version: str = "v1.1.2",
    latest: dict | None = None,
    manifests: dict[str, dict] | None = None,
    changelog_versions: list[str] | None = None,
) -> None:
    root.joinpath("VERSION").write_text(f"{version}\n", encoding="utf-8")
    versions = [version] if changelog_versions is None else changelog_versions
    root.joinpath("CHANGELOG.md").write_text(
        "# Changelog\n\n" + "\n".join(f"## {item} - 2026-07-13\n" for item in versions),
        encoding="utf-8",
    )
    if latest is None:
        latest = {
            "schema_version": validator.RELEASE_INDEX_SCHEMA_VERSION,
            "stable": version,
            "release_candidate": None,
            "releases": [version],
        }
    _write_json(root / "releases" / "latest.json", latest)
    manifests = {version: _manifest(version)} if manifests is None else manifests
    for manifest_version, manifest in manifests.items():
        _write_json(root / "releases" / f"{manifest_version}.json", manifest)


class FakeGitRunner:
    def __init__(self, repo_root: Path, *, tags: dict[str, str] | None = None, top_level_returncode: int = 0):
        self.repo_root = Path(repo_root)
        self.tags = dict(tags or {})
        self.top_level_returncode = top_level_returncode
        self.calls: list[tuple[tuple[str, ...], Path]] = []

    def __call__(self, args, cwd):
        raw_args = tuple(str(arg) for arg in args)
        git_args = raw_args[1:]
        if len(git_args) >= 2 and git_args[0] == "-c" and git_args[1].startswith("safe.directory="):
            git_args = git_args[2:]
        args_tuple = ("git", *git_args)
        self.calls.append((args_tuple, Path(cwd)))
        if git_args == ("rev-parse", "--show-toplevel"):
            if self.top_level_returncode:
                return validator.CommandResult(args_tuple, self.top_level_returncode, stderr="not a repo")
            return validator.CommandResult(args_tuple, 0, stdout=f"{self.repo_root}\n")
        if len(git_args) == 2 and git_args[0] == "rev-parse" and git_args[1].endswith("^{commit}"):
            version = git_args[1][: -len("^{commit}")]
            sha = self.tags.get(version)
            if sha:
                return validator.CommandResult(args_tuple, 0, stdout=f"{sha}\n")
            return validator.CommandResult(args_tuple, 128, stderr="unknown revision")
        return validator.CommandResult(args_tuple, 99, stderr=f"unexpected command: {git_args!r}")


def _validate(root: Path, *, check_tags: bool = False, runner: FakeGitRunner | None = None):
    runner = runner or FakeGitRunner(root)
    return validator.validate_release_metadata(
        validator.ValidationConfig(repo_root=root, check_tags=check_tags),
        command_runner=runner,
    )


def test_valid_stable_metadata_passes_without_existing_git_tag(tmp_path):
    _write_release_tree(tmp_path)

    result = _validate(tmp_path)

    assert result.status == validator.STATUS_VALID
    assert result.issues == ()


def test_valid_release_candidate_metadata_with_series_passes(tmp_path):
    latest = {
        "schema_version": validator.RELEASE_INDEX_SCHEMA_VERSION,
        "stable": "v1.1.17",
        "release_candidate": "v1.2.0-rc.6",
        "release_candidate_series": {
            "tag_prefix": "v1.2.0-rc.",
            "minimum": "v1.2.0-rc.6",
        },
        "releases": ["v1.2.0-rc.6", "v1.1.17"],
    }
    manifests = {
        "v1.1.17": _manifest("v1.1.17", channel="stable", rollback_version="v1.1.16"),
        "v1.2.0-rc.6": _manifest(
            "v1.2.0-rc.6",
            channel="release_candidate",
            previous_version="v1.2.0-rc.5",
            rollback_version="v1.1.17",
        ),
    }
    _write_release_tree(tmp_path, version="v1.2.0-rc.6", latest=latest, manifests=manifests)

    result = _validate(tmp_path)

    assert result.status == validator.STATUS_VALID
    assert result.issues == ()


def test_check_tags_verifies_advertised_and_referenced_tags(tmp_path):
    latest = {
        "schema_version": validator.RELEASE_INDEX_SCHEMA_VERSION,
        "stable": "v1.1.2",
        "release_candidate": None,
        "releases": ["v1.1.2"],
    }
    manifests = {"v1.1.2": _manifest("v1.1.2", previous_version="v1.1.1", rollback_version="v1.1.1")}
    _write_release_tree(tmp_path, latest=latest, manifests=manifests)
    runner = FakeGitRunner(
        tmp_path,
        tags={
            "v1.1.1": "1111111111111111111111111111111111111111",
            "v1.1.2": "2222222222222222222222222222222222222222",
        },
    )

    result = _validate(tmp_path, check_tags=True, runner=runner)

    assert result.status == validator.STATUS_VALID
    assert ("git", "rev-parse", "v1.1.2^{commit}") in [call[0] for call in runner.calls]
    assert ("git", "rev-parse", "v1.1.1^{commit}") in [call[0] for call in runner.calls]


def test_check_tags_reports_missing_tag(tmp_path):
    _write_release_tree(tmp_path)

    result = _validate(tmp_path, check_tags=True)

    assert result.status == validator.STATUS_INVALID
    assert "Git tag v1.1.2 could not be resolved." in result.issues


def test_main_outputs_success_message(tmp_path):
    _write_release_tree(tmp_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    returncode = validator.main(
        ["--repo-root", str(tmp_path)],
        command_runner=FakeGitRunner(tmp_path),
        stdout=stdout,
        stderr=stderr,
    )

    assert returncode == 0
    assert "Release metadata validation passed." in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_main_outputs_one_error_per_line(tmp_path):
    _write_release_tree(tmp_path)
    (tmp_path / "VERSION").write_text("not-a-version\n", encoding="utf-8")
    stdout = io.StringIO()
    stderr = io.StringIO()

    returncode = validator.main(
        ["--repo-root", str(tmp_path)],
        command_runner=FakeGitRunner(tmp_path),
        stdout=stdout,
        stderr=stderr,
    )

    assert returncode == validator.EXIT_CODES[validator.STATUS_INVALID]
    assert stdout.getvalue() == ""
    assert "ERROR: VERSION is not a supported LabCraft version" in stderr.getvalue()


def test_non_git_repo_returns_not_git_repo(tmp_path):
    result = _validate(tmp_path, runner=FakeGitRunner(tmp_path, top_level_returncode=128))

    assert result.status == validator.STATUS_NOT_GIT_REPO
    assert result.returncode == validator.EXIT_CODES[validator.STATUS_NOT_GIT_REPO]


def test_missing_version_fails(tmp_path):
    _write_release_tree(tmp_path)
    (tmp_path / "VERSION").unlink()

    result = _validate(tmp_path)

    assert result.status == validator.STATUS_INVALID
    assert "VERSION is missing." in result.issues


def test_changelog_missing_current_version_fails(tmp_path):
    _write_release_tree(tmp_path, changelog_versions=["v1.1.1"])

    result = _validate(tmp_path)

    assert result.status == validator.STATUS_INVALID
    assert "CHANGELOG.md does not contain a release heading for v1.1.2." in result.issues


def test_missing_matching_manifest_fails(tmp_path):
    _write_release_tree(tmp_path, manifests={})

    result = _validate(tmp_path)

    assert result.status == validator.STATUS_INVALID
    assert "VERSION v1.1.2 does not have a matching releases/v1.1.2.json." in result.issues


def test_manifest_version_mismatch_fails(tmp_path):
    manifests = {"v1.1.2": {**_manifest("v1.1.2"), "version": "v9.9.9"}}
    _write_release_tree(tmp_path, manifests=manifests)

    result = _validate(tmp_path)

    assert result.status == validator.STATUS_INVALID
    assert "v1.1.2.json version does not match its filename." in result.issues


def test_manifest_tag_mismatch_fails(tmp_path):
    manifests = {"v1.1.2": {**_manifest("v1.1.2"), "tag": "v9.9.9"}}
    _write_release_tree(tmp_path, manifests=manifests)

    result = _validate(tmp_path)

    assert result.status == validator.STATUS_INVALID
    assert "v1.1.2.json tag does not match its filename." in result.issues


def test_invalid_manifest_channel_fails(tmp_path):
    manifests = {"v1.1.2": {**_manifest("v1.1.2"), "channel": "beta"}}
    _write_release_tree(tmp_path, manifests=manifests)

    result = _validate(tmp_path)

    assert result.status == validator.STATUS_INVALID
    assert "v1.1.2.json channel must be stable or release_candidate." in result.issues


def test_unsupported_schema_versions_fail(tmp_path):
    latest = {
        "schema_version": "bad_index",
        "stable": "v1.1.2",
        "release_candidate": None,
        "releases": ["v1.1.2"],
    }
    manifests = {"v1.1.2": {**_manifest("v1.1.2"), "schema_version": "bad_manifest"}}
    _write_release_tree(tmp_path, latest=latest, manifests=manifests)

    result = _validate(tmp_path)

    assert result.status == validator.STATUS_INVALID
    assert "latest.json has unsupported schema_version." in result.issues
    assert "v1.1.2.json has unsupported schema_version." in result.issues


def test_latest_stable_must_be_valid_and_listed(tmp_path):
    latest = {
        "schema_version": validator.RELEASE_INDEX_SCHEMA_VERSION,
        "stable": "not-a-version",
        "release_candidate": None,
        "releases": ["v1.1.2"],
    }
    _write_release_tree(tmp_path, latest=latest)

    result = _validate(tmp_path)

    assert result.status == validator.STATUS_INVALID
    assert "latest.json stable is not a supported LabCraft version." in result.issues


def test_latest_release_candidate_must_be_listed(tmp_path):
    latest = {
        "schema_version": validator.RELEASE_INDEX_SCHEMA_VERSION,
        "stable": "v1.1.2",
        "release_candidate": "v1.2.0-rc.1",
        "releases": ["v1.1.2"],
    }
    _write_release_tree(tmp_path, latest=latest)

    result = _validate(tmp_path)

    assert result.status == validator.STATUS_INVALID
    assert "latest.json release_candidate must be included in releases." in result.issues


def test_known_metadata_incomplete_tag_is_rejected(tmp_path):
    latest = {
        "schema_version": validator.RELEASE_INDEX_SCHEMA_VERSION,
        "stable": "v1.1.2",
        "release_candidate": None,
        "releases": ["v1.1.2", "v1.1.15"],
    }
    _write_release_tree(tmp_path, latest=latest)

    result = _validate(tmp_path)

    assert result.status == validator.STATUS_INVALID
    assert "latest.json releases must not include metadata-incomplete tag v1.1.15." in result.issues


def test_malformed_release_candidate_series_fails(tmp_path):
    latest = {
        "schema_version": validator.RELEASE_INDEX_SCHEMA_VERSION,
        "stable": "v1.1.2",
        "release_candidate": "v1.2.0-rc.6",
        "release_candidate_series": {
            "tag_prefix": "v1.2.0-rc.",
            "minimum": "v1.3.0-rc.1",
        },
        "releases": ["v1.1.2", "v1.2.0-rc.6"],
    }
    _write_release_tree(tmp_path, latest=latest)

    result = _validate(tmp_path)

    assert result.status == validator.STATUS_INVALID
    assert "latest.json release_candidate_series.minimum must match tag_prefix." in result.issues


def test_notes_and_validation_must_be_lists(tmp_path):
    manifests = {
        "v1.1.2": {
            **_manifest("v1.1.2"),
            "notes": "not a list",
            "validation": "not a list",
        }
    }
    _write_release_tree(tmp_path, manifests=manifests)

    result = _validate(tmp_path)

    assert result.status == validator.STATUS_INVALID
    assert "v1.1.2.json notes must be a list." in result.issues
    assert "v1.1.2.json validation must be a list." in result.issues


def test_requires_firmware_must_be_null_or_artifact_object(tmp_path):
    manifests = {"v1.1.2": {**_manifest("v1.1.2"), "requires_firmware": {"note": "missing artifact"}}}
    _write_release_tree(tmp_path, manifests=manifests)

    result = _validate(tmp_path)

    assert result.status == validator.STATUS_INVALID
    assert "v1.1.2.json requires_firmware.artifact must be a non-empty string." in result.issues


def test_missing_non_rc_advertised_manifest_fails_but_missing_future_rc_warns(tmp_path):
    latest = {
        "schema_version": validator.RELEASE_INDEX_SCHEMA_VERSION,
        "stable": "v1.1.2",
        "release_candidate": "v1.2.0-rc.1",
        "releases": ["v1.1.2", "v1.1.3", "v1.2.0-rc.1"],
    }
    _write_release_tree(tmp_path, latest=latest)

    result = _validate(tmp_path)

    assert result.status == validator.STATUS_INVALID
    assert "Advertised stable release v1.1.3 is missing releases/v1.1.3.json." in result.issues
    assert "Advertised release candidate v1.2.0-rc.1 has no local manifest; assuming it lives on its tag." in result.warnings
