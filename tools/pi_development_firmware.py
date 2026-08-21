"""Exact-commit, SAFE-only Pi development firmware round-trip workflow.

The only Slice 5 mutation is a bounded development flash followed immediately
by a prevalidated released-firmware restore. Both stages must pass the strict
plain-SAFE contract. All logs and receipts live outside both Git worktrees.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
from typing import Any, Mapping, Sequence
from uuid import uuid4

import firmware_safe_hil
import pi_development_workflow as workflow


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_NAME = "labcraft.pi_development_firmware_roundtrip"
SCHEMA_VERSION = 1
ARTIFACT_RELATIVE_PATH = "firmware/artifacts/LabCraft_firmware.bin"
DEFAULT_RELEASED_TAG = "v1.3.0-rc.5"
DEFAULT_REMOTE_ROOT = (
    "/home/labcraft/.local/share/LabCraft/LabCraft Printer/"
    "development-workflow/firmware-sessions"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "verification_reports/development-workflow/firmware"
)


class FirmwareWorkflowError(RuntimeError):
    """Raised when the exact, recoverable SAFE lane cannot be proven."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_bytes(repo: Path, revision_path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", revision_path], cwd=repo, capture_output=True, check=False
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise FirmwareWorkflowError(f"Git cannot read {revision_path}: {detail}")
    return completed.stdout


def _git_text(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=repo, capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise FirmwareWorkflowError(
            f"Git command failed: {' '.join(arguments)}: "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    return completed.stdout.strip()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def collect_local_artifact_provenance(
    repo_root: Path, *, head: str, released_tag: str
) -> dict[str, Any]:
    root = repo_root.resolve()
    artifact = root / ARTIFACT_RELATIVE_PATH
    if not artifact.is_file():
        raise FirmwareWorkflowError(f"Development artifact is missing: {artifact}")
    tracked = _git_bytes(root, f"{head}:{ARTIFACT_RELATIVE_PATH}")
    working = artifact.read_bytes()
    if working != tracked:
        raise FirmwareWorkflowError(
            "Working development firmware bytes differ from the exact HEAD artifact."
        )

    tag_commit = _git_text(root, "rev-parse", f"refs/tags/{released_tag}^{{commit}}")
    version = _git_bytes(root, f"{released_tag}:VERSION").decode("utf-8").strip()
    if version != released_tag:
        raise FirmwareWorkflowError(
            f"Released tag VERSION is {version!r}, expected {released_tag!r}."
        )
    manifest_path = f"releases/{released_tag}.json"
    try:
        manifest = json.loads(_git_bytes(root, f"{released_tag}:{manifest_path}"))
    except json.JSONDecodeError as exc:
        raise FirmwareWorkflowError("Released firmware manifest is invalid JSON.") from exc
    required = manifest.get("requires_firmware")
    if (
        manifest.get("schema_version") != "labcraft_release_v1"
        or manifest.get("version") != released_tag
        or manifest.get("tag") != released_tag
        or not isinstance(required, Mapping)
        or required.get("artifact") != ARTIFACT_RELATIVE_PATH
    ):
        raise FirmwareWorkflowError(
            "Released tag manifest does not bind the expected firmware artifact."
        )
    released_bytes = _git_bytes(root, f"{released_tag}:{ARTIFACT_RELATIVE_PATH}")
    return {
        "development": {
            "commit": head,
            "path": str(artifact),
            "relative_path": ARTIFACT_RELATIVE_PATH,
            "sha256": _sha256_bytes(working),
            "size": len(working),
            "tracked_at_head": True,
        },
        "released": {
            "tag": released_tag,
            "tag_commit": tag_commit,
            "version": version,
            "manifest_path": manifest_path,
            "manifest_sha256": _sha256_bytes(
                json.dumps(
                    manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode("utf-8")
            ),
            "artifact_relative_path": ARTIFACT_RELATIVE_PATH,
            "sha256": _sha256_bytes(released_bytes),
            "size": len(released_bytes),
        },
    }


def validate_remote_session_root(
    path: str, *, pi_user: str, production_repo: str, development_repo: str
) -> None:
    session = PurePosixPath(path)
    production = PurePosixPath(production_repo)
    development = PurePosixPath(development_repo)
    if not session.is_absolute() or ".." in session.parts:
        raise FirmwareWorkflowError("Remote firmware session root must be absolute.")
    if (
        session in {PurePosixPath("/"), PurePosixPath(f"/home/{pi_user}")}
        or session in {production, development}
        or production in session.parents
        or development in session.parents
        or session in production.parents
        or session in development.parents
    ):
        raise FirmwareWorkflowError(
            "Remote firmware session root must be external to both worktrees."
        )


REMOTE_FIRMWARE_ROUNDTRIP = r'''
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(args, *, cwd=None, timeout=30, env=None, text=True):
    return subprocess.run(
        list(args), cwd=cwd, capture_output=True, text=text, check=False,
        timeout=timeout, env=env,
    )


def git_text(repo, *args):
    result = run(["git", *args], cwd=repo)
    if result.returncode:
        raise RuntimeError(f"Git failed in {repo}: {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def git_bytes(repo, revision_path):
    result = run(["git", "show", revision_path], cwd=repo, text=False)
    if result.returncode:
        raise RuntimeError(
            f"Git cannot read {revision_path}: {result.stderr.decode(errors='replace').strip()}"
        )
    return result.stdout


def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid4()}.tmp"
    data = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
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


def worktree_state(path):
    return {
        "head": git_text(path, "rev-parse", "HEAD"),
        "branch": git_text(path, "branch", "--show-current") or None,
        "status": git_text(path, "status", "--porcelain=v1", "--untracked-files=all").splitlines(),
    }


def relevant_processes():
    own = os.getpid()
    patterns = (
        "FreeRTOS-interface/App.py", "update_and_restart.py", "dfu_update.py",
        "flash_and_test.sh", "run_selftest.py", "run_fw_hil_windows",
    )
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == own:
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if command and any(pattern in command for pattern in patterns):
            found.append({"pid": int(entry.name), "command": command.strip()})
    return sorted(found, key=lambda item: item["pid"])


def stage_command(request, *, artifact, stage_dir):
    development = Path(request["development_repo"])
    return [
        "bash", str(development / "firmware/hil/flash_and_test.sh"),
        "--bin", str(artifact),
        "--dfu-script", str(development / "FreeRTOS-interface/dfu_update.py"),
        "--port", request["port"],
        "--profile", "SAFE",
        "--mode", "full",
        "--report", str(stage_dir / "safe-report.json"),
        "--log-dir", str(stage_dir),
        "--selftest-timeout-ms", "120000",
        "--progress-timeout-ms", "30000",
        "--activity-timeout-ms", "120000",
        "--status-only-timeout-ms", "10000",
    ]


def run_stage(request, *, role, artifact, session):
    stage_dir = session / role
    stage_dir.mkdir(parents=True, exist_ok=False)
    command = stage_command(request, artifact=artifact, stage_dir=stage_dir)
    if "FULL" in command or any("selector" in item or "camera" in item for item in command):
        raise RuntimeError("Internal refusal: generated command is not plain SAFE.")
    env = dict(os.environ)
    env["PATH"] = str(Path(request["shared_python"]).parent) + os.pathsep + env.get("PATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    started = now()
    result = run(
        command, cwd=Path(request["development_repo"]), timeout=300, env=env
    )
    log_path = stage_dir / "supervisor-output.log"
    log_path.write_text(result.stdout + result.stderr, encoding="utf-8", newline="\n")
    validation_result = run(
        [
            request["shared_python"],
            str(Path(request["development_repo"]) / "tools/firmware_safe_hil.py"),
            "--report", str(stage_dir / "safe-report.json"),
        ],
        cwd=Path(request["development_repo"]), timeout=30, env=env,
    )
    validation = None
    if validation_result.returncode == 0:
        validation = json.loads(validation_result.stdout)
    return {
        "role": role,
        "status": "passed" if result.returncode == 0 and validation is not None else "failed",
        "started_at_utc": started,
        "completed_at_utc": now(),
        "artifact_path": str(artifact),
        "artifact_sha256": sha_file(artifact),
        "command": command,
        "exit_code": result.returncode,
        "log_path": str(log_path),
        "log_sha256": sha_file(log_path),
        "safe_validation": validation,
        "safe_validation_error": None if validation is not None else validation_result.stdout.strip(),
    }


def main():
    request = json.loads(base64.urlsafe_b64decode(sys.argv[1]).decode("utf-8"))
    production = Path(request["production_repo"]).resolve()
    development = Path(request["development_repo"]).resolve()
    shared_python = Path(request["shared_python"]).resolve()
    workflow_config = Path(request["workflow_config"]).resolve()
    remote_root = Path(request["remote_session_root"]).resolve()
    session_id = str(uuid4())
    session = remote_root / session_id
    session.mkdir(parents=True, exist_ok=False)
    report_path = session / "roundtrip.json"
    report = {
        "schema_name": "labcraft.pi_development_firmware_remote_roundtrip",
        "schema_version": 1,
        "transaction_id": session_id,
        "operator": request["operator"],
        "started_at_utc": now(),
        "session_path": str(session),
        "status": "preflight",
        "stages": [],
    }
    try:
        if not production.is_dir() or not development.is_dir():
            raise RuntimeError("Both protected and development worktrees must exist.")
        production_state = worktree_state(production)
        development_state = worktree_state(development)
        if production_state["head"] != request["expected_production_head"]:
            raise RuntimeError("Protected production HEAD changed before firmware qualification.")
        if production_state["branch"] != request["expected_production_branch"] or production_state["status"]:
            raise RuntimeError("Protected production worktree is not clean on the expected branch.")
        if development_state != {
            "head": request["expected_commit"], "branch": None, "status": []
        }:
            raise RuntimeError("Development worktree is not clean/detached at the exact commit.")
        if relevant_processes():
            raise RuntimeError("A conflicting app, updater, DFU, or HIL process is running.")
        if not shared_python.is_file() or not os.access(shared_python, os.X_OK):
            raise RuntimeError("Shared production interpreter is unavailable.")
        if not workflow_config.is_file():
            raise RuntimeError("Persisted development workflow configuration changed.")
        workflow_payload = json.loads(workflow_config.read_text(encoding="utf-8"))
        workflow_canonical_sha256 = sha_bytes(
            json.dumps(workflow_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        )
        if workflow_canonical_sha256 != request["workflow_config_canonical_sha256"]:
            raise RuntimeError("Persisted development workflow configuration changed.")
        if not Path(request["port"]).exists():
            raise RuntimeError("Configured SAFE serial port is unavailable.")
        if run(["which", "dfu-util"]).returncode != 0:
            raise RuntimeError("dfu-util recovery command is unavailable.")

        source_validation = run(
            [request["shared_python"], str(development / "tools/firmware_safe_hil.py"),
             "--source-root", str(development)],
            cwd=development,
        )
        if source_validation.returncode:
            raise RuntimeError(f"SAFE source contract failed: {source_validation.stdout.strip()}")
        report["safe_source_contract"] = json.loads(source_validation.stdout)

        dev_artifact = development / request["artifact_relative_path"]
        dev_tracked = git_bytes(development, f'{request["expected_commit"]}:{request["artifact_relative_path"]}')
        if not dev_artifact.is_file() or dev_artifact.read_bytes() != dev_tracked:
            raise RuntimeError("Pi development artifact differs from its exact commit.")
        if sha_file(dev_artifact) != request["development_artifact_sha256"]:
            raise RuntimeError("Windows/Pi development artifact SHA-256 differs.")

        tag = request["released_tag"]
        tag_commit = git_text(production, "rev-parse", f"refs/tags/{tag}^{{commit}}")
        if tag_commit != request["released_tag_commit"]:
            raise RuntimeError("Pi released tag commit differs from Windows provenance.")
        version = git_bytes(production, f"{tag}:VERSION").decode().strip()
        manifest = json.loads(git_bytes(production, f"{tag}:releases/{tag}.json"))
        required = manifest.get("requires_firmware")
        if (
            version != tag or manifest.get("version") != tag or manifest.get("tag") != tag
            or not isinstance(required, dict)
            or required.get("artifact") != request["artifact_relative_path"]
        ):
            raise RuntimeError("Pi released tag manifest does not bind the recovery artifact.")
        release_tag_bytes = git_bytes(production, f'{tag}:{request["artifact_relative_path"]}')
        release_artifact = production / request["artifact_relative_path"]
        if not release_artifact.is_file() or release_artifact.read_bytes() != release_tag_bytes:
            raise RuntimeError("Protected-checkout recovery artifact differs from the released tag.")
        if sha_file(release_artifact) != request["released_artifact_sha256"]:
            raise RuntimeError("Windows/Pi released recovery artifact SHA-256 differs.")

        report["preflight"] = {
            "production_worktree": production_state,
            "development_worktree": development_state,
            "workflow_config_file_sha256": sha_file(workflow_config),
            "workflow_config_canonical_sha256": workflow_canonical_sha256,
            "recovery_command": "dfu-util",
            "development_artifact_sha256": sha_file(dev_artifact),
            "released_tag": tag,
            "released_tag_commit": tag_commit,
            "released_artifact_sha256": sha_file(release_artifact),
            "processes": [],
        }
        atomic_json(session / "request.json", request)

        development_stage = None
        try:
            development_stage = run_stage(
                request, role="development", artifact=dev_artifact, session=session
            )
            report["stages"].append(development_stage)
        except Exception as exc:
            development_stage = {"role": "development", "status": "failed", "error": str(exc)}
            report["stages"].append(development_stage)
        finally:
            try:
                released_stage = run_stage(
                    request, role="released-restore", artifact=release_artifact, session=session
                )
            except Exception as exc:
                released_stage = {"role": "released-restore", "status": "failed", "error": str(exc)}
            report["stages"].append(released_stage)

        post_production = worktree_state(production)
        post_development = worktree_state(development)
        post_processes = relevant_processes()
        report["postflight"] = {
            "production_worktree": post_production,
            "development_worktree": post_development,
            "processes": post_processes,
        }
        restored = released_stage.get("status") == "passed"
        qualified = development_stage.get("status") == "passed"
        unchanged = post_production == production_state and post_development == development_state
        report["final_firmware_role"] = "released" if restored else "recovery-required"
        report["status"] = "passed" if restored and qualified and unchanged and not post_processes else "failed"
        if not restored:
            report["failure"] = "Released firmware could not be restored and SAFE-verified."
        elif not qualified:
            report["failure"] = "Development firmware did not pass SAFE; released firmware was restored."
        elif not unchanged or post_processes:
            report["failure"] = "Protected postflight differs after released restoration."
    except Exception as exc:
        report["status"] = "failed"
        report["final_firmware_role"] = "unchanged-preflight"
        report["failure"] = str(exc)
    report["completed_at_utc"] = now()
    atomic_json(report_path, report)
    report["report_path"] = str(report_path)
    report["report_sha256"] = sha_file(report_path)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
'''


def run_remote_roundtrip(
    *,
    pi_host: str,
    pi_user: str,
    identity_file: Path | None,
    request: Mapping[str, Any],
    timeout_seconds: int = 720,
) -> dict[str, Any]:
    target = pi_host if "@" in pi_host else f"{pi_user}@{pi_host}"
    encoded = base64.urlsafe_b64encode(
        json.dumps(dict(request), sort_keys=True).encode("utf-8")
    ).decode("ascii")
    command = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
        "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=8",
    ]
    if identity_file is not None:
        command.extend(["-i", str(identity_file)])
    command.extend([target, "python3", "-", encoded])
    try:
        completed = subprocess.run(
            command, input=REMOTE_FIRMWARE_ROUNDTRIP, capture_output=True,
            text=True, check=False, timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise FirmwareWorkflowError(
            "Remote firmware round-trip timed out; released state must be inspected."
        ) from exc
    if completed.returncode != 0:
        raise FirmwareWorkflowError(
            "Remote firmware supervisor failed before returning evidence: "
            + (completed.stderr or completed.stdout).strip()
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise FirmwareWorkflowError("Pi returned malformed firmware evidence.") from exc
    if not isinstance(payload, dict):
        raise FirmwareWorkflowError("Pi firmware evidence is not an object.")
    return payload


def build_local_report(
    *, local: Mapping[str, Any], pre_remote: Mapping[str, Any], provenance: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "transaction_id": str(uuid4()),
        "started_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "preflight",
        "local": dict(local),
        "preflight_pi": dict(pre_remote),
        "artifact_provenance": dict(provenance),
    }


def write_report(report: Mapping[str, Any], output_root: Path) -> Path:
    timestamp = str(report["started_at_utc"]).replace("-", "").replace(":", "").replace(".", "")
    directory = output_root.resolve() / f"{timestamp}_{report['transaction_id']}"
    path = directory / "roundtrip.json"
    workflow._atomic_json(path, report)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pi-host", required=True)
    parser.add_argument("--pi-user", default="labcraft")
    parser.add_argument("--ssh-identity-file", type=Path)
    parser.add_argument("--production-repo", default=workflow.DEFAULT_PRODUCTION_REPO)
    parser.add_argument("--development-repo", default=workflow.DEFAULT_DEVELOPMENT_REPO)
    parser.add_argument("--shared-python", default=workflow.DEFAULT_SHARED_PYTHON)
    parser.add_argument("--workflow-config", default=workflow.DEFAULT_WORKFLOW_CONFIG)
    parser.add_argument("--released-tag", default=DEFAULT_RELEASED_TAG)
    parser.add_argument("--port", default="/dev/ttyAMA0")
    parser.add_argument("--operator", default=getpass.getuser())
    parser.add_argument("--remote-session-root", default=DEFAULT_REMOTE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _identity(path: Path | None) -> Path | None:
    if path is None:
        return None
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise FirmwareWorkflowError(f"SSH identity file does not exist: {candidate}")
    return candidate


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        identity = _identity(args.ssh_identity_file)
        workflow.validate_remote_paths(
            pi_user=args.pi_user,
            production_repo=args.production_repo,
            development_repo=args.development_repo,
            shared_python=args.shared_python,
            development_machine_data_root=None,
            workflow_config=args.workflow_config,
        )
        validate_remote_session_root(
            args.remote_session_root, pi_user=args.pi_user,
            production_repo=args.production_repo, development_repo=args.development_repo,
        )
        if not str(args.operator).strip():
            raise FirmwareWorkflowError("An operator identity is required.")
    except (FirmwareWorkflowError, workflow.WorkflowError) as exc:
        print(f"Firmware workflow failed: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        target = args.pi_host if "@" in args.pi_host else f"{args.pi_user}@{args.pi_host}"
        print("DRY RUN action=development-safe-released-safe-roundtrip")
        print(f"SSH target: {target}")
        print(f"Development worktree: {args.development_repo}")
        print(f"Protected worktree (read only): {args.production_repo}")
        print(f"Released recovery tag: {args.released_tag}")
        print("HIL profile: SAFE (fixed; no selectors, camera, motion, or pressure)")
        print("Mandatory final stage: released restore plus SAFE")
        print("No SSH call, flash, or evidence write was performed.")
        return 0
    if shutil.which("ssh") is None:
        print("Firmware workflow failed: ssh is unavailable.", file=sys.stderr)
        return 1

    report: dict[str, Any] | None = None
    report_path: Path | None = None
    try:
        local = workflow.collect_local_state(REPO_ROOT)
        pre_remote = workflow.collect_remote_state(
            pi_host=args.pi_host, pi_user=args.pi_user, identity_file=identity,
            production_repo=args.production_repo, development_repo=args.development_repo,
            shared_python=args.shared_python, development_machine_data_root=None,
            workflow_config=args.workflow_config,
        )
        blockers, _warnings = workflow.classify_status(local, pre_remote)
        development = pre_remote.get("development_worktree") or {}
        if blockers:
            raise FirmwareWorkflowError(
                "General development preflight is blocked: "
                + ", ".join(str(item["code"]) for item in blockers)
            )
        if (
            development.get("state") != "registered_clean"
            or development.get("head") != local.get("head")
            or not development.get("detached")
        ):
            raise FirmwareWorkflowError(
                "Pi development worktree is not clean/detached at exact Windows HEAD."
            )
        provenance = collect_local_artifact_provenance(
            REPO_ROOT, head=str(local["head"]), released_tag=args.released_tag
        )
        source_contract = firmware_safe_hil.validate_safe_source_contract(REPO_ROOT)
        report = build_local_report(
            local=local, pre_remote=pre_remote, provenance=provenance
        )
        report["safe_source_contract"] = source_contract
        report_path = write_report(report, args.output_root)
        workflow_config = pre_remote.get("workflow_config") or {}
        if not workflow_config.get("valid") or not isinstance(workflow_config.get("payload"), Mapping):
            raise FirmwareWorkflowError("Persisted workflow configuration is not valid/hash-bound.")
        production = pre_remote.get("production_worktree") or {}
        pre_invariant = workflow.canonical_sha256(workflow.launch_invariant_payload(pre_remote))
        request = {
            "production_repo": args.production_repo,
            "development_repo": args.development_repo,
            "shared_python": args.shared_python,
            "workflow_config": args.workflow_config,
            "workflow_config_canonical_sha256": workflow.canonical_sha256(
                workflow_config["payload"]
            ),
            "remote_session_root": args.remote_session_root,
            "operator": str(args.operator).strip(),
            "port": args.port,
            "expected_commit": local["head"],
            "expected_production_head": production["head"],
            "expected_production_branch": production["branch"],
            "artifact_relative_path": ARTIFACT_RELATIVE_PATH,
            "development_artifact_sha256": provenance["development"]["sha256"],
            "released_tag": args.released_tag,
            "released_tag_commit": provenance["released"]["tag_commit"],
            "released_artifact_sha256": provenance["released"]["sha256"],
        }
        remote_result = run_remote_roundtrip(
            pi_host=args.pi_host, pi_user=args.pi_user, identity_file=identity,
            request=request,
        )
        post_remote = workflow.collect_remote_state(
            pi_host=args.pi_host, pi_user=args.pi_user, identity_file=identity,
            production_repo=args.production_repo, development_repo=args.development_repo,
            shared_python=args.shared_python, development_machine_data_root=None,
            workflow_config=args.workflow_config,
        )
        post_invariant = workflow.canonical_sha256(workflow.launch_invariant_payload(post_remote))
        report["remote_roundtrip"] = remote_result
        report["postflight_pi"] = post_remote
        report["pre_invariant_sha256"] = pre_invariant
        report["post_invariant_sha256"] = post_invariant
        report["completed_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        report["status"] = (
            "passed"
            if remote_result.get("status") == "passed"
            and remote_result.get("final_firmware_role") == "released"
            and pre_invariant == post_invariant
            else "failed"
        )
        workflow._atomic_json(report_path, report)
        print(f"Firmware round-trip: {report['status'].upper()}")
        print(f"Final firmware role: {remote_result.get('final_firmware_role')}")
        print(f"Evidence: {report_path}")
        return 0 if report["status"] == "passed" else 2
    except (OSError, ValueError, FirmwareWorkflowError, workflow.WorkflowError,
            firmware_safe_hil.SafeHilValidationError) as exc:
        if report is not None and report_path is not None:
            report["status"] = "failed"
            report["failure"] = str(exc)
            report["completed_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            workflow._atomic_json(report_path, report)
            print(f"Evidence: {report_path}", file=sys.stderr)
        print(f"Firmware workflow failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
