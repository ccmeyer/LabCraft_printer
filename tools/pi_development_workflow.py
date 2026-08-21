"""Windows-to-Pi development workflow orchestration.

Slice 1 is deliberately read-only: it collects local and Pi state, classifies
readiness, and writes local evidence. Later slices extend the same interface.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import shutil
import subprocess
import sys
from typing import Any, Mapping, Sequence
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_NAME = "labcraft.pi_development_status"
SCHEMA_VERSION = 1
DEFAULT_PRODUCTION_REPO = "/home/labcraft/LabCraft_printer"
DEFAULT_DEVELOPMENT_REPO = "/home/labcraft/LabCraft_printer-dev"
DEFAULT_SHARED_PYTHON = "/home/labcraft/LabCraft_printer/env/bin/python"
DEFAULT_DEVELOPMENT_PARENT = (
    "/home/labcraft/.local/share/LabCraft/LabCraft Printer/development"
)
DEFAULT_WORKFLOW_CONFIG = "/home/labcraft/.config/LabCraft/development_workflow.json"
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "verification_reports" / "development-workflow" / "status"
)


class WorkflowError(RuntimeError):
    """Raised when status evidence cannot be collected safely."""


def validate_remote_paths(
    *,
    pi_user: str,
    production_repo: str,
    development_repo: str,
    shared_python: str,
    development_machine_data_root: str | None,
    workflow_config: str = DEFAULT_WORKFLOW_CONFIG,
) -> None:
    values = {
        "Production repository": production_repo,
        "Development repository": development_repo,
        "Shared Python": shared_python,
        "Workflow configuration": workflow_config,
    }
    if development_machine_data_root:
        values["Development machine-data root"] = development_machine_data_root
    paths: dict[str, PurePosixPath] = {}
    for label, value in values.items():
        path = PurePosixPath(value)
        if not path.is_absolute():
            raise WorkflowError(f"{label} must be an absolute Pi path: {value}")
        if ".." in path.parts:
            raise WorkflowError(f"{label} cannot contain '..': {value}")
        paths[label] = path
    production = paths["Production repository"]
    development = paths["Development repository"]
    unsafe_roots = {PurePosixPath("/"), PurePosixPath(f"/home/{pi_user}")}
    if production in unsafe_roots or development in unsafe_roots:
        raise WorkflowError("Code worktree paths cannot be a filesystem or user-home root.")
    if (
        production == development
        or production in development.parents
        or development in production.parents
    ):
        raise WorkflowError("Production and development worktree paths must be disjoint.")
    machine_data = paths.get("Development machine-data root")
    if machine_data is not None and (
        machine_data in {production, development}
        or production in machine_data.parents
        or development in machine_data.parents
        or machine_data in production.parents
        or machine_data in development.parents
    ):
        raise WorkflowError("Development machine data must be outside both worktrees.")
    config_path = paths["Workflow configuration"]
    if (
        config_path in {production, development}
        or production in config_path.parents
        or development in config_path.parents
        or config_path in production.parents
        or config_path in development.parents
    ):
        raise WorkflowError("Workflow configuration must be outside both worktrees.")


def _run(
    arguments: Sequence[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
    allowed_exit_codes: Sequence[int] = (0,),
    timeout_seconds: int | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            list(arguments),
            cwd=cwd,
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkflowError(
            f"Command timed out after {timeout_seconds} seconds: {arguments[0]}"
        ) from exc
    if completed.returncode not in allowed_exit_codes:
        detail = (completed.stderr or completed.stdout).strip()
        raise WorkflowError(
            f"Command failed ({completed.returncode}): {arguments[0]}"
            + (f": {detail}" if detail else "")
        )
    return completed


def _git(
    *arguments: str,
    cwd: Path = REPO_ROOT,
    allowed_exit_codes: Sequence[int] = (0,),
) -> subprocess.CompletedProcess[str]:
    return _run(
        ["git", *arguments], cwd=cwd, allowed_exit_codes=allowed_exit_codes
    )


def collect_local_state(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    root = Path(
        _git("rev-parse", "--show-toplevel", cwd=repo_root).stdout.strip()
    ).resolve()
    head = _git("rev-parse", "HEAD", cwd=root).stdout.strip()
    branch = _git("branch", "--show-current", cwd=root).stdout.strip()
    status = _git(
        "status", "--porcelain=v1", "--untracked-files=all", cwd=root
    ).stdout.splitlines()
    upstream_result = _git(
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
        cwd=root,
        allowed_exit_codes=(0, 128),
    )
    upstream = (
        upstream_result.stdout.strip() if upstream_result.returncode == 0 else ""
    )
    upstream_remote = None
    upstream_merge_ref = None
    if upstream and branch:
        remote_result = _git(
            "config",
            "--get",
            f"branch.{branch}.remote",
            cwd=root,
            allowed_exit_codes=(0, 1),
        )
        merge_result = _git(
            "config",
            "--get",
            f"branch.{branch}.merge",
            cwd=root,
            allowed_exit_codes=(0, 1),
        )
        upstream_remote = remote_result.stdout.strip() or None
        upstream_merge_ref = merge_result.stdout.strip() or None
    ahead = None
    behind = None
    reachable = False
    if upstream:
        counts = _git(
            "rev-list", "--left-right", "--count", f"HEAD...{upstream}", cwd=root
        ).stdout.split()
        if len(counts) != 2:
            raise WorkflowError("Git returned invalid ahead/behind counts.")
        ahead, behind = (int(counts[0]), int(counts[1]))
        reachable = (
            _git(
                "merge-base",
                "--is-ancestor",
                "HEAD",
                upstream,
                cwd=root,
                allowed_exit_codes=(0, 1),
            ).returncode
            == 0
        )
    origin_result = _git(
        "remote", "get-url", "origin", cwd=root, allowed_exit_codes=(0, 2)
    )
    return {
        "repo_root": str(root),
        "head": head,
        "short_head": head[:12],
        "branch": branch or None,
        "detached": not bool(branch),
        "clean": not status,
        "status": status,
        "upstream": upstream or None,
        "upstream_remote": upstream_remote,
        "upstream_merge_ref": upstream_merge_ref,
        "ahead": ahead,
        "behind": behind,
        "head_reachable_from_upstream": reachable,
        "origin_url": (
            origin_result.stdout.strip() if origin_result.returncode == 0 else None
        ),
    }


REMOTE_COLLECTOR = r'''
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID


def run(arguments, *, allowed=(0,)):
    completed = subprocess.run(
        list(arguments), capture_output=True, text=True, check=False
    )
    if completed.returncode not in allowed:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {arguments[0]}"
            + (f": {detail}" if detail else "")
        )
    return completed


def git(path, *arguments, allowed=(0,)):
    return run(["git", "-C", str(path), *arguments], allowed=allowed)


def resolved(value):
    return Path(value).expanduser().resolve(strict=False)


def beneath_or_equal(path, root):
    return path == root or root in path.parents


def parse_worktrees(text):
    records = []
    current = None
    for line in text.splitlines():
        if line.startswith("worktree "):
            if current:
                records.append(current)
            current = {
                "path": line[len("worktree "):],
                "head": None,
                "branch": None,
                "detached": False,
                "prunable": False,
            }
        elif current is None:
            continue
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch refs/heads/"):]
        elif line == "detached":
            current["detached"] = True
        elif line.startswith("prunable"):
            current["prunable"] = True
    if current:
        records.append(current)
    return records


def inspect_git_worktree(path):
    candidate = resolved(path)
    if not candidate.is_dir():
        return {"valid": False, "path": str(candidate), "error": "missing"}
    try:
        root = resolved(git(candidate, "rev-parse", "--show-toplevel").stdout.strip())
        head = git(candidate, "rev-parse", "HEAD").stdout.strip()
        branch = git(candidate, "branch", "--show-current").stdout.strip()
        status = git(
            candidate, "status", "--porcelain=v1", "--untracked-files=all"
        ).stdout.splitlines()
    except Exception as exc:
        return {"valid": False, "path": str(candidate), "error": str(exc)}
    return {
        "valid": root == candidate,
        "path": str(candidate),
        "head": head,
        "branch": branch or None,
        "detached": not bool(branch),
        "clean": not status,
        "status": status,
        "error": None if root == candidate else "top-level path differs",
    }


def inspect_store(root, production_repo, development_repo):
    requested = Path(root).expanduser()
    path = resolved(requested)
    result = {
        "path": str(path),
        "valid": False,
        "marker_valid": False,
        "active_pointer_valid": False,
        "machine_identity_valid": False,
        "store_id": None,
        "machine_id": None,
        "errors": [],
    }
    if not requested.is_dir():
        result["errors"].append("development store directory is missing")
        return result
    if requested.is_symlink():
        result["errors"].append("development store cannot be a symlink")
        return result
    marker_path = path / "development_store.json"
    pointer_path = path / "active_machine.json"
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        expected = {
            "schema_name", "schema_version", "development_root",
            "source_machine_data_root", "store_id", "created_at_utc",
            "created_by", "creation_commit", "source_tree_fingerprint",
            "source_active_pointer_sha256",
        }
        if not isinstance(marker, dict) or set(marker) != expected:
            raise ValueError("marker fields differ from schema")
        if marker["schema_name"] != "labcraft.development_machine_data_store":
            raise ValueError("marker schema name is invalid")
        if marker["schema_version"] != 1:
            raise ValueError("marker schema version is invalid")
        if resolved(marker["development_root"]) != path:
            raise ValueError("marker development root differs")
        source = resolved(marker["source_machine_data_root"])
        if source == path or beneath_or_equal(source, path) or beneath_or_equal(path, source):
            raise ValueError("source and development roots are not disjoint")
        UUID(str(marker["store_id"]))
        for name in (
            "created_at_utc", "created_by", "creation_commit",
            "source_tree_fingerprint", "source_active_pointer_sha256",
        ):
            if not isinstance(marker[name], str) or not marker[name].strip():
                raise ValueError(f"marker {name} is invalid")
        for name in ("source_tree_fingerprint", "source_active_pointer_sha256"):
            value = marker[name]
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise ValueError(f"marker {name} is not a SHA-256 value")
        prod = resolved(production_repo)
        dev = resolved(development_repo)
        if beneath_or_equal(path, prod) or beneath_or_equal(path, dev):
            raise ValueError("development store is inside a code worktree")
        result["store_id"] = str(UUID(str(marker["store_id"])))
        result["source_machine_data_root"] = str(source)
        result["marker_valid"] = True
    except Exception as exc:
        result["errors"].append(f"marker: {exc}")
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        if not isinstance(pointer, dict):
            raise ValueError("active pointer is not an object")
        if pointer.get("schema_name") != "labcraft.active_machine":
            raise ValueError("active pointer schema name is invalid")
        if pointer.get("schema_version") != 2:
            raise ValueError("active pointer is not authorized schema version 2")
        machine_id = pointer.get("machine_id")
        if not isinstance(machine_id, str) or not machine_id.strip():
            raise ValueError("machine_id is invalid")
        machine_uuid = str(UUID(str(pointer.get("machine_uuid"))))
        UUID(str(pointer.get("activation_id")))
        UUID(str(pointer.get("migration_id")))
        receipt_digest = pointer.get("activation_receipt_sha256")
        if not isinstance(receipt_digest, str) or len(receipt_digest) != 64 or any(
            ch not in "0123456789abcdef" for ch in receipt_digest
        ):
            raise ValueError("activation receipt digest is invalid")
        result["machine_id"] = machine_id
        result["machine_uuid"] = machine_uuid
        result["active_pointer_valid"] = True
    except Exception as exc:
        result["errors"].append(f"active pointer: {exc}")
    if result["active_pointer_valid"]:
        try:
            identity_path = (
                path / "machines" / result["machine_uuid"]
                / "metadata" / "machine_identity.json"
            )
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
            if not isinstance(identity, dict):
                raise ValueError("machine identity is not an object")
            if identity.get("schema_name") != "labcraft.machine_identity":
                raise ValueError("machine identity schema name is invalid")
            if identity.get("schema_version") != 1:
                raise ValueError("machine identity schema version is invalid")
            if identity.get("machine_id") != result["machine_id"]:
                raise ValueError("machine identity ID differs from active pointer")
            if str(UUID(str(identity.get("machine_uuid")))) != result["machine_uuid"]:
                raise ValueError("machine identity UUID differs from active pointer")
            if not isinstance(identity.get("assigned_at"), str) or not identity["assigned_at"].strip():
                raise ValueError("machine identity assignment time is invalid")
            if not isinstance(identity.get("notes", ""), str):
                raise ValueError("machine identity notes are invalid")
            result["machine_identity_valid"] = True
        except Exception as exc:
            result["errors"].append(f"machine identity: {exc}")
    result["valid"] = all(
        result[name] for name in (
            "marker_valid", "active_pointer_valid", "machine_identity_valid"
        )
    )
    return result


def inspect_workflow_config(path, production_repo, development_repo, shared_python):
    requested = Path(path).expanduser()
    target = resolved(requested)
    result = {"path": str(target), "exists": target.is_file(), "valid": False, "errors": []}
    if not requested.exists():
        return result
    if not requested.is_file() or requested.is_symlink():
        result["errors"].append("workflow configuration is not a regular file")
        return result
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        expected = {
            "schema_name", "schema_version", "production_repo",
            "development_repo", "shared_python", "development_machine_data_root",
            "development_store_id", "machine_id", "dependency_manifest_sha256",
            "configured_at_utc", "configured_by", "creation_commit",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ValueError("workflow configuration fields differ from schema")
        if payload["schema_name"] != "labcraft.pi_development_workflow_config":
            raise ValueError("workflow configuration schema name is invalid")
        if payload["schema_version"] != 1:
            raise ValueError("workflow configuration schema version is invalid")
        bindings = {
            "production_repo": production_repo,
            "development_repo": development_repo,
            "shared_python": shared_python,
        }
        for name, expected_path in bindings.items():
            if resolved(payload[name]) != resolved(expected_path):
                raise ValueError(f"configured {name} binding differs")
        UUID(str(payload["development_store_id"]))
        if not isinstance(payload["machine_id"], str) or not payload["machine_id"].strip():
            raise ValueError("configured machine ID is invalid")
        digest = payload["dependency_manifest_sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or any(
            ch not in "0123456789abcdef" for ch in digest
        ):
            raise ValueError("configured dependency fingerprint is invalid")
        for name in ("configured_at_utc", "configured_by", "creation_commit"):
            if not isinstance(payload[name], str) or not payload[name].strip():
                raise ValueError(f"configured {name} is invalid")
        result["valid"] = True
        result["payload"] = payload
    except Exception as exc:
        result["errors"].append(str(exc))
    return result


def collect_processes():
    needles = (
        "FreeRTOS-interface/App.py",
        "tools/run_development_app.py",
        "tools/update_window.py",
        "tools/update_and_restart.py",
        "firmware/hil/flash_and_test.sh",
        "dfu_update.py",
    )
    matches = []
    for entry in Path("/proc").glob("[0-9]*"):
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", errors="replace"
            ).strip()
        except (OSError, ValueError):
            continue
        if command and any(needle in command for needle in needles):
            matches.append({"pid": int(entry.name), "command": command})
    return sorted(matches, key=lambda value: value["pid"])


def main():
    config = json.loads(base64.urlsafe_b64decode(sys.argv[1]).decode("utf-8"))
    production_path = resolved(config["production_repo"])
    development_path = resolved(config["development_repo"])
    production = inspect_git_worktree(production_path)
    if production.get("valid"):
        worktree_text = git(
            production_path, "worktree", "list", "--porcelain"
        ).stdout
        worktrees = parse_worktrees(worktree_text)
    else:
        worktrees = []

    prod_registered = next(
        (item for item in worktrees if resolved(item["path"]) == production_path),
        None,
    )
    if production.get("valid"):
        production["registered"] = prod_registered is not None

    filesystem_root = Path(development_path.anchor).resolve(strict=False)
    home = Path.home().resolve(strict=False)
    unsafe_dev = (
        not development_path.is_absolute()
        or development_path in {filesystem_root, home, production_path}
        or beneath_or_equal(development_path, production_path)
        or beneath_or_equal(production_path, development_path)
        or development_path.is_symlink()
    )
    dev_registered = next(
        (item for item in worktrees if resolved(item["path"]) == development_path),
        None,
    )
    if unsafe_dev:
        development = {
            "path": str(development_path), "state": "invalid",
            "registered": dev_registered is not None,
            "error": "development worktree path is unsafe",
        }
    elif dev_registered is not None:
        inspected = inspect_git_worktree(development_path)
        if not inspected.get("valid"):
            state = "invalid"
        else:
            state = "registered_clean" if inspected["clean"] else "registered_dirty"
        development = {**inspected, "state": state, "registered": True}
    elif development_path.exists():
        development = {
            "path": str(development_path), "state": "unregistered_path",
            "registered": False, "error": "target exists but is not a registered worktree",
        }
    else:
        development = {
            "path": str(development_path), "state": "absent",
            "registered": False, "error": None,
        }

    other_worktrees = [
        item for item in worktrees
        if resolved(item["path"]) not in {production_path, development_path}
    ]

    python_path = resolved(config["shared_python"])
    interpreter = {
        "path": str(python_path),
        "exists": python_path.is_file(),
        "executable": python_path.is_file() and os.access(python_path, os.X_OK),
        "version": None,
    }
    if interpreter["executable"]:
        version = run([str(python_path), "--version"], allowed=(0,))
        interpreter["version"] = (version.stdout or version.stderr).strip()

    explicit_store = config.get("development_machine_data_root")
    workflow_config = inspect_workflow_config(
        config["workflow_config"], production_path, development_path, python_path
    )
    if explicit_store:
        candidates = [resolved(explicit_store)]
        selection_source = "explicit"
    elif workflow_config.get("valid"):
        candidates = [
            resolved(workflow_config["payload"]["development_machine_data_root"])
        ]
        selection_source = "configured"
    elif workflow_config.get("exists"):
        candidates = []
        selection_source = "configured_invalid"
    else:
        parent = resolved(config["development_machine_data_parent"])
        candidates = sorted(
            marker.parent.resolve(strict=False)
            for marker in parent.glob("*/development_store.json")
            if marker.is_file()
        ) if parent.is_dir() else []
        selection_source = (
            "single_candidate" if len(candidates) == 1
            else "none" if not candidates
            else "ambiguous"
        )
    selected_store = (
        inspect_store(candidates[0], production_path, development_path)
        if len(candidates) == 1 else None
    )
    if workflow_config.get("valid") and selected_store and selected_store.get("valid"):
        configured_payload = workflow_config["payload"]
        if (
            configured_payload["development_store_id"] != selected_store["store_id"]
            or configured_payload["machine_id"] != selected_store["machine_id"]
        ):
            workflow_config["valid"] = False
            workflow_config["errors"].append(
                "configured development store identity differs from current evidence"
            )

    payload = {
        "hostname": run(["hostname"]).stdout.strip(),
        "production_worktree": production,
        "development_worktree": development,
        "other_worktrees": other_worktrees,
        "shared_python": interpreter,
        "processes": collect_processes(),
        "development_machine_data": {
            "selection_source": selection_source,
            "candidate_paths": [str(path) for path in candidates],
            "selected": selected_store,
        },
        "workflow_config": workflow_config,
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


try:
    main()
except Exception as exc:
    print(f"Remote collection failed: {exc}", file=sys.stderr)
    raise SystemExit(1)
'''


REMOTE_SYNC = r'''
from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
import sys


def run(arguments, *, allowed=(0,)):
    completed = subprocess.run(
        list(arguments), capture_output=True, text=True, check=False
    )
    if completed.returncode not in allowed:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(arguments[:3])}"
            + (f": {detail}" if detail else "")
        )
    return completed


def git(path, *arguments, allowed=(0,)):
    return run(["git", "-C", str(path), *arguments], allowed=allowed)


def resolved(value):
    return Path(value).expanduser().resolve(strict=False)


def parse_worktrees(text):
    paths = []
    for line in text.splitlines():
        if line.startswith("worktree "):
            paths.append(str(resolved(line[len("worktree "):])) )
    return paths


def relevant_processes():
    needles = (
        "FreeRTOS-interface/App.py", "tools/run_development_app.py",
        "tools/update_window.py", "tools/update_and_restart.py",
        "firmware/hil/flash_and_test.sh", "dfu_update.py",
    )
    matches = []
    for entry in Path("/proc").glob("[0-9]*"):
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", errors="replace"
            ).strip()
        except (OSError, ValueError):
            continue
        if command and any(needle in command for needle in needles):
            matches.append({"pid": int(entry.name), "command": command})
    return matches


def main():
    config = json.loads(base64.urlsafe_b64decode(sys.argv[1]).decode("utf-8"))
    production = resolved(config["production_repo"])
    development = resolved(config["development_repo"])
    expected_commit = config["expected_commit"]
    expected_production_head = config["expected_production_head"]
    expected_production_branch = config["expected_production_branch"]
    remote_name = config["remote_name"]
    remote_ref = config["remote_ref"]
    tracking_ref = config["tracking_ref"]

    if not production.is_dir():
        raise RuntimeError("Protected production worktree is missing.")
    if git(production, "rev-parse", "HEAD").stdout.strip() != expected_production_head:
        raise RuntimeError("Protected production HEAD changed after preflight.")
    branch = git(production, "branch", "--show-current").stdout.strip()
    if branch != expected_production_branch:
        raise RuntimeError("Protected production branch changed after preflight.")
    if git(
        production, "status", "--porcelain=v1", "--untracked-files=all"
    ).stdout.splitlines():
        raise RuntimeError("Protected production worktree became dirty.")
    if relevant_processes():
        raise RuntimeError("A LabCraft application or hardware workflow is running.")
    actual_url = git(production, "remote", "get-url", remote_name).stdout.strip()
    if actual_url.rstrip("/") != config["expected_remote_url"].rstrip("/"):
        raise RuntimeError("Pi and Windows remote repository identities differ.")

    registered_before = parse_worktrees(
        git(production, "worktree", "list", "--porcelain").stdout
    )
    development_text = str(development)
    registered = development_text in registered_before
    if registered:
        if not development.is_dir():
            raise RuntimeError("Development worktree registration is stale.")
        if git(
            development, "status", "--porcelain=v1", "--untracked-files=all"
        ).stdout.splitlines():
            raise RuntimeError("Development worktree is dirty.")
    elif development.exists():
        raise RuntimeError("Development target exists but is not registered.")

    fetch_spec = f"{remote_ref}:{tracking_ref}"
    git(production, "fetch", "--no-tags", remote_name, fetch_spec)
    git(production, "cat-file", "-e", f"{expected_commit}^{{commit}}")
    if git(
        production,
        "merge-base",
        "--is-ancestor",
        expected_commit,
        tracking_ref,
        allowed=(0, 1),
    ).returncode != 0:
        raise RuntimeError("Requested commit is not reachable from the fetched remote ref.")

    action = "unchanged"
    if registered:
        current = git(development, "rev-parse", "HEAD").stdout.strip()
        if current != expected_commit:
            git(development, "switch", "--detach", expected_commit)
            action = "updated"
    else:
        git(production, "worktree", "add", "--detach", str(development), expected_commit)
        action = "created"

    final_head = git(development, "rev-parse", "HEAD").stdout.strip()
    final_branch = git(development, "branch", "--show-current").stdout.strip()
    final_status = git(
        development, "status", "--porcelain=v1", "--untracked-files=all"
    ).stdout.splitlines()
    if final_head != expected_commit or final_branch or final_status:
        raise RuntimeError("Development worktree postcondition failed.")
    if git(production, "rev-parse", "HEAD").stdout.strip() != expected_production_head:
        raise RuntimeError("Protected production HEAD changed during synchronization.")
    if git(production, "branch", "--show-current").stdout.strip() != expected_production_branch:
        raise RuntimeError("Protected production branch changed during synchronization.")
    if git(
        production, "status", "--porcelain=v1", "--untracked-files=all"
    ).stdout.splitlines():
        raise RuntimeError("Protected production worktree changed during synchronization.")
    registered_after = parse_worktrees(
        git(production, "worktree", "list", "--porcelain").stdout
    )
    expected_paths = sorted(set(registered_before) | {development_text})
    if sorted(registered_after) != expected_paths:
        raise RuntimeError("Unexpected worktree registration changed during synchronization.")
    print(json.dumps({
        "action": action,
        "commit": final_head,
        "development_repo": development_text,
        "remote_name": remote_name,
        "remote_ref": remote_ref,
        "tracking_ref": tracking_ref,
        "registered_before": registered,
    }, sort_keys=True, separators=(",", ":")))


try:
    main()
except Exception as exc:
    print(f"Remote synchronization failed: {exc}", file=sys.stderr)
    raise SystemExit(1)
'''


REMOTE_RUNTIME_CONFIG = r'''
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from uuid import UUID, uuid4


CONFIG_SCHEMA = "labcraft.pi_development_workflow_config"
CONFIG_VERSION = 1


def run(arguments, *, allowed=(0,)):
    completed = subprocess.run(
        list(arguments), capture_output=True, text=True, check=False
    )
    if completed.returncode not in allowed:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(arguments[:3])}"
            + (f": {detail}" if detail else "")
        )
    return completed


def git(path, *arguments, allowed=(0,)):
    return run(["git", "-C", str(path), *arguments], allowed=allowed)


def resolved(value):
    return Path(value).expanduser().resolve(strict=False)


def relevant_processes():
    needles = (
        "FreeRTOS-interface/App.py", "tools/run_development_app.py",
        "tools/update_window.py", "tools/update_and_restart.py",
        "firmware/hil/flash_and_test.sh", "dfu_update.py",
    )
    matches = []
    for entry in Path("/proc").glob("[0-9]*"):
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", errors="replace"
            ).strip()
        except (OSError, ValueError):
            continue
        if command and any(needle in command for needle in needles):
            matches.append({"pid": int(entry.name), "command": command})
    return matches


def dependency_inventory(repo):
    tracked = git(repo, "ls-files", "--").stdout.splitlines()
    names = {
        "pyproject.toml", "poetry.lock", "Pipfile", "Pipfile.lock",
        "setup.py", "setup.cfg",
    }
    selected = sorted(
        name for name in tracked
        if "/" not in name and (
            name in names or (name.startswith("requirements") and name.endswith(".txt"))
        )
    )
    if not selected:
        raise RuntimeError("No tracked root dependency declaration was found.")
    inventory = {}
    for relative in selected:
        data = (repo / relative).read_bytes()
        inventory[relative] = {
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    canonical = json.dumps(
        inventory, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return inventory, hashlib.sha256(canonical).hexdigest()


def validate_store(root, production_repo, development_repo):
    requested = Path(root).expanduser()
    reject_link_ancestors(requested)
    path = resolved(requested)
    if not requested.is_dir() or requested.is_symlink():
        raise RuntimeError("Development machine-data root is not a regular directory.")
    if (
        production_repo == path or development_repo == path
        or production_repo in path.parents or development_repo in path.parents
        or path in production_repo.parents or path in development_repo.parents
    ):
        raise RuntimeError("Development machine data is inside a code worktree.")
    marker = json.loads((path / "development_store.json").read_text(encoding="utf-8"))
    expected = {
        "schema_name", "schema_version", "development_root",
        "source_machine_data_root", "store_id", "created_at_utc", "created_by",
        "creation_commit", "source_tree_fingerprint", "source_active_pointer_sha256",
    }
    if not isinstance(marker, dict) or set(marker) != expected:
        raise RuntimeError("Development-store marker fields differ from schema.")
    if marker["schema_name"] != "labcraft.development_machine_data_store" or marker["schema_version"] != 1:
        raise RuntimeError("Development-store marker schema is invalid.")
    if resolved(marker["development_root"]) != path:
        raise RuntimeError("Development-store root binding differs.")
    source = resolved(marker["source_machine_data_root"])
    if source == path or source in path.parents or path in source.parents:
        raise RuntimeError("Development and source machine-data roots are not disjoint.")
    store_id = str(UUID(str(marker["store_id"])))
    for name in (
        "created_at_utc", "created_by", "creation_commit",
        "source_tree_fingerprint", "source_active_pointer_sha256",
    ):
        if not isinstance(marker[name], str) or not marker[name].strip():
            raise RuntimeError(f"Development-store marker {name} is invalid.")
    for name in ("source_tree_fingerprint", "source_active_pointer_sha256"):
        value = marker[name]
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise RuntimeError(f"Development-store marker {name} is not SHA-256.")
    pointer = json.loads((path / "active_machine.json").read_text(encoding="utf-8"))
    if pointer.get("schema_name") != "labcraft.active_machine" or pointer.get("schema_version") != 2:
        raise RuntimeError("Development active pointer is not authorized.")
    machine_id = pointer.get("machine_id")
    if not isinstance(machine_id, str) or not machine_id.strip():
        raise RuntimeError("Development machine ID is invalid.")
    machine_uuid = str(UUID(str(pointer.get("machine_uuid"))))
    UUID(str(pointer.get("activation_id")))
    UUID(str(pointer.get("migration_id")))
    receipt_digest = pointer.get("activation_receipt_sha256")
    if not isinstance(receipt_digest, str) or len(receipt_digest) != 64 or any(
        ch not in "0123456789abcdef" for ch in receipt_digest
    ):
        raise RuntimeError("Development activation receipt digest is invalid.")
    identity_path = path / "machines" / machine_uuid / "metadata" / "machine_identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    if (
        not isinstance(identity, dict)
        or identity.get("schema_name") != "labcraft.machine_identity"
        or identity.get("schema_version") != 1
    ):
        raise RuntimeError("Development machine identity schema is invalid.")
    if identity.get("machine_id") != machine_id:
        raise RuntimeError("Development machine identity differs from active pointer.")
    if str(UUID(str(identity.get("machine_uuid")))) != machine_uuid:
        raise RuntimeError("Development machine UUID differs from active pointer.")
    if not isinstance(identity.get("assigned_at"), str) or not identity["assigned_at"].strip():
        raise RuntimeError("Development machine identity assignment time is invalid.")
    if not isinstance(identity.get("notes", ""), str):
        raise RuntimeError("Development machine identity notes are invalid.")
    return store_id, machine_id


def environment_inventory(shared_python):
    probe = (
        "import importlib.metadata as m,json,sys;"
        "rows=sorted((str(d.metadata.get('Name') or '').lower(),str(d.version)) "
        "for d in m.distributions());"
        "print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,'packages':rows},"
        "sort_keys=True,separators=(',',':')))"
    )
    raw = run([str(shared_python), "-c", probe]).stdout.strip()
    payload = json.loads(raw)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "package_count": len(payload["packages"]),
        "executable": payload["executable"],
        "prefix": payload["prefix"],
    }


def load_config(path):
    target = Path(path)
    if not target.is_file() or target.is_symlink():
        raise RuntimeError("Development workflow configuration is missing or unsafe.")
    payload = json.loads(target.read_text(encoding="utf-8"))
    expected = {
        "schema_name", "schema_version", "production_repo", "development_repo",
        "shared_python", "development_machine_data_root", "development_store_id",
        "machine_id", "dependency_manifest_sha256", "configured_at_utc",
        "configured_by", "creation_commit",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise RuntimeError("Development workflow configuration fields differ from schema.")
    if payload["schema_name"] != CONFIG_SCHEMA or payload["schema_version"] != CONFIG_VERSION:
        raise RuntimeError("Development workflow configuration schema is invalid.")
    return payload


def reject_link_ancestors(path):
    current = Path(path.anchor)
    for part in path.parts[1:-1]:
        current = current / part
        if current.exists() and stat.S_ISLNK(current.lstat().st_mode):
            raise RuntimeError(f"Workflow configuration parent is a symlink: {current}")


def atomic_json(path, payload):
    reject_link_ancestors(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise RuntimeError("Workflow configuration path cannot be a symlink.")
    temporary = path.parent / f".{path.name}.{uuid4()}.tmp"
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main():
    config = json.loads(base64.urlsafe_b64decode(sys.argv[1]).decode("utf-8"))
    mode = config["mode"]
    production = resolved(config["production_repo"])
    development = resolved(config["development_repo"])
    shared_python = resolved(config["shared_python"])
    machine_data = resolved(config["development_machine_data_root"])
    config_path = Path(config["workflow_config"]).expanduser()
    expected_commit = config["expected_commit"]

    if not config_path.is_absolute():
        raise RuntimeError("Workflow configuration path is not absolute.")
    reject_link_ancestors(config_path)
    resolved_config = config_path.resolve(strict=False)
    if (
        resolved_config == production or resolved_config == development
        or production in resolved_config.parents or development in resolved_config.parents
        or resolved_config in production.parents or resolved_config in development.parents
    ):
        raise RuntimeError("Workflow configuration overlaps a code worktree.")

    if git(production, "rev-parse", "HEAD").stdout.strip() != config["expected_production_head"]:
        raise RuntimeError("Protected production HEAD changed after preflight.")
    if git(production, "branch", "--show-current").stdout.strip() != config["expected_production_branch"]:
        raise RuntimeError("Protected production branch changed after preflight.")
    if git(production, "status", "--porcelain=v1", "--untracked-files=all").stdout.splitlines():
        raise RuntimeError("Protected production worktree is dirty.")
    if git(development, "rev-parse", "HEAD").stdout.strip() != expected_commit:
        raise RuntimeError("Development worktree is not at the exact Windows commit.")
    if git(development, "branch", "--show-current").stdout.strip():
        raise RuntimeError("Development worktree is not detached.")
    if git(development, "status", "--porcelain=v1", "--untracked-files=all").stdout.splitlines():
        raise RuntimeError("Development worktree is dirty.")
    if relevant_processes():
        raise RuntimeError("A LabCraft application or hardware workflow is running.")

    production_inventory, production_fingerprint = dependency_inventory(production)
    development_inventory, development_fingerprint = dependency_inventory(development)
    if production_inventory != development_inventory or production_fingerprint != development_fingerprint:
        raise RuntimeError("Development dependency declarations differ from production.")
    if not shared_python.is_file() or not os.access(shared_python, os.X_OK):
        raise RuntimeError("Shared Python is missing or not executable.")
    environment_before = environment_inventory(shared_python)
    python_version_result = run([str(shared_python), "--version"])
    python_version = (python_version_result.stdout or python_version_result.stderr).strip()
    pip_check = run([str(shared_python), "-m", "pip", "check"])
    import_check = run([
        str(shared_python), "-c",
        "import PySide6, cv2, numpy, serial; print('PySide6,cv2,numpy,serial')",
    ])
    store_id, machine_id = validate_store(machine_data, production, development)
    environment_after = environment_inventory(shared_python)
    if environment_before != environment_after:
        raise RuntimeError("Shared Python environment changed during read-only validation.")

    desired = {
        "schema_name": CONFIG_SCHEMA,
        "schema_version": CONFIG_VERSION,
        "production_repo": str(production),
        "development_repo": str(development),
        "shared_python": str(shared_python),
        "development_machine_data_root": str(machine_data),
        "development_store_id": store_id,
        "machine_id": machine_id,
        "dependency_manifest_sha256": development_fingerprint,
        "configured_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "configured_by": config["operator"],
        "creation_commit": expected_commit,
    }
    action = "validated"
    if mode == "configure":
        if config_path.exists():
            existing = load_config(config_path)
            stable_names = set(desired) - {"configured_at_utc", "configured_by", "creation_commit"}
            if any(existing[name] != desired[name] for name in stable_names):
                raise RuntimeError("Existing workflow configuration differs; refusing to overwrite it.")
            desired = existing
            action = "unchanged"
        else:
            atomic_json(config_path, desired)
            action = "created"
    elif mode == "validate":
        existing = load_config(config_path)
        for name in (
            "production_repo", "development_repo", "shared_python",
            "development_machine_data_root", "development_store_id", "machine_id",
            "dependency_manifest_sha256",
        ):
            if existing[name] != desired[name]:
                raise RuntimeError(f"Configured {name} no longer matches validated state.")
        desired = existing
    else:
        raise RuntimeError(f"Unsupported runtime configuration mode: {mode}")

    print(json.dumps({
        "action": action,
        "config_path": str(config_path),
        "config": desired,
        "dependency_inventory": development_inventory,
        "dependency_manifest_sha256": development_fingerprint,
        "python_version": python_version,
        "pip_check": pip_check.stdout.strip(),
        "imports": import_check.stdout.strip(),
        "environment_before": environment_before,
        "environment_after": environment_after,
    }, sort_keys=True, separators=(",", ":")))


try:
    main()
except Exception as exc:
    print(f"Runtime configuration failed: {exc}", file=sys.stderr)
    raise SystemExit(1)
'''


def collect_remote_state(
    *,
    pi_host: str,
    pi_user: str,
    identity_file: Path | None,
    production_repo: str,
    development_repo: str,
    shared_python: str,
    development_machine_data_root: str | None,
    workflow_config: str = DEFAULT_WORKFLOW_CONFIG,
    timeout_seconds: int = 20,
) -> dict[str, Any]:
    if "@" in pi_host:
        target = pi_host
    else:
        target = f"{pi_user}@{pi_host}"
    config = {
        "production_repo": production_repo,
        "development_repo": development_repo,
        "shared_python": shared_python,
        "development_machine_data_root": development_machine_data_root,
        "development_machine_data_parent": DEFAULT_DEVELOPMENT_PARENT,
        "workflow_config": workflow_config,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(config, sort_keys=True).encode("utf-8")
    ).decode("ascii")
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={timeout_seconds}",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=2",
    ]
    if identity_file is not None:
        command.extend(["-i", str(identity_file)])
    command.extend([target, "python3", "-", encoded])
    completed = _run(command, input_text=REMOTE_COLLECTOR)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise WorkflowError("Pi returned malformed status JSON.") from exc
    if not isinstance(payload, dict):
        raise WorkflowError("Pi status response is not a JSON object.")
    payload["ssh_target"] = target
    payload["ssh_identity_supplied"] = identity_file is not None
    return payload


def sync_remote_worktree(
    *,
    pi_host: str,
    pi_user: str,
    identity_file: Path | None,
    production_repo: str,
    development_repo: str,
    expected_commit: str,
    expected_production_head: str,
    expected_production_branch: str,
    remote_name: str,
    remote_ref: str,
    expected_remote_url: str,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    if not remote_name or remote_name == ".":
        raise WorkflowError("A named Git remote is required for synchronization.")
    if not remote_ref.startswith("refs/heads/"):
        raise WorkflowError("The upstream merge ref must identify a remote branch.")
    branch_suffix = remote_ref[len("refs/heads/"):]
    tracking_ref = f"refs/remotes/{remote_name}/{branch_suffix}"
    target = pi_host if "@" in pi_host else f"{pi_user}@{pi_host}"
    config = {
        "production_repo": production_repo,
        "development_repo": development_repo,
        "expected_commit": expected_commit,
        "expected_production_head": expected_production_head,
        "expected_production_branch": expected_production_branch,
        "remote_name": remote_name,
        "remote_ref": remote_ref,
        "tracking_ref": tracking_ref,
        "expected_remote_url": expected_remote_url,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(config, sort_keys=True).encode("utf-8")
    ).decode("ascii")
    command = [
        "ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout_seconds}",
        "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=8",
    ]
    if identity_file is not None:
        command.extend(["-i", str(identity_file)])
    command.extend([target, "python3", "-", encoded])
    completed = _run(command, input_text=REMOTE_SYNC)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise WorkflowError("Pi returned malformed synchronization JSON.") from exc
    if not isinstance(payload, dict):
        raise WorkflowError("Pi synchronization response is not a JSON object.")
    return payload


def configure_remote_runtime(
    *,
    mode: str,
    pi_host: str,
    pi_user: str,
    identity_file: Path | None,
    production_repo: str,
    development_repo: str,
    shared_python: str,
    development_machine_data_root: str,
    workflow_config: str,
    operator: str,
    expected_commit: str,
    expected_production_head: str,
    expected_production_branch: str,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    if mode not in {"configure", "validate"}:
        raise WorkflowError(f"Unsupported runtime configuration mode: {mode}")
    operator_text = str(operator or "").strip()
    if not operator_text:
        raise WorkflowError("An operator identity is required.")
    target = pi_host if "@" in pi_host else f"{pi_user}@{pi_host}"
    config = {
        "mode": mode,
        "production_repo": production_repo,
        "development_repo": development_repo,
        "shared_python": shared_python,
        "development_machine_data_root": development_machine_data_root,
        "workflow_config": workflow_config,
        "operator": operator_text,
        "expected_commit": expected_commit,
        "expected_production_head": expected_production_head,
        "expected_production_branch": expected_production_branch,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(config, sort_keys=True).encode("utf-8")
    ).decode("ascii")
    command = [
        "ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout_seconds}",
        "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=8",
    ]
    if identity_file is not None:
        command.extend(["-i", str(identity_file)])
    command.extend([target, "python3", "-", encoded])
    completed = _run(
        command,
        input_text=REMOTE_RUNTIME_CONFIG,
        timeout_seconds=timeout_seconds,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise WorkflowError("Pi returned malformed runtime-configuration JSON.") from exc
    if not isinstance(payload, dict):
        raise WorkflowError("Pi runtime-configuration response is not a JSON object.")
    return payload


def pi_invariant_payload(remote: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "hostname": remote.get("hostname"),
        "production_worktree": remote.get("production_worktree"),
        "other_worktrees": remote.get("other_worktrees"),
        "shared_python": remote.get("shared_python"),
        "processes": remote.get("processes"),
        "development_machine_data": remote.get("development_machine_data"),
    }


def canonical_sha256(payload: Mapping[str, Any]) -> str:
    import hashlib

    data = json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def classify_status(
    local: Mapping[str, Any], remote: Mapping[str, Any]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    def block(code: str, message: str) -> None:
        blockers.append({"code": code, "message": message})

    def warn(code: str, message: str) -> None:
        warnings.append({"code": code, "message": message})

    if not local.get("clean"):
        block("local_dirty", "The Windows working tree is not clean.")
    if local.get("detached"):
        block("local_detached", "The Windows checkout has a detached HEAD.")
    if not local.get("upstream"):
        block("local_upstream_missing", "The Windows branch has no upstream.")
    elif not local.get("head_reachable_from_upstream"):
        block("local_head_unpublished", "Windows HEAD is not reachable from its upstream.")
    if (local.get("behind") or 0) > 0 and local.get("head_reachable_from_upstream"):
        warn("local_behind", "Windows HEAD is pushed but behind its upstream.")

    production = remote.get("production_worktree") or {}
    if not production.get("valid") or not production.get("registered", False):
        block("production_invalid", "The protected production worktree is invalid.")
    elif not production.get("clean"):
        block("production_dirty", "The protected production worktree is not clean.")

    development = remote.get("development_worktree") or {}
    development_state = development.get("state")
    if development_state == "absent":
        warn("development_worktree_absent", "The development worktree has not been created yet.")
    elif development_state != "registered_clean":
        block(
            "development_worktree_unsafe",
            f"Development worktree state is {development_state or 'unknown'}.",
        )

    other_worktrees = remote.get("other_worktrees") or []
    if other_worktrees:
        warn(
            "additional_worktrees",
            f"{len(other_worktrees)} additional registered worktree(s) were preserved.",
        )

    interpreter = remote.get("shared_python") or {}
    if not interpreter.get("exists") or not interpreter.get("executable"):
        block("shared_python_invalid", "The configured shared Python is unavailable.")

    processes = remote.get("processes") or []
    if processes:
        block("labcraft_process_running", "A LabCraft application or hardware workflow is running.")

    store = remote.get("development_machine_data") or {}
    if store.get("selection_source") in {"none", "ambiguous"}:
        block(
            "development_store_unresolved",
            "Development machine-data selection is missing or ambiguous.",
        )
    elif not (store.get("selected") or {}).get("valid"):
        block("development_store_invalid", "Development machine-data evidence is invalid.")
    workflow_config = remote.get("workflow_config") or {}
    if workflow_config.get("exists") and not workflow_config.get("valid"):
        block("workflow_config_invalid", "The external development workflow configuration is invalid.")

    return blockers, warnings


def build_report(
    *,
    action: str,
    local: Mapping[str, Any],
    remote: Mapping[str, Any],
    clock: datetime | None = None,
    collection_id: str | None = None,
) -> dict[str, Any]:
    blockers, warnings = classify_status(local, remote)
    now = clock or datetime.now(timezone.utc)
    state = "blocked" if blockers else "warning" if warnings else "ready"
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "collection_id": collection_id or str(uuid4()),
        "collected_at_utc": now.astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "action": action,
        "overall_state": state,
        "blockers": blockers,
        "warnings": warnings,
        "local": dict(local),
        "pi": dict(remote),
    }


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid4()}.tmp"
    data = json.dumps(
        dict(payload), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
    ) + "\n"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_report(
    report: Mapping[str, Any], output_root: Path = DEFAULT_OUTPUT_ROOT
) -> Path:
    timestamp = str(report["collected_at_utc"]).replace("-", "").replace(":", "")
    timestamp = timestamp.replace(".", "").replace("+0000", "Z")
    short_head = str((report.get("local") or {}).get("short_head") or "unknown")
    directory = output_root.resolve() / f"{timestamp}_{short_head}"
    path = directory / "status.json"
    if path.exists():
        directory = output_root.resolve() / f"{timestamp}_{short_head}_{report['collection_id']}"
        path = directory / "status.json"
    _atomic_json(path, report)
    return path


def print_summary(report: Mapping[str, Any], report_path: Path) -> None:
    local = report["local"]
    remote = report["pi"]
    production = remote["production_worktree"]
    development = remote["development_worktree"]
    interpreter = remote["shared_python"]
    store = remote["development_machine_data"]
    selected = store.get("selected") or {}
    print(f"Development workflow: {str(report['overall_state']).upper()}")
    print(f"Windows: {local.get('branch') or '(detached)'} {local['head']}")
    print(
        "Production Pi: "
        f"{production.get('branch') or '(detached)'} {production.get('head') or 'unknown'}"
    )
    print(f"Development worktree: {development.get('state')}")
    print(f"Shared Python: {interpreter.get('version') or 'unavailable'}")
    print(
        "Development data: "
        f"{selected.get('machine_id') or 'unresolved'} "
        f"{selected.get('store_id') or ''}".rstrip()
    )
    runtime = report.get("runtime") or {}
    if runtime.get("status") == "passed":
        print(
            "Runtime binding: "
            f"{runtime.get('action') or 'validated'} "
            f"{runtime.get('config_path') or ''}".rstrip()
        )
    for warning in report["warnings"]:
        print(f"WARNING [{warning['code']}]: {warning['message']}")
    for blocker in report["blockers"]:
        print(f"BLOCKED [{blocker['code']}]: {blocker['message']}")
    print(f"Report: {report_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect the Windows and Pi development workflow safely."
    )
    parser.add_argument(
        "--action",
        choices=("status", "preflight", "sync", "configure", "validate"),
        default="status",
    )
    parser.add_argument("--pi-host", required=True)
    parser.add_argument("--pi-user", default="labcraft")
    parser.add_argument("--ssh-identity-file", type=Path)
    parser.add_argument("--production-repo", default=DEFAULT_PRODUCTION_REPO)
    parser.add_argument("--development-repo", default=DEFAULT_DEVELOPMENT_REPO)
    parser.add_argument("--shared-python", default=DEFAULT_SHARED_PYTHON)
    parser.add_argument("--development-machine-data-root")
    parser.add_argument("--workflow-config", default=DEFAULT_WORKFLOW_CONFIG)
    parser.add_argument("--operator", default=getpass.getuser())
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    identity = args.ssh_identity_file
    if identity is not None:
        identity = identity.expanduser()
        if not identity.is_absolute():
            identity = (REPO_ROOT / identity).resolve()
        else:
            identity = identity.resolve()
        if not identity.is_file():
            print(f"Workflow failed: SSH identity file does not exist: {identity}", file=sys.stderr)
            return 1
    try:
        validate_remote_paths(
            pi_user=args.pi_user,
            production_repo=args.production_repo,
            development_repo=args.development_repo,
            shared_python=args.shared_python,
            development_machine_data_root=args.development_machine_data_root,
            workflow_config=args.workflow_config,
        )
    except WorkflowError as exc:
        print(f"Workflow failed: {exc}", file=sys.stderr)
        return 1
    if args.dry_run:
        target = args.pi_host if "@" in args.pi_host else f"{args.pi_user}@{args.pi_host}"
        print(f"DRY RUN action={args.action}")
        print(f"Windows repository: {REPO_ROOT}")
        print(f"SSH target: {target}")
        print(f"Production repository: {args.production_repo}")
        print(f"Development repository: {args.development_repo}")
        print(f"Shared Python: {args.shared_python}")
        print(
            "Development machine data: "
            f"{args.development_machine_data_root or '(from validated configuration/discovery)'}"
        )
        print(f"Workflow configuration: {args.workflow_config}")
        print(f"Operator: {args.operator}")
        print("No SSH call or report write was performed.")
        return 0
    if shutil.which("ssh") is None:
        print(
            "Workflow failed: Windows OpenSSH client 'ssh' was not found on PATH.",
            file=sys.stderr,
        )
        return 1
    try:
        local = collect_local_state(REPO_ROOT)
        remote = collect_remote_state(
            pi_host=args.pi_host,
            pi_user=args.pi_user,
            identity_file=identity,
            production_repo=args.production_repo,
            development_repo=args.development_repo,
            shared_python=args.shared_python,
            development_machine_data_root=args.development_machine_data_root,
            workflow_config=args.workflow_config,
        )
        report = build_report(action=args.action, local=local, remote=remote)
        if args.action == "sync" and not report["blockers"]:
            pre_invariant = canonical_sha256(pi_invariant_payload(remote))
            try:
                sync_result = sync_remote_worktree(
                    pi_host=args.pi_host,
                    pi_user=args.pi_user,
                    identity_file=identity,
                    production_repo=args.production_repo,
                    development_repo=args.development_repo,
                    expected_commit=local["head"],
                    expected_production_head=remote["production_worktree"]["head"],
                    expected_production_branch=remote["production_worktree"]["branch"],
                    remote_name=str(local.get("upstream_remote") or ""),
                    remote_ref=str(local.get("upstream_merge_ref") or ""),
                    expected_remote_url=str(local.get("origin_url") or ""),
                )
                post_remote = collect_remote_state(
                    pi_host=args.pi_host,
                    pi_user=args.pi_user,
                    identity_file=identity,
                    production_repo=args.production_repo,
                    development_repo=args.development_repo,
                    shared_python=args.shared_python,
                    development_machine_data_root=args.development_machine_data_root,
                    workflow_config=args.workflow_config,
                )
                post_invariant = canonical_sha256(pi_invariant_payload(post_remote))
                post_development = post_remote.get("development_worktree") or {}
                if pre_invariant != post_invariant:
                    raise WorkflowError("Protected Pi invariants changed during synchronization.")
                if (
                    post_development.get("state") != "registered_clean"
                    or post_development.get("head") != local["head"]
                    or not post_development.get("detached")
                ):
                    raise WorkflowError("Development worktree postflight differs from the requested commit.")
                report = build_report(
                    action=args.action, local=local, remote=post_remote
                )
                report["sync"] = {
                    "status": "passed",
                    "pre_invariant_sha256": pre_invariant,
                    "post_invariant_sha256": post_invariant,
                    **sync_result,
                }
            except (OSError, ValueError, WorkflowError) as exc:
                report["sync"] = {"status": "failed", "error": str(exc)}
                report_path = write_report(report, args.output_root)
                print_summary(report, report_path)
                print(f"Workflow failed: {exc}", file=sys.stderr)
                return 1
        if args.action in {"configure", "validate"} and not report["blockers"]:
            selected_store = (
                remote.get("development_machine_data") or {}
            ).get("selected") or {}
            development = remote.get("development_worktree") or {}
            if (
                development.get("state") != "registered_clean"
                or development.get("head") != local["head"]
                or not development.get("detached")
            ):
                report["runtime"] = {
                    "status": "failed",
                    "error": "Development worktree is not detached at the exact Windows commit.",
                }
                report_path = write_report(report, args.output_root)
                print_summary(report, report_path)
                return 2
            machine_data_root = selected_store.get("path")
            if not machine_data_root:
                report["runtime"] = {
                    "status": "failed", "error": "Development machine data is unresolved."
                }
                report_path = write_report(report, args.output_root)
                print_summary(report, report_path)
                return 2
            if args.action == "configure" and not args.development_machine_data_root:
                report["runtime"] = {
                    "status": "failed",
                    "error": "Configure requires an explicit development machine-data root.",
                }
                report_path = write_report(report, args.output_root)
                print_summary(report, report_path)
                return 2
            pre_invariant = canonical_sha256(pi_invariant_payload(remote))
            try:
                runtime_result = configure_remote_runtime(
                    mode=args.action,
                    pi_host=args.pi_host,
                    pi_user=args.pi_user,
                    identity_file=identity,
                    production_repo=args.production_repo,
                    development_repo=args.development_repo,
                    shared_python=args.shared_python,
                    development_machine_data_root=str(machine_data_root),
                    workflow_config=args.workflow_config,
                    operator=args.operator,
                    expected_commit=local["head"],
                    expected_production_head=remote["production_worktree"]["head"],
                    expected_production_branch=remote["production_worktree"]["branch"],
                )
                post_remote = collect_remote_state(
                    pi_host=args.pi_host,
                    pi_user=args.pi_user,
                    identity_file=identity,
                    production_repo=args.production_repo,
                    development_repo=args.development_repo,
                    shared_python=args.shared_python,
                    development_machine_data_root=(
                        args.development_machine_data_root
                        if args.action == "configure" else None
                    ),
                    workflow_config=args.workflow_config,
                )
                post_invariant = canonical_sha256(pi_invariant_payload(post_remote))
                if pre_invariant != post_invariant:
                    raise WorkflowError("Protected Pi invariants changed during runtime configuration.")
                if not (post_remote.get("workflow_config") or {}).get("valid"):
                    raise WorkflowError("Workflow configuration postflight is invalid.")
                report = build_report(action=args.action, local=local, remote=post_remote)
                report["runtime"] = {
                    "status": "passed",
                    "pre_invariant_sha256": pre_invariant,
                    "post_invariant_sha256": post_invariant,
                    "pre_workflow_config": remote.get("workflow_config"),
                    "post_workflow_config": post_remote.get("workflow_config"),
                    **runtime_result,
                }
            except (OSError, ValueError, WorkflowError) as exc:
                report["runtime"] = {"status": "failed", "error": str(exc)}
                report_path = write_report(report, args.output_root)
                print_summary(report, report_path)
                print(f"Workflow failed: {exc}", file=sys.stderr)
                return 1
        report_path = write_report(report, args.output_root)
        print_summary(report, report_path)
        if args.action == "sync" and report["blockers"]:
            return 2
        if args.action in {"configure", "validate"} and report["blockers"]:
            return 2
    except (OSError, ValueError, WorkflowError) as exc:
        print(f"Workflow failed: {exc}", file=sys.stderr)
        return 1
    if args.action == "preflight" and report["blockers"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
