#!/usr/bin/env python3
"""Validate LabCraft release metadata before tagging or packaging."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence, TextIO


RELEASE_INDEX_SCHEMA_VERSION = "labcraft_release_index_v1"
RELEASE_MANIFEST_SCHEMA_VERSION_V1 = "labcraft_release_v1"
RELEASE_MANIFEST_SCHEMA_VERSION_V2 = "labcraft_release_v2"
RELEASE_MANIFEST_SCHEMA_VERSION = RELEASE_MANIFEST_SCHEMA_VERSION_V1
SUPPORTED_RELEASE_MANIFEST_SCHEMA_VERSIONS = frozenset(
    {RELEASE_MANIFEST_SCHEMA_VERSION_V1, RELEASE_MANIFEST_SCHEMA_VERSION_V2}
)
RELEASE_VERSION_RE = re.compile(r"v[0-9]+(?:\.[0-9]+){2}(?:-[A-Za-z0-9][A-Za-z0-9.-]*)?")
RELEASE_CANDIDATE_VERSION_RE = re.compile(r"v[0-9]+(?:\.[0-9]+){2}-rc\.[0-9]+")
RELEASE_CANDIDATE_PREFIX_RE = re.compile(r"v[0-9]+(?:\.[0-9]+){2}-rc\.")
RELEASE_CHANNELS = ("stable", "release_candidate")
KNOWN_METADATA_INCOMPLETE_RELEASES = ("v1.1.15",)
MACHINE_DATA_CONTRACT_NAME = "labcraft.machine_data_update.v1"
UPDATE_COMPATIBILITY_SCHEMA_VERSION = "labcraft_update_compatibility_v1"

STATUS_VALID = "valid"
STATUS_INVALID = "invalid"
STATUS_NOT_GIT_REPO = "not_git_repo"

EXIT_CODES = {
    STATUS_VALID: 0,
    STATUS_INVALID: 1,
    STATUS_NOT_GIT_REPO: 2,
}


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class ValidationConfig:
    repo_root: Path
    check_tags: bool = False


@dataclass(frozen=True)
class ValidationResult:
    status: str
    returncode: int
    repo_root: Path | None
    issues: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


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
    safe_directory = Path(repo_root).resolve().as_posix()
    return command_runner(["git", "-c", f"safe.directory={safe_directory}", *git_args], repo_root)


def _resolve_repo_root(requested_root: Path, command_runner: CommandRunner) -> tuple[Path | None, str | None]:
    result = _run_git(Path(requested_root).resolve(), ["rev-parse", "--show-toplevel"], command_runner)
    if result.returncode != 0 or not result.stdout.strip():
        detail = result.stderr.strip() or result.stdout.strip()
        suffix = f": {detail}" if detail else ""
        return None, f"Not a Git checkout{suffix}"
    return Path(result.stdout.strip()).resolve(), None


def _is_valid_release_version(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(text and "/" not in text and "\\" not in text and ".." not in text and RELEASE_VERSION_RE.fullmatch(text))


def _is_release_candidate_version(value: str) -> bool:
    return bool(RELEASE_CANDIDATE_VERSION_RE.fullmatch(value))


def _read_json_file(path: Path, *, label: str, issues: list[str]) -> dict | None:
    if not path.is_file():
        issues.append(f"{label} is missing: {path}")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        issues.append(f"{label} is not valid JSON: {exc}")
        return None
    except OSError as exc:
        issues.append(f"{label} could not be read: {exc}")
        return None
    if not isinstance(payload, dict):
        issues.append(f"{label} must contain a JSON object.")
        return None
    return payload


def _read_version(repo_root: Path, issues: list[str]) -> str:
    path = repo_root / "VERSION"
    if not path.is_file():
        issues.append("VERSION is missing.")
        return ""
    try:
        version = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        issues.append(f"VERSION could not be read: {exc}")
        return ""
    if not _is_valid_release_version(version):
        issues.append(f"VERSION is not a supported LabCraft version: {version!r}")
        return ""
    return version


def _validate_changelog(repo_root: Path, version: str, issues: list[str]) -> None:
    path = repo_root / "CHANGELOG.md"
    if not path.is_file():
        issues.append("CHANGELOG.md is missing.")
        return
    if not version:
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        issues.append(f"CHANGELOG.md could not be read: {exc}")
        return
    if not re.search(rf"^##\s+{re.escape(version)}(?:\s|$)", text, flags=re.MULTILINE):
        issues.append(f"CHANGELOG.md does not contain a release heading for {version}.")


def _validate_requires_firmware(value: object, *, manifest_name: str, issues: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        issues.append(f"{manifest_name} requires_firmware must be null or an object.")
        return
    artifact = value.get("artifact")
    if not isinstance(artifact, str) or not artifact.strip():
        issues.append(f"{manifest_name} requires_firmware.artifact must be a non-empty string.")


def _parse_update_compatibility(value: object) -> tuple[str, ...] | None:
    if value in (None, ""):
        return None
    if not isinstance(value, dict):
        raise ValueError("update_compatibility must be an object.")
    expected = {"schema_version", "direct_legacy_sources"}
    if set(value) != expected:
        raise ValueError("update_compatibility fields are invalid.")
    if value.get("schema_version") != UPDATE_COMPATIBILITY_SCHEMA_VERSION:
        raise ValueError("update_compatibility schema_version is unsupported.")
    raw_sources = value.get("direct_legacy_sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError("direct_legacy_sources must be a nonempty list.")
    sources: list[str] = []
    for raw_source in raw_sources:
        if not _is_valid_release_version(raw_source):
            raise ValueError(
                f"direct_legacy_sources contains an invalid version: {raw_source!r}."
            )
        source = str(raw_source).strip()
        if source != raw_source:
            raise ValueError(
                "direct_legacy_sources versions cannot contain surrounding whitespace."
            )
        if source in sources:
            raise ValueError(f"direct_legacy_sources lists {source} more than once.")
        sources.append(source)
    return tuple(sources)


def _validate_update_compatibility(
    value: object,
    *,
    manifest_name: str,
    issues: list[str],
) -> None:
    try:
        _parse_update_compatibility(value)
    except ValueError as exc:
        issues.append(f"{manifest_name} {exc}")


def _requires_machine_data_contract(version: str) -> bool:
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?", str(version or ""))
    if match is None:
        return False
    core = tuple(int(match.group(index)) for index in (1, 2, 3))
    if core != (1, 3, 0):
        return core > (1, 3, 0)
    rc_number = match.group(4)
    return rc_number is None or int(rc_number) >= 2


def _validate_machine_data_contract(
    value: object,
    *,
    version: str,
    manifest_name: str,
    issues: list[str],
) -> None:
    if value is None:
        if _requires_machine_data_contract(version):
            issues.append(f"{manifest_name} machine_data preservation contract is required.")
        return
    if not isinstance(value, dict):
        issues.append(f"{manifest_name} machine_data must be an object.")
        return
    expected = {"preservation_contract", "data_schema_version", "transition", "transition_id"}
    if set(value) != expected:
        issues.append(f"{manifest_name} machine_data fields are invalid.")
        return
    if value.get("preservation_contract") != MACHINE_DATA_CONTRACT_NAME:
        issues.append(f"{manifest_name} machine_data preservation_contract is unsupported.")
    schema_version = value.get("data_schema_version")
    if type(schema_version) is not int or schema_version <= 0:
        issues.append(f"{manifest_name} machine_data data_schema_version must be a positive integer.")
    transition = value.get("transition")
    transition_id = value.get("transition_id")
    if transition == "none":
        if transition_id is not None:
            issues.append(f"{manifest_name} machine_data transition_id must be null for transition none.")
    elif transition == "bootstrap_recovery":
        if not isinstance(transition_id, str) or not transition_id.strip():
            issues.append(f"{manifest_name} machine_data bootstrap_recovery requires transition_id.")
    else:
        issues.append(f"{manifest_name} machine_data transition is unsupported.")


def _validate_manifest(path: Path, *, issues: list[str]) -> dict | None:
    manifest_name = path.name
    payload = _read_json_file(path, label=f"Release manifest {manifest_name}", issues=issues)
    if payload is None:
        return None

    expected_version = path.stem
    if not _is_valid_release_version(expected_version):
        issues.append(f"{manifest_name} filename is not a supported LabCraft version.")

    schema_version = payload.get("schema_version")
    if schema_version not in SUPPORTED_RELEASE_MANIFEST_SCHEMA_VERSIONS:
        issues.append(f"{manifest_name} has unsupported schema_version.")

    version = payload.get("version")
    tag = payload.get("tag")
    if not _is_valid_release_version(version):
        issues.append(f"{manifest_name} version is not a supported LabCraft version.")
    elif version != expected_version:
        issues.append(f"{manifest_name} version does not match its filename.")

    if not _is_valid_release_version(tag):
        issues.append(f"{manifest_name} tag is not a supported LabCraft version.")
    elif tag != expected_version:
        issues.append(f"{manifest_name} tag does not match its filename.")

    channel = payload.get("channel")
    if channel not in RELEASE_CHANNELS:
        issues.append(f"{manifest_name} channel must be stable or release_candidate.")
    if schema_version == RELEASE_MANIFEST_SCHEMA_VERSION_V2 and channel != "release_candidate":
        issues.append(
            f"{manifest_name} schema v2 is reserved for release_candidate updates."
        )

    previous = payload.get("previous_version")
    if previous not in (None, "") and not _is_valid_release_version(previous):
        issues.append(f"{manifest_name} previous_version is not a supported LabCraft version.")

    rollback = payload.get("rollback_version")
    if rollback not in (None, "") and not _is_valid_release_version(rollback):
        issues.append(f"{manifest_name} rollback_version is not a supported LabCraft version.")

    if not isinstance(payload.get("notes"), list):
        issues.append(f"{manifest_name} notes must be a list.")

    if not isinstance(payload.get("validation"), list):
        issues.append(f"{manifest_name} validation must be a list.")

    _validate_requires_firmware(payload.get("requires_firmware"), manifest_name=manifest_name, issues=issues)
    _validate_machine_data_contract(
        payload.get("machine_data"),
        version=str(version or ""),
        manifest_name=manifest_name,
        issues=issues,
    )
    _validate_update_compatibility(
        payload.get("update_compatibility"),
        manifest_name=manifest_name,
        issues=issues,
    )
    return payload


def _release_candidate_number(version: str, *, prefix: str) -> int | None:
    if not version.startswith(prefix):
        return None
    suffix = version[len(prefix) :]
    if not suffix.isdigit():
        return None
    number = int(suffix)
    return number if number > 0 else None


def _validate_release_candidate_series(series: object, *, release_candidate: str, issues: list[str]) -> None:
    if series in (None, ""):
        return
    if not isinstance(series, dict):
        issues.append("latest.json release_candidate_series must be an object.")
        return

    prefix = series.get("tag_prefix")
    minimum = series.get("minimum")
    if not isinstance(prefix, str) or not RELEASE_CANDIDATE_PREFIX_RE.fullmatch(prefix.strip()):
        issues.append("latest.json release_candidate_series.tag_prefix must look like v1.2.0-rc.")
        return
    prefix = prefix.strip()

    if not _is_valid_release_version(minimum):
        issues.append("latest.json release_candidate_series.minimum is not a supported LabCraft version.")
        return
    minimum = str(minimum).strip()
    if _release_candidate_number(minimum, prefix=prefix) is None:
        issues.append("latest.json release_candidate_series.minimum must match tag_prefix.")

    if release_candidate and _release_candidate_number(release_candidate, prefix=prefix) is None:
        issues.append("latest.json release_candidate must match release_candidate_series.tag_prefix.")


def _validate_legacy_release_candidate_sources(
    value: object,
    *,
    release_candidate: str,
    manifests: dict[str, dict],
    issues: list[str],
) -> None:
    if value in (None, ""):
        return
    if not isinstance(value, list) or not value:
        issues.append(
            "latest.json legacy_release_candidate_sources must be a nonempty list when present."
        )
        return
    sources: list[str] = []
    for raw_source in value:
        if not _is_valid_release_version(raw_source):
            issues.append(
                "latest.json legacy_release_candidate_sources contains an invalid version: "
                f"{raw_source!r}"
            )
            continue
        source = str(raw_source).strip()
        if source != raw_source:
            issues.append(
                "latest.json legacy release source versions cannot contain surrounding whitespace."
            )
            continue
        if source in sources:
            issues.append(
                f"latest.json legacy_release_candidate_sources lists {source} more than once."
            )
            continue
        sources.append(source)
    if not release_candidate:
        issues.append(
            "latest.json legacy_release_candidate_sources requires an exact release_candidate pointer."
        )
        return
    manifest = manifests.get(release_candidate)
    if manifest is None:
        issues.append(
            "latest.json legacy release_candidate manifest must be present for compatibility validation."
        )
        return
    try:
        declared = _parse_update_compatibility(manifest.get("update_compatibility"))
    except ValueError:
        declared = None
    if declared is None:
        issues.append(
            f"{release_candidate}.json must declare update_compatibility for the pinned legacy pointer."
        )
        return
    missing = sorted(set(sources) - set(declared))
    if missing:
        issues.append(
            f"{release_candidate}.json direct_legacy_sources does not cover the pinned legacy cohorts: "
            + ", ".join(missing)
        )
    unexpected = sorted(set(declared) - set(sources))
    if unexpected:
        issues.append(
            f"{release_candidate}.json direct_legacy_sources authorizes cohorts absent from "
            "latest.json legacy_release_candidate_sources: " + ", ".join(unexpected)
        )


def _validate_latest_index(
    latest: dict | None,
    *,
    current_version: str,
    manifests: dict[str, dict],
    issues: list[str],
    warnings: list[str],
) -> set[str]:
    if latest is None:
        return set()

    if latest.get("schema_version") != RELEASE_INDEX_SCHEMA_VERSION:
        issues.append("latest.json has unsupported schema_version.")

    stable = latest.get("stable")
    if not _is_valid_release_version(stable):
        issues.append("latest.json stable is not a supported LabCraft version.")
        stable = ""
    else:
        stable = str(stable).strip()

    release_candidate_raw = latest.get("release_candidate")
    release_candidate = ""
    if release_candidate_raw not in (None, ""):
        if not _is_valid_release_version(release_candidate_raw):
            issues.append("latest.json release_candidate is not a supported LabCraft version.")
        else:
            release_candidate = str(release_candidate_raw).strip()

    releases = latest.get("releases")
    advertised: list[str] = []
    if not isinstance(releases, list):
        issues.append("latest.json releases must be a list.")
    else:
        seen: set[str] = set()
        for raw_version in releases:
            if not _is_valid_release_version(raw_version):
                issues.append(f"latest.json releases contains an invalid version: {raw_version!r}")
                continue
            version = str(raw_version).strip()
            if version in seen:
                issues.append(f"latest.json releases lists {version} more than once.")
            seen.add(version)
            advertised.append(version)
            if version in KNOWN_METADATA_INCOMPLETE_RELEASES:
                issues.append(f"latest.json releases must not include metadata-incomplete tag {version}.")

        if stable and stable not in advertised:
            issues.append("latest.json stable must be included in releases.")
        if release_candidate and release_candidate not in advertised:
            issues.append("latest.json release_candidate must be included in releases.")

    _validate_release_candidate_series(
        latest.get("release_candidate_series"),
        release_candidate=release_candidate,
        issues=issues,
    )
    _validate_legacy_release_candidate_sources(
        latest.get("legacy_release_candidate_sources"),
        release_candidate=release_candidate,
        manifests=manifests,
        issues=issues,
    )

    for version in advertised:
        if version in manifests:
            continue
        if version == current_version:
            issues.append(f"Current VERSION {version} is listed but releases/{version}.json is missing.")
            continue
        if _is_release_candidate_version(version):
            warnings.append(f"Advertised release candidate {version} has no local manifest; assuming it lives on its tag.")
            continue
        issues.append(f"Advertised stable release {version} is missing releases/{version}.json.")

    return set(advertised)


def _collect_referenced_versions(manifests: dict[str, dict], advertised: set[str], current_version: str) -> set[str]:
    versions = set(advertised)
    if current_version:
        versions.add(current_version)
    for manifest in manifests.values():
        for key in ("previous_version", "rollback_version"):
            value = manifest.get(key)
            if isinstance(value, str) and value.strip():
                versions.add(value.strip())
    return versions


def _check_git_tags(
    repo_root: Path,
    versions: set[str],
    *,
    command_runner: CommandRunner,
    issues: list[str],
) -> None:
    for version in sorted(versions):
        result = _run_git(repo_root, ["rev-parse", f"{version}^{{commit}}"], command_runner)
        if result.returncode != 0 or not result.stdout.strip():
            issues.append(f"Git tag {version} could not be resolved.")


def validate_release_metadata(
    config: ValidationConfig,
    *,
    command_runner: CommandRunner = default_command_runner,
) -> ValidationResult:
    repo_root, repo_error = _resolve_repo_root(config.repo_root, command_runner)
    if repo_error is not None or repo_root is None:
        return ValidationResult(
            status=STATUS_NOT_GIT_REPO,
            returncode=EXIT_CODES[STATUS_NOT_GIT_REPO],
            repo_root=None,
            issues=(repo_error or "Not a Git checkout.",),
        )

    issues: list[str] = []
    warnings: list[str] = []

    current_version = _read_version(repo_root, issues)
    _validate_changelog(repo_root, current_version, issues)

    releases_dir = repo_root / "releases"
    if not releases_dir.is_dir():
        issues.append("releases directory is missing.")
        manifest_paths: list[Path] = []
    else:
        manifest_paths = sorted(path for path in releases_dir.glob("v*.json") if path.name != "latest.json")

    manifests: dict[str, dict] = {}
    for path in manifest_paths:
        manifest = _validate_manifest(path, issues=issues)
        if manifest is not None and _is_valid_release_version(path.stem):
            manifests[path.stem] = manifest

    if current_version and current_version not in manifests:
        issues.append(f"VERSION {current_version} does not have a matching releases/{current_version}.json.")

    latest = _read_json_file(releases_dir / "latest.json", label="latest.json", issues=issues)
    advertised = _validate_latest_index(
        latest,
        current_version=current_version,
        manifests=manifests,
        issues=issues,
        warnings=warnings,
    )

    if config.check_tags:
        _check_git_tags(
            repo_root,
            _collect_referenced_versions(manifests, advertised, current_version),
            command_runner=command_runner,
            issues=issues,
        )

    status = STATUS_INVALID if issues else STATUS_VALID
    return ValidationResult(
        status=status,
        returncode=EXIT_CODES[status],
        repo_root=repo_root,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate LabCraft release metadata.")
    parser.add_argument("--repo-root", type=Path, default=default_repo_root(), help="Path inside the Git checkout.")
    parser.add_argument(
        "--check-tags",
        action="store_true",
        help="Verify advertised and referenced release tags with git rev-parse.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    command_runner: CommandRunner = default_command_runner,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    args = build_arg_parser().parse_args(argv)
    result = validate_release_metadata(
        ValidationConfig(repo_root=Path(args.repo_root), check_tags=bool(args.check_tags)),
        command_runner=command_runner,
    )

    for warning in result.warnings:
        err.write(f"WARNING: {warning}\n")
    for issue in result.issues:
        err.write(f"ERROR: {issue}\n")

    if result.status == STATUS_VALID:
        out.write("Release metadata validation passed.\n")
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
