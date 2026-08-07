"""Typed composition and lifecycle ownership for composed SIL journeys."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Sequence

from tools.virtual_workflows.actions import ACTION_IDS, InteractionSurface
from tools.virtual_workflows.harness import AutomationHarness, AutomationHarnessConfig
from tools.virtual_workflows.report import ComposedReportAdapter, ComposedReportPayload


REPO_ROOT = Path(__file__).resolve().parents[2]

StepOperation = Callable[["JourneyRuntime"], Mapping[str, Any] | None]
StepPrecondition = Callable[[], tuple[bool, str, Mapping[str, Any] | None]]


@dataclass(frozen=True)
class SemanticStep:
    """One bounded, ledger-visible semantic action."""

    action_id: str
    surface: InteractionSurface
    operation: StepOperation = field(repr=False, compare=False)
    precondition: StepPrecondition | None = field(
        default=None, repr=False, compare=False
    )
    allowed_dialogs: tuple[Any, ...] = field(
        default=(), repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.action_id not in ACTION_IDS:
            raise ValueError(f"unknown semantic action ID: {self.action_id!r}")
        if not isinstance(self.surface, InteractionSurface):
            raise ValueError("semantic step surface must be an InteractionSurface")
        if not callable(self.operation):
            raise ValueError("semantic step operation must be callable")

    def normalized(self) -> dict[str, str]:
        return {
            "action_id": self.action_id,
            "interaction_surface": self.surface.value,
        }


FixtureLoader = Callable[[], tuple[dict[str, Any], Path]]
JourneyBody = Callable[["JourneyRuntime"], None]
ArtifactAssertion = Callable[["JourneyRuntime", Mapping[str, Any]], Any]
PayloadBuilder = Callable[
    ["JourneyRuntime", Mapping[str, Any]], ComposedReportPayload
]
SummaryBuilder = Callable[[Mapping[str, Any], "JourneyRuntime"], str]


@dataclass(frozen=True)
class JourneyDefinition:
    """Validated identity, lifecycle, evidence, and composition contract."""

    registry_id: str
    scenario_name: str
    scenario_version: str
    workload_id: str
    required_action_ids: frozenset[str]
    required_ui_action_ids: frozenset[str]
    required_assertion_ids: tuple[str, ...]
    required_screenshots: frozenset[str]
    fixture_loader: FixtureLoader = field(repr=False, compare=False)
    body: JourneyBody = field(repr=False, compare=False)
    artifact_assertion: ArtifactAssertion = field(repr=False, compare=False)
    payload_builder: PayloadBuilder = field(repr=False, compare=False)
    summary_builder: SummaryBuilder = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        identities = (
            self.registry_id,
            self.scenario_name,
            self.scenario_version,
            self.workload_id,
        )
        if any(not str(value).strip() for value in identities):
            raise ValueError("journey identities must be non-empty")
        unknown = sorted(self.required_action_ids - ACTION_IDS)
        if unknown:
            raise ValueError(f"journey has unknown action IDs: {unknown}")
        if not self.required_ui_action_ids <= self.required_action_ids:
            raise ValueError("required UI actions must be required journey actions")
        if len(set(self.required_assertion_ids)) != len(
            self.required_assertion_ids
        ):
            raise ValueError("required assertion IDs must be unique")
        if not self.required_assertion_ids:
            raise ValueError("journey requires at least one assertion")
        for callback in (
            self.fixture_loader,
            self.body,
            self.artifact_assertion,
            self.payload_builder,
            self.summary_builder,
        ):
            if not callable(callback):
                raise ValueError("journey callbacks must be callable")


@dataclass
class JourneyRuntime:
    """Fresh mutable state for one execution of a frozen definition."""

    definition: JourneyDefinition
    harness: AutomationHarness
    fixture: Mapping[str, Any]
    fixture_path: Path
    observations: MutableMapping[str, Any] = field(default_factory=dict)
    _restorables: list[tuple[str, Any]] = field(default_factory=list, repr=False)
    _restored_names: set[str] = field(default_factory=set, repr=False)

    @property
    def context(self) -> Any:
        return self.harness.context

    def run_steps(self, steps: Sequence[SemanticStep]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for step in steps:
            results.append(
                self.harness.run_action(
                    step.action_id,
                    lambda step=step: step.operation(self),
                    surface=step.surface,
                    precondition=step.precondition,
                    allowed_dialogs=step.allowed_dialogs,
                )
            )
        return results

    def add_assertion(self, result: Any, *, required: bool = True) -> None:
        row = result.to_dict() if hasattr(result, "to_dict") else dict(result)
        self.harness.add_assertion_result(row)
        if required and row.get("decision") != "pass":
            raise RuntimeError(
                f"required assertion {row.get('assertion_id')} was "
                f"{row.get('decision')}: "
                f"{row.get('message') or row.get('evidence')}"
            )

    def register_restorable(self, name: str, restorable: Any) -> None:
        key = str(name).strip()
        if not key or any(existing == key for existing, _ in self._restorables):
            raise ValueError(f"restorable name is empty or duplicated: {name!r}")
        if not callable(getattr(restorable, "restore", None)):
            raise ValueError("restorable must provide restore()")
        self._restorables.append((key, restorable))

    def restore_all(self) -> None:
        errors: list[BaseException] = []
        for name, restorable in reversed(self._restorables):
            if name in self._restored_names:
                continue
            try:
                restorable.restore()
                snapshot = getattr(restorable, "snapshot", None)
                if callable(snapshot):
                    self.observations[f"{name}_snapshot"] = snapshot()
            except BaseException as exc:
                errors.append(exc)
            finally:
                self._restored_names.add(name)
        if errors:
            raise RuntimeError(
                "journey restoration failed: "
                + "; ".join(str(error) for error in errors)
            )


def replay_command(harness: AutomationHarness, workload_id: str) -> list[str]:
    command = [
        r".\env\Scripts\python.exe",
        r"tools\run_virtual_workflow.py",
        "--scenario",
        str(workload_id),
        "--output-root",
        str(harness.config.output_root),
        "--seed",
        str(harness.config.seed),
        "--speed-multiplier",
        str(harness.config.speed_multiplier),
        "--timeout-seconds",
        str(harness.config.timeout_seconds),
    ]
    if harness.config.visible:
        command.append("--visible")
    return command


class JourneyExecutor:
    """Own the common success, failure, evidence, report, and teardown path."""

    def run(self, definition: JourneyDefinition, config: Any) -> dict[str, Any]:
        if str(config.scenario_id) != definition.registry_id:
            raise ValueError(
                f"journey {definition.registry_id!r} cannot run "
                f"scenario {config.scenario_id!r}"
            )
        fixture, fixture_path = definition.fixture_loader()
        harness = AutomationHarness(
            AutomationHarnessConfig(
                scenario_id=definition.scenario_name,
                workload_id=definition.workload_id,
                output_root=config.output_root,
                visible=config.visible,
                seed=config.seed,
                speed_multiplier=config.speed_multiplier,
                timeout_seconds=config.timeout_seconds,
                run_id=config.run_id,
            )
        )
        runtime = JourneyRuntime(
            definition=definition,
            harness=harness,
            fixture=fixture,
            fixture_path=Path(fixture_path).resolve(),
        )
        teardown: Mapping[str, Any] = {}
        try:
            harness.start()
            definition.body(runtime)
            self._validate_success_contract(runtime)
        except BaseException as exc:
            harness.capture_failure(exc)
        finally:
            try:
                runtime.restore_all()
            except BaseException as exc:
                if harness.failure is None:
                    harness.capture_failure(exc)
            try:
                teardown = harness.close()
            except BaseException as exc:
                if harness.failure is None:
                    harness.capture_failure(exc)
                teardown = {
                    "action_id": "scenario.teardown",
                    "status": "fail",
                    "evidence": {"close_succeeded": False},
                }

        artifact_result = definition.artifact_assertion(runtime, teardown)
        runtime.add_assertion(artifact_result, required=False)
        artifact_row = (
            artifact_result.to_dict()
            if hasattr(artifact_result, "to_dict")
            else dict(artifact_result)
        )
        if artifact_row.get("decision") != "pass" and harness.failure is None:
            harness.failure = RuntimeError("required artifacts/cleanup failed")

        self._mark_incomplete(runtime)
        payload = definition.payload_builder(runtime, teardown)
        command = replay_command(harness, definition.workload_id)
        report = ComposedReportAdapter(harness, repo_root=REPO_ROOT).build(
            workload_id=definition.workload_id,
            scenario_name=definition.scenario_name,
            scenario_version=definition.scenario_version,
            replay_command=command,
            required_assertion_ids=definition.required_assertion_ids,
            required_ui_action_ids=definition.required_ui_action_ids,
            payload=payload,
        )
        self._write_outputs(
            harness,
            report,
            definition.summary_builder(report, runtime),
        )
        return report

    @staticmethod
    def _validate_success_contract(runtime: JourneyRuntime) -> None:
        observed = {
            str(row.get("action_id"))
            for row in runtime.harness.context.action_results
        }
        expected = runtime.definition.required_action_ids - {"scenario.teardown"}
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        missing_screenshots = sorted(
            runtime.definition.required_screenshots
            - set(runtime.harness.context.screenshots)
        )
        if missing or extra or missing_screenshots:
            raise RuntimeError(
                "composed journey contract mismatch: "
                f"missing_actions={missing}, extra_actions={extra}, "
                f"missing_screenshots={missing_screenshots}"
            )

    @staticmethod
    def _mark_incomplete(runtime: JourneyRuntime) -> None:
        present = {
            str(item.get("assertion_id"))
            for item in runtime.harness.assertion_results
        }
        for assertion_id in runtime.definition.required_assertion_ids:
            if assertion_id in present:
                continue
            runtime.harness.add_assertion_result(
                {
                    "assertion_id": assertion_id,
                    "checkpoint": "not_reached",
                    "decision": "incomplete",
                    "observable_sources": [],
                    "evidence": {},
                    "message": "journey failed before this required checkpoint",
                }
            )

    @staticmethod
    def _write_outputs(
        harness: AutomationHarness,
        report: Mapping[str, Any],
        summary: str,
    ) -> None:
        from tools.virtual_workflows.report import write_report_atomic

        harness.write_ledgers()
        write_report_atomic(harness.report_dir / "report.json", report)
        (harness.report_dir / "summary.txt").write_text(summary, encoding="utf-8")
        harness.write_evidence_manifest()


def normalized_steps(steps: Sequence[SemanticStep]) -> list[dict[str, str]]:
    return [step.normalized() for step in steps]


__all__ = [
    "JourneyDefinition",
    "JourneyExecutor",
    "JourneyRuntime",
    "SemanticStep",
    "normalized_steps",
    "replay_command",
]
