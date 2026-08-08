# Experiment-Design Two-Stock Accuracy Correction Completion Record

Status: complete (2026-08-08)

Commit boundary: `fix: retain accurate two-stock optimizer candidates`

## Authorization and scope

The user explicitly authorized the separate correction plan after Slice 10.3
exposed a production optimizer defect. The correction changes only the
experiment-design optimizer and focused tests. It does not change View,
Controller, authoritative schemas, SIL schemas, firmware, protocol, hardware,
motion, pressure, printing, timing, or physical-calibration behavior.

Exact affected call path:

```text
Qt ExperimentDesignDialog Optimize and Generate
-> ExperimentDesignDialog._run_design_optimization_flow()
-> ExperimentModel.optimize_stock_solutions(allow_two=True)
-> ExperimentModel._enumerate_two_stock_candidates_with_meta()
-> bounded concentration/volume and accuracy-aware candidate retention
-> ExperimentModel._refine_two_selection()
-> plans_per_option + exact target preview
-> accepted editor finalization -> authoritative persistence
```

Controller, comms, and firmware are not reached by the optimizer correction.

## Correction

The existing Pareto pass retained only the concentration/volume frontier. At
the same 10 nL printed volume it therefore discarded exact `(5 mM, 10 mM)` in
favor of lower-concentration but inexact `(3.333333333335 mM, 10 mM)` before
the established accuracy refinement could compare them.

The enumerator now retains both:

- the historical concentration/volume frontier; and
- the best existing accuracy score at each feasible printed-volume tier.

It reuses the optimizer's established ordering of worst absolute error, mean
absolute error, concentration burden, and maximum volume. Enumeration remains
bounded by the unchanged pair scan/result cap and deterministic sort. For the
regression input it retains two candidates, both at 10 nL, without hitting the
12,000-pair cap. Final refinement selects `(5 mM, 10 mM)` and reconstructs
both `0.1 mM` and `0.2 mM` targets with zero error.

No Milestone 7-9 fixture, hash, catalog, report, replay, or persistence schema
changed.

## Validation

Focused defect regressions, before correction:

```text
2 failed, 39 deselected in 1.86s
```

The failures proved the omitted exact candidate and selected inexact stocks.

Focused defect regressions, after correction:

```text
2 passed, 39 deselected in 1.85s
```

Complete forced-stock/preview optimizer module:

```text
41 passed in 5.64s
```

Stock-input, tooltip/preview, reaction-preview, and execution-plan regression
set:

```text
139 passed in 5.06s
```

Complete default Python suite:

```text
4137 passed, 80 skipped, 389 warnings in 249.09s
```

Warnings are the existing Qt deprecations. The slow offline analysis pipeline
remained excluded by the repository's default test contract.

The Slice 10.3 cases and exact replays are intentionally not part of this
isolated correction commit: their temporary harness implementation was
discarded at the guardrail and no executable cases 3-4 exist at this boundary.
They are the first mandatory validation after Slice 10.3 restores that
additive harness scope.

## Risks, limitations, and rollback

The retained candidate set can be larger than the historical frontier, but it
cannot exceed the existing bounded pair result cap. Focused evidence shows two
candidates for the defect input and the full suite found no optimizer or
lifecycle regression. Existing stock choices may improve when a lower-error
candidate at the same volume was previously pruned; that is the authorized
behavior change.

Rollback is the isolated correction commit. Reverting it restores the prior
selection behavior and must also re-block Slice 10.3 rather than weakening its
independent exact oracle.

## Next action

Restart Slice 10.3 from its committed implementation plan. Reintroduce only
the one-stock/two-stock feasibility harness changes, run both selected cases
and exact replays, inspect the retained 5/10 mM evidence, and commit the slice
only after all exit criteria pass.
