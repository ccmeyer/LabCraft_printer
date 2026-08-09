"""Typed, literal contracts for Milestone 12 safeguard qualification.

This module is intentionally independent of the production MVC and machine
communication modules.  Scenario drivers translate boundary evidence into the
types below; the shared oracle then proves an exact outcome and unchanged
authoritative/runtime/dispatch state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping


SAFEGUARD_SCHEMA_VERSION = 1

SAFEGUARD_FAMILIES = frozenset(
    {
        "editor",
        "calibration",
        "identity",
        "lifecycle",
        "persistence",
    }
)
OUTCOME_KINDS = frozenset(
    {"typed_rejection", "persistence_classification", "safe_inactive"}
)
UI_SURFACES = frozenset({"dialog", "banner", "control_state", "load_status"})
FAULT_OPERATIONS = frozenset(
    {
        "replace_json_value",
        "remove_file",
        "truncate_json",
        "replace_file_bytes",
    }
)
FAULT_PHASES = frozenset({"prelaunch", "between_sessions"})
REQUIRED_DISPATCH_KEYS = (
    "machine_intents",
    "commands",
    "completions",
    "drops",
)
FORBIDDEN_POSITIONAL_IDENTITY_KEYS = frozenset(
    {"index", "row", "row_index", "list_index", "position", "ordinal"}
)


class SafeguardContractError(ValueError):
    """Raised when safeguard evidence is ambiguous, unsafe, or non-literal."""


def _require_text(value: Any, label: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise SafeguardContractError(f"{label} must be non-empty")
    return text


def _freeze_json(value: Any, path: str = "value") -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                raise SafeguardContractError(f"{path} keys must be non-empty strings")
            normalized[key] = _freeze_json(child, f"{path}.{key}")
        return MappingProxyType(normalized)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(child, f"{path}[]") for child in value)
    raise SafeguardContractError(
        f"{path} must contain only JSON-compatible literal values"
    )


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(child) for child in value]
    return value


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        _thaw_json(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def canonical_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _validate_identity_tree(value: Any, path: str = "identity_keys") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in FORBIDDEN_POSITIONAL_IDENTITY_KEYS:
                raise SafeguardContractError(
                    f"{path} cannot use positional identity key {key!r}"
                )
            _validate_identity_tree(child, f"{path}.{key}")
    elif isinstance(value, tuple):
        for index, child in enumerate(value):
            _validate_identity_tree(child, f"{path}[{index}]")


@dataclass(frozen=True)
class ExpectedSafeguardOutcome:
    """Literal operator-visible and runtime outcome for one boundary action."""

    outcome_kind: str
    classification: str
    code: str
    message: str
    ui_surface: str
    ui_title: str | None
    selected_control: str | None
    workflow_state: str
    queue_state: str
    runtime_active: bool = False
    activation_count: int = 0

    def __post_init__(self) -> None:
        if self.outcome_kind not in OUTCOME_KINDS:
            raise SafeguardContractError(
                f"unsupported safeguard outcome kind {self.outcome_kind!r}"
            )
        for field_name in (
            "classification",
            "code",
            "message",
            "workflow_state",
            "queue_state",
        ):
            object.__setattr__(
                self, field_name, _require_text(getattr(self, field_name), field_name)
            )
        if self.ui_surface not in UI_SURFACES:
            raise SafeguardContractError(
                f"unsupported operator UI surface {self.ui_surface!r}"
            )
        if self.ui_surface == "dialog" and not self.ui_title:
            raise SafeguardContractError("dialog outcomes require an exact UI title")
        if self.ui_title is not None:
            object.__setattr__(self, "ui_title", _require_text(self.ui_title, "ui_title"))
        if self.selected_control is not None:
            object.__setattr__(
                self,
                "selected_control",
                _require_text(self.selected_control, "selected_control"),
            )
        if self.activation_count != 0:
            raise SafeguardContractError("safeguard outcomes cannot activate execution")

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome_kind": self.outcome_kind,
            "classification": self.classification,
            "code": self.code,
            "message": self.message,
            "ui_surface": self.ui_surface,
            "ui_title": self.ui_title,
            "selected_control": self.selected_control,
            "workflow_state": self.workflow_state,
            "queue_state": self.queue_state,
            "runtime_active": self.runtime_active,
            "activation_count": self.activation_count,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExpectedSafeguardOutcome":
        allowed = {
            "outcome_kind",
            "classification",
            "code",
            "message",
            "ui_surface",
            "ui_title",
            "selected_control",
            "workflow_state",
            "queue_state",
            "runtime_active",
            "activation_count",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise SafeguardContractError(
                f"unexpected safeguard outcome fields: {sorted(unknown)}"
            )
        try:
            return cls(**dict(payload))
        except TypeError as exc:
            raise SafeguardContractError(f"invalid safeguard outcome: {exc}") from exc


@dataclass(frozen=True)
class PersistenceFaultSpec:
    """A predeclared mutation applied only to a case-owned fixture copy."""

    relative_path: str
    operation: str
    phase: str
    original_sha256: str
    faulted_sha256: str
    fixture_root_kind: str = "scenario_case_copy"

    def __post_init__(self) -> None:
        path_text = _require_text(self.relative_path, "fault relative_path")
        if "\\" in path_text or ":" in path_text:
            raise SafeguardContractError("fault path must be portable and relative")
        path = PurePosixPath(path_text)
        if path.is_absolute() or ".." in path.parts or path_text.startswith("/"):
            raise SafeguardContractError("fault path must remain inside its fixture copy")
        object.__setattr__(self, "relative_path", path.as_posix())
        if self.operation not in FAULT_OPERATIONS:
            raise SafeguardContractError(f"unsupported fault operation {self.operation!r}")
        if self.phase not in FAULT_PHASES:
            raise SafeguardContractError(f"unsupported fault phase {self.phase!r}")
        if self.fixture_root_kind != "scenario_case_copy":
            raise SafeguardContractError("faults must target a scenario-owned case copy")
        for field_name in ("original_sha256", "faulted_sha256"):
            digest = _require_text(getattr(self, field_name), field_name).lower()
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise SafeguardContractError(f"{field_name} must be a SHA-256 digest")
            object.__setattr__(self, field_name, digest)
        if self.original_sha256 == self.faulted_sha256:
            raise SafeguardContractError("faulted evidence must differ from its source")

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "operation": self.operation,
            "phase": self.phase,
            "original_sha256": self.original_sha256,
            "faulted_sha256": self.faulted_sha256,
            "fixture_root_kind": self.fixture_root_kind,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PersistenceFaultSpec":
        try:
            return cls(**dict(payload))
        except TypeError as exc:
            raise SafeguardContractError(f"invalid persistence fault spec: {exc}") from exc


@dataclass(frozen=True)
class SafeguardCase:
    """One independently hashable action, invariant, and literal oracle."""

    case_id: str
    family: str
    fixture_id: str
    operator_action_id: str
    operator_action_label: str
    invalid_invariant: str
    expected: ExpectedSafeguardOutcome
    identity_keys: Mapping[str, Any]
    setup: Mapping[str, Any]
    fault: PersistenceFaultSpec | None = None
    direct_required: bool = True
    manifest_required: bool = True
    fresh_process_required: bool = False
    replay_required: bool = False
    visible_required: bool = False
    schema_version: int = SAFEGUARD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SAFEGUARD_SCHEMA_VERSION:
            raise SafeguardContractError(
                f"unsupported safeguard schema version {self.schema_version}"
            )
        for field_name in (
            "case_id",
            "fixture_id",
            "operator_action_id",
            "operator_action_label",
            "invalid_invariant",
        ):
            object.__setattr__(
                self, field_name, _require_text(getattr(self, field_name), field_name)
            )
        if self.family not in SAFEGUARD_FAMILIES:
            raise SafeguardContractError(f"unsupported safeguard family {self.family!r}")
        frozen_identities = _freeze_json(self.identity_keys, "identity_keys")
        if not frozen_identities:
            raise SafeguardContractError("identity_keys must name durable fixture identities")
        _validate_identity_tree(frozen_identities)
        object.__setattr__(self, "identity_keys", frozen_identities)
        frozen_setup = _freeze_json(self.setup, "setup")
        if not frozen_setup:
            raise SafeguardContractError("setup must contain a literal case fixture")
        object.__setattr__(self, "setup", frozen_setup)
        if not self.direct_required or not self.manifest_required:
            raise SafeguardContractError(
                "every Milestone 12 safeguard must run directly and via a manifest"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "family": self.family,
            "fixture_id": self.fixture_id,
            "operator_action_id": self.operator_action_id,
            "operator_action_label": self.operator_action_label,
            "invalid_invariant": self.invalid_invariant,
            "expected": self.expected.to_dict(),
            "identity_keys": _thaw_json(self.identity_keys),
            "setup": _thaw_json(self.setup),
            "fault": self.fault.to_dict() if self.fault is not None else None,
            "direct_required": self.direct_required,
            "manifest_required": self.manifest_required,
            "fresh_process_required": self.fresh_process_required,
            "replay_required": self.replay_required,
            "visible_required": self.visible_required,
        }

    @property
    def contract_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def normalized(self) -> dict[str, Any]:
        """Matrix-contract spelling used by the existing typed runner."""

        return self.to_dict()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SafeguardCase":
        values = dict(payload)
        expected = values.get("expected")
        if not isinstance(expected, Mapping):
            raise SafeguardContractError("safeguard case expected outcome must be an object")
        values["expected"] = ExpectedSafeguardOutcome.from_dict(expected)
        fault = values.get("fault")
        if fault is not None:
            if not isinstance(fault, Mapping):
                raise SafeguardContractError("safeguard fault must be an object or null")
            values["fault"] = PersistenceFaultSpec.from_dict(fault)
        try:
            return cls(**values)
        except TypeError as exc:
            raise SafeguardContractError(f"invalid safeguard case: {exc}") from exc


@dataclass(frozen=True)
class SafeguardCatalog:
    cases: tuple[SafeguardCase, ...]
    schema_version: int = SAFEGUARD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SAFEGUARD_SCHEMA_VERSION:
            raise SafeguardContractError(
                f"unsupported safeguard catalog version {self.schema_version}"
            )
        if not self.cases:
            raise SafeguardContractError("safeguard catalog cannot be empty")
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise SafeguardContractError("safeguard case IDs must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "cases": [case.to_dict() for case in self.cases],
        }

    @property
    def contract_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SafeguardCatalog":
        unknown = set(payload) - {"schema_version", "cases"}
        if unknown:
            raise SafeguardContractError(
                f"unexpected safeguard catalog fields: {sorted(unknown)}"
            )
        cases = payload.get("cases")
        if not isinstance(cases, list):
            raise SafeguardContractError("safeguard catalog cases must be a list")
        parsed: list[SafeguardCase] = []
        for value in cases:
            if not isinstance(value, Mapping):
                raise SafeguardContractError("each safeguard case must be an object")
            parsed.append(SafeguardCase.from_dict(value))
        return cls(
            cases=tuple(parsed),
            schema_version=payload.get("schema_version", SAFEGUARD_SCHEMA_VERSION),
        )


def load_safeguard_catalog(path: Path) -> SafeguardCatalog:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SafeguardContractError(f"cannot load safeguard catalog: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise SafeguardContractError("safeguard catalog root must be an object")
    return SafeguardCatalog.from_dict(payload)


@dataclass(frozen=True)
class SafeguardBoundarySnapshot:
    """Exact state at one rejected-action boundary.

    UI evidence is intentionally carried by ``ExpectedSafeguardOutcome``.  The
    snapshot sections below must remain byte-for-byte equivalent after a
    rejected action.
    """

    persistence: Mapping[str, Any]
    model: Mapping[str, Any]
    lifecycle: Mapping[str, Any]
    queue: Mapping[str, Any]
    dispatch: Mapping[str, Any]

    def __post_init__(self) -> None:
        for field_name in ("persistence", "model", "lifecycle", "queue", "dispatch"):
            value = getattr(self, field_name)
            if not isinstance(value, Mapping):
                raise SafeguardContractError(f"snapshot {field_name} must be an object")
            object.__setattr__(self, field_name, _freeze_json(value, field_name))
        missing = set(REQUIRED_DISPATCH_KEYS) - set(self.dispatch)
        if missing:
            raise SafeguardContractError(
                f"snapshot dispatch is missing counters: {sorted(missing)}"
            )
        for key in REQUIRED_DISPATCH_KEYS:
            value = self.dispatch[key]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise SafeguardContractError(
                    f"snapshot dispatch counter {key!r} must be a non-negative integer"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            name: _thaw_json(getattr(self, name))
            for name in ("persistence", "model", "lifecycle", "queue", "dispatch")
        }

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.to_dict())


def capture_safeguard_boundary(
    *,
    persistence: Mapping[str, Any],
    model: Mapping[str, Any],
    lifecycle: Mapping[str, Any],
    queue: Mapping[str, Any],
    dispatch: Mapping[str, Any],
) -> SafeguardBoundarySnapshot:
    """Normalize explicit, already-observed boundary evidence."""

    return SafeguardBoundarySnapshot(
        persistence=persistence,
        model=model,
        lifecycle=lifecycle,
        queue=queue,
        dispatch=dispatch,
    )


def safeguard_rejection_no_mutation_no_dispatch_assertion(
    *,
    case: SafeguardCase,
    before: SafeguardBoundarySnapshot,
    after: SafeguardBoundarySnapshot,
    observed: ExpectedSafeguardOutcome,
    checkpoint: str,
):
    """Return a report-v1 ``AssertionResult`` for an exact safeguard boundary."""

    # Local import prevents a dependency cycle when existing assertion helpers
    # later reuse this oracle.
    from tools.virtual_workflows.assertions import AssertionResult

    section_checks = {
        f"{name}_unchanged": getattr(before, name) == getattr(after, name)
        for name in ("persistence", "model", "lifecycle", "queue", "dispatch")
    }
    outcome_checks = {
        "outcome_exact": observed.to_dict() == case.expected.to_dict(),
        "typed_classification_exact": (
            observed.outcome_kind == case.expected.outcome_kind
            and observed.classification == case.expected.classification
            and observed.code == case.expected.code
        ),
        "operator_ui_exact": (
            observed.message == case.expected.message
            and observed.ui_surface == case.expected.ui_surface
            and observed.ui_title == case.expected.ui_title
            and observed.selected_control == case.expected.selected_control
        ),
        "safe_workflow_exact": (
            observed.workflow_state == case.expected.workflow_state
            and observed.queue_state == case.expected.queue_state
        ),
        "runtime_state_exact": (
            observed.runtime_active is case.expected.runtime_active
        ),
        "no_activation": observed.activation_count == 0,
    }
    checks = {**section_checks, **outcome_checks}
    failed = sorted(name for name, passed in checks.items() if not passed)
    evidence = {
        "schema_version": SAFEGUARD_SCHEMA_VERSION,
        "case_id": case.case_id,
        "case_contract_sha256": case.contract_sha256,
        "before_sha256": before.sha256,
        "after_sha256": after.sha256,
        "checks": checks,
        "failed_checks": failed,
        "expected": case.expected.to_dict(),
        "observed": observed.to_dict(),
        "before": before.to_dict(),
        "after": after.to_dict(),
    }
    return AssertionResult(
        assertion_id="safeguard_rejection_no_mutation_no_dispatch",
        checkpoint=_require_text(checkpoint, "checkpoint"),
        decision="pass" if not failed else "fail",
        observable_sources=(
            "operator_action",
            "ui_evidence",
            "authoritative_persistence",
            "model_state",
            "workflow_lifecycle",
            "queue_state",
            "execution_observer",
        ),
        evidence=evidence,
        message=None if not failed else f"safeguard boundary failed: {', '.join(failed)}",
    )
