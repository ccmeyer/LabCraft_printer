# Milestone 9 Slice 9.5 Completion Record

Status: complete (2026-08-08)

## Outcome

Slice 9.5 completes the eight-case `calibration_requantization_v1` catalog
with the missing-fill safeguard and two-reagent isolation boundaries. Both
cases use the real editor, calibration dialog, Controller/Model execution
contracts, and hardware-isolated simulator. No production MVC, simulator,
firmware, protocol, tracked fixture, or report/matrix schema changed.

The negative case records one valid 9 nL calibration, selects a real
`droplet_to_stream` result at 2500 us / 60 nL, accepts the real mode-switch
confirmation, and observes the production `Apply failed` safeguard. Its
authoritative comparison is scoped immediately before and after the rejected
second Apply, after the normal initial calibration lock already exists.

The positive case derives the unchanged two-reagent reference fixture in
memory. Reagent 1 completes 24 one-drop intents before reagent 2 is
recalibrated from 18 nL / one drop to 9 nL / two drops. It then completes the
remaining 24 stock/well intents without replaying reagent 1.

## Implemented contracts

- Added frozen `MissingFillRequantizationCase` and
  `TwoReagentIsolationCase` catalog types with exact `Fraction` validation.
- Preserved the first six normalized cases and case hashes exactly.
- Added a calibration-driver expected-failure path that retains exact modal
  title, text, icon, selected button, and ordered mode-switch sequence.
- Added required assertion `execution.calibration_apply_fail_closed` and
  report evidence at
  `metrics.persistence.values.calibration_rejection_evidence`.
- Added required assertion `execution.two_reagent_isolation_exact` and report
  evidence at `metrics.persistence.values.two_reagent_isolation`.
- Generalized explicit matrix terminal validation for `completed`,
  `manual_refuel_cancelled`, and `calibration_apply_rejected`.
- Kept report-v1 and matrix plan/aggregate schema version 1 unchanged.

## Frozen catalog identity

- Eight-case catalog SHA-256:
  `d826a9e54c2e6190acfd5afdb0b2475de2be62557647aafa378890ca826c55af`.
- `zero_fill_missing_fill_rejected` case SHA-256:
  `8a3336f8cd834276ea24538cae41e96642b4defbc381f9206cc92db002f623b4`.
- `zero_fill_missing_fill_rejected` representative plan SHA-256:
  `b20a262896745b70e0755afd69a27996bec76289c1e3e0d473c284e2106bcf59`.
- `two_reagent_second_1_to_2_isolated` case SHA-256:
  `c8d294ebc31d2cef6c81c933ad10023d89a7f96f2ada93ec1681e286cd3f7f54`.
- `two_reagent_second_1_to_2_isolated` representative plan SHA-256:
  `06264aa348474ab6e81e8f8bb78637655c6b6b83f6d78a74201754bc9990766c`.
- Mixed-mode catalog and representative plan hashes remain
  `d2439c2e47cb9825ad5a5024e014fd4429ff6b28dcafa54809c92fa674cff884`
  and `543bec9aa811508fcba2bb84e0549054ddbffc6d10bc85ec2ed88353f971ab9f`.

## Retained evidence

| Qualification | Result | Report | Report SHA-256 |
|---|---|---|---|
| missing-fill offscreen replay | pass; 0/0 completions | `verification_reports/matrices/calibration_requantization_v1/20260808T172305473413Z_composed/report.json` | `3439f1a405a4ba8551dea02c486436025e0fe86cfaff5de3d6432f9f282b159e` |
| two-reagent offscreen replay | pass; 48/48 intents, 72 droplets | `verification_reports/matrices/calibration_requantization_v1/20260808T172313002413Z_composed/report.json` | `4835c8f32b3bacde2ef933081109fff301a6e9d2d3c1b03078bcaad980792b5b` |
| missing-fill visible | pass; exact safeguard dialog | `verification_reports/matrices/calibration_requantization_v1/20260808T172327026956Z_composed/report.json` | `0e0c6681170c818d2d85a12be768ae90ee53032978a8dd16bcaf4423ae677d0f` |
| missing-fill visible replay | pass; exact safeguard dialog | `verification_reports/matrices/calibration_requantization_v1/20260808T172336555956Z_composed/report.json` | `27cdda58a0463866855ff116bcbb5b83a1734915e3ba49414bae1ec295f8fa6b` |

The retained negative evidence has all ten safeguard checks passing. Its
durable begin, command attachment, completion, and simulator-dispense counts
are all zero, the preview displays zero reagent drops, and the authoritative
directory inventory and hashes remain exact. The retained positive evidence
has all twelve isolation checks passing, 48 joined non-manual completed
simulator commands, and 72 total commanded droplets.

## Validation

Targeted unit and contract selection:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_sil_calibration_dialog_driver.py `
  tests\test_virtual_workflow_matrices.py `
  tests\test_virtual_workflow_matrix_runner.py `
  tests\test_virtual_workflow_dispense_counts.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_actions.py `
  tests\test_virtual_workflow_page_drivers.py `
  tests\test_virtual_workflow_authoritative_evidence.py `
  tests\test_virtual_workflow_journey_phases.py `
  tests\test_virtual_workflow_composition.py `
  tests\test_virtual_workflow_contract_freeze.py
```

Result: `176 passed in 7.02s`.

Selected fresh-process system tests:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_matrix_execution.py `
  -k "zero_fill_missing_fill_rejected or two_reagent_second_1_to_2_isolated or missing_fill_requantization or two_reagent_requantization"
```

Result: `2 passed, 5 deselected in 13.00s`.

Both individual offscreen cases and their retained replay commands passed.
The missing-fill case also passed visibly and by exact visible replay.

Per the milestone validation policy, Slice 9.5 did not run the complete
eight-case matrix, mixed-mode matrix, lifecycle suite, host regression, or
unselected Python suite. Those run once in Slice 9.6.

## Risk and rollback

This is SIL verification infrastructure only. It makes no physical
calibration, pressure, motion, protocol, firmware, or droplet-quality claim.
The completed first reagent is normal positive progress, not refill/resume;
volume tracking remains disabled and refill-required coverage remains
deferred.

Rollback removes the two final catalog entries, expected-failure driver path,
two new assertions/evidence fields, focused tests, and documentation while
retaining Slices 9.1-9.4. Historical reports require no migration or deletion.

Slice 9.6 is the current next action.
