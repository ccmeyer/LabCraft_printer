# Milestone 12 Slice 12.5 Implementation Plan

Status: implementation in progress (2026-08-09)

## Objective and exclusions

Freeze and qualify all three Milestone 12 safeguard catalogs, join their matrix
aggregates to the capability manifest, run exact replay/visible/regression and
immutable optimizer-360 compatibility gates, document the results, and create
one final Milestone 12 commit. Do not add or weaken a safeguard, change
production MVC/firmware/protocol/physical behavior/refill, rewrite Milestone
11/11A, run the known-broken host-stress aggregate as a gate, push, or start
Milestone 13.

## Call paths and evidence boundary

```text
catalog -> matrix registry -> CLI list/dry-run -> fresh-child aggregate
-> manifest matrix-family join -> exact replay -> report/fingerprint audit

real Qt negative action -> exact rejection/locked state -> shared oracle
-> visible screenshot -> emitted exact replay

immutable optimizer-360 registry entry -> sessions 1-3 -> revisions 1-8
-> 1,800 intents / 46,208 drops -> terminal persistence + frozen hashes
```

The source checkpoint is frozen only after the minimal matrix-manifest join and
its tests pass. Any subsequent source correction invalidates final reports and
restarts the Slice 12.5 qualification sequence.

## Files to change

- capability-manifest parser/schema tests and
  `tools/virtual_workflows/manifests/capability_coverage_v1.json` for the
  matrix-family evidence join;
- add this plan, its completion record, and the milestone completion record;
- update `README.md`, `docs/sil_virtual_workflow_operator_runbook.md`, the
  Milestone 12 execution plan, and only Milestone 12/current-next-action status
  in the authoritative plan.

No production MVC, firmware, protocol, positive-control fixture/oracle, or
Milestone 13 file is in scope.

## Steps

1. Add the minimal typed manifest registration for the three matrix families
   and their shared safeguard assertion.
2. Run focused manifest/selection/report tests and freeze all source/catalog/
   fixture/manifest/dry-run hashes.
3. Run all three complete fresh-child matrices and exact aggregate replays.
4. Run and inspect the required visible representatives and their replays.
5. Run optimizer-360 direct/replay and lifecycle/host-regression compatibility.
6. Run all focused Milestone 12 tests and the full default Python suite once
   with a timeout of at least 900000 ms.
7. Audit report, lifecycle, fingerprint, cleanup, and known-exclusion evidence;
   then update operator and completion documentation.
8. Run final diff/status checks and create the one Milestone 12 commit without
   pushing.

## Acceptance, risks, and rollback

Acceptance requires all 34 safeguard cases to pass direct fresh-child and
manifest-registered aggregates, exact aggregate replays, the 10 selected
visible cases plus replays, focused/system/full-suite gates, and immutable
optimizer-360 compatibility. Every negative report must contain its exact
typed/UI outcome and shared oracle; persistence cases must retain one-fault
prelaunch manifests and no activation. The optimizer control must retain all
frozen hashes and exact totals.

Risks are stale evidence after source change, incomplete child selection,
misrepresenting generated path differences, conflating the known 384x10 issue,
or committing unrelated changes. Source fingerprints, fresh roots, aggregate
child audits, exact replay commands, manual screenshot inspection, scoped Git
review, and a single commit control these risks. Rollback reverts the final
Milestone 12 commit (or the cumulative uncommitted Milestone 12 files before
commit); no retained user data, prior reports, M11A contract, or release tag is
altered.
