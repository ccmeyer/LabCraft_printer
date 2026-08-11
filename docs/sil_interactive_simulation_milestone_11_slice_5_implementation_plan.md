# Milestone 11 Slice 11.5 Implementation Plan

Status: complete (2026-08-08)

## Objective and non-goals

Qualify the committed Slice 11.4 source identity with retained offscreen and
visible direct runs plus their exact emitted replays, lifecycle and host-
regression suites plus aggregate replays, focused contracts, and one complete
default Python suite. Audit all retained evidence and screenshots, update the
operator runbook, record Milestone 11 complete, and commit documentation only.

Do not change execution source after qualification begins. Any discovered
source defect stops this slice, requires a separate reviewed correction
commit, and restarts every Slice 11.5 qualification run from the corrected
identity. Do not run the analysis pipeline, Pi or host stress, firmware,
protocol, HIL, physical hardware, release operations, Milestone 12 safeguards,
or refill/resume behavior.

## Exact qualification path

```text
committed Slice 11.4 source a385b1b
-> catalog listing and dry-run identity capture
-> direct offscreen scenario -> exact emitted replay
-> visible Windows scenario at 20x -> exact emitted replay
-> lifecycle suite in fresh children -> exact aggregate replay
-> host_regression suite in fresh children -> exact aggregate replay
-> focused contracts/system selection -> complete default pytest once
-> report/evidence/hash/screenshot/manual audit
-> documentation-only closeout commit
```

## Files expected to change

Add:

- `docs/sil_interactive_simulation_milestone_11_slice_5_implementation_plan.md`
- `docs/sil_interactive_simulation_milestone_11_slice_5_completion_record.md`

Update only after all qualification passes:

- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- `docs/sil_interactive_simulation_milestone_11_execution_plan.md`
- `docs/sil_virtual_workflow_operator_runbook.md`

`README.md` changes only if inspection finds an operator entry point or
prerequisite changed; none is currently expected. No production, SIL source,
test, manifest, fixture, firmware, protocol, or persisted-schema file may
change in this slice.

## Qualification steps

1. Confirm clean committed Slice 11.4 source, capture commit/tree/source,
   manifest, joined case/fixture/count, lifecycle-selection, and host-selection
   hashes, and retain catalog listing plus scenario/suite dry runs beneath
   `verification_reports/m11-s5/`.
2. Run the joined scenario offscreen with seed 1, speed 1000, and timeout 180;
   execute its emitted replay exactly and require report/process/evidence parity.
3. Run the same scenario visibly on Windows with seed 1, speed 20, and timeout
   240; execute its emitted replay exactly and manually inspect all eleven
   retained screenshots for expected UI state and the simulation banner.
4. Run the complete `lifecycle` and `host_regression` suites offscreen in fresh
   child processes at seed 1/speed 1000, then execute each aggregate's emitted
   replay exactly.
5. Run focused Milestone 11 unit/contract/composition/manifest/selection/system
   tests and frozen Milestone 9/10 compatibility/hash checks.
6. Run the complete default Python suite exactly once with a fresh external
   `%LOCALAPPDATA%\Temp\LabCraft` base temp and at least a 15-minute timeout;
   do not enable the optional analysis pipeline.
7. Audit retained reports, aggregates, ledgers, evidence manifests, snapshots,
   hashes, session attribution, 24 intents/80 droplets, no positional joins,
   zero first/third-session dispatch, clean teardown, and exact replay lists.
8. Update the runbook and planning/completion documents, run the complete doc
   diff and `git diff --check`, then commit only documentation as
   `test: close randomized calibration lifecycle SIL milestone`.

## Entrance prerequisites and exit criteria

Entrance requires independent commits for Slices 11.1-11.4, a clean worktree
at `a385b1b`, active registered case
`randomized_calibration_reload_execution_v1`, and unchanged frozen joined
hashes. Exit requires every direct/suite run and every exact emitted replay to
pass from one execution-source fingerprint, no timeout/termination or
process/report disagreement, at most 96 joined actions, all required evidence
and screenshots present and manually inspected, focused and complete pytest
passing, documentation current, `git diff --check` passing, a documentation-
only commit, and a clean worktree.

## Evidence and compatibility requirements

Retain the two direct reports and replays, two suite aggregates and replays,
all child logs/reports, catalog and dry-run plans, source and selection
identities, action/assertion ledgers, evidence manifests, authoritative
snapshots/hashes, and all eleven named screenshots under the dedicated root.
Record SHA-256 values for the accepted direct reports, aggregates, evidence
manifests, and screenshots, plus exact emitted replay commands.

Require literal joined case SHA-256
`3081ebadd38a9e9de465f67e855ce63a471d7f9092e65e9f7881da1923d509cd`,
fixture SHA-256
`bf9631efdf2e0ad04e2310b378330a87941d05c157d69a6c47b69b645dbbe118`,
and count-oracle SHA-256
`468d78216fd52f326898c5b5625f6ae591995c642118a72ddb1cdf0cb5790814`.
Preserve Milestone 9/10 hashes, schemas, catalogs, selectors, historical
artifacts, reload/no-mutation behavior, report/replay grammar, and persisted
application formats. The expanded lifecycle selection's new source-current
hash is evidence, not a rewrite of historical hashes.

## Risks, rollback, and deferred validation

The primary risk is accepting stale, ambiguous, incomplete, or mixed-source
evidence. Every run must agree on one source fingerprint and select exactly one
matching report. A failure is retained and investigated; no timeout is widened
without evidence of bounded forward progress. No source correction may be
folded into this closeout.

Rollback reverts only the Slice 11.5 documentation commit; it does not delete
retained evidence or revert the independently valid Slices 11.1-11.4. Host
stress, Pi, firmware/protocol/HIL/physical qualification, analysis-pipeline
tests, refill/resume, Milestone 12 safeguards, and Milestone 13 exploration are
deliberately deferred beyond Milestone 11.
