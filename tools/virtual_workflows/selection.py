"""Read-only manifest selection and recommendations for SIL workflows."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from tools.virtual_workflows.registry import (
    MANIFEST_PATH,
    REPO_ROOT,
    get_registered_scenario,
    load_capability_manifest,
)


SELECTION_PLAN_SCHEMA_NAME = "labcraft.sil_selection_plan"
SELECTION_CATALOG_SCHEMA_NAME = "labcraft.sil_selection_catalog"
SELECTION_RECOMMENDATION_SCHEMA_NAME = (
    "labcraft.sil_selection_recommendation"
)
SELECTION_SCHEMA_VERSION = 1
STANDARD_SCENARIO_ID = "print_array_smoke_24_v1"
STANDARD_SEED = 1
STANDARD_TIMEOUT_SECONDS = 60.0


class SelectionError(ValueError):
    """Raised when a manifest selection cannot be planned safely."""


@dataclass(frozen=True)
class SelectionRequest:
    """One deterministic, non-executing manifest selection request."""

    kind: str
    selector_id: str
    platform: str = "windows_sil"
    seed: int = 1
    timeout_override: float | None = None
    pi_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class SelectedScenario:
    """Execution metadata resolved for one ordered manifest scenario."""

    order: int
    scenario_id: str
    registry_id: str
    seed: int
    timeout_seconds: float
    tier: str
    runner_family: str
    assertion_ids: tuple[str, ...]
    capability_ids: tuple[str, ...]
    required_pi_evidence: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "scenario_id": self.scenario_id,
            "registry_id": self.registry_id,
            "seed": self.seed,
            "timeout_seconds": self.timeout_seconds,
            "tier": self.tier,
            "runner_family": self.runner_family,
            "assertion_ids": list(self.assertion_ids),
            "capability_ids": list(self.capability_ids),
            "required_pi_evidence": list(self.required_pi_evidence),
        }


def _manifest_identity(
    manifest: Mapping[str, Any], manifest_path: Path
) -> dict[str, Any]:
    return {
        "schema_name": manifest["schema_name"],
        "schema_version": manifest["schema_version"],
        "manifest_id": manifest["manifest_id"],
        "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }


def _rows_by_id(
    manifest: Mapping[str, Any], section: str
) -> dict[str, Mapping[str, Any]]:
    return {str(row["id"]): row for row in manifest[section]}


def _scenario_platform(
    capability: Mapping[str, Any], requested_platform: str
) -> str:
    layers = set(capability["required_verification_layers"])
    platform_layers = layers & {"host_sil", "pi_sil"}
    required = {
        "host_sil": "windows_sil",
        "pi_sil": "pi_sil",
    }
    if len(platform_layers) == 1:
        capability_platform = required[next(iter(platform_layers))]
        if requested_platform != capability_platform:
            raise SelectionError(
                f"capability {capability['id']!r} requires platform "
                f"{capability_platform!r}, not {requested_platform!r}"
            )
    return requested_platform


def _require_pi_evidence(
    required: Iterable[str], provided: Iterable[str], label: str
) -> None:
    missing = sorted(set(required) - set(provided))
    if missing:
        raise SelectionError(
            f"{label} requires Pi safety evidence: {', '.join(missing)}"
        )


def resolve_selection(
    request: SelectionRequest,
    *,
    manifest_path: str | Path = MANIFEST_PATH,
) -> dict[str, Any]:
    """Resolve a suite, capability, or direct scenario without executing it."""

    path = Path(manifest_path)
    manifest = load_capability_manifest(path)
    scenarios = _rows_by_id(manifest, "scenarios")
    selector_metadata: dict[str, Any]

    if request.kind == "suite":
        suites = _rows_by_id(manifest, "suites")
        try:
            suite = suites[request.selector_id]
        except KeyError as exc:
            raise SelectionError(
                f"unknown suite {request.selector_id!r}"
            ) from exc
        if suite["status"] != "active":
            raise SelectionError(
                f"suite {request.selector_id!r} is {suite['status']!r}"
            )
        if suite["platform"] != request.platform:
            raise SelectionError(
                f"suite {request.selector_id!r} requires platform "
                f"{suite['platform']!r}, not {request.platform!r}"
            )
        required_pi = tuple(suite["requires_pi_safety_evidence"])
        _require_pi_evidence(
            required_pi, request.pi_evidence, f"suite {request.selector_id!r}"
        )
        selected_ids = list(suite["scenario_ids"])
        selector_metadata = {
            "kind": "suite",
            "id": request.selector_id,
            "status": suite["status"],
        }
    elif request.kind == "capability":
        capabilities = _rows_by_id(manifest, "capabilities")
        try:
            capability = capabilities[request.selector_id]
        except KeyError as exc:
            raise SelectionError(
                f"unknown capability {request.selector_id!r}"
            ) from exc
        if capability["status"] not in {"covered", "partial"}:
            raise SelectionError(
                f"capability {request.selector_id!r} is "
                f"{capability['status']!r} and cannot be selected"
            )
        _scenario_platform(capability, request.platform)
        selected_ids = list(capability["active_scenario_ids"])
        if not selected_ids:
            raise SelectionError(
                f"capability {request.selector_id!r} has no active scenarios"
            )
        required_pi = ("preflight", "hardware_proof") if (
            request.platform == "pi_sil"
        ) else ()
        _require_pi_evidence(
            required_pi,
            request.pi_evidence,
            f"capability {request.selector_id!r}",
        )
        selector_metadata = {
            "kind": "capability",
            "id": request.selector_id,
            "status": capability["status"],
        }
    elif request.kind == "scenario":
        registry_matches = {
            str(row["registry_id"]): scenario_id
            for scenario_id, row in scenarios.items()
        }
        try:
            selected_ids = [registry_matches[request.selector_id]]
        except KeyError as exc:
            raise SelectionError(
                f"unknown registered scenario {request.selector_id!r}"
            ) from exc
        selector_metadata = {
            "kind": "scenario",
            "id": request.selector_id,
            "status": "active",
        }
    else:
        raise SelectionError(f"unsupported selector kind {request.kind!r}")

    if request.seed < 0:
        raise SelectionError("seed must be non-negative")
    if request.timeout_override is not None and request.timeout_override <= 0:
        raise SelectionError("timeout override must be positive")

    if request.kind == "suite" and request.selector_id == "standard":
        if selected_ids != [STANDARD_SCENARIO_ID]:
            raise SelectionError("standard suite scenario/order contract drifted")
        if request.seed != STANDARD_SEED:
            raise SelectionError(
                f"standard suite seed is frozen at {STANDARD_SEED}"
            )
        if request.timeout_override not in {None, STANDARD_TIMEOUT_SECONDS}:
            raise SelectionError(
                "standard suite timeout is frozen at "
                f"{STANDARD_TIMEOUT_SECONDS:g} seconds"
            )

    planned: list[SelectedScenario] = []
    for order, scenario_id in enumerate(selected_ids, start=1):
        scenario = scenarios[scenario_id]
        if scenario["status"] != "active":
            raise SelectionError(
                f"scenario {scenario_id!r} is {scenario['status']!r}"
            )
        if request.platform not in scenario["supported_platforms"]:
            raise SelectionError(
                f"scenario {scenario_id!r} does not support platform "
                f"{request.platform!r}"
            )
        scenario_pi = (
            tuple(scenario["pi_safety_evidence"])
            if request.platform == "pi_sil"
            else ()
        )
        _require_pi_evidence(
            scenario_pi, request.pi_evidence, f"scenario {scenario_id!r}"
        )
        definition = get_registered_scenario(str(scenario["registry_id"]))
        timeout = (
            request.timeout_override
            if request.timeout_override is not None
            else float(scenario["timeout_seconds"])
        )
        planned.append(
            SelectedScenario(
                order=order,
                scenario_id=scenario_id,
                registry_id=definition.registry_id,
                seed=request.seed,
                timeout_seconds=float(timeout),
                tier=str(scenario["tier"]),
                runner_family=definition.runner_family,
                assertion_ids=tuple(scenario["assertion_ids"]),
                capability_ids=tuple(scenario["capability_ids"]),
                required_pi_evidence=scenario_pi,
            )
        )

    return {
        "schema_name": SELECTION_PLAN_SCHEMA_NAME,
        "schema_version": SELECTION_SCHEMA_VERSION,
        "manifest": _manifest_identity(manifest, path),
        "selector": selector_metadata,
        "platform": request.platform,
        "readiness": "ready",
        "execution_authorized": False,
        "scenario_count": len(planned),
        "scenarios": [scenario.as_dict() for scenario in planned],
    }


def build_catalog(
    section: str = "all", *, manifest_path: str | Path = MANIFEST_PATH
) -> dict[str, Any]:
    """Build a deterministic, read-only catalog for CLI display."""

    if section not in {"all", "suites", "capabilities"}:
        raise SelectionError(f"unsupported catalog section {section!r}")
    path = Path(manifest_path)
    manifest = load_capability_manifest(path)
    result: dict[str, Any] = {
        "schema_name": SELECTION_CATALOG_SCHEMA_NAME,
        "schema_version": SELECTION_SCHEMA_VERSION,
        "manifest": _manifest_identity(manifest, path),
        "section": section,
        "execution_authorized": False,
    }
    if section in {"all", "suites"}:
        schedules = {
            row["suite_id"]: row for row in manifest["schedules"]
        }
        result["suites"] = [
            {
                "id": row["id"],
                "status": row["status"],
                "kind": row["kind"],
                "platform": row["platform"],
                "scenario_ids": list(row["scenario_ids"]),
                "manual_trigger": {
                    "cadence": schedules[row["id"]]["cadence"],
                    "owner_role": schedules[row["id"]]["owner_role"],
                    "automation_status": schedules[row["id"]][
                        "automation_status"
                    ],
                    "max_evidence_age_days": schedules[row["id"]][
                        "max_evidence_age_days"
                    ],
                },
            }
            for row in manifest["suites"]
        ]
    if section in {"all", "capabilities"}:
        result["capabilities"] = [
            {
                "id": row["id"],
                "status": row["status"],
                "active_scenario_ids": list(row["active_scenario_ids"]),
                "required_verification_layers": list(
                    row["required_verification_layers"]
                ),
            }
            for row in manifest["capabilities"]
        ]
    if section == "all":
        result["scenarios"] = [
            {
                "id": row["id"],
                "registry_id": row["registry_id"],
                "status": row["status"],
                "tier": row["tier"],
                "supported_platforms": list(row["supported_platforms"]),
            }
            for row in manifest["scenarios"]
        ]
    return result


def _normalize_changed_path(value: str | Path, repo_root: Path) -> str:
    raw = str(value).strip()
    if not raw:
        raise SelectionError("changed paths must be nonempty")
    candidate = Path(raw.replace("\\", "/"))
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    try:
        relative = candidate.resolve(strict=False).relative_to(repo_root.resolve())
    except ValueError as exc:
        raise SelectionError(
            f"changed path is outside the repository: {value}"
        ) from exc
    normalized = relative.as_posix()
    if normalized in {"", "."}:
        raise SelectionError("changed path cannot be the repository root")
    return normalized


def discover_changed_paths(repo_root: str | Path = REPO_ROOT) -> tuple[str, ...]:
    """Return staged, unstaged, and untracked repository paths without writes."""

    root = Path(repo_root).resolve()
    commands = (
        ("git", "diff", "--name-only", "HEAD", "--"),
        ("git", "ls-files", "--others", "--exclude-standard"),
    )
    found: set[str] = set()
    for command in commands:
        result = subprocess.run(
            command,
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise SelectionError(
                f"changed-source discovery failed: {result.stderr.strip()}"
            )
        found.update(
            _normalize_changed_path(line, root)
            for line in result.stdout.splitlines()
            if line.strip()
        )
    return tuple(sorted(found))


def _paths_overlap(changed: str, source_area: str) -> bool:
    return (
        changed == source_area
        or changed.startswith(source_area.rstrip("/") + "/")
        or source_area.startswith(changed.rstrip("/") + "/")
    )


def recommend_changed_paths(
    changed_paths: Iterable[str | Path],
    *,
    manifest_path: str | Path = MANIFEST_PATH,
    repo_root: str | Path = REPO_ROOT,
) -> dict[str, Any]:
    """Recommend capabilities/scenarios affected by source paths; never run them."""

    root = Path(repo_root).resolve()
    changed = tuple(
        sorted({_normalize_changed_path(value, root) for value in changed_paths})
    )
    path = Path(manifest_path)
    manifest = load_capability_manifest(path)
    recommendations: list[dict[str, Any]] = []
    ordered_scenarios: list[str] = []
    for capability in manifest["capabilities"]:
        matches = [
            {
                "changed_path": changed_path,
                "related_source_area": source_area,
            }
            for changed_path in changed
            for source_area in capability["related_source_areas"]
            if _paths_overlap(changed_path, source_area)
        ]
        if not matches:
            continue
        scenario_ids = list(capability["active_scenario_ids"])
        for scenario_id in scenario_ids:
            if scenario_id not in ordered_scenarios:
                ordered_scenarios.append(scenario_id)
        recommendations.append(
            {
                "capability_id": capability["id"],
                "status": capability["status"],
                "reasons": matches,
                "scenario_ids": scenario_ids,
            }
        )
    scenario_rows = _rows_by_id(manifest, "scenarios")
    return {
        "schema_name": SELECTION_RECOMMENDATION_SCHEMA_NAME,
        "schema_version": SELECTION_SCHEMA_VERSION,
        "manifest": _manifest_identity(manifest, path),
        "changed_paths": list(changed),
        "execution_authorized": False,
        "recommendations": recommendations,
        "scenarios": [
            {
                "scenario_id": scenario_id,
                "registry_id": scenario_rows[scenario_id]["registry_id"],
            }
            for scenario_id in ordered_scenarios
        ],
    }


def deterministic_json(payload: Mapping[str, Any]) -> str:
    """Serialize planning output consistently for inspection and testing."""

    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


__all__ = [
    "SELECTION_CATALOG_SCHEMA_NAME",
    "SELECTION_PLAN_SCHEMA_NAME",
    "SELECTION_RECOMMENDATION_SCHEMA_NAME",
    "SELECTION_SCHEMA_VERSION",
    "STANDARD_SCENARIO_ID",
    "STANDARD_SEED",
    "STANDARD_TIMEOUT_SECONDS",
    "SelectedScenario",
    "SelectionError",
    "SelectionRequest",
    "build_catalog",
    "deterministic_json",
    "discover_changed_paths",
    "recommend_changed_paths",
    "resolve_selection",
]
