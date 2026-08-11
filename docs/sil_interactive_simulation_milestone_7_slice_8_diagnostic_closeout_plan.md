# Milestone 7 Slice 8 - Diagnostic Decomposition And Closeout Plan

Status: `implemented; responsiveness resolved by follow-up; visible rack gate blocked`

Planning date: 2026-08-07

Planning baseline: the intentionally uncommitted Milestone 7 worktree with the
Slice 8 composed migration, focused corrections, and guarded ACTIVE-plan cache
amendment present. Preserve every existing tracked and untracked change.

## Objective

Resolve the two remaining Slice 8 uncertainties without repeatedly using the
entire 384-well by 10-stock journey as the development loop:

1. determine why a run can stop making progress with lookahead print intents
   outstanding; and
2. determine whether the greater-than-1,000 ms UI gaps come from required
   durable persistence, application scheduling, or diagnostic overhead.

The full `virtual_print_array_384x10_v1` composed journey remains the final UI
qualification gate. Its fixture, 3,840-pair contract, interaction-surface
claims, durability requirements, responsiveness thresholds, and exact replay
requirements are not reduced. The legacy direct runner remains a parity oracle,
but it is separated from the composed pytest node so one failure does not force
both expensive runs to be repeated.

This plan does not migrate Slice 9, change firmware or protocol, operate a Pi or
physical hardware, weaken `fsync`/atomic-replace durability, batch progress,
move persistence to a background thread, pump Qt events from Model persistence,
change stress thresholds, or accept a new performance baseline. The complete
pytest suite remains deferred until the final Milestone 7 validation.

## Audit Findings

- The composed call path is shared with the passing 24x2 and 96-well journeys;
  Slice 8 does not have a separate workflow body.
- `tests/system/test_virtual_print_array_384x10_composed.py` currently performs
  the full composed run and then the full legacy direct run in one test node.
- The composed final pass calls `wait_for_completions()` with the remaining
  scenario deadline. The wait records only target count, observed count, and
  errors on timeout; it has no independent no-progress deadline and no live
  Controller/simulator/checkpoint snapshot.
- The Controller lookahead path is:

  ```text
  Array UI Start/Resume
    -> Controller.print_array()
    -> Controller._fill_array_lookahead()
    -> Controller._queue_next_array_well()
    -> ExperimentModel.begin_execution_print_intent()
    -> SimulatedMachine command queue
    -> ExperimentModel.attach_execution_print_command()
    -> SimulatedMachine._complete_active_command()
    -> dispense completion handler
    -> Controller._handle_array_well_complete()
    -> ExperimentModel completion/progress persistence
    -> Controller._fill_array_lookahead()
  ```

- On the simulator, completion handlers execute while `_completing` is true.
  Commands added by the handler cannot pump immediately; after the handler
  returns, `_complete_active_command()` fills the acceptance window and pumps
  the next command. Existing tests cover one handler extending the queue but
  do not soak this handoff across thousands of extensions or both 100x and
  1,000x pacing.
- `SimulationTimingPolicy.wall_delay_ms()` has a 1 ms minimum. The stress test
  already uses 1,000x, so a larger multiplier cannot accelerate most commands
  and cannot accelerate JSON serialization, `fsync`, atomic replacement, Qt
  work, or evidence collection.
- The existing persistence characterization tool already isolates real Model
  intent/progress durability without UI, Controller, simulator, or hardware.
  Its `execution_persistence_384_single_v1` workload is sufficient for the
  first diagnostic pass; no new benchmark implementation is needed.

## Frozen Diagnostic Decisions

1. **Observe before correcting.** Add read-only, bounded live-state capture and
   focused reproductions before changing Controller or simulator scheduling.
2. **Two pacing levels.** Scheduler probes run at 100x and 1,000x. A failure at
   both implicates shared Controller/scheduling behavior; a 1,000x-only failure
   implicates accelerated simulator scheduling until disproved.
3. **No-progress is distinct from total timeout.** The stress composition fails
   closed after 120 seconds with no increase in completed stock/well pairs,
   even if total scenario time remains. Any progress resets that interval.
4. **Failure evidence is read-only and bounded.** Capture in-memory state first;
   after declaring the stall, read the authoritative checkpoint once. Never
   recover, clear, retry, discard an intent, or mutate the Model to diagnose.
5. **No UI-coverage inflation.** Simulator/Controller and Model-only probes are
   diagnostic tests. They do not satisfy or replace the normal-QTest 384x10 UI
   gate.
6. **Cause-proven correction only.** Production or simulator code may change
   only when a new focused test reproduces the failure before the change and
   passes after it. Otherwise retain the diagnostics and perform one fresh full
   composed run without a speculative correction.
7. **Durability remains synchronous and exact.** This plan may remove proven
   redundant diagnostic work but cannot reduce the required three resume and
   one progress durable writes per completion.
8. **One expensive closeout sequence.** Run composed terminal qualification,
   legacy parity, visible execution, and exact replay only after all fast and
   medium gates pass.

## Required Failure Snapshot

The no-progress action evidence must include:

- target count, observed count, last-progress count, and stalled seconds;
- current pass index, stock ID, and head ID;
- Controller array state, finalize reason, current barrier, and at most the two
  queued lookahead wells with intent and command sequence IDs;
- simulator connection/pause/completion flags, command-timer state, active
  command, status counts, queue depth, and at most four nonterminal commands;
- command counters (`current`, `last_completed`, `last_accepted`, and
  `last_retired`);
- execution-plan state/revision and current synchronization error;
- checkpoint state and bounded pending-intent identities loaded once only after
  the no-progress decision; and
- latest event-loop and named-phase context when the evidence profile is
  installed.

The snapshot must contain no QObject instances, callbacks, absolute secret
paths, or unbounded histories. It must remain JSON serializable so the generic
harness retains it in the failed action ledger and failure report.

## Exact Files To Touch

Always required implementation files:

- `tools/virtual_workflows/execution_observer.py`
- `tools/virtual_workflows/actions.py`
- `tools/virtual_workflows/journey_phases.py`
- `tests/test_virtual_workflow_execution_observer.py`
- `tests/test_virtual_workflow_actions.py`
- `tests/test_simulated_machine.py`
- `tests/test_controller_print_guards.py`
- `tests/system/test_virtual_print_array_384x10_composed.py`
- `README.md`
- `docs/sil_interactive_simulation_milestone_7_slice_8_implementation_plan.md`
- `docs/sil_interactive_simulation_milestone_7_slice_8_completion_record.md`
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`

Conditional correction files, touched only if the corresponding focused test
first fails:

- `FreeRTOS-interface/simulation/machine.py` for a simulator pump/acceptance
  handoff defect;
- `FreeRTOS-interface/Controller.py` for a Controller lookahead/finalization
  scheduling defect; or
- `tools/virtual_workflows/regression_evidence.py` for proven diagnostic
  observer work on the hot path.

Do not touch the stress fixture, `Model.py`, `ExecutionResumeStore.py`, report
schema, registry, capability manifest, firmware, protocol, or Pi tooling under
this plan. If evidence requires one of those files, stop and amend the plan.

## Implementation Steps

1. **Freeze the diagnostic contract and split expensive nodes.** Preserve the
   existing contract-only test. Split composed success and legacy direct parity
   into separately selectable stress test nodes without changing either
   runner's inputs or assertions. Factor the currently compared workload and
   terminal fields into one frozen parity projection and apply it independently
   to both reports. The direct node must not let composed UI coverage be claimed
   from direct Model setup.

2. **Add a reusable bounded liveness snapshot.** In
   `execution_observer.py`, add a read-only serializer for the state listed
   above. Unit-test missing/partial components, bounded queues/intents, JSON
   serialization, and the guarantee that capture invokes no queue, recovery,
   or mutation method.

3. **Add a rolling no-progress watchdog.** Extend
   `wait_for_completions()` with an optional progress timeout and diagnostic
   callback. Reset the monotonic timer only when completion count increases;
   fail with `ScenarioActionError(stage="no_progress")` after the bound, attach
   the liveness snapshot, and still obey the outer scenario deadline. Configure
   the 384x10 stock-pass composition for 120 seconds; smaller journeys retain
   their current behavior. Cover progress resets, exact cutoff, outer-deadline
   precedence, and evidence-callback failure in action tests.

4. **Create fast scheduler reproductions.** Add parameterized 100x/1,000x tests
   that use the real `SimulatedMachine` timer/queue and a Controller-shaped
   two-well lookahead completion chain for at least 4,000 handler-driven queue
   extensions. Include a variant with a small synchronous completion delay to
   model persistence blocking. Assert every handler executes exactly once,
   command numbers remain ordered, the queue drains once at terminal, no
   premature drain occurs, and no synthetic intent remains pending. Keep these
   tests hardware-isolated and under 30 seconds total on the Windows reference
   host.

5. **Run the isolated persistence characterization.** Use the existing
   `execution_persistence_384_single_v1` workload with zero warmups and one
   measured run. Record per-phase p50/p95/p99/max, durable-write counts,
   first/last-quartile growth, full-rebuild/cached-update counts, and the
   longest single operation in the completion record. This diagnostic is
   informational and makes no UI claim.

6. **Apply at most one cause-proven correction.** If Step 4 fails, make the
   smallest simulator or Controller correction that preserves two-well
   lookahead, intent-before-command durability, command-sequence attachment,
   completion-before-progress, fail-closed handler errors, and normal hardware
   behavior. If Step 4 passes but persistence is not the source of the observed
   gap, remove only observer work proven by phase evidence to dominate the hot
   path. If neither condition is proven, make no runtime correction. If a
   required durable write itself blocks for more than the responsiveness
   threshold, stop: background/batched persistence requires a separate safety
   and crash-consistency plan.

7. **Run focused compatibility gates.** Run the simulator, Controller, action,
   observer, Model cache, persistence, 24x2 composed, and 96-well composed tests
   listed below. Inspect one deliberately forced no-progress failure report to
   confirm that the report is terminal, bounded, replayable, and retains the
   required snapshot. Do not run the full pytest suite.

8. **Perform Slice 8 closeout once.** Run the full composed 384x10 terminal node
   first. Only after it passes or warns within the frozen thresholds, run the
   legacy direct parity node, then one visible run at the documented 100x pace
   and its exact retained replay command. Update the Slice 8 completion record
   with paths and observed results. Any no-progress failure or greater-than-
   1,000 ms responsiveness failure keeps Slice 8 open and blocks Slice 9.

## Focused Test Commands

Fast scheduler and watchdog loop:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_simulated_machine.py `
  tests\test_controller_print_guards.py `
  tests\test_virtual_workflow_actions.py `
  tests\test_virtual_workflow_execution_observer.py
```

Model/persistence safety compatibility:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_authoritative_execution_runtime_cache.py `
  tests\test_execution_resume_store.py `
  tests\test_execution_progress_store.py `
  tests\test_authoritative_execution_load.py `
  tests\performance\test_execution_persistence_benchmark.py
```

One isolated real-persistence diagnostic:

```powershell
.\env\Scripts\python.exe tools\characterize_execution_persistence.py `
  --workload execution_persistence_384_single_v1 `
  --warmup-runs 0 `
  --measured-runs 1 `
  --keep-workload-artifacts on-failure `
  --output-root verification_reports\milestone7-slice8-diagnostics
```

Smaller real composed compatibility:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\system\test_virtual_workflow_multi_stock_composed.py `
  tests\system\test_virtual_print_array_96_composed.py
```

Run the split stress nodes separately, never as one combined invocation. The
composed node retains its frozen manifest ID even though direct execution has
been removed from that function:

```powershell
.\env\Scripts\python.exe -m pytest -q -m sil_stress `
  tests\system\test_virtual_print_array_384x10_composed.py::test_composed_384x10_success_and_direct_parity

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

Execute the exact `run.replay_command` from that visible report. Do not hand
construct a substitute replay command.

## Acceptance Gates

- The fast scheduler test completes all extensions at both pacing levels with
  exact-once handlers, ordered command lifecycle, one terminal drain, and zero
  pending synthetic intents.
- The deliberately forced watchdog test fails in bounded time with
  `failure_stage=no_progress` and the complete bounded liveness snapshot.
- Persistence characterization retains exactly four durable write operations
  per completion, zero hot-path authoritative reads, zero full progress
  rebuilds, and a clean terminal checkpoint.
- The 24x2 and 96-well composed journeys retain their current action surfaces,
  assertion results, reports, and cleanup behavior.
- The full composed stress report has all 3,840 unique pairs, ten valid pass
  boundaries, zero pending intents, zero queue starvation, exact durable I/O,
  a clean terminal bundle, and `pass` or permitted `warning` classification.
- No event-loop or pressure-render gap exceeds 1,000 ms and scheduling lateness
  p99 does not exceed 250 ms.
- Legacy direct parity matches the frozen workload and terminal-state fields.
- The visible run and exact replay both pass or warn, required screenshots are
  inspected, and teardown is clean.
- The full pytest suite is not run here; it remains the final Milestone 7 gate.

## Decision Outcomes

- **Simulator probe fails only at 1,000x:** correct simulator scheduling and
  retain 100x/1,000x regression coverage. Do not change Controller or Model.
- **Controller-shaped probe fails at both rates:** correct the lookahead or
  finalization handoff with Controller unit coverage. Do not alter firmware or
  protocol behavior.
- **All scheduler probes pass and full run stalls:** use the retained live
  snapshot to create one narrower reproducer; do not speculate or repeat the
  full run until that reproducer exists.
- **Persistence operation explains a greater-than-1,000 ms gap:** stop and
  propose a separate crash-consistency/performance plan. Do not weaken durable
  writes under this plan.
- **Diagnostic observer work explains the gap:** remove only the proven
  redundant work and prove evidence equivalence in focused tests.
- **All gates pass:** mark Slice 8 complete and proceed to planning Slice 9.

## Risks And Mitigations

- A diagnostic snapshot could perturb timing. Capture it only after the
  no-progress decision, not on every polling iteration.
- A synthetic scheduler soak might pass while the full UI journey fails. It is
  diagnostic evidence only and cannot replace the full gate.
- Splitting pytest nodes could accidentally weaken parity. Preserve all current
  fields in the shared frozen parity projection and require both nodes in
  closeout.
- Synchronous disk latency varies by host. Retain environment identity and raw
  phase distributions; do not accept or tune thresholds from one run.
- A scheduler correction could affect real hardware. Keep changes behind the
  simulated-machine implementation whenever the defect is simulator-only. Any
  Controller change must pass existing print guards and preserve command and
  intent ordering.

## Rollback

Before implementation, save the current diff. To roll back this diagnostic
slice, revert only the files changed under this plan and delete only newly
created diagnostic reports. Do not reset or discard the pre-existing
uncommitted Milestone 7 worktree.

If a conditional simulator, Controller, or observer correction is made and any
focused compatibility gate fails, revert that correction while retaining the
read-only snapshot/watchdog tests and record Slice 8 as blocked. No hardware or
firmware rollback is required because this plan does not operate or modify
either.

## Implementation Outcome

The user approved this plan and it was implemented on 2026-08-07. The bounded
liveness snapshot, rolling 120-second watchdog, split stress nodes, 100x/1,000x
simulator soak, and 4,000-operation Controller lookahead soak are present. All
scheduler probes passed, so no simulator or Controller correction was made.

The isolated 384-completion persistence characterization passed in 4.009
seconds. Per-completion p50/p95/p99/max were 9.861/10.931/11.914/12.573 ms;
the maximum observed `fsync` and atomic replacement were 2.782 and 0.544 ms.
It retained all 1,536 calls of each kind, zero hot-path reads, zero full
progress rebuilds, 384 cached updates, and a clean checkpoint. Ordinary
per-completion persistence therefore did not reproduce the one-second gap.

The first full composed run completed all 3,840 pairs with no failed actions or
starvation. It proved that nine greater-than-1,000 ms pressure-render intervals
were the nine intentional inactive gaps between stock passes, not active UI
starvation. The one allowed cause-proven observer correction now segments
pressure-render intervals by pass. Focused unit tests and real 96-well parity
passed afterward.

The corrected composed run again completed all 3,840 pairs with no failed
actions or starvation. It excluded exactly nine inactive pressure boundaries;
the active render maximum was 256.192 ms and scheduling-lateness p99 was
81.487 ms. The report still failed because one event-loop gap reached
1,064.585 ms. Retained phase and stack evidence attributes that gap to the real
pass-10 calibration transaction:

```text
Calibration UI Apply
  -> ExperimentModel.apply_execution_calibration()
  -> ExperimentModel._commit_plan_revision()
  -> validate_revision_history()
  -> load every immutable execution-plan revision
```

The measured `pass_start.commit_revision` phase was 347.510 ms and overlapped
the 1,064.585 ms service gap; later pass-start revision and full-bundle work
show the same growth pattern below the hard threshold. This is a real
synchronous revision-history scalability issue, not a simulator liveness or
ordinary per-well persistence defect.

The decisive corrected report and its bounded evidence were copied out of
pytest temporary storage and retained beneath
`verification_reports/milestone7-slice8-diagnostic-closeout/20260807T181633371835Z_composed/`.

Step 6 permits at most one cause-proven correction, already used for the
pressure measurement defect. No second Model optimization, threshold change,
background persistence, durability change, direct parity run, visible run, or
replay was performed. Slice 8 remains open. A separately reviewed plan is
required to bound calibration revision-history validation while preserving
immutable-history and crash-consistency guarantees.
