# Milestone 7 Slice 6 Completion Record

Status: `complete on 2026-08-06`

Planning baseline: `1db0ce658329cb9dbd17b2f18422b08e27bef54c`.

## Delivered Scope

Only `experiment_editor_post_start_lock_v1` was migrated from the legacy
editor runner to generic `composed_journey` dispatch. The fixture remained
byte-identical with SHA-256
`37EB774BC484C875F4B4115FCBCCA4E7AE3C511D6FF21302CCC512681B532FD2`.
No production MVC, simulator-response, firmware, protocol, Pi, or hardware
file changed.

The composed journey now:

- creates and finalizes the A1/A2 source through normal editor controls;
- records authoritative activation and the synthetic zero-progress
  `printing_started` lock as `model`, never UI;
- drives locked-state inspection, rejected in-place editing, editable-copy
  creation, tolerance editing, optimization, and finalization through QTest;
- proves the source remains byte-identical and the copy is a distinct fresh
  revision-1 `PREPARED` execution without progress, resume, calibration, or
  inherited history;
- reloads the prepared copy through the real editor folder dialog without
  activating it; and
- emits the standard report, action/assertion ledgers, evidence manifest,
  hashes, seed, replay command, ten screenshots, and generic teardown facts.

`ExperimentEditorDriver` is the single owner of the post-start raw QTest and
modal mechanics. The direct parity oracle delegates to that driver and the
same authoritative evidence/assertion policy.

## Code Shape

- named composed body: 80 physical lines (gate: 110);
- composed payload builder: 38 physical lines (gate: 70);
- scenario-specific journey additions: 217 physical lines (gate: 220);
- total touched runtime net growth: 367 physical lines (gate: 450); and
- `actions.py` plus `page_drivers.py` raw-driver move: net -2 physical lines.

The registry gained no scenario-ID branch, and no harness, session rotation,
fixture, report schema, or production implementation changed.

## Validation Results

Targeted reusable unit/contract gate:

```text
172 passed in 4.23s
```

Targeted production-adjacent lock/copy gate:

```text
81 passed in 4.65s
```

Retained direct fixture/success/failure oracle after delegation:

```text
3 passed in 4.24s
```

Final composed success/parity/two-failure gate:

```text
4 passed in 122.13s
```

The broader focused editor selection initially produced 11 passes and three
rename/refinalize summary failures caused by a displaced return block. After
the contained correction, the exact three affected nodes passed:

```text
3 passed in 63.21s
```

The visible run and its exact emitted replay both passed with nine of nine
assertions, 25 ordered action rows, ten screenshots, hardware access disabled,
byte-identical source evidence, a fresh inactive prepared copy, and equal
stable projections. Retained local evidence roots:

```text
verification_reports\milestone7-slice6-visible\experiment_editor_post_start_lock_v1\20260807T055629501987Z_composed
verification_reports\milestone7-slice6-visible\experiment_editor_post_start_lock_v1\20260807T055637920975Z_composed
```

The complete Python suite was intentionally not run. It remains the final
Milestone 7 validation gate, as requested.

## Risks And Rollback

The two Model setup actions could be mistaken for UI coverage; their frozen
ledger surfaces and README limitation prevent that claim. The source/copy
directory snapshots fail closed on mutation or inherited runtime evidence,
and controlled-failure tests retain diagnostic artifacts and clean teardown.

Rollback is limited to restoring this scenario's registry/manifest entry to
`experiment_editor`, removing its composed definition, phase/assertions, and
new composed tests, and restoring the legacy local driver only if delegation
is implicated. Existing Milestone 7 migrations, the unchanged fixture,
production data, firmware, protocol, Pi, and hardware remain untouched.

## Next Step

Create a separate concrete plan before migrating the 96-well regression.
