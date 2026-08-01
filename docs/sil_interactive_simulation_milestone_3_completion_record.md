# SIL Interactive Simulation Milestone 3 Completion Record

Date: 2026-08-01

Parent plan: `docs/sil_interactive_simulation_and_composable_workflows_plan.md`

Implementation plan:
`docs/sil_interactive_simulation_milestone_3_implementation_plan.md`

Baseline commit: `11a9e60`

Implementation commit: not created; the reviewed Milestone 3 worktree remains
intentionally uncommitted.

Status: `complete`

## Outcome

Milestone 3 adds a pure deterministic synthetic-calibration engine under
`tools.sil`. It provides strict request/result schema-v1 types, seven frozen
profile-v1 behaviors, request-local seeded generation, canonical SHA-256
fingerprints, stable virtual timestamps, explicit application validation,
and current-compatible summary-row/calibration-step adapters.

The provider is not connected to `SimulationSession`, Qt, the calibration UI,
Model, Controller, hardware, or authoritative persistence. Presentation,
selection, and Apply remain Milestone 4A.

## Files Changed

- `tools/sil/synthetic_calibration.py`
- `tools/sil/__init__.py`
- `tests/test_sil_synthetic_calibration.py`
- `docs/sil_calibration_schema_v1.md`
- `docs/sil_interactive_simulation_milestone_3_implementation_plan.md`
- `docs/sil_interactive_simulation_milestone_3_completion_record.md`
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- `README.md`

No `FreeRTOS-interface` production file, firmware, protocol, experiment
schema, session schema, launcher, or workflow runner changed.

## Frozen Schema And Profiles

Request identity: `labcraft.sil_calibration_request`, version 1.

Result identity: `labcraft.sil_calibration_result`, version 1.

Provider identity: `milestone-3-v1`.

Profiles:

- `nominal_droplet`;
- `nominal_stream`;
- `droplet_to_stream`;
- `low_volume_boundary`;
- `high_volume_boundary`;
- `invalid_outlier`;
- `missing_measurement`.

Canonical JSON is UTF-8, sorted, compact, rejects NaN/infinity, and includes
all frozen fields. The request fingerprint covers the request. The result
fingerprint covers the result excluding only its own fingerprint field.

## Representative Evidence

A manually inspected seed-1729 nominal droplet result retained:

- request fingerprint
  `f4874082be246481c3408df14044d0d55e20e1b20da1aef85039f3cc01bac009`;
- result fingerprint
  `aa78d8dbfd52bbee63e84c894b5aaab1b0a4ea80d302ba9729c6e6839c53287b`;
- stable timestamp `2000-09-06T20:45:53Z`;
- measured/effective volume `9.749429786` nL;
- pulse width `1563` us and pressure `2.052830772` psi;
- `application_valid=true`, no validation errors, and all four fixed
  synthetic limitations.

The corresponding seed-1729 `invalid_outlier` evidence retained:

- request fingerprint
  `818a34e04c4f518c471aecc704892d7f5f80b1a56a2669fe08b7344616aa554f`;
- result fingerprint
  `499081561bae8cc79504b1e073cb12c99414e77fce660e40de46f885e222cdb5`;
- measured/effective volume `11.1` nL;
- `application_valid=false` and
  `measured_volume_outside_requested_bounds`.

Both application adapters rejected the invalid profile in focused tests. The
manual generation command wrote no files.

## Validation

Focused synthetic-calibration contract suite:

```text
33 passed in 2.17s
```

Existing calibration summary/application regression:

```text
35 passed in 16.33s
```

Python compilation:

```text
.\env\Scripts\python.exe -m py_compile tools\sil\synthetic_calibration.py
passed
```

Complete Python suite, clean terminal run:

```text
3727 passed, 38 skipped, 270 warnings in 816.24s (0:13:36)
```

The warnings are existing QtCharts deprecation warnings. No new Milestone 3
warning was emitted.

An earlier complete-suite attempt recorded one timeout in
`test_lifecycle_order_lookahead_histories_and_single_drain` after 3 seconds;
the other 3,726 tests passed. The exact test then passed in 0.26 seconds, all
14 tests in `tests/test_simulated_machine.py` passed, and the clean complete
rerun above passed. The failure was an existing simulated-command-queue timing
flake, not a synthetic-calibration call-path failure; no production or
simulator code was changed in response.

## Isolation Findings

Focused tests establish that:

- identical requests are byte-identical across instances and call order;
- a seed set varies results while preserving bounds and all request inputs;
- process-global `random` state is unchanged;
- generation creates no filesystem entry;
- the implementation imports only Python standard-library modules;
- nominal droplet and stream steps normalize as valid through the existing
  `CalibrationManager` summary contract;
- the source-row fingerprint matches the existing calibration-view helper;
- boundary profiles land exactly at 1 and 250 nL;
- invalid and missing-measurement results fail before either adapter;
- unknown/missing fields, unsupported profiles/modes, invalid bounds,
  non-finite values, and altered fingerprints fail closed.

No camera, balance, serial, Qt, Controller, Model mutation, physical machine,
hardware factory, experiment writer, or authoritative file was invoked by the
provider.

## Limitations

This milestone provides application-workflow test data only. It does not
validate cameras, optics, segmentation, physical ejection, volume accuracy,
pressure response, refuel behavior, motion or collision safety, firmware,
protocol behavior, Pi operation, or performance.

Synthetic stream adapter data marks its evidence source and includes
`synthetic_result_without_camera_evidence`; it creates no measurement rows,
image references, or raw camera file.

## Rollback

Remove the additive provider, its `tools.sil` exports, focused tests, and the
Milestone 3 documentation/status additions. No application data, retained
session evidence, firmware, protocol, release metadata, or hardware migration
is required.

## Recommended Next Step

Create and review the concrete Milestone 4A plan for safe application-owned
presentation, selection, and Apply of synthetic droplet results through the
real calibration UI. Do not start that implementation from this milestone.
