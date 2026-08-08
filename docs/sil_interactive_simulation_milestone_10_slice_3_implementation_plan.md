# Milestone 10 Slice 10.3 Implementation Plan

Status: blocked before implementation acceptance (2026-08-08)

## Blocking evidence

The clean Slice 10.2 baseline can execute `one_stock_feasible`, but the first
selected `two_stock_required` diagnostic exposed a production optimizer
defect. The exact `(5 mM, 10 mM)` pair is feasible at one 10 nL droplet per
target, yet `ExperimentModel._enumerate_two_stock_candidates_with_meta()`
Pareto-prunes it in favor of `(3.333333333335 mM, 10 mM)` because the latter
has lower concentration sum at the same 10 nL maximum volume. The later
accuracy refinement never sees the exact pair. The resulting authoritative
plan achieves only `0.0666666666667 mM` for the requested `0.1 mM` target
(`0.0333333333333 mM` absolute error).

Retained failure report:

- `verification_reports/m10-s3-dev/experiment_design_pairwise_v1/20260808T203129604021Z_composed/report.json`
- SHA-256:
  `4ecfe471dd702aae8f6edb5e5273a2b1d2c0633b406ae7cf25a457efb243122b`

The harness changes used to expose this boundary were discarded. No
production change, executable catalog expansion, oracle change, or Slice 10.3
commit was accepted. Work may resume only after the separate optimizer
correction plan is reviewed and completed.

## Objective and non-goals

Append only `one_stock_feasible` and `two_stock_required` to the executable
experiment-design matrix. Prove the literal one-stock solution and the normal
Qt one-stock rejection -> two-stock checkbox -> successful regeneration path,
then preserve exact authoritative reload and reconstructed assignments.

Do not add wells/exclusions, alternate randomization, capacity boundaries,
terminal negative cases, production MVC changes, printing, firmware, protocol,
hardware, motion, pressure, or physical-calibration behavior.

## Exact call path

```text
matrix selector -> fresh child -> experiment_design journey
-> typed case -> ExperimentEditorDriver
-> Qt reagent inputs with fixed stock blank and maximum stock bound
-> Optimize and Generate
-> Model.optimize_stock_solutions(... allow_two=False)
-> case 3: literal 5 mM one-stock result
or case 4: Optimization failed warning/status, dirty editor, no authoritative mutation
-> Qt Allow Two Stock Solutions checkbox
-> Optimize and Generate
-> Model.optimize_stock_solutions(... allow_two=True)
-> literal 5 mM + 10 mM two-stock result
-> Finalize Design -> authoritative plan/progress/key/concentration files
-> Qt directory reload -> saved-plan projection with runtime inactive
-> exact stock/count/concentration/assignment assertion -> report-v1
```

## Initial files expected to change

- `tools/virtual_workflows/experiment_design_cases.py`
- `tools/virtual_workflows/matrices.py`
- `tools/virtual_workflows/actions.py`
- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/journeys.py`
- focused action/assertion/matrix/catalog/contract tests
- `tests/system/test_virtual_workflow_experiment_design_matrix.py`
- this slice completion record and Milestone 10 Current Next Action text

No production file or tracked fixture is expected to change.

## Implementation steps

1. Extend the executable catalog prefix from two to four cases and re-freeze
   only the additive prefix/plan hashes.
2. Project typed optimization attempts into editor inputs without deriving
   expected stocks or counts from production code.
3. Generalize the editor driver to record an expected optimization warning,
   prove the editor stays dirty/unfinalized, toggle the real two-stock control,
   and regenerate through QTest.
4. Make the composed action contract case-specific while leaving the legacy
   editor sequence unchanged.
5. Extend exact oracle evidence for the ordered formulation transition and
   ensure both positive outcomes still reload byte-identically.
6. Add focused and fresh-process tests for cases 3-4; run only those selected
   CLI cases and exact replays.
7. Run/replay `two_stock_required` visibly, inspect warning/control/stock rows,
   retain evidence, run `git diff --check`, record completion, and commit as
   `test: add formulation feasibility design SIL cases`.

## Contracts, evidence, and validation

Case 3 must contain exactly `Feasibility A_5.00_mM` plus the independently
expected fill stock/count rows. Case 4 must first show `Optimization failed`
with `Enable two-stock mode`, remain unfinalized with no authoritative
execution artifact mutation, then expose exactly
`Feasibility A_5.00_mM` and `Feasibility A_10.00_mM` after the normal checkbox
transition. Both cases must preserve plan revision 1, zero progress,
`ready_to_start`, inactive runtime, byte-identical reload, exact key and
concentration rows, and exact reconstructed assignments.

Run the Slice 10.2 focused command plus the relevant optimizer/UI contract
tests, then only the two new fresh-process parametrizations. Run each selected
case and its exact replay; run `two_stock_required` and its replay visibly.
The complete matrix and full Python suite remain deferred to Slice 10.6.

## Compatibility, risks, rollback, entrance, and exit

Keep cases 1-2, Milestone 7-9 catalog hashes, report-v1, matrix plan/aggregate
v1, replay formatting, fixture SHA, legacy editor action order, and hardware
isolation unchanged. Reuse the existing
`editor.regenerate_prepared_design_via_ui` vocabulary for the second explicit
generation step; do not add unreferenced manifest vocabulary.

Risks are modal timing, confusing an expected optimization rejection with a
journey failure, stale stock preview, and oracle drift. Fail closed on dialog
title/text/order, dirty state, finalization absence, any execution-artifact
mutation, or extra/missing stock/count evidence. A production defect stops
the slice for a separate reviewed correction plan.

Entrance is clean Slice 10.2 commit `fa6ed5c`. Exit requires both new cases,
their replays, the visible representative/replay, focused tests, evidence
inspection, completion record, `git diff --check`, and an independent clean
commit. Rollback reverts only that commit and restores the two-case prefix.
