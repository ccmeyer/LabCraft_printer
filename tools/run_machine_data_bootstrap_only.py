"""Run only the machine-data bootstrap UI against an explicit external root.

This helper intentionally stops after bootstrap authorization.  It never imports
the normal application, MVC, machine communication, or hardware composition.
It is uploaded by the Pi upgrade-rehearsal supervisor and may therefore run
outside the target checkout while importing the target release's bootstrap
implementation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


RESULT_SCHEMA = "labcraft.bootstrap_only_result"
RESULT_SCHEMA_VERSION = 1
FORBIDDEN_MODULES = frozenset(
    {
        "App",
        "Controller",
        "Model",
        "View",
        "Machine",
        "Machine_FreeRTOS",
        "ApplicationComposition",
        "BalanceProtocol",
        "BalanceService",
        "dfu_update",
        "firmware_state",
        "firmware_safe_hil",
        "gpiod",
        "hardware",
        "serial",
        "update_and_restart",
        "update_window",
        "tools.dfu_update",
        "tools.firmware_state",
        "tools.firmware_safe_hil",
        "tools.pi_development_firmware",
        "tools.update_and_restart",
        "tools.update_window",
    }
)
FORBIDDEN_PREFIXES = (
    "CalibrationClasses.",
    "hardware.",
    "serial.",
)


class BootstrapOnlyError(RuntimeError):
    """Raised when the bootstrap-only contract cannot be proven."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular_tree_evidence(root: Path) -> dict[str, Any]:
    requested = Path(root)
    resolved = requested.resolve(strict=False)
    rows: list[dict[str, Any]] = []
    folded: set[str] = set()
    if not requested.is_dir() or requested.is_symlink():
        raise BootstrapOnlyError(f"Tree root is missing or linked: {requested}")
    for candidate in sorted(requested.rglob("*")):
        details = candidate.lstat()
        if stat.S_ISLNK(details.st_mode):
            raise BootstrapOnlyError(f"Tree contains a symbolic link: {candidate}")
        relative = candidate.relative_to(requested).as_posix()
        folded_name = relative.casefold()
        if folded_name in folded:
            raise BootstrapOnlyError("Tree contains case-colliding paths.")
        folded.add(folded_name)
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise BootstrapOnlyError(f"Tree contains a special file: {candidate}")
        rows.append(
            {
                "relative_path": relative,
                "size": candidate.stat().st_size,
                "sha256": file_sha256(candidate),
            }
        )
    return {
        "root": str(resolved),
        "file_count": len(rows),
        "total_size": sum(row["size"] for row in rows),
        "tree_sha256": canonical_sha256(rows),
    }


def forbidden_imports() -> list[str]:
    return sorted(
        name
        for name in sys.modules
        if name in FORBIDDEN_MODULES
        or any(name.startswith(prefix) for prefix in FORBIDDEN_PREFIXES)
    )


def reject_link_ancestors(path: Path) -> None:
    requested = Path(os.path.abspath(str(Path(path).expanduser())))
    for candidate in reversed((requested, *requested.parents)):
        if candidate.is_symlink():
            raise BootstrapOnlyError(
                f"Path contains a symbolic-link ancestor: {candidate}"
            )


def require_absolute_path(path: Path, label: str) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise BootstrapOnlyError(f"{label} must be an absolute path without '..'.")


def result_path_is_safe(arguments: argparse.Namespace) -> bool:
    try:
        requested_result = Path(arguments.result_path)
        require_absolute_path(requested_result, "Result path")
        reject_link_ancestors(requested_result)
        result = requested_result.resolve(strict=False)
        for raw in (
            arguments.repo_root,
            arguments.source_wrapper,
            arguments.machine_data_root,
        ):
            protected = Path(raw)
            require_absolute_path(protected, "Protected path")
            reject_link_ancestors(protected)
            protected = protected.resolve(strict=False)
            if result == protected or protected in result.parents:
                return False
        return True
    except Exception:
        return False


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = json.dumps(dict(payload), indent=2, sort_keys=True) + "\n"
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _active_summary(context: object) -> dict[str, Any]:
    active = context.active_machine
    paths = context.paths
    evidence_paths = {
        "active_machine": paths.base.active_machine_path,
        "machine_identity": paths.identity_path,
        "candidate_evidence": paths.candidate_evidence_path,
        "migration_receipt": paths.migration_receipt_path,
        "migration_tree_manifest": paths.migration_tree_manifest_path,
        "verification": paths.verification_path,
        "activation_receipt": paths.activation_receipt_path,
        "deployment_anchor": paths.deployment_anchor_path,
    }
    hashes = {}
    for name, path in evidence_paths.items():
        target = Path(path)
        if not target.is_file():
            raise BootstrapOnlyError(f"Required bootstrap evidence is missing: {target}")
        hashes[name] = file_sha256(target)
    return {
        "machine_id": active.machine_id,
        "machine_uuid": active.machine_uuid,
        "activation_id": active.activation_id,
        "migration_id": active.migration_id,
        "machine_root": str(paths.machine_root.resolve()),
        "evidence_sha256": hashes,
    }


def run_bootstrap_only(arguments: argparse.Namespace) -> dict[str, Any]:
    requested_repo = Path(arguments.repo_root)
    requested_source = Path(arguments.source_wrapper)
    requested_machine_data = Path(arguments.machine_data_root)
    requested_result = Path(arguments.result_path)
    for path in (
        requested_repo,
        requested_source,
        requested_machine_data,
        requested_result,
    ):
        require_absolute_path(path, "Bootstrap path")
        reject_link_ancestors(path)
    repo = requested_repo.resolve(strict=True)
    source = requested_source.resolve(strict=True)
    machine_data = requested_machine_data.resolve(strict=False)
    result_path = requested_result.resolve(strict=False)

    if not (repo / ".git").exists():
        # Linked worktrees use a .git file; standalone clones use a directory.
        if not (repo / ".git").is_file():
            raise BootstrapOnlyError("Repository root is not a Git checkout.")
    if not (source / "VERSION").is_file() or not (source / "local").is_dir():
        raise BootstrapOnlyError("Source wrapper must contain VERSION and local/.")
    if repo == machine_data or repo in machine_data.parents or machine_data in repo.parents:
        raise BootstrapOnlyError("Machine-data root must be outside the target checkout.")
    if source == machine_data or source in machine_data.parents or machine_data in source.parents:
        raise BootstrapOnlyError("Source wrapper and destination must be disjoint.")
    for label, protected in (
        ("target checkout", repo),
        ("source wrapper", source),
        ("machine data", machine_data),
    ):
        if result_path == protected or protected in result_path.parents:
            raise BootstrapOnlyError(
                f"Result evidence cannot be written inside the {label}."
            )

    interface_root = repo / "FreeRTOS-interface"
    for candidate in (str(interface_root), str(repo)):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)

    from AppVersion import get_app_commit, get_app_version
    from MachineData import resolve_machine_data_base
    from MachineDataBootstrap import BootstrapState, MachineDataBootstrap
    from MachineDataBootstrapDialog import MachineDataBootstrapDialog
    from MachineDataMigration import CandidateSelection, CandidateSourceKind

    blocked = forbidden_imports()
    if blocked:
        raise BootstrapOnlyError(
            "Bootstrap-only imports loaded forbidden modules: " + ", ".join(blocked)
        )

    actual_version = get_app_version(repo)
    actual_commit = get_app_commit(repo)
    if actual_version != arguments.expected_version:
        raise BootstrapOnlyError(
            f"Target VERSION differs: expected {arguments.expected_version}, got {actual_version}."
        )
    if actual_commit != arguments.expected_commit:
        raise BootstrapOnlyError(
            f"Target commit differs: expected {arguments.expected_commit}, got {actual_commit}."
        )

    base = resolve_machine_data_base(
        app_local_data_root=machine_data.parent,
        repo_root=repo,
        explicit_root=machine_data,
        environment={},
    )
    bootstrap = MachineDataBootstrap(
        base,
        app_version=actual_version,
        app_commit=actual_commit,
    )
    source_evidence = regular_tree_evidence(source)
    started_at = utc_now()
    outcome = "failed"
    active_summary = None

    if arguments.expected_outcome == "ready":
        inspection = bootstrap.inspect()
        if inspection.state is not BootstrapState.READY:
            raise BootstrapOnlyError(
                f"Ready reopen found {inspection.state.value} instead of ready."
            )
        context = bootstrap.open_ready()
        try:
            active_summary = _active_summary(context)
        finally:
            context.close()
        outcome = "ready"
    else:
        if base.active_machine_path.exists():
            raise BootstrapOnlyError("Fresh bootstrap root already has an active pointer.")
        selection = CandidateSelection(
            CandidateSourceKind.OPERATOR_SELECTED_WRAPPER,
            source,
            "exact-tag upgrade rehearsal source",
        )
        candidate = bootstrap.inspect_candidate(selection)
        if candidate.normalized_source != source:
            raise BootstrapOnlyError("Inspected source differs from the bound wrapper.")
        if not candidate.is_importable:
            raise BootstrapOnlyError("Bound source is not importable.")
        if (
            candidate.legacy_identity is not None
            and candidate.identity_status == "assigned"
            and candidate.legacy_identity.machine_id != arguments.expected_machine_id
        ):
            raise BootstrapOnlyError("Source identity differs from expected machine ID.")

        from PySide6 import QtWidgets

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
        app.setOrganizationName("LabCraft")
        app.setApplicationName("LabCraft Printer Upgrade Rehearsal")
        dialog = MachineDataBootstrapDialog(
            bootstrap,
            current_checkout_local=source,
        )
        dialog.setWindowTitle(
            f"LabCraft Upgrade Rehearsal - {arguments.expected_version} - "
            f"{arguments.expected_outcome.upper()}"
        )
        dialog.source_path.setText(str(source))
        dialog.source_path.setReadOnly(True)
        dialog.browse_folder_button.setEnabled(False)
        dialog.browse_zip_button.setEnabled(False)
        dialog.machine_id.setText(arguments.expected_machine_id)
        dialog.machine_id.setReadOnly(True)
        dialog.operator.setText(arguments.operator)
        dialog.operator.setReadOnly(True)
        dialog.source_reason.setText(arguments.source_reason)
        dialog.source_reason.setReadOnly(True)
        code = dialog.exec()
        context = dialog.context if code == QtWidgets.QDialog.DialogCode.Accepted else None
        if dialog.failure_code:
            raise BootstrapOnlyError(
                f"{dialog.failure_code}: {dialog.failure_message or 'Bootstrap stopped.'}"
            )
        if arguments.expected_outcome == "cancelled":
            if context is not None:
                try:
                    context.close()
                finally:
                    raise BootstrapOnlyError("Cancellation gate activated a machine.")
            if base.active_machine_path.exists() or base.machines_root.exists():
                raise BootstrapOnlyError("Cancellation gate created durable machine data.")
            if (
                machine_data.exists()
                and regular_tree_evidence(machine_data)["file_count"] != 0
            ):
                raise BootstrapOnlyError("Cancellation gate wrote into its fresh destination.")
            outcome = "cancelled"
        else:
            if context is None:
                raise BootstrapOnlyError("Activation gate was cancelled before activation.")
            try:
                active_summary = _active_summary(context)
            finally:
                context.close()
            outcome = "activated"

    blocked = forbidden_imports()
    if blocked:
        raise BootstrapOnlyError(
            "Bootstrap-only process imported forbidden modules: " + ", ".join(blocked)
        )
    return {
        "schema_name": RESULT_SCHEMA,
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": "passed",
        "outcome": outcome,
        "started_at_utc": started_at,
        "completed_at_utc": utc_now(),
        "repo_root": str(repo),
        "source_wrapper": str(source),
        "source_tree": source_evidence,
        "machine_data_root": str(machine_data),
        "app_version": actual_version,
        "app_commit": actual_commit,
        "active_machine": active_summary,
        "forbidden_imports": blocked,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--source-wrapper", required=True)
    parser.add_argument("--machine-data-root", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-machine-id", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--source-reason", required=True)
    parser.add_argument(
        "--expected-outcome", choices=("cancelled", "activated", "ready"), required=True
    )
    parser.add_argument("--result-path", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result_path = Path(args.result_path).resolve(strict=False)
    try:
        payload = run_bootstrap_only(args)
        _atomic_json(result_path, payload)
        print(json.dumps(payload, sort_keys=True))
        return 0
    except Exception as exc:
        payload = {
            "schema_name": RESULT_SCHEMA,
            "schema_version": RESULT_SCHEMA_VERSION,
            "status": "failed",
            "outcome": "failed",
            "completed_at_utc": utc_now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        if result_path_is_safe(args):
            try:
                _atomic_json(result_path, payload)
            except Exception:
                pass
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
