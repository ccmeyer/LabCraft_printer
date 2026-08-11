# Milestone 13 Slice 13.1 Implementation Plan

Status: `active`

Started: 2026-08-09

## Start-boundary result

The Milestone 13 start boundary passed from a clean worktree at
`cc9656e34a5ec1644b11182a51f2ef728cc9addb`. The deterministic Milestone 9-12
direct and exact-replay checks passed, as did lifecycle and host-regression
direct/replay. The immutable
`optimizer_360_calibration_reload_execution_v1` control passed direct and
exact replay with 1,800 intents, 46,208 droplets, and three sessions. The
focused gate passed with 342 tests; the selected real-Qt baseline passed with
53 tests and 3 skips; and the exact default suite passed with 4,269 tests and
127 skips. `git diff --check` passed. The separately scoped 384x10 host-stress
aggregate was not run and is not part of this gate.

The retained entrance evidence is under
`verification_reports/milestone_13_start/`. Its presence is qualification
evidence, not tracked source, and no historical child evidence may be mutated.

## Slice objective

Freeze the versioned Milestone 13 state model, semantic operation catalog,
oracle-admission ledger, frozen and diagnostic seed tiers, numeric budgets,
normalized sequences, and hashes. Add read-only multi-campaign discovery and
dry-run planning while preserving the Milestone 8 campaign byte-for-byte at
its existing public API. Milestone 13 execution remains disabled in this
slice.

## Call paths

- list: CLI `--list explorations` -> exploration campaign registry -> frozen
  Milestone 8 descriptor plus Milestone 13 descriptor -> deterministic JSON;
- dry run: CLI `--exploration design_calibration_lifecycle_v1 --dry-run` ->
  campaign resolver -> state/operation/oracle/budget validation -> normalized
  frozen sequences -> canonical sequence and campaign hashes -> plan schema v2
  with `execution_authorized=false`;
- selected dry run: CLI `--sequence` -> durable sequence identity lookup ->
  exact frozen seed -> canonical original normalized sequence; and
- execution attempt: CLI exploration selection -> campaign metadata -> explicit
  Slice 13.1 execution-disabled guard -> fail closed before importing Qt,
  constructing Controller/Model, opening authoritative files, or reaching the
  simulator/dispatch boundary.

There is intentionally no UI -> Controller -> Model -> persistence -> machine
call path in Slice 13.1. Those real-operator paths are admitted only when the
corresponding execution slices attach the already-qualified deterministic
oracles.

## Scope and exclusions

In scope are immutable pure-data contracts, canonical validation/hash logic,
campaign discovery, v2 dry-run planning, explicit diagnostic-seed planning,
strict budget validation, and focused unit/CLI tests. Out of scope are Qt
actions, generated fixtures, child execution, aggregate/replay evidence,
semantic coverage output, reducers, simulator construction, dispatch,
production MVC changes, authoritative persistence, firmware, protocol,
physical calibration, motion, pressure, refill/resume, `pi_stress`, and the
known 384x10 issue.

## Implementation plan

1. Record the passed start boundary and mark only Milestone 13 Slice 13.1
   active.
2. Add the immutable versioned state, operation, oracle, seed-tier, identity,
   and budget contracts in a separate Milestone 13 module.
3. Generate the six reviewed frozen normalized sequences deterministically,
   validate continuity/admission/budgets, and freeze canonical hashes.
4. Extend campaign discovery and dry-run selection additively without changing
   Milestone 8 normalized plans, hashes, fixtures, execution, or CLI behavior.
5. Add focused fail-closed tests for hashes, state continuity, oracle
   admission, seed isolation, caps, and execution disablement.
6. Run focused Slice 13.1 tests, both campaign dry runs, catalog listing, the
   Milestone 8 compatibility checks, and `git diff --check`; then write the
   Slice 13.1 completion record.

## Files expected to change

- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- `docs/sil_interactive_simulation_milestone_13_execution_plan.md`
- this implementation plan and the Slice 13.1 completion record
- new `tools/virtual_workflows/exploration_m13.py`
- minimally `tools/virtual_workflows/exploration.py`
- minimally `tools/run_virtual_workflow.py`
- focused exploration and CLI tests

`tools/virtual_workflows/exploration_runner.py`, production MVC files, the
simulator, manifest, report/replay/coverage schemas, and all Milestone 8-12
fixtures remain unchanged in this slice.

## Acceptance criteria

- all six frozen sequences and their campaign are canonical and hash-stable;
- every operation names an existing deterministic oracle and an exact expected
  outcome; no unadmitted or weaker generated assertion is accepted;
- all state transitions are continuous, identity-keyed, and within every
  numeric budget;
- diagnostic seeds are explicit, deterministic, separately labeled, and do
  not alter the frozen catalog or gate;
- Milestone 13 execution fails closed before any Qt or dispatch path;
- the Milestone 8 seeds, normalized sequences, hashes, dry run, execution
  selector, and public imports remain compatible; and
- focused tests and `git diff --check` pass.

## Risks, dependencies, and rollback

The primary risks are accidental Milestone 8 hash drift, admitting a semantic
operation without its deterministic oracle, incidental UI position state,
and allowing diagnostic input to mutate the release gate. Tests must compare
the frozen Milestone 8 contract, reject unknown state/operation/oracle values,
and prove frozen catalog independence from diagnostic selection.

This slice depends only on the passed start boundary and committed Milestone
9-12/11A contracts. Rollback removes the new Milestone 13 module, selector,
tests, and documentation entries while leaving the Milestone 8 implementation
and every deterministic baseline untouched. No data cleanup or destructive
operation is required.
