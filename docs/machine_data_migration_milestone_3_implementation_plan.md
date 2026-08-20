# Machine Data Migration Milestone 3: Bootstrap, Verification, and Activation Plan

Status: `verified`

Prepared: 2026-08-19

Parent plan:
`docs/machine_data_migration_and_location_safety_plan.md`

Depends on:

- Milestone 1 commit `9b882141` (`verified`)
- Milestone 2 commit `157db800` (`verified`)

Target release: `v1.3.0-rc.2`

## Outcome

Milestone 3 will connect the external machine-data system to production for the
first time. It will run a hardware-free bootstrap before Settings, MVC, camera,
serial, balance, or machine construction; guide the operator through candidate
selection and identity/source/calibration verification; atomically activate a
fully verified canonical store; pass one exact set of canonical roots through
application composition; and make Controller reject unverified configuration-
derived movement before any command is queued.

At the end of Milestone 3:

- both `v1.2.0-rc.6` and `v1.3.0-rc.1` deployments use the same first-start
  workflow;
- a Desktop/external backup can be selected explicitly;
- a subsequent checkout for the same OS account resolves the same active
  machine without remigration;
- production never seeds a missing canonical config from tracked presets;
- copy verification, physical-machine/source attestation, and target
  verification remain separate evidence;
- Camera has a mandatory standalone verification decision;
- verification is bound to exact values and source-file hashes;
- the immutable Milestone 2 `copied_unverified` receipt and tree manifest
  remain valid provenance rather than being rewritten during activation;
- no `override`, `manual`, `ignore_safe_height`, UI bug, or direct workflow can
  bypass the Controller authorization decision for a saved target;
- cancel, conflict, corruption, incomplete verification, and lock failure exit
  before hardware-capable application construction.

Milestone 3 does not add configuration edit history or guarded edit previews.
Those remain Milestones 4 and 5. It does, however, guarantee that a changed or
new target no longer matches its verification evidence and is therefore
blocked.

## Safety boundary and call paths

### Current production path

```text
QApplication
-> application identity
-> application-wide lock
-> splash
-> import ApplicationComposition
-> get_machine_config_path("Settings.json")
   -> may seed missing <repo>/local file from Presets
-> load_settings() with fallback defaults
-> production_dependencies() with None roots
-> build Model
   -> config reads/seeding
   -> CalibrationMemory initialization
   -> camera-model initialization
-> build Machine / Controller / View
```

The current unsafe boundary is that Settings and configuration are selected
before any external-store, source, or calibration verification exists.

### Required Milestone 3 startup path

```text
QApplication
-> configure stable application identity
-> acquire application-wide lock
-> apply app icon/theme needed by bootstrap UI
-> MachineDataBootstrap.inspect()
   -> resolve external base
   -> inspect active pointer/canonical store
   -> validate ready store OR return a hardware-free workflow state
-> MachineDataBootstrapDialog when action is required
   -> select/compare candidate
   -> assign or confirm machine identity
   -> acquire base UUID migration lock
   -> create/reuse a contained activation workspace
   -> run verified backup and copied_unverified import, or strictly reconcile it
   -> validate the exact immutable M2 published baseline
   -> record source attestation
   -> record exact target verification
   -> acquire and retain per-machine configuration lock
   -> verify activation preconditions and M2 baseline again
   -> write/reopen verification and activation receipts
   -> write active_machine.json last
-> return AuthorizedMachineContext
-> strict-load Settings from the authorized config root
-> derive HardwareProfile
-> create production dependencies from AuthorizedMachineContext
-> build Model, Machine, Controller, View
-> show main window
```

The normal splash should appear only after bootstrap authorization, or remain
clearly subordinate to the bootstrap dialog. The migration/verification window
is the first actionable window on first start; no normal MainWindow exists
behind it.

### Required named/derived movement path

```text
View or workflow requests logical target
-> Controller resolves named/plate/rack-derived values
-> SavedTargetAuthorizer evaluates:
   machine UUID
   target key and exact current values
   verification state/value fingerprint
   bound source-file raw hash
   current source-file raw hash
   route/derived-target context
-> reject and emit reason OR return authorization decision
-> only an allowed decision may reach route planning
-> Controller queues safe-Z/dogleg/final commands
-> Machine_FreeRTOS
```

Authorization must happen before the first intermediate safe-Z, balance, rack,
plate dogleg, or final movement command. Existing collision/path checks remain
additional gates and are not replaced.

## Findings frozen into the plan

1. `App.main()` currently reads/seeds Settings before production composition.
2. `load_settings()` silently falls back to the current hardware profile on
   missing, malformed, or unreadable Settings. Canonical production must use a
   strict loader instead.
3. `Model` currently calls LocalConfig seeding helpers even when an explicit
   root is supplied. A canonical no-seed load policy is required without
   changing simulation's explicit fixture seeding behavior.
4. `CalibrationMemoryStore.ensure_initialized()` creates missing directories
   and seed files. Canonical activation therefore must require the migrated
   CalibrationMemory baseline and prevent silent first-start replacement.
5. `DropletCameraModel` reads and writes
   `<repo>/local/droplet_imager_optics.json` through a class constant.
6. Controller qualification identity and regulator-optimization output point
   directly at `<repo>/local`; `QualificationRunWorker` also has two
   checkout-local identity fallbacks.
7. `RegulatorProfiles.json` already follows Model's explicit config root when
   supplied; its legacy default can remain for pre-M3/test compatibility.
8. `Controller.move_to_location()` resolves configuration-derived targets and
   may queue intermediate commands before its final absolute target. The new
   gate belongs immediately after target resolution/normalization and before
   any route command.
9. Plate-well, rack-slot, camera-search, calibration, and some View workflows
   call absolute movement primitives directly. A call-site inventory and
   explicit derived-target authorization contract are required; guarding only
   one button is insufficient.
10. `override=True`, `manual=True`, and `ignore_safe_height=True` currently
    affect collision/route behavior. None may bypass verification.
11. HardwareProfile can be derived from strictly parsed canonical Settings
    without constructing hardware.
12. The current application-wide lock is acquired before heavy production
    imports and must remain the outermost process lock.
13. Milestone 2 commit `157db800` intentionally accepts only
    `copied_unverified` receipts and its exact migration-tree verifier rejects
    added files. Milestone 3 therefore needs separate activation evidence and
    a reviewed phase-aware baseline verifier; it must not mutate the M2 proof.
14. A successful M2 publication removes its migration workspace/journal. M3
    normal bootstrap and restart must recover from the published receipt,
    candidate evidence, tree manifest, and verified backup rather than assuming
    that workspace evidence still exists.

## Frozen Milestone 3 decisions

### 1. Bootstrap is mandatory production authority

Production composition receives an `AuthorizedMachineContext` returned only
after bootstrap validation. `production_dependencies()` no longer has a
zero-argument production path that silently produces `None` roots.

The context is immutable and includes:

- base and per-machine `MachineDataPaths`;
- canonical machine identity;
- exact active-machine record;
- immutable copied-unverified migration receipt and tree-manifest evidence;
- separate source/target verification and activation receipt evidence;
- parsed verification snapshot;
- strict Settings payload and hash;
- config and CalibrationMemory roots;
- canonical machine-calibration paths;
- a saved-target authorizer;
- an owned configuration-lock context that remains alive through app runtime.

Tests can construct a context only through an explicit validated test factory;
there is no implicit allow-all production fallback.

### 2. Application, migration, and configuration locks have one order

Lock order is always:

```text
application-wide instance lock
-> base UUID migration lock, only while bootstrap migrates/activates
-> per-machine configuration lock
```

For a ready existing canonical store, bootstrap acquires the per-machine
configuration lock before final validation and retains it for the complete
application lifetime. For first migration, bootstrap holds the migration lock,
publishes/verifies the exact M2 baseline, acquires the configuration lock,
writes and verifies M3 sidecars, activates, and then releases the migration
lock. The configuration-lock file is an explicitly permitted ephemeral M3
phase path; it is never folded into or used to rewrite the M2 tree manifest.

The retained configuration-lock token is passed to later transaction work; an
in-process Milestone 4 service must reuse ownership rather than deadlock by
reacquiring its own lock. External updater/support/other-checkout writers are
rejected while the app owns it.

### 3. Existing canonical state never falls back to legacy automatically

If `active_machine.json` points to a structurally valid, hash-consistent,
verified store, bootstrap returns it without showing migration UI.

If an active pointer exists but its identity, receipt, verification, files, or
hashes are missing/malformed/mismatched, bootstrap enters `recovery_required`.
It does not silently choose checkout-local data, presets, a newer timestamp, or
another machine directory.

If no active pointer exists:

- one exact `copied_unverified` migration may be offered for explicit resume;
- multiple canonical machine roots require explicit selection;
- no canonical root begins the candidate workflow;
- no directory is auto-activated merely because it is the only one present.

Published-store inspection first validates every file listed in the immutable
M2 migration-tree manifest. Before M3 artifacts exist, any extra file is fatal.
After activation has begun, only the exact versioned M3 sidecars and the
configuration-lock file are allowed; arbitrary extras remain fatal. The M2
receipt must still parse as `copied_unverified` with all M2 verification flags
false.

### 4. Candidate selection remains explicit

The current checkout's direct `local/` is inspected automatically only as a
visible candidate. External folders/ZIPs appear only after the operator uses
Browse. The UI may preselect a row for convenience but cannot enable Continue
until the operator explicitly confirms it.

An operator-selected Desktop/external folder or ZIP is candidate input. The
M2-generated backup is not candidate input: its layout is
`manifest.json` plus `source/local/...` and it is reopened only through
`verify_backup_archive()`. Resume from an already-published M2 tree uses its
receipt, candidate evidence, migration-tree manifest, and installed verified
backup; it does not re-normalize the generated backup as a legacy candidate.

For every candidate show:

- source label, type, normalized path, and VERSION evidence;
- machine identity status;
- required/migratable fingerprints;
- all saved named-location coordinates with Camera prominent;
- calibrated plate corner values;
- CalibrationMemory and machine-calibration status;
- historical preset and camera-only matches;
- duplicates, conflicts, unclassified paths, warnings, and fatal issues.

Conflicting candidates require an explicit selected source and nonempty reason.
No timestamp or version is a winner rule.

### 5. Identity assignment occurs before canonical import

If the selected candidate has a valid assigned identity, display its machine ID
and UUID and require the operator to confirm that it belongs to the physical
printer.

If identity is missing or `LC-UNASSIGNED`, the operator must enter the approved
machine display ID and confirm assignment. The service generates a UUID exactly
once, writes a durable assignment record in the migration workspace, and reuses
it after restart. Empty IDs and `LC-UNASSIGNED` are rejected. Hostname, serial
port, MCU ID, or USB enumeration may be recorded as supporting evidence but
never supplies the identity by itself.

The operator must type the displayed machine ID exactly on the source-
attestation page. A candidate assigned to a different UUID/ID is a conflict,
not an editable convenience.

### 6. Bootstrap UI is hardware-free and modal

Use a separate `MachineDataBootstrapDialog.py` rather than adding first-start
logic to the main View. A top-level modal dialog with a testable stacked-page
controller is preferred over constructing MainWindow early.

Suggested pages:

1. **System state** — new migration, resume, ready, or recovery reason.
2. **Choose source** — current checkout and explicitly browsed candidates.
3. **Machine identity** — confirm assigned identity or perform one assignment.
4. **Compare and attest source** — hashes, versions, coordinates, conflicts,
   preset warnings, typed machine-ID confirmation, and reason.
5. **Backup and copy** — progress for verified backup and canonical staging.
6. **Verify targets** — exact locations, rack pair, and plate corners.
7. **Activation review** — all gates, resulting external path, backup, and
   remaining restrictions.
8. **Result** — active/exit/recovery detail.

Long archive/migration work runs in a Qt worker thread that invokes the inert M2
core. Cancel requests are cooperative between durability checkpoints. The UI
must never terminate a writer thread, close while a write is unresolved, or
claim cancellation before the engine returns a reconciled state.

An exact verified M2 stage or published target may resume. A partial stage,
hash mismatch, conflicting target, or inconsistent journal remains preserved
and produces `recovery_required`; the dialog offers diagnostics/support exit,
not delete-and-rebuild. A normally completed publication has no M2 workspace,
which is expected rather than an error.

### 7. Copy, source, and target verification are separate

The layers are:

1. **Copy verification** — automatic M2 archive/stage hashes.
2. **Machine/source verification** — operator confirms the selected source
   belongs to the displayed physical machine and records identity/reason.
3. **Target verification** — exact saved values receive an allowed method.

No layer implies another. Copy success cannot make a location safe. Source
attestation cannot erase preset warnings. Target checks cannot compensate for a
hash mismatch or identity conflict.

### 8. Activation requires complete current target coverage

Before first activation, verify:

- every named location present in `Locations.json`, individually;
- the full Left/Right rack calibration as one aggregate target;
- every plate with a nonempty four-corner calibration, as one aggregate target
  per plate;
- the default plate must have a complete verified calibration;
- lowercase/case-folded location names must be unique;
- `camera` must exist and be verified when the resolved hardware profile has a
  droplet camera.

Empty/unconfigured non-default plate calibration entries remain unavailable and
do not block activation. A missing rack anchor, partial plate, or required
Camera blocks activation. Verifying all existing named locations keeps the
initial policy understandable and prevents an overlooked automatic name from
becoming a gap.

After activation, a newly added/changed location, rack pair, or plate no longer
matches the recorded value/hash and is blocked until a later guarded workflow
grants new verification.

### 9. Camera always has stronger confirmation

Camera is never included in a bulk action. Its row always displays:

- exact X/Y/Z values;
- the selected source and source version;
- any other candidate's Camera values and deltas;
- historical preset Camera values and deltas;
- raw `Locations.json` hash and semantic target fingerprint;
- verification method and operator identity.

For a Camera that does not match a known preset, the operator may explicitly
choose `verified_from_trusted_existing_calibration` only after source
attestation and must type the displayed Camera Y value as confirmation.

If Camera matches any historical preset, trusted-source/bulk verification is
not allowed. It requires `verified_against_service_record` with a nonempty
independent record reference and explicit X/Y/Z confirmation, or a future
`verified_by_controlled_calibration` workflow. This preconstruction milestone
does not move the machine to prove Camera. Without independent evidence, the
safe outcome is exit before hardware construction.

### 10. Preset-like targets cannot use blanket trust

A bulk `verified_from_trusted_existing_calibration` action is offered only when:

- the source identity is assigned/confirmed;
- source attestation is complete;
- candidate conflict selection/reason is complete;
- the candidate is not fully preset-like;
- each included target does not itself match a historical preset;
- copy/stage hashes are verified.

Camera is excluded regardless. Any preset-matching target requires an
individual independent-service-record method or remains unverified. The UI
must not provide a generic “verify all anyway” override.

### 11. Verification methods and states are versioned

Initial target states:

```text
unverified
verified_from_trusted_existing_calibration
verified_against_service_record
verified_by_controlled_calibration
revoked
```

The preconstruction dialog may grant only the first two verified states.
`verified_by_controlled_calibration` is reserved for a future separately
authorized workflow and can be parsed but not created by this UI.

Each verification contains who, when, method, source migration ID, exact target
value, semantic target hash, containing file raw hash, machine UUID, app
version/commit, preset flags, notes/reason, and service-record reference when
required.

### 12. Verification record is an exact snapshot, not a mutable flag

`metadata/verification.json` uses schema
`labcraft.machine_verification`, version 1. It includes:

- machine ID/UUID;
- policy schema/version;
- migration receipt ID/hash;
- source attestation;
- raw hashes of all required config files;
- overall required/migratable fingerprints;
- target records keyed by stable logical identifiers;
- creation/update timestamp and app version/commit;
- activation readiness derived from the exact snapshot.

Logical keys:

```text
location:<casefolded-name>
rack:primary
plate:<casefolded-plate-name>
```

The rack value contains both Left and Right anchor objects. A plate value
contains all four corners in fixed order. A location value contains X/Y/Z.
Serializers canonicalize ordering but preserve display names separately.

No boolean `verified=true` without bound values is accepted. Unknown schema,
method, target kind, duplicate key, illegal state, wrong UUID, or non-UTC time
fails closed.

### 13. Verification and activation are durable and ordered

Under migration and configuration lock ownership:

1. Revalidate the immutable M2 receipt, candidate evidence, migration-tree
   manifest, copied canonical bytes, and installed verified backup.
2. Record the baseline manifest hash and M2 receipt hash; strict-load all
   config and calibration evidence.
3. Build the complete verification record and activation receipt in memory.
4. Validate all target, identity, ownership, and durability requirements.
5. Atomically write, sync, reopen, and hash `verification.json`.
6. Atomically write, sync, reopen, and hash `activation_receipt.json`; it binds
   the M2 receipt hash, baseline-manifest hash, verification hash, UUID,
   migration/activation IDs, app build, ownership-policy version, and recorded
   filesystem durability capability.
7. Revalidate the immutable baseline plus the exact allowed M3 sidecars. Never
   rewrite the M2 receipt or migration-tree manifest.
8. Atomically write, sync, and reopen `active_machine.json` last.
9. Revalidate the pointer, identity, immutable M2 evidence, verification,
   activation receipt, allowed tree inventory, and roots.
10. Clean only a proven contained M3 activation workspace, return
    `AuthorizedMachineContext`, and retain the configuration lock.

File data and containing directories are synced where the platform supports
it. If directory sync is unavailable (including the recorded Windows M2
capability), the activation receipt records that limitation. The UI must show
it and Milestone 7 must qualify the exact platform behavior; code must not
claim a directory-sync guarantee that the platform did not provide.

On restart:

- verification plus activation receipt complete but no pointer resumes pointer
  creation after review;
- pointer present with a valid activation receipt is revalidated idempotently;
- pointer present before complete evidence is `recovery_required`;
- no step deletes or overwrites a conflicting canonical tree.

### 14. Keep M2 provenance immutable and add activation evidence

`metadata/migration_receipt.json` remains schema
`labcraft.migration_receipt` version 1, state `copied_unverified`, with
`source_verified`, `calibration_verified`, and `active` false. M3 does not add
states to that schema or overwrite the file.

M3 adds immutable `metadata/activation_receipt.json` using schema
`labcraft.activation_receipt`, version 1. Its final state is
`ready_for_activation`; the separately reopened base-level active pointer is
the evidence that the machine became active. The receipt contains at least:

- activation and migration IDs plus machine ID/UUID;
- raw SHA-256 of the M2 migration receipt and migration-tree manifest;
- raw SHA-256 of `verification.json` and the verified backup;
- required/migratable fingerprints and ownership-policy version;
- verification coverage result and Camera policy result;
- app version/commit, UTC creation time, and filesystem durability capability.

Mutable progress belongs only in a contained base-level activation journal:

```text
<base>/activation_work/<machine_uuid>/<activation_id>/journal.json
```

The journal is never an activation authority. It uses forward-only states such
as `identity_assigned`, `migration_published`, `verification_written`,
`activation_receipt_written`, and `pointer_written`. Bootstrap revalidates the
referenced immutable artifact at every transition and may clean the workspace
only after the active pointer and all bound evidence reopen successfully.

M2 gains narrowly scoped public, read-only parsers/verifiers for its published
receipt, candidate evidence, backup, and baseline tree. The phase verifier has
fixed allowed inventories (`copied_unverified`, `activation_staged`, `active`)
rather than accepting an arbitrary caller-provided ignore list. M3 must not
call M2 private helpers or weaken M2's exact default verification.

M3 writes `labcraft.active_machine` version 2 so the pointer binds the exact
activation instead of identifying only a UUID. In addition to the M1 fields it
contains `activation_id`, `migration_id`, and
`activation_receipt_sha256`. Version 1 can remain readable for diagnostics,
but cannot authorize production because no shipped M1/M2 path wrote an active
pointer. A v1 pointer therefore enters `recovery_required` rather than being
silently upgraded or falling back to legacy data.

### 15. Canonical production is no-seed and strict

LocalConfig gains read-only helpers that require existing canonical files and
never copy from Presets. Legacy default helpers retain their existing behavior
only for legacy/test compatibility.

Application roots carry an explicit load policy:

```text
legacy_or_simulation_seed_allowed
canonical_existing_only
```

Canonical Model construction:

- fails if any required config disappears or changes after bootstrap;
- does not call a seeding path;
- uses strict JSON loaders rather than swallowing corruption into `{}`;
- requires the migrated CalibrationMemory baseline and passes an existing-only
  initialization policy;
- retains normal ability to create new runtime CalibrationMemory runs/indices
  after initialization;
- receives the same strict Settings payload/hash used by App.

Simulation remains explicitly rooted and may seed its isolated fixtures. It
never reads the production active pointer or verification record.

### 16. All active machine calibration paths become external

Verified Milestone 2 commit `157db800` copies known data into:

```text
<machine_root>/calibration/droplet_imager_optics.json
<machine_root>/calibration/regulator_optimization/
```

Milestone 3 injects those paths:

- `DropletCameraModel` accepts an instance optics-config path instead of using
  the checkout-local class constant in production;
- Controller qualification identity resolves to canonical
  `metadata/machine_identity.json`;
- `QualificationRunWorker` receives that canonical identity path explicitly in
  production and cannot use its checkout-local fallback;
- Controller regulator-calibration output resolves to canonical
  `calibration/regulator_optimization/`;
- View displays the injected camera path through the model getter;
- standalone stream-analysis code continues to accept an explicit
  `config_path`; no Git checkout default is treated as canonical by App.

Missing optional optics data is recorded and the existing imaging default may
be used only with a visible verification warning; it does not change Camera
location verification. Regulator optimization history may be absent without
blocking activation because active RegulatorProfiles are one of the five
mandatory config files.

### 17. Controller owns the final saved-target gate

Add a pure `SavedTargetAuthorizer` constructed from the verified snapshot.
Controller asks it before queueing any configuration-derived route.

The authorization request contains:

- machine UUID;
- logical target key/kind/name;
- exact base and final coordinates;
- offsets and derived-source context;
- current config-file raw hash;
- rack/plate aggregate values when applicable;
- workflow label;
- manual/override/ignore-safe-height flags for diagnostics only.

The authorizer returns an immutable allow/deny decision with a reason code. A
deny result emits a user-visible error, records diagnostics, returns `False`,
and queues nothing.

At minimum route these sources through authorization:

- all `move_to_location()` named locations;
- active plate anchor and plate-well derived movement;
- rack Slot-* movement derived from Left/Right anchors;
- Camera workflows using explicit/custom coordinates;
- View calibration helpers that currently call absolute primitives with
  configuration-derived values.

Manual coordinate jogging that is not derived from a saved target remains
under existing homing, bounds, collision, and workflow controls. It must not be
misrepresented as verified saved-target movement.

`override`, `manual`, and `ignore_safe_height` never alter verification result.
A direct low-level primitive used by an audited saved-target workflow must
carry an allowed authorization context or be rejected.

### 18. Runtime hash/value mismatch revokes authorization immediately

Before each saved-target authorization, recompute the raw hash of its current
source config file and compare it with the verification record. Also compare
the exact current in-memory target/aggregate value with the bound semantic
fingerprint.

Therefore:

- an external edit after startup blocks movement;
- an in-memory unsaved edit blocks that target;
- a saved edit blocks every target bound to the changed file until a later
  verification transaction updates evidence;
- a changed plate corner blocks the aggregate plate;
- a changed rack anchor blocks every derived slot;
- unchanged UI enabled state cannot bypass the decision.

Milestone 4 will turn revocation and re-verification into audited transactions.
Milestone 3 supplies the fail-closed enforcement first.

### 19. Cancel and failure exit; no restricted hardware mode

Initial exit codes should distinguish:

```text
already_running
bootstrap_cancelled
bootstrap_failed
recovery_required
configuration_lock_unavailable
```

On cancel/failure:

- stop/cooperatively reconcile any worker;
- show/copy a concise diagnostic path and state;
- close bootstrap UI;
- do not import ApplicationComposition production factories;
- do not strict-load into Model;
- do not construct Machine, Controller, View, camera, balance, or serial;
- release owned locks in reverse order;
- return a nonzero code.

No restricted calibration/recovery hardware mode is part of Milestone 3. Such
a mode would need a separate command allowlist and qualification plan. A
preset-matching Camera without independent evidence therefore blocks startup
rather than offering a risky calibration shortcut.

### 20. The old updater requires no pre-update code change

Both supported deployments enter rc.2 through older updater code. Milestone 0
manual copies remain the pre-update protection. After rc.2 relaunch:

- bootstrap runs before any legacy config read;
- current checkout local and operator backup are candidates;
- M2 creates the automatic verified archive;
- rc.6/rc.1 both produce the same copied-unverified canonical form;
- M3 identity/source/target verification and activation are identical.

Updater-integrated pre/post preservation begins in Milestone 6. M3 must not
claim that the old updater performed new safeguards.

### 21. Unknown legacy data blocks activation until ownership is resolved

Milestone 2 preserves every safe source file in its verified archive but copies
only classified machine data into the canonical tree. Its
`unclassified_source_paths` inventory is therefore an activation gate, not an
informational footnote.

Before Milestone 3 can activate that migration, each reported path must match a
versioned, reviewed ownership rule that marks it as one of:

- canonical machine data with a defined external destination;
- archive-only update/cache/log/experiment data that is not read by production;
- prohibited or malformed content requiring support review.

An unknown path with no rule blocks activation and is displayed with its source
relative path and archive evidence. The bootstrap dialog has no generic
“ignore unknown files” action. A new classification requires a reviewed code/
policy change and a rerun of candidate inspection; an operator note alone
cannot silently discard a possible active machine file.

The checked-in `machine_data_ownership_rules.json` catalog is parsed by a pure
`MachineDataOwnership.py` module. Rules are exact paths or narrowly reviewed
anchored patterns, carry a stable rule ID/reason/destination classification,
and reject overlapping or ambiguous matches. The activation receipt records
the policy schema/version and the rule ID applied to every unclassified source
path. Operators cannot add rules or blanket ignores from the dialog.

## Bootstrap states

Core inspection states:

```text
ready
no_external_store
candidate_selection_required
identity_assignment_required
migration_required
migration_resume_required
source_verification_required
target_verification_required
activation_resume_required
recovery_required
lock_unavailable
```

Only `ready` can return production roots. UI page/button state is derived from
the core state and cannot force a transition absent valid domain evidence.

## Verification schema example

```json
{
  "schema_name": "labcraft.machine_verification",
  "schema_version": 1,
  "policy_name": "labcraft.initial_target_verification",
  "policy_version": 1,
  "machine_id": "LC-001",
  "machine_uuid": "00000000-0000-0000-0000-000000000001",
  "migration_id": "00000000-0000-0000-0000-000000000002",
  "required_config_fingerprint": "<sha256>",
  "source_verification": {
    "state": "verified",
    "verified_at_utc": "2026-08-19T12:00:00Z",
    "verified_by": "Operator Name",
    "machine_id_confirmation": "LC-001",
    "reason": "Selected preserved pre-update local backup"
  },
  "targets": {
    "location:camera": {
      "display_name": "camera",
      "kind": "location",
      "state": "verified_against_service_record",
      "value": {"X": 11040, "Y": 39636, "Z": 98052},
      "value_sha256": "<sha256>",
      "source_file": "config/Locations.json",
      "source_file_sha256": "<sha256>",
      "verified_at_utc": "2026-08-19T12:05:00Z",
      "verified_by": "Operator Name",
      "service_record_reference": "SERVICE-123",
      "preset_match": false
    }
  },
  "activation_ready": true,
  "created_at_utc": "2026-08-19T12:10:00Z",
  "app_version": "v1.3.0-rc.2",
  "app_commit": "<git-sha>"
}
```

`activation_ready` is recomputed and checked; a stored `true` value is not
trusted independently of target coverage and hashes.

`metadata/activation_receipt.json` is separate from the M2 receipt. Example:

```json
{
  "schema_name": "labcraft.activation_receipt",
  "schema_version": 1,
  "state": "ready_for_activation",
  "activation_id": "00000000-0000-0000-0000-000000000003",
  "migration_id": "00000000-0000-0000-0000-000000000002",
  "machine_id": "LC-001",
  "machine_uuid": "00000000-0000-0000-0000-000000000001",
  "migration_receipt_sha256": "<sha256>",
  "migration_tree_manifest_sha256": "<sha256>",
  "verification_sha256": "<sha256>",
  "backup_archive_sha256": "<sha256>",
  "ownership_policy_version": 1,
  "directory_sync_supported": false,
  "created_at_utc": "2026-08-19T12:10:00Z",
  "app_version": "v1.3.0-rc.2",
  "app_commit": "<git-sha>"
}
```

All hashes and readiness fields are recomputed on load. The durability flag is
capability evidence, not an excuse to skip any available file/directory sync.

The pointer written last is `labcraft.active_machine` version 2 and includes:

```json
{
  "schema_name": "labcraft.active_machine",
  "schema_version": 2,
  "machine_id": "LC-001",
  "machine_uuid": "00000000-0000-0000-0000-000000000001",
  "activation_id": "00000000-0000-0000-0000-000000000003",
  "migration_id": "00000000-0000-0000-0000-000000000002",
  "activation_receipt_sha256": "<sha256>",
  "selected_at_utc": "2026-08-19T12:10:01Z",
  "selection_source": "migration"
}
```

Bootstrap recomputes the receipt hash and all transitive bindings before
returning a context; presence of the pointer alone is never sufficient.

## Proposed modules and responsibilities

### `MachineDataOwnership.py`

Pure checked-in ownership policy:

- strict parser for `machine_data_ownership_rules.json`;
- exact/anchored match evaluation with ambiguity rejection;
- canonical, archive-only, and prohibited classifications;
- stable rule evidence for verification and activation receipts.

No user-authored ignore rule or Qt dependency.

### `MachineDataVerification.py`

Pure standard-library policy and evidence:

- verification schemas/parsers/serializers;
- target key/value canonicalization;
- all-location/rack/plate coverage policy;
- Camera/preset method restrictions;
- source attestation;
- atomic verification record writer/reopen validator;
- `SavedTargetAuthorizer` and decision reason codes;
- config hash and runtime value checks.
- versioned ownership-rule enforcement for M2 unclassified paths.

No Qt, MVC, updater, or hardware imports.

### `MachineDataBootstrap.py`

Hardware-free orchestration:

- inspect external active/canonical state;
- return explicit bootstrap state;
- identity assignment/resume record;
- call the inert M2 migration engine through injected interfaces;
- collect/validate source and target verification submissions;
- verify immutable M2 publication evidence through public M2 APIs;
- own the activation journal and immutable activation-receipt schema;
- write active pointer last;
- acquire/transfer configuration lock ownership;
- produce `AuthorizedMachineContext`.

No Machine, Controller, View, camera, serial, balance, or firmware import.

### `MachineDataBootstrapDialog.py`

Qt presentation/worker adapter:

- stacked first-start/recovery pages;
- explicit folder/ZIP selection;
- comparison tables and Camera prominence;
- identity and typed confirmations;
- target verification method widgets;
- cooperative progress/cancel handling;
- deterministic mapping between UI events and core submissions.

The dialog never calculates policy from widget state; the core returns allowed
actions and reasons.

## Proposed Python contracts

Exact names may evolve tests-first, but equivalent separation is required.

```python
@dataclass(frozen=True)
class AuthorizedMachineContext:
    paths: MachineDataPaths
    identity: MachineIdentity
    active_machine: ActiveMachine
    migration_receipt: MigrationReceipt
    verification: MachineVerification
    activation_receipt: ActivationReceipt
    settings: Mapping[str, object]
    settings_raw_sha256: str
    saved_target_authorizer: SavedTargetAuthorizer
    configuration_lock: AcquiredConfigurationLock


@dataclass(frozen=True)
class BootstrapInspection:
    state: BootstrapState
    base: MachineDataBasePaths
    active_machine: ActiveMachine | None
    machine_paths: MachineDataPaths | None
    migration_resume: MigrationReceipt | None
    issues: tuple[BootstrapIssue, ...]
    allowed_actions: frozenset[str]


@dataclass(frozen=True)
class PublishedMigrationEvidence:
    receipt: MigrationReceipt
    candidate: CandidateEvidence
    backup: VerifiedBackup
    migration_tree_manifest_sha256: str
    additional_paths: tuple[str, ...]


def load_candidate_evidence(path: Path) -> CandidateEvidence:
    ...


def load_migration_receipt(path: Path) -> MigrationReceipt:
    ...


def verify_published_migration(
    paths: MachineDataPaths,
    *,
    phase: PublishedMigrationPhase,
) -> PublishedMigrationEvidence:
    ...


class MachineDataBootstrap:
    def inspect(self) -> BootstrapInspection:
        ...

    def inspect_candidate(self, selection) -> CandidateEvidence:
        ...

    def assign_or_confirm_identity(self, submission) -> MachineIdentity:
        ...

    def migrate_selected_candidate(self, submission) -> MigrationResult:
        ...

    def verify_source(self, submission) -> SourceVerification:
        ...

    def verify_targets(self, submission) -> MachineVerification:
        ...

    def activate(self) -> AuthorizedMachineContext:
        ...


@dataclass(frozen=True)
class SavedTargetAuthorizationRequest:
    machine_uuid: str
    target_key: str
    target_kind: str
    base_value: Mapping[str, object]
    final_coordinates: Mapping[str, int]
    source_file_sha256: str
    workflow: str
    offsets: Mapping[str, int]
    manual: bool
    override: bool
    ignore_safe_height: bool


@dataclass(frozen=True)
class SavedTargetAuthorizationDecision:
    allowed: bool
    reason_code: str
    message: str
    target_key: str
    verified_value_sha256: str | None
```

The authorization service never receives a UI “force” flag.

## Implementation sequence

Milestone 3 is one reviewable production-cutover commit. Because it crosses MVC
and motion control, implement in these eight ordered slices with tests at each
boundary.

### Slice 1: Evidence schemas, ownership, and M2 phase handoff

Add failing tests, the ownership catalog/module, activation receipt/journal
schemas, and pure verification policy. Expose strict public M2 parsers and a
fixed-phase published-baseline verifier without changing the immutable M2
receipt. Cover source attestation, target keys, exact value/file binding,
all-target coverage, Camera stronger rules, preset restrictions, serializers,
extra-path rejection, and illegal-state rejection. No application integration.

### Slice 2: Saved-target authorizer

Implement pure allow/deny decisions and runtime file/value mismatch checks.
Add location, rack, plate, Camera, changed-file, changed-memory, override, and
missing-evidence tests before touching Controller.

### Slice 3: Bootstrap state core

Implement active/canonical inspection, identity assignment/resume, M2 adapter,
published-evidence/workspace-absent reconciliation, verification persistence,
activation journal/receipt, pointer-last activation, configuration-lock
transfer, and `AuthorizedMachineContext`. Fault-inject every verification,
activation-receipt/journal, and pointer boundary. Refuse activation while M2
reports an unclassified path that has no reviewed ownership rule.

### Slice 4: Hardware-free bootstrap dialog

Implement the standalone modal UI and worker with injected bootstrap core.
Test every page, conflict, browse selection, typed confirmation, Camera rule,
cancel checkpoint, error, and resume without importing or constructing
production hardware modules.

### Slice 5: Canonical strict roots and path injection

Extend MachineData calibration paths, ApplicationRoots/dependencies,
LocalConfig existing-only access, Model strict mode, CalibrationMemory existing-
baseline mode, optics path injection, qualification identity, and regulator
output roots. Preserve simulation and explicit legacy/test behavior.

### Slice 6: App sequencing and lock lifetime

Change `App.main()` so the app identity and application-wide lock precede
bootstrap, while Settings/composition/hardware follow only an authorized
context. Add deterministic exit codes and ensure every failure releases locks
without splash/MainWindow/hardware construction.

### Slice 7: Controller enforcement and call-site audit

Inject the authorizer into production Controller, gate
`move_to_location()` before route commands, adapt plate/rack/Camera and direct
config-derived absolute call sites, and prove manual/override/ignore flags do
not bypass it. Preserve existing collision and route behavior after allowance.

### Slice 8: Cohort journeys, closeout, and full validation

Run full rc.6/rc.1 synthetic migrations, second-checkout reuse, canonical
corruption/recovery, simulation isolation, and no-command SIL journeys. Refresh
direct-local search, run focused/full suites, record commit/results, and update
the parent plan.

## Exact expected file list

Expected new application modules:

- `FreeRTOS-interface/MachineDataOwnership.py`.
- `FreeRTOS-interface/MachineDataVerification.py`.
- `FreeRTOS-interface/MachineDataBootstrap.py`.
- `FreeRTOS-interface/MachineDataBootstrapDialog.py`.
- `FreeRTOS-interface/Presets/machine_data_ownership_rules.json`.

Expected existing application modules:

- `FreeRTOS-interface/MachineData.py` for activation-receipt/workspace paths,
  the hash-bound v2 active pointer, and the retained configuration-lock
  contract.
- Milestone 2 archive/migration modules for public candidate/receipt parsers,
  installed-backup verification, and fixed-phase baseline verification; the
  M2 receipt schema/state remains unchanged.
- Milestone 2 lock module plus a canonical configuration-lock adapter.
- `FreeRTOS-interface/App.py`.
- `FreeRTOS-interface/ApplicationComposition.py`.
- `FreeRTOS-interface/LocalConfig.py`.
- `FreeRTOS-interface/Model.py`.
- `FreeRTOS-interface/CalibrationMemoryStore.py`.
- `FreeRTOS-interface/CalibrationClasses/Model.py` for instance optics path.
- `FreeRTOS-interface/Controller.py`.
- `FreeRTOS-interface/QualificationRunWorker.py` for identity-path injection.
- `FreeRTOS-interface/View.py` for its currently hard-coded optics display path.
- `FreeRTOS-interface/RegulatorProfiles.py` only if tests prove its explicit
  path route is insufficient; its legacy default should remain unchanged.

Expected tests:

- New `tests/test_machine_data_ownership.py`.
- New `tests/test_machine_data_verification.py`.
- New `tests/test_machine_data_bootstrap.py`.
- New `tests/test_machine_data_bootstrap_recovery.py`.
- New `tests/test_machine_data_bootstrap_dialog.py`.
- New `tests/test_app_machine_data_bootstrap.py`.
- New `tests/test_controller_saved_target_authorization.py`.
- Extend Milestone 2 migration/recovery tests for public published-evidence
  parsing, fixed M3 sidecar inventories, immutable receipt behavior, absent
  completed workspace, partial-stage preservation, and installed-backup use.
- Extend `tests/test_machine_data_contract.py`.
- Extend `tests/test_local_config.py`.
- Extend `tests/test_safe_application_construction.py`.
- Extend `tests/test_view_window_icon_contract.py` for startup ordering.
- Extend `tests/test_controller_move_to_location.py` and relevant plate/rack/
  camera workflow tests.
- Extend optics, regulator calibration, Controller/qualification-worker
  identity, View display-path, and simulation root tests.
- Add virtual/SIL first-start journeys using only synthetic fixtures.

Expected documentation:

- Parent living plan.
- Milestone 2 ownership correction.
- This Milestone 3 implementation plan.
- Operator/support first-start instructions before M3 is verified.

Files explicitly not expected to change:

- `tools/update_and_restart.py` in this milestone.
- `VERSION`, `CHANGELOG.md`, `releases/latest.json`, release manifests, or tags.
- Firmware sources, firmware artifact, device protocol, opcode, parsing, motion
  timing, or pressure-control files.
- Actual deployed backups or machine-specific location values.

Reconfirm this list immediately before implementation. If a direct config-
derived movement exists outside it, update the parent plan and file list before
editing. Firmware changes would require reading `firmware/AGENTS.md` and a
separate approved scope; none are planned.

## Detailed test matrix

### Startup ordering and construction

| Case | Expected result |
| --- | --- |
| Duplicate app instance | Exit before bootstrap/splash/hardware |
| Bootstrap cancel | Nonzero exit; no composition import or hardware object |
| Bootstrap fatal error | Diagnostic and exit; no Settings/Model/Machine |
| Bootstrap ready | Strict Settings then production composition |
| Missing/malformed canonical Settings | Fail; no default profile fallback |
| Canonical file disappears after bootstrap | Strict Model construction fails; no preset seed |
| Configuration lock unavailable | Exit before Settings/hardware |
| Component construction fails | Context/locks close safely |
| Main app lifetime | Configuration lock remains owned until shutdown |

### Existing canonical store

| Case | Expected result |
| --- | --- |
| Valid active pointer/store | Silent validation and same roots |
| Second checkout, same account/base | Same UUID/config; no migration UI |
| Pointer missing with one copied-unverified store | Explicit resume offered; no auto activation |
| Multiple machine roots, no pointer | Explicit selection required |
| Pointer references missing root | Recovery required; no legacy fallback |
| M2 receipt/baseline/verification/activation/hash/identity mismatch | Recovery required |
| Unknown schema/version | Recovery required |
| Version 1 active pointer | Diagnostic/recovery only; never production authorization |
| Verification/activation receipt before pointer after crash | Idempotent activation resume |
| M2 receipt changed from copied-unverified | Recovery required; never upgraded in place |
| Arbitrary extra tree file | Recovery required |
| Exact M3 sidecars/configuration-lock file | Accepted only in its fixed phase |
| Completed M2 workspace absent | Published evidence validates normally |

### Candidate and identity UI

| Case | Expected result |
| --- | --- |
| Current checkout local exists | Visible, not silently confirmed |
| User selects Desktop wrapper/local/ZIP | M2 evidence shown identically |
| Code-generated M2 source backup | Verified as installed backup; never inspected as a legacy candidate |
| Duplicate candidates | Grouped; explicit source still required |
| Conflicting candidates | Selection plus nonempty reason required |
| Missing/fatal candidate files | Cannot continue |
| Assigned matching identity | Exact typed ID confirmation |
| Missing/unassigned identity | One durable UUID assignment workflow |
| Restart during assignment | Same UUID reused |
| Assigned identity mismatch | Conflict; no edit/activation |

### Source and preset policy

| Case | Expected result |
| --- | --- |
| Exact copy only | Still not source/target verified |
| Machine ID not typed exactly | Source verification rejected |
| Full historical preset candidate | No blanket trust action |
| Camera-only preset match | Camera trusted-source method unavailable |
| Conflicting source without reason | Rejected |
| Non-preset preserved source | Eligible non-Camera targets may use bulk trusted method |
| Service-record method | Requires nonempty operator and record reference |
| Known archive-only extra path | Shown and accepted by a versioned ownership rule |
| Unknown/unclassified extra path | Activation blocked; no operator ignore action |

### Target coverage

| Case | Expected result |
| --- | --- |
| Every named location verified | Location coverage passes |
| Any named location unverified/revoked | Activation blocked |
| Case-colliding location names | Activation blocked |
| Current profile lacks Camera | Activation blocked |
| Legacy profile without Camera | Allowed if all applicable targets pass |
| Camera trusted method with non-preset value | Separate typed Y confirmation required |
| Camera preset match with trusted method | Rejected |
| Complete rack pair verified together | Rack coverage passes |
| Missing/partial rack pair | Activation blocked |
| Every nonempty plate four-corner set verified | Plate coverage passes |
| Default plate empty/partial/unverified | Activation blocked |
| Empty non-default plate | Remains unavailable; does not block |

### Verification durability and activation

Fault-inject before/after verification and activation-receipt temp write, file
sync, replace, directory sync, and reopen; activation-journal transitions;
active pointer temp write/sync/replace/reopen; and lock transfer.

For every checkpoint prove:

- no hardware-capable construction occurs before a complete ready result;
- repeated bootstrap resumes or reports recovery without inventing evidence;
- pointer is never trusted ahead of immutable M2 evidence, verification, and
  activation receipt;
- active pointer is written last;
- candidate and migration backup remain unchanged;
- exact verification target/file hashes are preserved;
- no preset is used for repair.
- an unsupported directory-sync capability is recorded and surfaced rather
  than represented as completed durability.

### Controller authorization

| Case | Expected result |
| --- | --- |
| Verified location and matching file/value | Existing route sequence preserved |
| Unverified/revoked location | False, error, zero queued commands |
| UI would incorrectly enable move | Controller still blocks |
| `override=True` | Does not bypass verification |
| `manual=True` | Does not bypass saved-target verification |
| `ignore_safe_height=True` | Does not bypass verification |
| File hash changes after startup | Bound targets block |
| In-memory value changes | Target blocks |
| One plate corner changes | Plate/well movement blocks |
| One rack anchor changes | All slot-derived movement blocks |
| Verified Camera with exact value | Existing safe route preserved |
| Camera custom coordinates without matching authorization | Blocks |
| Authorization deny | Occurs before safe-Z/dogleg/final commands |
| Existing collision check denies an authorized target | Still blocks |
| Non-saved manual jog | Existing independent safety path remains |

### Canonical path injection

| Consumer | Expected production path |
| --- | --- |
| Settings/Locations/Plates/Obstacles/RegulatorProfiles | `<machine_root>/config` |
| CalibrationMemory | `<machine_root>/CalibrationMemory` |
| Droplet optics | `<machine_root>/calibration/droplet_imager_optics.json` |
| Regulator optimization | `<machine_root>/calibration/regulator_optimization` |
| Qualification identity | `<machine_root>/metadata/machine_identity.json` |
| Verification | `<machine_root>/metadata/verification.json` |
| Activation receipt | `<machine_root>/metadata/activation_receipt.json` |
| Experiments | Existing separate policy; not silently moved into machine config |

Search tests must prove production code no longer has active direct
`<repo>/local` consumers for these classified paths. Legacy helpers and
standalone explicitly configured tools may retain documented compatibility
defaults.

### Simulation and no-hardware journeys

| Case | Expected result |
| --- | --- |
| Official simulation | Uses explicit run roots; no production bootstrap/pointer |
| Bootstrap dialog unit tests | No Machine/serial/camera/balance construction |
| rc.6 synthetic first start | Migrates, verifies, activates with no hardware |
| rc.1 synthetic first start | Same canonical result contract |
| Preset Camera journey | Stops before hardware absent service evidence |
| Cancel/failure journeys | Zero machine queue calls |
| Second-checkout journey | Same external store and no legacy reads |

## Validation commands

Focused gate during implementation:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_machine_data_contract.py `
  tests\test_machine_data_archive.py `
  tests\test_machine_data_migration.py `
  tests\test_machine_data_migration_recovery.py `
  tests\test_machine_data_verification.py `
  tests\test_machine_data_bootstrap.py `
  tests\test_machine_data_bootstrap_recovery.py `
  tests\test_machine_data_bootstrap_dialog.py `
  tests\test_app_machine_data_bootstrap.py `
  tests\test_controller_saved_target_authorization.py `
  tests\test_controller_move_to_location.py `
  tests\test_local_config.py `
  tests\test_safe_application_construction.py `
  tests\test_view_window_icon_contract.py
```

Full Python gate:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

Virtual no-hardware gate should use the repository's existing virtual workflow
harness with a new explicit first-start scenario once implemented. Record the
exact command in the implementation record rather than inventing a second
launcher.

Static/documentation gates:

```powershell
git diff --check
git status --short
```

Use the repository-prescribed 15-minute timeout for the full Python suite.

This milestone changes production startup and blocks motion paths but does not
change firmware or protocol. No firmware build/flash is required. Physical HIL
movement is deferred to Milestone 7 and may occur only with the approved
machine identity, backups, verified values, app/firmware pairing, operator stop
capability, and route-specific checklist. Milestone 3 validation must first
prove all deny paths with zero queued virtual commands.

## Manual no-hardware checklist

Before marking verified, on Windows and the target Pi with machine communication
physically unavailable or disabled:

1. Launch with no external store and synthetic rc.6 local candidate.
2. Confirm the bootstrap dialog is the only actionable window.
3. Cancel from candidate, identity, migration, and target pages where safely
   allowed; confirm no normal app/hardware construction.
4. Complete a synthetic non-preset journey and record external paths/receipts.
5. Launch from a second checkout under the same account and confirm silent
   canonical reuse.
6. Corrupt a disposable test verification/hash and confirm recovery-required,
   never legacy fallback.
7. Use simulation to attempt unverified Camera, rack, and plate moves; confirm
   zero queued commands.
8. Restore/delete only disposable test roots, never deployed machine data.

## Review checklist

- [x] Bootstrap runs before Settings, composition, MVC, and hardware imports.
- [x] Production dependencies require an authorized canonical context.
- [x] Existing canonical corruption never falls back to legacy/preset.
- [x] Candidate selection and conflict reason are explicit.
- [x] Identity is assigned once and never inferred from hostname/port alone.
- [x] Copy/source/target evidence remains separate.
- [x] Every existing named location is covered before first activation.
- [x] Rack is one pair and each calibrated plate is one four-corner target.
- [x] Camera always uses its separate stronger action.
- [x] Preset-matching Camera cannot use trusted-source/bulk verification.
- [x] Every M2 unclassified path is resolved by a reviewed ownership rule or
  activation remains blocked.
- [x] M2 receipt/tree-manifest provenance remains immutable and publicly
  verifiable through fixed phase inventories.
- [x] Generated M2 backups are verified as backups, never reinterpreted as
  operator candidate ZIPs.
- [x] Verification records bind exact values, file hashes, UUID, app, and time.
- [x] Verification, activation-receipt/journal, and pointer writes are
  ordered/recoverable.
- [x] Active pointer is written last and reopened.
- [x] Canonical production cannot seed missing config or CalibrationMemory.
- [x] App and Model consume the exact same canonical Settings/config roots.
- [x] Optics, regulator output, and qualification identity no longer use active
  checkout-local paths.
- [x] Configuration lock is retained for the application lifetime.
- [x] Controller denies before any route command and UI cannot bypass it.
- [x] Override/manual/ignore flags do not bypass verification.
- [x] Plate/rack/Camera direct call sites are audited and adapted.
- [x] Simulation remains explicit and isolated.
- [x] rc.6, rc.1, cancel, corruption, resume, and second-checkout journeys pass.
- [x] Focused, full, and virtual no-hardware gates pass.
- [x] Parent plan records findings, validation, and dedicated commit.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Bootstrap imports hardware too early | Separate core/dialog modules; App ordering tests fail on production composition import/construction |
| User chooses wrong backup | Coordinate/hash/version/identity comparison, typed ID, conflict reason, no automatic winner |
| Exact copy mistaken for physical correctness | Separate source and target evidence; Camera stronger method |
| Old Camera preset accepted by blanket click | Historical match disables trusted/bulk Camera method and blocks without independent evidence |
| Operator cannot independently verify preset Camera | Safe exit before hardware; no restricted movement shortcut in M3 |
| Missing canonical file gets silently reseeded | Existing-only LocalConfig/CalibrationMemory policy and strict loaders |
| App and Model use different roots/Settings | One immutable authorized context and equality/hash tests |
| Crash between verification and pointer | Pointer-last order and idempotent activation-journal/receipt reconciliation |
| M3 sidecars invalidate exact M2 tree proof | Immutable baseline hashes plus fixed phase-specific additional-path inventories |
| Completed M2 workspace is absent | Recover from published receipt, candidate evidence, baseline manifest, and installed verified backup |
| M2 generated backup treated as candidate | Separate candidate-inspection and installed-backup verification APIs/tests |
| Another checkout/support tool writes active config | App-global plus retained canonical configuration lock |
| UI accidentally enables move | Controller authorizer independently denies before route commands |
| Override route bypasses verification | Verification decision ignores override/manual/ignore flags |
| Config changes after startup | Raw file and semantic value checks deny immediately |
| Plate/rack movement bypasses named-location gate | Aggregate authorizations plus direct-call inventory/tests |
| Optics/identity/optimization still follow checkout | Canonical calibration/metadata path injection |
| Unknown legacy file is silently left behind | Preserve it in the M2 archive and block activation until a versioned ownership rule resolves it |
| Bootstrap UI freezes during archive | Worker thread and cooperative checkpoint cancellation; never terminate writer |
| Legacy hardware profile lacks Camera | Profile-aware presence rule; all applicable existing targets still verified |
| Rollback launches legacy app against stale local | Keep original local untouched; after deployment require M6 compatibility export |

## Rollback plan

Before any fleet deployment, rollback is:

1. Revert the dedicated Milestone 3 production-cutover commit.
2. Keep Milestones 1/2 inert modules and tests if desired.
3. Confirm App again uses untouched legacy `<repo>/local`.
4. Preserve every external machine tree, backup, verification, receipt,
   workspace, and active pointer; do not delete them as part of code rollback.
5. Run LocalConfig, application-construction, startup-lock, Controller route,
   migration, and verification tests.

After any operator has used canonical production, do not simply install an
older app: it cannot see later canonical edits. Use the Milestone 6
hash-verified compatibility export and support-guided rollback procedure. The
original legacy local remains preserved but may no longer be current.

If startup fails during development, release locks in reverse order and retain
artifacts for reconciliation. Never “fix” it by deleting the external root or
active pointer without an evidence-preserving recovery procedure.

## Exit criteria

Milestone 3 is `verified` only when:

1. Milestone 2 is verified and its exact backup/copy/recovery evidence is used.
2. Bootstrap is provably before Settings, MVC, and all hardware construction.
3. Both source cohorts complete one deterministic hardware-free workflow.
4. Existing valid canonical state is reused from a second checkout/account-
   consistent base without migration.
5. Cancel, conflict, corruption, missing evidence, and lock failure construct no
   hardware and queue no commands.
6. Identity assignment/confirmation, source attestation, and all required
   target verification are durable and exact.
7. Camera's stronger preset/service rule is enforced in domain and UI tests.
8. Immutable M2 evidence, verification, and activation receipt are valid before
   active pointer, and crash recovery is idempotent at every write boundary.
9. Canonical production cannot seed a missing config or CalibrationMemory
   baseline.
10. All classified machine-owned active paths are outside the checkout.
11. No unresolved M2 `unclassified_source_paths` entry can pass activation.
12. Controller blocks every unverified/mismatched named, rack-derived, plate-
    derived, and Camera target before the first route command.
13. Existing collision/path behavior is unchanged for authorized targets.
14. Simulation remains isolated and requires no production external state.
15. Focused, full, virtual no-hardware, and manual Windows/Pi no-hardware gates
    pass with exact evidence recorded.
16. Implementation commit, findings, operator instructions, risks, and rollback
    evidence are current in the parent plan.

## Implementation record

- 2026-08-19: Implemented the hardware-free bootstrap core/dialog, reviewed
  ownership policy, exact source/target verification, immutable activation
  receipt, hash-bound version 2 active pointer, pointer-last recovery, retained
  configuration lock, strict canonical loaders, production path injection, and
  Controller saved/derived-target authorization on branch `update_bug_fix`.
- 2026-08-19: Added deterministic first-start coverage for both
  `v1.2.0-rc.6` and `v1.3.0-rc.1`, second-checkout reuse, copied-unverified and
  activation-stage resume, durable identity-assignment reuse, App failure/cancel
  ordering, dialog review, and zero-command Camera/rack/plate denial.
- 2026-08-19: Added the operator/support first-start guide at
  `docs/machine_data_migration_milestone_3_first_start.md`.
- This dedicated Milestone 3 commit contains the complete production cutover,
  its tests, operator guidance, findings, and automated validation record.
- 2026-08-19: Revised the plan after Milestone 2 verification at commit
  `157db800`. The revised boundary keeps M2 provenance immutable, adds a
  separate activation receipt/journal, specifies fixed phase inventories, and
  treats absent completed workspaces and installed generated backups correctly.
- 2026-08-19: Production-cutover commit `b3cf12ad` was followed by target-Pi
  worker-lifecycle correction commit `08d41bc2`. The correction stages worker
  results and waits for `QThread.finished` before closing or transitioning the
  bootstrap dialog.

## Validation record

- 2026-08-19: Python compilation passed for every changed application module.
- 2026-08-19: Focused Milestone 3 gate passed: `287 passed, 1 skipped`.
- 2026-08-19: Full Python gate passed using an external pytest base required by
  the simulation-session containment policy:
  `5232 passed, 153 skipped` in 406.93 seconds.
- 2026-08-19: Standard host SIL suite passed (`1/1`, no warnings/failures):
  `virtual_print_array_24_v1`; aggregate SHA-256
  `d3f91486bd811f532588616777bba9fbceee74530f574a56c0b89e1ad536dfd8`
  under `C:\Users\conar\source\LabCraft_m3_virtual`.
- 2026-08-19: Current startup, LocalConfig/Model seeding,
  CalibrationMemory initialization, optics/identity/regulator direct-local
  consumers, ApplicationComposition order, and Controller saved/derived motion
  call paths were re-audited after implementation.
- Post-M2 inspection reviewed the implemented `copied_unverified` receipt,
  exact migration-tree manifest, verified-backup layout, lock requirement,
  workspace cleanup, and partial-stage fail-closed behavior at commit
  `157db800`.
- 2026-08-19: `git diff --check`, strict ownership JSON parsing, UTF-8 and
  Markdown-fence checks, and changed-module Python compilation passed.
- 2026-08-19: Worker-lifecycle correction passed `13` dialog tests, `107`
  focused bootstrap/startup/safety tests, and the full Python suite at
  `5235 passed, 153 skipped`. A hardware-free probe using the target Pi's real
  PySide6/QThread runtime also passed.
- 2026-08-19: Target-Pi no-hardware qualification passed at `08d41bc2` using
  an operator-selected `v1.3.0-rc.1` backup, disposable external root, machine
  `LC-001`, and canonical hardware profile `current`. Both cancellation paths
  returned `2`; initial activation and detached-worktree reuse succeeded;
  deliberate Settings corruption failed closed with `4`; exact restoration
  reopened with `0`; and the Pi zero-command gate passed `10 tests` with exit
  `0`.
- The original Step 4 `evidence-sha256.txt` was not created after a deliberate
  missing-file probe executed `exit 1` in the interactive shell. The exception
  is retained rather than backfilled. All six immutable metadata files retained
  their activation timestamps, bootstrap revalidated the receipt/hash graph,
  restored Settings and its recovery copy shared SHA-256
  `69a5f4b90ede862fc716090cbf2e53ce330080f8d403ba747ce1d8d69ba7646a`,
  and the labeled closeout snapshot/check returned `OK` for every entry.
- Every M2 unclassified path in the real rc.1 source was beneath
  `update_logs/` and resolved through reviewed archive-only rule
  `legacy-update-logs-v1`. No unmatched/prohibited ownership decision passed.
- All exit criteria are satisfied; Milestone 3 is verified at `08d41bc2`.

## Findings discovered during planning

1. Production composition currently has a zero-argument root path; M3 should
   make authorized roots mandatory rather than add an optional migration path.
2. Strict App loading is insufficient alone because Model can independently
   seed explicit roots; load policy must travel through composition.
3. CalibrationMemory initialization is a second silent-creation boundary and
   must participate in canonical existing-only policy.
4. Camera verification must occur without moving to Camera. A preset-matching
   value without independent evidence therefore cannot be safely resolved by
   the preconstruction UI.
5. Verifying every existing named location is clearer and safer than trying to
   maintain an incomplete reserved-name allowlist during initial cutover.
6. Rack/plate verification needs aggregate value binding because their runtime
   targets are derived and may bypass direct named-location lookup.
7. Controller route authorization must precede intermediate dogleg/safe-height
   commands; checking only the final call would be too late.
8. A configuration lock held only during bootstrap would allow another process
   to change canonical data while the app runs; ownership must span runtime.
9. Known optics and regulator-optimization paths are machine calibration, not
   generic unclassified files, and require canonical path injection.
10. Treating unknown archived paths as harmless would recreate the same class
    of hidden local dependency. Activation must block until reviewed ownership
    policy proves that each path is canonical or archive-only.
11. Milestone 2's closeout inventory found direct-local fallbacks in
    `QualificationRunWorker` and a relative optics path in View. Both must be
    explicitly injected or removed from production during M3 rather than
    relying only on Controller/Model changes.
12. M2's receipt parser accepts only `copied_unverified` with all authority
    flags false. Extending that file would erase the clean M2/M3 trust boundary;
    M3 needs a separate activation receipt.
13. M2's migration-tree manifest is an exact inventory. Verification and
    activation sidecars plus the configuration lock require a fixed
    phase-aware verifier, while the manifest itself remains immutable.
14. Successful M2 publication removes the workspace. Normal M3 startup must
    use published evidence; a missing workspace is not incomplete migration.
15. Generated M2 backups use `manifest.json` plus `source/local/...`, unlike
    selectable legacy candidates. Resume must verify the installed archive
    directly instead of feeding it back to candidate inspection.
16. M2 requires a UUID migration lock for writes and preserves partial or
    mismatched stages for diagnosis. M3 must assign/confirm identity before
    locking and must never auto-delete/rebuild conflicting evidence.
17. M2 records whether directory syncing is supported. M3 must bind and surface
    that capability in activation evidence and qualify it per platform.
18. A fault before `DurableFileOps.atomic_write_json()` opened its temporary
    stream could leave the raw descriptor open on Windows and prevent contained
    recovery cleanup. The writer now closes that descriptor on every exception,
    with assignment-boundary recovery coverage.
19. Durable activation assignments live outside `machines/`; inspecting only
    canonical machine roots could miss an interruption before M2 publication.
    Bootstrap now detects that evidence and requires the same candidate,
    machine identity, UUID, activation ID, and migration ID on resume.
20. Repository-local pytest bases are intentionally rejected by SIL session
    containment. The valid full gate used an external disposable pytest base;
    representative failures from a repo-local base passed unchanged outside
    the checkout.
21. On the target Pi, a queued worker-result slot could call `accept()` while
    its child `QThread` was still running. Dialog destruction then waited for
    the worker while the GUI thread held the Python GIL, and the worker waited
    to reacquire that GIL. UI completion must be gated on both the operation
    result and `QThread.finished`.
22. An operator runbook probe must not execute `exit` from an interactive
    terminal. The missing-file experiment closed the shell and skipped the
    next evidence-snapshot command; revised guidance reports every missing path
    and tells the operator to stop without terminating the shell.
23. Machine ID and hardware profile are authorization evidence but are not
    clearly presented by the normal main window. Qualification must print them
    from the versioned active pointer and canonical Settings; a main-window
    screenshot proves lifecycle only.

## Document change log

| Date | Change |
| --- | --- |
| 2026-08-19 | Created the concrete first-start bootstrap, identity/source/target verification, canonical activation, strict loading, path injection, and Controller authorization implementation plan for Milestone 3. |
| 2026-08-19 | Added qualification-worker identity and View optics paths found by the Milestone 2 direct-local closeout inventory. |
| 2026-08-19 | Revised the plan against verified M2 commit `157db800`: immutable M2 provenance, separate activation receipt/journal, fixed phase inventories, public published-evidence APIs, installed-backup distinction, and workspace-absent recovery. |
| 2026-08-19 | Implemented all eight slices, added exact first-start/operator guidance, and recorded focused/full/host-SIL automated evidence in the dedicated Milestone 3 commit; status is `implementation_complete` pending manual Pi validation. |
| 2026-08-19 | Recorded production commit `b3cf12ad`, Pi worker-shutdown fix `08d41bc2`, complete automated/target-Pi evidence, the transparent missing-baseline exception, and marked Milestone 3 `verified`. |
