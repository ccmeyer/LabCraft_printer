# Machine Data Migration Milestone 6: Update Preservation and Controlled Rollback

Status: `implemented; local validation passed; commit and target-Pi qualification pending`

Prepared: 2026-08-20

Parent plan:
`docs/machine_data_migration_and_location_safety_plan.md`

Depends on:

- Milestone 1 machine-data contract `9b882141` (`verified`)
- Milestone 2 migration engine `157db800` (`verified`)
- Milestone 3 production cutover `b3cf12ad` and lifecycle correction
  `08d41bc2` (`verified`)
- Milestone 4 transaction history `6925d029` and exact-restore correction
  `f6d65fd9` (`verified`)
- Milestone 5 guarded changes `8b50872d` (`verified`)
- Milestone 5 verification record `083ab0a1`

Target release: `v1.3.0-rc.2`

## Outcome

Milestone 6 makes preservation of the authorized external machine-data store a
mandatory part of every update started by rc.2 or later. The updater must bind
itself to the exact active machine, acquire exclusive mutation locks, create
and reopen a verified backup outside the checkout, and prove the post-update
machine data before it can authorize a normal relaunch.

The same milestone provides a deliberately support-guided bridge to the exact
legacy releases that still read `<repo>/local`. Before changing Git to one of
those releases, the rc.2 updater must create and verify a target-specific
compatibility export, preserve any existing `local/`, and record an unresolved
legacy session externally. When an M6-capable version returns, bootstrap must
compare that legacy copy with the export baseline before constructing MVC or
hardware. A difference becomes an explicit recovery conflict; it is never
silently discarded or copied into the canonical store.

At the end of the milestone:

- the same external root, machine UUID, machine ID, activation ID, migration
  ID, active-pointer bytes, and operational file inventory are bound to an
  update request;
- a raw-byte backup is verified before the first Git command that can change
  the checked-out revision;
- no-schema updates require exact post-update bytes for every protected file;
- declared schema transitions run only in bootstrap recovery mode, before MVC
  or hardware, and must retain the safety snapshot and append migration
  evidence;
- update logs, receipts, latest-result pointers, and deployment authorization
  live outside every checkout;
- interrupted or ambiguous update state blocks normal launch;
- manual checkout changes after M6 enrollment are detected by a deployment
  anchor instead of being silently blessed;
- rollback to `v1.2.0-rc.6`, `v1.2.0`, or `v1.3.0-rc.1` is possible only through
  an exact reviewed compatibility profile and support confirmation;
- an unknown legacy tag, incomplete target authorization, export failure, or
  unresolved firmware pairing stops rollback before legacy relaunch;
- the canonical store is frozen during a legacy session; continuous dual
  writes are prohibited; and
- firmware flashing, motion protocol, motion planning, pressure control, and
  timing-sensitive firmware behavior remain unchanged.

## Scope

### In scope

- Versioned update-preservation records under canonical external
  `update_history/`.
- A dedicated update lock plus the existing lifetime configuration lock.
- Complete protected-file inventories, raw/semantic hashes, and a focused
  safety snapshot.
- A verified pre-update archive outside the Git checkout.
- Forward online and offline update integration.
- External updater logs and latest-result pointers.
- A deployment anchor checked before production application construction.
- Recovery-only handling for interrupted updates and declared schema
  transitions.
- Exact compatibility profiles and export for `v1.2.0-rc.6`, `v1.2.0`, and
  `v1.3.0-rc.1`.
- Support-only legacy rollback authorization, export, audit, and firmware
  attestation.
- Re-upgrade detection and comparison of an unresolved legacy session.
- Windows, real-Git, detached-checkout, offline-bundle, and target-Pi
  no-hardware qualification.
- Updater, rollback, release-process, recovery, and support runbooks.

### Out of scope

- Retrofitting the old rc.6/rc.1 updater with M6 preflight. Their first move to
  rc.2 remains protected by Milestones 0, 2, and 3.
- Continuous mirroring or dual-writing between canonical data and
  `<repo>/local`.
- Automatically accepting legacy-era edits into canonical machine data.
- Automatically selecting a side of a legacy/canonical conflict.
- Treating a backup on the same disk as an off-device disaster-recovery copy.
- Automatically flashing or downgrading firmware.
- Claiming that a recorded firmware attestation proves the physical firmware
  image without the Milestone 7 deployment check.
- Supporting rollback to arbitrary historical tags. A target without an exact
  reviewed profile fails closed.
- Changing the device protocol, firmware handlers, movement routing, motor
  commands, pressure behavior, or timing.
- Editing `VERSION`, `CHANGELOG.md`, release manifests, `latest.json`, bundles,
  or tags in this planning task. The rc.2 release metadata is Milestone 7.

## Audited call paths

### Forward update check and apply

Current check path:

```text
Firmware/update tab in MainWindow
-> View requests update check
-> Controller.start_app_update_check()
-> AppUpdateCheckWorker
-> run_update_check() or online/offline fallback
-> fetch and validate release index/tag/manifest
-> result displayed by View
```

Current apply path:

```text
View requests update
-> Controller.get_app_update_blockers()
-> Controller.launch_app_updater()
-> tools/update_and_restart.py --wait-pid --gui --no-relaunch --record-result
-> updater waits for App process to exit
-> validates clean checkout and target release/bundle
-> git merge --ff-only verified target
-> writes result under <repo>/local/update_logs
-> updater window permits operator relaunch
```

Milestone 6 target apply path:

```text
View requests update
-> Controller freezes an UpdateLaunchBinding from AuthorizedMachineContext
-> command includes exact external root, UUID, machine ID, activation ID,
   pointer hash, request ID, and selected release
-> updater waits for App process and lifetime config lock to end
-> resolve target without changing HEAD
-> acquire update lock, then configuration lock
-> re-resolve and validate exact bound identity/root/activation
-> reconcile or reject unfinished update state
-> capture protected inventory and safety snapshot
-> create, reopen, and hash-verify external backup
-> recheck checkout HEAD/clean state and protected hashes
-> append backup_verified stage
-> only now run the existing fast-forward Git operation
-> verify target HEAD and external machine-data preservation
-> append post_verified and relaunch_authorized stages
-> updater UI enables normal relaunch only from that authorization
```

Update checks remain read-only and do not create backups or acquire the
configuration lock. The preservation boundary begins only when an operator
chooses to apply a specific resolved target.

### Application shutdown and locks

Current production startup calls `MachineDataBootstrap.open_ready()` before
MVC/hardware construction and retains `configuration.lock` for the application
lifetime. `AuthorizedMachineContext.close()` releases that lock during normal
shutdown. The updater already waits for the application PID, but it currently
acquires no machine-data lock after the PID exits.

M6 adds this fixed order:

```text
main App holds configuration.lock
-> external updater starts but does not touch machine data
-> main App exits and releases configuration.lock
-> updater acquires update.lock
-> updater acquires configuration.lock
-> updater retains both across backup, Git mutation, and post-verification
-> updater releases configuration.lock, then update.lock
```

Every updater uses `update.lock -> configuration.lock`. No path may acquire the
same pair in reverse order. Locks use the existing non-stale-removing
`QLockFile` policy; uncertain lock ownership is a support condition, not a
reason to delete a lock automatically. If another checkout starts and wins the
configuration lock, the updater stops before backup or Git mutation.

### Rollback check and apply

Current rollback path:

```text
View requests rollback check
-> Controller.start_app_rollback_check()
-> AppRollbackCheckWorker
-> run_rollback_check() or offline fallback
-> current manifest's rollback_version is resolved

View requests rollback
-> Controller.launch_app_rollback()
-> updater waits for App and checks clean worktree
-> validates target tag/manifest or offline bundle
-> git reset --hard verified target
-> writes checkout-local result
-> legacy app may be relaunched
```

The current path changes Git before any compatibility export and therefore
must not be used for an M6-to-legacy rollback.

M6 target legacy path:

```text
support invokes reviewed rollback flow for an exact target
-> updater binds canonical machine and target compatibility profile
-> wait for App; acquire update.lock then configuration.lock
-> require all exported motion targets hard-valid and currently verified
-> require operator/reason/machine-ID/target and firmware-pairing attestations
-> backup and verify canonical operational data
-> backup and verify any current checkout local/
-> map canonical files through the exact legacy profile
-> stage beside the checkout on the same filesystem
-> reopen with legacy-schema validators and hash-verify
-> journal and atomically exchange staged directory into <repo>/local
-> append unresolved legacy-session record externally
-> only now git reset --hard the verified tag/ref
-> verify HEAD and compatibility copy again
-> authorize legacy relaunch only if every gate passed
```

Normal one-click rollback remains disabled for a legacy target in rc.2. The UI
may show the resolved target and why support is required, but it must not mint
the support attestations or provide a generic bypass.

### Re-upgrade after a legacy session

```text
M6-capable App starts
-> resolve external active machine before MVC/hardware
-> deployment anchor or unresolved legacy-session record is found
-> locate the exact checkout/local export named by that session
-> compare current raw and semantic hashes with the export baseline
-> exact match: record unchanged return and re-authorize the deployment
-> any difference: create comparison report and enter recovery-only UI
-> operator/support explicitly keeps canonical or begins reviewed import
-> only a completed resolution record permits normal construction
```

The old app never writes canonical data. M6 never silently copies its
`local/` changes back. A representation-only JSON rewrite is still recorded as
a difference; semantic equality is shown in the report but does not erase the
fact that legacy bytes changed.

### Firmware boundary

The updater continues to read `requires_firmware` from the release manifest.
M6 records the target artifact/note and the support deployment attestation in
external update evidence. It does not inspect, flash, or downgrade firmware.
If a legacy rollback requires a firmware change and no reviewed pairing record
is supplied, legacy relaunch remains unauthorized. Physical pairing is a
Milestone 7 attended deployment responsibility.

## Fixed safety invariants

1. **No Git mutation without verified backup:** fetch and target resolution may
   occur first, but merge/reset cannot occur before a reopened backup matches
   its manifest.
2. **Exact launch binding:** updater input is the absolute external root plus
   machine UUID, machine ID, activation ID, migration ID, active-pointer hash,
   current commit, and request ID captured by the authorized running app.
3. **No fallback:** apply mode never falls back to `<repo>/local`, tracked
   presets, another candidate, a different environment root, or a newly
   created machine-data store.
4. **One writer:** update lock and configuration lock are held across the
   preservation boundary; configuration transactions cannot race an update.
5. **Exact default:** when the target declares no schema transition, every
   protected path and byte must match before/after.
6. **Recovery-only migration:** a declared schema transition cannot run in a
   normal hardware-capable application. It completes in bootstrap with the
   updater locks and verified recovery archive available.
7. **Safety semantics survive migration:** named locations, Camera, rack
   anchors/derived slots, plate corners, hard bounds/exclusions, hardware
   profile, target authorization, and configuration-chain head are compared
   and audited.
8. **Append-only authority:** mutable logs and latest pointers are diagnostic;
   relaunch authority comes from immutable, hash-linked stage records.
9. **Deployment continuity:** after initial M6 enrollment, an app commit or
   release that is not authorized by the external deployment chain enters
   recovery before MVC/hardware.
10. **No automatic post-mutation rollback:** an ambiguous failure after Git or
    data mutation enters recovery. It does not automatically reset Git or
    overwrite canonical data to make startup pass.
11. **Exact legacy targets only:** compatibility is keyed by resolved tag and
    commit, never by a loose version prefix or claimed similarity.
12. **Legacy export before reset:** a failed backup, validation, stage, swap,
    authorization, or firmware-attestation gate prevents Git rollback.
13. **Canonical freeze during legacy use:** no dual write, background sync, or
    timestamp-based merge is permitted.
14. **Legacy differences are conflicts:** raw changes, semantic changes,
    additions, deletions, and opaque calibration changes are reported and
    require an explicit resolution.
15. **No target de-verification on export:** a revoked, missing, or hard-invalid
    saved target blocks legacy rollback because the old app cannot enforce M4/
    M5 authorization.
16. **No checkout-owned authoritative evidence:** logs, backups, intents,
    receipts, and deployment state survive worktree changes outside the repo.
17. **No hardware side effects:** updater, preservation, validation, export,
    comparison, and recovery tests do not connect, home, move, pressurize,
    flash, or construct hardware.
18. **No firmware/protocol change:** M6 records pairing requirements but does
    not change device messages or firmware.

## External storage and evidence layout

Reuse the existing canonical `MachineDataPaths.update_history_root` and add an
update lock path to the machine contract:

```text
<machine-data-root>/
  active_machine.json
  machines/<machine_uuid>/
    update_history/
      deployment_anchor.json
      latest_result.json
      transactions/<update_id>/
        01_intent.json
        02_preflight_manifest.json
        03_backup_verification.json
        04_git_result.json
        05_post_update_verification.json
        06_relaunch_authorization.json
        terminal_result.json
        backup/
          pre_update.machine-data.zip
          existing_checkout_local.zip
        legacy/
          export_manifest.json
          comparison.json
          resolution.json
        logs/
          updater.log
          launcher.log
    locks/
      configuration.lock
      update.lock
```

Not every optional file exists for every operation. Stage filenames are
written once with atomic durable writes. Each stage includes the prior stage's
SHA-256 and the transaction ID. `latest_result.json` and
`deployment_anchor.json` are atomically replaced pointers whose payloads bind
an immutable terminal record and its SHA-256. They are conveniences, not the
audit authority.

The backup is external to the checkout but may be on the same storage device.
The runbook continues to recommend an off-device copy for disaster recovery.

## Protected inventory and backup contract

### Included paths

The preflight inventory includes:

- root-level `active_machine.json` as a specially named entry;
- every regular file under the active canonical machine root, including
  `config/`, `CalibrationMemory/`, `calibration/`, `metadata/`, `history/`, and
  existing `backups/`; and
- empty directories required to reconstruct the active operational tree.

It excludes only:

- `locks/**`, because lock files are process state; and
- `update_history/**`, because the transaction and its archive live there and
  including it would recurse.

The inventory rejects symlinks, junctions/reparse points, sockets/devices,
case-colliding paths, traversal, changing files during capture, unknown entry
types, and configured file/count/size limits. The implementation reuses the M2
archive safety primitives instead of creating a permissive ZIP path.

### Manifest fields

`labcraft.machine_data_update_manifest` v1 records:

- update ID, operation (`update` or `rollback`), timestamp, and contract
  version;
- exact machine-data root real path and filesystem identity when available;
- machine UUID/ID and hashes of identity, active pointer, activation,
  migration, verification, and candidate evidence;
- activation ID, migration ID, current app version/commit, target version/tag/
  commit, channel, and online/offline source;
- target release-manifest bytes and SHA-256;
- ownership, configuration-safety-policy, and compatibility-profile hashes;
- sorted path/type/size/raw-SHA-256 inventory;
- semantic SHA-256 for known JSON documents;
- configuration head sequence/event/hash and saved-target authorization state;
- the safety snapshot described below; and
- excluded path rules and archive limits used.

### Safety snapshot

The separately hash-bound safety snapshot contains complete values, not just
counts:

- `Settings.json` hardware profile and updater-relevant settings;
- every named location, including Camera and rack anchors;
- every derived rack slot used for motion;
- every plate name and its four calibration corners;
- hard X/Y/Z boundaries and configured exclusion volumes;
- raw/semantic hashes for all five governed files;
- hashes for droplet-imager optics, regulator optimization, and
  CalibrationMemory files;
- current target-authorization records and exact values;
- M4 configuration-chain sequence, head, and event hash; and
- the M5 policy ID and raw policy hash.

The manifest contains sensitive machine coordinates and remains only in the
external machine store/evidence archive. Sanitized completion records must not
copy those values into tracked docs.

### Backup verification

Backup success requires all of the following before Git mutation:

1. capture the manifest from a stable locked source;
2. write the archive and manifest through a staging path;
3. fsync files and containing directories where supported;
4. reopen the completed archive through the bounded archive reader;
5. compare path inventory, sizes, raw hashes, JSON semantic hashes, identity,
   active pointer, and safety snapshot;
6. re-hash the live protected inventory and require it still equals the
   captured manifest; and
7. append `03_backup_verification.json` with archive/manifest hashes.

A free-space check is advisory; only the reopened archive proves success.

## Update transaction and release contract

### Launch binding

Controller builds one immutable launch binding from the authorized context and
passes explicit CLI arguments. Minimum fields are:

- `--machine-data-root`;
- `--machine-uuid` and `--machine-id`;
- `--activation-id` and `--migration-id`;
- `--active-pointer-sha256`;
- `--source-commit`;
- `--update-request-id`; and
- the already resolved target release or offline manifest.

Production apply/rollback rejects missing fields. Environment-variable or
default-root resolution may be used for read-only update checks, tests, and
first-start migration, but not to authorize an apply operation.

### State machine

The authoritative state progression is:

```text
requested
-> locked
-> preflight_validated
-> backup_verified
-> git_applied
-> post_verified
-> relaunch_authorized
```

Legacy rollback inserts `compatibility_export_verified` before `git_applied`.
A schema-changing forward update uses `target_bootstrap_required` after
`git_applied`; target bootstrap must append `schema_transition_verified`
before `relaunch_authorized`.

Any failure appends either:

- `failed_before_git`, after which the old app may be reopened only if the
  deployment anchor and live protected manifest still match; or
- `recovery_required`, after Git/data mutation or any ambiguous boundary, in
  which case no normal relaunch is offered.

An already-current target still performs identity validation but need not make
a duplicate archive if no Git/data mutation is requested. It records a
non-mutating terminal result and cannot be used to repair an unresolved prior
transaction.

### Target release declaration

Extend the release-manifest validator and release runbook with a required
field for M6-capable targets. The proposed v1 shape is:

```json
"machine_data": {
  "preservation_contract": "labcraft.machine_data_update.v1",
  "data_schema_version": 1,
  "transition": "none",
  "transition_id": null
}
```

For a future intentional schema change, `transition` is
`bootstrap_recovery` and `transition_id` names a reviewed target-side adapter.
Unknown preservation contracts, schema versions, transitions, missing
adapters, or a target that omits this declaration fail before Git mutation.
The rc.2 release metadata itself is added only in Milestone 7 after M6 is
verified.

### No-schema post-update verification

With `transition: none`, updater must prove:

- same absolute/real external root and same active-pointer path;
- same machine UUID/ID, activation ID, and migration ID;
- exact active-pointer bytes;
- exact included path set, type, size, and raw bytes;
- same semantic and safety snapshot;
- same configuration head and target authorization; and
- target HEAD exactly equals the verified release commit.

Only `update_history/**` and lock-file changes are permitted. A target app is
not launched to perform this check.

### Declared schema transition

The updater first proves the machine data is still exact after changing Git,
then appends `target_bootstrap_required`. It may start only the target's
bootstrap recovery entry, with hardware construction disabled and the update
ID passed explicitly. That path:

1. reopens and verifies the pre-update archive and target declaration;
2. acquires the existing update/configuration locks in the same order;
3. executes only the registered transition adapter;
4. journals every changed file and uses atomic durable writes;
5. appends the required M4/M6 migration events;
6. proves the complete post schema and exact semantic safety snapshot;
7. verifies unchanged identity and active pointer authority; and
8. appends `schema_transition_verified` and relaunch authorization.

If the adapter fails, bootstrap remains recovery-only. It does not silently
restore or retry. Exact restoration from the verified archive is a separate
support action with a new receipt.

### Deployment anchor

`labcraft.deployment_anchor` v1 binds the last authorized app version/commit to
the active root, identity, activation, target release manifest, and terminal
update receipt. Production bootstrap validates it before MVC/hardware.

The first rc.2 launch after a successful M2/M3 activation has no M6 receipt.
One tightly constrained enrollment path may create a genesis anchor only when:

- no prior deployment anchor or M6 deployment event exists;
- the active store passes all M3-M5 validation;
- no pending configuration/update/legacy transaction exists;
- the running release is the exact reviewed rc.2 enrollment release; and
- the activation/migration evidence proves this is an initial legacy-to-rc.2
  transition.

Thereafter, missing, malformed, mismatched, or unchained anchor state is a
recovery condition. A manual `git pull`, copied checkout, or changed
`LABCRAFT_MACHINE_DATA_ROOT` cannot create a new genesis anchor merely because
the current app starts.

## Initial rc.6/rc.1 to rc.2 transition

The old deployed versions cannot perform M6 preflight because the code does
not exist yet. Do not pretend that an rc.2 updater receipt can be created
retroactively.

The initial transition remains:

```text
Milestone 0 Desktop + external-drive local/ and VERSION backups
-> old updater or controlled checkout change installs rc.2
-> rc.2 first-start bootstrap runs before MVC/hardware
-> operator selects live local/ or the Desktop backup candidate
-> M2 raw migration backup, copy, and verification
-> M3 source/machine/Camera verification and activation
-> M4/M5 active validation and target authorization
-> M6 creates one genesis deployment anchor
-> future updates must use M6 preservation
```

This enrollment supports both source tags:

- `v1.2.0-rc.6`, whose legacy loaders always use `<repo>/local`; and
- `v1.3.0-rc.1`, whose loaders accept injected roots internally but whose
  deployed `App.py` still resolves the checkout-local store.

The saved Desktop copy remains a valid M2 candidate. M6 does not delete,
rewrite, or absorb the user's off-device Milestone 0 copies.

## Legacy compatibility profiles and export

### Supported exact targets

The initial catalog contains reviewed profiles for:

| Target | Reason |
| --- | --- |
| `v1.2.0-rc.6` | Deployed legacy source and original stable payload line |
| `v1.2.0` | Current stable rollback target; metadata-only promotion of rc.6 payload |
| `v1.3.0-rc.1` | Immediate predecessor/source cohort and possible support target |

Each entry binds tag, resolved commit SHA, required release-manifest hash,
legacy loader contract, mapping rules, required file types, and firmware note.
Tag similarity or release notes are not sufficient. If an existing tag's
resolved commit or manifest does not match the catalog, rollback is blocked;
the tag is never moved or reinterpreted.

### Export mapping

The v1 profiles map:

| Canonical source | Legacy destination |
| --- | --- |
| `config/Settings.json` | `local/Settings.json` |
| `config/Locations.json` | `local/Locations.json` |
| `config/Plates.json` | `local/Plates.json` |
| `config/Obstacles.json` | `local/Obstacles.json` |
| `config/RegulatorProfiles.json` | `local/RegulatorProfiles.json` |
| `CalibrationMemory/**` | `local/CalibrationMemory/**` |
| `calibration/droplet_imager_optics.json` | `local/droplet_imager_optics.json` |
| `calibration/regulator_optimization/**` | `local/regulator_optimization/**` |

Identity, activation, history, backups, locks, and update evidence are not
invented as legacy active files. Unknown canonical paths are reported and
remain canonical-only unless a reviewed profile revision classifies them.

### Rollback authorization gates

Before export, require:

- exact target profile and release commit;
- clean checkout and expected current deployment anchor;
- exact operator name, reason, machine ID, target version, and support case or
  service-record reference;
- explicit acknowledgement that the legacy app lacks M4/M5 enforcement;
- all exported motion targets currently hard-valid and exactly verified;
- no pending config/update/recovery transaction;
- verified backup of canonical data and existing checkout `local/`;
- target firmware requirement plus a reviewed pairing/deployment attestation;
  and
- sufficient space and same-filesystem staging for directory activation.

There is no `--force`, environment bypass, hidden checkbox, or generic
"continue anyway" path.

### Atomic local activation

Stage the complete new `local/` below a transaction-specific workspace beside
the checkout, on the same filesystem. Reject unsafe repository roots and
symlink/reparse boundaries. Validate the staged JSON using the exact profile,
reopen every mapped file, and compare raw/semantic hashes and the safety
snapshot.

Activation uses a journaled two-rename exchange:

1. move existing `<repo>/local` to the transaction workspace, if present;
2. move verified staged `local` to `<repo>/local`;
3. reopen and re-verify the active compatibility tree;
4. append `compatibility_export_verified`; and
5. only then change Git.

The old local directory is already in a verified external archive before the
exchange. Interruption recovery uses exact journal paths and hashes; it never
deletes or guesses among similarly named directories. A pre-Git export failure
restores the prior `local/` when that can be proven exactly and otherwise
enters recovery.

## Legacy session return and conflict handling

The external legacy-session record binds the export manifest, checkout real
path, legacy target commit, baseline raw/semantic hashes, canonical manifest,
and firmware attestation. It remains unresolved throughout legacy operation.

On return to an M6-capable release:

- missing exported `local/` is a conflict;
- added/deleted/changed paths are listed explicitly;
- known JSON gets both raw and semantic comparison;
- coordinate differences include old/new/delta and M5 classifications;
- opaque calibration files use raw hashes and sizes;
- canonical changes during the legacy interval are independently detected;
  and
- all reports are written externally before a decision is offered.

Initial rc.2 resolution choices are deliberately narrow:

1. **Unchanged return.** Exact baseline bytes close the session and allow a
   `legacy_return_unchanged` deployment record.
2. **Keep canonical.** Requires a fresh verified archive of the changed legacy
   tree, typed machine/target confirmation, operator/reason/support reference,
   and an immutable resolution record. It never deletes the archive.
3. **Review legacy changes.** Remains recovery-only. Governed configuration
   must enter through M5 preview/guard and M4 transactions; calibration-memory
   or opaque calibration differences require an explicit support import plan.
   M6 does not bulk overwrite canonical data.

There is no automatic "newest file wins," timestamp merge, semantic-equality
discard, or whole-directory adoption. A later milestone may add a separately
qualified calibration reconciliation service; its absence must not weaken the
fail-closed conflict behavior.

## User and support experience

### Normal forward update

The existing update dialog adds visible stages:

- waiting for LabCraft to close;
- locking machine data;
- validating machine identity;
- creating and verifying backup;
- applying application update;
- verifying preserved machine data; and
- safe to restart, or recovery required.

Before closing the app, the confirmation shows machine ID, external root,
current/target versions, backup destination, firmware note, and that operation
will stop on any mismatch. The final restart control is enabled only by an
external `relaunch_authorized` receipt matching the current target HEAD.

### Failures

Pre-Git failures explain that the application revision was not changed and
offer "Reopen current version" only after the old deployment anchor and live
manifest are revalidated. Post-Git/ambiguous failures show exact evidence
paths, keep the updater/recovery window open, and do not offer normal relaunch
or automatic reset.

### Legacy rollback

The normal UI displays:

- exact rollback target;
- that the target uses checkout-local machine data and lacks modern guards;
- firmware-pairing requirement; and
- "Support authorization required" instead of an enabled restore button.

The support runbook supplies the exact CLI/workflow, required attestations,
expected hashes, stop conditions, and return-to-M6 procedure. Secrets or SSH
credentials are never stored in the transaction.

## Implementation sequence

Implementation remains one Milestone 6 commit, but it is developed and
verified in these eight reviewable slices. Do not start a later mutating slice
until the prior slice's focused tests pass.

### Slice 0: Freeze contracts, target audit, and fixtures

- Record exact tag/commit/manifest fingerprints for `v1.2.0-rc.6`, `v1.2.0`,
  and `v1.3.0-rc.1`.
- Freeze update evidence, release declaration, compatibility-profile, and
  deployment-anchor schemas.
- Capture sanitized rc.6/rc.1 legacy layout fixtures and current M5 canonical
  fixtures, including revoked/verified targets.
- Prove tag loaders use the mapped legacy paths without launching hardware.
- Update the release-process contract text, but do not create rc.2 metadata.

Gate: schemas reject unknown versions/fields where authority is involved,
profile hashes are stable across Windows/Pi, and exact target fingerprints are
reviewed.

### Slice 1: External preservation core and locks

- Add canonical update-lock paths and lock tokens.
- Implement protected inventory, safety snapshot, backup, archive reopen,
  immutable stage records, terminal result, and latest pointer.
- Reuse bounded archive/path/atomic-write primitives.
- Add deterministic interrupted-stage inspection without automatic stale-lock
  deletion.

Gate: fault injection before/after every archive/stage write proves zero Git
commands and exact source preservation.

### Slice 2: Deployment anchor and bootstrap recovery gate

- Implement constrained rc.2 genesis enrollment.
- Validate deployment anchor and unfinished M6 state before MVC/hardware.
- Add recovery-only results for missing/mismatched anchors, pending schema
  transition, post-Git uncertainty, and unresolved legacy sessions.
- Keep the M3 first-start migration path valid when no active store exists.

Gate: correct anchor starts; wrong root/identity/commit and interrupted state
construct zero MVC/hardware objects; rc.6/rc.1 first transition still reaches
M2/M3.

### Slice 3: Forward updater integration

- Pass the exact launch binding from Controller to updater.
- Wrap both online and offline apply operations in the preservation state
  machine.
- Move launcher/updater logs and latest results to external update history.
- Add progress stages and receipt-gated restart behavior to updater window.
- Preserve existing target/tag/bundle validation and fast-forward-only Git
  behavior.

Gate: backup failure, lock race, path/identity/hash drift, Git failure, wrong
target HEAD, and post-check failure all stop at the correct state; online and
offline happy paths produce identical preservation evidence.

### Slice 4: Declared schema-transition recovery

- Extend release manifest validation with the M6 machine-data declaration.
- Add a target bootstrap-recovery adapter registry and no-hardware entry path.
- Journal adapter writes, require M4/M6 migration events, compare full safety
  semantics, and authorize relaunch only after verification.
- Add one synthetic representation-only transition fixture; rc.2 itself
  declares `transition: none` during Milestone 7.

Gate: missing/unknown/failed adapters remain recovery-only; the synthetic
transition preserves values and appends complete evidence; deliberate semantic
drift rejects.

### Slice 5: Exact legacy compatibility export

- Add the tracked exact-tag compatibility catalog and loader.
- Implement reverse mapping, authorization/firmware gates, existing-local
  archive, same-filesystem staging, profile validation, journaled activation,
  and unresolved session record.
- Route only support-authorized legacy rollback through this service before
  the existing verified Git reset.
- Disable normal one-click legacy rollback.

Gate: all three exact profiles export and reopen; unknown/mismatched tags,
revoked targets, malformed data, archive/swap failures, and missing firmware
attestation issue zero reset commands.

### Slice 6: Legacy return comparison and explicit resolution

- Detect unresolved sessions in bootstrap before hardware.
- Produce raw/semantic/path/coordinate/calibration comparison evidence.
- Implement unchanged return and explicit keep-canonical resolution with fresh
  legacy backup and immutable receipt.
- Route reviewed governed imports to M5/M4; leave opaque adoption blocked until
  an explicit support plan exists.

Gate: unchanged return authorizes; byte-only and semantic changes are visible;
missing/add/delete/edit cases remain recovery-only; no path silently writes
canonical data.

### Slice 7: Integrated validation, Pi qualification, and runbooks

- Run focused, full, real-Git, offline-bundle, detached-checkout, writer-
  inventory, and contained SIL gates.
- Run disposable target-Pi no-hardware qualification over SSH.
- Seal non-sensitive evidence and create the M6 completion record.
- Update live/concrete plans, release/update/rollback/recovery runbooks, and
  operator wording.
- Create the dedicated M6 commit only after local validation; mark verified
  only after clean Pi qualification.

Gate: every definition-of-done item passes and no firmware/protocol or machine
data/evidence artifact is included in the commit.

## Files expected to change during implementation

### Machine-data contracts and services

- `FreeRTOS-interface/MachineData.py`
- `FreeRTOS-interface/MachineDataLock.py`
- `FreeRTOS-interface/MachineDataArchive.py` only for reusable bounded archive
  primitives, if required
- new `FreeRTOS-interface/MachineDataUpdate.py`
- new `FreeRTOS-interface/MachineDataCompatibility.py`
- `FreeRTOS-interface/MachineDataBootstrap.py`
- `FreeRTOS-interface/ApplicationComposition.py` as required to expose external
  updater evidence without widening mutation authority
- new tracked compatibility policy under `FreeRTOS-interface/Policies/` or
  `FreeRTOS-interface/Presets/`, with LF enforced in `.gitattributes`

### App/updater integration

- `FreeRTOS-interface/App.py`
- `FreeRTOS-interface/Controller.py`
- `FreeRTOS-interface/View.py`
- `tools/update_and_restart.py`
- `tools/update_window.py`
- `tools/validate_release_metadata.py`
- `tools/create_update_bundle.py` only if the new release field needs explicit
  bundle validation/copy behavior

### Tests

- new `tests/test_machine_data_update_preservation.py`
- new `tests/test_machine_data_deployment_anchor.py`
- new `tests/test_machine_data_legacy_compatibility.py`
- new `tests/test_machine_data_update_recovery.py`
- `tests/test_update_and_restart.py`
- `tests/test_update_window.py`
- `tests/test_app_update_request.py`
- `tests/test_app_machine_data_bootstrap.py`
- `tests/test_safe_application_construction.py`
- `tests/test_machine_data_transactions.py`
- `tests/test_configuration_writer_inventory.py`
- `tests/test_validate_release_metadata.py`
- real-Git and offline-bundle tests already housed in updater test modules

### Documentation

- `docs/release_process.md`
- new `docs/machine_data_update_and_rollback_runbook.md`
- this concrete plan and the parent live plan
- a future M6 completion record after qualification
- operator-facing README/help text if the final UI requires it

### Explicitly not expected

- `FreeRTOS-interface/Machine_FreeRTOS.py`
- motion/pressure protocol modules
- any file under `firmware/`
- firmware artifact changes
- rc.2 `VERSION`, changelog, release manifest, `latest.json`, or tag until M7

If implementation discovers a need to touch those exclusions, stop, document
the call-path expansion and safety rationale, and obtain direction before
editing.

## Automated test plan

### Contracts, paths, and locks

- Update-history/update-lock paths are exact UUID-scoped children of the
  external machine root.
- Checkout-contained, home, root, relative, symlink, junction, traversal, and
  case-collision paths reject.
- Update lock followed by config lock succeeds once and concurrent checkout/
  updater attempts fail with owner evidence.
- Every error releases only locks owned by that token.
- Missing/uncertain stale lock is never silently removed.

### Inventory, safety snapshot, and backup

- Exact active pointer and every included machine file appear once.
- Locks/update history are the only excluded paths.
- Empty required directories restore; special files and changing files reject.
- Raw hashes detect formatting-only JSON changes; semantic hashes distinguish
  representation from value changes.
- Camera Y, rack anchor, one plate corner, bounds, hardware profile,
  authorization, and chain-head mutations each alter the expected evidence.
- Archive write/reopen/manifest/live-recheck failures prevent Git mutation.
- Existing M4 backup files do not cause recursive M6 archives.

### Forward updater

- Missing launch-binding field rejects apply.
- Wrong root, UUID, machine ID, activation/migration ID, active-pointer hash,
  source SHA, or target SHA rejects.
- Config edit between launch and lock acquisition rejects.
- Online and offline paths share identical preflight/postflight calls.
- `git fetch` may occur before backup; merge/reset cannot.
- Exact no-schema update succeeds from a different checkout and preserves
  every protected byte.
- Git apply failure records `failed_before_git` or `recovery_required`
  according to observed HEAD, without an unsafe relaunch.
- Post-Git identity/path/hash mismatch records recovery and disables restart.
- Checkout-local logs/results are no longer authoritative or required.

### Deployment anchor and bootstrap

- Exact rc.2 genesis enrollment succeeds once on a valid legacy migration.
- A second genesis request, deleted anchor with existing chain, manual commit
  change, wrong release, wrong root, or copied mismatched pointer rejects.
- An authorized update receipt advances the anchor atomically.
- New checkout/worktree at the authorized commit reopens the same canonical
  store.
- Pending/invalid update and legacy session state exits before MVC/hardware.
- Existing M3 no-active-store first-start and M4/M5 sequence-zero fixtures
  remain compatible.

### Schema transitions

- `transition: none` permits only exact bytes.
- Missing M6 target declaration, unknown contract/schema/mode/adapter rejects
  before Git.
- Synthetic representation transition preserves complete safety semantics and
  records every file/event.
- Changed/missing Camera, rack, plate, bounds, profile, authorization, or event
  chain rejects transition authorization.
- Adapter exception/interruption leaves recovery-only state and exact backup.
- No recovery entry imports Controller, Model, Machine_FreeRTOS, camera,
  balance, serial, GPIO, or firmware tools.

### Compatibility profiles and export

- Exact tag/commit/manifest profiles load for rc.6, v1.2.0, and rc.1.
- Tag retarget/mismatch, unknown target, version prefix, or modified profile
  rejects.
- All five config files, CalibrationMemory, optics, and regulator files map to
  exact legacy paths.
- Missing required file, malformed top-level type, preset fallback need,
  unclassified active path, or semantic mismatch rejects.
- Revoked/unverified/hard-invalid Camera/rack/plate target rejects before
  export.
- Existing checkout `local/` is archived and verified before activation.
- Faults before/between/after the two renames recover deterministically or
  remain blocked; no fallback presets can be selected silently.
- No `git reset --hard` command is observed until export verification and
  legacy-session record succeed.
- Missing/invalid firmware attestation prevents legacy relaunch.

### Legacy return and conflicts

- Exact unchanged local closes the session and leaves canonical bytes intact.
- Formatting-only JSON rewrite reports raw-different/semantic-equal.
- Camera Y, rack, plate, settings, calibration, addition, deletion, and missing
  local all produce explicit conflicts.
- Keep-canonical requires fresh backup plus exact typed confirmation and never
  deletes comparison/archive evidence.
- Review/import path cannot bypass M5 strong preview, M4 transaction, target
  revocation, or opaque-file blocking.
- No timestamp, mtime, newest-file, directory-wide copy, or implicit semantic
  merge is present.

### UI, logging, and relaunch

- Confirmation displays exact machine/root/current/target/backup/firmware
  information.
- Progress events occur in state-machine order.
- Restart remains disabled without a matching relaunch receipt and target
  HEAD.
- Pre-Git failure offers current-version reopen only after revalidation.
- Post-Git/ambiguous failure never offers normal relaunch.
- Legacy target displays support-required state and cannot call rollback apply
  through the normal button.
- External log/result paths survive checkout change and avoid coordinates in
  normal user-facing summaries.

### Fault-injection boundaries

Inject interruption or exception:

- before/after each stage record;
- during inventory and archive streaming;
- before/after archive rename and verification;
- before/after Git merge/reset;
- before/after target HEAD verification;
- before/after deployment-anchor replace;
- before/between/after legacy directory exchange; and
- before/after legacy resolution.

For every boundary assert exact live bytes, remaining evidence, lock release,
Git command count, relaunch authorization, and deterministic next-start state.

### Regression and zero-command safety

- M2 candidate/backup/migration tests continue to pass.
- M3 bootstrap/authorization/lifecycle tests continue to pass.
- M4 transaction/recovery/history/exact-restore tests continue to pass.
- M5 guard, capture, hard-bound, authorization, and zero-command tests
  continue to pass.
- Update/recovery imports construct no hardware and enqueue zero firmware
  commands.
- Firmware protocol golden vectors remain unchanged.

## Windows validation gates

Run focused files after each slice. Before the dedicated implementation
commit, run at minimum:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_machine_data_update_preservation.py `
  tests\test_machine_data_deployment_anchor.py `
  tests\test_machine_data_legacy_compatibility.py `
  tests\test_machine_data_update_recovery.py `
  tests\test_update_and_restart.py `
  tests\test_update_window.py `
  tests\test_app_update_request.py `
  tests\test_app_machine_data_bootstrap.py `
  tests\test_safe_application_construction.py `
  tests\test_machine_data_transactions.py `
  tests\test_configuration_writer_inventory.py `
  tests\test_validate_release_metadata.py

.\env\Scripts\python.exe -m pytest -q

.\env\Scripts\python.exe tools\validate_release_metadata.py

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario virtual_print_array_96_v1 `
  --output-root <external-output-root> `
  --warmup-runs 0 --measured-runs 1 `
  --host-label windows-m6-update-preservation

git diff --check
```

Use at least 900,000 ms for the full suite and an external pytest/SIL temporary
root. Compile each changed Python module with the project interpreter. Run the
configuration writer inventory plus a new updater Git-mutation inventory that
asserts every merge/reset site is behind preservation authorization.

Do not run `--check-tags` or edit release metadata until the later Milestone 7
release commit exists.

## Target-Pi disposable no-hardware qualification

Use the existing qualification target only after the dedicated M6 commit is
pulled into a clean checkout:

- host: `labcraft@192.168.0.33`
- SSH identity:
  `verification_reports\pi_sil_codex_network_ed25519`
- repository: `/home/labcraft/LabCraft_printer`
- interpreter: `/home/labcraft/LabCraft_printer/env/bin/python`

The procedure uses disposable repositories and machine-data roots under
`/tmp`. It must not move the production checkout's branch/HEAD, launch the
production `App.py`, connect serial/camera/balance/GPIO, enable/home motors,
send commands, or flash firmware.

Required sequence:

1. Record exact implementation commit, clean production checkout, Python/Git
   versions, policy/profile hashes, and prove no `App.py` process is running.
2. Create a fresh `/tmp` canonical copy from the verified M5 sequence-zero
   baseline and a disposable local Git clone/worktree containing required
   tags; record all real paths and hashes.
3. Enroll an M6 deployment anchor on the disposable store; reopen from two
   detached checkouts and prove the same root/identity/bytes with zero
   hardware imports or commands.
4. Run a synthetic no-schema forward update between local signed-off fixture
   commits. Prove verified external backup precedes merge, protected bytes are
   exact, HEAD is correct, relaunch receipt exists, and a detached checkout
   validates it.
5. Repeat the forward flow through a release-aware offline bundle and compare
   evidence shape with the online/local-remote path.
6. Inject backup failure, lock contention, active-pointer/root/identity drift,
   config drift, wrong target HEAD, and post-Git hash drift. Prove zero merge
   before backup and no relaunch after ambiguous mutation.
7. Run the synthetic bootstrap schema transition, prove complete safety
   semantics and event evidence, then restore the disposable baseline for the
   legacy tests.
8. Export each exact legacy profile into a disposable checkout without
   launching its `App.py`; run pure target loaders/no-hardware validation and
   prove raw/semantic equality. Unknown target and revoked Camera fixtures must
   issue zero reset commands.
9. Complete one disposable legacy Git rollback, modify a synthetic Camera Y in
   its `local/`, return to M6, and prove bootstrap enters conflict recovery
   before MVC/hardware. Archive the comparison; do not adopt or move to the
   synthetic value.
10. Exercise unchanged-return and explicit keep-canonical on separate fresh
    copies; prove canonical exact bytes, external receipts, and no pending
    transaction.
11. Run focused Pi tests, the existing zero-command safety gate, and contained
    `virtual_print_array_96_v1` with 96/96 expected and all hardware disabled.
12. Seal logs, manifests, receipts, profile/commit hashes, and results with a
    SHA-256 manifest; recheck it, copy the archive to ignored local
    `verification_reports/`, and record only non-sensitive totals/hashes in the
    completion record.

Any command that could change the real Pi checkout, default machine-data root,
or hardware state is outside this qualification and requires a separate
attended Milestone 7 procedure.

## Manual release and deployment checklist for Milestone 7

M6 verification does not itself tag rc.2. During M7:

1. re-read `docs/release_process.md`;
2. create the rc.2 release manifest with the exact M6 `machine_data`
   declaration and correct firmware requirement;
3. validate metadata before tagging and again with `--check-tags` after the
   local tag exists;
4. perform the controlled rc.6-to-rc.2 and rc.1-to-rc.2 first-start migrations;
5. verify the genesis deployment anchor on each source cohort;
6. perform attended firmware pairing and physical safety qualification; and
7. stage rollout only after both source cohorts pass.

No deployed legacy machine is expected to have an M6 preflight receipt for its
first rc.2 update. Every later update from rc.2 must have one.

## Rollback strategy for M6 implementation

### Before any M6 external record exists

Revert the M6 implementation commit in development and retain test evidence.
M1-M5 canonical stores remain unchanged. Do not remove the user's Milestone 0
backups.

### After genesis enrollment but before an M6 update

Preserve `update_history/` and the deployment anchor. Older application code
may ignore it but also lacks M6 enforcement, so reverting to M5 code is a
development diagnostic only, not an approved production operating state.

### After a verified forward update

Do not delete receipts or rewrite the deployment anchor. A code rollback must
itself use the qualified M6 rollback path or remain recovery-only. The exact
pre-update archive is retained for support restoration; it is not applied
automatically.

### After compatibility export or legacy operation

Do not revert M6 support code or delete the legacy-session record until the
session is explicitly resolved. Preserve canonical, legacy, existing-local,
comparison, and firmware evidence. If automated legacy rollback cannot pass
qualification, keep normal legacy rollback disabled and use the documented
manual support procedure; do not weaken export checks.

### Failure after Git mutation

Keep hardware stopped, preserve the updater window/logs and exact transaction
directory, and do not run an ad hoc `git reset --hard`. Support must establish
current HEAD, target tag, external root/identity, protected hashes, backup
validity, and firmware state before choosing forward completion or controlled
rollback.

## Definition of done

Milestone 6 is `verified` only when:

- update/apply commands require an exact authorized machine-data launch
  binding;
- update/config locks prevent cross-checkout and configuration-write races;
- a complete external archive is reopened and verified before every Git
  mutation;
- no-schema online and offline updates preserve exact protected bytes;
- post-update root, identity, activation, pointer, safety snapshot, and target
  HEAD are verified before relaunch authorization;
- deployment anchors detect unauthorized commit/root changes before
  MVC/hardware construction;
- initial rc.6 and rc.1 first-start migration remains supported without a
  fictitious old-updater receipt;
- declared schema transitions are recovery-only, journaled, audited, and prove
  semantic safety equality;
- logs/results/receipts/backups survive checkout and worktree changes;
- exact profiles for rc.6, v1.2.0, and rc.1 create verified legacy exports;
- normal one-click legacy rollback is disabled and unknown targets fail;
- revoked/hard-invalid targets or missing firmware attestation prevent legacy
  relaunch;
- re-upgrade detects all legacy differences and never silently overwrites
  canonical data;
- unchanged return and keep-canonical resolution retain complete evidence;
- every pre/post Git and directory-swap fault boundary has deterministic,
  fail-closed tests;
- all M1-M5 regression, full-suite, metadata, real-Git, offline-bundle,
  detached-checkout, writer/Git-mutation inventory, and contained SIL gates
  pass;
- clean target-Pi disposable no-hardware qualification and evidence sealing
  pass;
- no firmware/protocol or physical hardware behavior changes; and
- one dedicated Milestone 6 implementation commit contains code/tests/docs,
  with no machine data, credentials, generated logs, or qualification archive.

## Progress checklist

- [x] Audit current update/rollback check and apply call paths.
- [x] Audit external machine-data lock/lifecycle and updater log locations.
- [x] Audit exact rc.6, v1.2.0, and rc.1 legacy targets/layouts.
- [x] Define preservation, deployment-anchor, schema-transition, compatibility,
  and legacy-return contracts.
- [x] Define eight implementation slices, file inventory, test matrix, Pi gate,
  and rollback strategy.
- [x] Implement Slice 0 contracts and fixtures.
- [x] Implement Slices 1-6 tests-first.
- [x] Complete local Slice 7 validation.
- [ ] Create dedicated Milestone 6 implementation commit.
- [ ] Complete target-Pi no-hardware qualification and evidence preservation.
- [ ] Create completion record and mark both plans `verified`.

## Local implementation record

Implemented on 2026-08-20, before the dedicated milestone commit:

- exact external launch binding, `update.lock -> configuration.lock`, protected
  inventory, safety snapshot, reopened ZIP backup, immutable stage chain,
  deployment anchor, and receipt-gated updater UI;
- online/offline forward integration and protected M6-to-M6 rollback around
  the existing verified Git operations;
- constrained rc.2 genesis enrollment and pre-MVC detection of unauthorized
  commits, unfinished updates, and unresolved legacy sessions;
- target-side hardware-free schema adapter registry with one synthetic
  representation-only adapter, M4 transaction event, semantic-safety proof,
  and recovery-only failure behavior;
- exact compatibility catalog/export for `v1.2.0-rc.6`, `v1.2.0`, and
  `v1.3.0-rc.1`, including target authorization, existing-local backup, and
  firmware-attestation gates before Git reset;
- exact legacy-return comparison, automatic unchanged resolution, explicit
  keep-canonical backup/receipt, and fail-closed Camera-Y conflict handling;
- external diagnostic logs/operator summaries separated from the immutable
  latest-result authority; and
- release/runbook validation requiring the M6 manifest declaration for rc.2
  and later, without editing rc.2 release metadata in this milestone.

Local gates passed:

- 331 focused tests;
- 5,402 full-suite tests passed and 156 skipped;
- release metadata validation;
- compilation of every changed Python module;
- contained `virtual_print_array_96_v1`: 96/96, hardware-disabled; and
- `git diff --check` (line-ending notices only on Windows).

The milestone is not yet `verified`: it still requires the dedicated commit,
a clean pull on the target Pi, the disposable no-hardware qualification, and
sealed evidence/completion documentation.

One discarded full-suite attempt placed pytest's base temporary directory
inside the repository. Thirty-three SIL/session isolation tests correctly
rejected that topology. Repeating with a fresh absolute OS-temporary root
passed 5,402/5,402 runnable tests; the discarded run is not counted as product
validation.

## Planning findings

1. The updater already separates read-only checks from apply, validates online
   and offline release targets, waits for the application PID, requires a clean
   checkout, and uses fast-forward merge for updates. M6 can wrap those proven
   Git operations instead of replacing them.
2. Waiting for the App PID releases the production lifetime configuration
   lock, but another checkout can currently acquire it before or during Git
   mutation. A dedicated update lock plus reacquired configuration lock closes
   that race.
3. `MachineDataPaths.update_history_root` already exists but is unused by the
   updater. Current launcher/updater logs and `latest_update_result.json` live
   under `<repo>/local/update_logs`, so they are checkout-specific and can be
   hidden or replaced by rollback.
4. Controller currently passes repository/Python/PID/GUI flags but no external
   root or machine identity. An apply subprocess can therefore not prove it is
   protecting the same authorized machine that requested the update.
5. Current rollback executes verified `git reset --hard` before any legacy
   compatibility export. That order is unacceptable once canonical data is
   outside the checkout.
6. `v1.3.0-rc.1` declares rollback to `v1.2.0`. The v1.2.0 manifest states that
   it is a metadata-only promotion of the deployed `v1.2.0-rc.6` payload, but
   compatibility still needs an exact profile for each immutable tag/commit.
7. Both deployed source cohorts actively use `<repo>/local`. Their legacy
   active surface is the five JSON configs, CalibrationMemory, droplet-imager
   optics, and regulator optimization data.
8. Old releases cannot enforce M4 target authorization or M5 hard guards.
   Exporting a revoked or invalid target into an old app would re-enable unsafe
   movement, so support rollback must require complete current authorization.
9. Release manifests currently have firmware requirements but no machine-data
   preservation declaration. M6 must extend validation before rc.2 metadata is
   created in M7.
10. The updater process continues running old code after Git changes. Exact
    no-schema verification can safely finish there; intentional target-schema
    work belongs in a separately constrained target bootstrap recovery path.
11. A verified external backup prevents data loss but does not by itself prove
    safe relaunch. Relaunch authority must be a later receipt that binds
    post-update data and target HEAD.
12. A legacy app can rewrite JSON formatting even when values are unchanged.
    Recording raw and semantic comparison separately avoids confusing a
    representation change with a coordinate change while still preserving the
    audit fact.
13. The initial legacy-to-rc.2 move cannot satisfy a future-updater preflight.
    A constrained one-time deployment anchor after M2/M3 validation is the
    honest bridge; later missing receipts must fail closed.
14. Automatic rollback after an ambiguous post-Git failure could compound the
    incident. Recovery-only state with preserved evidence is safer and more
    reviewable.

## Frozen planning decisions

| Decision | Milestone 6 direction |
| --- | --- |
| Default update data rule | Exact protected bytes; no semantic-only pass when `transition: none` |
| Schema changes | Declared target bootstrap recovery adapter; unknown transitions block |
| Backup scope | Active pointer plus all active machine files except locks and update history |
| Authoritative evidence | Immutable external stage chain; logs/latest pointer are diagnostic |
| Lock order | `update.lock` then `configuration.lock`, retained through post-verification |
| First rc.2 transition | Existing M2/M3 migration plus one constrained genesis anchor |
| Legacy targets | Exact profiles for rc.6, v1.2.0, and rc.1 only |
| Legacy UI | Normal one-click rollback disabled; support-guided flow only |
| Legacy target state | Every exported motion target must be hard-valid and verified |
| Firmware | Explicit pairing attestation recorded; no automatic flash/downgrade |
| Dual writes | Prohibited |
| Legacy differences | Fail-closed conflict, even if JSON is semantically equal |
| Conflict adoption | Never automatic; governed changes use M5/M4, opaque changes remain support-reviewed |
| Post-Git failure | Recovery-only; no automatic Git reset or machine-data overwrite |

## Open implementation measurements

These do not change the safety defaults and are resolved in Slice 0 or during
qualification:

- maximum archive file/count/total-size limits based on current canonical
  fleet inventories with conservative headroom;
- filesystem free-space headroom and retained-backup policy;
- QLockFile behavior and directory fsync support on the deployed Pi filesystem;
- exact rc.6/v1.2.0/rc.1 tag commit and release-manifest hashes recorded in the
  tracked compatibility catalog;
- same-filesystem rename behavior for the Pi checkout parent and Windows
  development layout; and
- final operator confirmation text and support service-record format.

If any measurement cannot be established, implementation keeps the relevant
operation disabled rather than adding a bypass.

## Document change log

| Date | Change |
| --- | --- |
| 2026-08-20 | Created the concrete post-Milestone-5 update preservation, deployment anchor, schema-transition recovery, exact legacy compatibility export, conflict handling, eight-slice implementation, Windows/Pi qualification, and rollback plan. |
| 2026-08-20 | Implemented Slices 0-6 and completed local Slice 7 gates: 331 focused, 5,402 full passed/156 skipped, metadata/compile/diff validation, and contained SIL 96/96. Dedicated commit and target-Pi qualification remain pending. |
