# Milestone 10 Slice 10.1 Implementation Plan

Status: implementation in progress (2026-08-08)

## Objective

Define the complete nine-case experiment-design catalog, independent literal
oracles, named pairwise audit, and deterministic hashing contracts. Exercise
the cases through a test-local generic matrix definition only. Do not register
`experiment_design_pairwise_v1`, launch Qt, change a journey, or modify
production MVC behavior.

## Call path

```text
ExperimentDesignCase and nested frozen contracts
-> deterministic normalized JSON
-> independent case and cross-case validation
-> named required-pair audit
-> test-local MatrixDefinition / MatrixRegistry
-> resolve_plan() and SHA-256 validation
-> no application construction
```

## Files

Add:

- `tools/virtual_workflows/experiment_design_cases.py`
- `tests/test_virtual_workflow_experiment_design_cases.py`
- `docs/sil_interactive_simulation_milestone_10_slice_1_implementation_plan.md`
- `docs/sil_interactive_simulation_milestone_10_slice_1_completion_record.md`

Update:

- `tests/test_virtual_workflow_matrices.py`
- `tests/test_virtual_workflow_matrix_runner.py`
- only the Milestone 10 Current Next Action in
  `docs/sil_interactive_simulation_and_composable_workflows_plan.md`

## Implementation steps

1. Add strict frozen experiment, reagent, stock/count, reaction, assignment,
   capacity, warning, and case contracts.
2. Encode the nine approved cases with literal expected values and no imports
   from production Model/View algorithms.
3. Validate identifiers, decimals, cardinalities, stock/well membership,
   terminal-specific fields, and seed comparison invariants.
4. Add recognized coverage tags, named required pairs, and a complete audit.
5. Add a SHA-verified in-memory transformation of the unchanged editor
   reference fixture for future slices.
6. Add focused oracle, drift, hashing, test-local selection, and import-
   boundary tests while freezing existing Milestone 7-9 identities.
7. Run the targeted tests, inspect the diff, and run `git diff --check`.
8. Record exact results, advance to Slice 10.2, and commit as
   `test: define experiment design matrix contracts`.

## Tests and evidence

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_experiment_design_cases.py `
  tests\test_virtual_workflow_matrices.py `
  tests\test_virtual_workflow_matrix_runner.py
```

Retain the nine normalized case hashes, full planned-catalog hash, pairwise
audit, unchanged existing catalog/plan hashes, and unchanged production matrix
listing in the completion record. No SIL report is expected.

## Risks and rollback

The risks are coupling expected truth to production algorithms, accepting an
ambiguous case, or publishing an unexecutable selector. Fail closed on all
three. Rollback removes the new case module/tests and this slice's records;
no application data, schema, or retained evidence migration is involved.
