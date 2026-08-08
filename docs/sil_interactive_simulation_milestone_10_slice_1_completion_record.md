# Milestone 10 Slice 10.1 Completion Record

Status: complete (2026-08-08)

## Scope completed

Slice 10.1 defines the full nine-case experiment-design truth before any case
is made executable. The new frozen contracts cover editor inputs,
optimization attempts, stocks, reactions, stock/well droplet counts, well
assignments, terminal warnings, capacity boundaries, and no-authoritative-
mutation expectations. Expected values are literal data and the oracle module
imports no production Model, View, optimizer, generator, assignment, or
finalization implementation.

The named audit covers all 14 required interactions with the approved nine
curated cases. A SHA-verified builder derives future case fixtures in memory
from the unchanged editor reference fixture. Generic selection and runner
validation use a test-local `MatrixDefinition`; the production matrix registry
and command-line listing remain unchanged.

No Qt application, SIL journey, fresh child process, authoritative experiment
file, production MVC code, firmware, protocol, motion, pressure, or hardware
behavior was exercised or changed in this slice.

## Files changed

- `tools/virtual_workflows/experiment_design_cases.py`
- `tests/test_virtual_workflow_experiment_design_cases.py`
- `tests/test_virtual_workflow_matrices.py`
- `tests/test_virtual_workflow_matrix_runner.py`
- `docs/sil_interactive_simulation_milestone_10_slice_1_implementation_plan.md`
- `docs/sil_interactive_simulation_milestone_10_slice_1_completion_record.md`
- only Current Next Action text in
  `docs/sil_interactive_simulation_and_composable_workflows_plan.md`

## Frozen identities and evidence

Reference editor fixture:

- path: `tools/virtual_workflows/fixtures/experiment_editor_create_finalize_v1.json`
- SHA-256: `fc2bdf34fa5a7d8a9e851ace7a099aa8e05c61c2d0cd075b620d69937f8bfc45`

Planned experiment-design identities:

- planned catalog SHA-256:
  `81c68119944c125f796f59d4f9604f4a450c90709f25ba9199abd1efe08901e1`
- test-local `MatrixDefinition` catalog SHA-256:
  `cfe4f895bfd4550a121d9076df4962a24f60a786768d534587177e2900607aae`
- full test-local plan SHA-256 at seed 9, timeout 12, execution unauthorized:
  `71a3dc1e7ff9d8c9f87a503e3a309646a8fb4269bfc09f877aa11054fbeef21b`
- pairwise audit: 9 cases, 14 required pairs, 0 uncovered

Case SHA-256 values:

| Case | SHA-256 |
|---|---|
| `single_reagent_control` | `b0deaaf5af7b4391d3cc92de2b03b7729ba3ea6abf7b22d122f78b9ef347c033` |
| `multi_reagent_seed_4321` | `94c63041bb70d5a739f252d824d666fd973aa69e7749976ca8f07f38c2b1ac0e` |
| `one_stock_feasible` | `30ee17fcd869f6c3989d39b50d7e484ed8de233e5af6fc1f2c47cfac40230e17` |
| `two_stock_required` | `aa4d85a9f29df49d8c99f1b6f50fd80b59e79101c053f8d93a8ec332a4557350` |
| `custom_wells_with_exclusions` | `ace89896cfdfdf63ecb9c5ae567ef29c7926b6e5211ed15c168fdeee0b5eef6e` |
| `multi_reagent_seed_1234` | `a30c30ed1f5b9c40a64ebeed9eec4ed062532a1e9627e69e60d1711860ce9df4` |
| `exact_custom_capacity` | `f8f29163ef968a7a0ba0e6ba2483d96104dab1eac87db53e6f932ef10e9368bf` |
| `capacity_plus_one_rejected` | `16af7c74a8e4d5840e24317b20996a1bc511a1d26641e5e4a5dce10b31fca21a` |
| `fixed_stock_exceeds_max_rejected` | `c386c67a6d5da03ff4a376f5631189881fb16b9d49f758a5a94a42bca10bcca9` |

Existing production matrix identities remain:

- `calibration_requantization_v1`:
  `d826a9e54c2e6190acfd5afdb0b2475de2be62557647aafa378890ca826c55af`
- `mixed_mode_calibration_v1`:
  `d2439c2e47cb9825ad5a5024e014fd4429ff6b28dcafa54809c92fa674cff884`
- report and matrix plan/aggregate schemas remain version 1

The production `--list matrices` output contains only those two existing
matrices. `experiment_design_pairwise_v1` is intentionally not registered
until Slice 10.2 has executable positive cases.

## Validation

Focused contract command:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_experiment_design_cases.py `
  tests\test_virtual_workflow_matrices.py `
  tests\test_virtual_workflow_matrix_runner.py
```

Result: `35 passed in 0.34s` with all fixed case, catalog, definition, and plan
hash assertions enabled.

Additional checks:

- module compile/import: passed;
- catalog import-time validation: passed;
- `--list matrices`: passed and unchanged at two production matrices;
- `git diff --check`: passed before completion-record updates and is rerun at
  commit preparation;
- SIL matrices and the full Python suite: intentionally deferred.

## Risks and rollback

The primary risk is a literal oracle value that differs from the production
editor behavior. Later executable slices must stop on such a mismatch and
open a separate reviewed defect-correction plan; they must not derive or
weaken expected truth. Registering a case before its journey exists is
prevented by the explicit production-listing test.

Rollback is the independent Slice 10.1 commit. Reverting it removes only the
new catalog/contracts/tests and planning records. It does not migrate data,
change a schema, alter application behavior, or remove retained SIL evidence.

## Exit and next action

Slice 10.1 exit criteria are satisfied when final focused tests and
`git diff --check` pass and the slice commit is clean. Slice 10.2 is next:
make only `single_reagent_control` and `multi_reagent_seed_4321` executable
through reusable normal Qt inputs, finalization, authoritative folder reload,
Load Execution reconstruction, and the generic fresh-process matrix path.
