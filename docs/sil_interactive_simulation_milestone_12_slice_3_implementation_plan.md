# Milestone 12 Slice 12.3 Implementation Plan

Status: complete (2026-08-09)

## Objective and exclusions

Qualify the calibration/settings, durable-identity, and lifecycle preflight
boundaries in `execution_preflight_safeguards_v1` through real Qt operator
actions and the Slice 12.1 oracle. Use compact scenario-owned state except the
three explicitly permitted reduced multi-stock identity derivatives. Do not
change production override policy, execute the complete optimizer-360 journey,
add refill behavior, mutate user data, or touch firmware, protocol, physical
settings, or Milestone 13.

## Call paths and evidence boundary

```text
calibration tab / Calibrate All -> Controller calibration mode/profile preflight
-> operator Cancel -> no generation, Apply, settings command, or calibration revision

Start / Resume -> View applied-calibration/settings preflight
-> Controller.print_array() -> authoritative identity/lifecycle preflight
-> exact cancellation/rejection before pass preparation or dispatch

editor / saved execution / rack control -> lifecycle enablement and validation
-> disabled control or exact rejection -> unchanged design/runtime/rack/queue state
```

The case baseline is captured after isolated setup and immediately before the
declared operator action. Negative post-action snapshots must match it across
durable design, plan, progress, stock, head and calibration IDs; persistence;
lifecycle; rack/queue; and intents, commands, completions, and drops. The
reordered-row positive control compares keyed projections while remaining
inactive and dispatch-free.

## Files to change

- add `tools/virtual_workflows/execution_preflight_safeguards.py`
- add `tools/virtual_workflows/fixtures/execution_preflight_safeguards_v1.json`
- `tools/virtual_workflows/safeguards.py`
- `tools/virtual_workflows/actions.py`
- `tools/virtual_workflows/page_drivers.py`
- `tools/virtual_workflows/journey_phases.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/matrices.py`
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`
- focused unit/system tests for the new catalog, drivers, matrix, report, and
  adjacent calibration/identity/lifecycle behavior
- this plan, its completion record, the Milestone 12 execution plan, and the
  authoritative-plan current-slice text

No production MVC file is planned to change. A production fail-open result is
a separate reviewed defect and cannot be normalized into the expected oracle.

## Steps

1. Freeze the literal ordered case catalog with durable identity keys.
2. Build compact prepared/calibrated/progressed state through existing editor,
   head-staging, calibration, reload, and lifecycle helpers.
3. Add only missing QTest Cancel and invalid lifecycle-action mechanics.
4. Capture exact UI outcome and the shared boundary for each real action.
5. Register the typed Windows-SIL matrix and reusable manifest actions.
6. Add contract, mutation, driver, journey, identity, and report tests.
7. Qualify all fresh children, aggregate/replay, and four required visible
   direct/replay representatives.
8. Run adjacent regressions and `git diff --check`, then retain fingerprints
   and completion evidence.

## Acceptance, risk, and rollback

Every invalid action must match its literal code, title, message, selected
button or disabled-control evidence and pass the shared no-mutation/no-dispatch
oracle. No case may accidentally activate, resume, prepare a pass, revise a
plan/calibration, or move a head. The reordered-row control must join by durable
ID and remain inactive. Primary risks are intentional override paths, setup
commands leaking into the action baseline, positional joins, and races around
active queues; the driver records selected controls, baselines after setup,
uses bounded quiescent states, and stops immediately at the boundary.

Rollback removes this catalog, its reduced case-owned derivative, matrix and
safeguard-only driver/journey branches, tests, and slice documents. It leaves
earlier slices, user experiments, production behavior, and the immutable
Milestone 11A positive control unchanged.
