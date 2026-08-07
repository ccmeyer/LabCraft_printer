# Milestone 7 Slice 7 - Composed 96-Well Regression

Status: `implemented - targeted validation passed with documented variances`

Planning baseline: `af4ae5a7f5e5df7d7932b3f9936e164007b84715` with
Milestone 7 Slice 6 committed and a clean worktree.

## Objective

Migrate only `virtual_print_array_96_v1` from the branch-heavy legacy
print-array runner to generic `composed_journey` dispatch. The normal path
will use the same typed one-stock journey, page drivers, semantic actions,
assertions, report lifecycle, and teardown as the composed 24-well smoke.
The scenario-specific definition must supply only its frozen identity,
fixture, 48-completion midpoint, regression evidence profile, and contract.

The existing 96-well regression is also the repository's Windows/Pi
responsiveness and comparison anchor. Slice 7 therefore extracts, rather
than duplicates, its existing optional instrumentation into one reusable
regression evidence profile. The profile must preserve injected-stall,
report-set, baseline-comparison, and local Pi-evidence compatibility without
making those concerns part of the one-stock journey body. The retained
legacy runner remains directly callable as a parity oracle until all focused
gates pass.

This slice does not migrate `virtual_print_array_384x10_v1` or the disconnect
scenario. It does not change or accept a performance baseline, remediate
performance, add a scenario matrix or seeded sequence generator, add new
product/simulator fault injection, run a remote Pi operation, or change
production MVC, simulator responses, firmware, protocol, timing-sensitive
hardware behavior, or physical hardware.

## Audit Baseline

- HEAD is `af4ae5a7f5e5df7d7932b3f9936e164007b84715`; `git status`, the complete
  diff, and `git diff --check` were clean before this planning-only change.
- Slice 6 is present, documented, and committed. Seven registry scenarios
  already use generic `composed_journey`; the 96-well regression and 384x10
  stress remain on `virtual_print_array`.
- `virtual_print_array_96_v1` remains the CLI default, belongs to the host
  regression and Pi-primary suites, supports injected-stall controls,
  repeated report sets, accepted-baseline comparison, and paired Pi safety
  evidence.
- Its schema-v1 fixture remains byte-identical with SHA-256
  `25BEC67BE06A73D4C43766C328CE218731E577C75F8AEAE08021B81CD9FE8FF1`.
  It expands rows A-D in serpentine order to 96 unique wells, uses one
  droplet stock prepared at 5 nL and calibrated to 10 nL, and expects one
  completion per well.
- The existing 24-well composed journey already owns every normal UI action
  needed by the 96-well path. Its fixture adapter currently assumes schema
  v2 (`stocks`, `target_concentration`, and `staging_slot`), while the 96-well
  compatibility fixture uses schema v1 (`stock`, separate `printer_head`, and
  no staging-slot field).
- The bounded planning baseline completed in 12.18 seconds with 9 passes and
  one injected-stall failure. The exact injected-stall node passed on its
  immediate isolated retry in 6.65 seconds. This is treated as the existing
  timing-sensitive retry case, not authorization for performance remediation.
- The full Python suite was not run and remains deferred to the final
  Milestone 7 validation, as requested.

## Current Call Paths And Duplication

### Legacy registry path

```text
tools/run_virtual_workflow.py
  -> registry.run_registered_scenario()
  -> runner_family == "virtual_print_array"
  -> scenarios.run_virtual_print_array_scenario()
       -> create authoritative fixture files directly
       -> construct the application with simulation dependencies
       -> connect/configure/stage through mixed simulator/Model actions
       -> start the array through the normal UI
       -> embedded responsiveness, resource, phase, persistence-I/O,
          progress, queue, midpoint, stall, Pi, report, and teardown logic
```

The legacy setup bypasses Experiment Editor by writing and loading a prepared
bundle directly. Machine readiness and head staging also use mixed lower
surfaces, so the current regression does not provide the same end-to-end UI
coverage as the composed smoke. `run_virtual_print_array_scenario()` owns
both workflow behavior and roughly all diagnostic/report policy; the same
instrumentation is needed by the later 384x10 migration.

### Existing reusable normal-UI path

```text
registry -> JourneyExecutor -> AutomationHarness
  -> machine_startup_steps()
       QTest -> Machine/Settings controls -> Controller -> Model
       -> SimulatedMachine (literal SIMULATED port)
  -> run_editor_preparation(EditorPreparationSpec)
       QTest -> Experiment Editor -> ExperimentModel persistence
  -> run_stock_passes(StockPassSpec)
       QTest -> rack controls -> calibration dialog -> array controls
       -> Controller -> Model -> SimulatedMachine
  -> typed assertions -> composed report/evidence -> generic teardown
```

The application call path ends at `SimulatedMachine`; no comms framing,
firmware handler, physical motion, pressure hardware, camera, balance, GPIO,
or updater is exercised or changed.

### Target Slice 7 path

```text
generic registry dispatch -> 96-well JourneyDefinition
  -> shared schema-v1/v2 one-stock fixture projection
  -> existing one-stock normal-UI body
  -> optional reusable RegressionEvidenceProfile
       phase/persistence/progress/queue/responsiveness/resource observers
       existing injected-stall observation and paired Pi identity validation
  -> shared regression assertions/report sections
  -> generic evidence manifest and teardown
```

The 96-well definition must not contain QTest calls, construct application
objects, parse authoritative files, assemble a report envelope, or implement
observer restoration or teardown.

## Frozen Slice Decisions

1. **One migration only.** Preserve the registry/workload/scenario identity,
   schema-v1 fixture bytes/hash, default CLI identity, 96 serpentine wells,
   one stock/pass, 48-completion midpoint, expected dialogs, suite/platform
   membership, and expected pass outcome.
2. **One one-stock composition.** Generalize the existing 24-well helpers to
   read schema-v1 and schema-v2 stock shapes without modifying either fixture.
   Both 24- and 96-well definitions call the same body, pass builder, payload
   builder, and page drivers; Slice 7 adds no second print-array body.
3. **Truthful UI coverage.** Experiment creation, machine setup, head setup,
   calibration, and array start use the existing QTest page drivers and report
   `ui`. Observer installation, waits, midpoint capture, Pi validation,
   reporting, and teardown report `harness`. Direct fixture writes and mixed
   readiness/staging actions remain only in the labeled legacy oracle.
4. **Optional evidence profile.** Move the existing diagnostic ownership into
   one bounded profile used by the composed 96-well journey and retained
   legacy oracle. The profile owns install/snapshot/restore and cannot select
   wells, start printing, mutate plans, or decide workflow order.
5. **Compatibility, not remediation.** Preserve the exact report-v1 metric
   paths consumed by `compare.py`, the stall-stack artifact, injected-stall
   controls, report sets, and Windows/Pi compatibility fields. Do not change
   thresholds, tune product performance, or rewrite either accepted baseline.
6. **Pi remains local-contract only.** Support paired preflight/proof data in
   the composed config/report path and run local validation tests. Do not
   launch SSH, SCP, the Pi wrapper, or any remote Pi operation in Slice 7.
7. **Direct oracle remains callable.** Stable parity compares workload,
   completion, persistence, queue, responsiveness, stall, Pi, classification,
   and cleanup projections. The reviewed difference is the composed path's
   broader UI actions and added editor screenshots/ledgers.
8. **Targeted validation only.** Run the focused gates below. The complete
   Python suite is reserved for final Milestone 7 validation.

## Frozen Composed Contract

Required assertions are exactly:

```text
sil.host_hardware_disabled
sil.pi_evidence_valid
ui.real_app_constructed
execution.expected_completions
execution.no_queue_starvation
execution.intent_durability_exact
execution.terminal_bundle_valid
artifacts.required_present
ui.injected_stall_detected
ui.responsiveness_metrics_present
```

`sil.pi_evidence_valid` is `pass` with validated paired evidence on a Pi run
and `pass/not_applicable` evidence on a Windows run; it may never silently
accept one file, mismatched source/environment identity, or unsafe proof.
`ui.injected_stall_detected` is `pass/not_requested` for an ordinary run and
requires attributed detection plus a stack capture when the existing
injected-stall option is requested.

Visible milestones/screenshots are exactly:

```text
editor_opened
generated
ready
printing
mid_array
completed
```

The required semantic action set is the existing composed one-stock action
set. `artifact.capture_milestone` may repeat; every other action has its
existing bounded multiplicity. No legacy `fixture.prepare_authoritative`,
`machine.connect_ready`, `head.stage_virtual`, or
`validation.terminal_bundle` action may appear in a passing composed ledger.

The report retains report-v1 plus the composed action/assertion ledgers and
evidence manifest. Existing comparison paths under responsiveness remain
present, including scheduling p95/p99, persistence/controller phase p95s,
and maximum event-loop service gap. Existing persistence counts, terminal
transition facts, pressure-render evidence, queue cleanup, progress snapshot,
stall assessment, resources, workload compatibility fields, and Pi identity
fields remain inspectable.

## Code-Shape And Reuse Gates

- the named 96-well body/wrapper is at most 20 physical lines;
- the 96-well fixture loader, summary, contract, and definition together add
  at most 90 physical lines;
- the existing 24- and new 96-well definitions reference the same body, stock
  pass builder, payload builder, and UI action set;
- schema-v1 compatibility adds at most 70 physical lines and changes no
  fixture bytes;
- the regression evidence profile and report projection add at most 450 net
  physical lines after code moved out of `scenarios.py` is subtracted;
- total touched runtime net growth is at most 550 physical lines;
- `actions.py` and `page_drivers.py` gain no new raw QTest or workflow driver;
- `registry.run_registered_scenario()` gains no scenario-ID conditional;
- no second report envelope, observer family, or direct persistence parser is
  introduced; and
- accepted baseline JSON files remain byte-identical.

Line limits are review gates, not permission to compress or obscure code. If
the evidence profile cannot preserve the frozen metric paths within these
limits, stop and amend this plan rather than copy the legacy runner or weaken
the comparison contract.

## Exact Files To Touch During Implementation

Required runtime files:

- new `tools/virtual_workflows/regression_evidence.py`
- `tools/virtual_workflows/execution_observer.py`
- `tools/virtual_workflows/actions.py`
- `tools/virtual_workflows/scenarios.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/journey_phases.py`
- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/harness.py`
- `tools/virtual_workflows/composition.py`
- `tools/virtual_workflows/report.py`
- `tools/virtual_workflows/registry.py`
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`

Required focused tests:

- `tests/test_virtual_workflow_journey_phases.py`
- `tests/test_virtual_workflow_assertions.py`
- `tests/test_virtual_workflow_harness.py`
- `tests/test_virtual_workflow_composition.py`
- `tests/test_virtual_workflow_report.py`
- `tests/test_virtual_workflow_manifest.py`
- `tests/test_virtual_workflow_contract_freeze.py`
- `tests/performance/test_virtual_workflow_comparison.py`
- `tests/system/test_pi_virtual_workflow_lane.py`
- existing `tests/system/test_virtual_print_array_workflow.py`
- new `tests/system/test_virtual_print_array_96_composed.py`

Required implementation documentation:

- `README.md`
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- this implementation plan, for status only
- new
  `docs/sil_interactive_simulation_milestone_7_slice_7_completion_record.md`

`tools/run_virtual_workflow.py`, `tools/virtual_workflows/compare.py`,
`tools/virtual_workflows/pi_sil.py`, `tools/virtual_workflows/metrics.py`,
`tools/virtual_workflows/persistence_io.py`,
`tools/virtual_workflows/progress_snapshot.py`, both accepted baseline JSON
files, both print-array fixtures, production MVC, simulator responses, Pi
scripts, firmware, protocol, and hardware files are validation inputs and are
not expected to change. If implementation proves one necessary, stop and
amend this plan before editing it.

## Implementation Steps

1. **Freeze the legacy oracle and compatibility inputs.** Record fixture and
   accepted-baseline hashes; freeze normal, injected-stall, timeout, report-set,
   comparison, and local Pi projections before changing dispatch.
2. **Extract one regression evidence profile.** Move the legacy phase,
   persistence-I/O, progress, queue, responsiveness, resource, pressure-render,
   midpoint/stall, Pi, and restoration ownership behind a typed install,
   snapshot, and restore API; make the legacy runner delegate to it.
3. **Generalize the one-stock composition.** Add strict schema-v1/v2 stock and
   staging projections, preserve the 5-to-10 nL calibration transition, add a
   typed midpoint milestone, and keep both fixtures and raw QTest drivers
   unchanged.
4. **Add shared regression assertions and reporting.** Convert profile output
   into the ten frozen assertion decisions and existing report-v1 metric paths;
   extend the generic report/config/replay path only for optional regression
   evidence, injected-stall controls, and paired Pi identity.
5. **Compose and register 96 wells.** Add the thin definition over the shared
   one-stock body, switch only `virtual_print_array_96_v1` to
   `composed_journey`, retain all three support flags, and update manifest
   actions/surfaces/artifacts/test nodes without broadening capability claims.
6. **Add focused success, parity, and fail-closed tests.** Prove exact 96-well
   order/completion, 5-to-10 nL calibration, UI surfaces, diagnostics,
   direct/composed parity, timeout artifacts, injected-stall attribution,
   observer restoration, and rejection of partial/mismatched Pi evidence or
   missing required metrics.
7. **Run targeted regression, compatibility, visible, and replay gates.** Use
   only the commands below; inspect the report, ledgers, metric paths, hashes,
   six screenshots, stall stack, cleanup, and exact replay projection.
8. **Document and close Slice 7.** Update README commands/troubleshooting,
   roadmap status, measured code shape, targeted results, retained evidence,
   risks, and rollback. Stop before planning or implementing 384x10 stress.

## Focused Automated Gates

Use distinct roots below `%TEMP%\LabCraft`. A normal 96-well node currently
finishes in seconds at `--speed-multiplier 1000`. If one node stops making
progress materially beyond its 60-second internal deadline, inspect and
terminate only that confirmed process; do not wait for a 15-minute outer
timeout. The existing injected-stall node may be retried once in a fresh
process/root. Two consecutive failures block migration and are recorded as a
pre-existing timing issue; they do not authorize performance remediation.

Reusable profile/composition/report/contract tests:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice7-unit" `
  tests\test_virtual_workflow_journey_phases.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_harness.py `
  tests\test_virtual_workflow_composition.py `
  tests\test_virtual_workflow_report.py `
  tests\test_virtual_workflow_manifest.py `
  tests\test_virtual_workflow_contract_freeze.py `
  tests\performance\test_virtual_workflow_comparison.py `
  tests\system\test_pi_virtual_workflow_lane.py
```

Composed success/parity/failure and retained direct oracle:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-regression `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice7-regression" `
  tests\system\test_virtual_print_array_96_composed.py `
  tests\system\test_virtual_print_array_workflow.py
```

Revalidate the unchanged 24-well one-stock composition:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice7-smoke" `
  tests\system\test_virtual_workflow_smoke.py
```

Also run:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py --help
.\env\Scripts\python.exe -m py_compile `
  tools\virtual_workflows\regression_evidence.py `
  tools\virtual_workflows\scenarios.py `
  tools\virtual_workflows\journeys.py `
  tools\virtual_workflows\journey_phases.py `
  tools\virtual_workflows\assertions.py `
  tools\virtual_workflows\harness.py `
  tools\virtual_workflows\composition.py `
  tools\virtual_workflows\report.py `
  tools\virtual_workflows\registry.py
git diff --check
git status --short
```

Do not run unscoped `pytest -q` in Slice 7. The complete Python suite remains
the final Milestone 7 validation gate.

## Success, Parity, And Failure Gates

The composed success test must prove:

- a real application is constructed with hardware access disabled and only
  the literal simulated port;
- the editor creates A1-D1 in exact four-row serpentine order through normal
  controls and persists a prepared execution;
- the stock starts at the fixture's 5 nL prepared value, applies 10 nL at
  1300 us and 1.2 psi through the normal calibration dialog, and uses one
  associated staged head;
- exactly 96 unique stock/well intents complete once, `array_complete` occurs
  once, queue starvation is zero, the terminal plan is `COMPLETED`, and all
  observers restore before teardown;
- the exact durable-operation, authoritative-read, progress-snapshot,
  terminal-transition, pressure-render, and simulator-cleanup relationships
  required by the existing focused regression remain true;
- ordinary and injected runs both emit the frozen assertions and metric paths;
  injected stall evidence names the injected phase and retains a readable
  stack capture;
- paired Pi evidence is locally validated and represented without claiming or
  performing a remote Pi run;
- all six screenshots, action/assertion ledgers, evidence manifest, events,
  stall-stack file, hashes, seed, replay command, and clean teardown exist.

Stable direct/composed parity compares fixture/workload identity, well order,
calibration, completion and queue counts, persistence invariants, terminal
state, responsiveness metric presence/shape, injected-stall assessment, Pi
identity projection, classification, and cleanup. It explicitly permits the
composed path's UI action/surface ledger, editor screenshots, seed/replay
fields, generated plan/head identities, paths, timestamps, durations, and
identity-bearing hashes to differ.

At minimum, tests must fail closed for a missing responsiveness metric,
unrestored observer, incomplete terminal persistence evidence, unexpected
dialog, timeout, one-sided Pi evidence, source/environment mismatch, and
unsafe Pi proof. Failures retain the available screenshot, traceback,
events, stack file, ledgers, evidence manifest, partial metrics, and
best-effort cleanup. Existing UI-stall injection and timeout are compatibility
tests, not new product/simulator fault-injection features.

## Visible And Replay Gate

Run once through the normal Windows UI:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario virtual_print_array_96_v1 `
  --output-root verification_reports\milestone7-slice7-visible `
  --visible --seed 1 --speed-multiplier 2 --timeout-seconds 90
```

Inspect the editor, rack/head, calibration, printing, midpoint, and completed
screenshots; report; action/assertion ledgers; evidence manifest; events;
stall-stack artifact; metric paths; scenario root; and cleanup. Confirm the
workflow uses the editor and normal controls, every state-changing action is
truthfully surfaced, and hardware access remains disabled.

Then execute the exact `run.replay_command` emitted by that report into the
same output root. Require equal stable projection for fixture hash/seed,
action IDs/multiplicity/surfaces/statuses, assertion decisions, dialogs,
well/completion order, calibration, milestone/screenshot names, persistence
relationships, metric shape, classification, and cleanup. Ignore only
documented generated identities, paths, timestamps, durations, measured
timing values, and hashes bearing those identities.

## Risks And Mitigations

- **Instrumentation overwhelms the journey abstraction:** isolate it behind
  one optional profile and enforce the 20-line body and net-growth gates.
- **Schema-v1 adaptation changes fixture semantics:** hash the fixture before
  and after, test the 5-to-10 nL transition, and keep adaptation read-only.
- **UI migration invalidates accepted timing baselines:** preserve metric
  paths and comparison compatibility, but do not rewrite baselines or require
  performance acceptance in this slice; any performance decision is separate.
- **Pi evidence is accidentally dropped or overclaimed:** retain support flags,
  require paired local evidence, and freeze Pi run-mode/safety projections
  without executing a remote operation.
- **Observer teardown contaminates later Qt tests:** require idempotent reverse
  restoration on success/failure and assert all timers/threads/hooks are
  inactive before generic teardown completes.
- **Injected-stall timing flakes:** isolate and retry the exact node once;
  repeated failure blocks migration without expanding scope.
- **384x10 behavior changes prematurely:** keep its registry entry on the
  legacy runner and run only non-executing contract checks for it.

## Rollback

Keep `run_virtual_print_array_scenario()` directly callable until every
focused parity/evidence gate passes. If migration fails, restore only the
`virtual_print_array_96_v1` registry and manifest entry to
`virtual_print_array`; remove its composed definition and tests; and restore
the legacy-local instrumentation only if delegation caused the regression.

Retain independently passing schema adapters or evidence-profile helpers only
if the 24-well composed journey and legacy 96/384 contracts still pass and no
active scenario selects incomplete behavior. Do not modify or delete accepted
baselines, retained reports, Slice 6 or earlier migrations, production data,
or the 384x10 fixture/runner. No production MVC, firmware/protocol, simulator,
Pi-host, or hardware rollback is required.

## Approval Gate

Do not implement Slice 7 until the user approves this plan. Any fixture or
accepted-baseline change, production MVC edit, report-schema revision,
second workflow migration, performance remediation, active parameter matrix,
seeded exploration, new product/simulator fault injection, remote Pi
operation, firmware/protocol change, or hardware work requires an amended
plan and separate approval.

## Implementation Outcome

The approved migration and targeted gates are complete. Two audit findings
required explicit corrections to planning assumptions without changing the
fixture, accepted baselines, production MVC, simulator, firmware, protocol,
Pi scripts, or hardware:

- The normal application-owned pulse-aware synthetic calibration model
  produces 9 nL at the frozen 1300 us setting. The composed path truthfully
  selects and applies that 9 nL result from the fixture's 5 nL prepared value;
  it does not reproduce the legacy shortcut's canned 10 nL effective value.
  The fixture's 10 nL design target remains byte-identical and visible. A
  shared assertion now fails closed unless source volume, measured/applied
  volume, pulse width, and pressure match the deterministic SIL model.
- Touched runtime growth measured net +904 physical lines rather than the
  planned +550. The 96-well definition itself remains thin and shares the
  24-well body/action set/payload; the variance is reusable evidence,
  assertion, schema adapter, reporting, configuration, and visible-settle
  infrastructure. The regression profile plus report projection is net +424,
  within its +450 sub-gate. No second workflow-specific body, QTest driver,
  report envelope, or observer family was added.

The plan's `--run-sil-smoke` command was also corrected because this checkout
does not define that pytest option; the focused smoke module runs directly.
The completion record contains exact results, retained visible/replay roots,
hashes, risks, and rollback.
