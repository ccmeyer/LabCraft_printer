# Milestone 7 Slice 9 Completion Record

Status: `complete - final Milestone 7 validation passed`

Completed against baseline
`fb6730823801b81674ee26e9736dbead09a6a980` on 2026-08-07 local time.

## Outcome

`print_array_disconnect_mid_array_24_v1` is an active composed lifecycle
journey. It reuses the normal editor, startup, synthetic-calibration, stock-pass,
evidence, report, and teardown composition. Its bounded disconnect phase clicks
the normal Qt connection button after exactly six durable completions, observes
250 ms of quiescence, and stops at the recovery boundary without resuming or
printing the remaining 18 wells.

The Controller now interrupts an active array on machine disconnect. It retires
the two queued look-ahead intents only when the canonical simulation runtime is
disconnected and confirms its queue is drained. Physical or otherwise
unconfirmed cancellation retains the intents as ambiguous and remains blocked.
The qualifying state is ACTIVE plan, `resume_ready`, authoritative
`ready_to_resume`, disconnected/unhomed machine, six exact stock/well
completions, no pending intents, and a `machine_disconnect` dock check.

The fixture SHA-256 is
`4BE9CAA0D0F99057E06F631C63F421B808AEBF28390653E0EC846B3258917646`.

## Visible Teardown Correction

The first visible run reached and captured `recovery_ready` in about six
seconds but blocked before writing its report. A bounded stack diagnostic
showed this cleanup-only call path:

```text
ApplicationComponents.close() -> hide/processEvents
  -> focused pressure editor commit
  -> Controller.set_absolute_print_pressure()
  -> disconnected simulator rejects command
  -> MainWindow.popup_message() modal dialog
```

Application component cleanup now blocks the view and child QObject signals
before hide/delete. A focused regression queues a child UI commit and proves
cleanup cannot deliver it as a machine command. The corrected visible run and
exact replay each completed in approximately 6.3 seconds. No runtime command,
simulator timing, protocol, firmware, or hardware behavior changed.

## Validation

- affected unit files: `190 passed` in 9.70 seconds;
- disconnect composed/session/simulator focus: `4 passed`, `31 deselected`, in
  7.04 seconds;
- unchanged composed 24-well smoke: `1 passed` in approximately 4.7 seconds;
- offscreen CLI report: `pass`, SHA-256
  `5352DC3B6938C6502CAB2C64D8B49297B0DE0F0E20A2C0A4C33F093755A9D0AA`;
- visible Windows report: `pass`, SHA-256
  `664DA960BD23543ACC09C67BDD2FDD728A16670701786E14768E722B2C74D0A1`;
- exact emitted visible replay report: `pass`, SHA-256
  `B00CEFB75DEA39B93FF8094B3E7291E0F366FB9A81B8AC9067ED88A32366CD20`;
- first full Python suite: `3961 passed`, `66 skipped`, `2 failed` in 669.85
  seconds; both failures were stale top-level dialogs leaked by earlier Qt test
  modules into the session-scoped QApplication;
- the two failed harness nodes passed independently, confirming order-dependent
  test leakage rather than a harness or Slice 9 behavior failure;
- dialog-producing modules followed by the harness module: `50 passed` in 4.09
  seconds after the isolation correction;
- final full Python suite: `3963 passed`, `66 skipped`, `389 warnings` in
  192.25 seconds.

The visible and replay reports retain six screenshots, eight begun intents,
six completions, one two-intent discard batch for A7/A8, empty simulator and
durable queues, no completion change during quiescence, all required
assertions, no unexpected dialogs, clean teardown, and the exact replay
command. Retained evidence is local and ignored by Git.

The shared `qapp` test fixture now signal-blocks, hides, and deferred-deletes
top-level widgets after every test that requests it. This prevents dialogs
created in one Qt unit module from becoming unexpected input to a later module;
it does not relax the harness's fail-closed unexpected-dialog checks.

## Risks And Rollback

The safety-sensitive distinction is confirmation of canceled work. Only the
canonical simulator's disconnected and drained state authorizes intent discard;
an uncertain physical disconnect does not. Exact-trigger overshoot and any
completion/progress change during quiescence fail closed.

Rollback removes the scenario definition, fixture, typed disconnect phase,
actions, assertions, manifest rows, tests, and bounded Controller interrupt.
The independent teardown correction may remain because it prevents cleanup
from issuing machine commands; if reverted, restore both its signal blocking
and regression together. No experiment schema, report schema, simulator
protocol, firmware, Pi operation, or hardware state requires rollback.

## Next Boundary

Milestone 7 migration is complete. Milestone 8 must begin from a separately
approved plan covering suite selection, seeded sequence exploration,
scheduling, artifact retention, and operational handoff. This slice does not
authorize new fault injection, performance remediation, firmware/protocol
work, Pi operations, or hardware work.
