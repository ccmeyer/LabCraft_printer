# Milestone 7 Slice 3.5 — Authoritative-Evidence Consolidation

Status: `implemented — approved and completed on 2026-08-06`

Planning baseline: `f8bba35b83593c5b4dfd7a70844c5463d1404f45`, plus the
intentionally uncommitted and validated Milestone 7 Slice 3 worktree.

## Objective

Perform one bounded, behavior-preserving consolidation before migrating
another lifecycle. Replace repeated authoritative-bundle reads, filesystem
inventories, transition comparisons, editor action-ledger checks, and editor
report-payload assembly with small typed helpers that are used by the existing
composed editor journeys and exercised by the existing authoritative
reload/resume and post-start lock/copy validators.

The result must make the next migrations smaller without creating a generic
workflow language. Slice 3.5 adds no workflow, action, page-driver operation,
fixture, registry entry, assertion ID, screenshot requirement, or capability
claim. It does not migrate soft stop/resume, authoritative reload/resume, or
post-start lock/copy to composition. It does not begin matrices, seeded
exploration, fault injection, performance work, Pi operation, firmware or
protocol work, or hardware operation.

No file under `FreeRTOS-interface/` or `firmware/` is in scope.

## Audit Baseline

- HEAD remains the completed Slice 2.5 commit. The completed Slice 3
  implementation, tests, plan, README/roadmap updates, and completion record
  are present as intentional uncommitted changes.
- The retained Slice 3 baseline, visible, and replay reports are present on
  this computer. Their recorded stable projections can seed the pre-refactor
  parity set, but implementation must capture fresh references for every path
  changed by Slice 3.5.
- `assertions.py` currently contains separate readers for CSV rows, SHA-256,
  audit rows, runtime assignments, initial prepared state, refinalized state,
  and reload state. `editor_prepared_revision_assertions()` is roughly 350
  lines and repeats the same file-hash inventory twice to prove its own reads
  were non-mutating.
- `editor_scenarios.py` has another set of CSV, hash, audit, runtime-assignment,
  and directory-snapshot helpers. Its prepared-revision and post-start
  lock/copy branches independently reconstruct much of the same bundle.
- `scenarios.py` has a third file inventory and audit reader. The authoritative
  reload branch performs before-close, after-close, loaded, and activated
  comparisons inline.
- `journeys.py` has two editor-specific `ComposedReportPayload` builders with
  repeated workload, status, cleanup, persistence, queue, and limitation
  assembly.
- `editor_create_finalize_assertion()` and the prepared-revision assertion
  each implement their own ordered action/surface/status scan. The revision
  scan selects the last matching rows, which is correct for the frozen journey
  but is not a reusable explicit phase boundary.

## Call Paths

Slice 3 composed prepared revision:

```text
CLI / generic registry dispatch
  -> JourneyExecutor
  -> typed editor phases
  -> ExperimentEditorDriver
  -> bounded QTest controls
  -> View / ExperimentDesignDialog
  -> Controller where the production UI uses it
  -> Model / ExperimentModel authoritative writers
  -> read-only composed assertions and report payload
```

Legacy authoritative reload/resume:

```text
legacy scenario runner
  -> normal Qt print/stop controls and editor reload controls
  -> Controller -> Model -> SimulatedMachine
  -> read-only paused/loaded/activated/terminal validators
```

Legacy post-start lock/copy:

```text
legacy editor runner
  -> normal Qt editor controls
  -> View / ExperimentDesignDialog -> Model / ExperimentModel
  -> read-only locked-source/copy validators
```

Slice 3.5 changes only the final read-only evidence and report-composition
layers. It must not change any UI, Controller, Model, simulated-comms, or
firmware call. The editor journeys have no comms or firmware handler; the
reload lifecycle ends at `SimulatedMachine`, not physical hardware.

## Frozen Design Decisions

1. **Behavior and evidence are frozen.** Preserve scenario/version/workload
   identities, fixture bytes and hashes, ordered action IDs and interaction
   surfaces, assertion IDs and decisions, milestone/screenshot keys, report-v1
   shape and stable values, failure classification, replay command, retention,
   and teardown.
2. **Snapshot capture is read-only and JSON-safe.** The shared snapshot may
   contain only frozen scalar/tuple/mapping values. It may not retain a live Qt
   widget, `Model`, `ExperimentModel`, `ExecutionPlan`, callback, or other
   mutable production object. Capture must not load/activate/repair execution,
   write a file, advance simulated time, or dismiss a dialog.
3. **Capture and policy remain separate.** The snapshot reports facts; typed
   expectations and comparison helpers produce named checks. Assertion
   adapters retain scenario-specific assertion IDs and report evidence. A
   snapshot must not decide that a lifecycle passed.
4. **Typed Python, not a DSL.** Use frozen dataclasses, enums where field names
   need validation, and explicit functions. Do not add YAML, expression
   evaluation, reflection-based property paths, arbitrary dictionaries of
   callables, or a generic state-machine engine.
5. **Prove reuse now without migrating runners.** Both composed editor
   journeys consume the shared snapshot. The existing legacy authoritative
   reload and post-start lock/copy validators use the same inventory/audit and
   snapshot comparison primitives through compatibility adapters, while their
   orchestration and report contracts remain legacy and unchanged.
6. **Action checks use an explicit window.** A reusable typed action-sequence
   assertion receives the exact ledger start/end or an already bounded row
   sequence. It must compare order, status, and surface and fail on missing,
   extra, duplicate, or non-UI rows. It must not find a convenient subsequence
   in the whole run.
7. **Editor reporting is one bounded builder.** A typed editor lifecycle report
   specification assembles the scenario-specific `ComposedReportPayload` for
   create/finalize and rename/refinalize. `ComposedReportAdapter` and report-v1
   remain unchanged.
8. **Targeted validation only.** Run the focused unit, lifecycle, failure,
   direct, visible, replay, and parity gates below. Defer the complete Python
   suite until the final Milestone 7 validation, as requested.

## Proposed Contracts

`tools/virtual_workflows/authoritative_evidence.py` will own:

- a frozen `AuthoritativeBundleSnapshot` with normalized design metadata and
  canonical hash; plan identity/revision/state/lock reason and well mappings;
  history identities; eligibility; decoded progress totals/completion;
  resume presence/state/reference/intents; calibration counts; runtime
  assignments; key/concentration rows; audit rows; authoritative file hashes;
  and a deterministic directory inventory;
- a small capture specification that selects already-existing optional
  artifacts without changing missing-file semantics;
- `capture_authoritative_bundle(...)`, `read_csv_rows(...)`,
  `read_audit_rows(...)`, and `snapshot_directory(...)` as the only
  implementations of those reads in virtual-workflow code;
- typed comparison results containing `checks`, `failed_checks`, and bounded
  evidence for exact equality, allowlisted file changes, plan identity,
  prepared replacement, and source immutability. Only comparison forms used by
  the four current consumers may be implemented.

`tools/virtual_workflows/assertions.py` will retain public assertion IDs and
scenario-specific semantic expectations. It will add one reusable typed
ordered-action assertion and adapt snapshot/comparison results into the
existing assertion evidence. Initial/refinalized capture will no longer place
private `_plan` or `_design` objects in `JourneyRuntime.observations`.

`tools/virtual_workflows/editor_reporting.py` will own a frozen
`EditorLifecycleReportSpec` and `build_editor_lifecycle_payload(...)`. The
specification supplies only the differing identity, workload, persistence
sections, and limitations; common status, cleanup, zero-print queue, and
payload construction occur once.

## Measurable Consolidation Gates

- `_editor_csv_rows`, `_editor_file_sha256`, `_editor_audit_rows`, and
  `_editor_runtime_assignments` are removed from `assertions.py`;
- `_csv_rows`, `_file_sha256`, `_audit_rows`, `_runtime_assignments`, and
  `_directory_file_snapshot` are removed from `editor_scenarios.py`;
- `_file_inventory` and `_read_audit_rows` are removed from `scenarios.py`;
- one shared directory inventory preserves the legacy rich
  `{sha256, size_bytes}` form and can project the editor `{inventory, sha256}`
  form without rereading files;
- prepared capture, refinalized validation, reload validation, locked-source
  validation, and editable-copy validation all consume shared snapshot facts
  or comparison primitives;
- `editor_prepared_revision_assertions()` is at most 180 nonblank,
  non-comment lines, excluding reusable check-group declarations;
- each editor payload adapter in `journeys.py` is at most 25 nonblank,
  non-comment lines and delegates to the shared builder;
- the existing consumer files lose at least 450 physical lines and both new
  shared modules are recorded separately. Implementation measured a 482-line
  consumer reduction and a 633-line shared foundation, a one-time net increase
  of 151 physical lines. This measured amendment replaces the proposed
  no-net-growth gate: forcing the typed snapshot/report contracts below that
  number would require dense formatting or removal of validation rather than
  further scenario-family consolidation;
- no action/page-driver/phase/registry/manifest/fixture/report schema changes
  occur, and no scenario-specific conditional is added to a shared helper;
- stable report projections for all four affected workflows match their fresh
  pre-refactor references outside the already documented volatile fields.

Line gates are review aids. They must not be met by dense formatting, hidden
side effects, or opaque generic dictionaries.

## Implementation Steps

1. Capture fresh fixed-seed reference reports for composed editor
   create/finalize, composed prepared rename/refinalize, legacy authoritative
   reload/resume, and legacy post-start lock/copy. Freeze stable report,
   ordered action/assertion, milestone, screenshot, persistence, failure, and
   teardown projections before changing runtime code.
2. Add the typed JSON-safe authoritative snapshot, shared readers, deterministic
   directory inventory, and bounded comparison results. Unit-test missing and
   malformed artifacts, deterministic ordering, allowlisted changes, plan
   identity, source immutability, and a before/after hash proving capture is
   read-only.
3. Add the explicit-window ordered-action assertion. Record the prepared
   revision phase's ledger start in journey observations, then refactor the two
   composed editor action and authoritative-bundle assertions to use the new
   sequence/snapshot contracts while preserving every public assertion ID and
   evidence key.
4. Replace only the duplicated read/snapshot/comparison mechanics in the
   legacy authoritative reload and post-start lock/copy validators. Keep their
   action drivers, branches, orchestration, milestone names, report builders,
   and public entry points unchanged; use small projections where their legacy
   evidence shape differs from the typed snapshot.
5. Add the typed editor lifecycle report builder and reduce both editor payload
   adapters in `journeys.py` to specifications plus delegation. Preserve
   `ComposedReportPayload`, report-v1, persistence section names, limitations,
   and pass/partial behavior byte-for-byte in stable projection.
6. Run focused unit, source-shape, composed/legacy success, and existing
   controlled-failure tests. Measure the concision gates and inspect the diff
   for hidden mutations, direct Model writes, interaction-surface drift, or a
   new scenario-specific framework branch.
7. Run the four workflows directly, run one visible post-start lock/copy case
   and its exact emitted replay, and compare all post-refactor stable
   projections with Step 1. Inspect screenshots, action/assertion ledgers,
   authoritative hashes, retained failure evidence, teardown, and absence of
   session locks.
8. Update README and the roadmap, record exact before/after line counts,
   validation results, retained evidence roots, risks, and deferred full-suite
   status in the Slice 3.5 completion record, then stop for approval before
   planning Slice 4.

## Exact Implementation File Set

New files:

- `tools/virtual_workflows/authoritative_evidence.py`
- `tools/virtual_workflows/editor_reporting.py`
- `tests/test_virtual_workflow_authoritative_evidence.py`
- `tests/test_virtual_workflow_editor_reporting.py`
- `docs/sil_interactive_simulation_milestone_7_slice_3_5_completion_record.md`

Modified files:

- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/editor_scenarios.py`
- `tools/virtual_workflows/scenarios.py`
- `tests/test_virtual_workflow_assertions.py`
- `tests/test_virtual_workflow_contract_freeze.py`
- `README.md`
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- this plan

The existing system-test files listed below are validation inputs and are not
expected to change. No action, page-driver, phase, registry, manifest, fixture,
generic report, production MVC, simulator, Pi, firmware, protocol, or hardware
file may change. If implementation needs another file, stop and amend this
plan before editing it.

## Targeted Automated Gates

Run the focused unit and static contract set:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_authoritative_evidence.py `
  tests\test_virtual_workflow_editor_reporting.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_composition.py `
  tests\test_virtual_workflow_report.py `
  tests\test_virtual_workflow_contract_freeze.py
```

Run the affected composed and legacy success/failure paths:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_editor_composed.py `
  tests\system\test_virtual_workflow_editor_refinalize_composed.py `
  tests\system\test_virtual_workflow_editor_lifecycle.py `
  tests\system\test_virtual_workflow_editor_post_start_lifecycle.py `
  tests\system\test_virtual_workflow_authoritative_reload_lifecycle.py
```

Run adjacent authoritative persistence contracts because the new snapshot
reads these formats:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_initial_execution_plan_integration.py `
  tests\test_authoritative_execution_load.py `
  tests\test_execution_artifact_policy.py `
  tests\test_execution_progress_store.py `
  tests\test_execution_resume_store.py `
  tests\test_execution_calibration_store.py
```

Finish with:

```powershell
.\env\Scripts\python.exe -m py_compile `
  tools\virtual_workflows\authoritative_evidence.py `
  tools\virtual_workflows\editor_reporting.py `
  tools\virtual_workflows\assertions.py `
  tools\virtual_workflows\journeys.py `
  tools\virtual_workflows\editor_scenarios.py `
  tools\virtual_workflows\scenarios.py
.\env\Scripts\python.exe tools\run_virtual_workflow.py --help
git diff --check
git status --short
```

Do not run `pytest -q` without a focused path list in Slice 3.5. The complete
suite remains the final Milestone 7 validation gate.

## Direct, Visible, Replay, And Parity Gates

Before and after the refactor, run fixed-seed direct cases into separate
`milestone7-slice3-5-baseline` and `milestone7-slice3-5-post` roots:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py --scenario experiment_editor_create_finalize_v1 --output-root <root> --seed 1 --timeout-seconds 180
.\env\Scripts\python.exe tools\run_virtual_workflow.py --scenario experiment_editor_prestart_rename_refinalize_v1 --output-root <root> --seed 1 --timeout-seconds 180
.\env\Scripts\python.exe tools\run_virtual_workflow.py --scenario authoritative_reload_resume_24_v1 --output-root <root> --seed 1 --timeout-seconds 300
.\env\Scripts\python.exe tools\run_virtual_workflow.py --scenario experiment_editor_post_start_lock_v1 --output-root <root> --seed 1 --timeout-seconds 180
```

Run post-start lock/copy once with `--visible`, then execute the exact replay
command emitted by that report. This is the broadest shared-snapshot consumer;
its source directory must remain byte-identical while its editable copy gains
a fresh prepared execution identity.

Compare stable projections for:

- scenario/workload/version, fixture SHA-256, and replay arguments;
- ordered action IDs, statuses, interaction surfaces, assertion decisions,
  milestones, screenshot keys, dialogs, errors, and classification;
- design/plan/progress/resume/calibration identities and states;
- runtime assignments, key/concentration rows, audit event sequences,
  directory inventories, hashes, allowlisted changes, archive evidence, and
  source immutability;
- persistence section names/values, cleanup result, retained-root policy, and
  absent session lock.

Only timestamps, measured durations, generated paths, run/session/application
UUIDs, and hashes that necessarily contain those identities may differ. Any
other difference fails the gate unless this plan is amended before acceptance.

## Risks And Mitigations

- **Read-only helper mutates or activates runtime state:** hash all observed
  files before/after capture, assert runtime-active state is unchanged, and
  prohibit commands, callbacks, Qt interaction, and persistence writers in the
  new module.
- **One snapshot becomes an oversized universal model:** include only facts
  required by the four current consumers; reject unused extension hooks and
  defer new lifecycle facts until a migration actually needs them.
- **Legacy evidence drifts during projection:** retain fresh pre-refactor
  reports and compare stable nested persistence values, not only top-level
  report fields.
- **Action subsequence gives a false UI claim:** require an explicit ledger
  window and exact order/status/surface equality, plus the existing report
  interaction-surface validator.
- **Missing artifacts are normalized away:** snapshot capture records absence
  explicitly and fails closed when a required artifact is missing or malformed.
- **Code is moved rather than consolidated:** enforce one reader/inventory
  implementation, active consumers in both composed and legacy paths, the
  function line gates, and no net touched-runtime growth.
- **Prior uncommitted milestone work is lost:** edit only the stated files and
  never use reset, checkout, clean, or broad generated rewrites.

## Rollback

Before implementation, retain the fresh baseline reports. If a gate fails,
revert only the Slice 3.5 hunks in the four runtime consumers, remove the two
new modules and their tests, and restore the Slice 3 versions of README and the
roadmap. The composed editor journeys and all legacy runners then continue
through their current validated implementations.

Do not revert or delete the uncommitted Slice 3 implementation, fixtures,
retained reports, capability manifest, page-driver/action work, or earlier
milestone documents. No production, firmware, protocol, Pi, or hardware
rollback is required.

## Approval Gate

This plan was approved and implemented within the exact file set, eight steps,
behavior-preserving evidence/report consolidation, and targeted-test policy.
The measured code-shape amendment above is recorded explicitly in the
completion record. No workflow, production behavior, or report/schema change
was added. Slice 4 remains unimplemented.

## Approved Focused-Correction Amendment

Before Slice 4 planning, the retained visible post-start evidence exposed a
production dialog lifecycle defect at this call path:

```text
Duplicate button
  -> ExperimentDesignDialog._on_duplicate_design()
  -> EditableCopyNameDialog
  -> ExperimentModel.duplicate_design_from() only after acceptance
```

Qt's `QInputDialog` modal layout replaced the requested 640 px dialog minimum
with its computed 502 px minimum after `showEvent()` and its zero-delay
callback. The dialog remained 640 px wide, so a monkeypatched pre-`exec()` unit
test did not detect the non-persistent constraint. This amendment authorizes
only:

1. retaining the existing 640 px dialog and 480 px name-field minimums across
   `QEvent.LayoutRequest` in `FreeRTOS-interface/View.py`;
2. adding a real-modal-loop regression to
   `tests/test_experiment_designer_interlock.py`;
3. running the focused dialog/interlock, action, post-start SIL, and one visible
   post-start gate; and
4. updating this plan, the Slice 3.5 completion record, and roadmap status.

No action, page-driver, scenario, fixture, report schema, protocol, simulator,
firmware, Pi, or hardware behavior is in scope. Rollback removes the dialog
event override and its lifecycle regression, then restores the pre-correction
documentation wording.
