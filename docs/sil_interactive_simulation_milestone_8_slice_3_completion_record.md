# Milestone 8 Slice 3 — Completion Record

Status: complete (2026-08-07)

## Delivered behavior

Windows `--suite` and `--capability` selections now execute the validated
Slice 2 plan sequentially in fresh Python child processes. The parent remains
Qt/application-import-free. Direct scenario execution and all read-only
planning modes remain compatible.

The new `labcraft.virtual_workflow_aggregate` v1 evidence records the hashed
selection plan, manifest identity, parent and child PIDs, exact commands,
watchdogs, return codes, stdout/stderr paths and hashes, validated report-v1
references and hashes, source identity, child outcomes, aggregate
classification, and exact replay. All children continue after a failure;
timeouts terminate and then kill after the bounded grace period.

Aggregate execution rejects Pi, repetition, fault-injection, report-set,
baseline, comparison, and threshold controls. No scheduler, production MVC,
simulator, report-v1, protocol, firmware, Pi, or hardware behavior changed.

## Qualification findings and bounded corrections

The first eight-child lifecycle aggregate failed closed and retained all child
evidence. It exposed two existing SIL-harness defects:

- the unexpected-dialog guard raced expected editor progress/file dialogs;
  the reusable drivers now register those dialogs only while actively driving
  them, wait for transient progress deletion to settle, poll boundedly for the
  editor/file dialog, and select the folder row with QTest mouse input;
- the soft-stop report payload return had been displaced below the disconnect
  payload return, causing a completed journey to exit without report evidence;
  the payload builder now returns the authoritative soft-stop evidence.

These corrections are confined to composable workflow actions, page drivers,
and reporting composition. The affected editor and soft-stop journeys passed
individually before the lifecycle suite was repeated.

## Retained passing aggregates

- Standard offscreen:
  `verification_reports/suites/standard/20260807T223703204236Z_615b59a4-510/aggregate.json`
  — SHA-256 `2dff401cb2c152d7c41cffb36f78d24af82758098139511aa5b4f73fcbc07251`.
- Mixed-mode capability offscreen:
  `verification_reports/suites/capability__execution.mixed_droplet_stream_lifecycle/20260807T223222720793Z_d4dbe28d-6f8/aggregate.json`
  — SHA-256 `a4b8b4fff1d3a7d338df48c8149c810bdfc15ef795421ee8bb50616646269e9e`.
- Lifecycle offscreen, eight fresh children:
  `verification_reports/suites/lifecycle/20260807T223114638585Z_a8d5bc10-2e7/aggregate.json`
  — SHA-256 `3b144fa56c79261b181281871bd44091583b3c6f4e64d301499b488f7e94af30`.
- Standard visible Windows:
  `verification_reports/suites/standard/20260807T223238510813Z_74ea737f-b8f/aggregate.json`
  — SHA-256 `aa33cf3fcc1b556e94bc1cfa1af42ff1b926bd67cdb4e17681d6c1e6cec004d0`.
- Exact visible replay:
  `verification_reports/suites/standard/20260807T223255401699Z_a98314a8-c4e/aggregate.json`
  — SHA-256 `4f152c2a2d1125e4fe565b3f45ad6ed3fd40f747870fa0f4c583058ec3a4ce4f`.

Every final aggregate classified `pass`; the lifecycle aggregate recorded
eight of eight passing children and the other aggregates recorded one of one.

## Focused validation

The final focused unit/contract gate passed 221 tests. The final targeted
system gate passed seven tests covering the real-process standard suite,
direct smoke compatibility, all three editor lifecycles, and soft-stop/resume.
An additional 24 aggregate-runner tests passed after the failure-reason ledger
was finalized, and all five retained qualification aggregates revalidated with
their referenced hashes. The complete Python suite was intentionally not run
and remains the Milestone 8 Slice 8 final validation gate.

## Risks and rollback

The aggregate runner writes only new contained evidence roots and never
overwrites an existing aggregate. Scenario reports remain authoritative. The
principal residual risk is platform-specific Qt timing; bounded waits,
identity-matched reports, process/report agreement, and exact visible replay
provide fail-closed coverage.

Rollback removes `suite_runner.py`, the CLI aggregate branch, its tests and
documentation, and restores suite/capability selectors to dry-run-only. The
bounded editor synchronization and soft-stop payload correction can be
reverted independently. No persisted-data migration or hardware rollback is
required.
