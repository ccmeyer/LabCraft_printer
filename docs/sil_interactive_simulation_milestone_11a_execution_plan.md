# Milestone 11A Execution Plan: Optimizer-Driven 360-Reaction Calibration Lifecycle

Status: complete (2026-08-08; retained pre-existing host-stress finding noted
in the Slice 5 completion record)

Date: 2026-08-08

Predecessor: Milestone 11 (complete and immutable)

Next action after closeout: Milestone 12

## Purpose and safety boundary

Milestone 11A adds one Windows-only, on-demand `host_stress` SIL scenario,
`optimizer_360_calibration_reload_execution_v1`. It exercises the production
stock optimizer, five independent calibration/requantization operations, a
clean application-session rotation, 1,800 exact stock/well execution intents,
and terminal authoritative reload for one randomized 360-reaction experiment.

This milestone changes only test/SIL contracts, drivers, assertions,
registration, tests, and documentation. It does not change production MVC,
firmware, protocol, physical-machine behavior, release metadata, or persisted
application-data formats. A production mismatch is a defect signal and requires
a separate reviewed correction plan.

The application call path under qualification is:

`Qt experiment editor -> Controller -> ExperimentModel optimizer -> authoritative design/execution-plan files -> calibration dialog Apply -> Controller -> Model requantization -> clean SimulationSession rotation -> authoritative reload -> explicit Qt activation -> Qt Start Array -> Controller queue/preflight -> durable execution intent -> Machine_FreeRTOS.print_droplets() -> SimulatedMachine DISPENSE -> durable completion/progress -> terminal authoritative reload`.

Expected design, assignment, stock, count, revision, head, and execution values
are literal case-owned truth. Runtime assertions may use the qualified
Milestone 9 count normalizer only to normalize observations. They must never
derive expected truth through production algorithms or list position.

## Frozen case

The frozen contract is stored independently of the nine-case Milestone 10
catalog in
`tools/virtual_workflows/fixtures/optimizer_360_calibration_reload_execution_v1.json`
and `tools/virtual_workflows/optimizer_360_cases.py`. It defines four synthetic
`x` reagents, one optimized stock per reagent, Water fill, 360 literal
full-factorial reactions, seed-4321 randomized assignments to rows A–O of a
384-well plate, and row P exclusion.

The optimizer inputs leave fixed-stock fields blank, disable two-stock
solutions, and require the production-selected concentrations
222.22222222222223/100/555.5555555555555/20. The literal target preview has
seven nearest-achievable targets and zero unreachable targets. All stocks begin
at 9 nL. Range A, Range B, Range C, Range D, and Water are then
calibrated to 10.8/12.6/14.4/16.2/18 nL using distinct heads and pulse widths
1400/1500/1600/1700/1800 microseconds.

The revision chain is 1 prepared, 2 first-calibration lock, 3 Range A applied
and fresh loaded/activated, 4–7 remaining applies, and 8 terminal/reloaded.
Session 1 and session 3 dispatch nothing. Session 2 owns exactly 1,800 intents
and 46,208 droplets in Range A, Range B, Range C, Range D, Water order.

## Slices

### Slice 11A.1 — Typed case and literal oracle

Add the standalone typed case, tracked literal fixture, reaction/assignment and
expanded count hashes, strict identity-join validation, aggregate checkpoints,
and focused contract tests. Preserve the Milestone 10 catalog and all existing
Milestone 11 hashes byte-for-byte.

Commit: `test: define optimizer 360 calibration lifecycle contract`

### Slice 11A.2 — Real editor, optimizer, and first calibration

Drive the real Qt editor with blank fixed stocks and literal maxima. Assert the
exact optimized stocks, 360 reactions, seven literal nearest-achievable targets,
zero unreachable targets,
authoritative reaction/assignment/count truth, and prepared file hashes. Apply
Range A calibration through the real dialog and assert revisions 2–3, zero
progress, exact Range A and Water truth, and unchanged B/C/D truth.

Commit: `test: qualify optimizer 360 editor and first requantization`

### Slice 11A.3 — Fresh rotation and remaining calibration chain

Reuse the branch-free clean authoritative session-rotation phase. Parameterize
the joined lifecycle assertions/orchestration by case-owned stocks, revisions,
milestones, and pass sizes while preserving the Milestone 11 wrapper and
normalized evidence. Prove fresh reconstruction and explicit activation, then
apply Range B, Range C, Range D, and Water and assert all five simultaneous
stock/head/calibration/revision/progress joins.

Commit: `test: add five-stock calibrated session rotation`

### Slice 11A.4 — Execution, terminal reload, and registration

Execute five explicit passes with cumulative boundaries 360/720/1080/1440/1800.
Reconcile begin, attachment, simulator command, durable completion, progress,
and added-count evidence exactly once for 46,208 droplets. Reload terminal
revision 8 without activation. Register the capability and scenario only in
Windows `host_stress`; exclude lifecycle, standard, and Pi suites.

Commit: `test: add optimizer 360 calibration execution stress journey`

### Slice 11A.5 — Qualification and closeout

Retain the 16 frozen screenshots and complete report/evidence manifests using
action cap 160 and simulator evidence cap 10,000. Run offscreen direct and exact
replay, complete `host_stress`, visible direct and exact replay at 20x, focused
tests, existing Milestone 11, lifecycle, host regression, and the default Python
suite. Record exact hashes, artifact sizes, session identities, revision chain,
and totals. Mark Milestone 11A complete without altering Milestone 11 records and
restore Milestone 12 as current next action.

Commit: `test: close optimizer 360 calibration lifecycle qualification`

## Compatibility and rollback

All existing scenario IDs, CLI behavior, action/assertion IDs, schemas, reports,
M9–M11 hashes, catalog order, fixtures, screenshots, and replay behavior remain
unchanged. In particular, `randomized_calibration_reload_execution_v1` retains
revisions 1–6, 24 intents, 80 droplets, and byte-equivalent normalized truth.

Rollback is additive: remove the new case, fixture, scenario/capability/suite
entries, generic wrappers used only by Milestone 11A, tests, and Milestone 11A
documentation. Historical Milestone 9–11 evidence remains untouched.
