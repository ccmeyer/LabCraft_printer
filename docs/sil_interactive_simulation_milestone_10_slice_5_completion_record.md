# Milestone 10 Slice 10.5 Completion Record

Status: complete (2026-08-08)

Commit boundary: `test: add experiment design rejection boundaries`

## Delivered scope

Slice 10.5 appends `exact_custom_capacity`,
`capacity_plus_one_rejected`, and `fixed_stock_exceeds_max_rejected`, making
all nine curated cases executable. The positive case uses normal Qt controls,
Finalize Design, authoritative files, and Qt reload. Both negative cases use
the real Finalize Design button, retain the warning while visible, and prove
that the immediate pre/post directory, runtime, Controller, intent,
completion, and simulator-command boundaries are unchanged.

The call paths are:

```text
matrix selector -> fresh child -> typed exact-capacity case
-> Qt New/configuration/custom wells -> Optimize and Generate
-> Qt Finalize Design -> MainWindow -> application Model authoritative files
-> Qt reload -> exact reconstructed B1-B4 runtime assignment

matrix selector -> fresh child -> typed rejected case
-> Qt New/configuration/custom wells
-> [capacity only: Optimize and Generate]
-> immediate full guard snapshot -> Qt Finalize Design
-> production capacity/optimizer warning -> warning-visible screenshot
-> dismiss -> identical full guard snapshot -> no-mutation assertion
```

Controller remains idle in the rejection paths, and no comms or firmware
handler is reached. No production MVC, schema, fixture, static capability
manifest, firmware, protocol, hardware, motion, pressure, printing, timing,
or physical-calibration code changed.

## Contracts and independent-oracle correction

The editor specification now carries the catalog-owned expected terminal,
and the reusable driver supports `prepared`, `capacity_rejected`, and
`formulation_rejected`. Capacity rejection generates normally before
Finalize. Formulation rejection remains dirty so the production optimizer is
entered only through Finalize. The dynamic matrix definition selects exact
actions, assertions, screenshots, and authoritative-load behavior for each
terminal without changing registered scenario or report-v1 schemas.

The shared `experiment.finalization_rejected_no_mutation` assertion requires:

- one real Finalize activation and the exact warning title/fragments;
- the editor still visible, unaccepted, and without an apply request;
- a byte-identical full draft-directory inventory;
- absent execution plan, revision directory, key, concentration key, and
  resume artifacts;
- a preexisting New Experiment `progress.json` unchanged byte-for-byte;
- inactive authoritative runtime, empty reconstructed assignments,
  Controller/array state `idle`, and zero intents, attachments, completions,
  simulator dispenses, or simulator command events.

The static capability manifest was inspected and intentionally left
unchanged. Its schema requires every cataloged assertion to be emitted by a
registered scenario, while the established Milestone 10 contract keeps
matrix evidence outside registered suite capability aggregation. The new
assertion IDs therefore remain matrix-local and are retained in each report.

Fresh execution also exposed one catalog-only mistake in the newly activated
exact-capacity case: Water counts had been written as if the typed 9 nL fill
droplet were 10 nL. The literal independent ceiling counts are corrected to
`B1..B4 = 10, 9, 10, 9`. No production result is used to calculate an expected
value at assertion time. The affected identities are:

- `exact_custom_capacity`:
  `ddb0b20ba5722ce748fde01e17d589036d0d88b3117ae78130101f7bad7cc551`;
- full planned nine-case catalog:
  `15ec261cf19bec2f2758d76f8c8102d0d246eef02ff165a4bdb104b1a9e8dfcd`;
- test-local nine-case definition:
  `65dfb3e5a1e4ae2d7f212b9c873f8e8b660adfa1b3f5bc49080657664f35abc3`;
- test-local nine-case plan:
  `479142fd63f85b73e3d6fc1956ef87176e2465d419ca310963aba0755550ce51`;
- registered nine-case prefix:
  `acbd4d82f8c7ea6dd842c4ad88bd472c4b50f3a73822dc8c34cfded0dec6f59f`;
- selected control dry plan, seed 7, timeout 12, execution unauthorized:
  `68fe98feec0fe13883eeac6024644f105a26783b44b33b23ecc8f0c92470157e`.

Cases 1-6, all Milestone 7-9 identities, the reference fixture, report-v1,
matrix plan/aggregate v1, runners, and replay formatting remain unchanged.

## Exact results

The exact-capacity case prepares four reactions in `B1`-`B4`, reloads the
authoritative bundle, and reproduces assignment SHA-256
`918ab854c33c36a8ce05a4c09e4256f1d9acf14fb8aafc4e15ea322e03cc85cc`.
Its visible prepared-reload screenshot shows four selected wells, four total
reactions, and the expected 10 nL reagent/9 nL fill stock rows.

The capacity rejection displays `Insufficient Well Capacity`, required
reactions `5`, and available wells `4`. The formulation rejection displays
`Optimization failed` and states that fixed stock `35 mM` exceeds maximum
stock `20 mM`. Both reports record every no-mutation check true, unchanged
draft progress, all finalization-owned execution artifacts absent, inactive
runtime before/after, empty assignments, Controller idle, and zero dispatch.

## Validation and retained evidence

Focused catalog, selector, assertion, reporting, composition, and coverage
contracts:

```text
82 passed in 14.80s
```

Production-adjacent capacity, stock-input, and well-selection tests:

```text
60 passed in 1.97s
```

Shared action, journey-phase, selection, and report regressions:

```text
96 passed in 6.80s
```

Selected cases 7-9 in fresh pytest child processes:

```text
3 passed in 11.19s
```

Each of the three direct offscreen cases, exact offscreen replays, visible
cases, and exact visible replays passed. The positive report has 6/6 required
assertions; each rejection report has 5/5. Manual inspection accepted these
visible replay screenshots:

| Evidence | SHA-256 |
|---|---|
| exact-capacity prepared reload | `67d9aa5ba8f652045386a7681e133a9c753cb7499389a7fd8588fc1c8e61edc5` |
| capacity warning | `f036d1b87b52ef52446e0070c9b0c1614b5d08227bb82d687580f692fd0f0714` |
| formulation warning | `0e5f6cf22ed30636a672cd883182012900349bb6996060cea15163fbc009587d` |

Retained report and evidence-manifest hashes:

| Run | Report SHA-256 | Evidence manifest SHA-256 |
|---|---|---|
| exact offscreen | `31d33d1b8c8a692a927638c4ad7be7ea409bc05cb6a9ac7890448179ba1b6238` | `e99fe6c351b4e2e7f40d98496d160979dc04455b5f2abf91fb4eee7ea82e0e01` |
| exact offscreen replay | `29e7d16b7812e6360ed17a434f5b33e4fda01741bb5310b2dd5d13a53bf27fba` | `ff0ef2f32abf2bbc24cc468ca91ce4c4f7591bb8c9345589803c519c637f7076` |
| capacity offscreen | `323ccede8c3c908227858d985c5c7354caae71fd6f49061f11877e0f5174dc51` | `c424cd2b6ed6ac5dee166b4ce70ad269a76daf813d4d35f247ec896682919287` |
| capacity offscreen replay | `f3854257ef7d878451ae56e6085328e3d502a39f289553354540043106252cf3` | `239acdcf3af32c3f052ef2b2805b14578dfed5a8ed47c09239d64b08ec6f30da` |
| formulation offscreen | `a311f6e1add0c39acb81b5c09a693a7022b130039d6e08c813617a43790c807a` | `3097fd889b9429258b57f2ded1c5de288c73a963d93ecfccad69446dd6adc951` |
| formulation offscreen replay | `41912fb6a0b1ef003941117893b5ba13353f33b028307e3c0520624fc16adbde` | `34202c86347fd663b2c8af49189656b1b95d45141d4d89ed5ea64a4b32c91256` |
| exact visible | `4ecd1c112e7dbae2868f900274f68261b771fe9dd1107f43a4edc35af69cb0b8` | `b472618920089e94220357ea26165527e9c87324e02ab5dbff76a1dfbba86a37` |
| exact visible replay | `961e922bc3517e2a0030496430450d8dc6c85a9cbda82cf28c968944f49397f4` | `089d83325e50a9b365f66a141e2f99fb3572ca1058fd646afa7fcc361ff8fcf1` |
| capacity visible | `de9857bb7ef7881160e713b2d454fa8339ae1e26a7e61d258a6dce4e6970ef7c` | `0056230d2172c611925b1ed21d48c61721488647d24080fff5011f2a1b38e418` |
| capacity visible replay | `f052cc30ca8d23d086286ee1ffdb0f88aae3a95f5dbde58f2c4bba5bcc22ef67` | `1f67098b4d5fd370f725bbbad0183f82fc29f750242e7c394be433c580d6a0a3` |
| formulation visible | `52fa815cd8c9b785472f398133070d26487fa12491e4a3b9ab6c96e81864e7e0` | `704a0132540dfb063f79b543d864d49d6d3904159f1d76b4d05ac1b81af915db` |
| formulation visible replay | `c0b7d9d32e2e9f36543b6b71db869c35e0d3cbce18222e6087c5f80cd65f092f` | `19cb272c1addddf69c6041a47f522b26cda5efaac0209fd53b5f1599ff570442` |

Evidence roots:

- `verification_reports/m10-s5-offscreen-exact/`;
- `verification_reports/m10-s5-offscreen-capacity/`;
- `verification_reports/m10-s5-offscreen-formulation/`;
- `verification_reports/m10-s5-visible-exact/`;
- `verification_reports/m10-s5-visible-capacity/`;
- `verification_reports/m10-s5-visible-formulation/`.

## Risks, rollback, and next action

The driver baselines immediately before Finalize and compares the entire
guard state, not only named files. It treats draft progress as permissible
only when already present and byte-identical. Any unexpected modal, accepted
dialog, runtime activation, authoritative artifact, directory mutation, or
dispatch fails closed. Rollback reverts this slice commit and restores the
six-case executable prefix.

Slice 10.6 is next: from clean committed Slice 10.5 source, qualify and replay
the full nine-case aggregate, inspect visible positive/negative
representatives, run lifecycle and host regressions plus the complete default
Python suite, retain evidence, update operator documentation, and close
Milestone 10.
