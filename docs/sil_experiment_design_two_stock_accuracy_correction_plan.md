# Experiment-Design Two-Stock Accuracy Correction Plan

Status: complete after explicit authorization (2026-08-08)

This is the separate production-correction plan required by the Milestone 10
guardrail. The user explicitly authorized its implementation after reviewing
the blocked Slice 10.3 evidence. No firmware, protocol, hardware, motion,
pressure, printing, or physical-calibration work is in scope.

## Defect statement

For targets `[0.1, 0.2] mM`, 10 nL droplets, 500 nL final volume, and a 10 nL
printed-volume budget, the exact two-stock solution is `(5 mM, 10 mM)` with
one droplet from the corresponding stock per target. Production instead
selects `(3.333333333335 mM, 10 mM)`. The `0.1 mM` target is reconstructed as
`0.0666666666667 mM`, even though the exact pair is feasible at the same
maximum printed volume.

The defect is deterministic and independent of SIL orchestration:

1. `_candidate_single_stock_deltas()` supplies candidate deltas.
2. `_enumerate_two_stock_candidates_with_meta()` constructs feasible pairs.
3. Its Pareto pass sorts only by `(concentration sum, maximum volume)` and
   removes the exact `(0.1, 0.2)` delta pair because `(0.066666..., 0.2)` has a
   lower concentration sum at the same volume.
4. `_refine_two_selection()` scores accuracy only after that pruning, so it
   cannot recover the removed exact pair.

The retained SIL report is:
`verification_reports/m10-s3-dev/experiment_design_pairwise_v1/20260808T203129604021Z_composed/report.json`,
SHA-256
`4ecfe471dd702aae8f6edb5e5273a2b1d2c0633b406ae7cf25a457efb243122b`.

## Exact call path

```text
Qt ExperimentDesignDialog Optimize and Generate
-> ExperimentDesignDialog._run_design_optimization_flow()
-> ExperimentModel.optimize_stock_solutions(allow_two=True)
-> ExperimentModel._enumerate_two_stock_candidates_with_meta()
-> concentration/volume-only Pareto pruning removes exact candidate
-> ExperimentModel._refine_two_selection() sees only approximate candidate
-> plans_per_option + target preview
-> ExperimentModel.generate_experiment()
-> MainWindow.complete_experiment_design()
-> Model.load_experiment_from_model(finalize_execution_plan=True)
-> authoritative design / plan / key / concentration files
```

The editor design path directly owns an `ExperimentModel`; Controller does not
mediate optimization. MainWindow and the application Model participate only
after accepted editor finalization. No comms or firmware handler is reached.

## Recommended correction

Preserve candidates needed for the existing accuracy refinement instead of
Pareto-pruning solely by concentration burden and volume. The preferred small
change is to make two-stock pruning accuracy-aware using the already-defined
`_score_two_stock_plan()` ordering (worst absolute error, mean absolute error,
concentration burden, then volume), while retaining the current pair cap and
deterministic ordering. Do not special-case the Milestone 10 inputs or derive
expected outputs from the test catalog.

Material alternative: remove the early Pareto prune and let
`_refine_two_selection()` score the full bounded pair set. That is simpler but
could increase retained candidate count and downstream search cost, so it is
not the recommended first implementation.

## Initial files expected to change

- `FreeRTOS-interface/Model.py`
- `tests/test_experiment_forced_stock_preview.py`
- focused optimizer regression tests if a separate test module gives a
  clearer boundary
- this correction plan's completion record, if implementation is approved

No View, Controller, protocol, firmware, matrix schema, or catalog file should
need modification for the correction itself.

## Proposed implementation and validation steps

1. Add a focused failing unit test that proves the exact 5/10 mM candidate is
   retained and selected for the stated bounded design.
2. Add a nearby regression proving lower-error ordering wins at equal maximum
   volume without violating max-stock or pair-cap behavior.
3. Implement the smallest deterministic accuracy-aware pruning change in
   `Model.py`.
4. Run the focused optimizer, forced-stock, stock-input, preview, and execution
   plan tests.
5. Run the full default Python suite because this is a production optimizer
   correction with broad design impact.
6. Re-run only Milestone 10 Slice 10.3 selected cases and exact replays; verify
   the independent 5/10 mM oracle, exact concentration rows, and no regression
   in the one-stock case.
7. Record performance/candidate-count evidence, risks, rollback, and the exact
   correction commit before resuming Slice 10.3.

## Compatibility, risks, and rollback

Required unchanged contracts include fixed-stock behavior, maximum-stock
bounds, single-stock selection, pair caps, deterministic ordering, volume
budget safety, target-preview semantics, authoritative schemas, and all
Milestone 7-9 matrix identities. The change must not weaken unreachable-target
or capacity rejection.

Primary risks are larger candidate retention, slower optimization, or changed
stock selection for existing designs. Bound candidate counts in tests and
compare affected optimizer outputs explicitly. If existing approximate choices
change, accept them only when error ordering improves without exceeding the
same volume/bound constraints.

Rollback is the isolated correction commit. Reverting it restores the prior
optimizer selection; Slice 10.3 remains blocked rather than weakening its
independent exact oracle.

## Entrance and exit criteria

Entrance requires explicit review/authorization of this production behavior
change. Exit requires focused and full Python suites to pass, exact 5/10 mM
selection and target reconstruction, bounded performance evidence, no schema
or hardware-scope change, a completion record, and a clean correction commit.
Only then may Milestone 10 Slice 10.3 restart from clean commit `fa6ed5c` plus
the reviewed correction commit.
