# Milestone 9 Slice 2 Implementation Plan

## Objective

Retain exact calibration-preview cells and exact stock/well dispense counts
across authoritative plan, progress, reconstructed runtime, durable intent,
simulator command, and terminal progress boundaries. Add no requantization
matrix cases; independent expected count oracles begin in Slice 9.3.

## Call paths

- `Calibration UI -> preview model -> rendered table -> Apply -> authoritative
  plan/progress/runtime retargeting`.
- `Array UI -> Controller -> durable Model intent -> Machine_FreeRTOS DISPENSE
  -> simulator completion -> persisted terminal progress`.

The slice is observation-only with respect to the application. It does not
change production MVC, simulator behavior, firmware, protocol, fixtures,
matrix catalogs, or physical-hardware behavior.

## Implementation

1. Add exact visible-table capture to the calibration page driver while
   preserving its existing preview fields.
2. Retain commanded intent counts and bounded simulator DISPENSE command
   evidence through instance-local, restorative instrumentation.
3. Add deterministic stock/well count capture, strict preview projection, and
   fail-closed reconciliation helpers.
4. Capture prepared and per-calibration before/after plan, progress, runtime,
   and preview evidence in the shared mixed-mode journey.
5. Require exact self-consistency for the existing mixed-mode journey and
   completed matrix cases; retain the evidence additively in report-v1.
6. Run only focused unit, contract, one composed lifecycle, one fresh-process
   case, and that case's exact replay.
7. Inspect retained evidence, record results, and commit the slice
   independently.

## Compatibility gates

- No production matrix definition or case is added.
- Existing mixed-mode catalog and representative plan hashes remain frozen.
- report-v1 and matrix schema versions remain unchanged.
- Existing CLI selection, listing, dry-run, and replay behavior remain
  unchanged.
- Independent expected requantized counts remain outside this slice.

## Validation policy

Slices 9.2-9.5 run targeted tests only. Slice 9.6 runs the complete eight-case
requantization matrix, lifecycle and host regressions, and the full Python
suite. Slice 9.2 does not run the existing complete mixed-mode matrix or an
unfiltered `pytest -q` invocation.

## Safety and rollback

Malformed, duplicate, incomplete, ambiguous, overflowing, or mismatched count
evidence fails closed. Observer hooks are instance-local and restored during
teardown. Rollback reverts the page-driver, observer, reconciliation,
assertion, and report additions together; retained historical evidence needs
no cleanup or migration.
