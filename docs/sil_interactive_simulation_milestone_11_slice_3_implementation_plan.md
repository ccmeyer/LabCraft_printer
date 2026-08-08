# Milestone 11 Slice 11.3 Implementation Plan

Status: complete (2026-08-08)

## Objective and non-goals

Add one reusable, lifecycle-neutral clean application-session rotation phase
and extend the unregistered joined checkpoint through a genuine second
application session. Load the calibrated revision-3 execution through the real
Qt editor from authoritative files, prove the load is read-only, activate it
explicitly, and reconcile literal design/calibration/head/count/progress truth
at zero progress.

Do not modify the existing paused/resume phase, start or resume an array,
calibrate Water or Design B, register a scenario/capability/suite, publish an
accepted report/replay, change a persisted schema, or change production MVC
behavior.

## Exact call path

```text
revision-3 calibrated checkpoint + closed first observer
-> capture authoritative source bundle
-> restore remaining hooks -> AutomationHarness.close_application_session
-> recorder close/session-lock release -> exact directory comparison
-> AutomationHarness.reopen_application_session -> fresh ApplicationComponents
-> new ExecutionObserver bound to the second application session
-> ExperimentLoaderDriver real Qt directory selection/load
-> authoritative inspection with runtime inactive and ready_to_start
-> exact read-only loaded-boundary comparison
-> real Load Execution button -> MainWindow.activate_authoritative_execution
-> Model.load_authoritative_execution_runtime
-> clean resume checkpoint/export/audit allowlist
-> runtime active, controller idle, revision-3 identity/count reconciliation
```

## Files expected to change

Add:

- `docs/sil_interactive_simulation_milestone_11_slice_3_implementation_plan.md`
- `docs/sil_interactive_simulation_milestone_11_slice_3_completion_record.md`

Update:

- `tools/virtual_workflows/page_drivers.py`
- `tools/virtual_workflows/authoritative_evidence.py`
- `tools/virtual_workflows/journey_phases.py`
- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/journeys.py`
- focused page-driver, authoritative-evidence, phase, assertion, composition,
  contract-freeze, and joined system tests as evidence requires;
- only the Milestone 11 current-action text in
  `docs/sil_interactive_simulation_and_composable_workflows_plan.md`.

`tools/virtual_workflows/harness.py` is not expected to change because its
existing retained-session ID, fresh application-session ID, recorder status,
session-lock, and application-session records already expose the required
freshness evidence.

## Implementation steps

1. Generalize only the shared authoritative loader's expected eligibility and
   controller state with historical `ready_to_resume`/`resume_ready` defaults;
   preserve the old action IDs, evidence keys, and behavior.
2. Add clean-start loaded and activation boundary evidence helpers that require
   exact read-only load, the existing activation-write allowlist, one clean
   revision-3 resume checkpoint and activation audit row, zero progress, and
   stable plan/design identity.
3. Add `run_clean_authoritative_session_rotation_boundary()` with generic
   experiment/name/observer callbacks. It closes cleanly, compares bytes,
   reopens freshly, installs a new observer, drives real load/activation, and
   returns both session records and boundary snapshots without pause/resume
   branching.
4. Add joined read-only assertions for distinct application identity, closed
   first recorder/absent lock, zero first-session lifecycle, literal source /
   loaded / activated identity and keyed counts, exact calibration/head join,
   and no second-session dispatch.
5. Extend the unregistered joined body and selected offscreen system test
   through `fresh_loaded` and `fresh_activated`; retain five screenshots and
   forbid array/refill/remaining-calibration actions.
6. Add fail-closed unit/contract coverage for reused application identity,
   close/load mutation, disallowed activation writes, duplicate/missing
   activation evidence, stale plan/progress/resume references, pre-activation
   runtime activity, and lifecycle leakage where practical without duplicating
   existing paused-reload tests.
7. Run focused non-SIL tests, existing paused reload tests unchanged, and the
   selected two-session offscreen joined test. Inspect the full diff and run
   `git diff --check`.
8. Record exact results, advance to Slice 11.4, and commit as
   `test: add clean authoritative session rotation phase`.

## Entrance and exit criteria

Entrance requires committed Slice 11.2 (`67c01ff`) and a clean worktree. Exit
requires exactly two application-session IDs, the same retained SIL root, a
closed first recorder and absent lock, byte-identical files through close and
load, runtime inactive before and active after explicit activation, controller
state `idle`, one clean resume checkpoint at the same plan ID/revision 3, one
activation audit event, only allowlisted activation writes, and exact
seed/mapping/design/calibration/head/count/progress identity in the fresh
model. Both sessions must have zero dispatch/progress and all assertions must
remain keyed by `(stock_id, well_id)`.

## Tests and retained evidence

Focused tests cover loader-default compatibility, clean boundary comparisons,
phase/callback composition, joined assertions, historical authoritative
reload behavior, and the selected real-Qt system checkpoint. The authorized
system command remains direct/offscreen and intentionally produces no accepted
scenario report:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_randomized_calibration_lifecycle.py `
  tests\system\test_virtual_workflow_authoritative_reload_composed.py
```

Retain `fresh_loaded` and `fresh_activated` screenshots, both application
session records, close evidence, exact before/loaded/activated inventories and
hashes, activation audit/checkpoint evidence, assertion/action ledgers, and
fresh observer identity. Exact scenario replay remains deferred because the
complete journey is still unregistered.

## Compatibility, risks, rollback, and deferred validation

Preserve `run_authoritative_reload_resume_boundary()`, its default loader
semantics/evidence, completed-terminal reload, session-lifecycle merge,
Milestone 9/10 hashes/selectors/reports/replays, authoritative formats, and
negative no-mutation evidence. Expected design/count values stay literal and
case-owned; the count normalizer touches observations only.

The main risks are retaining a first-session object, confusing the retained
root with a reused application, or accepting activation-side writes outside
the established allowlist. Any production mismatch requires a separate
reviewed correction plan. Rollback is the independent Slice 11.3 commit and
requires no data migration or production rollback.

Remaining calibrations, stock-pass execution, terminal reload, scenario
registration, accepted offscreen/replay/visible qualification, host
regressions, and full pytest remain deferred to Slices 11.4 and 11.5.
