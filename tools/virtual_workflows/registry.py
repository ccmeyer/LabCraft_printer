"""Versioned registry and manifest validation for SIL virtual workflows."""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    Path(__file__).resolve().parent
    / "manifests"
    / "capability_coverage_v1.json"
)
MANIFEST_SCHEMA_NAME = "labcraft.sil_capability_coverage"
MANIFEST_SCHEMA_VERSION = 1
MANIFEST_ID = "sil_capability_coverage_v1"
DEFAULT_SCENARIO_ID = "virtual_print_array_96_v1"

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_URI_CREDENTIAL_PATTERN = re.compile(r"://[^/\s:@]+:[^/\s@]+@")
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)
_CAPABILITY_STATUSES = {"covered", "partial", "planned", "deferred"}
_VERIFICATION_LAYERS = {
    "contract",
    "host_sil",
    "pi_sil",
    "protocol_simulation",
    "hil",
}
_SCENARIO_STATUSES = {"active", "planned"}
_TIERS = {"smoke", "lifecycle", "regression", "stress"}
_PLATFORMS = {"windows_sil", "pi_sil"}
_EXPECTED_OUTCOMES = {"pass", "informational"}
_SUITE_STATUSES = {"active", "planned"}
_SUITE_KINDS = {"standard", "lifecycle", "regression", "stress"}
_CADENCES = {
    "on_demand",
    "every_change",
    "nightly",
    "weekly",
    "monthly",
    "pre_release",
}
_AUTOMATION_STATUSES = {"not_configured", "manual", "automated"}
_ACTION_IMPLEMENTATION_STATUSES = {"embedded", "reusable"}
_ASSERTION_EVIDENCE_KINDS = {"report_path", "pytest"}
_INTERACTION_SURFACES = {"ui", "controller", "model", "simulator", "harness"}
_PI_REQUIRED_EVIDENCE = ("preflight", "hardware_proof")


class RegistryError(ValueError):
    """Raised when a registered scenario cannot be selected or dispatched."""


class ManifestValidationError(ValueError):
    """Raised when the tracked SIL capability manifest is inconsistent."""


@dataclass(frozen=True)
class ScenarioDefinition:
    """Executable compatibility metadata for one registered workflow."""

    registry_id: str
    workload_id: str
    fixture_path: Path
    expected_completion_count: int
    scenario_name: str = "virtual_print_array"
    scenario_version: str = "1"
    runner_family: str = "virtual_print_array"
    supports_pi_evidence: bool = True
    supports_injected_stall: bool = True
    supports_report_sets: bool = True


_FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"
_SCENARIO_DEFINITIONS = {
    "virtual_print_array_96_v1": ScenarioDefinition(
        registry_id="virtual_print_array_96_v1",
        workload_id="virtual_print_array_96_v1",
        fixture_path=_FIXTURE_ROOT / "virtual_print_array_96_v1.json",
        expected_completion_count=96,
        runner_family="composed_journey",
    ),
    "virtual_print_array_384x10_v1": ScenarioDefinition(
        registry_id="virtual_print_array_384x10_v1",
        workload_id="virtual_print_array_384x10_v1",
        fixture_path=_FIXTURE_ROOT / "virtual_print_array_384x10_v1.json",
        expected_completion_count=3840,
        runner_family="composed_journey",
    ),
    "virtual_print_array_24_v1": ScenarioDefinition(
        registry_id="virtual_print_array_24_v1",
        workload_id="virtual_print_array_24_v1",
        fixture_path=_FIXTURE_ROOT / "virtual_print_array_24_v1.json",
        expected_completion_count=24,
        runner_family="composed_journey",
        supports_pi_evidence=False,
        supports_injected_stall=False,
        supports_report_sets=False,
    ),
    "experiment_editor_create_finalize_v1": ScenarioDefinition(
        registry_id="experiment_editor_create_finalize_v1",
        workload_id="experiment_editor_create_finalize_v1",
        fixture_path=(
            _FIXTURE_ROOT / "experiment_editor_create_finalize_v1.json"
        ),
        expected_completion_count=1,
        scenario_name="experiment_editor_create_finalize",
        runner_family="composed_journey",
        supports_pi_evidence=False,
        supports_injected_stall=False,
        supports_report_sets=False,
    ),
    "experiment_editor_prestart_rename_refinalize_v1": ScenarioDefinition(
        registry_id="experiment_editor_prestart_rename_refinalize_v1",
        workload_id="experiment_editor_prestart_rename_refinalize_v1",
        fixture_path=(
            _FIXTURE_ROOT
            / "experiment_editor_prestart_rename_refinalize_v1.json"
        ),
        expected_completion_count=2,
        scenario_name="experiment_editor_prestart_rename_refinalize",
        runner_family="composed_journey",
        supports_pi_evidence=False,
        supports_injected_stall=False,
        supports_report_sets=False,
    ),
    "experiment_editor_post_start_lock_v1": ScenarioDefinition(
        registry_id="experiment_editor_post_start_lock_v1",
        workload_id="experiment_editor_post_start_lock_v1",
        fixture_path=(
            _FIXTURE_ROOT / "experiment_editor_post_start_lock_v1.json"
        ),
        expected_completion_count=2,
        scenario_name="experiment_editor_post_start_lock",
        runner_family="composed_journey",
        supports_pi_evidence=False,
        supports_injected_stall=False,
        supports_report_sets=False,
    ),
    "print_array_soft_stop_resume_24_v1": ScenarioDefinition(
        registry_id="print_array_soft_stop_resume_24_v1",
        workload_id="print_array_soft_stop_resume_24_v1",
        fixture_path=(
            _FIXTURE_ROOT / "print_array_soft_stop_resume_24_v1.json"
        ),
        expected_completion_count=24,
        scenario_name="print_array_soft_stop_resume",
        runner_family="composed_journey",
        supports_pi_evidence=False,
        supports_injected_stall=False,
        supports_report_sets=False,
    ),
    "authoritative_reload_resume_24_v1": ScenarioDefinition(
        registry_id="authoritative_reload_resume_24_v1",
        workload_id="authoritative_reload_resume_24_v1",
        fixture_path=(
            _FIXTURE_ROOT / "authoritative_reload_resume_24_v1.json"
        ),
        expected_completion_count=24,
        scenario_name="authoritative_reload_resume",
        runner_family="composed_journey",
        supports_pi_evidence=False,
        supports_injected_stall=False,
        supports_report_sets=False,
    ),
    "print_array_multi_stock_24x2_v1": ScenarioDefinition(
        registry_id="print_array_multi_stock_24x2_v1",
        workload_id="print_array_multi_stock_24x2_v1",
        fixture_path=(
            _FIXTURE_ROOT / "print_array_multi_stock_24x2_v1.json"
        ),
        expected_completion_count=48,
        scenario_name="print_array_multi_stock_head_exchange",
        runner_family="composed_journey",
        supports_pi_evidence=False,
        supports_injected_stall=False,
        supports_report_sets=False,
    ),
    "print_array_mixed_mode_24x2_v1": ScenarioDefinition(
        registry_id="print_array_mixed_mode_24x2_v1",
        workload_id="print_array_mixed_mode_24x2_v1",
        fixture_path=(
            _FIXTURE_ROOT / "print_array_mixed_mode_24x2_v1.json"
        ),
        expected_completion_count=48,
        scenario_name="print_array_mixed_droplet_stream",
        runner_family="composed_journey",
        supports_pi_evidence=False,
        supports_injected_stall=False,
        supports_report_sets=False,
    ),
    "print_array_disconnect_mid_array_24_v1": ScenarioDefinition(
        registry_id="print_array_disconnect_mid_array_24_v1",
        workload_id="print_array_disconnect_mid_array_24_v1",
        fixture_path=(
            _FIXTURE_ROOT / "print_array_disconnect_mid_array_24_v1.json"
        ),
        expected_completion_count=24,
        scenario_name="print_array_disconnect_fail_closed",
        runner_family="composed_journey",
        supports_pi_evidence=False,
        supports_injected_stall=False,
        supports_report_sets=False,
    ),
}
REGISTERED_SCENARIOS: Mapping[str, ScenarioDefinition] = MappingProxyType(
    _SCENARIO_DEFINITIONS
)


def registered_scenario_ids() -> tuple[str, ...]:
    """Return stable CLI scenario IDs in default-first display order."""

    return tuple(REGISTERED_SCENARIOS)


def get_registered_scenario(registry_id: str) -> ScenarioDefinition:
    """Return one registered definition or fail with a stable message."""

    normalized = str(registry_id or "").strip()
    try:
        return REGISTERED_SCENARIOS[normalized]
    except KeyError as exc:
        raise RegistryError(f"unsupported registered scenario: {normalized!r}") from exc


def run_registered_scenario(
    registry_id: str,
    **config_values: Any,
) -> dict[str, Any]:
    """Dispatch through the existing compatibility config and scenario runner."""

    definition = get_registered_scenario(registry_id)
    requested_id = config_values.pop("scenario_id", definition.workload_id)
    if requested_id != definition.workload_id:
        raise RegistryError(
            "registered scenario/workload mismatch: "
            f"{definition.registry_id!r} cannot dispatch {requested_id!r}"
        )

    # Keep CLI help and registry inspection independent of Qt/application imports.
    if definition.runner_family == "composed_journey":
        injected_ms = int(config_values.get("inject_ui_stall_ms", 0))
        injected_after = int(config_values.get("inject_after_completion", 48))
        pi_preflight = config_values.get("pi_preflight_path")
        pi_proof = config_values.get("pi_hardware_proof_path")
        if not definition.supports_injected_stall and (
            injected_ms != 0 or injected_after != 48
        ):
            raise RegistryError(
                "composed journeys do not support fault injection"
            )
        if not definition.supports_pi_evidence and (
            pi_preflight is not None or pi_proof is not None
        ):
            raise RegistryError(
                "composed journeys do not support Pi evidence"
            )
        if not definition.supports_injected_stall:
            config_values.pop("inject_ui_stall_ms", None)
            config_values.pop("inject_after_completion", None)
        if not definition.supports_pi_evidence:
            config_values.pop("pi_preflight_path", None)
            config_values.pop("pi_hardware_proof_path", None)
        from tools.virtual_workflows.journeys import (
            JourneyRunConfig,
            run_composed_journey,
        )

        config = JourneyRunConfig(
            scenario_id=definition.workload_id,
            **config_values,
        )
        return run_composed_journey(config)
    if definition.runner_family == "virtual_print_array":
        config_values.pop("seed", None)
        if not definition.supports_injected_stall:
            injected_ms = config_values.get("inject_ui_stall_ms", 0)
            injected_after = config_values.get("inject_after_completion", 48)
            if int(injected_ms) != 0 or int(injected_after) != 48:
                raise RegistryError(
                    "print-array lifecycle scenarios do not support "
                    "injected-stall controls"
                )
        if not definition.supports_pi_evidence and (
            config_values.get("pi_preflight_path") is not None
            or config_values.get("pi_hardware_proof_path") is not None
        ):
            raise RegistryError(
                "print-array lifecycle scenarios do not support Pi evidence"
            )
        from tools.virtual_workflows.scenarios import (
            VirtualPrintArrayScenarioConfig,
            run_virtual_print_array_scenario,
        )

        config = VirtualPrintArrayScenarioConfig(
            scenario_id=definition.workload_id,
            **config_values,
        )
        return run_virtual_print_array_scenario(config)
    if definition.runner_family == "experiment_editor":
        injected_ms = config_values.pop("inject_ui_stall_ms", 0)
        injected_after = config_values.pop("inject_after_completion", 48)
        pi_preflight = config_values.pop("pi_preflight_path", None)
        pi_proof = config_values.pop("pi_hardware_proof_path", None)
        if int(injected_ms) != 0 or int(injected_after) != 48:
            raise RegistryError(
                "editor lifecycle scenarios do not support injected-stall controls"
            )
        if pi_preflight is not None or pi_proof is not None:
            raise RegistryError(
                "editor lifecycle scenarios do not support Pi evidence"
            )
        from tools.virtual_workflows.editor_scenarios import (
            EditorLifecycleScenarioConfig,
            POST_START_LOCK_WORKLOAD_ID,
            run_editor_create_finalize_scenario,
            run_editor_post_start_lock_scenario,
        )

        config = EditorLifecycleScenarioConfig(
            scenario_id=definition.workload_id,
            **config_values,
        )
        if definition.workload_id == POST_START_LOCK_WORKLOAD_ID:
            return run_editor_post_start_lock_scenario(config)
        return run_editor_create_finalize_scenario(config)
    raise RegistryError(
        f"unsupported runner family: {definition.runner_family!r}"
    )


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestValidationError(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ManifestValidationError(f"{label} must be an array")
    return value


def _require_keys(
    value: Mapping[str, Any],
    *,
    label: str,
    expected: set[str],
) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        raise ManifestValidationError(f"{label} is missing fields: {missing}")
    if unknown:
        raise ManifestValidationError(f"{label} has unknown fields: {unknown}")


def _require_id(value: Any, label: str) -> str:
    text = str(value or "")
    if not _ID_PATTERN.fullmatch(text):
        raise ManifestValidationError(f"{label} is not a stable ID: {text!r}")
    return text


def _require_unique_ids(rows: list[Any], label: str) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(rows):
        row = _require_mapping(raw, f"{label}[{index}]")
        row_id = _require_id(row.get("id"), f"{label}[{index}].id")
        if row_id in result:
            raise ManifestValidationError(f"{label} contains duplicate ID {row_id!r}")
        result[row_id] = row
    return result


def _require_string_list(value: Any, label: str) -> list[str]:
    rows = _require_list(value, label)
    result: list[str] = []
    for index, item in enumerate(rows):
        if not isinstance(item, str) or not item:
            raise ManifestValidationError(f"{label}[{index}] must be a nonempty string")
        result.append(item)
    if len(result) != len(set(result)):
        raise ManifestValidationError(f"{label} contains duplicate values")
    return result


def _require_enum(value: Any, label: str, allowed: set[str]) -> str:
    if value not in allowed:
        raise ManifestValidationError(
            f"{label} must be one of {sorted(allowed)}, got {value!r}"
        )
    return str(value)


def _portable_repo_path(value: Any, label: str, *, must_exist: bool) -> Path:
    if not isinstance(value, str) or not value:
        raise ManifestValidationError(f"{label} must be a repository-relative path")
    if "\\" in value or re.match(r"^[A-Za-z]:", value):
        raise ManifestValidationError(f"{label} must use portable POSIX separators")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts:
        raise ManifestValidationError(f"{label} must remain beneath the repository")
    resolved = (REPO_ROOT / Path(*pure.parts)).resolve()
    if resolved != REPO_ROOT and REPO_ROOT not in resolved.parents:
        raise ManifestValidationError(f"{label} escaped the repository")
    if must_exist and not resolved.exists():
        raise ManifestValidationError(f"{label} does not exist: {value}")
    return resolved


def _validate_test_node(value: Any, label: str) -> None:
    if not isinstance(value, str) or value.count("::") != 1:
        raise ManifestValidationError(f"{label} must be path::test_function")
    path_text, function_text = value.split("::", 1)
    function_name = function_text.split("[", 1)[0]
    if not function_name.startswith("test_"):
        raise ManifestValidationError(f"{label} must name a pytest test function")
    path = _portable_repo_path(path_text, label, must_exist=True)
    if path.suffix != ".py" or not path_text.startswith("tests/"):
        raise ManifestValidationError(f"{label} must reference a Python test file")
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise ManifestValidationError(f"{label} could not be inspected: {exc}") from exc
    functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if function_name not in functions:
        raise ManifestValidationError(
            f"{label} references missing test function {function_name!r}"
        )


def _validate_no_secrets(value: Any, label: str = "manifest") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
                raise ManifestValidationError(
                    f"{label} contains secret-like field {key!r}"
                )
            _validate_no_secrets(item, f"{label}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_no_secrets(item, f"{label}[{index}]")
    elif isinstance(value, str) and _URI_CREDENTIAL_PATTERN.search(value):
        raise ManifestValidationError(f"{label} contains URI credentials")


def _fixture_identity(path: Path, label: str) -> tuple[str, int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestValidationError(f"{label} is not valid JSON: {exc}") from exc
    fixture = _require_mapping(payload, label)
    workload = _require_mapping(fixture.get("workload"), f"{label}.workload")
    completion_count = workload.get("completion_count")
    if not isinstance(completion_count, int) or completion_count <= 0:
        raise ManifestValidationError(
            f"{label}.workload.completion_count must be positive"
        )
    return str(fixture.get("fixture_id") or ""), completion_count


def load_capability_manifest(path: str | Path = MANIFEST_PATH) -> dict[str, Any]:
    """Load and validate a capability manifest without mutating it."""

    manifest_path = Path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestValidationError(
            f"could not load SIL capability manifest {manifest_path}: {exc}"
        ) from exc
    validate_capability_manifest(payload)
    return payload


def validate_capability_manifest(payload: Mapping[str, Any]) -> None:
    """Validate schema, registry drift, references, paths, and safety policy."""

    manifest = _require_mapping(payload, "manifest")
    _require_keys(
        manifest,
        label="manifest",
        expected={
            "schema_name",
            "schema_version",
            "manifest_id",
            "capabilities",
            "scenarios",
            "suites",
            "schedules",
            "policy",
        },
    )
    if manifest["schema_name"] != MANIFEST_SCHEMA_NAME:
        raise ManifestValidationError("manifest.schema_name is unsupported")
    if manifest["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise ManifestValidationError("manifest.schema_version is unsupported")
    if manifest["manifest_id"] != MANIFEST_ID:
        raise ManifestValidationError("manifest.manifest_id is unsupported")
    _validate_no_secrets(manifest)

    policy = _require_mapping(manifest["policy"], "manifest.policy")
    _require_keys(
        policy,
        label="manifest.policy",
        expected={
            "default_registry_id",
            "standard_forbidden_tiers",
            "pi_required_evidence",
            "path_policy",
            "generated_evidence_updates_manifest",
            "coverage_join_status",
            "action_catalog",
            "assertion_catalog",
        },
    )
    if policy["default_registry_id"] != DEFAULT_SCENARIO_ID:
        raise ManifestValidationError("manifest.policy.default_registry_id drifted")
    if policy["path_policy"] != "repository_relative_posix":
        raise ManifestValidationError("manifest.policy.path_policy is unsupported")
    if policy["generated_evidence_updates_manifest"] is not False:
        raise ManifestValidationError(
            "generated evidence must not update the tracked manifest"
        )
    if policy["coverage_join_status"] != "implemented_milestone_8_slice_4":
        raise ManifestValidationError(
            "manifest.policy.coverage_join_status is unsupported"
        )
    forbidden_tiers = set(
        _require_string_list(
            policy["standard_forbidden_tiers"],
            "manifest.policy.standard_forbidden_tiers",
        )
    )
    if forbidden_tiers != {"lifecycle", "regression", "stress"}:
        raise ManifestValidationError("standard forbidden tiers are invalid")
    pi_required = tuple(
        _require_string_list(
            policy["pi_required_evidence"],
            "manifest.policy.pi_required_evidence",
        )
    )
    if pi_required != _PI_REQUIRED_EVIDENCE:
        raise ManifestValidationError("Pi suites require preflight and hardware proof")

    action_rows = _require_unique_ids(
        _require_list(policy["action_catalog"], "manifest.policy.action_catalog"),
        "manifest.policy.action_catalog",
    )
    for action_id, action in action_rows.items():
        expected_action_fields = {"id", "implementation_status", "source_path"}
        if "interaction_surface" in action:
            expected_action_fields.add("interaction_surface")
        _require_keys(
            action,
            label=f"action {action_id}",
            expected=expected_action_fields,
        )
        _require_enum(
            action["implementation_status"],
            f"action {action_id}.implementation_status",
            _ACTION_IMPLEMENTATION_STATUSES,
        )
        _portable_repo_path(
            action["source_path"],
            f"action {action_id}.source_path",
            must_exist=True,
        )
        if "interaction_surface" in action:
            _require_enum(
                action["interaction_surface"],
                f"action {action_id}.interaction_surface",
                _INTERACTION_SURFACES,
            )

    assertion_rows = _require_unique_ids(
        _require_list(
            policy["assertion_catalog"],
            "manifest.policy.assertion_catalog",
        ),
        "manifest.policy.assertion_catalog",
    )
    for assertion_id, assertion in assertion_rows.items():
        _require_keys(
            assertion,
            label=f"assertion {assertion_id}",
            expected={"id", "evidence_kind", "evidence_path", "test_node_ids"},
        )
        kind = _require_enum(
            assertion["evidence_kind"],
            f"assertion {assertion_id}.evidence_kind",
            _ASSERTION_EVIDENCE_KINDS,
        )
        evidence_path = assertion["evidence_path"]
        if kind == "report_path":
            if not isinstance(evidence_path, str) or not evidence_path:
                raise ManifestValidationError(
                    f"assertion {assertion_id}.evidence_path is required"
                )
        elif evidence_path is not None:
            raise ManifestValidationError(
                f"assertion {assertion_id}.evidence_path must be null for pytest"
            )
        test_nodes = _require_string_list(
            assertion["test_node_ids"],
            f"assertion {assertion_id}.test_node_ids",
        )
        if not test_nodes:
            raise ManifestValidationError(
                f"assertion {assertion_id} requires a current test"
            )
        for index, node in enumerate(test_nodes):
            _validate_test_node(node, f"assertion {assertion_id}.test_node_ids[{index}]")

    scenario_rows = _require_unique_ids(
        _require_list(manifest["scenarios"], "manifest.scenarios"),
        "manifest.scenarios",
    )
    registry_ids: dict[str, str] = {}
    for scenario_id, scenario in scenario_rows.items():
        _require_keys(
            scenario,
            label=f"scenario {scenario_id}",
            expected={
                "id",
                "version",
                "status",
                "registry_id",
                "workload_fixture_id",
                "workload_fixture_path",
                "tier",
                "suite_ids",
                "supported_platforms",
                "timeout_seconds",
                "action_ids",
                "assertion_ids",
                "capability_ids",
                "required_artifacts",
                "expected_outcome",
                "limitations",
                "test_node_ids",
                "pi_safety_evidence",
            },
        )
        if scenario["version"] != 1:
            raise ManifestValidationError(f"scenario {scenario_id}.version is unsupported")
        status = _require_enum(
            scenario["status"], f"scenario {scenario_id}.status", _SCENARIO_STATUSES
        )
        tier = _require_enum(
            scenario["tier"], f"scenario {scenario_id}.tier", _TIERS
        )
        _require_enum(
            scenario["expected_outcome"],
            f"scenario {scenario_id}.expected_outcome",
            _EXPECTED_OUTCOMES,
        )
        registry_id = _require_id(
            scenario["registry_id"], f"scenario {scenario_id}.registry_id"
        )
        if registry_id in registry_ids:
            raise ManifestValidationError(
                f"registry ID {registry_id!r} is used by multiple scenarios"
            )
        registry_ids[registry_id] = scenario_id
        try:
            definition = get_registered_scenario(registry_id)
        except RegistryError as exc:
            raise ManifestValidationError(str(exc)) from exc
        if scenario["workload_fixture_id"] != definition.workload_id:
            raise ManifestValidationError(
                f"scenario {scenario_id}.workload_fixture_id drifted"
            )
        fixture_path = _portable_repo_path(
            scenario["workload_fixture_path"],
            f"scenario {scenario_id}.workload_fixture_path",
            must_exist=True,
        )
        expected_fixture_path = definition.fixture_path.resolve()
        if fixture_path != expected_fixture_path:
            raise ManifestValidationError(
                f"scenario {scenario_id}.workload_fixture_path drifted"
            )
        fixture_id, completion_count = _fixture_identity(
            fixture_path,
            f"scenario {scenario_id} fixture",
        )
        if fixture_id != definition.workload_id:
            raise ManifestValidationError(f"scenario {scenario_id} fixture ID drifted")
        if completion_count != definition.expected_completion_count:
            raise ManifestValidationError(
                f"scenario {scenario_id} completion count drifted"
            )
        if not isinstance(scenario["timeout_seconds"], (int, float)) or (
            scenario["timeout_seconds"] <= 0
        ):
            raise ManifestValidationError(
                f"scenario {scenario_id}.timeout_seconds must be positive"
            )
        action_ids = _require_string_list(
            scenario["action_ids"], f"scenario {scenario_id}.action_ids"
        )
        assertion_ids = _require_string_list(
            scenario["assertion_ids"], f"scenario {scenario_id}.assertion_ids"
        )
        if status == "active" and not assertion_ids:
            raise ManifestValidationError(
                f"active scenario {scenario_id} requires assertions"
            )
        unknown_actions = sorted(set(action_ids) - set(action_rows))
        unknown_assertions = sorted(set(assertion_ids) - set(assertion_rows))
        if unknown_actions:
            raise ManifestValidationError(
                f"scenario {scenario_id} has unknown actions: {unknown_actions}"
            )
        if unknown_assertions:
            raise ManifestValidationError(
                f"scenario {scenario_id} has unknown assertions: {unknown_assertions}"
            )
        platforms = set(
            _require_string_list(
                scenario["supported_platforms"],
                f"scenario {scenario_id}.supported_platforms",
            )
        )
        if not platforms or not platforms <= _PLATFORMS:
            raise ManifestValidationError(
                f"scenario {scenario_id} has unsupported platforms"
            )
        pi_evidence = tuple(
            _require_string_list(
                scenario["pi_safety_evidence"],
                f"scenario {scenario_id}.pi_safety_evidence",
            )
        )
        if ("pi_sil" in platforms) != (pi_evidence == _PI_REQUIRED_EVIDENCE):
            raise ManifestValidationError(
                f"scenario {scenario_id} Pi safety evidence is inconsistent"
            )
        _require_string_list(
            scenario["suite_ids"], f"scenario {scenario_id}.suite_ids"
        )
        _require_string_list(
            scenario["capability_ids"], f"scenario {scenario_id}.capability_ids"
        )
        if not _require_string_list(
            scenario["required_artifacts"],
            f"scenario {scenario_id}.required_artifacts",
        ):
            raise ManifestValidationError(
                f"scenario {scenario_id} requires artifact declarations"
            )
        if not _require_string_list(
            scenario["limitations"], f"scenario {scenario_id}.limitations"
        ):
            raise ManifestValidationError(
                f"scenario {scenario_id} requires explicit limitations"
            )
        test_nodes = _require_string_list(
            scenario["test_node_ids"], f"scenario {scenario_id}.test_node_ids"
        )
        if status == "active" and not test_nodes:
            raise ManifestValidationError(
                f"active scenario {scenario_id} requires tests"
            )
        for index, node in enumerate(test_nodes):
            _validate_test_node(node, f"scenario {scenario_id}.test_node_ids[{index}]")
        if tier in forbidden_tiers and "standard" in scenario["suite_ids"]:
            raise ManifestValidationError(
                f"stress scenario {scenario_id} cannot join standard"
            )

    if set(registry_ids) != set(REGISTERED_SCENARIOS):
        missing = sorted(set(REGISTERED_SCENARIOS) - set(registry_ids))
        extra = sorted(set(registry_ids) - set(REGISTERED_SCENARIOS))
        raise ManifestValidationError(
            f"manifest/registry scenario drift; missing={missing}, extra={extra}"
        )
    referenced_actions = {
        action_id
        for scenario in scenario_rows.values()
        for action_id in scenario["action_ids"]
    }
    referenced_assertions = {
        assertion_id
        for scenario in scenario_rows.values()
        for assertion_id in scenario["assertion_ids"]
    }
    unused_actions = sorted(
        action_id
        for action_id in set(action_rows) - referenced_actions
        if action_rows[action_id]["implementation_status"] != "reusable"
    )
    unused_assertions = sorted(set(assertion_rows) - referenced_assertions)
    if unused_actions:
        raise ManifestValidationError(
            f"manifest has unreferenced actions: {unused_actions}"
        )
    if unused_assertions:
        raise ManifestValidationError(
            f"manifest has unreferenced assertions: {unused_assertions}"
        )

    capability_rows = _require_unique_ids(
        _require_list(manifest["capabilities"], "manifest.capabilities"),
        "manifest.capabilities",
    )
    for capability_id, capability in capability_rows.items():
        _require_keys(
            capability,
            label=f"capability {capability_id}",
            expected={
                "id",
                "risk",
                "owner_role",
                "status",
                "required_verification_layers",
                "active_scenario_ids",
                "required_assertion_ids",
                "related_source_areas",
                "limitations",
                "max_evidence_age_days",
            },
        )
        status = _require_enum(
            capability["status"],
            f"capability {capability_id}.status",
            _CAPABILITY_STATUSES,
        )
        for field in ("risk", "owner_role"):
            if not isinstance(capability[field], str) or not capability[field]:
                raise ManifestValidationError(
                    f"capability {capability_id}.{field} must be nonempty"
                )
        layers = set(
            _require_string_list(
                capability["required_verification_layers"],
                f"capability {capability_id}.required_verification_layers",
            )
        )
        if not layers or not layers <= _VERIFICATION_LAYERS:
            raise ManifestValidationError(
                f"capability {capability_id} has unsupported verification layers"
            )
        active_scenarios = _require_string_list(
            capability["active_scenario_ids"],
            f"capability {capability_id}.active_scenario_ids",
        )
        required_assertions = _require_string_list(
            capability["required_assertion_ids"],
            f"capability {capability_id}.required_assertion_ids",
        )
        unknown_scenarios = sorted(set(active_scenarios) - set(scenario_rows))
        unknown_assertions = sorted(set(required_assertions) - set(assertion_rows))
        if unknown_scenarios:
            raise ManifestValidationError(
                f"capability {capability_id} has unknown scenarios: {unknown_scenarios}"
            )
        if unknown_assertions:
            raise ManifestValidationError(
                f"capability {capability_id} has unknown assertions: {unknown_assertions}"
            )
        if status == "covered":
            if not active_scenarios or not required_assertions:
                raise ManifestValidationError(
                    f"covered capability {capability_id} requires scenarios and assertions"
                )
        if active_scenarios and not all(
            capability_id in scenario_rows[scenario_id]["capability_ids"]
            for scenario_id in active_scenarios
        ):
            raise ManifestValidationError(
                f"capability {capability_id} scenario membership drifted"
            )
        if required_assertions and active_scenarios:
            if not any(
                capability_id in scenario_rows[scenario_id]["capability_ids"]
                and set(required_assertions)
                <= set(scenario_rows[scenario_id]["assertion_ids"])
                for scenario_id in active_scenarios
            ):
                raise ManifestValidationError(
                    f"capability {capability_id} lacks assertion-backed scenario"
                )
        if status in {"planned", "deferred"} and active_scenarios:
            raise ManifestValidationError(
                f"{status} capability {capability_id} cannot claim active scenarios"
            )
        source_areas = _require_string_list(
            capability["related_source_areas"],
            f"capability {capability_id}.related_source_areas",
        )
        for index, path in enumerate(source_areas):
            _portable_repo_path(
                path,
                f"capability {capability_id}.related_source_areas[{index}]",
                must_exist=True,
            )
        if not _require_string_list(
            capability["limitations"],
            f"capability {capability_id}.limitations",
        ):
            raise ManifestValidationError(
                f"capability {capability_id} requires explicit limitations"
            )
        age = capability["max_evidence_age_days"]
        if age is not None and (not isinstance(age, int) or age <= 0):
            raise ManifestValidationError(
                f"capability {capability_id}.max_evidence_age_days is invalid"
            )

    for scenario_id, scenario in scenario_rows.items():
        unknown_capabilities = sorted(
            set(scenario["capability_ids"]) - set(capability_rows)
        )
        if unknown_capabilities:
            raise ManifestValidationError(
                f"scenario {scenario_id} has unknown capabilities: "
                f"{unknown_capabilities}"
            )

    suite_rows = _require_unique_ids(
        _require_list(manifest["suites"], "manifest.suites"),
        "manifest.suites",
    )
    for suite_id, suite in suite_rows.items():
        _require_keys(
            suite,
            label=f"suite {suite_id}",
            expected={
                "id",
                "status",
                "kind",
                "platform",
                "scenario_ids",
                "requires_pi_safety_evidence",
            },
        )
        status = _require_enum(
            suite["status"], f"suite {suite_id}.status", _SUITE_STATUSES
        )
        kind = _require_enum(
            suite["kind"], f"suite {suite_id}.kind", _SUITE_KINDS
        )
        platform = _require_enum(
            suite["platform"], f"suite {suite_id}.platform", _PLATFORMS
        )
        scenario_ids = _require_string_list(
            suite["scenario_ids"], f"suite {suite_id}.scenario_ids"
        )
        if status == "active" and not scenario_ids:
            raise ManifestValidationError(f"active suite {suite_id} has no scenarios")
        unknown_scenarios = sorted(set(scenario_ids) - set(scenario_rows))
        if unknown_scenarios:
            raise ManifestValidationError(
                f"suite {suite_id} has unknown scenarios: {unknown_scenarios}"
            )
        required_pi = tuple(
            _require_string_list(
                suite["requires_pi_safety_evidence"],
                f"suite {suite_id}.requires_pi_safety_evidence",
            )
        )
        if (platform == "pi_sil") != (required_pi == _PI_REQUIRED_EVIDENCE):
            raise ManifestValidationError(
                f"suite {suite_id} Pi safety evidence is inconsistent"
            )
        for scenario_id in scenario_ids:
            scenario = scenario_rows[scenario_id]
            if suite_id not in scenario["suite_ids"]:
                raise ManifestValidationError(
                    f"suite {suite_id} membership drifted for {scenario_id}"
                )
            if platform not in scenario["supported_platforms"]:
                raise ManifestValidationError(
                    f"suite {suite_id} platform is unsupported by {scenario_id}"
                )
            if kind == "standard" and (
                scenario["tier"] != "smoke" or platform == "pi_sil"
            ):
                raise ManifestValidationError(
                    f"suite {suite_id} can select only Windows smoke scenarios"
                )
            if kind == "stress" and scenario["tier"] != "stress":
                raise ManifestValidationError(
                    f"stress suite {suite_id} selected non-stress scenario"
                )

    for scenario_id, scenario in scenario_rows.items():
        unknown_suites = sorted(set(scenario["suite_ids"]) - set(suite_rows))
        if unknown_suites:
            raise ManifestValidationError(
                f"scenario {scenario_id} has unknown suites: {unknown_suites}"
            )
        reverse_suites = {
            suite_id
            for suite_id, suite in suite_rows.items()
            if scenario_id in suite["scenario_ids"]
        }
        if reverse_suites != set(scenario["suite_ids"]):
            raise ManifestValidationError(
                f"scenario {scenario_id} suite membership drifted"
            )

    standard = suite_rows.get("standard")
    if standard is None or standard["scenario_ids"] != [
        "print_array_smoke_24_v1"
    ]:
        raise ManifestValidationError(
            "standard suite scenario/order contract drifted"
        )
    standard_scenario = scenario_rows["print_array_smoke_24_v1"]
    if float(standard_scenario["timeout_seconds"]) != 60.0:
        raise ManifestValidationError(
            "standard suite timeout contract drifted"
        )

    schedule_rows = _require_unique_ids(
        _require_list(manifest["schedules"], "manifest.schedules"),
        "manifest.schedules",
    )
    scheduled_suites: set[str] = set()
    for schedule_id, schedule in schedule_rows.items():
        _require_keys(
            schedule,
            label=f"schedule {schedule_id}",
            expected={
                "id",
                "suite_id",
                "cadence",
                "owner_role",
                "automation_status",
                "max_evidence_age_days",
            },
        )
        suite_id = _require_id(
            schedule["suite_id"], f"schedule {schedule_id}.suite_id"
        )
        if suite_id not in suite_rows:
            raise ManifestValidationError(
                f"schedule {schedule_id} references unknown suite {suite_id!r}"
            )
        if suite_id in scheduled_suites:
            raise ManifestValidationError(
                f"suite {suite_id!r} has duplicate schedules"
            )
        scheduled_suites.add(suite_id)
        _require_enum(
            schedule["cadence"], f"schedule {schedule_id}.cadence", _CADENCES
        )
        _require_enum(
            schedule["automation_status"],
            f"schedule {schedule_id}.automation_status",
            _AUTOMATION_STATUSES,
        )
        if not isinstance(schedule["owner_role"], str) or not schedule["owner_role"]:
            raise ManifestValidationError(
                f"schedule {schedule_id}.owner_role must be nonempty"
            )
        age = schedule["max_evidence_age_days"]
        if not isinstance(age, int) or age <= 0:
            raise ManifestValidationError(
                f"schedule {schedule_id}.max_evidence_age_days is invalid"
            )
    if scheduled_suites != set(suite_rows):
        missing = sorted(set(suite_rows) - scheduled_suites)
        raise ManifestValidationError(f"suites missing schedules: {missing}")


__all__ = [
    "DEFAULT_SCENARIO_ID",
    "MANIFEST_ID",
    "MANIFEST_PATH",
    "MANIFEST_SCHEMA_NAME",
    "MANIFEST_SCHEMA_VERSION",
    "REGISTERED_SCENARIOS",
    "ManifestValidationError",
    "RegistryError",
    "ScenarioDefinition",
    "get_registered_scenario",
    "load_capability_manifest",
    "registered_scenario_ids",
    "run_registered_scenario",
    "validate_capability_manifest",
]
