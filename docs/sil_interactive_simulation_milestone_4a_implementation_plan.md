# SIL Interactive Simulation Milestone 4A Implementation Plan

Date: 2026-08-01

Parent plan: `docs/sil_interactive_simulation_and_composable_workflows_plan.md`

Prerequisites: Milestones 1, 2, and 3 `complete`

Planning baseline: `220df24`

Status: `complete`

## Goal

Present and apply one deterministic `nominal_droplet` synthetic calibration
through the real calibration summary, selection, preview, and Apply controls.
The synthetic candidate is transient and application-owned; authoritative
changes continue through the existing ExperimentModel calibration-revision
and persistence operations.

## Call Path

```text
Simulator Control
  -> SimulationSession
  -> SyntheticCalibrationApplicationAdapter
  -> SyntheticCalibrationProvider
  -> retained canonical request/result evidence
  -> CalibrationManager transient candidate surface
  -> camera-free simulation presentation of DropletImagingDialog
  -> real selection, bridge preview, and Apply control
  -> ExperimentModel.apply_*_droplet_volume()
  -> ExperimentModel.apply_execution_calibration()
  -> Controller-driven simulated print settings
  -> execution_calibrations.json / execution_plan.json / progress.json
  -> task-guide, state-recorder, and retained-root reload evidence
```

The presentation path never starts or stops a camera/read stream, enables a
physical calibration profile, runs a calibration process, or writes a
synthetic row into `calibration.json`.

## Frozen Interfaces

- `TransientCharacterizationCandidate` is an immutable application candidate
  carrying the summary row, fingerprints, and exact head/stock/design identity.
- `CalibrationManager` owns one transient candidate, merges it only for an
  exact current context, and validates it again immediately before Apply.
- `DropletImagingDialog(result_presentation_only=True)` is accepted only in the
  canonical simulation runtime and retains only summary, preview, Apply, and
  close behavior.
- `SyntheticCalibrationApplicationAdapter` derives a `nominal_droplet` request
  from current application state, writes canonical session evidence once, and
  then registers the candidate.
- `CalibrationDialogDriver` contains bounded QTest mechanics only.

## Implementation Steps

1. Add the application-owned transient result surface and identity validation.
2. Add the camera-free dialog mode, synthetic presentation, and safe launcher.
3. Add the simulation adapter, evidence, developer control, and lifecycle.
4. Add the calibration dialog driver and focused tests.
5. Update the parent roadmap and README.
6. Run focused, compilation, full-suite, visible Windows, reload, and diff
   gates.
7. Only after every gate passes, create the completion record and mark the
   milestone complete.

## Exclusions

No Controller, core Model, simulated-machine, firmware, protocol, production
factory, experiment schema, launcher CLI, stream/manual-refuel, workflow
migration, failure-injection, Pi, or performance-remediation change belongs to
this milestone.

## Verification Gates

Focused tests cover deterministic evidence, transient-surface validation,
synthetic UI provenance, camera isolation, real Apply, settings and plan
reconciliation, active/progressed locks, task guidance, and retained-root
reload. Final validation runs the complete Python suite, `git diff --check`,
and a visible Windows exercise using `tools/run_simulated_app.py`.

## Risks And Rollback

Stale identities are checked when rows are surfaced, selected, and applied.
Synthetic provenance is always visible. Evidence writes are attempted once;
ambiguous failures retain the session and inject no candidate.

Rollback removes the transient surface, presentation-only mode and launcher,
SIL adapter/control, page driver, tests, and Milestone 4A documentation while
retaining the Milestone 3 provider. No data, firmware, or protocol migration is
required.
