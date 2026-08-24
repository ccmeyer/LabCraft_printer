"""Orchestrate isolated exact-tag upgrade rehearsals on a Raspberry Pi."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import sys
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_RUNNER = REPO_ROOT / "tools" / "run_machine_data_bootstrap_only.py"
PUBLIC_REMOTE_URL = "https://github.com/ccmeyer/LabCraft_printer.git"
DEFAULT_PRODUCTION_REPO = "/home/labcraft/LabCraft_printer"
DEFAULT_DEVELOPMENT_REPO = "/home/labcraft/LabCraft_printer-dev"
DEFAULT_SHARED_PYTHON = "/home/labcraft/LabCraft_printer/env/bin/python"
DEFAULT_WORKFLOW_CONFIG = "/home/labcraft/.config/LabCraft/development_workflow.json"
DEFAULT_FIRMWARE_STATE = (
    "/home/labcraft/.local/share/LabCraft/LabCraft Printer/"
    "development-workflow/firmware-state.json"
)
DEFAULT_REMOTE_ROOT = (
    "/home/labcraft/.local/share/LabCraft/LabCraft Printer/"
    "development-workflow/upgrade-rehearsals"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "verification_reports" / "upgrade-rehearsal"
STATE_SCHEMA = "labcraft.pi_upgrade_rehearsal_state"
STATE_SCHEMA_VERSION = 1
REPORT_SCHEMA = "labcraft.pi_upgrade_rehearsal_report"
REPORT_SCHEMA_VERSION = 1
CAMPAIGN_SCHEMA = "labcraft.pi_upgrade_rehearsal_campaign"
CAMPAIGN_SCHEMA_VERSION = 1
STAGES = (
    "prepared",
    "updated",
    "cancellation_passed",
    "activated",
    "verified",
)
TAG_PATTERN = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+(?:-rc\.[0-9]+)?$")


class RehearsalError(RuntimeError):
    """Raised when a rehearsal safety or evidence gate fails."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_sha256(value: object) -> str:
    data = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _run(
    arguments: Sequence[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
    timeout_seconds: int | None = None,
    allowed: Sequence[int] = (0,),
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
        raise RehearsalError(
            f"Command timed out after {timeout_seconds} seconds: {arguments[0]}"
        ) from exc
    if completed.returncode not in allowed:
        detail = (completed.stderr or completed.stdout).strip()
        raise RehearsalError(
            f"Command failed ({completed.returncode}): {arguments[0]}"
            + (f": {detail}" if detail else "")
        )
    return completed


def _git(*arguments: str, cwd: Path = REPO_ROOT, allowed=(0,)):
    return _run(["git", *arguments], cwd=cwd, allowed=allowed)


def validate_tag(tag: str, label: str) -> str:
    value = str(tag or "").strip()
    if not TAG_PATTERN.fullmatch(value):
        raise RehearsalError(f"{label} must be an exact release tag: {tag!r}")
    return value


def validate_remote_paths(
    *,
    pi_user: str,
    production_repo: str,
    development_repo: str,
    shared_python: str,
    workflow_config: str,
    firmware_state_path: str,
    remote_root: str,
) -> None:
    values = {
        "production repository": production_repo,
        "development repository": development_repo,
        "shared Python": shared_python,
        "workflow configuration": workflow_config,
        "firmware state": firmware_state_path,
        "rehearsal root": remote_root,
    }
    parsed: dict[str, PurePosixPath] = {}
    for label, raw in values.items():
        path = PurePosixPath(raw)
        if not path.is_absolute() or ".." in path.parts:
            raise RehearsalError(f"{label} must be an absolute Pi path without '..'.")
        parsed[label] = path
    production = parsed["production repository"]
    development = parsed["development repository"]
    root = parsed["rehearsal root"]
    broad = {PurePosixPath("/"), PurePosixPath(f"/home/{pi_user}")}
    if production in broad or development in broad or root in broad:
        raise RehearsalError("Worktree and rehearsal paths cannot be broad roots.")
    if production == development or production in development.parents or development in production.parents:
        raise RehearsalError("Production and development worktrees must be disjoint.")
    for worktree in (production, development):
        if root == worktree or root in worktree.parents or worktree in root.parents:
            raise RehearsalError("Rehearsal storage must be external to both worktrees.")
    shared = parsed["shared Python"]
    if production not in shared.parents or development in shared.parents:
        raise RehearsalError("Shared Python must come from the protected production environment.")
    for label in ("workflow configuration", "firmware state"):
        path = parsed[label]
        if any(path == tree or path in tree.parents or tree in path.parents for tree in (production, development)):
            raise RehearsalError(f"{label} must be outside both worktrees.")
        if root == path or root in path.parents or path in root.parents:
            raise RehearsalError(f"Rehearsal root must be disjoint from {label}.")


def collect_local_harness(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    root = Path(_git("rev-parse", "--show-toplevel", cwd=repo_root).stdout.strip()).resolve()
    head = _git("rev-parse", "HEAD", cwd=root).stdout.strip()
    branch = _git("branch", "--show-current", cwd=root).stdout.strip()
    status = _git("status", "--porcelain=v1", "--untracked-files=all", cwd=root).stdout.splitlines()
    upstream_result = _git(
        "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}",
        cwd=root, allowed=(0, 128),
    )
    upstream = upstream_result.stdout.strip() if upstream_result.returncode == 0 else ""
    ahead = behind = None
    reachable = False
    if upstream:
        counts = _git("rev-list", "--left-right", "--count", f"HEAD...{upstream}", cwd=root).stdout.split()
        if len(counts) == 2:
            ahead, behind = map(int, counts)
        reachable = _git(
            "merge-base", "--is-ancestor", "HEAD", upstream,
            cwd=root, allowed=(0, 1),
        ).returncode == 0
    return {
        "repo_root": str(root),
        "head": head,
        "branch": branch or None,
        "clean": not status,
        "status": status,
        "upstream": upstream or None,
        "ahead": ahead,
        "behind": behind,
        "published": reachable and ahead == 0,
    }


def resolve_annotated_tag(tag: str, *, repo_root: Path = REPO_ROOT) -> dict[str, str]:
    tag = validate_tag(tag, "Release")
    object_type = _git("cat-file", "-t", f"refs/tags/{tag}", cwd=repo_root, allowed=(0, 128))
    if object_type.returncode != 0 or object_type.stdout.strip() != "tag":
        raise RehearsalError(f"Release {tag} is missing or is not an annotated tag.")
    object_sha = _git("rev-parse", f"refs/tags/{tag}", cwd=repo_root).stdout.strip()
    commit = _git("rev-parse", f"refs/tags/{tag}^{{commit}}", cwd=repo_root).stdout.strip()
    return {"tag": tag, "tag_object": object_sha, "commit": commit}


def validate_local_release_pair(source: str, target: str) -> tuple[dict[str, str], dict[str, str]]:
    source_ref = resolve_annotated_tag(source)
    target_ref = resolve_annotated_tag(target)
    if source_ref["commit"] == target_ref["commit"]:
        raise RehearsalError("Source and target releases resolve to the same commit.")
    ancestor = _git(
        "merge-base", "--is-ancestor", source_ref["commit"], target_ref["commit"],
        allowed=(0, 1),
    )
    if ancestor.returncode != 0:
        raise RehearsalError("Source release is not an ancestor of the target release.")
    manifest_path = f"releases/{target}.json"
    manifest_result = _git("show", f"{target}:{manifest_path}", allowed=(0, 128))
    if manifest_result.returncode != 0:
        raise RehearsalError(f"Target release manifest is missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_result.stdout)
    except json.JSONDecodeError as exc:
        raise RehearsalError("Target release manifest is malformed.") from exc
    if manifest.get("version") != target or manifest.get("tag") != target:
        raise RehearsalError("Target release manifest does not bind the requested tag.")
    machine_data = manifest.get("machine_data")
    if not isinstance(machine_data, dict) or machine_data.get("preservation_contract") != "labcraft.machine_data_update.v1":
        raise RehearsalError("Target release lacks the supported machine-data preservation contract.")
    return source_ref, target_ref


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(dict(payload), handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _ssh_command(args: argparse.Namespace) -> list[str]:
    target = args.pi_host if "@" in args.pi_host else f"{args.pi_user}@{args.pi_host}"
    command = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
        "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=8",
    ]
    if args.ssh_identity_file:
        command.extend(["-i", str(Path(args.ssh_identity_file))])
    command.extend([target, "python3", "-", "--remote"])
    return command


def invoke_remote(args: argparse.Namespace, request: Mapping[str, Any]) -> dict[str, Any]:
    encoded = base64.urlsafe_b64encode(
        json.dumps(dict(request), sort_keys=True).encode("utf-8")
    ).decode("ascii")
    command = [*_ssh_command(args), encoded]
    source = Path(__file__).read_text(encoding="utf-8")
    completed = _run(
        command,
        input_text=source,
        timeout_seconds=args.timeout_seconds + 60,
        allowed=(0, 1),
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RehearsalError("Pi returned malformed rehearsal JSON.") from exc
    if not isinstance(payload, dict):
        raise RehearsalError("Pi rehearsal response is not an object.")
    if payload.get("status") not in {"passed", "failed"}:
        raise RehearsalError("Pi rehearsal response has an invalid status.")
    if completed.returncode == 0 and payload.get("status") != "passed":
        raise RehearsalError("Pi returned failed status with a successful SSH exit code.")
    if completed.returncode != 0 and payload.get("status") != "failed":
        raise RehearsalError("Pi returned passing status with a failed SSH exit code.")
    return payload


def build_request(args: argparse.Namespace, local: Mapping[str, Any]) -> dict[str, Any]:
    request: dict[str, Any] = {
        "action": args.action,
        "run_ids": list(args.run_id or ()),
        "pi_user": args.pi_user,
        "production_repo": args.production_repo,
        "development_repo": args.development_repo,
        "shared_python": args.shared_python,
        "workflow_config": args.workflow_config,
        "firmware_state_path": args.firmware_state_path,
        "remote_root": args.remote_root,
        "public_remote_url": PUBLIC_REMOTE_URL,
        "harness_commit": local.get("head"),
        "operator": str(args.operator or "").strip(),
        "timeout_seconds": args.timeout_seconds,
    }
    if args.action == "prepare":
        source_ref, target_ref = validate_local_release_pair(
            args.source_release, args.target_release
        )
        runner_bytes = BOOTSTRAP_RUNNER.read_bytes()
        request.update(
            {
                "run_id": str(uuid4()),
                "source_release": source_ref,
                "target_release": target_ref,
                "source_wrapper": args.source_wrapper,
                "expected_machine_id": args.expected_machine_id,
                "bootstrap_runner_sha256": hashlib.sha256(runner_bytes).hexdigest(),
            }
        )
    if args.action in {"cancel", "activate", "verify"}:
        runner_bytes = BOOTSTRAP_RUNNER.read_bytes()
        request.update(
            {
                "bootstrap_runner_b64": base64.b64encode(runner_bytes).decode("ascii"),
                "bootstrap_runner_sha256": hashlib.sha256(runner_bytes).hexdigest(),
            }
        )
    return request


def _write_local_report(args: argparse.Namespace, payload: Mapping[str, Any]) -> Path:
    output = Path(args.output_root).resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_label = "_".join(args.run_id or ()) or str(payload.get("run_id") or "campaign")
    run_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", run_label)[:160]
    path = output / f"{stamp}_{args.action}_{run_label}.json"
    _atomic_json(path, payload)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action",
        choices=("prepare", "status", "update", "cancel", "activate", "verify", "summarize"),
        default="status",
    )
    parser.add_argument("--pi-host", required=True)
    parser.add_argument("--pi-user", default="labcraft")
    parser.add_argument("--ssh-identity-file", type=Path)
    parser.add_argument("--production-repo", default=DEFAULT_PRODUCTION_REPO)
    parser.add_argument("--development-repo", default=DEFAULT_DEVELOPMENT_REPO)
    parser.add_argument("--shared-python", default=DEFAULT_SHARED_PYTHON)
    parser.add_argument("--workflow-config", default=DEFAULT_WORKFLOW_CONFIG)
    parser.add_argument("--firmware-state-path", default=DEFAULT_FIRMWARE_STATE)
    parser.add_argument("--remote-root", default=DEFAULT_REMOTE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", action="append")
    parser.add_argument("--source-release")
    parser.add_argument("--target-release")
    parser.add_argument("--source-wrapper")
    parser.add_argument("--expected-machine-id")
    parser.add_argument("--operator", default=getpass.getuser())
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _validate_cli(args: argparse.Namespace) -> None:
    validate_remote_paths(
        pi_user=args.pi_user,
        production_repo=args.production_repo,
        development_repo=args.development_repo,
        shared_python=args.shared_python,
        workflow_config=args.workflow_config,
        firmware_state_path=args.firmware_state_path,
        remote_root=args.remote_root,
    )
    if not 30 <= args.timeout_seconds <= 86400:
        raise RehearsalError("Timeout must be between 30 and 86400 seconds.")
    run_ids = list(args.run_id or ())
    if args.action == "prepare":
        missing = [
            name for name, value in (
                ("source release", args.source_release),
                ("target release", args.target_release),
                ("source wrapper", args.source_wrapper),
                ("expected machine ID", args.expected_machine_id),
                ("operator", args.operator),
            ) if not str(value or "").strip()
        ]
        if missing or run_ids:
            raise RehearsalError(
                "Prepare requires source/target/source-wrapper/machine/operator and no run ID"
                + (f"; missing {', '.join(missing)}" if missing else ".")
            )
        validate_tag(args.source_release, "Source release")
        validate_tag(args.target_release, "Target release")
        source_path = PurePosixPath(args.source_wrapper)
        if not source_path.is_absolute() or ".." in source_path.parts:
            raise RehearsalError("Source wrapper must be an absolute Pi path without '..'.")
    elif args.action == "summarize":
        if len(run_ids) != 2 or len(set(run_ids)) != 2:
            raise RehearsalError("Summarize requires exactly two distinct run IDs.")
    elif len(run_ids) != 1:
        raise RehearsalError(f"{args.action.title()} requires exactly one run ID.")
    for value in run_ids:
        try:
            UUID(value)
        except ValueError as exc:
            raise RehearsalError(f"Invalid run ID: {value}") from exc


def local_main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _validate_cli(args)
        if args.dry_run:
            print("Pi upgrade rehearsal dry run")
            print(f"Action: {args.action}")
            print(f"Target: {args.pi_user}@{args.pi_host}")
            print(f"Remote root: {args.remote_root}")
            if args.run_id:
                print(f"Run IDs: {len(args.run_id)} run ID(s)")
            print("No SSH call, Git mutation, evidence write, bootstrap, or hardware action occurred.")
            return 0
        local = collect_local_harness()
        if args.action != "status" and (
            not local["clean"] or not local["branch"] or not local["upstream"] or not local["published"]
        ):
            raise RehearsalError(
                "Mutating rehearsal actions require a clean, attached, pushed Windows harness commit."
            )
        request = build_request(args, local)
        payload = invoke_remote(args, request)
        report = {
            "schema_name": REPORT_SCHEMA,
            "schema_version": REPORT_SCHEMA_VERSION,
            "recorded_at_utc": utc_now(),
            "action": args.action,
            "harness_commit": local["head"],
            "pi": payload,
        }
        path = _write_local_report(args, report)
        if payload.get("status") == "passed":
            print(json.dumps(payload, indent=2, sort_keys=True))
            print(f"Sanitized Windows evidence: {path}")
            return 0
        print(str(payload.get("error") or "Pi rehearsal action failed."), file=sys.stderr)
        print(f"Sanitized Windows failure evidence: {path}", file=sys.stderr)
        return 1
    except RehearsalError as exc:
        print(f"Upgrade rehearsal failed: {exc}", file=sys.stderr)
        return 1


# The functions below are intentionally standard-library-only.  The Windows
# supervisor streams this exact file to ``python3 -`` on the Pi; release code is
# imported only by the separately uploaded bootstrap-only runner.


def remote_run(
    arguments: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
    allowed: Sequence[int] = (0,),
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(arguments),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env=dict(env) if env is not None else None,
    )
    if completed.returncode not in allowed:
        detail = (completed.stderr or completed.stdout).strip()
        raise RehearsalError(
            f"Command failed ({completed.returncode}): {arguments[0]}"
            + (f": {detail}" if detail else "")
        )
    return completed


def remote_run_owned(
    arguments: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        list(arguments),
        cwd=cwd,
        env=dict(env) if env is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        cleanup = remote_stop_owned_group(process)
        stdout, stderr = process.communicate()
        raise RehearsalError(
            f"Owned command timed out after {timeout} seconds; cleanup={cleanup}."
        ) from exc
    completed = subprocess.CompletedProcess(
        list(arguments), process.returncode, stdout, stderr
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RehearsalError(
            f"Owned command failed ({completed.returncode}): {arguments[0]}"
            + (f": {detail}" if detail else "")
        )
    return completed


def remote_git(repo: Path, *arguments: str, allowed=(0,)):
    return remote_run(["git", "-C", str(repo), *arguments], allowed=allowed)


def remote_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def remote_tree_evidence(root: Path) -> dict[str, Any]:
    import stat

    requested = Path(root)
    resolved = requested.resolve(strict=False)
    rows: list[dict[str, Any]] = []
    folded: set[str] = set()
    if not requested.is_dir() or requested.is_symlink():
        raise RehearsalError(f"Tree root is missing or linked: {requested}")
    for candidate in sorted(requested.rglob("*")):
        details = candidate.lstat()
        if stat.S_ISLNK(details.st_mode):
            raise RehearsalError(f"Tree contains a symbolic link: {candidate}")
        relative = candidate.relative_to(requested).as_posix()
        if relative.casefold() in folded:
            raise RehearsalError("Tree contains case-colliding paths.")
        folded.add(relative.casefold())
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise RehearsalError(f"Tree contains a special file: {candidate}")
        rows.append(
            {
                "relative_path": relative,
                "size": candidate.stat().st_size,
                "sha256": remote_file_sha256(candidate),
            }
        )
    return {
        "path": str(resolved),
        "file_count": len(rows),
        "total_size": sum(row["size"] for row in rows),
        "tree_sha256": canonical_sha256(rows),
    }


def remote_optional_tree(root: Path) -> dict[str, Any]:
    if not root.exists():
        return {"path": str(root.resolve(strict=False)), "exists": False}
    result = remote_tree_evidence(root)
    result["exists"] = True
    return result


def remote_worktree(repo: Path) -> dict[str, Any]:
    root = repo.resolve(strict=False)
    if not repo.is_dir():
        return {"path": str(root), "valid": False, "error": "missing"}
    try:
        top = Path(remote_git(repo, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
        head = remote_git(repo, "rev-parse", "HEAD").stdout.strip()
        branch = remote_git(repo, "branch", "--show-current").stdout.strip()
        status = remote_git(
            repo, "status", "--porcelain=v1", "--untracked-files=all"
        ).stdout.splitlines()
        tree = remote_git(repo, "rev-parse", "HEAD^{tree}").stdout.strip()
        return {
            "path": str(root),
            "valid": top == root,
            "head": head,
            "tree": tree,
            "branch": branch or None,
            "clean": not status,
            "status": status,
            "error": None if top == root else "top-level mismatch",
        }
    except Exception as exc:
        return {"path": str(root), "valid": False, "error": str(exc)}


def remote_relevant_processes() -> list[dict[str, Any]]:
    needles = (
        "FreeRTOS-interface/App.py",
        "tools/run_development_app.py",
        "tools/update_window.py",
        "tools/update_and_restart.py",
        "run_machine_data_bootstrap_only.py",
        "firmware/hil/flash_and_test.sh",
        "tools/run_selftest.py",
        "dfu_update.py",
        "dfu-util",
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


def remote_dependency_inventory(repo: Path) -> dict[str, Any]:
    tracked = remote_git(repo, "ls-files", "--").stdout.splitlines()
    names = {"pyproject.toml", "poetry.lock", "Pipfile", "Pipfile.lock", "setup.py", "setup.cfg"}
    selected = sorted(
        name for name in tracked
        if "/" not in name
        and (name in names or (name.startswith("requirements") and name.endswith(".txt")))
    )
    if not selected:
        raise RehearsalError("No tracked dependency declaration was found.")
    files = {
        name: {
            "size": (repo / name).stat().st_size,
            "sha256": remote_file_sha256(repo / name),
        }
        for name in selected
    }
    return {"files": files, "sha256": canonical_sha256(files)}


def remote_environment_inventory(shared_python: Path) -> dict[str, Any]:
    probe = (
        "import importlib.metadata as m,json,sys;"
        "rows=sorted((str(d.metadata.get('Name') or '').lower(),str(d.version)) "
        "for d in m.distributions());"
        "print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,'packages':rows},"
        "sort_keys=True,separators=(',',':')))"
    )
    payload = json.loads(
        remote_run([str(shared_python), "-c", probe], timeout=120).stdout
    )
    return {
        "sha256": canonical_sha256(payload),
        "package_count": len(payload["packages"]),
        "executable": payload["executable"],
        "prefix": payload["prefix"],
    }


def remote_registered_worktrees(production: Path) -> dict[str, Any]:
    lines = remote_git(production, "worktree", "list", "--porcelain").stdout.splitlines()
    return {"count": sum(line.startswith("worktree ") for line in lines), "sha256": canonical_sha256(lines)}


def remote_json_file_evidence(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        return {"path": str(path.resolve(strict=False)), "exists": False, "sha256": None, "payload": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "path": str(path.resolve()), "exists": True,
            "sha256": remote_file_sha256(path), "payload": None, "error": str(exc),
        }
    return {
        "path": str(path.resolve()), "exists": True,
        "sha256": remote_file_sha256(path), "payload": payload,
    }


def remote_firmware_readiness(evidence: Mapping[str, Any]) -> dict[str, Any]:
    payload = evidence.get("payload")
    if (
        not evidence.get("exists")
        or not isinstance(payload, dict)
        or payload.get("schema_name") != "labcraft.firmware_state"
        or payload.get("schema_version") != 1
        or payload.get("role") not in {
            "released", "development", "unknown", "recovery-required"
        }
        or type(payload.get("state_revision")) is not int
        or payload["state_revision"] < 1
    ):
        raise RehearsalError("Durable firmware state is missing or malformed.")
    role = payload["role"]
    return {
        "role": role,
        "production_ready": role == "released",
        "state_revision": payload["state_revision"],
    }


def remote_collect_invariants(request: Mapping[str, Any]) -> dict[str, Any]:
    production = Path(request["production_repo"]).resolve(strict=False)
    development = Path(request["development_repo"]).resolve(strict=False)
    shared_python = Path(request["shared_python"])
    workflow = Path(request["workflow_config"])
    firmware = Path(request["firmware_state_path"])
    prod_state = remote_worktree(production)
    dev_state = remote_worktree(development)
    if not prod_state.get("valid") or not prod_state.get("clean"):
        raise RehearsalError("Protected production checkout is missing or dirty.")
    if not dev_state.get("valid") or not dev_state.get("clean"):
        raise RehearsalError("Development checkout is missing or dirty.")
    if not shared_python.is_file() or not os.access(shared_python, os.X_OK):
        raise RehearsalError("Shared production Python is missing or not executable.")
    version = remote_run([str(shared_python), "--version"]).stdout.strip()
    pip_check = remote_run([str(shared_python), "-m", "pip", "check"], timeout=120)
    workflow_evidence = remote_json_file_evidence(workflow)
    firmware_evidence = remote_json_file_evidence(firmware)
    if not workflow_evidence["exists"] or not isinstance(workflow_evidence.get("payload"), dict):
        raise RehearsalError("Development workflow binding is missing or malformed.")
    firmware_summary = remote_firmware_readiness(firmware_evidence)
    if not firmware_summary["production_ready"]:
        raise RehearsalError("Firmware state is not released and production-ready.")
    config = workflow_evidence["payload"]
    development_data = Path(str(config.get("development_machine_data_root") or ""))
    if not development_data.is_absolute():
        raise RehearsalError("Development workflow has no absolute machine-data binding.")
    marker_path = development_data / "development_store.json"
    marker = remote_json_file_evidence(marker_path)
    if not isinstance(marker.get("payload"), dict):
        raise RehearsalError("Development store marker is missing or malformed.")
    production_data = Path(str(marker["payload"].get("source_machine_data_root") or ""))
    if not production_data.is_absolute():
        raise RehearsalError("Development marker has no absolute production source root.")
    processes = remote_relevant_processes()
    payload = {
        "production_worktree": prod_state,
        "development_worktree": dev_state,
        "registered_worktrees": remote_registered_worktrees(production),
        "production_machine_data": remote_tree_evidence(production_data),
        "development_machine_data": remote_tree_evidence(development_data),
        "workflow_config_sha256": workflow_evidence["sha256"],
        "firmware_state_sha256": firmware_evidence["sha256"],
        "firmware_role": firmware_summary["role"],
        "firmware_production_ready": firmware_summary["production_ready"],
        "firmware_state_revision": firmware_summary["state_revision"],
        "shared_python": str(shared_python.resolve()),
        "shared_python_version": version,
        "pip_check": pip_check.stdout.strip(),
        "shared_environment": remote_environment_inventory(shared_python),
        "production_dependencies": remote_dependency_inventory(production),
        "development_dependencies": remote_dependency_inventory(development),
        "processes": processes,
    }
    payload["sha256"] = canonical_sha256(payload)
    return payload


def remote_require_no_processes(invariants: Mapping[str, Any]) -> None:
    if invariants.get("processes"):
        raise RehearsalError("A conflicting LabCraft, updater, DFU, or HIL process is running.")


def remote_reject_link_ancestors(path: Path) -> None:
    requested = Path(os.path.abspath(str(Path(path).expanduser())))
    for candidate in reversed((requested, *requested.parents)):
        if candidate.is_symlink():
            raise RehearsalError(f"Path contains a symbolic-link ancestor: {candidate}")


def remote_require_external_rehearsal_paths(
    root: Path,
    invariants: Mapping[str, Any],
    *,
    source: Path | None = None,
) -> None:
    protected = [
        Path(invariants["production_machine_data"]["path"]),
        Path(invariants["development_machine_data"]["path"]),
    ]
    for path in protected:
        if root == path or root in path.parents or path in root.parents:
            raise RehearsalError("Rehearsal root overlaps protected machine data.")
        if source is not None and (
            source == path or source in path.parents or path in source.parents
        ):
            raise RehearsalError("Source wrapper overlaps an active machine-data store.")


def remote_validate_root(request: Mapping[str, Any]) -> Path:
    required = (
        "pi_user",
        "production_repo",
        "development_repo",
        "shared_python",
        "workflow_config",
        "firmware_state_path",
        "remote_root",
        "public_remote_url",
        "harness_commit",
    )
    if any(not isinstance(request.get(name), str) or not request[name] for name in required):
        raise RehearsalError("Remote request is missing a required binding.")
    if request["pi_user"] != getpass.getuser():
        raise RehearsalError("Remote request user differs from the active Pi user.")
    if request["public_remote_url"] != PUBLIC_REMOTE_URL:
        raise RehearsalError("Remote request uses an unauthorized public repository.")
    if not re.fullmatch(r"[0-9a-f]{40}", request["harness_commit"]):
        raise RehearsalError("Remote request harness commit is invalid.")
    validate_remote_paths(
        pi_user=request["pi_user"],
        production_repo=request["production_repo"],
        development_repo=request["development_repo"],
        shared_python=request["shared_python"],
        workflow_config=request["workflow_config"],
        firmware_state_path=request["firmware_state_path"],
        remote_root=request["remote_root"],
    )
    root = Path(request["remote_root"]).expanduser()
    if not root.is_absolute() or ".." in root.parts:
        raise RehearsalError("Rehearsal root must be an absolute path without '..'.")
    remote_reject_link_ancestors(root)
    resolved = root.resolve(strict=False)
    broad = {Path("/"), Path(f"/home/{os.environ.get('USER', 'labcraft')}").resolve(strict=False)}
    if resolved in broad:
        raise RehearsalError("Rehearsal root cannot be a filesystem or user-home root.")
    for raw in (request["production_repo"], request["development_repo"]):
        worktree = Path(raw).resolve(strict=False)
        if resolved == worktree or resolved in worktree.parents or worktree in resolved.parents:
            raise RehearsalError("Rehearsal root overlaps a protected worktree.")
    if root.exists() and root.is_symlink():
        raise RehearsalError("Rehearsal root cannot be a symbolic link.")
    return resolved


def remote_state_path(root: Path, run_id: str) -> Path:
    try:
        canonical = str(UUID(run_id))
    except ValueError as exc:
        raise RehearsalError("Run ID is invalid.") from exc
    return root / canonical / "state.json"


def remote_load_state(
    root: Path, run_id: str, *, allow_failed: bool = False
) -> dict[str, Any]:
    path = remote_state_path(root, run_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RehearsalError(f"Cannot read rehearsal state: {exc}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_name") != STATE_SCHEMA
        or payload.get("schema_version") != STATE_SCHEMA_VERSION
        or payload.get("run_id") != str(UUID(run_id))
        or payload.get("stage") not in STAGES
    ):
        raise RehearsalError("Rehearsal state schema or identity is invalid.")
    stage = str(payload["stage"])
    expected_revision = STAGES.index(stage)
    expected_action = {
        "prepared": "prepare",
        "updated": "update",
        "cancellation_passed": "cancel",
        "activated": "activate",
        "verified": "verify",
    }[stage]
    if (
        type(payload.get("revision")) is not int
        or payload["revision"] != expected_revision
        or payload.get("last_action") != expected_action
    ):
        raise RehearsalError("Rehearsal state revision or action sequence is invalid.")
    receipt_path = (
        path.parent / "receipts" / f"{expected_revision:03d}_{expected_action}.json"
    )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RehearsalError("Current rehearsal state has no valid action receipt.") from exc
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_name") != "labcraft.pi_upgrade_rehearsal_receipt"
        or receipt.get("schema_version") != 1
        or receipt.get("run_id") != payload["run_id"]
        or receipt.get("revision") != expected_revision
        or receipt.get("action") != expected_action
        or receipt.get("stage") != stage
    ):
        raise RehearsalError("Current rehearsal action receipt does not match state.")
    failure_root = path.parent / "failures"
    if not allow_failed and failure_root.is_dir() and any(failure_root.iterdir()):
        raise RehearsalError(
            "This rehearsal has a failure receipt and cannot be reused. Prepare a new run ID."
        )
    return payload


def remote_write_receipt(run_root: Path, state: Mapping[str, Any], action: str, details: Mapping[str, Any]) -> Path:
    revision = int(state["revision"])
    path = run_root / "receipts" / f"{revision:03d}_{action}.json"
    if path.exists():
        raise RehearsalError("Action receipt already exists.")
    payload = {
        "schema_name": "labcraft.pi_upgrade_rehearsal_receipt",
        "schema_version": 1,
        "run_id": state["run_id"],
        "revision": revision,
        "action": action,
        "stage": state["stage"],
        "recorded_at_utc": utc_now(),
        "details": dict(details),
    }
    _remote_atomic_json(path, payload)
    return path


def _remote_atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(dict(payload), handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def remote_advance_state(
    run_root: Path,
    state: dict[str, Any],
    *,
    action: str,
    stage: str,
    details: Mapping[str, Any],
) -> dict[str, Any]:
    if stage not in STAGES:
        raise RehearsalError("Invalid rehearsal stage transition.")
    updated = dict(state)
    updated["revision"] = int(state["revision"]) + 1
    updated["stage"] = stage
    updated["updated_at_utc"] = utc_now()
    updated["last_action"] = action
    remote_write_receipt(run_root, updated, action, details)
    _remote_atomic_json(run_root / "state.json", updated)
    return updated


def remote_public_tag(remote_url: str, tag: str) -> dict[str, str]:
    completed = remote_run(
        ["git", "ls-remote", "--tags", remote_url, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
        timeout=120,
    )
    refs = {}
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2:
            refs[fields[1]] = fields[0]
    direct = refs.get(f"refs/tags/{tag}")
    peeled = refs.get(f"refs/tags/{tag}^{{}}")
    if not direct or not peeled or direct == peeled:
        raise RehearsalError(f"Public release {tag} is missing or not annotated.")
    return {"tag": tag, "tag_object": direct, "commit": peeled}


def remote_require_public_release_pair(
    source_release: Mapping[str, str],
    target_release: Mapping[str, str],
    public_source: Mapping[str, str],
    public_target: Mapping[str, str],
) -> None:
    if dict(public_source) != dict(source_release) or dict(public_target) != dict(target_release):
        raise RehearsalError("Public tag evidence differs from the Windows tag evidence.")


def remote_validate_source_wrapper(wrapper: Path, expected_version: str) -> dict[str, Any]:
    if not wrapper.is_dir() or wrapper.is_symlink():
        raise RehearsalError("Source wrapper is missing or linked.")
    version_path = wrapper / "VERSION"
    local = wrapper / "local"
    if not version_path.is_file() or not local.is_dir():
        raise RehearsalError("Source wrapper must contain VERSION and local/.")
    declared = version_path.read_text(encoding="utf-8").strip()
    if declared != expected_version:
        raise RehearsalError(
            f"Source wrapper VERSION is {declared!r}, expected {expected_version!r}."
        )
    for name in ("Locations.json", "Obstacles.json", "Plates.json", "RegulatorProfiles.json", "Settings.json"):
        path = local / name
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RehearsalError(f"Required source configuration is invalid: {name}: {exc}") from exc
        if not isinstance(payload, (dict, list)):
            raise RehearsalError(f"Required source configuration has the wrong type: {name}")
    return remote_tree_evidence(wrapper)


def remote_copy_tree(source: Path, target: Path) -> dict[str, Any]:
    if target.exists():
        raise RehearsalError(f"Owned copy destination already exists: {target}")
    shutil.copytree(source, target, symlinks=False)
    for candidate in sorted(target.rglob("*")):
        if candidate.is_dir():
            os.chmod(candidate, 0o700)
        elif candidate.is_file():
            os.chmod(candidate, 0o600)
    os.chmod(target, 0o700)
    evidence = remote_tree_evidence(target)
    return evidence


def remote_sanitized(state: Mapping[str, Any], *, report_path: Path | None = None) -> dict[str, Any]:
    payload = {
        "status": "passed",
        "run_id": state["run_id"],
        "stage": state["stage"],
        "revision": state["revision"],
        "source_release": state["source_release"],
        "source_commit": state["source_commit"],
        "target_release": state["target_release"],
        "target_commit": state["target_commit"],
        "source_file_count": state["source_tree"]["file_count"],
        "source_total_size": state["source_tree"]["total_size"],
        "source_tree_sha256": state["source_tree"]["tree_sha256"],
        "protected_invariants_sha256": state["protected_invariants_sha256"],
    }
    if report_path is not None:
        payload["pi_report_path"] = str(report_path)
        payload["pi_report_sha256"] = remote_file_sha256(report_path)
    return payload


def remote_require_stage(state: Mapping[str, Any], expected: str) -> None:
    if state.get("stage") != expected:
        raise RehearsalError(
            f"Action requires stage {expected}, found {state.get('stage')}."
        )


def remote_require_invariants(
    request: Mapping[str, Any], state: Mapping[str, Any]
) -> dict[str, Any]:
    if request.get("harness_commit") != state.get("harness_commit"):
        raise RehearsalError("Windows harness commit differs from the prepared run.")
    requested_runner = request.get("bootstrap_runner_sha256")
    if requested_runner is not None and requested_runner != state.get("bootstrap_runner_sha256"):
        raise RehearsalError("Bootstrap runner differs from the prepared run.")
    current = remote_collect_invariants(request)
    remote_require_no_processes(current)
    if current["sha256"] != state["protected_invariants_sha256"]:
        raise RehearsalError("Protected production/development invariants changed.")
    return current


def remote_action_prepare(request: Mapping[str, Any], root: Path) -> dict[str, Any]:
    source_release = request["source_release"]
    target_release = request["target_release"]
    source_tag = validate_tag(source_release["tag"], "Source release")
    target_tag = validate_tag(target_release["tag"], "Target release")
    source_path = Path(request["source_wrapper"]).expanduser()
    if not source_path.is_absolute() or ".." in source_path.parts:
        raise RehearsalError("Source wrapper must be an absolute path without '..'.")
    remote_reject_link_ancestors(source_path)
    source_path = source_path.resolve(strict=True)
    for worktree_raw in (request["production_repo"], request["development_repo"]):
        worktree = Path(worktree_raw).resolve(strict=False)
        if source_path == worktree or source_path in worktree.parents or worktree in source_path.parents:
            raise RehearsalError("Source wrapper cannot overlap a Git worktree.")
    if source_path == root or source_path in root.parents or root in source_path.parents:
        raise RehearsalError("Source wrapper and rehearsal parent must be disjoint.")

    before = remote_collect_invariants(request)
    remote_require_no_processes(before)
    remote_require_external_rehearsal_paths(root, before, source=source_path)
    source_before = remote_validate_source_wrapper(source_path, source_tag)
    public_source = remote_public_tag(request["public_remote_url"], source_tag)
    public_target = remote_public_tag(request["public_remote_url"], target_tag)
    remote_require_public_release_pair(
        source_release, target_release, public_source, public_target
    )

    try:
        run_id = str(UUID(str(request["run_id"])))
    except (KeyError, ValueError) as exc:
        raise RehearsalError("Prepare request has no valid run ID.") from exc
    run_root = root / run_id
    run_root.mkdir(parents=True, exist_ok=False, mode=0o700)
    evidence_root = run_root / "evidence"
    evidence_root.mkdir(mode=0o700)
    private_source = run_root / "source-wrapper"
    source_copy = remote_copy_tree(source_path, private_source)
    if source_copy["tree_sha256"] != source_before["tree_sha256"]:
        raise RehearsalError("Owned source copy differs from the supplied wrapper.")

    clone = run_root / "legacy-checkout"
    remote_run(
        ["git", "clone", "--no-tags", "--no-checkout", request["public_remote_url"], str(clone)],
        timeout=int(request["timeout_seconds"]),
    )
    remote_git(
        clone, "fetch", "--no-tags", "origin",
        f"refs/tags/{source_tag}:refs/tags/{source_tag}",
    )
    if remote_git(clone, "cat-file", "-t", f"refs/tags/{source_tag}").stdout.strip() != "tag":
        raise RehearsalError("Fetched source release is not an annotated tag.")
    fetched_source = remote_git(clone, "rev-parse", f"{source_tag}^{{commit}}").stdout.strip()
    if fetched_source != source_release["commit"]:
        raise RehearsalError("Fetched source commit differs from its bound release.")
    branch = f"rehearsal-{run_id}"
    remote_git(clone, "switch", "-c", branch, fetched_source)
    remote_git(clone, "branch", "--set-upstream-to=origin/main", branch)
    target_absent = remote_git(
        clone, "show-ref", "--verify", f"refs/tags/{target_tag}", allowed=(0, 1)
    )
    if target_absent.returncode == 0:
        raise RehearsalError("Target tag was unexpectedly present before the legacy update.")
    if (clone / "VERSION").read_text(encoding="utf-8").strip() != source_tag:
        raise RehearsalError("Legacy checkout VERSION differs from its source tag.")
    remote_copy_tree(private_source / "local", clone / "local")
    local_copy = remote_tree_evidence(clone / "local")
    private_local = remote_tree_evidence(private_source / "local")
    if local_copy["tree_sha256"] != private_local["tree_sha256"]:
        raise RehearsalError("Checkout-local source differs from the immutable copy.")
    clone_state = remote_worktree(clone)
    if not clone_state.get("valid") or not clone_state.get("clean") or clone_state.get("branch") != branch:
        raise RehearsalError("Prepared legacy checkout is not clean on its tracking branch.")
    upstream = remote_git(
        clone, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
    ).stdout.strip()
    if upstream != "origin/main":
        raise RehearsalError("Prepared legacy checkout does not track origin/main.")
    source_dependencies = remote_dependency_inventory(clone)
    if source_dependencies["sha256"] != before["production_dependencies"]["sha256"]:
        raise RehearsalError("Legacy dependency declarations differ from the shared environment.")

    after = remote_collect_invariants(request)
    remote_require_no_processes(after)
    if after["sha256"] != before["sha256"]:
        raise RehearsalError("Protected invariants changed while preparing the rehearsal.")
    _remote_atomic_json(evidence_root / "protected-preflight.json", before)
    state = {
        "schema_name": STATE_SCHEMA,
        "schema_version": STATE_SCHEMA_VERSION,
        "run_id": run_id,
        "revision": 0,
        "stage": "prepared",
        "created_at_utc": utc_now(),
        "updated_at_utc": utc_now(),
        "last_action": "prepare",
        "harness_commit": request["harness_commit"],
        "bootstrap_runner_sha256": request["bootstrap_runner_sha256"],
        "operator": request["operator"],
        "expected_machine_id": request["expected_machine_id"],
        "source_release": source_tag,
        "source_tag_object": source_release["tag_object"],
        "source_commit": source_release["commit"],
        "target_release": target_tag,
        "target_tag_object": target_release["tag_object"],
        "target_commit": target_release["commit"],
        "public_remote_url": request["public_remote_url"],
        "branch": branch,
        "source_tree": source_copy,
        "source_local_tree": private_local,
        "checkout_local_tree": local_copy,
        "source_dependencies": source_dependencies,
        "protected_invariants_sha256": before["sha256"],
    }
    remote_write_receipt(
        run_root,
        state,
        "prepare",
        {
            "source_copy_verified": True,
            "target_tag_absent": True,
            "checkout_clean": True,
            "protected_invariants_unchanged": True,
        },
    )
    _remote_atomic_json(run_root / "state.json", state)
    return remote_sanitized(state, report_path=run_root / "receipts" / "000_prepare.json")


def remote_action_status(request: Mapping[str, Any], root: Path) -> dict[str, Any]:
    state = remote_load_state(root, request["run_ids"][0], allow_failed=True)
    current = remote_collect_invariants(request)
    failure_root = root / state["run_id"] / "failures"
    failure_count = (
        sum(1 for path in failure_root.iterdir() if path.is_file())
        if failure_root.is_dir()
        else 0
    )
    result = remote_sanitized(state)
    result.update(
        {
            "protected_invariants_match": current["sha256"] == state["protected_invariants_sha256"],
            "related_process_count": len(current["processes"]),
            "failure_receipt_count": failure_count,
            "reusable": failure_count == 0 and state["stage"] != "verified",
        }
    )
    return result


def remote_action_update(request: Mapping[str, Any], root: Path) -> dict[str, Any]:
    state = remote_load_state(root, request["run_ids"][0])
    remote_require_stage(state, "prepared")
    remote_require_invariants(request, state)
    run_root = root / state["run_id"]
    clone = run_root / "legacy-checkout"
    private_source = run_root / "source-wrapper"
    if remote_tree_evidence(private_source)["tree_sha256"] != state["source_tree"]["tree_sha256"]:
        raise RehearsalError("Immutable source wrapper changed before update.")
    if remote_tree_evidence(clone / "local")["tree_sha256"] != state["checkout_local_tree"]["tree_sha256"]:
        raise RehearsalError("Checkout-local legacy source changed before update.")
    clone_state = remote_worktree(clone)
    if (
        not clone_state.get("clean")
        or clone_state.get("head") != state["source_commit"]
        or clone_state.get("branch") != state["branch"]
    ):
        raise RehearsalError("Legacy checkout no longer matches the prepared source state.")
    if remote_git(clone, "show-ref", "--verify", f"refs/tags/{state['target_release']}", allowed=(0, 1)).returncode == 0:
        raise RehearsalError("Target tag appeared before the legacy updater ran.")

    evidence = run_root / "evidence"
    update_result = evidence / "legacy-update-result.json"
    update_log = evidence / "legacy-update.log"
    command = remote_update_command(
        request,
        state,
        clone=clone,
        result_path=update_result,
        log_path=update_log,
    )
    completed = remote_run_owned(
        command,
        cwd=clone,
        timeout=int(request["timeout_seconds"]),
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    (evidence / "legacy-update-stdout.log").write_text(
        completed.stdout + completed.stderr, encoding="utf-8"
    )
    final = remote_worktree(clone)
    if (
        not final.get("valid")
        or not final.get("clean")
        or final.get("head") != state["target_commit"]
        or final.get("branch") != state["branch"]
    ):
        raise RehearsalError("Legacy updater did not finish at the exact clean target commit.")
    if (clone / "VERSION").read_text(encoding="utf-8").strip() != state["target_release"]:
        raise RehearsalError("Updated checkout VERSION differs from the target release.")
    final_upstream = remote_git(
        clone, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
    ).stdout.strip()
    if final_upstream != "origin/main":
        raise RehearsalError("Updated rehearsal branch no longer tracks origin/main.")
    if remote_git(clone, "cat-file", "-t", f"refs/tags/{state['target_release']}").stdout.strip() != "tag":
        raise RehearsalError("Updater did not fetch the annotated target tag.")
    if remote_git(clone, "rev-parse", f"{state['target_release']}^{{commit}}").stdout.strip() != state["target_commit"]:
        raise RehearsalError("Fetched target tag points to the wrong commit.")
    if remote_git(clone, "merge-base", "--is-ancestor", state["source_commit"], state["target_commit"], allowed=(0, 1)).returncode != 0:
        raise RehearsalError("Updated checkout did not prove source-to-target ancestry.")
    try:
        release_manifest = json.loads(
            (clone / "releases" / f"{state['target_release']}.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RehearsalError("Updated target release manifest is missing or malformed.") from exc
    if (
        release_manifest.get("version") != state["target_release"]
        or release_manifest.get("tag") != state["target_release"]
        or release_manifest.get("machine_data", {}).get("preservation_contract")
        != "labcraft.machine_data_update.v1"
    ):
        raise RehearsalError("Updated target release metadata differs from the request.")
    result_payload = json.loads(update_result.read_text(encoding="utf-8"))
    if (
        result_payload.get("status") != "updated"
        or result_payload.get("target_release_version") != state["target_release"]
        or result_payload.get("after_sha") != state["target_commit"]
    ):
        raise RehearsalError("Legacy updater result does not bind the requested target.")
    if remote_tree_evidence(private_source)["tree_sha256"] != state["source_tree"]["tree_sha256"]:
        raise RehearsalError("Immutable source wrapper changed during update.")
    if remote_tree_evidence(clone / "local")["tree_sha256"] != state["checkout_local_tree"]["tree_sha256"]:
        raise RehearsalError("Legacy checkout local/ changed during update.")
    target_dependencies = remote_dependency_inventory(clone)
    baseline = json.loads((evidence / "protected-preflight.json").read_text(encoding="utf-8"))
    if target_dependencies["sha256"] != baseline["production_dependencies"]["sha256"]:
        raise RehearsalError("Target dependency declarations differ from the shared environment.")
    remote_require_invariants(request, state)
    updated = remote_advance_state(
        run_root,
        state,
        action="update",
        stage="updated",
        details={
            "legacy_updater_exit_code": completed.returncode,
            "target_commit_verified": True,
            "legacy_source_unchanged": True,
            "update_result_sha256": remote_file_sha256(update_result),
            "update_log_sha256": remote_file_sha256(update_log),
        },
    )
    return remote_sanitized(updated, report_path=run_root / "receipts" / "001_update.json")


def remote_update_command(
    request: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    clone: Path,
    result_path: Path,
    log_path: Path,
) -> list[str]:
    return [
        str(request["shared_python"]),
        str(clone / "tools" / "update_and_restart.py"),
        "--repo-root", str(clone),
        "--target-release", str(state["target_release"]),
        "--no-relaunch",
        "--record-result",
        "--latest-result-path", str(result_path),
        "--log-path", str(log_path),
    ]


def remote_desktop_environment() -> dict[str, str]:
    runtime = Path(f"/run/user/{os.getuid()}")
    environment = {
        "XDG_RUNTIME_DIR": str(runtime),
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus",
    }
    wayland = [
        path for path in sorted(runtime.glob("wayland-*"))
        if not path.name.endswith(".lock")
    ] if runtime.is_dir() else []
    if wayland:
        environment.update(
            {"WAYLAND_DISPLAY": wayland[0].name, "DISPLAY": ":0", "QT_QPA_PLATFORM": "wayland;xcb"}
        )
    elif Path("/tmp/.X11-unix/X0").exists():
        environment.update({"DISPLAY": ":0", "QT_QPA_PLATFORM": "xcb"})
    else:
        raise RehearsalError("No active Pi desktop session is available.")
    return environment


def remote_stop_owned_group(process: subprocess.Popen, grace_seconds: float = 8.0) -> list[str]:
    actions: list[str] = []
    if process.poll() is not None:
        return actions
    for name, value in (("SIGINT", signal.SIGINT), ("SIGTERM", signal.SIGTERM), ("SIGKILL", signal.SIGKILL)):
        try:
            os.killpg(process.pid, value)
            actions.append(name)
        except ProcessLookupError:
            break
        try:
            process.wait(timeout=grace_seconds)
            break
        except subprocess.TimeoutExpired:
            continue
    return actions


def remote_install_bootstrap_runner(request: Mapping[str, Any], run_root: Path) -> Path:
    try:
        data = base64.b64decode(request["bootstrap_runner_b64"], validate=True)
    except Exception as exc:
        raise RehearsalError("Bootstrap runner upload is malformed.") from exc
    digest = hashlib.sha256(data).hexdigest()
    if digest != request["bootstrap_runner_sha256"]:
        raise RehearsalError("Bootstrap runner upload hash mismatch.")
    harness = run_root / "harness"
    harness.mkdir(exist_ok=True, mode=0o700)
    target = harness / "run_machine_data_bootstrap_only.py"
    if target.exists():
        if remote_file_sha256(target) != digest:
            raise RehearsalError("Existing bootstrap harness differs from the requested bytes.")
    else:
        with target.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(target, 0o700)
    return target


def remote_launch_bootstrap(
    request: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    expected_outcome: str,
    machine_data_root: Path,
    result_path: Path,
    log_path: Path,
    visible: bool,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    run_root = Path(request["remote_root"]).resolve() / state["run_id"]
    runner = remote_install_bootstrap_runner(request, run_root)
    target_repo = (repo_root or (run_root / "legacy-checkout")).resolve()
    result_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    command = [
        request["shared_python"], "-u", str(runner),
        "--repo-root", str(target_repo),
        "--source-wrapper", str(run_root / "source-wrapper"),
        "--machine-data-root", str(machine_data_root),
        "--expected-version", state["target_release"],
        "--expected-commit", state["target_commit"],
        "--expected-machine-id", state["expected_machine_id"],
        "--operator", request["operator"],
        "--source-reason", f"Exact-tag upgrade rehearsal from {state['source_release']}",
        "--expected-outcome", expected_outcome,
        "--result-path", str(result_path),
    ]
    environment = dict(os.environ)
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "LABCRAFT_MACHINE_DATA_ROOT", "LABCRAFT_DEPLOYMENT_MODE"):
        environment.pop(name, None)
    if visible:
        environment.update(remote_desktop_environment())
    else:
        environment["QT_QPA_PLATFORM"] = "offscreen"
        environment["XDG_RUNTIME_DIR"] = str(run_root / "runtime")
        Path(environment["XDG_RUNTIME_DIR"]).mkdir(exist_ok=True, mode=0o700)
    environment["PYTHONUNBUFFERED"] = "1"
    timed_out = False
    cleanup: list[str] = []
    with log_path.open("xb") as output:
        process = subprocess.Popen(
            command,
            cwd=target_repo,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            exit_code = process.wait(timeout=int(request["timeout_seconds"]))
        except subprocess.TimeoutExpired:
            timed_out = True
            cleanup = remote_stop_owned_group(process)
            exit_code = process.returncode
    if timed_out or exit_code != 0:
        raise RehearsalError(
            f"Bootstrap-only runner failed (exit={exit_code}, timed_out={timed_out}, cleanup={cleanup})."
        )
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RehearsalError(f"Bootstrap-only result is missing or malformed: {exc}") from exc
    if (
        payload.get("schema_name") != "labcraft.bootstrap_only_result"
        or payload.get("schema_version") != 1
        or payload.get("status") != "passed"
        or payload.get("outcome") != expected_outcome
        or payload.get("app_commit") != state["target_commit"]
        or payload.get("app_version") != state["target_release"]
        or payload.get("forbidden_imports") != []
    ):
        raise RehearsalError("Bootstrap-only result does not satisfy its bound outcome.")
    return payload


def remote_action_cancel(request: Mapping[str, Any], root: Path) -> dict[str, Any]:
    state = remote_load_state(root, request["run_ids"][0])
    remote_require_stage(state, "updated")
    remote_require_invariants(request, state)
    run_root = root / state["run_id"]
    attempt = str(uuid4())
    attempt_root = run_root / "cancel-attempts" / attempt
    attempt_root.mkdir(parents=True, exist_ok=False, mode=0o700)
    machine_data = attempt_root / "machine-data"
    result = run_root / "evidence" / f"bootstrap-cancel-{attempt}.json"
    log = run_root / "evidence" / f"bootstrap-cancel-{attempt}.log"
    payload = remote_launch_bootstrap(
        request,
        state,
        expected_outcome="cancelled",
        machine_data_root=machine_data,
        result_path=result,
        log_path=log,
        visible=True,
    )
    if machine_data.exists():
        cancellation_tree = remote_tree_evidence(machine_data)
        if cancellation_tree["file_count"] != 0:
            raise RehearsalError("Cancellation destination contains durable files.")
    remote_require_invariants(request, state)
    updated = remote_advance_state(
        run_root,
        state,
        action="cancel",
        stage="cancellation_passed",
        details={
            "attempt_id": attempt,
            "outcome": payload["outcome"],
            "destination_empty": True,
            "result_sha256": remote_file_sha256(result),
            "log_sha256": remote_file_sha256(log),
        },
    )
    return remote_sanitized(updated, report_path=run_root / "receipts" / "002_cancel.json")


def remote_action_activate(request: Mapping[str, Any], root: Path) -> dict[str, Any]:
    state = remote_load_state(root, request["run_ids"][0])
    remote_require_stage(state, "cancellation_passed")
    remote_require_invariants(request, state)
    run_root = root / state["run_id"]
    activation_parent = run_root / "activation"
    activation_parent.mkdir(exist_ok=True, mode=0o700)
    machine_data = activation_parent / "machine-data"
    if machine_data.exists():
        raise RehearsalError("Activation destination already exists; it cannot be reused.")
    result = run_root / "evidence" / "bootstrap-activation.json"
    log = run_root / "evidence" / "bootstrap-activation.log"
    payload = remote_launch_bootstrap(
        request,
        state,
        expected_outcome="activated",
        machine_data_root=machine_data,
        result_path=result,
        log_path=log,
        visible=True,
    )
    active = payload.get("active_machine")
    if not isinstance(active, dict) or active.get("machine_id") != state["expected_machine_id"]:
        raise RehearsalError("Activated machine identity differs from the bound rehearsal identity.")
    remote_require_invariants(request, state)
    updated = remote_advance_state(
        run_root,
        state,
        action="activate",
        stage="activated",
        details={
            "outcome": payload["outcome"],
            "machine_uuid": active["machine_uuid"],
            "activation_id": active["activation_id"],
            "migration_id": active["migration_id"],
            "result_sha256": remote_file_sha256(result),
            "log_sha256": remote_file_sha256(log),
        },
    )
    return remote_sanitized(updated, report_path=run_root / "receipts" / "003_activate.json")


def _canonical_json_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def remote_compare_migration(run_root: Path, state: Mapping[str, Any]) -> dict[str, Any]:
    source_local = run_root / "source-wrapper" / "local"
    machine_data = run_root / "activation" / "machine-data"
    active_path = machine_data / "active_machine.json"
    try:
        active = json.loads(active_path.read_text(encoding="utf-8"))
        machine_uuid = str(UUID(str(active["machine_uuid"])))
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise RehearsalError(f"Activated pointer is invalid: {exc}") from exc
    machine_root = machine_data / "machines" / machine_uuid
    metadata = machine_root / "metadata"
    required_evidence = (
        "machine_identity.json",
        "candidate_evidence.json",
        "migration_receipt.json",
        "migration_tree_manifest.json",
        "verification.json",
        "activation_receipt.json",
        "deployment_anchor.json",
    )
    evidence_hashes = {}
    for name in required_evidence:
        path = metadata / name
        if name == "deployment_anchor.json":
            path = machine_root / "update_history" / name
        if not path.is_file():
            raise RehearsalError(f"Required activated evidence is missing: {name}")
        evidence_hashes[name] = remote_file_sha256(path)
    candidate = json.loads((metadata / "candidate_evidence.json").read_text(encoding="utf-8"))
    migrated = candidate.get("migratable_files")
    if not isinstance(migrated, list) or not migrated:
        raise RehearsalError("Candidate evidence has no migratable inventory.")
    compared = []
    for item in migrated:
        if not isinstance(item, dict) or not isinstance(item.get("relative_path"), str):
            raise RehearsalError("Candidate migratable inventory is malformed.")
        canonical = item["relative_path"]
        if canonical.startswith("config/"):
            source_relative = canonical.removeprefix("config/")
        elif canonical.startswith("CalibrationMemory/"):
            source_relative = canonical
        elif canonical == "calibration/droplet_imager_optics.json":
            source_relative = "droplet_imager_optics.json"
        elif canonical.startswith("calibration/regulator_optimization/"):
            source_relative = canonical.removeprefix("calibration/")
        else:
            raise RehearsalError(f"Unknown canonical migration path: {canonical}")
        source = source_local / source_relative
        destination = machine_root / canonical
        if not source.is_file() or not destination.is_file():
            raise RehearsalError(f"Migrated member is missing: {canonical}")
        source_hash = remote_file_sha256(source)
        destination_hash = remote_file_sha256(destination)
        if source_hash != destination_hash or source_hash != item.get("raw_sha256"):
            raise RehearsalError(f"Migrated member differs from source: {canonical}")
        compared.append(canonical)
    semantic_hashes = {}
    for name in ("Locations.json", "Obstacles.json", "Plates.json", "RegulatorProfiles.json", "Settings.json"):
        source_payload = json.loads((source_local / name).read_text(encoding="utf-8"))
        destination_payload = json.loads((machine_root / "config" / name).read_text(encoding="utf-8"))
        source_semantic = _canonical_json_hash(source_payload)
        destination_semantic = _canonical_json_hash(destination_payload)
        if source_semantic != destination_semantic:
            raise RehearsalError(f"Migrated configuration semantics differ: {name}")
        semantic_hashes[name] = source_semantic
    locations = json.loads((machine_root / "config" / "Locations.json").read_text(encoding="utf-8"))
    plates = json.loads((machine_root / "config" / "Plates.json").read_text(encoding="utf-8"))
    if not isinstance(locations, dict):
        raise RehearsalError("Migrated Locations.json is not an object.")
    folded_locations = {str(name).casefold(): value for name, value in locations.items()}
    if len(folded_locations) != len(locations):
        raise RehearsalError("Migrated location names collide by case.")
    for required in (
        "camera",
        "pause",
        "home",
        "rack_position_left",
        "rack_position_right",
    ):
        value = folded_locations.get(required)
        if not isinstance(value, dict) or set(value) != {"X", "Y", "Z"}:
            raise RehearsalError(f"Required migrated location is missing or malformed: {required}")
    if not isinstance(plates, list):
        raise RehearsalError("Migrated Plates.json is not a list.")
    calibrated_plate_count = 0
    for plate in plates:
        if not isinstance(plate, dict):
            raise RehearsalError("Migrated plate entry is malformed.")
        calibrations = plate.get("calibrations")
        if not calibrations:
            continue
        if not isinstance(calibrations, dict) or set(calibrations) != {
            "top_left", "top_right", "bottom_right", "bottom_left"
        }:
            raise RehearsalError("Migrated plate corners are incomplete.")
        if any(
            not isinstance(point, dict) or set(point) != {"X", "Y", "Z"}
            for point in calibrations.values()
        ):
            raise RehearsalError("Migrated plate corner coordinates are malformed.")
        calibrated_plate_count += 1
    if calibrated_plate_count == 0:
        raise RehearsalError("Migration contains no calibrated plate corners.")
    verification = json.loads((metadata / "verification.json").read_text(encoding="utf-8"))
    targets = verification.get("targets")
    accepted_states = {
        "verified_from_trusted_existing_calibration",
        "verified_against_service_record",
        "verified_by_controlled_calibration",
    }
    if not isinstance(targets, dict) or not targets:
        raise RehearsalError("Migration verification has no target authorizations.")
    states = [target.get("state") for target in targets.values() if isinstance(target, dict)]
    if len(states) != len(targets) or any(value not in accepted_states for value in states):
        raise RehearsalError("Migration left one or more targets unauthorized.")
    ownership = verification.get("ownership_decisions")
    if (
        not isinstance(ownership, list)
        or any(
            not isinstance(item, dict) or item.get("activation_allowed") is not True
            for item in ownership
        )
    ):
        raise RehearsalError("Migration calibration ownership is unresolved.")
    receipt = json.loads((metadata / "migration_receipt.json").read_text(encoding="utf-8"))
    try:
        migration_id = str(UUID(str(receipt["migration_id"])))
        archive_sha256 = str(receipt["backup_archive_sha256"])
    except (KeyError, ValueError) as exc:
        raise RehearsalError("Migration receipt backup binding is malformed.") from exc
    archive = (
        machine_root / "backups" / "migration" / migration_id / "source_backup.zip"
    )
    if (
        not archive.is_file()
        or archive.is_symlink()
        or remote_file_sha256(archive) != archive_sha256
    ):
        raise RehearsalError("Verified migration archive differs from its receipt.")
    deployment = json.loads(
        (machine_root / "update_history" / "deployment_anchor.json").read_text(encoding="utf-8")
    )
    if deployment.get("app_version") != state["target_release"] or deployment.get("app_commit") != state["target_commit"]:
        raise RehearsalError("Deployment anchor does not bind the target release.")
    return {
        "machine_uuid": machine_uuid,
        "migrated_member_count": len(compared),
        "migrated_members_sha256": canonical_sha256(compared),
        "config_semantic_sha256": semantic_hashes,
        "safety_semantic_sha256": canonical_sha256(
            {"locations": locations, "plates": plates}
        ),
        "authorization_count": len(targets),
        "authorization_states": sorted(set(states)),
        "ownership_decision_count": len(ownership),
        "ownership_decisions_sha256": canonical_sha256(ownership),
        "backup_archive_sha256": archive_sha256,
        "calibrated_plate_count": calibrated_plate_count,
        "evidence_sha256": evidence_hashes,
        "machine_tree": remote_tree_evidence(machine_root),
    }


def remote_create_second_checkout(request: Mapping[str, Any], state: Mapping[str, Any]) -> Path:
    run_root = Path(request["remote_root"]).resolve() / state["run_id"]
    checkout = run_root / "target-reopen-checkout"
    if checkout.exists():
        raise RehearsalError("Second target checkout already exists.")
    remote_run(
        ["git", "clone", "--no-tags", "--no-checkout", request["public_remote_url"], str(checkout)],
        timeout=int(request["timeout_seconds"]),
    )
    remote_git(
        checkout, "fetch", "--no-tags", "origin",
        f"refs/tags/{state['target_release']}:refs/tags/{state['target_release']}",
    )
    if remote_git(checkout, "cat-file", "-t", f"refs/tags/{state['target_release']}").stdout.strip() != "tag":
        raise RehearsalError("Second checkout target tag is not annotated.")
    remote_git(checkout, "checkout", "--detach", state["target_commit"])
    checkout_state = remote_worktree(checkout)
    if (
        not checkout_state.get("clean")
        or checkout_state.get("head") != state["target_commit"]
        or checkout_state.get("branch") is not None
    ):
        raise RehearsalError("Second target checkout is not clean and detached at the target.")
    return checkout


def remote_action_verify(request: Mapping[str, Any], root: Path) -> dict[str, Any]:
    state = remote_load_state(root, request["run_ids"][0])
    remote_require_stage(state, "activated")
    remote_require_invariants(request, state)
    run_root = root / state["run_id"]
    machine_data = run_root / "activation" / "machine-data"
    tree_before = remote_tree_evidence(machine_data)
    primary_result = run_root / "evidence" / "bootstrap-ready-primary.json"
    primary_log = run_root / "evidence" / "bootstrap-ready-primary.log"
    primary = remote_launch_bootstrap(
        request,
        state,
        expected_outcome="ready",
        machine_data_root=machine_data,
        result_path=primary_result,
        log_path=primary_log,
        visible=False,
    )
    first_uuid = primary["active_machine"]["machine_uuid"]
    second = remote_create_second_checkout(request, state)
    original = run_root / "legacy-checkout"
    second_result = run_root / "evidence" / "bootstrap-ready-second.json"
    second_log = run_root / "evidence" / "bootstrap-ready-second.log"
    second_payload = remote_launch_bootstrap(
        request,
        state,
        expected_outcome="ready",
        machine_data_root=machine_data,
        result_path=second_result,
        log_path=second_log,
        visible=False,
        repo_root=second,
    )
    if (
        second_payload.get("status") != "passed"
        or second_payload.get("outcome") != "ready"
        or second_payload.get("active_machine", {}).get("machine_uuid") != first_uuid
        or second_payload.get("forbidden_imports") != []
    ):
        raise RehearsalError("Second-checkout reopen did not reuse the same authorized machine.")
    comparison = remote_compare_migration(run_root, state)
    tree_after = remote_tree_evidence(machine_data)
    if tree_after["tree_sha256"] != tree_before["tree_sha256"]:
        raise RehearsalError("Ready reopens changed protected machine-data bytes.")
    if remote_tree_evidence(run_root / "source-wrapper")["tree_sha256"] != state["source_tree"]["tree_sha256"]:
        raise RehearsalError("Immutable source wrapper changed during verification.")
    if remote_tree_evidence(original / "local")["tree_sha256"] != state["checkout_local_tree"]["tree_sha256"]:
        raise RehearsalError("Checkout-local legacy source changed during bootstrap.")
    remote_require_invariants(request, state)
    updated = remote_advance_state(
        run_root,
        state,
        action="verify",
        stage="verified",
        details={
            "primary_reopen_sha256": remote_file_sha256(primary_result),
            "second_reopen_sha256": remote_file_sha256(second_result),
            "machine_uuid": first_uuid,
            "machine_data_unchanged_by_reopen": True,
            "comparison": comparison,
        },
    )
    evidence_tree = remote_tree_evidence(run_root / "evidence")
    receipts_tree = remote_tree_evidence(run_root / "receipts")
    seal = {
        "schema_name": "labcraft.pi_upgrade_rehearsal_seal",
        "schema_version": 1,
        "run_id": updated["run_id"],
        "sealed_at_utc": utc_now(),
        "source_release": updated["source_release"],
        "source_commit": updated["source_commit"],
        "target_release": updated["target_release"],
        "target_commit": updated["target_commit"],
        "source_tree_sha256": updated["source_tree"]["tree_sha256"],
        "machine_tree_sha256": comparison["machine_tree"]["tree_sha256"],
        "safety_semantic_sha256": comparison["safety_semantic_sha256"],
        "protected_invariants_sha256": updated["protected_invariants_sha256"],
        "evidence_tree_sha256": evidence_tree["tree_sha256"],
        "receipts_tree_sha256": receipts_tree["tree_sha256"],
    }
    seal_path = run_root / "seal.json"
    _remote_atomic_json(seal_path, seal)
    return remote_sanitized(updated, report_path=seal_path)


def remote_action_summarize(request: Mapping[str, Any], root: Path) -> dict[str, Any]:
    states = [remote_load_state(root, run_id) for run_id in request["run_ids"]]
    for state in states:
        remote_require_stage(state, "verified")
        remote_require_invariants(request, state)
        if not (root / state["run_id"] / "seal.json").is_file():
            raise RehearsalError("Verified run has no seal.")
    if len({state["source_release"] for state in states}) != 2:
        raise RehearsalError("Campaign sources must be two distinct release tags.")
    if len({(state["target_release"], state["target_commit"]) for state in states}) != 1:
        raise RehearsalError("Campaign runs must share one exact target release.")
    campaign_id = str(uuid4())
    campaign = {
        "schema_name": CAMPAIGN_SCHEMA,
        "schema_version": CAMPAIGN_SCHEMA_VERSION,
        "campaign_id": campaign_id,
        "created_at_utc": utc_now(),
        "target_release": states[0]["target_release"],
        "target_commit": states[0]["target_commit"],
        "runs": [
            {
                "run_id": state["run_id"],
                "source_release": state["source_release"],
                "source_commit": state["source_commit"],
                "source_tree_sha256": state["source_tree"]["tree_sha256"],
                "seal_sha256": remote_file_sha256(root / state["run_id"] / "seal.json"),
            }
            for state in sorted(states, key=lambda item: item["source_release"])
        ],
        "protected_invariants_sha256": states[0]["protected_invariants_sha256"],
        "all_gates_passed": True,
    }
    campaign_path = root / "campaigns" / f"{campaign_id}.json"
    _remote_atomic_json(campaign_path, campaign)
    return {
        "status": "passed",
        "campaign_id": campaign_id,
        "target_release": campaign["target_release"],
        "target_commit": campaign["target_commit"],
        "source_releases": [row["source_release"] for row in campaign["runs"]],
        "run_ids": [row["run_id"] for row in campaign["runs"]],
        "all_gates_passed": True,
        "pi_report_path": str(campaign_path),
        "pi_report_sha256": remote_file_sha256(campaign_path),
    }


def remote_main(encoded: str) -> int:
    request: dict[str, Any] | None = None
    root: Path | None = None
    prepare_run_preexisted = False
    try:
        request = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8"))
        if not isinstance(request, dict):
            raise RehearsalError("Remote request is not an object.")
        root = remote_validate_root(request)
        action = request.get("action")
        actions = {
            "prepare": remote_action_prepare,
            "status": remote_action_status,
            "update": remote_action_update,
            "cancel": remote_action_cancel,
            "activate": remote_action_activate,
            "verify": remote_action_verify,
            "summarize": remote_action_summarize,
        }
        if action not in actions:
            raise RehearsalError("Remote action is unsupported.")
        if action != "prepare" and not root.is_dir():
            raise RehearsalError("Rehearsal parent does not exist.")
        if action == "prepare":
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                prepared_id = str(UUID(str(request.get("run_id"))))
                prepare_run_preexisted = (root / prepared_id).exists()
            except ValueError:
                pass
        payload = actions[action](request, root)
        print(json.dumps(payload, sort_keys=True))
        return 0
    except Exception as exc:
        failure_paths: list[str] = []
        if isinstance(request, dict) and root is not None and request.get("action") in {
            "prepare", "update", "cancel", "activate", "verify"
        }:
            candidate_ids = (
                [request.get("run_id")]
                if request.get("action") == "prepare"
                else list(request.get("run_ids") or ())
            )
            for candidate in candidate_ids:
                try:
                    run_id = str(UUID(str(candidate)))
                    if request.get("action") == "prepare" and prepare_run_preexisted:
                        continue
                    failure = root / run_id / "failures" / (
                        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_"
                        f"{request.get('action')}_{uuid4()}.json"
                    )
                    _remote_atomic_json(
                        failure,
                        {
                            "schema_name": "labcraft.pi_upgrade_rehearsal_failure",
                            "schema_version": 1,
                            "run_id": run_id,
                            "action": request.get("action"),
                            "recorded_at_utc": utc_now(),
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        },
                    )
                    failure_paths.append(str(failure))
                except Exception:
                    pass
        elif (
            isinstance(request, dict)
            and root is not None
            and request.get("action") == "summarize"
        ):
            try:
                failure = root / "campaign-failures" / (
                    f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_"
                    f"summarize_{uuid4()}.json"
                )
                _remote_atomic_json(
                    failure,
                    {
                        "schema_name": "labcraft.pi_upgrade_rehearsal_failure",
                        "schema_version": 1,
                        "run_ids": list(request.get("run_ids") or ()),
                        "action": "summarize",
                        "recorded_at_utc": utc_now(),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                failure_paths.append(str(failure))
            except Exception:
                pass
        action_label = request.get("action") if isinstance(request, dict) else "request"
        response_ids: list[str] = []
        if isinstance(request, dict):
            candidates = (
                [request.get("run_id")]
                if request.get("action") == "prepare"
                else list(request.get("run_ids") or ())
            )
            for candidate in candidates:
                try:
                    response_ids.append(str(UUID(str(candidate))))
                except ValueError:
                    pass
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": (
                        f"Pi rehearsal {action_label} failed. Review the private Pi failure receipt."
                    ),
                    "run_ids": response_ids,
                    "pi_failure_receipts": failure_paths,
                },
                sort_keys=True,
            )
        )
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "--remote":
        if len(arguments) != 2:
            print(json.dumps({"status": "failed", "error": "Remote request is missing."}))
            return 1
        return remote_main(arguments[1])
    return local_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
