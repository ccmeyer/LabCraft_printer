# Milestone 8 Slice 5 — Completion Record

Status: complete (2026-08-07)

## Delivered behavior

The operator can list, dry-run, execute, and replay the
`mixed_mode_calibration_v1` matrix. Its eight immutable cases cover mixed,
droplet/droplet, and stream/stream stock pairs; both stock orders; baseline and
alternate calibration profiles; passed stable checks; failed level-rise and
level-fall checks; unclear checks; and droplet-only not-applicable checks.

Every case is derived in memory from the unchanged tracked
`print_array_mixed_mode_24x2_v1` fixture. All cases reuse `_multi_body`, typed
stock-pass composition, normal QTest-driven Qt controls, reusable page drivers,
authoritative assertions, report-v1 evidence, and the simulated machine. No
case-specific fixture or journey body was added.

Negative cases perform the real Start action, accept its initial confirmation,
then select Cancel in “Manual Refuel Check Required.” Passing requires the
matching persisted non-pass and calibration fingerprint, unchanged completion
boundary and plan state, no new execution intent, an idle array, drained queue,
empty gripper, closed modal state, returned head, and clean teardown.

The Qt/application-import-free parent resolves and hashes the matrix plan, then
runs all cases sequentially in fresh Python children. It continues after a
failure but fails closed on process, watchdog, report count, report validation,
identity, case/catalog hash, path, or return-code disagreement. The v1 matrix
aggregate references and hashes each authoritative child report rather than
copying its evidence tree.

No production View, Controller, Model, simulator, tracked fixture, capability
manifest, coverage evaluator, protocol, firmware, Pi, scheduling, or hardware
behavior changed. Report-v1 and existing aggregate-v1 remain unchanged.

## Qualification finding and correction

The first complete matrix run passed seven cases and failed the second-stream
negative case. Its retained evidence proved the application safeguard worked:
the failed check matched the active stock/head and fingerprint, Cancel left 24
completions unchanged, the queue drained, and no intent remained. The harness
assertion had incorrectly treated the last iteration entry of a key-sorted
persistence mapping as the latest check. It was corrected to select the
blocked check by both stock and printer-head identity. The focused case and
the complete matrix then passed. No production defect was found.

## Retained qualification evidence

- Complete offscreen matrix: 8/8 pass —
  `verification_reports/matrices/mixed_mode_calibration_v1/20260807T234016700642Z_3cc7e798-874/aggregate.json`,
  SHA-256 `b02ef58a96e9d16dddce8cea2150299ba38ea1f79521ae33c7f93bb07c4797ba`.
- Exact aggregate replay: 8/8 pass —
  `verification_reports/matrices/mixed_mode_calibration_v1/20260807T234123280174Z_a2f7f9af-934/aggregate.json`,
  SHA-256 `b363010de5934c49be367b8b892823be50b7fd4743ca5af0d7b3f6a74bb7fe05`.
- Visible two-stream positive case: 48/48 completions — report SHA-256
  `b65cbfe7f8edd00d39cd934b181326044f5c51d0391bb0e78c0b227f9f0115d6`;
  exact replay report SHA-256
  `7c2af41ccc9b8976a1e6688bd2bdca0f1f3eb5b82d423d9a68590df8f208fdb2`.
- Visible unclear safeguard case: 0/0 completions with safe Cancel — report
  SHA-256 `e44e2b252e793b557a56b09d828d004b3f7b6e9d37820e5ca468621f0fc473aa`;
  exact replay report SHA-256
  `2ad9e71af3eed9e01bef06c8f96238748609b88d5265916cad245b4456e2350c`.

## Focused validation

The unit/contract gate passed 114 tests across matrix catalogs and aggregation,
composition, phases, page drivers, assertions, existing suite aggregation, and
contract freeze. The real-process gate passed four tests covering positive and
blocked matrix cases plus unchanged registered mixed-mode and suite execution.

The complete offscreen matrix, its exact replay, both visible representative
cases, and both exact case replays passed. The complete pytest suite was
intentionally not run and remains deferred to Milestone 8 Slice 8.

## Risks and rollback

Residual risk is concentrated in platform-specific visible dialog timing and
new combinations outside the frozen eight-case catalog. Dialog interactions
remain bounded and fail closed, every selected case is identity-hashed, and
success depends on authoritative state rather than the click alone.

Rollback removes the matrix selector, catalog, aggregate runner, dynamic case
composition, tests, and Slice 5 documentation, and restores the prior reusable
phase/driver defaults and Slice 3 helper organization. Registered fixtures,
scenario reports, suite aggregates, capability evidence, persisted experiments,
production behavior, protocol, firmware, and hardware require no migration.
