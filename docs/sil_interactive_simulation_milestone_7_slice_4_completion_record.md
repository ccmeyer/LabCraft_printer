# Milestone 7 Slice 4 Completion Record

Status: `complete - code-growth variance explicitly accepted`

Completed: 2026-08-06

Baseline: `f4ae6312a0ccd91719284ca956015f8e7f078a6a`

## Outcome

`print_array_soft_stop_resume_24_v1` now dispatches through the generic
composed journey runner. The journey creates and finalizes the unchanged
A1-A24 fixture through normal Qt controls, prepares and calibrates the virtual
head, requests the soft stop at completion 6, proves the paused persistence
and 250 ms quiescence boundary, resumes through the exact confirmation dialog,
and completes 24 authoritative stock/well lifecycles.

Raw QTest mechanics for array start, stop, and resume are owned by
`ArrayDriver`. `SoftStopResumeSpec`, the stop-boundary phase, the resume phase,
observer snapshot, and read-only assertion projections are reusable by the
later authoritative-reload migration. Both composed and direct legacy paths
consume the existing paused and terminal policy oracle; the direct legacy
callable remains available for parity and for the unmigrated reload workflow.

No production MVC, simulator-response, fixture, firmware, protocol, Pi, or
hardware file changed. The fixture remained byte-identical with SHA-256
`BB63B9C4D81F7A9DA9D667A78FFC7539313F50A208222D6BCEE79F460402D8C5`.

## Frozen Contracts

- Scenario ID/name/version remain
  `print_array_soft_stop_resume_24_v1` / `print_array_soft_stop_resume` / `1`.
- The exact ten required assertion IDs and lifecycle suite membership remain
  unchanged.
- `array.request_soft_stop_via_ui` and `array.resume_via_ui` report `ui`;
  waits, quiescence observation, milestones, assertions, and reporting do not
  claim UI interaction.
- The exact milestones are `editor_opened`, `generated`, `ready`, `printing`,
  `stop_requested`, `stopped`, `resumed`, and `completed`.
- The named body is 77 physical lines and the scenario payload is below the
  90-line gate. The stop-boundary and resume operations are separate reusable
  functions.

The planned total runtime-growth gate was not met: the touched runtime files
currently measure a net 598 physical lines versus the planned maximum of 450.
The named workflow itself remains concise; most growth is in reusable page
driver, typed phase, observer, and assertion infrastructure intended for the
authoritative-reload migration. This variance is recorded explicitly rather
than treating line wrapping as consolidation. On 2026-08-06 the user
explicitly accepted the variance and chose to proceed without a Slice 4.5
consolidation pass, so Slice 4 is closed.

## Validation

The pre-change legacy CLI oracle passed in 4.2 seconds and retained:

`verification_reports/milestone7-slice4-baseline/print_array_soft_stop_resume_24_v1/20260807T021231952495Z_f4ae6312a0cc/report.json`

Focused results:

- reusable unit, page-driver, phase, observer, assertion, composition,
  manifest, and freeze contracts: `163 passed in 4.03s`;
- production-adjacent array/controller/audit/resume/lifecycle plus report
  contracts: `145 passed in 2.00s`;
- composed success, direct-legacy parity, and controlled paused-boundary
  failure: `3 passed in 14.29s`;
- legacy soft-stop, composed smoke, and composed/legacy two-stock regression:
  `8 passed in 30.99s`;
- post-report-consolidation composed success/failure and two-stock report:
  `3 passed in 12.86s`.
- final post-documentation unit/contract selection: `164 passed in 4.28s`;
- final composed success/parity/failure selection: `3 passed in 14.25s`.

One initial three-node composed run reported a parity failure (`2 passed, 1
failed in 13.63s`). The exact parity node passed alone in 7.96 seconds, the
complete three-node file then passed, and the broader eight-node regression
also passed. This transient is retained as a Windows shared-QApplication test
batching observation; it did not reproduce in the isolated or repeated gates.

The visible run and its exact emitted replay both passed with seed 11,
24/24 completions, all assertions passing, and clean teardown. Reports:

- `verification_reports/milestone7-slice4-visible/print_array_soft_stop_resume_24_v1/20260807T022400619985Z_composed/report.json`
- `verification_reports/milestone7-slice4-visible/print_array_soft_stop_resume_24_v1/20260807T022413670095Z_composed/report.json`

The full Python suite was intentionally not run. Per the user-approved policy,
it remains the final Milestone 7 validation gate.

## Risks And Limitations

- The in-process simulator proves application-facing stop/clear/park/resume
  contracts, not physical stopping distance, firmware framing, ACK timing,
  motion, pressure response, camera/balance behavior, or droplet quality.
- Exact-trigger timing remains fail closed: overshoot, duplicate clicks,
  unexpected controls/dialogs, ambiguous writes, and stale state fail with
  retained evidence.
- Generated IDs, paths, timestamps, durations, and identity-bearing hashes are
  intentionally excluded from replay equality.

## Rollback

Restore only the soft-stop registry/manifest entry to the legacy
`virtual_print_array` family, remove the composed definition and its Slice 4
tests/documentation, and remove the distinct resume action/driver and typed
phase additions if they have no remaining consumer. Do not revert the fixture,
generic harness/executor, existing composed journeys, production data, or
unrelated Milestone 7 consolidation. No firmware or hardware rollback is
required.

## Next Step

The separate concrete plan for migrating
`authoritative_reload_resume_24_v1` is
`docs/sil_interactive_simulation_milestone_7_slice_5_implementation_plan.md`.
Do not implement it until approved.
