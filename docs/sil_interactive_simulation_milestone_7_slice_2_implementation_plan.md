# Milestone 7 Slice 2 — Composed Two-Stock 24x2 Lifecycle

Status: `implemented — approved and completed on 2026-08-06`

Planning baseline: `04594f37966bc3e41b025004733f17a70094672b`.

## Scope

Migrate only `print_array_multi_stock_24x2_v1` from the monolithic
`run_virtual_print_array_scenario()` family to the Milestone 6/7 shared
automation harness. The composed journey will create the two-stock A1-A24
experiment through the normal Experiment Editor, prepare and calibrate each
matching virtual head through normal Qt controls, print two 24-well passes,
exchange heads through the rack UI between passes, and validate one durable
48-pair authoritative execution.

This slice does not migrate prepared edit/refinalize, soft stop/resume,
authoritative reload/resume, post-start lock/copy, 96-well regression, 384x10
stress, disconnect, mixed droplet/stream, or another workflow. It adds no
production fault-injection option, performance remediation, seeded sequence
exploration, Pi operation, firmware/protocol work, or hardware operation.

No file under `FreeRTOS-interface/` or `firmware/` is in scope. The application
SIL still makes no physical motion, pressure-response, collision-safety,
camera, balance, firmware, protocol, or droplet-quality claim.

## Initial Audit

- The worktree is clean at committed Slice 1 HEAD
  `04594f37966bc3e41b025004733f17a70094672b`.
- Milestone 7 is in progress, Slice 1 is complete, and the roadmap selects
  `print_array_multi_stock_24x2_v1` as migration item 3.
- The existing scenario and its two focused lifecycle tests pass through the
  legacy `virtual_print_array` runner family. Slice 2 implementation must keep
  that direct runner callable as a parity oracle.
- The Milestone 5 retained two-stock evidence named in its completion record is
  not present on this computer, so this plan does not claim to have inspected
  that root. The tracked completion record establishes that the manually
  qualified normal-UI recipe used 9 nL/1300 µs and 18 nL/1800 µs heads.

## Current Call Paths And Bypasses

### Registry and legacy runner

```text
tools/run_virtual_workflow.py
  -> registry.run_registered_scenario()
  -> runner_family == "virtual_print_array"
  -> scenarios.run_virtual_print_array_scenario()
  -> multi_stock_head_exchange branches inside the shared 4,000+ line runner
```

The legacy function owns temporary roots, QApplication/application
construction, instrumentation, fixture preparation, dialog handling, action
execution, pass orchestration, validation, screenshots, failure retention,
report-v1 assembly, and teardown. Its multi-stock branches duplicate the
session/report structure now owned by `AutomationHarness` and duplicate the
machine/editor/rack/calibration/array orchestration already composed by the
24-well smoke.

### Direct setup and state mutation in the current scenario

```text
fixture.prepare_authoritative
  -> _create_prepared_fixture()
  -> direct design/plan/progress writers

app.launch_simulated
  -> ExperimentModel.load_experiment()
  -> Model.load_authoritative_execution_runtime()

machine.connect_ready
  -> direct simulated connection/readiness setup

canned calibration loop
  -> printer_head.set_identity_metadata()/set_absolute_volume()
  -> ExperimentModel.apply_execution_calibration()

head.stage_virtual
  -> RackModel transfer/update methods
  -> Controller print pulse/pressure setters
```

Only `array.start_via_ui` currently exercises the main operator surface. The
legacy action ledger truthfully labels `machine.connect_ready` as `simulator`,
`head.stage_virtual` as `model`, and pressure setup as `controller`; it must not
be treated as normal-UI coverage.

### Current print path after setup

```text
Start Print Array button (QTest)
  -> MainWindow confirmation dialogs
  -> Controller.print_array()
  -> ExperimentModel pass preparation and durable intent writers
  -> SimulatedMachine command queue
  -> Controller completion callbacks
  -> authoritative progress/resume/plan writers
  -> idle stock-pass boundary
  -> repeat for second stock
```

There is no firmware handler in this SIL path. `SimulatedMachine` terminates
the application-facing communications path; no serial transport or physical
interface is constructed.

### Target composed path

```text
CLI / registry
  -> run_multi_stock_24x2_journey()
  -> AutomationHarness / SimulationSession
  -> MachineControlsDriver: connect, enable, home through QTest
  -> ExperimentEditorDriver: two reagent rows, A1-A24, Finalize through QTest
  -> bounded execution observer / prepared assertions
  -> for each stock in fixture order:
       MachineControlsDriver: pulse/pressure/frequency through QTest
       RackDriver: volume, Confirm, Load/Unload through QTest
       CalibrationDialogDriver: open/generate/select/Apply through QTest
       ArrayDriver: Start Print Array confirmations through QTest
       harness wait and read-only stock-pass assertion
  -> read-only terminal/durability/history assertions
  -> shared report/evidence/teardown finalization
```

The deterministic virtual head-ID binding needed by the fixture is explicit
test stimulus, recorded as a non-UI `model` action. It may set identity metadata
on the two newly generated virtual heads, but it may not set volume, rack
position, calibration, pressure, progress, pass state, or terminal state.

## Required Fixture Contract Revision

The existing schema-v3 recipe is not reproducible through the current normal
synthetic-calibration UI: it declares 10 nL at 1300 and 1500 µs, while the
versioned pulse-aware simulator deterministically produces 9 nL at 1300 µs
and 12.6 nL at 1500 µs. Preserving 10 nL by calling
`apply_execution_calibration()` directly would retain the bypass this migration
is intended to remove.

Therefore Slice 2 proposes an explicit schema-v4 revision of the same
well/pass workload, aligned with the manually qualified Milestone 5 recipe:

| Field | Stock 1 | Stock 2 |
|---|---:|---:|
| concentration | 3.0 x | 1.5 x |
| target concentration | 1.0 x | 1.0 x |
| prepared/effective volume | 9 nL | 18 nL |
| pulse width | 1300 µs | 1800 µs |
| pressure | 1.2 psi | 1.5 psi |
| target dispenses per A1-A24 well | 1 | 1 |

The printed and final reaction volume becomes 27 nL and the fill target remains
zero. Plate, A1-A24 order, two-stock/two-pass structure, 48 completions,
staging semantics, factor labels, deterministic head IDs, and scenario ID stay
unchanged. The loader and fixture tests must reject schema-v3 assumptions after
this revision. The legacy parity oracle runs the same tracked schema-v4 bytes;
pre-Slice-2 v3 fixture hashes and 10 nL canned-calibration values are an
explicitly reviewed non-parity boundary.

If this fixture revision is not acceptable, do not implement a direct
calibration workaround. Stop and create a separate decision covering a new
versioned scenario ID or a different normal-UI recipe.

## Frozen Design Decisions

1. **One registry cutover.** Only `print_array_multi_stock_24x2_v1` changes to
   `runner_family="composed_journey"`. All later roadmap scenarios remain on
   their current runners.
2. **Normal controls own operator behavior.** Experiment creation, connection,
   motor enable/home, print settings, volume entry, rack confirm/load/unload,
   pressure regulation, both calibration applications, and both array starts
   use bounded QTest interactions. No composed action may call the legacy
   fixture writer, direct runtime activation, canned calibration, or
   `stage_virtual_head()`.
3. **One page driver per surface.** Generalize `ExperimentEditorDriver` to a
   validated ordered reagent sequence, `RackDriver` to stock-aware slot lookup
   plus Confirm/Load/Unload, and `ArrayDriver` to an explicit expected dialog
   sequence. Do not add a multi-stock-specific page driver.
4. **Truthful non-UI stimulus.** Binding fixture head IDs is a typed `model`
   action and is excluded from UI coverage. Assertions, waits, snapshots,
   observer setup, report work, and teardown remain `harness` actions.
5. **Exact pass boundaries.** Pass 1 must settle `idle`, queue-drained, with 24
   completions, clean/empty intents, and plan `ACTIVE` before the head is
   returned. Pass 2 must settle with 48 completions and plan `COMPLETED`.
   Printing never continues while a head exchange is in progress.
6. **Durability remains assertion-backed.** A bounded reusable execution
   observer records begin/attach/complete/discard intent events, command
   sequence identity, progress-cache modes, authoritative I/O counts, pass
   starts, errors, starvation, and bounded simulator histories. Assertions are
   read-only and never repair or advance state.
7. **Report-v1 compatibility.** Preserve scenario/workload/version identity,
   all eleven assertion IDs, the six legacy stock milestones, and
   `metrics.persistence.values.multi_stock_head_exchange`. Add the composed
   seed/replay/session roots, modern ledgers, evidence manifest, and the
   automatic `editor_opened`/`generated` screenshots. Generated UUIDs,
   timestamps, durations, paths, and identity-bearing hashes are not parity
   fields.
8. **Targeted validation only.** Run directly affected unit/system tests,
   Slice 1 and Milestone 6 regressions, one visible Windows run, and its exact
   replay command. Do not run the full Python suite until the final Milestone 7
   validation.

## Required Parity Contract

The legacy oracle and composed run, both using the schema-v4 fixture, must
agree on:

- scenario name/version, workload ID, fixture SHA-256, A1-A24 order, two
  stocks, two passes, and 48 expected completions;
- all eleven required assertion IDs and `pass` decisions;
- deterministic stock IDs and head IDs, 9/18 nL calibrations, 1300/1800 µs
  pulses, and 1.2/1.5 psi settings;
- two start events, pass terminal states `["active", "completed"]`, and 24 +
  24 well updates in fixture order;
- a clean and empty intent checkpoint at each pass boundary;
- 48 unique begin/attach/complete intent lifecycles, 48 unique command
  sequences, no discard batch, no replay, and exact terminal progress;
- no unexpected dialogs, controller/simulator errors, queue starvation, or
  unbounded retained histories;
- terminal plan `COMPLETED`, queue drained, two applied calibration records,
  no fill calibration, and no outstanding resume intents;
- the six legacy stock milestones plus composed editor screenshots, nonempty
  ledgers/evidence hashes, healthy recorder closure, and no session lock.

The action order intentionally differs because direct setup actions are
replaced by normal UI actions. The composed run must contain exactly two
settings, volume, stage, calibration, and array-start groups, two UI returns
to the rack, and one between-pass exchange. The first array start handles
`Start Print Array` plus `Evaporation Plate Dock Check`; the second handles
only `Start Print Array`.

## Implementation Steps

1. Revise the tracked multi-stock fixture to schema v4 and freeze its exact
   9/18 nL UI-reproducible recipe, registry identity, legacy oracle, report-v1,
   action count/surface, assertion, and parity contracts in targeted tests.
2. Add a bounded reusable execution observer for intent lifecycle, progress
   cache, authoritative I/O, pass, starvation, error, and history evidence;
   integrate it with harness close so restoration is attempted after failures.
3. Generalize existing editor, rack, array, and typed semantic actions for an
   ordered reagent list, stock-aware slot operations, UI head return, repeated
   per-stock settings/calibration/start groups, and explicit model-surface head
   identity binding while preserving one-stock behavior.
4. Add reusable read-only multi-stock assertions for prepared two-stock
   targets, exact applied calibrations/settings, safe head exchange, pass
   boundaries, completions, durability, starvation, bounded histories,
   terminal persistence, required artifacts, and cleanup.
5. Extract the common composed report envelope/finalization into a typed
   report adapter used by smoke, editor, and multi-stock journeys; retain each
   scenario's workload/metrics payload and prove no Slice 1 or smoke drift.
6. Add the short two-pass composition and dispatch only
   `print_array_multi_stock_24x2_v1` to it. Update its manifest actions to
   truthful surfaces and keep all seven capability claims only when the same
   eleven assertions pass.
7. Add composed success, schema-v4 legacy parity, and controlled unexpected
   between-pass-dialog failure tests. Prove downstream assertions become
   `incomplete`, failure evidence is retained, observer hooks are restored,
   the recorder closes, and teardown removes the session lock.
8. Run the targeted, visible, and exact-replay gates below; inspect both
   reports/session roots, update README/roadmap, and write the Slice 2
   completion record. Do not run the full suite.

## Exact Implementation File Set

New files:

- `tools/virtual_workflows/execution_observer.py`
- `tests/test_virtual_workflow_execution_observer.py`
- `tests/test_virtual_workflow_report.py`
- `tests/system/test_virtual_workflow_multi_stock_composed.py`
- `docs/sil_interactive_simulation_milestone_7_slice_2_completion_record.md`

Modified files:

- `tools/virtual_workflows/fixtures/print_array_multi_stock_24x2_v1.json`
- `tools/virtual_workflows/scenarios.py`
- `tools/virtual_workflows/actions.py`
- `tools/virtual_workflows/page_drivers.py`
- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/registry.py`
- `tools/virtual_workflows/report.py`
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`
- `tests/test_virtual_workflow_page_drivers.py`
- `tests/test_virtual_workflow_actions.py`
- `tests/test_virtual_workflow_assertions.py`
- `tests/test_virtual_workflow_manifest.py`
- `tests/test_virtual_workflow_contract_freeze.py`
- `tests/system/test_virtual_workflow_multi_stock_lifecycle.py`
- `README.md`
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- this plan

The legacy runner remains unchanged except for accepting/validating the tracked
schema-v4 fixture and any minimal shared report/observer adapter needed for
parity. Its multi-stock branch is not deleted in this slice because it remains
the oracle. Do not modify another workflow fixture, production MVC, simulation
response model/profile/schema, Pi tooling, performance/baseline tooling,
firmware, protocol, or hardware code.

## Targeted Automated Gates

Run the shared harness/driver/action/assertion/report contracts:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_simulation_session.py `
  tests\test_virtual_workflow_harness.py `
  tests\test_virtual_workflow_page_drivers.py `
  tests\test_virtual_workflow_actions.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_execution_observer.py `
  tests\test_virtual_workflow_manifest.py `
  tests\test_virtual_workflow_contract_freeze.py `
  tests\test_virtual_workflow_report.py
```

Run focused editor/calibration/authoritative integration contracts affected by
the schema-v4 recipe and two-stock UI path:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_sil_calibration_application.py `
  tests\test_sil_normal_ui_convergence.py `
  tests\test_initial_execution_plan_integration.py `
  tests\test_execution_progress_store.py `
  tests\test_execution_resume_store.py
```

Run the composed scenario, revised-fixture legacy oracle, normal-UI calibration
adjacency, and controlled failure cases:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_multi_stock_composed.py `
  tests\system\test_virtual_workflow_multi_stock_lifecycle.py `
  tests\system\test_sil_normal_ui_convergence_lifecycle.py
```

Run the existing composed-journey regressions:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_smoke.py `
  tests\system\test_virtual_workflow_editor_composed.py
```

Also run:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py --help
.\env\Scripts\python.exe -m py_compile `
  tools\virtual_workflows\execution_observer.py `
  tools\virtual_workflows\actions.py `
  tools\virtual_workflows\page_drivers.py `
  tools\virtual_workflows\assertions.py `
  tools\virtual_workflows\journeys.py `
  tools\virtual_workflows\registry.py `
  tools\virtual_workflows\report.py
git diff --check
git status --short
```

Do **not** run `.\env\Scripts\python.exe -m pytest -q` without targeted paths
in this slice. Record the cumulative full-suite gate as deferred to the end of
Milestone 7.

## Visible And Replay Gates

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario print_array_multi_stock_24x2_v1 `
  --output-root verification_reports\milestone7-slice2-visible `
  --visible --seed 1 --speed-multiplier 2 --timeout-seconds 300
```

The visible run passes only when the normal UI creates the A1-A24 two-reagent
design, calibrates the exact loaded stock at 9 nL then 18 nL, completes pass 1
as `ACTIVE`, returns the first head and loads the second through rack controls
while idle/drained, completes pass 2 as `COMPLETED`, returns the final head,
passes all eleven assertions, and closes with a healthy recorder and no lock.

Run the exact `run.replay_command` emitted by that report. Compare the stable
parity fields above, inspect both evidence manifests and terminal snapshots,
and record any generated-identity differences rather than normalizing state to
make them match.

## Short Manual Checklist

- The persistent banner reads `SIMULATION — NO HARDWARE`; no production port
  control is enabled.
- The editor visibly contains two ordered reagent rows and A1-A24 only.
- The rack visibly returns head 1 before loading head 2; no exchange happens
  while the array is running or the simulator queue is nonempty.
- Calibration presentation identifies the currently loaded head/stock and
  shows 9 nL/1300 µs for stock 1 and 18 nL/1800 µs for stock 2.
- The first pass ends `ACTIVE` at 24 completions; the second ends `COMPLETED`
  at 48; no well receives either stock twice.
- Closing the application removes `.sil-session.lock` and retains the report,
  ledgers, screenshots, snapshots, failure trace when applicable, and evidence
  manifest.

## Risks And Mitigations

- **Reviewed fixture change:** schema v4 changes concentrations, calibrated
  volumes, one pulse, and fixture hash. Freeze the exact diff and compare both
  runners only on v4; never describe pre-Slice-2 v3 evidence as byte-parity.
- **Two-reagent editor ordering:** validate row count/order, generated stock
  IDs, A1-A24 assignments, zero fill, and one target per stock before any
  calibration or printing.
- **Wrong-stock calibration context:** require the calibration candidate,
  preview, applied record, active rack head, and execution stock ID to agree at
  both passes. Fail before Apply on missing, duplicate, or ambiguous identity.
- **Unsafe/racy rack exchange:** Unload/Load actions require `idle`, drained
  queue, known origin/destination slots, visible enabled controls, and a
  post-action identity check. Do not fall back to RackModel transfers.
- **Premature terminal transition:** assert plan `ACTIVE` after pass 1 and
  `COMPLETED` only after pass 2, with 24/48 exact progress boundaries.
- **Observer-induced behavior:** keep the observer bounded and restorative,
  test success/failure uninstallation, and compare authoritative files and
  command ordering against the legacy oracle.
- **Report refactor drift:** run smoke and Slice 1 composed reports as mandatory
  targeted regressions and preserve their exact required fields/actions.
- **No per-slice full suite:** keep this migration reversible and require the
  complete Python suite before Milestone 7 is declared complete.

## Rollback

Restore `print_array_multi_stock_24x2_v1` to
`runner_family="virtual_print_array"`, restore the schema-v3 fixture and its
manifest/test contract, and remove only the composed multi-stock journey,
observer, UI exchange action, and assertions that have no other consumer.
Keep the Milestone 6 smoke, Slice 1 editor journey, all later legacy scenarios,
and the versioned synthetic response model intact.

No production experiment migration, authoritative-schema rollback, retained
evidence deletion, firmware/protocol rollback, Pi change, or hardware action is
required. Retained success/failure roots may remain for inspection.

## Approval Gate

This plan was approved and implemented, including the schema-v4 fixture
revision. Its approval covered only this one
scenario, the files above, eight implementation steps, targeted-test policy,
and visible/replay gates. Any alternative fixture strategy, additional
workflow migration, production seam, fault injection, performance work,
seeded exploration, Pi operation, firmware/protocol change, or hardware work
requires a separate decision.
