# Milestone 13 Slice 13.5 Completion Record

Status: `complete`

Completed: 2026-08-09

## Outcome

Slice 13.5 froze and qualified `design_calibration_lifecycle_v1` without adding
an operation, state, seed, budget, production behavior, reducer, or manifest
capability. Generated exploration remains supplemental to deterministic
Milestones 9-12 evidence. Milestone 8 `editor_prepared_guard_v1` remains schema
v1 with its frozen hashes, actions, replay, and CLI compatibility unchanged.

The final executable/verification source-tree SHA-256 was
`18bea8f25850b9a3de01af16cd6591a760a92238a0d0eb46acdd46b3ab430346`.
One focused delegation test initially failed because it still expected the old
keyword set after the driver intentionally began forwarding
`capture_milestones=True`. The test contract was corrected by one assertion
row. All affected final evidence, deterministic compatibility, focused/system
tests, and the default suite were then rerun from the new source checkpoint.

## Frozen contract

- campaign: `design_calibration_lifecycle_v1`;
- generator/state/operation/oracle/coverage versions:
  `design-calibration-lifecycle-v1`, `design-calibration-state-v1`,
  `design-calibration-operation-v1`,
  `design-calibration-oracle-ledger-v1`, and
  `design-calibration-semantic-coverage-v1`;
- frozen seeds: `13, 29, 47, 83, 131, 197` in that order;
- frozen denominator: 12 states, 34 transitions, 26 operations, and eight
  rejection classes;
- catalog SHA-256:
  `0d11d8dda4400620ffb053234ae29280cf776b4a8db812af9b7517da4db5825d`;
- campaign SHA-256:
  `fe1930114a7dc848b4a5a6c148d56907f661ae7b757450e6785a91673962e2c5`;
- state/operation/oracle SHA-256:
  `71e7ca63e564a3a841bb95f9bf157fb3d491dbf2e4b80cdf027c956dab884cc8`,
  `9445809961d52f0a92cd004d374fbc38b2fc20c688ef337ff0d90ba09f8ca88d`,
  and `7ca216df7d28fd8c01e94efebb5c51ba0db249a8fde3dfa6385de5381d77351e`;
- frozen-set SHA-256:
  `1b4a2b8113392c3f59129d95d71c51ebebdc475848ab5ddb48df54a3af0f8a4e`;
- compact workload: four reactions, two executable stocks, eight intents, and
  44 droplets per sequence.

The reducer is disabled in v1. Unit tests prove every original failure is
retained byte-for-byte with its normalized SHA and replay command. Any future
reducer must emit a separately labeled diagnostic derivative and cannot replace
the original.

## Budgets and observed aggregate

Per-sequence limits are 18 semantic operations, 80 action rows, three sessions,
two rotations, four screenshots, 256 retained files, 48 MiB, four reactions,
two stocks, eight intents, 44 droplets, a 270-second scenario deadline, and a
300-second child watchdog.

Frozen-campaign limits are 108 semantic operations, 480 action rows, 18
sessions, 12 rotations, 24 screenshots, 1,600 files, 320 MiB, 24 reactions, 12
stocks, 48 intents, 264 droplets, and 1,800 seconds. The final replay aggregate
observed 70 semantic operations, 362 action rows, 18 sessions, six rotations,
24 screenshots, 83 files, 11,348,109 bytes, 24 reactions, 12 stocks, 48 intents,
264 droplets, and 54.75 seconds. Every budget check passed. Overrun policy is
`fail_closed_no_retry_or_budget_growth`.

## Frozen, replay, visible, and diagnostic evidence

All six independent offscreen direct runs and their emitted exact normalized-
sequence replays passed. The complete fresh-process aggregate and its retained-
plan replay passed 6/6 with zero failures or warnings and complete coverage.

- final direct aggregate:
  `verification_reports/milestone_13_final/aggregate/design_calibration_lifecycle_v1/20260809T180731690070Z_ad51b588-178/aggregate.json`;
- direct aggregate SHA-256:
  `5120302b688e73871f5a68bac5ba4908a53fa4ed0770d302eedc75a9df659b20`;
- final replay aggregate:
  `verification_reports/milestone_13_final/aggregate/design_calibration_lifecycle_v1/20260809T180826814207Z_42f0ebfd-206/aggregate.json`;
- replay aggregate SHA-256:
  `de65365f75522bda4d0bc39ded5a8af4c5a955e1ad0738528953f650d1ee5f8b`;
- replay semantic-coverage SHA-256:
  `226b32003422424de431768fc800b1550b7e40780b1073bb76738c69d38434af`.

Windows-visible direct and exact replay passed for seeds 13, 47, 131, and 197.
All eight screenshot sets were inspected. Each retained exactly `prepared`,
`fresh_loaded`, `fresh_activated`, and `terminal_reloaded`; the terminal view
showed the compact four-reaction design as completed and read-only with
hardware activation unavailable, and no unexpected dialog was present.

Diagnostic seed 1 passed direct and aggregate exact replay. It was retained
outside the frozen hashes with `release_gate.status: not_applicable`. Tests
also cover failing diagnostic retention and prove it cannot affect the frozen
release classification.

## Deterministic compatibility and positive control

The exact final compatibility commands in the execution plan and every emitted
replay command were executed from the final source checkpoint. The following
all passed direct and replay:

- Milestone 8 `editor_prepared_guard_v1` (10/10);
- Milestone 9 `calibration_requantization_v1` and
  `mixed_mode_calibration_v1`;
- Milestone 10 `experiment_design_pairwise_v1`;
- Milestone 11 `randomized_calibration_reload_execution_v1`;
- Milestone 12 `editor_safeguards_v1`,
  `execution_preflight_safeguards_v1`, and
  `authoritative_persistence_safeguards_v1`;
- `lifecycle` and `host_regression` suites.

The immutable Milestone 11A
`optimizer_360_calibration_reload_execution_v1` direct/replay control passed
with three application sessions, revisions 1-8, 1,800 intents, and 46,208
droplets. Its fixture, case, requested multiset, achieved multiset, assignment,
and count-oracle hashes remained respectively:

`d7f4de4aafeaf4a66751872d017d89393c263d48b5ffefa1b0e1690efaa10783`,
`f238d4d90b822fdf52d4170b1f6fc1871b3d73f56df3aad543637f3e5d4078d8`,
`5acfa8580c581231275e2b6f17ec757d71df5dcc4696196e1c0f9b2176ee7afd`,
`418cf4a50cc0015c52b9b093a5df9096df98930dc0f58f42aa37c30830fe64f0`,
`5f84bfd4cd7c2c0d4b289b6797c50feeab9739a65d56ac2fc3949da030ab3ed2`,
and `3f86a60425d2c0d6abf0839d9f0fca16a41a6e398125053dd849d2e9b397458f`.

`host_stress` and `pi_stress` were not run. The known
`print_array_stress_384x10_v1` pulse-width fixture/staging mismatch remains
separately scoped and did not weaken any Milestone 13 oracle.

## Automated validation

The final source-current results were:

- focused unit/contract gate: `356 passed`;
- assigned real-Qt/system gate: `66 passed, 3 skipped`;
- exact default suite with a 900000 ms timeout:
  `4290 passed, 134 skipped, 389 warnings` in 265.87 seconds;
- analysis-pipeline tests: not run because analysis-pipeline code did not
  change;
- `git diff --check`: pass at closeout;
- firmware checks: not applicable; no firmware or protocol file changed.

## Risks, exclusions, and rollback

No application production MVC, simulator, firmware, protocol, physical
calibration, motion, pressure, refill/resume, scheduling, or hardware behavior
changed. The campaign never writes user experiment data; every session uses an
isolated temporary root. Generated exploration does not claim hardware
coverage and does not replace deterministic scenario evidence.

Rollback removes the M13 campaign module, M13 runner, CLI selector branches,
M13 journey/assertion helpers, M13 tests, and M13 documentation. Preserve the
Milestone 8 campaign, all Milestone 9-12/11A deterministic contracts, retained
historical reports, and all user experiment data. No automatic evidence cleanup
is part of rollback.
