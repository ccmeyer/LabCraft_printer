# Milestone 10 Slice 10.6 Completion Record

Status: complete (2026-08-08)

## Outcome

Milestone 10 is complete. The source-current nine-case experiment-design
catalog, exact matrix replay, five visible positive/negative representatives
and replays, lifecycle suite and replay, 96-well host regression and replay,
and default Python suite all pass.

All accepted SIL reports identify entrance commit
`a3734333c47f36ee405d33716ea38e4085c381a6` and source-tree SHA-256
`5e825afbcaa2a7614b1e415b39ffd76df92aa7b9d4657bc5eb1da17922fdafe1`
over 893 execution-input files. Reports record `dirty_worktree: true` only
because the Slice 10.6 implementation plan was the sole untracked file;
documentation and retained reports are excluded from the versioned
execution-input fingerprint.

Slice 10.6 changed documentation only. Milestone 10's separately planned and
reviewed optimizer-accuracy correction remains isolated in commits `649b4a5`
and `6c05b80` and is recorded in
`docs/sil_experiment_design_two_stock_accuracy_correction_completion_record.md`.
No firmware, protocol, hardware, motion, pressure, physical calibration,
fixture, report schema, aggregate schema, or capability-manifest behavior
changed during closeout.

## Frozen contracts

- registered `experiment_design_pairwise_v1`: nine cases, catalog SHA-256
  `acbd4d82f8c7ea6dd842c4ad88bd472c4b50f3a73822dc8c34cfded0dec6f59f`;
- complete planned catalog SHA-256
  `15ec261cf19bec2f2758d76f8c8102d0d246eef02ff165a4bdb104b1a9e8dfcd`;
- deterministic dry-run plan SHA-256
  `2104933b4792f3dfddd70df9bc89b18fcb339f9c1c647d4ecfed7f86b8c1f042`;
- executed matrix plan SHA-256
  `074fe5e7889fabe03d2be9ebad41c4a32379786639da91eec27b8273e252bcc8`;
- unchanged editor reference fixture SHA-256
  `fc2bdf34fa5a7d8a9e851ace7a099aa8e05c61c2d0cd075b620d69937f8bfc45`;
- preserved `calibration_requantization_v1` catalog SHA-256
  `d826a9e54c2e6190acfd5afdb0b2475de2be62557647aafa378890ca826c55af`;
- preserved `mixed_mode_calibration_v1` catalog SHA-256
  `d2439c2e47cb9825ad5a5024e014fd4429ff6b28dcafa54809c92fa674cff884`;
- report-v1, selection-plan-v1, matrix-plan-v1, and aggregate-v1 schemas and
  exact replay behavior remain compatible.

The ordered case hashes are:

| Order | Case | SHA-256 |
| --- | --- | --- |
| 1 | `single_reagent_control` | `b0deaaf5af7b4391d3cc92de2b03b7729ba3ea6abf7b22d122f78b9ef347c033` |
| 2 | `multi_reagent_seed_4321` | `5d2e7dff0ea9c2e0bcd1e3b218b39280aca57b745834024226fece850f110f51` |
| 3 | `one_stock_feasible` | `30ee17fcd869f6c3989d39b50d7e484ed8de233e5af6fc1f2c47cfac40230e17` |
| 4 | `two_stock_required` | `b9bd401c9f223c1576bc98938c75b2a7401958dad2048a2d048f95d4fbda2fff` |
| 5 | `custom_wells_with_exclusions` | `d7226b2e801489066516b46206274706a85749c4a73cfdfa4cc3df289f4391cf` |
| 6 | `multi_reagent_seed_1234` | `795a80c456f8af02e1b759a95de96994cd8dc6fbb4a8ed640fe0ee2f7b385f29` |
| 7 | `exact_custom_capacity` | `ddb0b20ba5722ce748fde01e17d589036d0d88b3117ae78130101f7bad7cc551` |
| 8 | `capacity_plus_one_rejected` | `16af7c74a8e4d5840e24317b20996a1bc511a1d26641e5e4a5dce10b31fca21a` |
| 9 | `fixed_stock_exceeds_max_rejected` | `c386c67a6d5da03ff4a376f5631189881fb16b9d49f758a5a94a42bca10bcca9` |

The catalog's named 14-pair audit is complete. Expected stocks, reactions,
assignments, capacity values, and warnings remain literal catalog data; they
are not computed by production optimization or assignment algorithms.

## Complete aggregate qualification

All execution was retained beneath `verification_reports/m10-s6/`.

| Qualification | Result | Aggregate | SHA-256 |
| --- | --- | --- | --- |
| experiment-design matrix | 9/9 pass | `verification_reports/m10-s6/matrices/experiment_design_pairwise_v1/20260808T213524390962Z_cb8f7234-325/aggregate.json` | `d1f033ea9de9ff252f5ce4197f06fd52ad328f87d73ccc6abf505661adf712c3` |
| matrix exact replay | 9/9 pass | `verification_reports/m10-s6/matrices/experiment_design_pairwise_v1/20260808T213608929439Z_c2d011b5-905/aggregate.json` | `b2a52205931c4a1897269eefa3dbeb3ec57a2b49c619426b4635bace63126ef9` |
| lifecycle suite | 8/8 pass | `verification_reports/m10-s6/suites/lifecycle/20260808T213826328584Z_e7960ce4-852/aggregate.json` | `2e548ba9090a279e59394579eef0b7bce7fec3069b5e0a9ef064480e14df0b6e` |
| lifecycle exact replay | 8/8 pass | `verification_reports/m10-s6/suites/lifecycle/20260808T213924527190Z_279c5c78-d16/aggregate.json` | `402c41870d2dc5720e5d8c04a40365ee1916ae7025ef6062ef1055b4bfe7ae7c` |
| host regression | 1/1 pass; 96 wells | `verification_reports/m10-s6/suites/host_regression/20260808T214021781731Z_a5506f5c-47d/aggregate.json` | `4ddfe7c8281677122faab48d841e71dc3229ffb7e1b4443de86ba228552b1f0b` |
| host-regression exact replay | 1/1 pass; 96 wells | `verification_reports/m10-s6/suites/host_regression/20260808T214037786381Z_666c1a89-dcb/aggregate.json` | `262448ffc73ae2a4c887490931ff17656d8590c99e914db2f376f63d9d22ef57` |

The original and replay lifecycle selection-plan SHA-256 is
`999ea650b46feae0ac0c85f445ae9496126d27be7904da339df140a3a60b0ae1`;
the host-regression selection-plan SHA-256 is
`be0e65b6ffa5b58518544e8ef7ae349a96d95f723a7da907e57d4853e5548f6d`.

Across 46 accepted reports, every aggregate child had a unique PID, returned
zero, avoided timeout/termination, and produced exactly one matching passing
report whose file hash agreed with its aggregate. There were zero report
classification, safety, cleanup, unexpected-dialog, or workflow-error
failures. Every report proves simulated operation, no physical hardware
interface, report-root containment, terminal-success cleanup, and absent
session lock.

## Visible Windows qualification

Each required case used `QT_QPA_PLATFORM=windows`, `--visible`, 20x speed, and
a 120-second watchdog, followed by its exact emitted replay.

Each row's `report.json` and `evidence_manifest.json` are beneath
`verification_reports/m10-s6/visible/<lane>/experiment_design_pairwise_v1/<run>/`.

| Case | Lane / run | Report SHA-256 | Manifest SHA-256 |
| --- | --- | --- | --- |
| `multi_reagent_seed_4321` | `multi-reagent/20260808T213701708150Z_composed` | `61469c5c5ae8a19ff1e6a348a72b00d32f23bdfaaeedcdcf056d4d66f6e16d92` | `b7bd713bb641c02f0bfcdbf5016024bf5662051f1012983c0408ac6fc6248282` |
| multi-reagent replay | `multi-reagent/20260808T213706777230Z_composed` | `1c304e6c39e1ae631df5198be2a7b072d38d11b8b539e6347e39f7523ecf0c9a` | `74fddae38bb8491c80a6d4a96997398ab8cff10e307fb3c350287dcf2482d880` |
| `two_stock_required` | `two-stock/20260808T213719349175Z_composed` | `5deacd6c1b1d22364338910c28a0cde1d471023e4a9a28f3438eb7181384c578` | `13bf6b1ca1d62fc53b28edea22be1d164120503d23a48a784ea2ae08e011fece` |
| two-stock replay | `two-stock/20260808T213724186330Z_composed` | `3d17f5c92b3651bcef991028bda473b00722a112f11eb91248d47d8e942afdb1` | `6d502cbd32642ba9b7363285bc2de009f8e1b3b0425fe2a32ee7c19f51cdc93b` |
| `custom_wells_with_exclusions` | `custom-wells/20260808T213738266968Z_composed` | `6897833306d87ccd3381129552725fce0ed80a836ec53edf768bdd6c237d81db` | `be1e747591e108188de06d83a773852e29c76c2ddaa0b756c5ff67d5ada84aad` |
| custom-wells replay | `custom-wells/20260808T213743010696Z_composed` | `8bc385923f89a515c4079cfcae6b6cba65cb4d307020d4fe8c883023fdffeeab` | `64ede53b0a1478bed1ceb9975a9a8e81ae61b3bb9b7a99fc870c5d5bab0c31ad` |
| `capacity_plus_one_rejected` | `capacity-rejected/20260808T213756677197Z_composed` | `f01e973a621a6eb8f38e7f66b838af63f7868905ae3ea452f5082fe7bb880e1a` | `c0dc92ab90dc61e9228011015019f33cb497d5aefc6f952ed64550bae5672809` |
| capacity replay | `capacity-rejected/20260808T213800840993Z_composed` | `fc5e5880029e926955ed42044fe0bb78a3ec6451d86de134bd8189584e2c816a` | `55cc43b8e8fdcc5923882f70dd4c506ad72496eac125fa6630a50248fa6e266d` |
| `fixed_stock_exceeds_max_rejected` | `formulation-rejected/20260808T213813358002Z_composed` | `4cb48699dc93f849c34c3b0c834b604e1d8991668469c88934e6a74d94dfc735` | `932a5dd9fa3df42f075efbde7d528edc063e16bc3d63e48b2f9b0ed201e85ca1` |
| formulation replay | `formulation-rejected/20260808T213817409008Z_composed` | `070c24be30f63e9535fb23342ef3197b8a773737e3b62815643b279161c83ad0` | `facaad5ad99ca1b8ba48c989361b645d6442b7377385f7e0ac2fdb31823f11a2` |

All 46 named screenshots across the ten visible reports were manually
inspected. Representative replay screenshot hashes are:

- multi-reagent `generated`:
  `757770016514e18098ad836bd1aef862be5829c426506b79e70a764b6426e815`;
- multi-reagent `prepared_reloaded`:
  `0d4b0546d9ba7e2244bf28cb89b7e344208f72b607c3bcc838e47fd14662a5e8`;
- two-stock `generated`:
  `143689da8cafe87adc90d2c932c5ca1507e02d56792ed133cc8ae23c4e44f93b`;
- custom-well `well_picker_configured`:
  `655a783c74b4e0ca9188ecbcf9ff6bfa0dc921272b603762f046fcc40b106808`;
- capacity `finalization_rejected`:
  `f036d1b87b52ef52446e0070c9b0c1614b5d08227bb82d687580f692fd0f0714`;
- formulation `finalization_rejected`:
  `0e5f6cf22ed30636a672cd883182012900349bb6996060cea15163fbc009587d`.

Every visible application image displays the simulation banner where the main
window is present. No visual anomaly or unexpected dialog was accepted.

## Representative design evidence

The exact matrix replay proves:

- `multi_reagent_seed_4321` and `multi_reagent_seed_1234` retain identical
  reaction-multiset SHA-256
  `b189fe1ed4b975953600c7d299fd320be366eda827ceb39f28cf3a3bbc22b696`
  but distinct assignment hashes
  `e264b345bddb83c2aeb12bf6421d83a81d21c8b9f31ff6698780164a1bee82ef`
  and
  `1ecbf5c4967d71a45fe33b6ac8cb858e3334b02bb1933f37ebbeddeae36450e9`;
- `two_stock_required` records the rejected one-stock attempt and successful
  two-stock attempt, with `authoritative_execution_artifacts_unchanged: true`
  at the rejected boundary;
- custom-well selection preserves printable `A1`, `A3`, `A4`, and `A6`, and
  keeps excluded `A2` and `A5` disabled and unassigned;
- exact capacity reconstructs four assignments with assignment SHA-256
  `918ab854c33c36a8ce05a4c09e4256f1d9acf14fb8aafc4e15ea322e03cc85cc`
  and execution-plan revision 1;
- capacity rejection shows `Insufficient Well Capacity`, five required
  reactions, and four available wells;
- formulation rejection shows `Optimization failed` and the exact status that
  fixed 35 mM exceeds max 20 mM for `Infeasible A`;
- both negative cases pass every catalog-owned warning and no-mutation check,
  retain byte-identical draft state, create or modify no finalization-owned
  execution artifact, do not activate runtime execution, and dispatch zero
  durable intents or simulator commands.

Representative exact-replay report SHA-256 values are
`11e03c8e56552233a078c3a7064255b85d56843c05ef0a83951c875649e034d3`
for seed 4321,
`a7c6bd85f2a29d925564010d239aeba94bacd9c5df77a1f569a5c5b179d9e5d6`
for two-stock,
`57fa71ba07fa1c61e411f67ac21865b6c0021c627e62ce539c265067af9e979b`
for custom wells,
`1b5128165e9ee04750e951b2bdbe72fe35ab68c1fbbaa01cf90640619a9d6932`
for exact capacity,
`0cc3e5cf2b9ac9db5fe4e927faccf32effbf6a53b0a1d5cb660c099511008829`
for capacity rejection, and
`5cae55bd1fcbf1c3eb86f9d3fa8d73d148d778e6797f35c23743bc8a71e83770`
for formulation rejection.

## Complete Python suite

The default suite ran exactly once with a fresh external temporary root:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  --basetemp=C:\Users\conar\AppData\Local\Temp\m10-s6-full-20260808T2141
```

Result: `4146 passed, 88 skipped, 389 warnings in 253.90s (0:04:13)`.

The warnings are existing Qt deprecation warnings. The unrelated opt-in
analysis pipeline was not enabled, and the full suite was not rerun.

## Slice and commit record

- planning: `2bc8055`;
- Slice 10.1 catalog/contracts: `74657bc`;
- Slice 10.2 control and multiple-reagent cases: `fa6ed5c`;
- separately reviewed two-stock correction plan and implementation:
  `649b4a5`, `6c05b80`;
- Slice 10.3 formulation-feasibility cases: `b68d17a`;
- Slice 10.4 well selection/randomization cases: `6e3900e`;
- Slice 10.5 exact/rejected boundary cases: `a373433`;
- Slice 10.6: this documentation-only closeout commit.

Each implementation slice has its own implementation plan, focused validation,
completion record, and independent commit.

## Scope, risk, and rollback

This milestone proves application SIL behavior through the real Qt editor,
Controller, Model, authoritative design/execution-plan files, fresh reload,
and hardware-isolated simulator composition. Positive cases stop after
prepared reload; they do not claim physical printing. Negative cases prove
the Finalize boundary, not every later execution safeguard.

Host stress, Pi qualification, firmware checks, analysis-pipeline tests,
release operations, and physical hardware were not run. This evidence does
not claim serial protocol, firmware, motion, pressure response, droplet
quality, camera, balance, or real printer-head coverage. Refill-required and
resume remain deferred while authoritative volume tracking is disabled.

Rollback reverts only the Slice 10.6 documentation closeout commit. Slices
10.1-10.5 and the independently reviewed optimizer correction remain intact;
retained historical evidence requires no deletion or migration.
