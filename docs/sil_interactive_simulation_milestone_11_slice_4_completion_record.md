# Milestone 11 Slice 11.4 Completion Record

Status: complete (2026-08-08)

## Scope completed

Slice 11.4 completes and registers the single typed Milestone 11 scenario,
`randomized_calibration_reload_execution_v1`. Starting from Slice 11.3's fresh
active revision-3 session, the journey applies the remaining Water and Design B
calibrations through the real dialog, verifies count-stable revision 5, executes
Design A, Design B, and Water through ID-keyed pre-calibrated passes, reaches
completed revision 6, and reconstructs terminal truth read-only in a third
fresh application session.

The implementation adds reusable calibration-return and pre-calibrated stock-
pass composition, exact remaining-calibration and terminal reconciliation
assertions, report-v1 evidence, scenario/capability registration, and lifecycle
suite membership. `RackDriver.confirm_and_load()` now accepts both legitimate
real-UI states: `Confirm` for a newly assigned head and `Load` for a previously
confirmed returned head. It rejects every other state.

No production MVC, firmware, protocol, physical-machine, persisted application-
data schema, report schema, refill/resume, safeguard, or release behavior
changed. No physical hardware or Pi stress path was accessed.

## Files changed

- `tools/virtual_workflows/journey_phases.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/page_drivers.py`
- `tools/virtual_workflows/registry.py`
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`
- `tests/test_virtual_workflow_journey_phases.py`
- `tests/test_virtual_workflow_joined_terminal_assertions.py`
- `tests/test_virtual_workflow_joined_interaction_cases.py`
- `tests/test_virtual_workflow_manifest.py`
- `tests/test_virtual_workflow_selection.py`
- `tests/test_virtual_workflow_contract_freeze.py`
- `tests/system/test_virtual_workflow_randomized_calibration_lifecycle.py`
- the Slice 11.4 implementation plan and this completion record
- only the Milestone 11 execution status/current-action planning text.

## Exact call path and contracts

The completed call path is:

```text
fresh active revision 3
-> real Qt Water calibration Apply/return -> revision 4
-> real Qt Design B calibration Apply/return -> revision 5
-> literal keyed plan/progress/runtime and calibration/head joins
-> real Qt Design A/B/Water array starts
-> Controller -> Machine_FreeRTOS -> SimulatedMachine DISPENSE
-> durable intent completion -> persisted progress at 8/16/24
-> completed revision 6
-> clean close -> third application session
-> real Qt completed read-only load -> exact terminal reconciliation
```

The scenario preserves case SHA-256
`3081ebadd38a9e9de465f67e855ce63a471d7f9092e65e9f7881da1923d509cd`,
fixture SHA-256
`bf9631efdf2e0ad04e2310b378330a87941d05c157d69a6c47b69b645dbbe118`,
and count-oracle SHA-256
`468d78216fd52f326898c5b5625f6ae591995c642118a72ddb1cdf0cb5790814`.
The frozen randomization seed remains `4321`, and every expected mapping,
calibration, stock, and count remains literal and case-owned. The Milestone 9
oracle is used only to normalize observed `(stock_id, well_id)` rows.

Exact assertions prove revisions 1-6, three stock/head/calibration-record joins,
24 unique durable intents, 24 unique command attachments, 24 completed
simulator DISPENSE commands, 24 unique completions, 80 commanded and persisted
droplets, active/active/completed pass boundaries at 8/16/24, no discard,
overflow, starvation, or unexpected error, and three distinct application
sessions. Session 1 and terminal session 3 dispatch nothing. Terminal reload is
completed, `analysis_only`, inactive, and count-identical without activation.

## Validation

Focused joined unit, contract, phase, composition, manifest, selection, report,
and compatibility tests completed with `205 passed`. Pure terminal mutation
coverage completed with `9 passed`; mutations reject wrong counts, missing or
duplicate command attachment/sequence, failed simulator completion, duplicate
completion, pass-order/boundary drift, and overflow.

The final direct and registered real-Qt system rerun, together with terminal
unit coverage, completed with `11 passed` and 90 existing Qt deprecation
warnings:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_joined_terminal_assertions.py `
  tests\system\test_virtual_workflow_randomized_calibration_lifecycle.py `
  --run-sil-lifecycle --basetemp .tmp\m11-slice4-final-20260808c
```

Selected historical synthetic calibration, authoritative reload, and two-
reagent requantization compatibility checks completed with `3 passed` and 25
existing Qt deprecation warnings. `git diff --check` passed.

During focused development, the first complete run exposed the legitimate
returned-head `Load` state and a diagnostic observer callback initially read
`current_pass` before execution began. Both issues were confined to the SIL
driver/harness: the driver now accepts the two explicit valid states, and the
callback returns no pass context until a pass is active. The complete direct
and registered journey passed after those corrections.

## Evidence, compatibility, risks, and rollback

Focused runs retained all eleven named screenshots, three application-session
records, exact inventories/hashes, revision/calibration evidence, action and
assertion ledgers, pass boundaries, terminal files, and report/replay fields.
They are diagnostic evidence only. New source-current retained direct/replay,
visible/replay, lifecycle-suite/replay, and host-regression/replay evidence is
deliberately deferred to Slice 11.5.

All Milestone 9/10 hashes, catalogs, historical scenario order, selectors,
runners, report/replay grammar, paused and terminal reload contracts, and
negative no-mutation evidence remain compatible. The only selection change is
the intentional append of the completed scenario to the lifecycle suite.

Residual risk is evidence qualification rather than implementation: stale or
mixed-source artifacts must not be accepted. Slice 11.5 must use one clean
committed Slice 11.4 source identity for every retained run and replay.
Rollback reverts the independent Slice 11.4 commit, removing the registered
scenario/capability, complete journey, terminal assertions, and pre-calibrated
pass phase while retaining Slice 11.3's independently tested clean-session
rotation phase.

The current next action is Slice 11.5: source-current retained offscreen and
visible qualification with exact emitted replays, lifecycle and host-
regression compatibility suites/replays, complete Python validation, retained-
evidence audit, operator documentation, and Milestone 11 closeout.
