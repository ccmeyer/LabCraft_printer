# Milestone 7 Slice 5 Completion Record

Status: `complete`

Completed: 2026-08-06

Planning baseline: `8cbe492f408421cece0ae77bf5960685b1aea3d6`

## Outcome

`authoritative_reload_resume_24_v1` now uses the generic
`composed_journey` runner. The fixed fixture remains unchanged at SHA-256
`20B0EA605B74E1C282D7DD62E1B1A04C2FF1B76616E6BF87994055E6FBD7CDE5`.
The composed journey:

- creates the A1-A24 design through normal Qt controls;
- starts printing, requests the existing soft stop after completion 6, and
  proves bounded catch-up, an empty paused checkpoint, and quiescence;
- closes the first application composition with its recorder healthy and
  closed while retaining the SIL root;
- opens a fresh application composition with a distinct application and
  recorder identity on the same retained session;
- loads the saved folder and explicitly selects `Load Execution` through the
  real Experiment Editor and `QFileDialog` surfaces;
- proves load is byte-identical and inactive, then limits activation writes to
  the existing authoritative allowlist;
- reconnects, homes, stages the persisted calibrated head, and resumes through
  the normal array control without recalibration or completed-work replay;
- reconciles exactly 24 terminal stock/well completions, intent durability,
  the completed plan, clean checkpoint, recorder closure, and lock removal.

No production MVC, simulator response model, protocol, firmware, Pi, or
hardware file changed. No OS-process restart is claimed: both fresh
application compositions share one in-process `QApplication`.

## Reusable Implementation

- `AutomationHarness` owns clean application-session close/reopen and ordered
  recorder/session evidence.
- `ExperimentLoaderDriver` owns the shared bounded editor and nested directory
  chooser mechanics for prepared and authoritative loads.
- Shared phases own stock-head staging, soft-stop milestone customization,
  persisted-head restaging, session rotation, observer rebinding, load/
  activation boundaries, and resume.
- Shared authoritative evidence owns directory comparisons, activation
  allowlisting, completed-pair projection, and multi-session lifecycle merge.
- Shared assertions project the twelve frozen paused, rotation, rehydration,
  no-replay, durability, terminal, and artifact decisions.
- The legacy direct oracle delegates to the same page driver and boundary
  policy while remaining directly callable for parity and rollback.

The registry gained no scenario-ID conditional and no dedicated Slice 5 runner
wrapper. The named `_authoritative_reload_body` is 97 physical lines and its
payload builder is 40. Touched runtime net growth is exactly 600 physical
lines, meeting the approved ceiling; scenario-specific `journeys.py` net
growth is 259 lines.

## Automated Validation

Reusable session, driver, evidence, assertion, report, manifest, and contract
selection:

```text
194 passed in 8.50s
```

Production-adjacent authoritative load/resume selection:

```text
97 passed in 2.93s
```

Focused composed success/parity/failure and journey regressions:

```text
11 passed in 64.59s
```

That lifecycle selection included the composed authoritative success, direct
oracle parity, first-session persistence mutation, disallowed activation-time
write, the legacy authoritative oracle, Slice 4 soft-stop composition, and the
24-well smoke. Both controlled mutations failed at their authoritative
boundary, retained failure evidence, completed best-effort teardown, and left
no lock.

The CLI help and focused module compilation passed. `git diff --check` passed.
The complete Python suite was intentionally not run; it remains the final
Milestone 7 validation gate.

## Visible And Replay Evidence

The normal visible Windows command and the exact emitted replay both passed:

```text
verification_reports/milestone7-slice5-visible/
  authoritative_reload_resume_24_v1/
    20260807T032228144591Z_composed/report.json
    20260807T032306938809Z_composed/report.json
```

Each report records 43 ordered actions, 12 passing assertions, eight non-empty
screenshots, two distinct completed application sessions with closed
recorders, 24/24 completions, and clean teardown. Their stable projections are
equal for fixture hash/seed, action IDs/surfaces/statuses, dialog titles,
assertion decisions, screenshot keys, session order/status, authoritative
load and activation checks, no-replay/terminal relationships, classification,
and lock state. Generated identities, paths, timestamps, durations, and
identity-bearing hashes differ as expected.

## Risks And Limitations

- The direct legacy runner remains sizable and should be removed only after
  the portfolio migration and final Milestone 7 validation make its parity
  role unnecessary.
- Qt nested dialogs remain timing-sensitive, but the driver accepts only the
  exact editor, folder dialog, action label, and bounded workflow and fails
  closed otherwise.
- The simulator does not validate firmware, protocol framing, physical motion,
  pressure response, cameras, balances, collision safety, or droplet quality.

## Rollback

Restore only the `authoritative_reload_resume_24_v1` registry and manifest
entry to `virtual_print_array`, remove its journey definition and Slice 5
tests/documentation, and retain the direct oracle. Keep generic harness,
driver, evidence, assertion, and head-staging consolidation only if their
focused tests remain green; otherwise revert those Slice 5 changes together.
Do not revert Slices 1-4, the fixture, production data, firmware, protocol, or
unrelated user changes.

## Next Boundary

Stop before post-start lock/editable-copy migration. That is the next candidate
slice and requires its own concrete plan. Broader parameter matrices, seeded
sequence exploration, fault injection, performance work, Pi operations,
firmware/protocol changes, and hardware work remain out of scope.
