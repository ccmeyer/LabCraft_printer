# Milestone 12 Slice 12.4 Implementation Plan

Status: complete (2026-08-09)

## Objective and exclusions

Qualify the nine `authoritative_persistence_safeguards_v1` classifications by
loading one-fault, test-owned authoritative bundle copies through the real Qt
experiment-folder action. Preserve pristine sources byte-for-byte, mutate only
before application launch, and prove inactive locked state and zero writes or
dispatch after launch. Do not repair or activate a rejected bundle, touch user
or historical experiment data, alter production persistence policy, or touch
firmware, protocol, physical behavior, refill, optimizer-360, or Milestone 13.

## Call path and evidence boundary

```text
production serializers -> pristine compact authoritative bundle
-> contained case copy -> one allowlisted prelaunch fault + manifest
-> fresh application -> Experiment Editor / Select Experiment Folder
-> ExperimentModel.load_experiment() -> inspect_authoritative_execution()
-> exact issue/eligibility -> locked inactive UI / activation evidence
-> shared mutated-baseline no-mutation/no-dispatch oracle
```

The source and destination roots, rich inventories, original/mutated hashes,
operation, exact target, and prelaunch phase are retained. The before snapshot
is captured only after the mutation and application launch, immediately before
the folder-load action; post-action equality therefore cannot mistake the
intentional prelaunch fault for product mutation.

## Files to change

- add `tools/virtual_workflows/persistence_safeguards.py`;
- add
  `tools/virtual_workflows/fixtures/authoritative_persistence_safeguards_v1.json`;
- narrowly update `tools/virtual_workflows/safeguards.py`, `actions.py`,
  `journeys.py`, `matrices.py`, and the capability manifest;
- add focused unit and SIL lifecycle system tests and update the existing
  action/journey/matrix/manifest tests only where registration requires it;
- this plan, its completion record, the Milestone 12 execution plan, and the
  authoritative current-slice text.

No production MVC or persistence source is planned to change. A production
fail-open result is a separate reviewed defect and remains a milestone blocker.

## Steps

1. Freeze the literal ordered catalog and expected classifications/messages.
2. Build pristine prepared/progressed/calibrated bundles with production
   serializers under a unique report-owned prelaunch root.
3. Copy once, resolve and apply exactly one allowlisted fault, verify
   containment and original preservation, and write the fault manifest.
4. Drive the real editor folder load and locked activation state with QTest.
5. Capture issue, eligibility, UI, persistence, lifecycle, and dispatch evidence
   and evaluate the shared oracle.
6. Register the Windows-SIL matrix and reusable manifest actions.
7. Add contract, fault-builder, escape-defense, journey/report, and real-load
   tests.
8. Qualify all fresh children, exact replay, three visible direct/replays,
   adjacent persistence regressions, and `git diff --check`.

## Acceptance, risk, and rollback

Each case must yield its literal status or fatal issue, with activation false,
the editor locked/inactive, no repair/checkpoint/export/audit write, and no
intent, command, completion, or drop. Pristine source inventory must remain
identical and the mutated copy must differ in exactly the declared target.
Fault code must reject path traversal, symlink escape, non-report roots,
pre-existing destinations, missing sources, and multiple mutations.

Risks are corrupting the wrong root, changing multiple invariants, producing a
syntax error instead of the intended semantic fault, and treating prelaunch
mutation as rejection mutation. Absolute-root containment, parse-after-write,
inventory deltas, and the post-fault baseline address them. Rollback removes
only the new catalog, test-owned builder, workflow registrations, tests, and
slice docs. Retained copies may be removed only by a separately validated
operation within their report root; user data and prior reports remain
untouched.
