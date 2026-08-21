"""Supervise explicit attended hardware development from an exact Pi commit."""

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


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = REPO_ROOT / "FreeRTOS-interface"
for candidate in (str(REPO_ROOT / "tools"), str(UI_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import firmware_state  # noqa: E402
import pi_development_firmware as firmware_workflow  # noqa: E402
import pi_development_workflow as workflow  # noqa: E402
from DevelopmentHardwareAuthorization import (  # noqa: E402
    ATTENDED_CONFIRMATION,
    CLEAR_ENVELOPE_CONFIRMATION,
)


SCHEMA_NAME = "labcraft.pi_development_hardware_status"
SCHEMA_VERSION = 1
DEFAULT_FIRMWARE_STATE = (
    "/home/labcraft/.local/share/LabCraft/LabCraft Printer/"
    "development-workflow/firmware-state.json"
)
DEFAULT_REMOTE_ROOT = (
    "/home/labcraft/.local/share/LabCraft/LabCraft Printer/"
    "development-workflow/hardware-sessions"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "verification_reports/development-workflow/hardware"
)
CAMPAIGN_CONFIRMATION = CLEAR_ENVELOPE_CONFIRMATION


class DevelopmentHardwareError(RuntimeError):
    """Raised when an attended hardware launch cannot be authorized."""


def _external_path(path: str, *, pi_user: str, worktrees: Sequence[str]) -> None:
    candidate = PurePosixPath(path)
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise DevelopmentHardwareError("Hardware evidence paths must be absolute.")
    if candidate in {PurePosixPath("/"), PurePosixPath(f"/home/{pi_user}")}:
        raise DevelopmentHardwareError("Hardware evidence path is too broad.")
    for value in worktrees:
        root = PurePosixPath(value)
        if candidate == root or root in candidate.parents or candidate in root.parents:
            raise DevelopmentHardwareError("Hardware evidence paths must be external to worktrees.")


def build_remote_request(
    *, args: argparse.Namespace, local: Mapping[str, Any], remote: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    production = remote["production_worktree"]
    config = remote["workflow_config"]
    return {
        "action": args.action,
        "runtime_mode": args.runtime_mode,
        "qualification_scenario": args.qualification_scenario,
        "execute": bool(args.execute),
        "production_repo": args.production_repo,
        "development_repo": args.development_repo,
        "shared_python": args.shared_python,
        "workflow_config": args.workflow_config,
        "workflow_config_canonical_sha256": workflow.canonical_sha256(config["payload"]),
        "firmware_state_path": args.firmware_state_path,
        "remote_session_root": args.remote_session_root,
        "operator": str(args.operator).strip(),
        "attended_confirmation": args.attended_confirmation,
        "expected_commit": local["head"],
        "expected_production_head": production["head"],
        "expected_production_branch": production["branch"],
        "development_artifact_sha256": provenance["development"]["sha256"],
        "released_artifact_sha256": provenance["released"]["sha256"],
        "released_tag": provenance["released"]["tag"],
        "artifact_relative_path": firmware_workflow.ARTIFACT_RELATIVE_PATH,
        "launch_timeout_seconds": args.launch_timeout_seconds,
    }


REMOTE_WORKER = r'''
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def git(repo, *args):
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def worktree(path):
    return {
        "head": git(path, "rev-parse", "HEAD"),
        "branch": git(path, "branch", "--show-current") or None,
        "status": git(path, "status", "--porcelain=v1", "--untracked-files=all").splitlines(),
    }


def processes():
    patterns = ("FreeRTOS-interface/App.py", "run_development_app.py", "update_and_restart.py", "dfu_update.py", "flash_and_test.sh", "run_selftest.py")
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if any(pattern in command for pattern in patterns):
            found.append({"pid": int(entry.name), "command": command.strip()})
    return sorted(found, key=lambda row: row["pid"])


def atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid4()}.tmp"
    data = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try: temporary.unlink()
        except FileNotFoundError: pass


def main():
    request = json.loads(base64.urlsafe_b64decode(sys.argv[1]).decode())
    production = Path(request["production_repo"]).resolve()
    development = Path(request["development_repo"]).resolve()
    config_path = Path(request["workflow_config"]).resolve()
    state_path = Path(request["firmware_state_path"]).resolve()
    session = Path(request["remote_session_root"]).resolve() / str(uuid4())
    session.mkdir(parents=True, exist_ok=False)
    report_path = session / "hardware-status.json"
    report = {
        "schema_name": "labcraft.pi_development_hardware_remote",
        "schema_version": 1,
        "action": request["action"],
        "operator": request["operator"],
        "started_at_utc": now(),
        "session_path": str(session),
        "status": "blocked",
    }
    try:
        production_before = worktree(production)
        development_before = worktree(development)
        if production_before != {"head": request["expected_production_head"], "branch": request["expected_production_branch"], "status": []}:
            raise RuntimeError("Protected production worktree changed.")
        if development_before != {"head": request["expected_commit"], "branch": None, "status": []}:
            raise RuntimeError("Development worktree is not exact, detached, and clean.")
        if processes():
            raise RuntimeError("A conflicting app, updater, DFU, or HIL process is running.")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if canonical(config) != request["workflow_config_canonical_sha256"]:
            raise RuntimeError("Persisted development workflow binding changed.")
        root = Path(config["development_machine_data_root"]).resolve()
        marker = json.loads((root / "development_store.json").read_text(encoding="utf-8"))
        machine_id = config["machine_id"]
        if marker["store_id"] != config["development_store_id"]:
            raise RuntimeError("Development store identity changed.")
        development_artifact = development / request["artifact_relative_path"]
        released_artifact = production / request["artifact_relative_path"]
        if sha(development_artifact) != request["development_artifact_sha256"]:
            raise RuntimeError("Pi development firmware artifact differs from Windows HEAD.")
        if sha(released_artifact) != request["released_artifact_sha256"]:
            raise RuntimeError("Pi protected recovery artifact differs from the released binding.")

        sys.path.insert(0, str(development / "tools"))
        sys.path.insert(0, str(development / "FreeRTOS-interface"))
        import firmware_state
        from DevelopmentHardwareAuthorization import create_authorization, ATTENDED_CONFIRMATION, CLEAR_ENVELOPE_CONFIRMATION

        compatibility = None
        state_error = None
        try:
            state = firmware_state.load_state(state_path)
            expected_commit = request["expected_commit"]
            development_sha = request["development_artifact_sha256"]
            scenario = request["qualification_scenario"]
            if scenario in {"stale-commit", "mismatched-artifact"}:
                fixture_payload = dict(state.payload)
                fixture_payload.update({
                    "role": "development",
                    "source_commit": request["expected_commit"],
                    "artifact_path": str(development / request["artifact_relative_path"]),
                    "artifact_sha256": request["development_artifact_sha256"],
                })
                state = firmware_state.FirmwareState(
                    state.path, state.sha256, fixture_payload
                )
                report["qualification_fixture"] = (
                    "in_memory_only_exact_development_state"
                )
            if scenario == "stale-commit": expected_commit = "0" * 40
            if scenario == "mismatched-artifact": development_sha = "0" * 64
            compatibility = firmware_state.require_hardware_compatible(
                state, machine_id=machine_id, development_commit=expected_commit,
                development_artifact_sha256=development_sha,
                released_artifact_sha256=request["released_artifact_sha256"],
            )
            compatibility["released_artifact_sha256"] = request["released_artifact_sha256"]
        except Exception as exc:
            state_error = str(exc)

        report["preflight"] = {
            "production_worktree": production_before,
            "development_worktree": development_before,
            "machine_id": machine_id,
            "store_id": marker["store_id"],
            "firmware_compatibility": compatibility,
            "firmware_state_error": state_error,
            "processes": [],
        }
        if request["action"] == "cancel":
            report["status"] = "canceled"
        elif request["runtime_mode"] != "hardware":
            report["status"] = "blocked"
            report["blocker"] = "no_hardware_mode_rejected"
        elif compatibility is None:
            report["status"] = "blocked"
            report["blocker"] = "firmware_state_incompatible"
        elif request["action"] == "preflight":
            report["status"] = "ready"
        elif request["action"] == "launch":
            if not request["execute"]:
                raise RuntimeError("Hardware launch requires the explicit execute switch.")
            if request["attended_confirmation"] != CLEAR_ENVELOPE_CONFIRMATION:
                raise RuntimeError("Exact attended/clear-envelope confirmation is missing.")
            authorization_path = session / "hardware-authorization.json"
            create_authorization(
                authorization_path, operator=request["operator"],
                expected_commit=request["expected_commit"],
                development_store_id=marker["store_id"],
                development_machine_data_root=root, firmware_state_path=state_path,
                firmware_compatibility=compatibility,
            )
            command = [
                request["shared_python"], str(development / "tools/run_development_app.py"),
                "--machine-data-root", str(root), "--operator", request["operator"],
                "--enable-hardware", "--hardware-confirmation", ATTENDED_CONFIRMATION,
                "--clear-envelope-confirmation", CLEAR_ENVELOPE_CONFIRMATION,
                "--hardware-authorization", str(authorization_path),
                "--expected-commit", request["expected_commit"],
            ]
            log_path = session / "application.log"
            with log_path.open("w", encoding="utf-8", newline="\n") as log:
                process = subprocess.Popen(
                    command, cwd=development, stdout=log, stderr=subprocess.STDOUT,
                    text=True, start_new_session=True,
                )
                report["owned_process"] = {"pid": process.pid, "process_group": process.pid}
                try:
                    exit_code = process.wait(timeout=request["launch_timeout_seconds"])
                    cleanup = "normal_exit"
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    try: exit_code = process.wait(timeout=10); cleanup = "owned_group_sigterm"
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL); exit_code = process.wait(timeout=5); cleanup = "owned_group_sigkill"
            report["launch"] = {"command": command, "exit_code": exit_code, "cleanup": cleanup, "log_path": str(log_path), "log_sha256": sha(log_path)}
            report["status"] = "passed" if exit_code == 0 and cleanup == "normal_exit" else "failed"

        report["postflight"] = {
            "production_worktree": worktree(production),
            "development_worktree": worktree(development),
            "processes": processes(),
        }
        if report["postflight"]["production_worktree"] != production_before or report["postflight"]["development_worktree"] != development_before or report["postflight"]["processes"]:
            report["status"] = "failed"
            report["failure"] = "Protected postflight changed or a related process remains."
    except Exception as exc:
        report["status"] = "blocked" if request["action"] != "launch" else "failed"
        report["failure"] = str(exc)
    report["completed_at_utc"] = now()
    atomic(report_path, report)
    report["report_path"] = str(report_path)
    report["report_sha256"] = sha(report_path)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__": main()
'''


def run_remote(
    *, pi_host: str, pi_user: str, identity_file: Path | None,
    shared_python: str, development_repo: str, request: Mapping[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    target = pi_host if "@" in pi_host else f"{pi_user}@{pi_host}"
    encoded = base64.urlsafe_b64encode(json.dumps(dict(request), sort_keys=True).encode()).decode()
    command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
               "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=8"]
    if identity_file is not None:
        command.extend(["-i", str(identity_file)])
    command.extend([target, "python3", "-", encoded])
    completed = subprocess.run(
        command, input=REMOTE_WORKER, capture_output=True, text=True, check=False,
        timeout=timeout_seconds + 60,
    )
    if completed.returncode:
        raise DevelopmentHardwareError((completed.stderr or completed.stdout).strip())
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise DevelopmentHardwareError("Pi returned malformed hardware evidence.") from exc
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("preflight", "cancel", "launch"), default="preflight")
    parser.add_argument("--runtime-mode", choices=("hardware", "no-hardware"), default="hardware")
    parser.add_argument("--qualification-scenario", choices=("normal", "stale-commit", "mismatched-artifact"), default="normal")
    parser.add_argument("--pi-host", required=True)
    parser.add_argument("--pi-user", default="labcraft")
    parser.add_argument("--ssh-identity-file", type=Path)
    parser.add_argument("--production-repo", default=workflow.DEFAULT_PRODUCTION_REPO)
    parser.add_argument("--development-repo", default=workflow.DEFAULT_DEVELOPMENT_REPO)
    parser.add_argument("--shared-python", default=workflow.DEFAULT_SHARED_PYTHON)
    parser.add_argument("--workflow-config", default=workflow.DEFAULT_WORKFLOW_CONFIG)
    parser.add_argument("--firmware-state-path", default=DEFAULT_FIRMWARE_STATE)
    parser.add_argument("--released-tag", default=firmware_workflow.DEFAULT_RELEASED_TAG)
    parser.add_argument("--remote-session-root", default=DEFAULT_REMOTE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--operator", default=getpass.getuser())
    parser.add_argument("--attended-confirmation")
    parser.add_argument("--launch-timeout-seconds", type=int, default=1800)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        identity = firmware_workflow._identity(args.ssh_identity_file)
        workflow.validate_remote_paths(
            pi_user=args.pi_user, production_repo=args.production_repo,
            development_repo=args.development_repo, shared_python=args.shared_python,
            development_machine_data_root=None, workflow_config=args.workflow_config,
        )
        _external_path(args.firmware_state_path, pi_user=args.pi_user,
                       worktrees=(args.production_repo, args.development_repo))
        _external_path(args.remote_session_root, pi_user=args.pi_user,
                       worktrees=(args.production_repo, args.development_repo))
        if not str(args.operator).strip():
            raise DevelopmentHardwareError("Operator identity is required.")
        if args.action == "launch" and (
            not args.execute or args.attended_confirmation != CAMPAIGN_CONFIRMATION
        ):
            raise DevelopmentHardwareError(
                "Hardware launch requires --execute and the exact attended confirmation."
            )
        if args.action != "launch" and args.execute:
            raise DevelopmentHardwareError("Execute is valid only for launch.")
    except (DevelopmentHardwareError, workflow.WorkflowError,
            firmware_workflow.FirmwareWorkflowError) as exc:
        print(f"Hardware workflow failed: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"DRY RUN action={args.action} runtime={args.runtime_mode}")
        print(f"Firmware state: {args.firmware_state_path}")
        print(f"Development repository: {args.development_repo}")
        print("Updater, rollback, and in-app DFU remain blocked.")
        print("No SSH call, application launch, or evidence write was performed.")
        return 0
    if shutil.which("ssh") is None:
        print("Hardware workflow failed: ssh is unavailable.", file=sys.stderr); return 1

    report = None
    path = None
    try:
        local = workflow.collect_local_state(REPO_ROOT)
        remote = workflow.collect_remote_state(
            pi_host=args.pi_host, pi_user=args.pi_user, identity_file=identity,
            production_repo=args.production_repo, development_repo=args.development_repo,
            shared_python=args.shared_python, development_machine_data_root=None,
            workflow_config=args.workflow_config,
        )
        blockers, _warnings = workflow.classify_status(local, remote)
        development = remote.get("development_worktree") or {}
        if blockers or development.get("head") != local["head"] or not development.get("detached"):
            raise DevelopmentHardwareError("Exact general development preflight is blocked.")
        provenance = firmware_workflow.collect_local_artifact_provenance(
            REPO_ROOT, head=local["head"], released_tag=args.released_tag
        )
        report = {
            "schema_name": SCHEMA_NAME, "schema_version": SCHEMA_VERSION,
            "transaction_id": str(uuid4()), "action": args.action,
            "started_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "preflight", "local": local, "preflight_pi": remote,
            "artifact_provenance": provenance,
        }
        path = firmware_workflow.write_report(report, args.output_root)
        pre_invariant = workflow.canonical_sha256(workflow.launch_invariant_payload(remote))
        request = build_remote_request(args=args, local=local, remote=remote, provenance=provenance)
        result = run_remote(
            pi_host=args.pi_host, pi_user=args.pi_user, identity_file=identity,
            shared_python=args.shared_python, development_repo=args.development_repo,
            request=request, timeout_seconds=args.launch_timeout_seconds,
        )
        post = workflow.collect_remote_state(
            pi_host=args.pi_host, pi_user=args.pi_user, identity_file=identity,
            production_repo=args.production_repo, development_repo=args.development_repo,
            shared_python=args.shared_python, development_machine_data_root=None,
            workflow_config=args.workflow_config,
        )
        post_invariant = workflow.canonical_sha256(workflow.launch_invariant_payload(post))
        report.update({
            "remote_result": result, "postflight_pi": post,
            "pre_invariant_sha256": pre_invariant, "post_invariant_sha256": post_invariant,
            "completed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        })
        report["status"] = result.get("status")
        if pre_invariant != post_invariant:
            report["status"] = "failed"; report["failure"] = "Protected invariant changed."
        workflow._atomic_json(path, report)
        print(f"Hardware development {args.action}: {str(report['status']).upper()}")
        print(f"Evidence: {path}")
        if report["status"] in {"ready", "canceled", "passed"}: return 0
        return 2
    except Exception as exc:
        if report is not None and path is not None:
            report["status"] = "failed"; report["failure"] = str(exc)
            workflow._atomic_json(path, report); print(f"Evidence: {path}", file=sys.stderr)
        print(f"Hardware workflow failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
