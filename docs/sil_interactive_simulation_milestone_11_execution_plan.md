# Milestone 11 Execution Plan: Randomized Design, Calibration, Reload, and Execution

Status: complete (2026-08-08; all five slices and final qualification complete)

Prepared: 2026-08-08

This is an implementation plan, not an implementation record. Preparing it did
not run a SIL journey, change production behavior, or authorize firmware,
protocol, hardware, motion, pressure, or physical-calibration work. Each slice
must receive its own implementation plan, focused validation, completion
record, and independent commit before the next slice begins. A production
defect stops the active slice and requires a separate reviewed correction plan.

## Verified entrance baseline

All Milestone 11 prerequisites were satisfied before this plan was written:

- Milestone 10 is recorded complete in
  `docs/sil_interactive_simulation_milestone_10_execution_plan.md`, the master
  plan, and
  `docs/sil_interactive_simulation_milestone_10_slice_6_completion_record.md`.
- The six Milestone 10 Slice 10.6 aggregate files recorded by the completion
  record exist and match their recorded SHA-256 values. The default Python
  qualification is recorded as `4146 passed, 88 skipped`.
- The master plan identifies Milestone 11 as the current next action.
- The expected Milestone 9 commits `19faf52`, `56c89d1`, `de002a9`,
  `5ad5f70`, `d2e3a96`, `792a7b0`, and `a10a63f`, and the expected Milestone
  10 commits `2bc8055`, `74657bc`, `fa6ed5c`, `649b4a5`, `6c05b80`,
  `b68d17a`, `6e3900e`, `a373433`, and `ea4c788`, are ancestors of `HEAD`.
- The planning baseline is `ea4c788` on
  `feature/general_bug_fix_1`, equal to its remote-tracking tip, with a clean
  worktree before these two planning-document edits.
- All eight Milestone 9 aggregate files recorded by Slice 9.6 exist and match
  their recorded SHA-256 values. The independently reviewed cross-session
  lifecycle-evidence correction is present in commit `792a7b0` and its plan
  and completion record remain available.
- The focused, non-SIL stability check passed with `44 passed` for
  `test_virtual_workflow_dispense_counts.py`,
  `test_virtual_workflow_experiment_design_cases.py`, and
  `test_virtual_workflow_matrices.py`.

The frozen entrance identities are:

- `calibration_requantization_v1` catalog SHA-256
  `d826a9e54c2e6190acfd5afdb0b2475de2be62557647aafa378890ca826c55af`;
- `mixed_mode_calibration_v1` catalog SHA-256
  `d2439c2e47cb9825ad5a5024e014fd4429ff6b28dcafa54809c92fa674cff884`;
- `experiment_design_pairwise_v1` catalog SHA-256
  `acbd4d82f8c7ea6dd842c4ad88bd472c4b50f3a73822dc8c34cfded0dec6f59f`;
- selected Milestone 10 case `multi_reagent_seed_4321` SHA-256
  `5d2e7dff0ea9c2e0bcd1e3b218b39280aca57b745834024226fece850f110f51`;
- selected reaction-multiset SHA-256
  `b189fe1ed4b975953600c7d299fd320be366eda827ceb39f28cf3a3bbc22b696`;
- selected assignment SHA-256
  `e264b345bddb83c2aeb12bf6421d83a81d21c8b9f31ff6698780164a1bee82ef`;
- unchanged editor reference-fixture SHA-256
  `fc2bdf34fa5a7d8a9e851ace7a099aa8e05c61c2d0cd075b620d69937f8bfc45`;
- report-v1, selection-plan-v1, matrix-plan-v1, and aggregate-v1 remain the
  current schemas.

The Milestone 9 observed-count path is stable through `StockWellCount`,
`normalize_stock_well_counts()`, `plan_target_counts()`,
`decoded_progress_counts()`, `runtime_target_counts()`, and
`intent_and_simulator_counts()`. Milestone 11 may use those contracts only to
normalize or join observed values. The joined case validates and freezes its
expected tuple independently; comparison is the normalized observed tuple
against that already-canonical literal tuple. Every expected design,
assignment, stock, count, revision, and identity value below is literal
joined-case data and must not be generated with production optimization,
assignment, calibration, requantization, or reconstruction code.

## Scope and non-goals

Milestone 11 adds one typed joined-interaction scenario. It is not a matrix and
does not add design or calibration variants. The scenario creates the selected
randomized design through the real editor, applies one boundary-crossing
calibration, rotates to a genuinely fresh application session at zero progress,
reloads and explicitly activates authoritative execution, calibrates the
remaining stocks, executes all three stock passes, reconciles exact durable
intent and simulator evidence, and reloads the terminal bundle in a third
fresh application session.

The following are non-goals for every slice:

- no assumed production MVC change or refactor;
- no extension of production two-stock calibration Apply behavior;
- no new matrix, extra scenario case, generated exploration, or Milestone 12
  safeguard catalog;
- no refill-required/resume behavior while authoritative volume tracking is
  disabled;
- no changes to firmware, protocol, serial transport, physical-machine
  behavior, motion, pressure control, persisted application-data formats, or
  release metadata;
- no physical hardware, Pi, `pi_stress`, camera, balance, or droplet-quality
  claim;
- no full lifecycle suite, host regression, complete Python suite, or final
  visible qualification before Slice 11.5 unless a documented failure triage
  requires a narrower reproduction.

## Existing call paths and ownership

### Scenario selection, fresh process, and composed journey

```text
tools/run_virtual_workflow.py --scenario randomized_calibration_reload_execution_v1
-> registry.get_registered_scenario()
-> registry.run_registered_scenario()
-> journeys.run_composed_journey()
-> JourneyDefinition and JourneyExecutor
-> one retained report-v1 tree and exact replay command

tools/run_virtual_workflow.py --suite lifecycle
-> selection.resolve_selection_plan()
-> suite_runner.execute_selection()
-> fresh child process for the registered Milestone 11 scenario
-> the same composed journey and report-v1 contract
-> aggregate-v1 and exact aggregate replay
```

A direct CLI invocation is itself a fresh operating-system process. Suite
qualification additionally proves the existing parent/fresh-child contract.
Unknown scenario identity, source drift, missing or ambiguous report
selection, timeout, child failure, report/process disagreement, or replay
drift continues to fail closed.

### Real editor to authoritative design and execution files

The repository does not route experiment authoring through a Controller
method. The exact path that must remain unchanged is:

```text
joined case and real Qt editor driver
-> ExperimentDesignDialog updates ExperimentModel inputs
-> Optimize & Generate
-> ExperimentModel.optimize_stock_solutions()
-> ExperimentModel.generate_experiment()
-> Finalize Design
-> MainWindow.complete_experiment_design()
-> Model.load_experiment_from_model(finalize_execution_plan=True)
-> experiment_design.json
-> execution_plan.json and execution_plan_revisions/
-> progress.json, key.csv, and concentration_key.csv
```

The plan must not add a Controller pass-through merely to make this path look
like a conventional MVC chain. The Controller becomes authoritative for
machine settings and execution after the design has been finalized.

### Deterministic assignment and authoritative mapping

```text
case-owned randomization flag and design seed 4321
-> ExperimentModel.generate_experiment()
-> saved experiment_design.json reaction definitions
-> saved execution_plan.json well/reaction assignments
-> _project_reconstructed_execution_plan()
-> exact case-owned reaction-to-well comparison after every reload
```

Randomization may change only the well assignment. All joins use explicit
`reaction_id`, `stock_id`, and `well_id`; no assertion may use table row,
dictionary iteration, stock-list position, or pass position as identity.

### Calibration, plan requantization, and head linkage

The real UI path is bifurcated and must be documented accurately:

```text
CalibrationDialogDriver QTest interaction
-> DropletImagingDialog Apply
-> ExperimentModel.apply_droplet_volume_for_option() or
   ExperimentModel.apply_fill_droplet_volume()
-> ExperimentModel.lock_execution_plan("calibration_started")
-> ExperimentModel.apply_execution_calibration()
-> _calibrated_target_counts()
-> immutable calibrated execution-plan revision
-> execution_calibration.json record
-> stock.calibration_record_key and stock.printer_head_id
-> progress/resume reference synchronization

then, for applied pulse/pressure settings only:
DropletImagingDialog._apply_print_settings_for_applied_calibration()
-> Controller.apply_applied_imaging_calibration_print_settings()
-> Controller machine-setting methods
```

Milestone 11 exercises both real paths but does not change either. The first
successful calibration locks revision 1 as revision 2 and writes the calibrated
Design A revision as revision 3. Later stock calibrations each add one revision.

### Calibrated zero-progress shutdown and clean reload

```text
revision-3 ACTIVE bundle with all added counts zero
-> capture_authoritative_bundle() and exact zero-progress assertion
-> restore first ExecutionObserver hooks
-> AutomationHarness.close_application_session()
-> SimulationSession.close()
-> recorder closed, no session lock, retained root unchanged
-> AutomationHarness.reopen_application_session()
-> new SimulationSession and application_session_id
```

The existing `run_authoritative_reload_resume_boundary()` cannot express this
boundary safely: it always requests a soft stop, requires paused/quiescence
evidence and completed-pair accounting, restages a resume head, and resumes an
already-started array. Adding scenario-specific zero-progress branches would
mix two distinct lifecycle contracts. Slice 11.3 should therefore add a small
reusable `run_clean_authoritative_session_rotation_boundary()` phase. It owns
only observer restoration, clean close, file comparison, fresh launch,
session-identity assertions, fresh observer installation, authoritative load,
and explicit activation. It must not contain pause, resume, completed-pair, or
scenario-specific count logic.

### Fresh authoritative reconstruction and activation

```text
fresh SimulationSession
-> ExperimentLoaderDriver opens Experiment Editor
-> Qt folder dialog selects the retained authoritative directory
-> ExperimentDesignDialog._on_load_design()
-> ExperimentModel.load_experiment()
-> persisted execution is analysis-only and runtime inactive
-> literal case-to-plan-to-reconstructed identity/count assertions
-> Load Execution / explicit activation through Qt
-> ExperimentModel.load_authoritative_execution_runtime()
-> ACTIVE runtime reconstructed from authoritative files
```

Load and pre-activation inspection must write no authoritative file. Explicit
activation may create the clean `execution_resume.json` checkpoint and may
touch only the existing allowlist (`execution_resume.json`,
`execution_plan.json`, `key.csv`, `concentration_key.csv`, and
`experiment_audit.jsonl`). It must retain plan/design/count identity, record
exactly one activation audit event, reject any other write, and must not reuse
the first session's model, controller, observer, dialog, or assertion success.

### Remaining calibrations and all stock-pass execution

```text
fresh active runtime
-> real fill calibration Apply, then real Design B calibration Apply
-> explicit case-owned stock IDs and head IDs
-> revision-5 plan/progress/runtime reconciliation
-> case-owned pass order by stock ID
-> normal Qt Start Array action
-> Controller authoritative preflight and prepare_authoritative_print_pass()
-> Controller._queue_next_array_well()
-> ExperimentModel.begin_execution_print_intent()
-> Machine_FreeRTOS.print_droplets()
-> SimulatedMachine DISPENSE command
-> command completion callback
-> Controller._handle_array_well_complete()
-> durable intent completion and persisted progress
```

The pass order is explicit scenario data, never inferred from the plan stock
list. Volume tracking stays disabled, so no refill-required branch is admitted.

### Terminal completion and terminal reload

```text
all 24 stock/well intents durably complete
-> Controller._finish_array_finalize("completed")
-> ExperimentModel.try_complete_execution_plan()
-> immutable COMPLETED revision 6
-> clean progress and resume references at revision 6
-> close session 2 and open fresh session 3
-> real Qt authoritative load without activation
-> COMPLETED / analysis_only reconstruction
-> exact target == added == intent == simulator reconciliation
```

The combined lifecycle must contain exactly 24 begins, attachments,
completions, and non-manual completed `DISPENSE` commands, all attributed to
application session 2. Sessions 1 and 3 must contribute zero execution
commands. Every `(stock_id, well_id)` pair appears once and only once.

## Selected joined case and literal oracle

### Identity and policy

- Scenario/workload/fixture ID:
  `randomized_calibration_reload_execution_v1`.
- Scenario name: `randomized_calibration_reload_execution`.
- Capability ID: `execution.randomized_calibration_reload_execution`.
- Tier and suite: Windows-host `lifecycle`; add the single scenario to the
  existing lifecycle suite only when the complete journey is registered in
  Slice 11.4. Historical Milestone 9 and 10 selection hashes remain records of
  their source versions; no historical artifact is rewritten.
- Simulation seed: CLI seed `1`.
- Design randomization seed: literal `4321`.
- Action cap: at most `96` completed or failed action-ledger entries, including
  all three launches and final teardown. Hitting the cap fails the journey.
- Timeout: `180` seconds for focused/offscreen direct and suite children, plus
  the existing suite-runner 60-second parent grace and 5-second termination
  grace. Visible qualification uses `240` seconds at 20x. A timeout may be
  increased only after retained liveness evidence proves continued progress.
- Simulator retention: preserve the existing 10,000-command bound and require
  overflow count zero; this scenario needs exactly 24 retained dispenses.
- Exact replay: execute the emitted replay list without reconstruction. It
  must preserve scenario/workload ID, CLI seed, case SHA-256, source identity,
  speed, Qt/visible choice, timeout, output containment, and required evidence.

Use `multi_reagent_seed_4321`, not the seed-1234 comparison. Seed 4321 already
has visible qualification, is the first qualified multi-reagent randomized
case, and avoids adding a second design variant. The joined contract carries
the Milestone 10 case, reaction-multiset, and assignment hashes above. Slice
11.1 freezes a separate normalized joined-case SHA-256 and tracked fixture
SHA-256; these new values must be recorded in its completion record and remain
unchanged thereafter. They must not replace or recalculate a Milestone 9 or 10
hash.

### Literal reaction-to-well mapping

| Well | Reaction | Design A target | Design B target |
| --- | --- | ---: | ---: |
| `A1` | `R8` | 2 x | 3 x |
| `A2` | `R6` | 1 x | 3 x |
| `A3` | `R3` | 2 x | 1 x |
| `A4` | `R2` | 1 x | 3 x |
| `A5` | `R7` | 2 x | 1 x |
| `A6` | `R4` | 2 x | 3 x |
| `A7` | `R1` | 1 x | 1 x |
| `A8` | `R5` | 1 x | 1 x |

### Calibration choices and identity joins

`Design A_10.00_x` is the calibrated single-stock reagent. Apply the qualified
version-1 synthetic droplet response at 1800 us / 18 nL through the real
calibration dialog, using printer head
`virtual-head-m11-design-a-v1`. This is the boundary-crossing step: the four
2-drop Design A wells become 1-drop wells; the four 1-drop wells remain 1.
Design B remains byte-for-byte and count-for-count unchanged at this boundary.
Slice 11.2 real-Qt evidence corrected the provisional dependent-fill oracle:
Design A Apply requantizes Water to the literal 56-drop vector below while
preserving every Design B count. This correction changes only case-owned test
truth; it does not change production behavior.

After clean reload and explicit activation, calibrate the remaining stocks in
this order to avoid an intermediate half-tie:

1. `Water_1.00_--` at 1300 us / 9 nL with
   `virtual-head-m11-water-v1`;
2. `Design B_10.00_x` at 1400 us / 10.8 nL with
   `virtual-head-m11-design-b-v1`.

Then execute the explicit pass order `Design A_10.00_x`,
`Design B_10.00_x`, `Water_1.00_--`. Calibration and pass lookup must always
use the stock ID. The joined case owns the expected factor/option/fill identity,
printer-head ID, applied volume, pulse width, pressure, and printing mode for
each step. Generated calibration record IDs remain deterministic application
records rather than invented planning literals; assertions must join each
observed record ID simultaneously to `execution_calibration.json`, the matching
plan stock's `calibration_record_key`, the same plan stock's printer-head ID,
and the applied UI evidence.

The literal revision/reference chain is:

| Checkpoint | State | Plan revision | Required progress and resume reference |
| --- | --- | ---: | --- |
| prepared | `prepared` | 1 | progress: plan ID / revision 1; resume absent |
| calibration lock | `active` | 2 | progress: plan ID / revision 2; resume absent |
| Design A calibrated, zero progress | `active` | 3 | progress: plan ID / revision 3; resume absent |
| fresh load before activation | analysis-only persisted revision 3 | 3 | progress: plan ID / revision 3; resume absent; eligibility `ready_to_start` |
| fresh explicit activation | `active` | 3 | progress and new clean resume: plan ID / revision 3 |
| Water calibrated | `active` | 4 | plan ID / revision 4 |
| Design B calibrated / execution target | `active` | 5 | plan ID / revision 5 |
| terminal | `completed` | 6 | plan ID / revision 6, clean/no pending intent |
| fresh terminal reload | `completed`, `analysis_only` | 6 | plan ID / revision 6 |

Every row must retain the same plan ID and design SHA-256. Revisions 1-6 are
append-only and contiguous. The first calibration produces two revisions by
the existing lock-then-calibrate contract; later calibration and terminal
transitions produce one each. No execution pass may add a head-binding revision
because its stock must already carry the exact calibrated head ID.

### Literal stock/well count oracle

Each tuple is `(Design A_10.00_x, Design B_10.00_x, Water_1.00_--)`. These are
case-owned literals. Implementation tests may validate their shape and hash,
but may not derive them by calling production requantization code.

| Well / reaction | Prepared revision 1 | Design A 18 nL, revision 3 | Water 9 nL, revision 4 | Final after Design B 10.8 nL, revision 5 |
| --- | --- | --- | --- | --- |
| `A1 / R8` | `(2, 3, 6)` | `(1, 3, 6)` | `(1, 3, 6)` | `(1, 3, 6)` |
| `A2 / R6` | `(1, 3, 7)` | `(1, 3, 6)` | `(1, 3, 6)` | `(1, 3, 6)` |
| `A3 / R3` | `(2, 1, 8)` | `(1, 1, 8)` | `(1, 1, 8)` | `(1, 1, 8)` |
| `A4 / R2` | `(1, 3, 7)` | `(1, 3, 6)` | `(1, 3, 6)` | `(1, 3, 6)` |
| `A5 / R7` | `(2, 1, 8)` | `(1, 1, 8)` | `(1, 1, 8)` | `(1, 1, 8)` |
| `A6 / R4` | `(2, 3, 6)` | `(1, 3, 6)` | `(1, 3, 6)` | `(1, 3, 6)` |
| `A7 / R1` | `(1, 1, 9)` | `(1, 1, 8)` | `(1, 1, 8)` | `(1, 1, 8)` |
| `A8 / R5` | `(1, 1, 9)` | `(1, 1, 8)` | `(1, 1, 8)` | `(1, 1, 8)` |

The exact unchanged-other-reagent oracle is therefore:

```text
Design B_10.00_x:
A1=3, A2=3, A3=1, A4=3, A5=1, A6=3, A7=1, A8=1
```

Design B must match this map before and after Design A Apply, after reload,
after its own 10.8 nL calibration, at runtime, in intent/simulator evidence, and
at terminal reload. Its calibration changes only its record/head/effective
volume linkage; it does not change these counts.

The final execution oracle contains 24 positive stock/well intents and 80
commanded droplets:

- Design A: 8 intents and 8 droplets;
- Design B: 8 intents and 16 droplets;
- Water: 8 intents and 56 droplets.

Session 1 has zero intents/commands/progress, session 2 has all 24 exactly
once, and session 3 has zero. Terminal targets and added counts equal the
revision-5 final map; the revision-6 plan changes lifecycle state and references
but not target counts.

The 10-to-18 calibration necessarily has a narrower unchanged-one-drop
rounding margin than the isolated Milestone 9 base cases. That is accepted only
as a literal joined-case input backed by exact observed-layer reconciliation;
it does not weaken or redefine Milestone 9's frozen minimum-margin cases. Any
production result that differs from the literal table is a defect signal, not
permission to rewrite the oracle.

## Compatibility freeze for all slices

The following remain unchanged unless a separate correction plan is approved:

- all Milestone 9 and 10 case payloads, case hashes, catalog order and hashes,
  matrix registrations, reference-fixture bytes, and retained reports;
- report-v1, selection-plan-v1, aggregate-v1, matrix-plan-v1, matrix-
  aggregate-v1, evidence-manifest-v1, calibration schema, design schema,
  execution-plan schema, progress schema, and resume schema;
- CLI selectors, fresh-child process isolation, source fingerprinting,
  aggregate validation, exact replay, and report selection;
- real editor selectors and driver behavior, authoritative reload/activation
  contracts, negative finalization no-mutation evidence, and calibration Apply
  behavior;
- `StockWellCount` ordering by `(stock_id, well_id)` and fail-closed duplicate
  rejection;
- `merge_session_lifecycles()` bounded metadata validation and explicit
  application-session attribution;
- Controller/Machine_FreeRTOS protocol behavior and SimulatedMachine command
  semantics;
- hardware isolation, cleanup, recorder closure, and session-root containment.

## Slice 11.1: Joined contract, literal oracle, and compatibility freeze

### Objective and explicit non-goals

Add the typed singleton joined-case contract, literal values above, independent
validation, and frozen hashes. Do not register an executable scenario yet;
the registry requires an active scenario to have a real journey and tests, so
a placeholder would weaken fail-closed capability evidence. Do not add UI,
calibration, reload, execution, or production changes.

### Exact call path

```text
tracked singleton fixture / typed JoinedInteractionCase
-> strict normalized validation
-> literal design, assignment, calibration, count, revision, and pass data
-> deterministic case SHA-256 and fixture SHA-256
-> test-local JourneyDefinition/registry compatibility validation only
```

### Entrance prerequisites and exit criteria

Entrance: the verified baseline above is clean and all recorded hashes match.
Exit: the singleton contract rejects missing, extra, reordered-by-position,
duplicate, nonliteral, inconsistent, or half-specified identity/count data;
the new hashes are recorded; all entrance hashes remain unchanged; no runtime
selector exposes an incomplete scenario.

### Contracts, identity, hashes, and evidence introduced

- `JoinedInteractionCase` (or equivalently named frozen type), singleton case
  ID equal to the scenario ID, source Milestone 10 case/hash joins, exact
  reaction mapping, calibration steps, head IDs, revision chain, per-checkpoint
  counts, pass order, action cap, timeout, screenshot names, and terminal
  cardinalities;
- one fixture derived from or validated against the unchanged editor reference;
- frozen joined-case SHA-256, fixture SHA-256, and normalized count-oracle
  SHA-256, recorded in tests and the Slice 11.1 completion record;
- named compatibility audit proving every listed Milestone 9/10 hash is still
  exact.

### Initial files expected to change

- add `tools/virtual_workflows/joined_interaction_cases.py`;
- add `tools/virtual_workflows/fixtures/randomized_calibration_reload_execution_v1.json`;
- add `tests/test_virtual_workflow_joined_interaction_cases.py`;
- `tests/test_virtual_workflow_contract_freeze.py`;
- add Slice 11.1 implementation plan and completion record;
- update only the Milestone 11 current-action text in the master plan.

### Focused tests and SIL checks

Run the new case tests plus experiment-design, matrix, count-normalizer, fixture,
manifest/registry test-local, and contract-freeze tests. Include mutations for
wrong seed/mapping/hash, wrong stock or well, duplicate pair, changed unchanged-
Design-B row, revision gap, wrong head join, pass-position lookup, action cap,
 and total 24/80 drift. No offscreen or visible SIL run is authorized.

### Retained evidence and replay

Retain the focused pytest output and normalized payload/hash audit in the
completion record. There is no accepted report or replay until a complete
scenario exists; explicitly record replay as deferred, not missing.

### Commit boundary

One commit: `test: define randomized calibration lifecycle contract`.

### Risks and rollback

Risks are duplicating Milestone 10 truth inconsistently and accidentally
calculating expected counts with production code. Require literal equality to
the source case and reject callable/generated expected data. Rollback removes
only the singleton contract, fixture, tests, and slice documentation.

### Validation deferred to Slice 11.5

All Qt, composed/system, offscreen, replay, visible, lifecycle, host-regression,
and complete-suite validation.

## Slice 11.2: Real-editor finalization and calibrated zero-progress checkpoint

### Objective and explicit non-goals

Build reusable joined-journey preparation through revision 3: real randomized
editor creation/finalization, exact prepared evidence, Design A head staging,
real 1800 us / 18 nL calibration Apply, and exact calibrated zero-progress
evidence. Do not close/reopen an application, activate a reloaded execution,
calibrate remaining stocks, execute an array, or register the scenario.

### Exact call path

```text
typed case -> real ExperimentEditorDriver -> Qt Generate/Finalize
-> authoritative revision 1
-> case-to-design/plan/progress/reconstruction assertions
-> real rack/head and CalibrationDialogDriver
-> ExperimentModel lock revision 2 and calibration revision 3
-> calibration record/head/progress joins
-> literal revision-3 zero-progress count assertion
```

### Entrance prerequisites and exit criteria

Entrance: Slice 11.1 committed, clean, and hashes frozen. Exit: prepared and
revision-3 snapshots match every literal identity/count; Design B remains
exact; all added counts and all execution lifecycle collections are zero; the
action sequence remains within its partial cap; no production file changes.

### Contracts, identity, hashes, and evidence introduced

- reusable real-editor-to-active-calibrated phase inputs;
- additive assertion IDs such as
  `experiment.randomized_joined_design_exact` and
  `execution.calibrated_zero_progress_exact`;
- evidence at
  `metrics.persistence.values.randomized_calibration_lifecycle.prepared` and
  `.calibrated_zero_progress`, without a report schema change;
- exact plan/design/assignment/count, calibration-record, printer-head,
  progress-reference, revision-history, dialog, and zero-dispatch evidence.

### Initial files expected to change

- `tools/virtual_workflows/actions.py` only if an existing reusable action
  cannot accept the typed inputs;
- `tools/virtual_workflows/page_drivers.py`;
- `tools/virtual_workflows/journey_phases.py`;
- `tools/virtual_workflows/journeys.py`;
- `tools/virtual_workflows/assertions.py`;
- `tools/virtual_workflows/authoritative_evidence.py`;
- `tools/virtual_workflows/editor_reporting.py` if additive projection is needed;
- focused action, driver, phase, assertion, evidence, composition, and
  contract-freeze tests;
- add a focused system test module for the joined journey;
- add Slice 11.2 implementation plan/completion record and advance only the
  master-plan current action.

### Focused tests and SIL checks

Run adjacent Milestone 9/10 unit and contract tests plus one selected
`--run-sil-lifecycle` checkpoint system test. Assert real Qt control use,
literal mapping, revisions 1/2/3, exact Design A/Design B/fill maps, one
calibration record linked to the Design A stock and head, zero added progress,
zero intent/simulator events, expected screenshots, hardware isolation, and
clean teardown. No visible run and no full terminal journey.

### Retained evidence and replay

Retain focused test output and checkpoint diagnostics/screenshots only. Do not
publish a passing scenario report or replay for a deliberately partial
lifecycle. The complete scenario replay remains deferred.

### Compatibility contracts

Preserve the editor driver used by all Milestone 10 cases, the full Milestone
9 calibration driver, existing action/assertion IDs, report-v1, and the
production direct-Model authoring/apply paths.

### Commit boundary

One commit: `test: add randomized calibrated zero-progress checkpoint`.

### Risks and rollback

Risks are treating reconstructed plan order as identity, accepting a narrow
rounding result by recomputing expected values, or allowing the first Apply to
dispatch. Compare only literal `(stock_id, well_id)` rows and require all
observer event collections empty. Rollback removes the new joined phase and
assertions while retaining the singleton contract.

### Validation deferred to Slice 11.5

Fresh-session rotation, remaining calibrations, execution, terminal reload,
offscreen/replay/visible qualification, broader regressions, and full pytest.

## Slice 11.3: Reusable clean-session rotation and exact fresh activation

### Objective and explicit non-goals

Add the reusable clean-session rotation phase justified above. Rotate from the
revision-3 calibrated zero-progress checkpoint, load through the real editor,
prove authoritative reconstruction in a new application session, and activate
explicitly with only the existing allowlisted checkpoint/export/audit effects.
Do not add pause/resume branching, execute a stock pass, register the scenario,
or generalize production reload behavior.

### Exact call path

```text
revision-3 checkpoint and first observer
-> restore hooks -> close_application_session()
-> exact directory comparison -> reopen_application_session()
-> new observer and starvation instrumentation
-> ExperimentLoaderDriver real Qt load
-> persisted/analysis-only reconstruction assertions
-> explicit Qt activation
-> active revision-3 runtime and zero-progress assertions
```

### Entrance prerequisites and exit criteria

Entrance: Slice 11.2 committed and clean. Exit: session IDs and recorder roots
are distinct, the first recorder is closed and lock absent, files are identical
through close and read-only load, activation changes only the established
allowlist and creates one clean revision-3 checkpoint, the second model
reconstructs every literal from files, runtime is inactive before and active
after explicit activation, and all progress and lifecycle counts remain zero.

### Contracts, identity, hashes, and evidence introduced

- `run_clean_authoritative_session_rotation_boundary()` with lifecycle-neutral
  inputs/callbacks and no scenario-specific branches;
- assertions for clean teardown, fresh application identity, persisted-source
  load, allowlisted activation effects, revision/reference identity, and
  zero-progress rehydration;
- evidence containing both application-session records, before/after directory
  hashes, loaded and activated boundaries, fresh observer identity, and the
  literal case comparison;
- no new evidence schema version and no modification of the paused/reload
  phase or its historical evidence.

### Initial files expected to change

- `tools/virtual_workflows/harness.py` only if a generic read-only freshness
  field is missing; otherwise leave it unchanged;
- `tools/virtual_workflows/journey_phases.py`;
- `tools/virtual_workflows/journeys.py`;
- `tools/virtual_workflows/assertions.py`;
- `tools/virtual_workflows/authoritative_evidence.py`;
- focused harness, phase, assertion, evidence, composition, and
  authoritative-reload tests;
- the joined focused system test module;
- add Slice 11.3 implementation plan/completion record and advance only the
  master-plan current action.

### Focused tests and SIL checks

Unit tests must reject reused application-session IDs, open recorder/lock,
close-time or load-time file mutation, any disallowed activation write, missing
or duplicate activation audit/checkpoint evidence, stale plan/progress/resume
references, runtime active before activation, missing calibration/head join,
nonzero progress, and first-session lifecycle leakage. Run the existing paused
reload success/failure tests unchanged and one focused two-session offscreen
system test through activation. No visible or terminal execution.

### Retained evidence and replay

Retain focused results plus two-session boundary diagnostics. A partial
activation report is not accepted as scenario qualification; exact scenario
replay remains deferred to Slice 11.5.

### Compatibility contracts

`run_authoritative_reload_resume_boundary()`, completed-terminal reload,
`merge_session_lifecycles()`, existing application-session evidence, and all
Milestone 7-10 reload assertions remain byte/behavior compatible.

### Commit boundary

One commit: `test: add clean authoritative session rotation phase`.

### Risks and rollback

Risks are retaining a first-session object, confusing retained root with a
reused application, and overgeneralizing pause/resume. Require persisted-source
reconstruction against the literal case, a distinct application-session ID,
fresh observer installation, and zero session-1 execution events. Rollback
removes the new phase/caller/tests; do not alter the existing paused phase.

### Validation deferred to Slice 11.5

Remaining calibration, all execution, terminal reload, retained direct/replay,
visible qualification, lifecycle/host regression, and complete pytest.

## Slice 11.4: Remaining calibration, exact execution, terminal reload, and registration

Status: complete (2026-08-08); see
`docs/sil_interactive_simulation_milestone_11_slice_4_completion_record.md`.

### Objective and explicit non-goals

Complete the composed journey: calibrate Water then Design B, reconcile
revision 5, execute all explicit stock passes, prove exact intent/simulator/
progress truth, transition to revision 6, and reload terminal state in a third
fresh session. Only after the full system test passes, register the one active
scenario and capability and add it to the lifecycle suite. Do not add a
matrix, refill/resume, negative safeguards, or production changes.

### Exact call path

```text
fresh active revision 3
-> Water real calibration Apply -> revision 4
-> Design B real calibration Apply -> revision 5
-> exact plan/progress/runtime map
-> ID-keyed Design A, Design B, Water stock passes
-> durable intent -> Machine_FreeRTOS -> SimulatedMachine DISPENSE
-> persisted completion for all 24 pairs / 80 drops
-> COMPLETED revision 6
-> clean close and third application session
-> real Qt terminal load without activation
-> exact terminal and no-extra-dispatch reconciliation
```

### Entrance prerequisites and exit criteria

Entrance: Slice 11.3 committed and clean. Exit: all three calibration records
and heads join by stock ID, revision chain is exactly 1-6, 24 unique commands
and 80 drops reconcile at every required layer, terminal reload is completed
analysis-only, action count is at most 96, and the registered scenario,
manifest, suite, and focused system contract agree.

### Contracts, identity, hashes, and evidence introduced

- case-owned remaining-calibration and stock-pass specs keyed by stock ID;
- final assertions for identity continuity, revision chain, per-pass boundary,
  exact count layers, session attribution, terminal state, and terminal reload;
- required named screenshots:
  `design_generated`, `prepared_randomized`, `calibrated_zero_progress`,
  `fresh_loaded`, `fresh_activated`, `remaining_stocks_calibrated`,
  `design_a_pass_complete`, `design_b_pass_complete`, `water_pass_complete`,
  `completed`, and `terminal_reloaded`;
- active registry and manifest scenario
  `randomized_calibration_reload_execution_v1`, capability
  `execution.randomized_calibration_reload_execution`, and lifecycle suite
  membership;
- additive report evidence at
  `metrics.persistence.values.randomized_calibration_lifecycle`, with the
  frozen joined-case/count hashes and no report schema change.

### Initial files expected to change

- `tools/virtual_workflows/journeys.py`;
- `tools/virtual_workflows/journey_phases.py` only for reusable composition;
- `tools/virtual_workflows/assertions.py`;
- `tools/virtual_workflows/authoritative_evidence.py`;
- `tools/virtual_workflows/registry.py`;
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`;
- `tests/test_virtual_workflow_registry.py` or current manifest tests;
- `tests/test_virtual_workflow_manifest.py`;
- `tests/test_virtual_workflow_selection.py`;
- `tests/test_virtual_workflow_journey_phases.py`;
- `tests/test_virtual_workflow_assertions.py`;
- `tests/test_virtual_workflow_authoritative_evidence.py`;
- `tests/test_virtual_workflow_composition.py`;
- `tests/test_virtual_workflow_contract_freeze.py`;
- the joined system test module;
- add Slice 11.4 implementation plan/completion record and advance only the
  master-plan current action.

### Focused tests and SIL checks

Run all joined unit/contract tests, adjacent count/action/driver/phase tests,
manifest/selection/runner tests, existing calibration/reload/terminal tests,
and the selected full scenario system test with `--run-sil-lifecycle`. Add
negative mutations for wrong head/record stock, pass order used as identity,
duplicate/missing intent, command mismatch, progress mismatch, session-1/3
dispatch, terminal revision drift, activation of completed state, action-cap
overflow, and cleanup failure. This is focused offscreen system validation,
not retained final qualification; no visible run yet.

### Retained evidence and replay

Retain focused outputs and one diagnostic full-system report if useful for
review, but do not call it milestone qualification. Slice 11.5 must run a new
source-current direct scenario and exact emitted replay beneath its dedicated
retained root.

### Compatibility contracts

Existing scenario order stays stable except the intentional append to the
lifecycle suite. Existing scenario definitions, action/assertion vocabulary,
selectors, matrix catalogs/hashes, historical aggregate hashes, and replay
parsers remain unchanged. The new capability is supported only by this
scenario and cannot make unrelated or Pi coverage pass.

### Commit boundary

One commit: `test: add randomized calibration reload execution SIL journey`.

### Risks and rollback

Risks are hidden positional association, calibrating the wrong stock after
randomization, duplicate execution after rotation, and terminal state based on
in-memory rather than persisted progress. Require explicit IDs at every API
boundary and fresh terminal reconstruction. Rollback removes the registered
scenario/capability and complete journey while leaving the reusable clean
rotation phase if it has independent passing callers/tests.

### Validation deferred to Slice 11.5

Retained offscreen and exact replay, visible and visible replay, full lifecycle
and host-regression suites/replays, complete Python suite, evidence audit,
operator documentation, and milestone closeout.

## Slice 11.5: Qualification, retained evidence, documentation, and closeout

Status: complete (2026-08-08); see
`docs/sil_interactive_simulation_milestone_11_slice_5_completion_record.md`.

### Objective and explicit non-goals

Qualify the source-current scenario and compatibility lanes, audit retained
evidence, update operator documentation, and record Milestone 11 complete.
This slice is documentation-only after successful qualification. Any source
defect requires a separate correction commit and a complete Slice 11.5 restart.
Do not run Pi, stress, firmware, analysis-pipeline, physical hardware, or
release operations.

### Exact call path

```text
clean committed Slice 11.4 source
-> direct offscreen scenario -> exact emitted replay
-> visible Windows scenario -> exact emitted visible replay
-> lifecycle suite fresh children -> exact aggregate replay
-> host-regression suite -> exact aggregate replay
-> focused contracts and complete default pytest once
-> evidence/hash/manual screenshot audit
-> documentation-only completion record and master-plan closeout
```

### Entrance prerequisites and exit criteria

Entrance: Slices 11.1-11.4 committed independently; worktree clean; scenario,
case, fixture, manifest, and source hashes captured. Exit: every qualification
passes from one source identity, all replays pass, required evidence and
screenshots are inspected, full pytest passes once, docs are current,
`git diff --check` passes, and Milestone 11 is recorded complete.

### Contracts, identity, hashes, and evidence introduced

- final source commit/tree fingerprint, scenario/case/fixture/count hashes,
  manifest hash, lifecycle/host selection hashes, and replay commands;
- direct, visible, suite, aggregate, report, evidence-manifest, and named
  screenshot SHA-256 values;
- completion record proving the exact plan/reaction/stock/head/calibration/
  progress/intent/simulator/terminal joins and limitations;
- operator-runbook entry for selection, replay, identity/count inspection,
  session attribution, and terminal reload.

### Initial files expected to change

After qualification, documentation only:

- add `docs/sil_interactive_simulation_milestone_11_slice_5_implementation_plan.md`;
- add `docs/sil_interactive_simulation_milestone_11_slice_5_completion_record.md`;
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`;
- `docs/sil_virtual_workflow_operator_runbook.md`;
- `README.md` only if the operator entry point or prerequisites changed.

### Qualification commands and policy

Use a dedicated `verification_reports/m11-s5/` root. Capture dry-run/listing
identity before execution. The intended direct commands are:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario randomized_calibration_reload_execution_v1 `
  --output-root verification_reports\m11-s5\offscreen `
  --seed 1 --speed-multiplier 1000 --timeout-seconds 180 `
  --qt-platform offscreen

$env:QT_QPA_PLATFORM = "windows"
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario randomized_calibration_reload_execution_v1 `
  --output-root verification_reports\m11-s5\visible `
  --seed 1 --speed-multiplier 20 --timeout-seconds 240 --visible

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --suite lifecycle --output-root verification_reports\m11-s5\suites `
  --seed 1 --speed-multiplier 1000 --qt-platform offscreen

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --suite host_regression --output-root verification_reports\m11-s5\suites `
  --seed 1 --speed-multiplier 1000 --qt-platform offscreen

.\env\Scripts\python.exe -m pytest -q --basetemp <fresh-external-temp-path>
```

Execute every emitted direct and aggregate replay exactly. Run the focused
unit/contract/composition/system selection before the complete suite. Run the
complete default suite once with at least a 15-minute tool timeout and a fresh
external `%LOCALAPPDATA%\Temp\LabCraft` base temp. Do not enable the analysis
pipeline.

### Retained evidence and replay audit

Retain both direct reports, both direct replays, lifecycle and host-regression
aggregates/replays, child logs, source and selection identities, action and
assertion ledgers, evidence manifests, authoritative snapshots/hashes, all
eleven named screenshots, calibration previews/dialogs, three application-
session records, and exact replay lists. Require:

- at most 96 actions, no timeout/termination, exactly one matching report per
  child, and process/report agreement;
- simulation banner, hardware disabled, zero unexpected dialogs/errors,
  zero starvation, zero simulator overflow, and clean teardown;
- session 1 revision-3 zero progress and zero dispatch;
- session 2 authoritative-file reconstruction, explicit activation, all 24
  unique intents and 80 droplets, and no positional joins;
- session 3 completed analysis-only reload and zero dispatch;
- terminal targets, terminal added, intent, simulator, and completed durable
  rows equal the literal final map exactly once.

### Compatibility contracts

Recheck all frozen Milestone 9/10 hashes, unchanged report/plan/aggregate
schemas, exact replay, existing reload and no-mutation tests, and historical
artifact availability. The intentionally expanded lifecycle selection receives
a new source-current selection hash; historical hashes remain untouched.

### Commit boundary

One documentation commit: `test: close randomized calibration lifecycle SIL milestone`.

### Risks and rollback

Qualification risk is accepting stale, ambiguous, or mixed-source evidence.
Require a single post-Slice-11.4 source identity and restart after any source
correction. Rollback reverts only the Slice 11.5 documentation closeout; Slices
11.1-11.4 and retained historical evidence remain. No evidence is deleted.

### Validation deferred beyond Milestone 11

Milestone 12 safeguards, Milestone 13 exploration, refill-required/resume,
host stress, Pi, firmware, protocol, HIL, physical hardware, and release work.

## Planned slice sequence

1. Freeze the singleton joined contract, selected Milestone 10 identity,
   literal mapping/count/revision/head truth, hashes, and compatibility audit.
2. Prove real-editor finalization and the real Design A boundary calibration
   through the calibrated revision-3 zero-progress checkpoint.
3. Add the lifecycle-neutral clean-session rotation phase and prove fresh
   authoritative load plus explicit activation at zero progress.
4. Calibrate remaining stocks, execute and reconcile all 24 pairs / 80 drops,
   reload terminal state, then register the complete scenario/capability.
5. Run retained offscreen/replay/visible/regression/full-suite qualification,
   audit evidence, document operation, and close the milestone.

There are no material production, architecture, schema, safety, or scope
decisions left open by this planning pass. Reversible implementation naming
and exact test-file organization may change within a slice. A discovered
production mismatch, need for a persisted-schema change, or inability to
express the clean rotation without changing production behavior is a stop
condition requiring a separate reviewed plan.
