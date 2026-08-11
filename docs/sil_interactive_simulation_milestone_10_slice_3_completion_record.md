# Milestone 10 Slice 10.3 Completion Record

Status: complete (2026-08-08)

Commit boundary: `test: add formulation feasibility design SIL cases`

## Delivered scope

Slice 10.3 appends only `one_stock_feasible` and `two_stock_required` to the
executable `experiment_design_pairwise_v1` prefix. It extends the reusable Qt
editor driver with typed ordered optimization attempts, an expected warning
boundary, the existing regeneration action, and exact no-mutation evidence.
Cases 1-2 keep their legacy single-generation action sequence.

The two-stock call path is:

```text
matrix selector -> fresh child -> experiment_design journey
-> typed case -> normal Qt editor controls
-> Optimize and Generate with Allow Two Stock Solutions clear
-> production Optimization failed warning/status
-> unchanged execution-plan/progress/key/concentration fingerprints
-> Qt checkbox enabled -> regenerate through the normal control
-> exact 5 mM + 10 mM design -> Finalize Design
-> MainWindow -> application Model authoritative persistence
-> Qt directory reload -> exact reconstructed assignments, runtime inactive
```

Controller is observed idle after reload but does not mediate editor
optimization. No comms, firmware, protocol, hardware, motion, pressure,
printing, timing, or physical-calibration path is reached.

## Authorized correction prerequisite

The first development attempt exposed the production optimizer defect retained
in the Slice 10.3 implementation plan. The user explicitly authorized the
separate correction, committed as `6c05b80`. That commit passed 41 optimizer
tests, 139 related regression tests, and the complete default Python suite:

```text
4137 passed, 80 skipped, 389 warnings in 249.09s
```

Slice 10.3 changed no further production code.

## Evidence-led oracle correction

The typed case originally expected the Model's raw phrase `Enable two-stock
mode`. The real Qt warning/status surface deliberately replaces that raw
reason with a more precise issue summary. The independent oracle now requires
both visible facts:

- `requires up to 20 nL per reaction`;
- `printed-volume budget is 10 nL`.

This strengthens the visible UI assertion and does not derive expected values
from the optimizer. The affected Milestone 10 identities were transparently
re-frozen:

- `two_stock_required` case:
  `b9bd401c9f223c1576bc98938c75b2a7401958dad2048a2d048f95d4fbda2fff`;
- full planned nine-case catalog:
  `cb283c2b8519dfe9dc806a8a0205fe9eb99bda976da728d4de6d6ef9c0ad35dc`;
- test-local nine-case definition:
  `47c5b7962f1788fdd2095ea96a1de9120bb1c17305b1a526244068c23a47629b`;
- test-local nine-case plan:
  `ea3fe6b3d508ca05fd4d95eab4f004a6679de331690ed621e8352a35858dae72`;
- registered four-case prefix:
  `1d4c866eebfff7803d39b7390cff053f8b741aec22f7b30f2bc0801712727ea1`;
- selected control dry plan, seed 7, timeout 12, execution unauthorized:
  `6ec75e4f04d495bf7fdf78245a936f3e71462f61a2fe59e9e1c4c5a63c694288`.

All Milestone 7-9 identities, report-v1, matrix plan/aggregate v1, replay
format, and the reference fixture SHA remain unchanged.

## Exact results

`one_stock_feasible` authoritatively contains
`Feasibility A_5.00_mM` and the required Water fill count. The two-stock case
first remains dirty and unfinalized after the expected warning; its plan,
progress, key, and concentration artifact fingerprints are identical before
and after rejection. The successful second attempt authoritatively contains
only `Feasibility A_5.00_mM` and `Feasibility A_10.00_mM`, with one droplet in
`A1` and `A2` respectively. The editor's zero-use Water preview row is not an
authoritative stock or count.

Both cases finish at plan revision 1 with zero progress, no resume file,
`ready_to_start`, byte-identical reload, exact key/concentration rows, exact
assignments `A1 -> R1` and `A2 -> R2`, idle Controller state, and inactive
authoritative runtime.

## Validation

Focused unit, contract, optimizer, and UI-input tests:

```text
261 passed in 11.70s
```

Selected fresh-process system cases:

```text
2 passed, 2 deselected in 8.66s
```

Legacy composed editor compatibility:

```text
1 passed, 10 existing Qt deprecation warnings in 3.56s
```

The retained offscreen case runs and their exact replays each passed 6/6
assertions. The visible `two_stock_required` representative and its exact
visible replay also passed 6/6. Manual inspection of the visible generated and
prepared-reload screenshots confirmed the checked two-stock control, 10/5 mM
rows, zero-use Water preview, two reactions, Finalize Design control, and
editable untouched-PREPARED reload. Report inspection confirmed all hardware
interfaces false and no reload path changes.

Retained evidence:

| Run | Report SHA-256 | Evidence manifest SHA-256 |
|---|---|---|
| one-stock offscreen | `1fca0461ab5944b410604ea66a20bc0fdcb864d539c62fa31e6f9e9850c66bee` | `449804ace32c0d894dbcedf27bf72a74510251310cd550740b41f05f769ea97c` |
| one-stock replay | `62b38f3ee0588fb773ec43e1f54b44fe8869ca99a08e6db9e02ca49d43cb0dd1` | `1635f884f8466bca5c40ef34f0766091440c06154ab92cbfb8c5b7e8bba6211b` |
| two-stock offscreen | `ca7550079d306bed06c8217a4328d52798192e4552d662b53bfb9630dddd8c50` | `2acbe71d5e739f4f43d9c79782656c7d6bef19ce7673704cfab9051f701b57d4` |
| two-stock replay | `f7bbff80717c8fb97b6dd7861618690b18b4c8599b777fbd5c28e8c7dacc9c8e` | `d8184f5f4d5a5f534d7013022e8d7ebd2c92a1522ec27027a6c6ccc09233d1f2` |
| two-stock visible | `ae84e2e967fc50c97cfa12cf769ddeb6896b20b7cd36f3584853223874899e27` | `8f251b9331fd60878d16ffe625cc38587f3c65fa6b5b03040afc101bdc154fd0` |
| two-stock visible replay | `066f6219e552630908c0b2a487ba04b68009f8cfcc73cc9d13583002ddf44e89` | `4b5f12909fc0df275d247c48b413088dcf8bc591903bd13176ffed6b30a74f16` |

Evidence root: `verification_reports/m10-s3/`.

## Risks, rollback, and next action

Risks remain limited to modal timing and future UI-copy drift. The driver
polls only for the explicitly named expected warning and fails closed on any
other modal, mismatched visible quantity, dirty/finalization state, artifact
mutation, stock/count mismatch, or reload change. The full four-case matrix
and full Python suite remain deferred to Slice 10.6; the production correction
already received its required full-suite gate.

Rollback reverts only this slice commit, restoring the two-case executable
prefix while leaving the separately authorized optimizer correction intact.
Slice 10.4 is next: add custom wells/exclusions and seed-1234 deterministic
randomization as an independent commit.
