# Milestone 11A Slice 1 Completion Record

Status: complete

Date: 2026-08-08

Commit boundary: `test: define optimizer 360 calibration lifecycle contract`

## Delivered

- Added the standalone typed case module and tracked literal fixture without
  adding a tenth case to the frozen Milestone 10 catalog.
- Stored 360 literal full-factorial reaction rows and 360 literal seed-4321
  reaction-to-well assignments. Rows A–O are covered and every row-P well is
  absent.
- Stored literal non-fill target/count maps and 360 reaction-keyed Water counts
  for prepared and all five calibration checkpoints.
- Expanded truth only through explicit reaction ID, stock ID, and well ID joins.
- Validated five stock identities, five distinct printer heads, the revision and
  session chain, 1,800 unique keys per checkpoint, simulator command bounds,
  pass boundaries, exact aggregate totals, and terminal exact-once truth.
- Kept production Model/View/Controller, optimizer, calibration, assignment, and
  execution code outside the oracle import boundary.

## Frozen hashes

- Fixture SHA-256: `d7f4de4aafeaf4a66751872d017d89393c263d48b5ffefa1b0e1690efaa10783`
- Normalized case SHA-256: `f238d4d90b822fdf52d4170b1f6fc1871b3d73f56df3aad543637f3e5d4078d8`
- Reaction multiset SHA-256: `5acfa8580c581231275e2b6f17ec757d71df5dcc4696196e1c0f9b2176ee7afd`
- Nearest-achievable reaction multiset SHA-256: `418cf4a50cc0015c52b9b093a5df9096df98930dc0f58f42aa37c30830fe64f0`
- Assignment SHA-256: `5f84bfd4cd7c2c0d4b289b6797c50feeab9739a65d56ac2fc3949da030ab3ed2`
- Expanded count-oracle SHA-256: `3f86a60425d2c0d6abf0839d9f0fca16a41a6e398125053dd849d2e9b397458f`

The hashes were re-frozen during Slice 2 after comparison with the user-created
2,000 nL production experiment established that the original 1,800 nL
zero-approximation oracle encoded a different optimizer policy. Production code
was not changed.

## Compatibility evidence

- The Milestone 10 design catalog still contains nine cases and retains
  SHA-256 `15ec261cf19bec2f2758d76f8c8102d0d246eef02ff165a4bdb104b1a9e8dfcd`.
- The Milestone 11 normalized case remains
  `3081ebadd38a9e9de465f67e855ce63a471d7f9092e65e9f7881da1923d509cd`.
- The Milestone 11 fixture remains
  `bf9631efdf2e0ad04e2310b378330a87941d05c157d69a6c47b69b645dbbe118`.

## Validation

` .\env\Scripts\python.exe -m pytest -q tests\test_virtual_workflow_optimizer_360_cases.py tests\test_virtual_workflow_joined_interaction_cases.py tests\test_virtual_workflow_experiment_design_cases.py `

Result: 37 passed.

## Deferred

Qt editor/optimizer execution, calibration Apply, session rotation, five-pass
execution, registry/manifest changes, retained SIL evidence, replay, visible
qualification, lifecycle/regression suites, and the complete Python suite are
deliberately deferred to later slices.
