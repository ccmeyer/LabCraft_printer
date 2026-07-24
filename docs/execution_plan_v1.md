# Execution Plan v1

## Purpose

`execution_plan.json` is the machine-readable snapshot of an experiment's
derived execution plan. It is separate from the authored design, progress
counters, and human-readable CSV exports.

Slice 3 writes the initial prepared plan when a fresh experiment is finalized.
Slice 4 adds immutable revision history, durable execution locking, and
calibration revisions without modifying the authored design.

## Schema identity

- `schema_name`: `labcraft.execution_plan`
- `schema_version`: `1`
- UTF-8 JSON object
- Exact effective volumes are stored as JSON numbers without display rounding.
- A v1 reader rejects unknown fields in execution-critical objects.
- Unsupported schema names or versions are rejected rather than interpreted by
  fallback logic.

Dynamic keys under `stocks` and `wells` are part of the schema. Their associated
records must contain exactly the fields documented below.

## Canonical structure

```json
{
  "schema_name": "labcraft.execution_plan",
  "schema_version": 1,
  "plan_id": "f33cf5d6-2f38-4ca7-86fd-74f73baac81d",
  "plan_revision": 1,
  "state": "prepared",
  "design_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "created_at_utc": "2026-07-17T12:00:00Z",
  "updated_at_utc": "2026-07-17T12:00:00Z",
  "locked_at_utc": null,
  "lock_reason": null,
  "plate": {
    "name": "shallow-384_well_plate",
    "rows": 16,
    "columns": 24
  },
  "volume_basis": {
    "target_printed_volume_nL": 2500.0,
    "final_reaction_volume_nL": 2500.0,
    "design_optimization_tolerance_nL": 50.0
  },
  "stocks": {
    "PURE MM_1.11_x": {
      "factor_name": "PURE MM",
      "option_name": null,
      "reagent_name": "PURE MM",
      "concentration": 1.11,
      "units": "x",
      "printing_mode": "stream",
      "intended_volume_nL": 60.0,
      "effective_volume_nL": 143.59278258103592,
      "printer_head_id": null,
      "calibration_record_key": null
    }
  },
  "wells": {
    "C3": {
      "reaction_id": "R1",
      "reagents": {
        "PURE MM_1.11_x": {
          "target_dispenses": 16
        }
      },
      "expected_printed_volume_nL": 2297.4845212965747
    }
  }
}
```

## Field authority

### Plan identity and lifecycle

- `plan_id` is a canonical UUID that remains stable across revisions of one
  finalized execution plan.
- `plan_revision` is a positive integer. The first durable lock and every
  distinct applied execution calibration increment it.
- `state` is one of `prepared`, `active`, `completed`, or `aborted`.
- A `prepared` plan has null lock fields. Every other state requires a UTC lock
  timestamp and nonempty lock reason.
- `design_sha256` links the execution plan to a caller-selected canonical frozen
  design payload. Slice 1 supplies deterministic hashing but does not choose the
  design projection.

### Plate and volume basis

- Plate dimensions are positive integers. Every well ID must use uppercase plate
  notation and fall inside those dimensions.
- The target and final reaction volumes are positive finite numbers.
- The design optimization tolerance is a nonnegative finite number. It records
  design-time optimization context; later execution stages will not treat it as
  a calibrated-volume limit.

### Stocks

- A stock ID is unique within a plan and is the lookup key used by wells.
- Concentration is finite and nonnegative.
- `printing_mode` is `droplet` or `stream` in v1.
- Intended volume may be null. Effective volume is required, finite, positive,
  and never rounded for display.
- Printer-head and calibration-record references may be null before calibration.

### Wells

- A well contains a reaction ID and zero or more stock target counts.
- Target counts are nonnegative integers; booleans are not integers for schema
  purposes.
- Every referenced stock must exist in the plan.
- `expected_printed_volume_nL` must equal the sum of each target count multiplied
  by its stock's effective volume. Validation allows only a small floating-point
  comparison tolerance: `max(1e-6 nL, 1e-9 * expected volume)`.

## Strict validation policy

Readers reject:

- Unknown or missing fields.
- Duplicate JSON object keys.
- Unsupported schema names or versions.
- Invalid UUIDs, hashes, timestamps, states, printing modes, or well IDs.
- Boolean numeric values, NaN, infinity, invalid signs, and inconsistent totals.
- References to undeclared stocks.

A validation failure never causes the source document to be rewritten. Future
non-execution annotations must be introduced through a versioned, explicitly
non-authoritative field; v1 has no free-form extension container.

## Persistence

The slice 1 writer:

- Requires the parent directory to exist.
- Validates the full immutable model before writing.
- Writes a temporary file in the destination directory.
- Flushes and syncs it before atomically replacing the destination.
- Removes the temporary file after failure and leaves an existing destination
  unchanged.
- Uses deterministic sorted-key, two-space-indented JSON with a trailing newline.

## Initial creation in Slice 3

- **Finish/Apply** creates the initial plan only after reactions have been
  assigned to their final runtime wells and before progress or key files are
  generated.
- Ordinary design saves, optimization previews, initialization, duplication,
  legacy loading, and merely opening a folder do not create a plan.
- The initial plan uses a new UUID, revision `1`, state `prepared`, equal
  creation/update timestamps, null lock fields, and null calibration/head
  references.
- The design hash is calculated from the exact parsed payload already persisted
  in `experiment_design.json`. Wells and targets come from the finalized runtime
  assignment, while exact concentrations and effective volumes come from the
  stock plan rather than rounded CSV headers.
- A valid existing prepared revision-1 plan is reused byte-for-byte only when
  its design and execution content match. Invalid, active, revised, or
  conflicting files are never overwritten.

Newly finalized progress files link to their plan with this metadata envelope:

```json
"__execution__": {
  "schema_version": 1,
  "plan_id": "f33cf5d6-2f38-4ca7-86fd-74f73baac81d",
  "plan_revision": 1
}
```

The reference has exactly these three fields. Well-oriented progress readers
exclude all `__*` metadata keys from reaction iteration.

Initial plan construction and persistence fail closed. A failure prevents a
successful runtime handoff and printing, clears partially loaded runtime
assignments, and leaves existing plan files unchanged. If the plan was already
written before a later progress/key failure, it remains as a prepared snapshot
and an identical retry reuses it.

## Durable locking and revisions in Slice 4

New finalizations also persist `execution_plan_revisions/revision_000001.json`.
The directory is immutable history: filenames are zero-padded, revisions are
contiguous from 1, and an existing revision can only be reused when its parsed
content is exactly equal. `execution_plan.json` is an exact mirror of the
latest history entry.

Before an execution-affecting calibration process or an accepted print request
can issue hardware actions, a prepared plan is durably changed to active:

- revision 1 `prepared` becomes revision 2 `active`;
- the reason is `calibration_started` or `printing_started`;
- the first lock timestamp and reason never change in later revisions; and
- progress is updated to reference the active revision before hardware starts.

Nozzle focus, trajectory, and other non-volume setup do not lock a plan by
themselves. A failed or stopped calibration does not unlock an already active
plan. If revision, current-mirror, progress, or sidecar synchronization fails,
the model retains a blocking synchronization error and hardware actions remain
disabled. Immutable artifacts that were written before a later failure are
retained; an exact retry adopts them and repairs the remaining mirrors instead
of creating another revision.

Loading an active new-format plan validates the design hash, immutable history,
latest mirror, progress reference and targets, and calibration references. It
does not rewrite any artifact. Slice 5 extends this inspection into the explicit
activation and resume flow described below.

## Execution calibration sidecar

`execution_calibrations.json` uses schema
`labcraft.execution_calibrations`, version 1. Its root contains exactly the
schema identity, `plan_id`, deterministic calibration records, and manual-refuel
checks. Unknown, missing, malformed, or duplicate fields fail closed.

Calibration-record UUIDs are deterministic UUID5 values derived from the plan,
stock, printer head, source-result fingerprint, exact effective volume,
printing mode, pulse width, and pressure. Recording time is preserved but does
not alter identity. Each calibrated stock points to its record through
`calibration_record_key`; stream manual-refuel checks point to that same record
and are stored only in the sidecar.

Applying a distinct calibration creates the next immutable plan revision. It:

- verifies the unchanged `experiment_design.json` hash and frozen execution
  identities;
- rejects two-stock option calibration and any selected stock that already has
  positive printed progress;
- changes only that stock's exact effective volume, printing mode, printer-head
  reference, calibration-record reference, and the resulting target maps;
- requantizes the selected stock with the existing nearest-integral rule while
  preserving all other non-fill targets;
- recalculates fill from remaining target printed volume and clamps it to zero
  when calibrated non-fill volume is already larger; and
- recomputes exact expected well volumes without applying the design-time
  tolerance as an execution feasibility limit.

Consequently, a calibrated historical well may legitimately exceed the design
optimization limit. Progress preserves all added counts while targets and its
`__execution__` revision reference are atomically replaced. `key.csv` and
`concentration_key.csv` are regenerated from the committed plan, not by running
stock optimization. `experiment_design.json` remains byte-identical throughout
locking, calibration, manual-refuel checks, and retries.

Mixed-volume dispense segments remain later work. Legacy executions remain
non-migrating, read-only snapshots unless the user explicitly creates the
analysis-only migration copy described below; merely opening any experiment
never creates or repairs execution artifacts.

## Authoritative load and resume in Slice 5

When `execution_plan.json` exists, the application no longer regenerates an
experiment from design inputs. It treats the following as one authoritative
bundle:

- immutable plan revisions and the exact latest-plan mirror define stocks,
  concentrations, effective volumes, printing modes, wells, reaction IDs, and
  target counts;
- `progress.json` defines only the added counts at those frozen targets;
- `execution_calibrations.json` defines referenced calibration and manual-check
  evidence; and
- `execution_resume.json` defines durable command boundaries for hardware
  restart decisions.

Opening a folder performs strict, non-mutating inspection. It neither creates a
resume checkpoint nor repairs files. The editor remains locked and offers an
explicit **Activate Execution** action only when the saved bundle is internally
consistent. Activation reconstructs runtime objects with the exact saved stock
IDs, well assignments, targets, and progress, without optimization,
randomization, or design writes. Derived key CSVs may be regenerated only as an
explicit activation side effect after the frozen design hash is verified.

Positive progress without `execution_resume.json` is analysis-only because the
application cannot prove whether a hardware command was in flight when the
previous process ended. Zero-progress executions may create a clean checkpoint
during explicit activation. A pending intent is repairable only when persisted
progress proves the entire commanded count was recorded; otherwise the intent
is ambiguous and hardware resume fails closed.

### Resume checkpoint schema

`execution_resume.json` uses strict schema `labcraft.execution_resume`, version
1. Its root records the plan ID/revision, session UUID, state, active stock/head,
canonical progress hash, intent array, and UTC timestamps. Each intent records
the exact well, reaction, stock, baseline added count, commanded count, optional
32-bit command sequence, status, and timestamps. Unknown, missing, malformed,
duplicate, nonintegral, or inconsistent fields are rejected.

The intent array is a bounded recovery checkpoint, not an execution-history
log. New runtime writes retain only unresolved pending intents. After
`progress.json` durably proves a command's entire recorded count, the following
resume write retires that intent instead of retaining a completed copy. The
schema continues to accept version-1 `completed` records written by earlier
releases. Passive inspection validates those records without editing the
folder; the next explicit activation verifies every record against progress
and compacts the checkpoint in its existing activation write. If progress does
not prove a legacy completion, activation fails closed. Completed-command
history is intentionally not reconstructed elsewhere because progress and the
immutable execution plan are the authoritative durable result.

For every new-format well dispense the host:

1. atomically persists a deterministic pending intent before queuing the
   dispense command;
2. records the returned command sequence when available;
3. updates `progress.json` only in the existing command-completion handler; and
4. retires the proven intent in a third atomic resume write only after that
   progress write succeeds.

If the process stops between steps, reload classification is conservative.
Progress that includes the whole intent can repair the checkpoint during the
next explicit activation. Progress that does not include it cannot distinguish
"not executed" from "executed but not recorded" and blocks resume.

A confirmed **Stop After Well** is also a durable command boundary. After the
pause watermark is reached and the firmware queue is confirmed empty, pending
look-ahead intents with command sequences beyond that watermark are discarded
and the checkpoint becomes paused. If queue clearing is not confirmed, those
intents remain pending and resume continues to fail closed.

Before hardware starts, the loaded stock, printing mode, durable printer-head
identity, and any referenced calibration record must match the latest plan. A
previously unbound, unprinted stock is bound through a new immutable plan
revision before its first dispense. Existing bindings cannot silently change.
Calibration of an unprinted stock remains available after authoritative
activation and uses the Slice 4 revision path; stocks with positive added counts
remain immutable.

## Reset, copies, migration, and terminal states in Slice 6

Recorded dispense counts are physical facts. Progress clearing and the Reset
Single/All Array actions first classify the folder and fail before changing
files or runtime objects when it contains positive counts, recorded legacy
evidence, any finalized plan, or an invalid partial new-format bundle. Editing
such an experiment always uses **Create Editable Copy**; the original folder is
never rewritten.

Editable copies are built in a sibling staging directory and published by one
directory rename only after stock optimization and design validation succeed.
They retain authored factors, reagent identities, conditions, random/manual
assignments, and embedded uploaded reactions. Intended dispense volumes and
printing modes replace calibrated effective values when available. Progress,
stock-preparation completion, calibration/manual-check evidence, plan history,
resume state, keys, recordings, and analysis outputs do not transfer. The fresh
copy contains a normalized design, empty `progress.json`, empty
`calibration.json`, and a materialized uploaded-design CSV when applicable.
Calibration-copy requests are rejected because physical evidence cannot grant
authority to a new execution.

Recorded legacy migration is explicit and always creates a full sibling copy.
It copies historical files and raw analysis data, preserves
`experiment_design.json` byte-for-byte, reconstructs normalized progress, and
persists the deterministic legacy plan as revision 1 and the latest mirror.
Compatible calibration/manual-check evidence is converted to strict sidecar
records; incomplete evidence is omitted with a warning rather than fabricated.
No resume checkpoint is created.

`legacy_migration.json` is strict schema
`labcraft.legacy_execution_migration`, version 1. It contains the migrated plan
ID, source folder and canonical design hash, SHA-256 for every relative source
file, UTC migration time, exact code/message warnings, and the permanent
`hardware_policy` value `analysis_only`. Unknown, missing, duplicate, or
malformed fields invalidate the authoritative bundle. A valid manifest always
overrides otherwise-normal resume eligibility: migrated zero-progress, active,
completed, and aborted executions can be opened only for analysis.

Active plans may end in one immutable terminal revision. `completed` requires
every added count to equal its frozen target and a clean checkpoint with no
pending intent. A refill or successful soft stop remains active. An explicit
abandonment or Controller hard abort creates `aborted`, retains recorded counts
and intents, and marks the checkpoint `uncertain`. Terminal transitions cannot
change stocks, wells, targets, design/plate facts, or first-lock metadata, and
terminal revisions cannot have successors. Exact retries reuse the immutable
terminal revision and repair later mirrors without incrementing again.

Starting **New Experiment** is also non-destructive. It requires an idle array
runner, an empty command queue, and no printer head in the gripper, then detaches
the previous folder unchanged and clears only in-memory runtime/execution state
before creating the fresh design folder.
