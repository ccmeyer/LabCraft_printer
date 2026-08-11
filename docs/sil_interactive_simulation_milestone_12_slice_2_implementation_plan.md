# Milestone 12 Slice 12.2 Implementation Plan

Status: complete (2026-08-09)

## Objective and exclusions

Qualify the compact editor safeguard family through real Qt operator controls
and the Slice 12.1 exact-outcome/no-mutation/no-dispatch oracle. The slice does
not activate or execute a plan, calibrate, mutate persisted fault copies,
change production MVC behavior, modify the frozen Milestone 10 catalog, or
touch the immutable Milestone 11A scenario.

## Call path and evidence boundary

```text
Qt editor fields / Upload Design / printable-well selection / Finalize
-> dialog-local input validation and optimizer/generator where applicable
-> exact QMessageBox or visible invalid-state rejection
-> no successful MainWindow.complete_experiment_design() handoff
-> safeguard boundary capture
-> shared exact-outcome/no-mutation/no-dispatch assertion
-> report-v1 matrix child evidence
```

The baseline is captured after isolated setup and immediately before the
operator action. The post-action capture occurs immediately after the expected
modal is dismissed. Both captures cover case-owned files, model identity and
revision, editor lifecycle, controller/queue state, and machine intents,
commands, completions, and simulator drops.

## Files to change

- `tools/virtual_workflows/safeguards.py`
- add `tools/virtual_workflows/editor_safeguards.py`
- add `tools/virtual_workflows/fixtures/editor_safeguards_v1.json`
- `tools/virtual_workflows/actions.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/matrices.py`
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`
- `tests/test_virtual_workflow_safeguards.py`
- add `tests/test_virtual_workflow_editor_safeguards.py`
- focused action, journey, matrix, manifest, assertion, and report tests if
  registry contracts require updates
- this implementation plan, its completion record, the Milestone 12 execution
  plan, and authoritative-plan current-slice text

No production file is planned to change. A production fail-open result stops
the slice for a separate reviewed defect correction.

## Steps

1. Define eight literal, durable-ID-keyed editor cases without changing the
   frozen Milestone 10 catalog.
2. Build each case from the existing editor reference fixture in memory.
3. Reuse the current Qt editor action driver and add only missing compact
   pre-Finalize mutation and upload-wizard mechanics.
4. Translate exact UI and boundary evidence into the Slice 12.1 oracle.
5. Register the family as a typed Windows-SIL matrix and register its reusable
   UI action in the capability manifest. The repository's v1 capability
   manifest accepts report-producing scenarios, not matrix aggregates; the
   aggregate-to-capability evidence join remains a Slice 12.5 closeout item.
6. Add contract, driver, report, and matrix tests including mutation failures.
7. Run every case directly and through the registered matrix in fresh child
   processes; retain reports and fingerprints.
8. Run adjacent regressions and `git diff --check`, then record acceptance,
   risk, and rollback evidence.

## Acceptance, risk, and rollback

Every case must perform its declared Qt action, match literal code/title/text
and selected control, leave the dialog safely unaccepted, and prove no model,
lifecycle, persistence, queue, intent, command, completion, drop, activation,
or resume drift. Cases stop at their rejection boundary. Inputs and expected
values are catalog literals, not production-algorithm output.

Primary risks are accidentally reusing stale generated truth, setup mutation
leaking into the action baseline, platform-specific file-dialog behavior, and
over-broad message matching. Drivers therefore baseline after setup, record
exact text, and use only case-owned CSVs. Rollback removes the separate catalog,
matrix registration, tooling branches, tests, and Slice 12.2 documents; it does
not touch production or user experiment data.
