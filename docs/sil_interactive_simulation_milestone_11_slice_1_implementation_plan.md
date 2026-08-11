# Milestone 11 Slice 11.1 Implementation Plan

Status: implementation in progress (2026-08-08)

## Objective

Define the one typed `randomized_calibration_reload_execution_v1` joined-
interaction case, its tracked literal fixture, deterministic hashes, and
compatibility audit. The contract must join the qualified Milestone 10
`multi_reagent_seed_4321` design to the Milestone 9 calibration/count
semantics without importing production design, optimization, calibration, or
execution algorithms.

Do not register an executable scenario, launch Qt or SIL, add journey phases,
change production MVC behavior, alter schemas, or derive expected values with
production code.

## Exact call path

```text
tracked joined-interaction fixture
-> strict fixture loader and frozen JoinedInteractionCase contracts
-> literal source-case/hash, assignment, calibration/head, revision,
   stock/well checkpoint, pass-order, timeout, screenshot, and terminal truth
-> deterministic normalized JSON
-> joined-case, fixture-byte, and count-oracle SHA-256
-> test-local compatibility and mutation audit
-> no application construction and no runtime scenario registration
```

The future runtime path remains deliberately outside this slice:

```text
matrix/scenario selector -> fresh-process runner -> composed journey
```

## Files

Add:

- `tools/virtual_workflows/joined_interaction_cases.py`
- `tools/virtual_workflows/fixtures/randomized_calibration_reload_execution_v1.json`
- `tests/test_virtual_workflow_joined_interaction_cases.py`
- `docs/sil_interactive_simulation_milestone_11_slice_1_implementation_plan.md`
- `docs/sil_interactive_simulation_milestone_11_slice_1_completion_record.md`

Update:

- `tests/test_virtual_workflow_contract_freeze.py`
- only the Milestone 11 current-action text in
  `docs/sil_interactive_simulation_and_composable_workflows_plan.md`

## Implementation steps

1. Add strict frozen types for source identity, assignment, calibration/head
   joins, revision checkpoints, keyed stock/well counts, execution passes,
   qualification limits, screenshots, and the singleton joined case.
2. Encode the approved seed-4321 mapping and every prepared/calibrated/final
   count as literal fixture-owned values, including the exact unchanged
   Design B map and 24-intent/80-droplet terminal oracle.
3. Validate uniqueness and membership by `(stock_id, well_id)`, the one-stock
   calibrated-reagent constraint, head/calibration/plan/progress joins,
   revision chain, pass order, action/timeout policy, and screenshot set.
4. Load the tracked fixture fail-closed, require exact normalized equality to
   the typed singleton, and expose deterministic case, fixture-byte, and
   count-oracle hashes.
5. Audit the joined source identity against the qualified Milestone 10 case
   and freeze every applicable Milestone 9/10 catalog, case, assignment,
   reaction-multiset, and editor-fixture hash without changing their owners.
6. Add focused positive and mutation tests for wrong seed/mapping/hash,
   duplicate or unknown keyed counts, changed Design B truth, revision gaps,
   incorrect head joins, positional pass semantics, limit drift, and 24/80
   terminal drift; prove the runtime registry remains unchanged.
7. Run the focused non-SIL contract/count/matrix/fixture tests, inspect the
   complete diff, and run `git diff --check`.
8. Record exact hashes and results, advance the master plan to Slice 11.2, and
   commit as `test: define randomized calibration lifecycle contract`.

## Entrance prerequisites and exit criteria

Entrance requires committed Slice 11 planning, a clean worktree, the exact
Milestone 9/10 source hashes, and the qualified seed-4321 case. Exit requires
all literal truth to validate independently, all mutation tests to fail
closed, all old hashes and runtime selectors to remain exact, and the new
case/fixture/count hashes to be recorded in the completion record.

## Tests and retained evidence

Run:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_joined_interaction_cases.py `
  tests\test_virtual_workflow_experiment_design_cases.py `
  tests\test_virtual_workflow_dispense_counts.py `
  tests\test_virtual_workflow_matrices.py `
  tests\test_virtual_workflow_matrix_runner.py `
  tests\test_virtual_workflow_manifest.py `
  tests\test_virtual_workflow_contract_freeze.py
```

Retain the command/result, normalized joined payload hashes, source compatibility
audit, and proof that no selector/report/replay was introduced. An accepted SIL
report, exact replay, screenshots, fresh-process run, visible run, lifecycle
suite, host regression, and complete Python suite are deliberately deferred to
Slice 11.5.

## Compatibility contracts

Milestones 9 and 10 hashes, schemas, selectors, runners, reports, replay
behavior, authoritative reload semantics, and negative no-mutation evidence
must remain unchanged. The Milestone 9 exact-count code may normalize future
observations only; this slice's expected values remain literal and case-owned.
No existing fixture or persisted application-data format may change.

## Risks and rollback

The principal risks are silently duplicating Milestone 10 truth incorrectly,
making count assertions positional, or coupling the oracle to production
algorithms. Strict source/hash equality, unique keyed rows, explicit pass
stock IDs, and import-boundary tests fail closed against those risks.

Rollback is the single Slice 11.1 commit: remove the joined case, fixture,
tests, and slice records and restore only the master-plan current-action text.
No production behavior, application data, retained SIL evidence, or schema
migration is involved.
