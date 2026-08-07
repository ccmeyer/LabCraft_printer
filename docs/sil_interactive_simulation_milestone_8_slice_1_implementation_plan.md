# Milestone 8 Slice 1 Implementation Plan

## Objective

Register one deterministic 24-well mixed droplet/stream lifecycle through the
existing composed SIL runner. The journey must drive normal Qt controls,
perform the real application manual-refuel modal workflow, retain exact
calibration/refuel evidence, complete 24 operations per stock, and close
cleanly without adding a runner family or changing production MVC behavior.

## Call path

`QTest controls -> View -> Controller -> Model -> SimulatedMachine`.

The stream boundary continues through the normal calibration Apply prompt,
deferred `ManualRefuelCheckDialog` launch, two five-droplet paired trials,
Stable outcome persistence, and the normal array-start preflight.

## Implementation

1. Add and strictly validate `print_array_mixed_mode_24x2_v1` as a schema-v4
   two-stock fixture.
2. Extend `StockPassSpec` with droplet-compatible calibration/refuel defaults
   and a typed optional manual-refuel contract.
3. Add a reusable bounded QTest driver for the real nested manual-refuel modal.
4. Compose the scenario through the existing multi-stock body and stock-pass
   runner, including named screenshots and truthful UI action surfaces.
5. Add persisted mixed-calibration and stream manual-refuel assertions plus
   additive `report-v1` evidence.
6. Register the scenario, action, assertions, capability, and lifecycle-suite
   membership in the validated manifest.
7. Run focused unit/system tests, an offscreen run, one visible Windows run,
   and the exact visible replay. Defer the full suite to Milestone 8 Slice 8.

## Safety, failure handling, and rollback

Unexpected dialogs, modal timeouts, stale calibration fingerprints, failed
trial clicks, ambiguous persistence, or an uncleared modal fail closed and
retain normal failure artifacts. The scenario is application-facing SIL only;
it makes no physical stream, refuel, pressure, protocol, firmware, or hardware
claim. Rollback removes the new fixture/registration and optional workflow
fields while retaining the previous droplet defaults and composed journeys.
