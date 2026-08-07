"""Typed scenario payloads for composed editor lifecycle reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from tools.virtual_workflows.report import ComposedReportPayload


@dataclass(frozen=True)
class EditorLifecycleReportSpec:
    workload: Mapping[str, Any]
    required_assertion_ids: tuple[str, ...]
    persistence_values: Mapping[str, Any]
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.required_assertion_ids:
            raise ValueError("editor report assertions must be non-empty")


def _decisions(runtime: Any) -> dict[str, str]:
    return {
        str(row.get("assertion_id")): str(row.get("decision"))
        for row in runtime.harness.assertion_results
    }


def _assertion_evidence(runtime: Any) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("assertion_id")): dict(row.get("evidence") or {})
        for row in runtime.harness.assertion_results
    }


def build_editor_lifecycle_payload(
    runtime: Any,
    teardown: Mapping[str, Any],
    spec: EditorLifecycleReportSpec,
) -> ComposedReportPayload:
    decisions = _decisions(runtime)
    passed = all(
        decisions.get(assertion_id) == "pass"
        for assertion_id in spec.required_assertion_ids
    )
    return ComposedReportPayload(
        workload=dict(spec.workload),
        workflow_status="measured" if passed else "partial",
        workflow_values={"cleanup_results": [dict(teardown)]},
        queue={
            "status": "not_applicable",
            "values": {"print_commands_executed": 0},
        },
        persistence={
            "status": "measured" if passed else "partial",
            "values": {
                "assertion_decisions": decisions,
                **dict(spec.persistence_values),
            },
        },
        limitations=spec.limitations,
    )


def create_finalize_report_spec(
    runtime: Any,
    *,
    base_workload: Mapping[str, Any],
    required_assertion_ids: tuple[str, ...],
) -> EditorLifecycleReportSpec:
    fixture = runtime.fixture
    evidence = _assertion_evidence(runtime)
    experiment = fixture["experiment"]
    return EditorLifecycleReportSpec(
        workload={
            **dict(base_workload),
            "experiment_name": experiment["name"],
            "plate_name": experiment["plate_name"],
            "expected_reaction_count": experiment["replicates"],
            "well_ids": list(experiment["expected_well_ids"]),
            "expected_editor_finalization_operations": fixture["workload"][
                "expected_editor_finalization_operations"
            ],
            "speed_multiplier": runtime.harness.config.speed_multiplier,
            "timeout_seconds": runtime.harness.config.timeout_seconds,
        },
        required_assertion_ids=required_assertion_ids,
        persistence_values={
            "prepared_bundle": evidence.get(
                "experiment.prepared_bundle_valid", {}
            ),
            "reload_activation": evidence.get(
                "experiment.prepared_reload_ready", {}
            ),
        },
        limitations=(
            "The scenario validates the editor and authoritative application lifecycle without printing or connecting the simulated machine.",
            "The simulator does not validate firmware, protocol framing, motion, pressure, cameras, balance behavior, or droplet quality.",
            "Generated plan IDs, timestamps, durations, and session paths are not expected to be byte-identical across replay.",
        ),
    )


def prepared_revision_report_spec(
    runtime: Any,
    *,
    base_workload: Mapping[str, Any],
    required_assertion_ids: tuple[str, ...],
) -> EditorLifecycleReportSpec:
    fixture = runtime.fixture
    experiment = fixture["experiment"]
    initial = dict(runtime.observations.get("prepared_revision_initial") or {})
    before = dict(initial.get("before") or {})
    prepared = dict(initial.get("prepared_bundle") or {})
    refinalized = dict(runtime.observations.get("refinalized_bundle") or {})
    after = {
        key: refinalized[key]
        for key in (
            "experiment_dir",
            "renamed_name",
            "plan_id",
            "plan_revision",
            "file_sha256",
            "audit_rows",
        )
        if key in refinalized
    }
    return EditorLifecycleReportSpec(
        workload={
            **dict(base_workload),
            "operation_count": fixture["workload"][
                "expected_editor_finalization_operations"
            ],
            "experiment_name": experiment["initial_name"],
            "renamed_experiment_name": experiment["renamed_name"],
            "expected_rename_operations": fixture["workload"][
                "expected_rename_operations"
            ],
            "plate_name": experiment["plate_name"],
            "expected_reaction_count": experiment["refinalized_replicates"],
            "well_ids": list(experiment["refinalized_expected_well_ids"]),
            "speed_multiplier": runtime.harness.config.speed_multiplier,
            "timeout_seconds": runtime.harness.config.timeout_seconds,
        },
        required_assertion_ids=required_assertion_ids,
        persistence_values={
            "prepared_bundle": prepared,
            "rename_refinalization": {"before": before, "after": after},
            "refinalized_bundle": refinalized,
            "reload_activation": dict(
                runtime.observations.get("reload_activation") or {}
            ),
        },
        limitations=(
            "The scenario validates an untouched prepared editor lifecycle without printing or connecting the simulated machine.",
            "The simulator does not validate firmware, protocol framing, motion, pressure, cameras, balance behavior, or droplet quality.",
            "Generated plan IDs, timestamps, durations, paths, and identity-bearing hashes are not expected to be byte-identical across replay.",
        ),
    )


__all__ = [
    "EditorLifecycleReportSpec",
    "build_editor_lifecycle_payload",
    "create_finalize_report_spec",
    "prepared_revision_report_spec",
]
