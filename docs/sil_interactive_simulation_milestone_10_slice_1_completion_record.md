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
  `cb283c2b8519dfe9dc806a8a0205fe9eb99bda976da728d4de6d6ef9c0ad35dc`
- test-local `MatrixDefinition` catalog SHA-256:
  `47c5b7962f1788fdd2095ea96a1de9120bb1c17305b1a526244068c23a47629b`
- full test-local plan SHA-256 at seed 9, timeout 12, execution unauthorized:
  `ea3fe6b3d508ca05fd4d95eab4f004a6679de331690ed621e8352a35858dae72`
- pairwise audit: 9 cases, 14 required pairs, 0 uncovered

Case SHA-256 values:

| Case | SHA-256 |
|---|---|
| `single_reagent_control` | `b0deaaf5af7b4391d3cc92de2b03b7729ba3ea6abf7b22d122f78b9ef347c033` |
| `multi_reagent_seed_4321` | `5d2e7dff0ea9c2e0bcd1e3b218b39280aca57b745834024226fece850f110f51` |
| `one_stock_feasible` | `30ee17fcd869f6c3989d39b50d7e484ed8de233e5af6fc1f2c47cfac40230e17` |
| `two_stock_required` | `b9bd401c9f223c1576bc98938c75b2a7401958dad2048a2d048f95d4fbda2fff` |
| `custom_wells_with_exclusions` | `ace89896cfdfdf63ecb9c5ae567ef29c7926b6e5211ed15c168fdeee0b5eef6e` |
| `multi_reagent_seed_1234` | `a30c30ed1f5b9c40a64ebeed9eec4ed062532a1e9627e69e60d1711860ce9df4` |
| `exact_custom_capacity` | `f8f29163ef968a7a0ba0e6ba2483d96104dab1eac87db53e6f932ef10e9368bf` |
| `capacity_plus_one_rejected` | `16af7c74a8e4d5840e24317b20996a1bc511a1d26641e5e4a5dce10b31fca21a` |
| `fixed_stock_exceeds_max_rejected` | `c386c67a6d5da03ff4a376f5631189881fb16b9d49f758a5a94a42bca10bcca9` |

Slice 10.2 execution corrected the `multi_reagent_seed_4321` literal Water
counts before that case was accepted: the editor input specifies a 9 nL fill
droplet, so the eight expected counts are the independently calculated
ceilings of each remaining printed volume divided by 9 nL. The prior literals
had inadvertently used 10 nL. The case, planned-catalog, test-local definition,
and test-local plan hashes above are the corrected frozen identities; no
production optimizer or generated output was used as the expected-value
source.

Slice 10.3 corrected a second planning-only oracle mismatch before accepting
the case. The Model's raw reason mentions enabling two-stock mode, but the
real Qt warning/status surface instead reports the independently exact 20 nL
requirement and 10 nL budget. The `two_stock_required`, planned-catalog,
test-local definition, and test-local plan hashes above freeze those stronger
visible fragments. No production message or behavior was changed.

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
exact saved-plan assignment reconstruction, and the generic fresh-process
matrix path.
