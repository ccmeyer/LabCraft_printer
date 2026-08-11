# Milestone 7 Slice 5 - Composed Authoritative Reload/Resume

Status: `implemented and validated on 2026-08-06`

Completion record:
`docs/sil_interactive_simulation_milestone_7_slice_5_completion_record.md`

Planning baseline: `8cbe492f408421cece0ae77bf5960685b1aea3d6` with the
Milestone 7 Slice 4 implementation committed and a clean worktree before this
planning-only documentation update.
The Slice 4 runtime-growth variance has been explicitly accepted by the user;
no consolidation pass is required before this slice.

## Objective

Migrate only `authoritative_reload_resume_24_v1` from the branch-heavy legacy
print-array runner to the Milestone 6 / Slice 2.5 typed composition harness.
The composed journey will create the tracked A1-A24 design through normal Qt
controls, print through completion 6, request and prove a soft-stop boundary,
close the first application session, open a fresh application composition on
the same retained SIL root, load and activate the authoritative execution
through Experiment Editor, restage the persisted virtual head through normal
controls, resume through the normal array control, and reconcile exactly 24
terminal stock/well completions without replaying completed work.

This slice adds reusable application-session rotation and authoritative
load/activation phases. It does not migrate post-start lock/editable copy, the
96-well regression, 384x10 stress, disconnect, or another workflow. It does
not add parameter matrices, seeded sequence exploration, fault injection,
performance remediation, Pi operation, firmware/protocol work, or hardware
operation.

No file under `FreeRTOS-interface/`, `firmware/`, or the simulation response
model is in scope.

## Audit Baseline

- Slice 4 is present as staged work and routes
  `print_array_soft_stop_resume_24_v1` through `composed_journey`. Its reusable
  `SoftStopResumeSpec`, stop-boundary phase, resume phase, `ArrayDriver`
  mechanics, observer evidence, and paused/terminal assertions are available.
- `authoritative_reload_resume_24_v1` still uses the default
  `virtual_print_array` runner. Its fixture remains schema v3, one droplet
  stock, wells A1-A24, stop request after completion 6, maximum catch-up 2,
  250 ms quiescence, and two application sessions.
- The fixture SHA-256 is
  `20B0EA605B74E1C282D7DD62E1B1A04C2FF1B76616E6BF87994055E6FBD7CDE5`.
- The fixture and current direct lifecycle oracle passed before planning:
  `2 passed in 7.77s` with `--run-sil-lifecycle`.
- The full Python suite was not run and remains deferred to the final
  Milestone 7 validation.

## Current Call Paths And Duplication

### Legacy automation path

```text
tools/run_virtual_workflow.py
  -> registry.run_registered_scenario()
  -> runner_family == "virtual_print_array"
  -> scenarios.run_virtual_print_array_scenario()
       -> authoritative-reload scenario branches
       -> common first-session setup/start
       -> Slice 4 soft-stop request, pause validation, and quiescence
       -> capture bundle/inventory/intent/progress/I/O evidence
       -> actions.close_simulated_session()
       -> manually rebuild ApplicationComponents and SimulatedMachine
       -> manually reconnect callbacks, probe, observers, stdout, and dialogs
       -> actions.drive_authoritative_reload_via_editor()
            -> private QTimer/QTest modal state machine
            -> QFileDialog selection
            -> loaded-boundary validation
            -> "Load Execution" activation
       -> direct model/controller setup for head, pressure, and resume
       -> terminal and cross-session reconciliation
       -> legacy report/teardown
```

The second application construction duplicates the ownership already provided
by `SimulationSession` and `AutomationHarness`. The private authoritative
editor state machine duplicates `ExperimentLoaderDriver` folder-selection and
modal mechanics. Loaded, activated, between-session, resume, and terminal
policy is embedded in the legacy runner instead of reusable read-only
evidence/assertion helpers. The branch also duplicates observer, callback,
dialog, report, failure, and cleanup plumbing.

### Production application path exercised

```text
QTest -> array control "Stop After Well"
  -> WellPlateWidget soft-stop request
  -> Controller pause/clear/park lifecycle
  -> authoritative progress/resume/plan persistence
  -> SimulatedMachine -> controller state "resume_ready"

harness -> close first SimulationSession application
  -> ApplicationComponents.close() and recorder close
  -> retained SIL root remains hardware-isolated
harness -> reopen retained SimulationSession root
  -> fresh Model -> Controller -> View -> SimulatedMachine composition

QTest -> Experiment Editor -> Load -> QFileDialog folder selection
  -> ExperimentDesignDialog loads and validates the saved execution
QTest -> "Load Execution"
  -> MainWindow.activate_authoritative_execution()
  -> Model.load_authoritative_execution_runtime()
  -> Controller state "resume_ready"

QTest -> machine/rack/pressure controls and "Resume Print"
  -> Controller.print_array()
  -> authoritative resume/checkpoint writers
  -> SimulatedMachine command lifecycle
```

The SIL boundary ends at `SimulatedMachine`. This slice changes no production
MVC, device protocol, firmware, motion, pressure-control, timing-sensitive
hardware, or physical dispensing behavior.

### Target composed path

```text
generic registry dispatch -> JourneyExecutor -> AutomationHarness
  -> existing startup/editor/head/calibration/array phases
  -> run_soft_stop_boundary(SoftStopResumeSpec)
  -> shared paused assertions and immutable first-session snapshot
  -> harness close/reopen of the same retained SIL root
  -> ExperimentLoaderDriver authoritative load and activation
  -> shared loaded/activated boundary assertions
  -> reusable persisted-head restaging and pressure phase
  -> resume_soft_stopped_array()
  -> existing terminal soft-stop assertions
  -> cross-session no-replay/durability assertions
  -> ComposedReportAdapter and generic failure/teardown
```

The named journey body must remain a short composition. It must not construct
MVC objects, install a Qt timer loop, parse persistence files, reconnect raw
signals, assemble a report envelope, or implement teardown.

## Frozen Slice Decisions

1. **One migration only.** Preserve the scenario ID, name, version, fixture
   bytes/hash, lifecycle suite membership, 24 completions, stop trigger,
   catch-up/quiescence limits, twelve required assertion IDs, and expected
   pass outcome.
2. **Fresh application, stable retained session.** Close the first
   `SimulationSession` cleanly and reopen its retained root through
   `SimulationSession.create()`. Require the same SIL `session_id`, two
   distinct application-session/recorder identities, two completed metadata
   records, and no lock left after final teardown. Do not add a second manual
   application-construction path or an OS-process restart claim.
3. **Harness owns rotation.** Refactor `AutomationHarness.start()` only enough
   to reuse one contained create/launch/rebind operation. Add fail-closed
   close/reopen semantics that emit the existing
   `app.close_simulated_session` and second `app.launch_simulated` ledger rows,
   preserve the first recorder artifacts, and leave the harness able to
   retain evidence when second-session construction fails.
4. **One page driver per surface.** `ExperimentLoaderDriver` owns the bounded
   QTest editor, QFileDialog, loaded-state inspection, and exact `Load
   Execution` click. The semantic action wrapper owns action IDs and boundary
   callbacks. Raw authoritative reload QTest is removed from `actions.py`, and
   the direct legacy oracle delegates to the same driver.
5. **Read-only boundaries.** Capture immutable directory/bundle evidence
   before first-session close, after close, after second-session load, and
   after activation. Loading must be byte-identical and runtime-inactive;
   activation may change only the existing five allowlisted authoritative
   files and must produce one activation audit event. Assertions may not
   repair, activate, write, advance simulated time, or dismiss dialogs.
6. **Reuse Slice 4 lifecycle.** Use `run_soft_stop_boundary()` before rotation
   and `resume_soft_stopped_array()` afterward. Generalize milestone names and
   persisted-head preparation only where needed; do not copy the pause,
   quiescence, resume, or terminal policies into the new journey.
7. **Truthful UI coverage.** Editor load/activation, machine controls, rack
   staging, pressure control, and array resume report `ui`. Session rotation,
   waits, snapshots, milestones, comparisons, assertions, and reporting
   report `harness`. No direct Model mutation may receive a UI claim.
8. **Targeted validation only.** Run the focused gates below. The full Python
   suite remains deferred until the final Milestone 7 validation.

Generated application IDs, paths, timestamps, durations, and
identity-bearing hashes may differ between the direct and composed reports.
The report must still prove two distinct fresh application sessions in order.

## Frozen Composed Contract

Required assertions remain exactly:

```text
sil.host_hardware_disabled
ui.real_app_constructed
ui.fresh_application_session_constructed
execution.first_session_paused
execution.first_session_teardown_clean
execution.authoritative_reload_valid
execution.authoritative_runtime_rehydrated
execution.reload_resume_exactly_once
execution.expected_completions
execution.intent_durability_exact
execution.terminal_bundle_valid
artifacts.required_present
```

Visible milestones/screenshots remain exactly:

```text
session_1_ready
session_1_printing
session_1_stop_requested
session_1_stopped
session_2_loaded
session_2_activated
session_2_resumed
completed
```

The exact composed action contract will include the existing normal-UI
startup/editor/head/calibration window and this ordered cross-session window:

```text
array.start_via_ui                       ui
artifact.capture_milestone               harness  (session_1_printing)
array.request_soft_stop_via_ui           ui
artifact.capture_milestone               harness  (session_1_stop_requested)
array.wait_for_state                     harness
artifact.capture_milestone               harness  (session_1_stopped)
array.observe_stopped_quiescence         harness
app.close_simulated_session              harness
app.launch_simulated                     harness  (second occurrence)
experiment.load_authoritative_via_ui     ui
artifact.capture_milestone               harness  (session_2_loaded)
experiment.activate_authoritative_via_ui ui
artifact.capture_milestone               harness  (session_2_activated)
machine.connect_via_ui                   ui
machine.enable_motors_via_ui             ui
machine.home_via_ui                      ui
machine.configure_print_settings_via_ui  ui
head.set_volume_via_ui                   ui
head.stage_via_ui                        ui
pressure.enable_regulation_via_ui        ui
array.resume_via_ui                      ui
artifact.capture_milestone               harness  (session_2_resumed)
array.wait_for_completions               harness
artifact.capture_milestone               harness  (completed)
```

The second application reuses the valid persisted synthetic calibration; it
must not generate or apply a replacement calibration merely to make resume
pass. Contract tests will freeze the final complete order, multiplicity,
surfaces, dialogs, assertions, screenshots, and report paths.

## Code-Shape And Reuse Gates

- `_authoritative_reload_body` is at most 140 physical lines;
- its payload builder is at most 100 physical lines;
- all scenario-specific constants, fixture adapter, body, payload, summary,
  and definition add at most 260 physical lines;
- reusable session rotation, authoritative loader, cross-session phase, and
  assertion additions together add at most 420 physical lines before legacy
  delegation/removal, and total touched runtime net growth is at most 600;
- the application-session lifecycle has one implementation in
  `AutomationHarness`; no journey constructs `ApplicationComponents`;
- raw QTest for authoritative folder load/activation exists only in
  `ExperimentLoaderDriver`;
- authoritative loaded/activated/cross-session policy has one implementation
  consumed by both direct-oracle and composed tests;
- existing Slice 4 stop/resume phases and terminal policy are reused rather
  than copied;
- `registry.run_registered_scenario()` gains no scenario-ID conditional;
- no report-schema or production-MVC change is introduced.

Line limits are review gates, not permission to compress or obscure behavior.
If these gates cannot be met cleanly, stop and amend this plan before adding a
parallel runner.

## Exact Files To Touch During Implementation

Required runtime files:

- `tools/virtual_workflows/harness.py`
- `tools/virtual_workflows/actions.py`
- `tools/virtual_workflows/page_drivers.py`
- `tools/virtual_workflows/journey_phases.py`
- `tools/virtual_workflows/authoritative_evidence.py`
- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/scenarios.py`
- `tools/virtual_workflows/registry.py`
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`

Required focused tests:

- `tests/test_virtual_workflow_harness.py`
- `tests/test_virtual_workflow_actions.py`
- `tests/test_virtual_workflow_page_drivers.py`
- `tests/test_virtual_workflow_journey_phases.py`
- `tests/test_virtual_workflow_authoritative_evidence.py`
- `tests/test_virtual_workflow_assertions.py`
- `tests/test_virtual_workflow_composition.py`
- `tests/test_virtual_workflow_manifest.py`
- `tests/test_virtual_workflow_contract_freeze.py`
- `tests/system/test_virtual_workflow_authoritative_reload_lifecycle.py`
- new `tests/system/test_virtual_workflow_authoritative_reload_composed.py`

Required implementation documentation:

- `README.md`
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- this implementation plan, for status only
- new
  `docs/sil_interactive_simulation_milestone_7_slice_5_completion_record.md`

`tools/sil/session.py`, `tools/virtual_workflows/composition.py`,
`tools/virtual_workflows/report.py`, `tools/virtual_workflows/execution_observer.py`,
the fixture, production MVC, simulator response models, Pi scripts, firmware,
protocol, and hardware files are validation inputs but are not expected to
change. If implementation proves one necessary, stop and amend this plan
before editing it.

## Implementation Steps

1. **Freeze the direct oracle.** Retain one fixed-input legacy report and
   stable projections for fixture identity, two sessions, pause/quiescence,
   directory inventories, load/activation, completed/discarded/reissued
   intents, progress/I/O/audit, terminal state, assertions, screenshots,
   failure classification, and cleanup. Record the fixture hash before edits.
2. **Add reusable harness session rotation.** Extract the current contained
   create/launch/context-bind operation; add a clean first-session close and
   same-root reopen that uses the public `SimulationSession` API; track both
   application identities/recorder outcomes; and fail closed on dirty close,
   changed root/session identity, lock leakage, or second launch failure.
3. **Consolidate authoritative editor mechanics.** Extend
   `ExperimentLoaderDriver` with bounded paused-execution load and activation;
   require the exact editor, file dialog, action label, guidance/banner,
   eligibility, and runtime state; and make the legacy semantic action
   delegate instead of retaining its private QTest timer state machine.
4. **Add typed cross-session phases and evidence.** Generalize Slice 4
   milestone naming, capture immutable first-session bundle/directory and
   observer facts, restore session-scoped observers before close, rotate,
   validate byte-identical load and allowlisted activation, reconnect shared
   observers, restage the persisted head through existing drivers without
   recalibration, and invoke the existing resume phase.
5. **Consolidate read-only assertions.** Add one authoritative-reload
   expectation/projection producing the twelve frozen decisions, including
   clean first teardown, fresh second application, exact partial-runtime
   rehydration, no replay of first-session completed pairs, one resume,
   intent/durable-write reconciliation, and the existing terminal oracle.
   Adapt legacy validation to the same helpers while it remains the oracle.
6. **Compose and register the journey.** Add a concise fixture adapter, body,
   payload, summary, and `JourneyDefinition`; switch only this registry entry
   to existing generic `composed_journey` dispatch; retain the direct legacy
   callable for parity; and update manifest evidence/action metadata without
   adding capability claims.
7. **Run targeted success, parity, failure, visible, and replay gates.** Run
   only the selections below, then run one visible CLI journey and its exact
   emitted replay. Inspect both application recorder roots, all eight images,
   ledgers, hashes, report, manifest, failure evidence, and final lock state.
8. **Document and close Slice 5.** Update README commands/troubleshooting,
   roadmap status, measured code shape, exact results, retained evidence,
   risks, and rollback. Stop before planning or implementing post-start
   lock/copy.

## Focused Automated Gates

Use distinct temporary roots. If a Qt lifecycle node exceeds its internal
60-second scenario deadline or stops making progress materially beyond its
normal runtime, inspect and terminate only that confirmed process and rerun
the exact node separately; do not wait for an unrelated 15-minute outer
timeout.

Reusable session, driver, evidence, assertion, and contract tests:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice5-unit" `
  tests\test_simulation_session.py `
  tests\test_virtual_workflow_harness.py `
  tests\test_virtual_workflow_actions.py `
  tests\test_virtual_workflow_page_drivers.py `
  tests\test_virtual_workflow_journey_phases.py `
  tests\test_virtual_workflow_authoritative_evidence.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_composition.py `
  tests\test_virtual_workflow_report.py `
  tests\test_virtual_workflow_manifest.py `
  tests\test_virtual_workflow_contract_freeze.py
```

Production-adjacent load/resume contracts, with no production edits expected:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice5-adjacent" `
  tests\test_experiment_designer_interlock.py `
  tests\test_authoritative_execution_load.py `
  tests\test_authoritative_execution_runtime_cache.py `
  tests\test_execution_resume_store.py `
  tests\test_execution_lifecycle_hardening.py `
  tests\test_view_array_controls.py `
  tests\test_controller_experiment_audit.py
```

Composed success/parity/failure and focused journey regressions:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice5-lifecycle" `
  tests\system\test_virtual_workflow_authoritative_reload_composed.py `
  tests\system\test_virtual_workflow_authoritative_reload_lifecycle.py `
  tests\system\test_virtual_workflow_soft_stop_composed.py `
  tests\system\test_virtual_workflow_smoke.py
```

Also run:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py --help
.\env\Scripts\python.exe -m py_compile `
  tools\virtual_workflows\harness.py `
  tools\virtual_workflows\actions.py `
  tools\virtual_workflows\page_drivers.py `
  tools\virtual_workflows\journey_phases.py `
  tools\virtual_workflows\authoritative_evidence.py `
  tools\virtual_workflows\assertions.py `
  tools\virtual_workflows\journeys.py `
  tools\virtual_workflows\scenarios.py `
  tools\virtual_workflows\registry.py
git diff --check
git status --short
```

Do not run unscoped `pytest -q` in Slice 5. The complete Python suite remains
the final Milestone 7 validation gate.

## Success, Parity, And Controlled-Failure Gates

The composed success test must prove:

- hardware access disabled and real application controls used in both fresh
  application compositions;
- the same retained SIL session/root with two distinct application and state
  recorder identities, the first closed before the second opens;
- stop requested at completion 6, bounded one-to-two catch-up, valid paused
  empty checkpoint, `ready_to_resume`, and 250 ms quiescence;
- first-session cleanup passes, its recorder is healthy/closed, its files are
  unchanged by teardown, and no stale callback/timer/window remains;
- second-session load uses the exact folder dialog and `Load Execution`
  surface, remains runtime-inactive, preserves plan/design identity, and is
  byte-identical before activation;
- activation changes no non-allowlisted file, emits one activation audit,
  restores exact partial progress and `resume_ready`, and does not start work;
- the persisted matching calibration is reused, the correct head is staged,
  and resume occurs once through the exact `Resume Print Array` dialog;
- first-session completed stock/well pairs are not replayed; discarded
  lookahead is reissued; all 24 pairs complete exactly once with no ambiguous
  intent or unexplained write;
- terminal checkpoint is empty, plan is COMPLETED, authoritative bundle is
  valid, all twelve assertions pass, both recorder artifact sets and all
  report artifacts are non-empty, teardown passes, and no lock remains.

Stable direct/composed parity compares fixture identity, stop/catch-up,
paused checkpoint/quiescence, between-session inventory, loaded/activated
checks, partial-progress count, completed/discarded/reissued relationships,
progress mode counts, durable writes, audit subsequence, terminal state,
assertion decisions, classification, and limitations. It ignores only the
reviewed action-plumbing differences and generated identities/paths/times.

At minimum, inject (a) a first-session teardown mutation and (b) a disallowed
activation-time file mutation. Each must fail at its authoritative boundary,
mark later assertions incomplete, retain failure screenshot/trace/ledgers/
manifest and both available recorder artifacts, complete best-effort teardown,
and leave no session lock. Unit tests must also reject an unexpected editor or
file dialog, wrong `Load Execution` label, dirty first close, changed retained
session identity, and second-session construction failure.

## Visible And Replay Gate

Run once through the normal Windows UI:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario authoritative_reload_resume_24_v1 `
  --output-root verification_reports\milestone7-slice5-visible `
  --visible --seed 1 --speed-multiplier 2 --timeout-seconds 60
```

Inspect the report, ledgers, evidence manifest, event trace, `session.json`,
both state-recorder directories, authoritative experiment directory, and all
eight screenshots. Verify that the first window closes, a fresh window opens,
the saved execution is visibly loaded before activation, `Load Execution`
does not resume printing, and only the later `Resume Print` action resumes it.
Confirm hardware access remains disabled.

Then execute the exact `run.replay_command` emitted by that report into the
same output root. Require equal stable projection for fixture hash/seed,
application-session count/order, action IDs/multiplicity/surfaces/statuses,
dialog titles, assertion decisions, screenshot keys, persistence/lifecycle
relationships, classification, and cleanup. Ignore only documented generated
identities, paths, timestamps, durations, and identity-bearing hashes.

## Risks And Mitigations

- **Session rotation is mistaken for process restart:** report it explicitly
  as two fresh in-process application compositions sharing a QApplication and
  retained root; make no OS restart claim.
- **First-session state is mutated during close:** snapshot before close,
  require a clean recorder/application close, resnapshot the directory before
  reopening, and fail before activation on any difference.
- **Old observers leak into the new composition:** restore every registered
  session-one observer before close, construct new observers against only the
  fresh objects, and inject failures on both sides of the boundary.
- **Load silently activates or repairs:** assert runtime inactive and exact
  file identity before the `Load Execution` click; allow changes only after
  that explicit UI action and only from the frozen allowlist.
- **Resume replays completed work:** retain exact first-session completed pairs
  and intent IDs, compare them to second-session begins/completions, and fail
  on duplicate pairs, missing reissues, or ambiguous writes.
- **Calibration is accidentally regenerated:** require reuse of the persisted
  matching calibration and no second-session generate/apply action.
- **UI coverage is overstated:** freeze action surfaces and reject Model or
  Controller shortcuts in the composed source/ledger contract.
- **Windows Qt batching stalls:** retain the 60-second scenario deadline,
  separate temp roots, and isolate a stalled node promptly rather than waiting
  for a broad outer timeout.

## Rollback

Keep `run_virtual_print_array_scenario()` directly callable until all focused
parity and evidence gates pass. If migration fails, restore only the
`authoritative_reload_resume_24_v1` registry and manifest entry to
`virtual_print_array`; remove its composed definition, cross-session phase,
assertions, tests, and Slice 5 documentation; and restore the legacy editor
action if delegation caused the regression.

Retain independently passing generic harness rotation and page-driver helpers
only if their focused tests pass and no scenario selects them; otherwise
remove those additions too. Do not revert Slice 4, its accepted variance, the
fixture, existing composed journeys, production data, or unrelated Milestone
7 work. No firmware/protocol, production MVC, Pi, simulator-response, or
hardware rollback is required.

## Approval Gate

Do not implement this plan until the user approves it. Approval covers only
the exact scope, files, eight steps, code-shape gates, targeted-test policy,
visible/replay evidence, and rollback above. Any production MVC or
`SimulationSession` change, fixture or report-schema revision, second workflow
migration, active matrix, seeded exploration, fault injection, performance
work, Pi operation, firmware/protocol change, or hardware work requires an
amended plan and separate approval.
