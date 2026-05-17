from __future__ import annotations

import csv
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .artifacts import now_timestamp, sanitize_machine_id
from .identity import DEFAULT_IDENTITY_PATH, load_or_create_identity
from .manifest import ManifestError, QualificationManifest, load_manifest
from .report import write_json_atomic
from .runner import (
    GripperControl,
    OperatorPrompter,
    QualificationRunResult,
    SelfTestInvoker,
    default_gripper_control,
    default_operator_prompter,
    default_selftest_invoker,
    run_qualification,
)

DEFAULT_CAMPAIGN_REF = "machine_full_qualification_v1"
CAMPAIGN_REPORT_SCHEMA = "qualification_campaign_report_v1"
DEFAULT_CAMPAIGN_OUTPUT_ROOT = Path("hil_reports") / "qualification_campaigns"
DEFAULT_SUITE_OUTPUT_ROOT = Path("hil_reports") / "qualification"


class CampaignError(ValueError):
    """Raised when a qualification campaign is invalid."""


@dataclass(frozen=True)
class CampaignStep:
    index: int
    manifest_ref: str
    manifest_id: str
    manifest_name: str
    fixture_id: str | None
    timeout_ms: int | None
    notes: str
    requires_operator_prompts: bool

    def to_report_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "manifest": self.manifest_ref,
            "manifest_id": self.manifest_id,
            "manifest_name": self.manifest_name,
            "fixture_id": self.fixture_id,
            "timeout_ms": self.timeout_ms,
            "notes": self.notes,
            "requires_operator_prompts": self.requires_operator_prompts,
        }


@dataclass(frozen=True)
class QualificationCampaign:
    schema_version: str
    campaign_id: str
    name: str
    description: str
    steps: tuple[CampaignStep, ...]
    raw: dict[str, Any]

    @property
    def requires_operator_prompts(self) -> bool:
        return any(step.requires_operator_prompts for step in self.steps)

    def to_report_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "campaign_id": self.campaign_id,
            "name": self.name,
            "description": self.description,
            "steps": [step.to_report_dict() for step in self.steps],
        }


@dataclass(frozen=True)
class CampaignArtifacts:
    campaign_dir: Path
    report_path: Path
    summary_csv_path: Path


@dataclass(frozen=True)
class CampaignRunResult:
    returncode: int
    campaign_dir: Path
    report_path: Path
    summary_csv_path: Path
    report: dict[str, Any]


QualificationRunner = Callable[..., QualificationRunResult]
CampaignEventCallback = Callable[[dict[str, Any]], None]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _campaign_dir() -> Path:
    return Path(__file__).resolve().parent / "campaigns"


def _resolve_campaign_path(ref: str | Path) -> Path:
    ref_path = Path(ref)
    if ref_path.exists() or ref_path.suffix.lower() == ".json" or len(ref_path.parts) > 1:
        return ref_path
    return _campaign_dir() / f"{ref_path.name}.json"


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CampaignError(f"Campaign is missing required string field '{key}'.")
    return value.strip()


def _required_fixture_ids(manifest: QualificationManifest) -> set[str]:
    return {
        str(item.get("fixture_id") or "").strip()
        for item in manifest.fixtures
        if str(item.get("fixture_id") or "").strip()
    }


def _parse_timeout(value: Any, *, step_index: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise CampaignError(f"Campaign step {step_index} timeout_ms must be an integer.")
    try:
        timeout_ms = int(value)
    except Exception as exc:
        raise CampaignError(f"Campaign step {step_index} timeout_ms must be an integer.") from exc
    if timeout_ms <= 0:
        raise CampaignError(f"Campaign step {step_index} timeout_ms must be positive.")
    return timeout_ms


def load_campaign(ref: str | Path = DEFAULT_CAMPAIGN_REF) -> QualificationCampaign:
    path = _resolve_campaign_path(ref)
    if not path.exists():
        raise CampaignError(f"Qualification campaign not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CampaignError(f"Invalid campaign JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise CampaignError("Campaign JSON must be an object.")

    schema_version = _require_string(payload, "schema_version")
    if schema_version != "qualification_campaign_v1":
        raise CampaignError("Campaign schema_version must be qualification_campaign_v1.")
    campaign_id = _require_string(payload, "campaign_id")
    name = _require_string(payload, "name")
    description = str(payload.get("description") or "").strip()
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise CampaignError("Campaign must include a non-empty 'steps' list.")

    steps: list[CampaignStep] = []
    for idx, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            raise CampaignError(f"Campaign step {idx} must be an object.")
        manifest_ref = str(raw_step.get("manifest") or "").strip()
        if not manifest_ref:
            raise CampaignError(f"Campaign step {idx} is missing manifest.")
        try:
            manifest = load_manifest(manifest_ref)
        except ManifestError as exc:
            raise CampaignError(f"Campaign step {idx} references invalid manifest '{manifest_ref}': {exc}") from exc
        fixture_id = str(raw_step.get("fixture") or "").strip() or None
        required_fixture_ids = _required_fixture_ids(manifest)
        if required_fixture_ids and fixture_id not in required_fixture_ids:
            raise CampaignError(
                f"Campaign step {idx} fixture '{fixture_id}' is not valid for manifest "
                f"{manifest.manifest_id}; expected one of {sorted(required_fixture_ids)}."
            )
        steps.append(
            CampaignStep(
                index=idx,
                manifest_ref=manifest_ref,
                manifest_id=manifest.manifest_id,
                manifest_name=manifest.name,
                fixture_id=fixture_id,
                timeout_ms=_parse_timeout(raw_step.get("timeout_ms"), step_index=idx),
                notes=str(raw_step.get("notes") or "").strip(),
                requires_operator_prompts=bool(manifest.requires_operator_prompts),
            )
        )

    return QualificationCampaign(
        schema_version=schema_version,
        campaign_id=campaign_id,
        name=name,
        description=description,
        steps=tuple(steps),
        raw=dict(payload),
    )


def create_campaign_artifacts(
    machine_id: str,
    *,
    output_root: str | Path = DEFAULT_CAMPAIGN_OUTPUT_ROOT,
    timestamp: str | None = None,
) -> CampaignArtifacts:
    safe_machine_id = sanitize_machine_id(machine_id)
    stamp = str(timestamp or now_timestamp())
    base_dir = Path(output_root) / safe_machine_id
    campaign_dir = base_dir / stamp
    if campaign_dir.exists():
        for idx in range(1, 1000):
            candidate = base_dir / f"{stamp}_{idx:03d}"
            if not candidate.exists():
                campaign_dir = candidate
                break
    campaign_dir.mkdir(parents=True, exist_ok=False)
    return CampaignArtifacts(
        campaign_dir=campaign_dir,
        report_path=campaign_dir / "campaign_report.json",
        summary_csv_path=campaign_dir / "campaign_summary.csv",
    )


def _step_result(
    step: CampaignStep,
    *,
    status: str,
    returncode: int | None = None,
    report: dict[str, Any] | None = None,
    result: QualificationRunResult | None = None,
    message: str = "",
) -> dict[str, Any]:
    warnings = list((report or {}).get("warnings") or [])
    return {
        "index": step.index,
        "manifest": step.manifest_ref,
        "manifest_id": step.manifest_id,
        "manifest_name": step.manifest_name,
        "fixture_id": step.fixture_id,
        "timeout_ms": step.timeout_ms,
        "status": status,
        "returncode": returncode,
        "overall_status": None if report is None else report.get("overall_status"),
        "warning_count": len(warnings),
        "message": message,
        "run_dir": None if result is None else str(result.run_dir),
        "report_path": None if result is None else str(result.report_path),
        "raw_selftest_path": None if result is None else str(result.raw_selftest_path),
        "summary_csv_path": None if result is None else str(result.summary_csv_path),
    }


def _campaign_warnings(step_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for step in step_results:
        count = int(step.get("warning_count") or 0)
        if count:
            warnings.append(
                {
                    "step_index": step.get("index"),
                    "manifest_id": step.get("manifest_id"),
                    "warning_count": count,
                    "report_path": step.get("report_path"),
                }
            )
    return warnings


def _build_campaign_report(
    *,
    campaign: QualificationCampaign,
    identity: dict[str, Any],
    artifacts: CampaignArtifacts,
    suite_output_root: str | Path,
    port: str,
    baud: int,
    operator_prompts: bool,
    progress_jsonl: bool,
    continue_on_failure: bool,
    started_at: str,
    finished_at: str,
    step_results: list[dict[str, Any]],
) -> dict[str, Any]:
    passed = sum(1 for item in step_results if item.get("status") == "pass")
    failed = sum(1 for item in step_results if item.get("status") == "fail")
    errored = sum(1 for item in step_results if item.get("status") == "error")
    skipped = sum(1 for item in step_results if item.get("status") == "skipped")
    warning_count = sum(int(item.get("warning_count") or 0) for item in step_results)
    overall_status = "pass" if failed == 0 and errored == 0 and skipped == 0 else "fail"
    return {
        "schema_version": CAMPAIGN_REPORT_SCHEMA,
        "campaign": campaign.to_report_dict(),
        "machine": {
            "machine_id": identity.get("machine_id"),
            "machine_uuid": identity.get("machine_uuid"),
            "assigned_at": identity.get("assigned_at"),
            "notes": identity.get("notes", ""),
        },
        "run": {
            "campaign_dir": str(artifacts.campaign_dir),
            "campaign_report_path": str(artifacts.report_path),
            "campaign_summary_csv_path": str(artifacts.summary_csv_path),
            "suite_output_root": str(suite_output_root),
            "port": str(port),
            "baud": int(baud),
            "operator_prompts": bool(operator_prompts),
            "progress_jsonl": bool(progress_jsonl),
            "continue_on_failure": bool(continue_on_failure),
        },
        "overall_status": overall_status,
        "started_at": started_at,
        "finished_at": finished_at,
        "summary": {
            "total": len(step_results),
            "passed": passed,
            "failed": failed,
            "errors": errored,
            "skipped": skipped,
            "warnings": warning_count,
        },
        "steps": step_results,
        "warnings": _campaign_warnings(step_results),
    }


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".campaign_", suffix=".csv", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def write_campaign_summary_csv(path: str | Path, report: dict[str, Any]) -> None:
    fieldnames = [
        "campaign_schema_version",
        "machine_id",
        "campaign_id",
        "campaign_name",
        "overall_status",
        "started_at",
        "finished_at",
        "step_index",
        "manifest_id",
        "fixture_id",
        "timeout_ms",
        "status",
        "returncode",
        "warning_count",
        "message",
        "report_path",
        "run_dir",
    ]
    common = {
        "campaign_schema_version": str(report.get("schema_version") or ""),
        "machine_id": str((report.get("machine") or {}).get("machine_id") or ""),
        "campaign_id": str((report.get("campaign") or {}).get("campaign_id") or ""),
        "campaign_name": str((report.get("campaign") or {}).get("name") or ""),
        "overall_status": str(report.get("overall_status") or ""),
        "started_at": str(report.get("started_at") or ""),
        "finished_at": str(report.get("finished_at") or ""),
    }
    rows = [
        {
            **common,
            "step_index": str(step.get("index") or ""),
            "manifest_id": str(step.get("manifest_id") or ""),
            "fixture_id": str(step.get("fixture_id") or ""),
            "timeout_ms": str(step.get("timeout_ms") if step.get("timeout_ms") is not None else ""),
            "status": str(step.get("status") or ""),
            "returncode": str(step.get("returncode") if step.get("returncode") is not None else ""),
            "warning_count": str(step.get("warning_count") or 0),
            "message": str(step.get("message") or ""),
            "report_path": str(step.get("report_path") or ""),
            "run_dir": str(step.get("run_dir") or ""),
        }
        for step in report.get("steps", [])
    ]
    with tempfile.TemporaryFile("w+", encoding="utf-8", newline="") as tmp:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        tmp.seek(0)
        text = tmp.read()
    _write_text_atomic(Path(path), text)


def _write_campaign_artifacts(report: dict[str, Any], artifacts: CampaignArtifacts) -> None:
    write_json_atomic(artifacts.report_path, report)
    write_campaign_summary_csv(artifacts.summary_csv_path, report)


def _emit_campaign_event(callback: CampaignEventCallback | None, event: dict[str, Any]) -> None:
    if callback is not None:
        callback(dict(event))


def run_campaign(
    *,
    campaign_ref: str | Path = DEFAULT_CAMPAIGN_REF,
    port: str = "/dev/ttyAMA0",
    baud: int = 115200,
    machine_id: str | None = None,
    identity_path: str | Path = DEFAULT_IDENTITY_PATH,
    campaign_output_root: str | Path = DEFAULT_CAMPAIGN_OUTPUT_ROOT,
    suite_output_root: str | Path = DEFAULT_SUITE_OUTPUT_ROOT,
    operator_prompts: bool = False,
    progress_jsonl: bool = False,
    continue_on_failure: bool = False,
    run_selftest_path: str | Path | None = None,
    invoker: SelfTestInvoker = default_selftest_invoker,
    prompter: OperatorPrompter = default_operator_prompter,
    gripper_control: GripperControl = default_gripper_control,
    qualification_runner: QualificationRunner = run_qualification,
    event_callback: CampaignEventCallback | None = None,
) -> CampaignRunResult:
    campaign = load_campaign(campaign_ref)
    identity = load_or_create_identity(identity_path, machine_id=machine_id)
    artifacts = create_campaign_artifacts(identity["machine_id"], output_root=campaign_output_root)
    started_at = _now_iso()
    step_results: list[dict[str, Any]] = []
    _emit_campaign_event(
        event_callback,
        {
            "event": "campaign_started",
            "campaign_id": campaign.campaign_id,
            "name": campaign.name,
            "total_steps": len(campaign.steps),
            "campaign_dir": str(artifacts.campaign_dir),
        },
    )

    if campaign.requires_operator_prompts and not operator_prompts:
        for step in campaign.steps:
            step_results.append(
                _step_result(
                    step,
                    status="skipped",
                    message="operator_prompts_required",
                )
            )
        report = _build_campaign_report(
            campaign=campaign,
            identity=identity,
            artifacts=artifacts,
            suite_output_root=suite_output_root,
            port=port,
            baud=baud,
            operator_prompts=operator_prompts,
            progress_jsonl=progress_jsonl,
            continue_on_failure=continue_on_failure,
            started_at=started_at,
            finished_at=_now_iso(),
            step_results=step_results,
        )
        _write_campaign_artifacts(report, artifacts)
        _emit_campaign_event(
            event_callback,
            {
                "event": "campaign_finished",
                "campaign_id": campaign.campaign_id,
                "status": report.get("overall_status"),
                "returncode": 3,
                "campaign_report_path": str(artifacts.report_path),
                "campaign_summary_csv_path": str(artifacts.summary_csv_path),
            },
        )
        return CampaignRunResult(3, artifacts.campaign_dir, artifacts.report_path, artifacts.summary_csv_path, report)

    stop_after_failure = False
    for step in campaign.steps:
        if stop_after_failure:
            skipped = _step_result(step, status="skipped", message="Skipped after previous failure.")
            step_results.append(skipped)
            _emit_campaign_event(
                event_callback,
                {
                    "event": "campaign_step_finished",
                    "campaign_id": campaign.campaign_id,
                    "step": step.to_report_dict(),
                    "step_result": skipped,
                },
            )
            continue
        _emit_campaign_event(
            event_callback,
            {
                "event": "campaign_step_started",
                "campaign_id": campaign.campaign_id,
                "step": step.to_report_dict(),
            },
        )
        try:
            result = qualification_runner(
                manifest_ref=step.manifest_ref,
                port=port,
                baud=baud,
                machine_id=machine_id,
                identity_path=identity_path,
                output_root=suite_output_root,
                timeout_ms=step.timeout_ms,
                run_selftest_path=run_selftest_path,
                fixture_id=step.fixture_id,
                operator_prompts=operator_prompts,
                progress_jsonl=progress_jsonl,
                invoker=invoker,
                prompter=prompter,
                gripper_control=gripper_control,
            )
            child_status = str(result.report.get("overall_status") or "fail")
            status = "pass" if int(result.returncode) == 0 and child_status == "pass" else "fail"
            step_result = _step_result(
                step,
                status=status,
                returncode=int(result.returncode),
                report=result.report,
                result=result,
                message="" if status == "pass" else f"Suite finished with status {child_status}.",
            )
            step_results.append(step_result)
            _emit_campaign_event(
                event_callback,
                {
                    "event": "campaign_step_finished",
                    "campaign_id": campaign.campaign_id,
                    "step": step.to_report_dict(),
                    "step_result": step_result,
                    "report": result.report,
                },
            )
        except Exception as exc:
            status = "error"
            step_result = _step_result(step, status=status, message=str(exc))
            step_results.append(step_result)
            _emit_campaign_event(
                event_callback,
                {
                    "event": "campaign_step_finished",
                    "campaign_id": campaign.campaign_id,
                    "step": step.to_report_dict(),
                    "step_result": step_result,
                },
            )
        if step_results[-1]["status"] != "pass" and not continue_on_failure:
            stop_after_failure = True

    report = _build_campaign_report(
        campaign=campaign,
        identity=identity,
        artifacts=artifacts,
        suite_output_root=suite_output_root,
        port=port,
        baud=baud,
        operator_prompts=operator_prompts,
        progress_jsonl=progress_jsonl,
        continue_on_failure=continue_on_failure,
        started_at=started_at,
        finished_at=_now_iso(),
        step_results=step_results,
    )
    _write_campaign_artifacts(report, artifacts)
    _emit_campaign_event(
        event_callback,
        {
            "event": "campaign_finished",
            "campaign_id": campaign.campaign_id,
            "status": report.get("overall_status"),
            "returncode": 0 if report.get("overall_status") == "pass" else 3,
            "campaign_report_path": str(artifacts.report_path),
            "campaign_summary_csv_path": str(artifacts.summary_csv_path),
            "report": report,
        },
    )
    return CampaignRunResult(
        0 if report.get("overall_status") == "pass" else 3,
        artifacts.campaign_dir,
        artifacts.report_path,
        artifacts.summary_csv_path,
        report,
    )


__all__ = [
    "CAMPAIGN_REPORT_SCHEMA",
    "DEFAULT_CAMPAIGN_REF",
    "CampaignError",
    "CampaignRunResult",
    "CampaignStep",
    "QualificationCampaign",
    "load_campaign",
    "run_campaign",
]
