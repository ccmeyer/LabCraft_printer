# Milestone 13 Slice 13.3 Implementation Plan

Status: `complete`

Started: 2026-08-09

## Objective and call paths

Implement only frozen seeds 47, 83, 131, and 197. Each generated rejected
operation uses its exact existing M12 case and the shared
`safeguard_rejection_no_mutation_no_dispatch` oracle. An outer M13 boundary
also snapshots the current compact authority before the isolated M12 action
fixture and after fixture cleanup, so fixture lifecycle setup cannot masquerade
as generated-state mutation.

- Seed 47: invalid real editor Finalize and one-stock Optimize & Generate
  dialogs -> M12 editor boundary -> valid New Experiment/configuration recovery
  -> compact terminal lifecycle.
- Seed 83: real calibration preflight Cancel -> M12 typed mode-mismatch oracle
  -> matching calibration Generate/Select/Apply -> terminal lifecycle.
- Seed 131: fresh inactive load -> inactive Start rejection -> activation ->
  wrong-head identity rejection -> matching identity/calibration continuation ->
  terminal lifecycle.
- Seed 197: first stock pass -> progressed/read-only edit and calibration
  rejections plus active-boundary Start/head-exchange rejections -> isolated
  fixture cleanup -> second valid stock pass -> terminal reload.

## Scope, exclusions, and state contract

The slice adds no new rejection wording or weaker success criterion. It reuses
the exact M12 case hashes, expected outcomes, Qt controls, and shared boundary
oracle. Rejected normalized transitions retain the same source/target state;
the outer compact authority, plan/progress revision, files, runtime assignment,
queue counters, and dispatch counters must be identical after each rejection.
Recovery must consist of already-qualified real operator actions and must end
at the same exact `4/2/8/44` terminal authority.

The M12 action fixture may temporarily project its frozen lifecycle label or
control state in memory. That test-owned projection must be restored before the
outer M13 after-snapshot and may not write an active authoritative file. This
is fixture cleanup, not recovery; terminal recovery remains the real compact
Qt lifecycle. No user data, firmware, protocol, hardware, refill/resume,
unseeded walk, scheduling, or known 384x10 scope is admitted.

## Implementation plan

1. Add unique M13 rejection-wrapper assertions around the frozen M12 oracle.
2. Make M12 rejection screenshot capture optional without changing its
   default behavior or frozen deterministic cases.
3. Add loaded/activated and post-pass hooks to existing journey phases.
4. Compose seed 47's two editor rejections before compact valid recovery.
5. Compose seeds 83/131 at prepared and reload/activation boundaries.
6. Compose seed 197 after the first durable stock pass and restore only the
   isolated fixture projection before valid continuation.
7. Add focused and real-Qt tests, then run direct/replay for all four and
   visible direct/replay representatives.
8. Audit budgets, evidence, hashes, cleanup, and write the completion record.

## Files likely to change

- `tools/virtual_workflows/actions.py`
- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/journey_phases.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/exploration_m13.py`
- `tools/virtual_workflows/m13_interaction_cases.py`
- M13 focused and system tests
- Milestone 13 master/execution/Slice 13.3 records

No production MVC, simulator implementation, firmware, protocol, manifest, or
frozen M8-12/11A fixture is expected to change.

## Budgets, tests, acceptance, and rollback

The provisional 64-row legal-only cap must be requalified against the largest
illegal sequence before the first passing Slice 13.3 report; any reviewed
increase remains inclusive, versioned, and fail closed. All other caps remain
18 semantic operations, three sessions/two rotations, four screenshots, 256
files/48 MiB, 270-second scenario deadline, 300-second child watchdog, and
`4/2/8/44`. No retry may silently enlarge a cap.

Acceptance requires every exact M12 oracle and outer M13 continuity wrapper to
pass; literal rejection UI evidence; zero rejected-operation dispatch; four
valid terminal boundaries; exact direct replay; selected visible direct/replay;
focused unit/system tests; cleanup without locks; and `git diff --check`.

Rollback removes the M13-only wrapper/hooks/branches and tests, restores the
Slice 13.2 legal-only execution gate and budget, and leaves deterministic M12
cases and all user data unchanged.
