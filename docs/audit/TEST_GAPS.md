# Audit Test Gaps

## Scope
- Date: 2026-02-26
- Commit/Branch: Working tree audit of `FreeRTOS-interface/` only
- Intent: Open test gaps only (resolved/covered gaps removed for triage clarity).

## Gap Triage (Open Only)
- Total open gaps: 1
- Dedupe notes:
  - Removed covered View designer reopen/lock items from active queue (Milestone M4 complete).
  - Removed legacy routing coverage gap after Milestone M5 completion.
  - Removed startup fallback and disconnect timing gaps after Milestone M6 completion.

## Model

| Gap ID | Related Issue ID | Area | Risk | Verification | Missing Test |
|---|---|---|---|---|---|
| (none open) | - | - | - | - | - |

## Controller

| Gap ID | Related Issue ID | Area | Risk | Verification | Missing Test |
|---|---|---|---|---|---|
| GAP-C-003 | n/a (coverage debt) | `Controller.print_array` | Medium | Simulate queue-nonempty/profile/refill/last-well branches and assert orchestration | Integration-lite print-array branch matrix |

## Comms Boundary

| Gap ID | Related Issue ID | Area | Risk | Verification | Missing Test |
|---|---|---|---|---|---|
| (none open) | - | - | - | - | - |

## View

| Gap ID | Related Issue ID | Area | Risk | Verification | Missing Test |
|---|---|---|---|---|---|
| (none open) | - | - | - | - | - |

## Priority Backlog (Hardware-Free First)
- [x] Model atomic-write and exclusion-reset resilience (`GAP-M-001`, `GAP-M-002`)
- [x] Protocol boundary hardening (`GAP-X-001`, `GAP-X-002`, `GAP-X-003`)
- [x] View designer lock/reopen regressions (`GAP-V-001`, `GAP-V-002`)
- [x] Legacy safe-height routing coverage (`GAP-C-005`)
- [x] Startup fallback smoke (`GAP-V-003`) and disconnect timing responsiveness (`GAP-X-004`)
- [ ] Controller print-array branch coverage (`GAP-C-003`)

## Deferred (Needs Hardware / HIL)
- [ ] Validate real UART timing jitter assumptions during CLEAR/GOODBYE handling.
- [ ] Validate gripper confirmation timing/UX with real hardware latency.
- [ ] Validate camera trigger/flash timing on target Pi + MCU.
