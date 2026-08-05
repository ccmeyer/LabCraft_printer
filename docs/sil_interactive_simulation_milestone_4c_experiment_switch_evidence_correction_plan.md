# Milestone 4C Experiment-Switch and State-Evidence Correction

## Baseline and evidence

The baseline is `00e8473008390241b230d41844a4a489b536796e` with the
Milestone 4C work intentionally uncommitted. Retained session
`20260804T194241257857Z-cd982ec2919b` proved the low-volume synthetic
Droplet-to-Stream application and exposed two follow-up defects:

- changing to an experiment whose legacy `calibration.json` is `{}` retained a
  prior physical-calibration run index and raised `KeyError: 'runs'` during
  readiness evaluation;
- the state projection selected a stale authoritative bundle and reported zero
  in-memory calibration records while the current sidecar contained two.

The retained session is evidence only and must not be modified.

## Corrected call paths

```text
Experiment switch
  -> CalibrationManager changes calibration path
  -> prior run identity is detached without ending or writing it
  -> legacy empty {} is normalized in memory
  -> readiness lookup returns an empty step list
  -> camera-free calibration dialog opens normally

Synthetic Apply
  -> authoritative execution calibration is persisted
  -> state projection validates bundle plan ID and revision
  -> stale bundles are rejected
  -> current contained execution_calibrations.json is strictly loaded
  -> calibration/refuel projections reconcile with persisted evidence
```

## Implementation constraints

- Loading an existing calibration file is read-only. A missing file may be
  initialized with the normal empty envelope.
- Phase-alias lookup remains unchanged for valid physical calibration runs.
- Projection performs no repair, retry, cache mutation, or authoritative write.
- Controller, camera, hardware, experiment-schema, synthetic-provider, and
  fingerprint contracts do not change.
- Broader Milestone 4C remains incomplete until focused automated, visible
  Windows, and retained-root reload gates pass.

## Validation

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_sil_normal_ui_convergence.py `
  tests\test_sil_state_projection.py `
  tests\test_calibration_phase_aliases.py `
  tests\test_droplet_imaging_summary_table.py

.\env\Scripts\python.exe -m py_compile `
  FreeRTOS-interface\CalibrationClasses\Model.py `
  tools\sil\state_projection.py

git diff --check
git status --short
```

No full-suite run is required for this focused correction. Visible validation
uses a fresh retained root, an exact 9 nL 24-well transition, a passed manual
refuel check, an empty-history duplicate, and a retained-root reload. Rollback
removes only this correction and its tests; retained experiments require no
migration.
