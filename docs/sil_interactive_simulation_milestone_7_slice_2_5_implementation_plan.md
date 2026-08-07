# Milestone 7 Slice 2.5 — Composed-Journey Consolidation

Status: `implemented — approved and completed on 2026-08-06`  
Planning baseline: `04594f37966bc3e41b025004733f17a70094672b`, plus the
intentionally uncommitted and validated Milestone 7 Slice 2 worktree.

## Objective

Refactor the three active composed journeys into a small typed composition
layer before migrating another workflow. Preserve their behavior and evidence
contracts while making future named journeys concise and making ordinary data
or order variations representable as typed inputs rather than new monolithic
runner functions.

This is a behavior-preserving consolidation slice. It does not migrate
`experiment_editor_prestart_rename_refinalize_v1` or any other scenario. It
does not add an active parameter matrix, seeded sequence generator, fault
injection, performance work, Pi operation, firmware/protocol work, or hardware
operation.

No file under `FreeRTOS-interface/` or `firmware/` is in scope.

## Audit Findings And Motivation

The reusable foundation is present:

- `AutomationHarness` owns a bounded `SimulationSession`, evidence, failure
  capture, and teardown;
- page drivers own bounded QTest interactions with application surfaces;
- `ExecutionObserver` observes progress and persistence without advancing
  application state;
- `ComposedReportAdapter` supplies common report-v1 sections;
- actions and assertions have stable IDs and interaction-surface contracts.

The remaining scenario layer is not yet concise:

| Current section | Approximate lines |
|---|---:|
| smoke journey | 207 |
| smoke report builder | 197 |
| editor journey | 124 |
| editor report builder | 185 |
| multi-stock journey | 458 |
| multi-stock report builder | 171 |

Slice 2 also added about 292 lines of multi-stock-specific assertions. Much of
the multi-stock journey repeats machine startup, action wrapping, editor
preparation, head configuration, calibration, array start, exception capture,
observer restoration, teardown, incomplete-assertion marking, artifact checks,
report writing, and replay-summary construction.

Continuing this pattern would make every substantial named workflow another
large runner. That conflicts with the roadmap requirements that journeys be
short typed compositions, stock/head loops not be expanded copies, and normal
data variations use parameters or builders.

## Current And Target Call Paths

Current composed dispatch:

```text
tools/run_virtual_workflow.py
  -> registry.run_registered_scenario()
  -> runner_family == "composed_journey"
  -> scenario-ID if/elif dispatch
  -> one run_*_journey() function
  -> repeated harness/page-driver/action/report lifecycle wiring
  -> Qt UI -> Controller -> Model -> SimulatedMachine
```

Target dispatch:

```text
tools/run_virtual_workflow.py
  -> registry.run_registered_scenario()
  -> run_composed_journey(config, registered definition)
  -> JourneyDefinition + typed phase inputs
  -> JourneyExecutor
       -> AutomationHarness / SimulationSession
       -> reusable phase builders
       -> SemanticStep -> harness.run_action()
       -> page driver -> bounded QTest interaction
       -> reusable assertion families
       -> common report/failure/teardown finalization
  -> Qt UI -> Controller -> Model -> SimulatedMachine
```

There is no firmware handler in either path. `SimulatedMachine` remains the
end of the application-facing communications path.

## Frozen Design Decisions

1. **No behavior or coverage change.** Preserve all three active composed
   workload IDs, scenario names/versions, fixture bytes and hashes, action IDs
   and order, interaction surfaces, assertion IDs and decisions, screenshot
   requirements, report-v1 fields, replay semantics, failure classification,
   retention policy, and teardown behavior.
2. **Typed Python composition, not a configuration DSL.** Add small validated
   dataclasses and Python phase builders. Do not introduce YAML, an expression
   language, reflection-based action lookup, or arbitrary fixture-driven code
   execution.
3. **One generic composed dispatch.** The registry selects one generic
   composed runner. Scenario selection is data-driven by a validated journey
   definition; adding a future composed journey must not add another dispatch
   `if` branch.
4. **Semantic steps remain truthful.** Every executable step has one stable
   action ID, declared `InteractionSurface`, bounded operation, optional
   precondition/dialog policy, and bounded evidence. UI claims may call only
   the existing page drivers/QTest path. Read-only waits, assertions, report
   work, and observation remain `harness`; deterministic head identity binding
   remains `model`.
5. **Reusable phases are lifecycle-sized.** Extract machine startup, editor
   preparation, stock/head pass execution, checkpoint capture, assertion
   evaluation, and finalization once. A phase may expand to semantic steps but
   may not hide an unrecorded operator action or collapse multiple action IDs
   into one ledger entry.
6. **Definitions are matrix-ready, not a matrix implementation.** A
   `JourneyDefinition` describes identity/contracts and a `StockPassSpec`
   describes per-pass values, dialogs, boundary expectations, and milestones.
   Unit tests must prove that different validated values and stock orders can
   produce normalized step plans without changing orchestration code. No new
   registered case or suite is added in Slice 2.5.
7. **One report finalizer.** Replace the three scenario-specific envelope
   builders with one generic finalizer plus bounded scenario metric payloads.
   Report-v1 remains unchanged; report-v2 and baseline schema changes are out
   of scope.
8. **Targeted validation only.** Capture pre-refactor reference reports, run
   directly affected tests, then compare post-refactor stable fields. Defer the
   complete pytest suite to the final Milestone 7 gate.

## Proposed Composition Contracts

`tools/virtual_workflows/composition.py` will own the generic contracts:

```python
@dataclass(frozen=True)
class SemanticStep:
    action_id: str
    surface: InteractionSurface
    operation: Callable[[JourneyRuntime], Mapping[str, Any] | None]
    precondition: ... = None
    allowed_dialogs: tuple[...] = ()

@dataclass(frozen=True)
class JourneyDefinition:
    registry_id: str
    scenario_name: str
    scenario_version: str
    workload_id: str
    required_action_ids: frozenset[str]
    required_assertion_ids: tuple[str, ...]
    required_screenshots: Mapping[str, str]
    compose: Callable[[JourneyRuntime], Sequence[SemanticStep]]

@dataclass
class JourneyRuntime:
    harness: AutomationHarness
    fixture: Mapping[str, Any]
    fixture_path: Path
    observations: MutableMapping[str, Any]
    restorables: list[...]

class JourneyExecutor:
    def run(self, definition: JourneyDefinition, config: JourneyRunConfig) -> dict: ...
```

`JourneyExecutor` owns the common start/execute/capture-failure/restore/close,
incomplete-assertion, artifact, report, ledger, manifest, summary, and return
sequence. Restorables such as `ExecutionObserver` are restored in reverse order
on both success and failure. It must never repair business state.

`tools/virtual_workflows/journey_phases.py` will own validated reusable phase
inputs and builders, including:

- `MachineStartupSpec` and `machine_startup_steps()`;
- `EditorPreparationSpec` and `editor_preparation_steps()`;
- `StockPassSpec` and `stock_pass_steps()`;
- checkpoint and assertion-step builders;
- the stock/head loop that expands ordered pass specifications.

Phase builders return explicit `SemanticStep` objects; they do not execute at
definition time. The normalized plan is therefore inspectable in unit tests
and is a future input boundary for parameter matrices and seeded exploration.

The three named journey definitions remain in `journeys.py`. They load their
existing fixtures, derive typed inputs, select reusable phases and assertions,
and supply scenario-specific metric values. They do not own generic exception,
teardown, artifact, report-envelope, or output-writing logic.

## Measurable Concision And Compatibility Gates

Slice 2.5 is not complete merely because code moved to new files. It must meet
all of these gates:

- each public `run_*_journey()` compatibility entry point is at most 80
  nonblank, non-comment lines and delegates to the generic executor;
- each named journey composition/definition is at most 120 nonblank,
  non-comment lines, excluding fixture validation and reusable phase code;
- `_report()`, `_editor_report()`, and `_multi_stock_report()` are removed;
- machine startup, common finalization, and repeated stock-pass orchestration
  each have one implementation and at least two active journey consumers where
  applicable;
- the normalized two-stock plan contains the same repeated action groups and
  surfaces as Slice 2, with exactly two settings/volume/stage/calibration/start/
  return groups;
- a pure unit test changes stock values and order through `StockPassSpec`
  instances and obtains the expected normalized plan without adding a runner;
- registry dispatch contains no scenario-ID conditional for composed journeys;
- pre/post stable report comparisons pass for smoke, editor, and multi-stock;
- source/import guards continue to prove that composed code cannot construct a
  production machine or physical port.

Line limits are review gates against another monolithic journey, not a reason
to compress readable code or hide behavior in anonymous helpers. Review must
also confirm that total duplication was removed rather than relocated.

## Implementation Steps

1. Capture reference reports and normalized action/assertion/screenshot/
   teardown contracts for the current smoke, editor, and multi-stock composed
   journeys. Add a stable-field comparison helper that excludes only documented
   timestamps, durations, paths, UUIDs, and identity-bearing hashes.
2. Add validated `SemanticStep`, `JourneyDefinition`, `JourneyRuntime`, and
   `JourneyExecutor` contracts with unit tests for invalid IDs, duplicate steps,
   unknown surfaces, deadline/failure propagation, reverse restoration,
   incomplete assertions, artifact finalization, and idempotent teardown.
3. Add reusable typed phase specifications/builders for machine startup,
   editor preparation, ordered stock/head passes, checkpoints, and assertion
   evaluation. Freeze their normalized action order, surfaces, preconditions,
   dialog policies, and parameter/order variation behavior in unit tests.
4. Generalize current execution assertions around typed prepared/pass/terminal
   expectations and replace the three scenario report builders with one
   report-v1 finalizer. Keep compatibility wrappers only where an existing test
   or external import contract requires them.
5. Rewrite the smoke, editor, and multi-stock journey definitions as concise
   compositions over the new executor and phases. Preserve their public runner
   entry points temporarily as thin compatibility wrappers and meet the
   measurable concision gates above.
6. Replace composed scenario-ID branching in `registry.py` with validated
   generic dispatch. Keep all non-composed runner families and every registry,
   fixture, manifest, Pi, and report-set capability unchanged.
7. Run targeted unit/system, controlled-failure, source/import-safety, and
   pre/post stable-report parity gates. Run all three CLI journeys, then one
   visible multi-stock run and its exact emitted replay; inspect retained
   evidence and session locks.
8. Update README/roadmap, record measured before/after code shape and validation
   in a Slice 2.5 completion record, and stop for approval before planning or
   implementing the prepared edit/refinalize migration.

## Exact Implementation File Set

New files:

- `tools/virtual_workflows/composition.py`
- `tools/virtual_workflows/journey_phases.py`
- `tests/test_virtual_workflow_composition.py`
- `tests/test_virtual_workflow_journey_phases.py`
- `docs/sil_interactive_simulation_milestone_7_slice_2_5_completion_record.md`

Modified files:

- `tools/virtual_workflows/harness.py`
- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/registry.py`
- `tools/virtual_workflows/report.py`
- `tests/test_virtual_workflow_harness.py`
- `tests/test_virtual_workflow_assertions.py`
- `tests/test_virtual_workflow_report.py`
- `tests/test_virtual_workflow_manifest.py`
- `tests/test_virtual_workflow_contract_freeze.py`
- `tests/system/test_virtual_workflow_smoke.py`
- `tests/system/test_virtual_workflow_editor_composed.py`
- `tests/system/test_virtual_workflow_multi_stock_composed.py`
- `README.md`
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- this plan

No fixture, capability-manifest JSON, page-driver, production MVC, simulator
response model, legacy runner, Pi tool, firmware, protocol, or hardware file is
intended to change. If implementation requires such a change, stop and amend
the plan before editing it.

## Targeted Automated Gates

Before refactoring, run the three current composed system tests and retain one
successful report for each as the parity reference. After each extraction,
run the directly affected unit group:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_simulation_session.py `
  tests\test_virtual_workflow_harness.py `
  tests\test_virtual_workflow_composition.py `
  tests\test_virtual_workflow_journey_phases.py `
  tests\test_virtual_workflow_page_drivers.py `
  tests\test_virtual_workflow_actions.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_execution_observer.py `
  tests\test_virtual_workflow_report.py `
  tests\test_virtual_workflow_manifest.py `
  tests\test_virtual_workflow_contract_freeze.py
```

Run the composed success and controlled-failure paths:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_smoke.py `
  tests\system\test_virtual_workflow_editor_composed.py `
  tests\system\test_virtual_workflow_multi_stock_composed.py
```

Run the existing calibration/execution/persistence adjacency contracts because
stock-pass phases observe those boundaries:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_sil_calibration_application.py `
  tests\test_sil_normal_ui_convergence.py `
  tests\test_initial_execution_plan_integration.py `
  tests\test_execution_progress_store.py `
  tests\test_execution_resume_store.py
```

Run source/import isolation checks selected by the contract-freeze test and:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py --help
.\env\Scripts\python.exe -m py_compile `
  tools\virtual_workflows\composition.py `
  tools\virtual_workflows\journey_phases.py `
  tools\virtual_workflows\harness.py `
  tools\virtual_workflows\assertions.py `
  tools\virtual_workflows\journeys.py `
  tools\virtual_workflows\registry.py `
  tools\virtual_workflows\report.py
git diff --check
git status --short
```

Do not run the unscoped full pytest command in Slice 2.5. Record it as deferred
to the final Milestone 7 validation.

## Direct, Visible, And Replay Gates

Run each refactored composition directly with a fixed seed:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario virtual_print_array_24_v1 `
  --output-root verification_reports\milestone7-slice2-5 `
  --seed 1 --timeout-seconds 180

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario experiment_editor_create_finalize_v1 `
  --output-root verification_reports\milestone7-slice2-5 `
  --seed 1 --timeout-seconds 180

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario print_array_multi_stock_24x2_v1 `
  --output-root verification_reports\milestone7-slice2-5 `
  --visible --seed 1 --speed-multiplier 2 --timeout-seconds 300
```

Run the exact replay command emitted by the visible multi-stock report. Compare
each post-refactor report with its pre-refactor reference on:

- scenario/workload/version and fixture SHA-256;
- ordered action IDs, surfaces, statuses, and stable bounded evidence;
- assertion IDs and decisions;
- milestone and screenshot keys;
- workload metrics, completion counts, pass boundaries, calibration/settings,
  persistence, and terminal state;
- classification and limitations;
- recorder health, teardown result, retained-root presence, and absence of the
  session lock.

Expected differences are limited to timestamps, durations, generated paths,
run/session/application UUIDs, and hashes containing those identities. Any
other difference is a failed parity gate unless explicitly reviewed and added
to an amended plan.

## Risks And Mitigations

- **Abstraction hides a bypass:** normalized step-plan tests freeze every action
  ID and surface, while system tests continue to observe real Qt controls and
  fail on unexpected dialogs.
- **Code is moved rather than deduplicated:** enforce the one-implementation and
  concision gates, inspect duplicate phase bodies, and record before/after
  scenario-specific line counts.
- **Over-generalized mini-framework:** limit contracts to behavior exercised by
  the three current journeys and the pure variation test. No plugin system,
  configuration DSL, or seeded generator is introduced.
- **Report drift:** capture reports before editing and compare documented stable
  fields for all three journeys. Keep report-v1 and manifests unchanged.
- **Cleanup/observer regression:** executor tests cover failures at startup,
  mid-phase, assertion, reporting, and teardown, including reverse restoration,
  recorder closure, retained failure evidence, and lock removal.
- **Mutable state leaks between cases:** create a fresh executor, harness,
  runtime, session root, observation store, and step plan per run; frozen
  definitions/specifications contain no runtime application objects.
- **Premature matrix or sequence design:** prove only typed parameter/order
  variation. Defer active matrices and seeded legal/illegal action generation
  to separately planned later slices/Milestone 8.
- **Prior uncommitted milestones:** apply changes narrowly and never use reset
  or checkout rollback commands that could discard Milestones 5–7 work.

## Rollback

Keep the existing three public runner entry points until all parity gates pass.
If consolidation fails, restore only the pre-Slice-2.5 versions of `harness.py`,
`assertions.py`, `journeys.py`, `registry.py`, and `report.py`; remove the new
composition/phase modules and their tests; and restore the roadmap/README
wording. The three existing composed scenarios then continue through their
current independently implemented functions.

Do not revert fixtures, Slice 2 page drivers/actions/observer, capability
claims, production state, or retained evidence. No firmware/protocol, Pi, or
hardware rollback is required.

## Approval Gate

This plan was approved and implemented. Its approval covered only the exact
file set, eight steps, behavior-preserving refactor, targeted-test policy, and
direct/visible/replay gates above. Slice 3 remains unplanned and unimplemented.
