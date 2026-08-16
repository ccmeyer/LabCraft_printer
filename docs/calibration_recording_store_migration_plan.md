# Calibration Recording Store Migration: Milestone 0 Contract and Plan

Status: Milestones 0 through 5 complete; Milestone 6 implementation qualification in progress

Prepared: 2026-08-14

## Purpose

This document defines the staged migration from the experiment-level
`calibration.json` history to an always-on, per-process calibration recording
store. It freezes the storage ownership, durability, compatibility, SIL, and
rollback contracts that later implementation milestones must preserve.

Milestone 0 changes no application behavior. It does not change firmware,
device protocol, motion, pressure control, timing, calibration algorithms,
image analysis, or existing experiment data.

## Decision summary

The migration adopts the following decisions:

1. Canonical structured calibration persistence will always be active. An
   operator will not be able to disable result persistence.
2. Image retention will be controlled independently from structured result
   persistence.
3. The existing `calibration_recordings/<process>/<process_run_id>/` layout
   will remain the run container. Existing diagnostic artifacts and tools will
   remain compatible during the migration.
4. New canonical `updates.jsonl` and terminal `result.json` artifacts will be
   added to each process run. A compact experiment-level
   `calibration_index.jsonl` will support bounded history queries.
5. The authoritative unit is a process-run bundle, not one growing experiment
   document. The compact index is rebuildable and is not the sole copy of a
   result.
6. `calibration.json` will remain dual-written until the new store, readers,
   migration tooling, storage-contract SIL, and Pi performance lane are
   qualified.
7. Existing `calibration.json` files will remain readable and will never be
   deleted or rewritten automatically by this migration.
8. Full camera and image-analysis SIL is deferred. This migration will use
   deterministic structured payloads and small synthetic images only to prove
   storage and retention behavior.

## Safety and scope boundary

### In scope

- Calibration session, process-run, result, printer-head, and stock identity.
- Durable structured updates and terminal process results.
- Compact history indexing and deterministic index rebuild.
- Separate structured-only, key-evidence, and full-capture retention policies.
- Legacy/new-store dual-writing, parity checking, reader fallback, and
  historical conversion.
- Calibration UI history, selection, recheck, and application reads.
- Calibration memory, audit, export, and experiment-lifecycle integration.
- Hardware-isolated storage-contract SIL on Windows and Raspberry Pi.
- Failure injection for interrupted, corrupt, partial, and unavailable writes.
- Pi latency, memory, file-count, and disk-growth measurement.

### Out of scope

- Changes to calibration calculations, thresholds, state-machine decisions, or
  process ordering.
- Full image-analysis or virtual-camera SIL.
- Claims about physical droplet formation, optical fidelity, pressure accuracy,
  collision safety, or calibration quality.
- Firmware, opcodes, serial framing, GPIO, flash timing, or device protocol.
- Changes to execution-calibration semantics in
  `execution_calibrations.json`, except replacing source references after the
  new calibration result identity is authoritative.
- Automatic deletion, compaction, or relocation of historical experiment
  data.
- General calibration-memory redesign. Calibration memory remains a derived
  consumer of authoritative calibration results.

## Current production call path

The migration must preserve this application path:

```text
DropletImagingDialog calibration button
-> Controller.start_*_calibration()
-> CalibrationManager.start_*() / calibration queue
-> BaseCalibrationProcess subclass and Qt state machine
-> CalibrationManager motion/settings/capture signals
-> Controller handlers
-> Machine_FreeRTOS in production or SimulatedMachine in SIL
-> process calibrationDataUpdated payload(s)
-> CalibrationManager.onCalibrationDataUpdated()
-> calibration.json append in memory + whole-file atomic rewrite
-> calibration_recordings analysis.jsonl duplicate when recording is enabled
-> history / recheck / application / calibration-memory consumers
```

Primary code locations at the Milestone 0 baseline:

| Responsibility | Current location |
| --- | --- |
| Calibration buttons and mode preflight | `FreeRTOS-interface/CalibrationClasses/View.py`, calibration start methods near lines 11757-12000 |
| Controller delegation | `FreeRTOS-interface/Controller.py`, calibration methods near lines 9642-9740 |
| Controller capture, motion, and settings adapters | `FreeRTOS-interface/Controller.py`, `handle_capture_request`, `handle_move_request`, `handle_absolute_move_request`, and `handle_settings_change_request` |
| Queue and process wiring | `FreeRTOS-interface/CalibrationClasses/Model.py`, `start_calibration_queue()` and `start_active_calibration()` |
| Per-process recorder | `FreeRTOS-interface/CalibrationClasses/Model.py`, `CalibrationProcessRecorder` |
| Structured update hook | `FreeRTOS-interface/CalibrationClasses/Model.py`, `onCalibrationDataUpdated()` and `_append_calibration_step_payload()` |
| Legacy atomic writer | `FreeRTOS-interface/CalibrationClasses/Model.py`, `_save_atomic()` |
| Experiment path ownership | `FreeRTOS-interface/Model.py`, `ExperimentModel.update_all_paths()` |

The simulated machine currently supports the command contract used by virtual
printing but deliberately rejects droplet-camera capture. The existing
synthetic-calibration adapter generates a candidate and registers it directly;
it does not exercise `calibrationDataUpdated` or the production calibration
recording lifecycle. Milestone 1 closes only that storage-test gap.

## Current storage baseline

### `calibration.json`

`calibration.json` is one schema-version-1 document per experiment. It contains
an array of calibration sessions:

```text
schema_version
runs[]
  run_id
  started_at
  ended_at
  outcome
  error_message
  stock and printer-head identity
  notes
  steps{phase -> payload[]}
  flat_measurements[]
```

Every `calibrationDataUpdated` payload is augmented with a timestamp, current
settings, calibration-session metadata, and canonical phase name. The payload
is appended to the in-memory document and the entire formatted JSON document
is synchronously written, flushed, `fsync`ed, and replaced.

This provides an atomic whole-document snapshot, but write cost grows with all
prior calibration sessions in the experiment. The write occurs on the
calibration manager's Qt thread.

### `calibration_recordings`

When recorder mode is enabled, every process gets a directory:

```text
calibration_recordings/
  <process_name>/
    <process_run_id>/
      run_meta.json
      verdict.json
      events.jsonl
      analysis.jsonl
      captures/
```

`run_meta.json` and `verdict.json` are atomically replaced. Events and analysis
are append-only JSONL. Captures are copied into an asynchronous image-write
queue and drained during finalization.

For processes that emit `calibrationDataUpdated`, the same augmented payload
stored under `calibration.json.runs[].steps[]` is also appended to
`analysis.jsonl` as `kind = "calibration_data_updated"`. The recording also
contains additional lifecycle, decision, analysis, verdict, and capture data.

The current recorder is diagnostic and best-effort:

- recorder mode can be disabled;
- start, append, capture, and finalize failures are caught and printed;
- a calibration can continue without a complete recording;
- JSONL appends do not currently flush and `fsync` each structured update;
- there is no canonical terminal result or compact query index.

It therefore cannot replace `calibration.json` without the later durability
and reader milestones.

### Informational Pi observations

The read-only investigation preceding Milestone 0 observed the following on
the target Pi. These values motivate the work but are not frozen acceptance
thresholds:

| Observation | Value |
| --- | --- |
| `calibration.json` files | 486 |
| Combined `calibration.json` size | approximately 313 MB |
| Largest `calibration.json` | approximately 15.7 MB |
| Largest-file Python load | approximately 137 ms |
| Largest-file compact serialization | approximately 610 ms |
| Largest-file formatted streaming serialization before disk I/O | approximately 785 ms and 1,196,415 writer calls |
| `calibration_recordings` storage | approximately 37 GB and 208,341 files |
| Recorded process runs | approximately 6,955 across 225 experiments |

The primary performance reason to retire `calibration.json` is eliminating
whole-history rewrites. Image-retention policy, not removal of
`calibration.json`, is the primary control for disk accumulation.

## Current producer and consumer inventory

Later milestones must update or preserve every row in this inventory.

### Producers and lifecycle owners

| Producer or owner | Current dependency | Required migration treatment |
| --- | --- | --- |
| `CalibrationManager.begin_session()` / `end_session()` | Creates and finalizes a `calibration.json` session run | Create and own a stable `calibration_session_id`; retain legacy write during dual-write milestones |
| `CalibrationManager.onCalibrationDataUpdated()` | Appends a phase payload and rewrites `calibration.json`; copies it to recording analysis | Append one canonical update first, then perform legacy shadow write |
| `CalibrationProcessRecorder` | Creates process directory, diagnostics, verdict, and captures | Evolve or wrap with an authoritative run-store component without breaking diagnostic files |
| `CalibrationManager.onCalibrationCompleted()` | Finalizes diagnostic recording before cleanup and queue advance | Commit terminal result and index before reporting successful completion |
| `CalibrationManager.onCalibrationError()` / Stop | Finalizes diagnostics with error or stopped outcome | Commit a terminal non-applicable outcome when possible; preserve incomplete evidence on storage failure |
| `ExperimentModel.initialize_experiment()` | Seeds `{}` at `calibration.json` and may begin a session | Stop seeding only after new-store cutover; new experiments should create storage lazily |
| `ExperimentModel.update_all_paths()` | Defines `calibration_file_path` | Add explicit recording-root and index paths without changing legacy paths |
| Experiment duplication | Seeds a fresh empty `calibration.json`; does not copy recordings | New design-only copies must start without calibration results or recordings |

### Runtime and UI readers

| Consumer | Current read | Required new-store behavior |
| --- | --- | --- |
| Current-run prerequisite getters | `_latest_step_list()`, centered-nozzle, emergence, and pressure presence from the active `calibration.json` session | Read active process/session state backed by canonical updates; do not scan historical directories |
| Recheck context construction | Locates source run and source step/pressure records in `calibration.json` | Resolve by `result_id`, `process_run_id`, update index, and pressure index |
| Characterization summary/history | Scans matching `calibration.json` runs and materializes droplet and stream rows | Query compact index projections and load a process result only when selected |
| Load/recheck UI actions | Depend on source run, phase, step, and pressure indices in summary rows | Preserve these source coordinates during compatibility period and add stable result/update identity |
| Calibration application | Converts a selected summary row into `execution_calibrations.json` state | Store stable `result_id` and result hash in the applied record while preserving legacy source fields until separately migrated |
| Synthetic SIL calibration history | Uses retained SIL artifacts and transient/historical candidates | Remains separate; storage SIL will use the real manager persistence path |

### Derived and external readers

| Consumer | Current dependency | Required migration treatment |
| --- | --- | --- |
| `CalibrationMemoryStore` | Records `calibration_json_path`, calibration run ID/index, and process-recording paths | Record process-result references and retain legacy refs for old runs |
| `CalibrationMemoryAggregator` | Reopens `calibration.json` to resolve an authoritative session run | Prefer canonical process results; legacy path remains fallback |
| `ExperimentAuditLog` | Records `calibration_file_path` and manager-provided artifact refs | Add result/index references; keep legacy path when present |
| `CalibrationRecordExport` | Archives recordings and optional `calibration.json` | Include canonical updates, results, and index automatically; retain legacy file when present |
| Calibration recording summary tool | Reads `run_meta.json`, `events.jsonl`, and `analysis.jsonl` | Existing inputs remain compatible; new result status may enhance output additively |
| Calibration replay tool | Reads recording metadata, events, analysis, and captures | Existing inputs remain compatible; no image-analysis expansion is required by this migration |
| Stream-analysis tools | Discover fixed process directories and consume metadata, JSONL, fit files, and captures | Preserve directory names and diagnostic files; migrate any `calibration_data_updated` dependency before removing that duplicate from analysis |
| Pre-breakup/refuel dataset tools | Discover run directories and read metadata, analysis, events, and captures | Preserve current artifacts and process-specific requirements |

## Desired storage ownership

The desired experiment layout is:

```text
<experiment>/
  calibration_index.jsonl
  calibration_recordings/
    <process_name>/
      <process_run_id>/
        run_meta.json
        updates.jsonl
        result.json
        verdict.json
        events.jsonl
        analysis.jsonl
        captures/
```

Existing process-specific artifacts such as fit files, frame manifests,
datasets, reports, and annotations remain beside these files as they are today.

### Authority rules

- The authoritative calibration record is the valid process-run bundle:
  `run_meta.json`, zero or more canonical updates, and one terminal
  `result.json`.
- A completed result-producing process must have at least one canonical update
  and a valid completed result.
- A stopped, failed, interrupted, dataset-only, or operational process may have
  zero canonical calibration updates, but its terminal result must explicitly
  classify its `result_kind` and outcome.
- The index is a durable query projection that can be rebuilt from valid
  terminal results. It is not the only copy of result data.
- `events.jsonl`, `analysis.jsonl`, verdicts, and retained images are evidence
  and diagnostics. They are not the authoritative calibration value.
- `execution_calibrations.json` remains authoritative for what calibration was
  applied to an execution plan. It references, but does not replace, the
  source calibration result.
- Absolute paths are diagnostic references only and never identity.

## Identity contract

The following identifiers have distinct meanings and must not be conflated:

| Identifier | Meaning | Lifetime |
| --- | --- | --- |
| `calibration_session_id` | One manager session that may contain a sequence of process runs | From `begin_session()` through `end_session()` |
| `process_run_id` | One invocation of one calibration process; current recorder directory identity | Immutable for the process run |
| `update_id` | One emitted structured calibration update | Immutable and unique within the repository-generated record set |
| `result_id` | One terminal materialized result | Immutable; assigned once at terminal commit |
| `result_sha256` | Canonical content hash used for integrity and dual-write parity | Recomputed from the defined semantic content |
| `printer_head_id` | Stable physical printer-head identity when available | As defined by the calibration identity schema |
| `stock_id` | Stable stock-solution identity when available | As defined by the calibration identity schema |

Every run must also retain the current reagent, concentration, units, head-type,
and identity-quality context when available. Unknown identity is represented
explicitly; list position, queue position, rack slot, run number, directory
order, and display label are never substitutes for stable identity.

The process-run ID used in paths and metadata must be identical. The current
recorder's `run_id` becomes `process_run_id`; a compatibility `run_id` alias may
remain during the transition. The current `calibration.json` run ID becomes
`calibration_session_id` in new artifacts.

## Canonical schemas

Schema names and versions are independent so an additive change in one file
does not require changing every recording artifact.

### Canonical update: `updates.jsonl`

Each nonblank line is one JSON object with these required fields:

| Field | Contract |
| --- | --- |
| `schema_name` | `labcraft.calibration_recording.update` |
| `schema_version` | `1` |
| `update_id` | Stable unique string |
| `update_index` | One-based, gap-free integer within the process run |
| `recorded_at_utc` | UTC timestamp with `Z` suffix |
| `calibration_session_id` | Owning manager session ID |
| `process_run_id` | Owning process-run ID |
| `process_name` | Concrete calibration process class name |
| `phase_name` | Canonical phase key |
| `payload_sha256` | SHA-256 of canonical `payload` bytes |
| `payload` | The augmented payload currently stored in `calibration.json`, preserving `timestamp`, `settings`, `meta`, `phase`, measurements, and result |

Updates are appended in signal-delivery order. Duplicate `update_id` values are
idempotent only when their canonical content matches exactly; a conflicting
duplicate is corruption.

### Terminal result: `result.json`

`result.json` is the atomic commit marker and compact materialization for one
process run. Required fields:

| Field | Contract |
| --- | --- |
| `schema_name` | `labcraft.calibration_recording.result` |
| `schema_version` | `1` |
| `result_id` | Stable unique terminal-result ID |
| `result_sha256` | SHA-256 of the canonical semantic result body, excluding the hash field itself |
| `calibration_session_id` | Owning manager session ID |
| `process_run_id` | Owning process-run ID |
| `process_name` | Concrete process class name |
| `phase_name` | Canonical phase key |
| `result_kind` | `calibration`, `dataset`, `operational`, or `none` |
| `outcome` | `completed`, `stopped`, `error`, `interrupted`, or `storage_error` |
| `started_at_utc` / `ended_at_utc` | Process timing |
| `identity` | Stock, reagent, printer-head, head-type, and identity-quality snapshot |
| `capture_policy` | Effective capture policy for this run |
| `update_count` | Number of committed canonical updates |
| `update_ids` | Ordered update IDs |
| `updates_sha256` | Hash over the ordered update indexes, IDs, and payload hashes |
| `final_update_id` | Last update ID or `null` |
| `summary_projection` | Bounded typed fields required for history display, matching, recheck lookup, and application eligibility |
| `warnings` | Structured terminal storage/evidence warnings |

The result must not duplicate every large update payload. Full structured data
remains in `updates.jsonl`; `result.json` binds it by ordered IDs and hashes.

Only `outcome = "completed"`, `result_kind = "calibration"`, valid identity,
valid hashes, and process-specific application eligibility may be offered for
calibration application. File presence alone is insufficient.

### Run metadata: `run_meta.json`

The authoritative store introduces
`schema_name = "labcraft.calibration_recording.run_meta"` and
`schema_version = 2`. Existing diagnostic fields remain. Required new fields:

- `process_run_id`;
- `calibration_session_id`;
- `result_kind`;
- `capture_policy_requested` and `capture_policy_effective`;
- `structured_persistence_required = true`;
- `result_id` and `result_sha256` after terminal commit;
- canonical update count;
- explicit recorder, canonical-storage, and capture warning counts.

The compatibility `run_id` field remains equal to `process_run_id` while
existing tools expect it.

### Experiment index: `calibration_index.jsonl`

Each terminal result contributes an idempotent index event:

| Field | Contract |
| --- | --- |
| `schema_name` | `labcraft.calibration_recording.index_event` |
| `schema_version` | `1` |
| `event_kind` | Initially `result_committed`; later additive values require documented reader behavior |
| `index_event_id` | Unique event ID |
| `recorded_at_utc` | Commit timestamp |
| `calibration_session_id`, `process_run_id`, `result_id` | Stable join identities |
| `result_relpath` | POSIX relative path beneath the experiment directory |
| `result_sha256` | Expected result hash |
| `process_name`, `phase_name`, `result_kind`, `outcome` | Query classification |
| `identity_projection` | Stable head/stock/reagent matching keys and quality |
| `summary_projection` | Bounded history-display and selection fields |

The index may not contain raw images, complete measurements, full online-stream
traces, or absolute paths. Index readers select the last valid identical event
for a result and reject conflicting duplicate identities.

### Canonical JSON and hashes

Canonical semantic hashing uses:

- UTF-8;
- JSON object keys sorted lexicographically;
- separators `,` and `:` without formatting whitespace;
- finite JSON numbers only;
- Python/NumPy scalar normalization to JSON scalars;
- arrays preserved in order;
- no implicit conversion of `NaN` or infinity to nonstandard tokens.

Pretty formatting on disk does not affect semantic hashes. Hash inputs and
excluded storage fields must be implemented once in the run-store module and
covered by golden vectors.

## Result-kind contract

Every process must declare one terminal result kind:

| Kind | Meaning | Application behavior |
| --- | --- | --- |
| `calibration` | Produces a value that can satisfy prerequisites, populate history, be rechecked, or be applied | Eligible only after process-specific validation |
| `dataset` | Produces a retained dataset or acquisition manifest | Never directly applied as a calibration value |
| `operational` | Produces an operational outcome such as prime/recovery evidence | Never directly applied as a volume calibration |
| `none` | No structured result was expected | Never applied; reason must be explicit |

Nozzle-position and dataset workflows require explicit adapters because their
historical generic `calibration_data_updated` coverage is not identical to the
main result-producing processes. A completed process must never be silently
classified as `none` because an expected signal was missed.

## Durability and completion contract

### Mandatory ordering

For each structured update:

1. Validate and normalize the payload.
2. Append one canonical update line.
3. Flush and `fsync` the update before acknowledging the update to downstream
   persistent-state consumers.
4. Perform the legacy shadow write while dual-writing is enabled.
5. Record diagnostic analysis without duplicating authority.

For terminal completion:

1. Drain capture writes according to the effective policy and process
   requirements.
2. Validate the ordered updates and construct the terminal result.
3. Write `result.json` through a same-directory temporary file, flush,
   `fsync`, and atomic replace.
4. Append, flush, and `fsync` the idempotent index event.
5. Atomically update `run_meta.json` with terminal state and result identity.
6. Only then emit successful manager completion, expose the result in history,
   or allow it to be applied.

An index failure after a valid result commit leaves a recoverable orphan
result. The active action reports a storage error and does not offer the result
for application. Index rebuild can recover it on the next explicit recovery or
startup maintenance pass.

### Failure classification

| Failure | Required behavior |
| --- | --- |
| Cannot create canonical process run | Do not start the calibration process once canonical persistence is authoritative |
| Canonical update validation or write fails | Stop the process through the normal calibration error path; do not apply or queue the next process |
| Terminal result commit fails | Preserve updates and diagnostics; report storage error; do not report successful completion |
| Index append fails after result commit | Preserve result; report storage error; require rebuild before normal visibility |
| Diagnostic event/analysis write fails with canonical store healthy | Surface and retain a warning when possible; canonical result may remain valid |
| Optional image write fails | Mark evidence incomplete and warn; calibration result may remain valid |
| Process-required image/dataset write fails | Fail that process according to its declared evidence requirement |
| Capture drain times out | Record pending/failure counts; apply process-specific evidence rule; never silently claim full evidence |
| Abrupt process/App/Pi termination | Leave no terminal result unless atomic commit completed; preserve parseable updates; classify unfinished run during recovery |

### JSONL recovery

- One incomplete trailing JSONL line may be ignored and reported during
  recovery.
- A malformed interior line is corruption and must not be silently skipped by
  authoritative readers.
- Recovery never edits the original JSONL automatically. A rebuilt index is
  written separately or atomically replaced from validated results.
- Replaying an already committed update or index event is idempotent only when
  identity and canonical content match.

## Capture-retention policy

Structured recording is always enabled. The operator-facing control changes
from an enable/disable checkbox to capture retention:

| Policy | Saved pixels | Required structured evidence |
| --- | --- | --- |
| `structured_only` | None | Metadata, canonical updates, result, index, events/analysis policy, and explicit `capture_omitted` evidence |
| `key_evidence` | Process-designated key frames only | All structured evidence plus selected captures; recommended default |
| `full` | Every recorder-requested capture | All structured evidence and all captures |

Every capture request still receives a capture ID and metadata. Under
`structured_only`, the store records that pixel retention was intentionally
omitted; it does not pretend a file was written.

Processes may declare a minimum capture policy. Dataset acquisition may require
`full`; a process that requires saved pixels must reject an incompatible
policy or explicitly elevate it with operator-visible confirmation. Ordinary
calibrations may analyze an in-memory frame while retaining no pixel data.

Policy changes affect only future process runs. A run snapshots its requested
and effective policy at start; it cannot silently change midway.

## Reader and compatibility contract

### Resolution states

Readers must handle these explicit states:

| Available data | Behavior during compatibility period |
| --- | --- |
| Valid new result only | Read new result |
| Legacy `calibration.json` only | Read through legacy adapter without writing |
| Valid matching new and legacy result | Prefer new result and record parity success |
| New result invalid, legacy valid | Report new-store issue; fallback only while the milestone's fallback flag permits it |
| New and legacy both valid but disagree | Typed parity conflict; never silently select one for application |
| Neither valid | No calibration available with typed reason |

### Stable source coordinates

Summary rows must add stable `result_id`, `process_run_id`, `update_id`, and
result hash. Legacy `source_run_id`, phase key, step index, and pressure index
remain during the compatibility period so recheck and existing tests do not
lose their source coordinates.

### Index rebuild

Index rebuild:

- scans only terminal `result.json` files beneath the selected experiment;
- validates result, update chain, relative path, and identities;
- writes a deterministic new index through a temporary file and atomic replace;
- never modifies process-run contents;
- reports invalid, incomplete, duplicate, and conflicting runs;
- produces the same semantic event set when repeated without source changes.

Routine history display must not rebuild or recursively scan recordings.
Rebuild is startup recovery after a detected index problem, an explicit repair
operation, or a migration step.

## Historical conversion contract

The historical conversion tool is introduced only after dual-write and reader
qualification. It must:

1. Default to dry-run.
2. Accept an explicit experiment directory, never an unbounded workspace root.
3. Read existing `calibration.json` and matching recording evidence without
   modifying either.
4. Resolve session/process linkage using explicit IDs and payload metadata;
   ambiguous linkage is reported, not guessed.
5. Write new canonical artifacts only when the target does not exist, or when
   an existing target is byte/semantically identical.
6. Be resumable and idempotent.
7. Produce a manifest containing source hashes, counts, conversions, skips,
   conflicts, and generated hashes.
8. Validate counts and canonical payload parity before reporting success.
9. Never delete, rename, truncate, or rewrite historical source files.

Converted records are labeled with migration provenance and source hashes.
Natural new records and migrated records use the same reader contract.

## Storage-contract SIL

### Claim boundary

Storage-contract SIL will prove:

```text
scripted calibration process lifecycle
-> real CalibrationManager process wiring
-> canonical update/result/index persistence
-> optional legacy dual-write and parity
-> capture retention behavior
-> history/select/recheck/application readers
-> fresh application reload and index rebuild
```

It will not prove camera capture, segmentation, image analysis, physical
calibration quality, real machine behavior, firmware, or protocol behavior.
Reports and test names must use `storage_contract` terminology and must not
claim full calibration acquisition coverage.

### SIL process boundary

Milestone 1 introduces a simulation-only scripted process derived from the
normal calibration process interface. It must:

- be constructible only in the canonical simulation runtime;
- run through `CalibrationManager.start_active_calibration()` so normal signal
  connection, recorder start, completion/error handling, cleanup, and queue
  behavior execute;
- emit deterministic stage changes and one or more
  `calibrationDataUpdated` payloads from a fixture;
- optionally submit small deterministic image arrays to the recorder solely to
  exercise capture retention and asynchronous writes;
- issue no physical machine, serial, GPIO, camera, balance, motion, pressure,
  or dispense operation;
- retain zero simulator command dispatch unless a future storage scenario
  explicitly requires a simulated non-hardware command contract.

Production calibration process mappings must not expose the scripted process.

### Fixture derivation

Fixtures may be derived from existing calibration records through a separate
read-only sanitizer. Tracked fixtures must:

- be self-contained and not depend on `FreeRTOS-interface/Experiments`;
- replace printer-head, stock, reagent, experiment, path, run, and timestamp
  identities with deterministic synthetic values;
- remove operator notes and unrelated metadata;
- preserve payload shape, update ordering, numeric types/ranges, list sizes,
  optional fields, warnings, and terminal classification needed by the test;
- contain no raw images by default;
- include schema identity, fixture version, source-shape description, expected
  canonical hashes, and explicit limitations;
- be immutable once used as a qualified parity oracle. Corrections require a
  new fixture version and explanation.

The sanitizer is not run automatically by tests. Tests consume only reviewed,
tracked fixtures.

### Minimum fixture catalog

| Fixture | Required coverage |
| --- | --- |
| `droplet_sequence_nominal_v1` | Multiple result-producing phases in one calibration session |
| `online_stream_large_multi_update_v1` | Representative large payload and more than one canonical update |
| `multi_head_isolation_v1` | At least two synthetic heads and stocks with overlapping process types |
| `non_calibration_terminal_v1` | Dataset or operational result kind with zero or non-applicable calibration updates |
| `stopped_and_error_v1` | Terminal stopped/error outcomes excluded from application |
| `capture_policy_v1` | Structured-only, key-evidence, and full capture counts and bytes |
| `legacy_parity_v1` | Exact legacy/new payload parity and source-coordinate preservation |

### SIL assertions

Every positive storage scenario must assert:

- expected session, process-run, update, and result identities;
- gap-free update indexes and exact payload hashes;
- exact result/update chain hash;
- one valid terminal result and one idempotent index projection per process
  run;
- exact summary rows and head/stock isolation;
- fresh-process reload produces the same normalized result and summary;
- selected calibration application references the expected result;
- capture policy produces exact saved/omitted counts;
- legacy parity while dual-writing is enabled;
- no physical hardware factory or non-simulated port is used;
- no unexpected simulator command or dispense is emitted.

Negative scenarios must inject and assert start, update, result, index,
diagnostic, capture, drain-timeout, trailing-line, interior-corruption,
duplicate, and interrupted-run behavior according to the durability table.

### SIL tiers

| Tier | Purpose | Proposed selection |
| --- | --- | --- |
| Unit | Canonicalization, schemas, hashing, append, commit, index, rebuild, and fault injection | Standard pytest |
| Component | Calibration manager lifecycle and dual-write parity with scripted process | Standard pytest if bounded |
| Host storage-contract SIL | Real Qt/model composition, UI readers, reload, and application | `sil_lifecycle` until runtime proves suitable for standard smoke |
| Pi storage-contract performance | Multi-head repetition and filesystem performance on target CPU/storage | Explicit Pi SIL command only |

The existing focused image-analysis replay tests remain valuable but are not a
gate for this migration beyond the normal affected-area regression suite.

## Performance qualification contract

Milestone 1 records the current legacy baseline and freezes the exact target-Pi
workload. The initial proposed workload is eight synthetic printer heads with
at least 25 process runs per head, including periodic large online-stream
payloads, executed under `structured_only`. A short separate run exercises
`key_evidence` capture draining.

The report must retain:

- platform, source fingerprint, fixture hashes, run count, payload bytes, and
  capture policy;
- append latency, result-finalize latency, index latency, history-load latency,
  and fresh-reload latency distributions;
- first-quartile versus last-quartile latency;
- peak RSS and end RSS;
- file count and byte growth by artifact type;
- exact update/result/index counts and integrity failures;
- any legacy `calibration.json` size and rewrite counts.

Final numerical gates are frozen from the qualified Milestone 1 baseline rather
than invented in Milestone 0. At minimum, the new-store qualification must
show:

- no `calibration.json` creation or rewrite in new-store-only mode;
- exact counts and hashes with zero cross-head leakage;
- bounded memory with no monotonic run-count leak;
- no write path whose work is proportional to total experiment history;
- no material last-quartile latency degradation relative to the first
  quartile after accounting for the frozen tolerance;
- history open and fresh reload within explicit watchdogs.

Host timing is diagnostic. Target-Pi timing is the performance acceptance lane.

## Implementation milestones

Each milestone is independently reviewable and must have one rollback point.

### Milestone 0: contract and inventory

Scope:

- Freeze this contract, consumer inventory, desired schemas, SIL boundary,
  milestones, risks, and rollback policy.

Exit criteria:

- This document exists and is internally consistent.
- Current producer/consumer call paths are represented.
- Full image-analysis SIL is explicitly deferred.
- No runtime or persisted data changes are made.

Rollback: remove this document; no runtime state is affected.

### Milestone 1: baseline storage-contract SIL

Completion status on 2026-08-14: the fixture catalog, guarded process,
artifact inspection, composed lifecycle, frozen stress workload, Pi
orchestration contract, and baseline-freezing tool are implemented. Focused,
host lifecycle, host stress, and full-suite validation pass. The qualified
Raspberry Pi 5 NVMe/ext4 report set was measured from clean commit
`ddea246c2aa89f492abf9cc8d4755e92af92d9f0`, and the tracked
`calibration_storage_legacy_pi5_v1.json` candidate baseline is frozen. See
`docs/calibration_recording_store_milestone_1_completion.md` for hashes,
results, limitations, and rollback.

Scope:

- Add sanitized, canonical fixtures.
- Add a simulation-only scripted calibration process and composed lifecycle.
- Prove current `calibration.json` plus recorder duplication, summary, apply,
  and fresh reload.
- Add a target-Pi baseline report shape and freeze the performance workload.

Exit criteria:

- Current legacy and recording payloads match fixture oracles.
- Multi-update, multi-head, terminal-error, and capture-policy scaffolding is
  proven without hardware access.
- Existing simulation safety contracts and full Python suite pass.

Rollback: remove SIL-only additions; production behavior remains unchanged.

### Milestone 2: new run store in shadow mode

Completion status on 2026-08-15: the canonical run-store module, manager
shadow integration, fixture-catalog dual-write journey, frozen 8x25 shadow
workload, failure injection, index rebuild/idempotency coverage, Pi wrapper,
and shadow-baseline tooling are implemented. Existing readers and legacy
writes remain unchanged. Focused, lifecycle, stress, and full-suite host gates
pass. A clean Raspberry Pi 5 NVMe/ext4 qualification passes the Milestone 1
comparison and the tracked `calibration_storage_shadow_pi5_v1.json` candidate
baseline is frozen. See
`docs/calibration_recording_store_milestone_2_completion.md` for exact source,
report, baseline, restoration, and rollback evidence.

Scope:

- Add canonicalization and run-store module.
- Write `updates.jsonl`, `result.json`, and index while keeping all current
  readers and legacy writes unchanged.
- Record parity diagnostics without making new storage authoritative.

Exit criteria:

- Golden schema/hash tests and all failure-injection unit tests pass.
- Storage SIL proves exact dual-write parity across the fixture catalog.
- Shadow writes do not change calibration completion behavior.
- Initial Pi comparison shows no material regression over the current writer.

Rollback: disable/remove shadow writer; legacy path remains authoritative.

### Milestone 3: authoritative structured persistence and capture policy

Scope:

- Make canonical run creation, updates, result, and index mandatory.
- Replace recorder enable/disable UI with capture-retention policy.
- Continue legacy dual-writing.
- Enforce fail-closed application/completion behavior for canonical storage
  failures.

Exit criteria:

- Every process has an explicit `result_kind` and terminal adapter.
- Structured-only, key-evidence, full, and process-minimum policies pass.
- Storage failures stop completion/application exactly as contracted.
- Legacy output remains compatible.

Rollback: feature flag restores legacy-authoritative completion and current
recorder toggle while retaining any additive new artifacts.

Completed 2026-08-15. The authoritative lifecycle and frozen 8-head x 25-run
SIL scenarios pass, the full Python suite passes, and the qualified Raspberry
Pi 5 candidate passes every Milestone 2 timing and RSS comparison with zero
integrity failures. The tracked evidence and operational rollback details are
recorded in `docs/calibration_recording_store_milestone_3_completion.md`.

### Milestone 4A: primary reader cutover

Scope:

- Move current-session prerequisites, history/summary, selection, load,
  recheck, and calibration application source reads to the new store.
- Retain typed legacy fallback.

Exit criteria:

- New-only, legacy-only, matching-dual, invalid-new, and conflict cases pass.
- Stable result/update identities survive fresh reload.
- Multi-head UI rows, selection, recheck, and applied result references are
  exact.

Rollback: switch reader preference to legacy; dual writes continue.

Completed 2026-08-15. The Qt-free primary reader, typed summary projection,
commit-gated current-session cache, exact selection/recheck resolution,
schema-v2 application references, explicit repair CLI, and registered
lifecycle/stress SIL scenarios pass. The clean-commit Raspberry Pi 5
qualification preserves the frozen 200-process/232-update workload, passes all
Milestone 3 timing and RSS limits, and records zero integrity, fallback, or
conflict events. The tracked evidence, limitations, and rollback procedure are
recorded in `docs/calibration_recording_store_milestone_4a_completion.md`.

### Milestone 4B: secondary reader cutover

Scope:

- Move calibration memory, audit, export, summary tooling, experiment
  initialization, and duplication to new references.
- Preserve recording-analysis and dataset tool compatibility.

Exit criteria:

- Consumer inventory has an implemented disposition for every row.
- Calibration-memory aggregation no longer requires new experiments to have a
  `calibration.json`.
- Exports contain the complete new bundle and retain legacy files when present.

Rollback: restore individual consumer fallback; core dual writes continue.

Implementation completed on 2026-08-15. Canonical session resolution,
schema-v2 calibration-memory references, canonical audit/export/summary and
offline-tool consumers, the complete consumer inventory, structured live SIL
progress, and registered lifecycle/stress scenarios are implemented. Final
host and Raspberry Pi evidence is recorded in
`docs/calibration_recording_store_milestone_4b_completion.md`.

The Milestone 4B Pi gate uses no warm-up and one measured frozen 8x25 pass
with a 3,600-second scenario budget. This is explicitly single-sample
candidate evidence; multi-run statistical qualification is optional and is
not required for Milestone 4B completion.

### Milestone 5: historical conversion

Scope:

- Add dry-run, conversion, validation, and resume tooling.
- Qualify representative historical calibration shapes and ambiguity reports.

Exit criteria:

- Repeated conversion is idempotent.
- Source files remain byte-identical.
- Counts, identities, payload hashes, and conflict reports are exact.
- Converted experiments behave like natural new-store experiments through
  readers and export.

Rollback: stop using generated additive artifacts; source data is untouched.

Implementation completed on 2026-08-15. The converter defaults to dry-run,
requires one explicit experiment, records deterministic migration provenance,
supports explicit resume and validation, and exposes generated bundles only
after a completed manifest validates. The typed reader and export path consume
the additive artifacts while preserving legacy fallbacks. A reviewed 12-step
fixture and one short composed Windows/Pi lifecycle replace the unrelated
200-process writer workload for this offline-only milestone. Final host and Pi
evidence is recorded in
`docs/calibration_recording_store_milestone_5_completion.md`.

### Milestone 6: stop legacy writes for new experiments

Scope:

- Disable `calibration.json` creation and rewriting for new experiments behind
  a rollback flag.
- Keep legacy readers and historical files.

Exit criteria:

- Full Python suite and storage-contract SIL pass in new-store-only mode.
- Target-Pi workload passes correctness and performance gates.
- No `calibration.json` is created or rewritten in new-store-only scenarios.
- A canary rollback run successfully re-enables dual-writing.

Rollback: re-enable legacy writer. Existing new-store artifacts remain
additive and readable.

### Milestone 7: proving period and writer retirement

Scope:

- Retain operational evidence over an agreed proving period.
- Remove dead legacy writer code only after no required reader depends on it.
- Preserve the legacy reader indefinitely unless a separate approved plan
  retires it.

Exit criteria:

- No unresolved parity, corruption, performance, or support issues from the
  proving period.
- Documentation and operator controls describe structured persistence and
  capture retention accurately.
- Rollback remains possible through the last release that contains the legacy
  writer.

Rollback: deploy the prior qualified release and re-enable dual-writing; do
not modify historical files.

### Deferred milestone: image-analysis SIL

This is not part of Milestones 0-7. A future separately approved project may
add a simulation-owned virtual camera, sanitized frame corpus, real process
state-machine capture sequences, and process-specific analysis oracles. It must
not be used to delay the storage migration or expand its validation claims.

## Expected file impact by milestone

This is a planning inventory, not authorization to edit every listed file in
one slice.

| Area | Likely files |
| --- | --- |
| Contract and operator documentation | `docs/calibration_recording_store_migration_plan.md`, later `README.md` updates |
| New authoritative store | New focused module under `FreeRTOS-interface/`, exact name selected in Milestone 2 |
| Manager integration | `FreeRTOS-interface/CalibrationClasses/Model.py` |
| Capture-policy UI | `FreeRTOS-interface/CalibrationClasses/View.py` |
| Experiment paths/lifecycle | `FreeRTOS-interface/Model.py` |
| Calibration memory | `FreeRTOS-interface/CalibrationMemoryStore.py`, `CalibrationMemoryAggregator.py` |
| Audit/export | `FreeRTOS-interface/ExperimentAuditLog.py`, `CalibrationRecordExport.py`, summary/export tools |
| SIL fixtures/process/journey | `tools/sil/`, `tools/virtual_workflows/fixtures/`, registry/journey modules |
| Automated coverage | Focused unit tests plus `tests/system/` storage-contract SIL tests |

Any slice crossing UI, Controller, Model, and persistence must restate its exact
call path and reduced file list before editing. No milestone authorizes a broad
MVC refactor.

## Validation strategy

Every implementation milestone must run focused tests for its changed area and
then the repository Python suite:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

Storage-contract lifecycle tests use the existing opt-in SIL selection until
their runtime is qualified for standard selection:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle <storage-contract-test-path>
```

The exact Pi SIL command and workload are created and frozen in Milestone 1.
Remote Pi execution remains explicit and separately authorized. No storage SIL
command may connect to a physical serial port, camera, GPIO, balance, or
firmware endpoint.

Milestone-specific completion records must include:

- changed files and rationale;
- exact focused and full-suite commands/results;
- schema and fixture identities;
- retained SIL report paths where applicable;
- risk and unresolved issues;
- rollback procedure;
- confirmation that historical experiment files were not modified.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| A new directory scan recreates UI slowdown | Compact append-only index; no routine recursive scan |
| Dual stores diverge silently | Canonical payload hashes, parity fixtures, typed conflicts, and no silent application on mismatch |
| Recorder failure loses the only result | Mandatory canonical writes and fail-closed completion before writer cutover |
| Index failure hides a valid result | Result-first commit and deterministic explicit rebuild |
| JSONL truncation after power loss | Flush/`fsync`, tolerate only incomplete tail, reject interior corruption |
| Multiple IDs remain ambiguous | Separate session, process-run, update, result, head, and stock identities |
| Image policy accidentally disables structured data | No structured-data toggle; capture policy controls pixels only |
| Dataset workflows lose required images | Per-process minimum capture policy and explicit validation |
| Existing replay/analysis tools break | Preserve current run layout and diagnostic files; migrate dependencies additively |
| Migration guesses historical linkage | Report ambiguity and skip; never silently infer a destructive mapping |
| Pi performance gate is brittle | Freeze workload and tolerance from measured baseline; use target-Pi distributions and slope, not host wall time |
| Scope expands into image analysis | Explicit deferred milestone and limited storage-contract claim language |

## Milestone 0 completion record

Milestone 0 is complete when this document is reviewed as the authoritative
plan for the migration. The milestone is documentation-only:

- one new plan/contract document;
- no production, firmware, protocol, schema-on-disk, UI, or test changes;
- no historical experiment modifications;
- no hardware action.

Baseline verification performed during planning:

```text
35 passed in 3.27s
```

The targeted baseline covered the existing synthetic droplet and stream
lifecycle, calibration process recorder, and synthetic calibration application
tests. That result confirms the existing SIL and recorder foundations were
healthy at planning time; it is not evidence that the new storage contract has
been implemented.
