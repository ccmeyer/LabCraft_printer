# Milestone 4C Low-Volume Droplet-to-Stream Correction

## Baseline and objective

Baseline: `00e8473008390241b230d41844a4a489b536796e` with the existing
Milestone 4C work intentionally uncommitted.

Allow the normal Stream-tab `Calibrate All` workflow from any valid droplet
ejection volume below 40 nL, including the normal 9 nL default. The synthetic
transition records the current source volume and produces an exact 40 nL
stream result before using the existing preview, mode-switch confirmation,
authoritative application, and manual-refuel paths.

```text
Stream-tab Calibrate All
  -> availability accepts current droplet volume in [1, 40)
  -> directional transition request records source volume and 40 nL target
  -> deterministic synthetic stream result
  -> existing row selection, preview, confirmation, and Apply
  -> ExperimentModel / Controller / authoritative persistence
  -> required manual-refuel check
```

Firmware, protocol, physical calibration, cameras, Controller behavior,
experiment schemas, and hardware factories are excluded.

## Frozen contract

- Existing request/result schema v1, provider version `milestone-3-v1`, profile
  version 1, serialization, and fingerprints remain unchanged.
- Add strict request/result schema v2 using the existing schema IDs,
  `schema_version: 2`, provider version `milestone-4c-v2`, and
  `droplet_to_stream` profile version 2.
- V2 replaces the symmetric nominal/variation fields with
  `source_volume_nL` and `target_volume_nL`. It requires requested mode
  `droplet`, a source in `[1, 40)`, and a target in `[40, 250]`.
- The application adapter always requests an exact 40 nL target. The result's
  measured and effective volumes equal that target.
- Canonical JSON, request/result fingerprints, virtual timestamps,
  source-row fingerprints, application validation, and synthetic limitations
  retain the v1 guarantees.
- Deserialization dispatches only recognized schema/provider/profile versions.
  Retained v1 and v2 artifacts may coexist and rehydrate into the same
  read-only synthetic history surface.
- The normal calibration dialog displays directional readiness such as
  `9.000 nL Droplet -> 40.000 nL Stream`; the existing Apply path is unchanged.

## Implementation sequence

1. Record this frozen correction plan.
2. Add immutable v2 request/result contracts and provider dispatch.
3. Generate v2 transitions in the application adapter and rehydrate both
   schema versions.
4. Export the v2 API and show directional readiness in the normal dialog.
5. Add focused provider, adapter, UI, lifecycle, persistence, and compatibility
   tests.
6. Update schema and developer documentation.
7. Run focused tests, compilation, diff, and worktree gates.
8. Run fresh visible Windows and retained-root validation before recording
   completion; do not mark broader Milestone 4C complete early.

## Validation and rollback

The focused validation covers source volumes 1, 9, 20, 25, and just below
40 nL; invalid boundaries and modes; deterministic fingerprints; unchanged v1
goldens; v1/v2 history coexistence; stale identity; preview/application; and
cancelled mode switches. The full pytest suite remains excluded for this
correction.

Rollback removes only the v2 contracts/dispatch, adapter selection, readiness
text, tests, and correction documentation. Existing v1 evidence and retained
experiment data require no migration or repair. Previously retained roots are
preserved and never edited by this work.
