# Milestone 7 Slice 3 Completion Record

Status: `complete`

Date: `2026-08-06`

Baseline: `f8bba35b83593c5b4dfd7a70844c5463d1404f45`.

## Outcome

`experiment_editor_prestart_rename_refinalize_v1` now runs through the generic
Slice 2.5 `JourneyExecutor`. It creates the initial two-well prepared design,
reopens and revises it through bounded normal Qt controls, refinalizes a new
six-well stream design, and reloads that design through the normal Qt folder
dialog. The registered CLI path now accepts the standard composed seed and
emits an exact replay command.

The fixture is byte-identical. The legacy direct runner remains callable and
passed as the stable parity oracle. No production MVC, simulator response
model, Pi, firmware, protocol, or hardware file changed.

## Implemented Reuse Boundary

- `drive_editor_prestart_rename_refinalize()` gained the same optional harness
  action-runner boundary already used by initial editor preparation. Its
  default remains the legacy action executor.
- `ExperimentEditorDriver.revise_prepared_design()` delegates to that one
  bounded modal implementation; no QTest loop was copied.
- `PreparedEditorRevisionSpec` validates names, unique wells, finite positive
  volumes, supported modes, and finite non-negative targets. Its normalized
  five-action plan can be inspected with no Qt/application construction.
- `run_prepared_editor_revision()` supplies the shared phase boundary.
- One read-only assertion family captures the initial prepared snapshot and
  validates UI action surfaces, rename isolation, material design changes,
  fresh plan identity, archive integrity, zero progress, empty calibration
  history, runtime assignments, directory uniqueness, audit advance, and
  key/concentration consistency. It hashes authoritative files twice to prove
  inspection did not alter them.
- The new journey body is 76 lines. It composes existing initial preparation,
  the new revision phase, shared assertions, normal-UI prepared load, common
  report finalization, and generic teardown. It contains no QTest timer loop,
  persistence parser, report envelope, or cleanup implementation.

## Reviewed Contract Change

The legacy `validation.prepared_bundle`, `validation.refinalized_bundle`, and
direct `experiment.reload_authoritative` action entries were removed from this
registered scenario. Validation is represented by the unchanged ten required
assertion IDs, and authoritative reload is now
`experiment.load_authoritative_via_ui` with interaction surface `ui`.

`validation.refinalized_bundle` remains a reusable action for the retained
legacy direct runner but is no longer referenced by an active scenario. The
manifest validator now permits unreferenced `reusable` actions while continuing
to reject unreferenced `embedded` actions. This keeps the compatibility oracle
callable without overstating active UI coverage.

The successful composed ledger contains 23 entries including launch,
milestones, teardown, two editor-open actions, initial editor preparation, five
prepared-revision UI actions, and the normal-UI load. All state-changing editor
and load actions report `ui`; assertions, milestones, launch, and teardown
report `harness`.

## Focused Validation

The approved targeted-only policy was used. The complete Python suite was not
run and remains deferred to the final Milestone 7 validation.

- Planning fixture contract: `1 passed`.
- Planning legacy success/failure baseline: `2 passed` in 3.79 seconds.
- Final action/driver/phase/assertion/composition/report/manifest/contract
  batch: `155 passed` in 4.03 seconds.
- New composed success, legacy parity, and controlled refinalization failure:
  `3 passed` in 7.37 seconds.
- All create/finalize, rename/refinalize, and legacy editor lifecycle files
  together: `13 passed` in 15.30 seconds.
- Prepared handoff, initial-plan integration, artifact policy, and
  authoritative-load adjacency: `40 passed` in 4.12 seconds.
- Python compilation and `git diff --check` passed.

The first attempted legacy CLI baseline exposed a pre-existing argument mismatch:
the legacy editor config does not accept the CLI's standard `seed`. The direct
legacy callable was used for the baseline, and the migrated registered path now
uses `JourneyRunConfig` and accepts/records the seed normally.

## Visible And Replay Evidence

The primary visible run passed with 23 actions, ten passing assertions, ten
non-empty screenshots, no unexpected dialog or error, no print command, and no
retained session lock:

```text
verification_reports\milestone7-slice3-visible\experiment_editor_prestart_rename_refinalize_v1\20260807T010403624886Z_composed
```

Its exact emitted replay command also passed:

```text
verification_reports\milestone7-slice3-visible\experiment_editor_prestart_rename_refinalize_v1\20260807T010412178480Z_composed
```

The stable projections were equal. Both reports contain 23 actions and ten
assertions, their screenshot-name sets match, and both session roots are
lock-free. Visual inspection confirmed the renamed three-replicate/six-well
120 nL stream edits, 0.5x/1.0x targets, 60 nL ejection values, finalized
six-reaction design, simulation banner, and disconnected hardware state.

The direct legacy baseline is retained locally at:

```text
verification_reports\milestone7-slice3-baseline\experiment_editor_prestart_rename_refinalize_v1\20260807T005507056005Z_f8bba35b8359
```

These ignored evidence roots are not added to Git.

## Risks And Limitations

- The authoritative assertion family is detailed because it owns the complete
  persistence safety contract once. Future prepared-design journeys should use
  its typed inputs rather than copy it.
- The fixture proves one untouched prepared droplet-to-stream revision. It
  does not cover post-start edits, additional reagent shapes, active matrices,
  or seeded action-order exploration.
- The legacy direct editor runner remains for parity until the final affected
  regression/retirement decision.
- This is application-facing SIL. It makes no firmware, protocol, physical
  motion, collision-safety, pressure-response, camera, balance,
  volume-accuracy, or droplet-quality claim.
- The full Python suite remains required at the final Milestone 7 gate.

## Rollback

Change only the prepared rename/refinalize registry entry back to
`runner_family="experiment_editor"`, restore its legacy manifest action and
artifact/test-node metadata, and remove the Slice 3 journey definition,
revision phase/spec, assertion helpers, driver action-runner hook tests,
composed system test, and documentation. Keep the fixture, legacy direct
runner, Slice 2.5 composition layer, and other composed journeys intact.

No production MVC, firmware/protocol, Pi, or hardware rollback is required.

## Next Step

Stop before Slice 4. Review this completion record and create a concrete plan
for migrating `print_array_soft_stop_resume_24_v1` through the typed
composition layer. Do not begin that migration or the final Milestone 7 full
suite without separate approval.
