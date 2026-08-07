# Milestone 7 Slice 4 — Composed Soft Stop/Resume

Status: `implemented and validated — code-growth gate requires review`

Completion evidence is recorded in
`docs/sil_interactive_simulation_milestone_7_slice_4_completion_record.md`.

Planning baseline: `f4ae6312a0ccd91719284ca956015f8e7f078a6a` with a clean
worktree.

## Objective

Migrate only `print_array_soft_stop_resume_24_v1` from the branch-heavy legacy
print-array runner to the Milestone 6 / Slice 2.5 typed composition harness.
The composed journey will create and finalize the tracked A1-A24 one-stock
design through normal Qt controls, prepare and calibrate the virtual head,
start printing through the normal UI, click `Stop After Well` at completion 6,
prove the confirmed pause/clear/park boundary and 250 ms quiescence window,
click `Resume Print`, and reconcile exactly 24 terminal stock/well
completions.

This slice adds a reusable typed soft-stop boundary and resume phase intended
for later reuse by the authoritative-reload migration. It does not migrate
`authoritative_reload_resume_24_v1`, post-start lock/editable copy, the 96-well
regression, 384x10 stress, disconnect, refill-required resume, or another
workflow. It does not add a parameter matrix, seeded sequence exploration,
fault injection, performance remediation, Pi operation, firmware/protocol
work, or hardware operation.

No file under `FreeRTOS-interface/`, `firmware/`, or the simulation response
model is in scope.

## Audit Baseline

- The planning worktree is clean at the baseline above. Milestone 7 Slices
  1–3.5 and the focused editable-copy dialog correction are committed.
- The tracked fixture remains schema v3 with one droplet stock, wells A1-A24,
  completion trigger 6, maximum catch-up 2, and a 250 ms quiescence window.
- The existing fixture, legacy success, and controlled paused-boundary failure
  nodes passed with `--run-sil-lifecycle`: `3 passed in 9.45s`.
- The current registry routes this ID through `runner_family ==
  "virtual_print_array"`; the composed registry already routes the smoke,
  editor create/refinalize, and 24x2 multi-stock journeys generically.
- The complete Python suite was not run and remains deferred to the final
  Milestone 7 validation.

## Current Call Paths And Duplication

### Registry and legacy automation

```text
tools/run_virtual_workflow.py
  -> registry.run_registered_scenario()
  -> runner_family == "virtual_print_array"
  -> scenarios.run_virtual_print_array_scenario()
       -> is_pause_resume_lifecycle branches
       -> legacy fixture/application/instrumentation/report/teardown owner
       -> request_soft_stop_via_ui()
       -> _validate_soft_stop_paused_scenario()
       -> observe_stopped_quiescence()
       -> start_array_via_ui() again for resume
       -> _validate_soft_stop_completed_scenario()
```

`run_virtual_print_array_scenario()` owns application construction, observers,
dialogs, execution, persistence validation, report assembly, failure capture,
and teardown for uninterrupted, multi-stock, soft-stop, and authoritative
reload branches. Those generic responsibilities duplicate `JourneyExecutor`,
`AutomationHarness`, `ExecutionObserver`, and `ComposedReportAdapter`.

The soft-stop-specific paused and terminal validators are large private
functions in `scenarios.py`. Their read-only intent, audit, resume, progress,
and terminal checks are also needed by the composed journey and later
authoritative reload. Copying them into `journeys.py` would create a second
policy implementation.

`request_soft_stop_via_ui()` contains raw QTest control mechanics even though
`ArrayDriver` is the shared print-array page driver. `start_array_via_ui()` and
`ArrayDriver.start()` also duplicate the start/resume button mechanics. The
composed stock-pass phase currently runs uninterrupted from start to terminal
completion, so it has no typed boundary at which a pause/resume phase can be
inserted.

### Production application path exercised

```text
QTest -> WellPlateWidget.start_print_array_button ("Stop After Well")
  -> WellPlateWidget.start_print_array()
  -> WellPlateWidget.request_array_soft_stop()
  -> Controller.request_array_soft_stop()
  -> machine.request_pause_after_seq32(current barrier)
  -> SimulatedMachine watermark/status callback
  -> Controller._begin_soft_stop_clear_and_park()
  -> machine.clear_command_queue()
  -> Controller soft-stop finalization
  -> ExperimentModel authoritative progress/resume/plan writers
  -> Controller state "resume_ready"

QTest -> same button ("Resume Print")
  -> WellPlateWidget.start_print_array()
  -> "Resume Print Array" confirmation and normal preflights
  -> Controller.print_array()
  -> ExperimentModel authoritative pass preparation/checkpoint writers
  -> machine.resume_commands() when transport remains paused
  -> normal array command lifecycle -> SimulatedMachine
```

On real hardware the machine boundary continues through `Machine_FreeRTOS`
and firmware pause-after/clear/resume handlers. Slice 4 ends at
`SimulatedMachine`; it changes none of that production path and makes no
firmware, protocol, motion, pressure, collision-safety, or physical dispensing
claim.

### Target composed path

```text
CLI / generic registry dispatch
  -> run_composed_journey(JourneyRunConfig)
  -> JourneyDefinition for print_array_soft_stop_resume_24_v1
  -> JourneyExecutor / AutomationHarness / SimulationSession
       -> existing machine-startup and editor-preparation phases
       -> existing typed stock/head preparation and calibration
       -> SoftStopResumeSpec
       -> reusable active-array soft-stop boundary
          -> ArrayDriver -> bounded QTest "Stop After Well"
          -> shared execution observer + authoritative snapshot
          -> reusable paused assertions
          -> bounded quiescence observation
       -> reusable resume phase
          -> ArrayDriver -> bounded QTest "Resume Print"
       -> reusable terminal pause/resume assertions
       -> ComposedReportAdapter / generic failure and teardown
```

The named journey body must remain a short composition. It must not contain a
Qt timer loop, persistence parser, intent-reconciliation implementation,
report envelope, or teardown implementation.

## Frozen Slice Decisions

1. **One migration only.** Preserve the scenario ID, name, version, fixture
   bytes and SHA-256, completion trigger/count, lifecycle suite membership,
   capability claims, ten required assertion IDs, and expected pass outcome.
2. **Normal UI setup and lifecycle.** The composed journey creates the design,
   prepares/calibrates the head, starts, stops, and resumes through normal Qt
   controls. Direct prepared-fixture creation, model head staging, and
   controller pressure toggling from the legacy action list will not claim UI
   coverage.
3. **One page driver per surface.** Extend `ArrayDriver` with bounded methods
   that verify the exact button text/state and handle the exact resume dialog.
   The semantic trigger owns completion-count policy; the page driver owns only
   QTest mechanics and visible control checks. The legacy action delegates to
   the same driver while it remains a parity oracle.
4. **Distinct resume semantics.** Add `array.resume_via_ui` rather than record a
   second start action. It must report `ui`, accept only `Resume Print Array`,
   and require the controller to transition from `resume_ready` to `running`.
   This is an explicit reviewed action-contract improvement; the required
   assertion IDs remain unchanged.
5. **Reusable typed boundary.** Add a frozen `SoftStopResumeSpec` containing
   trigger count, maximum catch-up, quiescence duration, and milestone names.
   Add separate reusable stop-boundary and resume operations so Slice 5 can
   insert application teardown/reload between them without copying Slice 4.
6. **One read-only policy implementation.** Consolidate the existing legacy
   paused/terminal check logic into reusable assertion/evidence helpers used by
   both the legacy oracle and composed journey. They may inspect shared
   `AuthoritativeBundleSnapshot`, observer evidence, controller/UI state, and
   simulator state; they may not repair, activate, write, advance time, or
   dismiss dialogs.
7. **Stable semantic parity, not identical action plumbing.** Preserve fixture,
   request/catch-up, paused checkpoint, quiescence, intent reconciliation,
   durable-write counts, audit ordering, terminal state, classification, and
   failure decisions. Explicitly allow the composed normal-UI action list,
   action/assertion ledgers, eight screenshot keys, replay metadata, and
   nondeterministic IDs/paths/timestamps/durations to differ from legacy.
8. **Targeted validation only.** Run the focused gates below. Do not run the
   full Python suite until final Milestone 7 validation.

## Frozen Composed Contract

Required assertions remain exactly:

```text
sil.host_hardware_disabled
ui.real_app_constructed
execution.soft_stop_requested
execution.soft_stop_boundary_valid
execution.stopped_boundary_quiescent
execution.resume_exactly_once
execution.expected_completions
execution.intent_durability_exact
execution.terminal_bundle_valid
artifacts.required_present
```

The visible milestones/screenshots are exactly:

```text
editor_opened
generated
ready
printing
stop_requested
stopped
resumed
completed
```

The action ledger must show the existing normal-UI startup/editor/head/
calibration actions followed by this ordered lifecycle window:

```text
array.start_via_ui                  ui
artifact.capture_milestone          harness  (printing)
array.request_soft_stop_via_ui      ui
artifact.capture_milestone          harness  (stop_requested)
array.wait_for_state                harness  (resume_ready)
artifact.capture_milestone          harness  (stopped)
array.observe_stopped_quiescence    harness
array.resume_via_ui                 ui
artifact.capture_milestone          harness  (resumed)
array.wait_for_completions          harness
artifact.capture_milestone          harness  (completed)
```

Read-only assertions replace legacy `validation.paused_bundle` and
`validation.terminal_bundle` action rows; validation is not an operator action.
The system test freezes the complete action order, multiplicity, surfaces,
dialogs, assertions, screenshots, and report paths.

## Code-Shape Gates

Slice 4 is not complete if it adds another large scenario runner:

- `_soft_stop_body` is at most 120 physical lines;
- `_soft_stop_payload` is at most 90 physical lines;
- the named journey's constants, fixture adapter, body, payload, summary, and
  definition add at most 220 physical lines total;
- reusable stop-boundary and resume phase functions add at most 180 physical
  lines total, excluding validated dataclass declarations;
- raw `QTest` for the array start/stop/resume control exists only in
  `ArrayDriver` after the migration;
- paused and terminal soft-stop policy checks have one implementation consumed
  by both legacy and composed paths;
- `registry.run_registered_scenario()` gains no scenario-ID conditional;
- total touched runtime growth is at most 450 physical lines after removing or
  delegating duplicate legacy validation/action mechanics.

Line limits are review gates, not permission to compress or hide behavior. If
the implementation cannot meet them cleanly, stop and propose a bounded Slice
4.5 consolidation rather than accepting another monolith.

## Exact Files To Touch During Implementation

Required runtime files:

- `tools/virtual_workflows/actions.py`
- `tools/virtual_workflows/page_drivers.py`
- `tools/virtual_workflows/journey_phases.py`
- `tools/virtual_workflows/execution_observer.py`
- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/scenarios.py`
- `tools/virtual_workflows/registry.py`
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`

Required focused tests:

- `tests/test_virtual_workflow_actions.py`
- `tests/test_virtual_workflow_page_drivers.py`
- `tests/test_virtual_workflow_journey_phases.py`
- `tests/test_virtual_workflow_execution_observer.py`
- `tests/test_virtual_workflow_assertions.py`
- `tests/test_virtual_workflow_composition.py`
- `tests/test_virtual_workflow_manifest.py`
- `tests/test_virtual_workflow_contract_freeze.py`
- new `tests/system/test_virtual_workflow_soft_stop_composed.py`

Required implementation documentation:

- `README.md`
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- this implementation plan, for status only
- new
  `docs/sil_interactive_simulation_milestone_7_slice_4_completion_record.md`

The existing `tests/system/test_virtual_workflow_lifecycle.py`, composed smoke
and multi-stock system tests, controller/view lifecycle tests, and fixture are
validation inputs but are not expected to change. The tracked fixture
`tools/virtual_workflows/fixtures/print_array_soft_stop_resume_24_v1.json`
must remain byte-identical.

`composition.py`, `harness.py`, `report.py`, `authoritative_evidence.py`, all
production MVC files, simulator response models, Pi scripts, firmware,
protocol, and hardware files are not expected to change. If implementation
proves one necessary, stop and amend this plan before editing it.

## Implementation Steps

1. **Freeze legacy baseline and parity projections.** Run the exact legacy
   fixture/success/failure nodes, retain one fixed-input direct report, and
   capture stable workload, request/catch-up, paused, quiescence, intent,
   durable-write, audit, terminal, dialog, screenshot, assertion, failure, and
   cleanup fields. Record the fixture hash before editing.
2. **Unify the array-control mechanics.** Add bounded `ArrayDriver` stop and
   resume operations; make the legacy soft-stop semantic action delegate to the
   same driver; expose only small non-ledger operation helpers needed by the
   composed harness; and add/freeze `array.resume_via_ui` with truthful surface
   reporting and exact dialog handling.
3. **Add typed pause/resume phases.** Define and validate
   `SoftStopResumeSpec`; add a normalized lifecycle-plan helper; allow the
   existing stock-pass execution to interpose one active-array phase without
   duplicating setup/calibration/terminal code; and implement separate reusable
   stop-boundary, quiescence, and resume operations.
4. **Consolidate read-only lifecycle evidence and assertions.** Extend the
   restorative execution observer only for facts already captured by legacy
   instrumentation. Extract one paused and terminal policy implementation,
   adapt the legacy validators to it, and produce the ten frozen assertion
   decisions plus compatible `soft_stop_resume`, progress, authoritative-I/O,
   and terminal evidence for the composed report.
5. **Compose and register the journey.** Add the fixture adapter, one-stock
   pass specification, concise body, required actions/UI actions/screenshots/
   assertions, bounded payload, summary, and `JourneyDefinition`; change only
   this registry entry to `composed_journey` through existing generic dispatch.
   Retain the direct legacy callable as the parity oracle and because the
   unmigrated authoritative-reload runner still shares its pause path.
6. **Update manifest and contract tests.** Replace legacy bypass/action and
   artifact metadata with the composed normal-UI action list and retained
   ledgers, point this scenario's test/evidence nodes at the new composed test,
   freeze exact contracts and source-shape gates, and preserve suite membership
   and capability coverage without adding claims.
7. **Run focused parity, failure, visible, and replay gates.** Run the unit,
   production-adjacent, legacy-oracle, composed success/parity, and controlled
   failure selections below. Then run one visible CLI journey and its exact
   emitted replay; inspect artifacts and compare stable projections. Do not run
   the full suite.
8. **Document and close the slice.** Update README commands and troubleshooting,
   roadmap status, measured code shape, exact validation results, retained
   evidence, risks, and rollback in the completion record. Stop before planning
   or implementing authoritative reload/resume.

## Focused Automated Gates

Use distinct temporary roots. If a combined Windows Qt run stops making
progress beyond its 60-second scenario deadline, terminate only the confirmed
process for that run and rerun the exact affected node separately; do not wait
for an unrelated 15-minute outer timeout.

Reusable automation and contract tests:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice4-unit" `
  tests\test_virtual_workflow_actions.py `
  tests\test_virtual_workflow_page_drivers.py `
  tests\test_virtual_workflow_journey_phases.py `
  tests\test_virtual_workflow_execution_observer.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_composition.py `
  tests\test_virtual_workflow_report.py `
  tests\test_virtual_workflow_manifest.py `
  tests\test_virtual_workflow_contract_freeze.py
```

Production soft-stop/resume contracts, with no production edits expected:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice4-adjacent" `
  tests\test_view_array_controls.py `
  tests\test_controller_print_guards.py `
  tests\test_controller_experiment_audit.py `
  tests\test_execution_resume_store.py `
  tests\test_execution_lifecycle_hardening.py
```

Composed and legacy lifecycle gates:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice4-lifecycle" `
  tests\system\test_virtual_workflow_soft_stop_composed.py `
  tests\system\test_virtual_workflow_lifecycle.py `
  tests\system\test_virtual_workflow_smoke.py `
  tests\system\test_virtual_workflow_multi_stock_composed.py
```

Also run:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py --help
.\env\Scripts\python.exe -m py_compile `
  tools\virtual_workflows\actions.py `
  tools\virtual_workflows\page_drivers.py `
  tools\virtual_workflows\journey_phases.py `
  tools\virtual_workflows\execution_observer.py `
  tools\virtual_workflows\assertions.py `
  tools\virtual_workflows\journeys.py `
  tools\virtual_workflows\scenarios.py `
  tools\virtual_workflows\registry.py
git diff --check
git status --short
```

Do not run unscoped `pytest -q` in Slice 4. The complete Python suite remains
the final Milestone 7 validation gate.

## Success, Parity, And Controlled-Failure Gates

The composed success test must prove:

- hardware interfaces disabled and the real application visible to QTest;
- exact UI action surfaces, dialog order, and eight milestones;
- soft-stop click recorded at completion 6 with a positive barrier;
- catch-up between one and two completions;
- ACTIVE plan identity preserved at a paused, empty checkpoint with
  `ready_to_resume` eligibility;
- confirmed watermark, transport pause, queue clear, certain state, empty
  simulator queue, and controller `resume_ready`;
- no completion or progress movement during 250 ms quiescence;
- exactly one resume transition and two total `running` transitions;
- 24 exact terminal stock/well completions, with every discarded lookahead
  intent reissued and no ambiguous intent;
- clean empty terminal checkpoint, COMPLETED plan, valid authoritative bundle,
  exact progress updates, audit order, and durable write formula;
- all ten assertions pass, all required artifacts are non-empty, every cleanup
  step passes, and no error, unexpected dialog, failure traceback, or session
  lock remains.

Stable composed/legacy parity compares fixture identity, request and catch-up,
paused checkpoint, quiescence counts, completed/discarded/reissued intent
relationships, progress mode counts, resume/progress durability totals, audit
subsequence, terminal plan/checkpoint/completion state, assertion decisions,
classification, and limitations. It does not require identical action lists,
artifact envelopes, generated identities, paths, timestamps, durations, or
identity-bearing hashes.

At minimum, inject a paused-boundary evidence failure after the soft-stop
request. Require `execution.soft_stop_requested=pass`,
`execution.soft_stop_boundary_valid=fail`, later lifecycle assertions
`incomplete`, retained failure screenshot/trace/ledgers/manifest, restored
observer hooks, passing teardown, and no session lock. Also reject any resume
modal whose title or button differs from the exact policy.

## Visible And Replay Gate

Run once through the normal Windows UI:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario print_array_soft_stop_resume_24_v1 `
  --output-root verification_reports\milestone7-slice4-visible `
  --visible --seed 1 --speed-multiplier 2 --timeout-seconds 60
```

Inspect the retained report, action/assertion ledgers, evidence manifest, event
trace, scenario root, and all eight screenshots. Verify that `Stop After Well`,
`Stop Pending`, and `Resume Print` are visibly represented at the expected
boundaries and that hardware access remains disabled.

Then execute the exact `run.replay_command` emitted by that report into the
same output root. Require equal stable projection for fixture hash and seed,
ordered action IDs/multiplicity/surfaces/statuses, dialog titles, assertion
decisions, screenshot keys, lifecycle/persistence relationships,
classification, and cleanup. Ignore only documented generated identities,
paths, timestamps, durations, and identity-bearing hashes.

## Risks And Mitigations

- **Exact-trigger race:** connect the completion observer before the trigger,
  queue one QTest click only at count 6, fail on overshoot or duplicate click,
  and retain the bounded one-to-two completion catch-up contract.
- **UI coverage is overstated:** require `ui` only for page-driver/QTest start,
  stop, and resume operations; waits, assertions, snapshots, milestones, and
  reports remain `harness`.
- **Pause evidence is sampled too late:** capture request, watermark/clear,
  authoritative snapshot, controller/button state, and simulator drain before
  the quiescence window or resume action can alter them.
- **Discarded intents are lost or replayed incorrectly:** preserve exact begin,
  attach, discard, completion, pair reissue, checkpoint, audit, and durable-I/O
  reconciliation from the legacy acceptance contract.
- **Observer wrappers leak after failure:** register the observer as a
  restorable before execution, inject a paused-boundary failure, and require
  reverse restoration plus clean session teardown.
- **Shared authoritative-reload behavior regresses:** keep the direct legacy
  lifecycle tests and authoritative-reload tests unchanged; shared validator
  delegation must preserve their current evidence shape.
- **Another monolith is introduced:** enforce the code-shape and one-policy
  gates. Stop for a consolidation plan if they cannot be met without hiding
  behavior.
- **Windows Qt batching stalls:** keep the scenario deadline at 60 seconds,
  use separate temp roots, inspect a stalled process promptly, and isolate
  affected nodes rather than waiting for the full-suite timeout.

## Rollback

Keep `run_virtual_print_array_scenario()` directly callable until parity and
focused regression gates pass. If the migration fails, restore only the
soft-stop registry entry and manifest metadata to `virtual_print_array`;
remove the composed definition, typed lifecycle phase/spec, distinct resume
action, shared driver additions, composed tests, and Slice 4 documentation.
Restore the legacy validators if shared delegation was introduced.

Do not revert the fixture, SimulationSession, generic executor, existing
composed journeys, Slice 2.5/3.5 consolidation, production experiment data, or
other Milestone 7 work. No firmware/protocol, production MVC, Pi, simulator
response model, or hardware rollback is required.

## Approval Gate

Do not implement this plan until the user approves it. Approval covers only
the exact scope, files, eight steps, code-shape gates, targeted-test policy,
visible/replay evidence, and rollback above. Any production MVC change,
fixture revision, report-schema change, second workflow migration, active
matrix, seeded exploration, fault injection, performance work, Pi operation,
firmware/protocol change, or hardware work requires a revised plan and
separate approval.
