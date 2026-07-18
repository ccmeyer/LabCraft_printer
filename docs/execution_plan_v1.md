# Execution Plan v1

## Purpose

`execution_plan.json` is the machine-readable snapshot of an experiment's
derived execution plan. It is separate from the authored design, progress
counters, and human-readable CSV exports.

Slice 3 writes the initial prepared plan when a fresh experiment is finalized.
Authoritative plan loading and calibrated revisions remain later slices.

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
- `plan_revision` is a positive integer. Later slices will increment it when a
  calibrated execution parameter or future target changes.
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

Slice 3 does not make persisted plans authoritative on load and does not revise
plans after calibration. Those behaviors, lifecycle locking, migration, and
reset semantics remain later slices. Merely opening an experiment never writes
or migrates `execution_plan.json`.
