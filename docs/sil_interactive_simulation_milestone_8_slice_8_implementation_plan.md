# Milestone 8 Slice 8 — Operational Runbook, Evidence Refresh, and Final Closeout

Status: in progress - Windows gates complete; final Pi requalification awaits
fresh operator authorization

## Purpose and baseline

Close Milestone 8 without adding runner behavior. This slice documents the
manual operating model, refreshes every Windows SIL lane against one final
execution-input tree, inspects representative visible and Pi evidence, and
runs the complete default Python suite once as the final gate.

The starting tracked commit is
`669d81df02f3fd4e5b3ed871948df223da99436b`. The Windows execution-input tree
initially contained 888 files and had SHA-256
`b1e57e7af6c3f868dcb882f3b7d825c3e99de180a0c6c400e4496d3a4aed5e45`.
Documentation and generated evidence are excluded from that fingerprint, so
the planned documentation edits do not stale the refreshed workflow reports.

Passing Windows aggregates retained from Slices 3, 5, and 6 predate the final
Slice 7 reporting/orchestration corrections and are source-stale for final
coverage. They remain useful historical and visible-interaction evidence. The
authorized Slice 7 Pi primary aggregate and exact replay were current for their
Linux execution-input tree at the start of this slice.

## Qualification findings and amendments

Final validation exposed two intermittent Qt-driver defects rather than an MVC
or simulator defect:

- the editable-copy name dialog was not registered with the global
  unexpected-dialog auditor, creating a race between the local modal driver and
  the auditor;
- the generic message-box action used one unverified click and recursive
  single-shot polling that could outlive a failed action.

The bounded corrections are recorded in
`sil_interactive_simulation_milestone_8_slice_8_copy_dialog_correction.md` and
`sil_interactive_simulation_milestone_8_slice_8_action_dialog_correction.md`.
They add one mouse-only retry after a proven no-activation result, require the
authoritative postcondition, fail immediately on ambiguous activation, and use
owned/cancelled modal timers. No production View, Controller, Model, simulator,
protocol, firmware, Pi configuration, or hardware file changed.

These corrections changed the final Windows execution-input fingerprint to
`bd2fb283c348f1bd8585079f2287f180223bfea4b058448899e6c138a2ace5d9`.
All Windows evidence below was regenerated after the last correction.

The approved in-repository pytest basetemp was also incompatible with
`SimulationSession`'s intentional repository-overlap guard. Validation uses
unique explicit roots beneath
`C:\Users\conar\AppData\Local\Temp\LabCraft` instead. The safety guard was not
relaxed.

## Call path and unchanged contracts

The exercised path remains:

`operator CLI` → `isolated Python child` → `QTest` → `View` → `Controller` →
`Model` → `SimulatedMachine` → `report-v1` → `aggregate/evaluation`.

No CLI, schema, fixture, manifest, semantic action, assertion, MVC, simulator,
protocol, firmware, Pi configuration, or hardware interface changes. Generated
artifacts remain ignored beneath `verification_reports/` and are never cleaned
automatically.

## Implementation and qualification

1. Create the operator runbook covering manual lane selection, commands,
   replay, evidence interpretation, failure triage, Pi safety, and retention.
2. Refresh current-source Windows standard, lifecycle, matrix, exploration,
   host-regression, and host-stress evidence in shortest-to-longest order.
3. Run one visible Windows standard suite at 20x and its exact emitted replay.
4. Generate and replay source-current Windows capability coverage from the four
   suite aggregates; validate Pi evidence separately through its aggregate and
   bundle.
5. Inspect representative current and retained screenshots, ledgers,
   assertions, queue/teardown state, hashes, process identities, and source
   freshness.
6. Run the focused unit/contract and real-process system gates from the
   approved plan.
7. Run `pytest -q` once with a unique explicit basetemp outside the repository
   and a 15-minute process timeout. The normal opt-in analysis/SIL skips remain intentional
   because those SIL tiers are exercised explicitly in the earlier gates.
8. Create the completion record and mark Milestone 8 complete only after every
   required gate passes.

## Acceptance

- standard 1/1, lifecycle 8/8, matrix 8/8, exploration 10/10,
  host-regression 1/1, and host-stress 1/1 aggregates pass;
- regression records 96/96 and stress records 3,840/3,840 completions with all
  ten head lifecycles;
- negative matrix cases prove their expected safe block and all exploration
  sequences remain within 25 actions;
- all current children match the final Windows source fingerprint, run in
  fresh processes, agree with their process return code, retain required
  artifacts, and show no unexpected dialogs, starvation, or dirty teardown;
- visible standard and exact replay pass through normal Qt controls;
- all in-scope active Windows capabilities pass source-current coverage, while
  deferred protocol/HIL/physical capabilities remain out of scope;
- retained Slice 7 Pi aggregates/bundle continue to validate with zero
  prohibited-device accesses;
- focused validation and the complete default pytest suite have zero failures.

## Current evidence and remaining gate

The final-source Windows evidence is:

| Gate | Result | Evidence SHA-256 |
|---|---|---|
| standard | 1/1 pass | `6957582c844ad7678fda32a1402aa28b4c02caf70824f2e138a054df4984c7e8` |
| lifecycle | 8/8 pass | `524e09a4304a50bb1e37acd741403881a72c7c8d816061ba18c8002437a47ac2` |
| matrix | 8/8 pass | `4ad41a4c02ec709c13c4b32a745c7a31923968c4635c7650151daad6dc3cde8e` |
| exploration | 10/10 pass | `cf272de4ec5bd1e57a7c3e1db78ef27e100052f2ece0028c8d3e31db73ad9731` |
| host regression | 96/96, pass | `ba0945acf393bff69528c054e9524fc81bcd01d2b1371cd78e2c1248c0c20921` |
| host stress | 3,840/3,840 and ten passes; informational warning | `c3a06fdc74bc76de57b6d9feda6bacf6fc4a7b93f2354fb8e72e419057afd748` |
| visible standard | 1/1 pass | `57b671b51142f71f73fa1c158f874839e9282f24bbc474d9fbf7e823f743e3f4` |
| visible exact replay | 1/1 pass | `e1be36825b6bca7865b6759e489d691c9abcfe0b88088038c94a5ca324db5914` |

The corresponding aggregate roots are:

```text
verification_reports/suites/standard/20260808T020751830138Z_2294a513-ef4/
verification_reports/suites/lifecycle/20260808T020801568267Z_80d1b8a0-4ac/
verification_reports/matrices/mixed_mode_calibration_v1/20260808T020853898332Z_e8e0fcc7-d8a/
verification_reports/exploration/editor_prepared_guard_v1/20260808T021000616940Z_07ecfa29-f23/
verification_reports/suites/host_regression/20260808T021046458346Z_a0ce4c94-0b9/
verification_reports/suites/host_stress/20260808T021103311974Z_01cb0966-74b/
verification_reports/suites/standard/20260808T021828253242Z_5908b3e2-f50/
verification_reports/suites/standard/20260808T021842873690Z_c8ef2397-679/
```

Stress had zero failed actions/assertions, zero starvation/unexpected dialogs,
a drained queue, and clean teardown. Its warning reasons are the unchanged
informational event-loop, pressure-render, and RSS thresholds.

Coverage and its exact replay each report 21 passing Windows capabilities,
zero failed/stale/missing capabilities, and three incomplete Pi-only
capabilities. The final evaluation hashes are
`a9d28cb54f2adf95322c9934f87766ccae1f73464d5bc7124f562718322f5723`
and `35b8233500fe03ca4e73493d51cae7f4627be21400077aa0b83822dc17b24532`.
The overall evaluator status remains fail by design for a Windows-only evidence
set because Pi verification layers are not present.

Focused validation passed 189 unit/contract tests and 18 real-process system
tests. The complete default suite passed 4,080 tests with 72 intentional skips
and 389 existing warnings in 218.64 seconds.

The retained Slice 7 Pi v2 bundle still validates all 52 members and both
aggregates; its archive SHA-256 remains
`ecb9fccc83017583eb2660f93db6fb89ffa2794aac864080505e4190d3927e09`.
However, the page-driver corrections are Pi execution inputs, so that retained
evidence is now source-stale relative to the final tree. Per the approved
authorization boundary, Slice 8 and Milestone 8 remain in progress until the
operator separately authorizes a fresh `pi_primary` run plus exact replay. Do
not run `pi_stress`.

## Failure policy, exclusions, and rollback

Stop before a later expensive lane if an earlier gate fails. Do not weaken an
assertion or silently select a convenient newer artifact. A source change made
to correct a failure invalidates refreshed downstream evidence and requires the
affected lanes to be rerun. A Pi execution-input change also requires fresh
operator authorization before another remote run.

`pi_stress`, analysis-pipeline tests, firmware, protocol, Pi configuration,
cleanup, scheduling, production hardware, physical motion/pressure, and
physical droplet behavior are excluded.

Rollback reverts the two bounded page-driver corrections, their focused tests,
and the Slice 8 documentation. Generated evidence is retained and becomes
historical; it is not deleted. No persisted application data, Pi configuration,
firmware, or hardware state requires rollback.
