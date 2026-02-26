# Audit Test Gaps

## Scope
- Date: 2026-02-26
- Commit/Branch: Working tree audit of `FreeRTOS-interface/` only
- Intent: Open test gaps only (resolved/covered gaps removed for triage clarity).

## Gap Triage (Open Only)
- Total open gaps: 9
- Dedupe notes:
  - Collapsed covered items from Milestones 1-4 plus protocol hardening from Milestone 2.
  - Kept View close-event/popup gaps closed; remaining View focus is designer lock/reopen flows.

## Model

| Gap ID | Related Issue ID | Area | Risk | Verification | Missing Test |
|---|---|---|---|---|---|
| (none open) | - | - | - | - | - |

## Controller

| Gap ID | Related Issue ID | Area | Risk | Verification | Missing Test |
|---|---|---|---|---|---|
| GAP-C-001 | AUD-2026-012 | `Controller._classify_port` | Medium | Feed synthetic `ListPortInfo` variants (case/descriptor/VID-only) | Parameterized classification edge-case test |
| GAP-C-002 | AUD-2026-013 | `Controller.disconnect_droplet_camera_signals` | Medium | Verify only controller callbacks are removed in multi-subscriber setup | Signal disconnection scoping test |
| GAP-C-003 | n/a (coverage debt) | `Controller.print_array` | Medium | Simulate queue-nonempty/profile/refill/last-well branches and assert orchestration | Integration-lite print-array branch matrix |
| GAP-C-004 | AUD-2026-016 | `Controller` class structure | Low | Static parse of critical classes for duplicate method names | AST duplicate-method guard test |
| GAP-C-005 | AUD-2026-020 | `Controller.move_to_location` legacy path | Low | Assert `safe_z=5000` behavior/order in legacy profile | Legacy safe-height routing test |

## Comms Boundary

| Gap ID | Related Issue ID | Area | Risk | Verification | Missing Test |
|---|---|---|---|---|---|
| GAP-X-004 | AUD-2026-014 | `Machine._on_goodbye_done` | Medium | Measure close/disconnect responsiveness under event loop | Disconnect timing responsiveness test |

## View

| Gap ID | Related Issue ID | Area | Risk | Verification | Missing Test |
|---|---|---|---|---|---|
| GAP-V-001 | n/a (coverage debt) | `ExperimentDesignDialog` lock precedence | Medium | Transition uploaded/manual/gripper modes and assert control-state matrix | Lock-precedence matrix test |
| GAP-V-002 | n/a (coverage debt) | `open_experiment_designer` reopen flow | Medium | Open/close repeatedly during active runtime state and assert no implicit apply/reset | Reopen integration-lite regression test |

## Priority Backlog (Hardware-Free First)
- [x] Model atomic-write and exclusion-reset resilience (`GAP-M-001`, `GAP-M-002`)
- [x] Protocol boundary hardening (`GAP-X-001`, `GAP-X-002`, `GAP-X-003`)
- [ ] View designer lock/reopen regressions (`GAP-V-001`, `GAP-V-002`)
- [ ] Controller branch/scoping/static guard coverage (`GAP-C-001`..`GAP-C-004`)

## Deferred (Needs Hardware / HIL)
- [ ] Validate real UART timing jitter assumptions during CLEAR/GOODBYE handling.
- [ ] Validate gripper confirmation timing/UX with real hardware latency.
- [ ] Validate camera trigger/flash timing on target Pi + MCU.
