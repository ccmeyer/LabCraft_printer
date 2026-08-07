# Milestone 7 Slice 8 - Implementation And Validation Record

Status: `complete - visible and exact-replay gates verified`

Date: 2026-08-07

## Outcome

`virtual_print_array_384x10_v1` now dispatches through the generic composed
journey and shares the cardinality-neutral multi-stock body, stock-pass phase,
lifecycle assertions, sustained-evidence profile, payload, report adapter, and
teardown used by the existing portfolio. The legacy direct runner remains
callable as the parity oracle.

The implementation preserves the byte-identical fixture, 384 serpentine
wells, ten stock/head identities, 3,840 stock/well targets, opt-in status,
report-v1 envelope, comparison/Pi contracts, and stress thresholds. The
approved performance amendment changes only the Model's repeated ACTIVE-plan
lock path; no Controller, View, simulator response, firmware, protocol,
Pi-operation, or hardware file changed.

Offscreen composed terminal validation, legacy-direct parity, visible Windows
validation, and the exact emitted visible replay now pass. Slice 8 is complete.

## Approved Amendments

- The schema-v2 editor projection uses the sum of prepared stock volumes for
  this fixture, producing one frozen target for each of 3,840 stock/well pairs.
- `RackDriver.swap_unassigned_head()` drives the existing rack Swap combobox
  with bounded mouse-only QTest interaction while idle and drained. It waits
  out Qt's post-open mouse-release guard, resets pointer state after callback
  repopulation, observes activation and the exact rack postcondition, closes
  rebuilt popups, and retries once only when neither activation nor a write
  occurred.
- An action-scoped dialog guard rejects and records unexpected dialogs even
  inside nested Qt event loops; driver-owned expected dialogs are registered
  only for the duration of their bounded interaction.
- Applying the original 1,300-1,390 us pulse-aware results through the normal
  calibration UI recalculated stocks 7-10 to zero targets above the 10 nL
  boundary. The approved fixed stress setting is therefore 1,355 us for every
  pass. The integer-only SIL response is 9.99 nL; the unchanged fixture design
  target remains reported separately as 10 nL.
- `ArrayDriver.start()` now requires the controller to reach `running`, so a
  confirmed Start dialog that produces no work fails at the start boundary.
- Final stock-pass completion uses the remaining outer scenario deadline
  instead of a separate 30-second cap.
- Pressure regulation waits for its simulated command queue to drain before
  the calibration control is used, closing a reproduced readiness race.
- Repeated ACTIVE execution-plan locks use the existing authoritative-session
  file/revision guard and return the matching cached plan without redundant
  recovery or progress/resume rewrites. Synchronization errors and external
  changes retain the full fail-closed recovery behavior.

## Call Path

```text
CLI/registry -> JourneyExecutor -> AutomationHarness
  -> shared multi-stock journey body
  -> normal Experiment Editor controls
  -> normal machine settings and pressure controls
  -> RackDriver Swap / volume / Load / Unload controls
  -> normal synthetic calibration dialog controls
  -> normal Start Array controls
  -> Controller -> Model -> SimulatedMachine
  -> authoritative intent/progress/resume persistence
  -> shared sustained evidence, assertions, report, and teardown
```

The only explicit Model-surface action remains deterministic head identity
binding. Operator behavior is recorded as `ui`; waits, validation, evidence,
reporting, and teardown are recorded as `harness`.

## Files Changed

Runtime/tooling:

- `FreeRTOS-interface/Model.py`
- `tools/virtual_workflows/page_drivers.py`
- `tools/virtual_workflows/journey_phases.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/regression_evidence.py`
- `tools/virtual_workflows/report.py`
- `tools/virtual_workflows/registry.py`
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`

Tests:

- `tests/test_authoritative_execution_runtime_cache.py`
- `tests/test_virtual_workflow_page_drivers.py`
- `tests/test_virtual_workflow_journey_phases.py`
- `tests/test_virtual_workflow_assertions.py`
- `tests/test_virtual_workflow_manifest.py`
- `tests/test_virtual_workflow_contract_freeze.py`
- `tests/performance/test_virtual_workflow_comparison.py`
- `tests/system/test_virtual_print_array_384x10_composed.py`

Documentation:

- `README.md`
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- `docs/sil_interactive_simulation_milestone_7_slice_8_implementation_plan.md`
- this record

## Targeted Validation

Passed before the terminal rerun:

- performance-amendment Model/persistence selection: 66 passed in 5.87
  seconds;
- real post-amendment 24x2 and 96-well composed selection: 7 passed with 112
  existing Qt deprecation warnings in 40.64 seconds;
- final post-correction Slice 8 targeted selection: 197 passed, 6 expected
  stress-gated skips, and 50 existing Qt deprecation warnings in 7.09 seconds;
- page-driver and harness selection: 22 tests in 3.21 seconds;
- phase/assertion/composition/report/manifest/contract/comparison/Pi and
  legacy-stress selection: 172 tests in 3.73 seconds;
- real 24x2 composed lifecycle/parity/fail-closed selection: 3 tests in 19.66
  seconds with 64 existing Qt deprecation warnings;
- 96-well composed success/parity, injected-stall, timeout, and contract
  selection: 4 tests in 22.38 seconds with 48 existing Qt deprecation warnings;
- focused consecutive-repopulation and nested-dialog tests after code-shape
  consolidation: 2 tests in 0.16 seconds.

The last pre-amendment opt-in stress selection passed its contract node and completed all
3,840/3,840 stock/well operations, all six rack replacements, and clean
functional teardown. Its terminal node failed because the report correctly
classified the frozen sustained-responsiveness assertion as `fail`.

The comparison selection originally exceeded its bound because two tests
still mocked the retired direct-runner seam and therefore launched real
composed workflows. They now mock `run_registered_scenario()`, and the isolated
comparison selection passes 25 tests as part of the 37-test group above.

The current runtime/tooling diff adds 757 and removes 182 physical lines, for
net growth of 575 lines. This satisfies the amended at-most-575-line reuse
gate. Python compilation, CLI help, and `git diff --check` pass; diff check
reports only the checkout's existing LF-to-CRLF conversion warnings.
The separate performance amendment adds 18 net production lines in
`FreeRTOS-interface/Model.py`, within its approved 25-line cap.

The complete Python suite was intentionally not run. Per the milestone plan it
remains the final Milestone 7 validation gate.

## Retained Blocker Evidence

The first amended accelerated run proved the calibration correction by
crossing 2,304 and reaching 3,330/3,840 completions. It then stopped servicing
the two pending lookahead intents during stock 9. Progress, resume, plan, and
calibration files remained readable and internally consistent. The process
was terminated after 120 seconds without progress. Its retained local session
root is:

```text
%TEMP%\LabCraft\SIL\composed-sessions\20260807T154335460332Z-m7-slice8-co
```

The permitted fresh-root retry stalled before calibration with one simulated
`REGULATE_PRESSURE_R` command executing and otherwise healthy idle UI,
controller, recorder, and prepared plan state. It was also terminated after
120 seconds without progress. Its retained local session root is:

```text
%TEMP%\LabCraft\SIL\composed-sessions\20260807T155208120114Z-m7-slice8-co
```

These paths are local Windows evidence only. Neither attempt produced a
terminal report, successful teardown evidence, visible gate, or replay gate.

A subsequent closeout run after the mouse-only/dialog correction reached
1,920 completions and failed on the second callback-repopulated rack Swap. Its
validated failure report is retained beneath:

```text
verification_reports/pytest_tmp/m7_slice8_closeout_stress_20260807/
  test_composed_384x10_success_a0/virtual_print_array_384x10_v1/
  20260807T165117931524Z_composed/
```

The approved pointer-reset, popup-cleanup, activation/postcondition, and
single-retry correction then crossed all six replacements and the prior 3,330
boundary. That run continued making progress through stock 10 but exhausted
the separate 30-second final-pass wait at 3,699/3,840 completions. It retained
an undrained queue, no unexpected dialogs or simulator errors, and this report:

```text
verification_reports/pytest_tmp/m7_slice8_final_stress_20260807/
  test_composed_384x10_success_a0/virtual_print_array_384x10_v1/
  20260807T170734886043Z_composed/
```

The first deadline-policy rerun exposed a separate first-pass race: the Model
reported pressure regulation before the simulated pressure command queue had
retired, so the normal calibration control correctly opened `Synthetic
Calibration Not Ready`. The reusable pressure driver now waits for both
conditions. The failure report is retained beneath:

```text
verification_reports/pytest_tmp/m7_slice8_final_stress_20260807b/
  test_composed_384x10_success_a0/virtual_print_array_384x10_v1/
  20260807T172234129809Z_composed/
```

The corrected terminal rerun completed 3,840/3,840 stock/well operations and
reached report classification. It failed only the frozen sustained-
responsiveness contract. The event-loop distribution contained three gaps
strictly above 1,000 ms and a 1,164.1633 ms maximum; the pressure-render
distribution contained nine intervals above 1,000 ms and a 3,470.9698 ms
maximum. Recorded overlap attributes the three event-loop failures to
`persistence.full_bundle_refresh` and `pass_start.plan_lock`/
`pass_start.plan_recovery` work near passes 8-10. The report is retained at:

```text
verification_reports/pytest_tmp/m7_slice8_final_stress_20260807c/
  test_composed_384x10_success_a0/virtual_print_array_384x10_v1/
  20260807T172628291611Z_composed/
```

The approved guarded ACTIVE-lock amendment passed its focused and smaller
composed regressions. Its fresh 384x10 run completed stocks 1-4 and reached
1,656/3,840 during stock 5, then made no progress for 140 observed seconds. The
confirmed parent/child pytest processes were terminated under the documented
120-second stop rule, so no terminal report or teardown assertion was
produced. Retained progress was readable, and the queue eventually drained,
but two stock-5 intents remained pending. The local evidence root is:

```text
%TEMP%\LabCraft\SIL\composed-sessions\20260807T174349094021Z-m7-slice8-co
```

## Diagnostic Decomposition And Closeout Attempt

The approved diagnostic closeout plan added a read-only bounded liveness
snapshot, a rolling 120-second no-progress watchdog for stress stock passes,
and separate composed/direct stress nodes. The composed node retains its frozen
manifest function name; direct execution is now isolated in
`test_direct_384x10_frozen_parity`.

Fast 100x and 1,000x simulated queue soaks completed 4,000 handler-driven
lookahead extensions exactly once and drained once at terminal. A separate
Controller-shaped 4,000-well soak preserved intent-before-command ordering,
monotonic command attachment, completion order, and a maximum lookahead of
two. These tests did not reproduce the earlier pending-intent stall, so no
simulator or Controller code changed.

The retained real-persistence diagnostic is:

```text
verification_reports/milestone7-slice8-diagnostics/
  execution_persistence_384_single_v1/
  20260807T180549257503Z_481d41506bf7/report.json
```

It passed in 4.009 seconds with per-completion p50/p95/p99/max of
9.861/10.931/11.914/12.573 ms, maximum `fsync` 2.782 ms, maximum atomic replace
0.544 ms, 1,536 calls of each kind, zero hot-path reads, zero full rebuilds,
384 cached updates, and a clean checkpoint.

The first closeout composed run completed all 3,840 operations with no failed
actions or starvation. It failed because the pressure interval calculation
joined active render timestamps across nine intentional between-pass
head-exchange/calibration windows. Its pytest-local report was produced beneath
the following path and was later cleaned by pytest; the decisive measurements
are retained in this record:

```text
%TEMP%/pytest-of-conar/pytest-197/test_composed_384x10_success_a0/
  virtual_print_array_384x10_v1/20260807T180735038230Z_composed/report.json
```

The plan's one cause-proven observer correction segments render intervals by
pass. The focused observer/assertion tests and real 96-well composed/legacy
parity passed. The corrected full run excluded exactly nine inactive
boundaries and reduced active pressure-render maximum from 3,074.606 ms to
256.192 ms. It again completed all 3,840 operations with no failed action or
starvation, but one event-loop gap reached 1,064.585 ms, above the frozen
1,000 ms failure boundary. Scheduling-lateness p99 was 81.487 ms. Its local
report was copied out of pytest temporary storage and is retained at:

```text
verification_reports/milestone7-slice8-diagnostic-closeout/
  20260807T181633371835Z_composed/report.json
```

The retained stack places the threshold violation in pass-10 Calibration UI
Apply -> `ExperimentModel.apply_execution_calibration()` ->
`_commit_plan_revision()` -> `validate_revision_history()` while every growing
immutable plan revision is reloaded. The overlapping
`pass_start.commit_revision` phase took 347.510 ms; related revision/full-bundle
phases grow across later passes. This is a real synchronous revision-history
scalability issue, not simulator queue starvation or normal per-well durable
I/O.

The diagnostic plan allows at most one correction, already used for pressure
measurement. Direct parity, visible, and exact replay gates were therefore not
run. The complete pytest suite remains deferred to final Milestone 7.

## Revision-History Scalability Remediation

The approved follow-up replaces repeated full-history parsing only for a
clean, active calibration transaction. It validates the candidate against the
already validated `AuthoritativeExecutionBundle.history`, rebuilds progress
from the cached prior payload, guards authoritative identities before and
after the unchanged atomic write sequence, and installs the advanced session
only after every write and export succeeds. Cold activation, recovery after a
partial commit, migration inspection, and terminal closeout still validate the
complete immutable revision chain.

Validation completed as follows:

- 66 focused revision/cache/integration tests passed in 7.28 seconds;
- 231 adjacent lifecycle, terminal, progress, harness, driver, manifest, and
  comparison tests passed in 10.43 seconds;
- the real two-stock composed lifecycle passed in 7.69 seconds;
- the final composed 384x10 node passed in 383.65 seconds;
- the separate legacy-direct parity node passed in 298.95 seconds;
- the complete pytest suite remains deferred to final Milestone 7 validation.

The passing composed report is retained at:

```text
verification_reports/milestone7-slice8-revision-history-scalability/
  20260807T185136291097Z_composed/report.json
```

Its SHA-256 is
`7a9a15484f44dc078e33adea6cbc1dc03a764c01e5c86436c46050c0eac6b199`.
It completed 3,840/3,840 operations with every required assertion passing and
zero starvation. Maximum event-loop gap was 685.460 ms, below the unchanged
1,000 ms hard gate; scheduling-lateness p99 was 81.616 ms and active
pressure-render maximum was 252.072 ms. Nine cached calibration transactions
had a maximum of 181.185 ms and their successor-validation maximum was
10.132 ms. There was one full bundle refresh before the cached sequence and
one 424.111 ms terminal full-chain validation; no cached calibration performed
a full refresh. The direct report is retained beside it under
`20260807T185822509959Z_direct/report.json` with SHA-256
`d24fa0e7d44af7b72f4eefde00dd47fd45e5821c38dca098c411f5fb454ceeea`.

The first visible run and its exact emitted replay both failed closed at 1,536
completions. In each run, the fifth-head Swap combobox produced no activation
after both bounded QTest attempts; the expected postcondition remained false
and the popup remained visible. The reports are retained at:

```text
verification_reports/milestone7-slice8-visible/virtual_print_array_384x10_v1/
  20260807T190354302230Z_composed/report.json
  20260807T190635866661Z_composed/report.json
```

Their SHA-256 values are
`f19e26154db55fc7dc9315807248eb21c96065fc25eaad0242149e06774e59ba` and
`9f0a8bd7e9a680bc15ac0c982e3ea2dd2888371228ed1295ea6754deacf232ef`.
The repeated, identical failure is a visible rack-driver blocker, not a
revision-history, simulator, persistence, or responsiveness failure. No
page-driver change was made under this focused plan.

## Visible Rack Focused Correction And Final Gate

The rack-only real-session regression reproduced the failure without volume
entry, calibration, array start, or printing. Its diagnostics proved that the
target point belonged to the popup viewport, resolved to row 1, and moved the
list focus/current index to row 1. Qt nevertheless suppressed the release
because it occurred inside the combobox popup's post-open mouse-release guard.

The reusable driver now waits for the application's bounded double-click
interval plus 25 ms, capped at 750 ms, before the distinct item press/release.
Selection remains mouse-only and success still requires the authoritative rack
postcondition. Four focused unit tests passed; the rack-only node passed
headlessly and in three fresh visible Windows processes, each cycling all six
replacement heads in under nine seconds.

The targeted offscreen composed node then passed in 396.33 seconds. One fresh
visible run and its exact emitted replay both completed 3,840/3,840 operations
with zero failed actions, failed assertions, or starvation, drained terminal
queues, and no failure traceback. Their reports are retained at:

```text
verification_reports/milestone7-slice8-visible-rack-correction/
  virtual_print_array_384x10_v1/
    20260807T193041485627Z_composed/report.json
    20260807T193834049228Z_composed/report.json
```

Their SHA-256 values are
`e1572ac7f0456661c3eba4d3e8f50aa661512763af6019a342947a6fd686dd69`
and
`598e88bbcfe91b608ba3d8784d4f81ca8307d01ffd8e2878d555fad40508bea1`.
Both reports are warnings only because informational candidate performance
observations fired; neither contains a functional or evidence failure.

## Risks And Next Gate

The synchronous calibration revision-history blocker is resolved without
weakening durability, immutable-history validation, or crash recovery. The
visible rack blocker is also resolved without a View, Controller, Model,
simulator, firmware, protocol, or hardware change. Slice 9 planning may begin.
The complete pytest suite remains deferred to final Milestone 7 validation.

## Rollback

Restore the stress registry/manifest entry to `virtual_print_array`, remove
the thin stress `JourneyDefinition` and focused composed test, and revert the
cardinality/sustained-evidence generalizations only if their passing 24x2 and
96-well consumers are also restored to their prior versions. The reusable rack
Swap and fail-closed Start checks can be retained independently. No hardware,
firmware, protocol, production-data, or migration rollback is required.

The performance amendment can be rolled back independently by removing the
18-line guarded ACTIVE-lock branch and its focused cache assertions. No file
format, migration, protocol, or persisted-data rollback is required.

The revision-history remediation can be rolled back independently by removing
the calibration-specific guarded append transaction and routing calibration
through `_commit_plan_revision()` plus
`_restore_authoritative_session_after_full_revision()` again. Persisted schemas
and existing revision files require no migration.

The visible rack correction can be rolled back independently by removing the
post-open release-guard wait and its focused tests. It changes no production
data, protocol, firmware, simulator timing, or hardware behavior.
