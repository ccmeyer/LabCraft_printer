# Milestone 10 Slice 10.2 Completion Record

Status: complete (2026-08-08)

Commit boundary: `test: add control and multi-reagent design SIL cases`

## Delivered scope

Slice 10.2 registers only `single_reagent_control` and
`multi_reagent_seed_4321` in `experiment_design_pairwise_v1`. The generic
fresh-process matrix runner now composes the real experiment editor journey
with reusable typed case inputs, normal Qt controls, authoritative
finalization, Qt directory reload, exact catalog comparison, and exact
reconstructed-assignment comparison. It does not connect, print, calibrate,
dispatch simulator commands, or change production MVC behavior.

The implementation adds:

- reusable multiple-reagent, optional stock-bound, custom-well, and explicit
  random-seed editor inputs without changing the legacy editor action order;
- generated control/stock-table/reaction evidence;
- exact `experiment.design_case_oracle_exact` and
  `experiment.prepared_runtime_reconstructed_exact` assertions;
- additive report-v1 `matrix_case` and `experiment_design_evidence` values;
- a two-case production matrix prefix with the generic selector, plan, child
  aggregate, and replay contracts;
- fresh-process system coverage for both cases and visible retained evidence
  for the multi-reagent representative.

No production file under `FreeRTOS-interface/`, firmware file, protocol,
hardware, motion, pressure, or physical-calibration behavior changed.

## Evidence-led corrections

Two fail-closed development runs identified planning/oracle issues before the
slice was accepted:

1. The generated editor table retains a Water candidate even when it has zero
   authoritative dispenses. The authoritative plan oracle remains unchanged;
   the preview assertion now independently accounts for that UI-only row.
2. `multi_reagent_seed_4321` specifies a 9 nL Water droplet. Its eight literal
   Water counts were corrected to the independently calculated ceilings of
   remaining volume divided by 9 nL. The corrected case/catalog hashes were
   re-frozen in the Slice 10.1 record and tests.

Repository tracing also corrected an execution-plan assumption. An untouched
PREPARED bundle intentionally reloads as editable, `ready_to_start`, and
runtime-inactive; `Model.load_experiment()` nevertheless projects exact saved
stocks, reactions, printer-head identities, and well assignments in memory.
The matrix therefore proves Qt reload, byte-identical files, and exact
reconstructed assignments. It does not require `Load Execution`, which is the
existing UI contract for a locked saved execution. This preserves production
behavior and avoids an unauthorized MVC change.

The capability manifest was not changed: its validator requires every
assertion vocabulary entry to be referenced by a static registered scenario,
whereas this workload is a dynamic matrix family. The assertions are fully
frozen by the composed journey and fresh-process system test without weakening
the manifest/registry join contract.

## Frozen identities

- full planned nine-case catalog:
  `9f2745b22e8c7a1a8601a498a46471ae94fd0c81eadeb884a4c0063f42216fa7`
- `multi_reagent_seed_4321` case:
  `5d2e7dff0ea9c2e0bcd1e3b218b39280aca57b745834024226fece850f110f51`
- registered two-case prefix catalog:
  `1af94890988d17829e34d4e63fa08d679c13a9aae9090941656fb91b168b012e`
- selected control dry plan, seed 7, timeout 12, execution unauthorized:
  `1c6fee0dc79b4f375b555f4183566eed3cc081850d97f37b0621cf8c450e352f`
- unchanged editor fixture:
  `fc2bdf34fa5a7d8a9e851ace7a099aa8e05c61c2d0cd075b620d69937f8bfc45`
- unchanged Milestone 9 catalogs:
  - `calibration_requantization_v1`:
    `d826a9e54c2e6190acfd5afdb0b2475de2be62557647aafa378890ca826c55af`
  - `mixed_mode_calibration_v1`:
    `d2439c2e47cb9825ad5a5024e014fd4429ff6b28dcafa54809c92fa674cff884`

Report-v1, matrix plan/aggregate v1, generic replay formatting, existing
scenario identities, and the legacy editor direct/composed contracts remain
unchanged.

## Validation

Focused unit and contract tests:

```text
182 passed in 7.49s
```

Command: the exact eleven-file focused pytest command in the Slice 10.2
implementation plan.

Selected fresh-process system tests:

```text
2 passed in 8.63s
```

Command:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_experiment_design_matrix.py `
  -k "single_reagent_control or multi_reagent_seed_4321"
```

Selected offscreen CLI cases and their exact replay commands passed 6/6
assertions. The visible `multi_reagent_seed_4321` case and its exact visible
replay also passed 6/6. Visual inspection confirmed two reagent rows, targets,
fixed stocks, seed 4321, eight selected wells, the three-row generated stock
table, Finalize Design, the intentionally editable untouched-PREPARED reload,
and the retained exact reconstructed mapping. Reload evidence records no
changed authoritative path, no resume file, zero progress, inactive runtime,
and idle Controller state.

Retained representative evidence:

| Run | Report SHA-256 | Manifest SHA-256 |
|---|---|---|
| control offscreen replay, `verification_reports/m10-s2-dev/experiment_design_pairwise_v1/20260808T202155136483Z_composed` | `552d21fa9c674817e3c362a27653ff31ff23361b73407df696c2a056c185c990` | `ebc4005393b28b1e93f0d9e979089e19427b3996afd43313bfdd921a474f91ec` |
| multi-reagent offscreen, `verification_reports/m10-s2-dev/experiment_design_pairwise_v1/20260808T201823155055Z_composed` | `a4a36c84d922e4e1dc1e612eee3dbed49ebaf5fd1c9ea2d081bc763249516c09` | `3899518bd5be72a3945fb97c2a54825e00fc67d43ac05a0c8f0f5155a970cf68` |
| multi-reagent visible, `verification_reports/m10-s2-visible/experiment_design_pairwise_v1/20260808T202203378230Z_composed` | `74c479425af45357c248db92b0868e3527ff46c985b95e89dbba6f9bef22ad6f` | `7f4c320f06a042def23763189b564b5f8567c79fe3575b151d5f9ce214b72e1f` |
| multi-reagent visible replay, `verification_reports/m10-s2-visible/experiment_design_pairwise_v1/20260808T202212489254Z_composed` | `e99fc838254fd63939b57a65a7100b1a3a2981c2dbbcd98691bbfd3be0709f72` | `1ef6b9d4e3d89c75237c97ae30ac165a93d0905326ac933b53229e05f0f4e2eb` |

The complete matrix, broader lifecycle/host regressions, and full default
Python suite remain intentionally deferred to Slice 10.6.

## Risks, rollback, and next action

Remaining risk is limited to the seven not-yet-executable catalog cases and
their additional UI boundaries. Runtime reconstruction evidence is explicitly
an inactive saved-plan projection, not permission to print. Generated IDs,
timestamps, paths, and identity-bearing artifact hashes remain replay-variant.

Rollback is the independent Slice 10.2 commit. It removes the new matrix
journey family, two-case registry prefix, additive harness/report contracts,
and focused tests while preserving Slice 10.1 and all production MVC code.

Slice 10.3 is next: append only `one_stock_feasible` and
`two_stock_required`, including the normal-UI one-stock rejection followed by
two-stock success, then prove exact formulation, count, reload, and
reconstructed-assignment evidence.
