# Audit Test Gaps

## Scope
- Date: 2026-02-26
- Commit/Branch: Working tree audit of `FreeRTOS-interface/` only
- Intent: Open test gaps only (resolved/covered gaps removed for triage clarity).

## Gap Triage (Open Only)
- Total open gaps: 4
- Dedupe notes:
  - Removed covered View designer reopen/lock items from active queue (Milestone M4 complete).
  - Retained only unresolved hardware-free gaps tied to open issues or explicit coverage debt.

## Model

| Gap ID | Related Issue ID | Area | Risk | Verification | Missing Test |
|---|---|---|---|---|---|
| (none open) | - | - | - | - | - |

## Controller

| Gap ID | Related Issue ID | Area | Risk | Verification | Missing Test |
|---|---|---|---|---|---|
| GAP-C-003 | n/a (coverage debt) | `Controller.print_array` | Medium | Simulate queue-nonempty/profile/refill/last-well branches and assert orchestration | Integration-lite print-array branch matrix |
| GAP-C-005 | AUD-2026-020 | `Controller.move_to_location` legacy path | Low | Assert `safe_z=5000` behavior/order in legacy profile | Legacy safe-height routing test |

## Comms Boundary

| Gap ID | Related Issue ID | Area | Risk | Verification | Missing Test |
|---|---|---|---|---|---|
| GAP-X-004 | AUD-2026-014 | `Machine._on_goodbye_done` | Medium | Measure close/disconnect responsiveness under event loop | Disconnect timing responsiveness test |

## View

| Gap ID | Related Issue ID | Area | Risk | Verification | Missing Test |
|---|---|---|---|---|---|
| GAP-V-003 | AUD-2026-011 | startup/view boot resilience | Low | Validate startup behavior when settings payload is missing/corrupt and UI still initializes safely | App/View startup fallback smoke test |

## Priority Backlog (Hardware-Free First)
- [x] Model atomic-write and exclusion-reset resilience (`GAP-M-001`, `GAP-M-002`)
- [x] Protocol boundary hardening (`GAP-X-001`, `GAP-X-002`, `GAP-X-003`)
- [x] View designer lock/reopen regressions (`GAP-V-001`, `GAP-V-002`)
- [ ] Controller branch coverage (`GAP-C-003`) and legacy routing (`GAP-C-005`)
- [ ] Disconnect timing responsiveness (`GAP-X-004`) and startup fallback smoke (`GAP-V-003`)

## Deferred (Needs Hardware / HIL)
- [ ] Validate real UART timing jitter assumptions during CLEAR/GOODBYE handling.
- [ ] Validate gripper confirmation timing/UX with real hardware latency.
- [ ] Validate camera trigger/flash timing on target Pi + MCU.
