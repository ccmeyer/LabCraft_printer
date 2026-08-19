# Machine Data Migration and Location Safety Plan for v1.3.0-rc.2

Status: `proposed`

Prepared: 2026-08-19

Target release: `v1.3.0-rc.2`

## Purpose

This is the living implementation and qualification plan for moving
machine-owned configuration out of a Git checkout, migrating deployed
`v1.2.0-rc.6` and `v1.3.0-rc.1` machines safely, recording configuration
changes, guarding high-risk edits, and proving configuration preservation
across future updates.

The plan was prompted by a damaging Camera-position collision after a machine
was updated to `v1.3.0-rc.1`. The observed symptom was an isolated and
substantial Camera Y error while the other tested named locations appeared
correct. The investigation found a credible configuration-seeding failure
mode: production configuration currently lives under `<repo>/local`, so a new
checkout or missing local directory can seed a tracked starter preset that
contains a historically older Camera position.

This document is authoritative for the work until the target release is
qualified. Update it as milestones begin, decisions are resolved, unexpected
findings appear, validation is run, or scope changes. Do not mark a milestone
complete without recording its implementation commit and validation evidence.

## How to maintain this document

Use these milestone states:

- `planned`: scope and exit criteria are defined; implementation has not begun.
- `in_progress`: implementation or validation is active.
- `implementation_complete`: code is complete, but one or more required gates
  remain.
- `verified`: every exit criterion and required validation gate passed.
- `blocked`: progress requires a documented decision or external dependency.
- `deferred`: explicitly removed from the target release with rationale.

For every milestone update:

1. Change its status in the milestone table and milestone section.
2. Record the commit or branch under **Implementation record**.
3. Record exact test commands and results under **Validation record**.
4. Add newly discovered facts to the findings log.
5. Add policy choices to the decision log.
6. Add plan edits to the change log.

## Milestone status

| Milestone | Scope | Status | Implementation | Validation |
| --- | --- | --- | --- | --- |
| 0 | Preserve deployed machine state | `verified` | Operator backup complete | Operator attestation recorded |
| 1 | Freeze external machine-data contract | `implementation_complete` | Inert contract complete on `update_bug_fix`; milestone commit pending | 101 focused and 5,100 full-suite tests passed |
| 2 | Build inert migration and backup engine | `planned` | Not started | Not started |
| 3 | Activate first-launch migration and verification | `planned` | Not started | Not started |
| 4 | Add transactional configuration history | `planned` | Not started | Not started |
| 5 | Add guarded location and calibration changes | `planned` | Not started | Not started |
| 6 | Protect future updates and controlled rollback | `planned` | Not started | Not started |
| 7 | Qualify, release, and stage deployment | `planned` | Not started | Not started |

No local `v1.3.0-rc.2` release tag may be created until Milestones 0 through 6
are `verified` and the Milestone 7 pre-tag gates pass. Do not push or advertise
the tag until Milestone 7 qualification is complete. A release decision may
defer a documented non-safety-critical item, but the fixed safety invariants
below cannot be deferred.

## Implementation discipline

- Develop on feature branches and keep one milestone per reviewable commit.
- Reconfirm the call path and exact file list before editing each milestone.
- Add behavior-lock and failure-path tests before or with implementation.
- Keep diffs narrow; do not combine unrelated MVC, firmware, or release work.
- Do not edit release metadata until Milestone 7 and after re-reading
  `docs/release_process.md`.
- Do not modify firmware or the device protocol as part of this plan unless a
  separately approved finding makes it necessary.
- Update this document in the same milestone commit when status, decisions,
  findings, risks, or validation evidence change.

## Executive decision summary

1. Machine configuration remains untracked but moves outside the repository.
2. Every checkout and worktree on a machine resolves the same external
   machine-data root.
3. A full manual copy of the active legacy `local/` directory is the Milestone
   0 recovery backup. Users are not required to calculate hashes manually.
4. The application calculates per-file SHA-256 hashes and verifies copies.
5. Missing configuration never silently becomes motion-authorized preset data.
6. The first rc.2 startup runs migration before Settings, Model, Controller,
   comms, or the normal main window are constructed.
7. Copy verification, source verification, and physical-calibration trust are
   separate states.
8. Safety-sensitive locations have individual verification state. Unverified
   targets cannot dispatch motion.
9. Existing JSON shapes remain compatible with the legacy readers. Metadata,
   verification, history, and migration receipts use sidecar artifacts.
10. Every committed location, rack, or plate calibration change creates a
    backup and a durable audit event.
11. Plate calibration is one four-corner transaction, not four independent
    active writes.
12. Hard machine bounds, physical exclusion regions, and large-change warning
    thresholds are distinct policies.
13. The updater proves preservation for rc.2-to-future updates. The old rc.6
    and rc.1 updater cannot perform the new preflight, so Milestones 0 and 3
    protect the initial transition.
14. Rollback to an older app is support-guided until the compatibility export
    and paired-firmware path is fully qualified.
15. No firmware protocol, opcode, motion algorithm, pressure behavior, or
    timing behavior is changed by this plan.

## Safety invariants

These invariants are mandatory and must be locked by automated tests where
possible:

1. **Fail closed:** missing, malformed, ambiguous, partially migrated, or
   unverified machine configuration cannot enable saved-location motion.
2. **No preset authorization:** a tracked preset may be copied only as an
   explicitly unverified draft. Its existence is never evidence of physical
   calibration.
3. **No pre-bootstrap hardware construction:** first-launch migration and
   verification run before hardware-capable MVC components are constructed.
4. **Preserve before mutation:** a readable source is backed up before any
   migration, import, restore, edit, update, or compatibility export can
   replace active data.
5. **Exact copy evidence:** migration records source and destination hashes and
   does not activate a destination unless required files compare exactly.
6. **No automatic conflict winner:** canonical and legacy configurations that
   differ are presented as a conflict. Timestamps alone never choose a winner.
7. **One canonical writer:** after migration, normal rc.2 operation writes only
   the external canonical store. It does not continuously dual-write
   checkout-local compatibility copies.
8. **Atomic durable writes:** active JSON changes use staged writes, flush,
   `fsync`, and atomic replacement. Multi-artifact transactions leave a
   recoverable journal if interrupted.
9. **Auditable mutations:** every attempted and committed safety-relevant
   configuration change has an event identity, before/after values, provenance,
   result, and file hashes.
10. **Visible failures:** copy, validation, backup, audit, or save failure is
    shown to the operator. A failed persistence operation is never reported as
    a successful calibration.
11. **Defense in depth at dispatch:** even if UI state is wrong, Controller
    rejects motion to an unverified named target before any command is queued.
12. **Single writer across checkouts:** the current application-wide instance
    lock must remain common across checkouts, and the canonical data store must
    have its own transaction lock. Cross-user and cross-platform behavior must
    be tested.
13. **Firmware pairing remains explicit:** configuration migration does not
    imply that the installed controller firmware is compatible or verified.
14. **Rollback is non-destructive:** rollback never overwrites the canonical or
    legacy copy without preserving both and verifying the compatibility export.

## Scope

### In scope

- External, machine-owned production configuration storage.
- Migration from the layouts used by `v1.2.0-rc.6` and `v1.3.0-rc.1`.
- Manual pre-update recovery backup and automatic first-start migration backup.
- Machine identity and active-machine selection metadata.
- Copy, source, and per-location verification states.
- Fail-closed first-start behavior and motion-dispatch authorization.
- Transactional history for named locations, rack calibration, and plate
  calibration.
- Before/after/delta previews and stronger confirmation for large changes.
- Global travel-bound validation and hooks for physical exclusion regions.
- Future updater preflight, post-update verification, and migration receipts.
- Controlled compatibility export before rollback to a legacy app.
- Automated fault injection, source-tag migration tests, virtual validation,
  controlled hardware qualification, and staged fleet rollout.

### Out of scope

- Changing firmware opcodes, protocol framing, coordinated-motion algorithms,
  pressure control, watchdog behavior, or timing.
- Claiming collision safety solely from existing `Obstacles.json`; the current
  tracked obstacle list contains no modeled physical obstacles.
- Automatically discovering the exact firmware flashed on a board when the
  firmware does not expose a trustworthy build identity.
- General experiment-storage relocation.
- Moving every cache, downloaded update bundle, temporary worktree, or
  reproducible artifact currently found under `local/`.
- Automatic deletion of legacy configuration or migration backups.
- Retargeting, deleting, or moving existing release tags.

## Terminology

| Term | Meaning |
| --- | --- |
| Checkout | One working directory containing a clone or worktree of the application repository. |
| Legacy local root | `<checkout>/local`, used by rc.6 and rc.1 production configuration. |
| Machine-data root | Stable untracked directory outside every checkout. |
| Canonical config | The active machine-owned configuration under the machine-data root. |
| Candidate | A legacy folder, manual backup folder, ZIP, or existing canonical store considered for import. |
| Tracked preset | Starter JSON under `FreeRTOS-interface/Presets`; not machine calibration. |
| Copy verified | Source and destination validate and have matching required file hashes. |
| Source verified | Operator confirms the candidate belongs to the selected physical machine. |
| Calibration verified | A named target or calibration is trusted for physical use according to the accepted verification policy. |
| Preset-like | Candidate whose required configuration or safety-sensitive values match tracked starter values. |
| Compatibility export | Verified copy from canonical external data back to legacy `<repo>/local` before running an older app. |
| Hard bound | Absolute machine travel or physical exclusion rule; violation is rejected. |
| Delta threshold | Difference between prior and proposed calibration; violation prompts stronger confirmation and may require service authorization. |

## Verified baseline findings

The read-only investigation established the following baseline:

1. `v1.2.0-rc.6` commit `199807eea95a238896137bddb2a83d3d892e2aab`
   and `v1.3.0-rc.1` commit
   `922f2ac65eab2ff1f63ffc0719a98b777bc2128f` both use
   `<repo>/local` for production machine configuration.
2. rc.1 added injectable roots for simulation/test composition, but production
   still resolves to checkout-local storage.
3. `v1.2.0-rc.6` is an ancestor of `v1.3.0-rc.1`; one migration engine can
   support both source layouts.
4. The tracked `Presets/Locations.json` is unchanged between the two tags.
5. The tracked Camera value remains `X=11563`, `Y=39550`, `Z=99388`.
6. A September 2025 commit changed Camera to that value. A February 2026
   location update changed several other locations but did not change Camera,
   making the tracked starter file mixed-age.
7. Missing `<repo>/local/Locations.json` currently copies the entire tracked
   preset. There is no separate old Camera file and no per-entry fallback.
8. Invalid existing JSON fails validation rather than selecting another Camera
   file.
9. Normal in-app updates preserve ignored `local/` data when updating in place.
   They do not run `git clean` or replace `local/`.
10. A new clone, worktree, deployment directory, deleted local directory, or
    launcher pointed at a different checkout can resolve a different local
    configuration.
11. The Controller sends the exact saved Camera X/Y values through
    `ABSOLUTE_XY`; there is no Camera-specific Y offset or scaling in the app.
12. Normal named-location writes occur through explicit add/modify/save paths.
    Rack calibration writes both rack anchors. No background Camera rewrite
    process was found.
13. Plate calibration captures `top_left`, `top_right`, `bottom_right`, and
    `bottom_left`, then replaces the active plate calibration as one UI
    acceptance operation.
14. The current app-level instance lock uses Qt application-local storage and
    is intended to be common across checkouts. Its cross-user/platform behavior
    still needs qualification once configuration is external.
15. `v1.3.0-rc.1` requires paired v1.3 firmware. The application updater does
    not flash firmware automatically.
16. Focused no-hardware investigation tests passed: 209 tests covering local
    configuration, updater behavior, production roots, named-location routing,
    and coordinated-motion contracts.

## Current production call paths

### Startup and configuration

```text
App.main()
-> configure Qt application identity
-> acquire single-instance lock
-> show splash
-> get_machine_config_path("Settings.json")
-> production_dependencies()
-> Model(..., config_root=None)
-> get_machine_config_path("Locations.json" / "Plates.json" /
                           "Settings.json" / "Obstacles.json")
-> construct View, Controller, Machine_FreeRTOS
```

The unsafe migration boundary is that Settings and Model configuration are
resolved before a migration/verification workflow exists.

### Named-location movement

```text
View.move_to_location()
-> Controller.move_to_location(name)
-> LocationModel.get_location_dict(name)
-> Controller.set_absolute_coordinates(X, Y, Z)
-> Machine_FreeRTOS ABSOLUTE_XY and Z commands
-> firmware handlers
```

The rc.2 defense-in-depth gate belongs in Controller before command dispatch.

### Named-location mutation

```text
View.add_new_location() / View.modify_location()
-> Controller captures MachineModel current position
-> LocationModel add/update in memory
-> operator confirms save
-> LocationModel.save_locations()
```

The current split between in-memory mutation and later optional persistence
must be replaced or wrapped by one transactional commit contract.

### Rack calibration mutation

```text
rack calibration workflow
-> Model.update_rack_calibration()
-> update rack_position_Left
-> update rack_position_Right
-> save Locations.json
```

Both rack anchors must be one audit transaction.

### Plate calibration mutation

```text
PlateCalibrationDialog
-> capture temporary top_left, top_right, bottom_right, bottom_left
-> dialog Accepted
-> WellPlate.update_calibration_data()
-> replace active four-corner calibration in memory
-> atomically replace Plates.json
-> apply transformation
```

The new storage layer must stage and validate the full proposed document before
changing active in-memory calibration.

### Update

```text
running old updater process
-> inspect current checkout
-> fetch/validate target release
-> update checkout
-> record updater result when enabled
-> relaunch application from the same checkout
```

For rc.6/rc.1 to rc.2, the updater process is old code. The rc.2 migration
begins only after the update, when rc.2 is relaunched.

## Target architecture

The exact OS paths are a Milestone 1 decision. The logical layout is:

```text
<machine-data-root>/
  active_machine.json
  machines/
    LC-001/
      config/
        Locations.json
        Settings.json
        Plates.json
        Obstacles.json
        RegulatorProfiles.json
      CalibrationMemory/
      metadata/
        machine.json
        verification.json
        migration_receipt.json
      history/
        configuration_events/
        pending_transactions/
      backups/
        migration/
        edits/
        updates/
        rollback_exports/
      update_history/
      locks/
        configuration.lock
```

Illustrative defaults to evaluate in Milestone 1:

- Windows system-wide: `%PROGRAMDATA%/LabCraft/...`, with installer-managed
  permissions.
- Windows per-user fallback: an OS application-data directory outside the
  checkout.
- Raspberry Pi/Linux: an installation-configured writable data root outside
  the repository, such as a service-owned directory or a stable directory
  beneath the deployment user's home.

Do not select a removable drive, Desktop backup, or Git worktree as the
canonical root. Those are candidate/backup sources only.

### Ownership classification

| Data | Canonical external store in rc.2 | Milestone 0 full backup | Notes |
| --- | --- | --- | --- |
| Locations | Yes | Yes | Safety-critical |
| Settings | Yes | Yes | Includes hardware-profile behavior |
| Plates | Yes | Yes | Includes four-corner calibrations |
| Obstacles | Yes | Yes | Safety-related, currently minimal |
| Regulator profiles | Yes | Yes | Machine-owned configuration |
| CalibrationMemory | Yes | Yes | Machine-owned learned/calibration state |
| Machine identity | Yes | Yes when present | Must not be guessed from hostname alone |
| Configuration audit/history | Yes | Not present on legacy tags | Created by rc.2 |
| Migration/update/rollback receipts | Yes | Legacy update logs included | Created or consolidated by rc.2 |
| Downloaded update bundles | No, initially | Yes if present | Reproducible and potentially large |
| Temporary worktrees/caches | No | Yes if under copied local | Not authoritative machine data |
| Experiments | No change in this plan | Only if already under local | Separate ownership/migration decision |
| General application logs | No mandatory relocation | Yes if under local | Selective diagnostic retention later |

### Proposed startup path

```text
App.main()
-> configure application identity
-> acquire application-wide instance lock
-> MachineDataBootstrap.prepare()
   -> resolve external base
   -> acquire canonical transaction/migration lock
   -> resolve active machine identity
   -> validate existing canonical store OR discover/import candidate
   -> create and verify migration backup
   -> obtain copy/source/calibration verification decisions
   -> return verified ApplicationRoots
-> load Settings from returned config root
-> construct Model with the same config root
-> construct Controller/View/Machine only when startup authorization permits
```

## Machine-data and migration contracts

### Active-machine contract

The active-machine record must minimally identify:

- schema name and version;
- stable machine ID;
- canonical machine directory;
- assignment timestamp;
- assignment source and operator where available.

The machine ID source and multi-machine behavior are open Milestone 1
decisions. An MCU/USB serial may be recorded as supporting evidence but must
not be assumed to identify the complete printer without qualification.

### Verification contract

Verification has three independent layers:

1. **Copy verification:** automatic structural validation and exact per-file
   hash comparison.
2. **Source verification:** operator confirms the selected candidate belongs
   to the selected physical machine and was an intended source.
3. **Calibration verification:** each required physical target is authorized
   according to the accepted policy.

Example location verification states:

- `unverified`
- `verified_from_trusted_existing_calibration`
- `verified_against_service_record`
- `verified_by_controlled_calibration`
- `revoked`

Verification records must include who/what performed verification, when, the
coordinate values and config hash verified, and the app version/commit. Any
subsequent value change revokes prior verification for the changed target until
the change workflow completes.

Copy verification alone never authorizes motion. A candidate identical to a
tracked preset is explicitly `preset_like` and cannot use a bulk trust action.

### Candidate discovery contract

Candidate precedence is not winner selection. The UI may present candidates in
this order:

1. Existing canonical store for the active machine.
2. Current checkout's legacy `<repo>/local`.
3. Operator-selected folder containing `local/`.
4. Operator-selected direct `local/` folder.
5. Operator-selected supported backup ZIP.

The app does not recursively scan an entire disk and does not choose the newest
file automatically. Candidates with equal required-file hashes are shown as
duplicates. Candidates with different hashes are a conflict requiring an
explicit choice and recorded reason.

### Migration state machine

```text
uninitialized
  -> candidate_selected
  -> source_validated
  -> backup_verified
  -> staged_copy_verified
  -> copied_unverified
  -> source_verified
  -> calibration_verification_pending
  -> verified
  -> active
```

Failure/alternate states:

```text
no_candidate
invalid_source
ambiguous_candidates
backup_failed
copy_failed
preset_like_requires_review
verification_cancelled
conflict
recovery_required
```

Every transition is idempotent. Relaunch after a crash resumes or reconciles a
recorded state instead of starting a second independent migration.

### Legacy compatibility contract

- Canonical `Locations.json`, `Plates.json`, and other legacy files retain the
  shapes expected by rc.6/rc.1 readers.
- Metadata and history remain sidecars.
- Normal rc.2 writes do not dual-write `<repo>/local`.
- A support-guided rollback performs an explicit, backed-up, hash-verified
  compatibility export.
- A later re-upgrade detects changes made by the legacy app and does not
  overwrite either side automatically.

## Backup contract

### Milestone 0 manual backup

Operator instructions:

1. Close LabCraft and disable machine motion.
2. Identify the checkout used by the current launcher.
3. Copy its complete `local/` directory to the Desktop.
4. Copy the same directory to an external drive.
5. Copy the checkout's `VERSION` file beside each `local/` copy.
6. Do not move, delete, or edit the original.
7. If the active checkout is uncertain, preserve every plausible candidate in
   separately named folders.

Recommended layout:

```text
LC-001_before_rc2_20260819/
  VERSION
  local/
    Locations.json
    Settings.json
    Plates.json
    Obstacles.json
    ...
```

Users do not calculate hashes. The complete copy is the recovery artifact.

### Automatic first-start backup

Before activating or modifying any candidate, rc.2 creates a verified archive
outside the checkout. The archive includes the source configuration and a
generated manifest containing:

- UTC collection timestamp;
- machine ID, if known;
- source path and source type;
- source version and best-effort pre-update SHA;
- per-file SHA-256 hashes;
- saved safety-sensitive coordinates;
- preset-match indicators;
- checkout firmware-artifact hash labeled as package evidence, not proof of
  installed board firmware;
- archive content list and any intentionally omitted files.

The exporter reopens the completed archive and verifies every recorded hash
before reporting success. Migration stops if backup verification fails.

### Privacy and size

The complete manual backup may contain experiments, logs, or proprietary
calibration information. It should not be uploaded automatically. A later
support-export function may create a curated archive, but it must not replace
the full local recovery backup.

## Configuration transaction and audit contract

### Transaction outline

For every safety-relevant change:

1. Acquire the external configuration lock.
2. Read and validate current persisted state.
3. Construct and validate the full proposed state without mutating active
   in-memory state.
4. Calculate before/after hashes and semantic deltas.
5. Create and verify a backup of current state.
6. Write and `fsync` a pending transaction journal.
7. Atomically replace the active JSON.
8. Commit an immutable audit event.
9. Update in-memory state only after persisted commit succeeds.
10. Remove/finalize the pending journal and release the lock.

Startup reconciles any pending transaction. Until reconciliation completes,
saved-location movement is disabled.

### Minimum audit event fields

- schema name/version;
- event ID and UTC timestamp;
- event type and result;
- machine ID;
- operator/workstation identity where available;
- app version and Git commit;
- source workflow;
- affected file and logical entities;
- complete before and after values for the affected entities;
- coordinate deltas where applicable;
- before and after file hashes;
- backup reference;
- verification state changes;
- reason/confirmation class;
- error details for failed or rejected attempts.

### Required event types

- `configuration_imported`
- `configuration_migration_completed`
- `configuration_conflict_detected`
- `location_add_attempted`
- `location_added`
- `location_change_attempted`
- `location_changed`
- `location_change_rejected`
- `location_restored`
- `rack_calibration_changed`
- `plate_calibration_started`
- `plate_calibration_cancelled`
- `plate_calibration_changed`
- `verification_granted`
- `verification_revoked`
- `update_preflight_completed`
- `update_preservation_verified`
- `rollback_export_completed`

### Plate calibration event

The committed event contains the complete old and new four-corner set for one
plate:

```text
top_left
top_right
bottom_right
bottom_left
```

Intermediate corner captures may be recorded as diagnostic events but cannot
replace active plate calibration. Cancelled or incomplete dialogs leave the
persisted and active calibration unchanged.

### Rack calibration event

Left and Right rack anchors are committed and audited together. A failure after
capturing one anchor must not activate a half-updated rack geometry.

## Location and calibration safety policy

### Layer 1: absolute travel bounds

All coordinates must fall within validated machine-axis bounds. A violation is
a hard rejection. Existing configured boundaries are a starting point, not
proof of complete collision safety.

### Layer 2: physical exclusion/path rules

Known collision volumes and controlled-approach regions are hard rules after
their geometry and route behavior are measured and HIL-qualified. This plan
does not claim those rules from the currently empty obstacle list.

### Layer 3: semantic calibration validation

Examples:

- Plate corners have all required axes, correct corner ordering, plausible
  dimensions, and a non-degenerate transform.
- Rack Left/Right anchors have plausible ordering and spacing.
- Reserved named locations have valid types and individually tracked
  verification state.

### Layer 4: change-delta policy

The UI always previews old, proposed, and delta values. Configurable thresholds
control stronger confirmation. Thresholds are not universal hard collision
envelopes.

No arbitrary global 5,000-step hard limit will be adopted without fleet data.
Milestone 5 must derive or explicitly approve per-location/per-axis defaults.
Camera should have a stricter policy than a generic user-created location.

### Layer 5: save preconditions

Capturing current machine coordinates for a saved calibration requires:

- machine homed;
- machine idle;
- no queued movement;
- recent position telemetry;
- active machine identity;
- valid destination/configuration state.

### Layer 6: dispatch authorization

Controller checks target verification, configuration hash binding, bounds, and
route policy before queueing any movement. UI enablement alone is insufficient.

## Milestone 0: Preserve deployed machine state

Status: `verified`

### Objective

Create an independent recovery copy before any deployed rc.6 or rc.1 machine
enters the rc.2 update process.

### Deliverables

- Operator backup instructions using full `local/` copies and `VERSION`.
- Per-machine rollout inventory with machine ID, source release, backup
  locations, and operator confirmation.
- Firmware-deployment status recorded by the deployment team; `unknown` is an
  acceptable honest value before it is re-established.
- Decision on who owns and retains the external-drive copy.

### User responsibilities

- Close the app and disable motion.
- Copy the active checkout's complete `local/` directory to Desktop and an
  external drive.
- Copy `VERSION`.
- Preserve the original.

Users do not run Git commands or calculate hashes.

### Deployment-team responsibilities

- Help identify the active checkout if ambiguous.
- Confirm both backups contain at least `local/Locations.json` and `VERSION`.
- Record the backup completion in the fleet inventory.
- Establish firmware provenance or schedule deployment of the known paired
  rc.2 artifact.

### Tests/checks

- Open each backup and parse required JSON files.
- Verify the backup is not stored inside the checkout being updated.
- Verify Desktop and external-drive copies are independently accessible.
- When automation becomes available, calculate and record per-file hashes.

### Exit criteria

- The backup procedure is proven on representative rc.6 and rc.1 machines or
  faithful fixtures before the release is tagged.
- The fleet inventory and per-machine backup gate are ready for rollout.
- Machines with ambiguous checkouts preserve all plausible candidates.
- No individual machine begins rc.2 deployment without a readable recovery
  copy or an explicit stop-work decision.

### Rollback

Milestone 0 changes no application behavior. Recovery is copying the preserved
legacy data back only under a support-guided procedure after preserving the
current state.

### Expected files touched

- This plan and operator/runbook documentation only.

### Implementation record

- 2026-08-19: The operator confirmed that the target Pi's complete active
  `local/` directory and `VERSION` file were copied before the rc.2 update.
- The recovery copies are treated as the authoritative Milestone 0 evidence for
  this target machine. The same per-machine backup gate remains mandatory for
  any additional machine before its update begins.

### Validation record

- 2026-08-19: Operator attestation accepted that the copies are readable and
  stored outside the checkout being updated.
- No user-calculated directory hash was required. Per-file hash generation and
  archive verification remain application responsibilities in Milestones 2
  and 3.

## Milestone 1: Freeze the external machine-data contract

Status: `implementation_complete`

Concrete plan:
[Machine Data Migration Milestone 1: Contract Implementation Plan](machine_data_migration_milestone_1_implementation_plan.md)

### Objective

Define and implement path resolution, identity, ownership, permissions,
metadata schemas, locks, and test injection without changing production's
active configuration path.

### Required decisions

- Exact Windows and Pi/Linux base paths.
- System-wide versus per-user ownership and installer/service permissions.
- Active-machine identity source and unassigned-machine behavior.
- Multi-machine behavior on one host.
- Curated canonical data set and retention policy.
- Metadata schema names/versions.
- External transaction-lock mechanism and cross-user semantics.

### Deliverables

- Machine-data path resolver.
- Immutable value object describing application roots.
- Active-machine and metadata schemas.
- Safe path containment checks.
- Configurable roots for tests and development.
- Lock contract common to all checkouts using the same machine data.
- No production cutover yet.

### Files touched

- New `FreeRTOS-interface/MachineData.py`.
- `FreeRTOS-interface/LocalConfig.py`.
- New `tests/test_machine_data_contract.py`.
- `tests/test_local_config.py`.
- This living plan and the detailed Milestone 1 implementation plan.

The application composition, startup, MVC, updater, firmware, protocol, and
release-metadata files were intentionally not changed.

### Tests

- Windows and POSIX path resolution.
- Relative-path rejection and containment.
- Same root resolved from two different checkout paths.
- Active-machine identity validation.
- Missing or malformed metadata.
- Canonical configuration-lock path construction.
- Test/simulation roots remain isolated and cannot escape their run root.
- Production startup does not import or activate the new contract.

Writable-root probes and concurrent lock acquisition remain Milestone 2 work;
Milestone 1 resolution is deliberately side-effect-free.

### Exit criteria

- Contract and schemas are documented and tested.
- Two checkouts resolve the same production machine root.
- Production still uses legacy local until Milestone 3.
- No firmware or motion behavior changes.

### Rollback

Remove the inert resolver and tests. Legacy production behavior remains intact.

### Implementation record

- 2026-08-19: Concrete implementation plan created. Application implementation
  started on the inert path/schema contract; production cutover remains out of
  scope.
- 2026-08-19: Implemented the pure external-root resolver, immutable and
  self-validating UUID-keyed path contracts, versioned identity and
  active-machine schemas, and public read-only LocalConfig inventories on
  branch `update_bug_fix`.
- Added focused tests for override precedence, unsafe-root rejection,
  cross-checkout equality, containment, schema validation, LocalConfig
  behavior, and production non-activation.
- No directory is created, no legacy file is read or changed, and no runtime
  call path imports the new module. A dedicated Milestone 1 commit is pending.

### Validation record

- Focused command:

  ```powershell
  .\env\Scripts\python.exe -m pytest -q `
    tests\test_machine_data_contract.py `
    tests\test_local_config.py `
    tests\test_safe_application_construction.py `
    tests\test_view_window_icon_contract.py
  ```

  Result: 101 passed; 110 existing Qt deprecation warnings; 5.86 seconds.

- Full Python gate:

  ```powershell
  .\env\Scripts\python.exe -m pytest -q
  ```

  Result: 5,100 passed, 152 skipped; 585 existing deprecation warnings;
  266.06 seconds.

- `git diff --check` passed for tracked changes. A separate scan found no
  trailing whitespace in the six Milestone 1 files and confirmed balanced
  Markdown fences in both new plan documents.
- No hardware command, firmware flash/build, HIL run, protocol change, or
  motion test was needed because this milestone is inert and not connected to
  production startup.

## Milestone 2: Build the inert migration and backup engine

Status: `planned`

### Objective

Implement candidate discovery, validation, backup, hash verification,
conflict handling, staged copy, receipts, and crash recovery behind direct APIs
and tests. Do not invoke it from production startup yet.

### Deliverables

- Candidate readers for current legacy local, selected folder, parent backup
  folder, and supported ZIP.
- Candidate normalization and duplicate detection by required-file hashes.
- Preset-like detection.
- Full-source backup exporter and manifest.
- Per-file SHA-256 calculation.
- Staged atomic canonical import.
- Idempotent migration state machine and receipt.
- Fault-injection hooks at every write/replace boundary.
- No disk-wide automatic search.

### Candidate rules

- A candidate is never mutated.
- Invalid required JSON blocks that candidate.
- Missing safety-critical files cannot be silently supplied and verified from
  presets.
- Missing non-safety fields may be migrated only through explicit versioned
  schema migration that preserves machine-owned values.
- Equal candidates are presented as duplicates.
- Different candidates are an unresolved conflict until the operator chooses.

### Expected files touched

- Machine-data module(s) introduced in Milestone 1.
- New migration/backup modules if separation improves reviewability.
- `FreeRTOS-interface/LocalConfig.py` validation helpers as appropriate.
- New migration, archive, and fault-injection tests.

### Tests

- Exact rc.6 legacy fixture with non-preset Camera.
- Exact rc.1 legacy fixture with non-preset Camera.
- Preset-identical candidate.
- Candidate whose Camera alone matches the preset.
- Direct local folder, parent folder, and ZIP selection.
- Duplicate sources and conflicting sources.
- Missing, malformed, and wrong-top-level-type JSON.
- Read-only source and unwritable destination.
- Disk-full/write-failure simulation.
- Failure before backup, during backup, during staged copy, before replace, and
  after replace before receipt finalization.
- Relaunch/reconciliation after every injected interruption.
- No partial canonical configuration becomes active.

### Exit criteria

- Migration is deterministic, idempotent, and fault-injection clean.
- Source/destination evidence is sufficient to prove an exact copy.
- Preset-like data remains unverified.
- Production startup still uses legacy local.

### Rollback

Remove the inert engine. It has not altered production startup. Preserve tests
and fixtures if they remain useful for the redesigned approach.

### Implementation record

- Not started.

### Validation record

- Not started.

## Milestone 3: Activate first-launch migration and verification

Status: `planned`

### Objective

Run migration before configuration or hardware construction, obtain required
operator verification, switch production to the canonical external root, and
enforce fail-closed movement authorization.

### User experience

1. rc.2 launches and acquires the application-wide lock.
2. A bootstrap migration window appears before the normal main window.
3. The current checkout legacy local is shown when present.
4. The operator may browse to a Desktop/external-drive backup folder or ZIP.
5. Candidate version, source path, machine ID, key coordinates, duplicate or
   conflict status, and preset-like warnings are shown.
6. The app automatically creates and verifies a migration backup.
7. The app stages and hash-verifies the canonical copy.
8. The operator verifies source identity and required physical calibrations.
9. Only then does App load Settings and construct MVC/hardware components.

If the operator cancels, source is ambiguous, or verification is incomplete,
the initial safe behavior is to exit without constructing the normal
hardware-capable application. A restricted calibration/recovery mode may be
added only if its hardware permissions and allowed commands are separately
specified and tested.

### Verification policy

- Copy verification is automatic.
- Machine/source verification is an explicit operator decision.
- Camera receives its own coordinate review and verification action.
- Preset-like configurations cannot use a blanket trust action.
- Unverified targets remain individually blocked.
- The verification record is bound to the exact coordinate values and config
  hash; changing values revokes it.
- The accepted list of locations requiring verification before normal startup
  is frozen during this milestone.

### Application integration requirements

- `App.main()` runs bootstrap before `get_machine_config_path("Settings.json")`.
- App and Model receive the same resolved canonical config root.
- Production config resolution cannot silently seed a missing canonical file.
- Controller rejects unverified named-location movement before queuing commands.
- Qualification/simulation composition remains isolated.
- Existing app-local single-instance behavior is preserved and tested from
  multiple checkouts; canonical transaction locking is added.

### Expected files touched

- `FreeRTOS-interface/App.py`.
- `FreeRTOS-interface/ApplicationComposition.py`.
- `FreeRTOS-interface/LocalConfig.py`.
- `FreeRTOS-interface/Model.py`.
- `FreeRTOS-interface/Controller.py`.
- A new bootstrap/migration dialog module; avoid expanding the main View when
  a small pre-construction dialog is sufficient.
- `FreeRTOS-interface/RegulatorProfiles.py` and other direct local-root callers
  identified by a fresh search.
- Startup, composition, Controller authorization, and migration UI tests.

### Tests

- Bootstrap precedes Settings and Model construction.
- No Machine/Controller is constructed on cancel or migration failure.
- Existing canonical store is reused from a second checkout without migration.
- Missing canonical and missing legacy configuration fail closed.
- Current checkout source and manually selected backup source both work.
- Exact copy plus unverified calibration cannot move.
- Controller rejects Camera even if the UI incorrectly enables it.
- Changed coordinate invalidates prior verification.
- App and Model paths are identical.
- Production cannot call the old silent seeding path.
- Simulation/test roots remain unaffected.

### Exit criteria

- Both source tags reach a verified external store through one migration path.
- A new checkout after migration uses the same external store.
- No failure path sends hardware commands or enables saved-location movement.
- The original legacy source and verified migration archive remain intact.

### Rollback

Before release, revert startup integration and continue using the untouched
legacy local source. Do not delete external migration artifacts. After fleet
deployment, use the Milestone 6 compatibility-export procedure rather than
merely switching app code back.

### Implementation record

- Not started.

### Validation record

- Not started.

## Milestone 4: Add transactional configuration history

Status: `planned`

### Objective

Make every safety-relevant configuration mutation durable, recoverable,
attributable, and reversible.

### Deliverables

- Central transactional configuration repository/service.
- Pending journal and startup reconciliation.
- Immutable audit events or append-only event log with equivalent atomicity.
- Full pre-change backups and restore references.
- Named-location, rack, plate, import, verification, restore, and rejection
  events.
- Human-readable history presentation or export sufficient for support.

### Named locations

Add/update/save becomes one transaction. The app does not modify the active
in-memory location and then ask separately whether persistence should happen.
Cancelled changes leave memory and disk unchanged.

### Rack calibration

Left and Right anchors are one before/after transaction with one result.

### Plate calibration

- Four temporary corners remain isolated while the dialog is active.
- Acceptance builds and validates a complete proposed `Plates.json` document.
- One transaction records all four old/new corners.
- Persistence completes before the new transform becomes active in memory.
- Cancellation records an optional cancellation event but changes no active
  data.

### Expected files touched

- New configuration transaction/audit module(s).
- `FreeRTOS-interface/Model.py` location, rack, and WellPlate persistence paths.
- `FreeRTOS-interface/Controller.py` mutation adapters.
- Relevant View dialogs for result/error presentation.
- New audit, recovery, location, rack, and plate transaction tests.

### Tests

- Successful named-location transaction.
- Cancelled location change.
- Save/backup/audit failure at every boundary.
- Pending-transaction reconciliation.
- Restore produces a new audit event rather than deleting history.
- Rack pair never partially commits.
- Four-corner plate commit is one event.
- Plate cancellation and failure leave prior transform/data active.
- Concurrent writer is rejected by lock.
- Changed target revokes verification until the transaction's verification
  requirements are satisfied.

### Exit criteria

- Every known mutation call site routes through the transaction service.
- A support operator can determine what changed, when, from what values, to
  what values, and by which workflow.
- Every committed change can be restored from a verified backup.
- No partial rack or plate calibration can become active.

### Rollback

Revert mutation adapters to legacy atomic writers only before rc.2 deployment.
Preserve generated audit/backups. After deployment, rollback must not discard
canonical history and requires a compatibility export.

### Implementation record

- Not started.

### Validation record

- Not started.

## Milestone 5: Add guarded location and calibration changes

Status: `planned`

### Objective

Prevent accidental or implausible edits through explicit previews,
preconditions, semantic validation, hard bounds, and stronger confirmation.

### Deliverables

- Old/proposed/delta preview for each coordinate.
- Fresh-telemetry, homed, idle, and queue-empty preconditions.
- Hard global travel-bound checks.
- Semantic Camera, rack, and plate validation.
- Configurable per-location/per-axis warning thresholds.
- Stronger confirmation and reason for large changes.
- Hard rejection for out-of-bound or invalid geometry.
- Audit events for accepted, cancelled, and rejected attempts.

### Policy distinctions

- Global travel bounds are hard limits.
- Qualified obstacle/exclusion geometry is a hard limit.
- Plate/rack geometric validity is a hard limit.
- Delta thresholds normally trigger stronger confirmation, not automatic
  rejection.
- No universal 5,000-step hard envelope is assumed.

### Threshold decision process

1. Collect current fleet values and normal calibration deltas without exposing
   private experiment content.
2. Define location classes and axes that need separate thresholds.
3. Propose warn, service-confirm, and reject behavior.
4. Test legacy valid calibrations against the proposal.
5. Freeze thresholds and rationale in the decision log.
6. Keep policy configurable and versioned.

### Expected files touched

- `FreeRTOS-interface/View.py` location and calibration dialogs.
- `FreeRTOS-interface/Controller.py` save preconditions and dispatch guard.
- `FreeRTOS-interface/Model.py` validation helpers or new pure policy module.
- Preset/config schema only if a reviewed policy requires it.
- UI, Controller, and pure validation-policy tests.

### Tests

- Exact before/after/delta display.
- Large Camera Y requires stronger confirmation.
- Ordinary qualified small change remains usable.
- Out-of-bounds value is rejected.
- Stale telemetry, not homed, moving, or queued commands reject capture.
- Invalid plate corner ordering/dimensions/transform reject commit.
- Invalid rack ordering/spacing rejects pair.
- Cancelled/rejected attempts are audited and change nothing.
- No UI bypass can defeat Controller/model validation.

### Exit criteria

- A substantial Camera change cannot be saved through a routine confirmation.
- Hard-invalid values cannot be persisted or dispatched.
- Thresholds are evidence-backed, documented, and tested.
- UI and Controller enforce consistent policy.

### Rollback

Threshold policies may be relaxed through a reviewed config/policy revision if
valid legacy calibrations are blocked. Hard machine bounds, transactional
writes, audit history, and unverified-target blocking remain.

### Implementation record

- Not started.

### Validation record

- Not started.

## Milestone 6: Protect future updates and controlled rollback

Status: `planned`

### Objective

Make configuration preservation a required updater contract for rc.2 and later,
and provide a verified support-guided bridge to legacy app versions.

### Future update preflight

Before updating, the rc.2 updater:

1. Acquires the machine-data/update lock and prevents config edits.
2. Resolves and records canonical path and machine identity.
3. Validates required configuration.
4. Creates and verifies a backup outside the checkout.
5. Records per-file hashes and safety-sensitive values.
6. Records current app version/SHA and expected target release.

### Future post-update verification

Before normal relaunch/use:

1. Resolve canonical path again.
2. Require the same machine identity and expected absolute path.
3. Require exact hashes if no schema migration was declared.
4. For an intentional migration, require semantic equality of machine-owned
   coordinates plus an explicit migration event.
5. Record verification results externally.
6. Enter restricted/recovery behavior if any check fails.

### Initial rc.6/rc.1 transition

The old updater cannot execute this new preflight. The initial transition is
protected by:

- Milestone 0 manual backup;
- preservation of ignored checkout-local data during in-place update;
- rc.2 first-start automatic backup before import;
- rc.2 fail-closed migration and verification.

### Rollback compatibility export

Before rc.2 changes the app revision to a legacy target:

1. Stop or lock all configuration mutation.
2. Back up canonical external and existing checkout-local data.
3. Validate legacy schema compatibility.
4. Stage canonical legacy-compatible JSON under checkout-local storage.
5. Hash-verify the staged copy.
6. Atomically activate the compatibility copy.
7. Record a rollback-export event externally.
8. Only then change app code and relaunch.

If any step fails, rollback stops before changing the Git revision. Continuous
dual-writing is prohibited.

After legacy operation, re-upgrade compares canonical and legacy hashes. If the
legacy app changed data, the operator must resolve the conflict explicitly.

Rollback remains support-guided until the complete path is qualified. Firmware
rollback/upgrade remains a separate paired deployment operation.

### Expected files touched

- `tools/update_and_restart.py`.
- App update/rollback UI adapters in Controller/View as required.
- External update-history integration.
- Updater, rollback, offline-bundle, and UI tests.
- Update and rollback runbooks.

### Tests

- Unchanged canonical data passes pre/post update.
- Path, machine ID, or hash mismatch fails closed.
- Backup failure prevents update.
- Intentional schema migration preserves semantic values and audits the change.
- New checkout after update resolves the same canonical data.
- Compatibility export preserves both sides and verifies hashes.
- Export failure prevents Git rollback.
- Legacy edit followed by re-upgrade produces a conflict.
- Offline and online update paths obey the same data contract.
- App/firmware pairing warning and deployment record are preserved.

### Exit criteria

- Future update cannot proceed without a verified config backup.
- Future update cannot silently select a different data root.
- Legacy rollback cannot proceed without a verified compatibility export.
- Re-upgrade cannot silently discard legacy-era changes.

### Rollback

If automated rollback cannot be qualified, disable normal UI rollback for rc.2
and retain a documented support-only process. Do not weaken update preservation
checks.

### Implementation record

- Not started.

### Validation record

- Not started.

## Milestone 7: Qualify, release, and stage deployment

Status: `planned`

### Objective

Prove the complete migration, safety, audit, update, rollback, and deployment
contract before tagging rc.2 and then stage it across both deployed source
versions.

### Source-tag migration matrix

| Source | Legacy layout | Config migration | Firmware operation |
| --- | --- | --- | --- |
| `v1.2.0-rc.6` | `<repo>/local` | Select/verify legacy or manual backup; copy to external canonical store | Deploy and verify rc.2-required v1.3 firmware |
| `v1.3.0-rc.1` | `<repo>/local` | Same migration path; preset-like Camera requires explicit review | Verify existing paired artifact or deploy rc.2-required artifact |
| New checkout after rc.2 migration | Canonical store already exists | Validate and reuse; no new import | No firmware conclusion from checkout alone |

### Required automated scenarios

- Exact rc.6 and rc.1 fixture layouts.
- Non-preset machine-specific Camera values.
- Camera-only preset match and full preset match.
- Desktop folder, external-drive folder, parent folder, direct local, and ZIP
  selection.
- Duplicate and conflicting candidates.
- Missing/malformed/partial data.
- Existing canonical data.
- New worktree and clone after migration.
- Permission, disk-full, lock, and interrupted-write failures.
- Verification cancellation and revocation.
- Named-location, rack-pair, and four-corner plate audit transactions.
- Guarded edit preconditions and threshold UI.
- Update pre/post preservation.
- Compatibility export, legacy edit, rollback, and re-upgrade conflict.
- Simulation isolation and no-hardware startup failure paths.

### Required validation commands

Focused commands will be finalized as tests are added. Minimum final gates:

```powershell
.\env\Scripts\python.exe -m pytest -q
.\env\Scripts\python.exe tools\validate_release_metadata.py
git diff --check
Get-ChildItem releases\*.json | ForEach-Object {
    Get-Content $_.FullName -Raw | ConvertFrom-Json | Out-Null
}
```

After creating the tag locally and before pushing:

```powershell
.\env\Scripts\python.exe tools\validate_release_metadata.py --check-tags
```

If any file under `firmware/` changes, read `firmware/AGENTS.md`, rebuild the
versioned binary, and run the required firmware checks. Configuration-only app
changes do not authorize a firmware source change.

### Release metadata

Before editing release metadata, re-read `docs/release_process.md`.

Expected lineage, subject to the current release index at release time:

- target version/tag: `v1.3.0-rc.2`;
- `previous_version`: `v1.3.0-rc.1`;
- `rollback_version`: current accepted stable release according to policy;
- `channel`: `release_candidate`;
- `requires_firmware`: retain an explicit v1.3 artifact requirement if rc.6
  machines can upgrade to rc.2, even when the binary is unchanged from rc.1.

`previous_version` records release lineage; it is not a migration whitelist.

### Controlled hardware qualification

1. Use a designated test machine with a preserved known-good config.
2. Disable automatic saved-location movement during migration.
3. Verify source/destination evidence and Camera values before enabling motion.
4. Verify app/firmware pairing.
5. Exercise only the approved low-risk calibration verification checklist.
6. Confirm no commands are dispatched for unverified targets.
7. Exercise audit and restore with non-hazardous test coordinates or a hardware
   simulator before any physical Camera approach.
8. Perform the approved Camera route verification with explicit rollback and
   stop conditions.

### Staged fleet rollout

1. Controlled test machine.
2. One representative `v1.2.0-rc.6` machine.
3. One representative `v1.3.0-rc.1` machine.
4. Review migration archives, audit events, firmware records, and operator
   feedback.
5. Pause rollout on any unexplained coordinate, path, identity, hash, or motion
   discrepancy.
6. Expand to the remaining fleet only after both source paths are accepted.

### Exit criteria

- Every automated and release gate passes.
- Both deployed source-tag paths pass controlled migration.
- Hardware qualification demonstrates fail-closed behavior and approved Camera
  verification.
- Rollback or support-only recovery is documented and rehearsed.
- Release notes explain external data, migration, verification, backups, and
  firmware pairing.
- No known safety-critical issue remains open.

### Rollback

Do not promote or push the release tag if qualification fails. Preserve all
evidence, fix on a new commit, and repeat validation. Never move a pushed tag.
For a deployed pilot, use the qualified support-guided app/config/firmware
rollback procedure.

### Expected files touched

- `VERSION`.
- `CHANGELOG.md`.
- `releases/latest.json`.
- New `releases/v1.3.0-rc.2.json`.
- Operator and support runbooks.
- Tests/evidence generated by prior milestones.

### Implementation record

- Not started.

### Validation record

- Not started.

## End-to-end migration flows

### rc.6 to rc.2

```text
Operator closes app and disables motion
-> copies active local + VERSION to Desktop and external drive
-> deployment records source and firmware status
-> old updater installs rc.2, preferably without uncontrolled relaunch/motion
-> rc.2 bootstrap starts before normal app
-> current legacy local or manual backup selected
-> automatic migration archive created and verified
-> canonical copy staged and hash-verified
-> source/machine/required calibration verification completed
-> paired v1.3 firmware deployed and verified operationally
-> normal app construction allowed
-> no unverified target may move
```

### rc.1 to rc.2

```text
Operator closes app and disables motion
-> copies active local + VERSION to Desktop and external drive
-> old updater installs rc.2
-> rc.2 bootstrap selects legacy or manual backup
-> preset-like and Camera values displayed prominently
-> automatic backup and copy verification complete
-> source and required calibration verification complete
-> existing v1.3 firmware provenance confirmed or artifact redeployed
-> normal app construction allowed
```

### First new checkout after successful migration

```text
new checkout starts
-> app-global lock prevents a second active app
-> external active-machine pointer resolves canonical store
-> canonical metadata/config/audit validate
-> no legacy import and no preset seeding occur
-> normal app starts using the same machine data
```

### Missing external data after successful migration

```text
startup cannot resolve canonical data
-> legacy/preset is not silently selected
-> recovery UI offers verified backups/candidates
-> no hardware-capable normal app and no saved-location movement
```

### Support-guided rollback

```text
rc.2 updater locks config
-> backs up canonical and legacy local
-> verifies legacy-compatible schema
-> stages canonical data into legacy local
-> verifies hashes and records rollback export
-> only then changes app revision
-> deployment pairs target app with target firmware
-> older app uses exported local
```

### Re-upgrade after legacy edits

```text
rc.2 sees existing canonical plus changed legacy local
-> compares hashes/semantics
-> records conflict
-> operator selects source with before/after preview and reason
-> backup, import, verification, and audit repeat
-> no last-write-wins behavior
```

## Test strategy

### Unit tests

- Path resolution and containment.
- Identity and metadata schemas.
- Hash manifests and archive verification.
- Candidate normalization and preset detection.
- State transitions and idempotence.
- Pure validation and threshold policies.
- Audit event schemas and semantic deltas.

### Persistence fault injection

- Open/read/parse failures.
- Directory creation and permission failures.
- Disk-full/short-write simulation.
- Flush and `fsync` failures.
- Atomic replace failure.
- Audit commit failure.
- Crash/restart at every transaction boundary.
- Corrupt or orphaned pending journal.

### MVC integration tests

- Bootstrap occurs before configuration and hardware construction.
- One canonical root reaches App and Model.
- UI cancellation dispatches nothing.
- Controller independently blocks unverified movement.
- Named-location, rack, and plate writes route through the transaction service.
- UI previews match the exact committed values.

### Updater integration tests

- Online and offline update preservation.
- Old-source first-launch behavior.
- New-source pre/post hashes.
- Relaunch result path and restricted failure behavior.
- Rollback compatibility export and re-upgrade divergence.

### Virtual/no-hardware workflows

- rc.6/rc.1 fixture migrations.
- Multiple checkout/worktree resolution.
- Full first-launch wizard journeys.
- Audit browse/restore journeys.
- Guarded-change acceptance/cancel/rejection journeys.
- No command queues on unverified/failure journeys.

### Hardware qualification

Hardware use is last. It requires:

- known app/firmware pairing;
- known machine identity;
- preserved configuration and rollback artifact;
- operator-present stop capability;
- explicit approved route/checklist;
- no reliance on an unmodeled obstacle file for collision safety.

## Risk register

| Risk | Impact | Mitigation | Gate |
| --- | --- | --- | --- |
| User copies wrong checkout local | Wrong machine config imported | Preserve all candidates when uncertain; show source/version/coordinates; require source verification | M0/M3 |
| Legacy file was already seeded from preset | Stale coordinates become canonical | Preset-like detection; per-location verification; Camera-specific review | M2/M3 |
| External path permissions fail | App cannot persist or audit | Resolve permissions in contract; preflight writable/fsync/replace tests | M1/M2 |
| Two checkouts run concurrently | Conflicting writes/hardware control | Preserve app-global lock; add canonical transaction lock; cross-user tests | M1/M3 |
| Interrupted migration | Partial canonical store | Staging, journals, idempotent recovery, fail closed | M2 |
| Audit succeeds but config fails, or inverse | History diverges from active state | Transaction journal and startup reconciliation | M4 |
| Plate/rack partially saves | Invalid geometry becomes active | One multi-entity transaction; memory updated after disk commit | M4 |
| Operators click through warning | Accidental large move remains possible | Explicit deltas, typed/strong confirmation, reason, per-location verification | M5 |
| Arbitrary threshold blocks valid calibration | Operational interruption | Fleet data, configurable versioned policy, warning vs hard-bound separation | M5 |
| Existing obstacle config gives false confidence | Collision despite in-range target | State limits honestly; qualify physical exclusion geometry separately | M5/M7 |
| Old updater lacks new preflight | Initial migration lacks pre-update software backup | Manual M0 copies plus first-start automatic archive | M0/M3 |
| Rollback app cannot see canonical store | Old app loads stale local | Verified compatibility export; support-guided rollback | M6 |
| Firmware/app mismatch | Incorrect motion behavior | Paired deployment record; explicit release manifest; controlled rollout | M7 |
| Canonical external directory is deleted | Loss of active configuration | Multiple verified backups; fail closed; recovery UI | M2/M6 |
| Removable backup chosen as live root | Data disappears when drive removed | Copy into approved canonical base; never operate directly from candidate | M1/M3 |
| Full backup contains sensitive/large data | Privacy/storage burden | No automatic upload; curated support export later; document ownership | M0/M2 |

## Decision log

### Accepted decisions

| Date | Decision | Rationale |
| --- | --- | --- |
| 2026-08-19 | Store authoritative machine configuration outside Git checkouts and worktrees | Checkout-local ignored data is not stable across clones/worktrees |
| 2026-08-19 | Keep machine data untracked | Per-machine calibration must not be distributed as common source content |
| 2026-08-19 | Users copy full `local/` plus `VERSION`; software calculates hashes | Simple operator workflow with exact automated evidence |
| 2026-08-19 | Run migration before normal MVC/hardware construction | Prevent configuration failure from reaching motion-capable state |
| 2026-08-19 | Separate copy, source, and calibration verification | Exact bytes do not prove physical correctness |
| 2026-08-19 | Treat presets as unverified drafts | Generic starter values cannot safely authorize machine motion |
| 2026-08-19 | Keep legacy JSON shapes and use sidecars | Reduces migration risk and enables controlled rollback export |
| 2026-08-19 | Audit rack as a pair and plate as one four-corner transaction | Prevent partial calibration and preserve meaningful history |
| 2026-08-19 | Separate hard bounds from delta warnings | A universal step delta is not a valid collision model |
| 2026-08-19 | Do not continuously dual-write canonical and legacy locations | Two live sources create ambiguity and conflict risk |
| 2026-08-19 | Keep rollback support-guided until fully qualified | Legacy apps cannot read the external store without a compatibility export |
| 2026-08-19 | Ship all safety milestones together in rc.2 | Partial rollout would leave known failure modes open |

### Open decisions

| Decision | Recommended direction | Resolve by | Status |
| --- | --- | --- | --- |
| Windows canonical base path | System-wide app data if permissions/install support are reliable; otherwise explicit per-user stable path | M1 | Open |
| Pi/Linux canonical base path | Stable service/deployment-user data path outside repo | M1 | Open |
| Machine identity source | Existing assigned identity when valid; operator assignment otherwise; do not infer solely from port/hostname | M1 | Open |
| Multi-machine host behavior | External active-machine pointer plus explicit selection | M1 | Open |
| Audit storage format | Immutable per-event JSON plus pending journal, or JSONL with equivalent durability/recovery | M1/M4 | Open |
| History/backup retention | No automatic deletion in rc.2 unless a separately reviewed bounded policy is required | M4 | Open |
| Required per-location verification list | Camera at minimum; evaluate Loading, Plate, rack anchors, Balance, and other automatic targets | M3 | Open |
| Existing trusted-file bulk verification | Allow only with explicit machine/source attestation; never for preset-like data; Camera remains explicit | M3 | Open |
| Failure UI | Exit before normal app is safest; restricted recovery/calibration mode only with separate command permissions | M3 | Open |
| Camera/rack/plate delta thresholds | Derive from fleet data and physical geometry; no arbitrary universal threshold | M5 | Open |
| Physical exclusion geometry | Measure and qualify separately; do not infer from current empty obstacle list | M5/M7 | Open |
| rc.2 rollback target | Follow release-process current stable policy at release time | M7 | Open |
| rc.2 firmware artifact | Retain qualified rc.1 artifact if unchanged, otherwise follow firmware release policy and full checks | M7 | Open |

## Findings log

| Date | Milestone | Finding | Effect on plan |
| --- | --- | --- | --- |
| 2026-08-18 | Investigation | A missing checkout-local file copies the whole tracked preset; there is no separate Camera fallback | Preset seeding must fail closed and remain unverified |
| 2026-08-18 | Investigation | Camera preset remained unchanged while other locations were refreshed later | Add preset-like/Camera-specific migration warning |
| 2026-08-18 | Investigation | Normal updater preserves local in-place, but new checkout/root selects different local | Move canonical config outside checkout and verify absolute root |
| 2026-08-18 | Investigation | No background Camera-specific writer was found | Audit explicit mutation, rack, plate, import, and restore paths |
| 2026-08-18 | Investigation | v1.3 motion executor changed substantially, while final tagged HIL passed | Keep firmware provenance as separate conditional root cause and release gate |
| 2026-08-19 | Planning | Users can reliably copy full local but should not calculate hashes manually | Make hashes and archive verification an rc.2 responsibility |
| 2026-08-19 | Planning | External shared data creates a cross-checkout writer boundary | Preserve app-global lock and add canonical transaction lock |
| 2026-08-19 | Planning | Plate calibration has four temporary corners and one acceptance action | Audit and commit it as one four-corner transaction |
| 2026-08-19 | M1 planning | Existing direct-local machine data also includes droplet-imager optics and regulator-optimization data outside the central LocalConfig list | Classify before Milestone 3; do not expand inert Milestone 1 into production cutover |
| 2026-08-19 | M1 planning | The current application-wide lock already uses Qt application-local storage | Use the same checkout-independent path convention and separately contract the canonical configuration lock |

Add findings here as work proceeds. Do not rewrite prior findings to hide an
earlier assumption; add a correction with date and evidence.

## Progress log

| Date | Milestone | Update | Commit/evidence | Next action |
| --- | --- | --- | --- | --- |
| 2026-08-19 | Plan | Initial comprehensive plan created | This document | Review and resolve Milestone 1 path/identity decisions |
| 2026-08-19 | 0 | Target Pi `local/` and `VERSION` recovery copies completed | Operator attestation | Repeat per-machine gate before each additional rollout |
| 2026-08-19 | 1 | Concrete inert contract implementation plan created | `docs/machine_data_migration_milestone_1_implementation_plan.md` | Review frozen M1 decisions, then begin tests-first implementation |
| 2026-08-19 | 1 | Tests-first inert contract implementation started | Working tree | Add path, identity, active-machine, and LocalConfig contract tests |
| 2026-08-19 | 1 | Inert contract implementation and validation completed | 101 focused tests and 5,100 full-suite tests passed on `update_bug_fix` | Review and create the dedicated Milestone 1 commit before marking verified |

## Definition of done for v1.3.0-rc.2

The work is complete only when:

1. Every rollout machine has a Milestone 0 recovery backup.
2. Production resolves a stable external machine-data root independent of
   checkout/worktree.
3. rc.6 and rc.1 migrations are deterministic, verified, and fail closed.
4. Preset or missing data cannot authorize saved-location motion.
5. Camera and all required safety-sensitive locations have explicit
   verification state bound to exact values.
6. Controller rejects unverified targets independently of UI state.
7. Named locations, rack pairs, and plate four-corner calibration use
   transactional persistence, backup, and audit.
8. Large changes show exact deltas and require the approved stronger
   confirmation; hard-invalid states are rejected.
9. Future updater pre/post preservation and support-guided rollback export pass
   automated tests.
10. Full Python validation and release metadata validation pass.
11. Required firmware artifact and deployment pairing are documented and
    verified for both source cohorts.
12. One controlled rc.6 and one controlled rc.1 deployment complete without
    unexplained configuration or movement discrepancies.
13. Risks, open decisions, findings, commits, and validation evidence are
    current in this document.
14. Release notes and operator/support runbooks are complete.

## Document change log

| Date | Change |
| --- | --- |
| 2026-08-19 | Created the living Milestones 0-7 migration, audit, safety, updater, rollback, qualification, and rollout plan for `v1.3.0-rc.2`. |
| 2026-08-19 | Marked Milestone 0 verified from the target Pi backup attestation and linked the concrete Milestone 1 implementation plan. |
| 2026-08-19 | Recorded the completed inert Milestone 1 implementation and focused/full validation; milestone remains implementation-complete pending its dedicated commit. |
