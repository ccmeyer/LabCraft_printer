# Milestone 13 Slice 13.5 Implementation Plan

Status: `complete`

Started: 2026-08-09

## Objective and qualification path

Freeze the completed M13 contracts, run the source-current release gate, add
operator documentation, and close the milestone without adding any operation,
seed, state, budget, or production behavior.

```text
catalog/hash audit
-> frozen direct children + aggregate + retained-plan replay
-> visible direct/replay representatives
-> deterministic M9-12 + immutable optimizer-360 compatibility
-> lifecycle/host-regression direct/replay
-> focused/system/default pytest
-> report/hash/screenshot/cleanup audit
-> README/runbook/completion records
```

M13 remains supplementary exploration. Its aggregate is deliberately not
joined to registered capability coverage, matching the existing M8 exploration
policy. The manifest is inspected and tested but changes only if its existing
schema explicitly requires a campaign record.

## Scope and exclusions

Freeze seeds `13, 29, 47, 83, 131, 197`, 12 states, 26 operations, 34 frozen
transitions, eight rejection classes, all current hashes, and the `80/480`
action budgets. Run four visible direct/replay representatives: seeds 13, 47,
131, and 197. Retain exact reports, screenshots, hashes, source identities,
cleanup, and commands.

No reducer, new diagnostic promotion, production fix, firmware/protocol/
hardware change, refill/resume, scheduler, `pi_stress`, complete `host_stress`,
or 384x10 fixture correction is in scope.

## Plan

1. Audit catalog/list/dry-run/hash/manifest stability.
2. Run final frozen aggregate and exact retained-plan replay.
3. Run and inspect four visible direct/replay representatives.
4. Run M9-12 and immutable optimizer-360 direct/replay compatibility.
5. Run lifecycle and host-regression aggregates and replays.
6. Run focused tests, assigned system tests, and full default pytest.
7. Update README/runbook and completion/master records with exact evidence.
8. Run final Git/diff audit and create one milestone commit without pushing.

## Files likely to change

- `README.md`
- `docs/sil_virtual_workflow_operator_runbook.md`
- Slice 13.5 and overall Milestone 13 completion records
- Milestone 13 execution/master status and evidence summary
- manifest/registry tests only if inspection finds an explicit required join

## Acceptance, risks, and rollback

Acceptance is the exact final gate in the Milestone 13 execution plan: all
frozen originals and replay, complete semantic coverage, visible evidence,
diagnostic isolation, original-failure preservation tests, M9-12 and
optimizer-360 compatibility, lifecycle/host-regression compatibility, focused
and system tests, full default pytest, cleanup, and `git diff --check`.

Any source correction restarts affected source-current qualification. The
known 384x10 mismatch stays separately scoped. Rollback removes M13 campaign,
v2 runner, tests, and M13 documentation while retaining M8, deterministic
M9-12/11A evidence, historical reports, and all user experiment data.
