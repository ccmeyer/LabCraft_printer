# SIL Interactive Simulation Milestone 3 Implementation Plan

Date: 2026-08-01

Parent plan: `docs/sil_interactive_simulation_and_composable_workflows_plan.md`

Prerequisites: Milestones 1 and 2 `complete`

Planning baseline: `11a9e60`

Status: `complete`

## Goal

Add a pure, deterministic synthetic-calibration provider that produces typed,
reproducible droplet and stream candidates without simulating cameras,
physical ejection, pressure response, firmware, or protocol behavior.

Milestone 3 stops at result generation and explicit application-contract
validation. It does not connect the provider to `SimulationSession`, Qt, the
calibration dialog, Model, Controller, hardware, or authoritative files.
Presentation, selection, and Apply remain Milestone 4A.

## Call Paths

### Generation

```text
simulation caller or focused test
  -> CalibrationGenerationRequestV1 validation
  -> SyntheticCalibrationProvider.generate()
  -> frozen profile-v1 registry
  -> request-local random.Random derived from the request fingerprint
  -> CalibrationGenerationResultV1 validation and fingerprinting
```

### Future application boundary

```text
CalibrationGenerationResultV1
  -> validate_for_application()
  -> existing-compatible summary-row or calibration-step adapter
  -> stop (Milestone 3)

Milestone 4A only:
  -> application-owned candidate surface
  -> real selection and Apply controls
  -> Model calibration revision and authoritative writers
```

Invalid profiles remain inspectable result evidence, but validation and both
adapters raise before an invalid candidate can reach an application surface.

## Frozen Interfaces

The public module is `tools.sil.synthetic_calibration`, re-exported by
`tools.sil`. It provides:

- `CalibrationGenerationRequestV1` and `CalibrationGenerationResultV1`;
- `SyntheticCalibrationProfileV1` and `SyntheticCalibrationProvider`;
- `CalibrationContractError` and `CalibrationApplicationError`;
- request/result schema IDs, schema version 1, and provider identity
  `milestone-3-v1`.

Requests retain seed, provider/profile identity, virtual run/head/stock and
factor/option/fill identity, requested printing mode, nominal volume and
variation, and inclusive pressure/pulse-width bounds.

Results retain every request input plus request/result fingerprints,
measured/effective volume, original/applied modes, pulse width, pressure,
run/phase/stable virtual timestamp, the existing six-field source-row
fingerprint, application validity/errors, and fixed synthetic limitations.

Canonical bytes use UTF-8 JSON with sorted keys, compact separators,
`ensure_ascii=False`, and `allow_nan=False`. The request fingerprint covers
the complete request. The result fingerprint covers the complete normalized
result except its own fingerprint field. The virtual timestamp is derived
from the request fingerprint within a fixed year-2000 epoch and never reads
the wall clock.

## Named Profiles

- `nominal_droplet`: bounded droplet candidate below 40 nL;
- `nominal_stream`: bounded stream candidate at or above 40 nL;
- `droplet_to_stream`: explicit valid droplet-to-stream transition;
- `low_volume_boundary`: exact inclusive lower request boundary;
- `high_volume_boundary`: exact inclusive upper request boundary;
- `invalid_outlier`: finite value outside the requested interval;
- `missing_measurement`: missing measured and effective volumes.

All profiles use version 1. Unsupported identities, versions, modes, bounds,
non-finite numbers, malformed schemas, and fingerprint mismatches fail closed.

## Implementation Steps And Files

1. Freeze this plan and call-path boundary.
2. Add the pure schema/profile/provider implementation in
   `tools/sil/synthetic_calibration.py`.
3. Re-export the stable API from `tools/sil/__init__.py`.
4. Add focused schema, determinism, contract, negative-profile, and isolation
   coverage in `tests/test_sil_synthetic_calibration.py`.
5. Document schema-v1 fields, canonicalization, adapters, and limitations in
   `docs/sil_calibration_schema_v1.md`.
6. Update the parent roadmap and `README.md` without adding a UI or launcher
   control.
7. Run focused, compilation, complete-suite, and diff checks; only then add
   the completion record and mark Milestone 3 complete.

No production `FreeRTOS-interface` file, firmware, protocol, experiment
schema, session schema, launcher, or workflow runner is changed.

## Verification Gates

Focused checks:

```powershell
.\env\Scripts\python.exe -m pytest -q tests\test_sil_synthetic_calibration.py
.\env\Scripts\python.exe -m py_compile tools\sil\synthetic_calibration.py
```

The tests must prove byte-identical repeated generation, bounded multi-seed
variation, complete retained inputs, unchanged global random state, no
filesystem writes, current application summary compatibility, exact boundary
behavior, strict schema/fingerprint rejection, and pre-adapter rejection of
invalid results.

Final checks after the implementation diff exists:

```powershell
.\env\Scripts\python.exe -m pytest -q
git diff --check
git status --short
```

## Risks And Rollback

Synthetic results could be mistaken for physical calibration evidence. Every
result therefore retains fixed limitations and stream adapters include an
explicit synthetic warning; no raw image or physical measurement is created.

Schema drift could make later UI work ambiguous. Strict exact-field parsing,
version identities, canonical fingerprints, and focused compatibility tests
freeze the boundary before Milestone 4A.

Rollback removes this provider, exports, tests, and documentation. It needs no
application-data, firmware, protocol, release, or hardware migration.
