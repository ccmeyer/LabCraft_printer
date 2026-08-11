# Milestone 8 Slice 1 Completion Record

Date: 2026-08-07

Status: `complete`

## Result

`print_array_mixed_mode_24x2_v1` is an active composed lifecycle scenario. It
uses normal Qt controls to create and execute one 9 nL droplet stock followed
by one 60 nL stream stock, exchanges two distinct virtual heads, applies the
matching mode-specific synthetic calibrations, and performs the real modal
manual-refuel check with two five-droplet trials and a Stable judgment.

The terminal report proves 48/48 durable stock/well completions, two clean pass
boundaries, exact calibration/head/stock identities, one current passed
manual-refuel record, correct Apply -> refuel -> Start ordering, no unexpected
dialogs or starvation, empty terminal queue, clean reconciliation, and clean
teardown. The requested 0.4 psi refuel target is represented by the existing
UI/model conversion as 0.4005 psi and remains within the bounded 0.01 psi
assertion tolerance.

No production View, Controller, Model, simulator, protocol, firmware, Pi, or
hardware code changed. Evidence is synthetic application-contract evidence;
it does not establish physical stream or refuel behavior.

## Focused validation

- Page-driver manual/refuel/calibration tests: 3 passed.
- Action, journey-phase, and manifest contract tests: 146 passed.
- Existing manual-refuel and stream-calibration tests: 22 passed.
- New mixed-mode system module: 2 passed.
- Existing multi-stock and smoke targeted nodes passed after preserving the
  original multi-stock action vocabulary.
- The complete pytest suite was not run; it remains deferred to Milestone 8
  Slice 8 as approved.

## Retained qualification

Offscreen report:

`verification_reports/milestone8-slice1/print_array_mixed_mode_24x2_v1/20260807T213941249323Z_composed/report.json`

SHA-256: `985a1313b935daa5521df99330762fcf5b3808ac147cd74388dc57dcc149235d`

Visible Windows report:

`verification_reports/milestone8-slice1-visible/print_array_mixed_mode_24x2_v1/20260807T214002507379Z_composed/report.json`

SHA-256: `5ebc8ce2743747c010efe28550b129aa0c1795001362a28221db581c4a58d82f`

Exact visible replay report:

`verification_reports/milestone8-slice1-visible/print_array_mixed_mode_24x2_v1/20260807T214025022071Z_composed/report.json`

SHA-256: `b6c03b2a0e6818ae8c5199a654d31fa3c240d52c766e9fec9d1e688ec6976180`

All three reports passed 13/13 required assertions and retained nine
screenshots, action/assertion ledgers, evidence hashes, seed 1, and replay
commands.

## Rollback

Remove the mixed fixture, registry/manifest rows, mixed journey definition,
optional manual-refuel pass fields/driver, and their tests/docs. Existing
droplet journeys retain their default calibration mode and behavior. No data
migration or device-state rollback is required.
