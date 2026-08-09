# Milestone 12 Execution Plan: Editor, Execution-Preflight, and Persistence Safeguards

Status: complete; all five slices and final qualification passed (2026-08-09)

Prepared: 2026-08-08

Authoritative source:
`docs/sil_interactive_simulation_and_composable_workflows_plan.md`

Predecessors: Milestones 9, 10, 11, and 11A are complete. Their execution
plans, slice plans, completion records, commits, fixtures, literal oracles, and
retained evidence remain historical inputs and must not be rewritten.

This document defines the completed implementation and qualification.
Milestone 13 remains unstarted.

## Objective and safety boundary

Prove, through independently runnable real-Qt operator actions and isolated
authoritative reload boundaries, that invalid design, calibration, durable
identity, lifecycle, or persistence state is rejected before dispensing. Every
negative case must observe its literal typed result and operator-visible
evidence, then apply one shared no-mutation/no-dispatch oracle.

Milestone 12 may add typed SIL contracts, compact fixtures, scenario/matrix
orchestration, test-only fault builders, assertions, registration, focused
tests, retained reports, and documentation. It does not assume a production
change. If a required guard fails open, that result is a separate product
defect. Stop the active slice, retain the failing evidence, and prepare a
minimal reviewed correction plan; do not weaken the expected rejection,
literal oracle, or no-dispatch boundary.

The following remain out of scope for every slice:

- firmware, device protocol, serial framing, and physical-hardware behavior;
- motion, pressure-control, timing, camera, balance, or droplet-quality claims;
- refill workflows and refill-required/resume while authoritative volume
  tracking remains disabled;
- persisted application-schema changes or broad MVC refactors;
- release metadata and release operations;
- modification, simplification, regeneration, or silent re-freezing of the
  Milestone 11A positive-control fixture, case, scenario, or literal oracle;
- correction of the pre-existing `print_array_stress_384x10_v1` pulse-width
  fixture/staging mismatch;
- seeded exploration or any other Milestone 13 work.

No fault fixture may touch a user experiment. Fault builders operate only on a
new case-owned directory beneath the current SIL scenario root, before the
application under test launches. Original and mutated inventories and SHA-256
values are retained. After launch, a rejected action is read-only relative to
that prepared fault baseline.

## Verified entrance baseline and compatibility freeze

Planning began on branch `feature/general_bug_fix_1` at `a2e1bc18`. The only
pre-existing worktree modification was the reviewed Milestone 12/13 update to
the authoritative plan. This document treats that diff as approved input and
does not modify it.

The evidence inspected for this plan includes:

- the Milestone 9 slice plans and completion records, including the
  independently reviewed cross-session evidence correction, exact keyed count
  normalization, calibration-requantization matrix, missing-fill fail-closed
  case, direct/replay reports, visible qualification, and source fingerprints;
- the Milestone 10 execution plan, all slice plans and completion records, the
  nine-case experiment-design catalog, real Finalize rejection driver,
  `experiment.finalization_rejected_no_mutation`, literal dialogs, matrix
  runner, and fresh-process/replay/visible qualification;
- the Milestone 11 execution plan, all slice plans and completion records,
  clean-session rotation, explicit inactive load and activation, keyed
  calibration/plan/progress joins, terminal reload, reports, and fingerprints;
- the Milestone 11A execution plan and all five completion records, the typed
  optimizer-360 case, fixture, assertions, registered journey, manifests,
  direct/replay/visible evidence, suite results, and retained `host_stress`
  finding;
- the relevant production UI, Controller, Model, authoritative inspection,
  execution-plan/revision/progress/resume, calibration, and print-dispatch
  paths; their focused tests; and the current workflow actions, page drivers,
  assertions, scenario/matrix runners, selection, reports, manifests,
  fingerprints, screenshots, exact replay, visible mode, and cleanup tooling;
- recent Git history from Milestone 9 through Milestone 11A. Milestone 11 and
  11A history is immutable for this work.

The following qualified Milestone 11A identities are immutable positive-control
inputs:

| Contract | SHA-256 |
| --- | --- |
| fixture | `d7f4de4aafeaf4a66751872d017d89393c263d48b5ffefa1b0e1690efaa10783` |
| normalized case | `f238d4d90b822fdf52d4170b1f6fc1871b3d73f56df3aad543637f3e5d4078d8` |
| requested reaction multiset | `5acfa8580c581231275e2b6f17ec757d71df5dcc4696196e1c0f9b2176ee7afd` |
| achieved reaction multiset | `418cf4a50cc0015c52b9b093a5df9096df98930dc0f58f42aa37c30830fe64f0` |
| randomized assignment | `5f84bfd4cd7c2c0d4b289b6797c50feeab9739a65d56ac2fc3949da030ab3ed2` |
| expanded count oracle | `3f86a60425d2c0d6abf0839d9f0fca16a41a6e398125053dd849d2e9b397458f` |

`optimizer_360_calibration_reload_execution_v1` remains the immutable complex
positive control for production optimizer behavior, randomized assignment,
five stock-specific calibrations, clean-session rotation, exact five-pass
execution, 1,800 durable intents, 46,208 droplets, and terminal persistence.
Milestone 12 must not edit its JSON fixture, Python case, literal values,
assertion semantics, scenario definition, or frozen hashes. It is selected as a
compatibility run at closeout; it is not copied or replayed for each negative
safeguard.

The known `print_array_stress_384x10_v1` failure is distinguishable by scenario
ID, report path, assertion ID `execution.stock_head_settings_match`, and its
fixed-1355-us staging versus per-stock 1300-1390-us fixture values. It is not a
Milestone 12 product failure. The complete `host_stress` aggregate is therefore
not a required green gate. Direct Milestone 12 catalogs and the selected direct
and replayed optimizer-360 child must report their own identities and outcomes
independently of that aggregate.

## Existing call paths and ownership

### Editor action to authoritative state

Experiment authoring intentionally does not pass through a Controller method:

```text
real Qt ExperimentDesignDialog edits
-> dialog input, dirty-state, optimization, capacity, and well validation
-> ExperimentModel.optimize_stock_solutions()
-> ExperimentModel.generate_experiment()
-> operator presses Finalize Design
-> ExperimentDesignDialog._on_finish()
-> MainWindow.complete_experiment_design()
-> Model.load_experiment_from_model() or prepared-design commit
-> experiment_design.json
-> execution_plan_revisions/ and execution_plan.json
-> progress.json, key.csv, concentration_key.csv, and audit
```

The rejection baseline is captured immediately before the attempted operator
action. Draft edits made to create the invalid condition are setup, not a
post-rejection mutation. A rejected Finalize must leave the dialog unaccepted,
runtime inactive, authoritative files byte-identical or absent as specified,
and all dispatch counters unchanged.

### Calibration and durable identity

```text
real Qt calibration Generate / Select / Apply
-> CalibrationModePreflightDialog and Controller.get_calibration_mode_preflight()
-> DropletImagingDialog Apply
-> ExperimentModel.apply_droplet_volume_for_option() or apply_fill_droplet_volume()
-> ExperimentModel.lock_execution_plan("calibration_started")
-> ExperimentModel.apply_execution_calibration()
-> immutable plan revision plus execution_calibrations.json
-> stock.calibration_record_key and stock.printer_head_id

applied machine settings only
-> DropletImagingDialog._apply_print_settings_for_applied_calibration()
-> Controller.apply_applied_imaging_calibration_print_settings()
-> machine-setting methods
```

Identity comparisons use durable `stock_id`, `printer_head_id`, calibration
record ID, design hash, plan ID/revision, progress reference, reaction ID, and
well ID. Row order, dictionary iteration, list position, slot position, and
pass position are never identity.

### Inspect, activate, start, resume, recalibrate, edit, and exchange

```text
operator chooses an experiment folder in the real editor
-> ExperimentModel.load_experiment()
-> inspect_authoritative_execution()
-> inactive/read-only editor classification and exact eligibility
-> operator presses Load Execution
-> Model.load_authoritative_execution_runtime()
-> explicit activation side effects only after complete validation

operator presses Start or Resume
-> WellPlate/Array Qt control and confirmation
-> applied-calibration and settings UI preflight
-> Controller.print_array()
-> ExperimentModel.validate_authoritative_print_context()
-> ExperimentModel.prepare_authoritative_print_pass()
-> Controller._start_array_run_context()
-> Controller._queue_next_array_well()
-> ExperimentModel.begin_execution_print_intent()
-> Machine_FreeRTOS.print_droplets()
-> SimulatedMachine DISPENSE
-> completion callback, durable intent completion, and progress
```

An active or progressed execution is edit-locked. Calibration of a stock with
positive progress is rejected before a new revision. Head exchange is valid
only at idle or `resume_ready` with a drained queue; an invalid exchange attempt
must not alter rack/gripper identity or commands. Resume is valid only at an
eligible clean resume boundary. A completed execution remains analysis-only and
cannot be activated, started, or resumed.

### Authoritative persistence classification

`inspect_authoritative_execution()` validates the exact persisted design hash,
latest plan, immutable contiguous history, progress linkage and counts,
calibration sidecar and references, checkpoint contents and fingerprint, and
plate identity. Inspection returns a typed bundle and eligibility without
writing. Existing exact statuses include `ready_to_start`, `ready_to_resume`,
`repairable_checkpoint`, `blocked_missing_checkpoint`,
`blocked_ambiguous_intent`, `blocked_checkpoint_reference`,
`blocked_checkpoint_progress`, `complete`, `analysis_only`, and fatal blocked
classification with issue code `authoritative_bundle_invalid`.

Explicit activation may create or repair the allowed checkpoint and update the
existing activation export/audit allowlist only after validation. A blocked or
ambiguous bundle must remain inactive and must not be repaired, normalized,
reoptimized, activated, started, or resumed.

### Dispatch paths forbidden after a rejection

The shared oracle must prove that rejection did not reach or change any of:

- authoritative pass preparation or a new plan revision;
- array run context, queueing, transport resume, or machine command history;
- durable intent begin, attachment, discard, or completion collections;
- `Machine_FreeRTOS.print_droplets()` or simulator `DISPENSE` events;
- per-stock/per-well added droplets or completion state;
- runtime activation, array state, rack/gripper binding, or unrelated stock;
- persisted plan/progress/resume/calibration/key/audit files, except no files at
  all for the rejected action. A persistence fault's prelaunch mutation is
  recorded separately and is never counted as an allowed rejection mutation.

## Milestone-wide contract and architecture

### Typed catalogs

Use three versioned catalogs rather than one long negative journey:

- `editor_safeguards_v1`;
- `execution_preflight_safeguards_v1`;
- `authoritative_persistence_safeguards_v1`.

Each catalog case is independently selectable and stops immediately after the
expected rejection and shared oracle. Catalog fields must include, at minimum:

- schema version, case ID, family, description, fixture identity, setup kind,
  and real operator action ID/label;
- literal expected issue/preflight/eligibility code and classification;
- exact dialog class/title/message or message fragments, selected button, UI
  status/banner/control state, and expected array/queue state;
- literal durable design, plan, stock, head, calibration, progress, and intent
  identities used by that case;
- exact permitted prelaunch fixture mutations and their target relative paths;
- expected before/after lifecycle and dispatch counts;
- qualification tier, timeout, required screenshots, action cap, and report
  evidence paths.

Expected values are case-owned literals. They may not be generated by the
production optimizer, assignment, calibration, reconstruction, or eligibility
algorithm. Production values are observations only.

### Shared no-mutation/no-dispatch oracle

Capture a `SafeguardBoundarySnapshot` immediately before and after the rejected
operator action. The shared assertion compares the following exact projections:

- directory inventory, file sizes, and SHA-256 values;
- design SHA-256, plan ID/revision/state, immutable revision names/hashes,
  progress plan ID/revision/fingerprint, calibration record IDs and bindings,
  resume state/intents, audit row count, and completion count;
- runtime-active flag, runtime assignments and target/added maps keyed by
  durable IDs, loaded stock/head IDs, rack/gripper origin, and unrelated stock
  state;
- Controller array state and run context, transport pause state, queue-drained
  state, queued command IDs, and command-history projection;
- observer begins, attachments, completions, discard batches, pass starts,
  terminal transitions, simulator commands, simulator `DISPENSE` events,
  total commanded droplets, and overflow counters;
- action ledger, expected dialog/message/code, unexpected dialogs, errors,
  activation count, and session identity.

The assertion passes only when the exact typed rejection is observed and every
non-UI before/after projection is equal, unless a case explicitly expects the
already existing safe boundary (`idle` or `resume_ready`) to remain unchanged.
No negative case may use cleanup to erase an unsafe command or mutation.

Existing `DirectoryEvidence`, `AuthoritativeBundleSnapshot`,
`capture_authoritative_bundle()`, `capture_count_snapshot()`, execution
observer lifecycle data, modal evidence, action ledger, queue checks,
`experiment.finalization_rejected_no_mutation`, and
`calibration_apply_fail_closed_assertion` should be composed rather than
duplicated. New code is justified only for one general boundary snapshot,
typed rejection comparison, isolated fault manifest, and any UI driver branch
that cannot already express the real attempted action.

### Override policy

Some current calibration and settings dialogs intentionally offer explicit
operator overrides. The normal Milestone 12 safeguard case must choose Cancel
and prove the exact preflight code plus zero mutation/dispatch. A bypass may be
covered only by a separately named compatibility test and cannot satisfy a
safe-start capability. Non-overridable durable identity and authoritative
persistence mismatches must fail closed. An unexpected success, implicit
override, missing dialog, weaker code, or dispatch before Cancel is a product
defect signal.

### Compact and reduced fixtures

Most cases use the smallest deterministic design that reaches one boundary,
normally one or two stocks and one to four wells. Every negative fixture owns
exact literal stock, head, calibration, plan, progress, and expected-dialog
values and stops after the rejection.

A reduced, case-owned derivative of the Milestone 11A contract is allowed only
for these identity-focused cases:

1. correct numeric calibration values joined to the wrong stock or printer-head
   identity;
2. the same durable stock records presented in a different row order;
3. a calibration made stale by an operator-visible optimizer regeneration or
   prepared refinalization boundary.

The derivative must not import the optimizer-360 expected algorithms, alter the
immutable fixture, or pretend to be the positive control. It should retain only
the minimum multiple-stock identities and literal values needed to expose a
positional join. The reordered-row case is a positive identity-control: the
semantically identical keyed bundle remains valid and inactive after
inspection. Its paired wrong-join case must reject. The regeneration/
refinalization case must use the normal editor lifecycle to create a new design
or plan identity; reusing the old calibration must then produce the literal
stale/missing result. If the normal UI cannot create the planned boundary, stop
and record the mismatch instead of mutating active authoritative files.

## Slice 12.1: Typed contracts and shared no-mutation/no-dispatch oracle

### Scope and exclusions

Define the three catalog schemas, typed case/rejection/fault contracts, literal
normalization and hashing, the general boundary snapshot, and the shared
assertion. Add unit-level fixtures sufficient to test malformed contracts and
each snapshot field. Do not register or execute a real safeguard case, add a UI
driver branch, change production code, or touch the optimizer-360 fixture.

### Operator-visible actions and outcomes

This slice describes but does not yet claim end-to-end operator coverage. The
contract must represent Finalize, Upload Design, calibration Generate/Apply,
Load/Activate, Start/Resume, Edit, Recalibrate, and Head Exchange attempts. A
typed expected outcome contains the production code/classification, exact
dialog/message and selected Cancel/OK action where applicable, disabled-control
evidence where no modal is applicable, and the unchanged safe lifecycle state.

Contract tests must reject missing or ambiguous operator actions, success
outcomes in a negative case, position-keyed identities, computed expected
values, unbounded message matching, unspecified mutation allowances, missing
queue/dispatch expectations, or a persistence fault without containment and
original/mutated hashes.

### Call paths involved

```text
typed case JSON -> catalog loader/validator -> canonical case/catalog hash
boundary capture -> existing authoritative/count/observer/UI projections
-> shared typed-rejection + no-mutation/no-dispatch assertion
-> report-v1 assertion result and evidence payload
```

No production UI, Controller, Model, persistence, workflow, or dispatch method
is invoked by this slice's unit contract tests.

### Files likely to change

- add `tools/virtual_workflows/safeguards.py`;
- add compact tracked catalog fixtures beneath
  `tools/virtual_workflows/fixtures/` as each family is populated;
- add `tests/test_virtual_workflow_safeguards.py`;
- add `docs/sil_interactive_simulation_milestone_12_slice_1_implementation_plan.md`;
- add `docs/sil_interactive_simulation_milestone_12_slice_1_completion_record.md`;
- update only Milestone 12 current-slice text in the authoritative plan.

No production file is expected to change.

### Fixtures, reused helpers, and genuinely new helpers

Use tiny in-memory snapshots and one contained temporary directory for oracle
unit tests. Reuse `DirectoryEvidence`, directory comparison, authoritative
bundle capture, keyed count normalizers, execution observer projections,
`AssertionResult`, canonical JSON hashing, report JSON safety, and fixture
identity checks.

New helpers are limited to:

- strict `SafeguardCase`, `ExpectedSafeguardOutcome`, and
  `PersistenceFaultSpec` types;
- `SafeguardBoundarySnapshot` with a deterministic JSON projection;
- `capture_safeguard_boundary()`;
- `safeguard_rejection_no_mutation_no_dispatch_assertion()`;
- isolated-fault containment and mutation-manifest validation.

### Focused automated validation

Run the new contract tests plus adjacent evidence, assertions, report,
manifest, and freeze tests. Include mutation tests for every required snapshot
field, malformed catalog fields, duplicate IDs, nondurable identity joins,
path escape, postlaunch mutation, unexpected dispatch, activation, resume, and
report-serialization overflow.

No direct SIL, manifest-registered execution, fresh child, replay, or visible
run is required yet because no executable case exists. That absence must be
explicit in the completion record and must not be described as safeguard
coverage.

### Reports, artifacts, fingerprints, and acceptance

Freeze schema version, ordered placeholder catalog identities as applicable,
type-normalized hashes, focused-test command/result, and the source fingerprint
used for tests. Do not fabricate scenario reports. Slice acceptance requires
all contract mutation tests to fail closed, byte/hash comparison to cover every
required authoritative file, dispatch comparison to cover intents/commands/
completions/drops, and all pre-Milestone 12 frozen contract tests to pass.

### Risks, edge cases, rollback, and dependencies

Risks are a false equality caused by omitted mutable state, nondeterministic
ordering, oversized report evidence, and conflating setup mutation with action
mutation. Canonicalize by durable keys, bound raw evidence while retaining
hashes/counts, and baseline only after setup. Slice 12.1 depends on Milestones
9-11A and is required by every later slice. Rollback removes only the new typed
contracts, empty/new fixture scaffolding, tests, and slice documentation.

## Slice 12.2: Editor safeguards

### Scope and exclusions

Populate and execute `editor_safeguards_v1` using compact deterministic editor
fixtures. Each case performs one real operator action and stops immediately
after rejection. Do not calibrate, activate, start, resume, mutate persisted
fault copies, extend two-stock production behavior, or replay the complete
optimizer-360 journey.

### Cases and expected operator-visible outcomes

| Case | Real action | Literal expected outcome |
| --- | --- | --- |
| `impossible_fixed_target_finalize_rejected` | enter the literal impossible fixed/max stock inputs and press Finalize | optimization rejection, `QMessageBox` title `Optimization failed`, catalog-owned issue code/message, dirty dialog remains open |
| `printed_exceeds_final_finalize_rejected` | set Printed Volume above Final Reaction Volume and press Finalize | issue code `printed_exceeds_final_volume`, title `Invalid volumes`, exact literal volume message, styled invalid controls, no optimizer call/finalization |
| `one_stock_infeasible_finalize_rejected` | leave two-stock disabled for a literal one-stock-infeasible design and press Finalize | `Optimization failed` with exact one-stock infeasibility code/message |
| `two_stock_infeasible_finalize_rejected` | enable two-stock for a literal design infeasible even with two stocks and press Finalize | `Optimization failed` with exact two-stock infeasibility/limit code/message |
| `capacity_plus_one_finalize_rejected` | generate five reactions for four printable wells and press Finalize | `Insufficient Well Capacity`, exact required `5` and available `4`, dialog remains open |
| `invalid_uploaded_well_rejected` | use Upload Design with an out-of-plate literal well such as `G16` on `96well-8x12` | `Invalid well assignments`, exact plate/well message, upload not applied |
| `excluded_uploaded_well_rejected` | use Upload Design with one case-local excluded well such as `A1` | `Invalid well assignments`, exact `Excluded wells`/`A1` message, upload not applied |
| `dirty_invalid_finalize_rejected` | disable auto-update, edit the clean generated design into one invalid invariant, then press Finalize | dirty state and Optimize/Generate guidance are visible; Finalize reaches the exact invalid-input/optimization rejection and cannot reuse stale generated truth |

The final literal catalog may reuse the already qualified Milestone 10 numeric
inputs and strings, but it must not silently change the Milestone 10 catalog or
turn its multi-step recovery cases into Milestone 12 negative evidence. Cases
that share an input must still own separate case IDs and stop at their intended
boundary.

### Call paths involved

```text
Qt editor controls / Upload Design / printable-well selection
-> dirty and input validation
-> optimizer/generator only where the case permits
-> _validate_plate_capacity() or uploaded-well validation
-> _on_finish()
-> expected modal/status rejection
-> no MainWindow.complete_experiment_design() success
-> no authoritative plan/progress/runtime/dispatch mutation
```

### Files likely to change

- `tools/virtual_workflows/safeguards.py`;
- `tools/virtual_workflows/fixtures/editor_safeguards_v1.json`;
- `tools/virtual_workflows/actions.py`;
- `tools/virtual_workflows/page_drivers.py` only for missing real Qt mechanics;
- `tools/virtual_workflows/journeys.py`;
- `tools/virtual_workflows/matrices.py` and `matrix_runner.py` only as needed to
  register the catalog without a new schema;
- `tools/virtual_workflows/assertions.py` only for a thin shared-oracle wrapper;
- `tools/virtual_workflows/editor_reporting.py`;
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`;
- adjacent unit/system tests, especially the safeguards, actions, page-driver,
  assertions, matrices, manifest, report, and experiment-design matrix tests;
- Slice 12.2 implementation plan and completion record;
- authoritative-plan current-slice text only.

No production file is expected to change.

### Reuse and necessary additions

Reuse the Milestone 10 editor specification, expected-modal handler, QTest
control editing, folder/CSV isolation, stock-table evidence, well picker,
optimization-attempt ledger, immediate pre-Finalize directory baseline,
`editor_create_rejected_assertion`,
`experiment_finalization_rejected_no_mutation_assertion`, screenshots,
matrix selection, fresh children, and report/replay plumbing.

Add only generalized negative terminal codes, the Upload Design operator path
if not already exposed by the shared driver, and the shared Milestone 12
snapshot/assertion. Do not duplicate optimizer or well-validation logic in the
oracle.

### Automated, direct, replay, and visible validation

- focused product-adjacent tests:
  `test_experiment_design_stock_input_validation.py`,
  `test_experiment_design_capacity_guard.py`,
  `test_experiment_design_well_selection_ui.py`, and
  `test_experiment_designer_interlock.py`;
- focused workflow catalog/driver/assertion/report/manifest tests;
- each new case directly with `--matrix editor_safeguards_v1 --case <id>` in a
  fresh process;
- complete manifest-registered `editor_safeguards_v1` matrix and its emitted
  exact aggregate replay;
- visible Windows direct and exact replay for
  `printed_exceeds_final_finalize_rejected`,
  `capacity_plus_one_finalize_rejected`, and
  `excluded_uploaded_well_rejected` at a bounded reviewed speed/watchdog.

### Reports, artifacts, fingerprints, and acceptance

Every report must retain the exact action label, issue code, dialog class/title/
text/button, invalid control/status state, before/after snapshot, directory
inventory/hashes, zero dispatch, screenshot where required, cleanup, hardware
isolation, case/catalog/fixture hash, source fingerprint, and exact replay.

Acceptance requires all eight real actions to reach their literal rejection,
the shared oracle to pass, no stale generated design to finalize, no runtime
activation, and no new authoritative execution artifact, intent, command,
completion, or drop. Existing Milestone 10 case/catalog hashes and its focused
rejection assertions remain unchanged.

### Risks, edge cases, rollback, and dependencies

Risks are baselining before setup, treating a disabled control as a completed
action, accepting message substrings that hide a different code, and accidental
reuse of a stale clean plan. Capture immediately before the attempt, require
one recorded QTest interaction, exact bounded messages, and explicit dirty/
clean evidence. Slice 12.2 depends on Slice 12.1. Rollback removes only this
catalog, its registration/driver branches, tests, and slice documents.

## Slice 12.3: Calibration, identity, and lifecycle preflight safeguards

### Scope and exclusions

Populate and execute `execution_preflight_safeguards_v1`. Cover calibration
generation and Apply, Start/Resume, inactive inspection/activation, edit,
recalibration, and head exchange at invalid boundaries. Use compact fixtures
except for the three allowed reduced multi-stock identity derivatives. Do not
change production override policy, execute a full 360-reaction negative case,
add refill behavior, or modify physical settings outside the simulator.

### Calibration/settings cases and outcomes

| Case | Real action | Literal expected outcome |
| --- | --- | --- |
| `calibration_head_mode_cancelled` | request calibration for a mode different from the loaded head and press Cancel | code `head_mode_mismatch`, `Calibration Settings Check` dialog with exact requested/head modes, no calibration start/Apply |
| `calibration_pulse_profile_cancelled` | request calibration with incompatible pulse width/profile and press Cancel | code `pulse_width_mismatch`, exact compatible-profile presentation or reviewed no-profile presentation, no settings command or calibration start |
| `start_missing_applied_calibration_cancelled` | press Start and cancel `Applied Calibration Missing` | code `missing_record`, exact loaded stock/head message, no override and no dispatch |
| `start_stale_design_volume_cancelled` | press Start after the case-owned operator regeneration/refinalization stale boundary and cancel | code `stale_design_volume`, exact applied/current volumes, no override and no dispatch |
| `start_pulse_width_mismatch_cancelled` | press Start with current pulse width different from the applied record and cancel | code `pulse_width_mismatch`, `Print Settings Differ`, no setting switch/override/dispatch |
| `start_pressure_mismatch_cancelled` | press Start with target/current pressure outside the literal tolerance and cancel | code `pressure_mismatch`, `Print Settings Differ`, no setting switch/override/dispatch |

The explicit Cancel selection is part of each oracle. Existing intentional
`Continue Anyway`, missing-calibration override, or settings-mismatch override
behavior is not a normal safe-start pass.

### Durable identity and lifecycle cases and outcomes

| Case | Real action | Literal expected outcome |
| --- | --- | --- |
| `wrong_stock_calibration_binding_rejected` | load/activate the reduced multi-stock copy, stage the affected head, and press Start | `authoritative_context_invalid`; exact wrong stock/calibration-binding message; no pass preparation |
| `wrong_printer_head_calibration_binding_rejected` | stage a head whose numeric calibration values match but durable head ID does not, then press Start | `authoritative_context_invalid`; exact saved-binding message; no pass preparation |
| `reordered_stock_rows_keyed_valid` | inspect the reduced copy with semantically identical stock rows in a different order | exact ready classification and durable keyed joins; remains inactive and dispatch-free until a separate explicit activation; this is the paired positive identity-control |
| `regenerated_design_stale_calibration_rejected` | use the real editor regeneration/refinalization lifecycle to create the case-owned new design/plan identity and changed literal design volume, then attempt Start with the old application record | code `stale_design_volume`, exact old/current volume message, and no positional reassociation |
| `inspected_not_activated_start_rejected` | load a valid persisted execution for inspection, close/leave it inactive, then press Start | Controller `Error`: `This execution has been inspected but not activated...`; runtime remains inactive |
| `invalid_activation_rejected` | press the saved-execution action for a nonactivatable classified bundle or QTest-attempt its disabled control | exact eligibility reason, `Execution Locked`/disabled state or `Could not activate execution` where applicable; no checkpoint write |
| `active_execution_edit_rejected` | open the editor after activation/start and attempt an in-place design edit/finalize | active read-only banner/guidance, disabled mutation controls, no editable source mutation and no activation |
| `progressed_stock_recalibration_rejected` | after one compact durable completion, Generate/Select/Apply a new calibration for that stock | critical `Apply failed` with exact `already dispensed droplets and cannot change calibration` text; no revision/calibration mutation |
| `start_while_active_rejected` | press Start while array state is `running` or `stop_requested` | exact disabled control or Controller rejection; existing run context/queue unchanged |
| `resume_at_invalid_boundary_rejected` | QTest-attempt Resume outside `resume_ready`/eligible resume | exact disabled Resume/control state and safe lifecycle classification; no transport resume or command |
| `head_exchange_at_invalid_boundary_rejected` | attempt the real rack/head exchange while running or stop finalization is incomplete | exact disabled/rejection UI; gripper/slot/head identities and command queue unchanged |

Only the wrong-binding, reordered-row, and regenerated/refinalized-stale cases
may use the reduced multi-stock derivative. All derivative truth is literal and
keyed. The reordered-row case must demonstrate order independence; it must not
be forced to reject merely because serialization order changed.

### Call paths involved

```text
calibration UI action -> Controller calibration mode preflight
-> optional Cancel before calibration process

calibration Apply -> ExperimentModel lock/requantization/calibration revision
-> expected Apply failed before mutation when lifecycle is invalid

Start/Resume UI -> applied calibration/settings UI preflight
-> Controller.print_array() -> authoritative identity preflight
-> rejection before pass preparation, run context, intent, or machine command

editor/rack action -> lifecycle-enabled state -> rejection/disabled control
-> unchanged design/runtime/rack/queue state
```

### Files likely to change

- `tools/virtual_workflows/safeguards.py`;
- `tools/virtual_workflows/fixtures/execution_preflight_safeguards_v1.json`;
- a small separate reduced-identity fixture if keeping it out of the catalog
  JSON makes review materially clearer;
- `tools/virtual_workflows/actions.py`, `page_drivers.py`, `journey_phases.py`,
  `journeys.py`, `matrices.py`, `assertions.py`, and `execution_observer.py` only
  for the listed reusable actions/evidence;
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`;
- focused safeguards, actions, page-driver, journey-phase, assertion, catalog,
  manifest, calibration-dialog, print-guard, plan-integration, and system tests;
- Slice 12.3 implementation plan/completion record and authoritative current
  slice text.

No production file is expected to change.

### Reuse and necessary additions

Reuse `CalibrationDialogDriver`, its preflight/profile interaction and
`apply_expected_failure()`, `ArrayDriver`, `RackDriver`, existing head identity
binding/staging, clean authoritative load/activation, editor post-start lock,
prepared refinalization, keyed stock/well count capture, execution observer,
calibrated-zero-progress assertions, and source immutability evidence.

Add only QTest branches for Cancel at calibration/settings preflights, an
inactive-inspection Start attempt, invalid lifecycle control attempts, and a
literal reduced multi-stock fixture loader. The shared oracle remains the sole
no-mutation/no-dispatch decision.

### Automated, direct, replay, and visible validation

- focused production-adjacent tests including `test_print_profiles.py`,
  `test_controller_print_guards.py`, `test_view_array_controls.py`,
  `test_experiment_designer_interlock.py`,
  `test_initial_execution_plan_integration.py`, and authoritative runtime-cache
  tests selected for identity/revision failure;
- focused workflow driver/assertion/journey/catalog/manifest tests;
- every case directly and then the complete manifest-registered catalog in
  fresh children, followed by exact aggregate replay;
- visible Windows direct and exact replay for at least
  `start_missing_applied_calibration_cancelled`,
  `wrong_printer_head_calibration_binding_rejected`,
  `progressed_stock_recalibration_rejected`, and
  `head_exchange_at_invalid_boundary_rejected`;
- the reordered-row positive identity-control both directly and in the
  registered catalog, without printing a stock pass.

### Reports, artifacts, fingerprints, and acceptance

Retain literal case/derivative hashes; stock/head/calibration/design/plan/
progress IDs; ordered serialized rows plus keyed normalized projection;
preflight code and full record; exact dialogs/buttons; before/after plan and
calibration hashes; queue/array/rack state; observer and machine histories;
screenshots; source fingerprint; cleanup; and exact replay.

Acceptance requires each invalid real action to show its exact rejection,
every negative shared oracle to pass, the reordered-row control to retain exact
keyed truth, no accidental activation/resume, no new plan/calibration revision,
and zero new intents, commands, completions, or drops. Any identity mismatch
that starts a pass is a blocking product defect.

### Risks, edge cases, rollback, and dependencies

Risks include mistaking an intentional override for the safe path, applying
machine settings before Cancel, positional stock joins, racing an active queue,
and creating stale state by forbidden file mutation. Record the selected button
and command history, key all joins, wait only for bounded safe states, and use
normal editor transitions. Slice 12.3 depends on Slices 12.1-12.2. Rollback
removes its catalog, derivative, registration, new driver branches, tests, and
slice documents while leaving all earlier safeguards and positive scenarios.

## Slice 12.4: Isolated persistence and authoritative-reload safeguards

### Scope and exclusions

Populate and execute `authoritative_persistence_safeguards_v1`. Build each fault
from a known-good compact prepared or progressed fixture into a unique contained
copy before application launch, change exactly one invariant, and retain both
inventories. Drive real Qt folder load and the visible activation attempt/state.
Do not mutate files after launch, auto-repair a blocked bundle, write a passing
state, or touch any user/historical experiment.

### Cases and expected persistence classifications

| Case | Single isolated fault | Real action and literal expected outcome |
| --- | --- | --- |
| `unreflected_pending_intent_blocked` | add one pending intent not reflected by progress | load folder; status `blocked_ambiguous_intent`, exact ambiguous intent ID/reason, activation disabled, no repair |
| `positive_progress_without_checkpoint_blocked` | remove checkpoint from a progressed copy | load folder; `blocked_missing_checkpoint`, exact reason, inactive analysis-only UI |
| `checkpoint_plan_revision_conflict_blocked` | change only checkpoint plan revision | load folder; `blocked_checkpoint_reference`, exact reason, no checkpoint rewrite |
| `checkpoint_progress_fingerprint_conflict_blocked` | change only persisted progress after a clean checkpoint | load folder; `blocked_checkpoint_progress`, exact reason, no activation |
| `progress_plan_revision_conflict_invalid` | change only `progress.json` execution reference | load folder; fatal issue `authoritative_bundle_invalid` with exact plan/progress revision message |
| `latest_plan_history_conflict_invalid` | make latest plan conflict with the immutable latest revision or omit one required contiguous revision | load folder; fatal `authoritative_bundle_invalid`, exact history/revision message |
| `progressed_calibration_link_missing_invalid` | remove only the calibration sidecar or referenced record from a progressed calibrated copy | load folder; fatal `authoritative_bundle_invalid`, exact missing calibration-link message |
| `design_plan_hash_conflict_invalid` | change only the copied design payload | load folder; fatal `authoritative_bundle_invalid`, exact design-hash message |
| `incomplete_authoritative_bundle_invalid` | remove exactly one required copied file, preferably `progress.json`, in its own case | load folder; fatal `authoritative_bundle_invalid`, exact missing-file message |

If a missing `execution_plan.json` is interpreted as a legacy/unrun design by
current production policy, do not use that mutation to claim authoritative
rejection. Use a required file whose authoritative-plan presence keeps the
case on the authoritative path, or record the behavior as a separately reviewed
scope decision.

`repairable_checkpoint` is a positive classification and must not be confused
with rejection. Existing Milestone 11 activation repair compatibility remains
covered by focused tests; Milestone 12 does not activate it as a negative case.

### Call paths involved

```text
known-good compact fixture -> contained copy -> one prelaunch fault mutation
-> original/mutated fault manifest and hashes
-> fresh application launch
-> Qt Experiment Editor / Select Experiment Folder
-> ExperimentModel.load_experiment()
-> inspect_authoritative_execution()
-> exact issue + eligibility + locked/inactive editor presentation
-> activation control attempt/disabled evidence
-> shared no-mutation/no-dispatch oracle relative to mutated baseline
```

### Files likely to change

- `tools/virtual_workflows/safeguards.py`;
- `tools/virtual_workflows/fixtures/authoritative_persistence_safeguards_v1.json`;
- `tools/virtual_workflows/persistence_io.py` or a focused new fault-builder
  module if that keeps mutation code clearly test-only;
- `tools/virtual_workflows/authoritative_evidence.py`;
- `tools/virtual_workflows/actions.py`, `page_drivers.py`, `journeys.py`,
  `matrices.py`, and `assertions.py` only for contained load/rejection evidence;
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`;
- focused safeguards, fault-builder, authoritative-evidence, page-driver,
  assertion, manifest, and persistence system tests;
- Slice 12.4 implementation plan/completion record and authoritative current
  slice text.

No production persistence code is expected to change.

### Reuse and necessary additions

Reuse atomic fixture preparation, scenario-root containment,
`snapshot_directory()`, rich inventories, `capture_authoritative_bundle()`,
`ExperimentLoaderDriver`, inactive-load boundaries, eligibility evidence,
revision/progress/resume serializers used by tests, report manifests, cleanup,
and the shared oracle.

Add a strict allowlisted fault builder that resolves every target beneath the
case root, copies rather than moves, applies one typed mutation, and emits a
manifest containing source path/hash, destination path, operation, original
hash, mutated hash or intentional absence, and prelaunch timestamp/session
phase. It must refuse user roots, historical report roots, multiple mutations,
path traversal, active application state, or a missing source baseline.

### Automated, direct, replay, and visible validation

- focused persistence tests: `test_authoritative_execution_load.py`,
  `test_authoritative_execution_runtime_cache.py`,
  `test_execution_plan.py`, `test_execution_plan_revision.py`,
  `test_execution_progress_store.py`, `test_execution_resume_store.py`, and
  selected initial-plan integration tests;
- fault-builder containment, one-mutation, original-preservation, and hash
  tests, including symlink/path-escape defenses where supported;
- every case directly, then the manifest-registered complete catalog in fresh
  child processes, followed by exact aggregate replay;
- visible Windows direct and exact replay for
  `unreflected_pending_intent_blocked`,
  `progressed_calibration_link_missing_invalid`, and
  `incomplete_authoritative_bundle_invalid`.

### Reports, artifacts, fingerprints, and acceptance

Retain the pristine source fixture identity, copied root, fault manifest,
original and mutated inventories/hashes, exact issue code/message/context,
eligibility flags, locked editor action/banner/status, attempted control
evidence, before/after mutated-baseline snapshot, zero activation/dispatch,
screenshots, cleanup, source fingerprint, case/catalog hashes, and replay.

Acceptance requires every real load to classify exactly, every blocked case to
remain inactive, no activation/repair/checkpoint/export/audit write, no command
or drop, pristine source fixtures byte-identical, contained copies retained for
diagnosis, and no user experiment access. A production guard that normalizes or
activates ambiguous state is a blocking defect.

### Risks, edge cases, rollback, and dependencies

Risks are faulting the wrong root, changing two invariants, producing an invalid
JSON parser failure instead of the intended semantic boundary, and mistaking
prelaunch mutation for rejection mutation. Resolve and record absolute roots,
verify containment, parse the mutated document, and compare against the mutated
baseline only after launch. Slice 12.4 depends on Slices 12.1-12.3. Rollback
removes the persistence catalog, test-only builders, registration, tests, and
slice documents; generated case-owned copies may be removed only under their
contained report root and historical reports/user data are never deleted.

## Slice 12.5: Replay, visible qualification, regression, documentation, and closeout

### Scope and exclusions

Freeze the three complete catalogs, run source-current qualification and exact
replays, inspect visible evidence, run compatibility/regression gates, validate
reports/fingerprints/lifecycle evidence, update operator documentation, and
close Milestone 12. Add no case and change no oracle in this slice. Any source
or fixture correction requires separate review and a complete Slice 12.5
restart. Do not start Milestone 13 or create its goal.

### Operator-visible qualification coverage

Every catalog case must already exercise its real operator action and exact
typed outcome. Closeout visibly re-runs a representative set spanning:

- invalid volume, capacity, and excluded-well editor rejections;
- calibration-mode/settings Cancel, wrong durable head/calibration binding,
  progressed-stock recalibration, and invalid head exchange;
- ambiguous intent, missing calibration linkage, and incomplete authoritative
  bundle reload.

Each visible representative is followed by its emitted exact replay. Inspect
the actual modal title/text/buttons or locked control/banner/status, simulation
banner, unchanged safe state, and absence of an unexpected dialog. Do not use
the optimizer-360 scenario as a visible negative fixture.

### Exact qualification path

```text
completed Slice 12.4 review checkpoint and source
-> list catalogs/cases and deterministic dry-run plans
-> direct fresh-process execution of every safeguard case
-> complete manifest-registered catalog aggregates
-> exact aggregate replays
-> visible representative direct runs and exact replays
-> selected immutable optimizer-360 direct run and exact replay
-> focused safeguard-family tests
-> lifecycle and host-regression compatibility suites/replays
-> full default Python suite once
-> evidence/hash/manual screenshot audit
-> documentation-only closeout
```

The selected positive-control command is the registered
`optimizer_360_calibration_reload_execution_v1` scenario itself, not the
complete `host_stress` suite. Its report must retain the frozen fixture/case/
reaction/assignment/count hashes, sessions 1-3, revisions 1-8, 1,800 intents,
and 46,208 droplets. This result is reported separately from the known 384x10
aggregate exclusion.

### Files likely to change

- add `docs/sil_interactive_simulation_milestone_12_slice_5_implementation_plan.md`;
- add `docs/sil_interactive_simulation_milestone_12_slice_5_completion_record.md`;
- add `docs/sil_interactive_simulation_milestone_12_completion_record.md`;
- update `README.md` with prerequisites, exact catalog commands, visible mode,
  replay, and known `host_stress` troubleshooting;
- update `docs/sil_virtual_workflow_operator_runbook.md` with selection,
  safeguard interpretation, artifacts, and failure policy;
- update only Milestone 12 status/results and Current Next Action in the
  authoritative plan.

No code, fixture, manifest, production file, Milestone 11/11A record, or
historical report is expected to change in Slice 12.5.

### Automated and SIL validation gate

Before execution, record a clean worktree, exact commit/source fingerprint,
catalog listing, ordered case hashes, fixture hashes, manifest hash, and dry-run
plan hashes. Use fresh output roots and bounded reviewed timeouts.

Required gates are:

1. every editor, preflight/lifecycle, and persistence case directly in a fresh
   process;
2. all three manifest-registered complete catalogs and their exact aggregate
   replays;
3. the visible representative set and each exact replay;
4. focused scenario-family unit and system tests, including the shared oracle,
   fault builder, drivers, manifests, reports, selection, fresh-child runner,
   and fingerprint/freeze tests;
5. lifecycle suite and exact replay, plus host-regression suite and exact
   replay, to protect existing deterministic paths;
6. direct and exact replay of immutable
   `optimizer_360_calibration_reload_execution_v1` with its frozen hashes and
   terminal totals;
7. the complete default Python suite with at least a 900000 ms tool timeout:

   ```powershell
   .\env\Scripts\python.exe -m pytest -q
   ```

8. opt-in analysis-pipeline tests only if analysis-pipeline code changed. They
   are not enabled merely because Milestone 12 exists.

Do not require the complete `host_stress` aggregate to be green. If it is run
diagnostically, record the optimizer-360 child independently and preserve the
known `print_array_stress_384x10_v1` mismatch without fixing or weakening it.

### Reports, artifacts, fingerprints, and lifecycle requirements

Retain every direct report, catalog plan/aggregate, replay report/aggregate,
visible screenshot, evidence manifest, log, child PID/return code, source and
manifest identity, case/catalog/fixture hash, fault manifest, original/mutated
file hash, and cleanup result. Never overwrite or delete failed qualification
runs.

Audit that:

- every negative report passes only because the exact safeguard assertion and
  shared no-mutation/no-dispatch oracle pass;
- all expected action/assertion IDs and screenshots are present and no
  unexpected dialog, omitted assertion, timeout, hardware access, or evidence
  overflow is accepted;
- every child is a fresh process, selects exactly one matching report, agrees
  with the parent result, and records the same source inputs;
- exact replay preserves case order, literal outcomes, normalized keyed
  evidence, and fingerprints while allowing generated IDs/timestamps/paths to
  differ where the existing schema permits;
- lifecycle state remains the exact pre-rejection safe boundary, queue is
  drained or unchanged as specified, runtime is not accidentally activated,
  and Start/Resume/transport dispatch never leaks;
- the optimizer-360 control remains byte/hash compatible and exact at its
  existing terminal boundary.

### Milestone acceptance criteria

Milestone 12 is complete only when:

- every required safeguard is exercised through a real operator action;
- exact typed rejection/persistence classification and exact UI evidence are
  present for every negative case;
- the shared no-mutation/no-dispatch oracle passes for every negative case;
- persistence faults remain isolated and are classified without activation;
- direct, manifest-registered, fresh-process, exact replay, and required
  visible-mode coverage pass;
- focused scenario-family tests, lifecycle/report/fingerprint validation, and
  the selected immutable Milestone 11A positive-control compatibility check
  pass;
- the complete Python suite passes with the required timeout;
- documentation records exact commands, reports, hashes, limitations, risks,
  rollback, and the known distinguishable 384x10 exclusion;
- `git diff --check` passes, each implementation slice has its own reviewed
  plan and completion record, and the complete milestone is captured in one
  final descriptive commit.

### Risks, rollback, and dependencies

Closeout risks are accepting stale evidence, mixing source fingerprints,
silently omitting a failed child, treating the known host-stress issue as new,
or changing source during qualification. Fail closed on any of those
conditions. A source correction restarts the complete closeout sequence after
its separate review checkpoint.

Slice 12.5 depends on completed, independently reviewed Slice 12.1-12.4
checkpoints in the cumulative Milestone 12 worktree. Rollback after completion
reverts the single final Milestone 12 commit; no artifact deletion or data
migration is part of rollback.

## Slice sequence and execution discipline

The five independently reviewable slices are:

1. typed safeguard contracts and shared no-mutation/no-dispatch oracle;
2. editor safeguards;
3. calibration, durable identity, and lifecycle preflight safeguards;
4. isolated persistence and authoritative-reload safeguards;
5. exact replay, visible qualification, regressions, documentation, and
   milestone closeout.

For each future execution slice:

1. verify the prior slice completion record, frozen hashes, and cumulative
   worktree contains only authorized Milestone 12 changes plus explicitly
   reviewed planning input;
2. write the slice implementation plan before code, restating call path, exact
   files, tests, safety boundary, defect policy, and rollback;
3. implement the smallest slice and no production correction unless separately
   planned and reviewed;
4. run focused tests and only that slice's direct/registered/replay/visible
   gates;
5. inspect and hash retained evidence, write the completion record, and run
   `git diff --check` without creating an intermediate commit;
6. do not advance while an expected rejection, literal oracle, shared snapshot,
   source fingerprint, cleanup result, or compatibility hash is unresolved.

The repository's one-milestone-per-commit policy and the active goal require a
single final descriptive Milestone 12 commit after all five slices and gates
pass. The slice boundaries remain independently reviewable through their
implementation plans, completion records, focused validation, and retained
evidence; no intermediate slice commit is created.

## Milestone 13 dependency

Milestone 13 remains out of scope. It cannot begin, and no Milestone 13
execution goal may be created, until the deterministic Milestone 9-12 baseline,
including the immutable Milestone 11A optimizer-360 positive control, is stable
and Milestone 12 is formally closed.

## Recommended execution-goal objective

Use this exact objective when the user later authorizes creation of the
Milestone 12 execution goal:

> Implement and qualify Milestone 12 of the SIL interactive simulation and
> composable workflows plan in five independently reviewed slices, proving
> real-operator editor, calibration/identity/lifecycle preflight, and isolated
> authoritative-persistence safeguards fail closed with exact typed UI evidence
> and a shared no-mutation/no-dispatch oracle, while preserving
> `optimizer_360_calibration_reload_execution_v1` as the immutable complex
> positive control and excluding firmware, protocol, physical hardware, refill
> workflows, the known 384x10 stress mismatch, and all Milestone 13 work.
