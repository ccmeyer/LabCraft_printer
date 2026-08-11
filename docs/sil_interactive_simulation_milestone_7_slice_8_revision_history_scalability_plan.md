# Milestone 7 Slice 8 Revision-History Scalability Plan

Status: `implemented and performance-verified; visible rack gate blocked`

## Objective

Remove the revision-count-dependent synchronous pause from each cached
calibration commit while preserving the existing immutable-history,
authoritative-file conflict, atomic-write, and partial-commit recovery
contracts. This is a focused Slice 8 remediation, not a general persistence
refactor.

The acceptance target is the existing unchanged Slice 8 contract: the
384-well, ten-stock composed journey must complete all 3,840 operations with
no failed action, starvation, unexpected dialog, or event-loop gap greater
than 1,000 ms. Thresholds will not be raised to make the run pass.

## Evidence And Cause

The corrected diagnostic run retained at
`verification_reports/milestone7-slice8-diagnostic-closeout/20260807T181633371835Z_composed/report.json`
completed all 3,840 operations without queue starvation or a failed action,
but recorded a 1,064.585 ms event-loop gap. The overlapping
`pass_start.commit_revision` phase took 347.510 ms during pass 10.

The synchronous call path was:

```text
Calibration page Apply button
  -> CalibrationClasses.View._apply_previewed_droplet_volume()
  -> ExperimentModel.apply_droplet_volume_for_option()
     or ExperimentModel.apply_fill_droplet_volume()
  -> ExperimentModel.apply_execution_calibration()
  -> ExperimentModel._commit_plan_revision()
  -> persist_immutable_revision(previous)
  -> persist_immutable_revision(candidate)
  -> validate_revision_history()
  -> load every revision_*.json
  -> _restore_authoritative_session_after_full_revision()
  -> _refresh_authoritative_execution_bundle()
  -> inspect_authoritative_execution()
  -> validate_revision_history()
  -> load every revision_*.json again
```

This persistence branch goes directly from the calibration View to the
experiment Model. After it returns, the View separately asks the Controller to
apply pulse-width/pressure settings through the existing machine command path.
That Controller -> machine communication -> firmware path is downstream of the
measured revision pause and is not changed by this plan.

Every revision contains the complete 384-well plan. Re-reading every prior
revision at each pass therefore makes calibration-start work grow with both
plan size and revision count. The isolated 384-completion persistence
characterization completed in 4.009 seconds with a 12.573 ms worst individual
completion, so normal per-well durability is not the cause.

The repository already has the appropriate bounded model for lock and
printer-head-binding successors:
`prepare_authoritative_print_pass()` validates one successor against the
in-memory `AuthoritativeExecutionBundle.history`, guards all authoritative
file identities before persistence, performs the same atomic writes, checks
the resulting identities and exact revision-name append, and advances the
active session without reloading old revision bodies.

## Design Decision

Add a calibration-specific cached transaction that follows the established
pass-start transaction pattern. Do not memoize `validate_revision_history()`
globally and do not persist a new cache or digest file.

The cached path is allowed only when all of these facts are true:

- an active authoritative runtime session exists and has no synchronization
  error;
- the session bundle is valid, is not a migrated legacy execution, and its
  latest plan exactly equals the `previous_plan` being calibrated;
- the existing authoritative-file identities and ordered immutable revision
  names still match the session snapshot;
- the candidate is exactly the next valid successor when checked by
  `advance_authoritative_execution_revision()` against the already validated
  in-memory history;
- the updated calibration sidecar contains the referenced record and keeps
  the same plan identity;
- the next immutable filename does not already exist.

The transaction will preserve the existing durable write order: calibration
sidecar, immutable candidate revision, current plan mirror, progress revision,
resume revision when present, and exports. It will then require the observed
revision-name set to be exactly the old ordered set plus the expected
successor and will reject any unexpected identity change. Only after all
writes and checks succeed will it install the advanced bundle/session.

This produces history-independent append validation: prior revision JSON
bodies are not reopened on a healthy cached commit. The current plan-sized
successor validation, target recalculation, serialization, atomic replacement,
and `fsync` remain synchronous and unchanged.

If no trustworthy session is available, or if a previous attempt left a
synchronization error, the existing full validation/recovery path remains the
only path. Any exception after the first durable write invalidates the session,
sets the synchronization error, and requires the existing explicit recovery
and full-history validation before another mutation. There is no permissive
fallback after an external-file conflict.

Full-history validation remains mandatory on process load, explicit runtime
activation, partial-commit recovery, legacy migration inspection, and terminal
closeout. Thus a terminal report still proves the complete immutable chain;
the optimization only removes redundant validation of an unchanged prefix
during a live, guarded session.

## Files To Touch During Implementation

Production and SIL instrumentation:

- `FreeRTOS-interface/Model.py`
  - add the guarded calibration append transaction and install the advanced
    authoritative session only after successful persistence;
  - keep `_commit_plan_revision()` and
    `_restore_authoritative_session_after_full_revision()` as the recovery and
    non-cached path;
  - expose a small last-transaction diagnostic describing cached versus full
    recovery behavior, without changing persisted schemas.
- `tools/virtual_workflows/scenarios.py`
  - time the new calibration transaction's successor validation, pre-write
    guard, durable writes, post-write acceptance, and cache installation so a
    future regression remains attributable.

Focused tests:

- `tests/test_authoritative_execution_runtime_cache.py`
  - prove the healthy calibration path does not call full authoritative
    inspection or full revision-history validation;
  - prove identity conflicts, unexpected successor files, and failed writes
    fail closed and never advance the cached session;
  - prove a valid append advances history, progress, resume, calibration
    references, identities, and revision names exactly once.
- `tests/test_initial_execution_plan_integration.py`
  - preserve calibration retry/partial-commit recovery, immutable bytes,
    target changes, refuel-check synchronization, and cold/full-validation
    behavior.
- `tests/test_virtual_workflow_execution_observer.py`
  - freeze the new phase attribution and bounded report shape without changing
    the responsiveness threshold.
- `tests/system/test_virtual_print_array_384x10_composed.py`
  - add only assertions needed to prove cached calibration commits avoid
    repeated full bundle/history reads and retain one final complete-chain
    validation; do not create another workflow.

Documentation updated only after the implementation and evidence pass:

- `README.md`
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- `docs/sil_interactive_simulation_milestone_7_slice_8_implementation_plan.md`
- `docs/sil_interactive_simulation_milestone_7_slice_8_diagnostic_closeout_plan.md`
- `docs/sil_interactive_simulation_milestone_7_slice_8_completion_record.md`
- this plan

No Controller, View, simulator, firmware, protocol, manifest, fixture, or
hardware file is in scope. `AuthoritativeExecutionLoad.py` already provides
`advance_authoritative_execution_revision()` and should remain unchanged
unless a focused test proves that its existing public helper cannot validate
the calibration sidecar/successor combination. Any such need stops the slice
for review rather than silently broadening it.

## Implementation Plan

1. **Freeze the cached calibration contract.** Add focused tests that activate
   a real authoritative session, apply successive target-changing calibration
   revisions, and monkeypatch full inspection/history validation to fail if
   invoked on the healthy cached path. Assert the exact successor history,
   calibration reference, progress/resume revision, revision filenames, and
   diagnostic path. Preserve a cold/no-session case that still invokes full
   validation.

2. **Add the in-memory successor preparation.** In `Model.py`, build the
   updated calibration bundle, retarget progress, synchronize the resume
   checkpoint, and call the existing
   `advance_authoritative_execution_revision()` before any durable write. Do
   not duplicate revision transition rules or construct a second history
   validator.

3. **Add the guarded durable append.** Reuse the existing authoritative
   transition identity guard and write helpers. Require the expected next
   filename to be absent, preserve current write order and atomic writers,
   and accept exactly the calibration sidecar/current plan/progress/resume/new
   revision identities. Install the advanced session only after persistence,
   exports, and post-write checks all succeed.

4. **Retain fail-closed recovery.** Route only a clean, matching active session
   through the cached transaction. Keep the current full `_commit_plan_revision`
   plus full bundle restoration for cold activation and recovery. Add failure
   injection at pre-write conflict, immutable-write success/current-plan
   failure, progress failure, resume failure, export failure, and post-write
   conflict; assert no stale cache survives and retry reconciles the durable
   prefix without changing immutable bytes.

5. **Make the cost visible.** Extend existing SIL phase instrumentation and
   focused observer tests to report cached calibration successor validation,
   guard, individual durable writes, post-write acceptance, and cache install.
   Assert passes 2 through 10 perform zero full bundle refreshes and zero full
   revision-history validations during calibration, while terminal closeout
   performs its existing full-chain validation once.

6. **Run targeted functional and performance validation.** Run only the
   focused commands below. First pass all unit/integration tests; then run the
   composed 384x10 node once. If it fails, inspect its retained report before
   allowing one cause-proven correction within these files. Do not loop the
   long stress test, change thresholds, or broaden into general performance
   work.

7. **Close Slice 8 only through the existing gates.** After a clean composed
   terminal report, run the legacy-direct parity node, one visible composed
   run, and exact replay of that visible report. Update the Slice 8 records
   with commands, durations, counts, hashes, and retained paths. The full
   pytest suite remains deferred until the final Milestone 7 validation, as
   previously directed.

## Focused Validation Commands

Unit and integration contract:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests/test_execution_plan_revision.py `
  tests/test_authoritative_execution_runtime_cache.py `
  tests/test_execution_pass_start_cache.py `
  tests/test_initial_execution_plan_integration.py `
  tests/test_virtual_workflow_execution_observer.py
```

Focused composed terminal gate:

```powershell
.\env\Scripts\python.exe -m pytest -q -m sil_stress `
  tests\system\test_virtual_print_array_384x10_composed.py::test_composed_384x10_success_and_direct_parity
```

Legacy-direct parity is run only after the composed gate passes:

```powershell
.\env\Scripts\python.exe -m pytest -q -m sil_stress `
  tests\system\test_virtual_print_array_384x10_composed.py::test_direct_384x10_frozen_parity
```

Visible qualification:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario virtual_print_array_384x10_v1 `
  --output-root verification_reports\milestone7-slice8-visible `
  --visible --seed 1 --speed-multiplier 100 --timeout-seconds 1800
```

Run the exact `run.replay_command` emitted by that retained visible report; do
not hand-construct a substitute. Its literal command, seed, report hash, and
paths must be recorded before Slice 8 is marked complete. No full-suite
command is part of this focused remediation.

## Acceptance Gates

Functional and safety gates:

- immutable revision filenames remain contiguous and existing revision bytes
  never change;
- a cached calibration adds exactly one valid successor and updates current
  plan, progress, resume, calibration references, and exports coherently;
- no healthy cached calibration reopens an earlier revision body or invokes
  `validate_revision_history()`/`inspect_authoritative_execution()`;
- external replacement, missing/extra revisions, ambiguous existing
  successors, and injected write failures fail closed before cache advance;
- recovery after a partial commit uses the existing full validation path and
  produces the same final authoritative bundle as a clean commit;
- restart/cold activation and terminal closeout still validate the complete
  immutable chain;
- no durability call, atomic replacement, `fsync`, schema, threshold, or UI
  interaction is removed or weakened.

Terminal SIL gates:

- 3,840/3,840 operation pairs complete with no failed action, unexpected
  dialog, queue starvation, or watchdog failure;
- event-loop maximum is at most 1,000 ms and scheduling-lateness p99 and active
  pressure-render measurements satisfy the already frozen Slice 8 contract;
- passes 2 through 10 show the cached calibration path and zero redundant full
  history/bundle validations;
- final terminal inspection reports a valid completed plan, contiguous full
  history, clean resume checkpoint, and matching progress;
- composed/direct normalized outcomes match;
- visible evidence and exact replay both validate with retained hashes and the
  same seed/configuration.

## Risks And Mitigations

- **Stale in-memory prefix:** every cached append is bracketed by the existing
  ordered revision-name and file-identity guards. A mismatch invalidates the
  session and requires explicit reload/reactivation.
- **Calibration sidecar/plan split:** successor validation uses the updated
  sidecar in memory before writes; all affected files are included in
  post-write acceptance. A mid-transaction failure leaves a synchronization
  error and enters full recovery.
- **Crash between atomic files:** the on-disk transaction remains intentionally
  multi-file. Existing immutable-first recovery is retained and tested; this
  plan does not claim cross-file atomicity.
- **Trusting writes without rereading history:** the approach uses the same
  in-process atomic-write plus identity-acceptance contract already used by
  pass-start revisions. Cold load, recovery, and terminal closeout still parse
  and validate the complete chain.
- **A different remaining pause:** the new phase ledger must identify any
  residual plan-sized serialization, export, or UI work. Only a cause-proven
  issue inside the listed files may be corrected without a new plan.
- **Dirty worktree/evidence provenance:** preserve every existing tracked and
  untracked Slice 8 change. Record reports by explicit path and do not claim
  evidence from another computer unless it is transferred and hash-verified.

## Rollback

Revert the calibration-specific cached transaction, its phase wrappers, and
its focused tests. Route calibration through the existing
`_commit_plan_revision()` and `_restore_authoritative_session_after_full_revision()`
path again. This restores the known slow but fully validated behavior without
any data migration because the plan, revision, calibration, progress, and
resume schemas are unchanged.

Retain the independent Slice 8 rack, deadline, pressure-readiness, ACTIVE-plan
cache, watchdog, pressure-boundary observer, and evidence work. Retained
reports remain immutable local evidence and require no rollback.

## Implementation Outcome

Implemented on 2026-08-07. A clean active authoritative session now validates
and persists one calibration successor against its already validated in-memory
history, with pre/post-write identity guards and the original durable write
order. Cold activation, partial-commit recovery, and terminal closeout retain
full revision-history validation. Seven injected failure points prove that no
partial write advances the cache and that a retry reconciles the immutable
prefix without changing existing revision bytes.

Focused validation passed 66 revision/cache/integration tests, 231 adjacent
lifecycle/harness tests, and the real two-stock composed lifecycle. The final
composed 384x10 node passed all 3,840 operations in 383.65 seconds, followed by
the direct parity node in 298.95 seconds. Its retained composed report is:

```text
verification_reports/milestone7-slice8-revision-history-scalability/
  20260807T185136291097Z_composed/report.json
```

The report SHA-256 is
`7a9a15484f44dc078e33adea6cbc1dc03a764c01e5c86436c46050c0eac6b199`.
Maximum event-loop gap was 685.460 ms, scheduling-lateness p99 was 81.616 ms,
and active pressure-render maximum was 252.072 ms. Nine cached calibration
commits had a 181.185 ms maximum; their successor validation had a 10.132 ms
maximum. No cached calibration invoked a full bundle refresh, while terminal
closeout retained one 424.111 ms full-chain validation.

The visible gate and its exact replay both failed closed at 1,536 completions
on the same unrelated rack interaction: the fifth-head Swap combobox emitted
no activation after both bounded QTest attempts while its popup remained
visible. Their retained report SHA-256 values are
`f19e26154db55fc7dc9315807248eb21c96065fc25eaad0242149e06774e59ba` and
`9f0a8bd7e9a680bc15ac0c982e3ea2dd2888371228ed1295ea6754deacf232ef`.
No rack/page-driver correction was made because it is outside this approved
revision-history plan. Slice 8 therefore remains open solely on a separately
reviewed visible-rack correction and passing visible/exact-replay evidence.
