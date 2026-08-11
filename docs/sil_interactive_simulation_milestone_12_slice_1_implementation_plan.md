# Milestone 12 Slice 12.1 Implementation Plan

Status: complete (2026-08-08)

## Objective and non-goals

Add strict typed safeguard contracts and one shared no-mutation/no-dispatch
oracle for all later Milestone 12 negative boundaries. This slice adds no
executable safeguard case, real-UI journey, production behavior, firmware,
protocol, hardware, refill workflow, or Milestone 13 work.

The Milestone 11A `optimizer_360_calibration_reload_execution_v1` fixture,
case, literal oracle, scenario, and frozen hashes remain read-only.

## Call path

```text
literal safeguard payload
-> strict typed contract validation
-> canonical normalized payload and SHA-256

existing directory/bundle/count/observer/UI evidence
-> deterministic SafeguardBoundarySnapshot
-> exact typed rejection comparison
-> complete before/after persistence/model/lifecycle/queue/dispatch comparison
-> report-v1-safe shared assertion evidence
```

No production UI, Controller, Model, comms, simulator, or firmware method is
invoked by this slice's contract tests.

## Files

- add `tools/virtual_workflows/safeguards.py`;
- add `tests/test_virtual_workflow_safeguards.py`;
- add this implementation plan;
- add the Slice 12.1 completion record after validation;
- update `docs/sil_interactive_simulation_milestone_12_execution_plan.md` for
  current status and the goal-authorized single final milestone commit;
- update only Milestone 12 current-action text in
  `docs/sil_interactive_simulation_and_composable_workflows_plan.md`.

## Implementation steps

1. Define strict action, expected-outcome, persistence-fault, and case types.
2. Validate durable identifiers, literal UI evidence, negative terminal state,
   zero-dispatch expectations, and isolated prelaunch fault metadata.
3. Normalize and hash cases/catalogs without production algorithm imports.
4. Define deterministic persistence, model, lifecycle, queue, dispatch, and UI
   boundary projections keyed by durable IDs.
5. Compare exact expected rejection and all immutable before/after projections.
6. Add mutation, malformed-input, containment, ordering, hash, and JSON-safety
   tests.
7. Run focused adjacent tests and `git diff --check`.
8. Record exact validation and hashes in the Slice 12.1 completion record.

## Acceptance and validation

The slice is accepted when malformed or ambiguous contracts fail closed,
canonical hashes are stable, row/list reordering cannot become identity,
contained fault specifications reject path escape or postlaunch mutation, and
the shared comparison detects every changed plan/progress/calibration file,
model/lifecycle state, queue, intent, command, completion, drop, activation, or
resume field.

Run:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_safeguards.py `
  tests\test_virtual_workflow_authoritative_evidence.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_report.py `
  tests\test_virtual_workflow_contract_freeze.py

git diff --check
```

No direct, registered, fresh-process, replay, or visible SIL run is applicable
until Slice 12.2 adds executable cases.

## Risks and rollback

The principal risks are omitted mutable state, unstable ordering, path escape,
and confusing setup mutation with rejected-action mutation. Use explicit
closed projections, canonical durable-key ordering, resolved containment, and a
baseline captured only after setup. Rollback removes the new module/tests and
Slice 12.1 documents; it does not alter production guards or historical
evidence.
