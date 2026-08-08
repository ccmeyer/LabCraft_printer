# Milestone 11 Slice 11.1 Completion Record

Status: complete (2026-08-08)

## Scope completed

Slice 11.1 defines the singleton
`randomized_calibration_reload_execution_v1` contract and tracked literal
fixture. The frozen case joins the already-qualified Milestone 10
`multi_reagent_seed_4321` source identity to explicit Milestone 11
calibration/head, session/revision/progress-reference, keyed stock/well count,
execution-pass, timeout, screenshot, and terminal-completion truth.

The literal mapping remains `A1..A8 -> R8,R6,R3,R2,R7,R4,R1,R5`. Design A is
the sole reagent receiving the Milestone 9 boundary-crossing 1800 us / 18 nL
calibration. Water and Design B retain their explicit 1300 us / 9 nL
calibrations after the clean-session boundary. Design B's exact per-well map
is frozen unchanged at `3,3,1,3,1,3,1,1`. All count validation is keyed by
`(stock_id, well_id)`; no list-position lookup is used.

No scenario, matrix, capability, suite, runner, journey phase, report, replay,
or screenshot was registered. No Qt application or SIL child process ran, and
no production MVC, persisted-data schema, firmware, protocol, motion,
pressure, or hardware behavior changed.

## Files changed

- `tools/virtual_workflows/joined_interaction_cases.py`
- `tools/virtual_workflows/fixtures/randomized_calibration_reload_execution_v1.json`
- `tests/test_virtual_workflow_joined_interaction_cases.py`
- `tests/test_virtual_workflow_contract_freeze.py`
- `docs/sil_interactive_simulation_milestone_11_slice_1_implementation_plan.md`
- `docs/sil_interactive_simulation_milestone_11_slice_1_completion_record.md`
- only the Milestone 11 current-action text in
  `docs/sil_interactive_simulation_and_composable_workflows_plan.md`

## Frozen identities and evidence

New identities:

- normalized joined-case SHA-256:
  `95abfc7be2fcb38744d374be8d7af7060fbe5636d7577b3417a7d6082843d992`;
- tracked fixture byte SHA-256:
  `f27c0331a367a1a104d11582348f602aa8868c904d8d3d22193bceefd6dc45cc`;
- normalized keyed count-oracle SHA-256:
  `930a85b245db04e18f4ed9963070baddf18740d39426a33475116ef33b3eb84e`.

The source compatibility audit remains exact:

- Milestone 10 source case:
  `5d2e7dff0ea9c2e0bcd1e3b218b39280aca57b745834024226fece850f110f51`;
- Milestone 10 registered catalog:
  `acbd4d82f8c7ea6dd842c4ad88bd472c4b50f3a73822dc8c34cfded0dec6f59f`;
- Milestone 10 planned catalog:
  `15ec261cf19bec2f2758d76f8c8102d0d246eef02ff165a4bdb104b1a9e8dfcd`;
- reaction multiset:
  `b189fe1ed4b975953600c7d299fd320be366eda827ceb39f28cf3a3bbc22b696`;
- seed-4321 assignment:
  `e264b345bddb83c2aeb12bf6421d83a81d21c8b9f31ff6698780164a1bee82ef`;
- editor reference fixture:
  `fc2bdf34fa5a7d8a9e851ace7a099aa8e05c61c2d0cd075b620d69937f8bfc45`;
- Milestone 9 requantization catalog:
  `d826a9e54c2e6190acfd5afdb0b2475de2be62557647aafa378890ca826c55af`;
- Milestone 9 mixed-mode catalog:
  `d2439c2e47cb9825ad5a5024e014fd4429ff6b28dcafa54809c92fa674cff884`.

The terminal oracle is exactly 24 durable stock/well intents and 80 commanded
and persisted droplets: Design A `8/8`, Design B `8/16`, and Water `8/56`.
It spans three genuinely distinct application sessions in the future journey.
The current registry still excludes the incomplete scenario.

## Validation

Focused contract and compatibility command:

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

Result: `163 passed` with the fixed hash and mutation assertions enabled.
Mutations cover seed/mapping/source-hash drift, duplicate keyed counts, changed
Design B truth, revision gaps, wrong head joins, pass reordering, action-cap
drift, and terminal 24/80 drift.

Additional evidence:

- direct source compatibility audit: complete;
- joined oracle production-import boundary: passed;
- runtime registry omission: passed;
- accepted SIL report/replay/screenshots: deliberately absent and deferred;
- `git diff --check`: passed at completion preparation and rerun before commit.

## Compatibility, risks, and rollback

All Milestone 9/10 hashes, schemas, selectors, runners, reports, replay
behavior, authoritative reload contracts, and negative no-mutation evidence
remain unchanged. The existing count code is not imported into the literal
oracle and remains reserved for normalizing future observations.

The remaining risk is disagreement between literal joined truth and a future
real-Qt observation. Slice 11.2 must stop on such a mismatch; it must not
weaken or regenerate the oracle. A production defect requires its own reviewed
correction plan.

Rollback is the independent Slice 11.1 commit. Reverting it removes only the
new contract, fixture, tests, and slice documentation and restores the prior
current-action text. No application data or retained SIL evidence needs
migration.

## Exit and next action

Slice 11.1 exit criteria are satisfied once the final focused run,
`git diff --check`, and commit complete cleanly. Slice 11.2 is next: compose
real-editor randomized finalization through revision 1, Design A's real
boundary-crossing calibration through revision 3, and the calibrated
zero-progress checkpoint without registering or running the full scenario.
