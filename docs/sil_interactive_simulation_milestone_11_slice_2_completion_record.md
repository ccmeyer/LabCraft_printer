# Milestone 11 Slice 11.2 Completion Record

Status: complete (2026-08-08)

## Scope completed

Slice 11.2 composes the unregistered first application-session checkpoint for
`randomized_calibration_reload_execution_v1`. It creates and finalizes the
qualified seed-4321 multi-reagent design through the real Qt editor, joins the
authoritative revision-1 files to the literal case, stages Design A through
the real machine/rack controls, and applies the real 1800 us / 18 nL
calibration through the calibration dialog. Read-only assertions prove the
resulting authoritative revision-3 state, its calibration/head/plan/progress
joins, exact stock/well counts, and zero execution progress.

The partial journey remains deliberately unregistered. It cannot activate or
start an array, rotate/reload a session, calibrate the remaining stocks, emit
an accepted scenario report/replay, or reach terminal completion. No
production MVC, persisted schema, firmware, protocol, motion, pressure, or
physical-machine behavior changed.

## Files changed

- `tools/virtual_workflows/journey_phases.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/joined_interaction_cases.py`
- `tools/virtual_workflows/fixtures/randomized_calibration_reload_execution_v1.json`
- `tests/test_virtual_workflow_journey_phases.py`
- `tests/test_virtual_workflow_joined_interaction_cases.py`
- `tests/test_virtual_workflow_contract_freeze.py`
- `tests/system/test_virtual_workflow_randomized_calibration_lifecycle.py`
- `docs/sil_interactive_simulation_milestone_11_slice_2_implementation_plan.md`
- `docs/sil_interactive_simulation_milestone_11_slice_2_completion_record.md`
- the Milestone 11 execution plan, Slice 11.1 records, and only the Milestone
  11 current-action text in the master plan, corrected to the observed literal
  oracle.

## Contract and evidence

The reusable `CalibrationOnlySpec` and phase have a bounded nine-action
sequence: stock/head identity bind, real print settings/volume/staging,
pressure regulation, and real calibration Open/Generate/Select/Apply. The
phase contains no array start, resume, refill, or terminal transition.

The selected offscreen Qt run proved:

- the literal mapping `A1..A8 -> R8,R6,R3,R2,R7,R4,R1,R5` at seed 4321;
- one stable plan ID and design SHA across revisions `1,2,3`, with states
  `prepared,active,active`;
- Design A record/head identity `virtual-head-m11-design-a-v1`, 1800 us, and
  18 nL joined simultaneously to the calibration store and revision-3 plan;
- Design B remains exactly `3,3,1,3,1,3,1,1` and uncalibrated;
- dependent Water is authoritatively requantized from its prepared 60-drop
  map to `6,6,8,6,8,6,8,8` (56 droplets);
- all target comparisons use `(stock_id, well_id)` keys;
- resume remains absent, eligibility is `ready_to_start`, runtime is inactive,
  added/completed/intents/simulator dispatch are zero, and teardown is clean;
- screenshots `design_generated`, `prepared_randomized`, and
  `calibrated_zero_progress` were captured.

The first real Apply corrected the planning-only provisional Water literals.
It also established the later Design B calibration at count-stable 1400 us /
10.8 nL. The corrected frozen hashes are:

- joined-case SHA-256:
  `3081ebadd38a9e9de465f67e855ce63a471d7f9092e65e9f7881da1923d509cd`;
- fixture-byte SHA-256:
  `bf9631efdf2e0ad04e2310b378330a87941d05c157d69a6c47b69b645dbbe118`;
- normalized count-oracle SHA-256:
  `468d78216fd52f326898c5b5625f6ae591995c642118a72ddb1cdf0cb5790814`.

The terminal case truth remains 24 unique keyed intents and 80 droplets:
Design A `8/8`, Design B `8/16`, and Water `8/56`.

## Validation

Focused unit, contract, composition, authoritative-evidence, manifest, and
adjacent Milestone 9/10 command:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_joined_interaction_cases.py `
  tests\test_virtual_workflow_journey_phases.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_authoritative_evidence.py `
  tests\test_virtual_workflow_experiment_design_cases.py `
  tests\test_virtual_workflow_dispense_counts.py `
  tests\test_virtual_workflow_manifest.py `
  tests\test_virtual_workflow_contract_freeze.py `
  tests\test_virtual_workflow_composition.py
```

Result: `219 passed`.

Selected direct offscreen real-Qt checkpoint:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_randomized_calibration_lifecycle.py
```

Result: `1 passed`, with 14 existing Qt deprecation warnings. The direct
harness reported no hardware interface, no unexpected dialog, no timeout,
zero execution events, three screenshots, and a clean removed session lock.
No accepted scenario report or replay exists for this intentionally partial
lifecycle.

## Compatibility, risks, rollback, and next action

All Milestone 9/10 source hashes, catalogs, selectors, reports, replays,
authoritative reload contracts, and negative no-mutation evidence remain
unchanged. Existing editor assertions retain their original default milestone
capture behavior; the joined caller explicitly selects its smaller evidence
sequence. The Milestone 9 count normalizer is used only on observations while
all expected mapping, calibration, stock, and count truth remains literal and
case-owned.

The primary remaining risk is cross-session leakage or identity drift during
fresh authoritative reconstruction. Rollback is the independent Slice 11.2
commit; reverting it removes the calibration-only phase, joined assertions,
focused system checkpoint, and records without migration or production
rollback.

Full lifecycle execution, report/replay, visible qualification, host
regressions, and the complete Python suite remain deferred. The current next
action is Slice 11.3: add and prove the lifecycle-neutral clean-session
rotation, real authoritative reload, and explicit activation boundary.
