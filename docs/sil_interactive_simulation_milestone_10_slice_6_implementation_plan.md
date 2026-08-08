# Milestone 10 Slice 10.6 Implementation Plan

Status: complete (2026-08-08)

Completion record:

- `docs/sil_interactive_simulation_milestone_10_slice_6_completion_record.md`

Entrance commit: `a3734333c47f36ee405d33716ea38e4085c381a6`

## Objective and non-goals

Qualify and exactly replay the frozen nine-case
`experiment_design_pairwise_v1` matrix from clean committed Slice 10.5
source. Also qualify and replay the lifecycle and host-regression suites, run
the complete default Python suite exactly once, inspect representative
visible evidence, update operator documentation, and record Milestone 10
complete.

This slice is qualification and documentation only. It adds no cases and
changes no harness, production MVC, fixture, manifest, schema, firmware,
protocol, hardware, motion, pressure, printing, timing, or physical
calibration. Any source defect stops qualification and requires a separate
reviewed correction plan and a complete Slice 10.6 restart.

## Exact call path and source boundary

```text
clean committed Slice 10.5 source
-> matrix catalog listing and deterministic dry-run plan
-> nine fresh Qt child processes -> per-case authoritative report-v1
-> matrix aggregate and exact emitted replay
-> five visible selectors and exact emitted replays
-> lifecycle suite fresh children -> aggregate -> exact replay
-> host-regression suite fresh children -> aggregate -> exact replay
-> complete default pytest suite exactly once
-> evidence/hash/manual inspection -> documentation-only closeout
```

All Qt journeys construct the real MainWindow, Controller, and Model with the
literal `SimulatedMachine`. Positive experiment-design cases stop after
authoritative prepared reload. Negative cases stop at the rejected Finalize
boundary. Suite execution remains within its registered SIL scenarios. No
firmware or physical-device handler is authorized.

## Files expected to change

- this implementation plan;
- `docs/sil_interactive_simulation_milestone_10_slice_6_completion_record.md`;
- `README.md`, limited to final experiment-design matrix operator commands,
  evidence, and limitations;
- `docs/sil_virtual_workflow_operator_runbook.md`, limited to selection,
  visible evidence, and accepted Milestone 10 baseline guidance;
- `docs/sil_interactive_simulation_milestone_10_execution_plan.md`, status
  only;
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`, only
  Milestone 10 results/current-next-action text.

No code, test, fixture, manifest, or production file is expected to change.

## Qualification sequence

1. Freeze the clean source identity, source-tree fingerprint, matrix listing,
   ordered case/catalog hashes, reference fixture hash, and deterministic
   dry-run plan/hash.
2. Run the complete nine-case matrix offscreen, audit all fresh child
   identities/reports, then execute the aggregate's exact emitted replay.
3. With the Windows Qt platform, 20x speed, and 120-second watchdog, visibly
   run and exactly replay `multi_reagent_seed_4321`, `two_stock_required`,
   `custom_wells_with_exclusions`, `capacity_plus_one_rejected`, and
   `fixed_stock_exceeds_max_rejected`.
4. Run the complete lifecycle suite offscreen and execute its exact emitted
   replay; repeat for host regression.
5. After every selected gate passes, run
   `.\env\Scripts\python.exe -m pytest -q` exactly once with a fresh external
   basetemp and without the unrelated analysis pipeline.
6. Inspect aggregate child status/PID/timeout/report hashes, report
   classifications, hardware isolation, cleanup, exact assignments,
   warnings, negative no-mutation fields, and every named visible screenshot.
7. Hash retained plans, aggregates, reports, manifests, and representative
   screenshots; update only the listed documentation; run `git diff --check`;
   commit `test: close experiment design SIL milestone`.

## Entrance, exit, safety, and rollback

Entrance requires clean committed Slices 10.1-10.5, all nine frozen case
hashes, and unchanged Milestone 7-9 compatibility contracts. Exit requires a
9/9 matrix and replay, all five visible run/replay pairs, lifecycle and
host-regression aggregates/replays, one passing full default Python suite,
manual evidence acceptance, documentation-current hashes, a documentation-
only diff, and a clean closeout commit.

Retain every generated success or failure under `verification_reports/`; do
not clean historical artifacts. Never accept a child without exactly one
matching passing report, any timeout/process-report disagreement, missing
hardware-isolation evidence, failed cleanup, unexpected dialog, or stale
source identity. Rollback reverts only the closeout documentation commit;
Slices 10.1-10.5 and retained evidence remain intact.

Deferred beyond Milestone 10: analysis-pipeline tests, host stress, Pi
qualification, firmware checks, hardware/release operations, Milestones
11-13, and refill-required/resume behavior.
