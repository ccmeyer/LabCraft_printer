# Milestone 12 Slice 12.1 Completion Record

Status: complete

Date: 2026-08-08

Commit boundary: cumulative Milestone 12 worktree; one final milestone commit
is required after Slice 12.5.

## Delivered

- Added strict, schema-versioned safeguard outcome, case, catalog, and isolated
  persistence-fault contracts.
- Added canonical literal JSON normalization and SHA-256 fingerprints.
- Rejected positional identity keys so later cases must join by durable design,
  plan, progress, stock, printer-head, and calibration identities.
- Confined persistence fault specifications to portable relative paths beneath
  a scenario-owned case copy and required distinct before/fault hashes.
- Added a boundary snapshot covering persistence, model, lifecycle, queue, and
  dispatch evidence. Dispatch coverage requires machine intents, commands,
  completions, and drops.
- Added the shared exact-outcome/no-mutation/no-dispatch assertion as a
  report-v1-compatible `AssertionResult`.
- Kept production UI, Controller, Model, persistence, workflow, machine,
  simulator, firmware, and protocol code outside the slice.

## Focused evidence

Command:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_safeguards.py `
  tests\test_virtual_workflow_authoritative_evidence.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_report.py `
  tests\test_virtual_workflow_contract_freeze.py
```

Result: `81 passed in 6.12s`.

The tests prove exact contract round trips and stable hashes; reject unknown,
empty, non-manifest, positional, active, activating, and path-escaping inputs;
and mutation-test each persistence, model, lifecycle, queue, dispatch, typed
outcome, UI, code, and safe-state comparison independently.

Source fingerprints at this review checkpoint:

- `tools/virtual_workflows/safeguards.py`:
  `d7614a6e3425858949eba67465cadd530375d21489d43e58086c59c88cc08eeb`
- `tests/test_virtual_workflow_safeguards.py`:
  `71a79c7337215a63429f4672b0c50f8ff67156c3100b707578705d37149384fc`

Slice 12.3 extended the original inactive-only expectation so the same oracle
can prove exact preservation of a pre-existing active or stop-requested
boundary. This is a contract correction, not a relaxation: runtime state must
now equal the case's literal expected value before and after the action,
activation count must remain zero, and all other lifecycle, persistence,
model, queue, and dispatch fields remain exact. The corrected shared source
fingerprint is
`39100e74b4ce5d990e8e6dd8c65c85e9f120bf60f931c73463a41c20a76c11a9`.

`git diff --check` passed. No executable safeguard case exists in this slice,
so no direct SIL, manifest, fresh-process, replay, visible-mode, retained
report, screenshot, or lifecycle claim is made.

## Risks and rollback

Later slices must populate snapshots only after setup and must not omit state
that their action can mutate. Exact equality deliberately fails closed if a
driver accidentally dispatches or activates. Rollback removes the new contract
module, focused tests, and Slice 12.1 documents; it does not touch production
or user experiment data.

## Deferred

Real operator-action editor cases, execution-preflight cases, isolated
persistence cases, manifest registration, retained evidence, replay,
visible-mode qualification, the immutable Milestone 11A compatibility run,
and the complete Python suite remain assigned to Slices 12.2-12.5.
