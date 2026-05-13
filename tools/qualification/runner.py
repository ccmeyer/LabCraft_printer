from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .artifacts import RunArtifacts, create_run_artifacts
from .identity import DEFAULT_IDENTITY_PATH, load_or_create_identity
from .manifest import QualificationManifest, load_manifest
from .report import write_json_atomic, write_qualification_artifacts


@dataclass(frozen=True)
class SelfTestInvocation:
    command: tuple[str, ...]
    raw_report_path: Path
    manifest: QualificationManifest
    identity: dict
    artifacts: RunArtifacts


@dataclass(frozen=True)
class QualificationRunResult:
    returncode: int
    run_dir: Path
    raw_selftest_path: Path
    report_path: Path
    summary_csv_path: Path
    report: dict


SelfTestInvoker = Callable[[SelfTestInvocation], int]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_selftest_invoker(invocation: SelfTestInvocation) -> int:
    completed = subprocess.run(list(invocation.command), check=False)
    return int(completed.returncode)


def _build_selftest_command(
    *,
    run_selftest_path: str | Path | None,
    port: str,
    baud: int,
    profile: str,
    raw_report_path: Path,
    timeout_ms: int | None,
) -> tuple[str, ...]:
    script = Path(run_selftest_path) if run_selftest_path is not None else _repo_root() / "tools" / "run_selftest.py"
    command = [
        sys.executable,
        str(script),
        "--port",
        str(port),
        "--baud",
        str(int(baud)),
        "--profile",
        str(profile).upper(),
        "--out",
        str(raw_report_path),
    ]
    if timeout_ms is not None:
        command.extend(["--timeout-ms", str(int(timeout_ms))])
    return tuple(command)


def _raw_missing_report(manifest: QualificationManifest, returncode: int) -> dict:
    return {
        "run_id": None,
        "profile": manifest.profile,
        "started_at": None,
        "finished_at": None,
        "aborted": True,
        "summary": {"total": 0, "passed": 0, "failed": 0},
        "results": [],
        "host_checks": [
            {
                "name": "selftest_invoker",
                "pass": False,
                "details": {
                    "returncode": int(returncode),
                    "error": "self-test runner did not produce raw_selftest.json",
                },
            }
        ],
    }


def run_qualification(
    *,
    manifest_ref: str | Path = "factory_acceptance_v0",
    port: str = "/dev/ttyAMA0",
    baud: int = 115200,
    machine_id: str | None = None,
    identity_path: str | Path = DEFAULT_IDENTITY_PATH,
    output_root: str | Path = Path("hil_reports") / "qualification",
    timeout_ms: int | None = None,
    run_selftest_path: str | Path | None = None,
    invoker: SelfTestInvoker = default_selftest_invoker,
) -> QualificationRunResult:
    manifest = load_manifest(manifest_ref)
    identity = load_or_create_identity(identity_path, machine_id=machine_id)
    artifacts = create_run_artifacts(identity["machine_id"], output_root=output_root)
    command = _build_selftest_command(
        run_selftest_path=run_selftest_path,
        port=port,
        baud=baud,
        profile=manifest.profile,
        raw_report_path=artifacts.raw_selftest_path,
        timeout_ms=timeout_ms,
    )
    invocation = SelfTestInvocation(
        command=command,
        raw_report_path=artifacts.raw_selftest_path,
        manifest=manifest,
        identity=identity,
        artifacts=artifacts,
    )
    selftest_returncode = int(invoker(invocation))

    if artifacts.raw_selftest_path.exists():
        raw_selftest = json.loads(artifacts.raw_selftest_path.read_text(encoding="utf-8"))
        raw_source_path: Path | None = artifacts.raw_selftest_path
    else:
        raw_selftest = _raw_missing_report(manifest, selftest_returncode)
        write_json_atomic(artifacts.raw_selftest_path, raw_selftest)
        raw_source_path = artifacts.raw_selftest_path

    report = write_qualification_artifacts(
        raw_selftest,
        manifest,
        identity,
        artifacts,
        raw_source_path=raw_source_path,
        selftest_returncode=selftest_returncode,
    )
    qualification_returncode = 0 if report.get("overall_status") == "pass" else 3
    return QualificationRunResult(
        returncode=qualification_returncode,
        run_dir=artifacts.run_dir,
        raw_selftest_path=artifacts.raw_selftest_path,
        report_path=artifacts.report_path,
        summary_csv_path=artifacts.summary_csv_path,
        report=report,
    )
