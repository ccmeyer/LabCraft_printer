# Milestone 13 Slice 13.3 Completion Record

Status: `complete`

Completed: 2026-08-09

## Outcome

Frozen seeds 47, 83, 131, and 197 now execute their admitted invalid
operations through real Qt/operator controls, reuse the exact deterministic
Milestone 12 case and shared no-mutation/no-dispatch assertion, prove the
surrounding compact authority is continuous, recover only through valid
operator actions, and finish at the same authoritative `4/2/8/44` terminal
boundary as the legal seeds.

The four sequence classes cover two draft-editor rejections, calibration
mismatch Cancel, inspected-inactive Start, wrong-head identity, progressed
editing and recalibration, Start while active, and unsafe head exchange. Each
rejected normalized transition retains its source state. The report preserves
the exact M12 case hash, typed outcome, before/after persistence/model/
lifecycle/queue/dispatch evidence, unique M13 wrapper assertion, recovery
lineage, terminal hashes, screenshots, and cleanup.

## Budget and frozen-hash correction

The legal-only 64-row cap from Slice 13.2 was explicitly provisional. The
largest qualified illegal sequence, seed 47, records 65 action rows including
teardown. Before the first complete Slice 13.3 qualification, the strict
inclusive cap was therefore versioned to 80 rows per sequence and 480 rows
for the six-sequence campaign. No action, oracle, assertion, screenshot, or
operator boundary was removed to fit a budget. All other caps remain
18 semantic operations, three sessions/two rotations, four screenshots,
256 files/48 MiB, 270-second scenario deadline, 300-second watchdog, and
`4/2/8/44` per sequence.

The budget correction changes only these current frozen projections:

- catalog SHA-256:
  `0d11d8dda4400620ffb053234ae29280cf776b4a8db812af9b7517da4db5825d`;
- campaign SHA-256:
  `fe1930114a7dc848b4a5a6c148d56907f661ae7b757450e6785a91673962e2c5`;
- compact case SHA-256:
  `46d6c60efd32bf4671c631f80e75bace7312698eaea40d3fa32ef598a682aa25`;
- refinalized compact case SHA-256:
  `c44570843ef88c6842948c90a87d2e83aff94de2ed4297f5a62214266a096851`.

The state, operation, oracle-ledger, frozen-set, fixture-projection, design,
and six normalized sequence hashes are unchanged. In particular, M8 remains
at catalog SHA-256
`7cfb5efa7e36175504a2fa04a6483add993f6db13d25bdd183dcd0d6809925e8`.

## Qualification evidence

All four offscreen direct runs and exact emitted replays passed. Visible direct
and replay qualification passed for the required Slice 13.3 representatives,
seeds 47 and 131. Every run retained exactly the four screenshots
`prepared`, `fresh_loaded`, `fresh_activated`, and `terminal_reloaded`, three
application sessions, eight intents, 44 droplets, terminal plan state
`completed`, passing cleanup, and no unexpected dialog or session lock.

| Sequence | Actions | Direct report SHA-256 | Replay report SHA-256 |
| --- | ---: | --- | --- |
| seed 47 | 65 | `cd0cf33fe4209c400968106dcab7086d89395e896e60a6182ecaba7f65cfb9e5` | `b600526cfd0409a743ee93c2f94600e248cc5fd3da7e5d24c8208d98119f036e` |
| seed 83 | 58 | `12c15bd71c5ff78e3517717cdb9ce355b5e0bb39a2d0b8ea3fcc22a63e09e5c3` | `7ce0843577d78973990af9381c982e19138f5789de0083a2a2454ef13c3f93ba` |
| seed 131 | 59 | `c5aead5193669da340272d80ad0f3e4cf1fea2ba56a7ad1a235622d7a5e97529` | `79c439054b8c731c50ab2bc48c0d4a04c32f5bec329fe03893b73951d304f577` |
| seed 197 | 61 | `0e23f948644f6267cc305734a4250a1aef38f80ea4149b38161cf89933b00a4b` | `95146cfcfa60aa067454a6a90b9baf6468623cc637aeea66042c9f199ca9b763` |

Visible seed-47 direct/replay report hashes are
`a610d3a642f7b1f4681b2ade31344b0fa88f66694d76e1772b0a4f22e8829b82`
and
`6d1f3911de51ca6a0d4824b2ddc54ee1174eaf60801098022bb723a29d67e7e2`.
Visible seed-131 direct/replay report hashes are
`a5fdb08388b11c38f6ca6b45ce5870ed284d33b613475ded34a74f433ed47daf`
and
`dfa5aefccc0266aac1b8a2b40cbf263fefc55777f7921c39af95b6558f4c408e`.
Slice evidence under `verification_reports/milestone_13_slice_3/` contains
136 files/24,390,742 bytes, below the retained evidence limits.

## Automated validation

Passed commands included:

```powershell
.\env\Scripts\python.exe -m pytest -q tests\test_virtual_workflow_exploration_m13.py tests\test_virtual_workflow_m13_interaction_cases.py tests\test_virtual_workflow_actions.py tests\test_virtual_workflow_assertions.py tests\system\test_virtual_workflow_m13_exploration_execution.py
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle tests\system\test_virtual_workflow_m13_exploration_execution.py
git diff --check
```

The default-marker focused selection passed 79 tests with six expected
lifecycle skips. The real-Qt lifecycle selection passed all six legal and
illegal sequence tests. Direct, replay, and visible commands are preserved in
the reports. Analysis-pipeline tests were not run because that code did not
change.

## Files changed

- `tools/virtual_workflows/actions.py`
- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/journey_phases.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/exploration_m13.py`
- `tools/virtual_workflows/m13_interaction_cases.py`
- M13 focused and system tests
- Milestone 13 master, execution, implementation, and completion records

No production MVC, simulator implementation, firmware, protocol, physical
calibration, motion, pressure, refill, hardware, M8 campaign, or frozen M9-12/
11A scenario changed.

## Risks and rollback

The generated journey deliberately reuses isolated Milestone 12 lifecycle
fixtures. The M13 wrapper restores only fixture-owned runtime/queue projection
before taking its outer continuity snapshot; it does not mutate an active
authoritative file or substitute cleanup for valid recovery. Unique case and
wrapper assertions fail closed if routing, wording, identity, dispatch, or
state continuity drifts.

Rollback removes the M13-only rejection routing, optional hooks, wrapper
assertions, tests, and Slice 13.3 records; restores the Slice 13.2 legal-only
execution gate and cap; and leaves all deterministic cases, retained evidence,
and user experiment data untouched.
