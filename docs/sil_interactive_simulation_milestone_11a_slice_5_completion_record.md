# Milestone 11A Slice 5 Completion Record

Status: complete with one retained pre-existing host-stress finding

Date: 2026-08-08

Commit boundary: `test: close optimizer 360 calibration lifecycle qualification`

## Qualified contract

- Scenario: `optimizer_360_calibration_reload_execution_v1`
- Capability: `execution.optimizer_360_calibration_reload_execution`
- Windows suite/tier: `host_stress` / `stress`
- Design seed: 4321; simulation seed: 1
- Optimized reagent stocks: 222.22222222222223, 100,
  555.5555555555555, and 20
- Optimizer outcome: seven nearest-achievable targets, zero unreachable
  targets, one execution stock per reagent
- Design: 360 literal reactions assigned to all wells in rows A-O; row P is
  unassigned
- Applied volumes: 10.8, 12.6, 14.4, 16.2, and 18 nL
- Execution: five 360-intent passes, 1,800 unique intents, and 46,208 droplets
- Sessions/revisions: sessions 1-3; revisions 1-8; session 2 owns all
  execution; sessions 1 and 3 dispatch nothing

## Frozen hashes

| Contract | SHA-256 |
| --- | --- |
| Fixture | `d7f4de4aafeaf4a66751872d017d89393c263d48b5ffefa1b0e1690efaa10783` |
| Case | `f238d4d90b822fdf52d4170b1f6fc1871b3d73f56df3aad543637f3e5d4078d8` |
| Requested reaction multiset | `5acfa8580c581231275e2b6f17ec757d71df5dcc4696196e1c0f9b2176ee7afd` |
| Achieved reaction multiset | `418cf4a50cc0015c52b9b093a5df9096df98930dc0f58f42aa37c30830fe64f0` |
| Assignment | `5f84bfd4cd7c2c0d4b289b6797c50feeab9739a65d56ac2fc3949da030ab3ed2` |
| Expanded count oracle | `3f86a60425d2c0d6abf0839d9f0fca16a41a6e398125053dd849d2e9b397458f` |

## Direct and replay evidence

| Run | Result | Report SHA-256 | Evidence-manifest SHA-256 | Bytes |
| --- | --- | --- | --- | ---: |
| Offscreen direct `20260809T022626138906Z_composed` | pass | `572e017ff339e667ee115910c56e504bf9472a0a0c111aef98b85a3adcebada4` | `9a834ff97388a705be43a9c18a664a6965e47a1d187c52aa5770a1a172a64a11` | 68,845,718 |
| Offscreen exact replay `20260809T022913051967Z_composed` | pass | `5b37fc340c094d1acafb6c8f298e7dff5b0f077f544661351a6cd240edc0e3be` | `89125bee04bc419bc07b3bc5a98c598f7d074e3560ce1372d2d874779450c6fc` | 68,854,467 |
| Visible direct `20260809T023200572605Z_composed` | pass | `c1de1a08894809c2430d9ee91a173c31fe34f6a09983bc4d757ae3facf96b1f1` | `e1a2aebc162605fda0cdd4f393b88bee91df5727253df1e52fa545ca4acd9f58` | 68,223,526 |
| Visible exact replay `20260809T023458134338Z_composed` | pass | `0b955706b791b03a2d33e7e2609c627627123d83f712f9e405aaaf67168dc851` | `797f026325aa31b8517ae834c6d5a7c54c4e53d987c063714915a62df2a9419b` | 68,242,762 |

Each retained run contains 22 evidence files and all 16 case-owned
screenshots: optimizer stocks, prepared randomization, five calibration
checkpoints, fresh load/activation, five pass completions, terminal completion,
and terminal reload. The audited visible direct report records 117 actions,
below the cap of 160, and every report records
simulator evidence below the 10,000-event cap with zero overflow.

## Suite and regression results

- Focused registry/manifest/oracle/terminal suite: 105 passed.
- Registered optimizer lifecycle system test: 1 passed.
- Existing Milestone 11 registered lifecycle compatibility test: 1 passed.
- Complete lifecycle suite: 9/9 passed; aggregate SHA-256
  `f33fce64322eaa16bcc2ec1d5c350775e8f66257bb35a251550b3f0cc655b2dd`.
- Host regression: 1/1 passed; aggregate SHA-256
  `9fc32014da9cc29405f10b14512449a8bcf202ec5f97ba181db3c15664ee71e0`.
- Complete default Python suite: 4,203 passed, 93 skipped, 389 warnings in
  374.01 seconds.

## Retained host-stress finding

The complete two-child `host_stress` aggregate was executed and retained at
`verification_reports/milestone_11a/host_stress/host_stress/
20260809T023824473592Z_4e1ca4b6-2ba/aggregate.json`, SHA-256
`c976cb817585d353c27f90bf38880609c3240c9eb564568d6232463990da65a3`.
The new optimizer child passed. The pre-existing
`virtual_print_array_384x10_v1` child failed
`execution.stock_head_settings_match`: its fixture owns per-stock pulse widths
1300-1390 microseconds while the existing stress journey stages every head at
the fixed 1355-microsecond calibration. Retained reports from before Milestone
11A show the same fixed value. This milestone does not change that historical
scenario, its fixture, production behavior, or literal truth. Any correction
requires a separately reviewed plan.

## Safety, compatibility, and closeout

- No production MVC, protocol, firmware, physical-machine behavior, persisted
  application schema, release metadata, or hardware behavior changed.
- No Pi lane or physical hardware was accessed.
- Milestones 9-11 fixtures, hashes, catalogs, scenario IDs, report schemas,
  replay behavior, and negative no-mutation contracts remain intact.
- The two Milestone 11 registry-freeze checks now assert continued membership
  rather than incorrectly requiring the historical scenario to remain last.
- Milestone 12 is restored as the current next action.
