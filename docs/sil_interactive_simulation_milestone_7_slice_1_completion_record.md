# Milestone 7 Slice 1 Completion Record

Status: `complete`

Date: 2026-08-06

Baseline: `f9d13b78002ea8aa3400953ab0f4b0ee8c1fb21f`

## Delivered Scope

Only `experiment_editor_create_finalize_v1` moved from the legacy editor
runner to the shared composed automation harness. The two other editor
lifecycle scenarios remain on `editor_scenarios.py`.

The composed journey now:

- constructs the hardware-isolated real application through
  `SimulationSession`;
- routes all five create/finalize editor stages through harness-owned bounded
  QTest action boundaries;
- validates the authoritative revision-1 prepared bundle, progress, keys,
  assignments, and absent calibration/printing history without mutation;
- reopens the retained experiment through the normal **Experiment Editor →
  Load Design…** controls and a non-native Qt folder dialog;
- verifies the same plan remains `PREPARED` and `ready_to_start`, with inactive
  runtime and no resume sidecar;
- retains action/assertion ledgers, five screenshots, snapshots, hashes, seed,
  replay command, failure evidence, and clean teardown evidence.

No production MVC, fixture, firmware, protocol, Pi, hardware, performance,
fault-injection, or other workflow implementation changed.

## Call Path

```text
tools/run_virtual_workflow.py
  -> registry composed_journey dispatch
  -> run_editor_create_finalize_journey()
  -> AutomationHarness / SimulationSession
  -> ExperimentEditorDriver / bounded QTest editor controls
  -> normal MainWindow finalization and authoritative writers
  -> read-only prepared assertions
  -> ExperimentLoaderDriver / normal Load Design… Qt folder dialog
  -> normal ExperimentModel.load_experiment() UI handler
  -> read-only reload assertions / report / teardown
```

The legacy direct runner remains callable only as a parity oracle and as shared
support for the two unmigrated editor scenarios.

## Validation

Targeted shared contract/unit gate:

```text
144 passed, 130 warnings
```

Targeted composed, parity-oracle, and adjacent editor lifecycle gate:

```text
13 passed, 100 warnings
```

Milestone 6 composed-smoke regression:

```text
2 passed, 14 warnings
```

The warnings are existing Qt deprecation warnings. The full Python suite was
not run, by the approved Milestone 7 per-slice policy. It remains deferred to
the final Milestone 7 validation.

The visible Windows run and its exact emitted replay command both passed with
8/8 assertions, five screenshots, inactive runtime, absent resume sidecar,
healthy retained evidence, and no remaining session lock:

```text
verification_reports/milestone7-slice1-visible/
  experiment_editor_create_finalize_v1/
    20260806T234759601204Z_composed/report.json
    20260806T234806885870Z_composed/report.json
```

Retained isolated session roots:

```text
C:\Users\conar\AppData\Local\Temp\LabCraft\SIL\composed-sessions\20260806T234759602586Z-60b53859-47a
C:\Users\conar\AppData\Local\Temp\LabCraft\SIL\composed-sessions\20260806T234806886829Z-7b8412f6-dfe
```

## Parity Decision

The legacy and composed runs agree on stable scenario/workload identity,
A1/A2 order, all eight passing assertion IDs, prepared revision 1, valid
authoritative state, zero progress, key consistency, and unchanged runtime
assignments. Generated IDs, paths, timestamps, durations, and identity-bearing
hashes remain excluded.

One intentional difference is retained: the composed UI reload does not
activate the authoritative runtime merely for verification. Its report records
`activation_performed: false`, `runtime_active: false`, and
`resume_present: false`, matching the user-visible prepared-reopen contract.

The legacy report never contained a fixture SHA-256 field. Parity therefore
checks the composed report hash directly against the tracked fixture bytes.

## Risk And Rollback

Risk is limited to SIL automation dispatch and evidence. No physical command,
device protocol, production application path, or authoritative schema changed.
The normal UI loader fails closed on an unexpected modal, escaped path, changed
plan identity, non-prepared state, active runtime, or ambiguous cleanup.

Rollback is to restore only `experiment_editor_create_finalize_v1` to the
`experiment_editor` registry family and revert its manifest mapping. The
Milestone 6 smoke harness and the two legacy editor scenarios remain intact;
no retained experiment or schema migration is required.

## Next Step

Create and approve a concrete plan for the next Milestone 7 slice. Continue
targeted tests for each slice and reserve the full suite for the final
Milestone 7 validation.
