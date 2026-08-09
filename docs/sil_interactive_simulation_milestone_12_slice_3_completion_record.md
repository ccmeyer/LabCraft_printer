# Milestone 12 Slice 12.3 Completion Record

Status: complete

Date: 2026-08-09

Commit boundary: cumulative Milestone 12 worktree; one final milestone commit
is required after Slice 12.5.

## Delivered

- Added the literal 17-case `execution_preflight_safeguards_v1` catalog for
  calibration mode/settings, applied-calibration validity, durable stock/head
  identity, row-order independence, activation/edit/recalibration, start,
  resume, and head-transfer lifecycle boundaries.
- Used compact case-owned fixtures and durable design, plan, progress, stock,
  printer-head, and calibration identifiers. The three multi-stock identity
  cases are reduced derivatives; the optimizer-360 positive control was not
  used or changed.
- Exercised real Qt calibration dialogs, the main-window Start Array flow and
  its confirmation/preflight choices, production message boxes, and real
  array-button state. Focused product-adjacent tests retain the production
  Controller/Model guard results separately from the UI-driving mechanics.
- Applied the shared exact-state/no-dispatch oracle at every action boundary,
  including pre-existing active and stop-requested states, without requiring
  an inactive baseline.
- Registered the family in the Windows-SIL matrix registry and its reusable
  operator actions in the capability manifest. Aggregate-to-capability
  evidence remains a Slice 12.5 closeout item.
- Kept production MVC, firmware, protocol, hardware, refill, and optimizer-360
  files unchanged.

## Frozen contracts

- source catalog canonical SHA-256:
  `66f7f4724e2ece43f525fdeddd60970b9ba992b5c9e2919fbe09d06eb15ff7d1`;
- registered matrix catalog SHA-256:
  `0a4169cfc5f844e25cc02c1af74ab9b26b01d82a9703470b85adfc0b0ed763c2`;
- source JSON file SHA-256:
  `f35a6aa52104cfe182d2f2853f699993406bbe1af4a5eee4ea70cc5dcbcb94fd`;
- shared contract/oracle source SHA-256:
  `39100e74b4ce5d990e8e6dd8c65c85e9f120bf60f931c73463a41c20a76c11a9`;
- execution-preflight catalog source SHA-256:
  `fdc4849d0ef326fd47c31126aa0833a21ab6434d55e52583131cc2e6efbc2dda`.

Expected codes, classifications, titles, messages, choices, control states,
workflow states, and durable identities are catalog literals and do not call
production algorithms to compute their expected values.

## Executable evidence

The source-current fresh-child matrix passed 17/17:

`verification_reports/m12_slice3_matrix_final/execution_preflight_safeguards_v1/20260809T073114438524Z_48c55a49-4a9/aggregate.json`

Aggregate SHA-256:
`780d9641ccba7da2edbe908fd8d7e7faf7b6138f5f4479594eb1d9bbb9bc0ff3`.
Its exact replay passed 17/17 at
`verification_reports/m12_slice3_replay_final/execution_preflight_safeguards_v1/20260809T073214124220Z_d1b3772f-812/aggregate.json`, SHA-256
`e248d917900aba299863736bc6eebab07fc22ed6b04fb47a05fcc2e8774afe19`.

Four Windows-visible representatives and their replays passed and were
manually inspected. Direct/replay rejection screenshot hashes matched:

- missing applied calibration:
  `93b32655a3866cf5e4892c71d1e16e329e0adc5373c30603803811bb4ba30b38`;
- wrong printer-head identity:
  `579629e08d8806af6d0f064c625bd7b835c54ca5b6079882cd791ba1b3eff3b8`;
- progressed-stock recalibration:
  `f55ad8ebc228debf946a45728aa31e3725c1d95e8613c936325299d19c2815b7`;
- invalid-boundary head exchange:
  `a127cbdb680bb84404e03d8ef59f600d0b77f1ac8b32c378493c5893309ebb0a`.

## Focused validation

- safeguard/preflight/action/journey/matrix/manifest/persistence-adjacent unit
  selection: `237 passed in 5.62s`;
- real-Qt fresh-process system family with `--run-sil-lifecycle`:
  `17 passed in 55.21s`;
- matrix direct and replay: `17/17` pass each;
- visible direct and replay: `8/8` pass;
- source compilation: pass.

The new unit and system tests have SHA-256
`3606d1bfc0ddbeb638e5a192857b8978c06095df2708a5feff6a70e5f89ad8c4`
and `8cedfbfc721ed2a58664f40f1f8e27648d3356f04718a486e55a2bea42133be4`.

## Risks and rollback

The matrix deliberately separates compact UI-boundary driving from focused
production guard-producer tests so rejected cases stop before preparation or
dispatch. Its principal risks are a positional identity comparison, an
override selecting Proceed instead of Cancel, or a pre-existing active state
being mistaken for activation caused by the action; frozen durable keys,
selected-control evidence, exact before/after snapshots, and zero activation
delta address those risks.

Rollback removes this catalog, its matrix/journey/driver branches, tests, and
slice documents, and restores the Slice 12.1 inactive-only oracle only if all
active-boundary cases are removed as well. It does not touch user data,
production behavior, or the immutable Milestone 11A positive control.

## Deferred

Isolated persistence corruption/classification, final capability-evidence
registration, combined replay/visible qualification, Milestone 11A
compatibility, and the complete Python suite remain assigned to Slices
12.4-12.5. Milestone 13 remains unstarted.
