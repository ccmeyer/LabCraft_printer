"""Offline capability coverage evaluation for retained SIL aggregates."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from tools.virtual_workflows.registry import (
    MANIFEST_ID,
    MANIFEST_PATH,
    MANIFEST_SCHEMA_NAME,
    MANIFEST_SCHEMA_VERSION,
    REPO_ROOT,
    load_capability_manifest,
)
from tools.virtual_workflows.report import (
    collect_source_identity,
    validate_report_v1,
)
from tools.virtual_workflows.selection import (
    SELECTION_PLAN_SCHEMA_NAME,
    SELECTION_SCHEMA_VERSION,
)
from tools.virtual_workflows.suite_runner import load_aggregate


COVERAGE_SCHEMA_NAME = "labcraft.sil_capability_evaluation"
COVERAGE_SCHEMA_VERSION = 1
COVERAGE_STATUSES = {"pass", "fail", "incomplete", "missing", "stale"}


class CoverageError(ValueError):
    """Raised when coverage inputs or output violate the Slice 4 contract."""


@dataclass(frozen=True)
class CoverageRunConfig:
    aggregate_paths: tuple[Path, ...]
    output_root: Path
    replay_command: tuple[str, ...]
    repo_root: Path = REPO_ROOT
    manifest_path: Path = MANIFEST_PATH

    def __post_init__(self) -> None:
        if not self.aggregate_paths:
            raise CoverageError("coverage requires at least one aggregate")
        if not self.replay_command:
            raise CoverageError("coverage replay command is required")


@dataclass(frozen=True)
class CoverageExecutionResult:
    evaluation: dict[str, Any]
    evaluation_path: Path
    summary_path: Path

    @property
    def exit_code(self) -> int:
        return coverage_exit_code(self.evaluation)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rows_by_id(payload: Mapping[str, Any], section: str) -> dict[str, Mapping[str, Any]]:
    return {str(row["id"]): row for row in payload[section]}


def _contained_reference(root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise CoverageError(f"{label} path is invalid")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts:
        raise CoverageError(f"{label} path escaped aggregate root")
    path = (root / Path(*pure.parts)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise CoverageError(f"{label} path escaped aggregate root")
    return path


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoverageError(f"could not load {label} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CoverageError(f"{label} must contain an object")
    return payload


def _source_state(source: Mapping[str, Any], target: Mapping[str, Any]) -> str:
    evidence_tree = source.get("source_tree")
    target_tree = target.get("source_tree")
    if not isinstance(evidence_tree, Mapping):
        return "missing"
    if not isinstance(target_tree, Mapping):
        return "error"
    if evidence_tree.get("error") or target_tree.get("error"):
        return "error"
    required = ("schema_name", "schema_version", "scope", "sha256")
    if any(not evidence_tree.get(key) for key in required):
        return "missing"
    if any(not target_tree.get(key) for key in required):
        return "error"
    return "current" if all(
        evidence_tree.get(key) == target_tree.get(key) for key in required
    ) else "stale"


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except (TypeError, ValueError) as exc:
        raise CoverageError(f"invalid report completion timestamp {value!r}") from exc
    return parsed.astimezone(timezone.utc)


def _manifest_identity(path: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_name": MANIFEST_SCHEMA_NAME,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_id": MANIFEST_ID,
        "path": str(path.resolve()),
        "sha256": _sha256(path),
    }


def _load_input(path: Path) -> dict[str, Any]:
    aggregate_path = path.resolve()
    aggregate = load_aggregate(aggregate_path, verify_hashes=True)
    root = aggregate_path.parent
    plan_path = _contained_reference(
        root, aggregate["selection_plan"]["path"], "selection plan"
    )
    plan = _load_json(plan_path, "selection plan")
    if plan.get("schema_name") != SELECTION_PLAN_SCHEMA_NAME:
        raise CoverageError("selection plan schema name is unsupported")
    if plan.get("schema_version") != SELECTION_SCHEMA_VERSION:
        raise CoverageError("selection plan schema version is unsupported")
    if _sha256(plan_path) != aggregate["selection_plan"]["sha256"]:
        raise CoverageError("selection plan SHA-256 mismatch")

    children: list[dict[str, Any]] = []
    for child in aggregate["children"]:
        report_payload = None
        report_path = None
        report_reference = child.get("report")
        if isinstance(report_reference, Mapping):
            report_path = _contained_reference(
                root, report_reference.get("path"), "child report"
            )
            report_payload = _load_json(report_path, "child report")
            validate_report_v1(report_payload)
        children.append(
            {
                "order": child["order"],
                "scenario_id": child["scenario_id"],
                "registry_id": child["registry_id"],
                "outcome": child["outcome"],
                "reasons": list(child.get("reasons") or []),
                "report": report_payload,
                "report_path": report_path,
                "report_reference": dict(report_reference) if report_reference else None,
            }
        )
    return {
        "path": aggregate_path,
        "sha256": _sha256(aggregate_path),
        "aggregate": aggregate,
        "plan": plan,
        "children": children,
    }


def _scenario_assessment(
    scenario: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    *,
    action_catalog: Mapping[str, Mapping[str, Any]],
    target_source: Mapping[str, Any],
    manifest_sha256: str,
) -> dict[str, Any]:
    base = {
        "scenario_id": scenario["id"],
        "registry_id": scenario["registry_id"],
        "status": "missing",
        "reasons": [],
        "evidence": [],
        "required_action_ids": list(scenario["action_ids"]),
        "required_assertion_ids": list(scenario["assertion_ids"]),
        "action_results": [],
        "assertion_results": [],
        "observable_sources": [],
        "source_state": "missing",
        "ended_at_utc": None,
    }
    if not candidates:
        base["reasons"] = ["no selected aggregate contains this required scenario"]
        return base

    unique: dict[str, Mapping[str, Any]] = {}
    without_reports: list[Mapping[str, Any]] = []
    for candidate in candidates:
        report_reference = candidate.get("report_reference")
        digest = report_reference.get("sha256") if isinstance(report_reference, Mapping) else None
        if isinstance(digest, str):
            unique.setdefault(digest, candidate)
        else:
            without_reports.append(candidate)
    if len(unique) > 1 or (unique and without_reports) or len(without_reports) > 1:
        base["status"] = "incomplete"
        base["reasons"] = ["conflicting evidence candidates require explicit disambiguation"]
        return base

    candidate = next(iter(unique.values()), without_reports[0] if without_reports else None)
    assert candidate is not None
    report = candidate.get("report")
    base["evidence"] = [
        {
            "aggregate_path": str(candidate["aggregate_path"]),
            "aggregate_sha256": candidate["aggregate_sha256"],
            "aggregate_run_id": candidate["aggregate_run_id"],
            "child_order": candidate["order"],
            "child_outcome": candidate["outcome"],
            "report_path": str(candidate["report_path"]) if candidate.get("report_path") else None,
            "report_sha256": (
                candidate["report_reference"].get("sha256")
                if candidate.get("report_reference") else None
            ),
        }
    ]
    if candidate["outcome"] not in {"pass", "warning"}:
        base["status"] = "fail"
        base["reasons"] = [
            "selected child failed: " + "; ".join(candidate.get("reasons") or [candidate["outcome"]])
        ]
        return base
    if not isinstance(report, Mapping):
        base["status"] = "missing"
        base["reasons"] = ["selected child has no authoritative report"]
        return base
    if report["classification"]["status"] == "fail":
        base["status"] = "fail"
        base["reasons"] = ["authoritative report classification is fail"]
        return base

    reasons: list[str] = []
    fail_reasons: list[str] = []
    workflow = report["metrics"]["workflow"]["values"]
    action_rows = workflow.get("action_results") or []
    assertion_rows = workflow.get("assertion_results") or []
    actions_by_id: dict[str, list[Mapping[str, Any]]] = {}
    assertions_by_id: dict[str, list[Mapping[str, Any]]] = {}
    for row in action_rows:
        if isinstance(row, Mapping):
            actions_by_id.setdefault(str(row.get("action_id")), []).append(row)
    for row in assertion_rows:
        if isinstance(row, Mapping):
            assertions_by_id.setdefault(str(row.get("assertion_id")), []).append(row)

    for action_id in scenario["action_ids"]:
        rows = actions_by_id.get(str(action_id), [])
        catalog = action_catalog[str(action_id)]
        expected_surface = catalog.get("interaction_surface")
        observed_surfaces = sorted({str(row.get("interaction_surface")) for row in rows})
        statuses = sorted({str(row.get("status")) for row in rows})
        base["action_results"].append(
            {
                "action_id": action_id,
                "expected_surface": expected_surface,
                "observed_surfaces": observed_surfaces,
                "statuses": statuses,
            }
        )
        if not rows:
            reasons.append(f"required action {action_id} is missing")
        elif any(row.get("status") != "pass" for row in rows):
            fail_reasons.append(f"required action {action_id} did not pass")
        elif expected_surface is None:
            reasons.append(f"required action {action_id} has no manifest interaction surface")
        elif observed_surfaces != [expected_surface]:
            fail_reasons.append(
                f"required action {action_id} used {observed_surfaces}, expected {expected_surface}"
            )

    observable_sources: set[str] = set()
    for assertion_id in scenario["assertion_ids"]:
        rows = assertions_by_id.get(str(assertion_id), [])
        decisions = sorted({str(row.get("decision")) for row in rows})
        for row in rows:
            observable_sources.update(str(value) for value in row.get("observable_sources") or [])
        base["assertion_results"].append(
            {"assertion_id": assertion_id, "decisions": decisions}
        )
        if not rows:
            reasons.append(f"required assertion {assertion_id} is missing")
        elif any(row.get("decision") != "pass" for row in rows):
            fail_reasons.append(f"required assertion {assertion_id} did not pass")
    base["observable_sources"] = sorted(observable_sources)

    manifest_matches = candidate["aggregate_manifest_sha256"] == manifest_sha256
    if not manifest_matches:
        reasons.append("aggregate manifest differs from the evaluated manifest")
    source_state = _source_state(report["source"], target_source)
    base["source_state"] = source_state
    base["ended_at_utc"] = report["run"]["ended_at_utc"]
    if fail_reasons:
        base["status"] = "fail"
        base["reasons"] = fail_reasons + reasons
    elif reasons or source_state in {"missing", "error"}:
        if source_state == "missing":
            reasons.append("report has no source-tree fingerprint")
        elif source_state == "error":
            reasons.append("source-tree identity could not be established")
        base["status"] = "incomplete"
        base["reasons"] = reasons
    elif source_state == "stale":
        base["status"] = "stale"
        base["reasons"] = ["report source tree differs from the evaluation target"]
    else:
        base["status"] = "pass"
    return base


def build_coverage_evaluation(
    config: CoverageRunConfig,
    *,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build one deterministic evidence-to-manifest coverage evaluation."""

    manifest_path = config.manifest_path.resolve()
    manifest = load_capability_manifest(manifest_path)
    manifest_identity = _manifest_identity(manifest_path, manifest)
    capabilities = _rows_by_id(manifest, "capabilities")
    scenarios = _rows_by_id(manifest, "scenarios")
    action_catalog = _rows_by_id(manifest["policy"], "action_catalog")
    target_source = collect_source_identity(config.repo_root)
    inputs = [_load_input(path) for path in config.aggregate_paths]

    in_scope: set[str] = set()
    candidates_by_scenario: dict[str, list[dict[str, Any]]] = {}
    input_rows: list[dict[str, Any]] = []
    platforms: set[str] = set()
    for loaded in inputs:
        aggregate = loaded["aggregate"]
        plan = loaded["plan"]
        selector = plan["selector"]
        platforms.add(str(plan["platform"]))
        if selector["kind"] == "capability":
            in_scope.add(str(selector["id"]))
        else:
            for selected in plan["scenarios"]:
                current = scenarios.get(str(selected["scenario_id"]))
                if current is not None:
                    in_scope.update(str(value) for value in current["capability_ids"])
        input_rows.append(
            {
                "path": str(loaded["path"]),
                "sha256": loaded["sha256"],
                "run_id": aggregate["run"]["run_id"],
                "selector": dict(aggregate["run"]["selector"]),
                "platform": aggregate["run"]["platform"],
                "classification": aggregate["classification"]["status"],
            }
        )
        for child in loaded["children"]:
            candidate = dict(child)
            candidate.update(
                {
                    "aggregate_path": loaded["path"],
                    "aggregate_sha256": loaded["sha256"],
                    "aggregate_run_id": aggregate["run"]["run_id"],
                    "aggregate_manifest_sha256": aggregate["manifest"]["sha256"],
                }
            )
            candidates_by_scenario.setdefault(str(child["scenario_id"]), []).append(candidate)

    unknown_scope = sorted(in_scope - set(capabilities))
    if unknown_scope:
        raise CoverageError("aggregate selected unknown capabilities: " + ", ".join(unknown_scope))
    if not in_scope:
        raise CoverageError("coverage inputs select no manifest capabilities")

    scenario_results: dict[str, dict[str, Any]] = {}
    capability_results: list[dict[str, Any]] = []
    now = (evaluated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    for capability_id in sorted(in_scope):
        capability = capabilities[capability_id]
        required_scenarios = [
            str(scenario_id)
            for scenario_id in capability["active_scenario_ids"]
            if set(scenarios[str(scenario_id)]["supported_platforms"]) & platforms
        ]
        for scenario_id in required_scenarios:
            if scenario_id not in scenario_results:
                scenario_results[scenario_id] = _scenario_assessment(
                    scenarios[scenario_id],
                    candidates_by_scenario.get(scenario_id, []),
                    action_catalog=action_catalog,
                    target_source=target_source,
                    manifest_sha256=manifest_identity["sha256"],
                )
        relevant = [scenario_results[scenario_id] for scenario_id in required_scenarios]
        observed_assertions = {
            row["assertion_id"]: row["decisions"]
            for result in relevant
            for row in result["assertion_results"]
        }
        missing_capability_assertions = [
            assertion_id
            for assertion_id in capability["required_assertion_ids"]
            if observed_assertions.get(assertion_id) != ["pass"]
        ]
        layers = list(capability["required_verification_layers"])
        supported_layers = ["contract"]
        if "windows_sil" in platforms:
            supported_layers.append("host_sil")
        if "pi_sil" in platforms:
            supported_layers.append("pi_sil")
        missing_layers = sorted(set(layers) - set(supported_layers))

        statuses = [result["status"] for result in relevant]
        reasons: list[str] = []
        if "fail" in statuses:
            status = "fail"
            reasons.append("one or more required scenarios failed")
        elif not relevant or all(value == "missing" for value in statuses):
            status = "missing"
            reasons.append("no authoritative evidence exists for the capability")
        elif (
            any(value in {"missing", "incomplete"} for value in statuses)
            or missing_capability_assertions
            or missing_layers
        ):
            status = "incomplete"
            reasons.append("required evidence is incomplete")
        elif "stale" in statuses:
            status = "stale"
            reasons.append("otherwise passing evidence is source-stale")
        else:
            status = "pass"
        if missing_capability_assertions:
            reasons.append(
                "missing required assertions: " + ", ".join(missing_capability_assertions)
            )
        if missing_layers:
            reasons.append("missing verification layers: " + ", ".join(missing_layers))

        age_rows = []
        threshold = int(capability["max_evidence_age_days"])
        for result in relevant:
            if result["ended_at_utc"]:
                age_days = max(0.0, (now - _parse_utc(result["ended_at_utc"])).total_seconds() / 86400.0)
                age_rows.append(
                    {
                        "scenario_id": result["scenario_id"],
                        "age_days": round(age_days, 6),
                        "max_evidence_age_days": threshold,
                        "threshold_exceeded": age_days > threshold,
                        "effect": "informational_only",
                    }
                )
        capability_results.append(
            {
                "capability_id": capability_id,
                "manifest_status": capability["status"],
                "status": status,
                "reasons": reasons,
                "required_scenario_ids": required_scenarios,
                "required_assertion_ids": list(capability["required_assertion_ids"]),
                "missing_assertion_ids": missing_capability_assertions,
                "required_verification_layers": layers,
                "missing_verification_layers": missing_layers,
                "scenario_statuses": {
                    result["scenario_id"]: result["status"] for result in relevant
                },
                "interaction_surfaces": sorted(
                    {
                        surface
                        for result in relevant
                        for action in result["action_results"]
                        for surface in action["observed_surfaces"]
                    }
                ),
                "observable_sources": sorted(
                    {source for result in relevant for source in result["observable_sources"]}
                ),
                "evidence_age": age_rows,
                "limitations": list(capability["limitations"]),
            }
        )

    counts = {status: 0 for status in sorted(COVERAGE_STATUSES)}
    for result in capability_results:
        counts[result["status"]] += 1
    overall = "pass" if counts["pass"] == len(capability_results) else "fail"
    run_id = str(uuid.uuid4())
    return {
        "schema_name": COVERAGE_SCHEMA_NAME,
        "schema_version": COVERAGE_SCHEMA_VERSION,
        "run": {
            "run_id": run_id,
            "evaluated_at_utc": now.isoformat().replace("+00:00", "Z"),
            "operator_invoked": True,
            "execution_requested": False,
            "replay_command": list(config.replay_command),
        },
        "manifest": manifest_identity,
        "target_source": target_source,
        "inputs": input_rows,
        "scope": {
            "capability_ids": sorted(in_scope),
            "out_of_scope_capability_ids": sorted(set(capabilities) - in_scope),
            "platforms": sorted(platforms),
        },
        "scenarios": [scenario_results[key] for key in sorted(scenario_results)],
        "capabilities": capability_results,
        "classification": {
            "status": overall,
            "counts": counts,
            "non_pass_count": len(capability_results) - counts["pass"],
        },
        "limitations": [
            "Coverage joins retained SIL evidence and does not prove physical dispensing.",
            "Evidence age is informational and does not schedule or execute tests.",
        ],
    }


def validate_coverage_evaluation(
    payload: Mapping[str, Any], *, verify_inputs: bool = False
) -> None:
    expected = {
        "schema_name", "schema_version", "run", "manifest", "target_source",
        "inputs", "scope", "scenarios", "capabilities", "classification", "limitations",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise CoverageError("coverage evaluation top-level fields are invalid")
    if payload["schema_name"] != COVERAGE_SCHEMA_NAME:
        raise CoverageError("coverage schema name is unsupported")
    if payload["schema_version"] != COVERAGE_SCHEMA_VERSION:
        raise CoverageError("coverage schema version is unsupported")
    run = payload["run"]
    classification = payload["classification"]
    if not isinstance(run, Mapping) or not isinstance(classification, Mapping):
        raise CoverageError("coverage metadata sections must be objects")
    if run.get("execution_requested") is not False or run.get("operator_invoked") is not True:
        raise CoverageError("coverage execution identity is invalid")
    capabilities = payload["capabilities"]
    if not isinstance(capabilities, list) or not capabilities:
        raise CoverageError("coverage has no in-scope capabilities")
    derived = {status: 0 for status in sorted(COVERAGE_STATUSES)}
    for row in capabilities:
        if not isinstance(row, Mapping) or row.get("status") not in COVERAGE_STATUSES:
            raise CoverageError("capability coverage status is invalid")
        derived[str(row["status"])] += 1
    if classification.get("counts") != derived:
        raise CoverageError("coverage status counts drifted")
    expected_status = "pass" if derived["pass"] == len(capabilities) else "fail"
    if classification.get("status") != expected_status:
        raise CoverageError("coverage classification disagrees with capabilities")
    if classification.get("non_pass_count") != len(capabilities) - derived["pass"]:
        raise CoverageError("coverage non-pass count drifted")
    if verify_inputs:
        for row in payload["inputs"]:
            if not isinstance(row, Mapping):
                raise CoverageError("coverage input reference is invalid")
            path = Path(str(row.get("path"))).resolve()
            if not path.is_file() or _sha256(path) != row.get("sha256"):
                raise CoverageError(f"coverage input SHA-256 mismatch: {path}")
            load_aggregate(path, verify_hashes=True)


def coverage_summary(payload: Mapping[str, Any]) -> str:
    validate_coverage_evaluation(payload, verify_inputs=False)
    lines = [
        "SIL capability coverage evaluation",
        f"Status: {payload['classification']['status']}",
        "Source fingerprint: "
        + str(payload["target_source"].get("source_tree", {}).get("sha256") or "unavailable"),
        "Counts: " + ", ".join(
            f"{key}={value}" for key, value in sorted(payload["classification"]["counts"].items())
        ),
        "Capabilities:",
    ]
    for row in payload["capabilities"]:
        lines.append(f"- {row['capability_id']}: {row['status']}")
        for reason in row["reasons"]:
            lines.append(f"  - {reason}")
        old = [age["scenario_id"] for age in row["evidence_age"] if age["threshold_exceeded"]]
        if old:
            lines.append("  - informational age threshold exceeded: " + ", ".join(old))
    lines.append("Replay: " + " ".join(payload["run"]["replay_command"]))
    return "\n".join(lines) + "\n"


def _write_atomic(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise CoverageError(f"refusing to overwrite coverage artifact: {path}")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            raise CoverageError(f"refusing to overwrite coverage artifact: {path}")
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return path


def write_coverage_evaluation(path: str | Path, payload: Mapping[str, Any]) -> Path:
    validate_coverage_evaluation(payload, verify_inputs=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return _write_atomic(Path(path).resolve(), encoded)


def load_coverage_evaluation(path: str | Path, *, verify_inputs: bool = True) -> dict[str, Any]:
    source = Path(path).resolve()
    payload = _load_json(source, "coverage evaluation")
    validate_coverage_evaluation(payload, verify_inputs=verify_inputs)
    return payload


def execute_coverage_evaluation(config: CoverageRunConfig) -> CoverageExecutionResult:
    output_root = config.output_root.resolve()
    run_root = (output_root / "coverage" / f"{_run_stamp()}_{uuid.uuid4().hex[:12]}").resolve()
    if not run_root.is_relative_to(output_root):
        raise CoverageError("coverage output escaped output root")
    run_root.mkdir(parents=True, exist_ok=False)
    evaluation = build_coverage_evaluation(config)
    evaluation_path = write_coverage_evaluation(run_root / "coverage.json", evaluation)
    summary_path = _write_atomic(
        run_root / "summary.txt", coverage_summary(evaluation).encode("utf-8")
    )
    return CoverageExecutionResult(evaluation, evaluation_path, summary_path)


def coverage_exit_code(payload: Mapping[str, Any]) -> int:
    validate_coverage_evaluation(payload, verify_inputs=False)
    return 0 if payload["classification"]["status"] == "pass" else 2


__all__ = [
    "COVERAGE_SCHEMA_NAME", "COVERAGE_SCHEMA_VERSION", "COVERAGE_STATUSES",
    "CoverageError", "CoverageExecutionResult", "CoverageRunConfig",
    "build_coverage_evaluation", "coverage_exit_code", "coverage_summary",
    "execute_coverage_evaluation", "load_coverage_evaluation",
    "validate_coverage_evaluation", "write_coverage_evaluation",
]
