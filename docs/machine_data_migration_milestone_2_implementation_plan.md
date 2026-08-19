# Machine Data Migration Milestone 2: Inert Engine Implementation Plan

Status: `implementation_complete`

Prepared: 2026-08-19

Parent plan:
`docs/machine_data_migration_and_location_safety_plan.md`

Depends on:
Milestone 1 commit `9b882141`

Target release: `v1.3.0-rc.2`

## Outcome

Milestone 2 will implement an inert, directly callable migration and backup
engine. It will inspect explicitly supplied legacy candidates, create and
reopen a verified full-source backup, construct a canonical machine tree in a
same-filesystem staging area, verify the staged copy, and atomically publish a
new UUID-keyed machine tree in the `copied_unverified` state.

Milestone 2 will not:

- run during production startup;
- select a candidate on the operator's behalf;
- write `active_machine.json`;
- mark source or calibration verification complete;
- change `ApplicationRoots.production()`;
- load configuration from the external store;
- construct the Model, View, Controller, or hardware;
- authorize saved-location movement;
- modify the updater, firmware, protocol, pressure, or motion behavior.

The externally published copy is therefore durable but inactive. Milestone 3
will own operator selection, identity assignment when necessary, source and
calibration verification, startup integration, and activation.

## Preserved production call path

Production remains unchanged throughout Milestone 2:

```text
App.main()
-> get_machine_config_path("Settings.json")
-> LocalConfig.LOCAL_DIR == <repo>/local
-> production_dependencies()
-> ApplicationRoots.production() with None roots
-> Model(config_root=None, calibration_memory_root=None)
-> LocalConfig paths beneath <repo>/local
```

The new engine is reachable only through an explicit caller or test:

```text
explicit test/support caller
-> resolve MachineData base and target UUID paths
-> acquire base-scoped migration lock
-> inspect one or more explicitly supplied candidates
-> caller explicitly chooses one candidate
-> snapshot candidate into verified backup archive
-> stage canonical tree from that verified archive
-> verify stage and atomically rename it to machines/<uuid>
-> write copied_unverified receipt
-> return evidence; do not activate
```

No `App.py`, MVC, or updater import of these APIs is permitted in this
milestone.

## Repository evidence frozen into the plan

The following facts were verified from the two supported source tags:

1. Both `v1.2.0-rc.6` and `v1.3.0-rc.1` store machine configuration beneath
   ignored `<repo>/local` and seed it from tracked presets when files are
   missing.
2. Both tags require the same five top-level machine config files:
   `Settings.json`, `Plates.json`, `Locations.json`, `Obstacles.json`, and
   `RegulatorProfiles.json`.
3. Both tags ship the five CalibrationMemory seed JSON files currently exposed
   by `LocalConfig.calibration_memory_seed_top_level_types()`.
4. Both tracked `Locations.json` presets contain the same lowercase `camera`
   value: `X=11563`, `Y=39550`, `Z=99388`.
5. The rc.1 preset adds `MACHINE_LOG_PORT` to `Settings.json`; therefore a
   historical rc.6 preset cannot be identified reliably by comparing all five
   files only to the current checkout's presets.
6. rc.1 adds explicit `local_root` arguments to LocalConfig, but the persisted
   JSON shapes remain compatible with rc.6.
7. Legacy `machine_identity.json` is optional, may be generated as
   `LC-UNASSIGNED`, and is not sufficient to authorize activation.
8. Known machine-owned data outside the five configs and CalibrationMemory
   includes `droplet_imager_optics.json` and `regulator_optimization/`.
   Milestone 3 planning classified both as machine calibration data, so
   Milestone 2 imports them into a canonical `calibration/` subtree when
   present. Unknown additional files remain fully backed up and explicitly
   unclassified.

No deployed customer backup is copied into the repository or used as a test
fixture. Test values must be synthetic and clearly labeled.

## Frozen design decisions

### 1. Separate inspection, selection, and import

Candidate inspection is pure with respect to the candidate and canonical
store. It returns immutable evidence. Candidate selection is an explicit
input; the engine never treats discovery precedence, timestamps, or version
numbers as permission to choose.

The engine may classify candidates as duplicates or conflicts, but only the
later Milestone 3 workflow can collect an operator choice and reason.

### 2. Discovery is explicit and shallow

Supported inputs are:

- the current checkout, supplied explicitly as a repository root;
- a directly selected `local/` directory;
- a selected wrapper directory whose direct child is `local/`;
- a selected supported ZIP backup;
- an existing canonical target, but only for reconciliation/inspection.

The engine does not recursively search Desktop, drives, home directories, Git
worktrees, or neighboring folders. Selecting a directory that simultaneously
looks like a direct local root and contains another `local/` candidate is
ambiguous and fails closed.

### 3. Candidate kinds are explicit provenance

Initial source kinds are:

```text
current_checkout_local
operator_selected_local
operator_selected_wrapper
operator_selected_zip
existing_canonical
```

The kind, normalized source root, version-evidence path, inspection timestamp,
and caller-supplied label are recorded. The manifest does not infer source
kind from a path name after normalization.

### 4. Five configuration files are mandatory

All five LocalConfig-managed machine config files must exist and pass the
existing top-level type contract. Missing files are fatal. Milestone 2 never
calls `get_machine_config_path()` on a candidate or target because that API
would seed missing values from presets.

Additional fail-closed shape checks are limited to what is necessary to copy
and display safety evidence:

- every named location is an object with finite numeric `X`, `Y`, and `Z`;
- booleans do not count as numeric coordinates;
- the reserved lowercase `camera` location must exist and have those axes;
- each plate is an object;
- an empty plate `calibrations` object is allowed;
- a nonempty plate calibration must contain `top_left`, `top_right`,
  `bottom_right`, and `bottom_left`, each with finite numeric `X`, `Y`, `Z`.

Geometric plausibility, travel bounds, corner orientation, collision
envelopes, and movement authorization remain Milestones 3 and 5 work.

### 5. CalibrationMemory is optional but never synthesized

If `CalibrationMemory/` exists, all safe regular files beneath it are included
in the migratable tree and all known seed JSON files present are validated.
Missing known seed files are reported; they are not copied from the tracked
template during migration.

If the directory is absent, candidate evidence records
`calibration_memory_status=absent`. This is a visible warning and never causes
the engine to seed a replacement. Milestone 3 decides whether the physical
machine may proceed without that state.

### 6. Identity is evidence, not an automatic assignment

Inspection accepts an absent legacy identity and can parse an assigned or
`LC-UNASSIGNED` legacy identity as evidence. It never generates a UUID.

Canonical import requires the caller to provide a valid assigned
`MachineIdentity`. This gives the target UUID and canonical identity sidecar.
If the candidate contains an assigned identity, its UUID and machine ID must
match the supplied target identity. A mismatch is an identity conflict. An
absent or unassigned legacy identity is recorded as such and keeps the result
unverified.

Milestone 3 owns any operator-mediated identity assignment before invoking the
import API.

### 7. Preserve everything in backup; import only classified data

The full-source backup includes every safe regular file under the selected
legacy `local/`, plus adjacent `VERSION` evidence when present and an optional
explicitly supplied firmware artifact. It rejects symlinks, junction-like
escapes where detectable, special files, path traversal, and case-colliding
relative paths.

The canonical tree imports only:

- the five mandatory config files into `config/`;
- the complete safe CalibrationMemory tree when present;
- `droplet_imager_optics.json` into
  `calibration/droplet_imager_optics.json` when present;
- `regulator_optimization/` into
  `calibration/regulator_optimization/` when present;
- the caller-supplied canonical machine identity into `metadata/`;
- migration receipt/evidence and the verified backup.

Other unknown files are retained in the archive and listed in
`unclassified_source_paths`. They are not deleted from the source and are not
quietly copied into an arbitrary canonical location. Their final ownership
must be resolved before Milestone 3 cutover.

### 8. The verified backup is the copy source

The engine first snapshots the selected candidate into a backup archive and
reopens the archive to verify every manifest entry. Canonical staging reads
from that verified archive, not from the live candidate.

This prevents a source file changed during migration from producing a backup
of one state and a canonical copy of another. The engine also compares the
pre-snapshot candidate fingerprint with the archive fingerprint; a detected
source change produces `source_changed` and no canonical publication.

### 9. Raw and semantic hashes have different purposes

All byte hashes use lowercase SHA-256 hexadecimal strings.

- `raw_sha256`: proves exact bytes copied into the archive and canonical tree.
- `semantic_json_sha256`: hashes UTF-8 canonical JSON using sorted keys and
  compact separators; it detects equal JSON values despite formatting.
- `required_config_fingerprint`: canonical hash of the five relative paths,
  sizes, and raw hashes.
- `migratable_tree_fingerprint`: canonical hash of all classified import paths
  and raw hashes.
- `full_source_fingerprint`: canonical hash of every archived source member.

Exact duplicates have equal migratable-tree fingerprints. Candidates with
equal five-file fingerprints but different CalibrationMemory or identity
evidence are `config_duplicates_with_optional_conflict`. Any other difference
is a conflict; neither result authorizes automatic winner selection.

### 10. Historical preset detection uses a checked-in catalog

Milestone 2 adds a small versioned catalog generated from the five preset JSON
files in `v1.2.0-rc.6` and `v1.3.0-rc.1`. It stores semantic hashes and the
semantic hash of the reserved `camera` coordinate object, not machine/customer
data.

Candidate classification records:

- complete match to a known historical preset set;
- which individual config files match known presets;
- whether `camera` alone matches any known preset;
- mismatch between declared `VERSION` and matched preset cohort.

A complete match is `preset_like`. A camera-only match is
`camera_preset_match`. Both remain unverified. The catalog is validated against
tag-derived synthetic fixtures in tests and does not require `.git` or tags at
runtime.

### 11. ZIP handling is hostile-input handling

Supported ZIP layouts are exactly:

```text
local/<source files>
VERSION
```

or:

```text
<one-wrapper>/local/<source files>
<one-wrapper>/VERSION
```

A ZIP whose root directly contains the five config files is also accepted as
an explicitly selected direct-local archive. Multiple wrappers/candidates are
ambiguous.

Before reading content, the archive reader rejects:

- absolute, drive-qualified, backslash, empty, dot, or `..` member paths;
- duplicate normalized names;
- Windows case-folding collisions;
- symlink/special-file Unix modes;
- encrypted members;
- unsupported compression methods;
- members exceeding configured size/count/total-size limits;
- suspicious compression ratios above the configured policy;
- CRC or truncated-data failures.

The initial policy object defaults to 100,000 files, 4 GiB per member, 20 GiB
total uncompressed bytes, and a 200:1 maximum compression ratio. Limits are
injectable in tests and must be rechecked against the target Pi storage during
Milestone 7. Exceeding a limit stops safely and never partially extracts.

### 12. Backup archive format is self-describing and reverified

The engine creates a ZIP with this logical layout:

```text
manifest.json
source/local/<all safe source files>
source/VERSION                         # when present
source/firmware/LabCraft_firmware.bin # only when explicitly supplied
```

The manifest schema is `labcraft.machine_backup_manifest`, version 1. It
includes:

- migration ID and UTC timestamp;
- source kind, path, label, and source-version evidence;
- target machine ID/UUID when supplied;
- every archive member's relative path, size, and raw SHA-256;
- required, migratable, and full-source fingerprints;
- all named location coordinates;
- plate four-corner values where present;
- preset and camera-match indicators;
- legacy identity status;
- CalibrationMemory status;
- unclassified source paths;
- firmware artifact hash explicitly labeled package evidence, not installed
  firmware proof;
- archive policy limits and intentionally omitted items.

Archive construction streams files, flushes and fsyncs the temporary archive,
atomically renames it, reopens it, checks member names/CRC/sizes/hashes, and
then hashes the completed ZIP itself. Only then is the backup `verified`.

### 13. Staging and locking are base-scoped

The target machine root must not be created merely to acquire its lock.
Milestone 2 therefore defines contained workspace paths:

```text
<base>/locks/migration-<machine_uuid>.lock
<base>/migration_work/<machine_uuid>/<migration_id>/
  journal.json
  source_backup.zip
  staged_machine/
```

The lock is implemented by a small Qt `QLockFile` adapter because PySide is an
existing dependency and the application already uses that primitive. The
standard-library migration core receives an acquired lock context and does not
import Qt. Lock contention fails immediately with the lock path and diagnostic
owner information where Qt supplies it.

Stale-lock behavior must be tested against the pinned project Qt version. The
engine must not call `removeStaleLockFile()` automatically when ownership is
uncertain. Milestone 3 will provide the user-facing recovery instruction.

### 14. Publish the complete machine tree with one rename

The engine constructs the entire future machine root under
`staged_machine/`, including config, CalibrationMemory, metadata, receipt, and
verified migration backup. It validates every staged raw hash and JSON shape.

Publication is a same-filesystem atomic rename from `staged_machine/` to:

```text
<base>/machines/<machine_uuid>/
```

The destination must not exist. The engine never merges, overlays, or deletes
an existing machine root. If the destination exists, reconciliation must prove
that it belongs to the same migration and exactly matches the recorded hashes;
otherwise the result is `target_conflict` or `recovery_required`.

Because `active_machine.json` is untouched, even a successfully published
tree is inactive.

### 15. Journal and receipt use a restricted state machine

Schemas:

```text
labcraft.migration_journal v1
labcraft.migration_receipt v1
```

Milestone 2 transitions are:

```text
candidate_selected
-> source_validated
-> backup_verified
-> staged_copy_verified
-> copied_unverified
```

Terminal/error classifications include:

```text
invalid_source
ambiguous_source
identity_conflict
source_changed
backup_failed
copy_failed
target_conflict
recovery_required
lock_unavailable
```

The receipt always contains:

```text
activation_authorized: false
source_verified: false
calibration_verified: false
```

Milestone 2 exposes no API that can set those values to true.

Every persisted transition contains the migration ID, prior/current state,
timestamp, source/target fingerprints, artifact paths relative to the base,
and failure checkpoint when applicable. Unknown schema versions or illegal
state regressions fail closed.

### 16. Recovery verifies rather than assumes

On restart or a repeated direct call:

- if only a workspace journal exists, revalidate every referenced artifact and
  resume from the last trustworthy transition;
- if a stage exists, verify it before retrying publication;
- if the target appeared after an interrupted rename, compare every expected
  path/hash and finalize only when exact;
- if a final `copied_unverified` receipt and hashes match, return the existing
  result idempotently;
- if source, stage, journal, receipt, or target disagree, stop with
  `recovery_required` and preserve all evidence;
- after successful final verification, remove only the now-empty/redundant
  workspace for that migration.

The engine never repairs a mismatch by selecting the newest file, overlaying
trees, deleting a target, or falling back to presets.

### 17. Durability and free-space checks are explicit

JSON journals and receipts use temporary files in the destination directory,
flush, `fsync`, and `os.replace`. Archive and copied-file writes are streamed,
flushed, and fsynced. Directory fsync is attempted on platforms that support it
and recorded as unsupported rather than falsely claimed on other platforms.

Before backup and stage construction, the engine estimates required space from
the inspected source and calls `shutil.disk_usage` on the canonical base's
existing ancestor. The policy requires the estimated archive plus staged tree
plus a configurable safety margin. A failed preflight or later short write is
fatal and fault-injection tested.

### 18. Time, UUIDs, filesystem actions, and faults are injectable

The core accepts injected UTC-clock and migration-ID factories. A narrow file
operations adapter owns open/write/fsync/replace/rename operations and invokes
a fault hook at named durability boundaries. Tests can therefore inject
failures without filling a real disk or corrupting repository files.

No production path uses a no-op lock or disables verification. Test-only
adapters must be passed explicitly.

## Proposed modules and responsibilities

### `MachineDataArchive.py`

Standard-library-only archive and evidence primitives:

- safe directory-tree enumeration;
- hostile ZIP member validation;
- streaming SHA-256;
- canonical JSON hashing;
- manifest schema parsing/serialization;
- full-source backup creation and reopening verification;
- verified archive member streaming for staging.

It never imports Qt, MVC, updater, or hardware modules.

### `MachineDataMigration.py`

Standard-library migration domain and orchestration:

- immutable candidate/evidence/result values;
- shallow candidate normalization;
- required JSON and safety-snapshot validation;
- historical preset classification;
- candidate duplicate/conflict classification;
- contained workspace paths;
- journal/receipt schemas and transition validation;
- staged canonical tree construction from a verified archive;
- exact target publication and reconciliation;
- injectable file operations and fault checkpoints.

It consumes the Milestone 1 `MachineData` values and public LocalConfig
inventories. It does not import App, ApplicationComposition, MVC, updater, or
hardware code.

### `MachineDataLock.py`

Small Qt adapter:

- create parent lock directory;
- acquire one UUID-scoped `QLockFile` without waiting;
- return a context object required by the engine;
- expose safe contention diagnostics;
- release deterministically.

No lock is acquired at module import.

### Historical preset fingerprint catalog

Add a versioned JSON catalog under `FreeRTOS-interface/Presets/`. A small
test/tool helper may regenerate it from reviewed fixture inputs, but runtime
code only reads the checked-in catalog and validates its schema.

## Proposed Python API surface

Exact naming may be adjusted during tests-first implementation, but equivalent
separation and invariants are required.

```python
@dataclass(frozen=True)
class CandidateSelection:
    source_kind: CandidateSourceKind
    selected_path: Path
    label: str = ""


@dataclass(frozen=True)
class CandidateEvidence:
    candidate_id: str
    source_kind: CandidateSourceKind
    normalized_source: Path
    version_text: str | None
    required_files: tuple[FileEvidence, ...]
    migratable_files: tuple[FileEvidence, ...]
    required_config_fingerprint: str
    migratable_tree_fingerprint: str
    safety_snapshot: Mapping[str, object]
    identity_status: str
    calibration_memory_status: str
    preset_matches: tuple[str, ...]
    camera_preset_match: bool
    unclassified_source_paths: tuple[str, ...]
    issues: tuple[CandidateIssue, ...]


def inspect_candidate(
    selection: CandidateSelection,
    *,
    preset_catalog: PresetFingerprintCatalog,
    archive_policy: ArchivePolicy,
) -> CandidateEvidence:
    ...


def classify_candidates(
    candidates: Sequence[CandidateEvidence],
) -> CandidateComparison:
    ...


def create_verified_backup(
    candidate: CandidateEvidence,
    *,
    workspace: MigrationWorkspacePaths,
    target_identity: MachineIdentity | None,
    io: MigrationFileOps,
) -> VerifiedBackup:
    ...


def import_verified_candidate(
    candidate: CandidateEvidence,
    backup: VerifiedBackup,
    *,
    target_paths: MachineDataPaths,
    target_identity: MachineIdentity,
    acquired_lock: AcquiredMigrationLock,
    io: MigrationFileOps,
) -> MigrationResult:
    ...


def reconcile_migration(
    *,
    workspace: MigrationWorkspacePaths,
    target_paths: MachineDataPaths,
    acquired_lock: AcquiredMigrationLock,
    io: MigrationFileOps,
) -> MigrationResult:
    ...
```

`CandidateEvidence` alone is not proof of a stable snapshot. Only
`VerifiedBackup` may be used as the source for `import_verified_candidate`.

## Schemas and canonical records

### Candidate issue severity

```text
info
warning
fatal
```

Fatal issues make `is_importable` false. Preset and missing-optional-state
issues are warnings that remain visible in the receipt and later UI; they do
not become verification.

### Receipt minimum fields

```json
{
  "schema_name": "labcraft.migration_receipt",
  "schema_version": 1,
  "migration_id": "00000000-0000-0000-0000-000000000002",
  "state": "copied_unverified",
  "machine_id": "LC-001",
  "machine_uuid": "00000000-0000-0000-0000-000000000001",
  "source_kind": "operator_selected_wrapper",
  "source_version": "v1.3.0-rc.1",
  "required_config_fingerprint": "<sha256>",
  "migratable_tree_fingerprint": "<sha256>",
  "backup_archive_sha256": "<sha256>",
  "preset_like": false,
  "camera_preset_match": false,
  "activation_authorized": false,
  "source_verified": false,
  "calibration_verified": false,
  "completed_at_utc": "2026-08-19T12:00:00Z"
}
```

Artifact paths in journal/receipt records are relative to the validated
machine-data base. Absolute paths may appear only as source diagnostic
provenance and are never used without re-normalization and containment checks.

## Implementation sequence

Milestone 2 is one reviewable implementation commit with these internal
slices. At most one slice is active at a time.

### Slice 1: Contract tests and immutable values

Add tests first for schemas, source kinds, workspace containment, legal state
transitions, illegal regressions, and the hard-coded false activation flags.
Add immutable values and errors without filesystem writes.

### Slice 2: Safe enumeration, hashing, and preset catalog

Implement streaming raw/semantic hashing, directory/ZIP path validation,
archive limits, synthetic historical fixtures, and the checked-in historical
preset fingerprint catalog. Prove no symlink, traversal, duplicate, case
collision, or archive bomb input is followed/extracted.

### Slice 3: Candidate inspection and comparison

Implement explicit current-checkout, direct-folder, wrapper-folder, ZIP, and
existing-canonical readers. Add required JSON/safety snapshots, identity and
CalibrationMemory evidence, preset flags, unclassified-path reporting, and
duplicate/conflict classification.

### Slice 4: Verified full-source backup

Implement streamed backup creation, manifest, fsync/atomic completion,
archive reopening, CRC/size/hash verification, completed archive hash, source
change detection, and read-only-source tests.

### Slice 5: Staged canonical import

Build the complete machine tree exclusively from the verified archive. Add
target identity checks, stage validation, backup placement, receipt creation,
free-space checks, and same-filesystem atomic publication to an absent target.

### Slice 6: Locking, journals, and recovery

Add the QLockFile adapter, transition journals, named fault checkpoints, exact
target reconciliation, idempotent re-entry, and contention/crash tests at
every durability boundary.

### Slice 7: Cohort and production non-activation coverage

Run representative synthetic rc.6 and rc.1 journeys from directory and ZIP,
including non-preset camera values, exact preset matches, camera-only matches,
conflicts, missing state, and interrupted recovery. Prove `App.py` and
production roots remain unchanged and no active-machine pointer is written.

### Slice 8: Closeout and full validation

Refresh direct-local inventory, document any classification discoveries, run
focused and full Python suites, record exact results and the dedicated commit,
and mark Milestone 2 verified only when all exit criteria pass.

## Exact expected file list

Expected application files:

- New `FreeRTOS-interface/MachineDataArchive.py`.
- New `FreeRTOS-interface/MachineDataMigration.py`.
- New `FreeRTOS-interface/MachineDataLock.py`.
- `FreeRTOS-interface/LocalConfig.py` only for a public CalibrationMemory
  validation helper if the existing read-only inventory is insufficient.
- `FreeRTOS-interface/MachineData.py` to add the canonical machine-calibration
  root, optics file, and regulator-optimization paths. Migration workspace
  paths remain owned by the migration module.
- New versioned historical preset fingerprint JSON under
  `FreeRTOS-interface/Presets/`.

Expected tests and synthetic fixtures:

- New `tests/test_machine_data_archive.py`.
- New `tests/test_machine_data_migration.py`.
- New `tests/test_machine_data_migration_recovery.py`.
- New synthetic/tag-derived fixtures beneath
  `tests/fixtures/machine_data_migration/`.
- Shared synthetic test helper `tests/machine_data_migration_helpers.py`.
- Existing `tests/test_machine_data_contract.py` and `tests/test_local_config.py`
  only when their public contracts are extended.
- Existing safe-construction/window-icon tests only for non-activation guards.

Expected documentation:

- Parent living plan.
- This Milestone 2 plan.

Files explicitly not expected to change:

- `FreeRTOS-interface/App.py`.
- `FreeRTOS-interface/ApplicationComposition.py`.
- `FreeRTOS-interface/Model.py`.
- `FreeRTOS-interface/Controller.py`.
- `FreeRTOS-interface/View.py`.
- `FreeRTOS-interface/RegulatorProfiles.py`.
- `tools/update_and_restart.py`.
- `VERSION`, `CHANGELOG.md`, `releases/latest.json`, release manifests, or tags.
- Firmware, firmware artifact, protocol, motion, pressure, or timing files.

Reconfirm this list immediately before implementation. If production code
outside the expected list becomes necessary, update the parent plan and stop
for scope review before editing it.

## Detailed test matrix

### Candidate normalization

| Case | Expected result |
| --- | --- |
| Explicit current checkout | Only its direct `local/` and `VERSION` inspected |
| Direct selected local | Five required files recognized |
| Wrapper with direct local child | Child normalized with wrapper VERSION |
| Directory with direct files and child local | Ambiguous; rejected |
| Directory requiring recursive search | Rejected; no search |
| Missing selected path | Fatal issue, no target write |
| Symlinked selected root or escaped member | Rejected |
| Existing canonical root | Inspection/reconciliation only |

### Source cohorts and validation

| Case | Expected result |
| --- | --- |
| Synthetic rc.6 customized Camera | Valid, non-preset evidence |
| Synthetic rc.1 customized Camera | Valid, non-preset evidence |
| Missing each mandatory config | Fatal; never seeded |
| Malformed JSON | Fatal with relative filename |
| Wrong top-level type | Fatal |
| Missing/malformed camera | Fatal |
| Nonnumeric, boolean, NaN, or infinite axis | Fatal |
| Empty plate calibrations | Allowed and recorded |
| Partial/nonfinite four-corner calibration | Fatal |
| CalibrationMemory absent | Warning, never seeded |
| CalibrationMemory extra regular files | Preserved and hashed |
| Valid assigned matching identity | Recorded as matching |
| Missing/unassigned identity | Evidence warning; no UUID generated |
| Assigned mismatched identity | Identity conflict; no import |
| Optics/optimization data present | Backed up and copied to canonical calibration paths |
| Unknown extra regular files | Backed up and listed unclassified |

### Preset and candidate comparison

| Case | Expected result |
| --- | --- |
| Exact rc.6 historical preset | `preset_like`, unverified |
| Exact rc.1 historical preset | `preset_like`, unverified |
| Same JSON with changed formatting | Semantic preset match still detected |
| Only camera matches a preset | `camera_preset_match`, unverified |
| Exact migratable-tree duplicates | Duplicate group; no auto winner |
| Five configs same, CalibrationMemory differs | Optional-state conflict |
| Different required config | Conflict |
| Declared rc.6 version matching rc.1 preset | Cohort mismatch warning |
| Missing VERSION | Unknown-version warning, not guessed |

### ZIP safety

| Case | Expected result |
| --- | --- |
| Supported direct/wrapper ZIP | Same evidence as directory source |
| Absolute/drive/`..`/backslash member | Rejected before extraction |
| Duplicate normalized member | Rejected |
| Case-only collision | Rejected on every OS |
| Symlink/special/encrypted member | Rejected |
| Unsupported compression or corrupt CRC | Rejected |
| Entry/member/total/ratio limit exceeded | Rejected without partial extraction |
| Multiple candidate wrappers | Ambiguous; rejected |

### Backup integrity

| Case | Expected result |
| --- | --- |
| Read-only candidate | Backup succeeds without source mutation |
| All source regular files | Present with exact raw hashes |
| VERSION present/absent | Included or explicitly recorded absent |
| Explicit firmware artifact | Included and labeled package evidence only |
| Source changes during snapshot | `source_changed`; no publication |
| Write/flush/fsync/replace failure | `backup_failed`; no target |
| Archive reopen/hash/CRC mismatch | `backup_failed`; no target |
| Backup succeeds | Completed ZIP hash and verified manifest returned |

### Staging and publication

| Case | Expected result |
| --- | --- |
| Stage built | Reads only verified archive members |
| Five configs | Exact raw hashes under `config/` |
| CalibrationMemory present | Exact safe tree copied |
| Unclassified source file | Archive only, not silently canonicalized |
| Insufficient free space | Fatal before publication |
| Existing target absent | Whole staged machine tree atomically renamed |
| Existing target exact same migration | Idempotent reconciliation |
| Existing target differs or lacks evidence | Conflict/recovery required; no overlay |
| Successful publication | Receipt is `copied_unverified` with three false flags |
| Any outcome | `active_machine.json` remains absent/unchanged |

### Fault injection and recovery

Inject immediately before and after every journal write, backup finalize,
archive verification, staged member copy, staged receipt write, target rename,
final receipt write, and workspace cleanup.

For every checkpoint prove:

- candidate bytes are unchanged;
- no partial target tree is treated as canonical;
- a repeated call either resumes to the exact result or reports
  `recovery_required` without mutation;
- a completed target has the exact expected tree fingerprint;
- no preset is used as repair material;
- no active-machine pointer appears;
- evidence needed for manual recovery is preserved.

### Locking and concurrency

| Case | Expected result |
| --- | --- |
| First UUID-scoped lock | Acquired |
| Second process/object same UUID | Immediate contention failure |
| Different target UUID | Independent lock path |
| Known dead stale lock per Qt contract | Deterministic reviewed behavior |
| Unknown ownership | Never auto-removed |
| Exception inside lock context | Lock released normally when ownership is valid |

### Production non-activation

| Case | Expected result |
| --- | --- |
| `App.py` source | No migration/archive/lock import or call |
| Production roots | Still all `None` |
| Legacy LocalConfig default | Still `<repo>/local` |
| Engine import | No directory creation, UI, or hardware construction |
| Successful direct migration | External tree inactive; runtime still reads legacy local |

## Validation commands

Focused implementation gate:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_machine_data_contract.py `
  tests\test_machine_data_archive.py `
  tests\test_machine_data_migration.py `
  tests\test_machine_data_migration_recovery.py `
  tests\test_local_config.py `
  tests\test_safe_application_construction.py `
  tests\test_view_window_icon_contract.py
```

Full Python gate:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

Static/documentation gates:

```powershell
git diff --check
git status --short
```

The full suite should run with the repository-prescribed 15-minute tool
timeout. No hardware command, firmware flash/build, HIL run, protocol test, or
motion test is required because Milestone 2 remains disconnected from
production and hardware construction.

## Review checklist

- [x] Only explicitly supplied shallow candidates are inspected.
- [x] Candidate paths and files cannot escape through links or ZIP members.
- [x] No candidate or manual backup is mutated.
- [x] No missing mandatory file is seeded from presets.
- [x] rc.6 and rc.1 preset cohorts are recognized semantically.
- [x] Camera preset-match evidence is prominent and unverified.
- [x] Full source is archived; known calibration data is canonical and unknown files are listed.
- [x] Completed backup is reopened and every member hash verified.
- [x] Canonical stage reads only from the verified archive.
- [x] Target identity is explicit and conflicts fail closed.
- [x] Locking coordinates checkouts before any migration write.
- [x] Entire machine tree is published by one same-filesystem rename.
- [x] Existing targets are never overlaid, deleted, or newest-wins merged.
- [x] Journals and receipts reject illegal state transitions/versions.
- [x] Fault recovery is idempotent or fails closed with evidence preserved at every reviewed checkpoint.
- [x] Receipt cannot authorize activation/source/calibration verification.
- [x] `active_machine.json` is never written.
- [x] App, MVC, updater, firmware, protocol, and motion remain unchanged.
- [x] Focused and full Python suites pass.
- [x] Parent plan records implementation findings and validation.
- [ ] Dedicated Milestone 2 commit is recorded.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Wrong candidate selected later | Engine never chooses; evidence, coordinates, version, identity, and conflicts are returned for M3 |
| Candidate changes during copy | Verified archive is the only stage source; pre/archive fingerprints must agree |
| Tracked preset mistaken for calibration | Historical semantic catalog plus camera-only flag; receipt stays unverified |
| ZIP traversal/archive bomb | Strict member normalization, collision checks, limits, CRC and streaming hashes |
| Read-only external backup | Source is read-only by contract; writes occur only beneath canonical base |
| Disk fills after preflight | Streamed writes, fault hooks, atomic publication, no target activation |
| Crash after target rename | External journal plus exact target reconciliation finalizes or fails closed |
| Existing canonical data overwritten | Destination must be absent or exactly reconcilable; no overlay/delete API |
| Different checkouts migrate concurrently | Shared base UUID lock plus existing app-wide lock later in M3 |
| Unassigned/mismatched identity | No UUID generation; explicit assigned target required; mismatch blocks |
| Auxiliary local data lost | Known optics/optimization data has canonical calibration paths; unknown data remains in full archive/inventory |
| Backup claimed installed firmware proof | Manifest labels artifact hash as package evidence only |
| Archive limits reject a legitimately large machine | Fail safely, report exact limit; qualify/increase reviewed policy before M3/M7 |
| Qt stale-lock behavior differs by installed version | Adapter integration tests and no unconditional stale-file removal |

## Rollback plan

Milestone 2 remains inert, so rollback is code-only for normal production:

1. Revert the dedicated Milestone 2 commit.
2. Remove the unused archive, migration, and lock modules and their catalog.
3. Preserve synthetic tests/fixtures only if useful for a redesign.
4. Confirm `App.py` has no engine import and production still resolves
   `<repo>/local`.
5. Run LocalConfig, safe-construction, and machine-data contract tests.

Never delete a canonical tree, verified backup, journal, or workspace merely
because the code is rolled back. If a developer/support user explicitly ran
the inert API against non-test data, preserve those external artifacts and
inspect their receipts before any cleanup. The source candidate remains
unchanged throughout.

## Exit criteria

Milestone 2 is `verified` only when:

1. All frozen candidate, archive, identity, hashing, and state schemas are
   implemented and tested.
2. Synthetic rc.6 and rc.1 customized and preset-like fixtures pass.
3. Full-source archives are reopened and prove exact member hashes.
4. Staging reads only from a verified archive.
5. One atomic rename publishes a complete absent target; existing targets are
   never overlaid.
6. Every injected interruption is idempotently recovered or fails closed with
   evidence preserved.
7. Lock contention prevents concurrent migration for the same UUID.
8. Preset-like, camera-match, missing identity, missing CalibrationMemory, and
   unclassified-file states remain visibly unverified.
9. The final receipt is `copied_unverified` and cannot authorize activation.
10. Production startup and roots still use legacy `<repo>/local`.
11. Focused and full Python suites pass.
12. Direct-local inventory, findings, validation, and the dedicated commit are
    recorded in the parent plan.

## Implementation record

- 2026-08-19: Implemented the inert Milestone 2 engine on `update_bug_fix`.
- Extended `MachineDataPaths` with canonical `calibration/`, droplet-optics,
  and regulator-optimization paths without changing production resolution.
- Added standard-library archive/evidence primitives, explicit candidate
  inspection and comparison, the checked-in rc.6/rc.1 semantic fingerprint
  catalog, the Qt UUID lock adapter, durable journals/receipts, verified backup
  creation, archive-only staging, atomic absent-target publication, and exact
  reconciliation.
- Added synthetic directory/ZIP cohort fixtures and tests for hostile archives,
  required shapes, preset/Camera detection, identity conflicts, optional and
  unclassified data, calibration ownership, free-space failure, concurrency,
  interruption boundaries, inactive publication, and production
  non-activation.
- Production `App.py`, application composition, MVC, updater, firmware,
  protocol, motion, pressure, timing, and release metadata were not changed.
- Dedicated Milestone 2 commit is pending; the milestone therefore remains
  `implementation_complete` rather than `verified`.

## Validation record

- 2026-08-19 focused gate:
  `180 passed, 1 skipped, 110 warnings in 10.54s`.
- 2026-08-19 full Python gate:
  `5179 passed, 153 skipped, 585 warnings in 281.23s`.
- The focused skip is the Windows symlink-creation safety case when the current
  account lacks symlink permission; ZIP symlink/reparse rejection remains
  covered without that permission.
- Existing warnings are Qt deprecation warnings and are unrelated to this
  milestone.
- Static/documentation validation and the dedicated commit remain to be
  recorded before changing status to `verified`.

## Findings discovered during planning

1. The two historical presets share the same `camera` coordinates, so a
   camera-only comparison is valuable but cannot identify which tag seeded a
   file.
2. rc.6 and rc.1 differ in `Settings.json`, so only comparing a whole candidate
   to the current rc.2 preset would miss a fully preset-seeded rc.6 candidate.
3. LocalConfig's existing seeding functions are intentionally unsuitable for
   candidate validation because calling them can create missing files.
4. A verified backup must be the import source to eliminate the live-source
   reread/TOCTOU gap.
5. Publishing config and CalibrationMemory separately would expose partial
   canonical state. Staging the complete machine tree and renaming it once
   avoids that boundary while the target is absent.
6. A per-machine lock inside the future machine root would create the target
   too early. Migration therefore needs a base-scoped UUID lock.
7. Optional/unclassified local data cannot be discarded safely; full archive
   preservation and explicit inventory are required even when canonical
   ownership is deferred.
8. Milestone 3 planning classified `droplet_imager_optics.json` and
   `regulator_optimization/` as machine calibration data. They must be imported
   beneath the canonical `calibration/` root so production has no active
   checkout-local dependency after cutover.
9. Windows rejects `fsync` on a read-only CRT file descriptor. Completed
   archives are reopened `r+b` solely for `fsync`; their contents are not
   changed, and the focused/full Windows gates pass.
10. Directory `fsync` is unavailable through the current Windows runtime.
    Journal and backup evidence explicitly record the capability as unsupported
    instead of claiming durability that the platform did not provide.
11. A generated backup containing highly compressible legitimate JSON could
    violate the hostile-input compression-ratio rule if compressed. Generated
    backup members are therefore stored without compression, while selected
    external ZIPs remain subject to the ratio limit.
12. A partial stage cannot always be resumed safely without deleting evidence.
    The engine resumes an exactly verified stage but fails closed and preserves
    a partial/mismatched stage for reviewed recovery.
13. The closeout direct-local inventory also found qualification-worker
    identity fallbacks and View's optics display path. They remain unchanged in
    inert Milestone 2 and are added to the Milestone 3 injection audit.

## Document change log

| Date | Change |
| --- | --- |
| 2026-08-19 | Created the concrete inert candidate, archive, staged-copy, locking, receipt, and crash-recovery implementation plan for Milestone 2. |
| 2026-08-19 | Incorporated Milestone 3 ownership findings by canonicalizing optics and regulator-optimization data beneath `calibration/`. |
| 2026-08-19 | Recorded implementation-complete inert engine, focused/full validation, recovery findings, and pending dedicated-commit gate. |
