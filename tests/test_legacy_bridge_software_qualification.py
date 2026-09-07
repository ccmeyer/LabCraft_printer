"""Host-only qualification of immutable legacy updater discovery.

The test intentionally executes the updater bytes from each historical source
tag.  A future rc.12 tag is advertised through series discovery at the same
time, proving that pre-rc.11 clients stop at the exact rc.11 bridge.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
CURRENT_UPDATER = REPO_ROOT / "tools" / "update_and_restart.py"
LEGACY_SOURCES = ("v1.2.0-rc.6", "v1.2.0", "v1.3.0-rc.1")
BRIDGE_VERSION = "v1.3.0-rc.11"
FUTURE_VERSION = "v1.3.0-rc.12"
BRIDGE_COMPATIBILITY = {
    "schema_version": "labcraft_update_compatibility_v1",
    "direct_legacy_sources": list(LEGACY_SOURCES),
}


def _run(args: list[str], *, cwd: Path, timeout: float = 60.0) -> subprocess.CompletedProcess:
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        pytest.fail(
            f"Command failed ({result.returncode}): {' '.join(args)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _git(cwd: Path, *args: str) -> str:
    return _run(["git", *args], cwd=cwd).stdout.strip()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _manifest(
    version: str,
    *,
    schema_version: str,
    previous_version: str,
    compatibility: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": schema_version,
        "version": version,
        "tag": version,
        "channel": "release_candidate",
        "previous_version": previous_version,
        "rollback_version": "v1.2.0",
        "summary": f"Synthetic qualification release {version}.",
        "notes": ["Host-only legacy updater qualification."],
    }
    if compatibility is not None:
        payload["update_compatibility"] = compatibility
    return payload


def _latest() -> dict[str, object]:
    return {
        "schema_version": "labcraft_release_index_v1",
        "stable": "v1.2.0",
        "release_candidate": BRIDGE_VERSION,
        "release_candidate_series": {
            "tag_prefix": "v1.3.0-rc.",
            "minimum": "v1.3.0-rc.1",
        },
        "legacy_release_candidate_sources": list(LEGACY_SOURCES),
        "releases": [FUTURE_VERSION, BRIDGE_VERSION, "v1.2.0"],
    }


def _historical_updater(tag: str) -> str:
    return _run(
        ["git", "show", f"{tag}:tools/update_and_restart.py"],
        cwd=REPO_ROOT,
    ).stdout


def _build_world(tmp_path: Path, source_version: str) -> tuple[Path, str, bytes, bytes]:
    author = tmp_path / "author"
    origin = tmp_path / "origin.git"
    machine = tmp_path / "machine"
    author.mkdir()
    _git(author, "init", "-b", "main")
    _git(author, "config", "user.name", "LabCraft Qualification")
    _git(author, "config", "user.email", "qualification@labcraft.invalid")

    tools_dir = author / "tools"
    tools_dir.mkdir()
    (tools_dir / "update_and_restart.py").write_text(
        _historical_updater(source_version), encoding="utf-8"
    )
    (author / "FreeRTOS-interface").mkdir()
    (author / "FreeRTOS-interface" / "App.py").write_text(
        "raise SystemExit('qualification app must not launch')\n", encoding="utf-8"
    )
    (author / ".gitignore").write_text("/local/\n", encoding="utf-8")
    (author / "VERSION").write_text(source_version + "\n", encoding="utf-8")
    _git(author, "add", ".")
    _git(author, "commit", "-m", f"synthetic source {source_version}")

    _run(["git", "clone", "--bare", str(author), str(origin)], cwd=tmp_path)
    _run(["git", "clone", str(origin), str(machine)], cwd=tmp_path)

    (tools_dir / "update_and_restart.py").write_bytes(CURRENT_UPDATER.read_bytes())
    (author / "VERSION").write_text(BRIDGE_VERSION + "\n", encoding="utf-8")
    _write_json(author / "releases" / "latest.json", _latest())
    _write_json(
        author / "releases" / f"{BRIDGE_VERSION}.json",
        _manifest(
            BRIDGE_VERSION,
            schema_version="labcraft_release_v1",
            previous_version="v1.3.0-rc.10",
            compatibility=BRIDGE_COMPATIBILITY,
        ),
    )
    _git(author, "add", ".")
    _git(author, "commit", "-m", "synthetic rc11 bridge")
    bridge_commit = _git(author, "rev-parse", "HEAD")
    _git(author, "tag", "-a", BRIDGE_VERSION, "-m", "Synthetic rc11 bridge")

    (author / "VERSION").write_text(FUTURE_VERSION + "\n", encoding="utf-8")
    _write_json(
        author / "releases" / f"{FUTURE_VERSION}.json",
        _manifest(
            FUTURE_VERSION,
            schema_version="labcraft_release_v2",
            previous_version=BRIDGE_VERSION,
        ),
    )
    _git(author, "add", ".")
    _git(author, "commit", "-m", "synthetic post-bridge rc12")
    _git(author, "tag", "-a", FUTURE_VERSION, "-m", "Synthetic future rc12")
    _run(["git", "push", str(origin), "main", "--tags"], cwd=author)

    bundle = b"synthetic legacy offline bundle\x00\r\n"
    nested = b'{"bundle":"preserve-only"}\r\n'
    remnants = machine / "local" / "LabCraftUpdates"
    (remnants / "nested").mkdir(parents=True)
    (remnants / "legacy.bundle").write_bytes(bundle)
    (remnants / "nested" / "legacy.json").write_bytes(nested)
    return machine, bridge_commit, bundle, nested


@pytest.mark.parametrize("source_version", LEGACY_SOURCES)
def test_immutable_legacy_updater_selects_pinned_rc11_with_future_rc_present(
    tmp_path: Path,
    source_version: str,
) -> None:
    machine, bridge_commit, bundle, nested = _build_world(tmp_path, source_version)
    log_path = tmp_path / "evidence" / f"{source_version}.log"

    result = _run(
        [
            sys.executable,
            str(machine / "tools" / "update_and_restart.py"),
            "--repo-root",
            str(machine),
            "--release-channel",
            "release_candidate",
            "--no-relaunch",
            "--log-path",
            str(log_path),
        ],
        cwd=machine,
    )

    assert "Status: updated" in result.stdout
    assert _git(machine, "rev-parse", "HEAD") == bridge_commit
    assert (machine / "VERSION").read_text(encoding="utf-8").strip() == BRIDGE_VERSION
    assert (machine / "local" / "LabCraftUpdates" / "legacy.bundle").read_bytes() == bundle
    assert (
        machine / "local" / "LabCraftUpdates" / "nested" / "legacy.json"
    ).read_bytes() == nested
    assert _git(machine, "status", "--porcelain") == ""
    assert BRIDGE_VERSION in log_path.read_text(encoding="utf-8")
    assert FUTURE_VERSION not in result.stdout
