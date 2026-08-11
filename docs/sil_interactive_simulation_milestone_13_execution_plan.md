# Milestone 13 Execution Plan: Bounded Seeded Design/Calibration Exploration

Status: `complete (2026-08-09)`

Prepared: 2026-08-09

This document began as the implementation and qualification plan for Milestone
13 of `docs/sil_interactive_simulation_and_composable_workflows_plan.md`. Its
start-boundary gate passed before implementation, and all five authorized
slices were completed and qualified on 2026-08-09. The original scope and gate
commands remain below as the historical contract.

The start-boundary gate in this document passed on 2026-08-09 from a clean
worktree at `cc9656e3`. That gate activated Slice 13.1 only after the committed
deterministic Milestones 9-12 baseline, including the immutable Milestone 11A
optimizer-360 positive control, was reconfirmed stable.

Start-boundary evidence: deterministic Milestone 9-12 direct and exact replay,
the immutable optimizer-360 direct and exact replay (1,800 intents, 46,208
droplets, three sessions), lifecycle and host-regression direct/replay, 342
focused tests, 53 selected real-Qt tests with 3 skips, and the exact default
Python suite (`4269 passed, 127 skipped`) all passed. `git diff --check` passed.
Evidence is retained below `verification_reports/milestone_13_start/`. The
known 384x10 host-stress aggregate was not run and remains separately scoped.

## Objective and safety boundary

Add a separately versioned, state-aware Windows host-SIL exploration campaign
that composes already qualified deterministic editor, calibration, persistence,
identity, and lifecycle actions in bounded legal and illegal/recovery orders.
Every generated operation must reuse a literal Milestone 9-12 matrix, scenario,
safeguard, or focused-test oracle. Generated exploration supplements those
deterministic cases and never replaces them.

The proposed campaign identity is:

- campaign ID: `design_calibration_lifecycle_v1`;
- generator version: `design-calibration-lifecycle-v1`;
- state-model version: `design-calibration-state-v1`;
- operation-catalog version: `design-calibration-operation-v1`;
- oracle-ledger version: `design-calibration-oracle-ledger-v1`;
- semantic-coverage version: `design-calibration-semantic-coverage-v1`.

The campaign uses compact deterministic cases. The normal generated corpus is
limited to four reactions, four durable well IDs, no more than three executable
stock IDs including fill, twelve dispense intents, and 120 commanded droplets
per sequence. `optimizer_360_calibration_reload_execution_v1` remains a
separately selected immutable stress oracle; its 360 reactions, five stocks,
1,800 intents, 46,208 droplets, three sessions, and revisions 1-8 are not copied
into generated fixtures.

The milestone excludes:

- firmware, protocol, physical calibration, motion, pressure-control behavior,
  refill behavior, and any physical-hardware claim;
- refill-required or resume operations while volume tracking is disabled and
  `execution.refill_resume` remains deferred;
- mutation of active authoritative files, except the already qualified,
  explicitly isolated, prelaunch Milestone 12 persistence-fault fixtures;
- generated persistence faults in the first campaign version;
- user experiment roots, historical evidence mutation, artifact deletion, or
  automatic cleanup;
- unseeded acceptance, unbounded random walks, unattended scheduling,
  `pi_stress`, and production hardware mode;
- any correction to the separately scoped
  `print_array_stress_384x10_v1` pulse-width fixture/staging mismatch.

## Inspected baseline

Planning inspection established the following entrance facts:

- the worktree was clean at `cc9656e3` (`test: qualify Milestone 12 safeguards`);
- Milestone 8 `editor_prepared_guard_v1` is complete and frozen at seeds
  `1, 7, 19, 42, 101`, ten sequences, a 25-action cap, and exploration
  plan/aggregate schema v1;
- Milestone 9 exact count and requantization oracles, Milestone 10 literal design
  cases, Milestone 11 joined randomized/calibrated lifecycle, Milestone 11A
  optimizer-360 control, and all 34 Milestone 12 safeguards are committed;
- Milestone 12 qualified all safeguard direct/replay matrices, ten visible
  direct/replay representatives, optimizer-360 direct/replay, lifecycle and
  host-regression direct/replay, 611 focused tests, 34 real-operator safeguard
  system tests, and the default suite (`4269 passed, 127 skipped`);
- the tracked capability manifest, report v1, matrix plan/aggregate v1,
  selection plan/aggregate v1, source fingerprint, screenshot, replay, and
  cleanup contracts are current;
- no current evidence authorizes Milestone 13 implementation before its own
  start-boundary stability gate.

The start gate compares observations to these Milestone 12 closeout references:

- executable/verification source-tree SHA-256
  `febdea578d1accd35793fb24736e9ff932bc6479d10cdf5bff1c231399528b9f`;
- manifest SHA-256
  `0b79d8a99f5353c8017588cfe42036fc65ca9eec930f729a54209b32a8fe5bb0`;
- editor/preflight/persistence safeguard catalog SHA-256 values
  `7b75e9776402641a1b8b00527b394de8296f5ed29875af52c05970de328d7da5`,
  `0a4169cfc5f844e25cc02c1af74ab9b26b01d82a9703470b85adfc0b0ed763c2`,
  and `64fffe3723489cb812358be06f146c22fd72cf36c4fc61292d5820154a06656c`;
- optimizer-360 fixture, case, requested-multiset, achieved-multiset,
  assignment, and count-oracle SHA-256 values
  `d7f4de4aafeaf4a66751872d017d89393c263d48b5ffefa1b0e1690efaa10783`,
  `f238d4d90b822fdf52d4170b1f6fc1871b3d73f56df3aad543637f3e5d4078d8`,
  `5acfa8580c581231275e2b6f17ec757d71df5dcc4696196e1c0f9b2176ee7afd`,
  `418cf4a50cc0015c52b9b093a5df9096df98930dc0f58f42aa37c30830fe64f0`,
  `5f84bfd4cd7c2c0d4b289b6797c50feeab9739a65d56ac2fc3949da030ab3ed2`,
  and `3f86a60425d2c0d6abf0839d9f0fca16a41a6e398125053dd849d2e9b397458f`.

Documentation-only commits do not change the executable/verification source
identity. Any executable or verification change after `cc9656e3` must be
reviewed and the start gate must record the new source identity rather than
pretend it is the qualified Milestone 12 fingerprint.

## Existing call paths to preserve

### Editor operations and finalization

Experiment authoring intentionally has no Controller hop:

```text
normalized generated operation
-> QTest on the real ExperimentDesignDialog / WellSelectionDialog
-> dialog dirty, input, well, formulation, and capacity validation
-> ExperimentModel.optimize_stock_solutions() / generate_experiment()
-> operator Finalize Design
-> ExperimentDesignDialog._on_finish()
-> MainWindow.complete_experiment_design()
-> Model.load_experiment_from_model() / prepared-design commit
-> experiment_design.json
-> immutable execution_plan_revisions/ plus execution_plan.json
-> progress.json, key.csv, concentration_key.csv, and audit
-> authoritative-evidence capture, action/assertion ledgers, screenshots,
   report v1, child report hash, exploration aggregate
```

Changing existing reagent values, one/two-stock mode, printable wells, or
randomization/seed changes only the dialog/model draft. Optimize/Generate makes
the draft clean and generated. Finalize/Refinalize is the first authoritative
commit. No editor operation may create a print intent, array run context,
machine print command, completion, or simulator `DISPENSE`.

### Head and calibration operations

```text
normalized stage-head operation
-> real rack/head page controls through the shared journey driver
-> rack/gripper model transfer and durable printer_head_id/stock_id binding
-> Controller print-setting methods
-> idle/resume-ready and drained-queue boundary
-> setting-command evidence only; no print intent or DISPENSE

normalized calibration Generate / Select / Apply
-> real CalibrationDialogDriver controls
-> seeded SIL calibration provider and literal result fingerprint
-> Controller.get_calibration_mode_preflight()
-> ExperimentModel.apply_droplet_volume_for_option() or
   apply_fill_droplet_volume()
-> ExperimentModel.lock_execution_plan("calibration_started")
-> ExperimentModel.apply_execution_calibration()
-> immutable plan revision and execution_calibrations.json
-> stock_id/printer_head_id/calibration_record_id binding
-> Controller.apply_applied_imaging_calibration_print_settings()
-> count, revision, identity, settings, UI, and report evidence
```

A mismatching head can be staged as an observed setup condition; the typed
rejection is attached to the later calibration or Start attempt. Staging itself
must not be misreported as rejected.

### Close, reload, activation, execution, and terminal persistence

```text
real session close
-> app.close_simulated_session
-> bounded cleanup of timers, machine, Controller, View, and Model references
-> retained authoritative files and cleanup result

fresh application session
-> real folder selection in the editor
-> ExperimentModel.load_experiment()
-> inspect_authoritative_execution() read-only validation
-> reloaded inactive eligibility and locked/read-only presentation
-> operator presses Load Execution
-> Model.load_authoritative_execution_runtime()
-> active zero-progress state only after exact validation

operator presses Start
-> real WellPlate/Array control and confirmation
-> applied-calibration/settings UI preflight
-> Controller.print_array()
-> ExperimentModel.validate_authoritative_print_context()
-> ExperimentModel.prepare_authoritative_print_pass()
-> Controller._start_array_run_context() / _queue_next_array_well()
-> ExperimentModel.begin_execution_print_intent()
-> Machine_FreeRTOS.print_droplets()
-> SimulatedMachine DISPENSE
-> durable intent completion, exact progress, terminal persistence
-> terminal reload/inspection, evidence manifest, report, child hash, aggregate
```

All joins use durable design hash, plan ID/revision, progress reference, stock
ID, printer-head ID, calibration record ID, reaction ID, well ID, application
session ID, and authoritative revision identity. UI row, list, slot, pass, or
iteration position is never state or identity.

### Rejected-operation path

```text
modeled valid pre-state and observed SafeguardBoundarySnapshot
-> real Qt operator attempt
-> exact production validation/preflight/lifecycle guard
-> literal typed code/classification/title/message/button or locked status
-> observed post-state snapshot
-> safeguard_rejection_no_mutation_no_dispatch_assertion()
-> safely_rejected observation linked to the unchanged base state
-> valid Qt-only recovery preserving design/plan/progress/revision continuity
-> valid authoritative terminal boundary
```

The shared oracle compares authoritative hashes, plan/progress/revision and
calibration identities, runtime maps, activation state, array/run context,
queue, command history, intents, completions, drops, rack/gripper binding,
audit, modal evidence, session, and action ledger. Cleanup cannot make a failed
rejection pass.

## Milestone 8 compatibility and architecture decision

The Milestone 8 campaign is an immutable compatibility surface:

- preserve `editor_prepared_guard_v1`, `editor-prepared-guard-v1`, seeds
  `1, 7, 19, 42, 101`, sequence order, normalized bytes, catalog and sequence
  hashes, action IDs, fixture derivation, maximum 25 actions, report fields,
  screenshots, exact replay, CLI commands, and plan/aggregate v1 validation;
- preserve `tools/virtual_workflows/exploration.py` public behavior for the
  existing campaign and retain all current unit/contract/system tests;
- preserve the current CLI behavior that rejects a conflicting `--seed` for a
  frozen Milestone 8 sequence;
- preserve fresh sequential child isolation, contained output roots,
  non-overwriting atomic writes, child logs, report-v1 hashes, and fail-closed
  timeout/report handling in `exploration_runner.py`.

Milestone 13 should extend campaign discovery and shared child execution, not
replace the Milestone 8 catalog. Add a campaign-specific state/generator module
and a semantic-coverage module. Introduce exploration plan/aggregate v2 only
for `design_calibration_lifecycle_v1`; readers and validators dispatch on
schema version, while v1 remains byte-compatible and fully replayable.

V2 is required because the new plan must retain state-model identity, operation
catalog, oracle-admission ledger, seed tier, all budgets, generated fixture and
sequence identities, original-failure authority, and semantic coverage. These
must not be backfilled into or change the hash projection of v1.

`tools/virtual_workflows/coverage.py` continues to evaluate retained scenario
aggregates against registered manifest capabilities. Milestone 13 semantic
coverage is a distinct v1 document over generated states, transitions,
operations, deterministic oracle IDs, and rejection classes. Exploration
evidence cannot satisfy registered deterministic capability coverage.

## Versioned state model

### Base states

The state machine has the following stable base states:

| State | Required observed contract |
| --- | --- |
| `draft_valid` | Inputs are valid but dirty or not yet generated; no authoritative execution exists. |
| `draft_invalid` | One literal invalid invariant is present; invalid controls/status are visible; no authoritative execution exists or changes. |
| `draft_generated` | Optimize/Generate completed; literal compact stock, reaction, assignment, and count oracle matches; draft is clean but not finalized. |
| `prepared_zero_progress` | Finalized authoritative plan/progress exists at zero progress; runtime is inactive; plan and design identities are exact. |
| `calibration_available_unapplied` | A deterministic calibration result was generated and selected, but its fingerprint is not yet bound into an authoritative plan revision. |
| `calibrated_zero_progress` | Every stock required for the next admitted pass has the exact applied keyed calibration; progress remains zero. Partial calibration is a facet, not an implied ready state. |
| `reloaded_inactive` | A fresh session inspected exact authoritative bytes and eligibility without runtime activation or write. |
| `active_zero_progress` | Explicit activation completed; runtime assignments and calibrated targets exactly match authority; no progress or print intent exists. |
| `progressed_locked` | At least one durable intent/completion exists; editor/recalibration/lifecycle locks apply and plan/progress continuity is exact. |
| `terminal` | All literal compact intents and droplets completed; terminal plan/progress/audit state reloads read-only and inactive. |

`safely_rejected` is a required observed rejection state, but not a destructive
replacement for the base state. It contains the rejected operation ID, literal
rejection class/code/UI result, before/after snapshot hashes, unchanged base
state identity, and recovery edge. After the assertion, the modeled current
base state is exactly the pre-rejection base state.

### Orthogonal facets

Additional facets are necessary to avoid collapsing semantically different
states:

- design validity: `valid` or one named invalid invariant;
- materialization: `dirty`, `generated`, or `finalized`;
- authority: draft design ID/hash or prepared plan ID/revision/design hash;
- calibration: `none`, `available_unapplied`, `partial`, `complete`, or `stale`,
  with stock/head/record IDs;
- persistence: session-local draft, authoritative current, or reloaded exact;
- runtime: `inactive` or `active`, with activation count and session ID;
- progress: `zero`, exact positive intent/completion set, or `complete`;
- lock: editable, prepared-editable, active-locked, progressed-locked, or
  terminal-read-only;
- head binding: durable staged stock/head/calibration identity;
- revision continuity: exact prior/current design hash, plan ID/revision,
  progress reference, immutable revision hashes, and audit count.

Dirty/generated/finalized status, calibration availability/application, runtime
activation, and authoritative revision continuity therefore remain explicit.
No state contains a UI row, list index, slot position, or iteration number.

### Transition rules

- Every normalized operation declares exact allowed source facets, expected
  target facets, operator action ID, deterministic oracle ID, expected outcome,
  and maximum action-ledger expansion.
- Generation fails if an operation has no exact source state, skips an
  intermediate state, exceeds a budget, or has no admitted oracle.
- Execution compares modeled pre-state to observed pre-state before the QTest
  action and modeled target to observed post-state afterward.
- A rejected transition must keep all non-UI facets and the base-state identity
  unchanged. Its only additions are rejection evidence and action/assertion
  ledger rows.
- Recovery cannot close and discard unsafe state, load an unrelated good
  experiment, rewrite authority, or use a fixture mutation. It follows a
  cataloged valid edge on the same durable design/plan lineage.
- Legal and recovered sequences must finish at `terminal`; an intermediate
  prepared or inactive state is not a Milestone 13 terminal boundary.

## Operation and oracle-admission ledger

The first campaign version admits only the following operations and literal
outcomes.

| Operation ID | Admitted source/target | Deterministic oracle |
| --- | --- | --- |
| `editor.change_existing_reagent_via_ui` | valid/generated prepared editor -> dirty valid or named invalid | M8 prepared edit/regenerate/refinalize fixture and action/assertion tests |
| `editor.toggle_two_stock_via_ui` | dirty valid one-stock <-> dirty valid two-stock | M10 `one_stock_feasible` and `two_stock_required`; M12 one/two-stock safeguards |
| `editor.change_printable_wells_via_ui` | draft/prepared editable -> dirty valid | M10 `custom_wells_with_exclusions`, exact capacity, and real picker assertions |
| `editor.set_randomization_seed_via_ui` | draft/prepared editable -> dirty valid | literal M10 `multi_reagent_seed_4321`/`multi_reagent_seed_1234` assignment and multiset hashes |
| `editor.optimize_generate_via_ui` | dirty valid -> `draft_generated` | M10 positive cases and M12 optimizer-infeasible safeguards |
| `editor.regenerate_prepared_design_via_ui` | prepared dirty valid -> generated with new design/revision lineage | M8 prepared campaign and M12 stale-calibration case |
| `editor.finalize_via_ui` | `draft_generated` -> `prepared_zero_progress` | M10 positive/rejected Finalize boundaries and exact authoritative reconstruction |
| `editor.refinalize_prepared_via_ui` | prepared generated -> new `prepared_zero_progress` | M8 refinalize/reload and M12 stale-calibration identity assertion |
| `head.stage_matching_via_ui` | inactive/active safe idle boundary -> keyed matching head staged | M11 joined lifecycle stock/head identities and head-stage focused tests |
| `head.stage_mismatching_via_ui` | safe idle boundary -> deliberately mismatching keyed head staged | M12 wrong-head/wrong-stock binding cases; later guarded action owns rejection |
| `calibration.generate_via_ui` | prepared with staged head -> `calibration_available_unapplied` | M9 requantization and M11 calibration generation fingerprint |
| `calibration.select_via_ui` | available result -> exact selected fingerprint | M9/M11 calibration-dialog selection evidence |
| `calibration.apply_via_ui` | selected matching result -> partial/complete `calibrated_zero_progress` | M9 literal volume/count transition; M11 exact keyed revision/calibration evidence |
| `app.close_simulated_session` | clean zero-progress or safe pass boundary -> no active app | M11 clean session rotation and cleanup contract |
| `experiment.reload_inactive_via_ui` | no active app -> `reloaded_inactive` | M11 byte-identical inactive inspection; M12 persistence classification |
| `experiment.activate_authoritative_via_ui` | eligible `reloaded_inactive` -> `active_zero_progress` | M11 explicit activation; M12 invalid-activation safeguard |
| `array.start_pass_via_ui` | active, matching staged/calibrated head -> active/progressed/terminal | M9 literal per-stock/per-well counts and M11 exact intents/completions/terminal assertions |
| `editor.finalize_invalid_via_ui` | named invalid editor state -> `safely_rejected` | selected M12 invalid-volume/capacity exact dialog plus shared oracle |
| `editor.optimize_one_stock_invalid_via_ui` | literal one-stock-infeasible draft -> `safely_rejected` | M10 `two_stock_required` first attempt and M12 one-stock safeguard/shared oracle |
| `calibration.attempt_mismatch_cancel_via_ui` | mismatching mode/settings -> `safely_rejected` | M12 calibration-mode/settings Cancel code/dialog/shared oracle |
| `array.start_wrong_identity_via_ui` | active with wrong head/calibration binding -> `safely_rejected` | M12 wrong-printer-head binding exact rejection/shared oracle |
| `array.start_inactive_via_ui` | `reloaded_inactive` -> `safely_rejected` | M12 `inspected_not_activated_start_rejected` |
| `editor.attempt_progressed_edit_via_ui` | `progressed_locked` -> `safely_rejected` | M12 `active_execution_edit_rejected` and post-start lock tests |
| `calibration.attempt_progressed_apply_via_ui` | progressed stock -> `safely_rejected` | M12 `progressed_stock_recalibration_rejected` |
| `array.start_while_active_via_ui` | active running boundary -> `safely_rejected` | M12 `start_while_active_rejected` |
| `head.attempt_unsafe_exchange_via_ui` | non-idle/non-drained boundary -> `safely_rejected` | M12 `head_exchange_at_invalid_boundary_rejected` and head-exchange precondition tests |

The frozen campaign must cover every operation above. If action timing makes
`array.start_while_active_via_ui` or `head.attempt_unsafe_exchange_via_ui`
unobservable without racing the queue, Slice 1 must exclude it before freezing
the catalog rather than weaken the guard. Removing an operation changes the
operation-catalog and campaign hashes and must be reviewed before Slice 2.

The following candidates are excluded from v1:

| Candidate | Reason and smallest prerequisite |
| --- | --- |
| Add/remove reagent rows | Existing focused widget tests do not freeze a complete real-Qt add/remove -> regenerate -> refinalize -> reload identity/count oracle. Add one compact deterministic scenario before admission. |
| Standalone Optimize or standalone Generate | The qualified operator action is combined `Optimize & Generate`; do not invent a semantic split. |
| Generated persistence fault/load recovery | M12 faults are prelaunch test-owned mutations, not normal in-session operator operations. Admission requires a reviewed same-authority operator recovery contract; loading an unrelated good bundle is not recovery. |
| Resume or refill-required operations | Deferred while volume tracking is disabled and `execution.refill_resume` is deferred. |
| Mutation of active authoritative files | Prohibited. Only the unchanged M12 isolated prelaunch fault fixtures may mutate their own copies. |
| Unseeded walk, production hardware, physical calibration/motion/pressure | Prohibited and incapable of satisfying application-SIL acceptance. |

Expected values remain catalog-owned literals. Production optimizer,
assignment, calibration, reconstruction, or eligibility algorithms supply only
observations and cannot generate the acceptance oracle.

## Seed tiers, sequence identities, and budgets

### Frozen release-blocking tier

The proposed frozen seeds are exactly:

```text
13, 29, 47, 83, 131, 197
```

They intentionally do not inherit the Milestone 8 set. Six seeds are proposed
because the v1 grammar needs two legal terminal paths and four distinct
illegal/recovery themes while remaining small enough for direct, aggregate,
exact-replay, and visible qualification. Slice 1 must generate and review the
normalized sequences and semantic-coverage projection before freezing them.
If these exact seeds do not satisfy every admitted state, transition,
operation, and rejection class within budget, implementation stops: the seed
set or catalog is changed only by updating this plan/review boundary, never by
silently adding seeds.

Proposed frozen sequence IDs and required roles are:

| Seed | Sequence ID | Required role |
| ---: | --- | --- |
| 13 | `seed_13_legal_design_calibration_terminal` | create/change/two-stock/wells/randomization, finalize, calibrate, activate, execute terminal |
| 29 | `seed_29_legal_refinalize_reload_terminal` | prepared edit/regenerate/refinalize, calibration revision, session rotation, reload/activate, execute terminal |
| 47 | `seed_47_illegal_editor_recovery_terminal` | invalid editor/formulation rejection, exact shared oracle, valid same-design recovery, terminal |
| 83 | `seed_83_illegal_calibration_recovery_terminal` | mismatching calibration preflight rejection, matching Generate/Select/Apply recovery, terminal |
| 131 | `seed_131_illegal_identity_activation_recovery_terminal` | wrong durable head/calibration and inactive-start rejections, valid activation/head recovery, terminal |
| 197 | `seed_197_illegal_progress_lock_recovery_terminal` | positive progress, edit/recalibration/active or exchange lock rejection, valid continuation, terminal |

The generator may choose only among reviewed equivalent placements inside each
role. It may not omit required role semantics. Slice 1 freezes each normalized
sequence SHA-256, the ordered frozen-set hash, catalog hash, oracle-ledger hash,
state-model hash, fixture projection hash, and campaign hash. Every promotion
or normalized-byte change requires a versioned review and invalidates prior
qualification; it is never a runtime sampling decision.

### Diagnostic tier

Diagnostic seeds are explicit and nonblocking. There is no implicit diagnostic
seed, random clock seed, or scheduled sample. The initial compatibility samples
are seeds `1` and `101`, selected only because they provide a recognizable
bridge to Milestone 8; they are not Milestone 13 frozen seeds and their M8
sequences are not reclassified.

The v2 CLI should require both `--seed-tier diagnostic` and
`--diagnostic-seed <non-negative-integer>`. At most four diagnostic seeds may be
selected per invocation. Diagnostic normalized sequences, hashes, reports,
failures, and rerun commands are retained and triaged. They cannot change the
frozen campaign plan, coverage denominator, aggregate classification, or
release gate. Promotion requires a reviewed catalog/seed-set version change and
new frozen hashes.

### Numeric limits

All limits are inclusive and fail closed:

| Budget | Per sequence | Complete six-sequence frozen campaign |
| --- | ---: | ---: |
| Normalized semantic operations | 18 | 108 |
| Executed action-ledger rows | 80 | 480 |
| Application sessions | 3 | 18 |
| Session rotations | 2 | 12 |
| Screenshots | 4 | 24 |
| Retained files | 256 | 1,600 including aggregate artifacts |
| Retained bytes | 48 MiB | 320 MiB including aggregate artifacts |
| Scenario deadline | 270 seconds | n/a |
| External fresh-child watchdog | 300 seconds including termination grace | 1,800 seconds aggregate wall time |
| Reactions / executable stocks / intents / droplets | 4 / 2 / 8 / 44 | 24 / 12 / 48 / 264 |

The complete campaign runs children sequentially. The aggregate wall limit
includes child startup, teardown, report validation, hashing, and summary
writing. Direct and visible single-sequence runs use the same 270/300-second
limits. Offscreen qualification uses `--speed-multiplier 1000`; visible runs
use `20`. A timeout increase, extra screenshot, evidence cap increase, or action
cap increase requires review; a runner may not retry with a larger budget.

The runner checks projected normalized budgets before writes, action/session/
screenshot counters during execution, and file/byte/runtime budgets while
retaining evidence. Any overrun classifies the child and parent `fail`. Existing
artifacts are never deleted to force a pass.

## Start-boundary stability gate

Milestone 13 remains inactive until every command below passes from a clean
worktree. Use a tool timeout of at least 900000 ms for pytest and a sufficiently
large shell timeout for the sequential SIL commands. Record HEAD, source-tree
identity, manifest/catalog/fixture hashes, aggregate/report hashes, replay
commands, cleanup, and the known host-stress exclusion.

```powershell
git status --short --branch
git rev-parse HEAD
git diff --check

.\env\Scripts\python.exe tools\run_virtual_workflow.py --list matrices
.\env\Scripts\python.exe tools\run_virtual_workflow.py --list suites
.\env\Scripts\python.exe tools\run_virtual_workflow.py --scenario optimizer_360_calibration_reload_execution_v1 --dry-run
.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix calibration_requantization_v1 --dry-run
.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix mixed_mode_calibration_v1 --dry-run
.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix experiment_design_pairwise_v1 --dry-run
.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix editor_safeguards_v1 --dry-run
.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix execution_preflight_safeguards_v1 --dry-run
.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix authoritative_persistence_safeguards_v1 --dry-run

.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix calibration_requantization_v1 --output-root verification_reports\milestone_13_start\m9_requantization --seed 1 --speed-multiplier 1000 --timeout-seconds 120 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix mixed_mode_calibration_v1 --output-root verification_reports\milestone_13_start\m9_mixed --seed 1 --speed-multiplier 1000 --timeout-seconds 120 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix experiment_design_pairwise_v1 --output-root verification_reports\milestone_13_start\m10_design --seed 1 --speed-multiplier 1000 --timeout-seconds 120 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --scenario randomized_calibration_reload_execution_v1 --output-root verification_reports\milestone_13_start\m11_joined --seed 1 --speed-multiplier 1000 --timeout-seconds 240 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix editor_safeguards_v1 --output-root verification_reports\milestone_13_start\m12_editor --seed 1 --speed-multiplier 1000 --timeout-seconds 240 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix execution_preflight_safeguards_v1 --output-root verification_reports\milestone_13_start\m12_preflight --seed 1 --speed-multiplier 1000 --timeout-seconds 240 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix authoritative_persistence_safeguards_v1 --output-root verification_reports\milestone_13_start\m12_persistence --seed 1 --speed-multiplier 1000 --timeout-seconds 240 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --scenario optimizer_360_calibration_reload_execution_v1 --output-root verification_reports\milestone_13_start\m11a_optimizer360 --seed 1 --speed-multiplier 1000 --timeout-seconds 900 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --suite lifecycle --output-root verification_reports\milestone_13_start\lifecycle --seed 1 --speed-multiplier 1000 --timeout-seconds 240 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --suite host_regression --output-root verification_reports\milestone_13_start\host_regression --seed 1 --speed-multiplier 1000 --timeout-seconds 240 --qt-platform offscreen
```

Immediately execute, verbatim, the `run.replay_command` retained by each of the
ten direct aggregate/report families above. Do not reconstruct or simplify a
replay. Each replay must select the same catalog/case order or scenario,
fixture/catalog hashes, seed, speed, timeout, Qt platform, and source identity.

Then run:

```powershell
.\env\Scripts\python.exe -m pytest -q tests\test_virtual_workflow_exploration.py tests\test_virtual_workflow_exploration_runner.py tests\test_virtual_workflow_matrices.py tests\test_virtual_workflow_matrix_runner.py tests\test_virtual_workflow_experiment_design_cases.py tests\test_virtual_workflow_joined_interaction_cases.py tests\test_virtual_workflow_optimizer_360_cases.py tests\test_virtual_workflow_safeguards.py tests\test_virtual_workflow_actions.py tests\test_virtual_workflow_page_drivers.py tests\test_virtual_workflow_journey_phases.py tests\test_virtual_workflow_assertions.py tests\test_virtual_workflow_authoritative_evidence.py tests\test_virtual_workflow_report.py tests\test_virtual_workflow_manifest.py tests\test_virtual_workflow_contract_freeze.py
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle tests\system\test_virtual_workflow_matrix_execution.py tests\system\test_virtual_workflow_experiment_design_matrix.py tests\system\test_virtual_workflow_randomized_calibration_lifecycle.py tests\system\test_virtual_workflow_optimizer_360_calibration_lifecycle.py tests\system\test_virtual_workflow_editor_safeguards.py tests\system\test_virtual_workflow_execution_preflight_safeguards.py tests\system\test_virtual_workflow_persistence_safeguards.py
.\env\Scripts\python.exe -m pytest -q
git diff --check
git status --short --branch
```

The gate fails on a dirty or changed source identity, hash drift, missing child,
failed replay, omitted assertion, unexpected dialog, timeout, cleanup failure,
hardware-access attempt, nonzero shared-oracle failure, or any mismatch in the
immutable optimizer-360 fixture/case/reaction/assignment/count hashes, sessions,
revisions, 1,800 intents, or 46,208 droplets. The complete `host_stress`
aggregate is not run or required; the known 384x10 mismatch remains separately
scoped.

Record the passing gate in the Slice 13.1 implementation plan/completion record
before editing generator or runner code. If any gate fails, Milestone 13 stays
inactive and the failure is triaged against its deterministic owner.

## Slice 13.1: State model, catalogs, oracle ledger, seeds, and budgets

### Scope and exclusions

Define immutable typed contracts for the v1 state model, operation catalog,
oracle ledger, compact fixture projections, frozen and diagnostic seed tiers,
normalized sequences, sequence/campaign hashing, and every numeric budget.
Add multi-campaign discovery and v2 plan validation only after freezing v1
compatibility tests. Do not launch Qt, execute a generated sequence, register a
manifest capability, or change production MVC/simulator behavior.

### Call paths and files likely to change

```text
campaign selector -> campaign registry -> M13 generator
-> versioned state/operation/oracle validation
-> local versioned PRNG -> normalized sequence and fixture projections
-> canonical hashes -> v2 dry-run plan with execution_authorized=false
```

Likely files:

- add `tools/virtual_workflows/exploration_m13.py`;
- add `tools/virtual_workflows/semantic_coverage.py` contract types only;
- minimally extend `tools/virtual_workflows/exploration.py`,
  `exploration_runner.py`, and `tools/run_virtual_workflow.py` for additive
  campaign/version discovery;
- add compact in-memory fixture builders or one tracked literal reference under
  `tools/virtual_workflows/fixtures/` only if canonical source data cannot be
  composed from existing M10/M11 fixtures;
- add `tests/test_virtual_workflow_exploration_m13.py`, extend
  `tests/test_virtual_workflow_exploration.py`,
  `test_virtual_workflow_exploration_runner.py`, and
  `test_virtual_workflow_contract_freeze.py`;
- add Slice 13.1 implementation plan and completion record;
- update only the current Milestone 13 slice line in the master plan after
  implementation is separately authorized.

### Contracts and admitted operations

Freeze all states, facets, transitions, operations, exclusions, oracle IDs,
six sequence identities, seeds, fixture literals, hashes, and seed-tier rules
defined above. Use a campaign-private fixed algorithm, preferably a
SHA-256/counter choice stream, so output is independent of process-global RNG
and Python `random` implementation drift. Do not change the private
`random.Random` behavior of the M8 generator.

Every operation entry must name the existing deterministic case/assertion/test,
literal outcome projection, allowed source/target facets, maximum ledger
expansion, screenshot policy, and whether it is legal or rejected. A missing or
stale oracle reference makes catalog validation fail.

### Budgets and seed behavior

The qualified contract freezes a limit of 18 semantic operations and 80 ledger actions,
three sessions/two rotations, four screenshots, 256 files/48 MiB, a 270-second
scenario deadline/300-second child watchdog, and the compact workload caps per
sequence; six sequences, 1,600 files/320 MiB, 24 screenshots, and 1,800 seconds
per frozen campaign. No SIL artifacts are produced in this slice.

Frozen seeds generate only the six reviewed normalized sequences. Diagnostic
selection requires the explicit tier and seed, is capped at four seeds, and is
excluded from frozen hashes and release classification. Mutation tests must
prove that silently adding seed `1` or `101` to the frozen set fails.

### Tests, validation, evidence, and acceptance

Run focused unit/contract tests for determinism, canonical normalization,
hash stability, state continuity, oracle completeness, operation eligibility,
all budget mutations, seed-tier isolation, fixture identity, campaign listing,
dry-run, v1 compatibility, and rejection of unknown schema/campaign/operation.
No real Qt/system/visible run is authorized in Slice 13.1.

Retain the start-gate record, normalized state/catalog/oracle/frozen sequence
projections, all hashes, dry-run JSON, test output, source fingerprint, and
`git diff --check`. Acceptance requires byte-identical M8 catalogs/plans/hashes,
the exact six proposed seeds covering the planned semantic denominator on
paper, and no executable v2 plan before the start gate is recorded.

Risks are accidental M8 hash drift, encoding outcomes from production
algorithms, admitting an operation without an oracle, positional identity, or
seed-set expansion to hide a coverage gap. Rollback removes the new M13 module,
v2 dispatch, tests, and Slice 13.1 records while leaving M8 and deterministic
Milestones 9-12 untouched. Slice 13.1 depends on the recorded passing
start-boundary gate and has no dependency on later slices.

## Slice 13.2: Legal sequences to authoritative terminal boundaries

### Scope and exclusions

Implement the two legal frozen sequences and reusable state observer. Exercise
real Qt design edits, stock-mode/well/randomization changes, combined
Optimize/Generate, Finalize or Refinalize, matching head staging, calibration
Generate/Select/Apply, session close/reload/activation where assigned, Start,
exact compact execution, and terminal reload. Do not add rejected operations,
aggregation v2, reduction, persistence faults, resume, or optimizer-360 data.

### Call paths and files likely to change

Use the editor, head/calibration, close/reload/activation, Start/dispatch, and
reporting paths defined above. Likely changes are additive branches or generic
wrappers in `actions.py`, `page_drivers.py`, `journey_phases.py`, `journeys.py`,
`assertions.py`, `authoritative_evidence.py`, `editor_reporting.py`, the M13
campaign module, report projection tests, and a new
`tests/system/test_virtual_workflow_m13_exploration_execution.py`. Production
View/Controller/Model/Machine files are not expected to change.

### State, transition, operation, and oracle contracts

The legal sequences must continuously prove observed equality for:

- draft valid/dirty/generated and exact literal M10 design truth;
- prepared zero-progress design/plan/progress/revision identity;
- available/selected/applied keyed calibration and exact M9 count transition;
- reloaded inactive and active zero-progress M11 boundaries;
- progressed/locked and terminal M9/M11 intent/count/persistence truth.

Only accepted operation rows from the admission ledger may execute. Each row
uses its listed M8-M11 deterministic oracle. Legal generation rejects a path
that cannot reach `terminal` within budget.

### Budgets, fixtures, and seed tier

Seeds 13 and 29 are the only frozen legal identities. Each uses at most 18
semantic operations, 80 ledger rows, three sessions/two rotations, four
screenshots, 256 files/48 MiB, four reactions, two stocks, eight intents,
44 droplets, a 270-second scenario deadline, and 300-second watchdog. Direct
offscreen execution uses 1000x; one seed-13 visible representative uses 20x.
Diagnostic legal seeds remain explicit and nonblocking.

### Tests and validation

Run focused state-observer, action, page-driver, phase, assertion, report,
authoritative-evidence, fixture, budget, and contract tests. Run each legal
sequence directly in a fresh process, repeat it with its exact emitted replay,
and run seed 13 visibly plus exact visible replay. Aggregate execution remains
deferred to Slice 13.4.

Every report retains normalized plan/hash, modeled and observed transitions,
operation/oracle IDs, action/assertion ledgers, sessions, screenshots, design/
stock/head/calibration/plan/progress/revision identities and hashes, intents,
commands, completions, drops, terminal reload, source identity, cleanup, and
exact replay command.

Acceptance requires real Qt interaction for every semantic operation, no
unexpected dialog or missing assertion, exact terminal authority and dispatch
evidence, clean teardown, zero budget overrun, and exact replay-stable semantic
projections. Risks include leaking state across sessions, using runtime rows as
identity, accepting prepared instead of terminal, and computing expected counts
from production. Rollback removes the M13 legal journey/driver branches and
tests without changing shared deterministic scenarios. Slice 13.2 depends on
the reviewed Slice 13.1 catalog, hashes, fixture projection, and budget tests.

## Slice 13.3: Illegal and recovery sequences

### Scope and exclusions

Implement the four illegal/recovery frozen sequences. Each deliberately reaches
one or more selected invalid operations through real Qt controls, observes the
literal typed rejection, immediately proves Milestone 12 no-mutation/no-
dispatch, proves base-state continuity, then uses only valid operator actions
on the same authoritative lineage to reach `terminal`.

Do not manufacture a rejection with a disabled control, mutate active files,
load a different good experiment as recovery, dismiss unsafe state by closing,
use cleanup to erase evidence, or add generated persistence/resume/refill
behavior.

### Call paths and files likely to change

Use the rejected-operation path and the same accepted recovery paths as Slice
13.2. Likely changes are narrowly additive in the M13 module, `actions.py`,
`page_drivers.py`, `journey_phases.py`, `journeys.py`, `assertions.py`,
`safeguards.py`, report/evidence projections, M13 unit/system tests, and Slice
13.3 records. Do not change the three M12 catalogs, their literal cases, shared
oracle meaning, or production safeguards.

### State, rejection, recovery, and oracle contracts

- Seed 47 covers selected editor invalidity and one-stock formulation
  rejection before valid edit/two-stock/Generate/Finalize recovery.
- Seed 83 covers a calibration mode/settings mismatch and exact Cancel before
  matching Generate/Select/Apply recovery.
- Seed 131 covers wrong durable head/calibration binding and inspected-inactive
  Start rejection before matching head and explicit activation recovery.
- Seed 197 reaches positive progress, proves selected edit/recalibration and
  active/exchange locks, then continues the existing plan to terminal.

Every rejection records its exact M12 case/assertion ID, code, classification,
dialog/status/button, before/after snapshot hashes, zero new revision,
activation, intent, command, completion, or drop, and unchanged base-state
identity. The next modeled transition begins from that same observed base state.
If the real application guard differs, the sequence fails and a separate defect
plan is required; the oracle is not weakened.

### Budgets, fixtures, and seed tier

The same per-sequence caps apply: 18 semantic operations, 80 ledger actions,
three sessions/two rotations, four screenshots, 256 files/48 MiB, compact
4/2/8/44 workload, 270-second scenario deadline, and 300-second watchdog.
Across these four sequences, caps are 72 semantics, 320 ledger rows, twelve
sessions, eight rotations, sixteen screenshots, 1,024 files, and 192 MiB.
Frozen identities are seeds 47, 83, 131, and 197. Diagnostic failures remain
outside the frozen classification.

### Tests, evidence, and acceptance

Run focused shared-oracle, state-continuity, recovery-edge, exact-dialog,
action-cap, identity, lifecycle, report, and original M12 compatibility tests.
Run each illegal sequence directly in a fresh process and execute its emitted
exact replay. Run visible seed 47 and seed 131 representatives plus exact
visible replays; Slice 13.5 later adds the progressed-lock visible
representative.

Reports retain all legal evidence plus typed rejection snapshots, recovery
lineage, and explicit proof that recovery did not reset or hide unsafe state.
Acceptance requires all shared-oracle checks and terminal checks to pass, no
unexpected dialog, exact replay, and no budget overflow. Risks are baselining
before invalid setup, treating a mismatching staged head as the rejection,
racing an active queue, or recovering onto a different authority. Rollback
removes M13 illegal/recovery branches and tests while retaining every M12 case
and report. Slice 13.3 depends on the reviewed Slice 13.2 observer, accepted
operation paths, terminal oracle, and frozen Slice 13.1 contracts.

## Slice 13.4: Fresh-process aggregation, replay, coverage, and failures

### Scope and exclusions

Implement v2 complete-campaign aggregation, exact original replay, semantic
coverage, diagnostic isolation, and authoritative original-failure retention.
An optional deterministic reducer may be added only if all mandatory behavior
is already complete; otherwise reduction remains deferred.

Do not change report v1 stable semantics unnecessarily, overwrite an original
failure, use reduced output as release evidence, merge diagnostic results into
the frozen gate, or treat seed/action count as coverage.

### Call paths and files likely to change

```text
CLI --exploration design_calibration_lifecycle_v1
-> frozen v2 plan and campaign hash validation
-> sequential fresh child per normalized sequence
-> direct M13 journey and report v1
-> child PID/return code/log/report/hash validation
-> reached-state/transition/operation/rejection extraction
-> semantic coverage v1 evaluation
-> v2 aggregate, summary, replay command, failure index
```

Likely files are `exploration_runner.py`, `exploration_m13.py`,
`semantic_coverage.py`, `tools/run_virtual_workflow.py`, report helpers,
`suite_runner.py` only for generic isolated-child primitives, unit/system tests
for runner/coverage/failure retention, and Slice 13.4 records.

### Aggregation, coverage, replay, and failure contracts

The aggregate validates the exact state-model, operation-catalog,
oracle-ledger, frozen-set, sequence, fixture, source, and campaign hashes. It
continues independent children after a failure to collect coverage but is
fail-closed. Missing/extra/duplicate reports, PID reuse, unsupported return
code, timeout, path escape, hash mismatch, source drift, omitted assertion,
budget overflow, or semantic discontinuity fails the parent.

Semantic coverage reports declared/reached states, facets, transitions,
operations, deterministic oracle IDs, and rejection classes with exact child/
step references. Complete means every declared frozen requirement has at least
one passing authoritative reference. Seed count, action count, or screenshot
count is never coverage.

Every failing normalized sequence is written once under a content-addressed,
non-overwriting original-failure record containing its exact normalized bytes,
hashes, generated fixture identity, reached prefix, report/logs/screenshots,
source identity, cleanup, and exact rerun command. Exact replay always uses
those original normalized bytes; it does not call the generator and hope for
the same result.

If reduction is implemented, it is deterministic, budgeted to at most 32
candidate executions and 900 seconds total, and emits a separate
`diagnostic_derivative` with `derived_from_sequence_sha256`. It cannot overwrite,
rename, mutate, satisfy coverage for, or replace the authoritative original.
Reducer failure has no effect on original replayability.

### Budgets and seed tiers

Enforce all global caps: six children, 108 semantic operations, 480 ledger
rows, 18 sessions/12 rotations, 24 screenshots, 1,600 files/320 MiB,
300 seconds per child, and 1,800 seconds aggregate wall time. Parent plan,
aggregate, coverage, summaries, logs, and failure index are included in the
campaign evidence caps.

Frozen and diagnostic aggregates have different tier identities and output
roots. A diagnostic invocation accepts at most four seeds and produces no
release classification. Unit tests inject a deterministic diagnostic failure
and prove the frozen aggregate/hash/status are byte-identical before and after.

### Tests, validation, evidence, and acceptance

Run unit tests for fresh PID/process isolation, continuation after failure,
termination/kill, path containment, report/hash validation, exact original
replay, semantic coverage completeness/missing/duplicate cases, original-
failure immutability, reducer derivative labeling if present, diagnostic
isolation, and every budget edge/overrun.

Run the complete offscreen frozen aggregate and its emitted exact replay. Run
one selected diagnostic seed and an injected diagnostic-failure system test;
retain both without altering the frozen result. Inspect aggregate/report hashes,
coverage references, logs, cleanup, and rerun commands.

Acceptance requires 6/6 direct children, exact replay of all six normalized
originals, complete semantic coverage, strict caps, unchanged originals,
diagnostic isolation, and M8 aggregate/replay compatibility. Risks are
regenerating instead of replaying, coverage from failed children, evidence
growth after the cap, and accidental shared Qt state. Rollback removes only v2
aggregation/coverage/failure support and the M13 selector; M8 v1 and all child
reports remain readable. Slice 13.4 depends on reviewed direct/replay legal and
illegal sequence evidence from Slices 13.2 and 13.3.

## Slice 13.5: Frozen qualification, visible evidence, regressions, and closeout

### Scope and exclusions

Freeze the final campaign and hashes, run source-current qualification and exact
replays, inspect visible representatives, run deterministic compatibility and
regression gates, update operator documentation, and close Milestone 13. Add no
operation, seed, oracle, state, or budget in this slice. Any source/fixture/
catalog correction restarts the complete Slice 13.5 gate after separate review.

Do not run `pi_stress`, require the complete `host_stress` aggregate to be
green, fix the 384x10 mismatch, or claim physical hardware coverage.

### Call paths and files likely to change

Qualification follows:

```text
frozen list/dry-run/hash audit
-> each sequence direct in a fresh process and exact replay
-> complete aggregate and exact aggregate replay
-> required visible direct/replay representatives
-> diagnostic-isolation proof
-> deterministic M9-12 direct/replay compatibility
-> immutable optimizer-360 direct/replay
-> lifecycle and host-regression direct/replay
-> focused unit/system tests and complete default suite
-> report/hash/screenshot/cleanup audit
-> documentation-only closeout
```

Likely documentation changes are README, the SIL operator runbook, Slice 13.5
plan/completion record, Milestone 13 completion record, and only Milestone 13
status/current-next-action text in the master plan. Code changes are not
expected after qualification starts.

### Frozen contracts and required visible representatives

Freeze and record every version, catalog/ledger/state/fixture/sequence/campaign
hash, exact seed set/order, semantic coverage denominator, source fingerprint,
manifest hash, action/assertion set, and budget.

Visible Windows direct and exact replay are required for:

- `seed_13_legal_design_calibration_terminal`;
- `seed_47_illegal_editor_recovery_terminal`;
- `seed_131_illegal_identity_activation_recovery_terminal`;
- `seed_197_illegal_progress_lock_recovery_terminal`.

Each visible run uses at most four screenshots and the same 18/80 action,
three-session/two-rotation, 48 MiB/256-file, 270/300-second, and compact workload
caps. The six-child frozen aggregate retains the 24-screenshot, 320 MiB/1,600-
file, and 1,800-second limits. Visible mode uses 20x; offscreen uses 1000x.

### Exact final qualification commands

After implementation, from a clean source checkpoint, run:

```powershell
git status --short --branch
git rev-parse HEAD
git diff --check

.\env\Scripts\python.exe tools\run_virtual_workflow.py --list explorations
.\env\Scripts\python.exe tools\run_virtual_workflow.py --exploration editor_prepared_guard_v1 --dry-run
.\env\Scripts\python.exe tools\run_virtual_workflow.py --exploration design_calibration_lifecycle_v1 --dry-run

.\env\Scripts\python.exe tools\run_virtual_workflow.py --exploration design_calibration_lifecycle_v1 --sequence seed_13_legal_design_calibration_terminal --output-root verification_reports\milestone_13_final\direct --speed-multiplier 1000 --timeout-seconds 270 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --exploration design_calibration_lifecycle_v1 --sequence seed_29_legal_refinalize_reload_terminal --output-root verification_reports\milestone_13_final\direct --speed-multiplier 1000 --timeout-seconds 270 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --exploration design_calibration_lifecycle_v1 --sequence seed_47_illegal_editor_recovery_terminal --output-root verification_reports\milestone_13_final\direct --speed-multiplier 1000 --timeout-seconds 270 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --exploration design_calibration_lifecycle_v1 --sequence seed_83_illegal_calibration_recovery_terminal --output-root verification_reports\milestone_13_final\direct --speed-multiplier 1000 --timeout-seconds 270 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --exploration design_calibration_lifecycle_v1 --sequence seed_131_illegal_identity_activation_recovery_terminal --output-root verification_reports\milestone_13_final\direct --speed-multiplier 1000 --timeout-seconds 270 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --exploration design_calibration_lifecycle_v1 --sequence seed_197_illegal_progress_lock_recovery_terminal --output-root verification_reports\milestone_13_final\direct --speed-multiplier 1000 --timeout-seconds 270 --qt-platform offscreen

.\env\Scripts\python.exe tools\run_virtual_workflow.py --exploration design_calibration_lifecycle_v1 --output-root verification_reports\milestone_13_final\aggregate --speed-multiplier 1000 --timeout-seconds 270 --qt-platform offscreen

$env:QT_QPA_PLATFORM='windows'
.\env\Scripts\python.exe tools\run_virtual_workflow.py --exploration design_calibration_lifecycle_v1 --sequence seed_13_legal_design_calibration_terminal --output-root verification_reports\milestone_13_final\visible --speed-multiplier 20 --timeout-seconds 270 --visible
.\env\Scripts\python.exe tools\run_virtual_workflow.py --exploration design_calibration_lifecycle_v1 --sequence seed_47_illegal_editor_recovery_terminal --output-root verification_reports\milestone_13_final\visible --speed-multiplier 20 --timeout-seconds 270 --visible
.\env\Scripts\python.exe tools\run_virtual_workflow.py --exploration design_calibration_lifecycle_v1 --sequence seed_131_illegal_identity_activation_recovery_terminal --output-root verification_reports\milestone_13_final\visible --speed-multiplier 20 --timeout-seconds 270 --visible
.\env\Scripts\python.exe tools\run_virtual_workflow.py --exploration design_calibration_lifecycle_v1 --sequence seed_197_illegal_progress_lock_recovery_terminal --output-root verification_reports\milestone_13_final\visible --speed-multiplier 20 --timeout-seconds 270 --visible
Remove-Item Env:QT_QPA_PLATFORM

.\env\Scripts\python.exe tools\run_virtual_workflow.py --exploration design_calibration_lifecycle_v1 --seed-tier diagnostic --diagnostic-seed 1 --output-root verification_reports\milestone_13_final\diagnostic --speed-multiplier 1000 --timeout-seconds 270 --qt-platform offscreen
```

Immediately after each of the six direct runs, the complete aggregate, the four
visible runs, and the diagnostic run, execute its retained
`run.replay_command` verbatim. Original frozen replay must load the retained
normalized sequence bytes and verify their SHA-256; it must not regenerate from
the seed. Inspect all four visible original and replay screenshot sets.

Run deterministic compatibility commands:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py --exploration editor_prepared_guard_v1 --output-root verification_reports\milestone_13_final\m8_compatibility --speed-multiplier 1000 --timeout-seconds 120 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix calibration_requantization_v1 --output-root verification_reports\milestone_13_final\m9_requantization --seed 1 --speed-multiplier 1000 --timeout-seconds 120 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix mixed_mode_calibration_v1 --output-root verification_reports\milestone_13_final\m9_mixed --seed 1 --speed-multiplier 1000 --timeout-seconds 120 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix experiment_design_pairwise_v1 --output-root verification_reports\milestone_13_final\m10_design --seed 1 --speed-multiplier 1000 --timeout-seconds 120 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --scenario randomized_calibration_reload_execution_v1 --output-root verification_reports\milestone_13_final\m11_joined --seed 1 --speed-multiplier 1000 --timeout-seconds 240 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix editor_safeguards_v1 --output-root verification_reports\milestone_13_final\m12_editor --seed 1 --speed-multiplier 1000 --timeout-seconds 240 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix execution_preflight_safeguards_v1 --output-root verification_reports\milestone_13_final\m12_preflight --seed 1 --speed-multiplier 1000 --timeout-seconds 240 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix authoritative_persistence_safeguards_v1 --output-root verification_reports\milestone_13_final\m12_persistence --seed 1 --speed-multiplier 1000 --timeout-seconds 240 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --scenario optimizer_360_calibration_reload_execution_v1 --output-root verification_reports\milestone_13_final\m11a_optimizer360 --seed 1 --speed-multiplier 1000 --timeout-seconds 900 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --suite lifecycle --output-root verification_reports\milestone_13_final\lifecycle --seed 1 --speed-multiplier 1000 --timeout-seconds 240 --qt-platform offscreen
.\env\Scripts\python.exe tools\run_virtual_workflow.py --suite host_regression --output-root verification_reports\milestone_13_final\host_regression --seed 1 --speed-multiplier 1000 --timeout-seconds 240 --qt-platform offscreen
```

Execute every emitted compatibility replay verbatim. Do not run the complete
`host_stress` aggregate. Record optimizer-360 direct/replay separately with its
immutable hashes and exact totals so the known 384x10 issue cannot be confused
with Milestone 13.

Run focused and complete automated gates:

```powershell
.\env\Scripts\python.exe -m pytest -q tests\test_virtual_workflow_exploration.py tests\test_virtual_workflow_exploration_runner.py tests\test_virtual_workflow_exploration_m13.py tests\test_virtual_workflow_exploration_runner_m13.py tests\test_virtual_workflow_m13_interaction_cases.py tests\test_virtual_workflow_actions.py tests\test_virtual_workflow_page_drivers.py tests\test_virtual_workflow_journey_phases.py tests\test_virtual_workflow_assertions.py tests\test_virtual_workflow_safeguards.py tests\test_virtual_workflow_authoritative_evidence.py tests\test_virtual_workflow_report.py tests\test_virtual_workflow_manifest.py tests\test_virtual_workflow_matrices.py tests\test_virtual_workflow_matrix_runner.py tests\test_virtual_workflow_suite_runner.py tests\test_virtual_workflow_contract_freeze.py
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle tests\system\test_virtual_workflow_m13_exploration_execution.py tests\system\test_virtual_workflow_m13_exploration_aggregate.py tests\system\test_virtual_workflow_exploration_execution.py tests\system\test_virtual_workflow_matrix_execution.py tests\system\test_virtual_workflow_experiment_design_matrix.py tests\system\test_virtual_workflow_randomized_calibration_lifecycle.py tests\system\test_virtual_workflow_optimizer_360_calibration_lifecycle.py tests\system\test_virtual_workflow_editor_safeguards.py tests\system\test_virtual_workflow_execution_preflight_safeguards.py tests\system\test_virtual_workflow_persistence_safeguards.py tests\system\test_virtual_workflow_lifecycle.py tests\system\test_virtual_workflow_suite_execution.py
.\env\Scripts\python.exe -m pytest -q
git diff --check
git status --short --branch
```

The default suite command requires a tool timeout of at least 900000 ms.
Analysis-pipeline tests run only if analysis-pipeline code changes:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-analysis-pipeline tests\test_plate_reader_analysis.py
```

### Reports, hashes, evidence, and acceptance

Retain every normalized plan, state/transition/operation/oracle row, fixture and
sequence identity, hashes, direct/aggregate/replay report, semantic coverage
document, visible screenshot, child PID/return code/log, source and manifest
identity, design/stock/head/calibration/plan/progress/revision evidence,
rejection snapshot, dispatch/intents/completions/drops, original failure,
diagnostic record, exact rerun command, and cleanup result. No automatic cleanup
runs at closeout.

Milestone 13 is complete only when:

- generator determinism and all frozen hashes are stable;
- modeled and observed state are continuous and every action/session/
  screenshot/evidence/runtime cap is enforced;
- the six-sequence frozen campaign has complete semantic coverage over every
  declared state, required transition, admitted operation, oracle, and
  rejection class;
- every frozen original sequence passes direct execution and exact replay;
- legal paths prove exact terminal persistence, identity, lifecycle, dispatch,
  simulator, and cleanup evidence;
- illegal paths prove exact rejection, immediate no-mutation/no-dispatch,
  unchanged base state, valid same-authority recovery, terminal persistence,
  and cleanup;
- original generated-failure retention and exact original replay pass, and any
  reducer derivative remains separate;
- diagnostic failures are retained/triaged but cannot change the frozen gate;
- all required visible direct/replay representatives pass and are inspected;
- deterministic Milestones 9-12 direct/replay compatibility passes;
- the selected immutable optimizer-360 direct/replay control passes with
  unchanged frozen hashes, three sessions, revisions 1-8, 1,800 intents, and
  46,208 droplets;
- assigned lifecycle and host-regression direct/replay gates pass;
- focused unit/system tests and the complete default Python suite pass;
- documentation records exact commands, evidence, limitations, risks,
  exclusions, and rollback; and `git diff --check` passes.

Risks at closeout are source drift after evidence capture, accepting stale or
diagnostic evidence, omitted failed children, regenerated rather than original
replay, coverage counted from failures, silent budget increases, or conflating
the 384x10 aggregate issue with a Milestone 13 result. Any source correction
restarts Slice 13.5. Rollback removes the new campaign, v2 selector/runner/
coverage/reduction support, M13 fixtures/tests, and M13 documentation while
retaining M8, all deterministic M9-12/11A contracts, and historical evidence.
Slice 13.5 depends on reviewed Slices 13.1-13.4 and an unchanged final source
checkpoint throughout qualification.

## Independently reviewable slice sequence

1. Versioned state model, operation catalog, oracle ledger, seed tiers, and
   budgets.
2. Legal generated sequences reaching valid authoritative terminal boundaries.
3. Illegal and recovery sequences proving fail-closed behavior and valid
   same-authority recovery.
4. Fresh-process aggregation, exact original replay, semantic coverage,
   original-failure preservation, diagnostic isolation, and optional
   derivative-only reduction.
5. Frozen-campaign qualification, visible representatives, deterministic
   compatibility/regressions, documentation, and closeout.

Each slice begins only after the prior slice plan, completion record, frozen
hashes, test result, `git diff --check`, and reviewed commit boundary are
confirmed. One milestone slice is one small descriptive commit after separate
authorization. A material production defect, schema incompatibility, missing
oracle, data-preservation ambiguity, or need to expand safety scope stops the
slice for a separately reviewed plan.

## Unresolved decisions and required review points

The plan deliberately leaves only these bounded decisions for Slice 13.1:

1. Confirm that seeds `13, 29, 47, 83, 131, 197` generate reviewed normalized
   sequences that cover the complete admitted semantic denominator within all
   budgets. If not, stop and revise the planned seed set; do not silently add a
   seed.
2. Confirm whether `array.start_while_active_via_ui` and
   `head.attempt_unsafe_exchange_via_ui` can be observed deterministically in a
   compact real-Qt sequence without racing the queue. If not, exclude them from
   v1 before catalog freeze and retain their M12 direct oracles.
3. Decide whether the optional reducer provides enough diagnostic value after
   mandatory replay/failure retention is complete. Deferral is preferred over
   weakening or delaying the release gate.
4. Confirm whether the compact fixture can be composed entirely in memory from
   frozen M10/M11 literals. A new tracked fixture is allowed only when it owns
   literal data and does not change existing fixtures.

These are not permissions to broaden the operation catalog during
implementation. Reagent-row add/remove, generated persistence faults, resume,
refill, physical behavior, and hardware remain excluded without a new reviewed
prerequisite and plan change.

## Milestone 13 execution-goal objective

The separately authorized implementation used this exact objective:

> Implement and qualify Milestone 13 of the SIL interactive simulation and
> composable workflows plan in five independently reviewed slices by adding the
> separate versioned `design_calibration_lifecycle_v1` bounded seeded campaign,
> reusing only deterministic Milestone 9-12 operation oracles and the Milestone
> 12 shared no-mutation/no-dispatch safeguard, proving legal and illegal/
> recovery real-Qt sequences reach exact authoritative terminal boundaries,
> preserving Milestone 8 compatibility and every original generated failure,
> enforcing the frozen/diagnostic seed separation and all numeric budgets, and
> retaining the immutable Milestone 11A optimizer-360 direct/replay control,
> while excluding firmware, protocol, physical hardware, refill/resume,
> active-authority mutation, unattended scheduling, `pi_stress`, and the known
> 384x10 stress-fixture mismatch.
