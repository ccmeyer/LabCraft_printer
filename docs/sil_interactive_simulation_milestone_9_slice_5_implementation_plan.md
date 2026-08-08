# Milestone 9 Slice 9.5 — Missing-Fill Safeguard and Two-Reagent Isolation

Status: implementation authorized (2026-08-08)

## Summary

Complete the eight-case `calibration_requantization_v1` catalog by appending:

1. a zero-fill case whose real UI calibration Apply would require an absent
   fill stock and must fail without changing the authoritative execution; and
2. a two-reagent case where the first reagent has already completed, the
   second reagent is recalibrated from one to two drops, and all first-reagent
   identity, assignment, count, and progress evidence remains exact.

The application-facing call paths are:

```text
Negative safeguard
Qt Editor -> valid 9 nL calibration Apply
-> authoritative ACTIVE execution with zero progress
-> second real calibration preview and droplet-to-stream confirmation
-> rejected Apply because one missing fill drop would be required
-> byte-identical authoritative bundle and zero execution dispatch

Positive isolation
Qt Editor -> Controller -> authoritative two-reagent plan
-> reagent 1 calibration and completed stock pass
-> reagent 2 calibration Apply
-> exact isolated plan/progress/runtime retargeting
-> Machine_FreeRTOS DISPENSE -> SimulatedMachine completion
-> persisted terminal reconciliation
```

No production MVC, simulator, firmware, protocol, existing fixture,
report-v1, matrix-plan, or aggregate-schema changes are authorized. A
production defect found by the new assertions requires a separate reviewed
correction plan.

## Catalog additions

Preserve the first six normalized cases and case hashes exactly. Append these
cases in order:

| Case ID | Prepared state | Requested result | Terminal outcome |
|---|---|---|---|
| `zero_fill_missing_fill_rejected` | 24 wells, one 10 mM reagent at a 10 mM target, 9 nL printed/final volume, one 9 nL reagent drop, no fill stock | after one accepted idempotent 9 nL calibration, request a `droplet_to_stream` result at 2500 us / 60 nL; hypothetical reagent count `1 -> 0`, leaving one absent 9 nL fill drop | `calibration_apply_rejected`, 0 completions |
| `two_reagent_second_1_to_2_isolated` | 24 wells, reagent 1 at 3.0x/1.0x and 9 nL, reagent 2 at 1.5x/1.0x and 18 nL; one drop of each and zero fill | reagent 1 remains 9 nL / one drop; after its 24 completed intents, reagent 2 changes to 9 nL / two drops | `completed`, 48 stock/well intents |

Frozen stock identities for the positive case are:

- `Virtual Multi Stock 01_3.00_x`;
- `Virtual Multi Stock 02_1.50_x`.

The count oracle is independent of production requantization:

- missing-fill reagent request: `9/60 = 3/20`, nearest count 0, boundary
  margin `7/20`; residual fill is exactly `9/9 = 1`, margin `1/2`;
- two-reagent support stock: requested 9 nL, `9/9 = 1`, margin `1/2`;
- two-reagent target stock: requested 18 nL, prepared `18/18 = 1` and
  calibrated `18/9 = 2`, both with margin `1/2`.

The positive case therefore retains 48 durable intents but commands 72 total
drops: 24 for reagent 1 and 48 for reagent 2. Fill remains absent in both
cases. Neither case uses a two-stock solution; each reagent maps to exactly one
execution stock, consistent with the production calibration UI contract.

## Types and evidence contracts

Add frozen catalog descriptors in `matrices.py`:

- `MissingFillRequantizationCase`, containing the prepared design, accepted
  calibration, rejected calibration request, hypothetical reagent/fill
  counts, exact margins, expected warning fragment, and terminal outcome;
- `TwoReagentIsolationCase`, containing ordered reagent definitions,
  calibration steps, grouped schema-2 count truth, primary stock identity,
  completion cardinality, and the requirement that the first pass precede the
  primary calibration.

The negative fixture retains a
`lifecycle.calibration_rejection_oracle` schema version 1. It must identify:

- the exact accepted and rejected calibration candidates;
- the before/after plan state expected at the rejected boundary (`active`);
- prepared, hypothetical reagent, and hypothetical missing-fill counts;
- the required `Apply failed` title and message fragment
  `would require a fill stock that is absent`;
- zero expected intents, simulator dispenses, pass boundaries, and
  completions;
- one accepted persisted calibration record and no rejected record.

The positive fixture continues to use `dispense_count_oracle` schema version
2. Generalize its validation only enough to support two non-fill stock
identities and positive progress in a non-target stock. Existing schema-1 and
schema-2 payloads remain valid and unchanged.

Add required assertions:

- `execution.calibration_apply_fail_closed` for the negative case;
- `execution.two_reagent_isolation_exact` for the positive case.

Retain additive evidence at:

- `metrics.persistence.values.calibration_rejection_evidence`;
- `metrics.persistence.values.two_reagent_isolation`;
- the existing `dispense_count_evidence` path for the positive count layers.

No report schema version changes are required.

## Fail-closed negative boundary

The negative journey will use the real editor and calibration dialog, not a
direct Model call:

1. Create the 24-well, one-reagent 9 nL design and prove its prepared plan has
   one non-fill stock, one drop per well, and no fill stock.
2. Stage the deterministic head and Apply a real idempotent droplet result at
   1300 us / 9 nL. This establishes the normal calibration lock, one linked
   calibration record, and an `ACTIVE` zero-progress execution.
3. Generate and select a real `droplet_to_stream` result at 2500 us / 60 nL,
   inspect the exact visible zero-drop preview, and capture the authoritative
   bundle, revision history, directory bytes, runtime targets, head settings,
   queue, and observer state immediately before Apply.
4. Accept the real `Apply calibration as mode switch?` confirmation, capture
   the real `Apply failed` dialog and message, then dismiss it through QTest.
5. Re-capture the same evidence and require exact equality.

`CalibrationDialogDriver` will gain a bounded expected-failure Apply path that
returns the modal title, text, icon, selected button, and mode-switch sequence,
and captures screenshot `calibration_apply_blocked` while the warning is
visible. Unexpected titles, text, extra dialogs, or a missing modal fail the
case.

The fail-closed assertion must prove:

- plan ID, revision, state, lock reason, design hash, full plan JSON, revision
  history, progress, resume state, calibration document, key files, audit
  rows, and authoritative file hashes are byte-identical across the rejected
  Apply;
- runtime targets, well/reaction assignments, stock/head linkage, printing
  mode, pulse width, pressure, and gripper/queue state are unchanged;
- the accepted calibration record remains the only persisted execution-
  calibration record and no applied stream record or manual-refuel requirement
  appears;
- no `array.start_via_ui` action, durable intent begin/attachment/completion,
  or simulator `DISPENSE` occurs;
- completion count and pass-boundary count remain zero, array state is idle,
  and cleanup releases the session lock.

## Positive isolation boundary

Derive the positive fixture in memory from the unchanged
`print_array_multi_stock_24x2_v1.json` reference:

- keep reagent 1 at prepared/applied 9 nL, pulse 1300 us, one drop per well;
- keep reagent 2 prepared at 18 nL, but Apply pulse 1300 us / 9 nL before its
  pass, changing its count from one to two drops per well;
- keep printed and final volume at 27 nL and fill at zero;
- execute reagent 1 first, reaching 24 completed intents, before opening the
  reagent 2 calibration boundary.

Capture an isolation snapshot immediately before and after reagent 2 Apply.
The new assertion must prove:

- the plan ID and design hash are stable and the plan revision advances by
  exactly one with an append-only contiguous history;
- all 24 well/reaction assignments and ordered stock identities are unchanged;
- reagent 1 retains target 1 and added progress 1 in every well, its effective
  volume, mode, calibration record, printer-head identity, and completed
  intent set are unchanged;
- reagent 2 alone changes target `1 -> 2`, remains at zero added progress at
  Apply, and receives the new 9 nL calibration/head linkage;
- no fill stock or fill count is introduced;
- preview, calibrated plan, progress targets, runtime targets, reagent 2
  intents, simulator commands, terminal targets, and terminal additions all
  equal two drops by exact stock/well identity;
- reagent 1 is not replayed after its completed boundary and all 48 unique
  stock/well intents finish with 72 total commanded/completed drops.

## Implementation plan

1. Add this implementation-plan document and update only the master plan's
   current-next-action text; preserve the targeted-per-slice/full-at-9.6
   policy.
2. Add the two frozen case types, exact rational validation, in-memory fixture
   builders, and ordered catalog entries. Reject half ties, insufficient
   margins, wrong stock/well membership, incorrect hypothetical fill truth,
   wrong transition direction, and altered reaction/completion cardinality.
3. Extract the reusable calibration-step phase needed to apply multiple
   candidates to one stock. Add an expected-rejection result without changing
   the existing successful stock-pass behavior.
4. Implement the negative Apply driver/evidence path and fail-closed assertion,
   including byte-level authoritative comparison and zero-dispatch observer
   checks.
5. Generalize the editor/fixture and schema-2 reconciliation contracts for two
   non-fill reagents, then add the before/after primary-calibration isolation
   assertion while preserving all earlier cases.
6. Generalize matrix outcome validation by explicit terminal kind:
   `completed`, `manual_refuel_cancelled`, or
   `calibration_apply_rejected`. Derive required actions, screenshots, and
   assertions from the selected typed case.
7. Add focused catalog, driver, phase, assertion, composition, contract, and
   fresh-process tests; update README and the SIL operator runbook.
8. Run the targeted qualification, inspect and replay both new cases, write
   the Slice 9.5 completion record, advance the master plan to Slice 9.6, and
   commit independently as `test: complete calibration requantization SIL catalog`.

## Files

Modify:

- `tools/virtual_workflows/matrices.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/journey_phases.py`
- `tools/virtual_workflows/page_drivers.py`
- `tools/virtual_workflows/dispense_counts.py`
- `tools/virtual_workflows/assertions.py`
- focused matrix, runner, count, action, driver, phase, composition, contract,
  and system tests
- `README.md`
- `docs/sil_virtual_workflow_operator_runbook.md`
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`

Add:

- `docs/sil_interactive_simulation_milestone_9_slice_5_implementation_plan.md`
- `docs/sil_interactive_simulation_milestone_9_slice_5_completion_record.md`

The tracked reference fixture remains unchanged. No files under
`FreeRTOS-interface/` or `firmware/` are planned for modification.

## Test and acceptance plan

Focused tests must cover:

- exact eight-case order, normalized payloads, catalog hash, new case hashes,
  and representative plan hashes;
- unchanged first six requantization case hashes and all mixed-mode hashes;
- rejection of half ties, margins below `1/3`, duplicate/incomplete
  stock/well groups, wrong missing-fill count, wrong terminal kind, incorrect
  primary reagent, and altered 24-well/48-intent cardinality;
- immutable reference fixture bytes and correct derived zero-fill and
  two-reagent workloads;
- exact real dialog order and message for the rejected Apply;
- failure on any plan, history, progress, resume, calibration, assignment,
  runtime, settings, file-hash, intent, simulator, queue, or action mutation at
  the rejected boundary;
- failure when reagent 1 changes or replays, reagent 2 does not change exactly
  `1 -> 2`, fill appears, assignments move, revisions skip, or total commanded
  drops differ from 72;
- unchanged report-v1, matrix plan/aggregate v1, replay, timeout, process
  isolation, and prior case behavior.

Run only selected unit and contract tests:

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

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_matrix_execution.py `
  -k "zero_fill_missing_fill_rejected or two_reagent_second_1_to_2_isolated"
```

Run each new case individually offscreen, never the complete eight-case matrix
during Slice 9.5:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --matrix calibration_requantization_v1 `
  --case <new-case-id> `
  --output-root verification_reports\matrices `
  --seed 1 `
  --speed-multiplier 1000 `
  --timeout-seconds 90 `
  --qt-platform offscreen
```

Execute both retained replay commands. Also run and replay
`zero_fill_missing_fill_rejected` once with `--visible` so the exact safeguard
dialog and blocked-state screenshot are operator-inspected.

Retained evidence must show:

- the negative preview displays zero reagent drops, the mode-switch prompt is
  accepted, and `Apply failed` reports the exact missing-fill reason;
- the negative bundle remains byte-identical with one accepted calibration,
  zero intents, zero simulator dispenses, zero completions, and no array start;
- the positive previews display 1 and 2 drops, reagent 1 completes before the
  reagent 2 Apply, and only reagent 2 target counts change;
- exactly 48 unique intents and simulator commands complete, with 72 total
  droplets and no fill dispatch;
- no hardware access, unexpected dialog, timeout, queue starvation, duplicate
  intent, or report/process disagreement occurs.

Finish with `git diff --check`. Do not run the complete requantization matrix,
mixed-mode matrix, lifecycle suite, host regression, or unselected
`pytest -q`; those remain reserved for Slice 9.6.

## Assumptions, risk, and rollback

- The negative case establishes one accepted calibration before the rejected
  request because production intentionally locks a PREPARED plan when the
  first calibration starts. Byte-identical comparison is scoped from
  immediately before the second Apply to immediately after its rejection.
- A completed first-reagent pass is intentional positive progress, not a
  refill/resume scenario. Volume tracking remains disabled and no
  refill-required operation is introduced.
- The case-local stream candidate and print profiles are SIL-only in-memory
  data and make no physical calibration claim.
- Two-stock reagent auto-application remains excluded; this case contains two
  independent single-stock reagents.

Rollback removes the two appended cases, rejected-Apply evidence path,
two-reagent isolation assertion, focused tests, and documentation while
retaining Slices 9.1-9.4. Historical reports need no migration or deletion.
