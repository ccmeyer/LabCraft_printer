# Machine Data Migration Milestone 4: Transactional Configuration History Plan

Status: `ready_for_implementation`

Prepared: 2026-08-19

Parent plan:
`docs/machine_data_migration_and_location_safety_plan.md`

Depends on:

- Milestone 1 contract commit `9b882141` (`verified`)
- Milestone 2 migration commit `157db800` (`verified`)
- Milestone 3 production cutover `b3cf12ad` and worker-lifecycle correction
  `08d41bc2` (`verified`)
- Milestone 3 documentation/cleanup commits `9dcf4936` and `99418d01`

Target release: `v1.3.0-rc.2`

## Outcome

Milestone 4 will replace the application's independent configuration writes
with one transaction boundary for governed machine configuration. Before a
configuration change can affect runtime state, the system will durably record
the intent, preserve and verify exact pre-change bytes, replace the complete
validated document, reopen and hash it, write a chained immutable event, and
advance a small current-state head. Only then may the Model install the new
snapshot in memory.

At the end of the milestone:

- a named-location add or edit is one operation instead of an in-memory edit
  followed by a separate save question;
- rack Left and Right are one indivisible `Locations.json` change;
- all four plate corners are one indivisible `Plates.json` change;
- cancellation or rejection changes neither disk nor active Model state;
- support can see the actor, time, workflow, reason, exact values, file hashes,
  verification effect, and restore reference for every accepted change;
- every committed file change has an exact, hash-verified pre-change backup;
- an interrupted write is reconciled before Settings, MVC, serial, camera,
  balance, or machine construction;
- changed and newly added motion targets become unverified immediately while
  unchanged targets retain their evidence through an explicit derived-state
  chain;
- restore and target re-verification are themselves new audited operations;
- the Milestone 2 manifest, Milestone 3 verification, and Milestone 3
  activation receipt remain immutable evidence of the original activation.

This milestone creates traceability, atomicity, recovery, and exact-value
authorization state. It does not add coordinate delta thresholds, travel
bounds, geometry envelopes, fresh-telemetry requirements, or large-change
confirmation. Those remain Milestone 5 and will plug in before the transaction
service's commit-intent boundary.

## Safety boundary and call-path audit

### Current named-location path

```text
MainWindow.add_new_location() / modify_location()
-> ask for a name
-> Controller.add_new_location() / modify_location()
-> LocationModel.add_location() / update_location()
-> active in-memory locations change and signals emit
-> only afterward ask "Write to file?"
-> Controller.save_locations()
-> LocationModel.save_locations()
-> temporary file + fsync + os.replace Locations.json
```

The save method catches and prints write failures instead of returning failure.
Selecting No at the second prompt therefore leaves memory changed, and a write
failure can leave memory and disk disagreeing.

### Current rack-calibration path

```text
RackBox._run_guided_rack_calibration()
or CalibrationClasses.View.RackCalibrationFixDialog.save_calibrations()
-> RackModel.set_calibration_position() for Left and Right temporary values
-> RackModel.update_calibration_data()
-> RackModel.store_calibrations() changes active rack memory and clears temp
-> rack_calibration_updated_signal
-> Model.update_rack_calibration()
-> LocationModel.update_location_coords(Left)
-> LocationModel.update_location_coords(Right)
-> LocationModel.save_locations()
-> RackModel.apply_calibration_data()
```

The two anchors reach one JSON write, but several active in-memory objects are
changed first. The location writer suppresses failure, so the RackModel,
LocationModel, and file can disagree.

### Current plate-calibration path

```text
WellPlateWidget.open_calibration_dialog()
-> PlateCalibrationDialog stores four temporary corners
-> dialog Accepted
-> WellPlate.update_calibration_data()
-> WellPlate.store_calibrations() installs corners and clears temp
-> WellPlate.save_calibrations_to_file()
-> temporary file + fsync + os.replace Plates.json
-> WellPlate.apply_calibration_data()
```

The four corners share a file write, but a failed write occurs after the prior
transform has already been replaced in memory and the temporary values have
been cleared.

### Other governed configuration writers

`LocalConfig.machine_config_top_level_types()` defines five governed files:

- `Settings.json`
- `Locations.json`
- `Plates.json`
- `Obstacles.json`
- `RegulatorProfiles.json`

The production UI currently writes only `Locations.json` and `Plates.json`.
`RegulatorProfileStore.save()` is a callable atomic writer, although no current
production call site invokes it. No runtime `Settings.json` or `Obstacles.json`
writer was found. Milestone 4 will nevertheless register all five documents,
route the dormant profile writer through an injected repository in canonical
production, and reject an unregistered direct canonical write. This prevents a
later feature from silently reopening a bypass.

CalibrationMemory, experiment files, calibration run recordings, images,
regulator optimization outputs, update history, and firmware artifacts are not
governed configuration documents. Their existing owners and durability rules
remain unchanged.

### Communications and firmware boundary

None of the persistence calls above sends a serial command or changes the
device protocol. Calibration dialogs do move hardware while collecting points,
through existing View -> Controller -> Machine paths, but the proposed commit,
audit, recovery, and Model-apply paths stop before communications:

```text
View confirmation
-> Controller configuration adapter
-> ConfigurationTransactionService
-> canonical files/history/backups only
-> Model installs committed snapshot
-> View refreshes
-> no Machine method and no firmware handler
```

No file under `firmware/` and no message format, opcode, parser, motion timing,
or pressure-control algorithm is in scope.

## Fixed design decisions

### 1. Activation evidence remains immutable

Milestone 4 must not rewrite:

- `metadata/migration_tree_manifest.json`;
- `metadata/migration_receipt.json`;
- `metadata/verification.json`;
- `metadata/activation_receipt.json`;
- the installed Milestone 2 source backup.

Those files answer, "What exact data was selected, copied, reviewed, and
activated?" Configuration history answers, "What authorized operations
happened after activation?" Mixing the two would erase the evidence needed to
investigate the original Camera discrepancy.

### 2. Current state is a chain anchored to Milestone 3

The current implementation requires all config files to continue matching the
Milestone 3 verification and the Milestone 2 tree manifest. That is correct
before an edit but would make every legitimate transaction fail on the next
start. Milestone 4 adds a second layer:

```text
immutable M2 tree manifest + immutable M3 verification
-> configuration event 1
-> configuration event 2
-> ...
-> configuration head
-> exact current governed file hashes and per-target authorization state
```

The chain is tamper-evident, not cryptographically signed. A filesystem owner
can still replace evidence deliberately, but a missing, reordered, altered, or
unreferenced event, backup, pending artifact, head, or governed file makes
bootstrap fail closed.

### 3. The head is created lazily

An exact Milestone 3 store with no configuration event remains a valid legacy
baseline and does not receive a new file just because rc.2 was launched. The
first committed, cancelled, rejected, verification, restore, or recovery event
creates the configuration head and anchors it to the immutable Milestone 3
verification hash.

This preserves a narrow rollback window: before any Milestone 4 event, the
store remains readable by the Milestone 3 code. Once history exists, older
code must fail closed rather than ignore it.

### 4. One event per immutable file

The audit is a directory of canonical JSON event files, not a JSONL file. Each
event is written with exclusive-create semantics, flushed, fsynced, reopened,
and hashed. This avoids a torn append and permits an exact previous-event hash
chain.

### 5. Pre-change backups preserve exact bytes

A committed file mutation first creates a transaction-specific backup holding
the exact bytes that were present on disk. The backup manifest records both raw
and semantic hashes. Restoration reads only a backup that passes containment,
schema, size, raw-hash, and semantic-hash verification.

### 6. Persistence precedes runtime activation

The service returns complete committed documents. The Controller then asks the
Model to install those documents as one in-memory operation and emit signals.
LocationModel, RackModel, and WellPlate will no longer write canonical files on
their own in production.

If persistence fails, Model state is untouched. If persistence and history
commit but Model installation unexpectedly fails, disk/history remain the
source of truth, all hardware-capable actions are disabled, and the app asks
for a controlled restart. The system must not silently undo a durable audited
commit or continue with stale memory.

### 7. Changed targets are revoked; unchanged targets carry forward

The Milestone 3 authorizer binds every target to both a value hash and the raw
hash of its entire source file. Consequently, changing Camera currently makes
every location fail with `source_file_changed`. Milestone 4 will derive a
current authorization snapshot after each transaction:

- a target whose canonical value is unchanged keeps its prior verified state
  and evidence lineage, while its source-file hash is rebound to the exact
  committed file through the audited event;
- a changed or new target becomes `revoked_pending_verification`;
- a removed target disappears from the current target set but remains visible
  in history;
- compound targets are revoked whenever one of their inputs changes;
- a separate exact-value verification event may promote a revoked target;
- verification never changes configuration bytes and never rewrites M3
  evidence.

This avoids needlessly disabling every location after one reviewed edit while
still ensuring that the changed Camera cannot move until its new value is
explicitly verified.

### 8. The retained configuration lock is the writer authority

Production already holds one `AcquiredConfigurationLock` for the entire
application lifetime. The transaction service receives that exact token and
calls `assert_owns(paths)` before every write; it does not reacquire the same
`QLockFile`. A nonblocking process-local mutex rejects overlapping commits
inside the application. Offline support tools must acquire the same canonical
lock and therefore require the app to be closed.

Simulation receives an explicitly contained service rooted beneath its run
directory. Unit tests receive temporary roots and explicit lock/test adapters.
No simulation or test fallback may write the repository's `local/` directory.

## Canonical layout additions

Milestone 1 already reserved the history, pending, backup, and lock roots. The
following exact layout will be added without changing the external base or
machine UUID:

```text
machines/<machine_uuid>/
  config/
    Settings.json
    Locations.json
    Plates.json
    Obstacles.json
    RegulatorProfiles.json
  history/
    configuration_head.json
    configuration_events/
      00000000000000000001-<event_uuid>.json
      00000000000000000002-<event_uuid>.json
    pending_transactions/
      <transaction_uuid>/
        journal.json
        proposed/
          <governed filename>.json
  backups/
    configuration/
      <transaction_uuid>/
        manifest.json
        before/
          config/
            <governed filename>.json
```

`MachineDataPaths` will expose `configuration_head_path` and
`configuration_backups_root` as validated canonical paths. Event, pending, and
backup UUIDs must parse canonically. Filenames are selected from the fixed
governed-file registry; user text is never interpolated into a path.

The active-tree verifier will accept only the exact files proven by a valid
head/event/backup chain plus at most one well-formed pending transaction. A
matching directory pattern alone is not sufficient. Links, reparse points,
case-colliding names, special files, unreferenced artifacts, multiple pending
transactions, and unexpected paths require recovery.

## Versioned schemas

All timestamps are canonical UTC RFC 3339 values. UUIDs are canonical text.
All JSON is UTF-8, finite, and deterministically encoded. Parsers reject
unknown schema names or versions, missing required keys, wrong scalar types,
unsafe relative paths, invalid hashes, and inconsistent derived fields.

### Configuration event schema v1

Schema name: `labcraft.configuration_event`

Required content:

- `schema_name`, `schema_version`;
- `event_id`, `sequence`, `previous_event_sha256`;
- `transaction_id` when the event belongs to a transaction;
- `machine_id`, `machine_uuid`;
- `event_type`: `change`, `import`, `restore`, `verification`, `cancelled`,
  `rejected`, or `recovery`;
- `outcome`: a closed enum appropriate to the event type;
- `created_at_utc`;
- actor fields: entered operator name, OS account, session ID;
- application version and commit;
- stable workflow code and human reason;
- affected governed files with exact before/after raw and semantic hashes;
- structured target changes containing target key/kind and exact old/new values
  for locations, rack anchors, and plate corners;
- verification effects with old/new state and evidence reference;
- backup manifest path/hash for every committed file mutation;
- restore source event/transaction when applicable;
- directory-sync support and recovery details where applicable.

Committed coordinate events contain the coordinate values themselves, not
only opaque hashes, so support can answer what changed without restoring a
backup. Full document bytes remain in the verified backup rather than being
duplicated in every event.

An event does not contain its own file hash. The next event and current head
bind the canonical event-file hash.

### Configuration head schema v1

Schema name: `labcraft.configuration_head`

Required content:

- machine ID/UUID;
- immutable activation ID and SHA-256 of `metadata/verification.json`;
- latest event sequence, relative path, ID, and raw SHA-256;
- exact raw and semantic hash for all five governed config files;
- current target authorization entries;
- creation/update timestamps and app provenance.

Each authorization entry includes target key, kind, current canonical value
hash, current source file/hash, state, verifying operator/time/method, original
M3 target or later verification-event reference, and optional service record.
The head is a cache of the fully replayed chain. Startup recomputes and compares
it rather than trusting it alone.

### Pending transaction journal schema v1

Schema name: `labcraft.configuration_transaction_journal`

Required content:

- transaction/event identity and intended sequence/previous event hash;
- immutable activation and expected-head bindings;
- actor, workflow, reason, event type, and final confirmation time;
- governed file list;
- exact before, proposed, and staged-file evidence;
- verified backup manifest evidence;
- complete planned event payload and its canonical hash;
- last completed durability checkpoint;
- directory-sync support.

The journal is updated atomically for diagnostics, but recovery derives the
truth from hashes of the config, staged proposal, backup, event, and head. It
never trusts only a textual checkpoint label.

### Configuration backup manifest schema v1

Schema name: `labcraft.configuration_backup`

Required content:

- transaction ID, machine identity, timestamp, actor/workflow, and reason;
- immutable activation and expected-head bindings;
- for every backed-up file: safe relative path, byte count, raw SHA-256, and
  semantic JSON SHA-256;
- aggregate evidence fingerprint;
- directory-sync support.

The manifest is written only after all exact pre-change bytes have been copied
and reopened. A transaction cannot reach commit intent without a verified
manifest.

## Governed document validation

The transaction engine accepts only complete proposed documents. Patch-like UI
requests are expanded against the exact current file, then the resulting full
set is validated before any backup or journal is created.

The document registry will:

- enforce the five existing top-level types from `LocalConfig`;
- reject non-finite or non-JSON values;
- enforce nonempty, case-insensitively unique location names and integral XYZ
  coordinate fields while preserving currently supported unrelated keys;
- enforce unique plate names, positive rows/columns/spacing, exactly one
  default, and either no calibration or a complete four-corner XYZ mapping;
- reuse the regulator-profile schema validator;
- preserve existing Settings and Obstacles compatibility while validating the
  fields consumed by production;
- build the complete target snapshot against the proposed set before commit;
- apply no new travel bounds, delta limits, or geometric plausibility rules in
  this milestone.

Any attempt to change `HARDWARE_PROFILE` while MVC is active is rejected and
audited because the instantiated Machine and Controller cannot safely change
profile in place. A future updater/startup transaction may support it only with
an explicit restart boundary. Other Settings changes are not exposed by the
Milestone 4 UI. The registry and transaction engine remain capable of auditing
a reviewed offline import, but production adapters are limited to documents
whose runtime installation is defined and tested.

## Target dependency and verification rules

The target-impact calculation is deterministic:

| Changed value | Revoked current targets |
| --- | --- |
| Named location | That `location:<casefold-name>` target |
| `rack_position_Left` or `rack_position_Right` | The changed location target(s) and `rack:primary` |
| One plate's corners | That `plate:<casefold-name>` target |
| Added target | The new target |
| Removed target | Removed from current authorization state |
| Settings affecting profile/default interpretation | All saved/derived targets, or reject when live profile would change |
| Obstacles/boundaries | All motion targets until the safety relationship is reviewed |
| Regulator profile | No coordinate target; the profile resource itself records changed/unverified state |

An unchanged target carries its verified state only if replay proves its value
hash is unchanged from the preceding authorization state and the new source
file hash is the exact transaction output. There is no blanket "trust every
target in the rewritten file" operation.

A re-verification event requires:

- the exact current head and target value hash;
- a nonempty operator name and reason;
- a declared method: physical check or independent service record;
- exact coordinate confirmation for a location;
- both anchors for the rack target;
- all four corners for a plate target;
- a service-record reference where policy requires it;
- no config change between review and event commit.

The Camera remains a standalone item and cannot be approved indirectly by
verifying a rack, plate, or whole-file checkbox. The verification dialog will
show and require exact confirmation of Camera X, Y, and Z. Milestone 5 will add
stronger change previews, telemetry preconditions, and thresholds before a
new value is accepted for persistence.

The movement call path becomes:

```text
Controller resolves current saved/derived target
-> transactional authorizer reads the latest in-process head snapshot
-> compare machine UUID, target key/kind, exact value hash, derivation, state,
   and exact current source-file hash
-> authorize or reject before any command is queued
```

The existing override/manual/ignore-safe-height protections remain. No flag or
direct workflow may bypass revoked state.

## Transaction protocol

All operations run while the retained configuration lock is owned and the
process-local writer mutex is held.

### Mutation transaction

1. Resolve the exact current head or immutable M3 baseline; verify the entire
   existing event chain and active inventory.
2. Reread every governed current document from disk. Compare exact raw hashes
   with the expected state and reject stale in-memory or concurrent proposals.
3. Expand the request into complete proposed documents, validate the whole
   governed set, calculate structured changes and target verification effects,
   and reject a semantic no-op.
4. Copy exact before bytes into the UUID backup directory, write/reopen the
   manifest, and verify raw/semantic hashes and aggregate fingerprint.
5. Write/reopen all complete proposed files beneath the pending directory.
   Write/reopen the journal containing the planned event and set durable commit
   intent. No canonical config has changed yet.
6. Atomically replace each affected canonical config file, fsync where
   supported, reopen it, rerun validation, and compare raw/semantic hashes.
7. Exclusively write/reopen/hash the immutable event, then atomically
   write/reopen the derived configuration head.
8. Remove only the exact contained pending UUID directory after event and head
   verification. Return immutable committed documents and the new
   authorization snapshot for Model installation.

For the normal location, rack, and plate workflows only one canonical JSON file
is replaced. Multi-file import/restore uses the same protocol; partial file
replacement is never made visible to MVC because the app is already holding
the lock and recovery completes before a new process can construct MVC.

### Non-mutating audit transaction

Cancellation, rejection, and re-verification use the same event-chain and head
protocol but do not create a pre-change backup unless a config file changes.
They still use a journal so an event/head interruption can be completed
deterministically. A cancellation that happens before a proposal exists may
record workflow and cancellation stage without coordinate values.

### Error result contract

The service returns typed results rather than printing or swallowing errors:

- `committed`: disk/history/head verified; includes committed documents;
- `recorded`: non-mutating event/head verified;
- `rejected`: no config or Model change; rejection event written when possible;
- `cancelled`: no config or Model change; cancellation event written;
- `retryable_conflict`: expected head/file changed; no config change;
- `recovery_required`: state is ambiguous or rollback/reconciliation could not
  be proven; all hardware-capable actions remain disabled;
- `model_restart_required`: durable commit succeeded but Model installation
  failed; controlled restart is required.

The UI must not display "saved" until it receives `committed` and the Model has
successfully installed the returned snapshot.

## Crash and startup reconciliation

### Startup order

```text
QApplication
-> application-wide lock
-> MachineDataBootstrap read-only inspection
   -> validate immutable activation evidence
   -> inspect exact history/head/pending inventory
-> acquire and retain configuration lock
-> ConfigurationTransactionRecovery.reconcile()
-> replay event chain and compare head/current config/authorization state
-> strict-load Settings
-> build MVC/hardware dependencies
```

No recovery code imports or constructs Model, Machine, Controller, View,
serial, cameras, or balance. A recovery failure uses the existing bootstrap
recovery-required exit path and keeps the main window closed.

### Read-only inspection states

- No head, no events, no pending transaction: require exact M2/M3 baseline.
- Valid head and chain, no pending transaction: require exact current hashes
  and exact derived inventory.
- Exactly one valid pending transaction in a recognized hash state: permit only
  the locked reconciliation path; do not construct MVC yet.
- Invalid schema, broken event link, altered backup, unreferenced artifact,
  unexpected file, multiple pending transactions, or unrecognized hash mix:
  `recovery_required` with diagnostics only.

### Deterministic pending recovery matrix

| Observed durable state | Recovery action |
| --- | --- |
| All governed files have before hashes; no planned event | Record recovered-abort event if possible, leave config unchanged, advance head, clean pending |
| A prefix/mix of files has after hashes and the rest has before hashes | Restore every affected file from verified pre-change backup, verify exact before state, record recovered-abort, advance head, clean pending |
| Every affected file has after hashes; planned event absent | Exclusively write the exact planned event, derive/write head, verify, clean pending |
| Planned event exists; head still references previous event | Verify event/config/backup, advance head, clean pending |
| Head already references planned event | Verify all bindings, clean the redundant pending directory |
| Any file has neither before nor after hash, or evidence conflicts | Stop with `recovery_required`; do not guess, overwrite, or launch hardware-capable code |

If a live transaction encounters an event/head failure after canonical
replacement, it first attempts exact restoration from its verified backup. It
must verify the restoration before returning a normal failure. If restoration
cannot be proven, the Controller enters the same fatal recovery-required state
and refuses further hardware operations.

Pending cleanup validates the resolved absolute directory, exact canonical
UUID name, expected parent, and absence of links/reparse points. Ambiguous
evidence is preserved for support rather than deleted.

## MVC and user-workflow adapters

### Dependency injection

`AuthorizedMachineContext` will expose the validated configuration state,
retained lock, transaction service, history reader, and dynamic target
authorizer. `ApplicationComposition` will pass the service to Controller and
the governed runtime apply adapter to Model. Production construction fails if
canonical roots are present without the production service.

Simulation construction creates an equivalent service beneath its run root.
Legacy isolated Model tests may use an explicit noncanonical adapter, but no
canonical production writer is optional.

### Named locations

Required path:

```text
MainWindow asks for name
-> Controller builds proposed name + current XYZ without mutating Model
-> one confirmation collects operator and reason
-> service commits complete Locations.json and records verification effect
-> Controller installs committed Locations snapshot in Model
-> UI reports saved and explains whether target is verified or blocked
```

There is no second "Write to file" prompt. Cancelling the name or confirmation
leaves memory and disk unchanged and records the appropriate cancellation stage
once the audit service is available. Duplicate names and absent names are
rejected before commit.

### Rack calibration

Both guided rack entry points will send the temporary Left and Right anchors to
one Controller method. The Controller requires both anchors, creates one
complete proposed `Locations.json`, and commits one event/backup. Only the
committed Locations snapshot is then installed into LocationModel and
RackModel; the rack interpolation is recalculated once.

Dialog cancellation clears temporary captures only. Transaction failure keeps
the prior anchors, slot positions, and active calibration. The secondary
`RackCalibrationFixDialog` must no longer call `RackModel.update_calibration_data()`
directly.

### Plate calibration

The four dialog corners remain temporary. Acceptance requires exactly
`top_left`, `top_right`, `bottom_right`, and `bottom_left`, expands them into a
complete copy of `Plates.json`, and commits one event/backup. The current plate
object, calibrations, wells, and transform are updated only from the committed
document. Signals are emitted once after successful installation.

Cancellation or any validation/persistence/history failure clears only the
temporary proposal and leaves the prior plate document and transform active.
The new plate target is blocked for derived movement until re-verification.

### Import

Import is a reviewed configuration operation, not a file copy over `config/`.
The importer reads supported selected JSON into memory, reports the source path
and hashes, expands a complete proposed governed set, validates it, and calls
the same transaction service. It never accepts metadata, identity, history,
locks, CalibrationMemory, or arbitrary paths.

The first implementation exposes imports through a support-oriented dialog or
controller API for `Locations.json`, `Plates.json`, and
`RegulatorProfiles.json`. Live `HARDWARE_PROFILE` changes are rejected.
Changed targets are revoked exactly as for manual edits.

### Restore

History presents the verified pre-change backup associated with a committed
event. Restore:

1. revalidates the entire chain and selected backup;
2. shows the affected files/event reference;
3. requires operator, reason, and exact machine-ID confirmation;
4. uses the current state as the new before image;
5. commits the historical bytes as a new `restore` transaction;
6. writes a new backup and event; it never deletes or rewinds history;
7. revokes changed targets until exact-value re-verification.

### Verification

After a saved change, the UI clearly reports that persistence succeeded but
movement using the changed target is blocked. A separate review action opens
the exact-value verification dialog. The successful verification is a chained
event and updates the dynamic authorizer immediately; cancellation changes no
authorization state.

### History presentation

A Configuration History window, distinct from the experiment audit timeline,
will provide:

- integrity status and current event sequence;
- timestamp, entered operator, OS account, workflow, type, outcome, and reason;
- affected file/target names and old/new coordinate values;
- verification-state changes and restore reference;
- detail view with hashes and application provenance;
- refresh and deterministic Markdown/JSON export;
- controlled restore and verify actions routed back through Controller.

The existing experiment audit remains unchanged because it describes print
execution, not machine configuration authority.

## Files expected during implementation

### New application modules

- `FreeRTOS-interface/MachineDataTransactions.py`: schemas, strict parsers,
  inventory/chain replay, transaction service, durable commit, and recovery.
- `FreeRTOS-interface/ConfigurationHistoryReader.py`: read-only rows, detail
  model, and deterministic support export.

If `MachineDataTransactions.py` becomes difficult to review, split pure schemas
into `MachineDataTransactionSchemas.py`; do not split by MVC layer or create
multiple competing writers.

### Existing application modules

- `FreeRTOS-interface/MachineData.py`: exact head/backup path contract.
- `FreeRTOS-interface/MachineDataArchive.py`: only generic exclusive durable
  JSON/byte primitives needed by immutable events/backups; no migration schema
  changes.
- `FreeRTOS-interface/MachineDataMigration.py`: active-phase verification of an
  exact transaction-derived inventory while preserving the immutable M2
  manifest.
- `FreeRTOS-interface/MachineDataVerification.py`: derived current target state
  and dynamic authorization without rewriting M3 verification.
- `FreeRTOS-interface/MachineDataBootstrap.py`: pre-MVC inspection,
  lock-owned reconciliation, and current-state context.
- `FreeRTOS-interface/ApplicationComposition.py`: mandatory production and
  contained-simulation service injection.
- `FreeRTOS-interface/App.py`: recovery-result presentation/exit handling only
  if the existing recovery exit cannot express the result.
- `FreeRTOS-interface/LocalConfig.py`: governed document registry and reusable
  payload validation.
- `FreeRTOS-interface/Model.py`: proposal/snapshot helpers and persistence-free
  LocationModel, RackModel, and WellPlate installation.
- `FreeRTOS-interface/Controller.py`: all mutation, import, restore,
  verification, and fatal-state orchestration.
- `FreeRTOS-interface/View.py`: unified confirmations, configuration history,
  and named/rack/plate result presentation.
- `FreeRTOS-interface/CalibrationClasses/View.py`: route the rack fix dialog
  through Controller.
- `FreeRTOS-interface/RegulatorProfiles.py`: injected canonical repository or
  explicit direct-write rejection.

No firmware, protocol, release metadata, `VERSION`, tracked presets, or actual
machine-data file belongs in the milestone commit.

### Test files

- `tests/test_machine_data_transaction_schemas.py`
- `tests/test_machine_data_transactions.py`
- `tests/test_machine_data_transaction_recovery.py`
- `tests/test_machine_data_configuration_chain.py`
- `tests/test_configuration_history_reader.py`
- `tests/test_configuration_mutation_adapters.py`
- focused updates to bootstrap, migration, verification, composition,
  saved-target authorization, plate calibration storage, rack calibration UI,
  and regulator-profile tests.

The final names may consolidate related tests, but the coverage categories and
acceptance gates below are mandatory.

## Implementation sequence

All eight slices are part of one Milestone 4 implementation commit. Each slice
must be independently reviewable and green before the next begins; do not make
intermediate release tags.

### Slice 1: Contract, schemas, and baseline bridge

Implement the path additions, governed registry, strict schema parsers, event
filename/path rules, exact inventory model, and pure chain-replay types. Add a
read-only bridge that recognizes either an untouched exact M3 baseline or a
valid transaction chain without weakening copied-unverified or
activation-staged validation.

Acceptance:

- an untouched M3 store is accepted without creating a head;
- a valid synthetic event/head chain is accepted;
- any unexpected or altered dynamic path is rejected;
- M2/M3 evidence bytes and hashes remain unchanged;
- no production write path changes yet.

### Slice 2: Durable transaction and fault-injection engine

Implement exact backups, proposed staging, journal, atomic governed-file
replace, immutable event creation, head advancement, in-process serialization,
typed results, and exhaustive checkpoints. Start with temporary roots and no
MVC dependencies.

Acceptance:

- success produces one backup, event, and head with verified hashes;
- failure before commit intent changes no canonical file;
- failure at each later checkpoint either proves exact restoration or returns
  recovery-required;
- no event or backup can be overwritten;
- stale expected head/file hashes reject without mutation.

### Slice 3: Startup reconciliation and authorization state

Wire read-only history inspection and lock-owned reconciliation into bootstrap
before Settings/MVC. Implement event replay, target-impact calculation,
unchanged-evidence carry-forward, changed-target revocation, and the dynamic
authorizer. Keep M3 verification and activation files immutable.

Acceptance:

- every recognized pending state follows the recovery matrix;
- ambiguous state exits before hardware-capable construction;
- Camera change blocks Camera while an unchanged location remains authorized;
- rack/plate dependency revocation is exact;
- subsequent checkout startup resolves the same history and current state.

### Slice 4: MVC foundation and named locations

Inject the service, add complete proposal/committed-snapshot Model APIs, replace
the two-step named-location workflow with one transaction, and make direct
canonical LocationModel writes unavailable in production. Add operator/reason
confirmation and clear saved-but-unverified presentation.

Acceptance:

- add/modify success updates disk first, then memory, once;
- cancellation leaves byte-for-byte disk and memory unchanged;
- backup/audit/head failure leaves prior memory active;
- LocationModel no longer suppresses a production persistence failure;
- no Machine/serial call occurs during a config commit.

### Slice 5: Rack and plate aggregate transactions

Route both rack entry points and the plate acceptance path through Controller.
Build complete proposed documents, commit once, install once, and clear temp
state only on defined success/cancel paths.

Acceptance:

- Left/Right are one event and can never partially activate;
- four corners are one event and prior transform remains active on failure;
- cancellation changes neither file nor active calibration;
- success emits expected UI/model signals once;
- derived rack/plate movement is blocked until re-verification.

### Slice 6: Verification, import, and restore operations

Add exact target verification events, restricted governed imports, verified
pre-change restoration as a new transaction, and profile-store canonical write
closure. Require actor/reason and exact machine confirmation where specified.

Acceptance:

- verification changes authorization only when exact current values/head match;
- Camera requires its standalone exact confirmation;
- restore creates a new backup/event and does not remove history;
- import cannot escape the governed registry or alter identity/metadata;
- every callable canonical writer routes through the service or rejects.

### Slice 7: Human-readable history and support export

Implement strict reader rows/details, integrity display, deterministic export,
and View access. Route restore and verification actions through Controller;
keep direct filesystem mutation out of the reader/UI.

Acceptance:

- support can answer who/what/when/before/after/workflow/reason;
- corrupt history is displayed as unsafe and cannot be restored or verified;
- export is deterministic and does not mutate the canonical store;
- experiment audit behavior is unchanged.

### Slice 8: Writer inventory, full qualification, and documentation closeout

Run a final search for all governed filenames and write primitives, add a
regression inventory test, run focused/full/SIL gates, exercise a disposable
M3-to-M4 Pi store without hardware commands, update both plans, and record exact
evidence and rollback conditions.

Acceptance:

- every known production mutation call site is accounted for;
- all automated and Pi gates pass;
- no repository-local machine data, logs, or evidence is committed;
- the parent plan is updated to `verified` only after the manual gate.

## Automated verification matrix

### Schema, containment, and immutable inventory

- Reject unknown schema/version and missing/extra inconsistent required data.
- Reject invalid UUID/timestamp/hash/sequence/event filename.
- Reject traversal, absolute path, link/reparse, special file, and case
  collision.
- Reject unreferenced event, backup, proposed file, pending directory, or
  additional active-tree file.
- Reject alteration of any M2/M3 immutable evidence file.
- Accept the exact untouched M3 baseline without writing.

### Transaction success and failure

- Named add, named update, rack pair, plate quartet, import, restore,
  verification, cancellation, and rejection each produce the expected single
  event.
- Backup bytes equal exact pre-change bytes and validate independently.
- Before/after raw and semantic hashes match reopened files.
- Event chain and head replay to exact current state.
- No-op, invalid document, stale head, stale file, and concurrent writer reject.
- Inject failures before/after backup write/fsync, manifest, proposed staging,
  journal, each canonical replace, reopen, event create/fsync, head replace,
  and pending cleanup.
- A normal failure never leaves active Model state changed.

### Recovery

- Before-only, partial before/after mix, all-after/no-event,
  event-with-old-head, head-complete/pending-remains, and cleanup interruption.
- Missing/altered backup, staged proposal, event, head, or config fails closed.
- Multiple pending transactions fail closed.
- Recovery is idempotent across repeated interruption at each recovery
  checkpoint.
- Bootstrap does not import hardware-capable modules before reconciliation.

### Authorization

- Changed Camera is revoked immediately and exact movement is denied.
- Unchanged locations in the same rewritten file remain authorized only through
  valid event-chain carry-forward.
- Changed rack anchor revokes its named target and `rack:primary`.
- Changed plate corners revoke only the affected plate target.
- Restore/import revoke changed targets.
- Exact verification event enables only its reviewed target.
- Stale verification review, wrong machine, wrong target kind/value, altered
  source, manual/override/ignore flags, or broken chain deny.

### MVC and UI

- Named cancel at each prompt changes neither memory nor disk.
- The success message occurs only after persistence and Model install.
- Rack and plate success install one complete committed snapshot.
- Rack/plate persistence failure retains prior anchors/corners/transform.
- Both rack dialogs route through Controller.
- History view is read-only except explicit Controller actions.
- Model-install failure disables hardware actions and requests restart.

### Regression gates

Run, at minimum:

```powershell
.\env\Scripts\python.exe -m pytest -q <focused Milestone 4 tests>
.\env\Scripts\python.exe -m pytest -q
.\tools\run_pi_virtual_workflow.ps1
git diff --check
```

The full pytest timeout must be at least 15 minutes. The standard SIL must use
an external contained run root and must issue no command to physical hardware.
Run `python -m py_compile` with the project interpreter for every changed
application module.

## Target-Pi qualification

Pi qualification uses a new disposable external machine-data root copied from
the verified M3 evidence or created through the documented M3 first-start
workflow. It must not use the live default external root and must not connect
serial, cameras, balance, or physical motion during fault cases.

Required sequence:

1. Record commit, disposable real path, active machine ID/UUID, and all baseline
   immutable/config hashes.
2. Launch and close once without a configuration event; prove no head/history
   file was created and the untouched M3 store is unchanged.
3. In a no-hardware test harness, commit a small synthetic non-Camera named
   location; verify backup/event/head/config and Model-after-disk ordering.
4. Relaunch from the primary checkout and a detached second checkout; prove
   identical history resolution.
5. Prove the changed target is denied and an unchanged target remains
   authorized without sending a command.
6. Re-verify the synthetic target, prove authorization changes, and keep
   command dispatch mocked/blocked.
7. Exercise rack and plate aggregate commits against disposable data and verify
   one event each.
8. Interrupt/fault at selected journal, config-replace, event, and head
   boundaries; relaunch and prove deterministic reconciliation or the expected
   recovery-required exit.
9. Restore a pre-change backup through the service; verify a new event and
   exact bytes, then re-run bootstrap validation.
10. Run the Pi zero-command safety gate and capture hashes/logs before reviewed
    cleanup.

The real Camera value must not be changed during qualification. A synthetic
copy may be used to prove Camera revocation, but no Camera movement is allowed.

## Compatibility and migration into rc.2

### From `v1.2.0-rc.6`

```text
operator backup
-> M2 imports rc.6 local data
-> M3 verifies/activates immutable baseline
-> M4 sees exact baseline with no history and launches normally
-> first later configuration event lazily creates the anchored history chain
```

### From `v1.3.0-rc.1`

The sequence is identical. The M2 candidate parser may classify archived
`update_logs/...` paths, but M4 begins only after the same M3 activation checks
have succeeded. No tag-specific M4 conversion is required.

### From the already-qualified Milestone 3 store

An active store produced by `08d41bc2` has no configuration head. M4 accepts it
only while its governed files still match immutable M3 evidence exactly. The
first event anchors to the existing verification SHA-256. A missing head plus
changed config is not treated as a legacy edit; it is recovery-required.

### Subsequent checkouts/worktrees

History is under the external machine root, so every checkout for the same OS
account resolves the same head, events, backups, and lock. Code checkout paths
never appear in canonical evidence except as non-authoritative application
provenance. A second checkout cannot write while another instance retains the
configuration lock.

## Rollback strategy

### Before the first Milestone 4 event

Because head creation is lazy, an untouched M3 store remains byte-compatible
with the verified M3 code. Reverting the application commit is possible if
Milestone 4 fails before any event is recorded.

### After any Milestone 4 event

Do not simply run M3 or an earlier release against the canonical store. Older
active-tree validation should reject the additional history, and older code
cannot prove current config from the chain. Preserve the entire external
machine root and use the controlled compatibility/export process defined in
Milestone 6. Never delete history/head/backups merely to make old code start.

### Slice rollback during development

- Revert the current uncommitted slice while retaining its temporary test
  fixtures outside the repository.
- Never point partially implemented code at the default production root.
- If a synthetic store has a history event, discard only that exact disposable
  store after path verification; do not reuse it as production evidence.
- The final Milestone 4 implementation is one dedicated commit so the code
  rollback boundary is explicit.

## Risks and mitigations

- **Weakening M2/M3 validation:** permit only an exact inventory derived from a
  fully replayed chain; keep immutable files byte-bound.
- **Audit written after config:** durable planned event in the journal permits
  exact finalize or verified rollback before MVC.
- **Multi-file partial update:** no MVC exists during recovery and live Model
  installation waits for all files/event/head.
- **Stale in-memory state:** compare expected raw hashes immediately before
  commit and install only service-returned documents.
- **Whole-file source hash revokes unrelated targets:** carry verification only
  for values proven unchanged through the chain; revoke exact dependents.
- **Audit says more than identity system proves:** record both entered operator
  and OS account; describe attribution as operator attestation, not login
  authentication.
- **Unbounded history replay:** replay all events for rc.2 correctness; add a
  separately versioned checkpoint only after measured need, never silently
  truncate.
- **Filesystem durability differs by platform:** record directory-fsync support
  and qualify Windows and Pi; do not claim unsupported guarantees.
- **Model apply fails after commit:** disable hardware actions and restart from
  durable truth.
- **Direct writer reappears:** maintain a writer inventory regression test and
  explicit canonical-mode rejection.
- **M4 confirmation confused with M5 guards:** document that M4 collects actor
  and reason but does not yet judge delta size or geometry.

## Definition of done

Milestone 4 is `verified` only when all of the following are true:

- every known production mutation of a governed config file routes through one
  transaction service or is explicitly rejected;
- immutable activation evidence remains byte-for-byte unchanged;
- every committed file mutation has a verified exact pre-change backup;
- the event chain, head, and current files validate on Windows and Pi;
- pending recovery completes before any hardware-capable construction;
- named cancellation changes neither disk nor memory;
- rack Left/Right and plate four-corner data cannot partially commit or become
  active before persistence;
- changed/new targets are blocked and unchanged targets retain authorization
  only through proved chain continuity;
- exact re-verification and restore create new immutable events;
- support can read/export who, what, when, before, after, workflow, reason,
  outcome, and restore reference;
- focused tests, the full Python suite, standard SIL, changed-module
  compilation, `git diff --check`, writer inventory, and target-Pi no-hardware
  qualification pass;
- implementation/validation findings are recorded in this document and the
  parent live plan;
- one dedicated Milestone 4 implementation commit contains code/tests/docs,
  with no local data or generated evidence.

## Progress checklist

- [x] Audit current location, rack, plate, governed-file, bootstrap, lock, and
  saved-target verification paths.
- [x] Freeze the M2/M3 immutable-baseline compatibility strategy.
- [x] Freeze transaction ordering, schemas, recovery matrix, and verification
  carry-forward/revocation rules.
- [x] Define MVC, import, restore, re-verification, history, tests, Pi gate, and
  rollback behavior.
- [ ] Implement Slice 1.
- [ ] Implement Slice 2.
- [ ] Implement Slice 3.
- [ ] Implement Slice 4.
- [ ] Implement Slice 5.
- [ ] Implement Slice 6.
- [ ] Implement Slice 7.
- [ ] Implement Slice 8.
- [ ] Create the dedicated Milestone 4 implementation commit.
- [ ] Complete and record target-Pi qualification.
- [ ] Mark Milestone 4 `verified` in both plans.

## Planning findings

1. M3 validation binds both the target value and the entire source-file hash;
   a legitimate one-location edit therefore needs per-target derived state, not
   merely an audit line.
2. M2's active tree is an exact immutable manifest. Accepting mutable config
   requires an exact chain-derived inventory; adding broad wildcard exceptions
   would undermine the original migration guarantee.
3. The application already retains the correct cross-process configuration
   lock. Reacquiring it inside the transaction service could deadlock; the
   service must assert the injected token and add only in-process serialization.
4. LocationModel suppresses persistence errors, while WellPlate raises after
   changing memory. Both must stop owning canonical writes in production.
5. Rack state is duplicated in RackModel and two named locations. One committed
   Locations snapshot must update both together after persistence.
6. The secondary rack-fix dialog is a direct Model bypass and must be included,
   not only the main guided rack workflow.
7. There is no authenticated user system. Audit attribution can reliably bind
   the OS account and entered operator attestation, but must not claim stronger
   identity proof.
8. RegulatorProfileStore has a dormant direct save API. Closing it now prevents
   future pressure-profile UI work from bypassing the transaction boundary.
9. Settings and Obstacles have no current writer. Their registry entries and
   conservative target-impact rules should exist, but live hardware-profile
   mutation must remain rejected.
10. A successful durable commit followed by Model failure is not an ordinary
    save failure. Durable disk/history are authoritative; continuing with stale
    runtime state is less safe than requiring restart.
11. Creating a head on every startup would unnecessarily break the last safe
    pre-event rollback path. Lazy creation retains M3 compatibility until the
    first event while still rejecting untracked edits.
12. The experiment audit timeline cannot substitute for configuration history;
    it has different ownership, retention, and recovery meaning.

## Document change log

| Date | Change |
| --- | --- |
| 2026-08-19 | Created the concrete transactional configuration history plan after Milestone 3 target-Pi verification and cleanup. |
