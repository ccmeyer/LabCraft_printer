# Milestone 10 Slice 10.4 Completion Record

Status: complete (2026-08-08)

Commit boundary: `test: add well selection and randomization design SIL cases`

## Delivered scope

Slice 10.4 appends only `custom_wells_with_exclusions` and
`multi_reagent_seed_1234` to the executable
`experiment_design_pairwise_v1` prefix. The reusable editor driver now stages
typed exclusions after the real New Experiment reset, opens the real Qt
Printable Wells dialog, explicitly attempts disabled cells, selects the
remaining declared wells, and retains the exact picker state and screenshot.

The exact call path is:

```text
matrix selector -> fresh child -> experiment_design journey
-> New Experiment through Qt -> scenario-local WellPlate exclusions
-> Qt Printable Wells dialog -> disabled-cell click rejection
-> ExperimentModel custom selection or Qt seed control
-> Optimize/Generate -> Finalize Design
-> MainWindow -> application Model authoritative files
-> Qt reload -> reconstructed assignments
-> selected/excluded/assigned and canonical hash assertions
```

Controller is observed idle only at reload. No production MVC, page-driver,
journey-phase, fixture, schema, manifest, firmware, protocol, hardware,
motion, pressure, printing, timing, or physical-calibration code changed.

## Independent-oracle corrections

Fresh execution exposed two catalog-only mistakes in the newly activated
cases. Their Water counts had been written as if fill droplets were 10 nL,
but the typed inputs and unchanged editor default both specify 9 nL. The
literal independent expectations were corrected to the ceiling counts:

- custom exclusions: `A1=10`, `A3=9`, `A4=8`;
- seed 1234: `A1..A8 = 7, 6, 8, 9, 7, 8, 9, 6`.

No production observation is used to calculate expected values at assertion
time. Explicit unit contracts now freeze these literals. Cases 1-4 and all
Milestone 7-9 identities remain unchanged. The affected identities are:

- `custom_wells_with_exclusions`:
  `d7226b2e801489066516b46206274706a85749c4a73cfdfa4cc3df289f4391cf`;
- `multi_reagent_seed_1234`:
  `795a80c456f8af02e1b759a95de96994cd8dc6fbb4a8ed640fe0ee2f7b385f29`;
- full planned nine-case catalog:
  `3bab3f49d6cb40786ca1d8a251d923c2392271cd4b513a626318d8f98c6ce590`;
- test-local nine-case definition:
  `fe45b2cefcf701e7977f7b968ba5420db6b9aab4f4ab8d731769ef1a27c66a74`;
- test-local nine-case plan:
  `935b11e042dc208cee7ed1cd5c7caf3f17a4f559d2c110344e2eef7d8a639e41`;
- registered six-case prefix:
  `0d11ae9e92176c4812450f4deac9d72872001ba5e5aaf862985348802d1ca3a1`;
- selected control dry plan, seed 7, timeout 12, execution unauthorized:
  `9d9eaaf59df4eee0484f1d600f0f7c6ca83f19924bf727a736c95441062465ea`.

The unchanged reference fixture remains
`fc2bdf34fa5a7d8a9e851ace7a099aa8e05c61c2d0cd075b620d69937f8bfc45`.
Report-v1, matrix plan/aggregate v1, selector, and replay formats are
unchanged.

## Exact results

The exclusion case records declared wells `A1`-`A6`, disabled and rejected
cells `A2` and `A5`, and selected printable wells `A1`, `A3`, `A4`, and `A6`.
Only `A1 -> R1`, `A3 -> R2`, and `A4 -> R3` are authoritatively assigned;
neither excluded well appears in the plan or reconstructed runtime. The
picker screenshot visibly retains four selected blue cells and two disabled
gray cells.

Both randomized cases retain reaction-multiset SHA-256
`b189fe1ed4b975953600c7d299fd320be366eda827ceb39f28cf3a3bbc22b696`.
Seed 4321 retains assignment SHA-256
`e264b345bddb83c2aeb12bf6421d83a81d21c8b9f31ff6698780164a1bee82ef`;
seed 1234 retains distinct assignment SHA-256
`1ecbf5c4967d71a45fe33b6ac8cb858e3334b02bb1933f37ebbeddeae36450e9`.
Same-selector replays reproduce the exact assignment hashes.

Every retained run finishes at plan revision 1 with zero progress, no resume
file, `ready_to_start`, byte-identical reload, exact stocks/counts,
Controller idle, inactive runtime, hardware interfaces false, and successful
scenario cleanup.

## Validation

Focused catalog, selector, driver, assertion, composition, assignment, RNG,
and picker tests:

```text
180 passed in 7.56s
```

Selected new fresh-process cases:

```text
2 passed in 8.37s
```

Cross-seed fresh-process comparison:

```text
1 passed in 8.42s
```

The complete experiment-design system file was also run as a bounded
compatibility check for cases 1-6 and the comparison contract:

```text
7 passed in 33.11s
```

Both new offscreen cases and their exact replays passed 6/6 assertions. The
visible exclusion representative and its exact visible replay also passed
6/6. Manual inspection confirmed the picker selection and disabled-cell
rendering in both visible screenshots; both images have SHA-256
`655a783c74b4e0ca9188ecbcf9ff6bfa0dc921272b603762f046fcc40b106808`.

Retained evidence:

| Run | Report SHA-256 | Evidence manifest SHA-256 |
|---|---|---|
| custom offscreen | `ef5197aacc79ebe6bcf5cfed8a09b2da1f12b71df431b84cdef8e9024ec7bf96` | `906ee55e2cff4a994ab85f70758cba9188f7b55a07654e5bc73f961238c72258` |
| custom offscreen replay | `10643f7cd82640b2591d5b3fccc13318774f3a7542a01ca0b3d8e2259a037e35` | `8e43b91566a3cbf545591e7b7743d18d06644384cfba9a712cade2b71fd19ae0` |
| seed-1234 offscreen | `38ef78a9354a2b002bc3619a1260a7827744d87ad507c5c473c449dea9eec45b` | `004024c2c0fdf22cf9f868a2975b68d471fca495939fc40c9372c840134ccab3` |
| seed-1234 offscreen replay | `4617602279f5ac7e03627be3c0f12971130b968ae9508940b40ca90b847d8243` | `2a2b56ead6143ba230eed08605975ba8e89e24ba995f211a15372634d43f9a09` |
| custom visible | `baf4c7ead3d499c8acbb2b1bbb822f8fe7065a6cbd5a4d8496bbe2fa0969bc80` | `62c213751510f690158edc3d4589b8e32057153a3f860f06c9020cbcbb824192` |
| custom visible replay | `8b6fc929058dc5723f7ee6abcd392f6c5cd8ecb39fc4ae27da5f2686f6cbd722` | `cb2e845f56851ed05be20bf48494fde13caec697e3c226a5a2efb99ed3981a34` |

Evidence roots:

- `verification_reports/m10-s4-offscreen-custom/`;
- `verification_reports/m10-s4-offscreen-seed1234/`;
- `verification_reports/m10-s4-visible-custom/`.

## Risks, rollback, and next action

The harness applies exclusions only after the production New Experiment
reset, requires an empty prior state, and each case runs in a fresh child.
The driver fails closed on any disabled/selected set drift, and the oracle
separately rejects excluded authoritative assignments or reload mutation.
The process-global RNG contract remains covered by focused tests.

Rollback reverts only this slice commit and restores the four-case executable
prefix. Slice 10.5 is next: add exact-capacity success and both rejected
finalization boundaries with exact warning/status and authoritative
no-mutation evidence. The complete nine-case matrix/replay, broader
regressions, and full Python suite remain deferred to Slice 10.6.
