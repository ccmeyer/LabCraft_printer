# Milestone 9 Slice 4 Implementation Plan

Status: implementation authorized (2026-08-08)

## Objective

Extend `calibration_requantization_v1` with three deterministic positive
cases: a multi-target reagent with changed and unchanged counts, the existing
40 nL to 10.8 nL stream-to-droplet transition followed by execution and a
fresh-session terminal reload, and positive fill-stock requantization with
unchanged non-fill targets.

The application call path remains:

```text
Qt editor / calibration UI
-> Controller
-> authoritative ExperimentModel plan and progress
-> Machine_FreeRTOS DISPENSE boundary
-> hardware-isolated SimulatedMachine completion
-> persisted terminal bundle
-> optional fresh-session read-only terminal reload
```

No production MVC, simulator, firmware, protocol, existing fixture,
report-v1, matrix-plan, or aggregate-schema behavior will change.

## Frozen cases

| Case | Prepared and calibrated counts | Positive intents |
|---|---|---:|
| `droplet_multi_target_10_to_9_and_1_to_1` | non-fill odd wells `1 -> 1`, even wells `10 -> 9`; fill odd wells `8 -> 8`, even wells `0 -> 0` | 36 |
| `stream_to_droplet_40_to_10_8` | non-fill `4 -> 15`; fill `121 -> 121` | 48 |
| `fill_volume_decrease_4_to_5` | non-fill `6 -> 6`; fill `4 -> 5` | 48 |

The multi-target case assigns the low target to `A1, A3, ..., A23` and the
high target to `A2, A4, ..., A24`. Positive nearest-integer groups retain
exact rational boundary margins of at least one third of a drop; zero fill
uses an explicit nonnegative-clamp rule.

## Implementation

1. Add frozen grouped count, calibration-step, and composite-case types while
   preserving the first three normalized case payloads and hashes.
2. Build the three cases in memory from the unchanged tracked reference
   fixture, including explicit fill-role stocks and ordered calibration steps.
3. Generalize editor inputs for reaction cardinality, fill settings, target
   lists, and replicate overrides without changing existing defaults.
4. Generalize pass execution for applied-mode calibration, expected mode
   switches, positive-intent completion boundaries, and support-stock passes.
5. Extend count reconciliation with grouped oracle schema 2, multi-row
   preview projection, aggregate fill-preview validation, and zero-intent
   filtering while retaining schema 1 unchanged.
6. Add fresh-session completed-execution inspection and exact terminal bundle
   comparison for the stream-to-droplet case.
7. Generalize matrix assertions and add focused unit, contract, and selected
   fresh-process system coverage plus operator documentation.
8. Run only targeted Slice 9.4 qualification, inspect and replay the three new
   cases, write the completion record, and commit independently.

## Compatibility and validation policy

- Preserve report-v1 and matrix plan/aggregate schema version 1.
- Preserve the mixed-mode catalog and representative plan hashes exactly.
- Preserve the first three requantization normalized payloads and case hashes.
- Freeze the expanded catalog and representative new-case plan hashes after
  the canonical payloads are finalized.
- Run the selected Slice 9.4 tests and each new case individually. Do not run
  the complete six-case matrix, mixed-mode matrix, lifecycle/host regressions,
  or full Python suite; those remain reserved for Slice 9.6.

## Rollback

Remove the three appended cases, grouped-oracle support, editor/pass
generalizations, and terminal reload inspection while retaining Slices
9.1-9.3. Historical reports require no migration or deletion.
