# Milestone 6 — Shared Automation Harness Completion Record

Status: `complete`

Completed: 2026-08-06 on Windows.

## Outcome

Milestone 6 adds one shared `SimulationSession` automation harness, reusable
QTest page drivers, explicit interaction surfaces, read-only assertions, and
generic evidence/teardown ownership. Only `virtual_print_array_24_v1` moved to
the new composition; every other workflow retains its existing runner.

The migrated smoke creates/finalizes its 24-well experiment, connects and
homes, configures print settings, stages its one stock head, generates/selects/
applies a 9 nL synthetic droplet calibration, enables pressure regulation, and
starts through normal Qt controls. It completes A1 through A24 in order with a
clean execution checkpoint and queue.

All 17 state-changing operator actions are recorded as `ui`; launch, waits,
screenshots, and teardown are `harness`. Seven required assertions have
explicit `pass`, `fail`, or `incomplete` decisions. Unexpected action-local
dialogs and unhealthy recorder evidence fail inside the current action.

A controlled active-session unexpected-dialog test retained a screenshot,
traceback, snapshots, action/assertion ledgers, seed, fixture hash, replay
command, and evidence manifest. Remaining assertions were `incomplete`, and
teardown removed the session lock without masking the primary failure. This is
a test-only harness boundary, not a production fault-injection feature.

No production MVC, firmware, protocol, Pi, performance, hardware, physical
calibration, or production fault-injection behavior changed.

## Final Visible And Replay Evidence

Visible report and retained session:

```text
C:\Users\conar\source\LabCraft_printer\verification_reports\milestone6-final\virtual_print_array_24_v1\20260806T225615203014Z_composed
C:\Users\conar\AppData\Local\Temp\LabCraft\SIL\composed-sessions\20260806T225615204704Z-1ac5a1da-d5a
```

- report SHA-256: `b02d6bd02b7a38717d8e985503f134715342331a59577dc5fd12a26cf0dcf2ce`
- evidence-manifest SHA-256: `a3cba061d936e48522d49b00ce9593f5b824a2fd66fa33740242d6021d2979cf`

Replay report and retained session:

```text
C:\Users\conar\source\LabCraft_printer\verification_reports\milestone6-final\virtual_print_array_24_v1\20260806T225625691489Z_composed
C:\Users\conar\AppData\Local\Temp\LabCraft\SIL\composed-sessions\20260806T225625692616Z-f969a5a1-dbd
```

- report SHA-256: `0e26483a38e6a78f4b0a3d3f555862e1e513aac96207cbb69f29cad6cb19d6dd`
- evidence-manifest SHA-256: `5e39cacc9c26d256e1f7aab97fccbf3dde51f6351600e53d3d41bbbb139d01d1`

Both passed with fixture SHA-256
`a05c18252bfb5d22908d9a3e6a55cfc126ecdddb70193362b53ac798005d9aac`,
seed 1, identical action IDs/surfaces/statuses, identical assertion decisions,
24 exact completions, and 9 nL / 1300 µs / 1.2005 psi settings. Both recorders
closed healthy, terminal status was completed, cleanup was complete, terminal
snapshots were present, and no lock remained.

Report/inventory hashes differ because evidence contains timestamps, UUIDs,
durations, paths, and generated identities. Those are outside replay equality.

## Validation

- shared-harness focused gate: `149 passed`;
- adjacent lifecycle compatibility gate: `8 passed, 11 skipped`;
- controlled failure and final focused smoke gate: `40 passed`;
- final complete Python suite: `3851 passed, 38 skipped, 349 warnings in
  536.31s (0:08:56)`.

## Risks, Limitations, And Rollback

This proves application-facing behavior against `SimulatedMachine`, not
firmware framing/ACK behavior, physical motion/collision safety, pressure or
fluid response, camera/balance behavior, volume accuracy, droplet quality, Pi
operation, or hardware readiness.

Rollback restores the smoke registry dispatch and prior fixture to the legacy
runner, removes the shared modules/tests, and removes only additive seed,
surface, evidence, and report fields. No MVC, firmware, protocol, Pi, hardware,
or authoritative-schema rollback is needed. Retained evidence may remain.
